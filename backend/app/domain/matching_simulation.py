from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
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
from app.domain.journal_entries import JournalEntry, JournalLine, build_purchase_entry, money
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


def select_accounts(chart_file_name: str, accounts: list[ChartAccount]) -> AccountSelection:
    notes: list[str] = []
    suppliers = [account for account in extract_counterparty_candidates(accounts) if account.counterparty_type == "supplier"]
    supplier = suppliers[0] if suppliers else _first_account(accounts, ("320",))
    expense = _first_account(accounts, ("770", "760", "740", "730", " gider"))
    purchase_vat = _first_account(accounts, ("191",))
    bank = _first_account(accounts, ("102",))

    if supplier is None:
        notes.append("fallback_supplier_320_missing")
    if expense is None:
        notes.append("fallback_expense_770_missing")
    if purchase_vat is None:
        notes.append("fallback_purchase_vat_191_missing")
    if bank is None:
        notes.append("fallback_bank_102_missing")

    return AccountSelection(
        chart_file_name=chart_file_name,
        expense_account=expense.normalized_account_code if expense else "770.01",
        purchase_vat_account=purchase_vat.normalized_account_code if purchase_vat else "191.01",
        supplier_account=supplier.normalized_account_code if supplier else "320.01.001",
        bank_account=bank.normalized_account_code if bank else "102.01",
        selection_notes=tuple(notes),
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

    if amount is None or amount <= 0:
        status = "review_required"
        draft_quality = "no_positive_amount"
    elif len(invoice.vat_rates) <= 1:
        entry = build_purchase_entry(
            entry_date=invoice.issue_date or "1900-01-01",
            total=money(invoice.payable_total),
            vat_rate=_single_vat_rate(invoice),
            expense_account=selection.expense_account,
            vat_account=selection.purchase_vat_account,
            supplier_account=supplier_account,
            document_ref=invoice.file_name,
        )
        draft_quality = "full_basic_purchase" if not reasons else "partial_review_required"
        status = "auto_ready" if not reasons else "review_required"
    else:
        entry = _gross_review_entry(invoice, selection, supplier_account)
        draft_quality = "gross_balanced_needs_vat_split"
        status = "review_required"

    raw_line = _product_line_hint(invoice)
    ai_used = False
    ai_provider = ""
    ai_skipped_reason = "client_profile_not_provided"
    ai_reason = ""
    ai_estimated_chars = 0
    ai_suggested_account_code = ""
    ai_suggested_counterparty_code = ""
    ai_risk_flags: tuple[str, ...] = ()
    ai_account_reason = ""
    relevance = (
        assess_business_relevance(raw_line, client_profile, supplier_hint=invoice.provider_hint)
        if client_profile
        else _not_assessed_relevance(raw_line)
    )
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
        selected_expense_account=selection.expense_account,
        selected_vat_account=selection.purchase_vat_account,
        selected_supplier_account=supplier_account,
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
