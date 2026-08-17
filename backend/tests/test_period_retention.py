from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import sys
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.period_retention import parse_accounting_period, period_retention_schedule
from app.domain.document_ai_artifacts import ArtifactKind, ArtifactWrite
from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository
from app.services.retention_service import RetentionService


class PeriodRetentionTests(unittest.TestCase):
    def test_scheduled_retention_deletes_pdf_and_raw_receipt_bodies_in_same_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "invoice.pdf"
            pdf.write_bytes(b"%PDF-retention")
            tenant_id = str(uuid4())
            taxpayer_id = str(uuid4())
            document_id = str(uuid4())
            source_file_id = str(uuid4())
            source_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
            artifacts = LocalDocumentAiArtifactRepository(
                manifest_path=root / "artifacts.json",
                storage=LocalDocumentStorage(root / "artifact-bodies"),
            )
            receipt = artifacts.append(
                ArtifactWrite(
                    tenant_id=tenant_id,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    source_file_id=source_file_id,
                    source_file_sha256=source_sha,
                    kind=ArtifactKind.PROVIDER_RECEIPT,
                    stage="document_extraction",
                    status="successful",
                ),
                request_body=b'{"request":"exact"}',
                response_body=b'{"response":"exact"}',
            )

            class Store:
                normalized_accounting_enabled = True
                _connect = None
                _json = None

                def __init__(self):
                    self.tenant_id = tenant_id
                    self.document_ai_artifact_repository = artifacts

            class DueRepository:
                def claim_retention_tick(self, **kwargs): return {"claimed": True}
                def prepare_retention_batches(self, **kwargs): return 0
                def open_due_retention_warnings(self, **kwargs): return 0
                def claim_due_retention_deletions(self, **kwargs):
                    return [{
                        "batch_id": str(uuid4()),
                        "taxpayer_id": taxpayer_id,
                        "sources": [{"source_file_id": source_file_id, "storage_path": str(pdf)}],
                    }]
                def resolve_retention_batch(self, **kwargs):
                    return {"deleted_source_count": 1, "resolved": True}

            service = RetentionService(store=Store(), document_storage_path=root)
            service.repository = DueRepository()

            summary = service.run_due(now=datetime(2026, 5, 31, tzinfo=UTC), worker_id="retention-test")

            self.assertEqual(summary["deleted_file_count"], 1)
            self.assertEqual(summary["deleted_raw_receipt_body_count"], 2)
            self.assertFalse(pdf.exists())
            self.assertFalse(Path(receipt.request_storage_path).exists())
            self.assertFalse(Path(receipt.response_storage_path).exists())

    def test_february_schedule_uses_calendar_month_boundaries(self) -> None:
        schedule = period_retention_schedule(date(2026, 2, 1))

        self.assertEqual(schedule.preparation_on, date(2026, 4, 30))
        self.assertEqual(schedule.warning_on, date(2026, 5, 1))
        self.assertEqual(schedule.delete_on, date(2026, 5, 31))

    def test_parse_accounting_period_requires_yyyy_mm(self) -> None:
        self.assertEqual(parse_accounting_period("2026-02"), date(2026, 2, 1))

        with self.assertRaisesRegex(ValueError, "invalid_accounting_period"):
            parse_accounting_period("2026-2")

    def test_schedule_handles_leap_year_and_december_rollover(self) -> None:
        self.assertEqual(
            period_retention_schedule(date(2024, 11, 1)).delete_on,
            date(2025, 2, 28),
        )
        self.assertEqual(
            period_retention_schedule(date(2024, 12, 1)).delete_on,
            date(2025, 3, 31),
        )


if __name__ == "__main__":
    unittest.main()
