from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, HTTPException

from app.api.phase0_context import (
    SESSION_COOKIE_NAME,
    get_protected_corpus_service,
    get_workflow_store,
    require_client_access,
    request_user_id,
)
from app.api.phase0_schemas import (
    ProtectedCorpusCreatePayload,
    ProtectedCorpusEnrollPayload,
    ProtectedCorpusFreezePayload,
)
from app.services.protected_corpus_service import ProtectedCorpusError


router = APIRouter()


def _accountant_user_id(
    x_fisora_user_id: str | None,
    x_fisora_session: str | None,
    fisora_session: str | None,
) -> str:
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if not user_id:
        raise HTTPException(status_code=401, detail={"allowed": False, "reason": "user_required"})
    store = get_workflow_store()
    portal_user = store.get_portal_user(user_id) if hasattr(store, "get_portal_user") else None
    role = str((portal_user or {}).get("role") or "").strip().lower()
    if role not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail={"allowed": False, "reason": "accountant_required"})
    return user_id


def _corpus_error(exc: ProtectedCorpusError) -> HTTPException:
    reason = str(exc)
    status = 404 if reason in {"corpus_not_found", "source_document_not_found"} else 409
    return HTTPException(status_code=status, detail={"allowed": False, "reason": reason})


def _safe_corpus_payload(payload: dict[str, object]) -> dict[str, object]:
    safe = dict(payload)
    safe.pop("protected_storage_path", None)
    if isinstance(safe.get("items"), list):
        safe["items"] = [
            {key: value for key, value in item.items() if key != "protected_storage_path"}
            for item in safe["items"]
            if isinstance(item, dict)
        ]
    return safe


@router.post("/store/corpora")
def create_protected_corpus(
    payload: ProtectedCorpusCreatePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _accountant_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if payload.target_purchase_count + payload.target_sales_count != 50:
        raise HTTPException(status_code=400, detail={"allowed": False, "reason": "pilot_corpus_requires_50_documents"})
    try:
        return _safe_corpus_payload(get_protected_corpus_service().create_corpus(
            corpus_key=payload.corpus_key,
            version=payload.version,
            target_purchase_count=payload.target_purchase_count,
            target_sales_count=payload.target_sales_count,
            actor=actor,
        ))
    except ProtectedCorpusError as exc:
        raise _corpus_error(exc) from exc


@router.get("/store/corpora/{corpus_id}")
def get_protected_corpus(
    corpus_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _accountant_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    try:
        return _safe_corpus_payload(get_protected_corpus_service().get_corpus(corpus_id))
    except ProtectedCorpusError as exc:
        raise _corpus_error(exc) from exc


@router.post("/store/corpora/{corpus_id}/items")
def enroll_protected_corpus_item(
    corpus_id: str,
    payload: ProtectedCorpusEnrollPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _accountant_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    require_client_access(
        client_id=payload.client_id,
        user_id=actor,
        allowed_roles=("accountant", "admin"),
    )
    try:
        return _safe_corpus_payload(get_protected_corpus_service().enroll_document(
            corpus_id=corpus_id,
            client_id=payload.client_id,
            document_ref=payload.document_ref,
            direction=payload.direction,
            actor=actor,
        ))
    except ProtectedCorpusError as exc:
        raise _corpus_error(exc) from exc


@router.post("/store/corpora/{corpus_id}/freeze")
def freeze_protected_corpus(
    corpus_id: str,
    payload: ProtectedCorpusFreezePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _accountant_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if payload.confirmation.strip() != "CORPUSU_DONDUR":
        raise HTTPException(status_code=400, detail={"allowed": False, "reason": "confirmation_required"})
    try:
        return get_protected_corpus_service().freeze_corpus(corpus_id)
    except ProtectedCorpusError as exc:
        raise _corpus_error(exc) from exc
