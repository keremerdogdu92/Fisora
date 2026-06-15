from __future__ import annotations

from pathlib import Path
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient

    from app.main import app, cors_allow_origins
except ModuleNotFoundError:
    TestClient = None
    app = None
    cors_allow_origins = None


class CorsConfigTests(unittest.TestCase):
    def test_production_compose_passes_auth_env_to_backend_and_worker(self) -> None:
        compose_file = ROOT / "docker-compose.production.yml"
        compose_text = compose_file.read_text(encoding="utf-8")

        self.assertIn("FISORA_AUTH_MODE: ${FISORA_AUTH_MODE:-session_required}", compose_text)
        self.assertIn("FISORA_AUTH_HEADER: ${FISORA_AUTH_HEADER:-X-Fisora-User-Id}", compose_text)
        self.assertIn("FISORA_RATE_LIMIT_ENABLED: ${FISORA_RATE_LIMIT_ENABLED:-true}", compose_text)
        self.assertGreaterEqual(compose_text.count("FISORA_AUTH_MODE:"), 2)
        self.assertGreaterEqual(compose_text.count("FISORA_AUTH_HEADER:"), 2)

    def test_cors_origins_are_configurable_from_environment(self) -> None:
        main_file = ROOT / "backend" / "app" / "main.py"
        main_text = main_file.read_text(encoding="utf-8")

        self.assertIn("FISORA_CORS_ALLOW_ORIGINS", main_text)
        self.assertNotIn('"http://192.168.1.101:3000"', main_text)

    def test_empty_cors_environment_uses_safe_local_defaults(self) -> None:
        if cors_allow_origins is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_CORS_ALLOW_ORIGINS")
        os.environ["FISORA_CORS_ALLOW_ORIGINS"] = ""
        try:
            origins = cors_allow_origins()
        finally:
            if previous is None:
                os.environ.pop("FISORA_CORS_ALLOW_ORIGINS", None)
            else:
                os.environ["FISORA_CORS_ALLOW_ORIGINS"] = previous

        self.assertIn("http://localhost:3000", origins)
        self.assertIn("http://192.168.1.101:3000", origins)

    def test_nginx_keeps_http_pilot_auth_and_tls_template_strips_spoofable_headers(self) -> None:
        nginx_file = ROOT / "deploy" / "nginx" / "default.conf"
        tls_file = ROOT / "deploy" / "nginx" / "default.tls.conf"
        nginx_text = nginx_file.read_text(encoding="utf-8")
        tls_text = tls_file.read_text(encoding="utf-8")

        self.assertIn("proxy_set_header X-Fisora-User-Id $http_x_fisora_user_id;", nginx_text)
        self.assertIn("proxy_set_header X-Fisora-Session $http_x_fisora_session;", nginx_text)
        self.assertIn("proxy_set_header X-Fisora-User-Id \"\";", tls_text)
        self.assertIn("listen 443 ssl", tls_text)
        self.assertIn("return 301 https://$host$request_uri;", tls_text)

    def test_lan_frontend_origin_can_call_backend(self) -> None:
        if TestClient is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        client = TestClient(app)
        response = client.options(
            "/health",
            headers={
                "Origin": "http://192.168.1.101:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://192.168.1.101:3000")
