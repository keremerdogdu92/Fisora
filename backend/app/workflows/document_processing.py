from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from os import environ
from pathlib import Path
import re
import time
from typing import Any

from app.domain.ai_classification import AiClassificationPolicy, ProductClassifier, StaticFirstClassifier
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event
from app.domain.business_relevance import ClientProfile, ProductClassification, assess_business_relevance
from app.domain.canonical_invoices import CanonicalExtractionPolicy
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty
from app.domain.learning_rules import apply_learning_rules, rule_from_event_payload
from app.domain.matching_simulation import AccountSelection, select_accounts, simulate_invoice
from app.domain.nace_research import resolve_nace_research_profile
from app.domain.openai_provider import (
    CEREBRAS_CHAT_COMPLETIONS_URL,
    DEFAULT_CEREBRAS_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_CHAT_COMPLETIONS_URL,
    ChatCompletionsAccountingProvider,
    FallbackAccountingProvider,
    GroqAccountingProvider,
    OpenAiAccountingProvider,
)
from app.domain.pdf_invoices import ParsedInvoice, parse_pdf_invoice
from app.domain.product_research_cache import normalize_product_research_key
from app.domain.research_harness import (
    ResearchHarness,
    apply_research_to_result,
    build_research_runtime_from_env,
    sanitize_research_query,
)
from app.domain.statement_ai_suggestions import (
    StatementAiSuggestionPolicy,
    StatementSuggestionProvider,
    statement_ai_batch_payload,
    suggest_statement_lines,
)
from app.domain.statement_journal_entries import build_statement_entry_records, statement_entry_payload
from app.domain.statement_lines import enrich_statement_lines_with_counterparties, parse_statement_file
from app.domain.vat_split_learning import build_vat_split_review_record, vat_split_review_payload
from app.domain.xml_invoices import parse_xml_invoice


PARSER_BY_DOCUMENT_TYPE = {
    "invoice": "text_pdf_invoice",
    "einvoice_xml": "einvoice_xml",
    "bank_statement": "bank_statement",
    "pos_statement": "pos_statement",
    "special_document": "manual_review",
}


def parser_kind_for_document_type(document_type: str) -> str:
    return PARSER_BY_DOCUMENT_TYPE.get(document_type, "manual_review")


def _chart_account(payload: dict[str, Any]) -> ChartAccount:
    raw_code = str(payload.get("raw_account_code") or payload.get("normalized_account_code") or "")
    normalized = str(payload.get("normalized_account_code") or normalize_account_code(raw_code))
    return ChartAccount(
        raw_account_code=raw_code,
        normalized_account_code=normalized,
        account_name=str(payload.get("account_name") or ""),
        is_detail_account=bool(payload.get("is_detail_account", True)),
        tax_id=str(payload.get("tax_id") or "") or None,
        tax_office=str(payload.get("tax_office") or "") or None,
        iban=str(payload.get("iban") or "") or None,
    )


def _first_detail_account(accounts: list[ChartAccount], prefixes: tuple[str, ...], fallback: str) -> str:
    for account in accounts:
        if account.is_detail_account and account.normalized_account_code.startswith(prefixes):
            return account.normalized_account_code
    return fallback


def _first_detail_account_with_hint(accounts: list[ChartAccount], prefix: str, hints: tuple[str, ...], fallback: str) -> str:
    for account in accounts:
        name = account.account_name.lower()
        if account.is_detail_account and account.normalized_account_code.startswith(prefix) and any(hint in name for hint in hints):
            return account.normalized_account_code
    return fallback


def _next_counterparty_account(accounts: list[ChartAccount], prefix: str, letter: str = "A") -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}\.?{re.escape(letter)}(\d+)$", re.IGNORECASE)
    max_index = 0
    for account in accounts:
        compact = account.normalized_account_code.replace(".", "")
        match = pattern.match(compact) or pattern.match(account.normalized_account_code)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return f"{prefix}.{letter}{max_index + 1:02d}" if max_index else f"{prefix}.{letter}01"


def _account_selection(workspace: dict[str, Any]) -> AccountSelection:
    chart_accounts = workspace.get("chart_accounts") or {}
    accounts = [_chart_account(account) for account in chart_accounts.get("accounts", [])]
    return select_accounts("workspace-store", accounts)


def _client_profile(workspace: dict[str, Any]) -> ClientProfile | None:
    client = workspace.get("client") or {}
    profile = client.get("profile") or {}
    client_id = str(profile.get("client_id") or client.get("client_id") or "").strip()
    if not client_id:
        return None
    chart_accounts = workspace.get("chart_accounts") or {}
    return ClientProfile(
        client_id=client_id,
        title=str(profile.get("title") or ""),
        tax_id=str(profile.get("tax_id") or ""),
        tckn=str(profile.get("tckn") or ""),
        vkn=str(profile.get("vkn") or ""),
        identity_type=str(profile.get("identity_type") or ""),
        tax_identifier=str(profile.get("tax_identifier") or profile.get("tax_id") or ""),
        legal_name=str(profile.get("legal_name") or ""),
        trade_name=str(profile.get("trade_name") or ""),
        display_title=str(profile.get("display_title") or profile.get("title") or ""),
        tax_office=str(profile.get("tax_office") or ""),
        activity_description=str(profile.get("activity_description") or ""),
        nace_code=str(profile.get("nace_code") or ""),
        activity_tags=tuple(profile.get("activity_tags") or ()),
        nace_research_profile=dict(profile.get("nace_research_profile") or {}),
        workplace_addresses=tuple(profile.get("workplace_addresses") or ()),
        has_chart_accounts=bool(profile.get("has_chart_accounts") or chart_accounts.get("account_count")),
    )


def _workspace_with_nace_research(workspace: dict[str, Any], store: Any) -> dict[str, Any]:
    client = workspace.get("client") or {}
    profile = client.get("profile") or {}
    nace_code = str(profile.get("nace_code") or "").strip()
    if not nace_code or profile.get("activity_tags"):
        return workspace
    try:
        research_profile = resolve_nace_research_profile(store=store, nace_code=nace_code)
    except Exception:
        return workspace
    activity_tags = [str(tag).strip() for tag in research_profile.get("activity_tags") or [] if str(tag).strip()]
    if not activity_tags:
        return workspace
    enriched_profile = {
        **profile,
        "activity_tags": activity_tags,
        "nace_research_profile": research_profile,
    }
    return {
        **workspace,
        "client": {
            **client,
            "profile": enriched_profile,
        },
    }


def _chart_accounts(workspace: dict[str, Any]) -> list[ChartAccount]:
    chart_accounts = workspace.get("chart_accounts") or {}
    return [_chart_account(account) for account in chart_accounts.get("accounts", [])]


def _counterparty_match_for_invoice(
    accounts: list[ChartAccount],
    invoice: ParsedInvoice,
    profile: ClientProfile | None,
):
    if not accounts:
        return None
    client_ids = {
        re.sub(r"\D+", "", value)
        for value in (
            profile.vkn if profile else "",
            profile.tckn if profile else "",
            profile.tax_id if profile else "",
            profile.tax_identifier if profile else "",
            profile.effective_tax_identifier if profile else "",
        )
        if value
    }
    issuer_tax_id = re.sub(r"\D+", "", getattr(invoice, "issuer_tax_id", ""))
    recipient_tax_id = re.sub(r"\D+", "", getattr(invoice, "recipient_tax_id", ""))
    if issuer_tax_id and issuer_tax_id in client_ids:
        return match_counterparty(
            accounts,
            tax_ids=(recipient_tax_id,),
            name_hint=getattr(invoice, "recipient_title", ""),
            account_prefixes=("120",),
        )
    if recipient_tax_id and recipient_tax_id in client_ids:
        return match_counterparty(
            accounts,
            tax_ids=(issuer_tax_id,),
            name_hint=getattr(invoice, "issuer_title", "") or invoice.provider_hint,
            account_prefixes=("320",),
        )
    return match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint)


