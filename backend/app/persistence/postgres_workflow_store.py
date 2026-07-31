from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.domain.ai_classification import merge_semantic_attempt_result, sanitize_semantic_evidence
from app.domain.document_uploads import extend_retention_deadline, retention_decision
from app.domain.portal_access import (
    PORTAL_USERS_CLIENT_ID,
    build_portal_user_record,
    decide_portal_access,
)
from app.domain.session_auth import auth_token_public_payload, credential_public_payload, is_expired, session_public_payload
from app.domain.qnb_credentials import QnbCredentialCipher
from app.domain.workspace_review_updates import (
    apply_review_decision_to_document,
    mark_export_package_downloaded,
)
from app.persistence.workflow_store import (
    PROCESSING_ATTEMPT_MARKER_KEY,
    ProcessingAttemptConflict as ProcessingAttemptConflict,
    ResearchProfileConflict,
    _clear_directory_contents,
    _validate_reset_roots,
    matching_processing_attempt,
    processing_attempt_marker,
    research_profile_is_visible,
    simulation_input_digest,
)
from app.persistence.normalized_accounting_repository import NormalizedAccountingRepository
from app.persistence.learning_rule_repository import LearningRuleRepository
from app.persistence.protected_corpus_repository import (
    ProtectedCorpusConflict,
    ProtectedCorpusRepository,
)


