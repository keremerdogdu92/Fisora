from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_outgoing_invoice_service,
    request_user_id,
    require_client_access,
)
from app.api.phase0_schemas import OutgoingInvoiceDraftPayload, OutgoingInvoiceSendPayload


router = APIRouter()


def _safe_outgoing_action_error(exc: ValueError) -> str:
    message = str(exc or "")
    allowed_markers = (
        "approved invoice",
        "idempotency key",
        "provider is disabled",
        "frozen ubl",
        "active client-scoped qnb connection",
        "test endpoint",
        "sandbox requires",
        "supplier tax id",
        "requiring reconciliation",
        "reconciliation attempt",
        "mutating request was not started",
        "resultcode",
    )
    if any(marker in message.lower() for marker in allowed_markers):
        return message[:240]
    return "Giden fatura sağlayıcı işlemi tamamlanamadı; deneme kaydını kontrol edin."


def _access(
    client_id: str,
    user_header: str | None,
    session_header: str | None,
    session_cookie: str | None,
) -> str:
    user_id = request_user_id(user_header, session_header, session_cookie)
    require_client_access(client_id=client_id, user_id=user_id, allowed_roles=("accountant", "admin"))
    return str(user_id or "")


@router.post("/outgoing-invoices/{client_id}/drafts")
def create_outgoing_invoice_draft(
    client_id: str,
    payload: OutgoingInvoiceDraftPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _access(client_id, x_fisora_user_id, x_fisora_session, fisora_session)
    try:
        return get_outgoing_invoice_service().create_draft(
            client_id=client_id, payload=payload.model_dump(), actor_user_id=actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/outgoing-invoices/{client_id}/drafts")
def list_outgoing_invoices(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> list[dict[str, object]]:
    _access(client_id, x_fisora_user_id, x_fisora_session, fisora_session)
    return get_outgoing_invoice_service().list(client_id=client_id)


@router.get("/outgoing-invoices/{client_id}/drafts/{invoice_id}")
def get_outgoing_invoice(
    client_id: str,
    invoice_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _access(client_id, x_fisora_user_id, x_fisora_session, fisora_session)
    try:
        return get_outgoing_invoice_service().get(client_id=client_id, invoice_id=invoice_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/outgoing-invoices/{client_id}/drafts/{invoice_id}/approve")
def approve_outgoing_invoice(
    client_id: str,
    invoice_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _access(client_id, x_fisora_user_id, x_fisora_session, fisora_session)
    try:
        return get_outgoing_invoice_service().approve(
            client_id=client_id, invoice_id=invoice_id, actor_user_id=actor
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/outgoing-invoices/{client_id}/drafts/{invoice_id}/send")
def send_outgoing_invoice(
    client_id: str,
    invoice_id: str,
    payload: OutgoingInvoiceSendPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _access(client_id, x_fisora_user_id, x_fisora_session, fisora_session)
    try:
        return get_outgoing_invoice_service().send(
            client_id=client_id,
            invoice_id=invoice_id,
            idempotency_key=payload.idempotency_key,
            actor_user_id=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_safe_outgoing_action_error(exc)) from exc


@router.post("/outgoing-invoices/{client_id}/drafts/{invoice_id}/reconcile")
def reconcile_outgoing_invoice(
    client_id: str,
    invoice_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _access(client_id, x_fisora_user_id, x_fisora_session, fisora_session)
    try:
        return get_outgoing_invoice_service().reconcile(
            client_id=client_id,
            invoice_id=invoice_id,
            actor_user_id=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_safe_outgoing_action_error(exc)) from exc
