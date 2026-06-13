from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import tempfile

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app.api import (
    phase0_routes_auth,
    phase0_routes_operations,
    phase0_routes_review_export,
    phase0_routes_upload_processing,
)
from app.api.phase0_dependencies import (
    clear_session_cookie,
    client_id_from_record,
    password_bootstrap_enabled,
    record_operation_event as _record_operation_event,
    request_user_id,
    require_mock_client_access,
    set_session_cookie,
)
from app.api.phase0_review_export import (
    entry_payload as _entry_payload,
    export_package_payload,
    safe_export_file_name as _safe_export_file_name,
    workspace_document as _workspace_document,
    write_export_manifest as _write_export_manifest,
)
from app.api.phase0_schemas import (
    AccountSelectionPayload,
    AiBatchBenchmarkPayload,
    AiBenchmarkCasePayload,
    AiClassificationPolicyPayload,
    AiModelComparisonPayload,
    AiUsageEventPayload,
    AiUsageSummaryPayload,
    AuthInviteAcceptPayload,
    AuthInvitePayload,
    AuthLoginPayload,
    AuthLogoutPayload,
    AuthPasswordPayload,
    AuthPasswordResetConfirmPayload,
    AuthPasswordResetPayload,
    ChartAccountPayload,
    ChartAccountsStorePayload,
    ClientOnboardingPackagePayload,
    ClientProfilePayload,
    CounterpartyMatchPayload,
    DocumentRetentionRunPayload,
    DocumentUploadPayload,
    ExportCandidatePayload,
    ExportPackagePayload,
    InvoicePayload,
    JournalLinePayload,
    LearnedPostingRulePayload,
    OperationEventPayload,
    PortalAccessPayload,
    PortalUserPayload,
    ProcessingRunPayload,
    ProductClassificationPayload,
    RelevancePayload,
    ReviewDecisionPayload,
    SimulationPayload,
    StatementAiSuggestionPolicyPayload,
    StatementAiSuggestionsPayload,
    StatementLineSuggestionPayload,
    StoredExportPackagePayload,
    StoredReviewDecisionPayload,
    StoredSimulationPayload,
    WorkspaceExportPackagePayload,
)
from app.api.phase0_uploads import save_uploaded_document_with_job
from app.domain.ai_benchmark import AiBenchmarkCase, run_ai_batch_benchmark
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event, estimate_ai_cost_usd, summarize_ai_usage
from app.domain.business_relevance import ClientProfile, assess_business_relevance, check_client_onboarding
from app.domain.ai_classification import AiClassificationPolicy, StaticFirstClassifier
from app.domain.openai_provider import (
    DEFAULT_COMPARISON_MODEL,
    DEFAULT_GROQ_COMPARISON_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENAI_MODEL,
    GroqAccountingProvider,
    OpenAiAccountingProvider,
)
from app.domain.auth_policy import auth_status_payload, build_auth_config, resolve_user_id
from app.domain.chart_accounts import ChartAccount, normalize_account_code, parse_chart_accounts
from app.domain.counterparty_matching import match_counterparty
from app.domain.document_uploads import decode_base64_content, store_document_content
from app.domain.export_adapters import get_export_adapter, journal_entry_payload, write_export_file
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, build_sample_entries, money
from app.domain.learning_intelligence import enrich_learning_event
from app.domain.learning_rules import LearnedPostingRule, apply_learning_rules
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.operation_monitoring import (
    build_operation_event,
    operation_event_payload,
    summarize_operation_health,
)
from app.domain.pdf_invoices import ParsedInvoice
from app.domain.production_readiness import production_readiness_payload
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.domain.session_auth import (
    action_token_expires_at,
    create_auth_action_token,
    create_password_hash,
    create_session_token,
    hash_session_token,
    session_expires_at,
    verify_password,
)
from app.domain.statement_ai_suggestions import (
    ReplayStatementSuggestionProvider,
    StatementAiSuggestionPolicy,
    statement_ai_batch_payload,
    suggest_statement_lines,
)
from app.domain.statement_lines import StatementLine
from app.domain.tax_certificates import parse_tax_certificate_file
from app.domain.workspace_exports import build_workspace_export_package
from app.persistence.store_factory import build_workflow_store
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents

