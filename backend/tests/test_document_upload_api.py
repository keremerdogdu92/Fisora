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

    def test_special_document_upload_goes_to_manual_review_queue(self) -> None:
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
                    "document_type": "special_document",
                    "intake_category": "special_document",
                    "file_name": "sozlesme.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "bWFudWFs",
                },
            )
            payload = response.json()
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["document_type"], "special_document")
        self.assertEqual(payload["intake_category"], "special_document")
        self.assertEqual(payload["processing_job"]["parser_kind"], "manual_review")
        self.assertEqual(workspace["uploaded_documents"][0]["intake_category"], "special_document")

    def test_client_onboarding_package_creates_upload_ready_workspace(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)

            package = client.post(
                "/phase0/store/client-onboarding-package",
                json={
                    "client": {
                        "client_id": "client-1",
                        "title": "Demo Mukellef",
                        "tax_id": "1111111111",
                        "activity_description": "isitme cihazi satis",
                        "workplace_addresses": ["Istanbul"],
                        "has_chart_accounts": True,
                    },
                    "chart_accounts": [
                        {
                            "raw_account_code": "320.01.015",
                            "normalized_account_code": "320.01.015",
                            "account_name": "Rexton Medikal",
                            "is_detail_account": True,
                            "tax_id": "1234567890",
                        }
                    ],
                    "portal_users": [
                        {
                            "user_id": "mukellef-user",
                            "display_name": "Mukellef Kullanici",
                            "role": "client_user",
                            "allowed_client_ids": ["client-1"],
                        }
                    ],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            )
            clients = client.get("/phase0/store/clients")

        self.assertEqual(package.status_code, 200)
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(clients.json()["clients"][0]["client_id"], "client-1")
        self.assertEqual(package.json()["workspace"]["portal_users"][0]["user_id"], "mukellef-user")

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

    def test_mock_auth_filters_clients_and_blocks_unassigned_workspace(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)
            for client_id in ("client-1", "client-2"):
                client.post(
                    "/phase0/store/client",
                    json={"client_id": client_id, "title": f"Demo {client_id}", "has_chart_accounts": True},
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
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1", "client-2"],
                },
            )

            client_user_clients = client.get(
                "/phase0/store/clients",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )
            accountant_clients = client.get(
                "/phase0/store/clients",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            denied_workspace = client.get(
                "/phase0/store/workspace/client-2",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )

        self.assertEqual(client_user_clients.status_code, 200)
        self.assertEqual([item["client_id"] for item in client_user_clients.json()["clients"]], ["client-1"])
        self.assertEqual(accountant_clients.status_code, 200)
        self.assertEqual(len(accountant_clients.json()["clients"]), 2)
        self.assertEqual(denied_workspace.status_code, 403)

    def test_mock_auth_blocks_client_user_export_package(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_EXPORT_PATH = Path(temp_dir) / "exports"
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
                "/phase0/store/export-package/from-workspace",
                headers={"X-Fisora-User-Id": "mukellef-user"},
                json={"client_id": "client-1", "export_type": "zirve_universal_csv"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["reason"], "role_not_allowed")

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
            manifest = client.get(payload["package"]["manifest_download_url"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["package"]["entry_count"], 1)
        self.assertTrue(payload["package"]["manifest_filename"].endswith(".manifest.json"))
        self.assertEqual(download.status_code, 200)
        self.assertIn("770.01", download.text)
        self.assertEqual(manifest.status_code, 200)
        self.assertIn("ready.pdf", manifest.text)

    def test_statement_ai_suggestions_endpoint_returns_review_only_structured_payload(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)

            response = client.post(
                "/phase0/statement/ai-suggestions",
                json={
                    "client_id": "client-1",
                    "ai_policy": {"enabled": True, "confidence_threshold": 70, "max_provider_calls": 2},
                    "provider_name": "replay_provider",
                    "provider_payloads": [
                        {
                            "transaction_type": "counterparty_payment",
                            "suggested_account_code": "320.01.123",
                            "confidence": 82,
                            "reason": "Satir tedarikci odemesi gibi gorunuyor.",
                            "evidence": ["tedarikci", "odeme"],
                        }
                    ],
                    "lines": [
                        {
                            "line_no": 1,
                            "transaction_date": "2026-06-01",
                            "description": "GIB ODEME",
                            "amount": "100.00",
                            "direction": "out",
                            "suggested_account_code": "360",
                            "transaction_type": "tax_payment",
                            "confidence": 86,
                            "risk_flags": [],
                        },
                        {
                            "line_no": 2,
                            "transaction_date": "2026-06-02",
                            "description": "BILINMEYEN TEDARIKCI ODEME",
                            "amount": "250.00",
                            "direction": "out",
                            "transaction_type": "unknown",
                            "confidence": 35,
                            "risk_flags": ["statement_review_required", "counterparty_not_found"],
                        },
                    ],
                },
            )
            summary_response = client.post(
                "/phase0/store/ai-usage/summary",
                json={"client_id": "client-1", "monthly_cap_usd": "100.00"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ai_used_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["suggestions"][0]["line_no"], 2)
        self.assertEqual(payload["suggestions"][0]["suggested_account_code"], "320.01.123")
        self.assertFalse(payload["suggestions"][0]["export_allowed"])
        self.assertEqual(summary_response.json()["summary"]["ai_used_count"], 1)


if __name__ == "__main__":
    unittest.main()
