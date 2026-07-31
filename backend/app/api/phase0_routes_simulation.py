from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.api.phase0_context import get_workflow_store
from app.api.phase0_mappers import (
    account_selection_from_payload,
    chart_account_from_payload,
    client_profile_from_payload,
    learned_rule_from_payload,
    parsed_invoice_from_payload,
    static_first_classifier_from_payload,
)
from app.api.phase0_schemas import (
    CounterpartyMatchPayload,
    RelevancePayload,
    SimulationPayload,
    StoredSimulationPayload,
)
from app.domain.business_relevance import assess_business_relevance, check_client_onboarding
from app.domain.counterparty_matching import match_counterparty
from app.domain.learning_rules import apply_learning_rules
from app.domain.matching_simulation import simulate_invoice


router = APIRouter()


@router.post("/counterparty/match")
def counterparty_match(payload: CounterpartyMatchPayload) -> dict[str, object]:
    match = match_counterparty(
        [chart_account_from_payload(account) for account in payload.accounts],
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


@router.post("/simulation/invoice")
def simulation_invoice(payload: SimulationPayload) -> dict[str, object]:
    client = client_profile_from_payload(payload.client) if payload.client else None
    counterparty = None
    if payload.chart_accounts:
        counterparty = match_counterparty(
            [chart_account_from_payload(account) for account in payload.chart_accounts],
            tax_ids=tuple(payload.invoice.tax_ids),
            name_hint=payload.invoice.provider_hint,
        )
    result = simulate_invoice(
        parsed_invoice_from_payload(payload.invoice),
        account_selection_from_payload(payload.account_selection),
        client,
        counterparty,
        static_first_classifier_from_payload(payload.ai_policy),
        payload.processing_mode,
        intended_direction=payload.intake_category,
    )
    result = apply_learning_rules(result, [learned_rule_from_payload(rule) for rule in payload.learning_rules])
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
    client_profile = client_profile_from_payload(payload.client)
    onboarding = check_client_onboarding(client_profile)
    store.upsert_client(
        client_id=payload.client.client_id,
        profile=payload.client.model_dump(),
        onboarding={"is_ready": onboarding.is_ready, "missing_fields": list(onboarding.missing_fields)},
    )
    if payload.chart_accounts:
        store.replace_chart_accounts(
            client_id=payload.client.client_id,
            accounts=[asdict(chart_account_from_payload(account)) for account in payload.chart_accounts],
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
        client_profile_from_payload(payload.client),
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
