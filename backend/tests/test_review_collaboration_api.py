from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api import phase0_routes_review_export as routes
from app.api.phase0_schemas import ReviewDecisionPayload, StoredReviewDecisionPayload
from app.services.review_collaboration_service import EditLeaseConflict


class _Store:
    normalized_accounting_enabled = True


class _ReviewService:
    store = _Store()

    def store_review_decision(self, **_kwargs):
        raise AssertionError("review decision must not save while another actor owns the lease")
class _LockedCollaborationService:
    def acquire(self, **_kwargs):
        raise EditLeaseConflict("held by another actor", owner_actor_id="accountant-a")


def test_review_decision_rejects_another_active_editor(monkeypatch) -> None:
    monkeypatch.setattr(routes, "get_review_service", lambda: _ReviewService())
    monkeypatch.setattr(routes, "request_user_id", lambda *_args: "accountant-b")
    monkeypatch.setattr(
        routes,
        "_review_edit_service",
        lambda *_args: (_LockedCollaborationService(), "accountant-b", "client-1", "accountant"),
    )
    payload = StoredReviewDecisionPayload(
        client_id="client-1",
        decision=ReviewDecisionPayload(
            document_ref="doc-1",
            action="approve",
            reviewer="accountant-b",
            expected_revision=4,
        ),
    )

    with pytest.raises(HTTPException) as captured:
        routes.store_review_decision(payload, "accountant-b", None, None)

    assert captured.value.status_code == 409
    assert captured.value.detail["reason"] == "edit_lease_conflict"
    assert captured.value.detail["owner_actor_id"] == "accountant-a"
