from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import re
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4

from app.domain.business_relevance import (
    CORE_INPUT_CATEGORIES,
    FIXED_ASSET_CATEGORIES,
    GENERAL_EXPENSE_CATEGORIES,
    HEARING_CENTER_CATEGORIES,
    PERSONAL_USE_CATEGORIES,
    REGULATED_ITEM_CATEGORIES,
    ProductClassification,
    classify_product_line,
)


ALLOWED_AI_CATEGORIES = tuple(
    sorted(
        {
            *GENERAL_EXPENSE_CATEGORIES,
            *HEARING_CENTER_CATEGORIES,
            *CORE_INPUT_CATEGORIES,
            *FIXED_ASSET_CATEGORIES,
            *PERSONAL_USE_CATEGORIES,
            *REGULATED_ITEM_CATEGORIES,
            "bilinmeyen",
        }
    )
)


@dataclass(frozen=True)
class AiClassificationPolicy:
    enabled: bool = False
    static_confidence_threshold: int = 70
    max_input_chars: int = 320
    max_provider_calls: int = 1
    single_stage_account_limit: int = 40
    final_stage_account_limit: int = 120
    counterparty_limit: int = 80


@dataclass(frozen=True)
class AiCandidateStrategy:
    mode: str = "single_stage"
    stage: str = "final_account"
    account_candidate_count: int = 0
    counterparty_candidate_count: int = 0
    selected_families: tuple[str, ...] = ()


