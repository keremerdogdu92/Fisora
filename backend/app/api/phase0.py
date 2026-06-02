from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.domain.ai_benchmark import AiBenchmarkCase, run_ai_batch_benchmark
from app.domain.business_relevance import ClientProfile, assess_business_relevance, check_client_onboarding
from app.domain.ai_classification import AiClassificationPolicy, StaticFirstClassifier
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty
from app.domain.document_uploads import decode_base64_content, store_document_content
from app.domain.export_adapters import get_export_adapter, journal_entry_payload, write_export_file
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, build_sample_entries, money
from app.domain.learning_rules import LearnedPostingRule, apply_learning_rules
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.pdf_invoices import ParsedInvoice
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.domain.workspace_exports import build_workspace_export_package
from app.persistence.store_factory import build_workflow_store
from app.workflows.document_processing import parser_kind_for_document_type, process_queued_documents

router = APIRouter()
DEFAULT_STORE_PATH = Path(os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json"))
DEFAULT_DOCUMENT_STORAGE_PATH = Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "exports/documents"))
DEFAULT_EXPORT_PATH = Path(os.environ.get("FISORA_EXPORT_PATH", "exports/generated"))

ReviewAction = Literal[
    "approve",
    "approve_with_changes",
    "exclude_export",
    "exclude_from_export",
    "out_of_scope",
    "business_out_of_scope",
    "wrong_counterparty",
    "wrong_account",
    "suggest_for_similar",
]


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


class ClientProfilePayload(BaseModel):
    client_id: str = ""
    title: str = ""
    tax_id: str = ""
    activity_description: str = ""
    nace_code: str = ""
    workplace_addresses: list[str] = Field(default_factory=list)
    has_chart_accounts: bool = False


class ChartAccountPayload(BaseModel):
    raw_account_code: str
    account_name: str
    normalized_account_code: str = ""
    is_detail_account: bool | None = None
    tax_id: str | None = None
    tax_office: str | None = None
    iban: str | None = None


class AccountSelectionPayload(BaseModel):
    chart_file_name: str = "api"
    expense_account: str = "770.01"
    purchase_vat_account: str = "191.01"
    supplier_account: str = "320.01"
    bank_account: str = "102.01"
    selection_notes: list[str] = Field(default_factory=list)


class InvoicePayload(BaseModel):
    file_name: str
    provider_hint: str = ""
    page_count: int = 1
    text_extractable: bool = True
    extracted_char_count: int = 0
    scenario: str = ""
    invoice_type: str = "ALIS"
    invoice_no: str = ""
    ettn: str = ""
    issue_date: str = ""
    tax_ids: list[str] = Field(default_factory=list)
    vat_rates: list[str] = Field(default_factory=list)
    goods_services_total: str = ""
    vat_total: str = ""
    special_tax_total: str = ""
    tax_inclusive_total: str = ""
    payable_total: str = "0.00"
    risk_flags: list[str] = Field(default_factory=list)
    suggested_route: str = "journal_candidate"
    parse_notes: list[str] = Field(default_factory=list)
    line_items: list[str] = Field(default_factory=list)


class CounterpartyMatchPayload(BaseModel):
    accounts: list[ChartAccountPayload] = Field(default_factory=list)
    tax_ids: list[str] = Field(default_factory=list)
    ibans: list[str] = Field(default_factory=list)
    name_hint: str = ""
    account_prefixes: list[str] = Field(default_factory=lambda: ["120", "320"])


class AiClassificationPolicyPayload(BaseModel):
    enabled: bool = False
    static_confidence_threshold: int = 70
    max_input_chars: int = 320
    max_provider_calls: int = 1


class LearnedPostingRulePayload(BaseModel):
    scope: str = "client_rule"
    action: str = "approve_with_changes"
    category: str
    corrected_account_code: str = ""
    corrected_counterparty_code: str = ""
    reason: str = ""
    automation_candidate: bool = False


