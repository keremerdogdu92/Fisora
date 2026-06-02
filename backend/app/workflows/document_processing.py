from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.domain.ai_classification import StaticFirstClassifier
from app.domain.business_relevance import ClientProfile
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.pdf_invoices import ParsedInvoice, parse_pdf_invoice
from app.domain.statement_journal_entries import build_statement_entries, journal_entry_payload
from app.domain.statement_lines import enrich_statement_lines_with_counterparties, parse_statement_file
from app.domain.xml_invoices import parse_xml_invoice


PARSER_BY_DOCUMENT_TYPE = {
    "invoice": "text_pdf_invoice",
    "einvoice_xml": "einvoice_xml",
    "bank_statement": "bank_statement",
    "pos_statement": "pos_statement",
}


def parser_kind_for_document_type(document_type: str) -> str:
    return PARSER_BY_DOCUMENT_TYPE.get(document_type, "manual_review")


def _chart_account(payload: dict[str, Any]) -> ChartAccount:
    raw_code = str(payload.get("raw_account_code") or payload.get("normalized_account_code") or "")
    normalized = str(payload.get("normalized_account_code") or normalize_account_code(raw_code))
    return ChartAccount(
        raw_account_code=raw_code,
        normalized_account_code=normalized,
        account_name=str(payload.get("account_name") or ""),
        is_detail_account=bool(payload.get("is_detail_account", True)),
        tax_id=str(payload.get("tax_id") or "") or None,
        tax_office=str(payload.get("tax_office") or "") or None,
        iban=str(payload.get("iban") or "") or None,
    )


def _first_detail_account(accounts: list[ChartAccount], prefixes: tuple[str, ...], fallback: str) -> str:
    for account in accounts:
        if account.is_detail_account and account.normalized_account_code.startswith(prefixes):
            return account.normalized_account_code
    return fallback


def _account_selection(workspace: dict[str, Any]) -> AccountSelection:
    chart_accounts = workspace.get("chart_accounts") or {}
    accounts = [_chart_account(account) for account in chart_accounts.get("accounts", [])]
    return AccountSelection(
        chart_file_name="workspace-store",
        expense_account=_first_detail_account(accounts, ("770", "760", "740", "730"), "770.01"),
        purchase_vat_account=_first_detail_account(accounts, ("191",), "191.01"),
        supplier_account=_first_detail_account(accounts, ("320",), "320.01.001"),
        bank_account=_first_detail_account(accounts, ("102",), "102.01"),
        selection_notes=(),
    )


def _client_profile(workspace: dict[str, Any]) -> ClientProfile | None:
    client = workspace.get("client") or {}
    profile = client.get("profile") or {}
    client_id = str(profile.get("client_id") or client.get("client_id") or "").strip()
    if not client_id:
        return None
    chart_accounts = workspace.get("chart_accounts") or {}
    return ClientProfile(
        client_id=client_id,
        title=str(profile.get("title") or ""),
        tax_id=str(profile.get("tax_id") or ""),
        activity_description=str(profile.get("activity_description") or ""),
        nace_code=str(profile.get("nace_code") or ""),
        workplace_addresses=tuple(profile.get("workplace_addresses") or ()),
        has_chart_accounts=bool(profile.get("has_chart_accounts") or chart_accounts.get("account_count")),
    )


def _chart_accounts(workspace: dict[str, Any]) -> list[ChartAccount]:
    chart_accounts = workspace.get("chart_accounts") or {}
    return [_chart_account(account) for account in chart_accounts.get("accounts", [])]


def _serializable_simulation(invoice: ParsedInvoice, workspace: dict[str, Any]) -> dict[str, Any]:
    accounts = _chart_accounts(workspace)
    counterparty = match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint) if accounts else None
    result = simulate_invoice(
        invoice,
        _account_selection(workspace),
        _client_profile(workspace),
        counterparty,
        StaticFirstClassifier(),
    )
    data = asdict(result)
    for key in (
        "vat_rates",
        "risk_flags",
        "parse_notes",
        "review_reason_codes",
        "business_relevance_evidence",
        "draft_lines",
    ):
        data[key] = list(data[key])
    return data


def _stored_path(document: dict[str, Any]) -> Path | None:
    storage_path = str(document.get("storage_path") or "").strip()
    if not storage_path:
        return None
    path = Path(storage_path)
    return path if path.exists() and path.is_file() else None


def _parse_invoice_document(path: Path, document_type: str) -> ParsedInvoice:
    if document_type == "einvoice_xml" or path.suffix.lower() == ".xml":
        return parse_xml_invoice(path)
    return parse_pdf_invoice(path)


