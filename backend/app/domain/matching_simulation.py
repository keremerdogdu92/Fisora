from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from app.domain.ai_classification import AiCandidateStrategy, AiClassificationContext, AiClassificationPolicy, AiClassificationResult, ProductClassifier, StaticFirstClassifier
from app.domain.utility_invoice_markers import utility_exception_requires_review
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
from app.domain.canonical_invoices import validate_line_decision_coverage
from app.domain.invoice_ai_gate import (
    AcceptedSemanticAttemptRef,
    LineAccountAuthority,
    SemanticAccountAuthoritySet,
    VerifiedRuleAuthorityV1,
    invoice_ai_gate,
)
from app.domain.journal_entries import (
    JournalEntry,
    JournalLine,
    build_component_purchase_entry,
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
from app.domain.vat_accounting_groups import (
    VatAccountingGroup,
    account_roles_for,
    build_vat_accounting_groups,
)

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
    revenue_account: str = ""
    zero_vat_revenue_account: str = ""
    sales_vat_account: str = ""
    customer_account: str = ""
    next_customer_account: str = ""
    next_supplier_account: str = ""
    stock_account: str = ""
    non_deductible_account: str = ""
    account_candidates: dict[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)
    account_names: dict[str, str] = field(default_factory=dict)


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
    ai_attempted_account_code: str
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
    learning_audit: dict[str, object] = field(default_factory=dict)
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
    semantic_attempts: tuple[dict[str, object], ...] = ()
    accepted_semantic_attempt_id: str = ""
    ai_account_candidate_count: int = 0
    ai_counterparty_candidate_count: int = 0
    ai_quality_scorecard: dict[str, object] = field(default_factory=dict)
    ai_resolution_status: str = "resolved"
    ai_retry_reason: str = ""
    static_fallback_account: str = ""
    static_fallback_suppressed: bool = False
    canonical_line_count: int = 0
    canonical_validation_status: str = ""
    canonical_validation_reasons: tuple[str, ...] = ()
    canonical_extraction_notes: tuple[str, ...] = ()
    canonical_extraction_ai_used: bool = False
    provider_id: str = ""
    service_profile: str = ""
    provider_match_kind: str = ""
    provider_directory_version: int = 0
    utility_exception_markers: tuple[str, ...] = ()
    tax_components: tuple[dict[str, object], ...] = ()
    monetary_components: tuple[dict[str, object], ...] = ()
    line_decisions: tuple[dict[str, object], ...] = ()
    line_decision_coverage: dict[str, object] = field(default_factory=dict)
    decision_narrative: dict[str, object] = field(default_factory=dict)


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
        "is_detail_account": account.is_detail_account is True,
        "is_active": True,
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


def _account_name_map(accounts: list[ChartAccount]) -> dict[str, str]:
    return {
        account.normalized_account_code: account.account_name
        for account in accounts
        if account.normalized_account_code and account.account_name
    }


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
    if non_deductible is None:
        notes.append("non_deductible_account_missing")

    return AccountSelection(
        chart_file_name=chart_file_name,
        expense_account=expense.normalized_account_code if expense else "",
        purchase_vat_account=purchase_vat.normalized_account_code if purchase_vat else "",
        supplier_account=supplier.normalized_account_code if supplier else "",
        bank_account=bank.normalized_account_code if bank else "",
        non_deductible_account=non_deductible.normalized_account_code if non_deductible else "",
        selection_notes=tuple(notes),
        revenue_account=revenue.normalized_account_code if revenue else "",
        zero_vat_revenue_account=zero_vat_revenue.normalized_account_code if zero_vat_revenue else "",
        sales_vat_account=sales_vat.normalized_account_code if sales_vat else "",
        customer_account=customer.normalized_account_code if customer else "",
        next_customer_account=_next_counterparty_account(accounts, "120"),
        next_supplier_account=_next_counterparty_account(accounts, "320"),
        stock_account=stock.normalized_account_code if stock else "",
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
        account_names=_account_name_map(accounts),
    )


def _decimal_or_none(value: str) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def build_utility_component_purchase_entry(
    *,
    invoice: ParsedInvoice,
    service_expense_account: str,
    vat_account: str,
    supplier_account: str,
    supplier_description: str = "Satici cari",
) -> JournalEntry | None:
    canonical = getattr(invoice, "canonical_invoice", None)
    if canonical is None or not getattr(invoice, "service_profile", ""):
        return None
    payable = _decimal_or_none(str(getattr(canonical.totals, "payable_total", "") or invoice.payable_total))
    if payable is None or payable <= 0:
        return None

    prior_period_total = sum(
        (
            _decimal_or_none(component.source_amount) or Decimal("0.00")
            for component in getattr(canonical, "monetary_components", ())
            if component.accounting_treatment == "exclude_current_period"
        ),
        Decimal("0.00"),
    )
    posting_total = (payable - prior_period_total).quantize(Decimal("0.01"))
    if posting_total <= 0:
        return None

    tax_components = tuple(getattr(canonical, "tax_components", ()) or ())
    vat_amount = sum(
        (
            _decimal_or_none(component.tax_amount) or Decimal("0.00")
            for component in tax_components
            if component.canonical_tax_kind == "vat"
        ),
        Decimal("0.00"),
    )
    if not vat_amount:
        vat_amount = _decimal_or_none(str(getattr(canonical.totals, "vat_total", "") or invoice.vat_total)) or Decimal("0.00")

    unresolved_components = tuple(
        component
        for component in tax_components
        if component.canonical_tax_kind != "vat"
        and component.accounting_treatment == "unresolved"
        and (_decimal_or_none(component.tax_amount) or Decimal("0.00")) != Decimal("0.00")
    )
    unresolved_total = sum(
        (_decimal_or_none(component.tax_amount) or Decimal("0.00") for component in unresolved_components),
        Decimal("0.00"),
    )
    service_expense_amount = (posting_total - vat_amount - unresolved_total).quantize(Decimal("0.01"))
    if service_expense_amount < 0:
        return None

    entry = build_component_purchase_entry(
        entry_date=invoice.issue_date or "1900-01-01",
        service_expense_account=service_expense_account,
        service_expense_amount=service_expense_amount,
        vat_account=vat_account,
        vat_amount=vat_amount,
        separate_expenses=tuple(
            ("", component.source_label or component.canonical_tax_kind, _decimal_or_none(component.tax_amount) or Decimal("0.00"))
            for component in unresolved_components
        ),
        supplier_account=supplier_account,
        supplier_total=posting_total,
        supplier_description=supplier_description,
        supplier_tax_id=getattr(invoice, "issuer_tax_id", "") or None,
        document_ref=invoice.file_name,
    )
    risks: list[str] = []
    if unresolved_components:
        risks.append("tax_component_account_unresolved")
    if not service_expense_account:
        risks.append("service_expense_account_missing")
    if vat_amount and not vat_account:
        risks.append("purchase_vat_account_missing")
    if not supplier_account:
        risks.append("supplier_account_missing")
    return replace(entry, risk_flags=tuple(risks))


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


def _ai_retry_reason(
    *,
    ai_skipped_reason: str,
    ai_used: bool,
    ai_suggested_account_code: str,
    ai_attempted_account_code: str,
    ai_research_requested: bool,
) -> str:
    if ai_suggested_account_code:
        return ""
    if ai_skipped_reason:
        return ai_skipped_reason
    if ai_research_requested:
        return "research_required"
    if ai_attempted_account_code:
        return "selected_account_not_in_candidates"
    if ai_used:
        return "ai_account_missing"
    return "ai_not_resolved"


def _classify_with_semantic_authority(
    classifier: ProductClassifier,
    raw_line: str,
    *,
    supplier_hint: str,
    context: AiClassificationContext,
) -> AiClassificationResult:
    if isinstance(classifier, StaticFirstClassifier) and classifier.policy.static_confidence_threshold <= 100:
        forced_classifier = StaticFirstClassifier(
            provider=classifier.provider,
            policy=replace(classifier.policy, static_confidence_threshold=101),
        )
        forced_classifier.provider_calls = classifier.provider_calls
        result = forced_classifier.classify(raw_line, supplier_hint=supplier_hint, context=context)
        classifier.provider_calls = forced_classifier.provider_calls
        return result
    return classifier.classify(raw_line, supplier_hint=supplier_hint, context=context)


def _attempted_ai_account_code(result: AiClassificationResult | None) -> str:
    if result is None:
        return ""
    if result.suggested_account_code:
        return result.suggested_account_code
    for trace in reversed(result.ai_trace):
        response = trace.get("provider_response")
        if not isinstance(response, dict):
            continue
        candidate = str(response.get("suggested_account_code") or "").strip()
        if candidate:
            return candidate
        for decision in response.get("line_decisions") or ():
            if isinstance(decision, dict):
                candidate = str(decision.get("suggested_account_code") or "").strip()
                if candidate:
                    return candidate
    return ""


_SEMANTIC_GROUPS_BY_DIRECTION = {
    "purchase": ("purchase_expense", "purchase_stock", "non_deductible"),
    "sales": ("sales_revenue", "zero_vat_revenue"),
}
_SEMANTIC_ROLE_GROUPS = {
    "expense": ("purchase_expense",),
    "stock": ("purchase_stock",),
    "non_deductible": ("non_deductible",),
    "revenue": ("sales_revenue", "zero_vat_revenue"),
}
_VERIFIED_SEMANTIC_ROLES_BY_DIRECTION = {
    "purchase": frozenset({"expense", "stock", "non_deductible"}),
    "sales": frozenset({"revenue"}),
}
_CHART_ROLE_BY_VERIFIED_SEMANTIC_ROLE = {
    "expense": "expense",
    "stock": "stock",
    "revenue": "sales_revenue",
    "non_deductible": "non_deductible",
}


def _semantic_candidate_codes(
    selection: AccountSelection,
    *,
    direction: str,
    semantic_role: str = "",
    require_verified_detail: bool = False,
) -> set[str]:
    if require_verified_detail:
        if semantic_role not in _VERIFIED_SEMANTIC_ROLES_BY_DIRECTION.get(direction, frozenset()):
            return set()
        groups = _SEMANTIC_ROLE_GROUPS[semantic_role]
    else:
        groups = _SEMANTIC_ROLE_GROUPS.get(semantic_role) or _SEMANTIC_GROUPS_BY_DIRECTION.get(direction, ())
    codes: set[str] = set()
    for group in groups:
        if group not in _SEMANTIC_GROUPS_BY_DIRECTION.get(direction, ()):
            continue
        for candidate in selection.account_candidates.get(group, ()):
            code = str(candidate.get("code") or "").strip()
            if not code:
                continue
            if require_verified_detail and (
                candidate.get("is_detail_account") is not True
                or candidate.get("is_active") is not True
            ):
                continue
            if require_verified_detail:
                chart_roles = semantic_roles_for_account(
                    ChartAccount(
                        raw_account_code=code,
                        normalized_account_code=code,
                        account_name=str(candidate.get("name") or ""),
                        is_detail_account=True,
                    )
                )
                if _CHART_ROLE_BY_VERIFIED_SEMANTIC_ROLE[semantic_role] not in chart_roles:
                    continue
            if code.startswith(("120", "191", "320", "391")):
                continue
            codes.add(code)
    return codes


def _resolve_verified_rule_authority(
    *,
    capabilities: tuple[VerifiedRuleAuthorityV1, ...],
    canonical_items: tuple[object, ...],
    selection: AccountSelection,
    client_id: str,
    direction: str,
    invoice_mode: str,
) -> SemanticAccountAuthoritySet:
    if not capabilities or not canonical_items:
        return SemanticAccountAuthoritySet()
    expected_ids = {
        str(getattr(line, "canonical_line_id", "") or "")
        for line in canonical_items
    }
    resolved: list[LineAccountAuthority] = []
    seen: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, VerifiedRuleAuthorityV1):
            return SemanticAccountAuthoritySet()
        line_id = capability.canonical_line_id.strip()
        account_code = capability.account_code.strip()
        if (
            capability.schema_version != "v1"
            or capability.client_id != client_id
            or not capability.rule_id.strip()
            or not capability.rule_version.strip()
            or not capability.activation_event_id.strip()
            or not capability.source_review_decision_id.strip()
            or not capability.confirmed_actor_id.strip()
            or line_id not in expected_ids
            or line_id in seen
            or capability.direction != direction
            or capability.invoice_mode != invoice_mode
            or not account_code
            or account_code not in _semantic_candidate_codes(
                selection,
                direction=direction,
                semantic_role=capability.semantic_role,
                require_verified_detail=True,
            )
        ):
            return SemanticAccountAuthoritySet()
        seen.add(line_id)
        resolved.append(
            LineAccountAuthority(
                canonical_line_id=line_id,
                account_code=account_code,
                semantic_role=capability.semantic_role,
                source="verified_rule",
                source_id=f"{capability.rule_id}:{capability.rule_version}",
            )
        )
    return SemanticAccountAuthoritySet(line_authorities=tuple(resolved))


