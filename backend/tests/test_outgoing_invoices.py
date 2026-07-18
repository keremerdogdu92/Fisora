from __future__ import annotations

import base64
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient

    from app.api import phase0
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None

from app.domain.outgoing_invoices import OutgoingInvoiceService
from app.persistence.workflow_store import JsonWorkflowStore


def invoice_payload(*, document_type: str = "earsiv", profile: str = "EARSIVFATURA") -> dict[str, object]:
    return {
        "document_type": document_type,
        "profile": profile,
        "invoice_no": "GIB2026000000001",
        "issue_date": "2026-07-13",
        "currency": "TRY",
        "supplier": {"tax_id": "5910611340", "title": "Fisora Test", "tax_office": "Kadikoy"},
        "customer": {"tax_id": "11111111111", "title": "Test Musteri"},
        "lines": [
            {"name": "Danismanlik", "quantity": "2", "unit_price": "100.00", "vat_rate": "20"},
            {"name": "Kurulum", "quantity": "1", "unit_price": "50.00", "vat_rate": "10"},
        ],
    }


class OutgoingInvoiceServiceTests(unittest.TestCase):
    def test_draft_approval_builds_frozen_ubl_with_exact_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OutgoingInvoiceService(store=JsonWorkflowStore(Path(temp_dir) / "store.json"))
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            approved = service.approve(
                client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant"
            )

        self.assertEqual(draft["totals"], {"net_amount": "250.00", "tax_amount": "45.00", "payable_amount": "295.00"})
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(len(approved["ubl_sha256"]), 64)
        root = ElementTree.fromstring(base64.b64decode(approved["ubl_base64"]))
        self.assertTrue(root.tag.endswith("}Invoice"))

    def test_send_requires_approval_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OutgoingInvoiceService(store=JsonWorkflowStore(Path(temp_dir) / "store.json"))
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            with self.assertRaisesRegex(ValueError, "approved"):
                service.send(
                    client_id="client-a",
                    invoice_id=draft["invoice_id"],
                    idempotency_key="send-1",
                    actor_user_id="accountant",
                )
            approved = service.approve(client_id="client-a", invoice_id=draft["invoice_id"], actor_user_id="accountant")
            sent = service.send(
                client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="send-2", actor_user_id="accountant"
            )
            repeated = service.send(
                client_id="client-a", invoice_id=approved["invoice_id"], idempotency_key="send-2", actor_user_id="accountant"
            )

        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sent["provider"], "fake")
        self.assertEqual(repeated["provider_document_id"], sent["provider_document_id"])
        self.assertEqual(len(repeated["history"]), 3)

    def test_invoice_is_tenant_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = OutgoingInvoiceService(store=JsonWorkflowStore(Path(temp_dir) / "store.json"))
            draft = service.create_draft(client_id="client-a", payload=invoice_payload(), actor_user_id="accountant")
            with self.assertRaisesRegex(ValueError, "not found"):
                service.get(client_id="client-b", invoice_id=draft["invoice_id"])


class OutgoingInvoiceApiTests(unittest.TestCase):
    def test_accountant_can_create_approve_and_fake_send(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post("/phase0/store/client", json={"client_id": "client-a", "title": "A", "has_chart_accounts": True})
            client.post(
                "/phase0/store/portal-user",
                json={"user_id": "accountant", "display_name": "Accountant", "role": "accountant", "allowed_client_ids": ["client-a"]},
            )
            headers = {"X-Fisora-User-Id": "accountant"}
            created = client.post("/phase0/outgoing-invoices/client-a/drafts", headers=headers, json=invoice_payload())
            invoice_id = created.json().get("invoice_id", "")
            approved = client.post(f"/phase0/outgoing-invoices/client-a/drafts/{invoice_id}/approve", headers=headers)
            sent = client.post(
                f"/phase0/outgoing-invoices/client-a/drafts/{invoice_id}/send",
                headers=headers,
                json={"idempotency_key": "api-send-1"},
            )

        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["status"], "sent")
        self.assertEqual(sent.json()["receipt"]["mode"], "local_fake")

    def test_client_user_cannot_manage_outgoing_invoices(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)
            client.post("/phase0/store/client", json={"client_id": "client-a", "title": "A", "has_chart_accounts": True})
            client.post(
                "/phase0/store/portal-user",
                json={"user_id": "client-user", "display_name": "Client", "role": "client_user", "allowed_client_ids": ["client-a"]},
            )
            response = client.post(
                "/phase0/outgoing-invoices/client-a/drafts",
                headers={"X-Fisora-User-Id": "client-user"},
                json=invoice_payload(),
            )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
