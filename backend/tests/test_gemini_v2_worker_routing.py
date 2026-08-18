from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.document_ai_artifacts import ArtifactKind
from app.persistence.workflow_store import JsonWorkflowStore
from app.workflows.document_processing import process_next_job_once
from backend.tests.test_gemini_invoice_pipeline_v2 import (
    _AccountingProvider,
    _ExtractionProvider,
    _canonical_payload,
    _complete_proposal,
    _workspace,
)


class _PoisonGeminiProvider:
    def __init__(self) -> None:
        self.calls = 0

    def extract_invoice_canonical(self, request):
        self.calls += 1
        raise AssertionError("Gemini V2 must not run for this document")

    def classify_product(self, request):
        self.calls += 1
        raise AssertionError("Gemini V2 must not run for this document")


class GeminiV2WorkerRoutingTests(unittest.TestCase):
    def test_transient_postgres_operational_error_moves_job_to_retry_wait(self) -> None:
        import psycopg

        with tempfile.TemporaryDirectory() as temporary:
            store = self._store_with_document(Path(temporary))
            original_get_workspace = store.get_workspace
            calls = 0

            def flaky_get_workspace(client_id: str):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise psycopg.OperationalError("database connection interrupted")
                return original_get_workspace(client_id)

            store.get_workspace = flaky_get_workspace  # type: ignore[method-assign]
            summary = process_next_job_once(store, research_runtime={})
            job = original_get_workspace("taxpayer-1")["processing_jobs"][0]

        self.assertEqual(
            summary,
            {"processed_count": 1, "completed_count": 0, "failed_count": 0},
        )
        self.assertEqual(job["status"], "retry_wait")
        self.assertGreaterEqual(int(job["retry_step"]), 1)
        self.assertTrue(job["next_attempt_at"])
        self.assertIn("database connection interrupted", job["error_message"])

    def _store_with_document(
        self,
        root: Path,
        *,
        document_type: str = "invoice",
        suffix: str = ".pdf",
        content: bytes = b"%PDF-1.7\n%worker-v2-native-only\n",
    ) -> JsonWorkflowStore:
        store = JsonWorkflowStore(root / "phase0_store.json")
        store.upsert_client(
            client_id="taxpayer-1",
            profile={
                "client_id": "taxpayer-1",
                "tax_id": "1111111111",
                "activity_description": "Retail",
                "nace_code": "47.74",
            },
            onboarding={"is_ready": True, "missing_fields": []},
        )
        store.replace_chart_accounts(
            client_id="taxpayer-1",
            accounts=list(_workspace()["chart_accounts"]["accounts"]),
        )
        source = root / f"invoice{suffix}"
        source.write_bytes(content)
        store.save_uploaded_document(
            client_id="taxpayer-1",
            document={
                "document_id": "document-1",
                "document_ref": "document-1",
                "source_file_id": "source-1",
                "document_type": document_type,
                "intake_category": "purchase_invoice",
                "storage_path": str(source),
                "content_type": (
                    "application/pdf" if suffix == ".pdf" else "application/xml"
                ),
                "original_file_name": source.name,
                "status": "stored",
            },
        )
        store.create_processing_job(
            client_id="taxpayer-1",
            document_ref="document-1",
            document_type=document_type,
            parser_kind="pdf" if suffix == ".pdf" else "xml",
            intake_category="purchase_invoice",
        )
        return store

    def test_flagged_pdf_runs_real_v2_pipeline_and_preserves_partial_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self._store_with_document(root)
            extraction = _ExtractionProvider(
                _canonical_payload("purchase", warning="worker_v2_warning")
            )
            accounting = _AccountingProvider([_complete_proposal])

            with patch.dict(
                os.environ,
                {"FISORA_GEMINI_PDF_V2_ENABLED": "true"},
                clear=False,
            ), patch(
                "app.workflows.document_processing.build_processing_result",
                side_effect=AssertionError(
                    "flagged Gemini V2 PDF must not enter legacy parser workflow"
                ),
            ):
                summary = process_next_job_once(
                    store,
                    extraction_provider=extraction,
                    accounting_provider=accounting,
                    artifact_repository=store.document_ai_artifact_repository,
                    research_runtime={},
                )

            workspace = store.get_workspace("taxpayer-1")
            result = workspace["documents"][0]["result"]
            job = workspace["processing_jobs"][0]
            artifacts = store.document_ai_artifact_repository.list_for_document(
                tenant_id="default",
                taxpayer_id="taxpayer-1",
                document_id="document-1",
            )

        self.assertEqual(
            summary,
            {"processed_count": 1, "completed_count": 1, "failed_count": 0},
        )
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(extraction.requests), 1)
        self.assertTrue(accounting.requests)
        self.assertEqual(result["selected_expense_account"], "770.01")
        self.assertEqual(result["selected_purchase_vat_account"], "191.20")
        self.assertEqual(result["selected_supplier_account"], "320.01")
        self.assertEqual(result["accounting_direction"], "purchase")
        self.assertTrue(result["draft_lines"])
        self.assertTrue(result["is_balanced"])
        self.assertIn("worker_v2_warning", result["pipeline_warnings"])
        self.assertEqual(result["export_status"], "review_required")
        self.assertTrue(
            {
                ArtifactKind.PROVIDER_RECEIPT,
                ArtifactKind.CANONICAL_INVOICE_FORM,
                ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                ArtifactKind.ACCOUNTING_PROPOSAL,
            }.issubset({item.kind for item in artifacts})
        )
        self.assertIn(
            "gemini_pdf_v2_selected",
            [item["step"] for item in workspace["document_pipeline_events"]],
        )

    def test_worker_assigns_exhaustive_group_once_and_persists_experiment_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = self._store_with_document(root)
            extraction = _ExtractionProvider(_canonical_payload("purchase"))
            accounting = _AccountingProvider(
                [_complete_proposal, _complete_proposal, _complete_proposal]
            )

            with patch.dict(
                os.environ,
                {
                    "FISORA_GEMINI_PDF_V2_ENABLED": "true",
                    "FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT": "100",
                    "FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES": "3000000",
                },
                clear=False,
            ):
                summary = process_next_job_once(
                    store,
                    extraction_provider=extraction,
                    accounting_provider=accounting,
                    artifact_repository=store.document_ai_artifact_repository,
                    research_runtime={},
                )

            receipts = [
                item
                for item in store.document_ai_artifact_repository.list_for_document(
                    tenant_id="default",
                    taxpayer_id="taxpayer-1",
                    document_id="document-1",
                )
                if item.kind is ArtifactKind.PROVIDER_RECEIPT
                and item.stage == "accounting_selection"
            ]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(len(accounting.requests), 3)
        self.assertTrue(receipts)
        self.assertTrue(all(item.metadata["candidate_discovery_mode"] == "exhaustive" for item in receipts))
        self.assertTrue(all(item.metadata["candidate_experiment_group"] == "experiment" for item in receipts))
        self.assertEqual(len({item.metadata["candidate_experiment_bucket"] for item in receipts}), 1)

    def test_flagged_pdf_missing_runtime_retries_without_parser_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store_with_document(Path(temporary))

            with patch.dict(
                os.environ,
                {
                    "FISORA_GEMINI_PDF_V2_ENABLED": "true",
                    "GEMINI_API_KEY": "",
                },
                clear=False,
            ):
                summary = process_next_job_once(store, research_runtime={})

            workspace = store.get_workspace("taxpayer-1")
            job = workspace["processing_jobs"][0]

        self.assertEqual(
            summary,
            {"processed_count": 1, "completed_count": 0, "failed_count": 0},
        )
        self.assertEqual(job["status"], "retry_wait")
        self.assertIn("gemini_api_key_missing", job["error_message"])
        self.assertEqual(workspace["documents"], [])
        failure_events = [
            item
            for item in workspace["document_pipeline_events"]
            if item["status"] == "error"
        ]
        self.assertTrue(failure_events)
        self.assertNotIn("parser_failed", [item["step"] for item in failure_events])

    def test_flag_does_not_route_xml_into_gemini_v2(self) -> None:
        xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
 <cbc:ID>INV-XML-1</cbc:ID><cbc:IssueDate>2026-08-12</cbc:IssueDate>
 <cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Supplier</cbc:Name></cac:PartyName><cac:PartyTaxScheme><cbc:CompanyID>1234567890</cbc:CompanyID><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme></cac:Party></cac:AccountingSupplierParty>
 <cac:AccountingCustomerParty><cac:Party><cac:PartyName><cbc:Name>Customer</cbc:Name></cac:PartyName><cac:PartyTaxScheme><cbc:CompanyID>1111111111</cbc:CompanyID><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme></cac:Party></cac:AccountingCustomerParty>
 <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Service</cbc:Name></cac:Item></cac:InvoiceLine>
 <cac:LegalMonetaryTotal><cbc:TaxInclusiveAmount currencyID="TRY">100.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="TRY">100.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>'''
        with tempfile.TemporaryDirectory() as temporary:
            store = self._store_with_document(
                Path(temporary),
                document_type="einvoice_xml",
                suffix=".xml",
                content=xml,
            )
            poison = _PoisonGeminiProvider()

            with patch.dict(
                os.environ,
                {"FISORA_GEMINI_PDF_V2_ENABLED": "true"},
                clear=False,
            ):
                summary = process_next_job_once(
                    store,
                    extraction_provider=poison,
                    accounting_provider=poison,
                    artifact_repository=store.document_ai_artifact_repository,
                    research_runtime={},
                )

        self.assertEqual(poison.calls, 0)
        self.assertEqual(summary["completed_count"], 1)

    def test_production_configuration_exposes_flag_off_and_dedicated_model(self) -> None:
        compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
        example = (ROOT / "deploy" / "production.env.example").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "FISORA_GEMINI_PDF_V2_ENABLED: ${FISORA_GEMINI_PDF_V2_ENABLED:-false}",
            compose,
        )
        self.assertIn(
            "FISORA_GEMINI_PDF_V2_MODEL: ${FISORA_GEMINI_PDF_V2_MODEL:-gemini-3.5-flash-lite}",
            compose,
        )
        self.assertIn("FISORA_GEMINI_PDF_V2_ENABLED=false", example)
        self.assertIn(
            "FISORA_GEMINI_PDF_V2_MODEL=gemini-3.5-flash-lite", example
        )
        self.assertIn(
            "FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT: ${FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT:-0}",
            compose,
        )
        self.assertIn(
            "FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES: ${FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES:-3000000}",
            compose,
        )
        self.assertIn("FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT=0", example)
        self.assertIn("FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES=3000000", example)

    def test_production_configuration_passes_all_gemini_project_slots_to_backend_and_worker(self) -> None:
        compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
        example = (ROOT / "deploy" / "production.env.example").read_text(encoding="utf-8")

        def service_environment(service: str) -> str:
            lines = compose.splitlines()
            start = lines.index(f"  {service}:")
            environment_start = next(
                index for index in range(start, len(lines))
                if lines[index] == "    environment:"
            )
            end = next(
                (
                    index
                    for index in range(environment_start + 1, len(lines))
                    if lines[index].startswith("  ")
                    and not lines[index].startswith("    ")
                    and lines[index].endswith(":")
                ),
                len(lines),
            )
            return "\n".join(lines[environment_start:end])

        backend_environment = service_environment("backend")
        worker_environment = service_environment("worker")

        for index in range(2, 9):
            entry = f"GEMINI_API_KEY_{index}: ${{GEMINI_API_KEY_{index}:-}}"
            self.assertIn(entry, backend_environment)
            self.assertIn(entry, worker_environment)
            self.assertIn(f"GEMINI_API_KEY_{index}=", example)
        for index in range(1, 9):
            entry = f"FISORA_GEMINI_REQUESTS_PER_MINUTE_{index}: ${{FISORA_GEMINI_REQUESTS_PER_MINUTE_{index}:-}}"
            self.assertIn(entry, backend_environment)
            self.assertIn(entry, worker_environment)
            self.assertIn(f"FISORA_GEMINI_REQUESTS_PER_MINUTE_{index}=", example)
        cooldown = "FISORA_GEMINI_PROJECT_COOLDOWN_SECONDS: ${FISORA_GEMINI_PROJECT_COOLDOWN_SECONDS:-60}"
        self.assertIn(cooldown, backend_environment)
        self.assertIn(cooldown, worker_environment)
        self.assertIn("FISORA_GEMINI_PROJECT_COOLDOWN_SECONDS=60", example)

    def test_worker_runtime_reuses_pool_when_primary_is_blank_and_secondary_is_present(self) -> None:
        import app.worker as worker

        previous_runtime = worker._GEMINI_RUNTIME
        try:
            worker._GEMINI_RUNTIME = None
            with patch.dict(
                os.environ,
                {
                    "FISORA_GEMINI_PDF_V2_ENABLED": "true",
                    "GEMINI_API_KEY": "",
                    "GEMINI_API_KEY_2": "secondary-worker-secret",
                },
                clear=False,
            ):
                first = worker._gemini_runtime_for_worker()
                os.environ["GEMINI_API_KEY_2"] = "different-secret-after-start"
                second = worker._gemini_runtime_for_worker()

            self.assertIsNotNone(first)
            self.assertIs(first, second)
            assert first is not None
            assert first.provider is not None
            self.assertTrue(first.available)
            self.assertEqual(first.provider.configured_credential_slots, ("GEMINI_API_KEY_SLOT_2",))
        finally:
            worker._GEMINI_RUNTIME = previous_runtime


if __name__ == "__main__":
    unittest.main()
