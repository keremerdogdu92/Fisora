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
    request_auth_context as _request_auth_context,
    request_user_id as _request_user_id,
    require_mock_client_access,
    set_session_cookie,
)
from app.api.phase0_uploads import save_uploaded_document_with_job as _save_uploaded_document_with_job
from app.persistence.store_factory import build_workflow_store
from app.domain.research_harness import ResearchHarness, build_research_runtime_from_env
from app.domain.qnb_efatura import QnbConnectionService, build_qnb_adapter_from_env
from app.domain.outgoing_invoices import OutgoingInvoiceService
from app.domain.qnb_outgoing import build_outgoing_invoice_provider
from app.workflows.document_processing import _provider_chain_from_env
from app.services.document_service import DocumentService
from app.services.retention_service import RetentionService
from app.services.export_service import ExportService
from app.services.review_service import ReviewService
from app.services.protected_corpus_service import ProtectedCorpusService
from app.services.workspace_service import WorkspaceService
from app.services.pilot_reinitialization_service import PilotReinitializationService


DEFAULT_STORE_PATH = Path(os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json"))
DEFAULT_DOCUMENT_STORAGE_PATH = Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "exports/documents"))
DEFAULT_EXPORT_PATH = Path(os.environ.get("FISORA_EXPORT_PATH", "exports/generated"))
DEFAULT_BACKUP_PATH = Path(os.environ.get("FISORA_BACKUP_PATH", os.environ.get("FISORA_BACKUP_DIR", "exports/backups")))
DEFAULT_PROTECTED_CORPUS_PATH = Path(
    os.environ.get("FISORA_PROTECTED_CORPUS_PATH", "exports/protected-corpus")
)
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


def default_protected_corpus_path() -> Path:
    return _phase0_value("DEFAULT_PROTECTED_CORPUS_PATH", DEFAULT_PROTECTED_CORPUS_PATH)


def get_workflow_store():
    return build_workflow_store(json_path=default_store_path())


def get_pilot_reinitialization_service() -> PilotReinitializationService:
    return PilotReinitializationService(
        store=get_workflow_store(),
        document_storage_path=default_document_storage_path(),
        export_path=default_export_path(),
        protected_storage_path=default_protected_corpus_path(),
    )


def get_workspace_service() -> WorkspaceService:
    store = get_workflow_store()
    return WorkspaceService(
        store=store,
        document_storage_path=default_document_storage_path(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
        request_user_id=request_user_id,
        nace_researcher=build_nace_researcher(store),
    )


def build_nace_researcher(store):
    runtime = build_research_runtime_from_env(os.environ)
    if not runtime:
        return None

    def researcher(nace_code: str) -> dict[str, object]:
        harness = ResearchHarness(
            store=store,
            provider=runtime.get("provider"),  # type: ignore[arg-type]
            policy=runtime.get("policy"),  # type: ignore[arg-type]
        )
        return harness.research_nace(nace_code=nace_code)

    return researcher


def get_document_service() -> DocumentService:
    return _build_document_service(get_workflow_store())


def get_retention_service(store=None) -> RetentionService:
    selected_store = store or get_workflow_store()
    return RetentionService(
        store=selected_store,
        document_storage_path=default_document_storage_path(),
    )


def _build_document_service(store) -> DocumentService:
    return DocumentService(
        store=store,
        document_storage_path=default_document_storage_path(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
    )


def get_review_service() -> ReviewService:
    store = get_workflow_store()
    return ReviewService(
        store=store,
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
        rule_interpreter=_provider_chain_from_env(os.environ),
        protected_corpus_service=ProtectedCorpusService(
            store=store,
            protected_root=default_protected_corpus_path(),
            document_root=default_document_storage_path(),
            export_root=default_export_path(),
        ),
    )


def get_protected_corpus_service() -> ProtectedCorpusService:
    return ProtectedCorpusService(
        store=get_workflow_store(),
        protected_root=default_protected_corpus_path(),
        document_root=default_document_storage_path(),
        export_root=default_export_path(),
    )


def get_export_service() -> ExportService:
    return ExportService(
        store=get_workflow_store(),
        export_path=default_export_path(),
        record_operation_event=record_operation_event,
        require_client_access=require_client_access,
    )


def get_qnb_connection_service() -> QnbConnectionService:
    return QnbConnectionService(
        store=get_workflow_store(),
        document_storage_path=default_document_storage_path(),
        adapter=build_qnb_adapter_from_env(os.environ),
    )


def get_outgoing_invoice_service() -> OutgoingInvoiceService:
    store = get_workflow_store()
    return OutgoingInvoiceService(
        store=store,
        provider=build_outgoing_invoice_provider(os.environ, store),
        document_service=_build_document_service(store),
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


def request_auth_context(
    user_header: str | None,
    session_header: str | None = None,
    session_cookie: str | None = None,
) -> dict[str, object]:
    return _request_auth_context(
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
    period: str = "",
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
        period=period,
        file_name=file_name,
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=request_user_id,
        content=content,
        size_bytes=size_bytes,
        sha256=sha256,
        retention_policy_days=retention_policy_days,
    )
