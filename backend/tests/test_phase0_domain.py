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
from app.domain.ai_classification import AiClassificationPolicy, AiClassificationRequest, StaticFirstClassifier
from app.domain.business_relevance import (
    ClientProfile,
    assess_business_relevance,
    check_client_onboarding,
    decide_export_status,
)
from app.domain.chart_accounts import ChartAccount
from app.domain.counterparty_matching import match_counterparty
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.exporters import export_universal_journal_csv
from app.domain.invoice_lines import extract_invoice_lines_from_text
from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_operations import (
    ReviewTaskDraft,
    run_invoice_operations,
    vat_rate_decimal,
)
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.journal_entries import (
    build_bank_payment_entry,
    build_mixed_vat_purchase_entry,
    build_purchase_entry,
    build_sales_entry,
    money,
)
from app.domain.pdf_invoices import ParsedInvoice, build_route, extract_vat_rates, parse_amount
from app.domain.review_learning import ReviewDecision, build_learning_event


class FakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[AiClassificationRequest] = []

    def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class Phase0DomainTests(unittest.TestCase):
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
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, max_input_chars=24),
        )

        result = classifier.classify("ZX Sonic Pro 9 receiver unit", supplier_hint="Medikal Tedarik")

        self.assertTrue(result.ai_used)
        self.assertEqual(result.provider, "fake_llm")
        self.assertEqual(result.classification.category, "isitme_cihazi")
        self.assertIn("ai_schema_validated", result.classification.evidence)
        self.assertEqual(provider.requests[0].to_schema_payload()["raw_line"], "ZX Sonic Pro 9 receiver")

    def test_static_first_classifier_rejects_invalid_provider_schema(self) -> None:
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider({"category": "serbest", "confidence": 110, "reason": ""}),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = classifier.classify("Bilinmeyen marka kalem")

        self.assertTrue(result.ai_used)
        self.assertEqual(result.classification.category, "bilinmeyen")
        self.assertIn("ai_invalid_schema", result.classification.evidence)

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
                }
            ),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = simulate_invoice(invoice, selection, profile, product_classifier=classifier)

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.ai_classification_provider, "fake_llm")
        self.assertEqual(result.product_category, "isitme_cihazi")
        self.assertEqual(result.business_relevance_status, "uygun")

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


if __name__ == "__main__":
    unittest.main()
