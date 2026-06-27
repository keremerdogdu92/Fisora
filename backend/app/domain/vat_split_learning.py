from __future__ import annotations

from dataclasses import asdict, dataclass

from app.domain.pdf_invoices import ParsedInvoice


VAT_SPLIT_REVIEW_SCHEMA_VERSION = "vat_split_review.v1"


@dataclass(frozen=True)
class VatSplitReviewLine:
    rate: str
    taxable_amount: str
    tax_amount: str
    source: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class VatSplitReviewRecord:
    schema_version: str
    document_ref: str
    file_name: str
    invoice_no: str
    issuer_tax_id: str
    recipient_tax_id: str
    provider_hint: str
    status: str
    confidence: str
    requires_accountant_review: bool
    review_reason_codes: tuple[str, ...]
    similarity_key: str
    lines: tuple[VatSplitReviewLine, ...]
    evidence: tuple[str, ...]
    total_taxable_amount: str
    total_tax_amount: str
    tax_inclusive_total: str
    payable_total: str
    learning_candidate: bool
    automation_candidate: bool = False


def build_vat_split_review_record(invoice: ParsedInvoice, *, document_ref: str = "") -> VatSplitReviewRecord:
    status = str(invoice.vat_split_status or "unavailable")
    lines = tuple(
        VatSplitReviewLine(
            rate=str(line.rate),
            taxable_amount=str(line.taxable_amount),
            tax_amount=str(line.tax_amount),
            source=str(line.source),
            evidence=tuple(str(item) for item in line.evidence),
        )
        for line in invoice.vat_split_lines
    )
    evidence = tuple(str(item) for item in invoice.vat_split_evidence)
    total_taxable = _sum_amount(line.taxable_amount for line in lines)
    total_tax = _sum_amount(line.tax_amount for line in lines)
    return VatSplitReviewRecord(
        schema_version=VAT_SPLIT_REVIEW_SCHEMA_VERSION,
        document_ref=document_ref or invoice.file_name,
        file_name=invoice.file_name,
        invoice_no=invoice.invoice_no,
        issuer_tax_id=invoice.issuer_tax_id,
        recipient_tax_id=invoice.recipient_tax_id,
        provider_hint=invoice.provider_hint,
        status=status,
        confidence=_confidence_for_status(status, evidence),
        requires_accountant_review=status not in {"exact", "derived"},
        review_reason_codes=_review_reason_codes(status),
        similarity_key=_similarity_key(status, lines, evidence, invoice.vat_rates),
        lines=lines,
        evidence=evidence,
        total_taxable_amount=total_taxable,
        total_tax_amount=total_tax,
        tax_inclusive_total=invoice.tax_inclusive_total,
        payable_total=invoice.payable_total,
        learning_candidate=status in {"exact", "derived"} and bool(lines),
    )


def vat_split_review_payload(record: VatSplitReviewRecord) -> dict[str, object]:
    payload = asdict(record)
    payload["lines"] = [asdict(line) for line in record.lines]
    payload["evidence"] = list(record.evidence)
    payload["review_reason_codes"] = list(record.review_reason_codes)
    return payload


def _confidence_for_status(status: str, evidence: tuple[str, ...]) -> str:
    if status == "exact":
        return "exact_total_validated"
    if status == "derived" and "vat_split_gross_total_not_vat_only" in evidence:
        return "vat_amounts_validated_non_vat_total"
    if status == "derived":
        return "vat_amounts_validated"
    return "manual_review_required"


def _review_reason_codes(status: str) -> tuple[str, ...]:
    if status == "derived":
        return ("vat_split_non_vat_total",)
    if status == "exact":
        return ()
    return ("vat_split_review_required",)


def _similarity_key(
    status: str,
    lines: tuple[VatSplitReviewLine, ...],
    evidence: tuple[str, ...],
    fallback_rates: tuple[str, ...],
) -> str:
    rates = tuple(line.rate for line in lines) or tuple(str(rate) for rate in fallback_rates)
    rate_key = "-".join(sorted(rates, key=lambda value: int(value) if value.isdigit() else 999)) or "no_rate"
    if "vat_split_gross_total_validated" in evidence:
        evidence_key = "vat_split_gross_total_validated"
    elif "vat_split_gross_total_not_vat_only" in evidence:
        evidence_key = "vat_split_gross_total_not_vat_only"
    else:
        evidence_key = "no_gross_evidence"
    return f"vat_split:{status}:{rate_key}:{evidence_key}"


def _sum_amount(values: object) -> str:
    from decimal import Decimal, InvalidOperation

    total = Decimal("0.00")
    for value in values:  # type: ignore[union-attr]
        try:
            total += Decimal(str(value or "0"))
        except (InvalidOperation, ValueError):
            continue
    return f"{total:.2f}"
