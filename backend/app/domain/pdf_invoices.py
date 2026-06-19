from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_lines import extract_invoice_lines_from_text, invoice_line_hints


DATE_RE = re.compile(r"(?<!\d)([0-3]?\d)\s*[./-]\s*([01]?\d)\s*[./-]\s*(20\d{2})(?!\d)")
ETTN_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
INVOICE_NO_RE = re.compile(r"\b([A-Z]{2,4}\d{8,16}|[A-Z]\d[A-Z]\d{8,16})\b")
TAX_ID_RE = re.compile(r"\b(?:VKN|TCKN|TC\s*Kimlik\s*No|Vergi\s*No)\s*:?\s*([0-9]{10,11})\b", re.IGNORECASE)
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


def parse_amount(raw: str) -> Decimal | None:
    compact = raw.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def format_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


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


def parse_pdf_invoice(path: Path) -> ParsedInvoice:
    page_count, text, extraction_notes = extract_pdf_text(path)
    stripped_text = text.strip()
    edge_summary = summarize_invoice_edge_cases(path.name, text, extracted_char_count=len(stripped_text))
    parsed_totals = {
        key: extract_label_amount(text, labels)
        for key, labels in TOTAL_LABELS.items()
    }
    parsed_identity = {
        "invoice_no": extract_invoice_no(text) or edge_summary.invoice_no,
        "issue_date": extract_issue_date(text),
        "payable_total": parsed_totals["payable_total"],
    }
    route, route_notes = build_route(edge_summary.risk_flags, parsed_identity)
    line_items = invoice_line_hints(extract_invoice_lines_from_text(text))
    return ParsedInvoice(
        file_name=path.name,
        provider_hint=extract_seller_hint(text) or edge_summary.provider_hint,
        page_count=page_count,
        text_extractable=len(stripped_text) >= 100,
        extracted_char_count=len(stripped_text),
        scenario=extract_scenario(text),
        invoice_type=extract_invoice_type(text),
        invoice_no=parsed_identity["invoice_no"],
        ettn=extract_ettn(text) or edge_summary.ettn,
        issue_date=parsed_identity["issue_date"],
        tax_ids=extract_tax_ids(text),
        vat_rates=extract_vat_rates(text),
        goods_services_total=parsed_totals["goods_services_total"],
        vat_total=parsed_totals["vat_total"],
        special_tax_total=parsed_totals["special_tax_total"],
        tax_inclusive_total=parsed_totals["tax_inclusive_total"],
        payable_total=parsed_totals["payable_total"],
        risk_flags=edge_summary.risk_flags,
        suggested_route=route,
        parse_notes=tuple(dict.fromkeys((*extraction_notes, *route_notes))),
        line_items=line_items,
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
