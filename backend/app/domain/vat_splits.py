from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re
import unicodedata


MONEY = Decimal("0.01")
VAT_RATE_RE = re.compile(r"%\s*(0|1|8|10|18|20)(?:[,.]0+)?(?!\d)")
VAT_RATE_PAREN_RE = re.compile(r"\((0|1|8|10|18|20)%\)")
AMOUNT_RE = re.compile(
    r"(?<![%\d.])-?(?:\d{1,3}(?:[.\s]\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2})(?![\d.])"
)
MATRAH_AMOUNT_RE = re.compile(
    r"matrah\s*:?\s*((?<![%\d.])-?(?:\d{1,3}(?:[.\s]\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2})(?![\d.]))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VatSplitLine:
    rate: str
    taxable_amount: str
    tax_amount: str
    source: str
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VatSplitResult:
    status: str = ""
    lines: tuple[VatSplitLine, ...] = ()
    total_taxable_amount: str = ""
    total_tax_amount: str = ""
    tax_inclusive_total: str = ""
    payable_total: str = ""
    evidence: tuple[str, ...] = ()


def _normalize(value: str) -> str:
    value = value.replace("\u0131", "i").replace("\u0130", "i")
    decomposed = unicodedata.normalize("NFKD", value)
    asciiish = "".join(character for character in decomposed if not unicodedata.combining(character))
    asciiish = asciiish.replace("\ufffd", "")
    return re.sub(r"\s+", " ", asciiish.lower()).strip()


def _decimal_from_match(selected: str) -> Decimal | None:
    compact = selected.replace(" ", "")
    if "," in compact:
        raw = compact.replace(".", "").replace(",", ".")
    elif "." in compact and len(compact.rsplit(".", 1)[-1]) == 2:
        raw = compact
    else:
        raw = compact.replace(".", "")
    try:
        return Decimal(raw).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _parse_money_candidates(value: str) -> list[Decimal]:
    matches = AMOUNT_RE.findall(str(value or "").replace("\n", " "))
    return [candidate for match in matches if (candidate := _decimal_from_match(match)) is not None]


def _parse_money(value: str, *, pick: str = "last") -> Decimal | None:
    candidates = _parse_money_candidates(value)
    if not candidates:
        return None
    if pick == "first":
        return candidates[0]
    if pick == "max":
        return max(candidates)
    return candidates[-1]


def _parse_rate(value: str) -> str:
    candidate = str(value or "")
    match = VAT_RATE_RE.search(candidate) or VAT_RATE_PAREN_RE.search(candidate)
    return str(int(match.group(1))) if match else ""


def _parse_matrah_amount(value: str) -> Decimal | None:
    match = MATRAH_AMOUNT_RE.search(str(value or ""))
    return _parse_money(match.group(1)) if match else None


def _find_amount_near_expected(value: str, expected: Decimal) -> Decimal | None:
    candidates = _parse_money_candidates(value)
    nearby = [candidate for candidate in candidates if _within_money_tolerance(candidate, expected, tolerance=Decimal("0.05"))]
    if nearby:
        return min(nearby, key=lambda candidate: abs(candidate - expected))
    return None


def _format_money(value: Decimal | None) -> str:
    return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}" if value is not None else ""


def _find_column(header: list[str], required_terms: tuple[str, ...]) -> int | None:
    for index, cell in enumerate(header):
        normalized = _normalize(cell)
        if all(term in normalized for term in required_terms):
            return index
    return None


def _add_amount(bucket: dict[str, dict[str, Decimal]], rate: str, field_name: str, amount: Decimal) -> None:
    bucket.setdefault(rate, {})
    bucket[rate][field_name] = bucket[rate].get(field_name, Decimal("0.00")) + amount


def _extract_line_table_splits(tables: list[list[list[str | None]]]) -> dict[str, dict[str, Decimal]]:
    splits: dict[str, dict[str, Decimal]] = {}
    for table in tables:
        for row_index, row in enumerate(table):
            header = [cell or "" for cell in row]
            joined_header = _normalize(" ".join(header))
            if "kdv" not in joined_header or "mal hizmet" not in joined_header or "tutar" not in joined_header:
                continue

            rate_col = _find_column(header, ("kdv", "oran"))
            tax_col = _find_column(header, ("kdv", "tutar"))
            taxable_col = _find_column(header, ("mal", "hizmet", "tutar"))
            if rate_col is None or tax_col is None or taxable_col is None:
                continue

            required_col = max(rate_col, tax_col, taxable_col)
            for data_row in table[row_index + 1 :]:
                if len(data_row) <= required_col:
                    continue
                rate = _parse_rate(data_row[rate_col] or "")
                taxable_amount = _parse_money(data_row[taxable_col] or "")
                tax_amount = _parse_money(data_row[tax_col] or "")
                if not rate or taxable_amount is None or tax_amount is None:
                    continue
                _add_amount(splits, rate, "taxable_amount", taxable_amount)
                _add_amount(splits, rate, "tax_amount", tax_amount)
    return splits


