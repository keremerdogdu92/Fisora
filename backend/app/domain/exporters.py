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

ZIRVE_TRIAL_COLUMNS = [
    "fis_tarihi",
    "fis_turu",
    "fis_aciklama",
    "satir_no",
    "hesap_kodu",
    "satir_aciklama",
    "borc",
    "alacak",
    "belge_no",
    "vergi_no",
    "kaynak_belge",
]

ZIRVE_MAPPING_COLUMNS = [
    "hesap_kodu",
    "evrak_tarihi",
    "evrak_no",
    "belge_turu",
    "aciklama",
    "borc",
    "alacak",
    "vkn_tckn",
    "odeme_sekli",
    "fis_turu",
    "satir_no",
    "kaynak_belge",
]

ZIRVE_TRIAL_VOUCHER_TYPES = {
    "bank_collection": "BANKA",
    "bank_payment": "BANKA",
}


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


def export_zirve_trial_csv(entries: list[JournalEntry], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ZIRVE_TRIAL_COLUMNS, delimiter=";")
        writer.writeheader()
        for entry in entries:
            voucher_type = ZIRVE_TRIAL_VOUCHER_TYPES.get(entry.entry_type, "MAHSUP")
            for line_no, line in enumerate(entry.lines, start=1):
                writer.writerow(
                    {
                        "fis_tarihi": entry.entry_date,
                        "fis_turu": voucher_type,
                        "fis_aciklama": entry.description,
                        "satir_no": line_no,
                        "hesap_kodu": line.account_code,
                        "satir_aciklama": line.description,
                        "borc": f"{line.debit:.2f}",
                        "alacak": f"{line.credit:.2f}",
                        "belge_no": line.document_ref or "",
                        "vergi_no": line.counterparty_tax_id or "",
                        "kaynak_belge": line.document_ref or "",
                    }
                )
    return output_path


def export_zirve_mapping_csv(entries: list[JournalEntry], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ZIRVE_MAPPING_COLUMNS, delimiter=";")
        writer.writeheader()
        for entry in entries:
            voucher_type = ZIRVE_TRIAL_VOUCHER_TYPES.get(entry.entry_type, "MAHSUP")
            for line_no, line in enumerate(entry.lines, start=1):
                document_ref = line.document_ref or ""
                writer.writerow(
                    {
                        "hesap_kodu": line.account_code,
                        "evrak_tarihi": entry.entry_date,
                        "evrak_no": document_ref,
                        "belge_turu": voucher_type,
                        "aciklama": line.description,
                        "borc": f"{line.debit:.2f}",
                        "alacak": f"{line.credit:.2f}",
                        "vkn_tckn": line.counterparty_tax_id or "",
                        "odeme_sekli": "",
                        "fis_turu": voucher_type,
                        "satir_no": line_no,
                        "kaynak_belge": document_ref,
                    }
                )
    return output_path

