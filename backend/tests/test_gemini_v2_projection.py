from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_projection import build_accounting_projection  # noqa: E402
from app.domain.accounting_proposal import required_decision_refs_for_projection  # noqa: E402
from app.domain.canonical_invoices import canonical_invoice_from_ai_payload  # noqa: E402


def _canonical_payload() -> dict[str, object]:
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
        "observed_tax_components": [
            {
                "component_type": "vat",
                "source_label": "KDV",
                "source_code": "0015",
                "rate": "20",
                "taxable_amount": "100.00",
                "tax_amount": "20.00",
                "source_position": "page:1#tax:KDV",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[0]"],
            },
            {
                "component_type": "withholding",
                "source_label": "KDV tevkifati",
                "source_code": "601",
                "rate": "50",
                "taxable_amount": "20.00",
                "tax_amount": "10.00",
                "source_position": "page:1#tax:withholding",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[1]"],
            },
        ],
        "observed_monetary_components": [
            {
                "source_label": "Kampanya indirimi",
                "source_amount": "5.00",
                "source_position": "page:1#allowance:1",
                "included_in_line_net": "yes",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["$.observed_monetary_components[0]"],
            },
            {
                "source_label": "Kurulum ucreti",
                "source_amount": "8.50",
                "source_position": "page:1#charge:1",
                "included_in_line_net": "no",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["$.observed_monetary_components[1]"],
            },
        ],
        "observed_totals": {
            "observed_goods_services_total": "95.00",
            "observed_allowance_total": "5.00",
            "observed_vat_total": "20.00",
            "observed_special_tax_total": "0.00",
            "observed_tax_inclusive_total": "115.00",
            "observed_payable_total": "113.50",
            "evidence": ["$.observed_totals"],
        },
        "extraction_notes": [],
    }


