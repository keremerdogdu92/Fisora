from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ProtectedCorpusBackupContractTests(unittest.TestCase):
    def test_production_compose_uses_separate_protected_volume_and_backup_image(self) -> None:
        compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
        self.assertIn("FISORA_PROTECTED_CORPUS_PATH: /opt/fisora/protected-corpus", compose)
        self.assertIn("fisora_protected:/opt/fisora/protected-corpus", compose)
        self.assertIn("dockerfile: deploy/backup/Dockerfile", compose)
        self.assertIn("FISORA_BACKUP_AGE_RECIPIENT", compose)

    def test_backup_archives_bytes_hash_manifest_and_encrypts_offhost_copy(self) -> None:
        script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
        self.assertIn("PROTECTED_CORPUS_DIR", script)
        self.assertIn("sha256sum", script)
        self.assertIn("tar -czf", script)
        self.assertIn("age -r", script)

    def test_restore_verifier_checks_manifest_hashes(self) -> None:
        script = (ROOT / "deploy" / "backup" / "verify_restore.sh").read_text(encoding="utf-8")
        self.assertIn("age -d", script)
        self.assertIn("sha256sum -c", script)


if __name__ == "__main__":
    unittest.main()
