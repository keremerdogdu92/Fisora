from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.workflow_store import JsonWorkflowStore
from app.workflows.synthetic_pilot import run_synthetic_pilot


class SyntheticPilotWorkflowTests(unittest.TestCase):
    def test_synthetic_pilot_runs_end_to_end_with_review_and_export_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "synthetic_pilot_store.json"
            export_csv_path = Path(temp_dir) / "synthetic_pilot_export.csv"
            summary = run_synthetic_pilot(store_path, export_csv_path)
            workspace = JsonWorkflowStore(store_path).get_workspace(summary["client_id"])
            csv_text = export_csv_path.read_text(encoding="utf-8-sig")

        self.assertEqual(summary["invoice_count"], 3)
        self.assertEqual(summary["export_ready_count"], 1)
        self.assertEqual(summary["review_required_count"], 2)
        self.assertEqual(summary["export_package_entry_count"], 1)
        self.assertEqual(summary["csv_output_path"], str(export_csv_path))
        self.assertEqual(summary["export_ready_documents"], ["pilot-rexton.pdf"])
        self.assertEqual(set(summary["excluded_document_refs"]), {"pilot-urban-care.pdf", "pilot-yeni-tedarikci.pdf"})
        self.assertIn("pilot-rexton.pdf", csv_text)
        self.assertNotIn("pilot-urban-care.pdf", csv_text)
        self.assertNotIn("pilot-yeni-tedarikci.pdf", csv_text)
        self.assertEqual(len(workspace["documents"]), 3)
        self.assertEqual(len(workspace["review_decisions"]), 2)
        self.assertEqual(len(workspace["export_packages"]), 1)


if __name__ == "__main__":
    unittest.main()
