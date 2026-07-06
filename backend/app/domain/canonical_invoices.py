from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping


MONEY = Decimal("0.01")


@dataclass(frozen=True)
class CanonicalInvoiceParty:
    title: str = ""
    tax_id: str = ""
    tax_office: str = ""
    address: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalInvoiceHeader:
    invoice_no: str = ""
    issue_date: str = ""
    ettn: str = ""
    scenario: str = ""
    invoice_type: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalInvoiceLine:
    description: str
    quantity: str = ""
    unit_price: str = ""
    taxable_amount: str = ""
    vat_rate: str = ""
    tax_amount: str = ""
    gross_amount: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalVatSummaryLine:
    rate: str
    taxable_amount: str = ""
    tax_amount: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalInvoiceTotals:
    goods_services_total: str = ""
    vat_total: str = ""
    special_tax_total: str = ""
    tax_inclusive_total: str = ""
    payable_total: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalInvoiceValidation:
    status: str
    reason_codes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalInvoice:
    source: str
    supplier_party: CanonicalInvoiceParty = CanonicalInvoiceParty()
    customer_party: CanonicalInvoiceParty = CanonicalInvoiceParty()
    header: CanonicalInvoiceHeader = CanonicalInvoiceHeader()
    line_items: tuple[CanonicalInvoiceLine, ...] = ()
    vat_summary: tuple[CanonicalVatSummaryLine, ...] = ()
    totals: CanonicalInvoiceTotals = CanonicalInvoiceTotals()
    validation: CanonicalInvoiceValidation = CanonicalInvoiceValidation(status="not_validated")
    ai_used: bool = False
    extraction_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalExtractionPolicy:
    enabled: bool = False
    max_input_chars: int = 12000
    max_provider_calls: int = 1


@dataclass(frozen=True)
class CanonicalExtractionRequest:
    document_text: str
    deterministic_payload: Mapping[str, object] = field(default_factory=dict)
    client_identity: Mapping[str, object] = field(default_factory=dict)
    max_input_chars: int = 12000

    def to_schema_payload(self) -> dict[str, object]:
        return {
            "document_text": self.document_text[: max(self.max_input_chars, 0)].strip(),
            "deterministic_payload": dict(self.deterministic_payload),
            "client_identity": dict(self.client_identity),
            "instructions": (
                "PDF metnini UBL benzeri canonical fatura JSON'una cevir. "
                "Urun/hizmet anlamini satici adindan cikarma; line_items sadece fatura satirlarindan gelsin. "
                "Hesap kodu, export karari veya muhasebe onayi uretme."
            ),
            "output_schema": canonical_extraction_output_schema(),
        }


def canonical_extraction_output_schema() -> dict[str, Any]:
    text_field = {"type": "string"}
    evidence_field = {"type": "array", "items": {"type": "string"}}
    party_schema = {
        "type": "object",
        "properties": {
            "title": text_field,
            "tax_id": text_field,
            "tax_office": text_field,
            "address": text_field,
            "evidence": evidence_field,
        },
        "required": ["title", "tax_id"],
        "additionalProperties": True,
    }
    line_schema = {
        "type": "object",
        "properties": {
            "description": text_field,
            "quantity": text_field,
            "unit_price": text_field,
            "taxable_amount": text_field,
            "vat_rate": text_field,
            "tax_amount": text_field,
            "gross_amount": text_field,
            "evidence": evidence_field,
        },
        "required": ["description"],
        "additionalProperties": True,
    }
    vat_schema = {
        "type": "object",
        "properties": {
            "rate": text_field,
            "taxable_amount": text_field,
            "tax_amount": text_field,
            "evidence": evidence_field,
        },
        "required": ["rate"],
        "additionalProperties": True,
    }
    return {
        "type": "object",
        "properties": {
            "supplier_party": party_schema,
            "customer_party": party_schema,
            "line_items": {"type": "array", "items": line_schema},
            "vat_summary": {"type": "array", "items": vat_schema},
            "totals": {
                "type": "object",
                "properties": {
                    "goods_services_total": text_field,
                    "vat_total": text_field,
                    "special_tax_total": text_field,
                    "tax_inclusive_total": text_field,
                    "payable_total": text_field,
                    "evidence": evidence_field,
                },
                "required": [],
                "additionalProperties": True,
            },
            "extraction_notes": evidence_field,
        },
        "required": ["supplier_party", "customer_party", "line_items", "vat_summary", "totals"],
        "additionalProperties": True,
    }


