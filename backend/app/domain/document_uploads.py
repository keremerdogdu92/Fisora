from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


ALLOWED_DOCUMENT_TYPES = {"invoice", "einvoice_xml", "bank_statement", "pos_statement"}


@dataclass(frozen=True)
class StoredDocument:
    document_id: str
    client_id: str
    document_type: str
    original_file_name: str
    stored_file_name: str
    storage_path: str
    status: str
    size_bytes: int
    sha256: str
    uploaded_by: str


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


def store_document_content(
    *,
    base_dir: Path | str,
    client_id: str,
    file_name: str,
    document_type: str,
    uploaded_by: str,
    content: bytes | None = None,
    declared_size_bytes: int = 0,
    declared_sha256: str = "",
) -> StoredDocument:
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise ValueError(f"unsupported document_type: {document_type}")
    if not client_id.strip():
        raise ValueError("client_id is required")
    if not file_name.strip():
        raise ValueError("file_name is required")

    document_id = str(uuid4())
    safe_client = sanitize_identifier(client_id)
    safe_name = sanitize_file_name(file_name)
    storage_dir = Path(base_dir) / safe_client / document_id
    storage_path = storage_dir / safe_name

    actual_size = declared_size_bytes
    actual_sha256 = declared_sha256
    status = "queued"

    if content is not None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        actual_size = len(content)
        actual_sha256 = hashlib.sha256(content).hexdigest()
        status = "stored"

    return StoredDocument(
        document_id=document_id,
        client_id=client_id,
        document_type=document_type,
        original_file_name=file_name,
        stored_file_name=safe_name,
        storage_path=str(storage_path),
        status=status,
        size_bytes=actual_size,
        sha256=actual_sha256,
        uploaded_by=uploaded_by,
    )
