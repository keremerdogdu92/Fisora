from __future__ import annotations

import unicodedata
from typing import Any, Mapping

from app.domain.ai_classification import (
    AiCandidateStrategy,
    AiClassificationContext,
    AiClassificationRequest,
)
from app.domain.canonical_invoices import CanonicalTaxComponent
from app.domain.chart_accounts import ChartAccount, semantic_roles_for_account


def _search_text(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _tax_component_candidates(accounts: list[ChartAccount]) -> tuple[dict[str, object], ...]:
    hints = ("vergi", "haberlesme", "iletisim", "k.k.e", "kke", "diger cesitli")
    candidates: list[dict[str, object]] = []
    for account in accounts:
        roles = set(semantic_roles_for_account(account))
        name = _search_text(account.account_name)
        if (
            not account.is_detail_account
            or not account.normalized_account_code
            or not roles.intersection({"expense", "non_deductible"})
            or not any(hint in name for hint in hints)
        ):
            continue
        candidates.append(
            {
                "code": account.normalized_account_code,
                "name": account.account_name,
                "reason": "real tenant chart candidate",
                "is_detail_account": True,
                "is_active": True,
            }
        )
    return tuple(sorted(candidates, key=lambda item: str(item["code"])))


def build_tax_component_account_experiment_request(
    *,
    component: CanonicalTaxComponent,
    service_profile: str,
    supplier_title: str,
    accounts: list[ChartAccount],
    client_activity: str,
) -> AiClassificationRequest:
    candidates = _tax_component_candidates(accounts)
    candidate_codes = tuple(str(candidate["code"]) for candidate in candidates)
    raw_line = " | ".join(
        part
        for part in (
            f"Vergi bileşeni: {component.source_label or component.canonical_tax_kind}",
            f"kaynak kodu: {component.source_code}" if component.source_code else "",
            f"oran: {component.rate}" if component.rate else "",
            f"matrah: {component.taxable_amount}" if component.taxable_amount else "",
            f"tutar: {component.tax_amount}" if component.tax_amount else "",
            f"hizmet profili: {service_profile}" if service_profile else "",
        )
        if part
    )
    return AiClassificationRequest(
        raw_line=raw_line,
        supplier_hint=supplier_title,
        allowed_categories=("tax_component", "unknown"),
        max_input_chars=720,
        context=AiClassificationContext(
            client_activity=client_activity,
            accounting_direction="purchase",
            direction_confidence=100,
            direction_evidence=("source_tax_component", "tenant_chart"),
            account_candidates=candidate_codes,
            account_candidate_details=candidates,
            candidate_strategy=AiCandidateStrategy(
                mode="single_stage",
                stage="final_account",
                account_candidate_count=len(candidate_codes),
                counterparty_candidate_count=0,
            ),
            account_candidate_limit=len(candidate_codes),
            account_candidate_details_limit=len(candidates),
            counterparty_candidate_limit=0,
        ),
    )


def validate_tax_component_account_experiment_response(
    *,
    request: AiClassificationRequest,
    response: Mapping[str, Any],
) -> dict[str, object]:
    selected_account_code = str(response.get("suggested_account_code") or "").strip()
    category = str(response.get("category") or "").strip()
    reason = str(response.get("reason") or "").strip()
    try:
        confidence = int(response.get("confidence", -1))
    except (TypeError, ValueError):
        confidence = -1
    errors: list[str] = []
    if category not in request.allowed_categories:
        errors.append("category_not_allowed")
    if selected_account_code not in request.context.account_candidates:
        errors.append("selected_account_not_in_tenant_candidates")
    if not reason:
        errors.append("reason_missing")
    if confidence < 0 or confidence > 100:
        errors.append("confidence_invalid")
    return {
        "accepted": not errors,
        "category": category,
        "confidence": confidence,
        "reason": reason[:500],
        "selected_account_code": selected_account_code,
        "validation_errors": tuple(errors),
    }
