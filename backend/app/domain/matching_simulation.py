from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from app.domain.ai_classification import AiCandidateStrategy, AiClassificationContext, AiClassificationPolicy, AiClassificationResult, ProductClassifier
from app.domain.business_relevance import (
    BusinessRelevance,
    ClientProfile,
    ProductClassification,
    assess_business_relevance,
    check_client_onboarding,
    classify_product_line,
    decide_export_status,
    normalize_text,
)
from app.domain.chart_accounts import (
    ChartAccount,
    extract_counterparty_candidates,
    parse_chart_accounts,
    select_revenue_account,
    select_usage_account,
    select_vat_account,
    semantic_roles_for_account,
    validate_vat_accounts,
)
from app.domain.counterparty_matching import CounterpartyMatch, match_counterparty
from app.domain.invoice_ai_gate import invoice_ai_gate
from app.domain.journal_entries import (
    JournalEntry,
    JournalLine,
    build_mixed_vat_purchase_entry,
    build_mixed_vat_sales_entry,
    build_purchase_entry,
    build_purchase_return_entry,
    build_purchase_return_review_entry,
    build_sales_entry,
    build_sales_return_entry,
    build_sales_return_review_entry,
    money,
)
from app.domain.pdf_invoices import ParsedInvoice, parse_invoice_folder

ProcessingMode = Literal["conservative", "ai_assisted_draft", "controlled_automation"]
VALID_PURCHASE_VAT_RATES = {"0", "1", "10", "20"}
MONEY_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class AccountSelection:
    chart_file_name: str
    expense_account: str
    purchase_vat_account: str
    supplier_account: str
    bank_account: str
    selection_notes: tuple[str, ...]
    revenue_account: str = "600.01"
    zero_vat_revenue_account: str = "600.00.3065"
    sales_vat_account: str = "391.01"
    customer_account: str = "120.01.001"
    next_customer_account: str = ""
    next_supplier_account: str = ""
    stock_account: str = "153.01"
    non_deductible_account: str = "689.01"
    account_candidates: dict[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulatedInvoiceResult:
    chart_file_name: str
    file_name: str
    provider_hint: str
    invoice_type: str
    issue_date: str
    payable_total: str
    vat_rates: tuple[str, ...]
    risk_flags: tuple[str, ...]
    parse_notes: tuple[str, ...]
    simulated_status: str
    draft_quality: str
    draft_entry_type: str
    total_debit: str
    total_credit: str
    is_balanced: bool
    selected_expense_account: str
    selected_vat_account: str
    selected_supplier_account: str
    counterparty_match_code: str
    counterparty_match_confidence: int
    counterparty_match_reason: str
    review_reason_codes: tuple[str, ...]
    processing_mode: str
    draft_decision_source: str
    deterministic_checks: tuple[str, ...]
    export_gate_reason: str
    product_line_hint: str
    product_category: str
    product_confidence: int
    business_relevance_status: str
    business_relevance_confidence: int
    business_relevance_reason: str
    business_relevance_evidence: tuple[str, ...]
    business_relevance_relation: str
    business_relevance_account_treatment: str
    business_relevance_requires_review: bool
    ai_classification_used: bool
    ai_classification_provider: str
    ai_classification_skipped_reason: str
    ai_classification_reason: str
    ai_estimated_input_chars: int
    ai_suggested_account_code: str
    ai_suggested_counterparty_code: str
    ai_risk_flags: tuple[str, ...]
    ai_account_reason: str
    learning_rule_applied: bool
    learning_rule_scope: str
    learning_rule_reason: str
    learning_rule_source_summary: str
    accounting_intent: str
    accounting_intent_confidence: int
    rule_prompt: dict[str, object]
    export_status: str
    draft_lines: tuple[dict[str, str], ...]
    draft_confidence: int = 0
    primary_suggestion: dict[str, object] = field(default_factory=dict)
    review_blockers: tuple[str, ...] = ()
    automation_eligibility: str = "not_eligible"
    accountant_action_hint: str = ""
    suggested_counterparty_creation: dict[str, object] | None = None
    selected_revenue_account: str = ""
    selected_purchase_vat_account: str = ""
    selected_sales_vat_account: str = ""
    selected_customer_account: str = ""
    suggested_counterparty_account: str = ""
    counterparty_creation_suggestion: dict[str, object] | None = None
    accounting_direction: str = "purchase"
    direction_confidence: int = 0
    direction_uncertainty: bool = False
    direction_evidence: tuple[str, ...] = ()
    direction_conflict: dict[str, object] = field(default_factory=dict)
    accountant_explanation_tr: str = ""
    account_candidates: dict[str, tuple[dict[str, Any], ...]] | None = None
    ai_gate_reason: str = ""
    ai_product_identity: str = ""
    ai_research_requested: bool = False
    ai_research_query: str = ""
    client_nace_code: str = ""
    client_activity_tags: tuple[str, ...] = ()
    counterparty_tax_id: str = ""
    counterparty_title: str = ""
    counterparty_identity_key: str = ""
    ai_candidate_strategy: str = "single_stage"
    ai_selected_account_families: tuple[str, ...] = ()
    ai_stage_evidence: tuple[dict[str, object], ...] = ()
    ai_account_stage_evidence: tuple[dict[str, object], ...] = ()
    ai_counterparty_stage_evidence: tuple[dict[str, object], ...] = ()
    ai_trace: tuple[dict[str, object], ...] = ()
    ai_account_candidate_count: int = 0
    ai_counterparty_candidate_count: int = 0
    ai_quality_scorecard: dict[str, object] = field(default_factory=dict)
    ai_resolution_status: str = "resolved"
    ai_retry_reason: str = ""
    static_fallback_account: str = ""
    static_fallback_suppressed: bool = False


@dataclass(frozen=True)
class SimulatedChartRun:
    chart_file_name: str
    account_count: int
    detail_account_count: int
    customer_candidate_count: int
    supplier_candidate_count: int
    has_purchase_vat_191: bool
    has_sales_vat_391: bool
    account_selection: AccountSelection
    invoice_results: tuple[SimulatedInvoiceResult, ...]

    @property
    def auto_ready_count(self) -> int:
        return sum(1 for result in self.invoice_results if result.simulated_status == "auto_ready")

    @property
    def review_required_count(self) -> int:
        return sum(1 for result in self.invoice_results if result.simulated_status == "review_required")

    @property
    def cannot_draft_count(self) -> int:
        return sum(1 for result in self.invoice_results if result.simulated_status == "cannot_draft")


def _first_account(accounts: list[ChartAccount], prefixes: tuple[str, ...]) -> ChartAccount | None:
    for account in accounts:
        if account.is_detail_account and account.normalized_account_code.startswith(prefixes):
            return account
    return None


def _account_with_name_hint(accounts: list[ChartAccount], prefix: str, hints: tuple[str, ...]) -> ChartAccount | None:
    for account in accounts:
        name = account.account_name.lower()
        if account.is_detail_account and account.normalized_account_code.startswith(prefix) and any(hint in name for hint in hints):
            return account
    return None


def _candidate_payload(account: ChartAccount, reason: str) -> dict[str, Any]:
    return {
        "code": account.normalized_account_code,
        "name": account.account_name,
        "reason": reason,
        "semantic_roles": semantic_roles_for_account(account),
        "vat_rate": account.vat_rate_hint,
    }


def _candidate_group(accounts: list[ChartAccount], prefixes: tuple[str, ...], reason: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        _candidate_payload(account, reason)
        for account in accounts
        if account.is_detail_account and account.normalized_account_code.startswith(prefixes)
    )


def _candidate_group_with_hint(accounts: list[ChartAccount], prefix: str, hints: tuple[str, ...], reason: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        _candidate_payload(account, reason)
        for account in accounts
        if account.is_detail_account
        and account.normalized_account_code.startswith(prefix)
        and any(hint in account.account_name.lower() for hint in hints)
    )


def _next_counterparty_account(accounts: list[ChartAccount], prefix: str, letter: str = "A") -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}\.?{re.escape(letter)}(\d+)$", re.IGNORECASE)
    max_index = 0
    for account in accounts:
        compact = account.normalized_account_code.replace(".", "")
        match = pattern.match(compact) or pattern.match(account.normalized_account_code)
        if match:
            max_index = max(max_index, int(match.group(1)))
    if max_index:
        return f"{prefix}.{letter}{max_index + 1:02d}"
    return f"{prefix}.{letter}01"


def select_accounts(chart_file_name: str, accounts: list[ChartAccount]) -> AccountSelection:
    notes: list[str] = []
    customers = [account for account in extract_counterparty_candidates(accounts) if account.counterparty_type == "customer"]
    suppliers = [account for account in extract_counterparty_candidates(accounts) if account.counterparty_type == "supplier"]
    customer = customers[0] if customers else _first_account(accounts, ("120",))
    supplier = suppliers[0] if suppliers else _first_account(accounts, ("320",))
    stock = _first_account(accounts, ("153",))
    expense = select_usage_account(accounts, "genel gider", "purchase") or _first_account(accounts, ("770", "760", "740", "730", " gider"))
    purchase_vat = select_vat_account(accounts, "191", "20") or _first_account(accounts, ("191",))
    revenue = select_revenue_account(accounts, "20") or _first_account(accounts, ("600",))
    zero_vat_revenue = _account_with_name_hint(accounts, "600", ("3065", "%0", "0 kdv", "istisna")) or select_revenue_account(accounts, "0") or revenue
    sales_vat = select_vat_account(accounts, "391", "20") or _first_account(accounts, ("391",))
    bank = _first_account(accounts, ("102",))
    non_deductible = _account_with_name_hint(accounts, "689", ("k.k.e", "kke", "kabul edilmeyen")) or _first_account(accounts, ("689",))

    if customer is None:
        notes.append("fallback_customer_120_missing")
    if supplier is None:
        notes.append("fallback_supplier_320_missing")
    if stock is None:
        notes.append("fallback_stock_153_missing")
    if expense is None:
        notes.append("fallback_expense_770_missing")
    if purchase_vat is None:
        notes.append("fallback_purchase_vat_191_missing")
    if revenue is None:
        notes.append("fallback_revenue_600_missing")
    if sales_vat is None:
        notes.append("fallback_sales_vat_391_missing")
    if bank is None:
        notes.append("fallback_bank_102_missing")

    return AccountSelection(
        chart_file_name=chart_file_name,
        expense_account=expense.normalized_account_code if expense else "770.01",
        purchase_vat_account=purchase_vat.normalized_account_code if purchase_vat else "191.01",
        supplier_account=supplier.normalized_account_code if supplier else "320.01.001",
        bank_account=bank.normalized_account_code if bank else "102.01",
        non_deductible_account=non_deductible.normalized_account_code if non_deductible else "689.01",
        selection_notes=tuple(notes),
        revenue_account=revenue.normalized_account_code if revenue else "600.01",
        zero_vat_revenue_account=zero_vat_revenue.normalized_account_code if zero_vat_revenue else "600.00.3065",
        sales_vat_account=sales_vat.normalized_account_code if sales_vat else "391.01",
        customer_account=customer.normalized_account_code if customer else "120.01.001",
        next_customer_account=_next_counterparty_account(accounts, "120"),
        next_supplier_account=_next_counterparty_account(accounts, "320"),
        stock_account=stock.normalized_account_code if stock else "153.01",
        account_candidates={
            "purchase_stock": _candidate_group(accounts, ("153",), "153 ticari mal/stok adayi"),
            "purchase_expense": _candidate_group(accounts, ("770", "760", "740"), "7xx gider hesabi adayi"),
            "purchase_vat": _candidate_group(accounts, ("191",), "191 indirilecek KDV adayi"),
            "sales_revenue": _candidate_group(accounts, ("600",), "600 satis geliri adayi"),
            "zero_vat_revenue": _candidate_group_with_hint(accounts, "600", ("3065", "%0", "0 kdv", "istisna"), "3065 kapsaminda yuzde 0 KDV satis geliri adayi")
            or _candidate_group(accounts, ("600",), "600 satis geliri adayi"),
            "sales_vat": _candidate_group(accounts, ("391",), "391 hesaplanan KDV adayi"),
            "customer": _candidate_group(accounts, ("120",), "120 alici cari adayi"),
            "supplier": _candidate_group(accounts, ("320",), "320 satici cari adayi"),
            "non_deductible": _candidate_group(accounts, ("689",), "KKEG adayi"),
        },
    )


def _decimal_or_none(value: str) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _single_vat_rate(invoice: ParsedInvoice) -> Decimal:
    if not invoice.vat_rates:
        return Decimal("0.00")
    return Decimal(invoice.vat_rates[0]) / Decimal("100")


