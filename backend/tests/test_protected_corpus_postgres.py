from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apply_migrations import apply_migrations, discover_migrations
from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.services.protected_corpus_service import ProtectedCorpusService


POSTGRES_DSN = os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip()


@unittest.skipUnless(POSTGRES_DSN, "set FISORA_TEST_POSTGRES_DSN to run protected corpus PostgreSQL tests")
class ProtectedCorpusPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_migrations(POSTGRES_DSN, discover_migrations(BACKEND / "db" / "migrations"))

    def test_reference_versions_and_rule_survive_operational_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = root / "documents"
            protected = root / "protected"
            exports = root / "exports"
            client_id = f"client-{uuid4().hex}"
            store = PostgresWorkflowStore(
                POSTGRES_DSN,
                tenant_key=f"protected-corpus-{uuid4().hex}",
                accounting_store_target="compatibility",
            )
            store.upsert_client(client_id=client_id, profile={"title": "Pilot"}, onboarding={})
            source = documents / client_id / "invoice.xml"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"<Invoice><InvoiceLine>one</InvoiceLine></Invoice>")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            store.save_uploaded_document(
                client_id=client_id,
                document={
                    "document_id": "invoice-1", "storage_path": str(source),
                    "original_file_name": "invoice.xml", "sha256": digest,
                    "size_bytes": source.stat().st_size, "status": "stored",
                    "accounting_direction": "purchase",
                },
            )
            service = ProtectedCorpusService(
                store=store, protected_root=protected,
                document_root=documents, export_root=exports,
            )
            corpus = service.create_corpus(
                corpus_key="pilot", version=1, target_purchase_count=1,
                target_sales_count=0, actor="accountant",
            )
            item = service.enroll_document(
                corpus_id=corpus["corpus_id"], client_id=client_id,
                document_ref="invoice-1", direction="purchase", actor="accountant",
            )
            saved_review = {
                "id": str(uuid4()),
                "corrected_document": {"result": {
                    "proposal_snapshot": {"selected_account_code": "770.01", "canonical_line_count": 1},
                    "accountant_final_decision": {"selected_account_code": "153.01", "is_balanced": True},
                    "quality_delta": {"changed_fields": ["selected_account_code"]},
                    "draft_lines": [
                        {"account_code": "153.01", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "debit": "0.00", "credit": "100.00"},
                    ],
                    "canonical_validation_status": "valid",
                    "line_decision_coverage": {"status": "valid", "expected_ids": ["line-1"], "received_ids": ["line-1"]},
                    "line_allocation_coverage": {"status": "valid"},
                    "line_decisions": [{"canonical_line_id": "line-1", "account_code": "153.01"}],
                    "is_balanced": True, "export_status": "export_ready",
                }},
            }
            first = service.capture_reference_if_enrolled(
                client_id=client_id, document_ref="invoice-1", saved_review=saved_review,
                learning_event={"learning_confirmation": "save_rule", "scope": "client_rule",
                                "rule_interpretation": {"source": "accountant_confirmed", "rule_key": "pilot-rule"}},
                actor="accountant",
            )
            second = service.capture_reference_if_enrolled(
                client_id=client_id, document_ref="invoice-1", saved_review=saved_review,
                learning_event={}, actor="accountant",
            )
            frozen = service.freeze_corpus(corpus["corpus_id"])

            with self.assertRaisesRegex(ValueError, "protected_reset_path_overlap"):
                store.reset_test_data(
                    document_storage_path=root,
                    export_path=exports,
                    protected_storage_path=protected,
                    delete_files=True,
                )
            self.assertIsNotNone(store.get_workspace(client_id)["client"])
            self.assertTrue(Path(item["protected_storage_path"]).is_file())

            reset = store.reset_test_data(
                document_storage_path=documents, export_path=exports,
                protected_storage_path=protected, delete_files=True,
            )

            self.assertEqual((first["version"], second["version"]), (1, 2))
            self.assertEqual(frozen["status"], "frozen")
            self.assertEqual(len(store.list_reference_outcomes(item["corpus_item_id"])), 2)
            self.assertEqual(len(store.list_protected_rules(item["corpus_item_id"])), 1)
            self.assertEqual(reset["preserved_reference_outcome_count"], 2)
            self.assertTrue(Path(item["protected_storage_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
