from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.auth_policy import auth_status_payload, build_auth_config

try:
    from fastapi.testclient import TestClient

    from app.api import phase0
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None


class AuthPolicyTests(unittest.TestCase):
    def test_trusted_header_mode_is_production_ready_and_requires_user(self) -> None:
        config = build_auth_config({"FISORA_AUTH_MODE": "trusted_header"})
        status = auth_status_payload(config)

        self.assertTrue(config.requires_portal_user)
        self.assertTrue(config.production_ready)
        self.assertEqual(status["auth_mode"], "trusted_header")
        self.assertTrue(status["requires_portal_user"])

    def test_session_required_mode_uses_app_session_not_mock_header(self) -> None:
        config = build_auth_config({"FISORA_AUTH_MODE": "session_required"})
        status = auth_status_payload(config)

        self.assertTrue(config.requires_portal_user)
        self.assertTrue(config.production_ready)
        self.assertEqual(status["auth_mode"], "session_required")
        self.assertFalse(status["allows_anonymous_access"])
        self.assertEqual(status["credential_transport"], "secure_cookie")

    def test_session_required_cookie_login_allows_workspace_and_logout_clears_cookie(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_bootstrap = os.environ.get("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED")
        previous_cookie_secure = os.environ.get("FISORA_SESSION_COOKIE_SECURE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "session_required"
        os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = "true"
        os.environ["FISORA_SESSION_COOKIE_SECURE"] = "false"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/client",
                    json={"client_id": "client-1", "title": "Mukellef A", "has_chart_accounts": True},
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
                    "/phase0/store/auth/password",
                    json={"user_id": "mukellef-user", "password": "GizliSifre123"},
                )
                header_only = client.get(
                    "/phase0/store/workspace/client-1",
                    headers={"X-Fisora-User-Id": "mukellef-user"},
                )
                login_response = client.post(
                    "/phase0/store/auth/login",
                    json={"user_id": "mukellef-user", "password": "GizliSifre123"},
                )
                workspace = client.get("/phase0/store/workspace/client-1")
                logout = client.post("/phase0/store/auth/logout", json={})
                revoked_session = client.get("/phase0/store/auth/session")
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            if previous_bootstrap is None:
                os.environ.pop("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED", None)
            else:
                os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = previous_bootstrap
            if previous_cookie_secure is None:
                os.environ.pop("FISORA_SESSION_COOKIE_SECURE", None)
            else:
                os.environ["FISORA_SESSION_COOKIE_SECURE"] = previous_cookie_secure
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(header_only.status_code, 401)
        self.assertEqual(header_only.json()["detail"]["reason"], "session_required")
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("fisora_session=", login_response.headers.get("set-cookie", ""))
        self.assertIn("HttpOnly", login_response.headers.get("set-cookie", ""))
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()["client"]["client_id"], "client-1")
        self.assertEqual(logout.status_code, 200)
        self.assertTrue(logout.json()["revoked"])
        self.assertIn("fisora_session=", logout.headers.get("set-cookie", ""))
        self.assertEqual(revoked_session.status_code, 401)
        self.assertEqual(revoked_session.json()["detail"]["reason"], "session_required")

    def test_api_blocks_anonymous_workspace_access_when_auth_requires_user(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_bootstrap = os.environ.get("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "trusted_header"
        os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = "true"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/client",
                    json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                )

                response = client.get("/phase0/store/workspace/client-1")
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            if previous_bootstrap is None:
                os.environ.pop("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED", None)
            else:
                os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = previous_bootstrap
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["reason"], "portal_user_required")

    def test_password_login_session_allows_workspace_access_and_logout_revokes(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_bootstrap = os.environ.get("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "trusted_header"
        os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = "true"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
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
                password_response = client.post(
                    "/phase0/store/auth/password",
                    json={"user_id": "mukellef-user", "password": "GizliSifre123"},
                )
                login_response = client.post(
                    "/phase0/store/auth/login",
                    json={"user_id": "mukellef-user", "password": "GizliSifre123"},
                )
                session_token = login_response.json()["session_token"]
                workspace = client.get(
                    "/phase0/store/workspace/client-1",
                    headers={"X-Fisora-Session": session_token},
                )
                logout = client.post(
                    "/phase0/store/auth/logout",
                    headers={"X-Fisora-Session": session_token},
                    json={},
                )
                revoked_session = client.get(
                    "/phase0/store/auth/session",
                    headers={"X-Fisora-Session": session_token},
                )
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            if previous_bootstrap is None:
                os.environ.pop("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED", None)
            else:
                os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = previous_bootstrap
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(password_response.status_code, 200)
        self.assertTrue(password_response.json()["has_password"])
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()["client"]["client_id"], "client-1")
        self.assertEqual(logout.status_code, 200)
        self.assertTrue(logout.json()["revoked"])
        self.assertEqual(revoked_session.status_code, 401)
        self.assertEqual(revoked_session.json()["detail"]["reason"], "session_revoked")

    def test_system_readiness_reports_storage_and_auth(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_document_path = phase0.DEFAULT_DOCUMENT_STORAGE_PATH
        previous_export_path = phase0.DEFAULT_EXPORT_PATH
        previous_backup_path = phase0.DEFAULT_BACKUP_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                base = Path(temp_dir)
                phase0.DEFAULT_DOCUMENT_STORAGE_PATH = base / "documents"
                phase0.DEFAULT_EXPORT_PATH = base / "exports"
                phase0.DEFAULT_BACKUP_PATH = base / "backups"
                phase0.DEFAULT_BACKUP_PATH.mkdir()
                (phase0.DEFAULT_BACKUP_PATH / "postgres-20260603T100000Z.sql").write_text("backup", encoding="utf-8")
                client = TestClient(app)

                response = client.get("/phase0/store/system/readiness")
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = previous_document_path
            phase0.DEFAULT_EXPORT_PATH = previous_export_path
            phase0.DEFAULT_BACKUP_PATH = previous_backup_path

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["auth"]["auth_mode"], "mock_header_required")
        self.assertTrue(payload["document_storage"]["ok"])
        self.assertTrue(payload["backup"]["ok"])
        self.assertEqual(payload["backup"]["database_backup_count"], 1)
        self.assertIn("disk_used_percent", payload["storage_usage"])
        self.assertIn("zirve_verified_adapter_missing", payload["warnings"])

    def test_operation_log_and_health_endpoint_summarize_jobs(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/client-onboarding-package",
                    json={
                        "client": {"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                        "portal_users": [
                            {
                                "user_id": "mali-musavir",
                                "display_name": "Mali Musavir",
                                "role": "accountant",
                                "allowed_client_ids": ["client-1"],
                            }
                        ],
                    },
                )
                event = client.post(
                    "/phase0/store/operation-log",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={
                        "client_id": "client-1",
                        "event_type": "processing_run",
                        "status": "ok",
                        "message": "Worker calisti.",
                        "metadata": {"completed_count": 1},
                    },
                )
                health = client.get(
                    "/phase0/store/operation-health/client-1",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                )
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(event.status_code, 200)
        self.assertEqual(event.json()["event_type"], "processing_run")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["summary"]["health_status"], "ok")
        self.assertEqual(health.json()["summary"]["event_count"], 1)

    def test_invite_accept_and_password_reset_flow(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)

                invite = client.post(
                    "/phase0/store/auth/invite",
                    json={
                        "user_id": "new-user",
                        "display_name": "New User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )
                accept = client.post(
                    "/phase0/store/auth/invite/accept",
                    json={"invite_token": invite.json()["invite_token"], "password": "GizliSifre123"},
                )
                reset = client.post(
                    "/phase0/store/auth/password-reset",
                    json={"user_id": "new-user"},
                )
                confirm = client.post(
                    "/phase0/store/auth/password-reset/confirm",
                    json={"reset_token": reset.json()["reset_token"], "password": "YeniSifre123"},
                )
                login_old = client.post(
                    "/phase0/store/auth/login",
                    json={"user_id": "new-user", "password": "GizliSifre123"},
                )
                login_new = client.post(
                    "/phase0/store/auth/login",
                    json={"user_id": "new-user", "password": "YeniSifre123"},
                )
        finally:
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(invite.status_code, 200)
        self.assertEqual(accept.status_code, 200)
        self.assertEqual(accept.json()["token"]["reason"], "token_used")
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(login_old.status_code, 401)
        self.assertEqual(login_new.status_code, 200)

    def test_product_classification_records_ai_usage_when_client_id_is_supplied(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)

                classification = client.post(
                    "/phase0/classification/product",
                    json={
                        "client_id": "client-1",
                        "raw_line": "Urban Care sac bakim seti",
                        "supplier_hint": "Market",
                    },
                )
                summary = client.post(
                    "/phase0/store/ai-usage/summary",
                    json={"client_id": "client-1", "monthly_cap_usd": "100.00"},
                )
        finally:
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(classification.status_code, 200)
        self.assertIsNotNone(classification.json()["usage_event"])
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["summary"]["event_count"], 1)
        self.assertEqual(summary.json()["summary"]["ai_skipped_count"], 1)


if __name__ == "__main__":
    unittest.main()
