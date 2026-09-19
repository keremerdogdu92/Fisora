from __future__ import annotations

from app.workflows.document_processing import _apply_learned_rule_audit_corrections


def _workspace() -> dict:
    return {
        "chart_accounts": {
            "accounts": [
                {
                    "normalized_account_code": "153.01",
                    "account_name": "Cihaz stoku",
                    "is_detail_account": True,
                },
                {
                    "normalized_account_code": "153.02",
                    "account_name": "Aksesuar stoku",
                    "is_detail_account": True,
                },
            ]
        }
    }


def _result() -> dict:
    return {
        "accounting_direction": "purchase",
        "selected_expense_account": "153.02",
        "draft_lines": [
            {
                "account_code": "153.02",
                "account_name": "Aksesuar stoku",
                "description": "MINIFIT HOPARLOR",
                "debit": "540.00",
                "credit": "0.00",
                "source_position": "1",
                "source_basis": ["1"],
                "source_line_numbers": [1],
                "source_anchors": [{"source_position": "1"}],
            }
        ],
        "line_decisions": [
            {
                "source_position": "1",
                "account_code": "153.02",
                "reason": "Muhasebe AI ilk kararı",
            }
        ],
        "decision_narrative": {
            "account_code": "153.02",
            "account_name": "Aksesuar stoku",
        },
        "primary_suggestion": {
            "account": "153.02",
            "draft_lines": [],
        },
    }

def _audit() -> dict:
    return {
        "status": "completed",
        "audit_status": "complete",
        "validation_errors": [],
        "mutated_accounting": False,
        "corrections": [
            {
                "row_id": "1",
                "rule_id": "rule-minifit",
                "from_account": "153.02",
                "to_account": "153.01",
                "reason": "Onayli MINIFIT kurali.",
            }
        ],
    }


def test_complete_rule_audit_auto_applies_account_and_preserves_ai_provenance() -> None:
    result = _result()

    _apply_learned_rule_audit_corrections(result, _audit(), _workspace())

    assert result["draft_lines"][0]["account_code"] == "153.01"
    assert result["draft_lines"][0]["account_name"] == "Cihaz stoku"
    assert result["draft_lines"][0]["ai_original_account_code"] == "153.02"
    assert result["draft_lines"][0]["learned_rule_id"] == "rule-minifit"
    assert result["selected_expense_account"] == "153.01"
    assert result["decision_narrative"]["account_code"] == "153.01"
    assert result["primary_suggestion"]["account"] == "153.01"

    # Muhasebe AI'in ilk karari provenance olarak degismeden kalir.
    assert result["line_decisions"][0]["account_code"] == "153.02"

    audit = result["technical_details"]["learned_rule_audit_shadow"]
    assert audit["application_status"] == "applied"
    assert audit["mutated_accounting"] is True
    assert audit["applied_correction_count"] == 1
    assert audit["corrections"][0]["application_status"] == "applied"
    assert audit["corrections"][0]["from_account"] == "153.02"
    assert audit["corrections"][0]["to_account"] == "153.01"


def test_multiple_corrections_for_same_journal_line_are_blocked_atomically() -> None:
    result = _result()
    result["draft_lines"][0]["source_basis"] = ["1", "2"]
    audit = _audit()
    audit["corrections"].append(
        {
            "row_id": "2",
            "rule_id": "rule-second",
            "from_account": "153.02",
            "to_account": "153.01",
            "reason": "Ikinci kaynak satiri ayni fis satirina denk geliyor.",
        }
    )
    _apply_learned_rule_audit_corrections(result, audit, _workspace())

    assert result["draft_lines"][0]["account_code"] == "153.02"
    applied = result["technical_details"]["learned_rule_audit_shadow"]
    assert applied["application_status"] == "blocked"
    assert applied["mutated_accounting"] is False
    assert any(
        str(item).startswith("draft_line_multiple_corrections:")
        for item in applied["application_errors"]
    )


def test_row_matching_ignores_tax_line_with_same_source_position() -> None:
    result = _result()
    result["draft_lines"].append(
        {
            "account_code": "191.20",
            "account_name": "Indirilecek KDV",
            "description": "KDV",
            "debit": "108.00",
            "credit": "0.00",
            "source_position": "1",
            "source_basis": ["1"],
            "source_line_numbers": [1],
            "source_anchors": [{"source_position": "1"}],
        }
    )

    _apply_learned_rule_audit_corrections(result, _audit(), _workspace())

    assert result["draft_lines"][0]["account_code"] == "153.01"
    assert result["draft_lines"][1]["account_code"] == "191.20"
    audit = result["technical_details"]["learned_rule_audit_shadow"]
    assert audit["application_status"] == "applied"
