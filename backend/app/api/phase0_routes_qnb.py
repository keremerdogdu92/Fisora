from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_qnb_connection_service,
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
)


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
    try:
        return get_qnb_connection_service().sync_incoming_invoices(
            client_id=client_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