def _serializable_simulation(
    invoice: ParsedInvoice,
    workspace: dict[str, Any],
    *,
    product_classifier: ProductClassifier | None = None,
    intended_direction: str | None = None,
    classification_override: ProductClassification | None = None,
) -> dict[str, Any]:
    accounts = _chart_accounts(workspace)
    profile = _client_profile(workspace)
    counterparty = _counterparty_match_for_invoice(accounts, invoice, profile)
    result = simulate_invoice(
        invoice,
        _account_selection(workspace),
        profile,
        counterparty,
        product_classifier or StaticFirstClassifier(),
        processing_mode="ai_assisted_draft" if product_classifier else "controlled_automation",
        intended_direction=intended_direction,
        classification_override=classification_override,
    )
    result = apply_learning_rules(
        result,
        [rule_from_event_payload(event) for event in workspace.get("learning_events") or []],
    )
    data = asdict(result)
    for key in (
        "vat_rates",
        "risk_flags",
        "ai_risk_flags",
        "parse_notes",
        "review_reason_codes",
        "deterministic_checks",
        "business_relevance_evidence",
        "ai_selected_account_families",
        "ai_stage_evidence",
        "ai_account_stage_evidence",
        "ai_counterparty_stage_evidence",
        "ai_trace",
        "draft_lines",
    ):
        data[key] = list(data[key])
    vat_review = build_vat_split_review_record(invoice, document_ref=invoice.file_name)
    if vat_review.status != "unavailable":
        data["vat_split_status"] = vat_review.status
        data["vat_split_lines"] = [asdict(line) for line in vat_review.lines]
        data["vat_split_evidence"] = list(vat_review.evidence)
        data["vat_split_review"] = vat_split_review_payload(vat_review)
        if vat_review.requires_accountant_review:
            data["review_reason_codes"] = list(
                dict.fromkeys((*data.get("review_reason_codes", []), *vat_review.review_reason_codes))
            )
            data["risk_flags"] = list(dict.fromkeys((*data.get("risk_flags", []), "vat_split_review_required")))
            data["simulated_status"] = "review_required"
            data["export_status"] = "review_required"
            data["export_gate_reason"] = "KDV oran/matrah ayrimi musavir kontrolu gerektiriyor."
    return _with_review_summary(data)


