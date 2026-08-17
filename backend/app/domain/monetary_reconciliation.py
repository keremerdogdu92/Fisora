from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import re
from typing import Mapping, Sequence


_CENT = Decimal("0.01")
_MEMBERSHIP_TOTALS = (
    "line_net_total",
    "line_gross_total",
    "vat_total",
    "special_tax_total",
    "tax_inclusive_total",
    "payable_total",
)


@dataclass(frozen=True)
class _ComponentCandidate:
    ref: str
    section: str
    index: int
    amount: Decimal
    effect: str
    payable_hint: str
    line_net_hint: str
    treatment: str

    @property
    def signed_amount(self) -> Decimal:
        if self.effect in {"reduce_payable", "decrease_payable"}:
            return -abs(self.amount)
        return abs(self.amount)

    @property
    def modes(self) -> tuple[str, ...]:
        if self.section == "monetary_components":
            return ("separate", "represented", "excluded")
        return ("separate", "excluded")


@dataclass(frozen=True)
class _Choice:
    modes: tuple[str, ...]
    preference_penalty: int


def reconcile_monetary_projection(
    projection: Mapping[str, object],
    *,
    max_states: int = 10000,
) -> dict[str, object]:
    """Derive component-to-total topology without choosing accounting accounts."""

    if max_states < 1:
        raise ValueError("max_states must be positive")
    result = deepcopy(dict(projection))
    line_items = _mutable_items(result, "line_items")
    vat_summary = _mutable_items(result, "vat_summary")
    tax_components = _mutable_items(result, "tax_components")
    monetary_components = _mutable_items(result, "monetary_components")
    _augment_source_backed_component_ledger(result, monetary_components)
    components = {
        "tax_components": tax_components,
        "monetary_components": monetary_components,
    }
    for item in (*tax_components, *monetary_components):
        item["total_memberships"] = {
            total: "unknown" for total in _MEMBERSHIP_TOTALS
        }
        item["total_membership_basis"] = {
            total: "unresolved" for total in _MEMBERSHIP_TOTALS
        }
        item["payable_membership"] = "unknown"
        item["posting_requirement"] = "unresolved"
        item["warnings"] = list(
            dict.fromkeys(str(value) for value in item.get("warnings", ()) if str(value))
        )

    line_total, line_complete = _sum_money(item.get("taxable_amount") for item in line_items)
    vat_total, vat_complete = _sum_unique_money(vat_summary, "identity_ref", "tax_amount")
    vat_base_total, vat_base_complete = _sum_unique_money(
        vat_summary,
        "identity_ref",
        "taxable_amount",
    )
    totals = result.get("totals")
    totals = totals if isinstance(totals, Mapping) else {}
    line_baseline_basis = "line_taxable_amounts"
    if (
        line_complete
        and vat_base_complete
        and vat_summary
        and line_total != vat_base_total
        and abs(line_total - vat_base_total) <= _CENT * max(len(line_items), 1)
    ):
        line_total = vat_base_total
        line_baseline_basis = "complete_vat_taxable_bases_cent_adjusted"
    if not line_complete:
        explicit_base = _money(
            totals.get("goods_services_total") or totals.get("tax_exclusive_total")
        )
        if explicit_base is not None:
            line_total = explicit_base
            line_complete = True
            line_baseline_basis = "explicit_goods_services_total"
        elif vat_base_complete and vat_summary:
            line_total = vat_base_total
            line_complete = True
            line_baseline_basis = "complete_vat_taxable_bases"
    line_allocation_adjustment = (
        _allocate_visible_line_amounts(line_items, target=line_total)
        if line_complete
        else Decimal("0.00")
    )
    mandatory_total = line_total + vat_total
    vat_refs = {
        str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
        for item in vat_summary
        if str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
    }

    candidates: list[_ComponentCandidate] = []
    represented_refs: set[str] = set()
    unresolved_refs: set[str] = set()
    for section, items, amount_field, effect_field in (
        ("tax_components", tax_components, "tax_amount", "economic_effect"),
        ("monetary_components", monetary_components, "source_amount", "signed_effect"),
    ):
        for index, item in enumerate(items):
            ref = str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
            represented_by = tuple(
                str(value).strip() for value in item.get("represented_by_refs", ()) if str(value).strip()
            )
            if section == "tax_components" and (ref in vat_refs or represented_by):
                item["posting_requirement"] = "represented"
                item["payable_membership"] = "yes"
                item["total_memberships"]["payable_total"] = "yes"
                item["total_membership_basis"]["payable_total"] = "arithmetic_exact"
                represented_refs.add(ref)
                continue
            amount = _money(item.get(amount_field))
            if amount is None:
                item["warnings"].append("amount_invalid")
                unresolved_refs.add(ref)
                continue
            effect = _reconciled_effect(item, section=section, effect_field=effect_field)
            if effect not in {
                "increase_tax",
                "increase_payable",
                "reduce_payable",
                "decrease_payable",
            }:
                item["warnings"].append("economic_effect_unknown")
                unresolved_refs.add(ref)
                continue
            item["reconciled_effect"] = effect
            item["posting_side"] = _posting_side(
                str(result.get("document_direction") or ""),
                effect,
            )
            candidates.append(
                _ComponentCandidate(
                    ref=ref,
                    section=section,
                    index=index,
                    amount=abs(amount),
                    effect=effect,
                    payable_hint=_state(item.get("included_in_payable")),
                    line_net_hint=_state(item.get("included_in_line_net")),
                    treatment=_reconciled_treatment(item, section=section),
                )
            )

    payable_total = _money(totals.get("payable_total"))
    state_limited = False
    if payable_total is None:
        payable_modes = tuple(_preferred_mode(candidate) for candidate in candidates)
        payable_basis = "semantic"
        status = "not_testable"
        residual: Decimal | None = None
        summary_warnings = ["monetary_reconciliation_not_testable"]
    else:
        target_component_effect = payable_total - mandatory_total
        payable_modes, state_limited = _solve_component_modes(
            candidates,
            target_component_effect,
            max_states=max_states,
        )
        selected_effect = _selected_effect(candidates, payable_modes)
        residual = payable_total - (mandatory_total + selected_effect)
        exact = residual == Decimal("0.00") and line_complete and vat_complete
        status = "exact" if exact else "partial"
        payable_basis = "arithmetic_exact" if exact else "arithmetic_best_fit"
        summary_warnings = [] if exact else ["monetary_reconciliation_residual"]
    if state_limited:
        summary_warnings.append("monetary_reconciliation_state_limit")

    selected_refs: list[str] = []
    excluded_refs: list[str] = []
    for candidate, mode in zip(candidates, payable_modes):
        item = components[candidate.section][candidate.index]
        item["posting_requirement"] = mode
        payable_state = "yes" if mode in {"separate", "represented"} else "no"
        item["payable_membership"] = payable_state
        item["total_memberships"]["payable_total"] = payable_state
        item["total_membership_basis"]["payable_total"] = payable_basis
        if mode == "represented":
            item["total_memberships"]["line_net_total"] = "yes"
            item["total_membership_basis"]["line_net_total"] = payable_basis
            selected_refs.append(candidate.ref)
        elif mode == "separate":
            item["total_memberships"]["line_net_total"] = "no"
            item["total_membership_basis"]["line_net_total"] = payable_basis
            selected_refs.append(candidate.ref)
        else:
            item["total_memberships"]["line_net_total"] = "no"
            item["total_membership_basis"]["line_net_total"] = payable_basis
            excluded_refs.append(candidate.ref)

    _annotate_vat_memberships(tax_components, monetary_components, vat_refs)
    _annotate_named_total(
        components,
        candidates,
        total_name="special_tax_total",
        target=_money(totals.get("special_tax_total")),
        baseline=Decimal("0.00"),
        eligible=lambda candidate: (
            candidate.section == "tax_components"
            and candidate.effect in {"increase_tax", "increase_payable"}
        ),
        max_states=max_states,
    )
    gross_total, gross_complete = _sum_money(item.get("gross_amount") for item in line_items)
    _annotate_named_total(
        components,
        candidates,
        total_name="line_gross_total",
        target=gross_total if gross_complete and line_items else None,
        baseline=mandatory_total,
        eligible=lambda candidate: candidate.effect in {"increase_tax", "increase_payable"},
        max_states=max_states,
    )
    tax_inclusive_total = _money(totals.get("tax_inclusive_total"))
    _annotate_named_total(
        components,
        candidates,
        total_name="tax_inclusive_total",
        target=tax_inclusive_total,
        baseline=mandatory_total,
        eligible=lambda candidate: True,
        max_states=max_states,
    )
    _annotate_represented_vat_memberships(
        tax_components,
        line_gross_observed=gross_complete and bool(line_items),
        tax_inclusive_observed=tax_inclusive_total is not None,
    )

    selected_effect = _selected_effect(candidates, payable_modes)
    reconciled_payable = mandatory_total + selected_effect
    projection_warnings = [
        str(value) for value in result.get("projection_warnings", ()) if str(value)
    ]
    projection_warnings.extend(summary_warnings)
    result["projection_warnings"] = list(dict.fromkeys(projection_warnings))
    result["monetary_reconciliation"] = {
        "status": status,
        "observed_payable_total": _money_text(payable_total),
        "mandatory_line_vat_total": _money_text(mandatory_total),
        "line_baseline_total": _money_text(line_total),
        "line_baseline_basis": line_baseline_basis,
        "line_allocation_adjustment": _money_text(line_allocation_adjustment),
        "selected_component_effect_total": _money_text(selected_effect),
        "reconciled_payable_total": _money_text(reconciled_payable),
        "residual": _money_text(residual),
        "selected_component_refs": list(dict.fromkeys(selected_refs)),
        "excluded_component_refs": list(dict.fromkeys(excluded_refs)),
        "represented_component_refs": list(dict.fromkeys(represented_refs)),
        "unresolved_component_refs": list(dict.fromkeys(unresolved_refs)),
        "warnings": list(dict.fromkeys(summary_warnings)),
        "component_hypotheses": [
            {
                "decision_ref": candidate.ref,
                "source_section": candidate.section,
                "amount": _money_text(candidate.amount),
                "deterministic_effect": candidate.effect,
                "possible_topologies": list(candidate.modes),
            }
            for candidate in candidates
        ],
    }
    return result


