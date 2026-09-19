from __future__ import annotations

from copy import deepcopy

from app.services.learned_rule_audit_shadow import (
    learned_rule_audit_shadow_client_allowed,
    learned_rule_audit_shadow_enabled,
    run_learned_rule_audit_shadow,
)


class FakeStructuredResult(dict):
    attempt = None


class FakeProvider:
    def __init__(self, *, applies: bool = True) -> None:
        self.calls: list[str] = []
        self.applies = applies

    def generate_structured_json(self, *, schema_name, instructions, user_payload, schema):
        self.calls.append(schema_name)
        if schema_name.endswith("_search"):
            return FakeStructuredResult(
                {
                    "row_plans": [
                        {
                            "row_id": "1",
                            "queries": ["MINIFIT HOPARLOR", "MINIFIT", "DEMANT MINIFIT"],
                            "reason": "Search exact family and counterparty context.",
                        }
                    ]
                }
            )
        if schema_name.endswith("_candidates"):
            catalog = user_payload["candidate_catalog_by_row"]["1"]
            assert catalog[0]["candidate_ref"] == "C1"
            return FakeStructuredResult(
                {
                    "row_candidates": [
                        {
                            "row_id": "1",
                            "candidate_refs": ["C1"],
                            "reason": "Family candidate needs full verification.",
                        }
                    ]
                }
            )
        if schema_name.endswith("_final"):
            opened = user_payload["opened_candidates_by_row"]["1"]
            assert opened[0]["candidate_ref"] == "C1"
            assert "rule_id" not in opened[0]["rule"]
            invoice_row = user_payload["invoice_context"]["rows"][0]
            assert "account_code" not in invoice_row
            assert "reason" not in invoice_row
            rule = opened[0]["rule"]
            if rule["binding_mode"] == "semantic_role":
                assert rule["account_code"] == ""
                chart_codes = {
                    item["account_code"]
                    for item in user_payload["current_client_chart_by_row"]["1"]
                }
                assert chart_codes == {"153.01", "153.02"}
            else:
                assert user_payload["current_client_chart_by_row"]["1"] == []
            if not self.applies:
                return FakeStructuredResult(
                    {
                        "row_resolutions": [
                            {
                                "row_id": "1",
                                "candidate_assessments": [
                                    {
                                        "candidate_ref": "C1",
                                        "verdict": "not_applicable",
                                        "reason": "The full rule does not cover this row.",
                                    }
                                ],
                                "status": "no_applicable_rule",
                                "candidate_ref": "",
                                "resolved_account": "",
                                "reason": "No learned rule applies.",
                            }
                        ]
                    }
                )
            return FakeStructuredResult(
                {
                    "row_resolutions": [
                        {
                            "row_id": "1",
                            "candidate_assessments": [
                                {
                                    "candidate_ref": "C1",
                                    "verdict": "applies",
                                    "reason": "The opened family rule directly covers this row.",
                                }
                            ],
                            "status": "resolved",
                            "candidate_ref": "C1",
                            "resolved_account": "153.01",
                            "reason": "The opened family rule directly covers this row.",
                        }
                    ]
                }
            )
        raise AssertionError(schema_name)


def _workspace() -> dict:
    return {
        "chart_accounts": {
            "accounts": [
                {
                    "account_code": "153.01",
                    "account_name": "Hearing device stock",
                    "semantic_roles": ["stock", "hearing_device_stock"],
                    "is_detail_account": True,
                    "is_active": True,
                },
                {
                    "account_code": "153.02",
                    "account_name": "Accessory stock",
                    "semantic_roles": ["stock", "hearing_aid_accessory_stock"],
                    "is_detail_account": True,
                    "is_active": True,
                },
            ]
        }
    }


def _source_package() -> dict:
    return {
        "invoice_table_rows": [
            {
                "source_position": "1",
                "description": "MINIFIT HOPARLOR 3R 85",
                "source_text": "MINIFIT HOPARLOR 3R 85",
            }
        ]
    }


