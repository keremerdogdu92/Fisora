import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.workflows.document_processing import (
    parser_kind_for_document_type,
    process_queued_documents,
    build_ai_runtime_from_env
)
from app.domain.research_harness import build_research_runtime_from_env
from app.persistence.workflow_store import JsonWorkflowStore
from app.domain.matching_simulation import parse_chart_accounts

def load_env():
    env_path = ROOT / "deploy" / "production.env"
    if not env_path.exists():
        print("production.env not found!")
        return
    with open(env_path, "r", encoding="utf-16") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip()
                if key.startswith("\ufeff"):
                    key = key.replace("\ufeff", "")
                key = "".join(c for c in key if ord(c) < 128)
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                os.environ[key] = val
                print(f"Loaded: {key} (len={len(val)})")

def run_real_pipeline():
    load_env()
    firm_id = "firma-1"
    firm_dir = ROOT / "private_samples" / "real_pilot" / firm_id
    invoice_dir = firm_dir / "invoices"
    chart_files = sorted(path for path in (firm_dir / "chart_accounts").glob("*") if path.is_file())
    if not chart_files:
        print("Chart accounts not found!")
        return
    chart_path = chart_files[0]
    
    accounts = parse_chart_accounts(chart_path)
    accounts_payload = [
        {
            "code": acc.normalized_account_code,
            "name": acc.account_name,
            "is_detail_account": acc.is_detail_account,
            "is_active": True
        }
        for acc in accounts
    ]
    
    temp_dir = Path(tempfile.mkdtemp())
    print(f"Using temp directory for store: {temp_dir}")
    try:
        store = JsonWorkflowStore(temp_dir / "store.json")
        
        store.upsert_client(
            client_id=firm_id,
            profile={
                "client_id": firm_id,
                "title": "Omer Yagci",
                "tax_id": "45661316282",
                "activity_description": "Isitme cihazi satis ve servis",
                "workplace_addresses": ["Istanbul"],
                "has_chart_accounts": True,
            },
            onboarding={"is_ready": True, "missing_fields": []}
        )
        store.replace_chart_accounts(client_id=firm_id, accounts=accounts_payload)
        
        invoice_paths = sorted(invoice_dir.rglob("*.pdf"))
        print(f"Found {len(invoice_paths)} invoices.")
        
        for path in invoice_paths:
            temp_invoice_path = temp_dir / path.name
            shutil.copy(path, temp_invoice_path)
            
            doc_id = path.stem
            store.save_uploaded_document(
                client_id=firm_id,
                document={
                    "document_id": doc_id,
                    "document_ref": doc_id,
                    "document_type": "invoice",
                    "original_file_name": path.name,
                    "storage_path": str(temp_invoice_path),
                    "status": "stored",
                }
            )
            store.create_processing_job(
                client_id=firm_id,
                document_ref=doc_id,
                document_type="invoice",
                parser_kind=parser_kind_for_document_type("invoice"),
            )
        
        ai_runtime = build_ai_runtime_from_env(os.environ)
        research_runtime = build_research_runtime_from_env(os.environ)
        
        print("Starting real queue processing with Tavily + Groq/Cerebras...")
        summary = process_queued_documents(
            store,
            max_jobs=25,
            product_classifier=ai_runtime.get("product_classifier"),
            research_runtime=research_runtime,
        )
        print("Queue processing finished.")
        print(f"Summary: {summary}")
        
        workspace = store.get_workspace(firm_id)
        events = workspace.get("document_pipeline_events", [])
        
        print("\n=== RESULTS FOR ALL INVOICES ===")
        for doc in workspace.get("documents", []):
            ref = doc.get("document_ref")
            print(f"\n==========================================")
            print(f"File Reference: {ref}")
            
            doc_events = [e for e in events if e.get("document_ref") == ref]
            print("Pipeline Events Steps:")
            for e in doc_events:
                 print(f"  [{e.get('step')}] status={e.get('status')} - Msg: {e.get('message_tr')}")
            
            res = doc.get("result") or {}
            print(f"Product Category: {res.get('product_category')} | Confidence: {res.get('product_confidence')}")
            print(f"AI Suggested Account: {res.get('ai_suggested_account_code')}")
            print(f"AI Attempted Account: {res.get('ai_attempted_account_code')}")
            print(f"Accepted Account Code: {res.get('accepted_account_code')}")
            print(f"Research Requested: {res.get('ai_research_requested', False)}")
            print(f"Research Query: {res.get('ai_research_query')}")
            
            research_profile = res.get("research_profile") or {}
            print(f"Research Confidence: {research_profile.get('confidence')}")
            print(f"Research Summary: {research_profile.get('brand_summary')}")
            evidence = research_profile.get("research_evidence") or []
            print(f"Research Evidence Count: {len(evidence)}")
            for ev in evidence:
                 print(f"  - Source: {ev.get('url')} | Summary: {ev.get('summary_tr')}")
            
            print(f"Decision Narrative:")
            dn = res.get("decision_narrative")
            if isinstance(dn, dict):
                 print(json.dumps(dn, indent=2, ensure_ascii=False))
            else:
                 print(dn)
                
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    run_real_pipeline()