def _resolve_accepted_ai_authority(
    *,
    semantic_attempts: tuple[dict[str, object], ...],
    accepted_attempt_id: str,
    canonical_items: tuple[object, ...],
    selection: AccountSelection,
    direction: str,
) -> SemanticAccountAuthoritySet:
    expected_ids = tuple(
        str(getattr(line, "canonical_line_id", "") or "").strip()
        for line in canonical_items
        if str(getattr(line, "canonical_line_id", "") or "").strip()
    )
    if not expected_ids or not accepted_attempt_id:
        return SemanticAccountAuthoritySet()
    matching = [item for item in semantic_attempts if str(item.get("attempt_id") or "") == accepted_attempt_id]
    if len(matching) != 1:
        return SemanticAccountAuthoritySet()
    attempt = matching[0]
    attempt_line_ids = tuple(str(item) for item in (attempt.get("canonical_line_ids") or ()))
    if (
        attempt.get("accepted") is not True
        or str(attempt.get("superseded_by_attempt_id") or "")
        or str(attempt.get("stage") or "") not in {
            "initial_account_decision",
            "account_correction",
            "correction_account_decision",  # legacy persisted stage name
            "research_synthesis",
        }
        or len(attempt_line_ids) != len(expected_ids)
        or len(set(attempt_line_ids)) != len(attempt_line_ids)
        or set(attempt_line_ids) != set(expected_ids)
        or tuple(attempt.get("validation_errors") or ())
    ):
        return SemanticAccountAuthoritySet()
    response = attempt.get("validated_response")
    if not isinstance(response, dict) or response.get("needs_research") is not False:
        return SemanticAccountAuthoritySet()
    attempt_candidates = {
        str(code).strip() for code in (attempt.get("candidate_account_codes") or ()) if str(code).strip()
    }
    current_candidates = _semantic_candidate_codes(selection, direction=direction)
    allowed_codes = attempt_candidates & current_candidates
    raw_decisions = response.get("line_decisions")
    decisions = tuple(raw_decisions) if isinstance(raw_decisions, (list, tuple)) else ()
    by_line: dict[str, dict[str, object]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            return SemanticAccountAuthoritySet()
        line_id = str(decision.get("canonical_line_id") or "").strip()
        if not line_id or line_id in by_line:
            return SemanticAccountAuthoritySet()
        by_line[line_id] = decision
    top_level_code = str(response.get("suggested_account_code") or "").strip()
    resolved: list[LineAccountAuthority] = []
    if len(expected_ids) == 1 and not decisions:
        if top_level_code not in allowed_codes:
            return SemanticAccountAuthoritySet()
        resolved.append(LineAccountAuthority(expected_ids[0], top_level_code, "semantic_account", "accepted_ai", accepted_attempt_id))
    else:
        if set(by_line) != set(expected_ids):
            return SemanticAccountAuthoritySet()
        for line_id in expected_ids:
            decision = by_line[line_id]
            code = str(decision.get("suggested_account_code") or "").strip()
            if not code or code not in allowed_codes or decision.get("needs_research") is not False:
                return SemanticAccountAuthoritySet()
            if len(expected_ids) == 1 and top_level_code and top_level_code != code:
                return SemanticAccountAuthoritySet()
            resolved.append(LineAccountAuthority(line_id, code, "semantic_account", "accepted_ai", accepted_attempt_id))
    return SemanticAccountAuthoritySet(
        line_authorities=tuple(resolved),
        accepted_attempt=AcceptedSemanticAttemptRef(accepted_attempt_id),
    )


def _combine_authorities(
    verified: SemanticAccountAuthoritySet,
    accepted_ai: SemanticAccountAuthoritySet,
) -> SemanticAccountAuthoritySet:
    combined: dict[str, LineAccountAuthority] = {}
    for item in (*accepted_ai.line_authorities, *verified.line_authorities):
        existing = combined.get(item.canonical_line_id)
        if existing and existing.account_code != item.account_code:
            if item.source == "verified_rule":
                combined[item.canonical_line_id] = item
                continue
            if existing.source == "verified_rule":
                continue
            return SemanticAccountAuthoritySet()
        combined[item.canonical_line_id] = existing or item
    return SemanticAccountAuthoritySet(
        line_authorities=tuple(combined.values()),
        accepted_attempt=accepted_ai.accepted_attempt,
    )


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
    if intended not in {"purchase", "sales"}:
        raise ValueError("invoice processing requires purchase or sales intake direction")

    explicit_direction = _explicit_party_direction(invoice, client_profile)
    return_evidence = ("return_invoice_signal",) if _is_return_invoice(invoice) else ()
    if explicit_direction:
        detected, confidence, evidence = explicit_direction
        resolved_evidence = tuple(dict.fromkeys((*evidence, *return_evidence)))
        if detected != intended:
            return detected, confidence, (*resolved_evidence, f"intake_conflict_{intended}")
        return detected, confidence, resolved_evidence

    issuer_tax_id = _only_digits(getattr(invoice, "issuer_tax_id", ""))
    recipient_tax_id = _only_digits(getattr(invoice, "recipient_tax_id", ""))
    if issuer_tax_id or recipient_tax_id:
        raise ValueError("party identity does not identify the client")
    is_text_pdf = (
        str(getattr(invoice, "file_name", "")).lower().endswith(".pdf")
        and bool(getattr(invoice, "text_extractable", False))
        and int(getattr(invoice, "extracted_char_count", 0) or 0) > 0
    )
    if not is_text_pdf:
        raise ValueError("party identity is required for non-PDF invoice intake")

    return intended, 88, (f"intake_category_{intended}", "party_identity_unverified", *return_evidence)


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
        "provider_id": str(getattr(invoice, "provider_id", "") or "").strip(),
        "service_profile": str(getattr(invoice, "service_profile", "") or "").strip(),
        "provider_match_kind": str(getattr(invoice, "provider_match_kind", "") or "").strip(),
        "provider_match_reason": str(getattr(invoice, "provider_match_reason", "") or "").strip(),
        "provider_directory_version": int(getattr(invoice, "provider_directory_version", 0) or 0),
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


def _category_label(category: str, product_identity: str = "") -> str:
    identity = str(product_identity or "").strip()
    labels = {
        "personal_clothing": "Pantolon / giyim urunu",
        "e_fatura_hizmeti": "E-fatura / yazilim hizmeti",
        "bulut_yazilim_hizmeti": "Bulut / yazilim hizmeti",
        "elektrik": "Elektrik / enerji gideri",
        "internet": "Internet hizmeti",
        "kira": "Kira gideri",
        "kargo": "Kargo / nakliye hizmeti",
        "isitme_cihazi": "Isitme cihazi",
        "isitme_cihazi_pili": "Isitme cihazi pili",
        "kisisel_bakim_kozmetik": "Kisisel bakim / kozmetik",
    }
    label = labels.get(str(category or ""), str(category or "").replace("_", " ").strip())
    if identity and label and identity.lower() not in label.lower():
        return f"{identity} / {label}"
    return label or identity or "-"


def _confidence_label(confidence: int) -> str:
    if confidence >= 80:
        return "Yuksek"
    if confidence >= 55:
        return "Orta"
    return "Dusuk"


def _business_relation_label(relation: str, status: str) -> str:
    labels = {
        "core_business": "Faaliyetle dogrudan iliskili",
        "adjacent_business": "Faaliyetle iliskili gorunuyor",
        "general_overhead": "Genel isletme gideri",
        "weak_match": "Faaliyet iliskisi net degil",
        "off_activity": "Faaliyetle dogrudan iliskili gorunmuyor",
        "blocked_or_regulated": "Ozel kontrol gerektiren kalem",
    }
    return labels.get(str(relation or ""), labels.get(str(status or ""), str(status or "").replace("_", " ").strip() or "-"))


def _counterparty_match_label(
    *,
    counterparty_match: CounterpartyMatch | None,
    suggested_counterparty: str,
    counterparty_title: str,
) -> str:
    title = str(counterparty_title or "").strip()
    if counterparty_match and counterparty_match.account_code:
        reason_labels = {
            "tax_id_exact": "VKN birebir eslesti",
            "iban_exact": "IBAN birebir eslesti",
            "title_similarity": "Unvan benzerligiyle eslesti",
            "title_token_overlap": "Unvan benzerligiyle eslesti",
            "learning_event": "Onceki musavir kararindan eslesti",
            "accountant_corrected": "Musavir duzeltmesiyle eslesti",
        }
        reason = reason_labels.get(counterparty_match.match_reason, "Cari eslesmesi bulundu")
        name = counterparty_match.account_name or title
        pieces = [reason, counterparty_match.account_code, name]
        return " / ".join(piece for piece in pieces if str(piece or "").strip())
    if suggested_counterparty:
        return f"Yeni cari onerisi / {suggested_counterparty}" + (f" / {title}" if title else "")
    return f"Cari bulunamadi" + (f" / {title}" if title else "")


def _amount_check(invoice: ParsedInvoice) -> str:
    try:
        goods = money(invoice.goods_services_total)
        vat = money(invoice.vat_total)
        total = money(invoice.payable_total)
    except Exception:  # noqa: BLE001 - narrative should not break simulation
        return ""
    return "Matrah + KDV toplamla uyumlu" if abs((goods + vat) - total) <= MONEY_TOLERANCE else "Tutarlar kontrol gerektiriyor"


def _non_empty_fact_rows(rows: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {label: value for label, value in rows if str(value or "").strip()}


def _decision_narrative(
    *,
    invoice: ParsedInvoice,
    relevance: BusinessRelevance,
    selected_account_code: str,
    selected_account_name: str,
    counterparty_match: CounterpartyMatch | None,
    suggested_counterparty: str,
    counterparty_title: str,
    counterparty_tax_id: str,
    export_gate_reason: str,
    ai_product_identity: str,
) -> dict[str, object]:
    invoice_product_line = str(invoice.line_items[0] if invoice.line_items else invoice.provider_hint or "").strip()
    unresolved = ""
    if relevance.status in {"supheli", "is_alani_disi"} or relevance.relation in {"weak_match", "off_activity"}:
        unresolved = "Urunun faaliyetle baglantisi net degil."
    if counterparty_match and counterparty_match.requires_review:
        unresolved = "Cari eslesmesi kesin degil." if not unresolved else f"{unresolved} Cari eslesmesi kesin degil."
    elif not counterparty_match and suggested_counterparty:
        unresolved = "Cari hesabi yeni acilacak gibi gorunuyor." if not unresolved else f"{unresolved} Cari hesabi yeni acilacak gibi gorunuyor."
    read_facts = _non_empty_fact_rows(
        (
            ("Fatura urun satiri", invoice_product_line),
            ("Satici unvani", counterparty_title or invoice.provider_hint),
            ("Vergi no", counterparty_tax_id),
            ("Fatura tarihi", invoice.issue_date),
            ("Matrah", invoice.goods_services_total),
            ("KDV orani", ", ".join(f"%{rate}" for rate in invoice.vat_rates if str(rate).strip())),
            ("KDV tutari", invoice.vat_total),
            ("Genel toplam", invoice.payable_total),
            ("Tutar kontrolu", _amount_check(invoice)),
        )
    )
    return {
        "invoice_product_line": invoice_product_line,
        "fisora_interpretation": _category_label(relevance.classification.category, ai_product_identity),
        "business_relation": _business_relation_label(relevance.relation, relevance.status),
        "account_code": selected_account_code,
        "account_name": selected_account_name,
        "counterparty_match": _counterparty_match_label(
            counterparty_match=counterparty_match,
            suggested_counterparty=suggested_counterparty,
            counterparty_title=counterparty_title,
        ),
        "confidence_label": _confidence_label(max(relevance.classification.confidence, relevance.confidence)),
        "unresolved_info": unresolved,
        "read_facts": read_facts,
        "export_gate_reason": export_gate_reason,
    }


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
    names: dict[str, str] = dict(selection.account_names)
    for candidates in selection.account_candidates.values():
        for candidate in candidates:
            code = str(candidate.get("code") or "").strip()
            name = str(candidate.get("name") or "").strip()
            if code and name:
                names.setdefault(code, name)
    if counterparty_match:
        code = str(counterparty_match.account_code or "").strip()
        name = str(counterparty_match.account_name or "").strip()
        if code and name:
            names.setdefault(code, name)
    return names


def _entry_lines(entry: JournalEntry | None, account_names: dict[str, str] | None = None) -> tuple[dict[str, Any], ...]:
    if entry is None:
        return ()
    names = account_names or {}
    return tuple(
        {
            "account_code": line.account_code,
            "description": names.get(line.account_code, "") or line.description,
            "debit": f"{line.debit:.2f}",
            "credit": f"{line.credit:.2f}",
            **(
                {"tax_rate": f"{line.tax_rate:.4f}"}
                if line.tax_rate is not None
                else {}
            ),
            **(
                {
                    "vat_group_id": line.vat_group_id,
                    "contributing_line_ids": list(line.contributing_line_ids),
                    "source_line_numbers": list(line.source_line_numbers),
                    "allocated_amounts": [
                        {
                            "canonical_line_id": canonical_line_id,
                            "amount": amount,
                        }
                        for canonical_line_id, amount in line.allocated_amounts
                    ],
                }
                if line.vat_group_id or line.contributing_line_ids
                else {}
            ),
        }
        for line in entry.lines
    )


def _normalize_processing_mode(mode: str | None) -> ProcessingMode:
    if mode in {"conservative", "ai_assisted_draft", "controlled_automation"}:
        return mode  # type: ignore[return-value]
    return "controlled_automation"


def _product_line_hint(invoice: ParsedInvoice) -> str:
    return invoice.line_items[0] if invoice.line_items else ""


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
    account_candidate_details = tuple(
        {
            "code": str(candidate.get("code") or "").strip(),
            "name": str(candidate.get("name") or "").strip(),
            "family": str(candidate.get("code") or "").strip().split(".")[0],
            "group": str(group),
            "reason": str(candidate.get("reason") or "").strip(),
            "semantic_roles": list(candidate.get("semantic_roles") or []),
            "vat_rate": str(candidate.get("vat_rate") or "").strip(),
            "is_detail_account": candidate.get("is_detail_account"),
            "is_active": candidate.get("is_active"),
        }
        for group, candidates in (selection.account_candidates or {}).items()
        for candidate in candidates
        if group in main_groups
        if str(candidate.get("code") or "").strip()
    )
    utility_hints = {
        "electricity": ("elektrik",),
        "water": ("su gider",),
        "natural_gas": ("dogalgaz", "dogal gaz"),
        "gsm_communication": ("haberlesme", "telefon", "gsm"),
        "fixed_internet": ("haberlesme", "internet", "telekom"),
    }.get(str(getattr(invoice, "service_profile", "") or ""), ())
    utility_matches = tuple(
        candidate
        for candidate in account_candidate_details
        if candidate.get("group") == "purchase_expense"
        and any(
            hint
            in unicodedata.normalize("NFKD", str(candidate.get("name") or ""))
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
            for hint in utility_hints
        )
    )
    if direction == "purchase" and utility_matches:
        account_candidate_details = utility_matches
    semantic_candidates = tuple(
        str(candidate.get("code") or "").strip()
        for candidate in account_candidate_details
        if str(candidate.get("code") or "").strip()
    )
    if utility_matches and direction == "purchase":
        base_account_codes = ()
    elif direction_uncertainty:
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
    real_counterparty_candidates = tuple(
        dict.fromkeys(
            str(candidate.get("code") or "").strip()
            for candidate in selection.account_candidates.get("supplier" if direction != "sales" else "customer", ())
            if str(candidate.get("code") or "").strip()
        )
    )
    real_counterparty_candidate_set = set(real_counterparty_candidates)
    counterparty_candidates = tuple(
        dict.fromkeys(
            code
            for code in (
                counterparty_match.account_code
                if counterparty_match and counterparty_match.account_code in real_counterparty_candidate_set
                else "",
                *real_counterparty_candidates,
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


def _vat_group_ai_context(
    context: AiClassificationContext,
    *,
    group: VatAccountingGroup,
    canonical_lines: tuple[dict[str, Any], ...],
    strategy: AiCandidateStrategy,
) -> AiClassificationContext:
    group_line_ids = set(group.line_ids)
    group_lines = tuple(
        line
        for line in canonical_lines
        if str(line.get("canonical_line_id") or "") in group_line_ids
    )
    net_prefixes = account_roles_for(context.accounting_direction)["net"]
    net_candidate_details = tuple(
        candidate
        for candidate in context.account_candidate_details
        if str(candidate.get("code") or "").startswith(net_prefixes)
        and candidate.get("is_detail_account") is not False
        and candidate.get("is_active") is not False
    )
    net_candidate_codes = tuple(
        dict.fromkeys(
            str(candidate.get("code") or "")
            for candidate in net_candidate_details
            if str(candidate.get("code") or "")
        )
    )
    return replace(
        context,
        account_candidates=net_candidate_codes,
        account_candidate_details=net_candidate_details,
        account_candidate_limit=len(net_candidate_codes),
        account_candidate_details_limit=len(net_candidate_details),
        canonical_lines=group_lines,
        vat_group={
            "vat_group_id": group.vat_group_id,
            "rate": group.rate,
            "taxable_amount": f"{group.taxable_amount:.2f}",
            "line_ids": group.line_ids,
        },
        candidate_strategy=replace(strategy, stage="vat_group_account"),
    )


def _classify_vat_accounting_groups(
    classifier: ProductClassifier,
    *,
    groups: tuple[VatAccountingGroup, ...],
    base_context: AiClassificationContext,
    canonical_lines: tuple[dict[str, Any], ...],
    supplier_hint: str,
) -> tuple[AiClassificationResult, ...]:
    results: list[AiClassificationResult] = []
    for group in groups:
        context = _vat_group_ai_context(
            base_context,
            group=group,
            canonical_lines=canonical_lines,
            strategy=base_context.candidate_strategy,
        )
        group_line = " | ".join(line.description for line in group.lines if line.description)
        results.append(
            _classify_with_semantic_authority(
                classifier,
                group_line,
                supplier_hint=supplier_hint,
                context=context,
            )
        )
    return tuple(results)


def _aggregate_group_classification_results(
    results: tuple[AiClassificationResult, ...],
) -> AiClassificationResult | None:
    if not results:
        return None
    selected_codes = {
        result.suggested_account_code
        for result in results
        if result.suggested_account_code
    }
    return replace(
        results[-1],
        ai_used=any(result.ai_used for result in results),
        suggested_account_code=next(iter(selected_codes)) if len(selected_codes) == 1 else "",
        risk_flags=tuple(dict.fromkeys(flag for result in results for flag in result.risk_flags)),
        needs_research=any(result.needs_research for result in results),
        ai_trace=tuple(trace for result in results for trace in result.ai_trace),
        semantic_attempts=tuple(
            attempt
            for result in results
            for attempt in result.semantic_attempts
        ),
        line_decisions=tuple(
            decision
            for result in results
            for decision in result.line_decisions
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


def _line_decision_invoice_entry(
    *,
    invoice: ParsedInvoice,
    canonical_items: tuple[object, ...],
    line_decisions: list[dict[str, object]],
    selection: AccountSelection,
    direction: str,
    counterparty_account: str,
    return_invoice: bool = False,
    non_deductible: bool = False,
) -> JournalEntry | None:
    decisions = {
        str(item.get("canonical_line_id") or ""): str(item.get("account_code") or "")
        for item in line_decisions
    }
    net_groups: dict[tuple[str, str], Decimal] = {}
    net_sources: dict[tuple[str, str], list[tuple[str, str]]] = {}
    tax_groups: dict[tuple[str, Decimal, str], Decimal] = {}
    tax_sources: dict[tuple[str, Decimal, str], list[tuple[str, str]]] = {}
    gross_sources: list[tuple[str, str]] = []
    gross_total = Decimal("0.00")
    source_line_no_by_id: dict[str, int] = {}
    for source_line_no, item in enumerate(canonical_items, start=1):
        line_id = str(getattr(item, "canonical_line_id", "") or "")
        source_line_no_by_id[line_id] = source_line_no
        vat_group_id = str(getattr(item, "vat_group_id", "") or "")
        account_code = decisions.get(line_id, "")
        net = _decimal_or_none(str(getattr(item, "taxable_amount", "") or ""))
        tax = _decimal_or_none(str(getattr(item, "tax_amount", "") or ""))
        raw_rate = str(getattr(item, "vat_rate", "") or "0").replace(",", ".")
        try:
            rate_percent = Decimal(raw_rate)
        except (InvalidOperation, ValueError):
            return None
        if not account_code or net is None or tax is None or net < 0 or tax < 0:
            return None
        hearing_device_zero_vat = (
            direction == "sales"
            and rate_percent > 0
            and _is_hearing_device_line(str(getattr(item, "description", "") or ""))
        )
        semantic_amount = (
            net + tax
            if (non_deductible and direction == "purchase") or hearing_device_zero_vat
            else net
        )
        net_key = (account_code, vat_group_id)
        net_groups[net_key] = (net_groups.get(net_key, Decimal("0.00")) + semantic_amount).quantize(
            Decimal("0.01")
        )
        net_sources.setdefault(net_key, []).append((line_id, f"{semantic_amount:.2f}"))
        if tax > 0 and not (non_deductible and direction == "purchase") and not hearing_device_zero_vat:
            vat_account = (
                _sales_vat_account_for_rate(selection, rate_percent / Decimal("100"))
                if direction == "sales"
                else _purchase_vat_account_for_rate(selection, rate_percent / Decimal("100"))
            )
            key = (vat_account, rate_percent, vat_group_id)
            tax_groups[key] = (tax_groups.get(key, Decimal("0.00")) + tax).quantize(
                Decimal("0.01")
            )
            tax_sources.setdefault(key, []).append((line_id, f"{tax:.2f}"))
        gross_total = (gross_total + net + tax).quantize(Decimal("0.01"))
        gross_sources.append((line_id, f"{(net + tax):.2f}"))
    expected_total = _decimal_or_none(invoice.payable_total)
    if (
        not counterparty_account
        or not net_groups
        or expected_total is None
        or abs(gross_total - expected_total) > MONEY_TOLERANCE
    ):
        return None
    lines: list[JournalLine] = []
    if direction == "sales":
        lines.append(
            JournalLine(
                counterparty_account,
                "Alici cari",
                credit=gross_total,
                contributing_line_ids=tuple(line_id for line_id, _ in gross_sources),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in gross_sources),
                allocated_amounts=tuple(gross_sources),
            )
            if return_invoice
            else JournalLine(
                counterparty_account,
                "Alici cari",
                debit=gross_total,
                contributing_line_ids=tuple(line_id for line_id, _ in gross_sources),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in gross_sources),
                allocated_amounts=tuple(gross_sources),
            )
        )
        lines.extend(
            JournalLine(
                account_code,
                "Satis iadesi",
                debit=amount,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in net_sources[(account_code, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in net_sources[(account_code, vat_group_id)]),
                allocated_amounts=tuple(net_sources[(account_code, vat_group_id)]),
            )
            if return_invoice
            else JournalLine(
                account_code,
                "Satis",
                credit=amount,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in net_sources[(account_code, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in net_sources[(account_code, vat_group_id)]),
                allocated_amounts=tuple(net_sources[(account_code, vat_group_id)]),
            )
            for (account_code, vat_group_id), amount in net_groups.items()
        )
        lines.extend(
            JournalLine(
                account_code,
                "Hesaplanan KDV iadesi",
                debit=amount,
                tax_rate=rate,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                allocated_amounts=tuple(tax_sources[(account_code, rate, vat_group_id)]),
            )
            if return_invoice
            else JournalLine(
                account_code,
                "Hesaplanan KDV",
                credit=amount,
                tax_rate=rate,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                allocated_amounts=tuple(tax_sources[(account_code, rate, vat_group_id)]),
            )
            for (account_code, rate, vat_group_id), amount in tax_groups.items()
        )
    elif direction == "purchase":
        lines.extend(
            JournalLine(
                account_code,
                "Alis iadesi",
                credit=amount,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in net_sources[(account_code, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in net_sources[(account_code, vat_group_id)]),
                allocated_amounts=tuple(net_sources[(account_code, vat_group_id)]),
            )
            if return_invoice
            else JournalLine(
                account_code,
                "Alis",
                debit=amount,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in net_sources[(account_code, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in net_sources[(account_code, vat_group_id)]),
                allocated_amounts=tuple(net_sources[(account_code, vat_group_id)]),
            )
            for (account_code, vat_group_id), amount in net_groups.items()
        )
        lines.extend(
            JournalLine(
                account_code,
                "Indirilecek KDV iadesi",
                credit=amount,
                tax_rate=rate,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                allocated_amounts=tuple(tax_sources[(account_code, rate, vat_group_id)]),
            )
            if return_invoice
            else JournalLine(
                account_code,
                "Indirilecek KDV",
                debit=amount,
                tax_rate=rate,
                vat_group_id=vat_group_id,
                contributing_line_ids=tuple(line_id for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in tax_sources[(account_code, rate, vat_group_id)]),
                allocated_amounts=tuple(tax_sources[(account_code, rate, vat_group_id)]),
            )
            for (account_code, rate, vat_group_id), amount in tax_groups.items()
        )
        lines.append(
            JournalLine(
                counterparty_account,
                "Satici cari",
                debit=gross_total,
                contributing_line_ids=tuple(line_id for line_id, _ in gross_sources),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in gross_sources),
                allocated_amounts=tuple(gross_sources),
            )
            if return_invoice
            else JournalLine(
                counterparty_account,
                "Satici cari",
                credit=gross_total,
                contributing_line_ids=tuple(line_id for line_id, _ in gross_sources),
                source_line_numbers=tuple(source_line_no_by_id[line_id] for line_id, _ in gross_sources),
                allocated_amounts=tuple(gross_sources),
            )
        )
    else:
        return None
    entry = JournalEntry(
        entry_type=f"line_decision_{direction}_{'return' if return_invoice else 'invoice'}",
        entry_date=invoice.issue_date or "1900-01-01",
        description=invoice.file_name,
        lines=tuple(lines),
    )
    return entry if entry.is_balanced else None


def _line_items_missing_relevance() -> BusinessRelevance:
    classification = ProductClassification(
        raw_line="",
        category="bilinmeyen",
        confidence=0,
        evidence=("line_items_missing",),
    )
    return BusinessRelevance(
        status="supheli",
        confidence=0,
        reason="Fatura satiri okunamadigi icin urun/hizmet anlamlandirilamadi.",
        evidence=("line_items_missing",),
        classification=classification,
        relation="weak_match",
        account_treatment="manual_review",
        requires_accountant_review=True,
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
    if "cancelled_invoice_visible" in review_reasons and not entry:
        return "Kaynak fatura iptal gorunuyor; muhasebe kaydi onerilmez."
    if "zero_payable_no_posting" in review_reasons and not entry:
        return "Kaynak belge toplamı sifir; muhasebe kaydi onerilmez."
    if processing_mode == "conservative":
        return "Conservative mod: mustavir onayi olmadan export kapali."
    if not entry or not entry.is_balanced:
        return "Fis dengeli degil veya taslak satirlari eksik."
    if counterparty_match and counterparty_match.requires_review:
        return f"Cari eslesmesi kontrol istiyor: {counterparty_match.match_reason}."
    if "cancelled_invoice_visible" in review_reasons:
        return "Bu fatura iptal gorunmektedir; fis taslagi hazir ama mustavir kontrolu gerekir."
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
    if "cancelled_invoice_visible" in blockers:
        return "Iptal kaynagi dogrula; belge icin muhasebe kaydi onerilmiyor."
    if "zero_payable_no_posting" in blockers:
        return "Ödenecek tutar 0,00 TL; fatura tamamen indirimle kapandığı için yevmiye kaydı oluşturulmayacak."
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
    verified_rule_bindings: tuple[dict[str, object], ...] = (),
    verified_rule_authorities: tuple[VerifiedRuleAuthorityV1, ...] = (),
) -> SimulatedInvoiceResult:
    mode = _normalize_processing_mode(processing_mode)
    reasons = tuple(
        dict.fromkeys(
            (
                *invoice.risk_flags,
                *invoice.parse_notes,
                *tuple(getattr(invoice, "utility_exception_markers", ()) or ()),
            )
        )
    )
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
    canonical_invoice = getattr(invoice, "canonical_invoice", None)
    canonical_validation = getattr(canonical_invoice, "validation", None)
    canonical_line_count = (
        len(tuple(getattr(canonical_invoice, "line_items", ()) or ()))
        if canonical_invoice
        else len(invoice.line_items)
    )
    canonical_validation_status = str(getattr(canonical_validation, "status", "") or "")
    canonical_validation_reasons = tuple(str(reason) for reason in getattr(canonical_validation, "reason_codes", ()) or ())
    canonical_extraction_notes = tuple(
        str(note) for note in getattr(canonical_invoice, "extraction_notes", ()) or ()
    )
    canonical_extraction_ai_used = bool(getattr(canonical_invoice, "ai_used", False)) if canonical_invoice else False
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
    line_items_missing = not raw_line.strip()
    relevance = (
        _line_items_missing_relevance()
        if line_items_missing
        else (
            assess_business_relevance(
                raw_line,
                client_profile,
                supplier_hint=invoice.provider_hint,
                classification=classification_override,
            )
            if client_profile
            else _not_assessed_relevance(raw_line)
        )
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
    canonical_items = tuple(getattr(canonical_invoice, "line_items", ()) or ()) if canonical_invoice else ()
    try:
        vat_accounting_groups = (
            build_vat_accounting_groups(canonical_invoice)
            if canonical_invoice and canonical_items
            else ()
        )
    except ValueError:
        vat_accounting_groups = ()
    return_invoice = _is_return_invoice(invoice)
    invoice_mode = "return" if return_invoice else "ordinary"
    verified_authority = _resolve_verified_rule_authority(
        capabilities=verified_rule_authorities,
        canonical_items=canonical_items,
        selection=selection,
        client_id=client_profile.client_id if client_profile else "",
        direction=direction,
        invoice_mode=invoice_mode,
    )
    # Compatibility dictionaries are intentionally non-authoritative.
    del verified_rule_bindings
    ai_gate = invoice_ai_gate(
        product_category=relevance.classification.category,
        product_confidence=relevance.classification.confidence,
        business_relation=relevance.relation,
        account_treatment=relevance.account_treatment,
        line_hint=raw_line,
        canonical_line_ids=tuple(
            str(getattr(line, "canonical_line_id", "") or "") for line in canonical_items
        ),
        semantic_authority=verified_authority,
    )
    ai_product_identity = ""
    ai_research_requested = False
    ai_research_query = ""
    ai_candidate_strategy = "single_stage"
    ai_selected_account_families: tuple[str, ...] = ()
    ai_stage_evidence: tuple[dict[str, object], ...] = ()
    ai_trace_records: list[dict[str, object]] = []
    semantic_attempt_records: list[dict[str, object]] = []
    accepted_semantic_attempt_id = ""
    ai_account_candidate_count = 0
    ai_counterparty_candidate_count = 0
    base_context: AiClassificationContext | None = None
    classification_result: AiClassificationResult | None = None
    counterparty_result: AiClassificationResult | None = None
    group_classification_results: tuple[AiClassificationResult, ...] = ()
    canonical_ai_lines = tuple(
        {
            "canonical_line_id": str(getattr(line, "canonical_line_id", "") or ""),
            "source_position": str(getattr(line, "source_position", "") or ""),
            "description": str(getattr(line, "description", "") or ""),
            "taxable_amount": str(getattr(line, "taxable_amount", "") or ""),
            "vat_rate": str(getattr(line, "vat_rate", "") or ""),
        }
        for line in canonical_items
    )
    use_line_batch = len(canonical_items) > 1
    no_posting_candidate = "cancelled_invoice_visible" in reasons or (amount is not None and amount <= 0)
    use_invoice_account = bool(
        direction == "purchase"
        and canonical_items
        and str(getattr(invoice, "service_profile", "") or "")
    )
    use_vat_group_account = (
        bool(vat_accounting_groups)
        and not use_invoice_account
        and relevance.account_treatment != "non_deductible_review"
    )
    if line_items_missing:
        ai_skipped_reason = "line_items_missing"
    elif no_posting_candidate:
        ai_skipped_reason = "no_posting"
    elif client_profile and product_classifier and ai_gate.needs_ai:
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
            family_result = _classify_with_semantic_authority(
                product_classifier,
                raw_line,
                supplier_hint=invoice.provider_hint,
                context=family_context,
            )
            selected_families = family_result.selected_account_families
            ai_trace_records.extend(family_result.ai_trace)
            semantic_attempt_records.extend(family_result.semantic_attempts)
            accepted_semantic_attempt_id = (
                family_result.accepted_semantic_attempt_id or accepted_semantic_attempt_id
            )
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
            final_context = replace(final_context, canonical_lines=canonical_ai_lines)
            if use_vat_group_account:
                group_classification_results = _classify_vat_accounting_groups(
                    product_classifier,
                    groups=vat_accounting_groups,
                    base_context=final_context,
                    canonical_lines=canonical_ai_lines,
                    supplier_hint=invoice.provider_hint,
                )
                classification_result = _aggregate_group_classification_results(
                    group_classification_results
                )
            else:
                if use_line_batch:
                    final_context = replace(
                        final_context,
                        canonical_lines=canonical_ai_lines,
                        candidate_strategy=replace(final_context.candidate_strategy, stage="line_batch"),
                    )
                classification_result = _classify_with_semantic_authority(
                    product_classifier,
                    raw_line,
                    supplier_hint=invoice.provider_hint,
                    context=final_context,
                )
            if classification_result is None:
                classification_result = _classify_with_semantic_authority(
                    product_classifier,
                    raw_line,
                    supplier_hint=invoice.provider_hint,
                    context=replace(
                        final_context,
                        canonical_lines=canonical_ai_lines,
                        candidate_strategy=replace(final_context.candidate_strategy, stage="line_batch"),
                    ),
                )
            ai_trace_records.extend(classification_result.ai_trace)
            semantic_attempt_records.extend(classification_result.semantic_attempts)
            accepted_semantic_attempt_id = (
                classification_result.accepted_semantic_attempt_id or accepted_semantic_attempt_id
            )
            stage_records.append(_stage_evidence(classification_result))
        else:
            single_context = replace(
                base_context,
                canonical_lines=canonical_ai_lines,
                account_candidate_limit=policy.single_stage_account_limit,
                counterparty_candidate_limit=policy.counterparty_limit,
                account_candidate_details_limit=policy.single_stage_account_limit,
                candidate_strategy=AiCandidateStrategy(
                    mode="single_stage",
                    stage=(
                        "invoice_account"
                        if use_invoice_account
                        else "line_batch"
                        if use_line_batch
                        else "final_account"
                    ),
                    account_candidate_count=len(base_context.account_candidates),
                    counterparty_candidate_count=len(base_context.counterparty_candidates),
                ),
            )
            if use_invoice_account:
                classification_result = _classify_with_semantic_authority(
                    product_classifier,
                    raw_line,
                    supplier_hint=invoice.provider_hint,
                    context=single_context,
                )
            elif use_vat_group_account:
                group_classification_results = _classify_vat_accounting_groups(
                    product_classifier,
                    groups=vat_accounting_groups,
                    base_context=single_context,
                    canonical_lines=canonical_ai_lines,
                    supplier_hint=invoice.provider_hint,
                )
                classification_result = _aggregate_group_classification_results(
                    group_classification_results
                )
            else:
                classification_result = _classify_with_semantic_authority(
                    product_classifier,
                    raw_line,
                    supplier_hint=invoice.provider_hint,
                    context=single_context,
                )
            if classification_result is None:
                classification_result = _classify_with_semantic_authority(
                    product_classifier,
                    raw_line,
                    supplier_hint=invoice.provider_hint,
                    context=single_context,
                )
            ai_trace_records.extend(classification_result.ai_trace)
            semantic_attempt_records.extend(classification_result.semantic_attempts)
            accepted_semantic_attempt_id = (
                classification_result.accepted_semantic_attempt_id or accepted_semantic_attempt_id
            )
            stage_records.append(_stage_evidence(classification_result))
        counterparty_needs_ai = not (
            counterparty_match
            and counterparty_match.account_code
            and not counterparty_match.requires_review
        )
        if base_context.counterparty_candidates and counterparty_needs_ai:
            counterparty_context = _counterparty_resolution_context(
                base_context,
                policy=policy,
                mode=ai_candidate_strategy,
            )
            counterparty_result = _classify_with_semantic_authority(
                product_classifier,
                raw_line,
                supplier_hint=invoice.provider_hint,
                context=counterparty_context,
            )
            ai_trace_records.extend(counterparty_result.ai_trace)
            semantic_attempt_records.extend(counterparty_result.semantic_attempts)
            accepted_semantic_attempt_id = (
                counterparty_result.accepted_semantic_attempt_id or accepted_semantic_attempt_id
            )
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
    ai_attempted_account_code = _attempted_ai_account_code(classification_result)
    if ai_suggested_counterparty_code and counterparty_result is not None:
        counterparty_match = CounterpartyMatch(
            account_code=ai_suggested_counterparty_code,
            account_name=selection.account_names.get(ai_suggested_counterparty_code, ""),
            confidence=counterparty_result.classification.confidence,
            match_reason="ai_real_chart_candidate",
            requires_review=counterparty_result.classification.confidence < 80,
        )
        suggested_counterparty = ai_suggested_counterparty_code
        counterparty_creation_suggestion = None
        if direction == "purchase":
            supplier_account = ai_suggested_counterparty_code
    if group_classification_results:
        accepted_ai_authority = SemanticAccountAuthoritySet()
        for group, group_result in zip(
            vat_accounting_groups,
            group_classification_results,
            strict=True,
        ):
            accepted_ai_authority = _combine_authorities(
                accepted_ai_authority,
                _resolve_accepted_ai_authority(
                    semantic_attempts=group_result.semantic_attempts,
                    accepted_attempt_id=group_result.accepted_semantic_attempt_id,
                    canonical_items=group.lines,
                    selection=selection,
                    direction=direction,
                ),
            )
    else:
        accepted_ai_authority = _resolve_accepted_ai_authority(
            semantic_attempts=tuple(semantic_attempt_records),
            accepted_attempt_id=accepted_semantic_attempt_id,
            canonical_items=canonical_items,
            selection=selection,
            direction=direction,
        )
    semantic_authority = _combine_authorities(verified_authority, accepted_ai_authority)
    canonical_line_ids = tuple(
        str(getattr(item, "canonical_line_id", "") or "") for item in canonical_items
    )
    utility_exception_markers = tuple(getattr(invoice, "utility_exception_markers", ()) or ())
    if not utility_exception_requires_review(
        utility_exception_markers,
        has_profile_authority=verified_authority.exactly_covers(canonical_line_ids),
    ):
        reasons = tuple(reason for reason in reasons if reason not in set(utility_exception_markers))
    authority_by_line = semantic_authority.account_by_line()
    ai_decision_by_line = {
        str(item.get("canonical_line_id") or ""): item
        for item in (classification_result.line_decisions if classification_result else ())
        if str(item.get("canonical_line_id") or "")
    }
    structured_line_decisions: list[dict[str, object]] = []
    for index, canonical_line in enumerate(canonical_items):
        line_id = str(getattr(canonical_line, "canonical_line_id", "") or "")
        authority = authority_by_line.get(line_id)
        if authority is None:
            continue
        ai_line_decision = ai_decision_by_line.get(line_id, {})
        vat_group_id = str(
            ai_line_decision.get("vat_group_id")
            or getattr(canonical_line, "vat_group_id", "")
            or ""
        )
        structured_line_decisions.append(
            {
                "canonical_line_id": line_id,
                "source_position": str(getattr(canonical_line, "source_position", "") or ""),
                "account_code": authority.account_code,
                "counterparty_code": ai_suggested_counterparty_code,
                "product_identity": ai_product_identity,
                "reason": "Accepted semantic account authority.",
                "provider": ai_provider if authority.source == "accepted_ai" else "verified_rule",
                "needs_research": False,
                "research_query": "",
                "decision_source": authority.source,
                "decision_origin": (
                    "confirmed_line_exception"
                    if authority.source == "verified_rule"
                    else "vat_group_default"
                    if vat_group_id
                    else authority.source
                ),
                "vat_group_id": vat_group_id,
                "possible_exception": bool(ai_line_decision.get("possible_exception")),
                "group_reason": str(ai_line_decision.get("reason") or ""),
                "authority_source_id": authority.source_id,
                "line_index": index + 1,
            }
        )
    if canonical_items:
        line_coverage = validate_line_decision_coverage(canonical_items, structured_line_decisions)
        if not no_posting_candidate and (line_coverage.status != "valid" or any(
            not str(decision.get("account_code") or "") for decision in structured_line_decisions
        )):
            reasons = tuple(dict.fromkeys((*reasons, "ai_line_decision_incomplete")))
    else:
        line_coverage = validate_line_decision_coverage(canonical_items, structured_line_decisions)
    authoritative_account = (
        semantic_authority.line_authorities[0].account_code
        if semantic_authority.exactly_covers(tuple(
            str(getattr(item, "canonical_line_id", "") or "") for item in canonical_items
        ))
        else ""
    )
    static_fallback_account = ""
    static_fallback_suppressed = False
    ai_resolution_status = "resolved"
    ai_retry_reason = ""
    semantic_authority_missing = not authoritative_account
    purchase_account = authoritative_account if direction == "purchase" else ""
    if semantic_authority_missing:
        static_fallback_suppressed = True
        ai_resolution_status = "ai_correction_required"
        ai_retry_reason = _ai_retry_reason(
            ai_skipped_reason=ai_skipped_reason,
            ai_used=ai_used,
            ai_suggested_account_code=ai_suggested_account_code,
            ai_attempted_account_code=ai_attempted_account_code,
            ai_research_requested=ai_research_requested,
        )
    hearing_device_vat_review = direction == "sales" and _sales_hearing_device_vat_review_needed(invoice)
    if hearing_device_vat_review:
        reasons = tuple(dict.fromkeys((*reasons, "hearing_device_vat_should_be_zero")))
    if line_items_missing:
        reasons = tuple(dict.fromkeys((*reasons, "line_items_missing")))

    no_posting_reason = (
        "cancelled_invoice_visible"
        if "cancelled_invoice_visible" in reasons
        else "zero_payable_no_posting"
        if amount is not None and amount <= 0
        else ""
    )
    if no_posting_reason:
        reasons = tuple(dict.fromkeys((*reasons, no_posting_reason)))
        status = "no_posting"
        draft_quality = "no_posting"
        entry = None
        supplier_account = ""
        suggested_counterparty = ""
        counterparty_creation_suggestion = None
        selected_revenue_account = ""
        selected_purchase_vat_account = ""
        selected_sales_vat_account = ""
        selected_customer_account = ""
        static_fallback_suppressed = False
        ai_resolution_status = "resolved"
        ai_retry_reason = ""
    elif static_fallback_suppressed:
        reasons = tuple(dict.fromkeys((*reasons, "ai_correction_required")))
        status = "review_required"
        draft_quality = "ai_correction_required"
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
        selected_revenue_account = authoritative_account
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
        selected_revenue_account = authoritative_account
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

    authority_complete = semantic_authority.exactly_covers(canonical_line_ids)
    if (
        status != "no_posting"
        and authority_complete
        and amount is not None
        and amount > 0
    ):
        deterministic_entry_type = entry.entry_type if entry is not None else ""
        deterministic_draft_quality = draft_quality
        if direction == "sales":
            selected_revenue_account = authoritative_account
        elif direction == "purchase":
            purchase_account = authoritative_account
        line_entry = _line_decision_invoice_entry(
            invoice=invoice,
            canonical_items=canonical_items,
            line_decisions=structured_line_decisions,
            selection=selection,
            direction=direction,
            counterparty_account=selected_customer_account if direction == "sales" else supplier_account,
            return_invoice=return_invoice,
            non_deductible=relevance.account_treatment == "non_deductible_review",
        )
        if line_entry is not None:
            entry = replace(line_entry, entry_type=deterministic_entry_type or line_entry.entry_type)
            authority_accounts = {item.account_code for item in semantic_authority.line_authorities}
            draft_quality = (
                "line_decision_grouped_draft"
                if len(authority_accounts) > 1 and not return_invoice
                else deterministic_draft_quality or (
                    "line_decision_return_review" if return_invoice else "line_decision_grouped_draft"
                )
            )
        else:
            reasons = tuple(dict.fromkeys((*reasons, "line_decision_journal_incomplete")))
            draft_quality = deterministic_draft_quality

    if (
        status != "no_posting"
        and direction == "purchase"
        and authoritative_account
        and str(getattr(invoice, "service_profile", "") or "")
    ):
        component_entry = build_utility_component_purchase_entry(
            invoice=invoice,
            service_expense_account=authoritative_account,
            vat_account=selected_purchase_vat_account or selection.purchase_vat_account,
            supplier_account=supplier_account,
            supplier_description=_counterparty_account_description(
                account=supplier_account,
                suggested_counterparty=suggested_counterparty,
                counterparty_match=counterparty_match,
                base_description="Satici cari",
            ),
        )
        if component_entry is not None:
            entry = component_entry
            reasons = tuple(
                reason
                for reason in reasons
                if reason
                not in {
                    "line_decision_journal_incomplete",
                    "mixed_vat_manual_review",
                    "vat_split_review_required",
                    "vat_split_non_vat_total",
                }
            )
            reasons = tuple(dict.fromkeys((*reasons, *component_entry.risk_flags)))
            draft_quality = (
                "utility_component_purchase_review"
                if component_entry.risk_flags
                else "utility_component_purchase_ready"
            )

    counterparty_reasons: tuple[str, ...] = ()
    if no_posting_reason:
        counterparty_reasons = ()
    elif counterparty_match and counterparty_match.requires_review:
        counterparty_reasons = (f"counterparty_{counterparty_match.match_reason}",)
    elif counterparty_match is None and counterparty_creation_suggestion:
        counterparty_reasons = ("counterparty_missing",)
    onboarding_reasons: tuple[str, ...] = ()
    if no_posting_reason:
        onboarding_reasons = ()
    elif client_profile:
        onboarding = check_client_onboarding(client_profile)
        if not onboarding.is_ready:
            onboarding_reasons = tuple(f"onboarding_missing_{field}" for field in onboarding.missing_fields)
    else:
        onboarding_reasons = ("onboarding_missing_client_profile",)
    direction_reasons = ("direction_conflict_review",) if direction_conflict and not no_posting_reason else ()
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
    if mode_reasons:
        all_reasons = tuple(dict.fromkeys((*all_reasons, *mode_reasons)))
        export_status = "review_required"
    if export_status != "export_ready" and status != "no_posting":
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
        export_gate_reason = "AI semantik hesap karari gecersiz veya tamamlanamadi; duzeltme gerekli."
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
    account_names = _account_names_from_selection(selection, counterparty_match)
    draft_lines = _entry_lines(entry, account_names)
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
    decision_narrative = _decision_narrative(
        invoice=invoice,
        relevance=relevance,
        selected_account_code=selected_account_code,
        selected_account_name=account_names.get(selected_account_code, ""),
        counterparty_match=counterparty_match,
        suggested_counterparty=suggested_counterparty,
        counterparty_title=counterparty_title,
        counterparty_tax_id=counterparty_tax_id,
        export_gate_reason=export_gate_reason,
        ai_product_identity=ai_product_identity,
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
        ai_attempted_account_code=ai_attempted_account_code,
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
            record
            for record in ai_stage_evidence
            if record.get("ai_stage") in {"family_select", "final_account", "vat_group_account"}
        ),
        ai_counterparty_stage_evidence=tuple(
            record for record in ai_stage_evidence if record.get("ai_stage") == "counterparty_resolve"
        ),
        ai_trace=tuple(ai_trace_records),
        semantic_attempts=tuple(semantic_attempt_records),
        accepted_semantic_attempt_id=accepted_semantic_attempt_id,
        ai_account_candidate_count=ai_account_candidate_count,
        ai_counterparty_candidate_count=ai_counterparty_candidate_count,
        ai_quality_scorecard=ai_quality_scorecard,
        ai_resolution_status=ai_resolution_status,
        ai_retry_reason=ai_retry_reason,
        static_fallback_account=static_fallback_account,
        static_fallback_suppressed=static_fallback_suppressed,
        canonical_line_count=canonical_line_count,
        canonical_validation_status=canonical_validation_status,
        canonical_validation_reasons=canonical_validation_reasons,
        canonical_extraction_notes=canonical_extraction_notes,
        canonical_extraction_ai_used=canonical_extraction_ai_used,
        provider_id=str(getattr(invoice, "provider_id", "") or ""),
        service_profile=str(getattr(invoice, "service_profile", "") or ""),
        provider_match_kind=str(getattr(invoice, "provider_match_kind", "") or ""),
        provider_directory_version=int(getattr(invoice, "provider_directory_version", 0) or 0),
        utility_exception_markers=tuple(getattr(invoice, "utility_exception_markers", ()) or ()),
        tax_components=tuple(asdict(component) for component in getattr(invoice, "tax_components", ()) or ()),
        monetary_components=tuple(
            asdict(component) for component in getattr(invoice, "monetary_components", ()) or ()
        ),
        line_decisions=tuple(structured_line_decisions),
        line_decision_coverage=asdict(line_coverage),
        decision_narrative=decision_narrative,
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
    intended_direction: str | None = None,
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
                intended_direction=intended_direction,
            )
            for invoice in invoices
        ),
    )


def simulate_private_matching(
    invoice_dir: Path,
    chart_paths: list[Path],
    client_profile: ClientProfile | None = None,
    product_classifier: ProductClassifier | None = None,
    *,
    intended_direction: str | None = None,
    canonical_extraction_provider: object | None = None,
    canonical_extraction_policy: object | None = None,
) -> list[SimulatedChartRun]:
    client_identity = None
    if client_profile is not None:
        client_identity = {
            "title": client_profile.title,
            "tax_id": client_profile.tax_id,
        }
    invoices = parse_invoice_folder(
        invoice_dir,
        canonical_extraction_provider=canonical_extraction_provider,
        canonical_extraction_policy=canonical_extraction_policy,
        client_identity=client_identity,
    )
    return [
        simulate_chart_run(
            chart_path,
            invoices,
            client_profile,
            product_classifier,
            intended_direction,
        )
        for chart_path in chart_paths
    ]


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
                    "canonicalLineCount": result.canonical_line_count,
                    "canonicalValidationStatus": result.canonical_validation_status,
                    "canonicalValidationReasons": list(result.canonical_validation_reasons),
                    "canonicalExtractionNotes": list(result.canonical_extraction_notes),
                    "canonicalExtractionAiUsed": result.canonical_extraction_ai_used,
                    "decisionNarrative": result.decision_narrative,
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
                    "semanticAttempts": list(result.semantic_attempts),
                    "acceptedSemanticAttemptId": result.accepted_semantic_attempt_id,
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
        "balanced_count": sum(1 for result in results if result.is_balanced),
        "export_ready_count": sum(1 for result in results if result.export_status == "export_ready"),
        "canonical_valid_count": sum(1 for result in results if result.canonical_validation_status == "valid"),
        "canonical_invalid_count": sum(1 for result in results if result.canonical_validation_status == "invalid"),
        "canonical_missing_count": sum(1 for result in results if not result.canonical_validation_status),
        "canonical_ai_used_count": sum(1 for result in results if result.canonical_extraction_ai_used),
        "canonical_ai_failure_count": sum(
            1
            for result in results
            if any(note.startswith("canonical_ai_error:") for note in result.canonical_extraction_notes)
        ),
        "canonical_ai_rejected_count": sum(
            1 for result in results if "canonical_ai_rejected" in result.canonical_extraction_notes
        ),
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
        "provider_failure_count": sum(
            1
            for result in results
            if "ai_provider_error" in result.ai_risk_flags
            or any(note.startswith("canonical_ai_error:") for note in result.canonical_extraction_notes)
        ),
        "review_reason_counts": {
            reason: review_reasons.count(reason)
            for reason in sorted(set(review_reasons))
        },
    }


def write_review_ui_json(runs: list[SimulatedChartRun], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build_review_ui_payload(runs), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
