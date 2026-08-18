from __future__ import annotations

import csv
from copy import deepcopy
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

from scripts.report_gemini_v2_accountant_pilot import (  # noqa: E402
    PilotReportRefused,
    _read_artifact_content,
    _rows_from_postgres,
    _resolution_evidence,
    build_pilot_report,
    write_pilot_report,
)


class GeminiV2AccountantPilotReportTests(unittest.TestCase):
    def _rows(self) -> list[dict[str, object]]:
        def candidate(candidate_id: str, *, active: bool = True) -> dict[str, object]:
            return {"candidate_id": candidate_id, "active": active, "code": candidate_id, "name": "safe"}

        proposal = {
            "required_decision_refs": ["counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1", "line:l2"],
            "sent_candidate_ids": ["acct-counterparty", "acct-line", "acct-vat", "acct-tax", "acct-suggest"],
            "counterparty": {
                "decision_ref": "counterparty", "action": "select_existing",
                "selected_candidate_id": "acct-counterparty", "candidate": candidate("acct-counterparty"),
            },
            "decisions": [
                {"decision_ref": "counterparty", "action": "select_existing", "selected_candidate_id": "acct-counterparty", "candidate": candidate("acct-counterparty")},
                {"decision_ref": "line:l1", "action": "select_existing", "selected_candidate_id": "acct-line", "candidate": candidate("acct-line")},
                {"decision_ref": "vat:v20", "action": "select_existing", "selected_candidate_id": "acct-vat", "candidate": candidate("acct-vat"), "selected_treatment": "no_separate_posting"},
                {"decision_ref": "tax:t1", "action": "select_existing", "selected_candidate_id": "acct-tax", "candidate": candidate("acct-tax"), "selected_treatment": "expense_or_cost", "treatment_review_required": False},
                {"decision_ref": "monetary:m1", "action": "select_existing", "selected_candidate_id": "acct-suggest", "candidate": candidate("acct-suggest"), "selected_treatment": "", "treatment_review_required": True},
                {"decision_ref": "line:l2", "action": "unresolved", "selected_candidate_id": "", "candidate": None},
            ],
            "validation_issues": [
                {"decision_ref": "vat:v20", "code": "nonoperative_treatment_ignored", "receipt_artifact_id": "receipt-normalization"},
            ],
            "semantic_conflicts": [{"decision_ref": "vat:v20", "conflict_code": "vat_rate_semantic_conflict"}],
        }
        return [
            {
                "document_id": "doc-opaque-1",
                "pipeline_version": "gemini-two-stage-v2",
                "processed_at": "2026-08-18T10:00:00+00:00",
                "job_status": "completed",
                "result": {
                    "canonical_validation_status": "valid",
                    "reconciliation_status": "exact",
                    "draft_balance_status": "balanced",
                    "accounting_decision_status": "complete",
                    "draft_status": "review_required",
                    "draft_lines": [
                        {"fact_ref": "counterparty", "resolution": "resolved", "selected_candidate_id": "acct-counterparty", "debit": "0.00", "credit": "0.00"},
                        {"fact_ref": "line:l1", "resolution": "resolved", "selected_candidate_id": "acct-line", "debit": "100.00", "credit": "0.00"},
                        {"fact_ref": "vat:v20", "resolution": "resolved", "selected_candidate_id": "acct-vat", "debit": "0.00", "credit": "20.00"},
                        {"fact_ref": "tax:t1", "resolution": "resolved", "selected_candidate_id": "acct-tax", "debit": "0.00", "credit": "10.00"},
                        {"fact_ref": "monetary:m1", "resolution": "review_required", "selected_candidate_id": "acct-suggest", "account_code": "acct-suggest", "debit": "0.00", "credit": "0.00"},
                        {"fact_ref": "line:l2", "resolution": "unresolved", "selected_candidate_id": "", "debit": "0.00", "credit": "0.00"},
                    ],
                },
                "artifacts": [
                    {
                        "id": "receipt-success",
                        "artifact_kind": "provider_receipt",
                        "status": "successful",
                        "credential_slot": "GEMINI_API_KEY_SLOT_2",
                        "http_status": 200,
                        "elapsed_ms": 120,
                        "token_usage": {"prompt_tokens": 10, "candidate_tokens": 5, "total_tokens": 15},
                        "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0},
                    },
                    {"id": "receipt-normalization", "artifact_kind": "provider_receipt", "status": "successful", "credential_slot": "GEMINI_API_KEY_SLOT_2", "http_status": 200, "elapsed_ms": 20, "token_usage": {}, "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0}},
                    {"id": "receipt-resolved", "artifact_kind": "provider_receipt", "status": "successful", "credential_slot": "GEMINI_API_KEY_SLOT_2", "http_status": 200, "elapsed_ms": 20, "token_usage": {}, "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0, "clarification_for_ref": "tax:t1", "clarification_attempt": 1}},
                    {"id": "receipt-failed", "artifact_kind": "provider_receipt", "status": "successful", "credential_slot": "GEMINI_API_KEY_SLOT_2", "http_status": 200, "elapsed_ms": 20, "token_usage": {}, "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0, "clarification_for_ref": "monetary:m1", "clarification_attempt": 1}},
                    {"id": "proposal-1", "artifact_kind": "accounting_proposal", "status": "successful", "provider_receipt_artifact_id": "receipt-success", "content": proposal, "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0}},
                    {
                        "artifact_kind": "canonical_invoice_form",
                        "status": "successful",
                        "metadata": {},
                    },
                ],
            },
            {
                "document_id": "doc-opaque-2",
                "pipeline_version": "gemini-two-stage-v2",
                "processed_at": "2026-08-18T10:01:00+00:00",
                "job_status": "retry_wait",
                "result": {},
                "artifacts": [
                    {
                        "artifact_kind": "provider_receipt",
                        "status": "failed",
                        "credential_slot": "GEMINI_API_KEY_SLOT_3",
                        "http_status": 429,
                        "elapsed_ms": 80,
                        "token_usage": {"total_tokens": 3},
                        "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0},
                    }
                ],
            },
        ]

    def test_report_has_machine_metrics_and_blank_accountant_grades(self) -> None:
        report = build_pilot_report(self._rows(), configured_experiment_percent=0)
        aggregate = report["aggregate"]
        self.assertEqual(aggregate["eligible_document_count"], 2)
        self.assertEqual(aggregate["completed"], 1)
        self.assertEqual(aggregate["retry_wait"], 1)
        self.assertEqual(aggregate["provider_attempts_by_credential_slot"], {
            "GEMINI_API_KEY_SLOT_2": 4,
            "GEMINI_API_KEY_SLOT_3": 1,
        })
        self.assertEqual(aggregate["http_status_counts"], {"200": 4, "429": 1})
        self.assertEqual(aggregate["latency_total_ms"], 260)
        self.assertEqual(aggregate["total_tokens"], 18)
        self.assertEqual(aggregate["canonical_extraction_available"], 1)
        self.assertEqual(aggregate["reconciliation_exact"], 1)
        self.assertEqual(aggregate["draft_balanced"], 1)
        self.assertEqual(aggregate["accounting_decision_complete"], 1)
        self.assertEqual(aggregate["nonoperative_treatment_ignored"], 1)
        self.assertEqual(aggregate["treatment_clarification_attempted"], 2)
        self.assertEqual(aggregate["treatment_clarification_resolved"], 1)
        self.assertEqual(aggregate["treatment_clarification_review_required"], 1)
        self.assertEqual(aggregate["suggested_account_preserved"], 1)
        self.assertEqual(aggregate["true_unresolved_account"], 1)
        self.assertEqual(aggregate["semantic_conflict_warnings"], 1)
        self.assertEqual(
            aggregate["representative_receipt_ids"],
            {
                "success": "receipt-success",
                "normalization": "receipt-normalization",
                "resolved_clarification": "receipt-resolved",
                "failed_clarification": "receipt-failed",
                "suggested_account": "receipt-success",
                "true_unresolved": "receipt-success",
            },
        )
        evidence = _resolution_evidence(self._rows()[0])["metric_refs"]
        self.assertFalse(evidence["suggested_account_preserved"] & evidence["true_unresolved_account"])

        with tempfile.TemporaryDirectory() as directory:
            paths = write_pilot_report(
                self._rows(), output_dir=Path(directory), configured_experiment_percent=0
            )
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertEqual(payload["aggregate"], aggregate)
            with paths["csv"].open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["document_id"], "doc-opaque-1")
            for column in ("account_selection_grade", "treatment_grade", "amount_balance_grade", "canonical_line_grade", "accountant_note"):
                self.assertEqual(rows[0][column], "")

    def test_report_refuses_exhaustive_observation_and_nonzero_configuration(self) -> None:
        exhaustive = self._rows()
        exhaustive[0]["artifacts"][0]["metadata"]["candidate_discovery_mode"] = "exhaustive"
        with self.assertRaisesRegex(PilotReportRefused, "exhaustive"):
            build_pilot_report(exhaustive, configured_experiment_percent=0)
        with self.assertRaisesRegex(PilotReportRefused, "experiment"):
            build_pilot_report(self._rows(), configured_experiment_percent=25)

    def test_report_does_not_emit_bodies_secrets_or_invalid_credential_slots(self) -> None:
        rows = self._rows()
        rows[0]["result"]["invoice_body"] = "SECRET-INVOICE-BODY"
        rows[0]["artifacts"].append({
            "artifact_kind": "provider_receipt",
            "status": "successful",
            "credential_slot": "AIza-secret-value",
            "http_status": 200,
            "metadata": {"response_body": "SECRET-RESPONSE-BODY"},
        })
        with tempfile.TemporaryDirectory() as directory:
            paths = write_pilot_report(rows, output_dir=Path(directory), configured_experiment_percent=0)
            rendered = paths["json"].read_text(encoding="utf-8") + paths["csv"].read_text(encoding="utf-8")
        self.assertNotIn("SECRET-INVOICE-BODY", rendered)
        self.assertNotIn("SECRET-RESPONSE-BODY", rendered)
        self.assertNotIn("AIza-secret-value", rendered)

    def test_accounting_proposal_content_path_escape_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "artifact-root"
            root.mkdir()
            outside = Path(directory) / "outside.json"
            outside.write_text('{"selected_candidate_id":"should-not-read"}', encoding="utf-8")
            with self.assertRaisesRegex(PilotReportRefused, "escapes"):
                _read_artifact_content(outside, root)

    def test_valid_represented_clarification_counts_as_resolved(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["required_decision_refs"].append("monetary:m2")
        proposal["decisions"].append({
            "decision_ref": "monetary:m2",
            "action": "represented",
            "selected_candidate_id": "acct-suggest",
            "candidate": {"candidate_id": "acct-suggest", "active": True},
            "selected_treatment": "represented",
            "treatment_review_required": False,
        })
        rows[0]["result"]["draft_lines"].append({
            "fact_ref": "monetary:m2",
            "resolution": "represented",
            "selected_candidate_id": "acct-suggest",
            "debit": "0.00",
            "credit": "0.00",
        })
        rows[0]["artifacts"].append({
            "id": "receipt-represented",
            "artifact_kind": "provider_receipt",
            "status": "successful",
            "credential_slot": "GEMINI_API_KEY_SLOT_2",
            "metadata": {"candidate_discovery_mode": "adaptive", "candidate_experiment_percent": 0, "clarification_for_ref": "monetary:m2", "clarification_attempt": 1},
        })
        report = build_pilot_report(rows, configured_experiment_percent=0)
        self.assertEqual(report["aggregate"]["treatment_clarification_resolved"], 2)

    def test_actual_hard_decision_issue_codes_count_unique_refs(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        codes = (
            "candidate_integrity_invalid",
            "ai_decision_validation_invalid",
            "unexpected_ai_decision_ref",
            "duplicate_ai_decision_ref",
            "missing_ai_decision",
        )
        proposal["validation_issues"] = [
            {"decision_ref": f"line:hard-{index}", "code": code, "receipt_artifact_id": "receipt-success"}
            for index, code in enumerate(codes)
        ]
        report = build_pilot_report(rows, configured_experiment_percent=0)
        self.assertEqual(report["aggregate"]["decision_integrity_rejections"], len(codes))

    def test_failed_only_clarification_does_not_get_resolved_receipt(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["decisions"][4]["treatment_review_required"] = True
        proposal["decisions"][4]["selected_treatment"] = ""
        rows[0]["result"]["draft_lines"][4]["resolution"] = "review_required"
        report = build_pilot_report(rows, configured_experiment_percent=0)
        representatives = report["aggregate"]["representative_receipt_ids"]
        self.assertEqual(representatives["resolved_clarification"], "receipt-resolved")
        self.assertEqual(representatives["failed_clarification"], "receipt-failed")
        failed_only = [rows[0]]
        failed_only[0]["artifacts"] = [
            item for item in failed_only[0]["artifacts"]
            if item.get("id") not in {"receipt-resolved"}
        ]
        failed_report = build_pilot_report(failed_only, configured_experiment_percent=0)
        self.assertEqual(failed_report["aggregate"]["representative_receipt_ids"]["resolved_clarification"], "")

    def test_resolution_rates_expose_metric_specific_denominators(self) -> None:
        report = build_pilot_report(self._rows(), configured_experiment_percent=0)
        aggregate = report["aggregate"]
        self.assertEqual(
            aggregate["resolution_metric_document_denominators"]["treatment_clarification_resolved"],
            {"kind": "eligible_documents", "value": 2},
        )
        self.assertEqual(
            aggregate["resolution_metric_ref_denominators"]["treatment_clarification_resolved"],
            {"kind": "clarification_attempted_refs", "value": 2},
        )
        self.assertEqual(
            aggregate["resolution_metric_ref_denominators"]["suggested_account_preserved"],
            {"kind": "treatment_review_refs", "value": 1},
        )
        self.assertEqual(
            aggregate["resolution_rates"]["treatment_clarification_resolved"]["decision_ref"],
            {"numerator": 1, "denominator": 2, "value": 0.5},
        )
        self.assertEqual(
            aggregate["resolution_metric_ref_denominators"]["treatment_clarification_attempted"],
            {"kind": "clarification_affected_refs", "value": 2},
        )
        self.assertEqual(
            aggregate["resolution_rates"]["treatment_clarification_attempted"]["attempt_count"],
            {"numerator": 2, "denominator": 2, "value": 1.0},
        )
        self.assertEqual(
            aggregate["resolution_metric_ref_denominators"]["nonoperative_treatment_ignored"],
            {"kind": "affected_decision_refs", "value": 1},
        )
        self.assertEqual(
            aggregate["resolution_rates"]["nonoperative_treatment_ignored"]["issue_count"],
            {"numerator": 1, "denominator": 1, "value": 1.0},
        )

    def test_zero_normalization_is_not_counted_as_nonoperative_metric(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["validation_issues"] = [{
            "decision_ref": "vat:v20",
            "code": "zero_fact_normalized_to_no_separate_posting",
            "receipt_artifact_id": "receipt-normalization",
        }]
        report = build_pilot_report(rows, configured_experiment_percent=0)
        self.assertEqual(report["aggregate"]["nonoperative_treatment_ignored"], 0)
        self.assertEqual(report["aggregate"]["representative_receipt_ids"]["normalization"], "receipt-normalization")

    def test_candidate_sufficiency_issue_is_not_a_decision_ref_or_integrity_rejection(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["validation_issues"] = [{
            "decision_ref": "candidate_sufficiency",
            "code": "candidate_sufficiency_invalid",
            "receipt_artifact_id": "receipt-success",
        }]
        report = build_pilot_report(rows, configured_experiment_percent=0)
        aggregate = report["aggregate"]
        self.assertEqual(aggregate["decision_integrity_rejections"], 0)
        self.assertEqual(aggregate["resolution_denominators"]["decision_ref_count"], 6)

    def test_missing_active_is_not_a_valid_candidate_and_select_existing_clarification_needs_it(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["decisions"][3]["candidate"].pop("active")
        report = build_pilot_report(rows, configured_experiment_percent=0)
        self.assertEqual(report["aggregate"]["treatment_clarification_resolved"], 0)

    def test_clarification_uses_terminal_receipt_and_skips_empty_ids(self) -> None:
        rows = self._rows()
        terminal = {
            "id": "receipt-resolved-terminal",
            "artifact_kind": "provider_receipt",
            "status": "successful",
            "metadata": {"clarification_for_ref": "tax:t1", "clarification_attempt": 2},
        }
        # Put the higher attempt before the original receipt so terminal
        # selection is numeric, not incidental artifact-list order.
        rows[0]["artifacts"].insert(2, terminal)
        rows[0]["artifacts"][3]["id"] = ""
        report = build_pilot_report(rows, configured_experiment_percent=0)
        self.assertEqual(
            report["aggregate"]["representative_receipt_ids"]["resolved_clarification"],
            "receipt-resolved-terminal",
        )

    def test_nonoperative_metric_reports_issue_count_and_affected_unique_refs(self) -> None:
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["validation_issues"] = [
            {"decision_ref": "vat:v20", "code": "nonoperative_treatment_ignored", "receipt_artifact_id": "receipt-normalization"},
            {"decision_ref": "vat:v20", "code": "nonoperative_treatment_ignored", "receipt_artifact_id": "receipt-success"},
            {"decision_ref": "", "code": "nonoperative_treatment_ignored", "receipt_artifact_id": "receipt-success"},
        ]
        report = build_pilot_report(rows, configured_experiment_percent=0)
        aggregate = report["aggregate"]
        self.assertEqual(aggregate["nonoperative_treatment_ignored"], 3)
        self.assertEqual(aggregate["nonoperative_treatment_ignored_affected_ref_count"], 1)
        self.assertEqual(
            aggregate["nonoperative_treatment_ignored_affected_refs"],
            [{"document_id": "doc-opaque-1", "decision_ref": "vat:v20"}],
        )
        self.assertEqual(aggregate["resolution_metric_count_kinds"]["nonoperative_treatment_ignored"], "validation_issue_count")

    def test_clarification_attempt_count_is_receipts_but_affected_refs_are_unique(self) -> None:
        rows = self._rows()
        rows[0]["artifacts"].append({
            "id": "receipt-resolved-attempt-2",
            "artifact_kind": "provider_receipt",
            "status": "successful",
            "metadata": {"clarification_for_ref": "tax:t1", "clarification_attempt": 2},
        })
        rows[0]["artifacts"].append({
            "id": "receipt-resolved-attempt-2-duplicate",
            "artifact_kind": "provider_receipt",
            "status": "successful",
            "metadata": {"clarification_for_ref": "tax:t1", "clarification_attempt": 2},
        })
        report = build_pilot_report(rows, configured_experiment_percent=0)
        aggregate = report["aggregate"]
        self.assertEqual(aggregate["treatment_clarification_attempted"], 3)
        self.assertEqual(aggregate["treatment_clarification_attempted_affected_ref_count"], 2)
        self.assertEqual(aggregate["resolution_metric_count_kinds"]["treatment_clarification_attempted"], "provider_attempt_count")

    def test_clarification_metadata_on_non_provider_artifact_is_ignored(self) -> None:
        rows = self._rows()
        rows[0]["artifacts"].append({
            "id": "proposal-not-receipt",
            "artifact_kind": "accounting_proposal",
            "status": "successful",
            "metadata": {"clarification_for_ref": "fake:ref", "clarification_attempt": 99},
        })
        report = build_pilot_report(rows, configured_experiment_percent=0)
        self.assertEqual(report["aggregate"]["treatment_clarification_attempted"], 2)

    def test_affected_ref_denominators_preserve_instances_across_documents(self) -> None:
        rows = self._rows()
        second = deepcopy(rows[0])
        second["document_id"] = "doc-opaque-2-shared-ref"
        rows.append(second)
        aggregate = build_pilot_report(rows, configured_experiment_percent=0)["aggregate"]
        self.assertEqual(aggregate["nonoperative_treatment_ignored"], 2)
        self.assertEqual(aggregate["nonoperative_treatment_ignored_affected_ref_count"], 2)
        self.assertEqual(
            aggregate["nonoperative_treatment_ignored_affected_refs"],
            [
                {"document_id": "doc-opaque-1", "decision_ref": "vat:v20"},
                {"document_id": "doc-opaque-2-shared-ref", "decision_ref": "vat:v20"},
            ],
        )
        self.assertEqual(aggregate["treatment_clarification_attempted"], 4)
        self.assertEqual(aggregate["treatment_clarification_attempted_affected_ref_count"], 4)
        self.assertEqual(
            aggregate["treatment_clarification_attempted_affected_refs"],
            [
                {"document_id": "doc-opaque-1", "decision_ref": "monetary:m1"},
                {"document_id": "doc-opaque-1", "decision_ref": "tax:t1"},
                {"document_id": "doc-opaque-2-shared-ref", "decision_ref": "monetary:m1"},
                {"document_id": "doc-opaque-2-shared-ref", "decision_ref": "tax:t1"},
            ],
        )
        self.assertEqual(
            aggregate["resolution_metric_ref_denominators"]["treatment_clarification_attempted"],
            {"kind": "clarification_affected_refs", "value": 4},
        )

    def test_suggested_account_requires_final_draft_account_code_match(self) -> None:
        blank = self._rows()
        blank[0]["result"]["draft_lines"][4]["account_code"] = ""
        self.assertEqual(build_pilot_report(blank, configured_experiment_percent=0)["aggregate"]["suggested_account_preserved"], 0)
        different = self._rows()
        different[0]["result"]["draft_lines"][4]["account_code"] = "770.99"
        self.assertEqual(build_pilot_report(different, configured_experiment_percent=0)["aggregate"]["suggested_account_preserved"], 0)

    def test_missing_ai_decision_remains_hard_integrity_metric(self) -> None:
        # The approved amendment treats missing/unknown/unsent/inactive refs as
        # hard integrity failures even when the parser returns a partial proposal.
        rows = self._rows()
        proposal = rows[0]["artifacts"][4]["content"]
        proposal["validation_issues"] = [{
            "decision_ref": "line:missing",
            "code": "missing_ai_decision",
            "receipt_artifact_id": "receipt-success",
        }]
        self.assertEqual(build_pilot_report(rows, configured_experiment_percent=0)["aggregate"]["decision_integrity_rejections"], 1)


@unittest.skipUnless(
    os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip(),
    "set FISORA_TEST_POSTGRES_DSN to run fake-provider PostgreSQL pilot proof",
)
class GeminiV2AccountantPilotPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scripts = BACKEND / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from apply_migrations import apply_migrations, discover_migrations

        cls.dsn = os.environ["FISORA_TEST_POSTGRES_DSN"].strip()
        apply_migrations(cls.dsn, discover_migrations(BACKEND / "db" / "migrations"))

    def test_preserved_source_requeues_v2_and_report_surfaces_fresh_balanced_draft(self) -> None:
        from app.domain.document_ai_artifacts import ArtifactKind
        from app.domain.storage_adapters import LocalDocumentStorage
        from app.persistence.gemini_trial_reset_repository import reset_gemini_trial_outputs
        from app.persistence.document_ai_artifact_repository import PostgresDocumentAiArtifactRepository
        from app.persistence.postgres_workflow_store import PostgresWorkflowStore
        from app.services.workspace_service import WorkspaceService
        from app.workflows.document_processing import process_next_job_once
        from backend.tests.test_gemini_invoice_pipeline_v2 import (
            _AccountingProvider,
            _ExtractionProvider,
            _canonical_payload,
            _complete_proposal,
            _workspace,
        )

        suffix = uuid4().hex
        tenant_key = f"accountant-pilot-{suffix}"
        client_id = f"client-{suffix}"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "preserved-invoice.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%fake-provider-pilot\n")
            repository = PostgresDocumentAiArtifactRepository(
                dsn=self.dsn,
                storage=LocalDocumentStorage(root / "artifact-bodies"),
            )
            store = PostgresWorkflowStore(
                self.dsn,
                tenant_key=tenant_key,
                accounting_store_target="compatibility",
                document_ai_artifact_repository=repository,
            )
            store.upsert_client(client_id=client_id, profile={"title": "Pilot", "tax_id": "1111111111"}, onboarding={})
            store.replace_chart_accounts(client_id=client_id, accounts=list(_workspace()["chart_accounts"]["accounts"]))
            document = store.save_uploaded_document(
                client_id=client_id,
                document={
                    "document_id": f"document-{suffix}",
                    "source_file_id": f"source-{suffix}",
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
            source_before = pdf.read_bytes()
            with patch.dict(os.environ, {"FISORA_GEMINI_PDF_V2_ENABLED": "true"}, clear=False):
                summary = process_next_job_once(
                    store,
                    extraction_provider=_ExtractionProvider(_canonical_payload("purchase")),
                    accounting_provider=_AccountingProvider([_complete_proposal]),
                    artifact_repository=repository,
                    tenant_id=str(store.tenant_id),
                    research_runtime={},
                )
            self.assertEqual(summary["completed_count"], 1)
            self.assertEqual(pdf.read_bytes(), source_before)
            workspace = store.get_workspace(client_id)
            old_result = next(item for item in workspace["documents"] if item["document_ref"] == document["document_ref"])["result"]
            self.assertTrue(old_result["is_balanced"])
            uploaded = workspace["uploaded_documents"][0]
            scope = store.document_ai_artifact_scope(client_id=client_id, document=uploaded)
            old_artifacts = repository.list_for_document(
                tenant_id=str(store.tenant_id),
                taxpayer_id=scope["taxpayer_id"],
                document_id=scope["document_id"],
            )
            old_artifact_ids = {item.artifact_id for item in old_artifacts}
            self.assertTrue(old_artifact_ids)

            reset_summary = reset_gemini_trial_outputs(
                dsn=self.dsn,
                tenant_key=tenant_key,
                artifact_storage_root=root / "artifact-bodies",
                apply=True,
                confirm_tenant_key=tenant_key,
            )
            self.assertEqual(reset_summary.requeued_job_count, 1)
            reset_workspace = store.get_workspace(client_id)
            self.assertEqual(reset_workspace["documents"], [])
            self.assertEqual(len(reset_workspace["processing_jobs"]), 1)
            self.assertEqual(reset_workspace["processing_jobs"][0]["status"], "queued")
            self.assertEqual(pdf.read_bytes(), source_before)

            with patch.dict(os.environ, {"FISORA_GEMINI_PDF_V2_ENABLED": "true"}, clear=False):
                fresh_summary = process_next_job_once(
                    store,
                    extraction_provider=_ExtractionProvider(_canonical_payload("purchase")),
                    accounting_provider=_AccountingProvider([_complete_proposal]),
                    artifact_repository=repository,
                    tenant_id=str(store.tenant_id),
                    research_runtime={},
                )
            self.assertEqual(fresh_summary["completed_count"], 1)
            fresh_workspace = store.get_workspace(client_id)
            fresh_result = next(item for item in fresh_workspace["documents"] if item["document_ref"] == document["document_ref"])["result"]
            self.assertTrue(fresh_result["is_balanced"])
            fresh_artifacts = repository.list_for_document(
                tenant_id=scope["tenant_id"],
                taxpayer_id=scope["taxpayer_id"],
                document_id=scope["document_id"],
            )
            fresh_artifact_ids = {item.artifact_id for item in fresh_artifacts}
            self.assertTrue(fresh_artifact_ids)
            self.assertTrue(old_artifact_ids.isdisjoint(fresh_artifact_ids))

            rows = _rows_from_postgres(
                self.dsn,
                tenant_key,
                artifact_storage_root=root / "artifact-bodies",
            )
            report = build_pilot_report(rows, configured_experiment_percent=0)
            self.assertEqual(report["aggregate"]["eligible_document_count"], 1)
            self.assertEqual(report["aggregate"]["completed"], 1)
            self.assertEqual(report["aggregate"]["draft_balanced"], 1)
            self.assertIn(ArtifactKind.ACCOUNTING_PROPOSAL, {item.kind for item in fresh_artifacts})

            try:
                from fastapi.testclient import TestClient
                from app.main import app
            except ModuleNotFoundError:
                self.skipTest("fastapi is not installed")
            route_service = WorkspaceService(
                store=store,
                document_storage_path=root,
                record_operation_event=lambda **kwargs: {},
                require_client_access=lambda **kwargs: {"allowed": True},
                request_user_id=lambda *_args: "accountant-pilot",
            )
            with patch("app.api.phase0_routes_workspace.get_workspace_service", return_value=route_service):
                response = TestClient(app).get(
                    f"/phase0/store/workspace/{client_id}",
                    headers={"X-Fisora-User-Id": "accountant-pilot"},
                )
            self.assertEqual(response.status_code, 200)
            rendered_workspace = response.text
            self.assertNotIn(next(iter(old_artifact_ids)), rendered_workspace)
            self.assertIn(next(iter(fresh_artifact_ids)), rendered_workspace)


if __name__ == "__main__":
    unittest.main()
