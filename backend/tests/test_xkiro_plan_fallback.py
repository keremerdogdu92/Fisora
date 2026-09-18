# File: backend/tests/test_xkiro_plan_fallback.py
# Summary: Verifies xKiro free-model quota failover to the plan-covered paid fallback without changing non-quota failures.
from __future__ import annotations

from pathlib import Path
import sys
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.openai_provider import ChatCompletionsAccountingProvider
from app.domain.xkiro_plan_fallback import (
    XkiroQuotaFallbackProvider,
    build_xkiro_final_provider,
)


class StubProvider:
    provider_name = "xkiro"

    def __init__(self, model: str, *, status_code: int | None = None) -> None:
        self.model = model
        self.status_code = status_code
        self.calls = 0
        self.last_capacity_snapshot: dict[str, object] = {}

    def _post_structured_json(self, **_: object) -> dict[str, object]:
        self.calls += 1
        if self.status_code is not None:
            request = httpx.Request("POST", "https://api.xkiro.com/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("xKiro error", request=request, response=response)
        return {"ok": True, "model": self.model}


class XkiroPlanFallbackTests(unittest.TestCase):
    def test_uses_paid_fallback_after_primary_429(self) -> None:
        primary = StubProvider("deepseek/deepseek-v4-flash", status_code=429)
        paid = StubProvider("openai/gpt-5.4-mini")
        provider = XkiroQuotaFallbackProvider([primary, paid])

        result = provider._post_structured_json(
            schema_name="test",
            instructions="Return JSON.",
            user_payload={"invoice": "test"},
            schema={"type": "object"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(paid.calls, 1)
        self.assertEqual(provider.model, "openai/gpt-5.4-mini")

    def test_does_not_use_paid_fallback_after_permission_error(self) -> None:
        primary = StubProvider("deepseek/deepseek-v4-flash", status_code=403)
        paid = StubProvider("openai/gpt-5.4-mini")
        provider = XkiroQuotaFallbackProvider([primary, paid])

        with self.assertRaises(httpx.HTTPStatusError):
            provider._post_structured_json(
                schema_name="test",
                instructions="Return JSON.",
                user_payload={"invoice": "test"},
                schema={"type": "object"},
            )

        self.assertEqual(primary.calls, 1)
        self.assertEqual(paid.calls, 0)

    def test_builder_adds_default_plan_fallback(self) -> None:
        provider = build_xkiro_final_provider(
            {
                "XKIRO_API_KEY": "test-key",
                "FISORA_XKIRO_MODEL": "deepseek/deepseek-v4-flash",
                "FISORA_XKIRO_TIMEOUT_SECONDS": "120",
                "FISORA_XKIRO_MAX_TOKENS": "4096",
            }
        )

        self.assertIsInstance(provider, XkiroQuotaFallbackProvider)
        self.assertEqual(
            [item.model for item in provider.providers],
            ["deepseek/deepseek-v4-flash", "openai/gpt-5.4-mini"],
        )
        self.assertEqual(provider.providers[0].timeout_seconds, 120.0)
        self.assertEqual(provider.providers[0].max_tokens, 4096)

    def test_builder_allows_explicit_fallback_disable(self) -> None:
        provider = build_xkiro_final_provider(
            {
                "XKIRO_API_KEY": "test-key",
                "FISORA_XKIRO_MODEL": "deepseek/deepseek-v4-flash",
                "FISORA_XKIRO_PLAN_FALLBACK_MODELS": "",
            }
        )

        self.assertIsInstance(provider, ChatCompletionsAccountingProvider)
        self.assertEqual(provider.model, "deepseek/deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
