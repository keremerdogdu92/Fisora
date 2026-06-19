from __future__ import annotations

from dataclasses import asdict
import os

from app.api.phase0_schemas import (
    AccountSelectionPayload,
    AiBenchmarkCasePayload,
    AiClassificationPolicyPayload,
    ChartAccountPayload,
    ClientProfilePayload,
    InvoicePayload,
    LearnedPostingRulePayload,
    StatementAiSuggestionPolicyPayload,
    StatementLineSuggestionPayload,
)
from app.domain.ai_benchmark import AiBenchmarkCase
from app.domain.ai_classification import AiClassificationPolicy, StaticFirstClassifier
from app.domain.ai_usage import estimate_ai_cost_usd
from app.domain.business_relevance import ClientProfile
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.learning_rules import LearnedPostingRule
from app.domain.matching_simulation import AccountSelection
from app.domain.openai_provider import (
    DEFAULT_COMPARISON_MODEL,
    DEFAULT_GROQ_COMPARISON_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENAI_MODEL,
    GroqAccountingProvider,
    OpenAiAccountingProvider,
)
from app.domain.pdf_invoices import ParsedInvoice
from app.domain.statement_ai_suggestions import StatementAiSuggestionPolicy
from app.domain.statement_lines import StatementLine


def client_profile_from_payload(payload: ClientProfilePayload) -> ClientProfile:
    return ClientProfile(
        client_id=payload.client_id,
        title=payload.title,
        tax_id=payload.tax_id,
        tckn=payload.tckn,
        vkn=payload.vkn,
        identity_type=payload.identity_type,
        tax_identifier=payload.tax_identifier,
        legal_name=payload.legal_name,
        trade_name=payload.trade_name,
        display_title=payload.display_title,
        tax_office=payload.tax_office,
        activity_description=payload.activity_description,
        nace_code=payload.nace_code,
        activity_tags=tuple(payload.activity_tags),
        workplace_addresses=tuple(payload.workplace_addresses),
        has_chart_accounts=payload.has_chart_accounts,
    )


def chart_account_from_payload(payload: ChartAccountPayload) -> ChartAccount:
    normalized = payload.normalized_account_code or normalize_account_code(payload.raw_account_code)
    return ChartAccount(
        raw_account_code=payload.raw_account_code,
        normalized_account_code=normalized,
        account_name=payload.account_name,
        is_detail_account=payload.is_detail_account,
        tax_id=payload.tax_id,
        tax_office=payload.tax_office,
        iban=payload.iban,
    )


def chart_account_payloads(accounts: list[ChartAccountPayload]) -> list[dict[str, object]]:
    return [asdict(chart_account_from_payload(account)) for account in accounts]


def account_selection_from_payload(payload: AccountSelectionPayload) -> AccountSelection:
    return AccountSelection(
        chart_file_name=payload.chart_file_name,
        expense_account=payload.expense_account,
        purchase_vat_account=payload.purchase_vat_account,
        supplier_account=payload.supplier_account,
        bank_account=payload.bank_account,
        selection_notes=tuple(payload.selection_notes),
        revenue_account=payload.revenue_account,
        zero_vat_revenue_account=payload.zero_vat_revenue_account,
        sales_vat_account=payload.sales_vat_account,
        customer_account=payload.customer_account,
        next_customer_account=payload.next_customer_account,
        next_supplier_account=payload.next_supplier_account,
        stock_account=payload.stock_account,
        account_candidates={
            key: tuple(value) if isinstance(value, list) else tuple()
            for key, value in payload.account_candidates.items()
        },
    )


def parsed_invoice_from_payload(payload: InvoicePayload) -> ParsedInvoice:
    return ParsedInvoice(
        file_name=payload.file_name,
        provider_hint=payload.provider_hint,
        page_count=payload.page_count,
        text_extractable=payload.text_extractable,
        extracted_char_count=payload.extracted_char_count,
        scenario=payload.scenario,
        invoice_type=payload.invoice_type,
        invoice_no=payload.invoice_no,
        ettn=payload.ettn,
        issue_date=payload.issue_date,
        tax_ids=tuple(payload.tax_ids),
        vat_rates=tuple(payload.vat_rates),
        goods_services_total=payload.goods_services_total,
        vat_total=payload.vat_total,
        special_tax_total=payload.special_tax_total,
        tax_inclusive_total=payload.tax_inclusive_total,
        payable_total=payload.payable_total,
        risk_flags=tuple(payload.risk_flags),
        suggested_route=payload.suggested_route,
        parse_notes=tuple(payload.parse_notes),
        line_items=tuple(payload.line_items),
        issuer_title=payload.issuer_title,
        issuer_tax_id=payload.issuer_tax_id,
        recipient_title=payload.recipient_title,
        recipient_tax_id=payload.recipient_tax_id,
        invoice_type_code=payload.invoice_type_code,
        is_return_invoice=payload.is_return_invoice,
    )


