from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from app.domain.journal_entries import JournalEntry, build_purchase_entry, money
from app.domain.pdf_invoices import ParsedInvoice


EXPENSE_ACCOUNT_BY_PROVIDER = {
    "Aposkal": "770.02",
    "Kolay Soft": "770.01",
    "QNB eFinans": "770.01",
}
DEFAULT_SUPPLIER_ACCOUNT = "320.01.001"


@dataclass(frozen=True)
class ReviewTaskDraft:
    file_name: str
    provider_hint: str
    issue_date: str
    payable_total: str
    reason_codes: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class InvoiceOperationRun:
    journal_entries: tuple[JournalEntry, ...]
    review_tasks: tuple[ReviewTaskDraft, ...]


def vat_rate_decimal(invoice: ParsedInvoice) -> Decimal:
    if not invoice.vat_rates:
        return Decimal("0.00")
    if len(invoice.vat_rates) > 1:
        raise ValueError("Mixed VAT invoices must go to review queue.")
    return Decimal(invoice.vat_rates[0]) / Decimal("100")


def review_task_from_invoice(invoice: ParsedInvoice) -> ReviewTaskDraft:
    reasons = list(invoice.risk_flags)
    reasons.extend(invoice.parse_notes)
    if invoice.suggested_route != "journal_candidate" and not reasons:
        reasons.append("manual_review_required")
    return ReviewTaskDraft(
        file_name=invoice.file_name,
        provider_hint=invoice.provider_hint,
        issue_date=invoice.issue_date,
        payable_total=invoice.payable_total,
        reason_codes=tuple(dict.fromkeys(reasons)),
        note="Kontrol kuyruğunda muhasebe personeli incelemesi gerekir.",
    )


def journal_entry_from_invoice(invoice: ParsedInvoice) -> JournalEntry:
    expense_account = EXPENSE_ACCOUNT_BY_PROVIDER.get(invoice.provider_hint, "770.01")
    return build_purchase_entry(
        entry_date=invoice.issue_date,
        total=money(invoice.payable_total),
        vat_rate=vat_rate_decimal(invoice),
        expense_account=expense_account,
        supplier_account=DEFAULT_SUPPLIER_ACCOUNT,
        document_ref=invoice.invoice_no or invoice.file_name,
    )


def run_invoice_operations(invoices: list[ParsedInvoice]) -> InvoiceOperationRun:
    journal_entries: list[JournalEntry] = []
    review_tasks: list[ReviewTaskDraft] = []
    for invoice in invoices:
        if invoice.suggested_route == "journal_candidate":
            journal_entries.append(journal_entry_from_invoice(invoice))
        else:
            review_tasks.append(review_task_from_invoice(invoice))
    return InvoiceOperationRun(tuple(journal_entries), tuple(review_tasks))


def write_journal_drafts_csv(entries: tuple[JournalEntry, ...], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "entry_no",
        "entry_type",
        "entry_date",
        "description",
        "total_debit",
        "total_credit",
        "is_balanced",
        "line_no",
        "account_code",
        "line_description",
        "debit",
        "credit",
        "document_ref",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for entry_no, entry in enumerate(entries, start=1):
            for line_no, line in enumerate(entry.lines, start=1):
                writer.writerow(
                    {
                        "entry_no": entry_no,
                        "entry_type": entry.entry_type,
                        "entry_date": entry.entry_date,
                        "description": entry.description,
                        "total_debit": f"{entry.total_debit:.2f}",
                        "total_credit": f"{entry.total_credit:.2f}",
                        "is_balanced": str(entry.is_balanced).lower(),
                        "line_no": line_no,
                        "account_code": line.account_code,
                        "line_description": line.description,
                        "debit": f"{line.debit:.2f}",
                        "credit": f"{line.credit:.2f}",
                        "document_ref": line.document_ref or "",
                    }
                )
    return output_path


def write_review_tasks_csv(tasks: tuple[ReviewTaskDraft, ...], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["file_name", "provider_hint", "issue_date", "payable_total", "reason_codes", "note"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for task in tasks:
            row = asdict(task)
            row["reason_codes"] = ";".join(task.reason_codes)
            writer.writerow(row)
    return output_path


def write_operation_summary_json(run: InvoiceOperationRun, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "journal_entry_count": len(run.journal_entries),
        "review_task_count": len(run.review_tasks),
        "journal_entries_balanced": all(entry.is_balanced for entry in run.journal_entries),
        "review_reason_counts": {},
    }
    reason_counts: dict[str, int] = {}
    for task in run.review_tasks:
        for reason in task.reason_codes:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    payload["review_reason_counts"] = reason_counts
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path

