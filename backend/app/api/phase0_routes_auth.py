from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException, Response

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    clear_portal_session_cookie,
    get_workflow_store,
    password_bootstrap_enabled,
    set_portal_session_cookie,
)
from app.api.phase0_schemas import (
    AuthInviteAcceptPayload,
    AuthInvitePayload,
    AuthLoginPayload,
    AuthLogoutPayload,
    AuthPasswordPayload,
    AuthPasswordResetConfirmPayload,
    AuthPasswordResetPayload,
    PortalAccessPayload,
    PortalUserPayload,
)
from app.domain.auth_policy import auth_status_payload, build_auth_config
from app.domain.session_auth import (
    action_token_expires_at,
    create_auth_action_token,
    create_password_hash,
    create_session_token,
    hash_session_token,
    session_expires_at,
    verify_password,
)


router = APIRouter()


@router.post("/store/portal-user")
def store_portal_user(payload: PortalUserPayload) -> dict[str, object]:
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required for portal user")
    try:
        return get_workflow_store().upsert_portal_user(
            user_id=payload.user_id,
            display_name=payload.display_name,
            role=payload.role,
            allowed_client_ids=payload.allowed_client_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/store/portal-access/check")
def store_portal_access_check(payload: PortalAccessPayload) -> dict[str, object]:
    if not payload.client_id.strip() or not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="client_id and user_id are required")
    return get_workflow_store().verify_portal_access(client_id=payload.client_id, user_id=payload.user_id)


@router.get("/store/auth/status")
def store_auth_status() -> dict[str, object]:
    return auth_status_payload(build_auth_config())


@router.post("/store/auth/password")
def store_auth_password(payload: AuthPasswordPayload) -> dict[str, object]:
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    if build_auth_config().production_ready and not password_bootstrap_enabled():
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "password_bootstrap_disabled"})
    try:
        password_hash = create_password_hash(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_workflow_store().set_auth_password(user_id=payload.user_id.strip(), password_hash=password_hash)


@router.post("/store/auth/login")
def store_auth_login(payload: AuthLoginPayload, response: Response) -> dict[str, object]:
    store = get_workflow_store()
    password_hash = store.get_auth_password_hash(user_id=payload.user_id.strip())
    if not password_hash or not verify_password(payload.password, password_hash):
        raise HTTPException(status_code=401, detail={"allowed": False, "reason": "invalid_credentials"})
    session_token = create_session_token()
    try:
        expires_at = session_expires_at(ttl_hours=payload.ttl_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = store.create_auth_session(
        user_id=payload.user_id.strip(),
        token_hash=session_token.token_hash,
        expires_at=expires_at,
    )
    set_portal_session_cookie(response, session_token.raw_token, ttl_hours=payload.ttl_hours)
    return {"session_token": session_token.raw_token, "session": session}


@router.post("/store/auth/invite")
def store_auth_invite(payload: AuthInvitePayload) -> dict[str, object]:
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    store = get_workflow_store()
    try:
        portal_user = store.upsert_portal_user(
            user_id=payload.user_id.strip(),
            display_name=payload.display_name,
            role=payload.role,
            allowed_client_ids=payload.allowed_client_ids,
        )
        expires_at = action_token_expires_at(ttl_hours=payload.ttl_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = create_auth_action_token()
    token_record = store.create_auth_token(
        purpose="invite",
        user_id=payload.user_id.strip(),
        token_hash=token.token_hash,
        expires_at=expires_at,
        payload={
            "display_name": payload.display_name,
            "role": payload.role,
            "allowed_client_ids": payload.allowed_client_ids,
            "invited_by": payload.invited_by,
        },
    )
    return {"invite_token": token.raw_token, "token": token_record, "portal_user": portal_user}


@router.post("/store/auth/invite/accept")
def store_auth_invite_accept(payload: AuthInviteAcceptPayload) -> dict[str, object]:
    token_hash = hash_session_token(payload.invite_token.strip())
    store = get_workflow_store()
    token = store.resolve_auth_token(purpose="invite", token_hash=token_hash)
    if not token.get("valid"):
        raise HTTPException(status_code=400, detail=token)
    try:
        password_hash = create_password_hash(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    credential = store.set_auth_password(user_id=str(token["user_id"]), password_hash=password_hash)
    used = store.mark_auth_token_used(token_hash=token_hash)
    return {"credential": credential, "token": used}


@router.post("/store/auth/password-reset")
def store_auth_password_reset(payload: AuthPasswordResetPayload) -> dict[str, object]:
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    token = create_auth_action_token()
    try:
        expires_at = action_token_expires_at(ttl_hours=payload.ttl_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token_record = get_workflow_store().create_auth_token(
        purpose="password_reset",
        user_id=payload.user_id.strip(),
        token_hash=token.token_hash,
        expires_at=expires_at,
        payload={},
    )
    return {"reset_token": token.raw_token, "token": token_record}


@router.post("/store/auth/password-reset/confirm")
def store_auth_password_reset_confirm(payload: AuthPasswordResetConfirmPayload) -> dict[str, object]:
    token_hash = hash_session_token(payload.reset_token.strip())
    store = get_workflow_store()
    token = store.resolve_auth_token(purpose="password_reset", token_hash=token_hash)
    if not token.get("valid"):
        raise HTTPException(status_code=400, detail=token)
    try:
        password_hash = create_password_hash(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    credential = store.set_auth_password(user_id=str(token["user_id"]), password_hash=password_hash)
    used = store.mark_auth_token_used(token_hash=token_hash)
    return {"credential": credential, "token": used}


@router.get("/store/auth/session")
def store_auth_session(
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    token = (x_fisora_session or fisora_session or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail={"valid": False, "reason": "session_required"})
    session = get_workflow_store().resolve_auth_session(token_hash=hash_session_token(token))
    if not session.get("valid"):
        raise HTTPException(status_code=401, detail=session)
    return session


@router.post("/store/auth/logout")
def store_auth_logout(
    payload: AuthLogoutPayload,
    response: Response,
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    token = (payload.session_token or x_fisora_session or fisora_session or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="session token is required")
    result = get_workflow_store().revoke_auth_session(token_hash=hash_session_token(token))
    clear_portal_session_cookie(response)
    return result
