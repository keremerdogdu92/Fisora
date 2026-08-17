from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_ai_artifacts import ArtifactKind
from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository
from app.workflows.gemini_invoice_pipeline import (
    GeminiInvoiceAccountingIdentity,
    GeminiInvoiceExtractionIdentity,
    GeminiInvoicePipelineRequest,
    run_gemini_invoice_pipeline_v2,
)


@dataclass(frozen=True)
class _Attempt:
    request_body: bytes
    response_body: bytes
    status: str
    provider: str = "gemini"
    model_alias: str = "gemini-test"
    resolved_model: str = "gemini-test-resolved"
    http_status: int | None = 200
    started_at: datetime = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    finished_at: datetime = datetime(2026, 8, 11, 9, 0, 0, 1000, tzinfo=UTC)
    elapsed_ms: int = 1
    token_usage: dict[str, int] | None = None
    error_metadata: dict[str, object] | None = None


class _Result(dict):
    def __init__(self, payload, *, attempt):
        super().__init__(payload)
        self.attempt = attempt


class _ProviderFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        provider: str = "gemini",
        model_alias: str = "gemini-test",
        resolved_model: str = "gemini-test-resolved",
    ):
        attempt = _Attempt(
            request_body=json.dumps({"stage": stage}).encode(),
            response_body=b'{"error":"provider_failed"}',
            status="failed",
            provider=provider,
            model_alias=model_alias,
            resolved_model=resolved_model,
            http_status=503,
            token_usage={},
            error_metadata={"phase": "transport", "message": message},
        )
        super().__init__(message)
        self.attempt = attempt


def _canonical_payload(direction: str = "purchase", *, warning: str = "") -> dict[str, object]:
    supplier_tax_id = "taxpayer-1" if direction == "sales" else "1234567890"
    customer_tax_id = "taxpayer-1" if direction == "purchase" else "1111111111"
    return {
        "header": {
            "invoice_no": f"INV-{direction}",
            "issue_date": "2026-08-11",
            "currency_code": "TRY",
            "document_direction": direction,
            "evidence": ["pdf:header"],
        },
        "supplier_party": {"title": "Supplier", "tax_id": supplier_tax_id, "evidence": ["pdf:supplier"]},
        "customer_party": {"title": "Customer", "tax_id": customer_tax_id, "evidence": ["pdf:customer"]},
        "line_items": [{
            "canonical_line_id": "l1", "source_position": "line:1", "description": "Service",
            "observed_taxable_amount": "100.00", "observed_vat_rate": "20", "observed_tax_amount": "20.00",
            "evidence": ["pdf:line:1"],
        }],
        "observed_vat_summary": [{
            "vat_group_id": "v20", "observed_rate": "20", "observed_taxable_amount": "100.00",
            "observed_tax_amount": "20.00", "contributing_line_ids": ["l1"], "evidence": ["pdf:vat"],
        }],
        "observed_tax_components": [{
            "component_type": "withholding", "source_label": "Withholding", "source_code": "WH",
            "taxable_amount": "100.00", "tax_amount": "10.00", "source_position": "tax:1",
            "included_in_tax_total": "yes", "included_in_payable": "yes", "evidence": ["pdf:tax"],
        }],
        "observed_monetary_components": [{
            "source_label": "Discount", "source_amount": "5.00", "source_position": "money:1",
            "included_in_line_net": "yes", "included_in_tax_total": "no", "included_in_payable": "yes",
            "evidence": ["pdf:discount"],
        }],
        "observed_totals": {
            "observed_goods_services_total": "100.00", "observed_vat_total": "20.00",
            "observed_special_tax_total": "10.00", "observed_tax_inclusive_total": "120.00",
            "observed_payable_total": "110.00", "evidence": ["pdf:totals"],
        },
        "extraction_notes": [warning] if warning else [],
    }


def _many_line_payload(line_count: int) -> dict[str, object]:
    payload = _canonical_payload("purchase")
    payload["line_items"] = [
        {
            "canonical_line_id": f"l{index:03d}",
            "source_position": f"line:{index}",
            "description": f"Distinct service {index}",
            "observed_taxable_amount": "1.00",
            "observed_vat_rate": "",
            "observed_tax_amount": "",
            "evidence": [f"pdf:line:{index}"],
        }
        for index in range(1, line_count + 1)
    ]
    payload["observed_vat_summary"] = []
    payload["observed_tax_components"] = []
    payload["observed_monetary_components"] = []
    total = f"{line_count:.2f}"
    payload["observed_totals"] = {
        "observed_goods_services_total": total,
        "observed_vat_total": "0.00",
        "observed_special_tax_total": "0.00",
        "observed_tax_inclusive_total": total,
        "observed_payable_total": total,
        "evidence": ["pdf:totals"],
    }
    return payload


def _workspace(*, expansion_target: bool = False) -> dict[str, object]:
    accounts = [
        {"code": "320.01", "name": "Supplier", "tax_id": "1234567890", "roles": ["counterparty"], "active": True},
        {"code": "120.01", "name": "Customer", "tax_id": "1111111111", "roles": ["counterparty"], "active": True},
        {"code": "770.01", "name": "Expense", "roles": ["line_expense"], "active": True},
        {"code": "600.01", "name": "Revenue", "roles": ["line_revenue"], "active": True},
        {"code": "191.20", "name": "Purchase VAT", "roles": ["vat"], "active": True},
        {"code": "391.20", "name": "Sales VAT", "roles": ["vat"], "active": True},
        {"code": "360.01", "name": "Withholding", "roles": ["special_tax"], "active": True},
        {"code": "649.01", "name": "Discount", "roles": ["special_tax"], "active": True},
    ]
    if expansion_target:
        accounts.extend(
            {"code": f"900.{index:02d}", "name": f"Generic {index}", "active": True}
            for index in range(50)
        )
        accounts.append({"code": "999.99", "name": "Expansion Target", "active": True})
    return {
        "chart_accounts": {"revision": "chart-r1", "accounts": accounts},
        "client": {"profile": {"activity_description": "Retail", "nace_code": "47.74"}},
    }


class _ExtractionProvider:
    provider_name = "gemini"
    model = "gemini-test"

    def __init__(self, payload: dict[str, object]):
        self.payload = payload
        self.requests = []

    def extract_invoice_canonical(self, request):
        self.requests.append(request)
        body = b'{"native_pdf":true}'
        response = json.dumps(self.payload, ensure_ascii=False).encode()
        return _Result(self.payload, attempt=_Attempt(body, response, "successful", token_usage={}, error_metadata={}))


