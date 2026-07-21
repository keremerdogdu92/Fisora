from __future__ import annotations

import csv
import os
from pathlib import Path

from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.phase0_context import SESSION_COOKIE_NAME, get_workflow_store, request_user_id
from app.domain.research_harness import ResearchHarness, build_research_runtime_from_env, normalize_research_profile
from app.persistence.workflow_store import ResearchProfileConflict


router = APIRouter()
REPO_ROOT = Path(__file__).resolve().parents[3]


class ResearchRefreshPayload(BaseModel):
    kind: str = "brand"
    key: str
    profile_id: str = ""
    client_id: str = ""
    query: str = ""
    supplier_hint: str = ""
    activity_context: str = ""
    force: bool = False


class ResearchOverridePayload(BaseModel):
    kind: str = "brand"
    key: str
    profile_id: str = ""
    summary_tr: str = ""
    category_tags: list[str] = Field(default_factory=list)
    activity_tags: list[str] = Field(default_factory=list)
    account_treatment: str = ""
    confidence: int = 70
    expected_revision: int | None = None


def _require_research_user(
    *,
    x_fisora_user_id: str | None,
    x_fisora_session: str | None,
    fisora_session: str | None,
) -> dict[str, object]:
    store = get_workflow_store()
    user_id = request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    user = store.get_portal_user(user_id) if user_id and hasattr(store, "get_portal_user") else None
    if not user or str(user.get("role") or "") not in {"accountant", "admin"}:
        raise HTTPException(status_code=403, detail="research workspace requires accountant access")
    return dict(user)


def _allowed_research_client_ids(user: dict[str, object]) -> set[str] | None:
    if str(user.get("role") or "") == "admin":
        return None
    allowed = {str(item) for item in user.get("allowed_client_ids") or []}
    return None if "*" in allowed else allowed


@router.get("/store/research/profiles")
def store_research_profiles(
    kind: str = "",
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    profiles = get_workflow_store().list_research_profiles(
        kind=kind,
        allowed_client_ids=_allowed_research_client_ids(user),
    )
    return {"profiles": profiles}


@router.get("/store/research/profile/{kind}/{key}")
def store_research_profile(
    kind: str,
    key: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    profile = get_workflow_store().get_research_profile(
        kind=kind,
        key=key,
        allowed_client_ids=_allowed_research_client_ids(user),
    )
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
    user = _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    store = get_workflow_store()
    if not payload.profile_id or payload.expected_revision is None:
        raise HTTPException(status_code=428, detail="profile_id and expected_revision are required")
    storage_key = payload.profile_id
    existing = store.get_research_profile(
        kind=payload.kind,
        key=storage_key,
        allowed_client_ids=_allowed_research_client_ids(user),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="research profile not found")
    actor = str(user.get("user_id") or "")
    owner_id = str(
        (existing or {}).get("owner_client_id")
        or (existing or {}).get("client_id")
        or (existing or {}).get("tenant_id")
        or ""
    )
    profile = normalize_research_profile(
        kind=payload.kind,
        key=str(existing.get("display_key") or payload.key),
        payload={
            **existing,
            "display_name": payload.key,
            "summary_tr": payload.summary_tr,
            "common_product_categories": payload.category_tags,
            "activity_tags": payload.activity_tags,
            "account_treatment": payload.account_treatment,
            "confidence": payload.confidence,
            "research_confidence": int((existing or {}).get("research_confidence") or 0),
            "accounting_impact_confidence": int((existing or {}).get("accounting_impact_confidence") or 0),
            "override": True,
            "override_actor": actor,
            "override_provenance": {"source": "accountant", "actor_id": actor},
            "profile_id": storage_key,
            "display_key": payload.key,
            "client_id": owner_id,
            "tenant_id": owner_id,
            "owner_client_id": owner_id,
            "scope_type": str((existing or {}).get("scope_type") or ("client_private" if owner_id else "legacy_unowned")),
            "accountant_override": {
                "active": True,
                "actor_user_id": actor,
                "summary_tr": payload.summary_tr,
                "category_tags": payload.category_tags,
            },
            "source_policy": "accountant_override",
        },
    )
    profile["override_actor"] = actor
    try:
        if payload.kind == "nace":
            stored = store.save_nace_research_profile(
                nace_code=storage_key,
                profile=profile,
                expected_revision=payload.expected_revision,
            )
        else:
            stored = store.save_brand_research_profile(
                brand_name=storage_key,
                profile=profile,
                expected_revision=payload.expected_revision,
            )
    except ResearchProfileConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "research_profile_conflict",
                "expected_revision": exc.expected_revision,
                "actual_revision": exc.actual_revision,
            },
        ) from exc
    if hasattr(store, "record_operation_event"):
        store.record_operation_event(
            client_id=owner_id or "__research_office__",
            event={
                "event_type": "research_profile_override",
                "actor_user_id": actor,
                "profile_id": storage_key,
                "kind": payload.kind,
                "previous_revision": payload.expected_revision,
                "revision": stored.get("revision"),
                "created_at": stored.get("updated_at"),
            },
        )
    return {"profile": stored}