def _vat_account_for_rate(
    candidates: tuple[dict[str, Any], ...] | None,
    *,
    rate: Decimal,
    fallback: str,
) -> str:
    rate_int = int((rate * Decimal("100")).quantize(Decimal("1"))) if rate else 0
    if not rate_int:
        return fallback
    padded = f"{rate_int:03d}"
    plain = str(rate_int)
    for candidate in candidates or ():
        haystack = f"{candidate.get('code', '')} {candidate.get('name', '')}".lower()
        if (
            haystack.endswith(padded)
            or f".{padded}" in haystack
            or f"%{plain}" in haystack
            or f"yuzde {plain}" in haystack
            or f"yüzde {plain}" in haystack
        ):
            return str(candidate.get("code") or fallback)
    return fallback


def _purchase_vat_account_for_rate(selection: AccountSelection, rate: Decimal) -> str:
    return _vat_account_for_rate(selection.account_candidates.get("purchase_vat"), rate=rate, fallback=selection.purchase_vat_account)


def _sales_vat_account_for_rate(selection: AccountSelection, rate: Decimal) -> str:
    return _vat_account_for_rate(selection.account_candidates.get("sales_vat"), rate=rate, fallback=selection.sales_vat_account)


def _candidate_accounts_as_chart_accounts(candidates: tuple[dict[str, Any], ...] | None) -> list[ChartAccount]:
    return [
        ChartAccount(
            raw_account_code=str(candidate.get("code") or ""),
            normalized_account_code=str(candidate.get("code") or ""),
            account_name=str(candidate.get("name") or candidate.get("code") or ""),
            is_detail_account=True,
        )
        for candidate in candidates or ()
        if str(candidate.get("code") or "").strip()
    ]


def _purchase_expense_account_for_line(selection: AccountSelection, raw_line: str) -> str:
    candidates = _candidate_accounts_as_chart_accounts(selection.account_candidates.get("purchase_expense"))
    selected = select_usage_account(candidates, raw_line, "purchase", account_treatment="expense")
    return selected.normalized_account_code if selected else selection.expense_account


def _purchase_stock_account_for_line(selection: AccountSelection, raw_line: str) -> str:
    candidates = _candidate_accounts_as_chart_accounts(selection.account_candidates.get("purchase_stock"))
    selected = select_usage_account(candidates, raw_line, "purchase", account_treatment="stock")
    return selected.normalized_account_code if selected else selection.stock_account


def _ai_retry_reason(*, ai_skipped_reason: str, ai_used: bool, ai_suggested_account_code: str, ai_research_requested: bool) -> str:
    if ai_suggested_account_code:
        return ""
    if ai_skipped_reason:
        return ai_skipped_reason
    if ai_research_requested:
        return "research_required"
    if ai_used:
        return "ai_account_missing"
    return "ai_not_resolved"


def _normalize_intended_direction(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("ı", "i").replace("ş", "s")
    if normalized in {"sales", "sales_invoice", "satis", "satis_faturasi", "satis faturasi"}:
        return "sales"
    if normalized in {"purchase", "purchase_invoice", "alis", "alis_faturasi", "alis faturasi"}:
        return "purchase"
    return ""


def _is_return_invoice(invoice: ParsedInvoice) -> bool:
    if getattr(invoice, "is_return_invoice", False):
        return True
    haystack = " ".join(
        (
            invoice.invoice_type,
            getattr(invoice, "invoice_type_code", ""),
            invoice.scenario,
            " ".join(invoice.risk_flags),
            " ".join(invoice.parse_notes),
        )
    ).upper()
    return "IADE" in haystack or "İADE" in haystack


def _only_digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _client_identifiers(client_profile: ClientProfile | None) -> tuple[str, ...]:
    if client_profile is None:
        return ()
    return tuple(
        dict.fromkeys(
            value
            for value in (
                client_profile.vkn,
                client_profile.tckn,
                client_profile.tax_identifier,
                client_profile.tax_id,
                client_profile.effective_tax_identifier,
            )
            if value
        )
    )


def _explicit_party_direction(
    invoice: ParsedInvoice,
    client_profile: ClientProfile | None,
) -> tuple[str, int, tuple[str, ...]] | None:
    identifiers = {_only_digits(identifier) for identifier in _client_identifiers(client_profile)}
    identifiers.discard("")
    if not identifiers:
        return None
    issuer_tax_id = _only_digits(getattr(invoice, "issuer_tax_id", ""))
    recipient_tax_id = _only_digits(getattr(invoice, "recipient_tax_id", ""))
    if issuer_tax_id and issuer_tax_id in identifiers:
        return "sales", 95, ("client_tax_id_matches_issuer",)
    if recipient_tax_id and recipient_tax_id in identifiers:
        return "purchase", 95, ("client_tax_id_matches_recipient",)
    return None


def _client_title_tokens(client_profile: ClientProfile | None) -> tuple[str, ...]:
    if client_profile is None:
        return ()
    return tuple(
        dict.fromkeys(
            normalize.strip()
            for normalize in (
                client_profile.effective_title,
                client_profile.title,
                client_profile.legal_name,
                client_profile.trade_name,
            )
            if normalize and normalize.strip()
        )
    )


def _line_mentions_client_after_sayin(invoice: ParsedInvoice, client_profile: ClientProfile | None) -> bool:
    titles = _client_title_tokens(client_profile)
    if not titles:
        return False
    for line in invoice.line_items:
        lowered = line.lower()
        if "sayin" not in lowered and "sayın" not in lowered:
            continue
        if any(title.lower() in lowered for title in titles):
            return True
    return False


def infer_accounting_direction(
    invoice: ParsedInvoice,
    client_profile: ClientProfile | None,
    *,
    intended_direction: str | None = None,
) -> tuple[str, int, tuple[str, ...]]:
    intended = _normalize_intended_direction(intended_direction)
    explicit_direction = _explicit_party_direction(invoice, client_profile)
    if _is_return_invoice(invoice):
        if explicit_direction:
            direction, confidence, evidence = explicit_direction
            return direction, confidence, tuple(dict.fromkeys((*evidence, "return_invoice_signal")))
        if intended:
            return intended, 88, (f"intake_category_{intended}", "return_invoice_signal")
        return "return_review", 100, ("return_invoice_signal",)
    if explicit_direction:
        return explicit_direction
    identifiers = _client_identifiers(client_profile)
    if not identifiers:
        if intended:
            return intended, 72, (f"intake_category_{intended}", "client_identity_missing")
        return "purchase", 40, ("client_identity_missing_purchase_fallback",)
    if _line_mentions_client_after_sayin(invoice, client_profile):
        return "purchase", 90, ("sayin_recipient_is_client",)
    if invoice.invoice_type.upper() in {"ALIS", "ALIŞ"}:
        return "purchase", 82, ("invoice_type_purchase",)
    if intended == "purchase" and invoice.invoice_type.upper() in {"SATIS", "SATIÅ"} and any(identifier in invoice.tax_ids for identifier in identifiers):
        return "purchase", 88, ("intake_category_purchase", "invoice_type_sales_supplier_perspective", "client_identifier_present")
    for identifier in identifiers:
        if not invoice.tax_ids:
            continue
        if invoice.tax_ids[0] == identifier:
            return "sales", 86, ("client_identifier_first_tax_id",)
        if identifier in invoice.tax_ids[1:]:
            return "purchase", 86, ("client_identifier_later_tax_id",)
    if invoice.invoice_type.upper() in {"SATIS", "SATIŞ"}:
        provider = invoice.provider_hint.lower()
        if provider and not any(title.lower() in provider for title in _client_title_tokens(client_profile)):
            return "purchase", 65, ("invoice_type_sales_but_issuer_not_client",)
        return "sales", 55, ("invoice_type_sales_fallback",)
    return "purchase", 55, ("purchase_fallback",)


def _direction_label_tr(direction: str) -> str:
    if direction == "sales":
        return "Satış"
    if direction == "purchase":
        return "Alış"
    return direction


def _direction_conflict_payload(
    *,
    intended_direction: str | None,
    detected_direction: str,
    confidence: int,
    evidence: tuple[str, ...],
) -> dict[str, object]:
    intended = _normalize_intended_direction(intended_direction)
    if intended not in {"sales", "purchase"} or detected_direction not in {"sales", "purchase"}:
        return {}
    if intended == detected_direction:
        return {}
    strong_identity_evidence = any(str(item).startswith("client_tax_id_matches_") for item in evidence)
    if confidence < 80 and not strong_identity_evidence:
        return {}
    intake_label = _direction_label_tr(intended)
    detected_label = _direction_label_tr(detected_direction)
    return {
        "status": "needs_review",
        "intake_direction": intended,
        "detected_direction": detected_direction,
        "confidence": confidence,
        "evidence": list(evidence),
        "question_tr": (
            f"Bu belge {intake_label}tan yüklendi; sistem mükellef açısından "
            f"{detected_label} olarak tespit etti. {detected_label} yönüne geçirilsin mi?"
        ),
    }


def _counterparty_tax_identifier(
    invoice: ParsedInvoice,
    client_profile: ClientProfile | None,
    *,
    direction: str,
) -> str:
    client_ids = {_only_digits(identifier) for identifier in _client_identifiers(client_profile)}
    client_ids.discard("")
    issuer_tax_id = _only_digits(getattr(invoice, "issuer_tax_id", ""))
    recipient_tax_id = _only_digits(getattr(invoice, "recipient_tax_id", ""))
    if direction == "sales" and recipient_tax_id and recipient_tax_id not in client_ids:
        return recipient_tax_id
    if direction != "sales" and issuer_tax_id and issuer_tax_id not in client_ids:
        return issuer_tax_id
    for tax_id in (_only_digits(value) for value in invoice.tax_ids):
        if tax_id and tax_id not in client_ids:
            return tax_id
    return ""


def _counterparty_creation_suggestion(
    direction: str,
    selection: AccountSelection,
    invoice: ParsedInvoice,
    client_profile: ClientProfile | None,
) -> tuple[str, dict[str, object]]:
    if direction == "sales":
        counterparty_tax_id = _counterparty_tax_identifier(invoice, client_profile, direction=direction)
        suggested = f"120.{counterparty_tax_id}" if counterparty_tax_id else selection.next_customer_account or selection.customer_account
        return suggested, {"type": "customer", "base_account": "120", "suggested_code": suggested, "always_suggest_new": True}
    counterparty_tax_id = _counterparty_tax_identifier(invoice, client_profile, direction=direction)
    suggested = f"320.{counterparty_tax_id}" if counterparty_tax_id else selection.next_supplier_account or selection.supplier_account
    return suggested, {"type": "supplier", "base_account": "320", "suggested_code": suggested, "always_suggest_new": True}


def _counterparty_title(
    invoice: ParsedInvoice,
    *,
    direction: str,
) -> str:
    if direction == "sales":
        return str(getattr(invoice, "recipient_title", "") or "").strip()
    return str(getattr(invoice, "issuer_title", "") or invoice.provider_hint or "").strip()


def _counterparty_identity_key(
    *,
    direction: str,
    tax_id: str,
    title: str,
) -> str:
    if tax_id:
        return f"{direction}|tax:{tax_id}"
    normalized_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{direction}|title:{normalized_title}" if normalized_title else ""


_COUNTERPARTY_LEGAL_NOISE = {
    "anonim",
    "as",
    "limited",
    "ltd",
    "sirketi",
    "sti",
    "ticaret",
    "ve",
}


def _normalized_title_tokens(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value).replace(".", " ")
    return tuple(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) >= 3 and token not in _COUNTERPARTY_LEGAL_NOISE
        )
    )


def _counterparty_direction_groups(direction: str) -> tuple[str, ...]:
    return ("customer",) if direction == "sales" else ("supplier",)


def _counterparty_invoice_payload(
    invoice: ParsedInvoice,
    *,
    direction: str,
    direction_confidence: int,
    direction_evidence: tuple[str, ...],
    counterparty_title: str,
    counterparty_tax_id: str,
) -> dict[str, object]:
    return {
        "direction": direction,
        "direction_confidence": direction_confidence,
        "direction_evidence": list(direction_evidence),
        "counterparty_title": counterparty_title,
        "counterparty_tax_id": counterparty_tax_id,
        "issuer_title": str(getattr(invoice, "issuer_title", "") or "").strip(),
        "issuer_tax_id": str(getattr(invoice, "issuer_tax_id", "") or "").strip(),
        "recipient_title": str(getattr(invoice, "recipient_title", "") or "").strip(),
        "recipient_tax_id": str(getattr(invoice, "recipient_tax_id", "") or "").strip(),
        "provider_hint": invoice.provider_hint,
        "normalized_title_tokens": list(_normalized_title_tokens(counterparty_title)),
        "raw_title_candidates": [
            value
            for value in (
                str(getattr(invoice, "issuer_title", "") or "").strip(),
                str(getattr(invoice, "recipient_title", "") or "").strip(),
                invoice.provider_hint.strip(),
            )
            if value
        ],
    }


