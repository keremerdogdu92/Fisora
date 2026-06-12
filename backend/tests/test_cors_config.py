from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient

    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    app = None


class CorsConfigTests(unittest.TestCase):
    def test_production_compose_passes_auth_env_to_backend_and_worker(self) -> None:
        compose_file = ROOT / "docker-compose.production.yml"
        compose_text = compose_file.read_text(encoding="utf-8")

        self.assertIn("FISORA_AUTH_MODE: ${FISORA_AUTH_MODE:-mock_header_required}", compose_text)
        self.assertIn("FISORA_AUTH_HEADER: ${FISORA_AUTH_HEADER:-X-Fisora-User-Id}", compose_text)
        self.assertGreaterEqual(compose_text.count("FISORA_AUTH_MODE:"), 2)
        self.assertGreaterEqual(compose_text.count("FISORA_AUTH_HEADER:"), 2)

    def test_nginx_strips_spoofable_auth_headers_and_is_tls_ready(self) -> None:
        nginx_file = ROOT / "deploy" / "nginx" / "default.conf"
        tls_file = ROOT / "deploy" / "nginx" / "default.tls.conf"
        nginx_text = nginx_file.read_text(encoding="utf-8")
        tls_text = tls_file.read_text(encoding="utf-8")

        self.assertIn("proxy_set_header X-Fisora-User-Id \"\";", nginx_text)
        self.assertIn("proxy_set_header X-Fisora-Session $http_x_fisora_session;", nginx_text)
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
