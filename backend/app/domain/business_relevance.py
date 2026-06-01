from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


RelevanceStatus = Literal["uygun", "genel_gider", "supheli", "is_alani_disi"]
ExportStatus = Literal["export_ready", "review_required", "blocked", "rejected"]


GENERAL_EXPENSE_CATEGORIES = {
    "e_fatura_hizmeti",
    "bulut_yazilim_hizmeti",
    "elektrik",
    "internet",
    "kira",
    "kargo",
}

HEARING_CENTER_CATEGORIES = {
    "isitme_cihazi",
    "isitme_cihazi_pili",
    "medikal_sarf",
}

PERSONAL_USE_CATEGORIES = {
    "kisisel_bakim_kozmetik",
    "market_kisisel",
}

PRODUCT_RULES: tuple[tuple[str, str, int], ...] = (
    ("urban care", "kisisel_bakim_kozmetik", 92),
    ("rexton", "isitme_cihazi", 91),
    ("phonak", "isitme_cihazi", 91),
    ("oticon", "isitme_cihazi", 91),
    ("widex", "isitme_cihazi", 90),
    ("signia", "isitme_cihazi", 90),
    ("hearing aid", "isitme_cihazi", 88),
    ("isitme cihazi", "isitme_cihazi", 94),
    ("pil", "isitme_cihazi_pili", 72),
    ("battery", "isitme_cihazi_pili", 72),
    ("kolaysoft", "e_fatura_hizmeti", 94),
    ("kolay soft", "e_fatura_hizmeti", 94),
    ("qnb efinans", "e_fatura_hizmeti", 94),
    ("efinans", "e_fatura_hizmeti", 90),
    ("aws", "bulut_yazilim_hizmeti", 86),
    ("amazon web services", "bulut_yazilim_hizmeti", 92),
    ("hosting", "bulut_yazilim_hizmeti", 82),
    ("elektrik", "elektrik", 90),
    ("internet", "internet", 88),
    ("kira", "kira", 85),
    ("kargo", "kargo", 85),
    ("sampuan", "kisisel_bakim_kozmetik", 94),
    ("shampoo", "kisisel_bakim_kozmetik", 94),
    ("kozmetik", "kisisel_bakim_kozmetik", 90),
)


@dataclass(frozen=True)
class ClientProfile:
    client_id: str
    title: str
    tax_id: str
    activity_description: str = ""
    nace_code: str = ""
    workplace_addresses: tuple[str, ...] = field(default_factory=tuple)
    has_chart_accounts: bool = False


@dataclass(frozen=True)
class OnboardingCheck:
    is_ready: bool
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class ProductClassification:
    raw_line: str
    category: str
    confidence: int
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class BusinessRelevance:
    status: RelevanceStatus
    confidence: int
    reason: str
    evidence: tuple[str, ...]
    classification: ProductClassification


def normalize_text(value: str) -> str:
    replacements = {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
    lowered = value.lower()
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    return " ".join(lowered.split())


def check_client_onboarding(profile: ClientProfile) -> OnboardingCheck:
    missing: list[str] = []
    if not profile.client_id.strip():
        missing.append("client_id")
    if not profile.title.strip():
        missing.append("title")
    if not profile.tax_id.strip():
        missing.append("tax_id")
    if not (profile.activity_description.strip() or profile.nace_code.strip()):
        missing.append("activity_or_nace")
    if not profile.workplace_addresses:
        missing.append("workplace_addresses")
    if not profile.has_chart_accounts:
        missing.append("chart_accounts")
    return OnboardingCheck(is_ready=not missing, missing_fields=tuple(missing))


def classify_product_line(raw_line: str, supplier_hint: str = "") -> ProductClassification:
    haystack = normalize_text(f"{raw_line} {supplier_hint}")
    for needle, category, confidence in PRODUCT_RULES:
        if needle in haystack:
            return ProductClassification(
                raw_line=raw_line,
                category=category,
                confidence=confidence,
                evidence=(f"matched:{needle}",),
            )
    return ProductClassification(
        raw_line=raw_line,
        category="bilinmeyen",
        confidence=35,
        evidence=("no_static_match",),
    )


def _is_hearing_center(profile: ClientProfile) -> bool:
    text = normalize_text(f"{profile.activity_description} {profile.nace_code}")
    return any(needle in text for needle in ("isitme", "hearing", "odyoloji", "medikal"))


def assess_business_relevance(
    raw_line: str,
    profile: ClientProfile,
    *,
    supplier_hint: str = "",
) -> BusinessRelevance:
    classification = classify_product_line(raw_line, supplier_hint)
    category = classification.category
    evidence = list(classification.evidence)

    if category in GENERAL_EXPENSE_CATEGORIES:
        evidence.append("general_expense")
        return BusinessRelevance(
            status="genel_gider",
            confidence=max(classification.confidence, 78),
            reason="Kalem sektorler arasi genel gider niteliginde gorunuyor.",
            evidence=tuple(evidence),
            classification=classification,
        )

    if _is_hearing_center(profile) and category in HEARING_CENTER_CATEGORIES:
        evidence.append("activity_match:hearing_center")
        return BusinessRelevance(
            status="uygun",
            confidence=max(classification.confidence, 88),
            reason="Kalem isitme merkezi faaliyet profiliyle uyumlu gorunuyor.",
            evidence=tuple(evidence),
            classification=classification,
        )

    if category in PERSONAL_USE_CATEGORIES:
        evidence.append("personal_use_category")
        return BusinessRelevance(
            status="is_alani_disi",
            confidence=max(classification.confidence, 86),
            reason="Kalem kisisel kullanim veya faaliyet disi harcama riski tasiyor.",
            evidence=tuple(evidence),
            classification=classification,
        )

    return BusinessRelevance(
        status="supheli",
        confidence=45,
        reason="Kalem faaliyet profiliyle yeterince eslestirilemedi.",
        evidence=tuple(evidence),
        classification=classification,
    )


def decide_export_status(
    *,
    is_balanced: bool,
    risk_flags: tuple[str, ...],
    relevance: BusinessRelevance,
) -> ExportStatus:
    if not is_balanced:
        return "blocked"
    if risk_flags:
        return "review_required"
    if relevance.status in {"supheli", "is_alani_disi"}:
        return "review_required"
    return "export_ready"
