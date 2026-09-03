# File: backend/tests/test_learning_rule_lifecycle.py
# Summary: Verifies confirmed learning-rule versioning, lifecycle safety, and compilation into narrow accountant-authorized posting authorities.
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.invoice_ai_gate import VerifiedRuleAuthorityV1
from app.domain.matching_simulation import AccountSelection
from app.domain.verified_rule_authority import (
    LearningRuleConflict,
    VerifiedRuleRecordV1,
    compile_verified_rule_authorities,
)
from app.persistence.learning_rule_repository import LearningRuleRepository
from app.services.learning_rule_service import LearningRuleService


def _snapshot(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "client_id": "firma-1",
        "scope": "client_counterparty",
        "direction": "purchase",
        "invoice_mode": "ordinary",
        "counterparty_tax_id": "1234567890",
        "line_match_mode": "all_lines",
        "normalized_terms": (),
        "semantic_role": "expense",
        "account_code": "770.03.001",
        "activation_event_id": "activation-1",
        "source_review_decision_id": "review-1",
        "confirmed_actor_id": "accountant",
        "confirmation_provenance": {"source": "accountant_confirmed"},
    }
    result.update(overrides)
    return result


def _account_selection(*, active: bool = True, detail: bool = True) -> AccountSelection:
    return AccountSelection(
        chart_file_name="firma-1.xlsx",
        expense_account="770.03.001",
        purchase_vat_account="191.01",
        supplier_account="320.01",
        bank_account="102.01",
        selection_notes=(),
        account_candidates={
            "purchase_expense": (
                {
                    "code": "770.03.001",
                    "normalized_account_code": "770.03.001",
                    "is_active": active,
                    "is_detail_account": detail,
                    "direction": "purchase",
                    "semantic_roles": ["expense"],
                },
            ),
        },
    )


def _record(**overrides: object) -> VerifiedRuleRecordV1:
    values = {
        "rule_id": "rule-1",
        "rule_key": "client:firma-1:supplier:1234567890:dogalgaz",
        "version": 1,
        "status": "active",
        **_snapshot(),
    }
    values.update(overrides)
    return VerifiedRuleRecordV1.from_mapping(values)


