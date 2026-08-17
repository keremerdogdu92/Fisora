from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_candidate_builder import AccountingCandidate
from app.domain.accounting_candidate_expansion import CandidateIntegrityError
from app.domain.accounting_proposal import (
    AccountingProposalRequestV2,
    parse_accounting_proposal,
    parse_accounting_proposal_result,
)
from app.domain.openai_provider import GeminiAccountingProvider


def _candidate(
    candidate_id: str,
    *,
    role: str,
    active: bool = True,
) -> AccountingCandidate:
    return AccountingCandidate(
        candidate_id=candidate_id,
        code=candidate_id,
        name=f"Account {candidate_id}",
        roles=(role,),
        normalized_tax_id="",
        tax_office="",
        active=active,
        origin_round=0,
    )


def _sent_candidates() -> dict[str, AccountingCandidate]:
    return {
        "320": _candidate("320", role="counterparty"),
        "770": _candidate("770", role="line_expense"),
        "191": _candidate("191", role="vat"),
        "360": _candidate("360", role="special_tax"),
        "649": _candidate("649", role="unrelated_but_sent"),
    }


def _payload(*, counterparty_action: str = "select_existing") -> dict[str, object]:
    counterparty: dict[str, object] = {
        "action": counterparty_action,
        "selected_candidate_id": "320" if counterparty_action == "select_existing" else "",
        "reason": "counterparty",
    }
    if counterparty_action == "propose_new":
        counterparty["proposal"] = {
            "party_title": "New Supplier",
            "tax_id": "1234567890",
            "direction": "supplier",
            "suggested_parent_family": "320",
        }
    return {
        "counterparty": counterparty,
        "decisions": [
            {"decision_ref": "line:l1", "action": "select_existing", "selected_candidate_id": "770", "amount": "999999"},
            {"decision_ref": "vat:v20", "action": "select_existing", "selected_candidate_id": "191"},
            {"decision_ref": "tax:t1", "action": "select_existing", "selected_candidate_id": "360", "selected_treatment": "expense_or_cost"},
            {"decision_ref": "monetary:m1", "action": "select_existing", "selected_candidate_id": "649", "selected_treatment": "increase_payable"},
        ],
        "candidate_sufficiency": {
            "sufficient": False,
            "request_more_candidates": True,
            "search_terms": ["discount"],
            "reason": "need another option",
            "provisional": True,
        },
    }


