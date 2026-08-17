from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
import json
from typing import Mapping, Sequence

from app.domain.accounting_candidate_builder import AccountingCandidate
from app.domain.accounting_candidate_expansion import CandidateIntegrityError
from app.domain.ai_classification import AiCandidateStrategy


@dataclass(frozen=True)
class AccountingProposalRequestContextV2:
    semantic_stage: str = "accounting_selection_v2"
    clarification_decision: Mapping[str, object] = field(default_factory=dict)
    candidate_strategy: AiCandidateStrategy = field(
        default_factory=lambda: AiCandidateStrategy(
            mode="bounded_expansion",
            stage="accounting_selection_v2",
        )
    )


@dataclass(frozen=True)
class AccountingProposalRequestV2:
    projection: Mapping[str, object]
    sent_candidates: tuple[AccountingCandidate, ...]
    required_decision_refs: tuple[str, ...]
    context: AccountingProposalRequestContextV2 = field(
        default_factory=AccountingProposalRequestContextV2
    )

    def to_schema_payload(self) -> dict[str, object]:
        candidates = tuple(candidate for candidate in self.sent_candidates if candidate.active)
        facts = {
            key: self.projection[key]
            for key in (
                "document_direction",
                "header",
                "supplier_party",
                "customer_party",
                "line_items",
                "vat_summary",
                "tax_components",
                "monetary_components",
                "totals",
                "warnings",
                "projection_warnings",
            )
            if key in self.projection
        }
        raw_context = self.projection.get("client_context")
        raw_context = raw_context if isinstance(raw_context, Mapping) else {}
        client_context = {
            key: value
            for key in ("activity_description", "nace_code", "activity_tags")
            for value in (raw_context.get(key),)
            if _safe_context_value(value)
        }
        facts["client_context"] = client_context
        strategy = self.context.candidate_strategy
        candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
        payload: dict[str, object] = {
            "stage": strategy.stage,
            "client_activity": str(client_context.get("activity_description") or ""),
            "raw_line": json.dumps(
                facts,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ),
            "candidate_strategy": {
                "mode": strategy.mode,
                "stage": strategy.stage,
                "account_candidate_count": len(candidates),
                "counterparty_candidate_count": len(candidates),
                "selected_families": list(strategy.selected_families),
            },
            "account_candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "code": candidate.code,
                    "name": candidate.name,
                    "roles": list(candidate.roles),
                    "tax_id": candidate.normalized_tax_id,
                    "tax_office": candidate.tax_office,
                    "vat_rates": list(candidate.vat_rates),
                    "is_active": candidate.active,
                    "origin_round": candidate.origin_round,
                }
                for candidate in candidates
            ],
            "output_schema": _proposal_output_schema(
                self.required_decision_refs,
                candidate_ids,
                self.projection,
            ),
        }
        if (
            self.context.semantic_stage == "treatment_clarification"
            and self.context.clarification_decision
        ):
            payload["clarification_decision"] = {
                key: str(self.context.clarification_decision.get(key) or "")
                for key in (
                    "decision_ref",
                    "action",
                    "selected_candidate_id",
                    "selected_treatment",
                    "reason",
                )
            }
        return payload


@dataclass(frozen=True)
class AccountingDecisionV2:
    decision_ref: str
    action: str
    selected_candidate_id: str = ""
    candidate: AccountingCandidate | None = None
    reason: str = ""
    selected_treatment: str = ""
    treatment_review_required: bool = False
    proposal: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountingDecisionValidationIssue:
    decision_ref: str
    code: str
    message: str
    round_index: int
    chunk_index: int
    receipt_artifact_id: str


@dataclass(frozen=True)
class SemanticConflict:
    decision_ref: str
    conflict_code: str
    deterministic_expectation: str
    ai_selection_or_treatment: str
    ai_reason: str
    candidate_round_index: int
    candidate_id: str
    source_evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class AccountingProposalParseResult:
    counterparty: AccountingDecisionV2
    valid_decisions: tuple[AccountingDecisionV2, ...]
    issues: tuple[AccountingDecisionValidationIssue, ...]
    sufficiency: Mapping[str, object]

    def to_proposal(
        self,
        *,
        required_decision_refs: Sequence[str],
        sent_candidate_ids: Sequence[str],
    ) -> AccountingProposalV2:
        required = tuple(dict.fromkeys(required_decision_refs))
        by_ref = {
            decision.decision_ref: decision
            for decision in self.valid_decisions
            if decision.decision_ref != "counterparty"
        }
        decisions = [self.counterparty]
        for decision_ref in required:
            if decision_ref == "counterparty":
                continue
            decisions.append(
                by_ref.get(decision_ref)
                or AccountingDecisionV2(
                    decision_ref=decision_ref,
                    action="unresolved",
                    reason="no valid AI decision is available for this reference",
                )
            )
        return AccountingProposalV2(
            counterparty=self.counterparty,
            decisions=tuple(decisions),
            required_decision_refs=required,
            candidate_sufficient=bool(self.sufficiency.get("sufficient", False)),
            request_more_candidates=bool(
                self.sufficiency.get("request_more_candidates", False)
            ),
            search_terms=tuple(self.sufficiency.get("search_terms", ())),
            sufficiency_reason=str(self.sufficiency.get("reason") or ""),
            provisional=bool(self.sufficiency.get("provisional", False)),
            sent_candidate_ids=tuple(dict.fromkeys(sent_candidate_ids)),
            validation_issues=self.issues,
        )


