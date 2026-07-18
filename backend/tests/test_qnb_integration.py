from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from datetime import UTC, datetime

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
    QnbConnectionService,
    QnbInvoiceSummary,
    QnbIncomingInvoiceStatus,
    QnbOutgoingInvoiceStatus,
    QnbSoapEfaturaAdapter,
    QnbSyncService,
    build_qnb_adapter_from_env,
    public_qnb_connection_payload,
    normalize_qnb_incoming_status,
)
from app.domain.qnb_sandbox_outgoing import QnbSandboxParty, build_qnb_sandbox_invoice_ubl
from app.domain.qnb_credentials import QnbCredentialCipher, validate_qnb_endpoint
from app.domain.qnb_scheduler import QnbScheduler, due_qnb_status_ettns, normalize_qnb_sync_policy
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
    def __init__(self, responses: list[str | tuple[str, int]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, *, content: str, headers: dict[str, str], timeout: int) -> FakeSoapResponse:
        self.requests.append({"url": url, "content": content, "headers": headers, "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected SOAP request")
        response = self.responses.pop(0)
        if isinstance(response, tuple):
            return FakeSoapResponse(response[0], response[1])
        return FakeSoapResponse(response)


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


def zipped_base64_file(name: str, content: bytes) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class QnbIntegrationTests(unittest.TestCase):
    def test_qnb_scheduler_claims_due_policy_and_schedules_next_run(self) -> None:
        class Service:
            def sync_incoming_invoices(self, *, client_id: str, max_documents: int = 100):
                return {"status": "completed", "downloaded_count": 1}

            def reconcile_incoming_invoices(self, *, client_id: str):
                return {"status": "completed", "updated_count": 1}

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
            store.save_qnb_sync_policy(
                client_id="client-1",
                policy=normalize_qnb_sync_policy({"enabled": True, "frequency_minutes": 30}, now=now),
            )
            result = QnbScheduler(store=store, service_factory=Service, worker_id="worker-a").run_due_once(now=now)

            self.assertEqual(result["client_id"], "client-1")
            policy = store.get_qnb_sync_policy(client_id="client-1")
            self.assertEqual(policy["last_run_status"], "completed")
            self.assertEqual(policy["consecutive_failure_count"], 0)
            self.assertEqual(policy["lease_owner"], "")
            self.assertEqual(policy["next_run_at"], "2026-07-11T12:30:00+00:00")

    def test_qnb_scheduler_lease_prevents_double_claim_and_failure_backs_off(self) -> None:
        class FailingService:
            def sync_incoming_invoices(self, *, client_id: str, max_documents: int = 100):
                raise RuntimeError("provider unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
            store.save_qnb_sync_policy(
                client_id="client-1",
                policy=normalize_qnb_sync_policy({"enabled": True, "frequency_minutes": 15}, now=now),
            )
            claimed = store.claim_due_qnb_sync_policy(
                worker_id="worker-a", now="2026-07-11T12:00:00+00:00", lease_expires_at="2026-07-11T12:10:00+00:00"
            )
            self.assertIsNotNone(claimed)
            self.assertIsNone(store.claim_due_qnb_sync_policy(
                worker_id="worker-b", now="2026-07-11T12:00:00+00:00", lease_expires_at="2026-07-11T12:10:00+00:00"
            ))
            store.save_qnb_sync_policy(client_id="client-1", policy={**claimed, "lease_owner": "", "lease_expires_at": ""})
            result = QnbScheduler(store=store, service_factory=FailingService, worker_id="worker-b").run_due_once(now=now)
            self.assertEqual(result["error_code"], "RuntimeError")
            self.assertEqual(result["policy"]["next_run_at"], "2026-07-11T12:30:00+00:00")

    def test_qnb_status_schedule_prioritizes_recent_and_risk_sensitive_documents(self) -> None:
        now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
        workspace = {"uploaded_documents": [
            {"source_provider": "qnb_esolutions", "source_qnb_ettn": "recent", "source_issue_date": "2026-07-10", "source_qnb_status_checked_at": "2026-07-11T05:00:00+00:00"},
            {"source_provider": "qnb_esolutions", "source_qnb_ettn": "old-safe", "source_issue_date": "2026-01-01", "source_qnb_status_checked_at": "2026-07-10T12:00:00+00:00"},
            {"source_provider": "qnb_esolutions", "source_qnb_ettn": "exported", "source_issue_date": "2026-06-01", "source_qnb_status_checked_at": "2026-07-10T11:00:00+00:00", "export_status": "exported"},
        ]}
        self.assertEqual(due_qnb_status_ettns(workspace, now=now, limit=10), ["recent", "exported"])

    def test_qnb_expired_lease_can_be_reclaimed_after_worker_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
            store.save_qnb_sync_policy(client_id="client-1", policy=normalize_qnb_sync_policy({"enabled": True}, now=now))
            first = store.claim_due_qnb_sync_policy(worker_id="worker-before-restart", now="2026-07-11T12:00:00+00:00", lease_expires_at="2026-07-11T12:10:00+00:00")
            self.assertIsNotNone(first)
            reclaimed = store.claim_due_qnb_sync_policy(worker_id="worker-after-restart", now="2026-07-11T12:11:00+00:00", lease_expires_at="2026-07-11T12:21:00+00:00")
            self.assertEqual(reclaimed["lease_owner"], "worker-after-restart")

    def test_qnb_connection_secret_is_encrypted_and_metadata_update_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "qnb.key"
            with patch.dict(os.environ, {"FISORA_QNB_CREDENTIAL_KEY_FILE": str(key_file), "FISORA_QNB_ERP_CODE": "PLATFORM-ERP"}):
                store_path = Path(temp_dir) / "store.json"
                store = JsonWorkflowStore(store_path)
                service = QnbConnectionService(
                    store=store,
                    document_storage_path=Path(temp_dir) / "documents",
                    adapter=FakeQnbEfaturaAdapter(),
                )
                first = service.save_connection(
                    client_id="client-1",
                    base_url="https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws",
                    username="user-1",
                    password="super-secret-password",
                    vkn="123",
                    environment="test",
                    actor_user_id="accountant-1",
                )
                ciphertext = store.get_qnb_connection(client_id="client-1")["credential_ciphertext"]
                second = service.save_connection(
                    client_id="client-1",
                    base_url="https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws",
                    username="user-2",
                    password="",
                    vkn="123",
                    environment="test",
                    actor_user_id="accountant-1",
                )
                stored_text = store_path.read_text(encoding="utf-8")
                events = store.list_operation_events(client_id="client-1")
                latest_connection = store.get_qnb_connection(client_id="client-1")

        self.assertNotIn("super-secret-password", stored_text)
        self.assertNotIn("super-secret-password", str(first) + str(second) + str(events))
        self.assertEqual(ciphertext, latest_connection["credential_ciphertext"])
        self.assertEqual(latest_connection["erp_code"], "PLATFORM-ERP")
        self.assertEqual(events[-1]["actor_user_id"], "accountant-1")
        self.assertNotIn("credential", str(events[-1].get("metadata", {})))

    def test_qnb_endpoint_environment_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "production credential"):
            validate_qnb_endpoint(
                "https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws", "production"
            )
        with self.assertRaisesRegex(ValueError, "test credential"):
            validate_qnb_endpoint("https://erp.qnbesolutions.com.tr/efatura/ws", "test")
        with self.assertRaisesRegex(ValueError, "host is not allowed"):
            validate_qnb_endpoint("https://example.test/efatura/ws", "test")

    def test_qnb_production_requires_external_credential_key(self) -> None:
        with patch.dict(os.environ, {"FISORA_ENV": "production", "FISORA_QNB_CREDENTIAL_KEY": ""}, clear=False):
            with self.assertRaisesRegex(ValueError, "required in production"):
                QnbCredentialCipher.from_env()

    def test_qnb_incoming_status_contract_maps_official_response_codes(self) -> None:
        self.assertEqual(normalize_qnb_incoming_status("-1"), "received")
        self.assertEqual(normalize_qnb_incoming_status("0"), "received")
        self.assertEqual(normalize_qnb_incoming_status("1"), "rejected")
        self.assertEqual(normalize_qnb_incoming_status("2"), "accepted")
        self.assertEqual(normalize_qnb_incoming_status("2", cancelled_at="2026-07-11"), "cancelled")
        self.assertEqual(normalize_qnb_incoming_status("99"), "unknown")

    def test_qnb_soap_adapter_queries_incoming_status_by_ettn(self) -> None:
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.csap.cs.com.tr/\" />"),
                soap_body(
                    "<ns2:gelenBelgeDurumSorgulaExtResponse xmlns:ns2=\"http://service.connector.uut.cs.com.tr/\">"
                    "<return><ettn>ETTN-1</ettn><yanitDurumu>1</yanitDurumu><yanitDetayi>Red cevabi</yanitDetayi></return>"
                    "</ns2:gelenBelgeDurumSorgulaExtResponse>"
                ),
            ]
        )
        adapter = QnbSoapEfaturaAdapter(http_client=http_client)
        status = adapter.get_incoming_invoice_status(
            QnbConnectionCredentials("https://test/efatura/ws", "u", "p", "123", "ERP"), ettn="ETTN-1"
        )

        self.assertEqual(status.normalized_status, "rejected")
        self.assertIn("<ettn>ETTN-1</ettn>", str(http_client.requests[1]["content"]))
        self.assertIn("<belgeTuru>FATURA</belgeTuru>", str(http_client.requests[1]["content"]))
        self.assertIn("<donusTipiVersiyon>7.0</donusTipiVersiyon>", str(http_client.requests[1]["content"]))

    def test_rejected_incoming_qnb_invoice_is_held_for_review_with_snapshot(self) -> None:
        ettn = "ETTN-REJECTED"
        adapter = FakeQnbEfaturaAdapter(
            incoming_statuses={ettn: QnbIncomingInvoiceStatus(ettn, "1", "rejected", "Ticari fatura reddedildi")}
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_connection(
                client_id="client-1",
                connection={"status": "active", "base_url": "test", "username": "u", "password": "p", "vkn": "1", "erp_code": "e"},
            )
            store.save_uploaded_document(
                client_id="client-1",
                document={"document_id": "doc-1", "source_provider": "qnb_esolutions", "source_external_uuid": ettn},
            )
            result = QnbConnectionService(
                store=store, document_storage_path=Path(temp_dir) / "documents", adapter=adapter
            ).reconcile_incoming_invoice(client_id="client-1", ettn=ettn)
            document = store.get_workspace("client-1")["uploaded_documents"][0]
            snapshots = store._read()["qnb_incoming_status_snapshots"]

        self.assertEqual(result["normalized_status"], "rejected")
        self.assertTrue(result["review_required"])
        self.assertTrue(document["automation_hold"])
        self.assertEqual(document["automation_hold_reason"], "qnb_status_review_required")
        self.assertEqual(len(snapshots), 1)

    def test_outgoing_status_reconciliation_keeps_append_only_evidence_and_detects_change(self) -> None:
        oid = "OID-123"
        adapter = FakeQnbEfaturaAdapter(
            outgoing_statuses={oid: QnbOutgoingInvoiceStatus(oid, "1", "received", "Alindi")}
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_connection(
                client_id="client-1",
                connection={"status": "active", "base_url": "test", "username": "u", "password": "p", "vkn": "1", "erp_code": "e"},
            )
            service = QnbConnectionService(store=store, document_storage_path=Path(temp_dir) / "documents", adapter=adapter)
            first = service.reconcile_outgoing_invoice(client_id="client-1", document_oid=oid, invoice_no="FSR1")
            adapter.outgoing_statuses[oid] = QnbOutgoingInvoiceStatus(oid, "3", "processed", "Islendi", ettn="ETTN-1")
            second = service.reconcile_outgoing_invoice(client_id="client-1", document_oid=oid)
            snapshots = store._read()["qnb_outgoing_status_snapshots"]

        self.assertFalse(first["changed"])
        self.assertTrue(second["changed"])
        self.assertEqual(second["previous_processing_state"], "received")
        self.assertEqual(second["processing_state"], "processed")
        self.assertEqual(second["invoice_no"], "FSR1")
        self.assertEqual(len(snapshots), 2)

    def test_unknown_outgoing_status_is_review_warning_not_success(self) -> None:
        oid = "OID-UNKNOWN"
        adapter = FakeQnbEfaturaAdapter(
            outgoing_statuses={oid: QnbOutgoingInvoiceStatus(oid, "99", "unknown", description="Yeni durum")}
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_connection(
                client_id="client-1",
                connection={"status": "active", "base_url": "test", "username": "u", "password": "p", "vkn": "1", "erp_code": "e"},
            )
            result = QnbConnectionService(
                store=store, document_storage_path=Path(temp_dir) / "documents", adapter=adapter
            ).reconcile_outgoing_invoice(client_id="client-1", document_oid=oid)

        self.assertEqual(result["processing_state"], "unknown")
        self.assertEqual(result["severity"], "warning")

    def test_bulk_outgoing_status_reconciliation_uses_persisted_documents(self) -> None:
        statuses = {
            "OID-1": QnbOutgoingInvoiceStatus("OID-1", "3", "processed"),
            "OID-2": QnbOutgoingInvoiceStatus("OID-2", "2", "processing_error"),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_connection(
                client_id="client-1",
                connection={"status": "active", "base_url": "test", "username": "u", "password": "p", "vkn": "1", "erp_code": "e"},
            )
            for oid in statuses:
                store.save_qnb_outgoing_invoice(client_id="client-1", invoice={"document_oid": oid, "processing_state": "received"})
            result = QnbConnectionService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=FakeQnbEfaturaAdapter(outgoing_statuses=statuses),
            ).reconcile_outgoing_invoices(client_id="client-1")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["updated_count"], 2)

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

    def test_qnb_soap_adapter_downloads_pdf_evidence_with_official_format_parameter(self) -> None:
        pdf = b"%PDF-1.7\nQNB test evidence"
        http_client = FakeSoapHttpClient([
            soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.earsiv.qnb.com/\" />"),
            soap_body(f"<ns2:gelenBelgeleriIndirExtResponse xmlns:ns2=\"http://service.efatura.qnb.com/\"><return>{zipped_base64_file('invoice.pdf', pdf)}</return></ns2:gelenBelgeleriIndirExtResponse>"),
        ])
        adapter = QnbSoapEfaturaAdapter(http_client=http_client)
        invoice = QnbInvoiceSummary("ettn-1", "QNB1", "42", "20260709", "5910611341", "Satici", "120")
        document = adapter.download_incoming_invoice_pdf(QnbConnectionCredentials("https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws", "user", "secret", "5910611341", "FSR31422"), invoice)
        self.assertEqual(document.content, pdf)
        self.assertEqual(document.content_type, "application/pdf")
        self.assertIn("<belgeFormati>PDF</belgeFormati>", str(http_client.requests[1]["content"]))

    def test_qnb_pdf_evidence_is_linked_to_ubl_and_idempotent(self) -> None:
        pdf = b"%PDF-1.7\nlinked evidence"
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"FISORA_QNB_CREDENTIAL_KEY_FILE": str(Path(temp_dir) / "qnb.key")}):
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_connection(client_id="client-1", connection={"status": "active", "base_url": "https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws", "username": "u", "password": "p", "vkn": "1", "erp_code": "ERP"})
            source = store.save_uploaded_document(client_id="client-1", document={"document_ref": "ubl-1", "document_type": "einvoice_xml", "source_provider": "qnb_esolutions", "source_external_uuid": "ettn-1", "source_invoice_no": "QNB1"})
            service = QnbConnectionService(store=store, document_storage_path=Path(temp_dir) / "documents", adapter=FakeQnbEfaturaAdapter(pdf_downloads={"ettn-1": pdf}))
            first = service.download_incoming_pdf(client_id="client-1", ettn="ettn-1")
            second = service.download_incoming_pdf(client_id="client-1", ettn="ettn-1")
        self.assertEqual(first["document_ref"], second["document_ref"])
        self.assertEqual(first["source_parent_document_ref"], source["document_ref"])
        self.assertEqual(first["processing_status"], "evidence_only")

    def test_qnb_download_rejects_unsafe_or_ambiguous_zip(self) -> None:
        from app.domain.qnb_efatura import _decode_qnb_download_payload

        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../invoice.xml", UBL_XML)
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            _decode_qnb_download_payload(base64.b64encode(unsafe.getvalue()).decode("ascii"))

        ambiguous = io.BytesIO()
        with zipfile.ZipFile(ambiguous, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("invoice-1.xml", UBL_XML)
            archive.writestr("invoice-2.xml", UBL_XML)
        with self.assertRaisesRegex(ValueError, "exactly one XML"):
            _decode_qnb_download_payload(base64.b64encode(ambiguous.getvalue()).decode("ascii"))

    def test_qnb_soap_adapter_retries_temporary_server_error(self) -> None:
        sleeps: list[float] = []
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.csap.cs.com.tr/\" />"),
                (soap_body("<soap:Fault xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\" />"), 500),
                soap_body(
                    """
<ns2:gelenBelgeleriListeleExtResponse xmlns:ns2="http://service.connector.uut.cs.com.tr/">
  <return><ettn>retry-ettn</ettn><belgeNo>FSR2026000000002</belgeNo><belgeSiraNo>2</belgeSiraNo></return>
</ns2:gelenBelgeleriListeleExtResponse>
"""
                ),
            ]
        )
        adapter = QnbSoapEfaturaAdapter(http_client=http_client, sleep=sleeps.append, max_attempts=3)

        invoices = adapter.list_incoming_invoices(
            QnbConnectionCredentials(
                base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                username="5910611341",
                password="secret-password",
                vkn="5910611341",
                erp_code="FSR31422",
            )
        )

        self.assertEqual(invoices[0].sequence_no, "2")
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(len(http_client.requests), 3)

    def test_qnb_sync_closes_real_soap_session_after_page_run(self) -> None:
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.csap.cs.com.tr/\" />"),
                soap_body('<ns2:gelenBelgeleriListeleExtResponse xmlns:ns2="http://service.connector.uut.cs.com.tr/" />'),
                soap_body("<ns2:logoutResponse xmlns:ns2=\"http://service.csap.cs.com.tr/\" />"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = QnbSyncService(
                store=JsonWorkflowStore(Path(temp_dir) / "store.json"),
                document_storage_path=Path(temp_dir) / "documents",
                adapter=QnbSoapEfaturaAdapter(http_client=http_client),
            ).sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials(
                    "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                    "5910611341",
                    "secret-password",
                    "5910611341",
                    "FSR31422",
                ),
                start_date="2026-07-10",
                end_date="2026-07-10",
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(http_client.requests), 3)
        self.assertIn("<qnb:logout", str(http_client.requests[2]["content"]))

    def test_qnb_adapter_rejects_cursor_mixed_with_date_filters(self) -> None:
        adapter = FakeQnbEfaturaAdapter()
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            adapter.list_incoming_page(
                QnbConnectionCredentials("https://example.test", "user", "secret", "1", "ERP"),
                start_date="2026-07-01",
                cursor="10",
            )

    def test_qnb_cursor_sync_pages_and_persists_safe_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            invoices = [
                QnbInvoiceSummary(
                    ettn=f"ettn-{index}",
                    invoice_no=f"FS{index:014d}",
                    sequence_no=str(index),
                    issue_date="20260710",
                    supplier_tax_id="5910611341",
                    supplier_title="QNB Test Satici",
                    payable_total="120.00",
                )
                for index in range(1, 12)
            ]
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            adapter = FakeQnbEfaturaAdapter(
                invoices=invoices,
                downloads={invoice.ettn: UBL_XML for invoice in invoices},
                page_size=5,
            )
            result = QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=adapter,
                max_pages=5,
            ).sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials("https://example.test", "user", "secret", "1", "ERP"),
            )
            saved_cursor = store.get_qnb_sync_cursor(client_id="client-1")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["listed_count"], 11)
        self.assertEqual(result["downloaded_count"], 11)
        self.assertEqual(result["cursor_after"], "11")
        self.assertEqual(saved_cursor, "11")

    def test_qnb_fake_page_models_provider_one_hundred_document_limit(self) -> None:
        invoices = [
            QnbInvoiceSummary(f"ettn-{index}", f"FS{index:014d}", str(index), "20260710", "5910611341", "Test", "120.00")
            for index in range(1, 102)
        ]
        page = FakeQnbEfaturaAdapter(invoices=invoices).list_incoming_page(
            QnbConnectionCredentials("https://example.test", "user", "secret", "1", "ERP")
        )

        self.assertEqual(len(page.items), 100)
        self.assertEqual(page.last_sequence_no, "100")
        self.assertTrue(page.has_more)

    def test_qnb_cursor_does_not_advance_when_page_partially_fails(self) -> None:
        class FailingDownloadAdapter(FakeQnbEfaturaAdapter):
            def download_incoming_invoice_ubl(self, credentials, invoice):
                if invoice.sequence_no == "2":
                    raise ValueError("temporary download failure")
                return super().download_incoming_invoice_ubl(credentials, invoice)

        with tempfile.TemporaryDirectory() as temp_dir:
            invoices = [
                QnbInvoiceSummary(f"ettn-{index}", f"FS{index:014d}", str(index), "20260710", "5910611341", "Test", "120.00")
                for index in range(1, 4)
            ]
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            adapter = FailingDownloadAdapter(
                invoices=invoices,
                downloads={invoice.ettn: UBL_XML for invoice in invoices},
            )
            result = QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=adapter,
            ).sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials("https://example.test", "user", "secret", "1", "ERP"),
            )
            failed_identity_reclaimed = store.claim_qnb_document_identity(
                client_id="client-1",
                identity_key="ettn:ettn-2",
            )
            saved_cursor = store.get_qnb_sync_cursor(client_id="client-1")

        self.assertEqual(result["status"], "partial_failed")
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["errors"][0]["code"], "provider_error")
        self.assertEqual(result["cursor_after"], "")
        self.assertEqual(saved_cursor, "")
        self.assertTrue(failed_identity_reclaimed)

    def test_qnb_backfill_reports_truncated_instead_of_mixing_cursor_and_dates(self) -> None:
        invoices = [
            QnbInvoiceSummary(f"ettn-{index}", f"FS{index:014d}", str(index), "20260710", "5910611341", "Test", "120.00")
            for index in range(1, 4)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            result = QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=FakeQnbEfaturaAdapter(
                    invoices=invoices,
                    downloads={invoice.ettn: UBL_XML for invoice in invoices},
                    page_size=2,
                ),
            ).sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials("https://example.test", "user", "secret", "1", "ERP"),
                start_date="2026-07-10",
                end_date="2026-07-10",
            )

        self.assertEqual(result["status"], "partial_failed")
        self.assertTrue(result["backfill_truncated"])
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["cursor_after"], "")

    def test_qnb_soap_adapter_lists_mailbox_labels_and_sends_outgoing_ubl(self) -> None:
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.csap.cs.com.tr/\" />"),
                soap_body(
                    """
<ns2:getMukellefAktifEtiketListResponse xmlns:ns2="http://service.connector.uut.cs.com.tr/">
  <return><acilisZamani>20250708140347</acilisZamani><etiket>urn:mail:sendergb@example.test</etiket><tip>GB</tip></return>
</ns2:getMukellefAktifEtiketListResponse>
"""
                ),
                soap_body(
                    """
<ns2:belgeGonderExtResponse xmlns:ns2="http://service.connector.uut.cs.com.tr/">
  <belgeOid>oid-123</belgeOid>
</ns2:belgeGonderExtResponse>
"""
                ),
            ]
        )
        adapter = QnbSoapEfaturaAdapter(http_client=http_client)
        credentials = QnbConnectionCredentials(
            base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
            username="5910611341",
            password="secret-password",
            vkn="5910611341",
            erp_code="FSR31422",
        )

        labels = adapter.list_active_mailbox_labels(credentials)
        result = adapter.send_outgoing_invoice_ubl(
            credentials,
            invoice_no="FSR2026000000001",
            content=UBL_XML,
            recipient_label="urn:mail:receiverpk@example.test",
            sender_label=labels[0].label,
        )

        self.assertEqual(labels[0].kind, "GB")
        self.assertEqual(result.document_oid, "oid-123")
        request = str(http_client.requests[2]["content"])
        self.assertIn("<qnb:belgeGonderExt", request)
        self.assertIn("<belgeTuru>FATURA_UBL</belgeTuru>", request)
        self.assertIn("<erpKodu>FSR31422</erpKodu>", request)
        self.assertIn("<alanEtiket>urn:mail:receiverpk@example.test</alanEtiket>", request)
        self.assertIn(f"<belgeHash>{hashlib.md5(UBL_XML).hexdigest()}</belgeHash>", request)
        self.assertIn(base64.b64encode(UBL_XML).decode("ascii"), request)

    def test_qnb_soap_adapter_reads_outgoing_status_by_oid(self) -> None:
        http_client = FakeSoapHttpClient(
            [
                soap_body("<ns2:wsLoginResponse xmlns:ns2=\"http://service.csap.cs.com.tr/\" />"),
                soap_body(
                    """
<ns2:gidenBelgeDurumSorgulaExtResponse xmlns:ns2="http://service.connector.uut.cs.com.tr/">
  <return><durum>3</durum><gonderimDurumu>ISLENDI</gonderimDurumu><aciklama>Belge islendi</aciklama><ettn>11111111-2222-3333-4444-555555555555</ettn></return>
</ns2:gidenBelgeDurumSorgulaExtResponse>
"""
                ),
            ]
        )
        adapter = QnbSoapEfaturaAdapter(http_client=http_client)
        status = adapter.get_outgoing_invoice_status(
            QnbConnectionCredentials(
                base_url="https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
                username="5910611341",
                password="secret-password",
                vkn="5910611341",
                erp_code="FSR31422",
            ),
            document_oid="oid-123",
        )

        self.assertEqual(status.status_code, "3")
        self.assertEqual(status.processing_state, "processed")
        self.assertEqual(status.status_text, "ISLENDI")
        self.assertEqual(status.ettn, "11111111-2222-3333-4444-555555555555")
        request = str(http_client.requests[1]["content"])
        self.assertIn("<belgeNo>oid-123</belgeNo>", request)
        self.assertIn("<belgeNoTipi>OID</belgeNoTipi>", request)

    def test_build_qnb_sandbox_invoice_ubl_has_required_parties_and_totals(self) -> None:
        from datetime import date, time
        from decimal import Decimal

        content = build_qnb_sandbox_invoice_ubl(
            invoice_no="FSR2026000000001",
            invoice_uuid="11111111-2222-3333-4444-555555555555",
            issue_date=date(2026, 7, 10),
            issue_time=time(12, 0, 0),
            supplier=QnbSandboxParty("5910611341", "Fisora Test2", "urn:mail:sendergb@example.test"),
            customer=QnbSandboxParty("5910611340", "Fisora Test1", "urn:mail:receiverpk@example.test"),
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("20"),
        )

        text = content.decode("utf-8")
        self.assertIn("<cbc:CustomizationID>TR1.2</cbc:CustomizationID>", text)
        self.assertIn("<cbc:ProfileID>TEMELFATURA</cbc:ProfileID>", text)
        self.assertIn("5910611341", text)
        self.assertIn("5910611340", text)
        self.assertIn('<cbc:TaxAmount currencyID="TRY">20.00</cbc:TaxAmount>', text)
        self.assertIn('<cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount>', text)

        from app.domain.qnb_sandbox_outgoing import validate_qnb_sandbox_invoice_ubl

        with self.assertRaisesRegex(ValueError, "supplier_vkn"):
            validate_qnb_sandbox_invoice_ubl(
                content,
                expected_invoice_no="FSR2026000000001",
                expected_supplier_vkn="9999999999",
                expected_customer_vkn="5910611340",
            )

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

    def test_qnb_connection_is_isolated_from_another_client_user(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"FISORA_QNB_CREDENTIAL_KEY_FILE": str(Path(temp_dir) / "qnb.key")}):
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
                client = TestClient(app)
                for client_id in ("client-a", "client-b"):
                    client.post("/phase0/store/client", json={"client_id": client_id, "title": client_id, "has_chart_accounts": True})
                client.post(
                    "/phase0/store/portal-user",
                    json={"user_id": "accountant", "display_name": "Accountant", "role": "accountant", "allowed_client_ids": ["client-a", "client-b"]},
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={"user_id": "client-b-user", "display_name": "Client B", "role": "client_user", "allowed_client_ids": ["client-b"]},
                )
                saved = client.post(
                    "/phase0/qnb/connections/client-a",
                    headers={"X-Fisora-User-Id": "accountant"},
                    json={
                        "base_url": "https://erpefaturatest1.qnbesolutions.com.tr/efatura/ws",
                        "username": "client-a-ws",
                        "password": "client-a-secret",
                        "vkn": "111",
                        "environment": "test",
                    },
                )
                forbidden = client.get(
                    "/phase0/qnb/connections/client-a", headers={"X-Fisora-User-Id": "client-b-user"}
                )
                store_text = (Path(temp_dir) / "store.json").read_text(encoding="utf-8")

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(forbidden.status_code, 403)
        self.assertNotIn("client-a-secret", str(saved.json()) + str(forbidden.json()) + store_text)


if __name__ == "__main__":
    unittest.main()