def _counterparty_candidate_details(
    *,
    selection: AccountSelection,
    direction: str,
    counterparty_candidates: tuple[str, ...],
    counterparty_title: str,
    counterparty_tax_id: str,
    suggested_counterparty: str,
    counterparty_match: CounterpartyMatch | None,
) -> tuple[dict[str, object], ...]:
    source_groups = _counterparty_direction_groups(direction)
    by_code: dict[str, tuple[str, dict[str, Any]]] = {}
    for group in source_groups:
        for candidate in selection.account_candidates.get(group, ()):
            code = str(candidate.get("code") or "").strip()
            if code and code not in by_code:
                by_code[code] = (group, candidate)
    title_tokens = set(_normalized_title_tokens(counterparty_title))
    details: list[dict[str, object]] = []
    fallback_group = source_groups[0]
    for code in counterparty_candidates:
        group, candidate = by_code.get(code, (fallback_group, {}))
        name = str(candidate.get("name") or "").strip()
        if not name and counterparty_match and code == counterparty_match.account_code:
            name = counterparty_match.account_name
        if not name and code == suggested_counterparty:
            name = counterparty_title or "Yeni cari onerisi"
        candidate_tokens = set(_normalized_title_tokens(name))
        evidence: list[str] = []
        reason = str(candidate.get("reason") or "").strip()
        if reason:
            evidence.append(reason)
        if title_tokens and candidate_tokens and title_tokens & candidate_tokens:
            evidence.append("title_token_overlap")
        if counterparty_match and code == counterparty_match.account_code and counterparty_match.match_reason:
            evidence.append(f"counterparty_match_{counterparty_match.match_reason}")
        if counterparty_tax_id and code == suggested_counterparty and counterparty_tax_id in code:
            evidence.append("tax_id_suggested_new_account")
        details.append(
            {
                "code": code,
                "name": name,
                "counterparty_type": "customer" if group == "customer" else "supplier",
                "source_group": group,
                "candidate_type": "new_counterparty_suggestion"
                if code == suggested_counterparty and code not in by_code
                else "existing_counterparty",
                "normalized_name_tokens": list(candidate_tokens),
                "evidence": list(dict.fromkeys(evidence)),
            }
        )
    return tuple(details)


def _counterparty_account_description(
    *,
    account: str,
    suggested_counterparty: str,
    counterparty_match: CounterpartyMatch | None,
    base_description: str,
) -> str:
    if account and account == suggested_counterparty and not (counterparty_match and counterparty_match.account_code):
        return f"Yeni cari onerisi - {base_description}"
    return base_description


def _selected_sales_customer_account(
    *,
    selection: AccountSelection,
    suggested_counterparty: str,
    counterparty_match: CounterpartyMatch | None,
) -> str:
    if counterparty_match and counterparty_match.account_code:
        return counterparty_match.account_code
    return suggested_counterparty or selection.customer_account


def _selected_purchase_supplier_account(
    *,
    selection: AccountSelection,
    suggested_counterparty: str,
    counterparty_match: CounterpartyMatch | None,
) -> str:
    if counterparty_match and counterparty_match.account_code:
        return counterparty_match.account_code
    return suggested_counterparty or selection.supplier_account


def _counterparty_requires_review(counterparty_match: CounterpartyMatch | None, counterparty_creation_suggestion: dict[str, object] | None) -> bool:
    if counterparty_match and counterparty_match.requires_review:
        return True
    return counterparty_match is None and bool(counterparty_creation_suggestion)


def _counterparty_match_for_invoice(
    accounts: list[ChartAccount],
    invoice: ParsedInvoice,
    client_profile: ClientProfile | None,
) -> CounterpartyMatch | None:
    if not accounts:
        return None
    identifiers = {_only_digits(identifier) for identifier in _client_identifiers(client_profile)}
    identifiers.discard("")
    issuer_tax_id = _only_digits(getattr(invoice, "issuer_tax_id", ""))
    recipient_tax_id = _only_digits(getattr(invoice, "recipient_tax_id", ""))
    if issuer_tax_id and issuer_tax_id in identifiers:
        return match_counterparty(
            accounts,
            tax_ids=(recipient_tax_id,),
            name_hint=getattr(invoice, "recipient_title", ""),
            account_prefixes=("120",),
        )
    if recipient_tax_id and recipient_tax_id in identifiers:
        return match_counterparty(
            accounts,
            tax_ids=(issuer_tax_id,),
            name_hint=getattr(invoice, "issuer_title", "") or invoice.provider_hint,
            account_prefixes=("320",),
        )
    return match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint)


def _sales_revenue_account(selection: AccountSelection, vat_rate: Decimal) -> str:
    if vat_rate == Decimal("0.00"):
        return selection.zero_vat_revenue_account or selection.revenue_account
    return selection.revenue_account


def _accountant_explanation(
    *,
    direction: str,
    direction_evidence: tuple[str, ...],
    invoice: ParsedInvoice,
    revenue_account: str,
    expense_account: str,
    purchase_vat_account: str,
    sales_vat_account: str,
    suggested_counterparty: str,
    draft_quality: str,
) -> str:
    vat_split_note = ""
    if len(invoice.vat_rates) > 1:
        if draft_quality.startswith("mixed_vat") and str(invoice.vat_split_status or "") in {"exact", "derived"}:
            vat_split_note = f" KDV ayrimi {invoice.vat_split_status}; fise oran bazli uygulandi."
        elif draft_quality == "gross_balanced_needs_vat_split":
            vat_split_note = " KDV oranlari var ama tutar ayrimi guvenli degil; brut kontrol fisi uretildi."
        else:
            vat_split_note = " KDV oranlari var; ayrim kontrol gerekcesinde gosterildi."
    if direction == "return_review":
        return "Iade sinyali bulundu. Bu fazda otomatik fis uretilmedi; belge iade kontrol kuyrugunda tutulmali."
    if direction == "sales":
        vat_text = ", ".join(invoice.vat_rates) or "yok"
        vat_account_text = sales_vat_account or "KDV satiri yok"
        return (
            f"Belge satis/gelir olarak yorumlandi ({', '.join(direction_evidence)}). "
            f"KDV oranlari: {vat_text}. Gelir hesabi: {revenue_account}. "
            f"Hesaplanan KDV hesabi: {vat_account_text}. Cari onerisi: {suggested_counterparty}."
            f"{vat_split_note}"
        )
    return (
        f"Belge alis/gider olarak yorumlandi ({', '.join(direction_evidence)}). "
        f"Gider/stok hesabi: {expense_account}. Indirilecek KDV hesabi: {purchase_vat_account}. "
        f"Cari onerisi: {suggested_counterparty}."
        f"{vat_split_note}"
    )


def _gross_review_entry(
    invoice: ParsedInvoice,
    selection: AccountSelection,
    supplier_account: str,
    *,
    expense_account: str | None = None,
    supplier_description: str = "Kontrol bekleyen satici cari",
) -> JournalEntry:
    total = money(invoice.payable_total)
    return JournalEntry(
        entry_type="review_purchase",
        entry_date=invoice.issue_date or "1900-01-01",
        description=f"Kontrol gerekli fatura {invoice.file_name}",
        lines=(
            JournalLine(expense_account or selection.expense_account, "Kontrol bekleyen gider taslagi", debit=total, document_ref=invoice.file_name),
            JournalLine(supplier_account, supplier_description, credit=total, document_ref=invoice.file_name),
        ),
        risk_flags=invoice.risk_flags,
    )


def _gross_sales_review_entry(
    invoice: ParsedInvoice,
    *,
    revenue_account: str,
    customer_account: str,
    customer_description: str = "Kontrol bekleyen alici cari",
) -> JournalEntry:
    total = money(invoice.payable_total)
    return JournalEntry(
        entry_type="review_sales",
        entry_date=invoice.issue_date or "1900-01-01",
        description=f"Kontrol gerekli satis faturasi {invoice.file_name}",
        lines=(
            JournalLine(customer_account, customer_description, debit=total, document_ref=invoice.file_name),
            JournalLine(revenue_account, "Kontrol bekleyen satis geliri", credit=total, document_ref=invoice.file_name),
        ),
        risk_flags=invoice.risk_flags,
    )


def _money_hint(value: str) -> Decimal | None:
    compact = str(value or "").strip().replace(" ", "")
    compact = re.sub(r"(?:TL|TRY)$", "", compact, flags=re.IGNORECASE)
    if "," in compact:
        raw = compact.replace(".", "").replace(",", ".")
    elif "." in compact and len(compact.rsplit(".", 1)[-1]) <= 2:
        raw = compact
    else:
        raw = compact.replace(".", "")
    try:
        return money(raw)
    except (InvalidOperation, ValueError):
        return None


def _money_values_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= MONEY_TOLERANCE


def _line_detail_money(line: object, field_name: str) -> Decimal | None:
    return _money_hint(str(getattr(line, field_name, "") or ""))


def _line_detail_gross_amount(line: object) -> Decimal | None:
    gross = _line_detail_money(line, "gross_amount")
    if gross is not None and gross > Decimal("0.00"):
        return gross
    taxable = _line_detail_money(line, "taxable_amount")
    tax = _line_detail_money(line, "tax_amount")
    if taxable is not None and tax is not None:
        return (taxable + tax).quantize(Decimal("0.01"))
    amount = _line_detail_money(line, "amount_hint")
    if amount is not None and amount > Decimal("0.00"):
        return amount
    return None


def _line_detail_vat_rate(line: object) -> str:
    explicit = str(getattr(line, "vat_rate", "") or "").strip()
    if explicit:
        return str(int(explicit)) if explicit.isdigit() else explicit
    haystack = " ".join(
        str(getattr(line, field_name, "") or "")
        for field_name in ("description", "raw_text")
    )
    match = re.search(r"%\s*(0|1|10|20)(?:[,.]0+)?\b", haystack)
    return str(int(match.group(1))) if match else ""


def _line_detail_amounts(invoice: ParsedInvoice) -> tuple[Decimal, ...]:
    amounts: list[Decimal] = []
    for line in getattr(invoice, "line_item_details", ()) or ():
        amount = _line_detail_gross_amount(line)
        if amount and amount > Decimal("0.00"):
            amounts.append(amount)
    return tuple(amounts)


def _line_detail_group_amounts(invoice: ParsedInvoice) -> dict[str, dict[str, Decimal]]:
    grouped: dict[str, dict[str, Decimal]] = {}
    for line in getattr(invoice, "line_item_details", ()) or ():
        rate = _line_detail_vat_rate(line)
        if not rate:
            continue
        if rate not in VALID_PURCHASE_VAT_RATES:
            return {}
        gross = _line_detail_gross_amount(line)
        if gross is None:
            continue
        bucket = grouped.setdefault(rate, {"gross": Decimal("0.00"), "taxable": Decimal("0.00"), "tax": Decimal("0.00")})
        bucket["gross"] += gross
        taxable = _line_detail_money(line, "taxable_amount")
        tax = _line_detail_money(line, "tax_amount")
        if taxable is not None:
            bucket["taxable"] += taxable
        if tax is not None:
            bucket["tax"] += tax
    return grouped


def _has_structured_line_vat_details(invoice: ParsedInvoice) -> bool:
    for line in getattr(invoice, "line_item_details", ()) or ():
        if any(
            str(getattr(line, field_name, "") or "").strip()
            for field_name in ("vat_rate", "taxable_amount", "tax_amount", "gross_amount")
        ):
            return True
    return False


def _vat_split_summary_by_rate(invoice: ParsedInvoice) -> dict[str, dict[str, Decimal]]:
    summary: dict[str, dict[str, Decimal]] = {}
    for line in getattr(invoice, "vat_split_lines", ()) or ():
        rate = str(getattr(line, "rate", "") or "").strip()
        taxable = _money_hint(str(getattr(line, "taxable_amount", "") or ""))
        tax = _money_hint(str(getattr(line, "tax_amount", "") or ""))
        if not rate or taxable is None or tax is None:
            continue
        bucket = summary.setdefault(rate, {"taxable": Decimal("0.00"), "tax": Decimal("0.00"), "gross": Decimal("0.00")})
        bucket["taxable"] += taxable
        bucket["tax"] += tax
        bucket["gross"] += (taxable + tax).quantize(Decimal("0.01"))
    return summary


def _grouped_line_amounts_validate(invoice: ParsedInvoice, grouped: dict[str, dict[str, Decimal]]) -> bool:
    if not grouped:
        return False
    invoice_rates = {str(rate) for rate in invoice.vat_rates}
    if invoice_rates and set(grouped) != invoice_rates:
        return False
    split_summary = _vat_split_summary_by_rate(invoice)
    for rate, summary_values in split_summary.items():
        group = grouped.get(rate)
        if not group:
            return False
        if not _money_values_match(group["taxable"], summary_values["taxable"]):
            return False
        if not _money_values_match(group["tax"], summary_values["tax"]):
            return False
    total_taxable = sum((values["taxable"] for values in grouped.values()), Decimal("0.00"))
    total_tax = sum((values["tax"] for values in grouped.values()), Decimal("0.00"))
    total_gross = sum((values["gross"] for values in grouped.values()), Decimal("0.00"))
    goods_total = _money_hint(invoice.goods_services_total)
    vat_total = _money_hint(invoice.vat_total)
    payable_total = _money_hint(invoice.payable_total) or _money_hint(invoice.tax_inclusive_total)
    if goods_total is not None and total_taxable and not _money_values_match(total_taxable, goods_total):
        return False
    if vat_total is not None and total_tax and not _money_values_match(total_tax, vat_total):
        return False
    if payable_total is not None and not _money_values_match(total_gross, payable_total):
        return False
    return True


