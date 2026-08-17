from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ArtifactKind(str, Enum):
    PROVIDER_RECEIPT = "provider_receipt"
    CANONICAL_INVOICE_FORM = "canonical_invoice_form"
    ACCOUNTING_INPUT_PROJECTION = "accounting_input_projection"
    ACCOUNTING_PROPOSAL = "accounting_proposal"


@dataclass(frozen=True)
class ArtifactWrite:
    tenant_id: str
    taxpayer_id: str
    document_id: str
    source_file_id: str
    source_file_sha256: str
    kind: ArtifactKind
    stage: str
    status: str
    pipeline_version: str = ""
    artifact_id: str | None = None
    parent_artifact_id: str | None = None
    retry_of_artifact_id: str | None = None
    provider_receipt_artifact_id: str | None = None
    component_receipt_artifact_ids: tuple[str, ...] = ()
    expanded_from_receipt_id: str | None = None
    provider: str | None = None
    model_alias: str | None = None
    resolved_model: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    mapper_version: str | None = None
    elapsed_ms: int | None = None
    http_status: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    error_metadata: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentAiArtifact:
    artifact_id: str
    revision_no: int
    created_at: str
    tenant_id: str
    taxpayer_id: str
    document_id: str
    source_file_id: str
    source_file_sha256: str
    kind: ArtifactKind
    stage: str
    status: str
    pipeline_version: str = ""
    parent_artifact_id: str | None = None
    retry_of_artifact_id: str | None = None
    provider_receipt_artifact_id: str | None = None
    component_receipt_artifact_ids: tuple[str, ...] = ()
    expanded_from_receipt_id: str | None = None
    provider: str | None = None
    model_alias: str | None = None
    resolved_model: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    mapper_version: str | None = None
    elapsed_ms: int | None = None
    http_status: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    error_metadata: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    content_storage_path: str | None = None
    content_sha256: str | None = None
    request_storage_path: str | None = None
    request_sha256: str | None = None
    response_storage_path: str | None = None
    response_sha256: str | None = None


_FORBIDDEN_FIELD_NAMES = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "credential",
    "credentials",
    "headers",
    "password",
    "refreshtoken",
    "secret",
    "token",
    "xgoogapikey",
}


def _normalized_field_name(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _find_secret_field(value: object) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalized_field_name(key)
            if normalized in _FORBIDDEN_FIELD_NAMES:
                return str(key)
            found = _find_secret_field(nested)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_secret_field(nested)
            if found is not None:
                return found
    return None


def validate_artifact_write(write: ArtifactWrite) -> None:
    if not isinstance(write.kind, ArtifactKind):
        raise ValueError("unsupported document AI artifact kind")
    for name in (
        "tenant_id",
        "taxpayer_id",
        "document_id",
        "source_file_id",
        "source_file_sha256",
        "stage",
        "status",
    ):
        if not str(getattr(write, name, "") or "").strip():
            raise ValueError(f"document AI artifact {name} is required")
    if write.elapsed_ms is not None and write.elapsed_ms < 0:
        raise ValueError("document AI artifact elapsed_ms cannot be negative")
    if write.http_status is not None and (
        not isinstance(write.http_status, int) or not 100 <= write.http_status <= 599
    ):
        raise ValueError("provider receipt http_status must be between 100 and 599")
    if (write.started_at is None) != (write.finished_at is None):
        raise ValueError("provider receipt started_at and finished_at must be supplied together")
    if write.started_at is not None and write.finished_at is not None:
        if write.started_at.tzinfo is None or write.finished_at.tzinfo is None:
            raise ValueError("provider receipt timestamps must be timezone-aware")
        if write.finished_at < write.started_at:
            raise ValueError("provider receipt finished_at cannot precede started_at")
    if write.kind is ArtifactKind.PROVIDER_RECEIPT:
        if write.provider_receipt_artifact_id is not None or write.component_receipt_artifact_ids:
            raise ValueError("provider receipt cannot reference itself as a typed provider receipt edge")
    elif write.expanded_from_receipt_id is not None:
        raise ValueError("expanded_from lineage is only valid between provider receipts")
    elif any(
        value is not None
        for value in (
            write.http_status,
            write.started_at,
            write.finished_at,
        )
    ):
        raise ValueError("HTTP and expansion fields are only valid on provider receipts")
    if write.kind is not ArtifactKind.PROVIDER_RECEIPT and write.retry_of_artifact_id is not None:
        raise ValueError("retry lineage is only valid between provider receipts")
    if write.component_receipt_artifact_ids:
        if write.kind is not ArtifactKind.ACCOUNTING_PROPOSAL:
            raise ValueError("component receipt lineage is only valid for accounting proposals")
        if len(set(write.component_receipt_artifact_ids)) != len(write.component_receipt_artifact_ids):
            raise ValueError("component receipt lineage cannot contain duplicates")
        if write.provider_receipt_artifact_id not in write.component_receipt_artifact_ids:
            raise ValueError("primary provider receipt must be included in component receipt lineage")
    if (
        write.kind is ArtifactKind.PROVIDER_RECEIPT
        and write.expanded_from_receipt_id is not None
        and write.stage != "accounting_selection"
    ):
        raise ValueError("expanded_from receipt lineage is only valid for accounting selection")
    secret_field = _find_secret_field(
        {
            "token_usage": write.token_usage,
            "error_metadata": write.error_metadata,
            "metadata": write.metadata,
        }
    )
    if secret_field is not None:
        raise ValueError(f"secret-bearing field is not accepted: {secret_field}")