def ai_policy_from_payload(payload: AiClassificationPolicyPayload | None) -> AiClassificationPolicy:
    if payload is None:
        return AiClassificationPolicy()
    return AiClassificationPolicy(
        enabled=payload.enabled,
        static_confidence_threshold=payload.static_confidence_threshold,
        max_input_chars=payload.max_input_chars,
        max_provider_calls=payload.max_provider_calls,
    )


def ai_provider_from_env(*, model: str = "") -> OpenAiAccountingProvider | GroqAccountingProvider | None:
    provider_name = os.environ.get("FISORA_AI_PROVIDER", "disabled").strip().lower()
    if provider_name == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            return None
        return GroqAccountingProvider(
            api_key=api_key,
            model=model or os.environ.get("FISORA_AI_MODEL", DEFAULT_GROQ_MODEL),
        )
    if provider_name == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        return OpenAiAccountingProvider(
            api_key=api_key,
            model=model or os.environ.get("FISORA_AI_MODEL", DEFAULT_OPENAI_MODEL),
        )
    return None


def static_first_classifier_from_payload(payload: AiClassificationPolicyPayload | None) -> StaticFirstClassifier:
    policy = ai_policy_from_payload(payload)
    return StaticFirstClassifier(
        provider=ai_provider_from_env() if policy.enabled else None,
        policy=policy,
    )


def statement_ai_policy_from_payload(
    payload: StatementAiSuggestionPolicyPayload | None,
) -> StatementAiSuggestionPolicy:
    if payload is None:
        return StatementAiSuggestionPolicy()
    return StatementAiSuggestionPolicy(
        enabled=payload.enabled,
        confidence_threshold=payload.confidence_threshold,
        max_input_chars=payload.max_input_chars,
        max_provider_calls=payload.max_provider_calls,
    )


def statement_line_from_payload(payload: StatementLineSuggestionPayload) -> StatementLine:
    return StatementLine(
        line_no=payload.line_no,
        transaction_date=payload.transaction_date,
        description=payload.description,
        amount=payload.amount,
        direction=payload.direction,
        balance_after=payload.balance_after,
        counterparty_name=payload.counterparty_name,
        tax_id=payload.tax_id,
        iban=payload.iban,
        suggested_account_code=payload.suggested_account_code,
        transaction_type=payload.transaction_type,
        confidence=payload.confidence,
        risk_flags=tuple(payload.risk_flags),
        review_reason=payload.review_reason,
    )


def benchmark_cases_from_payloads(cases: list[AiBenchmarkCasePayload]) -> tuple[AiBenchmarkCase, ...]:
    return tuple(
        AiBenchmarkCase(
            case_id=case.case_id,
            raw_line=case.raw_line,
            supplier_hint=case.supplier_hint,
            expected_category=case.expected_category,
        )
        for case in cases
    )


def benchmark_response(summary, *, model: str = "") -> dict[str, object]:
    estimated_cost = estimate_ai_cost_usd(provider=summary.provider, input_chars=summary.estimated_input_chars)
    return {
        "case_count": summary.case_count,
        "ai_used_count": summary.ai_used_count,
        "matched_count": summary.matched_count,
        "evaluated_count": summary.evaluated_count,
        "accuracy_percent": summary.accuracy_percent,
        "estimated_input_chars": summary.estimated_input_chars,
        "estimated_cost_usd": f"{estimated_cost:.6f}",
        "provider": summary.provider,
        "model": model,
        "results": [asdict(result) for result in summary.results],
    }


def learned_rule_from_payload(payload: LearnedPostingRulePayload) -> LearnedPostingRule:
    return LearnedPostingRule(
        scope=payload.scope,
        action=payload.action,
        category=payload.category,
        corrected_account_code=payload.corrected_account_code,
        corrected_counterparty_code=payload.corrected_counterparty_code,
        reason=payload.reason,
        automation_candidate=payload.automation_candidate,
    )


def comparison_defaults(provider_name: str) -> tuple[str, str, type[OpenAiAccountingProvider] | type[GroqAccountingProvider]]:
    if provider_name == "groq":
        return (
            os.environ.get("FISORA_AI_MODEL", "").strip() or DEFAULT_GROQ_MODEL,
            os.environ.get("FISORA_AI_COMPARISON_MODEL", "").strip() or DEFAULT_GROQ_COMPARISON_MODEL,
            GroqAccountingProvider,
        )
    return (
        os.environ.get("FISORA_AI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL,
        os.environ.get("FISORA_AI_COMPARISON_MODEL", "").strip() or DEFAULT_COMPARISON_MODEL,
        OpenAiAccountingProvider,
    )
