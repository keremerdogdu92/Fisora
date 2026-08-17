from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Mapping, Sequence

from app.domain.canonical_invoices import (
    CanonicalInvoice,
    CanonicalTaxComponent,
    CanonicalVatSummaryLine,
    bind_canonical_lines_to_vat_summary,
)
from app.domain.monetary_reconciliation import reconcile_monetary_projection


def _source_link(field_path: str, evidence: tuple[str, ...]) -> dict[str, object] | None:
    if not evidence:
        return None
    return {"field_path": field_path, "evidence": list(evidence)}


def _normalized_decimal(value: str) -> Decimal | None:
    raw = str(value or "").strip().replace(" ", "").strip("%")
    raw = re.sub(r"^[^0-9+\-.,]+|[^0-9.,]+$", "", raw)
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _same_vat_fact(
    component: CanonicalTaxComponent,
    summary: CanonicalVatSummaryLine,
) -> bool:
    component_rate = _normalized_decimal(component.rate)
    summary_rate = _normalized_decimal(summary.rate)
    component_tax = _normalized_decimal(component.tax_amount)
    summary_tax = _normalized_decimal(summary.tax_amount)
    if component_rate is None or summary_rate is None or component_rate != summary_rate:
        return False
    if component_tax is None or summary_tax is None or component_tax != summary_tax:
        return False
    component_taxable = _normalized_decimal(component.taxable_amount)
    summary_taxable = _normalized_decimal(summary.taxable_amount)
    return (
        component_taxable is None
        or summary_taxable is None
        or component_taxable == summary_taxable
    )


def _summed_decimal(values: Sequence[str]) -> Decimal | None:
    parsed = [_normalized_decimal(value) for value in values]
    if not parsed or any(value is None for value in parsed):
        return None
    return sum((value for value in parsed if value is not None), Decimal("0"))


def _vat_authority_refs(
    component: CanonicalTaxComponent,
    vat_summary: tuple[CanonicalVatSummaryLine, ...],
) -> tuple[str, ...]:
    exact_refs = tuple(
        sorted(
            {
                f"vat:{summary.vat_group_id}"
                for summary in vat_summary
                if _same_vat_fact(component, summary)
            }
        )
    )
    if exact_refs:
        return exact_refs
    if len(vat_summary) < 2:
        return ()
    component_tax = _normalized_decimal(component.tax_amount)
    summary_tax = _summed_decimal([summary.tax_amount for summary in vat_summary])
    if component_tax is None or summary_tax is None or component_tax != summary_tax:
        return ()
    component_taxable = _normalized_decimal(component.taxable_amount)
    summary_taxable = _summed_decimal([summary.taxable_amount for summary in vat_summary])
    if (
        component_taxable is not None
        and summary_taxable is not None
        and component_taxable != summary_taxable
    ):
        return ()
    return tuple(sorted(f"vat:{summary.vat_group_id}" for summary in vat_summary))


def _tax_component_authority(
    component: CanonicalTaxComponent,
    vat_summary: tuple[CanonicalVatSummaryLine, ...],
) -> tuple[str, str, tuple[str, ...]]:
    if component.canonical_tax_kind != "vat":
        ref = f"tax:{component.component_id}"
        return ref, ref, ()
    represented_by_refs = _vat_authority_refs(component, vat_summary)
    if len(represented_by_refs) == 1:
        return represented_by_refs[0], represented_by_refs[0], ()
    component_ref = f"vat:{component.component_id}"
    if represented_by_refs:
        return component_ref, "", represented_by_refs
    return component_ref, component_ref, ()


def _posting_side(*, document_direction: str, economic_effect: str) -> str:
    direction = str(document_direction or "").strip().lower()
    if economic_effect in {"informational", "unknown"}:
        return "none" if economic_effect == "informational" else "unknown"
    if direction not in {"purchase", "sales"}:
        return "unknown"
    purchase_debit = economic_effect in {"increase_tax", "increase_payable"}
    if economic_effect in {"reduce_payable", "decrease_payable"}:
        purchase_debit = False
    if direction == "sales":
        purchase_debit = not purchase_debit
    return "debit" if purchase_debit else "credit"


