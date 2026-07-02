from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Literal


RelevanceStatus = Literal["uygun", "genel_gider", "supheli", "is_alani_disi"]
ExportStatus = Literal["export_ready", "review_required", "blocked", "rejected"]
RelevanceRelation = Literal["core_business", "adjacent_business", "general_overhead", "weak_match", "off_activity", "blocked_or_regulated"]
AccountTreatment = Literal["stock_or_cogs", "expense", "fixed_asset_review", "manual_review", "non_deductible_review"]


@dataclass(frozen=True)
class ActivityProfile:
    primary_activity: str = "unknown"
    display_label: str = "Belirsiz faaliyet"
    activity_tags: tuple[str, ...] = ()
    nace_family: str = ""
    relevance_hints: tuple[str, ...] = ()
    confidence: int = 0
    needs_review: bool = True

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["activity_tags"] = list(self.activity_tags)
        payload["relevance_hints"] = list(self.relevance_hints)
        return payload


GENERAL_EXPENSE_CATEGORIES = {
    "e_fatura_hizmeti",
    "bulut_yazilim_hizmeti",
    "elektrik",
    "internet",
    "kira",
    "kargo",
    "arac_kiralama",
    "guvenlik",
}

HEARING_CENTER_CATEGORIES = {
    "isitme_cihazi",
    "isitme_cihazi_pili",
    "medikal_sarf",
}

PERSONAL_USE_CATEGORIES = {
    "kisisel_bakim_kozmetik",
    "market_kisisel",
    "personal_clothing",
}

CORE_INPUT_CATEGORIES = {
    "gida_alimi",
    "ambalaj",
    "construction_material",
    "subcontractor_service",
    "equipment_rental",
}

FIXED_ASSET_CATEGORIES = {
    "computer_equipment",
    "business_equipment",
}

REGULATED_ITEM_CATEGORIES = {
    "regulated_item",
}

PRODUCT_RULES: tuple[tuple[str, str, int], ...] = (
    ("urban care", "kisisel_bakim_kozmetik", 92),
    ("macbook", "computer_equipment", 94),
    ("laptop", "computer_equipment", 92),
    ("notebook", "computer_equipment", 88),
    ("bilgisayar", "computer_equipment", 86),
    ("demirbas", "business_equipment", 82),
    ("domates", "gida_alimi", 90),
    ("sebze", "gida_alimi", 86),
    ("gida alimi", "gida_alimi", 90),
    ("gida", "gida_alimi", 80),
    ("et alimi", "gida_alimi", 84),
    ("un alimi", "gida_alimi", 78),
    ("ambalaj", "ambalaj", 90),
    ("paket servisi", "ambalaj", 78),
    ("beton", "construction_material", 90),
    ("cimento", "construction_material", 88),
    ("insaat demiri", "construction_material", 90),
    ("tasaron", "subcontractor_service", 86),
    ("ekipman kiralama", "equipment_rental", 84),
    ("rexton", "isitme_cihazi", 91),
    ("phonak", "isitme_cihazi", 91),
    ("oticon", "isitme_cihazi", 91),
    ("widex", "isitme_cihazi", 90),
    ("signia", "isitme_cihazi", 90),
    ("hearing aid", "isitme_cihazi", 88),
    ("isitme cihazi", "isitme_cihazi", 94),
    ("pil", "isitme_cihazi_pili", 72),
    ("battery", "isitme_cihazi_pili", 72),
    ("kalip", "isitme_cihazi_pili", 72),
    ("kalib", "isitme_cihazi_pili", 72),
    ("montaj kit", "isitme_cihazi_pili", 72),
    ("kolaysoft", "e_fatura_hizmeti", 94),
    ("kolay soft", "e_fatura_hizmeti", 94),
    ("qnb efinans", "e_fatura_hizmeti", 94),
    ("efinans", "e_fatura_hizmeti", 90),
    ("aws", "bulut_yazilim_hizmeti", 86),
    ("amazon web services", "bulut_yazilim_hizmeti", 92),
    ("hosting", "bulut_yazilim_hizmeti", 82),
    ("elektrik", "elektrik", 90),
    ("internet", "internet", 88),
    ("arac kiralama", "arac_kiralama", 88),
    ("kira", "kira", 85),
    ("kargo", "kargo", 85),
    ("guvenlik", "guvenlik", 86),
    ("security", "guvenlik", 86),
    ("sampuan", "kisisel_bakim_kozmetik", 94),
    ("shampoo", "kisisel_bakim_kozmetik", 94),
    ("kozmetik", "kisisel_bakim_kozmetik", 90),
    ("slim taper", "personal_clothing", 88),
    ("jean", "personal_clothing", 82),
    ("pantolon", "personal_clothing", 82),
)