class SimulationPayload(BaseModel):
    invoice: InvoicePayload
    account_selection: AccountSelectionPayload = Field(default_factory=AccountSelectionPayload)
    client: ClientProfilePayload | None = None
    chart_accounts: list[ChartAccountPayload] = Field(default_factory=list)
    ai_policy: AiClassificationPolicyPayload | None = None
    learning_rules: list[LearnedPostingRulePayload] = Field(default_factory=list)


class RelevancePayload(BaseModel):
    raw_line: str
    supplier_hint: str = ""
    client: ClientProfilePayload


class ProductClassificationPayload(BaseModel):
    raw_line: str
    supplier_hint: str = ""
    ai_policy: AiClassificationPolicyPayload = Field(default_factory=AiClassificationPolicyPayload)


class AiBenchmarkCasePayload(BaseModel):
    case_id: str
    raw_line: str
    supplier_hint: str = ""
    expected_category: str = ""


class AiBatchBenchmarkPayload(BaseModel):
    cases: list[AiBenchmarkCasePayload] = Field(default_factory=list)
    ai_policy: AiClassificationPolicyPayload = Field(default_factory=AiClassificationPolicyPayload)
    provider_name: str = "static_rules"
    provider_payloads: list[dict[str, object]] = Field(default_factory=list)


class ReviewDecisionPayload(BaseModel):
    document_ref: str
    action: ReviewAction
    reviewer: str
    corrected_account_code: str = ""
    corrected_counterparty_code: str = ""
    category: str = ""
    reason: str = ""
    apply_to_similar: bool = False
    prior_consistent_approval_count: int = 0


class JournalLinePayload(BaseModel):
    account_code: str
    description: str = ""
    debit: str = "0.00"
    credit: str = "0.00"
    document_ref: str | None = None


class ExportCandidatePayload(BaseModel):
    document_ref: str
    export_status: str
    entry_type: str = "purchase"
    entry_date: str = "1900-01-01"
    description: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    lines: list[JournalLinePayload] = Field(default_factory=list)


class ExportPackagePayload(BaseModel):
    export_type: str = "zirve_universal_csv"
    candidates: list[ExportCandidatePayload] = Field(default_factory=list)


class ChartAccountsStorePayload(BaseModel):
    client_id: str
    accounts: list[ChartAccountPayload] = Field(default_factory=list)


class PortalUserPayload(BaseModel):
    user_id: str
    display_name: str = ""
    role: Literal["client_user", "accountant", "admin"] = "client_user"
    allowed_client_ids: list[str] = Field(default_factory=list)


class ClientOnboardingPackagePayload(BaseModel):
    client: ClientProfilePayload
    chart_accounts: list[ChartAccountPayload] = Field(default_factory=list)
    portal_users: list[PortalUserPayload] = Field(default_factory=list)


class DocumentUploadPayload(BaseModel):
    client_id: str
    document_type: Literal["invoice", "einvoice_xml", "bank_statement", "pos_statement"] = "invoice"
    file_name: str
    uploaded_by: str = ""
    uploaded_by_user_id: str = ""
    content_base64: str = ""
    size_bytes: int = 0
    sha256: str = ""
    retention_policy_days: int = 90


class PortalAccessPayload(BaseModel):
    client_id: str
    user_id: str


class DocumentRetentionRunPayload(BaseModel):
    delete_files: bool = True


class ProcessingRunPayload(BaseModel):
    max_jobs: int = 10


class StoredSimulationPayload(SimulationPayload):
    pass


class StoredReviewDecisionPayload(BaseModel):
    client_id: str
    decision: ReviewDecisionPayload


class StoredExportPackagePayload(BaseModel):
    client_id: str
    package: ExportPackagePayload


class WorkspaceExportPackagePayload(BaseModel):
    client_id: str
    export_type: str = "zirve_universal_csv"


def get_workflow_store():
    return build_workflow_store(json_path=DEFAULT_STORE_PATH)


