# File: backend/tests/test_html_source_accounting_adapter.py
# Summary: Verifies deterministic HTML snapshot projection and separate Planner/Final evidence channels.
from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.domain.html_semantic_evidence import (
    render_html_accountant_source_text,
    render_html_planner_source_text,
)
from app.workflows.html_source_processing import (
    build_html_accounting_source_package,
    html_accounting_eligibility,
    html_accounting_enabled,
)
from app.workflows.three_stage_accounting_pipeline import (
    run_prepared_source_accounting_pipeline,
)


SNAPSHOT = {
    "version": "1.0.0",
    "source": {"file": "invoice.html", "folder": None, "bytes": 321},
    "mode": "table",
    "confidence": 0.99,
    "sections": [
        {
            "kind": "table",
            "title": "Items",
            "columns": ["Description", "Amount"],
            "rows": [["Service A", "100.00"], ["Service B", "50.00"]],
        },
        {
            "kind": "key_value",
            "title": "Other",
            "columns": ["Label", "Value"],
            "rows": [["Reference", "X1"]],
        },
    ],
    "warnings": [],
    "metrics": {"sectionCount": 2, "rowCount": 3, "columnCount": 2},
}

EVIDENCE = {
    "machine_facts": [
        {"key": "no", "value": "ABC2026000000001", "source_kind": "embedded_machine_data"},
        {"key": "tarih", "value": "2026-08-28", "source_kind": "embedded_machine_data"},
        {"key": "ettn", "value": "uuid-1", "source_kind": "embedded_machine_data"},
        {"key": "odenecek", "value": "180.00", "source_kind": "embedded_machine_data"},
        {"key": "vergidahil", "value": "180.00", "source_kind": "embedded_machine_data"},
    ],
    "label_values": [
        {"label": "Hesaplanan KDV (%20)", "value": "30.00", "source_kind": "table_label_value"},
        {"label": "Odenecek Tutar", "value": "180.00", "source_kind": "table_label_value"},
    ],
    "text_lines": ["Passive note"],
    "identity_text_lines": ["SUPPLIER A.S.", "VKN: 1111111111", "CUSTOMER LTD.", "VKN: 2222222222"],
}


class FakePlannerProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def generate_structured_json(self, **kwargs: object):
        self.calls.append(dict(kwargs))
        result = dict(self.payload)
        result_obj = type("FakePlannerResult", (dict,), {})
        wrapped = result_obj(result)
        wrapped.attempt = SimpleNamespace(
            provider="gemini",
            resolved_model="gemini-test",
            model_alias="gemini-test",
            status="successful",
            elapsed_ms=1,
        )
        return wrapped


