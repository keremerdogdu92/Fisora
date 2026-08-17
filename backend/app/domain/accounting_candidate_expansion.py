from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import ClassVar, Mapping


class CandidateProtocolError(ValueError):
    """Raised when a caller attempts an invalid session transition."""


class CandidateIntegrityError(CandidateProtocolError):
    """Raised when a candidate is not both tenant-owned and already sent."""


@dataclass(frozen=True)
class NewCounterpartyProposal:
    party_title: str
    tax_id: str
    direction: str
    suggested_parent_family: str = ""


@dataclass(frozen=True)
class SelectedAccount:
    selected_candidate_id: str
    reason: str = ""


@dataclass(frozen=True)
class LineAccountSelection(SelectedAccount):
    line_ref: str = ""

    def __init__(self, line_ref: str, selected_candidate_id: str, reason: str = "") -> None:
        object.__setattr__(self, "line_ref", line_ref)
        object.__setattr__(self, "selected_candidate_id", selected_candidate_id)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class VatAccountSelection(SelectedAccount):
    vat_ref: str = ""
    rate: str = ""

    def __init__(
        self,
        vat_ref: str,
        rate: str,
        selected_candidate_id: str,
        reason: str = "",
    ) -> None:
        object.__setattr__(self, "vat_ref", vat_ref)
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "selected_candidate_id", selected_candidate_id)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class SpecialTaxAccountSelection(SelectedAccount):
    tax_ref: str = ""
    component_type: str = ""

    def __init__(
        self,
        tax_ref: str,
        component_type: str,
        selected_candidate_id: str,
        reason: str = "",
    ) -> None:
        object.__setattr__(self, "tax_ref", tax_ref)
        object.__setattr__(self, "component_type", component_type)
        object.__setattr__(self, "selected_candidate_id", selected_candidate_id)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class AccountingProposal:
    counterparty_account: SelectedAccount | None = None
    line_accounts: tuple[LineAccountSelection, ...] = ()
    vat_accounts: tuple[VatAccountSelection, ...] = ()
    special_tax_accounts: tuple[SpecialTaxAccountSelection, ...] = ()
    new_counterparty_proposal: NewCounterpartyProposal | None = None

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        selections: list[SelectedAccount] = []
        if self.counterparty_account is not None:
            selections.append(self.counterparty_account)
        selections.extend(self.line_accounts)
        selections.extend(self.vat_accounts)
        selections.extend(self.special_tax_accounts)
        return _ordered_unique_candidate_ids(
            tuple(item.selected_candidate_id for item in selections)
        )


@dataclass(frozen=True)
class SelectExistingDecision:
    selected_candidate_id: str
    reason: str = ""
    action: str = field(default="select_existing", init=False)


@dataclass(frozen=True)
class RequestMoreCandidatesDecision:
    search_terms: tuple[str, ...]
    requested_scope: str
    reason: str
    provisional_candidate_id: str | None = None
    provisional_proposal: object | None = None
    action: str = field(default="request_more_candidates", init=False)


@dataclass(frozen=True)
class ProposeNewDecision:
    proposal: NewCounterpartyProposal
    reason: str = ""
    action: str = field(default="propose_new", init=False)


@dataclass(frozen=True)
class FinalizeProposalDecision:
    proposal: object
    reason: str = ""
    action: str = field(default="finalize", init=False)


AccountingCandidateDecision = (
    SelectExistingDecision
    | RequestMoreCandidatesDecision
    | ProposeNewDecision
    | FinalizeProposalDecision
)


@dataclass(frozen=True)
class CandidateRound:
    round_index: int
    candidate_ids: tuple[str, ...]
    decision: AccountingCandidateDecision | None = None


