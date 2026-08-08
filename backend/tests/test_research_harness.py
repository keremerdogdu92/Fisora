from __future__ import annotations

from pathlib import Path
import inspect
import sys
import tempfile
import threading
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
from app.domain.ai_classification import AiClassificationPolicy, AiClassificationRequest, StaticFirstClassifier
from app.domain.product_research_cache import non_authoritative_research_payload
from app.persistence.workflow_store import JsonWorkflowStore, ProcessingAttemptConflict
from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents

try:
    from fastapi.testclient import TestClient
    from app.api import phase0
    from app.api import phase0_routes_research
    from app.main import app
except Exception:  # pragma: no cover - optional FastAPI import guard
    TestClient = None
    phase0 = None
    phase0_routes_research = None
    app = None


class FakeResearchProvider:
    provider_name = "fake_research_agent"

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.queries: list[ResearchQuery] = []

    def research(self, query: ResearchQuery) -> dict[str, object]:
        self.queries.append(query)
        return self.payload


class FakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[AiClassificationRequest] = []

    def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.response


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


def write_invoice_xml(
    path: Path,
    *,
    line_name: str,
    supplier_name: str = "Acme A.S.",
    total: str = "1200.00",
    line_names: tuple[str, ...] | None = None,
) -> None:
    invoice_lines = "\n".join(
        f"  <cac:InvoiceLine><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity><cac:Item><cbc:Name>{name}</cbc:Name></cac:Item></cac:InvoiceLine>"
        for name in (line_names if line_names is not None else (line_name,))
    )
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC202600000001</cbc:ID>
  <cbc:IssueDate>2026-05-03</cbc:IssueDate>
  <cbc:InvoiceTypeCode>ALIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>{supplier_name}</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyTaxScheme><cbc:CompanyID>1111111111</cbc:CompanyID></cac:PartyTaxScheme></cac:Party></cac:AccountingCustomerParty>
{invoice_lines}
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
            "intake_category": "purchase_invoice",
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
        intake_category="purchase_invoice",
    )


