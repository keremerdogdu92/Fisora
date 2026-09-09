# File: backend/tests/test_counterparty_account_api.py
# Summary: Verifies additive counterparty chart-account creation.
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


class CounterpartyAccountApiTests(unittest.TestCase):
    def test_create_counterparty_account_adds_without_replacing_existing_chart(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "tax_id": "9270740926"},
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
            stored = client.post(
                "/phase0/store/chart-accounts",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={"client_id": "client-1", "accounts": [{"raw_account_code": "100.01", "account_name": "Kasa", "is_detail_account": True}]},
            )
            created = client.post(
                "/phase0/store/counterparty-account",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client_id": "client-1",
                    "account": {
                        "raw_account_code": "320.1234567890",
                        "normalized_account_code": "320.1234567890",
                        "account_name": "Yeni Tedarikci",
                        "is_detail_account": True,
                        "tax_id": "1234567890",
                    },
                },
            )
            duplicate = client.post(
                "/phase0/store/counterparty-account",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client_id": "client-1",
                    "account": {
                        "raw_account_code": "320.1234567890",
                        "account_name": "Yeni Tedarikci",
                        "is_detail_account": True,
                    },
                },
            )
            invalid_name = client.post(
                "/phase0/store/counterparty-account",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client_id": "client-1",
                    "account": {
                        "raw_account_code": "320.9999999999",
                        "account_name": "   ",
                        "is_detail_account": True,
                    },
                },
            )
            workspace = client.get(
                "/phase0/store/workspace/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            ).json()

        self.assertEqual(stored.status_code, 200)
        self.assertEqual(created.status_code, 200)
        self.assertTrue(created.json()["created"])
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()["created"])
        self.assertEqual(invalid_name.status_code, 400)
        self.assertEqual(created.json()["account"]["normalized_account_code"], "320.1234567890")
        codes = {
            str(account.get("normalized_account_code") or account.get("raw_account_code") or "")
            for account in workspace["chart_accounts"]["accounts"]
        }
        self.assertEqual(codes, {"100.01", "320.1234567890"})
        self.assertEqual(workspace["chart_accounts"]["account_count"], 2)


if __name__ == "__main__":
    unittest.main()
