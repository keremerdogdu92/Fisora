from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from app.domain.learning_intelligence import normalize_text, normalized_terms
from app.domain.matching_simulation import SimulatedInvoiceResult
from app.domain.review_learning import LearningEvent


LEARNING_APPLIED_EVIDENCE = "learning_rule_applied"


@dataclass(frozen=True)
class LearnedPostingRule:
    scope: str
    action: str
    category: str
    corrected_account_code: str = ""
    corrected_counterparty_code: str = ""
    reason: str = ""
    automation_candidate: bool = False
    accounting_intent: str = ""
    accounting_intent_confidence: int = 0
    normalized_terms: tuple[str, ...] = ()
    nace_code: str = ""
    activity_tags: tuple[str, ...] = ()
    vat_rates: tuple[str, ...] = ()
    posting_signature: str = ""
    counterparty_tax_id: str = ""
    counterparty_title: str = ""
    counterparty_identity_key: str = ""
    source_summary: str = ""
    rule_prompt: dict[str, object] | None = None
    natural_language_rule_candidate: dict[str, object] | None = None


def rule_from_learning_event(event: LearningEvent) -> LearnedPostingRule:
    return LearnedPostingRule(
        scope=event.scope,
        action=event.action,
        category=event.category,
        corrected_account_code=event.corrected_account_code,
        corrected_counterparty_code=event.corrected_counterparty_code,
        reason=event.reason,
        automation_candidate=event.automation_candidate,
    )


def rule_from_event_payload(event: dict[str, object]) -> LearnedPostingRule:
    return LearnedPostingRule(
        scope=str(event.get("scope") or "general_candidate"),
        action=str(event.get("action") or ""),
        category=str(event.get("category") or ""),
        corrected_account_code=str(event.get("corrected_account_code") or ""),
        corrected_counterparty_code=str(event.get("corrected_counterparty_code") or ""),
        reason=str(event.get("reason") or ""),
        automation_candidate=bool(event.get("automation_candidate")),
        accounting_intent=str(event.get("accounting_intent") or ""),
        accounting_intent_confidence=int(event.get("accounting_intent_confidence") or 0),
        normalized_terms=tuple(str(term) for term in event.get("normalized_terms") or () if str(term).strip()),
        nace_code="".join(ch for ch in str(event.get("nace_code") or "") if ch.isdigit()),
        activity_tags=tuple(str(tag).strip() for tag in event.get("activity_tags") or () if str(tag).strip()),
        vat_rates=tuple(str(rate).strip() for rate in event.get("vat_rates") or () if str(rate).strip()),
        posting_signature=str(event.get("posting_signature") or ""),
        counterparty_tax_id="".join(ch for ch in str(event.get("counterparty_tax_id") or "") if ch.isdigit()),
        counterparty_title=str(event.get("counterparty_title") or ""),
        counterparty_identity_key=str(event.get("counterparty_identity_key") or ""),
        source_summary=str(event.get("learning_rule_source_summary") or ""),
        rule_prompt=event.get("rule_prompt") if isinstance(event.get("rule_prompt"), dict) else None,
        natural_language_rule_candidate=(
            event.get("natural_language_rule_candidate") if isinstance(event.get("natural_language_rule_candidate"), dict) else None
        ),
    )


def apply_learning_rules(
    result: SimulatedInvoiceResult,
    rules: Iterable[LearnedPostingRule],
) -> SimulatedInvoiceResult:
    rule_list = tuple(rules)
    rule = _select_rule(result, rule_list)
    if rule is None:
        semantic_rule = _select_semantic_rule(result, rule_list)
        if semantic_rule is None:
            return replace(result, learning_audit=_blocked_learning_audit(result, rule_list)) if rule_list else result
        return _apply_semantic_rule_context(result, semantic_rule)

    can_apply_counterparty = _can_apply_counterparty_code(result, rule)
    effective_rule = rule if can_apply_counterparty else replace(rule, corrected_counterparty_code="")
    trusted_export = _trusted_export_rule(result, rule)
    draft_lines = tuple(_apply_rule_to_line(line, result, effective_rule) for line in result.draft_lines)
    evidence = tuple(dict.fromkeys((*result.business_relevance_evidence, LEARNING_APPLIED_EVIDENCE)))
    review_reasons = (
        result.review_reason_codes
        if trusted_export
        else tuple(dict.fromkeys((*result.review_reason_codes, "learning_rule_review_required")))
    )
    reason = rule.source_summary or rule.reason
    return replace(
        result,
        selected_expense_account=rule.corrected_account_code or result.selected_expense_account,
        selected_supplier_account=effective_rule.corrected_counterparty_code or result.selected_supplier_account,
        business_relevance_evidence=evidence,
        review_reason_codes=review_reasons,
        learning_rule_applied=True,
        learning_rule_scope=rule.scope,
        learning_rule_reason=reason,
        learning_rule_source_summary=reason,
        accounting_intent=rule.accounting_intent,
        accounting_intent_confidence=rule.accounting_intent_confidence,
        rule_prompt=rule.rule_prompt or {},
        learning_audit=_applied_learning_audit(result, rule, status="applied", semantic=False),
        simulated_status=result.simulated_status if trusted_export else "review_required",
        export_status=result.export_status if trusted_export else "review_required",
        export_gate_reason=(
            result.export_gate_reason
            if trusted_export
            else reason or "Onceki musavir karari benzerlik nedeniyle review gerektiriyor."
        ),
        draft_lines=draft_lines,
    )