def _client_id_from_record(record: dict[str, object]) -> str:
    profile = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    return str(record.get("client_id") or profile.get("client_id") or "").strip()


def _require_mock_client_access(
    *,
    client_id: str,
    user_id: str | None,
    allowed_roles: tuple[str, ...] = (),
) -> dict[str, object]:
    if not user_id:
        return {"allowed": True, "reason": "mock_auth_disabled", "role": "anonymous", "client_id": client_id}
    access = get_workflow_store().verify_portal_access(client_id=client_id, user_id=user_id)
    if not access.get("allowed"):
        raise HTTPException(status_code=403, detail=access)
    role = str(access.get("role") or "")
    if allowed_roles and role not in allowed_roles and role != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                **access,
                "reason": "role_not_allowed",
                "allowed_roles": list(allowed_roles),
            },
        )
    return access


def _mock_user_header(value: str | None) -> str:
    return (value or "").strip()


def _safe_export_file_name(client_id: str, export_type: str, extension: str = ".csv") -> str:
    safe_client = re.sub(r"[^A-Za-z0-9_.-]+", "-", client_id.strip()).strip(".-") or "client"
    safe_type = re.sub(r"[^A-Za-z0-9_.-]+", "-", export_type.strip()).strip(".-") or "export"
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    return f"{safe_client}-{safe_type}{safe_extension}"


def _manifest_file_name(output_filename: str) -> str:
    path = Path(output_filename)
    return f"{path.stem}.manifest.json"