class AccountingProposalV2Tests(unittest.TestCase):
    def test_line_and_vat_nonoperative_treatment_preserves_valid_candidates(self) -> None:
        projection = {
            "line_items": [{"decision_ref": "line:l1", "taxable_amount": "100.00"}],
            "vat_summary": [{"decision_ref": "vat:v20", "tax_amount": "20.00"}],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "line:l1",
                    "action": "select_existing",
                    "selected_candidate_id": "770",
                    "selected_treatment": "expense_or_cost",
                },
                {
                    "decision_ref": "vat:v20",
                    "action": "select_existing",
                    "selected_candidate_id": "191",
                    "selected_treatment": "deductible_tax",
                },
            ],
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "line:l1", "vat:v20"),
            sent_candidates=_sent_candidates(),
            projection=projection,
            round_index=1,
            chunk_index=2,
            receipt_artifact_id="receipt-nonoperative",
        )
        proposal = result.to_proposal(
            required_decision_refs=("counterparty", "line:l1", "vat:v20"),
            sent_candidate_ids=tuple(_sent_candidates()),
        )

        self.assertEqual(proposal.decision_for("line:l1").selected_candidate_id, "770")
        self.assertEqual(proposal.decision_for("vat:v20").selected_candidate_id, "191")
        self.assertEqual(proposal.decision_for("line:l1").selected_treatment, "")
        self.assertEqual(proposal.decision_for("vat:v20").selected_treatment, "")
        self.assertEqual(proposal.unresolved_decision_refs, ())
        self.assertEqual(
            tuple(issue.code for issue in result.issues),
            ("nonoperative_treatment_ignored", "nonoperative_treatment_ignored"),
        )
        self.assertTrue(
            all(issue.receipt_artifact_id == "receipt-nonoperative" for issue in result.issues)
        )

    def test_nonzero_tax_and_monetary_incomplete_treatment_preserves_suggestion(self) -> None:
        projection = {
            "tax_components": [{"decision_ref": "tax:t1", "tax_amount": "5.00"}],
            "monetary_components": [
                {"decision_ref": "monetary:m1", "source_amount": "3.00"},
            ],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "tax:t1",
                    "action": "select_existing",
                    "selected_candidate_id": "360",
                    "selected_treatment": "",
                },
                {
                    "decision_ref": "monetary:m1",
                    "action": "select_existing",
                    "selected_candidate_id": "649",
                    "selected_treatment": "provider-specific-unknown",
                },
            ],
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "tax:t1", "monetary:m1"),
            sent_candidates=_sent_candidates(),
            projection=projection,
            receipt_artifact_id="receipt-clarification",
        )
        proposal = result.to_proposal(
            required_decision_refs=("counterparty", "tax:t1", "monetary:m1"),
            sent_candidate_ids=tuple(_sent_candidates()),
        )

        tax = proposal.decision_for("tax:t1")
        monetary = proposal.decision_for("monetary:m1")
        self.assertEqual(tax.selected_candidate_id, "360")
        self.assertEqual(monetary.selected_candidate_id, "649")
        self.assertTrue(tax.treatment_review_required)
        self.assertTrue(monetary.treatment_review_required)
        self.assertEqual(
            proposal.treatment_clarification_refs,
            ("tax:t1", "monetary:m1"),
        )
        self.assertEqual(proposal.unresolved_decision_refs, ())
        self.assertEqual(
            tuple(issue.code for issue in result.issues),
            ("treatment_clarification_required", "treatment_clarification_required"),
        )
    def test_line_and_vat_extra_treatments_are_ignored_without_losing_valid_accounts(self) -> None:
        projection = {
            "line_items": [{"decision_ref": "line:l1", "taxable_amount": "100.00"}],
            "vat_summary": [{"decision_ref": "vat:v20", "tax_amount": "20.00"}],
            "tax_components": [],
            "monetary_components": [],
        }
        payload = {
            "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
            "decisions": [
                {
                    "decision_ref": "line:l1",
                    "action": "select_existing",
                    "selected_candidate_id": "770",
                    "selected_treatment": "expense_or_cost",
                },
                {
                    "decision_ref": "vat:v20",
                    "action": "select_existing",
                    "selected_candidate_id": "191",
                    "selected_treatment": "deductible_tax",
                },
            ],
            "candidate_sufficiency": {
                "sufficient": True,
                "request_more_candidates": False,
                "provisional": False,
            },
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "line:l1", "vat:v20"),
            sent_candidates=_sent_candidates(),
            projection=projection,
            receipt_artifact_id="receipt-raw-1",
        )
        proposal = result.to_proposal(
            required_decision_refs=("counterparty", "line:l1", "vat:v20"),
            sent_candidate_ids=tuple(_sent_candidates()),
        )

        self.assertEqual(proposal.decision_for("line:l1").selected_candidate_id, "770")
        self.assertEqual(proposal.decision_for("vat:v20").selected_candidate_id, "191")
        self.assertEqual(proposal.decision_for("line:l1").selected_treatment, "")
        self.assertEqual(proposal.decision_for("vat:v20").selected_treatment, "")
        self.assertEqual(
            [(issue.decision_ref, issue.code, issue.receipt_artifact_id) for issue in result.issues],
            [
                ("line:l1", "nonoperative_treatment_ignored", "receipt-raw-1"),
                ("vat:v20", "nonoperative_treatment_ignored", "receipt-raw-1"),
            ],
        )

    def test_nonzero_tax_and_monetary_missing_or_invalid_treatment_preserves_suggested_account(self) -> None:
        projection = {
            "line_items": [],
            "vat_summary": [],
            "tax_components": [{"decision_ref": "tax:t1", "tax_amount": "5.00"}],
            "monetary_components": [{"decision_ref": "monetary:m1", "source_amount": "2.00"}],
        }
        payload = {
            "counterparty": {"action": "select_existing", "selected_candidate_id": "320"},
            "decisions": [
                {
                    "decision_ref": "tax:t1",
                    "action": "select_existing",
                    "selected_candidate_id": "360",
                    "selected_treatment": "",
                },
                {
                    "decision_ref": "monetary:m1",
                    "action": "select_existing",
                    "selected_candidate_id": "649",
                    "selected_treatment": "not-a-treatment",
                },
            ],
            "candidate_sufficiency": {
                "sufficient": True,
                "request_more_candidates": False,
                "provisional": False,
            },
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "tax:t1", "monetary:m1"),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )
        proposal = result.to_proposal(
            required_decision_refs=("counterparty", "tax:t1", "monetary:m1"),
            sent_candidate_ids=tuple(_sent_candidates()),
        )

        self.assertEqual(proposal.unresolved_decision_refs, ())
        self.assertEqual(proposal.decision_for("tax:t1").selected_candidate_id, "360")
        self.assertEqual(proposal.decision_for("monetary:m1").selected_candidate_id, "649")
        self.assertEqual(proposal.decision_for("tax:t1").selected_treatment, "")
        self.assertEqual(proposal.decision_for("monetary:m1").selected_treatment, "")
        self.assertEqual(
            [(issue.decision_ref, issue.code) for issue in result.issues],
            [
                ("tax:t1", "treatment_clarification_required"),
                ("monetary:m1", "treatment_clarification_required"),
            ],
        )

    def test_partial_parse_retains_valid_decisions_and_links_sanitized_issues(self) -> None:
        projection = {
            "line_items": [
                {"decision_ref": "line:l1", "taxable_amount": "100.00"},
            ],
            "vat_summary": [
                {"decision_ref": "vat:v20", "tax_amount": "20.00"},
            ],
            "tax_components": [
                {"decision_ref": "tax:t1", "tax_amount": "5.00"},
            ],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "line:l1",
                    "action": "select_existing",
                    "selected_candidate_id": "770",
                },
                {
                    "decision_ref": "vat:v20",
                    "action": "select_existing",
                    "selected_candidate_id": "provider-secret-unsent-id",
                },
            ],
            "candidate_sufficiency": {
                "sufficient": True,
                "request_more_candidates": False,
                "provisional": False,
            },
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1"),
            sent_candidates=_sent_candidates(),
            projection=projection,
            round_index=2,
            chunk_index=3,
            receipt_artifact_id="receipt-7",
        )

        self.assertEqual(result.counterparty.decision_ref, "counterparty")
        self.assertEqual(
            tuple(decision.decision_ref for decision in result.valid_decisions),
            ("counterparty", "line:l1"),
        )
        self.assertEqual(
            tuple(issue.decision_ref for issue in result.issues),
            ("vat:v20", "tax:t1"),
        )
        self.assertEqual(result.issues[0].code, "candidate_integrity_invalid")
        self.assertNotIn("provider-secret-unsent-id", result.issues[0].message)
        self.assertEqual(result.issues[0].round_index, 2)
        self.assertEqual(result.issues[0].chunk_index, 3)
        self.assertEqual(result.issues[0].receipt_artifact_id, "receipt-7")
        self.assertTrue(result.sufficiency["sufficient"])

    def test_zero_fact_actions_and_compatibility_shape_are_normalized_without_candidates(self) -> None:
        projection = {
            "vat_summary": [
                {"decision_ref": "vat:v0", "tax_amount": "0.00"},
            ],
            "tax_components": [
                {"decision_ref": "tax:t0", "tax_amount": "0"},
            ],
            "monetary_components": [
                {"decision_ref": "monetary:m0", "source_amount": "0,00"},
            ],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "vat:v0",
                    "action": "select_existing",
                    "selected_candidate_id": "",
                },
                {
                    "decision_ref": "tax:t0",
                    "action": "no_separate_posting",
                    "selected_candidate_id": "",
                    "selected_treatment": "no_separate_posting",
                },
                {
                    "decision_ref": "monetary:m0",
                    "action": "no_separate_posting",
                    "selected_candidate_id": "",
                    "selected_treatment": "no_separate_posting",
                },
            ],
        }

        proposal = parse_accounting_proposal(
            payload,
            required_decision_refs=(
                "counterparty",
                "vat:v0",
                "tax:t0",
                "monetary:m0",
            ),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )

        self.assertEqual(proposal.counterparty.selected_treatment, "")
        self.assertEqual(proposal.decision_for("vat:v0").action, "no_separate_posting")
        self.assertEqual(proposal.decision_for("vat:v0").selected_treatment, "")
        self.assertEqual(proposal.decision_for("tax:t0").selected_treatment, "no_separate_posting")
        self.assertEqual(proposal.decision_for("monetary:m0").selected_treatment, "no_separate_posting")
        self.assertEqual(proposal.selected_candidate_ids, ("320",))

    def test_zero_fact_sent_candidate_is_normalized_to_no_separate_posting(self) -> None:
        projection = {
            "tax_components": [
                {"decision_ref": "tax:t0", "tax_amount": "0.00"},
            ],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "tax:t0",
                    "action": "select_existing",
                    "selected_candidate_id": "360",
                    "selected_treatment": "expense_or_cost",
                    "reason": "provider returned a posting-shaped zero fact",
                },
            ],
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "tax:t0"),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )

        decision = result.valid_decisions[1]
        self.assertEqual(decision.action, "no_separate_posting")
        self.assertEqual(decision.selected_candidate_id, "")
        self.assertEqual(decision.selected_treatment, "no_separate_posting")
        self.assertEqual(
            [issue.code for issue in result.issues],
            ["zero_fact_normalized_to_no_separate_posting"],
        )
        proposal = parse_accounting_proposal(
            payload,
            required_decision_refs=("counterparty", "tax:t0"),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )
        self.assertEqual(
            proposal.decision_for("tax:t0").action,
            "no_separate_posting",
        )

        request = AccountingProposalRequestV2(
            projection=projection,
            sent_candidates=tuple(_sent_candidates().values()),
            required_decision_refs=("counterparty", "tax:t0"),
        )
        variants = request.to_schema_payload()["output_schema"]["properties"][
            "decisions"
        ]["items"]["anyOf"]
        self.assertEqual(
            [variant["properties"]["action"]["enum"] for variant in variants],
            [["no_separate_posting"]],
        )

    def test_zero_fact_invalid_treatment_is_nonoperative_after_candidate_integrity(self) -> None:
        projection = {
            "monetary_components": [
                {"decision_ref": "monetary:m0", "source_amount": "0.00"},
            ],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "monetary:m0",
                    "action": "select_existing",
                    "selected_candidate_id": "649",
                    "selected_treatment": "provider-invented-treatment",
                },
            ],
        }

        result = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "monetary:m0"),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )

        decision = result.valid_decisions[1]
        self.assertEqual(decision.action, "no_separate_posting")
        self.assertEqual(decision.selected_candidate_id, "")
        self.assertEqual(decision.selected_treatment, "no_separate_posting")
        self.assertEqual(
            [issue.code for issue in result.issues],
            ["zero_fact_normalized_to_no_separate_posting"],
        )

        payload["decisions"][0]["selected_candidate_id"] = "unsent-candidate"
        rejected = parse_accounting_proposal_result(
            payload,
            required_decision_refs=("counterparty", "monetary:m0"),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )
        self.assertNotIn(
            "monetary:m0",
            {decision.decision_ref for decision in rejected.valid_decisions},
        )
        self.assertEqual(rejected.issues[0].code, "candidate_integrity_invalid")

    def test_nonzero_fact_cannot_use_zero_only_compatibility_or_action(self) -> None:
        projection = {
            "vat_summary": [
                {"decision_ref": "vat:v20", "tax_amount": "20.00"},
            ],
            "tax_components": [
                {"decision_ref": "tax:t1", "tax_amount": "5.00"},
            ],
        }
        base = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
        }
        cases = (
            {
                **base,
                "decisions": [
                    {
                        "decision_ref": "vat:v20",
                        "action": "select_existing",
                        "selected_candidate_id": "",
                    }
                ],
            },
            {
                **base,
                "decisions": [
                    {
                        "decision_ref": "tax:t1",
                        "action": "no_separate_posting",
                        "selected_candidate_id": "",
                        "selected_treatment": "no_separate_posting",
                    }
                ],
            },
        )

        for payload, required in zip(
            cases,
            (("counterparty", "vat:v20"), ("counterparty", "tax:t1")),
            strict=True,
        ):
            with self.subTest(decision_ref=required[-1]):
                with self.assertRaises((ValueError, CandidateIntegrityError)):
                    parse_accounting_proposal(
                        payload,
                        required_decision_refs=required,
                        sent_candidates=_sent_candidates(),
                        projection=projection,
                    )

    def test_no_separate_posting_is_limited_to_zero_vat_tax_and_monetary_facts(self) -> None:
        projection = {
            "line_items": [
                {"decision_ref": "line:l0", "taxable_amount": "0.00"},
            ],
            "tax_components": [
                {"decision_ref": "tax:t1", "tax_amount": "5.00"},
            ],
        }
        cases = (
            (
                "line:l0",
                {
                    "action": "no_separate_posting",
                    "selected_candidate_id": "",
                },
            ),
            (
                "tax:t1",
                {
                    "action": "excluded",
                    "selected_candidate_id": "",
                    "reason": "Not a monetary fact",
                },
            ),
        )

        for decision_ref, decision in cases:
            with self.subTest(decision_ref=decision_ref):
                with self.assertRaises(ValueError):
                    parse_accounting_proposal(
                        {
                            "counterparty": {
                                "action": "select_existing",
                                "selected_candidate_id": "320",
                            },
                            "decisions": [
                                {"decision_ref": decision_ref, **decision}
                            ],
                        },
                        required_decision_refs=("counterparty", decision_ref),
                        sent_candidates=_sent_candidates(),
                        projection=projection,
                    )

    def test_represented_and_excluded_require_nonzero_fact_evidence_and_treatment(self) -> None:
        projection = {
            "tax_components": [
                {"decision_ref": "tax:t1", "tax_amount": "5.00"},
            ],
            "monetary_components": [
                {"decision_ref": "monetary:m1", "source_amount": "3.00"},
            ],
        }
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320",
            },
            "decisions": [
                {
                    "decision_ref": "tax:t1",
                    "action": "represented",
                    "selected_candidate_id": "",
                    "selected_treatment": "represented_in_line",
                    "reason": "Included in canonical line amount",
                },
                {
                    "decision_ref": "monetary:m1",
                    "action": "excluded",
                    "selected_candidate_id": "",
                    "selected_treatment": "excluded",
                    "reason": "Observed but outside current payable topology",
                },
            ],
        }

        proposal = parse_accounting_proposal(
            payload,
            required_decision_refs=("counterparty", "tax:t1", "monetary:m1"),
            sent_candidates=_sent_candidates(),
            projection=projection,
        )

        self.assertEqual(proposal.decision_for("tax:t1").action, "represented")
        self.assertEqual(proposal.decision_for("monetary:m1").action, "excluded")

        payload["decisions"][0]["reason"] = ""
        with self.assertRaises(ValueError):
            parse_accounting_proposal(
                payload,
                required_decision_refs=("counterparty", "tax:t1", "monetary:m1"),
                sent_candidates=_sent_candidates(),
                projection=projection,
            )

    def test_request_is_compact_fact_only_and_uses_v2_candidate_stage(self) -> None:
        projection = {
            "document_direction": "purchase",
            "header": {"currency_code": "TRY"},
            "line_items": [{"decision_ref": "line:l1", "taxable_amount": "100.00"}],
            "vat_summary": [],
            "tax_components": [],
            "monetary_components": [],
            "totals": {"payable_total": "100.00"},
            "client_context": {"internal_note": "must-not-enter-raw-line"},
            "warnings": ["canonical_warning"],
            "projection_warnings": ["projection_warning"],
            "source_field_links": [{"evidence": ["raw-private"]}],
        }
        request = AccountingProposalRequestV2(
            projection=projection,
            sent_candidates=tuple(_sent_candidates().values()),
            required_decision_refs=("counterparty", "line:l1"),
        )

        payload = request.to_schema_payload()

        self.assertEqual(request.context.candidate_strategy.stage, "accounting_selection_v2")
        self.assertEqual(payload["candidate_strategy"]["stage"], "accounting_selection_v2")
        raw_line = json.loads(payload["raw_line"])
        self.assertEqual(raw_line["line_items"], projection["line_items"])
        self.assertNotIn("source_field_links", raw_line)
        self.assertEqual(raw_line["warnings"], ["canonical_warning"])
        self.assertEqual(raw_line["projection_warnings"], ["projection_warning"])
        self.assertEqual(raw_line["client_context"], {})
        self.assertTrue(all(item["is_active"] for item in payload["account_candidates"]))
        self.assertIn("candidate_sufficiency", payload["output_schema"]["required"])
        self.assertIn("counterparty", payload["output_schema"]["required"])
        self.assertIn("decisions", payload["output_schema"]["required"])
        decision_schema = payload["output_schema"]["properties"]["decisions"]
        self.assertEqual(decision_schema.get("minItems"), 1)
        self.assertEqual(decision_schema.get("maxItems"), 1)
        self.assertEqual(
            decision_schema["items"]["properties"]["decision_ref"]["enum"],
            ["line:l1"],
        )
        candidate_ids = list(_sent_candidates())
        self.assertEqual(
            decision_schema["items"]["properties"]["selected_candidate_id"]["enum"],
            ["", *candidate_ids],
        )
        self.assertEqual(
            payload["output_schema"]["properties"]["counterparty"]["properties"]
            ["selected_candidate_id"]["enum"],
            ["", *candidate_ids],
        )

    def test_request_exposes_safe_client_context_and_reaches_gemini_http_boundary(self) -> None:
        class RaisingHttp:
            called = False
            body: dict[str, object] = {}

            def post(self, url, *, headers, content, timeout):
                self.called = True
                self.body = json.loads(content)
                raise RuntimeError("boundary reached")

        http = RaisingHttp()
        request = AccountingProposalRequestV2(
            projection={
                "document_direction": "purchase",
                "line_items": [], "vat_summary": [], "tax_components": [],
                "monetary_components": [], "totals": {"payable_total": "0"},
                "warnings": [], "projection_warnings": [],
                "client_context": {
                    "activity_description": "Hearing center",
                    "nace_code": "47.74",
                    "activity_tags": ["retail", "health"],
                    "secret": "drop",
                    "nested": {"drop": True},
                },
            },
            sent_candidates=tuple(_sent_candidates().values()),
            required_decision_refs=("counterparty",),
        )
        payload = request.to_schema_payload()
        raw_line = json.loads(payload["raw_line"])
        self.assertEqual(payload["client_activity"], "Hearing center")
        self.assertEqual(
            raw_line["client_context"],
            {"activity_description": "Hearing center", "nace_code": "47.74", "activity_tags": ["retail", "health"]},
        )
        provider = GeminiAccountingProvider(api_key="test-key", http_client=http)

        with self.assertRaisesRegex(Exception, "boundary reached"):
            provider.classify_product(request)

        self.assertTrue(http.called)
        sent_text = http.body["contents"][0]["parts"][0]["text"]
        sent_projection = json.loads(sent_text.split("\n", 1)[1])
        self.assertEqual(sent_projection["stage"], "accounting_selection_v2")

    def test_parser_covers_all_decision_families_and_ignores_ai_amounts(self) -> None:
        required = ("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1")

        proposal = parse_accounting_proposal(
            _payload(), required_decision_refs=required, sent_candidates=_sent_candidates()
        )

        self.assertEqual(tuple(item.decision_ref for item in proposal.decisions), required)
        self.assertEqual(proposal.selected_candidate_ids, ("320", "770", "191", "360", "649"))
        self.assertFalse(hasattr(proposal.decision_for("line:l1"), "amount"))
        self.assertTrue(proposal.request_more_candidates)
        self.assertTrue(proposal.provisional)

    def test_any_sent_active_candidate_is_allowed_without_role_veto(self) -> None:
        payload = _payload()
        payload["decisions"][0]["selected_candidate_id"] = "649"

        proposal = parse_accounting_proposal(
            payload,
            required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"),
            sent_candidates=_sent_candidates(),
        )

        self.assertEqual(proposal.decision_for("line:l1").selected_candidate_id, "649")

    def test_unknown_unsent_tenant_external_and_inactive_candidates_are_integrity_errors(self) -> None:
        cases = (
            ("unknown", "999", _sent_candidates()),
            ("unsent", "770", {"320": _sent_candidates()["320"]}),
            ("tenant_external", "external", _sent_candidates()),
            ("inactive", "inactive", {**_sent_candidates(), "inactive": _candidate("inactive", role="vat", active=False)}),
        )
        for label, candidate_id, candidates in cases:
            with self.subTest(case=label):
                payload = _payload()
                payload["decisions"][0]["selected_candidate_id"] = candidate_id
                with self.assertRaises(CandidateIntegrityError):
                    parse_accounting_proposal(
                        payload,
                        required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"),
                        sent_candidates=candidates,
                    )

    def test_parser_repairs_only_an_exact_duplicate_namespace_prefix(self) -> None:
        payload = _payload()
        payload["decisions"][1]["decision_ref"] = "vat:vat:v20"

        proposal = parse_accounting_proposal(
            payload,
            required_decision_refs=(
                "counterparty",
                "line:l1",
                "vat:v20",
                "tax:t1",
                "monetary:m1",
            ),
            sent_candidates=_sent_candidates(),
        )

        self.assertEqual(proposal.decision_for("vat:v20").selected_candidate_id, "191")

        payload["decisions"][1]["decision_ref"] = "vat:invented"
        with self.assertRaises(ValueError):
            parse_accounting_proposal(
                payload,
                required_decision_refs=(
                    "counterparty",
                    "line:l1",
                    "vat:v20",
                    "tax:t1",
                    "monetary:m1",
                ),
                sent_candidates=_sent_candidates(),
            )

    def test_propose_new_is_preserved_and_missing_selection_becomes_unresolved(self) -> None:
        payload = _payload(counterparty_action="propose_new")
        payload["decisions"] = payload["decisions"][:-1]

        proposal = parse_accounting_proposal(
            payload,
            required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"),
            sent_candidates=_sent_candidates(),
        )

        self.assertEqual(proposal.counterparty.action, "propose_new")
        self.assertEqual(proposal.counterparty.proposal["party_title"], "New Supplier")
        self.assertEqual(proposal.decision_for("monetary:m1").action, "unresolved")

    def test_invalid_propose_new_shape_and_non_boolean_sufficiency_are_rejected(self) -> None:
        invalid_proposal = _payload(counterparty_action="propose_new")
        invalid_proposal["counterparty"]["proposal"]["direction"] = ""
        invalid_boolean = _payload()
        invalid_boolean["candidate_sufficiency"]["sufficient"] = "false"
        contradictory = _payload()
        contradictory["candidate_sufficiency"]["sufficient"] = True
        with self.assertRaises(ValueError):
            parse_accounting_proposal(invalid_proposal, required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"), sent_candidates=_sent_candidates())
        with self.assertRaises(ValueError):
            parse_accounting_proposal(invalid_boolean, required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"), sent_candidates=_sent_candidates())
        with self.assertRaises(ValueError):
            parse_accounting_proposal(contradictory, required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"), sent_candidates=_sent_candidates())

    def test_schema_uses_supported_action_variants_and_parser_enforces_them(self) -> None:
        request = AccountingProposalRequestV2(
            projection={"document_direction": "purchase", "line_items": [{"decision_ref": "line:l1"}]},
            sent_candidates=tuple(_sent_candidates().values()),
            required_decision_refs=("counterparty", "line:l1"),
        )
        schema = request.to_schema_payload()["output_schema"]

        def mappings(value: object):
            if isinstance(value, dict):
                yield value
                for nested in value.values():
                    yield from mappings(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from mappings(nested)

        schema_mappings = tuple(mappings(schema))
        self.assertFalse(any("const" in item for item in schema_mappings))
        decision_schema = schema["properties"]["decisions"]["items"]
        counterparty_schema = schema["properties"]["counterparty"]
        self.assertNotIn("oneOf", decision_schema)
        self.assertNotIn("oneOf", counterparty_schema)
        self.assertEqual(
            [variant["properties"]["action"]["enum"] for variant in decision_schema["anyOf"]],
            [["select_existing"], ["unresolved"], ["represented"]],
        )
        self.assertEqual(
            [variant["properties"]["action"]["enum"] for variant in counterparty_schema["anyOf"]],
            [["select_existing"], ["unresolved"], ["propose_new"]],
        )
        self.assertEqual(
            counterparty_schema["anyOf"][0]["properties"]["proposal"],
            {"type": "null"},
        )
        self.assertEqual(
            counterparty_schema["anyOf"][1]["properties"]["selected_candidate_id"]["enum"],
            [""],
        )
        proposed = counterparty_schema["anyOf"][2]["properties"]["proposal"]
        self.assertEqual(
            proposed["required"],
            ["party_title", "tax_id", "direction", "suggested_parent_family"],
        )
        self.assertFalse(proposed["additionalProperties"])
        base = {
            "decisions": [
                {"decision_ref": "line:l1", "action": "select_existing", "selected_candidate_id": "770", "reason": "line"}
            ],
            "candidate_sufficiency": {
                "sufficient": True,
                "request_more_candidates": False,
                "search_terms": [],
                "reason": "enough",
                "provisional": False,
            },
        }
        select_existing = {
            **base,
            "counterparty": {"action": "select_existing", "selected_candidate_id": "320", "reason": "match", "proposal": None},
        }
        unresolved = {
            **base,
            "counterparty": {"action": "unresolved", "selected_candidate_id": "", "reason": "missing", "proposal": None},
        }
        propose_new = {
            **base,
            "counterparty": {
                "action": "propose_new", "selected_candidate_id": "", "reason": "new", "proposal": {
                    "party_title": "New Supplier", "tax_id": "1234567890", "direction": "supplier", "suggested_parent_family": "320"
                },
            },
        }
        invalid_new = {
            **base,
            "counterparty": {"action": "propose_new", "selected_candidate_id": "", "reason": "new", "proposal": None},
        }

        invalid_select = {
            **base,
            "counterparty": {"action": "select_existing", "selected_candidate_id": "", "reason": "bad", "proposal": None},
        }
        invalid_unresolved = {
            **base,
            "counterparty": {"action": "unresolved", "selected_candidate_id": "320", "reason": "bad", "proposal": None},
        }
        invalid_line_action = {
            **select_existing,
            "decisions": [{"decision_ref": "line:l1", "action": "unresolved", "selected_candidate_id": "770", "reason": "bad"}],
        }
        self.assertEqual(
            parse_accounting_proposal(
                select_existing,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            ).counterparty.proposal,
            {},
        )
        self.assertEqual(
            parse_accounting_proposal(
                unresolved,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            ).counterparty.proposal,
            {},
        )
        self.assertEqual(
            parse_accounting_proposal(
                propose_new,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            ).counterparty.proposal["party_title"],
            "New Supplier",
        )
        with self.assertRaises(ValueError):
            parse_accounting_proposal(
                invalid_new,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            )
        with self.assertRaises(CandidateIntegrityError):
            parse_accounting_proposal(
                invalid_select,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            )
        with self.assertRaises(ValueError):
            parse_accounting_proposal(
                invalid_unresolved,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            )
        with self.assertRaises(ValueError):
            parse_accounting_proposal(
                invalid_line_action,
                required_decision_refs=("counterparty", "line:l1"),
                sent_candidates=_sent_candidates(),
            )

    def test_propose_new_fields_must_be_actual_strings(self) -> None:
        for field_name in ("party_title", "tax_id", "direction", "suggested_parent_family"):
            with self.subTest(field=field_name):
                payload = _payload(counterparty_action="propose_new")
                payload["counterparty"]["proposal"][field_name] = 123
                with self.assertRaises(ValueError):
                    parse_accounting_proposal(
                        payload,
                        required_decision_refs=("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"),
                        sent_candidates=_sent_candidates(),
                    )

    def test_parser_rejects_proposal_replayed_into_non_proposal_actions(self) -> None:
        required = ("counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1")

        for fabricated in ({}, {"party_title": "fabricated"}, "fabricated"):
            with self.subTest(action="select_existing", proposal=fabricated):
                payload = _payload()
                payload["counterparty"]["proposal"] = fabricated
                with self.assertRaises(ValueError):
                    parse_accounting_proposal(
                        payload,
                        required_decision_refs=required,
                        sent_candidates=_sent_candidates(),
                    )

            with self.subTest(action="unresolved", proposal=fabricated):
                payload = _payload()
                payload["counterparty"] = {
                    "action": "unresolved",
                    "selected_candidate_id": "",
                    "reason": "missing",
                    "proposal": fabricated,
                }
                with self.assertRaises(ValueError):
                    parse_accounting_proposal(
                        payload,
                        required_decision_refs=required,
                        sent_candidates=_sent_candidates(),
                    )

        for fabricated in (None, {}, {"party_title": "fabricated"}, "fabricated"):
            with self.subTest(action="line", proposal=fabricated):
                payload = _payload()
                payload["decisions"][0]["proposal"] = fabricated
                with self.assertRaises(ValueError):
                    parse_accounting_proposal(
                        payload,
                        required_decision_refs=required,
                        sent_candidates=_sent_candidates(),
                    )

    def test_parser_accepts_only_projection_declared_identity_aliases(self) -> None:
        candidates = _sent_candidates()
        payload = _payload()
        payload["decisions"] = [{
            "decision_ref": "line:source-line-17",
            "action": "select_existing",
            "selected_candidate_id": "770",
        }]
        payload["candidate_sufficiency"] = {
            "sufficient": True,
            "request_more_candidates": False,
            "search_terms": [],
            "reason": "enough",
            "provisional": False,
        }

        parsed = parse_accounting_proposal(
            payload,
            required_decision_refs=("counterparty", "line:group-a"),
            sent_candidates=candidates,
            decision_ref_aliases={"line:source-line-17": "line:group-a"},
        )

        self.assertEqual("line:group-a", parsed.decisions[1].decision_ref)
        with self.assertRaisesRegex(ValueError, "unexpected accounting decision ref"):
            parse_accounting_proposal(
                payload,
                required_decision_refs=("counterparty", "line:group-a"),
                sent_candidates=candidates,
                decision_ref_aliases={"line:other": "line:group-a"},
            )

if __name__ == "__main__":
    unittest.main()