@dataclass(frozen=True)
class AccountingProposalV2:
    counterparty: AccountingDecisionV2
    decisions: tuple[AccountingDecisionV2, ...]
    required_decision_refs: tuple[str, ...]
    candidate_sufficient: bool
    request_more_candidates: bool
    search_terms: tuple[str, ...]
    sufficiency_reason: str
    provisional: bool
    sent_candidate_ids: tuple[str, ...]
    validation_issues: tuple[AccountingDecisionValidationIssue, ...] = ()
    warnings: tuple[str, ...] = ()
    semantic_conflicts: tuple[SemanticConflict, ...] = ()

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        values = (
            decision.selected_candidate_id
            for decision in self.decisions
            if decision.action == "select_existing"
        )
        return tuple(dict.fromkeys(value for value in values if value))

    @property
    def unresolved_decision_refs(self) -> tuple[str, ...]:
        return tuple(
            decision.decision_ref
            for decision in self.decisions
            if decision.action == "unresolved"
        )

    @property
    def treatment_clarification_refs(self) -> tuple[str, ...]:
        return tuple(
            decision.decision_ref
            for decision in self.decisions
            if decision.treatment_review_required
        )

    def decision_for(self, decision_ref: str) -> AccountingDecisionV2:
        for decision in self.decisions:
            if decision.decision_ref == decision_ref:
                return decision
        raise KeyError(decision_ref)


def attach_semantic_conflicts(
    projection: Mapping[str, object],
    proposal: AccountingProposalV2,
) -> AccountingProposalV2:
    conflicts: list[SemanticConflict] = []
    for item in _mapping_items(projection.get("vat_summary")):
        decision_ref = str(item.get("decision_ref") or "").strip()
        if not decision_ref:
            continue
        try:
            decision = proposal.decision_for(decision_ref)
        except KeyError:
            continue
        expected_rate = _normalized_semantic_rate(item.get("rate"))
        candidate_rates = decision.candidate.vat_rates if decision.candidate else ()
        if (
            decision.action == "select_existing"
            and expected_rate
            and candidate_rates
            and expected_rate not in candidate_rates
        ):
            conflicts.append(
                _semantic_conflict(
                    decision,
                    item,
                    conflict_code="vat_rate_semantic_conflict",
                    deterministic_expectation=expected_rate,
                    ai_selection_or_treatment=decision.selected_candidate_id,
                )
            )
    for item in _mapping_items(projection.get("tax_components")):
        decision_ref = str(item.get("decision_ref") or "").strip()
        if not decision_ref or decision_ref.startswith("vat:"):
            continue
        try:
            decision = proposal.decision_for(decision_ref)
        except KeyError:
            continue
        expectation = _tax_treatment_expectation(item)
        if (
            expectation
            and decision.selected_treatment
            and decision.selected_treatment != expectation
        ):
            conflicts.append(
                _semantic_conflict(
                    decision,
                    item,
                    conflict_code="tax_treatment_conflict",
                    deterministic_expectation=expectation,
                    ai_selection_or_treatment=decision.selected_treatment,
                )
            )
    for item in _mapping_items(projection.get("monetary_components")):
        decision_ref = str(item.get("decision_ref") or "").strip()
        if not decision_ref:
            continue
        try:
            decision = proposal.decision_for(decision_ref)
        except KeyError:
            continue
        expectation = _monetary_treatment_expectation(item)
        if (
            expectation
            and decision.selected_treatment
            and decision.selected_treatment != expectation
        ):
            conflicts.append(
                _semantic_conflict(
                    decision,
                    item,
                    conflict_code="monetary_effect_conflict",
                    deterministic_expectation=expectation,
                    ai_selection_or_treatment=decision.selected_treatment,
                )
            )
    return replace(proposal, semantic_conflicts=tuple(conflicts))


