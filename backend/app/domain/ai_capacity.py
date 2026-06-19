from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


PROVIDER_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "openai": "OPENAI_API_KEY",
}
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-20b:free"
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean_decimal(value: object) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        parsed = Decimal("0")
    return f"{parsed.quantize(Decimal('0.000001')):.6f}"


def _int_or_none(value: object) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(Decimal(str(value).strip()))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _rate_window(*, limit: object = None, remaining: object = None, reset: object = "") -> dict[str, object]:
    return {
        "limit": _int_or_none(limit),
        "remaining": _int_or_none(remaining),
        "reset": str(reset or ""),
    }


def normalize_groq_rate_limit_headers(headers: Mapping[str, object]) -> dict[str, object]:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    return {
        "source": "response_headers",
        "daily_requests": _rate_window(
            limit=lowered.get("x-ratelimit-limit-requests"),
            remaining=lowered.get("x-ratelimit-remaining-requests"),
            reset=lowered.get("x-ratelimit-reset-requests", ""),
        ),
        "minute_tokens": _rate_window(
            limit=lowered.get("x-ratelimit-limit-tokens"),
            remaining=lowered.get("x-ratelimit-remaining-tokens"),
            reset=lowered.get("x-ratelimit-reset-tokens", ""),
        ),
        "last_checked_at": utc_now(),
    }


def normalize_cerebras_rate_limit_headers(headers: Mapping[str, object]) -> dict[str, object]:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    return {
        "source": "response_headers",
        "daily_requests": _rate_window(
            limit=lowered.get("x-ratelimit-limit-requests-day"),
            remaining=lowered.get("x-ratelimit-remaining-requests-day"),
            reset=lowered.get("x-ratelimit-reset-requests-day", ""),
        ),
        "minute_tokens": _rate_window(
            limit=lowered.get("x-ratelimit-limit-tokens-minute"),
            remaining=lowered.get("x-ratelimit-remaining-tokens-minute"),
            reset=lowered.get("x-ratelimit-reset-tokens-minute", ""),
        ),
        "last_checked_at": utc_now(),
    }


def normalize_openrouter_key_payload(payload: Mapping[str, object]) -> dict[str, object]:
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(data, Mapping):
        data = {}
    return {
        "source": "key_endpoint",
        "credit": {
            "limit": None if data.get("limit") is None else _clean_decimal(data.get("limit")),
            "remaining": None if data.get("limit_remaining") is None else _clean_decimal(data.get("limit_remaining")),
            "reset": str(data.get("limit_reset") or ""),
        },
        "usage": {
            "daily": _clean_decimal(data.get("usage_daily", 0)),
            "weekly": _clean_decimal(data.get("usage_weekly", 0)),
            "monthly": _clean_decimal(data.get("usage_monthly", 0)),
        },
        "last_checked_at": utc_now(),
    }


def _provider_chain(env: Mapping[str, str]) -> list[str]:
    chain = [name.strip().lower() for name in str(env.get("FISORA_AI_PROVIDER_CHAIN", "")).split(",") if name.strip()]
    provider_name = str(env.get("FISORA_AI_PROVIDER", "")).strip().lower()
    if not chain and provider_name and provider_name != "disabled":
        chain = [provider_name]
    return [provider for provider in chain if provider in {"groq", "openrouter", "cerebras", "openai"}]


