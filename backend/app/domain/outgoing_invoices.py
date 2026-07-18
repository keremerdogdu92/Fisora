from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol
from uuid import uuid4
from xml.etree import ElementTree
from xml.sax.saxutils import escape


MONEY = Decimal("0.01")
ALLOWED_DOCUMENT_TYPES = {"efatura", "earsiv"}
ALLOWED_PROFILES = {
    "efatura": {"TEMELFATURA", "TICARIFATURA"},
    "earsiv": {"EARSIVFATURA"},
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def money(value: Any) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invoice amount must be numeric") from exc
    return result


def amount(value: Decimal) -> str:
    return f"{value.quantize(MONEY, rounding=ROUND_HALF_UP):.2f}"


def normalize_party(value: dict[str, Any], *, label: str) -> dict[str, str]:
    tax_id = "".join(ch for ch in str(value.get("tax_id") or "") if ch.isdigit())
    title = " ".join(str(value.get("title") or "").split())
    if len(tax_id) not in (10, 11):
        raise ValueError(f"{label} tax ID must contain 10 or 11 digits")
    if not title:
        raise ValueError(f"{label} title is required")
    return {
        "tax_id": tax_id,
        "title": title,
        "tax_office": str(value.get("tax_office") or "").strip(),
        "city": str(value.get("city") or "ISTANBUL").strip(),
        "district": str(value.get("district") or "").strip(),
        "email": str(value.get("email") or "").strip(),
    }


def normalize_lines(values: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, str]]:
    if not values:
        raise ValueError("At least one invoice line is required")
    lines: list[dict[str, str]] = []
    net_total = Decimal("0")
    tax_total = Decimal("0")
    for index, value in enumerate(values, start=1):
        name = " ".join(str(value.get("name") or "").split())
        quantity = money(value.get("quantity", "0"))
        unit_price = money(value.get("unit_price", "0"))
        vat_rate = money(value.get("vat_rate", "0"))
        if not name or quantity <= 0 or unit_price < 0 or vat_rate < 0:
            raise ValueError(f"Invoice line {index} is invalid")
        net = (quantity * unit_price).quantize(MONEY, rounding=ROUND_HALF_UP)
        tax = (net * vat_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
        lines.append(
            {
                "line_no": str(index),
                "name": name,
                "quantity": amount(quantity),
                "unit_code": str(value.get("unit_code") or "C62").strip(),
                "unit_price": amount(unit_price),
                "vat_rate": amount(vat_rate),
                "net_amount": amount(net),
                "tax_amount": amount(tax),
            }
        )
        net_total += net
        tax_total += tax
    totals = {
        "net_amount": amount(net_total),
        "tax_amount": amount(tax_total),
        "payable_amount": amount(net_total + tax_total),
    }
    return lines, totals


def _party_xml(party: dict[str, str]) -> str:
    scheme = "VKN" if len(party["tax_id"]) == 10 else "TCKN"
    return "".join(
        [
            "<cac:Party>",
            f'<cbc:EndpointID schemeID="{scheme}">{escape(party["tax_id"])}</cbc:EndpointID>',
            f'<cac:PartyIdentification><cbc:ID schemeID="{scheme}">{escape(party["tax_id"])}</cbc:ID></cac:PartyIdentification>',
            f"<cac:PartyName><cbc:Name>{escape(party['title'])}</cbc:Name></cac:PartyName>",
            "<cac:PostalAddress>",
            f"<cbc:CitySubdivisionName>{escape(party['district'])}</cbc:CitySubdivisionName>",
            f"<cbc:CityName>{escape(party['city'])}</cbc:CityName>",
            "<cac:Country><cbc:IdentificationCode>TR</cbc:IdentificationCode><cbc:Name>TURKIYE</cbc:Name></cac:Country>",
            "</cac:PostalAddress>",
            f"<cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>{escape(party['tax_office'])}</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>",
            f"<cac:PartyLegalEntity><cbc:RegistrationName>{escape(party['title'])}</cbc:RegistrationName></cac:PartyLegalEntity>",
            "</cac:Party>",
        ]
    )


def build_invoice_ubl(invoice: dict[str, Any]) -> bytes:
    currency = invoice["currency"]
    lines_xml: list[str] = []
    for line in invoice["lines"]:
        lines_xml.append(
            "".join(
                [
                    "<cac:InvoiceLine>",
                    f"<cbc:ID>{line['line_no']}</cbc:ID>",
                    f'<cbc:InvoicedQuantity unitCode="{escape(line["unit_code"])}">{line["quantity"]}</cbc:InvoicedQuantity>',
                    f'<cbc:LineExtensionAmount currencyID="{currency}">{line["net_amount"]}</cbc:LineExtensionAmount>',
                    "<cac:TaxTotal>",
                    f'<cbc:TaxAmount currencyID="{currency}">{line["tax_amount"]}</cbc:TaxAmount>',
                    "<cac:TaxSubtotal>",
                    f'<cbc:TaxableAmount currencyID="{currency}">{line["net_amount"]}</cbc:TaxableAmount>',
                    f'<cbc:TaxAmount currencyID="{currency}">{line["tax_amount"]}</cbc:TaxAmount>',
                    f"<cbc:Percent>{line['vat_rate']}</cbc:Percent>",
                    "<cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name><cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>",
                    "</cac:TaxSubtotal></cac:TaxTotal>",
                    f"<cac:Item><cbc:Name>{escape(line['name'])}</cbc:Name></cac:Item>",
                    f'<cac:Price><cbc:PriceAmount currencyID="{currency}">{line["unit_price"]}</cbc:PriceAmount></cac:Price>',
                    "</cac:InvoiceLine>",
                ]
            )
        )
    totals = invoice["totals"]
    content = "".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" ',
            'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" ',
            'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">',
            "<cbc:UBLVersionID>2.1</cbc:UBLVersionID><cbc:CustomizationID>TR1.2</cbc:CustomizationID>",
            f"<cbc:ProfileID>{invoice['profile']}</cbc:ProfileID>",
            f"<cbc:ID>{escape(invoice['invoice_no'])}</cbc:ID><cbc:CopyIndicator>false</cbc:CopyIndicator>",
            f"<cbc:UUID>{invoice['invoice_id']}</cbc:UUID><cbc:IssueDate>{invoice['issue_date']}</cbc:IssueDate>",
            "<cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>",
            f"<cbc:DocumentCurrencyCode>{currency}</cbc:DocumentCurrencyCode><cbc:LineCountNumeric>{len(invoice['lines'])}</cbc:LineCountNumeric>",
            f"<cac:AccountingSupplierParty>{_party_xml(invoice['supplier'])}</cac:AccountingSupplierParty>",
            f"<cac:AccountingCustomerParty>{_party_xml(invoice['customer'])}</cac:AccountingCustomerParty>",
            "<cac:TaxTotal>",
            f'<cbc:TaxAmount currencyID="{currency}">{totals["tax_amount"]}</cbc:TaxAmount></cac:TaxTotal>',
            "<cac:LegalMonetaryTotal>",
            f'<cbc:LineExtensionAmount currencyID="{currency}">{totals["net_amount"]}</cbc:LineExtensionAmount>',
            f'<cbc:TaxExclusiveAmount currencyID="{currency}">{totals["net_amount"]}</cbc:TaxExclusiveAmount>',
            f'<cbc:TaxInclusiveAmount currencyID="{currency}">{totals["payable_amount"]}</cbc:TaxInclusiveAmount>',
            f'<cbc:PayableAmount currencyID="{currency}">{totals["payable_amount"]}</cbc:PayableAmount>',
            "</cac:LegalMonetaryTotal>",
            *lines_xml,
            "</Invoice>",
        ]
    ).encode("utf-8")
    root = ElementTree.fromstring(content)
    if not root.tag.endswith("}Invoice"):
        raise ValueError("Generated document is not a UBL invoice")
    return content


