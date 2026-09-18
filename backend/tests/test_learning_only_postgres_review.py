from app.persistence.postgres_workflow_store import PostgresWorkflowStore


class ExplodingNormalizedRepository:
    def save_review(self, **kwargs):
        raise AssertionError("learning-only decision must not write a normalized journal")

    def with_connection(self, connection):
        raise AssertionError("learning-only decision must not open normalized journal transaction")


def test_postgres_learning_only_review_skips_document_and_normalized_journal(monkeypatch) -> None:
    store = PostgresWorkflowStore(
        "postgresql://example",
        connect=lambda: (_ for _ in ()).throw(AssertionError("database connection should not be needed")),
        accounting_store_target="normalized",
        normalized_repository=ExplodingNormalizedRepository(),
    )

    original_document = {
        "document_ref": "doc-1",
        "export_status": "review_required",
        "result": {
            "accounting_direction": "purchase",
            "export_status": "review_required",
            "draft_lines": [{"account_code": "", "description": "intentionally invalid legacy draft"}],
        },
    }
    monkeypatch.setattr(store, "_get_record", lambda *args, **kwargs: original_document)

    captured = {}

    def persist_review_records(**kwargs):
        captured.update(kwargs)
        return {
            "id": "review-1",
            "client_id": kwargs["client_id"],
            "decision": kwargs["decision"],
            "learning_event": kwargs["learning_event"],
            "normalized_review": kwargs["normalized_review"],
        }

    monkeypatch.setattr(store, "_persist_review_records", persist_review_records)

    saved = store.save_review_decision(
        client_id="client-1",
        decision={
            "document_ref": "doc-1",
            "action": "suggest_for_similar",
            "learning_confirmation": "save_rule",
            "corrected_account_code": "770.01.004",
            "reason": "Teach a rule only.",
        },
        learning_event={"document_ref": "doc-1", "action": "suggest_for_similar"},
    )

    assert saved["id"] == "review-1"
    assert captured["corrected_document"] is None
    assert captured["normalized_review"] == {}
