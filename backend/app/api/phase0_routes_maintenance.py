from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_pilot_reinitialization_service,
    get_workflow_store,
    request_user_id,
)
from app.api.phase0_schemas import PilotReinitializationExecutePayload
from app.services.pilot_reinitialization_service import (
    PILOT_REINITIALIZATION_CONFIRMATION,
    PilotReinitializationError,
)


router = APIRouter()


def _require_accountant_or_admin(
    *,
    x_fisora_user_id: str | None,
    x_fisora_session: str | None,
    fisora_session: str | None,
) -> dict[str, str]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail={"allowed": False, "reason": "user_required"})
    user = get_workflow_store().get_portal_user(user_id)
    if not user:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "accountant_required"})
    role = str(user.get("role") or "").strip().lower()
    if role not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "accountant_required"})
    return {"user_id": user_id, "role": role}


def _raise_service_error(exc: PilotReinitializationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail={"allowed": False, "reason": exc.reason}) from exc


@router.get("/store/admin/pilot-reinitialization/preview")
def pilot_reinitialization_preview(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_accountant_or_admin(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    try:
        return get_pilot_reinitialization_service().preview()
    except PilotReinitializationError as exc:
        _raise_service_error(exc)


@router.post("/store/admin/pilot-reinitialization")
def pilot_reinitialization_execute(
    payload: PilotReinitializationExecutePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    auth = _require_accountant_or_admin(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    if payload.confirmation != PILOT_REINITIALIZATION_CONFIRMATION:
        raise HTTPException(status_code=400, detail={"allowed": False, "reason": "confirmation_required"})
    try:
        return get_pilot_reinitialization_service().execute(
            actor_user_id=auth["user_id"],
            confirmation=payload.confirmation,
            preview_fingerprint=payload.preview_fingerprint,
            delete_files=payload.delete_files,
        )
    except PilotReinitializationError as exc:
        _raise_service_error(exc)
