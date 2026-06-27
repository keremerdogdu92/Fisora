from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.matching_simulation import ProcessingMode

ReviewAction = Literal[
    "approve",
    "approve_with_changes",
    "exclude_export",
    "exclude_from_export",
    "out_of_scope",
    "business_out_of_scope",
    "wrong_counterparty",
    "wrong_account",
    "review_required",
    "suggest_for_similar",
    "accept_detected_direction",
    "keep_upload_direction",
]


class ClientProfilePayload(BaseModel):
    client_id: str = ""
    title: str = ""
    tax_id: str = ""
    tckn: str = ""
    vkn: str = ""
    identity_type: str = ""
    tax_identifier: str = ""
    legal_name: str = ""
    trade_name: str = ""
    display_title: str = ""
    tax_office: str = ""
    activity_description: str = ""
    nace_code: str = ""
    activity_tags: list[str] = Field(default_factory=list)
    activity_profile: dict[str, object] = Field(default_factory=dict)
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
    revenue_account: str = "600.01"
    zero_vat_revenue_account: str = "600.00.3065"
    sales_vat_account: str = "391.01"
    customer_account: str = "120.01"
    next_customer_account: str = ""
    next_supplier_account: str = ""
    stock_account: str = "153.01"
    account_candidates: dict[str, object] = Field(default_factory=dict)


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
    issuer_title: str = ""
    issuer_tax_id: str = ""
    recipient_title: str = ""
    recipient_tax_id: str = ""
    invoice_type_code: str = ""
    is_return_invoice: bool = False


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


class StatementAiSuggestionPolicyPayload(BaseModel):
    enabled: bool = False
    confidence_threshold: int = 70
    max_input_chars: int = 420
    max_provider_calls: int = 3


class StatementLineSuggestionPayload(BaseModel):
    line_no: int
    transaction_date: str = ""
    description: str
    amount: str = "0.00"
    direction: Literal["in", "out", ""] = ""
    balance_after: str = ""
    counterparty_name: str = ""
    tax_id: str = ""
    iban: str = ""
    suggested_account_code: str = ""
    transaction_type: str = "unknown"
    confidence: int = 35
    risk_flags: list[str] = Field(default_factory=list)
    review_reason: str = ""


class StatementAiSuggestionsPayload(BaseModel):
    client_id: str = ""
    lines: list[StatementLineSuggestionPayload] = Field(default_factory=list)
    ai_policy: StatementAiSuggestionPolicyPayload = Field(default_factory=StatementAiSuggestionPolicyPayload)
    provider_name: str = "replay_provider"
    provider_payloads: list[dict[str, object]] = Field(default_factory=list)


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
    processing_mode: ProcessingMode = "ai_assisted_draft"
    learning_rules: list[LearnedPostingRulePayload] = Field(default_factory=list)


class RelevancePayload(BaseModel):
    raw_line: str
    supplier_hint: str = ""
    client: ClientProfilePayload


class ProductClassificationPayload(BaseModel):
    raw_line: str
    supplier_hint: str = ""
    client_id: str = ""
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
    model: str = ""
    provider_payloads: list[dict[str, object]] = Field(default_factory=list)


class AiModelComparisonPayload(BaseModel):
    cases: list[AiBenchmarkCasePayload] = Field(default_factory=list)
    ai_policy: AiClassificationPolicyPayload = Field(default_factory=AiClassificationPolicyPayload)
    provider_name: str = ""
    models: list[str] = Field(default_factory=list)


class AiUsageEventPayload(BaseModel):
    client_id: str
    provider: str = "static_rules"
    operation: str = "manual"
    input_chars: int = 0
    ai_used: bool = False
    skipped_reason: str = ""


class AiUsageSummaryPayload(BaseModel):
    client_id: str
    monthly_cap_usd: str = "100.00"


class OperationEventPayload(BaseModel):
    client_id: str = "__system__"
    event_type: str
    status: Literal["info", "ok", "warning", "error"] = "info"
    message: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class JournalLinePayload(BaseModel):
    account_code: str
    description: str = ""
    debit: str = "0.00"
    credit: str = "0.00"
    document_ref: str | None = None


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
    statement_line_no: int = 0
    draft_lines: list[JournalLinePayload] = Field(default_factory=list)


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
    document_type: Literal["invoice", "einvoice_xml", "bank_statement", "pos_statement", "special_document"] = "invoice"
    intake_category: str = ""
    period: str = ""
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


class AuthPasswordPayload(BaseModel):
    user_id: str
    password: str


class ClientPortalAccessUpdatePayload(BaseModel):
    client_id: str
    old_user_id: str = ""
    new_user_id: str
    display_name: str = ""
    password: str = ""


class AuthLoginPayload(BaseModel):
    user_id: str
    password: str
    ttl_hours: int = 12


class AuthLogoutPayload(BaseModel):
    session_token: str = ""


class AuthInvitePayload(BaseModel):
    user_id: str
    display_name: str = ""
    role: Literal["client_user", "accountant", "admin"] = "client_user"
    allowed_client_ids: list[str] = Field(default_factory=list)
    invited_by: str = ""
    ttl_hours: int = 48


class AuthInviteAcceptPayload(BaseModel):
    invite_token: str
    password: str


class AuthPasswordResetPayload(BaseModel):
    user_id: str
    ttl_hours: int = 24


class AuthPasswordResetConfirmPayload(BaseModel):
    reset_token: str
    password: str


class TestDataResetPayload(BaseModel):
    confirmation: str
    delete_files: bool = True


class DocumentRetentionRunPayload(BaseModel):
    delete_files: bool = True


class ClientDocumentsDeletePayload(BaseModel):
    client_id: str
    document_refs: list[str] = Field(default_factory=list)
    confirmed: bool = False
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
