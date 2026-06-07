from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import re
import unicodedata

from app.domain.journal_entries import JournalEntry, JournalLine, money
from app.domain.statement_lines import StatementLine


def _amount(value: str) -> Decimal:
    try:
        return money(value)
    except (InvalidOperation, ValueError):
        return money("0.00")


def _account_for_line(line: StatementLine) -> str:
    if line.suggested_account_code:
        return line.suggested_account_code
    if line.transaction_type == "tax_payment":
        return "360"
    if line.transaction_type == "sgk_payment":
        return "361"
    if line.transaction_type.startswith("pos"):
        return "108"
    return "320"


def build_statement_entry(
    *,
    line: StatementLine,
    bank_account: str = "102.01",
    document_ref: str | None = None,
) -> JournalEntry:
    amount = _amount(line.amount)
    account_code = _account_for_line(line)
    entry_date = line.transaction_date or "1900-01-01"
    description = f"{line.description} {document_ref or ''}".strip()
    if line.direction == "in":
        lines = (
            JournalLine(bank_account, "Banka girisi", debit=amount, document_ref=document_ref),
            JournalLine(account_code, line.transaction_type, credit=amount, document_ref=document_ref),
        )
        entry_type = "bank_collection"
    else:
        lines = (
            JournalLine(account_code, line.transaction_type, debit=amount, document_ref=document_ref),
            JournalLine(bank_account, "Banka cikisi", credit=amount, document_ref=document_ref),
        )
        entry_type = "bank_payment"
    return JournalEntry(
        entry_type=entry_type,
        entry_date=entry_date,
        description=description,
        lines=lines,
        risk_flags=line.risk_flags,
    )


def build_statement_entries(
    *,
    lines: tuple[StatementLine, ...],
    bank_account: str = "102.01",
    document_ref: str | None = None,
) -> tuple[JournalEntry, ...]:
    return tuple(entry for _, entry in build_statement_entry_records(lines=lines, bank_account=bank_account, document_ref=document_ref))


def build_statement_entry_records(
    *,
    lines: tuple[StatementLine, ...],
    bank_account: str = "102.01",
    document_ref: str | None = None,
) -> tuple[tuple[StatementLine, JournalEntry], ...]:
    return tuple(
        (line, build_statement_entry(line=line, bank_account=bank_account, document_ref=document_ref))
        for line in lines
        if _amount(line.amount) > 0 and line.direction in {"in", "out"}
    )


def statement_line_fingerprint(line: StatementLine) -> str:
    normalized_description = unicodedata.normalize("NFKD", line.description)
    normalized_description = "".join(character for character in normalized_description if not unicodedata.combining(character))
    normalized_description = re.sub(r"[^a-zA-Z0-9]+", " ", normalized_description).strip().lower()
    raw_key = "|".join(
        (
            line.transaction_date.strip(),
            line.direction.strip(),
            line.amount.strip(),
            normalized_description,
        )
    )
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:24]


def journal_entry_payload(entry: JournalEntry) -> dict[str, object]:
    return {
        "entry_type": entry.entry_type,
        "entry_date": entry.entry_date,
        "description": entry.description,
        "total_debit": f"{entry.total_debit:.2f}",
        "total_credit": f"{entry.total_credit:.2f}",
        "is_balanced": entry.is_balanced,
        "risk_flags": list(entry.risk_flags),
        "lines": [
            {
                **asdict(line),
                "debit": f"{line.debit:.2f}",
                "credit": f"{line.credit:.2f}",
            }
            for line in entry.lines
        ],
    }


def statement_entry_payload(
    *,
    line: StatementLine,
    entry: JournalEntry,
    source_document_ref: str,
) -> dict[str, object]:
    return {
        **journal_entry_payload(entry),
        "statement_line_no": line.line_no,
        "statement_fingerprint": statement_line_fingerprint(line),
        "source_document_ref": source_document_ref,
        "accountant_review_status": "",
    }
