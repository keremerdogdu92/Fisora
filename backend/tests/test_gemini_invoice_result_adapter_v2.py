from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository
from app.workflows.gemini_invoice_pipeline import GeminiInvoicePipelineRequest, run_gemini_invoice_pipeline_v2
from app.workflows.gemini_invoice_result_adapter import to_document_processing_payload
from backend.tests.test_gemini_invoice_pipeline_v2 import (
    _AccountingProvider,
    _ExtractionProvider,
    _canonical_payload,
    _complete_proposal,
    _workspace,
)


class GeminiInvoiceResultAdapterV2Tests(unittest.TestCase):
    def test_adapter_preserves_selected_candidate_id_for_treatment_review_line(self) -> None:
        def incomplete(request):
            payload = _complete_proposal(request)
            for decision in payload["decisions"]:
                if decision["decision_ref"].startswith("tax:"):
                    decision["selected_treatment"] = ""
            return payload

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"%PDF-1.7\n%adapter-treatment-review\n"
            repository = LocalDocumentAiArtifactRepository(
                manifest_path=root / "artifacts.json",
                storage=LocalDocumentStorage(root / "bodies"),
            )
            result = run_gemini_invoice_pipeline_v2(
                GeminiInvoicePipelineRequest(
                    tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-review",
                    source_file_id="source-review", source_file_sha256=hashlib.sha256(source).hexdigest(),
                    source_bytes=source, workspace=_workspace(), chart_revision="chart-r1",
                ),
                extraction_provider=_ExtractionProvider(_canonical_payload("purchase")),
                accounting_provider=_AccountingProvider([incomplete, incomplete]),
                artifact_repository=repository,
            )

            payload = to_document_processing_payload(result)

        review_line = next(
            line
            for line in payload["draft_lines"]
            if line["fact_ref"].startswith("tax:")
        )
        self.assertEqual(review_line["resolution"], "review_required")
        self.assertEqual(review_line["selected_candidate_id"], "360.01")
        self.assertEqual(review_line["account_code"], "360.01")
        self.assertEqual(review_line["debit"], "0.00")
        self.assertEqual(review_line["credit"], "0.00")

    def test_adapter_preserves_current_active_ui_shape_and_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"%PDF-1.7\n%adapter-v2\n"
            pdf = root / "invoice.pdf"
            pdf.write_bytes(source)
            repository = LocalDocumentAiArtifactRepository(
                manifest_path=root / "artifacts.json",
                storage=LocalDocumentStorage(root / "bodies"),
            )
            request = GeminiInvoicePipelineRequest(
                tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
                source_file_id="source-1", source_file_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
                source_bytes=pdf.read_bytes(), workspace=_workspace(), chart_revision="chart-r1",
            )
            result = run_gemini_invoice_pipeline_v2(
                request,
                extraction_provider=_ExtractionProvider(_canonical_payload("purchase", warning="adapter_warning")),
                accounting_provider=_AccountingProvider([_complete_proposal]),
                artifact_repository=repository,
            )

            payload = to_document_processing_payload(result)

        self.assertEqual(payload["issue_date"], "2026-08-11")
        self.assertEqual(payload["payable_total"], "110.00")
        self.assertIsInstance(payload["vat_rates"], list)
        self.assertIsInstance(payload["canonical_line_count"], int)
        self.assertIsInstance(payload["canonical_validation_reasons"], list)
        self.assertIsInstance(payload["decision_narrative"], dict)
        self.assertIsInstance(payload["decision_narrative"]["read_facts"], dict)
        self.assertEqual(payload["selected_expense_account"], "770.01")
        self.assertEqual(payload["selected_purchase_vat_account"], "191.20")
        self.assertEqual(payload["selected_supplier_account"], "320.01")
        self.assertEqual(payload["decision_narrative"]["account_name"], "Expense")
        self.assertIsNone(payload["counterparty_creation_suggestion"])
        self.assertIsInstance(payload["draft_lines"], list)
        self.assertTrue(all(isinstance(line["debit"], str) and isinstance(line["credit"], str) for line in payload["draft_lines"]))
        self.assertEqual(payload["total_debit"], "120.00")
        self.assertEqual(payload["total_credit"], "120.00")
        self.assertTrue(payload["is_balanced"])
        self.assertIn(payload["status"], {"complete", "partial"})
        self.assertEqual(payload["processing_status"], "complete")
        self.assertEqual(payload["extraction_validation_status"], "invalid")
        self.assertEqual(payload["reconciliation_status"], "exact")
        self.assertEqual(payload["accounting_decision_status"], "complete")
        self.assertEqual(payload["draft_balance_status"], "balanced")
        self.assertEqual(payload["review_status"], "review_required")
        self.assertEqual(payload["export_status"], "review_required")
        self.assertIn("canonical_evidence_categories", payload)
        self.assertIn("derived_line_to_vat_linkage", payload)
        self.assertIn("adapter_warning", payload["pipeline_warnings"])
        self.assertIn("adapter_warning", payload["review_reason_codes"])
        self.assertIn("adapter_warning", payload["risk_flags"])

    def test_adapter_preserves_new_counterparty_suggestion_without_creation(self) -> None:
        def propose_new(request):
            payload = _complete_proposal(request)
            payload["counterparty"] = {
                "action": "propose_new", "selected_candidate_id": "", "reason": "new",
                "proposal": {
                    "party_title": "Suggested Supplier", "tax_id": "9999999999",
                    "direction": "supplier", "suggested_parent_family": "320",
                },
            }
            return payload

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"%PDF-1.7\n%adapter-proposal\n"
            repository = LocalDocumentAiArtifactRepository(
                manifest_path=root / "artifacts.json", storage=LocalDocumentStorage(root / "bodies")
            )
            result = run_gemini_invoice_pipeline_v2(
                GeminiInvoicePipelineRequest(
                    tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-2",
                    source_file_id="source-2", source_file_sha256=hashlib.sha256(source).hexdigest(),
                    source_bytes=source, workspace=_workspace(), chart_revision="chart-r1",
                ),
                extraction_provider=_ExtractionProvider(_canonical_payload("purchase")),
                accounting_provider=_AccountingProvider([propose_new]),
                artifact_repository=repository,
            )
            payload = to_document_processing_payload(result)

        self.assertEqual(payload["counterparty_creation_suggestion"]["party_title"], "Suggested Supplier")
        self.assertEqual(payload["selected_supplier_account"], "")
        self.assertTrue(any(line["resolution"] == "propose_new" for line in payload["draft_lines"]))


if __name__ == "__main__":
    unittest.main()
