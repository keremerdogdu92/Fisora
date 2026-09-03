# File: backend/app/services/learning_rule_service.py
# Summary: Manages versioned accountant-confirmed learning rules and safely converts explicit review confirmations into narrow active authorities.
from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

from app.persistence.learning_rule_repository import LearningRuleRepository


class LearningRuleService:
    def __init__(self, *, repository: LearningRuleRepository) -> None:
        self.repository = repository

    def create_version(
        self,
        *,
        rule_key: str,
        expected_version: int,
        snapshot: Mapping[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        provenance = snapshot.get("confirmation_provenance")
        if not isinstance(provenance, Mapping) or provenance.get("source") != "accountant_confirmed":
            raise ValueError("learning_rule_confirmation_required")
        if not str(snapshot.get("source_review_decision_id") or "").strip():
            raise ValueError("learning_rule_confirmation_required")
        return self.repository.create_version(
            rule_key=rule_key,
            expected_version=expected_version,
            snapshot=snapshot,
            actor=actor,
        )

    def activate(self, *, rule_key: str, expected_version: int, actor: str) -> dict[str, Any]:
        return self.repository.transition(rule_key=rule_key, expected_version=expected_version, status="active", actor=actor)

    def pause(self, *, rule_key: str, expected_version: int, actor: str) -> dict[str, Any]:
        return self.repository.transition(rule_key=rule_key, expected_version=expected_version, status="paused", actor=actor)

    def archive(self, *, rule_key: str, expected_version: int, actor: str) -> dict[str, Any]:
        return self.repository.transition(rule_key=rule_key, expected_version=expected_version, status="archived", actor=actor)

    def list_active(self, *, client_id: str | None = None, rule_key: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_active(client_id=client_id, rule_key=rule_key)

    def list_versions(self, rule_key: str) -> list[dict[str, Any]]:
        return self.repository.list_versions(rule_key)

    def save_confirmed_review_rule(
        self,
        *,
        client_id: str,
        decision: Mapping[str, Any],
        learning_event: Mapping[str, Any],
        interpretation: Mapping[str, Any] | None,
        saved_review: Mapping[str, Any],
        document: Mapping[str, Any] | None,
        chart_accounts: Mapping[str, Any] | None,
        actor: str,
    ) -> dict[str, Any] | None:
        if str(decision.get("learning_confirmation") or "").strip() != "save_rule":
            return None
        if not isinstance(interpretation, Mapping) or str(interpretation.get("status") or "") != "ready":
            raise ValueError("learning_rule_interpretation_not_ready")
        candidate = learning_event.get("natural_language_rule_candidate")
        if not isinstance(candidate, Mapping) or not candidate:
            raise ValueError("learning_rule_candidate_required")

        result = document.get("result") if isinstance(document, Mapping) else {}
        result = result if isinstance(result, Mapping) else {}
        direction = str(result.get("accounting_direction") or "").strip()
        if direction not in {"purchase", "sales"}:
            raise ValueError("learning_rule_direction_unresolved")
        account_code = _account_code(
            decision.get("corrected_account_code")
            or learning_event.get("corrected_account_code")
            or learning_event.get("selected_account_code")
        )
        account = _selectable_detail_account(account_code, chart_accounts)
        if account is None:
            raise ValueError("learning_rule_account_not_selectable")
        normalized_review = saved_review.get("normalized_review")
        normalized_review = normalized_review if isinstance(normalized_review, Mapping) else {}
        saved_review_id = str(normalized_review.get("review_decision_id") or saved_review.get("id") or "").strip()
        if not saved_review_id:
            raise ValueError("learning_rule_source_review_required")

        scope_data = _narrow_scope(candidate=candidate, learning_event=learning_event)
        semantic_role = _semantic_role(direction=direction, account_code=account_code, account=account, candidate=candidate)
        if not semantic_role:
            raise ValueError("learning_rule_semantic_role_unresolved")
        invoice_mode = "return" if bool(result.get("is_return_invoice")) else "ordinary"
        rule_key = _rule_key(
            client_id=client_id,
            direction=direction,
            scope=str(scope_data["scope"]),
            qualifier=str(scope_data["qualifier"]),
        )
        snapshot = {
            "client_id": client_id,
            "scope": scope_data["scope"],
            "direction": direction,
            "invoice_mode": invoice_mode,
            "counterparty_tax_id": scope_data["counterparty_tax_id"],
            "service_profile": scope_data["service_profile"],
            "line_match_mode": scope_data["line_match_mode"],
            "normalized_terms": scope_data["normalized_terms"],
            "semantic_role": semantic_role,
            "account_code": account_code,
            "corrected_counterparty_code": str(learning_event.get("corrected_counterparty_code") or "").strip(),
            "category": str(learning_event.get("category") or "").strip(),
            "document_ref": str(decision.get("document_ref") or "").strip(),
            "source_document_label": str(result.get("file_name") or decision.get("document_ref") or "").strip(),
            "meaning_label": str(interpretation.get("summary_tr") or "").strip(),
            "guardrail_tr": str(interpretation.get("guardrail_tr") or "").strip(),
            "reason": str(decision.get("decision_note") or decision.get("reason") or "").strip(),
            "activation_event_id": saved_review_id,
            "source_review_decision_id": saved_review_id,
            "confirmed_actor_id": str(actor or "").strip(),
            "confirmation_provenance": {
                "source": "accountant_confirmed",
                "learning_confirmation": "save_rule",
                "interpretation_source": str(interpretation.get("source") or "").strip(),
            },
        }
        versions = self.list_versions(rule_key)
        current = versions[-1] if versions else None
        if current and _same_authority(current, snapshot):
            if str(current.get("status") or "") == "active":
                return {**current, "already_active": True}
            if str(current.get("status") or "") == "draft":
                return self.activate(rule_key=rule_key, expected_version=int(current["version"]), actor=actor)

        expected_version = int(current.get("version") or 0) if current else 0
        created = self.create_version(
            rule_key=rule_key,
            expected_version=expected_version,
            snapshot=snapshot,
            actor=actor,
        )
        return self.activate(
            rule_key=rule_key,
            expected_version=int(created["version"]),
            actor=actor,
        )


def _selectable_detail_account(code: str, chart_accounts: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    accounts = chart_accounts.get("accounts") if isinstance(chart_accounts, Mapping) else None
    if not isinstance(accounts, list):
        return None
    for raw in accounts:
        if not isinstance(raw, Mapping):
            continue
        candidate = _account_code(
            raw.get("normalized_account_code")
            or raw.get("account_code")
            or raw.get("code")
            or raw.get("raw_account_code")
        )
        if candidate != code:
            continue
        if raw.get("is_detail_account") is not True or raw.get("is_active") is False:
            return None
        return raw
    return None


def _narrow_scope(*, candidate: Mapping[str, Any], learning_event: Mapping[str, Any]) -> dict[str, Any]:
    candidate_scope = str(candidate.get("scope") or "").strip()
    tax_id = _digits(learning_event.get("counterparty_tax_id"))
    utility = learning_event.get("utility_context")
    utility = utility if isinstance(utility, Mapping) else {}
    service_profile = str(utility.get("service_profile") or "").strip()
    if candidate_scope == "client_counterparty" and tax_id:
        return {
            "scope": "client_counterparty",
            "qualifier": tax_id,
            "counterparty_tax_id": tax_id,
            "service_profile": "",
            "line_match_mode": "all_lines",
            "normalized_terms": (),
        }
    if service_profile:
        return {
            "scope": "client_service_profile",
            "qualifier": service_profile,
            "counterparty_tax_id": "",
            "service_profile": service_profile,
            "line_match_mode": "all_lines",
            "normalized_terms": (),
        }
    terms = _terms(candidate.get("match_phrase")) or _terms(learning_event.get("normalized_terms"))
    if not terms:
        raise ValueError("learning_rule_scope_unresolved")
    return {
        "scope": "client_phrase",
        "qualifier": "-".join(terms[:4]),
        "counterparty_tax_id": "",
        "service_profile": "",
        "line_match_mode": "normalized_terms_all",
        "normalized_terms": terms,
    }

def _semantic_role(
    *,
    direction: str,
    account_code: str,
    account: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> str:
    raw_roles = account.get("semantic_roles") or account.get("semantic_role") or ()
    if isinstance(raw_roles, str):
        raw_roles = (raw_roles,)
    roles = tuple(_key_part(role) for role in raw_roles if _key_part(role))
    preferred = ("revenue", "sales_revenue") if direction == "sales" else ("expense", "stock", "purchase_stock")
    for role in preferred:
        if role in roles:
            return "revenue" if role == "sales_revenue" else "stock" if role == "purchase_stock" else role
    family = account_code[:3]
    treatment = str(candidate.get("account_treatment") or "").strip()
    if direction == "sales" and family.startswith("6"):
        return "revenue"
    if direction == "purchase" and (family.startswith("15") or treatment == "stock_or_cogs"):
        return "stock"
    if direction == "purchase" and family.startswith("7"):
        return "expense"
    return ""


def _rule_key(*, client_id: str, direction: str, scope: str, qualifier: str) -> str:
    return ":".join(("client", _key_part(client_id), direction, scope, _key_part(qualifier)))


def _same_authority(current: Mapping[str, Any], snapshot: Mapping[str, Any]) -> bool:
    fields = (
        "client_id", "scope", "direction", "invoice_mode", "counterparty_tax_id",
        "service_profile", "line_match_mode", "semantic_role", "account_code",
    )
    if any(str(current.get(field) or "") != str(snapshot.get(field) or "") for field in fields):
        return False
    return tuple(current.get("normalized_terms") or ()) == tuple(snapshot.get("normalized_terms") or ())


def _terms(value: object) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple, set)) else str(value or "").split()
    normalized = tuple(_key_part(item) for item in values if _key_part(item))
    return tuple(dict.fromkeys(normalized))[:8]


def _key_part(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    ascii_text = "".join(character for character in raw if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def _account_code(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _digits(value: object) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())
