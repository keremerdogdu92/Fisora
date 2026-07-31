from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable


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
INLINE_ROW_RE = re.compile(
    r"^\s*\d{1,3}\s+"
    r"(?P<description>.+?)\s+"
    r"-?\d+(?:[.,]\d+)?\s*(?:adet|kg|lt|metre|paket|koli)\s+"
    r"-?\d+(?:[.,]\d+)?\s*(?:TL|TRY)?\s+"
    r"(?P<taxable>-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})|-?\d+(?:[,.]\d{1,2}))"
    r"\s*(?:TL|TRY)?\s*$",
    re.IGNORECASE,
)
MONEY = Decimal("0.01")


@dataclass(frozen=True)
class InvoiceLine:
    raw_text: str
    description: str
    amount_hint: str = ""
    source: str = "pdf_text"
    source_position: str = ""
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


def parse_invoice_money(value: str) -> Decimal:
    parsed = _parse_decimal(value)
    if parsed is None:
        raise ValueError(f"invalid invoice money: {value}")
    return parsed


def _format_decimal(value: Decimal) -> str:
    return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}"


def _table_amount_details(tokens: list[str]) -> tuple[str, str, str, str]:
    rate = ""
    rate_index = -1
    for index, token in enumerate(tokens):
        match = VAT_RATE_RE.fullmatch(_normalize_search(token))
        if match:
            rate = str(int(match.group(1)))
            rate_index = index
    if rate_index < 0:
        for index, token in enumerate(tokens):
            match = VAT_RATE_RE.search(_normalize_search(token))
            if match:
                rate = str(int(match.group(1)))
                rate_index = index
    all_money = [_money_token(token) for token in tokens]
    all_money = [value for value in all_money if value]
    if rate_index < 0:
        taxable_amount = all_money[-1] if all_money else ""
        return "", taxable_amount, "", taxable_amount

    money_after_rate = [_money_token(token) for token in tokens[rate_index + 1 :]]
    money_after_rate = [value for value in money_after_rate if value]
    money_before_rate = [_money_token(token) for token in tokens[:rate_index]]
    money_before_rate = [value for value in money_before_rate if value]
    tax_amount = money_after_rate[0] if money_after_rate else ""
    taxable_amount = ""
    rate_decimal = _parse_decimal(rate)
    tax_decimal = _parse_decimal(tax_amount)
    if rate_decimal is not None and tax_decimal is not None:
        precise_after = tuple(
            candidate
            for candidate in money_after_rate[1:]
            if "," in candidate or "." in candidate
        )
        precise_before = tuple(
            candidate
            for candidate in reversed(money_before_rate)
            if "," in candidate or "." in candidate
        )
        candidate_groups = (
            precise_after,
            precise_before,
            tuple(money_after_rate[1:]),
            tuple(reversed(money_before_rate)),
        )
        for candidates in candidate_groups:
            for candidate in candidates:
                candidate_decimal = _parse_decimal(candidate)
                if candidate_decimal is None:
                    continue
                expected_tax = (candidate_decimal * rate_decimal / Decimal("100")).quantize(
                    MONEY,
                    rounding=ROUND_HALF_UP,
                )
                if expected_tax == tax_decimal:
                    taxable_amount = candidate
                    break
            if taxable_amount:
                break
    if not taxable_amount:
        taxable_amount = (
            money_after_rate[1]
            if len(money_after_rate) >= 2
            else (money_before_rate[-1] if money_before_rate else "")
        )
    gross_amount = ""
    taxable_decimal = _parse_decimal(taxable_amount)
    tax_decimal = _parse_decimal(tax_amount)
    if taxable_decimal is not None and tax_decimal is not None:
        gross_amount = _format_decimal(taxable_decimal + tax_decimal)
    return rate, taxable_amount, tax_amount, gross_amount


