from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


AMOUNT_AT_END_RE = re.compile(r"(?<!\d)(-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|-?\d+(?:,\d{2}))(?:\s*(?:TL|TRY))?\s*$")
MONEY_TOKEN_RE = re.compile(
    r"^-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?(?:\s*(?:TL|TRY))?$|^-?\d+(?:[,.]\d{1,2})?(?:\s*(?:TL|TRY))?$",
    re.IGNORECASE,
)
VAT_RATE_RE = re.compile(r"%\s*(0|1|10|20)(?:[,.]0+)?\b")
QUANTITY_OR_AMOUNT_RE = re.compile(
    r"^-?\d{1,3}(?:[.\s]\d{3})*(?:[,.]\d+)?(?:\s*(?:TL|TRY))?$|^-?\d+(?:[,.]\d+)?(?:\s*(?:TL|TRY))?$"
)
NOISE_LABELS = (
    "mal hizmet toplam",
    "mal hizmet tutar",
    "mal hizmet",
    "malzeme/hizmet",
    "hesaplanan kdv",
    "kdv matrah",
    "kdv oran",
    "kdv tutar",
    "vergiler dahil",
    "vergi hari",
    "odenecek tutar",
    "odenecek tutar",
    "fatura no",
    "fatura tipi",
    "senaryo",
    "ozellestirme",
    "vergi dairesi",
    "vkn",
    "tckn",
    "ettn",
    "fatura tarihi",
)
UNIT_LABELS = {"adet", "kg", "lt", "metre", "paket", "koli", "tl", "try"}
QUANTITY_UNIT_RE = re.compile(r"^-?\d+(?:[,.]\d+)?\s*(?:adet|kg|lt|metre|paket|koli)\b", re.IGNORECASE)
MONEY = Decimal("0.01")


@dataclass(frozen=True)
class InvoiceLine:
    raw_text: str
    description: str
    amount_hint: str = ""
    source: str = "pdf_text"
    vat_rate: str = ""
    taxable_amount: str = ""
    tax_amount: str = ""
    gross_amount: str = ""


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_search(value: str) -> str:
    lowered = value.lower()
    return (
        lowered.replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ç", "c")
        .replace("Ç", "c")
    )


def _is_noise(line: str) -> bool:
    normalized = _normalize_search(line)
    return any(label in normalized for label in NOISE_LABELS)


def _is_table_header(line: str) -> bool:
    normalized = _normalize_search(_normalize(line))
    return normalized in {"mal hizmet", "malzeme/hizmet aciklamasi"}


def _is_line_no(line: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}", _normalize(line)))


def _is_value_or_unit(line: str) -> bool:
    normalized = _normalize(line)
    lowered = _normalize_search(normalized)
    return (
        lowered in UNIT_LABELS
        or lowered.startswith("%")
        or bool(QUANTITY_UNIT_RE.fullmatch(normalized))
        or bool(QUANTITY_OR_AMOUNT_RE.fullmatch(normalized))
    )


def _clean_amount(value: str) -> str:
    return re.sub(r"\s*(?:TL|TRY)\s*$", "", _normalize(value), flags=re.IGNORECASE)


def _money_token(value: str) -> str:
    normalized = _normalize(value)
    return _clean_amount(normalized) if MONEY_TOKEN_RE.fullmatch(normalized) else ""


def _parse_decimal(value: str) -> Decimal | None:
    compact = _clean_amount(value).replace(" ", "")
    if not compact:
        return None
    if "," in compact:
        raw = compact.replace(".", "").replace(",", ".")
    elif "." in compact and len(compact.rsplit(".", 1)[-1]) <= 2:
        raw = compact
    else:
        raw = compact.replace(".", "")
    try:
        return Decimal(raw).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal) -> str:
    return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}"


