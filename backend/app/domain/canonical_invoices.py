from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import re
from typing import Any, Mapping
import unicodedata


MONEY = Decimal("0.01")


@dataclass(frozen=True)
class CanonicalTaxComponent:
    source_label: str = ""
    source_code: str = ""
    rate: str = ""
    taxable_amount: str = ""
    tax_amount: str = ""
    source_position: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)
    canonical_tax_kind: str = "unknown_non_vat_tax"
    normalization_confidence: str = "unknown"
    accounting_treatment: str = "unresolved"


@dataclass(frozen=True)
class CanonicalMonetaryComponent:
    source_label: str = ""
    source_amount: str = ""
    source_position: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)
    canonical_component_kind: str = "service_charge"
    normalization_confidence: str = "unknown"
    accounting_treatment: str = "related_service_expense"


def _normalized_tax_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", folded.upper()).strip()


def normalize_tax_component(
    *,
    source_label: str,
    source_code: str,
    rate: str,
    taxable_amount: str,
    tax_amount: str,
    source_position: str,
    evidence: tuple[str, ...] = (),
) -> CanonicalTaxComponent:
    code = str(source_code or "").strip().upper()
    label = _normalized_tax_text(source_label)
    if code in {"0015", "KDV", "VAT"} or label in {"KDV", "VAT", "KATMA DEGER VERGISI"}:
        kind, treatment, confidence = "vat", "deductible_vat", "explicit"
    elif code == "4080" or "OZEL ILETISIM" in label or label == "OIV":
        kind, treatment, confidence = "special_communication_tax", "unresolved", "explicit"
    elif code == "4071" or "ELK.HAVAGAZ.TUK" in label or "ELEKTRIK TUKETIM" in label:
        kind, treatment, confidence = "electricity_consumption_tax", "related_service_expense", "explicit"
    elif code == "8006" or "TELSIZ" in label:
        kind, treatment, confidence = "radio_usage_fee", "related_service_expense", "explicit"
    else:
        kind, treatment, confidence = "unknown_non_vat_tax", "unresolved", "unknown"
    return CanonicalTaxComponent(
        source_label=str(source_label or "").strip(),
        source_code=str(source_code or "").strip(),
        rate=str(rate or "").strip(),
        taxable_amount=str(taxable_amount or "").strip(),
        tax_amount=str(tax_amount or "").strip(),
        source_position=str(source_position or "").strip(),
        evidence=tuple(evidence),
        canonical_tax_kind=kind,
        normalization_confidence=confidence,
        accounting_treatment=treatment,
    )


