from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.canonical_invoices import (  # noqa: E402
    canonical_extraction_output_schema,
    canonical_invoice_from_ai_payload,
    canonical_evidence_categories,
    derive_line_to_vat_linkage,
)


def _gemini_payload() -> dict[str, object]:
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
                "canonical_line_id": "",
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
            },
            {
                "canonical_line_id": "",
                "source_position": "page:1#line:2",
                "external_line_id": "2",
                "description": "Kurulum ucreti",
                "observed_quantity": "1",
                "observed_unit_code": "C62",
                "observed_unit_price": "25.00",
                "observed_unit_price_basis": "net",
                "observed_taxable_amount": "25.00",
                "observed_vat_rate": "20",
                "observed_tax_amount": "5.00",
                "observed_gross_amount": "30.00",
                "tax_scheme_code": "VAT",
                "tax_category_code": "S",
                "exemption_reason_code": "",
                "evidence": ["$.line_items[1]"],
            },
        ],
        "observed_vat_summary": [
            {
                "observed_rate": "20",
                "observed_taxable_amount": "125.00",
                "observed_tax_amount": "25.00",
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
                "taxable_amount": "125.00",
                "tax_amount": "12.50",
                "source_position": "page:1#tax:OIV",
                "evidence": ["$.observed_tax_components[0]"],
            }
        ],
        "observed_monetary_components": [
            {
                "source_label": "Kampanya indirimi",
                "source_amount": "5.00",
                "source_position": "page:1#allowance:1",
                "evidence": ["$.observed_monetary_components[0]"],
            }
        ],
        "observed_named_totals": [],
        "observed_totals": {
            "observed_goods_services_total": "120.00",
            "observed_allowance_total": "5.00",
            "observed_vat_total": "25.00",
            "observed_special_tax_total": "12.50",
            "observed_tax_inclusive_total": "157.50",
            "observed_payable_total": "157.50",
            "evidence": ["$.observed_totals"],
        },
        "extraction_notes": ["tax_component_classification_low_confidence"],
    }


