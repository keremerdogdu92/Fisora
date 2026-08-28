# File: backend/tests/test_production_security_hardening.py
# Summary: Locks production auth-before-write and upload surface protections.
from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient
    from app.api import phase0
    from app.main import app
    from app.persistence.workflow_store import JsonWorkflowStore
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None
    JsonWorkflowStore = None


class ProductionSecurityHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        self.previous_store_path = phase0.DEFAULT_STORE_PATH
        self.previous_storage_path = phase0.DEFAULT_DOCUMENT_STORAGE_PATH

    def tearDown(self) -> None:
        if phase0 is not None:
            phase0.DEFAULT_STORE_PATH = self.previous_store_path
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = self.previous_storage_path

    def test_production_onboarding_rejects_missing_session_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"FISORA_ENV": "production", "FISORA_AUTH_MODE": "session_required"},
            clear=False,
        ):
            store_path = Path(temp_dir) / "store.json"
            phase0.DEFAULT_STORE_PATH = store_path
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            response = TestClient(app).post(
                "/phase0/store/client-onboarding-package",
                json={
                    "client": {
                        "client_id": "blocked-client",
                        "title": "Blocked Client",
                        "tax_id": "1111111111",
                    },
                    "chart_accounts": [],
                    "portal_users": [],
                },
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(JsonWorkflowStore(store_path).list_clients(), [])

    def test_production_admin_mutations_require_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"FISORA_ENV": "production", "FISORA_AUTH_MODE": "session_required"},
            clear=False,
        ):
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            portal_user = client.post(
                "/phase0/store/portal-user",
                json={"user_id": "attacker", "role": "admin", "allowed_client_ids": ["*"]},
            )
            invite = client.post(
                "/phase0/store/auth/invite",
                json={"user_id": "attacker", "role": "admin", "allowed_client_ids": ["*"]},
            )
            retention = client.post("/phase0/store/document-retention/preview", json={})
            processing = client.post("/phase0/store/processing/run", json={"max_jobs": 1})

        self.assertEqual(portal_user.status_code, 401)
        self.assertEqual(invite.status_code, 401)
        self.assertEqual(retention.status_code, 401)
        self.assertEqual(processing.status_code, 401)

    def test_invoice_html_upload_is_accepted_but_preview_removes_active_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"FISORA_ENV": "test", "FISORA_AUTH_MODE": "mock_header_optional"},
            clear=False,
        ):
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            created = client.post(
                "/phase0/store/client-onboarding-package",
                json={
                    "client": {"client_id": "client-1", "title": "Client One", "tax_id": "1111111111"},
                    "portal_users": [
                        {"user_id": "client-user", "role": "client_user", "allowed_client_ids": ["client-1"]}
                    ],
                },
            )
            self.assertEqual(created.status_code, 200)
            response = client.post(
                "/phase0/store/document-upload",
                headers={"X-Fisora-User-Id": "client-user"},
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "intake_category": "purchase_invoice",
                    "period": "2026-08",
                    "file_name": "invoice.html",
                    "uploaded_by_user_id": "client-user",
                    "content_base64": base64.b64encode(
                        b"<html><body><h1>Invoice</h1><script>alert(1)</script></body></html>"
                    ).decode("ascii"),
                },
            )
            self.assertEqual(response.status_code, 200)
            document_ref = str(response.json().get("document_ref") or "")
            self.assertTrue(document_ref)

            preview = client.get(
                f"/phase0/store/document-file/client-1/{document_ref}",
                headers={"X-Fisora-User-Id": "client-user"},
            )
            self.assertEqual(preview.status_code, 200)
            self.assertIn("Invoice", preview.text)
            self.assertNotIn("<script", preview.text.lower())
            self.assertNotIn("alert(1)", preview.text)
            self.assertIn("script-src 'none'", preview.headers.get("content-security-policy", ""))
            self.assertEqual(preview.headers.get("x-content-type-options"), "nosniff")

    def test_invoice_upload_still_rejects_unapproved_file_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"FISORA_ENV": "test", "FISORA_AUTH_MODE": "mock_header_optional"},
            clear=False,
        ):
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            created = client.post(
                "/phase0/store/client-onboarding-package",
                json={
                    "client": {"client_id": "client-1", "title": "Client One", "tax_id": "1111111111"},
                    "portal_users": [
                        {"user_id": "client-user", "role": "client_user", "allowed_client_ids": ["client-1"]}
                    ],
                },
            )
            self.assertEqual(created.status_code, 200)
            response = client.post(
                "/phase0/store/document-upload",
                headers={"X-Fisora-User-Id": "client-user"},
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "intake_category": "purchase_invoice",
                    "period": "2026-08",
                    "file_name": "invoice.svg",
                    "uploaded_by_user_id": "client-user",
                    "content_base64": base64.b64encode(b"<svg></svg>").decode("ascii"),
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("requires a PDF or HTML", str(response.json()))


if __name__ == "__main__":
    unittest.main()