@router.post("/store/research/refresh")
def store_research_refresh(
    payload: ResearchRefreshPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_research_user(
        x_fisora_user_id=x_fisora_user_id,
        x_fisora_session=x_fisora_session,
        fisora_session=fisora_session,
    )
    store = get_workflow_store()
    storage_key = payload.profile_id or payload.key
    existing = store.get_research_profile(
        kind=payload.kind,
        key=storage_key,
        allowed_client_ids=_allowed_research_client_ids(user),
    )
    if payload.profile_id and not existing:
        raise HTTPException(status_code=404, detail="research profile not found")
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
            cache_scope=str((existing or {}).get("owner_client_id") or (existing or {}).get("client_id") or ""),
            cache_key_override=storage_key,
            bypass_cache=payload.force,
        )
        return {"profile": profile, "refreshed": True, "reason": "research_runtime"}
    if runtime and payload.kind == "nace":
        profile = ResearchHarness(
            store=store,
            provider=runtime.get("provider"),  # type: ignore[arg-type]
            policy=runtime.get("policy"),  # type: ignore[arg-type]
        ).research_nace(
            nace_code=payload.key,
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
        stored = store.save_nace_research_profile(nace_code=storage_key, profile=profile)
    else:
        stored = store.save_brand_research_profile(brand_name=storage_key, profile=profile)
    return {"profile": stored, "refreshed": False, "reason": "research_runtime_not_invoked"}


GOLDEN_RESEARCH_CASES = (
    {
        "case_id": "brand-rexton",
        "kind": "brand",
        "key": "Rexton",
        "expected_brand": "Rexton",
        "expected_category": "isitme_cihazi",
        "expected_account_treatment": "stock_or_cogs",
        "expected_review_required": False,
    },
    {
        "case_id": "brand-phonak",
        "kind": "brand",
        "key": "Phonak",
        "expected_brand": "Phonak",
        "expected_category": "isitme_cihazi",
        "expected_account_treatment": "stock_or_cogs",
        "expected_review_required": False,
    },
    {
        "case_id": "brand-urban-care",
        "kind": "brand",
        "key": "Urban Care",
        "expected_brand": "Urban Care",
        "expected_category": "kisisel_bakim_kozmetik",
        "expected_account_treatment": "non_deductible_review",
        "expected_review_required": True,
    },
    {
        "case_id": "brand-blendax",
        "kind": "brand",
        "key": "Blendax",
        "expected_brand": "Blendax",
        "expected_category": "kisisel_bakim_kozmetik",
        "expected_account_treatment": "non_deductible_review",
        "expected_review_required": True,
    },
    {
        "case_id": "general-internet",
        "kind": "brand",
        "key": "internet",
        "expected_brand": "internet",
        "expected_category": "internet",
        "expected_account_treatment": "expense",
        "expected_review_required": False,
    },
)


def _real_pilot_research_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    analysis_root = REPO_ROOT / "private_samples" / "real_pilot"
    for csv_path in sorted(analysis_root.glob("firma-*/analysis/matching_simulation.csv")):
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for index, row in enumerate(csv.DictReader(handle), start=1):
                    key = str(row.get("product_line_hint") or row.get("provider_hint") or "").strip()
                    category = str(row.get("product_category") or "").strip()
                    treatment = str(row.get("business_relevance_account_treatment") or "").strip()
                    if not key or not category or category in {"bilinmeyen", "not_assessed"}:
                        continue
                    cases.append(
                        {
                            "case_id": f"{csv_path.parent.parent.name}-{index}",
                            "kind": "brand",
                            "key": key,
                            "document": str(row.get("file_name") or ""),
                            "supplier_hint": str(row.get("provider_hint") or ""),
                            "expected_brand": key.split(" ")[0],
                            "expected_category": category,
                            "expected_account_treatment": treatment,
                            "expected_review_required": str(row.get("export_status") or "") != "export_ready",
                        }
                    )
        except OSError:
            continue
    return cases


def _benchmark_cases() -> list[dict[str, object]]:
    real_cases = _real_pilot_research_cases()
    return real_cases or [dict(case) for case in GOLDEN_RESEARCH_CASES]


def _percent(part: int, total: int) -> int:
    return int(round((part / total) * 100)) if total else 0


def _non_authoritative_display(profile: dict[str, object]) -> dict[str, object]:
    value = profile.get("non_authoritative_display")
    return dict(value) if isinstance(value, dict) else {}


def _profile_review_required(profile: dict[str, object], *, threshold: int = 70) -> bool:
    research_confidence = int(profile.get("research_confidence") or profile.get("confidence") or 0)
    impact_confidence = int(profile.get("accounting_impact_confidence") or 0)
    treatment = str(_non_authoritative_display(profile).get("account_treatment") or "")
    return (
        research_confidence < threshold
        or impact_confidence < threshold
        or treatment in {"fixed_asset_review", "non_deductible_review", "manual_review"}
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
    brand_matches = 0
    category_matches = 0
    accounting_matches = 0
    review_matches = 0
    cases = _benchmark_cases()
    for case in cases:
        profile = store.get_research_profile(kind=case["kind"], key=case["key"]) or {}
        categories = set(profile.get("common_product_categories") or profile.get("activity_tags") or [])
        display_name = str(profile.get("display_name") or profile.get("key") or "").lower()
        expected_brand = str(case.get("expected_brand") or case["key"]).lower()
        brand_matched = bool(profile) and expected_brand.split(" ")[0] in display_name
        category_matched = str(case.get("expected_category") or "") in categories
        accounting_matched = str(case.get("expected_account_treatment") or "") == str(
            _non_authoritative_display(profile).get("account_treatment") or ""
        )
        review_matched = bool(case.get("expected_review_required")) == _profile_review_required(profile)
        brand_matches += 1 if brand_matched else 0
        category_matches += 1 if category_matched else 0
        accounting_matches += 1 if accounting_matched else 0
        review_matches += 1 if review_matched else 0
        evaluated.append(
            {
                **case,
                "brand_matched": brand_matched,
                "category_matched": category_matched,
                "accounting_impact_matched": accounting_matched,
                "review_gate_matched": review_matched,
                "confidence": int(profile.get("research_confidence") or profile.get("confidence") or 0),
            }
        )
    metrics = {
        "brand_accuracy": _percent(brand_matches, len(evaluated)),
        "category_accuracy": _percent(category_matches, len(evaluated)),
        "accounting_impact_accuracy": _percent(accounting_matches, len(evaluated)),
        "review_gate_accuracy": _percent(review_matches, len(evaluated)),
    }
    run = store.save_research_benchmark_run(
        {
            "run_type": "benchmark",
            "case_count": len(evaluated),
            "matched_count": category_matches,
            "accuracy": metrics["category_accuracy"],
            "metrics": metrics,
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