def required_decision_refs_for_projection(
    projection: Mapping[str, object],
) -> tuple[str, ...]:
    refs: list[str] = ["counterparty"]
    for section in ("line_items", "vat_summary", "tax_components", "monetary_components"):
        for item in _mapping_items(projection.get(section)):
            posting_requirement = str(item.get("posting_requirement") or "").strip().lower()
            if posting_requirement in {"represented", "excluded"}:
                continue
            treatment = str(item.get("accounting_treatment") or "").strip().lower()
            if not posting_requirement and treatment in {"informational", "exclude_current_period"}:
                continue
            decision_ref = str(item.get("decision_ref") or "").strip()
            if decision_ref and decision_ref not in refs:
                refs.append(decision_ref)
    return tuple(refs)


def parse_accounting_proposal(
    payload: Mapping[str, object],
    *,
    required_decision_refs: Sequence[str],
    sent_candidates: Mapping[str, AccountingCandidate],
    decision_ref_aliases: Mapping[str, str] | None = None,
    projection: Mapping[str, object] | None = None,
) -> AccountingProposalV2:
    result = parse_accounting_proposal_result(
        payload,
        required_decision_refs=required_decision_refs,
        sent_candidates=sent_candidates,
        decision_ref_aliases=decision_ref_aliases,
        projection=projection,
    )
    fatal_issues = tuple(
        issue for issue in result.issues if issue.code not in _NON_FATAL_ISSUE_CODES
    )
    if fatal_issues:
        issue = fatal_issues[0]
        if issue.code == "candidate_integrity_invalid":
            raise CandidateIntegrityError(issue.message)
        raise ValueError(issue.message)
    return result.to_proposal(
        required_decision_refs=_normalized_required_refs(required_decision_refs),
        sent_candidate_ids=tuple(
            candidate_id
            for candidate_id, candidate in sent_candidates.items()
            if candidate.active
        ),
    )


def parse_accounting_proposal_result(
    payload: Mapping[str, object],
    *,
    required_decision_refs: Sequence[str],
    sent_candidates: Mapping[str, AccountingCandidate],
    decision_ref_aliases: Mapping[str, str] | None = None,
    projection: Mapping[str, object] | None = None,
    round_index: int = 0,
    chunk_index: int = 0,
    receipt_artifact_id: str = "",
) -> AccountingProposalParseResult:
    required = _normalized_required_refs(required_decision_refs)
    aliases = decision_ref_aliases or {}
    canonical_posting_amounts = _canonical_posting_amounts(projection or {})
    issues: list[AccountingDecisionValidationIssue] = []
    valid_decisions: list[AccountingDecisionV2] = []

    raw_counterparty = payload.get("counterparty")
    try:
        counterparty = _parse_decision(
            "counterparty",
            raw_counterparty if isinstance(raw_counterparty, Mapping) else {},
            sent_candidates=sent_candidates,
            counterparty=True,
            canonical_posting_amount=None,
        )
        valid_decisions.append(counterparty)
    except (CandidateIntegrityError, TypeError, ValueError) as exc:
        issues.append(
            _validation_issue(
                "counterparty",
                exc,
                round_index=round_index,
                chunk_index=chunk_index,
                receipt_artifact_id=receipt_artifact_id,
            )
        )
        counterparty = AccountingDecisionV2(
            decision_ref="counterparty",
            action="unresolved",
            reason="no valid AI counterparty decision is available",
        )

    by_ref: dict[str, Mapping[str, object]] = {}
    for item in _mapping_items(payload.get("decisions")):
        decision_ref = _normalize_decision_ref(
            str(item.get("decision_ref") or "").strip(),
            required,
            aliases,
        )
        if not decision_ref or decision_ref == "counterparty" or decision_ref not in required:
            issues.append(
                _validation_issue_for_code(
                    decision_ref or "unknown",
                    "unexpected_ai_decision_ref",
                    "unexpected accounting decision ref",
                    round_index=round_index,
                    chunk_index=chunk_index,
                    receipt_artifact_id=receipt_artifact_id,
                )
            )
            continue
        if decision_ref in by_ref:
            issues.append(
                _validation_issue_for_code(
                    decision_ref,
                    "duplicate_ai_decision_ref",
                    "AI decision reference is duplicated in the provider response",
                    round_index=round_index,
                    chunk_index=chunk_index,
                    receipt_artifact_id=receipt_artifact_id,
                )
            )
            continue
        by_ref[decision_ref] = item

    for decision_ref in required:
        if decision_ref == "counterparty":
            continue
        raw_decision = by_ref.get(decision_ref)
        if raw_decision is None:
            issues.append(
                _validation_issue_for_code(
                    decision_ref,
                    "missing_ai_decision",
                    "AI decision is missing for the required reference",
                    round_index=round_index,
                    chunk_index=chunk_index,
                    receipt_artifact_id=receipt_artifact_id,
                )
            )
            continue
        try:
            decision, normalization_issues = _parse_fact_decision_result(
                decision_ref,
                raw_decision,
                sent_candidates=sent_candidates,
                canonical_posting_amount=canonical_posting_amounts.get(decision_ref),
                round_index=round_index,
                chunk_index=chunk_index,
                receipt_artifact_id=receipt_artifact_id,
            )
            valid_decisions.append(decision)
            issues.extend(normalization_issues)
        except (CandidateIntegrityError, TypeError, ValueError) as exc:
            issues.append(
                _validation_issue(
                    decision_ref,
                    exc,
                    round_index=round_index,
                    chunk_index=chunk_index,
                    receipt_artifact_id=receipt_artifact_id,
                )
            )

    try:
        sufficiency = _parse_sufficiency(payload.get("candidate_sufficiency"))
    except (TypeError, ValueError) as exc:
        issues.append(
            _validation_issue_for_code(
                "candidate_sufficiency",
                "candidate_sufficiency_invalid",
                "Candidate sufficiency state is invalid",
                round_index=round_index,
                chunk_index=chunk_index,
                receipt_artifact_id=receipt_artifact_id,
            )
        )
        sufficiency = _parse_sufficiency({})
    return AccountingProposalParseResult(
        counterparty=counterparty,
        valid_decisions=tuple(valid_decisions),
        issues=tuple(issues),
        sufficiency=sufficiency,
    )


