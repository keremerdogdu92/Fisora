from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol
import re

from app.domain.statement_lines import StatementLine


ALLOWED_STATEMENT_TRANSACTION_TYPES = (
    "bank_fee",
    "bank_transfer_in",
    "bank_transfer_out",
    "card_payment",
    "counterparty_collection",
    "counterparty_payment",
    "internal_transfer",
    "loan_disbursement",
    "loan_payment",
    "pos_blocked",
    "pos_collection",
    "refund_or_reversal",
    "salary_payment",
    "sgk_payment",
    "suggested_by_import",
    "tax_payment",
    "unknown",
)
AI_REVIEW_FLAGS = {
    "counterparty_match_review_required",
    "counterparty_not_found",
    "learning_rule_review_required",
    "reversal_review_required",
    "statement_review_required",
    "transfer_review_required",
}
ACCOUNT_CODE_RE = re.compile(r"^\d{3}(?:\.\d{1,4}){0,5}$")


@dataclass(frozen=True)
class StatementAiSuggestionPolicy:
    enabled: bool = False
    confidence_threshold: int = 70
    max_input_chars: int = 420
    max_provider_calls: int = 3


@dataclass(frozen=True)
class StatementAiSuggestionRequest:
    line_no: int
    transaction_date: str
    description: str
    amount: str
    direction: str
    current_transaction_type: str
    current_suggested_account_code: str
    current_confidence: int
    risk_flags: tuple[str, ...]
    review_reason: str
    max_input_chars: int

    def to_schema_payload(self) -> dict[str, object]:
        return {
            "line_no": self.line_no,
            "transaction_date": self.transaction_date,
            "description": self.description[: self.max_input_chars].strip(),
            "amount": self.amount,
            "direction": self.direction,
            "current_transaction_type": self.current_transaction_type,
            "current_suggested_account_code": self.current_suggested_account_code,
            "current_confidence": self.current_confidence,
            "risk_flags": list(self.risk_flags),
            "review_reason": self.review_reason[:240],
            "allowed_transaction_types": list(ALLOWED_STATEMENT_TRANSACTION_TYPES),
            "output_schema": {
                "type": "object",
                "required": ["transaction_type", "suggested_account_code", "confidence", "reason"],
                "properties": {
                    "transaction_type": {
                        "type": "string",
                        "enum": list(ALLOWED_STATEMENT_TRANSACTION_TYPES),
                    },
                    "suggested_account_code": {
                        "type": "string",
                        "pattern": r"^\d{3}(?:\.\d{1,4}){0,5}$|^$",
                    },
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string", "maxLength": 240},
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "risk_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                },
                "additionalProperties": False,
            },
        }


@dataclass(frozen=True)
class StatementAiSuggestion:
    line_no: int
    transaction_type: str
    suggested_account_code: str
    confidence: int
    reason: str
    evidence: tuple[str, ...]
    risk_flags: tuple[str, ...]
    ai_used: bool
    provider: str
    skipped_reason: str = ""
    export_allowed: bool = False


@dataclass(frozen=True)
class StatementAiSuggestionBatch:
    suggestions: tuple[StatementAiSuggestion, ...]
    ai_used_count: int
    skipped_count: int
    invalid_schema_count: int
    estimated_input_chars: int
    provider: str


class StatementSuggestionProvider(Protocol):
    provider_name: str

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        ...


class ReplayStatementSuggestionProvider:
    def __init__(self, payloads: list[dict[str, Any]], *, provider_name: str = "replay_provider") -> None:
        self.payloads = list(payloads)
        self.provider_name = provider_name
        self.calls = 0

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        if self.calls >= len(self.payloads):
            self.calls += 1
            return {}
        payload = self.payloads[self.calls]
        self.calls += 1
        return payload


def _line_needs_ai(line: StatementLine, policy: StatementAiSuggestionPolicy) -> bool:
    if line.transaction_type == "unknown":
        return True
    if line.confidence < policy.confidence_threshold:
        return True
    return bool(set(line.risk_flags) & AI_REVIEW_FLAGS)


def _request_from_line(line: StatementLine, policy: StatementAiSuggestionPolicy) -> StatementAiSuggestionRequest:
    return StatementAiSuggestionRequest(
        line_no=line.line_no,
        transaction_date=line.transaction_date,
        description=line.description,
        amount=line.amount,
        direction=line.direction,
        current_transaction_type=line.transaction_type,
        current_suggested_account_code=line.suggested_account_code,
        current_confidence=line.confidence,
        risk_flags=line.risk_flags,
        review_reason=line.review_reason,
        max_input_chars=policy.max_input_chars,
    )


def _validated_suggestion(
    *,
    line: StatementLine,
    provider: str,
    payload: dict[str, Any],
) -> StatementAiSuggestion | None:
    transaction_type = str(payload.get("transaction_type") or "").strip()
    if transaction_type not in ALLOWED_STATEMENT_TRANSACTION_TYPES:
        return None
    suggested_account_code = str(payload.get("suggested_account_code") or "").strip()
    if suggested_account_code and ACCOUNT_CODE_RE.match(suggested_account_code) is None:
        return None
    try:
        confidence = int(payload.get("confidence", -1))
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 100:
        return None
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return None
    evidence_payload = payload.get("evidence") or ()
    evidence = _string_tuple(evidence_payload, limit=5)
    risk_flags = _string_tuple(payload.get("risk_flags") or line.risk_flags, limit=8)
    return StatementAiSuggestion(
        line_no=line.line_no,
        transaction_type=transaction_type,
        suggested_account_code=suggested_account_code,
        confidence=confidence,
        reason=reason[:240],
        evidence=(*evidence, "ai_schema_validated"),
        risk_flags=risk_flags,
        ai_used=True,
        provider=provider,
        export_allowed=False,
    )


def _invalid_schema_suggestion(line: StatementLine, *, provider: str) -> StatementAiSuggestion:
    return StatementAiSuggestion(
        line_no=line.line_no,
        transaction_type=line.transaction_type,
        suggested_account_code=line.suggested_account_code,
        confidence=line.confidence,
        reason="AI response schema validation failed.",
        evidence=("ai_invalid_schema",),
        risk_flags=tuple(dict.fromkeys((*line.risk_flags, "ai_invalid_schema"))),
        ai_used=True,
        provider=provider,
        export_allowed=False,
    )


def _provider_error_suggestion(line: StatementLine, *, provider: str) -> StatementAiSuggestion:
    return StatementAiSuggestion(
        line_no=line.line_no,
        transaction_type=line.transaction_type,
        suggested_account_code=line.suggested_account_code,
        confidence=line.confidence,
        reason="AI provider unavailable; static statement result kept for accountant review.",
        evidence=("ai_provider_error",),
        risk_flags=tuple(dict.fromkeys((*line.risk_flags, "ai_provider_error"))),
        ai_used=False,
        provider=provider,
        skipped_reason="ai_provider_error",
        export_allowed=False,
    )


def _string_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())[:limit]


