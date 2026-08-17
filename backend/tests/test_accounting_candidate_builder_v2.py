from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_candidate_builder import (
    DEFAULT_INITIAL_CANDIDATE_LIMIT,
    build_accounting_candidates,
)
from app.domain.accounting_candidate_expansion import (
    AccountingCandidateSession,
    FinalizeProposalDecision,
    RequestMoreCandidatesDecision,
)


def _account(
    code: str,
    name: str,
    *,
    active: bool = True,
    tax_id: str = "",
    tax_office: str = "",
    aliases: tuple[str, ...] = (),
    roles: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "normalized_account_code": code,
        "account_name": name,
        "is_detail_account": True,
        "is_active": active,
        "tax_id": tax_id,
        "tax_office": tax_office,
        "aliases": list(aliases),
        "roles": list(roles),
    }


def _workspace(accounts: list[dict[str, object]]) -> dict[str, object]:
    return {"chart_accounts": {"accounts": accounts}}


def _purchase_projection(tax_id: str = "1234567890") -> dict[str, object]:
    return {
        "document_direction": "purchase",
        "supplier_party": {
            "title": "Ornek Tedarikci A.S.",
            "tax_id": tax_id,
            "tax_office": "Maslak",
        },
        "customer_party": {"title": "Fisero", "tax_id": "1111111111"},
        "tax_components": [],
        "vat_summary": [],
    }


@dataclass(frozen=True)
class _FullProposal:
    selected_candidate_ids: tuple[str, ...]
    decisions: tuple[tuple[str, str], ...]


