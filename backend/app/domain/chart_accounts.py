from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CODE_KEYS = (
    "account_code",
    "hesap_kodu",
    "hesap kodu",
    "kod",
    "code",
    "raw_account_code",
)
NAME_KEYS = (
    "account_name",
    "hesap_adi",
    "hesap adı",
    "hesap adi",
    "name",
    "description",
)
TAX_ID_KEYS = ("tax_id", "vkn", "tckn", "vergi_no", "vergi no")
TAX_OFFICE_KEYS = ("tax_office", "vergi_dairesi", "vergi dairesi")
IBAN_KEYS = ("iban", "banka_iban", "banka iban", "counterparty_iban", "karsi_iban")
DETAIL_KEYS = ("is_detail_account", "detay e/h", "detay", "detay hesap")


@dataclass(frozen=True)
class ChartAccount:
    raw_account_code: str
    normalized_account_code: str
    account_name: str
    is_detail_account: bool | None = None
    tax_id: str | None = None
    tax_office: str | None = None
    iban: str | None = None

    @property
    def is_counterparty_candidate(self) -> bool:
        return self.normalized_account_code.startswith(("120", "320"))

    @property
    def counterparty_type(self) -> str | None:
        if self.normalized_account_code.startswith("120"):
            return "customer"
        if self.normalized_account_code.startswith("320"):
            return "supplier"
        return None


def normalize_account_code(value: str) -> str:
    compact = value.strip().replace(",", ".")
    compact = re.sub(r"[\s\-]+", ".", compact)
    compact = re.sub(r"[^0-9A-Za-z.]", "", compact)
    compact = re.sub(r"\.+", ".", compact).strip(".")
    return compact


def normalize_iban(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", value).upper()


def _normalized_header(value: str) -> str:
    return value.strip().lower().replace("ı", "i").replace("İ", "i").replace("_", " ")


def _first_value(row: dict[str, str], keys: Iterable[str]) -> str:
    normalized = {_normalized_header(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_normalized_header(key))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _is_child(parent: str, child: str) -> bool:
    if parent == child or not child.startswith(parent):
        return False
    remainder = child[len(parent) :]
    if remainder.startswith((".", "-")):
        return True
    return parent.isdigit() and child.isdigit() and len(child) > len(parent)


def parse_detail_flag(value: str) -> bool | None:
    normalized = _normalized_header(value)
    if normalized in {"evet", "e", "yes", "true", "1"}:
        return True
    if normalized in {"hayir", "h", "no", "false", "0"}:
        return False
    return None


def mark_detail_accounts(accounts: list[ChartAccount]) -> list[ChartAccount]:
    codes = [account.normalized_account_code for account in accounts]
    result: list[ChartAccount] = []
    for account in accounts:
        has_child = any(_is_child(account.normalized_account_code, code) for code in codes)
        explicit_detail = account.is_detail_account
        result.append(
            ChartAccount(
                raw_account_code=account.raw_account_code,
                normalized_account_code=account.normalized_account_code,
                account_name=account.account_name,
                is_detail_account=explicit_detail if explicit_detail is not None else not has_child,
                tax_id=account.tax_id,
                tax_office=account.tax_office,
                iban=account.iban,
            )
        )
    return result


def parse_chart_accounts_csv(path: Path) -> list[ChartAccount]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        accounts = []
        for row in reader:
            raw_code = _first_value(row, CODE_KEYS)
            if not raw_code:
                continue
            name = _first_value(row, NAME_KEYS) or raw_code
            accounts.append(
                ChartAccount(
                    raw_account_code=raw_code,
                    normalized_account_code=normalize_account_code(raw_code),
                    account_name=name,
                    is_detail_account=parse_detail_flag(_first_value(row, DETAIL_KEYS)),
                    tax_id=_first_value(row, TAX_ID_KEYS) or None,
                    tax_office=_first_value(row, TAX_OFFICE_KEYS) or None,
                    iban=normalize_iban(_first_value(row, IBAN_KEYS)) or None,
                )
            )
    return mark_detail_accounts(accounts)


def parse_chart_accounts_xlsx(path: Path) -> list[ChartAccount]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("XLSX parsing requires openpyxl. Install backend requirements first.") from exc

    workbook = load_workbook(path, data_only=True, read_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(value or "") for value in rows[0]]
    accounts = []
    for values in rows[1:]:
        row = {headers[index]: str(value or "") for index, value in enumerate(values)}
        raw_code = _first_value(row, CODE_KEYS)
        if not raw_code:
            continue
        name = _first_value(row, NAME_KEYS) or raw_code
        accounts.append(
            ChartAccount(
                raw_account_code=raw_code,
                normalized_account_code=normalize_account_code(raw_code),
                account_name=name,
                is_detail_account=parse_detail_flag(_first_value(row, DETAIL_KEYS)),
                tax_id=_first_value(row, TAX_ID_KEYS) or None,
                tax_office=_first_value(row, TAX_OFFICE_KEYS) or None,
                iban=normalize_iban(_first_value(row, IBAN_KEYS)) or None,
            )
        )
    return mark_detail_accounts(accounts)


def parse_chart_accounts(path: Path | str) -> list[ChartAccount]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return parse_chart_accounts_csv(file_path)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_chart_accounts_xlsx(file_path)
    raise ValueError(f"Unsupported chart account format: {suffix}")


def extract_counterparty_candidates(accounts: Iterable[ChartAccount]) -> list[ChartAccount]:
    return [account for account in accounts if account.is_detail_account and account.is_counterparty_candidate]


def validate_vat_accounts(accounts: Iterable[ChartAccount]) -> dict[str, bool]:
    codes = {account.normalized_account_code for account in accounts}
    return {
        "has_purchase_vat_191": any(code.startswith("191") for code in codes),
        "has_sales_vat_391": any(code.startswith("391") for code in codes),
    }
