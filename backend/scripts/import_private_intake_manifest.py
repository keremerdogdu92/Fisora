from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.chart_accounts import parse_chart_accounts  # noqa: E402
from app.domain.document_uploads import store_document_content  # noqa: E402
from app.domain.operation_monitoring import build_operation_event, operation_event_payload  # noqa: E402
from app.persistence.store_factory import build_workflow_store  # noqa: E402
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents  # noqa: E402


DEFAULT_MANIFEST_PATH = ROOT / "private_samples" / "intake_manifest.json"
DEFAULT_DOCUMENT_STORAGE_PATH = ROOT / "exports" / "documents"
DEFAULT_OUTPUT_PATH = ROOT / "private_samples" / "intake_import_summary.json"
PROCESSABLE_DOCUMENT_KINDS = {"invoice", "bank_statement", "pos_statement"}


def _document_type(row: dict[str, Any]) -> str:
    kind = str(row.get("document_kind") or "")
    extension = str(row.get("extension") or "").lower()
    if kind == "bank_statement":
        return "bank_statement"
    if kind == "pos_statement":
        return "pos_statement"
    if kind == "invoice" and extension == ".xml":
        return "einvoice_xml"
    return "invoice"


def _invoice_intake_category(row: dict[str, Any], *, document_type: str) -> str:
    if document_type not in {"invoice", "einvoice_xml"}:
        return str(row.get("intake_category") or "")

    direction = str(row.get("intake_category") or "").strip()
    if direction not in {"purchase_invoice", "sales_invoice"}:
        raise ValueError(
            "invoice manifest row requires purchase_invoice or sales_invoice: "
            f"{row.get('relative_path')}"
        )
    return direction


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("files"), list):
        raise ValueError("manifest JSON must contain a files list")
    return payload


def _source_path(source_dir: Path, row: dict[str, Any]) -> Path:
    relative_path = str(row.get("relative_path") or "").strip()
    if not relative_path:
        raise ValueError("manifest row is missing relative_path")
    path = (source_dir / relative_path).resolve()
    source_root = source_dir.resolve()
    if source_root not in path.parents and path != source_root:
        raise ValueError(f"manifest path escapes source_dir: {relative_path}")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"manifest source file not found: {path}")
    return path


def _client_profile(*, client_id: str, client_name: str, tax_id: str, activity: str) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "title": client_name or client_id,
        "tax_id": tax_id,
        "activity_description": activity,
        "nace_code": "",
        "workplace_addresses": [],
        "has_chart_accounts": False,
    }


def _onboarding(profile: dict[str, Any], *, has_chart_accounts: bool) -> dict[str, Any]:
    missing = []
    for key in ("client_id", "title", "tax_id", "activity_description"):
        if not str(profile.get(key) or "").strip():
            missing.append(key)
    if not has_chart_accounts:
        missing.append("chart_accounts")
    return {"is_ready": not missing, "missing_fields": missing}


def _record_event(store: Any, *, client_id: str, event_type: str, status: str, message: str, metadata: dict[str, Any]) -> None:
    if not hasattr(store, "record_operation_event"):
        return
    event = operation_event_payload(
        build_operation_event(
            client_id=client_id,
            event_type=event_type,
            status=status,
            message=message,
            metadata=metadata,
        )
    )
    store.record_operation_event(client_id=client_id, event=event)


