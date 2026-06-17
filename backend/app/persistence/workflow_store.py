from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.document_uploads import retention_decision
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
        "ai_usage_events": [],
        "operation_events": [],
        "document_pipeline_events": [],
        "nace_research_profiles": {},
    }


def normalize_nace_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


class JsonWorkflowStore:
    """Local persistence adapter for Phase 0 and demos.

    Production should swap this with a PostgreSQL-backed implementation using
    the same behavior surface. The default path lives under exports/, which is
    intentionally gitignored.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

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

    def create_auth_session(self, *, user_id: str, token_hash: str, expires_at: str) -> dict[str, Any]:
        data = self._read()
        timestamp = utc_now()
        record = {
            "session_id": str(uuid4()),
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
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
    ) -> dict[str, Any] | None:
        data = self._read()
        for job in data["processing_jobs"]:
            if job.get("id") != job_id:
                continue
            job["status"] = status
            job["error_message"] = error_message
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
