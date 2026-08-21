from __future__ import annotations

from collections.abc import Callable
import os
from typing import Any

from fastapi import HTTPException, Response

from app.domain.auth_policy import build_auth_config, resolve_user_id
from app.domain.operation_monitoring import build_operation_event, operation_event_payload
from app.domain.session_auth import hash_session_token


StoreFactory = Callable[[], Any]


def session_cookie_secure() -> bool:
    return os.environ.get("FISORA_SESSION_COOKIE_SECURE", "true").strip().lower() not in {"0", "false", "no"}


def session_cookie_samesite() -> str:
    value = os.environ.get("FISORA_SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def set_session_cookie(response: Response, token: str, *, ttl_hours: int, cookie_name: str) -> None:
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max(ttl_hours, 1) * 3600,
        httponly=True,
        secure=session_cookie_secure(),
        samesite=session_cookie_samesite(),
        path="/",
    )


def clear_session_cookie(response: Response, *, cookie_name: str) -> None:
    response.delete_cookie(
        key=cookie_name,
        httponly=True,
        secure=session_cookie_secure(),
        samesite=session_cookie_samesite(),
        path="/",
    )


def client_id_from_record(record: dict[str, object]) -> str:
    profile = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    return str(record.get("client_id") or profile.get("client_id") or "").strip()


def mock_user_header(value: str | None) -> str:
    return resolve_user_id(value, build_auth_config())


def request_user_id(
    user_header: str | None,
    session_header: str | None = None,
    session_cookie: str | None = None,
    *,
    store_factory: StoreFactory,
) -> str:
    auth_config = build_auth_config()
    if auth_config.accepts_user_header:
        user_id = mock_user_header(user_header)
        if user_id:
            return user_id
    token = (session_header or session_cookie or "").strip()
    if not token:
        if auth_config.mode == "session_required":
            raise HTTPException(status_code=401, detail={"valid": False, "reason": "session_required"})
        return ""
    session = store_factory().resolve_auth_session(token_hash=hash_session_token(token))
    if not session.get("valid"):
        raise HTTPException(status_code=401, detail=session)
    return str(session.get("user_id") or "")


def request_auth_context(
    user_header: str | None,
    session_header: str | None = None,
    session_cookie: str | None = None,
    *,
    store_factory: StoreFactory,
) -> dict[str, object]:
    auth_config = build_auth_config()
    user_id = ""
    if auth_config.accepts_user_header:
        user_id = mock_user_header(user_header)

    token = (session_header or session_cookie or "").strip()
    session: dict[str, object] = {}
    if token:
        session = store_factory().resolve_auth_session(token_hash=hash_session_token(token))
        if not session.get("valid"):
            raise HTTPException(status_code=401, detail=session)
    elif auth_config.mode == "session_required":
        raise HTTPException(status_code=401, detail={"valid": False, "reason": "session_required"})

    if not user_id:
        user_id = str(session.get("user_id") or "")
    return {
        "user_id": user_id,
        "session_kind": str(session.get("session_kind") or ""),
        "delegated_by": str(session.get("delegated_by") or ""),
        "delegated_client_id": str(session.get("delegated_client_id") or ""),
        "session_reason": str(session.get("reason") or ""),
    }


def require_mock_client_access(
    *,
    client_id: str,
    user_id: str | None,
    store_factory: StoreFactory,
    allowed_roles: tuple[str, ...] = (),
) -> dict[str, object]:
    auth_config = build_auth_config()
    if not user_id:
        if auth_config.allows_anonymous_access:
            return {
                "allowed": True,
                "reason": "mock_auth_optional_anonymous",
                "role": "anonymous",
                "client_id": client_id,
                "auth_mode": auth_config.mode,
            }
        raise HTTPException(
            status_code=401,
            detail={
                "allowed": False,
                "reason": "portal_user_required",
                "auth_mode": auth_config.mode,
                "user_header_name": auth_config.user_header_name,
            },
        )
    access = store_factory().verify_portal_access(client_id=client_id, user_id=user_id)
    if not access.get("allowed"):
        raise HTTPException(status_code=403, detail=access)
    role = str(access.get("role") or "")
    if allowed_roles and role not in allowed_roles and role != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                **access,
                "reason": "role_not_allowed",
                "allowed_roles": list(allowed_roles),
            },
        )
    return access


def require_accountant_or_admin(
    *,
    user_header: str | None,
    session_header: str | None = None,
    session_cookie: str | None = None,
    store_factory: StoreFactory,
) -> dict[str, object]:
    auth_config = build_auth_config()
    if os.environ.get("FISORA_ENV", "").strip().lower() != "production":
        return {"allowed": True, "role": "development_bootstrap", "user_id": ""}
    user_id = request_user_id(
        user_header, session_header, session_cookie, store_factory=store_factory
    )
    store = store_factory()
    user = store.get_portal_user(user_id) if hasattr(store, "get_portal_user") else None
    if not user:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "portal_user_not_found"})
    role = str(user.get("role") or "").strip().lower()
    if role not in {"accountant", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"allowed": False, "reason": "role_not_allowed", "allowed_roles": ["accountant", "admin"]},
        )
    return {"allowed": True, "role": role, "user_id": user_id}


def password_bootstrap_enabled() -> bool:
    return os.environ.get("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def record_operation_event(
    *,
    store: Any,
    client_id: str,
    event_type: str,
    status: str = "info",
    message: str = "",
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    event = operation_event_payload(
        build_operation_event(
            client_id=client_id,
            event_type=event_type,
            status=status,
            message=message,
            metadata=metadata,
        )
    )
    return store.record_operation_event(client_id=str(event["client_id"]), event=event)
