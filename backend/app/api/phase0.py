from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.domain.business_relevance import ClientProfile, assess_business_relevance, check_client_onboarding
from app.domain.journal_entries import build_sample_entries
from app.domain.review_learning import ReviewDecision, build_learning_event

router = APIRouter()


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


class RelevancePayload(BaseModel):
    raw_line: str
    supplier_hint: str = ""
    client: ClientProfilePayload


class ReviewDecisionPayload(BaseModel):
    document_ref: str
    action: str
    reviewer: str
    corrected_account_code: str = ""
    corrected_counterparty_code: str = ""
    category: str = ""
    reason: str = ""
    apply_to_similar: bool = False
    prior_consistent_approval_count: int = 0


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


@router.post("/onboarding/check")
def onboarding_check(payload: ClientProfilePayload) -> dict[str, object]:
    check = check_client_onboarding(_client_profile(payload))
    return {"is_ready": check.is_ready, "missing_fields": list(check.missing_fields)}


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
        action=payload.action,  # type: ignore[arg-type]
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

