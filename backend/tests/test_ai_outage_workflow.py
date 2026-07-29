from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.ai_outage import next_ai_retry, sanitize_provider_failure_evidence


class AiOutageWorkflowTests(unittest.TestCase):
    def test_initial_retry_steps_use_the_exact_base_schedule_without_jitter(self) -> None:
        opened = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
        expected = [
            timedelta(minutes=2),
            timedelta(minutes=5),
            timedelta(minutes=10),
            timedelta(minutes=15),
            timedelta(minutes=30),
            timedelta(hours=2),
            timedelta(hours=6),
        ]

        decisions = [next_ai_retry(step=step, opened_at=opened, now=opened) for step in range(7)]

        self.assertEqual([decision.delay for decision in decisions], expected)
        self.assertEqual(
            [decision.next_attempt_at for decision in decisions],
            [opened + delay for delay in expected],
        )
        self.assertTrue(all(decision.status == "retry_wait" for decision in decisions))
        self.assertEqual([decision.retry_step for decision in decisions], list(range(1, 8)))

    def test_six_hour_cadence_stops_at_twenty_four_hours(self) -> None:
        opened = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)

        cadence = next_ai_retry(
            step=7,
            opened_at=opened,
            now=opened + timedelta(hours=6),
        )
        terminal = next_ai_retry(
            step=10,
            opened_at=opened,
            now=opened + timedelta(hours=24),
        )

        self.assertEqual(cadence.status, "retry_wait")
        self.assertEqual(cadence.delay, timedelta(hours=6))
        self.assertEqual(cadence.next_attempt_at, opened + timedelta(hours=12))
        self.assertEqual(terminal.status, "manual_attention")
        self.assertIsNone(terminal.delay)
        self.assertIsNone(terminal.next_attempt_at)
        self.assertEqual(terminal.retry_step, 10)

    def test_document_jitter_is_deterministic_and_does_not_change_base_delay(self) -> None:
        opened = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)

        first = next_ai_retry(step=0, opened_at=opened, now=opened, document_id="document-42")
        second = next_ai_retry(step=0, opened_at=opened, now=opened, document_id="document-42")

        self.assertEqual(first.delay, timedelta(minutes=2))
        self.assertEqual(first.next_attempt_at, second.next_attempt_at)
        self.assertGreaterEqual(first.next_attempt_at, opened + first.delay)
        self.assertLess(first.next_attempt_at, opened + first.delay + timedelta(minutes=1))

    def test_provider_failure_evidence_only_contains_safe_normalized_fields(self) -> None:
        attempted_at = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)

        evidence = sanitize_provider_failure_evidence(
            provider_name="NVIDIA",
            category="timeout",
            attempted_at=attempted_at,
        )
        fallback = sanitize_provider_failure_evidence(
            provider_name="nvidia api_key=secret",
            category="unexpected_detail",
            attempted_at=attempted_at,
        )

        self.assertEqual(
            evidence,
            {
                "provider": "nvidia",
                "category": "timeout",
                "attempted_at": "2026-07-27T09:00:00+00:00",
            },
        )
        self.assertEqual(fallback["provider"], "unknown")
        self.assertEqual(fallback["category"], "unavailable")
        self.assertEqual(set(fallback), {"provider", "category", "attempted_at"})


if __name__ == "__main__":
    unittest.main()