ACTIVITY_TAG_CATEGORY_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "hearing_aid": tuple(sorted(HEARING_CENTER_CATEGORIES)),
    "medical_retail": ("medikal_sarf",),
    "food_service": ("ambalaj", "gida_alimi"),
    "retail_trade": ("ambalaj", "gida_alimi"),
    "construction": ("construction_material", "equipment_rental", "subcontractor_service"),
}

NACE_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("41", "42", "43"), "construction"),
    (("47",), "retail_trade"),
    (("56",), "food_service"),
    (("62",), "software_service"),
    (("86",), "healthcare"),
)

ACTIVITY_RULES: tuple[dict[str, object], ...] = (
    {
        "primary_activity": "hearing_aid_sales_service",
        "display_label": "Isitme cihazi satis/servis",
        "tags": ("hearing_aid", "medical_retail", "retail_trade"),
        "nace_prefixes": ("477401",),
        "needles": ("isitme", "hearing aid", "odyoloji"),
        "relevance_hints": ("isitme_cihazi", "isitme_cihazi_pili", "medikal_sarf"),
        "confidence": 90,
    },
    {
        "primary_activity": "software_development",
        "display_label": "Yazilim ve dijital hizmet",
        "tags": ("software_service", "digital_service", "professional_service"),
        "nace_prefixes": ("62",),
        "needles": ("yazilim", "bilgisayar programlama", "software"),
        "relevance_hints": ("bulut_yazilim_hizmeti", "e_fatura_hizmeti"),
        "confidence": 82,
    },
    {
        "primary_activity": "food_service",
        "display_label": "Yiyecek icecek hizmeti",
        "tags": ("food_service",),
        "nace_prefixes": ("56",),
        "needles": ("restoran", "lokanta", "kafe", "yiyecek", "icecek"),
        "relevance_hints": ("gida_alimi", "kira", "elektrik"),
        "confidence": 78,
    },
    {
        "primary_activity": "construction",
        "display_label": "Insaat ve taahhut",
        "tags": ("construction",),
        "nace_prefixes": ("41", "42", "43"),
        "needles": ("insaat", "taahhut", "yapi"),
        "relevance_hints": ("malzeme_alimi", "kira", "kargo"),
        "confidence": 76,
    },
    {
        "primary_activity": "pharmacy",
        "display_label": "Eczane",
        "tags": ("pharmacy", "healthcare", "retail_trade"),
        "nace_prefixes": ("4773",),
        "needles": ("eczane", "farmasotik"),
        "relevance_hints": ("medikal_sarf", "kargo"),
        "confidence": 82,
    },
    {
        "primary_activity": "retail_trade",
        "display_label": "Perakende satis",
        "tags": ("retail_trade",),
        "nace_prefixes": ("47",),
        "needles": ("perakende", "magaza", "satis"),
        "relevance_hints": ("gida_alimi", "ambalaj", "kira", "kargo", "internet"),
        "confidence": 58,
    },
)


