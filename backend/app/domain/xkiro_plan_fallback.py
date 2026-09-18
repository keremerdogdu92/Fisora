# File: backend/app/domain/xkiro_plan_fallback.py
# Summary: Keeps the xKiro final-accountant path on the free model first and falls back to plan-covered models after a 429 limit response.
from __future__ import annotations

from typing import Any, Callable, Mapping

import httpx

from app.domain.openai_provider import (
    DEFAULT_XKIRO_MODEL,
    XKIRO_CHAT_COMPLETIONS_URL,
    ChatCompletionsAccountingProvider,
)


DEFAULT_XKIRO_PLAN_FALLBACK_MODELS = ("openai/gpt-5.4-mini",)


def _configured_fallback_models(source: Mapping[str, str], primary_model: str) -> tuple[str, ...]:
    configured = str(
        source.get(
            "FISORA_XKIRO_PLAN_FALLBACK_MODELS",
            ",".join(DEFAULT_XKIRO_PLAN_FALLBACK_MODELS),
        )
        or ""
    )
    return tuple(
        dict.fromkeys(
            model.strip()
            for model in configured.split(",")
            if model.strip() and model.strip() != primary_model
        )
    )


class XkiroQuotaFallbackProvider:
    """Use the primary xKiro model until its free/rate allowance returns HTTP 429."""

    def __init__(self, providers: list[Any]) -> None:
        if not providers:
            raise ValueError("XkiroQuotaFallbackProvider requires at least one provider")
        self.providers = tuple(providers)
        self.provider_name = "xkiro"
        self.last_provider_name = ""
        self.model = providers[0].model
        self.last_capacity_snapshot: dict[str, object] = {}

    def _post_structured_json(
        self,
        *,
        schema_name: str,
        instructions: str,
        user_payload: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        last_error: httpx.HTTPStatusError | None = None
        for index, provider in enumerate(self.providers):
            try:
                result = provider._post_structured_json(
                    schema_name=schema_name,
                    instructions=instructions,
                    user_payload=user_payload,
                    schema=schema,
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                has_next_model = index + 1 < len(self.providers)
                if exc.response.status_code == 429 and has_next_model:
                    continue
                raise
            self.last_provider_name = provider.provider_name
            self.model = provider.model
            self.last_capacity_snapshot = dict(
                getattr(provider, "last_capacity_snapshot", {}) or {}
            )
            return result
        if last_error is not None:
            raise last_error
        raise RuntimeError("xKiro provider chain completed without a result")


def build_xkiro_final_provider(
    source: Mapping[str, str],
    *,
    provider_factory: Callable[[str, Mapping[str, str]], object] | None = None,
) -> object:
    """Build the final-accountant xKiro provider with a free-first plan fallback chain."""

    primary_model = str(source.get("FISORA_XKIRO_MODEL", DEFAULT_XKIRO_MODEL) or DEFAULT_XKIRO_MODEL).strip()
    models = (primary_model, *_configured_fallback_models(source, primary_model))

    def default_factory(_: str, model_source: Mapping[str, str]) -> object:
        return ChatCompletionsAccountingProvider(
            api_key=str(model_source.get("XKIRO_API_KEY", "") or ""),
            model=str(model_source.get("FISORA_XKIRO_MODEL", DEFAULT_XKIRO_MODEL) or DEFAULT_XKIRO_MODEL),
            chat_completions_url=str(
                model_source.get("FISORA_XKIRO_CHAT_COMPLETIONS_URL", XKIRO_CHAT_COMPLETIONS_URL)
                or XKIRO_CHAT_COMPLETIONS_URL
            ),
            provider_name="xkiro",
            key_name="XKIRO_API_KEY",
            timeout_seconds=float(model_source.get("FISORA_XKIRO_TIMEOUT_SECONDS", "60")),
            max_tokens=int(model_source.get("FISORA_XKIRO_MAX_TOKENS", "1024")),
        )

    factory = provider_factory or default_factory
    providers: list[object] = []
    for model in models:
        model_source = dict(source)
        model_source["FISORA_XKIRO_MODEL"] = model
        providers.append(factory("xkiro", model_source))
    if len(providers) == 1:
        return providers[0]
    return XkiroQuotaFallbackProvider(providers)
