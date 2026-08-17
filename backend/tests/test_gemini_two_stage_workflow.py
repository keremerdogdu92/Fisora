from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_ai_artifacts import ArtifactKind, ArtifactWrite
from app.domain.openai_provider import (
    GeminiAttemptEnvelope,
    GeminiProviderAttemptError,
    GeminiStructuredResult,
)
from app.domain.storage_adapters import LocalDocumentStorage
from app.domain.research_harness import ResearchPolicy
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository
from app.persistence.document_ai_artifact_repository import PostgresDocumentAiArtifactRepository
from app.persistence.workflow_store import JsonWorkflowStore
from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.workflows.document_processing import (
    DocumentParseError,
    process_next_job_once,
    run_gemini_two_stage_invoice_workflow,
)
from backend.tests.test_gemini_invoice_pipeline_v2 import (
    _AccountingProvider as V2AccountingProvider,
    _ExtractionProvider as V2ExtractionProvider,
    _canonical_payload as v2_canonical_payload,
    _complete_proposal as v2_complete_proposal,
    _workspace as v2_workspace,
)


def _attempt(
    *,
    request: bytes,
    response: bytes,
    status: str = "successful",
    http_status: int | None = 200,
) -> GeminiAttemptEnvelope:
    started = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    return GeminiAttemptEnvelope(
        request_body=request,
        response_body=response,
        provider="gemini",
        model_alias="gemini-3.5-flash-lite",
        resolved_model="gemini-3.5-flash-lite-2026-08",
        http_status=http_status,
        started_at=started,
        finished_at=started + timedelta(milliseconds=25),
        elapsed_ms=25,
        token_usage={"prompt_tokens": 10, "candidate_tokens": 5, "total_tokens": 15},
        status=status,
        error_metadata={} if status == "successful" else {"phase": "transport"},
    )


def _canonical_payload(*, warning: str = "") -> dict[str, object]:
    notes = [warning] if warning else []
    return {
        "header": {
            "invoice_no": "GIB2026000000042",
            "ettn": "17f56e87-f50c-4c7d-89e5-883e592c36f1",
            "issue_date": "2026-08-10",
            "invoice_type": "SATIS",
            "scenario": "TICARIFATURA",
            "currency_code": "TRY",
            "document_direction": "purchase",
            "original_invoice_no": "",
            "original_invoice_date": "",
            "evidence": ["$.header"],
        },
        "supplier_party": {
            "title": "Ornek Telekom A.S.",
            "tax_id": "1234567890",
            "tax_id_type": "VKN",
            "tax_office": "Maslak",
            "address": "Istanbul",
            "evidence": ["$.supplier_party"],
        },
        "customer_party": {
            "title": "Fisero Pilot Ltd.",
            "tax_id": "1111111111",
            "tax_id_type": "VKN",
            "tax_office": "Kadikoy",
            "address": "Istanbul",
            "evidence": ["$.customer_party"],
        },
        "line_items": [
            {
                "canonical_line_id": "line-1",
                "source_position": "page:1#line:1",
                "external_line_id": "1",
                "description": "Sabit internet hizmeti",
                "observed_quantity": "1",
                "observed_unit_code": "C62",
                "observed_unit_price": "100.00",
                "observed_unit_price_basis": "net",
                "observed_taxable_amount": "100.00",
                "observed_vat_rate": "20",
                "observed_tax_amount": "20.00",
                "observed_gross_amount": "120.00",
                "tax_scheme_code": "VAT",
                "tax_category_code": "S",
                "exemption_reason_code": "",
                "evidence": ["$.line_items[0]"],
            }
        ],
        "observed_vat_summary": [
            {
                "observed_rate": "20",
                "observed_taxable_amount": "100.00",
                "observed_tax_amount": "20.00",
                "tax_scheme_code": "VAT",
                "tax_category_code": "S",
                "exemption_reason_code": "",
                "evidence": ["$.observed_vat_summary[0]"],
            }
        ],
        "observed_tax_components": [
            {
                "component_type": "special_tax",
                "source_label": "Ozel Iletisim Vergisi",
                "source_code": "4080",
                "rate": "10",
                "taxable_amount": "100.00",
                "tax_amount": "10.00",
                "source_position": "page:1#tax:oiv",
                "evidence": ["$.observed_tax_components[0]"],
            }
        ],
        "observed_monetary_components": [],
        "observed_totals": {
            "observed_goods_services_total": "100.00",
            "observed_allowance_total": "0.00",
            "observed_vat_total": "20.00",
            "observed_special_tax_total": "10.00",
            "observed_tax_inclusive_total": "130.00",
            "observed_payable_total": "130.00",
            "evidence": ["$.observed_totals"],
        },
        "extraction_notes": notes,
    }


