from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "scripts" / "fisora-release.ps1"


class FisoraReleaseScriptTests(unittest.TestCase):
    def test_plan_only_outputs_compact_release_plan(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        self.assertIsNotNone(powershell, "PowerShell is required to validate fisora-release.ps1")
        self.assertTrue(SCRIPT.exists(), "deploy/scripts/fisora-release.ps1 must exist")

        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-PlanOnly",
                "-Json",
                "-Server",
                "codex@example.test",
                "-RemotePath",
                "/opt/fisora/app",
                "-Branch",
                "main",
                "-BaseUrl",
                "http://example.test",
                "-SkipLocalVerify",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["server"], "codex@example.test")
        self.assertEqual(payload["remote_path"], "/opt/fisora/app")
        self.assertEqual(payload["branch"], "main")
        self.assertFalse(payload["local_verify_enabled"])
        self.assertTrue(payload["sudo_enabled"])
        self.assertIn("ssh_key_configured", payload)
        self.assertIn("git fetch origin", payload["remote_script"])
        self.assertIn("git pull --ff-only origin main", payload["remote_script"])
        self.assertIn("sh deploy/scripts/fisora-prod.sh check", payload["remote_script"])
        self.assertIn("sh deploy/scripts/fisora-prod.sh deploy", payload["remote_script"])
        self.assertIn("/api/phase0/store/system/readiness", payload["remote_script"])

    def test_help_documents_low_token_flags(self) -> None:
        content = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("PlanOnly", content)
        self.assertIn("SshKey", content)
        self.assertIn("SkipLocalVerify", content)
        self.assertIn("SkipSmoke", content)
        self.assertIn("NoSudo", content)
        self.assertIn("Json", content)


if __name__ == "__main__":
    unittest.main()
