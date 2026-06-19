from __future__ import annotations

import re
from dataclasses import dataclass


AMOUNT_AT_END_RE = re.compile(r"(?<!\d)(-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|-?\d+(?:,\d{2}))(?:\s*(?:TL|TRY))?\s*$")
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


@dataclass(frozen=True)
class InvoiceLine:
    raw_text: str
    description: str
    amount_hint: str = ""
    source: str = "pdf_text"


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
    return lowered in UNIT_LABELS or lowered.startswith("%") or bool(QUANTITY_OR_AMOUNT_RE.fullmatch(normalized))


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
                extracted.append(InvoiceLine(raw_text=description, description=description))
                if len(extracted) >= max_lines:
                    return tuple(extracted)
            index = max(cursor, index + 1)
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
