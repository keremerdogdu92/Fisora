from __future__ import annotations

import re
from dataclasses import dataclass


KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("withholding", ("tevkifat", "tevkifatli", "tevkifatlı")),
    ("exemption", ("istisna", "muafiyet")),
    ("return_invoice", ("iade", "iade faturasi", "iade faturası")),
    ("cancelled_invoice", ("iptal", "iptal edilmistir", "iptal edildi", "cancelled", "canceled")),
    ("zero_amount", ("0,00", "0.00")),
    (
        "special_tax",
        (
            "oiv",
            "öiv",
            "ozel iletisim vergisi",
            "özel iletişim vergisi",
            "iletisim vergisi",
            "iletişim vergisi",
            "telsiz kullanma",
            "otv",
            "ötv",
        ),
    ),
    ("e_archive", ("e-arsiv", "e-arşiv")),
    ("e_invoice", ("e-fatura", "efatura")),
)

PROVIDER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Kolay Soft", ("kolay soft", "kolaysoft")),
    ("QNB eFinans", ("qnb", "efinans")),
    ("Aposkal", ("aposkal", "apoksal")),
)


@dataclass(frozen=True)
class InvoiceEdgeCaseSummary:
    provider_hint: str
    invoice_no: str
    ettn: str
    detected_keywords: tuple[str, ...]
    risk_flags: tuple[str, ...]
    suggested_expected_behavior: str


def normalize_text(value: str) -> str:
    lowered = value.lower()
    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
        "İ": "i",
    }
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    return lowered


def detect_provider(file_name: str, text: str) -> str:
    haystack = normalize_text(f"{file_name}\n{text}")
    for provider, needles in PROVIDER_RULES:
        if any(normalize_text(needle) in haystack for needle in needles):
            return provider
    return ""


def detect_keywords(text: str) -> tuple[str, ...]:
    haystack = normalize_text(text)
    detected: list[str] = []
    for keyword, needles in KEYWORD_RULES:
        if any(normalize_text(needle) in haystack for needle in needles):
            detected.append(keyword)
    return tuple(detected)


def detect_vat_rates(text: str) -> tuple[str, ...]:
    matches: set[str] = set()
    for line in text.splitlines():
        normalized = normalize_text(line)
        if "kdv" not in normalized and "katma deger vergisi" not in normalized:
            continue
        matches.update(re.findall(r"%\s*(0|1|8|10|18|20)(?:[,.]0+)?\b", normalized))
    return tuple(sorted(matches, key=lambda value: int(value)))


def extract_ettn(text: str) -> str:
    match = re.search(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        text,
    )
    return match.group(0) if match else ""


def extract_invoice_no(text: str) -> str:
    patterns = (
        r"(?:Fatura\s*No|Fatura\s*Numarasi|Fatura\s*Numarası|Invoice\s*No)\s*[:\-]?\s*([A-Z0-9\-]{6,})",
        r"\b([A-Z]{3}[0-9]{10,16})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def summarize_invoice_edge_cases(file_name: str, text: str, *, extracted_char_count: int) -> InvoiceEdgeCaseSummary:
    keywords = list(detect_keywords(text))
    vat_rates = detect_vat_rates(text)
    risk_flags: list[str] = []

    if extracted_char_count < 100:
        risk_flags.append("text_extraction_low_confidence")
    if "withholding" in keywords:
        risk_flags.append("withholding_manual_review")
    if "exemption" in keywords:
        risk_flags.append("exemption_manual_review")
    if "return_invoice" in keywords:
        risk_flags.append("return_invoice_manual_review")
    if "cancelled_invoice" in keywords:
        risk_flags.append("cancelled_invoice_visible")
    if "special_tax" in keywords:
        risk_flags.append("special_tax_manual_review")
    if len(vat_rates) > 1:
        risk_flags.append("mixed_vat_manual_review")

    expected = "review_queue" if risk_flags else "parser_candidate"
    if vat_rates:
        keywords.append("vat_rates:" + "|".join(vat_rates))

    return InvoiceEdgeCaseSummary(
        provider_hint=detect_provider(file_name, text),
        invoice_no=extract_invoice_no(text),
        ettn=extract_ettn(text),
        detected_keywords=tuple(dict.fromkeys(keywords)),
        risk_flags=tuple(dict.fromkeys(risk_flags)),
        suggested_expected_behavior=expected,
    )