ConnectFactory = Callable[[], Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def tenant_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:tenant:{value}")


def workflow_document_lock_key(
    tenant_id: object,
    client_id: str,
    document_ref: str,
) -> int:
    """Stable signed bigint key for a tenant/client/document advisory lock."""

    scope = f"{tenant_id}\x1f{client_id}\x1f{document_ref}".encode("utf-8")
    return int.from_bytes(sha256(scope).digest()[:8], "big", signed=True)


def taxpayer_uuid(tenant_id: UUID, client_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:taxpayer:{tenant_id}:{client_id}")


def normalize_nace_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_brand_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _pilot_reinitialization_roots(
    *,
    document_storage_path: Path | str,
    export_path: Path | str,
    protected_storage_path: Path | str,
) -> tuple[tuple[Path, Path, Path], list[Path]]:
    ordinary_root = Path(document_storage_path).resolve()
    export_root = Path(export_path).resolve()
    protected_root = Path(protected_storage_path).resolve()
    if len({ordinary_root, export_root, protected_root}) != 3:
        raise ValueError("unsafe_storage_root_overlap")
    _validate_reset_roots(
        document_storage_path=ordinary_root,
        export_path=export_root,
        protected_storage_path=protected_root,
    )
    inventory: list[Path] = []
    for root in (ordinary_root, export_root, protected_root):
        if root.exists() and root.is_dir():
            inventory.extend(path for path in root.rglob("*") if path.is_file())
    return (ordinary_root, export_root, protected_root), inventory


def _delete_inventoried_files(inventory: list[Path]) -> tuple[int, list[str]]:
    deleted = 0
    warnings: list[str] = []
    for path in inventory:
        try:
            if not path.exists():
                warnings.append("file_missing")
                continue
            path.unlink()
            deleted += 1
        except OSError:
            warnings.append("file_delete_failed")
    return deleted, sorted(set(warnings))


class PostgresWorkflowStore:
    """PostgreSQL store with a compatibility API and optional normalized owner."""

    def __init__(
        self,
        dsn: str,
        *,
        tenant_key: str | None = None,
        connect: ConnectFactory | None = None,
        accounting_store_target: str | None = None,
        normalized_repository: Any | None = None,
        protected_corpus_repository: Any | None = None,
    ) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL workflow store requires a database dsn")
        self.dsn = dsn
        self.tenant_key = tenant_key or os.environ.get("FISORA_TENANT_KEY", "default")
        self.tenant_id = tenant_uuid(self.tenant_key)
        self._connect_factory = connect
        self.accounting_store_target = (
            accounting_store_target
            or os.environ.get("FISORA_ACCOUNTING_STORE_TARGET", "compatibility")
        ).strip().lower()
        if self.accounting_store_target not in {"compatibility", "normalized"}:
            raise ValueError("FISORA_ACCOUNTING_STORE_TARGET must be compatibility or normalized")
        self.normalized_repository = normalized_repository
        if self.accounting_store_target == "normalized" and self.normalized_repository is None:
            self.normalized_repository = NormalizedAccountingRepository(
                connect=self._connect,
                tenant_id=self.tenant_id,
                json_value=self._json,
            )
        self.protected_corpus_repository = protected_corpus_repository or ProtectedCorpusRepository(
            connect=self._connect,
            tenant_id=self.tenant_id,
            json_value=self._json,
        )

    def create_protected_corpus(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return self.protected_corpus_repository.create_corpus(**kwargs)
        except ProtectedCorpusConflict as exc:
            raise ValueError(str(exc)) from exc

    def get_protected_corpus(self, corpus_id: str) -> dict[str, Any] | None:
        return self.protected_corpus_repository.get_corpus(corpus_id)

    def add_protected_corpus_item(self, *, item: dict[str, Any]) -> dict[str, Any]:
        enriched = {**item, "taxpayer_id": taxpayer_uuid(self.tenant_id, str(item["client_id"]))}
        try:
            return self.protected_corpus_repository.enroll_item(item=enriched)
        except ProtectedCorpusConflict as exc:
            raise ValueError(str(exc)) from exc

    def list_protected_items(self, corpus_id: str) -> list[dict[str, Any]]:
        return self.protected_corpus_repository.list_items(corpus_id)

    def protected_item_for_document(self, *, client_id: str, document_ref: str) -> dict[str, Any] | None:
        return self.protected_corpus_repository.item_for_document(
            client_id=client_id,
            document_ref=document_ref,
        )

    def append_reference_outcome(self, *, corpus_item_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.protected_corpus_repository.append_reference(
                corpus_item_id=corpus_item_id,
                outcome=outcome,
            )
        except ProtectedCorpusConflict as exc:
            raise ValueError(str(exc)) from exc

    def list_reference_outcomes(self, corpus_item_id: str) -> list[dict[str, Any]]:
        return self.protected_corpus_repository.list_references(corpus_item_id)

    def append_protected_rule(self, *, corpus_item_id: str, rule: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.protected_corpus_repository.append_rule(corpus_item_id=corpus_item_id, rule=rule)
        except ProtectedCorpusConflict as exc:
            raise ValueError(str(exc)) from exc

    def list_protected_rules(self, corpus_item_id: str) -> list[dict[str, Any]]:
        return self.protected_corpus_repository.list_rules(corpus_item_id)

    def freeze_protected_corpus(self, corpus_id: str) -> dict[str, Any]:
        try:
            return self.protected_corpus_repository.freeze_corpus(corpus_id)
        except ProtectedCorpusConflict as exc:
            raise ValueError(str(exc)) from exc

    @property
    def normalized_accounting_enabled(self) -> bool:
        return self.accounting_store_target == "normalized"

    def upsert_client(self, *, client_id: str, profile: dict[str, Any], onboarding: dict[str, Any]) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            "client_id": client_id,
            "profile": profile,
            "onboarding": onboarding,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        self._ensure_taxpayer(client_id=client_id, profile=profile)
        existing = self._get_record(client_id, "client", client_id)
        if existing:
            record["created_at"] = existing.get("created_at", timestamp)
        return self._upsert_record(client_id, "client", client_id, record)

    def list_clients(self) -> list[dict[str, Any]]:
        return [deepcopy(row["payload"]) for row in self._list_records("client")]

    def replace_chart_accounts(self, *, client_id: str, accounts: list[dict[str, Any]]) -> dict[str, Any]:
        timestamp = utc_now()
        if self.normalized_accounting_enabled:
            taxpayer_id = taxpayer_uuid(self.tenant_id, client_id)
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        update chart_accounts
                        set is_active = false, updated_at = now()
                        where tenant_id = %s and taxpayer_id = %s
                        """,
                        (self.tenant_id, taxpayer_id),
                    )
                    for account in accounts:
                        normalized_code = str(
                            account.get("normalized_account_code")
                            or account.get("raw_account_code")
                            or account.get("code")
                            or ""
                        ).strip()
                        if not normalized_code:
                            continue
                        raw_code = str(account.get("raw_account_code") or normalized_code).strip()
                        account_id = uuid5(
                            NAMESPACE_URL,
                            f"fisora:chart-account:{self.tenant_id}:{client_id}:{normalized_code}",
                        )
                        cursor.execute(
                            """
                            insert into chart_accounts (
                                id, tenant_id, taxpayer_id, raw_account_code,
                                normalized_account_code, account_name,
                                is_detail_account, tax_id, tax_office, iban, is_active
                            )
                            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                            on conflict (tenant_id, taxpayer_id, normalized_account_code)
                            do update set
                                raw_account_code = excluded.raw_account_code,
                                account_name = excluded.account_name,
                                is_detail_account = excluded.is_detail_account,
                                tax_id = excluded.tax_id,
                                tax_office = excluded.tax_office,
                                iban = excluded.iban,
                                is_active = true,
                                updated_at = now()
                            """,
                            (
                                account_id,
                                self.tenant_id,
                                taxpayer_id,
                                raw_code,
                                normalized_code,
                                str(account.get("account_name") or account.get("name") or normalized_code),
                                bool(account.get("is_detail_account")),
                                str(account.get("tax_id") or "") or None,
                                str(account.get("tax_office") or "") or None,
                                str(account.get("iban") or "") or None,
                            ),
                        )
        record = {
            "client_id": client_id,
            "account_count": len(accounts),
            "accounts": accounts,
            "updated_at": timestamp,
        }
        existing = self._get_record(client_id, "chart_accounts", client_id)
        if existing:
            record["created_at"] = existing.get("created_at", timestamp)
        else:
            record["created_at"] = timestamp
        return self._upsert_record(client_id, "chart_accounts", client_id, record)

    def upsert_portal_user(
        self,
        *,
        user_id: str,
        display_name: str,
        role: str,
        allowed_client_ids: list[str],
    ) -> dict[str, Any]:
        if not user_id.strip():
            raise ValueError("user_id is required")
        timestamp = utc_now()
        existing = self._get_record(PORTAL_USERS_CLIENT_ID, "portal_user", user_id)
        record = {
            **(existing or {}),
            **build_portal_user_record(
                user_id=user_id,
                display_name=display_name,
                role=role,
                allowed_client_ids=allowed_client_ids,
            ),
            "updated_at": timestamp,
        }
        record.setdefault("created_at", timestamp)
        return self._upsert_record(PORTAL_USERS_CLIENT_ID, "portal_user", user_id, record)

    def get_portal_user(self, user_id: str) -> dict[str, Any] | None:
        return self._get_record(PORTAL_USERS_CLIENT_ID, "portal_user", user_id)

    def replace_client_portal_user(
        self,
        *,
        client_id: str,
        old_user_id: str,
        new_user_id: str,
        display_name: str = "",
    ) -> dict[str, Any]:
        normalized_client_id = client_id.strip()
        normalized_old_user_id = old_user_id.strip()
        normalized_new_user_id = new_user_id.strip()
        if not normalized_client_id:
            raise ValueError("client_id is required")
        if not normalized_new_user_id:
            raise ValueError("new_user_id is required")
        if self._get_record(normalized_client_id, "client", normalized_client_id) is None:
            raise ValueError("client not found")

        timestamp = utc_now()
        old_user = self._get_record(PORTAL_USERS_CLIENT_ID, "portal_user", normalized_old_user_id) if normalized_old_user_id else None
        new_user = self._get_record(PORTAL_USERS_CLIENT_ID, "portal_user", normalized_new_user_id) or {}
        allowed_client_ids = list(dict.fromkeys([*(new_user.get("allowed_client_ids") or []), normalized_client_id]))
        portal_user = {
            **new_user,
            **build_portal_user_record(
                user_id=normalized_new_user_id,
                display_name=str(
                    display_name
                    or new_user.get("display_name")
                    or (old_user or {}).get("display_name")
                    or normalized_new_user_id
                ),
                role="client_user",
                allowed_client_ids=allowed_client_ids,
            ),
            "updated_at": timestamp,
        }
        portal_user.setdefault("created_at", timestamp)
        stored = self._upsert_record(PORTAL_USERS_CLIENT_ID, "portal_user", normalized_new_user_id, portal_user)

        old_user_removed = False
        if normalized_old_user_id and normalized_old_user_id != normalized_new_user_id and old_user:
            remaining_allowed = [
                existing_client_id
                for existing_client_id in old_user.get("allowed_client_ids") or []
                if existing_client_id != normalized_client_id
            ]
            if remaining_allowed:
                old_user["allowed_client_ids"] = remaining_allowed
                old_user["updated_at"] = timestamp
                self._upsert_record(PORTAL_USERS_CLIENT_ID, "portal_user", normalized_old_user_id, old_user)
            else:
                self._delete_portal_user_with_auth(normalized_old_user_id)
                old_user_removed = True
        return {
            "client_id": normalized_client_id,
            "old_user_id": normalized_old_user_id,
            "new_user_id": normalized_new_user_id,
            "old_user_removed": old_user_removed,
            "portal_user": stored,
        }

    def verify_portal_access(self, *, client_id: str, user_id: str) -> dict[str, Any]:
        decision = decide_portal_access(
            portal_user=self._get_record(PORTAL_USERS_CLIENT_ID, "portal_user", user_id),
            client_exists=self._get_record(client_id, "client", client_id) is not None,
            client_id=client_id,
        )
        return {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "role": decision.role,
            "client_id": client_id,
            "user_id": user_id,
        }

    def set_auth_password(self, *, user_id: str, password_hash: str) -> dict[str, Any]:
        timestamp = utc_now()
        existing = self._get_record(PORTAL_USERS_CLIENT_ID, "auth_credential", user_id) or {}
        record = {
            **existing,
            "user_id": user_id,
            "password_hash": password_hash,
            "updated_at": timestamp,
        }
        record.setdefault("created_at", timestamp)
        stored = self._upsert_record(PORTAL_USERS_CLIENT_ID, "auth_credential", user_id, record)
        return credential_public_payload(stored)

    def get_auth_password_hash(self, *, user_id: str) -> str:
        credential = self._get_record(PORTAL_USERS_CLIENT_ID, "auth_credential", user_id) or {}
        return str(credential.get("password_hash") or "")

    def create_auth_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: str,
        session_kind: str = "password",
        delegated_by: str = "",
        delegated_client_id: str = "",
    ) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            "session_id": str(uuid4()),
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "session_kind": session_kind,
            "delegated_by": delegated_by,
            "delegated_client_id": delegated_client_id,
            "revoked_at": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        stored = self._upsert_record(PORTAL_USERS_CLIENT_ID, "auth_session", token_hash, record)
        return session_public_payload(stored)

    def resolve_auth_session(self, *, token_hash: str) -> dict[str, Any]:
        record = self._get_record(PORTAL_USERS_CLIENT_ID, "auth_session", token_hash)
        if not record:
            return {"valid": False, "reason": "session_not_found"}
        if record.get("revoked_at"):
            return {"valid": False, "reason": "session_revoked", "user_id": record.get("user_id", "")}
        if is_expired(str(record.get("expires_at") or "")):
            return {"valid": False, "reason": "session_expired", "user_id": record.get("user_id", "")}
        return {"valid": True, "reason": "session_valid", **session_public_payload(record)}

    def revoke_auth_session(self, *, token_hash: str) -> dict[str, Any]:
        record = self._get_record(PORTAL_USERS_CLIENT_ID, "auth_session", token_hash)
        if not record:
            return {"revoked": False, "reason": "session_not_found"}
        record["revoked_at"] = utc_now()
        record["updated_at"] = record["revoked_at"]
        stored = self._upsert_record(PORTAL_USERS_CLIENT_ID, "auth_session", token_hash, record)
        return {"revoked": True, "reason": "session_revoked", **session_public_payload(stored)}

    def create_auth_token(
        self,
        *,
        purpose: str,
        user_id: str,
        token_hash: str,
        expires_at: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            "token_id": str(uuid4()),
            "purpose": purpose,
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "used_at": "",
            "payload": payload or {},
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        stored = self._upsert_record(PORTAL_USERS_CLIENT_ID, "auth_token", token_hash, record)
        return auth_token_public_payload(stored)

    def resolve_auth_token(self, *, purpose: str, token_hash: str) -> dict[str, Any]:
        record = self._get_record(PORTAL_USERS_CLIENT_ID, "auth_token", token_hash)
        if not record or record.get("purpose") != purpose:
            return {"valid": False, "reason": "token_not_found"}
        if record.get("used_at"):
            return {"valid": False, "reason": "token_used", "user_id": record.get("user_id", "")}
        if is_expired(str(record.get("expires_at") or "")):
            return {"valid": False, "reason": "token_expired", "user_id": record.get("user_id", "")}
        return {"valid": True, "reason": "token_valid", **auth_token_public_payload(record), "payload": deepcopy(record.get("payload") or {})}

    def mark_auth_token_used(self, *, token_hash: str) -> dict[str, Any]:
        record = self._get_record(PORTAL_USERS_CLIENT_ID, "auth_token", token_hash)
        if not record:
            return {"used": False, "reason": "token_not_found"}
        record["used_at"] = utc_now()
        record["updated_at"] = record["used_at"]
        stored = self._upsert_record(PORTAL_USERS_CLIENT_ID, "auth_token", token_hash, record)
        return {"used": True, "reason": "token_used", **auth_token_public_payload(stored)}

    def record_ai_usage(self, *, client_id: str, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id") or uuid4())
        record = {
            **event,
            "event_id": event_id,
            "client_id": client_id,
        }
        return self._upsert_record(client_id, "ai_usage_event", event_id, record)

    def list_ai_usage(self, *, client_id: str) -> list[dict[str, Any]]:
        return self._payloads(client_id, "ai_usage_event")

    def record_ai_capacity_snapshot(self, *, provider: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        key = str(provider or "").strip().lower()
        if not key:
            raise ValueError("provider is required")
        record = {
            **snapshot,
            "provider": key,
            "updated_at": utc_now(),
        }
        return self._upsert_record("__system__", "ai_capacity_snapshot", key, record)

    def latest_ai_capacity_snapshots(self) -> dict[str, dict[str, Any]]:
        return {
            str(row["record_key"]): deepcopy(row["payload"])
            for row in self._list_records("ai_capacity_snapshot", client_id="__system__")
        }

    def reset_test_data(
        self,
        *,
        document_storage_path: Path | str,
        export_path: Path | str,
        protected_storage_path: Path | str,
        delete_files: bool = True,
    ) -> dict[str, Any]:
        if delete_files:
            _validate_reset_roots(
                document_storage_path=document_storage_path,
                export_path=export_path,
                protected_storage_path=protected_storage_path,
            )
        self._ensure_tenant()
        protected_counts = self.protected_corpus_repository.reset_preservation_counts()
        deleted_record_count = 0
        deleted_portal_user_count = 0
        deleted_client_count = 0
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select record_key
                    from workflow_records
                    where tenant_id = %s
                      and client_id = %s
                      and record_type = 'portal_user'
                      and lower(payload->>'role') in ('accountant', 'admin')
                    order by record_key asc
                    """,
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID),
                )
                preserved_user_ids = [str(row[0]) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    select count(*)
                    from workflow_records
                    where tenant_id = %s and record_type = 'client'
                    """,
                    (self.tenant_id,),
                )
                deleted_client_count = int(cursor.fetchone()[0] or 0)
                for table_name in (
                    "learning_rules",
                    "review_decisions",
                    "export_batches",
                    "journal_entry_lines",
                    "journal_entries",
                    "counterparties",
                    "invoice_lines",
                    "documents",
                    "chart_accounts",
                    "chart_account_imports",
                    "portal_user_client_access",
                    "taxpayers",
                ):
                    cursor.execute(f"delete from {table_name} where tenant_id = %s", (self.tenant_id,))
                cursor.execute(
                    """
                    delete from workflow_records
                    where tenant_id = %s and client_id <> %s
                    """,
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID),
                )
                deleted_record_count += cursor.rowcount
                cursor.execute(
                    """
                    delete from workflow_records
                    where tenant_id = %s
                      and client_id = %s
                      and record_type = 'portal_user'
                      and not (lower(payload->>'role') in ('accountant', 'admin'))
                    """,
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID),
                )
                deleted_portal_user_count = cursor.rowcount
                deleted_record_count += cursor.rowcount
                if preserved_user_ids:
                    cursor.execute(
                        """
                        delete from workflow_records
                        where tenant_id = %s
                          and client_id = %s
                          and record_type = 'auth_credential'
                          and not (record_key = any(%s))
                        """,
                        (self.tenant_id, PORTAL_USERS_CLIENT_ID, preserved_user_ids),
                    )
                else:
                    cursor.execute(
                        """
                        delete from workflow_records
                        where tenant_id = %s
                          and client_id = %s
                          and record_type = 'auth_credential'
                        """,
                        (self.tenant_id, PORTAL_USERS_CLIENT_ID),
                    )
                deleted_record_count += cursor.rowcount
                cursor.execute(
                    """
                    delete from workflow_records
                    where tenant_id = %s
                      and client_id = %s
                      and record_type in ('auth_session', 'auth_token')
                    """,
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID),
                )
                deleted_record_count += cursor.rowcount
                cursor.execute(
                    """
                    delete from workflow_records
                    where tenant_id = %s
                      and client_id = %s
                      and record_type not in ('portal_user', 'auth_credential')
                    """,
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID),
                )
                deleted_record_count += cursor.rowcount
        deleted_file_count = 0
        if delete_files:
            deleted_file_count += _clear_directory_contents(Path(document_storage_path))
            deleted_file_count += _clear_directory_contents(Path(export_path))
        return {
            "reset": True,
            "deleted_client_count": deleted_client_count,
            "deleted_portal_user_count": deleted_portal_user_count,
            "deleted_record_count": deleted_record_count,
            "deleted_file_count": deleted_file_count,
            "preserved_portal_user_count": len(preserved_user_ids),
            "preserved_user_ids": preserved_user_ids,
            **protected_counts,
        }

    def _pilot_reinitialization_snapshot(self, cursor: Any) -> dict[str, Any]:
        preserved_user_ids: list[str] = []
        cursor.execute(
            """
            select record_key from workflow_records
            where tenant_id = %s and client_id = %s and record_type = 'portal_user'
              and lower(payload->>'role') in ('accountant', 'admin')
            order by record_key asc
            """,
            (self.tenant_id, PORTAL_USERS_CLIENT_ID),
        )
        preserved_user_ids = [str(row[0]) for row in cursor.fetchall()]
        operational_tables = (
            "taxpayers", "documents", "source_files", "document_sources",
            "processing_jobs", "processing_attempts", "ai_attempts", "invoice_lines",
            "counterparties", "journal_entries", "journal_entry_lines", "journal_revisions",
            "journal_revision_lines", "journal_line_allocations", "review_decisions",
            "export_batches", "export_batch_items", "learning_rules", "chart_accounts",
            "chart_account_imports", "workflow_events", "document_identities",
            "provider_document_links", "external_status_events", "document_safety_holds",
        )
        operational_ids: list[str] = []
        counts: dict[str, int] = {}
        for table_name in operational_tables:
            cursor.execute(f"select id::text from {table_name} where tenant_id = %s order by id", (self.tenant_id,))
            rows = [str(row[0]) for row in cursor.fetchall()]
            operational_ids.extend(f"{table_name}:{value}" for value in rows)
            counts[table_name] = len(rows)
        cursor.execute(
            """
            select id::text from workflow_records
            where tenant_id = %s and not (
                client_id = %s and record_type in ('portal_user', 'auth_credential')
                and record_key = any(%s)
            ) order by id
            """,
            (self.tenant_id, PORTAL_USERS_CLIENT_ID, preserved_user_ids or [""]),
        )
        operational_ids.extend(f"workflow_records:{row[0]}" for row in cursor.fetchall())
        protected_ids: dict[str, list[str]] = {}
        for table_name in ("protected_corpora", "protected_corpus_items", "reference_outcome_versions", "protected_rule_versions"):
            cursor.execute(f"select id::text from {table_name} where tenant_id = %s order by id", (self.tenant_id,))
            protected_ids[table_name] = [str(row[0]) for row in cursor.fetchall()]
        fingerprint_payload = {
            "tenant_id": str(self.tenant_id),
            "operational_ids": sorted(operational_ids),
            "protected_corpus_ids": sorted(protected_ids["protected_corpora"]),
            "protected_item_ids": sorted(protected_ids["protected_corpus_items"]),
            "protected_rule_ids": sorted(protected_ids["protected_rule_versions"] + protected_ids["reference_outcome_versions"]),
            "preserved_user_ids": sorted(preserved_user_ids),
        }
        preview_fingerprint = sha256(json.dumps(fingerprint_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "preview_fingerprint": preview_fingerprint,
            "operational_document_count": counts.get("documents", 0),
            "operational_client_count": counts.get("taxpayers", 0),
            "operational_record_count": len(operational_ids),
            "protected_corpus_count": len(protected_ids["protected_corpora"]),
            "protected_item_count": len(protected_ids["protected_corpus_items"]),
            "protected_rule_count": len(protected_ids["protected_rule_versions"]),
            "protected_reference_count": len(protected_ids["reference_outcome_versions"]),
            "preserved_accountant_admin_count": len(preserved_user_ids),
        }

    def preview_pilot_reinitialization(self) -> dict[str, Any]:
        if not self.normalized_accounting_enabled:
            raise ValueError("normalized_accounting_required")
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("select id from tenants where id = %s for update", (self.tenant_id,))
                return self._pilot_reinitialization_snapshot(cursor)

    def reinitialize_pilot_data(
        self, *, actor_user_id: str, preview_fingerprint: str,
        document_storage_path: Path | str, export_path: Path | str,
        protected_storage_path: Path | str, delete_files: bool = True,
    ) -> dict[str, Any]:
        if not self.normalized_accounting_enabled:
            raise ValueError("normalized_accounting_required")
        inventory: list[Path] = []
        if delete_files:
            _, inventory = _pilot_reinitialization_roots(
                document_storage_path=document_storage_path,
                export_path=export_path,
                protected_storage_path=protected_storage_path,
            )
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("select id from tenants where id = %s for update", (self.tenant_id,))
                before = self._pilot_reinitialization_snapshot(cursor)
                if str(before["preview_fingerprint"]) != str(preview_fingerprint):
                    raise ValueError("pilot_reinitialization_preview_stale")
                cursor.execute("update provider_document_links set current_status_event_id = null where tenant_id = %s", (self.tenant_id,))
                for table_name in (
                    "protected_rule_versions", "reference_outcome_versions", "protected_corpus_items", "protected_corpora", "workflow_events",
                    "document_safety_holds", "external_status_events", "provider_document_links", "document_identities",
                    "export_batch_items", "export_batches", "review_decisions", "journal_line_allocations", "journal_revision_lines",
                    "journal_revisions", "journal_entry_lines", "journal_entries", "ai_attempts", "processing_attempts",
                    "processing_jobs", "invoice_lines", "document_sources", "source_files", "documents", "counterparties",
                    "learning_rules", "chart_accounts", "chart_account_imports", "portal_user_client_access",
                    "taxpayers",
                ):
                    cursor.execute(f"delete from {table_name} where tenant_id = %s", (self.tenant_id,))
                cursor.execute("delete from portal_users where tenant_id = %s and lower(role) not in ('accountant', 'admin')", (self.tenant_id,))
                cursor.execute("delete from workflow_records where tenant_id = %s and client_id <> %s", (self.tenant_id, PORTAL_USERS_CLIENT_ID))
                cursor.execute("""delete from workflow_records where tenant_id = %s and client_id = %s
                    and record_type = 'portal_user' and lower(payload->>'role') not in ('accountant', 'admin')""", (self.tenant_id, PORTAL_USERS_CLIENT_ID))
                cursor.execute("delete from workflow_records where tenant_id = %s and client_id = %s and record_type in ('auth_session', 'auth_token')", (self.tenant_id, PORTAL_USERS_CLIENT_ID))
                cursor.execute("""delete from workflow_records where tenant_id = %s and client_id = %s
                    and record_type = 'auth_credential' and record_key not in (
                        select record_key from workflow_records where tenant_id = %s and client_id = %s
                          and record_type = 'portal_user' and lower(payload->>'role') in ('accountant', 'admin'))""",
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID, self.tenant_id, PORTAL_USERS_CLIENT_ID))
                cursor.execute("delete from workflow_records where tenant_id = %s and client_id = %s and record_type not in ('portal_user', 'auth_credential')", (self.tenant_id, PORTAL_USERS_CLIENT_ID))
        deleted_file_count = 0
        warning_categories: list[str] = []
        if delete_files:
            deleted_file_count, warning_categories = _delete_inventoried_files(inventory)
        after = self.preview_pilot_reinitialization()
        self.record_operation_event(
            client_id="__system__",
            event={
                "event_type": "pilot_reinitialization", "status": "completed", "actor": actor_user_id,
                "created_at": utc_now(),
                "metadata": {
                    "preview_fingerprint": preview_fingerprint,
                    "pre_counts": {key: value for key, value in before.items() if key.endswith("count")},
                    "post_counts": {key: value for key, value in after.items() if key.endswith("count")},
                },
            },
        )
        return {
            **after,
            "remaining_operational_document_count": after["operational_document_count"],
            "remaining_protected_corpus_count": after["protected_corpus_count"],
            "remaining_protected_rule_count": after["protected_rule_count"],
            "deleted_file_count": deleted_file_count,
            "file_delete_warning_count": len(warning_categories),
            "file_delete_warning_categories": warning_categories,
        }

    def preview_test_data_reset(self) -> dict[str, Any]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select
                      count(*) filter (where record_type = 'client'),
                      count(*) filter (where record_type = 'uploaded_document'),
                      count(*) filter (where record_type = 'review_decision')
                    from workflow_records where tenant_id = %s
                    """,
                    (self.tenant_id,),
                )
                row = cursor.fetchone()
        return {
            "reset": False,
            "preview": True,
            "deleted_client_count": int(row[0] or 0),
            "deleted_uploaded_document_count": int(row[1] or 0),
            "deleted_review_decision_count": int(row[2] or 0),
            **self.protected_corpus_repository.reset_preservation_counts(),
        }

    def record_operation_event(self, *, client_id: str, event: dict[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id") or uuid4())
        record = {
            **event,
            "event_id": event_id,
            "client_id": client_id,
        }
        return self._upsert_record(client_id, "operation_event", event_id, record)

    def list_operation_events(self, *, client_id: str, limit: int = 50) -> list[dict[str, Any]]:
        events = self._payloads(client_id, "operation_event")
        return events[-max(limit, 1):]

    def save_qnb_connection(self, *, client_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        existing = self._get_record(client_id, "qnb_connection", client_id) or {}
        timestamp = utc_now()
        record = {
            **existing,
            **connection,
            "client_id": client_id,
            "provider": connection.get("provider") or "qnb_esolutions",
            "updated_at": timestamp,
        }
        raw_password = str(record.pop("password", "") or "")
        if raw_password and not record.get("credential_ciphertext"):
            record["credential_ciphertext"] = QnbCredentialCipher.from_env().encrypt(raw_password)
        record.setdefault("created_at", timestamp)
        return self._upsert_record(client_id, "qnb_connection", client_id, record)

    def get_qnb_connection(self, *, client_id: str) -> dict[str, Any] | None:
        return self._get_record(client_id, "qnb_connection", client_id)

    def save_qnb_sync_run(self, *, client_id: str, sync_run: dict[str, Any]) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            **sync_run,
            "client_id": client_id,
            "updated_at": timestamp,
        }
        record.setdefault("sync_run_id", str(uuid4()))
        record.setdefault("created_at", timestamp)
        return self._upsert_record(client_id, "qnb_sync_run", str(record["sync_run_id"]), record)

    def list_qnb_sync_runs(self, *, client_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._payloads(client_id, "qnb_sync_run")
        return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)[:max(limit, 1)]

    def enqueue_qnb_sync_request(
        self,
        *,
        client_id: str,
        start_date: str = "",
        end_date: str = "",
        requested_by: str = "",
    ) -> dict[str, Any]:
        timestamp = utc_now()
        request_id = str(uuid4())
        record = {
            "request_id": request_id,
            "client_id": client_id,
            "start_date": start_date,
            "end_date": end_date,
            "requested_by": requested_by,
            "status": "queued",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        return self._upsert_record(
            client_id,
            "qnb_sync_request",
            request_id,
            record,
        )

    def claim_next_qnb_sync_request(
        self,
        *,
        worker_id: str,
        now: str,
        lease_expires_at: str,
    ) -> dict[str, Any] | None:
        self._ensure_tenant()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, payload
                    from workflow_records
                    where tenant_id = %s and record_type = 'qnb_sync_request'
                      and (
                        payload->>'status' = 'queued'
                        or (
                          payload->>'status' = 'processing'
                          and coalesce(payload->>'lease_expires_at', '') <= %s
                        )
                      )
                    order by created_at asc
                    for update skip locked
                    limit 1
                    """,
                    (self.tenant_id, now),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                request = dict(row[1] or {})
                request.update(
                    {
                        "status": "processing",
                        "lease_owner": worker_id,
                        "lease_token": str(uuid4()),
                        "lease_expires_at": lease_expires_at,
                        "updated_at": utc_now(),
                    }
                )
                cursor.execute(
                    "update workflow_records set payload = %s, updated_at = now() where id = %s",
                    (self._json(request), row[0]),
                )
                return request

    def complete_qnb_sync_request(
        self,
        *,
        client_id: str,
        request_id: str,
        worker_id: str,
        lease_token: str,
        status: str,
        result: dict[str, Any],
    ) -> bool:
        self._ensure_tenant()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'qnb_sync_request' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, request_id),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                request = dict(row[1] or {})
                if (
                    request.get("lease_owner") != worker_id
                    or request.get("lease_token") != lease_token
                ):
                    return False
                request.update(
                    {
                        "status": status,
                        "result": result,
                        "lease_owner": "",
                        "lease_token": "",
                        "lease_expires_at": "",
                        "completed_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                )
                cursor.execute(
                    "update workflow_records set payload = %s, updated_at = now() where id = %s",
                    (self._json(request), row[0]),
                )
                return True

    def save_qnb_sync_policy(self, *, client_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        existing = self._get_record(client_id, "qnb_sync_policy", client_id) or {}
        timestamp = utc_now()
        record = {**existing, **policy, "client_id": client_id, "updated_at": timestamp}
        record.setdefault("created_at", timestamp)
        return self._upsert_record(client_id, "qnb_sync_policy", client_id, record)

    def get_qnb_sync_policy(self, *, client_id: str) -> dict[str, Any] | None:
        return self._get_record(client_id, "qnb_sync_policy", client_id)

    def claim_due_qnb_sync_policy(self, *, worker_id: str, now: str, lease_expires_at: str) -> dict[str, Any] | None:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, payload from workflow_records
                    where tenant_id = %s and record_type = 'qnb_sync_policy'
                      and coalesce((payload->>'enabled')::boolean, false) = true
                      and coalesce(payload->>'next_run_at', '') <= %s
                      and coalesce(payload->>'lease_expires_at', '') <= %s
                    order by payload->>'next_run_at'
                    for update skip locked limit 1
                    """,
                    (self.tenant_id, now, now),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                record = dict(row[1] or {})
                record.update(
                    {
                        "lease_owner": worker_id,
                        "lease_token": str(uuid4()),
                        "lease_expires_at": lease_expires_at,
                        "last_attempt_at": now,
                    }
                )
                cursor.execute("update workflow_records set payload = %s, updated_at = now() where id = %s", (self._json(record), row[0]))
                return record

    def renew_qnb_sync_policy_lease(
        self,
        *,
        client_id: str,
        worker_id: str,
        lease_token: str,
        lease_expires_at: str,
    ) -> bool:
        self._ensure_tenant()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'qnb_sync_policy' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, client_id),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                policy = dict(row[1] or {})
                if (
                    policy.get("lease_owner") != worker_id
                    or policy.get("lease_token") != lease_token
                ):
                    return False
                policy["lease_expires_at"] = lease_expires_at
                policy["lease_renewed_at"] = utc_now()
                cursor.execute(
                    "update workflow_records set payload = %s, updated_at = now() where id = %s",
                    (self._json(policy), row[0]),
                )
                return True

    def complete_qnb_sync_policy(
        self,
        *,
        client_id: str,
        worker_id: str,
        lease_token: str,
        updates: dict[str, Any],
    ) -> bool:
        self._ensure_tenant()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'qnb_sync_policy' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, client_id),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                policy = dict(row[1] or {})
                if (
                    policy.get("lease_owner") != worker_id
                    or policy.get("lease_token") != lease_token
                ):
                    return False
                policy.update(updates)
                policy.update(
                    {
                        "lease_owner": "",
                        "lease_token": "",
                        "lease_expires_at": "",
                    }
                )
                cursor.execute(
                    "update workflow_records set payload = %s, updated_at = now() where id = %s",
                    (self._json(policy), row[0]),
                )
                return True

    def get_qnb_sync_cursor(self, *, client_id: str) -> str:
        record = self._get_record(client_id, "qnb_sync_cursor", client_id) or {}
        return str(record.get("cursor") or "")

    def save_qnb_sync_cursor(self, *, client_id: str, cursor: str) -> str:
        self._upsert_record(
            client_id,
            "qnb_sync_cursor",
            client_id,
            {"client_id": client_id, "cursor": str(cursor or ""), "updated_at": utc_now()},
        )
        return str(cursor or "")

    def claim_qnb_document_identity(
        self,
        *,
        client_id: str,
        identity_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        self._ensure_tenant()
        record = {
            "client_id": client_id,
            "identity_key": identity_key,
            "metadata": metadata or {},
            "claimed_at": utc_now(),
        }
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    insert into workflow_records (
                        id, tenant_id, client_id, record_type, record_key, payload
                    )
                    values (%s, %s, %s, 'qnb_document_identity', %s, %s)
                    on conflict (tenant_id, client_id, record_type, record_key) do nothing
                    returning id
                    """,
                    (uuid4(), self.tenant_id, client_id, identity_key, self._json(record)),
                )
                return cursor.fetchone() is not None

    def release_qnb_document_identity(self, *, client_id: str, identity_key: str) -> None:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    delete from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'qnb_document_identity' and record_key = %s
                    """,
                    (self.tenant_id, client_id, identity_key),
                )

    def save_qnb_outgoing_invoice(self, *, client_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
        oid = str(invoice.get("document_oid") or "")
        if not oid:
            raise ValueError("QNB outgoing document OID is required")
        existing = self._get_record(client_id, "qnb_outgoing_invoice", oid) or {}
        return self._upsert_record(client_id, "qnb_outgoing_invoice", oid, {**existing, **invoice, "client_id": client_id})

    def get_qnb_outgoing_invoice(self, *, client_id: str, document_oid: str) -> dict[str, Any] | None:
        return self._get_record(client_id, "qnb_outgoing_invoice", document_oid)

    def list_qnb_outgoing_invoices(self, *, client_id: str) -> list[dict[str, Any]]:
        return self._payloads(client_id, "qnb_outgoing_invoice")

    def append_qnb_outgoing_status_snapshot(self, *, client_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._upsert_record(
            client_id, "qnb_outgoing_status_snapshot", str(snapshot["snapshot_id"]), {**snapshot, "client_id": client_id}
        )

    def append_qnb_incoming_status_snapshot(self, *, client_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._upsert_record(
            client_id, "qnb_incoming_status_snapshot", str(snapshot["snapshot_id"]), {**snapshot, "client_id": client_id}
        )

    def record_qnb_incoming_status(
        self,
        *,
        client_id: str,
        document_ref: str,
        ettn: str,
        event_key: str,
        normalized_status: str,
        response_code: str,
        response_detail: str,
        cancelled_at: str,
        checked_at: str,
    ) -> dict[str, Any]:
        blocking_statuses = {"rejected", "cancelled", "unknown"}
        client = self._get_record(client_id, "client", client_id) or {}
        profile = client.get("profile") if isinstance(client.get("profile"), dict) else {}
        self._ensure_taxpayer(
            client_id=client_id,
            profile=profile or {"client_id": client_id},
        )
        taxpayer_id = taxpayer_uuid(self.tenant_id, client_id)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id
                    from documents
                    where tenant_id = %s and taxpayer_id = %s and source_ref = %s
                    for update
                    """,
                    (self.tenant_id, taxpayer_id, document_ref),
                )
                document_row = cursor.fetchone()
                if not document_row:
                    raise ValueError("document_not_found")
                document_id = document_row[0]
                cursor.execute(
                    """
                    insert into provider_document_links (
                        id, tenant_id, taxpayer_id, document_id, provider,
                        external_identity, current_status
                    )
                    values (%s, %s, %s, %s, 'qnb_esolutions', %s, %s)
                    on conflict (tenant_id, taxpayer_id, provider, external_identity)
                    do update set document_id = excluded.document_id, updated_at = now()
                    returning id
                    """,
                    (
                        uuid4(),
                        self.tenant_id,
                        taxpayer_id,
                        document_id,
                        ettn,
                        normalized_status,
                    ),
                )
                provider_link_id = cursor.fetchone()[0]
                status_event_id = uuid4()
                cursor.execute(
                    """
                    insert into external_status_events (
                        id, tenant_id, taxpayer_id, document_id, provider_link_id,
                        event_key, external_status, observed_at, provider_payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (tenant_id, taxpayer_id, provider_link_id, event_key)
                    do update set event_key = excluded.event_key
                    returning id
                    """,
                    (
                        status_event_id,
                        self.tenant_id,
                        taxpayer_id,
                        document_id,
                        provider_link_id,
                        event_key,
                        normalized_status,
                        checked_at,
                        self._json(
                            {
                                "response_code": response_code,
                                "response_detail": response_detail,
                                "cancelled_at": cancelled_at,
                            }
                        ),
                    ),
                )
                status_event_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    update provider_document_links
                    set current_status = %s, current_status_event_id = %s, updated_at = now()
                    where id = %s
                    """,
                    (normalized_status, status_event_id, provider_link_id),
                )
                cursor.execute(
                    """
                    select id, hold_code, created_at, trigger_event_id
                    from document_safety_holds
                    where tenant_id = %s and taxpayer_id = %s and document_id = %s
                      and resolved_at is null
                    order by created_at asc
                    limit 1
                    for update
                    """,
                    (self.tenant_id, taxpayer_id, document_id),
                )
                hold_row = cursor.fetchone()
                if normalized_status in blocking_statuses and hold_row is None:
                    hold_id = uuid4()
                    hold_code = f"qnb_status_{normalized_status}"
                    cursor.execute(
                        """
                        insert into document_safety_holds (
                            id, tenant_id, taxpayer_id, document_id,
                            hold_code, trigger_event_id
                        )
                        values (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            hold_id,
                            self.tenant_id,
                            taxpayer_id,
                            document_id,
                            hold_code,
                            status_event_id,
                        ),
                    )
                    hold_row = (
                        hold_id,
                        hold_code,
                        checked_at,
                        status_event_id,
                    )
                automation_hold = hold_row is not None
                hold_code = str(hold_row[1]) if hold_row else ""
                if hold_row:
                    self._upsert_record_with_cursor(
                        cursor,
                        client_id,
                        "document_safety_hold",
                        document_ref,
                        {
                            "id": str(hold_row[0]),
                            "client_id": client_id,
                            "document_ref": document_ref,
                            "hold_code": hold_code,
                            "trigger_event_id": str(hold_row[3]),
                            "created_at": str(hold_row[2]),
                            "resolved_at": "",
                        },
                    )
                cursor.execute(
                    """
                    select record_key, payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'export_package'
                    for update
                    """,
                    (self.tenant_id, client_id),
                )
                delivered_package_ids = []
                for package_key, package_record in cursor.fetchall():
                    package = package_record.get("package") or {}
                    if not package.get("downloaded_at"):
                        continue
                    if any(
                        str(entry.get("document_ref") or "").split("#", 1)[0]
                        == document_ref
                        for entry in package.get("entries", [])
                        if isinstance(entry, dict)
                    ):
                        delivered_package_ids.append(str(package_key))
                if (
                    normalized_status in {"rejected", "cancelled"}
                    and delivered_package_ids
                ):
                    cursor.execute(
                        """
                        select payload
                        from workflow_records
                        where tenant_id = %s and client_id = %s
                          and record_type = 'qnb_correction_review'
                          and record_key = %s
                        for update
                        """,
                        (self.tenant_id, client_id, document_ref),
                    )
                    correction_row = cursor.fetchone()
                    existing_correction = (
                        deepcopy(correction_row[0]) if correction_row else None
                    )
                    correction = existing_correction or {
                        "id": str(uuid4()),
                        "client_id": client_id,
                        "document_ref": document_ref,
                        "status": "review_required",
                        "reason": (
                            f"qnb_status_{normalized_status}_after_delivery"
                        ),
                        "trigger_event_key": event_key,
                        "delivered_export_package_ids": delivered_package_ids,
                        "automatic_reversal_created": False,
                        "created_at": checked_at,
                    }
                    self._upsert_record_with_cursor(
                        cursor,
                        client_id,
                        "qnb_correction_review",
                        document_ref,
                        correction,
                    )
                cursor.execute(
                    """
                    select payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'uploaded_document' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, document_ref),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("uploaded_document_not_found")
                document = deepcopy(row[0])
                previous_status = str(
                    document.get("source_qnb_normalized_status") or ""
                )
                document.update(
                    {
                        "source_qnb_status": response_code,
                        "source_qnb_normalized_status": normalized_status,
                        "source_qnb_status_detail": response_detail,
                        "source_qnb_status_checked_at": checked_at,
                        "source_qnb_status_changed": bool(previous_status)
                        and previous_status != normalized_status,
                        "qnb_review_required": automation_hold,
                        "automation_hold": automation_hold,
                        "automation_hold_reason": hold_code,
                        "updated_at": utc_now(),
                    }
                )
                self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    "uploaded_document",
                    document_ref,
                    document,
                )
                snapshot = {
                    "snapshot_id": event_key,
                    "document_ref": document_ref,
                    "ettn": ettn,
                    "response_code": response_code,
                    "normalized_status": normalized_status,
                    "response_detail": response_detail,
                    "cancelled_at": cancelled_at,
                    "checked_at": checked_at,
                    "source": "qnb_incoming_status_query",
                    "review_required": automation_hold,
                }
                self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    "qnb_incoming_status_snapshot",
                    event_key,
                    {**snapshot, "client_id": client_id},
                )
        return {
            **snapshot,
            "automation_hold": automation_hold,
            "automation_hold_reason": hold_code,
        }

    def active_document_safety_holds(
        self,
        *,
        client_id: str,
        document_refs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_tenant()
        taxpayer_id = taxpayer_uuid(self.tenant_id, client_id)
        requested = [str(item) for item in (document_refs or []) if str(item)]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select h.id, d.source_ref, h.hold_code, h.trigger_event_id,
                           h.created_at
                    from document_safety_holds h
                    join documents d on d.id = h.document_id
                    where h.tenant_id = %s and h.taxpayer_id = %s
                      and h.resolved_at is null
                      and (%s = '{}'::text[] or d.source_ref = any(%s))
                    order by h.created_at asc
                    """,
                    (self.tenant_id, taxpayer_id, requested, requested),
                )
                rows = cursor.fetchall()
        return [
            {
                "id": str(row[0]),
                "client_id": client_id,
                "document_ref": str(row[1]),
                "hold_code": str(row[2]),
                "trigger_event_id": str(row[3]),
                "created_at": str(row[4]),
                "resolved_at": "",
            }
            for row in rows
        ]

    def save_outgoing_invoice(self, *, client_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
        invoice_id = str(invoice.get("invoice_id") or "")
        if not invoice_id:
            raise ValueError("Outgoing invoice ID is required")
        existing = self._get_record(client_id, "outgoing_invoice", invoice_id) or {}
        return self._upsert_record(client_id, "outgoing_invoice", invoice_id, {**existing, **invoice, "client_id": client_id})

    def get_outgoing_invoice(self, *, client_id: str, invoice_id: str) -> dict[str, Any] | None:
        return self._get_record(client_id, "outgoing_invoice", invoice_id)

    def list_outgoing_invoices(self, *, client_id: str) -> list[dict[str, Any]]:
        return self._payloads(client_id, "outgoing_invoice")

    def claim_outgoing_invoice_attempt(
        self,
        *,
        client_id: str,
        invoice_id: str,
        idempotency_key: str,
        ubl_sha256: str,
        provider: str,
        provider_operation: str,
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        self._ensure_tenant()
        idempotency_key_hash = sha256(idempotency_key.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_key' and record_key = %s
                    """,
                    (self.tenant_id, client_id, idempotency_key_hash),
                )
                existing_row = cursor.fetchone()
                if existing_row:
                    claim = existing_row[0]
                    if claim.get("invoice_id") != invoice_id:
                        raise ValueError("Idempotency key is already used for another invoice")
                    if claim.get("ubl_sha256") != ubl_sha256:
                        raise ValueError("Idempotency key is already used for another UBL hash")
                    return False, *self._load_outgoing_attempt_rows(
                        cursor,
                        client_id=client_id,
                        invoice_id=invoice_id,
                        attempt_id=str(claim.get("attempt_id") or ""),
                    )

                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, invoice_id),
                )
                invoice_row = cursor.fetchone()
                if not invoice_row:
                    raise ValueError("Outgoing invoice not found")
                invoice = invoice_row[0]
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_key' and record_key = %s
                    """,
                    (self.tenant_id, client_id, idempotency_key_hash),
                )
                committed_claim_row = cursor.fetchone()
                if committed_claim_row:
                    claim = committed_claim_row[0]
                    if claim.get("invoice_id") != invoice_id or claim.get("ubl_sha256") != ubl_sha256:
                        raise ValueError("Idempotency key is already used for another invoice or UBL hash")
                    return False, *self._load_outgoing_attempt_rows(
                        cursor,
                        client_id=client_id,
                        invoice_id=invoice_id,
                        attempt_id=str(claim.get("attempt_id") or ""),
                    )
                if invoice.get("status") != "approved":
                    raise ValueError("Only an approved invoice can be sent")

                attempt_id = str(uuid4())
                claimed_at = utc_now()
                claim = {
                    "client_id": client_id,
                    "invoice_id": invoice_id,
                    "idempotency_key_hash": idempotency_key_hash,
                    "ubl_sha256": ubl_sha256,
                    "attempt_id": attempt_id,
                    "claimed_at": claimed_at,
                }
                cursor.execute(
                    """
                    insert into workflow_records (id, tenant_id, client_id, record_type, record_key, payload)
                    values (%s, %s, %s, 'outgoing_invoice_send_key', %s, %s)
                    on conflict do nothing
                    returning payload
                    """,
                    (uuid4(), self.tenant_id, client_id, idempotency_key_hash, self._json(claim)),
                )
                inserted = cursor.fetchone()
                if not inserted:
                    cursor.execute(
                        """
                        select payload from workflow_records
                        where tenant_id = %s and client_id = %s
                          and record_type = 'outgoing_invoice_send_key' and record_key = %s
                        """,
                        (self.tenant_id, client_id, idempotency_key_hash),
                    )
                    winning_claim = cursor.fetchone()
                    if not winning_claim:
                        raise ValueError("Outgoing invoice attempt claim could not be resolved")
                    claim = winning_claim[0]
                    if claim.get("invoice_id") != invoice_id or claim.get("ubl_sha256") != ubl_sha256:
                        raise ValueError("Idempotency key is already used for another invoice or UBL hash")
                    return False, *self._load_outgoing_attempt_rows(
                        cursor,
                        client_id=client_id,
                        invoice_id=invoice_id,
                        attempt_id=str(claim.get("attempt_id") or ""),
                    )

                attempt = {
                    "attempt_id": attempt_id,
                    "client_id": client_id,
                    "invoice_id": invoice_id,
                    "idempotency_key_hash": idempotency_key_hash,
                    "ubl_sha256": ubl_sha256,
                    "document_type": str(invoice.get("document_type") or ""),
                    "provider": provider,
                    "provider_operation": provider_operation,
                    "state": "claimed",
                    "events": [{"event": "claimed", "at": claimed_at, "details": {}}],
                    "created_at": claimed_at,
                    "updated_at": claimed_at,
                }
                cursor.execute(
                    """
                    insert into workflow_records (id, tenant_id, client_id, record_type, record_key, payload)
                    values (%s, %s, %s, 'outgoing_invoice_send_attempt', %s, %s)
                    """,
                    (uuid4(), self.tenant_id, client_id, attempt_id, self._json(attempt)),
                )
                invoice = {
                    **invoice,
                    "status": "sending",
                    "current_attempt_id": attempt_id,
                    "updated_at": claimed_at,
                }
                cursor.execute(
                    """
                    update workflow_records set payload = %s, updated_at = now()
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice' and record_key = %s
                    """,
                    (self._json(invoice), self.tenant_id, client_id, invoice_id),
                )
                return True, deepcopy(invoice), deepcopy(attempt)

    def _load_outgoing_attempt_rows(
        self, cursor: Any, *, client_id: str, invoice_id: str, attempt_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cursor.execute(
            """
            select record_type, payload from workflow_records
            where tenant_id = %s and client_id = %s
              and ((record_type = 'outgoing_invoice' and record_key = %s)
                or (record_type = 'outgoing_invoice_send_attempt' and record_key = %s))
            """,
            (self.tenant_id, client_id, invoice_id, attempt_id),
        )
        rows = cursor.fetchall()
        payloads = {str(record_type): payload for record_type, payload in rows}
        invoice = payloads.get("outgoing_invoice")
        attempt = payloads.get("outgoing_invoice_send_attempt")
        if not invoice or not attempt:
            raise ValueError("Outgoing invoice attempt is incomplete")
        return deepcopy(invoice), deepcopy(attempt)

    def append_outgoing_invoice_attempt_event(
        self,
        *,
        client_id: str,
        attempt_id: str,
        event: str,
        state: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_attempt' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, attempt_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Outgoing invoice attempt not found")
                now = utc_now()
                updated = deepcopy(row[0])
                updated.setdefault("events", []).append(
                    {"event": event, "at": now, "details": deepcopy(details or {})}
                )
                if state:
                    updated["state"] = state
                    if state != "reconciling":
                        updated.pop("reconciliation_owner", None)
                        updated.pop("reconciliation_lease_expires_at", None)
                updated["updated_at"] = now
                cursor.execute(
                    """
                    update workflow_records set payload = %s, updated_at = now()
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_attempt' and record_key = %s
                    """,
                    (self._json(updated), self.tenant_id, client_id, attempt_id),
                )
                return deepcopy(updated)

    def get_outgoing_invoice_attempt(self, *, client_id: str, attempt_id: str) -> dict[str, Any] | None:
        return self._get_record(client_id, "outgoing_invoice_send_attempt", attempt_id)

    def claim_outgoing_invoice_reconciliation(
        self,
        *,
        client_id: str,
        attempt_id: str,
        owner_id: str,
        stale_before: str,
        lease_expires_at: str,
    ) -> tuple[bool, dict[str, Any]]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_attempt' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, attempt_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Outgoing invoice attempt not found")
                attempt = deepcopy(row[0])
                now = utc_now()
                active_lease = str(attempt.get("reconciliation_lease_expires_at") or "")
                if active_lease and active_lease > now:
                    return False, attempt
                state = str(attempt.get("state") or "")
                if state == "request_started":
                    request_started_at = next(
                        (
                            str(item.get("at") or "")
                            for item in reversed(attempt.get("events") or [])
                            if item.get("event") == "request_started"
                        ),
                        "",
                    )
                    if not request_started_at or request_started_at > stale_before:
                        return False, attempt
                elif state not in {"reconciliation_required", "reconciling"}:
                    return False, attempt
                attempt.setdefault("events", []).append(
                    {"event": "reconciliation_started", "at": now, "details": {}}
                )
                attempt.update(
                    {
                        "state": "reconciling",
                        "reconciliation_owner": owner_id,
                        "reconciliation_lease_expires_at": lease_expires_at,
                        "updated_at": now,
                    }
                )
                cursor.execute(
                    """
                    update workflow_records set payload = %s, updated_at = now()
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_attempt' and record_key = %s
                    """,
                    (self._json(attempt), self.tenant_id, client_id, attempt_id),
                )
                return True, deepcopy(attempt)

    def finalize_outgoing_invoice_attempt(
        self,
        *,
        client_id: str,
        attempt_id: str,
        expected_state: str,
        event: str,
        state: str,
        details: dict[str, Any] | None = None,
        reconciliation_owner: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_attempt' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, attempt_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Outgoing invoice attempt not found")
                attempt = deepcopy(row[0])
                if str(attempt.get("state") or "") != expected_state:
                    return False, attempt
                if reconciliation_owner and attempt.get("reconciliation_owner") != reconciliation_owner:
                    return False, attempt
                now = utc_now()
                attempt.setdefault("events", []).append(
                    {"event": event, "at": now, "details": deepcopy(details or {})}
                )
                attempt["state"] = state
                attempt["updated_at"] = now
                attempt.pop("reconciliation_owner", None)
                attempt.pop("reconciliation_lease_expires_at", None)
                cursor.execute(
                    """
                    update workflow_records set payload = %s, updated_at = now()
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_attempt' and record_key = %s
                    """,
                    (self._json(attempt), self.tenant_id, client_id, attempt_id),
                )
                return True, deepcopy(attempt)

    def finalize_outgoing_invoice_attempt_and_invoice(
        self, *, client_id: str, attempt_id: str, expected_state: str, event: str,
        state: str, invoice: dict[str, Any], details: dict[str, Any] | None = None,
        reconciliation_owner: str = "",
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """select payload from workflow_records where tenant_id = %s and client_id = %s
                    and record_type = 'outgoing_invoice_send_attempt' and record_key = %s for update""",
                    (self.tenant_id, client_id, attempt_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Outgoing invoice attempt not found")
                attempt = deepcopy(row[0])
                if str(attempt.get("state") or "") != expected_state:
                    return False, deepcopy(invoice), attempt
                if reconciliation_owner and attempt.get("reconciliation_owner") != reconciliation_owner:
                    return False, deepcopy(invoice), attempt
                cursor.execute(
                    """select payload from workflow_records where tenant_id = %s and client_id = %s
                    and record_type = 'outgoing_invoice' and record_key = %s for update""",
                    (self.tenant_id, client_id, str(invoice.get("invoice_id") or "")),
                )
                if not cursor.fetchone():
                    raise ValueError("Outgoing invoice not found")
                now = utc_now()
                attempt.setdefault("events", []).append(
                    {"event": event, "at": now, "details": deepcopy(details or {})}
                )
                attempt.update({"state": state, "updated_at": now})
                attempt.pop("reconciliation_owner", None)
                attempt.pop("reconciliation_lease_expires_at", None)
                cursor.execute(
                    """update workflow_records set payload = %s, updated_at = now() where tenant_id = %s
                    and client_id = %s and record_type = 'outgoing_invoice_send_attempt' and record_key = %s""",
                    (self._json(attempt), self.tenant_id, client_id, attempt_id),
                )
                cursor.execute(
                    """update workflow_records set payload = %s, updated_at = now() where tenant_id = %s
                    and client_id = %s and record_type = 'outgoing_invoice' and record_key = %s""",
                    (self._json(invoice), self.tenant_id, client_id, str(invoice.get("invoice_id") or "")),
                )
                return True, deepcopy(invoice), deepcopy(attempt)

    def list_outgoing_invoice_attempts(self, *, client_id: str, invoice_id: str = "") -> list[dict[str, Any]]:
        rows = self._payloads(client_id, "outgoing_invoice_send_attempt")
        return [row for row in rows if not invoice_id or row.get("invoice_id") == invoice_id]

    def claim_outgoing_invoice_send(
        self, *, client_id: str, invoice_id: str, idempotency_key: str
    ) -> tuple[bool, dict[str, Any] | None]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice_send_key' and record_key = %s
                    """,
                    (self.tenant_id, client_id, idempotency_key),
                )
                existing_claim = cursor.fetchone()
                if existing_claim:
                    if existing_claim[0].get("invoice_id") != invoice_id:
                        raise ValueError("Idempotency key is already used for another invoice")
                    cursor.execute(
                        """
                        select payload from workflow_records
                        where tenant_id = %s and client_id = %s
                          and record_type = 'outgoing_invoice' and record_key = %s
                        """,
                        (self.tenant_id, client_id, invoice_id),
                    )
                    row = cursor.fetchone()
                    return False, deepcopy(row[0]) if row else None
                cursor.execute(
                    """
                    select payload from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, invoice_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("Outgoing invoice not found")
                invoice = row[0]
                if invoice.get("status") != "approved":
                    raise ValueError("Only an approved invoice can be sent")
                claim = {
                    "client_id": client_id,
                    "invoice_id": invoice_id,
                    "idempotency_key": idempotency_key,
                    "claimed_at": utc_now(),
                }
                cursor.execute(
                    """
                    insert into workflow_records (id, tenant_id, client_id, record_type, record_key, payload)
                    values (%s, %s, %s, 'outgoing_invoice_send_key', %s, %s)
                    """,
                    (uuid4(), self.tenant_id, client_id, idempotency_key, self._json(claim)),
                )
                invoice = {**invoice, "status": "sending", "updated_at": utc_now()}
                cursor.execute(
                    """
                    update workflow_records set payload = %s, updated_at = now()
                    where tenant_id = %s and client_id = %s
                      and record_type = 'outgoing_invoice' and record_key = %s
                    """,
                    (self._json(invoice), self.tenant_id, client_id, invoice_id),
                )
                return True, deepcopy(invoice)

    def record_document_pipeline_event(
        self,
        *,
        client_id: str,
        document_ref: str,
        step: str,
        status: str,
        message_tr: str,
        debug_code: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        record = {
            "event_id": event_id,
            "event_type": "document_pipeline_event",
            "client_id": client_id,
            "document_ref": document_ref,
            "step": step,
            "status": status,
            "message_tr": message_tr,
            "debug_code": debug_code,
            "details": sanitize_semantic_evidence(details or {}),
            "created_at": utc_now(),
        }
        return self._upsert_record(client_id, "document_pipeline_event", event_id, record)

    def list_document_pipeline_events(
        self,
        *,
        client_id: str,
        document_ref: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = [
            event
            for event in self._payloads(client_id, "document_pipeline_event")
            if event.get("document_ref") == document_ref
        ]
        return events[-max(limit, 1):]

    def save_nace_research_profile(
        self,
        *,
        nace_code: str,
        profile: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_nace_code(nace_code)
        if expected_revision is not None:
            return self._save_research_profile_with_revision(
                record_type="nace_research_profile",
                record_key=normalized,
                profile=profile,
                expected_revision=expected_revision,
                key_field="nace_code",
                default_bucket="__research_office__",
            )
        existing = self.get_nace_research_profile(normalized) or {}
        timestamp = utc_now()
        record = {
            **existing,
            **profile,
            "nace_code": normalized,
            "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
            "updated_at": timestamp,
            "revision": int(existing.get("revision") or 0) + 1,
        }
        bucket = str(record.get("owner_client_id") or record.get("client_id") or "__research_office__")
        return self._upsert_record(bucket, "nace_research_profile", normalized, record)

    def get_nace_research_profile(self, nace_code: str) -> dict[str, Any] | None:
        row = self._get_record_by_key("nace_research_profile", normalize_nace_code(nace_code))
        return deepcopy(row["payload"]) if row else None

    def save_brand_research_profile(
        self,
        *,
        brand_name: str,
        profile: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_brand_name(brand_name)
        if expected_revision is not None:
            return self._save_research_profile_with_revision(
                record_type="brand_research_profile",
                record_key=normalized,
                profile=profile,
                expected_revision=expected_revision,
                key_field="brand_name",
                default_bucket="__research_office__",
            )
        existing = self.get_brand_research_profile(normalized) or {}
        timestamp = utc_now()
        record = {
            **existing,
            **profile,
            "brand_name": normalized,
            "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
            "updated_at": timestamp,
            "revision": int(existing.get("revision") or 0) + 1,
        }
        bucket = str(record.get("owner_client_id") or record.get("client_id") or "__research_office__")
        return self._upsert_record(bucket, "brand_research_profile", normalized, record)

    def get_brand_research_profile(self, brand_name: str) -> dict[str, Any] | None:
        row = self._get_record_by_key("brand_research_profile", normalize_brand_name(brand_name))
        return deepcopy(row["payload"]) if row else None

    def get_research_profile(
        self,
        *,
        kind: str,
        key: str,
        allowed_client_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        if kind == "nace":
            normalized = normalize_nace_code(key)
            record_type = "nace_research_profile"
        elif kind == "brand":
            normalized = normalize_brand_name(key)
            record_type = "brand_research_profile"
        else:
            return None
        if allowed_client_ids is None:
            if kind == "nace":
                return self.get_nace_research_profile(key)
            return self.get_brand_research_profile(key)
        for row in self._scoped_research_rows(
            record_type,
            allowed_client_ids=allowed_client_ids,
        ):
            if str(row.get("record_key") or "") != normalized:
                continue
            profile = deepcopy(row["payload"])
            if research_profile_is_visible(profile, allowed_client_ids=allowed_client_ids):
                return profile
        return None

    def list_research_profiles(
        self,
        *,
        kind: str = "",
        allowed_client_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        if kind in {"", "brand"}:
            profiles.extend(
                deepcopy(row["payload"])
                for row in self._scoped_research_rows(
                    "brand_research_profile",
                    allowed_client_ids=allowed_client_ids,
                )
            )
        if kind in {"", "nace"}:
            profiles.extend(
                deepcopy(row["payload"])
                for row in self._scoped_research_rows(
                    "nace_research_profile",
                    allowed_client_ids=allowed_client_ids,
                )
            )
        return sorted(
            [
                profile
                for profile in profiles
                if research_profile_is_visible(profile, allowed_client_ids=allowed_client_ids)
            ],
            key=lambda profile: str(profile.get("updated_at") or profile.get("researched_at") or ""),
            reverse=True,
        )

    def _scoped_research_rows(
        self,
        record_type: str,
        *,
        allowed_client_ids: set[str] | None,
    ) -> list[dict[str, Any]]:
        if allowed_client_ids is None:
            return self._list_records(record_type)
        rows: list[dict[str, Any]] = []
        for client_id in sorted(allowed_client_ids | {"__research_office__"}):
            rows.extend(self._list_records(record_type, client_id=client_id))
        return rows

    def _save_research_profile_with_revision(
        self,
        *,
        record_type: str,
        record_key: str,
        profile: dict[str, Any],
        expected_revision: int,
        key_field: str,
        default_bucket: str,
    ) -> dict[str, Any]:
        """Compare and update one opaque research profile inside one DB transaction."""

        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select client_id, payload
                    from workflow_records
                    where tenant_id = %s and record_type = %s and record_key = %s
                    for update
                    """,
                    (self.tenant_id, record_type, record_key),
                )
                row = cursor.fetchone()
                existing = dict(row[1]) if row else {}
                actual_revision = int(existing.get("revision") or 0)
                if actual_revision != expected_revision:
                    raise ResearchProfileConflict(
                        expected_revision=expected_revision,
                        actual_revision=actual_revision,
                    )
                timestamp = utc_now()
                record = {
                    **existing,
                    **profile,
                    key_field: record_key,
                    "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
                    "updated_at": timestamp,
                    "revision": actual_revision + 1,
                }
                bucket = str(
                    record.get("owner_client_id")
                    or record.get("client_id")
                    or (row[0] if row else "")
                    or default_bucket
                )
                return self._upsert_record_with_cursor(
                    cursor,
                    bucket,
                    record_type,
                    record_key,
                    record,
                )

    def save_research_benchmark_run(self, run: dict[str, Any]) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            "run_id": str(uuid4()),
            "run_type": "benchmark",
            "created_at": timestamp,
            **run,
        }
        return self._upsert_record("__system__", "research_benchmark_run", record["run_id"], record)

    def list_research_benchmark_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        runs = [deepcopy(row["payload"]) for row in self._list_records("research_benchmark_run", client_id="__system__")]
        return runs[-max(limit, 1):]

    def save_uploaded_document(self, *, client_id: str, document: dict[str, Any]) -> dict[str, Any]:
        document_ref = str(document.get("document_id") or document.get("original_file_name") or uuid4())
        timestamp = utc_now()
        normalized: dict[str, Any] = {}
        if self.normalized_accounting_enabled:
            client = self._get_record(client_id, "client", client_id) or {}
            profile = client.get("profile") if isinstance(client.get("profile"), dict) else {}
            self._ensure_taxpayer(client_id=client_id, profile=profile or {"client_id": client_id})
        if (
            self.normalized_accounting_enabled
            and isinstance(self.normalized_repository, NormalizedAccountingRepository)
        ):
            with self._connect() as connection:
                transactional_repository = self.normalized_repository.with_connection(
                    connection
                )
                normalized = transactional_repository.store_source_document(
                    client_id=client_id,
                    document=document,
                )
                document_ref = str(normalized["document_ref"])
                record = {
                    **document,
                    **normalized,
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "updated_at": timestamp,
                }
                existing = self._get_record(
                    client_id,
                    "uploaded_document",
                    document_ref,
                )
                record["created_at"] = (
                    existing.get("created_at", timestamp)
                    if existing
                    else timestamp
                )
                with connection.cursor() as cursor:
                    return self._upsert_record_with_cursor(
                        cursor,
                        client_id,
                        "uploaded_document",
                        document_ref,
                        record,
                    )
        if self.normalized_accounting_enabled:
            normalized = self.normalized_repository.store_source_document(
                client_id=client_id,
                document=document,
            )
            document_ref = str(normalized["document_ref"])
        record = {
            **document,
            **normalized,
            "client_id": client_id,
            "document_ref": document_ref,
            "updated_at": timestamp,
        }
        existing = self._get_record(client_id, "uploaded_document", document_ref)
        record["created_at"] = existing.get("created_at", timestamp) if existing else timestamp
        return self._upsert_record(client_id, "uploaded_document", document_ref, record)

    def accept_document_source(
        self,
        *,
        client_id: str,
        document: dict[str, Any],
        source_channel: str,
        identities: list[dict[str, str]],
        parser_kind: str,
        intake_category: str = "",
    ) -> dict[str, Any]:
        client = self._get_record(client_id, "client", client_id) or {}
        profile = client.get("profile") if isinstance(client.get("profile"), dict) else {}
        self._ensure_taxpayer(
            client_id=client_id,
            profile=profile or {"client_id": client_id},
        )
        repository = (
            self.normalized_repository
            if isinstance(self.normalized_repository, NormalizedAccountingRepository)
            else NormalizedAccountingRepository(
                connect=self._connect,
                tenant_id=self.tenant_id,
                json_value=self._json,
            )
        )
        timestamp = utc_now()
        with self._connect() as connection:
            normalized = repository.with_connection(connection).accept_source_document(
                client_id=client_id,
                document=document,
                source_channel=source_channel,
                identities=identities,
                parser_kind=parser_kind,
                intake_category=intake_category,
            )
            document_ref = str(normalized["document_ref"])
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'uploaded_document' and record_key = %s
                    for update
                    """,
                    (self.tenant_id, client_id, document_ref),
                )
                row = cursor.fetchone()
                existing = deepcopy(row[0]) if row else {}
                requested_ref = str(
                    normalized.get("requested_document_ref")
                    or document.get("document_id")
                    or ""
                )
                source = {
                    "source_ref": requested_ref,
                    "source_channel": str(source_channel or "").strip(),
                    "sha256": str(document.get("sha256") or ""),
                    "original_file_name": str(
                        document.get("original_file_name") or requested_ref
                    ),
                    "storage_path": str(document.get("storage_path") or ""),
                    "attached_at": timestamp,
                }
                attachments = deepcopy(existing.get("document_sources") or [])
                if not any(
                    str(item.get("source_ref") or "") == requested_ref
                    or (
                        source["sha256"]
                        and str(item.get("sha256") or "") == source["sha256"]
                    )
                    for item in attachments
                ):
                    attachments.append(source)
                record = {
                    **document,
                    **existing,
                    **normalized,
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "document_sources": attachments,
                    "updated_at": timestamp,
                }
                record.setdefault("created_at", timestamp)
                persisted = self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    "uploaded_document",
                    document_ref,
                    record,
                )
                job = dict(normalized["processing_job"])
                self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    "processing_job",
                    str(job["id"]),
                    job,
                )
        return {
            **persisted,
            "processing_job": job,
            "processing_job_created": bool(normalized["processing_job_created"]),
            "deduplicated": bool(normalized["deduplicated"]),
            "requested_document_ref": str(normalized["requested_document_ref"]),
        }

    def save_onboarding_attachment(self, *, client_id: str, attachment: dict[str, Any]) -> dict[str, Any]:
        attachment_ref = str(attachment.get("attachment_ref") or attachment.get("document_id") or uuid4())
        timestamp = utc_now()
        record = {
            **attachment,
            "client_id": client_id,
            "attachment_ref": attachment_ref,
            "updated_at": timestamp,
        }
        existing = self._get_record(client_id, "onboarding_attachment", attachment_ref)
        record["created_at"] = existing.get("created_at", timestamp) if existing else timestamp
        return self._upsert_record(client_id, "onboarding_attachment", attachment_ref, record)

    def apply_document_retention(self, *, delete_files: bool = True) -> dict[str, Any]:
        checked_count = 0
        expiring_count = 0
        deleted_count = 0
        deleted_refs: list[str] = []
        for row in self._list_records("uploaded_document"):
            checked_count += 1
            client_id = str(row["client_id"])
            document_ref = str(row["record_key"])
            document = row["payload"]
            decision = retention_decision(document)
            if decision.storage_status == "expiring":
                document["storage_status"] = "expiring"
                document["updated_at"] = utc_now()
                self._upsert_record(client_id, "uploaded_document", document_ref, document)
                expiring_count += 1
            if not decision.should_delete:
                continue
            storage_path = Path(str(document.get("storage_path") or ""))
            if delete_files and storage_path.exists() and storage_path.is_file():
                storage_path.unlink()
            document["status"] = "deleted"
            document["storage_status"] = "deleted"
            document["deleted_at"] = utc_now()
            document["updated_at"] = document["deleted_at"]
            self._upsert_record(client_id, "uploaded_document", document_ref, document)
            deleted_refs.append(f"{client_id}:{document_ref}")
            deleted_count += 1
        return {
            "checked_count": checked_count,
            "expiring_count": expiring_count,
            "deleted_count": deleted_count,
            "deleted_document_refs": deleted_refs,
        }

    def preview_document_retention(self) -> dict[str, Any]:
        checked_count = 0
        expiring_count = 0
        expired_count = 0
        documents: list[dict[str, Any]] = []
        for row in self._list_records("uploaded_document"):
            checked_count += 1
            client_id = str(row["client_id"])
            document_ref = str(row["record_key"])
            document = row["payload"]
            decision = retention_decision(document)
            if decision.storage_status == "expiring":
                expiring_count += 1
            if decision.storage_status == "expired":
                expired_count += 1
            if decision.storage_status in {"expiring", "expired"}:
                documents.append(
                    {
                        "document_ref": document_ref,
                        "document_key": f"{client_id}:{document_ref}",
                        "client_id": client_id,
                        "original_file_name": str(document.get("original_file_name") or ""),
                        "storage_status": decision.storage_status,
                        "expires_at": str(document.get("expires_at") or ""),
                        "reason": decision.reason,
                    }
                )
        return {
            "checked_count": checked_count,
            "expiring_count": expiring_count,
            "expired_count": expired_count,
            "deleted_count": 0,
            "documents": documents,
        }

    def apply_document_retention_action(
        self,
        *,
        document_refs: list[str],
        action: str,
        delete_files: bool = True,
    ) -> dict[str, Any]:
        normalized_refs = {str(ref or "").strip() for ref in document_refs if str(ref or "").strip()}
        if action not in {"delete", "extend_90_days"}:
            raise ValueError("unsupported retention action")
        timestamp = utc_now()
        deleted_count = 0
        extended_count = 0
        deleted_file_count = 0
        changed_refs: list[str] = []
        for row in self._list_records("uploaded_document"):
            client_id = str(row["client_id"])
            document_ref = str(row["record_key"])
            document_key = f"{client_id}:{document_ref}"
            if document_ref not in normalized_refs and document_key not in normalized_refs:
                continue
            document = row["payload"]
            if action == "delete":
                storage_path = Path(str(document.get("storage_path") or ""))
                if delete_files and storage_path.exists() and storage_path.is_file():
                    storage_path.unlink()
                    deleted_file_count += 1
                document["status"] = "deleted"
                document["storage_status"] = "deleted"
                document["deleted_at"] = timestamp
                document["updated_at"] = timestamp
                deleted_count += 1
            else:
                current_expiry = str(document.get("expires_at") or "")
                if not current_expiry:
                    continue
                extended = extend_retention_deadline(current_expiry, days=90)
                document["expires_at"] = extended
                document["download_available_until"] = extended
                document["storage_status"] = "stored"
                document["deleted_at"] = ""
                document["updated_at"] = timestamp
                extended_count += 1
            self._upsert_record(client_id, "uploaded_document", document_ref, document)
            changed_refs.append(document_ref)
        return {
            "action": action,
            "deleted_count": deleted_count,
            "extended_count": extended_count,
            "deleted_file_count": deleted_file_count,
            "document_refs": changed_refs,
        }

    def delete_client_documents(
        self,
        *,
        client_id: str,
        document_refs: list[str],
        delete_files: bool = True,
    ) -> dict[str, Any]:
        normalized_client_id = client_id.strip()
        refs = list(dict.fromkeys(str(ref or "").strip() for ref in document_refs if str(ref or "").strip()))
        if not normalized_client_id:
            raise ValueError("client_id is required")
        deleted_refs: list[str] = []
        deleted_file_count = 0
        uploaded_rows = {
            str(row["record_key"]): row["payload"]
            for row in self._list_records("uploaded_document", client_id=normalized_client_id)
            if str(row["record_key"]) in set(refs)
        }
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for document_ref in refs:
                    uploaded = uploaded_rows.get(document_ref)
                    if uploaded and delete_files:
                        storage_path = Path(str(uploaded.get("storage_path") or ""))
                        if storage_path.exists() and storage_path.is_file():
                            storage_path.unlink()
                            deleted_file_count += 1
                    cursor.execute(
                        """
                        delete from workflow_records
                        where tenant_id = %s
                          and client_id = %s
                          and record_type in ('uploaded_document', 'document')
                          and record_key = %s
                        """,
                        (self.tenant_id, normalized_client_id, document_ref),
                    )
                    direct_deleted = cursor.rowcount
                    cursor.execute(
                        """
                        delete from workflow_records
                        where tenant_id = %s
                          and client_id = %s
                          and record_type in ('processing_job', 'document_pipeline_event')
                          and payload->>'document_ref' = %s
                        """,
                        (self.tenant_id, normalized_client_id, document_ref),
                    )
                    if direct_deleted:
                        deleted_refs.append(document_ref)
        return {
            "client_id": normalized_client_id,
            "deleted_count": len(deleted_refs),
            "deleted_document_refs": deleted_refs,
            "deleted_file_count": deleted_file_count,
        }

    def save_simulation_result(
        self,
        *,
        client_id: str,
        document_ref: str,
        result: dict[str, Any],
        attempt_id: str = "",
    ) -> dict[str, Any]:
        sanitized_result = merge_semantic_attempt_result(result)
        input_digest = simulation_input_digest(sanitized_result) if attempt_id else ""
        normalized_required = (
            self.normalized_accounting_enabled
            and str(sanitized_result.get("accounting_direction") or "")
            in {"purchase", "sales"}
        )

        def record_for(
            existing: dict[str, Any],
            current_result: dict[str, Any],
        ) -> dict[str, Any]:
            timestamp = utc_now()
            record = {
                **existing,
                "client_id": client_id,
                "document_ref": document_ref,
                "status": current_result.get(
                    "simulated_status",
                    "review_required",
                ),
                "export_status": current_result.get(
                    "export_status",
                    "review_required",
                ),
                "review_reason_codes": current_result.get(
                    "review_reason_codes",
                    [],
                ),
                "result": current_result,
                "updated_at": timestamp,
            }
            if attempt_id:
                record[PROCESSING_ATTEMPT_MARKER_KEY] = processing_attempt_marker(
                    attempt_id=attempt_id,
                    input_digest=input_digest,
                    result=current_result,
                )
            record.setdefault("id", str(uuid4()))
            record.setdefault("created_at", timestamp)
            return record

        # Test doubles and legacy injected repositories cannot share this store's
        # transaction. Keep their compatibility path without weakening the real
        # NormalizedAccountingRepository transaction below.
        if normalized_required and not isinstance(
            self.normalized_repository,
            NormalizedAccountingRepository,
        ):
            existing = self._get_record(client_id, "document", document_ref) or {}
            if attempt_id and matching_processing_attempt(
                existing,
                attempt_id=attempt_id,
                input_digest=input_digest,
            ):
                return deepcopy(existing)
            persisted_result = merge_semantic_attempt_result(
                sanitized_result,
                previous_result=(
                    existing.get("result") if isinstance(existing.get("result"), dict) else None
                ),
            )
            normalized = self.normalized_repository.persist_canonical_journal(
                client_id=client_id,
                document_ref=document_ref,
                result=persisted_result,
                **({"attempt_id": attempt_id} if attempt_id else {}),
            )
            persisted_result = {
                **persisted_result,
                "normalized_revision": normalized["revision_no"],
            }
            return self._upsert_record(
                client_id,
                "document",
                document_ref,
                record_for(existing, persisted_result),
            )

        self._ensure_tenant()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select pg_advisory_xact_lock(%s)",
                    (
                        workflow_document_lock_key(
                            self.tenant_id,
                            client_id,
                            document_ref,
                        ),
                    ),
                )
                cursor.execute(
                    """
                    select payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s
                      and record_type = 'document' and record_key = %s
                    limit 1
                    """,
                    (self.tenant_id, client_id, document_ref),
                )
                row = cursor.fetchone()
                existing = deepcopy(row[0]) if row else {}

            if attempt_id and matching_processing_attempt(
                existing,
                attempt_id=attempt_id,
                input_digest=input_digest,
            ):
                return deepcopy(existing)

            persisted_result = merge_semantic_attempt_result(
                sanitized_result,
                previous_result=(
                    existing.get("result") if isinstance(existing.get("result"), dict) else None
                ),
            )
            if normalized_required:
                transactional_repository = self.normalized_repository.with_connection(connection)
                normalized = transactional_repository.persist_canonical_journal(
                    client_id=client_id,
                    document_ref=document_ref,
                    result=persisted_result,
                    **({"attempt_id": attempt_id} if attempt_id else {}),
                )
                persisted_result = {
                    **persisted_result,
                    "normalized_revision": normalized["revision_no"],
                }

            record = record_for(existing, persisted_result)
            with connection.cursor() as cursor:
                return self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    "document",
                    document_ref,
                    record,
                )

    def create_processing_job(
        self,
        *,
        client_id: str,
        document_ref: str,
        document_type: str,
        parser_kind: str,
        intake_category: str = "",
        force_requeue: bool = False,
    ) -> dict[str, Any]:
        if self.normalized_accounting_enabled:
            existing = next(
                (
                    item
                    for item in self._payloads(client_id, "processing_job")
                    if str(item.get("document_ref") or "") == document_ref
                ),
                None,
            )
            if existing is not None and not force_requeue:
                return existing
            record = self.normalized_repository.create_processing_job(
                client_id=client_id,
                document_ref=document_ref,
                document_type=document_type,
                parser_kind=parser_kind,
                intake_category=intake_category,
                force_requeue=force_requeue,
            )
            return self._upsert_record(client_id, "processing_job", str(record["id"]), record)
        timestamp = utc_now()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "document_ref": document_ref,
            "document_type": document_type,
            "intake_category": intake_category,
            "parser_kind": parser_kind,
            "status": "queued",
            "attempt_count": 0,
            "error_message": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        return self._upsert_record(client_id, "processing_job", record["id"], record)

    def list_processing_jobs(self, *, client_id: str | None = None) -> list[dict[str, Any]]:
        return [
            deepcopy(row["payload"])
            for row in self._list_records("processing_job", client_id=client_id)
        ]

    def claim_next_processing_job(self) -> dict[str, Any] | None:
        if self.normalized_accounting_enabled:
            claimed = self.normalized_repository.claim_next_processing_job()
            if claimed is None:
                return None
            client_id = self._client_id_for_taxpayer_job(str(claimed["id"]))
            if not client_id:
                row = self._get_record_by_key("processing_job", str(claimed["id"]))
                client_id = str(row["client_id"]) if row is not None else ""
            if client_id:
                claimed["client_id"] = client_id
                self._upsert_record(client_id, "processing_job", str(claimed["id"]), claimed)
            return claimed
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    with next_job as (
                        select client_id, record_key, payload
                        from workflow_records
                        where tenant_id = %s
                          and record_type = 'processing_job'
                          and payload->>'status' = 'queued'
                        order by payload->>'created_at' asc, created_at asc
                        limit 1
                        for update skip locked
                    )
                    update workflow_records as records
                    set payload = jsonb_set(
                            jsonb_set(
                                jsonb_set(
                                    next_job.payload,
                                    '{status}',
                                    to_jsonb('processing'::text)
                                ),
                                '{attempt_count}',
                                to_jsonb(coalesce((next_job.payload->>'attempt_count')::int, 0) + 1)
                            ),
                            '{updated_at}',
                            to_jsonb(%s::text)
                        ),
                        updated_at = now()
                    from next_job
                    where records.tenant_id = %s
                      and records.client_id = next_job.client_id
                      and records.record_type = 'processing_job'
                      and records.record_key = next_job.record_key
                    returning records.client_id, records.record_key, records.payload
                    """,
                    (self.tenant_id, utc_now(), self.tenant_id),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return deepcopy(row[2])

    def update_processing_job(
        self,
        *,
        job_id: str,
        status: str,
        error_message: str = "",
        processing_metrics: dict[str, Any] | None = None,
        attempt_id: str = "",
        next_attempt_at: Any | None = None,
        retry_step: int = 0,
        outage_episode_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self.normalized_accounting_enabled:
            update_kwargs = {
                "job_id": job_id,
                "status": status,
                "error_message": error_message,
                "processing_metrics": processing_metrics,
            }
            if next_attempt_at is not None or retry_step or outage_episode_id:
                update_kwargs.update(
                    {
                        "next_attempt_at": next_attempt_at,
                        "retry_step": retry_step,
                        "outage_episode_id": outage_episode_id,
                    }
                )
            if attempt_id:
                update_kwargs["attempt_id"] = attempt_id
            updated = self.normalized_repository.update_processing_job(**update_kwargs)
            if updated is None:
                return None
            row = self._get_record_by_key("processing_job", job_id)
            if row is not None:
                client_id = str(row["client_id"])
                updated["client_id"] = client_id
                return self._upsert_record(client_id, "processing_job", job_id, updated)
            return updated
        row = self._get_record_by_key("processing_job", job_id)
        if row is None:
            return None
        payload = row["payload"]
        payload["status"] = status
        payload["error_message"] = error_message
        if processing_metrics is not None:
            payload["processing_metrics"] = processing_metrics
        payload["next_attempt_at"] = next_attempt_at.isoformat() if hasattr(next_attempt_at, "isoformat") else str(next_attempt_at or "")
        payload["retry_step"] = int(retry_step or 0)
        payload["outage_episode_id"] = str(outage_episode_id or "")
        payload["updated_at"] = utc_now()
        return self._upsert_record(str(row["client_id"]), "processing_job", job_id, payload)

    def record_ai_outage_failure(self, *, task_kind: str, document_id: str, evidence: dict[str, str], now: datetime) -> dict[str, Any]:
        if self.normalized_accounting_enabled:
            return self.normalized_repository.record_ai_outage_failure(
                task_kind=task_kind, document_id=document_id, evidence=evidence, now=now
            )
        episode = self._get_record(PORTAL_USERS_CLIENT_ID, "ai_outage_episode", task_kind) or {
            "id": str(uuid4()), "task_kind": task_kind, "status": "open", "affected_document_count": 0,
            "failed_provider_categories": [],
        }
        episode["affected_document_count"] = int(episode.get("affected_document_count") or 0) + 1
        episode["failed_provider_categories"] = [*episode.get("failed_provider_categories", []), evidence]
        return self._upsert_record(PORTAL_USERS_CLIENT_ID, "ai_outage_episode", task_kind, episode)

    def recover_ai_outage_episode(self, *, episode_id: str, now: datetime) -> dict[str, Any] | None:
        if self.normalized_accounting_enabled:
            return self.normalized_repository.recover_ai_outage_episode(episode_id=episode_id, now=now)
        return None

    def _client_id_for_taxpayer_job(self, job_id: str) -> str:
        row = self._get_record_by_key("processing_job", job_id)
        return str(row["client_id"]) if row is not None else ""

    def save_review_decision(
        self,
        *,
        client_id: str,
        decision: dict[str, Any],
        learning_event: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = utc_now()
        document_ref = str(decision.get("document_ref") or learning_event.get("document_ref") or "")
        document = self._get_record(client_id, "document", document_ref)
        corrected_document: dict[str, Any] | None = None
        if document is not None:
            corrected_document = apply_review_decision_to_document(
                document,
                decision=decision,
                learning_event=learning_event,
                reviewed_at=timestamp,
            )
        normalized_review: dict[str, Any] = {}
        corrected_result = (
            corrected_document.get("result")
            if corrected_document is not None
            else None
        )
        normalized_review_required = (
            self.normalized_accounting_enabled
            and isinstance(corrected_result, dict)
            and str(corrected_result.get("accounting_direction") or "")
            in {"purchase", "sales"}
        )
        if (
            normalized_review_required
            and isinstance(self.normalized_repository, NormalizedAccountingRepository)
        ):
            with self._connect() as connection:
                transactional_repository = self.normalized_repository.with_connection(
                    connection
                )
                normalized_review = transactional_repository.save_review(
                    client_id=client_id,
                    document_ref=document_ref,
                    decision=decision,
                    corrected_result=corrected_result,
                )
                corrected_result["normalized_revision"] = normalized_review[
                    "revision_no"
                ]
                corrected_result["normalized_revision_status"] = (
                    "approved"
                    if normalized_review["approved"]
                    else "review_required"
                )
                with connection.cursor() as cursor:
                    return self._persist_review_records(
                        cursor=cursor,
                        client_id=client_id,
                        decision=decision,
                        learning_event=learning_event,
                        normalized_review=normalized_review,
                        corrected_document=corrected_document,
                        timestamp=timestamp,
                    )
        if normalized_review_required:
            normalized_review = self.normalized_repository.save_review(
                client_id=client_id,
                document_ref=document_ref,
                decision=decision,
                corrected_result=corrected_result,
            )
            corrected_result["normalized_revision"] = normalized_review["revision_no"]
            corrected_result["normalized_revision_status"] = (
                "approved" if normalized_review["approved"] else "review_required"
            )
        return self._persist_review_records(
            cursor=None,
            client_id=client_id,
            decision=decision,
            learning_event=learning_event,
            normalized_review=normalized_review,
            corrected_document=corrected_document,
            timestamp=timestamp,
        )

    def _persist_review_records(
        self,
        *,
        cursor: Any | None,
        client_id: str,
        decision: dict[str, Any],
        learning_event: dict[str, Any],
        normalized_review: dict[str, Any],
        corrected_document: dict[str, Any] | None,
        timestamp: str,
    ) -> dict[str, Any]:
        def upsert(
            record_type: str,
            record_key: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            if cursor is not None:
                return self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    record_type,
                    record_key,
                    payload,
                )
            return self._upsert_record(
                client_id,
                record_type,
                record_key,
                payload,
            )

        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "decision": decision,
            "learning_event": learning_event,
            "normalized_review": normalized_review,
            "created_at": timestamp,
        }
        upsert("review_decision", record["id"], record)
        learning_event_id = str(uuid4())
        upsert(
            "learning_event",
            learning_event_id,
            {
                "id": learning_event_id,
                "client_id": client_id,
                **learning_event,
                "created_at": timestamp,
            },
        )
        if corrected_document is not None:
            document_ref = str(
                decision.get("document_ref")
                or learning_event.get("document_ref")
                or ""
            )
            upsert("document", document_ref, corrected_document)
            record["corrected_document"] = corrected_document
            upsert("review_decision", record["id"], record)
        return deepcopy(record)

    def save_export_package(self, *, client_id: str, package: dict[str, Any]) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "package": package,
            "created_at": utc_now(),
        }
        return self._upsert_record(client_id, "export_package", record["id"], record)

    def mark_export_package_downloaded(self, *, client_id: str, output_filename: str) -> dict[str, Any] | None:
        timestamp = utc_now()
        for row in reversed(self._list_records("export_package", client_id=client_id)):
            record = row["payload"]
            package = record.get("package") or {}
            if package.get("output_filename") != output_filename:
                continue
            updated = mark_export_package_downloaded(record, downloaded_at=timestamp)
            return self._upsert_record(client_id, "export_package", str(row["record_key"]), updated)
        return None

    def get_workspace(self, client_id: str) -> dict[str, Any]:
        workspace = {
            "client": self._get_record(client_id, "client", client_id),
            "chart_accounts": self._get_record(client_id, "chart_accounts", client_id),
            "uploaded_documents": self._payloads(client_id, "uploaded_document"),
            "onboarding_attachments": self._payloads(client_id, "onboarding_attachment"),
            "documents": self._payloads(client_id, "document"),
            "processing_jobs": self._payloads(client_id, "processing_job"),
            "review_decisions": self._payloads(client_id, "review_decision"),
            "learning_events": self._payloads(client_id, "learning_event"),
            "learning_rules": self.list_active_learning_rules(client_id=client_id),
            "export_packages": self._payloads(client_id, "export_package"),
            "portal_users": [
                user
                for user in self._payloads(PORTAL_USERS_CLIENT_ID, "portal_user")
                if client_id in set(user.get("allowed_client_ids") or []) or "*" in set(user.get("allowed_client_ids") or [])
            ],
            "operation_events": self.list_operation_events(client_id=client_id),
            "document_pipeline_events": self._payloads(client_id, "document_pipeline_event"),
            "qnb_incoming_status_snapshots": self._payloads(
                client_id,
                "qnb_incoming_status_snapshot",
            ),
            "document_safety_holds": self._payloads(
                client_id,
                "document_safety_hold",
            ),
            "qnb_correction_reviews": self._payloads(
                client_id,
                "qnb_correction_review",
            ),
        }
        if self.normalized_accounting_enabled:
            projections = {
                str(item.get("document_ref") or ""): item
                for item in self.normalized_repository.project_documents(client_id=client_id)
            }
            workspace["documents"] = [
                {**document, **projections.get(str(document.get("document_ref") or ""), {})}
                for document in workspace["documents"]
            ]
        return workspace

    def list_active_learning_rules(self, *, client_id: str) -> list[dict[str, Any]]:
        """Return only activated, tenant-scoped rules for worker compilation."""

        repository = LearningRuleRepository(
            connect=self._connect,
            tenant_id=self.tenant_id,
            json_value=self._json,
        )
        try:
            return repository.list_active(client_id=client_id)
        except Exception:  # compatibility databases may predate migration 008
            return []

    def authoritative_export_workspace(self, client_id: str) -> dict[str, Any]:
        workspace = self.get_workspace(client_id)
        if not self.normalized_accounting_enabled:
            return workspace
        workspace["documents"] = self.normalized_repository.project_documents(
            client_id=client_id,
            approved_only=True,
        )
        return workspace

    def reprocess_review_required_document_refs(
        self,
        *,
        client_id: str,
        document_refs: list[str],
    ) -> list[str]:
        if not self.normalized_accounting_enabled:
            return []
        return self.normalized_repository.reprocess_review_required_document_refs(
            client_id=client_id,
            document_refs=document_refs,
        )

    def reopen_journal(
        self,
        *,
        client_id: str,
        document_ref: str,
        expected_revision: int,
        reviewer: str,
        reason: str,
    ) -> dict[str, Any]:
        if not self.normalized_accounting_enabled:
            raise RuntimeError("journal reopen requires normalized accounting storage")
        document = self._get_record(client_id, "document", document_ref)
        if isinstance(self.normalized_repository, NormalizedAccountingRepository):
            with self._connect() as connection:
                transactional_repository = self.normalized_repository.with_connection(
                    connection
                )
                reopened = transactional_repository.reopen(
                    client_id=client_id,
                    document_ref=document_ref,
                    expected_revision=expected_revision,
                    reviewer=reviewer,
                    reason=reason,
                )
                if document is not None:
                    updated = self._reopened_document_projection(
                        document,
                        reopened=reopened,
                    )
                    with connection.cursor() as cursor:
                        self._upsert_record_with_cursor(
                            cursor,
                            client_id,
                            "document",
                            document_ref,
                            updated,
                        )
                return reopened
        reopened = self.normalized_repository.reopen(
            client_id=client_id,
            document_ref=document_ref,
            expected_revision=expected_revision,
            reviewer=reviewer,
            reason=reason,
        )
        if document is not None:
            updated = self._reopened_document_projection(
                document,
                reopened=reopened,
            )
            self._upsert_record(client_id, "document", document_ref, updated)
        return reopened

    @staticmethod
    def _reopened_document_projection(
        document: dict[str, Any],
        *,
        reopened: dict[str, Any],
    ) -> dict[str, Any]:
        updated = deepcopy(document)
        updated["status"] = "working_draft"
        updated["export_status"] = "review_required"
        updated["result"] = reopened["result"]
        updated["result"]["normalized_revision"] = reopened["revision_no"]
        updated["result"]["normalized_revision_status"] = "working_draft"
        updated["updated_at"] = utc_now()
        return updated

    def _payloads(self, client_id: str, record_type: str) -> list[dict[str, Any]]:
        return [deepcopy(row["payload"]) for row in self._list_records(record_type, client_id=client_id)]

    def _upsert_record(
        self,
        client_id: str,
        record_type: str,
        record_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                return self._upsert_record_with_cursor(
                    cursor,
                    client_id,
                    record_type,
                    record_key,
                    payload,
                )

    def _upsert_record_with_cursor(
        self,
        cursor: Any,
        client_id: str,
        record_type: str,
        record_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        cursor.execute(
            """
            insert into workflow_records (
                id, tenant_id, client_id, record_type, record_key, payload
            )
            values (%s, %s, %s, %s, %s, %s)
            on conflict (tenant_id, client_id, record_type, record_key)
            do update set payload = excluded.payload, updated_at = now()
            """,
            (
                uuid4(),
                self.tenant_id,
                client_id,
                record_type,
                record_key,
                self._json(payload),
            ),
        )
        return deepcopy(payload)

    def _get_record(self, client_id: str, record_type: str, record_key: str) -> dict[str, Any] | None:
        row = self._get_record_row(client_id, record_type, record_key)
        return deepcopy(row["payload"]) if row else None

    def _get_record_by_key(self, record_type: str, record_key: str) -> dict[str, Any] | None:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select client_id, record_key, payload
                    from workflow_records
                    where tenant_id = %s and record_type = %s and record_key = %s
                    limit 1
                    """,
                    (self.tenant_id, record_type, record_key),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {"client_id": row[0], "record_key": row[1], "payload": row[2]}

    def _delete_portal_user_with_auth(self, user_id: str) -> None:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    delete from workflow_records
                    where tenant_id = %s
                      and client_id = %s
                      and (
                        (record_type in ('portal_user', 'auth_credential') and record_key = %s)
                        or (record_type in ('auth_session', 'auth_token') and payload->>'user_id' = %s)
                      )
                    """,
                    (self.tenant_id, PORTAL_USERS_CLIENT_ID, user_id, user_id),
                )

    def _get_record_row(self, client_id: str, record_type: str, record_key: str) -> dict[str, Any] | None:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select client_id, record_key, payload
                    from workflow_records
                    where tenant_id = %s and client_id = %s and record_type = %s and record_key = %s
                    """,
                    (self.tenant_id, client_id, record_type, record_key),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {"client_id": row[0], "record_key": row[1], "payload": row[2]}

    def _list_records(self, record_type: str, *, client_id: str | None = None) -> list[dict[str, Any]]:
        self._ensure_tenant()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                if client_id is None:
                    cursor.execute(
                        """
                        select client_id, record_key, payload
                        from workflow_records
                        where tenant_id = %s and record_type = %s
                        order by created_at asc
                        """,
                        (self.tenant_id, record_type),
                    )
                else:
                    cursor.execute(
                        """
                        select client_id, record_key, payload
                        from workflow_records
                        where tenant_id = %s and client_id = %s and record_type = %s
                        order by created_at asc
                        """,
                        (self.tenant_id, client_id, record_type),
                    )
                rows = cursor.fetchall()
        return [{"client_id": row[0], "record_key": row[1], "payload": row[2]} for row in rows]

    def _ensure_tenant(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    insert into tenants (id, name)
                    values (%s, %s)
                    on conflict (id) do nothing
                    """,
                    (self.tenant_id, self.tenant_key),
                )

    def _ensure_taxpayer(self, *, client_id: str, profile: dict[str, Any]) -> None:
        self._ensure_tenant()
        display_name = str(profile.get("title") or profile.get("client_id") or client_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    insert into taxpayers (
                        id, tenant_id, display_name, legal_name, tax_number,
                        activity_description, nace_code, workplace_addresses
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                        display_name = excluded.display_name,
                        legal_name = excluded.legal_name,
                        tax_number = excluded.tax_number,
                        activity_description = excluded.activity_description,
                        nace_code = excluded.nace_code,
                        workplace_addresses = excluded.workplace_addresses,
                        updated_at = now()
                    """,
                    (
                        taxpayer_uuid(self.tenant_id, client_id),
                        self.tenant_id,
                        display_name,
                        display_name,
                        profile.get("tax_id") or "",
                        profile.get("activity_description") or "",
                        profile.get("nace_code") or "",
                        self._json(profile.get("workplace_addresses") or []),
                    ),
                )

    def _connect(self) -> Any:
        if self._connect_factory is not None:
            return self._connect_factory()
        import psycopg

        return psycopg.connect(self.dsn)

    @staticmethod
    def _json(value: Any) -> Any:
        from psycopg.types.json import Jsonb

        return Jsonb(value)
