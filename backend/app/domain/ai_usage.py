from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4


DEFAULT_PRICE_PER_1K_CHARS: dict[str, Decimal] = {
    "openai": Decimal("0.0010"),
    "gemini": Decimal("0.0008"),
    "manus": Decimal("0.0012"),
    "replay_provider": Decimal("0.0000"),
    "static_rules": Decimal("0.0000"),
}


@dataclass(frozen=True)
class AiUsageEvent:
    event_id: str
    client_id: str
    provider: str
    operation: str
    input_chars: int
    estimated_cost_usd: str
    ai_used: bool
    skipped_reason: str
    created_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def estimate_ai_cost_usd(
    *,
    provider: str,
    input_chars: int,
    price_per_1k_chars: Decimal | None = None,
) -> Decimal:
    if input_chars <= 0:
        return Decimal("0.000000")
    unit_price = price_per_1k_chars
    if unit_price is None:
        unit_price = DEFAULT_PRICE_PER_1K_CHARS.get(provider.lower(), Decimal("0.0010"))
    cost = (Decimal(input_chars) / Decimal(1000)) * unit_price
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def build_ai_usage_event(
    *,
    client_id: str,
    provider: str,
    operation: str,
    input_chars: int,
    ai_used: bool,
    skipped_reason: str = "",
) -> AiUsageEvent:
    return AiUsageEvent(
        event_id=str(uuid4()),
        client_id=client_id,
        provider=provider,
        operation=operation,
        input_chars=max(input_chars, 0),
        estimated_cost_usd=f"{estimate_ai_cost_usd(provider=provider, input_chars=input_chars):.6f}",
        ai_used=ai_used,
        skipped_reason=skipped_reason,
        created_at=utc_now(),
    )


def summarize_ai_usage(events: list[dict[str, object]], *, monthly_cap_usd: Decimal) -> dict[str, object]:
    total = Decimal("0.000000")
    used_count = 0
    skipped_count = 0
    for event in events:
        total += Decimal(str(event.get("estimated_cost_usd") or "0"))
        if event.get("ai_used"):
            used_count += 1
        else:
            skipped_count += 1
    remaining = max(monthly_cap_usd - total, Decimal("0.000000")).quantize(Decimal("0.000001"))
    return {
        "event_count": len(events),
        "ai_used_count": used_count,
        "ai_skipped_count": skipped_count,
        "estimated_total_cost_usd": f"{total.quantize(Decimal('0.000001')):.6f}",
        "monthly_cap_usd": f"{monthly_cap_usd.quantize(Decimal('0.01')):.2f}",
        "remaining_cap_usd": f"{remaining:.6f}",
        "cap_exceeded": total >= monthly_cap_usd,
    }


def ai_usage_payload(event: AiUsageEvent) -> dict[str, object]:
    return asdict(event)
