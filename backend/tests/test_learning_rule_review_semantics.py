from app.domain.workspace_review_updates import apply_review_decision_to_document


def _balanced_purchase_document() -> dict:
    return {
        "document_ref": "pilot-learning.html",
        "export_status": "review_required",
        "result": {
            "accounting_direction": "purchase",
            "selected_expense_account": "770.01.009",
            "selected_supplier_account": "320.A01",
            "selected_vat_account": "191.01.020",
            "draft_lines": [
                {"account_code": "770.01.004", "description": "Pilot hizmet", "debit": "352.34", "credit": "0.00"},
                {"account_code": "191.01.020", "description": "KDV", "debit": "70.47", "credit": "0.00"},
                {"account_code": "320.A01", "description": "Satici", "debit": "0.00", "credit": "422.81"},
            ],
            "is_balanced": True,
            "export_status": "review_required",
        },
    }


def test_suggest_for_similar_keeps_balanced_invoice_in_review() -> None:
    document = _balanced_purchase_document()
    decision = {
        "document_ref": "pilot-learning.html",
        "action": "suggest_for_similar",
        "reviewer": "accountant",
        "corrected_account_code": "770.01.004",
        "draft_lines": document["result"]["draft_lines"],
        "reason": "Teach a narrow pilot rule without approving export.",
    }

    updated = apply_review_decision_to_document(
        document,
        decision=decision,
        learning_event={
            "scope": "client_rule",
            "action": "suggest_for_similar",
            "reason": decision["reason"],
        },
        reviewed_at="2026-09-18T19:30:00Z",
    )

    assert updated["export_status"] == "review_required"
    assert updated["result"]["export_status"] == "review_required"
    assert updated["result"]["accountant_export_override"] is False
    assert updated["result"]["accountant_decision_action"] == "suggest_for_similar"


def test_approve_with_changes_still_opens_export_for_balanced_invoice() -> None:
    document = _balanced_purchase_document()
    decision = {
        "document_ref": "pilot-learning.html",
        "action": "approve_with_changes",
        "reviewer": "accountant",
        "corrected_account_code": "770.01.004",
        "draft_lines": document["result"]["draft_lines"],
        "reason": "Approve the corrected journal.",
    }

    updated = apply_review_decision_to_document(
        document,
        decision=decision,
        learning_event={"scope": "client_rule", "action": "approve_with_changes"},
        reviewed_at="2026-09-18T19:30:00Z",
    )

    assert updated["export_status"] == "export_ready"
    assert updated["result"]["export_status"] == "export_ready"
    assert updated["result"]["accountant_export_override"] is True
