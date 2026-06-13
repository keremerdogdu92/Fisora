from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, UploadFile

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_workflow_store,
    record_operation_event,
    request_user_id,
    require_client_access,
    save_uploaded_document_with_job,
)
from app.api.phase0_schemas import DocumentRetentionRunPayload, DocumentUploadPayload, ProcessingRunPayload
from app.domain.document_uploads import decode_base64_content
from app.workflows.document_processing import process_queued_documents


router = APIRouter()


@router.post("/store/document-upload")
def store_document_upload(
    payload: DocumentUploadPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    content = None
    if payload.content_base64:
        try:
            content = decode_base64_content(payload.content_base64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return save_uploaded_document_with_job(
        client_id=payload.client_id,
        document_type=payload.document_type,
        intake_category=payload.intake_category,
        file_name=payload.file_name,
        uploaded_by=payload.uploaded_by,
        uploaded_by_user_id=payload.uploaded_by_user_id,
        request_user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        content=content,
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        retention_policy_days=payload.retention_policy_days,
    )


@router.post("/store/document-upload-multipart")
async def store_document_upload_multipart(
    client_id: str = Form(...),
    document_type: Literal["invoice", "einvoice_xml", "bank_statement", "pos_statement", "special_document"] = Form("invoice"),
    intake_category: str = Form(""),
    uploaded_by: str = Form(""),
    uploaded_by_user_id: str = Form(""),
    retention_policy_days: int = Form(90),
    file: UploadFile = File(...),
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    content = await file.read()
    return save_uploaded_document_with_job(
        client_id=client_id,
        document_type=document_type,
        intake_category=intake_category,
        file_name=file.filename or "document.bin",
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        content=content,
        size_bytes=len(content),
        retention_policy_days=retention_policy_days,
    )


@router.post("/store/document-retention/run")
def store_document_retention_run(payload: DocumentRetentionRunPayload) -> dict[str, object]:
    store = get_workflow_store()
    summary = store.apply_document_retention(delete_files=payload.delete_files)
    record_operation_event(
        store=store,
        client_id="__system__",
        event_type="document_retention_run",
        status="warning" if summary["deleted_count"] else "ok",
        message="90 gun belge retention job'u calisti.",
        metadata=summary,
    )
    return summary


@router.post("/store/processing/run")
def store_processing_run(payload: ProcessingRunPayload) -> dict[str, object]:
    store = get_workflow_store()
    summary = process_queued_documents(store, max_jobs=payload.max_jobs)
    record_operation_event(
        store=store,
        client_id="__system__",
        event_type="processing_run",
        status="error" if summary["failed_count"] else "ok",
        message="Worker kuyrugu manuel/API tetiklemesiyle calisti.",
        metadata=summary,
    )
    return summary


@router.get("/store/processing-jobs/{client_id}")
def store_processing_jobs(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    require_client_access(
        client_id=client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )
    return {"jobs": get_workflow_store().list_processing_jobs(client_id=client_id)}
