from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Mapping, Sequence

from app.domain.accounting_proposal import (
    AccountingDecisionV2,
    AccountingProposalV2,
    SemanticConflict,
)


_CENT = Decimal("0.01")


@dataclass(frozen=True)
class JournalDraftLineV2:
    fact_ref: str
    raw_source_amount: str
    amount: Decimal
    side: str | None
    debit: Decimal
    credit: Decimal
    selected_candidate_id: str = ""
    account_code: str = ""
    account_name: str = ""
    resolution: str = "resolved"
    representation: str = "posting"
    represented_by_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class JournalDraftV2:
    lines: tuple[JournalDraftLineV2, ...]
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
    currency_code: str
    semantic_conflicts: tuple[SemanticConflict, ...] = ()

    def line_for(self, fact_ref: str) -> JournalDraftLineV2:
        for line in self.lines:
            if line.fact_ref == fact_ref:
                return line
        raise KeyError(fact_ref)


def projection_fact_refs(projection: Mapping[str, object]) -> tuple[str, ...]:
    refs: list[str] = ["counterparty"]
    for section in ("line_items", "vat_summary", "tax_components", "monetary_components"):
        for item in _mapping_items(projection.get(section)):
            identity = str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
            if identity and identity not in refs:
                refs.append(identity)
    return tuple(refs)


def build_journal_draft(
    projection: Mapping[str, object],
    proposal: AccountingProposalV2,
) -> JournalDraftV2:
    direction = str(projection.get("document_direction") or "").strip().lower()
    header = projection.get("header")
    header = header if isinstance(header, Mapping) else {}
    currency_code = str(header.get("currency_code") or "").strip()
    lines: list[JournalDraftLineV2] = []
    seen: set[str] = set()

    def add_fact(
        item: Mapping[str, object],
        *,
        amount_field: str,
        default_effect: str,
    ) -> None:
        identity = str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
        if not identity or identity in seen:
            return
        seen.add(identity)
        decision_ref = str(item.get("decision_ref") or "").strip()
        try:
            decision = proposal.decision_for(decision_ref) if decision_ref else None
        except KeyError:
            decision = None
        amount, amount_valid, raw_amount = _money(
            item.get(amount_field),
            currency_code=currency_code,
        )
        represented_by = tuple(str(value) for value in item.get("represented_by_refs", ()) if str(value))
        treatment = str(item.get("accounting_treatment") or "").strip().lower()
        if not amount_valid:
            lines.append(
                _unresolved_line(
                    identity,
                    amount,
                    decision,
                    "amount_invalid",
                    raw_source_amount=raw_amount,
                )
            )
            return
        if (
            decision is not None
            and decision.action == "select_existing"
            and amount != Decimal("0")
            and decision_ref.startswith(("tax:", "monetary:"))
            and not decision.selected_treatment
        ):
            lines.append(
                _review_required_line(
                    identity,
                    amount,
                    decision,
                    "treatment_topology_review_required",
                    raw_source_amount=raw_amount,
                )
            )
            return
        if decision is not None and decision.action in {
            "represented",
            "excluded",
            "no_separate_posting",
        }:
            lines.append(
                _representation_line(
                    identity,
                    amount,
                    decision.action,
                    (),
                    decision,
                    raw_source_amount=raw_amount,
                )
            )
            return
        if represented_by:
            lines.append(_representation_line(identity, amount, "represented_by_refs", represented_by, decision, raw_source_amount=raw_amount))
            return
        posting_requirement = str(item.get("posting_requirement") or "").strip().lower()
        if posting_requirement in {"represented", "excluded"}:
            lines.append(
                _representation_line(
                    identity,
                    amount,
                    f"reconciliation_{posting_requirement}",
                    (),
                    decision,
                    raw_source_amount=raw_amount,
                )
            )
            return
        if posting_requirement == "unresolved":
            lines.append(
                _unresolved_line(
                    identity,
                    amount,
                    decision,
                    "monetary_topology_unresolved",
                    raw_source_amount=raw_amount,
                )
            )
            return
        if not posting_requirement and treatment in {"informational", "exclude_current_period"}:
            lines.append(_representation_line(identity, amount, treatment, (), decision, raw_source_amount=raw_amount))
            return
        if (
            not posting_requirement
            and identity.startswith("monetary:")
            and str(item.get("included_in_line_net") or "").lower() == "yes"
        ):
            lines.append(_representation_line(identity, amount, "included_in_line_net", (), decision, raw_source_amount=raw_amount))
            return
        effect = _selected_effect(decision) or str(
            item.get("reconciled_effect")
            or item.get("economic_effect")
            or item.get("signed_effect")
            or default_effect
        ).strip().lower()
        if effect in {"", "unknown"}:
            lines.append(_unresolved_line(identity, amount, decision, "posting_side_unknown", raw_source_amount=raw_amount))
            return
        side = _posting_side(direction, effect)
        if side is None:
            lines.append(_unresolved_line(identity, amount, decision, "posting_side_unknown", raw_source_amount=raw_amount))
            return
        lines.append(_posting_line(identity, amount, side, decision, raw_source_amount=raw_amount))

    for item in _mapping_items(projection.get("line_items")):
        add_fact(
            item,
            amount_field=(
                "posting_amount"
                if item.get("posting_amount") not in (None, "")
                else "taxable_amount"
            ),
            default_effect="increase_payable",
        )
    for item in _mapping_items(projection.get("vat_summary")):
        add_fact(item, amount_field="tax_amount", default_effect="increase_tax")
    for item in _mapping_items(projection.get("tax_components")):
        add_fact(item, amount_field="tax_amount", default_effect="unknown")
    for item in _mapping_items(projection.get("monetary_components")):
        add_fact(item, amount_field="source_amount", default_effect="unknown")

    totals = projection.get("totals")
    totals = totals if isinstance(totals, Mapping) else {}
    counterparty_amount, counterparty_valid, counterparty_raw = _money(
        totals.get("payable_total"),
        currency_code=currency_code,
    )
    counterparty_side = "credit" if direction == "purchase" else "debit" if direction == "sales" else None
    if not counterparty_valid:
        lines.append(_unresolved_line("counterparty", counterparty_amount, proposal.counterparty, "amount_invalid", raw_source_amount=counterparty_raw))
    elif counterparty_side is None:
        lines.append(_unresolved_line("counterparty", counterparty_amount, proposal.counterparty, "document_direction_unknown", raw_source_amount=counterparty_raw))
    else:
        lines.append(_posting_line("counterparty", counterparty_amount, counterparty_side, proposal.counterparty, raw_source_amount=counterparty_raw))

    total_debit = sum((line.debit for line in lines), Decimal("0.00")).quantize(_CENT)
    total_credit = sum((line.credit for line in lines), Decimal("0.00")).quantize(_CENT)
    return JournalDraftV2(
        lines=tuple(lines),
        total_debit=total_debit,
        total_credit=total_credit,
        is_balanced=total_debit == total_credit,
        currency_code=str(header.get("currency_code") or "").strip(),
        semantic_conflicts=proposal.semantic_conflicts,
    )


