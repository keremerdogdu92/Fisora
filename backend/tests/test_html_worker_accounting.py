# File: backend/tests/test_html_worker_accounting.py
# Summary: Verifies HTML source-only fallback and flagged Planner/Final worker integration without invoking PDF reading.
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.workflows.document_processing import process_next_job_once


SNAPSHOT = {
    "version": "1.0.0",
    "source": {"file": "invoice.html", "folder": "", "bytes": 256},
    "mode": "table",
    "confidence": 0.99,
    "warnings": [],
    "sections": [{
        "kind": "table",
        "title": "Invoice Lines",
        "columns": ["Mal Hizmet", "Tutar"],
        "rows": [["Office service", "100.00"]],
    }],
    "metrics": {"sectionCount": 1, "rowCount": 1, "columnCount": 2},
}

HTML = b"""<!doctype html><html><body>
<div>SUPPLIER A.S.</div><div>VKN: 1111111111</div>
<div>CUSTOMER LTD.</div><div>VKN: 2222222222</div>
<div>{\"vkntckn\":\"1111111111\",\"avkntckn\":\"2222222222\",\"tarih\":\"2026-08-27\",\"no\":\"INV-1\",\"ettn\":\"uuid-1\",\"odenecek\":\"120.00\"}</div>
<table><tr><th>Odenecek Tutar:</th><td>120.00 TL</td></tr></table>
</body></html>"""


class FakeHtmlReader:
    reader_version = "1.0.0"

    def read(self, path: Path):
        return {"snapshot": SNAPSHOT}


class FakeAttempt:
    provider = "gemini"
    model_alias = "fake-planner"
    resolved_model = "fake-planner"
    status = "successful"
    elapsed_ms = 1


class FakePlannerProvider:
    provider_name = "gemini"
    def __init__(self) -> None:
        self.calls = []

    def generate_structured_json(self, **kwargs):
        self.calls.append(kwargs)
        return FakePlannerResult({
            "accounting_direction": "purchase",
            "our_party_index": "2",
            "counterparty_name": "SUPPLIER A.S.",
            "counterparty_identifier": "1111111111",
            "counterparty_match": "exact",
            "counterparty_account_code": "320.01",
            "tax_components": [{"label": "KDV", "semantic_type": "vat_input"}],
            "warnings": [],
        })


class FakePlannerResult(dict):
    attempt = FakeAttempt()


class FakeFinalProvider:
    provider_name = "xkiro"
    model = "fake-final"

    def __init__(self) -> None:
        self.calls = []

    def _post_structured_json(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "accounting_direction": "purchase",
            "row_decisions": [{
                "source_position": "1",
                "role": "business_line",
                "account_code": "770.01",
                "reason": "Office service",
            }],
            "operating_journal_lines": [
                {
                    "account_code": "770.01", "account_name": "Office Expense",
                    "description": "Office service", "debit": "100.00", "credit": "0",
                    "source_positions": ["1"],
                },
                {
                    "account_code": "191.01", "account_name": "Input VAT",
                    "description": "VAT", "debit": "20.00", "credit": "0",
                    "source_positions": [],
                },
            ],
            "counterparty_posting": {
                "description": "Supplier payable", "debit": "0", "credit": "120.00",
                "source_positions": ["1"],
            },
            "posting_basis_label": "Odenecek Tutar",
            "posting_basis_amount": "120.00",
            "warnings": [],
            "summary": "HTML draft ready.",
        }


class FakeStore:
    def __init__(self, path: Path) -> None:
        self.job = {
            "id": "job-1", "client_id": "client-1", "document_ref": "doc-1",
            "document_type": "invoice", "parser_kind": "html_source_invoice",
            "intake_category": "purchase_invoice", "attempt_count": 1,
        }
        self.document = {
            "document_ref": "doc-1", "document_id": "doc-1", "source_file_id": "src-1",
            "document_type": "invoice", "original_file_name": "invoice.html",
            "storage_path": str(path), "intake_category": "purchase_invoice",
        }
        self.workspace = {
            "client": {"client_id": "client-1", "profile": {
                "client_id": "client-1", "title": "CUSTOMER LTD.", "tax_id": "2222222222",
            }},
            "uploaded_documents": [self.document],
            "chart_accounts": {"accounts": [
                {"normalized_account_code": "770.01", "account_name": "Office Expense", "is_detail_account": True},
                {"normalized_account_code": "191.01", "account_name": "Input VAT", "is_detail_account": True},
                {"normalized_account_code": "320.01", "account_name": "SUPPLIER A.S.", "tax_id": "1111111111", "is_detail_account": True},
            ]},
        }
        self.saved = None
        self.updated = None
        self.snapshots = []
        self.events = []
        self.processing_snapshots = []
        self.ai_usage = []
    def claim_next_processing_job(self):
        job, self.job = self.job, None
        return job

    def get_workspace(self, client_id):
        return self.workspace

    def save_document_source_snapshot(self, **kwargs):
        self.snapshots.append(kwargs)
        return {"id": "snap-1", "snapshot_sha256": "a" * 64}

    def update_processing_snapshot(self, **kwargs):
        self.processing_snapshots.append(kwargs)
        return kwargs

    def save_simulation_result(self, *, client_id, document_ref, result, **kwargs):
        self.saved = result
        return result

    def update_processing_job(self, **kwargs):
        self.updated = kwargs
        return kwargs

    def record_document_pipeline_event(self, **kwargs):
        self.events.append(kwargs)

    def record_ai_usage(self, *, client_id, event):
        self.ai_usage.append((client_id, event))

    def record_ai_capacity_snapshot(self, **kwargs):
        return kwargs


class HtmlWorkerAccountingTests(unittest.TestCase):
    def _run(self, *, enabled: bool):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "invoice.html"
        path.write_bytes(HTML)
        store = FakeStore(path)
        planner = FakePlannerProvider()
        final = FakeFinalProvider()
        env = {
            "FISORA_HTML_ACCOUNTING_ENABLED": "true" if enabled else "false",
            "FISORA_THREE_STAGE_ACCOUNTING_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "app.workflows.document_processing._accounting_provider_from_env",
            return_value=final,
        ):
            summary = process_next_job_once(
                store,
                extraction_provider=planner,
                accounting_provider=planner,
                html_source_reader=FakeHtmlReader(),
            )
        return summary, store, planner, final

    def test_flag_off_preserves_source_only_behavior(self) -> None:
        summary, store, planner, final = self._run(enabled=False)
        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertFalse(bool(store.saved.get("html_accounting_used")))
        self.assertEqual(store.saved["draft_status"], "manual_draft_required")
        self.assertEqual(planner.calls, [])
        self.assertEqual(final.calls, [])
    def test_flag_on_runs_planner_final_and_persists_balanced_draft(self) -> None:
        summary, store, planner, final = self._run(enabled=True)
        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertTrue(store.saved["html_accounting_used"])
        self.assertTrue(store.saved["html_accounting_eligible"])
        self.assertTrue(store.saved["is_balanced"])
        self.assertEqual(store.saved["line_decision_coverage"]["status"], "valid")
        self.assertEqual(store.saved["counterparty_tax_id"], "1111111111")
        self.assertEqual(store.saved["payable_total"], "120.00")
        self.assertGreaterEqual(len(planner.calls), 1)
        self.assertGreaterEqual(len(final.calls), 1)
        self.assertEqual(store.updated["status"], "completed")
        self.assertTrue(any(item["step"] == "html_accounting_completed" for item in store.events))


if __name__ == "__main__":
    unittest.main()
