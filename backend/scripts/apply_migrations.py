from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = ROOT / "backend" / "db" / "migrations"
INCLUDE_PATTERN = re.compile(r"^\s*--\s*fisora:include\s+(.+?)\s*$")
LEGACY_MUTABLE_MIGRATION_VERSIONS = {"001"}


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str
    checksum: str


def discover_migrations(migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    base_dir = Path(migrations_dir)
    migrations = []
    seen_versions: set[str] = set()
    for path in sorted(base_dir.glob("*.sql")):
        version = path.name.split("_", 1)[0]
        if not version.isdigit():
            raise ValueError(f"Migration file must start with a numeric version: {path.name}")
        if version in seen_versions:
            raise ValueError(f"Duplicate migration version: {version}")
        seen_versions.add(version)
        sql = resolve_sql(path)
        migrations.append(
            Migration(
                version=version,
                name=path.name,
                path=path,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    return migrations


def resolve_sql(path: Path, *, visited: Iterable[Path] = ()) -> str:
    resolved_path = path.resolve()
    visited_set = {item.resolve() for item in visited}
    if resolved_path in visited_set:
        raise ValueError(f"Recursive migration include detected: {path}")
    output: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = INCLUDE_PATTERN.match(line)
        if not match:
            output.append(line)
            continue
        include_path = (path.parent / match.group(1)).resolve()
        output.append(resolve_sql(include_path, visited=(*visited_set, resolved_path)))
    return "\n".join(output).strip() + "\n"


def plan_migrations(migrations: list[Migration], applied_versions: set[str]) -> list[Migration]:
    return [migration for migration in migrations if migration.version not in applied_versions]


def _database_url(args: argparse.Namespace) -> str:
    return args.database_url or os.environ.get("FISORA_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""


def _ensure_schema_migrations(cursor: object) -> None:
    cursor.execute(
        """
        create table if not exists schema_migrations (
            version text primary key,
            name text not null,
            checksum text not null,
            applied_at timestamptz not null default now()
        )
        """
    )


def _applied_migrations(cursor: object) -> dict[str, str]:
    _ensure_schema_migrations(cursor)
    cursor.execute("select version, checksum from schema_migrations")
    return {str(row[0]): str(row[1]) for row in cursor.fetchall()}


def validate_applied_checksums(
    migrations: list[Migration],
    applied: dict[str, str],
) -> None:
    current = {migration.version: migration for migration in migrations}
    mismatches = [
        version
        for version, checksum in applied.items()
        if version in current
        and version not in LEGACY_MUTABLE_MIGRATION_VERSIONS
        and current[version].checksum != checksum
    ]
    if mismatches:
        raise ValueError(
            "Applied migration checksum mismatch: " + ", ".join(sorted(mismatches))
        )


def apply_migrations(database_url: str, migrations: list[Migration]) -> list[Migration]:
    if not database_url.strip():
        raise ValueError("DATABASE_URL or FISORA_DATABASE_URL is required")
    import psycopg

    applied: list[Migration] = []
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            applied_migrations = _applied_migrations(cursor)
            validate_applied_checksums(migrations, applied_migrations)
            pending = plan_migrations(migrations, set(applied_migrations))
            for migration in pending:
                cursor.execute(migration.sql)
                cursor.execute(
                    """
                    insert into schema_migrations (version, name, checksum)
                    values (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
                applied.append(migration)
    return applied


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Fisora PostgreSQL migrations.")
    parser.add_argument("--database-url", default="", help="PostgreSQL DSN. Defaults to FISORA_DATABASE_URL or DATABASE_URL.")
    parser.add_argument("--migrations-dir", default=str(DEFAULT_MIGRATIONS_DIR), help="Directory containing versioned SQL migrations.")
    parser.add_argument("--dry-run", action="store_true", help="Print the migration plan without connecting to PostgreSQL.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    migrations = discover_migrations(Path(args.migrations_dir))
    if args.dry_run:
        for migration in migrations:
            print(f"{migration.version} {migration.name} {migration.checksum[:12]}")
        return 0
    try:
        applied = apply_migrations(_database_url(args), migrations)
    except Exception as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    if not applied:
        print("No pending migrations.")
        return 0
    for migration in applied:
        print(f"Applied {migration.version} {migration.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