def _full_proposal(
    *,
    direction: str = "purchase",
    action: str = "finalize",
    include_counterparty: bool = True,
    new_counterparty: dict[str, str] | None = None,
) -> dict[str, object]:
    purchase = direction != "sales"
    return {
        "action": action,
        "candidate_set_sufficient": action != "request_more_candidates",
        "proposal": {
            "counterparty_account": (
                {
                    "selected_candidate_id": "320.01" if purchase else "120.01",
                    "reason": "Vergi kimligi ve unvan eslesmesi",
                }
                if include_counterparty
                else None
            ),
            "line_accounts": [
                {
                    "line_ref": "line-1",
                    "selected_candidate_id": "770.01" if purchase else "600.01",
                    "reason": "Belge satiri icin tenant hesabi",
                }
            ],
            "vat_accounts": [
                {
                    "vat_ref": "vat-20",
                    "rate": "20",
                    "selected_candidate_id": "191.20" if purchase else "391.20",
                    "reason": "Yuzde 20 KDV",
                }
            ],
            "special_tax_accounts": [
                {
                    "tax_ref": "tax-1",
                    "component_type": "special_tax",
                    "selected_candidate_id": "360.08",
                    "reason": "Ozel iletisim vergisi",
                }
            ],
            "new_counterparty_proposal": new_counterparty,
        },
        "reason": "Tam muhasebe taslagi",
    }


def _full_proposal_for_request(request, *, direction: str = "purchase", action: str = "finalize"):
    projection = request.accounting_projection
    payload = _full_proposal(direction=direction, action=action)
    payload["proposal"]["line_accounts"][0]["line_ref"] = projection["line_items"][0]["canonical_line_id"]
    payload["proposal"]["vat_accounts"][0]["vat_ref"] = projection["vat_summary"][0]["vat_ref"]
    payload["proposal"]["special_tax_accounts"][0]["tax_ref"] = projection["tax_components"][0]["tax_ref"]
    return payload


