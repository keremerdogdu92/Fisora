from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_candidate_builder import AccountingCandidate  # noqa: E402
from app.domain.accounting_proposal import (  # noqa: E402
    AccountingProposalRequestContextV2,
    AccountingProposalRequestV2,
)
from app.domain.ai_classification import AccountingSelectionRequest  # noqa: E402
from app.domain.openai_provider import (  # noqa: E402
    GeminiAccountingProvider,
    classification_instructions_for,
)


V1_ACCOUNTING_SELECTION_INSTRUCTION = (
    "Belge olgularini degistirmeden tam muhasebe teklifi don: karsi taraf hesabi, her canonical satir, "
    "her KDV grubu ve her ozel vergi bileseni icin secim ve gerekce ver. Yalniz gonderilen gercek tenant "
    "adaylarini kullan; hesap kodu uydurma. Aday listesinin yeterli olup olmadigina karar ver. Yetersizse "
    "request_more_candidates iste ve o ana kadarki tam provisional teklifi koru; daha sonraki turda onceki "
    "turlarda gonderilen adaya geri donebilirsin. Yeni cari onerisi, satir/KDV/ozel vergi secimleriyle birlikte "
    "bulunabilir ve otomatik cari olusturma talimati degildir."
)


class FakeResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, payload: dict[str, object]) -> None:
        self.content = json.dumps(
            {
                "modelVersion": "gemini-v2-test-001",
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        payload,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    )
                                }
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "cachedContentTokenCount": 4,
                    "thoughtsTokenCount": 3,
                    "totalTokenCount": 15,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return json.loads(self.content)


class RecordingClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def _candidate(candidate_id: str, role: str) -> AccountingCandidate:
    return AccountingCandidate(
        candidate_id=candidate_id,
        code=candidate_id,
        name=f"Real tenant account {candidate_id}",
        roles=(role,),
        normalized_tax_id="1234567890" if role == "counterparty" else "",
        tax_office="Maslak" if role == "counterparty" else "",
        active=True,
        origin_round=0,
    )


def _v2_request() -> AccountingProposalRequestV2:
    return AccountingProposalRequestV2(
        projection={
            "document_direction": "purchase",
            "header": {
                "invoice_no": "SAFE-INVOICE",
                "currency_code": "TRY",
                "evidence": ["HEADER-EVIDENCE-MARKER"],
                "source_position": "HEADER-SOURCE-POSITION-MARKER",
            },
            "supplier_party": {
                "title": "Safe Supplier",
                "tax_id": "1234567890",
                "evidence": ["SUPPLIER-EVIDENCE-MARKER"],
                "source_position": "SUPPLIER-SOURCE-POSITION-MARKER",
            },
            "customer_party": {
                "title": "Safe Client",
                "tax_id": "1111111111",
                "evidence": ["CUSTOMER-EVIDENCE-MARKER"],
                "source_position": "CUSTOMER-SOURCE-POSITION-MARKER",
            },
            "line_items": [
                {
                    "decision_ref": "line:l1",
                    "identity_ref": "line:l1",
                    "description": "Safe service",
                    "taxable_amount": "100.00",
                    "evidence": ["LINE-EVIDENCE-MARKER"],
                    "source_position": "LINE-SOURCE-POSITION-MARKER",
                    "raw_provider_receipt": "RAW-PROVIDER-MARKER",
                    "source_pdf_base64": "PDF-MARKER",
                }
            ],
            "vat_summary": [
                {
                    "decision_ref": "vat:v20",
                    "identity_ref": "vat:v20",
                    "rate": "20",
                    "tax_amount": "20.00",
                    "evidence": ["VAT-EVIDENCE-MARKER"],
                    "source_position": "VAT-SOURCE-POSITION-MARKER",
                }
            ],
            "tax_components": [
                {
                    "decision_ref": "tax:t1",
                    "identity_ref": "tax:t1",
                    "component_type": "withholding",
                    "canonical_tax_kind": "withholding",
                    "economic_effect": "reduce_payable",
                    "tax_amount": "10.00",
                    "evidence": ["TAX-EVIDENCE-MARKER"],
                    "source_position": "TAX-SOURCE-POSITION-MARKER",
                    "provider_response": "PROVIDER-RESPONSE-MARKER",
                }
            ],
            "monetary_components": [
                {
                    "decision_ref": "monetary:m1",
                    "identity_ref": "monetary:m1",
                    "source_label": "Discount",
                    "source_amount": "5.00",
                    "signed_effect": "decrease_payable",
                    "evidence": ["MONETARY-EVIDENCE-MARKER"],
                    "source_position": "MONETARY-SOURCE-POSITION-MARKER",
                    "secret_value": "SECRET-MARKER",
                }
            ],
            "totals": {
                "payable_total": "105.00",
                "evidence": ["TOTAL-EVIDENCE-MARKER"],
                "source_position": "TOTAL-SOURCE-POSITION-MARKER",
            },
            "warnings": [],
            "projection_warnings": [],
            "source_field_links": [{"evidence": ["SOURCE-LINK-MARKER"]}],
            "client_context": {
                "activity_description": "Safe activity",
                "secret": "CLIENT-SECRET-MARKER",
            },
        },
        sent_candidates=(
            _candidate("320", "counterparty"),
            _candidate("770", "line_expense"),
            _candidate("191", "vat"),
            _candidate("360", "special_tax"),
            _candidate("649", "monetary"),
        ),
        required_decision_refs=(
            "counterparty",
            "line:l1",
            "vat:v20",
            "tax:t1",
            "monetary:m1",
        ),
    )


