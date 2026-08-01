from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping

from app.domain.canonical_invoices import (
    CanonicalInvoice,
    CanonicalExtractionPolicy,
    CanonicalExtractionRequest,
    CanonicalInvoiceHeader,
    CanonicalInvoiceLine,
    CanonicalInvoiceParty,
    CanonicalInvoiceTotals,
    CanonicalInvoiceValidation,
    CanonicalVatSummaryLine,
    canonical_invoice_from_ai_payload,
    validate_line_decision_coverage,
    with_validation,
)
from app.domain.provider_directory import resolve_provider_profile
from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_lines import (
    InvoiceLine,
    extract_invoice_lines_from_pages,
    extract_invoice_lines_from_text,
    invoice_line_hints,
    parse_invoice_money,
)
from app.domain.pdf_invoice_boundaries import PdfPageText, detect_multiple_invoice_identities
from app.domain.vat_splits import VatSplitLine, extract_pdf_vat_split


@dataclass(frozen=True)
class PdfCanonicalExtractionOutcome:
    invoice: CanonicalInvoice
    missing_vat_group_ids: tuple[str, ...] = ()
    attempts: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing_vat_group_ids


class SupportedPdfExtractionError(ValueError):
    reason_code = "line-missing"

    def __init__(self, missing_vat_group_ids: tuple[str, ...]) -> None:
        self.missing_vat_group_ids = missing_vat_group_ids
        super().__init__(
            "line-missing: supported text PDF has unreconciled VAT groups: "
            + ", ".join(missing_vat_group_ids)
        )


def _pdf_canonical_extraction_outcome(
    invoice: CanonicalInvoice,
    *,
    attempts: tuple[str, ...] = (),
) -> PdfCanonicalExtractionOutcome:
    missing_vat_group_ids = tuple(
        dict.fromkeys(
            evidence.removeprefix("vat_group:")
            for evidence in invoice.validation.evidence
            if evidence.startswith("vat_group:")
        )
    )
    return PdfCanonicalExtractionOutcome(
        invoice=invoice,
        missing_vat_group_ids=missing_vat_group_ids,
        attempts=attempts,
    )


DATE_RE = re.compile(r"(?<!\d)([0-3]?\d)\s*[./-]\s*([01]?\d)\s*[./-]\s*(20\d{2})(?!\d)")
ETTN_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
INVOICE_NO_RE = re.compile(r"\b([A-Z]{2,4}\d{8,16}|[A-Z]\d[A-Z]\d{8,16})\b")
TAX_ID_RE = re.compile(r"\b(?:VKN|TCKN|TC\s*Kimlik\s*No|Vergi\s*No)\s*:?\s*([0-9]{10,11})\b", re.IGNORECASE)
TAX_ID_VALUE_RE = re.compile(r"\b([0-9]{10,11})\b")
VAT_RATE_RE = re.compile(
    r"(?:KDV|Katma\s+Değer\s+Vergisi|Katma\s+Deger\s+Vergisi)[^\n\r%]{0,40}%?\s*\(?\s*([0-9]{1,2})(?:[,.]0+)?\s*\)?",
    re.IGNORECASE,
)
VAT_PERCENT_RE = re.compile(r"%\s*(0|1|8|10|18|20)(?:[,.]0+)?\b")
AMOUNT_RE = re.compile(r"(-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|-?\d+(?:,\d{2}))")
PDF_LINE_MONEY_RE = re.compile(
    r"(?<![%\d])-?(?:\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+[,.]\d{1,2})(?!\d)"
)


TOTAL_LABELS = {
    "goods_services_total": (
        "Mal Hizmet Toplam Tutarı",
        "Mal Hizmet Toplam Tutari",
        "Mal\tHizmet\tToplam\tTutarı",
        "Enerji Tüketim Toplam",
        "Enerji Tuketim Toplam",
    ),
    "vat_total": (
        "Hesaplanan KDV",
        "KDV Toplam",
        "KDV Tutarı",
        "KDV Tutari",
        "KDV %10",
        "KDV %20",
    ),
    "special_tax_total": (
        "OIV",
        "ÖİV",
        "Özel İletişim Vergisi",
        "Ozel Iletisim Vergisi",
        "Diğer Vergiler",
        "Diger Vergiler",
    ),
    "tax_inclusive_total": (
        "Vergiler Dahil Toplam Tutar",
        "Vergiler\tDahil\tToplam\tTutar",
        "Ara Toplam",
        "TOPLAM TUTAR",
        "TOPLAM",
    ),
    "payable_total": (
        "Ödenecek Tutar",
        "Odenecek Tutar",
        "ÖDENECEK TUTAR",
        "FATURA TUTARI",
        "Fatura Tutarı",
        "Toplam Fatura Tutarı",
    ),
}


@dataclass(frozen=True)
class ParsedInvoice:
    file_name: str
    provider_hint: str
    page_count: int
    text_extractable: bool
    extracted_char_count: int
    scenario: str
    invoice_type: str
    invoice_no: str
    ettn: str
    issue_date: str
    tax_ids: tuple[str, ...]
    vat_rates: tuple[str, ...]
    goods_services_total: str
    vat_total: str
    special_tax_total: str
    tax_inclusive_total: str
    payable_total: str
    risk_flags: tuple[str, ...]
    suggested_route: str
    parse_notes: tuple[str, ...]
    line_items: tuple[str, ...] = ()
    line_item_details: tuple[InvoiceLine, ...] = ()
    issuer_title: str = ""
    issuer_tax_id: str = ""
    recipient_title: str = ""
    recipient_tax_id: str = ""
    invoice_type_code: str = ""
    is_return_invoice: bool = False
    accounting_direction: str = "uncertain"
    direction_confidence: int = 0
    direction_evidence: tuple[str, ...] = ()
    vat_split_status: str = ""
    vat_split_lines: tuple[VatSplitLine, ...] = ()
    vat_split_evidence: tuple[str, ...] = ()
    canonical_invoice: CanonicalInvoice | None = None
    provider_id: str = ""
    service_profile: str = ""
    provider_match_kind: str = ""
    provider_match_reason: str = ""
    provider_directory_version: int = 0
    utility_exception_markers: tuple[str, ...] = ()


def extract_pdf_pages(path: Path) -> tuple[tuple[PdfPageText, ...], tuple[str, ...]]:
    notes: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return (), ("pypdf_not_installed",)

    try:
        reader = PdfReader(str(path))
        pages = tuple(
            PdfPageText(page_no=index + 1, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages)
        )
        return pages, tuple(notes)
    except Exception as exc:  # noqa: BLE001
        return (), (f"pdf_read_error:{type(exc).__name__}",)


def extract_pdf_text(path: Path) -> tuple[int, str, tuple[str, ...]]:
    pages, notes = extract_pdf_pages(path)
    return len(pages), "\n".join(page.text for page in pages), notes