def _statement_total(lines: tuple[Any, ...]) -> str:
    total = Decimal("0")
    for line in lines:
        try:
            total += Decimal(line.amount)
        except Exception:
            continue
    return f"{total:.2f}"


def build_statement_processing_result(
    document: dict[str, Any],
    job: dict[str, Any],
    path: Path,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    lines = enrich_statement_lines_with_counterparties(
        parse_statement_file(path),
        _chart_accounts(workspace),
        workspace.get("learning_events") or (),
    )
    selection = _account_selection(workspace)
    entries = build_statement_entries(
        lines=lines,
        bank_account=selection.bank_account,
        document_ref=str(document.get("document_ref") or document.get("document_id") or document.get("original_file_name") or ""),
    )
    risk_flags = tuple(dict.fromkeys(flag for line in lines for flag in line.risk_flags))
    if not lines:
        risk_flags = ("statement_parser_required",)
    review_reason_codes = risk_flags
    is_balanced = bool(entries) and all(entry.is_balanced for entry in entries)
    draft_lines = entries[0].lines if entries else ()
    return {
        "chart_file_name": "workspace-store",
        "file_name": str(document.get("original_file_name") or path.name),
        "provider_hint": "Banka/POS ekstresi",
        "invoice_type": str(document.get("document_type") or job.get("document_type") or "statement"),
        "issue_date": lines[0].transaction_date if lines else "",
        "payable_total": _statement_total(lines),
        "vat_rates": [],
        "simulated_status": "review_required",
        "status": "review_required",
        "draft_quality": "statement_entries_ready" if entries else "statement_parse_pending",
        "is_balanced": is_balanced,
        "risk_flags": list(risk_flags),
        "parse_notes": [f"{len(lines)} statement satiri parse edildi."] if lines else ["statement satiri bulunamadi."],
        "review_reason_codes": list(review_reason_codes),
        "product_line_hint": lines[0].description if lines else "",
        "product_category": lines[0].transaction_type if lines else "",
        "product_confidence": lines[0].confidence if lines else 0,
        "business_relevance_status": "supheli",
        "business_relevance_confidence": lines[0].confidence if lines else 0,
        "business_relevance_reason": "Ekstre satirlari muhasebe taslagi icin musavir kontrolune hazirlandi.",
        "business_relevance_evidence": [f"{line.transaction_type}:{line.suggested_account_code}" for line in lines[:5]],
        "ai_classification_used": False,
        "ai_classification_provider": "static_statement_rules",
        "ai_classification_skipped_reason": "static_statement_rules",
        "ai_classification_reason": "",
        "ai_estimated_input_chars": sum(len(line.description) for line in lines),
        "learning_rule_applied": any(line.counterparty_match_reason == "learning_event" for line in lines),
        "learning_rule_scope": "",
        "learning_rule_reason": "Banka satiri onceki musavir kararina gore cariyle eslesti."
        if any(line.counterparty_match_reason == "learning_event" for line in lines)
        else "",
        "export_status": "export_ready" if is_balanced and not risk_flags else "review_required",
        "selected_expense_account": "",
        "selected_vat_account": "",
        "selected_supplier_account": lines[0].suggested_account_code if lines else "",
        "counterparty_match_code": lines[0].suggested_account_code if lines else "",
        "counterparty_match_confidence": lines[0].confidence if lines else 0,
        "counterparty_match_reason": lines[0].counterparty_match_reason if lines else "not_found",
        "draft_lines": [
            {
                "account_code": line.account_code,
                "description": line.description,
                "debit": f"{line.debit:.2f}",
                "credit": f"{line.credit:.2f}",
            }
            for line in draft_lines
        ],
        "statement_lines": [asdict(line) for line in lines],
        "statement_entries": [journal_entry_payload(entry) for entry in entries],
    }


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


def build_processing_result(document: dict[str, Any], job: dict[str, Any], workspace: dict[str, Any]) -> dict[str, Any]:
    document_type = str(document.get("document_type") or job.get("document_type") or "invoice")
    path = _stored_path(document)
    if path is None:
        return build_initial_processing_result(document, job)
    if document_type in {"bank_statement", "pos_statement"}:
        return build_statement_processing_result(document, job, path, workspace)
    invoice = _parse_invoice_document(path, document_type)
    return _serializable_simulation(invoice, workspace)


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
        result = build_processing_result(document, job, workspace)
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
