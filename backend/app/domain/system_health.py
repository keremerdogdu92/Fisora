from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import shutil


BACKUP_MODES = {"disabled", "checkpoint", "scheduled"}
BACKUP_FRESHNESS = timedelta(hours=26)
RESTORE_FRESHNESS = timedelta(days=30)


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


def _read_json_receipt(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _latest_receipt(path: Path, pattern: str) -> dict[str, object] | None:
    candidates = sorted(
        (item for item in path.glob(pattern) if item.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        receipt = _read_json_receipt(candidate)
        if receipt is not None:
            return receipt
    return None


def _receipt_datetime(receipt: dict[str, object] | None, field: str) -> datetime | None:
    if receipt is None:
        return None
    value = receipt.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def backup_health(
    *,
    backup_path: Path | str,
    mode: str,
    offhost_attested: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    path = Path(backup_path)
    exists = path.exists()
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    normalized_mode = mode.strip().lower()
    latest_database = _latest_file(path, "postgres-*.sql") if exists else None
    latest_manifest = _latest_file(path, "documents-*.manifest.tsv") if exists else None
    common = {
        "backup_path": str(path),
        "exists": exists,
        "size_bytes": directory_size_bytes(path),
        "database_backup_count": len(list(path.glob("postgres-*.sql"))) if exists else 0,
        "document_manifest_count": len(list(path.glob("documents-*.manifest.tsv"))) if exists else 0,
        "latest_database_backup": latest_database,
        "latest_document_manifest": latest_manifest,
        "checked_at": checked_at.isoformat(timespec="seconds"),
    }
    if normalized_mode not in BACKUP_MODES:
        return {
            **common,
            "ok": False,
            "mode": normalized_mode or "invalid",
            "required": True,
            "status": "failing",
            "service_state": "configuration_error",
            "latest_attempt_at": None,
            "latest_success_at": None,
            "latest_encrypted_generation": None,
            "latest_generation_digest": None,
            "offhost_copy_status": "unknown",
            "offhost_target_attested": offhost_attested,
            "restore_verified_at": None,
            "blocking": ["backup_mode_invalid"],
            "warnings": [],
        }
    if normalized_mode == "disabled":
        return {
            **common,
            "ok": True,
            "mode": "disabled",
            "required": False,
            "status": "not_required",
            "service_state": "not_started",
            "latest_attempt_at": None,
            "latest_success_at": None,
            "latest_encrypted_generation": None,
            "latest_generation_digest": None,
            "offhost_copy_status": "not_required",
            "offhost_target_attested": False,
            "restore_verified_at": None,
            "blocking": [],
            "warnings": [],
        }

    success = _latest_receipt(path, "backup-success-*.json") if exists else None
    restore = _latest_receipt(path, "restore-verified-*.json") if exists else None
    latest_success = _receipt_datetime(success, "latest_success_at")
    restore_verified = _receipt_datetime(restore, "verified_at")
    generation = success.get("generation_file") if success else None
    generation_digest = success.get("generation_digest") if success else None
    offhost_status = success.get("offhost_copy_status") if success else None
    blocking: list[str] = []
    if not offhost_attested:
        blocking.append("offhost_target_unattested")
    if success is None or latest_success is None or not isinstance(generation, str):
        blocking.append("backup_generation_missing")
    else:
        if checked_at - latest_success > BACKUP_FRESHNESS:
            blocking.append("backup_generation_stale")
        if not (path / generation).is_file():
            blocking.append("backup_generation_missing")
        if offhost_status != "complete":
            blocking.append("offhost_copy_incomplete")
        if not isinstance(generation_digest, str) or not generation_digest:
            blocking.append("backup_digest_missing")
    if restore_verified is None:
        blocking.append("restore_verification_missing")
    else:
        if checked_at - restore_verified > RESTORE_FRESHNESS:
            blocking.append("restore_verification_stale")
        if (
            restore.get("status") != "verified"
            or restore.get("generation_file") != generation
            or restore.get("generation_digest") != generation_digest
        ):
            blocking.append("restore_generation_mismatch")
    status = "recoverable" if not blocking else ("missing" if success is None else "failing")
    return {
        **common,
        "ok": not blocking,
        "mode": normalized_mode,
        "required": True,
        "status": status,
        "service_state": "completed" if success is not None else "unknown",
        "latest_attempt_at": success.get("latest_attempt_at") if success else None,
        "latest_success_at": success.get("latest_success_at") if success else None,
        "latest_encrypted_generation": generation if isinstance(generation, str) else None,
        "latest_generation_digest": generation_digest if isinstance(generation_digest, str) else None,
        "offhost_copy_status": offhost_status if isinstance(offhost_status, str) else "unknown",
        "offhost_target_attested": offhost_attested,
        "restore_verified_at": restore.get("verified_at") if restore else None,
        "blocking": list(dict.fromkeys(blocking)),
        "warnings": [],
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
