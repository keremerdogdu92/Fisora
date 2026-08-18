from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
import json
from os import environ
from pathlib import Path
import re
import time
from typing import Any
import unicodedata
from uuid import uuid4

from app.domain.ai_classification import (
    AccountingSelectionRequest,
    AiClassificationContext,
    AiClassificationPolicy,
    ProductClassifier,
    StaticFirstClassifier,
    merge_semantic_attempt_result,
    serialize_semantic_decision_attempt,
)
from app.domain.accounting_candidate_expansion import (
    AccountingProposal,
    AccountingCandidateSession,
    CandidateIntegrityError,
    FinalizeProposalDecision,
    LineAccountSelection,
    NewCounterpartyProposal,
    ProposeNewDecision,
    RequestMoreCandidatesDecision,
    SelectedAccount,
    SelectExistingDecision,
    SpecialTaxAccountSelection,
    VatAccountSelection,
)
from app.domain.accounting_projection import build_accounting_projection
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event
from app.domain.ai_outage import next_ai_retry, sanitize_provider_failure_evidence
from app.domain.business_relevance import ClientProfile, ProductClassification
from app.domain.canonical_invoices import (
    CanonicalExtractionPolicy,
    CanonicalExtractionRequest,
    canonical_invoice_from_ai_payload,
)
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty
from app.domain.learning_rules import apply_learning_rules, rule_from_event_payload
from app.domain.matching_simulation import (
    AccountSelection,
    infer_accounting_direction,
    select_accounts,
    simulate_invoice,
)
from app.domain.verified_rule_authority import compile_verified_rule_authorities
from app.domain.nace_research import resolve_nace_research_profile
from app.domain.openai_provider import (
    CEREBRAS_CHAT_COMPLETIONS_URL,
    CLOUDFLARE_CHAT_COMPLETIONS_URL_TEMPLATE,
    DEFAULT_CEREBRAS_MODEL,
    DEFAULT_CLOUDFLARE_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    DEFAULT_SAMBANOVA_MODEL,
    DEFAULT_XKIRO_MODEL,
    GEMINI_GENERATE_CONTENT_URL_TEMPLATE,
    NVIDIA_CHAT_COMPLETIONS_URL,
    OPENROUTER_CHAT_COMPLETIONS_URL,
    SAMBANOVA_CHAT_COMPLETIONS_URL,
    XKIRO_CHAT_COMPLETIONS_URL,
    ChatCompletionsAccountingProvider,
    FallbackAccountingProvider,
    GeminiAccountingProvider,
    GroqAccountingProvider,
    OpenAiAccountingProvider,
    TaskRoutingAccountingProvider,
)
from app.domain.document_ai_artifacts import ArtifactKind, ArtifactWrite
from app.domain.gemini_pdf_runtime import (
    build_gemini_pdf_runtime_from_env,
    candidate_discovery_assignment,
    candidate_experiment_percent_from_env,
    gemini_pdf_v2_enabled,
    max_accounting_request_bytes_from_env,
)
from app.domain.pdf_invoices import ParsedInvoice, parse_pdf_invoice, parsed_invoice_from_canonical
from app.domain.research_harness import (
    ResearchHarness,
    apply_research_to_result,
    build_research_runtime_from_env,
    research_brand_cache_key,
    research_profile_is_fresh,
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
from app.workflows.gemini_invoice_pipeline import (
    GeminiInvoicePipelineRequest,
    run_gemini_invoice_pipeline_v2,
)
from app.workflows.gemini_invoice_result_adapter import to_document_processing_payload


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
    selection = _account_selection(workspace)
    direction, _, _ = infer_accounting_direction(
        invoice,
        profile,
        intended_direction=intended_direction,
    )
    canonical_lines = tuple(getattr(getattr(invoice, "canonical_invoice", None), "line_items", ()) or ())
    counterparty_tax_id = (
        str(getattr(invoice, "recipient_tax_id", "") or "")
        if direction == "sales"
        else str(getattr(invoice, "issuer_tax_id", "") or "")
    )
    invoice_mode = "return" if bool(getattr(invoice, "is_return_invoice", False)) else "ordinary"
    active_rules = tuple(workspace.get("learning_rules") or ())
    compiled_rules = compile_verified_rule_authorities(
        rules=active_rules,
        client_id=profile.client_id if profile else "",
        direction=direction if direction in {"purchase", "sales"} else "purchase",
        invoice_mode=invoice_mode,
        counterparty_tax_id=counterparty_tax_id,
        service_profile=str(getattr(invoice, "service_profile", "") or ""),
        canonical_lines=canonical_lines,
        account_selection=selection,
    )
    result = simulate_invoice(
        invoice,
        selection,
        profile,
        counterparty,
        product_classifier or StaticFirstClassifier(),
        processing_mode="ai_assisted_draft" if product_classifier else "controlled_automation",
        intended_direction=intended_direction,
        classification_override=classification_override,
        verified_rule_authorities=compiled_rules.authorities,
    )
    result = apply_learning_rules(
        result,
        [rule_from_event_payload(event) for event in workspace.get("learning_events") or []],
    )
    data = asdict(result)
    conflicts = list(getattr(compiled_rules, "conflicts", ()) or ())
    if conflicts:
        data["review_reason_codes"] = list(
            dict.fromkeys((*data.get("review_reason_codes", []), "verified_rule_conflict"))
        )
        data["risk_flags"] = list(dict.fromkeys((*data.get("risk_flags", []), "verified_rule_conflict")))
        data["export_status"] = "review_required"
        data["export_gate_reason"] = "Dogrulanmis kurallar ayni satir icin celisiyor; musavir secimi gerekli."
    data["verified_rule_authority_digest"] = _verified_rule_authority_digest(compiled_rules.authorities)
    data["verified_rule_conflicts"] = conflicts
    if invoice.canonical_invoice is not None:
        data["canonical_invoice"] = asdict(invoice.canonical_invoice)
    data["invoice_no"] = invoice.invoice_no
    data["ettn"] = invoice.ettn
    data["goods_services_total"] = invoice.goods_services_total
    data["vat_total"] = invoice.vat_total
    data["issuer_title"] = invoice.issuer_title
    data["issuer_tax_id"] = invoice.issuer_tax_id
    data["recipient_title"] = invoice.recipient_title
    data["recipient_tax_id"] = invoice.recipient_tax_id
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
        "semantic_attempts",
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


def _verified_rule_authority_digest(authorities: tuple[object, ...]) -> str:
    import hashlib
    import json

    payload = [
        {
            "canonical_line_id": str(getattr(item, "canonical_line_id", "")),
            "rule_id": str(getattr(item, "rule_id", "")),
            "rule_version": str(getattr(item, "rule_version", "")),
            "account_code": str(getattr(item, "account_code", "")),
        }
        for item in authorities
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _accounting_provider_from_env(provider_name: str, source: dict[str, str] | Any) -> OpenAiAccountingProvider:
    if provider_name == "gemini":
        model = source.get("FISORA_GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        return GeminiAccountingProvider(
            api_key=source.get("GEMINI_API_KEY", ""),
            model=model,
            generate_content_url=source.get("FISORA_GEMINI_GENERATE_CONTENT_URL", "")
            or GEMINI_GENERATE_CONTENT_URL_TEMPLATE.format(model=model),
            timeout_seconds=float(source.get("FISORA_GEMINI_TIMEOUT_SECONDS", "60")),
            max_output_tokens=int(source.get("FISORA_GEMINI_MAX_OUTPUT_TOKENS", "16384")),
            max_inline_pdf_bytes=int(source.get("FISORA_GEMINI_MAX_INLINE_PDF_BYTES", "50000000")),
        )
    if provider_name == "nvidia":
        return ChatCompletionsAccountingProvider(
            api_key=source.get("NVIDIA_API_KEY", ""),
            model=source.get("FISORA_NVIDIA_MODEL", DEFAULT_NVIDIA_MODEL),
            chat_completions_url=source.get(
                "FISORA_NVIDIA_CHAT_COMPLETIONS_URL",
                NVIDIA_CHAT_COMPLETIONS_URL,
            ),
            provider_name="nvidia",
            key_name="NVIDIA_API_KEY",
            timeout_seconds=float(source.get("FISORA_NVIDIA_TIMEOUT_SECONDS", "60")),
            max_tokens=int(source.get("FISORA_NVIDIA_MAX_TOKENS", "1024")),
        )
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
    if provider_name == "cloudflare":
        account_id = source.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not account_id:
            raise ValueError("CLOUDFLARE_ACCOUNT_ID is required when FISORA_AI_PROVIDER=cloudflare")
        return ChatCompletionsAccountingProvider(
            api_key=source.get("CLOUDFLARE_API_TOKEN", ""),
            model=source.get("FISORA_CLOUDFLARE_MODEL", DEFAULT_CLOUDFLARE_MODEL),
            chat_completions_url=source.get("FISORA_CLOUDFLARE_CHAT_COMPLETIONS_URL", "")
            or CLOUDFLARE_CHAT_COMPLETIONS_URL_TEMPLATE.format(account_id=account_id),
            provider_name="cloudflare",
            key_name="CLOUDFLARE_API_TOKEN",
            max_tokens=int(source.get("FISORA_CLOUDFLARE_MAX_TOKENS", "1024")),
        )
    if provider_name == "sambanova":
        return ChatCompletionsAccountingProvider(
            api_key=source.get("SAMBANOVA_API_KEY", ""),
            model=source.get("FISORA_SAMBANOVA_MODEL", DEFAULT_SAMBANOVA_MODEL),
            chat_completions_url=source.get(
                "FISORA_SAMBANOVA_CHAT_COMPLETIONS_URL",
                SAMBANOVA_CHAT_COMPLETIONS_URL,
            ),
            provider_name="sambanova",
            key_name="SAMBANOVA_API_KEY",
        )
    if provider_name == "xkiro":
        return ChatCompletionsAccountingProvider(
            api_key=source.get("XKIRO_API_KEY", ""),
            model=source.get("FISORA_XKIRO_MODEL", DEFAULT_XKIRO_MODEL),
            chat_completions_url=source.get(
                "FISORA_XKIRO_CHAT_COMPLETIONS_URL",
                XKIRO_CHAT_COMPLETIONS_URL,
            ),
            provider_name="xkiro",
            key_name="XKIRO_API_KEY",
            timeout_seconds=float(source.get("FISORA_XKIRO_TIMEOUT_SECONDS", "60")),
            max_tokens=int(source.get("FISORA_XKIRO_MAX_TOKENS", "1024")),
        )
    return OpenAiAccountingProvider(
        api_key=source.get("OPENAI_API_KEY", ""),
        model=source.get("FISORA_OPENAI_MODEL", source.get("FISORA_AI_MODEL", DEFAULT_OPENAI_MODEL)),
    )


SUPPORTED_ACCOUNTING_PROVIDERS = {
    "gemini",
    "openai",
    "groq",
    "openrouter",
    "cerebras",
    "nvidia",
    "cloudflare",
    "sambanova",
    "xkiro",
}


def _configured_provider_names(source: dict[str, str] | Any) -> tuple[str, ...]:
    chain = tuple(
        dict.fromkeys(
            name.strip().lower()
            for name in source.get("FISORA_AI_PROVIDER_CHAIN", "").split(",")
            if name.strip().lower() in SUPPORTED_ACCOUNTING_PROVIDERS
        )
    )
    provider_name = source.get("FISORA_AI_PROVIDER", "disabled").strip().lower()
    if not chain and provider_name in SUPPORTED_ACCOUNTING_PROVIDERS:
        return (provider_name,)
    return chain


def _task_provider_names(
    source: dict[str, str] | Any,
    *,
    env_key: str,
    preferred_order: tuple[str, ...],
) -> tuple[str, ...]:
    configured = _configured_provider_names(source)
    configured_set = set(configured)
    override = tuple(
        dict.fromkeys(
            name.strip().lower()
            for name in source.get(env_key, "").split(",")
            if name.strip().lower() in configured_set
        )
    )
    if override:
        return (*override, *(name for name in configured if name not in set(override)))
    return (
        *(name for name in preferred_order if name in configured_set),
        *(name for name in configured if name not in set(preferred_order)),
    )


def _provider_chain_from_names(
    names: tuple[str, ...],
    source: dict[str, str] | Any,
) -> OpenAiAccountingProvider | FallbackAccountingProvider | None:
    if not names:
        return None
    providers = [_accounting_provider_from_env(name, source) for name in names]
    return providers[0] if len(providers) == 1 else FallbackAccountingProvider(providers)


def _provider_chain_from_env(source: dict[str, str] | Any) -> OpenAiAccountingProvider | FallbackAccountingProvider | None:
    return _provider_chain_from_names(_configured_provider_names(source), source)


def build_ai_runtime_from_env(env: dict[str, str] | None = None) -> dict[str, object]:
    source = env or environ
    statement_provider = _provider_chain_from_env(source)
    if statement_provider is None:
        return {
            "product_classifier": None,
            "canonical_extraction_provider": None,
            "native_pdf_extraction_provider": None,
            "accounting_selection_provider": None,
            "canonical_extraction_policy": CanonicalExtractionPolicy(),
            "statement_ai_provider": None,
            "statement_ai_policy": StatementAiSuggestionPolicy(),
        }
    canonical_provider = _provider_chain_from_names(
        _task_provider_names(
            source,
            env_key="FISORA_AI_CANONICAL_PROVIDER_CHAIN",
            preferred_order=("gemini", "xkiro", "nvidia", "cerebras", "groq", "cloudflare", "sambanova", "openrouter", "openai"),
        ),
        source,
    )
    classification_provider = _provider_chain_from_names(
        _task_provider_names(
            source,
            env_key="FISORA_AI_CLASSIFICATION_PROVIDER_CHAIN",
            preferred_order=("gemini", "nvidia", "groq", "cerebras", "cloudflare", "sambanova", "openrouter", "openai"),
        ),
        source,
    )
    native_pdf_extraction_provider = (
        _accounting_provider_from_env("gemini", source)
        if "gemini" in _configured_provider_names(source)
        else None
    )
    counterparty_provider = _provider_chain_from_names(
        _task_provider_names(
            source,
            env_key="FISORA_AI_COUNTERPARTY_PROVIDER_CHAIN",
            preferred_order=("gemini", "nvidia", "cerebras", "groq", "cloudflare", "sambanova", "openrouter", "openai"),
        ),
        source,
    )
    semantic_provider = TaskRoutingAccountingProvider(
        classification_provider=classification_provider,
        counterparty_provider=counterparty_provider,
        configured_provider=statement_provider,
    )
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
        "product_classifier": StaticFirstClassifier(provider=semantic_provider, policy=product_policy),
        "canonical_extraction_provider": canonical_provider,
        "native_pdf_extraction_provider": native_pdf_extraction_provider,
        "accounting_selection_provider": native_pdf_extraction_provider,
        "canonical_extraction_policy": canonical_policy,
        "statement_ai_provider": statement_provider,
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


def _ai_attention_status(result: dict[str, Any]) -> str:
    status = str(result.get("ai_resolution_status") or "")
    return status if status in {"ai_retry_required", "ai_correction_required"} else ""


def _draft_status(result: dict[str, Any]) -> str:
    if result.get("document_validation_status") == "unexpected_document":
        return "wrong_document_type"
    if result.get("simulated_status") in {"no_posting", "no_posting_suggested"}:
        return "no_posting"
    if attention := _ai_attention_status(result):
        return attention
    if result.get("draft_lines"):
        return "draft_ready"
    return "manual_draft_required"


def _accountant_summary(result: dict[str, Any]) -> str:
    if result.get("document_validation_status") == "unexpected_document":
        return "Bu dosya beklenen fatura/ekstre yapisinda gorunmuyor. Dogru belge yeniden istenmeli."
    if result.get("simulated_status") in {"no_posting", "no_posting_suggested"}:
        return str(result.get("export_gate_reason") or "Kaynak belge icin muhasebe kaydi onerilmiyor.")
    if _ai_attention_status(result) == "ai_retry_required":
        return "AI ajani mesgul veya karar tamamlanamadi; belge tekrar denenecek."
    if _ai_attention_status(result) == "ai_correction_required":
        return "AI hesap karari tamamlanamadi; duzeltme gerekli ve fis taslagi olusturulmadi."
    if result.get("draft_lines"):
        if result.get("is_balanced"):
            markers = set(result.get("utility_exception_markers") or [])
            if "utility_installment_line" in markers:
                return "Taksitli hizmet/cihaz satırı görüldü; fiş taslağı hazır, bu istisnayı bir kez kontrol et."
            if "utility_device_line" in markers:
                return "Açık cihaz satırı görüldü; fiş taslağı hazır, bu istisnayı bir kez kontrol et."
            service_label = {
                "gsm_communication": "GSM iletişim",
                "fixed_internet": "Sabit internet",
                "electricity": "Elektrik",
                "water": "Su",
                "natural_gas": "Doğalgaz",
            }.get(str(result.get("service_profile") or ""))
            if service_label:
                return f"{service_label} gideri için fiş taslağı hazır. Müşavir onayından sonra çıktı listesine alınabilir."
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
        "ai_attempted_account_code": str(result.get("ai_attempted_account_code") or ""),
        "ai_stage_evidence": list(result.get("ai_stage_evidence") or []),
        "ai_account_stage_evidence": list(result.get("ai_account_stage_evidence") or []),
        "ai_counterparty_stage_evidence": list(result.get("ai_counterparty_stage_evidence") or []),
        "ai_trace": list(result.get("ai_trace") or []),
        "semantic_attempts": list(result.get("semantic_attempts") or []),
        "accepted_semantic_attempt_id": str(result.get("accepted_semantic_attempt_id") or ""),
        "direction_uncertainty": bool(result.get("direction_uncertainty")),
        "static_fallback_account": str(result.get("static_fallback_account") or ""),
        "static_fallback_suppressed": bool(result.get("static_fallback_suppressed")),
        "provider_id": str(result.get("provider_id") or ""),
        "service_profile": str(result.get("service_profile") or ""),
        "provider_match_kind": str(result.get("provider_match_kind") or ""),
        "provider_directory_version": int(result.get("provider_directory_version") or 0),
        "utility_exception_markers": list(result.get("utility_exception_markers") or []),
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
    if _ai_attention_status(result):
        retry_reason = str(result.get("ai_retry_reason") or skipped or "ai_not_resolved")
        if _ai_attention_status(result) == "ai_correction_required":
            if skipped == "ai_provider_error":
                return f"AI karari alinamadi. Provider {provider} hata verdi. Duzeltme gerekli. Sebep: {retry_reason}. Riskler: {risks}."
            return f"AI hesap karari gecersiz veya eksik; Provider {provider} icin duzeltme gerekli. Sebep: {retry_reason}. Hesap onerisi nihai taslaga yazilmadi. Riskler: {risks}."
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
    if attention := _ai_attention_status(updated):
        updated["draft_status"] = attention
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
        if _ai_attention_status(updated)
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
    if _ai_attention_status(updated):
        updated["accountant_summary"] = _accountant_summary(updated)
        updated["accountant_explanation_tr"] = _ai_explanation_tr(updated)
        updated["ai_explanation_tr"] = _ai_explanation_tr(updated)
    else:
        updated.setdefault("accountant_summary", _accountant_summary(updated))
        updated.setdefault("accountant_explanation_tr", updated.get("accountant_explanation_tr") or _ai_explanation_tr(updated))
        updated.setdefault("ai_explanation_tr", _ai_explanation_tr(updated))
    updated["technical_details"] = _technical_details(updated)
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


def _canonical_line_ids_for_research(result: dict[str, Any]) -> tuple[str, ...]:
    for attempt in reversed(result.get("semantic_attempts") or []):
        if not isinstance(attempt, dict):
            continue
        line_ids = tuple(
            str(item).strip()
            for item in attempt.get("canonical_line_ids") or []
            if str(item).strip()
        )
        if line_ids:
            return line_ids
    canonical_invoice = result.get("canonical_invoice") if isinstance(result.get("canonical_invoice"), dict) else {}
    return tuple(
        str(item.get("canonical_line_id") or "").strip()
        for item in canonical_invoice.get("line_items") or []
        if isinstance(item, dict) and str(item.get("canonical_line_id") or "").strip()
    )


def _research_semantic_attempt(result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    candidate_account_codes = tuple(
        str(candidate.get("code") or "")
        for candidates in (result.get("account_candidates") or {}).values()
        for candidate in candidates
        if isinstance(candidate, dict) and str(candidate.get("code") or "")
    ) if isinstance(result.get("account_candidates"), dict) else ()
    canonical_line_ids = tuple(profile.get("canonical_line_ids") or ()) or _canonical_line_ids_for_research(result)
    confidence = int(profile.get("research_confidence") or profile.get("confidence") or 0)
    research_evidence = [
        {
            **item,
            "url": str(item.get("source_url") or ""),
            "source_type": str(item.get("source_kind") or "other"),
            "summary_tr": str(item.get("evidence_summary") or item.get("raw_summary") or ""),
            "accepted": bool(item.get("accepted", True)),
        }
        for item in profile.get("research_evidence") or []
        if isinstance(item, dict) and str(item.get("source_url") or "")
    ]
    if not research_evidence:
        research_evidence = [
            {
                "url": str(url),
                "title": "",
                "source_type": "",
                "summary_tr": "",
                "accepted": True,
            }
            for url in profile.get("source_urls") or []
            if str(url)
        ]
    return serialize_semantic_decision_attempt(
        stage="research_evidence_collection",
        canonical_line_ids=canonical_line_ids,
        prompt_version=str(profile.get("prompt_version") or "research-synthesis-v1"),
        provider=str(profile.get("provider") or profile.get("provider_name") or "research_harness"),
        model=str(profile.get("model") or ""),
        candidate_account_codes=candidate_account_codes,
        candidate_counterparty_codes=(),
        validated_response={
            "confidence": confidence,
            "display_name": str(profile.get("display_name") or ""),
            "research_confidence": int(profile.get("research_confidence") or 0),
            "question": str(profile.get("question") or ""),
            "canonical_line_ids": list(canonical_line_ids),
            "conflicts": list(profile.get("conflicts") or []),
            "evidence_gaps": list(profile.get("evidence_gaps") or []),
            "cache_provenance": dict(profile.get("cache_provenance") or {}),
            "authority": "evidence_only",
            "research_evidence": research_evidence,
        },
        validation_errors=(),
        accepted=False,
    )


class _ResearchSynthesisClassifier:
    def __init__(self, base: ProductClassifier, profile: dict[str, Any], prior_result: dict[str, Any]) -> None:
        self.base = base
        self.profile = profile
        self.prior_result = prior_result
        self.policy = getattr(base, "policy", None)

    def classify(
        self,
        raw_line: str,
        *,
        supplier_hint: str = "",
        context: AiClassificationContext | None = None,
    ) -> Any:
        resolved = context or AiClassificationContext()
        prior_attempts = [
            item for item in self.prior_result.get("semantic_attempts") or [] if isinstance(item, dict)
        ]
        staged = replace(
            resolved,
            semantic_stage="research_synthesis",
            research_evidence=tuple(
                item for item in self.profile.get("research_evidence") or [] if isinstance(item, dict)
            ),
            prior_semantic_attempt=dict(prior_attempts[-1]) if prior_attempts else {},
            validation_errors=(),
        )
        return self.base.classify(raw_line, supplier_hint=supplier_hint, context=staged)


def _merge_ai_result_history(
    rebuilt: dict[str, Any],
    original: dict[str, Any],
    *,
    appended_attempts: tuple[dict[str, Any], ...] = (),
    accepted_attempt_id: str | None = None,
) -> dict[str, Any]:
    merged = {**original, **rebuilt}
    merged.update({key: value for key, value in original.items() if key.startswith("ai_")})
    merged = merge_semantic_attempt_result(
        merged,
        previous_result=original,
        appended_attempts=appended_attempts,
        accepted_attempt_id=accepted_attempt_id,
    )
    accepted_id = str(merged.get("accepted_semantic_attempt_id") or "")
    merged["accepted_semantic_stage"] = next(
        (
            str(item.get("stage") or "")
            for item in merged.get("semantic_attempts") or []
            if isinstance(item, dict) and str(item.get("attempt_id") or "") == accepted_id
        ),
        "",
    )
    return _with_review_summary(merged)


def _rebuild_result_with_research(
    result: dict[str, Any],
    *,
    document: dict[str, Any],
    job: dict[str, Any],
    workspace: dict[str, Any],
    profile: dict[str, Any],
    product_classifier: ProductClassifier | None = None,
    canonical_extraction_provider: object | None = None,
    canonical_extraction_policy: CanonicalExtractionPolicy | None = None,
) -> dict[str, Any]:
    evidence_only = dict(result)
    evidence_only["research_evidence"] = list(profile.get("research_evidence") or [])
    evidence_only["research_evidence_gaps"] = list(profile.get("evidence_gaps") or [])
    if not profile.get("canonical_line_ids") or not evidence_only["research_evidence"]:
        return _merge_ai_result_history(evidence_only, result)
    accepted_initial_authority = any(
        isinstance(item, dict)
        and item.get("accepted") is True
        and not str(item.get("superseded_by_attempt_id") or "")
        for item in result.get("semantic_attempts") or []
    )
    if product_classifier is None or accepted_initial_authority:
        research_attempt = _research_semantic_attempt(evidence_only, profile)
        return _merge_ai_result_history(
            evidence_only,
            result,
            appended_attempts=(research_attempt,),
        )
    rebuilt = build_processing_result(
        document,
        job,
        workspace,
        product_classifier=_ResearchSynthesisClassifier(product_classifier, profile, result),
        canonical_extraction_provider=canonical_extraction_provider,
        canonical_extraction_policy=canonical_extraction_policy,
    )
    return _merge_ai_result_history(
        {**rebuilt, "research_evidence": evidence_only["research_evidence"], "research_evidence_gaps": evidence_only["research_evidence_gaps"]},
        result,
        appended_attempts=tuple(rebuilt.get("semantic_attempts") or ()),
        accepted_attempt_id=str(rebuilt.get("accepted_semantic_attempt_id") or ""),
    )


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
    try:
        parsed_lines = parse_statement_file(path)
    except Exception as exc:
        raise DocumentParseError(str(exc)) from exc
    lines = enrich_statement_lines_with_counterparties(
        parsed_lines,
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


class DocumentParseError(RuntimeError):
    """Raised only when source-document parsing itself fails."""


class RetryableDocumentTechnicalError(DocumentParseError):
    """A missing/transient direct-PDF prerequisite that should be retried."""


def is_transient_persistence_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


def _gemini_pdf_v2_eligible(
    document: dict[str, Any],
    job: dict[str, Any],
) -> bool:
    document_type = str(
        document.get("document_type") or job.get("document_type") or ""
    ).strip()
    path = _stored_path(document)
    return bool(
        gemini_pdf_v2_enabled(environ)
        and document_type == "invoice"
        and path is not None
        and path.suffix.lower() == ".pdf"
    )


def _document_ai_scope(
    store: Any,
    *,
    client_id: str,
    document: dict[str, Any],
) -> dict[str, str]:
    if hasattr(store, "document_ai_artifact_scope"):
        return dict(
            store.document_ai_artifact_scope(
                client_id=client_id,
                document=document,
            )
        )
    document_id = str(
        document.get("normalized_document_id")
        or document.get("document_id")
        or document.get("document_ref")
        or ""
    )
    return {
        "tenant_id": str(
            getattr(store, "tenant_id", "")
            or getattr(store, "tenant_key", "")
            or "default"
        ),
        "taxpayer_id": client_id,
        "document_id": document_id,
        "source_file_id": str(
            document.get("normalized_source_file_id")
            or document.get("source_file_id")
            or document_id
        ),
    }


def _client_tax_id(workspace: dict[str, Any]) -> str:
    profile = (workspace.get("client") or {}).get("profile") or {}
    return str(
        profile.get("tax_id")
        or profile.get("tax_number")
        or profile.get("vkn")
        or profile.get("tckn")
        or ""
    ).strip()


def _run_gemini_pdf_v2_for_worker(
    *,
    store: Any,
    document: dict[str, Any],
    workspace: dict[str, Any],
    client_id: str,
    extraction_provider: object | None,
    accounting_provider: object | None,
    artifact_repository: Any | None,
    max_parallel_accounting_chunks: int = 1,
    candidate_experiment_percent: int | None = None,
    max_accounting_request_bytes: int | None = None,
) -> tuple[dict[str, Any], object]:
    path = _stored_path(document)
    if path is None:
        raise RetryableDocumentTechnicalError("gemini_pdf_v2_source_missing")
    source_bytes = path.read_bytes()
    if not source_bytes.startswith(b"%PDF"):
        raise DocumentParseError("gemini_pdf_v2_source_is_not_pdf")

    provider = extraction_provider or accounting_provider
    if extraction_provider is None or accounting_provider is None:
        runtime = build_gemini_pdf_runtime_from_env(environ)
        if not runtime.available or runtime.provider is None:
            raise RetryableDocumentTechnicalError(
                runtime.unavailable_reason or "gemini_pdf_v2_runtime_unavailable"
            )
        provider = runtime.provider
        max_parallel_accounting_chunks = runtime.max_parallel_accounting_chunks
        candidate_experiment_percent = runtime.candidate_experiment_percent
        max_accounting_request_bytes = runtime.max_accounting_request_bytes
    extraction = extraction_provider or provider
    accounting = accounting_provider or provider
    repository = artifact_repository or getattr(
        store, "document_ai_artifact_repository", None
    )
    if extraction is None or accounting is None:
        raise RetryableDocumentTechnicalError("gemini_pdf_v2_provider_unavailable")
    if repository is None:
        raise RetryableDocumentTechnicalError(
            "gemini_pdf_v2_artifact_repository_unavailable"
        )

    scope = _document_ai_scope(
        store,
        client_id=client_id,
        document=document,
    )
    try:
        effective_experiment_percent = (
            candidate_experiment_percent_from_env(environ)
            if candidate_experiment_percent is None
            else int(candidate_experiment_percent)
        )
        effective_max_request_bytes = (
            max_accounting_request_bytes_from_env(environ)
            if max_accounting_request_bytes is None
            else int(max_accounting_request_bytes)
        )
        assignment = candidate_discovery_assignment(
            taxpayer_id=scope["taxpayer_id"],
            document_id=scope["document_id"],
            experiment_percent=effective_experiment_percent,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise RetryableDocumentTechnicalError(
            "gemini_pdf_v2_candidate_experiment_config_invalid"
        ) from exc
    profile = (workspace.get("client") or {}).get("profile") or {}
    pipeline_result = run_gemini_invoice_pipeline_v2(
        GeminiInvoicePipelineRequest(
            **scope,
            source_file_sha256=sha256(source_bytes).hexdigest(),
            source_bytes=source_bytes,
            workspace=workspace,
            tenant_tax_id=_client_tax_id(workspace),
            chart_revision=_chart_candidate_revision(workspace),
            client_context={
                "activity_description": str(
                    profile.get("activity_description") or ""
                ),
                "nace_code": str(profile.get("nace_code") or ""),
                "activity_tags": list(profile.get("activity_tags") or []),
            },
            max_parallel_accounting_chunks=max_parallel_accounting_chunks,
            candidate_discovery_mode=assignment.mode,
            candidate_experiment_group=assignment.group,
            candidate_experiment_bucket=assignment.bucket,
            candidate_experiment_percent=assignment.experiment_percent,
            max_accounting_request_bytes=effective_max_request_bytes,
        ),
        extraction_provider=extraction,
        accounting_provider=accounting,
        artifact_repository=repository,
    )
    if pipeline_result.canonical_invoice is None:
        warning = next(iter(pipeline_result.warnings), "document_extraction_failed")
        raise RetryableDocumentTechnicalError(f"gemini_pdf_v2:{warning}")
    result = dict(to_document_processing_payload(pipeline_result))
    result["gemini_pdf_v2_used"] = True
    result["pipeline_version"] = pipeline_result.extraction_identity.pipeline_version
    result["ai_classification_used"] = True
    result["ai_classification_provider"] = str(
        getattr(provider, "provider_name", "gemini") or "gemini"
    )
    result["document_ai_artifact_ids"] = [
        item.artifact_id for item in pipeline_result.artifacts
    ]
    return result, provider


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _artifact_scope(
    *,
    tenant_id: str,
    taxpayer_id: str,
    document: dict[str, Any],
    source_sha256: str,
) -> dict[str, str]:
    document_id = str(
        document.get("normalized_document_id")
        or document.get("document_id")
        or document.get("document_ref")
        or ""
    )
    return {
        "tenant_id": tenant_id,
        "taxpayer_id": taxpayer_id,
        "document_id": document_id,
        "source_file_id": str(
            document.get("normalized_source_file_id")
            or document.get("source_file_id")
            or document_id
        ),
        "source_file_sha256": source_sha256,
        "pipeline_version": "gemini-two-stage-v1",
    }


def _append_attempt_receipt(
    repository: Any,
    *,
    scope: dict[str, str],
    stage: str,
    attempt: Any,
    retry_of_artifact_id: str | None = None,
    expanded_from_receipt_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    return repository.append(
        ArtifactWrite(
            **scope,
            kind=ArtifactKind.PROVIDER_RECEIPT,
            stage=stage,
            status=str(getattr(attempt, "status", "failed") or "failed"),
            credential_slot=str(getattr(attempt, "credential_slot", "") or ""),
            provider=str(getattr(attempt, "provider", "gemini") or "gemini"),
            model_alias=str(getattr(attempt, "model_alias", "") or ""),
            resolved_model=str(getattr(attempt, "resolved_model", "") or ""),
            prompt_version=(
                "invoice-facts-v1" if stage == "document_extraction" else "accounting-selection-v1"
            ),
            schema_version=(
                "canonical-invoice-v1" if stage == "document_extraction" else "accounting-proposal-v1"
            ),
            elapsed_ms=int(getattr(attempt, "elapsed_ms", 0) or 0),
            http_status=getattr(attempt, "http_status", None),
            started_at=getattr(attempt, "started_at", None),
            finished_at=getattr(attempt, "finished_at", None),
            token_usage=dict(getattr(attempt, "token_usage", {}) or {}),
            error_metadata=dict(getattr(attempt, "error_metadata", {}) or {}),
            metadata=dict(metadata or {}),
            retry_of_artifact_id=retry_of_artifact_id,
            expanded_from_receipt_id=expanded_from_receipt_id,
        ),
        request_body=bytes(getattr(attempt, "request_body", b"") or b""),
        response_body=bytes(getattr(attempt, "response_body", b"") or b""),
    )


def _latest_failed_stage_receipt(
    repository: Any,
    *,
    tenant_id: str,
    taxpayer_id: str,
    document_id: str,
    stage: str,
    source_file_id: str,
    source_file_sha256: str,
    attempt: Any | None = None,
) -> Any | None:
    receipts = repository.list_for_document(
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        document_id=document_id,
        kind=ArtifactKind.PROVIDER_RECEIPT,
    )
    return next(
        (
            item
            for item in reversed(receipts)
            if item.stage == stage and item.status == "failed"
            and item.source_file_id == source_file_id
            and item.source_file_sha256 == source_file_sha256
            and item.pipeline_version == "gemini-two-stage-v1"
            and item.prompt_version == (
                "invoice-facts-v1" if stage == "document_extraction" else "accounting-selection-v1"
            )
            and item.schema_version == (
                "canonical-invoice-v1" if stage == "document_extraction" else "accounting-proposal-v1"
            )
            and (
                attempt is None
                or (
                    item.provider == str(getattr(attempt, "provider", "") or "")
                    and item.model_alias == str(getattr(attempt, "model_alias", "") or "")
                    and item.resolved_model == str(getattr(attempt, "resolved_model", "") or "")
                )
            )
        ),
        None,
    )


def _load_previous_result_snapshot(
    repository: Any,
    *,
    tenant_id: str,
    taxpayer_id: str,
    document_id: str,
    source_file_id: str,
    source_file_sha256: str,
    chart_candidate_revision: str,
) -> dict[str, Any] | None:
    proposals = repository.list_for_document(
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        document_id=document_id,
        kind=ArtifactKind.ACCOUNTING_PROPOSAL,
    )
    proposal = next(
        (
            item for item in reversed(proposals)
            if item.status in {"successful", "partial"}
            and item.source_file_id == source_file_id
            and item.source_file_sha256 == source_file_sha256
            and item.pipeline_version == "gemini-two-stage-v1"
            and str(item.metadata.get("chart_candidate_revision") or "")
            == chart_candidate_revision
        ),
        None,
    )
    if proposal is None:
        return None
    payload = json.loads(
        repository.read_content(
            tenant_id=tenant_id,
            taxpayer_id=taxpayer_id,
            artifact_id=proposal.artifact_id,
        ).decode("utf-8")
    )
    snapshot = payload.get("result_snapshot") if isinstance(payload, dict) else None
    return dict(snapshot) if isinstance(snapshot, dict) else None


def _chart_candidate_revision(workspace: dict[str, Any]) -> str:
    chart = workspace.get("chart_accounts") if isinstance(workspace.get("chart_accounts"), dict) else {}
    explicit = str(chart.get("revision") or chart.get("updated_at") or "")
    accounts = [
        {
            "code": str(item.get("normalized_account_code") or item.get("raw_account_code") or ""),
            "name": str(item.get("account_name") or ""),
            "tax_id": str(item.get("tax_id") or ""),
            "active": bool(item.get("is_active", True)),
            "detail": bool(item.get("is_detail_account", True)),
        }
        for item in chart.get("accounts") or []
        if isinstance(item, dict)
    ]
    payload = {"explicit_revision": explicit, "accounts": sorted(accounts, key=lambda item: item["code"])}
    return sha256(_json_bytes(payload)).hexdigest()


def _tenant_account_candidates(
    workspace: dict[str, Any],
    *,
    projection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    accounts = (workspace.get("chart_accounts") or {}).get("accounts") or []
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for account in accounts:
        if not isinstance(account, dict) or account.get("is_detail_account", True) is False:
            continue
        code = str(
            account.get("normalized_account_code") or account.get("raw_account_code") or ""
        ).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        candidate = {
                "candidate_id": code,
                "code": code,
                "name": str(account.get("account_name") or ""),
                "tax_id": str(account.get("tax_id") or ""),
                "tax_office": str(account.get("tax_office") or ""),
                "family": code.split(".")[0],
                "is_detail_account": True,
                "is_active": True,
                "origin_round": 0,
            }
        candidate["roles"] = _candidate_roles(candidate, projection or {})
        candidates.append(candidate)
    return candidates


def _candidate_roles(
    candidate: dict[str, Any],
    projection: dict[str, Any],
) -> list[str]:
    code = str(candidate.get("code") or "")
    text = _search_key(f"{code} {candidate.get('name', '')}")
    direction = str(projection.get("document_direction") or "purchase")
    party = projection.get("customer_party") if direction == "sales" else projection.get("supplier_party")
    party = party if isinstance(party, dict) else {}
    roles: list[str] = []
    if (
        str(candidate.get("tax_id") or "")
        and str(candidate.get("tax_id") or "") == str(party.get("tax_id") or "")
    ) or any(
        token and token in text
        for token in _search_key(party.get("title")).split()
        if len(token) >= 4
    ):
        roles.append("counterparty")
    if direction == "sales":
        if code.startswith("6") or "satis" in text or "gelir" in text:
            roles.append("line_revenue")
        if code.startswith("391") or "hesaplanan kdv" in text:
            roles.append("vat")
        if code.startswith("120"):
            roles.append("counterparty")
    else:
        if code.startswith(("15", "25", "7", "689")) or any(
            token in text for token in ("gider", "maliyet", "demirbas")
        ):
            roles.append("line_expense")
        if code.startswith("191") or "indirilecek kdv" in text:
            roles.append("vat")
        if code.startswith("320"):
            roles.append("counterparty")
    tax_text = " ".join(
        _search_key(
            f"{item.get('component_type', '')} {item.get('source_label', '')} "
            f"{item.get('source_code', '')} {item.get('canonical_tax_kind', '')}"
        )
        for item in projection.get("tax_components") or []
        if isinstance(item, dict)
    )
    if tax_text and (
        code.startswith("360")
        or any(token in text for token in tax_text.split() if len(token) >= 3)
        or any(token in tax_text for token in text.split() if len(token) >= 4)
    ):
        roles.append("special_tax")
    return list(dict.fromkeys(roles))


def _initial_candidate_ids(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[str, ...]:
    role_order = ("counterparty", "line_expense", "line_revenue", "vat", "special_tax")
    ranked = sorted(
        candidates,
        key=lambda item: (
            min(
                (role_order.index(role) for role in item.get("roles") or [] if role in role_order),
                default=len(role_order),
            ),
            -(
                3 if str(item.get("code") or "").startswith("770")
                else 2 if str(item.get("code") or "").startswith(("600", "191", "391", "320", "120", "360"))
                else 1 if str(item.get("code") or "").startswith(("15", "25", "7"))
                else 0
            ),
            str(item.get("code") or ""),
        ),
    )
    selected: list[str] = []
    for role in role_order:
        match = next(
            (
                item
                for item in ranked
                if role in (item.get("roles") or [])
                and str(item["candidate_id"]) not in selected
            ),
            None,
        )
        if match is not None:
            selected.append(str(match["candidate_id"]))
        if len(selected) >= max(limit, 0):
            return tuple(selected)
    for item in ranked:
        candidate_id = str(item["candidate_id"])
        if candidate_id not in selected:
            selected.append(candidate_id)
        if len(selected) >= max(limit, 0):
            break
    return tuple(selected)


def _search_key(value: object) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(
        "".join(character for character in folded if not unicodedata.combining(character))
        .casefold()
        .split()
    )


def _expanded_candidate_ids(
    all_candidates: list[dict[str, Any]],
    *,
    accumulated_ids: tuple[str, ...],
    search_terms: tuple[str, ...],
    limit: int,
) -> tuple[str, ...]:
    sent = set(accumulated_ids)
    terms = tuple(_search_key(term) for term in search_terms if _search_key(term))
    matches = [
        str(candidate["candidate_id"])
        for candidate in all_candidates
        if str(candidate["candidate_id"]) not in sent
        and terms
        and any(
            term in _search_key(f"{candidate.get('code', '')} {candidate.get('name', '')}")
            for term in terms
        )
    ]
    if not matches:
        matches = [
            str(candidate["candidate_id"])
            for candidate in sorted(all_candidates, key=lambda item: str(item.get("code") or ""))
            if str(candidate["candidate_id"]) not in sent
        ]
    return tuple(matches[: max(limit, 0)])


def _new_counterparty_proposal(payload: object) -> NewCounterpartyProposal | None:
    raw = payload if isinstance(payload, dict) else {}
    if not raw:
        return None
    return NewCounterpartyProposal(
        party_title=str(raw.get("party_title") or ""),
        tax_id=str(raw.get("tax_id") or ""),
        direction=str(raw.get("direction") or ""),
        suggested_parent_family=str(raw.get("suggested_parent_family") or ""),
    )


def _full_accounting_proposal(payload: object) -> AccountingProposal:
    raw = payload if isinstance(payload, dict) else {}
    counterparty = raw.get("counterparty_account")
    counterparty_account = (
        SelectedAccount(
            selected_candidate_id=str(counterparty.get("selected_candidate_id") or ""),
            reason=str(counterparty.get("reason") or ""),
        )
        if isinstance(counterparty, dict) and counterparty.get("selected_candidate_id")
        else None
    )
    return AccountingProposal(
        counterparty_account=counterparty_account,
        line_accounts=tuple(
            LineAccountSelection(
                line_ref=str(item.get("line_ref") or ""),
                selected_candidate_id=str(item.get("selected_candidate_id") or ""),
                reason=str(item.get("reason") or ""),
            )
            for item in raw.get("line_accounts") or []
            if isinstance(item, dict) and item.get("selected_candidate_id")
        ),
        vat_accounts=tuple(
            VatAccountSelection(
                vat_ref=str(item.get("vat_ref") or ""),
                rate=str(item.get("rate") or ""),
                selected_candidate_id=str(item.get("selected_candidate_id") or ""),
                reason=str(item.get("reason") or ""),
            )
            for item in raw.get("vat_accounts") or []
            if isinstance(item, dict) and item.get("selected_candidate_id")
        ),
        special_tax_accounts=tuple(
            SpecialTaxAccountSelection(
                tax_ref=str(item.get("tax_ref") or ""),
                component_type=str(item.get("component_type") or ""),
                selected_candidate_id=str(item.get("selected_candidate_id") or ""),
                reason=str(item.get("reason") or ""),
            )
            for item in raw.get("special_tax_accounts") or []
            if isinstance(item, dict) and item.get("selected_candidate_id")
        ),
        new_counterparty_proposal=_new_counterparty_proposal(
            raw.get("new_counterparty_proposal")
        ),
    )


def _candidate_decision(payload: dict[str, Any]) -> object:
    action = str(payload.get("action") or "").strip()
    if "proposal" in payload:
        proposal = _full_accounting_proposal(payload.get("proposal"))
        if action == "request_more_candidates":
            request = payload.get("request_more_candidates")
            request = request if isinstance(request, dict) else {}
            return RequestMoreCandidatesDecision(
                search_terms=tuple(str(term) for term in request.get("search_terms") or () if str(term)),
                requested_scope=str(request.get("requested_scope") or "broader_chart_slice"),
                reason=str(request.get("reason") or payload.get("reason") or ""),
                provisional_proposal=proposal,
            )
        return FinalizeProposalDecision(
            proposal=proposal,
            reason=str(payload.get("reason") or ""),
        )
    selected = str(payload.get("selected_candidate_id") or "").strip() or None
    reason = str(payload.get("reason") or "")
    if action == "select_existing":
        return SelectExistingDecision(selected_candidate_id=selected or "", reason=reason)
    if action == "propose_new":
        raw = payload.get("new_counterparty_proposal")
        proposal = raw if isinstance(raw, dict) else {}
        return ProposeNewDecision(
            proposal=NewCounterpartyProposal(
                party_title=str(proposal.get("party_title") or ""),
                tax_id=str(proposal.get("tax_id") or ""),
                direction=str(proposal.get("direction") or ""),
                suggested_parent_family=str(proposal.get("suggested_parent_family") or ""),
            ),
            reason=reason,
        )
    request = payload.get("request_more_candidates")
    request = request if isinstance(request, dict) else {}
    return RequestMoreCandidatesDecision(
        search_terms=tuple(str(term) for term in request.get("search_terms") or () if str(term)),
        requested_scope=str(request.get("requested_scope") or "broader_chart_slice"),
        reason=str(request.get("reason") or reason),
        provisional_candidate_id=selected,
    )


def _accounting_proposal_payload(session: AccountingCandidateSession) -> dict[str, Any]:
    full_proposal = session.final_proposal or session.provisional_proposal
    legacy_proposal = session.new_counterparty_proposal
    return {
        "action": session.final_action or "unresolved",
        "proposal": asdict(full_proposal) if full_proposal is not None else None,
        "selected_candidate_id": session.selected_candidate_id,
        "new_counterparty_proposal": (
            asdict(full_proposal.new_counterparty_proposal)
            if full_proposal is not None and full_proposal.new_counterparty_proposal is not None
            else asdict(legacy_proposal) if legacy_proposal is not None else None
        ),
        "accounting_call_count": session.accounting_call_count,
        "expansion_count": session.expansion_count,
        "selection_origin_round": min(
            (
                session.selection_origin_round(candidate_id)
                for candidate_id in (
                    full_proposal.selected_candidate_ids if full_proposal is not None else ()
                )
                if session.selection_origin_round(candidate_id) is not None
            ),
            default=(
                session.selection_origin_round(session.selected_candidate_id)
                if session.selected_candidate_id
                else None
            ),
        ),
        "warnings": list(session.warnings),
        "candidate_rounds": [
            {
                "round_index": item.round_index,
                "candidate_ids": list(item.candidate_ids),
                "decision": asdict(item.decision) if item.decision is not None else None,
            }
            for item in session.rounds
        ],
    }


def _money(value: object) -> str:
    try:
        return str(Decimal(str(value or "0")).quantize(Decimal("0.01")))
    except Exception:
        return "0.00"


def _build_accounting_proposal_result(
    canonical: Any,
    *,
    proposal: dict[str, Any],
    warnings: list[str],
    account_names: dict[str, str],
) -> dict[str, Any]:
    full = proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}
    direction = str(canonical.header.document_direction or "purchase")
    is_sales = direction == "sales"
    line_choices = {
        str(item.get("line_ref") or ""): item
        for item in full.get("line_accounts") or []
        if isinstance(item, dict)
    }
    vat_choices = {
        str(item.get("vat_ref") or ""): item
        for item in full.get("vat_accounts") or []
        if isinstance(item, dict)
    }
    tax_choices = {
        str(item.get("tax_ref") or ""): item
        for item in full.get("special_tax_accounts") or []
        if isinstance(item, dict)
    }
    legacy_selected = str(proposal.get("selected_candidate_id") or "")
    draft_lines: list[dict[str, Any]] = []
    selected_lines: list[str] = []
    for line in canonical.line_items:
        choice = line_choices.get(line.canonical_line_id, {})
        account = str(choice.get("selected_candidate_id") or legacy_selected)
        if account:
            selected_lines.append(account)
        else:
            account = f"UNRESOLVED:line:{line.canonical_line_id}"
            warnings.append(f"account_selection_unresolved:line:{line.canonical_line_id}")
        amount = _money(line.taxable_amount)
        draft_lines.append({
            "proposal_role": "canonical_line",
            "line_ref": line.canonical_line_id,
            "account_code": account,
            "description": line.description,
            "debit": "0.00" if is_sales else amount,
            "credit": amount if is_sales else "0.00",
            "reason": str(choice.get("reason") or ""),
            "canonical_line_ids": [line.canonical_line_id],
        })
    selected_vat: list[str] = []
    for index, vat in enumerate(canonical.vat_summary):
        vat_ref = vat.vat_group_id or f"vat:{index + 1}:{vat.rate}"
        choice = vat_choices.get(vat_ref, {})
        account = str(choice.get("selected_candidate_id") or "")
        if account:
            selected_vat.append(account)
        else:
            account = f"UNRESOLVED:vat:{vat_ref}"
            warnings.append(f"account_selection_unresolved:vat:{vat_ref}")
        amount = _money(vat.tax_amount)
        draft_lines.append({
            "proposal_role": "vat_group",
            "vat_ref": vat_ref,
            "vat_rate": vat.rate,
            "account_code": account,
            "description": f"KDV %{vat.rate}",
            "debit": "0.00" if is_sales else amount,
            "credit": amount if is_sales else "0.00",
            "reason": str(choice.get("reason") or ""),
            "canonical_line_ids": list(vat.contributing_line_ids),
        })
    selected_special: list[str] = []
    for index, tax in enumerate(canonical.tax_components):
        tax_ref = f"tax:{index + 1}:{tax.component_type}:{tax.source_code or tax.canonical_tax_kind}"
        choice = tax_choices.get(tax_ref, {})
        account = str(choice.get("selected_candidate_id") or "")
        if account:
            selected_special.append(account)
        else:
            account = f"UNRESOLVED:special_tax:{tax_ref}"
            warnings.append(f"account_selection_unresolved:special_tax:{tax_ref}")
        amount = _money(tax.tax_amount)
        draft_lines.append({
            "proposal_role": "special_tax",
            "tax_ref": tax_ref,
            "component_type": tax.component_type,
            "source_code": tax.source_code,
            "account_code": account,
            "description": tax.source_label or tax.canonical_tax_kind,
            "debit": "0.00" if is_sales else amount,
            "credit": amount if is_sales else "0.00",
            "reason": str(choice.get("reason") or ""),
        })
    counterparty_choice = full.get("counterparty_account")
    counterparty_choice = counterparty_choice if isinstance(counterparty_choice, dict) else {}
    counterparty = str(counterparty_choice.get("selected_candidate_id") or "")
    new_counterparty = full.get("new_counterparty_proposal")
    new_counterparty = new_counterparty if isinstance(new_counterparty, dict) else proposal.get("new_counterparty_proposal")
    if not counterparty:
        counterparty = "UNRESOLVED:counterparty"
        warnings.append("account_selection_unresolved:counterparty")
    payable = _money(canonical.totals.payable_total)
    draft_lines.append({
        "proposal_role": "counterparty",
        "account_code": counterparty,
        "description": canonical.customer_party.title if is_sales else canonical.supplier_party.title,
        "debit": payable if is_sales else "0.00",
        "credit": "0.00" if is_sales else payable,
        "reason": str(counterparty_choice.get("reason") or ""),
    })
    first_line = selected_lines[0] if selected_lines else ""
    first_vat = selected_vat[0] if selected_vat else ""
    rationale = "; ".join(
        f"{item.get('account_code')}: {item.get('reason')}"
        for item in draft_lines
        if item.get("reason")
    )
    resolved_counterparty = "" if counterparty.startswith("UNRESOLVED:") else counterparty
    interpretation = rationale or "AI teklifi kismi; cozulmeyen alanlar uyari olarak korundu."
    unresolved = ", ".join(
        dict.fromkeys(
            warning for warning in warnings if "unresolved" in warning or "failed" in warning
        )
    )
    decision_narrative = {
        "read_facts": {
            "invoice_no": canonical.header.invoice_no,
            "issue_date": canonical.header.issue_date,
            "direction": direction,
            "counterparty_title": canonical.customer_party.title if is_sales else canonical.supplier_party.title,
            "counterparty_tax_id": canonical.customer_party.tax_id if is_sales else canonical.supplier_party.tax_id,
            "line_count": str(len(canonical.line_items)),
            "payable_total": canonical.totals.payable_total,
            "vat_total": canonical.totals.vat_total,
            "special_tax_total": canonical.totals.special_tax_total,
        },
        "invoice_product_line": canonical.line_items[0].description if canonical.line_items else "",
        "fisora_interpretation": interpretation,
        "business_relation": (
            f"{direction}: {canonical.customer_party.title if is_sales else canonical.supplier_party.title}"
        ),
        "account_code": first_line,
        "account_name": account_names.get(first_line, ""),
        "counterparty_match": resolved_counterparty or (
            str(new_counterparty.get("party_title") or "") if isinstance(new_counterparty, dict) else ""
        ),
        "confidence_label": "Musavir onayi gereken AI taslagi",
        "unresolved_info": unresolved,
    }
    result: dict[str, Any] = {
        "invoice_no": canonical.header.invoice_no,
        "issue_date": canonical.header.issue_date,
        "invoice_date": canonical.header.issue_date,
        "currency_code": canonical.header.currency_code,
        "invoice_type": canonical.header.invoice_type,
        "accounting_direction": direction,
        "direction_confidence": 100,
        "direction_uncertainty": False,
        "direction_evidence": list(canonical.header.evidence),
        "supplier_title": canonical.supplier_party.title,
        "supplier_tax_id": canonical.supplier_party.tax_id,
        "customer_title": canonical.customer_party.title,
        "customer_tax_id": canonical.customer_party.tax_id,
        "counterparty_title": canonical.customer_party.title if is_sales else canonical.supplier_party.title,
        "counterparty_tax_id": canonical.customer_party.tax_id if is_sales else canonical.supplier_party.tax_id,
        "goods_services_total": canonical.totals.goods_services_total,
        "vat_total": canonical.totals.vat_total,
        "special_tax_total": canonical.totals.special_tax_total,
        "tax_inclusive_total": canonical.totals.tax_inclusive_total,
        "payable_total": canonical.totals.payable_total,
        "vat_rates": [item.rate for item in canonical.vat_summary],
        "canonical_line_count": len(canonical.line_items),
        "canonical_validation_status": canonical.validation.status,
        "canonical_validation_reasons": list(canonical.validation.reason_codes),
        "canonical_extraction_ai_used": True,
        "canonical_invoice": asdict(canonical),
        "draft_lines": draft_lines,
        "selected_expense_account": "" if is_sales else first_line,
        "selected_revenue_account": first_line if is_sales else "",
        "selected_purchase_vat_account": "" if is_sales else first_vat,
        "selected_sales_vat_account": first_vat if is_sales else "",
        "selected_vat_account": first_vat,
        "selected_supplier_account": "" if is_sales else resolved_counterparty,
        "selected_customer_account": resolved_counterparty if is_sales else "",
        "counterparty_match_code": resolved_counterparty,
        "selected_special_tax_accounts": selected_special,
        "decision_narrative": decision_narrative,
        "accountant_summary": rationale or "Belge olgularindan en iyi kullanilabilir taslak uretildi.",
        "accountant_explanation_tr": rationale or "Eksik hesap secimleri taslagi durdurmadan isaretlendi.",
        "counterparty_creation_suggestion": new_counterparty,
        "suggested_counterparty_creation": new_counterparty,
        "draft_status": "review_required",
        "export_status": "review_required",
        "accounting_proposal": proposal,
    }
    result["pipeline_warnings"] = list(dict.fromkeys(warnings))
    for key in ("risk_flags", "parse_notes", "review_reason_codes"):
        result[key] = list(dict.fromkeys(warnings))
    result = _with_review_summary(result)
    result["primary_suggestion"] = {
        "direction": direction,
        "counterparty_account": resolved_counterparty,
        "account": first_line,
        "vat_account": first_vat,
        "special_tax_accounts": selected_special,
        "draft_lines": draft_lines,
        "reason": decision_narrative["fisora_interpretation"],
        "export_gate_reason": "accountant_approval_required",
    }
    return result


def run_gemini_two_stage_invoice_workflow(
    *,
    document: dict[str, Any],
    job: dict[str, Any],
    workspace: dict[str, Any],
    tenant_id: str,
    taxpayer_id: str,
    extraction_provider: object,
    accounting_provider: object,
    artifact_repository: Any,
    initial_candidate_limit: int = 40,
    expansion_candidate_limit: int = 40,
) -> dict[str, Any]:
    """Run the V1 direct-PDF -> facts -> compact accounting pipeline."""

    path = _stored_path(document)
    if path is None:
        raise DocumentParseError("source PDF is unavailable")
    source_bytes = path.read_bytes()
    source_sha = sha256(source_bytes).hexdigest()
    scope = _artifact_scope(
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        document=document,
        source_sha256=source_sha,
    )
    chart_candidate_revision = _chart_candidate_revision(workspace)
    try:
        extraction_result = extraction_provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="",
                document_bytes=source_bytes,
                document_mime_type="application/pdf",
                deterministic_payload={},
                client_identity=_canonical_client_identity(workspace),
                max_input_chars=0,
                mode="discovery",
            )
        )
    except Exception as exc:
        attempt = getattr(exc, "attempt", None)
        if attempt is not None:
            prior_extraction = _latest_failed_stage_receipt(
                artifact_repository,
                tenant_id=tenant_id,
                taxpayer_id=taxpayer_id,
                document_id=scope["document_id"],
                stage="document_extraction",
                source_file_id=scope["source_file_id"],
                source_file_sha256=scope["source_file_sha256"],
                attempt=attempt,
            )
            _append_attempt_receipt(
                artifact_repository,
                scope=scope,
                stage="document_extraction",
                attempt=attempt,
                retry_of_artifact_id=(
                    prior_extraction.artifact_id if prior_extraction is not None else None
                ),
                metadata={"chart_candidate_revision": chart_candidate_revision},
            )
        previous = _load_previous_result_snapshot(
            artifact_repository,
            tenant_id=tenant_id,
            taxpayer_id=taxpayer_id,
            document_id=scope["document_id"],
            source_file_id=scope["source_file_id"],
            source_file_sha256=scope["source_file_sha256"],
            chart_candidate_revision=chart_candidate_revision,
        )
        if previous is not None:
            warnings = list(previous.get("pipeline_warnings") or [])
            warnings.append("document_extraction_retry_failed")
            previous["pipeline_warnings"] = list(dict.fromkeys(warnings))
            return previous
        raise DocumentParseError(str(exc)) from exc

    extraction_attempt = getattr(extraction_result, "attempt", None)
    if extraction_attempt is None:
        raise DocumentParseError("Gemini extraction result has no provider receipt")
    prior_extraction = _latest_failed_stage_receipt(
        artifact_repository,
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        document_id=scope["document_id"],
        stage="document_extraction",
        source_file_id=scope["source_file_id"],
        source_file_sha256=scope["source_file_sha256"],
        attempt=extraction_attempt,
    )
    extraction_receipt = _append_attempt_receipt(
        artifact_repository,
        scope=scope,
        stage="document_extraction",
        attempt=extraction_attempt,
        retry_of_artifact_id=(
            prior_extraction.artifact_id if prior_extraction is not None else None
        ),
        metadata={"chart_candidate_revision": chart_candidate_revision},
    )
    canonical = canonical_invoice_from_ai_payload(extraction_result)
    canonical_artifact = artifact_repository.append(
        ArtifactWrite(
            **scope,
            kind=ArtifactKind.CANONICAL_INVOICE_FORM,
            stage="canonical_mapping",
            status="successful",
            parent_artifact_id=extraction_receipt.artifact_id,
            provider_receipt_artifact_id=extraction_receipt.artifact_id,
            mapper_version="canonical-invoice-mapper-v1",
        ),
        content=_json_bytes(asdict(canonical)),
    )
    profile = (workspace.get("client") or {}).get("profile") or {}
    projection = build_accounting_projection(
        canonical,
        client_context={
            "activity_description": str(profile.get("activity_description") or ""),
            "nace_code": str(profile.get("nace_code") or ""),
            "activity_tags": list(profile.get("activity_tags") or []),
        },
    )
    for index, vat in enumerate(projection.get("vat_summary") or []):
        if isinstance(vat, dict):
            vat["vat_ref"] = str(vat.get("vat_group_id") or f"vat:{index + 1}:{vat.get('rate', '')}")
    for index, tax in enumerate(projection.get("tax_components") or []):
        if isinstance(tax, dict):
            tax["tax_ref"] = (
                f"tax:{index + 1}:{tax.get('component_type', '')}:"
                f"{tax.get('source_code') or tax.get('canonical_tax_kind') or ''}"
            )
    projection_artifact = artifact_repository.append(
        ArtifactWrite(
            **scope,
            kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
            stage="accounting_projection",
            status="successful",
            parent_artifact_id=canonical_artifact.artifact_id,
            mapper_version="accounting-projection-v1",
        ),
        content=_json_bytes(projection),
    )

    all_candidates = _tenant_account_candidates(workspace, projection=projection)
    tenant_candidate_ids = tuple(str(item["candidate_id"]) for item in all_candidates)
    initial_ids = _initial_candidate_ids(all_candidates, limit=initial_candidate_limit)
    session = AccountingCandidateSession.start(
        tenant_candidate_ids=tenant_candidate_ids,
        initial_candidate_ids=initial_ids,
    )
    previous_accounting_receipt = None
    authoritative_accounting_receipt = None
    warnings = list(canonical.extraction_notes)
    last_accounting_receipt = None
    proposal_status = "successful"
    while session.final_action is None:
        current = set(session.current_candidate_ids)
        details = tuple(
            {
                **candidate,
                "origin_round": session.selection_origin_round(str(candidate["candidate_id"])) or 0,
            }
            for candidate in all_candidates
            if str(candidate["candidate_id"]) in current
        )
        request = AccountingSelectionRequest(
            accounting_projection=projection,
            candidate_details=details,
            round_index=session.accounting_call_count - 1,
            prior_rounds=tuple(
                {
                    "round_index": item.round_index,
                    "candidate_ids": list(item.candidate_ids),
                    "decision": asdict(item.decision) if item.decision is not None else None,
                }
                for item in session.rounds[:-1]
            ),
        )
        try:
            accounting_result = accounting_provider.classify_product(request)
        except Exception as exc:
            attempt = getattr(exc, "attempt", None)
            if attempt is not None:
                last_accounting_receipt = _append_attempt_receipt(
                    artifact_repository,
                    scope=scope,
                    stage="accounting_selection",
                    attempt=attempt,
                    expanded_from_receipt_id=(
                        previous_accounting_receipt.artifact_id
                        if previous_accounting_receipt is not None
                        else None
                    ),
                    metadata={
                        "chart_candidate_revision": chart_candidate_revision,
                        "candidate_revision": sha256(_json_bytes(details)).hexdigest(),
                    },
                )
            warnings.append("accounting_provider_failed")
            warnings.append(f"accounting_provider_warning:{type(exc).__name__}")
            session = session.terminalize_best_available("accounting_provider_failed")
            proposal_status = "partial"
            break
        attempt = getattr(accounting_result, "attempt", None)
        if attempt is None:
            warnings.append("accounting_receipt_missing")
            session = session.terminalize_best_available("accounting_receipt_missing")
            proposal_status = "partial"
            break
        last_accounting_receipt = _append_attempt_receipt(
            artifact_repository,
            scope=scope,
            stage="accounting_selection",
            attempt=attempt,
            expanded_from_receipt_id=(
                previous_accounting_receipt.artifact_id
                if previous_accounting_receipt is not None
                else None
            ),
            metadata={
                "chart_candidate_revision": chart_candidate_revision,
                "candidate_revision": sha256(_json_bytes(details)).hexdigest(),
            },
        )
        previous_accounting_receipt = last_accounting_receipt
        authoritative_accounting_receipt = last_accounting_receipt
        decision = _candidate_decision(dict(accounting_result))
        try:
            session = session.record_decision(decision)  # type: ignore[arg-type]
        except CandidateIntegrityError:
            warnings.append("accounting_candidate_integrity_warning")
            session = session.terminalize_best_available(
                "accounting_candidate_integrity_warning"
            )
            proposal_status = "partial"
            break
        if session.final_action is not None:
            break
        expansion = session.pending_expansion_request
        if expansion is None:
            warnings.append("candidate_expansion_request_missing")
            break
        expansion_ids = _expanded_candidate_ids(
            all_candidates,
            accumulated_ids=session.accumulated_candidate_ids,
            search_terms=expansion.search_terms,
            limit=expansion_candidate_limit,
        )
        session = session.add_expansion_candidates(expansion_ids)

    warnings.extend(session.warnings)
    proposal = _accounting_proposal_payload(session)
    result = _build_accounting_proposal_result(
        canonical,
        proposal=proposal,
        warnings=warnings,
        account_names={
            str(candidate["candidate_id"]): str(candidate.get("name") or "")
            for candidate in all_candidates
        },
    )
    if authoritative_accounting_receipt is None:
        # No provider response means no typed proposal artifact. The usable
        # draft is still returned with warnings rather than discarded.
        return result
    proposal_artifact_id = str(uuid4())
    result["document_ai_artifacts"] = {
        "extraction_receipt_id": extraction_receipt.artifact_id,
        "canonical_invoice_form_id": canonical_artifact.artifact_id,
        "accounting_input_projection_id": projection_artifact.artifact_id,
        "accounting_proposal_id": proposal_artifact_id,
    }
    proposal_artifact = artifact_repository.append(
        ArtifactWrite(
            **scope,
            kind=ArtifactKind.ACCOUNTING_PROPOSAL,
            stage="accounting_proposal",
            status=proposal_status,
            artifact_id=proposal_artifact_id,
            parent_artifact_id=projection_artifact.artifact_id,
            provider_receipt_artifact_id=authoritative_accounting_receipt.artifact_id,
            mapper_version="accounting-proposal-v1",
            metadata={
                "accounting_call_count": session.accounting_call_count,
                "expansion_count": session.expansion_count,
                "chart_candidate_revision": chart_candidate_revision,
                "candidate_revision": sha256(
                    _json_bytes(session.accumulated_candidate_ids)
                ).hexdigest(),
            },
        ),
        content=_json_bytes({"proposal": proposal, "result_snapshot": result}),
    )
    if proposal_artifact.artifact_id != proposal_artifact_id:
        raise RuntimeError("accounting proposal artifact identity changed during append")
    return result


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
    try:
        invoice = _parse_invoice_document(
            path,
            document_type,
            canonical_extraction_provider=canonical_extraction_provider,
            canonical_extraction_policy=canonical_extraction_policy,
            client_identity=_canonical_client_identity(workspace),
        )
    except Exception as exc:
        raise DocumentParseError(str(exc)) from exc
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
        intended_direction=_intake_direction(
            str(document.get("intake_category") or job.get("intake_category") or "")
        ),
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
    extraction_provider: object | None = None,
    accounting_provider: object | None = None,
    artifact_repository: Any | None = None,
    max_parallel_accounting_chunks: int = 1,
    candidate_experiment_percent: int | None = None,
    max_accounting_request_bytes: int | None = None,
    tenant_id: str = "",
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
    failure_stage = "parse"
    gemini_pdf_v2_selected = False

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
        gemini_pdf_v2_selected = _gemini_pdf_v2_eligible(document, job)
        workspace = _workspace_with_nace_research(workspace, store)
        parse_start = time.perf_counter()
        failure_stage = "processing"
        runtime: dict[str, Any] = {}
        if gemini_pdf_v2_selected:
            pipeline_event(
                "gemini_pdf_v2_selected",
                "ok",
                "Gemini native-PDF V2 belge akisi secildi.",
                "gemini_pdf_v2_selected",
                {"parser_fallback": False},
            )
            result, v2_provider = _run_gemini_pdf_v2_for_worker(
                store=store,
                document=document,
                workspace=workspace,
                client_id=client_id,
                extraction_provider=extraction_provider,
                accounting_provider=accounting_provider,
                artifact_repository=artifact_repository,
                max_parallel_accounting_chunks=max_parallel_accounting_chunks,
                candidate_experiment_percent=candidate_experiment_percent,
                max_accounting_request_bytes=max_accounting_request_bytes,
            )
            selected_provider = str(
                getattr(v2_provider, "provider_name", "gemini") or "gemini"
            )
            parse_ms = _duration_ms(parse_start)
            ai_ms = parse_ms
            _record_ai_capacity_snapshot(store, v2_provider)
        else:
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
            selected_provider = str(
                getattr(
                    getattr(runtime["product_classifier"], "provider", None),
                    "provider_name",
                    "",
                )
            )
            result = build_processing_result(
                document,
                job,
                workspace,
                product_classifier=runtime["product_classifier"],
                canonical_extraction_provider=runtime.get(
                    "canonical_extraction_provider"
                ),
                canonical_extraction_policy=runtime.get(
                    "canonical_extraction_policy"
                ),
                statement_ai_provider=runtime["statement_ai_provider"],
                statement_ai_policy=runtime["statement_ai_policy"],
            )
            parse_ms = _duration_ms(parse_start)
            product_provider = getattr(
                runtime["product_classifier"], "provider", None
            )
            if str(result.get("ai_classification_provider") or "") not in {
                "",
                "static_rules",
            } or bool(result.get("canonical_extraction_ai_used")):
                ai_ms = parse_ms
            _record_ai_capacity_snapshot(store, product_provider)
            _record_ai_capacity_snapshot(store, runtime["statement_ai_provider"])
        if selected_provider:
            pipeline_event(
                "ai_provider_selected",
                "ok",
                f"AI provider secildi: {selected_provider}.",
                "ai_provider_selected",
                {"provider": selected_provider},
            )
        for warning in result.get("pipeline_warnings") or []:
            warning_code = str(warning or "").strip()
            if not warning_code:
                continue
            pipeline_event(
                "pipeline_warning",
                "warning",
                "Belge isleme uyarisi kaydedildi; kullanilabilir sonraki asamalar devam etti.",
                warning_code,
                {"warning": warning_code, "draft_retained": bool(result.get("draft_lines"))},
            )
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
        learning_audit = result.get("learning_audit") if isinstance(result.get("learning_audit"), dict) else {}
        if learning_audit:
            learning_status = str(learning_audit.get("status") or "")
            if learning_status == "applied":
                pipeline_event(
                    "learning_rule_applied",
                    "ok",
                    "Onceki musavir karari benzer belge icin kullanildi.",
                    "learning_rule_applied",
                    learning_audit,
                )
            elif learning_status == "blocked":
                pipeline_event(
                    "learning_rule_blocked",
                    "warning",
                    "Ogrenme kurali bu belgeye uygulanmadi.",
                    "learning_rule_blocked",
                    learning_audit,
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
        if (
            not gemini_pdf_v2_selected
            and effective_research_runtime
            and research_document_type not in {"bank_statement", "pos_statement"}
        ):
            raw_line = _research_candidate_from_result(result, document)
            should_run_research = bool(raw_line and _should_run_research_for_result(result))
            canonical_line_ids = _canonical_line_ids_for_research(result) if should_run_research else ()
            if should_run_research and not canonical_line_ids:
                result = {
                    **result,
                    "research_evidence": [],
                    "research_evidence_gaps": ["line-missing"],
                }
                pipeline_event(
                    "research_scope_missing",
                    "warning",
                    "Canonical fatura satiri bulunmadigi icin arastirma baslatilmadi.",
                    "line-missing",
                    {"evidence_gaps": ["line-missing"]},
                )
            if should_run_research and canonical_line_ids:
                activity_context = str((workspace.get("client") or {}).get("profile", {}).get("activity_description") or "")
                query = sanitize_research_query(
                    kind="brand",
                    raw_line=raw_line,
                    supplier_hint=str(result.get("provider_hint") or ""),
                    activity_context=activity_context,
                    canonical_line_ids=canonical_line_ids,
                )
                cache_key = research_brand_cache_key(query, cache_scope=str(client_id))
                cached = store.get_brand_research_profile(cache_key) if hasattr(store, "get_brand_research_profile") else None
                research_cache_hit = bool(cached and research_profile_is_fresh(cached))
                pipeline_event(
                    "research_cache_hit" if research_cache_hit else "research_started",
                    "ok",
                    "Research cache kullanildi." if research_cache_hit else "Marka/NACE arastirmasi basladi.",
                    "research_cache_hit" if research_cache_hit else "research_started",
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
                    canonical_line_ids=canonical_line_ids,
                    cache_scope=str(client_id),
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
                    product_classifier=runtime.get("product_classifier"),
                    canonical_extraction_provider=runtime.get("canonical_extraction_provider"),
                    canonical_extraction_policy=runtime.get("canonical_extraction_policy"),
                )
                result = apply_research_to_result(result, profile, confidence_threshold=threshold)
                confidence = int(profile.get("research_confidence") or profile.get("confidence") or 0)
                has_accepted_evidence = any(
                    isinstance(item, dict) and item.get("accepted") is True
                    for item in profile.get("research_evidence") or []
                )
                research_ok = confidence >= threshold and has_accepted_evidence
                research_step = (
                    "research_completed"
                    if research_ok
                    else "research_insufficient_evidence"
                    if not has_accepted_evidence
                    else "research_low_confidence"
                )
                pipeline_event(
                    research_step,
                    "ok" if research_ok else "warning",
                    "Arastirma profili hazirlandi."
                    if research_ok
                    else "Arastirma kaniti yetersiz."
                    if not has_accepted_evidence
                    else "Arastirma guveni dusuk; belge kontrolde kaldi.",
                    research_step,
                    {
                        "display_name": str(profile.get("display_name") or ""),
                        "confidence": confidence,
                        "source_urls": list(profile.get("source_urls") or []),
                        "semantic_attempts": list(result.get("semantic_attempts") or []),
                        "accepted_semantic_attempt_id": str(result.get("accepted_semantic_attempt_id") or ""),
                    },
                )
                if "source-rejected" in set(profile.get("evidence_gaps") or []):
                    pipeline_event(
                        "research_source_rejected",
                        "warning",
                        "Arastirma kaynagi kaynak politikasindan gecemedi.",
                        "research_source_rejected",
                        {"source_urls": list(profile.get("source_urls") or [])},
                    )
        result = _with_review_summary(result)
        if attention := _ai_attention_status(result):
            event_step = "ai_correction_required" if attention == "ai_correction_required" else "ai_retry_required"
            pipeline_event(
                event_step,
                "warning",
                (
                    "AI hesap karari tamamlanamadi; duzeltme gerekli."
                    if attention == "ai_correction_required"
                    else "AI ajani mesgul veya karar tamamlanamadi; belge tekrar denenecek."
                ),
                event_step,
                {
                    "reason": str(result.get("ai_retry_reason") or ""),
                    "ai_resolution_status": attention,
                    "ai_attempted_account_code": str(result.get("ai_attempted_account_code") or ""),
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
        failure_stage = "persistence"
        store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
            **(
                {"attempt_id": str(job.get("normalized_attempt_id") or "")}
                if job.get("normalized_attempt_id")
                else {}
            ),
        )
        failure_stage = "processing"
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
        if _ai_attention_status(result) == "ai_retry_required":
            try:
                opened_at = datetime.fromisoformat(str(job.get("created_at") or "").replace("Z", "+00:00"))
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=UTC)
            except ValueError:
                opened_at = datetime.now(UTC)
            retry = next_ai_retry(
                step=max(int(job.get("attempt_count") or 1) - 1, 0),
                opened_at=opened_at,
                now=datetime.now(UTC),
                document_id=document_ref,
            )
            outage_episode_id = ""
            if hasattr(store, "record_ai_outage_failure"):
                evidence = sanitize_provider_failure_evidence(
                    provider_name=str(result.get("ai_classification_provider") or "unknown"),
                    category="timeout" if "timeout" in str(result.get("ai_retry_reason") or "").lower() else "unavailable",
                    attempted_at=datetime.now(UTC),
                )
                episode = store.record_ai_outage_failure(
                    task_kind="invoice_classification",
                    document_id=document_ref,
                    evidence=evidence,
                    now=datetime.now(UTC),
                )
                outage_episode_id = str(episode.get("id") or "")
            store.update_processing_job(
                job_id=str(job["id"]),
                status=retry.status,
                processing_metrics=processing_metrics,
                next_attempt_at=retry.next_attempt_at,
                retry_step=retry.retry_step,
                outage_episode_id=outage_episode_id or None,
                **(
                    {"attempt_id": str(job.get("normalized_attempt_id") or "")}
                    if job.get("normalized_attempt_id")
                    else {}
                ),
            )
            return {"processed_count": 1, "completed_count": 0, "failed_count": 0}
        store.update_processing_job(
            job_id=str(job["id"]),
            status="completed",
            processing_metrics=processing_metrics,
            **(
                {"attempt_id": str(job.get("normalized_attempt_id") or "")}
                if job.get("normalized_attempt_id")
                else {}
            ),
        )
        if hasattr(store, "recover_ai_outage_episode") and str(job.get("outage_episode_id") or ""):
            store.recover_ai_outage_episode(
                episode_id=str(job["outage_episode_id"]),
                now=datetime.now(UTC),
            )
        return {"processed_count": 1, "completed_count": 1, "failed_count": 0}
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        if isinstance(exc, DocumentParseError) and not gemini_pdf_v2_selected:
            failure_stage = "parse"
        failure_event = (
            (
                "gemini_pdf_v2_failed",
                "Gemini native-PDF V2 belge islemesi tamamlanamadi.",
            )
            if gemini_pdf_v2_selected
            else {
                "parse": (
                    "parser_failed",
                    "Belge parse edilemedi.",
                ),
                "persistence": (
                    "persistence_failed",
                    "Belge sonucu kaydedilemedi.",
                ),
            }.get(
                failure_stage,
                (
                    "processing_failed",
                    "Belge isleme tamamlanamadi.",
                ),
            )
        )
        pipeline_event(
            failure_event[0],
            "error",
            failure_event[1],
            failure_event[0],
            {"error": str(exc), "failure_stage": failure_stage},
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
        if isinstance(exc, RetryableDocumentTechnicalError) or is_transient_persistence_error(exc):
            try:
                opened_at = datetime.fromisoformat(
                    str(job.get("created_at") or "").replace("Z", "+00:00")
                )
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=UTC)
            except ValueError:
                opened_at = datetime.now(UTC)
            retry = next_ai_retry(
                step=max(int(job.get("attempt_count") or 1) - 1, 0),
                opened_at=opened_at,
                now=datetime.now(UTC),
                document_id=document_ref,
            )
            store.update_processing_job(
                job_id=str(job.get("id") or ""),
                status=retry.status,
                error_message=str(exc),
                processing_metrics=processing_metrics,
                next_attempt_at=retry.next_attempt_at,
                retry_step=retry.retry_step,
                **(
                    {"attempt_id": str(job.get("normalized_attempt_id") or "")}
                    if job.get("normalized_attempt_id")
                    else {}
                ),
            )
            return {"processed_count": 1, "completed_count": 0, "failed_count": 0}
        store.update_processing_job(
            job_id=str(job.get("id") or ""),
            status="failed",
            error_message=str(exc),
            processing_metrics=processing_metrics,
            **(
                {"attempt_id": str(job.get("normalized_attempt_id") or "")}
                if job.get("normalized_attempt_id")
                else {}
            ),
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
    extraction_provider: object | None = None,
    accounting_provider: object | None = None,
    artifact_repository: Any | None = None,
    max_parallel_accounting_chunks: int = 1,
    candidate_experiment_percent: int | None = None,
    max_accounting_request_bytes: int | None = None,
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
            extraction_provider=extraction_provider,
            accounting_provider=accounting_provider,
            artifact_repository=artifact_repository,
            max_parallel_accounting_chunks=max_parallel_accounting_chunks,
            candidate_experiment_percent=candidate_experiment_percent,
            max_accounting_request_bytes=max_accounting_request_bytes,
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
