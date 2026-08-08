from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

from app.domain.canonical_invoices import (
    CanonicalInvoice,
    CanonicalInvoiceHeader,
    CanonicalInvoiceLine,
    CanonicalInvoiceValidation,
    CanonicalMonetaryComponent,
    CanonicalInvoiceParty,
    CanonicalTaxComponent,
    CanonicalInvoiceTotals,
    CanonicalVatSummaryLine,
    normalize_monetary_component,
    normalize_tax_component,
    _normalized_decimal_text,
    canonical_vat_group_id,
    with_validation,
)
from app.domain.pdf_invoices import ParsedInvoice
from app.domain.provider_directory import resolve_provider_profile
from app.domain.utility_invoice_markers import detect_utility_invoice_markers


TAX_ID_RE = re.compile(r"^\d{10,11}$")
GENERIC_TAX_SCHEME_NAMES = {"KDV", "VAT", "KATMA DEGER VERGISI"}
VAT_TAX_TYPE_CODES = {"0015", "KDV"}
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


def _first_descendant(root: ET.Element | None, local_name: str) -> ET.Element | None:
    if root is None:
        return None
    return next((element for element in root.iter() if _local_name(element.tag) == local_name), None)


def _first_direct_text(root: ET.Element, local_name: str) -> str:
    return _text(_direct_child(root, local_name))


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
        if _local_name(element.tag) != "TaxSubtotal":
            continue
        identity = _tax_identity(element)
        if not _is_vat_tax_scheme(identity["tax_scheme_code"]):
            continue
        value = identity["vat_rate"].replace(",", ".")
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


def _tax_identity(element: ET.Element) -> dict[str, str]:
    category = _first_descendant(element, "ClassifiedTaxCategory")
    if category is None:
        category = _first_descendant(element, "TaxCategory")
    if category is None:
        return {
            "tax_scheme_code": "",
            "tax_category_code": "",
            "vat_rate": "",
            "exemption_reason_code": "",
        }

    scheme = _first_descendant(category, "TaxScheme")
    tax_subtotal = _first_descendant(element, "TaxSubtotal")
    return {
        "tax_scheme_code": _first_text_under(scheme, ("TaxTypeCode", "ID")) if scheme is not None else "",
        "tax_category_code": _first_direct_text(category, "ID"),
        "vat_rate": (
            _first_text_under(category, ("Percent",))
            or _first_direct_text(tax_subtotal, "Percent")
            or _first_direct_text(element, "Percent")
        ),
        "exemption_reason_code": _first_text_under(category, ("TaxExemptionReasonCode",)),
    }


def _is_vat_tax_scheme(tax_scheme_code: str) -> bool:
    return not tax_scheme_code.strip() or tax_scheme_code.strip().upper() in VAT_TAX_TYPE_CODES


def _tax_subtotal_amounts(root: ET.Element) -> tuple[str, str]:
    vat_total = Decimal("0.00")
    special_tax_total = Decimal("0.00")
    has_vat = False
    has_special = False
    tax_totals = _direct_children(root, "TaxTotal")
    for tax_total in tax_totals:
        for subtotal in (element for element in tax_total.iter() if _local_name(element.tag) == "TaxSubtotal"):
            identity = _tax_identity(subtotal)
            amount = _decimal_text(_first_text_under(subtotal, ("TaxAmount",)))
            if not amount:
                continue
            if _is_vat_tax_scheme(identity["tax_scheme_code"]):
                vat_total += Decimal(amount)
                has_vat = True
            else:
                special_tax_total += Decimal(amount)
                has_special = True
    return (
        f"{vat_total:.2f}" if has_vat else "",
        f"{special_tax_total:.2f}" if has_special else "",
    )


def _canonical_tax_components(root: ET.Element) -> tuple[CanonicalTaxComponent, ...]:
    components: list[CanonicalTaxComponent] = []
    for tax_total in _direct_children(root, "TaxTotal"):
        for index, subtotal in enumerate(
            (element for element in tax_total.iter() if _local_name(element.tag) == "TaxSubtotal"),
            start=1,
        ):
            identity = _tax_identity(subtotal)
            scheme = _first_descendant(subtotal, "TaxScheme")
            label = _first_text_under(scheme, ("Name",)) if scheme is not None else ""
            position = f"xml:TaxSubtotal[{index}]"
            components.append(
                normalize_tax_component(
                    source_label=label,
                    source_code=identity["tax_scheme_code"],
                    rate=identity["vat_rate"],
                    taxable_amount=_first_amount_under(subtotal, ("TaxableAmount",)),
                    tax_amount=_first_amount_under(subtotal, ("TaxAmount",)),
                    source_position=position,
                    evidence=(position,),
                )
            )
    return tuple(components)


