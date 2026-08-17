from __future__ import annotations

import json
import shutil
import threading
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.ai_classification import merge_semantic_attempt_result, sanitize_semantic_evidence
from app.domain.document_uploads import extend_retention_deadline, retention_decision
from app.domain.storage_adapters import LocalDocumentStorage
from app.domain.qnb_credentials import QnbCredentialCipher
from app.domain.portal_access import (
    PORTAL_USERS_CLIENT_ID,
    build_portal_user_record,
    decide_portal_access,
)
from app.domain.session_auth import auth_token_public_payload, credential_public_payload, is_expired, session_public_payload
from app.domain.workspace_review_updates import (
    apply_review_decision_to_document,
    mark_export_package_downloaded,
)
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


PROCESSING_ATTEMPT_MARKER_KEY = "_processing_attempt"


class ProcessingAttemptConflict(RuntimeError):
    def __init__(self, *, attempt_id: str) -> None:
        super().__init__(f"processing attempt input conflict: {attempt_id}")
        self.attempt_id = attempt_id


class ResearchProfileConflict(RuntimeError):
    def __init__(self, *, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            f"research profile revision conflict: expected {expected_revision}, actual {actual_revision}"
        )
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


def simulation_input_digest(result: dict[str, Any]) -> str:
    """Digest the sanitized caller input before normalized persistence metadata."""

    sanitized = merge_semantic_attempt_result(result)
    sanitized.pop("normalized_revision", None)
    sanitized.pop("normalized_revision_status", None)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def matching_processing_attempt(
    record: dict[str, Any],
    *,
    attempt_id: str,
    input_digest: str,
) -> bool:
    marker = record.get(PROCESSING_ATTEMPT_MARKER_KEY)
    if not isinstance(marker, dict) or str(marker.get("attempt_id") or "") != attempt_id:
        return False
    if str(marker.get("input_digest") or "") != input_digest:
        raise ProcessingAttemptConflict(attempt_id=attempt_id)
    return True


def processing_attempt_marker(
    *,
    attempt_id: str,
    input_digest: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "input_digest": input_digest,
        "normalized_revision": result.get("normalized_revision"),
        "normalized_revision_status": str(result.get("normalized_revision_status") or ""),
    }


def empty_store() -> dict[str, Any]:
    return {
        "clients": {},
        "chart_accounts": {},
        "uploaded_documents": {},
        "onboarding_attachments": {},
        "documents": {},
        "processing_jobs": [],
        "review_decisions": [],
        "learning_events": [],
        "export_packages": [],
        "portal_users": {},
        "auth_credentials": {},
        "auth_sessions": {},
        "auth_tokens": {},
        "qnb_connections": {},
        "qnb_sync_runs": {},
        "qnb_sync_requests": {},
        "qnb_sync_policies": {},
        "qnb_sync_cursors": {},
        "qnb_document_identities": {},
        "document_identities": {},
        "qnb_outgoing_invoices": {},
        "qnb_outgoing_status_snapshots": {},
        "qnb_incoming_status_snapshots": {},
        "provider_document_links": {},
        "external_status_events": {},
        "document_safety_holds": {},
        "qnb_correction_reviews": {},
        "outgoing_invoices": {},
        "outgoing_invoice_send_keys": {},
        "outgoing_invoice_send_attempts": {},
        "ai_usage_events": [],
        "ai_capacity_snapshots": {},
        "operation_events": [],
        "document_pipeline_events": [],
        "nace_research_profiles": {},
        "brand_research_profiles": {},
        "research_benchmark_runs": [],
        "protected_corpora": {},
        "protected_corpus_items": {},
        "reference_outcome_versions": {},
        "protected_rule_versions": {},
    }


def normalize_nace_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_brand_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def research_profile_is_visible(
    profile: dict[str, Any],
    *,
    allowed_client_ids: set[str] | None,
) -> bool:
    """Apply server-derived client scope; ``None`` is trusted internal/admin access."""

    if allowed_client_ids is None or "*" in allowed_client_ids:
        return True
    owner = str(
        profile.get("owner_client_id")
        or profile.get("client_id")
        or profile.get("tenant_id")
        or ""
    )
    if owner:
        return owner in allowed_client_ids
    return str(profile.get("scope_type") or "legacy_unowned") == "office_public"