def _parse_fact_decision_result(
    decision_ref: str,
    payload: Mapping[str, object],
    *,
    sent_candidates: Mapping[str, AccountingCandidate],
    canonical_posting_amount: Decimal | None,
    round_index: int,
    chunk_index: int,
    receipt_artifact_id: str,
) -> tuple[AccountingDecisionV2, tuple[AccountingDecisionValidationIssue, ...]]:
    normalized_payload = dict(payload)
    raw_treatment = str(payload.get("selected_treatment") or "").strip().lower()
    issues: list[AccountingDecisionValidationIssue] = []

    if decision_ref.startswith(("line:", "vat:")) and raw_treatment:
        normalized_payload["selected_treatment"] = ""
        issues.append(
            _validation_issue_for_code(
                decision_ref,
                "nonoperative_treatment_ignored",
                "Line and VAT selected_treatment is non-operative and was ignored",
                round_index=round_index,
                chunk_index=chunk_index,
                receipt_artifact_id=receipt_artifact_id,
            )
        )

    zero_posting_selection = (
        canonical_posting_amount == Decimal("0")
        and decision_ref.startswith(("vat:", "tax:", "monetary:"))
        and str(payload.get("action") or "unresolved").strip().lower()
        == "select_existing"
        and bool(str(payload.get("selected_candidate_id") or "").strip())
    )
    if zero_posting_selection:
        candidate_id = str(payload.get("selected_candidate_id") or "").strip()
        candidate = sent_candidates.get(candidate_id)
        if candidate is None:
            raise CandidateIntegrityError(
                f"candidate was not sent to the accounting AI: {candidate_id!r}"
            )
        if not candidate.active:
            raise CandidateIntegrityError(f"candidate is inactive: {candidate_id!r}")
        normalized_payload.update(
            {
                "action": "no_separate_posting",
                "selected_candidate_id": "",
                "selected_treatment": (
                    "no_separate_posting"
                    if decision_ref.startswith(("tax:", "monetary:"))
                    else ""
                ),
            }
        )
        issues.append(
            _validation_issue_for_code(
                decision_ref,
                "zero_fact_normalized_to_no_separate_posting",
                "A posting-shaped zero fact was normalized to no_separate_posting",
                round_index=round_index,
                chunk_index=chunk_index,
                receipt_artifact_id=receipt_artifact_id,
            )
        )

    treatment_review_required = (
        canonical_posting_amount not in {None, Decimal("0")}
        and decision_ref.startswith(("tax:", "monetary:"))
        and str(payload.get("action") or "unresolved").strip().lower()
        == "select_existing"
        and not _is_valid_posting_treatment(decision_ref, raw_treatment)
    )
    if treatment_review_required:
        normalized_payload["selected_treatment"] = ""

    decision = _parse_decision(
        decision_ref,
        normalized_payload,
        sent_candidates=sent_candidates,
        counterparty=False,
        canonical_posting_amount=canonical_posting_amount,
    )
    if treatment_review_required:
        decision = replace(decision, treatment_review_required=True)
        issues.append(
            _validation_issue_for_code(
                decision_ref,
                "treatment_clarification_required",
                "A valid suggested account was retained but treatment/topology requires review",
                round_index=round_index,
                chunk_index=chunk_index,
                receipt_artifact_id=receipt_artifact_id,
            )
        )
    return decision, tuple(issues)


def _normalized_required_refs(values: Sequence[str]) -> tuple[str, ...]:
    required = tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )
    return required if "counterparty" in required else ("counterparty", *required)