class LearningRuleLifecycleTests(unittest.TestCase):
    def test_lifecycle_is_versioned_and_optimistic(self) -> None:
        repository = LearningRuleRepository()
        service = LearningRuleService(repository=repository)

        created = service.create_version(
            rule_key="client:firma-1:supplier:1234567890:dogalgaz",
            expected_version=0,
            snapshot=_snapshot(),
            actor="accountant",
        )
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["status"], "draft")

        active = service.activate(
            rule_key=created["rule_key"],
            expected_version=1,
            actor="accountant",
        )
        self.assertEqual(active["status"], "active")

        with self.assertRaisesRegex(LearningRuleConflict, "learning_rule_version_conflict"):
            service.pause(rule_key=created["rule_key"], expected_version=0, actor="accountant")

        paused = service.pause(rule_key=created["rule_key"], expected_version=1, actor="accountant")
        self.assertEqual(paused["status"], "paused")
        archived = service.archive(rule_key=created["rule_key"], expected_version=1, actor="accountant")
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(len(repository.list_versions(created["rule_key"])), 1)

    def test_activating_new_version_pauses_previous_active_version(self) -> None:
        repository = LearningRuleRepository()
        service = LearningRuleService(repository=repository)
        key = "client:firma-1:supplier:1234567890:dogalgaz"
        first = service.create_version(rule_key=key, expected_version=0, snapshot=_snapshot(), actor="accountant")
        service.activate(rule_key=key, expected_version=first["version"], actor="accountant")
        second = service.create_version(
            rule_key=key, expected_version=1, snapshot=_snapshot(account_code="760.03.001"), actor="accountant"
        )
        service.activate(rule_key=key, expected_version=second["version"], actor="accountant")

        versions = repository.list_versions(key)
        self.assertEqual([item["status"] for item in versions], ["paused", "active"])
        self.assertEqual(service.list_active(rule_key=key)[0]["account_code"], "760.03.001")

    def test_create_version_preserves_source_review_and_protected_reference_linkage(self) -> None:
        repository = LearningRuleRepository()
        service = LearningRuleService(repository=repository)
        snapshot = _snapshot(
            protected_corpus_item_id="corpus-item-1",
            protected_reference_version=3,
        )

        created = service.create_version(
            rule_key="client:firma-1:supplier:1234567890:dogalgaz",
            expected_version=0,
            snapshot=snapshot,
            actor="accountant",
        )

        self.assertEqual(created["source_review_decision_id"], "review-1")
        self.assertEqual(created["protected_corpus_item_id"], "corpus-item-1")
        self.assertEqual(created["protected_reference_version"], 3)

    def test_service_requires_accountant_confirmed_provenance_before_persisting(self) -> None:
        service = LearningRuleService(repository=LearningRuleRepository())

        with self.assertRaisesRegex(ValueError, "learning_rule_confirmation_required"):
            service.create_version(
                rule_key="client:firma-1:supplier:1234567890:dogalgaz",
                expected_version=0,
                snapshot={**_snapshot(), "confirmation_provenance": {}},
                actor="accountant",
            )

    def test_confirmed_review_rule_creates_narrow_active_authority(self) -> None:
        service = LearningRuleService(repository=LearningRuleRepository())
        active = service.save_confirmed_review_rule(
            client_id="firma-1",
            decision={
                "learning_confirmation": "save_rule",
                "corrected_account_code": "770.03.001",
                "document_ref": "doc-1",
                "decision_note": "Bu VKN için doğalgaz gideri hesabını kullan.",
            },
            learning_event={
                "natural_language_rule_candidate": {
                    "scope": "client_counterparty", "account_treatment": "expense", "match_phrase": "dogalgaz gideri"
                },
                "counterparty_tax_id": "1234567890",
                "corrected_account_code": "770.03.001",
                "category": "dogalgaz",
                "utility_context": {},
            },
            interpretation={
                "status": "ready", "summary_tr": "Doğalgaz gideri hesabı önerilecek.",
                "guardrail_tr": "Müşavir kontrolü sürer.", "source": "accountant_confirmed",
            },
            saved_review={"id": "review-42"},
            document={"result": {"accounting_direction": "purchase", "file_name": "doc-1.html"}},
            chart_accounts={"accounts": [{
                "normalized_account_code": "770.03.001", "is_detail_account": True,
                "is_active": True, "semantic_roles": ["expense"],
            }]},
            actor="accountant",
        )

        self.assertIsNotNone(active)
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["scope"], "client_counterparty")
        self.assertEqual(active["counterparty_tax_id"], "1234567890")
        self.assertEqual(active["source_review_decision_id"], "review-42")
        self.assertEqual(active["account_code"], "770.03.001")

    def test_full_vkn_rule_compiles_one_authority_per_canonical_line(self) -> None:
        authorities = compile_verified_rule_authorities(
            rules=(_record(),),
            client_id="firma-1",
            direction="purchase",
            invoice_mode="ordinary",
            counterparty_tax_id="1234567890",
            canonical_lines=(
                {"canonical_line_id": "line-1", "description": "Doğalgaz tüketimi"},
                {"canonical_line_id": "line-2", "description": "Dağıtım bedeli"},
            ),
            account_selection=_account_selection(),
        )

        self.assertEqual({item.canonical_line_id for item in authorities}, {"line-1", "line-2"})
        self.assertTrue(all(item.account_code == "770.03.001" for item in authorities))
        self.assertIsInstance(authorities[0], VerifiedRuleAuthorityV1)
        self.assertEqual(authorities.conflicts, ())

    def test_approved_service_profile_rule_compiles_only_for_that_profile(self) -> None:
        profile_rule = _record(
            scope="client_service_profile",
            counterparty_tax_id="",
            service_profile="gsm_communication",
        )
        common = {
            "client_id": "firma-1",
            "direction": "purchase",
            "invoice_mode": "ordinary",
            "counterparty_tax_id": "9250353261",
            "canonical_lines": ({"canonical_line_id": "line-1", "description": "Aylik hat kullanimi"},),
            "account_selection": _account_selection(),
        }

        matched = compile_verified_rule_authorities(
            rules=(profile_rule,), service_profile="gsm_communication", **common
        )
        unmatched = compile_verified_rule_authorities(
            rules=(profile_rule,), service_profile="electricity", **common
        )

        self.assertEqual(matched[0].account_code, "770.03.001")
        self.assertEqual(unmatched, ())

    def test_provider_specific_rule_wins_over_service_profile_rule(self) -> None:
        profile_rule = _record(
            rule_id="profile-rule",
            scope="client_service_profile",
            counterparty_tax_id="",
            service_profile="gsm_communication",
        )
        provider_rule = _record(rule_id="provider-rule", account_code="770.03.002")
        selection = _account_selection()
        selection.account_candidates["purchase_expense"] = (
            *selection.account_candidates["purchase_expense"],
            {
                "code": "770.03.002",
                "is_active": True,
                "is_detail_account": True,
                "direction": "purchase",
                "semantic_roles": ["expense"],
            },
        )

        matched = compile_verified_rule_authorities(
            rules=(profile_rule, provider_rule),
            client_id="firma-1",
            direction="purchase",
            invoice_mode="ordinary",
            counterparty_tax_id="1234567890",
            service_profile="gsm_communication",
            canonical_lines=({"canonical_line_id": "line-1", "description": "Aylik hat kullanimi"},),
            account_selection=selection,
        )

        self.assertEqual(matched[0].account_code, "770.03.002")

    def test_compiler_rejects_scope_and_provenance_mismatches(self) -> None:
        cases = (
            ("wrong client", {"client_id": "firma-2"}),
            ("wrong VKN", {"counterparty_tax_id": "9999999999"}),
            ("wrong direction", {"direction": "sales"}),
            ("wrong invoice mode", {"invoice_mode": "return"}),
            ("missing confirmation provenance", {"source_review_decision_id": ""}),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                result = compile_verified_rule_authorities(
                    rules=(_record(**changes),),
                    client_id="firma-1",
                    direction="purchase",
                    invoice_mode="ordinary",
                    counterparty_tax_id="1234567890",
                    canonical_lines=({"canonical_line_id": "line-1", "description": "Doğalgaz"},),
                    account_selection=_account_selection(),
                )
                self.assertEqual(result, ())

    def test_compiler_rejects_inactive_non_detail_and_incomplete_or_phrase_mismatch(self) -> None:
        common = {
            "client_id": "firma-1",
            "direction": "purchase",
            "invoice_mode": "ordinary",
            "counterparty_tax_id": "1234567890",
            "canonical_lines": ({"canonical_line_id": "line-1", "description": "Doğalgaz"},),
        }
        self.assertEqual(
            compile_verified_rule_authorities(
                rules=(_record(),), account_selection=_account_selection(active=False), **common
            ),
            (),
        )
        self.assertEqual(
            compile_verified_rule_authorities(
                rules=(_record(),), account_selection=_account_selection(detail=False), **common
            ),
            (),
        )
        self.assertEqual(
            compile_verified_rule_authorities(
                rules=(_record(),),
                account_selection=_account_selection(),
                client_id="firma-1",
                direction="purchase",
                invoice_mode="ordinary",
                counterparty_tax_id="1234567890",
                canonical_lines=({"description": "Doğalgaz"},),
            ),
            (),
        )
        phrase_rule = _record(
            scope="client_phrase",
            line_match_mode="normalized_terms_all",
            normalized_terms=("dogalgaz", "tuketimi"),
        )
        self.assertEqual(
            compile_verified_rule_authorities(
                rules=(phrase_rule,), account_selection=_account_selection(), **common
            ),
            (),
        )

    def test_equal_priority_conflict_returns_metadata_without_authority(self) -> None:
        first = _record(rule_id="rule-1", account_code="770.03.001")
        second = _record(rule_id="rule-2", account_code="760.03.001")

        selection = _account_selection()
        selection.account_candidates["purchase_expense"] = (
            *selection.account_candidates["purchase_expense"],
            {
                "code": "760.03.001",
                "is_active": True,
                "is_detail_account": True,
                "direction": "purchase",
                "semantic_roles": ["expense"],
            },
        )
        result = compile_verified_rule_authorities(
            rules=(first, second),
            client_id="firma-1",
            direction="purchase",
            invoice_mode="ordinary",
            counterparty_tax_id="1234567890",
            canonical_lines=({"canonical_line_id": "line-1", "description": "Doğalgaz"},),
            account_selection=selection,
        )

        self.assertEqual(tuple(result), ())
        self.assertEqual(result.conflicts[0]["reason"], "verified_rule_conflict")


@unittest.skipUnless(
    os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip(),
    "set FISORA_TEST_POSTGRES_DSN to run learning-rule PostgreSQL tests",
)
class LearningRulePostgresTests(unittest.TestCase):
    def test_postgres_roundtrip_requires_explicit_dsn(self) -> None:
        self.skipTest("PostgreSQL roundtrip is exercised only in the DSN-enabled pilot lane")


if __name__ == "__main__":
    unittest.main()