class JsonWorkflowStore:
    """Local persistence adapter for Phase 0 and demos.

    Production should swap this with a PostgreSQL-backed implementation using
    the same behavior surface. The default path lives under exports/, which is
    intentionally gitignored.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.tenant_key = "default"
        self.document_ai_artifact_repository = LocalDocumentAiArtifactRepository(
            manifest_path=self.path.with_name(
                f"{self.path.stem}.document-ai-artifacts.json"
            ),
            storage=LocalDocumentStorage(
                self.path.parent / f"{self.path.stem}.document-ai-artifact-bodies"
            ),
        )
        self._lock = threading.RLock()

    def _delete_document_ai_raw_bodies(
        self,
        *,
        client_id: str,
        document: dict[str, Any],
    ) -> int:
        document_id = str(document.get("document_id") or document.get("document_ref") or "")
        source_file_id = str(document.get("source_file_id") or document_id)
        if not source_file_id:
            return 0
        return self.document_ai_artifact_repository.delete_raw_bodies_for_source(
            tenant_id=self.tenant_key,
            taxpayer_id=client_id,
            source_file_id=source_file_id,
        )

    def upsert_client(self, *, client_id: str, profile: dict[str, Any], onboarding: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        clients = data["clients"]
        existing = clients.get(client_id, {})
        record = {
            **existing,
            "client_id": client_id,
            "profile": profile,
            "onboarding": onboarding,
            "updated_at": utc_now(),
        }
        record.setdefault("created_at", record["updated_at"])
        clients[client_id] = record
        self._write(data)
        return deepcopy(record)

    def list_clients(self) -> list[dict[str, Any]]:
        data = self._read()
        return [deepcopy(client) for client in data["clients"].values()]

    def replace_chart_accounts(self, *, client_id: str, accounts: list[dict[str, Any]]) -> dict[str, Any]:
        data = self._read()
        record = {
            "client_id": client_id,
            "account_count": len(accounts),
            "accounts": accounts,
            "updated_at": utc_now(),
        }
        data["chart_accounts"][client_id] = record
        self._write(data)
        return deepcopy(record)

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
        data = self._read()
        existing = data["portal_users"].get(user_id, {})
        record = {
            **existing,
            **build_portal_user_record(
                user_id=user_id,
                display_name=display_name,
                role=role,
                allowed_client_ids=allowed_client_ids,
            ),
            "updated_at": utc_now(),
        }
        record.setdefault("created_at", record["updated_at"])
        data["portal_users"][user_id] = record
        self._write(data)
        return deepcopy(record)

    def get_portal_user(self, user_id: str) -> dict[str, Any] | None:
        data = self._read()
        record = data["portal_users"].get(user_id)
        return deepcopy(record) if record else None

    def replace_client_portal_user(
        self,
        *,
        client_id: str,
        old_user_id: str,
        new_user_id: str,
        display_name: str = "",
    ) -> dict[str, Any]:
        normalized_client_id = client_id.strip()
        normalized_new_user_id = new_user_id.strip()
        normalized_old_user_id = old_user_id.strip()
        if not normalized_client_id:
            raise ValueError("client_id is required")
        if not normalized_new_user_id:
            raise ValueError("new_user_id is required")
        data = self._read()
        if normalized_client_id not in data["clients"]:
            raise ValueError("client not found")

        timestamp = utc_now()
        old_user = data["portal_users"].get(normalized_old_user_id) if normalized_old_user_id else None
        new_user = data["portal_users"].get(normalized_new_user_id) or {}
        existing_allowed = list(new_user.get("allowed_client_ids") or [])
        allowed_client_ids = list(dict.fromkeys([*existing_allowed, normalized_client_id]))
        fallback_display_name = str(
            display_name
            or new_user.get("display_name")
            or (old_user or {}).get("display_name")
            or normalized_new_user_id
        )
        record = {
            **new_user,
            **build_portal_user_record(
                user_id=normalized_new_user_id,
                display_name=fallback_display_name,
                role="client_user",
                allowed_client_ids=allowed_client_ids,
            ),
            "updated_at": timestamp,
        }
        record.setdefault("created_at", timestamp)
        data["portal_users"][normalized_new_user_id] = record

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
            else:
                self._remove_portal_user_auth_records(data, normalized_old_user_id)
                data["portal_users"].pop(normalized_old_user_id, None)
                old_user_removed = True
        self._write(data)
        return {
            "client_id": normalized_client_id,
            "old_user_id": normalized_old_user_id,
            "new_user_id": normalized_new_user_id,
            "old_user_removed": old_user_removed,
            "portal_user": deepcopy(record),
        }

    def verify_portal_access(self, *, client_id: str, user_id: str) -> dict[str, Any]:
        data = self._read()
        decision = decide_portal_access(
            portal_user=data["portal_users"].get(user_id),
            client_exists=client_id in data["clients"],
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
        data = self._read()
        timestamp = utc_now()
        existing = data["auth_credentials"].get(user_id, {})
        record = {
            **existing,
            "user_id": user_id,
            "password_hash": password_hash,
            "updated_at": timestamp,
        }
        record.setdefault("created_at", timestamp)
        data["auth_credentials"][user_id] = record
        self._write(data)
        return credential_public_payload(record)

    def get_auth_password_hash(self, *, user_id: str) -> str:
        data = self._read()
        credential = data["auth_credentials"].get(user_id) or {}
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
        data = self._read()
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
        data["auth_sessions"][token_hash] = record
        self._write(data)
        return session_public_payload(record)

    def resolve_auth_session(self, *, token_hash: str) -> dict[str, Any]:
        data = self._read()
        record = data["auth_sessions"].get(token_hash)
        if not record:
            return {"valid": False, "reason": "session_not_found"}
        if record.get("revoked_at"):
            return {"valid": False, "reason": "session_revoked", "user_id": record.get("user_id", "")}
        if is_expired(str(record.get("expires_at") or "")):
            return {"valid": False, "reason": "session_expired", "user_id": record.get("user_id", "")}
        return {"valid": True, "reason": "session_valid", **session_public_payload(record)}

    def revoke_auth_session(self, *, token_hash: str) -> dict[str, Any]:
        data = self._read()
        record = data["auth_sessions"].get(token_hash)
        if not record:
            return {"revoked": False, "reason": "session_not_found"}
        record["revoked_at"] = utc_now()
        record["updated_at"] = record["revoked_at"]
        self._write(data)
        return {"revoked": True, "reason": "session_revoked", **session_public_payload(record)}

    def create_auth_token(
        self,
        *,
        purpose: str,
        user_id: str,
        token_hash: str,
        expires_at: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._read()
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
        data["auth_tokens"][token_hash] = record
        self._write(data)
        return auth_token_public_payload(record)

    def resolve_auth_token(self, *, purpose: str, token_hash: str) -> dict[str, Any]:
        data = self._read()
        record = data["auth_tokens"].get(token_hash)
        if not record or record.get("purpose") != purpose:
            return {"valid": False, "reason": "token_not_found"}
        if record.get("used_at"):
            return {"valid": False, "reason": "token_used", "user_id": record.get("user_id", "")}
        if is_expired(str(record.get("expires_at") or "")):
            return {"valid": False, "reason": "token_expired", "user_id": record.get("user_id", "")}
        return {"valid": True, "reason": "token_valid", **auth_token_public_payload(record), "payload": deepcopy(record.get("payload") or {})}

    def mark_auth_token_used(self, *, token_hash: str) -> dict[str, Any]:
        data = self._read()
        record = data["auth_tokens"].get(token_hash)
        if not record:
            return {"used": False, "reason": "token_not_found"}
        record["used_at"] = utc_now()
        record["updated_at"] = record["used_at"]
        self._write(data)
        return {"used": True, "reason": "token_used", **auth_token_public_payload(record)}

    def record_ai_usage(self, *, client_id: str, event: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        record = {
            **event,
            "client_id": client_id,
        }
        data["ai_usage_events"].append(record)
        self._write(data)
        return deepcopy(record)

    def list_ai_usage(self, *, client_id: str) -> list[dict[str, Any]]:
        data = self._read()
        return [
            deepcopy(event)
            for event in data["ai_usage_events"]
            if event.get("client_id") == client_id
        ]

    def record_ai_capacity_snapshot(self, *, provider: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        key = str(provider or "").strip().lower()
        if not key:
            raise ValueError("provider is required")
        record = {
            **snapshot,
            "provider": key,
            "updated_at": utc_now(),
        }
        data["ai_capacity_snapshots"][key] = record
        self._write(data)
        return deepcopy(record)

    def latest_ai_capacity_snapshots(self) -> dict[str, dict[str, Any]]:
        data = self._read()
        return deepcopy(data["ai_capacity_snapshots"])

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
        data = self._read()
        preserved_users = {
            user_id: user
            for user_id, user in data["portal_users"].items()
            if str(user.get("role") or "").strip().lower() in {"accountant", "admin"}
        }
        preserved_credentials = {
            user_id: credential
            for user_id, credential in data["auth_credentials"].items()
            if user_id in preserved_users
        }
        deleted_portal_user_count = len(data["portal_users"]) - len(preserved_users)
        deleted_record_count = (
            len(data["clients"])
            + len(data["chart_accounts"])
            + len(data["uploaded_documents"])
            + len(data["onboarding_attachments"])
            + len(data["documents"])
            + len(data["processing_jobs"])
            + len(data["review_decisions"])
            + len(data["learning_events"])
            + len(data["export_packages"])
            + len(data["auth_sessions"])
            + len(data["auth_tokens"])
            + len(data["ai_usage_events"])
            + len(data["ai_capacity_snapshots"])
            + len(data["operation_events"])
            + len(data["document_pipeline_events"])
            + len(data["nace_research_profiles"])
            + len(data["brand_research_profiles"])
            + len(data["research_benchmark_runs"])
            + deleted_portal_user_count
            + (len(data["auth_credentials"]) - len(preserved_credentials))
        )
        deleted_client_count = len(data["clients"])
        data.update(
            {
                "clients": {},
                "chart_accounts": {},
                "uploaded_documents": {},
                "onboarding_attachments": {},
                "documents": {},
                "processing_jobs": [],
                "review_decisions": [],
                "learning_events": [],
                "export_packages": [],
                "portal_users": preserved_users,
                "auth_credentials": preserved_credentials,
                "auth_sessions": {},
                "auth_tokens": {},
                "ai_usage_events": [],
                "ai_capacity_snapshots": {},
                "operation_events": [],
                "document_pipeline_events": [],
                "nace_research_profiles": {},
                "brand_research_profiles": {},
                "research_benchmark_runs": [],
            }
        )
        self._write(data)
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
            "preserved_portal_user_count": len(preserved_users),
            "preserved_user_ids": sorted(preserved_users),
            **self._protected_reset_counts(data),
        }

    def preview_test_data_reset(self) -> dict[str, Any]:
        data = self._read()
        return {
            "reset": False,
            "preview": True,
            "deleted_client_count": len(data["clients"]),
            "deleted_uploaded_document_count": len(data["uploaded_documents"]),
            "deleted_review_decision_count": len(data["review_decisions"]),
            **self._protected_reset_counts(data),
        }

    @staticmethod
    def _protected_reset_counts(data: dict[str, Any]) -> dict[str, int]:
        return {
            "preserved_protected_corpus_count": len(data["protected_corpora"]),
            "preserved_protected_item_count": len(data["protected_corpus_items"]),
            "preserved_reference_outcome_count": len(data["reference_outcome_versions"]),
            "preserved_protected_rule_count": len(data["protected_rule_versions"]),
        }

    def record_operation_event(self, *, client_id: str, event: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        record = {
            **event,
            "client_id": client_id,
        }
        data["operation_events"].append(record)
        self._write(data)
        return deepcopy(record)

    def list_operation_events(self, *, client_id: str, limit: int = 50) -> list[dict[str, Any]]:
        data = self._read()
        events = [
            deepcopy(event)
            for event in data["operation_events"]
            if event.get("client_id") == client_id
        ]
        return events[-max(limit, 1):]

    def save_qnb_connection(self, *, client_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        timestamp = utc_now()
        existing = data.get("qnb_connections", {}).get(client_id, {})
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
        data.setdefault("qnb_connections", {})[client_id] = record
        self._write(data)
        return deepcopy(record)

    def get_qnb_connection(self, *, client_id: str) -> dict[str, Any] | None:
        data = self._read()
        record = data.get("qnb_connections", {}).get(client_id)
        return deepcopy(record) if record else None

    def save_qnb_sync_run(self, *, client_id: str, sync_run: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        record = {
            **sync_run,
            "client_id": client_id,
            "updated_at": utc_now(),
        }
        record.setdefault("sync_run_id", str(uuid4()))
        record.setdefault("created_at", record["updated_at"])
        key = f"{client_id}:{record['sync_run_id']}"
        data.setdefault("qnb_sync_runs", {})[key] = record
        self._write(data)
        return deepcopy(record)

    def list_qnb_sync_runs(self, *, client_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = [deepcopy(row) for row in self._read().get("qnb_sync_runs", {}).values() if row.get("client_id") == client_id]
        return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)[:max(limit, 1)]

    def enqueue_qnb_sync_request(
        self,
        *,
        client_id: str,
        start_date: str = "",
        end_date: str = "",
        requested_by: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            request_id = str(uuid4())
            timestamp = utc_now()
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
            data["qnb_sync_requests"][f"{client_id}:{request_id}"] = record
            self._write(data)
        return deepcopy(record)

    def claim_next_qnb_sync_request(
        self,
        *,
        worker_id: str,
        now: str,
        lease_expires_at: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            requests = sorted(
                data["qnb_sync_requests"].values(),
                key=lambda row: str(row.get("created_at") or ""),
            )
            for request in requests:
                status = str(request.get("status") or "")
                lease_expired = (
                    status == "processing"
                    and str(request.get("lease_expires_at") or "") <= now
                )
                if status != "queued" and not lease_expired:
                    continue
                request.update(
                    {
                        "status": "processing",
                        "lease_owner": worker_id,
                        "lease_token": str(uuid4()),
                        "lease_expires_at": lease_expires_at,
                        "updated_at": utc_now(),
                    }
                )
                self._write(data)
                return deepcopy(request)
        return None

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
        with self._lock:
            data = self._read()
            request = data["qnb_sync_requests"].get(
                f"{client_id}:{request_id}"
            )
            if (
                not request
                or request.get("lease_owner") != worker_id
                or request.get("lease_token") != lease_token
            ):
                return False
            request.update(
                {
                    "status": status,
                    "result": deepcopy(result),
                    "lease_owner": "",
                    "lease_token": "",
                    "lease_expires_at": "",
                    "completed_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            self._write(data)
        return True

    def save_qnb_sync_policy(self, *, client_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            timestamp = utc_now()
            existing = data.setdefault("qnb_sync_policies", {}).get(client_id, {})
            record = {**existing, **policy, "client_id": client_id, "updated_at": timestamp}
            record.setdefault("created_at", timestamp)
            data["qnb_sync_policies"][client_id] = record
            self._write(data)
        return deepcopy(record)

    def get_qnb_sync_policy(self, *, client_id: str) -> dict[str, Any] | None:
        record = self._read().get("qnb_sync_policies", {}).get(client_id)
        return deepcopy(record) if record else None

    def claim_due_qnb_sync_policy(self, *, worker_id: str, now: str, lease_expires_at: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            policies = data.setdefault("qnb_sync_policies", {})
            candidates = sorted(policies.values(), key=lambda row: str(row.get("next_run_at") or ""))
            for policy in candidates:
                if not policy.get("enabled") or str(policy.get("next_run_at") or "") > now:
                    continue
                if str(policy.get("lease_expires_at") or "") > now:
                    continue
                policy.update(
                    {
                        "lease_owner": worker_id,
                        "lease_token": str(uuid4()),
                        "lease_expires_at": lease_expires_at,
                        "last_attempt_at": now,
                    }
                )
                self._write(data)
                return deepcopy(policy)
        return None

    def renew_qnb_sync_policy_lease(
        self,
        *,
        client_id: str,
        worker_id: str,
        lease_token: str,
        lease_expires_at: str,
    ) -> bool:
        with self._lock:
            data = self._read()
            policy = data.setdefault("qnb_sync_policies", {}).get(client_id)
            if (
                not policy
                or policy.get("lease_owner") != worker_id
                or policy.get("lease_token") != lease_token
            ):
                return False
            policy["lease_expires_at"] = lease_expires_at
            policy["lease_renewed_at"] = utc_now()
            self._write(data)
        return True

    def complete_qnb_sync_policy(
        self,
        *,
        client_id: str,
        worker_id: str,
        lease_token: str,
        updates: dict[str, Any],
    ) -> bool:
        with self._lock:
            data = self._read()
            policy = data.setdefault("qnb_sync_policies", {}).get(client_id)
            if (
                not policy
                or policy.get("lease_owner") != worker_id
                or policy.get("lease_token") != lease_token
            ):
                return False
            policy.update(updates)
            policy.update(
                {
                    "lease_owner": "",
                    "lease_token": "",
                    "lease_expires_at": "",
                    "updated_at": utc_now(),
                }
            )
            self._write(data)
        return True

    def get_qnb_sync_cursor(self, *, client_id: str) -> str:
        data = self._read()
        return str(data.get("qnb_sync_cursors", {}).get(client_id) or "")

    def save_qnb_sync_cursor(self, *, client_id: str, cursor: str) -> str:
        with self._lock:
            data = self._read()
            data.setdefault("qnb_sync_cursors", {})[client_id] = str(cursor or "")
            self._write(data)
        return str(cursor or "")

    def claim_qnb_document_identity(
        self,
        *,
        client_id: str,
        identity_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        key = f"{client_id}:{identity_key}"
        with self._lock:
            data = self._read()
            identities = data.setdefault("qnb_document_identities", {})
            if key in identities:
                return False
            identities[key] = {
                "client_id": client_id,
                "identity_key": identity_key,
                "metadata": metadata or {},
                "claimed_at": utc_now(),
            }
            self._write(data)
        return True

    def release_qnb_document_identity(self, *, client_id: str, identity_key: str) -> None:
        key = f"{client_id}:{identity_key}"
        with self._lock:
            data = self._read()
            data.setdefault("qnb_document_identities", {}).pop(key, None)
            self._write(data)

    def save_qnb_outgoing_invoice(self, *, client_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
        oid = str(invoice.get("document_oid") or "")
        if not oid:
            raise ValueError("QNB outgoing document OID is required")
        key = f"{client_id}:{oid}"
        with self._lock:
            data = self._read()
            rows = data.setdefault("qnb_outgoing_invoices", {})
            record = {**rows.get(key, {}), **invoice, "client_id": client_id}
            rows[key] = record
            self._write(data)
        return deepcopy(record)

    def get_qnb_outgoing_invoice(self, *, client_id: str, document_oid: str) -> dict[str, Any] | None:
        record = self._read().get("qnb_outgoing_invoices", {}).get(f"{client_id}:{document_oid}")
        return deepcopy(record) if record else None

    def list_qnb_outgoing_invoices(self, *, client_id: str) -> list[dict[str, Any]]:
        return [deepcopy(row) for row in self._read().get("qnb_outgoing_invoices", {}).values() if row.get("client_id") == client_id]

    def append_qnb_outgoing_status_snapshot(self, *, client_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        record = {**snapshot, "client_id": client_id}
        with self._lock:
            data = self._read()
            data.setdefault("qnb_outgoing_status_snapshots", {})[f"{client_id}:{record['snapshot_id']}"] = record
            self._write(data)
        return deepcopy(record)

    def append_qnb_incoming_status_snapshot(self, *, client_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        record = {**snapshot, "client_id": client_id}
        with self._lock:
            data = self._read()
            data.setdefault("qnb_incoming_status_snapshots", {})[f"{client_id}:{record['snapshot_id']}"] = record
            self._write(data)
        return deepcopy(record)

    def save_outgoing_invoice(self, *, client_id: str, invoice: dict[str, Any]) -> dict[str, Any]:
        invoice_id = str(invoice.get("invoice_id") or "")
        if not invoice_id:
            raise ValueError("Outgoing invoice ID is required")
        key = f"{client_id}:{invoice_id}"
        with self._lock:
            data = self._read()
            rows = data.setdefault("outgoing_invoices", {})
            record = {**rows.get(key, {}), **invoice, "client_id": client_id}
            rows[key] = record
            self._write(data)
        return deepcopy(record)

    def get_outgoing_invoice(self, *, client_id: str, invoice_id: str) -> dict[str, Any] | None:
        record = self._read().get("outgoing_invoices", {}).get(f"{client_id}:{invoice_id}")
        return deepcopy(record) if record else None

    def list_outgoing_invoices(self, *, client_id: str) -> list[dict[str, Any]]:
        rows = self._read().get("outgoing_invoices", {}).values()
        return [deepcopy(row) for row in rows if row.get("client_id") == client_id]

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
        idempotency_key_hash = sha256(idempotency_key.encode("utf-8")).hexdigest()
        claim_key = f"{client_id}:{idempotency_key_hash}"
        invoice_key = f"{client_id}:{invoice_id}"
        with self._lock:
            data = self._read()
            claims = data.setdefault("outgoing_invoice_send_keys", {})
            attempts = data.setdefault("outgoing_invoice_send_attempts", {})
            invoices = data.setdefault("outgoing_invoices", {})
            existing = claims.get(claim_key)
            if existing:
                if existing.get("invoice_id") != invoice_id:
                    raise ValueError("Idempotency key is already used for another invoice")
                if existing.get("ubl_sha256") != ubl_sha256:
                    raise ValueError("Idempotency key is already used for another UBL hash")
                attempt = attempts.get(f"{client_id}:{existing.get('attempt_id')}")
                invoice = invoices.get(invoice_key)
                if not invoice or not attempt:
                    raise ValueError("Outgoing invoice attempt is incomplete")
                return False, deepcopy(invoice), deepcopy(attempt)
            invoice = invoices.get(invoice_key)
            if not invoice:
                raise ValueError("Outgoing invoice not found")
            if invoice.get("status") != "approved":
                raise ValueError("Only an approved invoice can be sent")
            attempt_id = str(uuid4())
            claimed_at = utc_now()
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
            claims[claim_key] = {
                "client_id": client_id,
                "invoice_id": invoice_id,
                "idempotency_key_hash": idempotency_key_hash,
                "ubl_sha256": ubl_sha256,
                "attempt_id": attempt_id,
                "claimed_at": claimed_at,
            }
            attempts[f"{client_id}:{attempt_id}"] = attempt
            invoice = {
                **invoice,
                "status": "sending",
                "current_attempt_id": attempt_id,
                "updated_at": claimed_at,
            }
            invoices[invoice_key] = invoice
            self._write(data)
        return True, deepcopy(invoice), deepcopy(attempt)

    def append_outgoing_invoice_attempt_event(
        self,
        *,
        client_id: str,
        attempt_id: str,
        event: str,
        state: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = f"{client_id}:{attempt_id}"
        with self._lock:
            data = self._read()
            attempts = data.setdefault("outgoing_invoice_send_attempts", {})
            attempt = attempts.get(key)
            if not attempt:
                raise ValueError("Outgoing invoice attempt not found")
            now = utc_now()
            attempt = deepcopy(attempt)
            attempt.setdefault("events", []).append(
                {"event": event, "at": now, "details": deepcopy(details or {})}
            )
            if state:
                attempt["state"] = state
                if state != "reconciling":
                    attempt.pop("reconciliation_owner", None)
                    attempt.pop("reconciliation_lease_expires_at", None)
            attempt["updated_at"] = now
            attempts[key] = attempt
            self._write(data)
        return deepcopy(attempt)

    def get_outgoing_invoice_attempt(self, *, client_id: str, attempt_id: str) -> dict[str, Any] | None:
        row = self._read().get("outgoing_invoice_send_attempts", {}).get(f"{client_id}:{attempt_id}")
        return deepcopy(row) if row else None

    def claim_outgoing_invoice_reconciliation(
        self,
        *,
        client_id: str,
        attempt_id: str,
        owner_id: str,
        stale_before: str,
        lease_expires_at: str,
    ) -> tuple[bool, dict[str, Any]]:
        key = f"{client_id}:{attempt_id}"
        with self._lock:
            data = self._read()
            attempts = data.setdefault("outgoing_invoice_send_attempts", {})
            attempt = attempts.get(key)
            if not attempt:
                raise ValueError("Outgoing invoice attempt not found")
            now = utc_now()
            active_lease = str(attempt.get("reconciliation_lease_expires_at") or "")
            if active_lease and active_lease > now:
                return False, deepcopy(attempt)
            state = str(attempt.get("state") or "")
            if state == "request_started":
                request_started_at = next(
                    (
                        str(event.get("at") or "")
                        for event in reversed(attempt.get("events") or [])
                        if event.get("event") == "request_started"
                    ),
                    "",
                )
                if not request_started_at or request_started_at > stale_before:
                    return False, deepcopy(attempt)
            elif state not in {"reconciliation_required", "reconciling"}:
                return False, deepcopy(attempt)
            updated = deepcopy(attempt)
            updated.setdefault("events", []).append(
                {"event": "reconciliation_started", "at": now, "details": {}}
            )
            updated.update(
                {
                    "state": "reconciling",
                    "reconciliation_owner": owner_id,
                    "reconciliation_lease_expires_at": lease_expires_at,
                    "updated_at": now,
                }
            )
            attempts[key] = updated
            self._write(data)
        return True, deepcopy(updated)

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
        key = f"{client_id}:{attempt_id}"
        with self._lock:
            data = self._read()
            attempts = data.setdefault("outgoing_invoice_send_attempts", {})
            attempt = attempts.get(key)
            if not attempt:
                raise ValueError("Outgoing invoice attempt not found")
            if str(attempt.get("state") or "") != expected_state:
                return False, deepcopy(attempt)
            if reconciliation_owner and attempt.get("reconciliation_owner") != reconciliation_owner:
                return False, deepcopy(attempt)
            now = utc_now()
            updated = deepcopy(attempt)
            updated.setdefault("events", []).append(
                {"event": event, "at": now, "details": deepcopy(details or {})}
            )
            updated["state"] = state
            updated["updated_at"] = now
            updated.pop("reconciliation_owner", None)
            updated.pop("reconciliation_lease_expires_at", None)
            attempts[key] = updated
            self._write(data)
        return True, deepcopy(updated)

    def finalize_outgoing_invoice_attempt_and_invoice(
        self, *, client_id: str, attempt_id: str, expected_state: str, event: str,
        state: str, invoice: dict[str, Any], details: dict[str, Any] | None = None,
        reconciliation_owner: str = "",
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        key = f"{client_id}:{attempt_id}"
        invoice_key = f"{client_id}:{invoice.get('invoice_id')}"
        with self._lock:
            data = self._read()
            attempts = data.setdefault("outgoing_invoice_send_attempts", {})
            current = attempts.get(key)
            if not current:
                raise ValueError("Outgoing invoice attempt not found")
            if str(current.get("state") or "") != expected_state:
                return False, deepcopy(invoice), deepcopy(current)
            if reconciliation_owner and current.get("reconciliation_owner") != reconciliation_owner:
                return False, deepcopy(invoice), deepcopy(current)
            now = utc_now()
            updated = deepcopy(current)
            updated.setdefault("events", []).append(
                {"event": event, "at": now, "details": deepcopy(details or {})}
            )
            updated.update({"state": state, "updated_at": now})
            updated.pop("reconciliation_owner", None)
            updated.pop("reconciliation_lease_expires_at", None)
            attempts[key] = updated
            data.setdefault("outgoing_invoices", {})[invoice_key] = deepcopy(invoice)
            self._write(data)
        return True, deepcopy(invoice), deepcopy(updated)

    def list_outgoing_invoice_attempts(self, *, client_id: str, invoice_id: str = "") -> list[dict[str, Any]]:
        rows = self._read().get("outgoing_invoice_send_attempts", {}).values()
        return [
            deepcopy(row)
            for row in rows
            if row.get("client_id") == client_id and (not invoice_id or row.get("invoice_id") == invoice_id)
        ]

    def claim_outgoing_invoice_send(
        self, *, client_id: str, invoice_id: str, idempotency_key: str
    ) -> tuple[bool, dict[str, Any] | None]:
        claim_key = f"{client_id}:{idempotency_key}"
        invoice_key = f"{client_id}:{invoice_id}"
        with self._lock:
            data = self._read()
            claims = data.setdefault("outgoing_invoice_send_keys", {})
            if claim_key in claims:
                existing_invoice = claims[claim_key].get("invoice_id")
                if existing_invoice != invoice_id:
                    raise ValueError("Idempotency key is already used for another invoice")
                return False, deepcopy(data.setdefault("outgoing_invoices", {}).get(invoice_key))
            invoices = data.setdefault("outgoing_invoices", {})
            invoice = invoices.get(invoice_key)
            if not invoice:
                raise ValueError("Outgoing invoice not found")
            if invoice.get("status") != "approved":
                raise ValueError("Only an approved invoice can be sent")
            claims[claim_key] = {
                "client_id": client_id,
                "invoice_id": invoice_id,
                "idempotency_key": idempotency_key,
                "claimed_at": utc_now(),
            }
            invoice = {**invoice, "status": "sending", "updated_at": utc_now()}
            invoices[invoice_key] = invoice
            self._write(data)
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
        data = self._read()
        record = {
            "event_id": str(uuid4()),
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
        data["document_pipeline_events"].append(record)
        self._write(data)
        return deepcopy(record)

    def list_document_pipeline_events(
        self,
        *,
        client_id: str,
        document_ref: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        data = self._read()
        events = [
            deepcopy(event)
            for event in data["document_pipeline_events"]
            if event.get("client_id") == client_id and event.get("document_ref") == document_ref
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
        with self._lock:
            data = self._read()
            existing = data["nace_research_profiles"].get(normalized, {})
            actual_revision = int(existing.get("revision") or 0)
            if expected_revision is not None and actual_revision != expected_revision:
                raise ResearchProfileConflict(
                    expected_revision=expected_revision,
                    actual_revision=actual_revision,
                )
            timestamp = utc_now()
            record = {
                **existing,
                **profile,
                "nace_code": normalized,
                "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
                "updated_at": timestamp,
                "revision": actual_revision + 1,
            }
            data["nace_research_profiles"][normalized] = record
            self._write(data)
            return deepcopy(record)

    def get_nace_research_profile(self, nace_code: str) -> dict[str, Any] | None:
        data = self._read()
        profile = data["nace_research_profiles"].get(normalize_nace_code(nace_code))
        return deepcopy(profile) if profile else None

    def save_brand_research_profile(
        self,
        *,
        brand_name: str,
        profile: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_brand_name(brand_name)
        with self._lock:
            data = self._read()
            existing = data["brand_research_profiles"].get(normalized, {})
            actual_revision = int(existing.get("revision") or 0)
            if expected_revision is not None and actual_revision != expected_revision:
                raise ResearchProfileConflict(
                    expected_revision=expected_revision,
                    actual_revision=actual_revision,
                )
            timestamp = utc_now()
            record = {
                **existing,
                **profile,
                "brand_name": normalized,
                "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
                "updated_at": timestamp,
                "revision": actual_revision + 1,
            }
            data["brand_research_profiles"][normalized] = record
            self._write(data)
            return deepcopy(record)

    def get_brand_research_profile(self, brand_name: str) -> dict[str, Any] | None:
        data = self._read()
        profile = data["brand_research_profiles"].get(normalize_brand_name(brand_name))
        return deepcopy(profile) if profile else None

    def get_research_profile(
        self,
        *,
        kind: str,
        key: str,
        allowed_client_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        if kind == "nace":
            profile = self.get_nace_research_profile(key)
        elif kind == "brand":
            profile = self.get_brand_research_profile(key)
        else:
            return None
        if profile and research_profile_is_visible(profile, allowed_client_ids=allowed_client_ids):
            return profile
        return None

    def list_research_profiles(
        self,
        *,
        kind: str = "",
        allowed_client_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        data = self._read()
        profiles: list[dict[str, Any]] = []
        if kind in {"", "brand"}:
            profiles.extend(deepcopy(profile) for profile in data["brand_research_profiles"].values())
        if kind in {"", "nace"}:
            profiles.extend(deepcopy(profile) for profile in data["nace_research_profiles"].values())
        return sorted(
            [
                profile
                for profile in profiles
                if research_profile_is_visible(profile, allowed_client_ids=allowed_client_ids)
            ],
            key=lambda profile: str(profile.get("updated_at") or profile.get("researched_at") or ""),
            reverse=True,
        )

    def save_research_benchmark_run(self, run: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        timestamp = utc_now()
        record = {
            "run_id": str(uuid4()),
            "run_type": "benchmark",
            "created_at": timestamp,
            **run,
        }
        data["research_benchmark_runs"].append(record)
        self._write(data)
        return deepcopy(record)

    def list_research_benchmark_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        data = self._read()
        return deepcopy(data["research_benchmark_runs"][-max(limit, 1):])

    def create_protected_corpus(
        self,
        *,
        corpus_key: str,
        version: int,
        target_purchase_count: int,
        target_sales_count: int,
        created_by: str,
    ) -> dict[str, Any]:
        data = self._read()
        duplicate = next(
            (
                corpus
                for corpus in data["protected_corpora"].values()
                if corpus.get("corpus_key") == corpus_key and int(corpus.get("version") or 0) == version
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError("duplicate_corpus_version")
        corpus_id = str(uuid4())
        timestamp = utc_now()
        record = {
            "corpus_id": corpus_id,
            "corpus_key": corpus_key,
            "version": version,
            "status": "draft",
            "target_purchase_count": target_purchase_count,
            "target_sales_count": target_sales_count,
            "created_by": created_by,
            "created_at": timestamp,
            "updated_at": timestamp,
            "frozen_at": "",
        }
        data["protected_corpora"][corpus_id] = record
        self._write(data)
        return deepcopy(record)

    def get_protected_corpus(self, corpus_id: str) -> dict[str, Any] | None:
        data = self._read()
        record = data["protected_corpora"].get(corpus_id)
        return deepcopy(record) if record else None

    def add_protected_corpus_item(self, *, item: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        corpus_id = str(item.get("corpus_id") or "")
        corpus = data["protected_corpora"].get(corpus_id)
        if not corpus:
            raise ValueError("corpus_not_found")
        if corpus.get("status") != "draft":
            raise ValueError("corpus_frozen")
        source_sha256 = str(item.get("source_sha256") or "")
        if any(
            existing.get("corpus_id") == corpus_id and existing.get("source_sha256") == source_sha256
            for existing in data["protected_corpus_items"].values()
        ):
            raise ValueError("duplicate_corpus_source")
        item_id = str(item.get("item_id") or uuid4())
        timestamp = utc_now()
        record = {
            **item,
            "item_id": item_id,
            "corpus_item_id": item_id,
            "status": str(item.get("status") or "candidate"),
            "current_reference_version": int(item.get("current_reference_version") or 0),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        data["protected_corpus_items"][item_id] = record
        self._write(data)
        return deepcopy(record)

    def list_protected_items(self, corpus_id: str) -> list[dict[str, Any]]:
        data = self._read()
        return [
            deepcopy(item)
            for item in data["protected_corpus_items"].values()
            if item.get("corpus_id") == corpus_id
        ]

    def protected_item_for_document(self, *, client_id: str, document_ref: str) -> dict[str, Any] | None:
        data = self._read()
        candidates = [
            item
            for item in data["protected_corpus_items"].values()
            if item.get("client_id") == client_id
            and item.get("document_ref") == document_ref
            and (data["protected_corpora"].get(str(item.get("corpus_id") or "")) or {}).get("status") != "archived"
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: int(
                (data["protected_corpora"].get(str(item.get("corpus_id") or "")) or {}).get("version") or 0
            ),
            reverse=True,
        )
        return deepcopy(candidates[0])

    def append_reference_outcome(self, *, corpus_item_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        item = data["protected_corpus_items"].get(corpus_item_id)
        if not item:
            raise ValueError("corpus_item_not_found")
        corpus = data["protected_corpora"].get(str(item.get("corpus_id") or ""))
        if not corpus or corpus.get("status") != "draft":
            raise ValueError("corpus_frozen")
        version = int(item.get("current_reference_version") or 0) + 1
        record_id = str(uuid4())
        record = {
            **deepcopy(outcome),
            "reference_id": record_id,
            "corpus_item_id": corpus_item_id,
            "version": version,
            "created_at": utc_now(),
        }
        data["reference_outcome_versions"][record_id] = record
        item["current_reference_version"] = version
        if bool(record.get("is_authoritative")):
            item["status"] = "reference_ready"
        item["updated_at"] = record["created_at"]
        self._write(data)
        return deepcopy(record)

    def list_reference_outcomes(self, corpus_item_id: str) -> list[dict[str, Any]]:
        data = self._read()
        records = [
            deepcopy(record)
            for record in data["reference_outcome_versions"].values()
            if record.get("corpus_item_id") == corpus_item_id
        ]
        return sorted(records, key=lambda record: int(record.get("version") or 0))

    def append_protected_rule(self, *, corpus_item_id: str, rule: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        item = data["protected_corpus_items"].get(corpus_item_id)
        if not item:
            raise ValueError("corpus_item_not_found")
        corpus = data["protected_corpora"].get(str(item.get("corpus_id") or ""))
        if not corpus or corpus.get("status") != "draft":
            raise ValueError("corpus_frozen")
        reference_version = int(rule.get("reference_version") or 0)
        if not any(
            record.get("corpus_item_id") == corpus_item_id
            and int(record.get("version") or 0) == reference_version
            for record in data["reference_outcome_versions"].values()
        ):
            raise ValueError("reference_version_not_found")
        rule_key = str(rule.get("rule_key") or "").strip()
        version = 1 + max(
            (
                int(existing.get("version") or 0)
                for existing in data["protected_rule_versions"].values()
                if existing.get("rule_key") == rule_key
            ),
            default=0,
        )
        record_id = str(uuid4())
        record = {
            **deepcopy(rule),
            "protected_rule_id": record_id,
            "corpus_item_id": corpus_item_id,
            "version": version,
            "created_at": utc_now(),
        }
        data["protected_rule_versions"][record_id] = record
        self._write(data)
        return deepcopy(record)

    def list_protected_rules(self, corpus_item_id: str) -> list[dict[str, Any]]:
        data = self._read()
        return [
            deepcopy(record)
            for record in data["protected_rule_versions"].values()
            if record.get("corpus_item_id") == corpus_item_id
        ]

    def freeze_protected_corpus(self, corpus_id: str) -> dict[str, Any]:
        data = self._read()
        corpus = data["protected_corpora"].get(corpus_id)
        if not corpus:
            raise ValueError("corpus_not_found")
        timestamp = utc_now()
        corpus["status"] = "frozen"
        corpus["frozen_at"] = timestamp
        corpus["updated_at"] = timestamp
        self._write(data)
        return deepcopy(corpus)

    def save_uploaded_document(self, *, client_id: str, document: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        document_ref = str(document.get("document_id") or document.get("original_file_name") or uuid4())
        document_key = self._document_key(client_id, document_ref)
        record = {
            **document,
            "client_id": client_id,
            "document_ref": document_ref,
            "updated_at": utc_now(),
        }
        record.setdefault("created_at", record["updated_at"])
        data["uploaded_documents"][document_key] = record
        self._write(data)
        return deepcopy(record)

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
        with self._lock:
            data = self._read()
            document_key = self._document_key(client_id, document_ref)
            document = data["uploaded_documents"].get(document_key)
            if not document:
                raise ValueError("document_not_found")
            provider_link_key = f"{client_id}:qnb_esolutions:{ettn}"
            provider_link = data["provider_document_links"].setdefault(
                provider_link_key,
                {
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "provider": "qnb_esolutions",
                    "external_identity": ettn,
                    "created_at": checked_at,
                },
            )
            status_event_key = f"{client_id}:{event_key}"
            event = data["external_status_events"].get(status_event_key)
            if event is None:
                event = {
                    "event_key": event_key,
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "provider": "qnb_esolutions",
                    "external_identity": ettn,
                    "normalized_status": normalized_status,
                    "response_code": response_code,
                    "response_detail": response_detail,
                    "cancelled_at": cancelled_at,
                    "checked_at": checked_at,
                    "created_at": utc_now(),
                }
                data["external_status_events"][status_event_key] = event
            provider_link.update(
                {
                    "document_ref": document_ref,
                    "current_status": normalized_status,
                    "current_status_event_key": event_key,
                    "updated_at": checked_at,
                }
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
                "review_required": normalized_status in blocking_statuses,
            }
            data["qnb_incoming_status_snapshots"][status_event_key] = snapshot
            hold_key = f"{client_id}:{document_ref}"
            hold = data["document_safety_holds"].get(hold_key)
            if normalized_status in blocking_statuses and hold is None:
                hold = {
                    "id": str(uuid4()),
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "hold_code": f"qnb_status_{normalized_status}",
                    "trigger_event_key": event_key,
                    "created_at": checked_at,
                    "resolved_at": "",
                }
                data["document_safety_holds"][hold_key] = hold
            automation_hold = bool(hold and not hold.get("resolved_at"))
            delivered_packages = [
                record
                for record in data["export_packages"]
                if record.get("client_id") == client_id
                and (record.get("package") or {}).get("downloaded_at")
                and any(
                    str(entry.get("document_ref") or "").split("#", 1)[0]
                    == document_ref
                    for entry in (record.get("package") or {}).get("entries", [])
                    if isinstance(entry, dict)
                )
            ]
            if normalized_status in {"rejected", "cancelled"} and delivered_packages:
                correction_key = f"{client_id}:{document_ref}"
                data["qnb_correction_reviews"].setdefault(
                    correction_key,
                    {
                        "id": str(uuid4()),
                        "client_id": client_id,
                        "document_ref": document_ref,
                        "status": "review_required",
                        "reason": f"qnb_status_{normalized_status}_after_delivery",
                        "trigger_event_key": event_key,
                        "delivered_export_package_ids": [
                            str(record.get("id") or "")
                            for record in delivered_packages
                        ],
                        "automatic_reversal_created": False,
                        "created_at": checked_at,
                    },
                )
            previous_status = str(document.get("source_qnb_normalized_status") or "")
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
                    "automation_hold_reason": (
                        str(hold.get("hold_code") or "") if automation_hold else ""
                    ),
                    "updated_at": utc_now(),
                }
            )
            self._write(data)
        return {
            **deepcopy(snapshot),
            "automation_hold": automation_hold,
            "automation_hold_reason": (
                str(hold.get("hold_code") or "") if automation_hold else ""
            ),
        }

    def active_document_safety_holds(
        self,
        *,
        client_id: str,
        document_refs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        requested = set(document_refs or [])
        return [
            deepcopy(hold)
            for hold in self._read()["document_safety_holds"].values()
            if hold.get("client_id") == client_id
            and not hold.get("resolved_at")
            and (not requested or str(hold.get("document_ref") or "") in requested)
        ]

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
        normalized_identities = [
            {
                "kind": str(identity.get("kind") or "").strip().lower(),
                "value": str(identity.get("value") or "").strip(),
            }
            for identity in identities
            if str(identity.get("kind") or "").strip()
            and str(identity.get("value") or "").strip()
        ]
        requested_ref = str(
            document.get("document_id")
            or document.get("original_file_name")
            or uuid4()
        )
        with self._lock:
            data = self._read()
            identity_records = data.setdefault("document_identities", {})
            existing_refs = {
                str(identity_records[key]["document_ref"])
                for identity in normalized_identities
                if (key := f"{client_id}:{identity['kind']}:{identity['value']}") in identity_records
            }
            if len(existing_refs) > 1:
                raise ValueError("document_identity_conflict")
            document_ref = next(iter(existing_refs), requested_ref)
            document_key = self._document_key(client_id, document_ref)
            existing = data["uploaded_documents"].get(document_key)
            timestamp = utc_now()
            source = {
                "source_ref": requested_ref,
                "source_channel": str(source_channel or "").strip(),
                "sha256": str(document.get("sha256") or ""),
                "original_file_name": str(document.get("original_file_name") or requested_ref),
                "storage_path": str(document.get("storage_path") or ""),
                "attached_at": timestamp,
            }
            if existing:
                record = deepcopy(existing)
                attachments = record.setdefault("document_sources", [])
                if not any(
                    str(item.get("source_ref") or "") == requested_ref
                    or (
                        source["sha256"]
                        and str(item.get("sha256") or "") == source["sha256"]
                    )
                    for item in attachments
                ):
                    attachments.append(source)
                record["updated_at"] = timestamp
            else:
                record = {
                    **document,
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "document_sources": [source],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            data["uploaded_documents"][document_key] = record
            for identity in normalized_identities:
                key = f"{client_id}:{identity['kind']}:{identity['value']}"
                owner = identity_records.get(key)
                if owner and str(owner.get("document_ref") or "") != document_ref:
                    raise ValueError("document_identity_conflict")
                identity_records[key] = {
                    **identity,
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "source_channel": str(source_channel or "").strip(),
                    "claimed_at": str(owner.get("claimed_at") or timestamp) if owner else timestamp,
                    "committed_at": timestamp,
                    "state": "committed",
                }
            existing_job = next(
                (
                    job
                    for job in data["processing_jobs"]
                    if str(job.get("client_id") or "") == client_id
                    and str(job.get("document_ref") or "") == document_ref
                    and str(job.get("status") or "") in {"queued", "processing", "completed"}
                ),
                None,
            )
            processing_job_created = existing_job is None
            if existing_job is None:
                existing_job = {
                    "id": str(uuid4()),
                    "client_id": client_id,
                    "document_ref": document_ref,
                    "document_type": str(document.get("document_type") or "invoice"),
                    "intake_category": intake_category,
                    "parser_kind": parser_kind,
                    "status": "queued",
                    "attempt_count": 0,
                    "error_message": "",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                data["processing_jobs"].append(existing_job)
            self._write(data)
        return {
            **deepcopy(record),
            "deduplicated": document_ref != requested_ref,
            "requested_document_ref": requested_ref,
            "processing_job": deepcopy(existing_job),
            "processing_job_created": processing_job_created,
        }

    def save_onboarding_attachment(self, *, client_id: str, attachment: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        attachment_ref = str(attachment.get("attachment_ref") or attachment.get("document_id") or uuid4())
        attachment_key = self._document_key(client_id, attachment_ref)
        record = {
            **attachment,
            "client_id": client_id,
            "attachment_ref": attachment_ref,
            "updated_at": utc_now(),
        }
        record.setdefault("created_at", record["updated_at"])
        data["onboarding_attachments"][attachment_key] = record
        self._write(data)
        return deepcopy(record)

    def apply_document_retention(self, *, delete_files: bool = True) -> dict[str, Any]:
        data = self._read()
        now = utc_now()
        checked_count = 0
        expiring_count = 0
        deleted_count = 0
        deleted_refs: list[str] = []
        for key, document in data["uploaded_documents"].items():
            checked_count += 1
            decision = retention_decision(document)
            if decision.storage_status == "expiring":
                document["storage_status"] = "expiring"
                expiring_count += 1
            if not decision.should_delete:
                continue
            storage_path = Path(str(document.get("storage_path") or ""))
            if delete_files and storage_path.exists() and storage_path.is_file():
                storage_path.unlink()
            if delete_files:
                self._delete_document_ai_raw_bodies(
                    client_id=str(document.get("client_id") or key.split(":", 1)[0]),
                    document=document,
                )
            document["status"] = "deleted"
            document["storage_status"] = "deleted"
            document["deleted_at"] = now
            document["updated_at"] = now
            deleted_refs.append(key)
            deleted_count += 1
        if expiring_count or deleted_count:
            self._write(data)
        return {
            "checked_count": checked_count,
            "expiring_count": expiring_count,
            "deleted_count": deleted_count,
            "deleted_document_refs": deleted_refs,
        }

    def preview_document_retention(self) -> dict[str, Any]:
        data = self._read()
        checked_count = 0
        expiring_count = 0
        expired_count = 0
        documents: list[dict[str, Any]] = []
        for key, document in data["uploaded_documents"].items():
            checked_count += 1
            decision = retention_decision(document)
            if decision.storage_status == "expiring":
                expiring_count += 1
            if decision.storage_status == "expired":
                expired_count += 1
            if decision.storage_status in {"expiring", "expired"}:
                documents.append(
                    {
                        "document_ref": decision.document_id,
                        "document_key": key,
                        "client_id": str(document.get("client_id") or ""),
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
        data = self._read()
        now = utc_now()
        deleted_count = 0
        extended_count = 0
        deleted_file_count = 0
        changed_refs: list[str] = []
        for key, document in data["uploaded_documents"].items():
            document_ref = str(document.get("document_id") or document.get("document_ref") or "")
            if key not in normalized_refs and document_ref not in normalized_refs:
                continue
            if action == "delete":
                storage_path = Path(str(document.get("storage_path") or ""))
                if delete_files and storage_path.exists() and storage_path.is_file():
                    storage_path.unlink()
                    deleted_file_count += 1
                if delete_files:
                    self._delete_document_ai_raw_bodies(
                        client_id=str(document.get("client_id") or key.split(":", 1)[0]),
                        document=document,
                    )
                document["status"] = "deleted"
                document["storage_status"] = "deleted"
                document["deleted_at"] = now
                document["updated_at"] = now
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
                document["updated_at"] = now
                extended_count += 1
            changed_refs.append(document_ref or key)
        if changed_refs:
            self._write(data)
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
        data = self._read()
        deleted_refs: list[str] = []
        deleted_file_count = 0
        for document_ref in refs:
            document_key = self._document_key(normalized_client_id, document_ref)
            uploaded = data["uploaded_documents"].pop(document_key, None)
            processed = data["documents"].pop(document_key, None)
            if uploaded and delete_files:
                storage_path = Path(str(uploaded.get("storage_path") or ""))
                if storage_path.exists() and storage_path.is_file():
                    storage_path.unlink()
                    deleted_file_count += 1
                self._delete_document_ai_raw_bodies(
                    client_id=normalized_client_id,
                    document=uploaded,
                )
            if uploaded or processed:
                deleted_refs.append(document_ref)
        if deleted_refs:
            deleted_set = set(deleted_refs)
            data["processing_jobs"] = [
                job
                for job in data["processing_jobs"]
                if not (job.get("client_id") == normalized_client_id and str(job.get("document_ref") or "") in deleted_set)
            ]
            data["document_pipeline_events"] = [
                event
                for event in data["document_pipeline_events"]
                if not (event.get("client_id") == normalized_client_id and str(event.get("document_ref") or "") in deleted_set)
            ]
            self._write(data)
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
        with self._lock:
            data = self._read()
            document_key = self._document_key(client_id, document_ref)
            existing = data["documents"].get(document_key, {})
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
            record = {
                **existing,
                "client_id": client_id,
                "document_ref": document_ref,
                "status": persisted_result.get("simulated_status", "review_required"),
                "export_status": persisted_result.get("export_status", "review_required"),
                "review_reason_codes": persisted_result.get("review_reason_codes", []),
                "result": persisted_result,
                "updated_at": utc_now(),
            }
            if attempt_id:
                record[PROCESSING_ATTEMPT_MARKER_KEY] = processing_attempt_marker(
                    attempt_id=attempt_id,
                    input_digest=input_digest,
                    result=persisted_result,
                )
            record.setdefault("id", str(uuid4()))
            record.setdefault("created_at", record["updated_at"])
            data["documents"][document_key] = record
            self._write(data)
            return deepcopy(record)

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
        data = self._read()
        created_at = utc_now()
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
            "created_at": created_at,
            "updated_at": created_at,
        }
        data["processing_jobs"].append(record)
        self._write(data)
        return deepcopy(record)

    def list_processing_jobs(self, *, client_id: str | None = None) -> list[dict[str, Any]]:
        data = self._read()
        return [
            deepcopy(job)
            for job in data["processing_jobs"]
            if client_id is None or job.get("client_id") == client_id
        ]

    def claim_next_processing_job(self) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            for job in data["processing_jobs"]:
                due_retry = (
                    job.get("status") == "retry_wait"
                    and str(job.get("next_attempt_at") or "") <= utc_now()
                )
                if job.get("status") != "queued" and not due_retry:
                    continue
                job["status"] = "processing"
                job["attempt_count"] = int(job.get("attempt_count") or 0) + 1
                job["updated_at"] = utc_now()
                self._write(data)
                return deepcopy(job)
            return None

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
        data = self._read()
        for job in data["processing_jobs"]:
            if job.get("id") != job_id:
                continue
            job["status"] = status
            job["error_message"] = error_message
            if processing_metrics is not None:
                job["processing_metrics"] = processing_metrics
            job["next_attempt_at"] = next_attempt_at.isoformat() if hasattr(next_attempt_at, "isoformat") else str(next_attempt_at or "")
            job["retry_step"] = int(retry_step or 0)
            job["outage_episode_id"] = str(outage_episode_id or "")
            job["updated_at"] = utc_now()
            self._write(data)
            return deepcopy(job)
        return None

    def save_review_decision(
        self,
        *,
        client_id: str,
        decision: dict[str, Any],
        learning_event: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._read()
        timestamp = utc_now()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "decision": decision,
            "learning_event": learning_event,
            "created_at": timestamp,
        }
        data["review_decisions"].append(record)
        data["learning_events"].append(
            {
                "id": str(uuid4()),
                "client_id": client_id,
                **learning_event,
                "created_at": record["created_at"],
            }
        )
        document_ref = str(decision.get("document_ref") or learning_event.get("document_ref") or "")
        document_key = self._document_key(client_id, document_ref)
        if document_key in data["documents"]:
            corrected_document = apply_review_decision_to_document(
                data["documents"][document_key],
                decision=decision,
                learning_event=learning_event,
                reviewed_at=timestamp,
            )
            data["documents"][document_key] = corrected_document
            record["corrected_document"] = deepcopy(corrected_document)
        self._write(data)
        return deepcopy(record)

    def save_export_package(self, *, client_id: str, package: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "package": package,
            "created_at": utc_now(),
        }
        data["export_packages"].append(record)
        self._write(data)
        return deepcopy(record)

    def mark_export_package_downloaded(self, *, client_id: str, output_filename: str) -> dict[str, Any] | None:
        data = self._read()
        timestamp = utc_now()
        for record in reversed(data["export_packages"]):
            package = record.get("package") or {}
            if record.get("client_id") != client_id or package.get("output_filename") != output_filename:
                continue
            updated = mark_export_package_downloaded(record, downloaded_at=timestamp)
            record.update(updated)
            self._write(data)
            return deepcopy(record)
        return None

    def get_workspace(self, client_id: str) -> dict[str, Any]:
        data = self._read()
        document_prefix = f"{client_id}:"
        return {
            "client": deepcopy(data["clients"].get(client_id)),
            "chart_accounts": deepcopy(data["chart_accounts"].get(client_id)),
            "uploaded_documents": [
                deepcopy(document)
                for key, document in data["uploaded_documents"].items()
                if key.startswith(document_prefix)
            ],
            "onboarding_attachments": [
                deepcopy(attachment)
                for key, attachment in data["onboarding_attachments"].items()
                if key.startswith(document_prefix)
            ],
            "documents": [
                deepcopy(document)
                for key, document in data["documents"].items()
                if key.startswith(document_prefix)
            ],
            "processing_jobs": [
                deepcopy(job)
                for job in data["processing_jobs"]
                if job.get("client_id") == client_id
            ],
            "review_decisions": [
                deepcopy(decision)
                for decision in data["review_decisions"]
                if decision.get("client_id") == client_id
            ],
            "learning_events": [
                deepcopy(event)
                for event in data["learning_events"]
                if event.get("client_id") == client_id
            ],
            "export_packages": [
                deepcopy(package)
                for package in data["export_packages"]
                if package.get("client_id") == client_id
            ],
            "portal_users": [
                deepcopy(user)
                for user in data["portal_users"].values()
                if client_id in set(user.get("allowed_client_ids") or []) or "*" in set(user.get("allowed_client_ids") or [])
            ],
            "operation_events": self.list_operation_events(client_id=client_id),
            "document_pipeline_events": [
                deepcopy(event)
                for event in data["document_pipeline_events"]
                if event.get("client_id") == client_id
            ],
            "qnb_incoming_status_snapshots": [
                deepcopy(snapshot)
                for key, snapshot in data["qnb_incoming_status_snapshots"].items()
                if key.startswith(document_prefix)
            ],
            "document_safety_holds": [
                deepcopy(hold)
                for hold in data["document_safety_holds"].values()
                if hold.get("client_id") == client_id
            ],
            "qnb_correction_reviews": [
                deepcopy(review)
                for review in data["qnb_correction_reviews"].values()
                if review.get("client_id") == client_id
            ],
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_store()
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        data = empty_store()
        for key, value in loaded.items():
            if key in data:
                data[key] = value
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _document_key(client_id: str, document_ref: str) -> str:
        return f"{client_id}:{document_ref}"

    @staticmethod
    def _remove_portal_user_auth_records(data: dict[str, Any], user_id: str) -> None:
        data["auth_credentials"].pop(user_id, None)
        data["auth_sessions"] = {
            token_hash: session
            for token_hash, session in data["auth_sessions"].items()
            if session.get("user_id") != user_id
        }
        data["auth_tokens"] = {
            token_hash: token
            for token_hash, token in data["auth_tokens"].items()
            if token.get("user_id") != user_id
        }


def _clear_directory_contents(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    deleted_count = 0
    for child in path.iterdir():
        if child.is_dir():
            deleted_count += sum(1 for item in child.rglob("*") if item.is_file())
            shutil.rmtree(child)
        elif child.is_file():
            child.unlink()
            deleted_count += 1
    return deleted_count


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_reset_roots(
    *,
    document_storage_path: Path | str,
    export_path: Path | str,
    protected_storage_path: Path | str,
) -> None:
    documents = Path(document_storage_path).resolve()
    exports = Path(export_path).resolve()
    protected = Path(protected_storage_path).resolve()
    for ordinary in (documents, exports):
        if _path_is_within(protected, ordinary) or _path_is_within(ordinary, protected):
            raise ValueError("protected_reset_path_overlap")
        if not ordinary.exists():
            continue
        for child in ordinary.rglob("*"):
            resolved = child.resolve()
            if not _path_is_within(resolved, ordinary) or _path_is_within(resolved, protected):
                raise ValueError("unsafe_reset_path")