@dataclass(frozen=True)
class ClientProfile:
    client_id: str
    title: str
    tax_id: str
    tckn: str = ""
    vkn: str = ""
    identity_type: str = ""
    tax_identifier: str = ""
    legal_name: str = ""
    trade_name: str = ""
    display_title: str = ""
    tax_office: str = ""
    activity_description: str = ""
    nace_code: str = ""
    activity_tags: tuple[str, ...] = field(default_factory=tuple)
    nace_research_profile: dict[str, object] = field(default_factory=dict)
    workplace_addresses: tuple[str, ...] = field(default_factory=tuple)
    has_chart_accounts: bool = False

    @property
    def effective_tax_identifier(self) -> str:
        return self.tax_identifier or self.vkn or self.tckn or self.tax_id

    @property
    def effective_title(self) -> str:
        return self.display_title or self.trade_name or self.legal_name or self.title


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
    relation: RelevanceRelation = "weak_match"
    account_treatment: AccountTreatment = "manual_review"
    requires_accountant_review: bool = True


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
    lowered = (
        lowered.replace("\u0131", "i")
        .replace("\u0130", "i")
        .replace("\u011f", "g")
        .replace("\u011e", "g")
        .replace("\u00fc", "u")
        .replace("\u00dc", "u")
        .replace("\u015f", "s")
        .replace("\u015e", "s")
        .replace("\u00f6", "o")
        .replace("\u00d6", "o")
        .replace("\u00e7", "c")
        .replace("\u00c7", "c")
    )
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    return " ".join(lowered.split())