def _parse_sufficiency(value: object) -> dict[str, object]:
    sufficiency = value if isinstance(value, Mapping) else {}
    candidate_sufficient = _strict_bool(sufficiency, "sufficient")
    request_more_candidates = _strict_bool(sufficiency, "request_more_candidates")
    provisional = _strict_bool(sufficiency, "provisional")
    if candidate_sufficient and (request_more_candidates or provisional):
        raise ValueError("candidate sufficiency state is contradictory")
    if request_more_candidates and not provisional:
        raise ValueError("candidate expansion request requires a provisional proposal")
    raw_terms = sufficiency.get("search_terms", ())
    search_terms = (
        tuple(str(term).strip() for term in raw_terms if str(term).strip())
        if isinstance(raw_terms, Sequence) and not isinstance(raw_terms, (str, bytes))
        else ()
    )
    return {
        "sufficient": candidate_sufficient,
        "request_more_candidates": request_more_candidates,
        "search_terms": search_terms,
        "reason": str(sufficiency.get("reason") or "").strip(),
        "provisional": provisional,
    }


def _validation_issue(
    decision_ref: str,
    exc: Exception,
    *,
    round_index: int,
    chunk_index: int,
    receipt_artifact_id: str,
) -> AccountingDecisionValidationIssue:
    if isinstance(exc, CandidateIntegrityError):
        code = "candidate_integrity_invalid"
        message = "Selected candidate failed sent-candidate integrity validation"
    else:
        code = "ai_decision_validation_invalid"
        message = "AI decision failed the accounting proposal contract"
    return _validation_issue_for_code(
        decision_ref,
        code,
        message,
        round_index=round_index,
        chunk_index=chunk_index,
        receipt_artifact_id=receipt_artifact_id,
    )


def _validation_issue_for_code(
    decision_ref: str,
    code: str,
    message: str,
    *,
    round_index: int,
    chunk_index: int,
    receipt_artifact_id: str,
) -> AccountingDecisionValidationIssue:
    return AccountingDecisionValidationIssue(
        decision_ref=decision_ref,
        code=code,
        message=message,
        round_index=round_index,
        chunk_index=chunk_index,
        receipt_artifact_id=receipt_artifact_id,
    )


def _normalize_decision_ref(
    value: str,
    required: Sequence[str],
    aliases: Mapping[str, str],
) -> str:
    if value in required or ":" not in value:
        return value
    declared_alias = str(aliases.get(value) or "").strip()
    if declared_alias in required:
        return declared_alias
    namespace = value.split(":", 1)[0]
    duplicate_prefix = f"{namespace}:{namespace}:"
    if value.startswith(duplicate_prefix):
        normalized = value[len(namespace) + 1 :]
        if normalized in required:
            return normalized
    return value