def _string(value: object) -> str:
    return str(value or "").strip()


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def canonical_invoice_from_ai_payload(payload: Mapping[str, object]) -> CanonicalInvoice:
    supplier = _mapping(payload.get("supplier_party"))
    customer = _mapping(payload.get("customer_party"))
    totals = _mapping(payload.get("totals"))
    line_items = tuple(
        CanonicalInvoiceLine(
            description=_string(line.get("description")),
            quantity=_string(line.get("quantity")),
            unit_price=_string(line.get("unit_price")),
            taxable_amount=_string(line.get("taxable_amount")),
            vat_rate=_string(line.get("vat_rate")),
            tax_amount=_string(line.get("tax_amount")),
            gross_amount=_string(line.get("gross_amount")),
            evidence=_strings(line.get("evidence")),
        )
        for item in payload.get("line_items") or []
        if isinstance(item, Mapping)
        if (line := _mapping(item)).get("description")
    )
    vat_summary = tuple(
        CanonicalVatSummaryLine(
            rate=_string(line.get("rate")),
            taxable_amount=_string(line.get("taxable_amount")),
            tax_amount=_string(line.get("tax_amount")),
            evidence=_strings(line.get("evidence")),
        )
        for item in payload.get("vat_summary") or []
        if isinstance(item, Mapping)
        if (line := _mapping(item)).get("rate") or line.get("taxable_amount") or line.get("tax_amount")
    )
    invoice = CanonicalInvoice(
        source="ai_canonical",
        supplier_party=CanonicalInvoiceParty(
            title=_string(supplier.get("title")),
            tax_id=_string(supplier.get("tax_id")),
            tax_office=_string(supplier.get("tax_office")),
            address=_string(supplier.get("address")),
            evidence=_strings(supplier.get("evidence")),
        ),
        customer_party=CanonicalInvoiceParty(
            title=_string(customer.get("title")),
            tax_id=_string(customer.get("tax_id")),
            tax_office=_string(customer.get("tax_office")),
            address=_string(customer.get("address")),
            evidence=_strings(customer.get("evidence")),
        ),
        line_items=line_items,
        vat_summary=vat_summary,
        totals=CanonicalInvoiceTotals(
            goods_services_total=_string(totals.get("goods_services_total")),
            vat_total=_string(totals.get("vat_total")),
            special_tax_total=_string(totals.get("special_tax_total")),
            tax_inclusive_total=_string(totals.get("tax_inclusive_total")),
            payable_total=_string(totals.get("payable_total")),
            evidence=_strings(totals.get("evidence")),
        ),
        ai_used=True,
        extraction_notes=_strings(payload.get("extraction_notes")),
    )
    return with_validation(invoice)


def _decimal(value: str) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    compact = raw.replace(" ", "")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    try:
        return Decimal(compact).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _sum(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0.00")).quantize(MONEY, rounding=ROUND_HALF_UP)


def _close(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return True
    return abs(left - right) <= Decimal("0.05")


def _line_tax(line: CanonicalInvoiceLine) -> Decimal | None:
    taxable = _decimal(line.taxable_amount)
    rate = _decimal(line.vat_rate)
    if taxable is None or rate is None:
        return None
    return (taxable * rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)


def validate_canonical_invoice(invoice: CanonicalInvoice) -> CanonicalInvoiceValidation:
    reasons: list[str] = []
    evidence: list[str] = []

    if not invoice.line_items:
        reasons.append("line_items_missing")

    line_taxables = [_decimal(line.taxable_amount) for line in invoice.line_items]
    line_taxes = [_decimal(line.tax_amount) for line in invoice.line_items]
    line_grosses = [_decimal(line.gross_amount) for line in invoice.line_items]
    taxable_sum = _sum([value for value in line_taxables if value is not None])
    tax_sum = _sum([value for value in line_taxes if value is not None])
    gross_sum = _sum([value for value in line_grosses if value is not None])

    for line in invoice.line_items:
        expected_tax = _line_tax(line)
        actual_tax = _decimal(line.tax_amount)
        if expected_tax is not None and actual_tax is not None and not _close(expected_tax, actual_tax):
            reasons.append("line_tax_amount_mismatch")
            evidence.append(f"line:{line.description[:60]}")

    if not _close(taxable_sum, _decimal(invoice.totals.goods_services_total)):
        reasons.append("line_total_mismatch")
    if not _close(tax_sum, _decimal(invoice.totals.vat_total)):
        reasons.append("vat_total_mismatch")

    summary_taxable_sum = _sum(
        [value for line in invoice.vat_summary if (value := _decimal(line.taxable_amount)) is not None]
    )
    summary_tax_sum = _sum([value for line in invoice.vat_summary if (value := _decimal(line.tax_amount)) is not None])
    if invoice.vat_summary and not _close(summary_taxable_sum, taxable_sum):
        reasons.append("vat_summary_taxable_mismatch")
    if invoice.vat_summary and not _close(summary_tax_sum, tax_sum):
        reasons.append("vat_summary_tax_mismatch")

    special_tax = _decimal(invoice.totals.special_tax_total) or Decimal("0.00")
    expected_gross = None
    if taxable_sum is not None and tax_sum is not None:
        expected_gross = (taxable_sum + tax_sum + special_tax).quantize(MONEY, rounding=ROUND_HALF_UP)
    total_gross = _decimal(invoice.totals.tax_inclusive_total) or _decimal(invoice.totals.payable_total)
    if not _close(expected_gross, total_gross):
        reasons.append("gross_total_mismatch")
    if gross_sum is not None and not _close(gross_sum, total_gross):
        reasons.append("line_gross_total_mismatch")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return CanonicalInvoiceValidation(
        status="valid" if not unique_reasons else "invalid",
        reason_codes=unique_reasons,
        evidence=tuple(dict.fromkeys(evidence)),
    )


def with_validation(invoice: CanonicalInvoice) -> CanonicalInvoice:
    return replace(invoice, validation=validate_canonical_invoice(invoice))