@dataclass(frozen=True)
class AiClassificationContext:
    client_activity: str = ""
    nace_code: str = ""
    nace_research_summary: str = ""
    activity_tags: tuple[str, ...] = ()
    accounting_direction: str = ""
    direction_confidence: int = 0
    direction_evidence: tuple[str, ...] = ()
    direction_uncertainty: bool = False
    account_candidates: tuple[str, ...] = ()
    account_candidate_details: tuple[dict[str, Any], ...] = ()
    counterparty_candidates: tuple[str, ...] = ()
    counterparty_candidate_details: tuple[dict[str, Any], ...] = ()
    invoice_counterparty: dict[str, Any] = field(default_factory=dict)
    account_family_candidates: tuple[dict[str, Any], ...] = ()
    canonical_lines: tuple[dict[str, Any], ...] = ()
    candidate_strategy: AiCandidateStrategy = field(default_factory=AiCandidateStrategy)
    account_candidate_limit: int = 40
    counterparty_candidate_limit: int = 80
    account_candidate_details_limit: int = 40
    semantic_stage: str = "initial_account_decision"
    research_evidence: tuple[dict[str, Any], ...] = ()
    prior_semantic_attempt: dict[str, Any] = field(default_factory=dict)
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AiClassificationRequest:
    raw_line: str
    supplier_hint: str
    allowed_categories: tuple[str, ...]
    max_input_chars: int
    context: AiClassificationContext = AiClassificationContext()

    def to_schema_payload(self) -> dict[str, object]:
        if self.context.semantic_stage in {"research_synthesis", "account_correction"}:
            payload = self._to_line_batch_payload()
            payload.update(
                {
                    "semantic_stage": self.context.semantic_stage,
                    "research_evidence": list(self.context.research_evidence),
                    "prior_semantic_attempt": dict(self.context.prior_semantic_attempt),
                    "validation_errors": list(self.context.validation_errors),
                }
            )
            return payload
        if self.context.candidate_strategy.stage == "family_select":
            return self._to_family_select_payload()
        if self.context.candidate_strategy.stage == "counterparty_resolve":
            return self._to_counterparty_resolve_payload()
        if self.context.candidate_strategy.stage == "line_batch":
            return self._to_line_batch_payload()
        account_candidates = _limited_strings(self.context.account_candidates, limit=max(self.context.account_candidate_limit, 0))
        counterparty_candidates = _limited_strings(self.context.counterparty_candidates, limit=max(self.context.counterparty_candidate_limit, 0))
        return {
            "raw_line": self.raw_line[: self.max_input_chars].strip(),
            "supplier_hint": self.supplier_hint[: self.max_input_chars].strip(),
            "client_activity": self.context.client_activity[: self.max_input_chars].strip(),
            "nace_code": self.context.nace_code[:64].strip(),
            "nace_research_summary": self.context.nace_research_summary[: self.max_input_chars].strip(),
            "activity_tags": list(_limited_strings(self.context.activity_tags, limit=8)),
            "accounting_direction": self.context.accounting_direction,
            "direction_confidence": self.context.direction_confidence,
            "direction_evidence": list(_limited_strings(self.context.direction_evidence, limit=8)),
            "direction_uncertainty": self.context.direction_uncertainty,
            "candidate_strategy": _candidate_strategy_payload(self.context.candidate_strategy),
            "account_candidates": list(account_candidates),
            "account_candidate_details": list(self.context.account_candidate_details[: max(self.context.account_candidate_details_limit, 0)]),
            "counterparty_candidates": list(counterparty_candidates),
            "counterparty_candidate_details": list(
                self.context.counterparty_candidate_details[: max(self.context.counterparty_candidate_limit, 0)]
            ),
            "invoice_counterparty": self.context.invoice_counterparty,
            "allowed_categories": list(self.allowed_categories),
            "output_schema": {
                "type": "object",
                "required": [
                    "category",
                    "confidence",
                    "reason",
                    "evidence",
                    "suggested_account_code",
                    "suggested_counterparty_code",
                    "risk_flags",
                    "account_reason",
                    "product_identity",
                    "needs_research",
                    "research_query",
                ],
                "properties": {
                    "category": {"type": "string", "enum": list(self.allowed_categories)},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string", "maxLength": 240},
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "suggested_account_code": {
                        "type": "string",
                        "enum": ["", *account_candidates],
                    },
                    "suggested_counterparty_code": {
                        "type": "string",
                        "enum": ["", *counterparty_candidates],
                    },
                    "risk_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                    "account_reason": {"type": "string", "maxLength": 240},
                    "product_identity": {"type": "string", "maxLength": 160},
                    "needs_research": {"type": "boolean"},
                    "research_query": {"type": "string", "maxLength": 160},
                },
                "additionalProperties": False,
            },
        }

    def _to_line_batch_payload(self) -> dict[str, object]:
        account_candidates = _limited_strings(
            self.context.account_candidates,
            limit=max(self.context.account_candidate_limit, 0),
        )
        counterparty_candidates = _limited_strings(
            self.context.counterparty_candidates,
            limit=max(self.context.counterparty_candidate_limit, 0),
        )
        canonical_lines = tuple(
            {
                "canonical_line_id": str(line.get("canonical_line_id") or ""),
                "source_position": str(line.get("source_position") or ""),
                "description": str(line.get("description") or "")[: self.max_input_chars],
                "taxable_amount": str(line.get("taxable_amount") or ""),
                "vat_rate": str(line.get("vat_rate") or ""),
            }
            for line in self.context.canonical_lines
            if str(line.get("canonical_line_id") or "")
        )
        line_ids = tuple(line["canonical_line_id"] for line in canonical_lines)
        decision_properties = {
            "canonical_line_id": {"type": "string", "enum": list(line_ids)},
            "category": {"type": "string", "enum": list(self.allowed_categories)},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "product_identity": {"type": "string", "maxLength": 160},
            "suggested_account_code": {"type": "string", "enum": ["", *account_candidates]},
            "reason": {"type": "string", "maxLength": 240},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "needs_research": {"type": "boolean"},
            "research_query": {"type": "string", "maxLength": 160},
            "risk_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        }
        output_properties = {
            "category": {"type": "string", "enum": list(self.allowed_categories)},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "reason": {"type": "string", "maxLength": 240},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "suggested_account_code": {"type": "string", "enum": ["", *account_candidates]},
            "suggested_counterparty_code": {"type": "string", "enum": ["", *counterparty_candidates]},
            "risk_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "account_reason": {"type": "string", "maxLength": 240},
            "product_identity": {"type": "string", "maxLength": 160},
            "needs_research": {"type": "boolean"},
            "research_query": {"type": "string", "maxLength": 160},
            "line_decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": decision_properties,
                    "required": list(decision_properties),
                    "additionalProperties": False,
                },
                "minItems": len(line_ids),
                "maxItems": len(line_ids),
            },
        }
        return {
            "raw_line": self.raw_line[: self.max_input_chars].strip(),
            "supplier_hint": self.supplier_hint[: self.max_input_chars].strip(),
            "client_activity": self.context.client_activity[: self.max_input_chars].strip(),
            "nace_code": self.context.nace_code[:64].strip(),
            "activity_tags": list(_limited_strings(self.context.activity_tags, limit=8)),
            "accounting_direction": self.context.accounting_direction,
            "direction_confidence": self.context.direction_confidence,
            "direction_evidence": list(_limited_strings(self.context.direction_evidence, limit=8)),
            "canonical_lines": list(canonical_lines),
            "account_candidates": list(account_candidates),
            "account_candidate_details": list(
                self.context.account_candidate_details[: max(self.context.account_candidate_details_limit, 0)]
            ),
            "counterparty_candidates": list(counterparty_candidates),
            "counterparty_candidate_details": list(
                self.context.counterparty_candidate_details[: max(self.context.counterparty_candidate_limit, 0)]
            ),
            "invoice_counterparty": self.context.invoice_counterparty,
            "allowed_categories": list(self.allowed_categories),
            "candidate_strategy": _candidate_strategy_payload(self.context.candidate_strategy),
            "output_schema": {
                "type": "object",
                "properties": output_properties,
                "required": list(output_properties),
                "additionalProperties": False,
            },
        }

    def _to_family_select_payload(self) -> dict[str, object]:
        family_candidates = tuple(self.context.account_family_candidates[: max(self.context.account_candidate_limit, 0)])
        allowed_families = _limited_strings(
            [str(candidate.get("family") or "").strip() for candidate in family_candidates],
            limit=max(self.context.account_candidate_limit, 0),
        )
        return {
            "raw_line": self.raw_line[: self.max_input_chars].strip(),
            "supplier_hint": self.supplier_hint[: self.max_input_chars].strip(),
            "client_activity": self.context.client_activity[: self.max_input_chars].strip(),
            "nace_code": self.context.nace_code[:64].strip(),
            "nace_research_summary": self.context.nace_research_summary[: self.max_input_chars].strip(),
            "activity_tags": list(_limited_strings(self.context.activity_tags, limit=8)),
            "accounting_direction": self.context.accounting_direction,
            "direction_confidence": self.context.direction_confidence,
            "direction_evidence": list(_limited_strings(self.context.direction_evidence, limit=8)),
            "direction_uncertainty": self.context.direction_uncertainty,
            "candidate_strategy": _candidate_strategy_payload(self.context.candidate_strategy),
            "account_family_candidates": list(family_candidates),
            "allowed_account_families": list(allowed_families),
            "allowed_categories": list(self.allowed_categories),
            "output_schema": {
                "type": "object",
                "required": [
                    "category",
                    "confidence",
                    "reason",
                    "evidence",
                    "selected_account_families",
                    "risk_flags",
                    "account_reason",
                    "product_identity",
                    "needs_research",
                    "research_query",
                ],
                "properties": {
                    "category": {"type": "string", "enum": list(self.allowed_categories)},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string", "maxLength": 240},
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "selected_account_families": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(allowed_families)},
                        "maxItems": 8,
                    },
                    "primary_account_families": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(allowed_families)},
                        "maxItems": 8,
                    },
                    "alternative_account_families": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(allowed_families)},
                        "maxItems": 8,
                    },
                    "direction_assessment": {"type": "string", "maxLength": 80},
                    "risk_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                    "account_reason": {"type": "string", "maxLength": 240},
                    "product_identity": {"type": "string", "maxLength": 160},
                    "needs_research": {"type": "boolean"},
                    "research_query": {"type": "string", "maxLength": 160},
                },
                "additionalProperties": False,
            },
        }

    def _to_counterparty_resolve_payload(self) -> dict[str, object]:
        counterparty_candidates = _limited_strings(
            self.context.counterparty_candidates,
            limit=len(self.context.counterparty_candidates),
        )
        return {
            "raw_line": self.raw_line[: self.max_input_chars].strip(),
            "supplier_hint": self.supplier_hint[: self.max_input_chars].strip(),
            "client_activity": self.context.client_activity[: self.max_input_chars].strip(),
            "nace_code": self.context.nace_code[:64].strip(),
            "activity_tags": list(_limited_strings(self.context.activity_tags, limit=8)),
            "accounting_direction": self.context.accounting_direction,
            "direction_confidence": self.context.direction_confidence,
            "direction_evidence": list(_limited_strings(self.context.direction_evidence, limit=8)),
            "direction_uncertainty": self.context.direction_uncertainty,
            "candidate_strategy": _candidate_strategy_payload(self.context.candidate_strategy),
            "counterparty_candidates": list(counterparty_candidates),
            "counterparty_candidate_details": list(self.context.counterparty_candidate_details),
            "invoice_counterparty": self.context.invoice_counterparty,
            "allowed_categories": list(self.allowed_categories),
            "output_schema": {
                "type": "object",
                "required": [
                    "category",
                    "confidence",
                    "reason",
                    "evidence",
                    "suggested_account_code",
                    "suggested_counterparty_code",
                    "risk_flags",
                    "account_reason",
                    "product_identity",
                    "needs_research",
                    "research_query",
                ],
                "properties": {
                    "category": {"type": "string", "enum": list(self.allowed_categories)},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string", "maxLength": 240},
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "suggested_account_code": {"type": "string", "enum": [""]},
                    "suggested_counterparty_code": {
                        "type": "string",
                        "enum": ["", *counterparty_candidates],
                    },
                    "risk_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                    "account_reason": {"type": "string", "maxLength": 240},
                    "product_identity": {"type": "string", "maxLength": 160},
                    "needs_research": {"type": "boolean"},
                    "research_query": {"type": "string", "maxLength": 160},
                },
                "additionalProperties": False,
            },
        }


