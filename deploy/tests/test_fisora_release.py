from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "scripts" / "fisora-release.ps1"
PUBLISH_SCRIPT = ROOT / "deploy" / "scripts" / "fisora-publish.ps1"


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
        self.assertIn("Assert-OriginParity", content)


class FisoraPublishScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.powershell = shutil.which("powershell") or shutil.which("pwsh")
        self.assertIsNotNone(self.powershell, "PowerShell is required to validate fisora-publish.ps1")
        self.assertTrue(PUBLISH_SCRIPT.exists(), "deploy/scripts/fisora-publish.ps1 must exist")

    def _run_publish(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PUBLISH_SCRIPT),
                *args,
            ],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    def _make_repo(self, temp_dir: Path) -> tuple[Path, Path]:
        origin = temp_dir / "origin.git"
        work = temp_dir / "work"
        self._git(temp_dir, "init", "--bare", str(origin))
        self._git(temp_dir, "init", str(work))
        self._git(work, "config", "user.email", "fisora-tests@example.test")
        self._git(work, "config", "user.name", "Fisora Tests")
        (work / "README.md").write_text("initial\n", encoding="utf-8")
        self._git(work, "add", "README.md")
        self._git(work, "commit", "-m", "initial")
        self._git(work, "branch", "-M", "main")
        self._git(work, "remote", "add", "origin", str(origin))
        self._git(work, "push", "-u", "origin", "main")
        self._git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        return origin, work

    def test_publish_plan_only_outputs_compact_json(self) -> None:
        completed = self._run_publish(
            ROOT,
            "-PlanOnly",
            "-Json",
            "-Remote",
            "origin",
            "-Branch",
            "main",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["remote"], "origin")
        self.assertEqual(payload["branch"], "main")
        self.assertTrue(payload["quiet"])
        self.assertEqual(payload["push_command"], "git push --quiet origin HEAD:main")

    def test_publish_pushes_ahead_branch_with_quiet_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, work = self._make_repo(Path(temp))
            (work / "README.md").write_text("initial\nchange\n", encoding="utf-8")
            self._git(work, "add", "README.md")
            self._git(work, "commit", "-m", "change")

            completed = self._run_publish(work, "-Branch", "main", "-Remote", "origin", "-Json")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["mode"], "publish")
            self.assertEqual(payload["branch"], "main")
            self.assertEqual(payload["remote"], "origin")
            self.assertEqual(payload["ahead"], 1)
            self.assertEqual(payload["behind"], 0)
            self.assertTrue(payload["pushed"])
            self.assertFalse(payload["skipped"])

    def test_publish_skips_when_branch_is_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, work = self._make_repo(Path(temp))

            completed = self._run_publish(work, "-Branch", "main", "-Remote", "origin", "-Json")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["pushed"])
            self.assertTrue(payload["skipped"])
            self.assertEqual(payload["ahead"], 0)
            self.assertEqual(payload["behind"], 0)

    def test_publish_rejects_dirty_worktree_without_allow_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, work = self._make_repo(Path(temp))
            (work / "draft.txt").write_text("draft\n", encoding="utf-8")

            completed = self._run_publish(work, "-Branch", "main", "-Remote", "origin", "-Json")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Local worktree has uncommitted changes", completed.stdout + completed.stderr)

    def test_publish_rejects_diverged_branch_without_pushing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            origin, work = self._make_repo(temp_path)
            other = temp_path / "other"
            self._git(temp_path, "clone", str(origin), str(other))
            self._git(other, "config", "user.email", "fisora-tests@example.test")
            self._git(other, "config", "user.name", "Fisora Tests")
            (other / "remote.txt").write_text("remote\n", encoding="utf-8")
            self._git(other, "add", "remote.txt")
            self._git(other, "commit", "-m", "remote")
            self._git(other, "push", "origin", "main")
            (work / "local.txt").write_text("local\n", encoding="utf-8")
            self._git(work, "add", "local.txt")
            self._git(work, "commit", "-m", "local")

            completed = self._run_publish(work, "-Branch", "main", "-Remote", "origin", "-Json")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("diverged", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