class GeminiInvoiceFormTests(unittest.TestCase):
    def test_derived_vat_linkage_and_validation_evidence_keep_distinct_categories(self) -> None:
        payload = _gemini_payload()
        payload["line_items"][0]["observed_vat_rate"] = ""
        payload["line_items"][0]["observed_tax_amount"] = ""
        invoice = canonical_invoice_from_ai_payload(payload)

        linkage = derive_line_to_vat_linkage(invoice)
        categories = canonical_evidence_categories(invoice, linkage)

        self.assertEqual(linkage["status"], "derived_reconciled")
        self.assertIn("unique_vat_group", linkage["links"][0]["basis"])
        self.assertIn("line_vat_rate_missing", categories["missing_evidence"])
        self.assertIn("line_tax_amount_missing", categories["missing_evidence"])
        self.assertIn("vat_total_mismatch", categories["factual_contradictions"])
        self.assertIn("vat_group_unexpected_lines", categories["factual_contradictions"])
        self.assertTrue(categories["derived_reconciled"])
        self.assertEqual(
            categories["informational_warnings"],
            list(invoice.extraction_notes),
        )
    def test_explicit_named_payable_outranks_conflicting_general_total(self) -> None:
        payload = _gemini_payload()
        payload["observed_totals"]["observed_tax_inclusive_total"] = "144609.98"
        payload["observed_totals"]["observed_payable_total"] = "144609.98"
        payload["observed_named_totals"] = [
            {
                "source_label": "Genel Toplam",
                "amount": "144609.98",
                "source_position": "page:1",
                "proposed_role": "tax_inclusive_total",
                "evidence": ["Genel Toplam 144.609,98"],
            },
            {
                "source_label": "TOPLAM \u00d6DENECEK TUTAR",
                "amount": "128738.49",
                "source_position": "page:2",
                "proposed_role": "payable_total",
                "evidence": ["TOPLAM \u00d6DENECEK TUTAR 128.738,49TL"],
            },
        ]

        invoice = canonical_invoice_from_ai_payload(payload)

        self.assertEqual(invoice.totals.tax_inclusive_total, "144609.98")
        self.assertEqual(invoice.totals.payable_total, "128738.49")
        self.assertEqual(len(invoice.named_totals), 2)

    def test_extraction_schema_requests_complete_document_facts_without_account_choices(self) -> None:
        schema = canonical_extraction_output_schema(mode="discovery")
        properties = schema["properties"]

        self.assertIn("header", properties)
        self.assertIn("observed_monetary_components", properties)
        self.assertIn("observed_unit_price_basis", properties["line_items"]["items"]["properties"])
        self.assertNotIn(
            "",
            properties["line_items"]["items"]["properties"]["observed_unit_price_basis"]["enum"],
        )
        for field_name in ("tax_scheme_code", "tax_category_code", "exemption_reason_code"):
            self.assertIn(field_name, properties["line_items"]["items"]["properties"])
            self.assertIn(field_name, properties["observed_vat_summary"]["items"]["properties"])
        self.assertIn("component_type", properties["observed_tax_components"]["items"]["properties"])
        self.assertEqual(
            properties["observed_tax_components"]["items"]["properties"]["component_type"]["enum"],
            ["vat", "withholding", "special_tax", "other_tax"],
        )
        tax_properties = properties["observed_tax_components"]["items"]["properties"]
        monetary_properties = properties["observed_monetary_components"]["items"]["properties"]
        for ambiguous_field in (
            "included_in_line_net",
            "included_in_tax_total",
            "included_in_payable",
        ):
            self.assertNotIn(ambiguous_field, tax_properties)
            self.assertNotIn(ambiguous_field, monetary_properties)
        self.assertIn("observed_allowance_total", properties["observed_totals"]["properties"])
        self.assertNotIn("selected_account_code", repr(schema))
        self.assertNotIn("account_candidates", repr(schema))
        self.assertNotIn("selected_counterparty", repr(schema))

    def test_ai_payload_maps_header_parties_lines_taxes_components_and_totals(self) -> None:
        invoice = canonical_invoice_from_ai_payload(_gemini_payload())

        self.assertEqual(invoice.header.invoice_no, "GIB2026000000042")
        self.assertEqual(invoice.header.currency_code, "TRY")
        self.assertEqual(invoice.header.document_direction, "purchase")
        self.assertEqual(invoice.supplier_party.tax_id_type, "VKN")
        self.assertEqual(invoice.customer_party.tax_id, "1111111111")
        self.assertEqual(len(invoice.line_items), 2)
        self.assertEqual(invoice.line_items[0].unit_price_basis, "net")
        self.assertEqual(invoice.line_items[0].tax_scheme_code, "VAT")
        self.assertEqual(invoice.line_items[0].tax_category_code, "S")
        self.assertTrue(all(line.canonical_line_id for line in invoice.line_items))
        self.assertEqual(invoice.vat_summary[0].tax_scheme_code, "VAT")
        self.assertEqual(invoice.vat_summary[0].tax_category_code, "S")
        self.assertEqual(invoice.tax_components[0].component_type, "special_tax")
        self.assertEqual(invoice.tax_components[0].canonical_tax_kind, "special_communication_tax")
        self.assertEqual(invoice.monetary_components[0].source_amount, "5.00")
        self.assertEqual(invoice.totals.allowance_total, "5.00")
        self.assertEqual(invoice.totals.payable_total, "157.50")

    def test_projection_is_accounting_complete_keeps_source_links_and_warning_data(self) -> None:
        try:
            projection_module = importlib.import_module("app.domain.accounting_projection")
        except ModuleNotFoundError:
            self.fail("accounting_projection module is required")
        invoice = canonical_invoice_from_ai_payload(_gemini_payload())

        projection = projection_module.build_accounting_projection(
            invoice,
            warnings=("tax_component_classification_low_confidence",),
        )

        self.assertEqual(projection["document_direction"], "purchase")
        self.assertEqual(projection["supplier_party"]["tax_id"], "1234567890")
        self.assertEqual(projection["customer_party"]["tax_id"], "1111111111")
        self.assertEqual(len(projection["line_items"]), len(invoice.line_items))
        self.assertEqual(
            [line["canonical_line_id"] for line in projection["line_items"]],
            [line.canonical_line_id for line in invoice.line_items],
        )
        self.assertEqual(len(projection["tax_components"]), len(invoice.tax_components))
        self.assertIn("tax_scheme_code", projection["line_items"][0])
        self.assertIn("tax_category_code", projection["line_items"][0])
        self.assertIn("tax_scheme_code", projection["vat_summary"][0])
        self.assertIn("tax_category_code", projection["vat_summary"][0])
        self.assertEqual(projection["line_items"][0].get("tax_scheme_code"), "VAT")
        self.assertEqual(projection["line_items"][0].get("tax_category_code"), "S")
        self.assertEqual(projection["vat_summary"][0].get("tax_scheme_code"), "VAT")
        self.assertEqual(projection["vat_summary"][0].get("tax_category_code"), "S")
        self.assertEqual(projection["totals"]["payable_total"], invoice.totals.payable_total)
        self.assertEqual(
            projection["warnings"],
            ["tax_component_classification_low_confidence"],
        )
        linked_paths = {link["field_path"] for link in projection["source_field_links"]}
        self.assertIn("header.invoice_no", linked_paths)
        self.assertIn("line_items[0]", linked_paths)
        self.assertIn("tax_components[0]", linked_paths)
        self.assertIn("totals", linked_paths)
        self.assertNotIn("selected_account_code", repr(projection))
        self.assertNotIn("account_candidates", repr(projection))
        self.assertNotIn("selected_counterparty", repr(projection))

    def test_incomplete_observed_rows_are_preserved_with_non_blocking_warnings(self) -> None:
        payload = _gemini_payload()
        payload["line_items"].append(
            {
                "canonical_line_id": "",
                "source_position": "page:1#line:3",
                "external_line_id": "3",
                "description": "",
                "observed_quantity": "1",
                "observed_unit_code": "C62",
                "observed_unit_price": "8.00",
                "observed_unit_price_basis": "",
                "observed_taxable_amount": "8.00",
                "observed_vat_rate": "",
                "observed_tax_amount": "",
                "observed_gross_amount": "8.00",
                "tax_scheme_code": "VAT",
                "tax_category_code": "Z",
                "exemption_reason_code": "350",
                "evidence": ["$.line_items[2]"],
            }
        )
        payload["observed_vat_summary"].append(
            {
                "observed_rate": "unknown",
                "observed_taxable_amount": "8.00",
                "observed_tax_amount": "0.00",
                "tax_scheme_code": "VAT",
                "tax_category_code": "Z",
                "exemption_reason_code": "350",
                "evidence": ["$.observed_vat_summary[1]"],
            }
        )

        invoice = canonical_invoice_from_ai_payload(payload)

        self.assertEqual(len(invoice.line_items), 3)
        self.assertEqual(invoice.line_items[2].description, "")
        self.assertEqual(invoice.line_items[2].unit_price_basis, "unknown")
        self.assertEqual(invoice.line_items[2].exemption_reason_code, "350")
        self.assertEqual(len(invoice.vat_summary), 2)
        self.assertEqual(invoice.vat_summary[1].rate, "")
        self.assertEqual(invoice.vat_summary[1].taxable_amount, "8.00")
        self.assertEqual(invoice.vat_summary[1].exemption_reason_code, "350")
        self.assertIn("line_description_missing", invoice.extraction_notes)
        self.assertIn("vat_summary_rate_missing", invoice.extraction_notes)
        projection_module = importlib.import_module("app.domain.accounting_projection")
        projection = projection_module.build_accounting_projection(invoice)
        self.assertEqual(projection["line_items"][2]["tax_scheme_code"], "VAT")
        self.assertEqual(projection["line_items"][2]["tax_category_code"], "Z")
        self.assertEqual(projection["line_items"][2]["exemption_reason_code"], "350")
        self.assertEqual(projection["vat_summary"][1]["tax_scheme_code"], "VAT")
        self.assertEqual(projection["vat_summary"][1]["tax_category_code"], "Z")
        self.assertEqual(projection["vat_summary"][1]["exemption_reason_code"], "350")

    def test_unknown_component_type_is_normalized_to_other_tax(self) -> None:
        payload = _gemini_payload()
        payload["observed_tax_components"][0]["component_type"] = "invented_tax_type"
        payload["observed_tax_components"][0]["source_label"] = "Belirsiz vergi"
        payload["observed_tax_components"][0]["source_code"] = "9999"

        invoice = canonical_invoice_from_ai_payload(payload)

        self.assertEqual(invoice.tax_components[0].component_type, "other_tax")

    def test_explicit_empty_monetary_components_does_not_derive_components_from_lines(self) -> None:
        payload = _gemini_payload()
        payload["observed_monetary_components"] = []

        invoice = canonical_invoice_from_ai_payload(payload)

        self.assertEqual(invoice.monetary_components, ())

        del payload["observed_monetary_components"]
        legacy_invoice = canonical_invoice_from_ai_payload(payload)
        self.assertEqual(len(legacy_invoice.monetary_components), len(legacy_invoice.line_items))

    def test_recognized_tax_kind_overrides_conflicting_provider_component_type(self) -> None:
        payload = _gemini_payload()
        payload["observed_tax_components"] = [
            {
                "component_type": "vat",
                "source_label": "Ozel Iletisim Vergisi",
                "source_code": "4080",
                "rate": "10",
                "taxable_amount": "125.00",
                "tax_amount": "12.50",
                "source_position": "page:1#tax:OIV",
                "evidence": ["$.observed_tax_components[0]"],
            },
            {
                "component_type": "special_tax",
                "source_label": "KDV",
                "source_code": "0015",
                "rate": "20",
                "taxable_amount": "125.00",
                "tax_amount": "25.00",
                "source_position": "page:1#tax:KDV",
                "evidence": ["$.observed_tax_components[1]"],
            },
            {
                "component_type": "withholding",
                "source_label": "Belirsiz kesinti",
                "source_code": "9999",
                "rate": "2",
                "taxable_amount": "125.00",
                "tax_amount": "2.50",
                "source_position": "page:1#tax:UNKNOWN",
                "evidence": ["$.observed_tax_components[2]"],
            },
        ]

        invoice = canonical_invoice_from_ai_payload(payload)

        self.assertEqual(invoice.tax_components[0].canonical_tax_kind, "special_communication_tax")
        self.assertEqual(invoice.tax_components[0].component_type, "special_tax")
        self.assertEqual(invoice.tax_components[1].canonical_tax_kind, "vat")
        self.assertEqual(invoice.tax_components[1].component_type, "vat")
        self.assertEqual(invoice.tax_components[2].canonical_tax_kind, "unknown_non_vat_tax")
        self.assertEqual(invoice.tax_components[2].component_type, "withholding")


if __name__ == "__main__":
    unittest.main()