@dataclass(frozen=True)
class AiProviderClassification:
    category: str
    confidence: int
    reason: str
    evidence: tuple[str, ...] = ()
    suggested_account_code: str = ""
    suggested_counterparty_code: str = ""
    risk_flags: tuple[str, ...] = ()
    account_reason: str = ""
    product_identity: str = ""
    needs_research: bool = False
    research_query: str = ""
    selected_account_families: tuple[str, ...] = ()
    line_decisions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AiClassificationResult:
    classification: ProductClassification
    ai_used: bool
    provider: str
    skipped_reason: str = ""
    provider_reason: str = ""
    estimated_input_chars: int = 0
    suggested_account_code: str = ""
    suggested_counterparty_code: str = ""
    risk_flags: tuple[str, ...] = ()
    account_reason: str = ""
    product_identity: str = ""
    needs_research: bool = False
    research_query: str = ""
    selected_account_families: tuple[str, ...] = ()
    candidate_strategy: AiCandidateStrategy = field(default_factory=AiCandidateStrategy)
    ai_trace: tuple[dict[str, Any], ...] = ()
    semantic_attempts: tuple[dict[str, Any], ...] = ()
    accepted_semantic_attempt_id: str = ""
    line_decisions: tuple[dict[str, Any], ...] = ()


class ProductClassifier(Protocol):
    def classify(
        self,
        raw_line: str,
        *,
        supplier_hint: str = "",
        context: AiClassificationContext | None = None,
    ) -> AiClassificationResult:
        ...


class ProductClassificationProvider(Protocol):
    provider_name: str

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        ...


def _limited_strings(value: tuple[str, ...] | list[str], *, limit: int) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:limit]


def _validated_suggestion(value: object, allowed: tuple[str, ...]) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    return candidate if candidate in set(allowed) else ""


def _candidate_strategy_payload(strategy: AiCandidateStrategy) -> dict[str, object]:
    return {
        "mode": strategy.mode,
        "stage": strategy.stage,
        "account_candidate_count": strategy.account_candidate_count,
        "counterparty_candidate_count": strategy.counterparty_candidate_count,
        "selected_families": list(strategy.selected_families),
    }


TRACE_MAX_STRING_CHARS = 4000
TRACE_MAX_LIST_ITEMS = 250
TRACE_SECRET_KEYS = {"authorization", "api_key", "key", "token", "secret", "password"}
SEMANTIC_ATTEMPT_FIELDS = (
    "attempt_id",
    "stage",
    "canonical_line_ids",
    "prompt_version",
    "provider",
    "model",
    "candidate_account_codes",
    "candidate_counterparty_codes",
    "validated_response",
    "validation_errors",
    "accepted",
    "superseded_by_attempt_id",
)
SEMANTIC_VALIDATED_RESPONSE_FIELDS = {
    "category",
    "product_category",
    "confidence",
    "reason",
    "evidence",
    "suggested_account_code",
    "suggested_counterparty_code",
    "selected_account_code",
    "selected_counterparty_code",
    "selected_account_families",
    "risk_flags",
    "account_reason",
    "product_identity",
    "needs_research",
    "research_query",
    "line_decisions",
    "display_name",
    "account_treatment",
    "research_confidence",
    "accounting_impact_confidence",
    "research_evidence",
    "question",
    "canonical_line_ids",
    "conflicts",
    "evidence_gaps",
    "cache_provenance",
    "authority",
}
SEMANTIC_LINE_DECISION_FIELDS = {
    "canonical_line_id",
    "category",
    "confidence",
    "product_identity",
    "suggested_account_code",
    "reason",
    "evidence",
    "needs_research",
    "research_query",
    "risk_flags",
}
SEMANTIC_RESEARCH_EVIDENCE_FIELDS = {
    "url",
    "title",
    "source_type",
    "summary_tr",
    "accepted",
    "question",
    "canonical_line_ids",
    "claims",
    "conflicts",
    "source_url",
    "source_domain",
    "source_kind",
    "evidence_summary",
    "confidence",
    "quality",
    "raw_summary",
}
SEMANTIC_STRING_LIST_FIELDS = {"evidence", "selected_account_families", "risk_flags"}
SEMANTIC_TEXT_FIELDS = {
    "category",
    "product_category",
    "reason",
    "suggested_account_code",
    "suggested_counterparty_code",
    "selected_account_code",
    "selected_counterparty_code",
    "account_reason",
    "product_identity",
    "research_query",
    "display_name",
    "account_treatment",
}
SEMANTIC_DOCUMENT_REDACTION_MARKER = "[redacted-document-content]"
AUTHORIZATION_ASSIGNMENT_PATTERN = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_])
    ["']?authorization["']?\s*[:=]\s*
    (?:["'][^"'\r\n]*["']|[^,;\r\n}\]]+)
    '''
)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_])
    ["']?(api[_-]?key|credential|password|secret|token)["']?\s*[:=]\s*
    (?:["'][^"'\r\n]*["']|[^\s,;\r\n}\]]+)
    '''
)
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
API_KEY_VALUE_PATTERN = re.compile(r"(?i)\b(?:sk|gsk|csk|tvly|or-v1)-[A-Za-z0-9._-]{6,}")
XML_INVOICE_DOCUMENT_PATTERN = re.compile(
    r"(?is)<(?:[A-Za-z0-9_.-]+:)?Invoice\b[^>]*>.*?</(?:[A-Za-z0-9_.-]+:)?Invoice\s*>"
)
UBL_DOCUMENT_MARKER_PATTERN = re.compile(
    r"(?is)(?:urn:oasis:names:specification:ubl|<cac:InvoiceLine\b|<cbc:InvoiceTypeCode\b)"
)
RAW_DOCUMENT_ENVELOPE_PATTERN = re.compile(
    r"(?is)(?:ocr\s+document\s+(?:start|end)|(?:begin|end)\s+(?:raw\s+)?(?:source\s+)?document|\[(?:document|raw_document)_(?:start|end)\])"
)
RAW_DOCUMENT_KEY_PATTERN = re.compile(
    r'''(?ix)["']?(?:raw_private_document|raw_document|source_document|full_invoice_xml|document_content)["']?\s*[:=]'''
)
DOCUMENT_FIELD_LINE_PATTERN = re.compile(
    r"(?im)^\s*(fatura\s*(?:no|numarasi)|invoice\s*(?:no|number)|ettn|uuid|"
    r"satici\s*(?:unvan|vkn|vergi\s*no)|supplier\s*(?:name|tax\s*id)|"
    r"alici\s*(?:unvan|vkn|vergi\s*no)|customer\s*(?:name|tax\s*id)|"
    r"kalem|invoice\s*line|matrah|kdv|vat|toplam|grand\s*total|payable)\s*[:=]"
)