def import_manifest(
    *,
    manifest_path: Path,
    source_dir: Path | None,
    document_storage_path: Path,
    output_path: Path,
    client_id: str,
    client_name: str,
    tax_id: str = "",
    activity: str = "",
    uploaded_by: str = "private-intake",
    retention_days: int = 90,
    run_worker: bool = False,
    store_backend: str | None = None,
    json_store_path: Path | None = None,
    postgres_dsn: str = "",
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    resolved_source_dir = (source_dir or Path(str(manifest.get("source_dir") or ""))).resolve()
    if not resolved_source_dir.exists() or not resolved_source_dir.is_dir():
        raise ValueError("source_dir is required and must exist")

    store = build_workflow_store(
        store_backend=store_backend,
        json_path=json_store_path or ROOT / "exports" / "phase0_store.json",
        postgres_dsn=postgres_dsn,
    )
    profile = _client_profile(client_id=client_id, client_name=client_name, tax_id=tax_id, activity=activity)
    imported_documents = []
    skipped_rows = []
    chart_account_count = 0

    for row in manifest["files"]:
        kind = str(row.get("document_kind") or "")
        path = _source_path(resolved_source_dir, row)
        if kind == "chart_accounts":
            accounts = parse_chart_accounts(path)
            chart_account_count = len(accounts)
            profile["has_chart_accounts"] = chart_account_count > 0
            store.replace_chart_accounts(
                client_id=client_id,
                accounts=[asdict(account) for account in accounts],
            )
            continue
        if kind not in PROCESSABLE_DOCUMENT_KINDS:
            skipped_rows.append(
                {
                    "relative_path": row.get("relative_path"),
                    "document_kind": kind,
                    "reason": "not_a_processing_document",
                }
            )
            continue
        content = path.read_bytes()
        document_type = _document_type(row)
        intake_category = _invoice_intake_category(row, document_type=document_type)
        stored = store_document_content(
            base_dir=document_storage_path,
            client_id=client_id,
            file_name=str(row.get("file_name") or path.name),
            document_type=document_type,
            intake_category=intake_category,
            uploaded_by=uploaded_by,
            content=content,
            retention_days=retention_days,
        )
        saved = store.save_uploaded_document(client_id=client_id, document=asdict(stored))
        job = store.create_processing_job(
            client_id=client_id,
            document_ref=str(saved["document_ref"]),
            document_type=document_type,
            parser_kind=parser_kind_for_document_type(document_type),
            intake_category=intake_category,
        )
        imported_documents.append(
            {
                "relative_path": row.get("relative_path"),
                "document_ref": saved["document_ref"],
                "document_type": document_type,
                "intake_category": intake_category,
                "processing_job_id": job["id"],
            }
        )

    store.upsert_client(
        client_id=client_id,
        profile=profile,
        onboarding=_onboarding(profile, has_chart_accounts=chart_account_count > 0),
    )
    worker_summary = process_queued_documents(store) if run_worker else {}
    summary = {
        "client_id": client_id,
        "client_name": client_name,
        "manifest_path": str(manifest_path),
        "source_dir": str(resolved_source_dir),
        "chart_account_count": chart_account_count,
        "imported_document_count": len(imported_documents),
        "skipped_row_count": len(skipped_rows),
        "run_worker": run_worker,
        "worker_summary": worker_summary,
        "imported_documents": imported_documents,
        "skipped_rows": skipped_rows,
    }
    _record_event(
        store,
        client_id=client_id,
        event_type="private_intake_imported",
        status="ok" if imported_documents or chart_account_count else "warning",
        message="Private intake manifest store'a aktarildi.",
        metadata={
            "chart_account_count": chart_account_count,
            "imported_document_count": len(imported_documents),
            "skipped_row_count": len(skipped_rows),
            "run_worker": run_worker,
        },
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a private intake manifest into the local Fisora workflow store.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Path to intake_manifest.json.")
    parser.add_argument("--source-dir", default="", help="Override source_dir from the manifest.")
    parser.add_argument("--client-id", required=True, help="Fisora client id.")
    parser.add_argument("--client-name", default="", help="Human readable client name.")
    parser.add_argument("--tax-id", default="", help="Optional VKN/TCKN for onboarding readiness.")
    parser.add_argument("--activity", default="", help="Optional activity/NACE description.")
    parser.add_argument("--uploaded-by", default="private-intake", help="Uploader label stored on imported documents.")
    parser.add_argument("--retention-days", type=int, default=90, help="Raw document retention days.")
    parser.add_argument("--document-storage-path", default=str(DEFAULT_DOCUMENT_STORAGE_PATH), help="Local document storage path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Ignored summary JSON output path.")
    parser.add_argument("--store-backend", default="", choices=("", "json", "postgres"), help="Override FISORA_STORE_BACKEND.")
    parser.add_argument("--json-store-path", default="", help="Optional JSON store path for local/private dry runs.")
    parser.add_argument("--postgres-dsn", default="", help="Optional PostgreSQL DSN for postgres store backend.")
    parser.add_argument("--run-worker", action="store_true", help="Process queued documents after import.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = import_manifest(
            manifest_path=Path(args.manifest),
            source_dir=Path(args.source_dir) if args.source_dir else None,
            document_storage_path=Path(args.document_storage_path),
            output_path=Path(args.output),
            client_id=args.client_id,
            client_name=args.client_name or args.client_id,
            tax_id=args.tax_id,
            activity=args.activity,
            uploaded_by=args.uploaded_by,
            retention_days=args.retention_days,
            run_worker=args.run_worker,
            store_backend=args.store_backend or None,
            json_store_path=Path(args.json_store_path) if args.json_store_path else None,
            postgres_dsn=args.postgres_dsn,
        )
    except Exception as exc:
        print(f"private intake import failed: {exc}", file=sys.stderr)
        return 1
    print(
        {
            "client_id": summary["client_id"],
            "chart_account_count": summary["chart_account_count"],
            "imported_document_count": summary["imported_document_count"],
            "skipped_row_count": summary["skipped_row_count"],
            "summary_path": str(Path(args.output)),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
