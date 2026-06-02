from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.domain.document_uploads import retention_decision
from app.domain.portal_access import (
    PORTAL_USERS_CLIENT_ID,
    build_portal_user_record,
    decide_portal_access,
)
from app.domain.workspace_review_updates import (
    apply_review_decision_to_document,
    mark_export_package_downloaded,
)


ConnectFactory = Callable[[], Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def tenant_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:tenant:{value}")


def taxpayer_uuid(client_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:taxpayer:{client_id}")


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
    ) -> dict[str, Any]:
        timestamp = utc_now()
        record = {
            "id": str(uuid4()),
            "client_id": client_id,
            "document_ref": document_ref,
            "document_type": document_type,
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
        rows = self._list_records("processing_job")
        queued = [row for row in rows if row["payload"].get("status") == "queued"]
        if not queued:
            return None
        queued.sort(key=lambda row: str(row["payload"].get("created_at") or ""))
        row = queued[0]
        payload = row["payload"]
        payload["status"] = "processing"
        payload["attempt_count"] = int(payload.get("attempt_count") or 0) + 1
        payload["updated_at"] = utc_now()
        return self._upsert_record(str(row["client_id"]), "processing_job", str(row["record_key"]), payload)

    def update_processing_job(
        self,
        *,
        job_id: str,
        status: str,
        error_message: str = "",
    ) -> dict[str, Any] | None:
        row = self._get_record_by_key("processing_job", job_id)
        if row is None:
            return None
        payload = row["payload"]
        payload["status"] = status
        payload["error_message"] = error_message
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