def normalize_spaces(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value.replace("\xa0", " ")).strip()


def normalize_turkish(value: str) -> str:
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
    result = value
    for source, target in replacements.items():
        result = result.replace(source, target)
    return result.lower()


def normalize_for_search(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_turkish(value)).strip()


def _fold_party_text(value: str) -> str:
    translated = value.translate(
        {
            0x0131: "i",
            0x0130: "i",
            0x011F: "g",
            0x011E: "g",
            0x00FC: "u",
            0x00DC: "u",
            0x015F: "s",
            0x015E: "s",
            0x00F6: "o",
            0x00D6: "o",
            0x00E7: "c",
            0x00C7: "c",
        }
    )
    translated = unicodedata.normalize("NFKD", translated)
    translated = "".join(character for character in translated if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", translated.lower()).strip()


def parse_amount(raw: str) -> Decimal | None:
    compact = raw.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _parse_resolved_total(raw: str) -> Decimal | None:
    value = str(raw or "").strip()
    if "." in value and "," not in value and len(value.rsplit(".", 1)[-1]) == 2:
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return parse_amount(value)


def format_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def resolve_payable_total(parsed_totals: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    payable_total = str(parsed_totals.get("payable_total") or "").strip()
    if payable_total:
        return payable_total, ()

    tax_inclusive_total = _parse_resolved_total(str(parsed_totals.get("tax_inclusive_total") or ""))
    if tax_inclusive_total is None or tax_inclusive_total <= 0:
        return "", ()

    goods_total = _parse_resolved_total(str(parsed_totals.get("goods_services_total") or ""))
    vat_total = _parse_resolved_total(str(parsed_totals.get("vat_total") or ""))
    special_tax_total = _parse_resolved_total(str(parsed_totals.get("special_tax_total") or "")) or Decimal("0.00")
    if goods_total is not None and vat_total is not None:
        expected_total = goods_total + vat_total + special_tax_total
        if abs(expected_total - tax_inclusive_total) > Decimal("0.01"):
            return "", ()

    return format_decimal(tax_inclusive_total), ("payable_total_fallback_tax_inclusive_total",)


def normalize_date_match(match: re.Match[str]) -> str:
    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3))
    return f"{day:02d}.{month:02d}.{year}"


def extract_label_amount(text: str, labels: tuple[str, ...]) -> str:
    lines = text.splitlines()
    for label in labels:
        normalized_label = normalize_for_search(label)
        for index, line in enumerate(lines):
            if normalized_label not in normalize_for_search(line):
                continue
            current_amounts = [parse_amount(match.group(1)) for match in AMOUNT_RE.finditer(line)]
            current_amounts = [amount for amount in current_amounts if amount is not None]
            if current_amounts:
                return format_decimal(current_amounts[-1])
            window = " ".join(lines[index + 1 : index + 9])
            amounts = [parse_amount(match.group(1)) for match in AMOUNT_RE.finditer(window)]
            amounts = [amount for amount in amounts if amount is not None]
            if amounts:
                return format_decimal(amounts[-1])
    return ""


def extract_first_labeled_value(text: str, labels: tuple[str, ...], pattern: re.Pattern[str]) -> str:
    lines = text.splitlines()
    for label in labels:
        normalized_label = normalize_for_search(label)
        for index, line in enumerate(lines):
            if normalized_label not in normalize_for_search(line):
                continue
            window = " ".join(lines[index : index + 4])
            match = pattern.search(window)
            if match:
                return normalize_spaces(match.group(1))
    return ""


def extract_scenario(text: str) -> str:
    values = ("TEMELFATURA", "TICARIFATURA", "IHRACAT", "YOLCUBERABERFATURA")
    normalized = normalize_turkish(text)
    for value in values:
        if normalize_turkish(value) in normalized:
            return value
    return ""


def extract_invoice_type(text: str) -> str:
    type_labels = ("Fatura Tipi", "FATURA TİPİ", "Fatura\tTipi")
    value = extract_first_labeled_value(text, type_labels, re.compile(r"Fatura\s*Tipi\s*:?\s*([A-ZÇĞİÖŞÜa-zçğıöşü]+)", re.IGNORECASE))
    if value:
        return value.upper()
    for candidate in ("ISTISNA", "İSTİSNA", "SATIS", "SATIŞ", "IADE", "İADE", "TEVKIFAT", "TEVKİFAT"):
        if normalize_turkish(candidate) in normalize_turkish(text):
            return candidate.upper()
    return ""


def extract_issue_date(text: str) -> str:
    lines = text.splitlines()
    labels = ("fatura tarihi", "fatura dönemi / tarihi", "fatura donemi / tarihi")
    for index, line in enumerate(lines):
        normalized = normalize_for_search(line)
        if "sonraki fatura tarihi" in normalized or "bir sonraki fatura tarihi" in normalized:
            continue
        if not any(label in normalized for label in labels):
            continue
        window = " ".join(lines[index : index + 3])
        match = DATE_RE.search(window)
        if match:
            return normalize_date_match(match)
    match = DATE_RE.search(text)
    return normalize_date_match(match) if match else ""


def extract_invoice_no(text: str) -> str:
    labeled = extract_first_labeled_value(
        text,
        ("Fatura No", "FaturaNo", "Fatura Sıra No", "Fatura Sira No", "FATURA\tNO"),
        INVOICE_NO_RE,
    )
    if labeled:
        return labeled
    match = INVOICE_NO_RE.search(text)
    return match.group(1) if match else ""


def extract_ettn(text: str) -> str:
    match = ETTN_RE.search(text)
    return match.group(0) if match else ""


def extract_tax_ids(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(TAX_ID_RE.findall(text)))


def _tax_id_from_line(line: str) -> str:
    match = TAX_ID_RE.search(line)
    return match.group(1) if match else ""


def _tax_id_from_labeled_window(lines: list[str], index: int) -> str:
    direct = _tax_id_from_line(lines[index])
    if direct:
        return direct
    normalized = _fold_party_text(lines[index])
    if not any(label in normalized for label in ("vkn", "tckn", "vergi no", "tc kimlik")):
        return ""
    for candidate in lines[index + 1 : index + 4]:
        match = TAX_ID_VALUE_RE.search(candidate)
        if match:
            return match.group(1)
    return ""


def _is_non_party_tax_line(line: str) -> bool:
    normalized = _fold_party_text(line)
    return "tasiyici" in normalized


