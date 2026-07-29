from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.phase0_routes_operations import _retention_notification


class NotificationContractTests(unittest.TestCase):
    def test_retention_notification_is_grouped_and_read_stays_pending(self) -> None:
        notification = _retention_notification(
            {
                "batch_id": "batch-1",
                "client_id": "firma-1",
                "accounting_period": "2026-02",
                "delete_on": "2026-05-31",
                "document_count": 12,
                "read_at": "2026-05-02T09:00:00+00:00",
            }
        )

        self.assertEqual(notification["notification_id"], "retention:batch-1")
        self.assertEqual(notification["document_count"], 12)
        self.assertIn("Şubat 2026", notification["title"])
        self.assertIn("31 Mayıs 2026", notification["message"])
        self.assertEqual(notification["read_at"], "2026-05-02T09:00:00+00:00")
        self.assertEqual(notification["status"], "pending")


if __name__ == "__main__":
    unittest.main()
