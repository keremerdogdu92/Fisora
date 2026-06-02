from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.workflow_store import JsonWorkflowStore
from app.persistence.store_factory import build_workflow_store
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents


class WorkflowStoreTests(unittest.TestCase):
    def test_json_store_persists_client_documents_reviews_and_export_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(store_path)

            client = store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Isitme Merkezi"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            chart_accounts = store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {
                        "raw_account_code": "320.01.015",
                        "normalized_account_code": "320.01.015",
                        "account_name": "Rexton Medikal",
                    }
                ],
            )
            uploaded_document = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "rexton.pdf",
                    "storage_path": "exports/documents/client-1/doc-1/rexton.pdf",
                    "status": "stored",
                },
            )
            document = store.save_simulation_result(
                client_id="client-1",
                document_ref="rexton.pdf",
                result={
                    "file_name": "rexton.pdf",
                    "simulated_status": "auto_ready",
                    "export_status": "export_ready",
                    "review_reason_codes": [],
                },
            )
            decision = store.save_review_decision(
                client_id="client-1",
                decision={"document_ref": "rexton.pdf", "action": "approve"},
                learning_event={"document_ref": "rexton.pdf", "automation_candidate": False},
            )
            package = store.save_export_package(
                client_id="client-1",
                package={"export_type": "zirve_universal_csv", "entry_count": 1},
            )

            reloaded = JsonWorkflowStore(store_path).get_workspace("client-1")

        self.assertEqual(client["client_id"], "client-1")
        self.assertEqual(chart_accounts["account_count"], 1)
        self.assertEqual(uploaded_document["document_ref"], "doc-1")
        self.assertEqual(document["export_status"], "export_ready")
        self.assertEqual(decision["decision"]["action"], "approve")
        self.assertEqual(package["package"]["entry_count"], 1)
        self.assertEqual(reloaded["client"]["profile"]["title"], "Demo Isitme Merkezi")
        self.assertEqual(len(reloaded["uploaded_documents"]), 1)
        self.assertEqual(len(reloaded["documents"]), 1)
        self.assertEqual(len(reloaded["review_decisions"]), 1)
        self.assertEqual(len(reloaded["learning_events"]), 1)
        self.assertEqual(len(reloaded["export_packages"]), 1)

    def test_json_store_is_scoped_by_client_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.upsert_client(
                client_id="client-2",
                profile={"client_id": "client-2"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="one.pdf",
                result={"file_name": "one.pdf", "export_status": "export_ready"},
            )
            store.save_simulation_result(
                client_id="client-2",
                document_ref="two.pdf",
                result={"file_name": "two.pdf", "export_status": "review_required"},
            )

            workspace = store.get_workspace("client-1")

        self.assertEqual(workspace["client"]["client_id"], "client-1")
        self.assertEqual([document["document_ref"] for document in workspace["documents"]], ["one.pdf"])

    def test_json_store_applies_document_retention_without_losing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "expired.pdf"
            storage_path.write_bytes(b"expired")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            expired_at = datetime.now(UTC) - timedelta(days=1)
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "expired-doc",
                    "document_type": "invoice",
                    "original_file_name": "expired.pdf",
                    "storage_path": str(storage_path),
                    "status": "stored",
                    "storage_status": "stored",
                    "expires_at": expired_at.isoformat(timespec="seconds"),
                    "deleted_at": "",
                },
            )

            summary = store.apply_document_retention()
            workspace = store.get_workspace("client-1")

        self.assertEqual(summary["deleted_count"], 1)
        self.assertFalse(storage_path.exists())
        self.assertEqual(workspace["uploaded_documents"][0]["storage_status"], "deleted")
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "expired.pdf")

    def test_json_store_tracks_processing_jobs_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "fatura.pdf",
                    "status": "stored",
                },
            )

            job = store.create_processing_job(
                client_id="client-1",
                document_ref="doc-1",
                document_type="invoice",
                parser_kind=parser_kind_for_document_type("invoice"),
            )
            claimed = store.claim_next_processing_job()
            store.update_processing_job(job_id=job["id"], status="completed")
            workspace = store.get_workspace("client-1")

        self.assertEqual(job["status"], "queued")
        self.assertEqual(claimed["status"], "processing")
        self.assertEqual(workspace["processing_jobs"][0]["status"], "completed")

    def test_processing_worker_creates_review_required_simulation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_ref": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "fatura.pdf",
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="invoice",
                parser_kind=parser_kind_for_document_type("invoice"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(workspace["processing_jobs"][0]["status"], "completed")
        self.assertEqual(workspace["documents"][0]["export_status"], "review_required")
        self.assertEqual(workspace["documents"][0]["review_reason_codes"], ["parser_output_required"])

    def test_store_factory_selects_json_and_requires_postgres_dsn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = build_workflow_store(store_backend="json", json_path=Path(temp_dir) / "store.json")

        self.assertIsInstance(store, JsonWorkflowStore)
        with self.assertRaises(ValueError):
            build_workflow_store(store_backend="postgres", postgres_dsn="")


if __name__ == "__main__":
    unittest.main()