def _final_output() -> dict:
    return {
        "row_decisions": [
            {
                "source_position": "1",
                "role": "business_line",
                "account_code": "153.02",
                "reason": "Draft accountant selection.",
            }
        ]
    }


def _active_rule() -> dict:
    return {
        "rule_id": "rule-minifit",
        "status": "active",
        "client_id": "client-1",
        "direction": "purchase",
        "scope": "client_phrase",
        "normalized_terms": ["minifit", "hoparlor"],
        "semantic_role": "stock",
        "semantic_intent": "hearing_device_stock",
        "binding_mode": "fixed_account",
        "meaning_label": "MINIFIT HOPARLOR family",
        "trigger_tr": "MINIFIT speaker family on purchase invoices.",
        "action_tr": "Use exact account 153.01.",
        "guardrail_tr": "Only apply to the MINIFIT speaker family.",
        "account_code": "153.01",
    }



def _active_semantic_rule() -> dict:
    rule = _active_rule()
    rule.update(
        {
            "rule_id": "rule-semantic-minifit",
            "binding_mode": "semantic_role",
            "semantic_role": "stock",
            "semantic_intent": "hearing_device_stock",
            "meaning_label": "MINIFIT HOPARLOR satırı işitme cihazı stok ailesidir.",
            "trigger_tr": "MINIFIT HOPARLOR ürün ailesi eşleştiğinde.",
            "action_tr": "İşitme cihazı stok anlamını uygula; exact hesabı güncel plandan seç.",
            "guardrail_tr": "Geçmiş exact hesaba bağlanma.",
            "account_code": "",
        }
    )
    return rule

def test_shadow_suggests_correction_without_mutating_draft() -> None:
    provider = FakeProvider()
    final_output = _final_output()
    before = deepcopy(final_output)

    result = run_learned_rule_audit_shadow(
        provider=provider,
        active_rules=[_active_rule()],
        source_package=_source_package(),
        semantic_plan={
            "accounting_direction": "purchase",
            "counterparty_name": "DEMANT",
            "counterparty_identifier": "123",
        },
        final_output=final_output,
        workspace=_workspace(),
    )

    assert provider.calls == [
        "learned_rule_audit_shadow_search",
        "learned_rule_audit_shadow_candidates",
        "learned_rule_audit_shadow_final",
    ]
    assert result["status"] == "completed"
    assert result["audit_status"] == "complete"
    assert result["mutated_accounting"] is False
    assert result["corrections"] == [
        {
            "row_id": "1",
            "rule_id": "rule-minifit",
            "from_account": "153.02",
            "to_account": "153.01",
            "reason": "The opened family rule directly covers this row.",
        }
    ]
    assert final_output == before


