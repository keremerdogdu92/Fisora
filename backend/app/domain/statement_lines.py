from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Iterable

from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty


@dataclass(frozen=True)
class StatementLine:
    line_no: int
    transaction_date: str
    description: str
    amount: str
    direction: str
    balance_after: str = ""
    counterparty_name: str = ""
    tax_id: str = ""
    iban: str = ""
    suggested_account_code: str = ""
    transaction_type: str = "unknown"
    confidence: int = 35
    risk_flags: tuple[str, ...] = ("statement_review_required",)
    counterparty_match_code: str = ""
    counterparty_match_name: str = ""
    counterparty_match_confidence: int = 0
    counterparty_match_reason: str = "not_assessed"


HEADER_ALIASES = {
    "transaction_date": {"transaction_date", "date", "tarih", "islem_tarihi", "işlem_tarihi"},
    "description": {"description", "aciklama", "açıklama", "islem_aciklama", "işlem_açıklama"},
    "amount": {"amount", "tutar", "islem_tutari", "işlem_tutarı"},
    "direction": {"direction", "yon", "yön", "borc_alacak", "borç_alacak"},
    "balance_after": {"balance_after", "bakiye", "son_bakiye"},
    "counterparty_name": {"counterparty_name", "cari_unvan", "unvan", "firma", "alici_satici", "karsi_hesap"},
    "tax_id": {"tax_id", "vkn", "tckn", "vergi_no", "vergi_numarasi"},
    "iban": {"iban", "karsi_iban", "counterparty_iban"},
    "suggested_account_code": {"suggested_account_code", "hesap_kodu", "account_code"},
}


