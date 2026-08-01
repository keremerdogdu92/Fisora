from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Literal, Mapping
import unicodedata

from app.domain.invoice_ai_gate import VerifiedRuleAuthorityV1


RuleScope = Literal["client_counterparty", "client_service_profile", "client_phrase", "office_semantic"]
RuleDirection = Literal["purchase", "sales"]
InvoiceMode = Literal["ordinary", "return"]
LineMatchMode = Literal["all_lines", "normalized_terms_all"]


class LearningRuleConflict(RuntimeError):
    """Raised when a version mutation races with a newer lifecycle version."""


@dataclass(frozen=True)
class VerifiedRuleRecordV1:
    rule_id: str
    rule_key: str
    version: int
    status: Literal["active"]
    client_id: str
    scope: RuleScope
    direction: RuleDirection
    invoice_mode: InvoiceMode
    counterparty_tax_id: str
    service_profile: str
    line_match_mode: LineMatchMode
    normalized_terms: tuple[str, ...]
    semantic_role: str
    account_code: str
    activation_event_id: str
    source_review_decision_id: str
    confirmed_actor_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VerifiedRuleRecordV1":
        return cls(
            rule_id=str(value.get("rule_id") or value.get("id") or ""),
            rule_key=str(value.get("rule_key") or ""),
            version=int(value.get("version") or 0),
            status=str(value.get("status") or "draft"),  # type: ignore[arg-type]
            client_id=str(value.get("client_id") or ""),
            scope=str(value.get("scope") or ""),  # type: ignore[arg-type]
            direction=str(value.get("direction") or ""),  # type: ignore[arg-type]
            invoice_mode=str(value.get("invoice_mode") or ""),  # type: ignore[arg-type]
            counterparty_tax_id=_digits(value.get("counterparty_tax_id")),
            service_profile=str(value.get("service_profile") or "").strip(),
            line_match_mode=str(value.get("line_match_mode") or "all_lines"),  # type: ignore[arg-type]
            normalized_terms=tuple(_normalize_text(term) for term in value.get("normalized_terms") or () if _normalize_text(term)),
            semantic_role=str(value.get("semantic_role") or ""),
            account_code=_account_code(value.get("account_code")),
            activation_event_id=str(value.get("activation_event_id") or ""),
            source_review_decision_id=str(value.get("source_review_decision_id") or ""),
            confirmed_actor_id=str(value.get("confirmed_actor_id") or value.get("confirmed_by") or ""),
        )


class CompiledVerifiedRuleAuthorities(tuple[VerifiedRuleAuthorityV1, ...]):
    """Tuple-compatible authority result carrying non-silent conflicts."""

    def __new__(
        cls,
        authorities: Iterable[VerifiedRuleAuthorityV1] = (),
        *,
        conflicts: Iterable[Mapping[str, Any]] = (),
    ) -> "CompiledVerifiedRuleAuthorities":
        result = super().__new__(cls, tuple(authorities))
        result.conflicts = tuple(dict(item) for item in conflicts)  # type: ignore[attr-defined]
        return result

    @property
    def authorities(self) -> tuple[VerifiedRuleAuthorityV1, ...]:
        return tuple(self)


def compile_verified_rule_authorities(
    *,
    rules: Iterable[VerifiedRuleRecordV1 | Mapping[str, Any]],
    client_id: str,
    direction: RuleDirection,
    invoice_mode: InvoiceMode,
    counterparty_tax_id: str,
    service_profile: str = "",
    canonical_lines: Iterable[Any],
    account_selection: Any,
) -> CompiledVerifiedRuleAuthorities:
    """Compile only fully evidenced, active rules into line-scoped capabilities."""

    lines = tuple(_line_mapping(line) for line in canonical_lines)
    line_ids = tuple(str(line.get("canonical_line_id") or line.get("id") or "").strip() for line in lines)
    if not lines or any(not line_id for line_id in line_ids) or len(set(line_ids)) != len(line_ids):
        return CompiledVerifiedRuleAuthorities()

    normalized_vkn = _digits(counterparty_tax_id)
    candidates: list[tuple[int, VerifiedRuleRecordV1, tuple[str, ...]]] = []
    for raw_rule in rules:
        rule = raw_rule if isinstance(raw_rule, VerifiedRuleRecordV1) else VerifiedRuleRecordV1.from_mapping(raw_rule)
        if not _rule_matches(rule, client_id, direction, invoice_mode, normalized_vkn, service_profile, lines):
            continue
        if not _chart_account_is_valid(rule, direction, account_selection):
            continue
        candidates.append((_priority(rule.scope), rule, line_ids))

    authorities: list[VerifiedRuleAuthorityV1] = []
    conflicts: list[Mapping[str, Any]] = []
    for line_id in line_ids:
        applicable = [item for item in candidates if line_id in item[2]]
        if not applicable:
            continue
        highest = max(item[0] for item in applicable)
        winners = [item[1] for item in applicable if item[0] == highest]
        account_codes = {rule.account_code for rule in winners}
        if len(account_codes) > 1:
            conflicts.append(
                {
                    "reason": "verified_rule_conflict",
                    "canonical_line_id": line_id,
                    "rule_ids": tuple(rule.rule_id for rule in winners),
                    "account_codes": tuple(sorted(account_codes)),
                }
            )
            continue
        rule = sorted(winners, key=lambda item: (item.rule_id, item.version))[0]
        authorities.append(
            VerifiedRuleAuthorityV1(
                schema_version="v1",
                client_id=rule.client_id,
                rule_id=rule.rule_id,
                rule_version=str(rule.version),
                activation_event_id=rule.activation_event_id,
                source_review_decision_id=rule.source_review_decision_id,
                confirmed_actor_id=rule.confirmed_actor_id,
                canonical_line_id=line_id,
                direction=rule.direction,
                invoice_mode=rule.invoice_mode,
                semantic_role=rule.semantic_role,
                account_code=rule.account_code,
            )
        )
    return CompiledVerifiedRuleAuthorities(authorities, conflicts=conflicts)