def suggest_statement_lines(
    lines: Iterable[StatementLine],
    *,
    provider: StatementSuggestionProvider | None = None,
    policy: StatementAiSuggestionPolicy | None = None,
) -> StatementAiSuggestionBatch:
    resolved_policy = policy or StatementAiSuggestionPolicy()
    provider_name = provider.provider_name if provider is not None else "static_statement_rules"
    suggestions: list[StatementAiSuggestion] = []
    skipped_count = 0
    invalid_schema_count = 0
    estimated_input_chars = 0
    provider_calls = 0
    for line in lines:
        estimated_input_chars += min(
            len(line.description) + len(line.amount) + len(line.direction),
            resolved_policy.max_input_chars,
        )
        if not _line_needs_ai(line, resolved_policy):
            skipped_count += 1
            continue
        if not resolved_policy.enabled or provider is None:
            skipped_count += 1
            continue
        if provider_calls >= resolved_policy.max_provider_calls:
            skipped_count += 1
            continue
        provider_calls += 1
        try:
            payload = provider.suggest_statement_line(_request_from_line(line, resolved_policy))
        except Exception:  # noqa: BLE001 - provider boundaries must not fail document processing
            suggestions.append(_provider_error_suggestion(line, provider=provider.provider_name))
            continue
        suggestion = _validated_suggestion(line=line, provider=provider.provider_name, payload=payload)
        if suggestion is None:
            invalid_schema_count += 1
            suggestion = _invalid_schema_suggestion(line, provider=provider.provider_name)
        suggestions.append(suggestion)
    return StatementAiSuggestionBatch(
        suggestions=tuple(suggestions),
        ai_used_count=sum(1 for suggestion in suggestions if suggestion.ai_used),
        skipped_count=skipped_count,
        invalid_schema_count=invalid_schema_count,
        estimated_input_chars=estimated_input_chars,
        provider=provider_name,
    )


def statement_ai_suggestion_payload(suggestion: StatementAiSuggestion) -> dict[str, object]:
    return {
        "line_no": suggestion.line_no,
        "transaction_type": suggestion.transaction_type,
        "suggested_account_code": suggestion.suggested_account_code,
        "confidence": suggestion.confidence,
        "reason": suggestion.reason,
        "evidence": list(suggestion.evidence),
        "risk_flags": list(suggestion.risk_flags),
        "ai_used": suggestion.ai_used,
        "provider": suggestion.provider,
        "skipped_reason": suggestion.skipped_reason,
        "export_allowed": suggestion.export_allowed,
    }


def statement_ai_batch_payload(batch: StatementAiSuggestionBatch) -> dict[str, object]:
    return {
        "suggestions": [statement_ai_suggestion_payload(suggestion) for suggestion in batch.suggestions],
        "ai_used_count": batch.ai_used_count,
        "skipped_count": batch.skipped_count,
        "invalid_schema_count": batch.invalid_schema_count,
        "estimated_input_chars": batch.estimated_input_chars,
        "provider": batch.provider,
    }
