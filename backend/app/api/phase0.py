from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    phase0_routes_ai,
    phase0_routes_auth,
    phase0_routes_operations,
    phase0_routes_outgoing_invoices,
    phase0_routes_qnb,
    phase0_routes_review_export,
    phase0_routes_research,
    phase0_routes_simulation,
    phase0_routes_upload_processing,
    phase0_routes_workspace,
)
from app.api.phase0_context import (
    DEFAULT_BACKUP_PATH,
    DEFAULT_DOCUMENT_STORAGE_PATH,
    DEFAULT_EXPORT_PATH,
    DEFAULT_STORE_PATH,
    SESSION_COOKIE_NAME,
    get_workflow_store,
)
from app.api.phase0_mappers import (
    account_selection_from_payload as _account_selection,
    ai_policy_from_payload as _ai_policy,
    ai_provider_from_env as _ai_provider_from_env,
    benchmark_cases_from_payloads as _benchmark_cases,
    benchmark_response as _benchmark_response,
    chart_account_from_payload as _chart_account,
    client_profile_from_payload as _client_profile,
    learned_rule_from_payload as _learned_rule,
    parsed_invoice_from_payload as _parsed_invoice,
    statement_ai_policy_from_payload as _statement_ai_policy,
    statement_line_from_payload as _statement_line,
    static_first_classifier_from_payload as _static_first_classifier,
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
    ReviewRulePreviewPayload,
    SimulationPayload,
    StatementAiSuggestionPolicyPayload,
    StatementAiSuggestionsPayload,
    StatementLineSuggestionPayload,
    StoredExportPackagePayload,
    StoredReviewDecisionPayload,
    StoredSimulationPayload,
    WorkspaceExportPackagePayload,
)
from app.domain.journal_entries import build_sample_entries
from app.domain.tax_certificates import parse_tax_certificate_file


router = APIRouter()
router.include_router(phase0_routes_auth.router)
router.include_router(phase0_routes_operations.router)
router.include_router(phase0_routes_outgoing_invoices.router)
router.include_router(phase0_routes_qnb.router)
router.include_router(phase0_routes_upload_processing.router)
router.include_router(phase0_routes_review_export.router)
router.include_router(phase0_routes_research.router)
router.include_router(phase0_routes_workspace.router)
router.include_router(phase0_routes_ai.router)
router.include_router(phase0_routes_simulation.router)


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
