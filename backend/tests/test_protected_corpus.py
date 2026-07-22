from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from app.persistence.workflow_store import JsonWorkflowStore
from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.services.protected_corpus_service import (
    ProtectedCorpusError,
    ProtectedCorpusService,
)
from app.services.review_service import ReviewService
from app.api.phase0_schemas import ReviewDecisionPayload, StoredReviewDecisionPayload
from run_private_pipeline_benchmark import build_frozen_corpus_benchmark_input

try:
    from fastapi.testclient import TestClient

    from app.api import phase0
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None


class ProtectedCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.document_root = self.base / "documents"
        self.export_root = self.base / "exports"
        self.protected_root = self.base / "protected"
        self.store = JsonWorkflowStore(self.base / "store.json")
        self.store.upsert_client(
            client_id="client-1",
            profile={"client_id": "client-1", "title": "Client One"},
            onboarding={"is_ready": True, "missing_fields": []},
        )
        self.service = ProtectedCorpusService(
            store=self.store,
            protected_root=self.protected_root,
            document_root=self.document_root,
            export_root=self.export_root,
        )
        self.corpus = self.service.create_corpus(
            corpus_key="pilot-accountant-reference",
            version=1,
            target_purchase_count=1,
            target_sales_count=0,
            actor="mali-musavir",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _store_source(
        self,
        content: bytes = b"<Invoice>source</Invoice>",
        *,
        direction: str = "purchase",
    ) -> tuple[Path, str]:
        source = self.document_root / "client-1" / "invoice.xml"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        self.store.save_uploaded_document(
            client_id="client-1",
            document={
                "document_id": "invoice-1",
                "original_file_name": "invoice.xml",
                "storage_path": str(source),
                "size_bytes": len(content),
                "sha256": digest,
                "status": "stored",
                "accounting_direction": direction,
            },
        )
        return source, digest

    def test_enroll_document_copies_bytes_and_verifies_sha256(self) -> None:
        source, digest = self._store_source()

        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"],
            client_id="client-1",
            document_ref="invoice-1",
            direction="purchase",
            actor="mali-musavir",
        )

        protected = Path(item["protected_storage_path"])
        self.assertEqual(protected.read_bytes(), source.read_bytes())
        self.assertEqual(hashlib.sha256(protected.read_bytes()).hexdigest(), digest)
        self.assertEqual(item["source_sha256"], digest)

    def test_enroll_document_leaves_no_file_or_row_on_hash_mismatch(self) -> None:
        self._store_source()
        data = self.store._read()
        data["uploaded_documents"]["client-1:invoice-1"]["sha256"] = "0" * 64
        self.store._write(data)

        with self.assertRaisesRegex(ProtectedCorpusError, "source_hash_mismatch"):
            self.service.enroll_document(
                corpus_id=self.corpus["corpus_id"],
                client_id="client-1",
                document_ref="invoice-1",
                direction="purchase",
                actor="mali-musavir",
            )

        self.assertEqual(self.store.list_protected_items(self.corpus["corpus_id"]), [])
        self.assertEqual(list(self.protected_root.rglob("*.xml")), [])

    def test_duplicate_source_is_rejected_within_corpus(self) -> None:
        self._store_source()
        payload = {
            "corpus_id": self.corpus["corpus_id"],
            "client_id": "client-1",
            "document_ref": "invoice-1",
            "direction": "purchase",
            "actor": "mali-musavir",
        }
        self.service.enroll_document(**payload)

        with self.assertRaisesRegex(ProtectedCorpusError, "duplicate_corpus_source"):
            self.service.enroll_document(**payload)

    def test_reference_versions_are_append_only_and_only_for_enrolled_document(self) -> None:
        self._store_source()
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"],
            client_id="client-1",
            document_ref="invoice-1",
            direction="purchase",
            actor="mali-musavir",
        )
        first = self.service.capture_reference_if_enrolled(
            client_id="client-1",
            document_ref="invoice-1",
            saved_review=self._saved_review(account="770.01"),
            learning_event={},
            actor="mali-musavir",
        )
        second = self.service.capture_reference_if_enrolled(
            client_id="client-1",
            document_ref="invoice-1",
            saved_review=self._saved_review(account="153.01"),
            learning_event={},
            actor="mali-musavir",
        )

        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        versions = self.store.list_reference_outcomes(item["corpus_item_id"])
        self.assertEqual(versions[0]["accountant_final_decision"]["selected_account_code"], "770.01")
        self.assertEqual(versions[1]["accountant_final_decision"]["selected_account_code"], "153.01")
        self.assertIsNone(
            self.service.capture_reference_if_enrolled(
                client_id="client-1",
                document_ref="not-enrolled",
                saved_review=self._saved_review(account="191.01"),
                learning_event={},
                actor="mali-musavir",
            )
        )

    def test_confirmed_rule_is_snapshotted_but_unconfirmed_candidate_is_not(self) -> None:
        self._store_source()
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"],
            client_id="client-1",
            document_ref="invoice-1",
            direction="purchase",
            actor="mali-musavir",
        )
        reference = self.service.capture_reference_if_enrolled(
            client_id="client-1",
            document_ref="invoice-1",
            saved_review=self._saved_review(account="153.01"),
            learning_event={
                "learning_confirmation": "save_rule",
                "rule_interpretation": {
                    "source": "accountant_confirmed",
                    "rule_key": "cargo-expense",
                    "summary_tr": "Kargo giderlerini 760 hesabina oner.",
                },
                "scope": "client_rule",
            },
            actor="mali-musavir",
        )
        self.assertEqual(len(self.store.list_protected_rules(item["corpus_item_id"])), 1)
        self.assertEqual(reference["protected_rule"]["reference_version"], 1)

        self.service.capture_reference_if_enrolled(
            client_id="client-1",
            document_ref="invoice-1",
            saved_review=self._saved_review(account="153.01"),
            learning_event={
                "rule_interpretation": {"source": "ai", "rule_key": "candidate-only"},
                "scope": "client_rule",
            },
            actor="mali-musavir",
        )
        self.assertEqual(len(self.store.list_protected_rules(item["corpus_item_id"])), 1)

    def test_reset_preview_and_reset_preserve_protected_corpus_and_source_bytes(self) -> None:
        self._store_source()
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"],
            client_id="client-1",
            document_ref="invoice-1",
            direction="purchase",
            actor="mali-musavir",
        )
        self.service.capture_reference_if_enrolled(
            client_id="client-1",
            document_ref="invoice-1",
            saved_review=self._saved_review(account="153.01"),
            learning_event={},
            actor="mali-musavir",
        )

        preview = self.store.preview_test_data_reset()
        result = self.store.reset_test_data(
            document_storage_path=self.document_root,
            export_path=self.export_root,
            protected_storage_path=self.protected_root,
            delete_files=True,
        )

        self.assertEqual(preview["preserved_protected_corpus_count"], 1)
        self.assertEqual(preview["preserved_protected_item_count"], 1)
        self.assertEqual(result["preserved_reference_outcome_count"], 1)
        self.assertTrue(Path(item["protected_storage_path"]).is_file())
        self.assertEqual(self.store.get_workspace("client-1")["uploaded_documents"], [])

    def test_reset_overlap_fails_before_database_or_file_mutation(self) -> None:
        self._store_source()
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"], client_id="client-1",
            document_ref="invoice-1", direction="purchase", actor="mali-musavir",
        )
        before = self.store._read()

        with self.assertRaisesRegex(ValueError, "protected_reset_path_overlap"):
            self.store.reset_test_data(
                document_storage_path=self.base,
                export_path=self.export_root,
                protected_storage_path=self.protected_root,
                delete_files=True,
            )

        self.assertEqual(before, self.store._read())
        self.assertTrue(Path(item["protected_storage_path"]).is_file())

    def test_freeze_requires_exact_direction_counts_reference_and_intact_bytes(self) -> None:
        self._store_source()
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"],
            client_id="client-1",
            document_ref="invoice-1",
            direction="purchase",
            actor="mali-musavir",
        )
        with self.assertRaisesRegex(ProtectedCorpusError, "reference_not_ready"):
            self.service.freeze_corpus(self.corpus["corpus_id"])

        self.service.capture_reference_if_enrolled(
            client_id="client-1",
            document_ref="invoice-1",
            saved_review=self._saved_review(account="153.01"),
            learning_event={},
            actor="mali-musavir",
        )
        frozen = self.service.freeze_corpus(self.corpus["corpus_id"])
        self.assertEqual(frozen["status"], "frozen")
        with self.assertRaisesRegex(ValueError, "corpus_frozen"):
            self.service.capture_reference_if_enrolled(
                client_id="client-1", document_ref="invoice-1",
                saved_review=self._saved_review(account="191.01"), learning_event={}, actor="mali-musavir",
            )

        Path(item["protected_storage_path"]).write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ProtectedCorpusError, "protected_source_hash_mismatch"):
            self.service.verify_corpus_integrity(self.corpus["corpus_id"])

    def test_frozen_corpus_benchmark_input_is_read_only_and_digest_based(self) -> None:
        self._store_source()
        self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"], client_id="client-1",
            document_ref="invoice-1", direction="purchase", actor="mali-musavir",
        )
        self.service.capture_reference_if_enrolled(
            client_id="client-1", document_ref="invoice-1",
            saved_review=self._saved_review(account="153.01"), learning_event={}, actor="mali-musavir",
        )
        self.service.freeze_corpus(self.corpus["corpus_id"])
        before = self.store._read()

        benchmark_input = build_frozen_corpus_benchmark_input(self.store, self.corpus["corpus_id"])

        self.assertEqual(before, self.store._read())
        self.assertEqual(benchmark_input["corpus_id"], self.corpus["corpus_id"])
        self.assertEqual(benchmark_input["status"], "frozen")
        self.assertNotIn("protected_storage_path", benchmark_input["items"][0])
        self.assertEqual(len(benchmark_input["items"][0]["source_sha256"]), 64)

    def test_real_review_service_result_creates_authoritative_reference(self) -> None:
        self._store_source()
        self.store.save_simulation_result(
            client_id="client-1",
            document_ref="invoice-1",
            result={
                "accounting_direction": "purchase",
                "canonical_validation_status": "valid",
                "canonical_invoice": {
                    "line_items": [{
                        "canonical_line_id": "line-1", "taxable_amount": "100.00",
                        "tax_amount": "0.00", "gross_amount": "100.00", "vat_rate": "0",
                    }]
                },
                "line_decision_coverage": {
                    "status": "valid", "expected_ids": ["line-1"], "received_ids": ["line-1"]
                },
                "line_decisions": [{"canonical_line_id": "line-1", "account_code": "770.01"}],
                "draft_lines": [
                    {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                    {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "100.00"},
                ],
                "selected_expense_account": "770.01",
                "selected_supplier_account": "320.01",
                "is_balanced": True,
                "export_status": "review_required",
            },
        )
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"], client_id="client-1",
            document_ref="invoice-1", direction="purchase", actor="mali-musavir",
        )
        review_service = ReviewService(
            store=self.store,
            record_operation_event=lambda **kwargs: kwargs["store"].record_operation_event(
                client_id=kwargs["client_id"],
                event={
                    "event_type": kwargs["event_type"], "status": kwargs["status"],
                    "message": kwargs["message"], "metadata": kwargs.get("metadata") or {},
                },
            ),
            require_client_access=lambda **kwargs: {},
            protected_corpus_service=self.service,
        )

        review_service.store_review_decision(
            payload=StoredReviewDecisionPayload(
                client_id="client-1",
                decision=ReviewDecisionPayload(
                    document_ref="invoice-1", action="approve_with_changes", reviewer="mali-musavir",
                    corrected_account_code="153.01", reason="Musavir duzeltmesi",
                ),
            ),
            user_id="mali-musavir",
        )

        references = self.store.list_reference_outcomes(item["corpus_item_id"])
        self.assertEqual(len(references), 1)
        self.assertTrue(references[0]["is_authoritative"])
        self.assertEqual(references[0]["proposal_snapshot"]["canonical_line_count"], 1)

    def test_sales_review_correction_updates_revenue_and_creates_authoritative_reference(self) -> None:
        self._store_source(direction="sale")
        self.store.save_simulation_result(
            client_id="client-1", document_ref="invoice-1",
            result={
                "accounting_direction": "sales",
                "canonical_validation_status": "valid",
                "canonical_invoice": {"line_items": [{
                    "canonical_line_id": "line-1", "taxable_amount": "100.00",
                    "tax_amount": "0.00", "gross_amount": "100.00", "vat_rate": "0",
                }]},
                "line_decision_coverage": {
                    "status": "valid", "expected_ids": ["line-1"], "received_ids": ["line-1"]
                },
                "line_decisions": [{"canonical_line_id": "line-1", "account_code": "600.01"}],
                "draft_lines": [
                    {"account_code": "120.01", "description": "Alici", "debit": "100.00", "credit": "0.00"},
                    {"account_code": "600.01", "description": "Satis", "debit": "0.00", "credit": "100.00"},
                ],
                "selected_revenue_account": "600.01", "selected_customer_account": "120.01",
                "is_balanced": True, "export_status": "review_required",
            },
        )
        item = self.service.enroll_document(
            corpus_id=self.corpus["corpus_id"], client_id="client-1",
            document_ref="invoice-1", direction="sale", actor="mali-musavir",
        )
        review_service = ReviewService(
            store=self.store,
            record_operation_event=lambda **kwargs: kwargs["store"].record_operation_event(
                client_id=kwargs["client_id"], event={
                    "event_type": kwargs["event_type"], "status": kwargs["status"],
                    "message": kwargs["message"], "metadata": kwargs.get("metadata") or {},
                },
            ),
            require_client_access=lambda **kwargs: {}, protected_corpus_service=self.service,
        )
        review_service.store_review_decision(
            payload=StoredReviewDecisionPayload(
                client_id="client-1",
                decision=ReviewDecisionPayload(
                    document_ref="invoice-1", action="approve_with_changes", reviewer="mali-musavir",
                    corrected_account_code="601.01", reason="Satis hesabi duzeltmesi",
                ),
            ), user_id="mali-musavir",
        )

        reference = self.store.list_reference_outcomes(item["corpus_item_id"])[0]
        self.assertTrue(reference["is_authoritative"])
        self.assertEqual(reference["accountant_final_decision"]["selected_account_code"], "601.01")
        self.assertEqual(reference["allocation_snapshot"]["line_decisions"][0]["account_code"], "601.01")

    @staticmethod
    def _saved_review(*, account: str) -> dict[str, object]:
        return {
            "id": "review-1",
            "corrected_document": {
                "result": {
                    "proposal_snapshot": {
                        "selected_account_code": "770.01",
                        "is_balanced": True,
                        "canonical_line_count": 1,
                    },
                    "accountant_final_decision": {
                        "selected_account_code": account,
                        "is_balanced": True,
                        "action": "approve_with_changes",
                    },
                    "quality_delta": {
                        "changed_fields": [] if account == "770.01" else ["selected_account_code"]
                    },
                    "draft_lines": [
                        {"account_code": account, "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "debit": "0.00", "credit": "100.00"},
                    ],
                    "is_balanced": True,
                    "export_status": "export_ready",
                    "canonical_validation_status": "valid",
                    "line_decision_coverage": {
                        "status": "valid", "expected_ids": ["line-1"], "received_ids": ["line-1"]
                    },
                    "line_allocation_coverage": {"status": "valid"},
                    "line_decisions": [{"canonical_line_id": "line-1", "account_code": account}],
                }
            },
        }

    def test_postgres_store_binds_protected_repository_in_compatibility_mode(self) -> None:
        repository = object()

        store = PostgresWorkflowStore(
            "postgresql://unused",
            accounting_store_target="compatibility",
            protected_corpus_repository=repository,
        )

        self.assertIs(store.protected_corpus_repository, repository)

    def test_accountant_can_create_and_read_corpus_through_api(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        previous_store = phase0.DEFAULT_STORE_PATH
        previous_documents = phase0.DEFAULT_DOCUMENT_STORAGE_PATH
        previous_exports = phase0.DEFAULT_EXPORT_PATH
        previous_protected = getattr(phase0, "DEFAULT_PROTECTED_CORPUS_PATH", None)
        try:
            phase0.DEFAULT_STORE_PATH = self.base / "api-store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = self.base / "api-documents"
            phase0.DEFAULT_EXPORT_PATH = self.base / "api-exports"
            phase0.DEFAULT_PROTECTED_CORPUS_PATH = self.base / "api-protected"
            client = TestClient(app)
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["*"],
                },
            )

            created = client.post(
                "/phase0/store/corpora",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "corpus_key": "pilot-accountant-reference",
                    "version": 1,
                    "target_purchase_count": 35,
                    "target_sales_count": 15,
                },
            )
            loaded = client.get(
                f"/phase0/store/corpora/{created.json().get('corpus_id', '')}",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            reset_preview = client.get(
                "/phase0/store/admin/test-reset/preview",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            unauthenticated = client.get(
                f"/phase0/store/corpora/{created.json().get('corpus_id', '')}"
            )
        finally:
            phase0.DEFAULT_STORE_PATH = previous_store
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = previous_documents
            phase0.DEFAULT_EXPORT_PATH = previous_exports
            if previous_protected is None:
                delattr(phase0, "DEFAULT_PROTECTED_CORPUS_PATH")
            else:
                phase0.DEFAULT_PROTECTED_CORPUS_PATH = previous_protected

        self.assertEqual(created.status_code, 200)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["corpus_key"], "pilot-accountant-reference")
        self.assertEqual(reset_preview.status_code, 200)
        self.assertEqual(reset_preview.json()["preserved_protected_corpus_count"], 1)
        self.assertEqual(unauthenticated.status_code, 401)


if __name__ == "__main__":
    unittest.main()
