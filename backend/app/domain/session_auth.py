from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets


DEFAULT_PASSWORD_ITERATIONS = 210_000
DEFAULT_SESSION_TTL_HOURS = 12


@dataclass(frozen=True)
class SessionToken:
    raw_token: str
    token_hash: str


@dataclass(frozen=True)
class AuthActionToken:
    raw_token: str
    token_hash: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def create_password_hash(password: str, *, iterations: int = DEFAULT_PASSWORD_ITERATIONS) -> str:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            "pbkdf2_sha256",
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("ascii"), validate=True)
        expected = base64.b64decode(digest_raw.encode("ascii"), validate=True)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_session_token() -> SessionToken:
    raw_token = secrets.token_urlsafe(32)
    return SessionToken(raw_token=raw_token, token_hash=hash_session_token(raw_token))


def create_auth_action_token() -> AuthActionToken:
    raw_token = secrets.token_urlsafe(32)
    return AuthActionToken(raw_token=raw_token, token_hash=hash_session_token(raw_token))


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def session_expires_at(*, ttl_hours: int = DEFAULT_SESSION_TTL_HOURS, now: datetime | None = None) -> str:
    if ttl_hours <= 0:
        raise ValueError("ttl_hours must be positive")
    return isoformat((now or utc_now()) + timedelta(hours=ttl_hours))


def action_token_expires_at(*, ttl_hours: int = 48, now: datetime | None = None) -> str:
    if ttl_hours <= 0:
        raise ValueError("ttl_hours must be positive")
    return isoformat((now or utc_now()) + timedelta(hours=ttl_hours))


def is_expired(expires_at: str, *, now: datetime | None = None) -> bool:
    if not expires_at:
        return True
    parsed = datetime.fromisoformat(expires_at)
    return (now or utc_now()) >= parsed


def credential_public_payload(record: dict[str, object]) -> dict[str, object]:
    return {
        "user_id": str(record.get("user_id") or ""),
        "has_password": bool(record.get("password_hash")),
        "updated_at": str(record.get("updated_at") or ""),
        "created_at": str(record.get("created_at") or ""),
    }


def session_public_payload(record: dict[str, object]) -> dict[str, object]:
    payload = {
        "session_id": str(record.get("session_id") or ""),
        "user_id": str(record.get("user_id") or ""),
        "expires_at": str(record.get("expires_at") or ""),
        "created_at": str(record.get("created_at") or ""),
    }
    for key in ("session_kind", "delegated_by", "delegated_client_id"):
        value = str(record.get(key) or "")
        if value:
            payload[key] = value
    return payload


def auth_token_public_payload(record: dict[str, object]) -> dict[str, object]:
    return {
        "token_id": str(record.get("token_id") or ""),
        "purpose": str(record.get("purpose") or ""),
        "user_id": str(record.get("user_id") or ""),
        "expires_at": str(record.get("expires_at") or ""),
        "used_at": str(record.get("used_at") or ""),
        "created_at": str(record.get("created_at") or ""),
    }
