from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_ai_artifacts import ArtifactKind, ArtifactWrite
from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository


def _append_receipt_in_process(manifest_path: str, storage_root: str, index: int) -> None:
    repository = LocalDocumentAiArtifactRepository(
        manifest_path=Path(manifest_path),
        storage=LocalDocumentStorage(Path(storage_root)),
    )
    started_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    repository.append(
        ArtifactWrite(
            tenant_id="tenant-process",
            taxpayer_id="client-process",
            document_id="document-process",
            source_file_id="source-process",
            source_file_sha256=hashlib.sha256(b"process-source").hexdigest(),
            kind=ArtifactKind.PROVIDER_RECEIPT,
            stage="document_extraction",
            status="successful",
            provider="gemini",
            http_status=200,
            started_at=started_at,
            finished_at=started_at + timedelta(milliseconds=index + 1),
        ),
        request_body=f'{{"request":{index}}}'.encode("utf-8"),
        response_body=f'{{"response":{index}}}'.encode("utf-8"),
    )


class DocumentAiArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = LocalDocumentStorage(self.root / "documents")
        self.repository = LocalDocumentAiArtifactRepository(
            manifest_path=self.root / "document-ai-artifacts.json",
            storage=self.storage,
        )
        self.base = {
            "tenant_id": "tenant-1",
            "taxpayer_id": "client-1",
            "document_id": "document-1",
            "source_file_id": "source-1",
            "source_file_sha256": hashlib.sha256(b"%PDF-source").hexdigest(),
            "pipeline_version": "gemini-two-stage-v1",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _receipt(
        self,
        *,
        status: str = "successful",
        retry_of_artifact_id: str | None = None,
        request_body: bytes = b'{"contents":[{"parts":[{"inline_data":"exact"}]}]}',
        response_body: bytes = b'{"candidates":[{"content":"exact"}]}',
        expanded_from_receipt_id: str | None = None,
        stage: str = "document_extraction",
        source_file_sha256: str | None = None,
    ):
        started_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
        return self.repository.append(
            ArtifactWrite(
                **{
                    **self.base,
                    "source_file_sha256": source_file_sha256
                    or self.base["source_file_sha256"],
                },
                kind=ArtifactKind.PROVIDER_RECEIPT,
                stage=stage,
                status=status,
                provider="gemini",
                model_alias="gemini-flash-lite",
                resolved_model="gemini-3.5-flash-lite-2026-07",
                prompt_version="invoice-facts-v1",
                schema_version="canonical-invoice-v1",
                elapsed_ms=1234,
                http_status=200 if status == "successful" else 503,
                started_at=started_at,
                finished_at=started_at + timedelta(milliseconds=1234),
                token_usage={
                    "prompt_tokens": 41,
                    "candidate_tokens": 17,
                    "cached_tokens": 11,
                    "thought_tokens": 3,
                    "total_tokens": 61,
                },
                retry_of_artifact_id=retry_of_artifact_id,
                expanded_from_receipt_id=expanded_from_receipt_id,
            ),
            request_body=request_body,
            response_body=response_body,
        )

    def test_provider_receipt_round_trips_exact_bytes_and_hashes(self) -> None:
        request_body = b'{"unicode":"fatura-\xc3\xb6zel","ordered":[2,1]}'
        response_body = b'{"raw":"provider-response","spacing":  true}'

        receipt = self._receipt(request_body=request_body, response_body=response_body)

        self.assertEqual(receipt.kind, ArtifactKind.PROVIDER_RECEIPT)
        self.assertEqual(receipt.revision_no, 1)
        self.assertEqual(receipt.request_sha256, hashlib.sha256(request_body).hexdigest())
        self.assertEqual(receipt.response_sha256, hashlib.sha256(response_body).hexdigest())
        self.assertEqual(receipt.http_status, 200)
        self.assertEqual(receipt.started_at, datetime(2026, 8, 11, 10, 0, tzinfo=UTC))
        self.assertEqual(
            receipt.finished_at,
            datetime(2026, 8, 11, 10, 0, 1, 234000, tzinfo=UTC),
        )
        self.assertEqual(
            self.repository.read_request_body(
                tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=receipt.artifact_id
            ),
            request_body,
        )
        self.assertEqual(
            self.repository.read_response_body(
                tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=receipt.artifact_id
            ),
            response_body,
        )
        self.assertIn(str(Path("client-1") / "document-1"), receipt.request_storage_path)
        self.assertFalse(hasattr(receipt, "api_key"))
        self.assertFalse(hasattr(receipt, "headers"))
        self.assertEqual(receipt.token_usage["cached_tokens"], 11)
        self.assertEqual(receipt.token_usage["thought_tokens"], 3)

    def test_four_artifacts_are_append_only_and_traceable(self) -> None:
        receipt = self._receipt()
        canonical = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=receipt.artifact_id,
                provider_receipt_artifact_id=receipt.artifact_id,
                schema_version="canonical-invoice-v1",
                mapper_version="gemini-canonical-mapper-v1",
            ),
            content=b'{"invoice_id":"INV-1"}',
        )
        projection = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                stage="accounting_projection",
                status="successful",
                parent_artifact_id=canonical.artifact_id,
                schema_version="accounting-projection-v1",
            ),
            content=b'{"canonical_line_ids":["line-1"]}',
        )
        accounting_receipt = self._receipt(stage="accounting_selection")
        proposal = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                stage="accounting_selection",
                status="successful",
                parent_artifact_id=projection.artifact_id,
                provider_receipt_artifact_id=accounting_receipt.artifact_id,
                provider="gemini",
                resolved_model="gemini-3.5-flash-lite-2026-07",
                prompt_version="accounting-selection-v1",
                schema_version="accounting-proposal-v1",
            ),
            content=b'{"action":"select_existing","candidate_id":"320.01"}',
        )

        lineage = self.repository.trace_lineage(
            tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=proposal.artifact_id
        )

        self.assertEqual(
            [item.kind for item in lineage],
            [
                ArtifactKind.PROVIDER_RECEIPT,
                ArtifactKind.CANONICAL_INVOICE_FORM,
                ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                ArtifactKind.ACCOUNTING_PROPOSAL,
            ],
        )
        self.assertEqual(proposal.provider_receipt_artifact_id, accounting_receipt.artifact_id)
        self.assertEqual(
            self.repository.read_content(
                tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=canonical.artifact_id
            ),
            b'{"invoice_id":"INV-1"}',
        )
        with self.assertRaisesRegex(ValueError, "append-only"):
            self.repository.append(
                ArtifactWrite(
                    **self.base,
                    artifact_id=canonical.artifact_id,
                    kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                    stage="canonical_mapping",
                    status="successful",
                    parent_artifact_id=receipt.artifact_id,
                ),
                content=b'{"invoice_id":"OVERWRITE"}',
            )

    def test_merged_accounting_proposal_keeps_all_successful_chunk_receipts_typed(self) -> None:
        extraction_receipt = self._receipt()
        canonical = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=extraction_receipt.artifact_id,
                provider_receipt_artifact_id=extraction_receipt.artifact_id,
            ),
            content=b'{}',
        )
        projection = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                stage="accounting_projection",
                status="successful",
                parent_artifact_id=canonical.artifact_id,
            ),
            content=b'{}',
        )
        first = self._receipt(stage="accounting_selection")
        second = self._receipt(stage="accounting_selection")
        proposal = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                stage="accounting_selection",
                status="successful",
                parent_artifact_id=projection.artifact_id,
                provider_receipt_artifact_id=second.artifact_id,
                component_receipt_artifact_ids=(first.artifact_id, second.artifact_id),
            ),
            content=b'{"merged":true}',
        )

        reloaded = LocalDocumentAiArtifactRepository(
            manifest_path=self.root / "document-ai-artifacts.json",
            storage=self.storage,
        ).get(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            artifact_id=proposal.artifact_id,
        )
        self.assertEqual(
            (first.artifact_id, second.artifact_id),
            reloaded.component_receipt_artifact_ids,
        )

        failed = self._receipt(status="failed", stage="accounting_selection")
        with self.assertRaisesRegex(ValueError, "successful provider receipts"):
            self.repository.append(
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                    stage="accounting_selection",
                    status="successful",
                    parent_artifact_id=projection.artifact_id,
                    provider_receipt_artifact_id=first.artifact_id,
                    component_receipt_artifact_ids=(first.artifact_id, failed.artifact_id),
                ),
                content=b'{}',
            )

    def test_secret_bearing_metadata_is_rejected_recursively(self) -> None:
        for metadata in (
            {"api_key": "secret"},
            {"transport": {"headers": {"Authorization": "Bearer secret"}}},
            {"request": {"x-goog-api-key": "secret"}},
            {"credentials": {"token": "secret"}},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaisesRegex(ValueError, "secret-bearing field"):
                    self.repository.append(
                        ArtifactWrite(
                            **self.base,
                            kind=ArtifactKind.PROVIDER_RECEIPT,
                            stage="document_extraction",
                            status="failed",
                            provider="gemini",
                            metadata=metadata,
                        ),
                        request_body=b"{}",
                        response_body=b"{}",
                    )

    def test_failed_retry_appends_and_preserves_previous_successful_revision(self) -> None:
        first = self._receipt()
        retry = self._receipt(
            status="failed",
            retry_of_artifact_id=first.artifact_id,
            response_body=b'{"error":{"code":503}}',
        )

        receipts = self.repository.list_for_document(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        )

        self.assertEqual([item.revision_no for item in receipts], [1, 2])
        self.assertEqual(retry.retry_of_artifact_id, first.artifact_id)
        self.assertEqual(
            self.repository.latest_successful(
                tenant_id="tenant-1",
                taxpayer_id="client-1",
                document_id="document-1",
                kind=ArtifactKind.PROVIDER_RECEIPT,
            ).artifact_id,
            first.artifact_id,
        )
        self.assertEqual(
            self.repository.read_response_body(
                tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=first.artifact_id
            ),
            b'{"candidates":[{"content":"exact"}]}',
        )

    def test_retry_may_reference_a_failed_receipt(self) -> None:
        failed = self._receipt(status="failed", response_body=b'{"error":"timeout"}')

        recovered = self._receipt(retry_of_artifact_id=failed.artifact_id)

        self.assertEqual(recovered.status, "successful")
        self.assertEqual(recovered.retry_of_artifact_id, failed.artifact_id)

    def test_failed_receipts_cannot_authorize_derived_or_expansion_lineage(self) -> None:
        failed_extraction = self._receipt(
            status="failed", response_body=b'{"error":"extraction"}'
        )
        successful_extraction = self._receipt()
        canonical = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=successful_extraction.artifact_id,
                provider_receipt_artifact_id=successful_extraction.artifact_id,
            ),
            content=b"{}",
        )
        projection = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                stage="accounting_projection",
                status="successful",
                parent_artifact_id=canonical.artifact_id,
            ),
            content=b"{}",
        )
        failed_accounting = self._receipt(
            stage="accounting_selection",
            status="failed",
            response_body=b'{"error":"accounting"}',
        )

        invalid_writes = (
            (
                "canonical",
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                    stage="canonical_mapping",
                    status="successful",
                    parent_artifact_id=failed_extraction.artifact_id,
                    provider_receipt_artifact_id=failed_extraction.artifact_id,
                ),
                {"content": b"{}"},
            ),
            (
                "proposal",
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                    stage="accounting_selection",
                    status="successful",
                    parent_artifact_id=projection.artifact_id,
                    provider_receipt_artifact_id=failed_accounting.artifact_id,
                ),
                {"content": b"{}"},
            ),
            (
                "expanded_from",
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.PROVIDER_RECEIPT,
                    stage="accounting_selection",
                    status="successful",
                    provider="gemini",
                    expanded_from_receipt_id=failed_accounting.artifact_id,
                ),
                {"request_body": b"{}", "response_body": b"{}"},
            ),
        )
        for label, write, bodies in invalid_writes:
            with self.subTest(link=label):
                with self.assertRaisesRegex(ValueError, "successful"):
                    self.repository.append(write, **bodies)

    def test_cross_source_hash_lineage_is_rejected_for_every_link(self) -> None:
        source_hash_a = self.base["source_file_sha256"]
        source_hash_b = hashlib.sha256(b"replacement-source").hexdigest()

        extraction_a = self._receipt(source_file_sha256=source_hash_a)
        canonical_a = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=extraction_a.artifact_id,
                provider_receipt_artifact_id=extraction_a.artifact_id,
            ),
            content=b'{"source":"a"}',
        )
        accounting_a = self._receipt(
            stage="accounting_selection", source_file_sha256=source_hash_a
        )

        base_b = {**self.base, "source_file_sha256": source_hash_b}
        extraction_b = self._receipt(source_file_sha256=source_hash_b)
        canonical_b = self.repository.append(
            ArtifactWrite(
                **base_b,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=extraction_b.artifact_id,
                provider_receipt_artifact_id=extraction_b.artifact_id,
            ),
            content=b'{"source":"b"}',
        )
        projection_b = self.repository.append(
            ArtifactWrite(
                **base_b,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                stage="accounting_projection",
                status="successful",
                parent_artifact_id=canonical_b.artifact_id,
            ),
            content=b'{"source":"b"}',
        )

        invalid_writes = (
            (
                "parent",
                ArtifactWrite(
                    **base_b,
                    kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                    stage="accounting_projection",
                    status="successful",
                    parent_artifact_id=canonical_a.artifact_id,
                ),
                {"content": b"{}"},
            ),
            (
                "provider receipt",
                ArtifactWrite(
                    **base_b,
                    kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                    stage="accounting_selection",
                    status="successful",
                    parent_artifact_id=projection_b.artifact_id,
                    provider_receipt_artifact_id=accounting_a.artifact_id,
                ),
                {"content": b"{}"},
            ),
            (
                "expanded_from",
                ArtifactWrite(
                    **base_b,
                    kind=ArtifactKind.PROVIDER_RECEIPT,
                    stage="accounting_selection",
                    status="failed",
                    provider="gemini",
                    expanded_from_receipt_id=accounting_a.artifact_id,
                ),
                {"request_body": b"{}", "response_body": b"{}"},
            ),
            (
                "retry",
                ArtifactWrite(
                    **base_b,
                    kind=ArtifactKind.PROVIDER_RECEIPT,
                    stage="document_extraction",
                    status="failed",
                    provider="gemini",
                    retry_of_artifact_id=extraction_a.artifact_id,
                ),
                {"request_body": b"{}", "response_body": b"{}"},
            ),
        )
        for label, write, bodies in invalid_writes:
            with self.subTest(link=label):
                with self.assertRaisesRegex(
                    ValueError, f"{label} lineage scope mismatch"
                ):
                    self.repository.append(write, **bodies)

    def test_failed_expansion_keeps_successful_receipt_as_proposal_authority(self) -> None:
        extraction_receipt = self._receipt()
        canonical = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=extraction_receipt.artifact_id,
                provider_receipt_artifact_id=extraction_receipt.artifact_id,
            ),
            content=b"{}",
        )
        projection = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                stage="accounting_projection",
                status="successful",
                parent_artifact_id=canonical.artifact_id,
            ),
            content=b"{}",
        )
        successful_receipt = self._receipt(stage="accounting_selection")
        failed_expansion = self._receipt(
            stage="accounting_selection",
            status="failed",
            expanded_from_receipt_id=successful_receipt.artifact_id,
            response_body=b'{"error":"unavailable"}',
        )
        proposal = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                stage="accounting_selection",
                status="successful",
                parent_artifact_id=projection.artifact_id,
                provider_receipt_artifact_id=successful_receipt.artifact_id,
            ),
            content=b'{"authority":"provisional"}',
        )

        self.assertEqual(failed_expansion.status, "failed")
        self.assertEqual(
            failed_expansion.expanded_from_receipt_id,
            successful_receipt.artifact_id,
        )
        self.assertEqual(
            proposal.provider_receipt_artifact_id,
            successful_receipt.artifact_id,
        )
        self.assertEqual(
            [
                item.artifact_id
                for item in self.repository.trace_lineage(
                    tenant_id="tenant-1",
                    taxpayer_id="client-1",
                    artifact_id=proposal.artifact_id,
                )
            ],
            [
                extraction_receipt.artifact_id,
                canonical.artifact_id,
                projection.artifact_id,
                proposal.artifact_id,
            ],
        )

    def test_source_deletion_removes_pdf_and_raw_receipt_bodies_but_keeps_manifest(self) -> None:
        source = self.storage.write_bytes(
            client_key="client-1",
            document_id="document-1",
            file_name="source.pdf",
            content=b"%PDF-source",
        )
        receipt = self._receipt()

        self.assertTrue(Path(receipt.request_storage_path).is_file())
        self.assertTrue(Path(receipt.response_storage_path).is_file())

        self.assertTrue(self.storage.delete(source.path))
        deleted_count = self.repository.delete_raw_bodies_for_source(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            source_file_id="source-1",
        )

        self.assertEqual(deleted_count, 2)
        self.assertFalse(Path(source.path).exists())
        self.assertFalse(Path(receipt.request_storage_path).exists())
        self.assertFalse(Path(receipt.response_storage_path).exists())
        self.assertEqual(
            self.repository.get(
                tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=receipt.artifact_id
            ).artifact_id,
            receipt.artifact_id,
        )

    def test_parent_lineage_must_follow_the_four_artifact_contract(self) -> None:
        receipt = self._receipt()
        with self.assertRaisesRegex(ValueError, "lineage"):
            self.repository.append(
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                    stage="accounting_selection",
                    status="successful",
                    parent_artifact_id=receipt.artifact_id,
                ),
                content=b"{}",
            )

    def test_accounting_expansion_receipt_has_typed_self_lineage(self) -> None:
        first = self._receipt(stage="accounting_selection")
        expanded = self._receipt(
            stage="accounting_selection",
            expanded_from_receipt_id=first.artifact_id,
        )

        self.assertEqual(expanded.expanded_from_receipt_id, first.artifact_id)
        with self.assertRaisesRegex(ValueError, "expanded_from"):
            self.repository.append(
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                    stage="canonical_mapping",
                    status="successful",
                    parent_artifact_id=first.artifact_id,
                    expanded_from_receipt_id=first.artifact_id,
                ),
                content=b"{}",
            )

    def test_stage_roles_reject_receipts_from_the_wrong_pipeline_stage(self) -> None:
        extraction_receipt = self._receipt(stage="document_extraction")
        accounting_receipt = self._receipt(stage="accounting_selection")

        with self.assertRaisesRegex(ValueError, "canonical.*document_extraction"):
            self.repository.append(
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                    stage="canonical_mapping",
                    status="successful",
                    parent_artifact_id=accounting_receipt.artifact_id,
                    provider_receipt_artifact_id=accounting_receipt.artifact_id,
                ),
                content=b"{}",
            )

        canonical = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=extraction_receipt.artifact_id,
                provider_receipt_artifact_id=extraction_receipt.artifact_id,
            ),
            content=b"{}",
        )
        projection = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                stage="accounting_projection",
                status="successful",
                parent_artifact_id=canonical.artifact_id,
            ),
            content=b"{}",
        )

        with self.assertRaisesRegex(ValueError, "proposal.*accounting_selection"):
            self.repository.append(
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.ACCOUNTING_PROPOSAL,
                    stage="accounting_selection",
                    status="successful",
                    parent_artifact_id=projection.artifact_id,
                    provider_receipt_artifact_id=extraction_receipt.artifact_id,
                ),
                content=b"{}",
            )

        with self.assertRaisesRegex(ValueError, "expanded_from.*accounting_selection"):
            self._receipt(
                stage="accounting_selection",
                expanded_from_receipt_id=extraction_receipt.artifact_id,
            )

    def test_sensitive_reads_require_and_enforce_tenant_scope(self) -> None:
        receipt = self._receipt()

        with self.assertRaises(KeyError):
            self.repository.get(
                tenant_id="tenant-other",
                taxpayer_id="client-1",
                artifact_id=receipt.artifact_id,
            )
        with self.assertRaises(KeyError):
            self.repository.read_response_body(
                tenant_id="tenant-1",
                taxpayer_id="client-other",
                artifact_id=receipt.artifact_id,
            )
        with self.assertRaises(KeyError):
            self.repository.trace_lineage(
                tenant_id="tenant-other",
                taxpayer_id="client-other",
                artifact_id=receipt.artifact_id,
            )

    def test_reads_reject_tampered_content_request_and_response_by_sha256(self) -> None:
        receipt = self._receipt()
        canonical = self.repository.append(
            ArtifactWrite(
                **self.base,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
                stage="canonical_mapping",
                status="successful",
                parent_artifact_id=receipt.artifact_id,
            ),
            content=b'{"invoice_id":"INV-1"}',
        )

        cases = (
            (
                receipt.request_storage_path,
                self.repository.read_request_body,
                receipt.artifact_id,
            ),
            (
                receipt.response_storage_path,
                self.repository.read_response_body,
                receipt.artifact_id,
            ),
            (
                canonical.content_storage_path,
                self.repository.read_content,
                canonical.artifact_id,
            ),
        )

        for path, reader, artifact_id in cases:
            with self.subTest(path=path):
                original = Path(path).read_bytes()
                Path(path).write_bytes(b'{"tampered":true}')
                with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                    reader(
                        tenant_id="tenant-1",
                        taxpayer_id="client-1",
                        artifact_id=artifact_id,
                    )
                Path(path).write_bytes(original)

    def test_two_repository_instances_atomically_merge_concurrent_appends(self) -> None:
        repositories = [
            LocalDocumentAiArtifactRepository(
                manifest_path=self.root / "document-ai-artifacts.json",
                storage=self.storage,
            )
            for _ in range(12)
        ]

        def append(index: int):
            started_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
            return repositories[index].append(
                ArtifactWrite(
                    **self.base,
                    kind=ArtifactKind.PROVIDER_RECEIPT,
                    stage="document_extraction",
                    status="successful",
                    provider="gemini",
                    http_status=200,
                    started_at=started_at,
                    finished_at=started_at + timedelta(milliseconds=index + 1),
                ),
                request_body=f'{{"request":{index}}}'.encode("utf-8"),
                response_body=f'{{"response":{index}}}'.encode("utf-8"),
            )

        with ThreadPoolExecutor(max_workers=len(repositories)) as executor:
            results = list(executor.map(append, range(len(repositories))))

        persisted = self.repository.list_for_document(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        )
        self.assertEqual(len(results), 12)
        self.assertEqual(len(persisted), 12)
        self.assertEqual([item.revision_no for item in persisted], list(range(1, 13)))

    def test_separate_processes_atomically_merge_manifest_appends(self) -> None:
        manifest_path = self.root / "process-document-ai-artifacts.json"
        storage_root = self.root / "process-documents"
        context = multiprocessing.get_context("spawn")
        processes = [
            context.Process(
                target=_append_receipt_in_process,
                args=(str(manifest_path), str(storage_root), index),
            )
            for index in range(4)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)

        repository = LocalDocumentAiArtifactRepository(
            manifest_path=manifest_path,
            storage=LocalDocumentStorage(storage_root),
        )
        persisted = repository.list_for_document(
            tenant_id="tenant-process",
            taxpayer_id="client-process",
            document_id="document-process",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        )
        self.assertEqual(len(persisted), 4)
        self.assertEqual([item.revision_no for item in persisted], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