def normalize_monetary_component(
    *,
    source_label: str,
    source_amount: str,
    source_position: str,
    evidence: tuple[str, ...] = (),
) -> CanonicalMonetaryComponent:
    label = _normalized_tax_text(source_label)
    if any(token in label for token in ("ONCEKI AYDAN DEVIR", "ONCEKI DONEM", "GECEN DONEM", "DEVREDEN BAKIYE")):
        kind, treatment, confidence = "prior_period_balance", "exclude_current_period", "explicit"
    elif "TAKSIT" in label:
        kind, treatment, confidence = "installment_charge", "related_service_expense", "explicit"
    elif "CIHAZ" in label or "BAGLANT" in label:
        kind, treatment, confidence = "device_connection_charge", "related_service_expense", "explicit"
    elif "YUVARLAMA" in label:
        kind, treatment, confidence = "rounding_adjustment", "related_service_expense", "explicit"
    elif "INDIRIM" in label:
        kind, treatment, confidence = "discount", "reduce_related_service_expense", "explicit"
    else:
        kind, treatment, confidence = "service_charge", "related_service_expense", "inferred"
    return CanonicalMonetaryComponent(
        source_label=str(source_label or "").strip(),
        source_amount=str(source_amount or "").strip(),
        source_position=str(source_position or "").strip(),
        evidence=tuple(evidence),
        canonical_component_kind=kind,
        normalization_confidence=confidence,
        accounting_treatment=treatment,
    )


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
    original_invoice_no: str = ""
    original_invoice_date: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalInvoiceLine:
    description: str
    canonical_line_id: str = ""
    source_position: str = ""
    external_line_id: str = ""
    quantity: str = ""
    unit_code: str = ""
    unit_price: str = ""
    taxable_amount: str = ""
    vat_rate: str = ""
    tax_amount: str = ""
    gross_amount: str = ""
    tax_scheme_code: str = ""
    tax_category_code: str = ""
    exemption_reason_code: str = ""
    vat_group_id: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalVatSummaryLine:
    rate: str
    taxable_amount: str = ""
    tax_amount: str = ""
    tax_scheme_code: str = ""
    tax_category_code: str = ""
    exemption_reason_code: str = ""
    vat_group_id: str = ""
    contributing_line_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CanonicalInvoiceTotals:
    goods_services_total: str = ""
    allowance_total: str = ""
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
class CanonicalLineDecisionCoverage:
    status: str
    expected_ids: tuple[str, ...] = ()
    received_ids: tuple[str, ...] = ()
    missing_ids: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()
    unknown_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalInvoice:
    source: str
    supplier_party: CanonicalInvoiceParty = CanonicalInvoiceParty()
    customer_party: CanonicalInvoiceParty = CanonicalInvoiceParty()
    header: CanonicalInvoiceHeader = CanonicalInvoiceHeader()
    line_items: tuple[CanonicalInvoiceLine, ...] = ()
    vat_summary: tuple[CanonicalVatSummaryLine, ...] = ()
    tax_components: tuple[CanonicalTaxComponent, ...] = ()
    monetary_components: tuple[CanonicalMonetaryComponent, ...] = ()
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
    document_bytes: bytes = field(default=b"", repr=False, compare=False)
    document_mime_type: str = "application/pdf"
    deterministic_payload: Mapping[str, object] = field(default_factory=dict)
    client_identity: Mapping[str, object] = field(default_factory=dict)
    max_input_chars: int = 12000
    mode: str = "repair"

    def to_schema_payload(self) -> dict[str, object]:
        mode = str(self.mode or "repair").strip().lower()
        if mode not in {"repair", "discovery"}:
            raise ValueError("canonical extraction mode must be repair or discovery")
        raw_lines = self.deterministic_payload.get("line_items", ())
        line_ids = tuple(
            str(item.get("canonical_line_id") or "")
            for item in raw_lines
            if isinstance(item, Mapping) and str(item.get("canonical_line_id") or "")
        )
        return {
            "mode": mode,
            "document_text": self.document_text[: max(self.max_input_chars, 0)].strip(),
            "deterministic_payload": dict(self.deterministic_payload),
            "client_identity": dict(self.client_identity),
            "instructions": (
                "Belgedeki tum fatura satirlarini ve kesin kaynak konumlarini gozlemle. "
                "Belgede yazmayan degeri bos birak; hesaplama veya muhasebe karari yapma. "
                "canonical_line_id ve external_line_id alanlarini bos don."
                if mode == "discovery"
                else
                "Yalniz verilen canonical line_items satirlarini belge kanitiyla tamamla. "
                "Her canonical_line_id icin tam bir sonuc don; kimlik ekleme, silme veya degistirme. "
                "Bir deger belgede acikca yazmiyorsa bos string don; hesaplama yapma."
            ),
            "output_schema": canonical_extraction_output_schema(line_ids=line_ids, mode=mode),
        }


