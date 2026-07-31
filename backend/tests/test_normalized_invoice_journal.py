from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.workspace_exports import build_workspace_export_package
from app.domain.xml_invoices import build_xml_canonical_invoice
from app.domain.pdf_invoices import _bind_ai_payload_to_deterministic_lines
from app.domain.canonical_invoices import (
    CanonicalInvoice,
    CanonicalInvoiceLine,
    canonical_invoice_from_ai_payload,
    ensure_stable_line_ids,
    with_validation,
    validate_line_decision_coverage,
)
from app.persistence.normalized_accounting_repository import (
    NormalizedAccountingRepository,
    NormalizedRevisionConflict,
    _allocation_plan,
    _canonical_lines,
)
from app.domain.matching_simulation import AccountSelection, _line_decision_invoice_entry
from app.persistence.postgres_workflow_store import PostgresWorkflowStore, taxpayer_uuid
from app.persistence.postgres_workflow_store import tenant_uuid


class FakeNormalizedRepository:
    def __init__(self) -> None:
        self.source_by_hash: dict[str, str] = {}
        self.documents: dict[str, dict[str, object]] = {}
        self.histories: dict[str, list[dict[str, object]]] = {}
        self.jobs: dict[str, dict[str, object]] = {}

    def store_source_document(self, *, client_id: str, document: dict[str, object]) -> dict[str, object]:
        requested = str(document["document_id"])
        sha256 = str(document["sha256"])
        authoritative = self.source_by_hash.setdefault(sha256, requested)
        self.documents.setdefault(authoritative, {"client_id": client_id, "document_ref": authoritative})
        return {
            "document_ref": authoritative,
            "normalized_document_id": f"normalized-{authoritative}",
            "normalized_source_file_id": f"source-{authoritative}",
            "deduplicated": authoritative != requested,
            "requested_document_ref": requested,
        }

    def create_processing_job(self, **values: object) -> dict[str, object]:
        job = {
            **values,
            "id": f"job-{values['document_ref']}",
            "status": "queued",
            "attempt_count": 0,
            "created_at": "2026-07-18T10:00:00+00:00",
            "updated_at": "2026-07-18T10:00:00+00:00",
        }
        self.jobs[str(job["id"])] = deepcopy(job)
        return job

    def claim_next_processing_job(self) -> dict[str, object] | None:
        job = next((item for item in self.jobs.values() if item["status"] == "queued"), None)
        if job is None:
            return None
        job["status"] = "processing"
        job["attempt_count"] = int(job["attempt_count"]) + 1
        return deepcopy(job)

    def update_processing_job(
        self,
        *,
        job_id: str,
        status: str,
        error_message: str,
        processing_metrics: dict[str, object] | None,
    ) -> dict[str, object] | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job["status"] = status
        job["error_message"] = error_message
        job["processing_metrics"] = processing_metrics or {}
        return deepcopy(job)

    def persist_canonical_journal(
        self, *, client_id: str, document_ref: str, result: dict[str, object]
    ) -> dict[str, object]:
        snapshot = deepcopy(result)
        snapshot["normalized_revision"] = 1
        self.histories[document_ref] = [
            {"revision_no": 1, "status": "review_required", "result": snapshot}
        ]
        return {"revision_no": 1, "journal_entry_id": f"journal-{document_ref}"}

    def save_review(
        self,
        *,
        client_id: str,
        document_ref: str,
        decision: dict[str, object],
        corrected_result: dict[str, object],
    ) -> dict[str, object]:
        history = self.histories[document_ref]
        current = int(history[-1]["revision_no"])
        expected = int(decision.get("expected_revision") or 0)
        if expected and expected != current:
            raise NormalizedRevisionConflict(expected=expected, actual=current)
        revision_no = current + 1
        approved = corrected_result.get("export_status") == "export_ready"
        history.append(
            {
                "revision_no": revision_no,
                "status": "approved" if approved else "review_required",
                "result": deepcopy(corrected_result),
            }
        )
        return {"revision_no": revision_no, "approved": approved, "result": deepcopy(corrected_result)}

    def project_documents(self, *, client_id: str, approved_only: bool = False) -> list[dict[str, object]]:
        projections: list[dict[str, object]] = []
        for document_ref, history in self.histories.items():
            current = history[-1]
            if approved_only and current["status"] != "approved":
                continue
            result = deepcopy(current["result"])
            projections.append(
                {
                    "document_ref": document_ref,
                    "status": current["status"],
                    "export_status": result.get("export_status", "review_required"),
                    "normalized_revision": current["revision_no"],
                    "normalized_revision_status": current["status"],
                    "result": result,
                }
            )
        return projections

    def reopen(
        self,
        *,
        client_id: str,
        document_ref: str,
        expected_revision: int,
        reviewer: str,
        reason: str,
    ) -> dict[str, object]:
        history = self.histories[document_ref]
        current = int(history[-1]["revision_no"])
        if expected_revision != current:
            raise NormalizedRevisionConflict(expected=expected_revision, actual=current)
        if history[-1]["status"] != "approved":
            raise RuntimeError("only approved revisions can be reopened")
        snapshot = deepcopy(history[-1]["result"])
        snapshot["export_status"] = "review_required"
        revision_no = current + 1
        history.append({"revision_no": revision_no, "status": "working_draft", "result": snapshot})
        return {"document_ref": document_ref, "revision_no": revision_no, "result": deepcopy(snapshot)}


