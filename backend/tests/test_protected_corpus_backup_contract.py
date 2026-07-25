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
        self.assertIn("protected-corpus.tar", script)
        self.assertIn("age -r", script)

    def test_backup_script_uses_mode_staging_and_success_receipt(self) -> None:
        script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
        self.assertIn('BACKUP_MODE="${FISORA_BACKUP_MODE:-disabled}"', script)
        self.assertIn("mktemp -d", script)
        self.assertIn("trap cleanup", script)
        self.assertIn("backup-success-", script)
        self.assertIn("offhost_copy_status", script)

    def test_scheduled_backup_archives_real_document_bytes(self) -> None:
        script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "$BACKUP_MODE" = "scheduled" ]', script)
        self.assertIn("documents.tar", script)
        self.assertIn("-iname '*.pdf'", script)
        self.assertIn("-iname '*.xml'", script)
        self.assertIn('-T "$stage/documents.list"', script)

    def test_checkpoint_does_not_use_document_manifest_as_backup(self) -> None:
        script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
        self.assertIn("checkpoint", script)
        self.assertIn("scheduled", script)
        self.assertNotIn("documents-$stamp.manifest.tsv", script)

    def test_failed_backup_cleans_partial_encrypted_copy_and_receipt(self) -> None:
        script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
        self.assertIn('rm -f -- "$local_encrypted.tmp"', script)
        self.assertIn('rm -f -- "$offhost_encrypted.tmp"', script)
        self.assertIn('rm -f -- "$receipt.tmp"', script)

    def test_restore_verifier_checks_manifest_hashes(self) -> None:
        script = (ROOT / "deploy" / "backup" / "verify_restore.sh").read_text(encoding="utf-8")
        self.assertIn("age -d", script)
        self.assertIn("sha256sum -c", script)
        self.assertIn("protected-corpus.tar", script)
        self.assertIn("postgres.sql", script)
        self.assertIn("SHA256SUMS", script)

    def test_restore_command_loads_packaged_postgres_before_corpus_verification(self) -> None:
        script = (ROOT / "deploy" / "scripts" / "fisora-prod.sh").read_text(encoding="utf-8")
        self.assertIn('psql "$DATABASE_URL" < /proof/restore/postgres.sql', script)

    def test_backup_service_is_profile_gated_and_mode_is_wired(self) -> None:
        compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
        self.assertIn('profiles: ["backup"]', compose)
        self.assertGreaterEqual(
            compose.count("FISORA_BACKUP_MODE: ${FISORA_BACKUP_MODE:-disabled}"),
            2,
        )

    def test_production_env_defaults_backup_to_disabled(self) -> None:
        env_example = (ROOT / "deploy" / "production.env.example").read_text(encoding="utf-8")
        self.assertIn("FISORA_BACKUP_MODE=disabled", env_example)
        self.assertIn("FISORA_BACKUP_OFFHOST_KEEP_DAYS=30", env_example)

    def test_ops_script_starts_profile_only_for_scheduled_mode(self) -> None:
        script = (ROOT / "deploy" / "scripts" / "fisora-prod.sh").read_text(encoding="utf-8")
        self.assertIn('backup_mode="', script)
        self.assertIn("--profile backup", script)
        self.assertIn("compose stop backup", script)
        self.assertIn("record-restore-verification", script)


if __name__ == "__main__":
    unittest.main()
