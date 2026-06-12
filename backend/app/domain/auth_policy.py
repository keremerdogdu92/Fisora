from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping, Literal


AuthMode = Literal["mock_header_optional", "mock_header_required", "trusted_header", "session_required"]


@dataclass(frozen=True)
class AuthConfig:
    mode: AuthMode
    user_header_name: str = "X-Fisora-User-Id"

    @property
    def allows_anonymous_access(self) -> bool:
        return self.mode == "mock_header_optional"

    @property
    def requires_portal_user(self) -> bool:
        return not self.allows_anonymous_access

    @property
    def production_ready(self) -> bool:
        return self.mode in {"trusted_header", "session_required"}

    @property
    def accepts_user_header(self) -> bool:
        return self.mode != "session_required"

    @property
    def credential_transport(self) -> str:
        if self.mode == "session_required":
            return "secure_cookie"
        if self.mode == "trusted_header":
            return "trusted_header"
        return "mock_header"


def normalize_auth_mode(value: str) -> AuthMode:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"", "mock", "mock_optional", "mock_header_optional"}:
        return "mock_header_optional"
    if normalized in {"mock_required", "mock_header_required"}:
        return "mock_header_required"
    if normalized in {"trusted", "trusted_header", "proxy_header"}:
        return "trusted_header"
    if normalized in {"session", "session_required", "cookie", "secure_cookie"}:
        return "session_required"
    raise ValueError(
        "unsupported FISORA_AUTH_MODE. supported: mock_header_optional, mock_header_required, trusted_header, session_required"
    )


def build_auth_config(env: Mapping[str, str] | None = None) -> AuthConfig:
    source = env if env is not None else os.environ
    return AuthConfig(
        mode=normalize_auth_mode(source.get("FISORA_AUTH_MODE", "mock_header_optional")),
        user_header_name=source.get("FISORA_AUTH_HEADER", "X-Fisora-User-Id").strip() or "X-Fisora-User-Id",
    )


def resolve_user_id(header_value: str | None, config: AuthConfig | None = None) -> str:
    active = config or build_auth_config()
    if not active.accepts_user_header:
        return ""
    return (header_value or "").strip()


def auth_status_payload(config: AuthConfig | None = None) -> dict[str, object]:
    active = config or build_auth_config()
    notes = {
        "mock_header_optional": "Local tests can omit the user header; not production safe.",
        "mock_header_required": "Controlled local use requires a portal user header; still not production safe.",
        "trusted_header": "Production bootstrap mode; a trusted gateway must strip browser-sent headers and inject the verified user id.",
        "session_required": "Controlled office mode; application sessions are required and browser-sent user headers are ignored.",
    }
    return {
        "auth_mode": active.mode,
        "user_header_name": active.user_header_name,
        "requires_portal_user": active.requires_portal_user,
        "allows_anonymous_access": active.allows_anonymous_access,
        "production_ready": active.production_ready,
        "credential_transport": active.credential_transport,
        "note": notes[active.mode],
    }