class FakeFinalProvider:
    provider_name = "xkiro"
    model = "final-test"

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def _post_structured_json(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(self.payload)


WORKSPACE = {
    "client": {"profile": {"title": "CLIENT LTD.", "tax_id": "2222222222"}},
    "chart_accounts": {"accounts": [
        {"normalized_account_code": "770.01", "account_name": "SERVICE EXPENSE", "is_detail_account": True},
        {"normalized_account_code": "191.01", "account_name": "INPUT VAT", "is_detail_account": True},
        {"normalized_account_code": "320.01", "account_name": "SUPPLIER A.S.", "tax_id": "1111111111", "is_detail_account": True},
    ]},
}

PLANNER = {
    "accounting_direction": "purchase",
    "our_party_index": "unknown",
    "counterparty_name": "SUPPLIER A.S.",
    "counterparty_identifier": "1111111111",
    "counterparty_match": "exact",
    "counterparty_account_code": "320.01",
    "tax_components": [{"label": "KDV 20", "semantic_type": "vat_input"}],
    "warnings": [],
}

FINAL = {
    "accounting_direction": "purchase",
    "row_decisions": [
        {"source_position": "1", "role": "business_line", "account_code": "770.01", "reason": "Service A"},
        {"source_position": "2", "role": "business_line", "account_code": "770.01", "reason": "Service B"},
        {"source_position": "3", "role": "non_posting_info", "account_code": "", "reason": "Reference metadata"},
    ],
    "operating_journal_lines": [
        {"account_code": "770.01", "account_name": "SERVICE EXPENSE", "description": "Services", "debit": "150.00", "credit": "0", "source_positions": ["1", "2"]},
        {"account_code": "191.01", "account_name": "INPUT VAT", "description": "VAT", "debit": "30.00", "credit": "0", "source_positions": []},
    ],
    "counterparty_posting": {"description": "Supplier payable", "debit": "0", "credit": "180.00", "source_positions": ["1", "2"]},
    "posting_basis_label": "ODENECEK TUTAR",
    "posting_basis_amount": "180.00",
    "warnings": [],
    "summary": "Prepared HTML accounting draft.",
}


class HtmlSourceAccountingAdapterTests(unittest.TestCase):
    def test_html_accounting_rollout_requires_explicit_flag(self) -> None:
        self.assertFalse(html_accounting_enabled({}))
        self.assertFalse(html_accounting_enabled({"FISORA_HTML_ACCOUNTING_ENABLED": "false"}))
        self.assertTrue(html_accounting_enabled({"FISORA_HTML_ACCOUNTING_ENABLED": "true"}))

    def test_html_accounting_eligibility_requires_rows_and_explicit_posting_basis(self) -> None:
        eligible_package = build_html_accounting_source_package(SNAPSHOT, EVIDENCE)
        eligible = html_accounting_eligibility(eligible_package)
        self.assertTrue(eligible["eligible"])
        self.assertEqual(eligible["accounting_row_count"], 3)
        self.assertTrue(eligible["posting_basis_evidence"])

        no_rows = dict(eligible_package)
        no_rows["invoice_table_rows"] = []
        self.assertEqual(
            html_accounting_eligibility(no_rows)["reasons"],
            ["no_frozen_table_rows"],
        )

        no_basis = dict(eligible_package)
        no_basis["printed_summary_lines"] = [{"label": "KDV", "value": "30.00"}]
        self.assertEqual(
            html_accounting_eligibility(no_basis)["reasons"],
            ["no_explicit_posting_basis"],
        )

        invoice_total_basis = dict(eligible_package)
        invoice_total_basis["printed_summary_lines"] = [{"label": "Fatura Tutar\u0131", "value": "180.00"}]
        self.assertTrue(html_accounting_eligibility(invoice_total_basis)["eligible"])

        generic_total_basis = dict(eligible_package)
        generic_total_basis["printed_summary_lines"] = [{"label": "Toplam Tutar", "value": "180.00"}]
        self.assertTrue(html_accounting_eligibility(generic_total_basis)["eligible"])

        goods_total_only = dict(eligible_package)
        goods_total_only["printed_summary_lines"] = [{"label": "Mal Hizmet Toplam Tutarı", "value": "150.00"}]
        self.assertEqual(
            html_accounting_eligibility(goods_total_only)["reasons"],
            ["no_explicit_posting_basis"],
        )

    def test_strips_leading_separator_from_html_label_values(self) -> None:
        evidence = {**EVIDENCE, "machine_facts": [], "label_values": [{"label": "Fatura No:", "value": ": INV-1", "source_kind": "table_label_value"}, {"label": "Odenecek Tutar", "value": ": 1.144,00 TL", "source_kind": "table_label_value"}]}
        package = build_html_accounting_source_package(SNAPSHOT, evidence)
        self.assertIn({"label": "FATURA NO", "value": "INV-1"}, package["document_header"])
        self.assertIn({"label": "Odenecek Tutar", "value": "1.144,00 TL"}, package["printed_summary_lines"])

    def test_projects_frozen_rows_to_unique_accounting_ordinals(self) -> None:
        package = build_html_accounting_source_package(SNAPSHOT, EVIDENCE)

        self.assertEqual([row["source_position"] for row in package["invoice_table_rows"]], ["1", "2", "3"])
        self.assertEqual(package["invoice_table_rows"][0]["source_text"], "[SOURCE 1:1] Service A | 100.00")
        self.assertEqual([row["ui_role"] for row in package["invoice_table_rows"]], ["posting_candidate", "posting_candidate", "informational"])
        self.assertEqual(package["document_header"][0], {"label": "FATURA NO", "value": "ABC2026000000001"})
        self.assertIn({"label": "Odenecek Tutar", "value": "180.00"}, package["printed_summary_lines"])

    def test_planner_and_accountant_receive_different_bounded_evidence_channels(self) -> None:
        planner_text = render_html_planner_source_text(EVIDENCE)
        accountant_text = render_html_accountant_source_text(SNAPSHOT, EVIDENCE)

        self.assertIn("TEXT SUPPLIER A.S.", planner_text)
        self.assertIn("TEXT VKN: 1111111111", planner_text)
        self.assertNotIn("SOURCE COLUMNS", planner_text)
        self.assertIn("SATIR 1: [SOURCE 1:1] Service A | 100.00", accountant_text)
        self.assertIn("SATIR 2: [SOURCE 1:2] Service B | 50.00", accountant_text)
        self.assertIn("SATIR 3: [SOURCE 2:1] Reference | X1", accountant_text)
        self.assertNotIn("SOURCE ROW 2:1:", accountant_text)
        self.assertNotIn("SATIR 1:1:", accountant_text)
        self.assertIn("[SOURCE section:row] is provenance only", accountant_text)

    def test_prepared_source_runner_keeps_rows_exact_and_uses_workspace_identity_fallback(self) -> None:
        package = build_html_accounting_source_package(SNAPSHOT, EVIDENCE)
        planner_text = render_html_planner_source_text(EVIDENCE)
        accountant_text = render_html_accountant_source_text(SNAPSHOT, EVIDENCE)
        planner = FakePlannerProvider(PLANNER)
        final = FakeFinalProvider(FINAL)

        run = run_prepared_source_accounting_pipeline(
            planner_provider=planner,
            final_provider=final,
            source_package=package,
            planner_source_text=planner_text,
            accountant_source_text=accountant_text,
            source_sha256="a" * 64,
            workspace=WORKSPACE,
            tenant_tax_id="2222222222",
            expected_direction="purchase",
            reader_elapsed_ms=7,
        )

        self.assertEqual(run.result["line_decision_coverage"]["status"], "valid")
        self.assertEqual(run.result["source_review_row_count"], 3)
        self.assertEqual(run.result["payable_total"], "180.00")
        self.assertTrue(run.result["is_balanced"])
        self.assertEqual(run.result["supplier_title"], "SUPPLIER A.S.")
        self.assertEqual(run.result["supplier_tax_id"], "1111111111")
        self.assertEqual(run.result["customer_title"], "CLIENT LTD.")
        self.assertEqual(run.result["customer_tax_id"], "2222222222")
        self.assertEqual(run.result["ai_trace"][0]["provider"], "prepared_source")
        self.assertIn("TEXT SUPPLIER A.S.", planner.calls[0]["user_payload"]["invoice_source_text"])
        self.assertIn("SATIR 1: [SOURCE 1:1]", final.calls[0]["user_payload"]["invoice_source_text"])


if __name__ == "__main__":
    unittest.main()
