from __future__ import annotations

import time
from math import ceil
from typing import Mapping

from fastapi import HTTPException, Request

from app.domain.rate_limits import rate_limit_config


_BUCKETS: dict[tuple[str, str], list[float]] = {}


def reset_rate_limit_state() -> None:
    _BUCKETS.clear()


def _request_identity(request: Request | None, explicit_key: str) -> str:
    if explicit_key.strip():
        return explicit_key.strip()
    if request is not None and request.client is not None:
        return request.client.host
    return "anonymous"


def enforce_rate_limit(
    *,
    scope: str,
    key: str = "",
    request: Request | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    config = rate_limit_config(env)
    if not config.enabled:
        return
    limit = config.ai_max_requests if scope == "ai" else config.export_max_requests
    if limit <= 0:
        raise HTTPException(
            status_code=429,
            detail={"allowed": False, "reason": "rate_limit_exceeded", "scope": scope},
            headers={"Retry-After": str(config.window_seconds)},
        )
    now = time.monotonic()
    bucket_key = (scope, _request_identity(request, key))
    cutoff = now - config.window_seconds
    requests = [timestamp for timestamp in _BUCKETS.get(bucket_key, []) if timestamp > cutoff]
    if len(requests) >= limit:
        retry_after = max(1, ceil(config.window_seconds - (now - requests[0])))
        _BUCKETS[bucket_key] = requests
        raise HTTPException(
            status_code=429,
            detail={"allowed": False, "reason": "rate_limit_exceeded", "scope": scope},
            headers={"Retry-After": str(retry_after)},
        )
    requests.append(now)
    _BUCKETS[bucket_key] = requests