class MemoryBackedPostgresStore(PostgresWorkflowStore):
    def __init__(self, repository: FakeNormalizedRepository) -> None:
        super().__init__(
            "postgresql://unused",
            accounting_store_target="normalized",
            normalized_repository=repository,
        )
        self.records: dict[tuple[str, str, str], dict[str, object]] = {}

    def _ensure_taxpayer(self, *, client_id: str, profile: dict[str, object]) -> None:
        return None

    def _get_record(self, client_id: str, record_type: str, record_key: str) -> dict[str, object] | None:
        value = self.records.get((client_id, record_type, record_key))
        return deepcopy(value) if value is not None else None

    def _upsert_record(
        self,
        client_id: str,
        record_type: str,
        record_key: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.records[(client_id, record_type, record_key)] = deepcopy(payload)
        return deepcopy(payload)

    def _payloads(self, client_id: str, record_type: str) -> list[dict[str, object]]:
        return [
            deepcopy(payload)
            for (stored_client, stored_type, _), payload in self.records.items()
            if stored_client == client_id and stored_type == record_type
        ]

    def _get_record_by_key(self, record_type: str, record_key: str) -> dict[str, object] | None:
        for (client_id, stored_type, stored_key), payload in self.records.items():
            if stored_type == record_type and stored_key == record_key:
                return {"client_id": client_id, "record_key": stored_key, "payload": deepcopy(payload)}
        return None

    def list_operation_events(self, *, client_id: str | None = None) -> list[dict[str, object]]:
        return []


class NormalizedInvoiceJournalSliceTests(unittest.TestCase):
    def test_transaction_binding_preserves_custom_repository_subclass(self) -> None:
        class CustomNormalizedRepository(NormalizedAccountingRepository):
            pass

        repository = CustomNormalizedRepository(
            connect=lambda: None,
            tenant_id=tenant_uuid("custom-normalized-repository"),
            json_value=lambda value: value,
        )
        repository.custom_state = {"preserved": True}

        bound = repository.with_connection(object())

        self.assertIsInstance(bound, CustomNormalizedRepository)
        self.assertIsNot(bound, repository)
        self.assertIs(bound.custom_state, repository.custom_state)

    def test_phase2_stable_line_identity_survives_parser_reordering(self) -> None:
        first = ensure_stable_line_ids(
            CanonicalInvoice(
                source="xml",
                line_items=(
                    CanonicalInvoiceLine(
                        description="A",
                        external_line_id="UBL-10",
                        source_position="xml:InvoiceLine[UBL-10]",
                    ),
                    CanonicalInvoiceLine(
                        description="B",
                        external_line_id="UBL-20",
                        source_position="xml:InvoiceLine[UBL-20]",
                    ),
                ),
            )
        )
        reordered = ensure_stable_line_ids(
            CanonicalInvoice(
                source="xml",
                line_items=tuple(reversed(first.line_items)),
            )
        )

        self.assertEqual(
            {line.external_line_id: line.canonical_line_id for line in first.line_items},
            {line.external_line_id: line.canonical_line_id for line in reordered.line_items},
        )

    def test_phase2_line_decision_coverage_rejects_missing_duplicate_and_unknown_ids(self) -> None:
        invoice = ensure_stable_line_ids(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(description="A", source_position="pdf:line:10"),
                    CanonicalInvoiceLine(description="B", source_position="pdf:line:20"),
                ),
            )
        )
        first_id = invoice.line_items[0].canonical_line_id
        invalid = validate_line_decision_coverage(
            invoice.line_items,
            (
                {"canonical_line_id": first_id},
                {"canonical_line_id": first_id},
                {"canonical_line_id": "line_unknown"},
            ),
        )

        self.assertEqual(invalid.status, "invalid")
        self.assertEqual(invalid.missing_ids, (invoice.line_items[1].canonical_line_id,))
        self.assertEqual(invalid.duplicate_ids, (first_id,))
        self.assertEqual(invalid.unknown_ids, ("line_unknown",))

    def test_phase2_ai_provider_cannot_choose_canonical_line_identity(self) -> None:
        first = ensure_stable_line_ids(
            CanonicalInvoice(
                source="ai_canonical",
                line_items=(
                    CanonicalInvoiceLine(
                        description="A",
                        canonical_line_id="provider-controlled-a",
                        external_line_id="provider-external-a",
                        source_position="pdf:table:1:row:2",
                    ),
                ),
            )
        )
        second = ensure_stable_line_ids(
            CanonicalInvoice(
                source="ai_canonical",
                line_items=(
                    CanonicalInvoiceLine(
                        description="A",
                        canonical_line_id="provider-controlled-b",
                        external_line_id="provider-external-b",
                        source_position="pdf:table:1:row:2",
                    ),
                ),
            )
        )

        self.assertNotEqual(first.line_items[0].canonical_line_id, "provider-controlled-a")
        self.assertEqual(first.line_items[0].canonical_line_id, second.line_items[0].canonical_line_id)

    def test_phase2_ai_pdf_lines_must_echo_server_generated_identity(self) -> None:
        deterministic = ensure_stable_line_ids(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(description="A", source_position="pdf:table:1:row:2"),
                    CanonicalInvoiceLine(description="B", source_position="pdf:table:1:row:3"),
                ),
            )
        )
        ids = [line.canonical_line_id for line in deterministic.line_items]

        bound = _bind_ai_payload_to_deterministic_lines(
            {
                "line_items": [
                    {"canonical_line_id": ids[1], "source_position": "provider:changed", "description": "B"},
                    {"canonical_line_id": ids[0], "source_position": "provider:changed", "description": "A"},
                ]
            },
            deterministic,
        )

        self.assertEqual(
            [item["source_position"] for item in bound["line_items"]],
            ["pdf:table:1:row:3", "pdf:table:1:row:2"],
        )
        with self.assertRaisesRegex(ValueError, "coverage"):
            _bind_ai_payload_to_deterministic_lines(
                {"line_items": [{"canonical_line_id": ids[0]}]},
                deterministic,
            )

    def test_phase2_missing_vat_evidence_is_not_treated_as_zero_vat(self) -> None:
        invoice = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(
                        description="A",
                        source_position="pdf:line:10",
                        taxable_amount="100.00",
                        gross_amount="100.00",
                    ),
                ),
            )
        )

        self.assertEqual(invoice.validation.status, "invalid")
        self.assertIn("line_vat_rate_missing", invoice.validation.reason_codes)
        self.assertIn("line_tax_amount_missing", invoice.validation.reason_codes)

    def test_phase2_allocation_reconciles_mixed_vat_lines_to_journal_components(self) -> None:
        canonical_lines = [
            {
                "canonical_line_id": "line-a",
                "vat_group_id": "KDV|S|20|",
                "taxable_amount": "100.00",
                "vat_rate": "20",
                "tax_amount": "20.00",
                "gross_amount": "120.00",
            },
            {
                "canonical_line_id": "line-b",
                "vat_group_id": "KDV|S|10|",
                "taxable_amount": "50.00",
                "vat_rate": "10",
                "tax_amount": "5.00",
                "gross_amount": "55.00",
            },
        ]
        draft_lines = [
            {"account_code": "770.01", "debit": "150.00", "credit": "0.00"},
            {"account_code": "191.20", "debit": "20.00", "credit": "0.00", "tax_rate": "20"},
            {"account_code": "191.10", "debit": "5.00", "credit": "0.00", "tax_rate": "10"},
            {"account_code": "320.01", "debit": "0.00", "credit": "175.00"},
        ]

        plan, coverage = _allocation_plan(
            canonical_lines=canonical_lines,
            draft_lines=draft_lines,
            line_decisions=[
                {
                    "canonical_line_id": "line-a",
                    "account_code": "770.01",
                    "decision_origin": "vat_group_default",
                },
                {
                    "canonical_line_id": "line-b",
                    "account_code": "770.01",
                    "decision_origin": "vat_group_default",
                },
            ],
        )

        self.assertEqual(coverage["status"], "valid")
        self.assertEqual(len(plan), 6)
        self.assertEqual(coverage["missing_components"], [])
        self.assertEqual(coverage["unallocated_journal_lines"], [])
        self.assertEqual(plan[0]["vat_group_id"], "KDV|S|20|")
        self.assertEqual(plan[0]["component"], "net")
        self.assertEqual(plan[0]["allocated_amount"], Decimal("100.00"))
        self.assertEqual(plan[0]["decision_origin"], "vat_group_default")

    def test_phase2_allocation_rejects_account_or_vat_rate_mismatch(self) -> None:
        canonical_lines = [
            {
                "canonical_line_id": "line-a",
                "taxable_amount": "100.00",
                "vat_rate": "20",
                "tax_amount": "20.00",
                "gross_amount": "120.00",
            }
        ]
        draft_lines = [
            {"account_code": "153.01", "debit": "100.00", "credit": "0.00"},
            {"account_code": "191.10", "debit": "20.00", "credit": "0.00", "tax_rate": "10"},
            {"account_code": "320.01", "debit": "0.00", "credit": "120.00"},
        ]

        _plan, coverage = _allocation_plan(
            canonical_lines=canonical_lines,
            draft_lines=draft_lines,
            line_decisions=[{"canonical_line_id": "line-a", "account_code": "770.01"}],
        )

        self.assertEqual(coverage["status"], "invalid")
        self.assertTrue(any(":net:" in item for item in coverage["missing_components"]))
        self.assertTrue(any(":tax:" in item for item in coverage["missing_components"]))

    def test_phase2_heterogeneous_line_decisions_build_grouped_journal(self) -> None:
        canonical_items = (
            CanonicalInvoiceLine(
                description="Stok",
                canonical_line_id="line-stock",
                source_position="xml:1",
                taxable_amount="100.00",
                vat_rate="20",
                tax_amount="20.00",
                vat_group_id="KDV|S|20|",
            ),
            CanonicalInvoiceLine(
                description="Nakliye",
                canonical_line_id="line-freight",
                source_position="xml:2",
                taxable_amount="50.00",
                vat_rate="20",
                tax_amount="10.00",
                vat_group_id="KDV|S|20|",
            ),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        entry = _line_decision_invoice_entry(
            invoice=SimpleNamespace(
                payable_total="180.00",
                issue_date="2026-07-18",
                file_name="mixed.xml",
            ),
            canonical_items=canonical_items,
            line_decisions=[
                {
                    "canonical_line_id": "line-stock",
                    "account_code": "153.01",
                    "decision_origin": "confirmed_exception",
                },
                {
                    "canonical_line_id": "line-freight",
                    "account_code": "770.01",
                    "decision_origin": "vat_group_default",
                },
            ],
            selection=selection,
            direction="purchase",
            counterparty_account="320.01",
        )

        self.assertIsNotNone(entry)
        self.assertTrue(entry.is_balanced)
        self.assertEqual(
            [(line.account_code, f"{line.debit:.2f}", f"{line.credit:.2f}") for line in entry.lines],
            [
                ("153.01", "100.00", "0.00"),
                ("770.01", "50.00", "0.00"),
                ("191.20", "30.00", "0.00"),
                ("320.01", "0.00", "180.00"),
            ],
        )
        self.assertEqual(entry.lines[0].vat_group_id, "KDV|S|20|")
        self.assertEqual(entry.lines[0].contributing_line_ids, ("line-stock",))
        self.assertEqual(entry.lines[1].contributing_line_ids, ("line-freight",))
        self.assertEqual(entry.lines[2].vat_group_id, "KDV|S|20|")
        self.assertEqual(entry.lines[2].contributing_line_ids, ("line-stock", "line-freight"))

    def test_phase2_taxpayer_identity_is_tenant_scoped(self) -> None:
        tenant_a = tenant_uuid("office-a")
        tenant_b = tenant_uuid("office-b")

        self.assertNotEqual(
            taxpayer_uuid(tenant_a, "client-1"),
            taxpayer_uuid(tenant_b, "client-1"),
        )

    def test_phase2_return_invoice_preserves_available_original_invoice_reference(self) -> None:
        root = ET.fromstring(
            """
            <Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
                     xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
                     xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
              <cbc:ID>RET2026001</cbc:ID>
              <cbc:InvoiceTypeCode>IADE</cbc:InvoiceTypeCode>
              <cac:BillingReference>
                <cac:InvoiceDocumentReference>
                  <cbc:ID>SALE2025009</cbc:ID>
                  <cbc:IssueDate>2025-12-31</cbc:IssueDate>
                </cac:InvoiceDocumentReference>
              </cac:BillingReference>
              <cac:InvoiceLine>
                <cbc:ID>1</cbc:ID>
                <cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity>
                <cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount>
                <cac:Item><cbc:Name>Iade edilen urun</cbc:Name></cac:Item>
              </cac:InvoiceLine>
              <cac:LegalMonetaryTotal>
                <cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount>
                <cbc:TaxInclusiveAmount currencyID="TRY">100.00</cbc:TaxInclusiveAmount>
                <cbc:PayableAmount currencyID="TRY">100.00</cbc:PayableAmount>
              </cac:LegalMonetaryTotal>
            </Invoice>
            """
        )

        canonical = build_xml_canonical_invoice(root)

        self.assertEqual(canonical.header.original_invoice_no, "SALE2025009")
        self.assertEqual(canonical.header.original_invoice_date, "2025-12-31")

    def test_dataclass_serialized_canonical_line_tuple_is_persistable(self) -> None:
        self.assertEqual(
            _canonical_lines({"canonical_invoice": {"line_items": ({"description": "Hizmet"},)}}),
            [{"description": "Hizmet"}],
        )

    def test_legacy_canonical_payload_remains_readable_and_json_serializable(self) -> None:
        legacy_payload = {
            "line_items": [
                {
                    "description": "Bakim hizmeti",
                    "source_position": "xml:InvoiceLine[1]",
                    "taxable_amount": "100.00",
                    "vat_rate": "20",
                    "tax_amount": "20.00",
                    "gross_amount": "120.00",
                }
            ],
            "vat_summary": [{"rate": "20", "taxable_amount": "100.00", "tax_amount": "20.00"}],
            "totals": {"goods_services_total": "100.00", "vat_total": "20.00", "payable_total": "120.00"},
        }

        canonical = canonical_invoice_from_ai_payload(legacy_payload)
        serialized = asdict(canonical)

        self.assertEqual(serialized["line_items"][0]["description"], "Bakim hizmeti")
        self.assertEqual(serialized["line_items"][0]["tax_scheme_code"], "")
        self.assertEqual(serialized["vat_summary"][0]["tax_category_code"], "")
        self.assertEqual(
            _canonical_lines({"canonical_invoice": serialized}),
            list(serialized["line_items"]),
        )
        self.assertIsInstance(json.dumps(serialized), str)

    def test_purchase_invoice_runs_source_to_approved_export_and_reopen(self) -> None:
        repository = FakeNormalizedRepository()
        store = MemoryBackedPostgresStore(repository)
        store._upsert_record(
            "client-1",
            "client",
            "client-1",
            {"client_id": "client-1", "profile": {"title": "Alici Ltd", "tax_id": "2222222222"}},
        )
        source = store.save_uploaded_document(
            client_id="client-1",
            document={
                "document_id": "source-1",
                "original_file_name": "purchase.xml",
                "stored_file_name": "purchase.xml",
                "storage_path": "/documents/source-1/purchase.xml",
                "storage_backend": "local",
                "document_type": "einvoice_xml",
                "status": "stored",
                "storage_status": "stored",
                "size_bytes": 512,
                "sha256": "abc123",
                "retention_policy_days": 90,
            },
        )
        duplicate = store.save_uploaded_document(
            client_id="client-1",
            document={
                "document_id": "source-duplicate",
                "original_file_name": "purchase-copy.xml",
                "storage_path": "/documents/source-duplicate/purchase-copy.xml",
                "document_type": "einvoice_xml",
                "status": "stored",
                "storage_status": "stored",
                "size_bytes": 512,
                "sha256": "abc123",
            },
        )
        job = store.create_processing_job(
            client_id="client-1",
            document_ref=str(source["document_ref"]),
            document_type="einvoice_xml",
            parser_kind="xml_invoice",
            intake_category="purchase_invoice",
        )
        claimed_job = store.claim_next_processing_job()
        result = {
            "file_name": "purchase.xml",
            "accounting_direction": "purchase",
            "issue_date": "2026-07-18",
            "payable_total": "120.00",
            "simulated_status": "review_required",
            "export_status": "review_required",
            "draft_entry_type": "purchase_invoice",
            "total_debit": "120.00",
            "total_credit": "120.00",
            "is_balanced": True,
            "risk_flags": [],
            "review_reason_codes": [],
            "draft_lines": [
                {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                {"account_code": "191.01", "description": "KDV", "debit": "20.00", "credit": "0.00"},
                {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "120.00"},
            ],
            "canonical_invoice": {
                "header": {
                    "invoice_no": "ABC2026000000001",
                    "ettn": "11111111-1111-1111-1111-111111111111",
                    "issue_date": "2026-07-18",
                    "currency": "TRY",
                },
                "supplier_party": {"title": "Satici Ltd", "tax_id": "1111111111"},
                "customer_party": {"title": "Alici Ltd", "tax_id": "2222222222"},
                "totals": {
                    "line_extension_total": "100.00",
                    "vat_total": "20.00",
                    "payable_total": "120.00",
                },
                "line_items": [
                    {
                        "description": "Bakim hizmeti",
                        "quantity": "1",
                        "taxable_amount": "100.00",
                        "vat_rate": "20",
                        "tax_amount": "20.00",
                        "gross_amount": "120.00",
                    }
                ],
            },
        }
        saved_document = store.save_simulation_result(
            client_id="client-1",
            document_ref=str(source["document_ref"]),
            result=result,
        )
        completed_job = store.update_processing_job(
            job_id=str(job["id"]),
            status="completed",
            processing_metrics={"duration_ms": 1200},
        )
        review = store.save_review_decision(
            client_id="client-1",
            decision={
                "document_ref": "source-1",
                "action": "approve",
                "reviewer": "accountant-1",
                "reason": "Kontrol edildi.",
                "expected_revision": 1,
            },
            learning_event={"document_ref": "source-1", "reason": "Kontrol edildi."},
        )
        approved_workspace = store.authoritative_export_workspace("client-1")
        package = build_workspace_export_package(approved_workspace, export_type="zirve_universal_csv")
        approved_snapshot = deepcopy(repository.histories["source-1"][1])
        reopened = store.reopen_journal(
            client_id="client-1",
            document_ref="source-1",
            expected_revision=2,
            reviewer="accountant-1",
            reason="Hesap aciklamasi duzeltilecek.",
        )

        self.assertEqual(source["document_ref"], "source-1")
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(duplicate["document_ref"], "source-1")
        self.assertEqual(job["id"], "job-source-1")
        self.assertEqual(claimed_job["status"], "processing")
        self.assertEqual(claimed_job["attempt_count"], 1)
        self.assertEqual(completed_job["status"], "completed")
        self.assertEqual(saved_document["result"]["normalized_revision"], 1)
        self.assertEqual(len(result["canonical_invoice"]["line_items"]), 1)
        self.assertTrue(review["normalized_review"]["approved"])
        self.assertEqual(review["normalized_review"]["revision_no"], 2)
        self.assertEqual(len(package.package.entries), 1)
        self.assertEqual(reopened["revision_no"], 3)
        self.assertEqual(repository.histories["source-1"][1], approved_snapshot)
        self.assertEqual(repository.histories["source-1"][1]["status"], "approved")
        self.assertEqual(repository.histories["source-1"][2]["status"], "working_draft")

    def test_stale_review_cannot_overwrite_current_revision(self) -> None:
        repository = FakeNormalizedRepository()
        repository.histories["source-1"] = [
            {"revision_no": 2, "status": "approved", "result": {"export_status": "export_ready"}}
        ]

        with self.assertRaises(NormalizedRevisionConflict):
            repository.save_review(
                client_id="client-1",
                document_ref="source-1",
                decision={"expected_revision": 1},
                corrected_result={"export_status": "export_ready"},
            )

    def test_phase2_sales_invoice_uses_normalized_owner(self) -> None:
        repository = FakeNormalizedRepository()
        store = MemoryBackedPostgresStore(repository)
        store._upsert_record(
            "client-1",
            "client",
            "client-1",
            {"client_id": "client-1", "profile": {"title": "Satici Ltd", "tax_id": "2222222222"}},
        )
        store.save_uploaded_document(
            client_id="client-1",
            document={
                "document_id": "sales-source",
                "original_file_name": "sales.xml",
                "storage_path": "/documents/sales-source/sales.xml",
                "document_type": "einvoice_xml",
                "status": "stored",
                "storage_status": "stored",
                "size_bytes": 256,
                "sha256": "sales-sha",
            },
        )
        result = {
            "accounting_direction": "sales",
            "draft_lines": [
                {"account_code": "120.01", "debit": "120.00", "credit": "0.00"},
                {"account_code": "600.01", "debit": "0.00", "credit": "100.00"},
                {"account_code": "391.01", "debit": "0.00", "credit": "20.00"},
            ],
            "canonical_invoice": {
                "line_items": [
                    {
                        "canonical_line_id": "sales-line-1",
                        "source_position": "xml:InvoiceLine[1]",
                        "description": "Hizmet",
                        "taxable_amount": "100.00",
                        "tax_amount": "20.00",
                        "gross_amount": "120.00",
                    }
                ]
            },
        }

        saved = store.save_simulation_result(
            client_id="client-1",
            document_ref="sales-source",
            result=result,
        )

        self.assertEqual(saved["result"]["normalized_revision"], 1)
        self.assertIn("sales-source", repository.histories)

    def test_phase1_migration_contains_relational_ownership_constraints(self) -> None:
        schema = (ROOT / "backend" / "db" / "schema.sql").read_text(encoding="utf-8").lower()
        migration = (ROOT / "backend" / "db" / "migrations" / "003_normalized_invoice_journal_slice.sql").read_text(
            encoding="utf-8"
        ).lower()

        self.assertIn("create table if not exists source_files", schema)
        self.assertIn("create table if not exists document_sources", schema)
        self.assertIn("create table if not exists processing_jobs", schema)
        self.assertIn("create table if not exists journal_revisions", schema)
        self.assertIn("create table if not exists journal_revision_lines", schema)
        self.assertIn("create table if not exists workflow_events", schema)
        self.assertIn("unique (journal_entry_id, revision_no)", schema)
        self.assertIn("uq_documents_tenant_taxpayer_ettn", schema)
        self.assertNotIn("fisora:include", migration)
        self.assertIn("create table if not exists journal_revisions", migration)

    def test_phase2_migration_contains_lineage_allocation_and_attempt_fencing(self) -> None:
        schema = (ROOT / "backend" / "db" / "schema.sql").read_text(encoding="utf-8").lower()
        migration = (
            ROOT / "backend" / "db" / "migrations" / "004_phase2_canonical_line_allocations.sql"
        ).read_text(encoding="utf-8").lower()

        for sql in (schema, migration):
            self.assertIn("journal_line_allocations", sql)
            self.assertIn("extraction_version", sql)
            self.assertIn("source_fingerprint", sql)
            self.assertIn("current_attempt_id", sql)
        self.assertIn("ck_journal_revision_lines_nonnegative", migration)
        self.assertIn("ck_journal_revision_lines_one_sided", migration)


if __name__ == "__main__":
    unittest.main()