class FakeExtractionProvider:
    provider_name = "gemini"

    def __init__(self, payload: dict[str, object], *, fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.requests = []

    def extract_invoice_canonical(self, request):
        self.requests.append(request)
        outbound = b'{"exact":"native-pdf-request"}'
        inbound = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")).encode()
        attempt = _attempt(
            request=outbound,
            response=b'{"error":"temporary"}' if self.fail else inbound,
            status="failed" if self.fail else "successful",
            http_status=503 if self.fail else 200,
        )
        if self.fail:
            raise GeminiProviderAttemptError("temporary", attempt=attempt)
        return GeminiStructuredResult(self.payload, attempt=attempt)


class FakeAccountingProvider:
    provider_name = "gemini"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests = []

    def classify_product(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = response(request)
        index = len(self.requests)
        return GeminiStructuredResult(
            response,
            attempt=_attempt(
                request=f'{{"accounting_request":{index}}}'.encode(),
                response=json.dumps(response, separators=(",", ":")).encode(),
            ),
        )


class WorkerStore:
    def __init__(self, document, workspace):
        self.job = {
            "id": "job-1",
            "client_id": "client-1",
            "document_ref": "document-1",
            "document_type": "invoice",
            "intake_category": "purchase_invoice",
            "attempt_count": 1,
        }
        self.workspace = {**workspace, "uploaded_documents": [document]}
        self.saved = None
        self.updated = None
        self.events = []

    def claim_next_processing_job(self):
        job, self.job = self.job, None
        return job

    def get_workspace(self, client_id):
        return self.workspace

    def save_simulation_result(self, *, client_id, document_ref, result, **kwargs):
        self.saved = result
        return result

    def update_processing_job(self, **payload):
        self.updated = payload
        return payload

    def record_document_pipeline_event(self, **payload):
        self.events.append(payload)


def _workspace(*, direction: str = "purchase") -> dict[str, object]:
    return {
        "client": {
            "client_id": "client-1",
            "profile": {
                "client_id": "client-1",
                "title": "Fisero Pilot Ltd.",
                "tax_id": "1111111111",
                "tax_identifier": "1111111111",
                "activity_description": "Yazilim hizmetleri",
                "has_chart_accounts": True,
            },
        },
        "chart_accounts": {
            "account_count": 10,
            "accounts": [
                {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Haberlesme Giderleri", "is_detail_account": True},
                {"raw_account_code": "191.20", "normalized_account_code": "191.20", "account_name": "Indirilecek KDV %20", "is_detail_account": True},
                {"raw_account_code": "320.01", "normalized_account_code": "320.01", "account_name": "Ornek Telekom", "is_detail_account": True, "tax_id": "1234567890"},
                {"raw_account_code": "360.08", "normalized_account_code": "360.08", "account_name": "Ozel Iletisim Vergisi", "is_detail_account": True},
                {"raw_account_code": "689.01", "normalized_account_code": "689.01", "account_name": "Diger Olagn Disi Gider", "is_detail_account": True},
                {"raw_account_code": "600.01", "normalized_account_code": "600.01", "account_name": "Yurtici Satislar", "is_detail_account": True},
                {"raw_account_code": "391.20", "normalized_account_code": "391.20", "account_name": "Hesaplanan KDV %20", "is_detail_account": True},
                {"raw_account_code": "120.01", "normalized_account_code": "120.01", "account_name": "Fisero Pilot", "is_detail_account": True, "tax_id": "1111111111"},
                {"raw_account_code": "360.09", "normalized_account_code": "360.09", "account_name": "Diger Ozel Vergiler", "is_detail_account": True},
            ],
        },
        "learning_events": [],
        "learning_rules": [],
    }


class GeminiTwoStageWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.pdf = self.root / "source.pdf"
        # Deliberately not a parser-usable PDF. The direct native provider is the authority.
        self.pdf.write_bytes(b"%PDF-1.7\n%native-provider-only\n")
        self.repository = LocalDocumentAiArtifactRepository(
            manifest_path=self.root / "artifacts.json",
            storage=LocalDocumentStorage(self.root / "storage"),
        )
        self.document = {
            "document_ref": "document-1",
            "document_id": "document-1",
            "source_file_id": "source-1",
            "storage_path": str(self.pdf),
            "original_file_name": "source.pdf",
            "document_type": "invoice",
            "intake_category": "purchase_invoice",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, *, extraction, accounting, initial_candidate_limit: int = 3):
        return run_gemini_two_stage_invoice_workflow(
            document=self.document,
            job={"document_ref": "document-1", "document_type": "invoice"},
            workspace=_workspace(),
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            extraction_provider=extraction,
            accounting_provider=accounting,
            artifact_repository=self.repository,
            initial_candidate_limit=initial_candidate_limit,
        )

    def test_full_purchase_proposal_builds_one_entry_for_every_fact_role(self) -> None:
        result = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([_full_proposal_for_request]),
            initial_candidate_limit=8,
        )

        by_role = {line["proposal_role"]: line for line in result["draft_lines"]}
        self.assertEqual(by_role["canonical_line"]["account_code"], "770.01")
        self.assertEqual(by_role["vat_group"]["account_code"], "191.20")
        self.assertEqual(by_role["special_tax"]["account_code"], "360.08")
        self.assertEqual(by_role["counterparty"]["account_code"], "320.01")
        self.assertEqual(result["selected_expense_account"], "770.01")
        self.assertEqual(result["selected_purchase_vat_account"], "191.20")
        self.assertEqual(result["selected_supplier_account"], "320.01")
        self.assertEqual(result["issue_date"], "2026-08-10")
        narrative = result["decision_narrative"]
        self.assertEqual(
            set(narrative),
            {
                "read_facts",
                "invoice_product_line",
                "fisora_interpretation",
                "business_relation",
                "account_code",
                "account_name",
                "counterparty_match",
                "confidence_label",
                "unresolved_info",
            },
        )
        self.assertEqual(narrative["read_facts"]["invoice_no"], "GIB2026000000042")
        self.assertEqual(narrative["account_code"], "770.01")
        self.assertEqual(narrative["account_name"], "Haberlesme Giderleri")
        self.assertEqual(narrative["counterparty_match"], "320.01")
        self.assertIn("770.01", narrative["fisora_interpretation"])

    def test_full_sales_proposal_builds_sales_line_vat_special_tax_and_customer(self) -> None:
        canonical = _canonical_payload()
        canonical["header"]["document_direction"] = "sales"
        result = run_gemini_two_stage_invoice_workflow(
            document=self.document,
            job={"document_ref": "document-1", "document_type": "invoice", "intake_category": "sales_invoice"},
            workspace=_workspace(direction="sales"),
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            extraction_provider=FakeExtractionProvider(canonical),
            accounting_provider=FakeAccountingProvider([
                lambda request: _full_proposal_for_request(request, direction="sales")
            ]),
            artifact_repository=self.repository,
            initial_candidate_limit=8,
        )

        by_role = {line["proposal_role"]: line for line in result["draft_lines"]}
        self.assertEqual(by_role["canonical_line"]["account_code"], "600.01")
        self.assertEqual(by_role["vat_group"]["account_code"], "391.20")
        self.assertEqual(by_role["special_tax"]["account_code"], "360.08")
        self.assertEqual(by_role["counterparty"]["account_code"], "120.01")
        self.assertEqual(result["selected_revenue_account"], "600.01")
        self.assertEqual(result["selected_sales_vat_account"], "391.20")
        self.assertEqual(result["selected_customer_account"], "120.01")

    def test_initial_candidates_are_fact_role_based_and_preserve_metadata_not_chart_first_n(self) -> None:
        accounting = FakeAccountingProvider([_full_proposal_for_request])

        self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=accounting,
            initial_candidate_limit=4,
        )

        candidates = accounting.requests[0].to_schema_payload()["account_candidates"]
        codes = {item["candidate_id"] for item in candidates}
        self.assertNotIn("102.01", codes)
        self.assertIn("320.01", codes)
        self.assertIn("770.01", codes)
        self.assertIn("191.20", codes)
        self.assertIn("360.08", codes)
        counterparty = next(item for item in candidates if item["candidate_id"] == "320.01")
        self.assertEqual(counterparty["tax_id"], "1234567890")
        self.assertIn("counterparty", counterparty["roles"])

    def test_failed_expansion_applies_full_provisional_and_marks_proposal_partial(self) -> None:
        def provisional(request):
            payload = _full_proposal_for_request(request, action="request_more_candidates")
            payload["request_more_candidates"] = {
                "search_terms": ["diger ozel vergi"],
                "requested_scope": "special_tax",
                "reason": "OIV alternatifleri",
            }
            return payload
        failure = GeminiProviderAttemptError(
            "temporary",
            attempt=_attempt(
                request=b'{"accounting_request":2}',
                response=b'{"error":"temporary"}',
                status="failed",
                http_status=503,
            ),
        )
        result = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([provisional, failure]),
            initial_candidate_limit=4,
        )

        self.assertEqual(result["selected_expense_account"], "770.01")
        self.assertIn("accounting_provider_failed", result["pipeline_warnings"])
        proposal_artifacts = self.repository.list_for_document(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            document_id="document-1",
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
        )
        self.assertEqual(proposal_artifacts[-1].status, "partial")
        failed_receipts = [item for item in self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="client-1", document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        ) if item.status == "failed"]
        self.assertEqual(len(failed_receipts), 1)
        successful_accounting_receipts = [item for item in self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="client-1", document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        ) if item.stage == "accounting_selection" and item.status == "successful"]
        self.assertEqual(
            proposal_artifacts[-1].provider_receipt_artifact_id,
            successful_accounting_receipts[-1].artifact_id,
        )
        self.assertEqual(
            failed_receipts[-1].expanded_from_receipt_id,
            successful_accounting_receipts[-1].artifact_id,
        )

    def test_first_accounting_failure_keeps_failed_receipt_without_fabricated_proposal(self) -> None:
        failure = GeminiProviderAttemptError(
            "temporary",
            attempt=_attempt(
                request=b'{"accounting_request":1}', response=b'{"error":"temporary"}',
                status="failed", http_status=503,
            ),
        )

        result = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([failure]),
            initial_candidate_limit=4,
        )

        self.assertTrue(result["draft_lines"])
        self.assertIn("accounting_provider_failed", result["pipeline_warnings"])
        self.assertNotIn("document_ai_artifacts", result)
        artifacts = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="client-1", document_id="document-1"
        )
        failed_accounting = [
            item for item in artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT
            and item.stage == "accounting_selection"
            and item.status == "failed"
        ]
        self.assertEqual(len(failed_accounting), 1)
        self.assertFalse(any(item.kind is ArtifactKind.ACCOUNTING_PROPOSAL for item in artifacts))

    def test_failed_extraction_retry_preserves_prior_partial_provisional_draft(self) -> None:
        def provisional(request):
            payload = _full_proposal_for_request(request, action="request_more_candidates")
            payload["request_more_candidates"] = {
                "search_terms": ["diger ozel"],
                "requested_scope": "special_tax",
                "reason": "alternatif",
            }
            return payload

        accounting_failure = GeminiProviderAttemptError(
            "temporary",
            attempt=_attempt(
                request=b'{"accounting_request":2}', response=b'{"error":"temporary"}',
                status="failed", http_status=503,
            ),
        )
        partial = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([provisional, accounting_failure]),
            initial_candidate_limit=4,
        )

        retried = self._run(
            extraction=FakeExtractionProvider(_canonical_payload(), fail=True),
            accounting=FakeAccountingProvider([]),
            initial_candidate_limit=4,
        )

        self.assertEqual(retried["draft_lines"], partial["draft_lines"])
        self.assertIn("document_extraction_retry_failed", retried["pipeline_warnings"])

    def test_pdf_worker_does_not_require_suspended_direct_dependencies(self) -> None:
        import fitz

        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "Invoice INV-1 2026-08-11 Total 130.00")
        pdf.save(self.pdf)
        pdf.close()
        store = WorkerStore(self.document, _workspace())

        summary = process_next_job_once(store, product_classifier=object(), research_runtime={})

        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertIsNotNone(store.saved)
        self.assertEqual(store.updated["status"], "completed")
        self.assertNotIn("gemini_direct_pdf_dependencies_missing", repr(store.updated))

    def test_pdf_worker_ignores_suspended_v1_provider_injection(self) -> None:
        import fitz

        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "Invoice INV-1 2026-08-11 Total 130.00")
        pdf.save(self.pdf)
        pdf.close()
        store = WorkerStore(self.document, _workspace())
        extraction = FakeExtractionProvider(_canonical_payload())
        accounting = FakeAccountingProvider([_full_proposal_for_request])

        summary = process_next_job_once(
            store,
            product_classifier=object(),
            extraction_provider=extraction,
            accounting_provider=accounting,
            artifact_repository=self.repository,
            tenant_id="tenant-1",
            research_runtime={},
        )

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(extraction.requests, [])
        self.assertEqual(accounting.requests, [])
        self.assertFalse(any(event["debug_code"] == "research_started" for event in store.events))

    def test_changed_source_retry_does_not_link_or_reuse_old_snapshot(self) -> None:
        self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([_full_proposal_for_request]),
            initial_candidate_limit=8,
        )
        self.pdf.write_bytes(b"%PDF-1.7\n%changed-source\n")

        with self.assertRaises(DocumentParseError):
            self._run(
                extraction=FakeExtractionProvider(_canonical_payload(), fail=True),
                accounting=FakeAccountingProvider([]),
                initial_candidate_limit=8,
            )

        receipts = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="client-1", document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        )
        self.assertEqual(receipts[-1].status, "failed")
        self.assertIsNone(receipts[-1].retry_of_artifact_id)
        self.assertNotEqual(receipts[-1].source_file_sha256, receipts[0].source_file_sha256)

    def test_changed_chart_revision_does_not_reuse_old_proposal_snapshot(self) -> None:
        self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([_full_proposal_for_request]),
            initial_candidate_limit=8,
        )
        changed_workspace = _workspace()
        changed_workspace["chart_accounts"]["accounts"].append({
            "raw_account_code": "770.99",
            "normalized_account_code": "770.99",
            "account_name": "Yeni tenant hesabi",
            "is_detail_account": True,
        })

        with self.assertRaises(DocumentParseError):
            run_gemini_two_stage_invoice_workflow(
                document=self.document,
                job={"document_ref": "document-1", "document_type": "invoice"},
                workspace=changed_workspace,
                tenant_id="tenant-1",
                taxpayer_id="client-1",
                extraction_provider=FakeExtractionProvider(_canonical_payload(), fail=True),
                accounting_provider=FakeAccountingProvider([]),
                artifact_repository=self.repository,
                initial_candidate_limit=8,
            )

    def test_same_input_forced_repeat_appends_new_revisions_without_overwrite(self) -> None:
        first = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([_full_proposal_for_request]),
            initial_candidate_limit=8,
        )
        second = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider([_full_proposal_for_request]),
            initial_candidate_limit=8,
        )

        proposals = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="client-1", document_id="document-1",
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
        )
        self.assertEqual([item.revision_no for item in proposals], [1, 2])
        self.assertNotEqual(
            first["document_ai_artifacts"]["accounting_proposal_id"],
            second["document_ai_artifacts"]["accounting_proposal_id"],
        )
        first_payload = json.loads(self.repository.read_content(
            tenant_id="tenant-1", taxpayer_id="client-1", artifact_id=proposals[0].artifact_id,
        ))
        self.assertEqual(
            first_payload["result_snapshot"]["document_ai_artifacts"],
            first["document_ai_artifacts"],
        )

    def test_full_proposal_with_new_counterparty_updates_active_ui_narrative_without_creation(self) -> None:
        workspace = _workspace()
        before = list(workspace["chart_accounts"]["accounts"])

        def response(request):
            payload = _full_proposal_for_request(request)
            payload["proposal"]["counterparty_account"] = None
            payload["proposal"]["new_counterparty_proposal"] = {
                "party_title": "Yeni Tedarikci A.S.",
                "tax_id": "9999999999",
                "direction": "supplier",
                "suggested_parent_family": "320",
            }
            return payload

        result = run_gemini_two_stage_invoice_workflow(
            document=self.document,
            job={"document_ref": "document-1", "document_type": "invoice"},
            workspace=workspace,
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            extraction_provider=FakeExtractionProvider(_canonical_payload()),
            accounting_provider=FakeAccountingProvider([response]),
            artifact_repository=self.repository,
            initial_candidate_limit=8,
        )

        self.assertEqual(result["counterparty_creation_suggestion"]["tax_id"], "9999999999")
        self.assertEqual(result["suggested_counterparty_creation"], result["counterparty_creation_suggestion"])
        self.assertEqual(result["primary_suggestion"]["account"], "770.01")
        self.assertIn("770.01", result["decision_narrative"]["fisora_interpretation"])
        self.assertIn("UNRESOLVED:counterparty", {line["account_code"] for line in result["draft_lines"]})
        self.assertEqual(workspace["chart_accounts"]["accounts"], before)

    def test_postgres_compatibility_scope_provisions_normalized_document_and_source_ids(self) -> None:
        normalized_document_id = "a2f46d19-1127-4f95-9f0a-d24dd3460e58"
        normalized_source_id = "571f81ea-6cc4-4b8b-b12f-0240fe4fb80c"

        class ScopeRepository:
            def __init__(self):
                self.calls = []

            def store_source_document(self, *, client_id, document):
                self.calls.append((client_id, dict(document)))
                return {
                    "normalized_document_id": normalized_document_id,
                    "normalized_source_file_id": normalized_source_id,
                    "document_ref": document["document_ref"],
                }

        scope_repository = ScopeRepository()
        store = PostgresWorkflowStore(
            "postgresql://unused",
            tenant_key="scope-test",
            connect=lambda: None,
            accounting_store_target="compatibility",
            normalized_repository=scope_repository,
            document_ai_artifact_repository=self.repository,
            protected_corpus_repository=object(),
        )
        document = {
            **self.document,
            "sha256": hashlib.sha256(self.pdf.read_bytes()).hexdigest(),
        }

        scope = store.document_ai_artifact_scope(client_id="client-1", document=document)

        self.assertEqual(scope["document_id"], normalized_document_id)
        self.assertEqual(scope["source_file_id"], normalized_source_id)
        self.assertEqual(len(scope_repository.calls), 1)
        self.assertEqual(document["normalized_document_id"], normalized_document_id)
        self.assertEqual(document["normalized_source_file_id"], normalized_source_id)

    def test_native_pdf_primary_persists_four_linked_artifacts_and_keeps_ui_shape(self) -> None:
        extraction = FakeExtractionProvider(_canonical_payload())
        accounting = FakeAccountingProvider(
            [{"action": "select_existing", "selected_candidate_id": "770.01", "reason": "Hizmet gideri"}]
        )

        result = self._run(extraction=extraction, accounting=accounting)

        self.assertEqual(extraction.requests[0].document_bytes, self.pdf.read_bytes())
        self.assertEqual(extraction.requests[0].document_mime_type, "application/pdf")
        self.assertEqual(extraction.requests[0].deterministic_payload, {})
        artifacts = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="client-1", document_id="document-1"
        )
        self.assertEqual(
            [item.kind for item in artifacts],
            [
                ArtifactKind.PROVIDER_RECEIPT,
                ArtifactKind.CANONICAL_INVOICE_FORM,
                ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                ArtifactKind.PROVIDER_RECEIPT,
                ArtifactKind.ACCOUNTING_PROPOSAL,
            ],
        )
        self.assertEqual(self.repository.trace_lineage(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            artifact_id=artifacts[-1].artifact_id,
        )[-1].kind, ArtifactKind.ACCOUNTING_PROPOSAL)
        self.assertEqual(result["invoice_no"], "GIB2026000000042")
        self.assertEqual(result["selected_expense_account"], "770.01")
        self.assertTrue(result["draft_lines"])
        self.assertIn("canonical_invoice", result)
        self.assertIn("accounting_proposal", result)
        self.assertNotIn("raw_provider_response", result)
        accounting_payload = accounting.requests[0].to_schema_payload()
        self.assertNotIn("document_bytes", repr(accounting_payload))
        self.assertNotIn("native-pdf-request", repr(accounting_payload))
        self.assertIn("Ozel Iletisim Vergisi", repr(accounting_payload))

    def test_warning_continues_expansion_and_retains_best_available_draft(self) -> None:
        extraction = FakeExtractionProvider(_canonical_payload(warning="tax_component_low_confidence"))
        accounting = FakeAccountingProvider(
            [
                {
                    "action": "request_more_candidates",
                    "selected_candidate_id": "770.01",
                    "candidate_set_sufficient": False,
                    "request_more_candidates": {
                        "search_terms": ["ozel iletisim vergisi", "oiv"],
                        "requested_scope": "broader_chart_slice",
                        "reason": "OIV hesabini da gormek istiyorum",
                    },
                },
                {"action": "select_existing", "selected_candidate_id": "770.01", "reason": "Ilk aday en iyi"},
            ]
        )

        result = self._run(extraction=extraction, accounting=accounting, initial_candidate_limit=3)

        self.assertEqual(len(accounting.requests), 2)
        second_payload = accounting.requests[1].to_schema_payload()
        self.assertIn("360.08", repr(second_payload))
        self.assertEqual(result["accounting_proposal"]["selection_origin_round"], 0)
        self.assertEqual(result["accounting_proposal"]["expansion_count"], 1)
        self.assertIn("tax_component_low_confidence", result["pipeline_warnings"])
        self.assertTrue(result["draft_lines"])
        self.assertEqual(result["selected_expense_account"], "770.01")

    def test_empty_expansion_is_warning_not_failure_and_preserves_provisional_choice(self) -> None:
        extraction = FakeExtractionProvider(_canonical_payload())
        accounting = FakeAccountingProvider(
            [
                {
                    "action": "request_more_candidates",
                    "selected_candidate_id": "770.01",
                    "candidate_set_sufficient": False,
                    "request_more_candidates": {
                        "search_terms": ["there-is-no-such-account"],
                        "requested_scope": "broader_chart_slice",
                        "reason": "Daha fazla hesap",
                    },
                }
            ]
        )

        result = self._run(extraction=extraction, accounting=accounting, initial_candidate_limit=10)

        self.assertEqual(result["accounting_proposal"]["action"], "select_existing")
        self.assertEqual(result["accounting_proposal"]["selected_candidate_id"], "770.01")
        self.assertIn("candidate_expansion_returned_no_new_candidates", result["pipeline_warnings"])
        self.assertTrue(result["draft_lines"])

    def test_accounting_calls_stop_after_two_expansions_and_keep_first_round_choice(self) -> None:
        def request_more(terms):
            def response(request):
                payload = _full_proposal_for_request(request, action="request_more_candidates")
                payload["request_more_candidates"] = {
                    "search_terms": terms,
                    "requested_scope": "broader_chart_slice",
                    "reason": "Daha fazla gercek hesap",
                }
                return payload
            return response
        accounting = FakeAccountingProvider(
            [request_more(["diger ozel"]), request_more(["banka"]), request_more(["diger gider"])]
        )

        result = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=accounting,
            initial_candidate_limit=4,
        )

        self.assertEqual(len(accounting.requests), 3)
        self.assertEqual(result["accounting_proposal"]["expansion_count"], 2)
        self.assertEqual(result["accounting_proposal"]["selection_origin_round"], 0)
        self.assertEqual(result["selected_expense_account"], "770.01")
        self.assertIn("candidate_expansion_limit_reached", result["pipeline_warnings"])
        self.assertTrue(result["draft_lines"])

    def test_propose_new_counterparty_is_preserved_without_creating_chart_account(self) -> None:
        workspace = _workspace()
        before_codes = [item["normalized_account_code"] for item in workspace["chart_accounts"]["accounts"]]
        result = run_gemini_two_stage_invoice_workflow(
            document=self.document,
            job={"document_ref": "document-1", "document_type": "invoice"},
            workspace=workspace,
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            extraction_provider=FakeExtractionProvider(_canonical_payload()),
            accounting_provider=FakeAccountingProvider(
                [
                    {
                        "action": "propose_new",
                        "selected_candidate_id": "",
                        "reason": "Mevcut cari yok",
                        "new_counterparty_proposal": {
                            "party_title": "Yeni Tedarikci A.S.",
                            "tax_id": "9999999999",
                            "direction": "supplier",
                            "suggested_parent_family": "320",
                        },
                    }
                ]
            ),
            artifact_repository=self.repository,
        )

        self.assertEqual(result["accounting_proposal"]["action"], "propose_new")
        self.assertEqual(
            result["accounting_proposal"]["new_counterparty_proposal"]["tax_id"],
            "9999999999",
        )
        after_codes = [item["normalized_account_code"] for item in workspace["chart_accounts"]["accounts"]]
        self.assertEqual(after_codes, before_codes)
        self.assertTrue(result["draft_lines"])

    def test_failed_retry_appends_receipt_and_preserves_previous_valid_result(self) -> None:
        successful = self._run(
            extraction=FakeExtractionProvider(_canonical_payload()),
            accounting=FakeAccountingProvider(
                [{"action": "select_existing", "selected_candidate_id": "770.01", "reason": "ok"}]
            ),
        )

        retried = self._run(
            extraction=FakeExtractionProvider(_canonical_payload(), fail=True),
            accounting=FakeAccountingProvider([]),
        )

        receipts = self.repository.list_for_document(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        )
        self.assertEqual(receipts[-1].status, "failed")
        self.assertIsNone(receipts[-1].retry_of_artifact_id)
        self.assertEqual(retried["invoice_no"], successful["invoice_no"])
        self.assertEqual(retried["draft_lines"], successful["draft_lines"])
        self.assertEqual(retried["document_ai_artifacts"], successful["document_ai_artifacts"])
        self.assertIn("document_extraction_retry_failed", retried["pipeline_warnings"])

        self._run(
            extraction=FakeExtractionProvider(_canonical_payload(), fail=True),
            accounting=FakeAccountingProvider([]),
        )
        receipts = self.repository.list_for_document(
            tenant_id="tenant-1",
            taxpayer_id="client-1",
            document_id="document-1",
            kind=ArtifactKind.PROVIDER_RECEIPT,
        )
        self.assertEqual(receipts[-2].status, "failed")
        self.assertEqual(receipts[-1].status, "failed")
        self.assertEqual(
            receipts[-1].retry_of_artifact_id,
            receipts[-2].artifact_id,
        )

    def test_worker_keeps_standalone_two_stage_path_suspended(self) -> None:
        import fitz

        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "Invoice INV-1 2026-08-11 Total 130.00")
        pdf.save(self.pdf)
        pdf.close()

        class WorkerStore:
            def __init__(self, document, workspace):
                self.job = {
                    "id": "job-1",
                    "client_id": "client-1",
                    "document_ref": "document-1",
                    "document_type": "invoice",
                    "intake_category": "purchase_invoice",
                    "attempt_count": 1,
                }
                self.workspace = {**workspace, "uploaded_documents": [document]}
                self.saved = None
                self.updated = None
                self.events = []

            def claim_next_processing_job(self):
                job, self.job = self.job, None
                return job

            def get_workspace(self, client_id):
                return self.workspace

            def save_simulation_result(self, *, client_id, document_ref, result, **kwargs):
                self.saved = result
                return result

            def update_processing_job(self, **payload):
                self.updated = payload
                return payload

            def record_document_pipeline_event(self, **payload):
                self.events.append(payload)

        store = WorkerStore(self.document, _workspace())
        extraction = FakeExtractionProvider(
            _canonical_payload(warning="tax_component_low_confidence")
        )
        accounting = FakeAccountingProvider(
            [{"action": "select_existing", "selected_candidate_id": "770.01", "reason": "ok"}]
        )
        summary = process_next_job_once(
            store,
            extraction_provider=extraction,
            accounting_provider=accounting,
            artifact_repository=self.repository,
            tenant_id="tenant-1",
            research_runtime={},
        )

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(extraction.requests, [])
        self.assertEqual(accounting.requests, [])
        self.assertEqual(store.saved["draft_lines"], [])
        self.assertEqual(store.updated["status"], "completed")

    def test_json_source_deletion_removes_pdf_and_raw_receipt_bodies(self) -> None:
        store = JsonWorkflowStore(self.root / "workflow-store.json")
        source_sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        uploaded = store.save_uploaded_document(
            client_id="client-1",
            document={
                **self.document,
                "sha256": source_sha,
                "status": "stored",
                "storage_status": "stored",
            },
        )
        receipt = store.document_ai_artifact_repository.append(
            ArtifactWrite(
                tenant_id=store.tenant_key,
                taxpayer_id="client-1",
                document_id="document-1",
                source_file_id="source-1",
                source_file_sha256=source_sha,
                kind=ArtifactKind.PROVIDER_RECEIPT,
                stage="document_extraction",
                status="successful",
            ),
            request_body=b'{"exact":"request"}',
            response_body=b'{"exact":"response"}',
        )

        summary = store.delete_client_documents(
            client_id="client-1", document_refs=[str(uploaded["document_ref"])]
        )

        self.assertEqual(summary["deleted_count"], 1)
        self.assertFalse(self.pdf.exists())
        self.assertFalse(Path(receipt.request_storage_path).exists())
        self.assertFalse(Path(receipt.response_storage_path).exists())


