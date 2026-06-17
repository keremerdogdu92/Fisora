from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.domain.storage_adapters import build_document_storage_adapter


ALLOWED_DOCUMENT_TYPES = {"invoice", "einvoice_xml", "bank_statement", "pos_statement", "special_document"}
ALLOWED_INTAKE_CATEGORIES = {
    "sales_invoice",
    "purchase_invoice",
    "bank_statement",
    "pos_statement",
    "special_document",
}
DEFAULT_INTAKE_CATEGORY_BY_DOCUMENT_TYPE = {
    "invoice": "purchase_invoice",
    "einvoice_xml": "purchase_invoice",
    "bank_statement": "bank_statement",
    "pos_statement": "pos_statement",
    "special_document": "special_document",
}
DEFAULT_RETENTION_DAYS = 90
DEFAULT_EXPIRING_WARNING_DAYS = 15


@dataclass(frozen=True)
class StoredDocument:
    document_id: str
    client_id: str
    document_type: str
    intake_category: str
    period: str
    original_file_name: str
    stored_file_name: str
    storage_path: str
    storage_backend: str
    status: str
    storage_status: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    retention_policy_days: int
    download_available_until: str
    expires_at: str
    deleted_at: str


@dataclass(frozen=True)
class DocumentRetentionDecision:
    document_id: str
    storage_status: str
    should_delete: bool
    reason: str


def sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned[:80] or "unknown"


def sanitize_file_name(file_name: str) -> str:
    candidate = Path(file_name).name.strip()
    candidate = re.sub(r"[^a-zA-Z0-9_. -]+", "-", candidate)
    candidate = re.sub(r"\s+", "-", candidate).strip(".-")
    return candidate[:120] or "document.bin"


def decode_base64_content(content_base64: str) -> bytes:
    try:
        return base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("content_base64 is not valid base64") from exc


def normalize_intake_category(*, document_type: str, intake_category: str = "") -> str:
    selected = intake_category.strip() or DEFAULT_INTAKE_CATEGORY_BY_DOCUMENT_TYPE.get(document_type, "purchase_invoice")
    if selected not in ALLOWED_INTAKE_CATEGORIES:
        raise ValueError(f"unsupported intake_category: {selected}")
    return selected


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def retention_deadline(*, created_at: datetime | None = None, retention_days: int = DEFAULT_RETENTION_DAYS) -> datetime:
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    return (created_at or utc_now()) + timedelta(days=retention_days)


def document_storage_status(
    *,
    expires_at: datetime,
    now: datetime | None = None,
    warning_days: int = DEFAULT_EXPIRING_WARNING_DAYS,
) -> str:
    current = now or utc_now()
    if current >= expires_at:
        return "expired"
    if current >= expires_at - timedelta(days=warning_days):
        return "expiring"
    return "stored"


def retention_decision(document: dict[str, object], *, now: datetime | None = None) -> DocumentRetentionDecision:
    expires_raw = str(document.get("expires_at") or "")
    deleted_raw = str(document.get("deleted_at") or "")
    document_id = str(document.get("document_id") or document.get("document_ref") or "")
    if deleted_raw:
        return DocumentRetentionDecision(document_id, "deleted", False, "already_deleted")
    if not expires_raw:
        return DocumentRetentionDecision(document_id, str(document.get("storage_status") or "unknown"), False, "missing_expiry")
    expires_at = datetime.fromisoformat(expires_raw)
    status = document_storage_status(expires_at=expires_at, now=now)
    return DocumentRetentionDecision(document_id, status, status == "expired", "retention_expired" if status == "expired" else "retained")


def store_document_content(
    *,
    base_dir: Path | str,
    client_id: str,
    file_name: str,
    document_type: str,
    intake_category: str = "",
    period: str = "",
    uploaded_by: str,
    content: bytes | None = None,
    declared_size_bytes: int = 0,
    declared_sha256: str = "",
    retention_days: int = DEFAULT_RETENTION_DAYS,
    created_at: datetime | None = None,
) -> StoredDocument:
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise ValueError(f"unsupported document_type: {document_type}")
    normalized_intake_category = normalize_intake_category(
        document_type=document_type,
        intake_category=intake_category,
    )
    if not client_id.strip():
        raise ValueError("client_id is required")
    if not file_name.strip():
        raise ValueError("file_name is required")

    document_id = str(uuid4())
    created = created_at or utc_now()
    expires_at = retention_deadline(created_at=created, retention_days=retention_days)
    safe_client = sanitize_identifier(client_id)
    safe_name = sanitize_file_name(file_name)
    storage_path = Path(base_dir) / safe_client / document_id / safe_name
    storage_backend = "local"

    actual_size = declared_size_bytes
    actual_sha256 = declared_sha256
    status = "queued"
    storage_status = "queued"

    if content is not None:
        stored = build_document_storage_adapter(base_dir=base_dir).write_bytes(
            client_key=safe_client,
            document_id=document_id,
            file_name=safe_name,
            content=content,
        )
        storage_path = Path(stored.path)
        storage_backend = stored.backend
        actual_size = len(content)
        actual_sha256 = hashlib.sha256(content).hexdigest()
        status = "stored"
        storage_status = document_storage_status(expires_at=expires_at, now=created)

    return StoredDocument(
        document_id=document_id,
        client_id=client_id,
        document_type=document_type,
        intake_category=normalized_intake_category,
        period=period.strip(),
        original_file_name=file_name,
        stored_file_name=safe_name,
        storage_path=str(storage_path),
        storage_backend=storage_backend,
        status=status,
        storage_status=storage_status,
        size_bytes=actual_size,
        sha256=actual_sha256,
        uploaded_by=uploaded_by,
        retention_policy_days=retention_days,
        download_available_until=isoformat(expires_at),
        expires_at=isoformat(expires_at),
        deleted_at="",
    )
