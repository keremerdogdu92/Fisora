from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from app.domain.canonical_invoices import (
    CanonicalInvoice,
    CanonicalInvoiceHeader,
    CanonicalInvoiceLine,
    CanonicalInvoiceParty,
    CanonicalInvoiceTotals,
    CanonicalVatSummaryLine,
    with_validation,
)
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


def _first_text_under(root: ET.Element, names: tuple[str, ...]) -> str:
    wanted = set(names)
    for element in root.iter():
        if _local_name(element.tag) in wanted:
            value = _text(element)
            if value:
                return value
    return ""


def _first_amount_under(root: ET.Element, names: tuple[str, ...]) -> str:
    return _decimal_text(_first_text_under(root, names))


def _direct_child(root: ET.Element, local_name: str) -> ET.Element | None:
    return next((child for child in list(root) if _local_name(child.tag) == local_name), None)


def _direct_children(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in list(root) if _local_name(child.tag) == local_name]


def _first_text_in_child(root: ET.Element, child_name: str, names: tuple[str, ...]) -> str:
    child = _direct_child(root, child_name)
    if child is None:
        return ""
    return _first_text_under(child, names)


def _first_amount_in_child(root: ET.Element, child_name: str, names: tuple[str, ...]) -> str:
    return _decimal_text(_first_text_in_child(root, child_name, names))


def _format_sum(left: str, right: str) -> str:
    try:
        return f"{Decimal(left or '0') + Decimal(right or '0'):.2f}"
    except (InvalidOperation, ValueError):
        return ""


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
        value = _first_text_in_child(line, "Item", ("Name", "Description"))
        if value:
            hints.append(value[:120])
        if len(hints) >= max_lines:
            break
    return tuple(dict.fromkeys(hints))


def _canonical_invoice_lines(root: ET.Element, *, max_lines: int = 100) -> tuple[CanonicalInvoiceLine, ...]:
    lines: list[CanonicalInvoiceLine] = []
    for index, line in enumerate((element for element in root.iter() if _local_name(element.tag) == "InvoiceLine"), start=1):
        description = _first_text_in_child(line, "Item", ("Name", "Description"))[:160]
        taxable_amount = _first_amount_in_child(line, "TaxTotal", ("TaxableAmount",)) or _first_amount_under(
            line,
            ("LineExtensionAmount",),
        )
        tax_amount = _first_amount_in_child(line, "TaxTotal", ("TaxAmount",))
        vat_rate = _first_text_under(line, ("Percent",))
        unit_price = _first_amount_in_child(line, "Price", ("PriceAmount",))
        quantity = _first_text_under(line, ("InvoicedQuantity", "CreditedQuantity"))
        if description:
            lines.append(
                CanonicalInvoiceLine(
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    taxable_amount=taxable_amount,
                    vat_rate=str(int(Decimal(vat_rate))) if vat_rate else "",
                    tax_amount=tax_amount,
                    gross_amount=_format_sum(taxable_amount, tax_amount),
                    evidence=(f"xml:InvoiceLine[{index}]",),
                )
            )
        if len(lines) >= max_lines:
            break
    return tuple(lines)


def _canonical_vat_summary(root: ET.Element) -> tuple[CanonicalVatSummaryLine, ...]:
    summary: list[CanonicalVatSummaryLine] = []
    tax_totals = _direct_children(root, "TaxTotal")
    search_roots = tax_totals or [root]
    for tax_total in search_roots:
        for index, subtotal in enumerate(
            (element for element in tax_total.iter() if _local_name(element.tag) == "TaxSubtotal"),
            start=1,
        ):
            rate = _first_text_under(subtotal, ("Percent",))
            summary.append(
                CanonicalVatSummaryLine(
                    rate=str(int(Decimal(rate))) if rate else "",
                    taxable_amount=_first_amount_under(subtotal, ("TaxableAmount",)),
                    tax_amount=_first_amount_under(subtotal, ("TaxAmount",)),
                    evidence=(f"xml:TaxSubtotal[{index}]",),
                )
            )
    return tuple(line for line in summary if line.rate or line.taxable_amount or line.tax_amount)


def build_xml_canonical_invoice(root: ET.Element) -> CanonicalInvoice:
    issuer_title, issuer_tax_id = _party_details(root, "AccountingSupplierParty")
    recipient_title, recipient_tax_id = _party_details(root, "AccountingCustomerParty")
    legal_totals = _direct_child(root, "LegalMonetaryTotal")
    if legal_totals is None:
        legal_totals = root
    invoice = CanonicalInvoice(
        source="xml",
        supplier_party=CanonicalInvoiceParty(
            title=issuer_title,
            tax_id=issuer_tax_id,
            evidence=("xml:AccountingSupplierParty",) if issuer_title or issuer_tax_id else (),
        ),
        customer_party=CanonicalInvoiceParty(
            title=recipient_title,
            tax_id=recipient_tax_id,
            evidence=("xml:AccountingCustomerParty",) if recipient_title or recipient_tax_id else (),
        ),
        header=CanonicalInvoiceHeader(
            invoice_no=_first_text(root, ("ID",)),
            issue_date=_first_text(root, ("IssueDate",)),
            ettn=_first_text(root, ("UUID",)),
            scenario=_first_text(root, ("ProfileID",)),
            invoice_type=_first_text(root, ("InvoiceTypeCode",)),
            evidence=("xml:InvoiceHeader",),
        ),
        line_items=_canonical_invoice_lines(root),
        vat_summary=_canonical_vat_summary(root),
        totals=CanonicalInvoiceTotals(
            goods_services_total=_first_amount_under(legal_totals, ("LineExtensionAmount",)),
            vat_total=_first_amount(root, ("TaxAmount",)),
            tax_inclusive_total=_first_amount_under(legal_totals, ("TaxInclusiveAmount",)),
            payable_total=_first_amount_under(legal_totals, ("PayableAmount",)),
            evidence=("xml:LegalMonetaryTotal",),
        ),
    )
    return with_validation(invoice)


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
    canonical_invoice = build_xml_canonical_invoice(root)
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
        canonical_invoice=canonical_invoice,
    )
