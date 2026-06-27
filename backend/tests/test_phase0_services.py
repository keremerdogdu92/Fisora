from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.phase0_dependencies import record_operation_event
from app.api.phase0_schemas import ClientProfilePayload, ReviewDecisionPayload, StoredReviewDecisionPayload
from app.persistence.workflow_store import JsonWorkflowStore
from app.services.document_service import DocumentService
from app.services.review_service import ReviewService
from app.services.workspace_service import WorkspaceService


def allow_access(**_: object) -> dict[str, object]:
    return {"allowed": True, "reason": "test"}


def request_user_id(user_header: str | None, *_: object) -> str:
    return user_header or ""


class Phase0ServiceTests(unittest.TestCase):
    def test_workspace_service_filters_clients_by_portal_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = WorkspaceService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
                request_user_id=request_user_id,
            )
            service.store_client(ClientProfilePayload(client_id="client-1", title="Demo 1", has_chart_accounts=True))
            service.store_client(ClientProfilePayload(client_id="client-2", title="Demo 2", has_chart_accounts=True))
            store.upsert_portal_user(
                user_id="mukellef-user",
                display_name="Mukellef",
                role="client_user",
                allowed_client_ids=["client-1"],
            )

            payload = service.store_clients(
                x_fisora_user_id="mukellef-user",
                x_fisora_session=None,
                fisora_session=None,
            )

        self.assertEqual([client["client_id"] for client in payload["clients"]], ["client-1"])
        self.assertEqual(payload["auth"]["mode"], "session_or_header")

    def test_document_service_rejects_mock_user_mismatch_before_writing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.upsert_portal_user(
                user_id="mukellef-user",
                display_name="Mukellef",
                role="client_user",
                allowed_client_ids=["client-1"],
            )
            service = DocumentService(
                store=store,
                document_storage_path=Path(temp_dir) / "documents",
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            with self.assertRaises(HTTPException) as raised:
                service.store_document_upload(
                    client_id="client-1",
                    document_type="invoice",
                    file_name="fatura.pdf",
                    uploaded_by="mukellef-user",
                    uploaded_by_user_id="mukellef-user",
                    request_user_id="other-user",
                    content=b"invoice",
                )

            workspace = store.get_workspace("client-1")

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(workspace["uploaded_documents"], [])
        self.assertEqual(workspace["processing_jobs"], [])

    def test_review_service_persists_learning_event_and_operation_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            saved = service.store_review_decision(
                payload=StoredReviewDecisionPayload(
                    client_id="client-1",
                    decision=ReviewDecisionPayload(
                        document_ref="kolaysoft-1.xml",
                        action="approve_with_changes",
                        reviewer="mali-musavir",
                        corrected_account_code="770.05",
                        corrected_counterparty_code="320.01.888",
                        category="e_fatura_hizmeti",
                        reason="Bu mukellefte Kolay Soft e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(saved["decision"]["action"], "approve_with_changes")
        self.assertEqual(workspace["learning_events"][0]["client_id"], "client-1")
        self.assertEqual(workspace["operation_events"][0]["event_type"], "review_decision_saved")

    def test_review_service_persists_vat_split_review_in_learning_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={
                    "file_name": "fatura.pdf",
                    "export_status": "review_required",
                    "vat_split_review": {"status": "needs_review"},
                },
            )
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            service.store_review_decision(
                payload=StoredReviewDecisionPayload(
                    client_id="client-1",
                    decision=ReviewDecisionPayload(
                        document_ref="fatura.pdf",
                        action="approve_with_changes",
                        reviewer="mali-musavir",
                        category="vat_split_pattern",
                        reason="KDV ayrimi musavir tarafindan onaylandi.",
                        vat_split_review={
                            "schema_version": "vat_split_review.v1",
                            "status": "derived",
                            "similarity_key": "vat_split:derived:20:vat_split_gross_total_not_vat_only",
                            "lines": [{"rate": "20", "taxable_amount": "580.81", "tax_amount": "116.16"}],
                        },
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(workspace["learning_events"][0]["vat_split_review"]["status"], "derived")
        self.assertEqual(workspace["learning_events"][0]["vat_split_review"]["lines"][0]["tax_amount"], "116.16")
        self.assertIn("vat_split_review_saved", [event["step"] for event in workspace["document_pipeline_events"]])

    def test_review_service_records_journal_edit_save_and_export_pipeline_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={
                    "file_name": "fatura.pdf",
                    "export_status": "review_required",
                    "is_balanced": True,
                    "selected_expense_account": "770.01",
                    "selected_supplier_account": "320.01",
                    "counterparty_match_code": "320.01",
                    "product_category": "e_fatura_hizmeti",
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            service.store_review_decision(
                payload=StoredReviewDecisionPayload(
                    client_id="client-1",
                    decision=ReviewDecisionPayload(
                        document_ref="fatura.pdf",
                        action="approve_with_changes",
                        reviewer="mali-musavir",
                        corrected_account_code="770.05",
                        corrected_counterparty_code="320.01.888",
                        category="e_fatura_hizmeti",
                        reason="Hesap ve cari müşavir tarafından düzeltildi.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual([event["step"] for event in workspace["document_pipeline_events"]], [
            "journal_edited",
            "journal_saved",
            "export_ready",
        ])
        self.assertEqual(workspace["document_pipeline_events"][0]["message_tr"], "Müşavir muhasebe fişine müdahale etti.")
        self.assertEqual(workspace["documents"][0]["export_status"], "export_ready")


if __name__ == "__main__":
    unittest.main()
