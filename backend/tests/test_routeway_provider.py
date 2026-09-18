# File: backend/tests/test_routeway_provider.py
# Summary: Verifies Routeway free-tier provider configuration, transport compatibility, and secret-safe capacity reporting.
from __future__ import annotations

from app.domain.ai_capacity import ai_capacity_payload
from app.domain.openai_provider import ChatCompletionsAccountingProvider
from app.workflows.document_processing import (
    _accounting_provider_from_env,
    _configured_provider_names,
)


def test_routeway_provider_uses_free_deepseek_defaults() -> None:
    provider = _accounting_provider_from_env(
        "routeway",
        {"ROUTEWAY_API_KEY": "test-routeway-secret"},
    )

    assert isinstance(provider, ChatCompletionsAccountingProvider)
    assert provider.provider_name == "routeway"
    assert provider.model == "deepseek-v4-flash:free"
    assert provider.chat_completions_url == "https://api.routeway.ai/v1/chat/completions"
    assert provider.extra_headers == {"User-Agent": "Fisora/1.0"}
    assert provider.timeout_seconds == 60.0
    assert provider.max_tokens == 4096
    assert provider.max_tokens_field == "max_completion_tokens"
    assert provider.response_format_enabled is False


def test_routeway_is_supported_in_configured_provider_chain() -> None:
    names = _configured_provider_names(
        {
            "FISORA_AI_PROVIDER_CHAIN": "gemini,routeway,openrouter",
        }
    )

    assert names == ("gemini", "routeway", "openrouter")


def test_routeway_capacity_is_configured_without_exposing_secret() -> None:
    payload = ai_capacity_payload(
        env={
            "FISORA_AI_PROVIDER_CHAIN": "routeway",
            "ROUTEWAY_API_KEY": "test-routeway-secret",
        }
    )

    routeway = payload["agents"][0]
    assert routeway["configured"] is True
    assert routeway["model"] == "deepseek-v4-flash"
    assert "test-routeway-secret" not in str(payload)


def test_routeway_transport_uses_supported_request_shape() -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
            timeout: float,
        ) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

    provider = _accounting_provider_from_env(
        "routeway",
        {"ROUTEWAY_API_KEY": "test-routeway-secret"},
    )
    provider.http_client = FakeClient()
    result = provider._post_structured_json(
        schema_name="test",
        instructions="Return JSON.",
        user_payload={"x": 1},
        schema={"type": "object"},
    )

    assert result == {"ok": True}
    headers = captured["headers"]
    body = captured["json"]
    assert isinstance(headers, dict)
    assert isinstance(body, dict)
    assert headers["User-Agent"] == "Fisora/1.0"
    assert body["model"] == "deepseek-v4-flash:free"
    assert body["max_completion_tokens"] == 4096
    assert "max_tokens" not in body
    assert "response_format" not in body
