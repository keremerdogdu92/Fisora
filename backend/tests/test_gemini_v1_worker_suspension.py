from __future__ import annotations

import inspect
from pathlib import Path
import sys
import tempfile
import unittest

import fitz


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.workflows.document_processing import process_next_job_once
from app.domain.ai_classification import StaticFirstClassifier
from app.domain.research_harness import ResearchPolicy


class _PoisonProvider:
    def __init__(self) -> None:
        self.calls = 0

    def extract_invoice_canonical(self, request):
        self.calls += 1
        raise AssertionError("standalone V1 extraction must not be called by worker")

    def classify_product(self, request):
        self.calls += 1
        raise AssertionError("standalone V1 accounting must not be called by worker")


class _WorkerStore:
    def __init__(self, pdf: Path) -> None:
        self.job = {
            "id": "job-1", "client_id": "client-1", "document_ref": "document-1",
            "document_type": "invoice", "intake_category": "purchase_invoice", "attempt_count": 1,
        }
        self.workspace = {
            "client": {"profile": {}},
            "uploaded_documents": [{
                "document_ref": "document-1", "document_id": "document-1",
                "document_type": "invoice", "storage_path": str(pdf),
            }],
        }
        self.updated = None
        self.saved = None
        self.events = []

    def claim_next_processing_job(self):
        job, self.job = self.job, None
        return job

    def get_workspace(self, client_id):
        return self.workspace

    def update_processing_job(self, **payload):
        self.updated = payload
        return payload

    def save_simulation_result(self, *, client_id, document_ref, result, **kwargs):
        self.saved = result
        return result

    def record_document_pipeline_event(self, **payload):
        self.events.append(payload)


class GeminiV1WorkerSuspensionTests(unittest.TestCase):
    def test_legacy_worker_result_with_truthy_research_runtime_is_v1_v2_independent(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
 <cbc:ID>INV-LEGACY-1</cbc:ID><cbc:IssueDate>2026-08-11</cbc:IssueDate>
 <cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Supplier</cbc:Name></cac:PartyName><cac:PartyTaxScheme><cbc:CompanyID>1234567890</cbc:CompanyID><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme></cac:Party></cac:AccountingSupplierParty>
 <cac:AccountingCustomerParty><cac:Party><cac:PartyName><cbc:Name>Customer</cbc:Name></cac:PartyName><cac:PartyTaxScheme><cbc:CompanyID>1111111111</cbc:CompanyID><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme></cac:Party></cac:AccountingCustomerParty>
 <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="NIU">1</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Office service</cbc:Name></cac:Item></cac:InvoiceLine>
 <cac:LegalMonetaryTotal><cbc:TaxInclusiveAmount currencyID="TRY">100.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="TRY">100.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invoice.xml"
            path.write_text(xml, encoding="utf-8")
            store = _WorkerStore(path)
            store.workspace["client"] = {
                "client_id": "client-1",
                "profile": {"tax_id": "1111111111", "title": "Customer"},
            }

            summary = process_next_job_once(
                store,
                product_classifier=StaticFirstClassifier(),
                research_runtime={
                    "provider": None,
                    "policy": ResearchPolicy(enabled=False),
                },
            )

        self.assertEqual(
            summary,
            {"processed_count": 1, "completed_count": 1, "failed_count": 0},
            store.updated,
        )
        self.assertIsNotNone(store.saved)
        self.assertEqual(store.updated["status"], "completed")

    def test_pdf_worker_ignores_old_v1_dependencies_and_never_invokes_standalone_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "invoice.pdf"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "Invoice INV-1 2026-08-11 Total 110.00")
            document.save(pdf)
            document.close()
            store = _WorkerStore(pdf)
            extraction = _PoisonProvider()
            accounting = _PoisonProvider()

            summary = process_next_job_once(
                store,
                product_classifier=object(),
                extraction_provider=extraction,
                accounting_provider=accounting,
                artifact_repository=object(),
                tenant_id="tenant-1",
                research_runtime={},
            )

        self.assertEqual(extraction.calls, 0)
        self.assertEqual(accounting.calls, 0)
        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertIsNotNone(store.saved)
        self.assertEqual(store.updated["status"], "completed")
        self.assertNotIn("gemini_direct_pdf_dependencies_missing", repr(store.updated))
        self.assertNotIn(
            "run_gemini_two_stage_invoice_workflow",
            inspect.getsource(process_next_job_once),
        )


if __name__ == "__main__":
    unittest.main()
