from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

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


class DocumentUploadApiTests(unittest.TestCase):
    def test_store_document_upload_writes_content_and_workspace_metadata(self) -> None:
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
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by": "mukellef-user",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            )
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "stored")
        self.assertEqual(payload["size_bytes"], 6)
        self.assertEqual(payload["processing_job"]["status"], "queued")
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "fatura.pdf")

    def test_store_document_upload_rejects_invalid_base64(self) -> None:
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
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "not valid base64",
                },
            )

        self.assertEqual(response.status_code, 400)

    def test_store_document_upload_multipart_writes_content(self) -> None:
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
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload-multipart",
                data={
                    "client_id": "client-1",
                    "document_type": "bank_statement",
                    "uploaded_by": "mukellef-user",
                    "uploaded_by_user_id": "mukellef-user",
                },
                files={"file": ("bank.csv", b"transaction_date,description,amount\n2026-06-01,GIB,10.00\n", "text/csv")},
            )
            payload = response.json()
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "stored")
        self.assertEqual(payload["processing_job"]["parser_kind"], "bank_statement")
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "bank.csv")

    def test_store_document_upload_rejects_unassigned_portal_user(self) -> None:
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
                    "user_id": "other-user",
                    "display_name": "Baska Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-2"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "other-user",
                    "content_base64": "ZmF0dXJh",
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_store_export_package_from_workspace_writes_downloadable_csv(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_EXPORT_PATH = Path(temp_dir) / "exports"
            client = TestClient(app)
            store = phase0.get_workflow_store()
            store.save_simulation_result(
                client_id="client-1",
                document_ref="ready.pdf",
                result={
                    "file_name": "ready.pdf",
                    "export_status": "export_ready",
                    "review_reason_codes": [],
                    "risk_flags": [],
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )

            response = client.post(
                "/phase0/store/export-package/from-workspace",
                json={"client_id": "client-1", "export_type": "zirve_universal_csv"},
            )
            payload = response.json()
            download = client.get(payload["package"]["download_url"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["package"]["entry_count"], 1)
        self.assertEqual(download.status_code, 200)
        self.assertIn("770.01", download.text)


if __name__ == "__main__":
    unittest.main()
