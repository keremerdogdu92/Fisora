from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from app.domain.business_relevance import (
    BusinessRelevance,
    ClientProfile,
    ProductClassification,
    assess_business_relevance,
    check_client_onboarding,
    decide_export_status,
)
from app.domain.chart_accounts import ChartAccount, extract_counterparty_candidates, parse_chart_accounts, validate_vat_accounts
from app.domain.counterparty_matching import CounterpartyMatch, match_counterparty
from app.domain.ai_classification import AiClassificationContext, ProductClassifier
from app.domain.journal_entries import JournalEntry, JournalLine, build_purchase_entry, build_sales_entry, money
from app.domain.pdf_invoices import ParsedInvoice, parse_invoice_folder

ProcessingMode = Literal["conservative", "ai_assisted_draft", "controlled_automation"]


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
    account_candidates: dict[str, tuple[dict[str, str], ...]] = field(default_factory=dict)


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
    selected_revenue_account: str = ""
    selected_purchase_vat_account: str = ""
    selected_sales_vat_account: str = ""
    selected_customer_account: str = ""
    suggested_counterparty_account: str = ""
    counterparty_creation_suggestion: dict[str, object] | None = None
    accounting_direction: str = "purchase"
    direction_confidence: int = 0
    direction_evidence: tuple[str, ...] = ()
    accountant_explanation_tr: str = ""
    account_candidates: dict[str, tuple[dict[str, str], ...]] | None = None


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


def _candidate_payload(account: ChartAccount, reason: str) -> dict[str, str]:
    return {
        "code": account.normalized_account_code,
        "name": account.account_name,
        "reason": reason,
    }


def _candidate_group(accounts: list[ChartAccount], prefixes: tuple[str, ...], reason: str) -> tuple[dict[str, str], ...]:
    return tuple(
        _candidate_payload(account, reason)
        for account in accounts
        if account.is_detail_account and account.normalized_account_code.startswith(prefixes)
    )


def _candidate_group_with_hint(accounts: list[ChartAccount], prefix: str, hints: tuple[str, ...], reason: str) -> tuple[dict[str, str], ...]:
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
    expense = _first_account(accounts, ("770", "760", "740", "730", " gider"))
    purchase_vat = _first_account(accounts, ("191",))
    revenue = _first_account(accounts, ("600",))
    zero_vat_revenue = _account_with_name_hint(accounts, "600", ("3065", "%0", "0 kdv", "istisna")) or revenue
    sales_vat = _first_account(accounts, ("391",))
    bank = _first_account(accounts, ("102",))

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


def _is_return_invoice(invoice: ParsedInvoice) -> bool:
    haystack = " ".join(
        (
            invoice.invoice_type,
            invoice.scenario,
            " ".join(invoice.risk_flags),
            " ".join(invoice.parse_notes),
        )
    ).upper()
    return "IADE" in haystack or "İADE" in haystack


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


def infer_accounting_direction(invoice: ParsedInvoice, client_profile: ClientProfile | None) -> tuple[str, int, tuple[str, ...]]:
    if _is_return_invoice(invoice):
        return "return_review", 100, ("return_invoice_signal",)
    identifiers = _client_identifiers(client_profile)
    if not identifiers:
        return "purchase", 40, ("client_identity_missing_purchase_fallback",)
    if _line_mentions_client_after_sayin(invoice, client_profile):
        return "purchase", 90, ("sayin_recipient_is_client",)
    if invoice.invoice_type.upper() in {"ALIS", "ALIŞ"}:
        return "purchase", 82, ("invoice_type_purchase",)
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


def _counterparty_creation_suggestion(direction: str, selection: AccountSelection) -> tuple[str, dict[str, object]]:
    if direction == "sales":
        suggested = selection.next_customer_account or selection.customer_account
        return suggested, {"type": "customer", "base_account": "120", "suggested_code": suggested, "always_suggest_new": True}
    suggested = selection.next_supplier_account or selection.supplier_account
    return suggested, {"type": "supplier", "base_account": "320", "suggested_code": suggested, "always_suggest_new": True}


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
) -> str:
    if direction == "return_review":
        return "Iade sinyali bulundu. Bu fazda otomatik fis uretilmedi; belge iade kontrol kuyrugunda tutulmali."
    if direction == "sales":
        vat_text = ", ".join(invoice.vat_rates) or "yok"
        vat_account_text = sales_vat_account or "KDV satiri yok"
        return (
            f"Belge satis/gelir olarak yorumlandi ({', '.join(direction_evidence)}). "
            f"KDV oranlari: {vat_text}. Gelir hesabi: {revenue_account}. "
            f"Hesaplanan KDV hesabi: {vat_account_text}. Cari onerisi: {suggested_counterparty}."
        )
    return (
        f"Belge alis/gider olarak yorumlandi ({', '.join(direction_evidence)}). "
        f"Gider/stok hesabi: {expense_account}. Indirilecek KDV hesabi: {purchase_vat_account}. "
        f"Cari onerisi: {suggested_counterparty}."
    )


