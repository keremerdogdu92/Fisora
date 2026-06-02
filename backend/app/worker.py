from __future__ import annotations

import os
import time
from pathlib import Path

from app.persistence.workflow_store import JsonWorkflowStore


DEFAULT_STORE_PATH = Path(os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
RETENTION_INTERVAL_SECONDS = int(os.environ.get("FISORA_WORKER_RETENTION_INTERVAL_SECONDS", "86400"))
RUN_ONCE = os.environ.get("FISORA_WORKER_RUN_ONCE", "").lower() in {"1", "true", "yes"}


def run_retention_once() -> dict[str, object]:
    store = JsonWorkflowStore(DEFAULT_STORE_PATH)
    return store.apply_document_retention(delete_files=True)


def main() -> None:
    while True:
        summary = run_retention_once()
        print(f"document_retention {summary}", flush=True)
        if RUN_ONCE:
            return
        time.sleep(RETENTION_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