def _table_amount_details(tokens: list[str]) -> tuple[str, str, str, str]:
    rate = ""
    rate_index = -1
    for index, token in enumerate(tokens):
        match = VAT_RATE_RE.search(_normalize_search(token))
        if match:
            rate = str(int(match.group(1)))
            rate_index = index
            break
    if rate_index < 0:
        return "", "", "", ""

    money_after_rate = [_money_token(token) for token in tokens[rate_index + 1 :]]
    money_after_rate = [value for value in money_after_rate if value]
    tax_amount = money_after_rate[0] if money_after_rate else ""
    taxable_amount = money_after_rate[1] if len(money_after_rate) >= 2 else ""
    gross_amount = ""
    taxable_decimal = _parse_decimal(taxable_amount)
    tax_decimal = _parse_decimal(tax_amount)
    if taxable_decimal is not None and tax_decimal is not None:
        gross_amount = _format_decimal(taxable_decimal + tax_decimal)
    return rate, taxable_amount, tax_amount, gross_amount


def _extract_table_invoice_lines(lines: list[str], *, max_lines: int) -> tuple[InvoiceLine, ...]:
    start_indexes = [index for index, line in enumerate(lines) if _is_table_header(line)]
    extracted: list[InvoiceLine] = []
    for start in start_indexes:
        index = start + 1
        while index < len(lines):
            line = lines[index]
            lowered = _normalize_search(line)
            if lowered.startswith("*") or "sicil" in lowered or "yalniz" in lowered:
                break
            if not _is_line_no(line):
                index += 1
                continue

            desc_parts: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor]
                lowered_candidate = _normalize_search(candidate)
                if lowered_candidate.startswith("*") or "sicil" in lowered_candidate or "yalniz" in lowered_candidate:
                    break
                if desc_parts and (_is_line_no(candidate) or _is_value_or_unit(candidate)):
                    break
                if not _is_noise(candidate) and not _is_value_or_unit(candidate):
                    desc_parts.append(candidate)
                cursor += 1

            description = _normalize(" ".join(desc_parts))
            if description:
                value_tokens: list[str] = []
                value_cursor = cursor
                while value_cursor < len(lines):
                    candidate = lines[value_cursor]
                    lowered_candidate = _normalize_search(candidate)
                    if lowered_candidate.startswith("*") or "sicil" in lowered_candidate or "yalniz" in lowered_candidate:
                        break
                    if _is_line_no(candidate) and value_tokens:
                        break
                    value_tokens.append(candidate)
                    value_cursor += 1
                vat_rate, taxable_amount, tax_amount, gross_amount = _table_amount_details(value_tokens)
                extracted.append(
                    InvoiceLine(
                        raw_text=description,
                        description=description,
                        amount_hint=gross_amount,
                        vat_rate=vat_rate,
                        taxable_amount=taxable_amount,
                        tax_amount=tax_amount,
                        gross_amount=gross_amount,
                    )
                )
                if len(extracted) >= max_lines:
                    return tuple(extracted)
            index = max(value_cursor if description else cursor, index + 1)
    return tuple(extracted)


def extract_invoice_lines_from_text(text: str, *, max_lines: int = 20) -> tuple[InvoiceLine, ...]:
    raw_lines = [_normalize(raw) for raw in text.splitlines()]
    raw_lines = [line for line in raw_lines if line]
    table_lines = _extract_table_invoice_lines(raw_lines, max_lines=max_lines)
    if table_lines:
        return table_lines

    lines: list[InvoiceLine] = []
    for line in raw_lines:
        if len(line) < 3 or _is_noise(line) or _is_value_or_unit(line):
            continue
        amount_match = AMOUNT_AT_END_RE.search(line)
        amount_hint = amount_match.group(1) if amount_match else ""
        description = _normalize(line[: amount_match.start()] if amount_match else line)
        if not description:
            continue
        if len(description) > 120:
            description = description[:120].rstrip()
        lines.append(InvoiceLine(raw_text=line, description=description, amount_hint=amount_hint))
        if len(lines) >= max_lines:
            break
    return tuple(lines)


def invoice_line_hints(lines: tuple[InvoiceLine, ...]) -> tuple[str, ...]:
    return tuple(line.description for line in lines if line.description)
