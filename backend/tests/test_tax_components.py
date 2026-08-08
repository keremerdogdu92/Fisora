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

from app.domain.canonical_invoices import (
    CanonicalMonetaryComponent,
    CanonicalTaxComponent,
    canonical_extraction_output_schema,
    normalize_monetary_component,
    normalize_tax_component,
)
from app.domain.ai_classification import (
    AiCandidateStrategy,
    AiClassificationContext,
    AiClassificationPolicy,
    StaticFirstClassifier,
)
from app.domain.journal_entries import build_component_purchase_entry
from app.domain.invoice_lines import InvoiceLine
from app.domain.business_relevance import ClientProfile, ProductClassification
from app.domain.counterparty_matching import CounterpartyMatch
from app.domain.chart_accounts import parse_chart_accounts
from app.domain.invoice_ai_gate import VerifiedRuleAuthorityV1
from app.domain.matching_simulation import (
    AccountSelection,
    _ai_context,
    build_utility_component_purchase_entry,
    select_accounts,
    simulate_invoice,
)
from app.domain.pdf_invoices import build_pdf_canonical_invoice
from app.domain.vat_splits import VatSplitLine
from app.domain.xml_invoices import parse_xml_invoice
from app.api.phase0_schemas import AccountSelectionPayload
from app.domain.tax_component_accounting import (
    build_tax_component_account_experiment_request,
    validate_tax_component_account_experiment_response,
)


