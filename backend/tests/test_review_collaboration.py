from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.normalized_accounting_repository import NormalizedRevisionConflict
from app.services.review_collaboration_service import (
    EditLeaseConflict,
    InMemoryReviewCollaborationRepository,
    ReviewCollaborationService,
)


UTC = timezone.utc
NOW = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


class ReviewCollaborationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryReviewCollaborationRepository()
        self.service = ReviewCollaborationService(
            repository=self.repository,
            tenant_id="tenant-a",
            now=lambda: NOW,
        )
        self.repository.set_current_journal_state(
            tenant_id="tenant-a",
            journal_entry_id="journal-1",
            current_revision=4,
            export_status="review_required",
        )

    def test_acquire_blocks_another_actor_until_activity_lease_expires(self) -> None:
        lease = self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            actor_role="accountant",
            user_activity_at=NOW,
        )

        self.assertEqual(lease["owner_actor_id"], "accountant-a")
        self.assertEqual(lease["expires_at"], (NOW + timedelta(minutes=5)).isoformat())
        with self.assertRaises(EditLeaseConflict):
            self.service.acquire(
                journal_entry_id="journal-1",
                actor_id="accountant-b",
                actor_role="accountant",
                user_activity_at=NOW + timedelta(minutes=1),
                now=NOW + timedelta(minutes=1),
            )

        replacement = self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-b",
            actor_role="accountant",
            user_activity_at=NOW + timedelta(minutes=6),
            now=NOW + timedelta(minutes=6),
        )

        self.assertEqual(replacement["owner_actor_id"], "accountant-b")

    def test_renew_requires_newer_non_future_real_user_activity(self) -> None:
        self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            actor_role="accountant",
            user_activity_at=NOW,
        )

        with self.assertRaisesRegex(ValueError, "newer"):
            self.service.renew(
                journal_entry_id="journal-1",
                actor_id="accountant-a",
                user_activity_at=NOW,
                now=NOW + timedelta(minutes=1),
            )
        with self.assertRaisesRegex(ValueError, "future"):
            self.service.renew(
                journal_entry_id="journal-1",
                actor_id="accountant-a",
                user_activity_at=NOW + timedelta(minutes=3),
                now=NOW + timedelta(minutes=2),
            )

        renewed = self.service.renew(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            user_activity_at=NOW + timedelta(minutes=2),
            now=NOW + timedelta(minutes=2),
        )

        self.assertEqual(renewed["last_user_activity_at"], (NOW + timedelta(minutes=2)).isoformat())
        self.assertEqual(renewed["expires_at"], (NOW + timedelta(minutes=7)).isoformat())

    def test_release_and_authorized_takeover_express_ownership(self) -> None:
        self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            actor_role="accountant",
            user_activity_at=NOW,
        )

        with self.assertRaisesRegex(ValueError, "reason"):
            self.service.takeover(
                journal_entry_id="journal-1",
                actor_id="admin-a",
                actor_role="admin",
                reason=" ",
                user_activity_at=NOW + timedelta(minutes=1),
                now=NOW + timedelta(minutes=1),
            )
        takeover = self.service.takeover(
            journal_entry_id="journal-1",
            actor_id="admin-a",
            actor_role="admin",
            reason="Urgent correction",
            user_activity_at=NOW + timedelta(minutes=1),
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(takeover["owner_actor_id"], "admin-a")
        self.assertEqual(takeover["takeover_reason"], "Urgent correction")

        self.service.release(journal_entry_id="journal-1", actor_id="admin-a")
        new_lease = self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-b",
            actor_role="accountant",
            user_activity_at=NOW + timedelta(minutes=1),
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(new_lease["owner_actor_id"], "accountant-b")

    def test_save_working_draft_requires_active_owner_and_preserves_current_export_state(self) -> None:
        self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            actor_role="accountant",
            user_activity_at=NOW,
        )

        draft = self.service.save_working_draft(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            expected_revision=4,
            payload={"lines": [{"account_code": "770", "debit": "100.00"}]},
            now=NOW + timedelta(minutes=1),
        )

        self.assertEqual(draft["revision_role"], "candidate")
        self.assertEqual(draft["candidate_revision"], 5)
        self.assertEqual(draft["current_revision"], 4)
        self.assertEqual(draft["export_status"], "review_required")
        self.assertEqual(
            self.repository.read_current_journal_state("tenant-a", "journal-1"),
            {"current_revision": 4, "export_status": "review_required"},
        )

        with self.assertRaises(NormalizedRevisionConflict):
            self.service.save_working_draft(
                journal_entry_id="journal-1",
                actor_id="accountant-a",
                expected_revision=3,
                payload={"lines": []},
                now=NOW + timedelta(minutes=2),
            )

    def test_list_candidates_returns_only_the_tenant_working_drafts(self) -> None:
        self.service.acquire(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            actor_role="accountant",
            user_activity_at=NOW,
        )
        self.service.save_working_draft(
            journal_entry_id="journal-1",
            actor_id="accountant-a",
            expected_revision=4,
            payload={"lines": [{"account_code": "770.01", "debit": "100.00"}]},
            now=NOW + timedelta(minutes=1),
        )
        other = ReviewCollaborationService(
            repository=self.repository,
            tenant_id="tenant-b",
            now=lambda: NOW,
        )

        self.assertEqual(
            self.service.list_candidates(),
            [
                {
                    "journal_entry_id": "journal-1",
                    "expected_revision": 4,
                    "candidate_revision": 5,
                    "revision_role": "candidate",
                    "current_revision": 4,
                    "export_status": "review_required",
                    "payload": {"lines": [{"account_code": "770.01", "debit": "100.00"}]},
                    "saved_by": "accountant-a",
                    "saved_at": (NOW + timedelta(minutes=1)).isoformat(),
                }
            ],
        )
        self.assertEqual(other.list_candidates(), [])


if __name__ == "__main__":
    unittest.main()
