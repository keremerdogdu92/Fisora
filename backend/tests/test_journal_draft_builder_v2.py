from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_candidate_builder import AccountingCandidate
from app.domain.accounting_proposal import parse_accounting_proposal
from app.domain.accounting_proposal import attach_semantic_conflicts
from app.domain.journal_draft_builder import build_journal_draft


def _c(candidate_id: str) -> AccountingCandidate:
    return AccountingCandidate(candidate_id, candidate_id, candidate_id, (), "", "", True, 0)


CANDIDATES = {code: _c(code) for code in ("320", "120", "770", "600", "191", "391", "360", "649")}


def _decision(ref: str, candidate_id: str) -> dict[str, str]:
    treatment = (
        "payable_withholding"
        if "withholding" in ref
        else "expense_or_cost"
        if ref.startswith("tax:")
        else "other"
        if ref.endswith(":unknown")
        else "reduce_payable"
        if "discount" in ref
        else "increase_payable"
        if ref.startswith("monetary:")
        else ""
    )
    return {
        "decision_ref": ref,
        "action": "select_existing",
        "selected_candidate_id": candidate_id,
        "selected_treatment": treatment,
    }


def _purchase_projection() -> dict[str, object]:
    return {
        "document_direction": "purchase",
        "header": {"currency_code": "TRY"},
        "line_items": [{"identity_ref": "line:l1", "decision_ref": "line:l1", "taxable_amount": "100.00"}],
        "vat_summary": [{"identity_ref": "vat:v20", "decision_ref": "vat:v20", "tax_amount": "20.00"}],
        "tax_components": [
            {"identity_ref": "vat:v20", "decision_ref": "vat:v20", "tax_amount": "20.00", "canonical_tax_kind": "vat", "economic_effect": "increase_tax", "represented_by_refs": []},
            {"identity_ref": "tax:withholding", "decision_ref": "tax:withholding", "tax_amount": "10.00", "canonical_tax_kind": "withholding", "economic_effect": "reduce_payable", "represented_by_refs": []},
        ],
        "monetary_components": [
            {"identity_ref": "monetary:discount", "decision_ref": "monetary:discount", "source_amount": "5.00", "signed_effect": "decrease_payable", "included_in_line_net": "yes", "included_in_tax_total": "no", "included_in_payable": "yes", "accounting_treatment": "separate_posting"},
            {"identity_ref": "monetary:charge", "decision_ref": "monetary:charge", "source_amount": "8.50", "signed_effect": "increase_payable", "included_in_line_net": "no", "included_in_tax_total": "no", "included_in_payable": "yes", "accounting_treatment": "separate_posting"},
            {"identity_ref": "monetary:unknown", "decision_ref": "monetary:unknown", "source_amount": "2.00", "signed_effect": "unknown", "included_in_line_net": "unknown", "included_in_tax_total": "no", "included_in_payable": "no", "accounting_treatment": "separate_posting"},
        ],
        "totals": {"payable_total": "118.50"},
    }