class AccountingCandidateBuilderV2Tests(unittest.TestCase):
    def test_vat_rate_labels_parse_percent_yuzde_and_kdv_forms_without_360_blanket_role(self) -> None:
        accounts = [
            _account("191.01", "%20 Indirilecek KDV", roles=("vat",)),
            _account("191.02", "Yuzde 18 Indirilecek KDV", roles=("vat",)),
            _account("191.03", "KDV 10 Indirilecek", roles=("vat",)),
            _account("360.99", "Generic liability account"),
        ]
        projection = _purchase_projection()
        projection["tax_components"] = [
            {"source_label": "Ozel Iletisim Vergisi", "canonical_tax_kind": "special_tax"}
        ]

        catalog = build_accounting_candidates(_workspace(accounts), projection)

        self.assertEqual(catalog.candidate_by_id("191.01").vat_rates, ("20",))
        self.assertEqual(catalog.candidate_by_id("191.02").vat_rates, ("18",))
        self.assertEqual(catalog.candidate_by_id("191.03").vat_rates, ("10",))
        self.assertNotIn("special_tax", catalog.candidate_by_id("360.99").roles)

    def test_progressive_rounds_cover_half_then_complete_stable_real_universe(self) -> None:
        accounts = [
            _account(
                f"{100 + (index % 8) * 100}.{index:03d}",
                f"Stable account {index}",
                roles=(() if index % 3 else ("line_expense",)),
            )
            for index in range(121)
        ]
        catalog = build_accounting_candidates(
            _workspace(accounts),
            _purchase_projection("9999999999"),
        )

        broad = catalog.for_round(1)
        exhaustive = broad.for_round(2)

        self.assertEqual(len(catalog.sent_candidates), 40)
        self.assertEqual(len(broad.sent_candidates), 80)
        self.assertEqual(len(exhaustive.sent_candidates), 121)
        self.assertTrue(set(catalog.sent_candidate_ids).issubset(broad.sent_candidate_ids))
        self.assertTrue(set(broad.sent_candidate_ids).issubset(exhaustive.sent_candidate_ids))
        self.assertEqual(
            tuple(item.candidate_id for item in exhaustive.sent_candidates),
            tuple(item.candidate_id for item in catalog.relevance_order),
        )
        self.assertTrue(
            all(
                exhaustive.candidate_by_id(candidate_id).origin_round == 2
                for candidate_id in exhaustive.sent_candidate_ids
                if candidate_id not in broad.sent_candidate_ids
            )
        )

    def test_initial_pool_reserves_every_required_vat_rate_before_counterparty_fill(self) -> None:
        accounts = [
            _account(f"320.{index:03d}", f"Cari {index}", roles=("counterparty",))
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT + 20)
        ]
        accounts.extend(
            _account(
                f"191.01.{rate:03d}",
                f"%{rate} İND KDV",
                roles=("vat",),
            )
            for rate in (1, 8, 10, 18, 20)
        )
        projection = _purchase_projection()
        projection["vat_summary"] = [
            {"rate": str(rate), "vat_group_id": f"vat-{rate}"}
            for rate in (1, 8, 10, 18, 20)
        ]

        catalog = build_accounting_candidates(_workspace(accounts), projection)

        for rate in (1, 8, 10, 18, 20):
            candidate = catalog.candidate_by_id(f"191.01.{rate:03d}")
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.vat_rates, (str(rate),))
            self.assertIn(candidate.candidate_id, catalog.initial_candidate_ids)
        self.assertLessEqual(
            len(catalog.initial_candidate_ids), DEFAULT_INITIAL_CANDIDATE_LIMIT
        )
    def test_missing_active_state_keeps_legacy_tenant_account_active(self) -> None:
        account = _account("770.LEGACY", "Legacy active account")
        account.pop("is_active")

        catalog = build_accounting_candidates(
            _workspace([account]), _purchase_projection()
        )

        self.assertEqual(catalog.all_candidate_ids, ("770.LEGACY",))

    def test_terminal_account_statuses_are_inactive_while_missing_status_is_active(self) -> None:
        inactive_statuses = (
            "archived",
            "deleted",
            "suspended",
            "arşivlenmiş",
            "silinmiş",
            "askıda",
            "askıya alınmış",
        )
        accounts: list[dict[str, object]] = []
        for index, status in enumerate(inactive_statuses):
            account = _account(f"770.S{index}", f"Status {status}")
            account.pop("is_active")
            account["status"] = status
            accounts.append(account)
        active_without_status = _account("770.OK", "Missing status remains active")
        active_without_status.pop("is_active")
        accounts.append(active_without_status)

        catalog = build_accounting_candidates(
            _workspace(accounts), _purchase_projection()
        )

        self.assertEqual(catalog.all_candidate_ids, ("770.OK",))

    def test_false_like_active_and_detail_states_are_excluded(self) -> None:
        false_like_values = (
            False,
            0,
            "false",
            "0",
            "inactive",
            "pasif",
            "disabled",
            "closed",
        )
        accounts: list[dict[str, object]] = []
        for index, value in enumerate(false_like_values):
            accounts.append(
                {
                    **_account(f"770.I{index}", f"is_active {value}"),
                    "is_active": value,
                }
            )
            active_key_account = _account(f"770.A{index}", f"active {value}")
            active_key_account.pop("is_active")
            active_key_account["active"] = value
            accounts.append(active_key_account)
        accounts.extend(
            (
                {
                    **_account("770.D1", "String false detail"),
                    "is_detail_account": "false",
                },
                _account("770.OK", "Only active account"),
            )
        )

        catalog = build_accounting_candidates(
            _workspace(accounts), _purchase_projection()
        )

        self.assertEqual(catalog.all_candidate_ids, ("770.OK",))

    def test_inactive_accounts_never_enter_initial_or_expansion_results(self) -> None:
        catalog = build_accounting_candidates(
            _workspace(
                [
                    _account("770.01", "Aktif gider", roles=("line_expense",)),
                    _account(
                        "770.99",
                        "Pasif gizli gider",
                        active=False,
                        aliases=("bulunmamali",),
                    ),
                ]
            ),
            _purchase_projection(),
        )

        self.assertEqual(catalog.all_candidate_ids, ("770.01",))
        self.assertNotIn("770.99", catalog.initial_candidate_ids)
        self.assertEqual(catalog.expansion_search(("bulunmamali",)), ())

    def test_exact_normalized_tax_id_is_forced_into_bounded_initial_pool(self) -> None:
        accounts = [
            _account(f"770.{index:02d}", f"Gider {index}", roles=("line_expense",))
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT + 3)
        ]
        accounts.append(
            _account(
                "320.999",
                "Exact counterparty",
                tax_id="123 456 7890",
                roles=("counterparty",),
            )
        )
        accounts.append(
            _account(
                "320.998",
                "Inactive exact counterparty",
                active=False,
                tax_id="123-456-7890",
                roles=("counterparty",),
            )
        )

        catalog = build_accounting_candidates(
            _workspace(accounts),
            _purchase_projection("1234567890"),
        )

        self.assertIn("320.999", catalog.initial_candidate_ids)
        self.assertNotIn("320.998", catalog.initial_candidate_ids)
        self.assertLessEqual(
            len(catalog.initial_candidate_ids), DEFAULT_INITIAL_CANDIDATE_LIMIT
        )
        exact = catalog.candidate_by_id("320.999")
        self.assertEqual(exact.normalized_tax_id, "1234567890")
        self.assertEqual(exact.origin_round, 0)

    def test_all_supported_tax_id_aliases_force_exact_match_into_initial_pool(self) -> None:
        tax_id_keys = (
            "normalized_tax_id",
            "tax_id",
            "vkn",
            "tckn",
            "tax_identifier",
            "vergi_no",
        )
        fillers = [
            _account(f"770.{index:03d}", f"Gider {index}", roles=("line_expense",))
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT + 1)
        ]
        for tax_id_key in tax_id_keys:
            with self.subTest(tax_id_key=tax_id_key):
                exact_account = _account("880.999", "Alias exact tax account")
                exact_account[tax_id_key] = "123 456-7890"
                catalog = build_accounting_candidates(
                    _workspace([*fillers, exact_account]),
                    _purchase_projection("1234567890"),
                )

                self.assertIn("880.999", catalog.initial_candidate_ids)
                self.assertEqual(
                    catalog.candidate_by_id("880.999").normalized_tax_id,
                    "1234567890",
                )

    def test_expansion_search_indexes_tax_id_role_alias_code_name_and_tax_office(self) -> None:
        accounts = [
            _account(f"770.{index:03d}", f"Ordinary {index}")
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT)
        ]
        accounts.extend(
            (
                _account("880.01", "Vergi adayi", tax_id="987 654 3210"),
                _account("880.02", "Rol adayi", roles=("withholding_liability",)),
                _account("880.03", "Alias adayi", aliases=("fiber aboneligi",)),
                _account("760.04", "Kod adayi"),
                _account("880.05", "Arac Kiralama Giderleri"),
                _account("880.06", "Daire adayi", tax_office="Buyuk Mukellefler"),
            )
        )
        catalog = build_accounting_candidates(_workspace(accounts), _purchase_projection())

        cases = {
            "987 654-3210": "880.01",
            "withholding_liability": "880.02",
            "fiber aboneligi": "880.03",
            "76004": "760.04",
            "arac kiralama": "880.05",
            "buyuk mukellefler": "880.06",
        }
        for search_term, expected_candidate_id in cases.items():
            with self.subTest(search_term=search_term):
                found = catalog.expansion_search((search_term,))
                self.assertIn(expected_candidate_id, tuple(item.candidate_id for item in found))

    def test_expansion_filters_sent_candidates_before_applying_limit(self) -> None:
        accounts = [
            _account(
                f"770.{index:03d}",
                f"Shared account {index}",
                aliases=("shared-marker",),
            )
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT + 2)
        ]
        catalog = build_accounting_candidates(
            _workspace(accounts), _purchase_projection("9999999999")
        )

        found = catalog.expansion_search(("shared-marker",), limit=1)

        self.assertEqual(len(found), 1)
        self.assertNotIn(found[0].candidate_id, catalog.sent_candidate_ids)

    def test_candidate_order_and_code_dedup_are_source_order_independent(self) -> None:
        accounts = [
            {
                **_account("880.02", "Duplicate B"),
                "candidate_id": "candidate-b",
            },
            _account("770.02", "Second"),
            {
                **_account("880.02", "Duplicate A"),
                "candidate_id": "candidate-a",
            },
            _account("770.01", "First"),
        ]

        forward = build_accounting_candidates(
            _workspace(accounts), _purchase_projection("9999999999")
        )
        reversed_catalog = build_accounting_candidates(
            _workspace(list(reversed(accounts))), _purchase_projection("9999999999")
        )

        self.assertEqual(forward.all_candidate_ids, reversed_catalog.all_candidate_ids)
        self.assertEqual(forward.initial_candidate_ids, reversed_catalog.initial_candidate_ids)
        self.assertEqual(
            tuple(item.code for item in forward.real_candidates).count("880.02"), 1
        )
        self.assertIn("candidate-a", forward.all_candidate_ids)
        self.assertNotIn("candidate-b", forward.all_candidate_ids)

    def test_code_identity_uses_domain_normalization_and_preserves_preferred_real_record(self) -> None:
        accounts = [
            {
                **_account("770-01", "Hyphen variant"),
                "candidate_id": "variant-b",
            },
            {
                **_account("770 01", "Space variant"),
                "candidate_id": "variant-c",
            },
            {
                **_account("770.01", "Canonical real record"),
                "candidate_id": "canonical-a",
            },
        ]

        forward = build_accounting_candidates(
            _workspace(accounts), _purchase_projection()
        )
        reversed_catalog = build_accounting_candidates(
            _workspace(list(reversed(accounts))), _purchase_projection()
        )

        self.assertEqual(forward.all_candidate_ids, ("canonical-a",))
        self.assertEqual(reversed_catalog.all_candidate_ids, ("canonical-a",))
        preferred = forward.candidate_by_id("canonical-a")
        self.assertEqual(preferred.code, "770.01")
        self.assertEqual(preferred.name, "Canonical real record")

    def test_non_numeric_search_term_does_not_rank_empty_tax_id_as_exact(self) -> None:
        accounts = [
            _account(f"770.{index:03d}", f"Ordinary {index}")
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT)
        ]
        accounts.extend(
            (
                _account("900.02", "Expense candidate without tax"),
                _account("900.01", "Expense candidate with tax", tax_id="1234567890"),
            )
        )
        catalog = build_accounting_candidates(
            _workspace(accounts), _purchase_projection("9999999999")
        )

        found = catalog.expansion_search(("expense",), limit=1)

        self.assertEqual(tuple(item.code for item in found), ("900.01",))

    def test_expansion_catalog_accumulates_all_earlier_sent_candidates(self) -> None:
        accounts = [
            _account(f"770.{index:02d}", f"Ordinary {index}")
            for index in range(DEFAULT_INITIAL_CANDIDATE_LIMIT)
        ]
        accounts.extend(
            (
                _account("760.91", "First expansion alias", aliases=("first-marker",)),
                _account("760.92", "Second expansion alias", aliases=("second-marker",)),
            )
        )
        initial = build_accounting_candidates(
            _workspace(accounts), _purchase_projection("9999999999")
        )

        first = initial.with_expansion(("first-marker",), origin_round=1)
        second = first.with_expansion(("second-marker",), origin_round=2)

        self.assertTrue(set(initial.sent_candidate_ids).issubset(first.sent_candidate_ids))
        self.assertTrue(set(first.sent_candidate_ids).issubset(second.sent_candidate_ids))
        self.assertEqual(second.candidate_by_id("760.91").origin_round, 1)
        self.assertEqual(second.candidate_by_id("760.92").origin_round, 2)

    def test_full_provisional_proposal_survives_empty_expansion_and_provider_failure(self) -> None:
        proposal = _FullProposal(
            selected_candidate_ids=("A",),
            decisions=(("counterparty", "A"), ("line:1", "A"), ("vat:20", "A")),
        )
        empty_session = AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B"),
            initial_candidate_ids=("A",),
        ).record_decision(
            RequestMoreCandidatesDecision(
                search_terms=("missing",),
                requested_scope="full_chart",
                reason="Need another candidate",
                provisional_proposal=proposal,
            )
        )

        after_empty = empty_session.add_expansion_candidates(())

        self.assertEqual(after_empty.final_proposal, proposal)
        self.assertEqual(after_empty.final_action, "finalize")

        failed_session = AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B"),
            initial_candidate_ids=("A",),
        ).record_decision(
            RequestMoreCandidatesDecision(
                search_terms=("B",),
                requested_scope="full_chart",
                reason="Need another candidate",
                provisional_proposal=proposal,
            )
        )
        failed_session = failed_session.add_expansion_candidates(("B",))
        after_failure = failed_session.terminalize_best_available("provider_failed")

        self.assertEqual(after_failure.final_proposal, proposal)
        self.assertEqual(after_failure.final_action, "finalize")
        self.assertIn("provider_failed", after_failure.warnings)

    def test_session_allows_two_expansions_and_can_finalize_an_earlier_candidate(self) -> None:
        proposal = _FullProposal(
            selected_candidate_ids=("A",), decisions=(("counterparty", "A"),)
        )
        session = AccountingCandidateSession.start(
            tenant_candidate_ids=("A", "B", "C", "D"),
            initial_candidate_ids=("A",),
        )
        for candidate_id in ("B", "C"):
            session = session.record_decision(
                RequestMoreCandidatesDecision(
                    search_terms=(candidate_id,),
                    requested_scope="full_chart",
                    reason="expand",
                    provisional_proposal=proposal,
                )
            )
            session = session.add_expansion_candidates((candidate_id,))

        final = session.record_decision(FinalizeProposalDecision(proposal=proposal))

        self.assertEqual(final.expansion_count, 2)
        self.assertFalse(final.can_expand)
        self.assertEqual(final.selection_origin_round("A"), 0)
        self.assertEqual(final.final_proposal, proposal)


if __name__ == "__main__":
    unittest.main()
