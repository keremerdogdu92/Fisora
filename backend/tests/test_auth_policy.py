from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.auth_policy import auth_status_payload, build_auth_config

try:
    from fastapi.testclient import TestClient

    from app.api import phase0, phase0_routes_operations
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    phase0_routes_operations = None
    app = None


class AuthPolicyTests(unittest.TestCase):
    def test_email_delivery_disabled_returns_link_only(self) -> None:
        from app.domain.email_delivery import send_auth_email

        result = send_auth_email(
            recipient="client@example.com",
            subject="Fisora davet",
            body_text="Link: https://portal.test/invite?token=abc",
            action_url="https://portal.test/invite?token=abc",
            env={"FISORA_EMAIL_PROVIDER": "disabled"},
        )

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["action_url"], "https://portal.test/invite?token=abc")

    def test_email_delivery_dry_run_records_provider_without_network(self) -> None:
        from app.domain.email_delivery import send_auth_email

        result = send_auth_email(
            recipient="client@example.com",
            subject="Fisora sifre sifirlama",
            body_text="Link: https://portal.test/reset?token=abc",
            action_url="https://portal.test/reset?token=abc",
            env={"FISORA_EMAIL_PROVIDER": "dry_run"},
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["provider"], "dry_run")

    def test_invite_route_returns_email_delivery_status(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        previous_base_url = os.environ.get("FISORA_PORTAL_BASE_URL")
        os.environ["FISORA_PORTAL_BASE_URL"] = "https://portal.test"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                with patch("app.api.phase0_routes_auth.send_auth_email") as sender:
                    sender.return_value = {
                        "status": "dry_run",
                        "provider": "dry_run",
                        "action_url": "https://portal.test/portal/invite?token=abc",
                    }
                    response = client.post(
                        "/phase0/store/auth/invite",
                        json={
                            "user_id": "client-user",
                            "display_name": "Client User",
                            "role": "client_user",
                            "allowed_client_ids": ["client-1"],
                            "invited_by": "mali-musavir",
                            "email": "client@example.com",
                        },
                    )
        finally:
            phase0.DEFAULT_STORE_PATH = previous_store_path
            if previous_base_url is None:
                os.environ.pop("FISORA_PORTAL_BASE_URL", None)
            else:
                os.environ["FISORA_PORTAL_BASE_URL"] = previous_base_url

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email_delivery"]["status"], "dry_run")

    def test_password_reset_route_returns_email_delivery_status(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        previous_base_url = os.environ.get("FISORA_PORTAL_BASE_URL")
        os.environ["FISORA_PORTAL_BASE_URL"] = "https://portal.test"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                with patch("app.api.phase0_routes_auth.send_auth_email") as sender:
                    sender.return_value = {
                        "status": "dry_run",
                        "provider": "dry_run",
                        "action_url": "https://portal.test/portal/password-reset?token=abc",
                    }
                    response = client.post(
                        "/phase0/store/auth/password-reset",
                        json={"user_id": "client-user", "email": "client@example.com"},
                    )
        finally:
            phase0.DEFAULT_STORE_PATH = previous_store_path
            if previous_base_url is None:
                os.environ.pop("FISORA_PORTAL_BASE_URL", None)
            else:
                os.environ["FISORA_PORTAL_BASE_URL"] = previous_base_url

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email_delivery"]["status"], "dry_run")

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

    def test_accountant_can_create_delegated_client_session_without_cookie(self) -> None:
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
                    "/phase0/store/client",
                    json={"client_id": "client-1", "title": "Client One", "has_chart_accounts": True},
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
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "client-user",
                        "display_name": "Client User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )

                response = client.post(
                    "/phase0/store/auth/delegated-client-session",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"client_id": "client-1", "target_user_id": "client-user", "ttl_hours": 12},
                )
                payload = response.json()
                session_token = payload.get("session_token", "")
                session = client.get(
                    "/phase0/store/auth/session",
                    headers={"X-Fisora-Session": session_token},
                )
                workspace = client.get(
                    "/phase0/store/workspace/client-1",
                    headers={"X-Fisora-Session": session_token},
                )
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("fisora_session=", response.headers.get("set-cookie", ""))
        self.assertEqual(payload["delegated_by"], "mali-musavir")
        self.assertEqual(payload["delegated_client_id"], "client-1")
        self.assertEqual(payload["session"]["user_id"], "client-user")
        self.assertEqual(payload["session"]["delegated_by"], "mali-musavir")
        self.assertEqual(payload["session"]["delegated_client_id"], "client-1")
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["delegated_by"], "mali-musavir")
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()["client"]["client_id"], "client-1")

    def test_delegated_client_session_requires_accountant_role_and_client_access(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                for client_id in ("client-1", "client-2"):
                    client.post(
                        "/phase0/store/client",
                        json={"client_id": client_id, "title": client_id, "has_chart_accounts": True},
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
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "client-user",
                        "display_name": "Client User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )

                client_actor = client.post(
                    "/phase0/store/auth/delegated-client-session",
                    headers={"X-Fisora-User-Id": "client-user"},
                    json={"client_id": "client-1", "target_user_id": "client-user"},
                )
                unassigned_client = client.post(
                    "/phase0/store/auth/delegated-client-session",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"client_id": "client-2", "target_user_id": "client-user"},
                )
        finally:
            if previous is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(client_actor.status_code, 403)
        self.assertEqual(client_actor.json()["detail"]["reason"], "role_not_allowed")
        self.assertEqual(unassigned_client.status_code, 403)
        self.assertEqual(unassigned_client.json()["detail"]["reason"], "client_not_assigned_to_user")

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

    def test_ai_capacity_endpoint_requires_accountant_and_hides_secrets(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        previous_env = {
            key: os.environ.get(key)
            for key in (
                "FISORA_AI_PROVIDER_CHAIN",
                "GROQ_API_KEY",
                "OPENROUTER_API_KEY",
                "CEREBRAS_API_KEY",
                "FISORA_RESEARCH_ENABLED",
                "OPENAI_API_KEY",
                "FISORA_RESEARCH_MODEL",
                "FISORA_RESEARCH_MAX_PER_DOCUMENT",
            )
        }
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        os.environ["FISORA_AI_PROVIDER_CHAIN"] = "groq,openrouter,cerebras"
        os.environ["GROQ_API_KEY"] = "gsk-secret"
        os.environ["OPENROUTER_API_KEY"] = "or-secret"
        os.environ["CEREBRAS_API_KEY"] = "csk-secret"
        os.environ["FISORA_RESEARCH_ENABLED"] = "true"
        os.environ["OPENAI_API_KEY"] = "sk-secret"
        os.environ["FISORA_RESEARCH_MODEL"] = "gpt-5.4-mini"
        os.environ["FISORA_RESEARCH_MAX_PER_DOCUMENT"] = "1"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "mali-musavir",
                        "display_name": "Mali Musavir",
                        "role": "accountant",
                        "allowed_client_ids": ["*"],
                    },
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "client-user",
                        "display_name": "Client User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )

                anonymous = client.get("/phase0/store/ai-capacity")
                forbidden = client.get("/phase0/store/ai-capacity", headers={"X-Fisora-User-Id": "client-user"})
                response = client.get("/phase0/store/ai-capacity", headers={"X-Fisora-User-Id": "mali-musavir"})
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["agents"][0]["label"], "Belge ajanı 1")
        self.assertEqual(payload["agents"][-1]["label"], "Araştırma ajanı")
        self.assertTrue(payload["agents"][-1]["configured"])
        public_text = str(payload).lower()
        self.assertNotIn("gsk-secret", public_text)
        self.assertNotIn("or-secret", public_text)
        self.assertNotIn("csk-secret", public_text)
        self.assertNotIn("sk-secret", public_text)
        self.assertNotIn("free", public_text)
        self.assertNotIn("ücretsiz", public_text)

    def test_ai_capacity_endpoint_refreshes_and_caches_tavily_usage(self) -> None:
        if TestClient is None or phase0 is None or phase0_routes_operations is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        previous_env = {
            key: os.environ.get(key)
            for key in (
                "FISORA_RESEARCH_ENABLED",
                "FISORA_RESEARCH_PROVIDER",
                "TAVILY_API_KEY",
            )
        }
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        os.environ["FISORA_RESEARCH_ENABLED"] = "true"
        os.environ["FISORA_RESEARCH_PROVIDER"] = "tavily"
        os.environ["TAVILY_API_KEY"] = "tvly-secret"
        usage_response = Mock()
        usage_response.json.return_value = {
            "key": {"usage": 150, "limit": 1000},
            "account": {"plan_usage": 500, "plan_limit": 15000},
        }
        usage_response.raise_for_status.return_value = None
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "mali-musavir",
                        "display_name": "Mali Musavir",
                        "role": "accountant",
                        "allowed_client_ids": ["*"],
                    },
                )
                with patch.object(phase0_routes_operations.httpx, "get", return_value=usage_response) as http_get:
                    first = client.get(
                        "/phase0/store/ai-capacity",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                    )
                    second = client.get(
                        "/phase0/store/ai-capacity",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                    )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["totals"]["internet_researches"], 318)
        self.assertEqual(first.json()["estimate"]["confidence"], "live")
        http_get.assert_called_once_with(
            "https://api.tavily.com/usage",
            headers={"Authorization": "Bearer tvly-secret"},
            timeout=2.0,
        )
        self.assertNotIn("tvly-secret", str(first.json()))

    def test_ai_capacity_endpoint_uses_cached_tavily_usage_when_refresh_fails(self) -> None:
        if TestClient is None or phase0 is None or phase0_routes_operations is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        previous_env = {
            key: os.environ.get(key)
            for key in (
                "FISORA_RESEARCH_ENABLED",
                "FISORA_RESEARCH_PROVIDER",
                "TAVILY_API_KEY",
            )
        }
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        os.environ["FISORA_RESEARCH_ENABLED"] = "true"
        os.environ["FISORA_RESEARCH_PROVIDER"] = "tavily"
        os.environ["TAVILY_API_KEY"] = "tvly-secret"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "mali-musavir",
                        "display_name": "Mali Musavir",
                        "role": "accountant",
                        "allowed_client_ids": ["*"],
                    },
                )
                phase0_routes_operations.get_workflow_store().record_ai_capacity_snapshot(
                    provider="tavily",
                    snapshot={
                        "source": "usage_endpoint",
                        "credit": {"limit": 1000, "used": 150, "remaining": 850, "reset": ""},
                        "last_checked_at": "2026-06-24T00:00:00+00:00",
                    },
                )
                with patch.object(
                    phase0_routes_operations.httpx,
                    "get",
                    side_effect=httpx.ConnectError("usage unavailable"),
                ):
                    response = client.get(
                        "/phase0/store/ai-capacity",
                        headers={"X-Fisora-User-Id": "mali-musavir"},
                    )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["totals"]["internet_researches"], 318)
        self.assertEqual(response.json()["estimate"]["confidence"], "cached")

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

    def test_accountant_can_replace_client_portal_login_and_password(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_bootstrap = os.environ.get("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = "true"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/client",
                    json={"client_id": "client-1", "title": "Client One", "has_chart_accounts": True},
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "mali-musavir",
                        "display_name": "Mali Musavir",
                        "role": "accountant",
                        "allowed_client_ids": ["*"],
                    },
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "old-user",
                        "display_name": "Old User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )
                client.post(
                    "/phase0/store/auth/password",
                    json={"user_id": "old-user", "password": "EskiSifre123"},
                )

                update = client.post(
                    "/phase0/store/client-portal-access",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={
                        "client_id": "client-1",
                        "old_user_id": "old-user",
                        "new_user_id": "new-user",
                        "display_name": "New User",
                        "password": "YeniSifre123",
                    },
                )
                old_login = client.post(
                    "/phase0/store/auth/login",
                    json={"user_id": "old-user", "password": "EskiSifre123"},
                )
                new_login = client.post(
                    "/phase0/store/auth/login",
                    json={"user_id": "new-user", "password": "YeniSifre123"},
                )
                workspace = client.get(
                    "/phase0/store/workspace/client-1",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            if previous_bootstrap is None:
                os.environ.pop("FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED", None)
            else:
                os.environ["FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED"] = previous_bootstrap
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["portal_user"]["user_id"], "new-user")
        self.assertTrue(update.json()["old_user_removed"])
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)
        self.assertEqual([user["user_id"] for user in workspace.json()["portal_users"] if user["role"] == "client_user"], ["new-user"])

    def test_accountant_can_delete_selected_client_documents_after_confirmation(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        from app.persistence.workflow_store import JsonWorkflowStore

        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                base = Path(temp_dir)
                phase0.DEFAULT_STORE_PATH = base / "store.json"
                stored_file = base / "documents" / "client-1" / "invoice.pdf"
                stored_file.parent.mkdir(parents=True)
                stored_file.write_bytes(b"pdf")
                client = TestClient(app)
                client.post(
                    "/phase0/store/client",
                    json={"client_id": "client-1", "title": "Client One", "has_chart_accounts": True},
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "mali-musavir",
                        "display_name": "Mali Musavir",
                        "role": "accountant",
                        "allowed_client_ids": ["*"],
                    },
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "client-user",
                        "display_name": "Client User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )
                store = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
                store.save_uploaded_document(
                    client_id="client-1",
                    document={
                        "document_id": "doc-1",
                        "document_type": "invoice",
                        "original_file_name": "invoice.pdf",
                        "storage_path": str(stored_file),
                        "status": "stored",
                    },
                )
                store.save_simulation_result(
                    client_id="client-1",
                    document_ref="doc-1",
                    result={"file_name": "invoice.pdf", "export_status": "review_required"},
                )

                missing_confirmation = client.post(
                    "/phase0/store/documents/delete",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"client_id": "client-1", "document_refs": ["doc-1"], "confirmed": False},
                )
                forbidden = client.post(
                    "/phase0/store/documents/delete",
                    headers={"X-Fisora-User-Id": "client-user"},
                    json={"client_id": "client-1", "document_refs": ["doc-1"], "confirmed": True},
                )
                deleted = client.post(
                    "/phase0/store/documents/delete",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"client_id": "client-1", "document_refs": ["doc-1"], "confirmed": True},
                )
                workspace = client.get(
                    "/phase0/store/workspace/client-1",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                )
                stored_file_exists_after_delete = stored_file.exists()
                workspace_payload = workspace.json()
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(missing_confirmation.status_code, 400)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted_document_refs"], ["doc-1"])
        self.assertFalse(stored_file_exists_after_delete)
        self.assertEqual(workspace_payload["uploaded_documents"], [])
        self.assertEqual(workspace_payload["documents"], [])

    def test_admin_test_reset_preserves_accountant_password_and_removes_client_data(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        from app.persistence.workflow_store import JsonWorkflowStore

        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        previous_document_storage_path = phase0.DEFAULT_DOCUMENT_STORAGE_PATH
        previous_export_path = phase0.DEFAULT_EXPORT_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                base = Path(temp_dir)
                phase0.DEFAULT_STORE_PATH = base / "store.json"
                phase0.DEFAULT_DOCUMENT_STORAGE_PATH = base / "documents"
                phase0.DEFAULT_EXPORT_PATH = base / "exports"
                stored_file = phase0.DEFAULT_DOCUMENT_STORAGE_PATH / "client-1" / "stored.pdf"
                export_file = phase0.DEFAULT_EXPORT_PATH / "client-1.csv"
                stored_file.parent.mkdir(parents=True)
                phase0.DEFAULT_EXPORT_PATH.mkdir()
                stored_file.write_bytes(b"stored")
                export_file.write_text("export", encoding="utf-8")
                client = TestClient(app)
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "mali-musavir",
                        "display_name": "Mali Musavir",
                        "role": "accountant",
                        "allowed_client_ids": ["*"],
                    },
                )
                client.post(
                    "/phase0/store/auth/password",
                    json={"user_id": "mali-musavir", "password": "GizliSifre123"},
                )
                client.post(
                    "/phase0/store/client",
                    json={"client_id": "client-1", "title": "Client One", "has_chart_accounts": True},
                )
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "client-user",
                        "display_name": "Client User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )
                store = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
                store.set_auth_password(user_id="client-user", password_hash="hash-client")
                store.save_uploaded_document(
                    client_id="client-1",
                    document={
                        "document_id": "stored",
                        "original_file_name": "stored.pdf",
                        "storage_path": str(stored_file),
                        "status": "stored",
                    },
                )
                forbidden = client.post(
                    "/phase0/store/admin/test-reset",
                    headers={"X-Fisora-User-Id": "client-user"},
                    json={"confirmation": "TEMIZLE"},
                )
                bad_confirmation = client.post(
                    "/phase0/store/admin/test-reset",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"confirmation": "sil"},
                )
                reset = client.post(
                    "/phase0/store/admin/test-reset",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"confirmation": "TEMIZLE"},
                )
                clients_after = client.get("/phase0/store/clients", headers={"X-Fisora-User-Id": "mali-musavir"})
                store_after = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
                accountant_password_after = store_after.get_auth_password_hash(user_id="mali-musavir")
                client_password_after = store_after.get_auth_password_hash(user_id="client-user")
                stored_file_exists = stored_file.exists()
                export_file_exists = export_file.exists()
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            phase0.DEFAULT_STORE_PATH = previous_store_path
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = previous_document_storage_path
            phase0.DEFAULT_EXPORT_PATH = previous_export_path

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(bad_confirmation.status_code, 400)
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["deleted_client_count"], 1)
        self.assertEqual(reset.json()["preserved_portal_user_count"], 1)
        self.assertEqual(clients_after.status_code, 200)
        self.assertEqual(clients_after.json()["clients"], [])
        self.assertTrue(accountant_password_after)
        self.assertEqual(client_password_after, "")
        self.assertFalse(stored_file_exists)
        self.assertFalse(export_file_exists)

    def test_pilot_reinitialization_preview_requires_authenticated_accountant(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_auth_mode = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "mock_header_required"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                client.post(
                    "/phase0/store/portal-user",
                    json={
                        "user_id": "client-user",
                        "display_name": "Client User",
                        "role": "client_user",
                        "allowed_client_ids": ["client-1"],
                    },
                )
                missing_user = client.get("/phase0/store/admin/pilot-reinitialization/preview")
                forbidden = client.get(
                    "/phase0/store/admin/pilot-reinitialization/preview",
                    headers={"X-Fisora-User-Id": "client-user"},
                )
        finally:
            if previous_auth_mode is None:
                os.environ.pop("FISORA_AUTH_MODE", None)
            else:
                os.environ["FISORA_AUTH_MODE"] = previous_auth_mode
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(missing_user.status_code, 401)
        self.assertEqual(missing_user.json()["detail"]["reason"], "user_required")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["detail"]["reason"], "accountant_required")

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

    def test_ai_endpoint_rate_limit_returns_429_after_configured_budget(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        from app.api.rate_limit import reset_rate_limit_state

        previous_enabled = os.environ.get("FISORA_RATE_LIMIT_ENABLED")
        previous_ai_limit = os.environ.get("FISORA_RATE_LIMIT_AI_MAX_REQUESTS")
        previous_window = os.environ.get("FISORA_RATE_LIMIT_WINDOW_SECONDS")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_RATE_LIMIT_ENABLED"] = "true"
        os.environ["FISORA_RATE_LIMIT_AI_MAX_REQUESTS"] = "1"
        os.environ["FISORA_RATE_LIMIT_WINDOW_SECONDS"] = "60"
        reset_rate_limit_state()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
                client = TestClient(app)
                payload = {
                    "client_id": "rate-limit-client",
                    "raw_line": "Urban Care sac bakim seti",
                    "supplier_hint": "Market",
                }

                first = client.post("/phase0/classification/product", json=payload)
                second = client.post("/phase0/classification/product", json=payload)
        finally:
            reset_rate_limit_state()
            if previous_enabled is None:
                os.environ.pop("FISORA_RATE_LIMIT_ENABLED", None)
            else:
                os.environ["FISORA_RATE_LIMIT_ENABLED"] = previous_enabled
            if previous_ai_limit is None:
                os.environ.pop("FISORA_RATE_LIMIT_AI_MAX_REQUESTS", None)
            else:
                os.environ["FISORA_RATE_LIMIT_AI_MAX_REQUESTS"] = previous_ai_limit
            if previous_window is None:
                os.environ.pop("FISORA_RATE_LIMIT_WINDOW_SECONDS", None)
            else:
                os.environ["FISORA_RATE_LIMIT_WINDOW_SECONDS"] = previous_window
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["detail"]["reason"], "rate_limit_exceeded")
        self.assertEqual(second.headers.get("Retry-After"), "60")


if __name__ == "__main__":
    unittest.main()
