from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Mapping

from app.persistence.store_factory import build_workflow_store
from app.workflows.document_processing import process_queued_documents


RETENTION_INTERVAL_SECONDS = int(os.environ.get("FISORA_WORKER_RETENTION_INTERVAL_SECONDS", "86400"))
PROCESSING_INTERVAL_SECONDS = int(os.environ.get("FISORA_WORKER_PROCESSING_INTERVAL_SECONDS", "30"))
MAX_JOBS_PER_TICK = int(os.environ.get("FISORA_WORKER_MAX_JOBS_PER_TICK", "10"))
RUN_ONCE = os.environ.get("FISORA_WORKER_RUN_ONCE", "").lower() in {"1", "true", "yes"}


def worker_concurrency_from_env(env: Mapping[str, str] | None = None) -> int:
    source = env or os.environ
    raw_value = str(source.get("FISORA_WORKER_CONCURRENCY") or "1").strip()
    try:
        return max(int(raw_value), 1)
    except ValueError:
        return 1


def run_retention_once() -> dict[str, object]:
    store = build_workflow_store(json_path=os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
    return store.apply_document_retention(delete_files=True)


def run_processing_once() -> dict[str, object]:
    store = build_workflow_store(json_path=os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
    return process_queued_documents(store, max_jobs=MAX_JOBS_PER_TICK)


def _merge_processing_summaries(summaries: list[dict[str, object]]) -> dict[str, object]:
    if not summaries:
        return {
            "run_id": "processing-run-empty",
            "queued_count": 0,
            "processed_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "current_status": "idle",
        }
    merged = {
        "run_id": ",".join(str(summary.get("run_id") or "") for summary in summaries if summary.get("run_id")),
        "queued_count": max(int(summary.get("queued_count") or 0) for summary in summaries),
        "processed_count": sum(int(summary.get("processed_count") or 0) for summary in summaries),
        "completed_count": sum(int(summary.get("completed_count") or 0) for summary in summaries),
        "failed_count": sum(int(summary.get("failed_count") or 0) for summary in summaries),
        "current_status": "completed",
        "worker_slots": len(summaries),
    }
    if merged["processed_count"] == 0:
        merged["current_status"] = "idle" if merged["queued_count"] == 0 else "queued"
    elif merged["failed_count"]:
        merged["current_status"] = "completed_with_errors"
    return merged


def run_processing_tick(*, concurrency: int | None = None) -> dict[str, object]:
    slot_count = max(concurrency or worker_concurrency_from_env(), 1)
    if slot_count == 1:
        summary = run_processing_once()
        summary["worker_slots"] = 1
        return summary
    summaries: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=slot_count) as executor:
        futures = [executor.submit(run_processing_once) for _ in range(slot_count)]
        for future in as_completed(futures):
            summaries.append(future.result())
    return _merge_processing_summaries(summaries)


def main() -> None:
    retention_tick = 0
    concurrency = worker_concurrency_from_env()
    while True:
        processing_summary = run_processing_tick(concurrency=concurrency)
        print(f"document_processing {processing_summary}", flush=True)
        if retention_tick == 0:
            retention_summary = run_retention_once()
            print(f"document_retention {retention_summary}", flush=True)
        if RUN_ONCE:
            return
        retention_tick = (retention_tick + PROCESSING_INTERVAL_SECONDS) % RETENTION_INTERVAL_SECONDS
        time.sleep(PROCESSING_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
