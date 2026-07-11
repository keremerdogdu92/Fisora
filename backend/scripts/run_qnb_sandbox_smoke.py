from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.qnb_efatura import (  # noqa: E402
    QnbConnectionCredentials,
    QnbSoapEfaturaAdapter,
    QnbSyncService,
)
from app.persistence.workflow_store import JsonWorkflowStore  # noqa: E402
from app.workflows.document_processing import process_queued_documents  # noqa: E402


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def receiver_credentials(env: Mapping[str, str]) -> tuple[str, QnbConnectionCredentials]:
    environment = str(env.get("QNB_EFATURA_RECEIVER_ENV") or "").strip().upper()
    if not environment:
        raise ValueError("QNB_EFATURA_RECEIVER_ENV is required")
    prefix = f"QNB_EFATURA_{environment}_"
    required = {
        "base_url": str(env.get(f"{prefix}BASE_URL") or "").strip(),
        "username": str(env.get(f"{prefix}USERNAME") or "").strip(),
        "password": str(env.get(f"{prefix}PASSWORD") or "").strip(),
        "vkn": str(env.get(f"{prefix}VKN") or "").strip(),
        "erp_code": str(env.get("QNB_ERP_CODE") or "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"missing QNB sandbox settings: {', '.join(sorted(missing))}")
    return environment, QnbConnectionCredentials(**required)


def safe_sync_summary(result: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "sync_run_id",
        "client_id",
        "mode",
        "status",
        "page_count",
        "listed_count",
        "downloaded_count",
        "skipped_duplicate_count",
        "queued_processing_count",
        "failed_count",
        "cursor_before",
        "cursor_after",
        "backfill_truncated",
    )
    return {name: result.get(name) for name in allowed if name in result}


def run_smoke(
    *,
    env: Mapping[str, str],
    work_dir: Path,
    client_id: str,
    start_date: str,
    end_date: str,
    process_worker: bool,
    repeat_sync: bool,
) -> dict[str, object]:
    environment, credentials = receiver_credentials(env)
    adapter = QnbSoapEfaturaAdapter(timeout=30)
    connection = adapter.test_connection(credentials)
    output: dict[str, object] = {
        "receiver_environment": environment,
        "connection": {"ok": connection.ok, "status": connection.status},
        "window": {"start_date": start_date, "end_date": end_date},
    }
    if not connection.ok:
        return output

    work_dir.mkdir(parents=True, exist_ok=True)
    store = JsonWorkflowStore(work_dir / "store.json")
    service = QnbSyncService(
        store=store,
        document_storage_path=work_dir / "documents",
        adapter=adapter,
    )
    cursor = store.get_qnb_sync_cursor(client_id=client_id) if not start_date and not end_date else ""
    first = service.sync_incoming_invoices(
        client_id=client_id,
        credentials=credentials,
        start_date=start_date,
        end_date=end_date,
        cursor=cursor,
    )
    store.save_qnb_sync_run(client_id=client_id, sync_run=first)
    output["first_sync"] = safe_sync_summary(first)

    if process_worker and int(first.get("queued_processing_count") or 0) > 0:
        output["worker"] = process_queued_documents(store, max_jobs=100)

    if repeat_sync:
        repeat_cursor = store.get_qnb_sync_cursor(client_id=client_id) if not start_date and not end_date else ""
        second = service.sync_incoming_invoices(
            client_id=client_id,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
            cursor=repeat_cursor,
        )
        store.save_qnb_sync_run(client_id=client_id, sync_run=second)
        output["repeat_sync"] = safe_sync_summary(second)

    workspace = store.get_workspace(client_id)
    output["workspace"] = {
        "uploaded_document_count": len(workspace.get("uploaded_documents") or []),
        "processed_document_count": len(workspace.get("documents") or []),
        "queued_job_count": sum(
            1
            for job in workspace.get("processing_jobs") or []
            if str(job.get("status") or "") == "queued"
        ),
        "failed_job_count": sum(
            1
            for job in workspace.get("processing_jobs") or []
            if str(job.get("status") or "") == "failed"
        ),
        "saved_cursor": store.get_qnb_sync_cursor(client_id=client_id),
    }
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a secret-safe QNB receiver sandbox sync against an ignored local env file."
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.qnb.local")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "exports" / "qnb-sandbox-smoke")
    parser.add_argument("--client-id", default="qnb-sandbox-receiver")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--process-worker", action="store_true")
    parser.add_argument("--repeat-sync", action="store_true")
    parser.add_argument(
        "--cursor-mode",
        action="store_true",
        help="Use the persisted QNB belgeSiraNo cursor instead of a date backfill window.",
    )
    parser.add_argument(
        "--expect-document",
        action="store_true",
        help="Return exit code 2 when the selected window lists no QNB document.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    end_date = "" if args.cursor_mode else (args.end_date or str(date.today()))
    start_date = "" if args.cursor_mode else (args.start_date or str(date.today() - timedelta(days=max(args.days, 0))))
    try:
        output = run_smoke(
            env=load_env_file(args.env_file),
            work_dir=args.work_dir,
            client_id=args.client_id,
            start_date=start_date,
            end_date=end_date,
            process_worker=args.process_worker,
            repeat_sync=args.repeat_sync,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}, ensure_ascii=True))
        return 1
    listed_count = int((output.get("first_sync") or {}).get("listed_count") or 0)
    output["ok"] = bool((output.get("connection") or {}).get("ok")) and (
        not args.expect_document or listed_count > 0
    )
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    if args.expect_document and listed_count == 0:
        return 2
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