@dataclass(frozen=True)
class AccountingCandidateSession:
    """Pure state for one bounded, accumulating accounting candidate decision."""

    MAX_EXPANSION_ATTEMPTS: ClassVar[int] = 2

    tenant_candidate_ids: frozenset[str]
    rounds: tuple[CandidateRound, ...]
    provisional_candidate_id: str | None = None
    provisional_proposal: object | None = None
    final_action: str | None = None
    selected_candidate_id: str | None = None
    new_counterparty_proposal: NewCounterpartyProposal | None = None
    final_proposal: object | None = None
    pending_expansion_request: RequestMoreCandidatesDecision | None = None
    expansion_limit_reached: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rounds:
            raise CandidateProtocolError("candidate session requires an initial round")
        if len(self.rounds) > self.MAX_EXPANSION_ATTEMPTS + 1:
            raise CandidateProtocolError(
                "candidate session cannot contain more than three accounting calls"
            )
        expected_indexes = tuple(range(len(self.rounds)))
        received_indexes = tuple(
            candidate_round.round_index for candidate_round in self.rounds
        )
        if received_indexes != expected_indexes:
            raise CandidateProtocolError("candidate round indexes must be sequential")

    @classmethod
    def start(
        cls,
        *,
        tenant_candidate_ids: tuple[str, ...],
        initial_candidate_ids: tuple[str, ...],
    ) -> AccountingCandidateSession:
        tenant_ids = frozenset(_ordered_unique_candidate_ids(tenant_candidate_ids))
        initial_ids = _ordered_unique_candidate_ids(initial_candidate_ids)
        _require_tenant_candidates(initial_ids, tenant_ids)
        return cls(
            tenant_candidate_ids=tenant_ids,
            rounds=(CandidateRound(round_index=0, candidate_ids=initial_ids),),
        )

    @property
    def current_candidate_ids(self) -> tuple[str, ...]:
        return self.rounds[-1].candidate_ids

    @property
    def accumulated_candidate_ids(self) -> tuple[str, ...]:
        return self.current_candidate_ids

    @property
    def accounting_call_count(self) -> int:
        return len(self.rounds)

    @property
    def expansion_count(self) -> int:
        return len(self.rounds) - 1

    @property
    def can_expand(self) -> bool:
        return (
            self.pending_expansion_request is not None
            and self.expansion_count < self.MAX_EXPANSION_ATTEMPTS
        )

    def selection_origin_round(self, candidate_id: str) -> int | None:
        for candidate_round in self.rounds:
            if candidate_id in candidate_round.candidate_ids:
                return candidate_round.round_index
        return None

    def record_decision(
        self,
        decision: AccountingCandidateDecision,
    ) -> AccountingCandidateSession:
        if self.final_action is not None:
            raise CandidateProtocolError("candidate session already has a final decision")
        if self.rounds[-1].decision is not None:
            raise CandidateProtocolError("current accounting call already has a decision")

        updated_rounds = _replace_current_round_decision(self.rounds, decision)

        if isinstance(decision, FinalizeProposalDecision):
            self._require_valid_proposal(decision.proposal)
            return replace(
                self,
                rounds=updated_rounds,
                final_action=decision.action,
                final_proposal=decision.proposal,
                pending_expansion_request=None,
            )

        if isinstance(decision, SelectExistingDecision):
            self._require_sent_real_candidate(decision.selected_candidate_id)
            return replace(
                self,
                rounds=updated_rounds,
                final_action=decision.action,
                selected_candidate_id=decision.selected_candidate_id,
                pending_expansion_request=None,
            )

        if isinstance(decision, ProposeNewDecision):
            return replace(
                self,
                rounds=updated_rounds,
                final_action=decision.action,
                selected_candidate_id=None,
                new_counterparty_proposal=decision.proposal,
                pending_expansion_request=None,
            )

        if not isinstance(decision, RequestMoreCandidatesDecision):
            raise TypeError("unsupported accounting candidate decision")

        provisional = self.provisional_candidate_id
        if decision.provisional_candidate_id is not None:
            self._require_sent_real_candidate(decision.provisional_candidate_id)
            provisional = decision.provisional_candidate_id
        provisional_proposal = self.provisional_proposal
        if decision.provisional_proposal is not None:
            self._require_valid_proposal(decision.provisional_proposal)
            provisional_proposal = decision.provisional_proposal

        if self.expansion_count >= self.MAX_EXPANSION_ATTEMPTS:
            return self._terminalize_best_available(
                rounds=updated_rounds,
                provisional_candidate_id=provisional,
                provisional_proposal=provisional_proposal,
                expansion_limit_reached=True,
                warning="candidate_expansion_limit_reached",
            )

        return replace(
            self,
            rounds=updated_rounds,
            provisional_candidate_id=provisional,
            provisional_proposal=provisional_proposal,
            pending_expansion_request=decision,
        )

    def add_expansion_candidates(
        self,
        candidate_ids: tuple[str, ...],
    ) -> AccountingCandidateSession:
        if not self.can_expand:
            raise CandidateProtocolError("no candidate expansion call is available")

        expansion_ids = _ordered_unique_candidate_ids(candidate_ids)
        _require_tenant_candidates(expansion_ids, self.tenant_candidate_ids)
        accumulated_ids = _ordered_unique_candidate_ids(
            self.accumulated_candidate_ids + expansion_ids
        )
        if accumulated_ids == self.accumulated_candidate_ids:
            return self._terminalize_best_available(
                warning="candidate_expansion_returned_no_new_candidates"
            )

        next_round = CandidateRound(
            round_index=len(self.rounds),
            candidate_ids=accumulated_ids,
        )
        return replace(
            self,
            rounds=self.rounds + (next_round,),
            pending_expansion_request=None,
        )

    def _terminalize_best_available(
        self,
        *,
        warning: str,
        rounds: tuple[CandidateRound, ...] | None = None,
        provisional_candidate_id: str | None = None,
        provisional_proposal: object | None = None,
        expansion_limit_reached: bool = False,
    ) -> AccountingCandidateSession:
        provisional = (
            self.provisional_candidate_id
            if provisional_candidate_id is None
            else provisional_candidate_id
        )
        best_proposal = (
            self.provisional_proposal
            if provisional_proposal is None
            else provisional_proposal
        )
        warnings = self.warnings
        if warning not in warnings:
            warnings += (warning,)
        return replace(
            self,
            rounds=self.rounds if rounds is None else rounds,
            provisional_candidate_id=provisional,
            provisional_proposal=best_proposal,
            final_action=(
                "finalize"
                if best_proposal is not None
                else "select_existing" if provisional is not None else "unresolved"
            ),
            selected_candidate_id=provisional,
            final_proposal=best_proposal,
            pending_expansion_request=None,
            expansion_limit_reached=expansion_limit_reached,
            warnings=warnings,
        )

    def terminalize_best_available(self, warning: str) -> AccountingCandidateSession:
        return self._terminalize_best_available(warning=warning)

    def _require_valid_proposal(self, proposal: object) -> None:
        for candidate_id in _proposal_candidate_ids(proposal):
            self._require_sent_real_candidate(candidate_id)

    def _require_sent_real_candidate(self, candidate_id: str) -> None:
        if candidate_id not in self.tenant_candidate_ids:
            raise CandidateIntegrityError(
                f"candidate is not in the tenant plan: {candidate_id!r}"
            )
        if candidate_id not in self.accumulated_candidate_ids:
            raise CandidateIntegrityError(
                f"candidate was not sent to the accounting AI: {candidate_id!r}"
            )