def _successful_proposal() -> dict[str, object]:
    return {
        "counterparty": {
            "action": "select_existing",
            "selected_candidate_id": "320",
            "reason": "exact tax id",
            "proposal": None,
        },
        "decisions": [
            {
                "decision_ref": decision_ref,
                "action": "select_existing",
                "selected_candidate_id": candidate_id,
                "selected_treatment": (
                    "expense_or_cost"
                    if decision_ref.startswith("tax:")
                    else "increase_payable"
                    if decision_ref.startswith("monetary:")
                    else ""
                ),
                "reason": "sent real tenant candidate",
            }
            for decision_ref, candidate_id in (
                ("line:l1", "770"),
                ("vat:v20", "191"),
                ("tax:t1", "360"),
                ("monetary:m1", "649"),
            )
        ],
        "candidate_sufficiency": {
            "sufficient": True,
            "request_more_candidates": False,
            "search_terms": [],
            "reason": "complete",
            "provisional": False,
        },
    }


def _posted_v2_user_payload(posted: dict[str, object]) -> dict[str, object]:
    parts = posted["contents"][0]["parts"]
    projection = json.loads(parts[0]["text"].split("\n", 1)[1])
    catalog = json.loads(parts[1]["text"].split("\n", 1)[1])
    return {**projection, **catalog}


