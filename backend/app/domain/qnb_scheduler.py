from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def normalize_qnb_sync_policy(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    frequency = max(5, min(int(payload.get("frequency_minutes") or 60), 1440))
    run_limit = max(1, min(int(payload.get("max_documents_per_run") or 100), 1000))
    enabled = bool(payload.get("enabled"))
    return {
        "enabled": enabled,
        "start_from_date": str(payload.get("start_from_date") or ""),
        "frequency_minutes": frequency,
        "max_documents_per_run": run_limit,
        "provider_request_budget": max(10, min(int(payload.get("provider_request_budget") or 150), 150)),
        "status_reconciliation_enabled": bool(payload.get("status_reconciliation_enabled", True)),
        "next_run_at": str(payload.get("next_run_at") or _iso(current if enabled else current + timedelta(days=3650))),
        "lease_owner": "",
        "lease_expires_at": "",
        "consecutive_failure_count": int(payload.get("consecutive_failure_count") or 0),
    }


def due_qnb_status_ettns(workspace: dict[str, Any], *, now: datetime, limit: int) -> list[str]:
    due: list[str] = []
    for document in workspace.get("uploaded_documents", []) or []:
        ettn = str(document.get("source_qnb_ettn") or document.get("source_external_uuid") or "").strip()
        if not ettn or str(document.get("source_provider") or "") != "qnb_esolutions":
            continue
        issue_raw = str(document.get("source_issue_date") or "")[:10]
        checked_raw = str(document.get("source_qnb_status_checked_at") or "")
        try:
            age_days = (now.date() - datetime.fromisoformat(issue_raw).date()).days
        except ValueError:
            age_days = 0
        try:
            checked_at = datetime.fromisoformat(checked_raw.replace("Z", "+00:00")) if checked_raw else None
            checked_age_hours = (now - checked_at.astimezone(UTC)).total_seconds() / 3600 if checked_at else 10_000
        except ValueError:
            checked_age_hours = 10_000
        review_sensitive = bool(document.get("qnb_review_required")) or str(document.get("export_status") or "") in {"approved", "exported"}
        interval_hours = 6 if age_days <= 7 else 24 if review_sensitive and age_days <= 90 else 168
        if checked_age_hours >= interval_hours:
            due.append(ettn)
        if len(due) >= max(limit, 0):
            break
    return due


class QnbScheduler:
    def __init__(self, *, store: Any, service_factory: Callable[[], Any], worker_id: str = "") -> None:
        self.store = store
        self.service_factory = service_factory
        self.worker_id = worker_id or f"qnb-worker-{uuid4()}"

    def run_due_once(self, *, now: datetime | None = None) -> dict[str, Any] | None:
        current = now or datetime.now(UTC)
        policy = self.store.claim_due_qnb_sync_policy(
            worker_id=self.worker_id,
            now=_iso(current),
            lease_expires_at=_iso(current + timedelta(minutes=10)),
        )
        if not policy:
            return None
        client_id = str(policy["client_id"])
        service = self.service_factory()
        try:
            request_budget = int(policy.get("provider_request_budget") or 150)
            document_limit = min(int(policy.get("max_documents_per_run") or 100), max(request_budget - 2, 1))
            sync = service.sync_incoming_invoices(client_id=client_id, max_documents=document_limit)
            status = {"status": "disabled", "updated_count": 0, "error_count": 0}
            if policy.get("status_reconciliation_enabled", True):
                remaining = max(request_budget - int(sync.get("page_count") or 0) - int(sync.get("downloaded_count") or 0) - 2, 0)
                ettns = due_qnb_status_ettns(self.store.get_workspace(client_id), now=current, limit=remaining)
                status = service.reconcile_incoming_invoices(client_id=client_id, ettns=ettns) if ettns else {"status": "completed", "updated_count": 0, "error_count": 0, "requested_count": 0}
                status["request_budget_remaining"] = remaining - int(status.get("requested_count") or 0)
            failed = sync.get("status") not in {"completed", "partial_completed", "backfill_truncated"} or status.get("status") == "partial_failed"
            failures = int(policy.get("consecutive_failure_count") or 0) + 1 if failed else 0
            delay = min(int(policy.get("frequency_minutes") or 60) * (2 ** failures), 1440)
            saved = self.store.save_qnb_sync_policy(
                client_id=client_id,
                policy={
                    **policy,
                    "lease_owner": "",
                    "lease_expires_at": "",
                    "last_success_at": str(policy.get("last_success_at") or "") if failed else _iso(current),
                    "consecutive_failure_count": failures,
                    "next_run_at": _iso(current + timedelta(minutes=delay)),
                    "last_run_status": "partial_failed" if failed else "completed",
                },
            )
            return {"client_id": client_id, "sync": sync, "status_reconciliation": status, "policy": saved}
        except Exception as exc:
            failures = int(policy.get("consecutive_failure_count") or 0) + 1
            delay = min(int(policy.get("frequency_minutes") or 60) * (2 ** failures), 1440)
            saved = self.store.save_qnb_sync_policy(
                client_id=client_id,
                policy={
                    **policy,
                    "lease_owner": "",
                    "lease_expires_at": "",
                    "consecutive_failure_count": failures,
                    "next_run_at": _iso(current + timedelta(minutes=delay)),
                    "last_run_status": "failed",
                    "last_error_code": type(exc).__name__,
                },
            )
            return {"client_id": client_id, "error_code": type(exc).__name__, "policy": saved}
