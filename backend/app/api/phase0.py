from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.domain.business_relevance import ClientProfile, assess_business_relevance, check_client_onboarding
from app.domain.ai_classification import AiClassificationPolicy, StaticFirstClassifier
from app.domain.chart_accounts import ChartAccount, normalize_account_code
from app.domain.counterparty_matching import match_counterparty
from app.domain.document_uploads import decode_base64_content, store_document_content
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, build_sample_entries, money
from app.domain.learning_rules import LearnedPostingRule, apply_learning_rules
from app.domain.matching_simulation import AccountSelection, simulate_invoice
from app.domain.pdf_invoices import ParsedInvoice
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.persistence.workflow_store import JsonWorkflowStore

router = APIRouter()
DEFAULT_STORE_PATH = Path(os.environ.get("FISORA_STORE_PATH", "exports/phase0_store.json"))
DEFAULT_DOCUMENT_STORAGE_PATH = Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "exports/documents"))

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


class DocumentUploadPayload(BaseModel):
    client_id: str
    document_type: Literal["invoice", "einvoice_xml", "bank_statement", "pos_statement"] = "invoice"
    file_name: str
    uploaded_by: str = ""
    content_base64: str = ""
    size_bytes: int = 0
    sha256: str = ""


class StoredSimulationPayload(SimulationPayload):
    pass


class StoredReviewDecisionPayload(BaseModel):
    client_id: str
    decision: ReviewDecisionPayload


class StoredExportPackagePayload(BaseModel):
    client_id: str
    package: ExportPackagePayload


def get_workflow_store() -> JsonWorkflowStore:
    return JsonWorkflowStore(DEFAULT_STORE_PATH)


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
    return {
        "entry_type": entry.entry_type,
        "entry_date": entry.entry_date,
        "description": entry.description,
        "total_debit": f"{entry.total_debit:.2f}",
        "total_credit": f"{entry.total_credit:.2f}",
        "is_balanced": entry.is_balanced,
        "risk_flags": list(entry.risk_flags),
        "lines": [
            {
                "account_code": line.account_code,
                "description": line.description,
                "debit": f"{line.debit:.2f}",
                "credit": f"{line.credit:.2f}",
                "document_ref": line.document_ref,
            }
            for line in entry.lines
        ],
    }


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


@router.post("/store/chart-accounts")
def store_chart_accounts(payload: ChartAccountsStorePayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
    accounts = [asdict(_chart_account(account)) for account in payload.accounts]
    return get_workflow_store().replace_chart_accounts(client_id=payload.client_id, accounts=accounts)


@router.post("/store/document-upload")
def store_document_upload(payload: DocumentUploadPayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for document upload")
    content = None
    if payload.content_base64:
        try:
            content = decode_base64_content(payload.content_base64)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        document = store_document_content(
            base_dir=DEFAULT_DOCUMENT_STORAGE_PATH,
            client_id=payload.client_id,
            file_name=payload.file_name,
            document_type=payload.document_type,
            uploaded_by=payload.uploaded_by,
            content=content,
            declared_size_bytes=payload.size_bytes,
            declared_sha256=payload.sha256,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_workflow_store().save_uploaded_document(
        client_id=payload.client_id,
        document=asdict(document),
    )


@router.post("/counterparty/match")
def counterparty_match(payload: CounterpartyMatchPayload) -> dict[str, object]:
    match = match_counterparty(
        [_chart_account(account) for account in payload.accounts],
        tax_ids=tuple(payload.tax_ids),
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
def store_review_decision(payload: StoredReviewDecisionPayload) -> dict[str, object]:
    if not payload.client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required for persistence")
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


@router.get("/store/workspace/{client_id}")
def store_workspace(client_id: str) -> dict[str, object]:
    if not client_id.strip():
        raise HTTPException(status_code=400, detail="client_id is required")
    return get_workflow_store().get_workspace(client_id)
