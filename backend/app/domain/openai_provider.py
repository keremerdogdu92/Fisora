from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from app.domain.ai_capacity import normalize_cerebras_rate_limit_headers, normalize_groq_rate_limit_headers
from app.domain.ai_classification import AiClassificationRequest
from app.domain.canonical_invoices import CanonicalExtractionRequest
from app.domain.review_rule_interpretation import REVIEW_RULE_INTERPRETATION_SCHEMA
from app.domain.statement_ai_suggestions import StatementAiSuggestionRequest


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
GROQ_RESPONSES_URL = "https://api.groq.com/openai/v1/responses"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
CEREBRAS_CHAT_COMPLETIONS_URL = "https://api.cerebras.ai/v1/chat/completions"
NVIDIA_CHAT_COMPLETIONS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
CLOUDFLARE_CHAT_COMPLETIONS_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
)
SAMBANOVA_CHAT_COMPLETIONS_URL = "https://api.sambanova.ai/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_COMPARISON_MODEL = "gpt-5.4-nano"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GROQ_COMPARISON_MODEL = "openai/gpt-oss-120b"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"
DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-120b"
DEFAULT_CLOUDFLARE_MODEL = "@cf/openai/gpt-oss-120b"
DEFAULT_SAMBANOVA_MODEL = "gpt-oss-120b"
PRODUCT_CLASSIFICATION_PROMPT_VERSION = "invoice-semantic-decision-v1"


def _provider_user_payload(
    payload: Mapping[str, Any],
    *,
    exclude_instructions: bool = False,
) -> dict[str, Any]:
    """Keep provider-channel metadata out of the document payload."""
    excluded = {"output_schema"}
    if exclude_instructions:
        excluded.add("instructions")
    return {key: value for key, value in payload.items() if key not in excluded}


def classification_instructions_for(request: AiClassificationRequest) -> str:
    semantic_stage = str(request.context.semantic_stage or "initial_account_decision").strip().lower()
    if semantic_stage == "research_synthesis":
        return (
            "Canonical satir ve mevcut mukellef baglamini esas al. Arastirma sonuclarini yalniz kaynakli ek kanit "
            "olarak degerlendir. Sayfa teslimat, menu veya reklam ifadelerini urun/hizmet kimligi sanma. Her "
            "canonical_line_id icin yalniz verilen gercek hesap adaylarindan en uygun hesabi sec ve celisen kaniti acikla."
        )
    if semantic_stage == "account_correction":
        return (
            "Onceki semantik karar korunmustur ancak secilen hesap mekanik olarak kullanilamiyor. Verilen dogrulama "
            "hatasini ve guncel gercek hesap adaylarini kullanarak ayni canonical_line_id icin yeni hesap sec. Genel "
            "hesaba sirf kullanilabilir oldugu icin gecme; ekonomik anlami koru."
        )
    stage = str(request.context.candidate_strategy.stage or "").strip().lower()
    if stage == "family_select":
        return (
            "Fatura satirinin ekonomik anlamini, belge yonunu ve mukellef faaliyetini degerlendir. "
            "Yalniz verilen gercek hesap ailelerinden uygun olanlari sec. "
            "Kaniti yetersiz ve hesap secimini degistirecek belirsizlikte research iste."
        )
    if stage == "counterparty_resolve":
        return (
            "Faturadaki karsi tarafi yalniz verilen gercek cari adaylariyla eslestir. "
            "VKN/TCKN, unvan ve dogrulanmis baglari birlikte kullan. "
            "Uygun cari yoksa yeni cari ihtiyacini belirt; cari kodu uydurma."
        )
    if stage == "vat_group_account":
        return (
            "Tek bir canonical KDV grubunun tum satirlarini birlikte degerlendir. Yalniz verilen gercek ve "
            "yon-filtreli net hesap adaylarindan bir hesap sec. Farkli satir anlatimi veya dusuk guven grubu "
            "kendiliginden bolmez; yalniz muhtemel istisna satir kimliklerini inceleme kaniti olarak belirt. "
            "Canonical kimlikleri, grup uyeligini, tutarlari veya KDV degerlerini degistirme."
        )
    return (
        "Her canonical fatura satiri icin mukellefin gercek hesap planindaki en uygun gercek hesabi sec. "
        "Satir kaniti, belge yonu, faaliyet/NACE, dogrulanmis kurallar ve verilen adaylari birlikte degerlendir. "
        "Verilmeyen hesap kodu uretme; her canonical_line_id icin tam karar ve kisa gerekce don. "
        "Canonical tutar veya KDV degerlerini degistirme; gerekirse research iste."
    )


