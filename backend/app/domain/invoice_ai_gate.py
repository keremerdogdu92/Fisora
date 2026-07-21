from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

AccountingDirection = Literal["purchase", "sales"]
InvoiceMode = Literal["ordinary", "return"]
SemanticRole = Literal["expense", "stock", "revenue", "non_deductible"]


@dataclass(frozen=True)
class VerifiedRuleAuthorityV1:
    """Immutable capability proving a reviewed rule may own one canonical line."""

    schema_version: Literal["v1"]
    client_id: str
    rule_id: str
    rule_version: str
    activation_event_id: str
    source_review_decision_id: str
    confirmed_actor_id: str
    canonical_line_id: str
    direction: AccountingDirection
    invoice_mode: InvoiceMode
    semantic_role: SemanticRole
    account_code: str


@dataclass(frozen=True)
class AcceptedSemanticAttemptRef:
    attempt_id: str


@dataclass(frozen=True)
class LineAccountAuthority:
    canonical_line_id: str
    account_code: str
    semantic_role: str
    source: Literal["verified_rule", "accepted_ai"]
    source_id: str


@dataclass(frozen=True)
class SemanticAccountAuthoritySet:
    line_authorities: tuple[LineAccountAuthority, ...] = ()
    accepted_attempt: AcceptedSemanticAttemptRef | None = None

    def account_by_line(self) -> dict[str, LineAccountAuthority]:
        return {item.canonical_line_id: item for item in self.line_authorities}

    def exactly_covers(self, canonical_line_ids: tuple[str, ...]) -> bool:
        expected = tuple(line_id for line_id in canonical_line_ids if line_id)
        actual = tuple(item.canonical_line_id for item in self.line_authorities)
        return (
            bool(expected)
            and len(actual) == len(expected)
            and len(set(actual)) == len(actual)
            and set(actual) == set(expected)
        )


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
    canonical_line_ids: tuple[str, ...] = (),
    verified_rule_bindings: tuple[Mapping[str, object], ...] = (),
    semantic_authority: SemanticAccountAuthoritySet | None = None,
) -> InvoiceAiGateDecision:
    expected_line_ids = tuple(str(line_id or "").strip() for line_id in canonical_line_ids if str(line_id or "").strip())
    # Raw dictionaries are retained only as a compatibility-shaped input and
    # deliberately carry no authority. A caller must present a typed capability.
    del verified_rule_bindings
    verified_binding_covers_lines = bool(
        semantic_authority and semantic_authority.exactly_covers(expected_line_ids)
    )
    if verified_binding_covers_lines:
        return InvoiceAiGateDecision(False, "verified_rule_binding", False, False)

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
    if hard_rule_reason_codes:
        return InvoiceAiGateDecision(True, "semantic_ai_required_with_hard_rule", True, False)
    return InvoiceAiGateDecision(True, "cold_start_semantic_authority_required", True, False)