def _select_rule(result: SimulatedInvoiceResult, rules: Iterable[LearnedPostingRule]) -> LearnedPostingRule | None:
    allowed_actions = {"approve", "approve_with_changes", "suggest_for_similar"}
    scored: list[tuple[int, LearnedPostingRule]] = []
    for rule in rules:
        if _is_office_semantic_rule(rule):
            continue
        if rule.action not in allowed_actions:
            continue
        if (
            rule.natural_language_rule_candidate
            and rule.natural_language_rule_candidate.get("requires_review")
            and rule.action != "suggest_for_similar"
        ):
            continue
        if not rule.corrected_account_code and not rule.corrected_counterparty_code:
            continue
        if not _rule_can_override_ai(rule):
            continue
        if _has_counterparty_scope(rule) and not _counterparty_scope_matches(result, rule):
            continue
        score = _rule_score(result, rule)
        if score >= 60:
            scored.append((score, rule))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _select_semantic_rule(result: SimulatedInvoiceResult, rules: Iterable[LearnedPostingRule]) -> LearnedPostingRule | None:
    allowed_actions = {"approve", "approve_with_changes", "suggest_for_similar"}
    scored: list[tuple[int, LearnedPostingRule]] = []
    for rule in rules:
        if rule.action not in allowed_actions or not _is_office_semantic_rule(rule):
            continue
        score = _rule_score(result, replace(rule, corrected_account_code="", corrected_counterparty_code=""))
        if score >= 60:
            scored.append((score, rule))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _apply_semantic_rule_context(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> SimulatedInvoiceResult:
    evidence = tuple(dict.fromkeys((*result.business_relevance_evidence, LEARNING_APPLIED_EVIDENCE)))
    reason = rule.source_summary or rule.reason
    return replace(
        result,
        business_relevance_evidence=evidence,
        learning_rule_applied=True,
        learning_rule_scope=rule.scope,
        learning_rule_reason=reason,
        learning_rule_source_summary=reason,
        accounting_intent=rule.accounting_intent,
        accounting_intent_confidence=rule.accounting_intent_confidence,
        rule_prompt=rule.rule_prompt or {},
        learning_audit=_applied_learning_audit(result, rule, status="applied", semantic=True),
    )


def _is_office_semantic_rule(rule: LearnedPostingRule) -> bool:
    candidate = rule.natural_language_rule_candidate or {}
    return str(candidate.get("scope") or "") == "office_semantic"


def _rule_can_override_ai(rule: LearnedPostingRule) -> bool:
    if rule.automation_candidate:
        return True
    if rule.scope == "client_rule":
        return True
    if rule.action == "suggest_for_similar":
        return True
    return False


def _rule_score(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> int:
    score = 0
    if rule.category and rule.category == result.product_category:
        score += 50
    haystack = normalize_text(
        " ".join(
            (
                result.product_line_hint,
                result.provider_hint,
                result.product_category,
                result.invoice_type,
            )
        )
    )
    haystack_terms = set(normalized_terms(haystack, limit=20))
    if rule.accounting_intent:
        intent_terms = set(normalized_terms(rule.accounting_intent.replace("_", " "), limit=8))
        if intent_terms & haystack_terms:
            score += 40
    overlap = len(set(rule.normalized_terms) & haystack_terms)
    score += min(overlap * 15, 45)
    result_nace = "".join(ch for ch in str(result.client_nace_code or "") if ch.isdigit())
    if rule.nace_code and result_nace:
        score += 30 if rule.nace_code == result_nace else -30
    result_vat_rates = {str(rate).strip() for rate in result.vat_rates if str(rate).strip()}
    rule_vat_rates = {str(rate).strip() for rate in rule.vat_rates if str(rate).strip()}
    if rule_vat_rates and result_vat_rates:
        score += 20 if rule_vat_rates.intersection(result_vat_rates) else -20
    tag_overlap = set(rule.activity_tags).intersection(result.client_activity_tags)
    score += min(len(tag_overlap) * 15, 30)
    if rule.corrected_account_code and rule.corrected_account_code[:3] == result.selected_expense_account[:3]:
        score += 10
    if _has_counterparty_scope(rule) and _counterparty_scope_matches(result, rule):
        score += 35
    return score


def _matched_terms(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> list[str]:
    haystack = normalize_text(
        " ".join(
            (
                result.product_line_hint,
                result.provider_hint,
                result.product_category,
                result.invoice_type,
            )
        )
    )
    haystack_terms = set(normalized_terms(haystack, limit=20))
    return sorted(set(rule.normalized_terms).intersection(haystack_terms))


def _applied_learning_audit(
    result: SimulatedInvoiceResult,
    rule: LearnedPostingRule,
    *,
    status: str,
    semantic: bool,
) -> dict[str, object]:
    score = _rule_score(result, rule)
    account = "" if semantic else rule.corrected_account_code
    counterparty = "" if semantic else rule.corrected_counterparty_code
    applied_effect = (
        "Ofis geneli anlam baglami kullanildi; hesap kodu baska mukellefe tasinmadi."
        if semantic
        else "; ".join(
            part
            for part in (
                f"Hesap {account} onerildi" if account else "",
                f"cari {counterparty} kullanildi" if counterparty else "",
            )
            if part
        )
        or "Onceki musavir karari benzerlik baglami olarak kullanildi."
    )
    return {
        "status": status,
        "scope": rule.scope,
        "source_action": rule.action,
        "understood_rule_tr": rule.source_summary or rule.reason,
        "trigger_tr": rule.counterparty_title or rule.counterparty_tax_id or rule.category or rule.accounting_intent,
        "applied_effect_tr": applied_effect,
        "guardrail_tr": "Ilk uygulamalarda musavir kontrolu istenir; KDV, fis dengesi ve export kapisi ayrica korunur.",
        "match_score": score,
        "matched_terms": _matched_terms(result, rule),
        "suggested_account_code": account,
        "suggested_counterparty_code": counterparty,
        "reason_codes": ["office_semantic_context"] if semantic else ["learning_rule_applied"],
    }


def _blocked_learning_audit(result: SimulatedInvoiceResult, rules: Iterable[LearnedPostingRule]) -> dict[str, object]:
    allowed_actions = {"approve", "approve_with_changes", "suggest_for_similar"}
    scored = [(max(_rule_score(result, rule), 0), rule) for rule in rules if rule.action in allowed_actions]
    if not scored:
        return {
            "status": "blocked",
            "reason_codes": ["no_approved_learning_rule"],
            "match_score": 0,
            "matched_terms": [],
        }
    scored.sort(key=lambda item: item[0], reverse=True)
    score, rule = scored[0]
    reason_codes = ["learning_rule_score_below_threshold"] if score < 60 else ["learning_rule_guardrail_blocked"]
    if _has_counterparty_scope(rule) and not _counterparty_scope_matches(result, rule):
        reason_codes.append("counterparty_scope_mismatch")
    if rule.natural_language_rule_candidate and rule.natural_language_rule_candidate.get("requires_review") and rule.action != "suggest_for_similar":
        reason_codes.append("requires_explicit_suggest_for_similar")
    return {
        "status": "blocked",
        "scope": rule.scope,
        "source_action": rule.action,
        "understood_rule_tr": rule.source_summary or rule.reason,
        "trigger_tr": rule.counterparty_title or rule.counterparty_tax_id or rule.category or rule.accounting_intent,
        "applied_effect_tr": "Ogrenme kurali bu belgeye uygulanmadi.",
        "guardrail_tr": "Benzerlik, kapsam ve guvenlik kosullari saglanmadan kural uygulanmaz.",
        "match_score": score,
        "matched_terms": _matched_terms(result, rule),
        "suggested_account_code": rule.corrected_account_code,
        "suggested_counterparty_code": rule.corrected_counterparty_code,
        "reason_codes": reason_codes,
    }


def _has_counterparty_scope(rule: LearnedPostingRule) -> bool:
    return bool(rule.counterparty_identity_key or rule.counterparty_tax_id or rule.counterparty_title.strip())


def _counterparty_scope_matches(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> bool:
    if rule.counterparty_identity_key and result.counterparty_identity_key:
        return rule.counterparty_identity_key == result.counterparty_identity_key
    if rule.counterparty_tax_id and result.counterparty_tax_id:
        return rule.counterparty_tax_id == result.counterparty_tax_id
    if rule.counterparty_title.strip() and result.counterparty_title.strip():
        return normalize_text(rule.counterparty_title) == normalize_text(result.counterparty_title)
    return False


def _can_apply_counterparty_code(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> bool:
    return bool(rule.corrected_counterparty_code and _has_counterparty_scope(rule) and _counterparty_scope_matches(result, rule))


def _trusted_export_rule(result: SimulatedInvoiceResult, rule: LearnedPostingRule) -> bool:
    if result.export_status != "export_ready":
        return False
    if not result.is_balanced:
        return False
    if not (rule.automation_candidate or rule.action == "suggest_for_similar"):
        return False
    if not (_has_counterparty_scope(rule) and _counterparty_scope_matches(result, rule)):
        return False
    return _rule_score(result, rule) >= 90


def _apply_rule_to_line(
    line: dict[str, str],
    result: SimulatedInvoiceResult,
    rule: LearnedPostingRule,
) -> dict[str, str]:
    updated = dict(line)
    if rule.corrected_account_code and line["account_code"] == result.selected_expense_account:
        updated["account_code"] = rule.corrected_account_code
    if rule.corrected_counterparty_code and line["account_code"] == result.selected_supplier_account:
        updated["account_code"] = rule.corrected_counterparty_code
    return updated
