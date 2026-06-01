from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.business_relevance import ProductClassification, classify_product_line


@dataclass(frozen=True)
class AiClassificationResult:
    classification: ProductClassification
    ai_used: bool
    provider: str


class ProductClassifier(Protocol):
    def classify(self, raw_line: str, *, supplier_hint: str = "") -> AiClassificationResult:
        ...


class StaticFirstClassifier:
    def classify(self, raw_line: str, *, supplier_hint: str = "") -> AiClassificationResult:
        classification = classify_product_line(raw_line, supplier_hint)
        return AiClassificationResult(
            classification=classification,
            ai_used=False,
            provider="static_rules",
        )


def classify_product_static_first(raw_line: str, *, supplier_hint: str = "") -> AiClassificationResult:
    return StaticFirstClassifier().classify(raw_line, supplier_hint=supplier_hint)