def _inclusion_warnings(
    values: Sequence[str],
    *,
    warning_code: str,
) -> list[str]:
    return [warning_code] if "unknown" in values else []


def build_accounting_projection(
    canonical_revision: CanonicalInvoice,
    warnings: Sequence[str] = (),
    *,
    client_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the compact, fact-only input for the accounting decision stage."""

    invoice = bind_canonical_lines_to_vat_summary(canonical_revision)
    line_decision_refs = _line_decision_refs(invoice.line_items)
    header = invoice.header
    supplier = invoice.supplier_party
    customer = invoice.customer_party
    totals = invoice.totals

    source_links: list[dict[str, object]] = []
    for field_name in (
        "invoice_no",
        "ettn",
        "issue_date",
        "invoice_type",
        "scenario",
        "currency_code",
        "document_direction",
        "original_invoice_no",
        "original_invoice_date",
    ):
        if getattr(header, field_name):
            link = _source_link(f"header.{field_name}", header.evidence)
            if link:
                source_links.append(link)
    for party_name, party in (("supplier_party", supplier), ("customer_party", customer)):
        for field_name in ("title", "tax_id", "tax_id_type", "tax_office", "address"):
            if getattr(party, field_name):
                link = _source_link(f"{party_name}.{field_name}", party.evidence)
                if link:
                    source_links.append(link)
    for index, line in enumerate(invoice.line_items):
        link = _source_link(f"line_items[{index}]", line.evidence)
        if link:
            source_links.append(link)
    for index, vat_group in enumerate(invoice.vat_summary):
        link = _source_link(f"vat_summary[{index}]", vat_group.evidence)
        if link:
            source_links.append(link)
    for index, tax_component in enumerate(invoice.tax_components):
        link = _source_link(f"tax_components[{index}]", tax_component.evidence)
        if link:
            source_links.append(link)
    for index, monetary_component in enumerate(invoice.monetary_components):
        link = _source_link(f"monetary_components[{index}]", monetary_component.evidence)
        if link:
            source_links.append(link)
    for index, named_total in enumerate(invoice.named_totals):
        link = _source_link(f"named_totals[{index}]", named_total.evidence)
        if link:
            source_links.append(link)
    totals_link = _source_link("totals", totals.evidence)
    if totals_link:
        source_links.append(totals_link)

    warning_values = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in (*invoice.extraction_notes, *warnings)
            if str(value).strip()
        )
    )
    projection_warnings: list[str] = []
    tax_components: list[dict[str, object]] = []
    for component in invoice.tax_components:
        inclusion_warnings: list[str] = []
        projection_warnings.extend(inclusion_warnings)
        identity_ref, decision_ref, represented_by_refs = _tax_component_authority(
            component,
            invoice.vat_summary,
        )
        tax_components.append(
            {
                "component_id": component.component_id,
                "occurrence_index": component.occurrence_index,
                "identity_ref": identity_ref,
                "decision_ref": decision_ref,
                "represented_by_refs": list(represented_by_refs),
                "component_type": component.component_type,
                "source_label": component.source_label,
                "source_code": component.source_code,
                "rate": component.rate,
                "taxable_amount": component.taxable_amount,
                "tax_amount": component.tax_amount,
                "canonical_tax_kind": component.canonical_tax_kind,
                "accounting_treatment": component.accounting_treatment,
                "economic_effect": component.economic_effect,
                "posting_side": _posting_side(
                    document_direction=header.document_direction,
                    economic_effect=component.economic_effect,
                ),
                "included_in_tax_total": component.included_in_tax_total,
                "included_in_payable": component.included_in_payable,
                "source_evidence_refs": list(component.evidence),
                "warnings": inclusion_warnings,
            }
        )
    monetary_components: list[dict[str, object]] = []
    for component in invoice.monetary_components:
        inclusion_warnings: list[str] = []
        projection_warnings.extend(inclusion_warnings)
        decision_ref = f"monetary:{component.component_id}"
        monetary_components.append(
            {
                "component_id": component.component_id,
                "occurrence_index": component.occurrence_index,
                "identity_ref": decision_ref,
                "decision_ref": decision_ref,
                "source_label": component.source_label,
                "source_amount": component.source_amount,
                "canonical_component_kind": component.canonical_component_kind,
                "accounting_treatment": component.accounting_treatment,
                "signed_effect": component.signed_effect,
                "posting_side": _posting_side(
                    document_direction=header.document_direction,
                    economic_effect=component.signed_effect,
                ),
                "included_in_line_net": component.included_in_line_net,
                "included_in_tax_total": component.included_in_tax_total,
                "included_in_payable": component.included_in_payable,
                "source_evidence_refs": list(component.evidence),
                "warnings": inclusion_warnings,
            }
        )
    projection = {
        "document_direction": header.document_direction,
        "header": {
            "invoice_no": header.invoice_no,
            "ettn": header.ettn,
            "issue_date": header.issue_date,
            "invoice_type": header.invoice_type,
            "scenario": header.scenario,
            "currency_code": header.currency_code,
            "original_invoice_no": header.original_invoice_no,
            "original_invoice_date": header.original_invoice_date,
        },
        "supplier_party": {
            "title": supplier.title,
            "tax_id": supplier.tax_id,
            "tax_id_type": supplier.tax_id_type,
            "tax_office": supplier.tax_office,
        },
        "customer_party": {
            "title": customer.title,
            "tax_id": customer.tax_id,
            "tax_id_type": customer.tax_id_type,
            "tax_office": customer.tax_office,
        },
        "line_items": [
            {
                "canonical_line_id": line.canonical_line_id,
                "identity_ref": f"line:{line.canonical_line_id}",
                "decision_ref": decision_ref,
                "description": line.description,
                "quantity": line.quantity,
                "unit_code": line.unit_code,
                "unit_price": line.unit_price,
                "unit_price_basis": line.unit_price_basis,
                "taxable_amount": line.taxable_amount,
                "vat_rate": line.vat_rate,
                "tax_amount": line.tax_amount,
                "gross_amount": line.gross_amount,
                "tax_scheme_code": line.tax_scheme_code,
                "tax_category_code": line.tax_category_code,
                "exemption_reason_code": line.exemption_reason_code,
                "vat_group_id": line.vat_group_id,
                "source_evidence_refs": list(line.evidence),
            }
            for line, decision_ref in zip(invoice.line_items, line_decision_refs)
        ],
        "vat_summary": [
            {
                "identity_ref": f"vat:{line.vat_group_id}",
                "decision_ref": f"vat:{line.vat_group_id}",
                "rate": line.rate,
                "taxable_amount": line.taxable_amount,
                "tax_amount": line.tax_amount,
                "tax_scheme_code": line.tax_scheme_code,
                "tax_category_code": line.tax_category_code,
                "exemption_reason_code": line.exemption_reason_code,
                "vat_group_id": line.vat_group_id,
                "contributing_line_ids": list(line.contributing_line_ids),
                "source_evidence_refs": list(line.evidence),
            }
            for line in invoice.vat_summary
        ],
        "tax_components": tax_components,
        "monetary_components": monetary_components,
        "named_totals": [
            {
                "source_label": item.source_label,
                "amount": item.amount,
                "source_position": item.source_position,
                "proposed_role": item.proposed_role,
                "source_evidence_refs": list(item.evidence),
            }
            for item in invoice.named_totals
        ],
        "totals": {
            "goods_services_total": totals.goods_services_total,
            "allowance_total": totals.allowance_total,
            "vat_total": totals.vat_total,
            "special_tax_total": totals.special_tax_total,
            "tax_inclusive_total": totals.tax_inclusive_total,
            "payable_total": totals.payable_total,
            "source_evidence_refs": list(totals.evidence),
        },
        "warnings": list(warning_values),
        "projection_warnings": list(dict.fromkeys(projection_warnings)),
        "client_context": dict(client_context or {}),
        "source_field_links": source_links,
    }
    return reconcile_monetary_projection(projection)


def _line_decision_refs(lines: Sequence[object]) -> tuple[str, ...]:
    return tuple(
        f"line:{getattr(line, 'canonical_line_id', '')}"
        for line in lines
    )