router = APIRouter()
router.include_router(phase0_routes_auth.router)
router.include_router(phase0_routes_operations.router)
router.include_router(phase0_routes_upload_processing.router)
router.include_router(phase0_routes_review_export.router)
DEFAULT_STORE_PATH = Path(os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json"))
DEFAULT_DOCUMENT_STORAGE_PATH = Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "exports/documents"))
DEFAULT_EXPORT_PATH = Path(os.environ.get("FISORA_EXPORT_PATH", "exports/generated"))
DEFAULT_BACKUP_PATH = Path(os.environ.get("FISORA_BACKUP_PATH", os.environ.get("FISORA_BACKUP_DIR", "exports/backups")))
SESSION_COOKIE_NAME = "fisora_session"

@router.get("/summary")
def summary() -> dict[str, object]:
    entries = build_sample_entries()
    return {
        "phase": "0",
        "goal": "Validate chart account import, balanced journal entries, and Zirve export candidates.",
        "sample_entry_count": len(entries),
        "sample_entries_balanced": all(entry.is_balanced for entry in entries),
        "risk_flags": sorted({flag for entry in entries for flag in entry.risk_flags}),
    }


def get_workflow_store():
    return build_workflow_store(json_path=DEFAULT_STORE_PATH)


def _set_session_cookie(response: Response, token: str, *, ttl_hours: int) -> None:
    set_session_cookie(response, token, ttl_hours=ttl_hours, cookie_name=SESSION_COOKIE_NAME)


def _clear_session_cookie(response: Response) -> None:
    clear_session_cookie(response, cookie_name=SESSION_COOKIE_NAME)


def _client_id_from_record(record: dict[str, object]) -> str:
    return client_id_from_record(record)


def _require_mock_client_access(
    *,
    client_id: str,
    user_id: str | None,
    allowed_roles: tuple[str, ...] = (),
) -> dict[str, object]:
    return require_mock_client_access(
        client_id=client_id,
        user_id=user_id,
        store_factory=get_workflow_store,
        allowed_roles=allowed_roles,
    )


def _request_user_id(
    user_header: str | None,
    session_header: str | None = None,
    session_cookie: str | None = None,
) -> str:
    return request_user_id(
        user_header,
        session_header,
        session_cookie,
        store_factory=get_workflow_store,
    )


def _password_bootstrap_enabled() -> bool:
    return password_bootstrap_enabled()


def _save_uploaded_document_with_job(
    *,
    client_id: str,
    document_type: str,
    intake_category: str = "",
    file_name: str,
    uploaded_by: str,
    uploaded_by_user_id: str = "",
    request_user_id: str = "",
    content: bytes | None,
    size_bytes: int = 0,
    sha256: str = "",
    retention_policy_days: int = 90,
) -> dict[str, object]:
    return save_uploaded_document_with_job(
        store=get_workflow_store(),
        document_storage_path=DEFAULT_DOCUMENT_STORAGE_PATH,
        record_operation_event=_record_operation_event,
        client_id=client_id,
        document_type=document_type,
        intake_category=intake_category,
        file_name=file_name,
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=request_user_id,
        content=content,
        size_bytes=size_bytes,
        sha256=sha256,
        retention_policy_days=retention_policy_days,
    )


def _client_profile(payload: ClientProfilePayload) -> ClientProfile:
    return ClientProfile(
        client_id=payload.client_id,
        title=payload.title,
        tax_id=payload.tax_id,
        activity_description=payload.activity_description,
        nace_code=payload.nace_code,
        activity_tags=tuple(payload.activity_tags),
        workplace_addresses=tuple(payload.workplace_addresses),
        has_chart_accounts=payload.has_chart_accounts,
    )


def _chart_account(payload: ChartAccountPayload) -> ChartAccount:
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


def _account_selection(payload: AccountSelectionPayload) -> AccountSelection:
    return AccountSelection(
        chart_file_name=payload.chart_file_name,
        expense_account=payload.expense_account,
        purchase_vat_account=payload.purchase_vat_account,
        supplier_account=payload.supplier_account,
        bank_account=payload.bank_account,
        selection_notes=tuple(payload.selection_notes),
    )


