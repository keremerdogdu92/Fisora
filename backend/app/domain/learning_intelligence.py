from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable

from app.domain.natural_language_rule_builder import build_natural_language_rule_candidate


APPROVAL_ACTIONS = {"approve", "approve_with_changes", "suggest_for_similar"}
GLOBAL_TEMPLATE_INTENTS = {
    "banka_masrafi",
    "dogalgaz_gideri",
    "e_fatura_yazilim_gideri",
    "elektrik_gideri",
    "internet_gideri",
    "kira_gideri",
    "su_gideri",
}
STOP_TERMS = {
    "alt",
    "bu",
    "da",
    "de",
    "diye",
    "gibi",
    "icin",
    "ile",
    "ise",
    "kalem",
    "mukellef",
    "sekilde",
    "ve",
}


@dataclass(frozen=True)
class LearningPolicy:
    client_rule_threshold: int = 3
    office_client_threshold: int = 3
    office_decision_threshold: int = 5
    global_prompt_confidence: int = 82


@dataclass(frozen=True)
class IntentClassification:
    accounting_intent: str
    confidence: int
    scope_suggestion: str
    keywords: tuple[str, ...]
    provider: str = "static_intent_classifier"


def normalize_text(value: str) -> str:
    replacements = {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
    text = str(value or "").strip()
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalized_terms(value: str, *, limit: int = 12) -> tuple[str, ...]:
    terms = []
    for term in normalize_text(value).split():
        if len(term) < 2 or term in STOP_TERMS:
            continue
        terms.append(term)
    return tuple(dict.fromkeys(terms))[:limit]


def classify_accounting_intent(source_text: str, *, category: str = "", document_type: str = "") -> IntentClassification:
    normalized = normalize_text(f"{source_text} {category} {document_type}")
    term_set = set(normalized.split())
    patterns: list[tuple[str, tuple[str, ...], int]] = [
        ("e_fatura_yazilim_gideri", ("kolay", "soft", "e", "fatura", "efatura", "yazilim", "uyumsoft", "luca"), 88),
        ("internet_gideri", ("internet", "fiber", "superonline", "ttnet", "turknet", "telekom"), 86),
        ("elektrik_gideri", ("elektrik", "edas", "enerji"), 86),
        ("su_gideri", ("su", "iski", "aski", "su faturasi"), 84),
        ("dogalgaz_gideri", ("dogalgaz", "gaz", "igdas"), 84),
        ("kira_gideri", ("kira", "kiralama", "gayrimenkul"), 84),
        ("banka_masrafi", ("masraf", "komisyon", "eft", "havale", "banka"), 78),
        ("tedarikci_odeme", ("tedarikci", "odeme", "satici", "cari"), 74),
    ]
    for intent, keywords, confidence in patterns:
        matched = tuple(keyword for keyword in keywords if keyword in term_set or keyword in normalized)
        if matched:
            scope = "global_template_candidate" if intent in GLOBAL_TEMPLATE_INTENTS else "client_rule_candidate"
            if "bu mukellef" in normalized or "mukellefte" in normalized:
                scope = "client_rule_candidate"
            if "ofis geneli" in normalized or "tum mukellef" in normalized:
                scope = "office_policy_candidate"
            return IntentClassification(intent, confidence, scope, matched)
    fallback_terms = normalized_terms(source_text or category or document_type, limit=4)
    fallback_intent = "_".join(fallback_terms[:3]) if fallback_terms else "genel_muhasebe_notu"
    return IntentClassification(fallback_intent, 52, "client_rule_candidate", fallback_terms)


def enrich_learning_event(
    event: dict[str, Any],
    *,
    client_id: str,
    decision: dict[str, Any],
    document: dict[str, Any] | None = None,
    client_profile: dict[str, Any] | None = None,
    prior_learning_events: Iterable[dict[str, Any]] = (),
    policy: LearningPolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or LearningPolicy()
    result = (document or {}).get("result") or {}
    line = _statement_line(result, int(decision.get("statement_line_no") or event.get("statement_line_no") or 0))
    document_type = str(result.get("invoice_type") or result.get("document_type") or "")
    transaction_type = str(
        (line or {}).get("transaction_type")
        or result.get("product_category")
        or result.get("draft_entry_type")
        or event.get("category")
        or ""
    )
    source_text = _source_text(event=event, decision=decision, result=result, line=line)
    classification = classify_accounting_intent(
        source_text,
        category=str(event.get("category") or decision.get("category") or ""),
        document_type=document_type,
    )
    enriched = dict(event)
    selected_account_code = _selected_account_code(result)
    selected_counterparty_code = _selected_counterparty_code(result)
    action = str(enriched.get("action") or "")
    if action in APPROVAL_ACTIONS:
        if not str(enriched.get("corrected_account_code") or "").strip():
            enriched["corrected_account_code"] = selected_account_code
        if not str(enriched.get("corrected_counterparty_code") or "").strip():
            enriched["corrected_counterparty_code"] = selected_counterparty_code
    profile = client_profile or {}
    nace_code = _digits_only(profile.get("nace_code") or result.get("nace_code") or "")
    activity_tags = _string_list(profile.get("activity_tags") or result.get("activity_tags") or [])
    vat_rates = _string_list(result.get("vat_rates") or [])
    counterparty_tax_id = _digits_only(result.get("counterparty_tax_id") or "")
    counterparty_title = str(result.get("counterparty_title") or result.get("provider_hint") or "").strip()
    counterparty_identity_key = str(result.get("counterparty_identity_key") or "").strip()
    enriched.update(
        {
            "client_id": client_id,
            "document_type": document_type,
            "transaction_type": transaction_type,
            "source_text": source_text[:600],
            "normalized_terms": list(normalized_terms(source_text)),
            "accounting_intent": classification.accounting_intent,
            "accounting_intent_confidence": classification.confidence,
            "accounting_intent_provider": classification.provider,
            "accounting_intent_keywords": list(classification.keywords),
            "scope_suggestion": classification.scope_suggestion,
            "nace_code": nace_code,
            "activity_tags": activity_tags,
            "vat_rates": vat_rates,
            "selected_account_code": selected_account_code,
            "selected_counterparty_code": selected_counterparty_code,
            "counterparty_tax_id": counterparty_tax_id,
            "counterparty_title": counterparty_title,
            "counterparty_identity_key": counterparty_identity_key,
            "posting_signature": _posting_signature(
                nace_code=nace_code,
                category=str(event.get("category") or decision.get("category") or result.get("product_category") or ""),
                vat_rates=vat_rates,
                account_code=str(enriched.get("corrected_account_code") or selected_account_code),
                counterparty_code=str(enriched.get("corrected_counterparty_code") or selected_counterparty_code),
            ),
            "match_key": _match_key(
                client_id=client_id,
                document_type=document_type,
                transaction_type=transaction_type,
                accounting_intent=classification.accounting_intent,
                terms=classification.keywords or normalized_terms(source_text, limit=4),
            ),
        }
    )
    accountant_note = str(decision.get("accountant_note") or event.get("accountant_note") or "").strip()
    rule_instruction = str(decision.get("rule_instruction") or event.get("rule_instruction") or "").strip()
    if accountant_note or rule_instruction:
        enriched["accountant_note"] = accountant_note
        enriched["rule_instruction"] = rule_instruction
        enriched["natural_language_rule_candidate"] = build_natural_language_rule_candidate(
            accountant_note=accountant_note,
            rule_instruction=rule_instruction,
            product_line_hint=str(result.get("product_line_hint") or result.get("provider_hint") or ""),
            category=str(event.get("category") or decision.get("category") or result.get("product_category") or ""),
            corrected_account_code=str(enriched.get("corrected_account_code") or decision.get("corrected_account_code") or ""),
        )
    client_count = _consistent_count(enriched, prior_learning_events, client_scoped=True)
    office_events = [*prior_learning_events, enriched]
    office_count = _consistent_count(enriched, prior_learning_events, client_scoped=False)
    office_client_count = len(
        {
            str(item.get("client_id") or "")
            for item in office_events
            if _office_match(enriched, item) and str(item.get("client_id") or "")
        }
    )
    prompt = _rule_prompt(
        event=enriched,
        policy=resolved_policy,
        client_count=client_count,
        office_count=office_count,
        office_client_count=office_client_count,
    )
    enriched.update(
        {
            "client_consistent_decision_count": client_count,
            "office_consistent_decision_count": office_count,
            "office_distinct_client_count": office_client_count,
            "rule_prompt": prompt,
            "rule_status": prompt["status"],
            "learning_rule_source_summary": _source_summary(enriched, prompt),
        }
    )
    return enriched


def _source_text(*, event: dict[str, Any], decision: dict[str, Any], result: dict[str, Any], line: dict[str, Any] | None) -> str:
    parts = [
        str(decision.get("reason") or event.get("reason") or ""),
        str(decision.get("category") or event.get("category") or ""),
        str(result.get("provider_hint") or ""),
        str(result.get("product_line_hint") or ""),
        str(result.get("file_name") or ""),
    ]
    if line:
        parts.extend(
            [
                str(line.get("description") or ""),
                str(line.get("counterparty_name") or ""),
                str(line.get("transaction_type") or ""),
            ]
        )
    return " ".join(part for part in parts if part.strip()).strip()


def _statement_line(result: dict[str, Any], line_no: int) -> dict[str, Any] | None:
    if line_no <= 0:
        return None
    for line in result.get("statement_lines") or []:
        if isinstance(line, dict) and int(line.get("line_no") or 0) == line_no:
            return line
    return None


def _match_key(*, client_id: str, document_type: str, transaction_type: str, accounting_intent: str, terms: Iterable[str]) -> str:
    stable_terms = "-".join(tuple(dict.fromkeys(str(term) for term in terms if str(term).strip()))[:4])
    return "|".join((client_id, document_type, transaction_type, accounting_intent, stable_terms))


def _consistent_count(target: dict[str, Any], events: Iterable[dict[str, Any]], *, client_scoped: bool) -> int:
    count = 1
    for item in events:
        if client_scoped and str(item.get("client_id") or "") != str(target.get("client_id") or ""):
            continue
        if _office_match(target, item):
            count += 1
    return count


def _office_match(target: dict[str, Any], item: dict[str, Any]) -> bool:
    if str(item.get("action") or "") not in APPROVAL_ACTIONS:
        return False
    target_nace = str(target.get("nace_code") or "")
    item_nace = str(item.get("nace_code") or "")
    if target_nace and item_nace and target_nace != item_nace:
        return False
    target_vat_rates = set(_string_list(target.get("vat_rates") or []))
    item_vat_rates = set(_string_list(item.get("vat_rates") or []))
    if target_vat_rates and item_vat_rates and not target_vat_rates.intersection(item_vat_rates):
        return False
    if str(item.get("accounting_intent") or "") != str(target.get("accounting_intent") or ""):
        return False
    target_account = str(target.get("corrected_account_code") or "")
    item_account = str(item.get("corrected_account_code") or "")
    target_counterparty = str(target.get("corrected_counterparty_code") or "")
    item_counterparty = str(item.get("corrected_counterparty_code") or "")
    if target_account and item_account and target_account != item_account and str(item.get("client_id") or "") == str(target.get("client_id") or ""):
        return False
    if target_counterparty and item_counterparty and target_counterparty != item_counterparty and str(item.get("client_id") or "") == str(target.get("client_id") or ""):
        return False
    return True


def _selected_account_code(result: dict[str, Any]) -> str:
    direction = str(result.get("accounting_direction") or "").strip()
    if direction == "sales":
        return str(result.get("selected_revenue_account") or result.get("selected_expense_account") or "").strip()
    return str(result.get("selected_expense_account") or result.get("selected_revenue_account") or "").strip()


def _selected_counterparty_code(result: dict[str, Any]) -> str:
    direction = str(result.get("accounting_direction") or "").strip()
    if direction == "sales":
        return str(result.get("selected_customer_account") or result.get("selected_supplier_account") or "").strip()
    return str(result.get("selected_supplier_account") or result.get("selected_customer_account") or "").strip()


def _digits_only(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if str(value or "").strip():
        return [str(value).strip()]
    return []


def _account_family(code: str) -> str:
    match = re.match(r"^(\d{3})", str(code or "").strip())
    return match.group(1) if match else ""


def _posting_signature(
    *,
    nace_code: str,
    category: str,
    vat_rates: Iterable[str],
    account_code: str,
    counterparty_code: str,
) -> str:
    vat = ",".join(tuple(dict.fromkeys(str(rate).strip() for rate in vat_rates if str(rate).strip())))
    return "|".join(
        (
            f"nace:{nace_code}",
            f"category:{str(category or '').strip()}",
            f"vat:{vat}",
            f"account:{_account_family(account_code)}",
            f"counterparty:{_account_family(counterparty_code)}",
        )
    )


def _rule_prompt(
    *,
    event: dict[str, Any],
    policy: LearningPolicy,
    client_count: int,
    office_count: int,
    office_client_count: int,
) -> dict[str, Any]:
    action = str(event.get("action") or "")
    if action not in APPROVAL_ACTIONS:
        return {
            "show": False,
            "status": "learning_note",
            "default_scope": "note_only",
            "message": "Bu karar risk notu olarak saklandi.",
            "client_consistent_decision_count": client_count,
            "office_distinct_client_count": office_client_count,
            "office_consistent_decision_count": office_count,
        }
    office_ready = office_client_count >= policy.office_client_threshold and office_count >= policy.office_decision_threshold
    client_ready = client_count >= policy.client_rule_threshold
    direct_rule_request = action == "suggest_for_similar"
    global_candidate = (
        str(event.get("accounting_intent") or "") in GLOBAL_TEMPLATE_INTENTS
        and int(event.get("accounting_intent_confidence") or 0) >= policy.global_prompt_confidence
    )
    show = client_ready or office_ready or direct_rule_request or global_candidate
    if office_ready:
        status = "office_policy_candidate"
        message = f"Ofis geneli aday: {office_client_count}/{policy.office_client_threshold} mukellef, {office_count}/{policy.office_decision_threshold} karar."
    elif direct_rule_request:
        status = "client_rule_prompt"
        message = "Musavir bu karari tek seferde benzerleri icin kural adayi yapti."
    elif client_ready:
        status = "client_rule_prompt"
        message = f"Bu karari {client_count} kez benzer sekilde verdiniz."
    elif global_candidate:
        status = "global_template_candidate"
        message = f"Global sablon adayi: {event.get('accounting_intent')}."
    else:
        status = "learning_signal"
        message = "Bu karar sonraki benzer belgeler icin ogrenme sinyali olarak saklandi."
    return {
        "show": show,
        "status": status,
        "default_scope": "client_narrow",
        "message": message,
        "client_consistent_decision_count": client_count,
        "office_distinct_client_count": office_client_count,
        "office_consistent_decision_count": office_count,
    }


def _source_summary(event: dict[str, Any], prompt: dict[str, Any]) -> str:
    intent = str(event.get("accounting_intent") or "muhasebe_niyeti")
    confidence = int(event.get("accounting_intent_confidence") or 0)
    count = int(prompt.get("client_consistent_decision_count") or 0)
    if count >= 2:
        return f"Bu oneride {count} onceki/tutarli musavir karari ve {intent} niyeti kullanildi; guven %{confidence}."
    return f"Muhasebe niyeti: {intent}, guven %{confidence}."
