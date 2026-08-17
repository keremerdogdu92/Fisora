from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from app.workflows.gemini_invoice_pipeline import GeminiInvoicePipelineResult


def to_document_processing_payload(
    result: GeminiInvoicePipelineResult,
) -> dict[str, object]:
    """Project a V2 result into the existing active document payload."""

    canonical = result.canonical_invoice
    projection = result.projection or {}
    draft = result.draft
    proposal = result.proposal
    if canonical is None:
        warnings = list(result.warnings)
        return {
            "issue_date": "",
            "payable_total": "",
            "vat_rates": [],
            "canonical_line_count": 0,
            "canonical_validation_status": "unavailable",
            "canonical_validation_reasons": warnings,
            "decision_narrative": {"read_facts": {}, "fisora_interpretation": "", "account_code": "", "account_name": ""},
            "accounting_direction": "",
            "selected_expense_account": "",
            "selected_revenue_account": "",
            "selected_vat_account": "",
            "selected_purchase_vat_account": "",
            "selected_sales_vat_account": "",
            "selected_supplier_account": "",
            "selected_customer_account": "",
            "selected_special_tax_accounts": [],
            "counterparty_creation_suggestion": None,
            "suggested_counterparty_creation": None,
            "draft_lines": [],
            "total_debit": "0.00",
            "total_credit": "0.00",
            "is_balanced": False,
            "status": "partial",
            "draft_status": "review_required",
            "processing_status": result.processing_status,
            "extraction_validation_status": result.extraction_validation_status,
            "reconciliation_status": result.reconciliation_status,
            "accounting_decision_status": result.accounting_decision_status,
            "draft_balance_status": result.draft_balance_status,
            "review_status": result.review_status,
            "export_status": result.export_status,
            "canonical_evidence_categories": {
                "factual_contradictions": [],
                "missing_evidence": warnings,
                "derived_reconciled": [],
                "informational_warnings": [],
            },
            "derived_line_to_vat_linkage": {
                "status": "unavailable",
                "links": [],
                "factual_contradictions": [],
                "missing_evidence": warnings,
            },
            "confidence_label": "Musavir onayi gereken kismi taslak",
            "pipeline_warnings": warnings,
            "review_reason_codes": warnings,
            "risk_flags": warnings,
            "accountant_summary": "Belge icin kullanilabilir muhasebe taslagi olusturulamadi.",
            "accountant_explanation_tr": "; ".join(warnings),
        }

    direction = str(projection.get("document_direction") or canonical.header.document_direction)
    is_sales = direction == "sales"
    lines = draft.lines if draft is not None else ()
    first_line = _first_account(lines, "line:")
    first_vat = _first_account(lines, "vat:")
    counterparty = next((line for line in lines if line.fact_ref == "counterparty"), None)
    counterparty_code = counterparty.account_code if counterparty is not None else ""
    special_accounts = list(
        dict.fromkeys(
            line.account_code
            for line in lines
            if line.account_code
            and (line.fact_ref.startswith("tax:") or line.fact_ref.startswith("monetary:"))
        )
    )
    warnings = list(dict.fromkeys(result.warnings))
    counterparty_suggestion = (
        dict(proposal.counterparty.proposal)
        if proposal is not None and proposal.counterparty.action == "propose_new"
        else None
    )
    counterparty_party = canonical.customer_party if is_sales else canonical.supplier_party
    interpretation = (
        "Tum canonical muhasebe olgulari dengeli taslakta temsil edildi."
        if result.status == "complete"
        else "En iyi kullanilabilir taslak korundu; uyari ve cozulmeyen alanlar mustavir incelemesine acik."
    )
    read_facts = {
        "invoice_no": canonical.header.invoice_no,
        "issue_date": canonical.header.issue_date,
        "direction": direction,
        "counterparty_title": counterparty_party.title,
        "counterparty_tax_id": counterparty_party.tax_id,
        "line_count": str(len(canonical.line_items)),
        "payable_total": canonical.totals.payable_total,
        "vat_total": canonical.totals.vat_total,
        "special_tax_total": canonical.totals.special_tax_total,
    }
    decision_narrative = {
        "read_facts": read_facts,
        "invoice_product_line": canonical.line_items[0].description if canonical.line_items else "",
        "fisora_interpretation": interpretation,
        "business_relation": f"{direction}: {counterparty_party.title}",
        "account_code": first_line.account_code if first_line is not None else "",
        "account_name": first_line.account_name if first_line is not None else "",
        "counterparty_match": counterparty_code or str((counterparty_suggestion or {}).get("party_title") or ""),
        "confidence_label": "Musavir onayi gereken AI taslagi",
        "unresolved_info": "; ".join(warnings),
    }
    draft_lines = [
        {
            "fact_ref": line.fact_ref,
            "proposal_role": line.fact_ref.split(":", 1)[0],
            "account_code": line.account_code,
            "account_name": line.account_name,
            "description": _description_for(line.fact_ref, projection, counterparty_party.title),
            "debit": _money(line.debit),
            "credit": _money(line.credit),
            "amount": _money(line.amount),
            "side": line.side,
            "selected_candidate_id": line.selected_candidate_id,
            "resolution": line.resolution,
            "representation": line.representation,
            "warnings": list(line.warnings),
        }
        for line in lines
    ]
    return {
        "invoice_no": canonical.header.invoice_no,
        "issue_date": canonical.header.issue_date,
        "invoice_date": canonical.header.issue_date,
        "currency_code": canonical.header.currency_code,
        "invoice_type": canonical.header.invoice_type,
        "accounting_direction": direction,
        "supplier_title": canonical.supplier_party.title,
        "supplier_tax_id": canonical.supplier_party.tax_id,
        "customer_title": canonical.customer_party.title,
        "customer_tax_id": canonical.customer_party.tax_id,
        "counterparty_title": counterparty_party.title,
        "counterparty_tax_id": counterparty_party.tax_id,
        "goods_services_total": canonical.totals.goods_services_total,
        "vat_total": canonical.totals.vat_total,
        "special_tax_total": canonical.totals.special_tax_total,
        "tax_inclusive_total": canonical.totals.tax_inclusive_total,
        "payable_total": canonical.totals.payable_total,
        "vat_rates": [item.rate for item in canonical.vat_summary],
        "canonical_line_count": len(canonical.line_items),
        "canonical_validation_status": canonical.validation.status,
        "canonical_validation_reasons": list(canonical.validation.reason_codes),
        "canonical_extraction_ai_used": True,
        "decision_narrative": decision_narrative,
        "selected_expense_account": "" if is_sales or first_line is None else first_line.account_code,
        "selected_revenue_account": first_line.account_code if is_sales and first_line is not None else "",
        "selected_vat_account": first_vat.account_code if first_vat is not None else "",
        "selected_purchase_vat_account": "" if is_sales or first_vat is None else first_vat.account_code,
        "selected_sales_vat_account": first_vat.account_code if is_sales and first_vat is not None else "",
        "selected_supplier_account": "" if is_sales else counterparty_code,
        "selected_customer_account": counterparty_code if is_sales else "",
        "counterparty_match_code": counterparty_code,
        "selected_special_tax_accounts": special_accounts,
        "counterparty_creation_suggestion": counterparty_suggestion,
        "suggested_counterparty_creation": counterparty_suggestion,
        "draft_lines": draft_lines,
        "total_debit": _money(draft.total_debit if draft is not None else Decimal("0")),
        "total_credit": _money(draft.total_credit if draft is not None else Decimal("0")),
        "is_balanced": bool(draft and draft.is_balanced),
        "status": result.status,
        "draft_status": "review_required",
        "processing_status": result.processing_status,
        "extraction_validation_status": result.extraction_validation_status,
        "reconciliation_status": result.reconciliation_status,
        "accounting_decision_status": result.accounting_decision_status,
        "draft_balance_status": result.draft_balance_status,
        "review_status": result.review_status,
        "export_status": result.export_status,
        "canonical_evidence_categories": dict(
            projection.get("canonical_evidence_categories") or {}
        ),
        "derived_line_to_vat_linkage": dict(
            projection.get("derived_line_to_vat_linkage") or {}
        ),
        "confidence_label": "Musavir onayi gereken AI taslagi",
        "pipeline_warnings": warnings,
        "review_reason_codes": warnings,
        "risk_flags": warnings,
        "accountant_summary": interpretation,
        "accountant_explanation_tr": interpretation,
    }


def _first_account(lines: Sequence[object], prefix: str):
    return next(
        (
            line
            for line in lines
            if getattr(line, "fact_ref", "").startswith(prefix)
            and getattr(line, "account_code", "")
        ),
        None,
    )


def _description_for(
    fact_ref: str,
    projection: Mapping[str, object],
    counterparty_title: str,
) -> str:
    if fact_ref == "counterparty":
        return counterparty_title
    for section in ("line_items", "vat_summary", "tax_components", "monetary_components"):
        values = projection.get(section)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        for value in values:
            if not isinstance(value, Mapping):
                continue
            identity = str(value.get("identity_ref") or value.get("decision_ref") or "")
            if identity == fact_ref:
                return str(value.get("description") or value.get("source_label") or identity)
    return fact_ref


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))