def _meaningful_party_line(line: str) -> bool:
    normalized = _fold_party_text(line)
    if not normalized:
        return False
    location_tokens = {
        "istanbul",
        "samsun",
        "bursa",
        "maltepe",
        "kagithane",
        "kartal",
        "tekkekoy",
        "nilufer",
        "kadikoy",
        "merkez",
    }
    address_tokens = (
        " mah",
        "cad",
        "sok",
        "no ",
        "no:",
        "kapi no",
        "adres",
        "sitesi",
        "web sitesi",
        "siparis tarihi",
        "yalniz",
    )
    if normalized in location_tokens or any(token in normalized for token in address_tokens):
        return False
    stop_tokens = (
        "vergi dairesi",
        "vkn",
        "tckn",
        "ettn",
        "fatura",
        "senaryo",
        "ozellestirme",
        "mal hizmet",
        "toplam",
        "kdv",
        "vergiler",
        "odenecek",
        "tel:",
        "tel ",
        "fax:",
        "fax ",
        "e-posta",
        "email",
        "web sitesi",
        "mersis",
        "musterino",
        "ticaret sicil",
    )
    return not any(token in normalized for token in stop_tokens)


def _party_title_score(line: str) -> int:
    normalized = _fold_party_text(line)
    company_tokens = (
        "limited",
        "ltd",
        "anonim",
        "a.s",
        "sirket",
        "ticaret",
        "sanayi",
        "hizmet",
        "magazacilik",
        "lojistik",
        "odyoloji",
        "medikal",
        "eczane",
        "market",
        "banka",
    )
    score = sum(3 for token in company_tokens if token in normalized)
    letters = [character for character in line if character.isalpha()]
    if letters and sum(1 for character in letters if character.isupper()) / len(letters) >= 0.65:
        score += 1
    return score


def _title_before_tax_line(lines: list[str], tax_line_index: int) -> str:
    window_start = max(0, tax_line_index - 24)
    candidates = [
        (index, line, _party_title_score(line))
        for index, line in enumerate(lines[window_start:tax_line_index], start=window_start)
        if _meaningful_party_line(line) and not any(character.isdigit() for character in line) and "/" not in line
    ]
    scored = [candidate for candidate in candidates if candidate[2] > 0]
    if scored:
        best_index, _, _ = max(scored, key=lambda item: (item[2], item[0]))
        selected_indexes = {best_index}
        for neighbor in (best_index - 1, best_index + 1):
            if neighbor < window_start or neighbor >= tax_line_index:
                continue
            line = lines[neighbor]
            if _meaningful_party_line(line) and not any(character.isdigit() for character in line) and "/" not in line:
                if _party_title_score(line) >= 3:
                    selected_indexes.add(neighbor)
        return " ".join(lines[index] for index in sorted(selected_indexes))[:120]

    parts: list[str] = []
    for _, line, _ in reversed(candidates):
        parts.append(line)
        if len(parts) >= 2:
            break
    return " ".join(reversed(parts))[:120]


def extract_recipient_title_from_text(text: str) -> str:
    lines = [normalize_spaces(line) for line in text.splitlines()]
    for index, line in enumerate(lines):
        normalized = normalize_for_search(line)
        if not normalized.startswith("sayin"):
            continue
        parts = line.split(maxsplit=1)
        title_parts: list[str] = []
        if len(parts) > 1 and _meaningful_party_line(parts[1]):
            title_parts.append(parts[1].strip(" :\t"))
        for next_line in lines[index + 1 : index + 6]:
            if _tax_id_from_line(next_line):
                break
            if _meaningful_party_line(next_line) and not any(character.isdigit() for character in next_line) and "/" not in next_line:
                title_parts.append(next_line)
            if len(title_parts) >= 2:
                break
        if title_parts:
            return " ".join(title_parts)[:120]
    return ""


def extract_pdf_party_details_from_text(text: str) -> tuple[str, str, str, str]:
    lines = [normalize_spaces(line) for line in text.splitlines()]
    sayin_index = next((index for index, line in enumerate(lines) if normalize_for_search(line).startswith("sayin")), -1)
    tax_lines = [
        (index, _tax_id_from_labeled_window(lines, index))
        for index, line in enumerate(lines)
        if not _is_non_party_tax_line(line)
    ]
    tax_lines = [(index, tax_id) for index, tax_id in tax_lines if tax_id]

    issuer_tax_id = ""
    issuer_title = ""
    recipient_tax_id = ""
    recipient_title = extract_recipient_title_from_text(text)

    if sayin_index >= 0:
        before_sayin = [(index, tax_id) for index, tax_id in tax_lines if index < sayin_index]
        after_sayin = [(index, tax_id) for index, tax_id in tax_lines if index > sayin_index]
        if after_sayin:
            recipient_tax_index, recipient_tax_id = after_sayin[0]
            if not recipient_title:
                recipient_title = _title_before_tax_line(lines, recipient_tax_index)
        if before_sayin:
            issuer_tax_index, issuer_tax_id = before_sayin[-1]
            issuer_title = _title_before_tax_line(lines, issuer_tax_index)
        elif len(after_sayin) > 1:
            issuer_tax_index, issuer_tax_id = after_sayin[-1]
            issuer_title = _title_before_tax_line(lines, issuer_tax_index)
    elif tax_lines:
        issuer_tax_index, issuer_tax_id = tax_lines[0]
        issuer_title = _title_before_tax_line(lines, issuer_tax_index)
        if len(tax_lines) > 1:
            recipient_tax_index, recipient_tax_id = tax_lines[1]
            recipient_title = _title_before_tax_line(lines, recipient_tax_index)

    return issuer_title, issuer_tax_id, recipient_title, recipient_tax_id


def extract_vat_rates(text: str) -> tuple[str, ...]:
    rates = set()
    for line in text.splitlines():
        normalized = normalize_for_search(line)
        if "kdv" not in normalized and "katma deger vergisi" not in normalized:
            continue
        for match in VAT_PERCENT_RE.finditer(line):
            rates.add(match.group(1))
    return tuple(sorted(rates, key=lambda item: int(item)))


def extract_seller_hint(text: str) -> str:
    company_tokens = (
        "ltd",
        "limited",
        "anonim",
        "a.ş",
        "a.s",
        "şirket",
        "sirket",
        "ticaret",
        "mağazacılık",
        "magazacilik",
        "odyoloji",
    )
    lines = [normalize_spaces(line) for line in text.splitlines() if normalize_spaces(line)]
    for index, line in enumerate(lines):
        normalized = normalize_for_search(line)
        if not any(token in normalized for token in company_tokens):
            continue
        parts = [line]
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            candidate_normalized = normalize_for_search(candidate)
            if any(
                stop in candidate_normalized
                for stop in ("vergi dairesi", "vkn", "tckn", "ettn", "sayin", " mah", " cad", " sok", " no:")
            ):
                break
            if candidate in {"/", "No:", "Kapı No:"} or re.search(r"\d", candidate):
                break
            if len(parts) >= 3:
                break
            if len(candidate.split()) <= 6:
                parts.append(candidate)
            cursor += 1
        return normalize_spaces(" ".join(parts))
    return ""


