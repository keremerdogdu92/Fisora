from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_document_service,
    get_retention_service,
    request_auth_context,
    request_user_id,
    require_accountant_or_admin,
)
from app.api.phase0_schemas import (
    ClientReprocessPayload,
    DocumentReprocessPayload,
    DocumentRetentionActionPayload,
    DocumentRetentionRunPayload,
    DocumentUploadPayload,
    ProcessingRunPayload,
)
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
    auth_context = request_auth_context(x_fisora_user_id, x_fisora_session, fisora_session)
    content = None
    if payload.content_base64:
        try:
            content = decode_base64_content(payload.content_base64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_document_service().store_document_upload(
        client_id=payload.client_id,
        document_type=payload.document_type,
        intake_category=payload.intake_category,
        period=payload.period,
        file_name=payload.file_name,
        uploaded_by=payload.uploaded_by,
        uploaded_by_user_id=payload.uploaded_by_user_id,
        request_user_id=str(auth_context.get("user_id") or ""),
        session_kind=str(auth_context.get("session_kind") or ""),
        delegated_by_user_id=str(auth_context.get("delegated_by") or ""),
        delegated_client_id=str(auth_context.get("delegated_client_id") or ""),
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
    period: str = Form(""),
    uploaded_by: str = Form(""),
    uploaded_by_user_id: str = Form(""),
    retention_policy_days: int = Form(90),
    file: UploadFile = File(...),
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    auth_context = request_auth_context(x_fisora_user_id, x_fisora_session, fisora_session)
    content = await file.read()
    return get_document_service().store_document_upload(
        client_id=client_id,
        document_type=document_type,
        intake_category=intake_category,
        period=period,
        file_name=file.filename or "document.bin",
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=str(auth_context.get("user_id") or ""),
        session_kind=str(auth_context.get("session_kind") or ""),
        delegated_by_user_id=str(auth_context.get("delegated_by") or ""),
        delegated_client_id=str(auth_context.get("delegated_client_id") or ""),
        content=content,
        size_bytes=len(content),
        retention_policy_days=retention_policy_days,
    )


@router.post("/store/document-retention/run")
def store_document_retention_run(
    payload: DocumentRetentionRunPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    document_service = get_document_service()
    if getattr(document_service.store, "normalized_accounting_enabled", False):
        return get_retention_service(document_service.store).run_due(
            now=datetime.now(UTC),
            worker_id="phase0-api-retention",
        )
    return document_service.store_document_retention_run(delete_files=payload.delete_files)


@router.get("/store/document-retention/pending")
def store_document_retention_pending(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail="user_required")
    document_service = get_document_service()
    if not getattr(document_service.store, "normalized_accounting_enabled", False):
        return {"items": []}
    service = get_retention_service(document_service.store)
    try:
        return service.list_pending(user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/store/document-retention/{batch_id}/read")
def store_document_retention_read(
    batch_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail="user_required")
    document_service = get_document_service()
    if not getattr(document_service.store, "normalized_accounting_enabled", False):
        raise HTTPException(status_code=404, detail="retention_batch_not_found_or_access_denied")
    try:
        return get_retention_service(document_service.store).mark_read(batch_id=batch_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/store/document-retention/preview")
def store_document_retention_preview(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    return get_document_service().store_document_retention_preview()


@router.post("/store/document-retention/action")
def store_document_retention_action(
    payload: DocumentRetentionActionPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    return get_document_service().store_document_retention_action(
        document_refs=payload.document_refs,
        action=payload.action,
        delete_files=payload.delete_files,
    )


@router.post("/store/processing/run")
def store_processing_run(
    payload: ProcessingRunPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    return get_document_service().store_processing_run(max_jobs=payload.max_jobs)


@router.post("/store/document-reprocess")
def store_document_reprocess(
    payload: DocumentReprocessPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_document_service().store_document_reprocess(
        client_id=payload.client_id,
        document_ref=payload.document_ref,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.post("/store/client-reprocess")
def store_client_reprocess(
    payload: ClientReprocessPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_document_service().store_client_reprocess(
        client_id=payload.client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        max_jobs=payload.max_jobs,
    )


@router.get("/store/processing-jobs/{client_id}")
def store_processing_jobs(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_document_service().store_processing_jobs(
        client_id=client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.post("/store/client-onboarding-attachment")
async def store_client_onboarding_attachment(
    client_id: str = Form(...),
    attachment_type: str = Form("tax_certificate"),
    uploaded_by: str = Form(""),
    uploaded_by_user_id: str = Form(""),
    retention_policy_days: int = Form(365),
    file: UploadFile = File(...),
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    content = await file.read()
    return get_document_service().store_onboarding_attachment(
        client_id=client_id,
        attachment_type=attachment_type,
        file_name=file.filename or "attachment.bin",
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        content=content,
        size_bytes=len(content),
        retention_policy_days=retention_policy_days,
    )


@router.get("/store/document-pipeline/{client_id}/{document_ref}")
def store_document_pipeline(
    client_id: str,
    document_ref: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    return get_document_service().document_pipeline(
        client_id=client_id,
        document_ref=document_ref,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )


@router.get("/store/document-file/{client_id}/{document_ref}")
def store_document_file(
    client_id: str,
    document_ref: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Response:
    file_info = get_document_service().original_document_file(
        client_id=client_id,
        document_ref=document_ref,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )
    if "html" in file_info:
        return HTMLResponse(
            content=str(file_info["html"]),
            media_type=str(file_info["media_type"]),
        )
    return FileResponse(
        file_info["path"],
        filename=str(file_info["file_name"]),
        media_type=str(file_info["media_type"]),
    )