def _posting_side(direction: str, effect: str) -> str | None:
    if direction not in {"purchase", "sales"}:
        return None
    purchase_debit = effect in {"increase_tax", "increase_payable"}
    if effect not in {"increase_tax", "increase_payable", "reduce_payable", "decrease_payable"}:
        return None
    if direction == "sales":
        purchase_debit = not purchase_debit
    return "debit" if purchase_debit else "credit"


def _selected_effect(decision: AccountingDecisionV2 | None) -> str:
    if decision is None:
        return ""
    treatment = decision.selected_treatment
    if treatment in {"increase_payable", "reduce_payable"}:
        return treatment
    if treatment == "payable_withholding":
        return "reduce_payable"
    if treatment in {"deductible_tax", "expense_or_cost"}:
        return "increase_payable"
    return ""


def _posting_line(ref: str, amount: Decimal, side: str, decision: AccountingDecisionV2 | None, *, raw_source_amount: str) -> JournalDraftLineV2:
    candidate = decision.candidate if decision is not None else None
    action = decision.action if decision is not None else "unresolved"
    resolution = "propose_new" if action == "propose_new" else "resolved" if candidate else "unresolved"
    return JournalDraftLineV2(
        fact_ref=ref,
        raw_source_amount=raw_source_amount,
        amount=amount,
        side=side,
        debit=amount if side == "debit" else Decimal("0.00"),
        credit=amount if side == "credit" else Decimal("0.00"),
        selected_candidate_id=candidate.candidate_id if candidate else "",
        account_code=candidate.code if candidate else "",
        account_name=candidate.name if candidate else "",
        resolution=resolution,
    )


def _representation_line(ref: str, amount: Decimal, representation: str, represented_by: tuple[str, ...], decision: AccountingDecisionV2 | None, *, raw_source_amount: str) -> JournalDraftLineV2:
    candidate = decision.candidate if decision is not None else None
    return JournalDraftLineV2(
        fact_ref=ref, raw_source_amount=raw_source_amount, amount=amount, side=None, debit=Decimal("0.00"), credit=Decimal("0.00"),
        selected_candidate_id=candidate.candidate_id if candidate else "",
        account_code=candidate.code if candidate else "", account_name=candidate.name if candidate else "",
        resolution="represented", representation=representation, represented_by_refs=represented_by,
    )


def _unresolved_line(ref: str, amount: Decimal, decision: AccountingDecisionV2 | None, warning: str, *, raw_source_amount: str) -> JournalDraftLineV2:
    candidate = decision.candidate if decision is not None else None
    return JournalDraftLineV2(
        fact_ref=ref, raw_source_amount=raw_source_amount, amount=amount, side=None, debit=Decimal("0.00"), credit=Decimal("0.00"),
        selected_candidate_id=candidate.candidate_id if candidate else "",
        account_code=candidate.code if candidate else "", account_name=candidate.name if candidate else "",
        resolution="unresolved", warnings=(warning,),
    )


def _review_required_line(ref: str, amount: Decimal, decision: AccountingDecisionV2, warning: str, *, raw_source_amount: str) -> JournalDraftLineV2:
    candidate = decision.candidate
    return JournalDraftLineV2(
        fact_ref=ref,
        raw_source_amount=raw_source_amount,
        amount=amount,
        side=None,
        debit=Decimal("0.00"),
        credit=Decimal("0.00"),
        selected_candidate_id=candidate.candidate_id if candidate else "",
        account_code=candidate.code if candidate else "",
        account_name=candidate.name if candidate else "",
        resolution="review_required",
        warnings=(warning,),
    )


def _money(value: object, *, currency_code: str = "") -> tuple[Decimal, bool, str]:
    source_raw = str(value if value is not None else "")
    raw = source_raw.strip().replace(" ", "")
    code = str(currency_code or "").strip()
    if code and raw.upper().startswith(code.upper()):
        raw = raw[len(code):]
    if code and raw.upper().endswith(code.upper()):
        raw = raw[:-len(code)]
    if not raw:
        return Decimal("0.00"), False, source_raw
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("0.00"), False, source_raw
    if not parsed.is_finite():
        return Decimal("0.00"), False, source_raw
    try:
        amount = abs(parsed).quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0.00"), False, source_raw
    return amount, True, source_raw


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))