def build_route(risk_flags: tuple[str, ...], parsed: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    notes: list[str] = []
    if not parsed["invoice_no"]:
        notes.append("missing_invoice_no")
    if not parsed["issue_date"]:
        notes.append("missing_issue_date")
    if not parsed["payable_total"]:
        notes.append("missing_payable_total")
    if notes:
        return "review_queue", tuple(notes)
    if risk_flags:
        return "review_queue", tuple(notes)
    return "journal_candidate", tuple(notes)


def _canonical_line_from_invoice_line(line: InvoiceLine) -> CanonicalInvoiceLine:
    return CanonicalInvoiceLine(
        description=line.description,
        source_position=line.source_position or line.source,
        taxable_amount=line.taxable_amount,
        vat_rate=line.vat_rate,
        tax_amount=line.tax_amount,
        gross_amount=line.gross_amount or line.amount_hint,
        evidence=(line.source or "pdf_text",),
    )


def build_pdf_canonical_invoice(
    *,
    issuer_title: str,
    issuer_tax_id: str,
    recipient_title: str,
    recipient_tax_id: str,
    invoice_no: str,
    issue_date: str,
    ettn: str,
    scenario: str,
    invoice_type: str,
    line_item_details: tuple[InvoiceLine, ...],
    vat_split_lines: tuple[VatSplitLine, ...],
    parsed_totals: dict[str, str],
    ai_used: bool = False,
    extraction_notes: tuple[str, ...] = (),
) -> CanonicalInvoice:
    invoice = CanonicalInvoice(
        source="pdf_text",
        supplier_party=CanonicalInvoiceParty(
            title=issuer_title,
            tax_id=issuer_tax_id,
            evidence=("pdf_party:issuer",) if issuer_title or issuer_tax_id else (),
        ),
        customer_party=CanonicalInvoiceParty(
            title=recipient_title,
            tax_id=recipient_tax_id,
            evidence=("pdf_party:recipient",) if recipient_title or recipient_tax_id else (),
        ),
        header=CanonicalInvoiceHeader(
            invoice_no=invoice_no,
            issue_date=issue_date,
            ettn=ettn,
            scenario=scenario,
            invoice_type=invoice_type,
            evidence=("pdf_header",),
        ),
        line_items=tuple(_canonical_line_from_invoice_line(line) for line in line_item_details),
        vat_summary=tuple(
            CanonicalVatSummaryLine(
                rate=line.rate,
                taxable_amount=line.taxable_amount,
                tax_amount=line.tax_amount,
                evidence=line.evidence or (line.source,),
            )
            for line in vat_split_lines
        ),
        totals=CanonicalInvoiceTotals(
            goods_services_total=parsed_totals.get("goods_services_total", ""),
            vat_total=parsed_totals.get("vat_total", ""),
            special_tax_total=parsed_totals.get("special_tax_total", ""),
            tax_inclusive_total=parsed_totals.get("tax_inclusive_total", ""),
            payable_total=parsed_totals.get("payable_total", ""),
            evidence=("pdf_totals",),
        ),
        ai_used=ai_used,
        extraction_notes=extraction_notes,
    )
    return with_validation(invoice)


def _recover_single_declared_pdf_vat_group(
    lines: tuple[InvoiceLine, ...],
    vat_split_lines: tuple[VatSplitLine, ...],
) -> tuple[InvoiceLine, ...]:
    if len(vat_split_lines) != 1:
        return lines
    declared = vat_split_lines[0]
    try:
        declared_rate = Decimal(declared.rate)
    except (InvalidOperation, ValueError):
        return lines

    recovered: list[InvoiceLine] = []
    for line in lines:
        if line.vat_rate or not line.taxable_amount:
            recovered.append(line)
            continue
        try:
            taxable = parse_invoice_money(line.taxable_amount)
        except ValueError:
            recovered.append(line)
            continue
        tax = (taxable * declared_rate / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        recovered.append(
            replace(
                line,
                vat_rate=f"{declared_rate.normalize():f}",
                tax_amount=format_decimal(tax),
                gross_amount=format_decimal(taxable + tax),
            )
        )
    return tuple(recovered)


def _money_values_from_pdf_text(value: str) -> tuple[Decimal, ...]:
    parsed: list[Decimal] = []
    for candidate in PDF_LINE_MONEY_RE.findall(value):
        try:
            parsed.append(parse_invoice_money(candidate))
        except ValueError:
            continue
    return tuple(parsed)


def recover_missing_pdf_group_lines(
    *,
    pages: tuple[PdfPageText, ...],
    lines: tuple[InvoiceLine, ...],
    vat_split_lines: tuple[VatSplitLine, ...],
) -> tuple[InvoiceLine, ...]:
    qualified = tuple(
        line
        for line in lines
        if line.source_position and line.vat_rate and line.taxable_amount
    )
    if len(vat_split_lines) != 1:
        return qualified

    declared = vat_split_lines[0]
    try:
        declared_rate = Decimal(declared.rate)
        declared_taxable = parse_invoice_money(declared.taxable_amount)
        declared_tax = parse_invoice_money(declared.tax_amount)
    except (InvalidOperation, ValueError):
        return qualified

    covered_taxable = Decimal("0.00")
    for line in qualified:
        try:
            if Decimal(line.vat_rate) == declared_rate:
                covered_taxable += parse_invoice_money(line.taxable_amount)
        except (InvalidOperation, ValueError):
            continue
    if covered_taxable == declared_taxable:
        return qualified
    if covered_taxable:
        return qualified

    page_rows = tuple(
        (
            page.page_no,
            tuple(
                normalize_spaces(row)
                for row in page.text.splitlines()
                if normalize_spaces(row)
            ),
        )
        for page in pages
    )
    evidence: tuple[int, int, str] | None = None
    for page_no, rows in page_rows:
        for index, row in enumerate(rows):
            normalized = normalize_for_search(row)
            values = _money_values_from_pdf_text(row)
            next_values = (
                _money_values_from_pdf_text(rows[index + 1])
                if index + 1 < len(rows)
                else ()
            )
            if "matrah" in normalized and declared_taxable in (*values, *next_values):
                evidence = (
                    page_no,
                    index + 1,
                    f"KDV matrahı (%{declared.rate}) - toplu kaynak satırı",
                )
                break
        if evidence:
            break

    # Some supported layouts provide one declared KDV group and put the
    # matching taxable amount directly below a meaningful service label.
    # This fallback is considered only when no explicit matrah row exists.
    if not evidence:
        for page_no, rows in page_rows:
            for index, row in enumerate(rows):
                normalized = normalize_for_search(row)
                next_values = (
                    _money_values_from_pdf_text(rows[index + 1])
                    if index + 1 < len(rows)
                    else ()
                )
                if index + 1 >= len(rows) or declared_taxable not in next_values:
                    continue
                if any(
                    token in normalized
                    for token in ("kdv", "vergi", "matrah", "toplam", "odenecek", "ödenecek")
                ):
                    continue
                if len(row) < 5 or any(character.isdigit() for character in row):
                    continue
                evidence = (page_no, index + 1, row[:120])
                break
            if evidence:
                break

    if not evidence:
        return qualified
    page_no, line_no, description = evidence
    gross = declared_taxable + declared_tax
    return (
        *qualified,
        InvoiceLine(
            raw_text=description,
            description=description,
            amount_hint=format_decimal(gross),
            source=f"pdf:page:{page_no}:text:line:{line_no}",
            source_position=f"pdf:page:{page_no}:text:line:{line_no}",
            vat_rate=f"{declared_rate.normalize():f}",
            taxable_amount=format_decimal(declared_taxable),
            tax_amount=format_decimal(declared_tax),
            gross_amount=format_decimal(gross),
        ),
    )


def _pdf_canonical_ai_payload(
    *,
    canonical_invoice: CanonicalInvoice,
    parsed_identity: dict[str, str],
    parsed_totals: dict[str, str],
    line_item_details: tuple[InvoiceLine, ...],
    vat_split: object,
) -> dict[str, object]:
    return {
        "invoice_no": parsed_identity.get("invoice_no", ""),
        "issue_date": parsed_identity.get("issue_date", ""),
        "line_count": len(line_item_details),
        "validation_status": canonical_invoice.validation.status,
        "validation_reasons": list(canonical_invoice.validation.reason_codes),
        "totals": dict(parsed_totals),
        "vat_split_status": str(getattr(vat_split, "status", "") or ""),
        "vat_summary": [
            {
                "rate": line.rate,
                "taxable_amount": line.taxable_amount,
                "tax_amount": line.tax_amount,
                "source": line.source,
            }
            for line in getattr(vat_split, "lines", ()) or ()
        ],
        "line_items": [
            {
                "canonical_line_id": line.canonical_line_id,
                "source_position": line.source_position,
                "description": line.description,
                "vat_rate": line.vat_rate,
                "taxable_amount": line.taxable_amount,
                "tax_amount": line.tax_amount,
                "gross_amount": line.gross_amount,
            }
            for line in canonical_invoice.line_items
        ],
    }


def _bind_ai_payload_to_deterministic_lines(
    payload: Mapping[str, object],
    deterministic: CanonicalInvoice,
) -> dict[str, object]:
    def values_differ(field_name: str, trusted_value: object, observed_value: object) -> bool:
        if field_name != "observed_unit_code":
            trusted_decimal = _parse_resolved_total(str(trusted_value or ""))
            observed_decimal = _parse_resolved_total(str(observed_value or ""))
            if trusted_decimal is not None and observed_decimal is not None:
                return abs(trusted_decimal - observed_decimal) > Decimal("0.001")
        return " ".join(str(trusted_value or "").strip().split()).casefold() != " ".join(
            str(observed_value or "").strip().split()
        ).casefold()

    trusted_by_id = {
        line.canonical_line_id: line
        for line in deterministic.line_items
        if line.canonical_line_id
    }
    raw_items = payload.get("line_items")
    if not isinstance(raw_items, (list, tuple)):
        raise ValueError("canonical AI response must echo deterministic line identities")
    received_ids = [
        str(item.get("canonical_line_id") or "")
        for item in raw_items
        if isinstance(item, Mapping)
    ]
    if (
        len(received_ids) != len(trusted_by_id)
        or len(set(received_ids)) != len(received_ids)
        or set(received_ids) != set(trusted_by_id)
    ):
        raise ValueError("canonical AI response line identity coverage is invalid")
    bound_items: list[dict[str, object]] = []
    extraction_notes = [str(note) for note in payload.get("extraction_notes") or () if str(note).strip()]
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ValueError("canonical AI response contains a non-object line")
        echoed_id = str(item.get("canonical_line_id") or "")
        trusted = trusted_by_id[echoed_id]
        observed_values = {
            "observed_quantity": item.get("observed_quantity") or item.get("quantity") or "",
            "observed_unit_code": item.get("observed_unit_code") or item.get("unit_code") or "",
            "observed_unit_price": item.get("observed_unit_price") or item.get("unit_price") or "",
            "observed_taxable_amount": item.get("observed_taxable_amount") or item.get("taxable_amount") or "",
            "observed_vat_rate": item.get("observed_vat_rate") or item.get("vat_rate") or "",
            "observed_tax_amount": item.get("observed_tax_amount") or item.get("tax_amount") or "",
            "observed_gross_amount": item.get("observed_gross_amount") or item.get("gross_amount") or "",
        }
        trusted_values = {
            "observed_quantity": trusted.quantity,
            "observed_unit_code": trusted.unit_code,
            "observed_unit_price": trusted.unit_price,
            "observed_taxable_amount": trusted.taxable_amount,
            "observed_vat_rate": trusted.vat_rate,
            "observed_tax_amount": trusted.tax_amount,
            "observed_gross_amount": trusted.gross_amount,
        }
        for field_name, trusted_value in trusted_values.items():
            observed_value = str(observed_values[field_name] or "").strip()
            if trusted_value and observed_value and values_differ(field_name, trusted_value, observed_value):
                extraction_notes.append(f"{field_name}_conflict")
            if trusted_value:
                observed_values[field_name] = trusted_value
        bound_items.append(
            {
                **dict(item),
                **observed_values,
                "canonical_line_id": echoed_id,
                "source_position": trusted.source_position,
                "external_line_id": "",
                "description": trusted.description or str(item.get("description") or ""),
                "evidence": list(
                    dict.fromkeys(
                        (
                            *trusted.evidence,
                            *tuple(str(value) for value in item.get("evidence") or () if str(value).strip()),
                            trusted.source_position,
                        )
                    )
                ),
            }
        )
    return {
        **dict(payload),
        "line_items": bound_items,
        "extraction_notes": list(dict.fromkeys(extraction_notes)),
    }


def _canonical_extraction_mode(deterministic: CanonicalInvoice) -> str:
    discovery_reasons = {
        "line_items_missing",
        "line_total_mismatch",
        "gross_total_mismatch",
        "line_gross_total_mismatch",
    }
    return "discovery" if discovery_reasons.intersection(deterministic.validation.reason_codes) else "repair"


def _bind_ai_discovery_payload(payload: Mapping[str, object]) -> dict[str, object]:
    raw_items = payload.get("line_items")
    if not isinstance(raw_items, (list, tuple)) or not raw_items:
        raise ValueError("canonical AI discovery requires at least one source line")
    bound_items: list[dict[str, object]] = []
    source_positions: list[str] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ValueError("canonical AI discovery contains a non-object line")
        source_position = " ".join(str(item.get("source_position") or "").strip().split())
        description = " ".join(str(item.get("description") or "").strip().split())
        if not source_position or not description:
            raise ValueError("canonical AI discovery requires description and source_position")
        source_positions.append(source_position.casefold())
        bound_items.append(
            {
                **dict(item),
                "canonical_line_id": "",
                "external_line_id": "",
                "source_position": source_position,
                "description": description,
                "evidence": list(
                    dict.fromkeys(
                        (
                            *tuple(str(value) for value in item.get("evidence") or () if str(value).strip()),
                            source_position,
                        )
                    )
                ),
            }
        )
    if len(set(source_positions)) != len(source_positions):
        raise ValueError("canonical AI discovery source positions must be unique")
    return {
        **dict(payload),
        "line_items": bound_items,
        "extraction_notes": list(
            dict.fromkeys(
                (
                    *tuple(str(note) for note in payload.get("extraction_notes") or () if str(note).strip()),
                    "provider_line_identity_discarded",
                )
            )
        ),
    }


def _apply_deterministic_canonical_arithmetic(
    candidate: CanonicalInvoice,
    deterministic: CanonicalInvoice,
) -> CanonicalInvoice:
    authoritative_total = _parse_resolved_total(
        deterministic.totals.payable_total
        or deterministic.totals.tax_inclusive_total
        or candidate.totals.payable_total
        or candidate.totals.tax_inclusive_total
    )
    if authoritative_total is None or authoritative_total <= 0 or not candidate.line_items:
        return candidate

    special_tax = _parse_resolved_total(
        deterministic.totals.special_tax_total or candidate.totals.special_tax_total
    ) or Decimal("0.00")
    taxable_total = Decimal("0.00")
    vat_total = Decimal("0.00")
    vat_groups: dict[Decimal, tuple[Decimal, Decimal]] = {}
    reconciled_lines: list[CanonicalInvoiceLine] = []
    mismatch_notes: list[str] = []
    for line in candidate.line_items:
        taxable = _parse_resolved_total(line.taxable_amount)
        rate = _parse_resolved_total(line.vat_rate)
        if taxable is None or rate is None or taxable < 0 or rate < 0:
            return candidate
        tax = (taxable * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        gross = (taxable + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        observed_tax = _parse_resolved_total(line.tax_amount)
        observed_gross = _parse_resolved_total(line.gross_amount)
        if observed_tax is not None and abs(observed_tax - tax) > Decimal("0.05"):
            mismatch_notes.append("observed_tax_amount_mismatch")
        if observed_gross is not None and abs(observed_gross - gross) > Decimal("0.05"):
            mismatch_notes.append("observed_gross_amount_mismatch")
        taxable_total += taxable
        vat_total += tax
        group_taxable, group_tax = vat_groups.get(rate, (Decimal("0.00"), Decimal("0.00")))
        vat_groups[rate] = (group_taxable + taxable, group_tax + tax)
        reconciled_lines.append(
            replace(
                line,
                taxable_amount=format_decimal(taxable),
                vat_rate=f"{rate.normalize():f}",
                tax_amount=format_decimal(tax),
                gross_amount=format_decimal(gross),
            )
        )

    taxable_total = taxable_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    vat_total = vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    derived_total = (taxable_total + vat_total + special_tax).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    observed_goods_total = _parse_resolved_total(candidate.totals.goods_services_total)
    observed_vat_total = _parse_resolved_total(candidate.totals.vat_total)
    observed_tax_inclusive_total = _parse_resolved_total(candidate.totals.tax_inclusive_total)
    observed_payable_total = _parse_resolved_total(candidate.totals.payable_total)
    if observed_goods_total is not None and abs(observed_goods_total - taxable_total) > Decimal("0.05"):
        mismatch_notes.append("observed_goods_services_total_mismatch")
    if observed_vat_total is not None and abs(observed_vat_total - vat_total) > Decimal("0.05"):
        mismatch_notes.append("observed_vat_total_mismatch")
    if (
        observed_tax_inclusive_total is not None
        and abs(observed_tax_inclusive_total - derived_total) > Decimal("0.05")
    ):
        mismatch_notes.append("observed_tax_inclusive_total_mismatch")
    if observed_payable_total is not None and abs(observed_payable_total - authoritative_total) > Decimal("0.05"):
        mismatch_notes.append("observed_payable_total_mismatch")
    for observed_summary in candidate.vat_summary:
        observed_rate = _parse_resolved_total(observed_summary.rate)
        observed_summary_taxable = _parse_resolved_total(observed_summary.taxable_amount)
        observed_summary_tax = _parse_resolved_total(observed_summary.tax_amount)
        derived_group = vat_groups.get(observed_rate) if observed_rate is not None else None
        if derived_group is None or (
            observed_summary_taxable is not None
            and abs(observed_summary_taxable - derived_group[0]) > Decimal("0.05")
        ) or (
            observed_summary_tax is not None
            and abs(observed_summary_tax - derived_group[1]) > Decimal("0.05")
        ):
            mismatch_notes.append("observed_vat_summary_mismatch")
            break
    if abs(derived_total - authoritative_total) > Decimal("0.05"):
        return replace(
            candidate,
            validation=CanonicalInvoiceValidation(
                status="invalid",
                reason_codes=tuple(
                    dict.fromkeys((*candidate.validation.reason_codes, "deterministic_document_total_mismatch"))
                ),
                evidence=candidate.validation.evidence,
            ),
            extraction_notes=tuple(
                dict.fromkeys(
                    (
                        *candidate.extraction_notes,
                        *mismatch_notes,
                        "deterministic_document_total_mismatch",
                    )
                )
            ),
        )

    reconciled = replace(
        candidate,
        line_items=tuple(reconciled_lines),
        vat_summary=tuple(
            CanonicalVatSummaryLine(
                rate=f"{rate.normalize():f}",
                taxable_amount=format_decimal(group_taxable),
                tax_amount=format_decimal(group_tax),
                evidence=("deterministic_arithmetic_from_ai_lines",),
            )
            for rate, (group_taxable, group_tax) in sorted(vat_groups.items())
        ),
        totals=CanonicalInvoiceTotals(
            goods_services_total=format_decimal(taxable_total),
            vat_total=format_decimal(vat_total),
            special_tax_total=format_decimal(special_tax),
            tax_inclusive_total=format_decimal(derived_total),
            payable_total=format_decimal(authoritative_total),
            evidence=tuple(
                dict.fromkeys(
                    (*candidate.totals.evidence, "deterministic_arithmetic_from_document_total")
                )
            ),
        ),
        extraction_notes=tuple(
            dict.fromkeys(
                (
                    *candidate.extraction_notes,
                    *mismatch_notes,
                    "canonical_deterministic_arithmetic_applied",
                )
            )
        ),
    )
    return with_validation(reconciled)


def _merge_source_grounded_partial_recovery(
    deterministic: CanonicalInvoice,
    candidate: CanonicalInvoice,
) -> CanonicalInvoice | None:
    deterministic_missing = set(
        _pdf_canonical_extraction_outcome(deterministic).missing_vat_group_ids
    )
    candidate_missing = set(
        _pdf_canonical_extraction_outcome(candidate).missing_vat_group_ids
    )
    recovered_group_ids = deterministic_missing - candidate_missing
    if not recovered_group_ids:
        return None

    existing_positions = {
        line.source_position.casefold()
        for line in deterministic.line_items
        if line.source_position
    }
    recovered_lines = tuple(
        line
        for line in candidate.line_items
        if line.vat_group_id in recovered_group_ids
        and line.source_position
        and line.source_position.casefold() not in existing_positions
    )
    if not recovered_lines:
        return None

    return with_validation(
        replace(
            deterministic,
            line_items=(*deterministic.line_items, *recovered_lines),
            ai_used=True,
            extraction_notes=tuple(
                dict.fromkeys(
                    (
                        *deterministic.extraction_notes,
                        *candidate.extraction_notes,
                        "canonical_ai_used",
                        "canonical_ai_partial_recovery_used",
                    )
                )
            ),
        )
    )


def _maybe_complete_canonical_with_ai(
    *,
    provider: object | None,
    policy: CanonicalExtractionPolicy | None,
    document_text: str,
    deterministic: CanonicalInvoice,
    parsed_identity: dict[str, str],
    parsed_totals: dict[str, str],
    line_item_details: tuple[InvoiceLine, ...],
    vat_split: object,
    client_identity: dict[str, object] | None,
) -> CanonicalInvoice:
    effective_policy = policy or CanonicalExtractionPolicy()
    if (
        provider is None
        or not effective_policy.enabled
        or effective_policy.max_provider_calls <= 0
        or deterministic.validation.status == "valid"
    ):
        return deterministic
    extractor = getattr(provider, "extract_invoice_canonical", None)
    if extractor is None:
        return deterministic
    mode = _canonical_extraction_mode(deterministic)
    try:
        payload = extractor(
            CanonicalExtractionRequest(
                document_text=document_text,
                deterministic_payload=_pdf_canonical_ai_payload(
                    canonical_invoice=deterministic,
                    parsed_identity=parsed_identity,
                    parsed_totals=parsed_totals,
                    line_item_details=line_item_details,
                    vat_split=vat_split,
                ),
                client_identity=client_identity or {},
                max_input_chars=effective_policy.max_input_chars,
                mode=mode,
            )
        )
        bound_payload = (
            _bind_ai_discovery_payload(payload)
            if mode == "discovery"
            else _bind_ai_payload_to_deterministic_lines(payload, deterministic)
        )
        candidate = canonical_invoice_from_ai_payload(bound_payload)
        candidate = with_validation(
            replace(
                candidate,
                source=deterministic.source,
            )
        )
    except Exception as exc:  # noqa: BLE001 - parser fallback must keep deterministic extraction
        return replace(
            deterministic,
            extraction_notes=tuple(
                dict.fromkeys(
                    (
                        *deterministic.extraction_notes,
                        *(('canonical_ai_discovery_rejected',) if mode == "discovery" else ()),
                        f"canonical_ai_error:{type(exc).__name__}",
                    )
                )
            ),
        )
    if mode == "repair":
        line_coverage = validate_line_decision_coverage(
            deterministic.line_items,
            [
                {"canonical_line_id": line.canonical_line_id}
                for line in candidate.line_items
            ],
        )
        if line_coverage.status != "valid":
            return replace(
                deterministic,
                extraction_notes=tuple(
                    dict.fromkeys(
                        (
                            *deterministic.extraction_notes,
                            "canonical_ai_rejected",
                            "canonical_line_coverage_invalid",
                        )
                    )
                ),
            )
    candidate = _apply_deterministic_canonical_arithmetic(candidate, deterministic)
    if mode == "discovery" and deterministic.vat_summary:
        candidate = with_validation(
            replace(
                candidate,
                header=deterministic.header,
                vat_summary=deterministic.vat_summary,
                totals=deterministic.totals,
            )
        )
    if candidate.validation.status == "valid":
        return replace(
            candidate,
            header=deterministic.header,
            ai_used=True,
            extraction_notes=tuple(
                dict.fromkeys(
                    (
                        *deterministic.extraction_notes,
                        *candidate.extraction_notes,
                        "canonical_ai_used",
                        *(('canonical_ai_discovery_used',) if mode == "discovery" else ('canonical_ai_repair_used',)),
                    )
                )
            ),
        )
    partial_recovery = (
        _merge_source_grounded_partial_recovery(deterministic, candidate)
        if mode == "discovery"
        else None
    )
    if partial_recovery is not None:
        return partial_recovery
    return replace(
        deterministic,
        extraction_notes=tuple(
            dict.fromkeys(
                (
                    *deterministic.extraction_notes,
                    "canonical_ai_rejected",
                    *(('canonical_ai_discovery_rejected',) if mode == "discovery" else ()),
                    *candidate.validation.reason_codes,
                )
            )
        ),
    )


def parse_pdf_invoice(
    path: Path,
    *,
    canonical_extraction_provider: object | None = None,
    canonical_extraction_policy: CanonicalExtractionPolicy | None = None,
    client_identity: dict[str, object] | None = None,
) -> ParsedInvoice:
    pages, extraction_notes = extract_pdf_pages(path)
    page_count = len(pages)
    text = "\n".join(page.text for page in pages)
    stripped_text = text.strip()
    if page_count > 0 and not stripped_text:
        return ParsedInvoice(
            file_name=path.name,
            provider_hint="",
            page_count=page_count,
            text_extractable=False,
            extracted_char_count=0,
            scenario="",
            invoice_type="",
            invoice_no="",
            ettn="",
            issue_date="",
            tax_ids=(),
            vat_rates=(),
            goods_services_total="",
            vat_total="",
            special_tax_total="",
            tax_inclusive_total="",
            payable_total="",
            risk_flags=("scanned_pdf_unsupported",),
            suggested_route="review_queue",
            parse_notes=tuple(dict.fromkeys((*extraction_notes, "scanned_pdf_unsupported"))),
        )
    boundary = detect_multiple_invoice_identities(pages)
    if boundary.status == "confirmed_multiple":
        return ParsedInvoice(
            file_name=path.name,
            provider_hint="",
            page_count=page_count,
            text_extractable=len(stripped_text) >= 100,
            extracted_char_count=len(stripped_text),
            scenario="",
            invoice_type="",
            invoice_no="",
            ettn="",
            issue_date="",
            tax_ids=(),
            vat_rates=(),
            goods_services_total="",
            vat_total="",
            special_tax_total="",
            tax_inclusive_total="",
            payable_total="",
            risk_flags=("multi_invoice_container_confirmed",),
            suggested_route="review_queue",
            parse_notes=(*extraction_notes, "separate_invoice_upload_required"),
        )
    edge_summary = summarize_invoice_edge_cases(path.name, text, extracted_char_count=len(stripped_text))
    parsed_totals = {
        key: extract_label_amount(text, labels)
        for key, labels in TOTAL_LABELS.items()
    }
    vat_split = extract_pdf_vat_split(path)
    if vat_split.status in {"exact", "derived"}:
        if vat_split.total_taxable_amount:
            parsed_totals["goods_services_total"] = vat_split.total_taxable_amount
        if vat_split.total_tax_amount:
            parsed_totals["vat_total"] = vat_split.total_tax_amount
        if vat_split.tax_inclusive_total:
            parsed_totals["tax_inclusive_total"] = vat_split.tax_inclusive_total
        if vat_split.payable_total:
            parsed_totals["payable_total"] = vat_split.payable_total
    payable_total, payable_notes = resolve_payable_total(parsed_totals)
    parsed_identity = {
        "invoice_no": extract_invoice_no(text) or edge_summary.invoice_no,
        "issue_date": extract_issue_date(text),
        "payable_total": payable_total,
    }
    route, route_notes = build_route(edge_summary.risk_flags, parsed_identity)
    line_item_details = recover_missing_pdf_group_lines(
        pages=pages,
        lines=_recover_single_declared_pdf_vat_group(
            extract_invoice_lines_from_pages(pages, max_lines=200),
            vat_split.lines,
        ),
        vat_split_lines=vat_split.lines,
    )
    line_items = invoice_line_hints(line_item_details)
    issuer_title, issuer_tax_id, recipient_title, recipient_tax_id = extract_pdf_party_details_from_text(text)
    invoice_type = extract_invoice_type(text)
    scenario = extract_scenario(text)
    invoice_no = parsed_identity["invoice_no"]
    ettn = extract_ettn(text) or edge_summary.ettn
    canonical_invoice = build_pdf_canonical_invoice(
        issuer_title=issuer_title or extract_seller_hint(text) or edge_summary.provider_hint,
        issuer_tax_id=issuer_tax_id,
        recipient_title=recipient_title,
        recipient_tax_id=recipient_tax_id,
        invoice_no=invoice_no,
        issue_date=parsed_identity["issue_date"],
        ettn=ettn,
        scenario=scenario,
        invoice_type=invoice_type,
        line_item_details=line_item_details,
        vat_split_lines=vat_split.lines,
        parsed_totals=parsed_totals,
        extraction_notes=tuple(dict.fromkeys((*extraction_notes, *route_notes, *payable_notes))),
    )
    canonical_invoice = _maybe_complete_canonical_with_ai(
        provider=canonical_extraction_provider,
        policy=canonical_extraction_policy,
        document_text=text,
        deterministic=canonical_invoice,
        parsed_identity=parsed_identity,
        parsed_totals=parsed_totals,
        line_item_details=line_item_details,
        vat_split=vat_split,
        client_identity=client_identity,
    )
    canonical_outcome = _pdf_canonical_extraction_outcome(
        canonical_invoice,
        attempts=(
            "deterministic",
            *(("source_grounded_ai",) if canonical_invoice.ai_used else ()),
        ),
    )
    if not canonical_outcome.complete:
        raise SupportedPdfExtractionError(canonical_outcome.missing_vat_group_ids)
    provider_title = issuer_title or extract_seller_hint(text) or edge_summary.provider_hint
    provider_match = resolve_provider_profile(
        supplier_tax_id=issuer_tax_id,
        supplier_title=provider_title,
        source="pdf",
    )
    return ParsedInvoice(
        file_name=path.name,
        provider_hint=provider_title,
        page_count=page_count,
        text_extractable=len(stripped_text) >= 100,
        extracted_char_count=len(stripped_text),
        scenario=scenario,
        invoice_type=invoice_type,
        invoice_no=invoice_no,
        ettn=ettn,
        issue_date=parsed_identity["issue_date"],
        tax_ids=extract_tax_ids(text),
        vat_rates=extract_vat_rates(text),
        goods_services_total=parsed_totals["goods_services_total"],
        vat_total=parsed_totals["vat_total"],
        special_tax_total=parsed_totals["special_tax_total"],
        tax_inclusive_total=parsed_totals["tax_inclusive_total"],
        payable_total=payable_total,
        risk_flags=edge_summary.risk_flags,
        suggested_route=route,
        parse_notes=tuple(dict.fromkeys((*extraction_notes, *route_notes, *payable_notes))),
        line_items=line_items,
        line_item_details=line_item_details,
        issuer_title=provider_title,
        issuer_tax_id=issuer_tax_id,
        recipient_title=recipient_title,
        recipient_tax_id=recipient_tax_id,
        invoice_type_code=invoice_type,
        is_return_invoice=normalize_for_search(invoice_type) in {"iade", "return"},
        vat_split_status=vat_split.status,
        vat_split_lines=vat_split.lines,
        vat_split_evidence=vat_split.evidence,
        canonical_invoice=canonical_invoice,
        provider_id=provider_match.provider_id,
        service_profile=provider_match.service_profile,
        provider_match_kind=provider_match.match_kind,
        provider_match_reason=provider_match.reason_code,
        provider_directory_version=provider_match.directory_version,
    )


def parse_invoice_folder(
    input_dir: Path,
    *,
    canonical_extraction_provider: object | None = None,
    canonical_extraction_policy: CanonicalExtractionPolicy | None = None,
    client_identity: dict[str, object] | None = None,
) -> list[ParsedInvoice]:
    files = sorted(input_dir.rglob("*.pdf"), key=lambda item: item.name.lower())
    return [
        parse_pdf_invoice(
            path,
            canonical_extraction_provider=canonical_extraction_provider,
            canonical_extraction_policy=canonical_extraction_policy,
            client_identity=client_identity,
        )
        for path in files
    ]


def write_invoice_analysis_csv(invoices: list[ParsedInvoice], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(invoices[0]).keys()) if invoices else [])
        if invoices:
            writer.writeheader()
            for invoice in invoices:
                row = asdict(invoice)
                row["tax_ids"] = ";".join(invoice.tax_ids)
                row["vat_rates"] = ";".join(invoice.vat_rates)
                row["risk_flags"] = ";".join(invoice.risk_flags)
                row["parse_notes"] = ";".join(invoice.parse_notes)
                row["line_items"] = ";".join(invoice.line_items)
                writer.writerow(row)
    return output_path


def write_invoice_analysis_json(invoices: list[ParsedInvoice], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = []
    for invoice in invoices:
        row = asdict(invoice)
        payload.append(row)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
