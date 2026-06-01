from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ReviewAction = Literal[
    "approve",
    "approve_with_changes",
    "exclude_from_export",
    "business_out_of_scope",
    "wrong_counterparty",
    "wrong_account",
    "suggest_for_similar",
]
LearningScope = Literal["general_candidate", "office_policy", "client_rule"]


@dataclass(frozen=True)
class ReviewDecision:
    document_ref: str
    action: ReviewAction
    reviewer: str
    corrected_account_code: str = ""
    corrected_counterparty_code: str = ""
    category: str = ""
    reason: str = ""
    apply_to_similar: bool = False


@dataclass(frozen=True)
class LearningEvent:
    document_ref: str
    scope: LearningScope
    action: ReviewAction
    category: str
    corrected_account_code: str
    corrected_counterparty_code: str
    reason: str
    automation_candidate: bool


def build_learning_event(decision: ReviewDecision, *, prior_consistent_approval_count: int = 0) -> LearningEvent:
    if decision.apply_to_similar:
        scope: LearningScope = "client_rule"
    elif decision.action == "suggest_for_similar":
        scope = "office_policy"
    else:
        scope = "general_candidate"

    automation_candidate = (
        decision.action in {"approve", "approve_with_changes", "suggest_for_similar"}
        and prior_consistent_approval_count + 1 >= 3
    )
    return LearningEvent(
        document_ref=decision.document_ref,
        scope=scope,
        action=decision.action,
        category=decision.category,
        corrected_account_code=decision.corrected_account_code,
        corrected_counterparty_code=decision.corrected_counterparty_code,
        reason=decision.reason,
        automation_candidate=automation_candidate,
    )
