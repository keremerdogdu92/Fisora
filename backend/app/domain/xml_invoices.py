from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from app.domain.pdf_invoices import ParsedInvoice


TAX_ID_RE = re.compile(r"^\d{10,11}$")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def _decimal_text(value: str) -> str:
    try:
        return f"{Decimal(value.strip()):.2f}"
    except (InvalidOperation, ValueError):
        return ""


def _first_text(root: ET.Element, names: tuple[str, ...]) -> str:
    wanted = set(names)
    for element in root.iter():
        if _local_name(element.tag) in wanted:
            value = _text(element)
            if value:
                return value
    return ""


def _party_details(root: ET.Element, parent_name: str) -> tuple[str, str]:
    tax_id = ""
    legal_title = ""
    display_title = ""
    for parent in root.iter():
        if _local_name(parent.tag) != parent_name:
            continue
        for element in parent.iter():
            local_name = _local_name(element.tag)
            value = _text(element)
            if not value:
                continue
            if local_name in {"CompanyID", "ID"} and TAX_ID_RE.match(value) and not tax_id:
                tax_id = value
            elif local_name == "RegistrationName" and not legal_title:
                legal_title = value[:120]
            elif local_name == "Name" and not display_title:
                display_title = value[:120]
        break
    return legal_title or display_title, tax_id


def _first_amount(root: ET.Element, names: tuple[str, ...]) -> str:
    value = _first_text(root, names)
    return _decimal_text(value)


def _tax_ids(root: ET.Element) -> tuple[str, ...]:
    ids: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "CompanyID":
            continue
        value = _text(element)
        if TAX_ID_RE.match(value):
            ids.append(value)
    return tuple(dict.fromkeys(ids))


def _vat_rates(root: ET.Element) -> tuple[str, ...]:
    rates: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) != "Percent":
            continue
        value = _text(element).replace(",", ".")
        try:
            percent = Decimal(value)
        except InvalidOperation:
            continue
        if percent == percent.to_integral_value():
            rates.add(str(int(percent)))
    return tuple(sorted(rates, key=lambda item: int(item)))


def _provider_hint(root: ET.Element) -> str:
    supplier_title, _ = _party_details(root, "AccountingSupplierParty")
    if supplier_title:
        return supplier_title
    for name in ("RegistrationName", "Name"):
        value = _first_text(root, (name,))
        if value:
            return value[:120]
    return ""


def _invoice_line_hints(root: ET.Element, *, max_lines: int = 20) -> tuple[str, ...]:
    hints: list[str] = []
    for line in root.iter():
        if _local_name(line.tag) != "InvoiceLine":
            continue
        for child in line.iter():
            if _local_name(child.tag) not in {"Name", "Description"}:
                continue
            value = _text(child)
            if value:
                hints.append(value[:120])
                break
        if len(hints) >= max_lines:
            break
    return tuple(dict.fromkeys(hints))


def parse_xml_invoice(path: Path) -> ParsedInvoice:
    notes: list[str] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return ParsedInvoice(
            file_name=path.name,
            provider_hint="",
            page_count=0,
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
            risk_flags=("xml_parse_error",),
            suggested_route="review_queue",
            parse_notes=("xml_parse_error",),
            line_items=(),
        )

    invoice_no = _first_text(root, ("ID",))
    issue_date = _first_text(root, ("IssueDate",))
    payable_total = _first_amount(root, ("PayableAmount",))
    if not invoice_no:
        notes.append("missing_invoice_no")
    if not issue_date:
        notes.append("missing_issue_date")
    if not payable_total:
        notes.append("missing_payable_total")

    route = "review_queue" if notes else "journal_candidate"
    xml_text = ET.tostring(root, encoding="unicode")
    issuer_title, issuer_tax_id = _party_details(root, "AccountingSupplierParty")
    recipient_title, recipient_tax_id = _party_details(root, "AccountingCustomerParty")
    invoice_type_code = _first_text(root, ("InvoiceTypeCode",))
    return ParsedInvoice(
        file_name=path.name,
        provider_hint=_provider_hint(root),
        page_count=0,
        text_extractable=True,
        extracted_char_count=len(xml_text),
        scenario=_first_text(root, ("ProfileID",)),
        invoice_type=invoice_type_code,
        invoice_no=invoice_no,
        ettn=_first_text(root, ("UUID",)),
        issue_date=issue_date,
        tax_ids=_tax_ids(root),
        vat_rates=_vat_rates(root),
        goods_services_total=_first_amount(root, ("LineExtensionAmount",)),
        vat_total=_first_amount(root, ("TaxAmount",)),
        special_tax_total="",
        tax_inclusive_total=_first_amount(root, ("TaxInclusiveAmount",)),
        payable_total=payable_total,
        risk_flags=(),
        suggested_route=route,
        parse_notes=tuple(notes),
        line_items=_invoice_line_hints(root),
        issuer_title=issuer_title,
        issuer_tax_id=issuer_tax_id,
        recipient_title=recipient_title,
        recipient_tax_id=recipient_tax_id,
        invoice_type_code=invoice_type_code,
        is_return_invoice=invoice_type_code.upper() in {"IADE", "\u0130ADE", "RETURN"},
    )
