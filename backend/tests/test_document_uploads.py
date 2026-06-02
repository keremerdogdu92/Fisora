from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_uploads import decode_base64_content, sanitize_file_name, store_document_content


class DocumentUploadTests(unittest.TestCase):
    def test_document_content_is_stored_under_client_and_document_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = store_document_content(
                base_dir=Path(temp_dir),
                client_id="client 1",
                file_name="../Rexton Alis Faturasi.pdf",
                document_type="invoice",
                uploaded_by="mukellef-user",
                content=b"invoice-bytes",
            )

            stored_path = Path(document.storage_path)
            stored_bytes = stored_path.read_bytes()

        self.assertEqual(document.status, "stored")
        self.assertEqual(document.client_id, "client 1")
        self.assertEqual(document.stored_file_name, "Rexton-Alis-Faturasi.pdf")
        self.assertEqual(document.size_bytes, len(b"invoice-bytes"))
        self.assertEqual(stored_bytes, b"invoice-bytes")
        self.assertIn("client-1", document.storage_path)

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
        self.assertEqual(document.size_bytes, 123)
        self.assertEqual(document.sha256, "declared")

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


if __name__ == "__main__":
    unittest.main()