def _extract_inline_invoice_lines(lines: list[str], *, max_lines: int) -> tuple[InvoiceLine, ...]:
    extracted: list[InvoiceLine] = []
    for index, line in enumerate(lines):
        match = INLINE_ROW_RE.fullmatch(line)
        if not match:
            continue
        description = _normalize(match.group("description"))
        taxable_amount = _clean_amount(match.group("taxable"))
        vat_rate = ""
        tax_amount = ""
        if index + 1 < len(lines):
            adjacent = lines[index + 1]
            rate_match = VAT_RATE_RE.search(_normalize_search(adjacent))
            adjacent_amount = AMOUNT_AT_END_RE.search(adjacent)
            if rate_match and adjacent_amount:
                vat_rate = str(int(rate_match.group(1)))
                tax_amount = _clean_amount(adjacent_amount.group(1))
        taxable = _parse_decimal(taxable_amount)
        tax = _parse_decimal(tax_amount)
        gross_amount = (
            _format_decimal(taxable + tax)
            if taxable is not None and tax is not None
            else taxable_amount
        )
        extracted.append(
            InvoiceLine(
                raw_text=line,
                description=description,
                amount_hint=gross_amount,
                source=f"pdf:inline:row:{index + 1}",
                source_position=f"pdf:inline:row:{index + 1}",
                vat_rate=vat_rate,
                taxable_amount=taxable_amount,
                tax_amount=tax_amount,
                gross_amount=gross_amount,
            )
        )
        if len(extracted) >= max_lines:
            break
    return tuple(extracted)


