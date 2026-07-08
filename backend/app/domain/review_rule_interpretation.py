from __future__ import annotations

from typing import Any, Mapping


REVIEW_RULE_INTERPRETATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["ready", "needs_clarification", "not_available"]},
        "summary_tr": {"type": "string"},
        "trigger_tr": {"type": "string"},
        "action_tr": {"type": "string"},
        "guardrail_tr": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary_tr", "trigger_tr", "action_tr", "guardrail_tr", "confidence", "reason_codes"],
}


def build_review_rule_interpretation(
    *,
    event: Mapping[str, Any],
    document: Mapping[str, Any] | None,
    provider: Any | None = None,
) -> dict[str, Any] | None:
    candidate = event.get("natural_language_rule_candidate")
    note = str(event.get("accountant_note") or event.get("rule_instruction") or "").strip()
    if not isinstance(candidate, Mapping) or not note:
        return None
    request = review_rule_interpretation_request(event=event, document=document, candidate=candidate)
    if provider is not None and hasattr(provider, "interpret_review_rule"):
        try:
            interpreted = _validated_provider_interpretation(provider.interpret_review_rule(request))
            interpreted.update(
                {
                    "source": "ai",
                    "provider": str(getattr(provider, "last_provider_name", "") or getattr(provider, "provider_name", "") or "ai"),
                }
            )
            return interpreted
        except Exception as exc:  # noqa: BLE001 - review save should not fail when AI cannot clarify a note
            fallback = deterministic_review_rule_interpretation(event=event, document=document, candidate=candidate)
            fallback["ai_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            return fallback
    return deterministic_review_rule_interpretation(event=event, document=document, candidate=candidate)


def review_rule_interpretation_request(
    *,
    event: Mapping[str, Any],
    document: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> dict[str, object]:
    result = _result(document)
    return {
        "accountant_note": str(event.get("accountant_note") or ""),
        "rule_instruction": str(event.get("rule_instruction") or ""),
        "candidate": dict(candidate),
        "learning_event": {
            "action": str(event.get("action") or ""),
            "category": str(event.get("category") or ""),
            "corrected_account_code": str(event.get("corrected_account_code") or ""),
            "corrected_counterparty_code": str(event.get("corrected_counterparty_code") or ""),
            "accounting_intent": str(event.get("accounting_intent") or ""),
            "scope_suggestion": str(event.get("scope_suggestion") or ""),
        },
        "document": {
            "accounting_direction": str(result.get("accounting_direction") or ""),
            "product_line_hint": str(result.get("product_line_hint") or ""),
            "product_category": str(result.get("product_category") or ""),
            "counterparty_tax_id": str(result.get("counterparty_tax_id") or ""),
            "counterparty_title": str(result.get("counterparty_title") or ""),
            "selected_expense_account": str(result.get("selected_expense_account") or ""),
            "selected_revenue_account": str(result.get("selected_revenue_account") or ""),
            "selected_supplier_account": str(result.get("selected_supplier_account") or ""),
            "selected_customer_account": str(result.get("selected_customer_account") or ""),
        },
        "output_schema": REVIEW_RULE_INTERPRETATION_SCHEMA,
    }


def deterministic_review_rule_interpretation(
    *,
    event: Mapping[str, Any],
    document: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    result = _result(document)
    tax_id = str(result.get("counterparty_tax_id") or event.get("counterparty_tax_id") or "").strip()
    title = str(result.get("counterparty_title") or event.get("counterparty_title") or "").strip()
    direction = _direction_label(str(result.get("accounting_direction") or ""))
    account = str(candidate.get("suggested_account_code") or event.get("corrected_account_code") or "").strip()
    counterparty_code = str(event.get("corrected_counterparty_code") or result.get("selected_supplier_account") or result.get("selected_customer_account") or "").strip()
    category = str(candidate.get("product_category") or event.get("category") or result.get("product_category") or "").strip()
    scope = str(candidate.get("scope") or "").strip()
    vague = not str(candidate.get("match_phrase") or "").strip() and not account and scope == "client_only"
    status = "needs_clarification" if vague else "ready"
    subject = _subject(title=title, tax_id=tax_id, category=category)
    trigger = _trigger(scope=scope, title=title, tax_id=tax_id, category=category, direction=direction)
    action = _action(account=account, counterparty_code=counterparty_code)
    summary = (
        f"{subject} için {account} hesabı önerilecek."
        if account
        else f"{subject} için benzer belge kuralı aday olarak kaydedilecek."
    )
    if status == "needs_clarification":
        summary = "Not kural yapmak için yeterince net değil; müşavir karar notunu daraltmalı."
    return {
        "source": "deterministic",
        "provider": "static_rule_interpreter",
        "status": status,
        "summary_tr": summary,
        "trigger_tr": trigger,
        "action_tr": action,
        "guardrail_tr": "İlk uygulamalarda müşavir kontrolü istenir; KDV, fiş dengesi ve export kapısı ayrıca korunur.",
        "confidence": 72 if status == "ready" else 35,
        "reason_codes": _reason_codes(scope=scope, tax_id=tax_id, account=account, status=status),
    }


def _validated_provider_interpretation(payload: object) -> dict[str, Any]:
    source = payload if isinstance(payload, Mapping) else {}
    status = str(source.get("status") or "needs_clarification")
    if status not in {"ready", "needs_clarification", "not_available"}:
        status = "needs_clarification"
    confidence = int(source.get("confidence") or 0)
    confidence = min(max(confidence, 0), 100)
    return {
        "status": status,
        "summary_tr": str(source.get("summary_tr") or ""),
        "trigger_tr": str(source.get("trigger_tr") or ""),
        "action_tr": str(source.get("action_tr") or ""),
        "guardrail_tr": str(source.get("guardrail_tr") or "İlk uygulamalarda müşavir kontrolü istenir."),
        "confidence": confidence,
        "reason_codes": [str(item) for item in source.get("reason_codes") or [] if str(item).strip()],
    }


def _result(document: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        return {}
    result = document.get("result")
    return result if isinstance(result, Mapping) else {}


def _direction_label(direction: str) -> str:
    if direction == "purchase":
        return "alış faturası"
    if direction == "sales":
        return "satış faturası"
    return "belge"


def _subject(*, title: str, tax_id: str, category: str) -> str:
    if title and tax_id:
        return f"VKN {tax_id} / {title} faturaları"
    if tax_id:
        return f"VKN {tax_id} olan karşı tarafın faturaları"
    if title:
        return f"{title} faturaları"
    if category:
        return f"{category} belgeleri"
    return "Benzer belgeler"


def _trigger(*, scope: str, title: str, tax_id: str, category: str, direction: str) -> str:
    pieces = []
    if scope == "client_counterparty":
        if tax_id:
            pieces.append(f"VKN {tax_id}")
        if title:
            pieces.append(title)
    if category:
        pieces.append(category)
    pieces.append(direction)
    return " / ".join(piece for piece in pieces if piece)


def _action(*, account: str, counterparty_code: str) -> str:
    pieces = []
    if account:
        pieces.append(f"Hesap {account} önerilecek")
    if counterparty_code:
        pieces.append(f"cari {counterparty_code} kullanılacak")
    return "; ".join(pieces) if pieces else "Kural adayı sadece not olarak saklanacak"


def _reason_codes(*, scope: str, tax_id: str, account: str, status: str) -> list[str]:
    if status != "ready":
        return ["clarification_required"]
    codes = []
    if scope == "client_counterparty" or tax_id:
        codes.append("counterparty_tax_id_rule")
    if account:
        codes.append("account_rule")
    return codes or ["learning_note_rule"]