def _looks_like_document_payload(value: str) -> bool:
    if XML_INVOICE_DOCUMENT_PATTERN.search(value):
        return True
    if UBL_DOCUMENT_MARKER_PATTERN.search(value) and "<" in value and ">" in value:
        return True
    if RAW_DOCUMENT_ENVELOPE_PATTERN.search(value) or RAW_DOCUMENT_KEY_PATTERN.search(value):
        return True
    nonempty_lines = [line for line in value.splitlines() if line.strip()]
    field_matches = list(DOCUMENT_FIELD_LINE_PATTERN.finditer(value))
    field_names = {
        match.group(1).casefold()
        for match in field_matches
    }
    return (
        len(nonempty_lines) >= 6
        and len(field_names) >= 4
        and len(field_matches) * 2 >= len(nonempty_lines)
    )


def _redact_sensitive_text(value: str) -> str:
    if _looks_like_document_payload(value):
        return SEMANTIC_DOCUMENT_REDACTION_MARKER
    redacted = AUTHORIZATION_ASSIGNMENT_PATTERN.sub("authorization=[redacted]", value)
    redacted = SENSITIVE_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}=[redacted]",
        redacted,
    )
    redacted = BEARER_PATTERN.sub("Bearer [redacted]", redacted)
    return API_KEY_VALUE_PATTERN.sub("[redacted-api-key]", redacted)


def _trace_safe_value(value: Any) -> Any:
    if isinstance(value, str):
        safe_text = _redact_sensitive_text(value)
        if len(safe_text) <= TRACE_MAX_STRING_CHARS:
            return safe_text
        return f"{safe_text[:TRACE_MAX_STRING_CHARS]}... [truncated {len(safe_text) - TRACE_MAX_STRING_CHARS} chars]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return _trace_safe_value(list(value))
    if isinstance(value, list):
        safe_items = [_trace_safe_value(item) for item in value[:TRACE_MAX_LIST_ITEMS]]
        if len(value) > TRACE_MAX_LIST_ITEMS:
            safe_items.append({"truncated_items": len(value) - TRACE_MAX_LIST_ITEMS})
        return safe_items
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.strip().lower() in TRACE_SECRET_KEYS:
                safe[key_text] = "[redacted]"
            else:
                safe[key_text] = _trace_safe_value(item)
        return safe
    return str(value)


def _provider_model(provider: ProductClassificationProvider) -> str:
    return str(getattr(provider, "model", "") or "")


def _provider_prompt(provider: ProductClassificationProvider) -> str:
    return str(
        getattr(provider, "last_product_classification_instructions", "")
        or getattr(provider, "product_classification_instructions", "")
        or ""
    )


def _provider_prompt_version(provider: ProductClassificationProvider) -> str:
    return str(getattr(provider, "product_classification_prompt_version", "") or "unversioned")[:160]


def _provider_error_code(exc: Exception) -> str:
    return f"provider_error:{type(exc).__name__}"


