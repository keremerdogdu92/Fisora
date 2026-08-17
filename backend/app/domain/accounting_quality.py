from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.domain.accounting_proposal import (
    AccountingProposalV2,
    required_decision_refs_for_projection,
)
from app.domain.journal_draft_builder import (
    JournalDraftV2,
    build_journal_draft,
    projection_fact_refs,
)


@dataclass(frozen=True)
class AccountingQualityResult:
    status: str
    warnings: tuple[str, ...]
    draft: JournalDraftV2
    accounting_decision_status: str
    draft_balance_status: str


def evaluate_accounting_quality(
    projection: Mapping[str, object],
    proposal: AccountingProposalV2,
    draft: JournalDraftV2,
) -> AccountingQualityResult:
    warnings: list[str] = [
        *proposal.warnings,
        *(conflict.conflict_code for conflict in proposal.semantic_conflicts),
    ]
    required = required_decision_refs_for_projection(projection)
    decision_counts = Counter(item.decision_ref for item in proposal.decisions)
    if any(decision_counts[ref] != 1 for ref in required):
        warnings.append("decision_ref_coverage_incomplete")
    for decision in proposal.decisions:
        if decision.action == "select_existing" and (
            decision.candidate is None
            or not decision.candidate.active
            or decision.candidate.candidate_id != decision.selected_candidate_id
            or decision.selected_candidate_id not in proposal.sent_candidate_ids
        ):
            warnings.append("candidate_integrity_invalid")
            break
    if proposal.counterparty.action not in {"select_existing", "propose_new"}:
        warnings.append("counterparty_action_unresolved")
    if proposal.counterparty.action == "propose_new":
        proposal_fields = {
            "party_title",
            "tax_id",
            "direction",
            "suggested_parent_family",
        }
        proposal_shape_valid = (
            set(proposal.counterparty.proposal) == proposal_fields
            and all(
                isinstance(proposal.counterparty.proposal.get(key), str)
                and proposal.counterparty.proposal[key].strip()
                for key in proposal_fields
            )
        )
        if not proposal_shape_valid:
            warnings.append("counterparty_proposal_invalid")
        expected_direction = (
            "supplier"
            if str(projection.get("document_direction") or "").lower() == "purchase"
            else "customer"
            if str(projection.get("document_direction") or "").lower() == "sales"
            else ""
        )
        if (
            not expected_direction
            or str(proposal.counterparty.proposal.get("direction") or "").lower()
            != expected_direction
        ):
            warnings.append("counterparty_proposal_direction_mismatch")
    if (
        not proposal.candidate_sufficient
        or proposal.request_more_candidates
        or proposal.provisional
    ):
        warnings.append("candidate_sufficiency_incomplete")
    if any(line.resolution == "unresolved" for line in draft.lines):
        warnings.append("unresolved_accounts")
    if any(
        "treatment_topology_review_required" in line.warnings for line in draft.lines
    ):
        warnings.append("treatment_topology_review_required")
    if any("amount_invalid" in line.warnings for line in draft.lines):
        warnings.append("amount_invalid")
    expected_facts = projection_fact_refs(projection)
    draft_counts = Counter(line.fact_ref for line in draft.lines)
    if any(draft_counts[ref] != 1 for ref in expected_facts) or any(
        ref not in expected_facts for ref in draft_counts
    ):
        warnings.append("fact_representation_mismatch")
    expected_draft = build_journal_draft(projection, proposal)
    expected_by_ref = {line.fact_ref: line for line in expected_draft.lines}
    actual_by_ref = {line.fact_ref: line for line in draft.lines}
    if any(
        (
            actual_by_ref[ref].amount,
            actual_by_ref[ref].side,
            actual_by_ref[ref].debit,
            actual_by_ref[ref].credit,
            actual_by_ref[ref].representation,
            actual_by_ref[ref].represented_by_refs,
            actual_by_ref[ref].resolution,
            actual_by_ref[ref].selected_candidate_id,
            actual_by_ref[ref].account_code,
            actual_by_ref[ref].account_name,
        )
        != (
            expected.amount,
            expected.side,
            expected.debit,
            expected.credit,
            expected.representation,
            expected.represented_by_refs,
            expected.resolution,
            expected.selected_candidate_id,
            expected.account_code,
            expected.account_name,
        )
        for ref, expected in expected_by_ref.items()
        if draft_counts[ref] == 1 and ref in actual_by_ref
    ):
        warnings.append("fact_amount_or_posting_mismatch")
    debit_values = tuple(line.debit for line in draft.lines)
    credit_values = tuple(line.credit for line in draft.lines)
    values_finite = all(value.is_finite() for value in (*debit_values, *credit_values))
    recomputed_debit = sum(debit_values, Decimal("0.00")) if values_finite else Decimal("NaN")
    recomputed_credit = sum(credit_values, Decimal("0.00")) if values_finite else Decimal("NaN")
    recomputed_balanced = values_finite and recomputed_debit == recomputed_credit
    if (
        not draft.total_debit.is_finite()
        or not draft.total_credit.is_finite()
        or draft.total_debit != recomputed_debit
        or draft.total_credit != recomputed_credit
        or draft.is_balanced != recomputed_balanced
    ):
        warnings.append("draft_totals_mismatch")
    if not recomputed_balanced:
        warnings.append("journal_unbalanced")
    accounting_decision_status = (
        "partial"
        if proposal.validation_issues
        or proposal.unresolved_decision_refs
        or not proposal.candidate_sufficient
        or proposal.request_more_candidates
        or proposal.provisional
        else "complete"
    )
    return AccountingQualityResult(
        status="complete" if not warnings else "partial",
        warnings=tuple(dict.fromkeys(warnings)),
        draft=draft,
        accounting_decision_status=accounting_decision_status,
        draft_balance_status="balanced" if recomputed_balanced else "unbalanced",
    )
