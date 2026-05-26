from __future__ import annotations

import csv
from pathlib import Path

from app.domain.journal_entries import JournalEntry


UNIVERSAL_JOURNAL_COLUMNS = [
    "entry_no",
    "entry_type",
    "entry_date",
    "line_no",
    "account_code",
    "description",
    "debit",
    "credit",
    "document_ref",
    "counterparty_tax_id",
    "risk_flags",
]


def export_universal_journal_csv(entries: list[JournalEntry], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNIVERSAL_JOURNAL_COLUMNS)
        writer.writeheader()
        for entry_no, entry in enumerate(entries, start=1):
            for line_no, line in enumerate(entry.lines, start=1):
                writer.writerow(
                    {
                        "entry_no": entry_no,
                        "entry_type": entry.entry_type,
                        "entry_date": entry.entry_date,
                        "line_no": line_no,
                        "account_code": line.account_code,
                        "description": line.description,
                        "debit": f"{line.debit:.2f}",
                        "credit": f"{line.credit:.2f}",
                        "document_ref": line.document_ref or "",
                        "counterparty_tax_id": line.counterparty_tax_id or "",
                        "risk_flags": ";".join(entry.risk_flags),
                    }
                )
    return output_path

