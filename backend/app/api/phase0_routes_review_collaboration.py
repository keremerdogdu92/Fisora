from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import SESSION_COOKIE_NAME, get_workflow_store, request_user_id, require_client_access
from app.api.phase0_schemas import (
    JournalEditLeaseAcquirePayload, JournalEditLeaseRenewPayload,
    JournalEditLeaseTakeoverPayload, JournalWorkingDraftPayload,
)
from app.persistence.postgres_workflow_store import taxpayer_uuid
from app.persistence.normalized_accounting_repository import NormalizedRevisionConflict
from app.services.review_collaboration_service import (
    EditLeaseConflict, PostgresReviewCollaborationRepository, ReviewCollaborationService,
)

router = APIRouter()


def _service(payload_client_id: str, headers: tuple[str | None, str | None, str | None]) -> tuple[ReviewCollaborationService, str, str, str]:
    user_id = request_user_id(*headers)
    store = get_workflow_store()
    access = require_client_access(client_id=payload_client_id, user_id=user_id, allowed_roles=("accountant", "admin"))
    if not getattr(store, "normalized_accounting_enabled", False):
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": "normalized_collaboration_required"})
    repo = PostgresReviewCollaborationRepository(connect=store._connect, tenant_id=store.tenant_id, taxpayer_id=taxpayer_uuid(store.tenant_id, payload_client_id))
    return ReviewCollaborationService(repository=repo, tenant_id=str(store.tenant_id), now=lambda: datetime.now(UTC)), user_id, payload_client_id, str(access.get("role") or "accountant")


def _at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"allowed": False, "reason": "invalid_activity_timestamp"}) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _headers(x_user: str | None, x_session: str | None, cookie: str | None) -> tuple[str | None, str | None, str | None]:
    return x_user, x_session, cookie


@router.post("/store/journal/edit-lease/acquire")
def acquire_edit_lease(payload: JournalEditLeaseAcquirePayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, actor, _, role = _service(payload.client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return service.acquire(journal_entry_id=payload.document_ref, actor_id=actor, actor_role=role, expected_revision=payload.expected_revision, user_activity_at=datetime.now(UTC), now=datetime.now(UTC))
    except (EditLeaseConflict, NormalizedRevisionConflict) as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc


@router.post("/store/journal/edit-lease/renew")
def renew_edit_lease(payload: JournalEditLeaseRenewPayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, actor, _, _ = _service(payload.client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return service.renew(journal_entry_id=payload.document_ref, actor_id=actor, user_activity_at=_at(payload.user_activity_at))
    except (EditLeaseConflict, ValueError, NormalizedRevisionConflict) as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc


@router.post("/store/journal/edit-lease/release")
def release_edit_lease(payload: JournalEditLeaseRenewPayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, actor, _, _ = _service(payload.client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        service.release(journal_entry_id=payload.document_ref, actor_id=actor)
    except EditLeaseConflict as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc
    return {"released": True}


@router.post("/store/journal/edit-lease/takeover")
def takeover_edit_lease(payload: JournalEditLeaseTakeoverPayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, actor, _, role = _service(payload.client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return service.takeover(journal_entry_id=payload.document_ref, actor_id=actor, actor_role=role, expected_revision=payload.expected_revision, reason=payload.reason, user_activity_at=_at(payload.user_activity_at))
    except (EditLeaseConflict, ValueError, NormalizedRevisionConflict) as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc


@router.put("/store/journal/working-draft")
def save_working_draft(payload: JournalWorkingDraftPayload, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, actor, _, _ = _service(payload.client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    try:
        return service.save_working_draft(journal_entry_id=payload.document_ref, actor_id=actor, expected_revision=payload.expected_revision, payload={"draft_lines": payload.draft_lines, "reason": payload.reason})
    except (EditLeaseConflict, ValueError, NormalizedRevisionConflict) as exc:
        raise HTTPException(status_code=409, detail={"allowed": False, "reason": str(exc)}) from exc


@router.get("/store/journal/candidates/{client_id}")
def list_journal_candidates(client_id: str, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, _, _, _ = _service(client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    return {"items": service.list_candidates()}


@router.get("/store/journal/candidates/{client_id}/{document_ref}")
def list_document_candidates(client_id: str, document_ref: str, x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"), x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"), fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict[str, object]:
    service, _, _, _ = _service(client_id, _headers(x_fisora_user_id, x_fisora_session, fisora_session))
    return {"items": [item for item in service.list_candidates() if item.get("journal_entry_id") == document_ref]}
