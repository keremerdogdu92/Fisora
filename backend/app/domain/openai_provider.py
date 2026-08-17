from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import inspect
import json
import re
from threading import Lock
from time import monotonic, perf_counter_ns, sleep
from typing import Any, Callable, Mapping, Sequence

import httpx

from app.domain.ai_capacity import normalize_cerebras_rate_limit_headers, normalize_groq_rate_limit_headers, utc_now
from app.domain.ai_classification import AiClassificationRequest
from app.domain.canonical_invoices import CanonicalExtractionRequest
from app.domain.review_rule_interpretation import REVIEW_RULE_INTERPRETATION_SCHEMA
from app.domain.statement_ai_suggestions import StatementAiSuggestionRequest


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
GROQ_RESPONSES_URL = "https://api.groq.com/openai/v1/responses"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
CEREBRAS_CHAT_COMPLETIONS_URL = "https://api.cerebras.ai/v1/chat/completions"
NVIDIA_CHAT_COMPLETIONS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
CLOUDFLARE_CHAT_COMPLETIONS_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
)
SAMBANOVA_CHAT_COMPLETIONS_URL = "https://api.sambanova.ai/v1/chat/completions"
XKIRO_CHAT_COMPLETIONS_URL = "https://api.xkiro.com/v1/chat/completions"
GEMINI_GENERATE_CONTENT_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_COMPARISON_MODEL = "gpt-5.4-nano"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GROQ_COMPARISON_MODEL = "openai/gpt-oss-120b"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"
DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-120b"
DEFAULT_CLOUDFLARE_MODEL = "@cf/openai/gpt-oss-120b"
DEFAULT_SAMBANOVA_MODEL = "gpt-oss-120b"
DEFAULT_XKIRO_MODEL = "anthropic/claude-opus-4.8"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
PRODUCT_CLASSIFICATION_PROMPT_VERSION = "invoice-semantic-decision-v1"


@dataclass(frozen=True)
class GeminiAttemptEnvelope:
    request_body: bytes
    response_body: bytes
    provider: str
    model_alias: str
    resolved_model: str
    http_status: int | None
    started_at: datetime
    finished_at: datetime
    elapsed_ms: int
    token_usage: dict[str, int]
    status: str
    error_metadata: dict[str, Any]


class GeminiStructuredResult(dict[str, Any]):
    """A normal mapping result with its persistable provider attempt attached."""

    def __init__(self, payload: Mapping[str, Any], *, attempt: GeminiAttemptEnvelope) -> None:
        super().__init__(payload)
        self.attempt = attempt


class GeminiProviderAttemptError(ValueError):
    """Gemini transport/parse failure that retains the exact failed attempt."""

    def __init__(self, message: str, *, attempt: GeminiAttemptEnvelope) -> None:
        super().__init__(message)
        self.attempt = attempt