def _parsed_invoice(payload: InvoicePayload) -> ParsedInvoice:
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
    )


def _ai_policy(payload: AiClassificationPolicyPayload | None) -> AiClassificationPolicy:
    if payload is None:
        return AiClassificationPolicy()
    return AiClassificationPolicy(
        enabled=payload.enabled,
        static_confidence_threshold=payload.static_confidence_threshold,
        max_input_chars=payload.max_input_chars,
        max_provider_calls=payload.max_provider_calls,
    )


def _ai_provider_from_env(*, model: str = "") -> OpenAiAccountingProvider | GroqAccountingProvider | None:
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


def _static_first_classifier(payload: AiClassificationPolicyPayload | None) -> StaticFirstClassifier:
    policy = _ai_policy(payload)
    return StaticFirstClassifier(
        provider=_ai_provider_from_env() if policy.enabled else None,
        policy=policy,
    )


def _statement_ai_policy(payload: StatementAiSuggestionPolicyPayload | None) -> StatementAiSuggestionPolicy:
    if payload is None:
        return StatementAiSuggestionPolicy()
    return StatementAiSuggestionPolicy(
        enabled=payload.enabled,
        confidence_threshold=payload.confidence_threshold,
        max_input_chars=payload.max_input_chars,
        max_provider_calls=payload.max_provider_calls,
    )


def _statement_line(payload: StatementLineSuggestionPayload) -> StatementLine:
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


def _benchmark_cases(cases: list[AiBenchmarkCasePayload]) -> tuple[AiBenchmarkCase, ...]:
    return tuple(
        AiBenchmarkCase(
            case_id=case.case_id,
            raw_line=case.raw_line,
            supplier_hint=case.supplier_hint,
            expected_category=case.expected_category,
        )
        for case in cases
    )


def _benchmark_response(summary, *, model: str = "") -> dict[str, object]:
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


def _learned_rule(payload: LearnedPostingRulePayload) -> LearnedPostingRule:
    return LearnedPostingRule(
        scope=payload.scope,
        action=payload.action,
        category=payload.category,
        corrected_account_code=payload.corrected_account_code,
        corrected_counterparty_code=payload.corrected_counterparty_code,
        reason=payload.reason,
        automation_candidate=payload.automation_candidate,
    )


@router.post("/onboarding/check")
def onboarding_check(payload: ClientProfilePayload) -> dict[str, object]:
    check = check_client_onboarding(_client_profile(payload))
    return {"is_ready": check.is_ready, "missing_fields": list(check.missing_fields)}


