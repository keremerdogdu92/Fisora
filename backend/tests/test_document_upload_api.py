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

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            )
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "stored")
        self.assertEqual(payload["size_bytes"], 6)
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "fatura.pdf")

    def test_store_document_upload_rejects_invalid_base64(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "content_base64": "not valid base64",
                },
            )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
