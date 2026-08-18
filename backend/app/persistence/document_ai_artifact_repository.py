from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import Lock, RLock
from typing import Any, Iterable
from uuid import uuid4

from app.domain.document_ai_artifacts import (
    ArtifactKind,
    ArtifactWrite,
    DocumentAiArtifact,
    validate_artifact_write,
)
from app.domain.storage_adapters import DocumentStorageAdapter


_EXPECTED_PARENT_KIND = {
    ArtifactKind.CANONICAL_INVOICE_FORM: ArtifactKind.PROVIDER_RECEIPT,
    ArtifactKind.ACCOUNTING_INPUT_PROJECTION: ArtifactKind.CANONICAL_INVOICE_FORM,
    ArtifactKind.ACCOUNTING_PROPOSAL: ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
}
_PROCESS_LOCKS: dict[str, RLock] = {}
_PROCESS_LOCKS_GUARD = Lock()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _record_to_dict(record: DocumentAiArtifact) -> dict[str, Any]:
    payload = asdict(record)
    payload["kind"] = record.kind.value
    payload["started_at"] = record.started_at.isoformat() if record.started_at else None
    payload["finished_at"] = record.finished_at.isoformat() if record.finished_at else None
    return payload


def _record_from_dict(payload: dict[str, Any]) -> DocumentAiArtifact:
    return DocumentAiArtifact(
        **{
            **payload,
            "kind": ArtifactKind(str(payload["kind"])),
            "revision_no": int(payload["revision_no"]),
            "token_usage": dict(payload.get("token_usage") or {}),
            "error_metadata": dict(payload.get("error_metadata") or {}),
            "metadata": dict(payload.get("metadata") or {}),
            "component_receipt_artifact_ids": tuple(
                payload.get("component_receipt_artifact_ids") or ()
            ),
            "started_at": (
                datetime.fromisoformat(str(payload["started_at"]))
                if payload.get("started_at")
                else None
            ),
            "finished_at": (
                datetime.fromisoformat(str(payload["finished_at"]))
                if payload.get("finished_at")
                else None
            ),
        }
    )


def _validate_bytes(
    write: ArtifactWrite,
    *,
    content: bytes | None,
    request_body: bytes | None,
    response_body: bytes | None,
) -> None:
    if write.kind is ArtifactKind.PROVIDER_RECEIPT:
        if content is not None or not isinstance(request_body, bytes) or not isinstance(response_body, bytes):
            raise ValueError("provider receipt requires exact request_body and response_body bytes only")
        return
    if not isinstance(content, bytes) or request_body is not None or response_body is not None:
        raise ValueError("derived document AI artifact requires content bytes only")