def _ordered_unique_candidate_ids(candidate_ids: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate_id in candidate_ids:
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise CandidateIntegrityError("candidate IDs must be non-empty strings")
        if candidate_id not in seen:
            seen.add(candidate_id)
            ordered.append(candidate_id)
    return tuple(ordered)


def _require_tenant_candidates(
    candidate_ids: tuple[str, ...],
    tenant_candidate_ids: frozenset[str],
) -> None:
    unknown = tuple(
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in tenant_candidate_ids
    )
    if unknown:
        raise CandidateIntegrityError(
            f"candidates are not in the tenant plan: {unknown!r}"
        )


def _replace_current_round_decision(
    rounds: tuple[CandidateRound, ...],
    decision: AccountingCandidateDecision,
) -> tuple[CandidateRound, ...]:
    return rounds[:-1] + (replace(rounds[-1], decision=decision),)


def _proposal_candidate_ids(proposal: object) -> tuple[str, ...]:
    selected_ids = getattr(proposal, "selected_candidate_ids", None)
    if selected_ids is not None:
        return _ordered_unique_candidate_ids(tuple(selected_ids))
    if isinstance(proposal, Mapping):
        found: list[str] = []

        def visit(value: object) -> None:
            if isinstance(value, Mapping):
                selected = value.get("selected_candidate_id")
                if isinstance(selected, str) and selected.strip():
                    found.append(selected)
                for child in value.values():
                    visit(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    visit(child)

        visit(proposal)
        return _ordered_unique_candidate_ids(tuple(found)) if found else ()
    raise CandidateIntegrityError(
        "proposal must expose selected_candidate_ids or be a mapping"
    )
