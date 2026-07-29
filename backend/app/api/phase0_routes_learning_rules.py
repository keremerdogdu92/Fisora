from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import SESSION_COOKIE_NAME, get_workflow_store, request_user_id
from app.api.phase0_schemas import LearningRuleLifecyclePayload, LearningRuleNewVersionPayload
from app.persistence.learning_rule_repository import LearningRuleRepository
from app.services.learning_rule_service import LearningRuleService


router = APIRouter()


def _service_and_actor(
    x_fisora_user_id: str | None,
    x_fisora_session: str | None,
    fisora_session: str | None,
) -> tuple[LearningRuleService, str]:
    actor = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    store = get_workflow_store()
    user = store.get_portal_user(actor) if actor and hasattr(store, "get_portal_user") else None
    role = str((user or {}).get("role") or "").strip().lower()
    if role not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "accountant_required"})
    if not hasattr(store, "_connect"):
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": "normalized_learning_rules_required"})
    repository = LearningRuleRepository(
        connect=store._connect,
        tenant_id=store.tenant_id,
        json_value=store._json,
    )
    return LearningRuleService(repository=repository), actor


def _rule_view(rule: dict[str, Any]) -> dict[str, Any]:
    snapshot = rule.get("rule_snapshot") if isinstance(rule.get("rule_snapshot"), dict) else rule
    return {
        "rule_key": str(rule.get("rule_key") or ""),
        "version": int(rule.get("version") or 0),
        "status": str(rule.get("status") or ""),
        "scope_label": str(snapshot.get("client_id") or snapshot.get("scope") or ""),
        "trigger_label": str(snapshot.get("counterparty_tax_id") or snapshot.get("normalized_terms") or ""),
        "meaning_label": str(snapshot.get("meaning_label") or snapshot.get("category") or snapshot.get("semantic_role") or ""),
        "binding_label": str(snapshot.get("account_code") or snapshot.get("corrected_account_code") or ""),
        "source_document_label": str(snapshot.get("source_document_label") or snapshot.get("document_ref") or ""),
        "confirmed_by": str(rule.get("confirmed_by") or rule.get("confirmed_actor_id") or ""),
        "last_matched_at": str(rule.get("last_matched_at") or ""),
        "match_count": int(rule.get("match_count") or 0),
        "correction_count": int(rule.get("correction_count") or 0),
    }


@router.get("/store/learning-rules")
def list_learning_rules(
    client_id: str | None = None,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    service, _ = _service_and_actor(x_fisora_user_id, x_fisora_session, fisora_session)
    return {"items": [_rule_view(rule) for rule in service.list_active(client_id=client_id)]}


def _transition(rule_key: str, payload: LearningRuleLifecyclePayload, action: str, headers: tuple[str | None, str | None, str | None]) -> dict[str, object]:
    service, actor = _service_and_actor(*headers)
    try:
        updated = getattr(service, action)(rule_key=rule_key, expected_version=payload.expected_version, actor=actor)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc
    return _rule_view(updated)


@router.post("/store/learning-rules/{rule_key}/activate")
def activate_learning_rule(rule_key: str, payload: LearningRuleLifecyclePayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    return _transition(rule_key, payload, "activate", (x_fisora_user_id, x_fisora_session, fisora_session))


@router.post("/store/learning-rules/{rule_key}/pause")
def pause_learning_rule(rule_key: str, payload: LearningRuleLifecyclePayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    return _transition(rule_key, payload, "pause", (x_fisora_user_id, x_fisora_session, fisora_session))


@router.post("/store/learning-rules/{rule_key}/archive")
def archive_learning_rule(rule_key: str, payload: LearningRuleLifecyclePayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    return _transition(rule_key, payload, "archive", (x_fisora_user_id, x_fisora_session, fisora_session))


@router.post("/store/learning-rules/{rule_key}/versions")
def create_learning_rule_version(rule_key: str, payload: LearningRuleNewVersionPayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, actor = _service_and_actor(x_fisora_user_id, x_fisora_session, fisora_session)
    snapshot = {**payload.rule_snapshot, "reason": payload.reason}
    try:
        return _rule_view(service.create_version(rule_key=rule_key, expected_version=payload.expected_version, snapshot=snapshot, actor=actor))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc
