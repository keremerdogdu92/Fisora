from __future__ import annotations

import json
import shutil
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.document_uploads import extend_retention_deadline, retention_decision
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


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
        "qnb_sync_policies": {},
        "qnb_sync_cursors": {},
        "qnb_document_identities": {},
        "qnb_outgoing_invoices": {},
        "qnb_outgoing_status_snapshots": {},
        "qnb_incoming_status_snapshots": {},
        "outgoing_invoices": {},
        "outgoing_invoice_send_keys": {},
        "ai_usage_events": [],
        "ai_capacity_snapshots": {},
        "operation_events": [],
        "document_pipeline_events": [],
        "nace_research_profiles": {},
        "brand_research_profiles": {},
        "research_benchmark_runs": [],
    }


def normalize_nace_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_brand_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


class JsonWorkflowStore:
    """Local persistence adapter for Phase 0 and demos.

    Production should swap this with a PostgreSQL-backed implementation using
    the same behavior surface. The default path lives under exports/, which is
    intentionally gitignored.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

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
        delete_files: bool = True,
    ) -> dict[str, Any]:
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
                policy.update({"lease_owner": worker_id, "lease_expires_at": lease_expires_at, "last_attempt_at": now})
                self._write(data)
                return deepcopy(policy)
        return None

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
            "details": details or {},
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

    def save_nace_research_profile(self, *, nace_code: str, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_nace_code(nace_code)
        data = self._read()
        existing = data["nace_research_profiles"].get(normalized, {})
        timestamp = utc_now()
        record = {
            **existing,
            **profile,
            "nace_code": normalized,
            "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
            "updated_at": timestamp,
        }
        data["nace_research_profiles"][normalized] = record
        self._write(data)
        return deepcopy(record)

    def get_nace_research_profile(self, nace_code: str) -> dict[str, Any] | None:
        data = self._read()
        profile = data["nace_research_profiles"].get(normalize_nace_code(nace_code))
        return deepcopy(profile) if profile else None

    def save_brand_research_profile(self, *, brand_name: str, profile: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_brand_name(brand_name)
        data = self._read()
        existing = data["brand_research_profiles"].get(normalized, {})
        timestamp = utc_now()
        record = {
            **existing,
            **profile,
            "brand_name": normalized,
            "researched_at": profile.get("researched_at") or existing.get("researched_at") or timestamp,
            "updated_at": timestamp,
        }
        data["brand_research_profiles"][normalized] = record
        self._write(data)
        return deepcopy(record)

    def get_brand_research_profile(self, brand_name: str) -> dict[str, Any] | None:
        data = self._read()
        profile = data["brand_research_profiles"].get(normalize_brand_name(brand_name))
        return deepcopy(profile) if profile else None

    def get_research_profile(self, *, kind: str, key: str) -> dict[str, Any] | None:
        if kind == "nace":
            return self.get_nace_research_profile(key)
        if kind == "brand":
            return self.get_brand_research_profile(key)
        return None

    def list_research_profiles(self, *, kind: str = "") -> list[dict[str, Any]]:
        data = self._read()
        profiles: list[dict[str, Any]] = []
        if kind in {"", "brand"}:
            profiles.extend(deepcopy(profile) for profile in data["brand_research_profiles"].values())
        if kind in {"", "nace"}:
            profiles.extend(deepcopy(profile) for profile in data["nace_research_profiles"].values())
        return sorted(
            profiles,
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
    ) -> dict[str, Any]:
        data = self._read()
        document_key = self._document_key(client_id, document_ref)
        existing = data["documents"].get(document_key, {})
        record = {
            **existing,
            "client_id": client_id,
            "document_ref": document_ref,
            "status": result.get("simulated_status", "review_required"),
            "export_status": result.get("export_status", "review_required"),
            "review_reason_codes": result.get("review_reason_codes", []),
            "result": result,
            "updated_at": utc_now(),
        }
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
                if job.get("status") != "queued":
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
    ) -> dict[str, Any] | None:
        data = self._read()
        for job in data["processing_jobs"]:
            if job.get("id") != job_id:
                continue
            job["status"] = status
            job["error_message"] = error_message
            if processing_metrics is not None:
                job["processing_metrics"] = processing_metrics
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
