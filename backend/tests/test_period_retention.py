from __future__ import annotations

from datetime import date
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.period_retention import parse_accounting_period, period_retention_schedule


class PeriodRetentionTests(unittest.TestCase):
    def test_february_schedule_uses_calendar_month_boundaries(self) -> None:
        schedule = period_retention_schedule(date(2026, 2, 1))

        self.assertEqual(schedule.preparation_on, date(2026, 4, 30))
        self.assertEqual(schedule.warning_on, date(2026, 5, 1))
        self.assertEqual(schedule.delete_on, date(2026, 5, 31))

    def test_parse_accounting_period_requires_yyyy_mm(self) -> None:
        self.assertEqual(parse_accounting_period("2026-02"), date(2026, 2, 1))

        with self.assertRaisesRegex(ValueError, "invalid_accounting_period"):
            parse_accounting_period("2026-2")

    def test_schedule_handles_leap_year_and_december_rollover(self) -> None:
        self.assertEqual(
            period_retention_schedule(date(2024, 11, 1)).delete_on,
            date(2025, 2, 28),
        )
        self.assertEqual(
            period_retention_schedule(date(2024, 12, 1)).delete_on,
            date(2025, 3, 31),
        )


if __name__ == "__main__":
    unittest.main()
