# File: deploy/tests/test_production_deploy_contract.py
# Summary: Verifies the production deployment contract between GitHub Actions, the restricted SSM document, and production scripts.

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT / "deploy" / "aws" / "fisora-production-deploy-document.json"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"
PROD_SCRIPT = ROOT / "deploy" / "scripts" / "fisora-prod.sh"


class ProductionDeployContractTests(unittest.TestCase):
    def test_ssm_document_is_restricted_and_self_diagnosing(self) -> None:
        payload = json.loads(DOCUMENT.read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], "2.2")
        self.assertEqual(payload["parameters"]["TargetSha"]["allowedPattern"], "^[0-9a-f]{40}$")

        steps = payload["mainSteps"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["action"], "aws:runShellScript")
        commands = "\n".join(steps[0]["inputs"]["runCommand"])
        self.assertIn("sudo -u ubuntu git -C", commands)
        self.assertIn("--untracked-files=no", commands)
        self.assertIn("FISORA_DEPLOY_BLOCKED reason=tracked_worktree_changes", commands)
        self.assertIn("FISORA_DIRTY_WORKTREE_BLOB=", commands)
        self.assertIn("FISORA_DIRTY_HEAD_BLOB=", commands)
        self.assertIn("7001c451a720f682b5334f97d10dab9643c38180", commands)
        self.assertIn("FISORA_DEPLOY_REPAIRED reason=known_legacy_workflow_blob", commands)
        self.assertIn("restore --source=HEAD --worktree", commands)
        self.assertIn("merge-base --is-ancestor", commands)
        self.assertIn("github-actions-prod-deploy.sh", commands)
        self.assertNotIn("reset --hard", commands)

    def test_workflow_only_invokes_the_restricted_document_with_exact_sha(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("SSM_DOCUMENT: FisoraProductionDeploy", workflow)
        self.assertIn('--parameters "TargetSha=${GITHUB_SHA}"', workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertNotIn("AWS-RunShellScript", workflow)

    def test_production_script_uses_safe_git_wrapper_for_receipts(self) -> None:
        script = PROD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('git -c safe.directory="$ROOT_DIR" -C "$ROOT_DIR" "$@"', script)
        self.assertIn('before_sha="$(git_repo rev-parse HEAD', script)
        self.assertIn('after_sha="$(git_repo rev-parse HEAD', script)


if __name__ == "__main__":
    unittest.main()
