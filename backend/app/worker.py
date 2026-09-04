# File: backend/app/worker.py
# Summary: Runs concurrent document-processing workers with shared provider runtimes, HTML reader reuse, and optional retention.
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Mapping

from app.domain.gemini_pdf_runtime import (
    GeminiPdfRuntime,
    build_gemini_pdf_runtime_from_env,
    gemini_pdf_v2_enabled,
)
from app.integrations.html_source_reader import RestartingHtmlSourceReader, build_html_source_reader_from_env
from app.persistence.store_factory import build_workflow_store
from app.services.retention_service import RetentionService
from app.workflows.document_processing import (
    _three_stage_gemini_runtime,
    is_transient_persistence_error,
    process_queued_documents,
)
from app.workflows.three_stage_accounting_pipeline import three_stage_accounting_enabled


RETENTION_INTERVAL_SECONDS = int(os.environ.get("FISORA_WORKER_RETENTION_INTERVAL_SECONDS", "86400"))
IDLE_MIN_SECONDS = float(os.environ.get("FISORA_WORKER_IDLE_MIN_SECONDS", "1"))
IDLE_MAX_SECONDS = float(os.environ.get("FISORA_WORKER_IDLE_MAX_SECONDS", "5"))
MAX_JOBS_PER_TICK = int(os.environ.get("FISORA_WORKER_MAX_JOBS_PER_TICK", "10"))
RUN_ONCE = os.environ.get("FISORA_WORKER_RUN_ONCE", "").lower() in {"1", "true", "yes"}
_GEMINI_RUNTIME: GeminiPdfRuntime | None = None
_GEMINI_RUNTIME_LOCK = Lock()
_HTML_SOURCE_READER: RestartingHtmlSourceReader | None = None
_HTML_SOURCE_READER_LOCK = Lock()


def worker_concurrency_from_env(env: Mapping[str, str] | None = None) -> int:
    source = env or os.environ
    raw_value = str(source.get("FISORA_WORKER_CONCURRENCY") or "1").strip()
    try:
        return max(int(raw_value), 1)
    except ValueError:
        return 1


def retention_enabled_from_env(env: Mapping[str, str] | None = None) -> bool:
    source = env or os.environ
    return str(source.get("FISORA_WORKER_RETENTION_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}


def run_retention_once() -> dict[str, object]:
    store = build_workflow_store(json_path=os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
    if getattr(store, "normalized_accounting_enabled", False):
        return RetentionService(
            store=store,
            document_storage_path=Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "/opt/fisora/data/exports/documents")),
        ).run_due(now=datetime.now(UTC), worker_id=f"worker-{os.getpid()}")
    return store.apply_document_retention(delete_files=True)


def _gemini_runtime_for_worker() -> GeminiPdfRuntime | None:
    global _GEMINI_RUNTIME
    if not (three_stage_accounting_enabled(os.environ) or gemini_pdf_v2_enabled(os.environ)):
        return None
    if _GEMINI_RUNTIME is None:
        with _GEMINI_RUNTIME_LOCK:
            if _GEMINI_RUNTIME is None:
                _GEMINI_RUNTIME = (
                    _three_stage_gemini_runtime(os.environ)
                    if three_stage_accounting_enabled(os.environ)
                    else build_gemini_pdf_runtime_from_env(os.environ)
                )
    return _GEMINI_RUNTIME


def _html_source_reader_for_worker() -> RestartingHtmlSourceReader:
    """Return one process-global Node reader shared by all Python worker slots."""

    global _HTML_SOURCE_READER
    if _HTML_SOURCE_READER is None:
        with _HTML_SOURCE_READER_LOCK:
            if _HTML_SOURCE_READER is None:
                _HTML_SOURCE_READER = build_html_source_reader_from_env()
    return _HTML_SOURCE_READER


def run_processing_once() -> dict[str, object]:
    try:
        store = build_workflow_store(json_path=os.environ.get("FISORA_STORE_PATH", "/opt/fisora/data/exports/phase0_store.json"))
        runtime = _gemini_runtime_for_worker()
        provider = runtime.provider if runtime is not None and runtime.available else None
        max_parallel_chunks = (
            runtime.max_parallel_accounting_chunks
            if runtime is not None and runtime.available
            else 1
        )
        candidate_experiment_percent = (
            runtime.candidate_experiment_percent
            if runtime is not None and runtime.available
            else None
        )
        max_accounting_request_bytes = (
            runtime.max_accounting_request_bytes
            if runtime is not None and runtime.available
            else None
        )
        return process_queued_documents(
            store,
            max_jobs=MAX_JOBS_PER_TICK,
            extraction_provider=provider,
            accounting_provider=provider,
            html_source_reader=_html_source_reader_for_worker(),
            max_parallel_accounting_chunks=max_parallel_chunks,
            candidate_experiment_percent=candidate_experiment_percent,
            max_accounting_request_bytes=max_accounting_request_bytes,
        )
    except Exception as exc:
        if not is_transient_persistence_error(exc):
            raise
        return {
            "run_id": "processing-run-transient-database-error",
            "queued_count": 0,
            "processed_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "current_status": "retry_wait",
        }


def next_idle_delay(current: float, *, processed_count: int) -> float:
    if processed_count > 0:
        return 0.0
    return min(max(current * 2, IDLE_MIN_SECONDS), max(IDLE_MAX_SECONDS, IDLE_MIN_SECONDS))


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
    next_retention_at = 0.0
    idle_delay = 0.0
    concurrency = worker_concurrency_from_env()
    retention_enabled = retention_enabled_from_env()
    while True:
        processing_summary = run_processing_tick(concurrency=concurrency)
        print(f"document_processing {processing_summary}", flush=True)
        now = time.monotonic()
        if retention_enabled and now >= next_retention_at:
            retention_summary = run_retention_once()
            print(f"document_retention {retention_summary}", flush=True)
            next_retention_at = now + max(RETENTION_INTERVAL_SECONDS, 1)
        if RUN_ONCE:
            return
        processed_count = int(processing_summary.get("processed_count") or 0)
        idle_delay = next_idle_delay(idle_delay, processed_count=processed_count)
        if processed_count == 0 and idle_delay > 0:
            time.sleep(idle_delay)


if __name__ == "__main__":
    main()
