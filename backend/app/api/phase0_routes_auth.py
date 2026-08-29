from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    clear_portal_session_cookie,
    default_document_storage_path,
    default_export_path,
    default_protected_corpus_path,
    get_workflow_store,
    password_bootstrap_enabled,
    require_accountant_or_admin,
    require_client_access,
    request_user_id,
    set_portal_session_cookie,
)
from app.api.rate_limit import enforce_rate_limit
from app.api.phase0_schemas import (
    AuthInviteAcceptPayload,
    AuthInvitePayload,
    AuthLoginPayload,
    AuthLogoutPayload,
    AuthPasswordPayload,
    AuthPasswordResetConfirmPayload,
    AuthPasswordResetPayload,
    AuthPasswordResetRequestPayload,
    ClientPortalAccessUpdatePayload,
    DelegatedClientSessionPayload,
    PortalAccessPayload,
    PortalUserPayload,
    TestDataResetPayload,
)
from app.domain.auth_policy import auth_status_payload, build_auth_config
from app.domain.email_delivery import send_auth_email
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


def _portal_action_url(path: str, token: str) -> str:
    portal_base_url = os.getenv("FISORA_PORTAL_BASE_URL", "").rstrip("/")
    return f"{portal_base_url}{path}?token={token}" if portal_base_url else ""


def _auth_email_delivery(
    *,
    recipient: str,
    subject: str,
    body_text: str,
    action_url: str,
) -> dict[str, object]:
    if not recipient.strip() or not action_url:
        return {
            "status": "manual_link",
            "provider": "manual",
            "recipient": recipient.strip(),
            "action_url": action_url,
        }
    return send_auth_email(
        recipient=recipient.strip(),
        subject=subject,
        body_text=body_text,
        action_url=action_url,
    )


