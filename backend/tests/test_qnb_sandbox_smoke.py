from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_qnb_sandbox_smoke.py"
SPEC = importlib.util.spec_from_file_location("run_qnb_sandbox_smoke", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QnbSandboxSmokeTests(unittest.TestCase):
    def test_load_env_file_supports_comments_and_quoted_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env.qnb.local"
            env_path.write_text(
                "# secret sandbox settings\n"
                "QNB_EFATURA_RECEIVER_ENV=TEST1\n"
                "QNB_EFATURA_TEST1_USERNAME='receiver'\n"
                'QNB_EFATURA_TEST1_PASSWORD="secret"\n',
                encoding="utf-8",
            )

            values = MODULE.load_env_file(env_path)

        self.assertEqual(values["QNB_EFATURA_RECEIVER_ENV"], "TEST1")
        self.assertEqual(values["QNB_EFATURA_TEST1_USERNAME"], "receiver")
        self.assertEqual(values["QNB_EFATURA_TEST1_PASSWORD"], "secret")

    def test_receiver_credentials_uses_selected_environment_without_exposing_secret(self) -> None:
        environment, credentials = MODULE.receiver_credentials(
            {
                "QNB_EFATURA_RECEIVER_ENV": "test1",
                "QNB_EFATURA_TEST1_BASE_URL": "https://example.test/efatura/ws",
                "QNB_EFATURA_TEST1_USERNAME": "receiver",
                "QNB_EFATURA_TEST1_PASSWORD": "secret",
                "QNB_EFATURA_TEST1_VKN": "1111111111",
                "QNB_ERP_CODE": "ERP1",
            }
        )

        self.assertEqual(environment, "TEST1")
        self.assertEqual(credentials.username, "receiver")
        self.assertEqual(credentials.password, "secret")

    def test_safe_sync_summary_drops_error_payloads(self) -> None:
        summary = MODULE.safe_sync_summary(
            {
                "sync_run_id": "run-1",
                "listed_count": 1,
                "failed_count": 1,
                "errors": [{"ettn": "private-id", "message": "provider detail"}],
            }
        )

        self.assertEqual(summary["sync_run_id"], "run-1")
        self.assertEqual(summary["listed_count"], 1)
        self.assertNotIn("errors", summary)


if __name__ == "__main__":
    unittest.main()
