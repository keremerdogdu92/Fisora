from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool
    window_seconds: int
    ai_max_requests: int
    export_max_requests: int
    auth_max_requests: int

    @property
    def configured(self) -> bool:
        return self.enabled and self.window_seconds > 0 and self.ai_max_requests > 0 and self.export_max_requests > 0 and self.auth_max_requests > 0


def _env_bool(value: str, *, default: bool) -> bool:
    if not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(value: str, *, default: int) -> int:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def rate_limit_config(env: Mapping[str, str] | None = None) -> RateLimitConfig:
    source = env if env is not None else os.environ
    return RateLimitConfig(
        enabled=_env_bool(source.get("FISORA_RATE_LIMIT_ENABLED", "true"), default=True),
        window_seconds=max(_env_int(source.get("FISORA_RATE_LIMIT_WINDOW_SECONDS", "60"), default=60), 1),
        ai_max_requests=max(_env_int(source.get("FISORA_RATE_LIMIT_AI_MAX_REQUESTS", "120"), default=120), 0),
        export_max_requests=max(_env_int(source.get("FISORA_RATE_LIMIT_EXPORT_MAX_REQUESTS", "60"), default=60), 0),
        auth_max_requests=max(_env_int(source.get("FISORA_RATE_LIMIT_AUTH_MAX_REQUESTS", "10"), default=10), 0),
    )
