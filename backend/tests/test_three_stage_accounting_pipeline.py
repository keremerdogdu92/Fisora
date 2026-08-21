# File: backend/tests/test_three_stage_accounting_pipeline.py
# Summary: Verifies the Reader-planner-accountant contract and compatibility projection for accountant review.
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from app.workflows.three_stage_accounting_pipeline import (
    _compose_journal,
    run_three_stage_accounting_pipeline,
    three_stage_accounting_enabled,
)


@dataclass
class FakeAttempt:
    provider: str = "gemini"
    model_alias: str = "gemini-3.5-flash-lite"
    resolved_model: str = "gemini-3.5-flash-lite"
    status: str = "successful"
    elapsed_ms: int = 10
    http_status: int = 200
    token_usage: dict[str, int] | None = None
    credential_slot: str = "GEMINI_API_KEY_SLOT_1"

    def __post_init__(self) -> None:
        if self.token_usage is None:
            self.token_usage = {"total_tokens": 100}


class FakeResult(dict):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(payload)
        self.attempt = FakeAttempt()
class FakeReaderPlanner:
    def __init__(self, reader: dict[str, object], planner: dict[str, object]) -> None:
        self.reader = reader
        self.planner = planner
        self.calls: list[str] = []

    def generate_structured_json(self, **kwargs: object) -> FakeResult:
        name = str(kwargs.get("schema_name") or "")
        self.calls.append(name)
        return FakeResult(self.reader if "source_reconstruction" in name else self.planner)