class OutgoingInvoiceProvider(Protocol):
    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> dict[str, Any]: ...


class FakeOutgoingInvoiceProvider:
    def send(self, *, invoice: dict[str, Any], ubl_content: bytes) -> dict[str, Any]:
        digest = hashlib.sha256(ubl_content).hexdigest()
        return {
            "provider": "fake",
            "provider_document_id": f"FAKE-{digest[:16].upper()}",
            "provider_status": "accepted",
            "receipt": {"ubl_sha256": digest, "mode": "local_fake"},
        }


class OutgoingInvoiceService:
    def __init__(self, *, store: Any, provider: OutgoingInvoiceProvider | None = None) -> None:
        self.store = store
        self.provider = provider or FakeOutgoingInvoiceProvider()

    def create_draft(self, *, client_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        document_type = str(payload.get("document_type") or "").lower()
        profile = str(payload.get("profile") or "").upper()
        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise ValueError("Document type must be efatura or earsiv")
        if profile not in ALLOWED_PROFILES[document_type]:
            raise ValueError("Invoice profile is not valid for the document type")
        invoice_no = str(payload.get("invoice_no") or "").strip()
        issue_date = str(payload.get("issue_date") or "").strip()
        if not invoice_no or len(issue_date) != 10:
            raise ValueError("Invoice number and ISO issue date are required")
        lines, totals = normalize_lines(payload.get("lines") or [])
        now = utc_now()
        invoice = {
            "invoice_id": str(uuid4()),
            "client_id": client_id,
            "status": "draft",
            "document_type": document_type,
            "profile": profile,
            "invoice_no": invoice_no,
            "issue_date": issue_date,
            "currency": str(payload.get("currency") or "TRY").upper(),
            "supplier": normalize_party(payload.get("supplier") or {}, label="Supplier"),
            "customer": normalize_party(payload.get("customer") or {}, label="Customer"),
            "lines": lines,
            "totals": totals,
            "history": [{"status": "draft", "actor_user_id": actor_user_id, "at": now}],
            "created_at": now,
            "updated_at": now,
        }
        return self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)

    def approve(self, *, client_id: str, invoice_id: str, actor_user_id: str) -> dict[str, Any]:
        invoice = self._get(client_id, invoice_id)
        if invoice.get("status") != "draft":
            raise ValueError("Only a draft invoice can be approved")
        ubl_content = build_invoice_ubl(invoice)
        now = utc_now()
        invoice.update(
            {
                "status": "approved",
                "ubl_base64": base64.b64encode(ubl_content).decode("ascii"),
                "ubl_sha256": hashlib.sha256(ubl_content).hexdigest(),
                "approved_at": now,
                "approved_by": actor_user_id,
                "updated_at": now,
            }
        )
        invoice.setdefault("history", []).append({"status": "approved", "actor_user_id": actor_user_id, "at": now})
        return self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)

    def send(
        self, *, client_id: str, invoice_id: str, idempotency_key: str, actor_user_id: str
    ) -> dict[str, Any]:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise ValueError("Idempotency key is required")
        claimed, invoice = self.store.claim_outgoing_invoice_send(
            client_id=client_id, invoice_id=invoice_id, idempotency_key=idempotency_key
        )
        if not invoice:
            raise ValueError("Outgoing invoice not found")
        if not claimed:
            return invoice
        try:
            ubl_content = base64.b64decode(invoice.get("ubl_base64") or "", validate=True)
            result = self.provider.send(invoice=invoice, ubl_content=ubl_content)
            now = utc_now()
            invoice.update({**result, "status": "sent", "sent_at": now, "sent_by": actor_user_id, "updated_at": now})
            invoice.setdefault("history", []).append({"status": "sent", "actor_user_id": actor_user_id, "at": now})
        except Exception as exc:
            now = utc_now()
            invoice.update({"status": "failed", "last_error": str(exc), "updated_at": now})
            invoice.setdefault("history", []).append({"status": "failed", "actor_user_id": actor_user_id, "at": now})
            self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)
            raise
        return self.store.save_outgoing_invoice(client_id=client_id, invoice=invoice)

    def get(self, *, client_id: str, invoice_id: str) -> dict[str, Any]:
        return self._get(client_id, invoice_id)

    def list(self, *, client_id: str) -> list[dict[str, Any]]:
        return self.store.list_outgoing_invoices(client_id=client_id)

    def _get(self, client_id: str, invoice_id: str) -> dict[str, Any]:
        invoice = self.store.get_outgoing_invoice(client_id=client_id, invoice_id=invoice_id)
        if not invoice:
            raise ValueError("Outgoing invoice not found")
        return invoice
