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


if __name__ == "__main__":
    unittest.main()
