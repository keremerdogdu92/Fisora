from __future__ import annotations

import unittest
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.gemini_credential_slots import normalize_gemini_credential_slot


class GeminiCredentialSlotTests(unittest.TestCase):
    def test_only_empty_or_exact_slots_one_through_eight_are_accepted(self) -> None:
        valid = ("", *(f"GEMINI_API_KEY_SLOT_{index}" for index in range(1, 9)))
        for value in valid:
            with self.subTest(value=value):
                self.assertEqual(normalize_gemini_credential_slot(value), value)

    def test_api_key_digest_bounds_and_malformed_values_are_rejected(self) -> None:
        invalid = (
            "AIzaSyRAW-API-KEY",
            "a" * 64,
            "GEMINI_API_KEY_SLOT_0",
            "GEMINI_API_KEY_SLOT_9",
            " GEMINI_API_KEY_SLOT_1",
            "GEMINI_API_KEY_SLOT_1 ",
            "gemini_api_key_slot_1",
            None,
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "credential slot"):
                normalize_gemini_credential_slot(value)


if __name__ == "__main__":
    unittest.main()
