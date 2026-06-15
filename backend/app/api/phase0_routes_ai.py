from __future__ import annotations

from decimal import Decimal
import os

from fastapi import APIRouter, Cookie, Header, HTTPException, Request

from app.api.phase0_context import SESSION_COOKIE_NAME, get_workflow_store, request_user_id, require_client_access
from app.api.phase0_mappers import (
    ai_policy_from_payload,
    ai_provider_from_env,
    benchmark_cases_from_payloads,
    benchmark_response,
    comparison_defaults,
    static_first_classifier_from_payload,
    statement_ai_policy_from_payload,
    statement_line_from_payload,
)
from app.api.rate_limit import enforce_rate_limit
from app.api.phase0_schemas import (
    AiBatchBenchmarkPayload,
    AiModelComparisonPayload,
    AiUsageEventPayload,
    AiUsageSummaryPayload,
    ProductClassificationPayload,
    StatementAiSuggestionsPayload,
)
from app.domain.ai_benchmark import run_ai_batch_benchmark
from app.domain.ai_classification import AiClassificationPolicy
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event, summarize_ai_usage
from app.domain.statement_ai_suggestions import (
    ReplayStatementSuggestionProvider,
    statement_ai_batch_payload,
    suggest_statement_lines,
)


router = APIRouter()


@router.post("/classification/product")
def product_classification(payload: ProductClassificationPayload, request: Request) -> dict[str, object]:
    enforce_rate_limit(scope="ai", key=payload.client_id.strip(), request=request)
    result = static_first_classifier_from_payload(payload.ai_policy).classify(
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
    request: Request,
    x_fisora_user_id: str | None = Header(default=None, alias="X-Fisora-User-Id"),
    x_fisora_session: str | None = Header(default=None, alias="X-Fisora-Session"),
    fisora_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    enforce_rate_limit(scope="ai", key=payload.client_id.strip(), request=request)
    if payload.client_id.strip():
        require_client_access(
            client_id=payload.client_id.strip(),
            user_id=request_user_id(x_fisora_user_id, x_fisora_session, fisora_session),
        )
    replay_provider = (
        ReplayStatementSuggestionProvider(
            list(payload.provider_payloads),
            provider_name=payload.provider_name,
        )
        if payload.provider_payloads
        else None
    )
    provider = replay_provider or (ai_provider_from_env() if payload.ai_policy.enabled else None)
    batch = suggest_statement_lines(
        tuple(statement_line_from_payload(line) for line in payload.lines),
        provider=provider,
        policy=statement_ai_policy_from_payload(payload.ai_policy),
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
def classification_batch_benchmark(payload: AiBatchBenchmarkPayload, request: Request) -> dict[str, object]:
    enforce_rate_limit(scope="ai", request=request)
    provider = None
    if payload.provider_name.strip().lower() in {"openai", "groq"} and not payload.provider_payloads:
        provider = ai_provider_from_env(model=payload.model.strip())
        if provider is None:
            raise HTTPException(
                status_code=400,
                detail=f"{payload.provider_name} provider requires matching FISORA_AI_PROVIDER and API key",
            )
    summary = run_ai_batch_benchmark(
        benchmark_cases_from_payloads(payload.cases),
        policy=ai_policy_from_payload(payload.ai_policy),
        provider=provider,
        provider_payloads=payload.provider_payloads,
        provider_name=payload.provider_name,
    )
    return benchmark_response(summary, model=payload.model.strip())


@router.post("/classification/model-comparison")
def classification_model_comparison(payload: AiModelComparisonPayload, request: Request) -> dict[str, object]:
    enforce_rate_limit(scope="ai", request=request)
    provider_name = (payload.provider_name or os.environ.get("FISORA_AI_PROVIDER", "disabled")).strip().lower()
    if provider_name not in {"openai", "groq"}:
        raise HTTPException(status_code=400, detail="Model comparison requires FISORA_AI_PROVIDER=openai or groq")
    api_key_env = "GROQ_API_KEY" if provider_name == "groq" else "OPENAI_API_KEY"
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{provider_name} comparison requires API key")
    primary_model, comparison_model, provider_class = comparison_defaults(provider_name)
    models = [
        model.strip()
        for model in (payload.models or [primary_model, comparison_model])
        if model.strip()
    ]
    models = list(dict.fromkeys(models))[:3]
    cases = benchmark_cases_from_payloads(payload.cases)
    case_count = len(cases) or 10
    base_policy = ai_policy_from_payload(payload.ai_policy)
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
            provider=provider_class(api_key=api_key, model=model),
            provider_name=provider_name,
        )
        comparisons.append(benchmark_response(summary, model=model))
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