def _allocate_visible_line_amounts(
    line_items: list[dict[str, object]],
    *,
    target: Decimal,
) -> Decimal:
    if not line_items:
        return Decimal("0.00")
    visible: list[Decimal] = []
    for item in line_items:
        amount = _money(item.get("taxable_amount"))
        if amount is None:
            amount = _money(item.get("gross_amount"))
        if amount is None:
            return Decimal("0.00")
        visible.append(amount)
    adjustment = target - sum(visible, Decimal("0.00"))
    if abs(adjustment) > _CENT * max(len(line_items), 1):
        return Decimal("0.00")
    for index, (item, amount) in enumerate(zip(line_items, visible)):
        item_adjustment = adjustment if index == len(line_items) - 1 else Decimal("0.00")
        item["posting_amount"] = _money_text(amount + item_adjustment)
        item["allocation_adjustment"] = _money_text(item_adjustment)
    return adjustment


def _solve_component_modes(
    candidates: Sequence[_ComponentCandidate],
    target: Decimal,
    *,
    max_states: int,
) -> tuple[tuple[str, ...], bool]:
    target_cents = _cents(target)
    states: dict[int, _Choice] = {0: _Choice((), 0)}
    limited = False
    for candidate in candidates:
        next_states: dict[int, _Choice] = {}
        signed_cents = _cents(candidate.signed_amount)
        for subtotal, choice in states.items():
            for mode in candidate.modes:
                contribution = signed_cents if mode == "separate" else 0
                candidate_choice = _Choice(
                    modes=(*choice.modes, mode),
                    preference_penalty=(
                        choice.preference_penalty + _mode_penalty(candidate, mode)
                    ),
                )
                new_total = subtotal + contribution
                existing = next_states.get(new_total)
                if existing is None or _choice_key(candidate_choice) < _choice_key(existing):
                    next_states[new_total] = candidate_choice
        if len(next_states) > max_states:
            limited = True
            ranked = sorted(
                next_states.items(),
                key=lambda pair: (
                    abs(target_cents - pair[0]),
                    pair[1].preference_penalty,
                    pair[0],
                    pair[1].modes,
                ),
            )
            next_states = dict(ranked[:max_states])
        states = next_states
    _, best = min(
        states.items(),
        key=lambda pair: (
            abs(target_cents - pair[0]),
            pair[1].preference_penalty,
            pair[0],
            pair[1].modes,
        ),
    )
    return best.modes, limited


