from __future__ import annotations

from app.domain.brand_research import normalize_brand_name


def normalize_product_research_key(value: str) -> str:
    return normalize_brand_name(value)[:120]
