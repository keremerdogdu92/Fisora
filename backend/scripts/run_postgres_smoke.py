from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.postgres_workflow_store import PostgresWorkflowStore
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents


def main() -> int:
    dsn = os.environ.get("FISORA_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
    if not dsn:
        print("DATABASE_URL or FISORA_DATABASE_URL is required.", file=sys.stderr)
        return 2

    store = PostgresWorkflowStore(dsn, tenant_key=os.environ.get("FISORA_TENANT_KEY", "smoke"))
    client_id = os.environ.get("FISORA_SMOKE_CLIENT_ID", "smoke-client")
    with tempfile.TemporaryDirectory() as temp_dir:
        statement_path = Path(temp_dir) / "smoke-bank.csv"
        statement_path.write_text(
            "transaction_date,description,amount,direction,balance_after\n"
            "2026-06-01,GIB ODEME,100.00,out,900.00\n",
            encoding="utf-8",
        )
        store.upsert_client(
            client_id=client_id,
            profile={
                "client_id": client_id,
                "title": "Smoke Mukellef",
                "tax_id": "1111111111",
                "activity_description": "genel isletme",
                "workplace_addresses": ["Istanbul"],
                "has_chart_accounts": True,
            },
            onboarding={"is_ready": True, "missing_fields": []},
        )
        store.replace_chart_accounts(
            client_id=client_id,
            accounts=[
                {"raw_account_code": "102.01", "normalized_account_code": "102.01", "account_name": "Banka", "is_detail_account": True},
                {"raw_account_code": "360", "normalized_account_code": "360", "account_name": "Vergi Borclari", "is_detail_account": True},
            ],
        )
        uploaded = store.save_uploaded_document(
            client_id=client_id,
            document={
                "document_id": "smoke-bank-doc",
                "document_ref": "smoke-bank-doc",
                "document_type": "bank_statement",
                "original_file_name": "smoke-bank.csv",
                "storage_path": str(statement_path),
                "status": "stored",
                "storage_status": "stored",
            },
        )
        store.create_processing_job(
            client_id=client_id,
            document_ref=uploaded["document_ref"],
            document_type="bank_statement",
            parser_kind=parser_kind_for_document_type("bank_statement"),
        )
        summary = process_queued_documents(store, max_jobs=1)
        workspace = store.get_workspace(client_id)

    documents = workspace.get("documents", [])
    jobs = workspace.get("processing_jobs", [])
    if summary["completed_count"] != 1 or not documents or jobs[-1]["status"] != "completed":
        print({"summary": summary, "document_count": len(documents), "job_count": len(jobs)}, file=sys.stderr)
        return 1
    print(
        {
            "status": "ok",
            "client_id": client_id,
            "completed_jobs": summary["completed_count"],
            "document_export_status": documents[-1]["export_status"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