def canonical_extraction_instructions_for(request: CanonicalExtractionRequest) -> str:
    if str(request.mode or "repair").strip().lower() == "discovery":
        return (
            "Yalniz verilen PDF belge iceriginde acikca gorulen fatura alanlarini ve tum fatura satirlarini gozlemle. "
            "Belgede yazmayan degeri bos birak; parasal hesaplama veya muhasebe karari yapma. "
            "Her satirin kesin source_position degerini ver; canonical_line_id ve external_line_id alanlarini bos birak. "
            "Urun veya hizmet anlamini satici unvanindan turetme."
        )
    return (
        "PDF belge kanitindan canonical JSON line_items alanlarini tamamla. "
        "Her canonical_line_id icin tam bir sonuc don; satir ekleme, silme, birlestirme veya kimlik degistirme. "
        "Bir deger belgede acikca yazmiyorsa bos string don. Parasal hesaplama yapma veya muhasebe karari verme. "
        "Canonical tutar veya KDV degerlerini birbirine uydurma."
    )


class OpenAiAccountingProvider:
    """OpenAI Responses API adapter for schema-validated accounting suggestions."""

    provider_name = "openai"
    product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION
    product_classification_instructions = (
        "Gercek hesap plani adaylarindan kanitli bir muhasebe taslagi hazirla. "
        "candidate_strategy.stage=line_batch ise her canonical_line_id icin tam bir kez line_decision don."
    )
    canonical_extraction_instructions = "PDF belge alanlarini yalniz kaynak kanitindan gozlemle; hesaplama yapma."
    statement_suggestion_instructions = (
        "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
        "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
        "Export izni verme; mustavir onayi gerektigini koru."
    )
    review_rule_interpretation_instructions = (
        "Muhasebe mustavirinin karar notunu kisa, denetlenebilir bir kural adayina cevir. "
        "Sadece verilen belge, cari, hesap ve aday kural alanlarini kullan. "
        "Yeni hesap kodu veya cari kod uydurma. Not belirsizse status=needs_clarification don. "
        "Cikti mustavire gosterilecek; teknik olmayan Turkce kullan. "
        "Kural aktiflesse bile ilk uygulamalarda mustavir kontrolu ve KDV/fis dengesi korundugunu belirt."
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
        instructions = classification_instructions_for(request)
        self.last_product_classification_instructions = instructions
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = canonical_extraction_instructions_for(request)
        return self._post_structured_json(
            schema_name="fisora_invoice_canonical_extraction",
            instructions=instructions,
            user_payload=_provider_user_payload(payload, exclude_instructions=True),
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        payload = dict(request)
        return self._post_structured_json(
            schema_name="fisora_review_rule_interpretation",
            instructions=self.review_rule_interpretation_instructions,
            user_payload=_provider_user_payload(payload),
            schema=REVIEW_RULE_INTERPRETATION_SCHEMA,
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
    product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION
    product_classification_instructions = OpenAiAccountingProvider.product_classification_instructions
    canonical_extraction_instructions = OpenAiAccountingProvider.canonical_extraction_instructions
    statement_suggestion_instructions = (
        "Banka/POS ekstresi satiri icin muhasebe taslak onerisi uret. "
        "Sadece verilen satir bilgisi ve mevcut hesap kodu adayi uzerinden yorum yap. "
        "Export izni verme; mustavir onayi gerektigini koru."
    )
    review_rule_interpretation_instructions = OpenAiAccountingProvider.review_rule_interpretation_instructions

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
        max_tokens: int | None = None,
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
        self.max_tokens = max_tokens
        self.last_capacity_snapshot: dict[str, object] = {}

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = classification_instructions_for(request)
        self.last_product_classification_instructions = instructions
        return self._post_structured_json(
            schema_name="fisora_invoice_ai_draft",
            instructions=instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        instructions = canonical_extraction_instructions_for(request)
        return self._post_structured_json(
            schema_name="fisora_invoice_canonical_extraction",
            instructions=instructions,
            user_payload=_provider_user_payload(payload, exclude_instructions=True),
            schema=payload["output_schema"],
        )

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        payload = request.to_schema_payload()
        return self._post_structured_json(
            schema_name="fisora_statement_ai_suggestion",
            instructions=self.statement_suggestion_instructions,
            user_payload=_provider_user_payload(payload),
            schema=payload["output_schema"],
        )

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        payload = dict(request)
        return self._post_structured_json(
            schema_name="fisora_review_rule_interpretation",
            instructions=self.review_rule_interpretation_instructions,
            user_payload=_provider_user_payload(payload),
            schema=REVIEW_RULE_INTERPRETATION_SCHEMA,
        )

    def _post_structured_json(
        self,
        *,
        schema_name: str,
        instructions: str,
        user_payload: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        request_payload: dict[str, Any] = {
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
        }
        if self.max_tokens is not None:
            request_payload["max_tokens"] = self.max_tokens
        response = self.http_client.post(
            self.chat_completions_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                **self.extra_headers,
            },
            json=request_payload,
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
        self.model = ""
        self.product_classification_instructions = ""
        self.product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        return self._call("classify_product", request)

    def extract_invoice_canonical(self, request: CanonicalExtractionRequest) -> dict[str, Any]:
        return self._call("extract_invoice_canonical", request)

    def suggest_statement_line(self, request: StatementAiSuggestionRequest) -> dict[str, Any]:
        return self._call("suggest_statement_line", request)

    def interpret_review_rule(self, request: Mapping[str, object]) -> dict[str, Any]:
        return self._call("interpret_review_rule", request)

    def _call(
        self,
        method_name: str,
        request: AiClassificationRequest | CanonicalExtractionRequest | StatementAiSuggestionRequest | Mapping[str, object],
    ) -> dict[str, Any]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                result = getattr(provider, method_name)(request)
                self.last_provider_name = provider.provider_name
                self.last_capacity_snapshot = dict(getattr(provider, "last_capacity_snapshot", {}) or {})
                self.model = str(getattr(provider, "model", "") or "")
                self.product_classification_instructions = str(
                    getattr(provider, "last_product_classification_instructions", "")
                    or getattr(provider, "product_classification_instructions", "")
                    or ""
                )
                self.product_classification_prompt_version = str(
                    getattr(provider, "product_classification_prompt_version", "")
                    or PRODUCT_CLASSIFICATION_PROMPT_VERSION
                )
                return result
            except Exception as exc:  # noqa: BLE001 - fallback boundary keeps the pipeline alive
                errors.append(f"{provider.provider_name}: {type(exc).__name__}: {str(exc)[:160]}")
        raise RuntimeError("; ".join(errors))


class TaskRoutingAccountingProvider:
    """Route semantic stages to independently ordered configured providers."""

    def __init__(
        self,
        *,
        classification_provider: object,
        counterparty_provider: object,
        configured_provider: object | None = None,
    ) -> None:
        self.classification_provider = classification_provider
        self.counterparty_provider = counterparty_provider
        compatibility_provider = configured_provider or classification_provider
        self.provider_name = str(getattr(compatibility_provider, "provider_name", "") or "")
        self.providers = tuple(
            getattr(compatibility_provider, "providers", (compatibility_provider,))
        )
        self.last_provider_name = ""
        self.last_capacity_snapshot: dict[str, object] = {}
        self.model = ""
        self.product_classification_instructions = ""
        self.product_classification_prompt_version = PRODUCT_CLASSIFICATION_PROMPT_VERSION

    def classify_product(self, request: AiClassificationRequest) -> dict[str, Any]:
        stage = str(request.context.candidate_strategy.stage or "").strip().lower()
        provider = self.counterparty_provider if stage == "counterparty_resolve" else self.classification_provider
        try:
            return provider.classify_product(request)
        finally:
            self.last_provider_name = str(
                getattr(provider, "last_provider_name", "") or getattr(provider, "provider_name", "") or ""
            )
            self.last_capacity_snapshot = dict(getattr(provider, "last_capacity_snapshot", {}) or {})
            self.model = str(getattr(provider, "model", "") or "")
            self.product_classification_instructions = str(
                getattr(provider, "last_product_classification_instructions", "")
                or getattr(provider, "product_classification_instructions", "")
                or classification_instructions_for(request)
            )
            self.product_classification_prompt_version = str(
                getattr(provider, "product_classification_prompt_version", "")
                or PRODUCT_CLASSIFICATION_PROMPT_VERSION
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
