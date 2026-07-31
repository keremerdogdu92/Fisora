from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

from app.domain.canonical_invoices import CanonicalInvoice, CanonicalInvoiceLine
from app.domain.journal_entries import JournalEntry, JournalLine


@dataclass(frozen=True)
class VatAccountingGroup:
    vat_group_id: str
    rate: str
    tax_scheme_code: str
    tax_category_code: str
    exemption_reason_code: str
    taxable_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    lines: tuple[CanonicalInvoiceLine, ...]

    @property
    def line_ids(self) -> tuple[str, ...]:
        return tuple(line.canonical_line_id for line in self.lines)


@dataclass(frozen=True)
class VatGroupAccountDecision:
    vat_group_id: str
    selected_account_code: str
    selected_account_name: str
    covered_line_ids: tuple[str, ...]
    decision_origin: str
    reason: str
    possible_exception_line_ids: tuple[str, ...] = ()


def _money(value: str) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid VAT group money: {value}") from exc


def build_vat_accounting_groups(invoice: CanonicalInvoice) -> tuple[VatAccountingGroup, ...]:
    lines_by_id = {
        line.canonical_line_id: line
        for line in invoice.line_items
        if line.canonical_line_id
    }
    groups: list[VatAccountingGroup] = []
    seen_line_ids: set[str] = set()
    for summary in invoice.vat_summary:
        line_ids = tuple(summary.contributing_line_ids)
        if (
            not summary.vat_group_id
            or not line_ids
            or len(line_ids) != len(set(line_ids))
            or any(line_id not in lines_by_id for line_id in line_ids)
            or any(line_id in seen_line_ids for line_id in line_ids)
        ):
            raise ValueError("canonical VAT summary has invalid line membership")
        lines = tuple(lines_by_id[line_id] for line_id in line_ids)
        if any(line.vat_group_id != summary.vat_group_id for line in lines):
            raise ValueError("canonical line VAT group does not match its summary")
        seen_line_ids.update(line_ids)
        taxable = _money(summary.taxable_amount)
        tax = _money(summary.tax_amount)
        groups.append(
            VatAccountingGroup(
                vat_group_id=summary.vat_group_id,
                rate=summary.rate,
                tax_scheme_code=summary.tax_scheme_code,
                tax_category_code=summary.tax_category_code,
                exemption_reason_code=summary.exemption_reason_code,
                taxable_amount=taxable,
                tax_amount=tax,
                gross_amount=taxable + tax,
                lines=lines,
            )
        )
    if seen_line_ids != set(lines_by_id):
        raise ValueError("every canonical line must belong to one VAT group")
    return tuple(groups)