def _canonical_monetary_components(
    lines: tuple[CanonicalInvoiceLine, ...],
) -> tuple[CanonicalMonetaryComponent, ...]:
    return tuple(
        normalize_monetary_component(
            source_label=line.description,
            source_amount=line.taxable_amount,
            source_position=line.source_position,
            evidence=line.evidence,
        )
        for line in lines
    )


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
        tax_identity = _tax_identity(line)
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
                    vat_rate=_normalized_decimal_text(tax_identity["vat_rate"]),
                    tax_amount=tax_amount,
                    gross_amount=_format_sum(taxable_amount, tax_amount),
                    tax_scheme_code=tax_identity["tax_scheme_code"],
                    tax_category_code=tax_identity["tax_category_code"],
                    exemption_reason_code=tax_identity["exemption_reason_code"],
                    vat_group_id=canonical_vat_group_id(**tax_identity),
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
            tax_identity = _tax_identity(subtotal)
            if not _is_vat_tax_scheme(tax_identity["tax_scheme_code"]):
                continue
            summary.append(
                CanonicalVatSummaryLine(
                    rate=_normalized_decimal_text(tax_identity["vat_rate"]),
                    taxable_amount=_first_amount_under(subtotal, ("TaxableAmount",)),
                    tax_amount=_first_amount_under(subtotal, ("TaxAmount",)),
                    tax_scheme_code=tax_identity["tax_scheme_code"],
                    tax_category_code=tax_identity["tax_category_code"],
                    exemption_reason_code=tax_identity["exemption_reason_code"],
                    vat_group_id=canonical_vat_group_id(**tax_identity),
                    evidence=(f"xml:TaxSubtotal[{index}]",),
                )
            )
    return tuple(line for line in summary if line.rate or line.taxable_amount or line.tax_amount)


def _assign_single_header_vat_group_to_lines(
    lines: tuple[CanonicalInvoiceLine, ...],
    vat_summary: tuple[CanonicalVatSummaryLine, ...],
    *,
    special_tax_total: str,
) -> tuple[CanonicalInvoiceLine, ...]:
    """Allocate one explicitly declared header VAT group across source lines.

    This is valid only when the source establishes that every line belongs to
    the sole VAT group. A declared non-VAT utility tax may be included in that
    group's VAT base; it stays a header-level utility-cost component rather
    than being invented as a separate source line.
    """
    if len(vat_summary) != 1 or not lines or any(line.vat_rate for line in lines):
        return lines
    summary = vat_summary[0]
    try:
        taxable_amounts = [Decimal(line.taxable_amount) for line in lines]
        declared_taxable = Decimal(summary.taxable_amount)
        declared_tax = Decimal(summary.tax_amount)
        special_tax = Decimal(special_tax_total or "0")
    except (InvalidOperation, ValueError):
        return lines
    source_taxable = sum(taxable_amounts, Decimal("0.00"))
    if declared_taxable <= Decimal("0.00") or source_taxable not in {
        declared_taxable,
        declared_taxable - special_tax,
    }:
        return lines
    allocated_taxes: list[Decimal] = []
    allocated_so_far = Decimal("0.00")
    for index, taxable_amount in enumerate(taxable_amounts):
        if index == len(taxable_amounts) - 1:
            tax_amount = declared_tax - allocated_so_far
        else:
            tax_amount = (declared_tax * taxable_amount / declared_taxable).quantize(Decimal("0.01"))
            allocated_so_far += tax_amount
        allocated_taxes.append(tax_amount)
    return tuple(
        replace(
            line,
            vat_rate=summary.rate,
            tax_amount=f"{tax_amount:.2f}",
            gross_amount=_format_sum(line.taxable_amount, f"{tax_amount:.2f}"),
            tax_scheme_code=summary.tax_scheme_code,
            tax_category_code=summary.tax_category_code,
            exemption_reason_code=summary.exemption_reason_code,
            vat_group_id=summary.vat_group_id,
            evidence=(*line.evidence, "xml:TaxSubtotal[header-pro-rata]"),
        )
        for line, tax_amount in zip(lines, allocated_taxes, strict=True)
    )


