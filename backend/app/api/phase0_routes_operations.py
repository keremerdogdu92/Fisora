from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    default_backup_path,
    default_document_storage_path,
    default_export_path,
    get_workflow_store,
    record_operation_event,
    request_user_id,
    require_client_access,
)
from app.api.phase0_schemas import OperationEventPayload
from app.domain.operation_monitoring import summarize_operation_health
from app.domain.production_readiness import production_readiness_payload


router = APIRouter()


@router.get("/store/system/readiness")
def store_system_readiness() -> dict[str, object]:
    return production_readiness_payload(
        document_storage_path=default_document_storage_path(),
        export_path=default_export_path(),
        backup_path=default_backup_path(),
    )


@router.post("/store/operation-log")
def store_operation_log(
    payload: OperationEventPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    if payload.client_id != "__system__":
        require_client_access(
            client_id=payload.client_id,
            user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
            allowed_roles=("accountant", "admin"),
        )
    return record_operation_event(
        store=get_workflow_store(),
        client_id=payload.client_id,
        event_type=payload.event_type,
        status=payload.status,
        message=payload.message,
        metadata=payload.metadata,
    )


@router.get("/store/operation-health/{client_id}")
def store_operation_health(
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
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    events = store.list_operation_events(client_id=client_id)
    jobs = store.list_processing_jobs(client_id=client_id)
    return {
        "client_id": client_id,
        "summary": summarize_operation_health(events=events, processing_jobs=jobs),
        "events": events,
        "processing_jobs": jobs,
    }