class ResearchHarnessTests(unittest.TestCase):
    def test_provider_cannot_forge_accountant_override_or_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            provider = FakeResearchProvider(
                {
                    "override": True,
                    "override_actor": "forged",
                    "summary_tr": "Provider supplied override.",
                    "evidence": [{"url": "https://manufacturer.example/item", "summary_tr": "Real claim."}],
                }
            )
            profile = ResearchHarness(
                store=store,
                provider=provider,
                policy=ResearchPolicy(enabled=True),
            ).research_brand(
                raw_line="Scoped item",
                canonical_line_ids=["line-1"],
                cache_scope="client-1",
            )

        self.assertFalse(profile["override"])
        self.assertNotEqual(profile["research_confidence"], 100)
        self.assertEqual(profile["client_id"], "client-1")
        self.assertTrue(str(profile["profile_id"]).startswith("ctxv2"))
        self.assertEqual(profile["display_key"], "scoped item")

    def test_research_profile_sanitizes_summary_and_url_path_and_requires_a_claim(self) -> None:
        profile = normalize_research_profile(
            kind="brand",
            key="private item",
            payload={
                "summary_tr": "Contact ali@example.com or +90 555 111 22 33.",
                "canonical_line_ids": ["line-1"],
                "evidence": [
                    {
                        "url": "https://manufacturer.example/customer/ali@example.com?token=secret",
                        "summary_tr": "",
                        "claim": "",
                    }
                ],
            },
        )

        self.assertNotIn("ali@example.com", profile["summary_tr"])
        self.assertNotIn("ali@example.com", profile["evidence"][0]["url"])
        self.assertNotIn("token", profile["evidence"][0]["url"])
        self.assertEqual(profile["research_evidence"], [])
        self.assertIn("insufficient-evidence", profile["evidence_gaps"])

    def test_research_profile_rejects_title_only_evidence_and_redacts_identifier_paths(self) -> None:
        profile = normalize_research_profile(
            kind="brand",
            key="private item",
            payload={
                "canonical_line_ids": ["line-1"],
                "evidence": [
                    {
                        "url": "https://manufacturer.example/customer/12345678901/document",
                        "title": "Private item product page",
                    }
                ],
            },
        )

        self.assertEqual(profile["evidence"][0]["url"], "https://manufacturer.example/")
        self.assertFalse(profile["evidence"][0]["accepted"])
        self.assertEqual(profile["research_evidence"], [])
        self.assertIn("insufficient-evidence", profile["evidence_gaps"])

    def test_expired_research_cache_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "store.json")
            query = sanitize_research_query(
                kind="brand",
                raw_line="Scoped item",
                canonical_line_ids=["line-1"],
            )
            from app.domain.research_harness import research_brand_cache_key

            cache_key = research_brand_cache_key(query, cache_scope="client-1")
            store.save_brand_research_profile(
                brand_name=cache_key,
                profile={
                    "profile_id": cache_key,
                    "display_key": "scoped item",
                    "client_id": "client-1",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                    "summary_tr": "Expired.",
                },
            )
            provider = FakeResearchProvider(
                {
                    "summary_tr": "Fresh claim.",
                    "evidence": [{"url": "https://manufacturer.example/item", "summary_tr": "Fresh claim."}],
                }
            )
            profile = ResearchHarness(
                store=store,
                provider=provider,
                policy=ResearchPolicy(enabled=True),
            ).research_brand(
                raw_line="Scoped item",
                canonical_line_ids=["line-1"],
                cache_scope="client-1",
            )

        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(profile["summary_tr"], "Fresh claim.")

    @staticmethod
    def _semantic_attempt(attempt_id: str, *, model: str = "fake-model") -> dict[str, object]:
        return {
            "attempt_id": attempt_id,
            "stage": "initial_account_decision",
            "canonical_line_ids": ["line-1"],
            "prompt_version": "semantic-v1",
            "provider": "fake_llm",
            "model": model,
            "candidate_account_codes": ["770.01"],
            "candidate_counterparty_codes": ["320.01"],
            "validated_response": {"suggested_account_code": "770.01"},
            "validation_errors": [],
            "accepted": False,
            "superseded_by_attempt_id": "",
        }

    def test_json_store_serializes_concurrent_semantic_attempt_merges_on_one_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            original_read = store._read
            first_read = threading.Event()
            second_read = threading.Event()
            release_first = threading.Event()
            read_count = 0
            counter_lock = threading.Lock()
            errors: list[BaseException] = []

            def controlled_read() -> dict[str, object]:
                nonlocal read_count
                data = original_read()
                with counter_lock:
                    read_count += 1
                    current_read = read_count
                if current_read == 1:
                    first_read.set()
                    release_first.wait(timeout=2)
                elif current_read == 2:
                    second_read.set()
                return data

            store._read = controlled_read  # type: ignore[method-assign]

            def save(attempt_id: str) -> None:
                try:
                    store.save_simulation_result(
                        client_id="client-1",
                        document_ref="doc-1",
                        result={
                            "semantic_attempts": [self._semantic_attempt(attempt_id)],
                            "accepted_semantic_attempt_id": "",
                        },
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            first = threading.Thread(target=save, args=("attempt-first",))
            second = threading.Thread(target=save, args=("attempt-second",))
            first.start()
            self.assertTrue(first_read.wait(timeout=1))
            second.start()
            second_read.wait(timeout=0.2)
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            stored = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(
            {item["attempt_id"] for item in stored["semantic_attempts"]},
            {"attempt-first", "attempt-second"},
        )

    def test_json_store_conflicting_semantic_attempt_leaves_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(store_path)
            store.save_simulation_result(
                client_id="client-1",
                document_ref="doc-1",
                result={
                    "semantic_attempts": [self._semantic_attempt("attempt-conflict")],
                    "accepted_semantic_attempt_id": "",
                },
            )
            before = store_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "semantic attempt_id conflict"):
                store.save_simulation_result(
                    client_id="client-1",
                    document_ref="doc-1",
                    result={
                        "semantic_attempts": [
                            self._semantic_attempt("attempt-conflict", model="different-model")
                        ],
                        "accepted_semantic_attempt_id": "",
                    },
                )

            self.assertEqual(store_path.read_bytes(), before)

    def test_json_store_processing_attempt_retry_is_idempotent_and_digest_conflict_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(store_path)
            result = {
                "accountant_summary": "first input",
                "semantic_attempts": [self._semantic_attempt("semantic-attempt")],
                "accepted_semantic_attempt_id": "",
            }
            first = store.save_simulation_result(
                client_id="client-1",
                document_ref="doc-1",
                result=result,
                attempt_id="processing-attempt",
            )
            before_retry = store_path.read_bytes()

            retried = store.save_simulation_result(
                client_id="client-1",
                document_ref="doc-1",
                result=result,
                attempt_id="processing-attempt",
            )

            self.assertEqual(retried, first)
            self.assertEqual(store_path.read_bytes(), before_retry)
            with self.assertRaisesRegex(
                ProcessingAttemptConflict,
                "processing attempt input conflict",
            ):
                store.save_simulation_result(
                    client_id="client-1",
                    document_ref="doc-1",
                    result={**result, "accountant_summary": "conflicting input"},
                    attempt_id="processing-attempt",
                )
            self.assertEqual(store_path.read_bytes(), before_retry)

    def test_postgres_document_lock_key_is_stable_and_scope_sensitive(self) -> None:
        from app.persistence.postgres_workflow_store import workflow_document_lock_key

        baseline = workflow_document_lock_key("tenant-a", "client-a", "document-a")
        self.assertEqual(
            baseline,
            workflow_document_lock_key("tenant-a", "client-a", "document-a"),
        )
        self.assertNotEqual(
            baseline,
            workflow_document_lock_key("tenant-b", "client-a", "document-a"),
        )
        self.assertNotEqual(
            baseline,
            workflow_document_lock_key("tenant-a", "client-b", "document-a"),
        )
        self.assertNotEqual(
            baseline,
            workflow_document_lock_key("tenant-a", "client-a", "document-b"),
        )

    def test_postgres_simulation_save_locks_then_reads_then_writes_on_one_connection(self) -> None:
        events: list[str] = []

        class RecordingCursor:
            def __enter__(self) -> "RecordingCursor":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def execute(self, query: str, params: object = ()) -> None:
                events.append(" ".join(query.lower().split()))

            def fetchone(self) -> None:
                return None

        class RecordingConnection:
            def __enter__(self) -> "RecordingConnection":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def cursor(self) -> RecordingCursor:
                return RecordingCursor()

        class RecordingStore(PostgresWorkflowStore):
            @staticmethod
            def _json(value: object) -> object:
                return value

        store = RecordingStore(
            "postgresql://unused",
            tenant_key="tenant-a",
            connect=RecordingConnection,
        )
        store.save_simulation_result(
            client_id="client-a",
            document_ref="document-a",
            result={"semantic_attempts": [], "accepted_semantic_attempt_id": ""},
        )

        lock_index = next(
            index for index, query in enumerate(events) if "pg_advisory_xact_lock" in query
        )
        read_index = next(
            index
            for index, query in enumerate(events)
            if "select payload from workflow_records" in query
        )
        write_index = next(
            index
            for index, query in enumerate(events)
            if "insert into workflow_records" in query
        )
        self.assertLess(lock_index, read_index)
        self.assertLess(read_index, write_index)

    def test_json_store_appends_sanitized_semantic_attempt_history_across_result_persistence(self) -> None:
        def attempt(
            attempt_id: str,
            stage: str,
            *,
            accepted: bool,
            superseded_by_attempt_id: str = "",
        ) -> dict[str, object]:
            return {
                "attempt_id": attempt_id,
                "stage": stage,
                "canonical_line_ids": ["line-1"],
                "prompt_version": "semantic-v1",
                "provider": "fake_llm",
                "model": "fake-model",
                "candidate_account_codes": ["153.01", "770.01"],
                "candidate_counterparty_codes": ["320.01"],
                "validated_response": {
                    "suggested_account_code": "153.01",
                    "authorization": "Bearer private-provider-secret",
                },
                "validation_errors": [],
                "accepted": accepted,
                "superseded_by_attempt_id": superseded_by_attempt_id,
                "raw_private_document": "complete-private-invoice",
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_simulation_result(
                client_id="client-1",
                document_ref="doc-1",
                result={
                    "semantic_attempts": [
                        attempt("attempt-initial", "initial_account_decision", accepted=False),
                        attempt("attempt-research", "research_synthesis", accepted=False),
                    ],
                    "accepted_semantic_attempt_id": "",
                },
            )
            store.save_simulation_result(
                client_id="client-1",
                document_ref="doc-1",
                result={
                    "semantic_attempts": [
                        attempt("attempt-correction", "account_correction", accepted=True),
                    ],
                    "accepted_semantic_attempt_id": "attempt-correction",
                },
            )
            stored = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(
            [item["stage"] for item in stored["semantic_attempts"]],
            ["initial_account_decision", "research_synthesis", "account_correction"],
        )
        self.assertEqual(stored["semantic_attempts"][0]["accepted"], False)
        self.assertEqual(stored["semantic_attempts"][-1]["accepted"], True)
        self.assertTrue(stored["semantic_attempts"][0]["candidate_account_codes"])
        self.assertEqual(stored["accepted_semantic_attempt_id"], "attempt-correction")
        self.assertNotIn("private-provider-secret", str(stored))
        self.assertNotIn("complete-private-invoice", str(stored))

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

    def test_research_profile_contains_line_and_source_scoped_non_authoritative_evidence(self) -> None:
        profile = normalize_research_profile(
            kind="brand",
            key="Muson cosmetics",
            payload={
                "question": "Muson Stick Contour VKN 1234567890 Fatura ABC2026000000001",
                "canonical_line_ids": ["line-1"],
                "common_product_categories": ["kargo"],
                "authoritative_product_category": "kargo",
                "selected_account_code": "760.03.010",
                "research_confidence": 90,
                "conflicts": ["Retailer shipping text conflicts with manufacturer product identity."],
                "evidence": [
                    {
                        "url": "https://musoncosmetics.example/products/stick-contour",
                        "source_type": "manufacturer",
                        "summary_tr": "Stick contour is a cosmetics product.",
                        "raw_summary": "Stick contour is a cosmetics product; fast shipping is available.",
                        "confidence": 92,
                    },
                    {
                        "url": "https://retailer.example/muson-stick-contour",
                        "source_type": "shipping_widget",
                        "summary_tr": "Fast shipping and delivery navigation.",
                        "confidence": 30,
                    },
                ],
            },
        )

        self.assertIn("research_evidence", profile)
        evidence_item = profile["research_evidence"][0]
        self.assertEqual(evidence_item["canonical_line_ids"], ["line-1"])
        self.assertEqual(evidence_item["question"], "Muson Stick Contour")
        self.assertIn("source_url", evidence_item)
        self.assertEqual(evidence_item["source_domain"], "musoncosmetics.example")
        self.assertEqual(evidence_item["source_kind"], "manufacturer")
        self.assertEqual(evidence_item["claims"][0]["source_kind"], "manufacturer")
        self.assertIn(evidence_item["claims"][0]["source_kind"], {"official", "manufacturer", "retailer", "other"})
        self.assertEqual(profile["research_evidence"][1]["source_kind"], "other")
        self.assertEqual(evidence_item["conflicts"], ["Retailer shipping text conflicts with manufacturer product identity."])
        self.assertIn("fast shipping", evidence_item["raw_summary"])
        self.assertNotIn("authoritative_product_category", profile)
        self.assertNotIn("selected_account_code", profile)
        self.assertNotIn("classification_override", profile)
        self.assertNotIn("product_category", profile)
        self.assertNotIn("account_treatment", profile)

    def test_research_payload_recursively_strips_authority_fields(self) -> None:
        payload = non_authoritative_research_payload(
            {
                "display_name": "Safe display",
                "selected_account_code": "760.01",
                "nested": {
                    "classification_override": {"category": "kargo"},
                    "items": [
                        {"authoritative_product_category": "kargo", "claim": "safe claim"},
                        {"selected_expense_account": "770.01"},
                    ],
                },
            }
        )

        self.assertEqual(payload["display_name"], "Safe display")
        self.assertNotIn("selected_account_code", str(payload))
        self.assertNotIn("classification_override", str(payload))
        self.assertNotIn("authoritative_product_category", str(payload))
        self.assertNotIn("selected_expense_account", str(payload))

    def test_research_evidence_requires_canonical_line_scope_and_sourced_claim(self) -> None:
        missing_line_scope = normalize_research_profile(
            kind="brand",
            key="Scoped product",
            payload={
                "question": "Scoped product",
                "research_confidence": 95,
                "evidence": [
                    {
                        "url": "https://manufacturer.example/product",
                        "source_type": "manufacturer",
                        "summary_tr": "Manufacturer evidence.",
                    }
                ],
            },
        )
        missing_source = normalize_research_profile(
            kind="brand",
            key="Unsourced product",
            payload={
                "question": "Unsourced product",
                "canonical_line_ids": ["line-1"],
                "research_confidence": 95,
                "evidence": [{"summary_tr": "Claim without a source URL."}],
            },
        )

        self.assertEqual(missing_line_scope["research_evidence"], [])
        self.assertIn("line-missing", missing_line_scope["evidence_gaps"])
        self.assertEqual(missing_source["research_evidence"], [])
        self.assertIn("insufficient-evidence", missing_source["evidence_gaps"])

    def test_claim_confidence_is_source_local_and_rejected_sources_do_not_inherit_profile_confidence(self) -> None:
        profile = normalize_research_profile(
            kind="brand",
            key="Source confidence product",
            payload={
                "question": "Source confidence product",
                "canonical_line_ids": ["line-1"],
                "research_confidence": 97,
                "evidence": [
                    {
                        "url": "https://manufacturer.example/product",
                        "source_type": "manufacturer",
                        "summary_tr": "Accepted source without local confidence.",
                    },
                    {
                        "url": "https://www.trendyol.com/product",
                        "source_type": "retailer",
                        "summary_tr": "Rejected source without local confidence.",
                    },
                ],
            },
        )

        self.assertEqual(profile["research_evidence"][0]["confidence"], 0)
        self.assertEqual(profile["research_evidence"][1]["confidence"], 0)
        self.assertTrue(profile["research_evidence"][0]["accepted"])
        self.assertFalse(profile["research_evidence"][1]["accepted"])

    def test_source_policy_uses_hostname_boundaries_and_safe_url_parsing(self) -> None:
        self.assertFalse(source_policy_accepts("https://agency.gov.tr.evil.example/product"))
        self.assertFalse(source_policy_accepts("https://ec.europa.eu.evil.example/product"))
        self.assertTrue(source_policy_accepts("HTTPS://user:password@EC.EUROPA.EU:443/product"))

        profile = normalize_research_profile(
            kind="brand",
            key="Official product",
            payload={
                "question": "Official product",
                "canonical_line_ids": ["line-1"],
                "evidence": [
                    {
                        "url": "HTTPS://user:password@EC.EUROPA.EU:443/product?email=private@example.com",
                        "source_type": "shipping_widget",
                        "summary_tr": "Official source.",
                        "confidence": 80,
                    }
                ],
            },
        )

        claim = profile["research_evidence"][0]["claims"][0]
        self.assertEqual(claim["source_domain"], "ec.europa.eu")
        self.assertEqual(claim["source_kind"], "official")
        self.assertNotIn("user:password", claim["source_url"])
        self.assertNotIn("private@example.com", claim["source_url"])

    def test_research_evidence_redacts_email_and_phone_but_keeps_product_identity(self) -> None:
        profile = normalize_research_profile(
            kind="brand",
            key="Muson Stick Contour",
            payload={
                "question": "Muson Stick Contour info@example.com +90 532 123 45 67",
                "canonical_line_ids": ["line-1"],
                "evidence": [
                    {
                        "url": "https://manufacturer.example/product",
                        "source_type": "manufacturer",
                        "claim": "Muson Stick Contour destek@example.com 0532 123 45 67",
                        "summary_tr": "Muson Stick Contour kozmetik urunudur. Telefon 0212 555 44 33.",
                        "raw_summary": "Muson Stick Contour kozmetik urunudur; +44 20 7946 0958 veya raw@example.com.",
                        "confidence": 80,
                    }
                ],
            },
        )

        evidence_text = str(profile["research_evidence"])
        self.assertIn("Muson Stick Contour", evidence_text)
        self.assertNotIn("@", evidence_text)
        self.assertNotIn("0532 123 45 67", evidence_text)
        self.assertNotIn("0212 555 44 33", evidence_text)
        self.assertNotIn("+44 20 7946 0958", evidence_text)

    def test_source_policy_rejects_marketplaces_and_accepts_official_or_manufacturer_sources(self) -> None:
        self.assertFalse(source_policy_accepts("https://www.trendyol.com/blendax/sampuan"))
        self.assertFalse(source_policy_accepts("https://blog.example.com/en-iyi-sampuan"))
        self.assertTrue(source_policy_accepts("https://www.blendax.com.tr/urunler/sampuan"))
        self.assertTrue(source_policy_accepts("https://ec.europa.eu/eurostat/web/nace/overview"))

    def test_research_harness_cache_hit_reuses_store_profile_without_calling_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            first_provider = FakeResearchProvider(
                {
                    "display_name": "Blendax",
                    "brand_summary": "Sampuan markasi.",
                    "common_product_categories": ["kisisel_bakim_kozmetik"],
                    "authoritative_product_category": "kargo",
                    "selected_account_code": "760.03.010",
                    "confidence": 88,
                    "evidence": [
                        {
                            "url": "https://www.blendax.com.tr/",
                            "source_type": "manufacturer",
                            "summary_tr": "Sampuan urun sayfasi.",
                        }
                    ],
                }
            )
            ResearchHarness(store=store, provider=first_provider, policy=ResearchPolicy(enabled=True)).research_brand(
                raw_line="Blendax sac bakim seti",
                supplier_hint="Acme Kozmetik",
                activity_context="Isitme merkezi",
                canonical_line_ids=["line-first"],
            )
            provider = FakeResearchProvider({"display_name": "Blendax", "confidence": 99})
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_brand(
                raw_line="Blendax sac bakim seti",
                supplier_hint="Acme Kozmetik",
                activity_context="Isitme merkezi",
                canonical_line_ids=["line-current"],
            )

        self.assertEqual(profile["brand_summary"], "Sampuan markasi.")
        self.assertEqual(provider.queries, [])
        self.assertIn("cache_provenance", profile)
        self.assertTrue(profile["cache_provenance"]["hit"])
        self.assertTrue(profile["cache_provenance"]["key"].startswith("ctxv2"))
        self.assertEqual(profile["canonical_line_ids"], ["line-current"])
        self.assertNotIn("authoritative_product_category", profile)
        self.assertNotIn("selected_account_code", profile)

    def test_research_cache_is_digest_scoped_by_client_supplier_activity_and_lookup(self) -> None:
        payload = {
            "display_name": "Scoped Product",
            "summary_tr": "Scoped manufacturer evidence.",
            "research_confidence": 80,
            "evidence": [
                {
                    "url": "https://manufacturer.example/scoped-product",
                    "source_type": "manufacturer",
                    "summary_tr": "Scoped manufacturer evidence.",
                    "confidence": 80,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            first_provider = FakeResearchProvider(payload)
            first = ResearchHarness(store=store, provider=first_provider, policy=ResearchPolicy(enabled=True))
            first_profile = first.research_brand(
                raw_line="Scoped Product X1",
                supplier_hint="Supplier Alpha",
                activity_context="Medical retail",
                canonical_line_ids=["line-a"],
                cache_scope="client-a",
            )

            same_provider = FakeResearchProvider({"display_name": "Should not call"})
            same = ResearchHarness(store=store, provider=same_provider, policy=ResearchPolicy(enabled=True))
            same_profile = same.research_brand(
                raw_line="Scoped Product X1",
                supplier_hint="Supplier Alpha",
                activity_context="Medical retail",
                canonical_line_ids=["line-b"],
                cache_scope="client-a",
            )

            other_provider = FakeResearchProvider(payload)
            other = ResearchHarness(store=store, provider=other_provider, policy=ResearchPolicy(enabled=True))
            other_profile = other.research_brand(
                raw_line="Scoped Product X1",
                supplier_hint="Supplier Alpha",
                activity_context="Cosmetics retail",
                canonical_line_ids=["line-c"],
                cache_scope="client-b",
            )

        self.assertEqual(len(first_provider.queries), 1)
        self.assertEqual(same_provider.queries, [])
        self.assertEqual(len(other_provider.queries), 1)
        self.assertTrue(same_profile["cache_provenance"]["hit"])
        self.assertEqual(same_profile["canonical_line_ids"], ["line-b"])
        self.assertNotEqual(
            first_profile["cache_provenance"]["key"],
            other_profile["cache_provenance"]["key"],
        )
        cache_key = first_profile["cache_provenance"]["key"]
        self.assertTrue(cache_key.startswith("ctxv2"))
        self.assertNotIn("supplier", cache_key)
        self.assertNotIn("medical", cache_key)

    def test_research_cache_contract_accepts_private_client_scope(self) -> None:
        self.assertIn("cache_scope", inspect.signature(ResearchHarness.research_brand).parameters)

    def test_research_harness_uses_full_product_phrase_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            first_provider = FakeResearchProvider(
                {
                    "display_name": "ZX Sonic Pro 9",
                    "summary_tr": "Daha once arastirilmis model.",
                    "common_product_categories": ["isitme_cihazi"],
                    "research_confidence": 88,
                    "accounting_impact_confidence": 90,
                    "evidence": [{"url": "https://manufacturer.example/zx-sonic-pro-9", "summary_tr": "Uretici sayfasi."}],
                }
            )
            ResearchHarness(store=store, provider=first_provider, policy=ResearchPolicy(enabled=True)).research_brand(
                raw_line="ZX Sonic Pro 9",
                supplier_hint="Medikal",
                canonical_line_ids=["line-first"],
            )
            provider = FakeResearchProvider({"display_name": "Should Not Call", "confidence": 99})
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_brand(
                raw_line="ZX Sonic Pro 9",
                supplier_hint="Medikal",
                canonical_line_ids=["line-current"],
            )

        self.assertEqual(profile["display_name"], "ZX Sonic Pro 9")
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

    def test_forced_research_refresh_preserves_accountant_override_without_skipping_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            from app.domain.research_harness import research_brand_cache_key

            query = sanitize_research_query(
                kind="brand",
                raw_line="Rexton isitme cihazi",
                supplier_hint="Rexton",
                activity_context="isitme merkezi",
            )
            cache_key = research_brand_cache_key(query)
            store.save_brand_research_profile(
                brand_name=cache_key,
                profile=normalize_research_profile(
                    kind="brand",
                    key="Rexton isitme cihazi",
                    payload={
                    "display_name": "Rexton",
                    "summary_tr": "Musavir karari.",
                    "common_product_categories": ["isitme_cihazi"],
                    "account_treatment": "stock_or_cogs",
                    "override": True,
                    "override_actor": "mali-musavir",
                    "override_provenance": {"source": "accountant", "actor_id": "mali-musavir"},
                    "accountant_override": {"active": True, "actor_user_id": "mali-musavir"},
                    "profile_id": cache_key,
                    "confidence": 100,
                    },
                ),
            )
            provider = FakeResearchProvider({"display_name": "Rexton", "confidence": 40})
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_brand(
                raw_line="Rexton isitme cihazi",
                supplier_hint="Rexton",
                activity_context="isitme merkezi",
                canonical_line_ids=["line-current"],
                bypass_cache=True,
            )

        self.assertEqual(len(provider.queries), 1)
        self.assertTrue(profile["override"])
        self.assertEqual(profile["research_confidence"], 40)
        self.assertNotEqual(profile["accounting_impact_confidence"], 100)
        self.assertEqual(profile["accountant_override"]["actor_user_id"], "mali-musavir")

    def test_forced_nace_refresh_does_not_skip_provider_for_accountant_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            store.save_nace_research_profile(
                nace_code="477401",
                profile=normalize_research_profile(
                    kind="nace",
                    key="477401",
                    payload={
                        "summary_tr": "Musavir notu.",
                        "override": True,
                        "override_actor": "mali-musavir",
                        "override_provenance": {"source": "accountant", "actor_id": "mali-musavir"},
                        "accountant_override": {"active": True, "actor_user_id": "mali-musavir"},
                    },
                ),
            )
            provider = FakeResearchProvider(
                {
                    "summary_tr": "Fresh NACE scope claim.",
                    "evidence": [
                        {
                            "url": "https://ec.europa.eu/eurostat/web/nace/overview",
                            "summary_tr": "Medical retail scope.",
                        }
                    ],
                }
            )
            harness = ResearchHarness(store=store, provider=provider, policy=ResearchPolicy(enabled=True))

            profile = harness.research_nace(nace_code="477401", bypass_cache=True)

        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(profile["summary_tr"], "Fresh NACE scope claim.")

    def test_apply_research_to_result_never_mutates_readiness_statuses(self) -> None:
        result = {
            "export_status": "export_ready",
            "simulated_status": "auto_ready",
            "draft_status": "draft_ready",
            "review_reason_codes": [],
            "risk_flags": [],
        }
        profile = normalize_research_profile(
            kind="brand",
            key="unknown brand",
            payload={
                "display_name": "Unknown Brand",
                "brand_summary": "Kaynak zayif.",
                "canonical_line_ids": ["line-1"],
                "common_product_categories": ["bilinmeyen"],
                "confidence": 69,
                "evidence": [{"url": "https://www.trendyol.com/product", "summary_tr": "Urun sayfasi."}],
            },
        )

        updated = apply_research_to_result(result, profile, confidence_threshold=70)

        self.assertEqual(updated["export_status"], "export_ready")
        self.assertEqual(updated["simulated_status"], "auto_ready")
        self.assertEqual(updated["draft_status"], "draft_ready")
        self.assertEqual(updated["review_reason_codes"], [])
        self.assertEqual(updated["risk_flags"], [])
        self.assertIn("source-rejected", updated["research_evidence_gaps"])
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

        self.assertEqual(updated["export_status"], "export_ready")
        self.assertEqual(updated["review_reason_codes"], [])
        self.assertEqual(updated["research_quality"]["accounting_impact_confidence"], 60)

    def test_research_display_treatment_does_not_create_accounting_authority(self) -> None:
        result = {
            "export_status": "export_ready",
            "simulated_status": "auto_ready",
            "review_reason_codes": [],
            "risk_flags": [],
        }
        profile = normalize_research_profile(
            kind="brand",
            key="legacy cached product",
            payload={
                "question": "legacy cached product",
                "canonical_line_ids": ["line-1"],
                "common_product_categories": ["business_equipment"],
                "account_treatment": "fixed_asset_review",
                "research_confidence": 90,
                "accounting_impact_confidence": 90,
                "evidence": [
                    {
                        "url": "https://manufacturer.example/product",
                        "source_type": "manufacturer",
                        "summary_tr": "Manufacturer product evidence.",
                    }
                ],
            },
        )

        updated = apply_research_to_result(result, profile, confidence_threshold=70)

        self.assertEqual(updated["export_status"], "export_ready")
        self.assertNotIn("research_accounting_treatment_review", updated["review_reason_codes"])


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
        profile = normalize_research_profile(
            kind="brand",
            key="Rexton",
            payload={**payload, "canonical_line_ids": ["line-1"]},
        )

        request = http_client.requests[0]
        self.assertEqual(request["url"], "https://api.tavily.com/search")
        self.assertEqual(request["headers"]["Authorization"], "Bearer tvly-test")
        self.assertEqual(request["json"]["max_results"], 5)
        self.assertIn("Rexton isitme cihazi", request["json"]["query"])
        self.assertEqual(profile["summary_tr"], "Rexton isitme cihazlari ve aksesuarları ureten bir markadir.")
        self.assertEqual(profile["confidence"], 85)
        self.assertEqual(profile["research_confidence"], 85)
        self.assertEqual(profile["accounting_impact_confidence"], 40)
        self.assertEqual(profile["common_product_categories"], [])
        self.assertEqual(profile["non_authoritative_display"]["account_treatment"], "")
        self.assertEqual(profile["authority"], "evidence_only")
        self.assertTrue(profile["research_evidence"])
        self.assertEqual(
            profile["research_evidence"][0]["source_url"],
            "https://www.rexton.com/hearing-aids/",
        )
        self.assertEqual(profile["source_urls"], ["https://www.rexton.com/hearing-aids/"])
        self.assertEqual(profile["evidence"][1]["accepted"], False)

    def test_tavily_nace_research_uses_turkish_query_and_summary_fallback(self) -> None:
        http_client = FakeHttpClient(
            {
                "answer": "Retail sale of medical and orthopaedic goods in specialised stores.",
                "results": [
                    {
                        "title": "NACE Rev.2",
                        "url": "https://ec.europa.eu/eurostat/web/nace/overview",
                        "content": "Retail sale of medical and orthopaedic goods.",
                    }
                ],
            }
        )
        provider = TavilySearchResearchProvider(api_key="tvly-test", http_client=http_client)

        payload = provider.research(
            ResearchQuery(
                kind="nace",
                key="477401",
                search_text="NACE 477401 faaliyet kodu kapsami",
                activity_context="Tibbi ve ortopedik urunlerin perakende ticareti",
            )
        )

        request_query = http_client.requests[0]["json"]["query"]
        self.assertIn("Turkce", request_query)
        self.assertNotIn("business expenses", request_query)
        self.assertIn("477401 NACE kodu", payload["summary_tr"])
        self.assertIn("Tibbi ve ortopedik urunlerin perakende ticareti", payload["summary_tr"])

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
                        "profile_id": profiles.json()["profiles"][0]["profile_id"],
                        "category_tags": ["kisisel_bakim_kozmetik"],
                        "confidence": 92,
                        "expected_revision": detail.json()["profile"]["revision"],
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
        self.assertEqual(override.json()["profile"]["research_confidence"], 88)
        self.assertNotEqual(override.json()["profile"]["accounting_impact_confidence"], 100)
        self.assertTrue(override.json()["profile"]["accountant_override"]["active"])
        self.assertEqual(override.json()["profile"]["evidence"][0]["url"], "https://www.blendax.com.tr/")
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(benchmark.status_code, 200)
        self.assertGreaterEqual(benchmark.json()["run"]["case_count"], 3)
        self.assertIn("brand_accuracy", benchmark.json()["run"]["metrics"])
        self.assertIn("category_accuracy", benchmark.json()["run"]["metrics"])
        self.assertIn("accounting_impact_accuracy", benchmark.json()["run"]["metrics"])
        self.assertIn("review_gate_accuracy", benchmark.json()["run"]["metrics"])
        self.assertEqual(runs.json()["runs"][0]["run_type"], "benchmark")

    def test_research_api_filters_client_owned_profiles_and_addresses_opaque_id(self) -> None:
        if TestClient is None or phase0 is None or app is None:
            self.skipTest("FastAPI TestClient unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            original_store_path = phase0.DEFAULT_STORE_PATH
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
            store.upsert_portal_user(
                user_id="scoped-accountant",
                display_name="Scoped Accountant",
                role="accountant",
                allowed_client_ids=["client-1"],
            )
            for profile_id, client_id in (("ctxv2-one", "client-1"), ("ctxv2-two", "client-2")):
                store.save_brand_research_profile(
                    brand_name=profile_id,
                    profile=normalize_research_profile(
                        kind="brand",
                        key="same display",
                        payload={
                            "profile_id": profile_id,
                            "display_key": "same display",
                            "client_id": client_id,
                            "tenant_id": client_id,
                            "summary_tr": client_id,
                        },
                    ),
                )
            try:
                client = TestClient(app)
                headers = {"X-Fisora-User-Id": "scoped-accountant"}
                profiles = client.get("/phase0/store/research/profiles?kind=brand", headers=headers)
                allowed = client.get("/phase0/store/research/profile/brand/ctxv2-one", headers=headers)
                denied = client.get("/phase0/store/research/profile/brand/ctxv2-two", headers=headers)
                denied_override = client.post(
                    "/phase0/store/research/override",
                    headers=headers,
                    json={
                        "kind": "brand",
                        "key": "same display",
                        "profile_id": "ctxv2-two",
                        "expected_revision": 1,
                    },
                )
            finally:
                phase0.DEFAULT_STORE_PATH = original_store_path

        self.assertEqual([item["profile_id"] for item in profiles.json()["profiles"]], ["ctxv2-one"])
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied_override.status_code, 404)

    def test_research_override_requires_opaque_id_and_expected_revision(self) -> None:
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
            try:
                client = TestClient(app)
                response = client.post(
                    "/phase0/store/research/override",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={"kind": "brand", "key": "Blendax"},
                )
            finally:
                phase0.DEFAULT_STORE_PATH = original_store_path

        self.assertEqual(response.status_code, 428)

    def test_research_benchmark_reads_treatment_only_from_non_authoritative_display(self) -> None:
        if phase0_routes_research is None:
            self.skipTest("FastAPI research routes are not installed")

        nested_review = {
            "research_confidence": 90,
            "accounting_impact_confidence": 90,
            "non_authoritative_display": {"account_treatment": "fixed_asset_review"},
        }
        conflicting_legacy_alias = {
            "research_confidence": 90,
            "accounting_impact_confidence": 90,
            "account_treatment": "fixed_asset_review",
            "non_authoritative_display": {"account_treatment": "expense"},
        }

        self.assertTrue(phase0_routes_research._profile_review_required(nested_review))
        self.assertFalse(phase0_routes_research._profile_review_required(conflicting_legacy_alias))

    def test_research_api_refresh_invokes_nace_runtime_when_forced(self) -> None:
        if TestClient is None or phase0 is None or phase0_routes_research is None or app is None:
            self.skipTest("FastAPI TestClient unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            original_store_path = phase0.DEFAULT_STORE_PATH
            original_runtime_builder = phase0_routes_research.build_research_runtime_from_env
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
            store.upsert_portal_user(
                user_id="mali-musavir",
                display_name="Mali Musavir",
                role="accountant",
                allowed_client_ids=["*"],
            )
            provider = FakeResearchProvider(
                {
                    "display_name": "477401",
                    "summary_tr": "Isitme cihazi perakende faaliyet kapsami.",
                    "activity_tags": ["hearing_aid", "medical_retail"],
                    "confidence": 84,
                    "source_urls": ["https://ec.europa.eu/eurostat/web/nace/overview"],
                }
            )
            phase0_routes_research.build_research_runtime_from_env = lambda _env: {
                "provider": provider,
                "policy": ResearchPolicy(enabled=True, confidence_threshold=70),
            }
            try:
                client = TestClient(app)
                response = client.post(
                    "/phase0/store/research/refresh",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={
                        "kind": "nace",
                        "key": "47.74.01",
                        "activity_context": "Isitme cihazi satis ve servis",
                        "force": True,
                    },
                )
            finally:
                phase0.DEFAULT_STORE_PATH = original_store_path
                phase0_routes_research.build_research_runtime_from_env = original_runtime_builder

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "research_runtime")
        self.assertEqual(len(provider.queries), 1)
        self.assertEqual(provider.queries[0].kind, "nace")
        self.assertEqual(provider.queries[0].key, "477401")
        self.assertEqual(response.json()["profile"]["activity_tags"], ["hearing_aid", "medical_retail"])

    def test_research_api_unavailable_refresh_saves_back_to_opaque_storage_key(self) -> None:
        if TestClient is None or phase0 is None or phase0_routes_research is None or app is None:
            self.skipTest("FastAPI TestClient unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            original_store_path = phase0.DEFAULT_STORE_PATH
            original_runtime_builder = phase0_routes_research.build_research_runtime_from_env
            phase0.DEFAULT_STORE_PATH = Path(temp_dir) / "phase0_store.json"
            store = JsonWorkflowStore(phase0.DEFAULT_STORE_PATH)
            store.upsert_portal_user(
                user_id="mali-musavir",
                display_name="Mali Musavir",
                role="accountant",
                allowed_client_ids=["client-1"],
            )
            store.save_brand_research_profile(
                brand_name="ctxv2-one",
                profile=normalize_research_profile(
                    kind="brand",
                    key="Blendax",
                    payload={
                        "profile_id": "ctxv2-one",
                        "display_key": "Blendax",
                        "owner_client_id": "client-1",
                        "summary_tr": "cached evidence",
                    },
                ),
            )
            phase0_routes_research.build_research_runtime_from_env = lambda _env: None
            try:
                client = TestClient(app)
                response = client.post(
                    "/phase0/store/research/refresh",
                    headers={"X-Fisora-User-Id": "mali-musavir"},
                    json={
                        "kind": "brand",
                        "key": "Blendax",
                        "profile_id": "ctxv2-one",
                        "force": True,
                    },
                )
                opaque = store.get_brand_research_profile("ctxv2-one")
                display_alias = store.get_brand_research_profile("Blendax")
            finally:
                phase0.DEFAULT_STORE_PATH = original_store_path
                phase0_routes_research.build_research_runtime_from_env = original_runtime_builder

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "research_runtime_not_invoked")
        self.assertEqual(opaque["revision"], 2)
        self.assertIsNone(display_alias)

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
  <cac:AccountingCustomerParty><cac:Party><cac:PartyTaxScheme><cbc:CompanyID>1111111111</cbc:CompanyID></cac:PartyTaxScheme></cac:Party></cac:AccountingCustomerParty>
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
                intake_category="purchase_invoice",
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

    def test_worker_does_not_run_or_append_research_without_canonical_line_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "line-missing.xml"
            write_invoice_xml(
                xml_path,
                line_name="unused",
                line_names=(),
                supplier_name="Acme A.S.",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            provider = FakeResearchProvider(
                {
                    "display_name": "Unsafely scoped result",
                    "research_confidence": 95,
                    "evidence": [
                        {
                            "url": "https://manufacturer.example/product",
                            "source_type": "manufacturer",
                            "summary_tr": "Source without an invoice line scope.",
                            "confidence": 95,
                        }
                    ],
                }
            )

            process_queued_documents(
                store,
                research_runtime={
                    "provider": provider,
                    "policy": ResearchPolicy(enabled=True, confidence_threshold=70),
                },
            )
            result = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(provider.queries, [])
        self.assertEqual(result.get("research_evidence"), [])
        self.assertIn("line-missing", result.get("research_evidence_gaps") or [])
        self.assertNotIn(
            "research_synthesis",
            [item.get("stage") for item in result.get("semantic_attempts") or []],
        )

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

    def test_worker_keeps_research_category_as_evidence_for_uncertain_invoice(self) -> None:
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
        self.assertEqual(result["product_category"], "bilinmeyen")
        self.assertNotEqual(result.get("selected_expense_account"), "153.01")
        self.assertTrue(all(line.get("account_code") != "153.01" for line in result.get("draft_lines") or []))
        self.assertTrue(result["research_evidence"])
        self.assertEqual(result["research_profile"]["authority"], "evidence_only")
        self.assertEqual(
            result["research_profile"]["non_authoritative_display"]["product_category"],
            "isitme_cihazi",
        )
        self.assertEqual(result["research_profile"]["accounting_impact_confidence"], 90)

    def test_research_shipping_snippet_cannot_overwrite_cosmetics_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "muson-cosmetics.xml"
            write_invoice_xml(
                xml_path,
                line_name="Muson Stick Contour",
                line_names=("Muson Stick Contour", "Very Vanta Mascara"),
                supplier_name="Muson Kozmetik A.Ş.",
            )
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {"raw_account_code": "153.01", "normalized_account_code": "153.01", "account_name": "Ticari mallar", "is_detail_account": True, "is_active": True},
                    {"raw_account_code": "770.01", "normalized_account_code": "770.01", "account_name": "Genel yonetim giderleri", "is_detail_account": True, "is_active": True},
                    {"raw_account_code": "191.20", "normalized_account_code": "191.20", "account_name": "Indirilecek KDV yuzde 20", "is_detail_account": True, "is_active": True},
                    {"raw_account_code": "320.01", "normalized_account_code": "320.01", "account_name": "Muson Kozmetik", "is_detail_account": True, "is_active": True},
                ],
            )
            initial_response = {
                    "category": "kisisel_bakim_kozmetik",
                    "confidence": 91,
                    "reason": "Canonical satırlardaki stick contour ve mascara kozmetik ürünleridir.",
                    "evidence": ["ai:canonical_cosmetics_lines"],
                    "suggested_account_code": "153.01",
                    "suggested_counterparty_code": "320.01",
                    "risk_flags": [],
                    "account_reason": "Kozmetik sarf/gider hesabı adaylar arasından seçilmeli.",
                    "product_identity": "Muson Stick Contour ve Very Vanta Mascara",
                    "needs_research": True,
                    "research_query": "Muson Stick Contour Very Vanta Mascara",
                }

            class ResearchSynthesisProductProvider(FakeProductProvider):
                def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
                    self.requests.append(request)
                    proposed_account = "770.01" if request.context.semantic_stage == "research_synthesis" else "153.01"
                    line_decisions = [
                            {
                                "canonical_line_id": str(line.get("canonical_line_id") or ""),
                                "category": "kisisel_bakim_kozmetik",
                                "confidence": 93,
                                "product_identity": str(line.get("description") or ""),
                                "suggested_account_code": proposed_account,
                                "reason": "Canonical kozmetik satiri ve kaynakli urun kaniti birlikte degerlendirildi.",
                                "evidence": ["canonical_line", "manufacturer_claim"],
                                "needs_research": request.context.semantic_stage != "research_synthesis",
                                "research_query": "" if request.context.semantic_stage == "research_synthesis" else "Muson Stick Contour Very Vanta Mascara",
                                "risk_flags": [],
                            }
                            for line in request.context.canonical_lines
                        ]
                    if request.context.semantic_stage == "research_synthesis":
                        return {
                            **initial_response,
                            "suggested_account_code": "770.01",
                            "needs_research": False,
                            "research_query": "",
                            "line_decisions": line_decisions,
                        }
                    return {**initial_response, "line_decisions": line_decisions}

            product_provider = ResearchSynthesisProductProvider(initial_response)
            classifier = StaticFirstClassifier(
                provider=product_provider,
                policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
            )
            research_provider = FakeResearchProvider(
                {
                    "display_name": "Muson cosmetics",
                    "summary_tr": "Perakendeci özeti hızlı kargo ifadesi içeriyor; üretici kaynaklar ürünleri kozmetik olarak tanımlıyor.",
                    "common_product_categories": ["kargo"],
                    "account_treatment": "expense",
                    "research_confidence": 90,
                    "accounting_impact_confidence": 90,
                    "evidence": [
                        {
                            "url": "https://retailer.example/muson-stick-contour",
                            "title": "Perakendeci ürün sayfası",
                            "source_type": "retailer",
                            "summary_tr": "Muson Stick Contour için hızlı kargo ve teslimat bilgisi.",
                            "raw_summary": "Muson Stick Contour için hızlı kargo ve teslimat bilgisi.",
                        },
                        {
                            "url": "https://musoncosmetics.example/products/stick-contour",
                            "title": "Muson üretici ürün sayfası",
                            "source_type": "manufacturer",
                            "summary_tr": "Stick contour ve mascara kişisel bakım/kozmetik ürünleridir.",
                            "raw_summary": "Stick contour ve mascara kişisel bakım/kozmetik ürünleridir.",
                        },
                    ],
                }
            )

            process_queued_documents(
                store,
                product_classifier=classifier,
                research_runtime={"provider": research_provider, "policy": ResearchPolicy(enabled=True, confidence_threshold=70)},
            )
            result = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(result["product_category"], "kisisel_bakim_kozmetik")
        self.assertNotEqual(result["product_category"], "kargo")
        self.assertIn("research_evidence", result)
        self.assertIn("hızlı kargo", result["research_evidence"][0]["raw_summary"])
        self.assertTrue(result["research_evidence"][0]["canonical_line_ids"])
        self.assertIn("source_url", result["research_evidence"][0])
        self.assertNotIn("authoritative_product_category", result)
        self.assertNotIn("selected_account_code", result)
        self.assertEqual(result.get("accepted_semantic_stage"), "research_synthesis", result.get("semantic_attempts"))
        self.assertEqual(result.get("selected_expense_account"), "770.01", result)
        accepted_attempt = next(
            item
            for item in result.get("semantic_attempts") or []
            if item.get("attempt_id") == result.get("accepted_semantic_attempt_id")
        )
        self.assertEqual(accepted_attempt["validated_response"]["suggested_account_code"], "770.01")
        synthesis_request = next(
            request
            for request in product_provider.requests
            if request.context.semantic_stage == "research_synthesis"
        )
        initial_request = next(
            request
            for request in product_provider.requests
            if request.context.semantic_stage == "initial_account_decision"
        )
        self.assertEqual(synthesis_request.context.semantic_stage, "research_synthesis")
        self.assertEqual(
            [item["canonical_line_id"] for item in synthesis_request.context.canonical_lines],
            [item["canonical_line_id"] for item in initial_request.context.canonical_lines],
        )
        self.assertEqual(synthesis_request.context.account_candidates, initial_request.context.account_candidates)
        self.assertTrue(synthesis_request.context.research_evidence)

    def test_nace_profile_cache_does_not_block_uncertain_invoice_line_research(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "nace-cached-uncertain.xml"
            write_invoice_xml(xml_path, line_name="Mystery Sonic Pro bakim seti", supplier_name="Acme A.S.")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            workspace = store.get_workspace("client-1")
            profile = dict(workspace["client"]["profile"])
            store.upsert_client(
                client_id="client-1",
                profile={**profile, "nace_code": "477401"},
                onboarding=workspace["client"]["onboarding"],
            )
            store.save_nace_research_profile(
                nace_code="477401",
                profile={
                    "activity_title": "Tibbi perakende",
                    "scope_summary": "Cache profil",
                    "activity_tags": ["hearing_aid", "medical_retail"],
                    "source_urls": ["https://example.test/nace"],
                    "research_confidence": 85,
                    "accounting_impact_confidence": 90,
                },
            )
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
        self.assertEqual(result["research_profile"]["display_name"], "Mystery Sonic")

    def test_worker_uses_ai_research_query_before_raw_invoice_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "ai-query.xml"
            write_invoice_xml(xml_path, line_name="ZX Sonic Pro 9 bundle extra text", supplier_name="Medikal Tedarik")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            product_provider = FakeProductProvider(
                {
                    "category": "bilinmeyen",
                    "confidence": 45,
                    "reason": "Model net degil, arastirma gerekir.",
                    "evidence": ["ai:uncertain"],
                    "suggested_account_code": "",
                    "suggested_counterparty_code": "",
                    "risk_flags": ["accountant_review_required"],
                    "account_reason": "",
                    "product_identity": "ZX Sonic Pro 9",
                    "needs_research": True,
                    "research_query": "ZX Sonic Pro 9",
                }
            )
            classifier = StaticFirstClassifier(
                provider=product_provider,
                policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
            )
            research_provider = FakeResearchProvider(
                {
                    "display_name": "ZX Sonic Pro 9",
                    "summary_tr": "Uretici sayfasina gore isitme cihazi modelidir.",
                    "common_product_categories": ["isitme_cihazi"],
                    "account_treatment": "stock_or_cogs",
                    "research_confidence": 85,
                    "accounting_impact_confidence": 90,
                    "evidence": [{"url": "https://manufacturer.example/zx-sonic-pro-9", "summary_tr": "Uretici sayfasi."}],
                }
            )

            process_queued_documents(
                store,
                product_classifier=classifier,
                research_runtime={"provider": research_provider, "policy": ResearchPolicy(enabled=True, confidence_threshold=70)},
            )
            result = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(len(product_provider.requests), 2)
        self.assertEqual(len(research_provider.queries), 1)
        self.assertEqual(research_provider.queries[0].search_text, "ZX Sonic Pro 9")
        self.assertEqual(result["research_profile"]["display_name"], "ZX Sonic Pro 9")
        self.assertEqual(
            [item["stage"] for item in result["semantic_attempts"]],
            ["initial_account_decision", "research_synthesis"],
        )
        self.assertFalse(result["semantic_attempts"][0]["accepted"])
        self.assertFalse(result["semantic_attempts"][-1]["accepted"])
        self.assertEqual(result["accepted_semantic_attempt_id"], "")
        research_response = result["semantic_attempts"][-1]["validated_response"]
        self.assertEqual(
            research_response["research_evidence"][0]["source_url"],
            "https://manufacturer.example/zx-sonic-pro-9",
        )
        self.assertIn("Uretici sayfasi", research_response["research_evidence"][0]["evidence_summary"])

    def test_worker_honors_ai_research_request_even_with_known_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "ai-known-needs-research.xml"
            write_invoice_xml(xml_path, line_name="Helix Force 200 RI isitme cihazi", supplier_name="Medikal Tedarik")
            store = JsonWorkflowStore(Path(temp_dir) / "phase0_store.json")
            queue_invoice(store, xml_path)
            store.replace_chart_accounts(
                client_id="client-1",
                accounts=[
                    {
                        "raw_account_code": "153.01",
                        "normalized_account_code": "153.01",
                        "account_name": "Ticari mallar",
                        "is_detail_account": True,
                        "is_active": True,
                    }
                ],
            )
            product_provider = FakeProductProvider(
                {
                    "category": "isitme_cihazi",
                    "confidence": 88,
                    "reason": "Urun isitme cihazi gibi; model yeni oldugu icin kaynak kontrolu gerekir.",
                    "evidence": ["ai:known_category"],
                    "suggested_account_code": "153.01",
                    "suggested_counterparty_code": "",
                    "risk_flags": [],
                    "account_reason": "Stok hesabi uygun gorunuyor.",
                    "product_identity": "Helix Force 200 RI",
                    "needs_research": True,
                    "research_query": "Helix Force 200 RI",
                }
            )
            classifier = StaticFirstClassifier(
                provider=product_provider,
                policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
            )
            research_provider = FakeResearchProvider(
                {
                    "display_name": "Helix Force 200 RI",
                    "summary_tr": "Uretici sayfasina gore isitme cihazi modelidir.",
                    "common_product_categories": ["isitme_cihazi"],
                    "account_treatment": "stock_or_cogs",
                    "research_confidence": 85,
                    "accounting_impact_confidence": 90,
                    "evidence": [{"url": "https://manufacturer.example/helix-force-200-ri", "summary_tr": "Uretici sayfasi."}],
                }
            )

            process_queued_documents(
                store,
                product_classifier=classifier,
                research_runtime={"provider": research_provider, "policy": ResearchPolicy(enabled=True, confidence_threshold=70)},
            )
            result = store.get_workspace("client-1")["documents"][0]["result"]

        self.assertEqual(len(product_provider.requests), 2)
        self.assertEqual(len(research_provider.queries), 1)
        self.assertEqual(research_provider.queries[0].search_text, "Helix Force 200 RI")
        self.assertTrue(result["ai_research_requested"])
        self.assertEqual(result["research_profile"]["display_name"], "Helix Force 200 RI")


if __name__ == "__main__":
    unittest.main()