def _vat_split_summary_validate(invoice: ParsedInvoice, summary: dict[str, dict[str, Decimal]]) -> bool:
    if str(getattr(invoice, "vat_split_status", "") or "") not in {"exact", "derived"}:
        return False
    return _grouped_line_amounts_validate(invoice, summary)


def _mixed_vat_items_from_grouped_amounts(
    grouped: dict[str, dict[str, Decimal]],
    selection: AccountSelection,
    *,
    direction: str,
    purchase_account: str,
) -> tuple[tuple[str, Decimal, Decimal, str], ...]:
    items: list[tuple[str, Decimal, Decimal, str]] = []
    for raw_rate in sorted(grouped, key=lambda value: Decimal(str(value).replace(",", "."))):
        rate = Decimal(raw_rate.replace(",", ".")) / Decimal("100")
        gross_amount = grouped[raw_rate]["gross"].quantize(Decimal("0.01"))
        if direction == "sales":
            revenue_account = _sales_revenue_account(selection, rate)
            if rate > Decimal("0.00"):
                revenue_account = _vat_account_for_rate(
                    selection.account_candidates.get("sales_revenue"),
                    rate=rate,
                    fallback=revenue_account,
                )
            vat_account = _sales_vat_account_for_rate(selection, rate)
            items.append((revenue_account, gross_amount, rate, vat_account))
        else:
            vat_account = _purchase_vat_account_for_rate(selection, rate)
            items.append((purchase_account, gross_amount, rate, vat_account))
    return tuple(items)


def _line_detail_text(invoice: ParsedInvoice, index: int) -> str:
    details = tuple(getattr(invoice, "line_item_details", ()) or ())
    if index < len(details):
        detail = details[index]
        return " ".join(
            part
            for part in (
                getattr(detail, "description", ""),
                getattr(detail, "raw_text", ""),
            )
            if part
        )
    if index < len(invoice.line_items):
        return invoice.line_items[index]
    return _product_line_hint(invoice)


def _is_hearing_device_line(text: str) -> bool:
    return classify_product_line(text).category == "isitme_cihazi"


def _sales_hearing_device_vat_review_needed(invoice: ParsedInvoice) -> bool:
    rates: list[Decimal] = []
    for raw_rate in invoice.vat_rates:
        try:
            rates.append(Decimal(str(raw_rate).strip().replace(",", ".")))
        except InvalidOperation:
            rates.append(Decimal("0"))
    if not any(rate > Decimal("0") for rate in rates):
        return False
    line_count = max(len(invoice.line_items), len(tuple(getattr(invoice, "line_item_details", ()) or ())))
    line_texts = [
        _line_detail_text(invoice, index)
        for index in range(max(line_count, 1))
    ]
    if line_count == len(rates):
        return any(
            rate > Decimal("0") and _is_hearing_device_line(line_texts[index])
            for index, rate in enumerate(rates)
        )
    return any(_is_hearing_device_line(line_text) for line_text in line_texts)


def _mixed_vat_items_from_lines(
    invoice: ParsedInvoice,
    selection: AccountSelection,
    *,
    direction: str,
    purchase_account: str,
) -> tuple[tuple[str, Decimal, Decimal, str], ...]:
    grouped = _line_detail_group_amounts(invoice)
    if grouped and _grouped_line_amounts_validate(invoice, grouped):
        return _mixed_vat_items_from_grouped_amounts(
            grouped,
            selection,
            direction=direction,
            purchase_account=purchase_account,
        )
    split_summary = _vat_split_summary_by_rate(invoice)
    if split_summary and _vat_split_summary_validate(invoice, split_summary):
        return _mixed_vat_items_from_grouped_amounts(
            split_summary,
            selection,
            direction=direction,
            purchase_account=purchase_account,
        )
    if _has_structured_line_vat_details(invoice):
        return ()

    amounts = _line_detail_amounts(invoice)
    if not amounts or len(amounts) != len(invoice.vat_rates):
        return ()
    items: list[tuple[str, Decimal, Decimal, str]] = []
    for index, raw_rate in enumerate(invoice.vat_rates):
        rate = Decimal(raw_rate) / Decimal("100")
        if direction == "sales":
            line_text = _line_detail_text(invoice, index)
            line_is_hearing_device = _is_hearing_device_line(line_text)
            effective_rate = Decimal("0.00") if line_is_hearing_device else rate
            revenue_account = _sales_revenue_account(selection, effective_rate)
            if effective_rate > Decimal("0.00"):
                revenue_account = _vat_account_for_rate(
                    selection.account_candidates.get("sales_revenue"),
                    rate=effective_rate,
                    fallback=revenue_account,
                )
            vat_account = _sales_vat_account_for_rate(selection, effective_rate)
            items.append((revenue_account, amounts[index], effective_rate, vat_account))
        else:
            vat_account = _purchase_vat_account_for_rate(selection, rate)
            items.append((purchase_account, amounts[index], rate, vat_account))
    return tuple(items)


def _account_names_from_selection(
    selection: AccountSelection,
    counterparty_match: CounterpartyMatch | None = None,
) -> dict[str, str]:
    names: dict[str, str] = {}
    for candidates in selection.account_candidates.values():
        for candidate in candidates:
            code = str(candidate.get("code") or "").strip()
            name = str(candidate.get("name") or "").strip()
            if code and name:
                names[code] = name
    if counterparty_match:
        code = str(counterparty_match.account_code or "").strip()
        name = str(counterparty_match.account_name or "").strip()
        if code and name:
            names.setdefault(code, name)
    return names


def _entry_lines(entry: JournalEntry | None, account_names: dict[str, str] | None = None) -> tuple[dict[str, str], ...]:
    if entry is None:
        return ()
    names = account_names or {}
    return tuple(
        {
            "account_code": line.account_code,
            "description": names.get(line.account_code, ""),
            "debit": f"{line.debit:.2f}",
            "credit": f"{line.credit:.2f}",
        }
        for line in entry.lines
    )


def _normalize_processing_mode(mode: str | None) -> ProcessingMode:
    if mode in {"conservative", "ai_assisted_draft", "controlled_automation"}:
        return mode  # type: ignore[return-value]
    return "controlled_automation"


def _product_line_hint(invoice: ParsedInvoice) -> str:
    return invoice.line_items[0] if invoice.line_items else invoice.provider_hint or invoice.invoice_type or invoice.file_name


def _ai_policy_from_classifier(product_classifier: ProductClassifier | None) -> AiClassificationPolicy:
    policy = getattr(product_classifier, "policy", None)
    return policy if isinstance(policy, AiClassificationPolicy) else AiClassificationPolicy()


def _account_family_for_ai(code: str) -> str:
    compact = str(code or "").strip()
    if not compact:
        return ""
    family = compact.split(".")[0]
    if family.startswith("25"):
        return "25"
    return family


def _is_main_account_candidate(detail: dict[str, Any]) -> bool:
    group = str(detail.get("group") or "")
    if group in {"customer", "supplier", "purchase_vat", "sales_vat"}:
        return False
    return bool(str(detail.get("code") or "").strip())


def _is_family_stage_candidate(detail: dict[str, Any]) -> bool:
    group = str(detail.get("group") or "")
    if group in {"customer", "supplier"}:
        return False
    return bool(str(detail.get("code") or "").strip())


def _direction_role_for_group(group: str) -> str:
    if group in {"purchase_stock", "fixed_asset", "purchase_expense", "non_deductible"}:
        return "purchase_account"
    if group == "purchase_vat":
        return "purchase_vat"
    if group in {"sales_revenue", "zero_vat_revenue"}:
        return "sales_account"
    if group == "sales_vat":
        return "sales_vat"
    return "account"