def _extract_summary_values(text: str) -> tuple[dict[str, dict[str, Decimal]], dict[str, Decimal]]:
    split_values: dict[str, dict[str, Decimal]] = {}
    totals: dict[str, Decimal] = {}
    raw_lines = text.splitlines()
    for index, raw_line in enumerate(raw_lines):
        line = " ".join(raw_line.split())
        normalized = _normalize(line)
        normalized_compact = re.sub(r"[^a-z0-9%]", "", normalized)
        amount = _parse_money(line)
        rate = _parse_rate(line)
        matrah_amount = _parse_matrah_amount(line)
        amount_candidates = _parse_money_candidates(line)
        summary_window = " ".join(raw_lines[index : index + 8])
        if matrah_amount is None and "kdv" in normalized and rate:
            matrah_amount = _parse_matrah_amount(summary_window)
        if matrah_amount is not None and "kdv" in normalized and rate:
            expected_tax = (matrah_amount * Decimal(rate) / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
            amount = _find_amount_near_expected(summary_window, expected_tax) or amount
        if amount is None and "denecek tutar" in normalized:
            amount = _parse_money(" ".join(raw_lines[index + 1 : index + 9]), pick="max")
        if amount is None and "fatura tutari" in normalized:
            amount = _parse_money(" ".join(raw_lines[index + 1 : index + 8]), pick="max")
        if amount is None:
            amount = _parse_money(" ".join(raw_lines[index + 1 : index + 4]), pick="first")
        if amount is None and "katma deger vergisi" in normalized:
            amount = _parse_money(" ".join(raw_lines[max(0, index - 3) : index]), pick="last")
        if amount is None:
            continue

        if matrah_amount is not None and "kdv" in normalized and rate:
            split_values.setdefault(rate, {})["taxable_amount"] = matrah_amount
            split_values.setdefault(rate, {})["tax_amount"] = amount
        elif "kdv" in normalized and rate and len(amount_candidates) >= 2:
            split_values.setdefault(rate, {})["taxable_amount"] = amount_candidates[-2]
            split_values.setdefault(rate, {})["tax_amount"] = amount_candidates[-1]
        elif "kdv matrah" in normalized and rate:
            split_values.setdefault(rate, {})["taxable_amount"] = amount
        elif (
            "hesaplanan kdv" in normalized
            or "hesaplanankdv" in normalized_compact
            or "katma deger vergisi" in normalized
        ) and rate:
            split_values.setdefault(rate, {})["tax_amount"] = amount
        elif "vergi haric" in normalized:
            totals["taxable_total"] = amount
        elif "mal hizmet toplam" in normalized:
            totals.setdefault("goods_services_total", amount)
        elif "vergiler dahil" in normalized:
            totals["tax_inclusive_total"] = amount
        elif "fatura tutari" in normalized:
            totals["tax_inclusive_total"] = amount
        elif "denecek tutar" in normalized:
            totals["payable_total"] = amount
        elif "matrah har" in normalized:
            totals["vat_exempt_taxable_total"] = amount
    return split_values, totals


def _extract_text_line_splits(text: str) -> dict[str, dict[str, Decimal]]:
    summary_match = re.search(r"Mal\s+Hizmet\s+Toplam|Vergi\s+Hari", text, re.IGNORECASE)
    line_text = text[: summary_match.start()] if summary_match else text
    splits: dict[str, dict[str, Decimal]] = {}
    for match in VAT_RATE_RE.finditer(line_text):
        rate = str(int(match.group(1)))
        before = line_text[max(0, match.start() - 140) : match.start()]
        after = line_text[match.end() : match.end() + 80]
        taxable_matches = AMOUNT_RE.findall(before)
        tax_matches = AMOUNT_RE.findall(after)
        if not taxable_matches or not tax_matches:
            continue
        taxable_amount = _parse_money(taxable_matches[-1])
        tax_amount = _parse_money(tax_matches[0])
        if taxable_amount is None or tax_amount is None:
            continue
        _add_amount(splits, rate, "taxable_amount", taxable_amount)
        _add_amount(splits, rate, "tax_amount", tax_amount)
    return splits


def _within_money_tolerance(left: Decimal, right: Decimal, *, tolerance: Decimal = MONEY) -> bool:
    return abs(left - right) <= tolerance


def _values_validate(rate: str, values: dict[str, Decimal]) -> bool:
    if "taxable_amount" not in values or "tax_amount" not in values:
        return False
    expected_tax = (values["taxable_amount"] * Decimal(rate) / Decimal("100")).quantize(
        MONEY,
        rounding=ROUND_HALF_UP,
    )
    return _within_money_tolerance(expected_tax, values["tax_amount"])


def _complete_summary_splits(
    line_splits: dict[str, dict[str, Decimal]],
    summary_splits: dict[str, dict[str, Decimal]],
    totals: dict[str, Decimal],
) -> dict[str, dict[str, Decimal]]:
    completed = {rate: dict(values) for rate, values in summary_splits.items()}
    rates = sorted(set(line_splits) | set(completed), key=lambda value: int(value))
    if not rates:
        return completed

    gross_total = totals.get("payable_total") or totals.get("tax_inclusive_total")
    goods_total = totals.get("taxable_total") or totals.get("goods_services_total")
    vat_exempt_taxable_total = totals.get("vat_exempt_taxable_total")

    if vat_exempt_taxable_total is not None and "0" in rates:
        completed.setdefault("0", {})["taxable_amount"] = vat_exempt_taxable_total
        completed.setdefault("0", {})["tax_amount"] = Decimal("0.00")
        non_zero_rates = [rate for rate in rates if rate != "0"]
        if len(non_zero_rates) == 1 and goods_total is not None:
            completed.setdefault(non_zero_rates[0], {})["taxable_amount"] = (
                goods_total - vat_exempt_taxable_total
            ).quantize(MONEY, rounding=ROUND_HALF_UP)

    summary_tax_rates = [rate for rate, values in completed.items() if "tax_amount" in values]
    if len(summary_tax_rates) == 1 and goods_total is not None:
        completed.setdefault(summary_tax_rates[0], {}).setdefault("taxable_amount", goods_total)

    if len(rates) == 1:
        rate = rates[0]
        values = completed.setdefault(rate, {})
        line_values = line_splits.get(rate, {})
        if "taxable_amount" not in values and "taxable_amount" in line_values and _values_validate(rate, line_values):
            values["taxable_amount"] = line_values["taxable_amount"]
        if "taxable_amount" not in values and goods_total is not None:
            values["taxable_amount"] = goods_total
        if "tax_amount" not in values and "tax_amount" in line_values:
            values["tax_amount"] = line_values["tax_amount"]
        if "taxable_amount" not in values and gross_total is not None and "tax_amount" in values:
            values["taxable_amount"] = (gross_total - values["tax_amount"]).quantize(MONEY, rounding=ROUND_HALF_UP)
        if "tax_amount" not in values and gross_total is not None and "taxable_amount" in values:
            values["tax_amount"] = (gross_total - values["taxable_amount"]).quantize(MONEY, rounding=ROUND_HALF_UP)

    for rate in rates:
        values = completed.setdefault(rate, {})
        line_values = line_splits.get(rate, {})
        if (
            "taxable_amount" in line_values
            and "tax_amount" in line_values
            and ("taxable_amount" not in values or "tax_amount" not in values)
        ):
            expected_line_tax = (line_values["taxable_amount"] * Decimal(rate) / Decimal("100")).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )
            if _within_money_tolerance(expected_line_tax, line_values["tax_amount"]):
                values.setdefault("taxable_amount", line_values["taxable_amount"])
                values.setdefault("tax_amount", line_values["tax_amount"])
        if rate == "0" and "taxable_amount" in values and "tax_amount" not in values:
            values["tax_amount"] = Decimal("0.00")

    if gross_total is not None:
        total_taxable = sum(
            (values["taxable_amount"] for values in completed.values() if "taxable_amount" in values),
            Decimal("0.00"),
        )
        known_tax = sum((values["tax_amount"] for values in completed.values() if "tax_amount" in values), Decimal("0.00"))
        missing_tax_rates = [
            rate
            for rate, values in completed.items()
            if rate != "0" and "taxable_amount" in values and "tax_amount" not in values
        ]
        if len(missing_tax_rates) == 1 and total_taxable:
            missing_tax = (gross_total - total_taxable - known_tax).quantize(MONEY, rounding=ROUND_HALF_UP)
            if missing_tax >= Decimal("0.00"):
                completed[missing_tax_rates[0]]["tax_amount"] = missing_tax

    return completed