def _rule_matches(
    rule: VerifiedRuleRecordV1,
    client_id: str,
    direction: str,
    invoice_mode: str,
    counterparty_tax_id: str,
    service_profile: str,
    lines: tuple[dict[str, Any], ...],
) -> bool:
    if rule.status != "active" or rule.version < 1 or not rule.rule_id or not rule.rule_key:
        return False
    if rule.client_id != str(client_id) or rule.direction != direction or rule.invoice_mode != invoice_mode:
        return False
    if not rule.activation_event_id or not rule.source_review_decision_id or not rule.confirmed_actor_id:
        return False
    if rule.scope == "client_counterparty" and (not rule.counterparty_tax_id or rule.counterparty_tax_id != counterparty_tax_id):
        return False
    if rule.scope == "client_service_profile" and (
        not rule.service_profile or rule.service_profile != str(service_profile or "").strip()
    ):
        return False
    if rule.scope not in {"client_counterparty", "client_service_profile", "client_phrase", "office_semantic"}:
        return False
    if rule.line_match_mode == "all_lines":
        return True
    if rule.line_match_mode != "normalized_terms_all" or not rule.normalized_terms:
        return False
    haystack = _normalize_text(" ".join(_line_text(line) for line in lines))
    return all(term in haystack for term in rule.normalized_terms)


def _chart_account_is_valid(rule: VerifiedRuleRecordV1, direction: str, account_selection: Any) -> bool:
    code = _account_code(rule.account_code)
    if not code:
        return False
    candidates_by_family = getattr(account_selection, "account_candidates", None)
    if not isinstance(candidates_by_family, Mapping):
        return False
    role = _normalize_text(rule.semantic_role)
    for family, family_candidates in candidates_by_family.items():
        family_text = _normalize_text(family)
        if not isinstance(family_candidates, Iterable) or isinstance(family_candidates, (str, bytes, Mapping)):
            continue
        for raw_candidate in family_candidates:
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate_code = _account_code(
                raw_candidate.get("normalized_account_code")
                or raw_candidate.get("account_code")
                or raw_candidate.get("code")
                or raw_candidate.get("raw_account_code")
            )
            if candidate_code != code:
                continue
            if raw_candidate.get("is_active") is not True or raw_candidate.get("is_detail_account") is not True:
                return False
            candidate_direction = str(raw_candidate.get("direction") or raw_candidate.get("accounting_direction") or "").strip()
            if candidate_direction and candidate_direction != direction:
                return False
            if not candidate_direction and direction not in family_text and "purchase" not in family_text and "sales" not in family_text:
                return False
            raw_roles = raw_candidate.get("semantic_roles") or raw_candidate.get("semantic_role") or ()
            if isinstance(raw_roles, str):
                raw_roles = (raw_roles,)
            if raw_roles and role not in {_normalize_text(item) for item in raw_roles}:
                return False
            if not raw_roles and role not in family_text:
                return False
            return True
    return False


def _line_mapping(line: Any) -> dict[str, Any]:
    if isinstance(line, Mapping):
        return dict(line)
    return {
        "canonical_line_id": getattr(line, "canonical_line_id", getattr(line, "id", "")),
        "description": getattr(line, "description", getattr(line, "original_description", "")),
    }


def _line_text(line: Mapping[str, Any]) -> str:
    return " ".join(
        str(line.get(key) or "")
        for key in ("description", "original_description", "name", "text", "normalized_text")
    )


def _priority(scope: str) -> int:
    return {"client_counterparty": 300, "client_service_profile": 200, "client_phrase": 100, "office_semantic": 50}.get(scope, 0)


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _account_code(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "")).lower()
    return "".join(ch for ch in raw if not unicodedata.combining(ch) and (ch.isalnum() or ch.isspace())).strip()
