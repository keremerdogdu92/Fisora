from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def directory_size_bytes(path: Path | str) -> int:
    base = Path(path)
    if not base.exists():
        return 0
    total = 0
    for item in base.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _latest_file(path: Path, pattern: str) -> dict[str, object] | None:
    candidates = [item for item in path.glob(pattern) if item.is_file()]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    stat = latest.stat()
    return {
        "file_name": latest.name,
        "path": str(latest),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
    }


def backup_health(*, backup_path: Path | str) -> dict[str, object]:
    path = Path(backup_path)
    exists = path.exists()
    if exists:
        path.mkdir(parents=True, exist_ok=True)
    latest_database = _latest_file(path, "postgres-*.sql") if exists else None
    latest_manifest = _latest_file(path, "documents-*.manifest.tsv") if exists else None
    return {
        "ok": bool(latest_database),
        "backup_path": str(path),
        "exists": exists,
        "size_bytes": directory_size_bytes(path),
        "database_backup_count": len(list(path.glob("postgres-*.sql"))) if exists else 0,
        "document_manifest_count": len(list(path.glob("documents-*.manifest.tsv"))) if exists else 0,
        "latest_database_backup": latest_database,
        "latest_document_manifest": latest_manifest,
        "checked_at": utc_now(),
    }


def storage_usage_health(*, document_path: Path | str, export_path: Path | str, backup_path: Path | str) -> dict[str, object]:
    paths = {
        "documents": Path(document_path),
        "exports": Path(export_path),
        "backups": Path(backup_path),
    }
    usage_root = next((path for path in paths.values() if path.exists()), Path("."))
    disk = shutil.disk_usage(usage_root)
    used_percent = round((disk.used / disk.total) * 100, 2) if disk.total else 0
    return {
        "document_size_bytes": directory_size_bytes(paths["documents"]),
        "export_size_bytes": directory_size_bytes(paths["exports"]),
        "backup_size_bytes": directory_size_bytes(paths["backups"]),
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_used_percent": used_percent,
        "disk_warning": used_percent >= 80,
    }
