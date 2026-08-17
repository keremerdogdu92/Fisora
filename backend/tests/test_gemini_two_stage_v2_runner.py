from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_ai_artifacts import ArtifactKind
from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import LocalDocumentAiArtifactRepository
from app.workflows.gemini_invoice_pipeline import (
    GeminiInvoicePipelineRequest,
    run_gemini_invoice_pipeline_v2,
)
from scripts.run_gemini_two_stage_v2 import (
    _is_native_pdf,
    build_aggregate_report,
    build_safe_document_report,
    probe_prerequisites,
    run_controlled_proof,
)


PRICE_PROFILE = {
    "model_alias": "gemini-test",
    "resolved_model": "gemini-test-resolved",
    "input_price_per_million": "0.50",
    "output_price_per_million": "2.50",
    "currency": "USD",
}


@dataclass(frozen=True)
class _Attempt:
    request_body: bytes
    response_body: bytes
    status: str = "successful"
    provider: str = "gemini"
    model_alias: str = "gemini-test"
    resolved_model: str = "gemini-test-resolved"
    http_status: int = 200
    started_at: datetime = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    finished_at: datetime = datetime(2026, 8, 11, 9, 0, tzinfo=UTC) + timedelta(
        milliseconds=7
    )
    elapsed_ms: int = 7
    token_usage: dict[str, int] | None = None
    error_metadata: dict[str, object] | None = None


class _Result(dict):
    def __init__(self, payload: dict[str, object], *, attempt: _Attempt) -> None:
        super().__init__(payload)
        self.attempt = attempt


def _canonical_payload(*, warning: str = "") -> dict[str, object]:
    return {
        "header": {
            "invoice_no": "PRIVATE-INVOICE-NO",
            "issue_date": "2026-08-11",
            "currency_code": "TRY",
            "document_direction": "purchase",
            "evidence": ["pdf:header"],
        },
        "supplier_party": {
            "title": "Private Supplier",
            "tax_id": "1234567890",
            "evidence": ["pdf:supplier"],
        },
        "customer_party": {
            "title": "Private Customer",
            "tax_id": "1111111111",
            "evidence": ["pdf:customer"],
        },
        "line_items": [
            {
                "canonical_line_id": "l1",
                "source_position": "line:1",
                "description": "Private service description",
                "observed_taxable_amount": "100.00",
                "observed_vat_rate": "20",
                "observed_tax_amount": "20.00",
                "evidence": ["pdf:line:1"],
            }
        ],
        "observed_vat_summary": [
            {
                "vat_group_id": "v20",
                "observed_rate": "20",
                "observed_taxable_amount": "100.00",
                "observed_tax_amount": "20.00",
                "contributing_line_ids": ["l1"],
                "evidence": ["pdf:vat"],
            }
        ],
        "observed_tax_components": [
            {
                "component_type": "withholding",
                "source_label": "Withholding",
                "source_code": "WH",
                "taxable_amount": "100.00",
                "tax_amount": "10.00",
                "source_position": "tax:1",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["pdf:tax"],
            }
        ],
        "observed_monetary_components": [
            {
                "source_label": "Discount",
                "source_amount": "5.00",
                "source_position": "money:1",
                "included_in_line_net": "yes",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["pdf:discount"],
            }
        ],
        "observed_totals": {
            "observed_goods_services_total": "100.00",
            "observed_allowance_total": "0.00",
            "observed_vat_total": "20.00",
            "observed_special_tax_total": "10.00",
            "observed_tax_inclusive_total": "130.00",
            "observed_payable_total": "110.00",
            "evidence": ["pdf:totals"],
        },
        "extraction_notes": [warning] if warning else [],
    }


def _workspace(*, active: bool = True, revision: str = "chart-r1") -> dict[str, object]:
    return {
        "tenant_id": "tenant-real-1",
        "taxpayer_id": "taxpayer-real-1",
        "chart_accounts": {
            "revision": revision,
            "accounts": [
                {"code": "320.01", "name": "Supplier", "tax_id": "1234567890", "roles": ["counterparty"], "active": active},
                {"code": "770.01", "name": "Expense", "roles": ["line_expense"], "active": active},
                {"code": "191.20", "name": "VAT", "roles": ["vat"], "active": active},
                {"code": "360.01", "name": "Withholding", "roles": ["special_tax"], "active": active},
                {"code": "649.01", "name": "Discount", "roles": ["special_tax"], "active": active},
            ],
        },
    }


