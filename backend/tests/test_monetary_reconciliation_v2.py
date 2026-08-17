from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.monetary_reconciliation import reconcile_monetary_projection
from app.domain.accounting_candidate_builder import AccountingCandidate
from app.domain.accounting_proposal import (
    attach_semantic_conflicts,
    parse_accounting_proposal,
    required_decision_refs_for_projection,
)
from app.domain.journal_draft_builder import build_journal_draft


def _telecom_projection(*, payable_total: str = "45.25") -> dict[str, object]:
    return {
        "document_direction": "purchase",
        "header": {"currency_code": "TRY"},
        "line_items": [
            {
                "identity_ref": "line:monthly",
                "decision_ref": "line:monthly",
                "taxable_amount": "8.37",
                "gross_amount": "10.88",
            },
            {
                "identity_ref": "line:other",
                "decision_ref": "line:other",
                "taxable_amount": "5.67",
                "gross_amount": "7.37",
            },
        ],
        "vat_summary": [
            {
                "identity_ref": "vat:20",
                "decision_ref": "vat:20",
                "tax_amount": "2.81",
            }
        ],
        "tax_components": [
            {
                "identity_ref": "tax:oiv",
                "decision_ref": "tax:oiv",
                "component_type": "special_tax",
                "canonical_tax_kind": "special_communication_tax",
                "tax_amount": "1.40",
                "economic_effect": "increase_tax",
                "included_in_tax_total": "unknown",
                "included_in_payable": "no",
                "represented_by_refs": [],
            },
            {
                "identity_ref": "tax:radio",
                "decision_ref": "tax:radio",
                "component_type": "special_tax",
                "canonical_tax_kind": "radio_usage_fee",
                "tax_amount": "26.98",
                "economic_effect": "increase_tax",
                "included_in_tax_total": "unknown",
                "included_in_payable": "unknown",
                "represented_by_refs": [],
            },
        ],
        "monetary_components": [
            {
                "identity_ref": "monetary:previous",
                "decision_ref": "monetary:previous",
                "source_label": "Onceki aydan devir",
                "source_amount": "0.17",
                "canonical_component_kind": "prior_period_balance",
                "accounting_treatment": "exclude_current_period",
                "signed_effect": "increase_payable",
                "included_in_line_net": "unknown",
                "included_in_payable": "unknown",
            },
            {
                "identity_ref": "monetary:next",
                "decision_ref": "monetary:next",
                "source_label": "Sonraki aya devir",
                "source_amount": "-0.15",
                "canonical_component_kind": "next_period_balance",
                "accounting_treatment": "separate_posting",
                "signed_effect": "decrease_payable",
                "included_in_line_net": "unknown",
                "included_in_payable": "unknown",
            },
        ],
        "totals": {
            "goods_services_total": "14.04",
            "vat_total": "2.81",
            "special_tax_total": "1.40",
            "tax_inclusive_total": "45.25",
            "payable_total": payable_total,
        },
        "projection_warnings": [],
    }


def _by_ref(projection: dict[str, object], section: str) -> dict[str, dict[str, object]]:
    return {
        str(item["identity_ref"]): item
        for item in projection[section]
    }


