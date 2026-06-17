from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable


NaceResearcher = Callable[[str], dict[str, Any]]

NACE_PROFILE_FIELDS = (
    "activity_title",
    "scope_summary",
    "included_goods_services",
    "likely_business_expenses",
    "unlikely_or_personal_items",
    "bank_statement_hints",
    "activity_tags",
    "source_urls",
)


def normalize_nace_code(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_profile(nace_code: str) -> dict[str, Any]:
    return {
        "nace_code": nace_code,
        "activity_title": "",
        "scope_summary": "NACE faaliyet kapsamı için araştırma profili henüz dış kaynakla zenginleştirilmedi.",
        "included_goods_services": [],
        "likely_business_expenses": [],
        "unlikely_or_personal_items": [],
        "bank_statement_hints": [],
        "activity_tags": [],
        "source_urls": ["https://ec.europa.eu/eurostat/web/nace/overview"],
    }


def normalize_nace_research_profile(nace_code: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_code = normalize_nace_code(nace_code)
    source = payload or {}
    profile = _default_profile(normalized_code)
    for field in NACE_PROFILE_FIELDS:
        value = source.get(field, profile[field])
        if field in {
            "included_goods_services",
            "likely_business_expenses",
            "unlikely_or_personal_items",
            "bank_statement_hints",
            "activity_tags",
            "source_urls",
        }:
            profile[field] = [str(item).strip() for item in value or [] if str(item).strip()]
        else:
            profile[field] = str(value or "").strip()
    profile["nace_code"] = normalized_code
    profile["researched_at"] = str(source.get("researched_at") or _timestamp())
    profile["expires_at"] = str(
        source.get("expires_at") or (datetime.now(UTC) + timedelta(days=365)).isoformat(timespec="seconds")
    )
    return profile


def resolve_nace_research_profile(
    *,
    store: Any,
    nace_code: str,
    researcher: NaceResearcher | None = None,
) -> dict[str, Any]:
    normalized_code = normalize_nace_code(nace_code)
    if not normalized_code:
        return normalize_nace_research_profile("", {})
    if hasattr(store, "get_nace_research_profile"):
        cached = store.get_nace_research_profile(normalized_code)
        if cached:
            return normalize_nace_research_profile(normalized_code, cached)
    researched_payload = researcher(normalized_code) if researcher else {}
    profile = normalize_nace_research_profile(normalized_code, researched_payload)
    if hasattr(store, "save_nace_research_profile"):
        return store.save_nace_research_profile(nace_code=normalized_code, profile=profile)
    return profile