def canonical_extraction_output_schema(
    *,
    line_ids: tuple[str, ...] = (),
    mode: str = "repair",
) -> dict[str, Any]:
    resolved_mode = str(mode or "repair").strip().lower()
    if resolved_mode not in {"repair", "discovery"}:
        raise ValueError("canonical extraction mode must be repair or discovery")
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
        "required": ["title", "tax_id", "tax_office", "address", "evidence"],
        "additionalProperties": False,
    }
    line_schema = {
        "type": "object",
        "properties": {
            "canonical_line_id": {
                "type": "string",
                **(
                    {"enum": [""]}
                    if resolved_mode == "discovery"
                    else ({"enum": list(line_ids)} if line_ids else {})
                ),
            },
            "source_position": text_field,
            "external_line_id": text_field,
            "description": text_field,
            "observed_quantity": text_field,
            "observed_unit_code": text_field,
            "observed_unit_price": text_field,
            "observed_taxable_amount": text_field,
            "observed_vat_rate": text_field,
            "observed_tax_amount": text_field,
            "observed_gross_amount": text_field,
            "evidence": evidence_field,
        },
        "required": [
            "canonical_line_id",
            "source_position",
            "external_line_id",
            "description",
            "observed_quantity",
            "observed_unit_code",
            "observed_unit_price",
            "observed_taxable_amount",
            "observed_vat_rate",
            "observed_tax_amount",
            "observed_gross_amount",
            "evidence",
        ],
        "additionalProperties": False,
    }
    vat_schema = {
        "type": "object",
        "properties": {
            "observed_rate": text_field,
            "observed_taxable_amount": text_field,
            "observed_tax_amount": text_field,
            "evidence": evidence_field,
        },
        "required": ["observed_rate", "observed_taxable_amount", "observed_tax_amount", "evidence"],
        "additionalProperties": False,
    }
    tax_component_schema = {
        "type": "object",
        "properties": {
            "source_label": text_field,
            "source_code": text_field,
            "rate": text_field,
            "taxable_amount": text_field,
            "tax_amount": text_field,
            "source_position": text_field,
            "evidence": evidence_field,
        },
        "required": ["source_label", "source_code", "rate", "taxable_amount", "tax_amount", "source_position", "evidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "supplier_party": party_schema,
            "customer_party": party_schema,
            "line_items": {
                "type": "array",
                "items": line_schema,
                **(
                    {"minItems": 1}
                    if resolved_mode == "discovery"
                    else ({"minItems": len(line_ids), "maxItems": len(line_ids)} if line_ids else {})
                ),
            },
            "observed_vat_summary": {"type": "array", "items": vat_schema},
            "observed_tax_components": {"type": "array", "items": tax_component_schema},
            "observed_totals": {
                "type": "object",
                "properties": {
                    "observed_goods_services_total": text_field,
                    "observed_vat_total": text_field,
                    "observed_special_tax_total": text_field,
                    "observed_tax_inclusive_total": text_field,
                    "observed_payable_total": text_field,
                    "evidence": evidence_field,
                },
                "required": [
                    "observed_goods_services_total",
                    "observed_vat_total",
                    "observed_special_tax_total",
                    "observed_tax_inclusive_total",
                    "observed_payable_total",
                    "evidence",
                ],
                "additionalProperties": False,
            },
            "extraction_notes": evidence_field,
        },
        "required": [
            "supplier_party",
            "customer_party",
            "line_items",
            "observed_vat_summary",
            "observed_tax_components",
            "observed_totals",
            "extraction_notes",
        ],
        "additionalProperties": False,
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
    totals = _mapping(payload.get("observed_totals") or payload.get("totals"))
    line_items = tuple(
        CanonicalInvoiceLine(
            description=_string(line.get("description")),
            canonical_line_id=_string(line.get("canonical_line_id")),
            source_position=_string(line.get("source_position")),
            external_line_id=_string(line.get("external_line_id")),
            quantity=_string(line.get("observed_quantity") or line.get("quantity")),
            unit_code=_string(line.get("observed_unit_code") or line.get("unit_code")),
            unit_price=_string(line.get("observed_unit_price") or line.get("unit_price")),
            taxable_amount=_string(line.get("observed_taxable_amount") or line.get("taxable_amount")),
            vat_rate=_string(line.get("observed_vat_rate") or line.get("vat_rate")),
            tax_amount=_string(line.get("observed_tax_amount") or line.get("tax_amount")),
            gross_amount=_string(line.get("observed_gross_amount") or line.get("gross_amount")),
            tax_scheme_code=_string(line.get("tax_scheme_code")),
            tax_category_code=_string(line.get("tax_category_code")),
            exemption_reason_code=_string(line.get("exemption_reason_code")),
            vat_group_id=_string(line.get("vat_group_id")),
            evidence=_strings(line.get("evidence")),
        )
        for item in payload.get("line_items") or []
        if isinstance(item, Mapping)
        if (line := _mapping(item)).get("description")
    )
    vat_summary = tuple(
        CanonicalVatSummaryLine(
            rate=_string(line.get("observed_rate") or line.get("rate")),
            taxable_amount=_string(line.get("observed_taxable_amount") or line.get("taxable_amount")),
            tax_amount=_string(line.get("observed_tax_amount") or line.get("tax_amount")),
            tax_scheme_code=_string(line.get("tax_scheme_code")),
            tax_category_code=_string(line.get("tax_category_code")),
            exemption_reason_code=_string(line.get("exemption_reason_code")),
            vat_group_id=_string(line.get("vat_group_id")),
            contributing_line_ids=_strings(line.get("contributing_line_ids")),
            evidence=_strings(line.get("evidence")),
        )
        for item in payload.get("observed_vat_summary") or payload.get("vat_summary") or []
        if isinstance(item, Mapping)
        if (line := _mapping(item)).get("observed_rate") or line.get("rate")
    )
    tax_components = tuple(
        normalize_tax_component(
            source_label=_string(item.get("source_label")),
            source_code=_string(item.get("source_code")),
            rate=_string(item.get("rate")),
            taxable_amount=_string(item.get("taxable_amount")),
            tax_amount=_string(item.get("tax_amount")),
            source_position=_string(item.get("source_position")),
            evidence=_strings(item.get("evidence")),
        )
        for item in payload.get("observed_tax_components") or []
        if isinstance(item, Mapping)
    )
    monetary_components = tuple(
        normalize_monetary_component(
            source_label=line.description,
            source_amount=line.taxable_amount,
            source_position=line.source_position,
            evidence=line.evidence,
        )
        for line in line_items
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
        tax_components=tax_components,
        monetary_components=monetary_components,
        totals=CanonicalInvoiceTotals(
            goods_services_total=_string(
                totals.get("observed_goods_services_total") or totals.get("goods_services_total")
            ),
            vat_total=_string(totals.get("observed_vat_total") or totals.get("vat_total")),
            special_tax_total=_string(
                totals.get("observed_special_tax_total") or totals.get("special_tax_total")
            ),
            tax_inclusive_total=_string(
                totals.get("observed_tax_inclusive_total") or totals.get("tax_inclusive_total")
            ),
            payable_total=_string(totals.get("observed_payable_total") or totals.get("payable_total")),
            evidence=_strings(totals.get("evidence")),
        ),
        ai_used=True,
        extraction_notes=_strings(payload.get("extraction_notes")),
    )
    return with_validation(invoice)


def stable_canonical_line_id(
    *,
    source: str,
    source_position: str,
    external_line_id: str = "",
    description: str = "",
    taxable_amount: str = "",
    tax_amount: str = "",
    ordinal: int = 0,
) -> str:
    """Build a deterministic identity without depending on parser output order.

    Provider/XML line identifiers win. A durable source locator is the second
    choice. Content and ordinal are only a conservative fallback for sources
    that cannot expose a better locator.
    """

    source_key = " ".join(str(source or "unknown").strip().lower().split())
    external_key = " ".join(str(external_line_id or "").strip().split())
    position_key = " ".join(str(source_position or "").strip().split())
    if external_key:
        identity = f"{source_key}:external:{external_key}"
    elif position_key:
        identity = f"{source_key}:position:{position_key}"
    else:
        normalized_description = " ".join(str(description or "").strip().lower().split())
        identity = (
            f"{source_key}:fallback:{normalized_description}:"
            f"{str(taxable_amount or '').strip()}:{str(tax_amount or '').strip()}:{ordinal}"
        )
    return f"line_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def with_stable_line_id(
    line: CanonicalInvoiceLine,
    *,
    source: str,
    ordinal: int,
) -> CanonicalInvoiceLine:
    trusted_external_line_id = line.external_line_id if source != "ai_canonical" else ""
    return replace(
        line,
        canonical_line_id=stable_canonical_line_id(
            source=source,
            source_position=line.source_position,
            external_line_id=trusted_external_line_id,
            description=line.description,
            taxable_amount=line.taxable_amount,
            tax_amount=line.tax_amount,
            ordinal=ordinal,
        ),
    )


