from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from app.domain.ai_capacity import normalize_cerebras_rate_limit_headers, normalize_groq_rate_limit_headers
from app.domain.ai_classification import AiClassificationRequest
from app.domain.statement_ai_suggestions import StatementAiSuggestionRequest


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
GROQ_RESPONSES_URL = "https://api.groq.com/openai/v1/responses"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
CEREBRAS_CHAT_COMPLETIONS_URL = "https://api.cerebras.ai/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_COMPARISON_MODEL = "gpt-5.4-nano"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GROQ_COMPARISON_MODEL = "openai/gpt-oss-120b"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"


class OpenAiAccountingProvider:
    """OpenAI Responses API adapter for schema-validated accounting suggestions."""

    provider_name = "openai"
    product_classification_instructions = (
        "Muhasebe mustavirine yardim eden kontrollu bir taslak motorusun. "
        "Yalnizca verilen sinirli fatura kalemi, faaliyet ve mevcut hesap/cari adaylarini kullan. "
        "Internet aramasi yapma veya kaynak biliyormus gibi davranma. "
        "Egitiminden biliyorsan marka/modelin urun kategorisini soyle. "
        "Emin degilsen needs_research=true ve kisa research_query don. "
        "Yeni hesap kodu uydurma, emin degilsen bos string ve review risk flag'i don. "
        "Kanuni KDV ve hesap ailesi kurallarini ezme. "
        "Export izni verme; bu cikti sadece mustavir review taslagidir."
    )
    statement_suggestion_instructions = (
        "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
        "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
        "Export izni verme; mustavir onayi gerektigini koru."
    )

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
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=self.product_classification_instructions,
            user_payload=payload,
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
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
        self._capture_capacity_snapshot(response)
        response.raise_for_status()
        return _extract_json_response(response.json())

    def _capture_capacity_snapshot(self, response: Any) -> None:
        if self.provider_name == "groq":
            self.last_capacity_snapshot = normalize_groq_rate_limit_headers(dict(getattr(response, "headers", {}) or {}))


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


class ChatCompletionsAccountingProvider:
    """OpenAI-compatible chat-completions adapter for fallback providers."""

    provider_name = "chat_completions"
    product_classification_instructions = (
        "Muhasebe mustavirine yardim eden kontrollu bir taslak motorusun. "
        "Yalnizca verilen sinirli fatura kalemi, faaliyet ve mevcut hesap/cari adaylarini kullan. "
        "Yeni hesap kodu uydurma, emin degilsen bos string ve review risk flag'i don. "
        "Export izni verme; bu cikti sadece mustavir review taslagidir."
    )
    statement_suggestion_instructions = (
        "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
        "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
        "Export izni verme; mustavir onayi gerektigini koru."
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        chat_completions_url: str,
        provider_name: str,
        key_name: str,
        extra_headers: Mapping[str, str] | None = None,
        http_client: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError(f"{key_name} is required when FISORA_AI_PROVIDER={provider_name}")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.chat_completions_url = chat_completions_url
        self.provider_name = provider_name
        self.extra_headers = {key: value for key, value in (extra_headers or {}).items() if value.strip()}
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=self.product_classification_instructions,
            user_payload=payload,
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
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
            self.chat_completions_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                **self.extra_headers,
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {
                        "role": "user",
                        "content": (
                            "Yalnizca gecerli JSON obje don. "
                            f"Schema adi: {schema_name}. "
                            f"JSON schema: {json.dumps(schema, ensure_ascii=False)}. "
                            f"Girdi: {json.dumps(user_payload, ensure_ascii=False)}"
                        ),
                    },
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "top_p": 1,
                "stream": False,
            },
            timeout=self.timeout_seconds,
        )
        self._capture_capacity_snapshot(response)
        response.raise_for_status()
        return _extract_chat_completion_json_response(response.json())

    def _capture_capacity_snapshot(self, response: Any) -> None:
        if self.provider_name == "groq":
            self.last_capacity_snapshot = normalize_groq_rate_limit_headers(dict(getattr(response, "headers", {}) or {}))
        if self.provider_name == "cerebras":
            self.last_capacity_snapshot = normalize_cerebras_rate_limit_headers(dict(getattr(response, "headers", {}) or {}))


class FallbackAccountingProvider:
    """Try multiple accounting providers before reporting a provider failure."""

    def __init__(self, providers: list[OpenAiAccountingProvider]) -> None:
        if not providers:
            raise ValueError("FallbackAccountingProvider requires at least one provider")
        self.providers = providers
        self.provider_name = ">".join(provider.provider_name for provider in providers)
        self.last_provider_name = ""
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        return self._call("classify_product", request)

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        return self._call("suggest_statement_line", request)

    def _call(self, method_name: str, request: AiClassificationRequest | StatementAiSuggestionRequest) -> dict[str, Any]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                result = getattr(provider, method_name)(request)
                self.last_provider_name = provider.provider_name
                self.last_capacity_snapshot = dict(getattr(provider, "last_capacity_snapshot", {}) or {})
                return result
            except Exception as exc:  # noqa: BLE001 - fallback boundary keeps the pipeline alive
                errors.append(f"{provider.provider_name}: {type(exc).__name__}: {str(exc)[:160]}")
        raise RuntimeError("; ".join(errors))


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
            if content.get("type") not in {"output_text", "text"}:
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return _loads_object("".join(chunks))
    raise ValueError("OpenAI response did not contain structured JSON output")


def _extract_chat_completion_json_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Chat completion response did not contain choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("Chat completion choice must be an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Chat completion choice did not contain a message")
    content = message.get("content")
    if isinstance(content, list):
        chunks = [
            item.get("text", "")
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        ]
        content = "".join(chunks)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Chat completion message did not contain JSON text")
    return _loads_object(_strip_json_fence(content))


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads_object(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("OpenAI structured output must be a JSON object")
    return loaded
