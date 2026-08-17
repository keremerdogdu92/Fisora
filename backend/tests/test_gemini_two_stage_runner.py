from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.run_gemini_two_stage_v1 import (  # noqa: E402
    build_safe_document_report,
    probe_prerequisites,
    run_controlled_proof,
)
from app.domain.openai_provider import GeminiAttemptEnvelope, GeminiStructuredResult  # noqa: E402


def _attempt(index: int) -> GeminiAttemptEnvelope:
    started = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    return GeminiAttemptEnvelope(
        request_body=f'{{"request":{index}}}'.encode(),
        response_body=f'{{"response":{index}}}'.encode(),
        provider="gemini",
        model_alias="gemini-test-model",
        resolved_model="gemini-test-model-001",
        http_status=200,
        started_at=started,
        finished_at=started + timedelta(milliseconds=25),
        elapsed_ms=25,
        token_usage={"prompt_tokens": 10, "candidate_tokens": 5, "total_tokens": 15},
        status="successful",
        error_metadata={},
    )


def _canonical_payload() -> dict[str, object]:
    return {
        "header": {
            "invoice_no": "PRIVATE-INVOICE",
            "ettn": "",
            "issue_date": "2026-08-11",
            "invoice_type": "SATIS",
            "scenario": "",
            "currency_code": "TRY",
            "document_direction": "purchase",
            "original_invoice_no": "",
            "original_invoice_date": "",
            "evidence": ["$.header"],
        },
        "supplier_party": {
            "title": "PRIVATE SUPPLIER",
            "tax_id": "1234567890",
            "tax_id_type": "VKN",
            "tax_office": "",
            "address": "",
            "evidence": ["$.supplier_party"],
        },
        "customer_party": {
            "title": "PRIVATE CUSTOMER",
            "tax_id": "1111111111",
            "tax_id_type": "VKN",
            "tax_office": "",
            "address": "",
            "evidence": ["$.customer_party"],
        },
        "line_items": [
            {
                "canonical_line_id": "line-1",
                "source_position": "page:1#line:1",
                "external_line_id": "1",
                "description": "PRIVATE LINE",
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
        "observed_tax_components": [],
        "observed_monetary_components": [],
        "observed_totals": {
            "observed_goods_services_total": "100.00",
            "observed_allowance_total": "0.00",
            "observed_vat_total": "20.00",
            "observed_special_tax_total": "0.00",
            "observed_tax_inclusive_total": "120.00",
            "observed_payable_total": "120.00",
            "evidence": ["$.totals"],
        },
        "extraction_notes": ["test-warning"],
    }


class _FakeGeminiProvider:
    def __init__(self) -> None:
        self.attempt_count = 0

    def _result(self, payload: dict[str, object]) -> GeminiStructuredResult:
        self.attempt_count += 1
        return GeminiStructuredResult(payload, attempt=_attempt(self.attempt_count))

    def extract_invoice_canonical(self, request):
        return self._result(_canonical_payload())

    def classify_product(self, request):
        payload = request.to_schema_payload()
        candidate_ids = {
            str(item["candidate_id"]): item for item in payload["account_candidates"]
        }
        self.assert_candidate(candidate_ids, "770.01")
        self.assert_candidate(candidate_ids, "191.20")
        self.assert_candidate(candidate_ids, "320.01")
        return self._result(
            {
                "action": "finalize",
                "candidate_set_sufficient": True,
                "proposal": {
                    "counterparty_account": {
                        "selected_candidate_id": "320.01",
                        "reason": "tenant candidate",
                    },
                    "line_accounts": [
                        {
                            "line_ref": "line-1",
                            "selected_candidate_id": "770.01",
                            "reason": "tenant candidate",
                        }
                    ],
                    "vat_accounts": [
                        {
                            "vat_ref": str(payload["output_schema"]["properties"]["proposal"]["properties"]["vat_accounts"]["items"]["properties"]["vat_ref"]["enum"][0]),
                            "rate": "20",
                            "selected_candidate_id": "191.20",
                            "reason": "tenant candidate",
                        }
                    ],
                    "special_tax_accounts": [],
                    "new_counterparty_proposal": None,
                },
                "request_more_candidates": {
                    "search_terms": [],
                    "requested_scope": "",
                    "reason": "",
                },
                "reason": "complete",
            }
        )

    @staticmethod
    def assert_candidate(candidates, candidate_id: str) -> None:
        if candidate_id not in candidates:
            raise AssertionError(f"missing test candidate {candidate_id}")


class _FailingAccountingProvider(_FakeGeminiProvider):
    def classify_product(self, request):
        raise RuntimeError("PRIVATE provider detail must not escape")


class GeminiTwoStageRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_probe_supports_existing_five_case_manifest_and_reports_only_safe_blockers(self) -> None:
        existing_pdf = self.root / "private-title-and-tax-id.pdf"
        existing_pdf.write_bytes(b"%PDF-1.7\n")
        missing_pdf = self.root / "missing-private-invoice.pdf"
        manifest = self.root / "results.json"
        manifest.write_text(
            json.dumps(
                {
                    "benchmark": "gemini-accounting-one-call-vs-two-call",
                    "cases": [
                        {"invoice_id": "safe-doc-1", "source_pdf": str(existing_pdf)},
                        {"invoice_id": "safe-doc-2", "source_pdf": str(missing_pdf)},
                    ],
                }
            ),
            encoding="utf-8",
        )
        workspace = self.root / "missing-workspace-private-name.json"
        secret = "should-never-be-printed"

        result = probe_prerequisites(
            manifest_path=manifest,
            workspace_path=workspace,
            env={"GEMINI_API_KEY": "", "FISORA_GEMINI_MODEL": "gemini-test-model"},
            tenant_id="tenant-real",
            taxpayer_id="taxpayer-real",
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["document_count"], 2)
        self.assertEqual(result["available_document_count"], 1)
        self.assertEqual(
            result["missing_prerequisites"],
            ["gemini_api_key", "workspace_file", "document_files:1"],
        )
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(str(existing_pdf), serialized)
        self.assertNotIn(str(missing_pdf), serialized)
        self.assertNotIn(str(workspace), serialized)
        self.assertNotIn(secret, serialized)

    def test_probe_rejects_empty_chart_accounts_and_missing_real_scope_identity(self) -> None:
        pdf = self.root / "invoice.pdf"
        pdf.write_bytes(b"%PDF-1.7\n")
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps({"model_alias": "gemini-test-model", "documents": [{"id": "doc-1", "pdf_path": str(pdf)}]}),
            encoding="utf-8",
        )
        workspace = self.root / "workspace.json"
        workspace.write_text(
            json.dumps({"chart_accounts": {"accounts": [{}]}}),
            encoding="utf-8",
        )

        result = probe_prerequisites(
            manifest_path=manifest,
            workspace_path=workspace,
            env={"GEMINI_API_KEY": "present"},
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(
            result["missing_prerequisites"],
            ["tenant_chart_accounts", "tenant_identity", "taxpayer_identity"],
        )

    def test_probe_requires_price_configuration_for_unknown_selected_model(self) -> None:
        pdf = self.root / "invoice.pdf"
        pdf.write_bytes(b"%PDF-1.7\n")
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "model_alias": "gemini-unknown-future-model",
                    "tenant_id": "tenant-real",
                    "taxpayer_id": "taxpayer-real",
                    "documents": [{"id": "doc-1", "pdf_path": str(pdf)}],
                }
            ),
            encoding="utf-8",
        )
        workspace = self.root / "workspace.json"
        workspace.write_text(
            json.dumps(
                {
                    "tenant_id": "tenant-real",
                    "taxpayer_id": "taxpayer-real",
                    "chart_accounts": {"accounts": [{"normalized_account_code": "770.01"}]},
                }
            ),
            encoding="utf-8",
        )

        result = probe_prerequisites(
            manifest_path=manifest,
            workspace_path=workspace,
            env={"GEMINI_API_KEY": "present"},
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["missing_prerequisites"], ["model_pricing"])

    def test_safe_report_exposes_metrics_but_not_private_invoice_or_account_values(self) -> None:
        canonical = {
            "header": {"invoice_no": "PRIVATE-INVOICE-NO"},
            "supplier_party": {"title": "PRIVATE SUPPLIER", "tax_id": "1234567890"},
            "customer_party": {"title": "PRIVATE CUSTOMER", "tax_id": "1111111111"},
            "line_items": [{"description": "PRIVATE LINE"}, {"description": "PRIVATE LINE 2"}],
            "vat_summary": [{"rate": "20"}],
            "tax_components": [{"component_type": "special_tax"}],
            "totals": {
                "goods_services_total": "100.00",
                "vat_total": "20.00",
                "payable_total": "130.00",
            },
        }
        projection = {
            "supplier_party": {"title": "PRIVATE SUPPLIER", "tax_id": "1234567890"},
            "customer_party": {"title": "PRIVATE CUSTOMER", "tax_id": "1111111111"},
            "line_items": [{"description": "PRIVATE LINE"}, {"description": "PRIVATE LINE 2"}],
            "vat_summary": [{"rate": "20"}],
            "tax_components": [{"component_type": "special_tax"}],
            "totals": {
                "goods_services_total": "100.00",
                "vat_total": "20.00",
                "payable_total": "130.00",
            },
        }
        result = {
            "status": "review_required",
            "is_balanced": True,
            "pipeline_warnings": ["safe-warning-code"],
            "draft_lines": [
                {
                    "proposal_role": "canonical_line",
                    "account_code": "770.PRIVATE",
                    "account_name": "PRIVATE ACCOUNT",
                },
                {"proposal_role": "vat_group", "account_code": "191.PRIVATE"},
                {"proposal_role": "counterparty", "account_code": "320.PRIVATE"},
            ],
            "accounting_proposal": {
                "accounting_call_count": 2,
                "expansion_count": 1,
                "selection_origin_round": 0,
            },
            "document_ai_artifacts": {
                "extraction_receipt_id": "artifact-extraction",
                "canonical_invoice_form_id": "artifact-canonical",
                "accounting_input_projection_id": "artifact-projection",
                "accounting_proposal_id": "artifact-proposal",
            },
        }
        artifacts = [
            SimpleNamespace(
                kind=SimpleNamespace(value="provider_receipt"),
                elapsed_ms=125,
                token_usage={"prompt_tokens": 1000, "candidate_tokens": 200, "total_tokens": 1200},
            ),
            SimpleNamespace(
                kind=SimpleNamespace(value="provider_receipt"),
                elapsed_ms=75,
                token_usage={"prompt_tokens": 500, "candidate_tokens": 100, "total_tokens": 600},
            ),
        ]

        report = build_safe_document_report(
            document_id="safe-doc-1",
            source_sha256="a" * 64,
            result=result,
            artifacts=artifacts,
            canonical_payload=canonical,
            projection_payload=projection,
            canonical_size_bytes=2000,
            projection_size_bytes=1000,
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(report["coverage"]["canonical"]["line_count"], 2)
        self.assertEqual(report["coverage"]["projection"]["party_tax_id_count"], 2)
        self.assertTrue(report["coverage"]["retained"]["all_accounting_facts"])
        self.assertEqual(report["projection_size_ratio"], 0.5)
        self.assertEqual(report["warnings"], {
            "count": 1,
            "pipeline_continued": False,
            "draft_retained": True,
            "last_observed_stage": "source",
        })
        self.assertEqual(report["accounting"]["call_count"], 2)
        self.assertEqual(report["accounting"]["expansion_count"], 1)
        self.assertEqual(report["accounting"]["selection_origin_round"], 0)
        self.assertEqual(report["provider"]["elapsed_ms"], 200)
        self.assertEqual(report["provider"]["tokens"], {
            "input": 1500,
            "output": 300,
            "total": 1800,
        })
        self.assertEqual(report["provider"]["estimated_cost_usd"], "0.001500")
        self.assertEqual(report["draft"], {
            "status": "review_required",
            "line_count": 3,
            "is_balanced": True,
            "role_counts": {"canonical_line": 1, "counterparty": 1, "vat_group": 1},
        })
        self.assertNotEqual(report["document_id"], "safe-doc-1")
        self.assertRegex(report["document_id"], r"^document-[a-f0-9]{16}$")

        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        for forbidden in (
            "PRIVATE-INVOICE-NO",
            "PRIVATE SUPPLIER",
            "PRIVATE CUSTOMER",
            "PRIVATE LINE",
            "1234567890",
            "1111111111",
            "770.PRIVATE",
            "PRIVATE ACCOUNT",
            "safe-warning-code",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_fact_integrity_detects_equal_counts_with_changed_values(self) -> None:
        canonical = {
            "supplier_party": {"tax_id": "1234567890"},
            "customer_party": {"tax_id": "1111111111"},
            "line_items": [{"canonical_line_id": "line-1", "taxable_amount": "100.00", "tax_amount": "20.00"}],
            "vat_summary": [{"rate": "20", "taxable_amount": "100.00", "tax_amount": "20.00"}],
            "tax_components": [{"component_type": "special_tax", "tax_amount": "10.00"}],
            "totals": {"payable_total": "130.00"},
        }
        projection = {
            "supplier_party": {"tax_id": "9999999999"},
            "customer_party": {"tax_id": "8888888888"},
            "line_items": [{"canonical_line_id": "line-1", "taxable_amount": "999.00", "tax_amount": "99.00"}],
            "vat_summary": [{"rate": "20", "taxable_amount": "999.00", "tax_amount": "99.00"}],
            "tax_components": [{"component_type": "special_tax", "tax_amount": "88.00"}],
            "totals": {"payable_total": "999.00"},
        }

        report = build_safe_document_report(
            document_id="doc-1",
            source_sha256="b" * 64,
            result={"status": "review_required", "draft_lines": []},
            artifacts=[],
            canonical_payload=canonical,
            projection_payload=projection,
            canonical_size_bytes=100,
            projection_size_bytes=100,
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        retained = report["coverage"]["retained"]
        self.assertFalse(retained["party_tax_ids"])
        self.assertFalse(retained["line_items"])
        self.assertFalse(retained["vat_summary"])
        self.assertFalse(retained["tax_components"])
        self.assertFalse(retained["totals"])
        self.assertFalse(retained["all_accounting_facts"])
        serialized = json.dumps(report, sort_keys=True)
        for private_value in ("1234567890", "9999999999", "130.00", "999.00"):
            self.assertNotIn(private_value, serialized)

    def test_controlled_proof_uses_production_workflow_and_isolates_each_rerun(self) -> None:
        pdf = self.root / "private.pdf"
        pdf.write_bytes(b"%PDF-1.7\n%native-provider-only\n")
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "model_alias": "gemini-test-model",
                    "tenant_id": "tenant-real",
                    "taxpayer_id": "taxpayer-real",
                    "documents": [{"invoice_id": "PRIVATE202600000001", "source_pdf": str(pdf)}],
                }
            ),
            encoding="utf-8",
        )
        workspace = self.root / "workspace.json"
        workspace.write_text(
            json.dumps(
                {
                    "tenant_id": "tenant-real",
                    "taxpayer_id": "taxpayer-real",
                    "client": {"profile": {"tax_id": "1111111111", "title": "PRIVATE CUSTOMER"}},
                    "chart_accounts": {
                        "accounts": [
                            {"normalized_account_code": "770.01", "account_name": "PRIVATE EXPENSE"},
                            {"normalized_account_code": "191.20", "account_name": "PRIVATE VAT"},
                            {"normalized_account_code": "320.01", "account_name": "PRIVATE SUPPLIER", "tax_id": "1234567890"},
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        output = self.root / "output"
        provider = _FakeGeminiProvider()

        first = run_controlled_proof(
            manifest_path=manifest,
            workspace_path=workspace,
            output_dir=output,
            env={"GEMINI_API_KEY": "fake-boundary-key"},
            provider=provider,
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )
        second = run_controlled_proof(
            manifest_path=manifest,
            workspace_path=workspace,
            output_dir=output,
            env={"GEMINI_API_KEY": "fake-boundary-key"},
            provider=provider,
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(first["status"], "OK", first)
        self.assertEqual(second["status"], "OK", second)
        self.assertEqual(first["model_alias"], "gemini-test-model")
        self.assertEqual(first["documents"][0]["workflow_status"], "complete")
        self.assertEqual(first["documents"][0]["provider"]["tokens"]["total"], 30)
        self.assertEqual(second["documents"][0]["provider"]["tokens"]["total"], 30)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(list((output / "runs").glob("*/artifact-manifest.json"))), 2)
        self.assertTrue(first["documents"][0]["warnings"]["pipeline_continued"])
        serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
        for private_value in (
            "PRIVATE202600000001",
            "PRIVATE CUSTOMER",
            "PRIVATE SUPPLIER",
            "1234567890",
            "1111111111",
            "fake-boundary-key",
            str(pdf),
            str(workspace),
        ):
            self.assertNotIn(private_value, serialized)

    def test_safe_report_marks_missing_required_artifacts_partial(self) -> None:
        report = build_safe_document_report(
            document_id="doc-1",
            source_sha256="c" * 64,
            result={
                "status": "review_required",
                "pipeline_warnings": ["provider-warning"],
                "draft_lines": [{"proposal_role": "canonical_line"}],
                "accounting_proposal": {"accounting_call_count": 1},
            },
            artifacts=[
                SimpleNamespace(kind=SimpleNamespace(value="provider_receipt"), stage="document_extraction", status="successful", elapsed_ms=1, token_usage={}),
                SimpleNamespace(kind=SimpleNamespace(value="canonical_invoice_form"), stage="canonical_mapping", status="successful"),
                SimpleNamespace(kind=SimpleNamespace(value="accounting_input_projection"), stage="accounting_projection", status="successful"),
            ],
            canonical_payload={},
            projection_payload={},
            canonical_size_bytes=1,
            projection_size_bytes=1,
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(report["workflow_status"], "partial")
        self.assertTrue(report["warnings"]["pipeline_continued"])
        self.assertEqual(report["warnings"]["last_observed_stage"], "draft")

    def test_safe_report_keeps_partial_proposal_as_partial_quality(self) -> None:
        artifacts = [
            SimpleNamespace(kind=SimpleNamespace(value="provider_receipt"), stage="document_extraction", status="successful", elapsed_ms=1, token_usage={}),
            SimpleNamespace(kind=SimpleNamespace(value="canonical_invoice_form"), stage="canonical_mapping", status="successful"),
            SimpleNamespace(kind=SimpleNamespace(value="accounting_input_projection"), stage="accounting_projection", status="successful"),
            SimpleNamespace(kind=SimpleNamespace(value="provider_receipt"), stage="accounting_selection", status="successful", elapsed_ms=1, token_usage={}),
            SimpleNamespace(kind=SimpleNamespace(value="accounting_proposal"), stage="accounting_proposal", status="partial"),
        ]

        report = build_safe_document_report(
            document_id="doc-1",
            source_sha256="d" * 64,
            result={
                "draft_status": "review_required",
                "pipeline_warnings": ["accounting_provider_failed"],
                "draft_lines": [{"proposal_role": "canonical_line", "debit": "1", "credit": "1"}],
            },
            artifacts=artifacts,
            canonical_payload={},
            projection_payload={},
            canonical_size_bytes=1,
            projection_size_bytes=1,
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(report["workflow_status"], "partial")
        self.assertTrue(report["warnings"]["pipeline_continued"])
        self.assertTrue(report["warnings"]["draft_retained"])

    def test_controlled_proof_reports_partial_when_accounting_stage_warns_and_draft_survives(self) -> None:
        pdf = self.root / "private.pdf"
        pdf.write_bytes(b"%PDF-1.7\n%native-provider-only\n")
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "model_alias": "gemini-test-model",
                    "tenant_id": "tenant-real",
                    "taxpayer_id": "taxpayer-real",
                    "documents": [{"invoice_id": "PRIVATE202600000001", "source_pdf": str(pdf)}],
                }
            ),
            encoding="utf-8",
        )
        workspace = self.root / "workspace.json"
        workspace.write_text(
            json.dumps(
                {
                    "tenant_id": "tenant-real",
                    "taxpayer_id": "taxpayer-real",
                    "client": {"profile": {"tax_id": "1111111111"}},
                    "chart_accounts": {"accounts": [{"normalized_account_code": "770.01"}]},
                }
            ),
            encoding="utf-8",
        )

        report = run_controlled_proof(
            manifest_path=manifest,
            workspace_path=workspace,
            output_dir=self.root / "partial-output",
            env={"GEMINI_API_KEY": "fake-boundary-key"},
            provider=_FailingAccountingProvider(),
            input_price_per_million="0.50",
            output_price_per_million="2.50",
        )

        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["completed_document_count"], 0)
        self.assertEqual(report["documents"][0]["workflow_status"], "partial")
        self.assertTrue(report["documents"][0]["warnings"]["pipeline_continued"])
        self.assertTrue(report["documents"][0]["warnings"]["draft_retained"])
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("PRIVATE provider detail", serialized)


if __name__ == "__main__":
    unittest.main()
