# File: backend/tests/test_html_accounting_worker.py
# Summary: Verifies HTML worker rollout keeps source-only behavior off-flag and runs Planner/Final on-flag.
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.workflows.document_processing import process_next_job_once
from app.workflows.html_source_processing import HTML_SOURCE_PARSER_KIND


SNAPSHOT = {
    "version": "1.0.0",
    "source": {"file": "invoice.html", "folder": None, "bytes": 200},
    "mode": "table",
    "confidence": 0.99,
    "sections": [{
        "kind": "table",
        "title": "Items",
        "columns": ["Description", "Amount"],
        "rows": [["Service A", "100.00"], ["Service B", "50.00"]],
    }],
    "warnings": [],
    "metrics": {"sectionCount": 1, "rowCount": 2, "columnCount": 2},
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
    ],
    "operating_journal_lines": [
        {"account_code": "770.01", "account_name": "SERVICE EXPENSE", "description": "Services", "debit": "150.00", "credit": "0", "source_positions": ["1", "2"]},
        {"account_code": "191.01", "account_name": "INPUT VAT", "description": "VAT", "debit": "30.00", "credit": "0", "source_positions": []},
    ],
    "counterparty_posting": {"description": "Supplier payable", "debit": "0", "credit": "180.00", "source_positions": ["1", "2"]},
    "posting_basis_label": "ODENECEK TUTAR",
    "posting_basis_amount": "180.00",
    "warnings": [],
    "summary": "HTML draft ready.",
}


class FakeHtmlReader:
    reader_version = "1.0.0"

    def read(self, path: Path):
        return {"snapshot": SNAPSHOT}


class ZeroRowHtmlReader:
    reader_version = "1.0.0"

    def read(self, path: Path):
        snapshot = dict(SNAPSHOT)
        snapshot["mode"] = "section"
        snapshot["sections"] = [{
            "kind": "key_value",
            "title": None,
            "columns": ["Label", "Value"],
            "rows": [["Service", "100.00"]],
        }]
        snapshot["metrics"] = {"sectionCount": 1, "rowCount": 1, "columnCount": 2}
        return {"snapshot": snapshot}


class FakePlannerProvider:
    provider_name = "gemini"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_structured_json(self, **kwargs: object):
        self.calls.append(dict(kwargs))
        result_type = type("FakePlannerResult", (dict,), {})
        result = result_type(PLANNER)
        result.attempt = SimpleNamespace(
            provider="gemini",
            resolved_model="gemini-test",
            model_alias="gemini-test",
            status="successful",
            elapsed_ms=1,
        )
        return result