@router.post("/store/client")
def store_client(payload: ClientProfilePayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    return get_workflow_store().upsert_client(
        client_id=payload.client_id,
        profile=payload.model_dump(),
        onboarding=onboarding_check(payload),
    )


@router.get("/store/clients")
def store_clients(
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    store = get_workflow_store()
    clients = store.list_clients()
    user_id = _request_user_id(x_fisora_user_id, x_fisora_session, fisora_session)
    if user_id:
        clients = [
            client
            for client in clients
            if store.verify_portal_access(client_id=_client_id_from_record(client), user_id=user_id).get("allowed")
        ]
    return {
        "clients": clients,
        "auth": {
            "mode": "session_or_header" if user_id else "disabled",
            "user_id": user_id,
        },
    }


@router.post("/store/chart-accounts")
def store_chart_accounts(payload: ChartAccountsStorePayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    accounts = [asdict(_chart_account(account)) for account in payload.accounts]
    return get_workflow_store().replace_chart_accounts(client_id=payload.client_id, accounts=accounts)


@router.post("/store/chart-accounts/upload")
async def store_chart_accounts_upload(
    client_id: str = Form(...),
    file: UploadFile = File(...),
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    normalized_client_id = client_id.strip()
    if not normalized_client_id:
        raise HTTPException(status_code=400, detail="client_id is required for chart account upload")
    _require_mock_client_access(
        client_id=normalized_client_id,
        user_id=_request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        allowed_roles=("accountant", "admin"),
    )
    original_name = Path(file.filename or "chart_accounts.csv").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail=f"Unsupported chart account format: {suffix or 'unknown'}")
    content = await file.read()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / original_name
        temp_path.write_bytes(content)
        try:
            parsed_accounts = parse_chart_accounts(temp_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    accounts = [asdict(account) for account in parsed_accounts]
    stored = get_workflow_store().replace_chart_accounts(client_id=normalized_client_id, accounts=accounts)
    _record_operation_event(
        store=get_workflow_store(),
        client_id=normalized_client_id,
        event_type="chart_accounts_uploaded",
        status="ok" if accounts else "warning",
        message="Hesap plani import edildi.",
        metadata={"file_name": original_name, "account_count": len(accounts)},
    )
    return {**stored, "file_name": original_name}


@router.post("/store/client-onboarding-package")
def store_client_onboarding_package(payload: ClientOnboardingPackagePayload) -> dict[str, object]:
    if not payload.client.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for onboarding package")
    store = get_workflow_store()
    client = store.upsert_client(
        client_id=payload.client.client_id,
        profile=payload.client.model_dump(),
        onboarding=onboarding_check(payload.client),
    )
    chart_accounts = None
    if payload.chart_accounts:
        chart_accounts = store.replace_chart_accounts(
            client_id=payload.client.client_id,
            accounts=[asdict(_chart_account(account)) for account in payload.chart_accounts],
        )
    portal_users = []
    for user in payload.portal_users:
        portal_users.append(
            store.upsert_portal_user(
                user_id=user.user_id,
                display_name=user.display_name,
                role=user.role,
                allowed_client_ids=user.allowed_client_ids or [payload.client.client_id],
            )
        )
    return {
        "client": client,
        "chart_accounts": chart_accounts,
        "portal_users": portal_users,
        "workspace": store.get_workspace(payload.client.client_id),
    }


@router.post("/tax-certificate/parse")
async def parse_tax_certificate_upload(file: UploadFile = File(...)) -> dict[str, object]:
    suffix = Path(file.filename or "tax-certificate.pdf").suffix.lower() or ".pdf"
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="unsupported tax certificate file type")
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        return parse_tax_certificate_file(temp_path).to_payload()
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/counterparty/match")
def counterparty_match(payload: CounterpartyMatchPayload) -> dict[str, object]:
    match = match_counterparty(
        [_chart_account(account) for account in payload.accounts],
        tax_ids=tuple(payload.tax_ids),
        ibans=tuple(payload.ibans),
        name_hint=payload.name_hint,
        account_prefixes=tuple(payload.account_prefixes),
    )
    return {
        "account_code": match.account_code,
        "account_name": match.account_name,
        "confidence": match.confidence,
        "match_reason": match.match_reason,
        "requires_review": match.requires_review,
    }


@router.post("/classification/product")
def product_classification(payload: ProductClassificationPayload) -> dict[str, object]:
    result = _static_first_classifier(payload.ai_policy).classify(
        payload.raw_line,
        supplier_hint=payload.supplier_hint,
    )
    usage_event = None
    if payload.client_id.strip():
        usage_event = ai_usage_payload(
            build_ai_usage_event(
                client_id=payload.client_id.strip(),
                provider=result.provider,
                operation="product_classification",
                input_chars=result.estimated_input_chars,
                ai_used=result.ai_used,
                skipped_reason=result.skipped_reason,
            )
        )
        get_workflow_store().record_ai_usage(client_id=payload.client_id.strip(), event=usage_event)
    return {
        "classification": {
            "raw_line": result.classification.raw_line,
            "category": result.classification.category,
            "confidence": result.classification.confidence,
            "evidence": list(result.classification.evidence),
        },
        "ai_used": result.ai_used,
        "provider": result.provider,
        "skipped_reason": result.skipped_reason,
        "provider_reason": result.provider_reason,
        "estimated_input_chars": result.estimated_input_chars,
        "usage_event": usage_event,
    }


@router.post("/statement/ai-suggestions")
def statement_ai_suggestions(
    payload: StatementAiSuggestionsPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if payload.client_id.strip():
        _require_mock_client_access(
            client_id=payload.client_id.strip(),
            user_id=_request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        )
    replay_provider = (
        ReplayStatementSuggestionProvider(
            list(payload.provider_payloads),
            provider_name=payload.provider_name,
        )
        if payload.provider_payloads
        else None
    )
    provider = replay_provider or (_ai_provider_from_env() if payload.ai_policy.enabled else None)
    batch = suggest_statement_lines(
        tuple(_statement_line(line) for line in payload.lines),
        provider=provider,
        policy=_statement_ai_policy(payload.ai_policy),
    )
    data = statement_ai_batch_payload(batch)
    usage_event = None
    if payload.client_id.strip():
        usage_event = ai_usage_payload(
            build_ai_usage_event(
                client_id=payload.client_id.strip(),
                provider=batch.provider,
                operation="statement_ai_suggestions",
                input_chars=batch.estimated_input_chars,
                ai_used=batch.ai_used_count > 0,
                skipped_reason="" if batch.ai_used_count > 0 else "statement_ai_skipped",
            )
        )
        get_workflow_store().record_ai_usage(client_id=payload.client_id.strip(), event=usage_event)
    return {**data, "usage_event": usage_event}


@router.post("/store/ai-usage")
def store_ai_usage(payload: AiUsageEventPayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    event = ai_usage_payload(
        build_ai_usage_event(
            client_id=payload.client_id.strip(),
            provider=payload.provider,
            operation=payload.operation,
            input_chars=payload.input_chars,
            ai_used=payload.ai_used,
            skipped_reason=payload.skipped_reason,
        )
    )
    return get_workflow_store().record_ai_usage(client_id=payload.client_id.strip(), event=event)


@router.post("/store/ai-usage/summary")
def store_ai_usage_summary(payload: AiUsageSummaryPayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    events = get_workflow_store().list_ai_usage(client_id=payload.client_id.strip())
    return {
        "client_id": payload.client_id,
        "summary": summarize_ai_usage(events, monthly_cap_usd=Decimal(payload.monthly_cap_usd)),
        "events": events,
    }


@router.post("/classification/batch-benchmark")
def classification_batch_benchmark(payload: AiBatchBenchmarkPayload) -> dict[str, object]:
    provider = None
    if payload.provider_name.strip().lower() in {"openai", "groq"} and not payload.provider_payloads:
        provider = _ai_provider_from_env(model=payload.model.strip())
        if provider is None:
            raise HTTPException(status_code=400, detail=f"{payload.provider_name} provider requires matching FISORA_AI_PROVIDER and API key")
    summary = run_ai_batch_benchmark(
        _benchmark_cases(payload.cases),
        policy=_ai_policy(payload.ai_policy),
        provider=provider,
        provider_payloads=payload.provider_payloads,
        provider_name=payload.provider_name,
    )
    return _benchmark_response(summary, model=payload.model.strip())


@router.post("/classification/model-comparison")
def classification_model_comparison(payload: AiModelComparisonPayload) -> dict[str, object]:
    provider_name = (payload.provider_name or os.environ.get("FISORA_AI_PROVIDER", "disabled")).strip().lower()
    if provider_name == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        default_models = [
            os.environ.get("FISORA_AI_MODEL", "").strip() or DEFAULT_GROQ_MODEL,
            os.environ.get("FISORA_AI_COMPARISON_MODEL", "").strip() or DEFAULT_GROQ_COMPARISON_MODEL,
        ]
        provider_factory = lambda selected_model: GroqAccountingProvider(api_key=api_key, model=selected_model)
    elif provider_name == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        default_models = [
            os.environ.get("FISORA_AI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL,
            os.environ.get("FISORA_AI_COMPARISON_MODEL", "").strip() or DEFAULT_COMPARISON_MODEL,
        ]
        provider_factory = lambda selected_model: OpenAiAccountingProvider(api_key=api_key, model=selected_model)
    else:
        raise HTTPException(status_code=400, detail="Model comparison requires FISORA_AI_PROVIDER=openai or groq")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{provider_name} comparison requires API key")
    models = [
        model.strip()
        for model in (payload.models or default_models)
        if model.strip()
    ]
    models = list(dict.fromkeys(models))[:3]
    cases = _benchmark_cases(payload.cases)
    case_count = len(cases) or 10
    base_policy = _ai_policy(payload.ai_policy)
    policy = AiClassificationPolicy(
        enabled=True,
        static_confidence_threshold=base_policy.static_confidence_threshold,
        max_input_chars=base_policy.max_input_chars,
        max_provider_calls=max(base_policy.max_provider_calls, case_count),
    )
    comparisons = []
    for model in models:
        summary = run_ai_batch_benchmark(
            cases,
            policy=policy,
            provider=provider_factory(model),
            provider_name=provider_name,
        )
        comparisons.append(_benchmark_response(summary, model=model))
    ranked = sorted(
        comparisons,
        key=lambda item: (
            -int(item["accuracy_percent"]),
            Decimal(str(item["estimated_cost_usd"])),
            -int(item["ai_used_count"]),
        ),
    )
    return {
        "provider": provider_name,
        "models": comparisons,
        "recommended_model": ranked[0]["model"] if ranked else "",
    }


@router.post("/simulation/invoice")
def simulation_invoice(payload: SimulationPayload) -> dict[str, object]:
    client = _client_profile(payload.client) if payload.client else None
    counterparty = None
    if payload.chart_accounts:
        counterparty = match_counterparty(
            [_chart_account(account) for account in payload.chart_accounts],
            tax_ids=tuple(payload.invoice.tax_ids),
            name_hint=payload.invoice.provider_hint,
        )
    result = simulate_invoice(
        _parsed_invoice(payload.invoice),
        _account_selection(payload.account_selection),
        client,
        counterparty,
        _static_first_classifier(payload.ai_policy),
        payload.processing_mode,
    )
    result = apply_learning_rules(result, [_learned_rule(rule) for rule in payload.learning_rules])
    data = asdict(result)
    for key in (
        "vat_rates",
        "risk_flags",
        "parse_notes",
        "review_reason_codes",
        "deterministic_checks",
        "business_relevance_evidence",
        "draft_lines",
    ):
        data[key] = list(data[key])
    return data


@router.post("/store/simulation")
def store_simulation(payload: StoredSimulationPayload) -> dict[str, object]:
    if payload.client is None or not payload.client.client_id.strip():
        raise HTTPException(status_code=400, detail="client profile with client_id is required for persistence")
    result = simulation_invoice(payload)
    store = get_workflow_store()
    store.upsert_client(
        client_id=payload.client.client_id,
        profile=payload.client.model_dump(),
        onboarding=onboarding_check(payload.client),
    )
    if payload.chart_accounts:
        store.replace_chart_accounts(
            client_id=payload.client.client_id,
            accounts=[asdict(_chart_account(account)) for account in payload.chart_accounts],
        )
    return store.save_simulation_result(
        client_id=payload.client.client_id,
        document_ref=str(result["file_name"]),
        result=result,
    )


@router.post("/relevance/assess")
def relevance_assess(payload: RelevancePayload) -> dict[str, object]:
    relevance = assess_business_relevance(
        payload.raw_line,
        _client_profile(payload.client),
        supplier_hint=payload.supplier_hint,
    )
    return {
        "status": relevance.status,
        "confidence": relevance.confidence,
        "reason": relevance.reason,
        "evidence": list(relevance.evidence),
        "relation": relevance.relation,
        "account_treatment": relevance.account_treatment,
        "requires_accountant_review": relevance.requires_accountant_review,
        "classification": {
            "raw_line": relevance.classification.raw_line,
            "category": relevance.classification.category,
            "confidence": relevance.classification.confidence,
            "evidence": list(relevance.classification.evidence),
        },
    }


@router.get("/store/workspace/{client_id}")
def store_workspace(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    _require_mock_client_access(
        client_id=client_id,
        user_id=_request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
    )
    return get_workflow_store().get_workspace(client_id)
