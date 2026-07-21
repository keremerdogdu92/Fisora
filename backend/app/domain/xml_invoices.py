from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import unicodedata
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
GENERIC_TAX_SCHEME_NAMES = {"KDV", "VAT", "KATMA DEGER VERGISI"}
CANCELLATION_MARKERS = ("IPTAL", "CANCELLED", "CANCELED")


@dataclass(frozen=True)
class XmlPartyDetails:
    title: str = ""
    tax_id: str = ""
    tax_office: str = ""
    address: str = ""
    evidence: tuple[str, ...] = ()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def _ascii_upper(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").upper().strip()


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


def _document_text(root: ET.Element) -> str:
    return " ".join(_text(element) for element in root.iter() if _text(element))


def _cancellation_risk_flags(root: ET.Element) -> tuple[str, ...]:
    haystack = _ascii_upper(_document_text(root))
    return ("cancelled_invoice_visible",) if any(marker in haystack for marker in CANCELLATION_MARKERS) else ()


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


def _text_at(root: ET.Element | None, path: tuple[str, ...]) -> str:
    current = root
    for part in path:
        if current is None:
            return ""
        current = _direct_child(current, part)
    return _text(current)


def _first_party_title(party: ET.Element, *, evidence: list[str]) -> str:
    for entity in _direct_children(party, "PartyLegalEntity"):
        value = _text_at(entity, ("RegistrationName",))
        if value:
            evidence.append("PartyLegalEntity/RegistrationName")
            return value[:120]
    for name in _direct_children(party, "PartyName"):
        value = _text_at(name, ("Name",))
        if value:
            evidence.append("PartyName/Name")
            return value[:120]
    for person in _direct_children(party, "Person"):
        parts = (
            _text_at(person, ("FirstName",)),
            _text_at(person, ("MiddleName",)),
            _text_at(person, ("FamilyName",)),
        )
        value = " ".join(part for part in parts if part)
        if value:
            evidence.append("Person/FirstName+FamilyName")
            return value[:120]
        value = _text_at(person, ("Name",))
        if value:
            evidence.append("Person/Name")
            return value[:120]
    return ""


def _first_party_tax_id(party: ET.Element, *, evidence: list[str]) -> str:
    candidates: list[tuple[str, str]] = []
    for identification in _direct_children(party, "PartyIdentification"):
        candidates.append((_text_at(identification, ("ID",)), "PartyIdentification/ID"))
    for scheme in _direct_children(party, "PartyTaxScheme"):
        candidates.append((_text_at(scheme, ("CompanyID",)), "PartyTaxScheme/CompanyID"))
    for entity in _direct_children(party, "PartyLegalEntity"):
        candidates.append((_text_at(entity, ("CompanyID",)), "PartyLegalEntity/CompanyID"))
    for value, path in candidates:
        digits = re.sub(r"\D", "", value)
        if TAX_ID_RE.match(digits):
            evidence.append(path)
            return digits
    return ""


def _party_tax_office(party: ET.Element, *, evidence: list[str]) -> str:
    for scheme in _direct_children(party, "PartyTaxScheme"):
        value = _text_at(_direct_child(scheme, "TaxScheme"), ("Name",))
        if value and _ascii_upper(value) not in GENERIC_TAX_SCHEME_NAMES:
            evidence.append("PartyTaxScheme/TaxScheme/Name")
            return value[:80]
    return ""


def _party_address(party: ET.Element, *, evidence: list[str]) -> str:
    address = _direct_child(party, "PostalAddress")
    if address is None:
        return ""
    parts: list[str] = []
    for name in ("StreetName", "BuildingName", "BuildingNumber", "Room", "CitySubdivisionName", "CityName", "PostalZone"):
        value = _text_at(address, (name,))
        if value:
            parts.append(value)
    for line in _direct_children(address, "AddressLine"):
        value = _text_at(line, ("Line",))
        if value:
            parts.append(value)
    unique_parts = tuple(dict.fromkeys(parts))
    if unique_parts:
        evidence.append("PostalAddress")
    return " / ".join(unique_parts)[:240]


def _party_details(root: ET.Element, parent_name: str) -> XmlPartyDetails:
    parent = next((element for element in root.iter() if _local_name(element.tag) == parent_name), None)
    party = _direct_child(parent, "Party") if parent is not None else None
    if party is None:
        return XmlPartyDetails()
    evidence: list[str] = []
    return XmlPartyDetails(
        title=_first_party_title(party, evidence=evidence),
        tax_id=_first_party_tax_id(party, evidence=evidence),
        tax_office=_party_tax_office(party, evidence=evidence),
        address=_party_address(party, evidence=evidence),
        evidence=tuple(evidence),
    )


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
    supplier = _party_details(root, "AccountingSupplierParty")
    if supplier.title:
        return supplier.title
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
        external_line_id = next(
            (
                (child.text or "").strip()
                for child in list(line)
                if _local_name(child.tag) == "ID" and (child.text or "").strip()
            ),
            "",
        )
        description = _first_text_in_child(line, "Item", ("Name", "Description"))[:160]
        taxable_amount = _first_amount_in_child(line, "TaxTotal", ("TaxableAmount",)) or _first_amount_under(
            line,
            ("LineExtensionAmount",),
        )
        tax_amount = _first_amount_in_child(line, "TaxTotal", ("TaxAmount",))
        vat_rate = _first_text_under(line, ("Percent",))
        unit_price = _first_amount_in_child(line, "Price", ("PriceAmount",))
        quantity_element = next(
            (
                child
                for child in line.iter()
                if _local_name(child.tag) in {"InvoicedQuantity", "CreditedQuantity"}
            ),
            None,
        )
        quantity = (quantity_element.text or "").strip() if quantity_element is not None else ""
        unit_code = str(quantity_element.attrib.get("unitCode") or "") if quantity_element is not None else ""
        if description:
            lines.append(
                CanonicalInvoiceLine(
                    description=description,
                    source_position=f"xml:InvoiceLine[{external_line_id or index}]",
                    external_line_id=external_line_id,
                    quantity=quantity,
                    unit_code=unit_code,
                    unit_price=unit_price,
                    taxable_amount=taxable_amount,
                    vat_rate=str(int(Decimal(vat_rate))) if vat_rate else "",
                    tax_amount=tax_amount,
                    gross_amount=_format_sum(taxable_amount, tax_amount),
                    evidence=(f"xml:InvoiceLine[{external_line_id or index}]",),
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
    supplier = _party_details(root, "AccountingSupplierParty")
    customer = _party_details(root, "AccountingCustomerParty")
    legal_totals = _direct_child(root, "LegalMonetaryTotal")
    if legal_totals is None:
        legal_totals = root
    billing_reference = _direct_child(root, "BillingReference")
    original_reference = (
        _direct_child(billing_reference, "InvoiceDocumentReference")
        if billing_reference is not None
        else None
    )
    invoice = CanonicalInvoice(
        source="xml",
        supplier_party=CanonicalInvoiceParty(
            title=supplier.title,
            tax_id=supplier.tax_id,
            tax_office=supplier.tax_office,
            address=supplier.address,
            evidence=tuple(f"xml:AccountingSupplierParty/{item}" for item in supplier.evidence) if supplier.evidence else (),
        ),
        customer_party=CanonicalInvoiceParty(
            title=customer.title,
            tax_id=customer.tax_id,
            tax_office=customer.tax_office,
            address=customer.address,
            evidence=tuple(f"xml:AccountingCustomerParty/{item}" for item in customer.evidence) if customer.evidence else (),
        ),
        header=CanonicalInvoiceHeader(
            invoice_no=_first_text(root, ("ID",)),
            issue_date=_first_text(root, ("IssueDate",)),
            ettn=_first_text(root, ("UUID",)),
            scenario=_first_text(root, ("ProfileID",)),
            invoice_type=_first_text(root, ("InvoiceTypeCode",)),
            original_invoice_no=(
                _first_text_under(original_reference, ("ID",))
                if original_reference is not None
                else ""
            ),
            original_invoice_date=(
                _first_text_under(original_reference, ("IssueDate",))
                if original_reference is not None
                else ""
            ),
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

    cancellation_risk_flags = _cancellation_risk_flags(root)
    route = "review_queue" if notes or cancellation_risk_flags else "journal_candidate"
    xml_text = ET.tostring(root, encoding="unicode")
    supplier = _party_details(root, "AccountingSupplierParty")
    customer = _party_details(root, "AccountingCustomerParty")
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
        risk_flags=cancellation_risk_flags,
        suggested_route=route,
        parse_notes=tuple(notes),
        line_items=_invoice_line_hints(root),
        issuer_title=supplier.title,
        issuer_tax_id=supplier.tax_id,
        recipient_title=customer.title,
        recipient_tax_id=customer.tax_id,
        invoice_type_code=invoice_type_code,
        is_return_invoice=invoice_type_code.upper() in {"IADE", "\u0130ADE", "RETURN"},
        canonical_invoice=canonical_invoice,
    )
