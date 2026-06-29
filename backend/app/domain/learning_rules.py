from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from app.domain.learning_intelligence import normalize_text, normalized_terms
from app.domain.matching_simulation import SimulatedInvoiceResult
from app.domain.review_learning import LearningEvent


LEARNING_APPLIED_EVIDENCE = "learning_rule_applied"


@dataclass(frozen=True)
class LearnedPostingRule:
    scope: str
    action: str
    category: str
    corrected_account_code: str = ""
    corrected_counterparty_code: str = ""
    reason: str = ""
    automation_candidate: bool = False
    accounting_intent: str = ""
    accounting_intent_confidence: int = 0
    normalized_terms: tuple[str, ...] = ()
    source_summary: str = ""
    rule_prompt: dict[str, object] | None = None
    natural_language_rule_candidate: dict[str, object] | None = None


def rule_from_learning_event(event: LearningEvent) -> LearnedPostingRule:
    return LearnedPostingRule(
        scope=event.scope,
        action=event.action,
        category=event.category,
        corrected_account_code=event.corrected_account_code,
        corrected_counterparty_code=event.corrected_counterparty_code,
        reason=event.reason,
        automation_candidate=event.automation_candidate,
    )


def rule_from_event_payload(event: dict[str, object]) -> LearnedPostingRule:
    return LearnedPostingRule(
        scope=str(event.get("scope") or "general_candidate"),
        action=str(event.get("action") or ""),
        category=str(event.get("category") or ""),
        corrected_account_code=str(event.get("corrected_account_code") or ""),
        corrected_counterparty_code=str(event.get("corrected_counterparty_code") or ""),
        reason=str(event.get("reason") or ""),
        automation_candidate=bool(event.get("automation_candidate")),
        accounting_intent=str(event.get("accounting_intent") or ""),
        accounting_intent_confidence=int(event.get("accounting_intent_confidence") or 0),
        normalized_terms=tuple(str(term) for term in event.get("normalized_terms") or () if str(term).strip()),
        source_summary=str(event.get("learning_rule_source_summary") or ""),
        rule_prompt=event.get("rule_prompt") if isinstance(event.get("rule_prompt"), dict) else None,
        natural_language_rule_candidate=(
            event.get("natural_language_rule_candidate") if isinstance(event.get("natural_language_rule_candidate"), dict) else None
        ),
    )


def apply_learning_rules(
    result: SimulatedInvoiceResult,
    rules: Iterable[LearnedPostingRule],
) -> SimulatedInvoiceResult:
    rule = _select_rule(result, rules)
    if rule is None:
        return result

    draft_lines = tuple(_apply_rule_to_line(line, result, rule) for line in result.draft_lines)
    evidence = tuple(dict.fromkeys((*result.business_relevance_evidence, LEARNING_APPLIED_EVIDENCE)))
    review_reasons = tuple(dict.fromkeys((*result.review_reason_codes, "learning_rule_review_required")))
    reason = rule.source_summary or rule.reason
    return replace(
        result,
        selected_expense_account=rule.corrected_account_code or result.selected_expense_account,
        selected_supplier_account=rule.corrected_counterparty_code or result.selected_supplier_account,
        business_relevance_evidence=evidence,
        review_reason_codes=review_reasons,
        learning_rule_applied=True,
        learning_rule_scope=rule.scope,
        learning_rule_reason=reason,
        learning_rule_source_summary=reason,
        accounting_intent=rule.accounting_intent,
        accounting_intent_confidence=rule.accounting_intent_confidence,
        rule_prompt=rule.rule_prompt or {},
        simulated_status="review_required",
        export_status="review_required",
        export_gate_reason=reason or "Onceki musavir karari benzerlik nedeniyle review gerektiriyor.",
        draft_lines=draft_lines,
    )


def _select_rule(result: SimulatedInvoiceResult, rules: Iterable[LearnedPostingRule]) -> LearnedPostingRule | None:
    allowed_actions = {"approve", "approve_with_changes", "suggest_for_similar"}
    scored: list[tuple[int, LearnedPostingRule]] = []
    for rule in rules:
        if rule.action not in allowed_actions:
            continue
        if (
            rule.natural_language_rule_candidate
            and rule.natural_language_rule_candidate.get("requires_review")
            and rule.action != "suggest_for_similar"
        ):
            continue
        if not rule.corrected_account_code and not rule.corrected_counterparty_code:
            continue
        score = _rule_score(result, rule)
        if score >= 60:
            scored.append((score, rule))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _rule_score(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> int:
    score = 0
    if rule.category and rule.category == result.product_category:
        score += 50
    haystack = normalize_text(
        " ".join(
            (
                result.product_line_hint,
                result.provider_hint,
                result.product_category,
                result.invoice_type,
            )
        )
    )
    haystack_terms = set(normalized_terms(haystack, limit=20))
    if rule.accounting_intent:
        intent_terms = set(normalized_terms(rule.accounting_intent.replace("_", " "), limit=8))
        if intent_terms & haystack_terms:
            score += 40
    overlap = len(set(rule.normalized_terms) & haystack_terms)
    score += min(overlap * 15, 45)
    if rule.corrected_account_code and rule.corrected_account_code[:3] == result.selected_expense_account[:3]:
        score += 10
    return score


def _apply_rule_to_line(
    line: dict[str, str],
    result: SimulatedInvoiceResult,
    rule: LearnedPostingRule,
) -> dict[str, str]:
    updated = dict(line)
    if rule.corrected_account_code and line["account_code"] == result.selected_expense_account:
        updated["account_code"] = rule.corrected_account_code
    if rule.corrected_counterparty_code and line["account_code"] == result.selected_supplier_account:
        updated["account_code"] = rule.corrected_counterparty_code
    return updated
