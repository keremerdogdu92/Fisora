from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Any, Callable


BrandResearcher = Callable[[str], dict[str, Any]]

KNOWN_BRAND_PROFILES: dict[str, dict[str, Any]] = {
    "blendax": {
        "display_name": "Blendax",
        "brand_summary": "Sampuan ve sac bakim urunleriyle bilinen genel tuketici markasi.",
        "common_product_categories": ["kisisel_bakim_kozmetik", "sampuan"],
        "source_urls": [],
        "confidence": 90,
    },
}


def normalize_brand_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ç", "c")
        .replace("Ç", "c")
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize_brand_research_profile(brand_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_brand_name(brand_name)
    source = payload or {}
    return {
        "brand_name": normalized,
        "display_name": str(source.get("display_name") or brand_name or normalized).strip(),
        "brand_summary": str(source.get("brand_summary") or "").strip(),
        "common_product_categories": [
            str(item).strip() for item in source.get("common_product_categories", []) if str(item).strip()
        ],
        "source_urls": [str(item).strip() for item in source.get("source_urls", []) if str(item).strip()],
        "confidence": int(source.get("confidence") or 0),
        "researched_at": str(source.get("researched_at") or _timestamp()),
        "expires_at": str(
            source.get("expires_at") or (datetime.now(UTC) + timedelta(days=365)).isoformat(timespec="seconds")
        ),
        "model_level_todo": "Model/uzanti uyumlulugu sonraki fazda ayrica cache'lenecek.",
    }


def resolve_brand_research_profile(
    *,
    store: Any,
    brand_name: str,
    researcher: BrandResearcher | None = None,
) -> dict[str, Any]:
    normalized = normalize_brand_name(brand_name)
    if not normalized:
        return normalize_brand_research_profile("", {})
    if hasattr(store, "get_brand_research_profile"):
        cached = store.get_brand_research_profile(normalized)
        if cached:
            return normalize_brand_research_profile(normalized, cached)
    payload = KNOWN_BRAND_PROFILES.get(normalized)
    if payload is None:
        payload = researcher(normalized) if researcher else {}
    profile = normalize_brand_research_profile(normalized, payload)
    if hasattr(store, "save_brand_research_profile"):
        return store.save_brand_research_profile(brand_name=normalized, profile=profile)
    return profile
