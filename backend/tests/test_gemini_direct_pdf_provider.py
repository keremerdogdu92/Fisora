from __future__ import annotations

import base64
from datetime import UTC
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.ai_classification import (  # noqa: E402
    AccountingSelectionRequest,
    AiClassificationContext,
    AiClassificationRequest,
)
from app.domain.canonical_invoices import CanonicalExtractionRequest  # noqa: E402
from app.domain.openai_provider import GeminiAccountingProvider  # noqa: E402


def _successful_body(
    parsed: dict[str, object] | None = None,
    *,
    model_version: str = "gemini-2.5-flash-lite-001",
) -> bytes:
    structured = parsed or {
        "supplier_party": {"title": "TEDARIKCI", "tax_id": "9999999999"},
        "customer_party": {"title": "MUKELLEF", "tax_id": "1234567890"},
        "line_items": [],
        "vat_summary": [],
        "totals": {},
    }
    return json.dumps(
        {
            "modelVersion": model_version,
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    structured,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                            }
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 24,
                "candidatesTokenCount": 12,
                "totalTokenCount": 36,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class FakeResponse:
    headers: dict[str, str] = {}

    def __init__(self, body: bytes, *, status_code: int = 200, error: Exception | None = None) -> None:
        self.content = body
        self.status_code = status_code
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict[str, object]:
        return json.loads(self.content)


class RecordingClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def _posted_user_payload(client: RecordingClient) -> dict[str, object]:
    request_payload = json.loads(client.calls[0]["content"])
    text = request_payload["contents"][0]["parts"][-1]["text"]
    marker = "Girdi: "
    return json.loads(text[text.index(marker) + len(marker) :])


class GeminiDirectPdfProviderTests(unittest.TestCase):
    def test_provider_rejects_invalid_credential_slot_before_http(self) -> None:
        for invalid_slot in (
            "AIzaSyRAW-API-KEY",
            "a" * 64,
            "GEMINI_API_KEY_SLOT_0",
            "GEMINI_API_KEY_SLOT_9",
            " GEMINI_API_KEY_SLOT_1",
            "gemini_api_key_slot_1",
        ):
            with self.subTest(invalid_slot=invalid_slot):
                client = RecordingClient(FakeResponse(_successful_body()))
                with self.assertRaisesRegex(ValueError, "credential slot"):
                    GeminiAccountingProvider(
                        api_key="AIza-test-key",
                        credential_slot=invalid_slot,
                        http_client=client,
                    )
                self.assertEqual(client.calls, [])

    def test_success_and_failure_attempts_keep_opaque_slot_without_secret(self) -> None:
        slot = "GEMINI_API_KEY_SLOT_7"
        request = AiClassificationRequest(
            raw_line="Iletisim hizmeti",
            supplier_hint="Operator",
            allowed_categories=("genel_gider",),
            max_input_chars=200,
        )

        success = GeminiAccountingProvider(
            api_key="AIza-success-secret",
            credential_slot=slot,
            http_client=RecordingClient(FakeResponse(_successful_body())),
        ).classify_product(request)
        self.assertEqual(success.attempt.credential_slot, slot)
        self.assertNotIn("AIza-success-secret", repr(success.attempt))

        class SecretRaisingClient:
            def post(self, url: str, **kwargs: object) -> FakeResponse:
                raise RuntimeError("transport failure with AiZA-transport-secret")

        with self.assertRaises(Exception) as transport_context:
            GeminiAccountingProvider(
                api_key="AiZA-transport-secret",
                credential_slot=slot,
                http_client=SecretRaisingClient(),
            ).classify_product(request)
        transport_attempt = transport_context.exception.attempt
        self.assertEqual(transport_attempt.credential_slot, slot)
        self.assertNotIn("AiZA-transport-secret", repr(transport_attempt))

        with self.assertRaises(Exception) as http_context:
            GeminiAccountingProvider(
                api_key="AiZA-http-secret",
                credential_slot=slot,
                http_client=RecordingClient(
                    FakeResponse(b'{"error":{"code":429}}', status_code=429, error=RuntimeError("429"))
                ),
            ).classify_product(request)
        self.assertEqual(http_context.exception.attempt.credential_slot, slot)
        self.assertNotIn("AiZA-http-secret", repr(http_context.exception.attempt))

        malformed = b'{"modelVersion":"gemini-broken","candidates":[{"content":{"parts":[{"text":"{bad"}]}}]}'
        with self.assertRaises(Exception) as parse_context:
            GeminiAccountingProvider(
                api_key="AiZA-parse-secret",
                credential_slot=slot,
                http_client=RecordingClient(FakeResponse(malformed)),
            ).classify_product(request)
        self.assertEqual(parse_context.exception.attempt.credential_slot, slot)
        self.assertNotIn("AiZA-parse-secret", repr(parse_context.exception.attempt))

    def test_actual_accounting_selection_preserves_candidate_roles_and_tax_metadata(self) -> None:
        output = {
            "action": "finalize",
            "candidate_set_sufficient": True,
            "proposal": {
                "counterparty_account": {"selected_candidate_id": "320.01", "reason": "VKN"},
                "line_accounts": [{"line_ref": "line-1", "selected_candidate_id": "770.01", "reason": "gider"}],
                "vat_accounts": [],
                "special_tax_accounts": [],
                "new_counterparty_proposal": None,
            },
            "reason": "tam",
        }
        client = RecordingClient(FakeResponse(_successful_body(output)))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)
        request = AccountingSelectionRequest(
            accounting_projection={
                "document_direction": "purchase",
                "supplier_party": {"title": "Operator", "tax_id": "1234567890"},
                "customer_party": {},
                "line_items": [{"canonical_line_id": "line-1", "description": "Internet", "taxable_amount": "100"}],
                "vat_summary": [],
                "tax_components": [],
                "totals": {"payable_total": "100"},
            },
            candidate_details=(
                {
                    "candidate_id": "320.01",
                    "code": "320.01",
                    "name": "Operator cari",
                    "roles": ["counterparty"],
                    "tax_id": "1234567890",
                    "tax_office": "Maslak",
                    "origin_round": 0,
                    "raw_provider_receipt": "LEAK-RAW-RECEIPT",
                    "source_pdf_base64": "LEAK-PDF",
                },
                {
                    "candidate_id": "770.01",
                    "code": "770.01",
                    "name": "Haberlesme gideri",
                    "roles": ["line_expense"],
                    "tax_id": "",
                    "tax_office": "",
                    "origin_round": 0,
                },
            ),
            round_index=0,
        )

        provider.classify_product(request)

        posted = _posted_user_payload(client)
        candidates = posted["account_candidates"]
        self.assertEqual(candidates[0]["roles"], ["counterparty"])
        self.assertEqual(candidates[0]["tax_id"], "1234567890")
        self.assertEqual(candidates[0]["tax_office"], "Maslak")
        rendered = client.calls[0]["content"].decode("utf-8")
        self.assertIn("her canonical satir", rendered)
        self.assertIn("KDV", rendered)
        self.assertIn("ozel vergi", rendered)
        self.assertIn("provisional", rendered)
        self.assertNotIn("LEAK-RAW-RECEIPT", rendered)
        self.assertNotIn("LEAK-PDF", rendered)

    def test_transport_error_redacts_api_key_and_sensitive_url_or_header_patterns(self) -> None:
        api_key = "AIza-review-secret-exact"

        class SecretRaisingClient:
            def post(self, url: str, **kwargs: object) -> FakeResponse:
                raise RuntimeError(
                    f"transport {api_key} {url}?key={api_key} "
                    f"Authorization: Bearer {api_key} x-goog-api-key={api_key}"
                )

        provider = GeminiAccountingProvider(api_key=api_key, http_client=SecretRaisingClient())

        try:
            provider.classify_product(
                AiClassificationRequest(
                    raw_line="Iletisim hizmeti",
                    supplier_hint="Operator",
                    allowed_categories=("genel_gider",),
                    max_input_chars=200,
                )
            )
        except Exception as exc:
            rendered_metadata = json.dumps(exc.attempt.error_metadata, ensure_ascii=False)
            self.assertIsNone(exc.__context__)
            self.assertIsNone(exc.__cause__)
            self.assertNotIn(api_key, str(exc))
            self.assertNotIn(api_key, rendered_metadata)
            self.assertNotIn(f"?key={api_key}", str(exc))
            self.assertNotIn(f"Bearer {api_key}", rendered_metadata)
            self.assertIn("[redacted", str(exc))
        else:
            self.fail("transport error must be raised with a redacted attempt")

    def test_extraction_rejects_text_only_input_before_http(self) -> None:
        client = RecordingClient(FakeResponse(_successful_body()))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)

        with self.assertRaisesRegex(ValueError, "requires native PDF bytes"):
            provider.extract_invoice_canonical(
                CanonicalExtractionRequest(document_text="text-only invoice")
            )

        self.assertEqual(client.calls, [])

    def test_native_pdf_success_captures_exact_attempt_and_stays_dict_compatible(self) -> None:
        response_body = _successful_body()
        client = RecordingClient(FakeResponse(response_body))
        pdf_bytes = b"%PDF-1.7\nexact native invoice\n%%EOF"
        provider = GeminiAccountingProvider(
            api_key="AIza-test-key-never-store",
            http_client=client,
        )

        result = provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="must not be posted with native PDF",
                document_bytes=pdf_bytes,
                document_mime_type="application/pdf",
                deterministic_payload={"invoice_no": "FTR-42"},
                client_identity={"tax_id": "1234567890"},
            )
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["supplier_party"]["tax_id"], "9999999999")
        self.assertTrue(hasattr(result, "attempt"), "structured result must expose its provider attempt")
        call = client.calls[0]
        self.assertIn("content", call, "Gemini must post the one serialized byte body")
        self.assertNotIn("json", call)
        self.assertEqual(result.attempt.request_body, call["content"])
        self.assertEqual(result.attempt.response_body, response_body)
        posted = json.loads(result.attempt.request_body)
        inline_data = posted["contents"][0]["parts"][0]["inline_data"]
        self.assertEqual(inline_data["mime_type"], "application/pdf")
        self.assertEqual(base64.b64decode(inline_data["data"]), pdf_bytes)
        self.assertNotIn("must not be posted", result.attempt.request_body.decode("utf-8"))
        self.assertEqual(result.attempt.provider, "gemini")
        self.assertEqual(result.attempt.model_alias, "gemini-2.5-flash-lite")
        self.assertEqual(result.attempt.resolved_model, "gemini-2.5-flash-lite-001")
        self.assertEqual(result.attempt.http_status, 200)
        self.assertEqual(result.attempt.status, "successful")
        self.assertEqual(result.attempt.token_usage["total_tokens"], 36)
        self.assertEqual(result.attempt.started_at.tzinfo, UTC)
        self.assertEqual(result.attempt.finished_at.tzinfo, UTC)
        self.assertGreaterEqual(result.attempt.elapsed_ms, 0)
        self.assertNotIn("AIza-test-key-never-store", repr(result.attempt))
        self.assertNotIn("headers", result.attempt.__dataclass_fields__)

    def test_malformed_structured_json_raises_with_failed_exact_attempt(self) -> None:
        response_body = json.dumps(
            {
                "modelVersion": "gemini-broken-001",
                "candidates": [{"content": {"parts": [{"text": "{not-json"}]}}],
                "usageMetadata": {"totalTokenCount": 9},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        provider = GeminiAccountingProvider(
            api_key="AIza-test-key-never-store",
            http_client=RecordingClient(FakeResponse(response_body)),
        )

        try:
            provider.extract_invoice_canonical(
                CanonicalExtractionRequest(
                    document_text="",
                    document_bytes=b"%PDF-malformed",
                    document_mime_type="application/pdf",
                )
            )
        except Exception as exc:  # exact error class is part of the new contract
            self.assertIsNone(exc.__context__)
            self.assertTrue(hasattr(exc, "attempt"), "parse error must retain its failed attempt")
            self.assertEqual(exc.attempt.response_body, response_body)
            self.assertEqual(exc.attempt.http_status, 200)
            self.assertEqual(exc.attempt.status, "failed")
            self.assertEqual(exc.attempt.resolved_model, "gemini-broken-001")
            self.assertEqual(exc.attempt.error_metadata["phase"], "structured_parse")
            self.assertNotIn("parsed_data", exc.attempt.error_metadata)
        else:
            self.fail("malformed Gemini structured JSON must not fabricate canonical data")

    def test_http_error_raises_with_exact_failed_attempt(self) -> None:
        response_body = b'{"error":{"code":429,"message":"quota"}}'
        client = RecordingClient(
            FakeResponse(response_body, status_code=429, error=RuntimeError("429 quota"))
        )
        provider = GeminiAccountingProvider(
            api_key="AIza-test-key-never-store",
            http_client=client,
        )

        try:
            provider.classify_product(
                AiClassificationRequest(
                    raw_line="Mobil iletisim hizmeti",
                    supplier_hint="Operator",
                    allowed_categories=("genel_gider",),
                    max_input_chars=200,
                )
            )
        except Exception as exc:
            self.assertIsNone(exc.__context__)
            self.assertTrue(hasattr(exc, "attempt"), "HTTP error must retain its failed attempt")
            self.assertEqual(exc.attempt.request_body, client.calls[0]["content"])
            self.assertEqual(exc.attempt.response_body, response_body)
            self.assertEqual(exc.attempt.http_status, 429)
            self.assertEqual(exc.attempt.status, "failed")
            self.assertEqual(exc.attempt.error_metadata["phase"], "http")
        else:
            self.fail("Gemini HTTP error must be raised")

    def test_extraction_transport_removes_accounting_candidate_context(self) -> None:
        client = RecordingClient(FakeResponse(_successful_body()))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)

        provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="",
                document_bytes=b"%PDF-boundary",
                document_mime_type="application/pdf",
                deterministic_payload={
                    "invoice_no": "FTR-1",
                    "account_candidates": ["770.01"],
                    "counterparty_candidates": ["320.01"],
                    "candidate_strategy": {"stage": "line_batch"},
                },
            )
        )

        posted_body = client.calls[0].get("content")
        self.assertIsInstance(posted_body, bytes, "extraction must post exact serialized bytes")
        posted_text = posted_body.decode("utf-8")
        self.assertNotIn("account_candidates", posted_text)
        self.assertNotIn("counterparty_candidates", posted_text)
        self.assertNotIn("candidate_strategy", posted_text)
        self.assertIn("FTR-1", posted_text)

    def test_extraction_allow_list_blocks_alternate_and_nested_accounting_aliases(self) -> None:
        client = RecordingClient(FakeResponse(_successful_body()))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)

        provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="",
                document_bytes=b"%PDF-allow-list",
                document_mime_type="application/pdf",
                deterministic_payload={
                    "invoice_no": "SAFE-FTR-9",
                    "line_items": [
                        {
                            "canonical_line_id": "line-1",
                            "description": "SAFE-LINE-DESCRIPTION",
                            "evidence": [
                                "SAFE-EVIDENCE",
                                {"raw_provider_receipt": "LEAK-DEEP-EVIDENCE"},
                            ],
                            "ledger_options": ["LEAK-NESTED-LEDGER"],
                            "source_pdf_payload": "LEAK-NESTED-PDF",
                        }
                    ],
                    "totals": {
                        "payable_total": "118.00",
                        "chartSlice": ["LEAK-TOTALS-CHART"],
                    },
                    "ledger_options": ["LEAK-TOP-LEDGER"],
                    "chartSlice": ["LEAK-TOP-CHART"],
                    "candidateAliases": ["LEAK-CANDIDATE-ALIAS"],
                    "metadata": {"source_pdf_base64": "LEAK-METADATA-PDF"},
                },
                client_identity={
                    "title": "SAFE-CLIENT",
                    "tax_id": "1234567890",
                    "chart_snapshot": "LEAK-CLIENT-CHART",
                },
            )
        )

        posted_text = client.calls[0]["content"].decode("utf-8")
        for marker in (
            "LEAK-NESTED-LEDGER",
            "LEAK-NESTED-PDF",
            "LEAK-TOTALS-CHART",
            "LEAK-TOP-LEDGER",
            "LEAK-TOP-CHART",
            "LEAK-CANDIDATE-ALIAS",
            "LEAK-METADATA-PDF",
            "LEAK-CLIENT-CHART",
            "LEAK-DEEP-EVIDENCE",
        ):
            self.assertNotIn(marker, posted_text)
        self.assertIn("SAFE-FTR-9", posted_text)
        self.assertIn("SAFE-LINE-DESCRIPTION", posted_text)
        self.assertIn("SAFE-EVIDENCE", posted_text)
        self.assertIn("SAFE-CLIENT", posted_text)

    def test_accounting_transport_removes_pdf_and_raw_extraction_material(self) -> None:
        output = {
            "category": "genel_gider",
            "confidence": 85,
            "reason": "hizmet",
            "evidence": ["satir"],
            "suggested_account_code": "770.01",
            "suggested_counterparty_code": "",
            "risk_flags": [],
            "account_reason": "uygun aday",
            "product_identity": "iletisim",
            "needs_research": False,
            "research_query": "",
        }
        client = RecordingClient(FakeResponse(_successful_body(output)))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)
        request = AiClassificationRequest(
            raw_line="Mobil iletisim hizmeti",
            supplier_hint="Operator",
            allowed_categories=("genel_gider",),
            max_input_chars=200,
            context=AiClassificationContext(
                account_candidates=("770.01",),
                semantic_stage="research_synthesis",
                prior_semantic_attempt={
                    "selected_candidate": "770.01",
                    "raw_extraction_response": "RAW-EXTRACTION-MARKER",
                    "pdf_base64": "PDF-BASE64-MARKER",
                    "inline_data": {"data": "INLINE-PDF-MARKER"},
                },
            ),
        )

        result = provider.classify_product(request)

        posted_body = client.calls[0].get("content")
        self.assertIsInstance(posted_body, bytes, "accounting must post exact serialized bytes")
        posted_text = posted_body.decode("utf-8")
        self.assertEqual(result["suggested_account_code"], "770.01")
        self.assertIn("770.01", posted_text)
        self.assertNotIn("RAW-EXTRACTION-MARKER", posted_text)
        self.assertNotIn("PDF-BASE64-MARKER", posted_text)
        self.assertNotIn("INLINE-PDF-MARKER", posted_text)
        self.assertNotIn("raw_extraction_response", posted_text)
        self.assertNotIn("pdf_base64", posted_text)
        self.assertNotIn("inline_data", posted_text)

    def test_accounting_allow_list_blocks_alternate_nested_receipt_and_source_aliases(self) -> None:
        output = {
            "category": "genel_gider",
            "confidence": 85,
            "reason": "hizmet",
            "evidence": ["satir"],
            "suggested_account_code": "770.01",
            "suggested_counterparty_code": "",
            "risk_flags": [],
            "account_reason": "uygun aday",
            "product_identity": "iletisim",
            "needs_research": False,
            "research_query": "",
        }
        client = RecordingClient(FakeResponse(_successful_body(output)))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)

        provider.classify_product(
            AiClassificationRequest(
                raw_line="Mobil iletisim hizmeti",
                supplier_hint="Operator",
                allowed_categories=("genel_gider",),
                max_input_chars=200,
                context=AiClassificationContext(
                    account_candidates=("770.01",),
                    account_candidate_details=(
                        {
                            "code": "770.01",
                            "name": "SAFE-ACCOUNT-NAME",
                            "semantic_roles": [
                                "expense",
                                {"source_pdf": "LEAK-DEEP-CANDIDATE-ROLE"},
                            ],
                            "ledger_dump": "LEAK-CANDIDATE-LEDGER",
                        },
                    ),
                    semantic_stage="research_synthesis",
                    prior_semantic_attempt={
                        "attempt_id": "SAFE-ATTEMPT-ID",
                        "stage": "initial_account_decision",
                        "validated_response": {
                            "suggested_account_code": "770.01",
                            "reason": "SAFE-PRIOR-REASON",
                            "responseEnvelope": "LEAK-NESTED-ENVELOPE",
                            "sourceDocument": "LEAK-NESTED-SOURCE",
                        },
                        "providerReceipt": "LEAK-PROVIDER-RECEIPT",
                        "chart_snapshot": "LEAK-PRIOR-CHART",
                        "base64Document": "LEAK-PRIOR-PDF",
                    },
                    research_evidence=(
                        {
                            "source_url": "https://evidence.example/item",
                            "evidence_summary": "SAFE-RESEARCH-SUMMARY",
                            "source_pdf": "LEAK-RESEARCH-PDF",
                        },
                    ),
                ),
            )
        )

        posted_text = client.calls[0]["content"].decode("utf-8")
        for marker in (
            "LEAK-CANDIDATE-LEDGER",
            "LEAK-NESTED-ENVELOPE",
            "LEAK-NESTED-SOURCE",
            "LEAK-PROVIDER-RECEIPT",
            "LEAK-PRIOR-CHART",
            "LEAK-PRIOR-PDF",
            "LEAK-RESEARCH-PDF",
            "LEAK-DEEP-CANDIDATE-ROLE",
        ):
            self.assertNotIn(marker, posted_text)
        self.assertIn("SAFE-ACCOUNT-NAME", posted_text)
        self.assertIn("SAFE-ATTEMPT-ID", posted_text)
        self.assertIn("SAFE-PRIOR-REASON", posted_text)
        self.assertIn("SAFE-RESEARCH-SUMMARY", posted_text)

    def test_research_evidence_allow_list_preserves_full_safe_contract(self) -> None:
        output = {
            "category": "genel_gider",
            "confidence": 85,
            "reason": "hizmet",
            "evidence": ["satir"],
            "suggested_account_code": "770.01",
            "suggested_counterparty_code": "",
            "risk_flags": [],
            "account_reason": "uygun aday",
            "product_identity": "iletisim",
            "needs_research": False,
            "research_query": "",
        }
        client = RecordingClient(FakeResponse(_successful_body(output)))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)
        safe_evidence = {
            "url": "https://evidence.example/page",
            "title": "Official product page",
            "source_type": "manufacturer",
            "summary_tr": "Turkce ozet",
            "accepted": True,
            "question": "Bu hizmet nedir?",
            "canonical_line_ids": ["line-1"],
            "claims": ["SAFE-CLAIM", {"provider_receipt": "LEAK-DEEP-CLAIM"}],
            "conflicts": ["SAFE-CONFLICT"],
            "source_url": "https://evidence.example/source",
            "source_domain": "evidence.example",
            "source_kind": "official",
            "evidence_summary": "SAFE-EVIDENCE-SUMMARY",
            "confidence": 91,
            "quality": "high",
            "raw_summary": "SAFE-RAW-SUMMARY",
            "raw_pdf": "LEAK-RAW-PDF",
            "provider_receipt": "LEAK-PROVIDER-RECEIPT",
            "provider_response": "LEAK-PROVIDER-RESPONSE",
        }

        provider.classify_product(
            AiClassificationRequest(
                raw_line="Mobil iletisim hizmeti",
                supplier_hint="Operator",
                allowed_categories=("genel_gider",),
                max_input_chars=200,
                context=AiClassificationContext(
                    account_candidates=("770.01",),
                    semantic_stage="research_synthesis",
                    research_evidence=(safe_evidence,),
                ),
            )
        )

        posted = _posted_user_payload(client)
        item = posted["research_evidence"][0]
        for field in (
            "url",
            "title",
            "source_type",
            "summary_tr",
            "accepted",
            "question",
            "canonical_line_ids",
            "claims",
            "conflicts",
            "source_url",
            "source_domain",
            "source_kind",
            "evidence_summary",
            "confidence",
            "quality",
            "raw_summary",
        ):
            self.assertIn(field, item)
        self.assertEqual(item["claims"], ["SAFE-CLAIM"])
        self.assertEqual(item["canonical_line_ids"], ["line-1"])
        self.assertNotIn("raw_pdf", item)
        self.assertNotIn("provider_receipt", item)
        self.assertNotIn("provider_response", item)
        rendered = json.dumps(item, ensure_ascii=False)
        self.assertNotIn("LEAK-DEEP-CLAIM", rendered)
        self.assertIn("SAFE-RAW-SUMMARY", rendered)

    def test_invalid_token_usage_is_zeroed_without_losing_success_attempt(self) -> None:
        response_payload = json.loads(_successful_body())
        response_payload["usageMetadata"] = {
            "promptTokenCount": "not-a-number",
            "candidatesTokenCount": None,
            "totalTokenCount": {"unexpected": "object"},
        }
        response_body = json.dumps(response_payload, separators=(",", ":")).encode("utf-8")
        provider = GeminiAccountingProvider(
            api_key="test-key",
            http_client=RecordingClient(FakeResponse(response_body)),
        )

        try:
            result = provider.classify_product(
                AiClassificationRequest(
                    raw_line="Iletisim hizmeti",
                    supplier_hint="Operator",
                    allowed_categories=("genel_gider",),
                    max_input_chars=200,
                )
            )
        except Exception as exc:
            self.fail(f"invalid usage metadata must not escape without a result attempt: {exc!r}")

        self.assertEqual(
            result.attempt.token_usage,
            {
                "prompt_tokens": 0,
                "candidate_tokens": 0,
                "cached_tokens": 0,
                "thought_tokens": 0,
                "total_tokens": 0,
            },
        )
        self.assertIn("usage_diagnostics", result.attempt.error_metadata)

    def test_response_body_capture_failure_raises_with_failed_attempt(self) -> None:
        class ExplodingResponse:
            status_code = 200

            @property
            def content(self) -> bytes:
                raise RuntimeError("response content unavailable")

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                raise RuntimeError("response json unavailable")

        provider = GeminiAccountingProvider(
            api_key="test-key",
            http_client=RecordingClient(ExplodingResponse()),
        )

        try:
            provider.classify_product(
                AiClassificationRequest(
                    raw_line="Iletisim hizmeti",
                    supplier_hint="Operator",
                    allowed_categories=("genel_gider",),
                    max_input_chars=200,
                )
            )
        except Exception as exc:
            self.assertIsNone(exc.__context__)
            self.assertTrue(hasattr(exc, "attempt"))
            self.assertEqual(exc.attempt.status, "failed")
            self.assertEqual(exc.attempt.error_metadata["phase"], "response_capture")
        else:
            self.fail("post-response conversion failure must retain its failed attempt")

    def test_invalid_outer_response_json_raises_without_secret_context(self) -> None:
        provider = GeminiAccountingProvider(
            api_key="test-key",
            http_client=RecordingClient(FakeResponse(b"not-json")),
        )

        try:
            provider.classify_product(
                AiClassificationRequest(
                    raw_line="Iletisim hizmeti",
                    supplier_hint="Operator",
                    allowed_categories=("genel_gider",),
                    max_input_chars=200,
                )
            )
        except Exception as exc:
            self.assertIsNone(exc.__context__)
            self.assertEqual(exc.attempt.error_metadata["phase"], "response_json")
        else:
            self.fail("invalid response JSON must retain a sanitized failed attempt")


if __name__ == "__main__":
    unittest.main()