def ensure_stable_line_ids(invoice: CanonicalInvoice) -> CanonicalInvoice:
    return replace(
        invoice,
        line_items=tuple(
            with_stable_line_id(line, source=invoice.source, ordinal=index)
            for index, line in enumerate(invoice.line_items, start=1)
        ),
    )


def validate_line_decision_coverage(
    lines: tuple[CanonicalInvoiceLine, ...] | list[CanonicalInvoiceLine],
    decisions: object,
) -> CanonicalLineDecisionCoverage:
    expected = tuple(line.canonical_line_id for line in lines if line.canonical_line_id)
    received: list[str] = []
    if isinstance(decisions, (list, tuple)):
        for decision in decisions:
            if isinstance(decision, Mapping):
                received.append(_string(decision.get("canonical_line_id")))
    counts = {line_id: received.count(line_id) for line_id in set(received) if line_id}
    duplicate = tuple(sorted(line_id for line_id, count in counts.items() if count > 1))
    expected_set = set(expected)
    received_set = {line_id for line_id in received if line_id}
    missing = tuple(sorted(expected_set - received_set))
    unknown = tuple(sorted(received_set - expected_set))
    status = "valid" if expected and not missing and not duplicate and not unknown and len(received) == len(expected) else "invalid"
    return CanonicalLineDecisionCoverage(
        status=status,
        expected_ids=expected,
        received_ids=tuple(received),
        missing_ids=missing,
        duplicate_ids=duplicate,
        unknown_ids=unknown,
    )


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