def _solve_binary_membership(
    candidates: Sequence[_ComponentCandidate],
    target: Decimal,
    *,
    max_states: int,
) -> tuple[set[str], bool, bool]:
    target_cents = _cents(target)
    states: dict[int, tuple[tuple[str, ...], int]] = {0: ((), 0)}
    limited = False
    for candidate in candidates:
        next_states: dict[int, tuple[tuple[str, ...], int]] = {}
        amount = _cents(candidate.signed_amount)
        for subtotal, (selected, penalty) in states.items():
            for include in (False, True):
                new_total = subtotal + (amount if include else 0)
                new_selected = (*selected, candidate.ref) if include else selected
                new_penalty = penalty + (0 if include else 1)
                existing = next_states.get(new_total)
                value = (new_selected, new_penalty)
                if existing is None or (new_penalty, new_selected) < (existing[1], existing[0]):
                    next_states[new_total] = value
        if len(next_states) > max_states:
            limited = True
            ranked = sorted(
                next_states.items(),
                key=lambda pair: (
                    abs(target_cents - pair[0]),
                    pair[1][1],
                    pair[0],
                    pair[1][0],
                ),
            )
            next_states = dict(ranked[:max_states])
        states = next_states
    best_total, (selected, _) = min(
        states.items(),
        key=lambda pair: (
            abs(target_cents - pair[0]),
            pair[1][1],
            pair[0],
            pair[1][0],
        ),
    )
    return set(selected), best_total == target_cents, limited


