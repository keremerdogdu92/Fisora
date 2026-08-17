from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_candidate_builder import AccountingCandidate
from app.domain.accounting_proposal import parse_accounting_proposal
from app.domain.accounting_quality import evaluate_accounting_quality
from app.domain.journal_draft_builder import build_journal_draft
from app.domain.accounting_proposal import SemanticConflict


def _candidate(candidate_id: str) -> AccountingCandidate:
    return AccountingCandidate(candidate_id, candidate_id, candidate_id, (), "", "", True, 0)


CANDIDATES = {code: _candidate(code) for code in ("320", "770")}


def _projection(*, payable: str = "100.00") -> dict[str, object]:
    return {
        "document_direction": "purchase", "header": {"currency_code": "TRY"},
        "line_items": [{"identity_ref": "line:l1", "decision_ref": "line:l1", "taxable_amount": "100.00"}],
        "vat_summary": [], "tax_components": [], "monetary_components": [],
        "totals": {"payable_total": payable},
    }


def _proposal(*, line_action: str = "select_existing", counterparty_action: str = "select_existing"):
    counterparty = {"action": counterparty_action, "selected_candidate_id": "320" if counterparty_action == "select_existing" else ""}
    if counterparty_action == "propose_new":
        counterparty["proposal"] = {"party_title": "New Supplier", "tax_id": "1234567890", "direction": "supplier", "suggested_parent_family": "320"}
    return parse_accounting_proposal(
        {"counterparty": counterparty, "decisions": [{"decision_ref": "line:l1", "action": line_action, "selected_candidate_id": "770" if line_action == "select_existing" else ""}], "candidate_sufficiency": {"sufficient": True, "request_more_candidates": False, "provisional": False}},
        required_decision_refs=("counterparty", "line:l1"), sent_candidates=CANDIDATES,
    )


