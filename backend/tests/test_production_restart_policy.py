import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.production.yml"
LONG_RUNNING_SERVICES = {
    "postgres",
    "redis",
    "backend",
    "worker",
    "qnb-scheduler",
    "frontend",
    "nginx",
    "backup",
}


def service_blocks(compose_text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^  ([a-z][a-z0-9_-]*):\s*$", compose_text, re.MULTILINE))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compose_text)
        blocks[match.group(1)] = compose_text[match.start():end]
    return blocks


class ProductionRestartPolicyTest(unittest.TestCase):
    def test_long_running_services_restart_unless_stopped(self):
        blocks = service_blocks(COMPOSE_FILE.read_text(encoding="utf-8"))

        for service in sorted(LONG_RUNNING_SERVICES):
            with self.subTest(service=service):
                self.assertIn(
                    "restart: unless-stopped",
                    blocks[service],
                    f"{service} must restart after a host reboot",
                )

    def test_migration_service_remains_one_shot(self):
        blocks = service_blocks(COMPOSE_FILE.read_text(encoding="utf-8"))

        self.assertNotIn("restart:", blocks["migrate"])

    def test_store_target_is_forwarded_consistently_to_backend_worker_and_qnb_scheduler(self):
        blocks = service_blocks(COMPOSE_FILE.read_text(encoding="utf-8"))
        expected = "FISORA_ACCOUNTING_STORE_TARGET: ${FISORA_ACCOUNTING_STORE_TARGET:-compatibility}"

        self.assertIn(expected, blocks["backend"])
        self.assertIn(expected, blocks["worker"])
        self.assertIn(expected, blocks["qnb-scheduler"])

    def test_doctor_command_reports_only_safe_store_settings(self):
        script = (ROOT / "deploy" / "scripts" / "fisora-prod.sh").read_text(encoding="utf-8")

        self.assertIn("doctor)", script)
        self.assertIn("FISORA_STORE_BACKEND=", script)
        self.assertIn("FISORA_ACCOUNTING_STORE_TARGET=", script)
        self.assertNotRegex(script, r"doctor[\s\S]*DATABASE_URL")


if __name__ == "__main__":
    unittest.main()
