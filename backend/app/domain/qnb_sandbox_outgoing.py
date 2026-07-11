from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from xml.etree import ElementTree
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class QnbSandboxParty:
    vkn: str
    title: str
    mailbox_label: str
    city: str = "ISTANBUL"
    district: str = "KADIKOY"
    tax_office: str = "KADIKOY"


def validate_qnb_sandbox_invoice_ubl(
    content: bytes,
    *,
    expected_invoice_no: str,
    expected_supplier_vkn: str,
    expected_customer_vkn: str,
) -> None:
    root = ElementTree.fromstring(content)
    namespaces = {
        "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }
    if root.tag != f"{{{namespaces['inv']}}}Invoice":
        raise ValueError("QNB sandbox document root must be UBL Invoice")

    def text(path: str) -> str:
        element = root.find(path, namespaces)
        return (element.text or "").strip() if element is not None else ""

    values = {
        "invoice_no": text("cbc:ID"),
        "profile": text("cbc:ProfileID"),
        "supplier_vkn": text("cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID"),
        "customer_vkn": text("cac:AccountingCustomerParty/cac:Party/cac:PartyIdentification/cbc:ID"),
        "payable": text("cac:LegalMonetaryTotal/cbc:PayableAmount"),
    }
    expected = {
        "invoice_no": expected_invoice_no,
        "profile": "TEMELFATURA",
        "supplier_vkn": expected_supplier_vkn,
        "customer_vkn": expected_customer_vkn,
        "payable": "120.00",
    }
    mismatches = [name for name, value in expected.items() if values.get(name) != value]
    if mismatches:
        raise ValueError(f"QNB sandbox UBL validation failed: {', '.join(mismatches)}")


def build_qnb_sandbox_invoice_ubl(
    *,
    invoice_no: str,
    invoice_uuid: str,
    issue_date: date,
    issue_time: time,
    supplier: QnbSandboxParty,
    customer: QnbSandboxParty,
    item_name: str = "Fisora QNB sandbox test hizmeti",
    quantity: Decimal = Decimal("1"),
    unit_price: Decimal = Decimal("100.00"),
    vat_rate: Decimal = Decimal("20"),
) -> bytes:
    line_extension = (quantity * unit_price).quantize(Decimal("0.01"))
    tax_amount = (line_extension * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    payable = line_extension + tax_amount

    def amount(value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01')):.2f}"

    def party_xml(party: QnbSandboxParty) -> str:
        return "".join(
            [
                "<cac:Party>",
                f'<cbc:EndpointID schemeID="VKN">{escape(party.vkn)}</cbc:EndpointID>',
                f'<cac:PartyIdentification><cbc:ID schemeID="VKN">{escape(party.vkn)}</cbc:ID></cac:PartyIdentification>',
                f"<cac:PartyName><cbc:Name>{escape(party.title)}</cbc:Name></cac:PartyName>",
                "<cac:PostalAddress>",
                f"<cbc:CitySubdivisionName>{escape(party.district)}</cbc:CitySubdivisionName>",
                f"<cbc:CityName>{escape(party.city)}</cbc:CityName>",
                '<cac:Country><cbc:IdentificationCode>TR</cbc:IdentificationCode><cbc:Name>TURKIYE</cbc:Name></cac:Country>',
                "</cac:PostalAddress>",
                f"<cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>{escape(party.tax_office)}</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>",
                f"<cac:PartyLegalEntity><cbc:RegistrationName>{escape(party.title)}</cbc:RegistrationName></cac:PartyLegalEntity>",
                "</cac:Party>",
            ]
        )

    xml = "".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" ',
            'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" ',
            'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">',
            "<cbc:UBLVersionID>2.1</cbc:UBLVersionID>",
            "<cbc:CustomizationID>TR1.2</cbc:CustomizationID>",
            "<cbc:ProfileID>TEMELFATURA</cbc:ProfileID>",
            f"<cbc:ID>{escape(invoice_no)}</cbc:ID>",
            "<cbc:CopyIndicator>false</cbc:CopyIndicator>",
            f"<cbc:UUID>{escape(invoice_uuid)}</cbc:UUID>",
            f"<cbc:IssueDate>{issue_date.isoformat()}</cbc:IssueDate>",
            f"<cbc:IssueTime>{issue_time.replace(microsecond=0).isoformat()}</cbc:IssueTime>",
            "<cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>",
            "<cbc:Note>Fisora QNB sandbox entegrasyon testi</cbc:Note>",
            "<cbc:DocumentCurrencyCode>TRY</cbc:DocumentCurrencyCode>",
            "<cbc:LineCountNumeric>1</cbc:LineCountNumeric>",
            "<cac:AccountingSupplierParty>",
            party_xml(supplier),
            "</cac:AccountingSupplierParty>",
            "<cac:AccountingCustomerParty>",
            party_xml(customer),
            "</cac:AccountingCustomerParty>",
            "<cac:TaxTotal>",
            f'<cbc:TaxAmount currencyID="TRY">{amount(tax_amount)}</cbc:TaxAmount>',
            "<cac:TaxSubtotal>",
            f'<cbc:TaxableAmount currencyID="TRY">{amount(line_extension)}</cbc:TaxableAmount>',
            f'<cbc:TaxAmount currencyID="TRY">{amount(tax_amount)}</cbc:TaxAmount>',
            f"<cbc:CalculationSequenceNumeric>1</cbc:CalculationSequenceNumeric><cbc:Percent>{vat_rate}</cbc:Percent>",
            "<cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>",
            "</cac:TaxSubtotal>",
            "</cac:TaxTotal>",
            "<cac:LegalMonetaryTotal>",
            f'<cbc:LineExtensionAmount currencyID="TRY">{amount(line_extension)}</cbc:LineExtensionAmount>',
            f'<cbc:TaxExclusiveAmount currencyID="TRY">{amount(line_extension)}</cbc:TaxExclusiveAmount>',
            f'<cbc:TaxInclusiveAmount currencyID="TRY">{amount(payable)}</cbc:TaxInclusiveAmount>',
            '<cbc:AllowanceTotalAmount currencyID="TRY">0.00</cbc:AllowanceTotalAmount>',
            f'<cbc:PayableAmount currencyID="TRY">{amount(payable)}</cbc:PayableAmount>',
            "</cac:LegalMonetaryTotal>",
            "<cac:InvoiceLine>",
            "<cbc:ID>1</cbc:ID>",
            f'<cbc:InvoicedQuantity unitCode="C62">{quantity}</cbc:InvoicedQuantity>',
            f'<cbc:LineExtensionAmount currencyID="TRY">{amount(line_extension)}</cbc:LineExtensionAmount>',
            "<cac:TaxTotal>",
            f'<cbc:TaxAmount currencyID="TRY">{amount(tax_amount)}</cbc:TaxAmount>',
            "<cac:TaxSubtotal>",
            f'<cbc:TaxableAmount currencyID="TRY">{amount(line_extension)}</cbc:TaxableAmount>',
            f'<cbc:TaxAmount currencyID="TRY">{amount(tax_amount)}</cbc:TaxAmount>',
            f"<cbc:Percent>{vat_rate}</cbc:Percent>",
            "<cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>",
            "</cac:TaxSubtotal>",
            "</cac:TaxTotal>",
            f"<cac:Item><cbc:Name>{escape(item_name)}</cbc:Name></cac:Item>",
            f'<cac:Price><cbc:PriceAmount currencyID="TRY">{amount(unit_price)}</cbc:PriceAmount></cac:Price>',
            "</cac:InvoiceLine>",
            "</Invoice>",
        ]
    )
    content = xml.encode("utf-8")
    validate_qnb_sandbox_invoice_ubl(
        content,
        expected_invoice_no=invoice_no,
        expected_supplier_vkn=supplier.vkn,
        expected_customer_vkn=customer.vkn,
    )
    return content
