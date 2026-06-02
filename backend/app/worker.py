from __future__ import annotations

import os
import time

from app.persistence.store_factory import build_workflow_store
from app.workflows.document_processing import process_queued_documents


RETENTION_INTERVAL_SECONDS = int(os.environ.get("FISORA_WORKER_RETENTION_INTERVAL_SECONDS", "86400"))
PROCESSING_INTERVAL_SECONDS = int(os.environ.get("FISORA_WORKER_PROCESSING_INTERVAL_SECONDS", "30"))
MAX_JOBS_PER_TICK = int(os.environ.get("FISORA_WORKER_MAX_JOBS_PER_TICK", "10"))
RUN_ONCE = os.environ.get("FISORA_WORKER_RUN_ONCE", "").lower() in {"1", "true", "yes"}


def run_retention_once() -> dict[str, object]:
    store = build_workflow_store(json_path=os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
    return store.apply_document_retention(delete_files=True)


def run_processing_once() -> dict[str, object]:
    store = build_workflow_store(json_path=os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
    return process_queued_documents(store, max_jobs=MAX_JOBS_PER_TICK)


def main() -> None:
    retention_tick = 0
    while True:
        processing_summary = run_processing_once()
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
