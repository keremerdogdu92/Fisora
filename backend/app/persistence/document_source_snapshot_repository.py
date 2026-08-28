# File: backend/app/persistence/document_source_snapshot_repository.py
# Summary: Persists immutable DocumentSourceSnapshot payloads in PostgreSQL with tenant/document/source lineage enforcement.
from __future__ import annotations

from typing import Any, Callable
from uuid import UUID, uuid4

from app.domain.document_source_snapshots import DocumentSourceSnapshotWrite


ConnectFactory = Callable[[], Any]


class DocumentSourceSnapshotConflict(RuntimeError):
    """Raised when the same source/version scope produces different snapshot bytes."""


class PostgresDocumentSourceSnapshotRepository:
    def __init__(
        self,
        *,
        connect: ConnectFactory,
        tenant_id: UUID,
        json_value: Callable[[Any], Any],
    ) -> None:
        self._connect = connect
        self.tenant_id = tenant_id
        self._json = json_value

    def save(self, write: DocumentSourceSnapshotWrite) -> dict[str, Any]:
        write.validated()
        payload_hash = write.payload_sha256
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (
                        f"source-snapshot:{write.tenant_id}:{write.taxpayer_id}:"
                        f"{write.document_id}:{write.source_file_id}:{write.snapshot_version}:{write.reader_version}",
                    ),
                )
                cursor.execute(
                    """
                    insert into document_source_snapshots (
                        id, tenant_id, taxpayer_id, document_id, source_file_id,
                        source_file_sha256, snapshot_version, reader_version,
                        parser_kind, snapshot_sha256, payload
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (
                        tenant_id, taxpayer_id, document_id, source_file_id,
                        snapshot_version, reader_version
                    ) do nothing
                    returning id, created_at
                    """,
                    (
                        uuid4(), write.tenant_id, write.taxpayer_id, write.document_id,
                        write.source_file_id, write.source_file_sha256, write.snapshot_version,
                        write.reader_version, write.parser_kind, payload_hash,
                        self._json(write.snapshot),
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute(
                        """
                        select id, snapshot_sha256, payload, created_at
                        from document_source_snapshots
                        where tenant_id = %s and taxpayer_id = %s
                          and document_id = %s and source_file_id = %s
                          and snapshot_version = %s and reader_version = %s
                        """,
                        (
                            write.tenant_id, write.taxpayer_id, write.document_id,
                            write.source_file_id, write.snapshot_version, write.reader_version,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None or str(row[1]) != payload_hash:
                        raise DocumentSourceSnapshotConflict(
                            "immutable source snapshot conflicts with existing release output"
                        )
                    return {
                        "id": str(row[0]),
                        "snapshot_sha256": str(row[1]),
                        "payload": dict(row[2] or {}),
                        "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                        "created": False,
                    }
                return {
                    "id": str(inserted[0]),
                    "snapshot_sha256": payload_hash,
                    "payload": dict(write.snapshot),
                    "created_at": inserted[1].isoformat() if hasattr(inserted[1], "isoformat") else str(inserted[1]),
                    "created": True,
                }

    def latest_for_document_ref(self, *, taxpayer_id: str, document_ref: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select s.id, s.snapshot_sha256, s.snapshot_version, s.reader_version,
                           s.parser_kind, s.payload, s.created_at
                    from document_source_snapshots s
                    join documents d on d.id = s.document_id
                    where s.tenant_id = %s and s.taxpayer_id = %s
                      and d.tenant_id = s.tenant_id and d.taxpayer_id = s.taxpayer_id
                      and d.source_ref = %s
                    order by s.created_at desc
                    limit 1
                    """,
                    (self.tenant_id, taxpayer_id, document_ref),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "snapshot_sha256": str(row[1]),
            "snapshot_version": str(row[2]),
            "reader_version": str(row[3]),
            "parser_kind": str(row[4]),
            "payload": dict(row[5] or {}),
            "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
        }