def normalize_activity_tags(tags: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for tag in tags:
        candidate = re.sub(r"[^a-z0-9_]+", "_", str(tag).strip().lower()).strip("_")
        if candidate:
            normalized.append(candidate)
    return tuple(dict.fromkeys(normalized))


def _nace_digits(nace_code: str) -> str:
    return re.sub(r"\D", "", nace_code or "")


def _nace_family(nace_digits: str) -> str:
    for prefixes, family in NACE_FAMILIES:
        if any(nace_digits.startswith(prefix) for prefix in prefixes):
            return family
    return ""


def _rule_matches(rule: dict[str, object], *, text: str, nace_digits: str) -> bool:
    prefixes = tuple(str(prefix) for prefix in rule.get("nace_prefixes", ()))
    needles = tuple(str(needle) for needle in rule.get("needles", ()))
    return any(nace_digits.startswith(prefix) for prefix in prefixes) or any(needle in text for needle in needles)


def build_activity_profile(*, activity_description: str = "", nace_code: str = "") -> ActivityProfile:
    text = normalize_text(activity_description)
    digits = _nace_digits(nace_code)
    family = _nace_family(digits)
    for rule in ACTIVITY_RULES:
        if not _rule_matches(rule, text=text, nace_digits=digits):
            continue
        return ActivityProfile(
            primary_activity=str(rule["primary_activity"]),
            display_label=str(rule["display_label"]),
            activity_tags=normalize_activity_tags(tuple(str(tag) for tag in rule.get("tags", ()))),
            nace_family=family,
            relevance_hints=tuple(str(item) for item in rule.get("relevance_hints", ())),
            confidence=int(rule.get("confidence", 70)),
            needs_review=False,
        )
    if family:
        return ActivityProfile(
            primary_activity=family,
            display_label=family.replace("_", " ").title(),
            activity_tags=(family,),
            nace_family=family,
            confidence=50,
            needs_review=True,
        )
    return ActivityProfile()


def activity_profile_for_client(profile: ClientProfile) -> ActivityProfile:
    inferred = build_activity_profile(
        activity_description=profile.activity_description,
        nace_code=profile.nace_code,
    )
    explicit_tags = normalize_activity_tags(profile.activity_tags)
    if not explicit_tags:
        return inferred
    return ActivityProfile(
        primary_activity=inferred.primary_activity,
        display_label=inferred.display_label,
        activity_tags=explicit_tags,
        nace_family=inferred.nace_family,
        relevance_hints=inferred.relevance_hints,
        confidence=max(inferred.confidence, 70),
        needs_review=False if inferred.primary_activity != "unknown" else inferred.needs_review,
    )


def account_treatment_for_category(category: str) -> AccountTreatment:
    if category in HEARING_CENTER_CATEGORIES or category in CORE_INPUT_CATEGORIES:
        return "stock_or_cogs"
    if category in GENERAL_EXPENSE_CATEGORIES:
        return "expense"
    if category in FIXED_ASSET_CATEGORIES:
        return "fixed_asset_review"
    if category in PERSONAL_USE_CATEGORIES or category in REGULATED_ITEM_CATEGORIES:
        return "non_deductible_review"
    return "manual_review"


def check_client_onboarding(profile: ClientProfile) -> OnboardingCheck:
    missing: list[str] = []
    if not profile.client_id.strip():
        missing.append("client_id")
    if not profile.effective_title.strip():
        missing.append("title")
    if not profile.effective_tax_identifier.strip():
        missing.append("tax_id")
    if not (profile.activity_description.strip() or profile.nace_code.strip() or profile.activity_tags):
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
    activity_tags = activity_profile_for_client(profile).activity_tags
    return "hearing_aid" in activity_tags or any(needle in text for needle in ("isitme", "hearing", "odyoloji", "medikal"))


def assess_business_relevance(
    raw_line: str,
    profile: ClientProfile,
    *,
    supplier_hint: str = "",
    classification: ProductClassification | None = None,
) -> BusinessRelevance:
    classification = classification or classify_product_line(raw_line, supplier_hint)
    category = classification.category
    evidence = list(classification.evidence)
    activity_profile = activity_profile_for_client(profile)

    if category in GENERAL_EXPENSE_CATEGORIES:
        evidence.append("general_expense")
        return BusinessRelevance(
            status="genel_gider",
            confidence=max(classification.confidence, 78),
            reason="Kalem sektorler arasi genel gider niteliginde gorunuyor.",
            evidence=tuple(evidence),
            classification=classification,
            relation="general_overhead",
            account_treatment="expense",
            requires_accountant_review=False,
        )

    if category in FIXED_ASSET_CATEGORIES:
        evidence.append("fixed_asset_candidate")
        return BusinessRelevance(
            status="supheli",
            confidence=max(classification.confidence, 82),
            reason="Kalem faaliyetle iliskili olabilir ancak demirbas/amortisman kontrolu gerektirir.",
            evidence=tuple(evidence),
            classification=classification,
            relation="adjacent_business",
            account_treatment="fixed_asset_review",
            requires_accountant_review=True,
        )

    for tag in activity_profile.activity_tags:
        allowed_categories = ACTIVITY_TAG_CATEGORY_ALLOWLIST.get(tag, ())
        if category in allowed_categories:
            treatment = account_treatment_for_category(category)
            evidence.append(f"activity_tag:{tag}")
            return BusinessRelevance(
                status="uygun",
                confidence=max(classification.confidence, activity_profile.confidence, 86),
                reason="Kalem faaliyet profili etiketiyle uyumlu gorunuyor.",
                evidence=tuple(evidence),
                classification=classification,
                relation="core_business",
                account_treatment=treatment,
                requires_accountant_review=treatment not in {"stock_or_cogs", "expense"},
            )

    if _is_hearing_center(profile) and category in HEARING_CENTER_CATEGORIES:
        evidence.append("activity_match:hearing_center")
        return BusinessRelevance(
            status="uygun",
            confidence=max(classification.confidence, 88),
            reason="Kalem isitme merkezi faaliyet profiliyle uyumlu gorunuyor.",
            evidence=tuple(evidence),
            classification=classification,
            relation="core_business",
            account_treatment=account_treatment_for_category(category),
            requires_accountant_review=False,
        )

    if category in PERSONAL_USE_CATEGORIES:
        evidence.append("personal_use_category")
        return BusinessRelevance(
            status="is_alani_disi",
            confidence=max(classification.confidence, 86),
            reason="Kalem kisisel kullanim veya faaliyet disi harcama riski tasiyor.",
            evidence=tuple(evidence),
            classification=classification,
            relation="off_activity",
            account_treatment="non_deductible_review",
            requires_accountant_review=True,
        )

    return BusinessRelevance(
        status="supheli",
        confidence=45,
        reason="Kalem faaliyet profiliyle yeterince eslestirilemedi.",
        evidence=tuple(evidence),
        classification=classification,
        relation="weak_match",
        account_treatment="manual_review",
        requires_accountant_review=True,
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
    if relevance.requires_accountant_review:
        return "review_required"
    if relevance.status in {"supheli", "is_alani_disi"}:
        return "review_required"
    return "export_ready"
