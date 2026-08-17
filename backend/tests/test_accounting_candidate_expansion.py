from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _candidate_expansion_module(test_case: unittest.TestCase):
    module_name = "app.domain.accounting_candidate_expansion"
    test_case.assertIsNotNone(
        importlib.util.find_spec(module_name),
        "accounting candidate expansion domain module must exist",
    )
    return importlib.import_module(module_name)


class AccountingCandidateExpansionTests(unittest.TestCase):
    def test_full_proposal_validates_every_selected_account_and_preserves_all_roles(self) -> None:
        domain = _candidate_expansion_module(self)
        proposal = domain.AccountingProposal(
            counterparty_account=domain.SelectedAccount("320.01", "VKN eslesmesi"),
            line_accounts=(
                domain.LineAccountSelection("line-1", "770.01", "Hizmet gideri"),
                domain.LineAccountSelection("line-2", "770.02", "Diger hizmet"),
            ),
            vat_accounts=(
                domain.VatAccountSelection("vat-20", "20", "191.20", "Indirilecek KDV"),
            ),
            special_tax_accounts=(
                domain.SpecialTaxAccountSelection(
                    "tax-oiv", "special_tax", "360.08", "OIV hesabi"
                ),
            ),
        )
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("320.01", "770.01", "770.02", "191.20", "360.08"),
            initial_candidate_ids=("320.01", "770.01", "770.02", "191.20", "360.08"),
        )

        final = session.record_decision(
            domain.FinalizeProposalDecision(proposal=proposal, reason="Tam taslak")
        )

        self.assertEqual(final.final_action, "finalize")
        self.assertEqual(final.final_proposal, proposal)
        self.assertEqual(final.selection_origin_round("770.02"), 0)

    def test_full_proposal_rejects_each_unknown_or_unsent_selected_account(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("320.01", "770.01", "191.20", "360.08", "tenant-unsent"),
            initial_candidate_ids=("320.01", "770.01", "191.20", "360.08"),
        )
        invalid_proposals = (
            domain.AccountingProposal(
                counterparty_account=domain.SelectedAccount("tenant-unsent", "real but unsent")
            ),
            domain.AccountingProposal(
                line_accounts=(domain.LineAccountSelection("line-1", "foreign", "bad"),)
            ),
            domain.AccountingProposal(
                vat_accounts=(domain.VatAccountSelection("vat-20", "20", "foreign", "bad"),)
            ),
            domain.AccountingProposal(
                special_tax_accounts=(
                    domain.SpecialTaxAccountSelection("tax-oiv", "special_tax", "foreign", "bad"),
                )
            ),
        )

        for proposal in invalid_proposals:
            with self.subTest(proposal=proposal), self.assertRaises(domain.CandidateIntegrityError):
                session.record_decision(domain.FinalizeProposalDecision(proposal=proposal))

    def test_provisional_full_proposal_survives_expansion_and_can_reuse_earlier_candidates(self) -> None:
        domain = _candidate_expansion_module(self)
        provisional = domain.AccountingProposal(
            counterparty_account=domain.SelectedAccount("320.01", "VKN"),
            line_accounts=(domain.LineAccountSelection("line-1", "770.01", "ilk tercih"),),
            vat_accounts=(domain.VatAccountSelection("vat-20", "20", "191.20", "KDV"),),
            special_tax_accounts=(
                domain.SpecialTaxAccountSelection("tax-oiv", "special_tax", "360.08", "OIV"),
            ),
        )
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("320.01", "770.01", "191.20", "360.08", "360.09"),
            initial_candidate_ids=("320.01", "770.01", "191.20", "360.08"),
        ).record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("ozel vergi",),
                requested_scope="special_tax",
                reason="Alternatif OIV hesaplari",
                provisional_proposal=provisional,
            )
        )

        expanded = session.add_expansion_candidates(("360.09",))
        final = expanded.record_decision(
            domain.FinalizeProposalDecision(proposal=provisional, reason="Ilk liste hala en iyi")
        )

        self.assertEqual(session.provisional_proposal, provisional)
        self.assertEqual(final.final_proposal, provisional)
        self.assertEqual(final.selection_origin_round("360.08"), 0)

    def test_provider_failure_terminalizes_provisional_full_proposal_as_warning(self) -> None:
        domain = _candidate_expansion_module(self)
        provisional = domain.AccountingProposal(
            line_accounts=(domain.LineAccountSelection("line-1", "770.01", "best so far"),)
        )
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("770.01", "770.02"),
            initial_candidate_ids=("770.01",),
        ).record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("alternative",),
                requested_scope="expense",
                reason="Inspect",
                provisional_proposal=provisional,
            )
        ).add_expansion_candidates(("770.02",))

        terminal = session.terminalize_best_available("accounting_provider_failed")

        self.assertEqual(terminal.final_action, "finalize")
        self.assertEqual(terminal.final_proposal, provisional)
        self.assertIn("accounting_provider_failed", terminal.warnings)

    def test_first_round_can_select_any_real_sent_candidate(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("account-120", "account-153", "account-770"),
            initial_candidate_ids=("account-120", "account-770"),
        )

        selected = session.record_decision(
            domain.SelectExistingDecision(selected_candidate_id="account-770")
        )

        self.assertEqual(selected.final_action, "select_existing")
        self.assertEqual(selected.selected_candidate_id, "account-770")
        self.assertEqual(selected.selection_origin_round("account-770"), 0)
        self.assertEqual(selected.accounting_call_count, 1)
        self.assertEqual(selected.expansion_count, 0)

    def test_two_expansions_accumulate_candidates_and_allow_round_one_return(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B", "C", "D"),
            initial_candidate_ids=("A", "B"),
        )

        session = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                provisional_candidate_id="A",
                search_terms=("special tax",),
                requested_scope="broader_chart_slice",
                reason="A is best so far; inspect tax accounts.",
            )
        )
        session = session.add_expansion_candidates(("C",))
        session = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("other tax",),
                requested_scope="broader_chart_slice",
                reason="Inspect one more chart slice.",
            )
        )
        session = session.add_expansion_candidates(("D",))
        session = session.record_decision(
            domain.SelectExistingDecision(selected_candidate_id="A")
        )

        self.assertEqual(session.accumulated_candidate_ids, ("A", "B", "C", "D"))
        self.assertEqual(session.current_candidate_ids, ("A", "B", "C", "D"))
        self.assertEqual(session.selected_candidate_id, "A")
        self.assertEqual(session.selection_origin_round("A"), 0)
        self.assertEqual(session.selection_origin_round("D"), 2)
        self.assertEqual(session.accounting_call_count, 3)
        self.assertEqual(session.expansion_count, 2)
        self.assertEqual(len(session.rounds), 3)

    def test_expansion_limit_refuses_fourth_call_without_losing_provisional_choice(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B", "C"),
            initial_candidate_ids=("A",),
        )
        session = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                provisional_candidate_id="A",
                search_terms=("first",),
                requested_scope="broader_chart_slice",
                reason="Need another option.",
            )
        ).add_expansion_candidates(("B",))
        session = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("second",),
                requested_scope="broader_chart_slice",
                reason="Need a final option.",
            )
        ).add_expansion_candidates(("C",))

        capped = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("third",),
                requested_scope="full_chart",
                reason="Would like another call.",
            )
        )

        self.assertFalse(capped.can_expand)
        self.assertTrue(capped.expansion_limit_reached)
        self.assertEqual(capped.accounting_call_count, 3)
        self.assertEqual(capped.provisional_candidate_id, "A")
        self.assertEqual(capped.final_action, "select_existing")
        self.assertEqual(capped.selected_candidate_id, "A")
        self.assertIn("candidate_expansion_limit_reached", capped.warnings)

    def test_expansion_limit_without_provisional_terminalizes_as_unresolved(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B", "C"),
            initial_candidate_ids=("A",),
        )
        session = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("first",),
                requested_scope="broader_chart_slice",
                reason="Need another option.",
            )
        ).add_expansion_candidates(("B",))
        session = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("second",),
                requested_scope="broader_chart_slice",
                reason="Need a final option.",
            )
        ).add_expansion_candidates(("C",))

        capped = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("third",),
                requested_scope="full_chart",
                reason="Would like another call.",
            )
        )

        self.assertEqual(capped.final_action, "unresolved")
        self.assertIsNone(capped.selected_candidate_id)
        self.assertFalse(capped.can_expand)
        self.assertIn("candidate_expansion_limit_reached", capped.warnings)

    def test_empty_expansion_terminalizes_provisional_choice_without_throwing(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A",),
            initial_candidate_ids=("A",),
        ).record_decision(
            domain.RequestMoreCandidatesDecision(
                provisional_candidate_id="A",
                search_terms=("special tax",),
                requested_scope="broader_chart_slice",
                reason="Inspect other tax accounts.",
            )
        )

        try:
            terminal = session.add_expansion_candidates(())
        except domain.CandidateProtocolError as error:
            self.fail(f"empty expansion must be a non-throwing result: {error}")

        self.assertEqual(terminal.final_action, "select_existing")
        self.assertEqual(terminal.selected_candidate_id, "A")
        self.assertEqual(terminal.accounting_call_count, 1)
        self.assertFalse(terminal.can_expand)
        self.assertIn("candidate_expansion_returned_no_new_candidates", terminal.warnings)

    def test_duplicate_only_expansion_terminalizes_without_an_extra_call(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A",),
            initial_candidate_ids=("A",),
        ).record_decision(
            domain.RequestMoreCandidatesDecision(
                search_terms=("special tax",),
                requested_scope="broader_chart_slice",
                reason="Inspect other tax accounts.",
            )
        )

        try:
            terminal = session.add_expansion_candidates(("A", "A"))
        except domain.CandidateProtocolError as error:
            self.fail(f"duplicate-only expansion must be a non-throwing result: {error}")

        self.assertEqual(terminal.final_action, "unresolved")
        self.assertIsNone(terminal.selected_candidate_id)
        self.assertEqual(terminal.accounting_call_count, 1)
        self.assertFalse(terminal.can_expand)
        self.assertIn("candidate_expansion_returned_no_new_candidates", terminal.warnings)

    def test_provisional_selection_survives_expansion_until_final_decision(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B"),
            initial_candidate_ids=("A",),
        )
        requested = session.record_decision(
            domain.RequestMoreCandidatesDecision(
                provisional_candidate_id="A",
                search_terms=("alternative",),
                requested_scope="broader_chart_slice",
                reason="Check alternatives while retaining A.",
            )
        )

        expanded = requested.add_expansion_candidates(("B",))
        selected = expanded.record_decision(
            domain.SelectExistingDecision(selected_candidate_id="A")
        )

        self.assertEqual(requested.provisional_candidate_id, "A")
        self.assertEqual(expanded.provisional_candidate_id, "A")
        self.assertEqual(selected.selected_candidate_id, "A")

    def test_existing_selection_rejects_unknown_or_unsent_but_has_no_relevance_gate(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("contextually-obvious", "odd-but-real", "not-sent-yet"),
            initial_candidate_ids=("contextually-obvious", "odd-but-real"),
        )

        accepted = session.record_decision(
            domain.SelectExistingDecision(selected_candidate_id="odd-but-real")
        )
        self.assertEqual(accepted.selected_candidate_id, "odd-but-real")

        with self.assertRaises(domain.CandidateIntegrityError):
            session.record_decision(
                domain.SelectExistingDecision(selected_candidate_id="not-sent-yet")
            )
        with self.assertRaises(domain.CandidateIntegrityError):
            session.record_decision(
                domain.SelectExistingDecision(selected_candidate_id="another-tenant-account")
            )
        with self.assertRaises(domain.CandidateIntegrityError):
            domain.AccountingCandidateSession.start(
                tenant_candidate_ids=("A",),
                initial_candidate_ids=("A", "foreign"),
            )

    def test_propose_new_preserves_proposal_without_creating_or_selecting_candidate(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("counterparty-17",),
            initial_candidate_ids=("counterparty-17",),
        )
        proposal = domain.NewCounterpartyProposal(
            party_title="Example Supplier A.S.",
            tax_id="1234567890",
            direction="supplier",
            suggested_parent_family="320",
        )

        proposed = session.record_decision(domain.ProposeNewDecision(proposal=proposal))

        self.assertEqual(proposed.final_action, "propose_new")
        self.assertIsNone(proposed.selected_candidate_id)
        self.assertEqual(proposed.new_counterparty_proposal, proposal)
        self.assertEqual(proposed.tenant_candidate_ids, frozenset({"counterparty-17"}))
        self.assertEqual(proposed.accumulated_candidate_ids, ("counterparty-17",))
        self.assertFalse(hasattr(proposed, "create_counterparty"))

    def test_round_transcript_is_deterministic_and_records_each_ai_response(self) -> None:
        domain = _candidate_expansion_module(self)
        session = domain.AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B"),
            initial_candidate_ids=("A",),
        )
        request = domain.RequestMoreCandidatesDecision(
            provisional_candidate_id="A",
            search_terms=("tax",),
            requested_scope="broader_chart_slice",
            reason="Inspect more.",
        )
        session = session.record_decision(request).add_expansion_candidates(("B",))
        final = domain.SelectExistingDecision(selected_candidate_id="A")
        session = session.record_decision(final)

        self.assertEqual(session.rounds[0].candidate_ids, ("A",))
        self.assertEqual(session.rounds[0].decision, request)
        self.assertEqual(session.rounds[1].candidate_ids, ("A", "B"))
        self.assertEqual(session.rounds[1].decision, final)

    def test_hydration_rejects_more_than_three_accounting_call_rounds(self) -> None:
        domain = _candidate_expansion_module(self)
        rounds = tuple(
            domain.CandidateRound(round_index=index, candidate_ids=("A",))
            for index in range(4)
        )

        with self.assertRaises(domain.CandidateProtocolError):
            domain.AccountingCandidateSession(
                tenant_candidate_ids=frozenset({"A"}),
                rounds=rounds,
            )


if __name__ == "__main__":
    unittest.main()
