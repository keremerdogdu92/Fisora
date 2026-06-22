from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.phase0_context import SESSION_COOKIE_NAME, get_workflow_store, request_user_id
from app.domain.research_harness import ResearchHarness, build_research_runtime_from_env, normalize_research_profile


router = APIRouter()


class ResearchRefreshPayload(BaseModel):
    kind: str = "brand"
    key: str
    query: str = ""
    supplier_hint: str = ""
    activity_context: str = ""
    force: bool = False


class ResearchOverridePayload(BaseModel):
    kind: str = "brand"
    key: str
    summary_tr: str = ""
    category_tags: list[str] = Field(default_factory=list)
    activity_tags: list[str] = Field(default_factory=list)
    confidence: int = 70


def _require_research_user(
    *,
    x_fisora_user_id: str | None,
    x_fisora_session: str | None,
    fisora_session: str | None,
) -> str:
    store = get_workflow_store()
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    user = store.get_portal_user(user_id) if user_id and hasattr(store, "get_portal_user") else None
    if not user or str(user.get("role") or "") not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail="research workspace requires accountant access")
    return user_id


@router.get("/store/research/profiles")
def store_research_profiles(
    kind: str = "",
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    return {"profiles": get_workflow_store().list_research_profiles(kind=kind)}


@router.get("/store/research/profile/{kind}/{key}")
def store_research_profile(
    kind: str,
    key: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    profile = get_workflow_store().get_research_profile(kind=kind, key=key)
    if not profile:
        raise HTTPException(status_code=404, detail="research profile not found")
    return {"profile": profile}


@router.post("/store/research/override")
def store_research_override(
    payload: ResearchOverridePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    store = get_workflow_store()
    profile = normalize_research_profile(
        kind=payload.kind,
        key=payload.key,
        payload={
            "display_name": payload.key,
            "summary_tr": payload.summary_tr,
            "common_product_categories": payload.category_tags,
            "activity_tags": payload.activity_tags,
            "confidence": payload.confidence,
            "override": True,
            "source_policy": "accountant_override",
        },
    )
    profile["override_actor"] = actor
    if payload.kind == "nace":
        stored = store.save_nace_research_profile(nace_code=payload.key, profile=profile)
    else:
        stored = store.save_brand_research_profile(brand_name=payload.key, profile=profile)
    return {"profile": stored}


@router.post("/store/research/refresh")
def store_research_refresh(
    payload: ResearchRefreshPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    store = get_workflow_store()
    existing = store.get_research_profile(kind=payload.kind, key=payload.key)
    if existing and not payload.force:
        return {"profile": existing, "refreshed": False, "reason": "cache_hit"}
    runtime = build_research_runtime_from_env(os.environ)
    if runtime and payload.kind == "brand":
        profile = ResearchHarness(
            store=store,
            provider=runtime.get("provider"),  # type: ignore[arg-type]
            policy=runtime.get("policy"),  # type: ignore[arg-type]
        ).research_brand(
            raw_line=payload.query or payload.key,
            supplier_hint=payload.supplier_hint,
            activity_context=payload.activity_context,
            bypass_cache=payload.force,
        )
        return {"profile": profile, "refreshed": True, "reason": "research_runtime"}
    profile = normalize_research_profile(
        kind=payload.kind,
        key=payload.key,
        payload={
            **(existing or {}),
            "display_name": payload.key,
            "summary_tr": (existing or {}).get("summary_tr") or (existing or {}).get("brand_summary") or "",
            "confidence": (existing or {}).get("confidence") or 0,
        },
    )
    if payload.kind == "nace":
        stored = store.save_nace_research_profile(nace_code=payload.key, profile=profile)
    else:
        stored = store.save_brand_research_profile(brand_name=payload.key, profile=profile)
    return {"profile": stored, "refreshed": False, "reason": "research_runtime_not_invoked"}


GOLDEN_RESEARCH_CASES = (
    {"case_id": "brand-rexton", "kind": "brand", "key": "Rexton", "expected": "isitme_cihazi"},
    {"case_id": "brand-phonak", "kind": "brand", "key": "Phonak", "expected": "isitme_cihazi"},
    {"case_id": "brand-urban-care", "kind": "brand", "key": "Urban Care", "expected": "kisisel_bakim_kozmetik"},
    {"case_id": "brand-blendax", "kind": "brand", "key": "Blendax", "expected": "kisisel_bakim_kozmetik"},
    {"case_id": "general-internet", "kind": "brand", "key": "internet", "expected": "internet"},
)


@router.post("/store/research/benchmark/run")
def store_research_benchmark_run(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    store = get_workflow_store()
    evaluated = []
    matched_count = 0
    for case in GOLDEN_RESEARCH_CASES:
        profile = store.get_research_profile(kind=case["kind"], key=case["key"]) or {}
        categories = set(profile.get("common_product_categories") or profile.get("activity_tags") or [])
        matched = case["expected"] in categories
        matched_count += 1 if matched else 0
        evaluated.append({**case, "matched": matched, "confidence": int(profile.get("confidence") or 0)})
    accuracy = int(round((matched_count / len(evaluated)) * 100)) if evaluated else 0
    run = store.save_research_benchmark_run(
        {
            "run_type": "benchmark",
            "case_count": len(evaluated),
            "matched_count": matched_count,
            "accuracy": accuracy,
            "model": "research-cache",
            "cases": evaluated,
        }
    )
    return {"run": run}


@router.get("/store/research/benchmark/runs")
def store_research_benchmark_runs(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    return {"runs": get_workflow_store().list_research_benchmark_runs()}