def _gross_review_entry(invoice: ParsedInvoice, selection: AccountSelection, supplier_account: str) -> JournalEntry:
    total = money(invoice.payable_total)
    return JournalEntry(
        entry_type="review_purchase",
        entry_date=invoice.issue_date or "1900-01-01",
        description=f"Kontrol gerekli fatura {invoice.file_name}",
        lines=(
            JournalLine(selection.expense_account, "Kontrol bekleyen gider taslagi", debit=total, document_ref=invoice.file_name),
            JournalLine(supplier_account, "Kontrol bekleyen satici cari", credit=total, document_ref=invoice.file_name),
        ),
        risk_flags=invoice.risk_flags,
    )


def _entry_lines(entry: JournalEntry | None) -> tuple[dict[str, str], ...]:
    if entry is None:
        return ()
    return tuple(
        {
            "account_code": line.account_code,
            "description": line.description,
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


def _ai_context(
    *,
    selection: AccountSelection,
    client_profile: ClientProfile | None,
    counterparty_match: CounterpartyMatch | None,
) -> AiClassificationContext:
    account_candidates = tuple(
        dict.fromkeys(
            code
            for code in (
                selection.expense_account,
                selection.purchase_vat_account,
                selection.bank_account,
            )
            if code
        )
    )
    counterparty_candidates = tuple(
        dict.fromkeys(
            code
            for code in (
                counterparty_match.account_code if counterparty_match else "",
                selection.supplier_account,
            )
            if code
        )
    )
    return AiClassificationContext(
        client_activity=client_profile.activity_description if client_profile else "",
        activity_tags=client_profile.activity_tags if client_profile else (),
        account_candidates=account_candidates,
        counterparty_candidates=counterparty_candidates,
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


def simulate_invoice(
    invoice: ParsedInvoice,
    selection: AccountSelection,
    client_profile: ClientProfile | None = None,
    counterparty_match: CounterpartyMatch | None = None,
    product_classifier: ProductClassifier | None = None,
    processing_mode: ProcessingMode | str = "controlled_automation",
) -> SimulatedInvoiceResult:
    mode = _normalize_processing_mode(processing_mode)
    reasons = tuple(dict.fromkeys((*invoice.risk_flags, *invoice.parse_notes)))
    amount = _decimal_or_none(invoice.payable_total)
    entry: JournalEntry | None = None
    draft_quality = "none"
    supplier_account = counterparty_match.account_code if counterparty_match and counterparty_match.account_code else selection.supplier_account
    direction, direction_confidence, direction_evidence = infer_accounting_direction(invoice, client_profile)
    suggested_counterparty, counterparty_creation_suggestion = _counterparty_creation_suggestion(direction, selection)
    selected_revenue_account = ""
    selected_purchase_vat_account = ""
    selected_sales_vat_account = ""
    selected_customer_account = ""
    raw_line = _product_line_hint(invoice)
    relevance = (
        assess_business_relevance(raw_line, client_profile, supplier_hint=invoice.provider_hint)
        if client_profile
        else _not_assessed_relevance(raw_line)
    )
    purchase_account = selection.stock_account if relevance.account_treatment == "stock_or_cogs" else selection.expense_account

    if direction == "return_review":
        status = "review_required"
        draft_quality = "return_manual_review"
        reasons = tuple(dict.fromkeys((*reasons, "return_invoice_manual_review")))
    elif amount is None or amount <= 0:
        status = "review_required"
        draft_quality = "no_positive_amount"
    elif direction == "sales" and len(invoice.vat_rates) <= 1:
        vat_rate = _single_vat_rate(invoice)
        selected_revenue_account = _sales_revenue_account(selection, vat_rate)
        selected_sales_vat_account = selection.sales_vat_account if vat_rate > Decimal("0.00") else ""
        selected_customer_account = counterparty_match.account_code if counterparty_match and counterparty_match.account_code else selection.customer_account
        entry = build_sales_entry(
            entry_date=invoice.issue_date or "1900-01-01",
            total=money(invoice.payable_total),
            vat_rate=vat_rate,
            revenue_account=selected_revenue_account,
            vat_account=selection.sales_vat_account,
            customer_account=selected_customer_account,
            document_ref=invoice.file_name,
        )
        draft_quality = "full_basic_sales" if not reasons else "partial_review_required"
        status = "auto_ready" if not reasons else "review_required"
    elif direction == "sales":
        entry = _gross_review_entry(invoice, selection, selection.customer_account)
        selected_revenue_account = selection.revenue_account
        selected_sales_vat_account = selection.sales_vat_account
        selected_customer_account = selection.customer_account
        draft_quality = "gross_balanced_needs_vat_split"
        status = "review_required"
    elif len(invoice.vat_rates) <= 1:
        selected_purchase_vat_account = selection.purchase_vat_account
        entry = build_purchase_entry(
            entry_date=invoice.issue_date or "1900-01-01",
            total=money(invoice.payable_total),
            vat_rate=_single_vat_rate(invoice),
            expense_account=purchase_account,
            vat_account=selection.purchase_vat_account,
            supplier_account=supplier_account,
            document_ref=invoice.file_name,
        )
        draft_quality = "full_basic_purchase" if not reasons else "partial_review_required"
        status = "auto_ready" if not reasons else "review_required"
    else:
        selected_purchase_vat_account = selection.purchase_vat_account
        entry = _gross_review_entry(invoice, selection, supplier_account)
        draft_quality = "gross_balanced_needs_vat_split"
        status = "review_required"

    ai_used = False
    ai_provider = ""
    ai_skipped_reason = "client_profile_not_provided"
    ai_reason = ""
    ai_estimated_chars = 0
    ai_suggested_account_code = ""
    ai_suggested_counterparty_code = ""
    ai_risk_flags: tuple[str, ...] = ()
    ai_account_reason = ""
    if client_profile and product_classifier:
        classification_result = product_classifier.classify(
            raw_line,
            supplier_hint=invoice.provider_hint,
            context=_ai_context(
                selection=selection,
                client_profile=client_profile,
                counterparty_match=counterparty_match,
            ),
        )
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
    elif client_profile:
        ai_skipped_reason = "classifier_not_configured"
    counterparty_reasons: tuple[str, ...] = ()
    if counterparty_match and counterparty_match.requires_review:
        counterparty_reasons = (f"counterparty_{counterparty_match.match_reason}",)
    onboarding_reasons: tuple[str, ...] = ()
    if client_profile:
        onboarding = check_client_onboarding(client_profile)
        if not onboarding.is_ready:
            onboarding_reasons = tuple(f"onboarding_missing_{field}" for field in onboarding.missing_fields)
    else:
        onboarding_reasons = ("onboarding_missing_client_profile",)
    all_reasons = tuple(dict.fromkeys((*reasons, *counterparty_reasons, *onboarding_reasons)))

    export_status = decide_export_status(
        is_balanced=entry.is_balanced if entry else False,
        risk_flags=all_reasons,
        relevance=relevance,
    )
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
    accountant_explanation = _accountant_explanation(
        direction=direction,
        direction_evidence=direction_evidence,
        invoice=invoice,
        revenue_account=selected_revenue_account,
        expense_account="" if direction == "sales" else purchase_account,
        purchase_vat_account=selected_purchase_vat_account,
        sales_vat_account=selected_sales_vat_account,
        suggested_counterparty=suggested_counterparty,
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
        selected_vat_account=selected_sales_vat_account if direction == "sales" else selection.purchase_vat_account,
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
        learning_rule_applied=False,
        learning_rule_scope="",
        learning_rule_reason="",
        learning_rule_source_summary="",
        accounting_intent="",
        accounting_intent_confidence=0,
        rule_prompt={},
        export_status=export_status,
        draft_lines=_entry_lines(entry),
        selected_revenue_account=selected_revenue_account,
        selected_purchase_vat_account=selected_purchase_vat_account,
        selected_sales_vat_account=selected_sales_vat_account,
        selected_customer_account=selected_customer_account,
        suggested_counterparty_account=suggested_counterparty,
        counterparty_creation_suggestion=counterparty_creation_suggestion,
        accounting_direction=direction,
        direction_confidence=direction_confidence,
        direction_evidence=direction_evidence,
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
        invoice.file_name: match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint)
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
        "is_balanced",
        "selected_expense_account",
        "selected_vat_account",
        "selected_supplier_account",
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
                    "isBalanced": result.is_balanced,
                    "riskFlags": list(result.risk_flags),
                    "parseNotes": list(result.parse_notes),
                    "reviewReasonCodes": list(result.review_reason_codes),
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
                    "aiSuggestedAccountCode": result.ai_suggested_account_code,
                    "aiSuggestedCounterpartyCode": result.ai_suggested_counterparty_code,
                    "aiRiskFlags": list(result.ai_risk_flags),
                    "aiAccountReason": result.ai_account_reason,
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


def write_review_ui_json(runs: list[SimulatedChartRun], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build_review_ui_payload(runs), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