class FakeFinalProvider:
    provider_name = "xkiro"
    model = "anthropic/claude-opus-4.8"

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def _post_structured_json(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(self.payload)


def account(code: str, name: str, tax_id: str = "") -> dict[str, object]:
    return {
        "normalized_account_code": code,
        "account_name": name,
        "tax_id": tax_id,
        "is_detail_account": True,
    }


WORKSPACE = {
    "client": {"profile": {"title": "ARİF ŞAN", "tax_id": "29021276942"}},
    "chart_accounts": {"accounts": [
        account("770.02.002", "HABERLEŞME GİDERLERİ"),
        account("770.02.003", "DİĞER ÇEŞİTLİ GİDERLER"),
        account("191.01.020", "Yüzde 20 İndirilecek KDV"),
        account("795", "VERGİ RESİM VE HARÇLAR"),
        account("329.03", "TTNET ANONIM SIRKETI", "8590491872"),
        account("120.01", "ALICILAR"),
    ]},
}
READER = {
    "document_header": [
        {"label": "FATURA NO", "value": "2026055572238"},
        {"label": "Fatura Tarih", "value": "31-05-2026"},
        {"label": "ETTN", "value": "27002d14-3114-4ad4-a190-22ed37aeec0e"},
    ],
    "principal_parties": [
        {"heading": "", "primary_name": "TTNET ANONIM SIRKETI", "detail_lines": [{"label": "VKN", "value": "8590491872"}]},
        {"heading": "", "primary_name": "ARİF ŞAN", "detail_lines": [{"label": "TCKN", "value": "29021276942"}]},
    ],
    "invoice_table_header": "Tutar İndirim Toplam",
    "invoice_table_rows": [
        {"source_position": "1", "source_text": "İnternet 1.800,01 815,01 985,00", "description": "İnternet", "ui_amount": "985,00", "ui_amount_label": "Toplam", "ui_amount_basis": "line_total_ex_tax", "ui_role": "group_or_subtotal"},
        {"source_position": "8", "source_text": "Gecikme Bedeli 23,44", "description": "Gecikme Bedeli", "ui_amount": "23,44", "ui_amount_label": "", "ui_amount_basis": "ambiguous", "ui_role": "posting_candidate"},
    ],
    "printed_summary_lines": [
        {"label": "TOPLAM FATURA TUTARI", "value": "1.150,66"},
        {"label": "Önceki Aydan Devir", "value": "0,11"},
        {"label": "Gelecek Aya Devir", "value": "-0,02"},
        {"label": "ÖDENECEK TOPLAM", "value": "1.150,75"},
        {"label": "KDV %20", "value": "178,03"},
        {"label": "ÖİV %10", "value": "80,14"},
    ],
    "note_lines": [],
}

PLANNER = {
    "accounting_direction": "purchase",
    "our_party_index": "2",
    "counterparty_name": "TTNET ANONIM SIRKETI",
    "counterparty_identifier": "8590491872",
    "counterparty_match": "exact",
    "counterparty_account_code": "329.03",
    "tax_components": [{"label": "KDV %20", "semantic_type": "vat_input"}, {"label": "ÖİV %10", "semantic_type": "non_vat_tax"}],
    "warnings": [],
}
FINAL = {
    "accounting_direction": "purchase",
    "row_decisions": [
        {"source_position": "1", "role": "business_line", "account_code": "770.02.002", "reason": "Internet service"},
        {"source_position": "8", "role": "business_line", "account_code": "770.02.003", "reason": "Late fee"},
    ],
    "operating_journal_lines": [
        {"account_code": "770.02.002", "account_name": "HABERLEŞME GİDERLERİ", "description": "İnternet hizmet bedeli", "debit": "869.05", "credit": "0", "source_positions": ["1"]},
        {"account_code": "770.02.003", "account_name": "DİĞER ÇEŞİTLİ GİDERLER", "description": "Gecikme bedeli", "debit": "23.44", "credit": "0", "source_positions": ["8"]},
        {"account_code": "191.01.020", "account_name": "KDV", "description": "KDV %20", "debit": "178.03", "credit": "0", "source_positions": []},
        {"account_code": "795", "account_name": "ÖİV", "description": "ÖİV %10", "debit": "80.14", "credit": "0", "source_positions": []},
    ],
    "counterparty_posting": {"description": "Tedarikçi borcu", "debit": "0", "credit": "1150.66", "source_positions": ["1", "8"]},
    "posting_basis_label": "TOPLAM FATURA TUTARI",
    "posting_basis_amount": "1150.66",
    "warnings": [],
    "summary": "TTNET faturası için müşavir kontrolüne hazır taslak.",
}


class ThreeStageAccountingPipelineTests(unittest.TestCase):
    def test_feature_flag_is_independent(self) -> None:
        self.assertTrue(three_stage_accounting_enabled({"FISORA_THREE_STAGE_ACCOUNTING_ENABLED": "true"}))
        self.assertFalse(three_stage_accounting_enabled({"FISORA_AI_FIRST_RESCUE_ENABLED": "true"}))

    def test_ttnet_preserves_current_invoice_basis_and_planner_owned_current(self) -> None:
        reader = FakeReaderPlanner(READER, PLANNER)
        final = FakeFinalProvider(FINAL)
        run = run_three_stage_accounting_pipeline(
            reader_provider=reader,
            final_provider=final,
            source_bytes=b"%PDF-1.7 test",
            source_sha256="abc",
            workspace=WORKSPACE,
            tenant_tax_id="29021276942",
            expected_direction="purchase",
        )
        result = run.result
        self.assertEqual(reader.calls, ["fisora_invoice_source_reconstruction_v4", "fisora_semantic_planner"])
        self.assertEqual(len(final.calls), 1)
        self.assertTrue(result["three_stage_accounting_used"])
        self.assertEqual(result["pipeline_version"], "source-identity-tax-accountant-v3")
        self.assertEqual(result["counterparty_match_code"], "329.03")
        self.assertEqual(result["payable_total"], "1150.75")
        self.assertEqual(result["vat_total"], "178.03")
        self.assertEqual(result["three_stage_posting_basis_amount"], "1150.66")
        self.assertEqual(result["total_debit"], "1150.66")
        self.assertEqual(result["total_credit"], "1150.66")
        self.assertTrue(result["is_balanced"])
        self.assertEqual(result["draft_lines"][0]["source_line_numbers"], [1])
        self.assertEqual(result["draft_lines"][1]["source_line_numbers"], [8])
        self.assertEqual(result["source_review_row_count"], 2)
        self.assertEqual(result["source_review_posting_candidate_count"], 1)
        self.assertEqual(result["source_review_rows"][1]["description"], "Gecikme Bedeli")
        self.assertEqual(result["source_review_rows"][1]["amount"], "23,44")
        self.assertIn("SATIR 1: İnternet", run.source_text)
        self.assertNotIn("new_counterparty_required", result["review_reason_codes"])

    def test_vat_summary_ignores_tax_base_labels(self) -> None:
        reader_payload = dict(READER)
        reader_payload["printed_summary_lines"] = [
            {"label": "KDV Matrahı (%0.00)", "value": "208.500,00"},
            {"label": "KDV Matrahı (%20.00)", "value": "20.225,01"},
            {"label": "Hesaplanan KDV (%20.00)", "value": "178,03"},
            {"label": "ÖDENECEK TOPLAM", "value": "1.150,75"},
        ]
        run = run_three_stage_accounting_pipeline(
            reader_provider=FakeReaderPlanner(reader_payload, PLANNER),
            final_provider=FakeFinalProvider(FINAL),
            source_bytes=b"%PDF-1.7 test",
            source_sha256="abc",
            workspace=WORKSPACE,
            tenant_tax_id="29021276942",
            expected_direction="purchase",
        )
        self.assertEqual(run.result["vat_total"], "178.03")

    def test_final_cannot_take_over_counterparty_account_selection(self) -> None:
        plan = dict(PLANNER)
        plan["counterparty_match"] = "none"
        plan["counterparty_account_code"] = ""
        bad_final = dict(FINAL)
        bad_final["operating_journal_lines"] = [
            {"account_code": "120.01", "account_name": "ALICILAR", "description": "Generic current", "debit": "100", "credit": "0", "source_positions": ["1"]},
        ]
        lines, warnings = _compose_journal(bad_final, plan, {"120.01": "ALICILAR"})
        self.assertEqual(lines[0]["account_code"], "")
        self.assertEqual(lines[-1]["account_code"], "")
        self.assertIn("operating_line_used_counterparty_family:120.01", warnings)
        self.assertIn("new_counterparty_required", warnings)

    def test_missing_row_decision_stays_visible_as_review_warning(self) -> None:
        partial_final = dict(FINAL)
        partial_final["row_decisions"] = list(FINAL["row_decisions"][:1])
        run = run_three_stage_accounting_pipeline(
            reader_provider=FakeReaderPlanner(READER, PLANNER),
            final_provider=FakeFinalProvider(partial_final),
            source_bytes=b"%PDF-1.7 test",
            source_sha256="abc",
            workspace=WORKSPACE,
            tenant_tax_id="29021276942",
            expected_direction="purchase",
        )
        self.assertIn("row_coverage_incomplete", run.result["review_reason_codes"])
        self.assertEqual(run.result["export_status"], "review_required")


    def test_final_failure_preserves_source_review_rows(self) -> None:
        class FailingFinalProvider:
            provider_name = "xkiro"
            model = "deepseek/deepseek-v4-flash"

            def _post_structured_json(self, **kwargs: object) -> dict[str, object]:
                raise ValueError("invalid structured output")

        run = run_three_stage_accounting_pipeline(
            reader_provider=FakeReaderPlanner(READER, PLANNER),
            final_provider=FailingFinalProvider(),
            source_bytes=b"%PDF-1.7 test",
            source_sha256="abc",
            workspace=WORKSPACE,
            tenant_tax_id="29021276942",
            expected_direction="purchase",
        )

        self.assertEqual(run.result["source_review_row_count"], 2)
        self.assertEqual(run.result["source_review_rows"][1]["description"], "Gecikme Bedeli")
        self.assertEqual(run.result["draft_lines"], [])
        self.assertIn("final_accountant_unavailable", run.result["review_reason_codes"])
        self.assertEqual(run.result["processing_status"], "completed")
        self.assertEqual(run.result["ai_trace"][-1]["status"], "failed")

if __name__ == "__main__":
    unittest.main()
