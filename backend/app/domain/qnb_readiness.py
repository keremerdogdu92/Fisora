from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping


def _enabled(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _fresh(value: object, *, now: datetime, hours: int) -> bool:
    parsed = _parse_timestamp(value)
    return bool(parsed and now - parsed <= timedelta(hours=hours))


def qnb_readiness_payload(
    *,
    store: Any,
    env: Mapping[str, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    clients = list(store.list_clients()) if hasattr(store, "list_clients") else []
    client_ids = [
        str(client.get("client_id") or "")
        for client in clients
        if str(client.get("client_id") or "")
    ]
    evidence: dict[str, Any] = {
        "active_connection_clients": [],
        "recent_sync_clients": [],
        "canonical_success_clients": [],
        "duplicate_proof_clients": [],
        "cursor_proof_clients": [],
        "status_proof_clients": [],
        "scheduler_success_clients": [],
        "operation_events": [],
    }
    operation_event_types: set[str] = set()
    for client_id in client_ids:
        connection = store.get_qnb_connection(client_id=client_id)
        if connection and connection.get("status") == "active":
            evidence["active_connection_clients"].append(client_id)
        runs = (
            store.list_qnb_sync_runs(client_id=client_id, limit=50)
            if hasattr(store, "list_qnb_sync_runs")
            else []
        )
        recent_runs = [
            run
            for run in runs
            if _fresh(
                run.get("updated_at") or run.get("completed_at") or run.get("created_at"),
                now=current,
                hours=24,
            )
        ]
        if any(
            run.get("status") in {"completed", "partial_completed"}
            and int(run.get("downloaded_count") or 0) > 0
            for run in recent_runs
        ):
            evidence["recent_sync_clients"].append(client_id)
        if any(int(run.get("skipped_duplicate_count") or 0) > 0 for run in recent_runs):
            evidence["duplicate_proof_clients"].append(client_id)
        if any(
            str(run.get("cursor_after") or "")
            and str(run.get("cursor_after") or "") != str(run.get("cursor_before") or "")
            for run in recent_runs
        ):
            evidence["cursor_proof_clients"].append(client_id)

        workspace = store.get_workspace(client_id)
        qnb_refs = {
            str(document.get("document_ref") or "")
            for document in workspace.get("uploaded_documents", [])
            if (
                str(document.get("source_provider") or "") == "qnb_esolutions"
                or any(
                    isinstance(source, dict)
                    and str(source.get("source_channel") or "")
                    == "qnb_esolutions"
                    for source in document.get("document_sources", [])
                )
            )
        }
        processed_refs = {
            str(document.get("document_ref") or document.get("id") or "")
            for document in workspace.get("documents", [])
            if isinstance(document.get("result"), dict)
        }
        if qnb_refs & processed_refs:
            evidence["canonical_success_clients"].append(client_id)
        if workspace.get("qnb_incoming_status_snapshots"):
            evidence["status_proof_clients"].append(client_id)
        policy = (
            store.get_qnb_sync_policy(client_id=client_id)
            if hasattr(store, "get_qnb_sync_policy")
            else None
        )
        if (
            policy
            and policy.get("last_run_status") == "completed"
            and not policy.get("lease_owner")
            and _fresh(policy.get("last_success_at"), now=current, hours=24)
        ):
            evidence["scheduler_success_clients"].append(client_id)
        events = (
            store.list_operation_events(client_id=client_id, limit=200)
            if hasattr(store, "list_operation_events")
            else []
        )
        for event in events:
            event_type = str(event.get("event_type") or "")
            if event_type and _fresh(
                event.get("created_at") or event.get("recorded_at"),
                now=current,
                hours=24 * 30,
            ):
                operation_event_types.add(event_type)
    evidence["operation_events"] = sorted(operation_event_types)

    incoming_checks = {
        "soap_adapter": str(env.get("FISORA_QNB_ADAPTER") or "").lower() == "soap",
        "credential_key": bool(str(env.get("FISORA_QNB_CREDENTIAL_KEY") or "").strip()),
        "erp_code": bool(str(env.get("FISORA_QNB_ERP_CODE") or "").strip()),
        "active_connection": bool(evidence["active_connection_clients"]),
        "recent_successful_sync": bool(evidence["recent_sync_clients"]),
        "canonical_success": bool(evidence["canonical_success_clients"]),
        "duplicate_proof": bool(evidence["duplicate_proof_clients"]),
        "cursor_proof": bool(evidence["cursor_proof_clients"]),
        "status_proof": bool(evidence["status_proof_clients"]),
    }
    incoming_blocking = [
        key for key, passed in incoming_checks.items() if not passed
    ]
    incoming = {
        "ready": not incoming_blocking,
        "blocking": incoming_blocking,
        "checks": incoming_checks,
    }

    pilot_checks = {
        "incoming_ready": incoming["ready"],
        "scheduler_enabled": _enabled(
            env.get("FISORA_QNB_SCHEDULER_ENABLED")
        ),
        "scheduler_recent_success": bool(
            evidence["scheduler_success_clients"]
        ),
        "explicit_real_data_enable": _enabled(
            env.get("FISORA_REAL_DATA_PILOT_ENABLED")
        ),
        "restricted_live_access": str(
            env.get("FISORA_REAL_DATA_ACCESS_MODE") or ""
        ).lower()
        in {"tls", "restricted_network", "vpn", "ip_allowlist"},
        "tls_auth_probe": "qnb_tls_auth_probe_succeeded"
        in operation_event_types,
        "fresh_restore_receipt": "backup_restore_verified"
        in operation_event_types,
        "operation_owner": bool(
            str(env.get("FISORA_QNB_OPERATION_OWNER") or "").strip()
        ),
    }
    pilot_blocking = [key for key, passed in pilot_checks.items() if not passed]
    pilot = {
        "ready": not pilot_blocking,
        "blocking": pilot_blocking,
        "checks": pilot_checks,
    }

    production_checks = {
        "pilot_ready": pilot["ready"],
        "multi_tenant_isolation": "qnb_multi_tenant_isolation_verified"
        in operation_event_types,
        "secret_rotation": "qnb_secret_rotation_verified"
        in operation_event_types,
        "rollback_drill": "qnb_rollback_drill_verified"
        in operation_event_types,
        "alarms": "qnb_alarm_delivery_verified" in operation_event_types,
        "provider_outage": "qnb_provider_outage_verified"
        in operation_event_types,
    }
    production_blocking = [
        key for key, passed in production_checks.items() if not passed
    ]
    production = {
        "ready": not production_blocking,
        "blocking": production_blocking,
        "checks": production_checks,
    }
    return {
        "incoming": incoming,
        "pilot": pilot,
        "production": production,
        "evidence": evidence,
        "evaluated_at": current.isoformat(timespec="seconds"),
    }