def _validate_lineage(
    write: ArtifactWrite,
    *,
    parent: DocumentAiArtifact | None,
    retry: DocumentAiArtifact | None,
    provider_receipt: DocumentAiArtifact | None,
    component_receipts: tuple[DocumentAiArtifact, ...],
    expanded_from: DocumentAiArtifact | None,
) -> None:
    expected_parent_kind = _EXPECTED_PARENT_KIND.get(write.kind)
    if expected_parent_kind is None:
        if write.parent_artifact_id is not None:
            raise ValueError("provider receipt lineage cannot have a parent artifact")
    elif parent is None or parent.kind is not expected_parent_kind:
        raise ValueError(
            f"document AI artifact lineage requires {expected_parent_kind.value} parent"
        )
    if (
        write.kind is ArtifactKind.CANONICAL_INVOICE_FORM
        and parent is not None
        and parent.stage != "document_extraction"
    ):
        raise ValueError("canonical lineage requires a document_extraction provider receipt")
    if (
        write.kind is ArtifactKind.CANONICAL_INVOICE_FORM
        and parent is not None
        and parent.status != "successful"
    ):
        raise ValueError("canonical lineage requires a successful provider receipt")
    for linked, label in (
        (parent, "parent"),
        (retry, "retry"),
        (provider_receipt, "provider receipt"),
        (expanded_from, "expanded_from"),
        *((item, "component provider receipt") for item in component_receipts),
    ):
        if linked is None:
            continue
        if (
            linked.tenant_id != write.tenant_id
            or linked.taxpayer_id != write.taxpayer_id
            or linked.document_id != write.document_id
            or linked.source_file_id != write.source_file_id
            or linked.source_file_sha256 != write.source_file_sha256
        ):
            raise ValueError(f"document AI artifact {label} lineage scope mismatch")
    if retry is not None:
        if write.kind is not ArtifactKind.PROVIDER_RECEIPT or retry.kind is not ArtifactKind.PROVIDER_RECEIPT:
            raise ValueError("retry lineage is only valid between provider receipts")
    if provider_receipt is not None and provider_receipt.kind is not ArtifactKind.PROVIDER_RECEIPT:
        raise ValueError("typed provider receipt lineage must reference a provider receipt")
    if provider_receipt is not None and provider_receipt.status != "successful":
        raise ValueError("typed provider receipt lineage requires a successful provider receipt")
    for component_receipt in component_receipts:
        if component_receipt.kind is not ArtifactKind.PROVIDER_RECEIPT:
            raise ValueError("component receipt lineage must reference provider receipts")
        if component_receipt.stage != "accounting_selection":
            raise ValueError("component receipt lineage must reference accounting selection receipts")
        if component_receipt.status != "successful":
            raise ValueError("component receipt lineage requires successful provider receipts")
    if expanded_from is not None and expanded_from.kind is not ArtifactKind.PROVIDER_RECEIPT:
        raise ValueError("expanded_from lineage must reference a provider receipt")
    if write.kind is ArtifactKind.ACCOUNTING_PROPOSAL and provider_receipt is None:
        raise ValueError("accounting proposal requires typed provider receipt lineage")
    if write.kind is ArtifactKind.CANONICAL_INVOICE_FORM and provider_receipt is not None:
        if parent is None or provider_receipt.artifact_id != parent.artifact_id:
            raise ValueError("canonical typed provider receipt must match its parent receipt")
        if provider_receipt.stage != "document_extraction":
            raise ValueError("canonical provider receipt must be document_extraction stage")
    if (
        write.kind is ArtifactKind.ACCOUNTING_INPUT_PROJECTION
        and provider_receipt is not None
    ):
        raise ValueError("accounting projection does not have a provider receipt call")
    if (
        write.kind is ArtifactKind.ACCOUNTING_PROPOSAL
        and provider_receipt is not None
        and provider_receipt.stage != "accounting_selection"
    ):
        raise ValueError("accounting proposal provider receipt must be accounting_selection stage")
    if expanded_from is not None and expanded_from.stage != "accounting_selection":
        raise ValueError("expanded_from receipt must be accounting_selection stage")
    if expanded_from is not None and expanded_from.status != "successful":
        raise ValueError("expanded_from receipt must be successful")


def _process_lock_for(path: Path) -> RLock:
    key = str(path.resolve())
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, RLock())


@contextmanager
def _cross_process_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_artifact_bodies(
    storage: DocumentStorageAdapter,
    write: ArtifactWrite,
    artifact_id: str,
    *,
    content: bytes | None,
    request_body: bytes | None,
    response_body: bytes | None,
) -> dict[str, str | None]:
    values: dict[str, str | None] = {
        "content_storage_path": None,
        "content_sha256": None,
        "request_storage_path": None,
        "request_sha256": None,
        "response_storage_path": None,
        "response_sha256": None,
    }
    items = (
        ("content", content),
        ("request", request_body),
        ("response", response_body),
    )
    for label, body in items:
        if body is None:
            continue
        stored = storage.write_bytes(
            client_key=write.taxpayer_id,
            document_id=write.document_id,
            file_name=f"ai-artifact-{artifact_id}.{label}.body",
            content=body,
        )
        values[f"{label}_storage_path"] = stored.path
        values[f"{label}_sha256"] = _sha256(body)
    return values


def _delete_written_paths(storage: DocumentStorageAdapter, paths: Iterable[str | None]) -> None:
    for path in paths:
        if path:
            storage.delete(path)


