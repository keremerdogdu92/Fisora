from __future__ import annotations

import base64
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

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

from app.domain.qnb_efatura import (
    FakeQnbEfaturaAdapter,
    QnbConnectionCredentials,
    QnbInvoiceSummary,
    QnbSoapEfaturaAdapter,
    QnbSyncService,
    build_qnb_adapter_from_env,
    public_qnb_connection_payload,
)
from app.persistence.workflow_store import JsonWorkflowStore


UBL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>QNB2026000000001</ID>
  <UUID>11111111-2222-3333-4444-555555555555</UUID>
</Invoice>
"""


class FakeSoapResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSoapHttpClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, *, content: str, headers: dict[str, str], timeout: int) -> FakeSoapResponse:
        self.requests.append({"url": url, "content": content, "headers": headers, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected SOAP request")
        return FakeSoapResponse(self.responses.pop(0))


def soap_body(inner: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>{inner}</soap:Body>
</soap:Envelope>
"""


def zipped_base64_xml(content: bytes) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("invoice.xml", content)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class QnbIntegrationTests(unittest.TestCase):
    def test_qnb_adapter_factory_uses_fake_by_default_and_soap_when_enabled(self) -> None:
        self.assertIsInstance(build_qnb_adapter_from_env({}), FakeQnbEfaturaAdapter)
        self.assertIsInstance(build_qnb_adapter_from_env({"FISORA_QNB_ADAPTER": "soap"}), QnbSoapEfaturaAdapter)

    def test_qnb_soap_adapter_logs_in_and_lists_incoming_invoices(self) -> None:
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.earsiv.qnb.com/\" />"),
                soap_body(
                    """
<ns2:gelenBelgeleriListeleExtResponse xmlns:ns2="http://service.efatura.qnb.com/">
  <return>
    <ettn>11111111-2222-3333-4444-555555555555</ettn>
    <belgeNo>QNB2026000000001</belgeNo>
    <belgeSiraNo>42</belgeSiraNo>
    <belgeTarihi>20260709</belgeTarihi>
    <gonderenVknTckn>5910611341</gonderenVknTckn>
    <saticiUnvan>QNB Test Satici</saticiUnvan>
    <payableAmount>120.00</payableAmount>
    <yanitDurumu>ONAYLANAN</yanitDurumu>
  </return>
</ns2:gelenBelgeleriListeleExtResponse>
"""
                ),
            ]
        )
        adapter = QnbSoapEfaturaAdapter(http_client=http_client)

        invoices = adapter.list_incoming_invoices(
            QnbConnectionCredentials(
                base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                username="5910611341",
                password="secret-password",
                vkn="5910611341",
                erp_code="FSR31422",
            ),
            start_date="2026-07-01",
            end_date="2026-07-09",
        )

        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].ettn, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(invoices[0].invoice_no, "QNB2026000000001")
        self.assertEqual(invoices[0].sequence_no, "42")
        self.assertEqual(invoices[0].supplier_title, "QNB Test Satici")
        self.assertEqual(http_client.requests[0]["url"], "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws/userService")
        self.assertEqual(http_client.requests[1]["url"], "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws/connectorService")
        self.assertIn("<userId>5910611341</userId>", str(http_client.requests[0]["content"]))
        self.assertIn("<erpKodu>FSR31422</erpKodu>", str(http_client.requests[1]["content"]))
        self.assertIn("<gelisTarihiBaslangic>2026-07-01</gelisTarihiBaslangic>", str(http_client.requests[1]["content"]))

    def test_qnb_soap_adapter_downloads_zipped_ubl_xml(self) -> None:
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.earsiv.qnb.com/\" />"),
                soap_body(
                    f"""
<ns2:gelenBelgeleriIndirExtResponse xmlns:ns2="http://service.efatura.qnb.com/">
  <return>{zipped_base64_xml(UBL_XML)}</return>
</ns2:gelenBelgeleriIndirExtResponse>
"""
                ),
            ]
        )
        adapter = QnbSoapEfaturaAdapter(http_client=http_client)
        invoice = QnbInvoiceSummary(
            ettn="11111111-2222-3333-4444-555555555555",
            invoice_no="QNB2026000000001",
            sequence_no="42",
            issue_date="20260709",
            supplier_tax_id="5910611341",
            supplier_title="QNB Test Satici",
            payable_total="120.00",
        )

        document = adapter.download_incoming_invoice_ubl(
            QnbConnectionCredentials(
                base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                username="5910611341",
                password="secret-password",
                vkn="5910611341",
                erp_code="FSR31422",
            ),
            invoice,
        )

        self.assertEqual(document.file_name, "qnb-11111111-2222-3333-4444-555555555555.xml")
        self.assertEqual(document.content, UBL_XML)
        self.assertIn("<belgeFormati>UBL</belgeFormati>", str(http_client.requests[1]["content"]))
        self.assertIn("<ettn>11111111-2222-3333-4444-555555555555</ettn>", str(http_client.requests[1]["content"]))

    def test_public_connection_payload_masks_secret_fields(self) -> None:
        payload = public_qnb_connection_payload(
            {
                "client_id": "client-1",
                "provider": "qnb_esolutions",
                "username": "5910611341",
                "password": "super-secret-password",
                "status": "active",
                "last_error": "",
            }
        )

        self.assertEqual(payload["username"], "5********1")
        self.assertEqual(payload["status"], "active")
        self.assertNotIn("password", payload)
        self.assertNotIn("super-secret-password", str(payload))

    def test_fake_qnb_sync_stores_ubl_and_queues_processing_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            adapter = FakeQnbEfaturaAdapter(
                invoices=[
                    QnbInvoiceSummary(
                        ettn="11111111-2222-3333-4444-555555555555",
                        invoice_no="QNB2026000000001",
                        sequence_no="42",
                        issue_date="20260709",
                        supplier_tax_id="5910611341",
                        supplier_title="QNB Test Satici",
                        payable_total="120.00",
                        qnb_status="ONAYLANAN",
                    )
                ],
                downloads={"11111111-2222-3333-4444-555555555555": UBL_XML},
            )
            service = QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=adapter,
            )

            result = service.sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials(
                    base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    username="5910611341",
                    password="secret",
                    vkn="5910611341",
                    erp_code="FSR31422",
                ),
                start_date="2026-07-01",
                end_date="2026-07-09",
            )
            workspace = store.get_workspace("client-1")
            stored_file_exists = Path(workspace["uploaded_documents"][0]["storage_path"]).exists()

        self.assertEqual(result["listed_count"], 1)
        self.assertEqual(result["downloaded_count"], 1)
        self.assertEqual(result["queued_processing_count"], 1)
        self.assertEqual(result["skipped_duplicate_count"], 0)
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        document = workspace["uploaded_documents"][0]
        self.assertEqual(document["document_type"], "einvoice_xml")
        self.assertEqual(document["intake_category"], "purchase_invoice")
        self.assertEqual(document["source_provider"], "qnb_esolutions")
        self.assertEqual(document["source_external_uuid"], "11111111-2222-3333-4444-555555555555")
        self.assertTrue(stored_file_exists)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertEqual(workspace["processing_jobs"][0]["parser_kind"], "einvoice_xml")
        self.assertIn("qnb_ubl_stored", [event["step"] for event in workspace["document_pipeline_events"]])
        self.assertNotIn("secret", str(workspace["document_pipeline_events"]))

    def test_qnb_sync_skips_duplicate_ettn_without_second_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            adapter = FakeQnbEfaturaAdapter(
                invoices=[
                    QnbInvoiceSummary(
                        ettn="duplicate-ettn",
                        invoice_no="QNB2026000000002",
                        sequence_no="43",
                        issue_date="20260709",
                        supplier_tax_id="5910611341",
                        supplier_title="QNB Test Satici",
                        payable_total="240.00",
                        qnb_status="ONAYLANAN",
                    )
                ],
                downloads={"duplicate-ettn": UBL_XML},
            )
            service = QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=adapter,
            )
            credentials = QnbConnectionCredentials(
                base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                username="5910611341",
                password="secret",
                vkn="5910611341",
                erp_code="FSR31422",
            )

            first = service.sync_incoming_invoices(client_id="client-1", credentials=credentials)
            second = service.sync_incoming_invoices(client_id="client-1", credentials=credentials)
            workspace = store.get_workspace("client-1")

        self.assertEqual(first["downloaded_count"], 1)
        self.assertEqual(second["downloaded_count"], 0)
        self.assertEqual(second["skipped_duplicate_count"], 1)
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)

    def test_qnb_connection_api_masks_password_and_syncs_active_connection(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )

            save_response = client.post(
                "/phase0/qnb/connections/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "base_url": "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    "username": "5910611341",
                    "password": "secret-password",
                    "vkn": "5910611341",
                    "erp_code": "FSR31422",
                },
            )
            status_response = client.get(
                "/phase0/qnb/connections/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            sync_response = client.post(
                "/phase0/qnb/connections/client-1/sync-incoming-invoices",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={"start_date": "2026-07-01", "end_date": "2026-07-09"},
            )

        self.assertEqual(save_response.status_code, 200)
        self.assertNotIn("secret-password", str(save_response.json()))
        self.assertEqual(save_response.json()["status"], "active")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["username"], "5********1")
        self.assertEqual(sync_response.status_code, 200)
        self.assertEqual(sync_response.json()["listed_count"], 0)
        self.assertEqual(sync_response.json()["downloaded_count"], 0)

    def test_qnb_sync_api_requires_active_connection(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/qnb/connections/client-1/sync-incoming-invoices",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={"start_date": "2026-07-01", "end_date": "2026-07-09"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("active QNB connection", str(response.json()))


if __name__ == "__main__":
    unittest.main()