class GeminiRequestGovernor:
    """Process-local start-rate governor shared by one reusable Gemini provider."""

    def __init__(
        self,
        requests_per_minute: int = 0,
        *,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._interval_seconds = (
            60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        )
        self._clock = clock
        self._sleeper = sleeper
        self._lock = Lock()
        self._next_start = 0.0

    def acquire(self) -> None:
        if self._interval_seconds <= 0:
            return
        with self._lock:
            now = self._clock()
            scheduled = max(now, self._next_start)
            self._next_start = scheduled + self._interval_seconds
        wait_seconds = scheduled - now
        if wait_seconds > 0:
            self._sleeper(wait_seconds)


_PARTY_FACT_FIELDS = frozenset(
    {"title", "legal_name", "tax_id", "tax_id_type", "tax_office", "address", "vkn", "tckn", "evidence"}
)
_HEADER_FACT_FIELDS = frozenset(
    {
        "invoice_no", "ettn", "issue_date", "invoice_type", "scenario", "currency_code",
        "document_direction", "original_invoice_no", "original_invoice_date", "evidence",
    }
)
_LINE_FACT_FIELDS = frozenset(
    {
        "canonical_line_id", "source_position", "external_line_id", "description", "quantity",
        "unit_code", "unit_price", "unit_price_basis", "taxable_amount", "vat_rate", "tax_amount",
        "gross_amount", "tax_scheme_code", "tax_category_code", "exemption_reason_code", "vat_group_id",
        "observed_quantity", "observed_unit_code", "observed_unit_price", "observed_unit_price_basis",
        "observed_taxable_amount", "observed_vat_rate", "observed_tax_amount", "observed_gross_amount",
        "evidence",
    }
)
_VAT_FACT_FIELDS = frozenset(
    {
        "rate", "taxable_amount", "tax_amount", "source", "source_position", "tax_scheme_code",
        "tax_category_code", "exemption_reason_code", "vat_group_id", "contributing_line_ids",
        "observed_rate", "observed_taxable_amount", "observed_tax_amount", "evidence",
    }
)
_TAX_FACT_FIELDS = frozenset(
    {
        "component_type", "source_label", "source_code", "rate", "taxable_amount", "tax_amount",
        "source_position", "canonical_tax_kind", "normalization_confidence", "accounting_treatment", "evidence",
    }
)
_MONETARY_FACT_FIELDS = frozenset(
    {
        "source_label", "source_amount", "source_position", "canonical_component_kind",
        "normalization_confidence", "accounting_treatment", "evidence",
    }
)
_NAMED_TOTAL_FACT_FIELDS = frozenset(
    {"source_label", "amount", "source_position", "proposed_role", "evidence"}
)
_TOTAL_FACT_FIELDS = frozenset(
    {
        "goods_services_total", "allowance_total", "vat_total", "special_tax_total", "tax_exclusive_total",
        "tax_inclusive_total", "payable_total", "line_net_total", "line_gross_total", "currency_code",
        "observed_goods_services_total", "observed_allowance_total", "observed_vat_total",
        "observed_special_tax_total", "observed_tax_inclusive_total", "observed_payable_total", "evidence",
    }
)
_ACCOUNT_CANDIDATE_FIELDS = frozenset(
    {
        "candidate_id", "code", "name", "reason", "semantic_roles", "vat_rate", "is_detail_account",
        "is_active", "group", "family", "label", "direction_role", "groups", "candidate_count", "examples",
        "origin_round", "vat_rates",
        "roles", "tax_id", "tax_office",
    }
)
_COUNTERPARTY_CANDIDATE_FIELDS = frozenset(
    {
        "candidate_id", "code", "name", "counterparty_type", "source_group", "candidate_type",
        "normalized_name_tokens", "evidence", "origin_round",
    }
)
_COUNTERPARTY_FACT_FIELDS = frozenset(
    {
        "title", "tax_id", "tax_id_type", "tax_office", "address", "direction", "direction_confidence",
        "direction_evidence", "counterparty_title", "counterparty_tax_id", "issuer_title", "issuer_tax_id",
        "recipient_title", "recipient_tax_id", "provider_hint", "provider_id", "service_profile",
        "provider_match_kind", "provider_match_reason", "provider_directory_version", "normalized_title_tokens",
        "raw_title_candidates", "evidence",
    }
)
_CANDIDATE_STRATEGY_FIELDS = frozenset(
    {"mode", "stage", "account_candidate_count", "counterparty_candidate_count", "selected_families"}
)
_RESEARCH_EVIDENCE_FIELDS = frozenset(
    {
        "url", "title", "source_type", "summary_tr", "accepted", "question", "canonical_line_ids", "claims",
        "conflicts", "source_url", "source_domain", "source_kind", "evidence_summary", "confidence", "quality",
        "raw_summary",
    }
)
_PRIOR_ATTEMPT_FIELDS = frozenset(
    {
        "attempt_id", "stage", "canonical_line_ids", "prompt_version", "provider", "model",
        "candidate_account_codes", "candidate_counterparty_codes", "validation_errors", "accepted",
        "superseded_by_attempt_id",
    }
)
_VALIDATED_RESPONSE_FIELDS = frozenset(
    {
        "category", "product_category", "confidence", "reason", "evidence", "suggested_account_code",
        "suggested_counterparty_code", "selected_account_code", "selected_counterparty_code",
        "selected_account_families", "risk_flags", "account_reason", "product_identity", "needs_research",
        "research_query", "display_name", "account_treatment", "research_confidence",
        "accounting_impact_confidence", "question", "canonical_line_ids", "conflicts", "evidence_gaps", "authority",
    }
)


_OMIT_TRANSPORT_VALUE = object()


def _transport_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [
            item
            for item in value
            if isinstance(item, (str, int, float, bool)) or item is None
        ]
    return _OMIT_TRANSPORT_VALUE


def _allow_fields(value: object, allowed: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {}
    for raw_field, raw_value in value.items():
        field = str(raw_field)
        if field not in allowed:
            continue
        transport_value = _transport_value(raw_value)
        if transport_value is not _OMIT_TRANSPORT_VALUE:
            safe[field] = transport_value
    return safe


def _allow_items(value: object, allowed: frozenset[str]) -> list[dict[str, object]]:
    return [
        _allow_fields(item, allowed)
        for item in (value if isinstance(value, (list, tuple)) else ())
        if isinstance(item, Mapping)
    ]


def _extraction_transport_payload(payload: Mapping[str, object]) -> dict[str, object]:
    raw = payload.get("deterministic_payload")
    raw = raw if isinstance(raw, Mapping) else {}
    deterministic = _allow_fields(
        raw,
        _HEADER_FACT_FIELDS
        | frozenset(
            {
                "line_count", "validation_status", "validation_reasons", "vat_split_status", "extraction_notes"
            }
        ),
    )
    for field, allowed in (
        ("header", _HEADER_FACT_FIELDS),
        ("supplier_party", _PARTY_FACT_FIELDS),
        ("customer_party", _PARTY_FACT_FIELDS),
        ("totals", _TOTAL_FACT_FIELDS),
        ("observed_totals", _TOTAL_FACT_FIELDS),
    ):
        if field in raw:
            deterministic[field] = _allow_fields(raw.get(field), allowed)
    for field, allowed in (
        ("line_items", _LINE_FACT_FIELDS),
        ("vat_summary", _VAT_FACT_FIELDS),
        ("observed_vat_summary", _VAT_FACT_FIELDS),
        ("tax_components", _TAX_FACT_FIELDS),
        ("observed_tax_components", _TAX_FACT_FIELDS),
        ("monetary_components", _MONETARY_FACT_FIELDS),
        ("observed_monetary_components", _MONETARY_FACT_FIELDS),
        ("observed_named_totals", _NAMED_TOTAL_FACT_FIELDS),
    ):
        if field in raw:
            deterministic[field] = _allow_items(raw.get(field), allowed)
    return {
        "mode": str(payload.get("mode") or "repair"),
        "deterministic_payload": deterministic,
        "client_identity": _allow_fields(payload.get("client_identity"), _PARTY_FACT_FIELDS),
    }


def _safe_prior_attempt(value: object) -> dict[str, object]:
    safe = _allow_fields(value, _PRIOR_ATTEMPT_FIELDS)
    if isinstance(value, Mapping) and "validated_response" in value:
        validated = _allow_fields(value.get("validated_response"), _VALIDATED_RESPONSE_FIELDS)
        raw_validated = value.get("validated_response")
        if isinstance(raw_validated, Mapping):
            if "line_decisions" in raw_validated:
                validated["line_decisions"] = _allow_items(raw_validated.get("line_decisions"), _VALIDATED_RESPONSE_FIELDS | _LINE_FACT_FIELDS)
            if "research_evidence" in raw_validated:
                validated["research_evidence"] = _allow_items(raw_validated.get("research_evidence"), _RESEARCH_EVIDENCE_FIELDS)
        safe["validated_response"] = validated
    return safe


def _accounting_transport_payload(payload: Mapping[str, object]) -> dict[str, object]:
    top_level_fields = frozenset(
        {
            "raw_line", "supplier_hint", "client_activity", "nace_code", "nace_research_summary", "activity_tags",
            "accounting_direction", "direction", "direction_confidence", "direction_evidence", "direction_uncertainty",
            "stage", "service_profile", "account_candidates", "counterparty_candidates", "allowed_categories",
            "allowed_account_families", "semantic_stage", "validation_errors",
        }
    )
    safe = _allow_fields(payload, top_level_fields)
    for field, allowed in (
        ("candidate_strategy", _CANDIDATE_STRATEGY_FIELDS),
        ("vat_group", _VAT_FACT_FIELDS | frozenset({"line_ids", "line_descriptions"})),
        ("counterparty", _COUNTERPARTY_FACT_FIELDS),
        ("invoice_counterparty", _COUNTERPARTY_FACT_FIELDS),
    ):
        if field in payload:
            safe[field] = _allow_fields(payload.get(field), allowed)
    for field, allowed in (
        ("canonical_lines", _LINE_FACT_FIELDS),
        ("account_candidates", _ACCOUNT_CANDIDATE_FIELDS),
        ("account_candidate_details", _ACCOUNT_CANDIDATE_FIELDS),
        ("counterparty_candidate_details", _COUNTERPARTY_CANDIDATE_FIELDS),
        ("account_family_candidates", _ACCOUNT_CANDIDATE_FIELDS),
        ("research_evidence", _RESEARCH_EVIDENCE_FIELDS),
    ):
        raw_value = payload.get(field)
        if isinstance(raw_value, (list, tuple)) and all(
            isinstance(item, Mapping) for item in raw_value
        ):
            safe[field] = _allow_items(raw_value, allowed)
    if "prior_semantic_attempt" in payload:
        safe["prior_semantic_attempt"] = _safe_prior_attempt(payload.get("prior_semantic_attempt"))
    return safe


_V2_FACT_IDENTITY_FIELDS = frozenset(
    {
        "component_id",
        "occurrence_index",
        "identity_ref",
        "decision_ref",
        "represented_by_refs",
        "warnings",
    }
)
_V2_HEADER_FACT_FIELDS = frozenset(
    {
        "invoice_no",
        "ettn",
        "issue_date",
        "invoice_type",
        "scenario",
        "currency_code",
        "document_direction",
        "original_invoice_no",
        "original_invoice_date",
    }
)
_V2_PARTY_FACT_FIELDS = frozenset(
    {
        "title",
        "legal_name",
        "tax_id",
        "tax_id_type",
        "tax_office",
        "address",
        "vkn",
        "tckn",
    }
)
_V2_LINE_FACT_FIELDS = frozenset(
    {
        "canonical_line_id",
        "description",
        "quantity",
        "unit_code",
        "unit_price",
        "unit_price_basis",
        "taxable_amount",
        "vat_rate",
        "tax_amount",
        "gross_amount",
        "tax_scheme_code",
        "tax_category_code",
        "exemption_reason_code",
        "vat_group_id",
        "posting_amount",
        "allocation_adjustment",
    }
)
_V2_VAT_FACT_FIELDS = frozenset(
    {
        "rate",
        "taxable_amount",
        "tax_amount",
        "tax_scheme_code",
        "tax_category_code",
        "exemption_reason_code",
        "vat_group_id",
        "contributing_line_ids",
    }
)
_V2_TAX_FACT_FIELDS = frozenset(
    {
        "component_type",
        "source_label",
        "source_code",
        "rate",
        "taxable_amount",
        "tax_amount",
        "canonical_tax_kind",
        "normalization_confidence",
        "accounting_treatment",
    }
)
_V2_MONETARY_FACT_FIELDS = frozenset(
    {
        "source_label",
        "source_amount",
        "canonical_component_kind",
        "normalization_confidence",
        "accounting_treatment",
    }
)
_V2_TOTAL_FACT_FIELDS = frozenset(
    {
        "goods_services_total",
        "allowance_total",
        "vat_total",
        "special_tax_total",
        "tax_exclusive_total",
        "tax_inclusive_total",
        "payable_total",
        "line_net_total",
        "line_gross_total",
        "currency_code",
    }
)
_V2_TAX_POSTING_FIELDS = frozenset(
    {
        "economic_effect",
        "posting_side",
        "included_in_tax_total",
        "included_in_payable",
        "payable_membership",
        "posting_requirement",
        "reconciled_effect",
    }
)
_V2_MONETARY_POSTING_FIELDS = frozenset(
    {
        "signed_effect",
        "posting_side",
        "included_in_line_net",
        "included_in_tax_total",
        "included_in_payable",
        "payable_membership",
        "posting_requirement",
        "reconciled_effect",
    }
)
_V2_CLIENT_CONTEXT_FIELDS = frozenset(
    {"activity_description", "nace_code", "activity_tags"}
)


def _v2_projection_transport_value(raw_line: object) -> str:
    if not isinstance(raw_line, str):
        raise ValueError("accounting_selection_v2 raw_line must be JSON text")
    try:
        raw = json.loads(raw_line)
    except (TypeError, ValueError) as exc:
        raise ValueError("accounting_selection_v2 raw_line must be valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("accounting_selection_v2 raw_line must contain a JSON object")
    safe: dict[str, object] = {}
    direction = _transport_value(raw.get("document_direction"))
    if direction is not _OMIT_TRANSPORT_VALUE:
        safe["document_direction"] = direction
    for field, allowed in (
        ("header", _V2_HEADER_FACT_FIELDS),
        ("supplier_party", _V2_PARTY_FACT_FIELDS),
        ("customer_party", _V2_PARTY_FACT_FIELDS),
        ("totals", _V2_TOTAL_FACT_FIELDS),
        ("client_context", _V2_CLIENT_CONTEXT_FIELDS),
    ):
        if field in raw:
            safe[field] = _allow_fields(raw.get(field), allowed)
    for field, allowed in (
        ("line_items", _V2_LINE_FACT_FIELDS | _V2_FACT_IDENTITY_FIELDS),
        ("vat_summary", _V2_VAT_FACT_FIELDS | _V2_FACT_IDENTITY_FIELDS),
        (
            "tax_components",
            _V2_TAX_FACT_FIELDS
            | _V2_FACT_IDENTITY_FIELDS
            | _V2_TAX_POSTING_FIELDS,
        ),
        (
            "monetary_components",
            _V2_MONETARY_FACT_FIELDS
            | _V2_FACT_IDENTITY_FIELDS
            | _V2_MONETARY_POSTING_FIELDS,
        ),
    ):
        if field in raw:
            safe[field] = _allow_items(raw.get(field), allowed)
    for field in ("warnings", "projection_warnings"):
        if field in raw:
            value = _transport_value(raw.get(field))
            if value is not _OMIT_TRANSPORT_VALUE:
                safe[field] = value
    return json.dumps(safe, ensure_ascii=False, separators=(",", ":"))


def _accounting_v2_transport_payload(payload: Mapping[str, object]) -> dict[str, object]:
    safe = _accounting_transport_payload(payload)
    safe["raw_line"] = _v2_projection_transport_value(payload.get("raw_line"))
    return safe


def _accounting_v2_cache_ready_parts(
    *,
    schema_name: str,
    user_payload: Mapping[str, object],
    schema: Mapping[str, object],
) -> list[dict[str, object]]:
    stable_projection = {
        key: value
        for key, value in user_payload.items()
        if key not in {"candidate_strategy", "account_candidates"}
    }
    stable_catalog = {
        "candidate_strategy": user_payload.get("candidate_strategy", {}),
        "account_candidates": user_payload.get("account_candidates", []),
    }
    required_refs = ["counterparty"]
    properties = schema.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    decisions = properties.get("decisions")
    decisions = decisions if isinstance(decisions, Mapping) else {}
    items = decisions.get("items")
    items = items if isinstance(items, Mapping) else {}
    item_properties = items.get("properties")
    item_properties = item_properties if isinstance(item_properties, Mapping) else {}
    decision_ref = item_properties.get("decision_ref")
    decision_ref = decision_ref if isinstance(decision_ref, Mapping) else {}
    raw_refs = decision_ref.get("enum")
    if isinstance(raw_refs, Sequence) and not isinstance(raw_refs, (str, bytes)):
        required_refs.extend(str(value) for value in raw_refs if str(value))
    round_contract = {
        "schema_name": schema_name,
        "required_decision_refs": list(dict.fromkeys(required_refs)),
        "response_rule": "Return only one valid JSON object matching responseJsonSchema.",
    }

    def part(marker: str, value: Mapping[str, object]) -> dict[str, object]:
        return {
            "text": marker
            + "\n"
            + json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        }

    return [
        part("ACCOUNTING_V2_STABLE_PROJECTION", stable_projection),
        part("ACCOUNTING_V2_STABLE_CANDIDATE_CATALOG", stable_catalog),
        part("ACCOUNTING_V2_ROUND_DECISION_CONTRACT", round_contract),
    ]


def _provider_user_payload(
    payload: Mapping[str, Any],
    *,
    exclude_instructions: bool = False,
) -> dict[str, Any]:
    """Keep provider-channel metadata out of the document payload."""
    excluded = {"output_schema"}
    if exclude_instructions:
        excluded.add("instructions")
    return {key: value for key, value in payload.items() if key not in excluded}


def classification_instructions_for(request: AiClassificationRequest) -> str:
    semantic_stage = str(request.context.semantic_stage or "initial_account_decision").strip().lower()
    if semantic_stage == "research_synthesis":
        return (
            "Canonical satir ve mevcut mukellef baglamini esas al. Arastirma sonuclarini yalniz kaynakli ek kanit "
            "olarak degerlendir. Sayfa teslimat, menu veya reklam ifadelerini urun/hizmet kimligi sanma. Her "
            "canonical_line_id icin yalniz verilen gercek hesap adaylarindan en uygun hesabi sec ve celisen kaniti acikla."
        )
    if semantic_stage == "account_correction":
        return (
            "Onceki semantik karar korunmustur ancak secilen hesap mekanik olarak kullanilamiyor. Verilen dogrulama "
            "hatasini ve guncel gercek hesap adaylarini kullanarak ayni canonical_line_id icin yeni hesap sec. Genel "
            "hesaba sirf kullanilabilir oldugu icin gecme; ekonomik anlami koru."
        )
    if semantic_stage == "treatment_clarification":
        return (
            "This is one targeted clarification for the required decision reference. Return a corrected full decision "
            "for that reference, including a valid selected_treatment when the non-zero tax or monetary fact creates "
            "a separate posting. Keep the selected account when it remains appropriate, or select only from the sent "
            "real tenant candidates. If those candidates are insufficient, set request_more_candidates with bounded "
            "search terms while still returning the best provisional decision. Do not invent accounts, facts, amounts, "
            "or decision references."
        )
    stage = str(request.context.candidate_strategy.stage or "").strip().lower()
    if stage == "accounting_selection_v2":
        return (
            "This is accounting_selection_v2. Return a complete accounting proposal for the counterparty and every "
            "required decision reference: line:<id>, vat:<id>, tax:<id> for each non-VAT tax or withholding fact, "
            "and monetary:<id> for each accounting-relevant monetary fact. Select only sent real tenant candidates. "
            "Report candidate sufficiency explicitly and set request_more_candidates when the sent pool is insufficient. "
            "When requesting more candidates, still return a full provisional proposal covering the counterparty and "
            "every required reference; a later round may select an earlier sent candidate. The maximum rounds are "
            "controlled externally. A special-tax or withholding decision may request broader real accounts. Do not "
            "invent account or counterparty codes, do not change amounts or canonical facts, and do not auto-create a "
            "new counterparty; propose_new is only a reviewable suggestion. Line and VAT decisions select only an "
            "account; selected_treatment is non-operative for them and must be empty. For an exactly zero VAT, tax, or "
            "monetary fact use no_separate_posting. For non-VAT tax choose selected_treatment from deductible_tax, "
            "expense_or_cost, payable_withholding, represented_in_line, or no_separate_posting. For monetary facts "
            "choose increase_payable, reduce_payable, represented, excluded, or no_separate_posting. "
            "Use represented only with explicit evidence that another canonical fact carries the amount, and use "
            "excluded only with explicit exclusion evidence."
        )
    if stage == "accounting_selection":
        return (
            "Belge olgularini degistirmeden tam muhasebe teklifi don: karsi taraf hesabi, her canonical satir, "
            "her KDV grubu ve her ozel vergi bileseni icin secim ve gerekce ver. Yalniz gonderilen gercek tenant "
            "adaylarini kullan; hesap kodu uydurma. Aday listesinin yeterli olup olmadigina karar ver. Yetersizse "
            "request_more_candidates iste ve o ana kadarki tam provisional teklifi koru; daha sonraki turda onceki "
            "turlarda gonderilen adaya geri donebilirsin. Yeni cari onerisi, satir/KDV/ozel vergi secimleriyle birlikte "
            "bulunabilir ve otomatik cari olusturma talimati degildir."
        )
    if stage == "family_select":
        return (
            "Fatura satirinin ekonomik anlamini, belge yonunu ve mukellef faaliyetini degerlendir. "
            "Yalniz verilen gercek hesap ailelerinden uygun olanlari sec. "
            "Kaniti yetersiz ve hesap secimini degistirecek belirsizlikte research iste."
        )
    if stage == "counterparty_resolve":
        return (
            "Faturadaki karsi tarafi yalniz verilen gercek cari adaylariyla eslestir. "
            "VKN/TCKN, unvan ve dogrulanmis baglari birlikte kullan. "
            "Uygun cari yoksa selected_counterparty_code alanini bos birak, needs_research=true don ve yeni cari "
            "ihtiyacini belirt; cari kodu uydurma."
        )
    if stage == "vat_group_account":
        return (
            "Tek bir canonical KDV grubunun tum satirlarini birlikte degerlendir. Yalniz verilen gercek ve "
            "yon-filtreli net hesap adaylarindan bir hesap sec. Farkli satir anlatimi veya dusuk guven grubu "
            "kendiliginden bolmez; yalniz muhtemel istisna satir kimliklerini inceleme kaniti olarak belirt. "
            "Canonical kimlikleri, grup uyeligini, tutarlari veya KDV degerlerini degistirme."
        )
    if stage == "invoice_account":
        return (
            "Dogrulanmis utility hizmet profilini, canonical fatura satirlarini ve mukellefin gercek hesap "
            "adaylarini birlikte degerlendir. Faturanin ortak hizmet gideri hesabini yalniz verilen adaylardan "
            "bir kez sec. KDV, OIV ve diger vergi bilesenlerinin hesaplarini uydurma; tutarlari veya canonical "
            "kimlikleri degistirme. Gercek bir satir farkli hesap gerektirebilir gorunuyorsa yalniz o satirin "
            "canonical_line_id degerini possible_exception_line_ids alaninda belirt."
        )
    return (
        "Her canonical fatura satiri icin mukellefin gercek hesap planindaki en uygun gercek hesabi sec. "
        "Satir kaniti, belge yonu, faaliyet/NACE, dogrulanmis kurallar ve verilen adaylari birlikte degerlendir. "
        "invoice_counterparty.service_profile doluysa, bu dogrulanmis saglayici hizmet profilidir; uygun hesap "
        "adayini secmende guclu kanittir ama hesap kodu veya KDV kuralini kendi basina yaratmaz. "
        "Verilmeyen hesap kodu uretme; her canonical_line_id icin tam karar ve kisa gerekce don. "
        "Canonical tutar veya KDV degerlerini degistirme; gerekirse research iste."
    )


def canonical_extraction_instructions_for(request: CanonicalExtractionRequest) -> str:
    if str(request.mode or "repair").strip().lower() == "discovery":
        return (
            "Yalniz verilen PDF belge iceriginde acikca gorulen fatura alanlarini ve tum fatura satirlarini gozlemle. "
            "Belgede yazmayan degeri bos birak; parasal hesaplama veya muhasebe karari yapma. "
            "Vergi ve parasal bilesenlerde yalniz gorunen etiket, kod, oran, matrah, tutar, konum ve kaniti don; "
            "bir bilesenin ara toplamlara veya odenecek toplama dahil olup olmadigini tahmin etme. "
            "Belgede gorunen her adlandirilmis toplami, genel toplam ile odenecek tutari birbirine karistirmadan, "
            "etiketi, tutari, sayfa/konumu ve kanitiyla observed_named_totals icinde ayri ayri don. "
            "Her satirin kesin source_position degerini ver; canonical_line_id ve external_line_id alanlarini bos birak. "
            "Urun veya hizmet anlamini satici unvanindan turetme."
        )
    return (
        "PDF belge kanitindan canonical JSON line_items alanlarini tamamla. "
        "Her canonical_line_id icin tam bir sonuc don; satir ekleme, silme, birlestirme veya kimlik degistirme. "
        "Bir deger belgede acikca yazmiyorsa bos string don. Parasal hesaplama yapma veya muhasebe karari verme. "
        "Canonical tutar veya KDV degerlerini birbirine uydurma."
    )


class OpenAiAccountingProvider:
    """OpenAI Responses API adapter for schema-validated accounting suggestions."""

    provider_name = "openai"
    product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION
    product_classification_instructions = (
        "Gercek hesap plani adaylarindan kanitli bir muhasebe taslagi hazirla. "
        "candidate_strategy.stage=line_batch ise her canonical_line_id icin tam bir kez line_decision don."
    )
    canonical_extraction_instructions = "PDF belge alanlarini yalniz kaynak kanitindan gozlemle; hesaplama yapma."
    statement_suggestion_instructions = (
        "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
        "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
        "Export izni verme; mustavir onayi gerektigini koru."
    )
    review_rule_interpretation_instructions = (
        "Muhasebe mustavirinin karar notunu kisa, denetlenebilir bir kural adayina cevir. "
        "Sadece verilen belge, cari, hesap ve aday kural alanlarini kullan. "
        "Yeni hesap kodu veya cari kod uydurma. Not belirsizse status=needs_clarification don. "
        "Cikti mustavire gosterilecek; teknik olmayan Turkce kullan. "
        "Kural aktiflesse bile ilk uygulamalarda mustavir kontrolu ve KDV/fis dengesi korundugunu belirt."
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        responses_url: str = OPENAI_RESPONSES_URL,
        provider_name: str = "openai",
        key_name: str = "OPENAI_API_KEY",
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError(f"{key_name} is required when FISORA_AI_PROVIDER={provider_name}")
        self.api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_OPENAI_MODEL
        self.responses_url = responses_url
        self.provider_name = provider_name
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = classification_instructions_for(request)
        self.last_product_classification_instructions = instructions
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = canonical_extraction_instructions_for(request)
        return self._post_structured_json(
            schema_name="fisora_invoice_canonical_extraction",
            instructions=instructions,
            user_payload=_provider_user_payload(payload, exclude_instructions=True),
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        payload = dict(request)
        return self._post_structured_json(
            schema_name="fisora_review_rule_interpretation",
            instructions=self.review_rule_interpretation_instructions,
            user_payload=_provider_user_payload(payload),
            schema=REVIEW_RULE_INTERPRETATION_SCHEMA,
        )

    def _post_structured_json(
        self,
        *,
        schema_name: str,
        instructions: str,
        user_payload: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        response = self.http_client.post(
            self.responses_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
            timeout=self.timeout_seconds,
        )
        self._capture_capacity_snapshot(response)
        response.raise_for_status()
        return _extract_json_response(response.json())

    def _capture_capacity_snapshot(self, response: Any) -> None:
        if self.provider_name == "groq":
            self.last_capacity_snapshot = normalize_groq_rate_limit_headers(dict(getattr(response, "headers", {}) or {}))


class GroqAccountingProvider(OpenAiAccountingProvider):
    """Groq OpenAI-compatible Responses API adapter for free-tier pre-demo tests."""

    provider_name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_GROQ_MODEL,
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model.strip() or DEFAULT_GROQ_MODEL,
            responses_url=GROQ_RESPONSES_URL,
            provider_name="groq",
            key_name="GROQ_API_KEY",
            http_client=http_client,
            timeout_seconds=timeout_seconds,
        )


class ChatCompletionsAccountingProvider:
    """OpenAI-compatible chat-completions adapter for fallback providers."""

    provider_name = "chat_completions"
    product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION
    product_classification_instructions = OpenAiAccountingProvider.product_classification_instructions
    canonical_extraction_instructions = OpenAiAccountingProvider.canonical_extraction_instructions
    statement_suggestion_instructions = (
        "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
        "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
        "Export izni verme; mustavir onayi gerektigini koru."
    )
    review_rule_interpretation_instructions = OpenAiAccountingProvider.review_rule_interpretation_instructions

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        chat_completions_url: str,
        provider_name: str,
        key_name: str,
        extra_headers: Mapping[str, str] | None = None,
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
        max_tokens: int | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError(f"{key_name} is required when FISORA_AI_PROVIDER={provider_name}")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.chat_completions_url = chat_completions_url
        self.provider_name = provider_name
        self.extra_headers = {key: value for key, value in (extra_headers or {}).items() if value.strip()}
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = classification_instructions_for(request)
        self.last_product_classification_instructions = instructions
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = canonical_extraction_instructions_for(request)
        return self._post_structured_json(
            schema_name="fisora_invoice_canonical_extraction",
            instructions=instructions,
            user_payload=_provider_user_payload(payload, exclude_instructions=True),
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        payload = dict(request)
        return self._post_structured_json(
            schema_name="fisora_review_rule_interpretation",
            instructions=self.review_rule_interpretation_instructions,
            user_payload=_provider_user_payload(payload),
            schema=REVIEW_RULE_INTERPRETATION_SCHEMA,
        )

    def _post_structured_json(
        self,
        *,
        schema_name: str,
        instructions: str,
        user_payload: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        request_payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": (
                        "Yalnizca gecerli JSON obje don. "
                        f"Schema adi: {schema_name}. "
                        f"JSON schema: {json.dumps(schema, ensure_ascii=False)}. "
                        f"Girdi: {json.dumps(user_payload, ensure_ascii=False)}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "top_p": 1,
            "stream": False,
        }
        if self.max_tokens is not None:
            request_payload["max_tokens"] = self.max_tokens
        response = self.http_client.post(
            self.chat_completions_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                **self.extra_headers,
            },
            json=request_payload,
            timeout=self.timeout_seconds,
        )
        self._capture_capacity_snapshot(response)
        response.raise_for_status()
        return _extract_chat_completion_json_response(response.json())

    def _capture_capacity_snapshot(self, response: Any) -> None:
        if self.provider_name == "groq":
            self.last_capacity_snapshot = normalize_groq_rate_limit_headers(dict(getattr(response, "headers", {}) or {}))
        if self.provider_name == "cerebras":
            self.last_capacity_snapshot = normalize_cerebras_rate_limit_headers(dict(getattr(response, "headers", {}) or {}))


def _post_exact_json_bytes(
    http_client: object,
    url: str,
    *,
    headers: Mapping[str, str],
    request_body: bytes,
    timeout_seconds: float,
) -> object:
    post = getattr(http_client, "post")
    try:
        parameters = inspect.signature(post).parameters.values()
        accepts_content = any(
            parameter.name == "content" or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
    except (TypeError, ValueError):
        accepts_content = True
    if accepts_content:
        return post(
            url,
            headers=dict(headers),
            content=request_body,
            timeout=timeout_seconds,
        )
    # Compatibility for existing narrow fake clients. Production httpx always
    # takes the exact pre-serialized bytes through the content branch above.
    return post(
        url,
        headers=dict(headers),
        json=json.loads(request_body),
        timeout=timeout_seconds,
    )


def _exact_response_body(response: object) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.encode("utf-8")
    payload = response.json()
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _response_status(response: object) -> int:
    raw_status = getattr(response, "status_code", None)
    try:
        return int(raw_status) if raw_status is not None else 200
    except (TypeError, ValueError):
        return 200


def _gemini_token_usage(payload: Mapping[str, Any]) -> tuple[dict[str, int], tuple[str, ...]]:
    usage = payload.get("usageMetadata")
    usage = usage if isinstance(usage, Mapping) else {}

    diagnostics: list[str] = []

    def count(field: str) -> int:
        value = usage.get(field)
        if value in (None, ""):
            return 0
        if isinstance(value, bool):
            diagnostics.append(f"invalid_numeric:{field}")
            return 0
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            diagnostics.append(f"invalid_numeric:{field}")
            return 0
        if parsed < 0:
            diagnostics.append(f"invalid_numeric:{field}")
            return 0
        return parsed

    return (
        {
            "prompt_tokens": count("promptTokenCount"),
            "candidate_tokens": count("candidatesTokenCount"),
            "cached_tokens": count("cachedContentTokenCount"),
            "thought_tokens": count("thoughtsTokenCount"),
            "total_tokens": count("totalTokenCount"),
        },
        tuple(diagnostics),
    )


_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:key|api[_-]?key|access[_-]?token|token)=)[^&\s]+"
)
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(authorization|x-goog-api-key|api[_-]?key|access[_-]?token|token)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")


def _redact_gemini_error_text(value: object, *, secret_values: tuple[str, ...]) -> str:
    safe = str(value or "")
    for secret in secret_values:
        if secret:
            safe = safe.replace(secret, "[redacted-api-key]")
    safe = _SENSITIVE_QUERY_PATTERN.sub(lambda match: f"{match.group(1)}[redacted]", safe)
    safe = _SENSITIVE_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}=[redacted]",
        safe,
    )
    return _BEARER_PATTERN.sub("Bearer [redacted]", safe)


def _gemini_attempt(
    *,
    request_body: bytes,
    response_body: bytes,
    model_alias: str,
    resolved_model: str,
    http_status: int | None,
    started_at: datetime,
    started_clock: int,
    token_usage: Mapping[str, int],
    status: str,
    error: Exception | None = None,
    error_phase: str = "",
    secret_values: tuple[str, ...] = (),
    usage_diagnostics: tuple[str, ...] = (),
) -> GeminiAttemptEnvelope:
    finished_at = datetime.now(UTC)
    elapsed_ms = max(0, int((perf_counter_ns() - started_clock) / 1_000_000))
    error_metadata: dict[str, Any] = (
        {
            "phase": error_phase,
            "type": type(error).__name__,
            "message": _redact_gemini_error_text(error, secret_values=secret_values)[:500],
        }
        if error is not None
        else {}
    )
    if usage_diagnostics:
        error_metadata["usage_diagnostics"] = list(usage_diagnostics)
    return GeminiAttemptEnvelope(
        request_body=request_body,
        response_body=response_body,
        provider="gemini",
        model_alias=model_alias,
        resolved_model=resolved_model,
        http_status=http_status,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_ms=elapsed_ms,
        token_usage=dict(token_usage),
        status=status,
        error_metadata=error_metadata,
    )


class GeminiAccountingProvider:
    """Native Gemini generateContent adapter with inline-PDF structured output."""

    provider_name = "gemini"
    product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION
    product_classification_instructions = OpenAiAccountingProvider.product_classification_instructions
    canonical_extraction_instructions = OpenAiAccountingProvider.canonical_extraction_instructions
    statement_suggestion_instructions = ChatCompletionsAccountingProvider.statement_suggestion_instructions
    review_rule_interpretation_instructions = OpenAiAccountingProvider.review_rule_interpretation_instructions

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        generate_content_url: str = "",
        http_client: Any | None = None,
        timeout_seconds: float = 60.0,
        max_output_tokens: int = 16384,
        max_inline_pdf_bytes: int = 50_000_000,
        requests_per_minute: int = 0,
        request_governor: GeminiRequestGovernor | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("GEMINI_API_KEY is required when FISORA_AI_PROVIDER=gemini")
        self.api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_GEMINI_MODEL
        self.generate_content_url = generate_content_url.strip() or GEMINI_GENERATE_CONTENT_URL_TEMPLATE.format(
            model=self.model
        )
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.max_inline_pdf_bytes = max_inline_pdf_bytes
        self.request_governor = request_governor or GeminiRequestGovernor(
            requests_per_minute
        )
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = classification_instructions_for(request)
        self.last_product_classification_instructions = instructions
        stage = str(payload.get("stage") or "").strip().lower()
        user_payload = (
            _accounting_v2_transport_payload(payload)
            if stage == "accounting_selection_v2"
            else _accounting_transport_payload(payload)
        )
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=instructions,
            user_payload=user_payload,
            schema=payload["output_schema"],
            cache_ready_accounting_v2=stage == "accounting_selection_v2",
        )

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        if not request.document_bytes:
            raise ValueError("Gemini invoice extraction requires native PDF bytes")
        payload = request.to_schema_payload()
        user_payload = _extraction_transport_payload(payload)
        return self._post_structured_json(
            schema_name="fisora_invoice_canonical_extraction",
            instructions=canonical_extraction_instructions_for(request),
            user_payload=user_payload,
            schema=payload["output_schema"],
            document_bytes=request.document_bytes,
            document_mime_type=request.document_mime_type,
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        payload = dict(request)
        return self._post_structured_json(
            schema_name="fisora_review_rule_interpretation",
            instructions=self.review_rule_interpretation_instructions,
            user_payload=_provider_user_payload(payload),
            schema=REVIEW_RULE_INTERPRETATION_SCHEMA,
        )

    def _post_structured_json(
        self,
        *,
        schema_name: str,
        instructions: str,
        user_payload: Mapping[str, object],
        schema: Mapping[str, object],
        document_bytes: bytes = b"",
        document_mime_type: str = "",
        cache_ready_accounting_v2: bool = False,
    ) -> dict[str, Any]:
        parts: list[dict[str, object]] = []
        if document_bytes:
            if len(document_bytes) > self.max_inline_pdf_bytes:
                raise ValueError(
                    f"Gemini inline PDF exceeds {self.max_inline_pdf_bytes} bytes"
                )
            if document_mime_type != "application/pdf":
                raise ValueError("Gemini native document input must use application/pdf")
            parts.append(
                {
                    "inline_data": {
                        "mime_type": document_mime_type,
                        "data": base64.b64encode(document_bytes).decode("ascii"),
                    }
                }
            )
        if cache_ready_accounting_v2:
            parts.extend(
                _accounting_v2_cache_ready_parts(
                    schema_name=schema_name,
                    user_payload=user_payload,
                    schema=schema,
                )
            )
        else:
            parts.append(
                {
                    "text": (
                        "Yalnizca verilen schema ile uyumlu gecerli JSON obje don. "
                        f"Schema adi: {schema_name}. "
                        f"Girdi: {json.dumps(user_payload, ensure_ascii=False)}"
                    )
                }
            )
        generation_config: dict[str, object] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": dict(schema),
            "maxOutputTokens": self.max_output_tokens,
        }
        if "gemini-3.5-flash-lite" not in self.model.lower():
            generation_config.update(
                {
                    "temperature": 0.2,
                    "topP": 1,
                }
            )
        request_payload = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }
        request_body = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        started_at = datetime.now(UTC)
        started_clock = perf_counter_ns()
        pending_error: GeminiProviderAttemptError | None = None
        try:
            self.request_governor.acquire()
            response = _post_exact_json_bytes(
                self.http_client,
                self.generate_content_url,
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                request_body=request_body,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as exc:
            attempt = _gemini_attempt(
                request_body=request_body,
                response_body=b"",
                model_alias=self.model,
                resolved_model="",
                http_status=None,
                started_at=started_at,
                started_clock=started_clock,
                token_usage={},
                status="failed",
                error=exc,
                error_phase="transport",
                secret_values=(self.api_key,),
            )
            pending_error = GeminiProviderAttemptError(
                str(attempt.error_metadata.get("message") or "Gemini transport failed"),
                attempt=attempt,
            )
        if pending_error is not None:
            raise pending_error

        http_status = _response_status(response)
        pending_error = None
        try:
            response_body = _exact_response_body(response)
        except Exception as exc:
            attempt = _gemini_attempt(
                request_body=request_body,
                response_body=b"",
                model_alias=self.model,
                resolved_model="",
                http_status=http_status,
                started_at=started_at,
                started_clock=started_clock,
                token_usage={},
                status="failed",
                error=exc,
                error_phase="response_capture",
                secret_values=(self.api_key,),
            )
            pending_error = GeminiProviderAttemptError(
                str(attempt.error_metadata.get("message") or "Gemini response capture failed"),
                attempt=attempt,
            )
        if pending_error is not None:
            raise pending_error
        pending_error = None
        try:
            response.raise_for_status()
        except Exception as exc:
            attempt = _gemini_attempt(
                request_body=request_body,
                response_body=response_body,
                model_alias=self.model,
                resolved_model="",
                http_status=http_status,
                started_at=started_at,
                started_clock=started_clock,
                token_usage={},
                status="failed",
                error=exc,
                error_phase="http",
                secret_values=(self.api_key,),
            )
            pending_error = GeminiProviderAttemptError(
                str(attempt.error_metadata.get("message") or "Gemini HTTP request failed"),
                attempt=attempt,
            )
        if pending_error is not None:
            raise pending_error

        pending_error = None
        response_payload: Mapping[str, Any] = {}
        try:
            loaded_response = json.loads(response_body.decode("utf-8"))
            if not isinstance(loaded_response, Mapping):
                raise ValueError("Gemini response body must be a JSON object")
            response_payload = loaded_response
        except Exception as exc:
            attempt = _gemini_attempt(
                request_body=request_body,
                response_body=response_body,
                model_alias=self.model,
                resolved_model="",
                http_status=http_status,
                started_at=started_at,
                started_clock=started_clock,
                token_usage={},
                status="failed",
                error=exc,
                error_phase="response_json",
                secret_values=(self.api_key,),
            )
            pending_error = GeminiProviderAttemptError(
                str(attempt.error_metadata.get("message") or "Gemini response JSON failed"),
                attempt=attempt,
            )
        if pending_error is not None:
            raise pending_error

        resolved_model = str(response_payload.get("modelVersion") or "")
        token_usage, usage_diagnostics = _gemini_token_usage(response_payload)
        self.last_capacity_snapshot = {
            "source": "response_body",
            "usage": dict(token_usage),
            "last_checked_at": utc_now(),
        }
        pending_error = None
        parsed: dict[str, Any] = {}
        try:
            parsed = _extract_gemini_json_response(response_payload)
        except Exception as exc:
            attempt = _gemini_attempt(
                request_body=request_body,
                response_body=response_body,
                model_alias=self.model,
                resolved_model=resolved_model,
                http_status=http_status,
                started_at=started_at,
                started_clock=started_clock,
                token_usage=token_usage,
                status="failed",
                error=exc,
                error_phase="structured_parse",
                secret_values=(self.api_key,),
                usage_diagnostics=usage_diagnostics,
            )
            pending_error = GeminiProviderAttemptError(
                str(attempt.error_metadata.get("message") or "Gemini structured parse failed"),
                attempt=attempt,
            )
        if pending_error is not None:
            raise pending_error
        attempt = _gemini_attempt(
            request_body=request_body,
            response_body=response_body,
            model_alias=self.model,
            resolved_model=resolved_model,
            http_status=http_status,
            started_at=started_at,
            started_clock=started_clock,
            token_usage=token_usage,
            status="successful",
            usage_diagnostics=usage_diagnostics,
        )
        return GeminiStructuredResult(parsed, attempt=attempt)


class FallbackAccountingProvider:
    """Try multiple accounting providers before reporting a provider failure."""

    def __init__(self, providers: list[OpenAiAccountingProvider]) -> None:
        if not providers:
            raise ValueError("FallbackAccountingProvider requires at least one provider")
        self.providers = providers
        self.provider_name = ">".join(provider.provider_name for provider in providers)
        self.last_provider_name = ""
        self.last_capacity_snapshot: dict[str, object] = {}
        self.model = ""
        self.product_classification_instructions = ""
        self.product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        return self._call("classify_product", request)

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        return self._call("extract_invoice_canonical", request)

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        return self._call("suggest_statement_line", request)

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        return self._call("interpret_review_rule", request)

    def _call(
        self,
        method_name: str,
        request: AiClassificationRequest | CanonicalExtractionRequest | StatementAiSuggestionRequest | Mapping[str, object],
    ) -> dict[str, Any]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                result = getattr(provider, method_name)(request)
                self.last_provider_name = provider.provider_name
                self.last_capacity_snapshot = dict(getattr(provider, "last_capacity_snapshot", {}) or {})
                self.model = str(getattr(provider, "model", "") or "")
                self.product_classification_instructions = str(
                    getattr(provider, "last_product_classification_instructions", "")
                    or getattr(provider, "product_classification_instructions", "")
                    or ""
                )
                self.product_classification_prompt_version = str(
                    getattr(provider, "product_classification_prompt_version", "")
                    or PRODUCT_CLASSIFICATION_PROMPT_VERSION
                )
                return result
            except Exception as exc:  # noqa: BLE001 - fallback boundary keeps the pipeline alive
                errors.append(f"{provider.provider_name}: {type(exc).__name__}: {str(exc)[:160]}")
        raise RuntimeError("; ".join(errors))


class TaskRoutingAccountingProvider:
    """Route semantic stages to independently ordered configured providers."""

    def __init__(
        self,
        *,
        classification_provider: object,
        counterparty_provider: object,
        configured_provider: object | None = None,
    ) -> None:
        self.classification_provider = classification_provider
        self.counterparty_provider = counterparty_provider
        compatibility_provider = configured_provider or classification_provider
        self.provider_name = str(getattr(compatibility_provider, "provider_name", "") or "")
        self.providers = tuple(
            getattr(compatibility_provider, "providers", (compatibility_provider,))
        )
        self.last_provider_name = ""
        self.last_capacity_snapshot: dict[str, object] = {}
        self.model = ""
        self.product_classification_instructions = ""
        self.product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        stage = str(request.context.candidate_strategy.stage or "").strip().lower()
        provider = self.counterparty_provider if stage == "counterparty_resolve" else self.classification_provider
        try:
            return provider.classify_product(request)
        finally:
            self.last_provider_name = str(
                getattr(provider, "last_provider_name", "") or getattr(provider, "provider_name", "") or ""
            )
            self.last_capacity_snapshot = dict(getattr(provider, "last_capacity_snapshot", {}) or {})
            self.model = str(getattr(provider, "model", "") or "")
            self.product_classification_instructions = str(
                getattr(provider, "last_product_classification_instructions", "")
                or getattr(provider, "product_classification_instructions", "")
                or classification_instructions_for(request)
            )
            self.product_classification_prompt_version = str(
                getattr(provider, "product_classification_prompt_version", "")
                or PRODUCT_CLASSIFICATION_PROMPT_VERSION
            )


def _extract_json_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("output_parsed"), dict):
        return dict(payload["output_parsed"])
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return _loads_object(output_text)

    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, Mapping):
                continue
            if isinstance(content.get("parsed"), dict):
                return dict(content["parsed"])
            if content.get("type") not in {"output_text", "text"}:
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return _loads_object("".join(chunks))
    raise ValueError("OpenAI response did not contain structured JSON output")


def _extract_chat_completion_json_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Chat completion response did not contain choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("Chat completion choice must be an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Chat completion choice did not contain a message")
    content = message.get("content")
    if isinstance(content, list):
        chunks = [
            item.get("text", "")
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        ]
        content = "".join(chunks)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Chat completion message did not contain JSON text")
    return _loads_object(_strip_json_fence(content))


def _extract_gemini_json_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response did not contain candidates")
    first = candidates[0]
    content = first.get("content") if isinstance(first, Mapping) else None
    parts = content.get("parts") if isinstance(content, Mapping) else None
    if not isinstance(parts, list):
        raise ValueError("Gemini candidate did not contain content parts")
    chunks = [
        part.get("text", "")
        for part in parts
        if isinstance(part, Mapping) and isinstance(part.get("text"), str)
    ]
    raw = "".join(chunks).strip()
    if not raw:
        raise ValueError("Gemini response did not contain JSON text")
    return _loads_object(_strip_json_fence(raw))


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads_object(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("OpenAI structured output must be a JSON object")
    return loaded