def _accounting_provider_from_env(provider_name: str, source: dict[str, str] | Any) -> OpenAiAccountingProvider:
    if provider_name == "groq":
        return GroqAccountingProvider(
            api_key=source.get("GROQ_API_KEY", ""),
            model=source.get("FISORA_GROQ_MODEL", source.get("FISORA_AI_MODEL", DEFAULT_GROQ_MODEL)),
        )
    if provider_name == "openrouter":
        return ChatCompletionsAccountingProvider(
            api_key=source.get("OPENROUTER_API_KEY", ""),
            model=source.get("FISORA_OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            chat_completions_url=source.get("FISORA_OPENROUTER_CHAT_COMPLETIONS_URL", OPENROUTER_CHAT_COMPLETIONS_URL),
            provider_name="openrouter",
            key_name="OPENROUTER_API_KEY",
            extra_headers={
                "HTTP-Referer": source.get("FISORA_OPENROUTER_SITE_URL", ""),
                "X-Title": source.get("FISORA_OPENROUTER_APP_TITLE", ""),
            },
        )
    if provider_name == "cerebras":
        return ChatCompletionsAccountingProvider(
            api_key=source.get("CEREBRAS_API_KEY", ""),
            model=source.get("FISORA_CEREBRAS_MODEL", DEFAULT_CEREBRAS_MODEL),
            chat_completions_url=source.get("FISORA_CEREBRAS_CHAT_COMPLETIONS_URL", CEREBRAS_CHAT_COMPLETIONS_URL),
            provider_name="cerebras",
            key_name="CEREBRAS_API_KEY",
        )
    return OpenAiAccountingProvider(
        api_key=source.get("OPENAI_API_KEY", ""),
        model=source.get("FISORA_OPENAI_MODEL", source.get("FISORA_AI_MODEL", DEFAULT_OPENAI_MODEL)),
    )


def _provider_chain_from_env(source: dict[str, str] | Any) -> OpenAiAccountingProvider | FallbackAccountingProvider | None:
    chain = [
        name.strip().lower()
        for name in source.get("FISORA_AI_PROVIDER_CHAIN", "").split(",")
        if name.strip()
    ]
    provider_name = source.get("FISORA_AI_PROVIDER", "disabled").strip().lower()
    supported_providers = {"openai", "groq", "openrouter", "cerebras"}
    if not chain and provider_name in supported_providers:
        chain = [provider_name]
    chain = [name for name in chain if name in supported_providers]
    if not chain:
        return None
    providers = [_accounting_provider_from_env(name, source) for name in chain]
    return providers[0] if len(providers) == 1 else FallbackAccountingProvider(providers)


def build_ai_runtime_from_env(env: dict[str, str] | None = None) -> dict[str, object]:
    source = env or environ
    provider = _provider_chain_from_env(source)
    if provider is None:
        return {
            "product_classifier": None,
            "canonical_extraction_provider": None,
            "canonical_extraction_policy": CanonicalExtractionPolicy(),
            "statement_ai_provider": None,
            "statement_ai_policy": StatementAiSuggestionPolicy(),
        }
    product_policy = AiClassificationPolicy(
        enabled=True,
        static_confidence_threshold=int(source.get("FISORA_AI_STATIC_CONFIDENCE_THRESHOLD", "101")),
        max_input_chars=int(source.get("FISORA_AI_MAX_INPUT_CHARS", "420")),
        max_provider_calls=int(source.get("FISORA_AI_MAX_PROVIDER_CALLS", "3")),
        single_stage_account_limit=int(source.get("FISORA_AI_SINGLE_STAGE_ACCOUNT_LIMIT", "40")),
        final_stage_account_limit=int(source.get("FISORA_AI_FINAL_STAGE_ACCOUNT_LIMIT", "120")),
        counterparty_limit=int(source.get("FISORA_AI_COUNTERPARTY_LIMIT", "80")),
    )
    statement_policy = StatementAiSuggestionPolicy(
        enabled=True,
        confidence_threshold=int(source.get("FISORA_AI_STATEMENT_CONFIDENCE_THRESHOLD", "101")),
        max_input_chars=int(source.get("FISORA_AI_STATEMENT_MAX_INPUT_CHARS", "420")),
        max_provider_calls=int(source.get("FISORA_AI_STATEMENT_MAX_PROVIDER_CALLS", "3")),
    )
    canonical_policy = CanonicalExtractionPolicy(
        enabled=source.get("FISORA_AI_CANONICAL_EXTRACTION_ENABLED", "true").strip().lower()
        not in {"0", "false", "no", "disabled"},
        max_input_chars=int(source.get("FISORA_AI_CANONICAL_MAX_INPUT_CHARS", "12000")),
        max_provider_calls=int(source.get("FISORA_AI_CANONICAL_MAX_PROVIDER_CALLS", "1")),
    )
    return {
        "product_classifier": StaticFirstClassifier(provider=provider, policy=product_policy),
        "canonical_extraction_provider": provider,
        "canonical_extraction_policy": canonical_policy,
        "statement_ai_provider": provider,
        "statement_ai_policy": statement_policy,
    }


def _stored_path(document: dict[str, Any]) -> Path | None:
    storage_path = str(document.get("storage_path") or "").strip()
    if not storage_path:
        return None
    path = Path(storage_path)
    return path if path.exists() and path.is_file() else None


def _invoice_has_expected_shape(invoice: ParsedInvoice) -> bool:
    return bool(invoice.invoice_no or invoice.ettn or invoice.issue_date or invoice.payable_total or invoice.tax_ids)


def _draft_status(result: dict[str, Any]) -> str:
    if result.get("document_validation_status") == "unexpected_document":
        return "wrong_document_type"
    if result.get("ai_resolution_status") == "ai_retry_required":
        return "ai_retry_required"
    if result.get("draft_lines"):
        return "draft_ready"
    return "manual_draft_required"


def _accountant_summary(result: dict[str, Any]) -> str:
    if result.get("document_validation_status") == "unexpected_document":
        return "Bu dosya beklenen fatura/ekstre yapisinda gorunmuyor. Dogru belge yeniden istenmeli."
    if result.get("ai_resolution_status") == "ai_retry_required":
        return "AI ajani mesgul veya karar tamamlanamadi; belge tekrar denenecek."
    if result.get("draft_lines"):
        if result.get("is_balanced"):
            return "Fis taslagi hazir. Musavir kontrolunden sonra cikti listesine alinabilir."
        return "Fis taslagi var ancak borc/alacak dengesi musavir kontrolu istiyor."
    if "ai_provider_error" in set(result.get("ai_risk_flags") or []):
        return "AI onerisi alinamadi; belge manuel fis girisine hazirlandi."
    return "Bu belge icin otomatik fis taslagi uretilemedi. Musavir manuel fis satirlarini girmeli."


def _technical_details(result: dict[str, Any]) -> dict[str, object]:
    return {
        "parse_notes": list(result.get("parse_notes") or []),
        "review_reason_codes": list(result.get("review_reason_codes") or []),
        "risk_flags": list(result.get("risk_flags") or []),
        "vat_split_review": result.get("vat_split_review") if isinstance(result.get("vat_split_review"), dict) else {},
        "ai_provider": str(result.get("ai_classification_provider") or ""),
        "ai_skipped_reason": str(result.get("ai_classification_skipped_reason") or ""),
        "ai_reason": str(result.get("ai_classification_reason") or ""),
        "ai_resolution_status": str(result.get("ai_resolution_status") or ""),
        "ai_retry_reason": str(result.get("ai_retry_reason") or ""),
        "ai_stage_evidence": list(result.get("ai_stage_evidence") or []),
        "ai_account_stage_evidence": list(result.get("ai_account_stage_evidence") or []),
        "ai_counterparty_stage_evidence": list(result.get("ai_counterparty_stage_evidence") or []),
        "ai_trace": list(result.get("ai_trace") or []),
        "direction_uncertainty": bool(result.get("direction_uncertainty")),
        "static_fallback_account": str(result.get("static_fallback_account") or ""),
        "static_fallback_suppressed": bool(result.get("static_fallback_suppressed")),
    }


def _ai_explanation_tr(result: dict[str, Any]) -> str:
    provider = str(result.get("ai_classification_provider") or "statik kurallar")
    skipped = str(result.get("ai_classification_skipped_reason") or "")
    reason = str(result.get("ai_classification_reason") or result.get("business_relevance_reason") or "")
    category = str(result.get("product_category") or "-")
    confidence = int(result.get("product_confidence") or result.get("business_relevance_confidence") or 0)
    account = str(result.get("ai_suggested_account_code") or result.get("selected_expense_account") or "-")
    counterparty = str(result.get("ai_suggested_counterparty_code") or result.get("selected_supplier_account") or "-")
    risks = ", ".join(str(flag) for flag in result.get("ai_risk_flags") or result.get("review_reason_codes") or []) or "risk yok"
    if result.get("ai_resolution_status") == "ai_retry_required":
        retry_reason = str(result.get("ai_retry_reason") or skipped or "ai_not_resolved")
        if skipped == "ai_provider_error":
            return f"AI karari alinamadi. Provider {provider} hata verdi; belge tekrar denenecek. Sebep: {retry_reason}. Riskler: {risks}."
        return f"AI karari tamamlanamadi; belge tekrar denenecek. Sebep: {retry_reason}. Hesap onerisi nihai taslaga yazilmadi. Riskler: {risks}."
    if skipped == "ai_provider_error":
        return f"AI karari alinamadi. Provider {provider} hata verdi; belge tekrar denenecek. Riskler: {risks}."
    return (
        f"AI karari: {provider} belge kalemini {category} olarak degerlendirdi. "
        f"Guven: %{confidence}. Gerekce: {reason or 'Gerekce uretilmedi.'} "
        f"Hesap onerisi: {account}. Cari onerisi: {counterparty}. Riskler: {risks}."
    )


def _with_review_summary(result: dict[str, Any], *, document_validation_status: str = "expected_document") -> dict[str, Any]:
    updated = dict(result)
    updated.setdefault("document_validation_status", document_validation_status)
    if updated.get("ai_resolution_status") == "ai_retry_required":
        updated["draft_status"] = "ai_retry_required"
    updated.setdefault("draft_status", _draft_status(updated))
    draft_lines = list(updated.get("draft_lines") or [])
    statement_entries = list(updated.get("statement_entries") or [])
    review_blockers = list(updated.get("review_blockers") or updated.get("review_reason_codes") or updated.get("risk_flags") or [])
    updated.setdefault("review_blockers", review_blockers)
    updated.setdefault("draft_confidence", 75 if draft_lines or statement_entries else 20)
    updated.setdefault(
        "automation_eligibility",
        "eligible_after_policy" if updated.get("export_status") == "export_ready" and not review_blockers else "not_eligible",
    )
    updated.setdefault(
        "accountant_action_hint",
        "AI kararini tamamlayinca belge otomatik yeniden denenecek."
        if updated.get("ai_resolution_status") == "ai_retry_required"
        else "Taslak hazir; mustavir kontrolu bekliyor." if draft_lines or statement_entries else "Manuel kontrol gerekiyor.",
    )
    updated.setdefault(
        "primary_suggestion",
        {
            "direction": updated.get("accounting_direction") or updated.get("invoice_type") or "",
            "counterparty_account": updated.get("selected_supplier_account")
            or updated.get("selected_customer_account")
            or updated.get("suggested_counterparty_account")
            or "",
            "account": updated.get("selected_expense_account") or updated.get("selected_revenue_account") or "",
            "vat_account": updated.get("selected_vat_account")
            or updated.get("selected_purchase_vat_account")
            or updated.get("selected_sales_vat_account")
            or "",
            "draft_lines": draft_lines,
            "statement_entries": statement_entries,
            "reason": updated.get("accountant_summary") or updated.get("business_relevance_reason") or "",
            "export_gate_reason": updated.get("export_gate_reason") or "",
        },
    )
    if updated.get("ai_resolution_status") == "ai_retry_required":
        updated["accountant_summary"] = _accountant_summary(updated)
        updated["accountant_explanation_tr"] = _ai_explanation_tr(updated)
        updated["ai_explanation_tr"] = _ai_explanation_tr(updated)
    else:
        updated.setdefault("accountant_summary", _accountant_summary(updated))
        updated.setdefault("accountant_explanation_tr", updated.get("accountant_explanation_tr") or _ai_explanation_tr(updated))
        updated.setdefault("ai_explanation_tr", _ai_explanation_tr(updated))
    updated.setdefault("technical_details", _technical_details(updated))
    return updated


def _research_candidate_from_result(result: dict[str, Any], document: dict[str, Any]) -> str:
    for value in (
        result.get("ai_research_query"),
        result.get("ai_product_identity"),
        result.get("product_line_hint"),
        document.get("original_file_name"),
    ):
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return ""


def _should_run_research_for_result(result: dict[str, Any]) -> bool:
    if result.get("ai_resolution_status") == "ai_retry_required":
        return True
    if bool(result.get("ai_research_requested")):
        return True
    category = str(result.get("product_category") or "").strip()
    relation = str(result.get("business_relevance_relation") or "").strip()
    treatment = str(result.get("business_relevance_account_treatment") or "").strip()
    status = str(result.get("business_relevance_status") or "").strip()
    product_confidence = int(result.get("product_confidence") or 0)
    if category in {"", "bilinmeyen", "not_assessed"}:
        return True
    if product_confidence < 70:
        return True
    if relation == "weak_match":
        return True
    if treatment in {"manual_review", "non_deductible_review"}:
        return True
    return status == "is_alani_disi"


def _apply_research_accounting_effect(
    result: dict[str, Any],
    profile: dict[str, Any],
    *,
    client_profile: ClientProfile | None,
) -> dict[str, Any]:
    category = str(profile.get("product_category") or "").strip()
    if not category or not client_profile:
        return result
    confidence = int(profile.get("accounting_impact_confidence") or profile.get("research_confidence") or 0)
    classification = ProductClassification(
        raw_line=str(result.get("product_line_hint") or profile.get("display_name") or ""),
        category=category,
        confidence=confidence,
        evidence=("research_profile",),
    )
    relevance = assess_business_relevance(
        str(result.get("product_line_hint") or profile.get("display_name") or ""),
        client_profile,
        supplier_hint=str(result.get("provider_hint") or ""),
        classification=classification,
    )
    updated = dict(result)
    updated["product_category"] = relevance.classification.category
    updated["product_confidence"] = relevance.classification.confidence
    updated["business_relevance_status"] = relevance.status
    updated["business_relevance_confidence"] = relevance.confidence
    updated["business_relevance_reason"] = relevance.reason
    updated["business_relevance_evidence"] = list(relevance.evidence)
    updated["business_relevance_relation"] = relevance.relation
    updated["business_relevance_account_treatment"] = relevance.account_treatment
    updated["business_relevance_requires_review"] = relevance.requires_accountant_review
    return updated


def _research_classification_from_profile(result: dict[str, Any], profile: dict[str, Any]) -> ProductClassification | None:
    category = str(profile.get("product_category") or "").strip()
    if not category:
        return None
    confidence = int(profile.get("accounting_impact_confidence") or profile.get("research_confidence") or 0)
    return ProductClassification(
        raw_line=str(result.get("product_line_hint") or profile.get("display_name") or ""),
        category=category,
        confidence=confidence,
        evidence=("research_profile",),
    )


def _preserve_ai_fields(rebuilt: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    preserved = dict(rebuilt)
    for key in (
        "ai_classification_used",
        "ai_classification_provider",
        "ai_classification_skipped_reason",
        "ai_classification_reason",
        "ai_estimated_input_chars",
        "ai_suggested_account_code",
        "ai_suggested_counterparty_code",
        "ai_risk_flags",
        "ai_account_reason",
        "ai_gate_reason",
        "ai_product_identity",
        "ai_research_requested",
        "ai_research_query",
    ):
        if key in original:
            preserved[key] = original[key]
    return _with_review_summary(preserved)


def _rebuild_result_with_research(
    result: dict[str, Any],
    *,
    document: dict[str, Any],
    job: dict[str, Any],
    workspace: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    classification = _research_classification_from_profile(result, profile)
    path = _stored_path(document)
    if classification is None or path is None:
        return _apply_research_accounting_effect(result, profile, client_profile=_client_profile(workspace))
    document_type = str(document.get("document_type") or job.get("document_type") or "invoice")
    invoice = _parse_invoice_document(path, document_type)
    rebuilt = _serializable_simulation(
        invoice,
        workspace,
        intended_direction=str(document.get("intake_category") or job.get("intake_category") or ""),
        classification_override=classification,
    )
    return _preserve_ai_fields(rebuilt, result)


def _canonical_client_identity(workspace: dict[str, Any]) -> dict[str, object]:
    profile = ((workspace.get("client") or {}).get("profile") or {}) if isinstance(workspace, dict) else {}
    return {
        "title": profile.get("display_title") or profile.get("title") or profile.get("legal_name") or "",
        "tax_id": profile.get("tax_identifier") or profile.get("tax_id") or profile.get("vkn") or profile.get("tckn") or "",
    }


def _parse_invoice_document(
    path: Path,
    document_type: str,
    *,
    canonical_extraction_provider: object | None = None,
    canonical_extraction_policy: CanonicalExtractionPolicy | None = None,
    client_identity: dict[str, object] | None = None,
) -> ParsedInvoice:
    if document_type == "einvoice_xml" or path.suffix.lower() == ".xml":
        return parse_xml_invoice(path)
    return parse_pdf_invoice(
        path,
        canonical_extraction_provider=canonical_extraction_provider,
        canonical_extraction_policy=canonical_extraction_policy,
        client_identity=client_identity,
    )


def _intake_direction(value: str) -> str:
    normalized = value.strip().lower().replace("ı", "i").replace("ş", "s")
    if normalized in {"sales_invoice", "satis", "satis_faturasi", "satis faturasi"}:
        return "sales"
    if normalized in {"purchase_invoice", "alis", "alis_faturasi", "alis faturasi"}:
        return "purchase"
    return ""


def _unexpected_document_result(document: dict[str, Any], job: dict[str, Any], *, reason: str) -> dict[str, Any]:
    file_name = str(document.get("original_file_name") or document.get("document_ref") or job.get("document_ref") or "")
    return _with_review_summary(
        {
            "chart_file_name": "workspace-store",
            "file_name": file_name,
            "provider_hint": "",
            "invoice_type": str(document.get("document_type") or job.get("document_type") or "invoice"),
            "issue_date": "",
            "payable_total": "0.00",
            "vat_rates": [],
            "simulated_status": "review_required",
            "status": "review_required",
            "draft_quality": "manual_draft_required",
            "is_balanced": False,
            "risk_flags": ["unexpected_document_type"],
            "parse_notes": [reason],
            "review_reason_codes": ["unexpected_document_type"],
            "processing_mode": "controlled_automation",
            "draft_decision_source": "document_validation",
            "deterministic_checks": ["expected_document_shape_missing"],
            "export_gate_reason": "Dosya beklenen belge turunde olmadigi icin ciktiya alinamaz.",
            "product_line_hint": "",
            "product_category": "",
            "product_confidence": 0,
            "business_relevance_status": "supheli",
            "business_relevance_confidence": 0,
            "business_relevance_reason": "Dosya beklenen belge turunde gorunmuyor.",
            "business_relevance_evidence": [],
            "ai_classification_used": False,
            "ai_classification_provider": "",
            "ai_classification_skipped_reason": "unexpected_document_type",
            "ai_classification_reason": "",
            "ai_estimated_input_chars": 0,
            "learning_rule_applied": False,
            "learning_rule_scope": "",
            "learning_rule_reason": "",
            "export_status": "review_required",
            "selected_expense_account": "",
            "selected_vat_account": "",
            "selected_supplier_account": "",
            "counterparty_match_code": "",
            "counterparty_match_confidence": 0,
            "counterparty_match_reason": "not_found",
            "draft_lines": [],
        },
        document_validation_status="unexpected_document",
    )


def _statement_total(lines: tuple[Any, ...]) -> str:
    total = Decimal("0")
    for line in lines:
        try:
            total += Decimal(line.amount)
        except Exception:
            continue
    return f"{total:.2f}"


def build_statement_processing_result(
    document: dict[str, Any],
    job: dict[str, Any],
    path: Path,
    workspace: dict[str, Any],
    *,
    statement_ai_provider: StatementSuggestionProvider | None = None,
    statement_ai_policy: StatementAiSuggestionPolicy | None = None,
) -> dict[str, Any]:
    lines = enrich_statement_lines_with_counterparties(
        parse_statement_file(path),
        _chart_accounts(workspace),
        workspace.get("learning_events") or (),
    )
    selection = _account_selection(workspace)
    source_document_ref = str(document.get("document_ref") or document.get("document_id") or document.get("original_file_name") or "")
    entry_records = build_statement_entry_records(
        lines=lines,
        bank_account=selection.bank_account,
        document_ref=source_document_ref,
    )
    entries = tuple(entry for _, entry in entry_records)
    line_risk_flags = tuple(dict.fromkeys(flag for line in lines for flag in line.risk_flags))
    risk_flags = (
        tuple(dict.fromkeys((*line_risk_flags, "statement_accountant_approval_required")))
        if lines
        else ("statement_parser_required",)
    )
    review_reason_codes = risk_flags
    is_balanced = bool(entries) and all(entry.is_balanced for entry in entries)
    draft_lines = entries[0].lines if entries else ()
    ai_batch = suggest_statement_lines(
        lines,
        provider=statement_ai_provider,
        policy=statement_ai_policy,
    )
    ai_batch_data = statement_ai_batch_payload(ai_batch)
    ai_used = ai_batch.ai_used_count > 0
    return _with_review_summary({
        "chart_file_name": "workspace-store",
        "file_name": str(document.get("original_file_name") or path.name),
        "provider_hint": "Banka/POS ekstresi",
        "invoice_type": str(document.get("document_type") or job.get("document_type") or "statement"),
        "issue_date": lines[0].transaction_date if lines else "",
        "payable_total": _statement_total(lines),
        "vat_rates": [],
        "simulated_status": "review_required",
        "status": "review_required",
        "draft_quality": "statement_entries_ready" if entries else "statement_parse_pending",
        "is_balanced": is_balanced,
        "risk_flags": list(risk_flags),
        "parse_notes": [f"{len(lines)} statement satiri parse edildi."] if lines else ["statement satiri bulunamadi."],
        "review_reason_codes": list(review_reason_codes),
        "processing_mode": "controlled_automation",
        "draft_decision_source": "static_statement_rules",
        "deterministic_checks": [
            "statement_lines_parsed" if lines else "statement_lines_missing",
            "balanced_entry" if is_balanced else "balanced_entry_missing",
            "statement_risk_flags_clear" if not line_risk_flags else "statement_risk_flags_present",
            "statement_accountant_approval_required" if lines else "statement_accountant_approval_missing",
        ],
        "export_gate_reason": "Ekstre satirlari musavir onayindan sonra export paketine alinabilir."
        if is_balanced
        else "Ekstre satirlari musavir kontrolu veya risk temizligi gerektiriyor.",
        "product_line_hint": lines[0].description if lines else "",
        "product_category": lines[0].transaction_type if lines else "",
        "product_confidence": lines[0].confidence if lines else 0,
        "business_relevance_status": "supheli",
        "business_relevance_confidence": lines[0].confidence if lines else 0,
        "business_relevance_reason": "Ekstre satirlari muhasebe taslagi icin musavir kontrolune hazirlandi.",
        "business_relevance_evidence": [f"{line.transaction_type}:{line.suggested_account_code}" for line in lines[:5]],
        "ai_classification_used": ai_used,
        "ai_classification_provider": ai_batch.provider if ai_used else "static_statement_rules",
        "ai_classification_skipped_reason": "" if ai_used else "static_statement_rules",
        "ai_classification_reason": "AI banka satiri icin yapilandirilmis oneriler uretti." if ai_used else "",
        "ai_estimated_input_chars": ai_batch.estimated_input_chars,
        "learning_rule_applied": any(line.counterparty_match_reason == "learning_event" for line in lines),
        "learning_rule_scope": "",
        "learning_rule_reason": "Banka satiri onceki musavir kararina gore cariyle eslesti."
        if any(line.counterparty_match_reason == "learning_event" for line in lines)
        else "",
        "export_status": "review_required",
        "selected_expense_account": "",
        "selected_vat_account": "",
        "selected_supplier_account": lines[0].suggested_account_code if lines else "",
        "counterparty_match_code": lines[0].suggested_account_code if lines else "",
        "counterparty_match_confidence": lines[0].confidence if lines else 0,
        "counterparty_match_reason": lines[0].counterparty_match_reason if lines else "not_found",
        "draft_lines": [
            {
                "account_code": line.account_code,
                "description": line.description,
                "debit": f"{line.debit:.2f}",
                "credit": f"{line.credit:.2f}",
            }
            for line in draft_lines
        ],
        "statement_lines": [asdict(line) for line in lines],
        "statement_entries": [
            statement_entry_payload(line=line, entry=entry, source_document_ref=source_document_ref)
            for line, entry in entry_records
        ],
        "statement_ai_suggestions": ai_batch_data["suggestions"],
        "statement_ai_summary": {
            key: value for key, value in ai_batch_data.items() if key != "suggestions"
        },
    })


def build_initial_processing_result(document: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    file_name = str(document.get("original_file_name") or document.get("document_ref") or job.get("document_ref") or "")
    document_type = str(document.get("document_type") or job.get("document_type") or "invoice")
    parser_kind = str(job.get("parser_kind") or parser_kind_for_document_type(document_type))
    review_code = "parser_output_required"
    if document_type in {"bank_statement", "pos_statement"}:
        review_code = "statement_parser_required"
    if parser_kind == "manual_review":
        review_code = "manual_review_required"
    return _with_review_summary({
        "chart_file_name": "workspace-store",
        "file_name": file_name,
        "provider_hint": "",
        "invoice_type": document_type,
        "issue_date": "",
        "payable_total": "0.00",
        "vat_rates": [],
        "simulated_status": "review_required",
        "status": "review_required",
        "draft_quality": "partial_review_required",
        "is_balanced": False,
        "risk_flags": [review_code],
        "parse_notes": [f"{parser_kind} parser secildi; gercek parse ciktisi bekleniyor."],
        "review_reason_codes": [review_code],
        "processing_mode": "ai_assisted_draft",
        "draft_decision_source": "parser_placeholder",
        "deterministic_checks": ["parse_output_missing", "balanced_entry_missing"],
        "export_gate_reason": "Belge musavir kontrolu olmadan export'a alinmaz."
        if parser_kind == "manual_review"
        else "Parse sonucu henuz fis taslagina donusmedigi icin export kapali.",
        "product_line_hint": "",
        "product_category": "",
        "product_confidence": 0,
        "business_relevance_status": "supheli",
        "business_relevance_confidence": 0,
        "business_relevance_reason": "Belge yuklendi ancak parse sonucu henuz muhasebe taslagina donusmedi.",
        "business_relevance_evidence": [],
        "ai_classification_used": False,
        "ai_classification_provider": "",
        "ai_classification_skipped_reason": "worker_initial_parse_placeholder",
        "ai_classification_reason": "",
        "ai_estimated_input_chars": 0,
        "learning_rule_applied": False,
        "learning_rule_scope": "",
        "learning_rule_reason": "",
        "export_status": "review_required",
        "selected_expense_account": "",
        "selected_vat_account": "",
        "selected_supplier_account": "",
        "counterparty_match_code": "",
        "counterparty_match_confidence": 0,
        "counterparty_match_reason": "not_found",
        "draft_lines": [],
    }, document_validation_status="manual_review" if parser_kind == "manual_review" else "parse_pending")


def build_processing_result(
    document: dict[str, Any],
    job: dict[str, Any],
    workspace: dict[str, Any],
    *,
    product_classifier: ProductClassifier | None = None,
    canonical_extraction_provider: object | None = None,
    canonical_extraction_policy: CanonicalExtractionPolicy | None = None,
    statement_ai_provider: StatementSuggestionProvider | None = None,
    statement_ai_policy: StatementAiSuggestionPolicy | None = None,
) -> dict[str, Any]:
    document_type = str(document.get("document_type") or job.get("document_type") or "invoice")
    path = _stored_path(document)
    if path is None:
        return build_initial_processing_result(document, job)
    if document_type in {"bank_statement", "pos_statement"}:
        return build_statement_processing_result(
            document,
            job,
            path,
            workspace,
            statement_ai_provider=statement_ai_provider,
            statement_ai_policy=statement_ai_policy,
        )
    invoice = _parse_invoice_document(
        path,
        document_type,
        canonical_extraction_provider=canonical_extraction_provider,
        canonical_extraction_policy=canonical_extraction_policy,
        client_identity=_canonical_client_identity(workspace),
    )
    if not _invoice_has_expected_shape(invoice):
        return _unexpected_document_result(
            document,
            job,
            reason="Fatura numarasi, tarih, tutar veya vergi kimligi okunamadi.",
        )
    return _serializable_simulation(
        invoice,
        workspace,
        product_classifier=product_classifier,
        intended_direction=str(document.get("intake_category") or job.get("intake_category") or ""),
    )


def _record_ai_usage_from_result(store: Any, *, client_id: str, result: dict[str, Any]) -> None:
    if not hasattr(store, "record_ai_usage") or not result.get("ai_classification_used"):
        return
    provider = str(result.get("ai_classification_provider") or "unknown")
    input_chars = int(result.get("ai_estimated_input_chars") or 0)
    event = ai_usage_payload(
        build_ai_usage_event(
            client_id=client_id,
            provider=provider,
            operation="worker_ai_assisted_draft",
            input_chars=input_chars,
            ai_used=True,
            skipped_reason="",
        )
    )
    store.record_ai_usage(client_id=client_id, event=event)


def _record_ai_capacity_snapshot(store: Any, provider: Any) -> None:
    if not hasattr(store, "record_ai_capacity_snapshot") or provider is None:
        return
    snapshot = getattr(provider, "last_capacity_snapshot", {}) or {}
    if not isinstance(snapshot, dict) or not snapshot:
        return
    provider_name = str(getattr(provider, "last_provider_name", "") or getattr(provider, "provider_name", "")).strip()
    if not provider_name:
        return
    store.record_ai_capacity_snapshot(provider=provider_name, snapshot=snapshot)


def _record_research_usage(
    store: Any,
    *,
    client_id: str,
    provider_name: str,
    input_chars: int,
) -> None:
    if not hasattr(store, "record_ai_usage"):
        return
    event = ai_usage_payload(
        build_ai_usage_event(
            client_id=client_id,
            provider=provider_name or "research_agent",
            operation="internet_research",
            input_chars=input_chars,
            ai_used=True,
            skipped_reason="",
        )
    )
    store.record_ai_usage(client_id=client_id, event=event)


def _duration_ms(start: float) -> int:
    return max(int((time.perf_counter() - start) * 1000), 0)


def _timestamp_to_ms(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - timestamp).total_seconds() * 1000), 0)


def process_next_job_once(
    store: Any,
    *,
    product_classifier: ProductClassifier | None = None,
    statement_ai_provider: StatementSuggestionProvider | None = None,
    statement_ai_policy: StatementAiSuggestionPolicy | None = None,
    research_runtime: dict[str, object] | None = None,
) -> dict[str, Any]:
    job = store.claim_next_processing_job()
    if job is None:
        return {"processed_count": 0, "completed_count": 0, "failed_count": 0}
    client_id = str(job["client_id"])
    document_ref = str(job.get("document_ref") or "")
    total_start = time.perf_counter()
    parse_ms = 0
    ai_ms = 0
    research_ms = 0
    selected_provider = ""
    research_cache_hit = False
    nace_cache_hit = False

    def pipeline_event(step: str, status: str, message_tr: str, debug_code: str, details: dict[str, Any] | None = None) -> None:
        if not hasattr(store, "record_document_pipeline_event"):
            return
        store.record_document_pipeline_event(
            client_id=client_id,
            document_ref=document_ref,
            step=step,
            status=status,
            message_tr=message_tr,
            debug_code=debug_code,
            details=details or {},
        )

    try:
        pipeline_event(
            "parse_started",
            "ok",
            "Belge parse edilmeye basladi.",
            "parse_started",
            {"parser_kind": str(job.get("parser_kind") or "")},
        )
        workspace = store.get_workspace(client_id)
        profile = (workspace.get("client") or {}).get("profile") or {}
        nace_code = str(profile.get("nace_code") or "").strip()
        nace_cache_hit = bool(profile.get("activity_tags")) or bool(
            nace_code and hasattr(store, "get_nace_research_profile") and store.get_nace_research_profile(nace_code)
        )
        document = next(
            (
                item
                for item in workspace.get("uploaded_documents", [])
                if str(item.get("document_ref")) == document_ref
                or str(item.get("document_id")) == document_ref
            ),
            None,
        )
        if document is None:
            raise ValueError(f"uploaded document not found: {document_ref}")
        runtime = (
            {
                "product_classifier": product_classifier,
                "canonical_extraction_provider": None,
                "canonical_extraction_policy": CanonicalExtractionPolicy(),
                "statement_ai_provider": statement_ai_provider,
                "statement_ai_policy": statement_ai_policy,
            }
            if product_classifier or statement_ai_provider or statement_ai_policy
            else build_ai_runtime_from_env()
        )
        selected_provider = getattr(getattr(runtime["product_classifier"], "provider", None), "provider_name", "")
        if selected_provider:
            pipeline_event(
                "ai_provider_selected",
                "ok",
                f"AI provider secildi: {selected_provider}.",
                "ai_provider_selected",
                {"provider": selected_provider},
            )
        workspace = _workspace_with_nace_research(workspace, store)
        parse_start = time.perf_counter()
        result = build_processing_result(
            document,
            job,
            workspace,
            product_classifier=runtime["product_classifier"],
            canonical_extraction_provider=runtime.get("canonical_extraction_provider"),
            canonical_extraction_policy=runtime.get("canonical_extraction_policy"),
            statement_ai_provider=runtime["statement_ai_provider"],
            statement_ai_policy=runtime["statement_ai_policy"],
        )
        parse_ms = _duration_ms(parse_start)
        product_provider = getattr(runtime["product_classifier"], "provider", None)
        if str(result.get("ai_classification_provider") or "") not in {"", "static_rules"} or bool(
            result.get("canonical_extraction_ai_used")
        ):
            ai_ms = parse_ms
        _record_ai_capacity_snapshot(store, product_provider)
        _record_ai_capacity_snapshot(store, runtime["statement_ai_provider"])
        pipeline_event(
            "parse_succeeded",
            "ok",
            "Belge parse edildi.",
            "parse_succeeded",
            {
                "document_validation_status": str(result.get("document_validation_status") or ""),
                "product_category": str(result.get("product_category") or ""),
            },
        )
        canonical_line_count = int(result.get("canonical_line_count") or 0)
        canonical_validation_status = str(result.get("canonical_validation_status") or "")
        canonical_validation_reasons = list(result.get("canonical_validation_reasons") or [])
        pipeline_event(
            "canonical_extraction_completed",
            "ok" if canonical_validation_status != "invalid" else "warning",
            "Canonical fatura modeli hazirlandi.",
            "canonical_extraction_completed",
            {
                "line_count": canonical_line_count,
                "validation_status": canonical_validation_status,
                "validation_reasons": canonical_validation_reasons,
                "ai_used": bool(result.get("canonical_extraction_ai_used")),
            },
        )
        pipeline_event(
            "line_items_extracted" if canonical_line_count > 0 else "line_items_missing",
            "ok" if canonical_line_count > 0 else "warning",
            "Fatura satirlari okundu." if canonical_line_count > 0 else "Fatura satirlari okunamadi.",
            "line_items_extracted" if canonical_line_count > 0 else "line_items_missing",
            {"line_count": canonical_line_count},
        )
        if canonical_validation_status == "invalid":
            pipeline_event(
                "canonical_validation_failed",
                "warning",
                "Canonical fatura mutabakati saglanamadi.",
                "canonical_validation_failed",
                {"validation_reasons": canonical_validation_reasons},
            )
        if bool(result.get("canonical_extraction_ai_used")):
            pipeline_event(
                "canonical_extraction_ai_used",
                "ok",
                "Canonical fatura modeli AI yardimiyla tamamlandi.",
                "canonical_extraction_ai_used",
                {"line_count": canonical_line_count},
            )
        pipeline_event(
            "party_resolution_completed",
            "ok",
            "Satici/alici ve karsi taraf bilgisi canonical modelden cozuldu.",
            "party_resolution_completed",
            {
                "accounting_direction": str(result.get("accounting_direction") or ""),
                "counterparty_title": str(result.get("counterparty_title") or ""),
                "counterparty_tax_id": str(result.get("counterparty_tax_id") or ""),
            },
        )
        if result.get("accounting_direction"):
            pipeline_event(
                "direction_detected",
                "ok",
                "Fatura yonu icerikten tespit edildi.",
                "direction_detected",
                {
                    "accounting_direction": str(result.get("accounting_direction") or ""),
                    "direction_confidence": int(result.get("direction_confidence") or 0),
                    "direction_uncertainty": bool(result.get("direction_uncertainty")),
                    "direction_evidence": list(result.get("direction_evidence") or []),
                },
            )
            intended_direction = _intake_direction(str(document.get("intake_category") or job.get("intake_category") or ""))
            detected_direction = str(result.get("accounting_direction") or "")
            if intended_direction and detected_direction in {"sales", "purchase"} and intended_direction != detected_direction:
                pipeline_event(
                    "direction_conflict_detected",
                    "warning",
                    "Yukleme sekmesi ile belge icerigi celisti; icerik karari kazandi.",
                    "direction_conflict_detected",
                    {
                        "intake_direction": intended_direction,
                        "detected_direction": detected_direction,
                    },
                )
        if "vat_rates" in result:
            pipeline_event(
                "vat_summary_parsed",
                "ok",
                "KDV ozeti parse edildi.",
                "vat_summary_parsed",
                {
                    "vat_rates": list(result.get("vat_rates") or []),
                    "vat_total": str(result.get("vat_total") or ""),
                    "payable_total": str(result.get("payable_total") or ""),
                },
            )
        vat_split_review = result.get("vat_split_review") if isinstance(result.get("vat_split_review"), dict) else {}
        if vat_split_review:
            requires_vat_review = bool(vat_split_review.get("requires_accountant_review"))
            pipeline_event(
                "vat_split_classified",
                "warning" if requires_vat_review else "ok",
                "KDV ayrimi guven sinifina alindi.",
                "vat_split_classified",
                {
                    "status": str(vat_split_review.get("status") or ""),
                    "confidence": str(vat_split_review.get("confidence") or ""),
                    "similarity_key": str(vat_split_review.get("similarity_key") or ""),
                    "requires_accountant_review": requires_vat_review,
                    "review_reason_codes": list(vat_split_review.get("review_reason_codes") or []),
                },
            )
        if result.get("accountant_explanation_tr"):
            pipeline_event(
                "accounting_explanation_ready",
                "ok",
                "Musavir icin muhasebe gerekcesi hazirlandi.",
                "accounting_explanation_ready",
                {"accountant_explanation_tr": str(result.get("accountant_explanation_tr") or "")},
            )
        if any("ocr" in str(note).lower() for note in result.get("parse_notes") or []):
            pipeline_event(
                "ocr_fallback_succeeded",
                "ok",
                "Belge OCR fallback ile okundu.",
                "ocr_fallback_succeeded",
                {"parse_notes": list(result.get("parse_notes") or [])},
            )
        ai_provider_name = str(result.get("ai_classification_provider") or "")
        if ai_provider_name and ai_provider_name != "static_rules":
            ai_status = "error" if result.get("ai_classification_skipped_reason") == "ai_provider_error" else "ok"
            pipeline_event(
                "ai_decision_ready" if ai_status == "ok" else "ai_provider_failed",
                ai_status,
                "AI geldi karar verdi." if ai_status == "ok" else "AI provider karar veremedi; belge tekrar denenecek.",
                "ai_decision_ready" if ai_status == "ok" else "ai_provider_failed",
                {
                    "provider": str(result.get("ai_classification_provider") or ""),
                    "skipped_reason": str(result.get("ai_classification_skipped_reason") or ""),
                    "reason": str(result.get("ai_classification_reason") or ""),
                },
            )
            pipeline_event(
                "accountant_ai_explanation_ready",
                "ok",
                "Musavir AI ciktisini Turkce gerekceyle gorebilir.",
                "accountant_ai_explanation_ready",
                {"ai_explanation_tr": str(result.get("ai_explanation_tr") or _ai_explanation_tr(result))},
            )
        if result.get("business_relevance_relation") == "weak_match":
            pipeline_event(
                "weak_match",
                "warning",
                "Kalem faaliyet profiliyle zayif eslesti.",
                "weak_match",
                {"business_relevance_reason": str(result.get("business_relevance_reason") or "")},
            )
        effective_research_runtime = research_runtime if research_runtime is not None else build_research_runtime_from_env(environ)
        research_document_type = str(document.get("document_type") or job.get("document_type") or "invoice")
        if effective_research_runtime and research_document_type not in {"bank_statement", "pos_statement"}:
            raw_line = _research_candidate_from_result(result, document)
            if raw_line and _should_run_research_for_result(result):
                activity_context = str((workspace.get("client") or {}).get("profile", {}).get("activity_description") or "")
                query = sanitize_research_query(
                    kind="brand",
                    raw_line=raw_line,
                    supplier_hint=str(result.get("provider_hint") or ""),
                    activity_context=activity_context,
                )
                cache_key = normalize_product_research_key(query.search_text or query.key)
                cached = store.get_brand_research_profile(cache_key) if hasattr(store, "get_brand_research_profile") else None
                research_cache_hit = bool(cached)
                pipeline_event(
                    "research_cache_hit" if cached else "research_started",
                    "ok",
                    "Research cache kullanildi." if cached else "Marka/NACE arastirmasi basladi.",
                    "research_cache_hit" if cached else "research_started",
                    {
                        "kind": "brand",
                        "search_text": query.search_text,
                        "supplier_hint": query.supplier_hint,
                    },
                )
                harness = ResearchHarness(
                    store=store,
                    provider=effective_research_runtime.get("provider"),  # type: ignore[arg-type]
                    policy=effective_research_runtime.get("policy"),  # type: ignore[arg-type]
                )
                research_start = time.perf_counter()
                profile = harness.research_brand(
                    raw_line=raw_line,
                    supplier_hint=str(result.get("provider_hint") or ""),
                    activity_context=activity_context,
                )
                research_ms += _duration_ms(research_start)
                if harness.call_count > 0:
                    _record_research_usage(
                        store,
                        client_id=client_id,
                        provider_name=str(getattr(effective_research_runtime.get("provider"), "provider_name", "")),
                        input_chars=len(query.search_text) + len(query.supplier_hint) + len(query.activity_context),
                    )
                threshold = int(getattr(effective_research_runtime.get("policy"), "confidence_threshold", 70))
                result = _rebuild_result_with_research(
                    result,
                    document=document,
                    job=job,
                    workspace=workspace,
                    profile=profile,
                )
                result = apply_research_to_result(result, profile, confidence_threshold=threshold)
                confidence = int(profile.get("research_confidence") or profile.get("confidence") or 0)
                research_ok = confidence >= threshold
                pipeline_event(
                    "research_completed" if research_ok else "research_low_confidence",
                    "ok" if research_ok else "warning",
                    "Arastirma profili hazirlandi." if research_ok else "Arastirma guveni dusuk; belge kontrolde kaldi.",
                    "research_completed" if research_ok else "research_low_confidence",
                    {
                        "display_name": str(profile.get("display_name") or ""),
                        "confidence": confidence,
                        "source_urls": list(profile.get("source_urls") or []),
                    },
                )
                if "research_source_rejected" in set(result.get("review_reason_codes") or []):
                    pipeline_event(
                        "research_source_rejected",
                        "warning",
                        "Arastirma kaynagi kaynak politikasindan gecemedi.",
                        "research_source_rejected",
                        {"source_urls": list(profile.get("source_urls") or [])},
                    )
        result = _with_review_summary(result)
        if result.get("ai_resolution_status") == "ai_retry_required":
            pipeline_event(
                "ai_retry_required",
                "warning",
                "AI ajani mesgul veya karar tamamlanamadi; belge tekrar denenecek.",
                "ai_retry_required",
                {
                    "reason": str(result.get("ai_retry_reason") or ""),
                    "static_fallback_account": str(result.get("static_fallback_account") or ""),
                    "static_fallback_suppressed": bool(result.get("static_fallback_suppressed")),
                },
            )
        if result.get("draft_lines"):
            pipeline_event(
                "journal_draft_ready",
                "ok",
                "Belge muhasebe fisi olarak doldu.",
                "journal_draft_ready",
                {"draft_line_count": len(result.get("draft_lines") or [])},
            )
        if result.get("draft_lines") and not result.get("is_balanced"):
            pipeline_event(
                "journal_unbalanced",
                "warning",
                "Muhasebe fisi dengeli degil.",
                "journal_unbalanced",
                {
                    "total_debit": str(result.get("total_debit") or ""),
                    "total_credit": str(result.get("total_credit") or ""),
                },
            )
        if result.get("export_status") == "export_ready":
            pipeline_event(
                "export_ready",
                "ok",
                "Muhasebe fisi kaydedildi; exporta gonderilebilir durumda.",
                "export_ready",
                {},
            )
        store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
        )
        _record_ai_usage_from_result(store, client_id=client_id, result=result)
        processing_metrics = {
            "queue_wait_ms": _timestamp_to_ms(job.get("created_at")),
            "parse_ms": parse_ms,
            "ai_ms": ai_ms,
            "research_ms": research_ms,
            "total_ms": _duration_ms(total_start),
            "provider": selected_provider or str(result.get("ai_classification_provider") or ""),
            "research_cache_hit": research_cache_hit,
            "nace_cache_hit": nace_cache_hit,
        }
        store.update_processing_job(job_id=str(job["id"]), status="completed", processing_metrics=processing_metrics)
        return {"processed_count": 1, "completed_count": 1, "failed_count": 0}
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        pipeline_event(
            "parser_failed",
            "error",
            "Belge parse edilemedi.",
            "parser_failed",
            {"error": str(exc)},
        )
        processing_metrics = {
            "queue_wait_ms": _timestamp_to_ms(job.get("created_at")),
            "parse_ms": parse_ms,
            "ai_ms": ai_ms,
            "research_ms": research_ms,
            "total_ms": _duration_ms(total_start),
            "provider": selected_provider,
            "research_cache_hit": research_cache_hit,
            "nace_cache_hit": nace_cache_hit,
        }
        store.update_processing_job(
            job_id=str(job.get("id") or ""),
            status="failed",
            error_message=str(exc),
            processing_metrics=processing_metrics,
        )
        return {"processed_count": 1, "completed_count": 0, "failed_count": 1}


def process_queued_documents(
    store: Any,
    *,
    max_jobs: int = 10,
    product_classifier: ProductClassifier | None = None,
    statement_ai_provider: StatementSuggestionProvider | None = None,
    statement_ai_policy: StatementAiSuggestionPolicy | None = None,
    research_runtime: dict[str, object] | None = None,
) -> dict[str, Any]:
    queued_count = 0
    try:
        queued_count = sum(1 for job in store.list_processing_jobs() if str(job.get("status") or "") == "queued")
    except Exception:
        queued_count = 0
    summary = {
        "run_id": f"processing-run-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
        "queued_count": queued_count,
        "processed_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "current_status": "running" if queued_count else "idle",
    }
    for _ in range(max_jobs):
        result = process_next_job_once(
            store,
            product_classifier=product_classifier,
            statement_ai_provider=statement_ai_provider,
            statement_ai_policy=statement_ai_policy,
            research_runtime=research_runtime,
        )
        if result["processed_count"] == 0:
            break
        for key in ("processed_count", "completed_count", "failed_count"):
            summary[key] += int(result[key])
    if summary["processed_count"] == 0:
        summary["current_status"] = "idle" if queued_count == 0 else "queued"
    elif summary["failed_count"]:
        summary["current_status"] = "completed_with_errors"
    else:
        summary["current_status"] = "completed"
    return summary
