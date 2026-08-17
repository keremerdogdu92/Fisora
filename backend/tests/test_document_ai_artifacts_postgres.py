from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apply_migrations import apply_migrations, discover_migrations
from app.domain.document_ai_artifacts import ArtifactKind, ArtifactWrite
from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import PostgresDocumentAiArtifactRepository


POSTGRES_DSN = os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip()


@unittest.skipUnless(
    POSTGRES_DSN,
    "set FISORA_TEST_POSTGRES_DSN to run document AI artifact PostgreSQL tests",
)
class DocumentAiArtifactPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_migrations(POSTGRES_DSN, discover_migrations(BACKEND / "db" / "migrations"))

    def setUp(self) -> None:
        import psycopg

        suffix = uuid4().hex
        self.tenant_id = str(uuid4())
        self.taxpayer_id = str(uuid4())
        self.document_id = str(uuid4())
        self.source_file_id = str(uuid4())
        self.source_sha256 = hashlib.sha256(suffix.encode("utf-8")).hexdigest()
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "insert into tenants (id, name) values (%s, %s)",
                    (self.tenant_id, f"Artifact tenant {suffix}"),
                )
                cursor.execute(
                    "insert into taxpayers (id, tenant_id, display_name) values (%s, %s, %s)",
                    (self.taxpayer_id, self.tenant_id, f"Artifact client {suffix}"),
                )
                cursor.execute(
                    """
                    insert into documents
                        (id, tenant_id, taxpayer_id, source_filename, document_type)
                    values (%s, %s, %s, %s, 'invoice_pdf')
                    """,
                    (self.document_id, self.tenant_id, self.taxpayer_id, f"{suffix}.pdf"),
                )
                cursor.execute(
                    """
                    insert into source_files
                        (id, tenant_id, taxpayer_id, source_ref, original_filename,
                         storage_path, sha256)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.source_file_id,
                        self.tenant_id,
                        self.taxpayer_id,
                        f"source-{suffix}",
                        f"{suffix}.pdf",
                        f"/tmp/{suffix}.pdf",
                        self.source_sha256,
                    ),
                )
                cursor.execute(
                    """
                    insert into document_sources
                        (id, tenant_id, taxpayer_id, document_id, source_file_id,
                         relationship_type, is_canonical)
                    values (%s, %s, %s, %s, %s, 'canonical', true)
                    """,
                    (
                        str(uuid4()),
                        self.tenant_id,
                        self.taxpayer_id,
                        self.document_id,
                        self.source_file_id,
                    ),
                )
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = PostgresDocumentAiArtifactRepository(
            dsn=POSTGRES_DSN,
            storage=LocalDocumentStorage(Path(self.temporary.name)),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, kind: ArtifactKind, *, parent_artifact_id: str | None = None) -> ArtifactWrite:
        started_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
        return ArtifactWrite(
            tenant_id=self.tenant_id,
            taxpayer_id=self.taxpayer_id,
            document_id=self.document_id,
            source_file_id=self.source_file_id,
            source_file_sha256=self.source_sha256,
            kind=kind,
            stage="document_extraction",
            status="successful",
            parent_artifact_id=parent_artifact_id,
            provider="gemini" if kind is ArtifactKind.PROVIDER_RECEIPT else None,
            http_status=200 if kind is ArtifactKind.PROVIDER_RECEIPT else None,
            started_at=started_at if kind is ArtifactKind.PROVIDER_RECEIPT else None,
            finished_at=(started_at + timedelta(milliseconds=50))
            if kind is ArtifactKind.PROVIDER_RECEIPT
            else None,
            pipeline_version="gemini-two-stage-v1",
        )

    def test_postgres_enforces_tenant_lineage_and_append_only_revisions(self) -> None:
        import psycopg

        receipt = self.repository.append(
            self._write(ArtifactKind.PROVIDER_RECEIPT),
            request_body=b'{"request":1}',
            response_body=b'{"response":1}',
        )
        canonical = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(
                        ArtifactKind.CANONICAL_INVOICE_FORM,
                        parent_artifact_id=receipt.artifact_id,
                    ).__dict__,
                    "provider_receipt_artifact_id": receipt.artifact_id,
                }
            ),
            content=b'{"invoice_id":"INV-1"}',
        )
        projection = self.repository.append(
            self._write(
                ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                parent_artifact_id=canonical.artifact_id,
            ),
            content=b'{"canonical_line_ids":["line-1"]}',
        )
        accounting_receipt = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                    "stage": "accounting_selection",
                }
            ),
            request_body=b'{"accounting":1}',
            response_body=b'{"proposal":1}',
        )
        proposal = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(
                        ArtifactKind.ACCOUNTING_PROPOSAL,
                        parent_artifact_id=projection.artifact_id,
                    ).__dict__,
                    "provider_receipt_artifact_id": accounting_receipt.artifact_id,
                }
            ),
            content=b'{"action":"select_existing"}',
        )
        expanded_receipt = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                    "stage": "accounting_selection",
                    "expanded_from_receipt_id": accounting_receipt.artifact_id,
                }
            ),
            request_body=b'{"accounting":2}',
            response_body=b'{"proposal":2}',
        )

        with self.assertRaisesRegex(ValueError, "canonical.*document_extraction"):
            self.repository.append(
                ArtifactWrite(
                    **{
                        **self._write(
                            ArtifactKind.CANONICAL_INVOICE_FORM,
                            parent_artifact_id=accounting_receipt.artifact_id,
                        ).__dict__,
                        "provider_receipt_artifact_id": accounting_receipt.artifact_id,
                    }
                ),
                content=b"{}",
            )
        with self.assertRaisesRegex(ValueError, "proposal.*accounting_selection"):
            self.repository.append(
                ArtifactWrite(
                    **{
                        **self._write(
                            ArtifactKind.ACCOUNTING_PROPOSAL,
                            parent_artifact_id=projection.artifact_id,
                        ).__dict__,
                        "provider_receipt_artifact_id": receipt.artifact_id,
                    }
                ),
                content=b"{}",
            )
        with self.assertRaisesRegex(ValueError, "expanded_from.*accounting_selection"):
            self.repository.append(
                ArtifactWrite(
                    **{
                        **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                        "stage": "accounting_selection",
                        "expanded_from_receipt_id": receipt.artifact_id,
                    }
                ),
                request_body=b"{}",
                response_body=b"{}",
            )

        invalid_sql_rows = (
            (
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, parent_artifact_id,
                     provider_receipt_artifact_id, stage, status, source_file_sha256,
                     content_storage_path, content_sha256)
                values (%s, %s, %s, %s, %s, 'canonical_invoice_form', 90,
                        %s, %s, 'canonical_mapping', 'successful', %s,
                        '/tmp/canonical', %s)
                """,
                (
                    str(uuid4()), self.tenant_id, self.taxpayer_id, self.document_id,
                    self.source_file_id, accounting_receipt.artifact_id,
                    accounting_receipt.artifact_id, self.source_sha256,
                    hashlib.sha256(b"canonical").hexdigest(),
                ),
            ),
            (
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, parent_artifact_id,
                     provider_receipt_artifact_id, stage, status, source_file_sha256,
                     content_storage_path, content_sha256)
                values (%s, %s, %s, %s, %s, 'accounting_proposal', 90,
                        %s, %s, 'accounting_selection', 'successful', %s,
                        '/tmp/proposal', %s)
                """,
                (
                    str(uuid4()), self.tenant_id, self.taxpayer_id, self.document_id,
                    self.source_file_id, projection.artifact_id, receipt.artifact_id,
                    self.source_sha256, hashlib.sha256(b"proposal").hexdigest(),
                ),
            ),
            (
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, expanded_from_receipt_id,
                     stage, status, source_file_sha256,
                     request_storage_path, request_sha256,
                     response_storage_path, response_sha256)
                values (%s, %s, %s, %s, %s, 'provider_receipt', 90, %s,
                        'accounting_selection', 'successful', %s,
                        '/tmp/request', %s, '/tmp/response', %s)
                """,
                (
                    str(uuid4()), self.tenant_id, self.taxpayer_id, self.document_id,
                    self.source_file_id, receipt.artifact_id, self.source_sha256,
                    hashlib.sha256(b"request").hexdigest(),
                    hashlib.sha256(b"response").hexdigest(),
                ),
            ),
        )
        for statement, parameters in invalid_sql_rows:
            with psycopg.connect(POSTGRES_DSN) as connection:
                with connection.cursor() as cursor:
                    with self.assertRaises(psycopg.errors.RaiseException):
                        cursor.execute(statement, parameters)

        self.assertEqual((receipt.revision_no, canonical.revision_no), (1, 1))
        self.assertEqual(proposal.provider_receipt_artifact_id, accounting_receipt.artifact_id)
        self.assertEqual(expanded_receipt.expanded_from_receipt_id, accounting_receipt.artifact_id)
        self.assertEqual(
            [
                item.artifact_id
                for item in self.repository.trace_lineage(
                    tenant_id=self.tenant_id,
                    taxpayer_id=self.taxpayer_id,
                    artifact_id=canonical.artifact_id,
                )
            ],
            [receipt.artifact_id, canonical.artifact_id],
        )
        with self.assertRaises(KeyError):
            self.repository.get(
                tenant_id=str(uuid4()),
                taxpayer_id=self.taxpayer_id,
                artifact_id=receipt.artifact_id,
            )

        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.errors.RaiseException):
                    cursor.execute(
                        "update document_ai_artifacts set status = 'failed' where id = %s",
                        (receipt.artifact_id,),
                    )
            connection.rollback()
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.errors.RaiseException):
                    cursor.execute("delete from document_ai_artifacts where id = %s", (canonical.artifact_id,))

    def test_postgres_rejects_cross_tenant_source_and_secret_metadata(self) -> None:
        import psycopg

        other_tenant_id = str(uuid4())
        other_taxpayer_id = str(uuid4())
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("insert into tenants (id, name) values (%s, 'Other tenant')", (other_tenant_id,))
                cursor.execute(
                    "insert into taxpayers (id, tenant_id, display_name) values (%s, %s, 'Other client')",
                    (other_taxpayer_id, other_tenant_id),
                )

        with self.assertRaisesRegex(ValueError, "secret-bearing field"):
            self.repository.append(
                ArtifactWrite(
                    **{
                        **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                        "metadata": {"authorization": "Bearer secret"},
                    }
                ),
                request_body=b"{}",
                response_body=b"{}",
            )

        for json_column, secret_payload in (
            ("metadata", '{"transport":{"HeAdErS":{"Authorization":"secret"}}}'),
            ("error_metadata", '{"detail":{"CLIENT_SECRET":"secret"}}'),
            ("token_usage", '{"nested":[{"X-Goog-Api-Key":"secret"}]}'),
        ):
            with self.subTest(json_column=json_column):
                with psycopg.connect(POSTGRES_DSN) as connection:
                    with connection.cursor() as cursor:
                        with self.assertRaises(psycopg.errors.CheckViolation):
                            cursor.execute(
                                f"""
                                insert into document_ai_artifacts
                                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                                     artifact_kind, revision_no, stage, status, source_file_sha256,
                                     request_storage_path, request_sha256,
                                     response_storage_path, response_sha256, {json_column})
                                values (%s, %s, %s, %s, %s, 'provider_receipt', 98,
                                        'document_extraction', 'failed', %s,
                                        '/tmp/request', %s, '/tmp/response', %s, %s::jsonb)
                                """,
                                (
                                    str(uuid4()),
                                    self.tenant_id,
                                    self.taxpayer_id,
                                    self.document_id,
                                    self.source_file_id,
                                    self.source_sha256,
                                    hashlib.sha256(b"request").hexdigest(),
                                    hashlib.sha256(b"response").hexdigest(),
                                    secret_payload,
                                ),
                            )
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.errors.RaiseException):
                    cursor.execute(
                        """
                        insert into document_ai_artifacts
                            (id, tenant_id, taxpayer_id, document_id, source_file_id,
                             artifact_kind, revision_no, stage, status, source_file_sha256,
                             request_storage_path, request_sha256,
                             response_storage_path, response_sha256, metadata)
                        values (%s, %s, %s, %s, %s, 'provider_receipt', 98,
                                'document_extraction', 'failed', %s,
                                '/tmp/request', %s, '/tmp/response', %s, %s::jsonb)
                        """,
                        (
                            str(uuid4()),
                            other_tenant_id,
                            other_taxpayer_id,
                            self.document_id,
                            self.source_file_id,
                            self.source_sha256,
                            hashlib.sha256(b"request").hexdigest(),
                            hashlib.sha256(b"response").hexdigest(),
                            '{}',
                        ),
                    )

    def test_postgres_trigger_rejects_cross_source_hash_for_every_lineage_link(self) -> None:
        import psycopg

        extraction_a = self.repository.append(
            self._write(ArtifactKind.PROVIDER_RECEIPT),
            request_body=b'{"source":"a"}',
            response_body=b'{"source":"a"}',
        )
        canonical_a = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(
                        ArtifactKind.CANONICAL_INVOICE_FORM,
                        parent_artifact_id=extraction_a.artifact_id,
                    ).__dict__,
                    "provider_receipt_artifact_id": extraction_a.artifact_id,
                }
            ),
            content=b'{"source":"a"}',
        )
        accounting_a = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                    "stage": "accounting_selection",
                }
            ),
            request_body=b'{"source":"a"}',
            response_body=b'{"source":"a"}',
        )

        source_hash_b = hashlib.sha256(b"replacement-source").hexdigest()
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "update source_files set sha256 = %s where id = %s",
                    (source_hash_b, self.source_file_id),
                )
        self.source_sha256 = source_hash_b

        extraction_b = self.repository.append(
            self._write(ArtifactKind.PROVIDER_RECEIPT),
            request_body=b'{"source":"b"}',
            response_body=b'{"source":"b"}',
        )
        canonical_b = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(
                        ArtifactKind.CANONICAL_INVOICE_FORM,
                        parent_artifact_id=extraction_b.artifact_id,
                    ).__dict__,
                    "provider_receipt_artifact_id": extraction_b.artifact_id,
                }
            ),
            content=b'{"source":"b"}',
        )
        projection_b = self.repository.append(
            self._write(
                ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                parent_artifact_id=canonical_b.artifact_id,
            ),
            content=b'{"source":"b"}',
        )

        request_hash = hashlib.sha256(b"request").hexdigest()
        response_hash = hashlib.sha256(b"response").hexdigest()
        content_hash = hashlib.sha256(b"content").hexdigest()
        invalid_sql_rows = (
            (
                "parent",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, parent_artifact_id, stage, status,
                     source_file_sha256, content_storage_path, content_sha256)
                values (%s, %s, %s, %s, %s, 'accounting_input_projection', 91,
                        %s, 'accounting_projection', 'successful', %s,
                        '/tmp/content', %s)
                """,
                (canonical_a.artifact_id, source_hash_b, content_hash),
            ),
            (
                "provider_receipt",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, parent_artifact_id,
                     provider_receipt_artifact_id, stage, status, source_file_sha256,
                     content_storage_path, content_sha256)
                values (%s, %s, %s, %s, %s, 'accounting_proposal', 92,
                        %s, %s, 'accounting_selection', 'successful', %s,
                        '/tmp/content', %s)
                """,
                (
                    projection_b.artifact_id,
                    accounting_a.artifact_id,
                    source_hash_b,
                    content_hash,
                ),
            ),
            (
                "retry",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, retry_of_artifact_id, stage, status,
                     source_file_sha256, request_storage_path, request_sha256,
                     response_storage_path, response_sha256)
                values (%s, %s, %s, %s, %s, 'provider_receipt', 93,
                        %s, 'document_extraction', 'failed', %s,
                        '/tmp/request', %s, '/tmp/response', %s)
                """,
                (
                    extraction_a.artifact_id,
                    source_hash_b,
                    request_hash,
                    response_hash,
                ),
            ),
            (
                "expanded_from",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, expanded_from_receipt_id, stage, status,
                     source_file_sha256, request_storage_path, request_sha256,
                     response_storage_path, response_sha256)
                values (%s, %s, %s, %s, %s, 'provider_receipt', 94,
                        %s, 'accounting_selection', 'failed', %s,
                        '/tmp/request', %s, '/tmp/response', %s)
                """,
                (
                    accounting_a.artifact_id,
                    source_hash_b,
                    request_hash,
                    response_hash,
                ),
            ),
        )
        for label, statement, link_parameters in invalid_sql_rows:
            with self.subTest(link=label):
                parameters = (
                    str(uuid4()),
                    self.tenant_id,
                    self.taxpayer_id,
                    self.document_id,
                    self.source_file_id,
                    *link_parameters,
                )
                with psycopg.connect(POSTGRES_DSN) as connection:
                    with connection.cursor() as cursor:
                        with self.assertRaisesRegex(
                            psycopg.errors.RaiseException,
                            f"scope_mismatch: {label}",
                        ):
                            cursor.execute(statement, parameters)

    def test_postgres_requires_successful_authority_but_allows_retry_of_failure(self) -> None:
        import psycopg

        failed_extraction = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                    "status": "failed",
                    "http_status": 503,
                }
            ),
            request_body=b'{"stage":"extraction"}',
            response_body=b'{"error":"failed"}',
        )
        successful_extraction = self.repository.append(
            self._write(ArtifactKind.PROVIDER_RECEIPT),
            request_body=b'{"stage":"extraction"}',
            response_body=b'{"status":"successful"}',
        )
        canonical = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(
                        ArtifactKind.CANONICAL_INVOICE_FORM,
                        parent_artifact_id=successful_extraction.artifact_id,
                    ).__dict__,
                    "provider_receipt_artifact_id": successful_extraction.artifact_id,
                }
            ),
            content=b"{}",
        )
        projection = self.repository.append(
            self._write(
                ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                parent_artifact_id=canonical.artifact_id,
            ),
            content=b"{}",
        )
        failed_accounting = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                    "stage": "accounting_selection",
                    "status": "failed",
                    "http_status": 503,
                }
            ),
            request_body=b'{"stage":"accounting"}',
            response_body=b'{"error":"failed"}',
        )

        content_hash = hashlib.sha256(b"content").hexdigest()
        request_hash = hashlib.sha256(b"request").hexdigest()
        response_hash = hashlib.sha256(b"response").hexdigest()
        invalid_sql_rows = (
            (
                "canonical_parent_receipt_must_be_successful",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, parent_artifact_id,
                     provider_receipt_artifact_id, stage, status, source_file_sha256,
                     content_storage_path, content_sha256)
                values (%s, %s, %s, %s, %s, 'canonical_invoice_form', 95,
                        %s, %s, 'canonical_mapping', 'successful', %s,
                        '/tmp/content', %s)
                """,
                (
                    failed_extraction.artifact_id,
                    failed_extraction.artifact_id,
                    self.source_sha256,
                    content_hash,
                ),
            ),
            (
                "accounting_proposal_receipt_must_be_successful",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, parent_artifact_id,
                     provider_receipt_artifact_id, stage, status, source_file_sha256,
                     content_storage_path, content_sha256)
                values (%s, %s, %s, %s, %s, 'accounting_proposal', 96,
                        %s, %s, 'accounting_selection', 'successful', %s,
                        '/tmp/content', %s)
                """,
                (
                    projection.artifact_id,
                    failed_accounting.artifact_id,
                    self.source_sha256,
                    content_hash,
                ),
            ),
            (
                "expanded_from_receipt_must_be_successful",
                """
                insert into document_ai_artifacts
                    (id, tenant_id, taxpayer_id, document_id, source_file_id,
                     artifact_kind, revision_no, expanded_from_receipt_id, stage, status,
                     source_file_sha256, request_storage_path, request_sha256,
                     response_storage_path, response_sha256)
                values (%s, %s, %s, %s, %s, 'provider_receipt', 97,
                        %s, 'accounting_selection', 'successful', %s,
                        '/tmp/request', %s, '/tmp/response', %s)
                """,
                (
                    failed_accounting.artifact_id,
                    self.source_sha256,
                    request_hash,
                    response_hash,
                ),
            ),
        )
        for error_code, statement, link_parameters in invalid_sql_rows:
            with self.subTest(error_code=error_code):
                parameters = (
                    str(uuid4()),
                    self.tenant_id,
                    self.taxpayer_id,
                    self.document_id,
                    self.source_file_id,
                    *link_parameters,
                )
                with psycopg.connect(POSTGRES_DSN) as connection:
                    with connection.cursor() as cursor:
                        with self.assertRaisesRegex(
                            psycopg.errors.RaiseException,
                            error_code,
                        ):
                            cursor.execute(statement, parameters)

        recovered = self.repository.append(
            ArtifactWrite(
                **{
                    **self._write(ArtifactKind.PROVIDER_RECEIPT).__dict__,
                    "retry_of_artifact_id": failed_extraction.artifact_id,
                }
            ),
            request_body=b'{"retry":true}',
            response_body=b'{"status":"successful"}',
        )
        self.assertEqual(recovered.retry_of_artifact_id, failed_extraction.artifact_id)


if __name__ == "__main__":
    unittest.main()