def _extract_columnar_invoice_lines(lines: list[str], *, max_lines: int) -> tuple[InvoiceLine, ...]:
    header_indexes = [
        index
        for index, line in enumerate(lines)
        if _normalize_search(line) in {"no/kalem", "no / kalem"}
    ]
    if not header_indexes:
        return ()

    start = header_indexes[0]
    try:
        values_start = next(
            index + 1
            for index in range(start, len(lines))
            if _normalize_search(lines[index]) == "tutar"
        )
    except StopIteration:
        return ()

    extracted: list[InvoiceLine] = []
    index = values_start
    while index < len(lines):
        if _is_noise(lines[index]):
            break
        if not _is_line_no(lines[index]):
            index += 1
            continue

        row_start = index
        row_end = len(lines)
        cursor = index + 1
        while cursor < len(lines):
            if _is_noise(lines[cursor]):
                row_end = cursor
                break
            cursor += 1
        tokens = lines[index + 1 : row_end]
        rate_index = next(
            (
                token_index
                for token_index, token in enumerate(tokens)
                if _normalize(token) in {"0", "1", "8", "10", "18", "20"}
                and len(
                    [
                        value
                        for value in (_money_token(item) for item in tokens[token_index + 1 :])
                        if value
                    ]
                )
                >= 2
            ),
            -1,
        )
        if rate_index >= 0:
            description_parts = [
                token
                for token in tokens[:rate_index]
                if token != "-" and not QUANTITY_OR_AMOUNT_RE.fullmatch(_normalize(token))
            ]
            money_after_rate = [
                value
                for value in (_money_token(item) for item in tokens[rate_index + 1 :])
                if value
            ]
            description = _normalize(" ".join(description_parts))
            taxable_amount = money_after_rate[-1]
            taxable = _parse_decimal(taxable_amount)
            rate = Decimal(_normalize(tokens[rate_index]))
            if description and taxable is not None:
                tax = (taxable * rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
                extracted.append(
                    InvoiceLine(
                        raw_text=description,
                        description=description,
                        amount_hint=_format_decimal(taxable + tax),
                        source=f"pdf:columnar:row:{row_start + 1}",
                        source_position=f"pdf:columnar:row:{row_start + 1}",
                        vat_rate=f"{rate.normalize():f}",
                        taxable_amount=taxable_amount,
                        tax_amount=_format_decimal(tax),
                        gross_amount=_format_decimal(taxable + tax),
                    )
                )
                if len(extracted) >= max_lines:
                    break
        index = max(row_end, index + 1)
    return tuple(extracted)


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
            current_line_no = int(_normalize(line))

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
                    if value_tokens and _is_noise(candidate):
                        break
                    if (
                        value_tokens
                        and _is_line_no(candidate)
                        and int(_normalize(candidate)) == current_line_no + 1
                        and value_cursor + 1 < len(lines)
                        and _normalize_search(lines[value_cursor + 1]) not in UNIT_LABELS
                        and not QUANTITY_UNIT_RE.fullmatch(_normalize(lines[value_cursor + 1]))
                        and not _is_noise(lines[value_cursor + 1])
                    ):
                        break
                    value_tokens.append(candidate)
                    value_cursor += 1
                vat_rate, taxable_amount, tax_amount, gross_amount = _table_amount_details(value_tokens)
                extracted.append(
                    InvoiceLine(
                        raw_text=description,
                        description=description,
                        amount_hint=gross_amount,
                        source=f"pdf:table:{start + 1}:row:{index + 1}",
                        source_position=f"pdf:table:{start + 1}:row:{index + 1}",
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
    inline_lines = _extract_inline_invoice_lines(raw_lines, max_lines=max_lines)
    if inline_lines:
        return inline_lines
    columnar_lines = _extract_columnar_invoice_lines(raw_lines, max_lines=max_lines)
    if columnar_lines:
        return columnar_lines

    lines: list[InvoiceLine] = []
    for source_index, line in enumerate(raw_lines, start=1):
        if len(line) < 3 or _is_noise(line) or _is_value_or_unit(line):
            continue
        amount_match = AMOUNT_AT_END_RE.search(line)
        amount_hint = amount_match.group(1) if amount_match else ""
        description = _normalize(line[: amount_match.start()] if amount_match else line)
        if not description:
            continue
        if len(description) > 120:
            description = description[:120].rstrip()
        lines.append(
            InvoiceLine(
                raw_text=line,
                description=description,
                amount_hint=amount_hint,
                source=f"pdf:text:line:{source_index}",
                source_position=f"pdf:text:line:{source_index}",
            )
        )
        if len(lines) >= max_lines:
            break
    return tuple(lines)


def extract_invoice_lines_from_pages(
    pages: Iterable[object],
    *,
    max_lines: int = 20,
) -> tuple[InvoiceLine, ...]:
    parsed_pages: list[tuple[int, tuple[InvoiceLine, ...]]] = []
    has_table_lines = False
    for page in pages:
        page_no = int(getattr(page, "page_no", 0) or 0)
        page_text = str(getattr(page, "text", "") or "")
        page_lines = extract_invoice_lines_from_text(page_text, max_lines=max_lines)
        has_table_lines = has_table_lines or any(
            line.source_position.startswith("pdf:table:")
            for line in page_lines
        )
        parsed_pages.append((page_no, page_lines))

    extracted: list[InvoiceLine] = []
    seen_positions: set[str] = set()
    for page_no, page_lines in parsed_pages:
        for line in page_lines:
            if has_table_lines and not line.source_position.startswith("pdf:table:"):
                continue
            row_position = line.source_position.rsplit(":row:", 1)[-1]
            source_position = (
                f"pdf:page:{page_no}:row:{row_position}"
                if ":row:" in line.source_position
                else f"pdf:page:{page_no}:{line.source_position}"
            )
            if source_position in seen_positions:
                continue
            seen_positions.add(source_position)
            extracted.append(
                replace(
                    line,
                    source=source_position,
                    source_position=source_position,
                )
            )
            if len(extracted) >= max_lines:
                return tuple(extracted)
    return tuple(extracted)


def invoice_line_hints(lines: tuple[InvoiceLine, ...]) -> tuple[str, ...]:
    return tuple(line.description for line in lines if line.description)