def _annotate_named_total(
    components: Mapping[str, list[dict[str, object]]],
    candidates: Sequence[_ComponentCandidate],
    *,
    total_name: str,
    target: Decimal | None,
    baseline: Decimal,
    eligible: Callable[[_ComponentCandidate], bool],
    max_states: int,
) -> None:
    selected_candidates = [candidate for candidate in candidates if eligible(candidate)]
    if target is None:
        return
    selected, exact, _ = _solve_binary_membership(
        selected_candidates,
        target - baseline,
        max_states=max_states,
    )
    basis = "arithmetic_exact" if exact else "arithmetic_best_fit"
    eligible_refs = {candidate.ref for candidate in selected_candidates}
    for section_items in components.values():
        for item in section_items:
            ref = str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
            if ref not in eligible_refs:
                if item["total_memberships"][total_name] == "unknown":
                    item["total_memberships"][total_name] = "no"
                    item["total_membership_basis"][total_name] = "not_applicable"
                continue
            item["total_memberships"][total_name] = "yes" if ref in selected else "no"
            item["total_membership_basis"][total_name] = basis


def _annotate_vat_memberships(
    tax_components: Sequence[dict[str, object]],
    monetary_components: Sequence[dict[str, object]],
    vat_refs: set[str],
) -> None:
    for item in tax_components:
        ref = str(item.get("identity_ref") or item.get("decision_ref") or "").strip()
        represented_by = {
            str(value).strip() for value in item.get("represented_by_refs", ()) if str(value).strip()
        }
        is_vat = str(item.get("canonical_tax_kind") or "").strip().lower() == "vat"
        state = "yes" if is_vat and (ref in vat_refs or represented_by & vat_refs) else "no"
        item["total_memberships"]["vat_total"] = state
        item["total_membership_basis"]["vat_total"] = (
            "arithmetic_exact" if state == "yes" else "not_applicable"
        )
    for item in monetary_components:
        item["total_memberships"]["vat_total"] = "no"
        item["total_membership_basis"]["vat_total"] = "not_applicable"


def _annotate_represented_vat_memberships(
    tax_components: Sequence[dict[str, object]],
    *,
    line_gross_observed: bool,
    tax_inclusive_observed: bool,
) -> None:
    for item in tax_components:
        if str(item.get("canonical_tax_kind") or "").strip().lower() != "vat":
            continue
        if str(item.get("posting_requirement") or "").strip().lower() != "represented":
            continue
        item["total_memberships"]["line_net_total"] = "no"
        item["total_membership_basis"]["line_net_total"] = "not_applicable"
        if line_gross_observed:
            item["total_memberships"]["line_gross_total"] = "yes"
            item["total_membership_basis"]["line_gross_total"] = "arithmetic_exact"
        if tax_inclusive_observed:
            item["total_memberships"]["tax_inclusive_total"] = "yes"
            item["total_membership_basis"]["tax_inclusive_total"] = "arithmetic_exact"