def test_shadow_skips_without_active_rules_and_does_not_call_model() -> None:
    provider = FakeProvider()
    result = run_learned_rule_audit_shadow(
        provider=provider,
        active_rules=[],
        source_package=_source_package(),
        semantic_plan={"accounting_direction": "purchase"},
        final_output=_final_output(),
        workspace=_workspace(),
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_active_rules"
    assert provider.calls == []


def test_shadow_feature_and_client_gates() -> None:
    assert not learned_rule_audit_shadow_enabled({})
    assert learned_rule_audit_shadow_enabled(
        {"FISORA_LEARNED_RULE_AUDIT_SHADOW_ENABLED": "true"}
    )
    env = {"FISORA_LEARNED_RULE_AUDIT_SHADOW_CLIENT_IDS": "a,b"}
    assert learned_rule_audit_shadow_client_allowed(env, "a")
    assert not learned_rule_audit_shadow_client_allowed(env, "c")
    assert learned_rule_audit_shadow_client_allowed({}, "anything")


def test_search_rules_returns_all_boolean_matches_without_scores_or_top_k() -> None:
    from app.services.learned_rule_audit_shadow import _rule_document, _search_rules

    rules = []
    for index in range(12):
        rule = _active_rule()
        rule["rule_id"] = f"rule-{index:02d}"
        rule["meaning_label"] = f"MINIFIT HOPARLOR family {index}"
        rules.append(_rule_document(rule))

    result = _search_rules(
        rules,
        query="MINIFIT HOPARLOR",
        direction="purchase",
        counterparty_identifier="",
        result_limit=100,
    )

    assert result["total_matches"] == 12
    assert result["overflow"] is False
    assert len(result["items"]) == 12
    assert all("search_score" not in item for item in result["items"])
    assert {item["rule_id"] for item in result["items"]} == {f"rule-{index:02d}" for index in range(12)}


def test_search_rules_marks_overflow_instead_of_silently_accepting_partial_results() -> None:
    from app.services.learned_rule_audit_shadow import _rule_document, _search_rules

    rules = []
    for index in range(6):
        rule = _active_rule()
        rule["rule_id"] = f"overflow-{index}"
        rules.append(_rule_document(rule))

    result = _search_rules(
        rules,
        query="MINIFIT",
        direction="purchase",
        result_limit=3,
    )

    assert result["total_matches"] == 6
    assert result["overflow"] is True
    assert len(result["items"]) == 3


def test_search_rules_discovers_exact_counterparty_scope_without_phrase_terms() -> None:
    from app.services.learned_rule_audit_shadow import _rule_document, _search_rules

    rule = {
        "rule_id": "rule-counterparty",
        "status": "active",
        "client_id": "client-1",
        "direction": "purchase",
        "scope": "client_counterparty",
        "counterparty_tax_id": "1234567890",
        "semantic_role": "expense",
        "meaning_label": "Counterparty-wide purchase treatment",
        "account_code": "770.01",
    }

    result = _search_rules(
        [_rule_document(rule)],
        query="unrelated supplier wording",
        direction="purchase",
        counterparty_identifier="1234567890",
    )

    assert result["total_matches"] == 1
    assert result["items"][0]["match_classes"] == ["exact_counterparty"]

def test_semantic_rule_resolves_current_chart_without_seeing_draft_account() -> None:
    provider = FakeProvider()
    result = run_learned_rule_audit_shadow(
        provider=provider,
        active_rules=[_active_semantic_rule()],
        source_package=_source_package(),
        semantic_plan={
            "accounting_direction": "purchase",
            "counterparty_name": "DEMANT",
            "counterparty_identifier": "123",
        },
        final_output=_final_output(),
        workspace=_workspace(),
    )

    assert result["audit_status"] == "complete"
    assert result["corrections"] == [
        {
            "row_id": "1",
            "rule_id": "rule-semantic-minifit",
            "from_account": "153.02",
            "to_account": "153.01",
            "reason": "The opened family rule directly covers this row.",
        }
    ]


def test_harness_does_not_resolve_account_when_no_opened_rule_applies() -> None:
    provider = FakeProvider(applies=False)
    result = run_learned_rule_audit_shadow(
        provider=provider,
        active_rules=[_active_semantic_rule()],
        source_package=_source_package(),
        semantic_plan={
            "accounting_direction": "purchase",
            "counterparty_name": "DEMANT",
            "counterparty_identifier": "123",
        },
        final_output=_final_output(),
        workspace=_workspace(),
    )

    assert result["audit_status"] == "complete"
    assert result["corrections"] == []
    assert result["row_audits"] == [
        {
            "row_id": "1",
            "status": "no_applicable_rule_found",
            "rule_id": "",
            "reason": "No learned rule applies.",
        }
    ]


def test_semantic_rule_is_usable_without_exact_account_code() -> None:
    from app.services.learned_rule_audit_shadow import _rule_document, _usable_rule

    rule = _active_semantic_rule()
    assert _usable_rule(rule)
    document = _rule_document(rule)
    assert document["binding_mode"] == "semantic_role"
    assert document["account_code"] == ""
    assert document["summary"]
    assert document["trigger"]
    assert document["action"]
    assert document["guardrail"]