class LocalDocumentAiArtifactRepository:
    def __init__(self, *, manifest_path: Path, storage: DocumentStorageAdapter) -> None:
        self.manifest_path = Path(manifest_path)
        self.storage = storage
        self._lock_path = self.manifest_path.with_suffix(self.manifest_path.suffix + ".lock")
        self._process_lock = _process_lock_for(self._lock_path)

    def append(
        self,
        write: ArtifactWrite,
        *,
        content: bytes | None = None,
        request_body: bytes | None = None,
        response_body: bytes | None = None,
    ) -> DocumentAiArtifact:
        validate_artifact_write(write)
        _validate_bytes(
            write,
            content=content,
            request_body=request_body,
            response_body=response_body,
        )
        with self._manifest_fence():
            records = self._load_unlocked()
            if write.artifact_id and any(item.artifact_id == write.artifact_id for item in records):
                raise ValueError("document AI artifacts are append-only; artifact_id already exists")
            parent = self._find(records, write.parent_artifact_id)
            retry = self._find(records, write.retry_of_artifact_id)
            provider_receipt = self._find(records, write.provider_receipt_artifact_id)
            component_receipts = tuple(
                item
                for artifact_id in write.component_receipt_artifact_ids
                for item in (self._find(records, artifact_id),)
                if item is not None
            )
            expanded_from = self._find(records, write.expanded_from_receipt_id)
            if write.parent_artifact_id and parent is None:
                raise ValueError("document AI artifact lineage parent does not exist")
            if write.retry_of_artifact_id and retry is None:
                raise ValueError("document AI artifact retry lineage does not exist")
            if write.provider_receipt_artifact_id and provider_receipt is None:
                raise ValueError("typed provider receipt lineage does not exist")
            if len(component_receipts) != len(write.component_receipt_artifact_ids):
                raise ValueError("component receipt lineage does not exist")
            if write.expanded_from_receipt_id and expanded_from is None:
                raise ValueError("expanded_from receipt lineage does not exist")
            _validate_lineage(
                write,
                parent=parent,
                retry=retry,
                provider_receipt=provider_receipt,
                component_receipts=component_receipts,
                expanded_from=expanded_from,
            )
            revision_no = 1 + max(
                (
                    item.revision_no
                    for item in records
                    if item.tenant_id == write.tenant_id
                    and item.taxpayer_id == write.taxpayer_id
                    and item.document_id == write.document_id
                    and item.kind is write.kind
                ),
                default=0,
            )
            artifact_id = write.artifact_id or str(uuid4())
            body_fields = _write_artifact_bodies(
                self.storage,
                write,
                artifact_id,
                content=content,
                request_body=request_body,
                response_body=response_body,
            )
            record = DocumentAiArtifact(
                artifact_id=artifact_id,
                revision_no=revision_no,
                created_at=datetime.now(UTC).isoformat(),
                tenant_id=write.tenant_id,
                taxpayer_id=write.taxpayer_id,
                document_id=write.document_id,
                source_file_id=write.source_file_id,
                source_file_sha256=write.source_file_sha256,
                kind=write.kind,
                stage=write.stage,
                status=write.status,
                pipeline_version=write.pipeline_version,
                credential_slot=write.credential_slot,
                parent_artifact_id=write.parent_artifact_id,
                retry_of_artifact_id=write.retry_of_artifact_id,
                provider_receipt_artifact_id=write.provider_receipt_artifact_id,
                component_receipt_artifact_ids=write.component_receipt_artifact_ids,
                expanded_from_receipt_id=write.expanded_from_receipt_id,
                provider=write.provider,
                model_alias=write.model_alias,
                resolved_model=write.resolved_model,
                prompt_version=write.prompt_version,
                schema_version=write.schema_version,
                mapper_version=write.mapper_version,
                elapsed_ms=write.elapsed_ms,
                http_status=write.http_status,
                started_at=write.started_at,
                finished_at=write.finished_at,
                token_usage=dict(write.token_usage),
                error_metadata=dict(write.error_metadata),
                metadata=dict(write.metadata),
                **body_fields,
            )
            try:
                self._save_unlocked([*records, record])
            except Exception:
                _delete_written_paths(
                    self.storage,
                    (
                        record.content_storage_path,
                        record.request_storage_path,
                        record.response_storage_path,
                    ),
                )
                raise
            return record

    def get(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> DocumentAiArtifact:
        with self._manifest_fence():
            record = self._find(self._load_unlocked(), artifact_id)
            if record is not None and (
                record.tenant_id != tenant_id or record.taxpayer_id != taxpayer_id
            ):
                record = None
        if record is None:
            raise KeyError(f"document AI artifact not found: {artifact_id}")
        return record

    def list_for_document(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        document_id: str,
        kind: ArtifactKind | None = None,
    ) -> list[DocumentAiArtifact]:
        with self._manifest_fence():
            records = self._load_unlocked()
        return sorted(
            (
                item
                for item in records
                if item.tenant_id == tenant_id
                and item.taxpayer_id == taxpayer_id
                and item.document_id == document_id
                and (kind is None or item.kind is kind)
            ),
            key=lambda item: (item.created_at, item.revision_no),
        )

    def latest_successful(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        document_id: str,
        kind: ArtifactKind,
    ) -> DocumentAiArtifact | None:
        successful = [
            item
            for item in self.list_for_document(
                tenant_id=tenant_id,
                taxpayer_id=taxpayer_id,
                document_id=document_id,
                kind=kind,
            )
            if item.status == "successful"
        ]
        return successful[-1] if successful else None

    def trace_lineage(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> list[DocumentAiArtifact]:
        with self._manifest_fence():
            records = {
                item.artifact_id: item
                for item in self._load_unlocked()
                if item.tenant_id == tenant_id and item.taxpayer_id == taxpayer_id
            }
        current = records.get(artifact_id)
        if current is None:
            raise KeyError(f"document AI artifact not found: {artifact_id}")
        lineage: list[DocumentAiArtifact] = []
        seen: set[str] = set()
        while current is not None:
            if current.artifact_id in seen:
                raise ValueError("document AI artifact lineage cycle")
            seen.add(current.artifact_id)
            lineage.append(current)
            current = records.get(current.parent_artifact_id or "")
        return list(reversed(lineage))

    def read_content(self, *, tenant_id: str, taxpayer_id: str, artifact_id: str) -> bytes:
        record = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        return self._read_path(record.content_storage_path, record.content_sha256, "content")

    def read_request_body(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> bytes:
        record = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        return self._read_path(record.request_storage_path, record.request_sha256, "request")

    def read_response_body(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> bytes:
        record = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        return self._read_path(record.response_storage_path, record.response_sha256, "response")

    def delete_raw_bodies_for_source(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        source_file_id: str,
    ) -> int:
        deleted = 0
        with self._manifest_fence():
            records = self._load_unlocked()
            for record in records:
                if (
                    record.kind is not ArtifactKind.PROVIDER_RECEIPT
                    or record.tenant_id != tenant_id
                    or record.taxpayer_id != taxpayer_id
                    or record.source_file_id != source_file_id
                ):
                    continue
                for path in (record.request_storage_path, record.response_storage_path):
                    if path and self.storage.delete(path):
                        deleted += 1
        return deleted

    def _load_unlocked(self) -> list[DocumentAiArtifact]:
        if not self.manifest_path.exists():
            return []
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("document AI artifact manifest must be a list")
        return [_record_from_dict(dict(item)) for item in payload]

    def _save_unlocked(self, records: list[DocumentAiArtifact]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.manifest_path.parent,
                prefix=f".{self.manifest_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    [_record_to_dict(item) for item in records],
                    temporary,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.manifest_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @contextmanager
    def _manifest_fence(self):
        with self._process_lock:
            with _cross_process_file_lock(self._lock_path):
                yield

    @staticmethod
    def _find(
        records: Iterable[DocumentAiArtifact], artifact_id: str | None
    ) -> DocumentAiArtifact | None:
        if artifact_id is None:
            return None
        return next((item for item in records if item.artifact_id == artifact_id), None)

    @staticmethod
    def _read_path(path: str | None, expected_sha256: str | None, label: str) -> bytes:
        if path is None:
            raise ValueError(f"document AI artifact has no {label} body")
        content = Path(path).read_bytes()
        actual_sha256 = _sha256(content)
        if expected_sha256 is None or actual_sha256 != expected_sha256:
            raise ValueError(f"document AI artifact {label} sha256 mismatch")
        return content


class PostgresDocumentAiArtifactRepository:
    def __init__(self, *, dsn: str, storage: DocumentStorageAdapter) -> None:
        self.dsn = dsn
        self.storage = storage

    def append(
        self,
        write: ArtifactWrite,
        *,
        content: bytes | None = None,
        request_body: bytes | None = None,
        response_body: bytes | None = None,
    ) -> DocumentAiArtifact:
        validate_artifact_write(write)
        _validate_bytes(
            write,
            content=content,
            request_body=request_body,
            response_body=response_body,
        )
        import psycopg

        artifact_id = write.artifact_id or str(uuid4())
        body_fields: dict[str, str | None] | None = None
        try:
            with psycopg.connect(self.dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "select pg_advisory_xact_lock(hashtext(%s))",
                        (f"{write.tenant_id}:{write.taxpayer_id}:{write.document_id}:{write.kind.value}",),
                    )
                    if self._get_with_cursor(cursor, artifact_id) is not None:
                        raise ValueError(
                            "document AI artifacts are append-only; artifact_id already exists"
                        )
                    parent = self._get_with_cursor(cursor, write.parent_artifact_id)
                    retry = self._get_with_cursor(cursor, write.retry_of_artifact_id)
                    provider_receipt = self._get_with_cursor(
                        cursor, write.provider_receipt_artifact_id
                    )
                    component_receipts = tuple(
                        item
                        for component_id in write.component_receipt_artifact_ids
                        for item in (self._get_with_cursor(cursor, component_id),)
                        if item is not None
                    )
                    expanded_from = self._get_with_cursor(
                        cursor, write.expanded_from_receipt_id
                    )
                    if write.parent_artifact_id and parent is None:
                        raise ValueError("document AI artifact lineage parent does not exist")
                    if write.retry_of_artifact_id and retry is None:
                        raise ValueError("document AI artifact retry lineage does not exist")
                    if write.provider_receipt_artifact_id and provider_receipt is None:
                        raise ValueError("typed provider receipt lineage does not exist")
                    if len(component_receipts) != len(write.component_receipt_artifact_ids):
                        raise ValueError("component receipt lineage does not exist")
                    if write.expanded_from_receipt_id and expanded_from is None:
                        raise ValueError("expanded_from receipt lineage does not exist")
                    _validate_lineage(
                        write,
                        parent=parent,
                        retry=retry,
                        provider_receipt=provider_receipt,
                        component_receipts=component_receipts,
                        expanded_from=expanded_from,
                    )
                    cursor.execute(
                        """
                        select coalesce(max(revision_no), 0) + 1
                        from document_ai_artifacts
                        where tenant_id = %s and taxpayer_id = %s and document_id = %s
                          and artifact_kind = %s
                        """,
                        (write.tenant_id, write.taxpayer_id, write.document_id, write.kind.value),
                    )
                    revision_no = int(cursor.fetchone()[0])
                    body_fields = _write_artifact_bodies(
                        self.storage,
                        write,
                        artifact_id,
                        content=content,
                        request_body=request_body,
                        response_body=response_body,
                    )
                    cursor.execute(
                        """
                        insert into document_ai_artifacts (
                            id, tenant_id, taxpayer_id, document_id, source_file_id,
                            artifact_kind, revision_no, parent_artifact_id, retry_of_artifact_id,
                            provider_receipt_artifact_id, component_receipt_artifact_ids,
                            expanded_from_receipt_id,
                            stage, status, provider, model_alias, resolved_model, elapsed_ms,
                            http_status, started_at, finished_at,
                            token_usage, error_metadata, metadata, source_file_sha256,
                            content_storage_path, content_sha256, request_storage_path, request_sha256,
                            response_storage_path, response_sha256, prompt_version, schema_version,
                            mapper_version, pipeline_version, credential_slot
                        ) values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s::jsonb, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        returning created_at
                        """,
                        (
                            artifact_id,
                            write.tenant_id,
                            write.taxpayer_id,
                            write.document_id,
                            write.source_file_id,
                            write.kind.value,
                            revision_no,
                            write.parent_artifact_id,
                            write.retry_of_artifact_id,
                            write.provider_receipt_artifact_id,
                            list(write.component_receipt_artifact_ids),
                            write.expanded_from_receipt_id,
                            write.stage,
                            write.status,
                            write.provider,
                            write.model_alias,
                            write.resolved_model,
                            write.elapsed_ms,
                            write.http_status,
                            write.started_at,
                            write.finished_at,
                            json.dumps(write.token_usage),
                            json.dumps(write.error_metadata),
                            json.dumps(write.metadata),
                            write.source_file_sha256,
                            body_fields["content_storage_path"],
                            body_fields["content_sha256"],
                            body_fields["request_storage_path"],
                            body_fields["request_sha256"],
                            body_fields["response_storage_path"],
                            body_fields["response_sha256"],
                            write.prompt_version,
                            write.schema_version,
                            write.mapper_version,
                            write.pipeline_version,
                            write.credential_slot,
                        ),
                    )
                    created_at = cursor.fetchone()[0]
            return DocumentAiArtifact(
                artifact_id=artifact_id,
                revision_no=revision_no,
                created_at=created_at.isoformat(),
                tenant_id=write.tenant_id,
                taxpayer_id=write.taxpayer_id,
                document_id=write.document_id,
                source_file_id=write.source_file_id,
                source_file_sha256=write.source_file_sha256,
                kind=write.kind,
                stage=write.stage,
                status=write.status,
                pipeline_version=write.pipeline_version,
                credential_slot=write.credential_slot,
                parent_artifact_id=write.parent_artifact_id,
                retry_of_artifact_id=write.retry_of_artifact_id,
                provider_receipt_artifact_id=write.provider_receipt_artifact_id,
                component_receipt_artifact_ids=write.component_receipt_artifact_ids,
                expanded_from_receipt_id=write.expanded_from_receipt_id,
                provider=write.provider,
                model_alias=write.model_alias,
                resolved_model=write.resolved_model,
                prompt_version=write.prompt_version,
                schema_version=write.schema_version,
                mapper_version=write.mapper_version,
                elapsed_ms=write.elapsed_ms,
                http_status=write.http_status,
                started_at=write.started_at,
                finished_at=write.finished_at,
                token_usage=dict(write.token_usage),
                error_metadata=dict(write.error_metadata),
                metadata=dict(write.metadata),
                **body_fields,
            )
        except Exception:
            if body_fields is not None:
                _delete_written_paths(
                    self.storage,
                    (
                        body_fields["content_storage_path"],
                        body_fields["request_storage_path"],
                        body_fields["response_storage_path"],
                    ),
                )
            raise

    def get(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> DocumentAiArtifact:
        import psycopg

        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select {self._SELECT_COLUMNS}
                    from document_ai_artifacts
                    where id = %s and tenant_id = %s and taxpayer_id = %s
                    """,
                    (artifact_id, tenant_id, taxpayer_id),
                )
                row = cursor.fetchone()
                record = self._from_row(row) if row else None
        if record is None:
            raise KeyError(f"document AI artifact not found: {artifact_id}")
        return record

    def list_for_document(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        document_id: str,
        kind: ArtifactKind | None = None,
    ) -> list[DocumentAiArtifact]:
        import psycopg

        query = f"""
            select {self._SELECT_COLUMNS}
            from document_ai_artifacts
            where tenant_id = %s and taxpayer_id = %s and document_id = %s
            {"and artifact_kind = %s" if kind is not None else ""}
            order by created_at, revision_no
        """
        parameters: tuple[object, ...] = (tenant_id, taxpayer_id, document_id)
        if kind is not None:
            parameters = (*parameters, kind.value)
        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return [self._from_row(row) for row in cursor.fetchall()]

    def latest_successful(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        document_id: str,
        kind: ArtifactKind,
    ) -> DocumentAiArtifact | None:
        records = self.list_for_document(
            tenant_id=tenant_id,
            taxpayer_id=taxpayer_id,
            document_id=document_id,
            kind=kind,
        )
        successful = [item for item in records if item.status == "successful"]
        return successful[-1] if successful else None

    def trace_lineage(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> list[DocumentAiArtifact]:
        lineage: list[DocumentAiArtifact] = []
        seen: set[str] = set()
        current = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        while current is not None:
            if current.artifact_id in seen:
                raise ValueError("document AI artifact lineage cycle")
            seen.add(current.artifact_id)
            lineage.append(current)
            current = (
                self.get(
                    tenant_id=tenant_id,
                    taxpayer_id=taxpayer_id,
                    artifact_id=current.parent_artifact_id,
                )
                if current.parent_artifact_id
                else None
            )
        return list(reversed(lineage))

    def read_content(self, *, tenant_id: str, taxpayer_id: str, artifact_id: str) -> bytes:
        record = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        return LocalDocumentAiArtifactRepository._read_path(
            record.content_storage_path, record.content_sha256, "content"
        )

    def read_request_body(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> bytes:
        record = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        return LocalDocumentAiArtifactRepository._read_path(
            record.request_storage_path, record.request_sha256, "request"
        )

    def read_response_body(
        self, *, tenant_id: str, taxpayer_id: str, artifact_id: str
    ) -> bytes:
        record = self.get(
            tenant_id=tenant_id, taxpayer_id=taxpayer_id, artifact_id=artifact_id
        )
        return LocalDocumentAiArtifactRepository._read_path(
            record.response_storage_path, record.response_sha256, "response"
        )

    def delete_raw_bodies_for_source(
        self,
        *,
        tenant_id: str,
        taxpayer_id: str,
        source_file_id: str,
    ) -> int:
        import psycopg

        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select request_storage_path, response_storage_path
                    from document_ai_artifacts
                    where tenant_id = %s and taxpayer_id = %s and source_file_id = %s
                      and artifact_kind = 'provider_receipt'
                    """,
                    (tenant_id, taxpayer_id, source_file_id),
                )
                paths = cursor.fetchall()
        return sum(
            1
            for pair in paths
            for path in pair
            if path and self.storage.delete(str(path))
        )

    _SELECT_COLUMNS = """
        id, revision_no, created_at, tenant_id, taxpayer_id, document_id, source_file_id,
        source_file_sha256, artifact_kind, stage, status, pipeline_version, credential_slot,
        parent_artifact_id, retry_of_artifact_id, provider_receipt_artifact_id,
        component_receipt_artifact_ids, expanded_from_receipt_id,
        provider, model_alias, resolved_model,
        prompt_version, schema_version, mapper_version, elapsed_ms, http_status,
        started_at, finished_at, token_usage,
        error_metadata, metadata, content_storage_path, content_sha256,
        request_storage_path, request_sha256, response_storage_path, response_sha256
    """

    @classmethod
    def _get_with_cursor(cls, cursor: object, artifact_id: str | None) -> DocumentAiArtifact | None:
        if artifact_id is None:
            return None
        cursor.execute(
            f"select {cls._SELECT_COLUMNS} from document_ai_artifacts where id = %s",
            (artifact_id,),
        )
        row = cursor.fetchone()
        return cls._from_row(row) if row else None

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> DocumentAiArtifact:
        return DocumentAiArtifact(
            artifact_id=str(row[0]),
            revision_no=int(row[1]),
            created_at=row[2].isoformat(),
            tenant_id=str(row[3]),
            taxpayer_id=str(row[4]),
            document_id=str(row[5]),
            source_file_id=str(row[6]),
            source_file_sha256=str(row[7]),
            kind=ArtifactKind(str(row[8])),
            stage=str(row[9]),
            status=str(row[10]),
            pipeline_version=str(row[11] or ""),
            credential_slot=str(row[12] or ""),
            parent_artifact_id=str(row[13]) if row[13] else None,
            retry_of_artifact_id=str(row[14]) if row[14] else None,
            provider_receipt_artifact_id=str(row[15]) if row[15] else None,
            component_receipt_artifact_ids=tuple(str(value) for value in (row[16] or ())),
            expanded_from_receipt_id=str(row[17]) if row[17] else None,
            provider=str(row[18]) if row[18] else None,
            model_alias=str(row[19]) if row[19] else None,
            resolved_model=str(row[20]) if row[20] else None,
            prompt_version=str(row[21]) if row[21] else None,
            schema_version=str(row[22]) if row[22] else None,
            mapper_version=str(row[23]) if row[23] else None,
            elapsed_ms=int(row[24]) if row[24] is not None else None,
            http_status=int(row[25]) if row[25] is not None else None,
            started_at=row[26],
            finished_at=row[27],
            token_usage=dict(row[28] or {}),
            error_metadata=dict(row[29] or {}),
            metadata=dict(row[30] or {}),
            content_storage_path=str(row[31]) if row[31] else None,
            content_sha256=str(row[32]) if row[32] else None,
            request_storage_path=str(row[33]) if row[33] else None,
            request_sha256=str(row[34]) if row[34] else None,
            response_storage_path=str(row[35]) if row[35] else None,
            response_sha256=str(row[36]) if row[36] else None,
        )
