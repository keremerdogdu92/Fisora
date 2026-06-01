from __future__ import annotations

import re
from dataclasses import dataclass


AMOUNT_AT_END_RE = re.compile(r"(?<!\d)(-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|-?\d+(?:,\d{2}))(?:\s*(?:TL|TRY))?\s*$")
NOISE_LABELS = (
    "mal hizmet toplam",
    "hesaplanan kdv",
    "vergiler dahil",
    "odenecek tutar",
    "ödenecek tutar",
    "fatura no",
    "ettn",
    "fatura tarihi",
)


@dataclass(frozen=True)
class InvoiceLine:
    raw_text: str
    description: str
    amount_hint: str = ""
    source: str = "pdf_text"


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())


def _is_noise(line: str) -> bool:
    normalized = line.lower()
    return any(label in normalized for label in NOISE_LABELS)


def extract_invoice_lines_from_text(text: str, *, max_lines: int = 20) -> tuple[InvoiceLine, ...]:
    lines: list[InvoiceLine] = []
    for raw in text.splitlines():
        line = _normalize(raw)
        if len(line) < 3 or _is_noise(line):
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
