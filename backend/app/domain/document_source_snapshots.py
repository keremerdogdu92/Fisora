# File: backend/app/domain/document_source_snapshots.py
# Summary: Validates immutable structural source snapshots and computes deterministic payload hashes for persistence.
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


SNAPSHOT_VERSION = "1.0.0"
READER_VERSION = "1.0.0"


def canonical_snapshot_bytes(snapshot: dict[str, Any]) -> bytes:
    return json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    return sha256(canonical_snapshot_bytes(snapshot)).hexdigest()


def validate_source_snapshot(snapshot: object) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError("document source snapshot must be an object")
    if snapshot.get("version") != SNAPSHOT_VERSION:
        raise ValueError("unsupported document source snapshot version")
    source = snapshot.get("source")
    if not isinstance(source, dict):
        raise ValueError("document source snapshot requires source metadata")
    if set(("file", "folder", "bytes")) - set(source):
        raise ValueError("document source snapshot source metadata is incomplete")
    if source.get("file") is not None and not isinstance(source.get("file"), str):
        raise ValueError("document source snapshot source file must be a string or null")
    if source.get("folder") is not None and not isinstance(source.get("folder"), str):
        raise ValueError("document source snapshot source folder must be a string or null")
    source_bytes = source.get("bytes")
    if not isinstance(source_bytes, int) or isinstance(source_bytes, bool) or source_bytes < 0:
        raise ValueError("document source snapshot source bytes must be a non-negative integer")
    if snapshot.get("mode") not in {"table", "section"}:
        raise ValueError("invalid document source snapshot mode")
    confidence = snapshot.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("invalid document source snapshot confidence")
    sections = snapshot.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("document source snapshot requires sections")
    warnings = snapshot.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise ValueError("document source snapshot warnings must be strings")
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("document source snapshot requires metrics")
    for metric_name in ("sectionCount", "rowCount", "columnCount"):
        metric_value = metrics.get(metric_name)
        if not isinstance(metric_value, int) or isinstance(metric_value, bool) or metric_value < 0:
            raise ValueError(f"document source snapshot metric {metric_name} must be a non-negative integer")
    for section in sections:
        if not isinstance(section, dict) or section.get("kind") not in {"table", "key_value", "fragmented"}:
            raise ValueError("invalid document source snapshot section")
        rows = section.get("rows")
        columns = section.get("columns")
        if not isinstance(rows, list) or not isinstance(columns, list):
            raise ValueError("document source snapshot section requires rows and columns")
        if not all(isinstance(row, list) and all(isinstance(cell, str) for cell in row) for row in rows):
            raise ValueError("document source snapshot row cells must be strings")
    return dict(snapshot)


@dataclass(frozen=True, slots=True)
class DocumentSourceSnapshotWrite:
    tenant_id: str
    taxpayer_id: str
    document_id: str
    source_file_id: str
    source_file_sha256: str
    parser_kind: str
    snapshot: dict[str, Any]
    reader_version: str = READER_VERSION
    snapshot_version: str = SNAPSHOT_VERSION

    def validated(self) -> "DocumentSourceSnapshotWrite":
        for label, value in (
            ("tenant_id", self.tenant_id),
            ("taxpayer_id", self.taxpayer_id),
            ("document_id", self.document_id),
            ("source_file_id", self.source_file_id),
            ("parser_kind", self.parser_kind),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required")
        source_hash = self.source_file_sha256.strip().lower()
        if len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash):
            raise ValueError("source_file_sha256 must be a lowercase SHA-256 hex digest")
        if self.snapshot_version != SNAPSHOT_VERSION or self.reader_version != READER_VERSION:
            raise ValueError("document source snapshot release version mismatch")
        validated_snapshot = validate_source_snapshot(self.snapshot)
        if validated_snapshot.get("version") != self.snapshot_version:
            raise ValueError("snapshot payload version does not match snapshot_version")
        return self

    @property
    def payload_sha256(self) -> str:
        self.validated()
        return snapshot_sha256(self.snapshot)


def snapshot_plain_text(snapshot: dict[str, Any]) -> str:
    """Render only structural snapshot strings for text-only consumers; original preview is a separate isolated path."""

    validated = validate_source_snapshot(snapshot)
    lines: list[str] = []
    for section in validated.get("sections") or []:
        title = str(section.get("title") or "").strip()
        if title:
            lines.append(title)
        columns = [str(value) for value in section.get("columns") or [] if str(value).strip()]
        if columns:
            lines.append(" | ".join(columns))
        for row in section.get("rows") or []:
            cells = [str(value) for value in row if str(value).strip()]
            if cells:
                lines.append(" | ".join(cells))
        lines.append("")
    return "\n".join(lines).strip()
