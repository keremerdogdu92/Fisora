from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.ai_classification import (
    AiClassificationPolicy,
    AiClassificationRequest,
    StaticFirstClassifier,
)


@dataclass(frozen=True)
class AiBenchmarkCase:
    case_id: str
    raw_line: str
    supplier_hint: str = ""
    expected_category: str = ""


@dataclass(frozen=True)
class AiBenchmarkCaseResult:
    case_id: str
    raw_line: str
    expected_category: str
    predicted_category: str
    confidence: int
    ai_used: bool
    provider: str
    matched_expected: bool | None
    estimated_input_chars: int
    skipped_reason: str
    provider_reason: str


@dataclass(frozen=True)
class AiBenchmarkSummary:
    case_count: int
    ai_used_count: int
    matched_count: int
    evaluated_count: int
    accuracy_percent: int
    estimated_input_chars: int
    provider: str
    results: tuple[AiBenchmarkCaseResult, ...]


class ReplayClassificationProvider:
    def __init__(self, payloads: list[dict[str, Any]], *, provider_name: str = "replay_provider") -> None:
        self.provider_name = provider_name
        self.payloads = payloads
        self.index = 0

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        if self.index >= len(self.payloads):
            return {
                "category": "bilinmeyen",
                "confidence": 0,
                "reason": "Replay payload missing.",
                "evidence": ["replay_missing"],
            }
        payload = self.payloads[self.index]
        self.index += 1
        return payload


def run_ai_batch_benchmark(
    cases: tuple[AiBenchmarkCase, ...],
    *,
    policy: AiClassificationPolicy | None = None,
    provider_payloads: list[dict[str, Any]] | None = None,
    provider_name: str = "static_rules",
) -> AiBenchmarkSummary:
    provider = ReplayClassificationProvider(provider_payloads or [], provider_name=provider_name) if provider_payloads else None
    classifier = StaticFirstClassifier(provider=provider, policy=policy or AiClassificationPolicy())
    results: list[AiBenchmarkCaseResult] = []
    for case in cases:
        classification = classifier.classify(case.raw_line, supplier_hint=case.supplier_hint)
        predicted = classification.classification.category
        matched_expected = None
        if case.expected_category:
            matched_expected = predicted == case.expected_category
        results.append(
            AiBenchmarkCaseResult(
                case_id=case.case_id,
                raw_line=case.raw_line,
                expected_category=case.expected_category,
                predicted_category=predicted,
                confidence=classification.classification.confidence,
                ai_used=classification.ai_used,
                provider=classification.provider,
                matched_expected=matched_expected,
                estimated_input_chars=classification.estimated_input_chars,
                skipped_reason=classification.skipped_reason,
                provider_reason=classification.provider_reason,
            )
        )
    evaluated = [result for result in results if result.matched_expected is not None]
    matched_count = sum(1 for result in evaluated if result.matched_expected)
    accuracy = int(round((matched_count / len(evaluated)) * 100)) if evaluated else 0
    return AiBenchmarkSummary(
        case_count=len(results),
        ai_used_count=sum(1 for result in results if result.ai_used),
        matched_count=matched_count,
        evaluated_count=len(evaluated),
        accuracy_percent=accuracy,
        estimated_input_chars=sum(result.estimated_input_chars for result in results),
        provider=provider_name if provider else "static_rules",
        results=tuple(results),
    )
