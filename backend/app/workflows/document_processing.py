from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from os import environ
from pathlib import Path
from typing import Any

from app.domain.ai_classification import AiClassificationPolicy, ProductClassifier, StaticFirstClassifier
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event
from app.domain.business_relevance import ClientProfile
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty
from app.domain.learning_rules import apply_learning_rules, rule_from_event_payload
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.nace_research import resolve_nace_research_profile
from app.domain.openai_provider import DEFAULT_GROQ_MODEL, DEFAULT_OPENAI_MODEL, FallbackAccountingProvider, GroqAccountingProvider, OpenAiAccountingProvider
from app.domain.pdf_invoices import ParsedInvoice, parse_pdf_invoice
from app.domain.statement_ai_suggestions import (
    StatementAiSuggestionPolicy,
    StatementSuggestionProvider,
    statement_ai_batch_payload,
    suggest_statement_lines,
)
from app.domain.statement_journal_entries import build_statement_entry_records, statement_entry_payload
from app.domain.statement_lines import enrich_statement_lines_with_counterparties, parse_statement_file
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


def _account_selection(workspace: dict[str, Any]) -> AccountSelection:
    chart_accounts = workspace.get("chart_accounts") or {}
    accounts = [_chart_account(account) for account in chart_accounts.get("accounts", [])]
    return AccountSelection(
        chart_file_name="workspace-store",
        expense_account=_first_detail_account(accounts, ("770", "760", "740", "730"), "770.01"),
        purchase_vat_account=_first_detail_account(accounts, ("191",), "191.01"),
        supplier_account=_first_detail_account(accounts, ("320",), "320.01.001"),
        bank_account=_first_detail_account(accounts, ("102",), "102.01"),
        selection_notes=(),
    )


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
        activity_description=str(profile.get("activity_description") or ""),
        nace_code=str(profile.get("nace_code") or ""),
        activity_tags=tuple(profile.get("activity_tags") or ()),
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


def _serializable_simulation(
    invoice: ParsedInvoice,
    workspace: dict[str, Any],
    *,
    product_classifier: ProductClassifier | None = None,
) -> dict[str, Any]:
    accounts = _chart_accounts(workspace)
    counterparty = match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint) if accounts else None
    result = simulate_invoice(
        invoice,
        _account_selection(workspace),
        _client_profile(workspace),
        counterparty,
        product_classifier or StaticFirstClassifier(),
        processing_mode="ai_assisted_draft" if product_classifier else "controlled_automation",
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
        "draft_lines",
    ):
        data[key] = list(data[key])
    return _with_review_summary(data)


