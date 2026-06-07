from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from app.domain.ai_classification import AiClassificationRequest
from app.domain.statement_ai_suggestions import StatementAiSuggestionRequest


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
GROQ_RESPONSES_URL = "https://api.groq.com/openai/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_COMPARISON_MODEL = "gpt-5.4-nano"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GROQ_COMPARISON_MODEL = "openai/gpt-oss-120b"


class OpenAiAccountingProvider:
    """OpenAI Responses API adapter for schema-validated accounting suggestions."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        responses_url: str = OPENAI_RESPONSES_URL,
        provider_name: str = "openai",
        key_name: str = "OPENAI_API_KEY",
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError(f"{key_name} is required when FISORA_AI_PROVIDER={provider_name}")
        self.api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_OPENAI_MODEL
        self.responses_url = responses_url
        self.provider_name = provider_name
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=(
                "Muhasebe mustavirine yardim eden kontrollu bir taslak motorusun. "
                "Yalnizca verilen sinirli fatura kalemi, faaliyet ve mevcut hesap/cari adaylarini kullan. "
                "Yeni hesap kodu uydurma, emin degilsen bos string ve review risk flag'i don. "
                "Export izni verme; bu cikti sadece mustavir review taslagidir."
            ),
            user_payload=payload,
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=(
                "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
                "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
                "Export izni verme; mustavir onayi gerektigini koru."
            ),
            user_payload=payload,
            schema=payload["output_schema"],
        )

    def _post_structured_json(
        self,
        *,
        schema_name: str,
        instructions: str,
        user_payload: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        response = self.http_client.post(
            self.responses_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return _extract_json_response(response.json())


class GroqAccountingProvider(OpenAiAccountingProvider):
    """Groq OpenAI-compatible Responses API adapter for free-tier pre-demo tests."""

    provider_name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_GROQ_MODEL,
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model.strip() or DEFAULT_GROQ_MODEL,
            responses_url=GROQ_RESPONSES_URL,
            provider_name="groq",
            key_name="GROQ_API_KEY",
            http_client=http_client,
            timeout_seconds=timeout_seconds,
        )


def _extract_json_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("output_parsed"), dict):
        return dict(payload["output_parsed"])
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return _loads_object(output_text)

    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, Mapping):
                continue
            if isinstance(content.get("parsed"), dict):
                return dict(content["parsed"])
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return _loads_object("".join(chunks))
    raise ValueError("OpenAI response did not contain structured JSON output")


def _loads_object(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("OpenAI structured output must be a JSON object")
    return loaded