class GeminiV2ProviderPromptTests(unittest.TestCase):
    def test_v2_schema_keeps_line_and_vat_treatment_nonoperative_and_requires_posting_treatment(self) -> None:
        schema = _v2_request().to_schema_payload()["output_schema"]
        decision_schema = schema["properties"]["decisions"]["items"]
        variants = decision_schema["anyOf"]

        def select_treatments(decision_ref: str) -> list[str]:
            for variant in variants:
                properties = variant["properties"]
                if (
                    properties["decision_ref"]["enum"] == [decision_ref]
                    and properties["action"]["enum"] == ["select_existing"]
                ):
                    return properties["selected_treatment"]["enum"]
            self.fail(f"select_existing schema variant missing for {decision_ref}")

        self.assertEqual(select_treatments("line:l1"), [""])
        self.assertEqual(select_treatments("vat:v20"), [""])
        self.assertEqual(
            select_treatments("tax:t1"),
            ["deductible_tax", "expense_or_cost", "payable_withholding"],
        )
        self.assertEqual(
            select_treatments("monetary:m1"),
            ["increase_payable", "reduce_payable"],
        )

    def test_targeted_treatment_clarification_instruction_is_bounded_and_ref_scoped(self) -> None:
        request = _v2_request()
        request = AccountingProposalRequestV2(
            projection=request.projection,
            sent_candidates=request.sent_candidates,
            required_decision_refs=("counterparty", "tax:t1"),
            context=AccountingProposalRequestContextV2(
                semantic_stage="treatment_clarification",
                candidate_strategy=request.context.candidate_strategy,
                clarification_decision={
                    "decision_ref": "tax:t1",
                    "action": "select_existing",
                    "selected_candidate_id": "360",
                    "selected_treatment": "",
                    "reason": "valid account, incomplete treatment",
                },
            ),
        )

        instruction = classification_instructions_for(request).lower()
        clarification = request.to_schema_payload()["clarification_decision"]

        for expected in (
            "one targeted clarification",
            "corrected full decision",
            "selected_treatment",
            "request_more_candidates",
            "sent real tenant candidates",
            "do not invent",
        ):
            self.assertIn(expected, instruction)
        self.assertEqual(clarification["decision_ref"], "tax:t1")
        self.assertEqual(clarification["selected_candidate_id"], "360")
        self.assertEqual(clarification["selected_treatment"], "")

    def test_v2_request_places_stable_projection_and_catalog_before_round_contract(self) -> None:
        client = RecordingClient(FakeResponse(_successful_proposal()))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)

        result = provider.classify_product(_v2_request())

        posted = json.loads(client.calls[0]["content"])
        text_parts = [
            part["text"]
            for part in posted["contents"][0]["parts"]
            if "text" in part
        ]
        self.assertEqual(len(text_parts), 3)
        self.assertTrue(text_parts[0].startswith("ACCOUNTING_V2_STABLE_PROJECTION\n"))
        self.assertTrue(text_parts[1].startswith("ACCOUNTING_V2_STABLE_CANDIDATE_CATALOG\n"))
        self.assertTrue(text_parts[2].startswith("ACCOUNTING_V2_ROUND_DECISION_CONTRACT\n"))
        projection = json.loads(text_parts[0].split("\n", 1)[1])
        catalog = json.loads(text_parts[1].split("\n", 1)[1])
        contract = json.loads(text_parts[2].split("\n", 1)[1])
        self.assertIn("raw_line", projection)
        self.assertNotIn("account_candidates", projection)
        self.assertEqual(
            [item["candidate_id"] for item in catalog["account_candidates"]],
            ["320", "770", "191", "360", "649"],
        )
        self.assertEqual(
            contract["required_decision_refs"],
            ["counterparty", "line:l1", "vat:v20", "tax:t1", "monetary:m1"],
        )
        self.assertEqual(
            result.attempt.token_usage,
            {
                "prompt_tokens": 10,
                "candidate_tokens": 5,
                "cached_tokens": 4,
                "thought_tokens": 3,
                "total_tokens": 15,
            },
        )

    def test_gemini_35_flash_lite_omits_deprecated_sampling_parameters(self) -> None:
        client = RecordingClient(FakeResponse(_successful_proposal()))
        provider = GeminiAccountingProvider(
            api_key="test-key",
            model="gemini-3.5-flash-lite",
            http_client=client,
        )

        provider.classify_product(_v2_request())

        config = json.loads(client.calls[0]["content"])["generationConfig"]
        self.assertNotIn("temperature", config)
        self.assertNotIn("topP", config)
        self.assertEqual(config["maxOutputTokens"], provider.max_output_tokens)

    def test_real_gemini_request_uses_v2_prompt_safe_facts_candidates_and_schema(self) -> None:
        client = RecordingClient(FakeResponse(_successful_proposal()))
        provider = GeminiAccountingProvider(
            api_key="API-SECRET-MARKER",
            http_client=client,
        )

        result = provider.classify_product(_v2_request())

        self.assertEqual(result["counterparty"]["selected_candidate_id"], "320")
        self.assertEqual(len(client.calls), 1)
        request_body = client.calls[0].get("content")
        self.assertIsInstance(request_body, bytes)
        self.assertEqual(result.attempt.request_body, request_body)
        self.assertEqual(result.attempt.status, "successful")
        posted = json.loads(request_body)
        instruction = posted["systemInstruction"]["parts"][0]["text"]
        for required_text in (
            "accounting_selection_v2",
            "counterparty",
            "line:<id>",
            "vat:<id>",
            "tax:<id>",
            "monetary:<id>",
            "request_more_candidates",
            "full provisional proposal",
            "earlier sent candidate",
            "maximum rounds are controlled externally",
            "broader real accounts",
            "do not invent",
            "do not change amounts",
            "do not auto-create a new counterparty",
            "no_separate_posting",
            "represented_in_line",
            "deductible_tax",
            "increase_payable",
            "reduce_payable",
            "excluded",
        ):
            self.assertIn(required_text, instruction.lower())

        rendered_body = request_body.decode("utf-8")
        for forbidden_marker in (
            "RAW-PROVIDER-MARKER",
            "PDF-MARKER",
            "PROVIDER-RESPONSE-MARKER",
            "SECRET-MARKER",
            "SOURCE-LINK-MARKER",
            "CLIENT-SECRET-MARKER",
            "API-SECRET-MARKER",
        ):
            self.assertNotIn(forbidden_marker, rendered_body)

        user_payload = _posted_v2_user_payload(posted)
        self.assertEqual(user_payload["candidate_strategy"]["stage"], "accounting_selection_v2")
        self.assertEqual(
            [item["candidate_id"] for item in user_payload["account_candidates"]],
            ["320", "770", "191", "360", "649"],
        )
        self.assertEqual(user_payload["account_candidates"][0]["tax_id"], "1234567890")
        schema = posted["generationConfig"]["responseJsonSchema"]
        decision_ref_schema = schema["properties"]["decisions"]["items"]["properties"]["decision_ref"]
        self.assertEqual(
            decision_ref_schema["enum"],
            ["line:l1", "vat:v20", "tax:t1", "monetary:m1"],
        )
        self.assertEqual(
            schema["properties"]["decisions"]["minItems"],
            4,
        )
        self.assertEqual(schema["properties"]["decisions"]["maxItems"], 4)

    def test_v2_transport_removes_nested_raw_pdf_source_and_secret_markers(self) -> None:
        client = RecordingClient(FakeResponse(_successful_proposal()))
        provider = GeminiAccountingProvider(
            api_key="API-SECRET-MARKER",
            http_client=client,
        )

        provider.classify_product(_v2_request())

        rendered_body = client.calls[0]["content"].decode("utf-8")
        for forbidden_marker in (
            "RAW-PROVIDER-MARKER",
            "PDF-MARKER",
            "PROVIDER-RESPONSE-MARKER",
            "SECRET-MARKER",
            "SOURCE-LINK-MARKER",
            "CLIENT-SECRET-MARKER",
            "API-SECRET-MARKER",
        ):
            self.assertNotIn(forbidden_marker, rendered_body)

    def test_v2_transport_strips_all_source_material_and_keeps_accounting_semantics(self) -> None:
        client = RecordingClient(FakeResponse(_successful_proposal()))
        provider = GeminiAccountingProvider(api_key="test-key", http_client=client)

        provider.classify_product(_v2_request())

        request_body = client.calls[0]["content"]
        self.assertIsInstance(request_body, bytes)
        rendered_body = request_body.decode("utf-8")
        for forbidden_marker in (
            "HEADER-EVIDENCE-MARKER",
            "HEADER-SOURCE-POSITION-MARKER",
            "SUPPLIER-EVIDENCE-MARKER",
            "SUPPLIER-SOURCE-POSITION-MARKER",
            "CUSTOMER-EVIDENCE-MARKER",
            "CUSTOMER-SOURCE-POSITION-MARKER",
            "LINE-EVIDENCE-MARKER",
            "LINE-SOURCE-POSITION-MARKER",
            "VAT-EVIDENCE-MARKER",
            "VAT-SOURCE-POSITION-MARKER",
            "TAX-EVIDENCE-MARKER",
            "TAX-SOURCE-POSITION-MARKER",
            "MONETARY-EVIDENCE-MARKER",
            "MONETARY-SOURCE-POSITION-MARKER",
            "TOTAL-EVIDENCE-MARKER",
            "TOTAL-SOURCE-POSITION-MARKER",
            "SOURCE-LINK-MARKER",
        ):
            self.assertNotIn(forbidden_marker, rendered_body)

        posted = json.loads(request_body)
        user_payload = _posted_v2_user_payload(posted)
        facts = json.loads(user_payload["raw_line"])
        self.assertEqual(facts["header"]["invoice_no"], "SAFE-INVOICE")
        self.assertEqual(facts["supplier_party"]["tax_id"], "1234567890")
        self.assertEqual(facts["line_items"][0]["identity_ref"], "line:l1")
        self.assertEqual(facts["line_items"][0]["decision_ref"], "line:l1")
        self.assertEqual(facts["line_items"][0]["description"], "Safe service")
        self.assertEqual(facts["vat_summary"][0]["identity_ref"], "vat:v20")
        self.assertEqual(facts["tax_components"][0]["canonical_tax_kind"], "withholding")
        self.assertEqual(facts["tax_components"][0]["economic_effect"], "reduce_payable")
        self.assertEqual(facts["monetary_components"][0]["signed_effect"], "decrease_payable")
        self.assertEqual(facts["totals"]["payable_total"], "105.00")

    def test_v1_accounting_selection_instruction_remains_exactly_frozen(self) -> None:
        request = AccountingSelectionRequest(
            accounting_projection={},
            candidate_details=(),
            round_index=0,
        )

        self.assertEqual(
            classification_instructions_for(request),
            V1_ACCOUNTING_SELECTION_INSTRUCTION,
        )


if __name__ == "__main__":
    unittest.main()
