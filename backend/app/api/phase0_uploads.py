from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.domain.document_uploads import store_document_content
from app.services.document_identity import extract_source_identities
from app.workflows.document_processing import parser_kind_for_document_type


OperationRecorder = Callable[..., dict[str, object]]


def save_uploaded_document_with_job(
    *,
    store: Any,
    document_storage_path: Path,
    record_operation_event: OperationRecorder,
    client_id: str,
    document_type: str,
    intake_category: str = "",
    period: str = "",
    file_name: str,
    uploaded_by: str,
    uploaded_by_user_id: str = "",
    request_user_id: str = "",
    content: bytes | None,
    size_bytes: int = 0,
    sha256: str = "",
    retention_policy_days: int = 90,
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for document upload")
    effective_user_id = uploaded_by_user_id.strip() or uploaded_by.strip() or request_user_id.strip()
    if request_user_id.strip() and effective_user_id and request_user_id.strip() != effective_user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "allowed": False,
                "reason": "mock_user_header_mismatch",
                "user_id": request_user_id.strip(),
                "payload_user_id": effective_user_id,
            },
        )
    if not effective_user_id:
        raise HTTPException(status_code=403, detail="portal user is required for document upload")
    access = store.verify_portal_access(client_id=client_id, user_id=effective_user_id)
    if not access.get("allowed"):
        raise HTTPException(status_code=403, detail=access)
    try:
        document = store_document_content(
            base_dir=document_storage_path,
            client_id=client_id,
            file_name=file_name,
            document_type=document_type,
            intake_category=intake_category,
            period=period,
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
    if hasattr(store, "accept_document_source"):
        saved = store.accept_document_source(
            client_id=client_id,
            document=document_payload,
            source_channel="manual_upload",
            identities=extract_source_identities(content=content, file_name=file_name),
            parser_kind=parser_kind_for_document_type(document_type),
            intake_category=str(document_payload.get("intake_category") or ""),
        )
        job = dict(saved.get("processing_job") or {})
    else:
        saved = store.save_uploaded_document(
            client_id=client_id,
            document=document_payload,
        )
        job = store.create_processing_job(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            document_type=document_type,
            parser_kind=parser_kind_for_document_type(document_type),
            intake_category=str(saved.get("intake_category") or ""),
        )
    record_operation_event(
        store=store,
        client_id=client_id,
        event_type="document_uploaded",
        status="ok",
        message="Belge kaydedildi ve processing job kuyruga alindi.",
        metadata={
            "document_ref": saved["document_ref"],
            "document_type": document_type,
            "intake_category": saved.get("intake_category", ""),
            "period": saved.get("period", ""),
            "file_name": file_name,
            "processing_job_id": job["id"],
            "parser_kind": job["parser_kind"],
            "uploaded_by_user_id": effective_user_id,
        },
    )
    return {**saved, "processing_job": job}
