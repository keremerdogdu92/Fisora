from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

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
from app.persistence.workflow_store import _clear_directory_contents


ConnectFactory = Callable[[], Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def tenant_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:tenant:{value}")


def taxpayer_uuid(client_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:taxpayer:{client_id}")


def normalize_nace_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_brand_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


class PostgresWorkflowStore:
    """PostgreSQL-backed MVP workspace store.

    This first production adapter keeps the same payload contract as the JSON
    store in a `workflow_records` compatibility table. The normalized accounting
    tables remain available for later hardening once real pilot data stabilizes.
    """

    def __init__(
        self,
        dsn: str,
        *,
        tenant_key: str | None = None,
        connect: ConnectFactory | None = None,
    ) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL workflow store requires a database dsn")
        self.dsn = dsn
        self.tenant_key = tenant_key or os.environ.get("FISORA_TENANT_KEY", "default")
        self.tenant_id = tenant_uuid(self.tenant_key)
        self._connect_factory = connect

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
        delete_files: bool = True,
    ) -> dict[str, Any]:
        self._ensure_tenant()
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
            "details": details or {},
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

    def save_nace_research_profile(self, *, nace_code: str, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_nace_code(nace_code)
        existing = self.get_nace_research_profile(normalized) or {}
        timestamp = utc_now()
        record = {
            **existing,
            **profile,
            "nace_code": normalized,
            "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
            "updated_at": timestamp,
        }
        return self._upsert_record("nace", "nace_research_profile", normalized, record)

    def get_nace_research_profile(self, nace_code: str) -> dict[str, Any] | None:
        return self._get_record("nace", "nace_research_profile", normalize_nace_code(nace_code))

    def save_brand_research_profile(self, *, brand_name: str, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_brand_name(brand_name)
        existing = self.get_brand_research_profile(normalized) or {}
        timestamp = utc_now()
        record = {
            **existing,
            **profile,
            "brand_name": normalized,
            "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
            "updated_at": timestamp,
        }
        return self._upsert_record("brand", "brand_research_profile", normalized, record)

    def get_brand_research_profile(self, brand_name: str) -> dict[str, Any] | None:
        return self._get_record("brand", "brand_research_profile", normalize_brand_name(brand_name))

    def get_research_profile(self, *, kind: str, key: str) -> dict[str, Any] | None:
        if kind == "nace":
            return self.get_nace_research_profile(key)
        if kind == "brand":
            return self.get_brand_research_profile(key)
        return None

    def list_research_profiles(self, *, kind: str = "") -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        if kind in {"", "brand"}:
            profiles.extend(deepcopy(row["payload"]) for row in self._list_records("brand_research_profile", client_id="brand"))
        if kind in {"", "nace"}:
            profiles.extend(deepcopy(row["payload"]) for row in self._list_records("nace_research_profile", client_id="nace"))
        return sorted(
            profiles,
            key=lambda profile: str(profile.get("updated_at") or profile.get("researched_at") or ""),
            reverse=True,
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
        record = {
            **document,
            "client_id": client_id,
            "document_ref": document_ref,
            "updated_at": timestamp,
        }
        existing = self._get_record(client_id, "uploaded_document", document_ref)
        record["created_at"] = existing.get("created_at", timestamp) if existing else timestamp
        return self._upsert_record(client_id, "uploaded_document", document_ref, record)

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
    ) -> dict[str, Any]:
        timestamp = utc_now()
        existing = self._get_record(client_id, "document", document_ref) or {}
        record = {
            **existing,
            "client_id": client_id,
            "document_ref": document_ref,
            "status": result.get("simulated_status", "review_required"),
            "export_status": result.get("export_status", "review_required"),
            "review_reason_codes": result.get("review_reason_codes", []),
            "result": result,
            "updated_at": timestamp,
        }
        record.setdefault("id", str(uuid4()))
        record.setdefault("created_at", timestamp)
        return self._upsert_record(client_id, "document", document_ref, record)

    def create_processing_job(
        self,
        *,
        client_id: str,
        document_ref: str,
        document_type: str,
        parser_kind: str,
        intake_category: str = "",
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any] | None:
        row = self._get_record_by_key("processing_job", job_id)
        if row is None:
            return None
        payload = row["payload"]
        payload["status"] = status
        payload["error_message"] = error_message
        if processing_metrics is not None:
            payload["processing_metrics"] = processing_metrics
        payload["updated_at"] = utc_now()
        return self._upsert_record(str(row["client_id"]), "processing_job", job_id, payload)

    def save_review_decision(
        self,
        *,
        client_id: str,
        decision: dict[str, Any],
        learning_event: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "decision": decision,
            "learning_event": learning_event,
            "created_at": timestamp,
        }
        self._upsert_record(client_id, "review_decision", record["id"], record)
        learning_event_id = str(uuid4())
        self._upsert_record(
            client_id,
            "learning_event",
            learning_event_id,
            {
                "id": learning_event_id,
                "client_id": client_id,
                **learning_event,
                "created_at": timestamp,
            },
        )
        document_ref = str(decision.get("document_ref") or learning_event.get("document_ref") or "")
        document = self._get_record(client_id, "document", document_ref)
        if document is not None:
            corrected_document = apply_review_decision_to_document(
                document,
                decision=decision,
                learning_event=learning_event,
                reviewed_at=timestamp,
            )
            self._upsert_record(client_id, "document", document_ref, corrected_document)
            record["corrected_document"] = corrected_document
            self._upsert_record(client_id, "review_decision", record["id"], record)
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
        return {
            "client": self._get_record(client_id, "client", client_id),
            "chart_accounts": self._get_record(client_id, "chart_accounts", client_id),
            "uploaded_documents": self._payloads(client_id, "uploaded_document"),
            "onboarding_attachments": self._payloads(client_id, "onboarding_attachment"),
            "documents": self._payloads(client_id, "document"),
            "processing_jobs": self._payloads(client_id, "processing_job"),
            "review_decisions": self._payloads(client_id, "review_decision"),
            "learning_events": self._payloads(client_id, "learning_event"),
            "export_packages": self._payloads(client_id, "export_package"),
            "portal_users": [
                user
                for user in self._payloads(PORTAL_USERS_CLIENT_ID, "portal_user")
                if client_id in set(user.get("allowed_client_ids") or []) or "*" in set(user.get("allowed_client_ids") or [])
            ],
            "operation_events": self.list_operation_events(client_id=client_id),
            "document_pipeline_events": self._payloads(client_id, "document_pipeline_event"),
        }

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
                cursor.execute(
                    """
                    insert into workflow_records (
                        id, tenant_id, client_id, record_type, record_key, payload
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (tenant_id, client_id, record_type, record_key)
                    do update set payload = excluded.payload, updated_at = now()
                    """,
                    (uuid4(), self.tenant_id, client_id, record_type, record_key, self._json(payload)),
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
                        taxpayer_uuid(client_id),
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