class AccountingQualityV2Tests(unittest.TestCase):
    def test_treatment_review_keeps_suggested_account_without_unresolved_account_warning(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [],
            "vat_summary": [],
            "tax_components": [
                {
                    "identity_ref": "tax:t1",
                    "decision_ref": "tax:t1",
                    "tax_amount": "5.00",
                    "economic_effect": "increase_tax",
                }
            ],
            "monetary_components": [],
            "totals": {"payable_total": "0.00"},
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
                "decisions": [
                    {
                        "decision_ref": "tax:t1",
                        "action": "select_existing",
                        "selected_candidate_id": "770",
                        "selected_treatment": "",
                    }
                ],
                "candidate_sufficiency": {
                    "sufficient": True,
                    "request_more_candidates": False,
                    "provisional": False,
                },
            },
            required_decision_refs=("counterparty", "tax:t1"),
            sent_candidates=CANDIDATES,
            projection=projection,
        )
        draft = build_journal_draft(projection, proposal)

        result = evaluate_accounting_quality(projection, proposal, draft)

        self.assertEqual(draft.line_for("tax:t1").resolution, "review_required")
        self.assertNotIn("unresolved_accounts", result.warnings)
        self.assertIn("treatment_topology_review_required", result.warnings)
        self.assertEqual(result.status, "partial")

    def test_semantic_conflicts_are_review_warnings_without_erasing_draft(self) -> None:
        projection = _projection()
        proposal = replace(
            _proposal(),
            semantic_conflicts=(
                SemanticConflict(
                    decision_ref="line:l1",
                    conflict_code="tax_treatment_conflict",
                    deterministic_expectation="expense_or_cost",
                    ai_selection_or_treatment="payable_withholding",
                    ai_reason="AI treatment",
                    candidate_round_index=1,
                    candidate_id="770",
                    source_evidence_refs=("pdf:line:1",),
                ),
            ),
        )
        draft = build_journal_draft(projection, proposal)

        result = evaluate_accounting_quality(projection, proposal, draft)

        self.assertIs(result.draft, draft)
        self.assertGreater(len(draft.lines), 0)
        self.assertIn("tax_treatment_conflict", result.warnings)
    def test_valid_zero_fact_without_account_is_complete_and_preserved(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [],
            "vat_summary": [
                {"identity_ref": "vat:v0", "decision_ref": "vat:v0", "tax_amount": "0.00"}
            ],
            "tax_components": [],
            "monetary_components": [],
            "totals": {"payable_total": "0.00"},
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
                "decisions": [
                    {
                        "decision_ref": "vat:v0",
                        "action": "no_separate_posting",
                        "selected_candidate_id": "",
                    }
                ],
                "candidate_sufficiency": {
                    "sufficient": True,
                    "request_more_candidates": False,
                    "provisional": False,
                },
            },
            required_decision_refs=("counterparty", "vat:v0"),
            sent_candidates=CANDIDATES,
            projection=projection,
        )
        draft = build_journal_draft(projection, proposal)

        result = evaluate_accounting_quality(projection, proposal, draft)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.warnings, ())
        self.assertEqual(draft.line_for("vat:v0").representation, "no_separate_posting")

    def test_fully_covered_balanced_draft_is_complete_and_not_mutated(self) -> None:
        projection = _projection()
        proposal = _proposal()
        draft = build_journal_draft(projection, proposal)

        result = evaluate_accounting_quality(projection, proposal, draft)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.warnings, ())
        self.assertIs(result.draft, draft)

    def test_unresolved_and_unbalanced_drafts_remain_partial_and_intact(self) -> None:
        cases = (
            ("unresolved", _projection(), _proposal(line_action="unresolved"), "unresolved_accounts"),
            ("unbalanced", _projection(payable="90.00"), _proposal(), "journal_unbalanced"),
        )
        for label, projection, proposal, warning in cases:
            with self.subTest(case=label):
                draft = build_journal_draft(projection, proposal)
                result = evaluate_accounting_quality(projection, proposal, draft)
                self.assertEqual(result.status, "partial")
                self.assertIn(warning, result.warnings)
                self.assertIs(result.draft, draft)
                self.assertGreater(len(result.draft.lines), 0)

    def test_duplicate_fact_representation_is_partial(self) -> None:
        projection = _projection()
        proposal = _proposal()
        draft = build_journal_draft(projection, proposal)
        duplicate = replace(draft, lines=(*draft.lines, draft.line_for("line:l1")))

        result = evaluate_accounting_quality(projection, proposal, duplicate)

        self.assertEqual(result.status, "partial")
        self.assertIn("fact_representation_mismatch", result.warnings)

    def test_preserved_propose_new_counterparty_is_a_valid_complete_action(self) -> None:
        projection = _projection()
        proposal = _proposal(counterparty_action="propose_new")
        draft = build_journal_draft(projection, proposal)

        result = evaluate_accounting_quality(projection, proposal, draft)

        self.assertEqual(draft.line_for("counterparty").resolution, "propose_new")
        self.assertEqual(result.status, "complete")

    def test_forged_totals_and_fact_amounts_are_partial(self) -> None:
        projection = _projection()
        proposal = _proposal()
        draft = build_journal_draft(projection, proposal)
        forged_line = replace(draft.line_for("line:l1"), amount=__import__("decimal").Decimal("999.00"), debit=__import__("decimal").Decimal("999.00"))
        forged = replace(draft, lines=(forged_line, draft.line_for("counterparty")), total_debit=__import__("decimal").Decimal("100.00"), total_credit=__import__("decimal").Decimal("100.00"), is_balanced=True)

        result = evaluate_accounting_quality(projection, proposal, forged)

        self.assertEqual(result.status, "partial")
        self.assertIn("draft_totals_mismatch", result.warnings)
        self.assertIn("fact_amount_or_posting_mismatch", result.warnings)

    def test_recorded_sent_set_and_sufficiency_are_quality_gates(self) -> None:
        projection = _projection()
        proposal = _proposal()
        draft = build_journal_draft(projection, proposal)
        forged_sent = replace(proposal, sent_candidate_ids=("320",))
        insufficient = replace(proposal, candidate_sufficient=False, request_more_candidates=True, provisional=True)

        integrity = evaluate_accounting_quality(projection, forged_sent, draft)
        sufficiency = evaluate_accounting_quality(projection, insufficient, draft)

        self.assertIn("candidate_integrity_invalid", integrity.warnings)
        self.assertIn("candidate_sufficiency_incomplete", sufficiency.warnings)

    def test_candidate_object_and_draft_account_metadata_cannot_be_forged(self) -> None:
        projection = _projection()
        proposal = _proposal()
        draft = build_journal_draft(projection, proposal)
        line_decision = proposal.decision_for("line:l1")
        external_candidate = _candidate("external")
        forged_decision = replace(line_decision, candidate=external_candidate)
        forged_proposal = replace(
            proposal,
            decisions=(proposal.counterparty, forged_decision),
        )
        forged_line = replace(
            draft.line_for("line:l1"),
            selected_candidate_id="external",
            account_code="999",
            account_name="External",
        )
        forged_draft = replace(
            draft,
            lines=(forged_line, draft.line_for("counterparty")),
        )

        integrity = evaluate_accounting_quality(projection, forged_proposal, draft)
        metadata = evaluate_accounting_quality(projection, proposal, forged_draft)

        self.assertIn("candidate_integrity_invalid", integrity.warnings)
        self.assertIn("fact_amount_or_posting_mismatch", metadata.warnings)

    def test_quality_rejects_forged_propose_new_shape_and_direction(self) -> None:
        projection = _projection()
        proposal = _proposal(counterparty_action="propose_new")
        draft = build_journal_draft(projection, proposal)
        malformed_counterparty = replace(
            proposal.counterparty,
            proposal={
                "party_title": 123,
                "tax_id": "1234567890",
                "direction": "customer",
                "suggested_parent_family": "320",
            },
        )
        malformed = replace(
            proposal,
            counterparty=malformed_counterparty,
            decisions=(malformed_counterparty, proposal.decision_for("line:l1")),
        )

        result = evaluate_accounting_quality(projection, malformed, draft)

        self.assertEqual(result.status, "partial")
        self.assertIn("counterparty_proposal_invalid", result.warnings)


if __name__ == "__main__":
    unittest.main()
