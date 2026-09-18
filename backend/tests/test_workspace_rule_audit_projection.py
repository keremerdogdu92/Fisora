from app.services.workspace_service import compact_result


def test_review_projection_preserves_learned_rule_audit_technical_details() -> None:
    source = {
        "draft_status": "draft_ready",
        "technical_details": {
            "learned_rule_audit_shadow": {
                "status": "completed",
                "audit_status": "complete",
                "corrections": [
                    {
                        "row_id": "1",
                        "rule_id": "rule-1",
                        "from_account": "153.02",
                        "to_account": "153.01",
                    }
                ],
            }
        },
        "internal_secret": "must-not-pass",
    }

    projected = compact_result(source)

    assert projected["technical_details"] == source["technical_details"]
    assert "internal_secret" not in projected
