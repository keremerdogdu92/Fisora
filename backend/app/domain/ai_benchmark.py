from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.ai_classification import (
    AiClassificationPolicy,
    AiClassificationRequest,
    ProductClassificationProvider,
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


DEFAULT_AI_BENCHMARK_CASES: tuple[AiBenchmarkCase, ...] = (
    AiBenchmarkCase("hearing-rexton", "Rexton RLi 20", "Rexton Medikal", "isitme_cihazi"),
    AiBenchmarkCase("hearing-device-battery", "13 numara pil blister", "Medikal Tedarik", "isitme_cihazi_pili"),
    AiBenchmarkCase("personal-urban-care", "Urban Care sac bakim seti", "Market Tedarik", "kisisel_bakim_kozmetik"),
    AiBenchmarkCase("personal-shampoo-brand", "Argan shampoo repair set", "Kozmetik Magaza", "kisisel_bakim_kozmetik"),
    AiBenchmarkCase("general-efatura", "QNB eFinans e-fatura kontor paketi", "QNB eFinans", "e_fatura_hizmeti"),
    AiBenchmarkCase("general-cloud", "AWS hosting aylik kullanim", "Amazon Web Services", "bulut_yazilim_hizmeti"),
    AiBenchmarkCase("general-electric", "Elektrik tuketim bedeli", "Elektrik Dagitim", "elektrik"),
    AiBenchmarkCase("general-internet", "Fiber internet hizmet bedeli", "Turk Telekom", "internet"),
    AiBenchmarkCase("statement-tax", "GIB ODEME 2026/05", "Banka ekstresi", "bilinmeyen"),
    AiBenchmarkCase("unknown-model", "ZX Sonic Pro 9 receiver unit", "Medikal Tedarik", "bilinmeyen"),
)


def default_ai_benchmark_cases() -> tuple[AiBenchmarkCase, ...]:
    return DEFAULT_AI_BENCHMARK_CASES


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
    provider: ProductClassificationProvider | None = None,
    provider_payloads: list[dict[str, Any]] | None = None,
    provider_name: str = "static_rules",
) -> AiBenchmarkSummary:
    if not cases:
        cases = DEFAULT_AI_BENCHMARK_CASES
    resolved_provider = provider or (
        ReplayClassificationProvider(provider_payloads or [], provider_name=provider_name)
        if provider_payloads
        else None
    )
    classifier = StaticFirstClassifier(provider=resolved_provider, policy=policy or AiClassificationPolicy())
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
        provider=provider_name if resolved_provider else "static_rules",
        results=tuple(results),
    )