def _parse_decision(
    decision_ref: str,
    payload: Mapping[str, object],
    *,
    sent_candidates: Mapping[str, AccountingCandidate],
    counterparty: bool,
    canonical_posting_amount: Decimal | None,
) -> AccountingDecisionV2:
    action = str(payload.get("action") or "unresolved").strip().lower()
    allowed = {
        "select_existing",
        "unresolved",
        *(("propose_new",) if counterparty else ("represented", "excluded", "no_separate_posting")),
    }
    if action not in allowed:
        raise ValueError(f"invalid action for {decision_ref}: {action!r}")
    candidate_id = str(payload.get("selected_candidate_id") or "").strip()
    selected_treatment = str(payload.get("selected_treatment") or "").strip().lower()
    if counterparty and selected_treatment:
        raise ValueError("counterparty decision cannot carry selected_treatment")
    if not counterparty:
        selected_treatment = _validated_fact_treatment(
            decision_ref,
            action,
            selected_treatment,
        )
    if (
        not counterparty
        and action == "select_existing"
        and not candidate_id
        and canonical_posting_amount == Decimal("0")
        and decision_ref.startswith(("vat:", "tax:", "monetary:"))
    ):
        action = "no_separate_posting"
        selected_treatment = (
            "no_separate_posting"
            if decision_ref.startswith(("tax:", "monetary:"))
            else ""
        )
    candidate: AccountingCandidate | None = None
    if action == "select_existing":
        candidate = sent_candidates.get(candidate_id)
        if candidate is None:
            raise CandidateIntegrityError(
                f"candidate was not sent to the accounting AI: {candidate_id!r}"
            )
        if not candidate.active:
            raise CandidateIntegrityError(f"candidate is inactive: {candidate_id!r}")
    else:
        if candidate_id:
            raise ValueError(
                f"{action} decision cannot carry selected_candidate_id"
            )
        candidate_id = ""
    if action == "no_separate_posting":
        if canonical_posting_amount != Decimal("0"):
            raise ValueError(
                f"no_separate_posting requires an exactly zero canonical posting amount for {decision_ref}"
            )
    elif action in {"represented", "excluded"}:
        if canonical_posting_amount in {None, Decimal("0")}:
            raise ValueError(f"{action} requires a non-zero canonical posting amount for {decision_ref}")
        if not str(payload.get("reason") or "").strip():
            raise ValueError(f"{action} requires explicit evidence in reason for {decision_ref}")
    proposal = payload.get("proposal")
    has_proposal = "proposal" in payload
    proposal_value = dict(proposal) if isinstance(proposal, Mapping) else {}
    if action == "propose_new":
        required_proposal_fields = {
            "party_title",
            "tax_id",
            "direction",
            "suggested_parent_family",
        }
        if set(proposal_value) != required_proposal_fields or any(
            not isinstance(proposal_value.get(key), str)
            or not proposal_value[key].strip()
            for key in required_proposal_fields
        ):
            raise ValueError("propose_new requires the exact nonempty proposal shape")
        if str(proposal_value["direction"]).strip().lower() not in {
            "supplier",
            "customer",
        }:
            raise ValueError("propose_new direction must be supplier or customer")
    elif counterparty:
        if has_proposal and proposal is not None:
            raise ValueError(f"{action} counterparty cannot carry a proposal")
        proposal_value = {}
    elif has_proposal:
        raise ValueError("accounting decisions cannot carry a proposal")
    return AccountingDecisionV2(
        decision_ref=decision_ref,
        action=action,
        selected_candidate_id=candidate_id,
        candidate=candidate,
        reason=str(payload.get("reason") or "").strip(),
        selected_treatment=selected_treatment,
        proposal=proposal_value,
    )


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _proposal_output_schema(
    required_decision_refs: Sequence[str],
    sent_candidate_ids: Sequence[str],
    projection: Mapping[str, object],
) -> dict[str, object]:
    decision_refs = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in required_decision_refs
            if str(value).strip() and str(value).strip() != "counterparty"
        )
    )
    canonical_posting_amounts = _canonical_posting_amounts(projection)
    selection = {
        "type": "object",
        "required": ["decision_ref", "action", "selected_candidate_id", "selected_treatment", "reason"],
        "properties": {
            "decision_ref": {"type": "string", "enum": list(decision_refs)},
            "action": {
                "type": "string",
                "enum": [
                    "select_existing",
                    "represented",
                    "excluded",
                    "no_separate_posting",
                    "unresolved",
                ],
            },
            "selected_candidate_id": {
                "type": "string",
                "enum": ["", *sent_candidate_ids],
            },
            "selected_treatment": {
                "type": "string",
                "enum": [
                    "",
                    *_TAX_TREATMENTS,
                    *_MONETARY_TREATMENTS,
                ],
            },
            "reason": {"type": "string"},
        },
        "anyOf": [
            variant
            for decision_ref in decision_refs
            for variant in _decision_schema_variants(
                decision_ref,
                canonical_posting_amounts.get(decision_ref),
            )
        ],
        "additionalProperties": False,
    }
    new_counterparty_schema = {
        "type": "object",
        "required": [
            "party_title",
            "tax_id",
            "direction",
            "suggested_parent_family",
        ],
        "properties": {
            "party_title": {"type": "string", "minLength": 1},
            "tax_id": {"type": "string", "minLength": 1},
            "direction": {
                "type": "string",
                "enum": ["supplier", "customer"],
            },
            "suggested_parent_family": {
                "type": "string",
                "minLength": 1,
            },
        },
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "required": ["counterparty", "decisions", "candidate_sufficiency"],
        "properties": {
            "counterparty": {
                "type": "object",
                "required": ["action", "selected_candidate_id", "reason", "proposal"],
                "properties": {
                    "action": {"type": "string", "enum": ["select_existing", "propose_new", "unresolved"]},
                    "selected_candidate_id": {
                        "type": "string",
                        "enum": ["", *sent_candidate_ids],
                    },
                    "reason": {"type": "string"},
                    "proposal": {
                        "anyOf": [{"type": "null"}, new_counterparty_schema],
                    },
                },
                "anyOf": [
                    {
                        "properties": {
                            "action": {"enum": ["select_existing"]},
                            "selected_candidate_id": {
                                "enum": list(sent_candidate_ids),
                            },
                            "proposal": {"type": "null"},
                        }
                    },
                    {
                        "properties": {
                            "action": {"enum": ["unresolved"]},
                            "selected_candidate_id": {"enum": [""]},
                            "proposal": {"type": "null"},
                        }
                    },
                    {
                        "properties": {
                            "action": {"enum": ["propose_new"]},
                            "selected_candidate_id": {"enum": [""]},
                            "proposal": new_counterparty_schema,
                        }
                    },
                ],
                "additionalProperties": False,
            },
            "decisions": {
                "type": "array",
                "items": selection,
                "minItems": len(decision_refs),
                "maxItems": len(decision_refs),
            },
            "candidate_sufficiency": {
                "type": "object",
                "required": ["sufficient", "request_more_candidates", "search_terms", "reason", "provisional"],
                "properties": {
                    "sufficient": {"type": "boolean"},
                    "request_more_candidates": {"type": "boolean"},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "provisional": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def _strict_bool(payload: Mapping[str, object], key: str) -> bool:
    if key not in payload:
        return False
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"candidate_sufficiency.{key} must be boolean")
    return value


def _safe_context_value(value: object) -> bool:
    if isinstance(value, (str, int, float, bool)):
        return True
    return isinstance(value, (list, tuple)) and all(
        isinstance(item, (str, int, float, bool)) for item in value
    )


_TAX_TREATMENTS = (
    "deductible_tax",
    "expense_or_cost",
    "payable_withholding",
    "represented_in_line",
    "no_separate_posting",
    "other",
)
_MONETARY_TREATMENTS = (
    "increase_payable",
    "reduce_payable",
    "represented",
    "excluded",
    "no_separate_posting",
    "other",
)
_NON_FATAL_ISSUE_CODES = {
    "missing_ai_decision",
    "nonoperative_treatment_ignored",
    "treatment_clarification_required",
    "zero_fact_normalized_to_no_separate_posting",
}


def _is_valid_posting_treatment(decision_ref: str, selected_treatment: str) -> bool:
    if decision_ref.startswith("tax:"):
        allowed = _TAX_TREATMENTS
        non_posting = {"represented_in_line", "no_separate_posting"}
    else:
        allowed = _MONETARY_TREATMENTS
        non_posting = {"represented", "excluded", "no_separate_posting"}
    return (
        bool(selected_treatment)
        and selected_treatment in allowed
        and selected_treatment != "other"
        and selected_treatment not in non_posting
    )


def _validated_fact_treatment(
    decision_ref: str,
    action: str,
    selected_treatment: str,
) -> str:
    if action == "excluded" and not decision_ref.startswith("monetary:"):
        raise ValueError(f"excluded is only valid for monetary facts: {decision_ref}")
    if action == "no_separate_posting" and not decision_ref.startswith(
        ("vat:", "tax:", "monetary:")
    ):
        raise ValueError(
            "no_separate_posting is only valid for VAT, tax, and monetary facts: "
            f"{decision_ref}"
        )
    if decision_ref.startswith("tax:"):
        allowed = _TAX_TREATMENTS
        required_by_action = {
            "represented": "represented_in_line",
            "no_separate_posting": "no_separate_posting",
        }
    elif decision_ref.startswith("monetary:"):
        allowed = _MONETARY_TREATMENTS
        required_by_action = {
            "represented": "represented",
            "excluded": "excluded",
            "no_separate_posting": "no_separate_posting",
        }
    else:
        if selected_treatment:
            raise ValueError(f"{decision_ref} cannot carry selected_treatment")
        return ""
    if selected_treatment and selected_treatment not in allowed:
        raise ValueError(
            f"invalid selected_treatment for {decision_ref}: {selected_treatment!r}"
        )
    required = required_by_action.get(action)
    if required and selected_treatment != required:
        raise ValueError(
            f"{action} for {decision_ref} requires selected_treatment={required!r}"
        )
    if action == "select_existing" and selected_treatment in {
        "represented_in_line",
        "represented",
        "excluded",
        "no_separate_posting",
    }:
        raise ValueError(
            f"select_existing cannot use non-posting treatment for {decision_ref}"
        )
    return selected_treatment


def _canonical_posting_amounts(
    projection: Mapping[str, object],
) -> dict[str, Decimal | None]:
    amounts: dict[str, Decimal | None] = {}
    for section, fields in (
        ("line_items", ("posting_amount", "taxable_amount")),
        ("vat_summary", ("tax_amount",)),
        ("tax_components", ("tax_amount",)),
        ("monetary_components", ("source_amount",)),
    ):
        for item in _mapping_items(projection.get(section)):
            decision_ref = str(item.get("decision_ref") or "").strip()
            if not decision_ref:
                continue
            raw_amount = next(
                (
                    item.get(field_name)
                    for field_name in fields
                    if item.get(field_name) not in (None, "")
                ),
                None,
            )
            amount = _canonical_decimal(raw_amount)
            if decision_ref not in amounts:
                amounts[decision_ref] = amount
            elif amounts[decision_ref] != amount:
                amounts[decision_ref] = None
    return amounts


def _canonical_decimal(value: object) -> Decimal | None:
    raw = str(value if value is not None else "").strip().replace(" ", "")
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return abs(amount) if amount.is_finite() else None


def _decision_schema_variants(
    decision_ref: str,
    canonical_posting_amount: Decimal | None,
) -> tuple[dict[str, object], ...]:
    base = {"decision_ref": {"enum": [decision_ref]}}
    if (
        canonical_posting_amount == Decimal("0")
        and decision_ref.startswith(("vat:", "tax:", "monetary:"))
    ):
        return (
            _schema_variant(
                base,
                "no_separate_posting",
                "no_separate_posting"
                if decision_ref.startswith(("tax:", "monetary:"))
                else "",
            ),
        )
    if decision_ref.startswith("tax:"):
        posting_treatments = [
            "deductible_tax",
            "expense_or_cost",
            "payable_withholding",
        ]
        nonposting = [
            _schema_variant(base, "represented", "represented_in_line"),
        ]
    elif decision_ref.startswith("monetary:"):
        posting_treatments = ["increase_payable", "reduce_payable"]
        nonposting = [
            _schema_variant(base, "represented", "represented"),
            _schema_variant(base, "excluded", "excluded"),
        ]
    else:
        posting_treatments = [""]
        nonposting = [_schema_variant(base, "represented", "")]
    variants = [
        {
            "properties": {
                **base,
                "action": {"enum": ["select_existing"]},
                "selected_treatment": {"enum": posting_treatments},
            }
        },
        {
            "properties": {
                **base,
                "action": {"enum": ["unresolved"]},
                "selected_candidate_id": {"enum": [""]},
                "selected_treatment": {
                    "enum": list(
                        _TAX_TREATMENTS
                        if decision_ref.startswith("tax:")
                        else _MONETARY_TREATMENTS
                        if decision_ref.startswith("monetary:")
                        else ("",)
                    )
                },
            }
        },
        *nonposting,
    ]
    return tuple(variants)


def _schema_variant(
    base: Mapping[str, object],
    action: str,
    selected_treatment: str,
) -> dict[str, object]:
    return {
        "properties": {
            **base,
            "action": {"enum": [action]},
            "selected_candidate_id": {"enum": [""]},
            "selected_treatment": {"enum": [selected_treatment]},
        }
    }


def _semantic_conflict(
    decision: AccountingDecisionV2,
    item: Mapping[str, object],
    *,
    conflict_code: str,
    deterministic_expectation: str,
    ai_selection_or_treatment: str,
) -> SemanticConflict:
    raw_evidence = item.get("source_evidence_refs") or ()
    source_evidence_refs = (
        tuple(str(value).strip() for value in raw_evidence if str(value).strip())
        if isinstance(raw_evidence, Sequence)
        and not isinstance(raw_evidence, (str, bytes))
        else ()
    )
    return SemanticConflict(
        decision_ref=decision.decision_ref,
        conflict_code=conflict_code,
        deterministic_expectation=deterministic_expectation,
        ai_selection_or_treatment=ai_selection_or_treatment,
        ai_reason=decision.reason,
        candidate_round_index=(
            decision.candidate.origin_round if decision.candidate is not None else 0
        ),
        candidate_id=decision.selected_candidate_id,
        source_evidence_refs=source_evidence_refs,
    )


def _tax_treatment_expectation(item: Mapping[str, object]) -> str:
    explicit = str(item.get("accounting_treatment") or "").strip().lower()
    if explicit in _TAX_TREATMENTS:
        return explicit
    posting_requirement = str(item.get("posting_requirement") or "").strip().lower()
    if posting_requirement == "represented":
        return "represented_in_line"
    amount = _canonical_decimal(item.get("tax_amount"))
    if amount == Decimal("0"):
        return "no_separate_posting"
    kind = str(item.get("canonical_tax_kind") or item.get("component_type") or "").strip().lower()
    effect = str(item.get("economic_effect") or "").strip().lower()
    if "withholding" in kind or effect in {"reduce_payable", "decrease_payable"}:
        return "payable_withholding"
    return ""


def _monetary_treatment_expectation(item: Mapping[str, object]) -> str:
    posting_requirement = str(item.get("posting_requirement") or "").strip().lower()
    if posting_requirement == "represented":
        return "represented"
    if posting_requirement == "excluded":
        return "excluded"
    explicit = str(item.get("accounting_treatment") or "").strip().lower()
    if explicit in {"represented", "excluded", "no_separate_posting"}:
        return explicit
    effect = str(
        item.get("reconciled_effect")
        or item.get("signed_effect")
        or ""
    ).strip().lower()
    if effect in {"increase_tax", "increase_payable"}:
        return "increase_payable"
    if effect in {"reduce_payable", "decrease_payable"}:
        return "reduce_payable"
    return ""


def _normalized_semantic_rate(value: object) -> str:
    raw = str(value or "").strip().replace("%", "").replace(",", ".")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError):
        return ""
    if not parsed.is_finite() or parsed < 0:
        return ""
    return format(parsed.normalize(), "f")
