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
