from app.services.workspace_service import compact_result


def test_review_projection_exposes_only_sanitized_learned_rule_audit_details() -> None:
    source = {
        "draft_status": "draft_ready",
        "technical_details": {
            "provider_internal": {"secret": "must-not-pass"},
            "learned_rule_audit_shadow": {
                "status": "completed",
                "audit_status": "complete",
                "model": "gemini-3.5-flash-lite",
                "elapsed_ms": 4200,
                "prompt_version": "learned-rule-audit-shadow-v4-20260918",
                "corrections": [
                    {
                        "row_id": "1",
                        "rule_id": "rule-1",
                        "from_account": "153.02",
                        "to_account": "153.01",
                        "reason": "Confirmed rule applies.",
                        "hidden_field": "must-not-pass",
                    }
                ],
                "unresolved_rows": [],
                "validation_errors": [],
                "opened_candidates_by_row": {"1": [{"secret": "must-not-pass"}]},
            },
        },
        "internal_secret": "must-not-pass",
    }

    projected = compact_result(source)

    audit = projected["technical_details"]["learned_rule_audit_shadow"]
    assert audit["status"] == "completed"
    assert audit["audit_status"] == "complete"
    assert audit["corrections"] == [
        {
            "row_id": "1",
            "rule_id": "rule-1",
            "from_account": "153.02",
            "to_account": "153.01",
            "reason": "Confirmed rule applies.",
        }
    ]
    assert "provider_internal" not in projected["technical_details"]
    assert "opened_candidates_by_row" not in audit
    assert "internal_secret" not in projected


def test_review_projection_hides_skipped_rule_audit() -> None:
    source = {
        "draft_status": "draft_ready",
        "technical_details": {
            "learned_rule_audit_shadow": {
                "status": "skipped",
                "reason": "no_active_rules",
            }
        },
    }

    projected = compact_result(source)

    assert "technical_details" not in projected
