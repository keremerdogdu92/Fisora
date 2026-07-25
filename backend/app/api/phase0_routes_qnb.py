from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_qnb_connection_service,
    get_workflow_store,
    request_user_id,
    require_client_access,
)
from app.api.phase0_schemas import (
    QnbConnectionPayload,
    QnbIncomingBulkStatusPayload,
    QnbIncomingStatusPayload,
    QnbOutgoingBulkStatusPayload,
    QnbOutgoingStatusPayload,
    QnbSyncPayload,
    QnbSyncPolicyPayload,
)
from app.domain.qnb_scheduler import normalize_qnb_sync_policy


router = APIRouter()


def _require_qnb_admin_access(client_id: str, user_id: str | None) -> None:
    require_client_access(
        client_id=client_id,
        user_id=user_id,
        allowed_roles=("accountant", "admin"),
    )


@router.post("/qnb/connections/{client_id}")
def save_qnb_connection(
    client_id: str,
    payload: QnbConnectionPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    _require_qnb_admin_access(client_id, user_id)
    try:
        return get_qnb_connection_service().save_connection(
            client_id=client_id,
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            vkn=payload.vkn,
            erp_code=payload.erp_code,
            environment=payload.environment,
            actor_user_id=str(user_id or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/qnb/connections/{client_id}/disable")
def disable_qnb_connection(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    _require_qnb_admin_access(client_id, user_id)
    try:
        return get_qnb_connection_service().disable_connection(client_id=client_id, actor_user_id=str(user_id or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/qnb/connections/{client_id}")
def get_qnb_connection(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    _require_qnb_admin_access(client_id, user_id)
    return get_qnb_connection_service().public_connection(client_id=client_id)


@router.post("/qnb/connections/{client_id}/sync-incoming-invoices")
def sync_qnb_incoming_invoices(
    client_id: str,
    payload: QnbSyncPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    _require_qnb_admin_access(client_id, user_id)
    connection = get_workflow_store().get_qnb_connection(client_id=client_id)
    if not connection or connection.get("status") != "active":
        raise HTTPException(
            status_code=400,
            detail="active QNB connection is required",
        )
    return get_workflow_store().enqueue_qnb_sync_request(
        client_id=client_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        requested_by=user_id or "",
    )


@router.get("/qnb/connections/{client_id}/sync-policy")
def get_qnb_sync_policy(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    store = get_qnb_connection_service().store
    return store.get_qnb_sync_policy(client_id=client_id) or normalize_qnb_sync_policy({})


@router.get("/qnb/connections/{client_id}/health")
def get_qnb_health(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    service = get_qnb_connection_service()
    connection = service.public_connection(client_id=client_id)
    policy = service.store.get_qnb_sync_policy(client_id=client_id) or normalize_qnb_sync_policy({})
    runs = service.store.list_qnb_sync_runs(client_id=client_id, limit=10)
    latest = runs[0] if runs else {}
    return {
        "client_id": client_id,
        "connection": connection,
        "policy": policy,
        "latest_run": latest,
        "recent_runs": runs,
        "cursor": service.store.get_qnb_sync_cursor(client_id=client_id),
        "health_status": "error" if policy.get("last_run_status") == "failed" else "active" if connection.get("status") == "active" else connection.get("status", "missing"),
        "safe_message": "Son otomatik senkronizasyon başarısız; bağlantıyı test edin." if policy.get("last_run_status") == "failed" else "QNB otomatik belge akışı çalışıyor." if connection.get("status") == "active" and policy.get("enabled") else "QNB bağlantısı hazır; otomatik akış kapalı." if connection.get("status") == "active" else "QNB bağlantısı kurulmalı.",
    }


@router.post("/qnb/connections/{client_id}/sync-policy")
def save_qnb_sync_policy(
    client_id: str,
    payload: QnbSyncPolicyPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    service = get_qnb_connection_service()
    if payload.enabled:
        service._active_credentials(client_id)
    policy = normalize_qnb_sync_policy(payload.model_dump())
    return service.store.save_qnb_sync_policy(client_id=client_id, policy=policy)


@router.post("/qnb/connections/{client_id}/outgoing-invoices/status")
def reconcile_qnb_outgoing_invoice(
    client_id: str,
    payload: QnbOutgoingStatusPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return get_qnb_connection_service().reconcile_outgoing_invoice(
            client_id=client_id, document_oid=payload.document_oid, invoice_no=payload.invoice_no
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/qnb/connections/{client_id}/outgoing-invoices/status/bulk")
def reconcile_qnb_outgoing_invoices(
    client_id: str,
    payload: QnbOutgoingBulkStatusPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    return get_qnb_connection_service().reconcile_outgoing_invoices(client_id=client_id, document_oids=payload.document_oids)


@router.get("/qnb/connections/{client_id}/outgoing-invoices")
def list_qnb_outgoing_invoices(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    items = get_qnb_connection_service().store.list_qnb_outgoing_invoices(client_id=client_id)
    return {"count": len(items), "items": items}


@router.post("/qnb/connections/{client_id}/incoming-invoices/status")
def reconcile_qnb_incoming_invoice(
    client_id: str,
    payload: QnbIncomingStatusPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return get_qnb_connection_service().reconcile_incoming_invoice(client_id=client_id, ettn=payload.ettn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/qnb/connections/{client_id}/incoming-invoices/pdf")
def download_qnb_incoming_pdf(
    client_id: str,
    payload: QnbIncomingStatusPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return get_qnb_connection_service().download_incoming_pdf(client_id=client_id, ettn=payload.ettn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/qnb/connections/{client_id}/incoming-invoices/status/bulk")
def reconcile_qnb_incoming_invoices(
    client_id: str,
    payload: QnbIncomingBulkStatusPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_qnb_admin_access(client_id, request_user_id(x_fisora_user_id, x_fisora_session, fisora_session))
    return get_qnb_connection_service().reconcile_incoming_invoices(client_id=client_id, ettns=payload.ettns)