def _provider_model(provider: str, env: Mapping[str, str]) -> str:
    if provider == "groq":
        return str(env.get("FISORA_GROQ_MODEL") or env.get("FISORA_AI_MODEL") or DEFAULT_GROQ_MODEL)
    if provider == "openrouter":
        return str(env.get("FISORA_OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL)
    if provider == "cerebras":
        return str(env.get("FISORA_CEREBRAS_MODEL") or DEFAULT_CEREBRAS_MODEL)
    return str(env.get("FISORA_OPENAI_MODEL") or env.get("FISORA_AI_MODEL") or "")


def _public_model(value: str) -> str:
    return value.replace(":free", "").replace(":FREE", "")


def _requests_per_document(env: Mapping[str, str]) -> int:
    values = []
    for key, default in (
        ("FISORA_AI_MAX_PROVIDER_CALLS", "3"),
        ("FISORA_AI_STATEMENT_MAX_PROVIDER_CALLS", "3"),
    ):
        parsed = _int_or_none(env.get(key, default))
        if parsed is not None:
            values.append(max(parsed, 1))
    return max(values or [3])


def _document_estimate(snapshot: Mapping[str, object] | None, *, requests_per_document: int) -> int:
    if not snapshot:
        return 0
    daily = snapshot.get("daily_requests")
    if isinstance(daily, Mapping):
        remaining = _int_or_none(daily.get("remaining"))
        if remaining is not None:
            return max(remaining // max(requests_per_document, 1), 0)
    return 0


def _agent_status(*, configured: bool, snapshot: Mapping[str, object] | None) -> str:
    if not configured:
        return "not_configured"
    if snapshot and snapshot.get("status") == "error":
        return "last_check_error"
    return "ready" if snapshot else "configured"


def _research_enabled(env: Mapping[str, str]) -> bool:
    return str(env.get("FISORA_RESEARCH_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}


def _research_agent(env: Mapping[str, str]) -> dict[str, object]:
    enabled = _research_enabled(env)
    key_present = bool(str(env.get("OPENAI_API_KEY", "")).strip())
    configured = enabled and key_present
    max_per_document = max(_int_or_none(env.get("FISORA_RESEARCH_MAX_PER_DOCUMENT", "1")) or 1, 1)
    if configured:
        status = "ready"
        internet_researches = max_per_document
    elif enabled:
        status = "missing_key"
        internet_researches = 0
    else:
        status = "disabled"
        internet_researches = 0
    return {
        "kind": "research",
        "slot": "research",
        "label": "Araştırma ajanı",
        "configured": configured,
        "status": status,
        "model": str(env.get("FISORA_RESEARCH_MODEL") or "gpt-5.4-mini"),
        "source": "server_config",
        "last_checked_at": "",
        "daily_requests": {"limit": None, "remaining": None, "reset": ""},
        "minute_tokens": {"limit": None, "remaining": None, "reset": ""},
        "estimates": {
            "document_queries": 0,
            "internet_researches": internet_researches,
            "confidence": "configured" if configured else "not_available",
        },
    }


def ai_capacity_payload(
    *,
    env: Mapping[str, str],
    provider_snapshots: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    snapshots = provider_snapshots or {}
    agents: list[dict[str, object]] = []
    requests_per_document = _requests_per_document(env)
    for index, provider in enumerate(_provider_chain(env), start=1):
        snapshot = snapshots.get(provider) or {}
        key_name = PROVIDER_KEY_ENV.get(provider, "")
        configured = bool(key_name and str(env.get(key_name, "")).strip() and _provider_model(provider, env).strip())
        document_queries = _document_estimate(snapshot, requests_per_document=requests_per_document)
        agents.append(
            {
                "kind": "document",
                "slot": f"document_{index}",
                "label": f"Belge ajanı {index}",
                "configured": configured,
                "status": _agent_status(configured=configured, snapshot=snapshot),
                "model": _public_model(_provider_model(provider, env)),
                "source": str(snapshot.get("source") or "server_config"),
                "last_checked_at": str(snapshot.get("last_checked_at") or ""),
                "daily_requests": snapshot.get("daily_requests") or {"limit": None, "remaining": None, "reset": ""},
                "minute_tokens": snapshot.get("minute_tokens") or {"limit": None, "remaining": None, "reset": ""},
                "credit": snapshot.get("credit") or {"limit": None, "remaining": None, "reset": ""},
                "estimates": {
                    "document_queries": document_queries,
                    "internet_researches": 0,
                    "confidence": "header_based" if document_queries else "configured" if configured else "not_available",
                },
            }
        )
    agents.append(_research_agent(env))
    return {
        "generated_at": utc_now(),
        "status": "ok",
        "agents": agents,
        "totals": {
            "document_queries": sum(int(agent["estimates"]["document_queries"]) for agent in agents),
            "internet_researches": sum(int(agent["estimates"]["internet_researches"]) for agent in agents),
        },
    }