def _account_family_candidates(details: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    families: dict[str, dict[str, Any]] = {}
    for detail in details:
        if not _is_family_stage_candidate(detail):
            continue
        code = str(detail.get("code") or "").strip()
        family = _account_family_for_ai(code)
        if not family:
            continue
        record = families.setdefault(
            family,
            {
                "family": family,
                "label": str(detail.get("name") or "").strip() or family,
                "direction_role": _direction_role_for_group(str(detail.get("group") or "").strip()),
                "groups": [],
                "candidate_count": 0,
                "examples": [],
            },
        )
        group = str(detail.get("group") or "").strip()
        if group and group not in record["groups"]:
            record["groups"].append(group)
        record["candidate_count"] = int(record["candidate_count"]) + 1
        examples = record["examples"]
        if isinstance(examples, list) and len(examples) < 3:
            examples.append(f"{code} {str(detail.get('name') or '').strip()}".strip())
    return tuple(families.values())


def _fallback_account_families(direction: str) -> tuple[str, ...]:
    if direction == "sales":
        return ("600", "601", "602")
    return ("153", "15", "25", "740", "750", "760", "770", "780", "689")


def _filter_context_for_families(
    context: AiClassificationContext,
    *,
    selected_families: tuple[str, ...],
    policy: AiClassificationPolicy,
) -> AiClassificationContext:
    allowed = set(selected_families)
    details = tuple(
        detail
        for detail in context.account_candidate_details
        if _is_main_account_candidate(detail) and _account_family_for_ai(str(detail.get("code") or "")) in allowed
    )
    account_candidates = tuple(
        dict.fromkeys(str(detail.get("code") or "").strip() for detail in details if str(detail.get("code") or "").strip())
    )
    return replace(
        context,
        account_candidates=account_candidates,
        account_candidate_details=details,
        account_candidate_limit=len(account_candidates),
        counterparty_candidate_limit=policy.counterparty_limit,
        account_candidate_details_limit=len(details),
        candidate_strategy=AiCandidateStrategy(
            mode="two_stage",
            stage="final_account",
            account_candidate_count=len(account_candidates),
            counterparty_candidate_count=len(context.counterparty_candidates),
            selected_families=selected_families,
        ),
    )


def _counterparty_resolution_context(
    context: AiClassificationContext,
    *,
    policy: AiClassificationPolicy,
    mode: str,
) -> AiClassificationContext:
    return replace(
        context,
        account_candidates=(),
        account_candidate_details=(),
        account_candidate_limit=0,
        account_candidate_details_limit=0,
        counterparty_candidate_limit=len(context.counterparty_candidates),
        candidate_strategy=AiCandidateStrategy(
            mode=mode,
            stage="counterparty_resolve",
            account_candidate_count=0,
            counterparty_candidate_count=len(context.counterparty_candidates),
        ),
    )


def _stage_evidence(result: AiClassificationResult, *, fallback_reason: str = "") -> dict[str, object]:
    strategy = result.candidate_strategy
    return {
        "ai_stage": strategy.stage,
        "candidate_strategy": strategy.mode,
        "account_candidate_count": strategy.account_candidate_count,
        "counterparty_candidate_count": strategy.counterparty_candidate_count,
        "input_chars": result.estimated_input_chars,
        "selected_account_families": list(result.selected_account_families or strategy.selected_families),
        "selected_account_code": result.suggested_account_code,
        "selected_counterparty_code": result.suggested_counterparty_code,
        "fallback_reason": fallback_reason or result.skipped_reason,
    }


def _ai_context(
    *,
    invoice: ParsedInvoice,
    selection: AccountSelection,
    client_profile: ClientProfile | None,
    counterparty_match: CounterpartyMatch | None,
    direction: str,
    direction_confidence: int,
    direction_evidence: tuple[str, ...],
    suggested_counterparty: str,
    counterparty_title: str,
    counterparty_tax_id: str,
) -> AiClassificationContext:
    direction_uncertainty = direction_confidence < 70
    if direction_uncertainty:
        main_groups = {"sales_revenue", "zero_vat_revenue", "purchase_stock", "purchase_expense", "non_deductible", "fixed_asset"}
    elif direction == "sales":
        main_groups = {"sales_revenue", "zero_vat_revenue"}
    else:
        main_groups = {"purchase_stock", "purchase_expense", "non_deductible", "fixed_asset"}
    semantic_candidates = tuple(
        str(candidate.get("code") or "").strip()
        for group, candidates in (selection.account_candidates or {}).items()
        for candidate in candidates
        if group in main_groups
        if str(candidate.get("code") or "").strip()
    )
    if direction_uncertainty:
        base_account_codes = (
            selection.revenue_account,
            selection.zero_vat_revenue_account,
            selection.stock_account,
            selection.expense_account,
            selection.non_deductible_account,
        )
    elif direction == "sales":
        base_account_codes = (selection.revenue_account, selection.zero_vat_revenue_account)
    else:
        base_account_codes = (selection.stock_account, selection.expense_account, selection.non_deductible_account)
    account_candidates = tuple(
        dict.fromkeys(
            code
            for code in (
                *base_account_codes,
                *semantic_candidates,
            )
            if code
        )
    )
    account_candidate_details = tuple(
        {
            "code": str(candidate.get("code") or "").strip(),
            "name": str(candidate.get("name") or "").strip(),
            "family": str(candidate.get("code") or "").strip().split(".")[0],
            "group": str(group),
            "reason": str(candidate.get("reason") or "").strip(),
            "semantic_roles": list(candidate.get("semantic_roles") or []),
            "vat_rate": str(candidate.get("vat_rate") or "").strip(),
        }
        for group, candidates in (selection.account_candidates or {}).items()
        for candidate in candidates
        if str(candidate.get("code") or "").strip()
    )
    counterparty_candidates = tuple(
        dict.fromkeys(
            code
            for code in (
                counterparty_match.account_code if counterparty_match else "",
                suggested_counterparty,
                selection.customer_account if direction == "sales" else selection.supplier_account,
                *(
                    str(candidate.get("code") or "").strip()
                    for candidate in selection.account_candidates.get("supplier" if direction != "sales" else "customer", ())
                    if str(candidate.get("code") or "").strip()
                ),
            )
            if code
        )
    )
    counterparty_candidate_details = _counterparty_candidate_details(
        selection=selection,
        direction=direction,
        counterparty_candidates=counterparty_candidates,
        counterparty_title=counterparty_title,
        counterparty_tax_id=counterparty_tax_id,
        suggested_counterparty=suggested_counterparty,
        counterparty_match=counterparty_match,
    )
    return AiClassificationContext(
        client_activity=client_profile.activity_description if client_profile else "",
        nace_code=client_profile.nace_code if client_profile else "",
        nace_research_summary=str((client_profile.nace_research_profile if client_profile else {}).get("scope_summary") or ""),
        activity_tags=client_profile.activity_tags if client_profile else (),
        accounting_direction=direction,
        direction_confidence=direction_confidence,
        direction_evidence=direction_evidence,
        direction_uncertainty=direction_uncertainty,
        account_candidates=account_candidates,
        account_candidate_details=account_candidate_details,
        counterparty_candidates=counterparty_candidates,
        counterparty_candidate_details=counterparty_candidate_details,
        invoice_counterparty=_counterparty_invoice_payload(
            invoice,
            direction=direction,
            direction_confidence=direction_confidence,
            direction_evidence=direction_evidence,
            counterparty_title=counterparty_title,
            counterparty_tax_id=counterparty_tax_id,
        ),
    )


def _not_assessed_relevance(raw_line: str) -> BusinessRelevance:
    classification = ProductClassification(
        raw_line=raw_line,
        category="not_assessed",
        confidence=0,
        evidence=("client_profile_not_provided",),
    )
    return BusinessRelevance(
        status="supheli",
        confidence=0,
        reason="Mukellef faaliyet profili verilmedigi icin is alani uygunlugu degerlendirilmedi.",
        evidence=("client_profile_not_provided",),
        classification=classification,
    )


def _deterministic_checks(
    *,
    entry: JournalEntry | None,
    invoice: ParsedInvoice,
    amount: Decimal | None,
    counterparty_match: CounterpartyMatch | None,
    client_profile: ClientProfile | None,
) -> tuple[str, ...]:
    checks: list[str] = []
    checks.append("amount_positive" if amount is not None and amount > 0 else "amount_requires_review")
    checks.append("single_vat_rate" if len(invoice.vat_rates) <= 1 else "mixed_vat_requires_review")
    checks.append("balanced_entry" if entry and entry.is_balanced else "balanced_entry_missing")
    if counterparty_match and counterparty_match.account_code and not counterparty_match.requires_review:
        checks.append("counterparty_matched")
    elif counterparty_match and counterparty_match.account_code:
        checks.append("counterparty_low_confidence")
    else:
        checks.append("counterparty_missing")
    checks.append("client_onboarding_ready" if client_profile and check_client_onboarding(client_profile).is_ready else "client_onboarding_incomplete")
    return tuple(checks)


def _draft_decision_source(*, ai_used: bool, processing_mode: ProcessingMode) -> str:
    if ai_used:
        return "ai_assisted_classification"
    if processing_mode == "ai_assisted_draft":
        return "static_rules_ai_assisted_draft"
    if processing_mode == "conservative":
        return "static_rules_conservative_review"
    return "deterministic_rules"


def _export_gate_reason(
    *,
    export_status: str,
    processing_mode: ProcessingMode,
    review_reasons: tuple[str, ...],
    relevance: BusinessRelevance,
    counterparty_match: CounterpartyMatch | None,
    entry: JournalEntry | None,
) -> str:
    if processing_mode == "conservative":
        return "Conservative mod: mustavir onayi olmadan export kapali."
    if processing_mode == "ai_assisted_draft":
        return "AI assisted draft modu: fis taslagi hazir, mustavir onayi olmadan export kapali."
    if not entry or not entry.is_balanced:
        return "Fis dengeli degil veya taslak satirlari eksik."
    if counterparty_match and counterparty_match.requires_review:
        return f"Cari eslesmesi kontrol istiyor: {counterparty_match.match_reason}."
    if review_reasons:
        return f"Review nedeni: {', '.join(review_reasons)}."
    if relevance.status == "is_alani_disi":
        return "Kalem faaliyet disi riski tasiyor."
    if relevance.status == "supheli":
        return "Kalem faaliyet profiliyle net eslesmedi."
    if export_status != "export_ready":
        return "Mustavir politikasi veya risk kapisi export onayi istiyor."
    return "Deterministik kontroller temiz; export paketine alinabilir."


def _draft_confidence(
    *,
    entry: JournalEntry | None,
    amount: Decimal | None,
    direction_confidence: int,
    counterparty_match: CounterpartyMatch | None,
    review_reasons: tuple[str, ...],
) -> int:
    score = 35
    if amount is not None and amount > 0:
        score += 15
    if entry and entry.is_balanced:
        score += 20
    if direction_confidence >= 70:
        score += 15
    if counterparty_match and counterparty_match.account_code and not counterparty_match.requires_review:
        score += 10
    elif counterparty_match and counterparty_match.account_code:
        score += 5
    score -= min(len(review_reasons) * 5, 25)
    return max(10, min(score, 95))


def _review_blockers(
    *,
    review_reasons: tuple[str, ...],
    deterministic_checks: tuple[str, ...],
    counterparty_match: CounterpartyMatch | None,
    counterparty_creation_suggestion: dict[str, object] | None,
) -> tuple[str, ...]:
    blockers = list(review_reasons)
    if counterparty_match is None and counterparty_creation_suggestion:
        blockers.append("counterparty_missing")
    if "balanced_entry_missing" in deterministic_checks:
        blockers.append("balanced_entry_missing")
    if "amount_requires_review" in deterministic_checks:
        blockers.append("amount_requires_review")
    return tuple(dict.fromkeys(blockers))


def _automation_eligibility(*, export_status: str, mode: ProcessingMode, blockers: tuple[str, ...]) -> str:
    if export_status != "export_ready":
        return "not_eligible"
    if mode == "controlled_automation" and not blockers:
        return "eligible_after_policy"
    return "candidate"


def _accountant_action_hint(*, export_status: str, blockers: tuple[str, ...], draft_lines: tuple[dict[str, str], ...]) -> str:
    if export_status == "export_ready":
        return "Tek tik onay veya cikti listesine alma icin hazir."
    if "counterparty_missing" in blockers:
        return "Fis taslagi hazir; yeni cari onerisi mustavir onayi bekliyor."
    if not draft_lines:
        return "Belge manuel kontrol istiyor; fis satirlari tamamlanmali."
    return "Fis taslagi hazir; mustavir onayi veya kucuk duzeltme bekliyor."


def _primary_suggestion(
    *,
    direction: str,
    counterparty_account: str,
    suggested_counterparty: str,
    expense_account: str,
    revenue_account: str,
    vat_account: str,
    draft_lines: tuple[dict[str, str], ...],
    ai_reason: str,
    export_gate_reason: str,
) -> dict[str, object]:
    return {
        "direction": direction,
        "counterparty_account": counterparty_account or suggested_counterparty,
        "account": revenue_account if direction == "sales" else expense_account,
        "vat_account": vat_account,
        "draft_lines": list(draft_lines),
        "reason": ai_reason,
        "export_gate_reason": export_gate_reason,
    }


def _ai_quality_scorecard(
    *,
    raw_line: str,
    supplier_hint: str,
    relevance: BusinessRelevance,
    ai_used: bool,
    ai_provider: str,
    ai_skipped_reason: str,
    ai_reason: str,
    ai_suggested_account_code: str,
    ai_suggested_counterparty_code: str,
    ai_product_identity: str,
    ai_research_requested: bool,
    ai_research_query: str,
    ai_risk_flags: tuple[str, ...],
    client_profile: ClientProfile | None,
    selected_account_code: str,
    selected_vat_account: str,
    selected_counterparty_account: str,
    direction: str,
    direction_confidence: int,
    deterministic_checks: tuple[str, ...],
    export_status: str,
    review_reason_codes: tuple[str, ...],
    draft_confidence: int,
    ai_account_candidate_count: int,
    ai_counterparty_candidate_count: int,
) -> dict[str, object]:
    static_classification = classify_product_line(raw_line, supplier_hint)
    return {
        "static": {
            "category": static_classification.category,
            "confidence": static_classification.confidence,
            "evidence": list(static_classification.evidence),
        },
        "ai": {
            "used": ai_used,
            "provider": ai_provider,
            "skipped_reason": ai_skipped_reason,
            "category": relevance.classification.category,
            "confidence": relevance.classification.confidence,
            "reason": ai_reason,
            "suggested_account_code": ai_suggested_account_code,
            "suggested_counterparty_code": ai_suggested_counterparty_code,
            "product_identity": ai_product_identity,
            "needs_research": ai_research_requested,
            "research_query": ai_research_query,
            "risk_flags": list(ai_risk_flags),
        },
        "final": {
            "selected_account_code": selected_account_code,
            "selected_vat_account": selected_vat_account,
            "selected_counterparty_account": selected_counterparty_account,
            "direction": direction,
            "export_status": export_status,
            "review_reason_codes": list(review_reason_codes),
            "draft_confidence": draft_confidence,
        },
        "context": {
            "client_nace_code": client_profile.nace_code if client_profile else "",
            "client_activity_tags": list(client_profile.activity_tags) if client_profile else [],
            "direction_confidence": direction_confidence,
            "deterministic_checks": list(deterministic_checks),
            "account_candidate_count": ai_account_candidate_count,
            "counterparty_candidate_count": ai_counterparty_candidate_count,
        },
    }


def simulate_invoice(
    invoice: ParsedInvoice,
    selection: AccountSelection,
    client_profile: ClientProfile | None = None,
    counterparty_match: CounterpartyMatch | None = None,
    product_classifier: ProductClassifier | None = None,
    processing_mode: ProcessingMode | str = "controlled_automation",
    intended_direction: str | None = None,
    classification_override: ProductClassification | None = None,
) -> SimulatedInvoiceResult:
    mode = _normalize_processing_mode(processing_mode)
    reasons = tuple(dict.fromkeys((*invoice.risk_flags, *invoice.parse_notes)))
    amount = _decimal_or_none(invoice.payable_total)
    entry: JournalEntry | None = None
    draft_quality = "none"
    direction, direction_confidence, direction_evidence = infer_accounting_direction(
        invoice,
        client_profile,
        intended_direction=intended_direction,
    )
    direction_conflict = _direction_conflict_payload(
        intended_direction=intended_direction,
        detected_direction=direction,
        confidence=direction_confidence,
        evidence=direction_evidence,
    )
    suggested_counterparty, counterparty_creation_suggestion = _counterparty_creation_suggestion(
        direction,
        selection,
        invoice,
        client_profile,
    )
    counterparty_tax_id = _counterparty_tax_identifier(invoice, client_profile, direction=direction)
    counterparty_title = _counterparty_title(invoice, direction=direction)
    counterparty_identity_key = _counterparty_identity_key(
        direction=direction,
        tax_id=counterparty_tax_id,
        title=counterparty_title,
    )
    supplier_account = _selected_purchase_supplier_account(
        selection=selection,
        suggested_counterparty=suggested_counterparty if direction != "sales" else "",
        counterparty_match=counterparty_match,
    )
    selected_revenue_account = ""
    selected_purchase_vat_account = ""
    selected_sales_vat_account = ""
    selected_customer_account = ""
    raw_line = _product_line_hint(invoice)
    relevance = (
        assess_business_relevance(
            raw_line,
            client_profile,
            supplier_hint=invoice.provider_hint,
            classification=classification_override,
        )
        if client_profile
        else _not_assessed_relevance(raw_line)
    )
    ai_used = False
    ai_provider = ""
    ai_skipped_reason = "client_profile_not_provided"
    ai_reason = ""
    ai_estimated_chars = 0
    ai_suggested_account_code = ""
    ai_suggested_counterparty_code = ""
    ai_risk_flags: tuple[str, ...] = ()
    ai_account_reason = ""
    ai_gate = invoice_ai_gate(
        product_category=relevance.classification.category,
        product_confidence=relevance.classification.confidence,
        business_relation=relevance.relation,
        account_treatment=relevance.account_treatment,
        line_hint=raw_line,
    )
    ai_product_identity = ""
    ai_research_requested = False
    ai_research_query = ""
    ai_candidate_strategy = "single_stage"
    ai_selected_account_families: tuple[str, ...] = ()
    ai_stage_evidence: tuple[dict[str, object], ...] = ()
    ai_trace_records: list[dict[str, object]] = []
    ai_account_candidate_count = 0
    ai_counterparty_candidate_count = 0
    if client_profile and product_classifier and ai_gate.needs_ai and classification_override is None:
        policy = _ai_policy_from_classifier(product_classifier)
        base_context = _ai_context(
            invoice=invoice,
            selection=selection,
            client_profile=client_profile,
            counterparty_match=counterparty_match,
            direction=direction,
            direction_confidence=direction_confidence,
            direction_evidence=direction_evidence,
            suggested_counterparty=suggested_counterparty,
            counterparty_title=counterparty_title,
            counterparty_tax_id=counterparty_tax_id,
        )
        ai_account_candidate_count = len(base_context.account_candidates)
        ai_counterparty_candidate_count = len(base_context.counterparty_candidates)
        stage_records: list[dict[str, object]] = []
        if len(base_context.account_candidates) > policy.single_stage_account_limit:
            ai_candidate_strategy = "two_stage"
            family_candidates = _account_family_candidates(base_context.account_candidate_details)
            family_context = replace(
                base_context,
                account_family_candidates=family_candidates,
                account_candidate_limit=policy.final_stage_account_limit,
                account_candidate_details_limit=0,
                counterparty_candidate_limit=policy.counterparty_limit,
                candidate_strategy=AiCandidateStrategy(
                    mode="two_stage",
                    stage="family_select",
                    account_candidate_count=len(base_context.account_candidates),
                    counterparty_candidate_count=len(base_context.counterparty_candidates),
                ),
            )
            family_result = product_classifier.classify(
                raw_line,
                supplier_hint=invoice.provider_hint,
                context=family_context,
            )
            selected_families = family_result.selected_account_families
            ai_trace_records.extend(family_result.ai_trace)
            fallback_reason = ""
            if not selected_families:
                selected_families = tuple(
                    family
                    for family in _fallback_account_families(direction)
                    if any(str(candidate.get("family") or "") == family for candidate in family_candidates)
                )
                fallback_reason = "family_stage_fallback"
            ai_selected_account_families = selected_families
            stage_records.append(_stage_evidence(family_result, fallback_reason=fallback_reason))
            final_context = _filter_context_for_families(base_context, selected_families=selected_families, policy=policy)
            classification_result = product_classifier.classify(
                raw_line,
                supplier_hint=invoice.provider_hint,
                context=final_context,
            )
            ai_trace_records.extend(classification_result.ai_trace)
            stage_records.append(_stage_evidence(classification_result))
        else:
            single_context = replace(
                base_context,
                account_candidate_limit=policy.single_stage_account_limit,
                counterparty_candidate_limit=policy.counterparty_limit,
                account_candidate_details_limit=policy.single_stage_account_limit,
                candidate_strategy=AiCandidateStrategy(
                    mode="single_stage",
                    stage="final_account",
                    account_candidate_count=len(base_context.account_candidates),
                    counterparty_candidate_count=len(base_context.counterparty_candidates),
                ),
            )
            classification_result = product_classifier.classify(
                raw_line,
                supplier_hint=invoice.provider_hint,
                context=single_context,
            )
            ai_trace_records.extend(classification_result.ai_trace)
            stage_records.append(_stage_evidence(classification_result))
        if len(base_context.counterparty_candidates) > policy.counterparty_limit:
            counterparty_context = _counterparty_resolution_context(
                base_context,
                policy=policy,
                mode=ai_candidate_strategy,
            )
            counterparty_result = product_classifier.classify(
                raw_line,
                supplier_hint=invoice.provider_hint,
                context=counterparty_context,
            )
            ai_trace_records.extend(counterparty_result.ai_trace)
            stage_records.append(_stage_evidence(counterparty_result))
            if counterparty_result.suggested_counterparty_code:
                classification_result = replace(
                    classification_result,
                    suggested_counterparty_code=counterparty_result.suggested_counterparty_code,
                    risk_flags=tuple(
                        dict.fromkeys((*classification_result.risk_flags, *counterparty_result.risk_flags))
                    ),
                    account_reason=classification_result.account_reason or counterparty_result.account_reason,
                    provider_reason=classification_result.provider_reason or counterparty_result.provider_reason,
                )
        ai_stage_evidence = tuple(stage_records)
        relevance = assess_business_relevance(
            raw_line,
            client_profile,
            supplier_hint=invoice.provider_hint,
            classification=classification_result.classification,
        )
        ai_used = classification_result.ai_used
        ai_provider = classification_result.provider
        ai_skipped_reason = classification_result.skipped_reason
        ai_reason = classification_result.provider_reason
        ai_estimated_chars = classification_result.estimated_input_chars
        ai_suggested_account_code = classification_result.suggested_account_code
        ai_suggested_counterparty_code = classification_result.suggested_counterparty_code
        ai_risk_flags = classification_result.risk_flags
        ai_account_reason = classification_result.account_reason
        ai_product_identity = classification_result.product_identity
        ai_research_requested = classification_result.needs_research
        ai_research_query = classification_result.research_query
        ai_estimated_chars = sum(int(record.get("input_chars") or 0) for record in ai_stage_evidence)
        ai_account_candidate_count = classification_result.candidate_strategy.account_candidate_count or ai_account_candidate_count
        ai_counterparty_candidate_count = classification_result.candidate_strategy.counterparty_candidate_count or ai_counterparty_candidate_count
    elif client_profile and product_classifier:
        ai_provider = "static_rules"
        ai_skipped_reason = ai_gate.reason
    elif client_profile:
        ai_skipped_reason = "classifier_not_configured"
    guarded_ai_account = ai_suggested_account_code
    static_fallback_account = ""
    static_fallback_suppressed = False
    ai_resolution_status = "resolved"
    ai_retry_reason = ""
    return_invoice = _is_return_invoice(invoice)
    suppress_static_purchase_fallback = (
        direction == "purchase"
        and not return_invoice
        and ai_gate.needs_ai
        and client_profile is not None
        and product_classifier is not None
        and not guarded_ai_account
        and relevance.account_treatment not in {"non_deductible_review", "stock_or_cogs"}
    )
    if relevance.account_treatment == "stock_or_cogs":
        static_fallback_account = _purchase_stock_account_for_line(selection, raw_line)
        purchase_account = guarded_ai_account or ("" if suppress_static_purchase_fallback else static_fallback_account)
    elif relevance.account_treatment == "non_deductible_review":
        purchase_account = selection.non_deductible_account
    else:
        static_fallback_account = _purchase_expense_account_for_line(selection, raw_line)
        purchase_account = guarded_ai_account or ("" if suppress_static_purchase_fallback else static_fallback_account)
    if suppress_static_purchase_fallback:
        static_fallback_suppressed = True
        ai_resolution_status = "ai_retry_required"
        ai_retry_reason = _ai_retry_reason(
            ai_skipped_reason=ai_skipped_reason,
            ai_used=ai_used,
            ai_suggested_account_code=ai_suggested_account_code,
            ai_research_requested=ai_research_requested,
        )
    hearing_device_vat_review = direction == "sales" and _sales_hearing_device_vat_review_needed(invoice)
    if hearing_device_vat_review:
        reasons = tuple(dict.fromkeys((*reasons, "hearing_device_vat_should_be_zero")))

    if static_fallback_suppressed:
        reasons = tuple(dict.fromkeys((*reasons, "ai_retry_required")))
        status = "review_required"
        draft_quality = "ai_retry_required"
    elif return_invoice and amount is not None and amount > 0:
        reasons = tuple(dict.fromkeys((*reasons, "return_invoice_manual_review")))
        vat_rate = _single_vat_rate(invoice) if len(invoice.vat_rates) <= 1 else Decimal("0.00")
        if direction == "sales":
            selected_revenue_account = _sales_revenue_account(selection, vat_rate)
            selected_sales_vat_account = _sales_vat_account_for_rate(selection, vat_rate) if vat_rate > Decimal("0.00") else ""
            selected_customer_account = _selected_sales_customer_account(
                selection=selection,
                suggested_counterparty=suggested_counterparty,
                counterparty_match=counterparty_match,
            )
            if len(invoice.vat_rates) <= 1:
                entry = build_sales_return_entry(
                    entry_date=invoice.issue_date or "1900-01-01",
                    total=money(invoice.payable_total),
                    vat_rate=vat_rate,
                    revenue_account=selected_revenue_account,
                    vat_account=selected_sales_vat_account or selection.sales_vat_account,
                    customer_account=selected_customer_account,
                    document_ref=invoice.file_name,
                )
                draft_quality = "return_reversal_review"
            else:
                entry = build_sales_return_review_entry(
                    entry_date=invoice.issue_date or "1900-01-01",
                    total=money(invoice.payable_total),
                    revenue_account=selection.revenue_account,
                    customer_account=selected_customer_account,
                    document_ref=invoice.file_name,
                )
                selected_revenue_account = selection.revenue_account
                selected_sales_vat_account = selection.sales_vat_account
                draft_quality = "return_gross_review"
        elif direction == "purchase":
            selected_purchase_vat_account = _purchase_vat_account_for_rate(selection, vat_rate) if len(invoice.vat_rates) <= 1 else selection.purchase_vat_account
            if len(invoice.vat_rates) <= 1:
                entry = build_purchase_return_entry(
                    entry_date=invoice.issue_date or "1900-01-01",
                    total=money(invoice.payable_total),
                    vat_rate=vat_rate,
                    expense_account=purchase_account,
                    vat_account=selected_purchase_vat_account,
                    supplier_account=supplier_account,
                    document_ref=invoice.file_name,
                )
                draft_quality = "return_reversal_review"
            else:
                entry = build_purchase_return_review_entry(
                    entry_date=invoice.issue_date or "1900-01-01",
                    total=money(invoice.payable_total),
                    expense_account=purchase_account,
                    supplier_account=supplier_account,
                    document_ref=invoice.file_name,
                )
                draft_quality = "return_gross_review"
        else:
            entry = None
            draft_quality = "return_manual_review"
        if entry:
            reasons = tuple(dict.fromkeys((*reasons, *entry.risk_flags)))
        status = "review_required"
    elif direction == "return_review":
        status = "review_required"
        draft_quality = "return_manual_review"
        reasons = tuple(dict.fromkeys((*reasons, "return_invoice_manual_review")))
    elif amount is None or amount <= 0:
        status = "review_required"
        draft_quality = "no_positive_amount"
    elif direction == "sales" and len(invoice.vat_rates) <= 1:
        vat_rate = _single_vat_rate(invoice)
        if hearing_device_vat_review:
            vat_rate = Decimal("0.00")
        sales_vat_account = _sales_vat_account_for_rate(selection, vat_rate)
        selected_revenue_account = _sales_revenue_account(selection, vat_rate)
        selected_sales_vat_account = sales_vat_account if vat_rate > Decimal("0.00") else ""
        selected_customer_account = _selected_sales_customer_account(
            selection=selection,
            suggested_counterparty=suggested_counterparty,
            counterparty_match=counterparty_match,
        )
        entry = build_sales_entry(
            entry_date=invoice.issue_date or "1900-01-01",
            total=money(invoice.payable_total),
            vat_rate=vat_rate,
            revenue_account=selected_revenue_account,
            vat_account=sales_vat_account,
            customer_account=selected_customer_account,
            customer_description=_counterparty_account_description(
                account=selected_customer_account,
                suggested_counterparty=suggested_counterparty,
                counterparty_match=counterparty_match,
                base_description="Alici cari",
            ),
            document_ref=invoice.file_name,
        )
        draft_quality = "full_basic_sales" if not reasons else "partial_review_required"
        status = "auto_ready" if not reasons else "review_required"
    elif direction == "sales":
        selected_revenue_account = selection.revenue_account
        selected_sales_vat_account = selection.sales_vat_account
        selected_customer_account = _selected_sales_customer_account(
            selection=selection,
            suggested_counterparty=suggested_counterparty,
            counterparty_match=counterparty_match,
        )
        mixed_items = _mixed_vat_items_from_lines(
            invoice,
            selection,
            direction="sales",
            purchase_account=purchase_account,
        )
        if mixed_items:
            entry = build_mixed_vat_sales_entry(
                entry_date=invoice.issue_date or "1900-01-01",
                items=mixed_items,
                customer_account=selected_customer_account,
                customer_description=_counterparty_account_description(
                    account=selected_customer_account,
                    suggested_counterparty=suggested_counterparty,
                    counterparty_match=counterparty_match,
                    base_description="Alici cari",
                ),
                document_ref=invoice.file_name,
            )
            reasons = tuple(
                reason
                for reason in reasons
                if reason not in {"mixed_vat_manual_review", "vat_split_review_required", "vat_split_non_vat_total"}
            )
            reasons = tuple(dict.fromkeys((*reasons, *entry.risk_flags)))
            selected_revenue_account = mixed_items[-1][0]
            selected_sales_vat_account = mixed_items[-1][3]
            draft_quality = (
                "mixed_vat_sales_review"
                if reasons or _counterparty_requires_review(counterparty_match, counterparty_creation_suggestion)
                else "mixed_vat_sales_ready"
            )
        else:
            entry = _gross_sales_review_entry(
                invoice,
                revenue_account=selected_revenue_account,
                customer_account=selected_customer_account,
                customer_description=_counterparty_account_description(
                    account=selected_customer_account,
                    suggested_counterparty=suggested_counterparty,
                    counterparty_match=counterparty_match,
                    base_description="Kontrol bekleyen alici cari",
                ),
            )
            draft_quality = "gross_balanced_needs_vat_split"
        status = "review_required"
    elif len(invoice.vat_rates) <= 1:
        vat_rate = _single_vat_rate(invoice)
        selected_purchase_vat_account = _purchase_vat_account_for_rate(selection, vat_rate)
        if relevance.account_treatment == "non_deductible_review":
            entry = _gross_review_entry(
                invoice,
                selection,
                supplier_account,
                expense_account=selection.non_deductible_account,
                supplier_description=_counterparty_account_description(
                    account=supplier_account,
                    suggested_counterparty=suggested_counterparty,
                    counterparty_match=counterparty_match,
                    base_description="Kontrol bekleyen satici cari",
                ),
            )
            selected_purchase_vat_account = ""
            draft_quality = "gross_non_deductible_review"
        else:
            entry = build_purchase_entry(
                entry_date=invoice.issue_date or "1900-01-01",
                total=money(invoice.payable_total),
                vat_rate=vat_rate,
                expense_account=purchase_account,
                vat_account=selected_purchase_vat_account,
                supplier_account=supplier_account,
                supplier_description=_counterparty_account_description(
                    account=supplier_account,
                    suggested_counterparty=suggested_counterparty,
                    counterparty_match=counterparty_match,
                    base_description="Satici cari",
                ),
                document_ref=invoice.file_name,
            )
            draft_quality = "full_basic_purchase" if not reasons else "partial_review_required"
        status = "auto_ready" if not reasons else "review_required"
    else:
        selected_purchase_vat_account = selection.purchase_vat_account
        mixed_items = _mixed_vat_items_from_lines(
            invoice,
            selection,
            direction="purchase",
            purchase_account=purchase_account,
        )
        if mixed_items:
            entry = build_mixed_vat_purchase_entry(
                entry_date=invoice.issue_date or "1900-01-01",
                items=mixed_items,
                supplier_account=supplier_account,
                supplier_description=_counterparty_account_description(
                    account=supplier_account,
                    suggested_counterparty=suggested_counterparty,
                    counterparty_match=counterparty_match,
                    base_description="Satici cari",
                ),
                document_ref=invoice.file_name,
            )
            reasons = tuple(
                reason
                for reason in reasons
                if reason not in {"mixed_vat_manual_review", "vat_split_review_required", "vat_split_non_vat_total"}
            )
            reasons = tuple(dict.fromkeys((*reasons, *entry.risk_flags)))
            selected_purchase_vat_account = mixed_items[-1][3]
            draft_quality = (
                "mixed_vat_purchase_review"
                if reasons or _counterparty_requires_review(counterparty_match, counterparty_creation_suggestion)
                else "mixed_vat_purchase_ready"
            )
        else:
            entry = _gross_review_entry(
                invoice,
                selection,
                supplier_account,
                expense_account=purchase_account,
                supplier_description=_counterparty_account_description(
                    account=supplier_account,
                    suggested_counterparty=suggested_counterparty,
                    counterparty_match=counterparty_match,
                    base_description="Kontrol bekleyen satici cari",
                ),
            )
            draft_quality = "gross_balanced_needs_vat_split"
        status = "review_required"

    counterparty_reasons: tuple[str, ...] = ()
    if counterparty_match and counterparty_match.requires_review:
        counterparty_reasons = (f"counterparty_{counterparty_match.match_reason}",)
    elif counterparty_match is None and counterparty_creation_suggestion:
        counterparty_reasons = ("counterparty_missing",)
    onboarding_reasons: tuple[str, ...] = ()
    if client_profile:
        onboarding = check_client_onboarding(client_profile)
        if not onboarding.is_ready:
            onboarding_reasons = tuple(f"onboarding_missing_{field}" for field in onboarding.missing_fields)
    else:
        onboarding_reasons = ("onboarding_missing_client_profile",)
    direction_reasons = ("direction_conflict_review",) if direction_conflict else ()
    all_reasons = tuple(dict.fromkeys((*reasons, *counterparty_reasons, *onboarding_reasons, *direction_reasons)))

    export_status = decide_export_status(
        is_balanced=entry.is_balanced if entry else False,
        risk_flags=all_reasons,
        relevance=relevance,
    )
    if static_fallback_suppressed:
        export_status = "review_required"
    mode_reasons: tuple[str, ...] = ()
    if mode == "conservative" and export_status == "export_ready":
        mode_reasons = ("conservative_mode_requires_review",)
    elif mode == "ai_assisted_draft" and export_status == "export_ready":
        mode_reasons = ("ai_assisted_draft_requires_accountant_approval",)
    if mode_reasons:
        all_reasons = tuple(dict.fromkeys((*all_reasons, *mode_reasons)))
        export_status = "review_required"
    if export_status != "export_ready":
        status = "review_required"
    deterministic_checks = _deterministic_checks(
        entry=entry,
        invoice=invoice,
        amount=amount,
        counterparty_match=counterparty_match,
        client_profile=client_profile,
    )
    export_gate_reason = _export_gate_reason(
        export_status=export_status,
        processing_mode=mode,
        review_reasons=all_reasons,
        relevance=relevance,
        counterparty_match=counterparty_match,
        entry=entry,
    )
    if static_fallback_suppressed:
        export_gate_reason = "AI ajani karar tamamlayamadi; belge tekrar denenecek."
    accountant_explanation = _accountant_explanation(
        direction=direction,
        direction_evidence=direction_evidence,
        invoice=invoice,
        revenue_account=selected_revenue_account,
        expense_account="" if direction == "sales" else purchase_account,
        purchase_vat_account=selected_purchase_vat_account,
        sales_vat_account=selected_sales_vat_account,
        suggested_counterparty=suggested_counterparty,
        draft_quality=draft_quality,
    )
    draft_lines = _entry_lines(entry, _account_names_from_selection(selection, counterparty_match))
    review_blockers = _review_blockers(
        review_reasons=all_reasons,
        deterministic_checks=deterministic_checks,
        counterparty_match=counterparty_match,
        counterparty_creation_suggestion=counterparty_creation_suggestion,
    )
    draft_confidence = _draft_confidence(
        entry=entry,
        amount=amount,
        direction_confidence=direction_confidence,
        counterparty_match=counterparty_match,
        review_reasons=review_blockers,
    )
    automation_eligibility = _automation_eligibility(export_status=export_status, mode=mode, blockers=review_blockers)
    primary_suggestion = _primary_suggestion(
        direction=direction,
        counterparty_account=(
            selected_customer_account
            if direction == "sales"
            else counterparty_match.account_code if counterparty_match and counterparty_match.account_code else ""
        ),
        suggested_counterparty=suggested_counterparty,
        expense_account="" if direction == "sales" else purchase_account,
        revenue_account=selected_revenue_account,
        vat_account=selected_sales_vat_account if direction == "sales" else selected_purchase_vat_account,
        draft_lines=draft_lines,
        ai_reason=ai_reason or relevance.reason,
        export_gate_reason=export_gate_reason,
    )
    selected_account_code = selected_revenue_account if direction == "sales" else purchase_account
    selected_vat_account = selected_sales_vat_account if direction == "sales" else selected_purchase_vat_account
    selected_counterparty_account = (
        selected_customer_account
        if direction == "sales"
        else counterparty_match.account_code if counterparty_match and counterparty_match.account_code else suggested_counterparty
    )
    ai_quality_scorecard = _ai_quality_scorecard(
        raw_line=raw_line,
        supplier_hint=invoice.provider_hint,
        relevance=relevance,
        ai_used=ai_used,
        ai_provider=ai_provider,
        ai_skipped_reason=ai_skipped_reason,
        ai_reason=ai_reason,
        ai_suggested_account_code=ai_suggested_account_code,
        ai_suggested_counterparty_code=ai_suggested_counterparty_code,
        ai_product_identity=ai_product_identity,
        ai_research_requested=ai_research_requested,
        ai_research_query=ai_research_query,
        ai_risk_flags=ai_risk_flags,
        client_profile=client_profile,
        selected_account_code=selected_account_code,
        selected_vat_account=selected_vat_account,
        selected_counterparty_account=selected_counterparty_account,
        direction=direction,
        direction_confidence=direction_confidence,
        deterministic_checks=deterministic_checks,
        export_status=export_status,
        review_reason_codes=all_reasons,
        draft_confidence=draft_confidence,
        ai_account_candidate_count=ai_account_candidate_count,
        ai_counterparty_candidate_count=ai_counterparty_candidate_count,
    )

    return SimulatedInvoiceResult(
        chart_file_name=selection.chart_file_name,
        file_name=invoice.file_name,
        provider_hint=invoice.provider_hint,
        invoice_type=invoice.invoice_type,
        issue_date=invoice.issue_date,
        payable_total=invoice.payable_total,
        vat_rates=invoice.vat_rates,
        risk_flags=invoice.risk_flags,
        parse_notes=invoice.parse_notes,
        simulated_status=status,
        draft_quality=draft_quality,
        draft_entry_type=entry.entry_type if entry else "",
        total_debit=f"{entry.total_debit:.2f}" if entry else "",
        total_credit=f"{entry.total_credit:.2f}" if entry else "",
        is_balanced=entry.is_balanced if entry else False,
        selected_expense_account="" if direction == "sales" else purchase_account,
        selected_vat_account=selected_sales_vat_account if direction == "sales" else selected_purchase_vat_account,
        selected_supplier_account="" if direction == "sales" else supplier_account,
        counterparty_match_code=counterparty_match.account_code if counterparty_match else "",
        counterparty_match_confidence=counterparty_match.confidence if counterparty_match else 0,
        counterparty_match_reason=counterparty_match.match_reason if counterparty_match else "not_assessed",
        review_reason_codes=all_reasons,
        processing_mode=mode,
        draft_decision_source=_draft_decision_source(ai_used=ai_used, processing_mode=mode),
        deterministic_checks=deterministic_checks,
        export_gate_reason=export_gate_reason,
        product_line_hint=raw_line,
        product_category=relevance.classification.category,
        product_confidence=relevance.classification.confidence,
        business_relevance_status=relevance.status,
        business_relevance_confidence=relevance.confidence,
        business_relevance_reason=relevance.reason,
        business_relevance_evidence=relevance.evidence,
        business_relevance_relation=relevance.relation,
        business_relevance_account_treatment=relevance.account_treatment,
        business_relevance_requires_review=relevance.requires_accountant_review,
        ai_classification_used=ai_used,
        ai_classification_provider=ai_provider,
        ai_classification_skipped_reason=ai_skipped_reason,
        ai_classification_reason=ai_reason,
        ai_estimated_input_chars=ai_estimated_chars,
        ai_suggested_account_code=ai_suggested_account_code,
        ai_suggested_counterparty_code=ai_suggested_counterparty_code,
        ai_risk_flags=ai_risk_flags,
        ai_account_reason=ai_account_reason,
        ai_gate_reason=ai_gate.reason,
        ai_product_identity=ai_product_identity,
        ai_research_requested=ai_research_requested,
        ai_research_query=ai_research_query,
        client_nace_code=client_profile.nace_code if client_profile else "",
        client_activity_tags=client_profile.activity_tags if client_profile else (),
        counterparty_tax_id=counterparty_tax_id,
        counterparty_title=counterparty_title,
        counterparty_identity_key=counterparty_identity_key,
        ai_candidate_strategy=ai_candidate_strategy,
        ai_selected_account_families=ai_selected_account_families,
        ai_stage_evidence=ai_stage_evidence,
        ai_account_stage_evidence=tuple(
            record for record in ai_stage_evidence if record.get("ai_stage") in {"family_select", "final_account"}
        ),
        ai_counterparty_stage_evidence=tuple(
            record for record in ai_stage_evidence if record.get("ai_stage") == "counterparty_resolve"
        ),
        ai_trace=tuple(ai_trace_records),
        ai_account_candidate_count=ai_account_candidate_count,
        ai_counterparty_candidate_count=ai_counterparty_candidate_count,
        ai_quality_scorecard=ai_quality_scorecard,
        ai_resolution_status=ai_resolution_status,
        ai_retry_reason=ai_retry_reason,
        static_fallback_account=static_fallback_account,
        static_fallback_suppressed=static_fallback_suppressed,
        learning_rule_applied=False,
        learning_rule_scope="",
        learning_rule_reason="",
        learning_rule_source_summary="",
        accounting_intent="",
        accounting_intent_confidence=0,
        rule_prompt={},
        export_status=export_status,
        draft_lines=draft_lines,
        draft_confidence=draft_confidence,
        primary_suggestion=primary_suggestion,
        review_blockers=review_blockers,
        automation_eligibility=automation_eligibility,
        accountant_action_hint=_accountant_action_hint(
            export_status=export_status,
            blockers=review_blockers,
            draft_lines=draft_lines,
        ),
        suggested_counterparty_creation=counterparty_creation_suggestion,
        selected_revenue_account=selected_revenue_account,
        selected_purchase_vat_account=selected_purchase_vat_account,
        selected_sales_vat_account=selected_sales_vat_account,
        selected_customer_account=selected_customer_account,
        suggested_counterparty_account=suggested_counterparty,
        counterparty_creation_suggestion=counterparty_creation_suggestion,
        accounting_direction=direction,
        direction_confidence=direction_confidence,
        direction_uncertainty=direction_confidence < 70,
        direction_evidence=direction_evidence,
        direction_conflict=direction_conflict,
        accountant_explanation_tr=accountant_explanation,
        account_candidates=selection.account_candidates,
    )


def simulate_chart_run(
    chart_path: Path,
    invoices: list[ParsedInvoice],
    client_profile: ClientProfile | None = None,
    product_classifier: ProductClassifier | None = None,
) -> SimulatedChartRun:
    accounts = parse_chart_accounts(chart_path)
    detail_accounts = [account for account in accounts if account.is_detail_account]
    counterparties = extract_counterparty_candidates(accounts)
    vat_status = validate_vat_accounts(accounts)
    selection = select_accounts(chart_path.name, accounts)
    counterparty_matches = {
        invoice.file_name: _counterparty_match_for_invoice(accounts, invoice, client_profile)
        for invoice in invoices
    }
    return SimulatedChartRun(
        chart_file_name=chart_path.name,
        account_count=len(accounts),
        detail_account_count=len(detail_accounts),
        customer_candidate_count=sum(1 for account in counterparties if account.counterparty_type == "customer"),
        supplier_candidate_count=sum(1 for account in counterparties if account.counterparty_type == "supplier"),
        has_purchase_vat_191=vat_status["has_purchase_vat_191"],
        has_sales_vat_391=vat_status["has_sales_vat_391"],
        account_selection=selection,
        invoice_results=tuple(
            simulate_invoice(
                invoice,
                selection,
                client_profile,
                counterparty_matches[invoice.file_name],
                product_classifier,
            )
            for invoice in invoices
        ),
    )


def simulate_private_matching(
    invoice_dir: Path,
    chart_paths: list[Path],
    client_profile: ClientProfile | None = None,
    product_classifier: ProductClassifier | None = None,
) -> list[SimulatedChartRun]:
    invoices = parse_invoice_folder(invoice_dir)
    return [simulate_chart_run(chart_path, invoices, client_profile, product_classifier) for chart_path in chart_paths]


def write_simulation_csv(runs: list[SimulatedChartRun], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "chart_file_name",
        "file_name",
        "provider_hint",
        "invoice_type",
        "issue_date",
        "payable_total",
        "vat_rates",
        "simulated_status",
        "draft_quality",
        "draft_entry_type",
        "is_balanced",
        "selected_expense_account",
        "selected_vat_account",
        "selected_supplier_account",
        "selected_revenue_account",
        "selected_purchase_vat_account",
        "selected_sales_vat_account",
        "selected_customer_account",
        "suggested_counterparty_account",
        "accounting_direction",
        "direction_confidence",
        "direction_uncertainty",
        "direction_evidence",
        "direction_conflict",
        "counterparty_match_code",
        "counterparty_match_confidence",
        "counterparty_match_reason",
        "processing_mode",
        "draft_decision_source",
        "deterministic_checks",
        "export_gate_reason",
        "product_line_hint",
        "product_category",
        "product_confidence",
        "business_relevance_status",
        "business_relevance_confidence",
        "business_relevance_reason",
        "business_relevance_evidence",
        "ai_classification_used",
        "ai_classification_provider",
        "ai_classification_skipped_reason",
        "ai_classification_reason",
        "ai_estimated_input_chars",
        "learning_rule_applied",
        "learning_rule_scope",
        "learning_rule_reason",
        "learning_rule_source_summary",
        "accounting_intent",
        "accounting_intent_confidence",
        "export_status",
        "risk_flags",
        "parse_notes",
        "review_reason_codes",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for run in runs:
            for result in run.invoice_results:
                row = asdict(result)
                row["vat_rates"] = ";".join(result.vat_rates)
                row["risk_flags"] = ";".join(result.risk_flags)
                row["parse_notes"] = ";".join(result.parse_notes)
                row["review_reason_codes"] = ";".join(result.review_reason_codes)
                row["deterministic_checks"] = ";".join(result.deterministic_checks)
                row["business_relevance_evidence"] = ";".join(result.business_relevance_evidence)
                row["direction_evidence"] = ";".join(result.direction_evidence)
                writer.writerow({column: row[column] for column in columns})
    return output_path


def build_review_ui_payload(runs: list[SimulatedChartRun]) -> dict[str, object]:
    chart_runs = []
    invoice_rows = []
    for run in runs:
        chart_runs.append(
            {
                "chartFileName": run.chart_file_name,
                "accountCount": run.account_count,
                "detailAccountCount": run.detail_account_count,
                "customerCandidateCount": run.customer_candidate_count,
                "supplierCandidateCount": run.supplier_candidate_count,
                "hasPurchaseVat191": run.has_purchase_vat_191,
                "hasSalesVat391": run.has_sales_vat_391,
                "autoReadyCount": run.auto_ready_count,
                "reviewRequiredCount": run.review_required_count,
                "cannotDraftCount": run.cannot_draft_count,
                "selectedAccounts": asdict(run.account_selection),
            }
        )
        for result in run.invoice_results:
            invoice_rows.append(
                {
                    "chartFileName": result.chart_file_name,
                    "fileName": result.file_name,
                    "providerHint": result.provider_hint,
                    "invoiceType": result.invoice_type,
                    "issueDate": result.issue_date,
                    "payableTotal": result.payable_total,
                    "vatRates": list(result.vat_rates),
                    "status": result.simulated_status,
                    "draftQuality": result.draft_quality,
                    "draftEntryType": result.draft_entry_type,
                    "isBalanced": result.is_balanced,
                    "riskFlags": list(result.risk_flags),
                    "parseNotes": list(result.parse_notes),
                    "reviewReasonCodes": list(result.review_reason_codes),
                    "accountingDirection": result.accounting_direction,
                    "directionConfidence": result.direction_confidence,
                    "directionUncertainty": result.direction_uncertainty,
                    "directionEvidence": list(result.direction_evidence),
                    "directionConflict": result.direction_conflict,
                    "productLineHint": result.product_line_hint,
                    "productCategory": result.product_category,
                    "productConfidence": result.product_confidence,
                    "businessRelevanceStatus": result.business_relevance_status,
                    "businessRelevanceConfidence": result.business_relevance_confidence,
                    "businessRelevanceReason": result.business_relevance_reason,
                    "businessRelevanceEvidence": list(result.business_relevance_evidence),
                    "aiClassificationUsed": result.ai_classification_used,
                    "aiClassificationProvider": result.ai_classification_provider,
                    "aiClassificationSkippedReason": result.ai_classification_skipped_reason,
                    "aiClassificationReason": result.ai_classification_reason,
                    "aiEstimatedInputChars": result.ai_estimated_input_chars,
                    "aiGateReason": result.ai_gate_reason,
                    "aiProductIdentity": result.ai_product_identity,
                    "aiResearchRequested": result.ai_research_requested,
                    "aiResearchQuery": result.ai_research_query,
                    "aiSuggestedAccountCode": result.ai_suggested_account_code,
                    "aiSuggestedCounterpartyCode": result.ai_suggested_counterparty_code,
                    "aiRiskFlags": list(result.ai_risk_flags),
                    "aiAccountReason": result.ai_account_reason,
                    "aiCandidateStrategy": result.ai_candidate_strategy,
                    "aiSelectedAccountFamilies": list(result.ai_selected_account_families),
                    "aiStageEvidence": list(result.ai_stage_evidence),
                    "aiTrace": list(result.ai_trace),
                    "aiAccountCandidateCount": result.ai_account_candidate_count,
                    "aiCounterpartyCandidateCount": result.ai_counterparty_candidate_count,
                    "aiProviderStatus": result.ai_classification_skipped_reason or ("used" if result.ai_classification_used else "not_used"),
                    "clientNaceCode": result.client_nace_code,
                    "clientActivityTags": list(result.client_activity_tags),
                    "counterpartyTaxId": result.counterparty_tax_id,
                    "counterpartyTitle": result.counterparty_title,
                    "counterpartyIdentityKey": result.counterparty_identity_key,
                    "learningRuleApplied": result.learning_rule_applied,
                    "learningRuleScope": result.learning_rule_scope,
                    "learningRuleReason": result.learning_rule_reason,
                    "learningRuleSourceSummary": result.learning_rule_source_summary,
                    "accountingIntent": result.accounting_intent,
                    "accountingIntentConfidence": result.accounting_intent_confidence,
                    "rulePrompt": result.rule_prompt,
                    "exportStatus": result.export_status,
                    "selectedExpenseAccount": result.selected_expense_account,
                    "selectedVatAccount": result.selected_vat_account,
                    "selectedSupplierAccount": result.selected_supplier_account,
                    "selectedRevenueAccount": result.selected_revenue_account,
                    "selectedPurchaseVatAccount": result.selected_purchase_vat_account,
                    "selectedSalesVatAccount": result.selected_sales_vat_account,
                    "selectedCustomerAccount": result.selected_customer_account,
                    "suggestedCounterpartyAccount": result.suggested_counterparty_account,
                    "counterpartyMatchCode": result.counterparty_match_code,
                    "counterpartyMatchConfidence": result.counterparty_match_confidence,
                    "counterpartyMatchReason": result.counterparty_match_reason,
                    "processingMode": result.processing_mode,
                    "draftDecisionSource": result.draft_decision_source,
                    "deterministicChecks": list(result.deterministic_checks),
                    "exportGateReason": result.export_gate_reason,
                    "draftLines": list(result.draft_lines),
                }
            )
    return {
        "generatedFrom": "private local files",
        "summary": {
            "chartRunCount": len(runs),
            "invoiceRowCount": len(invoice_rows),
            "autoReadyCount": sum(run.auto_ready_count for run in runs),
            "reviewRequiredCount": sum(run.review_required_count for run in runs),
            "cannotDraftCount": sum(run.cannot_draft_count for run in runs),
            "allDraftsBalanced": all(
                result.is_balanced
                for run in runs
                for result in run.invoice_results
                if result.draft_lines
            ),
        },
        "chartRuns": chart_runs,
        "invoiceRows": invoice_rows,
    }


def private_benchmark_summary(
    runs: list[SimulatedChartRun],
    *,
    run_label: str,
    firm_id: str,
) -> dict[str, object]:
    results = [result for run in runs for result in run.invoice_results]
    review_reasons = [reason for result in results for reason in result.review_reason_codes]
    return {
        "firm_id": firm_id,
        "run_label": run_label,
        "chart_run_count": len(runs),
        "invoice_count": len(results),
        "auto_ready_count": sum(1 for result in results if result.simulated_status == "auto_ready"),
        "review_required_count": sum(1 for result in results if result.simulated_status == "review_required"),
        "blocked_count": sum(1 for result in results if result.export_status == "blocked"),
        "mixed_vat_review_count": sum(1 for result in results if "mixed_vat_manual_review" in result.review_reason_codes),
        "sales_direction_purchase_draft_count": sum(
            1
            for result in results
            if result.accounting_direction == "sales" and "purchase" in result.draft_entry_type
        ),
        "missing_total_count": sum(1 for result in results if "missing_payable_total" in result.review_reason_codes),
        "counterparty_matched_count": sum(
            1
            for result in results
            if result.counterparty_match_code and result.counterparty_match_confidence >= 80
        ),
        "counterparty_weak_count": sum(
            1
            for result in results
            if result.counterparty_match_code and result.counterparty_match_confidence < 80
        ),
        "counterparty_missing_count": sum(1 for result in results if not result.counterparty_match_code),
        "unknown_product_count": sum(1 for result in results if result.product_confidence < 70),
        "ai_used_count": sum(1 for result in results if result.ai_classification_used),
        "provider_failure_count": sum(1 for result in results if "ai_provider_error" in result.ai_risk_flags),
        "review_reason_counts": {
            reason: review_reasons.count(reason)
            for reason in sorted(set(review_reasons))
        },
    }


def write_review_ui_json(runs: list[SimulatedChartRun], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build_review_ui_payload(runs), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