class _PaidBoundaryProvider:
    provider_name = "gemini"
    model = "gemini-test"

    def __init__(
        self,
        *,
        warning: str = "",
        extraction_usage: dict[str, int] | None = None,
        accounting_usage: dict[str, int] | None = None,
    ) -> None:
        self.warning = warning
        self.extraction_usage = extraction_usage or {
            "prompt_tokens": 10,
            "candidate_tokens": 5,
            "total_tokens": 15,
        }
        self.accounting_usage = accounting_usage or {
            "prompt_tokens": 20,
            "candidate_tokens": 8,
            "total_tokens": 28,
        }
        self.extraction_calls = 0
        self.accounting_calls = 0

    @property
    def call_count(self) -> int:
        return self.extraction_calls + self.accounting_calls

    def extract_invoice_canonical(self, request):
        self.extraction_calls += 1
        payload = _canonical_payload(warning=self.warning)
        return _Result(
            payload,
            attempt=_Attempt(
                request_body=b'{"raw":"TOP-SECRET-RAW-REQUEST"}',
                response_body=b'{"raw":"TOP-SECRET-RAW-RESPONSE"}',
                token_usage=self.extraction_usage,
                error_metadata={},
            ),
        )

    def classify_product(self, request):
        self.accounting_calls += 1
        candidates = {item.candidate_id: item for item in request.sent_candidates}
        picks = {
            "counterparty": "320.01",
            "line": "770.01",
            "vat": "191.20",
            "tax": "360.01",
            "monetary": "649.01",
        }
        decisions: list[dict[str, object]] = []
        for decision_ref in request.required_decision_refs:
            if decision_ref == "counterparty":
                continue
            decision_role = decision_ref.split(":", 1)[0]
            candidate_id = picks[decision_role]
            if candidate_id not in candidates:
                raise AssertionError(f"candidate not sent: {candidate_id}")
            decisions.append(
                {
                    "decision_ref": decision_ref,
                    "action": "select_existing",
                    "selected_candidate_id": candidate_id,
                    "selected_treatment": (
                        "payable_withholding"
                        if decision_role == "tax"
                        else "reduce_payable"
                        if decision_role == "monetary"
                        else ""
                    ),
                    "reason": "test",
                }
            )
        payload = {
            "counterparty": {
                "action": "select_existing",
                "selected_candidate_id": "320.01",
                "reason": "exact tax id",
                "proposal": None,
            },
            "decisions": decisions,
            "candidate_sufficiency": {
                "sufficient": True,
                "request_more_candidates": False,
                "search_terms": [],
                "reason": "enough",
                "provisional": False,
            },
        }
        return _Result(
            payload,
            attempt=_Attempt(
                request_body=b'{"raw":"TOP-SECRET-RAW-REQUEST"}',
                response_body=b'{"raw":"TOP-SECRET-RAW-RESPONSE"}',
                token_usage=self.accounting_usage,
                error_metadata={},
            ),
        )