class JournalDraftBuilderV2Tests(unittest.TestCase):
    def test_missing_nonzero_treatment_keeps_suggested_account_without_financial_posting(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [],
            "vat_summary": [],
            "tax_components": [
                {
                    "identity_ref": "tax:oiv",
                    "decision_ref": "tax:oiv",
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
                        "decision_ref": "tax:oiv",
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
            required_decision_refs=("counterparty", "tax:oiv"),
            sent_candidates=CANDIDATES,
            projection=projection,
        )

        draft = build_journal_draft(projection, proposal)
        line = draft.line_for("tax:oiv")

        self.assertEqual(line.selected_candidate_id, "770")
        self.assertEqual(line.account_code, "770")
        self.assertEqual(line.resolution, "review_required")
        self.assertIsNone(line.side)
        self.assertEqual(line.debit, Decimal("0.00"))
        self.assertEqual(line.credit, Decimal("0.00"))
        self.assertIn("treatment_topology_review_required", line.warnings)

    def test_ai_vat_and_tax_choices_are_kept_with_structured_semantic_conflicts(self) -> None:
        candidates = {
            **CANDIDATES,
            "191.18": AccountingCandidate(
                "191.18", "191.18", "Explicit VAT 18", ("vat",), "", "", True, 2,
                vat_rates=("18",),
            ),
        }
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [],
            "vat_summary": [
                {
                    "identity_ref": "vat:v20",
                    "decision_ref": "vat:v20",
                    "rate": "20",
                    "tax_amount": "20.00",
                    "source_evidence_refs": ["pdf:vat:20"],
                }
            ],
            "tax_components": [
                {
                    "identity_ref": "tax:oiv",
                    "decision_ref": "tax:oiv",
                    "tax_amount": "5.00",
                    "accounting_treatment": "expense_or_cost",
                    "economic_effect": "increase_tax",
                    "source_evidence_refs": ["pdf:tax:oiv"],
                }
            ],
            "monetary_components": [],
            "totals": {"payable_total": "25.00"},
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
                "decisions": [
                    {
                        "decision_ref": "vat:v20",
                        "action": "select_existing",
                        "selected_candidate_id": "191.18",
                        "reason": "AI semantic VAT choice",
                    },
                    {
                        "decision_ref": "tax:oiv",
                        "action": "select_existing",
                        "selected_candidate_id": "360",
                        "selected_treatment": "payable_withholding",
                        "reason": "AI tax treatment",
                    },
                ],
            },
            required_decision_refs=("counterparty", "vat:v20", "tax:oiv"),
            sent_candidates=candidates,
            projection=projection,
        )
        proposal = attach_semantic_conflicts(projection, proposal)

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("vat:v20").selected_candidate_id, "191.18")
        self.assertEqual(draft.line_for("tax:oiv").selected_candidate_id, "360")
        self.assertEqual(
            {item.conflict_code for item in draft.semantic_conflicts},
            {"vat_rate_semantic_conflict", "tax_treatment_conflict"},
        )
        vat_conflict = next(
            item for item in draft.semantic_conflicts
            if item.conflict_code == "vat_rate_semantic_conflict"
        )
        self.assertEqual(vat_conflict.deterministic_expectation, "20")
        self.assertEqual(vat_conflict.ai_selection_or_treatment, "191.18")
        self.assertEqual(vat_conflict.candidate_round_index, 2)
        self.assertEqual(vat_conflict.source_evidence_refs, ("pdf:vat:20",))

    def test_zero_and_nonposting_ai_actions_remain_once_in_draft_topology(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [],
            "vat_summary": [
                {"identity_ref": "vat:v0", "decision_ref": "vat:v0", "tax_amount": "0.00"}
            ],
            "tax_components": [
                {"identity_ref": "tax:t1", "decision_ref": "tax:t1", "tax_amount": "5.00"}
            ],
            "monetary_components": [
                {"identity_ref": "monetary:m1", "decision_ref": "monetary:m1", "source_amount": "5.00"}
            ],
            "totals": {"payable_total": "0.00"},
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {
                    "action": "select_existing",
                    "selected_candidate_id": "320",
                },
                "decisions": [
                    {
                        "decision_ref": "vat:v0",
                        "action": "no_separate_posting",
                        "selected_candidate_id": "",
                    },
                    {
                        "decision_ref": "tax:t1",
                        "action": "represented",
                        "selected_candidate_id": "",
                        "selected_treatment": "represented_in_line",
                        "reason": "Included in line amount",
                    },
                    {
                        "decision_ref": "monetary:m1",
                        "action": "excluded",
                        "selected_candidate_id": "",
                        "selected_treatment": "excluded",
                        "reason": "Excluded from current payable",
                    },
                ],
            },
            required_decision_refs=("counterparty", "vat:v0", "tax:t1", "monetary:m1"),
            sent_candidates=CANDIDATES,
            projection=projection,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(tuple(line.fact_ref for line in draft.lines), (
            "vat:v0", "tax:t1", "monetary:m1", "counterparty"
        ))
        self.assertEqual(draft.line_for("vat:v0").representation, "no_separate_posting")
        self.assertEqual(draft.line_for("tax:t1").representation, "represented")
        self.assertEqual(draft.line_for("monetary:m1").representation, "excluded")
        self.assertTrue(
            all(
                line.side is None
                for line in draft.lines
                if line.fact_ref != "counterparty"
            )
        )
        self.assertTrue(draft.is_balanced)

    def test_purchase_posts_each_identity_once_and_uses_projection_amounts(self) -> None:
        projection = _purchase_projection()
        refs = ("counterparty", "line:l1", "vat:v20", "tax:withholding", "monetary:discount", "monetary:charge", "monetary:unknown")
        proposal = parse_accounting_proposal(
            {
                "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
                "decisions": [
                    _decision("line:l1", "770"), _decision("vat:v20", "191"),
                    _decision("tax:withholding", "360"), _decision("monetary:discount", "649"),
                    _decision("monetary:charge", "770"), _decision("monetary:unknown", "770"),
                ],
                "candidate_sufficiency": {"sufficient": True, "request_more_candidates": False},
            },
            required_decision_refs=refs,
            sent_candidates=CANDIDATES,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(len([line for line in draft.lines if line.fact_ref == "vat:v20"]), 1)
        self.assertEqual(draft.line_for("line:l1").debit, Decimal("100.00"))
        self.assertEqual(draft.line_for("vat:v20").debit, Decimal("20.00"))
        self.assertEqual(draft.line_for("tax:withholding").credit, Decimal("10.00"))
        self.assertEqual(draft.line_for("counterparty").credit, Decimal("118.50"))
        self.assertEqual(draft.line_for("monetary:discount").representation, "included_in_line_net")
        self.assertEqual(draft.line_for("monetary:charge").debit, Decimal("8.50"))
        self.assertEqual(draft.line_for("monetary:unknown").resolution, "unresolved")
        self.assertIsNone(draft.line_for("monetary:unknown").side)
        self.assertEqual(draft.line_for("monetary:unknown").amount, Decimal("2.00"))
        self.assertEqual(draft.total_debit, Decimal("128.50"))
        self.assertEqual(draft.total_credit, Decimal("128.50"))
        self.assertTrue(draft.is_balanced)

    def test_sales_mirrors_purchase_sides(self) -> None:
        projection = {
            "document_direction": "sales", "header": {"currency_code": "TRY"},
            "line_items": [{"identity_ref": "line:l1", "decision_ref": "line:l1", "taxable_amount": "100.00"}],
            "vat_summary": [{"identity_ref": "vat:v20", "decision_ref": "vat:v20", "tax_amount": "20.00"}],
            "tax_components": [], "monetary_components": [], "totals": {"payable_total": "120.00"},
        }
        proposal = parse_accounting_proposal(
            {"counterparty": {"action": "select_existing", "selected_candidate_id": "120"}, "decisions": [_decision("line:l1", "600"), _decision("vat:v20", "391")]},
            required_decision_refs=("counterparty", "line:l1", "vat:v20"), sent_candidates=CANDIDATES,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("counterparty").debit, Decimal("120.00"))
        self.assertEqual(draft.line_for("line:l1").credit, Decimal("100.00"))
        self.assertEqual(draft.line_for("vat:v20").credit, Decimal("20.00"))
        self.assertTrue(draft.is_balanced)

    def test_unmatched_vat_component_is_posted_and_aggregate_vat_is_represented(self) -> None:
        projection = {
            "document_direction": "sales", "header": {"currency_code": "TRY"}, "line_items": [], "vat_summary": [],
            "tax_components": [
                {"identity_ref": "vat:unmatched", "decision_ref": "vat:unmatched", "tax_amount": "5.60", "canonical_tax_kind": "vat", "economic_effect": "increase_tax", "represented_by_refs": []},
                {"identity_ref": "vat:aggregate", "decision_ref": "", "tax_amount": "5.60", "canonical_tax_kind": "vat", "economic_effect": "increase_tax", "represented_by_refs": ["vat:unmatched"]},
            ],
            "monetary_components": [], "totals": {"payable_total": "5.60"},
        }
        proposal = parse_accounting_proposal(
            {"counterparty": {"action": "select_existing", "selected_candidate_id": "120"}, "decisions": [_decision("vat:unmatched", "391")]},
            required_decision_refs=("counterparty", "vat:unmatched"), sent_candidates=CANDIDATES,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("vat:unmatched").credit, Decimal("5.60"))
        self.assertEqual(draft.line_for("vat:aggregate").representation, "represented_by_refs")
        self.assertEqual(draft.line_for("vat:aggregate").credit, Decimal("0.00"))
        self.assertTrue(draft.is_balanced)

    def test_known_tax_effect_posts_when_legacy_tax_total_membership_is_unknown(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [
                {"identity_ref": "line:l1", "decision_ref": "line:l1", "taxable_amount": "14.04"}
            ],
            "vat_summary": [
                {"identity_ref": "vat:v20", "decision_ref": "vat:v20", "tax_amount": "2.81"}
            ],
            "tax_components": [
                {
                    "identity_ref": "tax:oiv",
                    "decision_ref": "tax:oiv",
                    "tax_amount": "1.40",
                    "economic_effect": "increase_tax",
                    "included_in_tax_total": "unknown",
                    "included_in_payable": "yes",
                    "posting_requirement": "separate",
                }
            ],
            "monetary_components": [],
            "totals": {"payable_total": "18.25"},
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
                "decisions": [
                    _decision("line:l1", "770"),
                    _decision("vat:v20", "191"),
                    _decision("tax:oiv", "770"),
                ],
            },
            required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:oiv"),
            sent_candidates=CANDIDATES,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("tax:oiv").debit, Decimal("1.40"))
        self.assertEqual(draft.line_for("tax:oiv").resolution, "resolved")
        self.assertTrue(draft.is_balanced)

    def test_informational_excluded_and_unresolved_counterparty_remain_visible(self) -> None:
        projection = {
            "document_direction": "purchase", "header": {"currency_code": "TRY"},
            "line_items": [], "vat_summary": [], "tax_components": [],
            "monetary_components": [
                {"identity_ref": "monetary:info", "decision_ref": "monetary:info", "source_amount": "3.00", "accounting_treatment": "informational"},
                {"identity_ref": "monetary:excluded", "decision_ref": "monetary:excluded", "source_amount": "4.00", "accounting_treatment": "exclude_current_period"},
            ],
            "totals": {"payable_total": "0.00"},
        }
        proposal = parse_accounting_proposal(
            {"counterparty": {"action": "unresolved"}, "decisions": []},
            required_decision_refs=("counterparty",), sent_candidates=CANDIDATES,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("monetary:info").representation, "informational")
        self.assertEqual(draft.line_for("monetary:excluded").representation, "exclude_current_period")
        self.assertEqual(draft.line_for("counterparty").resolution, "unresolved")
        self.assertEqual(len(draft.lines), 3)

    def test_invalid_and_nonfinite_amounts_are_unresolved_without_crashing(self) -> None:
        for raw_amount in ("", "garbage", "NaN", "Infinity"):
            with self.subTest(raw_amount=raw_amount):
                projection = {
                    "document_direction": "purchase", "header": {"currency_code": "TRY"},
                    "line_items": [{"identity_ref": "line:bad", "decision_ref": "line:bad", "taxable_amount": raw_amount}],
                    "vat_summary": [], "tax_components": [], "monetary_components": [],
                    "totals": {"payable_total": "0.00"},
                }
                proposal = parse_accounting_proposal(
                    {"counterparty": {"action": "select_existing", "selected_candidate_id": "320"}, "decisions": [_decision("line:bad", "770")]},
                    required_decision_refs=("counterparty", "line:bad"), sent_candidates=CANDIDATES,
                )
                draft = build_journal_draft(projection, proposal)
                line = draft.line_for("line:bad")
                self.assertEqual(line.raw_source_amount, raw_amount)
                self.assertEqual(line.amount, Decimal("0.00"))
                self.assertEqual(line.resolution, "unresolved")
                self.assertIn("amount_invalid", line.warnings)
                self.assertIsNone(line.side)

    def test_printed_currency_suffix_is_parsed_without_changing_raw_source_amount(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [
                {
                    "identity_ref": "line:l1",
                    "decision_ref": "line:l1",
                    "taxable_amount": "430,86TRY",
                }
            ],
            "vat_summary": [],
            "tax_components": [],
            "monetary_components": [],
            "totals": {"payable_total": "430,86TRY"},
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {
                    "action": "select_existing",
                    "selected_candidate_id": "320",
                },
                "decisions": [_decision("line:l1", "770")],
            },
            required_decision_refs=("counterparty", "line:l1"),
            sent_candidates=CANDIDATES,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("line:l1").raw_source_amount, "430,86TRY")
        self.assertEqual(draft.line_for("line:l1").debit, Decimal("430.86"))
        self.assertEqual(draft.line_for("counterparty").credit, Decimal("430.86"))
        self.assertTrue(draft.is_balanced)


if __name__ == "__main__":
    unittest.main()