def _write_export_manifest(
    *,
    client_id: str,
    output_path: Path,
    package_payload: dict[str, object],
) -> dict[str, str]:
    manifest_filename = _manifest_file_name(str(package_payload.get("output_filename") or output_path.name))
    manifest_path = output_path.with_name(manifest_filename)
    manifest_payload = {
        "client_id": client_id,
        "export_type": package_payload.get("export_type"),
        "output_filename": package_payload.get("output_filename"),
        "entry_count": package_payload.get("entry_count"),
        "candidate_count": package_payload.get("candidate_count"),
        "excluded_document_refs": package_payload.get("excluded_document_refs"),
        "generated_entries": [
            {
                "entry_type": entry.get("entry_type"),
                "entry_date": entry.get("entry_date"),
                "description": entry.get("description"),
                "line_count": len(entry.get("lines") or []),
            }
            for entry in package_payload.get("entries") or []
            if isinstance(entry, dict)
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest_filename": manifest_filename, "manifest_path": str(manifest_path)}


def _save_uploaded_document_with_job(
    *,
    client_id: str,
    document_type: str,
    file_name: str,
    uploaded_by: str,
    uploaded_by_user_id: str = "",
    request_user_id: str = "",
    content: bytes | None,
    size_bytes: int = 0,
    sha256: str = "",
    retention_policy_days: int = 90,
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for document upload")
    store = get_workflow_store()
    effective_user_id = uploaded_by_user_id.strip() or uploaded_by.strip() or request_user_id.strip()
    if request_user_id.strip() and effective_user_id and request_user_id.strip() != effective_user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "allowed": False,
                "reason": "mock_user_header_mismatch",
                "user_id": request_user_id.strip(),
                "payload_user_id": effective_user_id,
            },
        )
    if not effective_user_id:
        raise HTTPException(status_code=403, detail="portal user is required for document upload")
    access = store.verify_portal_access(client_id=client_id, user_id=effective_user_id)
    if not access.get("allowed"):
        raise HTTPException(status_code=403, detail=access)
    try:
        document = store_document_content(
            base_dir=DEFAULT_DOCUMENT_STORAGE_PATH,
            client_id=client_id,
            file_name=file_name,
            document_type=document_type,
            uploaded_by=uploaded_by,
            content=content,
            declared_size_bytes=size_bytes,
            declared_sha256=sha256,
            retention_days=retention_policy_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    document_payload = asdict(document)
    document_payload["uploaded_by_user_id"] = effective_user_id
    document_payload["portal_access_reason"] = access.get("reason", "")
    saved = store.save_uploaded_document(
        client_id=client_id,
        document=document_payload,
    )
    job = store.create_processing_job(
        client_id=client_id,
        document_ref=str(saved["document_ref"]),
        document_type=document_type,
        parser_kind=parser_kind_for_document_type(document_type),
    )
    return {**saved, "processing_job": job}


def _client_profile(payload: ClientProfilePayload) -> ClientProfile:
    return ClientProfile(
        client_id=payload.client_id,
        title=payload.title,
        tax_id=payload.tax_id,
        activity_description=payload.activity_description,
        nace_code=payload.nace_code,
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


def _static_first_classifier(payload: AiClassificationPolicyPayload | None) -> StaticFirstClassifier:
    return StaticFirstClassifier(policy=_ai_policy(payload))


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


def _journal_entry(payload: ExportCandidatePayload) -> JournalEntry:
    return JournalEntry(
        entry_type=payload.entry_type,
        entry_date=payload.entry_date,
        description=payload.description or f"Export candidate {payload.document_ref}",
        lines=tuple(
            JournalLine(
                line.account_code,
                line.description,
                debit=money(line.debit),
                credit=money(line.credit),
                document_ref=line.document_ref or payload.document_ref,
            )
            for line in payload.lines
        ),
        risk_flags=tuple(payload.risk_flags),
    )


def _entry_payload(entry: JournalEntry) -> dict[str, object]:
    return journal_entry_payload(entry)


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
def store_clients(x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id")) -> dict[str, object]:
    store = get_workflow_store()
    clients = store.list_clients()
    user_id = _mock_user_header(x_fisora_user_id)
    if user_id:
        clients = [
            client
            for client in clients
            if store.verify_portal_access(client_id=_client_id_from_record(client), user_id=user_id).get("allowed")
        ]
    return {
        "clients": clients,
        "auth": {
            "mode": "mock_header" if user_id else "disabled",
            "user_id": user_id,
        },
    }


@router.post("/store/chart-accounts")
def store_chart_accounts(payload: ChartAccountsStorePayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    accounts = [asdict(_chart_account(account)) for account in payload.accounts]
    return get_workflow_store().replace_chart_accounts(client_id=payload.client_id, accounts=accounts)


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


@router.post("/store/portal-user")
def store_portal_user(payload: PortalUserPayload) -> dict[str, object]:
    if not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required for portal user")
    try:
        return get_workflow_store().upsert_portal_user(
            user_id=payload.user_id,
            display_name=payload.display_name,
            role=payload.role,
            allowed_client_ids=payload.allowed_client_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/store/portal-access/check")
def store_portal_access_check(payload: PortalAccessPayload) -> dict[str, object]:
    if not payload.client_id.strip() or not payload.user_id.strip():
        raise HTTPException(status_code=400, detail="client_id and user_id are required")
    return get_workflow_store().verify_portal_access(client_id=payload.client_id, user_id=payload.user_id)


@router.post("/store/document-upload")
def store_document_upload(
    payload: DocumentUploadPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> dict[str, object]:
    content = None
    if payload.content_base64:
        try:
            content = decode_base64_content(payload.content_base64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _save_uploaded_document_with_job(
        client_id=payload.client_id,
        document_type=payload.document_type,
        file_name=payload.file_name,
        uploaded_by=payload.uploaded_by,
        uploaded_by_user_id=payload.uploaded_by_user_id,
        request_user_id=_mock_user_header(x_fisora_user_id),
        content=content,
        size_bytes=payload.size_bytes,
        sha256=payload.sha256,
        retention_policy_days=payload.retention_policy_days,
    )


@router.post("/store/document-upload-multipart")
async def store_document_upload_multipart(
    client_id: str = Form(...),
    document_type: Literal["invoice", "einvoice_xml", "bank_statement", "pos_statement"] = Form("invoice"),
    uploaded_by: str = Form(""),
    uploaded_by_user_id: str = Form(""),
    retention_policy_days: int = Form(90),
    file: UploadFile = File(...),
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> dict[str, object]:
    content = await file.read()
    return _save_uploaded_document_with_job(
        client_id=client_id,
        document_type=document_type,
        file_name=file.filename or "document.bin",
        uploaded_by=uploaded_by,
        uploaded_by_user_id=uploaded_by_user_id,
        request_user_id=_mock_user_header(x_fisora_user_id),
        content=content,
        size_bytes=len(content),
        retention_policy_days=retention_policy_days,
    )


@router.post("/store/document-retention/run")
def store_document_retention_run(payload: DocumentRetentionRunPayload) -> dict[str, object]:
    return get_workflow_store().apply_document_retention(delete_files=payload.delete_files)


@router.post("/store/processing/run")
def store_processing_run(payload: ProcessingRunPayload) -> dict[str, object]:
    return process_queued_documents(get_workflow_store(), max_jobs=payload.max_jobs)


@router.get("/store/processing-jobs/{client_id}")
def store_processing_jobs(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    _require_mock_client_access(client_id=client_id, user_id=_mock_user_header(x_fisora_user_id))
    return {"jobs": get_workflow_store().list_processing_jobs(client_id=client_id)}


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
    }


@router.post("/classification/batch-benchmark")
def classification_batch_benchmark(payload: AiBatchBenchmarkPayload) -> dict[str, object]:
    summary = run_ai_batch_benchmark(
        tuple(
            AiBenchmarkCase(
                case_id=case.case_id,
                raw_line=case.raw_line,
                supplier_hint=case.supplier_hint,
                expected_category=case.expected_category,
            )
            for case in payload.cases
        ),
        policy=_ai_policy(payload.ai_policy),
        provider_payloads=payload.provider_payloads,
        provider_name=payload.provider_name,
    )
    return {
        "case_count": summary.case_count,
        "ai_used_count": summary.ai_used_count,
        "matched_count": summary.matched_count,
        "evaluated_count": summary.evaluated_count,
        "accuracy_percent": summary.accuracy_percent,
        "estimated_input_chars": summary.estimated_input_chars,
        "provider": summary.provider,
        "results": [asdict(result) for result in summary.results],
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
    )
    result = apply_learning_rules(result, [_learned_rule(rule) for rule in payload.learning_rules])
    data = asdict(result)
    for key in (
        "vat_rates",
        "risk_flags",
        "parse_notes",
        "review_reason_codes",
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
        "classification": {
            "raw_line": relevance.classification.raw_line,
            "category": relevance.classification.category,
            "confidence": relevance.classification.confidence,
            "evidence": list(relevance.classification.evidence),
        },
    }


@router.post("/review/learning-event")
def review_learning_event(payload: ReviewDecisionPayload) -> dict[str, object]:
    decision = ReviewDecision(
        document_ref=payload.document_ref,
        action=payload.action,
        reviewer=payload.reviewer,
        corrected_account_code=payload.corrected_account_code,
        corrected_counterparty_code=payload.corrected_counterparty_code,
        category=payload.category,
        reason=payload.reason,
        apply_to_similar=payload.apply_to_similar,
    )
    event = build_learning_event(
        decision,
        prior_consistent_approval_count=payload.prior_consistent_approval_count,
    )
    return {
        "document_ref": event.document_ref,
        "scope": event.scope,
        "action": event.action,
        "category": event.category,
        "corrected_account_code": event.corrected_account_code,
        "corrected_counterparty_code": event.corrected_counterparty_code,
        "reason": event.reason,
        "automation_candidate": event.automation_candidate,
    }


@router.post("/store/review-decision")
def store_review_decision(
    payload: StoredReviewDecisionPayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    _require_mock_client_access(
        client_id=payload.client_id,
        user_id=_mock_user_header(x_fisora_user_id),
        allowed_roles=("accountant", "admin"),
    )
    event = review_learning_event(payload.decision)
    return get_workflow_store().save_review_decision(
        client_id=payload.client_id,
        decision=payload.decision.model_dump(),
        learning_event=event,
    )


@router.post("/export/package")
def export_package(payload: ExportPackagePayload) -> dict[str, object]:
    candidates = [
        ExportCandidate(
            candidate.document_ref,
            candidate.export_status,
            _journal_entry(candidate),
            risk_flags=tuple(candidate.risk_flags),
        )
        for candidate in payload.candidates
    ]
    package = build_export_package(candidates, export_type=payload.export_type)
    return {
        "export_type": package.export_type,
        "entry_count": len(package.entries),
        "excluded_document_refs": list(package.excluded_document_refs),
        "entries": [_entry_payload(entry) for entry in package.entries],
    }


@router.post("/store/export-package")
def store_export_package(payload: StoredExportPackagePayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    package = export_package(payload.package)
    return get_workflow_store().save_export_package(client_id=payload.client_id, package=package)


@router.post("/store/export-package/from-workspace")
def store_export_package_from_workspace(
    payload: WorkspaceExportPackagePayload,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    _require_mock_client_access(
        client_id=payload.client_id,
        user_id=_mock_user_header(x_fisora_user_id),
        allowed_roles=("accountant", "admin"),
    )
    store = get_workflow_store()
    workspace = store.get_workspace(payload.client_id)
    try:
        adapter = get_export_adapter(payload.export_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    build = build_workspace_export_package(workspace, export_type=adapter.export_type)
    output_filename = _safe_export_file_name(payload.client_id, adapter.export_type, adapter.file_extension)
    output_path = DEFAULT_EXPORT_PATH / payload.client_id / output_filename
    write_export_file(
        adapter=adapter,
        entries=build.package.entries,
        output_path=output_path,
        client_id=payload.client_id,
    )
    package_payload = {
        "export_type": build.package.export_type,
        "adapter": {
            "display_name": adapter.display_name,
            "file_extension": adapter.file_extension,
            "mime_type": adapter.mime_type,
            "verified_in_zirve": adapter.verified_in_zirve,
        },
        "candidate_count": build.candidate_count,
        "entry_count": len(build.package.entries),
        "excluded_document_refs": list(build.package.excluded_document_refs),
        "output_filename": output_filename,
        "output_path": str(output_path),
        "download_url": f"/phase0/store/export-package/download/{payload.client_id}/{output_filename}",
        "entries": [_entry_payload(entry) for entry in build.package.entries],
    }
    manifest = _write_export_manifest(client_id=payload.client_id, output_path=output_path, package_payload=package_payload)
    package_payload.update(
        {
            **manifest,
            "manifest_download_url": f"/phase0/store/export-package/download/{payload.client_id}/{manifest['manifest_filename']}",
        }
    )
    return store.save_export_package(client_id=payload.client_id, package=package_payload)


@router.get("/store/export-package/download/{client_id}/{file_name}")
def download_export_package(
    client_id: str,
    file_name: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> FileResponse:
    _require_mock_client_access(client_id=client_id, user_id=_mock_user_header(x_fisora_user_id))
    safe_name = Path(file_name).name
    path = DEFAULT_EXPORT_PATH / client_id / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="export file not found")
    if path.suffix.lower() == ".csv":
        get_workflow_store().mark_export_package_downloaded(client_id=client_id, output_filename=safe_name)
    media_type = "application/json; charset=utf-8" if path.suffix.lower() == ".json" else "text/csv; charset=utf-8"
    return FileResponse(path, filename=safe_name, media_type=media_type)


@router.get("/store/workspace/{client_id}")
def store_workspace(
    client_id: str,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    _require_mock_client_access(client_id=client_id, user_id=_mock_user_header(x_fisora_user_id))
    return get_workflow_store().get_workspace(client_id)
