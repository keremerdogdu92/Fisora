from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_uploads import (
    decode_base64_content,
    document_storage_status,
    extend_retention_deadline,
    retention_decision,
    sanitize_file_name,
    store_document_content,
)
from app.domain.storage_adapters import storage_readiness


class DocumentUploadTests(unittest.TestCase):
    def test_invoice_upload_requires_explicit_purchase_or_sales_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "invoice intake_category is required"):
                store_document_content(
                    base_dir=Path(temp_dir),
                    client_id="pilot",
                    file_name="invoice.xml",
                    document_type="einvoice_xml",
                    uploaded_by="test",
                    content=b"<Invoice />",
                )

    def test_invoice_upload_rejects_non_invoice_intake_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "invoice intake_category must be purchase_invoice or sales_invoice"):
                store_document_content(
                    base_dir=Path(temp_dir),
                    client_id="pilot",
                    file_name="invoice.xml",
                    document_type="einvoice_xml",
                    intake_category="bank_statement",
                    uploaded_by="test",
                    content=b"<Invoice />",
                )

    def test_non_invoice_document_keeps_its_existing_default_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stored = store_document_content(
                base_dir=Path(temp_dir),
                client_id="pilot",
                file_name="bank.csv",
                document_type="bank_statement",
                uploaded_by="test",
                content=b"date,amount",
            )

        self.assertEqual(stored.intake_category, "bank_statement")

    def test_document_content_is_stored_under_client_and_document_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = store_document_content(
                base_dir=Path(temp_dir),
                client_id="client 1",
                file_name="../Rexton Alis Faturasi.pdf",
                document_type="invoice",
                intake_category="purchase_invoice",
                uploaded_by="mukellef-user",
                content=b"invoice-bytes",
            )

            stored_path = Path(document.storage_path)
            stored_bytes = stored_path.read_bytes()

        self.assertEqual(document.status, "stored")
        self.assertEqual(document.storage_backend, "local")
        self.assertEqual(document.client_id, "client 1")
        self.assertEqual(document.stored_file_name, "Rexton-Alis-Faturasi.pdf")
        self.assertEqual(document.retention_policy_days, 90)
        self.assertEqual(document.storage_status, "stored")
        self.assertTrue(document.download_available_until)
        self.assertTrue(document.expires_at)
        self.assertEqual(document.deleted_at, "")
        self.assertEqual(document.size_bytes, len(b"invoice-bytes"))
        self.assertEqual(stored_bytes, b"invoice-bytes")
        self.assertIn("client-1", document.storage_path)

    def test_local_storage_readiness_reports_writable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            readiness = storage_readiness(base_dir=Path(temp_dir))

        self.assertTrue(readiness["ok"])
        self.assertEqual(readiness["backend"], "local")
        self.assertTrue(readiness["writable"])

    def test_document_without_content_is_queued_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = store_document_content(
                base_dir=Path(temp_dir),
                client_id="client-1",
                file_name="banka.xlsx",
                document_type="bank_statement",
                uploaded_by="mukellef-user",
                declared_size_bytes=123,
                declared_sha256="declared",
            )

        self.assertEqual(document.status, "queued")
        self.assertEqual(document.storage_status, "queued")
        self.assertEqual(document.size_bytes, 123)
        self.assertEqual(document.sha256, "declared")

    def test_period_managed_invoice_has_no_upload_time_retention_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = store_document_content(
                base_dir=Path(temp_dir),
                client_id="client-1",
                file_name="subat-faturasi.xml",
                document_type="einvoice_xml",
                intake_category="purchase_invoice",
                period="2026-02",
                uploaded_by="mukellef-user",
                content=b"invoice-bytes",
                period_retention_managed=True,
            )

        self.assertEqual(document.period, "2026-02")
        self.assertEqual(document.storage_status, "stored")
        self.assertEqual(document.download_available_until, "")
        self.assertEqual(document.expires_at, "")

    def test_special_document_keeps_intake_category_for_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = store_document_content(
                base_dir=Path(temp_dir),
                client_id="client-1",
                file_name="sozlesme.pdf",
                document_type="special_document",
                intake_category="special_document",
                uploaded_by="mukellef-user",
                content=b"manual-review",
            )

        self.assertEqual(document.document_type, "special_document")
        self.assertEqual(document.intake_category, "special_document")
        self.assertEqual(document.status, "stored")

    def test_invalid_document_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                store_document_content(
                    base_dir=Path(temp_dir),
                    client_id="client-1",
                    file_name="fatura.pdf",
                    document_type="unknown",
                    uploaded_by="user",
                )

    def test_base64_decode_validates_payload(self) -> None:
        self.assertEqual(decode_base64_content("ZmF0dXJh"), b"fatura")
        with self.assertRaises(ValueError):
            decode_base64_content("not valid base64")

    def test_file_name_sanitizer_removes_path_segments(self) -> None:
        self.assertEqual(sanitize_file_name("..\\secret\\fatura 01.pdf"), "fatura-01.pdf")

    def test_retention_status_marks_expiring_and_expired_documents(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        expires_at = now + timedelta(days=10)
        self.assertEqual(document_storage_status(expires_at=expires_at, now=now), "expiring")
        self.assertEqual(document_storage_status(expires_at=now - timedelta(seconds=1), now=now), "expired")

    def test_retention_decision_keeps_metadata_and_marks_expired_for_deletion(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        decision = retention_decision(
            {
                "document_id": "doc-1",
                "expires_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
                "storage_status": "stored",
            },
            now=now,
        )

        self.assertEqual(decision.document_id, "doc-1")
        self.assertEqual(decision.storage_status, "expired")
        self.assertTrue(decision.should_delete)

    def test_extend_retention_deadline_adds_90_days_from_current_expiry(self) -> None:
        self.assertEqual(
            extend_retention_deadline("2026-01-01T00:00:00+00:00", days=90),
            "2026-04-01T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
