from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.chart_accounts import (
    extract_counterparty_candidates,
    normalize_account_code,
    parse_chart_accounts,
    validate_vat_accounts,
)
from app.domain.ai_benchmark import AiBenchmarkCase, run_ai_batch_benchmark
from app.domain.ai_classification import AiClassificationContext, AiClassificationPolicy, AiClassificationRequest, StaticFirstClassifier
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event, summarize_ai_usage
from app.domain.openai_provider import GroqAccountingProvider, OpenAiAccountingProvider
from app.domain.business_relevance import (
    ClientProfile,
    assess_business_relevance,
    check_client_onboarding,
    decide_export_status,
)
from app.domain.chart_accounts import ChartAccount
from app.domain.counterparty_matching import match_counterparty
from app.domain.export_adapters import get_export_adapter, write_export_file
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.exporters import export_universal_journal_csv, export_zirve_trial_csv
from app.domain.invoice_lines import extract_invoice_lines_from_text
from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_operations import (
    ReviewTaskDraft,
    run_invoice_operations,
    vat_rate_decimal,
)
from app.domain.learning_rules import apply_learning_rules, rule_from_learning_event
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.journal_entries import (
    build_bank_payment_entry,
    build_mixed_vat_purchase_entry,
    build_purchase_entry,
    build_sales_entry,
    money,
)
from app.domain.pdf_invoices import ParsedInvoice, build_route, extract_vat_rates, parse_amount
from app.domain.production_readiness import production_readiness_payload
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.domain.statement_ai_suggestions import StatementAiSuggestionPolicy, suggest_statement_lines
from app.domain.statement_lines import StatementLine
from app.domain.workspace_exports import build_workspace_export_package, export_candidates_from_workspace


class FakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[AiClassificationRequest] = []

    def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class FakeStatementSuggestionProvider:
    provider_name = "fake_statement_llm"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def suggest_statement_line(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return self.responses.pop(0)


class Phase0DomainTests(unittest.TestCase):
    def test_ai_usage_summary_tracks_ten_dollar_cap(self) -> None:
        events = [
            ai_usage_payload(
                build_ai_usage_event(
                    client_id="client-1",
                    provider="openai",
                    operation="worker_ai_assisted_draft",
                    input_chars=420,
                    ai_used=True,
                )
            )
        ]

        summary = summarize_ai_usage(events, monthly_cap_usd=Decimal("10"))

        self.assertEqual(summary["monthly_cap_usd"], "10.00")
        self.assertEqual(summary["estimated_total_cost_usd"], "0.000420")
        self.assertEqual(summary["remaining_cap_usd"], "9.999580")
        self.assertFalse(summary["cap_exceeded"])

    def test_ai_usage_summary_tracks_groq_free_tier_as_zero_cost(self) -> None:
        events = [
            ai_usage_payload(
                build_ai_usage_event(
                    client_id="client-1",
                    provider="groq",
                    operation="worker_ai_assisted_draft",
                    input_chars=1200,
                    ai_used=True,
                )
            )
        ]

        summary = summarize_ai_usage(events, monthly_cap_usd=Decimal("0.01"))

        self.assertEqual(summary["estimated_total_cost_usd"], "0.000000")
        self.assertEqual(summary["remaining_cap_usd"], "0.010000")
        self.assertFalse(summary["cap_exceeded"])

    def test_production_readiness_requires_openai_key_when_openai_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "openai",
                    "FISORA_AI_MODEL": "gpt-5.4-mini",
                },
            )

        self.assertFalse(payload["checks"]["ai_provider_configured"])
        self.assertIn("ai_provider_configured", payload["blocking"])
        self.assertIn("ai_openai_key_missing", payload["warnings"])

    def test_production_readiness_accepts_groq_key_when_groq_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "groq",
                    "FISORA_AI_MODEL": "openai/gpt-oss-20b",
                    "GROQ_API_KEY": "gsk-test",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_provider"], "groq")
        self.assertTrue(payload["ai_groq_key_present"])
        self.assertNotIn("ai_groq_key_missing", payload["warnings"])

    def test_production_readiness_uses_groq_default_model_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_model"], "openai/gpt-oss-20b")
        self.assertNotIn("ai_model_missing", payload["warnings"])

    def test_chart_account_import_marks_detail_accounts(self) -> None:
        accounts = parse_chart_accounts(ROOT / "samples" / "chart_accounts" / "chart_accounts_sample_a.csv")
        account_by_code = {account.normalized_account_code: account for account in accounts}

        self.assertFalse(account_by_code["120"].is_detail_account)
        self.assertTrue(account_by_code["120.01.001"].is_detail_account)
        self.assertTrue(account_by_code["320.01.001"].is_detail_account)

    def test_three_chart_account_samples_are_parseable(self) -> None:
        sample_dir = ROOT / "samples" / "chart_accounts"
        for sample_name in (
            "chart_accounts_sample_a.csv",
            "chart_accounts_sample_b.csv",
            "chart_accounts_sample_c.csv",
        ):
            with self.subTest(sample=sample_name):
                accounts = parse_chart_accounts(sample_dir / sample_name)
                counterparties = extract_counterparty_candidates(accounts)
                vat_status = validate_vat_accounts(accounts)

                self.assertGreaterEqual(len(accounts), 10)
                self.assertGreaterEqual(len(counterparties), 2)
                self.assertTrue(vat_status["has_purchase_vat_191"])
                self.assertTrue(vat_status["has_sales_vat_391"])

    def test_chart_account_import_extracts_counterparties_and_vat_status(self) -> None:
        accounts = parse_chart_accounts(ROOT / "samples" / "chart_accounts" / "chart_accounts_sample_a.csv")
        counterparties = extract_counterparty_candidates(accounts)
        vat_status = validate_vat_accounts(accounts)

        self.assertEqual({item.counterparty_type for item in counterparties}, {"customer", "supplier"})
        self.assertEqual(vat_status, {"has_purchase_vat_191": True, "has_sales_vat_391": True})

    def test_account_code_normalization(self) -> None:
        self.assertEqual(normalize_account_code(" 120.01,001 "), "120.01.001")
        self.assertEqual(normalize_account_code("100 01 001"), "100.01.001")
        self.assertEqual(normalize_account_code("120-01-001"), "120.01.001")

    def test_purchase_sales_bank_entries_are_balanced(self) -> None:
        entries = [
            build_purchase_entry(
                entry_date="2026-05-01",
                total=money("1200.00"),
                vat_rate=Decimal("0.20"),
                expense_account="770.01",
            ),
            build_sales_entry(
                entry_date="2026-05-02",
                total=money("2400.00"),
                vat_rate=Decimal("0.20"),
                revenue_account="600.01",
            ),
            build_bank_payment_entry(
                entry_date="2026-05-03",
                amount=money("500.00"),
                bank_account="102.01",
                counterparty_account="320.01.001",
            ),
        ]

        self.assertTrue(all(entry.is_balanced for entry in entries))

    def test_mixed_vat_purchase_entry_is_balanced_and_flagged(self) -> None:
        entry = build_mixed_vat_purchase_entry(
            entry_date="2026-05-04",
            items=(("770.01", money("108.00"), Decimal("0.08")), ("770.02", money("120.00"), Decimal("0.20"))),
        )

        self.assertTrue(entry.is_balanced)
        self.assertIn("mixed_vat_manual_review", entry.risk_flags)

    def test_universal_journal_export(self) -> None:
        entry = build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="AF-0001",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = export_universal_journal_csv([entry], Path(temp_dir) / "journal.csv")
            text = output.read_text(encoding="utf-8-sig")

        self.assertIn("entry_no,entry_type,entry_date", text)
        self.assertIn("770.01", text)
        self.assertIn("320.01.001", text)

    def test_invoice_edge_case_summary_flags_manual_review(self) -> None:
        text = """
        E-FATURA
        Fatura No: ABC2026000000001
        ETTN: 123e4567-e89b-12d3-a456-426614174000
        Tevkifat
        KDV %8
        KDV %20
        """

        summary = summarize_invoice_edge_cases("Kolay Soft 1.pdf", text, extracted_char_count=len(text))

        self.assertEqual(summary.provider_hint, "Kolay Soft")
        self.assertEqual(summary.invoice_no, "ABC2026000000001")
        self.assertEqual(summary.ettn, "123e4567-e89b-12d3-a456-426614174000")
        self.assertIn("withholding_manual_review", summary.risk_flags)
        self.assertIn("mixed_vat_manual_review", summary.risk_flags)
        self.assertEqual(summary.suggested_expected_behavior, "review_queue")

    def test_pdf_invoice_helpers_parse_amounts_and_vat_rates(self) -> None:
        text = "Mal Hizmet Toplam Tutarı 1.234,56 TL Hesaplanan KDV(%20) 246,91 TL KDV %8"

        self.assertEqual(str(parse_amount("1.234,56")), "1234.56")
        self.assertEqual(extract_vat_rates(text), ("8", "20"))

    def test_pdf_invoice_route_returns_notes_tuple_for_journal_candidate(self) -> None:
        route, notes = build_route(
            (),
            {
                "invoice_no": "ABC2026000000001",
                "issue_date": "01.05.2026",
                "payable_total": "1200.00",
            },
        )

        self.assertEqual(route, "journal_candidate")
        self.assertEqual(notes, ())

    def test_invoice_operation_run_splits_journals_and_review_tasks(self) -> None:
        journal_invoice = ParsedInvoice(
            file_name="normal.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
        )
        review_invoice = ParsedInvoice(
            file_name="mixed.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="DEF2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("10", "20"),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
        )

        run = run_invoice_operations([journal_invoice, review_invoice])

        self.assertEqual(len(run.journal_entries), 1)
        self.assertEqual(len(run.review_tasks), 1)
        self.assertTrue(run.journal_entries[0].is_balanced)
        self.assertIsInstance(run.review_tasks[0], ReviewTaskDraft)
        self.assertEqual(vat_rate_decimal(journal_invoice), Decimal("0.20"))

    def test_matching_simulation_creates_review_draft_for_risky_positive_invoice(self) -> None:
        invoice = ParsedInvoice(
            file_name="mixed.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="DEF2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("10", "20"),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_invoice(invoice, selection)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_quality, "gross_balanced_needs_vat_split")
        self.assertTrue(result.is_balanced)
        self.assertEqual(len(result.draft_lines), 2)

    def test_matching_simulation_requires_client_profile_for_export(self) -> None:
        invoice = ParsedInvoice(
            file_name="rexton.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_invoice(invoice, selection)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.export_status, "review_required")
        self.assertIn("onboarding_missing_client_profile", result.review_reason_codes)

    def test_matching_simulation_marks_incomplete_client_profile_for_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="rexton.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=False,
        )

        result = simulate_invoice(invoice, selection, profile)

        self.assertEqual(result.export_status, "review_required")
        self.assertIn("onboarding_missing_chart_accounts", result.review_reason_codes)

    def test_matching_simulation_keeps_zero_amount_invoice_in_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="zero.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="",
            invoice_type="ISTISNA",
            invoice_no="IST2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("0",),
            goods_services_total="0.00",
            vat_total="0.00",
            special_tax_total="",
            tax_inclusive_total="0.00",
            payable_total="0.00",
            risk_flags=("exemption_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_invoice(invoice, selection)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_quality, "no_positive_amount")
        self.assertEqual(result.draft_lines, ())

    def test_client_onboarding_requires_profile_and_chart_accounts(self) -> None:
        profile = ClientProfile(
            client_id="",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=False,
        )

        check = check_client_onboarding(profile)

        self.assertFalse(check.is_ready)
        self.assertIn("client_id", check.missing_fields)
        self.assertIn("chart_accounts", check.missing_fields)

    def test_brand_model_line_flags_personal_care_for_hearing_center(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Urban Care sac bakim seti", profile)
        status = decide_export_status(is_balanced=True, risk_flags=(), relevance=relevance)

        self.assertEqual(relevance.classification.category, "kisisel_bakim_kozmetik")
        self.assertEqual(relevance.status, "is_alani_disi")
        self.assertEqual(status, "review_required")

    def test_brand_model_line_allows_hearing_device_for_hearing_center(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Rexton RLi 20", profile)
        status = decide_export_status(is_balanced=True, risk_flags=(), relevance=relevance)

        self.assertEqual(relevance.classification.category, "isitme_cihazi")
        self.assertEqual(relevance.status, "uygun")
        self.assertEqual(status, "export_ready")

    def test_static_first_classifier_skips_ai_for_high_confidence_static_match(self) -> None:
        provider = FakeProductProvider(
            {"category": "bilinmeyen", "confidence": 40, "reason": "fallback", "evidence": []}
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=70),
        )

        result = classifier.classify("Rexton RLi 20", supplier_hint="Rexton Medikal")

        self.assertFalse(result.ai_used)
        self.assertEqual(result.classification.category, "isitme_cihazi")
        self.assertEqual(result.skipped_reason, "static_high_confidence")
        self.assertEqual(provider.requests, [])

    def test_static_first_classifier_calls_provider_for_unknown_line_with_schema(self) -> None:
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 84,
                "reason": "Model odyoloji cihaz ailesine benziyor.",
                "evidence": ["ai:model_family"],
                "suggested_account_code": "770.01",
                "suggested_counterparty_code": "320.01.015",
                "risk_flags": ["accountant_review_required"],
                "account_reason": "Hesap plani adaylari icinden medikal gider hesabi secildi.",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, max_input_chars=24),
        )

        result = classifier.classify(
            "ZX Sonic Pro 9 receiver unit",
            supplier_hint="Medikal Tedarik",
            context=AiClassificationContext(
                client_activity="Isitme cihazi satis ve servis",
                account_candidates=("770.01", "760.01"),
                counterparty_candidates=("320.01.015",),
            ),
        )

        self.assertTrue(result.ai_used)
        self.assertEqual(result.provider, "fake_llm")
        self.assertEqual(result.classification.category, "isitme_cihazi")
        self.assertEqual(result.suggested_account_code, "770.01")
        self.assertEqual(result.suggested_counterparty_code, "320.01.015")
        self.assertEqual(result.risk_flags, ("accountant_review_required",))
        self.assertIn("medikal gider", result.account_reason)
        self.assertIn("ai_schema_validated", result.classification.evidence)
        self.assertEqual(provider.requests[0].to_schema_payload()["raw_line"], "ZX Sonic Pro 9 receiver")
        self.assertEqual(provider.requests[0].to_schema_payload()["account_candidates"], ["770.01", "760.01"])

    def test_static_first_classifier_rejects_invalid_provider_schema(self) -> None:
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider({"category": "serbest", "confidence": 110, "reason": ""}),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = classifier.classify("Bilinmeyen marka kalem")

        self.assertTrue(result.ai_used)
        self.assertEqual(result.classification.category, "bilinmeyen")
        self.assertIn("ai_invalid_schema", result.classification.evidence)

    def test_openai_accounting_provider_posts_limited_structured_payload(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"category":"isitme_cihazi","confidence":86,'
                                        '"reason":"Kalem isitme cihazi parcasina benziyor.",'
                                        '"evidence":["receiver"],"suggested_account_code":"770.01",'
                                        '"suggested_counterparty_code":"320.01.015",'
                                        '"risk_flags":["accountant_review_required"],'
                                        '"account_reason":"Mevcut hesap adaylari icinden secildi."}'
                                    ),
                                }
                            ]
                        }
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = OpenAiAccountingProvider(api_key="sk-test", model="gpt-5.4-mini", http_client=FakeClient())
        response = provider.classify_product(
            AiClassificationRequest(
                raw_line="ZX Sonic Pro 9 receiver unit",
                supplier_hint="Medikal Tedarik",
                allowed_categories=("isitme_cihazi", "bilinmeyen"),
                max_input_chars=80,
                context=AiClassificationContext(
                    client_activity="Isitme cihazi satis ve servis",
                    account_candidates=("770.01",),
                    counterparty_candidates=("320.01.015",),
                ),
            )
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(request_payload["model"], "gpt-5.4-mini")
        self.assertEqual(request_payload["text"]["format"]["type"], "json_schema")
        user_content = request_payload["input"][1]["content"]
        self.assertIn("ZX Sonic Pro 9 receiver unit", user_content)
        self.assertIn("770.01", user_content)
        self.assertNotIn("raw_pdf", user_content.lower())
        self.assertEqual(response["suggested_account_code"], "770.01")
        self.assertEqual(response["suggested_counterparty_code"], "320.01.015")

    def test_groq_accounting_provider_posts_openai_compatible_structured_payload(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "output_text": (
                        '{"category":"bilinmeyen","confidence":52,'
                        '"reason":"Kalem belirsiz, musavir kontrolu gerekli.",'
                        '"evidence":["belirsiz"],"suggested_account_code":"",'
                        '"suggested_counterparty_code":"",'
                        '"risk_flags":["accountant_review_required"],'
                        '"account_reason":"Hesap adayi yeterli degil."}'
                    )
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = GroqAccountingProvider(api_key="gsk-test", http_client=FakeClient())
        response = provider.classify_product(
            AiClassificationRequest(
                raw_line="Bilinmeyen banka hizmet bedeli",
                supplier_hint="Banka",
                allowed_categories=("genel_gider", "bilinmeyen"),
                max_input_chars=80,
            )
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.groq.com/openai/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer gsk-test")
        self.assertEqual(request_payload["model"], "openai/gpt-oss-20b")
        self.assertEqual(request_payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(provider.provider_name, "groq")
        self.assertIn("Bilinmeyen banka hizmet bedeli", request_payload["input"][1]["content"])
        self.assertEqual(response["category"], "bilinmeyen")

    def test_statement_ai_suggestions_only_call_provider_for_uncertain_statement_lines(self) -> None:
        provider = FakeStatementSuggestionProvider(
            [
                {
                    "transaction_type": "bank_transfer_out",
                    "suggested_account_code": "320.01.111",
                    "confidence": 74,
                    "reason": "Açıklama tedarikçi ödemesine benziyor.",
                    "evidence": ["odeme", "tedarikci"],
                },
                {
                    "transaction_type": "counterparty_payment",
                    "suggested_account_code": "320.01.222",
                    "confidence": 81,
                    "reason": "Düşük güvenli havale satırı cari ödemeye benziyor.",
                    "evidence": ["havale"],
                },
            ]
        )
        lines = (
            StatementLine(
                line_no=1,
                transaction_date="2026-06-01",
                description="GIB ODEME",
                amount="100.00",
                direction="out",
                suggested_account_code="360",
                transaction_type="tax_payment",
                confidence=86,
                risk_flags=(),
            ),
            StatementLine(
                line_no=2,
                transaction_date="2026-06-02",
                description="BILINMEYEN TEDARIKCI ODEME",
                amount="250.00",
                direction="out",
                transaction_type="unknown",
                confidence=35,
                risk_flags=("statement_review_required", "counterparty_not_found"),
            ),
            StatementLine(
                line_no=3,
                transaction_date="2026-06-03",
                description="GIDEN HAVALE",
                amount="400.00",
                direction="out",
                suggested_account_code="320",
                transaction_type="bank_transfer_out",
                confidence=68,
                risk_flags=("statement_review_required",),
            ),
        )

        batch = suggest_statement_lines(
            lines,
            provider=provider,
            policy=StatementAiSuggestionPolicy(enabled=True, confidence_threshold=70, max_provider_calls=5),
        )

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(batch.ai_used_count, 2)
        self.assertEqual([suggestion.line_no for suggestion in batch.suggestions], [2, 3])
        self.assertEqual(batch.suggestions[0].suggested_account_code, "320.01.111")
        self.assertFalse(batch.suggestions[0].export_allowed)
        self.assertEqual(batch.skipped_count, 1)

    def test_invoice_line_extraction_keeps_brand_model_rows(self) -> None:
        text = """
        Fatura No: ABC2026000000001
        Rexton RLi 20 12.000,00
        Urban Care sac bakim seti 450,00
        Odenecek Tutar 12.450,00
        """

        lines = extract_invoice_lines_from_text(text)

        descriptions = [line.description for line in lines]
        self.assertIn("Rexton RLi 20", descriptions)
        self.assertIn("Urban Care sac bakim seti", descriptions)

    def test_matching_simulation_records_ai_classification_metadata(self) -> None:
        invoice = ParsedInvoice(
            file_name="unknown-device.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9 receiver unit",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider(
                {
                    "category": "isitme_cihazi",
                    "confidence": 84,
                    "reason": "Model odyoloji cihaz ailesine benziyor.",
                    "evidence": ["ai:model_family"],
                    "suggested_account_code": "770.01",
                    "suggested_counterparty_code": "320.01",
                    "risk_flags": ["accountant_review_required"],
                    "account_reason": "AI mevcut hesap adaylari icinden gider ve cari onerdi.",
                }
            ),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = simulate_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.ai_classification_provider, "fake_llm")
        self.assertEqual(result.product_category, "isitme_cihazi")
        self.assertEqual(result.business_relevance_status, "uygun")
        self.assertEqual(result.ai_suggested_account_code, "770.01")
        self.assertEqual(result.ai_suggested_counterparty_code, "320.01")
        self.assertEqual(result.ai_risk_flags, ("accountant_review_required",))
        self.assertIn("gider ve cari", result.ai_account_reason)
        self.assertEqual(result.export_status, "review_required")

    def test_ai_assisted_draft_mode_keeps_clean_draft_in_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="rexton.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890",),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        accounts = [
            ChartAccount("320.01.015", "320.01.015", "Rexton Medikal", is_detail_account=True, tax_id="1234567890"),
        ]
        counterparty = match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint)

        assisted = simulate_invoice(invoice, selection, profile, counterparty, processing_mode="ai_assisted_draft")
        controlled = simulate_invoice(invoice, selection, profile, counterparty, processing_mode="controlled_automation")

        self.assertEqual(assisted.processing_mode, "ai_assisted_draft")
        self.assertEqual(assisted.export_status, "review_required")
        self.assertEqual(assisted.simulated_status, "review_required")
        self.assertIn("ai_assisted_draft_requires_accountant_approval", assisted.review_reason_codes)
        self.assertIn("balanced_entry", assisted.deterministic_checks)
        self.assertIn("mustavir onayi olmadan export kapali", assisted.export_gate_reason)
        self.assertEqual(controlled.export_status, "export_ready")
        self.assertEqual(controlled.simulated_status, "auto_ready")

    def test_counterparty_matching_prefers_tax_id_then_review_for_missing(self) -> None:
        accounts = [
            ChartAccount("320.01", "320.01", "Saticilar", is_detail_account=False),
            ChartAccount("320.01.015", "320.01.015", "Rexton Medikal", is_detail_account=True, tax_id="1234567890"),
        ]

        exact = match_counterparty(accounts, tax_ids=("1234567890",), name_hint="Bilinmeyen")
        missing = match_counterparty(accounts, tax_ids=("9999999999",), name_hint="Baska Firma")

        self.assertEqual(exact.account_code, "320.01.015")
        self.assertEqual(exact.match_reason, "tax_id_exact")
        self.assertFalse(exact.requires_review)
        self.assertEqual(missing.match_reason, "not_found")
        self.assertTrue(missing.requires_review)

    def test_review_decision_creates_learning_event_after_three_consistent_approvals(self) -> None:
        decision = ReviewDecision(
            document_ref="AF-0001",
            action="approve_with_changes",
            reviewer="mustavir",
            corrected_account_code="770.04",
            category="e_fatura_hizmeti",
            apply_to_similar=True,
        )

        event = build_learning_event(decision, prior_consistent_approval_count=2)

        self.assertEqual(event.scope, "client_rule")
        self.assertTrue(event.automation_candidate)

    def test_learning_rule_changes_next_similar_document_suggestion(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="kolaysoft-tekrar.pdf",
            provider_hint="Kolay Soft",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kolay Soft e-fatura hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        decision = ReviewDecision(
            document_ref="kolaysoft-ilk.pdf",
            action="approve_with_changes",
            reviewer="mustavir",
            corrected_account_code="770.05",
            category="e_fatura_hizmeti",
            reason="Bu mukellefte e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
            apply_to_similar=True,
        )

        result = simulate_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_learning_event(build_learning_event(decision))])

        self.assertEqual(result.selected_expense_account, "770.01")
        self.assertEqual(learned.selected_expense_account, "770.05")
        self.assertEqual(learned.draft_lines[0]["account_code"], "770.05")
        self.assertTrue(learned.learning_rule_applied)
        self.assertEqual(learned.learning_rule_scope, "client_rule")

    def test_export_package_excludes_risky_or_review_required_entries(self) -> None:
        ready = build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="ready.pdf",
        )
        risky = build_purchase_entry(
            entry_date="2026-05-02",
            total=money("600.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="risky.pdf",
        )

        package = build_export_package(
            [
                ExportCandidate("ready.pdf", "export_ready", ready),
                ExportCandidate("risky.pdf", "review_required", risky, risk_flags=("counterparty_not_found",)),
            ]
        )

        self.assertEqual(len(package.entries), 1)
        self.assertEqual(package.entries[0].description, "Alis faturasi ready.pdf")
        self.assertEqual(package.excluded_document_refs, ("risky.pdf",))

    def test_export_adapter_writes_json_manifest_and_rejects_unknown_type(self) -> None:
        entry = build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="ready.pdf",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manifest.json"
            adapter = get_export_adapter("json_manifest")

            written = write_export_file(
                adapter=adapter,
                entries=(entry,),
                output_path=output_path,
                client_id="client-1",
            )
            text = written.read_text(encoding="utf-8")

        self.assertTrue(written.name.endswith(".json"))
        self.assertIn('"export_type": "json_manifest"', text)
        self.assertIn('"document_ref": "ready.pdf"', text)
        with self.assertRaises(ValueError):
            get_export_adapter("zirve_verified_format")

    def test_zirve_trial_csv_adapter_writes_field_mapping_candidate(self) -> None:
        entry = build_bank_payment_entry(
            entry_date="2026-05-03",
            amount=money("500.00"),
            bank_account="102.01",
            counterparty_account="360",
            counterparty_tax_id="1111111111",
            document_ref="BNK-0001",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = export_zirve_trial_csv([entry], Path(temp_dir) / "zirve-trial.csv")
            adapter = get_export_adapter("zirve_trial_csv")
            text = output.read_text(encoding="utf-8-sig")

        self.assertEqual(adapter.validation_status, "field_test_pending")
        self.assertFalse(adapter.verified_in_zirve)
        self.assertIn("fis_tarihi;fis_turu;fis_aciklama", text)
        self.assertIn("2026-05-03;BANKA", text)
        self.assertIn("360;Cari odeme;500.00;0.00;BNK-0001;1111111111", text)

    def test_workspace_export_package_includes_only_ready_balanced_entries(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "ready.pdf",
                    "export_status": "export_ready",
                    "result": {
                        "file_name": "ready.pdf",
                        "issue_date": "2026-05-01",
                        "draft_entry_type": "purchase",
                        "review_reason_codes": [],
                        "risk_flags": [],
                        "draft_lines": [
                            {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                            {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "100.00"},
                        ],
                    },
                },
                {
                    "document_ref": "statement.csv",
                    "export_status": "export_ready",
                    "result": {
                        "export_status": "export_ready",
                        "accountant_export_override": True,
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "GIB ODEME",
                                "statement_line_no": 1,
                                "statement_fingerprint": "statement-ready-1",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                            {
                                "entry_type": "bank_collection",
                                "entry_date": "2026-05-03",
                                "description": "POS BLOKE",
                                "statement_line_no": 2,
                                "statement_fingerprint": "statement-pos-2",
                                "risk_flags": ["pos_policy_review_required"],
                                "lines": [
                                    {"account_code": "102.01", "description": "Banka girisi", "debit": "80.00", "credit": "0.00"},
                                    {"account_code": "108", "description": "pos_blocked", "debit": "0.00", "credit": "80.00"},
                                ],
                            },
                        ]
                    },
                },
            ]
        }

        build = build_workspace_export_package(workspace)

        self.assertEqual(build.candidate_count, 3)
        self.assertEqual(len(build.package.entries), 2)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-2",))

    def test_workspace_export_package_blocks_statement_entries_until_accountant_approval(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "export_status": "export_ready",
                    "result": {
                        "export_status": "export_ready",
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "GIB ODEME",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                        ],
                    },
                },
            ]
        }

        build = build_workspace_export_package(workspace)

        self.assertEqual(build.candidate_count, 1)
        self.assertEqual(len(build.package.entries), 0)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-1",))

    def test_workspace_export_package_blocks_duplicate_approved_statement_entry(self) -> None:
        entry_payload = {
            "entry_type": "bank_payment",
            "entry_date": "2026-05-02",
            "description": "GIB ODEME",
            "accountant_review_status": "approved",
            "statement_fingerprint": "2026-05-02|out|50.00|gib-odeme",
            "risk_flags": [],
            "lines": [
                {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
            ],
        }
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "result": {
                        "statement_entries": [
                            {**entry_payload, "statement_line_no": 1},
                            {**entry_payload, "statement_line_no": 2},
                        ]
                    },
                },
            ]
        }

        candidates = export_candidates_from_workspace(workspace)
        build = build_workspace_export_package(workspace)

        self.assertEqual(candidates[0].export_status, "export_ready")
        self.assertEqual(candidates[1].export_status, "review_required")
        self.assertIn("duplicate_statement_line", candidates[1].risk_flags)
        self.assertEqual(len(build.package.entries), 1)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-2",))

    def test_workspace_export_package_blocks_statement_entry_without_bank_account(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "result": {
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "Eksik banka satiri",
                                "accountant_review_status": "approved",
                                "statement_fingerprint": "2026-05-02|out|50.00|eksik",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "320.01", "description": "Cari", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "320.02", "description": "Cari", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                        ]
                    },
                },
            ]
        }

        candidate = export_candidates_from_workspace(workspace)[0]

        self.assertEqual(candidate.export_status, "review_required")
        self.assertIn("bank_account_missing", candidate.risk_flags)

    def test_ai_batch_benchmark_scores_static_and_replay_provider_results(self) -> None:
        static_summary = run_ai_batch_benchmark(
            (
                AiBenchmarkCase("1", "Rexton RLi 20", "Rexton", "isitme_cihazi"),
                AiBenchmarkCase("2", "Urban Care sac bakim", "", "kisisel_bakim_kozmetik"),
            )
        )
        provider_summary = run_ai_batch_benchmark(
            (AiBenchmarkCase("3", "ZX Sonic Pro 9", "Medikal", "isitme_cihazi"),),
            policy=AiClassificationPolicy(enabled=True),
            provider_name="replay_openai",
            provider_payloads=[
                {
                    "category": "isitme_cihazi",
                    "confidence": 82,
                    "reason": "Model isitme cihazi ailesine benziyor.",
                    "evidence": ["benchmark"],
                }
            ],
        )

        self.assertEqual(static_summary.accuracy_percent, 100)
        self.assertEqual(static_summary.ai_used_count, 0)
        self.assertEqual(provider_summary.provider, "replay_openai")
        self.assertEqual(provider_summary.ai_used_count, 1)
        self.assertEqual(provider_summary.accuracy_percent, 100)

    def test_ai_batch_benchmark_uses_default_demo_cases_when_empty(self) -> None:
        summary = run_ai_batch_benchmark(())

        self.assertGreaterEqual(summary.case_count, 8)
        self.assertEqual(summary.ai_used_count, 0)
        self.assertEqual(summary.accuracy_percent, 100)
        self.assertIn("Urban Care", " ".join(result.raw_line for result in summary.results))


if __name__ == "__main__":
    unittest.main()
