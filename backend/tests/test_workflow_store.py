from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.workflow_store import JsonWorkflowStore
from app.domain.workspace_exports import build_workspace_export_package
from app.persistence.store_factory import build_workflow_store
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents


class WorkflowStoreTests(unittest.TestCase):
    def test_json_store_persists_client_documents_reviews_and_export_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(store_path)

            client = store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Isitme Merkezi"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            chart_accounts = store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {
                        "raw_account_code": "320.01.015",
                        "normalized_account_code": "320.01.015",
                        "account_name": "Rexton Medikal",
                    }
                ],
            )
            uploaded_document = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "rexton.pdf",
                    "storage_path": "exports/documents/client-1/doc-1/rexton.pdf",
                    "status": "stored",
                },
            )
            document = store.save_simulation_result(
                client_id="client-1",
                document_ref="rexton.pdf",
                result={
                    "file_name": "rexton.pdf",
                    "simulated_status": "auto_ready",
                    "export_status": "export_ready",
                    "review_reason_codes": [],
                },
            )
            decision = store.save_review_decision(
                client_id="client-1",
                decision={"document_ref": "rexton.pdf", "action": "approve"},
                learning_event={"document_ref": "rexton.pdf", "automation_candidate": False},
            )
            package = store.save_export_package(
                client_id="client-1",
                package={"export_type": "zirve_universal_csv", "entry_count": 1},
            )

            reloaded = JsonWorkflowStore(store_path).get_workspace("client-1")

        self.assertEqual(client["client_id"], "client-1")
        self.assertEqual(chart_accounts["account_count"], 1)
        self.assertEqual(uploaded_document["document_ref"], "doc-1")
        self.assertEqual(document["export_status"], "export_ready")
        self.assertEqual(decision["decision"]["action"], "approve")
        self.assertEqual(package["package"]["entry_count"], 1)
        self.assertEqual(reloaded["client"]["profile"]["title"], "Demo Isitme Merkezi")
        self.assertEqual(len(reloaded["uploaded_documents"]), 1)
        self.assertEqual(len(reloaded["documents"]), 1)
        self.assertEqual(len(reloaded["review_decisions"]), 1)
        self.assertEqual(len(reloaded["learning_events"]), 1)
        self.assertEqual(len(reloaded["export_packages"]), 1)

    def test_json_store_is_scoped_by_client_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.upsert_client(
                client_id="client-2",
                profile={"client_id": "client-2"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="one.pdf",
                result={"file_name": "one.pdf", "export_status": "export_ready"},
            )
            store.save_simulation_result(
                client_id="client-2",
                document_ref="two.pdf",
                result={"file_name": "two.pdf", "export_status": "review_required"},
            )

            workspace = store.get_workspace("client-1")

        self.assertEqual(workspace["client"]["client_id"], "client-1")
        self.assertEqual([document["document_ref"] for document in workspace["documents"]], ["one.pdf"])

    def test_json_store_tracks_portal_user_client_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1"},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            user = store.upsert_portal_user(
                user_id="mukellef-user",
                display_name="Mukellef Kullanici",
                role="client_user",
                allowed_client_ids=["client-1"],
            )
            allowed = store.verify_portal_access(client_id="client-1", user_id="mukellef-user")
            denied = store.verify_portal_access(client_id="client-2", user_id="mukellef-user")
            workspace = store.get_workspace("client-1")

        self.assertEqual(user["role"], "client_user")
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["reason"], "assigned_client_access")
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["reason"], "client_not_onboarded")
        self.assertEqual(workspace["portal_users"][0]["user_id"], "mukellef-user")

    def test_json_store_applies_document_retention_without_losing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir) / "expired.pdf"
            storage_path.write_bytes(b"expired")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            expired_at = datetime.now(UTC) - timedelta(days=1)
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "expired-doc",
                    "document_type": "invoice",
                    "original_file_name": "expired.pdf",
                    "storage_path": str(storage_path),
                    "status": "stored",
                    "storage_status": "stored",
                    "expires_at": expired_at.isoformat(timespec="seconds"),
                    "deleted_at": "",
                },
            )

            summary = store.apply_document_retention()
            workspace = store.get_workspace("client-1")

        self.assertEqual(summary["deleted_count"], 1)
        self.assertFalse(storage_path.exists())
        self.assertEqual(workspace["uploaded_documents"][0]["storage_status"], "deleted")
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "expired.pdf")

    def test_json_store_tracks_processing_jobs_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "fatura.pdf",
                    "status": "stored",
                },
            )

            job = store.create_processing_job(
                client_id="client-1",
                document_ref="doc-1",
                document_type="invoice",
                parser_kind=parser_kind_for_document_type("invoice"),
            )
            claimed = store.claim_next_processing_job()
            store.update_processing_job(job_id=job["id"], status="completed")
            workspace = store.get_workspace("client-1")

        self.assertEqual(job["status"], "queued")
        self.assertEqual(claimed["status"], "processing")
        self.assertEqual(workspace["processing_jobs"][0]["status"], "completed")

    def test_json_store_applies_review_correction_to_stored_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="urban-care.pdf",
                result={
                    "file_name": "urban-care.pdf",
                    "simulated_status": "review_required",
                    "export_status": "review_required",
                    "review_reason_codes": ["business_out_of_scope"],
                    "risk_flags": [],
                    "is_balanced": True,
                    "selected_expense_account": "770.01",
                    "selected_supplier_account": "320.01.001",
                    "counterparty_match_code": "320.01.001",
                    "product_category": "kisisel_bakim",
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01.001", "description": "Cari", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )

            decision = store.save_review_decision(
                client_id="client-1",
                decision={
                    "document_ref": "urban-care.pdf",
                    "action": "approve_with_changes",
                    "reviewer": "mali-musavir",
                    "corrected_account_code": "770.04.001",
                    "corrected_counterparty_code": "320.01.999",
                    "reason": "Pilot duzeltme",
                },
                learning_event={
                    "document_ref": "urban-care.pdf",
                    "scope": "client_rule",
                    "action": "approve_with_changes",
                    "category": "kisisel_bakim",
                    "corrected_account_code": "770.04.001",
                    "corrected_counterparty_code": "320.01.999",
                    "reason": "Pilot duzeltme",
                    "automation_candidate": False,
                },
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            export_build = build_workspace_export_package(workspace)

        self.assertIn("corrected_document", decision)
        self.assertEqual(result["selected_expense_account"], "770.04.001")
        self.assertEqual(result["selected_supplier_account"], "320.01.999")
        self.assertEqual(result["counterparty_match_code"], "320.01.999")
        self.assertEqual(result["draft_lines"][0]["account_code"], "770.04.001")
        self.assertEqual(result["draft_lines"][1]["account_code"], "320.01.999")
        self.assertTrue(result["learning_rule_applied"])
        self.assertTrue(result["accountant_export_override"])
        self.assertEqual(result["export_status"], "export_ready")
        self.assertEqual(len(export_build.package.entries), 1)

    def test_json_store_marks_export_package_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_export_package(
                client_id="client-1",
                package={
                    "export_type": "zirve_universal_csv",
                    "entry_count": 1,
                    "output_filename": "client-1-zirve.csv",
                },
            )

            downloaded = store.mark_export_package_downloaded(
                client_id="client-1",
                output_filename="client-1-zirve.csv",
            )
            workspace = store.get_workspace("client-1")

        self.assertIsNotNone(downloaded)
        self.assertEqual(downloaded["package"]["download_count"], 1)
        self.assertTrue(downloaded["package"]["downloaded_at"])
        self.assertEqual(workspace["export_packages"][0]["package"]["download_count"], 1)

    def test_processing_worker_creates_review_required_simulation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "doc-1",
                    "document_ref": "doc-1",
                    "document_type": "invoice",
                    "original_file_name": "fatura.pdf",
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="invoice",
                parser_kind=parser_kind_for_document_type("invoice"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(workspace["processing_jobs"][0]["status"], "completed")
        self.assertEqual(workspace["documents"][0]["export_status"], "review_required")
        self.assertEqual(workspace["documents"][0]["review_reason_codes"], ["parser_output_required"])

    def test_processing_worker_parses_xml_invoice_and_runs_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "rexton.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ProfileID>TEMELFATURA</cbc:ProfileID>
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:UUID>123e4567-e89b-12d3-a456-426614174000</cbc:UUID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyLegalEntity><cbc:RegistrationName>Rexton Medikal</cbc:RegistrationName></cac:PartyLegalEntity>
      <cac:PartyTaxScheme><cbc:CompanyID>1234567890</cbc:CompanyID></cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:InvoiceLine>
    <cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cac:Item><cbc:Name>Rexton RLi 20</cbc:Name></cac:Item>
  </cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>200.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>1200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
""",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={
                    "client_id": "client-1",
                    "title": "Demo Isitme Merkezi",
                    "tax_id": "1111111111",
                    "activity_description": "isitme cihazi satis ve servis",
                    "workplace_addresses": ["Istanbul"],
                    "has_chart_accounts": True,
                },
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel gider", "is_detail_account": True},
                    {"raw_account_code": "191.01", "normalized_account_code": "191.01", "account_name": "Indirilecek KDV", "is_detail_account": True},
                    {"raw_account_code": "320.01.015", "normalized_account_code": "320.01.015", "account_name": "Rexton Medikal", "is_detail_account": True, "tax_id": "1234567890"},
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "xml-doc",
                    "document_ref": "xml-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "rexton.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["file_name"], "rexton.xml")
        self.assertEqual(result["payable_total"], "1200.00")
        self.assertEqual(result["product_category"], "isitme_cihazi")
        self.assertEqual(result["selected_supplier_account"], "320.01.015")
        self.assertEqual(result["export_status"], "export_ready")
        self.assertTrue(result["draft_lines"])

    def test_processing_worker_parses_bank_statement_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction,balance_after\n"
                "2026-05-03,GIB ODEME,500.00,out,9500.00\n"
                "2026-05-04,SGK PRIM,700.00,out,8800.00\n"
                "2026-05-05,POS BLOKE,1200.00,in,10000.00\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "review_required")
        self.assertTrue(result["is_balanced"])
        self.assertEqual(result["draft_quality"], "statement_entries_ready")
        self.assertEqual(len(result["statement_entries"]), 3)
        self.assertEqual(result["statement_entries"][0]["total_debit"], "500.00")
        self.assertEqual(result["statement_entries"][0]["total_credit"], "500.00")
        self.assertTrue(result["draft_lines"])
        self.assertEqual(result["statement_lines"][0]["transaction_type"], "tax_payment")
        self.assertEqual(result["statement_lines"][1]["suggested_account_code"], "361")
        self.assertEqual(result["statement_lines"][2]["transaction_type"], "pos_blocked")

    def test_processing_worker_matches_bank_statement_counterparty_by_tax_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction,tax_id,counterparty_name\n"
                "2026-05-03,Rexton Medikal odeme,1200.00,out,1234567890,Rexton Medikal\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {"raw_account_code": "320.01.015", "normalized_account_code": "320.01.015", "account_name": "Rexton Medikal", "is_detail_account": True, "tax_id": "1234567890"},
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "export_ready")
        self.assertEqual(result["statement_lines"][0]["transaction_type"], "counterparty_payment")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_code"], "320.01.015")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_reason"], "tax_id_exact")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.015")

    def test_processing_worker_matches_bank_statement_counterparty_by_iban(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction,iban\n"
                "2026-05-03,Tedarikci odeme,1200.00,out,TR12 0000 0000 0000 0000 0000 01\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {
                        "raw_account_code": "320.01.777",
                        "normalized_account_code": "320.01.777",
                        "account_name": "IBAN Tedarikci",
                        "is_detail_account": True,
                        "iban": "TR120000000000000000000001",
                    },
                ],
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "export_ready")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_code"], "320.01.777")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_reason"], "iban_exact")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.777")

    def test_processing_worker_matches_bank_statement_counterparty_by_learning_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            statement_path = Path(temp_dir) / "bank.csv"
            statement_path.write_text(
                "transaction_date,description,amount,direction\n"
                "2026-05-03,Kolay Soft hizmet odemesi,900.00,out\n",
                encoding="utf-8",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.upsert_client(
                client_id="client-1",
                profile={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
                onboarding={"is_ready": True, "missing_fields": []},
            )
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                    {
                        "raw_account_code": "320.01.888",
                        "normalized_account_code": "320.01.888",
                        "account_name": "Kolay Soft",
                        "is_detail_account": True,
                    },
                ],
            )
            store.save_review_decision(
                client_id="client-1",
                decision={"document_ref": "old-kolay-soft.pdf", "action": "approve_with_changes"},
                learning_event={
                    "document_ref": "old-kolay-soft.pdf",
                    "scope": "client_rule",
                    "action": "approve_with_changes",
                    "category": "kolay_soft",
                    "corrected_account_code": "770.01",
                    "corrected_counterparty_code": "320.01.888",
                    "reason": "Kolay Soft e-fatura hizmeti",
                    "automation_candidate": True,
                },
            )
            uploaded = store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "bank-doc",
                    "document_ref": "bank-doc",
                    "document_type": "bank_statement",
                    "original_file_name": "bank.csv",
                    "storage_path": str(statement_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref=uploaded["document_ref"],
                document_type="bank_statement",
                parser_kind=parser_kind_for_document_type("bank_statement"),
            )

            summary = process_queued_documents(store)
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(result["export_status"], "export_ready")
        self.assertTrue(result["learning_rule_applied"])
        self.assertEqual(result["statement_lines"][0]["counterparty_match_code"], "320.01.888")
        self.assertEqual(result["statement_lines"][0]["counterparty_match_reason"], "learning_event")
        self.assertEqual(result["statement_entries"][0]["lines"][0]["account_code"], "320.01.888")

    def test_store_factory_selects_json_and_requires_postgres_dsn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = build_workflow_store(store_backend="json", json_path=Path(temp_dir) / "store.json")

        self.assertIsInstance(store, JsonWorkflowStore)
        with self.assertRaises(ValueError):
            build_workflow_store(store_backend="postgres", postgres_dsn="")


if __name__ == "__main__":
    unittest.main()
