# File: backend/tests/test_deepseek_final_provider.py
# Summary: Verifies the direct DeepSeek final-accountant transport and low-reasoning request contract.
from __future__ import annotations

from app.domain.openai_provider import ChatCompletionsAccountingProvider
from app.workflows.document_processing import _build_final_accountant_provider


def test_final_accountant_prefers_direct_deepseek_when_key_exists() -> None:
    provider = _build_final_accountant_provider(
        {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_FLASH_MODEL": "deepseek-v4-flash",
        }
    )
    assert isinstance(provider, ChatCompletionsAccountingProvider)
    assert provider.provider_name == "deepseek"
    assert provider.model == "deepseek-v4-flash"
    assert provider.max_tokens == 16384
    assert provider.request_body_overrides == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
    }


def test_chat_provider_merges_deepseek_request_overrides() -> None:
    captured: dict[str, object] = {}
    class FakeResponse:
        headers: dict[str, str] = {}
        def raise_for_status(self) -> None:
            return None
        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
            captured["json"] = json
            return FakeResponse()

    provider = ChatCompletionsAccountingProvider(
        api_key="test-key", model="deepseek-v4-flash",
        chat_completions_url="https://api.deepseek.com/chat/completions",
        provider_name="deepseek", key_name="DEEPSEEK_API_KEY",
        http_client=FakeClient(), max_tokens=16384,
        request_body_overrides={"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
    )
    result = provider._post_structured_json(
        schema_name="test", instructions="Return JSON.",
        user_payload={"x": 1}, schema={"type": "object"},
    )
    assert result == {"ok": True}
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "low"
    assert payload["max_tokens"] == 16384
