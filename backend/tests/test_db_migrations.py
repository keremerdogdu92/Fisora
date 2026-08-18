from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from apply_migrations import (
    discover_migrations,
    plan_migrations,
    resolve_sql,
    validate_applied_checksums,
)


class DbMigrationTests(unittest.TestCase):
    def test_discover_migrations_orders_versions_and_builds_checksums(self) -> None:
        migrations = discover_migrations(ROOT / "backend" / "db" / "migrations")

        self.assertGreaterEqual(len(migrations), 2)
        self.assertEqual([migration.version for migration in migrations], sorted(migration.version for migration in migrations))
        self.assertTrue(all(migration.checksum for migration in migrations))
        self.assertIn("create table if not exists tenants", migrations[0].sql)

    def test_resolve_sql_expands_include_relative_to_migration_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "schema.sql").write_text("select 1;", encoding="utf-8")
            migration = base / "migrations" / "001_initial_schema.sql"
            migration.parent.mkdir()
            migration.write_text("-- fisora:include ../schema.sql\n", encoding="utf-8")

            sql = resolve_sql(migration)

        self.assertEqual(sql, "select 1;\n")

    def test_plan_migrations_skips_applied_versions(self) -> None:
        migrations = discover_migrations(ROOT / "backend" / "db" / "migrations")
        pending = plan_migrations(migrations, {migrations[0].version})

        self.assertEqual([migration.version for migration in pending], [migration.version for migration in migrations[1:]])

    def test_applied_checksum_mismatch_fails_fast(self) -> None:
        migrations = discover_migrations(ROOT / "backend" / "db" / "migrations")
        immutable = next(migration for migration in migrations if migration.version == "003")

        with self.assertRaisesRegex(ValueError, immutable.version):
            validate_applied_checksums(
                migrations,
                {immutable.version: "stale-checksum"},
            )

    def test_legacy_mutable_initial_migration_is_explicitly_allowlisted(self) -> None:
        migrations = discover_migrations(ROOT / "backend" / "db" / "migrations")

        validate_applied_checksums(migrations, {"001": "production-legacy-checksum"})

    def test_protected_corpus_migration_is_immutable_and_complete(self) -> None:
        migration = next(
            item
            for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
            if item.version == "005"
        )

        self.assertIn("create table protected_corpora", migration.sql.lower())
        self.assertIn("create table protected_corpus_items", migration.sql.lower())
        self.assertIn("create table reference_outcome_versions", migration.sql.lower())
        self.assertIn("create table protected_rule_versions", migration.sql.lower())
        self.assertIn("unique (corpus_id, source_sha256)", migration.sql.lower())

    def test_period_retention_migration_is_complete(self) -> None:
        migration = next(
            item
            for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
            if item.version == "007"
        )
        sql = migration.sql.lower()

        self.assertIn("ck_documents_accounting_period_month_start", sql)
        self.assertIn("ck_source_files_accounting_period_month_start", sql)
        self.assertIn("create table if not exists retention_batches", sql)
        self.assertIn("create table if not exists retention_batch_sources", sql)
        self.assertIn("create table if not exists retention_scheduler_state", sql)
        self.assertIn("unique (tenant_id, taxpayer_id, accounting_period)", sql)
        self.assertIn("idx_retention_batches_due", sql)

    def test_learning_rule_lifecycle_migration_is_versioned_and_immutable(self) -> None:
        migration = next(
            item
            for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
            if item.version == "008"
        )
        sql = migration.sql.lower()

        self.assertIn("alter table learning_rules add column if not exists rule_key text", sql)
        self.assertIn("add column if not exists version integer not null default 1", sql)
        self.assertIn("check (status in ('draft', 'active', 'paused', 'archived'))", sql)
        self.assertIn("scope_snapshot jsonb not null default '{}'", sql)
        self.assertIn("rule_snapshot jsonb not null default '{}'", sql)
        self.assertIn("uq_learning_rules_key_version", sql)
        self.assertIn("idx_learning_rules_active_scope", sql)

    def test_journal_edit_collaboration_migration_keeps_candidate_revisions_separate(self) -> None:
        migration = next(
            item
            for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
            if item.version == "009"
        )
        sql = migration.sql.lower()

        self.assertIn("create table if not exists journal_edit_leases", sql)
        self.assertIn("create table if not exists journal_working_drafts", sql)
        self.assertIn("revision_role text not null default 'candidate'", sql)
        self.assertIn("check (revision_role = 'candidate')", sql)
        self.assertIn("primary key (tenant_id, journal_entry_id)", sql)

    def test_ai_outage_retry_migration_is_complete(self) -> None:
        migration = next(
            item
            for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
            if item.version == "010"
        )
        sql = migration.sql.lower()

        self.assertIn("create table if not exists ai_outage_episodes", sql)
        self.assertIn("check (status in ('open', 'recovered'))", sql)
        self.assertIn("failed_provider_categories jsonb not null default '[]'", sql)
        self.assertIn("add column if not exists next_attempt_at timestamptz", sql)
        self.assertIn("add column if not exists retry_step integer not null default 0", sql)
        self.assertIn("add column if not exists outage_episode_id uuid references ai_outage_episodes(id)", sql)
        self.assertIn("idx_processing_jobs_due_retry", sql)
        self.assertIn("uq_ai_outage_episode_open_task", sql)

    def test_gemini_credential_slot_migration_is_backward_compatible(self) -> None:
        migration = next(
            item
            for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
            if item.version == "012"
        )
        sql = migration.sql.lower()
        self.assertIn("alter table document_ai_artifacts", sql)
        self.assertIn("add column if not exists credential_slot text not null default ''", sql)


if __name__ == "__main__":
    unittest.main()
