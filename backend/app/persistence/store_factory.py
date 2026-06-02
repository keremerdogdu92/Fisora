from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.persistence.workflow_store import JsonWorkflowStore


def build_workflow_store(
    *,
    store_backend: str | None = None,
    json_path: Path | str | None = None,
    postgres_dsn: str | None = None,
) -> Any:
    backend = (store_backend or os.environ.get("FISORA_STORE_BACKEND") or "json").strip().lower()
    if backend == "json":
        path = json_path or os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json")
        return JsonWorkflowStore(path)
    if backend == "postgres":
        dsn = postgres_dsn or os.environ.get("FISORA_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
        return PostgresWorkflowStore(dsn)
    raise ValueError(f"Unsupported workflow store backend: {backend}")