def materialize_group_line_decisions(
    *,
    group: VatAccountingGroup,
    decision: VatGroupAccountDecision,
    confirmed_exceptions: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    if decision.vat_group_id != group.vat_group_id:
        raise ValueError("VAT group decision does not match the target group")
    if (
        len(decision.covered_line_ids) != len(group.line_ids)
        or set(decision.covered_line_ids) != set(group.line_ids)
    ):
        raise ValueError("VAT group decision must cover every canonical line exactly once")

    possible_exceptions = set(decision.possible_exception_line_ids)
    results: list[dict[str, object]] = []
    for line in group.lines:
        account_code = decision.selected_account_code
        origin = "vat_group_default"
        if line.canonical_line_id in confirmed_exceptions:
            account_code = str(confirmed_exceptions[line.canonical_line_id] or "").strip()
            origin = "confirmed_line_exception"
        results.append(
            {
                "canonical_line_id": line.canonical_line_id,
                "vat_group_id": group.vat_group_id,
                "account_code": account_code,
                "decision_origin": origin,
                "group_reason": decision.reason,
                "possible_exception": line.canonical_line_id in possible_exceptions,
            }
        )
    return tuple(results)


def account_roles_for(direction: str) -> dict[str, tuple[str, ...]]:
    if direction == "purchase":
        return {
            "net": ("153", "7", "25"),
            "vat": ("191",),
            "counterparty": ("320",),
        }
    return {
        "net": ("600",),
        "vat": ("391",),
        "counterparty": ("120",),
    }


def _line_allocations(
    group: VatAccountingGroup,
    *,
    component: str,
) -> tuple[tuple[str, str], ...]:
    field_name = {
        "net": "taxable_amount",
        "tax": "tax_amount",
        "gross": "gross_amount",
    }[component]
    return tuple(
        (
            line.canonical_line_id,
            f"{_money(getattr(line, field_name)):.2f}",
        )
        for line in group.lines
    )


def build_vat_grouped_invoice_entry(
    *,
    entry_date: str,
    direction: str,
    groups: tuple[VatAccountingGroup, ...],
    decisions: tuple[VatGroupAccountDecision, ...],
    vat_accounts: Mapping[str, str],
    counterparty_account: str,
    document_ref: str = "",
    line_decisions: tuple[Mapping[str, object], ...] = (),
) -> JournalEntry:
    if direction not in {"purchase", "sales"}:
        raise ValueError("VAT-grouped journal direction must be purchase or sales")
    decisions_by_group = {decision.vat_group_id: decision for decision in decisions}
    if len(decisions_by_group) != len(decisions) or set(decisions_by_group) != {
        group.vat_group_id for group in groups
    }:
        raise ValueError("every VAT group must have exactly one account decision")
    if not counterparty_account.strip():
        raise ValueError("VAT-grouped journal requires a counterparty account")

    lines: list[JournalLine] = []
    line_account_by_id = {
        str(item.get("canonical_line_id") or ""): str(item.get("account_code") or "").strip()
        for item in line_decisions
        if str(item.get("canonical_line_id") or "")
    }
    for group in groups:
        decision = decisions_by_group[group.vat_group_id]
        if (
            not decision.selected_account_code.strip()
            or set(decision.covered_line_ids) != set(group.line_ids)
        ):
            raise ValueError("VAT group decision is incomplete")
        lines_by_account: dict[str, list[CanonicalInvoiceLine]] = {}
        for source_line in group.lines:
            account_code = (
                line_account_by_id.get(source_line.canonical_line_id)
                or decision.selected_account_code
            )
            lines_by_account.setdefault(account_code, []).append(source_line)
        for account_code, source_lines in lines_by_account.items():
            net_amount = sum(
                (_money(line.taxable_amount) for line in source_lines),
                Decimal("0.00"),
            ).quantize(Decimal("0.01"))
            lines.append(
                JournalLine(
                    account_code,
                    (
                        decision.selected_account_name
                        if account_code == decision.selected_account_code
                        else "Onayli satir istisnasi"
                    )
                    or "KDV grubu net hesabi",
                    debit=net_amount if direction == "purchase" else Decimal("0.00"),
                    credit=net_amount if direction == "sales" else Decimal("0.00"),
                    document_ref=document_ref or None,
                    vat_group_id=group.vat_group_id,
                    contributing_line_ids=tuple(
                        line.canonical_line_id for line in source_lines
                    ),
                    allocated_amounts=tuple(
                        (
                            line.canonical_line_id,
                            f"{_money(line.taxable_amount):.2f}",
                        )
                        for line in source_lines
                    ),
                )
            )
        if group.tax_amount > Decimal("0.00"):
            vat_account = str(vat_accounts.get(group.vat_group_id) or "").strip()
            if not vat_account:
                raise ValueError("taxable VAT group requires a usable VAT account")
            lines.append(
                JournalLine(
                    vat_account,
                    "Indirilecek KDV" if direction == "purchase" else "Hesaplanan KDV",
                    debit=group.tax_amount if direction == "purchase" else Decimal("0.00"),
                    credit=group.tax_amount if direction == "sales" else Decimal("0.00"),
                    tax_rate=Decimal(group.rate or "0"),
                    document_ref=document_ref or None,
                    vat_group_id=group.vat_group_id,
                    contributing_line_ids=group.line_ids,
                    allocated_amounts=_line_allocations(group, component="tax"),
                )
            )

    gross_total = sum((group.gross_amount for group in groups), Decimal("0.00")).quantize(
        Decimal("0.01")
    )
    lines.append(
        JournalLine(
            counterparty_account,
            "Satici cari" if direction == "purchase" else "Alici cari",
            debit=gross_total if direction == "sales" else Decimal("0.00"),
            credit=gross_total if direction == "purchase" else Decimal("0.00"),
            document_ref=document_ref or None,
            contributing_line_ids=tuple(
                line_id for group in groups for line_id in group.line_ids
            ),
            allocated_amounts=tuple(
                allocation
                for group in groups
                for allocation in _line_allocations(group, component="gross")
            ),
        )
    )
    return JournalEntry(
        entry_type=(
            f"mixed_vat_{direction}"
            if len(groups) > 1
            else direction
        ),
        entry_date=entry_date,
        description=(
            f"KDV gruplu {'alis' if direction == 'purchase' else 'satis'} faturasi "
            f"{document_ref}"
        ).strip(),
        lines=tuple(lines),
    )