@unittest.skipUnless(
    os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip(),
    "set FISORA_TEST_POSTGRES_DSN to run direct worker PostgreSQL integration",
)
class GeminiTwoStagePostgresWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scripts = BACKEND / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from apply_migrations import apply_migrations, discover_migrations

        cls.dsn = os.environ["FISORA_TEST_POSTGRES_DSN"].strip()
        apply_migrations(cls.dsn, discover_migrations(BACKEND / "db" / "migrations"))

    def test_compatibility_worker_appends_artifacts_with_real_fk_scope(self) -> None:
        suffix = uuid4().hex
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / f"{suffix}.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%direct-pg-worker\n")
            artifact_repository = PostgresDocumentAiArtifactRepository(
                dsn=self.dsn,
                storage=LocalDocumentStorage(root / "artifact-bodies"),
            )
            store = PostgresWorkflowStore(
                self.dsn,
                tenant_key=f"gemini-worker-{suffix}",
                accounting_store_target="compatibility",
                document_ai_artifact_repository=artifact_repository,
            )
            client_id = f"client-{suffix}"
            store.upsert_client(
                client_id=client_id,
                profile={"title": "PG Worker Client", "tax_id": "1111111111"},
                onboarding={},
            )
            store.replace_chart_accounts(
                client_id=client_id,
                accounts=v2_workspace()["chart_accounts"]["accounts"],
            )
            document = store.save_uploaded_document(
                client_id=client_id,
                document={
                    "document_id": f"document-{suffix}",
                    "source_file_id": f"legacy-source-{suffix}",
                    "original_file_name": pdf.name,
                    "storage_path": str(pdf),
                    "document_type": "invoice",
                    "intake_category": "purchase_invoice",
                    "size_bytes": pdf.stat().st_size,
                    "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    "status": "stored",
                    "storage_status": "stored",
                },
            )
            store.create_processing_job(
                client_id=client_id,
                document_ref=str(document["document_ref"]),
                document_type="invoice",
                parser_kind="gemini_native_pdf",
                intake_category="purchase_invoice",
            )

            with patch.dict(
                os.environ,
                {"FISORA_GEMINI_PDF_V2_ENABLED": "true"},
                clear=False,
            ):
                summary = process_next_job_once(
                    store,
                    extraction_provider=V2ExtractionProvider(
                        v2_canonical_payload("purchase")
                    ),
                    accounting_provider=V2AccountingProvider(
                        [v2_complete_proposal]
                    ),
                    artifact_repository=artifact_repository,
                    tenant_id=str(store.tenant_id),
                    research_runtime={},
                )

            self.assertEqual(summary["completed_count"], 1)
            stored_document = next(
                item for item in store.get_workspace(client_id)["uploaded_documents"]
                if item["document_ref"] == document["document_ref"]
            )
            scope = store.document_ai_artifact_scope(
                client_id=client_id, document=stored_document
            )
            self.assertEqual(len(scope["document_id"]), 36)
            self.assertEqual(len(scope["source_file_id"]), 36)
            artifacts = artifact_repository.list_for_document(
                tenant_id=str(store.tenant_id),
                taxpayer_id=scope["taxpayer_id"],
                document_id=scope["document_id"],
            )
            self.assertEqual(artifacts[-1].kind, ArtifactKind.ACCOUNTING_PROPOSAL)


if __name__ == "__main__":
    unittest.main()
