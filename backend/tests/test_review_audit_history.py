# Summary: Verifies accountant review audit history filtering and undo/reopen event semantics.
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.workflow_store import JsonWorkflowStore
from app.services.review_service import ReviewService


def test_json_review_audit_history_filters_actor_action_and_document(tmp_path: Path) -> None:
    store = JsonWorkflowStore(tmp_path / "workflow.json")
    store.save_review_decision(
        client_id="client-1",
        decision={
            "document_ref": "ABC2026000001.pdf",
            "action": "approve",
            "reviewer": "mali-musavir",
            "operation_kind": "decision",
            "reason": "Kontrol edildi.",
        },
        learning_event={"document_ref": "ABC2026000001.pdf"},
    )
    store.save_review_decision(
        client_id="client-1",
        decision={
            "document_ref": "ABC2026000001.pdf",
            "action": "review_required",
            "reviewer": "mali-musavir",
            "operation_kind": "undo",
            "reason": "Son m??avir i?lemi geri al?nd?.",
        },
        learning_event={"document_ref": "ABC2026000001.pdf"},
    )
    store.save_review_decision(
        client_id="client-2",
        decision={
            "document_ref": "OTHER.pdf",
            "action": "approve",
            "reviewer": "other-user",
        },
        learning_event={"document_ref": "OTHER.pdf"},
    )

    events = store.list_audit_history(
        client_id="client-1", query="ABC2026", actor="mali-musavir", limit=100
    )
    assert len(events) == 2
    assert events[0]["event_type"] == "journal_undo"
    assert events[0]["details"]["operation_kind"] == "undo"
    assert events[0]["details"]["after_state"] == "review_required"
    assert events[1]["event_type"] == "journal_approved"
    assert events[1]["details"]["after_state"] == "approved"

    approvals = store.list_audit_history(client_id="client-1", action="approve")
    assert [event["event_type"] for event in approvals] == ["journal_approved"]


def test_review_service_audit_history_requires_accountant_scope_and_forwards_filters() -> None:
    calls: list[dict[str, object]] = []
    access_calls: list[dict[str, object]] = []

    class Store:
        def list_audit_history(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(dict(kwargs))
            return [{"event_id": "event-1"}]

    def require_client_access(**kwargs: object) -> dict[str, object]:
        access_calls.append(dict(kwargs))
        return {"role": "accountant"}

    service = ReviewService(
        store=Store(),
        record_operation_event=lambda **_: {},
        require_client_access=require_client_access,
    )
    payload = service.audit_history(
        client_id="client-1",
        user_id="mali-musavir",
        query="ABC",
        actor="mali",
        action="approve",
        start_date="2026-09-01",
        end_date="2026-09-14",
        limit=999,
    )

    assert payload == {"client_id": "client-1", "events": [{"event_id": "event-1"}]}
    assert access_calls == [{
        "client_id": "client-1",
        "user_id": "mali-musavir",
        "allowed_roles": ("accountant", "admin"),
    }]
    assert calls == [{
        "client_id": "client-1",
        "query": "ABC",
        "actor": "mali",
        "action": "approve",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "limit": 200,
    }]