def _preferred_mode(candidate: _ComponentCandidate) -> str:
    return min(candidate.modes, key=lambda mode: (_mode_penalty(candidate, mode), mode))


def _mode_penalty(candidate: _ComponentCandidate, mode: str) -> int:
    penalty = {"separate": 0, "represented": 1, "excluded": 2}[mode]
    if candidate.treatment in {"informational", "exclude_current_period"}:
        penalty += 0 if mode == "excluded" else 4
    if candidate.line_net_hint == "yes":
        penalty += 0 if mode == "represented" else 2 if mode == "separate" else 1
    elif candidate.line_net_hint == "no" and mode == "represented":
        penalty += 2
    if candidate.payable_hint == "yes" and mode == "excluded":
        penalty += 2
    elif candidate.payable_hint == "no" and mode != "excluded":
        penalty += 1
    return penalty


def _choice_key(choice: _Choice) -> tuple[object, ...]:
    return choice.preference_penalty, choice.modes


def _selected_effect(
    candidates: Sequence[_ComponentCandidate],
    modes: Sequence[str],
) -> Decimal:
    return sum(
        (
            candidate.signed_amount
            for candidate, mode in zip(candidates, modes)
            if mode == "separate"
        ),
        Decimal("0.00"),
    ).quantize(_CENT, rounding=ROUND_HALF_UP)


def _mutable_items(container: dict[str, object], field: str) -> list[dict[str, object]]:
    raw = container.get(field)
    items = [dict(item) for item in raw if isinstance(item, Mapping)] if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
    container[field] = items
    return items


def _sum_money(values: Iterable[object]) -> tuple[Decimal, bool]:
    parsed: list[Decimal] = []
    complete = True
    for value in values:
        amount = _money(value)
        if amount is None:
            complete = False
        else:
            parsed.append(amount)
    return sum(parsed, Decimal("0.00")).quantize(_CENT), complete


def _sum_unique_money(
    items: Sequence[Mapping[str, object]],
    identity_field: str,
    amount_field: str,
) -> tuple[Decimal, bool]:
    seen: set[str] = set()
    values: list[object] = []
    for index, item in enumerate(items):
        identity = str(item.get(identity_field) or f"index:{index}")
        if identity in seen:
            continue
        seen.add(identity)
        values.append(item.get(amount_field))
    return _sum_money(values)


def _money(value: object) -> Decimal | None:
    raw = str(value if value is not None else "").strip().replace(" ", "").strip("%")
    raw = re.sub(r"^[^0-9+\-.,]+|[^0-9.,]+$", "", raw)
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    try:
        return parsed.quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _money_text(value: Decimal | None) -> str:
    return "" if value is None else format(value.quantize(_CENT), ".2f")


def _cents(value: Decimal) -> int:
    return int((value.quantize(_CENT) * 100).to_integral_value())


def _state(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"yes", "no"} else "unknown"


def _reconciled_effect(
    item: Mapping[str, object],
    *,
    section: str,
    effect_field: str,
) -> str:
    if section == "monetary_components":
        kind = str(item.get("canonical_component_kind") or "").strip().lower()
        label = str(item.get("source_label") or "").strip().lower()
        if kind in {"discount", "allowance"} or any(
            token in label for token in ("discount", "indirim", "iskonto")
        ):
            return "reduce_payable"
        if kind == "prior_period_balance":
            return "increase_payable"
        if kind == "next_period_balance":
            return "decrease_payable"
    return str(item.get(effect_field) or "").strip().lower()