class FakeFinalProvider:
    provider_name = "xkiro"
    model = "final-test"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def _post_structured_json(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return dict(FINAL)


class WorkerStore:
    def __init__(self, path: Path) -> None:
        self.job = {
            "id": "job-html-1",
            "client_id": "client-1",
            "document_ref": "document-html-1",
            "document_type": "invoice",
            "intake_category": "purchase_invoice",
            "parser_kind": HTML_SOURCE_PARSER_KIND,
            "attempt_count": 1,
            "normalized_attempt_id": "attempt-html-1",
        }
        self.workspace = {
            "client": {"profile": {"title": "CLIENT LTD.", "tax_id": "2222222222"}},
            "uploaded_documents": [{
                "document_ref": "document-html-1",
                "document_id": "document-html-1",
                "document_type": "invoice",
                "intake_category": "purchase_invoice",
                "original_file_name": "invoice.html",
                "storage_path": str(path),
            }],
            "chart_accounts": {"accounts": [
                {"normalized_account_code": "770.01", "account_name": "SERVICE EXPENSE", "is_detail_account": True},
                {"normalized_account_code": "191.01", "account_name": "INPUT VAT", "is_detail_account": True},
                {"normalized_account_code": "320.01", "account_name": "SUPPLIER A.S.", "tax_id": "1111111111", "is_detail_account": True},
            ]},
        }
        self.saved = None
        self.updated = None
        self.snapshots: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []

    def claim_next_processing_job(self):
        job, self.job = self.job, None
        return job

    def get_workspace(self, client_id):
        return self.workspace

    def save_document_source_snapshot(self, **kwargs):
        return {"id": "snapshot-1", "snapshot_sha256": "b" * 64}

    def update_processing_snapshot(self, **payload):
        self.snapshots.append(payload)
        return payload

    def save_simulation_result(self, *, client_id, document_ref, result, **kwargs):
        self.saved = result
        return result

    def update_processing_job(self, **payload):
        self.updated = payload
        return payload

    def record_document_pipeline_event(self, **payload):
        self.events.append(payload)


HTML = """<!doctype html><html><body>
<div>SUPPLIER A.S.</div><div>VKN: 1111111111</div>
<div>CLIENT LTD.</div><div>VKN: 2222222222</div>
<div>{\"vkntckn\":\"1111111111\",\"avkntckn\":\"2222222222\",\"tarih\":\"2026-08-28\",\"no\":\"ABC1\",\"ettn\":\"uuid-1\",\"odenecek\":\"180.00\"}</div>
<table><tr><th>Odenecek Tutar</th><td>180.00 TL</td></tr></table>
</body></html>"""


class HtmlAccountingWorkerTests(unittest.TestCase):
    def _store(self, directory: str) -> WorkerStore:
        path = Path(directory) / "invoice.html"
        path.write_text(HTML, encoding="utf-8")
        return WorkerStore(path)

    def test_flag_off_preserves_source_only_worker_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            planner = FakePlannerProvider()
            with patch.dict(os.environ, {"FISORA_HTML_ACCOUNTING_ENABLED": "false", "FISORA_THREE_STAGE_ACCOUNTING_ENABLED": "true"}, clear=False):
                summary = process_next_job_once(store, html_source_reader=FakeHtmlReader(), accounting_provider=planner)

        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertEqual(planner.calls, [])
        self.assertFalse(store.saved.get("html_accounting_used", False))
        self.assertEqual(store.saved["draft_lines"], [])
        self.assertEqual(store.updated["status"], "completed")

    def test_flag_on_still_blocks_ai_when_frozen_table_rows_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            planner = FakePlannerProvider()
            final = FakeFinalProvider()
            env = {"FISORA_HTML_ACCOUNTING_ENABLED": "true", "FISORA_THREE_STAGE_ACCOUNTING_ENABLED": "true"}
            with patch.dict(os.environ, env, clear=False), patch(
                "app.workflows.document_processing._accounting_provider_from_env",
                return_value=final,
            ):
                summary = process_next_job_once(
                    store,
                    html_source_reader=ZeroRowHtmlReader(),
                    accounting_provider=planner,
                )

        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertEqual(planner.calls, [])
        self.assertEqual(final.calls, [])
        self.assertFalse(store.saved["html_accounting_eligible"])
        self.assertFalse(store.saved["html_accounting_used"])
        self.assertIn("html_accounting_no_frozen_table_rows", store.saved["review_reason_codes"])
        self.assertTrue(any(event["step"] == "html_accounting_not_eligible" for event in store.events))

    def test_flag_on_runs_prepared_html_planner_and_final_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            planner = FakePlannerProvider()
            final = FakeFinalProvider()
            env = {"FISORA_HTML_ACCOUNTING_ENABLED": "true", "FISORA_THREE_STAGE_ACCOUNTING_ENABLED": "true"}
            with patch.dict(os.environ, env, clear=False), patch(
                "app.workflows.document_processing._accounting_provider_from_env",
                return_value=final,
            ):
                summary = process_next_job_once(
                    store,
                    html_source_reader=FakeHtmlReader(),
                    accounting_provider=planner,
                )

        self.assertEqual(summary, {"processed_count": 1, "completed_count": 1, "failed_count": 0})
        self.assertEqual(len(planner.calls), 1)
        self.assertEqual(len(final.calls), 1)
        self.assertTrue(store.saved["html_accounting_used"])
        self.assertTrue(store.saved["is_balanced"])
        self.assertEqual(store.saved["payable_total"], "180.00")
        self.assertEqual(store.saved["line_decision_coverage"]["status"], "valid")
        self.assertEqual(store.saved["source_review_row_count"], 2)
        self.assertEqual(store.saved["supplier_tax_id"], "1111111111")
        self.assertEqual(store.saved["customer_tax_id"], "2222222222")
        self.assertEqual(store.saved["canonical_validation_status"], "frozen_html_snapshot")
        self.assertFalse(store.saved["canonical_extraction_ai_used"])
        self.assertEqual(store.updated["status"], "completed")
        self.assertTrue(any(event["step"] == "html_accounting_completed" for event in store.events))
        self.assertTrue(any(snapshot["processing_snapshot"]["current_stage"] == "completed" for snapshot in store.snapshots))


if __name__ == "__main__":
    unittest.main()