class GeminiV2ProjectionTests(unittest.TestCase):
    def test_discount_and_charge_facts_preserve_amount_effect_and_inclusion(self) -> None:
        projection = build_accounting_projection(
            canonical_invoice_from_ai_payload(_canonical_payload())
        )

        components = projection["monetary_components"]
        self.assertEqual(
            [(item["source_amount"], item.get("signed_effect")) for item in components],
            [("5.00", "decrease_payable"), ("8.50", "increase_payable")],
        )
        self.assertEqual(
            [item.get("included_in_line_net") for item in components],
            ["yes", "no"],
        )
        self.assertTrue(all(item.get("component_id") for item in components))
        self.assertTrue(
            all(
                item.get("decision_ref") == f'monetary:{item.get("component_id")}'
                for item in components
            )
        )

    def test_vat_summary_and_duplicate_tax_component_share_one_accounting_identity(self) -> None:
        projection = build_accounting_projection(
            canonical_invoice_from_ai_payload(_canonical_payload())
        )

        vat_summary = projection["vat_summary"][0]
        vat_component = projection["tax_components"][0]
        self.assertEqual(vat_summary.get("decision_ref"), f'vat:{vat_summary["vat_group_id"]}')
        self.assertEqual(vat_component.get("identity_ref"), vat_summary.get("identity_ref"))
        self.assertEqual(vat_component.get("decision_ref"), vat_summary.get("decision_ref"))
        self.assertFalse(str(vat_component.get("decision_ref")).startswith("tax:"))

    def test_purchase_withholding_has_payable_reducing_credit_side_effect(self) -> None:
        projection = build_accounting_projection(
            canonical_invoice_from_ai_payload(_canonical_payload())
        )

        withholding = projection["tax_components"][1]
        self.assertEqual(withholding.get("economic_effect"), "reduce_payable")
        self.assertEqual(withholding.get("posting_side"), "credit")
        self.assertEqual(
            withholding.get("decision_ref"),
            f'tax:{withholding.get("component_id")}',
        )

    def test_unknown_legacy_inclusion_does_not_warn_or_drop_an_exactly_reconciled_fact(self) -> None:
        payload = _canonical_payload()
        payload["observed_monetary_components"][1]["included_in_line_net"] = ""
        payload["observed_monetary_components"][1]["included_in_tax_total"] = "unknown"
        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        self.assertEqual(len(projection["monetary_components"]), 2)
        retained = projection["monetary_components"][1]
        self.assertEqual(retained["source_amount"], "8.50")
        self.assertEqual(retained.get("included_in_line_net"), "unknown")
        self.assertEqual(retained.get("included_in_tax_total"), "unknown")
        self.assertEqual(retained.get("posting_requirement"), "separate")
        self.assertEqual(retained.get("payable_membership"), "yes")
        self.assertNotIn("monetary_component_inclusion_unknown", retained.get("warnings", []))
        self.assertEqual(projection["monetary_reconciliation"]["status"], "exact")

    def test_projection_emits_named_total_topology_and_exact_reconciliation(self) -> None:
        projection = build_accounting_projection(
            canonical_invoice_from_ai_payload(_canonical_payload())
        )

        self.assertEqual(projection["monetary_reconciliation"]["status"], "exact")
        self.assertEqual(projection["monetary_reconciliation"]["residual"], "0.00")
        withholding = projection["tax_components"][1]
        self.assertEqual(withholding["posting_requirement"], "separate")
        self.assertEqual(withholding["payable_membership"], "yes")

    def test_component_and_fact_refs_are_stable_across_repeated_mapping(self) -> None:
        first = build_accounting_projection(
            canonical_invoice_from_ai_payload(_canonical_payload())
        )
        second = build_accounting_projection(
            canonical_invoice_from_ai_payload(_canonical_payload())
        )

        for section in ("line_items", "vat_summary", "tax_components", "monetary_components"):
            self.assertEqual(
                [(item.get("identity_ref"), item.get("decision_ref")) for item in first[section]],
                [(item.get("identity_ref"), item.get("decision_ref")) for item in second[section]],
            )
            self.assertTrue(all(item.get("identity_ref") for item in first[section]))

    def test_component_ids_include_semantics_when_source_positions_collide(self) -> None:
        payload = _canonical_payload()
        payload["observed_tax_components"] = [
            {
                "component_type": "special_tax",
                "source_label": "Ozel Iletisim Vergisi",
                "source_code": "4080",
                "rate": "10",
                "taxable_amount": "100.00",
                "tax_amount": "10.00",
                "source_position": "page:1#tax:shared",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[0]"],
            },
            {
                "component_type": "special_tax",
                "source_label": "Telsiz Kullanim Ucreti",
                "source_code": "8006",
                "rate": "",
                "taxable_amount": "",
                "tax_amount": "3.50",
                "source_position": "page:1#tax:shared",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[1]"],
            },
        ]

        first = canonical_invoice_from_ai_payload(payload)
        reversed_payload = deepcopy(payload)
        reversed_payload["observed_tax_components"].reverse()
        second = canonical_invoice_from_ai_payload(reversed_payload)

        self.assertEqual(len({item.component_id for item in first.tax_components}), 2)
        self.assertEqual(
            {item.source_label: item.component_id for item in first.tax_components},
            {item.source_label: item.component_id for item in second.tax_components},
        )

    def test_component_ids_do_not_change_only_because_provider_order_changes(self) -> None:
        payload = _canonical_payload()
        for component in payload["observed_monetary_components"]:
            component["source_position"] = ""

        first = canonical_invoice_from_ai_payload(payload)
        reversed_payload = deepcopy(payload)
        reversed_payload["observed_monetary_components"].reverse()
        second = canonical_invoice_from_ai_payload(reversed_payload)

        self.assertEqual(
            {item.source_label: item.component_id for item in first.monetary_components},
            {item.source_label: item.component_id for item in second.monetary_components},
        )

    def test_component_ids_ignore_derived_inclusion_and_provider_classification(self) -> None:
        payload = _canonical_payload()
        first = canonical_invoice_from_ai_payload(payload)
        changed = deepcopy(payload)
        changed["observed_tax_components"][1]["component_type"] = "other_tax"
        changed["observed_tax_components"][1]["included_in_tax_total"] = "yes"
        changed["observed_tax_components"][1]["included_in_payable"] = "no"
        changed["observed_monetary_components"][1]["included_in_line_net"] = "yes"
        changed["observed_monetary_components"][1]["included_in_tax_total"] = "yes"
        changed["observed_monetary_components"][1]["included_in_payable"] = "no"
        second = canonical_invoice_from_ai_payload(changed)

        self.assertEqual(
            [item.component_id for item in first.tax_components],
            [item.component_id for item in second.tax_components],
        )
        self.assertEqual(
            [item.component_id for item in first.monetary_components],
            [item.component_id for item in second.monetary_components],
        )

    def test_period_carry_components_keep_signed_payable_effects(self) -> None:
        payload = _canonical_payload()
        payload["observed_monetary_components"] = [
            {
                "source_label": "Onceki aydan devir",
                "source_amount": "0.17",
                "source_position": "page:1#carry:previous",
                "evidence": ["$.observed_monetary_components[0]"],
            },
            {
                "source_label": "Sonraki aya devir",
                "source_amount": "-0.15",
                "source_position": "page:1#carry:next",
                "evidence": ["$.observed_monetary_components[1]"],
            },
        ]
        payload["observed_totals"]["observed_tax_inclusive_total"] = "110.02"
        payload["observed_totals"]["observed_payable_total"] = "110.02"
        payload["observed_totals"]["observed_allowance_total"] = "0.00"

        invoice = canonical_invoice_from_ai_payload(payload)

        self.assertEqual(
            [item.canonical_component_kind for item in invoice.monetary_components],
            ["prior_period_balance", "next_period_balance"],
        )
        self.assertEqual(invoice.monetary_components[0].signed_effect, "informational")
        self.assertEqual(invoice.monetary_components[0].accounting_treatment, "exclude_current_period")

        projection = build_accounting_projection(invoice)
        components = projection["monetary_components"]
        self.assertEqual(
            [item["reconciled_effect"] for item in components],
            ["increase_payable", "decrease_payable"],
        )
        self.assertEqual(
            [item["posting_requirement"] for item in components],
            ["separate", "separate"],
        )
        required_refs = required_decision_refs_for_projection(projection)
        self.assertIn(components[0]["decision_ref"], required_refs)
        self.assertIn(components[1]["decision_ref"], required_refs)

    def test_true_duplicate_facts_receive_explicit_distinct_occurrence_ids(self) -> None:
        payload = _canonical_payload()
        duplicate = deepcopy(payload["observed_monetary_components"][0])
        payload["observed_monetary_components"] = [duplicate, deepcopy(duplicate)]

        invoice = canonical_invoice_from_ai_payload(payload)

        ids = [item.component_id for item in invoice.monetary_components]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(
            [getattr(item, "occurrence_index", None) for item in invoice.monetary_components],
            [1, 2],
        )

    def test_duplicate_line_descriptions_keep_distinct_decisions_and_fact_identities(self) -> None:
        payload = _canonical_payload()
        duplicate = deepcopy(payload["line_items"][0])
        duplicate["canonical_line_id"] = ""
        duplicate["source_position"] = "page:1#line:duplicate"
        payload["line_items"].append(duplicate)

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        matching = [
            item
            for item in projection["line_items"]
            if item["description"] == payload["line_items"][0]["description"]
        ]
        self.assertEqual(len(matching), 2)
        self.assertEqual(len({item["identity_ref"] for item in matching}), 2)
        self.assertEqual(len({item["decision_ref"] for item in matching}), 2)
        self.assertTrue(all(item["decision_ref"] == item["identity_ref"] for item in matching))

    def test_provider_marked_unknown_vat_does_not_merge_with_vat_summary(self) -> None:
        payload = _canonical_payload()
        payload["observed_tax_components"] = [
            {
                "component_type": "vat",
                "source_label": "Bilinmeyen vergi",
                "source_code": "9999",
                "rate": "20",
                "taxable_amount": "100.00",
                "tax_amount": "20.00",
                "source_position": "page:1#tax:unknown",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[0]"],
            }
        ]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        component = projection["tax_components"][0]
        self.assertEqual(component.get("component_type"), "other_tax")
        self.assertEqual(component.get("canonical_tax_kind"), "unknown_non_vat_tax")
        self.assertEqual(component.get("decision_ref"), f'tax:{component.get("component_id")}')
        self.assertNotEqual(component.get("decision_ref"), projection["vat_summary"][0]["decision_ref"])

    def test_printed_hesaplanan_kdv_label_uses_vat_summary_authority(self) -> None:
        payload = _canonical_payload()
        payload["observed_tax_components"] = [
            {
                "component_type": "other_tax",
                "source_label": "Hesaplanan KDV (%20)",
                "source_code": "",
                "rate": "%20",
                "taxable_amount": "100.00",
                "tax_amount": "20.00",
                "source_position": "page:1#tax:calculated-vat",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[0]"],
            }
        ]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        component = projection["tax_components"][0]
        self.assertEqual(component["canonical_tax_kind"], "vat")
        self.assertEqual(component["component_type"], "vat")
        self.assertEqual(
            component["decision_ref"],
            projection["vat_summary"][0]["decision_ref"],
        )

    def test_aggregate_vat_component_reuses_all_per_rate_vat_authorities(self) -> None:
        payload = _canonical_payload()
        payload["observed_vat_summary"].append(
            {
                "observed_rate": "10",
                "observed_taxable_amount": "50.00",
                "observed_tax_amount": "5.00",
                "tax_scheme_code": "VAT",
                "tax_category_code": "S",
                "exemption_reason_code": "",
                "evidence": ["$.observed_vat_summary[1]"],
            }
        )
        payload["observed_tax_components"] = [
            {
                "component_type": "other_tax",
                "source_label": "KDV",
                "source_code": "0015",
                "rate": "",
                "taxable_amount": "150.00",
                "tax_amount": "25.00",
                "source_position": "page:1#tax:aggregate-vat",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[0]"],
            }
        ]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        component = projection["tax_components"][0]
        summary_refs = {item["decision_ref"] for item in projection["vat_summary"]}
        self.assertEqual(set(component.get("represented_by_refs", [])), summary_refs)
        self.assertFalse(component.get("decision_ref"))
        all_decision_refs = summary_refs | {
            item["decision_ref"]
            for item in projection["tax_components"]
            if item.get("decision_ref")
        }
        self.assertEqual(all_decision_refs, summary_refs)

    def test_vat_authority_comparison_accepts_currency_suffix_without_changing_raw_values(self) -> None:
        payload = _canonical_payload()
        payload["observed_vat_summary"][0]["observed_rate"] = "%20"
        payload["observed_vat_summary"][0]["observed_taxable_amount"] = "9.000,00 TL"
        payload["observed_vat_summary"][0]["observed_tax_amount"] = "1.800,00 TL"
        payload["observed_tax_components"] = [{
            "component_type": "vat",
            "source_label": "Hesaplanan KDV",
            "source_code": "0015",
            "rate": "20",
            "taxable_amount": "9000.00",
            "tax_amount": "1800.00",
            "source_position": "page:1#tax:vat",
            "included_in_tax_total": "yes",
            "included_in_payable": "yes",
            "evidence": ["$.observed_tax_components[0]"],
        }]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        component = projection["tax_components"][0]
        self.assertEqual(
            component["decision_ref"],
            projection["vat_summary"][0]["decision_ref"],
        )
        self.assertEqual("1800.00", component["tax_amount"])
        self.assertEqual("1.800,00 TL", projection["vat_summary"][0]["tax_amount"])

    def test_unmatched_recognized_vat_keeps_a_vat_component_authority(self) -> None:
        payload = _canonical_payload()
        payload["observed_tax_components"] = [
            {
                "component_type": "other_tax",
                "source_label": "KDV",
                "source_code": "0015",
                "rate": "8",
                "taxable_amount": "70.00",
                "tax_amount": "5.60",
                "source_position": "page:1#tax:unmatched-vat",
                "included_in_tax_total": "yes",
                "included_in_payable": "yes",
                "evidence": ["$.observed_tax_components[0]"],
            }
        ]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        component = projection["tax_components"][0]
        self.assertEqual(component.get("canonical_tax_kind"), "vat")
        self.assertEqual(component.get("decision_ref"), f'vat:{component.get("component_id")}')

    def test_withholding_is_recognized_from_labels_and_code_without_provider_authority(self) -> None:
        payload = _canonical_payload()
        base = {
            "rate": "50",
            "taxable_amount": "20.00",
            "tax_amount": "10.00",
            "included_in_tax_total": "no",
            "included_in_payable": "yes",
        }
        payload["observed_tax_components"] = [
            {
                **base,
                "component_type": "special_tax",
                "source_label": "KDV Tevkifati",
                "source_code": "",
                "source_position": "page:1#tax:tevkifat",
                "evidence": ["$.observed_tax_components[0]"],
            },
            {
                **base,
                "component_type": "vat",
                "source_label": "VAT Withholding",
                "source_code": "",
                "source_position": "page:1#tax:withholding",
                "evidence": ["$.observed_tax_components[1]"],
            },
            {
                **base,
                "component_type": "other_tax",
                "source_label": "Kesinti",
                "source_code": "9015",
                "source_position": "page:1#tax:9015",
                "evidence": ["$.observed_tax_components[2]"],
            },
        ]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        for component in projection["tax_components"]:
            with self.subTest(label=component["source_label"]):
                self.assertEqual(component.get("canonical_tax_kind"), "withholding")
                self.assertEqual(component.get("component_type"), "withholding")
                self.assertEqual(component.get("economic_effect"), "reduce_payable")
                self.assertEqual(component.get("posting_side"), "credit")

    def test_monetary_signed_effect_uses_amount_sign_without_double_inverting_discounts(self) -> None:
        payload = _canonical_payload()
        payload["observed_monetary_components"] = [
            {
                "source_label": "Kurulum ucreti",
                "source_amount": "-8.50",
                "source_position": "page:1#charge:negative",
                "included_in_line_net": "no",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["$.observed_monetary_components[0]"],
            },
            {
                "source_label": "Kampanya indirimi",
                "source_amount": "5.00",
                "source_position": "page:1#discount:positive",
                "included_in_line_net": "yes",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["$.observed_monetary_components[1]"],
            },
            {
                "source_label": "Ek indirim",
                "source_amount": "-2.00",
                "source_position": "page:1#discount:negative",
                "included_in_line_net": "yes",
                "included_in_tax_total": "no",
                "included_in_payable": "yes",
                "evidence": ["$.observed_monetary_components[2]"],
            },
        ]

        projection = build_accounting_projection(canonical_invoice_from_ai_payload(payload))

        effects = {
            item["source_label"]: item.get("signed_effect")
            for item in projection["monetary_components"]
        }
        self.assertEqual(effects["Kurulum ucreti"], "decrease_payable")
        self.assertEqual(effects["Kampanya indirimi"], "decrease_payable")
        self.assertEqual(effects["Ek indirim"], "decrease_payable")


if __name__ == "__main__":
    unittest.main()
