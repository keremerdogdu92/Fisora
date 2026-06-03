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

    def test_api_blocks_anonymous_workspace_access_when_auth_requires_user(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous = os.environ.get("FISORA_AUTH_MODE")
        previous_store_path = phase0.DEFAULT_STORE_PATH
        os.environ["FISORA_AUTH_MODE"] = "trusted_header"
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
            phase0.DEFAULT_STORE_PATH = previous_store_path

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["reason"], "portal_user_required")


if __name__ == "__main__":
    unittest.main()
