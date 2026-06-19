from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.research_harness import (
    ResearchHarness,
    ResearchPolicy,
    ResearchQuery,
    apply_research_to_result,
    build_research_runtime_from_env,
    normalize_research_profile,
    sanitize_research_query,
    source_policy_accepts,
)
from app.persistence.workflow_store import JsonWorkflowStore
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents

try:
    from fastapi.testclient import TestClient
    from app.api import phase0
    from app.main import app
except Exception:  # pragma: no cover - optional FastAPI import guard
    TestClient = None
    phase0 = None
    app = None


class FakeResearchProvider:
    provider_name = "fake_research_agent"

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.queries: list[ResearchQuery] = []

    def research(self, query: ResearchQuery) -> dict[str, object]:
        self.queries.append(query)
        return self.payload


class ResearchHarnessTests(unittest.TestCase):
    def test_research_query_sanitizer_keeps_brand_and_supplier_but_removes_private_invoice_fields(self) -> None:
        query = sanitize_research_query(
            kind="brand",
            raw_line="Blendax sac bakim seti 1.250,00 TL Fatura ABC2026000000001 VKN 1234567890",
            supplier_hint="Acme Kozmetik A.S. VKN 1234567890 Ataturk Cad. No: 12",
            activity_context="Isitme cihazi satis merkezi",
        )

        self.assertEqual(query.kind, "brand")
        self.assertIn("Blendax", query.search_text)
        self.assertIn("Acme Kozmetik", query.supplier_hint)
        self.assertNotIn("1234567890", query.search_text)
        self.assertNotIn("ABC2026000000001", query.search_text)
        self.assertNotIn("1.250,00", query.search_text)
        self.assertNotIn("Ataturk Cad", query.supplier_hint)

    def test_source_policy_rejects_marketplaces_and_accepts_official_or_manufacturer_sources(self) -> None:
        self.assertFalse(source_policy_accepts("https://www.trendyol.com/blendax/sampuan"))
        self.assertFalse(source_policy_accepts("https://blog.example.com/en-iyi-sampuan"))
        self.assertTrue(source_policy_accepts("https://www.blendax.com.tr/urunler/sampuan"))
        self.assertTrue(source_policy_accepts("https://ec.europa.eu/eurostat/web/nace/overview"))

    def test_research_harness_cache_hit_reuses_store_profile_without_calling_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_brand_research_profile(
                brand_name="Blendax",
                profile={
                    "display_name": "Blendax",
                    "brand_summary": "Sampuan markasi.",
                    "common_product_categories": ["kisisel_bakim_kozmetik"],
                    "confidence": 88,
                    "source_urls": ["https://www.blendax.com.tr/"],
                },
            )
            provider = FakeResearchProvider({"display_name": "Blendax", "confidence": 99})
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_brand(
                raw_line="Blendax sac bakim seti",
                supplier_hint="Acme Kozmetik",
                activity_context="Isitme merkezi",
            )

        self.assertEqual(profile["brand_summary"], "Sampuan markasi.")
        self.assertEqual(provider.queries, [])

    def test_apply_research_to_result_keeps_low_confidence_research_in_review(self) -> None:
        result = {
            "export_status": "export_ready",
            "simulated_status": "auto_ready",
            "review_reason_codes": [],
            "risk_flags": [],
        }
        profile = normalize_research_profile(
            kind="brand",
            key="unknown brand",
            payload={
                "display_name": "Unknown Brand",
                "brand_summary": "Kaynak zayif.",
                "common_product_categories": ["bilinmeyen"],
                "confidence": 69,
                "evidence": [{"url": "https://manufacturer.example/product", "summary_tr": "Urun sayfasi."}],
            },
        )

        updated = apply_research_to_result(result, profile, confidence_threshold=70)

        self.assertEqual(updated["export_status"], "review_required")
        self.assertIn("research_low_confidence", updated["review_reason_codes"])
        self.assertEqual(updated["research_profile"]["confidence"], 69)

    def test_build_research_runtime_from_env_is_openai_only_and_disabled_without_key(self) -> None:
        self.assertIsNone(build_research_runtime_from_env({"FISORA_RESEARCH_ENABLED": "true"}))
        runtime = build_research_runtime_from_env(
            {
                "FISORA_RESEARCH_ENABLED": "true",
                "OPENAI_API_KEY": "sk-test",
                "FISORA_RESEARCH_MODEL": "gpt-5.4-mini",
                "FISORA_RESEARCH_MAX_PER_DOCUMENT": "1",
            }
        )

        self.assertEqual(runtime["policy"].max_per_document, 1)
        self.assertEqual(runtime["provider"].provider_name, "openai_agents_research")

    def test_store_lists_research_profiles_and_tracks_benchmark_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_brand_research_profile(
                brand_name="Blendax",
                profile=normalize_research_profile(
                    kind="brand",
                    key="Blendax",
                    payload={
                        "display_name": "Blendax",
                        "summary_tr": "Sampuan markasi.",
                        "common_product_categories": ["kisisel_bakim_kozmetik"],
                        "confidence": 88,
                    },
                ),
            )
            run = store.save_research_benchmark_run(
                {
                    "run_type": "benchmark",
                    "case_count": 2,
                    "accuracy": 50,
                    "model": "gpt-5.4-mini",
                }
            )
            profiles = store.list_research_profiles(kind="brand")
            runs = store.list_research_benchmark_runs()

        self.assertEqual(profiles[0]["display_name"], "Blendax")
        self.assertEqual(run["run_type"], "benchmark")
        self.assertEqual(runs[0]["accuracy"], 50)

    def test_research_api_exposes_profiles_override_refresh_and_benchmark(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("FastAPI TestClient unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            original_store_path = phase0.DEFAULT_STORE_PATH
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
            store.upsert_portal_user(
                user_id="mali-musavir",
                display_name="Mali Musavir",
                role="accountant",
                allowed_client_ids=["*"],
            )
            store.save_brand_research_profile(
                brand_name="Blendax",
                profile=normalize_research_profile(
                    kind="brand",
                    key="Blendax",
                    payload={
                        "display_name": "Blendax",
                        "summary_tr": "Sampuan markasi.",
                        "common_product_categories": ["kisisel_bakim_kozmetik"],
                        "confidence": 88,
                        "evidence": [{"url": "https://www.blendax.com.tr/", "summary_tr": "Uretici sitesi."}],
                    },
                ),
            )
            try:
                client = TestClient(app)
                headers = {"X-Fisora-User-Id": "mali-musavir"}
                profiles = client.get("/phase0/store/research/profiles?kind=brand", headers=headers)
                detail = client.get("/phase0/store/research/profile/brand/blendax", headers=headers)
                override = client.post(
                    "/phase0/store/research/override",
                    headers=headers,
                    json={
                        "kind": "brand",
                        "key": "Blendax",
                        "summary_tr": "Müşavir düzeltti.",
                        "category_tags": ["kisisel_bakim_kozmetik"],
                        "confidence": 92,
                    },
                )
                refresh = client.post(
                    "/phase0/store/research/refresh",
                    headers=headers,
                    json={"kind": "brand", "key": "Blendax", "force": True},
                )
                benchmark = client.post("/phase0/store/research/benchmark/run", headers=headers, json={})
                runs = client.get("/phase0/store/research/benchmark/runs", headers=headers)
            finally:
                phase0.DEFAULT_STORE_PATH = original_store_path

        self.assertEqual(profiles.status_code, 200)
        self.assertEqual(profiles.json()["profiles"][0]["display_name"], "Blendax")
        self.assertEqual(detail.json()["profile"]["display_name"], "Blendax")
        self.assertEqual(override.json()["profile"]["summary_tr"], "Müşavir düzeltti.")
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(benchmark.status_code, 200)
        self.assertGreaterEqual(benchmark.json()["run"]["case_count"], 3)
        self.assertEqual(runs.json()["runs"][0]["run_type"], "benchmark")

    def test_worker_records_research_timeline_and_keeps_low_confidence_result_in_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "unknown.xml"
            xml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Acme Kozmetik A.S.</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>Mystery Sonic Pro bakım seti</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>200.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount><cbc:TaxInclusiveAmount>1200.00</cbc:TaxInclusiveAmount><cbc:PayableAmount>1200.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
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
            store.save_uploaded_document(
                client_id="client-1",
                document={
                    "document_id": "xml-doc",
                    "document_ref": "xml-doc",
                    "document_type": "einvoice_xml",
                    "original_file_name": "unknown.xml",
                    "storage_path": str(xml_path),
                    "status": "stored",
                },
            )
            store.create_processing_job(
                client_id="client-1",
                document_ref="xml-doc",
                document_type="einvoice_xml",
                parser_kind=parser_kind_for_document_type("einvoice_xml"),
            )
            provider = FakeResearchProvider(
                {
                    "display_name": "Mystery Sonic",
                    "summary_tr": "Tek kaynakli belirsiz urun.",
                    "common_product_categories": ["bilinmeyen"],
                    "confidence": 69,
                    "evidence": [{"url": "https://manufacturer.example/mystery", "summary_tr": "Uretici sayfasi."}],
                }
            )

            summary = process_queued_documents(
                store,
                research_runtime={"provider": provider, "policy": ResearchPolicy(enabled=True, confidence_threshold=70)},
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            pipeline_steps = [event["step"] for event in workspace["document_pipeline_events"]]

        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(result["export_status"], "review_required")
        self.assertEqual(result["research_profile"]["confidence"], 69)
        self.assertIn("research_started", pipeline_steps)
        self.assertIn("research_low_confidence", pipeline_steps)


if __name__ == "__main__":
    unittest.main()