def _normalized_decimal_text(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    compact = raw.replace(" ", "")
    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(compact)
    except (InvalidOperation, ValueError):
        return raw
    if not parsed.is_finite():
        return raw
    normalized = format(parsed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def canonical_vat_group_id(
    *,
    tax_scheme_code: str,
    tax_category_code: str,
    vat_rate: str,
    exemption_reason_code: str = "",
) -> str:
    """Build the stable tax identity used to reconcile UBL VAT groups."""
    return "|".join(
        (
            tax_scheme_code.strip().upper(),
            tax_category_code.strip().upper(),
            _normalized_decimal_text(vat_rate),
            exemption_reason_code.strip().upper(),
        )
    )


def bind_canonical_lines_to_vat_summary(invoice: CanonicalInvoice) -> CanonicalInvoice:
    """Attach canonical line IDs to the declared VAT summary group they evidence."""
    identified = ensure_stable_line_ids(invoice)
    lines = tuple(
        replace(
            line,
            vat_group_id=canonical_vat_group_id(
                tax_scheme_code=line.tax_scheme_code,
                tax_category_code=line.tax_category_code,
                vat_rate=line.vat_rate,
                exemption_reason_code=line.exemption_reason_code,
            ),
        )
        for line in identified.line_items
    )
    line_ids_by_group: dict[str, list[str]] = {}
    for line in lines:
        line_ids_by_group.setdefault(line.vat_group_id, []).append(line.canonical_line_id)
    summary = tuple(
        replace(
            line,
            vat_group_id=canonical_vat_group_id(
                tax_scheme_code=line.tax_scheme_code,
                tax_category_code=line.tax_category_code,
                vat_rate=line.rate,
                exemption_reason_code=line.exemption_reason_code,
            ),
            contributing_line_ids=tuple(
                line_ids_by_group.get(
                    canonical_vat_group_id(
                        tax_scheme_code=line.tax_scheme_code,
                        tax_category_code=line.tax_category_code,
                        vat_rate=line.rate,
                        exemption_reason_code=line.exemption_reason_code,
                    ),
                    (),
                )
            ),
        )
        for line in identified.vat_summary
    )
    return replace(identified, line_items=lines, vat_summary=summary)


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
    invoice = bind_canonical_lines_to_vat_summary(invoice)
    reasons: list[str] = []
    evidence: list[str] = []

    if not invoice.line_items:
        reasons.append("line_items_missing")
    line_ids = [line.canonical_line_id for line in invoice.line_items]
    if any(not line_id for line_id in line_ids):
        reasons.append("canonical_line_id_missing")
    if len(set(line_ids)) != len(line_ids):
        reasons.append("canonical_line_id_duplicate")
    if any(not line.source_position and not line.external_line_id for line in invoice.line_items):
        reasons.append("canonical_source_position_missing")

    line_taxables = [_decimal(line.taxable_amount) for line in invoice.line_items]
    line_taxes = [_decimal(line.tax_amount) for line in invoice.line_items]
    line_grosses = [_decimal(line.gross_amount) for line in invoice.line_items]
    taxable_sum = _sum([value for value in line_taxables if value is not None])
    tax_sum = _sum([value for value in line_taxes if value is not None])
    gross_sum = _sum([value for value in line_grosses if value is not None])
    special_tax = _decimal(invoice.totals.special_tax_total) or Decimal("0.00")
    allowance_total = _decimal(invoice.totals.allowance_total) or Decimal("0.00")
    fully_discounted = (
        taxable_sum is not None
        and allowance_total >= taxable_sum
        and _close(_decimal(invoice.totals.goods_services_total), Decimal("0.00"))
        and _close(_decimal(invoice.totals.payable_total), Decimal("0.00"))
    )
    if not fully_discounted:
        if any(not str(line.vat_rate).strip() for line in invoice.line_items):
            reasons.append("line_vat_rate_missing")
        if any(not str(line.tax_amount).strip() for line in invoice.line_items):
            reasons.append("line_tax_amount_missing")

    net_after_allowance = taxable_sum - allowance_total if taxable_sum is not None else None
    if not _close(net_after_allowance, _decimal(invoice.totals.goods_services_total)):
        reasons.append("line_total_mismatch")
    if not _close(tax_sum, _decimal(invoice.totals.vat_total)):
        reasons.append("vat_total_mismatch")

    summary_taxable_sum = _sum(
        [value for line in invoice.vat_summary if (value := _decimal(line.taxable_amount)) is not None]
    )
    summary_tax_sum = _sum([value for line in invoice.vat_summary if (value := _decimal(line.tax_amount)) is not None])
    header_special_tax_in_vat_base = (
        special_tax > Decimal("0.00")
        and len(invoice.vat_summary) == 1
        and net_after_allowance is not None
        and _close(summary_taxable_sum, net_after_allowance + special_tax)
    )
    if not header_special_tax_in_vat_base:
        for line in invoice.line_items:
            expected_tax = _line_tax(line)
            actual_tax = _decimal(line.tax_amount)
            if expected_tax is not None and actual_tax is not None and not _close(expected_tax, actual_tax):
                reasons.append("line_tax_amount_mismatch")
                evidence.append(f"line:{line.description[:60]}")
    vat_taxable_expected = net_after_allowance
    if header_special_tax_in_vat_base and vat_taxable_expected is not None:
        vat_taxable_expected += special_tax
    if invoice.vat_summary and not _close(summary_taxable_sum, vat_taxable_expected):
        reasons.append("vat_summary_taxable_mismatch")
    if invoice.vat_summary and not _close(summary_tax_sum, tax_sum):
        reasons.append("vat_summary_tax_mismatch")

    declared_vat_groups = {line.vat_group_id for line in invoice.vat_summary}
    line_groups: dict[str, list[CanonicalInvoiceLine]] = {}
    for line in invoice.line_items:
        line_groups.setdefault(line.vat_group_id, []).append(line)
    for summary_line in (() if fully_discounted else invoice.vat_summary):
        group_lines = line_groups.get(summary_line.vat_group_id, [])
        if not group_lines:
            reasons.append("vat_group_lines_missing")
            evidence.append(f"vat_group:{summary_line.vat_group_id}")
            continue
        group_taxable = _sum(
            [value for line in group_lines if (value := _decimal(line.taxable_amount)) is not None]
        )
        group_tax = _sum([value for line in group_lines if (value := _decimal(line.tax_amount)) is not None])
        declared_taxable = _decimal(summary_line.taxable_amount)
        declared_tax = _decimal(summary_line.tax_amount)
        group_taxable_expected = group_taxable
        if header_special_tax_in_vat_base and group_taxable_expected is not None:
            group_taxable_expected += special_tax
        if (group_taxable_expected is not None and declared_taxable is None) or not _close(group_taxable_expected, declared_taxable):
            reasons.append("vat_group_taxable_mismatch")
            evidence.append(f"vat_group:{summary_line.vat_group_id}")
        if (group_tax is not None and declared_tax is None) or not _close(group_tax, declared_tax):
            reasons.append("vat_group_tax_mismatch")
            evidence.append(f"vat_group:{summary_line.vat_group_id}")
    if invoice.vat_summary and not fully_discounted:
        for group_id in line_groups:
            if group_id not in declared_vat_groups:
                reasons.append("vat_group_unexpected_lines")
                evidence.append(f"vat_group:{group_id}")

    expected_gross = None
    if taxable_sum is not None and tax_sum is not None:
        expected_gross = (taxable_sum - allowance_total + tax_sum + special_tax).quantize(MONEY, rounding=ROUND_HALF_UP)
    total_gross = _decimal(invoice.totals.tax_inclusive_total) or _decimal(invoice.totals.payable_total)
    if not _close(expected_gross, total_gross):
        reasons.append("gross_total_mismatch")
    if gross_sum is not None and not _close(gross_sum - allowance_total + special_tax, total_gross):
        reasons.append("line_gross_total_mismatch")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return CanonicalInvoiceValidation(
        status="valid" if not unique_reasons else "invalid",
        reason_codes=unique_reasons,
        evidence=tuple(dict.fromkeys(evidence)),
    )


def with_validation(invoice: CanonicalInvoice) -> CanonicalInvoice:
    bound = bind_canonical_lines_to_vat_summary(invoice)
    return replace(bound, validation=validate_canonical_invoice(bound))
