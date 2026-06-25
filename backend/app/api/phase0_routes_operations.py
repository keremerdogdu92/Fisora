from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    default_backup_path,
    default_document_storage_path,
    default_export_path,
    get_workflow_store,
    record_operation_event,
    request_user_id,
    require_client_access,
)
from app.domain.ai_capacity import (
    ai_capacity_payload,
    normalize_openrouter_key_payload,
    normalize_tavily_usage_payload,
)
from app.api.phase0_schemas import OperationEventPayload
from app.domain.operation_monitoring import summarize_operation_health
from app.domain.production_readiness import production_readiness_payload


router = APIRouter()
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
TAVILY_USAGE_URL = "https://api.tavily.com/usage"
CAPACITY_SNAPSHOT_TTL = timedelta(minutes=10)


@router.get("/store/system/readiness")
def store_system_readiness() -> dict[str, object]:
    return production_readiness_payload(
        document_storage_path=default_document_storage_path(),
        export_path=default_export_path(),
        backup_path=default_backup_path(),
    )


def _require_accountant_or_admin(
    *,
    x_fisora_user_id: str | None,
    x_fisora_session: str | None,
    fisora_session: str | None,
) -> dict[str, object]:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail={"allowed": False, "reason": "portal_user_required"})
    store = get_workflow_store()
    user = store.get_portal_user(user_id) if hasattr(store, "get_portal_user") else None
    if not user:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "portal_user_not_found"})
    role = str(user.get("role") or "")
    if role not in {"accountant", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"allowed": False, "reason": "role_not_allowed", "allowed_roles": ["accountant", "admin"]},
        )
    return {"allowed": True, "role": role, "user_id": user_id}


def _snapshot_is_fresh(snapshot: dict[str, object] | None) -> bool:
    if not snapshot:
        return False
    checked_at = str(snapshot.get("last_checked_at") or "").strip()
    if not checked_at:
        return False
    try:
        parsed = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return datetime.now(UTC) - parsed <= CAPACITY_SNAPSHOT_TTL


def _cached_snapshot(snapshot: dict[str, object] | None) -> dict[str, object] | None:
    return {**snapshot, "status": "cached"} if snapshot else None


def _refresh_openrouter_snapshot(
    store: object,
    existing: dict[str, object] | None,
) -> dict[str, object] | None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key.startswith("sk-or-"):
        return existing
    if _snapshot_is_fresh(existing):
        return existing
    try:
        response = httpx.get(
            OPENROUTER_KEY_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=2.0,
        )
        response.raise_for_status()
    except Exception:
        return _cached_snapshot(existing)
    snapshot = normalize_openrouter_key_payload(response.json())
    if hasattr(store, "record_ai_capacity_snapshot"):
        store.record_ai_capacity_snapshot(provider="openrouter", snapshot=snapshot)
    return snapshot


def _refresh_tavily_snapshot(
    store: object,
    existing: dict[str, object] | None,
) -> dict[str, object] | None:
    research_enabled = os.environ.get("FISORA_RESEARCH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    provider = os.environ.get("FISORA_RESEARCH_PROVIDER", "openai").strip().lower()
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not research_enabled or provider != "tavily" or not api_key.startswith("tvly-"):
        return existing
    if _snapshot_is_fresh(existing):
        return existing
    try:
        response = httpx.get(
            TAVILY_USAGE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=2.0,
        )
        response.raise_for_status()
    except Exception:
        return _cached_snapshot(existing)
    snapshot = normalize_tavily_usage_payload(response.json())
    if hasattr(store, "record_ai_capacity_snapshot"):
        store.record_ai_capacity_snapshot(provider="tavily", snapshot=snapshot)
    return snapshot


@router.get("/store/ai-capacity")
def store_ai_capacity(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_accountant_or_admin(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    store = get_workflow_store()
    snapshots = store.latest_ai_capacity_snapshots() if hasattr(store, "latest_ai_capacity_snapshots") else {}
    openrouter_snapshot = _refresh_openrouter_snapshot(store, snapshots.get("openrouter"))
    if openrouter_snapshot:
        snapshots = {**snapshots, "openrouter": openrouter_snapshot}
    tavily_snapshot = _refresh_tavily_snapshot(store, snapshots.get("tavily"))
    if tavily_snapshot:
        snapshots = {**snapshots, "tavily": tavily_snapshot}
    return ai_capacity_payload(env=os.environ, provider_snapshots=snapshots)


@router.post("/store/operation-log")
def store_operation_log(
    payload: OperationEventPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    if payload.client_id != "__system__":
        require_client_access(
            client_id=payload.client_id,
            user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
            allowed_roles=("accountant", "admin"),
        )
    return record_operation_event(
        store=get_workflow_store(),
        client_id=payload.client_id,
        event_type=payload.event_type,
        status=payload.status,
        message=payload.message,
        metadata=payload.metadata,
    )


@router.get("/store/operation-health/{client_id}")
def store_operation_health(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    require_client_access(
        client_id=client_id,
        user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    events = store.list_operation_events(client_id=client_id)
    jobs = store.list_processing_jobs(client_id=client_id)
    return {
        "client_id": client_id,
        "summary": summarize_operation_health(events=events, processing_jobs=jobs),
        "events": events,
        "processing_jobs": jobs,
    }
