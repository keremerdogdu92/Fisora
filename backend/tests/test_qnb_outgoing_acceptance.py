from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_qnb_outgoing_service_sandbox_acceptance.py"
SPEC = importlib.util.spec_from_file_location("run_qnb_outgoing_service_sandbox_acceptance", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QnbOutgoingAcceptanceTests(unittest.TestCase):
    def test_plan_only_does_not_construct_or_call_service(self) -> None:
        calls: list[str] = []

        result = MODULE.execute_plan(
            {"document_type": "efatura", "invoice_no": "FSR2026000000001"},
            confirm_send=False,
            service_factory=lambda: calls.append("constructed"),
        )

        self.assertFalse(result["sent"])
        self.assertEqual(calls, [])

    def test_confirm_send_uses_common_outgoing_service(self) -> None:
        class Service:
            def create_draft(self, **kwargs: object) -> dict[str, object]:
                return {"invoice_id": "invoice-1"}

            def approve(self, **kwargs: object) -> dict[str, object]:
                return {"invoice_id": "invoice-1", "ubl_sha256": "a" * 64}

            def send(self, **kwargs: object) -> dict[str, object]:
                return {
                    "invoice_id": "invoice-1",
                    "status": "sent",
                    "provider": "qnb_sandbox",
                    "provider_document_id": "oid-123",
                    "ubl_sha256": "a" * 64,
                    "current_attempt_id": "attempt-1",
                    "canonical_document_ref": "document-1",
                    "accounting_link_status": "queued",
                }

        result = MODULE.execute_plan(
            {
                "client_id": "qnb-acceptance",
                "document_type": "efatura",
                "invoice_no": "FSR2026000000001",
                "draft_payload": {"document_type": "efatura"},
            },
            confirm_send=True,
            service_factory=Service,
        )

        self.assertTrue(result["sent"])
        self.assertEqual(result["provider_document_id"], "oid-123")
        self.assertNotIn("password", str(result).lower())

    def test_non_test_endpoint_is_rejected_before_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "test endpoint"):
            MODULE.validate_plan_endpoints(
                {
                    "document_type": "efatura",
                    "efatura_base_url": "https://erpefatura.qnbesolutions.com.tr/efatura/ws",
                }
            )


if __name__ == "__main__":
    unittest.main()
