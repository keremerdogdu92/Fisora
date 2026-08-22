# File: backend/tests/test_phase0_services.py
# Summary: Verifies phase0 workspace, document, review, export, access, and progressive processing services.
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
from app.api.phase0_schemas import ClientProfilePayload, ReviewDecisionPayload, ReviewRulePreviewPayload, StoredReviewDecisionPayload, WorkspaceExportPackagePayload
from app.persistence.workflow_store import JsonWorkflowStore
from app.services.document_service import DocumentService
from app.services.export_service import ExportService
from app.services.review_service import ReviewService
from app.services.workspace_service import WorkspaceService, compact_workspace_payload, review_workspace_payload


def allow_access(**_: object) -> dict[str, object]:
    return {"allowed": True, "reason": "test"}


def request_user_id(user_header: str | None, *_: object) -> str:
    return user_header or ""


class FakeRuleInterpreter:
    provider_name = "fake_rule_ai"

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def interpret_review_rule(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        return {
            "status": "ready",
            "summary_tr": "Bu mükellefte Yurtiçi Kargo faturaları kargo gideri olarak önerilecek.",
            "trigger_tr": "VKN 9860008925 / Yurtiçi Kargo alış faturası",
            "action_tr": "Gider hesabı 760.03.010, cari 320.9860008925.",
            "guardrail_tr": "İlk uygulamalarda müşavir kontrolü istenir.",
            "confidence": 91,
            "reason_codes": ["counterparty_tax_id_rule", "expense_account_rule"],
        }


class Phase0ServiceTests(unittest.TestCase):
    def test_compact_workspace_payload_strips_heavy_history_for_summary_views(self) -> None:
        workspace = {
            "client": {"client_id": "client-1", "profile": {"title": "Demo"}},
            "chart_accounts": {
                "account_count": 582,
                "accounts": [
                    {"normalized_account_code": "770.01", "account_name": "Genel gider"},
                    {"normalized_account_code": "320.01", "account_name": "Satici"},
                ],
            },
            "documents": [
                {
                    "document_ref": "doc-1",
                    "export_status": "review_required",
                    "created_at": "2026-07-09T10:00:00Z",
                    "result": {
                        "file_name": "alis.pdf",
                        "invoice_type": "ALIS",
                        "provider_hint": "Yurtici Kargo",
                        "payable_total": "120.00",
                        "draft_lines": [{"account_code": "770.01"}],
                        "technical_details": {"ai_trace": [{"large": "payload"}]},
                        "ai_stage_evidence": [{"large": "payload"}],
                        "account_candidates": {"purchase_expense": [{"code": "770.01"}]},
                        "rule_prompt": {"show": True},
                    },
                }
            ],
            "document_pipeline_events": [{"document_ref": "doc-1", "step": "uploaded"}],
            "operation_events": [{"event_type": "one"}, {"event_type": "two"}],
        }

        compact = compact_workspace_payload(workspace)

        self.assertEqual(compact["chart_accounts"], {"account_count": 582, "accounts": []})
        self.assertEqual(compact["document_pipeline_events"], [])
        self.assertEqual(compact["operation_events"], [{"event_type": "two"}, {"event_type": "one"}])
        result = compact["documents"][0]["result"]
        self.assertEqual(result["file_name"], "alis.pdf")
        self.assertEqual(result["rule_prompt"], {"show": True})
        self.assertNotIn("technical_details", result)
        self.assertNotIn("ai_stage_evidence", result)
        self.assertEqual(result["account_candidates"], {"purchase_expense": [{"code": "770.01"}]})
        self.assertEqual(result["draft_lines"], [{"account_code": "770.01"}])

    def test_review_workspace_payload_keeps_selectable_chart_accounts_without_heavy_history(self) -> None:
        workspace = {
            "chart_accounts": {
                "account_count": 2,
                "accounts": [
                    {
                        "normalized_account_code": "153.01.001",
                        "raw_account_code": "153.01.001",
                        "account_name": "ALINAN CİHAZLAR",
                        "is_detail_account": True,
                        "tax_id": "1234567890",
                        "tax_office": "Kadıköy",
                        "iban": "TR0001",
                        "unused_private_field": "drop-me",
                    },
                    {
                        "normalized_account_code": "191.01.020",
                        "account_name": "Yüzde20 Hesaplanan Kdv",
                        "is_detail_account": True,
                    },
                ],
            },
            "documents": [],
            "uploaded_documents": [],
            "processing_jobs": [],
            "review_decisions": [],
            "learning_events": [],
            "document_pipeline_events": [{"document_ref": "doc-1", "step": "uploaded"}],
            "operation_events": [{"event_type": "one"}],
        }

        review = review_workspace_payload(workspace)

        self.assertEqual(review["chart_accounts"]["account_count"], 2)
        self.assertEqual(
            review["chart_accounts"]["accounts"][0],
            {
                "normalized_account_code": "153.01.001",
                "raw_account_code": "153.01.001",
                "account_name": "ALINAN CİHAZLAR",
                "is_detail_account": True,
                "tax_id": "1234567890",
                "tax_office": "Kadıköy",
                "iban": "TR0001",
            },
        )
        self.assertEqual(review["document_pipeline_events"], [])

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

    def test_workspace_service_researches_and_caches_nace_when_storing_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            calls: list[str] = []

            def researcher(nace_code: str) -> dict[str, object]:
                calls.append(nace_code)
                return {
                    "activity_title": "Tütün ürünleri perakende ticareti",
                    "scope_summary": "Tekel bayi faaliyetinde içecek, gıda ve tütün ürünü alımları stokla ilişkilidir.",
                    "included_goods_services": ["sigara", "içecek", "gıda"],
                    "likely_business_expenses": ["kira", "pos komisyonu"],
                    "unlikely_or_personal_items": ["kişisel giyim"],
                    "bank_statement_hints": ["tedarikçi ödemesi"],
                    "activity_tags": ["retail_trade", "food_service"],
                    "source_urls": ["https://example.test/nace-472601"],
                }

            service = WorkspaceService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
                request_user_id=request_user_id,
                nace_researcher=researcher,
            )

            saved = service.store_client(
                ClientProfilePayload(
                    client_id="client-1",
                    title="Bünyamin Aktar",
                    tax_id="10649861252",
                    nace_code="47.26.01",
                    workplace_addresses=["İstanbul"],
                    has_chart_accounts=False,
                )
            )
            cached = store.get_nace_research_profile("472601")

        profile = saved["profile"]
        self.assertEqual(calls, ["472601"])
        self.assertEqual(profile["activity_tags"], ["retail_trade", "food_service"])
        self.assertEqual(
            profile["nace_research_profile"]["scope_summary"],
            "Tekel bayi faaliyetinde içecek, gıda ve tütün ürünü alımları stokla ilişkilidir.",
        )
        self.assertEqual(cached["activity_tags"], ["retail_trade", "food_service"])

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

    def test_review_service_rejects_manual_draft_line_outside_chart_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                    {"raw_account_code": "320.01", "normalized_account_code": "320.01", "account_name": "Satici cari", "is_detail_account": True},
                ],
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={"file_name": "fatura.pdf", "export_status": "review_required", "draft_lines": []},
            )
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            with self.assertRaises(HTTPException) as raised:
                service.store_review_decision(
                    payload=StoredReviewDecisionPayload(
                        client_id="client-1",
                        decision=ReviewDecisionPayload(
                            document_ref="fatura.pdf",
                            action="approve_with_changes",
                            reviewer="mali-musavir",
                            draft_lines=[
                                {"account_code": "770.99", "description": "Serbest gider", "debit": "100.00", "credit": "0.00"},
                                {"account_code": "320.01", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                            ],
                        ),
                    ),
                    user_id="mali-musavir",
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("770.99", str(raised.exception.detail))

    def test_review_service_canonicalizes_manual_draft_descriptions_from_chart_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                    {"raw_account_code": "320.01", "normalized_account_code": "320.01", "account_name": "Satici cari", "is_detail_account": True},
                ],
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={"file_name": "fatura.pdf", "export_status": "review_required", "draft_lines": []},
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
                        draft_lines=[
                            {"account_code": "770.01", "description": "Elle yazilan gider", "debit": "100.00", "credit": "0.00"},
                            {"account_code": "320.01", "description": "Elle yazilan cari", "debit": "0.00", "credit": "100.00"},
                        ],
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(
            [line["description"] for line in workspace["documents"][0]["result"]["draft_lines"]],
            ["Genel gider", "Satici cari"],
        )

    def test_review_service_rejects_header_accounts_even_when_in_chart_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770", "normalized_account_code": "770", "account_name": "Genel Yonetim Giderleri", "is_detail_account": False},
                    {"raw_account_code": "320.01", "normalized_account_code": "320.01", "account_name": "Satici cari", "is_detail_account": True},
                ],
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={"file_name": "fatura.pdf", "export_status": "review_required", "draft_lines": []},
            )
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            with self.assertRaises(HTTPException) as raised:
                service.store_review_decision(
                    payload=StoredReviewDecisionPayload(
                        client_id="client-1",
                        decision=ReviewDecisionPayload(
                            document_ref="fatura.pdf",
                            action="approve_with_changes",
                            reviewer="mali-musavir",
                            draft_lines=[
                                {"account_code": "770", "description": "Header", "debit": "100.00", "credit": "0.00"},
                                {"account_code": "320.01", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                            ],
                        ),
                    ),
                    user_id="mali-musavir",
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("770", str(raised.exception.detail))

    def test_review_service_allows_system_suggested_new_counterparty_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                ],
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={
                    "file_name": "fatura.pdf",
                    "export_status": "review_required",
                    "draft_lines": [],
                    "suggested_counterparty_account": "320.A01",
                    "selected_supplier_account": "320.A01",
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
                        draft_lines=[
                            {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                            {"account_code": "320.A01", "description": "Yeni cari", "debit": "0.00", "credit": "100.00"},
                        ],
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(workspace["documents"][0]["result"]["draft_lines"][1]["account_code"], "320.A01")

    def test_review_service_rejects_free_typed_counterparty_account_without_new_counterparty_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                ],
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="fatura.pdf",
                result={"file_name": "fatura.pdf", "export_status": "review_required", "draft_lines": []},
            )
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            with self.assertRaises(HTTPException) as raised:
                service.store_review_decision(
                    payload=StoredReviewDecisionPayload(
                        client_id="client-1",
                        decision=ReviewDecisionPayload(
                            document_ref="fatura.pdf",
                            action="approve_with_changes",
                            reviewer="mali-musavir",
                            draft_lines=[
                                {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                                {"account_code": "320.A99", "description": "Serbest yeni cari", "debit": "0.00", "credit": "100.00"},
                            ],
                        ),
                    ),
                    user_id="mali-musavir",
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("320.A99", str(raised.exception.detail))

    def test_export_package_exposes_zirve_mapping_field_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="ready.pdf",
                result={
                    "file_name": "ready.pdf",
                    "export_status": "export_ready",
                    "review_reason_codes": [],
                    "risk_flags": [],
                    "issue_date": "2026-07-01",
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "description": "Tedarikci", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )
            service = ExportService(
                store=store,
                export_path=Path(temp_dir) / "exports",
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            saved = service.store_export_package_from_workspace(
                payload=WorkspaceExportPackagePayload(client_id="client-1", export_type="zirve_mapping_csv"),
                user_id="mali-musavir",
            )

        adapter = saved["package"]["adapter"]
        self.assertEqual(adapter["validation_status"], "field_test_pending")
        self.assertFalse(adapter["verified_in_zirve"])
        self.assertTrue(any("manual column mapping" in note.lower() for note in adapter["field_mapping_notes"]))

    def test_export_download_blocks_package_containing_reprocessed_approved_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export_root = Path(temp_dir) / "exports"
            output_path = export_root / "client-1" / "old.csv"
            output_path.parent.mkdir(parents=True)
            output_path.write_text("old export", encoding="utf-8")
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.save_export_package(
                client_id="client-1",
                package={
                    "output_filename": "old.csv",
                    "entries": [{"document_ref": "approved.pdf"}],
                },
            )
            store.reprocess_review_required_document_refs = (
                lambda *, client_id, document_refs: ["approved.pdf"]
            )
            service = ExportService(
                store=store,
                export_path=export_root,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            with self.assertRaises(HTTPException) as raised:
                service.export_download_path(
                    client_id="client-1",
                    file_name="old.csv",
                    user_id="mali-musavir",
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            {
                "reason": "normalized_reprocess_review_required",
                "document_refs": ["approved.pdf"],
            },
        )

    def test_review_decision_payload_normalizes_decision_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            event = service.review_learning_event(
                ReviewDecisionPayload(
                    document_ref="fuel.pdf",
                    action="approve_with_changes",
                    reviewer="mali-musavir",
                    decision_note="Fuel vendor should stay in review until vehicle rule is learned.",
                    apply_to_similar=True,
                )
            )

        self.assertEqual(event["accountant_note"], "Fuel vendor should stay in review until vehicle rule is learned.")
        self.assertEqual(event["rule_instruction"], "Fuel vendor should stay in review until vehicle rule is learned.")

    def test_review_decision_payload_preserves_legacy_note_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            event = service.review_learning_event(
                ReviewDecisionPayload(
                    document_ref="legacy.pdf",
                    action="approve_with_changes",
                    reviewer="mali-musavir",
                    accountant_note="Accountant rationale",
                    rule_instruction="Learning rule text",
                    apply_to_similar=True,
                )
            )

        self.assertEqual(event["accountant_note"], "Accountant rationale")
        self.assertEqual(event["rule_instruction"], "Learning rule text")

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

    def test_review_service_stores_accountant_note_rule_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="rexton.pdf",
                result={
                    "file_name": "rexton.pdf",
                    "export_status": "review_required",
                    "product_line_hint": "Rexton RLi 20",
                    "product_category": "bilinmeyen",
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
                        document_ref="rexton.pdf",
                        action="approve_with_changes",
                        reviewer="mali-musavir",
                        corrected_account_code="153.01",
                        category="",
                        reason="Fişi bu hesapla kaydettim.",
                        accountant_note="Rexton RLi 20 isitme cihazidir, stok olarak izleyelim.",
                        rule_instruction="Benzer Rexton RLi 20 satirlarinda aday kural olarak oner.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        candidate = workspace["learning_events"][0]["natural_language_rule_candidate"]
        self.assertEqual(candidate["scope"], "global_product_phrase")
        self.assertEqual(candidate["match_phrase"], "rexton rli 20")
        self.assertEqual(candidate["suggested_account_code"], "153.01")
        self.assertTrue(candidate["requires_review"])

    def test_review_service_records_ai_rule_interpretation_for_accountant_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="kargo.xml",
                result={
                    "file_name": "kargo.xml",
                    "export_status": "review_required",
                    "is_balanced": True,
                    "accounting_direction": "purchase",
                    "selected_expense_account": "760.03.010",
                    "selected_supplier_account": "320.9860008925",
                    "counterparty_tax_id": "9860008925",
                    "counterparty_title": "Yurtiçi Kargo Servisi A.Ş.",
                    "product_line_hint": "Posta Hizmet Geliri",
                    "product_category": "kargo",
                    "draft_lines": [
                        {"account_code": "760.03.010", "description": "Kargo", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.9860008925", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )
            interpreter = FakeRuleInterpreter()
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
                rule_interpreter=interpreter,
            )

            service.store_review_decision(
                payload=StoredReviewDecisionPayload(
                    client_id="client-1",
                    decision=ReviewDecisionPayload(
                        document_ref="kargo.xml",
                        action="suggest_for_similar",
                        reviewer="mali-musavir",
                        category="kargo",
                        reason="Kargo gideri olarak kaydettim.",
                        accountant_note="Bundan sonra bu vergi numarası ile gelen faturaları kargo gideri olarak işle.",
                        rule_instruction="Bundan sonra bu vergi numarası ile gelen faturaları kargo gideri olarak işle.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        interpretation = workspace["learning_events"][0]["rule_interpretation"]
        document_interpretation = workspace["documents"][0]["result"]["rule_interpretation"]
        self.assertEqual(interpretation["source"], "ai")
        self.assertEqual(interpretation["provider"], "fake_rule_ai")
        self.assertEqual(interpretation["status"], "ready")
        self.assertIn("Yurtiçi Kargo", interpretation["summary_tr"])
        self.assertEqual(document_interpretation["summary_tr"], interpretation["summary_tr"])
        self.assertEqual(interpreter.requests[0]["candidate"]["suggested_account_code"], "760.03.010")

    def test_review_service_records_learning_pipeline_events_for_rule_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="kargo.xml",
                result={
                    "file_name": "kargo.xml",
                    "export_status": "review_required",
                    "is_balanced": True,
                    "accounting_direction": "purchase",
                    "selected_expense_account": "760.03.010",
                    "selected_supplier_account": "320.9860008925",
                    "counterparty_tax_id": "9860008925",
                    "counterparty_title": "Yurtici Kargo",
                    "product_line_hint": "Kargo hizmeti",
                    "product_category": "kargo",
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
                        document_ref="kargo.xml",
                        action="suggest_for_similar",
                        reviewer="mali-musavir",
                        corrected_account_code="760.03.010",
                        category="kargo",
                        decision_note="Bundan sonra bu VKN'den gelen faturalar kargo gideridir.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        learning_events = [event for event in workspace["document_pipeline_events"] if event["step"].startswith("learning_")]
        self.assertEqual([event["step"] for event in learning_events], ["learning_candidate_built", "learning_rule_interpreted"])
        candidate_details = learning_events[0]["details"]
        self.assertEqual(candidate_details["scope"], "client_counterparty")
        self.assertEqual(candidate_details["action"], "suggest_for_similar")
        self.assertEqual(candidate_details["suggested_account_code"], "760.03.010")
        interpreted_details = learning_events[1]["details"]
        self.assertEqual(interpreted_details["reason_codes"], ["counterparty_tax_id_rule", "account_rule"])
        self.assertIn("760.03.010", interpreted_details["applied_effect_tr"])

    def test_review_service_records_deterministic_rule_interpretation_without_ai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="dogalgaz.xml",
                result={
                    "file_name": "dogalgaz.xml",
                    "export_status": "review_required",
                    "is_balanced": True,
                    "accounting_direction": "purchase",
                    "selected_expense_account": "770.02.003",
                    "selected_supplier_account": "320.4700022607",
                    "counterparty_tax_id": "4700022607",
                    "counterparty_title": "İstanbul Gaz Dağıtım Sanayi ve Ticaret A.Ş.",
                    "product_line_hint": "Toplam Tüketim Bedeli",
                    "product_category": "dogalgaz",
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
                        document_ref="dogalgaz.xml",
                        action="suggest_for_similar",
                        reviewer="mali-musavir",
                        category="dogalgaz",
                        reason="Doğalgaz gideri olarak kaydettim.",
                        accountant_note="Bundan sonra bu vergi numarası ile gelen faturaları doğalgaz gideri olarak işle.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        interpretation = workspace["learning_events"][0]["rule_interpretation"]
        document_interpretation = workspace["documents"][0]["result"]["rule_interpretation"]
        self.assertEqual(interpretation["source"], "deterministic")
        self.assertEqual(interpretation["status"], "ready")
        self.assertIn("4700022607", interpretation["summary_tr"])
        self.assertIn("770.02.003", interpretation["action_tr"])
        self.assertEqual(document_interpretation["action_tr"], interpretation["action_tr"])

    def test_review_rule_preview_returns_interpretation_without_persisting_learning_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="kargo.xml",
                result={
                    "file_name": "kargo.xml",
                    "export_status": "review_required",
                    "is_balanced": True,
                    "accounting_direction": "purchase",
                    "selected_expense_account": "770.01",
                    "selected_supplier_account": "320.01",
                    "counterparty_tax_id": "9860008925",
                    "counterparty_title": "Yurtici Kargo",
                    "product_line_hint": "Kargo hizmeti",
                    "product_category": "kargo",
                },
            )
            service = ReviewService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
            )

            preview = service.preview_review_rule(
                payload=ReviewRulePreviewPayload(
                    client_id="client-1",
                    decision=ReviewDecisionPayload(
                        document_ref="kargo.xml",
                        action="suggest_for_similar",
                        reviewer="mali-musavir",
                        corrected_account_code="760.03.010",
                        category="kargo",
                        decision_note="Bundan sonra bu VKN'den gelen faturalar kargo gideridir.",
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        self.assertEqual(preview["rule_interpretation"]["status"], "ready")
        self.assertEqual(preview["natural_language_rule_candidate"]["suggested_account_code"], "760.03.010")
        self.assertEqual(workspace["learning_events"], [])

    def test_confirmed_rule_interpretation_is_persisted_on_learning_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            store.upsert_client(client_id="client-1", profile={"client_id": "client-1"}, onboarding={"is_ready": True})
            store.save_simulation_result(
                client_id="client-1",
                document_ref="kargo.xml",
                result={
                    "file_name": "kargo.xml",
                    "export_status": "review_required",
                    "is_balanced": True,
                    "accounting_direction": "purchase",
                    "selected_expense_account": "760.03.010",
                    "selected_supplier_account": "320.01",
                    "counterparty_tax_id": "9860008925",
                    "counterparty_title": "Yurtici Kargo",
                    "product_line_hint": "Kargo hizmeti",
                    "product_category": "kargo",
                    "draft_lines": [
                        {"account_code": "760.03.010", "description": "Kargo", "debit": "100.00", "credit": "0.00"},
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
                        document_ref="kargo.xml",
                        action="suggest_for_similar",
                        reviewer="mali-musavir",
                        corrected_account_code="760.03.010",
                        category="kargo",
                        decision_note="Bundan sonra bu VKN'den gelen faturalar kargo gideridir.",
                        learning_confirmation="suggest_similar",
                        confirmed_rule_interpretation={
                            "status": "ready",
                            "summary_tr": "Yurtici Kargo faturalari kargo gideri onerisi olacak.",
                            "trigger_tr": "VKN 9860008925 / alis faturasi",
                            "action_tr": "Hesap 760.03.010 onerilecek.",
                            "guardrail_tr": "Ilk uygulamalarda musavir kontrolu istenir.",
                            "confidence": 88,
                            "reason_codes": ["account_rule"],
                        },
                    ),
                ),
                user_id="mali-musavir",
            )
            workspace = store.get_workspace("client-1")

        event = workspace["learning_events"][0]
        self.assertEqual(event["learning_confirmation"], "suggest_similar")
        self.assertEqual(event["rule_interpretation"]["summary_tr"], "Yurtici Kargo faturalari kargo gideri onerisi olacak.")

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


class ProgressiveProcessingServiceTests(unittest.TestCase):
    def test_selected_document_progress_exposes_latest_job_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            service = WorkspaceService(
                store=store,
                record_operation_event=record_operation_event,
                require_client_access=allow_access,
                request_user_id=request_user_id,
            )
            job = store.create_processing_job(
                client_id="client-1",
                document_ref="doc-1",
                document_type="invoice",
                parser_kind="gemini_pdf_v2",
                intake_category="purchase_invoice",
            )
            claimed = store.claim_next_processing_job()
            self.assertIsNotNone(claimed)
            snapshot = {
                "attempt_count": 1,
                "current_stage": "planner",
                "stages": {
                    "reader": {"status": "completed", "elapsed_ms": 5000},
                    "planner": {"status": "processing", "elapsed_ms": 0},
                    "final": {"status": "pending", "elapsed_ms": 0},
                },
                "reader": {"invoice_table_rows": [{"source_position": "1"}]},
            }
            updated = store.update_processing_snapshot(
                job_id=job["id"], processing_snapshot=snapshot, attempt_count=1,
            )
            self.assertIsNotNone(updated)
            progress = service.document_processing_progress(
                client_id="client-1", document_ref="doc-1",
                x_fisora_user_id="mali-musavir", x_fisora_session=None, fisora_session=None,
            )
            self.assertFalse(progress["terminal"])
            self.assertEqual(progress["job"]["id"], job["id"])
            self.assertEqual(progress["job"]["processing_snapshot"]["current_stage"], "planner")
            store.update_processing_job(job_id=job["id"], status="completed")
            terminal = service.document_processing_progress(
                client_id="client-1", document_ref="doc-1",
                x_fisora_user_id="mali-musavir", x_fisora_session=None, fisora_session=None,
            )
            self.assertTrue(terminal["terminal"])

    def test_snapshot_rejects_stale_attempt_after_reclaim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            job = store.create_processing_job(
                client_id="client-1", document_ref="doc-1",
                document_type="invoice", parser_kind="gemini_pdf_v2",
            )
            first = store.claim_next_processing_job()
            self.assertEqual(first["attempt_count"], 1)
            store.update_processing_snapshot(
                job_id=job["id"], processing_snapshot={"current_stage": "planner"}, attempt_count=1,
            )
            store.update_processing_job(job_id=job["id"], status="queued")
            second = store.claim_next_processing_job()
            self.assertEqual(second["attempt_count"], 2)
            self.assertEqual(second["processing_snapshot"], {})
            stale = store.update_processing_snapshot(
                job_id=job["id"], processing_snapshot={"current_stage": "stale"}, attempt_count=1,
            )
            self.assertIsNone(stale)
            current = next(item for item in store.list_processing_jobs(client_id="client-1") if item["id"] == job["id"])
            self.assertEqual(current["processing_snapshot"], {})


if __name__ == "__main__":
    unittest.main()
