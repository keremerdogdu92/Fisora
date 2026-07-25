from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import time

from app.domain.qnb_efatura import (
    QnbConnectionService,
    build_qnb_adapter_from_env,
)
from app.domain.qnb_scheduler import QnbScheduler
from app.persistence.store_factory import build_workflow_store


SCHEDULER_INTERVAL_SECONDS = max(
    int(os.environ.get("FISORA_QNB_SCHEDULER_INTERVAL_SECONDS", "30")),
    5,
)
RUN_ONCE = os.environ.get("FISORA_QNB_SCHEDULER_RUN_ONCE", "").lower() in {
    "1",
    "true",
    "yes",
}
SCHEDULER_ENABLED = os.environ.get(
    "FISORA_QNB_SCHEDULER_ENABLED",
    "false",
).lower() in {"1", "true", "yes"}
HEARTBEAT_PATH = Path(
    os.environ.get(
        "FISORA_QNB_SCHEDULER_HEARTBEAT_PATH",
        "/tmp/fisora-qnb-scheduler-heartbeat",
    )
)


def build_store():
    return build_workflow_store(
        json_path=os.environ.get(
            "FISORA_STORE_PATH",
            "/opt/fisora/data/exports/phase0_store.json",
        )
    )


def build_connection_service(store) -> QnbConnectionService:
    return QnbConnectionService(
        store=store,
        document_storage_path=Path(
            os.environ.get(
                "FISORA_DOCUMENT_STORAGE_PATH",
                "/opt/fisora/data/documents",
            )
        ),
        adapter=build_qnb_adapter_from_env(os.environ),
    )


def build_scheduler(store=None) -> QnbScheduler:
    active_store = store or build_store()
    return QnbScheduler(
        store=active_store,
        service_factory=lambda: build_connection_service(active_store),
        worker_id=f"qnb-scheduler-{os.getpid()}",
    )


def write_heartbeat() -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.touch()


def run_qnb_scheduler_once(store=None) -> dict[str, object] | None:
    if not SCHEDULER_ENABLED:
        return {"status": "disabled", "reason": "global_kill_switch"}
    return build_scheduler(store).run_due_once()


def run_manual_sync_once(store=None) -> dict[str, object] | None:
    if not SCHEDULER_ENABLED:
        return None
    active_store = store or build_store()
    worker_id = f"qnb-scheduler-{os.getpid()}"
    claimed_at = datetime.now(UTC)
    request = active_store.claim_next_qnb_sync_request(
        worker_id=worker_id,
        now=claimed_at.isoformat(timespec="seconds"),
        lease_expires_at=(claimed_at + timedelta(minutes=15)).isoformat(
            timespec="seconds"
        ),
    )
    if not request:
        return None
    try:
        result = build_connection_service(active_store).sync_incoming_invoices(
            client_id=str(request["client_id"]),
            start_date=str(request.get("start_date") or ""),
            end_date=str(request.get("end_date") or ""),
        )
        completed = active_store.complete_qnb_sync_request(
            client_id=str(request["client_id"]),
            request_id=str(request["request_id"]),
            worker_id=worker_id,
            lease_token=str(request["lease_token"]),
            status="completed",
            result=result,
        )
        return {
            "status": (
                "completed" if completed else "stale_completion_rejected"
            ),
            "request_id": str(request["request_id"]),
            "result": result,
        }
    except Exception as exc:
        active_store.complete_qnb_sync_request(
            client_id=str(request["client_id"]),
            request_id=str(request["request_id"]),
            worker_id=worker_id,
            lease_token=str(request["lease_token"]),
            status="failed",
            result={"error_code": type(exc).__name__},
        )
        return {
            "status": "failed",
            "request_id": str(request["request_id"]),
            "error_code": type(exc).__name__,
        }


def main() -> None:
    store = build_store()
    while True:
        summary = run_manual_sync_once(store) or run_qnb_scheduler_once(store)
        write_heartbeat()
        if summary:
            print(f"qnb_scheduler {summary}", flush=True)
        if RUN_ONCE:
            return
        time.sleep(SCHEDULER_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