def _augment_source_backed_component_ledger(
    projection: Mapping[str, object],
    monetary_components: list[dict[str, object]],
) -> None:
    existing_keys = {
        _ledger_component_key(
            item.get("source_label"),
            item.get("source_amount"),
        )
        for item in monetary_components
    }
    totals = projection.get("totals")
    totals = totals if isinstance(totals, Mapping) else {}
    allowance = _money(totals.get("allowance_total"))
    if allowance not in {None, Decimal("0.00")}:
        key = _ledger_component_key("allowance_total", allowance)
        allowance_already_observed = any(
            _money(item.get("source_amount")) == allowance
            and _is_allowance_component(item)
            for item in monetary_components
        )
        if key not in existing_keys and not allowance_already_observed:
            monetary_components.append(
                _synthetic_component(
                    source_label="allowance_total",
                    source_amount=allowance,
                    source_position="totals.allowance_total",
                    source_evidence_refs=_evidence_refs(
                        totals.get("source_evidence_refs")
                    ),
                    ledger_source="allowance_total",
                    canonical_kind="allowance",
                    signed_effect="reduce_payable",
                )
            )
            existing_keys.add(key)

    named_totals = projection.get("named_totals")
    if not isinstance(named_totals, Sequence) or isinstance(named_totals, (str, bytes)):
        return
    excluded_roles = {
        "payable_total",
        "tax_inclusive_total",
        "goods_services_total",
        "tax_exclusive_total",
        "vat_total",
        "special_tax_total",
    }
    for item in named_totals:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("proposed_role") or "other").strip().lower()
        if role in excluded_roles:
            continue
        amount = _money(item.get("amount"))
        if amount in {None, Decimal("0.00")}:
            continue
        label = str(item.get("source_label") or "").strip()
        key = _ledger_component_key(label, amount)
        if key in existing_keys:
            continue
        raw_evidence = item.get("source_evidence_refs") or ()
        evidence = (
            tuple(str(value).strip() for value in raw_evidence if str(value).strip())
            if isinstance(raw_evidence, Sequence)
            and not isinstance(raw_evidence, (str, bytes))
            else ()
        )
        normalized_label = label.casefold()
        reduce = any(
            token in normalized_label for token in ("discount", "indirim", "iskonto")
        )
        monetary_components.append(
            _synthetic_component(
                source_label=label,
                source_amount=amount,
                source_position=str(item.get("source_position") or ""),
                source_evidence_refs=evidence,
                ledger_source="named_total",
                canonical_kind="named_monetary_component",
                signed_effect="reduce_payable" if reduce else "increase_payable",
            )
        )
        existing_keys.add(key)


def _synthetic_component(
    *,
    source_label: str,
    source_amount: Decimal,
    source_position: str,
    source_evidence_refs: Sequence[str],
    ledger_source: str,
    canonical_kind: str,
    signed_effect: str,
) -> dict[str, object]:
    identity_seed = "|".join(
        (source_label.casefold(), _money_text(source_amount), source_position)
    )
    component_id = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:16]
    decision_ref = f"monetary:ledger_{component_id}"
    return {
        "component_id": f"ledger_{component_id}",
        "identity_ref": decision_ref,
        "decision_ref": decision_ref,
        "source_label": source_label,
        "source_amount": _money_text(source_amount),
        "source_position": source_position,
        "source_evidence_refs": list(source_evidence_refs),
        "canonical_component_kind": canonical_kind,
        "accounting_treatment": "",
        "signed_effect": signed_effect,
        "included_in_line_net": "unknown",
        "included_in_tax_total": "no",
        "included_in_payable": "unknown",
        "ledger_source": ledger_source,
        "warnings": [],
    }


def _ledger_component_key(label: object, amount: object) -> tuple[str, str]:
    normalized_label = " ".join(str(label or "").casefold().split())
    parsed = _money(amount)
    return normalized_label, _money_text(parsed)


def _evidence_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _is_allowance_component(item: Mapping[str, object]) -> bool:
    kind = str(item.get("canonical_component_kind") or "").strip().lower()
    label = str(item.get("source_label") or "").strip().lower()
    return kind in {"discount", "allowance"} or any(
        token in label for token in ("discount", "indirim", "iskonto")
    )


def _reconciled_treatment(
    item: Mapping[str, object],
    *,
    section: str,
) -> str:
    if section == "monetary_components":
        kind = str(item.get("canonical_component_kind") or "").strip().lower()
        if kind in {"prior_period_balance", "next_period_balance"}:
            return "separate_posting"
    return str(item.get("accounting_treatment") or "").strip().lower()


def _posting_side(direction: str, effect: str) -> str:
    resolved_direction = str(direction or "").strip().lower()
    if resolved_direction not in {"purchase", "sales"}:
        return "unknown"
    purchase_debit = effect in {"increase_tax", "increase_payable"}
    if resolved_direction == "sales":
        purchase_debit = not purchase_debit
    return "debit" if purchase_debit else "credit"
