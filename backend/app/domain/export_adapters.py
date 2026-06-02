from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.domain.exporters import export_universal_journal_csv
from app.domain.journal_entries import JournalEntry


ExportAdapterType = Literal["zirve_universal_csv", "json_manifest"]


@dataclass(frozen=True)
class ExportAdapter:
    export_type: ExportAdapterType
    file_extension: str
    mime_type: str
    display_name: str
    verified_in_zirve: bool


SUPPORTED_EXPORT_ADAPTERS: dict[str, ExportAdapter] = {
    "zirve_universal_csv": ExportAdapter(
        export_type="zirve_universal_csv",
        file_extension=".csv",
        mime_type="text/csv; charset=utf-8",
        display_name="Zirve Universal Journal CSV",
        verified_in_zirve=False,
    ),
    "json_manifest": ExportAdapter(
        export_type="json_manifest",
        file_extension=".json",
        mime_type="application/json; charset=utf-8",
        display_name="JSON audit manifest",
        verified_in_zirve=False,
    ),
}


def get_export_adapter(export_type: str) -> ExportAdapter:
    adapter = SUPPORTED_EXPORT_ADAPTERS.get(export_type)
    if adapter is None:
        supported = ", ".join(sorted(SUPPORTED_EXPORT_ADAPTERS))
        raise ValueError(f"unsupported export adapter: {export_type}. supported: {supported}")
    return adapter


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
                "account_code": line.account_code,
                "description": line.description,
                "debit": f"{line.debit:.2f}",
                "credit": f"{line.credit:.2f}",
                "document_ref": line.document_ref,
                "counterparty_tax_id": line.counterparty_tax_id,
            }
            for line in entry.lines
        ],
    }


def write_export_file(
    *,
    adapter: ExportAdapter,
    entries: tuple[JournalEntry, ...],
    output_path: Path | str,
    client_id: str = "",
) -> Path:
    path = Path(output_path)
    if adapter.export_type == "zirve_universal_csv":
        return export_universal_journal_csv(list(entries), path)
    if adapter.export_type == "json_manifest":
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "client_id": client_id,
            "export_type": adapter.export_type,
            "adapter": {
                "display_name": adapter.display_name,
                "verified_in_zirve": adapter.verified_in_zirve,
            },
            "entry_count": len(entries),
            "entries": [journal_entry_payload(entry) for entry in entries],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    raise ValueError(f"unsupported export adapter: {adapter.export_type}")
