from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "send_qnb_sandbox_invoice.py"
SPEC = importlib.util.spec_from_file_location("send_qnb_sandbox_invoice", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QnbSandboxOutgoingTests(unittest.TestCase):
    def test_select_label_uses_requested_mailbox_kind(self) -> None:
        from app.domain.qnb_efatura import QnbMailboxLabel

        labels = [
            QnbMailboxLabel("urn:mail:pk@example.test", "PK"),
            QnbMailboxLabel("urn:mail:gb@example.test", "GB"),
        ]

        self.assertEqual(MODULE.select_label(labels, "GB"), "urn:mail:gb@example.test")
        self.assertEqual(MODULE.select_label(labels, "PK"), "urn:mail:pk@example.test")

    def test_sandbox_sender_rejects_non_test_qnb_endpoint(self) -> None:
        self.assertTrue(
            MODULE.is_qnb_sandbox_base_url(
                "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws"
            )
        )
        self.assertFalse(MODULE.is_qnb_sandbox_base_url("https://efatura.qnbesolutions.com.tr/efatura/ws"))


if __name__ == "__main__":
    unittest.main()
