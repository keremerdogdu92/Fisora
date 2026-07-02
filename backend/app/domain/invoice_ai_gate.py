from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvoiceAiGateDecision:
    needs_ai: bool
    reason: str
    allow_ai_account_override: bool
    allow_research_after_ai: bool


def invoice_ai_gate(
    *,
    product_category: str,
    product_confidence: int,
    business_relation: str,
    account_treatment: str,
    line_hint: str,
    hard_rule_reason_codes: tuple[str, ...] = (),
) -> InvoiceAiGateDecision:
    if hard_rule_reason_codes:
        return InvoiceAiGateDecision(False, "hard_rule_applied", False, False)

    category = str(product_category or "").strip()
    relation = str(business_relation or "").strip()
    treatment = str(account_treatment or "").strip()
    normalized = " ".join(str(line_hint or "").lower().split())
    vague_terms = {"bedel", "hizmet", "mal", "urun", "ürün", "muhtelif", "islem", "işlem"}
    vague = normalized in vague_terms

    if category in {"", "bilinmeyen", "not_assessed"}:
        return InvoiceAiGateDecision(True, "unknown_product_category", True, True)
    if product_confidence < 70:
        return InvoiceAiGateDecision(True, "low_product_confidence", True, True)
    if relation == "weak_match":
        return InvoiceAiGateDecision(True, "weak_business_match", True, True)
    if treatment == "manual_review":
        return InvoiceAiGateDecision(True, "manual_review_treatment", True, True)
    if relation == "core_business" and treatment == "stock_or_cogs":
        return InvoiceAiGateDecision(True, "cold_start_core_accounting_line", True, False)
    if vague:
        return InvoiceAiGateDecision(True, "vague_line", True, True)
    return InvoiceAiGateDecision(False, "static_confident", False, False)
