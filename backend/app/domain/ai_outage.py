from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import re
from typing import Literal


INITIAL_RETRY_DELAYS = (
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=10),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
)
RETRY_CADENCE = timedelta(hours=6)
RETRY_WINDOW = timedelta(hours=24)
MAX_JITTER = timedelta(seconds=59)
FAILURE_CATEGORIES = frozenset({"timeout", "rate_limited", "unavailable", "configuration_error"})
_SAFE_PROVIDER_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


@dataclass(frozen=True)
class AiRetryDecision:
    status: Literal["retry_wait", "manual_attention"]
    retry_step: int
    delay: timedelta | None
    next_attempt_at: datetime | None


def next_ai_retry(
    *,
    step: int,
    opened_at: datetime,
    now: datetime,
    document_id: str = "",
) -> AiRetryDecision:
    if step < 0:
        raise ValueError("retry_step_must_not_be_negative")
    if now < opened_at:
        raise ValueError("retry_now_precedes_opened_at")

    deadline = opened_at + RETRY_WINDOW
    if now >= deadline:
        return AiRetryDecision(
            status="manual_attention",
            retry_step=step,
            delay=None,
            next_attempt_at=None,
        )

    delay = INITIAL_RETRY_DELAYS[step] if step < len(INITIAL_RETRY_DELAYS) else RETRY_CADENCE
    next_attempt_at = now + delay + _retry_jitter(document_id)
    if next_attempt_at > deadline:
        return AiRetryDecision(
            status="manual_attention",
            retry_step=step,
            delay=None,
            next_attempt_at=None,
        )

    return AiRetryDecision(
        status="retry_wait",
        retry_step=step + 1,
        delay=delay,
        next_attempt_at=next_attempt_at,
    )


def sanitize_provider_failure_evidence(
    *,
    provider_name: str,
    category: str,
    attempted_at: datetime,
) -> dict[str, str]:
    provider = str(provider_name or "").strip().lower()
    safe_provider = provider if _SAFE_PROVIDER_NAME.fullmatch(provider) else "unknown"
    safe_category = str(category or "").strip().lower()
    if safe_category not in FAILURE_CATEGORIES:
        safe_category = "unavailable"
    return {
        "provider": safe_provider,
        "category": safe_category,
        "attempted_at": attempted_at.astimezone(UTC).isoformat(timespec="seconds"),
    }


def _retry_jitter(document_id: str) -> timedelta:
    if not document_id:
        return timedelta(0)
    digest = hashlib.sha256(document_id.encode("utf-8")).digest()
    return timedelta(seconds=digest[0] % (int(MAX_JITTER.total_seconds()) + 1))
