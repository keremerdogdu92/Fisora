from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.domain.document_uploads import store_document_content
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents


OperationRecorder = Callable[..., dict[str, object]]
AccessChecker = Callable[..., dict[str, object]]


class DocumentService:
    def __init__(
        self,
        *,
        store: Any,
        document_storage_path: Path,
        record_operation_event: OperationRecorder,
        require_client_access: AccessChecker,
    ) -> None:
        self.store = store
        self.document_storage_path = document_storage_path
        self.record_operation_event = record_operation_event
        self.require_client_access = require_client_access

    def store_document_upload(
        self,
        *,
        client_id: str,
        document_type: str,
        intake_category: str = "",
        file_name: str,
        uploaded_by: str,
        uploaded_by_user_id: str = "",
        request_user_id: str | None = None,
        content: bytes | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        retention_policy_days: int = 90,
    ) -> dict[str, object]:
        if not client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required for document upload")
        request_user = (request_user_id or "").strip()
        effective_user_id = uploaded_by_user_id.strip() or uploaded_by.strip() or request_user
        if request_user and effective_user_id and request_user != effective_user_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "allowed": False,
                    "reason": "mock_user_header_mismatch",
                    "user_id": request_user,
                    "payload_user_id": effective_user_id,
                },
            )
        if not effective_user_id:
            raise HTTPException(status_code=403, detail="portal user is required for document upload")
        access = self.store.verify_portal_access(client_id=client_id, user_id=effective_user_id)
        if not access.get("allowed"):
            raise HTTPException(status_code=403, detail=access)
        try:
            document = store_document_content(
                base_dir=self.document_storage_path,
                client_id=client_id,
                file_name=file_name,
                document_type=document_type,
                intake_category=intake_category,
                uploaded_by=uploaded_by,
                content=content,
                declared_size_bytes=size_bytes,
                declared_sha256=sha256,
                retention_days=retention_policy_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        document_payload = asdict(document)
        document_payload["uploaded_by_user_id"] = effective_user_id
        document_payload["portal_access_reason"] = access.get("reason", "")
        saved = self.store.save_uploaded_document(
            client_id=client_id,
            document=document_payload,
        )
        self.store.record_document_pipeline_event(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            step="uploaded",
            status="ok",
            message_tr="Belge yüklendi.",
            debug_code="uploaded",
            details={
                "file_name": file_name,
                "document_type": document_type,
                "intake_category": saved.get("intake_category", ""),
                "size_bytes": saved.get("size_bytes", 0),
                "uploaded_by_user_id": effective_user_id,
            },
        )
        storage_path = Path(str(saved.get("storage_path") or ""))
        if storage_path.exists() and storage_path.is_file():
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=str(saved["document_ref"]),
                step="file_preview_ready",
                status="ok",
                message_tr="Belge önizlenebiliyor.",
                debug_code="file_preview_ready",
                details={
                    "storage_backend": saved.get("storage_backend", ""),
                    "media_type": mimetypes.guess_type(file_name)[0] or "application/octet-stream",
                },
            )
        else:
            self.store.record_document_pipeline_event(
                client_id=client_id,
                document_ref=str(saved["document_ref"]),
                step="storage_missing",
                status="error",
                message_tr="Belge storage kaydı doğrulanamadı.",
                debug_code="storage_missing",
                details={"storage_path": str(storage_path)},
            )
        job = self.store.create_processing_job(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            document_type=document_type,
            parser_kind=parser_kind_for_document_type(document_type),
            intake_category=str(saved.get("intake_category") or ""),
        )
        self.record_operation_event(
            store=self.store,
            client_id=client_id,
            event_type="document_uploaded",
            status="ok",
            message="Belge kaydedildi ve processing job kuyruga alindi.",
            metadata={
                "document_ref": saved["document_ref"],
                "document_type": document_type,
                "intake_category": saved.get("intake_category", ""),
                "file_name": file_name,
                "processing_job_id": job["id"],
                "parser_kind": job["parser_kind"],
                "uploaded_by_user_id": effective_user_id,
            },
        )
        return {**saved, "processing_job": job}

    def store_document_retention_run(self, *, delete_files: bool) -> dict[str, object]:
        summary = self.store.apply_document_retention(delete_files=delete_files)
        self.record_operation_event(
            store=self.store,
            client_id="__system__",
            event_type="document_retention_run",
            status="warning" if summary["deleted_count"] else "ok",
            message="90 gun belge retention job'u calisti.",
            metadata=summary,
        )
        return summary

    def store_processing_run(self, *, max_jobs: int) -> dict[str, object]:
        summary = process_queued_documents(self.store, max_jobs=max_jobs)
        self.record_operation_event(
            store=self.store,
            client_id="__system__",
            event_type="processing_run",
            status="error" if summary["failed_count"] else "ok",
            message="Worker kuyrugu manuel/API tetiklemesiyle calisti.",
            metadata=summary,
        )
        return summary

    def store_processing_jobs(self, *, client_id: str, user_id: str | None) -> dict[str, object]:
        if not client_id.strip():
            raise HTTPException(status_code=400, detail="client_id is required")
        self.require_client_access(client_id=client_id, user_id=user_id)
        return {"jobs": self.store.list_processing_jobs(client_id=client_id)}

    def document_pipeline(self, *, client_id: str, document_ref: str, user_id: str | None) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        normalized_ref = document_ref.strip()
        if not normalized_client_id or not normalized_ref:
            raise HTTPException(status_code=400, detail="client_id and document_ref are required")
        self.require_client_access(client_id=normalized_client_id, user_id=user_id)
        return {
            "client_id": normalized_client_id,
            "document_ref": normalized_ref,
            "events": self.store.list_document_pipeline_events(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
            ),
        }

    def original_document_file(self, *, client_id: str, document_ref: str, user_id: str | None) -> dict[str, object]:
        normalized_client_id = client_id.strip()
        normalized_ref = document_ref.strip()
        if not normalized_client_id or not normalized_ref:
            raise HTTPException(status_code=400, detail="client_id and document_ref are required")
        self.require_client_access(client_id=normalized_client_id, user_id=user_id)
        workspace = self.store.get_workspace(normalized_client_id)
        document = next(
            (
                item
                for item in workspace.get("uploaded_documents", [])
                if str(item.get("document_ref") or item.get("document_id") or item.get("original_file_name")) == normalized_ref
            ),
            None,
        )
        if not document:
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
                step="preview_fetch_failed",
                status="error",
                message_tr="Önizleme alınamadı: belge kaydı bulunamadı.",
                debug_code="preview_document_not_found",
                details={},
            )
            raise HTTPException(status_code=404, detail="document not found")
        path = Path(str(document.get("storage_path") or ""))
        if not path.exists() or not path.is_file():
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
                step="preview_fetch_failed",
                status="error",
                message_tr="Önizleme alınamadı: dosya storage'da bulunamadı.",
                debug_code="preview_file_missing",
                details={"storage_path": str(path)},
            )
            raise HTTPException(status_code=404, detail="document file not found")
        try:
            path.resolve().relative_to(self.document_storage_path.resolve())
        except ValueError as exc:
            self.store.record_document_pipeline_event(
                client_id=normalized_client_id,
                document_ref=normalized_ref,
                step="preview_fetch_failed",
                status="error",
                message_tr="Önizleme alınamadı: dosya yolu izin verilen alanın dışında.",
                debug_code="preview_path_outside_storage",
                details={"storage_path": str(path)},
            )
            raise HTTPException(status_code=403, detail="document storage path is outside allowed storage") from exc
        file_name = Path(str(document.get("original_file_name") or path.name)).name
        media_type = str(document.get("content_type") or "") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        return {
            "path": path,
            "file_name": file_name,
            "media_type": media_type,
        }