class TaxComponentTests(unittest.TestCase):
    def test_invoice_account_stage_returns_one_real_account_authority_for_all_utility_lines(self) -> None:
        class Provider:
            provider_name = "test_ai"

            def classify_product(self, request: object) -> dict[str, object]:
                return {
                    "selected_account_code": "770.02.001",
                    "confidence": 96,
                    "reason": "Sabit internet hizmeti gerçek haberleşme gideri hesabıyla eşleşiyor.",
                    "possible_exception_line_ids": [],
                    "needs_research": False,
                    "research_query": "",
                }

        classifier = StaticFirstClassifier(
            provider=Provider(),
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )
        context = AiClassificationContext(
            client_activity="Perakende ticaret",
            accounting_direction="purchase",
            account_candidates=("770.02.001",),
            account_candidate_details=(
                {"code": "770.02.001", "name": "HABERLEŞME GİDERLERİ"},
            ),
            canonical_lines=(
                {"canonical_line_id": "line-1", "description": "İnternet", "taxable_amount": "684.61"},
                {"canonical_line_id": "line-2", "description": "Bağlantı ücreti", "taxable_amount": "75.00"},
            ),
            invoice_counterparty={"service_profile": "fixed_internet"},
            candidate_strategy=AiCandidateStrategy(
                mode="single_stage",
                stage="invoice_account",
                account_candidate_count=1,
            ),
        )

        result = classifier.classify("İnternet | Bağlantı ücreti", context=context)

        self.assertTrue(result.ai_used)
        self.assertEqual(result.classification.category, "internet")
        self.assertEqual(result.suggested_account_code, "770.02.001")
        self.assertEqual(
            [(item["canonical_line_id"], item["suggested_account_code"]) for item in result.line_decisions],
            [("line-1", "770.02.001"), ("line-2", "770.02.001")],
        )
        self.assertTrue(result.semantic_attempts[0]["accepted"])
        self.assertEqual(result.ai_trace[0]["stage"], "invoice_account")

    def test_counterparty_stage_selects_only_a_real_tenant_cari_candidate(self) -> None:
        class Provider:
            provider_name = "test_ai"

            def classify_product(self, request: object) -> dict[str, object]:
                return {
                    "selected_counterparty_code": "320.01.001",
                    "confidence": 94,
                    "reason": "VKN ve unvan gerçek cari adayıyla eşleşiyor.",
                    "needs_research": False,
                    "research_query": "",
                }

        classifier = StaticFirstClassifier(
            provider=Provider(),
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )
        context = AiClassificationContext(
            accounting_direction="purchase",
            counterparty_candidates=("320.01.001", "320.01.002"),
            counterparty_candidate_details=(
                {"code": "320.01.001", "name": "ENERJİSA", "tax_id": "4810577635"},
                {"code": "320.01.002", "name": "DİĞER SATICI", "tax_id": "1111111111"},
            ),
            invoice_counterparty={"counterparty_title": "ENERJİSA", "counterparty_tax_id": "4810577635"},
            candidate_strategy=AiCandidateStrategy(
                mode="single_stage",
                stage="counterparty_resolve",
                counterparty_candidate_count=2,
            ),
        )

        result = classifier.classify("Elektrik tüketimi", context=context)

        self.assertTrue(result.ai_used)
        self.assertEqual(result.suggested_counterparty_code, "320.01.001")
        self.assertEqual(result.ai_trace[0]["stage"], "counterparty_resolve")

    def test_normalization_preserves_source_and_classifies_known_tax_codes(self) -> None:
        vat = normalize_tax_component(
            source_label="KDV",
            source_code="0015",
            rate="20",
            taxable_amount="100.00",
            tax_amount="20.00",
            source_position="xml:TaxSubtotal[1]",
        )
        oiv = normalize_tax_component(
            source_label="ÖZEL İLETİŞİM VERGİSİ",
            source_code="4080",
            rate="10",
            taxable_amount="100.00",
            tax_amount="10.00",
            source_position="xml:TaxSubtotal[2]",
        )
        electricity = normalize_tax_component(
            source_label="ELK.HAVAGAZ.TÜK.VER.",
            source_code="4071",
            rate="0",
            taxable_amount="0.00",
            tax_amount="14.35",
            source_position="xml:TaxSubtotal[3]",
        )

        self.assertEqual(vat.canonical_tax_kind, "vat")
        self.assertEqual(vat.accounting_treatment, "deductible_vat")
        self.assertEqual(oiv.canonical_tax_kind, "special_communication_tax")
        self.assertEqual(oiv.accounting_treatment, "unresolved")
        self.assertEqual(electricity.canonical_tax_kind, "electricity_consumption_tax")
        self.assertEqual(electricity.accounting_treatment, "related_service_expense")
        self.assertEqual(oiv.source_label, "ÖZEL İLETİŞİM VERGİSİ")
        self.assertEqual(oiv.source_position, "xml:TaxSubtotal[2]")

    def test_unknown_non_vat_tax_is_not_silently_assigned(self) -> None:
        component = normalize_tax_component(
            source_label="DİĞER VERGİ",
            source_code="9999",
            rate="",
            taxable_amount="",
            tax_amount="5.00",
            source_position="pdf:page[1]:line[42]",
        )

        self.assertEqual(component.canonical_tax_kind, "unknown_non_vat_tax")
        self.assertEqual(component.accounting_treatment, "unresolved")
        self.assertEqual(component.normalization_confidence, "unknown")

    def test_utility_monetary_components_separate_prior_period_from_current_expense(self) -> None:
        previous = normalize_monetary_component(
            source_label="Önceki Aydan Devir",
            source_amount="0.06",
            source_position="xml:InvoiceLine[8]",
        )
        device = normalize_monetary_component(
            source_label="Cihaz/ Bağlantı Ücreti",
            source_amount="75.00",
            source_position="xml:InvoiceLine[5]",
        )
        installment = normalize_monetary_component(
            source_label="Taksitler Toplamı",
            source_amount="90.00",
            source_position="xml:InvoiceLine[7]",
        )

        self.assertIsInstance(previous, CanonicalMonetaryComponent)
        self.assertEqual(previous.canonical_component_kind, "prior_period_balance")
        self.assertEqual(previous.accounting_treatment, "exclude_current_period")
        self.assertEqual(device.accounting_treatment, "related_service_expense")
        self.assertEqual(installment.accounting_treatment, "related_service_expense")

    def test_radio_usage_fee_is_related_telecom_expense_not_unresolved_tax(self) -> None:
        component = normalize_tax_component(
            source_label="Telsiz Kullanma Ücretleri",
            source_code="8006",
            rate="",
            taxable_amount="",
            tax_amount="26.98",
            source_position="xml:TaxSubtotal[3]",
        )

        self.assertEqual(component.canonical_tax_kind, "radio_usage_fee")
        self.assertEqual(component.accounting_treatment, "related_service_expense")

    def test_account_selection_never_invents_missing_chart_codes(self) -> None:
        selection = select_accounts("empty-chart.xlsx", [])

        self.assertEqual(selection.expense_account, "")
        self.assertEqual(selection.purchase_vat_account, "")
        self.assertEqual(selection.supplier_account, "")
        self.assertEqual(selection.bank_account, "")
        self.assertEqual(selection.non_deductible_account, "")
        self.assertEqual(selection.revenue_account, "")
        self.assertEqual(selection.sales_vat_account, "")
        self.assertEqual(selection.customer_account, "")
        self.assertEqual(selection.stock_account, "")

        manual = AccountSelection(
            chart_file_name="api",
            expense_account="",
            purchase_vat_account="",
            supplier_account="",
            bank_account="",
            selection_notes=(),
        )
        self.assertEqual(manual.revenue_account, "")
        self.assertEqual(manual.zero_vat_revenue_account, "")
        self.assertEqual(manual.sales_vat_account, "")
        self.assertEqual(manual.customer_account, "")
        self.assertEqual(manual.stock_account, "")
        self.assertEqual(manual.non_deductible_account, "")

        payload = AccountSelectionPayload()
        self.assertEqual(payload.expense_account, "")
        self.assertEqual(payload.purchase_vat_account, "")
        self.assertEqual(payload.supplier_account, "")
        self.assertEqual(payload.non_deductible_account, "")

    def test_ai_account_context_does_not_mix_cari_vat_or_sales_candidates_into_purchase_prompt(self) -> None:
        chart_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "chart_accounts"
            / "chart_accounts.xlsx"
        )
        invoice_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "4810577635_AS02026001010557.xml"
        )
        invoice = parse_xml_invoice(invoice_path)
        selection = select_accounts(chart_path.name, parse_chart_accounts(chart_path))
        profile = ClientProfile(
            client_id="firma-7",
            title=invoice.recipient_title,
            tax_id=invoice.recipient_tax_id,
            activity_description="İşitme cihazı satış ve uygulama merkezi",
            workplace_addresses=("İstanbul",),
            has_chart_accounts=True,
        )

        context = _ai_context(
            invoice=invoice,
            selection=selection,
            client_profile=profile,
            counterparty_match=None,
            direction="purchase",
            direction_confidence=100,
            direction_evidence=("ubl_parties",),
            suggested_counterparty=selection.supplier_account,
            counterparty_title=invoice.issuer_title,
            counterparty_tax_id=invoice.issuer_tax_id,
        )

        groups = {str(candidate["group"]) for candidate in context.account_candidate_details}
        self.assertEqual(len(context.account_candidate_details), 1)
        self.assertEqual(groups, {"purchase_expense"})
        self.assertEqual(context.account_candidates, ("770.02.003",))
        self.assertNotIn("purchase_vat", groups)
        self.assertNotIn("supplier", groups)
        self.assertNotIn("sales_revenue", groups)
        real_supplier_codes = {
            str(candidate["code"])
            for candidate in selection.account_candidates.get("supplier", ())
        }
        self.assertTrue(set(context.counterparty_candidates).issubset(real_supplier_codes))
        self.assertNotIn("320.4810577635", context.counterparty_candidates)

    def test_oiv_experiment_uses_only_real_chart_candidates_without_policy_hint(self) -> None:
        chart_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "chart_accounts"
            / "chart_accounts.xlsx"
        )
        invoice_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "9250353261_N3F2026000841471.xml"
        )
        invoice = parse_xml_invoice(invoice_path)
        oiv = next(
            component
            for component in invoice.tax_components
            if component.canonical_tax_kind == "special_communication_tax"
        )

        request = build_tax_component_account_experiment_request(
            component=oiv,
            service_profile=invoice.service_profile,
            supplier_title=invoice.issuer_title,
            accounts=parse_chart_accounts(chart_path),
            client_activity="İşitme cihazı satış ve uygulama merkezi",
        )
        payload = request.to_schema_payload()
        candidate_codes = tuple(candidate["code"] for candidate in payload["account_candidate_details"])
        serialized = str(payload).lower()

        self.assertEqual(candidate_codes, ("689.01", "760.03.010", "770.02.001", "770.02.016"))
        self.assertNotIn("non_deductible", serialized)
        self.assertNotIn("öiv kke", serialized)
        self.assertIn("96.38", payload["raw_line"])
        self.assertIn("gsm_communication", payload["raw_line"])

        accepted = validate_tax_component_account_experiment_response(
            request=request,
            response={
                "category": "tax_component",
                "confidence": 92,
                "reason": "Kaynak vergi bileşeni ve gerçek hesap adları değerlendirildi.",
                "suggested_account_code": "689.01",
            },
        )
        rejected = validate_tax_component_account_experiment_response(
            request=request,
            response={
                "category": "tax_component",
                "confidence": 92,
                "reason": "Gerçek planda bulunmayan kod.",
                "suggested_account_code": "689.99",
            },
        )
        self.assertTrue(accepted["accepted"])
        self.assertFalse(rejected["accepted"])
        self.assertIn("selected_account_not_in_tenant_candidates", rejected["validation_errors"])

    def test_ubl_adapter_emits_canonical_tax_components(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>UTILITY-1</cbc:ID><cbc:IssueDate>2026-08-08</cbc:IssueDate>
  <cac:TaxTotal><cbc:TaxAmount>30.00</cbc:TaxAmount>
    <cac:TaxSubtotal><cbc:TaxableAmount>100.00</cbc:TaxableAmount><cbc:TaxAmount>20.00</cbc:TaxAmount><cbc:Percent>20</cbc:Percent><cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>
    <cac:TaxSubtotal><cbc:TaxableAmount>100.00</cbc:TaxableAmount><cbc:TaxAmount>10.00</cbc:TaxAmount><cbc:Percent>10</cbc:Percent><cac:TaxCategory><cac:TaxScheme><cbc:Name>ÖZEL İLETİŞİM VERGİSİ</cbc:Name><cbc:TaxTypeCode>4080</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount>100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount>130.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>130.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount>100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>İnternet hizmeti</cbc:Name></cac:Item></cac:InvoiceLine>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "utility.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)

        components = invoice.canonical_invoice.tax_components
        self.assertEqual([item.canonical_tax_kind for item in components], ["vat", "special_communication_tax"])
        self.assertEqual(invoice.tax_components, components)

    def test_ttnet_ubl_preserves_prior_period_device_and_installment_components(self) -> None:
        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "8590491872_A322026000097438.xml"
        )

        invoice = parse_xml_invoice(path)
        components = invoice.canonical_invoice.monetary_components
        by_kind = {component.canonical_component_kind: component for component in components}

        self.assertEqual(invoice.canonical_invoice.validation.status, "partial_valid")
        self.assertEqual(by_kind["prior_period_balance"].source_amount, "0.06")
        self.assertEqual(by_kind["device_connection_charge"].source_amount, "75.00")
        self.assertEqual(by_kind["installment_charge"].source_amount, "90.00")
        self.assertEqual(invoice.monetary_components, components)

    def test_vodafone_header_vat_is_allocated_to_the_only_positive_service_line(self) -> None:
        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "9250353261_N3F2026000841471.xml"
        )

        invoice = parse_xml_invoice(path)
        canonical = invoice.canonical_invoice
        positive_lines = [line for line in canonical.line_items if Decimal(line.taxable_amount or "0") > 0]

        self.assertEqual(canonical.validation.status, "valid")
        self.assertEqual(len(positive_lines), 1)
        self.assertEqual(positive_lines[0].vat_rate, "20")
        self.assertEqual(positive_lines[0].tax_amount, "192.77")
        self.assertEqual(
            [(component.canonical_tax_kind, component.accounting_treatment) for component in canonical.tax_components],
            [
                ("vat", "deductible_vat"),
                ("special_communication_tax", "unresolved"),
                ("radio_usage_fee", "related_service_expense"),
            ],
        )

    def test_ai_extraction_schema_accepts_source_grounded_tax_components(self) -> None:
        schema = canonical_extraction_output_schema()
        component_schema = schema["properties"]["observed_tax_components"]

        self.assertEqual(component_schema["type"], "array")
        self.assertIn("source_label", component_schema["items"]["required"])
        self.assertIn("source_position", component_schema["items"]["required"])
        self.assertIn("tax_amount", component_schema["items"]["required"])

    def test_pdf_adapter_emits_unknown_component_for_observed_special_tax_total(self) -> None:
        invoice = build_pdf_canonical_invoice(
            issuer_title="Telekom",
            issuer_tax_id="1234567890",
            recipient_title="Musteri",
            recipient_tax_id="1111111111",
            invoice_no="PDF-UTILITY-1",
            issue_date="2026-08-08",
            ettn="",
            scenario="EARSIVFATURA",
            invoice_type="SATIS",
            line_item_details=(
                InvoiceLine(
                    raw_text="Internet hizmeti 100,00",
                    description="Internet hizmeti",
                    taxable_amount="100.00",
                    vat_rate="20",
                    tax_amount="20.00",
                    gross_amount="120.00",
                ),
            ),
            vat_split_lines=(
                VatSplitLine(
                    rate="20",
                    taxable_amount="100.00",
                    tax_amount="20.00",
                    source="pdf_text",
                ),
            ),
            parsed_totals={
                "goods_services_total": "100.00",
                "vat_total": "20.00",
                "special_tax_total": "10.00",
                "tax_inclusive_total": "130.00",
                "payable_total": "130.00",
            },
        )

        self.assertEqual(len(invoice.tax_components), 1)
        self.assertEqual(invoice.tax_components[0].canonical_tax_kind, "unknown_non_vat_tax")
        self.assertEqual(invoice.tax_components[0].tax_amount, "10.00")

    def test_component_purchase_entry_uses_exact_source_amounts_and_balances(self) -> None:
        entry = build_component_purchase_entry(
            entry_date="2026-08-08",
            service_expense_account="770.02.001",
            service_expense_amount=Decimal("100.00"),
            vat_account="191.01.020",
            vat_amount=Decimal("20.00"),
            separate_expenses=(("689.01", "Özel İletişim Vergisi", Decimal("10.00")),),
            supplier_account="320.01.001",
            supplier_total=Decimal("130.00"),
            document_ref="UTILITY-1",
        )

        self.assertTrue(entry.is_balanced)
        self.assertEqual(entry.total_debit, Decimal("130.00"))
        self.assertEqual(entry.total_credit, Decimal("130.00"))
        self.assertEqual([line.account_code for line in entry.lines], ["770.02.001", "191.01.020", "689.01", "320.01.001"])

    def test_enerjisa_component_journal_includes_consumption_tax_in_electricity_expense(self) -> None:
        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "4810577635_AS02026001010557.xml"
        )
        invoice = parse_xml_invoice(path)

        entry = build_utility_component_purchase_entry(
            invoice=invoice,
            service_expense_account="770.ELEKTRIK",
            vat_account="191.KDV",
            supplier_account="320.ENERJISA",
        )

        self.assertIsNotNone(entry)
        self.assertTrue(entry.is_balanced)
        self.assertEqual(entry.risk_flags, ())
        self.assertEqual(
            [(line.account_code, line.debit, line.credit) for line in entry.lines],
            [
                ("770.ELEKTRIK", Decimal("1172.94"), Decimal("0.00")),
                ("191.KDV", Decimal("117.06"), Decimal("0.00")),
                ("320.ENERJISA", Decimal("0.00"), Decimal("1290.00")),
            ],
        )

    def test_ttnet_component_journal_excludes_prior_period_and_keeps_oiv_separate(self) -> None:
        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "8590491872_A322026000097438.xml"
        )
        invoice = parse_xml_invoice(path)

        entry = build_utility_component_purchase_entry(
            invoice=invoice,
            service_expense_account="770.INTERNET",
            vat_account="191.KDV",
            supplier_account="320.TTNET",
        )

        self.assertIsNotNone(entry)
        self.assertTrue(entry.is_balanced)
        self.assertEqual(entry.risk_flags, ("tax_component_account_unresolved",))
        self.assertEqual(entry.total_credit, Decimal("1054.94"))
        self.assertEqual(
            [(line.account_code, line.description, line.debit) for line in entry.lines[:-1]],
            [
                ("770.INTERNET", "Hizmet gideri", Decimal("837.06")),
                ("191.KDV", "Indirilecek KDV", Decimal("149.42")),
                ("", "ÖZEL İLETİŞİM VERGİSİ", Decimal("68.46")),
            ],
        )

    def test_simulation_uses_component_journal_for_utility_purchase(self) -> None:
        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "4810577635_AS02026001010557.xml"
        )
        invoice = parse_xml_invoice(path)
        expense_account = "770.01.001"
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account=expense_account,
            purchase_vat_account="191.KDV",
            supplier_account="320.ENERJISA",
            bank_account="102.BANKA",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {
                        "code": expense_account,
                        "name": "Elektrik giderleri",
                        "reason": "tenant chart",
                        "is_detail_account": True,
                        "is_active": True,
                    },
                ),
                "purchase_vat": (
                    {"code": "191.KDV", "name": "İndirilecek KDV", "reason": "tenant chart"},
                ),
                "supplier": (
                    {"code": "320.ENERJISA", "name": "Enerjisa", "reason": "tenant chart"},
                ),
            },
            account_names={
                expense_account: "Elektrik giderleri",
                "191.KDV": "İndirilecek KDV",
                "320.ENERJISA": "Enerjisa",
            },
        )
        profile = ClientProfile(
            client_id="firma-7",
            title=invoice.recipient_title,
            tax_id=invoice.recipient_tax_id,
            activity_description="İşitme cihazı satış ve uygulama merkezi",
            workplace_addresses=("İstanbul",),
            has_chart_accounts=True,
        )
        counterparty = CounterpartyMatch(
            account_code="320.ENERJISA",
            account_name="Enerjisa",
            confidence=100,
            match_reason="tax_id_exact",
            requires_review=False,
        )
        authorities = tuple(
            VerifiedRuleAuthorityV1(
                schema_version="v1",
                client_id="firma-7",
                rule_id=f"utility-{index}",
                rule_version="1",
                activation_event_id=f"activation-{index}",
                source_review_decision_id=f"review-{index}",
                confirmed_actor_id="accountant",
                canonical_line_id=line.canonical_line_id,
                direction="purchase",
                invoice_mode="ordinary",
                semantic_role="expense",
                account_code=expense_account,
            )
            for index, line in enumerate(invoice.canonical_invoice.line_items, start=1)
        )

        result = simulate_invoice(
            invoice,
            selection,
            profile,
            counterparty,
            intended_direction="purchase",
            classification_override=ProductClassification(
                raw_line="Elektrik tüketimi",
                category="office_expense",
                confidence=100,
                evidence=("utility_profile:electricity",),
            ),
            verified_rule_authorities=authorities,
        )

        self.assertEqual(result.draft_entry_type, "component_purchase")
        self.assertTrue(result.is_balanced)
        self.assertEqual(
            [(line["account_code"], line["debit"], line["credit"]) for line in result.draft_lines],
            [
                (expense_account, "1172.94", "0.00"),
                ("191.KDV", "117.06", "0.00"),
                ("320.ENERJISA", "0.00", "1290.00"),
            ],
        )

    def test_ttnet_simulation_preserves_ready_draft_and_blocks_only_unresolved_oiv_account(self) -> None:
        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "8590491872_A322026000097438.xml"
        )
        invoice = parse_xml_invoice(path)
        expense_account = "770.02.001"
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account=expense_account,
            purchase_vat_account="191.01.020",
            supplier_account="320.TTNET",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {
                        "code": expense_account,
                        "name": "Haberleşme giderleri",
                        "reason": "tenant chart",
                        "is_detail_account": True,
                        "is_active": True,
                    },
                ),
            },
            account_names={expense_account: "Haberleşme giderleri"},
        )
        profile = ClientProfile(
            client_id="firma-7",
            title=invoice.recipient_title,
            tax_id=invoice.recipient_tax_id,
            activity_description="İşitme cihazı satış ve uygulama merkezi",
            workplace_addresses=("İstanbul",),
            has_chart_accounts=True,
        )
        authorities = tuple(
            VerifiedRuleAuthorityV1(
                schema_version="v1",
                client_id="firma-7",
                rule_id=f"ttnet-{index}",
                rule_version="1",
                activation_event_id=f"activation-{index}",
                source_review_decision_id=f"review-{index}",
                confirmed_actor_id="accountant",
                canonical_line_id=line.canonical_line_id,
                direction="purchase",
                invoice_mode="ordinary",
                semantic_role="expense",
                account_code=expense_account,
            )
            for index, line in enumerate(invoice.canonical_invoice.line_items, start=1)
        )

        result = simulate_invoice(
            invoice,
            selection,
            profile,
            CounterpartyMatch(
                account_code="320.TTNET",
                account_name="TTNET",
                confidence=100,
                match_reason="tax_id_exact",
                requires_review=False,
            ),
            intended_direction="purchase",
            classification_override=ProductClassification(
                raw_line="İnternet hizmeti",
                category="office_expense",
                confidence=100,
                evidence=("utility_profile:fixed_internet",),
            ),
            verified_rule_authorities=authorities,
        )

        self.assertEqual(result.draft_entry_type, "component_purchase")
        self.assertTrue(result.is_balanced)
        self.assertEqual(result.total_debit, "1054.94")
        self.assertIn("tax_component_account_unresolved", result.review_reason_codes)
        self.assertNotIn("line_decision_journal_incomplete", result.review_reason_codes)
        self.assertNotIn("utility_device_line", result.review_reason_codes)
        self.assertEqual(result.draft_lines[2]["account_code"], "")
        self.assertEqual(result.draft_lines[2]["description"], "ÖZEL İLETİŞİM VERGİSİ")

    def test_zero_payable_utility_skips_ai_and_has_only_no_posting_reason(self) -> None:
        class Provider:
            provider_name = "must_not_run"

            def classify_product(self, request: object) -> dict[str, object]:
                raise AssertionError("Zero-payable invoice must not call AI")

        path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "invoices"
            / "purchases"
            / "3210362123_SV02026000010240.xml"
        )
        chart_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-7"
            / "chart_accounts"
            / "chart_accounts.xlsx"
        )
        invoice = parse_xml_invoice(path)
        classifier = StaticFirstClassifier(
            provider=Provider(),
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )
        result = simulate_invoice(
            invoice,
            select_accounts(chart_path.name, parse_chart_accounts(chart_path)),
            ClientProfile(
                client_id="firma-7",
                title=invoice.recipient_title,
                tax_id=invoice.recipient_tax_id,
                activity_description="Perakende ticaret",
                workplace_addresses=("İstanbul",),
                has_chart_accounts=True,
            ),
            CounterpartyMatch(
                account_code="",
                account_name="",
                confidence=0,
                match_reason="not_found",
                requires_review=True,
            ),
            product_classifier=classifier,
            intended_direction="purchase",
        )

        self.assertEqual(classifier.provider_calls, 0)
        self.assertEqual(result.simulated_status, "no_posting")
        self.assertEqual(result.review_reason_codes, ("zero_payable_no_posting",))
        self.assertEqual(result.draft_lines, ())
        self.assertEqual(result.selected_supplier_account, "")
        self.assertIsNone(result.suggested_counterparty_creation)


if __name__ == "__main__":
    unittest.main()