def _accounting_provider_from_env(provider_name: str, source: dict[str, str] | Any) -> OpenAiAccountingProvider:
    if provider_name == "groq":
        return GroqAccountingProvider(
            api_key=source.get("GROQ_API_KEY", ""),
            model=source.get("FISORA_GROQ_MODEL", source.get("FISORA_AI_MODEL", DEFAULT_GROQ_MODEL)),
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
    if not chain and provider_name in {"openai", "groq"}:
        chain = [provider_name]
    chain = [name for name in chain if name in {"openai", "groq"}]
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
            "statement_ai_provider": None,
            "statement_ai_policy": StatementAiSuggestionPolicy(),
        }
    product_policy = AiClassificationPolicy(
        enabled=True,
        static_confidence_threshold=int(source.get("FISORA_AI_STATIC_CONFIDENCE_THRESHOLD", "101")),
        max_input_chars=int(source.get("FISORA_AI_MAX_INPUT_CHARS", "420")),
        max_provider_calls=int(source.get("FISORA_AI_MAX_PROVIDER_CALLS", "3")),
    )
    statement_policy = StatementAiSuggestionPolicy(
        enabled=True,
        confidence_threshold=int(source.get("FISORA_AI_STATEMENT_CONFIDENCE_THRESHOLD", "101")),
        max_input_chars=int(source.get("FISORA_AI_STATEMENT_MAX_INPUT_CHARS", "420")),
        max_provider_calls=int(source.get("FISORA_AI_STATEMENT_MAX_PROVIDER_CALLS", "3")),
    )
    return {
        "product_classifier": StaticFirstClassifier(provider=provider, policy=product_policy),
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
    if result.get("draft_lines"):
        return "draft_ready"
    return "manual_draft_required"


def _accountant_summary(result: dict[str, Any]) -> str:
    if result.get("document_validation_status") == "unexpected_document":
        return "Bu dosya beklenen fatura/ekstre yapisinda gorunmuyor. Dogru belge yeniden istenmeli."
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
        "ai_provider": str(result.get("ai_classification_provider") or ""),
        "ai_skipped_reason": str(result.get("ai_classification_skipped_reason") or ""),
        "ai_reason": str(result.get("ai_classification_reason") or ""),
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
    if skipped == "ai_provider_error":
        return f"AI kararı alınamadı. Provider {provider} hata verdi; statik kontrol sonucu korundu. Riskler: {risks}."
    return (
        f"AI kararı: {provider} belge kalemini {category} olarak değerlendirdi. "
        f"Güven: %{confidence}. Gerekçe: {reason or 'Gerekçe üretilmedi.'} "
        f"Hesap önerisi: {account}. Cari önerisi: {counterparty}. Riskler: {risks}."
    )


def _with_review_summary(result: dict[str, Any], *, document_validation_status: str = "expected_document") -> dict[str, Any]:
    updated = dict(result)
    updated.setdefault("document_validation_status", document_validation_status)
    updated.setdefault("draft_status", _draft_status(updated))
    updated.setdefault("accountant_summary", _accountant_summary(updated))
    updated.setdefault("ai_explanation_tr", _ai_explanation_tr(updated))
    updated.setdefault("technical_details", _technical_details(updated))
    return updated


def _parse_invoice_document(path: Path, document_type: str) -> ParsedInvoice:
    if document_type == "einvoice_xml" or path.suffix.lower() == ".xml":
        return parse_xml_invoice(path)
    return parse_pdf_invoice(path)


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
    invoice = _parse_invoice_document(path, document_type)
    if not _invoice_has_expected_shape(invoice):
        return _unexpected_document_result(
            document,
            job,
            reason="Fatura numarasi, tarih, tutar veya vergi kimligi okunamadi.",
        )
    return _serializable_simulation(invoice, workspace, product_classifier=product_classifier)


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


def process_next_job_once(
    store: Any,
    *,
    product_classifier: ProductClassifier | None = None,
    statement_ai_provider: StatementSuggestionProvider | None = None,
    statement_ai_policy: StatementAiSuggestionPolicy | None = None,
) -> dict[str, Any]:
    job = store.claim_next_processing_job()
    if job is None:
        return {"processed_count": 0, "completed_count": 0, "failed_count": 0}
    client_id = str(job["client_id"])
    document_ref = str(job.get("document_ref") or "")

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
            "Belge parse edilmeye başladı.",
            "parse_started",
            {"parser_kind": str(job.get("parser_kind") or "")},
        )
        workspace = store.get_workspace(client_id)
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
                f"AI provider seçildi: {selected_provider}.",
                "ai_provider_selected",
                {"provider": selected_provider},
            )
        workspace = _workspace_with_nace_research(workspace, store)
        result = build_processing_result(
            document,
            job,
            workspace,
            product_classifier=runtime["product_classifier"],
            statement_ai_provider=runtime["statement_ai_provider"],
            statement_ai_policy=runtime["statement_ai_policy"],
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
                "AI geldi karar verdi." if ai_status == "ok" else "AI provider hata verdi; fallback kontrol kullanıldı.",
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
                "Müşavir AI çıktısını Türkçe gerekçeyle görebilir.",
                "accountant_ai_explanation_ready",
                {"ai_explanation_tr": str(result.get("ai_explanation_tr") or _ai_explanation_tr(result))},
            )
        if result.get("business_relevance_relation") == "weak_match":
            pipeline_event(
                "weak_match",
                "warning",
                "Kalem faaliyet profiliyle zayıf eşleşti.",
                "weak_match",
                {"business_relevance_reason": str(result.get("business_relevance_reason") or "")},
            )
        if result.get("draft_lines"):
            pipeline_event(
                "journal_draft_ready",
                "ok",
                "Belge muhasebe fişi olarak doldu.",
                "journal_draft_ready",
                {"draft_line_count": len(result.get("draft_lines") or [])},
            )
        if result.get("draft_lines") and not result.get("is_balanced"):
            pipeline_event(
                "journal_unbalanced",
                "warning",
                "Muhasebe fişi dengeli değil.",
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
                "Muhasebe fişi kaydedildi; exporta gönderilebilir durumda.",
                "export_ready",
                {},
            )
        store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
        )
        _record_ai_usage_from_result(store, client_id=client_id, result=result)
        store.update_processing_job(job_id=str(job["id"]), status="completed")
        return {"processed_count": 1, "completed_count": 1, "failed_count": 0}
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        pipeline_event(
            "parser_failed",
            "error",
            "Belge parse edilemedi.",
            "parser_failed",
            {"error": str(exc)},
        )
        store.update_processing_job(job_id=str(job.get("id") or ""), status="failed", error_message=str(exc))
        return {"processed_count": 1, "completed_count": 0, "failed_count": 1}


def process_queued_documents(
    store: Any,
    *,
    max_jobs: int = 10,
    product_classifier: ProductClassifier | None = None,
    statement_ai_provider: StatementSuggestionProvider | None = None,
    statement_ai_policy: StatementAiSuggestionPolicy | None = None,
) -> dict[str, Any]:
    summary = {"processed_count": 0, "completed_count": 0, "failed_count": 0}
    for _ in range(max_jobs):
        result = process_next_job_once(
            store,
            product_classifier=product_classifier,
            statement_ai_provider=statement_ai_provider,
            statement_ai_policy=statement_ai_policy,
        )
        if result["processed_count"] == 0:
            break
        for key in summary:
            summary[key] += int(result[key])
    return summary
