from __future__ import annotations

from typing import Any


PARSER_BY_DOCUMENT_TYPE = {
    "invoice": "text_pdf_invoice",
    "einvoice_xml": "einvoice_xml",
    "bank_statement": "bank_statement",
    "pos_statement": "pos_statement",
}


def parser_kind_for_document_type(document_type: str) -> str:
    return PARSER_BY_DOCUMENT_TYPE.get(document_type, "manual_review")


def build_initial_processing_result(document: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    file_name = str(document.get("original_file_name") or document.get("document_ref") or job.get("document_ref") or "")
    document_type = str(document.get("document_type") or job.get("document_type") or "invoice")
    parser_kind = str(job.get("parser_kind") or parser_kind_for_document_type(document_type))
    review_code = "parser_output_required"
    if document_type in {"bank_statement", "pos_statement"}:
        review_code = "statement_parser_required"
    return {
        "chart_file_name": "workspace-store",
        "file_name": file_name,
        "provider_hint": "",
        "invoice_type": document_type,
        "issue_date": "",
        "payable_total": "0.00",
        "vat_rates": [],
        "simulated_status": "review_required",
        "status": "review_required",
        "draft_quality": "partial_review_required",
        "is_balanced": False,
        "risk_flags": [review_code],
        "parse_notes": [f"{parser_kind} parser secildi; gercek parse ciktisi bekleniyor."],
        "review_reason_codes": [review_code],
        "product_line_hint": "",
        "product_category": "",
        "product_confidence": 0,
        "business_relevance_status": "supheli",
        "business_relevance_confidence": 0,
        "business_relevance_reason": "Belge yuklendi ancak parse sonucu henuz muhasebe taslagina donusmedi.",
        "business_relevance_evidence": [],
        "ai_classification_used": False,
        "ai_classification_provider": "",
        "ai_classification_skipped_reason": "worker_initial_parse_placeholder",
        "ai_classification_reason": "",
        "ai_estimated_input_chars": 0,
        "learning_rule_applied": False,
        "learning_rule_scope": "",
        "learning_rule_reason": "",
        "export_status": "review_required",
        "selected_expense_account": "",
        "selected_vat_account": "",
        "selected_supplier_account": "",
        "counterparty_match_code": "",
        "counterparty_match_confidence": 0,
        "counterparty_match_reason": "not_found",
        "draft_lines": [],
    }


def process_next_job_once(store: Any) -> dict[str, Any]:
    job = store.claim_next_processing_job()
    if job is None:
        return {"processed_count": 0, "completed_count": 0, "failed_count": 0}
    try:
        workspace = store.get_workspace(str(job["client_id"]))
        document = next(
            (
                item
                for item in workspace.get("uploaded_documents", [])
                if str(item.get("document_ref")) == str(job.get("document_ref"))
                or str(item.get("document_id")) == str(job.get("document_ref"))
            ),
            None,
        )
        if document is None:
            raise ValueError(f"uploaded document not found: {job.get('document_ref')}")
        result = build_initial_processing_result(document, job)
        store.save_simulation_result(
            client_id=str(job["client_id"]),
            document_ref=str(job["document_ref"]),
            result=result,
        )
        store.update_processing_job(job_id=str(job["id"]), status="completed")
        return {"processed_count": 1, "completed_count": 1, "failed_count": 0}
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        store.update_processing_job(job_id=str(job.get("id") or ""), status="failed", error_message=str(exc))
        return {"processed_count": 1, "completed_count": 0, "failed_count": 1}


def process_queued_documents(store: Any, *, max_jobs: int = 10) -> dict[str, Any]:
    summary = {"processed_count": 0, "completed_count": 0, "failed_count": 0}
    for _ in range(max_jobs):
        result = process_next_job_once(store)
        if result["processed_count"] == 0:
            break
        for key in summary:
            summary[key] += int(result[key])
    return summary
