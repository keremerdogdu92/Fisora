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


@unittest.skipUnless(
    POSTGRES_DSN,
    "set FISORA_TEST_POSTGRES_DSN to run pilot reinitialization PostgreSQL tests",
)
class PilotReinitializationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_migrations(POSTGRES_DSN, discover_migrations(BACKEND / "db" / "migrations"))

    def test_full_pilot_reinitialization_deletes_pilot_records_and_preserves_accountants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = root / "documents"
            exports = root / "exports"
            protected = root / "protected"
            tenant_key = f"pilot-reinit-{uuid4().hex}"
            client_id = f"client-{uuid4().hex}"
            store = PostgresWorkflowStore(
                POSTGRES_DSN,
                tenant_key=tenant_key,
                accounting_store_target="normalized",
            )
            store.upsert_portal_user(
                user_id="mali-musavir",
                display_name="Mali Musavir",
                role="accountant",
                allowed_client_ids=["*"],
            )
            store.upsert_portal_user(
                user_id="admin-user",
                display_name="Admin",
                role="admin",
                allowed_client_ids=["*"],
            )
            store.upsert_portal_user(
                user_id="client-user",
                display_name="Client User",
                role="client_user",
                allowed_client_ids=[client_id],
            )
            store.set_auth_password(user_id="mali-musavir", password_hash="hash-accountant")
            store.set_auth_password(user_id="admin-user", password_hash="hash-admin")
            store.set_auth_password(user_id="client-user", password_hash="hash-client")
            store.create_auth_session(
                user_id="client-user",
                token_hash="token-hash-1",
                expires_at="2099-01-01T00:00:00+00:00",
            )
            store.create_auth_token(
                purpose="invite",
                user_id="client-user",
                token_hash="token-hash-2",
                expires_at="2099-01-01T00:00:00+00:00",
            )
            store.upsert_client(
                client_id=client_id,
                profile={"client_id": client_id, "title": "Pilot Client"},
                onboarding={"is_ready": True},
            )
            store.replace_chart_accounts(
                client_id=client_id,
                accounts=[
                    {"code": "153.01", "account_name": "Stok", "is_detail_account": True},
                    {"code": "320.01", "account_name": "Satici", "is_detail_account": True},
                ],
            )
            source = documents / client_id / "invoice.xml"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"<Invoice><InvoiceLine>one</InvoiceLine></Invoice>")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            stored = store.accept_document_source(
                client_id=client_id,
                document={
                    "document_id": "invoice-1",
                    "document_type": "einvoice_xml",
                    "original_file_name": "invoice.xml",
                    "storage_path": str(source),
                    "sha256": digest,
                    "size_bytes": source.stat().st_size,
                    "status": "stored",
                    "source_qnb_status": "received",
                    "accounting_direction": "purchase",
                },
                source_channel="qnb_esolutions",
                identities=[{"kind": "ettn", "value": f"ettn-{uuid4().hex}"}],
                parser_kind="xml_invoice",
                intake_category="purchase_invoice",
            )
            store.record_qnb_incoming_status(
                client_id=client_id,
                document_ref=str(stored["document_ref"]),
                ettn=f"ettn-status-{uuid4().hex}",
                event_key=f"event-{uuid4().hex}",
                normalized_status="unknown",
                response_code="99",
                response_detail="unknown",
                cancelled_at="",
                checked_at="2026-07-27T10:00:00+00:00",
            )
            service = ProtectedCorpusService(
                store=store,
                protected_root=protected,
                document_root=documents,
                export_root=exports,
            )
            corpus = service.create_corpus(
                corpus_key="pilot-accountant-reference",
                version=1,
                target_purchase_count=1,
                target_sales_count=0,
                actor="mali-musavir",
            )
            item = service.enroll_document(
                corpus_id=corpus["corpus_id"],
                client_id=client_id,
                document_ref=str(stored["document_ref"]),
                direction="purchase",
                actor="mali-musavir",
            )
            service.capture_reference_if_enrolled(
                client_id=client_id,
                document_ref=str(stored["document_ref"]),
                saved_review={
                    "id": str(uuid4()),
                    "corrected_document": {"result": {
                        "proposal_snapshot": {"selected_account_code": "153.01", "canonical_line_count": 1},
                        "accountant_final_decision": {"selected_account_code": "153.01", "is_balanced": True},
                        "quality_delta": {"changed_fields": []},
                        "draft_lines": [
                            {"account_code": "153.01", "debit": "100.00", "credit": "0.00"},
                            {"account_code": "320.01", "debit": "0.00", "credit": "100.00"},
                        ],
                        "canonical_validation_status": "valid",
                        "line_decision_coverage": {"status": "valid", "expected_ids": ["line-1"], "received_ids": ["line-1"]},
                        "line_allocation_coverage": {"status": "valid"},
                        "line_decisions": [{"canonical_line_id": "line-1", "account_code": "153.01"}],
                        "is_balanced": True,
                        "export_status": "export_ready",
                    }},
                },
                learning_event={
                    "learning_confirmation": "save_rule",
                    "scope": "client_rule",
                    "rule_interpretation": {
                        "source": "accountant_confirmed",
                        "rule_key": f"pilot-rule-{uuid4().hex}",
                    },
                },
                actor="mali-musavir",
            )

            preview = store.preview_pilot_reinitialization()
            result = store.reinitialize_pilot_data(
                actor_user_id="mali-musavir",
                preview_fingerprint=str(preview["preview_fingerprint"]),
                document_storage_path=documents,
                export_path=exports,
                protected_storage_path=protected,
                delete_files=True,
            )
            post_preview = store.preview_pilot_reinitialization()

        self.assertEqual(len(str(preview["preview_fingerprint"])), 64)
        self.assertGreaterEqual(int(preview["operational_document_count"]), 1)
        self.assertEqual(int(preview["protected_corpus_count"]), 1)
        self.assertEqual(int(preview["protected_rule_count"]), 1)
        self.assertEqual(result["remaining_operational_document_count"], 0)
        self.assertEqual(result["remaining_protected_corpus_count"], 0)
        self.assertEqual(result["remaining_protected_rule_count"], 0)
        self.assertEqual(post_preview["operational_document_count"], 0)
        self.assertEqual(post_preview["protected_corpus_count"], 0)
        self.assertTrue(store.get_portal_user("mali-musavir"))
        self.assertTrue(store.get_portal_user("admin-user"))
        self.assertIsNone(store.get_portal_user("client-user"))
        self.assertEqual(store.get_auth_password_hash(user_id="mali-musavir"), "hash-accountant")
        self.assertEqual(store.get_auth_password_hash(user_id="admin-user"), "hash-admin")
        self.assertEqual(store.get_auth_password_hash(user_id="client-user"), "")
        self.assertEqual(store.list_clients(), [])
        self.assertFalse(source.exists())
        self.assertFalse(Path(item["protected_storage_path"]).exists())


if __name__ == "__main__":
    unittest.main()