@router.post("/store/portal-user")
def store_portal_user(
    payload: PortalUserPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required for portal user")
    try:
        return get_workflow_store().upsert_portal_user(
            user_id=payload.user_id,
            display_name=payload.display_name,
            role=payload.role,
            allowed_client_ids=payload.allowed_client_ids,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/store/portal-access/check")
def store_portal_access_check(
    payload: PortalAccessPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
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


@router.post("/store/client-portal-access")
def store_client_portal_access(
    payload: ClientPortalAccessUpdatePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    if not payload.new_user_id.strip():
        raise HTTPException(status_code=400, detail="new_user_id is required")
    actor_user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    require_client_access(
        client_id=payload.client_id.strip(),
        user_id=actor_user_id,
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    try:
        result = store.replace_client_portal_user(
            client_id=payload.client_id.strip(),
            old_user_id=payload.old_user_id.strip(),
            new_user_id=payload.new_user_id.strip(),
            display_name=payload.display_name.strip(),
        )
        if payload.password.strip():
            if build_auth_config().production_ready and not password_bootstrap_enabled():
                raise HTTPException(status_code=403, detail={"allowed": False, "reason": "password_bootstrap_disabled"})
            password_hash = create_password_hash(payload.password)
            result["credential"] = store.set_auth_password(
                user_id=payload.new_user_id.strip(),
                password_hash=password_hash,
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


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


@router.post("/store/auth/delegated-client-session")
def store_auth_delegated_client_session(
    payload: DelegatedClientSessionPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    client_id = payload.client_id.strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    actor_user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    require_client_access(
        client_id=client_id,
        user_id=actor_user_id,
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    workspace = store.get_workspace(client_id)
    target_user_id = payload.target_user_id.strip()
    if not target_user_id:
        target_user_id = next(
            (
                str(user.get("user_id") or "").strip()
                for user in workspace.get("portal_users", [])
                if str(user.get("role") or "").strip().lower() == "client_user"
            ),
            "",
        )
    if not target_user_id:
        raise HTTPException(status_code=400, detail={"allowed": False, "reason": "client_portal_user_required"})
    target_access = store.verify_portal_access(client_id=client_id, user_id=target_user_id)
    if not target_access.get("allowed"):
        raise HTTPException(status_code=403, detail=target_access)
    if str(target_access.get("role") or "").strip().lower() != "client_user":
        raise HTTPException(
            status_code=403,
            detail={
                **target_access,
                "reason": "target_role_not_allowed",
                "allowed_roles": ["client_user"],
            },
        )
    session_token = create_session_token()
    try:
        expires_at = session_expires_at(ttl_hours=payload.ttl_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = store.create_auth_session(
        user_id=target_user_id,
        token_hash=session_token.token_hash,
        expires_at=expires_at,
        session_kind="delegated_client",
        delegated_by=actor_user_id,
        delegated_client_id=client_id,
    )
    return {
        "session_token": session_token.raw_token,
        "session": session,
        "delegated_by": actor_user_id,
        "delegated_client_id": client_id,
    }


@router.post("/store/auth/invite")
def store_auth_invite(
    payload: AuthInvitePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    store = get_workflow_store()
    try:
        portal_user = store.upsert_portal_user(
            user_id=payload.user_id.strip(),
            display_name=payload.display_name,
            role=payload.role,
            allowed_client_ids=payload.allowed_client_ids,
            email=payload.email,
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
            "email": payload.email,
        },
    )
    action_url = _portal_action_url("/portal/invite", token.raw_token)
    email_delivery = _auth_email_delivery(
        recipient=payload.email,
        subject="Fisora portal daveti",
        body_text=f"Fisora portal davet linkiniz: {action_url or token.raw_token}",
        action_url=action_url,
    )
    return {
        "invite_token": token.raw_token,
        "token": token_record,
        "portal_user": portal_user,
        "invite_url": action_url,
        "email_delivery": email_delivery,
    }


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


@router.post("/store/auth/password-reset/request")
def store_auth_password_reset_request(payload: AuthPasswordResetRequestPayload, request: Request) -> dict[str, object]:
    enforce_rate_limit(scope="auth", request=request)
    email = payload.email.strip().lower()
    generic = {"accepted": True, "message": "Hesap bulunursa sifre sifirlama baglantisi e-posta adresine gonderildi."}
    if not email:
        return generic
    store = get_workflow_store()
    portal_user = store.find_portal_user_by_email(email=email) if hasattr(store, "find_portal_user_by_email") else None
    user_id = str((portal_user or {}).get("user_id") or "").strip()
    # Email ownership is sufficient for secure first-password recovery of an existing portal user.
    if not user_id:
        return generic
    store.invalidate_auth_tokens_for_user(user_id=user_id, purpose="password_reset")
    token = create_auth_action_token()
    expires_at = action_token_expires_at(ttl_hours=1)
    action_url = _portal_action_url("/portal/password-reset", token.raw_token)
    store.create_auth_token(purpose="password_reset", user_id=user_id, token_hash=token.token_hash, expires_at=expires_at, payload={"email": email})
    _auth_email_delivery(recipient=email, subject="Fisora sifre sifirlama", body_text=f"Fisora sifre sifirlama linkiniz: {action_url or token.raw_token}", action_url=action_url)
    return generic


@router.post("/store/auth/password-reset")
def store_auth_password_reset(
    payload: AuthPasswordResetPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    require_accountant_or_admin(x_fisora_user_id, x_fisora_session, fisora_session)
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    token = create_auth_action_token()
    try:
        expires_at = action_token_expires_at(ttl_hours=payload.ttl_hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    action_url = _portal_action_url("/portal/password-reset", token.raw_token)
    token_record = get_workflow_store().create_auth_token(
        purpose="password_reset",
        user_id=payload.user_id.strip(),
        token_hash=token.token_hash,
        expires_at=expires_at,
        payload={"email": payload.email},
    )
    email_delivery = _auth_email_delivery(
        recipient=payload.email,
        subject="Fisora sifre sifirlama",
        body_text=f"Fisora sifre sifirlama linkiniz: {action_url or token.raw_token}",
        action_url=action_url,
    )
    return {
        "reset_token": token.raw_token,
        "token": token_record,
        "reset_url": action_url,
        "email_delivery": email_delivery,
    }


@router.post("/store/auth/password-reset/confirm")
def store_auth_password_reset_confirm(payload: AuthPasswordResetConfirmPayload) -> dict[str, object]:
    token_hash = hash_session_token(payload.reset_token.strip())
    try:
        password_hash = create_password_hash(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = get_workflow_store()
    token = store.consume_auth_token(purpose="password_reset", token_hash=token_hash)
    if not token.get("valid"):
        raise HTTPException(status_code=400, detail=token)
    user_id = str(token["user_id"])
    credential = store.set_auth_password(user_id=user_id, password_hash=password_hash)
    revoked_sessions = store.revoke_auth_sessions_for_user(user_id=user_id)
    store.invalidate_auth_tokens_for_user(user_id=user_id, purpose="password_reset")
    return {"credential": credential, "token": token, "revoked_sessions": revoked_sessions}


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


@router.post("/store/admin/test-reset")
def store_admin_test_reset(
    payload: TestDataResetPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if payload.confirmation.strip() != "TEMIZLE":
        raise HTTPException(status_code=400, detail={"allowed": False, "reason": "confirmation_required"})
    store = get_workflow_store()
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail={"allowed": False, "reason": "user_required"})
    portal_user = store.get_portal_user(user_id) if hasattr(store, "get_portal_user") else None
    role = str((portal_user or {}).get("role") or "").strip().lower()
    if role not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "accountant_required"})
    if not hasattr(store, "reset_test_data"):
        raise HTTPException(status_code=501, detail={"allowed": False, "reason": "reset_not_supported"})
    return store.reset_test_data(
        document_storage_path=default_document_storage_path(),
        export_path=default_export_path(),
        protected_storage_path=default_protected_corpus_path(),
        delete_files=payload.delete_files,
    )


@router.get("/store/admin/test-reset/preview")
def store_admin_test_reset_preview(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    store = get_workflow_store()
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail={"allowed": False, "reason": "user_required"})
    portal_user = store.get_portal_user(user_id) if hasattr(store, "get_portal_user") else None
    role = str((portal_user or {}).get("role") or "").strip().lower()
    if role not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "accountant_required"})
    if not hasattr(store, "preview_test_data_reset"):
        raise HTTPException(status_code=501, detail={"allowed": False, "reason": "reset_preview_not_supported"})
    return store.preview_test_data_reset()
