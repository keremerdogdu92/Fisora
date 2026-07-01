from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

try:
    from fastapi.testclient import TestClient

    from app.api import phase0
    from app.main import app
except ModuleNotFoundError:
    TestClient = None
    phase0 = None
    app = None


class DocumentUploadApiTests(unittest.TestCase):
    def test_store_document_upload_writes_content_and_workspace_metadata(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "period": "2026-05",
                    "file_name": "fatura.pdf",
                    "uploaded_by": "mukellef-user",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            )
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "stored")
        self.assertEqual(payload["size_bytes"], 6)
        self.assertEqual(payload["processing_job"]["status"], "queued")
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "fatura.pdf")
        self.assertEqual(workspace["uploaded_documents"][0]["period"], "2026-05")
        pipeline = workspace["document_pipeline_events"]
        self.assertEqual([event["step"] for event in pipeline], ["uploaded", "file_preview_ready"])
        self.assertEqual(pipeline[0]["message_tr"], "Belge yüklendi.")
        self.assertEqual(pipeline[1]["message_tr"], "Belge önizlenebiliyor.")

    def test_document_pipeline_endpoint_returns_events_for_document(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by": "mukellef-user",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            ).json()

            response = client.get(
                f"/phase0/store/document-pipeline/client-1/{upload['document_ref']}",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["client_id"], "client-1")
        self.assertEqual(payload["document_ref"], upload["document_ref"])
        self.assertEqual([event["step"] for event in payload["events"]], ["uploaded", "file_preview_ready"])

    def test_document_reprocess_queues_existing_uploaded_document(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "intake_category": "purchase_invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "mali-musavir",
                    "content_base64": "ZmF0dXJh",
                },
            ).json()

            response = client.post(
                "/phase0/store/document-reprocess",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={"client_id": "client-1", "document_ref": upload["document_ref"]},
            )
            workspace = client.get(
                "/phase0/store/workspace/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            ).json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["document_ref"], upload["document_ref"])
        self.assertEqual(payload["processing_job"]["status"], "queued")
        self.assertEqual(payload["processing_job"]["intake_category"], "purchase_invoice")
        self.assertEqual([job["status"] for job in workspace["processing_jobs"]], ["queued", "queued"])
        self.assertIn("reprocess_queued", [event["step"] for event in workspace["document_pipeline_events"]])

    def test_client_reprocess_reloads_tax_certificate_nace_and_processes_documents(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        from app.domain.research_harness import ResearchPolicy
        from app.domain.tax_certificates import TaxCertificateExtraction

        class FakeNaceProvider:
            provider_name = "fake_nace_research"

            def research(self, query):
                return {
                    "display_name": "47.74.01 Tibbi ve ortopedik urunlerin perakende ticareti",
                    "summary_tr": "Isitme cihazi ve tibbi urun perakende faaliyeti.",
                    "activity_tags": ["hearing_aid", "medical_retail"],
                    "source_urls": ["https://ec.europa.eu/eurostat/web/nace/overview"],
                    "confidence": 88,
                    "research_confidence": 88,
                    "accounting_impact_confidence": 90,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )
            client.post(
                "/phase0/store/client-onboarding-attachment",
                data={
                    "client_id": "client-1",
                    "attachment_type": "tax_certificate",
                    "uploaded_by": "mali-musavir",
                    "uploaded_by_user_id": "mali-musavir",
                },
                files={"file": ("vergi-levhasi.pdf", b"fake-pdf", "application/pdf")},
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            document = client.post(
                "/phase0/store/document-upload",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client_id": "client-1",
                    "document_type": "special_document",
                    "intake_category": "special_document",
                    "file_name": "eski-belge.pdf",
                    "uploaded_by_user_id": "mali-musavir",
                    "content_base64": "ZXNraS1iZWxnZQ==",
                },
            ).json()
            client.post("/phase0/store/processing-run", json={"max_jobs": 5})

            with patch(
                "app.services.document_service.parse_tax_certificate_file",
                return_value=TaxCertificateExtraction(
                    title="Demo Mukellef",
                    tax_id="1111111111",
                    vkn="1111111111",
                    tax_office="Kadikoy",
                    activity_description="Tibbi ve ortopedik urunlerin perakende ticareti",
                    nace_code="477401",
                    workplace_addresses=("Istanbul",),
                    confidence=95,
                ),
                create=True,
            ):
                with patch(
                    "app.services.document_service.build_research_runtime_from_env",
                    return_value={"provider": FakeNaceProvider(), "policy": ResearchPolicy(enabled=True)},
                    create=True,
                ):
                    with patch(
                        "app.services.document_service.process_queued_documents",
                        side_effect=AssertionError("client reprocess must return after queueing documents"),
                    ):
                        response = client.post(
                            "/phase0/store/client-reprocess",
                            headers={"X-Fisora-User-Id": "mali-musavir"},
                            json={"client_id": "client-1", "max_jobs": 5},
                        )
            workspace = client.get(
                "/phase0/store/workspace/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            ).json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["queued_document_count"], 1)
        self.assertEqual(payload["processing_summary"]["current_status"], "queued")
        self.assertEqual(payload["processing_summary"]["processed_count"], 0)
        self.assertEqual(payload["tax_certificate"]["nace_code"], "477401")
        self.assertEqual(payload["nace_research_profile"]["activity_tags"], ["hearing_aid", "medical_retail"])
        self.assertEqual(workspace["client"]["profile"]["nace_code"], "477401")
        self.assertEqual(workspace["client"]["profile"]["activity_tags"], ["hearing_aid", "medical_retail"])
        self.assertEqual(workspace["processing_jobs"][-1]["document_ref"], document["document_ref"])
        self.assertEqual(workspace["processing_jobs"][-1]["status"], "queued")

    def test_onboarding_attachment_does_not_create_processing_job(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": False},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/client-onboarding-attachment",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                data={
                    "client_id": "client-1",
                    "attachment_type": "tax_certificate",
                    "uploaded_by": "mali-musavir",
                    "uploaded_by_user_id": "mali-musavir",
                },
                files={"file": ("vergi-levhasi.pdf", b"%PDF-1.7", "application/pdf")},
            )
            workspace = client.get(
                "/phase0/store/workspace/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            ).json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["attachment_type"], "tax_certificate")
        self.assertEqual(len(workspace["onboarding_attachments"]), 1)
        self.assertEqual(workspace["uploaded_documents"], [])
        self.assertEqual(workspace["processing_jobs"], [])

    def test_tax_certificate_attachment_updates_client_profile_without_processing_job(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        from app.domain.tax_certificates import TaxCertificateExtraction

        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "tax_id": "1111111111", "has_chart_accounts": False},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )

            with patch(
                "app.services.document_service.parse_tax_certificate_file",
                return_value=TaxCertificateExtraction(
                    title="Demo Mukellef A.S.",
                    tax_id="1111111111",
                    vkn="1111111111",
                    tax_office="Kadikoy",
                    activity_description="Tibbi ve ortopedik urunlerin perakende ticareti",
                    nace_code="477401",
                    workplace_addresses=("Istanbul",),
                    confidence=95,
                ),
                create=True,
            ):
                response = client.post(
                    "/phase0/store/client-onboarding-attachment",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    data={
                        "client_id": "client-1",
                        "attachment_type": "tax_certificate",
                        "uploaded_by": "mali-musavir",
                        "uploaded_by_user_id": "mali-musavir",
                    },
                    files={"file": ("vergi-levhasi.pdf", b"%PDF-1.7", "application/pdf")},
                )
            workspace = client.get(
                "/phase0/store/workspace/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            ).json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["tax_certificate_parse_status"], "parsed")
        self.assertEqual(payload["tax_certificate"]["nace_code"], "477401")
        self.assertEqual(workspace["client"]["profile"]["nace_code"], "477401")
        self.assertEqual(workspace["client"]["profile"]["activity_description"], "Tibbi ve ortopedik urunlerin perakende ticareti")
        self.assertEqual(workspace["client"]["profile"]["workplace_addresses"], ["Istanbul"])
        self.assertEqual(workspace["processing_jobs"], [])

    def test_store_document_file_records_preview_fetch_failure_when_file_is_missing(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by": "mukellef-user",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            ).json()
            stored_path = Path(upload["storage_path"])
            stored_path.unlink()

            response = client.get(
                f"/phase0/store/document-file/client-1/{upload['document_ref']}",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )
            pipeline = client.get(
                f"/phase0/store/document-pipeline/client-1/{upload['document_ref']}",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            ).json()["events"]

        self.assertEqual(response.status_code, 404)
        self.assertEqual(pipeline[-1]["step"], "preview_fetch_failed")
        self.assertEqual(pipeline[-1]["message_tr"], "Önizleme alınamadı: dosya storage'da bulunamadı.")

    def test_store_document_file_endpoint_returns_original_file_for_authorized_user(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "other-user",
                    "display_name": "Baska Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-2"],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJhLW9yaWppbmFs",
                },
            )
            document_ref = upload.json()["document_ref"]

            authorized = client.get(
                f"/phase0/store/document-file/client-1/{document_ref}",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )
            denied = client.get(
                f"/phase0/store/document-file/client-1/{document_ref}",
                headers={"X-Fisora-User-Id": "other-user"},
            )

        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.content, b"fatura-orijinal")
        self.assertIn("application/pdf", authorized.headers["content-type"])
        self.assertEqual(denied.status_code, 403)

    def test_store_document_upload_rejects_invalid_base64(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "not valid base64",
                },
            )

        self.assertEqual(response.status_code, 400)

    def test_store_review_decision_accepts_review_required_action(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/review-decision",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client_id": "client-1",
                    "decision": {
                        "document_ref": "purchase.xml",
                        "action": "review_required",
                        "reviewer": "mali-musavir",
                        "reason": "Kontrolde tut",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"]["action"], "review_required")

    def test_store_review_decision_enriches_learning_event_and_rule_prompt(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1"],
                },
            )
            for index in range(1, 4):
                response = client.post(
                    "/phase0/store/review-decision",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={
                        "client_id": "client-1",
                        "decision": {
                            "document_ref": f"kolaysoft-{index}.xml",
                            "action": "approve_with_changes",
                            "reviewer": "mali-musavir",
                            "corrected_account_code": "770.05",
                            "corrected_counterparty_code": "320.01.888",
                            "category": "e_fatura_hizmeti",
                            "reason": "Bu mukellefte Kolay Soft e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
                        },
                    },
                )

        payload = response.json()
        learning_event = payload["learning_event"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(learning_event["client_id"], "client-1")
        self.assertEqual(learning_event["accounting_intent"], "e_fatura_yazilim_gideri")
        self.assertEqual(learning_event["client_consistent_decision_count"], 3)
        self.assertTrue(learning_event["rule_prompt"]["show"])

    def test_store_document_upload_multipart_writes_content(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload-multipart",
                data={
                    "client_id": "client-1",
                    "document_type": "bank_statement",
                    "uploaded_by": "mukellef-user",
                    "uploaded_by_user_id": "mukellef-user",
                },
                files={"file": ("bank.csv", b"transaction_date,description,amount\n2026-06-01,GIB,10.00\n", "text/csv")},
            )
            payload = response.json()
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "stored")
        self.assertEqual(payload["processing_job"]["parser_kind"], "bank_statement")
        self.assertEqual(workspace["uploaded_documents"][0]["original_file_name"], "bank.csv")

    def test_special_document_upload_goes_to_manual_review_queue(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "special_document",
                    "intake_category": "special_document",
                    "file_name": "sozlesme.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "bWFudWFs",
                },
            )
            payload = response.json()
            workspace = client.get("/phase0/store/workspace/client-1").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["document_type"], "special_document")
        self.assertEqual(payload["intake_category"], "special_document")
        self.assertEqual(payload["processing_job"]["parser_kind"], "manual_review")
        self.assertEqual(workspace["uploaded_documents"][0]["intake_category"], "special_document")

    def test_client_onboarding_package_creates_upload_ready_workspace(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)

            package = client.post(
                "/phase0/store/client-onboarding-package",
                json={
                    "client": {
                        "client_id": "client-1",
                        "title": "Demo Mukellef",
                        "tax_id": "1111111111",
                        "activity_description": "isitme cihazi satis",
                        "workplace_addresses": ["Istanbul"],
                        "has_chart_accounts": True,
                    },
                    "chart_accounts": [
                        {
                            "raw_account_code": "320.01.015",
                            "normalized_account_code": "320.01.015",
                            "account_name": "Rexton Medikal",
                            "is_detail_account": True,
                            "tax_id": "1234567890",
                        }
                    ],
                    "portal_users": [
                        {
                            "user_id": "mukellef-user",
                            "display_name": "Mukellef Kullanici",
                            "role": "client_user",
                            "allowed_client_ids": ["client-1"],
                        }
                    ],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "mukellef-user",
                    "content_base64": "ZmF0dXJh",
                },
            )
            clients = client.get("/phase0/store/clients")

        self.assertEqual(package.status_code, 200)
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(clients.json()["clients"][0]["client_id"], "client-1")
        self.assertEqual(package.json()["workspace"]["portal_users"][0]["user_id"], "mukellef-user")

    def test_accountant_onboarding_package_grants_upload_access_to_new_client(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": [],
                },
            )

            package = client.post(
                "/phase0/store/client-onboarding-package",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client": {
                        "client_id": "ibrahim-degerli",
                        "title": "Ibrahim Degerli",
                        "tax_id": "38119521000",
                        "activity_description": "Tibbi ve ortopedik urunlerin perakende ticareti",
                        "has_chart_accounts": False,
                    },
                    "portal_users": [
                        {
                            "user_id": "ibrahim-degerli-user",
                            "display_name": "Ibrahim Degerli",
                            "role": "client_user",
                            "allowed_client_ids": ["ibrahim-degerli"],
                        }
                    ],
                },
            )
            upload = client.post(
                "/phase0/store/document-upload",
                headers={"X-Fisora-User-Id": "mali-musavir"},
                json={
                    "client_id": "ibrahim-degerli",
                    "document_type": "special_document",
                    "intake_category": "special_document",
                    "file_name": "vergi-levhasi.pdf",
                    "uploaded_by_user_id": "mali-musavir",
                    "content_base64": "dmVyZ2ktbGV2aGFzaQ==",
                    "retention_policy_days": 365,
                },
            )

        self.assertEqual(package.status_code, 200)
        self.assertEqual(upload.status_code, 200)

    def test_chart_accounts_multipart_upload_parses_and_replaces_workspace_accounts(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["*"],
                },
            )
            response = client.post(
                "/phase0/store/chart-accounts/upload",
                data={"client_id": "client-1"},
                files={
                    "file": (
                        "hesap-plani.csv",
                        b"hesap_kodu,hesap_adi\n320.01,Rexton Medikal\n191.01,Indirilecek KDV\n",
                        "text/csv",
                    )
                },
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            workspace = client.get(
                "/phase0/store/workspace/client-1",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            ).json()
            raw_chart_path_exists = Path(workspace["onboarding_attachments"][0]["storage_path"]).exists()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["account_count"], 2)
        self.assertEqual(workspace["chart_accounts"]["account_count"], 2)
        self.assertEqual(workspace["chart_accounts"]["accounts"][0]["normalized_account_code"], "320.01")
        self.assertEqual(workspace["onboarding_attachments"][0]["attachment_type"], "chart_accounts")
        self.assertEqual(workspace["onboarding_attachments"][0]["original_file_name"], "hesap-plani.csv")
        self.assertTrue(raw_chart_path_exists)

    def test_chart_accounts_parse_endpoint_returns_accounts_without_creating_client(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)

            response = client.post(
                "/phase0/chart-accounts/parse",
                files={
                    "file": (
                        "hesap-plani.csv",
                        b"hesap_kodu,hesap_adi\n320.01,Rexton Medikal\n191.01,Indirilecek KDV\n",
                        "text/csv",
                    )
                },
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            clients = client.get("/phase0/store/clients")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["account_count"], 2)
        self.assertEqual(response.json()["accounts"][0]["normalized_account_code"], "320.01")
        self.assertEqual(clients.json()["clients"], [])

    def test_store_document_upload_rejects_unassigned_portal_user(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_DOCUMENT_STORAGE_PATH = Path(temp_dir) / "documents"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "other-user",
                    "display_name": "Baska Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-2"],
                },
            )

            response = client.post(
                "/phase0/store/document-upload",
                json={
                    "client_id": "client-1",
                    "document_type": "invoice",
                    "file_name": "fatura.pdf",
                    "uploaded_by_user_id": "other-user",
                    "content_base64": "ZmF0dXJh",
                },
            )

        self.assertEqual(response.status_code, 403)

    def test_mock_auth_filters_clients_and_blocks_unassigned_workspace(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)
            for client_id in ("client-1", "client-2"):
                client.post(
                    "/phase0/store/client",
                    json={"client_id": client_id, "title": f"Demo {client_id}", "has_chart_accounts": True},
                )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mali-musavir",
                    "display_name": "Mali Musavir",
                    "role": "accountant",
                    "allowed_client_ids": ["client-1", "client-2"],
                },
            )

            client_user_clients = client.get(
                "/phase0/store/clients",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )
            accountant_clients = client.get(
                "/phase0/store/clients",
                headers={"X-Fisora-User-Id": "mali-musavir"},
            )
            denied_workspace = client.get(
                "/phase0/store/workspace/client-2",
                headers={"X-Fisora-User-Id": "mukellef-user"},
            )

        self.assertEqual(client_user_clients.status_code, 200)
        self.assertEqual([item["client_id"] for item in client_user_clients.json()["clients"]], ["client-1"])
        self.assertEqual(accountant_clients.status_code, 200)
        self.assertEqual(len(accountant_clients.json()["clients"]), 2)
        self.assertEqual(denied_workspace.status_code, 403)

    def test_mock_auth_blocks_client_user_export_package(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_EXPORT_PATH = Path(temp_dir) / "exports"
            client = TestClient(app)
            client.post(
                "/phase0/store/client",
                json={"client_id": "client-1", "title": "Demo Mukellef", "has_chart_accounts": True},
            )
            client.post(
                "/phase0/store/portal-user",
                json={
                    "user_id": "mukellef-user",
                    "display_name": "Mukellef Kullanici",
                    "role": "client_user",
                    "allowed_client_ids": ["client-1"],
                },
            )

            response = client.post(
                "/phase0/store/export-package/from-workspace",
                headers={"X-Fisora-User-Id": "mukellef-user"},
                json={"client_id": "client-1", "export_type": "zirve_universal_csv"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["reason"], "role_not_allowed")

    def test_store_export_package_from_workspace_writes_downloadable_csv(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            phase0.DEFAULT_EXPORT_PATH = Path(temp_dir) / "exports"
            client = TestClient(app)
            store = phase0.get_workflow_store()
            store.save_simulation_result(
                client_id="client-1",
                document_ref="ready.pdf",
                result={
                    "file_name": "ready.pdf",
                    "export_status": "export_ready",
                    "review_reason_codes": [],
                    "risk_flags": [],
                    "draft_lines": [
                        {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                        {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "100.00"},
                    ],
                },
            )

            response = client.post(
                "/phase0/store/export-package/from-workspace",
                json={"client_id": "client-1", "export_type": "zirve_universal_csv"},
            )
            payload = response.json()
            download = client.get(payload["package"]["download_url"])
            manifest = client.get(payload["package"]["manifest_download_url"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["package"]["entry_count"], 1)
        self.assertTrue(payload["package"]["manifest_filename"].endswith(".manifest.json"))
        self.assertEqual(download.status_code, 200)
        self.assertIn("770.01", download.text)
        self.assertEqual(manifest.status_code, 200)
        self.assertIn("ready.pdf", manifest.text)

    def test_statement_ai_suggestions_endpoint_returns_review_only_structured_payload(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("fastapi is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as temp_dir:
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "store.json"
            client = TestClient(app)

            response = client.post(
                "/phase0/statement/ai-suggestions",
                json={
                    "client_id": "client-1",
                    "ai_policy": {"enabled": True, "confidence_threshold": 70, "max_provider_calls": 2},
                    "provider_name": "replay_provider",
                    "provider_payloads": [
                        {
                            "transaction_type": "counterparty_payment",
                            "suggested_account_code": "320.01.123",
                            "confidence": 82,
                            "reason": "Satir tedarikci odemesi gibi gorunuyor.",
                            "evidence": ["tedarikci", "odeme"],
                        }
                    ],
                    "lines": [
                        {
                            "line_no": 1,
                            "transaction_date": "2026-06-01",
                            "description": "GIB ODEME",
                            "amount": "100.00",
                            "direction": "out",
                            "suggested_account_code": "360",
                            "transaction_type": "tax_payment",
                            "confidence": 86,
                            "risk_flags": [],
                        },
                        {
                            "line_no": 2,
                            "transaction_date": "2026-06-02",
                            "description": "BILINMEYEN TEDARIKCI ODEME",
                            "amount": "250.00",
                            "direction": "out",
                            "transaction_type": "unknown",
                            "confidence": 35,
                            "risk_flags": ["statement_review_required", "counterparty_not_found"],
                        },
                    ],
                },
            )
            summary_response = client.post(
                "/phase0/store/ai-usage/summary",
                json={"client_id": "client-1", "monthly_cap_usd": "100.00"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ai_used_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["suggestions"][0]["line_no"], 2)
        self.assertEqual(payload["suggestions"][0]["suggested_account_code"], "320.01.123")
        self.assertFalse(payload["suggestions"][0]["export_allowed"])
        self.assertEqual(summary_response.json()["summary"]["ai_used_count"], 1)


if __name__ == "__main__":
    unittest.main()
