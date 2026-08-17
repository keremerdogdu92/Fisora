from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.persistence.operational_control_repository import OperationalControlRepository
from app.persistence.postgres_workflow_store import taxpayer_uuid


class RetentionService:
    def __init__(self, *, store: Any, document_storage_path: Path) -> None:
        self.store = store
        self.document_storage_path = document_storage_path
        self.repository = OperationalControlRepository(
            connect=store._connect,
            tenant_id=store.tenant_id,
            json_value=store._json,
        )

    def run_due(self, *, now: datetime, worker_id: str) -> dict[str, Any]:
        empty = {
            "claimed": 0,
            "prepared_batch_count": 0,
            "opened_warning_count": 0,
            "deleted_source_count": 0,
            "deleted_file_count": 0,
            "deleted_raw_receipt_body_count": 0,
            "resolved_batch_count": 0,
            "warnings": [],
        }
        if not getattr(self.store, "normalized_accounting_enabled", False):
            return empty
        claim = self.repository.claim_retention_tick(now=now, worker_id=worker_id)
        if claim is None:
            return empty
        prepared = self.repository.prepare_retention_batches(now=now)
        opened = self.repository.open_due_retention_warnings(now=now)
        batches = self.repository.claim_due_retention_deletions(now=now, worker_id=worker_id)
        warnings: list[str] = []
        deleted_source_count = 0
        deleted_file_count = 0
        deleted_raw_receipt_body_count = 0
        resolved_batch_count = 0
        for batch in batches:
            batch_warnings: list[str] = []
            for source in batch.get("sources", []):
                artifact_repository = getattr(
                    self.store, "document_ai_artifact_repository", None
                )
                if artifact_repository is not None:
                    try:
                        deleted_raw_receipt_body_count += int(
                            artifact_repository.delete_raw_bodies_for_source(
                                tenant_id=str(self.store.tenant_id),
                                taxpayer_id=str(batch.get("taxpayer_id") or ""),
                                source_file_id=str(source.get("source_file_id") or ""),
                            )
                        )
                    except Exception:
                        batch_warnings.append("raw_receipt_body_delete_failed")
                path = self._validated_local_path(str(source.get("storage_path") or ""))
                if path is None:
                    batch_warnings.append("raw_file_delete_skipped")
                    continue
                try:
                    path.unlink()
                    deleted_file_count += 1
                except FileNotFoundError:
                    batch_warnings.append("raw_file_missing")
                except OSError:
                    batch_warnings.append("raw_file_delete_failed")
            result = self.repository.resolve_retention_batch(
                batch=batch,
                worker_id=worker_id,
                delete_warnings=batch_warnings,
            )
            deleted_source_count += int(result["deleted_source_count"])
            resolved_batch_count += 1 if result["resolved"] else 0
            warnings.extend(batch_warnings)
        return {
            "claimed": 1,
            "prepared_batch_count": prepared,
            "opened_warning_count": opened,
            "deleted_source_count": deleted_source_count,
            "deleted_file_count": deleted_file_count,
            "deleted_raw_receipt_body_count": deleted_raw_receipt_body_count,
            "resolved_batch_count": resolved_batch_count,
            "warnings": sorted(set(warnings)),
        }

    def list_pending(self, *, user_id: str) -> dict[str, Any]:
        items = self.repository.list_pending_retention(user_id=user_id)
        portal_user = self.store.get_portal_user(user_id) or {}
        role = str(portal_user.get("role") or "").lower()
        allowed_client_ids = {str(item) for item in portal_user.get("allowed_client_ids") or []}
        if role not in {"accountant", "admin"} and not allowed_client_ids:
            return {"items": []}
        client_map: dict[str, tuple[str, str]] = {}
        for client in self.store.list_clients():
            client_id = str(client.get("client_id") or "")
            profile = client.get("profile") if isinstance(client.get("profile"), dict) else {}
            client_map[str(taxpayer_uuid(self.store.tenant_id, client_id))] = (
                client_id,
                str(profile.get("title") or client_id),
            )
        for item in items:
            client_id, client_name = client_map.get(
                str(item["taxpayer_id"]),
                ("", str(item.get("client_name") or "")),
            )
            item["client_id"] = client_id
            item["client_name"] = client_name
            item.pop("taxpayer_id", None)
        if role not in {"accountant", "admin"}:
            items = [item for item in items if item.get("client_id") in allowed_client_ids]
        return {"items": items}

    def mark_read(self, *, batch_id: str, user_id: str) -> dict[str, Any]:
        portal_user = self.store.get_portal_user(user_id) or {}
        role = str(portal_user.get("role") or "").lower()
        if role not in {"accountant", "admin"}:
            allowed_client_ids = {str(item) for item in portal_user.get("allowed_client_ids") or []}
            pending = self.list_pending(user_id=user_id)["items"]
            if not any(item.get("batch_id") == batch_id and item.get("client_id") in allowed_client_ids for item in pending):
                raise ValueError("retention_batch_not_found_or_access_denied")
        return self.repository.mark_retention_read(batch_id=batch_id, user_id=user_id)

    def _validated_local_path(self, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            return None
        try:
            path.resolve().relative_to(self.document_storage_path.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None
