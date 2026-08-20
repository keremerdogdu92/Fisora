# File: backend/tests/test_three_stage_stage_contracts.py
# Summary: Verifies the isolated Reader, planner, and final-accountant stage boundaries.
from __future__ import annotations

import unittest

from app.workflows.three_stage_accounting_pipeline import (
    ACCOUNTANT_INSTRUCTIONS,
    PLANNER_SCHEMA,
    run_final_accountant_stage,
    run_semantic_planner_stage,
    run_source_reader_stage,
)


class CaptureProvider:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate_structured_json(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(self.responses[str(kwargs.get("schema_name") or "")])


class CaptureFinalProvider:
    provider_name = "xkiro"
    model = "deepseek/deepseek-v4-flash"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def _post_structured_json(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(self.response)


READER_RESPONSE = {
    "document_header": [{"label": "FATURA NO", "value": "A1"}],
    "principal_parties": [],
    "invoice_table_header": "Açıklama Tutar",
    "invoice_table_rows": [{"source_position": "1", "source_text": "İnternet 100,00"}],
    "printed_summary_lines": [{"label": "TOPLAM", "value": "120,00"}],
    "note_lines": [],
}
PLANNER_RESPONSE = {
    "accounting_direction": "purchase",
    "our_party_index": "2",
    "counterparty_name": "TTNET",
    "counterparty_identifier": "8590491872",
    "counterparty_match": "exact",
    "counterparty_account_code": "329.03",
    "tax_components": [{"label": "KDV %20", "semantic_type": "vat_input"}],
    "warnings": [],
}
FINAL_RESPONSE = {
    "accounting_direction": "purchase",
    "row_decisions": [{"source_position": "1", "role": "business_line", "account_code": "770.02.002", "reason": "Internet service"}],
    "operating_journal_lines": [],
    "counterparty_posting": {"description": "TTNET borcu", "debit": "0", "credit": "120.00", "source_positions": ["1"]},
    "posting_basis_label": "TOPLAM FATURA TUTARI",
    "posting_basis_amount": "120.00",
    "warnings": [],
    "summary": "Draft ready for review.",
}


class ThreeStageStageContractTests(unittest.TestCase):
    def test_reader_sees_pdf_but_no_chart_or_accounting_context(self) -> None:
        provider = CaptureProvider({"fisora_invoice_source_reconstruction_v4": READER_RESPONSE})
        package, source_text, _, _ = run_source_reader_stage(provider=provider, source_bytes=b"%PDF-1.7 test")
        self.assertEqual(package["invoice_table_rows"][0]["source_position"], "1")
        self.assertIn("SATIR 1: İnternet 100,00", source_text)
        call = provider.calls[0]
        self.assertIn("document_bytes", call)
        self.assertEqual(call["user_payload"], {"task": "source_reconstruction_only"})
        self.assertNotIn("chart_accounts", str(call["user_payload"]))
        self.assertNotIn("current_counterparty_candidates", str(call["user_payload"]))

    def test_planner_sees_semantics_and_current_candidates_but_not_full_chart(self) -> None:
        provider = CaptureProvider({"fisora_semantic_planner": PLANNER_RESPONSE})
        plan, _, _ = run_semantic_planner_stage(
            provider=provider,
            source_text="# FATURA\nSATIR 1: İnternet 100,00\n",
            client={"title": "ARİF ŞAN", "tax_id": "29021276942"},
            current_candidates="329.03 | TTNET | tax_id=8590491872",
            expected_direction="purchase",
        )
        self.assertEqual(plan["counterparty_account_code"], "329.03")
        self.assertEqual(plan["tax_components"][0]["semantic_type"], "vat_input")
        payload = provider.calls[0]["user_payload"]
        self.assertIn("current_counterparty_candidates", payload)
        self.assertNotIn("chart_accounts", payload)

    def test_planner_has_only_minimal_tax_semantic_authority(self) -> None:
        properties = PLANNER_SCHEMA["properties"]
        self.assertNotIn("posting_basis_amount", properties)
        self.assertNotIn("posting_basis_label", properties)
        self.assertNotIn("row_plans", properties)
        self.assertIn("tax_components", properties)
        tax_properties = properties["tax_components"]["items"]["properties"]
        self.assertEqual(set(tax_properties), {"label", "semantic_type"})
        self.assertNotIn("amount", tax_properties)

    def test_final_sees_full_chart_and_plan_but_cannot_choose_counterparty_code(self) -> None:
        provider = CaptureFinalProvider(FINAL_RESPONSE)
        result, _ = run_final_accountant_stage(
            provider=provider,
            source_text="# FATURA\nSATIR 1: İnternet 100,00\n",
            semantic_plan=PLANNER_RESPONSE,
            chart_text="770.02.002 | HABERLEŞME GİDERLERİ\n329.03 | TTNET",
        )
        self.assertEqual(result["posting_basis_amount"], "120.00")
        payload = provider.calls[0]["user_payload"]
        self.assertEqual(payload["semantic_plan"]["counterparty_account_code"], "329.03")
        self.assertIn("chart_accounts", payload)
        counterparty_properties = provider.calls[0]["schema"]["properties"]["counterparty_posting"]["properties"]
        self.assertNotIn("account_code", counterparty_properties)

    def test_final_prompt_keeps_purchase_discount_as_netting_semantics(self) -> None:
        self.assertIn("journal lines do not need one posting per raw row", ACCOUNTANT_INSTRUCTIONS)
        self.assertIn("Independently determine the current-invoice posting basis", ACCOUNTANT_INSTRUCTIONS)
        self.assertIn("discount_or_reduction rows normally reduce the related purchase or expense amount", ACCOUNTANT_INSTRUCTIONS)
        self.assertIn("Do not use sales contra-revenue accounts such as 610, 611 or 612", ACCOUNTANT_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