class _FailingExtractionProvider:
    provider_name = "gemini"
    model = "gemini-test"

    def __init__(
        self,
        *,
        provider: str = "gemini",
        model_alias: str = "gemini-test",
        resolved_model: str = "gemini-test-resolved",
    ) -> None:
        self.provider = provider
        self.model_alias = model_alias
        self.resolved_model = resolved_model

    def extract_invoice_canonical(self, request):
        raise _ProviderFailure(
            "extraction failed",
            stage="document_extraction",
            provider=self.provider,
            model_alias=self.model_alias,
            resolved_model=self.resolved_model,
        )


class _AccountingProvider:
    provider_name = "gemini"
    model = "gemini-test"

    def __init__(self, outcomes: list[object]):
        self.outcomes = list(outcomes)
        self.requests = []

    def classify_product(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        payload = outcome(request) if callable(outcome) else outcome
        response = json.dumps(payload, ensure_ascii=False).encode()
        return _Result(payload, attempt=_Attempt(b'{"accounting":true}', response, "successful", token_usage={}, error_metadata={}))


def _complete_proposal(request) -> dict[str, object]:
    candidates = {item.candidate_id: item for item in request.sent_candidates}
    direction = request.projection["document_direction"]
    picks = {
        "counterparty": "120.01" if direction == "sales" else "320.01",
        "line": "600.01" if direction == "sales" else "770.01",
        "vat": "391.20" if direction == "sales" else "191.20",
        "tax": "360.01",
        "monetary": "649.01",
    }
    decisions = []
    for ref in request.required_decision_refs:
        if ref == "counterparty":
            continue
        prefix = ref.split(":", 1)[0]
        if prefix == "line-group":
            prefix = "line"
        selected = picks[prefix]
        assert selected in candidates
        tax_fact = next(
            (
                item
                for item in request.projection.get("tax_components", ())
                if item.get("decision_ref") == ref
            ),
            {},
        )
        treatment = (
            "payable_withholding"
            if prefix == "tax"
            and (
                tax_fact.get("canonical_tax_kind") == "withholding"
                or tax_fact.get("economic_effect") == "reduce_payable"
            )
            else "expense_or_cost"
            if prefix == "tax"
            else "increase_payable"
            if prefix == "monetary"
            else ""
        )
        decisions.append(
            {
                "decision_ref": ref,
                "action": "select_existing",
                "selected_candidate_id": selected,
                "selected_treatment": treatment,
                "reason": prefix,
            }
        )
    return {
        "counterparty": {"action": "select_existing", "selected_candidate_id": picks["counterparty"], "reason": "exact VKN", "proposal": None},
        "decisions": decisions,
        "candidate_sufficiency": {"sufficient": True, "request_more_candidates": False, "search_terms": [], "reason": "enough", "provisional": False},
    }


def _provisional(search_terms: list[str]):
    def outcome(request):
        payload = _complete_proposal(request)
        payload["candidate_sufficiency"] = {
            "sufficient": False, "request_more_candidates": True,
            "search_terms": search_terms, "reason": "expand", "provisional": True,
        }
        return payload
    return outcome


class GeminiInvoicePipelineV2Tests(unittest.TestCase):
    def test_targeted_treatment_clarification_runs_once_and_replaces_only_corrected_ref(self) -> None:
        tax_ref: list[str] = []

        def incomplete(request):
            payload = _complete_proposal(request)
            for decision in payload["decisions"]:
                if decision["decision_ref"].startswith("tax:"):
                    tax_ref.append(decision["decision_ref"])
                    decision["selected_treatment"] = ""
            return payload

        def corrected(request):
            self.assertEqual(request.required_decision_refs, ("counterparty", tax_ref[0]))
            self.assertEqual(request.context.semantic_stage, "treatment_clarification")
            self.assertEqual(
                request.context.clarification_decision["selected_candidate_id"],
                "360.01",
            )
            self.assertEqual(
                request.context.clarification_decision["selected_treatment"],
                "",
            )
            return _complete_proposal(request)

        result, accounting = self.run_pipeline(outcomes=[incomplete, corrected])

        self.assertEqual(len(accounting.requests), 2)
        corrected_decision = result.proposal.decision_for(tax_ref[0])
        self.assertEqual(corrected_decision.selected_candidate_id, "360.01")
        self.assertEqual(corrected_decision.selected_treatment, "payable_withholding")
        self.assertFalse(corrected_decision.treatment_review_required)
        self.assertNotIn(tax_ref[0], result.proposal.treatment_clarification_refs)
        self.assertIn("treatment_clarification_resolved", result.proposal.warnings)
        clarification_receipts = [
            artifact
            for artifact in result.artifacts
            if artifact.kind is ArtifactKind.PROVIDER_RECEIPT
            and artifact.metadata.get("clarification_for_ref") == tax_ref[0]
        ]
        self.assertEqual(len(clarification_receipts), 1)

    def test_targeted_treatment_clarification_accepts_valid_nonposting_decision(self) -> None:
        tax_ref: list[str] = []

        def incomplete(request):
            payload = _complete_proposal(request)
            for decision in payload["decisions"]:
                if decision["decision_ref"].startswith("tax:"):
                    tax_ref.append(decision["decision_ref"])
                    decision["selected_treatment"] = ""
            return payload

        def represented(request):
            payload = _complete_proposal(request)
            decision = next(
                item
                for item in payload["decisions"]
                if item["decision_ref"] == tax_ref[0]
            )
            decision.update(
                {
                    "action": "represented",
                    "selected_candidate_id": "",
                    "selected_treatment": "represented_in_line",
                    "reason": "canonical line already represents this tax",
                }
            )
            return payload

        result, accounting = self.run_pipeline(outcomes=[incomplete, represented])

        self.assertEqual(len(accounting.requests), 2)
        corrected = result.proposal.decision_for(tax_ref[0])
        self.assertEqual(corrected.action, "represented")
        self.assertEqual(corrected.selected_candidate_id, "")
        self.assertFalse(corrected.treatment_review_required)
        self.assertEqual(
            result.draft.line_for(tax_ref[0]).representation,
            "represented",
        )
        self.assertIn("treatment_clarification_resolved", result.proposal.warnings)
        self.assertNotIn("treatment_clarification_failed", result.proposal.warnings)

    def test_failed_targeted_treatment_clarification_keeps_suggestion_and_other_decisions(self) -> None:
        tax_ref: list[str] = []

        def incomplete(request):
            payload = _complete_proposal(request)
            for decision in payload["decisions"]:
                if decision["decision_ref"].startswith("tax:"):
                    tax_ref.append(decision["decision_ref"])
                    decision["selected_treatment"] = ""
            return payload

        result, accounting = self.run_pipeline(
            outcomes=[
                incomplete,
                _ProviderFailure(
                    "clarification unavailable",
                    stage="accounting_selection",
                ),
            ]
        )

        self.assertEqual(len(accounting.requests), 2)
        suggested = result.proposal.decision_for(tax_ref[0])
        self.assertEqual(suggested.selected_candidate_id, "360.01")
        self.assertTrue(suggested.treatment_review_required)
        self.assertEqual(result.draft.line_for(tax_ref[0]).resolution, "review_required")
        self.assertTrue(
            any(
                decision.action == "select_existing"
                for decision in result.proposal.decisions
                if decision.decision_ref.startswith(("line:", "line-group:"))
            )
        )
        self.assertIn("treatment_clarification_failed", result.proposal.warnings)
        self.assertNotIn("unresolved_accounts", result.warnings)

    def test_targeted_treatment_clarification_expands_candidates_once_within_round_limit(self) -> None:
        tax_ref: list[str] = []

        def incomplete(request):
            payload = _complete_proposal(request)
            for decision in payload["decisions"]:
                if decision["decision_ref"].startswith("tax:"):
                    tax_ref.append(decision["decision_ref"])
                    decision["selected_treatment"] = ""
            return payload

        def request_expansion(request):
            self.assertEqual(request.context.semantic_stage, "treatment_clarification")
            payload = incomplete(request)
            payload["candidate_sufficiency"] = {
                "sufficient": False,
                "request_more_candidates": True,
                "search_terms": ["Expansion Target"],
                "reason": "broader special-tax account needed",
                "provisional": True,
            }
            return payload

        def corrected_after_expansion(request):
            self.assertEqual(request.context.semantic_stage, "treatment_clarification")
            self.assertIn(
                "999.99",
                {candidate.candidate_id for candidate in request.sent_candidates},
            )
            return _complete_proposal(request)

        result, accounting = self.run_pipeline(
            workspace=_workspace(expansion_target=True),
            outcomes=[incomplete, request_expansion, corrected_after_expansion],
        )

        self.assertEqual(len(accounting.requests), 3)
        self.assertFalse(result.proposal.decision_for(tax_ref[0]).treatment_review_required)
        self.assertIn("treatment_clarification_resolved", result.proposal.warnings)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.pdf = self.root / "invoice.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\n%native-v2\n")
        self.source_bytes = self.pdf.read_bytes()
        self.source_sha = hashlib.sha256(self.source_bytes).hexdigest()
        self.repository = LocalDocumentAiArtifactRepository(
            manifest_path=self.root / "artifacts.json",
            storage=LocalDocumentStorage(self.root / "bodies"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def request(
        self,
        *,
        workspace=None,
        prior_valid_result=None,
        chart_revision="chart-r1",
        client_context=None,
        client_context_revision="",
        candidate_builder_version="accounting-candidate-builder-v2",
        pipeline_version="gemini-two-stage-v2",
        extraction_prompt_version="invoice-facts-v2",
        extraction_schema_version="canonical-invoice-v2",
        source_file_id="source-1",
        source_bytes=None,
        source_file_sha256=None,
        max_parallel_accounting_chunks=1,
        candidate_discovery_mode="adaptive",
        max_accounting_request_bytes=3_000_000,
        max_accounting_provider_calls=None,
    ):
        actual_source_bytes = source_bytes or self.source_bytes
        return GeminiInvoicePipelineRequest(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            source_file_id=source_file_id,
            source_file_sha256=source_file_sha256 or hashlib.sha256(actual_source_bytes).hexdigest(),
            source_bytes=actual_source_bytes, workspace=workspace or _workspace(),
            chart_revision=chart_revision,
            client_context=client_context or {"activity_description": "Retail"},
            client_context_revision=client_context_revision,
            candidate_builder_version=candidate_builder_version,
            pipeline_version=pipeline_version,
            extraction_prompt_version=extraction_prompt_version,
            extraction_schema_version=extraction_schema_version,
            max_parallel_accounting_chunks=max_parallel_accounting_chunks,
            candidate_discovery_mode=candidate_discovery_mode,
            max_accounting_request_bytes=max_accounting_request_bytes,
            max_accounting_provider_calls=max_accounting_provider_calls,
            prior_valid_result=prior_valid_result,
        )

    def run_pipeline(
        self,
        *,
        direction="purchase",
        outcomes=None,
        warning="",
        workspace=None,
        prior=None,
        extraction_payload=None,
        **request_kwargs,
    ):
        extraction = _ExtractionProvider(
            extraction_payload or _canonical_payload(direction, warning=warning)
        )
        accounting = _AccountingProvider(outcomes or [_complete_proposal])
        result = run_gemini_invoice_pipeline_v2(
            self.request(
                workspace=workspace,
                prior_valid_result=prior,
                **request_kwargs,
            ),
            extraction_provider=extraction,
            accounting_provider=accounting,
            artifact_repository=self.repository,
        )
        self.assertEqual(extraction.requests[0].document_bytes, self.source_bytes)
        self.assertEqual(extraction.requests[0].document_text, "")
        return result, accounting

    def test_result_and_artifacts_record_exact_typed_accounting_identity(self) -> None:
        result, _ = self.run_pipeline(client_context_revision="context-r1")

        self.assertIsInstance(result.accounting_identity, GeminiInvoiceAccountingIdentity)
        self.assertEqual(result.accounting_identity.chart_revision, "chart-r1")
        self.assertTrue(result.accounting_identity.canonical_revision)
        self.assertEqual(result.accounting_identity.candidate_builder_version, "accounting-candidate-builder-v2")
        self.assertEqual(result.accounting_identity.client_context_revision, "context-r1")
        self.assertEqual(result.accounting_identity.pipeline_version, "gemini-two-stage-v2")
        expected = result.accounting_identity.to_metadata()
        accounting_receipts = [
            item for item in result.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT and item.stage == "accounting_selection"
        ]
        proposal = next(item for item in result.artifacts if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL)
        self.assertTrue(accounting_receipts)
        self.assertTrue(all(item.metadata["accounting_identity"] == expected for item in accounting_receipts))
        self.assertEqual(proposal.metadata["accounting_identity"], expected)

    def test_document_direction_is_bound_to_exact_tenant_party_not_provider_label(self) -> None:
        for expected_direction in ("purchase", "sales"):
            with self.subTest(expected_direction=expected_direction):
                payload = _canonical_payload(expected_direction)
                payload["header"]["document_direction"] = "outbound"

                result, accounting = self.run_pipeline(
                    direction=expected_direction,
                    extraction_payload=payload,
                )

                self.assertEqual(result.canonical_invoice.header.document_direction, expected_direction)
                self.assertEqual(result.projection["document_direction"], expected_direction)
                self.assertEqual(accounting.requests[0].projection["document_direction"], expected_direction)
                self.assertTrue(result.draft.is_balanced)

    def test_extraction_receipt_and_result_record_exact_typed_extraction_identity(self) -> None:
        result, _ = self.run_pipeline()

        self.assertIsInstance(result.extraction_identity, GeminiInvoiceExtractionIdentity)
        expected = {
            "source_file_id": "source-1",
            "source_file_sha256": self.source_sha,
            "provider": "gemini",
            "model_alias": "gemini-test",
            "resolved_model": "gemini-test-resolved",
            "prompt_version": "invoice-facts-v2",
            "schema_version": "canonical-invoice-v2",
            "pipeline_version": "gemini-two-stage-v2",
        }
        self.assertEqual(result.extraction_identity.to_metadata(), expected)
        receipt = next(
            item for item in result.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT and item.stage == "document_extraction"
        )
        self.assertEqual(receipt.metadata["extraction_identity"], expected)
        self.assertEqual(receipt.source_file_id, expected["source_file_id"])
        self.assertEqual(receipt.source_file_sha256, expected["source_file_sha256"])
        self.assertEqual(receipt.provider, expected["provider"])
        self.assertEqual(receipt.model_alias, expected["model_alias"])
        self.assertEqual(receipt.resolved_model, expected["resolved_model"])
        self.assertEqual(receipt.prompt_version, expected["prompt_version"])
        self.assertEqual(receipt.schema_version, expected["schema_version"])
        self.assertEqual(receipt.pipeline_version, expected["pipeline_version"])

    def test_request_rejects_empty_chart_or_pipeline_revision(self) -> None:
        for field in ("chart_revision", "pipeline_version"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self.request(**{field: ""})

    def test_client_context_fingerprint_is_order_stable_and_content_sensitive(self) -> None:
        first = self.request(
            client_context={"nace_code": "62.01", "activity_tags": ["software"]},
        )
        reordered = self.request(
            client_context={"activity_tags": ["software"], "nace_code": "62.01"},
        )
        changed = self.request(
            client_context={"nace_code": "62.02", "activity_tags": ["software"]},
        )

        self.assertEqual(
            first.accounting_identity.client_context_revision,
            reordered.accounting_identity.client_context_revision,
        )
        self.assertNotEqual(
            first.accounting_identity.client_context_revision,
            changed.accounting_identity.client_context_revision,
        )

    def test_purchase_and_sales_preserve_all_fact_families_and_linked_artifacts(self) -> None:
        for direction in ("purchase", "sales"):
            with self.subTest(direction=direction):
                result, _ = self.run_pipeline(direction=direction)
                self.assertEqual(result.status, "partial")
                self.assertEqual(result.processing_status, "complete")
                self.assertEqual(result.extraction_validation_status, "invalid")
                self.assertTrue(result.draft.is_balanced)
                self.assertEqual(
                    {line.fact_ref.split(":", 1)[0] for line in result.draft.lines},
                    {"counterparty", "line", "vat", "tax", "monetary"},
                )
                self.assertEqual(
                    [artifact.kind for artifact in result.artifacts],
                    [
                        ArtifactKind.PROVIDER_RECEIPT,
                        ArtifactKind.CANONICAL_INVOICE_FORM,
                        ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                        ArtifactKind.PROVIDER_RECEIPT,
                        ArtifactKind.ACCOUNTING_PROPOSAL,
                    ],
                )
                self.assertTrue(all(item.source_file_sha256 == self.source_sha for item in result.artifacts))
                lineage = self.repository.trace_lineage(
                    tenant_id="tenant-1", taxpayer_id="taxpayer-1",
                    artifact_id=result.proposal_artifact_id,
                )
                self.assertEqual([item.kind for item in lineage][-3:], [
                    ArtifactKind.CANONICAL_INVOICE_FORM,
                    ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
                    ArtifactKind.ACCOUNTING_PROPOSAL,
                ])

    def test_invalid_extraction_validation_cannot_report_compatibility_complete(self) -> None:
        payload = _canonical_payload("purchase")
        payload["line_items"][0]["observed_tax_amount"] = ""

        result, _ = self.run_pipeline(extraction_payload=payload)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.processing_status, "complete")
        self.assertEqual(result.extraction_validation_status, "invalid")
        self.assertEqual(result.reconciliation_status, "exact")
        self.assertEqual(result.accounting_decision_status, "complete")
        self.assertEqual(result.draft_balance_status, "balanced")
        self.assertEqual(result.review_status, "review_required")
        self.assertEqual(result.export_status, "review_required")
        self.assertIn("line_tax_amount_missing", result.warnings)
        self.assertEqual(
            result.projection["canonical_evidence_categories"]["missing_evidence"],
            ["line_tax_amount_missing"],
        )
        self.assertEqual(
            result.projection["derived_line_to_vat_linkage"]["status"],
            "derived_reconciled",
        )

    def test_warnings_and_empty_expansion_retain_partial_draft(self) -> None:
        result, accounting = self.run_pipeline(
            warning="canonical_warning",
            outcomes=[_provisional(["definitely absent"])],
        )

        self.assertEqual(len(accounting.requests), 1)
        self.assertEqual(result.status, "partial")
        self.assertIsNotNone(result.draft)
        self.assertIn("canonical_warning", result.warnings)
        self.assertIn("candidate_expansion_returned_no_new_candidates", result.warnings)

    def test_decision_capacity_fast_path_and_ten_ref_chunk_boundary(self) -> None:
        fast, fast_provider = self.run_pipeline(
            extraction_payload=_many_line_payload(8),
        )
        chunked, chunked_provider = self.run_pipeline(
            extraction_payload=_many_line_payload(9),
            outcomes=[_complete_proposal, _complete_proposal],
        )

        self.assertEqual(1, len(fast_provider.requests))
        self.assertEqual(9, len(fast_provider.requests[0].required_decision_refs))
        self.assertEqual(2, len(chunked_provider.requests))
        self.assertEqual([9, 2], [len(item.required_decision_refs) for item in chunked_provider.requests])
        self.assertTrue(fast.draft.is_balanced)
        self.assertTrue(chunked.draft.is_balanced)
        self.assertEqual(9, len(chunked.proposal.decisions) - 1)

    def test_forty_plus_ref_middle_chunk_failure_continues_and_preserves_best_draft(self) -> None:
        result, provider = self.run_pipeline(
            extraction_payload=_many_line_payload(42),
            outcomes=[
                _complete_proposal,
                _complete_proposal,
                _ProviderFailure("middle chunk failed", stage="accounting_selection"),
                _complete_proposal,
                _complete_proposal,
                _complete_proposal,
            ],
        )

        self.assertEqual(6, len(provider.requests))
        self.assertEqual([9, 9, 9, 9, 9, 3], [len(item.required_decision_refs) for item in provider.requests])
        self.assertIsNotNone(result.proposal)
        self.assertIsNotNone(result.draft)
        self.assertEqual(8, len(result.proposal.unresolved_decision_refs))
        self.assertEqual(43, len(result.proposal.required_decision_refs))
        self.assertIn("accounting_chunk_failed", result.warnings)
        receipts = [
            item for item in result.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT and item.stage == "accounting_selection"
        ]
        self.assertEqual(
            ["successful", "successful", "failed", "successful", "successful", "successful"],
            [item.status for item in receipts],
        )
        proposal_artifact = next(
            item for item in result.artifacts if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL
        )
        self.assertEqual(
            tuple(receipt.artifact_id for receipt in receipts if receipt.status == "successful"),
            proposal_artifact.component_receipt_artifact_ids,
        )

    def test_chunked_document_shares_one_catalog_and_two_global_expansion_rounds(self) -> None:
        workspace = _workspace(expansion_target=True)
        workspace["chart_accounts"]["accounts"].extend([
            {"code": "999.98", "name": "Second Expansion", "active": True},
            {"code": "999.97", "name": "Never Requested Before Limit", "active": True},
        ])
        workspace["chart_accounts"]["accounts"].extend(
            {
                "code": f"880.{index:03d}",
                "name": f"Broad expansion universe {index}",
                "active": True,
            }
            for index in range(80)
        )
        result, provider = self.run_pipeline(
            extraction_payload=_many_line_payload(9),
            workspace=workspace,
            outcomes=[
                _provisional(["Expansion Target"]),
                _provisional(["Expansion Target"]),
                _provisional(["Second Expansion"]),
                _provisional(["Second Expansion"]),
                _provisional(["Never Requested Before Limit"]),
                _provisional(["Never Requested Before Limit"]),
            ],
        )

        self.assertEqual(6, len(provider.requests))
        self.assertEqual([0, 0, 1, 1, 2, 2], [item.round_index for item in result.candidate_rounds])
        self.assertEqual([0, 1, 0, 1, 0, 1], [item.chunk_index for item in result.candidate_rounds])
        for offset in (0, 2, 4):
            self.assertEqual(
                tuple(item.candidate_id for item in provider.requests[offset].sent_candidates),
                tuple(item.candidate_id for item in provider.requests[offset + 1].sent_candidates),
            )
        self.assertIn("candidate_expansion_limit_reached", result.warnings)
        self.assertIsNotNone(result.draft)
        self.assertEqual(2, max(
            candidate.origin_round
            for request in provider.requests
            for candidate in request.sent_candidates
        ))

    def test_parallel_chunks_are_persisted_and_merged_in_stable_chunk_order(self) -> None:
        result, _ = self.run_pipeline(
            extraction_payload=_many_line_payload(17),
            outcomes=[_complete_proposal, _complete_proposal, _complete_proposal],
            max_parallel_accounting_chunks=3,
        )

        self.assertEqual(
            [0, 1, 2],
            [item.chunk_index for item in result.candidate_rounds],
        )
        receipts = [
            item for item in result.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT
            and item.stage == "accounting_selection"
            and item.status == "successful"
        ]
        self.assertEqual(
            [0, 1, 2],
            [item.metadata["capacity_chunk_index"] for item in receipts],
        )
        proposal_artifact = next(
            item for item in result.artifacts
            if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL
        )
        self.assertEqual(
            tuple(item.artifact_id for item in receipts),
            proposal_artifact.component_receipt_artifact_ids,
        )
        self.assertTrue(result.draft.is_balanced)

    def test_only_chunks_requesting_more_candidates_are_replayed(self) -> None:
        result, provider = self.run_pipeline(
            extraction_payload=_many_line_payload(9),
            workspace=_workspace(expansion_target=True),
            outcomes=[
                _complete_proposal,
                _provisional(["Expansion Target"]),
                _complete_proposal,
            ],
        )

        self.assertEqual(3, len(provider.requests))
        self.assertEqual(
            [(0, 0), (0, 1), (1, 1)],
            [(item.round_index, item.chunk_index) for item in result.candidate_rounds],
        )
        self.assertTrue(result.draft.is_balanced)

        receipts = [
            item for item in result.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT
            and item.stage == "accounting_selection"
            and item.status == "successful"
        ]
        proposal_artifact = next(
            item for item in result.artifacts
            if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL
        )
        self.assertEqual(
            tuple(item.artifact_id for item in receipts),
            proposal_artifact.component_receipt_artifact_ids,
        )
        self.assertEqual(
            receipts[-1].artifact_id,
            proposal_artifact.provider_receipt_artifact_id,
        )

    def test_duplicate_descriptions_keep_per_line_decisions_through_pipeline(self) -> None:
        payload = _many_line_payload(2)
        payload["line_items"][1]["description"] = payload["line_items"][0]["description"]

        result, _ = self.run_pipeline(
            extraction_payload=payload,
            outcomes=[_complete_proposal],
        )

        self.assertIsNotNone(result.proposal)
        self.assertNotIn("accounting_proposal_invalid", result.warnings)
        self.assertEqual(2, len({
            item["decision_ref"] for item in result.projection["line_items"]
        }))
        self.assertEqual(2, len(result.draft.lines) - 1)

    def test_failed_later_expansion_keeps_last_successful_receipt_as_authority(self) -> None:
        result, accounting = self.run_pipeline(
            workspace=_workspace(expansion_target=True),
            outcomes=[_provisional(["Expansion Target"]), _ProviderFailure("later failed", stage="accounting_selection")],
        )

        self.assertEqual(len(accounting.requests), 2)
        receipts = [item for item in result.artifacts if item.kind is ArtifactKind.PROVIDER_RECEIPT and item.stage == "accounting_selection"]
        self.assertEqual([item.status for item in receipts], ["successful", "failed"])
        self.assertIsNone(receipts[1].retry_of_artifact_id)
        self.assertEqual(receipts[1].expanded_from_receipt_id, receipts[0].artifact_id)
        proposal_artifact = next(item for item in result.artifacts if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL)
        self.assertEqual(proposal_artifact.provider_receipt_artifact_id, receipts[0].artifact_id)
        self.assertIsNotNone(result.draft)
        self.assertIn("accounting_expansion_failed", result.warnings)

    def test_first_accounting_failure_creates_no_proposal_and_retains_prior_snapshot(self) -> None:
        prior, _ = self.run_pipeline()
        before = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
        )
        failed, _ = self.run_pipeline(
            outcomes=[_ProviderFailure("first accounting failed", stage="accounting_selection")],
            prior=prior,
        )
        after = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
        )

        self.assertEqual(len(after), len(before))
        self.assertEqual(failed.status, "partial")
        self.assertEqual(failed.draft, prior.draft)
        self.assertEqual(failed.proposal_artifact_id, prior.proposal_artifact_id)
        self.assertIn("accounting_initial_call_failed", failed.warnings)

    def test_invalid_first_accounting_decision_keeps_other_decisions_and_useful_draft(self) -> None:
        prior, _ = self.run_pipeline()
        invalid = _complete_proposal

        def unsent_candidate(request):
            payload = invalid(request)
            payload["decisions"][0]["selected_candidate_id"] = "external-account"
            return payload

        before = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
        )
        failed, _ = self.run_pipeline(outcomes=[unsent_candidate], prior=prior)
        after = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
        )

        self.assertEqual(len(after), len(before) + 1)
        self.assertNotEqual(failed.proposal_artifact_id, prior.proposal_artifact_id)
        line_ref = failed.projection["line_items"][0]["decision_ref"]
        vat_ref = failed.projection["vat_summary"][0]["decision_ref"]
        self.assertEqual(failed.proposal.decision_for(line_ref).action, "unresolved")
        self.assertEqual(failed.proposal.decision_for(vat_ref).action, "select_existing")
        self.assertEqual(failed.draft.line_for(line_ref).resolution, "unresolved")
        self.assertEqual(failed.draft.line_for(vat_ref).resolution, "resolved")
        self.assertIn("candidate_integrity_invalid", {
            issue.code for issue in failed.proposal.validation_issues
        })
        self.assertNotIn("accounting_proposal_invalid", failed.warnings)

    def test_later_invalid_decision_preserves_last_valid_with_warning_and_receipt_lineage(self) -> None:
        def later_invalid(request):
            payload = _complete_proposal(request)
            payload["decisions"][0]["selected_candidate_id"] = "external-account"
            return payload

        result, accounting = self.run_pipeline(
            workspace=_workspace(expansion_target=True),
            outcomes=[_provisional(["Expansion Target"]), later_invalid],
        )

        self.assertEqual(len(accounting.requests), 2)
        line_ref = result.projection["line_items"][0]["decision_ref"]
        self.assertEqual(
            result.proposal.decision_for(line_ref).selected_candidate_id,
            "770.01",
        )
        self.assertIn("latest_ai_decision_invalid", result.proposal.warnings)
        self.assertIn("using_last_valid_ai_decision", result.proposal.warnings)
        issue = next(
            item
            for item in result.proposal.validation_issues
            if item.decision_ref == line_ref
        )
        receipts = [
            item
            for item in result.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT
            and item.stage == "accounting_selection"
        ]
        self.assertEqual(issue.round_index, 1)
        self.assertEqual(issue.chunk_index, 0)
        self.assertEqual(issue.receipt_artifact_id, receipts[-1].artifact_id)
        proposal_artifact = next(
            item
            for item in result.artifacts
            if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL
        )
        self.assertEqual(
            tuple(item.artifact_id for item in receipts),
            proposal_artifact.component_receipt_artifact_ids,
        )
        persisted = json.loads(
            self.repository.read_content(
                tenant_id="tenant-1",
                taxpayer_id="taxpayer-1",
                artifact_id=proposal_artifact.artifact_id,
            )
        )
        self.assertNotIn("external-account", json.dumps(persisted["validation_issues"]))

    def test_later_normalized_line_decision_is_structurally_valid_not_last_valid_fallback(self) -> None:
        def later_normalized(request):
            payload = _complete_proposal(request)
            line_decision = next(
                decision
                for decision in payload["decisions"]
                if decision["decision_ref"].startswith(("line:", "line-group:"))
            )
            line_decision["selected_candidate_id"] = "649.01"
            line_decision["selected_treatment"] = "expense_or_cost"
            return payload

        result, accounting = self.run_pipeline(
            workspace=_workspace(expansion_target=True),
            outcomes=[_provisional(["Expansion Target"]), later_normalized],
        )

        self.assertEqual(len(accounting.requests), 2)
        line_ref = result.projection["line_items"][0]["decision_ref"]
        self.assertEqual(
            result.proposal.decision_for(line_ref).selected_candidate_id,
            "649.01",
        )
        self.assertNotIn("using_last_valid_ai_decision", result.proposal.warnings)
        self.assertIn(
            "nonoperative_treatment_ignored",
            {
                issue.code
                for issue in result.proposal.validation_issues
                if issue.decision_ref == line_ref
            },
        )

    def test_later_normalized_zero_fact_is_structurally_valid_not_last_valid_fallback(self) -> None:
        extraction = _canonical_payload("purchase")
        extraction["observed_tax_components"][0]["tax_amount"] = "0.00"
        extraction["observed_totals"]["observed_special_tax_total"] = "0.00"
        extraction["observed_totals"]["observed_payable_total"] = "120.00"

        result, accounting = self.run_pipeline(
            workspace=_workspace(expansion_target=True),
            extraction_payload=extraction,
            outcomes=[_provisional(["Expansion Target"]), _complete_proposal],
        )

        self.assertEqual(len(accounting.requests), 2)
        tax_ref = result.projection["tax_components"][0]["decision_ref"]
        decision = result.proposal.decision_for(tax_ref)
        self.assertEqual(decision.action, "no_separate_posting")
        self.assertEqual(decision.selected_candidate_id, "")
        self.assertNotIn("using_last_valid_ai_decision", result.proposal.warnings)
        self.assertIn(
            "zero_fact_normalized_to_no_separate_posting",
            {
                issue.code
                for issue in result.proposal.validation_issues
                if issue.decision_ref == tax_ref
            },
        )

    def test_later_incomplete_treatment_keeps_new_suggested_account_for_clarification(self) -> None:
        tax_ref: list[str] = []

        def later_incomplete(request):
            payload = _complete_proposal(request)
            tax_decision = next(
                decision
                for decision in payload["decisions"]
                if decision["decision_ref"].startswith("tax:")
            )
            tax_ref.append(tax_decision["decision_ref"])
            tax_decision["selected_candidate_id"] = "649.01"
            tax_decision["selected_treatment"] = ""
            return payload

        result, accounting = self.run_pipeline(
            workspace=_workspace(expansion_target=True),
            outcomes=[
                _provisional(["Expansion Target"]),
                later_incomplete,
                _ProviderFailure(
                    "clarification unavailable",
                    stage="accounting_selection",
                ),
            ],
        )

        self.assertEqual(len(accounting.requests), 3)
        suggested = result.proposal.decision_for(tax_ref[0])
        self.assertEqual(suggested.selected_candidate_id, "649.01")
        self.assertTrue(suggested.treatment_review_required)
        self.assertNotIn("using_last_valid_ai_decision", result.proposal.warnings)
        self.assertEqual(result.draft.line_for(tax_ref[0]).resolution, "review_required")
    def test_exhaustive_runs_all_rounds_and_adaptive_stops_after_sufficient_round_zero(self) -> None:
        workspace = _workspace(expansion_target=True)
        workspace["chart_accounts"]["accounts"].extend(
            {
                "code": f"880.{index:03d}",
                "name": f"Broad universe {index}",
                "active": True,
            }
            for index in range(80)
        )
        exhaustive, exhaustive_provider = self.run_pipeline(
            workspace=workspace,
            outcomes=[_complete_proposal, _complete_proposal, _complete_proposal],
            candidate_discovery_mode="exhaustive",
        )
        adaptive, adaptive_provider = self.run_pipeline(
            workspace=workspace,
            outcomes=[_complete_proposal],
            candidate_discovery_mode="adaptive",
        )

        universe_count = len(exhaustive_provider.requests[0].sent_candidates)
        counts = [len(request.sent_candidates) for request in exhaustive_provider.requests]
        self.assertEqual(len(exhaustive_provider.requests), 3)
        self.assertEqual(counts[0], 40)
        self.assertGreaterEqual(counts[1], 80)
        self.assertGreater(counts[2], counts[1])
        self.assertEqual(counts[2], exhaustive.candidate_rounds[-1].universe_count)
        self.assertEqual(exhaustive.candidate_rounds[-1].coverage_ratio, 1.0)
        self.assertFalse(exhaustive.candidate_rounds[-1].candidate_universe_truncated)
        self.assertEqual(len(adaptive_provider.requests), 1)
        self.assertEqual(adaptive.candidate_rounds[0].round_index, 0)
        self.assertGreater(universe_count, 0)

    def test_request_budget_truncation_is_stable_and_explicit(self) -> None:
        def unresolved(request):
            return {
                "counterparty": {"action": "unresolved", "selected_candidate_id": ""},
                "decisions": [
                    {
                        "decision_ref": ref,
                        "action": "unresolved",
                        "selected_candidate_id": "",
                        "selected_treatment": "other" if ref.startswith(("tax:", "monetary:")) else "",
                    }
                    for ref in request.required_decision_refs
                    if ref != "counterparty"
                ],
                "candidate_sufficiency": {
                    "sufficient": True,
                    "request_more_candidates": False,
                    "provisional": False,
                },
            }

        workspace = _workspace(expansion_target=True)
        workspace["chart_accounts"]["accounts"].extend(
            {
                "code": f"880.{index:03d}",
                "name": f"Broad universe {index}",
                "active": True,
            }
            for index in range(80)
        )
        result, provider = self.run_pipeline(
            workspace=workspace,
            outcomes=[unresolved, unresolved, unresolved],
            candidate_discovery_mode="exhaustive",
            max_accounting_request_bytes=25_000,
        )

        self.assertEqual(len(provider.requests), 3)
        self.assertTrue(result.candidate_rounds[-1].candidate_universe_truncated)
        self.assertLess(
            result.candidate_rounds[-1].sent_count,
            result.candidate_rounds[-1].universe_count,
        )
        self.assertIn("candidate_universe_truncated", result.warnings)
        self.assertTrue(
            all(round.serialized_request_bytes <= 25_000 for round in result.candidate_rounds)
        )
        self.assertEqual(
            [round.candidate_ids for round in result.candidate_rounds],
            [tuple(item.candidate_id for item in request.sent_candidates) for request in provider.requests],
        )

    def test_accounting_provider_call_budget_bounds_multi_chunk_document(self) -> None:
        result, provider = self.run_pipeline(
            extraction_payload=_many_line_payload(17),
            outcomes=[_complete_proposal, _complete_proposal],
            max_accounting_provider_calls=2,
            max_parallel_accounting_chunks=3,
        )

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(len(result.candidate_rounds), 2)
        self.assertIn("accounting_provider_call_budget_exhausted", result.warnings)
        self.assertEqual(result.status, "partial")

    def test_failed_first_call_does_not_reuse_prior_when_accounting_identity_changes(self) -> None:
        prior, _ = self.run_pipeline(client_context_revision="context-r1")
        changed_canonical = _canonical_payload()
        changed_canonical["header"]["invoice_no"] = "INV-CHANGED"
        cases = (
            {"chart_revision": "chart-r2", "client_context_revision": "context-r1"},
            {"client_context": {"activity_description": "Changed"}, "client_context_revision": "context-r2"},
            {"extraction_payload": changed_canonical, "client_context_revision": "context-r1"},
            {"candidate_builder_version": "accounting-candidate-builder-v3", "client_context_revision": "context-r1"},
            {"pipeline_version": "gemini-two-stage-v2.1", "client_context_revision": "context-r1"},
        )
        for changed in cases:
            with self.subTest(changed=changed):
                failed, _ = self.run_pipeline(
                    outcomes=[_ProviderFailure("first accounting failed", stage="accounting_selection")],
                    prior=prior,
                    **changed,
                )
                self.assertIsNone(failed.draft)
                self.assertFalse(failed.retained_prior_result)
                self.assertEqual(failed.proposal_artifact_id, "")

    def test_retry_links_to_latest_matching_failed_receipt(self) -> None:
        for _ in range(2):
            run_gemini_invoice_pipeline_v2(
                self.request(client_context_revision="context-r1"),
                extraction_provider=_FailingExtractionProvider(),
                accounting_provider=_AccountingProvider([_complete_proposal]),
                artifact_repository=self.repository,
            )
        extraction_receipts = [
            item for item in self.repository.list_for_document(
                tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
                kind=ArtifactKind.PROVIDER_RECEIPT,
            )
            if item.stage == "document_extraction"
        ]
        self.assertEqual([item.status for item in extraction_receipts], ["failed", "failed"])
        self.assertEqual(extraction_receipts[1].retry_of_artifact_id, extraction_receipts[0].artifact_id)

        for _ in range(2):
            self.run_pipeline(
                outcomes=[_ProviderFailure("accounting failed", stage="accounting_selection")],
                client_context_revision="context-r1",
            )
        accounting_receipts = [
            item for item in self.repository.list_for_document(
                tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
                kind=ArtifactKind.PROVIDER_RECEIPT,
            )
            if item.stage == "accounting_selection"
        ]
        self.assertEqual(accounting_receipts[-2].status, "failed")
        self.assertEqual(accounting_receipts[-1].retry_of_artifact_id, accounting_receipts[-2].artifact_id)

    def test_extraction_retry_and_prior_are_isolated_by_source_and_provider_contract(self) -> None:
        prior, _ = self.run_pipeline()
        changed_source = b"%PDF-1.7\n%different-native-v2\n"

        changed_source_result = run_gemini_invoice_pipeline_v2(
            self.request(
                source_bytes=changed_source,
                prior_valid_result=prior,
            ),
            extraction_provider=_FailingExtractionProvider(),
            accounting_provider=_AccountingProvider([_complete_proposal]),
            artifact_repository=self.repository,
        )
        self.assertFalse(changed_source_result.retained_prior_result)
        self.assertIsNone(changed_source_result.draft)
        self.assertIsNone(changed_source_result.artifacts[-1].retry_of_artifact_id)

        identity_changes = (
            ({}, _FailingExtractionProvider(provider="other-provider")),
            ({}, _FailingExtractionProvider(resolved_model="gemini-other-model")),
            ({"extraction_prompt_version": "invoice-facts-v3"}, _FailingExtractionProvider()),
            ({"extraction_schema_version": "canonical-invoice-v3"}, _FailingExtractionProvider()),
        )
        for request_changes, provider in identity_changes:
            with self.subTest(request_changes=request_changes, provider=provider.provider):
                failed = run_gemini_invoice_pipeline_v2(
                    self.request(prior_valid_result=prior, **request_changes),
                    extraction_provider=provider,
                    accounting_provider=_AccountingProvider([_complete_proposal]),
                    artifact_repository=self.repository,
                )
                self.assertFalse(failed.retained_prior_result)
                self.assertIsNone(failed.draft)
                self.assertIsNone(failed.artifacts[-1].retry_of_artifact_id)

    def test_blank_resolved_model_failure_uses_exact_model_alias_compatibility(self) -> None:
        prior, _ = self.run_pipeline()
        prior_extraction_receipt = next(
            item for item in prior.artifacts
            if item.kind is ArtifactKind.PROVIDER_RECEIPT and item.stage == "document_extraction"
        )

        compatible = run_gemini_invoice_pipeline_v2(
            self.request(prior_valid_result=prior),
            extraction_provider=_FailingExtractionProvider(resolved_model=""),
            accounting_provider=_AccountingProvider([_complete_proposal]),
            artifact_repository=self.repository,
        )
        compatible_receipt = compatible.artifacts[-1]
        self.assertTrue(compatible.retained_prior_result)
        self.assertEqual(compatible.draft, prior.draft)
        self.assertIsNone(compatible_receipt.retry_of_artifact_id)
        self.assertEqual(compatible_receipt.resolved_model, "")
        self.assertEqual(compatible_receipt.metadata["extraction_identity"]["resolved_model"], "")
        self.assertEqual(
            compatible_receipt.metadata["extraction_identity"]["model_alias"],
            "gemini-test",
        )

        incompatible = run_gemini_invoice_pipeline_v2(
            self.request(prior_valid_result=prior),
            extraction_provider=_FailingExtractionProvider(
                model_alias="gemini-other-alias",
                resolved_model="",
            ),
            accounting_provider=_AccountingProvider([_complete_proposal]),
            artifact_repository=self.repository,
        )
        self.assertFalse(incompatible.retained_prior_result)
        self.assertIsNone(incompatible.draft)
        self.assertIsNone(incompatible.artifacts[-1].retry_of_artifact_id)

    def test_extraction_failure_persists_receipt_without_canonical_and_retains_prior(self) -> None:
        prior, _ = self.run_pipeline()
        before_canonical = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.CANONICAL_INVOICE_FORM,
        )
        failed = run_gemini_invoice_pipeline_v2(
            self.request(prior_valid_result=prior),
            extraction_provider=_FailingExtractionProvider(),
            accounting_provider=_AccountingProvider([_complete_proposal]),
            artifact_repository=self.repository,
        )
        after_canonical = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.CANONICAL_INVOICE_FORM,
        )

        self.assertEqual(len(after_canonical), len(before_canonical))
        self.assertEqual(failed.draft, prior.draft)
        self.assertEqual(failed.proposal_artifact_id, prior.proposal_artifact_id)
        self.assertIn("document_extraction_failed", failed.warnings)
        self.assertEqual(failed.artifacts[-1].kind, ArtifactKind.PROVIDER_RECEIPT)
        self.assertEqual(failed.artifacts[-1].status, "failed")

    def test_extraction_mapping_failure_keeps_successful_receipt_and_same_identity_prior(self) -> None:
        prior, _ = self.run_pipeline(client_context_revision="context-r1")
        before_canonical = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.CANONICAL_INVOICE_FORM,
        )
        invalid_payload = _canonical_payload()
        invalid_payload["line_items"] = 123

        failed = run_gemini_invoice_pipeline_v2(
            self.request(
                prior_valid_result=prior,
                client_context_revision="context-r1",
            ),
            extraction_provider=_ExtractionProvider(invalid_payload),
            accounting_provider=_AccountingProvider([_complete_proposal]),
            artifact_repository=self.repository,
        )
        after_canonical = self.repository.list_for_document(
            tenant_id="tenant-1", taxpayer_id="taxpayer-1", document_id="document-1",
            kind=ArtifactKind.CANONICAL_INVOICE_FORM,
        )

        self.assertEqual(len(after_canonical), len(before_canonical))
        self.assertEqual(failed.draft, prior.draft)
        self.assertTrue(failed.retained_prior_result)
        self.assertIn("document_extraction_mapping_failed", failed.warnings)
        self.assertEqual(failed.artifacts[-1].kind, ArtifactKind.PROVIDER_RECEIPT)
        self.assertEqual(failed.artifacts[-1].status, "successful")

    def test_v2_module_has_no_legacy_parser_or_v1_orchestration_import(self) -> None:
        import app.workflows.gemini_invoice_pipeline as module

        source = inspect.getsource(module)
        for forbidden in ("pdf_invoices", "Textract", "textract", "build_processing_result", "run_gemini_two_stage_invoice_workflow"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
