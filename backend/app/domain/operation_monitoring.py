from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class OperationEvent:
    event_id: str
    client_id: str
    event_type: str
    status: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_operation_event(
    *,
    client_id: str,
    event_type: str,
    status: str = "info",
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> OperationEvent:
    clean_status = status if status in {"info", "ok", "warning", "error"} else "info"
    return OperationEvent(
        event_id=str(uuid4()),
        client_id=client_id.strip() or "__system__",
        event_type=event_type.strip() or "operation",
        status=clean_status,
        message=message.strip(),
        metadata=metadata or {},
        created_at=utc_now(),
    )


def operation_event_payload(event: OperationEvent) -> dict[str, Any]:
    return asdict(event)


def summarize_operation_health(
    *,
    events: list[dict[str, Any]],
    processing_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    event_status_counts = Counter(str(event.get("status") or "info") for event in events)
    event_type_counts = Counter(str(event.get("event_type") or "operation") for event in events)
    job_status_counts = Counter(str(job.get("status") or "unknown") for job in processing_jobs)
    latest_event = events[-1] if events else None
    failed_jobs = job_status_counts.get("failed", 0)
    error_events = event_status_counts.get("error", 0)
    warning_events = event_status_counts.get("warning", 0)
    if failed_jobs or error_events:
        health_status = "error"
    elif warning_events or job_status_counts.get("queued", 0) or job_status_counts.get("processing", 0):
        health_status = "warning"
    else:
        health_status = "ok"
    return {
        "health_status": health_status,
        "event_count": len(events),
        "event_status_counts": dict(event_status_counts),
        "event_type_counts": dict(event_type_counts),
        "job_count": len(processing_jobs),
        "job_status_counts": dict(job_status_counts),
        "failed_job_count": failed_jobs,
        "latest_event": latest_event,
    }
