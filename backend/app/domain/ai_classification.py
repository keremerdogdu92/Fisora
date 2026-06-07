from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.business_relevance import (
    GENERAL_EXPENSE_CATEGORIES,
    HEARING_CENTER_CATEGORIES,
    PERSONAL_USE_CATEGORIES,
    ProductClassification,
    classify_product_line,
)


ALLOWED_AI_CATEGORIES = tuple(
    sorted(
        {
            *GENERAL_EXPENSE_CATEGORIES,
            *HEARING_CENTER_CATEGORIES,
            *PERSONAL_USE_CATEGORIES,
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


@dataclass(frozen=True)
class AiClassificationContext:
    client_activity: str = ""
    account_candidates: tuple[str, ...] = ()
    counterparty_candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class AiClassificationRequest:
    raw_line: str
    supplier_hint: str
    allowed_categories: tuple[str, ...]
    max_input_chars: int
    context: AiClassificationContext = AiClassificationContext()

    def to_schema_payload(self) -> dict[str, object]:
        account_candidates = _limited_strings(self.context.account_candidates, limit=12)
        counterparty_candidates = _limited_strings(self.context.counterparty_candidates, limit=12)
        return {
            "raw_line": self.raw_line[: self.max_input_chars].strip(),
            "supplier_hint": self.supplier_hint[: self.max_input_chars].strip(),
            "client_activity": self.context.client_activity[: self.max_input_chars].strip(),
            "account_candidates": list(account_candidates),
            "counterparty_candidates": list(counterparty_candidates),
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


def _validate_provider_payload(payload: dict[str, Any], request: AiClassificationRequest) -> AiProviderClassification | None:
    category = str(payload.get("category", "")).strip()
    if category not in ALLOWED_AI_CATEGORIES:
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
    return AiProviderClassification(
        category=category,
        confidence=confidence,
        reason=reason[:240],
        evidence=evidence,
        suggested_account_code=_validated_suggestion(payload.get("suggested_account_code"), request.context.account_candidates),
        suggested_counterparty_code=_validated_suggestion(payload.get("suggested_counterparty_code"), request.context.counterparty_candidates),
        risk_flags=risk_flags,
        account_reason=str(payload.get("account_reason") or "").strip()[:240],
    )


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

        if static.category != "bilinmeyen" and static.confidence >= self.policy.static_confidence_threshold:
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
        if self.provider_calls >= self.policy.max_provider_calls:
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
        provider_payload = self.provider.classify_product(request)
        provider_result = _validate_provider_payload(provider_payload, request)
        if provider_result is None:
            return AiClassificationResult(
                classification=ProductClassification(
                    raw_line=raw_line,
                    category=static.category,
                    confidence=static.confidence,
                    evidence=(*static.evidence, "ai_invalid_schema"),
                ),
                ai_used=True,
                provider=self.provider.provider_name,
                skipped_reason="",
                provider_reason="AI response schema validation failed.",
                estimated_input_chars=estimated_chars,
            )

        return AiClassificationResult(
            classification=ProductClassification(
                raw_line=raw_line,
                category=provider_result.category,
                confidence=provider_result.confidence,
                evidence=(*provider_result.evidence, "ai_schema_validated"),
            ),
            ai_used=True,
            provider=self.provider.provider_name,
            provider_reason=provider_result.reason,
            estimated_input_chars=estimated_chars,
            suggested_account_code=provider_result.suggested_account_code,
            suggested_counterparty_code=provider_result.suggested_counterparty_code,
            risk_flags=provider_result.risk_flags,
            account_reason=provider_result.account_reason,
        )


def classify_product_static_first(raw_line: str, *, supplier_hint: str = "") -> AiClassificationResult:
    return StaticFirstClassifier().classify(raw_line, supplier_hint=supplier_hint)