class GeminiTwoStageV2RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.pdf = self.root / "private-invoice.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\n%runner-v2\n")
        self.workspace_path = self.root / "workspace.json"
        self.manifest_path = self.root / "manifest.json"
        self.output_dir = self.root / "runs"
        self.write_inputs()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_inputs(
        self,
        *,
        workspace: dict[str, object] | None = None,
        tenant_id: str = "tenant-real-1",
        taxpayer_id: str = "taxpayer-real-1",
        price_profile: dict[str, str] | None = PRICE_PROFILE,
    ) -> None:
        self.workspace_path.write_text(
            json.dumps(workspace or _workspace()), encoding="utf-8"
        )
        manifest = {
            "tenant_id": tenant_id,
            "taxpayer_id": taxpayer_id,
            "documents": [
                {"document_id": "PRIVATE-DOCUMENT-ID", "pdf_path": str(self.pdf)}
            ],
        }
        if price_profile is not None:
            manifest["price_profile"] = price_profile
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def run_pipeline_result(self, *, warning: str = ""):
        run_dir = self.root / f"direct-{warning or 'clean'}"
        repository = LocalDocumentAiArtifactRepository(
            manifest_path=run_dir / "artifacts.json",
            storage=LocalDocumentStorage(run_dir / "bodies"),
        )
        source_bytes = self.pdf.read_bytes()
        result = run_gemini_invoice_pipeline_v2(
            GeminiInvoicePipelineRequest(
                tenant_id="tenant-real-1",
                taxpayer_id="taxpayer-real-1",
                document_id="PRIVATE-DOCUMENT-ID",
                source_file_id="source-1",
                source_file_sha256=hashlib.sha256(source_bytes).hexdigest(),
                source_bytes=source_bytes,
                workspace=_workspace(),
                chart_revision="chart-r1",
            ),
            extraction_provider=_PaidBoundaryProvider(warning=warning),
            accounting_provider=_PaidBoundaryProvider(warning=warning),
            artifact_repository=repository,
        )
        current_ids = frozenset(item.artifact_id for item in result.artifacts)
        return result, repository, current_ids

    def test_preflight_blocks_missing_live_requirements_without_paid_call(self) -> None:
        self.write_inputs(workspace=_workspace(active=False, revision=""), tenant_id="", taxpayer_id="")
        provider = _PaidBoundaryProvider()

        preflight = probe_prerequisites(
            manifest_path=self.manifest_path,
            workspace_path=self.workspace_path,
            env={},
        )
        report = run_controlled_proof(
            manifest_path=self.manifest_path,
            workspace_path=self.workspace_path,
            output_dir=self.output_dir,
            env={},
            provider=provider,
        )

        self.assertEqual(preflight["status"], "BLOCKED")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(provider.call_count, 0)
        self.assertTrue(
            {"gemini_api_key", "tenant_identity", "taxpayer_identity", "active_coded_tenant_chart", "chart_revision"}
            .issubset(set(report["missing_prerequisites"]))
        )

    def test_cli_bootstraps_backend_imports_and_help(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BACKEND / "scripts" / "run_gemini_two_stage_v2.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())
        self.assertNotIn("Traceback", completed.stderr)

    def test_cli_unexpected_exception_returns_safe_exit_two_without_traceback(self) -> None:
        blocked_output = self.root / "output-is-a-file"
        blocked_output.write_text("not a directory", encoding="utf-8")
        secret = "TOP-SECRET-CLI-KEY"
        completed = subprocess.run(
            [
                sys.executable,
                str(BACKEND / "scripts" / "run_gemini_two_stage_v2.py"),
                "--manifest",
                str(self.manifest_path),
                "--workspace",
                str(self.workspace_path),
                "--output-dir",
                str(blocked_output),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "GEMINI_API_KEY": secret,
                "FISORA_GEMINI_MAX_INLINE_PDF_BYTES": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("Traceback", completed.stdout)
        self.assertNotIn(secret, completed.stdout)
        self.assertNotIn(str(self.root), completed.stdout)
        self.assertIn(json.loads(completed.stdout)["status"], {"BLOCKED", "NOT_OK"})

    def test_missing_or_invalid_model_price_profile_blocks_before_paid_call(self) -> None:
        cases = (None, {**PRICE_PROFILE, "input_price_per_million": "-1"})
        for profile in cases:
            with self.subTest(profile=profile):
                self.write_inputs(price_profile=profile)
                provider = _PaidBoundaryProvider()

                report = run_controlled_proof(
                    manifest_path=self.manifest_path,
                    workspace_path=self.workspace_path,
                    output_dir=self.output_dir,
                    env={"GEMINI_API_KEY": "configured"},
                    provider=provider,
                )

                self.assertEqual(report["status"], "BLOCKED")
                self.assertIn("model_price_profile", report["missing_prerequisites"])
                self.assertEqual(provider.call_count, 0)

    def test_price_profile_binds_receipt_models_and_mixed_token_keys(self) -> None:
        provider = _PaidBoundaryProvider(
            extraction_usage={"input_tokens": 10, "output_tokens": 5},
            accounting_usage={
                "prompt_tokens": 20,
                "candidate_tokens": 8,
                "total_tokens": 28,
            },
        )
        report = run_controlled_proof(
            manifest_path=self.manifest_path,
            workspace_path=self.workspace_path,
            output_dir=self.output_dir,
            env={"GEMINI_API_KEY": "configured"},
            provider=provider,
        )

        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["provider_totals"]["total_tokens"], 43)
        self.assertEqual(
            report["provider_totals"]["model_profiles"],
            [
                {
                    "model_alias": "gemini-test",
                    "resolved_model": "gemini-test-resolved",
                    "call_count": 2,
                }
            ],
        )

        self.write_inputs(
            price_profile={**PRICE_PROFILE, "resolved_model": "different-model"}
        )
        mismatched = run_controlled_proof(
            manifest_path=self.manifest_path,
            workspace_path=self.workspace_path,
            output_dir=self.output_dir,
            env={"GEMINI_API_KEY": "configured"},
            provider=_PaidBoundaryProvider(),
        )
        self.assertEqual(mismatched["status"], "NOT_OK")

    def test_preflight_accepts_existing_five_document_manifest_shape(self) -> None:
        self.manifest_path.write_text(
            json.dumps(
                {
                    "tenant_id": "tenant-real-1",
                    "taxpayer_id": "taxpayer-real-1",
                    "price_profile": PRICE_PROFILE,
                    "cases": [
                        {
                            "invoice_id": f"private-{index}",
                            "source_pdf": str(self.pdf),
                        }
                        for index in range(5)
                    ],
                }
            ),
            encoding="utf-8",
        )

        preflight = probe_prerequisites(
            manifest_path=self.manifest_path,
            workspace_path=self.workspace_path,
            env={"GEMINI_API_KEY": "configured"},
        )

        self.assertEqual(preflight["status"], "READY")
        self.assertEqual(preflight["document_count"], 5)
        self.assertEqual(preflight["valid_document_count"], 5)

    def test_preflight_rejects_malformed_or_unadmitted_documents_and_scope_mismatch(self) -> None:
        valid_document = {
            "document_id": "private-valid",
            "pdf_path": str(self.pdf),
        }
        malformed_manifests = (
            {
                "documents": [valid_document, "malformed-entry"],
                "expected_document_count": 2,
            },
            {"documents": [valid_document], "expected_document_count": 2},
            {
                "documents": [valid_document, dict(valid_document)],
                "expected_document_count": 2,
            },
        )
        for changes in malformed_manifests:
            with self.subTest(changes=changes):
                payload = {
                    "tenant_id": "tenant-real-1",
                    "taxpayer_id": "taxpayer-real-1",
                    "price_profile": PRICE_PROFILE,
                    **changes,
                }
                self.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
                preflight = probe_prerequisites(
                    manifest_path=self.manifest_path,
                    workspace_path=self.workspace_path,
                    env={"GEMINI_API_KEY": "configured"},
                )
                self.assertEqual(preflight["status"], "BLOCKED")
                self.assertIn("manifest_documents", preflight["missing_prerequisites"])

        invalid_files = (
            (self.root / "invoice.txt", b"%PDF-1.7\n"),
            (self.root / "invalid.pdf", b"not-a-pdf"),
        )
        for path, content in invalid_files:
            with self.subTest(path=path.name):
                path.write_bytes(content)
                payload = {
                    "tenant_id": "tenant-real-1",
                    "taxpayer_id": "taxpayer-real-1",
                    "price_profile": PRICE_PROFILE,
                    "documents": [{"document_id": "private", "pdf_path": str(path)}],
                }
                self.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
                preflight = probe_prerequisites(
                    manifest_path=self.manifest_path,
                    workspace_path=self.workspace_path,
                    env={"GEMINI_API_KEY": "configured"},
                )
                self.assertEqual(preflight["status"], "BLOCKED")
                self.assertIn("native_pdf_documents", preflight["missing_prerequisites"])

        self.write_inputs()
        mismatched_workspace = _workspace()
        mismatched_workspace["tenant_id"] = "different-tenant"
        self.workspace_path.write_text(json.dumps(mismatched_workspace), encoding="utf-8")
        mismatch = probe_prerequisites(
            manifest_path=self.manifest_path,
            workspace_path=self.workspace_path,
            env={"GEMINI_API_KEY": "configured"},
        )
        self.assertEqual(mismatch["status"], "BLOCKED")
        self.assertIn("scope_identity_mismatch", mismatch["missing_prerequisites"])

    def test_monetary_loss_or_duplication_fails_fact_integrity(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        assert result.draft is not None
        monetary_line = next(line for line in result.draft.lines if line.fact_ref.startswith("monetary:"))
        cases = (
            replace(result, draft=replace(result.draft, lines=tuple(line for line in result.draft.lines if line is not monetary_line))),
            replace(result, draft=replace(result.draft, lines=(*result.draft.lines, monetary_line))),
        )

        for tampered in cases:
            with self.subTest(line_count=len(tampered.draft.lines)):
                report = build_safe_document_report(
                    result=tampered,
                    artifact_repository=repository,
                    current_run_artifact_ids=current_ids,
                )
                self.assertFalse(report["integrity"]["monetary"]["complete"])
                self.assertFalse(report["integrity"]["all_facts_complete"])
                self.assertEqual(build_aggregate_report([report])["status"], "NOT_OK")

    def test_duplicate_projection_refs_unexpected_draft_refs_and_amount_drift_fail_exact_once(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        assert result.projection is not None
        assert result.draft is not None
        monetary = tuple(result.projection["monetary_components"])
        duplicate_projection = {
            **result.projection,
            "monetary_components": [*monetary, monetary[0]],
        }
        first = result.draft.lines[0]
        unexpected_line = replace(first, fact_ref="unexpected:private")
        amount_drift = replace(first, amount=first.amount + Decimal("1.00"))
        cases = (
            replace(result, projection=duplicate_projection),
            replace(
                result,
                draft=replace(result.draft, lines=(*result.draft.lines, unexpected_line)),
            ),
            replace(
                result,
                draft=replace(result.draft, lines=(amount_drift, *result.draft.lines[1:])),
            ),
        )

        for changed in cases:
            report = build_safe_document_report(
                result=changed,
                artifact_repository=repository,
                current_run_artifact_ids=current_ids,
            )
            self.assertFalse(report["integrity"]["all_facts_complete"])
            self.assertEqual(build_aggregate_report([report])["status"], "NOT_OK")

    def test_blank_or_non_numeric_totals_fail_integrity(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        assert result.projection is not None
        for field, value in (
            ("payable_total", ""),
            ("payable_total", "not-money"),
            ("allowance_total", ""),
        ):
            with self.subTest(field=field, value=value):
                totals = {**result.projection["totals"], field: value}
                report = build_safe_document_report(
                    result=replace(result, projection={**result.projection, "totals": totals}),
                    artifact_repository=repository,
                    current_run_artifact_ids=current_ids,
                )
                self.assertFalse(report["integrity"]["totals"]["complete"])
                self.assertFalse(report["integrity"]["all_facts_complete"])

    def test_balanced_blank_fact_refs_are_counted_as_unexpected(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        assert result.draft is not None
        template = result.draft.lines[0]
        blank_debit = replace(
            template,
            fact_ref="",
            raw_source_amount="1.00",
            amount=Decimal("1.00"),
            side="debit",
            debit=Decimal("1.00"),
            credit=Decimal("0.00"),
        )
        blank_credit = replace(
            template,
            fact_ref="   ",
            raw_source_amount="1.00",
            amount=Decimal("1.00"),
            side="credit",
            debit=Decimal("0.00"),
            credit=Decimal("1.00"),
        )
        changed = replace(
            result,
            draft=replace(
                result.draft,
                lines=(*result.draft.lines, blank_debit, blank_credit),
                total_debit=result.draft.total_debit + Decimal("1.00"),
                total_credit=result.draft.total_credit + Decimal("1.00"),
                is_balanced=True,
            ),
        )

        report = build_safe_document_report(
            result=changed,
            artifact_repository=repository,
            current_run_artifact_ids=current_ids,
        )

        self.assertEqual(report["integrity"]["unexpected_draft_refs"]["count"], 2)
        self.assertFalse(report["integrity"]["all_facts_complete"])
        self.assertEqual(build_aggregate_report([report])["status"], "NOT_OK")

    def test_native_pdf_probe_reads_only_first_five_bytes(self) -> None:
        read_sizes: list[int] = []
        full_read_used = False

        class ObservedReader:
            def __init__(self, path: Path) -> None:
                self.handle = path.open("rb")

            def __enter__(self):
                self.handle.__enter__()
                return self

            def __exit__(self, *args):
                return self.handle.__exit__(*args)

            def read(self, size: int = -1) -> bytes:
                read_sizes.append(size)
                return self.handle.read(size)

        class ObservedPath:
            suffix = self.pdf.suffix

            def is_file(inner_self) -> bool:
                return self.pdf.is_file()

            def stat(inner_self):
                return self.pdf.stat()

            def open(inner_self, mode: str):
                self.assertEqual(mode, "rb")
                return ObservedReader(self.pdf)

            def read_bytes(inner_self) -> bytes:
                nonlocal full_read_used
                full_read_used = True
                return self.pdf.read_bytes()

        self.assertTrue(_is_native_pdf(ObservedPath()))
        self.assertFalse(full_read_used)
        self.assertEqual(read_sizes, [5])

    def test_partial_unbalanced_and_unresolved_each_prevent_aggregate_ok(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        assert result.draft is not None
        first = result.draft.lines[0]
        unbalanced_line = replace(first, debit=first.debit + Decimal("1.00"))
        unbalanced_draft = replace(
            result.draft,
            lines=(unbalanced_line, *result.draft.lines[1:]),
            total_debit=result.draft.total_debit + Decimal("1.00"),
            is_balanced=False,
        )
        unresolved_draft = replace(
            result.draft,
            lines=(replace(first, resolution="unresolved"), *result.draft.lines[1:]),
        )
        cases = (
            replace(result, status="partial"),
            replace(result, draft=unbalanced_draft),
            replace(result, draft=unresolved_draft),
        )

        for changed in cases:
            report = build_safe_document_report(
                result=changed,
                artifact_repository=repository,
                current_run_artifact_ids=current_ids,
            )
            self.assertEqual(build_aggregate_report([report])["status"], "NOT_OK")

    def test_stale_artifact_id_prevents_current_run_lineage_and_ok(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        stale_ids = frozenset(value for value in current_ids if value != result.proposal_artifact_id)

        report = build_safe_document_report(
            result=result,
            artifact_repository=repository,
            current_run_artifact_ids=stale_ids,
        )

        self.assertFalse(report["lineage"]["current_run"])
        self.assertEqual(build_aggregate_report([report])["status"], "NOT_OK")

    def test_fake_repository_artifact_or_broken_typed_receipt_edge_fails_lineage(self) -> None:
        result, repository, current_ids = self.run_pipeline_result()
        fake = replace(result.artifacts[0], artifact_id="fake-current-run-artifact")
        fake_result = replace(result, artifacts=(*result.artifacts, fake))
        fake_report = build_safe_document_report(
            result=fake_result,
            artifact_repository=repository,
            current_run_artifact_ids=(*current_ids, fake.artifact_id),
        )
        self.assertFalse(fake_report["lineage"]["current_run"])

        proposal = next(
            item for item in result.artifacts if item.artifact_id == result.proposal_artifact_id
        )
        broken = replace(proposal, provider_receipt_artifact_id=None)
        broken_result = replace(
            result,
            artifacts=tuple(broken if item is proposal else item for item in result.artifacts),
        )
        broken_report = build_safe_document_report(
            result=broken_result,
            artifact_repository=repository,
            current_run_artifact_ids=current_ids,
        )
        self.assertFalse(broken_report["lineage"]["current_run"])

    def test_repeated_runs_use_unique_repositories_and_isolated_counts(self) -> None:
        provider = _PaidBoundaryProvider()
        arguments = {
            "manifest_path": self.manifest_path,
            "workspace_path": self.workspace_path,
            "output_dir": self.output_dir,
            "env": {"GEMINI_API_KEY": "TOP-SECRET-API-KEY"},
            "provider": provider,
        }

        first = run_controlled_proof(**arguments)
        second = run_controlled_proof(**arguments)

        self.assertEqual(first["status"], "OK")
        self.assertEqual(second["status"], "OK")
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["artifact_count"], second["artifact_count"])
        self.assertEqual(first["provider_totals"], second["provider_totals"])
        self.assertEqual(len(tuple(self.output_dir.glob("run-*"))), 2)
        rendered = json.dumps((first, second), ensure_ascii=False)
        for secret in (
            "TOP-SECRET-API-KEY",
            "TOP-SECRET-RAW-REQUEST",
            "TOP-SECRET-RAW-RESPONSE",
            "PRIVATE-DOCUMENT-ID",
            "PRIVATE-INVOICE-NO",
            "Private Supplier",
        ):
            self.assertNotIn(secret, rendered)

    def test_warning_continuation_requires_later_artifacts_and_draft(self) -> None:
        result, repository, current_ids = self.run_pipeline_result(warning="canonical_warning")
        complete_report = build_safe_document_report(
            result=result,
            artifact_repository=repository,
            current_run_artifact_ids=current_ids,
        )
        stopped_report = build_safe_document_report(
            result=replace(result, draft=None),
            artifact_repository=repository,
            current_run_artifact_ids=current_ids,
        )

        self.assertGreater(complete_report["warnings"]["count"], 0)
        self.assertTrue(complete_report["warnings"]["pipeline_continued"])
        self.assertTrue(complete_report["warnings"]["later_artifacts_and_draft"])
        self.assertFalse(stopped_report["warnings"]["pipeline_continued"])

        late_report = build_safe_document_report(
            result=replace(result, warnings=(*result.warnings, "late_unproven_warning")),
            artifact_repository=repository,
            current_run_artifact_ids=current_ids,
        )
        self.assertFalse(late_report["warnings"]["pipeline_continued"])
        self.assertEqual(late_report["warnings"]["unproven_count"], 1)
        self.assertTrue(late_report["warnings"]["stage_progression"])


if __name__ == "__main__":
    unittest.main()