def _normalize(value: str) -> str:
    replacements = {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
    result = value.strip().lower()
    for source, target in replacements.items():
        result = result.replace(source, target)
    result = re.sub(r"[^a-z0-9]+", "_", result).strip("_")
    return result


def _column_map(headers: Iterable[str]) -> dict[str, str]:
    normalized_headers = {header: _normalize(header) for header in headers}
    mapped: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for header, normalized in normalized_headers.items():
            if normalized in aliases:
                mapped[canonical] = header
                break
    return mapped


def _parse_decimal(value: str) -> Decimal | None:
    compact = value.strip().replace(" ", "")
    if not compact:
        return None
    if "," in compact and "." in compact:
        compact = compact.replace(".", "").replace(",", ".")
    elif "," in compact:
        compact = compact.replace(",", ".")
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _format_decimal(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else ""


def _infer_direction(amount: Decimal | None, raw_direction: str) -> str:
    direction = _normalize(raw_direction)
    if direction in {"out", "cikis", "borc", "debit", "odeme"}:
        return "out"
    if direction in {"in", "giris", "alacak", "credit", "tahsilat"}:
        return "in"
    if amount is not None and amount < 0:
        return "out"
    if amount is not None and amount > 0:
        return "in"
    return ""


def _classify_statement_line(description: str, suggested_account_code: str) -> tuple[str, str, int, tuple[str, ...]]:
    normalized = _normalize(description).replace("_", " ")
    if "gib" in normalized or "vergi" in normalized:
        return "tax_payment", suggested_account_code or "360", 86, ()
    if "sgk" in normalized or "sosyal guvenlik" in normalized:
        return "sgk_payment", suggested_account_code or "361", 86, ()
    if "pos" in normalized and "bloke" in normalized:
        return "pos_blocked", suggested_account_code or "108", 78, ("pos_policy_review_required",)
    if "pos" in normalized:
        return "pos_collection", suggested_account_code or "108", 72, ("pos_policy_review_required",)
    if suggested_account_code:
        return "suggested_by_import", suggested_account_code, 70, ("statement_review_required",)
    return "unknown", "", 35, ("statement_review_required",)


def _line_from_row(line_no: int, row: dict[str, object], mapping: dict[str, str]) -> StatementLine:
    def value(key: str) -> str:
        column = mapping.get(key, "")
        return str(row.get(column, "") or "").strip()

    amount = _parse_decimal(value("amount"))
    direction = _infer_direction(amount, value("direction"))
    transaction_type, account_code, confidence, risk_flags = _classify_statement_line(
        value("description"),
        value("suggested_account_code"),
    )
    return StatementLine(
        line_no=line_no,
        transaction_date=value("transaction_date"),
        description=value("description"),
        amount=_format_decimal(abs(amount) if amount is not None else None),
        direction=direction,
        balance_after=value("balance_after"),
        counterparty_name=value("counterparty_name"),
        tax_id=value("tax_id"),
        iban=value("iban"),
        suggested_account_code=account_code,
        transaction_type=transaction_type,
        confidence=confidence,
        risk_flags=risk_flags,
    )


def enrich_statement_lines_with_counterparties(
    lines: tuple[StatementLine, ...],
    accounts: list[ChartAccount],
    learning_events: Iterable[dict[str, object]] = (),
) -> tuple[StatementLine, ...]:
    if not accounts:
        return tuple(
            _add_counterparty_missing_flag(line)
            if line.transaction_type == "unknown" and not line.suggested_account_code
            else line
            for line in lines
        )
    events = tuple(learning_events)
    return tuple(_enrich_statement_line_with_counterparty(line, accounts, events) for line in lines)


def _enrich_statement_line_with_counterparty(
    line: StatementLine,
    accounts: list[ChartAccount],
    learning_events: tuple[dict[str, object], ...],
) -> StatementLine:
    if line.transaction_type in {"tax_payment", "sgk_payment"}:
        return line
    name_hint = line.counterparty_name or line.description
    match = match_counterparty(
        accounts,
        tax_ids=tuple(tax_id for tax_id in (line.tax_id,) if tax_id),
        ibans=tuple(iban for iban in (line.iban,) if iban),
        name_hint=name_hint,
    )
    learned = _learning_counterparty_match(line, accounts, learning_events)
    if learned is not None and (not match.account_code or match.requires_review):
        return learned
    if not match.account_code:
        return _add_counterparty_missing_flag(line) if line.transaction_type == "unknown" else line

    flags = tuple(flag for flag in line.risk_flags if flag != "statement_review_required")
    if match.requires_review:
        flags = tuple(dict.fromkeys((*flags, "counterparty_match_review_required")))
    transaction_type = line.transaction_type
    if transaction_type == "unknown":
        transaction_type = "counterparty_collection" if line.direction == "in" else "counterparty_payment"
    return replace(
        line,
        suggested_account_code=line.suggested_account_code or match.account_code,
        transaction_type=transaction_type,
        confidence=max(line.confidence, match.confidence),
        risk_flags=flags,
        counterparty_match_code=match.account_code,
        counterparty_match_name=match.account_name,
        counterparty_match_confidence=match.confidence,
        counterparty_match_reason=match.match_reason,
    )


def _learning_counterparty_match(
    line: StatementLine,
    accounts: list[ChartAccount],
    learning_events: tuple[dict[str, object], ...],
) -> StatementLine | None:
    normalized_text = _normalize(f"{line.description} {line.counterparty_name}")
    if not normalized_text:
        return None
    accounts_by_code = {account.normalized_account_code: account for account in accounts if account.is_detail_account}
    for event in reversed(learning_events):
        account_code = normalize_account_code(str(event.get("corrected_counterparty_code") or ""))
        account = accounts_by_code.get(account_code)
        if account is None:
            continue
        hints = (
            str(event.get("category") or ""),
            str(event.get("reason") or ""),
            str(event.get("document_ref") or ""),
        )
        if not any(_learning_hint_matches(normalized_text, hint) for hint in hints):
            continue
        automation_candidate = bool(event.get("automation_candidate"))
        flags = tuple(flag for flag in line.risk_flags if flag != "statement_review_required")
        if not automation_candidate:
            flags = tuple(dict.fromkeys((*flags, "learning_rule_review_required")))
        transaction_type = line.transaction_type
        if transaction_type == "unknown":
            transaction_type = "counterparty_collection" if line.direction == "in" else "counterparty_payment"
        return replace(
            line,
            suggested_account_code=line.suggested_account_code or account.normalized_account_code,
            transaction_type=transaction_type,
            confidence=max(line.confidence, 90 if automation_candidate else 76),
            risk_flags=flags,
            counterparty_match_code=account.normalized_account_code,
            counterparty_match_name=account.account_name,
            counterparty_match_confidence=90 if automation_candidate else 76,
            counterparty_match_reason="learning_event",
        )
    return None


def _learning_hint_matches(normalized_text: str, hint: str) -> bool:
    normalized_hint = _normalize(hint)
    return len(normalized_hint) >= 4 and normalized_hint in normalized_text


def _add_counterparty_missing_flag(line: StatementLine) -> StatementLine:
    return replace(
        line,
        risk_flags=tuple(dict.fromkeys((*line.risk_flags, "counterparty_not_found"))),
        counterparty_match_reason="not_found",
    )


def parse_statement_csv(path: Path) -> tuple[StatementLine, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        mapping = _column_map(reader.fieldnames or [])
        return tuple(
            _line_from_row(index, row, mapping)
            for index, row in enumerate(reader, start=1)
            if any(str(value or "").strip() for value in row.values())
        )


def parse_statement_xlsx(path: Path) -> tuple[StatementLine, ...]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    headers = [str(value or "") for value in next(rows, ())]
    mapping = _column_map(headers)
    lines: list[StatementLine] = []
    for index, values in enumerate(rows, start=1):
        row = {header: value for header, value in zip(headers, values, strict=False)}
        if not any(str(value or "").strip() for value in row.values()):
            continue
        lines.append(_line_from_row(index, row, mapping))
    return tuple(lines)


def parse_statement_file(path: Path) -> tuple[StatementLine, ...]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return parse_statement_csv(path)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_statement_xlsx(path)
    return ()
