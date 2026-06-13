from __future__ import annotations

import os
from pathlib import Path
import sys

from fastapi import Response

from app.api.phase0_dependencies import (
    clear_session_cookie,
    client_id_from_record,
    password_bootstrap_enabled,
    record_operation_event,
    request_user_id as _request_user_id,
    require_mock_client_access,
    set_session_cookie,
)
from app.api.phase0_uploads import save_uploaded_document_with_job as _save_uploaded_document_with_job
from app.persistence.store_factory import build_workflow_store
from app.services.document_service import DocumentService
from app.services.export_service import ExportService
from app.services.review_service import ReviewService
from app.services.workspace_service import WorkspaceService


DEFAULT_STORE_PATH = Path(os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json"))
DEFAULT_DOCUMENT_STORAGE_PATH = Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "exports/documents"))
DEFAULT_EXPORT_PATH = Path(os.environ.get("FISORA_EXPORT_PATH", "exports/generated"))
DEFAULT_BACKUP_PATH = Path(os.environ.get("FISORA_BACKUP_PATH", os.environ.get("FISORA_BACKUP_DIR", "exports/backups")))
SESSION_COOKIE_NAME = "fisora_session"


def _phase0_value(name: str, default):
    phase0 = sys.modules.get("app.api.phase0")
    return getattr(phase0, name, default) if phase0 is not None else default


def default_store_path() -> Path:
    return _phase0_value("DEFAULT_STORE_PATH", DEFAULT_STORE_PATH)


def default_document_storage_path() -> Path:
    return _phase0_value("DEFAULT_DOCUMENT_STORAGE_PATH", DEFAULT_DOCUMENT_STORAGE_PATH)


def default_export_path() -> Path:
    return _phase0_value("DEFAULT_EXPORT_PATH", DEFAULT_EXPORT_PATH)


def default_backup_path() -> Path:
    return _phase0_value("DEFAULT_BACKUP_PATH", DEFAULT_BACKUP_PATH)


def get_workflow_store():
    return build_workflow_store(json_path=default_store_path())


def get_workspace_service() -> WorkspaceService:
    return WorkspaceService(
        store=get_workflow_store(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
        request_user_id=request_user_id,
    )


def get_document_service() -> DocumentService:
    return DocumentService(
        store=get_workflow_store(),
        document_storage_path=default_document_storage_path(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
    )


def get_review_service() -> ReviewService:
    return ReviewService(
        store=get_workflow_store(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
    )


def get_export_service() -> ExportService:
    return ExportService(
        store=get_workflow_store(),
        export_path=default_export_path(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
    )


def request_user_id(
    user_header: str | None,
    session_header: str | None = None,
    session_cookie: str | None = None,
) -> str:
    return _request_user_id(
        user_header,
        session_header,
        session_cookie,
        store_factory=get_workflow_store,
    )


def set_portal_session_cookie(response: Response, token: str, *, ttl_hours: int) -> None:
    set_session_cookie(response, token, ttl_hours=ttl_hours, cookie_name=SESSION_COOKIE_NAME)


def clear_portal_session_cookie(response: Response) -> None:
    clear_session_cookie(response, cookie_name=SESSION_COOKIE_NAME)


def require_client_access(
    *,
    client_id: str,
    user_id: str | None,
    allowed_roles: tuple[str, ...] = (),
) -> dict[str, object]:
    return require_mock_client_access(
        client_id=client_id,
        user_id=user_id,
        store_factory=get_workflow_store,
        allowed_roles=allowed_roles,
    )


def save_uploaded_document_with_job(
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
    return _save_uploaded_document_with_job(
        store=get_workflow_store(),
        document_storage_path=default_document_storage_path(),
        record_operation_event=record_operation_event,
        client_id=client_id,
        document_type=document_type,
        intake_category=intake_category,
        file_name=file_name,
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=request_user_id,
        content=content,
        size_bytes=size_bytes,
        sha256=sha256,
        retention_policy_days=retention_policy_days,
    )
