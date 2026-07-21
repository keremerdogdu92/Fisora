from __future__ import annotations

from app.domain.brand_research import normalize_brand_name


RESEARCH_AUTHORITY_KEYS = frozenset(
    {
        "product_category",
        "account_treatment",
        "authoritative_product_category",
        "classification_override",
        "selected_account_code",
        "selected_expense_account",
        "selected_revenue_account",
        "selected_supplier_account",
    }
)


def normalize_product_research_key(value: str) -> str:
    return normalize_brand_name(value)[:120]


def non_authoritative_research_payload(payload: dict[str, object] | None) -> dict[str, object]:
    """Return cached/provider research without fields that can select accounting output."""

    source = dict(payload or {})
    existing_display = (
        dict(source.get("non_authoritative_display") or {})
        if isinstance(source.get("non_authoritative_display"), dict)
        else {}
    )
    product_category = source.get("product_category") or existing_display.get("product_category") or ""
    account_treatment = source.get("account_treatment") or existing_display.get("account_treatment") or ""
    cleaned = _strip_research_authority(source)
    if isinstance(cleaned, dict):
        cleaned["non_authoritative_display"] = {
            "product_category": str(product_category or ""),
            "account_treatment": str(account_treatment or ""),
        }
        return cleaned
    return {}


def _strip_research_authority(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _strip_research_authority(item)
            for key, item in value.items()
            if str(key) not in RESEARCH_AUTHORITY_KEYS and str(key) != "non_authoritative_display"
        }
    if isinstance(value, list):
        return [_strip_research_authority(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_research_authority(item) for item in value)
    return value


def research_cache_provenance(*, hit: bool, key: str, kind: str) -> dict[str, object]:
    return {
        "hit": hit is True,
        "key": normalize_product_research_key(key) if kind == "brand" else str(key or "").strip(),
        "kind": str(kind or ""),
        "authority": "evidence_only",
    }