def _build_result(
    *,
    line_splits: dict[str, dict[str, Decimal]],
    summary_splits: dict[str, dict[str, Decimal]],
    totals: dict[str, Decimal],
) -> VatSplitResult:
    summary_splits = _complete_summary_splits(line_splits, summary_splits, totals)
    rates = sorted(set(line_splits) | set(summary_splits), key=lambda value: int(value))
    lines: list[VatSplitLine] = []
    evidence: list[str] = []
    validated = bool(rates)

    for rate in rates:
        line_values = line_splits.get(rate, {})
        summary_values = summary_splits.get(rate, {})
        taxable_amount = (
            summary_values["taxable_amount"] if "taxable_amount" in summary_values else line_values.get("taxable_amount")
        )
        tax_amount = summary_values["tax_amount"] if "tax_amount" in summary_values else line_values.get("tax_amount")
        if taxable_amount is None or tax_amount is None:
            validated = False
            continue

        expected_tax = (taxable_amount * Decimal(rate) / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
        if not _within_money_tolerance(expected_tax, tax_amount):
            if not summary_values and any(values for values in summary_splits.values()):
                validated = False
                continue
            validated = False

        source_parts = []
        if "taxable_amount" in line_values or "tax_amount" in line_values:
            source_parts.append("pdf_line_table")
        if "taxable_amount" in summary_values or "tax_amount" in summary_values:
            source_parts.append("pdf_summary_table")
        source = "+".join(source_parts) or "pdf_table"
        evidence.append(f"vat_rate_{rate}_taxable_and_tax_validated")
        lines.append(
            VatSplitLine(
                rate=rate,
                taxable_amount=_format_money(taxable_amount),
                tax_amount=_format_money(tax_amount),
                source=source,
                evidence=(f"expected_tax:{_format_money(expected_tax)}",),
            )
        )

    total_taxable = sum((Decimal(line.taxable_amount) for line in lines), Decimal("0.00"))
    total_tax = sum((Decimal(line.tax_amount) for line in lines), Decimal("0.00"))
    payable_total = totals.get("payable_total")
    tax_inclusive_total = totals.get("tax_inclusive_total")
    expected_gross = (total_taxable + total_tax).quantize(MONEY, rounding=ROUND_HALF_UP)
    gross_total = payable_total or tax_inclusive_total
    gross_validated = True
    if gross_total is not None and not _within_money_tolerance(expected_gross, gross_total):
        gross_validated = False
        validated = False
    if gross_total is not None:
        evidence.append("vat_split_gross_total_validated" if gross_validated else "vat_split_gross_total_not_vat_only")

    if validated and lines:
        status = "exact"
    elif lines and all(
        _within_money_tolerance(
            (Decimal(line.taxable_amount) * Decimal(line.rate) / Decimal("100")).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            ),
            Decimal(line.tax_amount),
        )
        for line in lines
    ):
        status = "derived"
    else:
        status = "needs_review"
    return VatSplitResult(
        status=status,
        lines=tuple(lines),
        total_taxable_amount=_format_money(total_taxable) if lines else "",
        total_tax_amount=_format_money(total_tax) if lines else "",
        tax_inclusive_total=_format_money(tax_inclusive_total),
        payable_total=_format_money(payable_total),
        evidence=tuple(dict.fromkeys(evidence)),
    )


def extract_pdf_vat_split(path: Path) -> VatSplitResult:
    all_tables: list[list[list[str | None]]] = []
    all_text: list[str] = []
    try:
        import pdfplumber
    except ImportError:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            all_text = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:  # noqa: BLE001
            return VatSplitResult(status="needs_review", evidence=(f"pdf_vat_split_error:{type(exc).__name__}",))
    else:
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    all_tables.extend(page.extract_tables())
                    all_text.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
        except Exception as exc:  # noqa: BLE001
            return VatSplitResult(status="needs_review", evidence=(f"pdf_vat_split_error:{type(exc).__name__}",))

    line_splits = _extract_line_table_splits(all_tables)
    text = "\n".join(all_text)
    if not line_splits:
        line_splits = _extract_text_line_splits(text)
    summary_splits, totals = _extract_summary_values(text)
    return _build_result(line_splits=line_splits, summary_splits=summary_splits, totals=totals)
