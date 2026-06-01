from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

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


def apply_learning_rules(
    result: SimulatedInvoiceResult,
    rules: Iterable[LearnedPostingRule],
) -> SimulatedInvoiceResult:
    rule = _select_rule(result.product_category, rules)
    if rule is None:
        return result

    draft_lines = tuple(_apply_rule_to_line(line, result, rule) for line in result.draft_lines)
    evidence = tuple(dict.fromkeys((*result.business_relevance_evidence, LEARNING_APPLIED_EVIDENCE)))
    return replace(
        result,
        selected_expense_account=rule.corrected_account_code or result.selected_expense_account,
        selected_supplier_account=rule.corrected_counterparty_code or result.selected_supplier_account,
        business_relevance_evidence=evidence,
        learning_rule_applied=True,
        learning_rule_scope=rule.scope,
        learning_rule_reason=rule.reason,
        draft_lines=draft_lines,
    )


def _select_rule(category: str, rules: Iterable[LearnedPostingRule]) -> LearnedPostingRule | None:
    allowed_actions = {"approve", "approve_with_changes", "suggest_for_similar"}
    for rule in rules:
        if rule.category == category and rule.action in allowed_actions:
            if rule.corrected_account_code or rule.corrected_counterparty_code:
                return rule
    return None


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

