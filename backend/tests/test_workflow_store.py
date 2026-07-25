from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.workflow_store import JsonWorkflowStore, ResearchProfileConflict
from app.domain.ai_classification import AiClassificationPolicy, StaticFirstClassifier
from app.domain.statement_ai_suggestions import StatementAiSuggestionPolicy
from app.domain.workspace_exports import build_workspace_export_package
from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.persistence.store_factory import build_workflow_store
from app.services.document_service import DocumentService
from app.worker import worker_concurrency_from_env
from backend.scripts.import_private_intake_manifest import import_manifest
from app.workflows.document_processing import build_ai_runtime_from_env, build_statement_processing_result, parser_kind_for_document_type, process_queued_documents


class FakeStatementSuggestionProvider:
    provider_name = "fake_statement_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[object] = []

    def suggest_statement_line(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class FakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[object] = []

    def classify_product(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class RaisingProductProvider:
    provider_name = "raising_llm"

    def classify_product(self, request: object) -> dict[str, object]:
        raise RuntimeError("401 Unauthorized")


class WorkflowStoreTests(unittest.TestCase):
    def test_outgoing_attempt_claim_is_idempotent_and_events_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_outgoing_invoice(
                client_id="client-a",
                invoice={
                    "invoice_id": "invoice-1",
                    "status": "approved",
                    "document_type": "earsiv",
                    "ubl_sha256": "a" * 64,
                },
            )

            claimed, invoice, attempt = store.claim_outgoing_invoice_attempt(
                client_id="client-a",
                invoice_id="invoice-1",
                idempotency_key="send-1",
                ubl_sha256="a" * 64,
                provider="qnb_sandbox",
                provider_operation="faturaOlusturExt",
            )
            repeated_claim, repeated_invoice, repeated_attempt = store.claim_outgoing_invoice_attempt(
                client_id="client-a",
                invoice_id="invoice-1",
                idempotency_key="send-1",
                ubl_sha256="a" * 64,
                provider="qnb_sandbox",
                provider_operation="faturaOlusturExt",
            )
            updated = store.append_outgoing_invoice_attempt_event(
                client_id="client-a",
                attempt_id=attempt["attempt_id"],
                event="request_started",
                state="request_started",
                details={"endpoint_class": "qnb_test"},
            )
            stored_attempt = store.get_outgoing_invoice_attempt(
                client_id="client-a", attempt_id=attempt["attempt_id"]
            )

        self.assertTrue(claimed)
        self.assertFalse(repeated_claim)
        self.assertEqual(invoice["status"], "sending")
        self.assertEqual(repeated_invoice["status"], "sending")
        self.assertEqual(repeated_attempt["attempt_id"], attempt["attempt_id"])
        self.assertEqual([row["event"] for row in updated["events"]], ["claimed", "request_started"])
        self.assertEqual(stored_attempt["state"], "request_started")

    def test_outgoing_attempt_key_cannot_be_reused_for_another_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_outgoing_invoice(
                client_id="client-a",
                invoice={
                    "invoice_id": "invoice-1",
                    "status": "approved",
                    "document_type": "efatura",
                    "ubl_sha256": "a" * 64,
                },
            )
            store.claim_outgoing_invoice_attempt(
                client_id="client-a",
                invoice_id="invoice-1",
                idempotency_key="send-1",
                ubl_sha256="a" * 64,
                provider="qnb_sandbox",
                provider_operation="belgeGonderExt",
            )

            with self.assertRaisesRegex(ValueError, "hash"):
                store.claim_outgoing_invoice_attempt(
                    client_id="client-a",
                    invoice_id="invoice-1",
                    idempotency_key="send-1",
                    ubl_sha256="b" * 64,
                    provider="qnb_sandbox",
                    provider_operation="belgeGonderExt",
                )

    def test_document_file_returns_rendered_invoice_preview_for_xml(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-06</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Satici Ltd Sti</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Alici Ltd Sti</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Isitme cihazi bakim seti</cbc:Name></cac:Item>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:TaxInclusiveAmount currencyID="TRY">120.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            storage = base / "documents"
            xml_path = storage / "client-1" / "invoice.xml"
            xml_path.parent.mkdir(parents=True)
            xml_path.write_text(xml, encoding="utf-8")
            store = JsonWorkflowStore(base / "phase0_store.json")
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "invoice.xml",
                    "document_ref": "invoice.xml",
                    "document_type": "einvoice_xml",
                    "original_file_name": "invoice.xml",
                    "storage_path": str(xml_path),
                    "content_type": "application/xml",
                    "status": "stored",
                },
            )
            service = DocumentService(
                store=store,
                document_storage_path=storage,
                record_operation_event=lambda **kwargs: dict(kwargs),
                require_client_access=lambda **kwargs: {"allowed": True},
            )

            info = service.original_document_file(client_id="client-1", document_ref="invoice.xml", user_id="tester")

        self.assertEqual(info["media_type"], "text/html; charset=utf-8")
        self.assertIn("html", info)
        self.assertIn("Fatura", info["html"])
        self.assertIn("Isitme cihazi bakim seti", info["html"])
        self.assertNotIn("<Invoice", info["html"])

    def test_worker_concurrency_defaults_to_single_slot_outside_production_env(self) -> None:
        self.assertEqual(worker_concurrency_from_env({}), 1)

    def test_worker_concurrency_uses_configured_positive_slot_count(self) -> None:
        self.assertEqual(worker_concurrency_from_env({"FISORA_WORKER_CONCURRENCY": "3"}), 3)

    def test_ai_runtime_from_env_builds_groq_provider_for_worker(self) -> None:
        runtime = build_ai_runtime_from_env(
            {
                "FISORA_AI_PROVIDER": "groq",
                "GROQ_API_KEY": "gsk-test",
                "FISORA_AI_MODEL": "",
            }
        )

        provider = runtime["statement_ai_provider"]

        self.assertEqual(provider.provider_name, "groq")
        self.assertEqual(provider.model, "openai/gpt-oss-20b")

    def test_ai_runtime_from_env_builds_provider_chain_for_fallback(self) -> None:
        runtime = build_ai_runtime_from_env(
            {
                "FISORA_AI_PROVIDER_CHAIN": "groq,openai",
                "GROQ_API_KEY": "gsk-test",
                "OPENAI_API_KEY": "sk-test",
                "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
                "FISORA_OPENAI_MODEL": "gpt-5.4-mini",
            }
        )

        product_provider = runtime["product_classifier"].provider
        statement_provider = runtime["statement_ai_provider"]

        self.assertEqual(product_provider.provider_name, "groq>openai")
        self.assertEqual(statement_provider.provider_name, "groq>openai")

    def test_ai_runtime_from_env_builds_three_provider_chain_for_fallback(self) -> None:
        runtime = build_ai_runtime_from_env(
            {
                "FISORA_AI_PROVIDER_CHAIN": "groq,openrouter,cerebras",
                "GROQ_API_KEY": "gsk-test",
                "OPENROUTER_API_KEY": "or-test",
                "CEREBRAS_API_KEY": "csk-test",
                "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
                "FISORA_OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
                "FISORA_CEREBRAS_MODEL": "gpt-oss-120b",
                "FISORA_OPENROUTER_SITE_URL": "http://185.184.208.188",
                "FISORA_OPENROUTER_APP_TITLE": "Fisora Operasyon Portal",
            }
        )

        product_provider = runtime["product_classifier"].provider
        statement_provider = runtime["statement_ai_provider"]

        self.assertEqual(product_provider.provider_name, "groq>openrouter>cerebras")
        self.assertEqual(statement_provider.provider_name, "groq>openrouter>cerebras")
        self.assertEqual([provider.model for provider in product_provider.providers], [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-20b:free",
            "gpt-oss-120b",
        ])

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

    def test_processing_run_summary_exposes_progress_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")

            summary = process_queued_documents(store, max_jobs=3)

        self.assertRegex(summary["run_id"], r"^processing-run-")
        self.assertEqual(summary["queued_count"], 0)
        self.assertEqual(summary["completed_count"], 0)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["current_status"], "idle")

    def test_processing_run_records_job_timing_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            document_path = Path(temp_dir) / "manual.txt"
            document_path.write_text("manual review", encoding="utf-8")
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_ref": "doc-1",
                    "document_type": "special_document",
                    "intake_category": "special_document",
                    "storage_path": str(document_path),
                    "original_file_name": "manual.txt",
                },
            )
            job = store.create_processing_job(
                client_id="client-1",
                document_ref="doc-1",
                document_type="special_document",
                parser_kind="manual_review",
                intake_category="special_document",
            )

            summary = process_queued_documents(store, max_jobs=1)
            workspace = store.get_workspace("client-1")

        updated_job = workspace["processing_jobs"][0]
        metrics = updated_job["processing_metrics"]
        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(updated_job["id"], job["id"])
        self.assertIn("queue_wait_ms", metrics)
        self.assertIn("parse_ms", metrics)
        self.assertIn("ai_ms", metrics)
        self.assertIn("research_ms", metrics)
        self.assertIn("total_ms", metrics)
        self.assertIn("provider", metrics)
        self.assertIn("research_cache_hit", metrics)
        self.assertIn("nace_cache_hit", metrics)
        self.assertGreaterEqual(metrics["total_ms"], 0)

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

    def test_json_store_tracks_portal_user_client_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            user = store.upsert_portal_user(
                user_id="mukellef-user",
                display_name="Mukellef Kullanici",
                role="client_user",
                allowed_client_ids=["client-1"],
            )
            allowed = store.verify_portal_access(client_id="client-1", user_id="mukellef-user")
            denied = store.verify_portal_access(client_id="client-2", user_id="mukellef-user")
            workspace = store.get_workspace("client-1")

        self.assertEqual(user["role"], "client_user")
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["reason"], "assigned_client_access")
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["reason"], "client_not_onboarded")
        self.assertEqual(workspace["portal_users"][0]["user_id"], "mukellef-user")

    def test_json_store_replaces_client_portal_user_as_single_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.upsert_portal_user(
                user_id="old-user",
                display_name="Old User",
                role="client_user",
                allowed_client_ids=["client-1"],
            )
            store.set_auth_password(user_id="old-user", password_hash="old-hash")

            result = store.replace_client_portal_user(
                client_id="client-1",
                old_user_id="old-user",
                new_user_id="new-user",
                display_name="New User",
            )
            workspace = store.get_workspace("client-1")
            old_password = store.get_auth_password_hash(user_id="old-user")
            old_access = store.verify_portal_access(client_id="client-1", user_id="old-user")
            new_access = store.verify_portal_access(client_id="client-1", user_id="new-user")

            self.assertEqual(result["portal_user"]["user_id"], "new-user")
            self.assertTrue(result["old_user_removed"])
            self.assertEqual(old_password, "")
            self.assertFalse(old_access["allowed"])
            self.assertTrue(new_access["allowed"])
            self.assertEqual([user["user_id"] for user in workspace["portal_users"]], ["new-user"])

    def test_json_store_deletes_selected_documents_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            stored_file = base / "documents" / "client-1" / "invoice.pdf"
            stored_file.parent.mkdir(parents=True)
            stored_file.write_bytes(b"pdf")
            store = JsonWorkflowStore(base / "phase0_store.json")
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "invoice.pdf",
                    "storage_path": str(stored_file),
                    "status": "stored",
                },
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="doc-1",
                result={"file_name": "invoice.pdf", "export_status": "review_required"},
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref="doc-1",
                document_type="invoice",
                parser_kind="invoice_pdf",
            )
            store.record_document_pipeline_event(
                client_id="client-1",
                document_ref="doc-1",
                step="uploaded",
                status="ok",
                message_tr="Belge yuklendi.",
                debug_code="uploaded",
            )

            summary = store.delete_client_documents(
                client_id="client-1",
                document_refs=["doc-1"],
                delete_files=True,
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(summary["deleted_count"], 1)
        self.assertEqual(summary["deleted_document_refs"], ["doc-1"])
        self.assertFalse(stored_file.exists())
        self.assertEqual(workspace["uploaded_documents"], [])
        self.assertEqual(workspace["documents"], [])
        self.assertEqual(workspace["processing_jobs"], [])
        self.assertEqual(workspace["document_pipeline_events"], [])

    def test_json_store_reset_test_data_preserves_accountant_login_and_deletes_client_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            document_dir = base / "documents"
            export_dir = base / "exports"
            stored_file = document_dir / "client-1" / "stored.pdf"
            export_file = export_dir / "client-1-export.csv"
            stored_file.parent.mkdir(parents=True)
            export_dir.mkdir()
            stored_file.write_bytes(b"stored")
            export_file.write_text("export", encoding="utf-8")
            store = JsonWorkflowStore(base / "phase0_store.json")
            store.upsert_portal_user(
                user_id="mali-musavir",
                display_name="Mali Musavir",
                role="accountant",
                allowed_client_ids=["*"],
            )
            store.set_auth_password(user_id="mali-musavir", password_hash="hash-accountant")
            store.upsert_portal_user(
                user_id="client-user",
                display_name="Client User",
                role="client_user",
                allowed_client_ids=["client-1"],
            )
            store.set_auth_password(user_id="client-user", password_hash="hash-client")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Client One"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(client_id="client-1", accounts=[{"raw_account_code": "100"}])
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "stored",
                    "original_file_name": "stored.pdf",
                    "storage_path": str(stored_file),
                    "status": "stored",
                },
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="stored.pdf",
                result={"file_name": "stored.pdf", "export_status": "review_required"},
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref="stored.pdf",
                document_type="invoice",
                parser_kind="invoice_pdf",
            )
            store.save_export_package(client_id="client-1", package={"output_filename": export_file.name})

            summary = store.reset_test_data(document_storage_path=document_dir, export_path=export_dir)
            reloaded = JsonWorkflowStore(base / "phase0_store.json")
            self.assertEqual(summary["preserved_portal_user_count"], 1)
            self.assertEqual(summary["deleted_client_count"], 1)
            self.assertGreaterEqual(summary["deleted_record_count"], 6)
            self.assertGreaterEqual(summary["deleted_file_count"], 2)
            self.assertEqual(reloaded.list_clients(), [])
            self.assertEqual(reloaded.get_auth_password_hash(user_id="mali-musavir"), "hash-accountant")
            self.assertEqual(reloaded.get_auth_password_hash(user_id="client-user"), "")
            self.assertEqual(reloaded.get_portal_user("mali-musavir")["role"], "accountant")
            self.assertEqual(reloaded.verify_portal_access(client_id="client-1", user_id="mali-musavir")["reason"], "client_not_onboarded")
            self.assertFalse(reloaded.verify_portal_access(client_id="client-1", user_id="client-user")["allowed"])
            self.assertFalse(stored_file.exists())
            self.assertFalse(export_file.exists())

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

    def test_json_store_document_retention_preview_does_not_delete_expired_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "expired-preview.pdf"
            storage_path.write_bytes(b"expired")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            expired_at = datetime.now(UTC) - timedelta(days=1)
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "expired-preview",
                    "document_type": "invoice",
                    "original_file_name": "expired-preview.pdf",
                    "storage_path": str(storage_path),
                    "status": "stored",
                    "storage_status": "stored",
                    "expires_at": expired_at.isoformat(timespec="seconds"),
                    "deleted_at": "",
                },
            )

            preview = store.preview_document_retention()
            workspace = store.get_workspace("client-1")
            file_exists = storage_path.exists()

        self.assertEqual(preview["expired_count"], 1)
        self.assertEqual(preview["deleted_count"], 0)
        self.assertTrue(file_exists)
        self.assertEqual(workspace["uploaded_documents"][0]["storage_status"], "stored")

    def test_json_store_document_retention_action_extends_expired_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "expired-extend.pdf"
            storage_path.write_bytes(b"expired")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            expired_at = datetime(2026, 1, 1, tzinfo=UTC)
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "expired-extend",
                    "document_type": "invoice",
                    "original_file_name": "expired-extend.pdf",
                    "storage_path": str(storage_path),
                    "status": "stored",
                    "storage_status": "stored",
                    "download_available_until": expired_at.isoformat(timespec="seconds"),
                    "expires_at": expired_at.isoformat(timespec="seconds"),
                    "deleted_at": "",
                },
            )

            result = store.apply_document_retention_action(
                document_refs=["expired-extend"],
                action="extend_90_days",
            )
            workspace = store.get_workspace("client-1")
            file_exists = storage_path.exists()

        self.assertEqual(result["extended_count"], 1)
        self.assertEqual(result["deleted_count"], 0)
        self.assertTrue(file_exists)
        self.assertEqual(workspace["uploaded_documents"][0]["storage_status"], "stored")
        self.assertEqual(workspace["uploaded_documents"][0]["expires_at"], "2026-04-01T00:00:00+00:00")

    def test_json_store_keeps_document_under_review_for_review_required_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="purchase.xml",
                result={
                    "file_name": "purchase.xml",
                    "simulated_status": "review_required",
                    "export_status": "export_ready",
                    "is_balanced": True,
                },
            )

            store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "purchase.xml",
                    "action": "review_required",
                    "reviewer": "mali-musavir",
                    "reason": "Kontrolde tut",
                },
                learning_event={
                    "document_ref": "purchase.xml",
                    "scope": "general_candidate",
                    "action": "review_required",
                    "category": "live_screen_smoke",
                    "corrected_account_code": "",
                    "corrected_counterparty_code": "",
                    "reason": "Kontrolde tut",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            document = workspace["documents"][0]

        self.assertEqual(document["export_status"], "review_required")
        self.assertEqual(document["result"]["export_status"], "review_required")
        self.assertEqual(document["result"]["accountant_decision_action"], "review_required")
        self.assertEqual(document["result"]["accountant_decision_reason"], "Kontrolde tut")

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

    def test_json_store_concurrent_claims_do_not_claim_same_job_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.create_processing_job(
                client_id="client-1",
                document_ref="doc-1",
                document_type="invoice",
                parser_kind="text_pdf_invoice",
            )
            claimed: list[str] = []

            def claim_once() -> None:
                job = store.claim_next_processing_job()
                if job:
                    claimed.append(str(job["id"]))

            threads = [threading.Thread(target=claim_once) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(len(claimed), 1)

    def test_json_store_tracks_operation_events_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            event = store.record_operation_event(
                client_id="client-1",
                event={
                    "event_id": "event-1",
                    "client_id": "client-1",
                    "event_type": "processing_run",
                    "status": "ok",
                    "message": "Worker calisti.",
                    "metadata": {"completed_count": 1},
                    "created_at": "2026-06-03T10:00:00+00:00",
                },
            )
            events = store.list_operation_events(client_id="client-1")
            workspace = store.get_workspace("client-1")

        self.assertEqual(event["event_type"], "processing_run")
        self.assertEqual(events[0]["metadata"]["completed_count"], 1)
        self.assertEqual(workspace["operation_events"][0]["event_id"], "event-1")

    def test_json_store_tracks_document_pipeline_events_by_document_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            first = store.record_document_pipeline_event(
                client_id="client-1",
                document_ref="doc-1",
                step="uploaded",
                status="ok",
                message_tr="Belge yüklendi.",
                debug_code="uploaded",
                details={"size_bytes": 6},
            )
            store.record_document_pipeline_event(
                client_id="client-1",
                document_ref="doc-1",
                step="file_preview_ready",
                status="ok",
                message_tr="Belge önizlenebiliyor.",
                debug_code="file_preview_ready",
                details={"media_type": "application/pdf"},
            )
            store.record_document_pipeline_event(
                client_id="client-1",
                document_ref="other-doc",
                step="uploaded",
                status="ok",
                message_tr="Başka belge yüklendi.",
                debug_code="uploaded",
                details={},
            )

            events = store.list_document_pipeline_events(client_id="client-1", document_ref="doc-1")
            workspace = store.get_workspace("client-1")

        self.assertEqual(first["event_type"], "document_pipeline_event")
        self.assertEqual([event["step"] for event in events], ["uploaded", "file_preview_ready"])
        self.assertEqual(events[0]["message_tr"], "Belge yüklendi.")
        self.assertEqual(events[0]["details"]["size_bytes"], 6)
        self.assertEqual(len(workspace["document_pipeline_events"]), 3)

    def test_json_store_caches_nace_research_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            profile = store.save_nace_research_profile(
                nace_code="47.74.01",
                profile={
                    "activity_title": "Tıbbi ürünlerin perakende ticareti",
                    "scope_summary": "İşitme cihazı satış faaliyetini kapsar.",
                    "included_goods_services": ["işitme cihazı", "pil"],
                    "likely_business_expenses": ["medikal sarf", "kargo"],
                    "unlikely_or_personal_items": ["kişisel bakım"],
                    "bank_statement_hints": ["tedarikçi ödemesi"],
                    "activity_tags": ["hearing_aid", "medical_retail"],
                    "source_urls": ["https://example.test/nace"],
                },
            )
            cached = store.get_nace_research_profile("477401")

        self.assertEqual(profile["nace_code"], "477401")
        self.assertEqual(cached["scope_summary"], "İşitme cihazı satış faaliyetini kapsar.")
        self.assertEqual(cached["activity_tags"], ["hearing_aid", "medical_retail"])

    def test_nace_research_cache_hit_reuses_profile_without_research(self) -> None:
        from app.domain.nace_research import resolve_nace_research_profile

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_nace_research_profile(
                nace_code="99.99.99",
                profile={
                    "activity_title": "Özel pilot faaliyet",
                    "scope_summary": "Cache edilmiş faaliyet kapsamı.",
                    "included_goods_services": ["pilot hizmet"],
                    "likely_business_expenses": ["gider"],
                    "unlikely_or_personal_items": [],
                    "bank_statement_hints": [],
                    "activity_tags": ["food_service"],
                    "source_urls": ["https://example.test/cached"],
                },
            )
            calls: list[str] = []

            profile = resolve_nace_research_profile(
                store=store,
                nace_code="999999",
                researcher=lambda code: calls.append(code) or {},
            )

        self.assertEqual(profile["scope_summary"], "Cache edilmiş faaliyet kapsamı.")
        self.assertEqual(calls, [])

    def test_json_store_caches_brand_research_profiles(self) -> None:
        from app.domain.brand_research import resolve_brand_research_profile

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            profile = store.save_brand_research_profile(
                brand_name="Blendax",
                profile={
                    "display_name": "Blendax",
                    "brand_summary": "Sampuan markasi.",
                    "common_product_categories": ["kisisel_bakim_kozmetik"],
                    "source_urls": ["https://example.test/brand"],
                    "confidence": 88,
                },
            )
            calls: list[str] = []
            cached = resolve_brand_research_profile(
                store=store,
                brand_name="blendax",
                researcher=lambda brand: calls.append(brand) or {"brand_summary": "Arastirma yapildi."},
            )

        self.assertEqual(profile["brand_name"], "blendax")
        self.assertEqual(cached["brand_summary"], "Sampuan markasi.")
        self.assertEqual(cached["common_product_categories"], ["kisisel_bakim_kozmetik"])
        self.assertEqual(calls, [])

    def test_json_research_profile_lookup_enforces_client_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_brand_research_profile(
                brand_name="ctxv2-client-1",
                profile={"profile_id": "ctxv2-client-1", "owner_client_id": "client-1"},
            )
            store.save_brand_research_profile(
                brand_name="ctxv2-client-2",
                profile={"profile_id": "ctxv2-client-2", "owner_client_id": "client-2"},
            )
            store.save_brand_research_profile(
                brand_name="ctxv2-office",
                profile={"profile_id": "ctxv2-office", "scope_type": "office_public"},
            )
            store.save_brand_research_profile(
                brand_name="legacy",
                profile={"profile_id": "legacy", "scope_type": "legacy_unowned"},
            )

            visible = store.list_research_profiles(kind="brand", allowed_client_ids={"client-1"})
            denied = store.get_research_profile(
                kind="brand",
                key="ctxv2-client-2",
                allowed_client_ids={"client-1"},
            )

        self.assertEqual({item["profile_id"] for item in visible}, {"ctxv2-client-1", "ctxv2-office"})
        self.assertIsNone(denied)

    def test_json_research_profile_update_uses_expected_revision_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            first = store.save_brand_research_profile(
                brand_name="ctxv2-one",
                profile={"profile_id": "ctxv2-one", "evidence": [{"url": "https://example.test"}]},
            )
            updated = store.save_brand_research_profile(
                brand_name="ctxv2-one",
                profile={"summary_tr": "accountant note"},
                expected_revision=first["revision"],
            )
            with self.assertRaises(ResearchProfileConflict):
                store.save_brand_research_profile(
                    brand_name="ctxv2-one",
                    profile={"summary_tr": "stale note"},
                    expected_revision=first["revision"],
                )

        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["evidence"], [{"url": "https://example.test"}])

    def test_postgres_store_exposes_generic_research_profile_lookup(self) -> None:
        class FakePostgresStore(PostgresWorkflowStore):
            def __init__(self) -> None:
                pass

            def get_nace_research_profile(self, nace_code: str) -> dict[str, object] | None:
                return {"kind": "nace", "key": nace_code}

            def get_brand_research_profile(self, brand_name: str) -> dict[str, object] | None:
                return {"kind": "brand", "key": brand_name}

        store = FakePostgresStore()

        self.assertEqual(store.get_research_profile(kind="brand", key="Rexton")["kind"], "brand")
        self.assertEqual(store.get_research_profile(kind="nace", key="477401")["kind"], "nace")
        self.assertIsNone(store.get_research_profile(kind="other", key="x"))

    def test_postgres_research_profile_update_locks_and_compares_revision(self) -> None:
        executed_sql: list[str] = []

        class FakeCursor:
            def __enter__(self) -> "FakeCursor":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def execute(self, sql: str, params: object = None) -> None:
                executed_sql.append(sql)

            def fetchone(self) -> tuple[str, dict[str, object]]:
                return (
                    "client-1",
                    {
                        "profile_id": "ctxv2-one",
                        "owner_client_id": "client-1",
                        "revision": 3,
                        "evidence": [{"url": "https://example.test"}],
                    },
                )

        class FakeConnection:
            def __enter__(self) -> "FakeConnection":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def cursor(self) -> FakeCursor:
                return FakeCursor()

        store = PostgresWorkflowStore("postgresql://example", connect=lambda: FakeConnection())
        store._ensure_tenant = lambda: None  # type: ignore[method-assign]
        updated = store.save_brand_research_profile(
            brand_name="ctxv2-one",
            profile={"summary_tr": "accountant note"},
            expected_revision=3,
        )
        with self.assertRaises(ResearchProfileConflict):
            store.save_brand_research_profile(
                brand_name="ctxv2-one",
                profile={"summary_tr": "stale note"},
                expected_revision=2,
            )

        self.assertIn("for update", "\n".join(executed_sql).lower())
        self.assertEqual(updated["revision"], 4)
        self.assertEqual(updated["evidence"], [{"url": "https://example.test"}])

    def test_postgres_claim_next_processing_job_uses_atomic_update(self) -> None:
        executed_sql: list[str] = []

        class FakeCursor:
            def __enter__(self) -> "FakeCursor":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def execute(self, sql: str, params: object = None) -> None:
                executed_sql.append(sql)

            def fetchone(self) -> tuple[str, str, dict[str, object]] | None:
                return (
                    "client-1",
                    "job-1",
                    {
                        "id": "job-1",
                        "client_id": "client-1",
                        "status": "processing",
                        "attempt_count": 1,
                    },
                )

        class FakeConnection:
            def __enter__(self) -> "FakeConnection":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def cursor(self) -> FakeCursor:
                return FakeCursor()

        store = PostgresWorkflowStore("postgresql://example", connect=lambda: FakeConnection())
        store.claim_next_processing_job()

        claim_sql = "\n".join(executed_sql).lower()
        self.assertIn("for update skip locked", claim_sql)
        self.assertIn("update workflow_records", claim_sql)
        self.assertIn("returning records.client_id, records.record_key, records.payload", claim_sql)

    def test_postgres_outgoing_attempt_claim_writes_attempt_and_sending_in_one_connection(self) -> None:
        executed_sql: list[str] = []
        fetches: list[object] = [
            None,
            (
                {
                    "invoice_id": "invoice-1",
                    "client_id": "client-a",
                    "status": "approved",
                    "document_type": "earsiv",
                    "ubl_sha256": "a" * 64,
                },
            ),
            None,
            ({"inserted": True},),
        ]

        class FakeCursor:
            def __enter__(self) -> "FakeCursor":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def execute(self, sql: str, params: object = None) -> None:
                executed_sql.append(sql)

            def fetchone(self) -> object:
                return fetches.pop(0)

        class FakeConnection:
            def __enter__(self) -> "FakeConnection":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def cursor(self) -> FakeCursor:
                return FakeCursor()

        connection = FakeConnection()
        store = PostgresWorkflowStore("postgresql://example", connect=lambda: connection)
        store._ensure_tenant = lambda: None  # type: ignore[method-assign]

        claimed, invoice, attempt = store.claim_outgoing_invoice_attempt(
            client_id="client-a",
            invoice_id="invoice-1",
            idempotency_key="send-1",
            ubl_sha256="a" * 64,
            provider="qnb_sandbox",
            provider_operation="faturaOlusturExt",
        )

        sql = "\n".join(executed_sql).lower()
        self.assertTrue(claimed)
        self.assertEqual(invoice["status"], "sending")
        self.assertEqual(attempt["state"], "claimed")
        self.assertIn("for update", sql)
        self.assertIn("outgoing_invoice_send_key", sql)
        self.assertIn("outgoing_invoice_send_attempt", sql)
        self.assertIn("update workflow_records", sql)

    def test_postgres_store_lists_research_profiles_and_benchmark_runs(self) -> None:
        class FakePostgresStore(PostgresWorkflowStore):
            def __init__(self) -> None:
                self.rows: list[dict[str, object]] = []

            def _upsert_record(
                self,
                client_id: str,
                record_type: str,
                record_key: str,
                payload: dict[str, object],
            ) -> dict[str, object]:
                self.rows.append(
                    {
                        "client_id": client_id,
                        "record_type": record_type,
                        "record_key": record_key,
                        "payload": payload,
                    }
                )
                return payload

            def _list_records(self, record_type: str, *, client_id: str | None = None) -> list[dict[str, object]]:
                return [
                    row
                    for row in self.rows
                    if row["record_type"] == record_type and (client_id is None or row["client_id"] == client_id)
                ]

        store = FakePostgresStore()
        store.rows.extend(
            [
                {
                    "client_id": "brand",
                    "record_type": "brand_research_profile",
                    "record_key": "old",
                    "payload": {"key": "old", "updated_at": "2026-01-01T00:00:00+00:00"},
                },
                {
                    "client_id": "brand",
                    "record_type": "brand_research_profile",
                    "record_key": "new",
                    "payload": {"key": "new", "updated_at": "2026-02-01T00:00:00+00:00"},
                },
            ]
        )

        profiles = store.list_research_profiles(kind="brand")
        first_run = store.save_research_benchmark_run({"case_count": 1, "accuracy": 0})
        second_run = store.save_research_benchmark_run({"case_count": 2, "accuracy": 50})
        runs = store.list_research_benchmark_runs(limit=1)

        self.assertEqual([profile["key"] for profile in profiles], ["new", "old"])
        self.assertEqual(first_run["run_type"], "benchmark")
        self.assertEqual(runs, [second_run])

    def test_json_store_applies_review_correction_to_stored_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="urban-care.pdf",
                result={
                    "file_name": "urban-care.pdf",
                    "simulated_status": "review_required",
                    "export_status": "review_required",
                    "review_reason_codes": ["business_out_of_scope"],
                    "risk_flags": [],
                    "is_balanced": True,
                    "selected_expense_account": "770.01",
                    "selected_supplier_account": "320.01.001",
                    "counterparty_match_code": "320.01.001",
                    "product_category": "kisisel_bakim",
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01.001", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )

            decision = store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "urban-care.pdf",
                    "action": "approve_with_changes",
                    "reviewer": "mali-musavir",
                    "corrected_account_code": "770.04.001",
                    "corrected_counterparty_code": "320.01.999",
                    "reason": "Pilot duzeltme",
                },
                learning_event={
                    "document_ref": "urban-care.pdf",
                    "scope": "client_rule",
                    "action": "approve_with_changes",
                    "category": "kisisel_bakim",
                    "corrected_account_code": "770.04.001",
                    "corrected_counterparty_code": "320.01.999",
                    "reason": "Pilot duzeltme",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            export_build = build_workspace_export_package(workspace)

        self.assertIn("corrected_document", decision)
        self.assertEqual(result["selected_expense_account"], "770.04.001")
        self.assertEqual(result["selected_supplier_account"], "320.01.999")
        self.assertEqual(result["counterparty_match_code"], "320.01.999")
        self.assertEqual(result["draft_lines"][0]["account_code"], "770.04.001")
        self.assertEqual(result["draft_lines"][1]["account_code"], "320.01.999")
        self.assertTrue(result["learning_rule_applied"])
        self.assertTrue(result["accountant_export_override"])
        self.assertEqual(result["export_status"], "export_ready")
        self.assertEqual(len(export_build.package.entries), 1)

    def test_json_store_resolves_direction_conflict_without_export_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="wrong-sales-upload.xml",
                result={
                    "file_name": "wrong-sales-upload.xml",
                    "simulated_status": "review_required",
                    "export_status": "review_required",
                    "review_reason_codes": ["direction_conflict_review"],
                    "risk_flags": [],
                    "is_balanced": True,
                    "accounting_direction": "purchase",
                    "direction_conflict": {
                        "status": "needs_review",
                        "intake_direction": "sales",
                        "detected_direction": "purchase",
                        "confidence": 95,
                        "evidence": ["client_tax_id_matches_recipient"],
                        "question_tr": "Bu belge Satıştan yüklendi; sistem mükellef açısından Alış olarak tespit etti. Alış yönüne geçirilsin mi?",
                    },
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )

            store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "wrong-sales-upload.xml",
                    "action": "accept_detected_direction",
                    "reviewer": "mali-musavir",
                    "reason": "Sistem yonu dogru.",
                },
                learning_event={
                    "document_ref": "wrong-sales-upload.xml",
                    "scope": "client_rule",
                    "action": "accept_detected_direction",
                    "category": "direction_conflict",
                    "reason": "Sistem yonu dogru.",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(result["accounting_direction"], "purchase")
        self.assertEqual(result["direction_conflict"]["status"], "resolved")
        self.assertEqual(result["direction_conflict"]["resolved_direction"], "purchase")
        self.assertEqual(result["direction_conflict"]["resolution"], "accepted_detected_direction")
        self.assertEqual(result["export_status"], "review_required")
        self.assertNotIn("direction_conflict_review", result["review_reason_codes"])

    def test_json_store_applies_manual_draft_lines_from_review_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="manual-required.pdf",
                result={
                    "file_name": "manual-required.pdf",
                    "simulated_status": "review_required",
                    "export_status": "review_required",
                    "review_reason_codes": ["manual_draft_required"],
                    "risk_flags": ["manual_draft_required"],
                    "is_balanced": False,
                    "draft_status": "manual_draft_required",
                    "draft_lines": [],
                },
            )

            store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "manual-required.pdf",
                    "action": "approve_with_changes",
                    "reviewer": "mali-musavir",
                    "reason": "Fis satirlari elle tamamlandi.",
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "191.01", "description": "KDV", "debit": "20.00", "credit": "0.00"},
                        {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "120.00"},
                    ],
                },
                learning_event={
                    "document_ref": "manual-required.pdf",
                    "scope": "client_rule",
                    "action": "approve_with_changes",
                    "category": "manuel_fis",
                    "reason": "Fis satirlari elle tamamlandi.",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(result["draft_status"], "manual_draft_completed")
        self.assertEqual(result["draft_lines"][0]["account_code"], "770.01")
        self.assertEqual(result["total_debit"], "120.00")
        self.assertEqual(result["total_credit"], "120.00")
        self.assertTrue(result["is_balanced"])
        self.assertEqual(result["export_status"], "export_ready")

    def test_json_store_exports_statement_entry_after_accountant_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="statement.csv",
                result={
                    "file_name": "statement.csv",
                    "simulated_status": "review_required",
                    "export_status": "review_required",
                    "review_reason_codes": ["statement_accountant_approval_required"],
                    "risk_flags": ["statement_accountant_approval_required"],
                    "is_balanced": True,
                    "statement_entries": [
                        {
                            "entry_type": "bank_payment",
                            "entry_date": "2026-05-02",
                            "description": "GIB ODEME",
                            "statement_line_no": 1,
                            "statement_fingerprint": "approved-statement-1",
                            "risk_flags": [],
                            "lines": [
                                {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                                {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                            ],
                        },
                    ],
                },
            )

            store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "statement.csv",
                    "action": "approve",
                    "reviewer": "mali-musavir",
                    "reason": "Banka satiri kontrol edildi",
                },
                learning_event={
                    "document_ref": "statement.csv",
                    "scope": "general_candidate",
                    "action": "approve",
                    "category": "tax_payment",
                    "corrected_account_code": "",
                    "corrected_counterparty_code": "",
                    "reason": "Banka satiri kontrol edildi",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            export_build = build_workspace_export_package(workspace)

        self.assertTrue(result["accountant_export_override"])
        self.assertEqual(result["export_status"], "export_ready")
        self.assertEqual(len(export_build.package.entries), 1)
        self.assertEqual(export_build.package.excluded_document_refs, ())

    def test_json_store_applies_statement_line_review_without_approving_other_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="statement.csv",
                result={
                    "file_name": "statement.csv",
                    "simulated_status": "review_required",
                    "export_status": "review_required",
                    "review_reason_codes": ["statement_accountant_approval_required"],
                    "risk_flags": ["statement_accountant_approval_required"],
                    "is_balanced": True,
                    "statement_lines": [
                        {
                            "line_no": 1,
                            "transaction_date": "2026-05-02",
                            "description": "TEDARIKCI ODEME",
                            "amount": "50.00",
                            "direction": "out",
                            "transaction_type": "bank_transfer_out",
                            "suggested_account_code": "320",
                            "confidence": 68,
                            "risk_flags": ["statement_review_required"],
                        },
                        {
                            "line_no": 2,
                            "transaction_date": "2026-05-03",
                            "description": "BASKA ODEME",
                            "amount": "60.00",
                            "direction": "out",
                            "transaction_type": "bank_transfer_out",
                            "suggested_account_code": "320",
                            "confidence": 68,
                            "risk_flags": ["statement_review_required"],
                        },
                    ],
                    "statement_entries": [
                        {
                            "entry_type": "bank_payment",
                            "entry_date": "2026-05-02",
                            "description": "TEDARIKCI ODEME",
                            "statement_line_no": 1,
                            "statement_fingerprint": "statement-line-1",
                            "risk_flags": ["statement_review_required"],
                            "lines": [
                                {"account_code": "320", "description": "bank_transfer_out", "debit": "50.00", "credit": "0.00"},
                                {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                            ],
                        },
                        {
                            "entry_type": "bank_payment",
                            "entry_date": "2026-05-03",
                            "description": "BASKA ODEME",
                            "statement_line_no": 2,
                            "statement_fingerprint": "statement-line-2",
                            "risk_flags": ["statement_review_required"],
                            "lines": [
                                {"account_code": "320", "description": "bank_transfer_out", "debit": "60.00", "credit": "0.00"},
                                {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "60.00"},
                            ],
                        },
                    ],
                },
            )

            store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "statement.csv",
                    "statement_line_no": 1,
                    "action": "approve_with_changes",
                    "reviewer": "mali-musavir",
                    "corrected_counterparty_code": "320.01.111",
                    "reason": "Ilk satir tedarikci cari hesabi ile onaylandi.",
                },
                learning_event={
                    "document_ref": "statement.csv",
                    "statement_line_no": 1,
                    "scope": "client_rule",
                    "action": "approve_with_changes",
                    "category": "tedarikci_odeme",
                    "corrected_account_code": "",
                    "corrected_counterparty_code": "320.01.111",
                    "reason": "Ilk satir tedarikci cari hesabi ile onaylandi.",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            export_build = build_workspace_export_package(workspace)

        self.assertEqual(result["statement_lines"][0]["accountant_review_status"], "approved")
        self.assertEqual(result["statement_lines"][0]["suggested_account_code"], "320.01.111")
        self.assertEqual(result["statement_lines"][1].get("accountant_review_status", ""), "")
        self.assertEqual(result["statement_entries"][0]["accountant_review_status"], "approved")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.111")
        self.assertEqual(result["statement_entries"][1]["lines"][0]["account_code"], "320")
        self.assertEqual(result["export_status"], "review_required")
        self.assertEqual(len(export_build.package.entries), 1)
        self.assertEqual(export_build.package.excluded_document_refs, ("statement.csv#statement-2",))

    def test_json_store_marks_export_package_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_export_package(
                client_id="client-1",
                package={
                    "export_type": "zirve_universal_csv",
                    "entry_count": 1,
                    "output_filename": "client-1-zirve.csv",
                },
            )

            downloaded = store.mark_export_package_downloaded(
                client_id="client-1",
                output_filename="client-1-zirve.csv",
            )
            workspace = store.get_workspace("client-1")

        self.assertIsNotNone(downloaded)
        self.assertEqual(downloaded["package"]["download_count"], 1)
        self.assertTrue(downloaded["package"]["downloaded_at"])
        self.assertEqual(workspace["export_packages"][0]["package"]["download_count"], 1)

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

    def test_processing_worker_persists_vat_split_review_record_for_pdf_invoice(self) -> None:
        sample_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-3"
            / "invoices"
            / "sales"
            / "einvoice.1a78033e-af6d-498e-8252-28c5b9132ccb.IF02026000000013.pdf"
        )
        if not sample_path.exists():
            self.skipTest("private pilot invoice sample missing")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Isitme Merkezi",
                    "tax_id": "21106530840",
                    "activity_description": "isitme cihazi satis ve servis",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "600.01", "normalized_account_code": "600.01", "account_name": "Yurt ici satislar", "is_detail_account": True},
                    {"raw_account_code": "391.01", "normalized_account_code": "391.01", "account_name": "Hesaplanan KDV", "is_detail_account": True},
                    {"raw_account_code": "120.01", "normalized_account_code": "120.01", "account_name": "Alicilar", "is_detail_account": True},
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "pdf-doc",
                    "document_ref": "pdf-doc",
                    "document_type": "invoice",
                    "original_file_name": sample_path.name,
                    "storage_path": str(sample_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="invoice",
                parser_kind=parser_kind_for_document_type("invoice"),
                intake_category="sales_invoice",
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["vat_split_review"]["status"], "exact")
        self.assertEqual(result["vat_split_review"]["lines"][0]["taxable_amount"], "15999.90")
        self.assertEqual(result["vat_split_review"]["similarity_key"], "vat_split:exact:20:vat_split_gross_total_validated")
        self.assertTrue(result["vat_split_review"]["learning_candidate"])
        self.assertIn("vat_split_classified", [event["step"] for event in workspace["document_pipeline_events"]])

    def test_processing_worker_parses_xml_invoice_and_runs_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "rexton.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ProfileID>TEMELFATURA</cbc:ProfileID>
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:UUID>123e4567-e89b-12d3-a456-426614174000</cbc:UUID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyLegalEntity><cbc:RegistrationName>Rexton Medikal</cbc:RegistrationName></cac:PartyLegalEntity>
      <cac:PartyTaxScheme><cbc:CompanyID>1234567890</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:InvoiceLine>
    <cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cac:Item><cbc:Name>Rexton RLi 20</cbc:Name></cac:Item>
  </cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>200.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>1200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Isitme Merkezi",
                    "tax_id": "1111111111",
                    "activity_description": "isitme cihazi satis ve servis",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                    {"raw_account_code": "191.01", "normalized_account_code": "191.01", "account_name": "Indirilecek KDV", "is_detail_account": True},
                    {"raw_account_code": "320.01.015", "normalized_account_code": "320.01.015", "account_name": "Rexton Medikal", "is_detail_account": True, "tax_id": "1234567890"},
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "xml-doc",
                    "document_ref": "xml-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "rexton.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["file_name"], "rexton.xml")
        self.assertEqual(result["payable_total"], "1200.00")
        self.assertEqual(result["product_category"], "isitme_cihazi")
        self.assertEqual(result["selected_supplier_account"], "320.01.015")
        self.assertEqual(result["export_status"], "review_required")
        self.assertEqual(result["ai_quality_scorecard"]["static"]["category"], "isitme_cihazi")
        self.assertEqual(result["ai_quality_scorecard"]["ai"]["provider"], "static_rules")
        self.assertEqual(result["ai_quality_scorecard"]["final"]["selected_account_code"], "")
        self.assertEqual(result["ai_quality_scorecard"]["context"]["client_nace_code"], "")
        self.assertEqual(result["ai_quality_scorecard"]["context"]["account_candidate_count"], result["ai_account_candidate_count"])
        self.assertEqual(result["draft_lines"], [])
        pipeline_steps = [event["step"] for event in workspace["document_pipeline_events"]]
        self.assertIn("ai_correction_required", pipeline_steps)
        self.assertNotIn("journal_draft_ready", pipeline_steps)
        self.assertNotIn("export_ready", pipeline_steps)
        self.assertEqual(workspace["document_pipeline_events"][1]["message_tr"], "Belge parse edildi.")
        correction = next(event for event in workspace["document_pipeline_events"] if event["step"] == "ai_correction_required")
        self.assertIn("duzeltme", correction["message_tr"].lower())

    def test_processing_worker_records_learning_rule_applied_pipeline_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "kargo.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>KRG202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyLegalEntity><cbc:RegistrationName>Yurtici Kargo</cbc:RegistrationName></cac:PartyLegalEntity>
      <cac:PartyTaxScheme><cbc:CompanyID>9860008925</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party><cac:PartyTaxScheme><cbc:CompanyID>1111111111</cbc:CompanyID></cac:PartyTaxScheme></cac:Party>
  </cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cac:Item><cbc:Name>Kargo hizmet bedeli</cbc:Name></cac:Item>
  </cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>20.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>100.00</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount>120.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>120.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Lojistik",
                    "tax_id": "1111111111",
                    "activity_description": "lojistik hizmetleri",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                    {"raw_account_code": "760.03.010", "normalized_account_code": "760.03.010", "account_name": "Kargo gideri", "is_detail_account": True},
                    {"raw_account_code": "191.01", "normalized_account_code": "191.01", "account_name": "Indirilecek KDV", "is_detail_account": True},
                    {"raw_account_code": "320.9860008925", "normalized_account_code": "320.9860008925", "account_name": "Yurtici Kargo", "is_detail_account": True, "tax_id": "9860008925"},
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                ],
            )
            store.save_review_decision(
                client_id="client-1",
                decision={"document_ref": "source-kargo.xml", "action": "suggest_for_similar"},
                learning_event={
                    "document_ref": "source-kargo.xml",
                    "scope": "client_rule",
                    "action": "suggest_for_similar",
                    "category": "kargo",
                    "corrected_account_code": "760.03.010",
                    "corrected_counterparty_code": "320.9860008925",
                    "reason": "Yurtici Kargo kargo gideri olarak izlenir.",
                    "accounting_intent": "kargo_gideri",
                    "accounting_intent_confidence": 90,
                    "normalized_terms": ["yurtici", "kargo", "hizmet"],
                    "counterparty_tax_id": "9860008925",
                    "counterparty_title": "Yurtici Kargo",
                    "automation_candidate": True,
                    "learning_rule_source_summary": "Yurtici Kargo onceki musavir kararindan eslesti.",
                },
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "kargo-doc",
                    "document_ref": "kargo-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "kargo.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertFalse(result["learning_rule_applied"])
        self.assertEqual(result["learning_audit"]["status"], "evidence_only")
        self.assertNotIn("learning_rule_applied", [event["step"] for event in workspace["document_pipeline_events"]])
        self.assertEqual(result["selected_expense_account"], "")

    def test_processing_worker_records_ai_decision_events_and_turkish_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "rexton.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Medikal Tedarik</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>ZX Sonic Pro 9 receiver</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>200.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount><cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>1200.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Isitme Merkezi",
                    "tax_id": "1111111111",
                    "activity_description": "isitme cihazi satis ve servis",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "xml-doc",
                    "document_ref": "xml-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "rexton.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )
            classifier = StaticFirstClassifier(
                provider=FakeProductProvider(
                    {
                        "category": "isitme_cihazi",
                        "confidence": 84,
                        "reason": "Model işitme cihazı ürün ailesine benziyor.",
                        "evidence": ["ai:model_family"],
                        "suggested_account_code": "770.01",
                        "suggested_counterparty_code": "320.01",
                        "risk_flags": ["accountant_review_required"],
                        "account_reason": "Mevcut hesap adayları içinden gider ve cari önerildi.",
                    }
                ),
                policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
            )

            process_queued_documents(store, product_classifier=classifier)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            pipeline_steps = [event["step"] for event in workspace["document_pipeline_events"]]

        self.assertIn("ai_provider_selected", pipeline_steps)
        self.assertIn("ai_decision_ready", pipeline_steps)
        self.assertIn("accountant_ai_explanation_ready", pipeline_steps)
        self.assertIn("AI", result["ai_explanation_tr"])
        self.assertIn("karar", result["ai_explanation_tr"])
        self.assertIn("fake_llm", result["ai_explanation_tr"])
        self.assertTrue(result["ai_trace"])
        self.assertEqual(result["ai_trace"][0]["stage"], "final_account")
        self.assertEqual(result["ai_trace"][0]["provider"], "fake_llm")
        self.assertEqual(result["ai_trace"][0]["validation_status"], "accepted")
        self.assertEqual(result["ai_trace"][0]["request_payload"]["candidate_strategy"]["stage"], "final_account")
        self.assertEqual(result["technical_details"]["ai_trace"], result["ai_trace"])

    def test_processing_worker_sends_nace_research_and_chart_semantics_to_ai(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "rexton.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Medikal Tedarik</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>ZX Sonic Pro 9 receiver</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>200.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount><cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>1200.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Isitme Merkezi",
                    "tax_id": "1111111111",
                    "nace_code": "47.74.01",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.save_nace_research_profile(
                nace_code="477401",
                profile={
                    "activity_title": "Tibbi ve ortopedik urunlerin perakende ticareti",
                    "scope_summary": "Isitme cihazi satis faaliyetini kapsar.",
                    "included_goods_services": ["isitme cihazi", "pil", "kalip"],
                    "likely_business_expenses": ["medikal sarf"],
                    "unlikely_or_personal_items": [],
                    "bank_statement_hints": [],
                    "activity_tags": ["hearing_aid", "medical_retail"],
                    "source_urls": ["https://example.test/nace-477401"],
                },
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {
                        "raw_account_code": "153.01.001",
                        "normalized_account_code": "153.01.001",
                        "account_name": "ALINAN CIHAZLAR",
                        "is_detail_account": True,
                    },
                    {
                        "raw_account_code": "153.01.002",
                        "normalized_account_code": "153.01.002",
                        "account_name": "Pil Ve Kalip Montaj Kit Macun Alis",
                        "is_detail_account": True,
                    },
                    {
                        "raw_account_code": "191.01.020",
                        "normalized_account_code": "191.01.020",
                        "account_name": "Yuzde 20 Indirilecek KDV",
                        "is_detail_account": True,
                    },
                    {
                        "raw_account_code": "320.01",
                        "normalized_account_code": "320.01",
                        "account_name": "Medikal Tedarik",
                        "is_detail_account": True,
                    },
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "xml-doc",
                    "document_ref": "xml-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "rexton.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )
            provider = FakeProductProvider(
                {
                    "category": "isitme_cihazi",
                    "confidence": 88,
                    "reason": "NACE ve hesap adaylari isitme cihazi stok alimiyla uyumlu.",
                    "evidence": ["nace:477401", "account:153.01.001"],
                    "suggested_account_code": "153.01.001",
                    "suggested_counterparty_code": "320.01",
                    "risk_flags": [],
                    "account_reason": "153 stok hesabi cihaz alimi icin en guclu aday.",
                    "product_identity": "isitme cihazi receiver",
                    "needs_research": False,
                    "research_query": "",
                }
            )
            classifier = StaticFirstClassifier(
                provider=provider,
                policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
            )

            process_queued_documents(store, product_classifier=classifier)

        self.assertEqual(len(provider.requests), 1)
        payload = provider.requests[0].to_schema_payload()
        self.assertEqual(payload["nace_research_summary"], "Isitme cihazi satis faaliyetini kapsar.")
        self.assertIn("hearing_aid", payload["activity_tags"])
        account_details = {
            str(item["code"]): item for item in payload["account_candidate_details"] if isinstance(item, dict)
        }
        self.assertIn("153.01.001", account_details)
        self.assertIn("hearing_device_stock", account_details["153.01.001"]["semantic_roles"])

    def test_processing_worker_uses_cached_nace_activity_tags_as_match_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "gida.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>GID202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-04</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyLegalEntity><cbc:RegistrationName>Hal Tedarik</cbc:RegistrationName></cac:PartyLegalEntity>
      <cac:PartyTaxScheme><cbc:CompanyID>2222222222</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:InvoiceLine><cbc:InvoicedQuantity>10</cbc:InvoicedQuantity><cac:Item><cbc:Name>Domates gida alimi</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>20.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>10</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>200.00</cbc:LineExtensionAmount><cbc:TaxInclusiveAmount>220.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>220.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Lokanta",
                    "tax_id": "1111111111",
                    "nace_code": "99.99.99",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.save_nace_research_profile(
                nace_code="999999",
                profile={
                    "activity_title": "Yiyecek hizmeti pilot cache",
                    "scope_summary": "Gida alimlari faaliyet icinde kabul edilir.",
                    "included_goods_services": ["gida alimi"],
                    "likely_business_expenses": ["sebze", "ambalaj"],
                    "unlikely_or_personal_items": [],
                    "bank_statement_hints": [],
                    "activity_tags": ["food_service"],
                    "source_urls": ["https://example.test/nace-food"],
                },
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Gider", "is_detail_account": True},
                    {"raw_account_code": "191.01", "normalized_account_code": "191.01", "account_name": "KDV", "is_detail_account": True},
                    {"raw_account_code": "320.01.020", "normalized_account_code": "320.01.020", "account_name": "Hal Tedarik", "is_detail_account": True, "tax_id": "2222222222"},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "gida-doc",
                    "document_ref": "gida-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "gida.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )

            process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            pipeline_steps = [event["step"] for event in workspace["document_pipeline_events"]]

        self.assertEqual(result["product_category"], "gida_alimi")
        self.assertEqual(result["business_relevance_relation"], "core_business")
        self.assertIn("activity_tag:food_service", result["business_relevance_evidence"])
        self.assertNotIn("weak_match", pipeline_steps)

    def test_processing_worker_records_ai_provider_failure_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "unknown.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>UNK202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-04</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Bilinmeyen Tedarik</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>ZX Pilot Kalem</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>20.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>100.00</cbc:LineExtensionAmount><cbc:TaxInclusiveAmount>120.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>120.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Sirket",
                    "tax_id": "1111111111",
                    "activity_description": "pilot faaliyet",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                    {"raw_account_code": "191.01", "normalized_account_code": "191.01", "account_name": "Indirilecek KDV", "is_detail_account": True},
                    {"raw_account_code": "320.01", "normalized_account_code": "320.01", "account_name": "Bilinmeyen Tedarik", "is_detail_account": True},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "unknown-doc",
                    "document_ref": "unknown-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "unknown.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )
            classifier = StaticFirstClassifier(
                provider=RaisingProductProvider(),
                policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
            )

            process_queued_documents(store, product_classifier=classifier)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            failed_event = next(event for event in workspace["document_pipeline_events"] if event["step"] == "ai_provider_failed")
            correction_event = next(
                event
                for event in workspace["document_pipeline_events"]
                if event["step"] == "ai_correction_required"
            )

        self.assertEqual(failed_event["status"], "error")
        self.assertEqual(failed_event["details"]["provider"], "raising_llm")
        self.assertNotIn("fallback", failed_event["message_tr"].lower())
        self.assertEqual(correction_event["status"], "warning")
        self.assertIn("ai_provider_error", str(correction_event["details"]))
        self.assertEqual(result["ai_resolution_status"], "ai_correction_required")
        self.assertEqual(result["ai_retry_reason"], "ai_provider_error")
        self.assertEqual(result["static_fallback_account"], "")
        self.assertTrue(result["static_fallback_suppressed"])
        self.assertEqual(result["selected_expense_account"], "")
        self.assertEqual(result["draft_lines"], [])
        self.assertEqual(result["draft_status"], "ai_correction_required")
        self.assertIn("duzelt", result["accountant_summary"].lower())
        self.assertIn("ai_correction_required", str(result["technical_details"]))
        self.assertIn("Provider raising_llm hata verdi", result["ai_explanation_tr"])
        self.assertIn("ai_provider_error", result["ai_explanation_tr"])

    def test_processing_worker_parses_bank_statement_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction,balance_after\n"
                "2026-05-03,GIB ODEME,500.00,out,9500.00\n"
                "2026-05-04,SGK PRIM,700.00,out,8800.00\n"
                "2026-05-05,POS BLOKE,1200.00,in,10000.00\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "review_required")
        self.assertTrue(result["is_balanced"])
        self.assertEqual(result["draft_quality"], "statement_entries_ready")
        self.assertEqual(len(result["statement_entries"]), 3)
        self.assertEqual(result["statement_entries"][0]["statement_line_no"], 1)
        self.assertTrue(result["statement_entries"][0]["statement_fingerprint"])
        self.assertEqual(result["statement_entries"][0]["source_document_ref"], "bank-doc")
        self.assertEqual(result["statement_entries"][0]["total_debit"], "500.00")
        self.assertEqual(result["statement_entries"][0]["total_credit"], "500.00")
        self.assertTrue(result["draft_lines"])
        self.assertEqual(result["statement_lines"][0]["transaction_type"], "tax_payment")
        self.assertEqual(result["statement_lines"][1]["suggested_account_code"], "361")
        self.assertEqual(result["statement_lines"][2]["transaction_type"], "pos_blocked")

    def test_statement_processing_result_attaches_ai_suggestions_without_export_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction\n"
                "2026-05-03,BILINMEYEN TEDARIKCI ODEME,1200.00,out\n",
                encoding="utf-8",
            )
            provider = FakeStatementSuggestionProvider(
                {
                    "transaction_type": "counterparty_payment",
                    "suggested_account_code": "320.01.123",
                    "confidence": 82,
                    "reason": "Satir tedarikci odemesi gibi gorunuyor.",
                    "evidence": ["tedarikci", "odeme"],
                }
            )

            result = build_statement_processing_result(
                {
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                },
                {"document_type": "bank_statement"},
                statement_path,
                {},
                statement_ai_provider=provider,
                statement_ai_policy=StatementAiSuggestionPolicy(enabled=True),
            )

        self.assertEqual(len(provider.requests), 1)
        self.assertTrue(result["ai_classification_used"])
        self.assertEqual(result["ai_classification_provider"], "fake_statement_llm")
        self.assertEqual(result["statement_ai_suggestions"][0]["line_no"], 1)
        self.assertEqual(result["statement_ai_suggestions"][0]["suggested_account_code"], "320.01.123")
        self.assertFalse(result["statement_ai_suggestions"][0]["export_allowed"])
        self.assertEqual(result["export_status"], "review_required")

    def test_processing_worker_records_ai_usage_when_statement_ai_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction\n"
                "2026-05-03,BILINMEYEN TEDARIKCI ODEME,1200.00,out\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {"raw_account_code": "320.01.123", "normalized_account_code": "320.01.123", "account_name": "Bilinmeyen Tedarikci", "is_detail_account": True},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )
            provider = FakeStatementSuggestionProvider(
                {
                    "transaction_type": "counterparty_payment",
                    "suggested_account_code": "320.01.123",
                    "confidence": 82,
                    "reason": "Satir tedarikci odemesi gibi gorunuyor.",
                    "evidence": ["tedarikci", "odeme"],
                }
            )

            summary = process_queued_documents(
                store,
                statement_ai_provider=provider,
                statement_ai_policy=StatementAiSuggestionPolicy(enabled=True, confidence_threshold=101),
            )
            workspace = store.get_workspace("client-1")
            usage_events = store.list_ai_usage(client_id="client-1")

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(len(workspace["operation_events"]), 0)
        self.assertEqual(len(usage_events), 1)
        self.assertEqual(usage_events[0]["provider"], "fake_statement_llm")
        self.assertEqual(usage_events[0]["operation"], "worker_ai_assisted_draft")
        self.assertTrue(usage_events[0]["ai_used"])
        self.assertGreater(int(usage_events[0]["input_chars"]), 0)

    def test_processing_worker_matches_bank_statement_counterparty_by_tax_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction,tax_id,counterparty_name\n"
                "2026-05-03,Rexton Medikal odeme,1200.00,out,1234567890,Rexton Medikal\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {"raw_account_code": "320.01.015", "normalized_account_code": "320.01.015", "account_name": "Rexton Medikal", "is_detail_account": True, "tax_id": "1234567890"},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "review_required")
        self.assertIn("statement_accountant_approval_required", result["review_reason_codes"])
        self.assertEqual(result["statement_lines"][0]["transaction_type"], "counterparty_payment")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_code"], "320.01.015")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_reason"], "tax_id_exact")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.015")

    def test_processing_worker_matches_bank_statement_counterparty_by_iban(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction,iban\n"
                "2026-05-03,Tedarikci odeme,1200.00,out,TR12 0000 0000 0000 0000 0000 01\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {
                        "raw_account_code": "320.01.777",
                        "normalized_account_code": "320.01.777",
                        "account_name": "IBAN Tedarikci",
                        "is_detail_account": True,
                        "iban": "TR120000000000000000000001",
                    },
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "review_required")
        self.assertIn("statement_accountant_approval_required", result["review_reason_codes"])
        self.assertEqual(result["statement_lines"][0]["counterparty_match_code"], "320.01.777")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_reason"], "iban_exact")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.777")

    def test_processing_worker_matches_bank_statement_counterparty_by_learning_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction\n"
                "2026-05-03,Kolay Soft hizmet odemesi,900.00,out\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {
                        "raw_account_code": "320.01.888",
                        "normalized_account_code": "320.01.888",
                        "account_name": "Kolay Soft",
                        "is_detail_account": True,
                    },
                ],
            )
            store.save_review_decision(
                client_id="client-1",
                decision={"document_ref": "old-kolay-soft.pdf", "action": "approve_with_changes"},
                learning_event={
                    "document_ref": "old-kolay-soft.pdf",
                    "scope": "client_rule",
                    "action": "approve_with_changes",
                    "category": "kolay_soft",
                    "corrected_account_code": "770.01",
                    "corrected_counterparty_code": "320.01.888",
                    "reason": "Kolay Soft e-fatura hizmeti",
                    "automation_candidate": True,
                },
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "review_required")
        self.assertIn("statement_accountant_approval_required", result["review_reason_codes"])
        self.assertTrue(result["learning_rule_applied"])
        self.assertEqual(result["statement_lines"][0]["counterparty_match_code"], "320.01.888")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_reason"], "learning_event")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.888")

    def test_private_intake_manifest_imports_chart_accounts_and_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source_dir = base / "pilot"
            source_dir.mkdir()
            (source_dir / "zirve_hesap_plani.csv").write_text(
                "account_code,account_name,is_detail_account\n"
                "102.01,Banka,true\n"
                "360,Vergi Borclari,true\n",
                encoding="utf-8",
            )
            (source_dir / "banka_ekstresi.csv").write_text(
                "transaction_date,description,amount,direction\n"
                "2026-06-03,GIB ODEME,100.00,out\n",
                encoding="utf-8",
            )
            manifest_path = base / "intake_manifest.json"
            manifest_path.write_text(
                """
{
  "source_dir": "%s",
  "files": [
    {
      "client_id": "client-1",
      "client_name": "Pilot",
      "relative_path": "zirve_hesap_plani.csv",
      "file_name": "zirve_hesap_plani.csv",
      "extension": ".csv",
      "document_kind": "chart_accounts"
    },
    {
      "client_id": "client-1",
      "client_name": "Pilot",
      "relative_path": "banka_ekstresi.csv",
      "file_name": "banka_ekstresi.csv",
      "extension": ".csv",
      "document_kind": "bank_statement"
    }
  ]
}
"""
                % str(source_dir).replace("\\", "\\\\"),
                encoding="utf-8",
            )

            summary = import_manifest(
                manifest_path=manifest_path,
                source_dir=None,
                document_storage_path=base / "documents",
                output_path=base / "summary.json",
                client_id="client-1",
                client_name="Pilot",
                tax_id="1111111111",
                activity="genel isletme",
                run_worker=True,
                store_backend="json",
                json_store_path=base / "store.json",
            )
            workspace = JsonWorkflowStore(base / "store.json").get_workspace("client-1")

        self.assertEqual(summary["chart_account_count"], 2)
        self.assertEqual(summary["imported_document_count"], 1)
        self.assertEqual(workspace["chart_accounts"]["account_count"], 2)
        self.assertEqual(workspace["processing_jobs"][0]["status"], "completed")
        self.assertEqual(workspace["documents"][0]["result"]["statement_lines"][0]["transaction_type"], "tax_payment")
        self.assertEqual(workspace["operation_events"][-1]["event_type"], "private_intake_imported")

    def test_store_factory_selects_json_and_requires_postgres_dsn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = build_workflow_store(store_backend="json", json_path=Path(temp_dir) / "store.json")

        self.assertIsInstance(store, JsonWorkflowStore)
        with self.assertRaises(ValueError):
            build_workflow_store(store_backend="postgres", postgres_dsn="")


if __name__ == "__main__":
    unittest.main()