class MonetaryReconciliationV2Tests(unittest.TestCase):
    def test_allowance_and_deduplicated_named_totals_enter_source_backed_component_ledger(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [
                {"identity_ref": "line:1", "decision_ref": "line:1", "taxable_amount": "100.00"}
            ],
            "vat_summary": [
                {"identity_ref": "vat:20", "decision_ref": "vat:20", "taxable_amount": "100.00", "tax_amount": "20.00"}
            ],
            "tax_components": [],
            "monetary_components": [],
            "named_totals": [
                {
                    "source_label": "SGK Katilim Payi",
                    "amount": "5.00",
                    "source_position": "total:sgk:1",
                    "proposed_role": "other",
                    "source_evidence_refs": ["pdf:sgk:1"],
                },
                {
                    "source_label": "SGK Katilim Payi",
                    "amount": "5.00",
                    "source_position": "total:sgk:duplicate",
                    "proposed_role": "other",
                    "source_evidence_refs": ["pdf:sgk:duplicate"],
                },
            ],
            "totals": {
                "allowance_total": "10.00",
                "payable_total": "125.00",
            },
            "projection_warnings": [],
        }

        reconciled = reconcile_monetary_projection(projection)

        synthetic = [
            item for item in reconciled["monetary_components"]
            if item.get("ledger_source") in {"allowance_total", "named_total"}
        ]
        self.assertEqual(len(synthetic), 2)
        self.assertEqual(
            {item["ledger_source"] for item in synthetic},
            {"allowance_total", "named_total"},
        )
        named = next(item for item in synthetic if item["ledger_source"] == "named_total")
        self.assertEqual(named["source_evidence_refs"], ["pdf:sgk:1"])
        self.assertEqual(named["reconciled_effect"], "increase_payable")
        self.assertEqual(reconciled["monetary_reconciliation"]["residual"], "0.00")

    def test_discount_kind_cannot_remain_a_payable_increase(self) -> None:
        projection = {
            "document_direction": "purchase",
            "line_items": [],
            "vat_summary": [],
            "tax_components": [],
            "monetary_components": [
                {
                    "identity_ref": "monetary:discount",
                    "decision_ref": "monetary:discount",
                    "source_label": "Indirim",
                    "source_amount": "5.00",
                    "canonical_component_kind": "discount",
                    "signed_effect": "increase_payable",
                }
            ],
            "totals": {"payable_total": "-5.00"},
            "projection_warnings": [],
        }

        reconciled = reconcile_monetary_projection(projection)

        self.assertEqual(
            reconciled["monetary_components"][0]["reconciled_effect"],
            "reduce_payable",
        )

    def test_ai_monetary_treatment_controls_posting_and_conflict_keeps_reconciliation_evidence(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [],
            "vat_summary": [],
            "tax_components": [],
            "monetary_components": [
                {
                    "identity_ref": "monetary:fee",
                    "decision_ref": "monetary:fee",
                    "source_label": "Fee",
                    "source_amount": "5.00",
                    "reconciled_effect": "increase_payable",
                    "posting_requirement": "separate",
                    "source_evidence_refs": ["pdf:fee"],
                }
            ],
            "totals": {"payable_total": "5.00"},
        }
        candidates = {
            code: AccountingCandidate(code, code, code, (), "", "", True, 1)
            for code in ("320", "649")
        }
        proposal = parse_accounting_proposal(
            {
                "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
                "decisions": [
                    {
                        "decision_ref": "monetary:fee",
                        "action": "select_existing",
                        "selected_candidate_id": "649",
                        "selected_treatment": "reduce_payable",
                        "reason": "AI says this reduces payable",
                    }
                ],
            },
            required_decision_refs=("counterparty", "monetary:fee"),
            sent_candidates=candidates,
            projection=projection,
        )
        proposal = attach_semantic_conflicts(projection, proposal)

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(draft.line_for("monetary:fee").credit, Decimal("5.00"))
        conflict = next(
            item for item in draft.semantic_conflicts
            if item.conflict_code == "monetary_effect_conflict"
        )
        self.assertEqual(conflict.deterministic_expectation, "increase_payable")
        self.assertEqual(conflict.ai_selection_or_treatment, "reduce_payable")
        self.assertEqual(conflict.source_evidence_refs, ("pdf:fee",))

    def test_complete_vat_base_allocates_bounded_cent_difference_across_visible_lines(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [
                {"identity_ref": "line:1", "decision_ref": "line:1", "taxable_amount": "580.26", "gross_amount": "580.26"},
                {"identity_ref": "line:2", "decision_ref": "line:2", "taxable_amount": "123.08", "gross_amount": "123.08"},
            ],
            "vat_summary": [
                {"identity_ref": "vat:20", "decision_ref": "vat:20", "taxable_amount": "703.33", "tax_amount": "140.67"}
            ],
            "tax_components": [
                {"identity_ref": "tax:oiv", "decision_ref": "tax:oiv", "tax_amount": "66.00", "economic_effect": "increase_tax"}
            ],
            "monetary_components": [],
            "totals": {"payable_total": "910.00", "special_tax_total": "66.00"},
        }

        reconciled = reconcile_monetary_projection(projection)

        self.assertEqual(reconciled["monetary_reconciliation"]["status"], "exact")
        self.assertEqual(reconciled["monetary_reconciliation"]["line_baseline_total"], "703.33")
        self.assertEqual(
            reconciled["monetary_reconciliation"]["line_baseline_basis"],
            "complete_vat_taxable_bases_cent_adjusted",
        )
        self.assertEqual(reconciled["monetary_reconciliation"]["line_allocation_adjustment"], "-0.01")
        self.assertEqual(
            [item["posting_amount"] for item in reconciled["line_items"]],
            ["580.26", "123.07"],
        )

    def test_telecom_components_reconcile_named_totals_and_payable_exactly(self) -> None:
        reconciled = reconcile_monetary_projection(_telecom_projection())

        summary = reconciled["monetary_reconciliation"]
        self.assertEqual(summary["status"], "exact")
        self.assertEqual(summary["mandatory_line_vat_total"], "16.85")
        self.assertEqual(summary["selected_component_effect_total"], "28.40")
        self.assertEqual(summary["reconciled_payable_total"], "45.25")
        self.assertEqual(summary["residual"], "0.00")
        self.assertEqual(
            set(summary["selected_component_refs"]),
            {"tax:oiv", "tax:radio", "monetary:previous", "monetary:next"},
        )

        taxes = _by_ref(reconciled, "tax_components")
        self.assertEqual(taxes["tax:oiv"]["total_memberships"]["special_tax_total"], "yes")
        self.assertEqual(taxes["tax:radio"]["total_memberships"]["special_tax_total"], "no")
        self.assertEqual(taxes["tax:oiv"]["payable_membership"], "yes")
        self.assertEqual(taxes["tax:radio"]["payable_membership"], "yes")
        self.assertEqual(taxes["tax:oiv"]["posting_requirement"], "separate")
        self.assertEqual(taxes["tax:radio"]["posting_requirement"], "separate")

        monetary = _by_ref(reconciled, "monetary_components")
        self.assertEqual(monetary["monetary:previous"]["posting_requirement"], "separate")
        self.assertEqual(monetary["monetary:next"]["posting_requirement"], "separate")

    def test_arithmetic_exact_result_overrides_contradictory_provider_hint(self) -> None:
        projection = _telecom_projection()
        projection["tax_components"][0]["included_in_payable"] = "no"

        reconciled = reconcile_monetary_projection(projection)
        oiv = _by_ref(reconciled, "tax_components")["tax:oiv"]

        self.assertEqual(reconciled["monetary_reconciliation"]["status"], "exact")
        self.assertEqual(oiv["payable_membership"], "yes")
        self.assertEqual(
            oiv["total_membership_basis"]["payable_total"],
            "arithmetic_exact",
        )

    def test_nonzero_residual_keeps_best_topology_and_warns(self) -> None:
        reconciled = reconcile_monetary_projection(
            _telecom_projection(payable_total="45.24")
        )

        summary = reconciled["monetary_reconciliation"]
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["reconciled_payable_total"], "45.25")
        self.assertEqual(summary["residual"], "-0.01")
        self.assertIn("monetary_reconciliation_residual", summary["warnings"])
        self.assertIn(
            "monetary_reconciliation_residual",
            reconciled["projection_warnings"],
        )
        self.assertEqual(len(summary["selected_component_refs"]), 4)

    def test_missing_payable_is_not_testable_but_known_effects_remain_postable(self) -> None:
        projection = _telecom_projection(payable_total="")

        reconciled = reconcile_monetary_projection(projection)

        summary = reconciled["monetary_reconciliation"]
        self.assertEqual(summary["status"], "not_testable")
        self.assertEqual(len(summary["selected_component_refs"]), 4)
        for section in ("tax_components", "monetary_components"):
            for item in reconciled[section]:
                self.assertEqual(item["posting_requirement"], "separate")

    def test_duplicate_vat_component_is_represented_and_not_counted_twice(self) -> None:
        projection = _telecom_projection()
        projection["tax_components"].insert(
            0,
            {
                "identity_ref": "vat:20",
                "decision_ref": "vat:20",
                "component_type": "vat",
                "canonical_tax_kind": "vat",
                "tax_amount": "2.81",
                "economic_effect": "increase_tax",
                "represented_by_refs": [],
            },
        )

        reconciled = reconcile_monetary_projection(projection)
        duplicate = reconciled["tax_components"][0]

        self.assertEqual(reconciled["monetary_reconciliation"]["status"], "exact")
        self.assertEqual(duplicate["posting_requirement"], "represented")
        self.assertEqual(duplicate["total_memberships"]["vat_total"], "yes")
        self.assertEqual(duplicate["total_memberships"]["line_net_total"], "no")
        self.assertEqual(duplicate["total_memberships"]["line_gross_total"], "yes")
        self.assertEqual(duplicate["total_memberships"]["tax_inclusive_total"], "yes")
        self.assertNotIn("vat:20", reconciled["monetary_reconciliation"]["selected_component_refs"])
        self.assertEqual(
            reconciled["monetary_reconciliation"]["reconciled_payable_total"],
            "45.25",
        )

    def test_telecom_reconciliation_drives_complete_balanced_journal(self) -> None:
        projection = reconcile_monetary_projection(_telecom_projection())
        candidates = {
            candidate_id: AccountingCandidate(
                candidate_id=candidate_id,
                code=candidate_id,
                name=f"Account {candidate_id}",
                roles=(),
                normalized_tax_id="",
                tax_office="",
                active=True,
                origin_round=0,
            )
            for candidate_id in ("320", "770", "191", "360", "649")
        }
        required_refs = required_decision_refs_for_projection(projection)
        proposal = parse_accounting_proposal(
            {
                "counterparty": {
                    "action": "select_existing",
                    "selected_candidate_id": "320",
                },
                "decisions": [
                    {
                        "decision_ref": ref,
                        "action": "select_existing",
                        "selected_candidate_id": (
                            "191" if ref.startswith("vat:") else
                            "360" if ref.startswith("tax:") else
                            "649" if ref.startswith("monetary:") else
                            "770"
                        ),
                        "selected_treatment": (
                            "expense_or_cost" if ref.startswith("tax:") else
                            "increase_payable" if ref == "monetary:previous" else
                            "reduce_payable" if ref == "monetary:next" else
                            ""
                        ),
                    }
                    for ref in required_refs
                    if ref != "counterparty"
                ],
            },
            required_decision_refs=required_refs,
            sent_candidates=candidates,
            projection=projection,
        )

        draft = build_journal_draft(projection, proposal)

        self.assertEqual(required_refs, (
            "counterparty",
            "line:monthly",
            "line:other",
            "vat:20",
            "tax:oiv",
            "tax:radio",
            "monetary:previous",
            "monetary:next",
        ))
        self.assertEqual(draft.line_for("tax:oiv").debit, Decimal("1.40"))
        self.assertEqual(draft.line_for("tax:radio").debit, Decimal("26.98"))
        self.assertEqual(draft.line_for("monetary:previous").debit, Decimal("0.17"))
        self.assertEqual(draft.line_for("monetary:next").credit, Decimal("0.15"))
        self.assertEqual(draft.line_for("counterparty").credit, Decimal("45.25"))
        self.assertFalse(any(line.resolution == "unresolved" for line in draft.lines))
        self.assertEqual(draft.total_debit, Decimal("45.40"))
        self.assertEqual(draft.total_credit, Decimal("45.40"))
        self.assertTrue(draft.is_balanced)


if __name__ == "__main__":
    unittest.main()
