from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.domain.canonical_invoices import (
    CanonicalInvoice,
    CanonicalExtractionPolicy,
    CanonicalExtractionRequest,
    CanonicalInvoiceHeader,
    CanonicalInvoiceLine,
    CanonicalInvoiceParty,
    CanonicalInvoiceTotals,
    CanonicalVatSummaryLine,
    canonical_invoice_from_ai_payload,
    with_validation,
)
from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_lines import InvoiceLine, extract_invoice_lines_from_text, invoice_line_hints
from app.domain.vat_splits import VatSplitLine, extract_pdf_vat_split


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


def extract_pdf_text(path: Path) -> tuple[int, str, tuple[str, ...]]:
    notes: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return 0, "", ("pypdf_not_installed",)

    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return len(reader.pages), "\n".join(chunks), tuple(notes)
    except Exception as exc:  # noqa: BLE001
        return 0, "", (f"pdf_read_error:{type(exc).__name__}",)


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
                "description": line.description,
                "vat_rate": line.vat_rate,
                "taxable_amount": line.taxable_amount,
                "tax_amount": line.tax_amount,
                "gross_amount": line.gross_amount,
            }
            for line in line_item_details
        ],
    }


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
            )
        )
        candidate = canonical_invoice_from_ai_payload(payload)
    except Exception as exc:  # noqa: BLE001 - parser fallback must keep deterministic extraction
        return replace(
            deterministic,
            extraction_notes=tuple(dict.fromkeys((*deterministic.extraction_notes, f"canonical_ai_error:{type(exc).__name__}"))),
        )
    if candidate.validation.status == "valid":
        return replace(
            candidate,
            header=deterministic.header,
            extraction_notes=tuple(dict.fromkeys((*deterministic.extraction_notes, "canonical_ai_used"))),
        )
    return replace(
        deterministic,
        extraction_notes=tuple(
            dict.fromkeys(
                (
                    *deterministic.extraction_notes,
                    "canonical_ai_rejected",
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
    page_count, text, extraction_notes = extract_pdf_text(path)
    stripped_text = text.strip()
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
    line_item_details = extract_invoice_lines_from_text(text)
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
    return ParsedInvoice(
        file_name=path.name,
        provider_hint=issuer_title or extract_seller_hint(text) or edge_summary.provider_hint,
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
        issuer_title=issuer_title or extract_seller_hint(text) or edge_summary.provider_hint,
        issuer_tax_id=issuer_tax_id,
        recipient_title=recipient_title,
        recipient_tax_id=recipient_tax_id,
        invoice_type_code=invoice_type,
        is_return_invoice=normalize_for_search(invoice_type) in {"iade", "return"},
        vat_split_status=vat_split.status,
        vat_split_lines=vat_split.lines,
        vat_split_evidence=vat_split.evidence,
        canonical_invoice=canonical_invoice,
    )


def parse_invoice_folder(input_dir: Path) -> list[ParsedInvoice]:
    files = sorted(input_dir.rglob("*.pdf"), key=lambda item: item.name.lower())
    return [parse_pdf_invoice(path) for path in files]


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
