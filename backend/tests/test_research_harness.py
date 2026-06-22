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
    TavilySearchResearchProvider,
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


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeHttpClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


def write_invoice_xml(path: Path, *, line_name: str, supplier_name: str = "Acme A.S.", total: str = "1200.00") -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>{supplier_name}</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>{line_name}</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:TaxTotal><cbc:TaxAmount>200.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:Percent>20</cbc:Percent></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>1000.00</cbc:LineExtensionAmount><cbc:TaxInclusiveAmount>{total}</cbc:TaxInclusiveAmount><cbc:PayableAmount>{total}</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>
""",
        encoding="utf-8",
    )


def queue_invoice(store: JsonWorkflowStore, xml_path: Path, *, document_type: str = "einvoice_xml") -> None:
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
            "document_type": document_type,
            "original_file_name": xml_path.name,
            "storage_path": str(xml_path),
            "status": "stored",
        },
    )
    store.create_processing_job(
        client_id="client-1",
        document_ref="xml-doc",
        document_type=document_type,
        parser_kind=parser_kind_for_document_type(document_type),
    )


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

    def test_research_harness_can_bypass_cache_for_forced_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_brand_research_profile(
                brand_name="Rexton",
                profile={
                    "display_name": "Rexton",
                    "summary_tr": "",
                    "confidence": 0,
                    "source_urls": [],
                },
            )
            provider = FakeResearchProvider(
                {
                    "display_name": "Rexton",
                    "summary_tr": "Rexton isitme cihazi markasidir.",
                    "confidence": 75,
                    "evidence": [{"url": "https://www.rexton.com/", "summary_tr": "Uretici sitesi."}],
                }
            )
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_brand(
                raw_line="Rexton isitme cihazi",
                supplier_hint="Rexton",
                activity_context="isitme merkezi",
                bypass_cache=True,
            )

        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(profile["summary_tr"], "Rexton isitme cihazi markasidir.")
        self.assertEqual(profile["confidence"], 75)

    def test_research_harness_does_not_bypass_accountant_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_brand_research_profile(
                brand_name="Rexton",
                profile={
                    "display_name": "Rexton",
                    "summary_tr": "Musavir karari.",
                    "common_product_categories": ["isitme_cihazi"],
                    "account_treatment": "stock_or_cogs",
                    "override": True,
                    "confidence": 100,
                },
            )
            provider = FakeResearchProvider({"display_name": "Rexton", "confidence": 40})
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_brand(
                raw_line="Rexton isitme cihazi",
                supplier_hint="Rexton",
                activity_context="isitme merkezi",
                bypass_cache=True,
            )

        self.assertEqual(provider.queries, [])
        self.assertTrue(profile["override"])
        self.assertEqual(profile["research_confidence"], 100)
        self.assertEqual(profile["accounting_impact_confidence"], 100)

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
        self.assertEqual(updated["research_profile"]["research_confidence"], 69)

    def test_apply_research_to_result_uses_accounting_impact_confidence(self) -> None:
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
                "summary_tr": "Kaynak iyi ama muhasebe etkisi belirsiz.",
                "common_product_categories": ["bilinmeyen"],
                "research_confidence": 85,
                "accounting_impact_confidence": 60,
                "evidence": [{"url": "https://manufacturer.example/product", "summary_tr": "Urun sayfasi."}],
            },
        )

        updated = apply_research_to_result(result, profile, confidence_threshold=70)

        self.assertEqual(updated["export_status"], "review_required")
        self.assertIn("research_accounting_impact_low_confidence", updated["review_reason_codes"])


    def test_build_research_runtime_from_env_is_openai_only_and_disabled_without_key(self) -> None:
        self.assertIsNone(build_research_runtime_from_env({"FISORA_RESEARCH_ENABLED": "true"}))
        self.assertIsNone(
            build_research_runtime_from_env(
                {
                    "FISORA_RESEARCH_ENABLED": "true",
                    "OPENAI_API_KEY": "sk-or-v1-not-openai",
                }
            )
        )
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

    def test_build_research_runtime_from_env_supports_tavily_without_openai_key(self) -> None:
        runtime = build_research_runtime_from_env(
            {
                "FISORA_RESEARCH_ENABLED": "true",
                "FISORA_RESEARCH_PROVIDER": "tavily",
                "TAVILY_API_KEY": "tvly-test",
                "FISORA_RESEARCH_MAX_PER_DOCUMENT": "2",
            }
        )

        self.assertEqual(runtime["policy"].max_per_document, 2)
        self.assertEqual(runtime["provider"].provider_name, "tavily_search")

    def test_tavily_provider_maps_search_results_to_research_profile_payload(self) -> None:
        http_client = FakeHttpClient(
            {
                "answer": "Rexton isitme cihazlari ve aksesuarları ureten bir markadir.",
                "results": [
                    {
                        "title": "Rexton hearing aids",
                        "url": "https://www.rexton.com/hearing-aids/",
                        "content": "Rexton hearing aids and accessories.",
                    },
                    {
                        "title": "Marketplace listing",
                        "url": "https://www.trendyol.com/rexton/urun",
                        "content": "Pazaryeri urun listesi.",
                    },
                ],
            }
        )
        provider = TavilySearchResearchProvider(api_key="tvly-test", http_client=http_client)

        payload = provider.research(
            ResearchQuery(
                kind="brand",
                key="Rexton",
                search_text="Rexton isitme cihazi",
                supplier_hint="Rexton",
                activity_context="isitme merkezi",
            )
        )
        profile = normalize_research_profile(kind="brand", key="Rexton", payload=payload)

        request = http_client.requests[0]
        self.assertEqual(request["url"], "https://api.tavily.com/search")
        self.assertEqual(request["headers"]["Authorization"], "Bearer tvly-test")
        self.assertEqual(request["json"]["max_results"], 5)
        self.assertIn("Rexton isitme cihazi", request["json"]["query"])
        self.assertEqual(profile["summary_tr"], "Rexton isitme cihazlari ve aksesuarları ureten bir markadir.")
        self.assertEqual(profile["confidence"], 85)
        self.assertEqual(profile["research_confidence"], 85)
        self.assertEqual(profile["accounting_impact_confidence"], 90)
        self.assertEqual(profile["common_product_categories"], ["isitme_cihazi"])
        self.assertEqual(profile["account_treatment"], "stock_or_cogs")
        self.assertEqual(profile["source_urls"], ["https://www.rexton.com/hearing-aids/"])
        self.assertEqual(profile["evidence"][1]["accepted"], False)

    def test_tavily_research_confidence_scoring_tiers(self) -> None:
        accepted_result = {"results": [{"url": "https://www.rexton.com/", "content": "Rexton hearing aids."}]}
        rejected_result = {
            "answer": "Marketplace summary.",
            "results": [{"url": "https://www.trendyol.com/rexton", "content": "x"}],
        }

        accepted_profile = normalize_research_profile(
            kind="brand",
            key="Rexton",
            payload=TavilySearchResearchProvider(api_key="tvly-test", http_client=FakeHttpClient(accepted_result)).research(
                ResearchQuery(kind="brand", key="Rexton", search_text="Rexton isitme cihazi")
            ),
        )
        rejected_profile = normalize_research_profile(
            kind="brand",
            key="Rexton",
            payload=TavilySearchResearchProvider(api_key="tvly-test", http_client=FakeHttpClient(rejected_result)).research(
                ResearchQuery(kind="brand", key="Rexton", search_text="Rexton unknown")
            ),
        )

        self.assertEqual(accepted_profile["research_confidence"], 65)
        self.assertEqual(rejected_profile["research_confidence"], 40)

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
        self.assertEqual(override.json()["profile"]["research_confidence"], 100)
        self.assertEqual(override.json()["profile"]["accounting_impact_confidence"], 100)
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(benchmark.status_code, 200)
        self.assertGreaterEqual(benchmark.json()["run"]["case_count"], 3)
        self.assertIn("brand_accuracy", benchmark.json()["run"]["metrics"])
        self.assertIn("category_accuracy", benchmark.json()["run"]["metrics"])
        self.assertIn("accounting_impact_accuracy", benchmark.json()["run"]["metrics"])
        self.assertIn("review_gate_accuracy", benchmark.json()["run"]["metrics"])
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

    def test_worker_skips_research_for_high_confidence_known_invoice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "known.xml"
            write_invoice_xml(xml_path, line_name="Rexton RLi 20 isitme cihazi", supplier_name="Rexton Medikal")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            provider = FakeResearchProvider({"display_name": "Should Not Call", "confidence": 99})

            process_queued_documents(
                store,
                research_runtime={"provider": provider, "policy": ResearchPolicy(enabled=True, confidence_threshold=70)},
            )
            workspace = store.get_workspace("client-1")
            result = workspace["documents"][0]["result"]
            pipeline_steps = [event["step"] for event in workspace["document_pipeline_events"]]

        self.assertEqual(provider.queries, [])
        self.assertNotIn("research_started", pipeline_steps)
        self.assertNotIn("research_profile", result)

    def test_worker_applies_research_category_to_accounting_impact_for_uncertain_invoice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "uncertain.xml"
            write_invoice_xml(xml_path, line_name="Mystery Sonic Pro bakim seti", supplier_name="Acme A.S.")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            provider = FakeResearchProvider(
                {
                    "display_name": "Mystery Sonic",
                    "summary_tr": "Isitme cihazi aksesuaridir.",
                    "common_product_categories": ["isitme_cihazi"],
                    "account_treatment": "stock_or_cogs",
                    "research_confidence": 85,
                    "accounting_impact_confidence": 90,
                    "evidence": [{"url": "https://manufacturer.example/mystery", "summary_tr": "Uretici sayfasi."}],
                }
            )

            process_queued_documents(
                store,
                research_runtime={"provider": provider, "policy": ResearchPolicy(enabled=True, confidence_threshold=70)},
            )
            result = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(result["product_category"], "isitme_cihazi")
        self.assertEqual(result["business_relevance_account_treatment"], "stock_or_cogs")
        self.assertEqual(result["research_profile"]["accounting_impact_confidence"], 90)


if __name__ == "__main__":
    unittest.main()
