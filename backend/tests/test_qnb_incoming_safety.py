from __future__ import annotations

from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


from app.persistence.workflow_store import JsonWorkflowStore
from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.persistence.normalized_accounting_repository import _date_or_none
from app.api.phase0_uploads import save_uploaded_document_with_job
from app.api.phase0_schemas import ReviewDecisionPayload, StoredReviewDecisionPayload
from app.services.document_identity import extract_source_identities
from app.services.export_service import ExportService
from app.services.review_service import ReviewService
from app.domain.workspace_exports import apply_document_safety_holds
from app.domain.qnb_readiness import qnb_readiness_payload
from app.domain.qnb_efatura import (
    FakeQnbEfaturaAdapter,
    QnbConnectionCredentials,
    QnbInvoiceSummary,
    QnbSyncService,
)
from app.domain.qnb_scheduler import QnbScheduler
from app import qnb_worker


UBL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>QNB2026000000001</ID>
  <UUID>same-ettn</UUID>
</Invoice>
"""


class QnbIncomingSafetyTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("DATABASE_URL"),
        "DATABASE_URL is required for PostgreSQL QNB safety proof",
    )
    def test_postgres_cross_channel_intake_and_status_hold_are_relational(self) -> None:
        store = PostgresWorkflowStore(
            os.environ["DATABASE_URL"],
            tenant_key=f"qnb-safety-{time.time_ns()}",
            accounting_store_target="compatibility",
        )
        store.upsert_client(
            client_id="client-1",
            profile={"client_id": "client-1", "title": "Pilot"},
            onboarding={"is_ready": True},
        )
        manual = store.accept_document_source(
            client_id="client-1",
            document={
                "document_id": "manual-source",
                "document_type": "einvoice_xml",
                "sha256": "manual-hash",
                "original_file_name": "manual.xml",
                "storage_path": "/tmp/manual.xml",
            },
            source_channel="manual_upload",
            identities=[{"kind": "ettn", "value": "same-ettn"}],
            parser_kind="einvoice_xml",
            intake_category="purchase_invoice",
        )
        qnb = store.accept_document_source(
            client_id="client-1",
            document={
                "document_id": "qnb-source",
                "document_type": "einvoice_xml",
                "sha256": "qnb-hash",
                "original_file_name": "qnb.xml",
                "storage_path": "/tmp/qnb.xml",
                "source_qnb_status": "received",
            },
            source_channel="qnb_esolutions",
            identities=[{"kind": "ettn", "value": "same-ettn"}],
            parser_kind="einvoice_xml",
            intake_category="purchase_invoice",
        )
        status = store.record_qnb_incoming_status(
            client_id="client-1",
            document_ref=manual["document_ref"],
            ettn="same-ettn",
            event_key="status-1",
            normalized_status="unknown",
            response_code="99",
            response_detail="unknown",
            cancelled_at="",
            checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        workspace = store.get_workspace("client-1")
        queued = store.enqueue_qnb_sync_request(
            client_id="client-1",
            start_date="2026-07-01",
            end_date="2026-07-09",
            requested_by="accountant-1",
        )
        first_claim = store.claim_next_qnb_sync_request(
            worker_id="worker-a",
            now="2026-07-25T10:00:00+00:00",
            lease_expires_at="2026-07-25T10:01:00+00:00",
        )
        second_claim = store.claim_next_qnb_sync_request(
            worker_id="worker-b",
            now="2026-07-25T10:02:00+00:00",
            lease_expires_at="2026-07-25T10:03:00+00:00",
        )

        self.assertEqual(qnb["document_ref"], manual["document_ref"])
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertTrue(status["automation_hold"])
        self.assertEqual(len(workspace["document_safety_holds"]), 1)
        self.assertEqual(second_claim["request_id"], queued["request_id"])
        self.assertNotEqual(second_claim["lease_token"], first_claim["lease_token"])

    @unittest.skipUnless(
        os.environ.get("DATABASE_URL"),
        "DATABASE_URL is required for PostgreSQL concurrency proof",
    )
    def test_postgres_concurrent_identity_claim_has_one_document_and_job(self) -> None:
        tenant_key = f"qnb-concurrency-{time.time_ns()}"
        setup_store = PostgresWorkflowStore(
            os.environ["DATABASE_URL"],
            tenant_key=tenant_key,
            accounting_store_target="compatibility",
        )
        setup_store.upsert_client(
            client_id="client-1",
            profile={"client_id": "client-1", "title": "Pilot"},
            onboarding={"is_ready": True},
        )

        def accept(index: int) -> dict[str, object]:
            store = PostgresWorkflowStore(
                os.environ["DATABASE_URL"],
                tenant_key=tenant_key,
                accounting_store_target="compatibility",
            )
            return store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": f"source-{index}",
                    "document_type": "einvoice_xml",
                    "sha256": f"hash-{index}",
                    "original_file_name": f"source-{index}.xml",
                    "storage_path": f"/tmp/source-{index}.xml",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": "concurrent-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(accept, (1, 2)))
        workspace = setup_store.get_workspace("client-1")

        self.assertEqual(
            {str(result["document_ref"]) for result in results},
            {str(results[0]["document_ref"])},
        )
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)

    def test_qnb_safety_migration_defines_relational_identity_status_and_hold_owners(self) -> None:
        sql = (
            ROOT
            / "backend"
            / "db"
            / "migrations"
            / "006_qnb_incoming_safety.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("create table if not exists document_identities", sql.lower())
        self.assertIn("create table if not exists provider_document_links", sql.lower())
        self.assertIn("create table if not exists external_status_events", sql.lower())
        self.assertIn("create table if not exists document_safety_holds", sql.lower())
        self.assertIn("unique (tenant_id, taxpayer_id, identity_kind, identity_value)", sql.lower())
        self.assertIn("where resolved_at is null", sql.lower())

    def test_ubl_identity_extraction_uses_ettn_before_composite_identity(self) -> None:
        identities = extract_source_identities(
            content=UBL_XML,
            file_name="invoice.xml",
        )

        self.assertEqual(identities[0], {"kind": "ettn", "value": "same-ettn"})

    def test_cross_channel_identity_attaches_second_source_to_one_document_and_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")

            manual = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "manual-source",
                    "document_type": "einvoice_xml",
                    "sha256": "manual-hash",
                    "original_file_name": "manual.xml",
                },
                source_channel="manual_upload",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            qnb = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "qnb-source",
                    "document_type": "einvoice_xml",
                    "sha256": "qnb-hash",
                    "original_file_name": "qnb.xml",
                    "source_provider": "qnb_esolutions",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(qnb["document_ref"], manual["document_ref"])
        self.assertFalse(manual["deduplicated"])
        self.assertTrue(qnb["deduplicated"])
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertEqual(
            {source["source_channel"] for source in workspace["uploaded_documents"][0]["document_sources"]},
            {"manual_upload", "qnb_esolutions"},
        )

    def test_qnb_sync_uses_cross_channel_identity_owned_by_manual_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            manual = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "manual-source",
                    "document_type": "einvoice_xml",
                    "sha256": "manual-hash",
                    "original_file_name": "manual.xml",
                },
                source_channel="manual_upload",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            invoice = QnbInvoiceSummary(
                ettn="same-ettn",
                invoice_no="QNB2026000000001",
                sequence_no="42",
                issue_date="20260709",
                supplier_tax_id="5910611341",
                supplier_title="QNB Test Satici",
                payable_total="120.00",
            )
            result = QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=FakeQnbEfaturaAdapter(
                    invoices=[invoice],
                    downloads={"same-ettn": UBL_XML},
                ),
            ).sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials(
                    "https://example.test",
                    "user",
                    "secret",
                    "5910611341",
                    "FSR31422",
                ),
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(result["downloaded_count"], 1)
        self.assertEqual(result["queued_processing_count"], 0)
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertEqual(workspace["uploaded_documents"][0]["document_ref"], manual["document_ref"])
        self.assertEqual(
            {source["source_channel"] for source in workspace["uploaded_documents"][0]["document_sources"]},
            {"manual_upload", "qnb_esolutions"},
        )

    def test_manual_upload_entrypoint_registers_ettn_for_later_qnb_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True},
            )
            store.upsert_portal_user(
                user_id="accountant-1",
                display_name="Accountant",
                role="accountant",
                allowed_client_ids=["client-1"],
            )
            manual = save_uploaded_document_with_job(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                record_operation_event=lambda **_: None,
                client_id="client-1",
                document_type="einvoice_xml",
                intake_category="purchase_invoice",
                file_name="manual.xml",
                uploaded_by="accountant-1",
                uploaded_by_user_id="accountant-1",
                content=UBL_XML,
            )
            invoice = QnbInvoiceSummary(
                ettn="same-ettn",
                invoice_no="QNB2026000000001",
                sequence_no="42",
                issue_date="20260709",
                supplier_tax_id="5910611341",
                supplier_title="QNB Test Satici",
                payable_total="120.00",
            )
            QnbSyncService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                adapter=FakeQnbEfaturaAdapter(
                    invoices=[invoice],
                    downloads={"same-ettn": UBL_XML},
                ),
            ).sync_incoming_invoices(
                client_id="client-1",
                credentials=QnbConnectionCredentials(
                    "https://example.test",
                    "user",
                    "secret",
                    "5910611341",
                    "FSR31422",
                ),
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertEqual(workspace["uploaded_documents"][0]["document_ref"], manual["document_ref"])

    def test_terminal_qnb_status_creates_persistent_export_hold_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            accepted = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "qnb-source",
                    "document_type": "einvoice_xml",
                    "sha256": "qnb-hash",
                    "source_provider": "qnb_esolutions",
                    "source_external_uuid": "same-ettn",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            first = store.record_qnb_incoming_status(
                client_id="client-1",
                document_ref=accepted["document_ref"],
                ettn="same-ettn",
                event_key="status-event-1",
                normalized_status="cancelled",
                response_code="2",
                response_detail="cancelled",
                cancelled_at="2026-07-25T10:00:00+00:00",
                checked_at="2026-07-25T10:01:00+00:00",
            )
            second = store.record_qnb_incoming_status(
                client_id="client-1",
                document_ref=accepted["document_ref"],
                ettn="same-ettn",
                event_key="status-event-2",
                normalized_status="received",
                response_code="-1",
                response_detail="received",
                cancelled_at="",
                checked_at="2026-07-25T10:02:00+00:00",
            )
            workspace = store.get_workspace("client-1")
            holds = store.active_document_safety_holds(
                client_id="client-1",
                document_refs=[accepted["document_ref"]],
            )

        self.assertTrue(first["automation_hold"])
        self.assertTrue(second["automation_hold"])
        self.assertEqual(len(workspace["qnb_incoming_status_snapshots"]), 2)
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["hold_code"], "qnb_status_cancelled")

    def test_active_qnb_hold_forces_authoritative_workspace_candidate_out_of_export(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "doc-1",
                    "export_status": "export_ready",
                    "result": {
                        "export_status": "export_ready",
                        "review_reason_codes": [],
                    },
                }
            ]
        }

        guarded = apply_document_safety_holds(
            workspace,
            holds=[
                {
                    "document_ref": "doc-1",
                    "hold_code": "qnb_status_unknown",
                }
            ],
        )

        document = guarded["documents"][0]
        self.assertEqual(document["export_status"], "review_required")
        self.assertIn(
            "qnb_status_unknown",
            document["result"]["review_reason_codes"],
        )

    def test_export_download_revalidates_qnb_hold_created_after_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = JsonWorkflowStore(root / "store.json")
            accepted = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "einvoice_xml",
                    "sha256": "hash-1",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            output_filename = "package.csv"
            output_path = root / "exports" / "client-1" / output_filename
            output_path.parent.mkdir(parents=True)
            output_path.write_text("entry", encoding="utf-8")
            store.save_export_package(
                client_id="client-1",
                package={
                    "output_filename": output_filename,
                    "entries": [{"document_ref": accepted["document_ref"]}],
                },
            )
            store.record_qnb_incoming_status(
                client_id="client-1",
                document_ref=accepted["document_ref"],
                ettn="same-ettn",
                event_key="status-event-after-package",
                normalized_status="unknown",
                response_code="99",
                response_detail="unknown",
                cancelled_at="",
                checked_at="2026-07-25T10:01:00+00:00",
            )
            service = ExportService(
                store=store,
                export_path=root / "exports",
                record_operation_event=lambda **_: {},
                require_client_access=lambda **_: {"allowed": True},
            )

            with self.assertRaises(HTTPException) as raised:
                service.export_download_path(
                    client_id="client-1",
                    file_name=output_filename,
                    user_id="accountant-1",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail["reason"],
            "qnb_external_status_hold",
        )

    def test_review_approval_is_blocked_while_qnb_status_hold_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            accepted = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "einvoice_xml",
                    "sha256": "hash-1",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            store.record_qnb_incoming_status(
                client_id="client-1",
                document_ref=accepted["document_ref"],
                ettn="same-ettn",
                event_key="status-event-before-approval",
                normalized_status="cancelled",
                response_code="2",
                response_detail="cancelled",
                cancelled_at="2026-07-25",
                checked_at="2026-07-25T10:01:00+00:00",
            )
            service = ReviewService(
                store=store,
                record_operation_event=lambda **_: {},
                require_client_access=lambda **_: {"allowed": True},
            )

            with self.assertRaises(HTTPException) as raised:
                service.store_review_decision(
                    payload=StoredReviewDecisionPayload(
                        client_id="client-1",
                        decision=ReviewDecisionPayload(
                            document_ref=accepted["document_ref"],
                            action="approve",
                            reviewer="accountant-1",
                        ),
                    ),
                    user_id="accountant-1",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail["reason"],
            "qnb_external_status_hold",
        )

    def test_cancelled_status_after_delivery_opens_correction_review_without_mutating_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            accepted = store.accept_document_source(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "einvoice_xml",
                    "sha256": "hash-1",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": "same-ettn"}],
                parser_kind="einvoice_xml",
                intake_category="purchase_invoice",
            )
            package = store.save_export_package(
                client_id="client-1",
                package={
                    "output_filename": "delivered.csv",
                    "entries": [{"document_ref": accepted["document_ref"]}],
                },
            )
            delivered = store.mark_export_package_downloaded(
                client_id="client-1",
                output_filename="delivered.csv",
            )
            store.record_qnb_incoming_status(
                client_id="client-1",
                document_ref=accepted["document_ref"],
                ettn="same-ettn",
                event_key="cancelled-after-delivery",
                normalized_status="cancelled",
                response_code="2",
                response_detail="cancelled",
                cancelled_at="2026-07-25",
                checked_at="2026-07-25T10:01:00+00:00",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(
            workspace["export_packages"][0]["package"]["downloaded_at"],
            delivered["package"]["downloaded_at"],
        )
        self.assertEqual(workspace["export_packages"][0]["id"], package["id"])
        self.assertEqual(len(workspace["qnb_correction_reviews"]), 1)
        self.assertEqual(
            workspace["qnb_correction_reviews"][0]["status"],
            "review_required",
        )
        self.assertFalse(
            workspace["qnb_correction_reviews"][0]["automatic_reversal_created"]
        )

    def test_scheduler_fencing_rejects_stale_worker_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_sync_policy(
                client_id="client-1",
                policy={
                    "enabled": True,
                    "next_run_at": "2026-07-25T10:00:00+00:00",
                },
            )
            first = store.claim_due_qnb_sync_policy(
                worker_id="worker-a",
                now="2026-07-25T10:00:00+00:00",
                lease_expires_at="2026-07-25T10:01:00+00:00",
            )
            second = store.claim_due_qnb_sync_policy(
                worker_id="worker-b",
                now="2026-07-25T10:02:00+00:00",
                lease_expires_at="2026-07-25T10:03:00+00:00",
            )
            stale_completed = store.complete_qnb_sync_policy(
                client_id="client-1",
                worker_id="worker-a",
                lease_token=first["lease_token"],
                updates={"last_run_status": "completed"},
            )
            policy = store.get_qnb_sync_policy(client_id="client-1")

        self.assertNotEqual(first["lease_token"], second["lease_token"])
        self.assertFalse(stale_completed)
        self.assertEqual(policy["lease_owner"], "worker-b")
        self.assertEqual(policy["lease_token"], second["lease_token"])

    def test_scheduler_renews_lease_during_slow_provider_run(self) -> None:
        class SlowService:
            def sync_incoming_invoices(self, *, client_id: str, max_documents: int):
                time.sleep(0.04)
                return {
                    "status": "completed",
                    "page_count": 1,
                    "downloaded_count": 0,
                }

            def reconcile_incoming_invoices(self, *, client_id: str, ettns: list[str]):
                return {
                    "status": "completed",
                    "updated_count": 0,
                    "error_count": 0,
                    "requested_count": 0,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_qnb_sync_policy(
                client_id="client-1",
                policy={
                    "enabled": True,
                    "next_run_at": "2026-07-25T10:00:00+00:00",
                    "status_reconciliation_enabled": False,
                },
            )
            result = QnbScheduler(
                store=store,
                service_factory=SlowService,
                worker_id="worker-a",
                lease_seconds=1,
                heartbeat_seconds=0.01,
            ).run_due_once()
            policy = store.get_qnb_sync_policy(client_id="client-1")

        self.assertEqual(result["policy"]["last_run_status"], "completed")
        self.assertTrue(policy["lease_renewed_at"])
        self.assertEqual(policy["lease_owner"], "")

    def test_qnb_scheduler_runs_in_dedicated_process_without_document_worker_secret(self) -> None:
        worker_source = (ROOT / "backend" / "app" / "worker.py").read_text(
            encoding="utf-8"
        )
        qnb_worker_source = (
            ROOT / "backend" / "app" / "qnb_worker.py"
        ).read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.production.yml").read_text(
            encoding="utf-8"
        )
        worker_block, qnb_block = compose.split("\n  qnb-scheduler:", 1)
        worker_block = worker_block.split("\n  worker:", 1)[1]

        self.assertNotIn("QnbScheduler", worker_source)
        self.assertNotIn("run_qnb_scheduler_once", worker_source)
        self.assertIn("QnbScheduler", qnb_worker_source)
        self.assertIn('command: ["python", "-m", "app.qnb_worker"]', qnb_block)
        self.assertNotIn("FISORA_QNB_CREDENTIAL_KEY", worker_block)
        self.assertIn("FISORA_QNB_CREDENTIAL_KEY", qnb_block)

    def test_dedicated_qnb_worker_consumes_manual_sync_queue(self) -> None:
        class FakeConnectionService:
            def sync_incoming_invoices(
                self,
                *,
                client_id: str,
                start_date: str,
                end_date: str,
            ) -> dict[str, object]:
                return {
                    "status": "completed",
                    "client_id": client_id,
                    "start_date": start_date,
                    "end_date": end_date,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            queued = store.enqueue_qnb_sync_request(
                client_id="client-1",
                start_date="2026-07-01",
                end_date="2026-07-09",
                requested_by="accountant-1",
            )
            with (
                patch.object(qnb_worker, "SCHEDULER_ENABLED", True),
                patch.object(
                    qnb_worker,
                    "build_connection_service",
                    return_value=FakeConnectionService(),
                ),
            ):
                result = qnb_worker.run_manual_sync_once(store)
            persisted = store._read()["qnb_sync_requests"][
                f"client-1:{queued['request_id']}"
            ]

        self.assertEqual(result["status"], "completed")
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(persisted["result"]["start_date"], "2026-07-01")

    def test_expired_manual_sync_request_is_reclaimed_with_fencing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            queued = store.enqueue_qnb_sync_request(
                client_id="client-1",
                start_date="2026-07-01",
                end_date="2026-07-09",
                requested_by="accountant-1",
            )
            first = store.claim_next_qnb_sync_request(
                worker_id="worker-a",
                now="2026-07-25T10:00:00+00:00",
                lease_expires_at="2026-07-25T10:01:00+00:00",
            )
            second = store.claim_next_qnb_sync_request(
                worker_id="worker-b",
                now="2026-07-25T10:02:00+00:00",
                lease_expires_at="2026-07-25T10:03:00+00:00",
            )
            stale_completed = store.complete_qnb_sync_request(
                client_id="client-1",
                request_id=queued["request_id"],
                worker_id="worker-a",
                lease_token=first["lease_token"],
                status="completed",
                result={},
            )

        self.assertEqual(second["request_id"], queued["request_id"])
        self.assertEqual(second["lease_owner"], "worker-b")
        self.assertNotEqual(second["lease_token"], first["lease_token"])
        self.assertFalse(stale_completed)

    def test_readiness_accepts_qnb_attachment_on_manual_canonical_document(self) -> None:
        class ReadinessStore:
            def list_clients(self):
                return [{"client_id": "client-1"}]

            def get_qnb_connection(self, *, client_id: str):
                return None

            def list_qnb_sync_runs(self, *, client_id: str, limit: int):
                return []

            def get_workspace(self, client_id: str):
                return {
                    "uploaded_documents": [
                        {
                            "document_ref": "doc-1",
                            "source_provider": "manual_upload",
                            "document_sources": [
                                {"source_channel": "manual_upload"},
                                {"source_channel": "qnb_esolutions"},
                            ],
                        }
                    ],
                    "documents": [
                        {"document_ref": "doc-1", "result": {"status": "processed"}}
                    ],
                    "qnb_incoming_status_snapshots": [],
                }

            def get_qnb_sync_policy(self, *, client_id: str):
                return None

            def list_operation_events(self, *, client_id: str, limit: int):
                return []

        payload = qnb_readiness_payload(store=ReadinessStore(), env={})

        self.assertEqual(payload["evidence"]["canonical_success_clients"], ["client-1"])

    def test_qnb_compact_issue_date_is_persistable(self) -> None:
        self.assertEqual(str(_date_or_none("20260709")), "2026-07-09")

    def test_qnb_readiness_rejects_config_only_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            payload = qnb_readiness_payload(
                store=store,
                env={
                    "FISORA_QNB_ADAPTER": "soap",
                    "FISORA_QNB_CREDENTIAL_KEY": "present",
                    "FISORA_QNB_ERP_CODE": "FSR31422",
                    "FISORA_QNB_SCHEDULER_ENABLED": "true",
                    "FISORA_REAL_DATA_PILOT_ENABLED": "true",
                    "FISORA_REAL_DATA_ACCESS_MODE": "tls",
                },
            )

        self.assertFalse(payload["incoming"]["ready"])
        self.assertFalse(payload["pilot"]["ready"])
        self.assertIn("active_connection", payload["incoming"]["blocking"])
        self.assertIn("recent_successful_sync", payload["incoming"]["blocking"])

    def test_production_config_has_single_qnb_owner_and_tls_preflight(self) -> None:
        env_text = (ROOT / "deploy" / "production.env.example").read_text(
            encoding="utf-8"
        )
        keys = [
            line.split("=", 1)[0]
            for line in env_text.splitlines()
            if line and not line.startswith("#") and "=" in line
        ]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        compose = (ROOT / "docker-compose.production.yml").read_text(
            encoding="utf-8"
        )
        preflight = (
            ROOT / "deploy" / "scripts" / "fisora-prod.sh"
        ).read_text(encoding="utf-8")

        self.assertEqual(duplicates, [])
        self.assertIn("FISORA_QNB_SCHEDULER_ENABLED=false", env_text)
        self.assertIn("FISORA_QNB_OPERATION_OWNER=", env_text)
        self.assertIn('${FISORA_HTTPS_PORT:-443}:443', compose)
        self.assertIn("default.tls.conf", compose)
        backend_block = compose.split("\n  backend:", 1)[1].split("\n  worker:", 1)[0]
        self.assertIn("FISORA_QNB_SCHEDULER_ENABLED:", backend_block)
        self.assertIn("FISORA_QNB_OPERATION_OWNER:", backend_block)
        self.assertIn("duplicate environment keys", preflight)
        self.assertIn("QNB live mode requires HTTPS", preflight)
        self.assertIn("fullchain.pem", preflight)
        self.assertIn("privkey.pem", preflight)
        self.assertIn("change-me", preflight)
        self.assertIn("FISORA_RELEASE_RECEIPT", preflight)
        self.assertIn("config_fingerprint", preflight)
        self.assertIn("rollback-code", preflight)


if __name__ == "__main__":
    unittest.main()