def _complete_single_header_vat_taxable(
    lines: tuple[CanonicalInvoiceLine, ...],
    vat_summary: tuple[CanonicalVatSummaryLine, ...],
) -> tuple[CanonicalVatSummaryLine, ...]:
    if len(vat_summary) != 1 or not lines or vat_summary[0].taxable_amount:
        return vat_summary
    summary = vat_summary[0]
    try:
        source_taxable = sum((Decimal(line.taxable_amount) for line in lines), Decimal("0.00"))
        declared_tax = Decimal(summary.tax_amount)
        rate = Decimal(summary.rate)
    except (InvalidOperation, ValueError):
        return vat_summary
    expected_tax = (source_taxable * rate / Decimal("100")).quantize(Decimal("0.01"))
    if source_taxable <= 0 or abs(expected_tax - declared_tax) > Decimal("0.05"):
        return vat_summary
    return (
        replace(
            summary,
            taxable_amount=f"{source_taxable:.2f}",
            evidence=(*summary.evidence, "xml:TaxSubtotal[taxable-derived-from-lines]"),
        ),
    )


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
    vat_total, special_tax_total = _tax_subtotal_amounts(root)
    tax_components = _canonical_tax_components(root)
    line_items = _canonical_invoice_lines(root)
    vat_summary = _canonical_vat_summary(root)
    vat_summary = _complete_single_header_vat_taxable(line_items, vat_summary)
    if len(line_items) == 1 and not line_items[0].vat_rate and len(vat_summary) == 1:
        line = line_items[0]
        vat = vat_summary[0]
        gross = _format_sum(line.taxable_amount, vat.tax_amount)
        line_items = (
            replace(
                line,
                vat_rate=vat.rate,
                tax_amount=vat.tax_amount,
                gross_amount=gross,
                tax_scheme_code=vat.tax_scheme_code,
                tax_category_code=vat.tax_category_code,
                exemption_reason_code=vat.exemption_reason_code,
                vat_group_id=vat.vat_group_id,
                evidence=(*line.evidence, "xml:TaxSubtotal[header-single-line]"),
            ),
        )
    else:
        line_items = _assign_single_header_vat_group_to_lines(
            line_items,
            vat_summary,
            special_tax_total=special_tax_total,
        )
    monetary_components = _canonical_monetary_components(line_items)
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
        line_items=line_items,
        vat_summary=vat_summary,
        tax_components=tax_components,
        monetary_components=monetary_components,
        totals=CanonicalInvoiceTotals(
            goods_services_total=(
                _first_amount_under(legal_totals, ("TaxExclusiveAmount",))
                or _first_amount_under(legal_totals, ("LineExtensionAmount",))
            ),
            allowance_total=_first_amount_under(legal_totals, ("AllowanceTotalAmount",)),
            vat_total=vat_total or _first_amount(root, ("TaxAmount",)),
            special_tax_total=special_tax_total,
            tax_inclusive_total=_first_amount_under(legal_totals, ("TaxInclusiveAmount",)),
            payable_total=_first_amount_under(legal_totals, ("PayableAmount",)),
            evidence=("xml:LegalMonetaryTotal",),
        ),
    )
    return with_validation(invoice)


UTILITY_HEADER_GROUNDED_LINE_REASONS = frozenset(
    {
        "line_vat_rate_missing",
        "line_tax_amount_missing",
        "line_total_mismatch",
        "vat_total_mismatch",
        "vat_summary_taxable_mismatch",
        "vat_summary_tax_mismatch",
        "vat_group_lines_missing",
        "vat_group_unexpected_lines",
        "vat_group_taxable_mismatch",
        "vat_group_tax_mismatch",
        "line_gross_total_mismatch",
    }
)


def _mark_header_grounded_utility_partial(
    invoice: CanonicalInvoice,
    *,
    service_profile: str,
) -> CanonicalInvoice:
    reasons = set(invoice.validation.reason_codes)
    if (
        not service_profile
        or invoice.validation.status != "invalid"
        or not reasons
        or not reasons.issubset(UTILITY_HEADER_GROUNDED_LINE_REASONS)
        or not invoice.supplier_party.tax_id
        or not invoice.customer_party.tax_id
        or not invoice.totals.payable_total
        or not invoice.totals.vat_total
        or not invoice.tax_components
        or not any((_decimal_text(line.taxable_amount) or "0") != "0.00" for line in invoice.line_items)
    ):
        return invoice
    return replace(
        invoice,
        validation=CanonicalInvoiceValidation(
            status="partial_valid",
            reason_codes=invoice.validation.reason_codes,
            evidence=(*invoice.validation.evidence, "xml:utility-header-grounded"),
        ),
        extraction_notes=tuple(dict.fromkeys((*invoice.extraction_notes, "utility_header_grounded_partial"))),
    )


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
    provider_match = resolve_provider_profile(
        supplier_tax_id=supplier.tax_id,
        supplier_title=supplier.title,
        source="xml",
    )
    invoice_type_code = _first_text(root, ("InvoiceTypeCode",))
    canonical_invoice = build_xml_canonical_invoice(root)
    canonical_invoice = _mark_header_grounded_utility_partial(
        canonical_invoice,
        service_profile=provider_match.service_profile,
    )
    utility_exception_markers = detect_utility_invoice_markers(
        service_profile=provider_match.service_profile,
        source="xml",
        line_descriptions=tuple(line.description for line in canonical_invoice.line_items),
    )
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
        goods_services_total=canonical_invoice.totals.goods_services_total,
        vat_total=canonical_invoice.totals.vat_total,
        special_tax_total=canonical_invoice.totals.special_tax_total,
        tax_inclusive_total=canonical_invoice.totals.tax_inclusive_total,
        payable_total=canonical_invoice.totals.payable_total or payable_total,
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
        provider_id=provider_match.provider_id,
        service_profile=provider_match.service_profile,
        provider_match_kind=provider_match.match_kind,
        provider_match_reason=provider_match.reason_code,
        provider_directory_version=provider_match.directory_version,
        utility_exception_markers=utility_exception_markers,
        tax_components=canonical_invoice.tax_components,
        monetary_components=canonical_invoice.monetary_components,
    )