def _safe_validated_response(value: Mapping[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, raw_value in dict(value or {}).items():
        key = str(raw_key)
        if key not in SEMANTIC_VALIDATED_RESPONSE_FIELDS:
            continue
        if key == "line_decisions":
            decisions: list[dict[str, Any]] = []
            for item in raw_value if isinstance(raw_value, (list, tuple)) else ():
                if not isinstance(item, Mapping):
                    continue
                decision: dict[str, Any] = {}
                for item_key, item_value in item.items():
                    decision_key = str(item_key)
                    if decision_key not in SEMANTIC_LINE_DECISION_FIELDS:
                        continue
                    if decision_key in {"evidence", "risk_flags"}:
                        decision[decision_key] = [
                            _trace_safe_value(entry)
                            for entry in (item_value if isinstance(item_value, (list, tuple)) else ())
                            if isinstance(entry, str)
                        ][:TRACE_MAX_LIST_ITEMS]
                    elif decision_key in {
                        "canonical_line_id",
                        "category",
                        "product_identity",
                        "suggested_account_code",
                        "reason",
                        "research_query",
                    }:
                        decision[decision_key] = _trace_safe_value(str(item_value or ""))
                    else:
                        decision[decision_key] = _trace_safe_value(item_value)
                decisions.append(decision)
            safe[key] = decisions[:TRACE_MAX_LIST_ITEMS]
            continue
        if key == "research_evidence":
            evidence: list[dict[str, Any]] = []
            for item in raw_value if isinstance(raw_value, (list, tuple)) else ():
                if not isinstance(item, Mapping):
                    continue
                evidence_item: dict[str, Any] = {}
                for item_key, item_value in item.items():
                    evidence_key = str(item_key)
                    if evidence_key not in SEMANTIC_RESEARCH_EVIDENCE_FIELDS:
                        continue
                    evidence_item[evidence_key] = bool(item_value) if evidence_key == "accepted" else _trace_safe_value(item_value)
                evidence.append(evidence_item)
            safe[key] = evidence[:TRACE_MAX_LIST_ITEMS]
            continue
        if key in SEMANTIC_STRING_LIST_FIELDS:
            safe[key] = [
                _trace_safe_value(item)
                for item in (raw_value if isinstance(raw_value, (list, tuple)) else ())
                if isinstance(item, str)
            ][:TRACE_MAX_LIST_ITEMS]
            continue
        if key in SEMANTIC_TEXT_FIELDS:
            safe[key] = _trace_safe_value(str(raw_value or ""))
            continue
        safe[key] = _trace_safe_value(raw_value)
    return safe


def serialize_semantic_decision_attempt(
    *,
    attempt_id: str = "",
    stage: str,
    canonical_line_ids: Iterable[object] = (),
    prompt_version: str,
    provider: str,
    model: str,
    candidate_account_codes: Iterable[object] = (),
    candidate_counterparty_codes: Iterable[object] = (),
    validated_response: Mapping[str, Any] | None = None,
    validation_errors: Iterable[object] = (),
    accepted: bool,
    superseded_by_attempt_id: str = "",
) -> dict[str, Any]:
    """Serialize the sole persistence-safe semantic attempt contract."""

    return {
        "attempt_id": str(attempt_id or uuid4())[:160],
        "stage": str(stage or "initial_account_decision")[:80],
        "canonical_line_ids": list(_limited_strings(list(canonical_line_ids), limit=TRACE_MAX_LIST_ITEMS)),
        "prompt_version": str(prompt_version or "unversioned")[:160],
        "provider": str(provider or "")[:160],
        "model": str(model or "")[:160],
        "candidate_account_codes": list(
            _limited_strings(list(candidate_account_codes), limit=TRACE_MAX_LIST_ITEMS)
        ),
        "candidate_counterparty_codes": list(
            _limited_strings(list(candidate_counterparty_codes), limit=TRACE_MAX_LIST_ITEMS)
        ),
        "validated_response": _safe_validated_response(validated_response),
        "validation_errors": [
            str(_trace_safe_value(item))
            for item in _limited_strings(list(validation_errors), limit=50)
        ],
        "accepted": accepted is True,
        "superseded_by_attempt_id": str(superseded_by_attempt_id or "")[:160],
    }


def _validate_semantic_attempt_graph(attempts: list[dict[str, Any]]) -> None:
    by_id = {str(item["attempt_id"]): item for item in attempts}
    for attempt_id, item in by_id.items():
        target = str(item.get("superseded_by_attempt_id") or "")
        if target and target not in by_id:
            raise ValueError(f"semantic attempt {attempt_id} supersedes missing target {target}")

    visited: set[str] = set()
    for start in by_id:
        path: set[str] = set()
        current = start
        while current:
            if current in path:
                raise ValueError(f"semantic attempt supersession cycle at {current}")
            if current in visited:
                break
            path.add(current)
            current = str(by_id[current].get("superseded_by_attempt_id") or "")
        visited.update(path)

    accepted_unsuperseded = [
        item
        for item in attempts
        if item.get("accepted") is True and not str(item.get("superseded_by_attempt_id") or "")
    ]
    if len(accepted_unsuperseded) > 1:
        raise ValueError("multiple accepted unsuperseded semantic attempts")


def merge_semantic_attempts(*histories: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Append sanitized attempts by stable ID without rewriting an earlier record."""

    merged: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for history in histories:
        for raw in history or ():
            if not isinstance(raw, Mapping):
                continue
            serialized = serialize_semantic_decision_attempt(
                attempt_id=str(raw.get("attempt_id") or ""),
                stage=str(raw.get("stage") or "initial_account_decision"),
                canonical_line_ids=raw.get("canonical_line_ids") or (),
                prompt_version=str(raw.get("prompt_version") or "unversioned"),
                provider=str(raw.get("provider") or ""),
                model=str(raw.get("model") or ""),
                candidate_account_codes=raw.get("candidate_account_codes") or (),
                candidate_counterparty_codes=raw.get("candidate_counterparty_codes") or (),
                validated_response=(
                    raw.get("validated_response")
                    if isinstance(raw.get("validated_response"), Mapping)
                    else {}
                ),
                validation_errors=raw.get("validation_errors") or (),
                accepted=raw.get("accepted") is True,
                superseded_by_attempt_id=str(raw.get("superseded_by_attempt_id") or ""),
            )
            attempt_id = str(serialized["attempt_id"])
            if attempt_id in seen:
                if seen[attempt_id] != serialized:
                    raise ValueError(f"semantic attempt_id conflict: {attempt_id}")
                continue
            seen[attempt_id] = serialized
            merged.append(serialized)
    _validate_semantic_attempt_graph(merged)
    return merged


def merge_semantic_attempt_result(
    result: Mapping[str, Any],
    *,
    previous_result: Mapping[str, Any] | None = None,
    appended_attempts: Iterable[Mapping[str, Any]] = (),
    accepted_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Merge append-only semantic evidence while preserving the latest result body."""

    updated = dict(result)
    previous = dict(previous_result or {})
    attempts = merge_semantic_attempts(
        previous.get("semantic_attempts")
        if isinstance(previous.get("semantic_attempts"), (list, tuple))
        else (),
        updated.get("semantic_attempts") if isinstance(updated.get("semantic_attempts"), (list, tuple)) else (),
        appended_attempts,
    )
    updated["semantic_attempts"] = attempts
    attempt_ids = {str(item["attempt_id"]) for item in attempts}
    accepted_ids = {
        str(item["attempt_id"])
        for item in attempts
        if item.get("accepted") is True
    }
    requested = str(
        accepted_attempt_id
        if accepted_attempt_id is not None
        else updated.get("accepted_semantic_attempt_id") or previous.get("accepted_semantic_attempt_id") or ""
    )
    if requested and (requested not in attempt_ids or requested not in accepted_ids):
        raise ValueError(f"accepted_semantic_attempt_id points to invalid attempt: {requested}")
    if requested and str(next(item for item in attempts if item["attempt_id"] == requested).get("superseded_by_attempt_id") or ""):
        raise ValueError(f"accepted_semantic_attempt_id points to superseded attempt: {requested}")
    if not requested:
        requested = next(
            (
                str(item["attempt_id"])
                for item in reversed(attempts)
                if item.get("accepted") is True and not str(item.get("superseded_by_attempt_id") or "")
            ),
            "",
        )
    updated["accepted_semantic_attempt_id"] = requested
    return updated


def sanitize_semantic_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitize semantic history nested in a workflow evidence payload."""

    if "semantic_attempts" not in payload and "accepted_semantic_attempt_id" not in payload:
        return dict(payload)
    return merge_semantic_attempt_result(payload)


def _semantic_attempt_record(
    *,
    request: AiClassificationRequest,
    provider: ProductClassificationProvider,
    provider_name: str,
    provider_response: Mapping[str, Any] | None = None,
    accepted_result: AiProviderClassification | None = None,
    validation_errors: Iterable[object] = (),
) -> dict[str, Any]:
    candidate_stage = str(request.context.candidate_strategy.stage or "")
    accepted = (
        accepted_result is not None
        and candidate_stage in {"final_account", "line_batch"}
        and not accepted_result.needs_research
    )
    validated_response: dict[str, Any] = {}
    if request.context.semantic_stage == "research_synthesis":
        validated_response.update(
            {
                "authority": "evidence_only",
                "canonical_line_ids": [
                    str(line.get("canonical_line_id") or "")
                    for line in request.context.canonical_lines
                    if str(line.get("canonical_line_id") or "")
                ],
                "research_evidence": list(request.context.research_evidence),
            }
        )
    if accepted_result is not None:
        validated_response.update({
            "category": accepted_result.category,
            "confidence": accepted_result.confidence,
            "reason": accepted_result.reason,
            "evidence": list(accepted_result.evidence),
            "suggested_account_code": accepted_result.suggested_account_code,
            "suggested_counterparty_code": accepted_result.suggested_counterparty_code,
            "selected_account_families": list(accepted_result.selected_account_families),
            "risk_flags": list(accepted_result.risk_flags),
            "account_reason": accepted_result.account_reason,
            "product_identity": accepted_result.product_identity,
            "needs_research": accepted_result.needs_research,
            "research_query": accepted_result.research_query,
            "line_decisions": list(accepted_result.line_decisions),
        })
    elif provider_response:
        validated_response = {}
    return serialize_semantic_decision_attempt(
        stage=str(request.context.semantic_stage or "initial_account_decision"),
        canonical_line_ids=(
            str(line.get("canonical_line_id") or "")
            for line in request.context.canonical_lines
            if str(line.get("canonical_line_id") or "")
        ),
        prompt_version=_provider_prompt_version(provider),
        provider=provider_name,
        model=_provider_model(provider),
        candidate_account_codes=request.context.account_candidates,
        candidate_counterparty_codes=request.context.counterparty_candidates,
        validated_response=validated_response,
        validation_errors=validation_errors,
        accepted=accepted,
    )


def _ai_trace_record(
    *,
    request: AiClassificationRequest,
    provider: ProductClassificationProvider,
    provider_name: str,
    request_payload: dict[str, object],
    estimated_chars: int,
    validation_status: str,
    provider_response: dict[str, Any] | None = None,
    accepted_result: AiProviderClassification | None = None,
    error: str = "",
) -> dict[str, Any]:
    accepted_payload: dict[str, Any] = {}
    if accepted_result is not None:
        accepted_payload = {
            "category": accepted_result.category,
            "confidence": accepted_result.confidence,
            "reason": accepted_result.reason,
            "selected_account_code": accepted_result.suggested_account_code,
            "selected_counterparty_code": accepted_result.suggested_counterparty_code,
            "selected_account_families": list(accepted_result.selected_account_families),
            "risk_flags": list(accepted_result.risk_flags),
            "account_reason": accepted_result.account_reason,
            "product_identity": accepted_result.product_identity,
            "needs_research": accepted_result.needs_research,
            "research_query": accepted_result.research_query,
            "line_decisions": list(accepted_result.line_decisions),
        }
    return {
        "stage": request.context.candidate_strategy.stage,
        "candidate_strategy": _candidate_strategy_payload(request.context.candidate_strategy),
        "provider": provider_name,
        "model": _provider_model(provider),
        "estimated_input_chars": estimated_chars,
        "system_prompt": _provider_prompt(provider),
        "request_payload": _trace_safe_value(request_payload),
        "output_schema": _trace_safe_value(request_payload.get("output_schema") or {}),
        "provider_response": _trace_safe_value(provider_response or {}),
        "validation_status": validation_status,
        "accepted_result": _trace_safe_value(accepted_payload),
        "error": error[:400],
    }


def _allowed_family_values(request: AiClassificationRequest) -> tuple[str, ...]:
    return _limited_strings(
        [str(candidate.get("family") or "").strip() for candidate in request.context.account_family_candidates],
        limit=max(request.context.account_candidate_limit, 0),
    )


def _validated_families(value: object, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    allowed_set = set(allowed)
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip() in allowed_set))[:8]


def _validated_line_decisions(
    value: object,
    request: AiClassificationRequest,
) -> tuple[dict[str, Any], ...] | None:
    if request.context.candidate_strategy.stage != "line_batch":
        return ()
    if not isinstance(value, list):
        return None
    expected_ids = tuple(
        str(line.get("canonical_line_id") or "")
        for line in request.context.canonical_lines
        if str(line.get("canonical_line_id") or "")
    )
    received_ids = tuple(
        str(item.get("canonical_line_id") or "")
        for item in value
        if isinstance(item, dict)
    )
    if (
        not expected_ids
        or len(value) != len(expected_ids)
        or len(received_ids) != len(expected_ids)
        or len(set(received_ids)) != len(received_ids)
        or set(received_ids) != set(expected_ids)
    ):
        return None
    by_id: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            return None
        line_id = str(item.get("canonical_line_id") or "")
        category = str(item.get("category") or "")
        reason = str(item.get("reason") or "").strip()
        try:
            confidence = int(item.get("confidence", -1))
        except (TypeError, ValueError):
            return None
        if category not in request.allowed_categories or not reason or confidence < 0 or confidence > 100:
            return None
        evidence = (
            _limited_strings(item.get("evidence") or [], limit=5)
            if isinstance(item.get("evidence"), list)
            else ()
        )
        risk_flags = (
            _limited_strings(item.get("risk_flags") or [], limit=8)
            if isinstance(item.get("risk_flags"), list)
            else ()
        )
        by_id[line_id] = {
            "canonical_line_id": line_id,
            "category": category,
            "confidence": confidence,
            "product_identity": str(item.get("product_identity") or "").strip()[:160],
            "suggested_account_code": _validated_suggestion(
                item.get("suggested_account_code"), request.context.account_candidates
            ),
            "reason": reason[:240],
            "evidence": evidence,
            "needs_research": bool(item.get("needs_research")),
            "research_query": str(item.get("research_query") or "").strip()[:160],
            "risk_flags": risk_flags,
        }
    return tuple(by_id[line_id] for line_id in expected_ids)


def _validate_provider_payload(payload: dict[str, Any], request: AiClassificationRequest) -> AiProviderClassification | None:
    category = str(payload.get("category", "")).strip()
    if category not in request.allowed_categories:
        return None
    try:
        confidence = int(payload.get("confidence", -1))
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 100:
        return None
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        return None
    evidence_payload = payload.get("evidence", ())
    if isinstance(evidence_payload, list):
        evidence = tuple(str(item).strip() for item in evidence_payload if str(item).strip())[:5]
    else:
        evidence = ()
    risk_flags = _limited_strings(payload.get("risk_flags") or [], limit=8) if isinstance(payload.get("risk_flags"), list) else ()
    selected_families = _validated_families(payload.get("selected_account_families"), _allowed_family_values(request))
    primary_families = _validated_families(payload.get("primary_account_families"), _allowed_family_values(request))
    alternative_families = _validated_families(payload.get("alternative_account_families"), _allowed_family_values(request))
    resolved_families = tuple(dict.fromkeys((*primary_families, *alternative_families, *selected_families)))
    line_decisions = _validated_line_decisions(payload.get("line_decisions"), request)
    if line_decisions is None:
        return None
    return AiProviderClassification(
        category=category,
        confidence=confidence,
        reason=reason[:240],
        evidence=evidence,
        suggested_account_code=_validated_suggestion(payload.get("suggested_account_code"), request.context.account_candidates),
        suggested_counterparty_code=_validated_suggestion(payload.get("suggested_counterparty_code"), request.context.counterparty_candidates),
        risk_flags=risk_flags,
        account_reason=str(payload.get("account_reason") or "").strip()[:240],
        product_identity=str(payload.get("product_identity") or "").strip()[:160],
        needs_research=bool(payload.get("needs_research")),
        research_query=str(payload.get("research_query") or "").strip()[:160],
        selected_account_families=resolved_families,
        line_decisions=line_decisions,
    )


def _provider_validation_errors(
    payload: Mapping[str, Any],
    request: AiClassificationRequest,
    result: AiProviderClassification | None,
) -> tuple[str, ...]:
    errors: list[str] = []
    if result is None:
        errors.append("invalid_schema")
    allowed = set(request.context.account_candidates)
    attempted = str(payload.get("suggested_account_code") or "").strip()
    if attempted and attempted not in allowed:
        errors.append("selected_account_not_in_candidates")
    for decision in payload.get("line_decisions") or ():
        if not isinstance(decision, Mapping):
            continue
        code = str(decision.get("suggested_account_code") or "").strip()
        if code and code not in allowed:
            errors.append("selected_account_not_in_candidates")
    return tuple(dict.fromkeys(errors))


class StaticFirstClassifier:
    def __init__(
        self,
        provider: ProductClassificationProvider | None = None,
        policy: AiClassificationPolicy | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy or AiClassificationPolicy()
        self.provider_calls = 0

    def classify(
        self,
        raw_line: str,
        *,
        supplier_hint: str = "",
        context: AiClassificationContext | None = None,
    ) -> AiClassificationResult:
        static = classify_product_line(raw_line, supplier_hint)
        estimated_chars = min(len(raw_line) + len(supplier_hint), self.policy.max_input_chars * 2)
        resolved_context = context or AiClassificationContext()

        if (
            resolved_context.semantic_stage == "initial_account_decision"
            and resolved_context.candidate_strategy.stage != "line_batch"
            and static.category != "bilinmeyen"
            and static.confidence >= self.policy.static_confidence_threshold
        ):
            return AiClassificationResult(
                classification=static,
                ai_used=False,
                provider="static_rules",
                skipped_reason="static_high_confidence",
                estimated_input_chars=estimated_chars,
            )
        if not self.policy.enabled:
            return AiClassificationResult(
                classification=static,
                ai_used=False,
                provider="static_rules",
                skipped_reason="ai_disabled",
                estimated_input_chars=estimated_chars,
            )
        if self.provider is None:
            return AiClassificationResult(
                classification=static,
                ai_used=False,
                provider="static_rules",
                skipped_reason="provider_missing",
                estimated_input_chars=estimated_chars,
            )
        if self.policy.max_provider_calls <= 0:
            return AiClassificationResult(
                classification=static,
                ai_used=False,
                provider="static_rules",
                skipped_reason="provider_call_budget_exhausted",
                estimated_input_chars=estimated_chars,
            )

        self.provider_calls += 1
        request = AiClassificationRequest(
            raw_line=raw_line,
            supplier_hint=supplier_hint,
            allowed_categories=ALLOWED_AI_CATEGORIES,
            max_input_chars=self.policy.max_input_chars,
            context=resolved_context,
        )
        request_payload = request.to_schema_payload()
        estimated_chars = len(json.dumps(request_payload, ensure_ascii=False))
        try:
            provider_payload = self.provider.classify_product(request)
        except Exception as exc:  # noqa: BLE001 - provider boundaries must not fail document processing
            provider_name = str(getattr(self.provider, "last_provider_name", "") or self.provider.provider_name)
            provider_error = _provider_error_code(exc)
            semantic_attempt = _semantic_attempt_record(
                request=request,
                provider=self.provider,
                provider_name=provider_name,
                validation_errors=(provider_error,),
            )
            return AiClassificationResult(
                classification=ProductClassification(
                    raw_line=raw_line,
                    category=static.category,
                    confidence=static.confidence,
                    evidence=(*static.evidence, "ai_provider_error"),
                ),
                ai_used=False,
                provider=provider_name,
                skipped_reason="ai_provider_error",
                provider_reason=provider_error,
                estimated_input_chars=estimated_chars,
                risk_flags=("ai_provider_error",),
                candidate_strategy=resolved_context.candidate_strategy,
                ai_trace=(
                    _ai_trace_record(
                        request=request,
                        provider=self.provider,
                        provider_name=provider_name,
                        request_payload=request_payload,
                        estimated_chars=estimated_chars,
                        validation_status="provider_error",
                        error=provider_error,
                    ),
                ),
                semantic_attempts=(semantic_attempt,),
            )
        provider_result = _validate_provider_payload(provider_payload, request)
        provider_name = str(getattr(self.provider, "last_provider_name", "") or self.provider.provider_name)
        validation_errors = _provider_validation_errors(provider_payload, request, provider_result)
        if validation_errors and resolved_context.semantic_stage != "account_correction":
            failed_attempt = _semantic_attempt_record(
                request=request,
                provider=self.provider,
                provider_name=provider_name,
                provider_response=provider_payload,
                validation_errors=validation_errors,
            )
            correction_context = replace(
                resolved_context,
                semantic_stage="account_correction",
                prior_semantic_attempt=failed_attempt,
                validation_errors=validation_errors,
            )
            correction_request = AiClassificationRequest(
                raw_line=raw_line,
                supplier_hint=supplier_hint,
                allowed_categories=ALLOWED_AI_CATEGORIES,
                max_input_chars=self.policy.max_input_chars,
                context=correction_context,
            )
            correction_payload = correction_request.to_schema_payload()
            self.provider_calls += 1
            try:
                correction_response = self.provider.classify_product(correction_request)
                correction_result = _validate_provider_payload(correction_response, correction_request)
                correction_errors = _provider_validation_errors(
                    correction_response,
                    correction_request,
                    correction_result,
                )
            except Exception as exc:  # noqa: BLE001
                correction_response = {}
                correction_result = None
                correction_errors = (_provider_error_code(exc),)
            correction_attempt = _semantic_attempt_record(
                request=correction_request,
                provider=self.provider,
                provider_name=str(getattr(self.provider, "last_provider_name", "") or self.provider.provider_name),
                provider_response=correction_response,
                accepted_result=correction_result if not correction_errors else None,
                validation_errors=correction_errors,
            )
            if correction_attempt.get("accepted"):
                failed_attempt = {**failed_attempt, "superseded_by_attempt_id": correction_attempt["attempt_id"]}
                correction_trace = _ai_trace_record(
                    request=correction_request,
                    provider=self.provider,
                    provider_name=str(getattr(self.provider, "last_provider_name", "") or self.provider.provider_name),
                    request_payload=correction_payload,
                    estimated_chars=len(json.dumps(correction_payload, ensure_ascii=False)),
                    validation_status="accepted",
                    provider_response=correction_response,
                    accepted_result=correction_result,
                )
                assert correction_result is not None
                return AiClassificationResult(
                    classification=ProductClassification(
                        raw_line=raw_line,
                        category=correction_result.category,
                        confidence=correction_result.confidence,
                        evidence=(*correction_result.evidence, "ai_schema_validated"),
                    ),
                    ai_used=True,
                    provider=str(getattr(self.provider, "last_provider_name", "") or self.provider.provider_name),
                    provider_reason=correction_result.reason,
                    estimated_input_chars=estimated_chars,
                    suggested_account_code=correction_result.suggested_account_code,
                    suggested_counterparty_code=correction_result.suggested_counterparty_code,
                    risk_flags=correction_result.risk_flags,
                    account_reason=correction_result.account_reason,
                    product_identity=correction_result.product_identity,
                    needs_research=correction_result.needs_research,
                    research_query=correction_result.research_query,
                    selected_account_families=correction_result.selected_account_families,
                    candidate_strategy=resolved_context.candidate_strategy,
                    ai_trace=(
                        _ai_trace_record(
                            request=request,
                            provider=self.provider,
                            provider_name=provider_name,
                            request_payload=request_payload,
                            estimated_chars=estimated_chars,
                            validation_status="invalid_schema" if validation_errors == ("invalid_schema",) else "candidate_rejected",
                            provider_response=provider_payload,
                        ),
                        correction_trace,
                    ),
                    semantic_attempts=(failed_attempt, correction_attempt),
                    accepted_semantic_attempt_id=str(correction_attempt["attempt_id"]),
                    line_decisions=correction_result.line_decisions,
                )
            provider_result = None
            validation_errors = tuple(dict.fromkeys((*validation_errors, *correction_errors)))
            semantic_attempt = failed_attempt
            correction_trace = _ai_trace_record(
                request=correction_request,
                provider=self.provider,
                provider_name=str(getattr(self.provider, "last_provider_name", "") or self.provider.provider_name),
                request_payload=correction_payload,
                estimated_chars=len(json.dumps(correction_payload, ensure_ascii=False)),
                validation_status="invalid_schema",
                provider_response=correction_response,
            )
            return AiClassificationResult(
                classification=ProductClassification(
                    raw_line=raw_line,
                    category=static.category,
                    confidence=static.confidence,
                    evidence=(*static.evidence, "ai_invalid_schema"),
                ),
                ai_used=True,
                provider=provider_name,
                provider_reason=validation_errors[0],
                estimated_input_chars=estimated_chars,
                candidate_strategy=resolved_context.candidate_strategy,
                ai_trace=(
                    _ai_trace_record(
                        request=request,
                        provider=self.provider,
                        provider_name=provider_name,
                        request_payload=request_payload,
                        estimated_chars=estimated_chars,
                        validation_status="invalid_schema" if validation_errors == ("invalid_schema",) else "candidate_rejected",
                        provider_response=provider_payload,
                    ),
                    correction_trace,
                ),
                semantic_attempts=(semantic_attempt, correction_attempt),
            )
        if provider_result is None:
            semantic_attempt = _semantic_attempt_record(
                request=request,
                provider=self.provider,
                provider_name=provider_name,
                provider_response=provider_payload,
                validation_errors=validation_errors or ("invalid_schema",),
            )
            return AiClassificationResult(
                classification=ProductClassification(
                    raw_line=raw_line,
                    category=static.category,
                    confidence=static.confidence,
                    evidence=(*static.evidence, "ai_invalid_schema"),
                ),
                ai_used=True,
                provider=provider_name,
                skipped_reason="",
                provider_reason="AI response schema validation failed.",
                estimated_input_chars=estimated_chars,
                candidate_strategy=resolved_context.candidate_strategy,
                ai_trace=(
                    _ai_trace_record(
                        request=request,
                        provider=self.provider,
                        provider_name=provider_name,
                        request_payload=request_payload,
                        estimated_chars=estimated_chars,
                        validation_status="invalid_schema",
                        provider_response=provider_payload,
                    ),
                ),
                semantic_attempts=(semantic_attempt,),
            )

        semantic_attempt = _semantic_attempt_record(
            request=request,
            provider=self.provider,
            provider_name=provider_name,
            provider_response=provider_payload,
            accepted_result=provider_result,
        )
        return AiClassificationResult(
            classification=ProductClassification(
                raw_line=raw_line,
                category=provider_result.category,
                confidence=provider_result.confidence,
                evidence=(*provider_result.evidence, "ai_schema_validated"),
            ),
            ai_used=True,
            provider=provider_name,
            provider_reason=provider_result.reason,
            estimated_input_chars=estimated_chars,
            suggested_account_code=provider_result.suggested_account_code,
            suggested_counterparty_code=provider_result.suggested_counterparty_code,
            risk_flags=provider_result.risk_flags,
            account_reason=provider_result.account_reason,
            product_identity=provider_result.product_identity,
            needs_research=provider_result.needs_research,
            research_query=provider_result.research_query,
            selected_account_families=provider_result.selected_account_families,
            candidate_strategy=resolved_context.candidate_strategy,
            ai_trace=(
                _ai_trace_record(
                    request=request,
                    provider=self.provider,
                    provider_name=provider_name,
                    request_payload=request_payload,
                    estimated_chars=estimated_chars,
                    validation_status="accepted",
                    provider_response=provider_payload,
                    accepted_result=provider_result,
                ),
            ),
            semantic_attempts=(semantic_attempt,),
            accepted_semantic_attempt_id=(
                str(semantic_attempt["attempt_id"]) if semantic_attempt["accepted"] else ""
            ),
            line_decisions=provider_result.line_decisions,
        )


def classify_product_static_first(raw_line: str, *, supplier_hint: str = "") -> AiClassificationResult:
    return StaticFirstClassifier().classify(raw_line, supplier_hint=supplier_hint)
