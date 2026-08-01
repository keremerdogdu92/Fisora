from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.provider_directory import resolve_provider_profile
from app.domain.xml_invoices import parse_xml_invoice
from app.domain.matching_simulation import _counterparty_invoice_payload
from app.workflows.document_processing import _accountant_summary


class ProviderDirectoryTests(unittest.TestCase):
    def test_known_ubl_supplier_vkn_resolves_fast_lane_profile(self) -> None:
        match = resolve_provider_profile(
            supplier_tax_id="9250353261",
            supplier_title="Vodafone Telekomünikasyon A.Ş.",
            source="xml",
        )

        self.assertEqual(match.provider_id, "vodafone_tr")
        self.assertEqual(match.service_profile, "gsm_communication")
        self.assertEqual(match.match_kind, "vkn")

    def test_pdf_title_can_resolve_profile_when_vkn_is_missing(self) -> None:
        match = resolve_provider_profile(
            supplier_tax_id="",
            supplier_title="Vodafone Telekomünikasyon A.Ş.",
            source="pdf",
        )

        self.assertEqual(match.provider_id, "vodafone_tr")
        self.assertEqual(match.match_kind, "title")

    def test_national_catalog_resolves_common_gsm_internet_electricity_and_gas_issuers(self) -> None:
        cases = (
            ("8590380323", "TT Mobil İletişim Hizmetleri A.Ş.", "gsm_communication"),
            ("7350150917", "Turknet İletişim Hizmetleri A.Ş.", "fixed_internet"),
            ("3350432123", "Enerjisa Başkent Elektrik Perakende Satış A.Ş.", "electricity"),
            ("8830347477", "Vangölü Elektrik Perakende Satış A.Ş.", "electricity"),
            ("1480394682", "Başkent Doğalgaz Dağıtım Gayrimenkul Yatırım Ortaklığı A.Ş.", "natural_gas"),
            ("3800307997", "ESGAZ Eskişehir Şehiriçi Doğal Gaz Dağıtım Ticaret ve Taahhüt A.Ş.", "natural_gas"),
            ("3890607989", "GAZDAŞ Gaziantep Doğal Gaz Dağıtım A.Ş.", "natural_gas"),
            ("7200361395", "PALGAZ Doğal Gaz Dağıtım Sanayi ve Ticaret A.Ş.", "natural_gas"),
        )

        for tax_id, title, expected_profile in cases:
            with self.subTest(tax_id=tax_id):
                match = resolve_provider_profile(
                    supplier_tax_id=tax_id,
                    supplier_title=title,
                    source="xml",
                )
                self.assertEqual(match.service_profile, expected_profile)
                self.assertEqual(match.match_kind, "vkn")

    def test_pdf_exact_brand_title_resolves_active_fixed_internet_profile(self) -> None:
        match = resolve_provider_profile(
            supplier_tax_id="",
            supplier_title="TurkNet",
            source="pdf",
        )

        self.assertEqual(match.provider_id, "turknet")
        self.assertEqual(match.service_profile, "fixed_internet")
        self.assertEqual(match.match_kind, "title")

    def test_ubl_title_without_vkn_does_not_open_fast_lane(self) -> None:
        match = resolve_provider_profile(
            supplier_tax_id="",
            supplier_title="Vodafone Telekomünikasyon A.Ş.",
            source="xml",
        )

        self.assertEqual(match.provider_id, "")
        self.assertEqual(match.reason_code, "ubl_supplier_vkn_missing")

    def test_xml_parse_exposes_exact_supplier_profile_evidence(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>VDF2026001</cbc:ID><cbc:IssueDate>2026-08-01</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyIdentification><cbc:ID schemeID="VKN">9250353261</cbc:ID></cac:PartyIdentification><cac:PartyName><cbc:Name>Vodafone Telekomunikasyon A.S.</cbc:Name></cac:PartyName></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyIdentification><cbc:ID schemeID="VKN">1234567890</cbc:ID></cac:PartyIdentification><cac:PartyName><cbc:Name>Fisero Musteri A.S.</cbc:Name></cac:PartyName></cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount>100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Telefon cihaz bedeli</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:LegalMonetaryTotal><cbc:PayableAmount>120.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vodafone.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)

        self.assertEqual(invoice.provider_id, "vodafone_tr")
        self.assertEqual(invoice.service_profile, "gsm_communication")
        self.assertEqual(invoice.provider_match_kind, "vkn")
        self.assertEqual(invoice.utility_exception_markers, ("utility_device_line",))

        ai_counterparty = _counterparty_invoice_payload(
            invoice,
            direction="purchase",
            direction_confidence=100,
            direction_evidence=("taxpayer_matches_customer",),
            counterparty_title=invoice.issuer_title,
            counterparty_tax_id=invoice.issuer_tax_id,
        )
        self.assertEqual(ai_counterparty["service_profile"], "gsm_communication")
        self.assertEqual(ai_counterparty["provider_id"], "vodafone_tr")
        self.assertEqual(ai_counterparty["provider_match_kind"], "vkn")

    def test_accountant_summary_names_known_utility_profile(self) -> None:
        summary = _accountant_summary(
            {
                "draft_lines": [{"account_code": "770.03.001"}],
                "is_balanced": True,
                "service_profile": "gsm_communication",
            }
        )

        self.assertIn("GSM", summary)

    def test_accountant_summary_keeps_device_exception_focused(self) -> None:
        summary = _accountant_summary(
            {
                "draft_lines": [{"account_code": "770.03.001"}],
                "is_balanced": True,
                "service_profile": "gsm_communication",
                "utility_exception_markers": ["utility_device_line"],
            }
        )

        self.assertIn("cihaz", summary.lower())


if __name__ == "__main__":
    unittest.main()
