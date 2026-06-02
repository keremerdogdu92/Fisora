from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PORTAL_USERS_CLIENT_ID = "__portal_users__"


@dataclass(frozen=True)
class PortalAccessDecision:
    allowed: bool
    reason: str
    role: str = ""


def build_portal_user_record(
    *,
    user_id: str,
    display_name: str,
    role: str,
    allowed_client_ids: list[str],
) -> dict[str, Any]:
    normalized_role = role.strip().lower() or "client_user"
    if normalized_role not in {"client_user", "accountant", "admin"}:
        raise ValueError(f"unsupported portal role: {role}")
    cleaned_clients = [client_id.strip() for client_id in allowed_client_ids if client_id.strip()]
    return {
        "user_id": user_id.strip(),
        "display_name": display_name.strip() or user_id.strip(),
        "role": normalized_role,
        "allowed_client_ids": cleaned_clients,
    }


def decide_portal_access(
    *,
    portal_user: dict[str, Any] | None,
    client_exists: bool,
    client_id: str,
) -> PortalAccessDecision:
    if not client_exists:
        return PortalAccessDecision(False, "client_not_onboarded")
    if portal_user is None:
        return PortalAccessDecision(False, "portal_user_not_found")
    role = str(portal_user.get("role") or "")
    allowed_clients = {str(value) for value in portal_user.get("allowed_client_ids") or []}
    if "*" in allowed_clients:
        return PortalAccessDecision(True, "wildcard_access", role)
    if client_id in allowed_clients:
        return PortalAccessDecision(True, "assigned_client_access", role)
    return PortalAccessDecision(False, "client_not_assigned_to_user", role)
