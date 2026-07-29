from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.chart_accounts import (
    build_chart_semantic_map,
    extract_counterparty_candidates,
    normalize_account_code,
    parse_chart_accounts,
    validate_vat_accounts,
)
from app.domain.ai_benchmark import AiBenchmarkCase, run_ai_batch_benchmark
from app.domain.ai_classification import (
    AiCandidateStrategy,
    AiClassificationContext,
    AiClassificationPolicy,
    AiClassificationRequest,
    AiClassificationResult,
    StaticFirstClassifier,
    merge_semantic_attempt_result,
    merge_semantic_attempts,
    serialize_semantic_decision_attempt,
)
from app.domain.ai_capacity import (
    ai_capacity_payload,
    normalize_cerebras_rate_limit_headers,
    normalize_groq_rate_limit_headers,
    normalize_openrouter_key_payload,
    normalize_tavily_usage_payload,
)
from app.domain.ai_usage import ai_usage_payload, build_ai_usage_event, summarize_ai_usage
from app.domain.openai_provider import ChatCompletionsAccountingProvider, GroqAccountingProvider, OpenAiAccountingProvider
from app.domain.business_relevance import (
    build_activity_profile,
    ClientProfile,
    ProductClassification,
    assess_business_relevance,
    check_client_onboarding,
    classify_product_line,
    decide_export_status,
    normalize_text,
)
from app.domain.chart_accounts import ChartAccount
from app.domain.counterparty_matching import CounterpartyMatch, match_counterparty
from app.domain.export_adapters import get_export_adapter, write_export_file
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.exporters import ZIRVE_MAPPING_COLUMNS, export_universal_journal_csv, export_zirve_trial_csv
from app.domain.invoice_lines import InvoiceLine, extract_invoice_lines_from_text
from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_operations import (
    ReviewTaskDraft,
    run_invoice_operations,
    vat_rate_decimal,
)
from app.domain.learning_intelligence import LearningPolicy, enrich_learning_event
from app.domain.learning_rules import apply_learning_rules, rule_from_event_payload, rule_from_learning_event
from app.domain.natural_language_rule_builder import build_natural_language_rule_candidate
from app.domain.matching_simulation import (
    AccountSelection,
    SimulatedChartRun,
    _vat_account_for_rate,
    private_benchmark_summary,
    infer_accounting_direction,
    simulate_chart_run,
    simulate_invoice as _simulate_invoice,
    simulate_private_matching,
)
from app.domain.invoice_ai_gate import VerifiedRuleAuthorityV1, invoice_ai_gate
from app.domain.matching_simulation import build_review_ui_payload, write_simulation_csv
from app.domain.matching_simulation import select_accounts
from app.domain.journal_entries import (
    build_bank_payment_entry,
    build_mixed_vat_purchase_entry,
    build_purchase_entry,
    build_sales_entry,
    money,
)
from app.domain.pdf_invoices import (
    ParsedInvoice,
    build_route,
    extract_vat_rates,
    parse_amount,
    parse_pdf_invoice,
    resolve_payable_total,
)
from app.domain.pdf_invoice_boundaries import PdfPageText
from app.domain.production_readiness import production_readiness_payload
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.domain.workspace_review_updates import apply_review_decision_to_document
from app.domain.statement_ai_suggestions import StatementAiSuggestionPolicy, StatementAiSuggestionRequest, suggest_statement_lines
from app.domain.statement_lines import StatementLine
from app.domain.vat_split_learning import build_vat_split_review_record, vat_split_review_payload
from app.domain.vat_splits import VatSplitLine
from app.domain.workspace_exports import build_workspace_export_package, export_candidates_from_workspace


class FakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[AiClassificationRequest] = []

    def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class SequentialFakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[AiClassificationRequest] = []

    def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.responses.pop(0)


class AcceptedSemanticAccountClassifier:
    policy = AiClassificationPolicy(enabled=True, static_confidence_threshold=101)

    def __init__(self, account_code: str, *, category: str = "", line_account_codes: tuple[str, ...] = ()) -> None:
        self.account_code = account_code
        self.category = category
        self.line_account_codes = line_account_codes

    def classify(
        self,
        raw_line: str,
        *,
        supplier_hint: str = "",
        context: AiClassificationContext | None = None,
    ) -> AiClassificationResult:
        static = classify_product_line(raw_line, supplier_hint)
        classification = (
            ProductClassification(
                raw_line=raw_line,
                category=self.category,
                confidence=95,
                evidence=("test:accepted_semantic_decision",),
            )
            if self.category
            else static
        )
        effective_context = context or AiClassificationContext()
        canonical_ids = tuple(
            str(line.get("canonical_line_id") or "")
            for line in effective_context.canonical_lines
            if str(line.get("canonical_line_id") or "")
        )
        line_codes = self.line_account_codes or tuple(self.account_code for _ in canonical_ids)
        line_decisions = tuple(
            {
                "canonical_line_id": line_id,
                "suggested_account_code": code,
                "product_identity": self.category or "mechanical fixture line",
                "reason": "Explicit accepted semantic fixture decision.",
                "needs_research": False,
                "research_query": "",
            }
            for line_id, code in zip(canonical_ids, line_codes)
        ) if len(canonical_ids) > 1 else ()
        validated_response = {
            "suggested_account_code": self.account_code,
            "needs_research": False,
            "line_decisions": list(line_decisions),
        }
        attempt = serialize_semantic_decision_attempt(
            attempt_id="accepted-semantic-fixture",
            stage="initial_account_decision",
            canonical_line_ids=canonical_ids,
            prompt_version="test-semantic-v1",
            provider="accepted_semantic_fixture",
            model="deterministic-test-fixture",
            candidate_account_codes=effective_context.account_candidates,
            candidate_counterparty_codes=effective_context.counterparty_candidates,
            validated_response=validated_response,
            validation_errors=(),
            accepted=True,
        )
        return AiClassificationResult(
            classification=classification,
            ai_used=True,
            provider="accepted_semantic_fixture",
            provider_reason="Test fixture supplies an accepted semantic account decision.",
            suggested_account_code=self.account_code,
            account_reason="Accepted semantic test decision.",
            accepted_semantic_attempt_id="accepted-semantic-fixture",
            candidate_strategy=effective_context.candidate_strategy,
            semantic_attempts=(attempt,),
            line_decisions=line_decisions,
        )


def _accepted_semantic_fixture_account(
    invoice: ParsedInvoice,
    selection: AccountSelection,
    client_profile: ClientProfile | None,
    classification_override: ProductClassification | None,
    intended_direction: str | None,
) -> str:
    direction, _, _ = infer_accounting_direction(
        invoice,
        client_profile,
        intended_direction=intended_direction,
    )
    raw_line = " ".join(str(item or "") for item in invoice.line_items).strip()
    if direction == "sales":
        normalized_line = normalize_text(raw_line)
        if len(tuple(invoice.vat_rates)) > 1:
            return selection.revenue_account
        if tuple(invoice.vat_rates) == ("0",) or any(
            token in normalized_line for token in ("isitme cihazi", "rexton")
        ):
            return selection.zero_vat_revenue_account
        return selection.revenue_account
    relevance = (
        assess_business_relevance(
            raw_line,
            client_profile,
            supplier_hint=invoice.provider_hint,
            classification=classification_override,
        )
        if client_profile
        else None
    )
    if relevance and relevance.account_treatment == "non_deductible_review":
        return selection.non_deductible_account
    if relevance and relevance.account_treatment == "stock_or_cogs":
        normalized_line = normalize_text(raw_line)
        line_tokens = {token for token in normalized_line.split() if len(token) >= 3}
        stock_candidates = selection.account_candidates.get("purchase_stock", ())
        scored_stock = sorted(
            (
                (
                    sum(token in normalize_text(str(candidate.get("name") or "")) for token in line_tokens),
                    str(candidate.get("code") or ""),
                )
                for candidate in stock_candidates
            ),
            reverse=True,
        )
        if scored_stock and scored_stock[0][0] > 0:
            return scored_stock[0][1]
        if selection.expense_account.startswith("153"):
            return selection.expense_account
        return selection.stock_account
    normalized_line = normalize_text(raw_line)
    line_tokens = {token for token in normalized_line.split() if len(token) >= 4}
    expense_candidates = selection.account_candidates.get("purchase_expense", ())
    if expense_candidates and line_tokens:
        scored = sorted(
            (
                (
                    sum(token in normalize_text(str(candidate.get("name") or "")) for token in line_tokens),
                    str(candidate.get("code") or ""),
                )
                for candidate in expense_candidates
            ),
            reverse=True,
        )
        if scored and scored[0][0] > 0:
            return scored[0][1]
    return selection.expense_account


def _mechanical_canonical_invoice(invoice: ParsedInvoice):
    if invoice.canonical_invoice is not None:
        return invoice.canonical_invoice
    descriptions = tuple(invoice.line_items) or ("Mechanical accounting fixture",)
    net_total = Decimal(invoice.goods_services_total or "0")
    tax_total = Decimal(invoice.vat_total or "0")
    gross_total = Decimal(invoice.payable_total or invoice.tax_inclusive_total or "0")
    rates = tuple(Decimal(str(rate or "0")) for rate in invoice.vat_rates)
    specs: list[tuple[str, str, str, str, str]] = []
    vat_splits = tuple(getattr(invoice, "vat_split_lines", ()) or ())
    if vat_splits:
        for index, split in enumerate(vat_splits):
            net = Decimal(str(split.taxable_amount))
            tax = Decimal(str(split.tax_amount))
            description = descriptions[index] if index < len(descriptions) else descriptions[-1]
            specs.append((description, f"{net:.2f}", str(split.rate), f"{tax:.2f}", f"{net + tax:.2f}"))
    elif len(descriptions) > 1 and len(rates) == 2 and rates[0] != rates[1]:
        low, high = rates[0] / Decimal("100"), rates[1] / Decimal("100")
        second_net = ((tax_total - low * net_total) / (high - low)).quantize(Decimal("0.01"))
        first_net = (net_total - second_net).quantize(Decimal("0.01"))
        nets = (first_net, second_net)
        taxes = ((first_net * low).quantize(Decimal("0.01")), (second_net * high).quantize(Decimal("0.01")))
        for index, (net, tax, rate) in enumerate(zip(nets, taxes, rates)):
            description = descriptions[index] if index < len(descriptions) else descriptions[-1]
            specs.append((description, f"{net:.2f}", str(rate), f"{tax:.2f}", f"{net + tax:.2f}"))
    else:
        rate = str(rates[0]) if len(rates) == 1 else "0"
        specs.append((" / ".join(descriptions), f"{net_total:.2f}", rate, f"{tax_total:.2f}", f"{gross_total:.2f}"))
    return _task3_canonical_invoice(*specs)


def simulate_mechanical_invoice(
    invoice: ParsedInvoice,
    selection: AccountSelection,
    client_profile: ClientProfile | None = None,
    counterparty_match: CounterpartyMatch | None = None,
    product_classifier: object | None = None,
    processing_mode: str = "controlled_automation",
    intended_direction: str | None = None,
    classification_override: ProductClassification | None = None,
    verified_rule_bindings: tuple[dict[str, object], ...] = (),
    verified_rule_authorities: tuple[VerifiedRuleAuthorityV1, ...] = (),
):
    fixture_invoice = (
        invoice
        if invoice.canonical_invoice is not None or not invoice.line_items
        else replace(invoice, canonical_invoice=_mechanical_canonical_invoice(invoice))
    )
    fixture_selection = selection
    classifier = product_classifier
    if classifier is None and not verified_rule_bindings:
        canonical = _mechanical_canonical_invoice(fixture_invoice)
        base_account = _accepted_semantic_fixture_account(
            fixture_invoice,
            selection,
            client_profile,
            classification_override,
            intended_direction,
        )
        direction, _, _ = infer_accounting_direction(
            fixture_invoice,
            client_profile,
            intended_direction=intended_direction,
        )
        candidate_group = "sales_revenue" if direction == "sales" else (
            "purchase_stock" if base_account.startswith("153") else
            "non_deductible" if base_account.startswith("689") else
            "purchase_expense"
        )
        candidate_groups = dict(selection.account_candidates)
        current_group = tuple(candidate_groups.get(candidate_group, ()))
        if base_account and base_account not in {str(item.get("code") or "") for item in current_group}:
            candidate_groups[candidate_group] = (*current_group, {
                "code": base_account,
                "name": "Explicit mechanical semantic fixture account",
                "reason": "test fixture",
                "is_detail_account": True,
                "is_active": True,
            })
        if direction == "sales" and any(
            "isitme" in normalize_text(str(line.description or ""))
            for line in canonical.line_items
        ):
            sales_candidates = tuple(candidate_groups.get("sales_revenue", ()))
            if selection.zero_vat_revenue_account not in {str(item.get("code") or "") for item in sales_candidates}:
                candidate_groups["sales_revenue"] = (*sales_candidates, {
                    "code": selection.zero_vat_revenue_account,
                    "name": "Explicit zero VAT semantic fixture account",
                    "reason": "test fixture",
                    "is_detail_account": True,
                    "is_active": True,
                })
        fixture_selection = replace(selection, account_candidates=candidate_groups)
        line_codes: tuple[str, ...] = ()
        if len(canonical.line_items) > 1 and direction == "sales":
            line_codes = tuple(
                selection.zero_vat_revenue_account
                if "isitme" in normalize_text(str(line.description or ""))
                else _vat_account_for_rate(
                    fixture_selection.account_candidates.get("sales_revenue"),
                    rate=Decimal(str(line.vat_rate or "0")) / Decimal("100"),
                    fallback=selection.revenue_account,
                )
                for line in canonical.line_items
            )
        classifier = AcceptedSemanticAccountClassifier(
            base_account,
            line_account_codes=line_codes,
        )
    return _simulate_invoice(
        fixture_invoice,
        fixture_selection,
        client_profile,
        counterparty_match,
        classifier,
        processing_mode,
        intended_direction,
        classification_override,
        verified_rule_bindings,
        verified_rule_authorities,
    )


simulate_invoice = _simulate_invoice


def _task3_canonical_invoice(
    *lines: tuple[str, str, str, str, str],
):
    from app.domain.canonical_invoices import (
        CanonicalInvoice,
        CanonicalInvoiceLine,
        CanonicalInvoiceTotals,
        CanonicalVatSummaryLine,
        with_validation,
    )

    canonical_lines = tuple(
        CanonicalInvoiceLine(
            description=description,
            source_position=f"test:line:{index}",
            taxable_amount=taxable,
            vat_rate=vat_rate,
            tax_amount=tax,
            gross_amount=gross,
        )
        for index, (description, taxable, vat_rate, tax, gross) in enumerate(lines, start=1)
    )
    taxable_total = sum((Decimal(line[1]) for line in lines), Decimal("0.00"))
    tax_total = sum((Decimal(line[3]) for line in lines), Decimal("0.00"))
    gross_total = sum((Decimal(line[4]) for line in lines), Decimal("0.00"))
    vat_summary = tuple(
        CanonicalVatSummaryLine(rate=rate, taxable_amount=taxable, tax_amount=tax)
        for _, taxable, rate, tax, _ in lines
    )
    return with_validation(
        CanonicalInvoice(
            source="test",
            line_items=canonical_lines,
            vat_summary=vat_summary,
            totals=CanonicalInvoiceTotals(
                goods_services_total=f"{taxable_total:.2f}",
                vat_total=f"{tax_total:.2f}",
                special_tax_total="0.00",
                tax_inclusive_total=f"{gross_total:.2f}",
                payable_total=f"{gross_total:.2f}",
            ),
        )
    )


def _task3_profile() -> ClientProfile:
    return ClientProfile(
        client_id="client-task3",
        title="Task 3 Isitme Merkezi",
        tax_id="1234567890",
        activity_description="Isitme cihazi satis ve servis",
        workplace_addresses=("Istanbul",),
        has_chart_accounts=True,
    )


def _task3_verified_authority(
    canonical_line_id: str,
    account_code: str,
    *,
    direction: str = "purchase",
    invoice_mode: str = "ordinary",
    semantic_role: str = "expense",
    index: int = 1,
    client_id: str = "client-task3",
) -> VerifiedRuleAuthorityV1:
    return VerifiedRuleAuthorityV1(
        schema_version="v1",
        client_id=client_id,
        rule_id=f"rule-task3-{index}",
        rule_version="1",
        activation_event_id=f"activation-task3-{index}",
        source_review_decision_id=f"review-task3-{index}",
        confirmed_actor_id="accountant-task3",
        canonical_line_id=canonical_line_id,
        direction=direction,  # type: ignore[arg-type]
        invoice_mode=invoice_mode,  # type: ignore[arg-type]
        semantic_role=semantic_role,
        account_code=account_code,
    )


class FakeStatementSuggestionProvider:
    provider_name = "fake_statement_llm"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def suggest_statement_line(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return self.responses.pop(0)


def _write_recoverable_backup_receipts(backup_path: Path) -> str:
    backup_path.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    generation_name = f"fisora-backup-{stamp}.tar.gz.age"
    (backup_path / generation_name).write_bytes(b"encrypted")
    (backup_path / f"backup-success-{stamp}.json").write_text(
        json.dumps(
            {
                "latest_attempt_at": now.isoformat(),
                "latest_success_at": now.isoformat(),
                "generation_file": generation_name,
                "generation_digest": "abc123",
                "offhost_copy_status": "complete",
            }
        ),
        encoding="utf-8",
    )
    (backup_path / f"restore-verified-{stamp}.json").write_text(
        json.dumps(
            {
                "verified_at": now.isoformat(),
                "status": "verified",
                "generation_file": generation_name,
                "generation_digest": "abc123",
            }
        ),
        encoding="utf-8",
    )
    return generation_name


class Phase0DomainTests(unittest.TestCase):
    def test_ai_usage_summary_tracks_ten_dollar_cap(self) -> None:
        events = [
            ai_usage_payload(
                build_ai_usage_event(
                    client_id="client-1",
                    provider="openai",
                    operation="worker_ai_assisted_draft",
                    input_chars=420,
                    ai_used=True,
                )
            )
        ]

        summary = summarize_ai_usage(events, monthly_cap_usd=Decimal("10"))

        self.assertEqual(summary["monthly_cap_usd"], "10.00")
        self.assertEqual(summary["estimated_total_cost_usd"], "0.000420")
        self.assertEqual(summary["remaining_cap_usd"], "9.999580")
        self.assertFalse(summary["cap_exceeded"])

    def test_ai_usage_summary_tracks_groq_free_tier_as_zero_cost(self) -> None:
        events = [
            ai_usage_payload(
                build_ai_usage_event(
                    client_id="client-1",
                    provider="groq",
                    operation="worker_ai_assisted_draft",
                    input_chars=1200,
                    ai_used=True,
                )
            )
        ]

        summary = summarize_ai_usage(events, monthly_cap_usd=Decimal("0.01"))

        self.assertEqual(summary["estimated_total_cost_usd"], "0.000000")
        self.assertEqual(summary["remaining_cap_usd"], "0.010000")
        self.assertFalse(summary["cap_exceeded"])

    def test_ai_capacity_normalizes_provider_limits_without_public_plan_language(self) -> None:
        groq = normalize_groq_rate_limit_headers(
            {
                "x-ratelimit-limit-requests": "1000",
                "x-ratelimit-remaining-requests": "742",
                "x-ratelimit-limit-tokens": "8000",
                "x-ratelimit-remaining-tokens": "6500",
                "x-ratelimit-reset-requests": "3h12m",
                "x-ratelimit-reset-tokens": "12s",
            }
        )
        cerebras = normalize_cerebras_rate_limit_headers(
            {
                "x-ratelimit-limit-requests-day": "100",
                "x-ratelimit-remaining-requests-day": "81",
                "x-ratelimit-limit-tokens-minute": "30000",
                "x-ratelimit-remaining-tokens-minute": "24000",
                "x-ratelimit-reset-requests-day": "500",
                "x-ratelimit-reset-tokens-minute": "10",
            }
        )
        openrouter = normalize_openrouter_key_payload(
            {
                "data": {
                    "limit": 100,
                    "limit_remaining": 74.5,
                    "usage_daily": 25.5,
                    "usage_monthly": 25.5,
                    "is_free_tier": True,
                    "label": "sk-or-secret",
                }
            }
        )

        self.assertEqual(groq["daily_requests"]["remaining"], 742)
        self.assertEqual(groq["daily_requests"]["limit"], 1000)
        self.assertEqual(groq["minute_tokens"]["remaining"], 6500)
        self.assertEqual(cerebras["daily_requests"]["remaining"], 81)
        self.assertEqual(cerebras["minute_tokens"]["limit"], 30000)
        self.assertEqual(openrouter["credit"]["remaining"], "74.500000")
        self.assertNotIn("is_free_tier", openrouter)
        self.assertNotIn("label", openrouter)
        self.assertNotIn("secret", str(openrouter).lower())

    def test_ai_capacity_payload_reports_research_agent_configuration_without_keys(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_AI_PROVIDER_CHAIN": "groq,openrouter,cerebras",
                "GROQ_API_KEY": "gsk-secret",
                "OPENROUTER_API_KEY": "or-secret",
                "CEREBRAS_API_KEY": "csk-secret",
                "FISORA_RESEARCH_ENABLED": "true",
                "OPENAI_API_KEY": "sk-secret",
                "FISORA_RESEARCH_MODEL": "gpt-5.4-mini",
                "FISORA_RESEARCH_MAX_PER_DOCUMENT": "1",
            },
            provider_snapshots={
                "groq": normalize_groq_rate_limit_headers(
                    {
                        "x-ratelimit-limit-requests": "1000",
                        "x-ratelimit-remaining-requests": "742",
                    }
                )
            },
        )

        labels = [agent["label"] for agent in payload["agents"]]
        research = next(agent for agent in payload["agents"] if agent["kind"] == "research")
        self.assertEqual(labels, ["Belge ajanı 1", "Belge ajanı 2", "Belge ajanı 3", "Araştırma ajanı"])
        self.assertTrue(research["configured"])
        self.assertEqual(research["status"], "ready")
        self.assertEqual(payload["totals"]["document_queries"], 92)
        self.assertIsNone(payload["totals"]["internet_researches"])
        self.assertEqual(payload["estimate"]["confidence"], "partial")
        public_text = str(payload).lower()
        self.assertNotIn("gsk-secret", public_text)
        self.assertNotIn("or-secret", public_text)
        self.assertNotIn("csk-secret", public_text)
        self.assertNotIn("sk-secret", public_text)
        self.assertNotIn("free", public_text)
        self.assertNotIn("ücretsiz", public_text)

    def test_ai_capacity_reports_nvidia_without_secret(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_AI_PROVIDER_CHAIN": "nvidia,groq",
                "FISORA_NVIDIA_MODEL": "openai/gpt-oss-120b",
                "NVIDIA_API_KEY": "nvapi-test-secret",
                "GROQ_API_KEY": "gsk-test",
            }
        )

        self.assertTrue(payload["agents"][0]["configured"])
        self.assertEqual(payload["agents"][0]["model"], "openai/gpt-oss-120b")
        self.assertNotIn("nvapi-test-secret", str(payload))

    def test_ai_capacity_reports_cloudflare_and_sambanova_without_secrets(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_AI_PROVIDER_CHAIN": "cloudflare,sambanova",
                "FISORA_CLOUDFLARE_MODEL": "@cf/openai/gpt-oss-120b",
                "FISORA_SAMBANOVA_MODEL": "gpt-oss-120b",
                "CLOUDFLARE_API_TOKEN": "cfai-private-123456",
                "CLOUDFLARE_ACCOUNT_ID": "account-private-123456",
                "SAMBANOVA_API_KEY": "snapi-private-123456",
            }
        )

        document_agents = [agent for agent in payload["agents"] if agent["kind"] == "document"]
        self.assertEqual(len(document_agents), 2)
        self.assertTrue(all(agent["configured"] for agent in document_agents))
        self.assertEqual(document_agents[0]["model"], "@cf/openai/gpt-oss-120b")
        self.assertEqual(document_agents[1]["model"], "gpt-oss-120b")
        self.assertNotIn("cfai-private-123456", str(payload))
        self.assertNotIn("account-private-123456", str(payload))
        self.assertNotIn("snapi-private-123456", str(payload))

    def test_ai_capacity_reserves_retry_budget_for_documents(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_AI_PROVIDER_CHAIN": "groq",
                "GROQ_API_KEY": "gsk-secret",
                "FISORA_AI_MAX_PROVIDER_CALLS": "3",
                "FISORA_AI_STATEMENT_MAX_PROVIDER_CALLS": "3",
            },
            provider_snapshots={
                "groq": normalize_groq_rate_limit_headers(
                    {"x-ratelimit-remaining-requests": "742"}
                )
            },
        )

        self.assertEqual(payload["totals"]["document_queries"], 92)
        self.assertEqual(payload["estimate"]["estimate_mode"], "conservative")
        self.assertEqual(payload["estimate"]["reserve_percent"], 25)
        self.assertEqual(payload["estimate"]["retry_multiplier"], 2)

    def test_tavily_usage_normalization_and_conservative_research_capacity(self) -> None:
        snapshot = normalize_tavily_usage_payload(
            {
                "key": {"usage": 150, "limit": 1000},
                "account": {"plan_usage": 500, "plan_limit": 15000},
            }
        )
        payload = ai_capacity_payload(
            env={
                "FISORA_RESEARCH_ENABLED": "true",
                "FISORA_RESEARCH_PROVIDER": "tavily",
                "TAVILY_API_KEY": "tvly-secret",
            },
            provider_snapshots={"tavily": snapshot},
        )

        self.assertEqual(snapshot["credit"]["remaining"], 850)
        self.assertEqual(payload["totals"]["internet_researches"], 318)
        self.assertEqual(payload["estimate"]["confidence"], "live")

    def test_research_capacity_is_unknown_without_a_usage_snapshot(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_RESEARCH_ENABLED": "true",
                "FISORA_RESEARCH_PROVIDER": "tavily",
                "TAVILY_API_KEY": "tvly-secret",
            },
            provider_snapshots={},
        )

        research = next(agent for agent in payload["agents"] if agent["kind"] == "research")
        self.assertIsNone(research["estimates"]["internet_researches"])
        self.assertIsNone(payload["totals"]["internet_researches"])
        self.assertEqual(payload["estimate"]["confidence"], "not_available")

    def test_unconfigured_document_provider_snapshot_does_not_inflate_capacity(self) -> None:
        payload = ai_capacity_payload(
            env={"FISORA_AI_PROVIDER_CHAIN": "groq"},
            provider_snapshots={
                "groq": normalize_groq_rate_limit_headers(
                    {"x-ratelimit-remaining-requests": "742"}
                )
            },
        )

        self.assertIsNone(payload["totals"]["document_queries"])
        self.assertEqual(payload["estimate"]["confidence"], "not_available")

    def test_ai_capacity_payload_does_not_mark_openrouter_key_as_research_ready(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_RESEARCH_ENABLED": "true",
                "OPENAI_API_KEY": "sk-or-v1-not-openai",
                "FISORA_RESEARCH_MODEL": "gpt-5.4-mini",
            },
            provider_snapshots={},
        )

        research = next(agent for agent in payload["agents"] if agent["kind"] == "research")
        self.assertFalse(research["configured"])
        self.assertEqual(research["status"], "configuration_error")
        self.assertEqual(payload["totals"]["internet_researches"], 0)
        self.assertNotIn("sk-or-v1-not-openai", str(payload))

    def test_ai_capacity_payload_marks_tavily_research_ready_without_openai_key(self) -> None:
        payload = ai_capacity_payload(
            env={
                "FISORA_RESEARCH_ENABLED": "true",
                "FISORA_RESEARCH_PROVIDER": "tavily",
                "TAVILY_API_KEY": "tvly-secret",
                "FISORA_RESEARCH_MAX_PER_DOCUMENT": "2",
            },
            provider_snapshots={},
        )

        research = next(agent for agent in payload["agents"] if agent["kind"] == "research")
        self.assertTrue(research["configured"])
        self.assertEqual(research["status"], "ready")
        self.assertIsNone(payload["totals"]["internet_researches"])
        self.assertEqual(payload["estimate"]["confidence"], "not_available")
        self.assertNotIn("tvly-secret", str(payload))

    def test_backup_disabled_is_not_required_before_real_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=base / "backups",
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://test",
                    "FISORA_BACKUP_MODE": "disabled",
                },
            )

        self.assertEqual(payload["backup"]["status"], "not_required")
        self.assertFalse(payload["backup"]["required"])
        self.assertNotIn("backup_missing", payload["warnings"])
        self.assertNotIn("backup_available", payload["pilot_checks"])

    def test_real_data_pilot_requires_scheduled_backup_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=base / "backups",
                env={
                    "FISORA_AUTH_MODE": "session_required",
                    "FISORA_SESSION_COOKIE_SECURE": "true",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://test",
                    "FISORA_REAL_DATA_PILOT_ENABLED": "true",
                    "FISORA_REAL_DATA_ACCESS_MODE": "restricted_network",
                    "FISORA_BACKUP_MODE": "disabled",
                },
            )

        self.assertFalse(payload["real_data_pilot"]["allowed"])
        self.assertIn("scheduled_backup_mode", payload["real_data_pilot"]["blocking"])

    def test_scheduled_backup_requires_fresh_receipt_and_restore_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "session_required",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://test",
                    "FISORA_BACKUP_MODE": "scheduled",
                },
            )

        self.assertEqual(payload["backup"]["status"], "missing")
        self.assertIn("backup_generation_missing", payload["backup"]["blocking"])
        self.assertIn("restore_verification_missing", payload["backup"]["blocking"])

    def test_scheduled_backup_is_recoverable_with_fresh_generation_and_restore_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            generation_name = _write_recoverable_backup_receipts(backup_path)
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "session_required",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://test",
                    "FISORA_BACKUP_MODE": "scheduled",
                    "FISORA_BACKUP_OFFHOST_ATTESTED": "true",
                },
            )

        self.assertTrue(payload["backup"]["ok"])
        self.assertEqual(payload["backup"]["status"], "recoverable")
        self.assertEqual(payload["backup"]["latest_encrypted_generation"], generation_name)
        self.assertTrue(payload["qnb_pilot"]["checks"]["recoverable_backup"])

    def test_scheduled_backup_requires_offhost_failure_domain_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            _write_recoverable_backup_receipts(backup_path)
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={"FISORA_BACKUP_MODE": "scheduled"},
            )

        self.assertFalse(payload["backup"]["ok"])
        self.assertIn("offhost_target_unattested", payload["backup"]["blocking"])

    def test_scheduled_backup_rejects_stale_generation_and_restore_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            stale = datetime.now(UTC).replace(microsecond=0) - timedelta(days=31)
            generation_name = "fisora-backup-20260601T100000Z.tar.gz.age"
            (backup_path / generation_name).write_bytes(b"encrypted")
            (backup_path / "backup-success-20260601T100000Z.json").write_text(
                json.dumps(
                    {
                        "latest_attempt_at": stale.isoformat(),
                        "latest_success_at": stale.isoformat(),
                        "generation_file": generation_name,
                        "generation_digest": "abc123",
                        "offhost_copy_status": "complete",
                    }
                ),
                encoding="utf-8",
            )
            (backup_path / "restore-verified-20260601T100000Z.json").write_text(
                json.dumps({"verified_at": stale.isoformat(), "status": "verified"}),
                encoding="utf-8",
            )
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={"FISORA_BACKUP_MODE": "scheduled"},
            )

        self.assertFalse(payload["backup"]["ok"])
        self.assertIn("backup_generation_stale", payload["backup"]["blocking"])
        self.assertIn("restore_verification_stale", payload["backup"]["blocking"])

    def test_scheduled_backup_rejects_restore_receipt_for_another_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            _write_recoverable_backup_receipts(backup_path)
            restore_receipt = next(backup_path.glob("restore-verified-*.json"))
            receipt = json.loads(restore_receipt.read_text(encoding="utf-8"))
            receipt["generation_digest"] = "different"
            restore_receipt.write_text(json.dumps(receipt), encoding="utf-8")
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={"FISORA_BACKUP_MODE": "scheduled"},
            )

        self.assertFalse(payload["backup"]["ok"])
        self.assertIn("restore_generation_mismatch", payload["backup"]["blocking"])

    def test_unknown_backup_mode_is_a_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=base / "backups",
                env={"FISORA_BACKUP_MODE": "sometimes"},
            )

        self.assertEqual(payload["backup"]["status"], "failing")
        self.assertEqual(payload["backup"]["service_state"], "configuration_error")
        self.assertIn("backup_mode_invalid", payload["backup"]["blocking"])
        self.assertIn("backup_mode_invalid", payload["warnings"])

    def test_production_readiness_requires_openai_key_when_openai_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            _write_recoverable_backup_receipts(backup_path)

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "openai",
                    "FISORA_AI_MODEL": "gpt-5.4-mini",
                },
            )

        self.assertFalse(payload["checks"]["ai_provider_configured"])
        self.assertIn("ai_provider_configured", payload["blocking"])
        self.assertIn("ai_openai_key_missing", payload["warnings"])

    def test_production_readiness_accepts_groq_key_when_groq_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "groq",
                    "FISORA_AI_MODEL": "openai/gpt-oss-20b",
                    "GROQ_API_KEY": "gsk-test",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_provider"], "groq")
        self.assertTrue(payload["ai_groq_key_present"])
        self.assertNotIn("ai_groq_key_missing", payload["warnings"])

    def test_production_readiness_uses_groq_default_model_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_model"], "openai/gpt-oss-20b")
        self.assertNotIn("ai_model_missing", payload["warnings"])

    def test_production_readiness_accepts_three_provider_ai_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER_CHAIN": "groq,openrouter,cerebras",
                    "GROQ_API_KEY": "gsk-test",
                    "OPENROUTER_API_KEY": "or-test",
                    "CEREBRAS_API_KEY": "csk-test",
                    "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
                    "FISORA_OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
                    "FISORA_CEREBRAS_MODEL": "gpt-oss-120b",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_provider"], "groq>openrouter>cerebras")
        self.assertEqual(payload["ai_provider_chain"], ["groq", "openrouter", "cerebras"])
        self.assertEqual(payload["ai_model"], "openai/gpt-oss-20b > openai/gpt-oss-20b:free > gpt-oss-120b")
        self.assertTrue(payload["ai_openrouter_key_present"])
        self.assertTrue(payload["ai_cerebras_key_present"])
        self.assertNotIn("ai_openrouter_key_missing", payload["warnings"])
        self.assertNotIn("ai_cerebras_key_missing", payload["warnings"])

    def test_production_readiness_accepts_nvidia_first_ai_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER": "nvidia",
                    "FISORA_AI_PROVIDER_CHAIN": "nvidia,groq,openrouter,cerebras",
                    "FISORA_NVIDIA_MODEL": "openai/gpt-oss-120b",
                    "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
                    "FISORA_OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
                    "FISORA_CEREBRAS_MODEL": "gpt-oss-120b",
                    "NVIDIA_API_KEY": "nvapi-test-secret",
                    "GROQ_API_KEY": "gsk-test",
                    "OPENROUTER_API_KEY": "or-test",
                    "CEREBRAS_API_KEY": "csk-test",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_provider"], "nvidia>groq>openrouter>cerebras")
        self.assertEqual(payload["ai_provider_chain"][0], "nvidia")
        self.assertTrue(payload["ai_nvidia_key_present"])
        self.assertNotIn("ai_nvidia_key_missing", payload["warnings"])

    def test_production_readiness_accepts_cloudflare_and_sambanova_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER_CHAIN": "cloudflare,sambanova",
                    "FISORA_CLOUDFLARE_MODEL": "@cf/openai/gpt-oss-120b",
                    "FISORA_SAMBANOVA_MODEL": "gpt-oss-120b",
                    "CLOUDFLARE_API_TOKEN": "cfai-test-token",
                    "CLOUDFLARE_ACCOUNT_ID": "account-test-123",
                    "SAMBANOVA_API_KEY": "snapi-test-token",
                },
            )

        self.assertTrue(payload["checks"]["ai_provider_configured"])
        self.assertEqual(payload["ai_provider"], "cloudflare>sambanova")
        self.assertTrue(payload["ai_cloudflare_key_present"])
        self.assertTrue(payload["ai_cloudflare_account_id_present"])
        self.assertTrue(payload["ai_sambanova_key_present"])

    def test_production_readiness_requires_cloudflare_account_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER_CHAIN": "cloudflare",
                    "CLOUDFLARE_API_TOKEN": "cfai-test-token",
                },
            )

        self.assertFalse(payload["checks"]["ai_provider_configured"])
        self.assertIn("ai_cloudflare_account_id_missing", payload["warnings"])

    def test_production_readiness_warns_when_chain_provider_key_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_AI_PROVIDER_CHAIN": "groq,openrouter,cerebras",
                    "GROQ_API_KEY": "gsk-test",
                    "OPENROUTER_API_KEY": "or-test",
                    "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
                    "FISORA_OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
                    "FISORA_CEREBRAS_MODEL": "gpt-oss-120b",
                },
            )

        self.assertFalse(payload["checks"]["ai_provider_configured"])
        self.assertIn("ai_provider_configured", payload["blocking"])
        self.assertIn("ai_cerebras_key_missing", payload["warnings"])

    def test_pilot_sellable_allows_closed_pilot_without_verified_zirve_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://fisora:test@localhost:5432/fisora",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                },
            )

        self.assertTrue(payload["ready"])
        self.assertTrue(payload["pilot_sellable"])
        self.assertFalse(payload["production_ready"])
        self.assertEqual(payload["commercial_readiness"]["status"], "pilot_sellable")
        self.assertEqual(payload["commercial_readiness"]["primary_offer"], "accountant_reviewed_controlled_export")
        self.assertIn("zirve_verified_adapter_missing", payload["warnings"])
        self.assertNotIn("zirve_verified_adapter_available", payload["pilot_blocking"])

    def test_real_data_pilot_blocks_mock_auth_even_when_pilot_sellable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://fisora:test@localhost:5432/fisora",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                    "FISORA_REAL_DATA_PILOT_ENABLED": "true",
                    "FISORA_REAL_DATA_ACCESS_MODE": "restricted_network",
                    "FISORA_BACKUP_MODE": "scheduled",
                    "FISORA_BACKUP_OFFHOST_ATTESTED": "true",
                },
            )

        self.assertTrue(payload["pilot_sellable"])
        self.assertFalse(payload["real_data_pilot"]["allowed"])
        self.assertIn("session_required_active", payload["real_data_pilot"]["blocking"])

    def test_real_data_pilot_allows_restricted_session_backed_live_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            _write_recoverable_backup_receipts(backup_path)

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "session_required",
                    "FISORA_SESSION_COOKIE_SECURE": "true",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://fisora:test@localhost:5432/fisora",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                    "FISORA_REAL_DATA_PILOT_ENABLED": "true",
                    "FISORA_REAL_DATA_ACCESS_MODE": "restricted_network",
                    "FISORA_BACKUP_MODE": "scheduled",
                    "FISORA_BACKUP_OFFHOST_ATTESTED": "true",
                },
            )

        self.assertTrue(payload["real_data_pilot"]["allowed"])
        self.assertEqual(payload["real_data_pilot"]["status"], "ready_for_restricted_live_pilot")
        self.assertEqual(payload["real_data_pilot"]["blocking"], [])

    def test_production_readiness_reports_mapping_adapter_and_security_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_required",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://fisora:test@localhost:5432/fisora",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                    "FISORA_RATE_LIMIT_ENABLED": "false",
                },
            )

        self.assertTrue(payload["checks"]["zirve_mapping_adapter_available"])
        self.assertFalse(payload["checks"]["session_required_active"])
        self.assertFalse(payload["checks"]["rate_limit_configured"])
        self.assertTrue(payload["pilot_sellable"])
        self.assertFalse(payload["production_ready"])
        self.assertIn("session_required_missing", payload["warnings"])
        self.assertIn("rate_limit_missing", payload["warnings"])
        self.assertIn("zirve_field_test_pending", payload["warnings"])

    def test_qnb_pilot_readiness_requires_real_adapter_key_erp_backup_and_restricted_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            _write_recoverable_backup_receipts(backup_path)
            payload = production_readiness_payload(
                document_storage_path=base / "documents", export_path=base / "exports", backup_path=backup_path,
                env={"FISORA_STORE_BACKEND": "postgres", "DATABASE_URL": "postgresql://test", "FISORA_REAL_DATA_ACCESS_MODE": "vpn", "FISORA_QNB_ADAPTER": "soap", "FISORA_QNB_CREDENTIAL_KEY": "secret", "FISORA_QNB_ERP_CODE": "ERP", "FISORA_QNB_SCHEDULER_ENABLED": "true", "FISORA_BACKUP_MODE": "scheduled", "FISORA_BACKUP_OFFHOST_ATTESTED": "true"},
            )
        self.assertFalse(payload["qnb_pilot"]["ready"])
        self.assertIn(
            "outcome_evidence_available",
            payload["qnb_pilot"]["blocking"],
        )
        self.assertTrue(payload["qnb_pilot"]["runtime"]["incoming_ready"])
        self.assertNotIn("secret", str(payload["qnb_pilot"]))

    def test_pilot_sellable_blocks_anonymous_or_json_store_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            backup_path = base / "backups"
            backup_path.mkdir()
            (backup_path / "postgres-20260606T100000Z.sql").write_text("backup", encoding="utf-8")

            payload = production_readiness_payload(
                document_storage_path=base / "documents",
                export_path=base / "exports",
                backup_path=backup_path,
                env={
                    "FISORA_AUTH_MODE": "mock_header_optional",
                    "FISORA_STORE_BACKEND": "json",
                    "FISORA_AI_PROVIDER": "disabled",
                },
            )

        self.assertFalse(payload["pilot_sellable"])
        self.assertEqual(payload["commercial_readiness"]["status"], "blocked")
        self.assertIn("auth_requires_user", payload["pilot_blocking"])
        self.assertIn("postgres_store_active", payload["pilot_blocking"])

    def test_chart_account_import_marks_detail_accounts(self) -> None:
        accounts = parse_chart_accounts(ROOT / "samples" / "chart_accounts" / "chart_accounts_sample_a.csv")
        account_by_code = {account.normalized_account_code: account for account in accounts}

        self.assertFalse(account_by_code["120"].is_detail_account)
        self.assertTrue(account_by_code["120.01.001"].is_detail_account)
        self.assertTrue(account_by_code["320.01.001"].is_detail_account)

    def test_three_chart_account_samples_are_parseable(self) -> None:
        sample_dir = ROOT / "samples" / "chart_accounts"
        for sample_name in (
            "chart_accounts_sample_a.csv",
            "chart_accounts_sample_b.csv",
            "chart_accounts_sample_c.csv",
        ):
            with self.subTest(sample=sample_name):
                accounts = parse_chart_accounts(sample_dir / sample_name)
                counterparties = extract_counterparty_candidates(accounts)
                vat_status = validate_vat_accounts(accounts)

                self.assertGreaterEqual(len(accounts), 10)
                self.assertGreaterEqual(len(counterparties), 2)
                self.assertTrue(vat_status["has_purchase_vat_191"])
                self.assertTrue(vat_status["has_sales_vat_391"])

    def test_chart_account_import_extracts_counterparties_and_vat_status(self) -> None:
        accounts = parse_chart_accounts(ROOT / "samples" / "chart_accounts" / "chart_accounts_sample_a.csv")
        counterparties = extract_counterparty_candidates(accounts)
        vat_status = validate_vat_accounts(accounts)

        self.assertEqual({item.counterparty_type for item in counterparties}, {"customer", "supplier"})
        self.assertEqual(vat_status, {"has_purchase_vat_191": True, "has_sales_vat_391": True})

    def test_chart_semantic_map_extracts_stock_revenue_vat_and_counterparty_roles(self) -> None:
        accounts = [
            ChartAccount("153 01 001", "153.01.001", "ALINAN CİHAZLAR", True),
            ChartAccount("153 03", "153.03", "SİGARA ALIŞLARI", True),
            ChartAccount("600 01 000", "600.01.000", "3065 KAPSAMINDA CİHAZ SATIŞI", True),
            ChartAccount("191 01 020", "191.01.020", "Yüzde 20 İndirilecek KDV", True),
            ChartAccount("391 01 020", "391.01.020", "Yüzde 20 Hesaplanan KDV", True),
            ChartAccount("320 201", "320.201", "2BIR MEŞRUBAT VE GIDA", True),
        ]

        semantic_map = build_chart_semantic_map(accounts)

        self.assertEqual(semantic_map["153.01.001"]["roles"], ["stock", "hearing_device_stock"])
        self.assertEqual(semantic_map["153.03"]["roles"], ["stock", "tobacco_stock"])
        self.assertEqual(semantic_map["600.01.000"]["roles"], ["sales_revenue", "zero_vat_3065_revenue"])
        self.assertEqual(semantic_map["191.01.020"]["roles"], ["purchase_vat"])
        self.assertEqual(semantic_map["191.01.020"]["vat_rate"], "20")
        self.assertEqual(semantic_map["391.01.020"]["roles"], ["sales_vat"])
        self.assertEqual(semantic_map["320.201"]["roles"], ["supplier", "food_supplier"])

    def test_account_code_normalization(self) -> None:
        self.assertEqual(normalize_account_code(" 120.01,001 "), "120.01.001")
        self.assertEqual(normalize_account_code("100 01 001"), "100.01.001")
        self.assertEqual(normalize_account_code("120-01-001"), "120.01.001")

    def test_purchase_sales_bank_entries_are_balanced(self) -> None:
        entries = [
            build_purchase_entry(
                entry_date="2026-05-01",
                total=money("1200.00"),
                vat_rate=Decimal("0.20"),
                expense_account="770.01",
            ),
            build_sales_entry(
                entry_date="2026-05-02",
                total=money("2400.00"),
                vat_rate=Decimal("0.20"),
                revenue_account="600.01",
            ),
            build_bank_payment_entry(
                entry_date="2026-05-03",
                amount=money("500.00"),
                bank_account="102.01",
                counterparty_account="320.01.001",
            ),
        ]

        self.assertTrue(all(entry.is_balanced for entry in entries))

    def test_mixed_vat_purchase_entry_is_balanced_without_review_flag(self) -> None:
        entry = build_mixed_vat_purchase_entry(
            entry_date="2026-05-04",
            items=(("770.01", money("108.00"), Decimal("0.08")), ("770.02", money("120.00"), Decimal("0.20"))),
        )

        self.assertTrue(entry.is_balanced)
        self.assertEqual(entry.risk_flags, ())

    def test_universal_journal_export(self) -> None:
        entry = build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="AF-0001",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = export_universal_journal_csv([entry], Path(temp_dir) / "journal.csv")
            text = output.read_text(encoding="utf-8-sig")

        self.assertIn("entry_no,entry_type,entry_date", text)
        self.assertIn("770.01", text)
        self.assertIn("320.01.001", text)

    def test_invoice_edge_case_summary_flags_manual_review(self) -> None:
        text = """
        E-FATURA
        Fatura No: ABC2026000000001
        ETTN: 123e4567-e89b-12d3-a456-426614174000
        Tevkifat
        KDV %8
        KDV %20
        """

        summary = summarize_invoice_edge_cases("Kolay Soft 1.pdf", text, extracted_char_count=len(text))

        self.assertEqual(summary.provider_hint, "Kolay Soft")
        self.assertEqual(summary.invoice_no, "ABC2026000000001")
        self.assertEqual(summary.ettn, "123e4567-e89b-12d3-a456-426614174000")
        self.assertIn("withholding_manual_review", summary.risk_flags)
        self.assertIn("mixed_vat_manual_review", summary.risk_flags)
        self.assertEqual(summary.suggested_expected_behavior, "review_queue")

    def test_pdf_invoice_helpers_parse_amounts_and_vat_rates(self) -> None:
        text = "Mal Hizmet Toplam Tutarı 1.234,56 TL Hesaplanan KDV(%20) 246,91 TL KDV %8"

        self.assertEqual(str(parse_amount("1.234,56")), "1234.56")
        self.assertEqual(extract_vat_rates(text), ("8", "20"))
        noisy_table_header = "KDV Oranı\nKDV Tutarı\n1\nSLIM TAPER\n"
        self.assertEqual(extract_vat_rates(noisy_table_header), ())
        self.assertEqual(extract_vat_rates("KATMA DEĞER VERGİSİ(%10)\n309,09 TL"), ("10",))

    def test_textless_pdf_invoice_is_reviewed_without_ocr(self) -> None:
        from unittest.mock import patch

        with patch("app.domain.pdf_invoices.extract_pdf_pages", return_value=((PdfPageText(1, ""),), ("pdf_text_empty",))):
            invoice = parse_pdf_invoice(Path("scanned.pdf"))

        self.assertEqual(invoice.suggested_route, "review_queue")
        self.assertIn("scanned_pdf_unsupported", invoice.parse_notes)
        self.assertNotIn("ocr", " ".join(invoice.parse_notes).lower())

    def test_pdf_invoice_line_extraction_prefers_product_table_rows(self) -> None:
        text = "\n".join(
            [
                "SAYIN",
                "ORHAN ELIBOL",
                "TCKN: 30052309394",
                "Fatura No:",
                "AVQ2026000000026",
                "Malzeme/Hizmet Açıklaması",
                "Miktar",
                "Birim Fiyat",
                "KDV Oranı",
                "1",
                "SLIM TAPER",
                "1",
                "Adet",
                "3.090,9 TL",
                "%10,00",
                "309,09 TL",
            ]
        )

        lines = extract_invoice_lines_from_text(text)

        self.assertEqual(lines[0].description, "SLIM TAPER")
        self.assertEqual(lines[0].vat_rate, "10")
        self.assertEqual(lines[0].tax_amount, "309,09")

    def test_invoice_line_extraction_keeps_table_amounts_for_grouped_vat(self) -> None:
        text = "\n".join(
            [
                "Fatura No:",
                "EEY2026000002099",
                "Mal Hizmet",
                "Miktar",
                "Birim Fiyat",
                "KDV Oranı",
                "KDV Tutarı",
                "Mal Hizmet Tutarı",
                "1",
                "TAMEK KORNİŞON (SALATALIK) TURŞUSU 330 CC*12",
                "12 Adet",
                "98,56TL",
                "%1,00",
                "11,83TL",
                "1.182,72TL",
                "2",
                "COCA COLA CHERRY *24",
                "6 Adet",
                "90,91TL",
                "%10,00",
                "54,55TL",
                "545,46TL",
            ]
        )

        lines = extract_invoice_lines_from_text(text)

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].description, "TAMEK KORNİŞON (SALATALIK) TURŞUSU 330 CC*12")
        self.assertEqual(lines[0].vat_rate, "1")
        self.assertEqual(lines[0].taxable_amount, "1.182,72")
        self.assertEqual(lines[0].tax_amount, "11,83")
        self.assertEqual(lines[1].vat_rate, "10")
        self.assertEqual(lines[1].taxable_amount, "545,46")
        self.assertEqual(lines[1].tax_amount, "54,55")

    def test_canonical_invoice_validation_accepts_balanced_line_vat_and_totals(self) -> None:
        from app.domain.canonical_invoices import (
            CanonicalInvoice,
            CanonicalInvoiceHeader,
            CanonicalInvoiceLine,
            CanonicalInvoiceParty,
            CanonicalInvoiceTotals,
            CanonicalVatSummaryLine,
            validate_canonical_invoice,
        )

        invoice = CanonicalInvoice(
            source="xml",
            supplier_party=CanonicalInvoiceParty(title="Medikal Tedarik", tax_id="9999999999"),
            customer_party=CanonicalInvoiceParty(title="ORHAN ELIBOL", tax_id="1234567890"),
            header=CanonicalInvoiceHeader(invoice_no="AAA2026000000001", issue_date="01.06.2026"),
            line_items=(
                CanonicalInvoiceLine(
                    description="Isitme cihazi",
                    source_position="xml:InvoiceLine[1]",
                    taxable_amount="1000.00",
                    vat_rate="20",
                    tax_amount="200.00",
                    gross_amount="1200.00",
                    evidence=("xml:InvoiceLine[1]",),
                ),
            ),
            vat_summary=(CanonicalVatSummaryLine(rate="20", taxable_amount="1000.00", tax_amount="200.00"),),
            totals=CanonicalInvoiceTotals(
                goods_services_total="1000.00",
                vat_total="200.00",
                tax_inclusive_total="1200.00",
                payable_total="1200.00",
            ),
        )

        validation = validate_canonical_invoice(invoice)

        self.assertEqual(validation.status, "valid")
        self.assertEqual(validation.reason_codes, ())

    def test_canonical_invoice_validation_flags_missing_lines_before_product_classification(self) -> None:
        from app.domain.canonical_invoices import (
            CanonicalInvoice,
            CanonicalInvoiceHeader,
            CanonicalInvoiceParty,
            CanonicalInvoiceTotals,
            validate_canonical_invoice,
        )

        invoice = CanonicalInvoice(
            source="pdf_text",
            supplier_party=CanonicalInvoiceParty(title="Rexton Medikal", tax_id="9999999999"),
            customer_party=CanonicalInvoiceParty(title="ORHAN ELIBOL", tax_id="1234567890"),
            header=CanonicalInvoiceHeader(invoice_no="AAA2026000000002", issue_date="01.06.2026"),
            line_items=(),
            vat_summary=(),
            totals=CanonicalInvoiceTotals(payable_total="1200.00"),
        )

        validation = validate_canonical_invoice(invoice)

        self.assertEqual(validation.status, "invalid")
        self.assertIn("line_items_missing", validation.reason_codes)

    def test_product_classification_does_not_infer_product_from_supplier_without_lines(self) -> None:
        invoice = ParsedInvoice(
            file_name="supplier-name-only.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000000003",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=(),
            line_item_details=(),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = _simulate_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.product_line_hint, "")
        self.assertEqual(result.product_category, "bilinmeyen")
        self.assertEqual(result.product_confidence, 0)
        self.assertIn("line_items_missing", result.review_reason_codes)
        self.assertIn("line_items_missing", result.business_relevance_evidence)
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.draft_lines, ())
        self.assertEqual(result.export_status, "review_required")

    def test_sales_return_without_canonical_line_evidence_cannot_build_journal(self) -> None:
        invoice = ParsedInvoice(
            file_name="supplier-name-only-return.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="IADE",
            invoice_type="IADE",
            invoice_no="RET2026000000000",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_title="Isitme Merkezi A",
            issuer_tax_id="1234567890",
            recipient_title="Alici Firma",
            recipient_tax_id="9999999999",
            is_return_invoice=True,
            line_items=(),
            line_item_details=(),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )

        result = _simulate_invoice(invoice, selection, profile)

        self.assertEqual(result.accounting_direction, "sales")
        self.assertIn("line_items_missing", result.review_reason_codes)
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.selected_revenue_account, "")
        self.assertEqual(result.draft_lines, ())
        self.assertEqual(result.export_status, "review_required")

    def test_simulation_exposes_canonical_extraction_summary(self) -> None:
        from app.domain.canonical_invoices import (
            CanonicalInvoice,
            CanonicalInvoiceHeader,
            CanonicalInvoiceLine,
            CanonicalInvoiceParty,
            CanonicalInvoiceTotals,
            CanonicalVatSummaryLine,
            with_validation,
        )

        canonical = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                supplier_party=CanonicalInvoiceParty(title="Medikal Tedarik", tax_id="9999999999"),
                customer_party=CanonicalInvoiceParty(title="ORHAN ELIBOL", tax_id="1234567890"),
                header=CanonicalInvoiceHeader(invoice_no="AAA2026000000006", issue_date="01.06.2026"),
                line_items=(
                    CanonicalInvoiceLine(
                        description="Isitme cihazi",
                        source_position="pdf:text:line:1",
                        taxable_amount="1000.00",
                        vat_rate="20",
                        tax_amount="200.00",
                        gross_amount="1200.00",
                    ),
                ),
                vat_summary=(CanonicalVatSummaryLine(rate="20", taxable_amount="1000.00", tax_amount="200.00"),),
                totals=CanonicalInvoiceTotals(
                    goods_services_total="1000.00",
                    vat_total="200.00",
                    tax_inclusive_total="1200.00",
                    payable_total="1200.00",
                ),
                ai_used=True,
            )
        )
        invoice = ParsedInvoice(
            file_name="canonical-summary.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000000006",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Isitme cihazi",),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.canonical_line_count, 1)
        self.assertEqual(result.canonical_validation_status, "valid")
        self.assertEqual(result.canonical_validation_reasons, ())
        self.assertTrue(result.canonical_extraction_ai_used)

    def test_xml_invoice_populates_canonical_parties_lines_vat_and_totals(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:ID>AAA2026000000004</cbc:ID>
  <cbc:UUID>11111111-2222-3333-4444-555555555555</cbc:UUID>
  <cbc:IssueDate>2026-06-01</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID>9999999999</cbc:ID></cac:PartyIdentification>
      <cac:PartyName><cbc:Name>MEDIKAL TEDARIK A.S.</cbc:Name></cac:PartyName>
      <cac:PartyLegalEntity><cbc:RegistrationName>MEDIKAL TEDARIK A.S.</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID>1234567890</cbc:ID></cac:PartyIdentification>
      <cac:PartyLegalEntity><cbc:RegistrationName>ORHAN ELIBOL</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="TRY">200.00</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="TRY">1000.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="TRY">200.00</cbc:TaxAmount>
      <cac:TaxCategory><cbc:Percent>20</cbc:Percent></cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="TRY">1000.00</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount currencyID="TRY">1200.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="TRY">1200.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">1000.00</cbc:LineExtensionAmount>
    <cac:TaxTotal>
      <cbc:TaxAmount currencyID="TRY">200.00</cbc:TaxAmount>
      <cac:TaxSubtotal>
        <cbc:TaxableAmount currencyID="TRY">1000.00</cbc:TaxableAmount>
        <cbc:TaxAmount currencyID="TRY">200.00</cbc:TaxAmount>
        <cac:TaxCategory><cbc:Percent>20</cbc:Percent></cac:TaxCategory>
      </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:Item><cbc:Name>Isitme cihazi</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="TRY">1000.00</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xml"
            path.write_text(xml, encoding="utf-8")

            invoice = parse_xml_invoice(path)

        canonical = invoice.canonical_invoice
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.supplier_party.title, "MEDIKAL TEDARIK A.S.")
        self.assertEqual(canonical.customer_party.tax_id, "1234567890")
        self.assertEqual(canonical.line_items[0].description, "Isitme cihazi")
        self.assertEqual(canonical.line_items[0].vat_rate, "20")
        self.assertEqual(canonical.vat_summary[0].taxable_amount, "1000.00")
        self.assertEqual(canonical.validation.status, "valid")

    def test_xml_invoice_line_description_uses_item_name_not_tax_scheme_name(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>TEF2026000000570</cbc:ID>
  <cbc:IssueDate>2026-06-17</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">3850103686</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Favori Tekstil</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="TCKN">69889018582</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">306.35</cbc:LineExtensionAmount>
    <cac:TaxTotal>
      <cbc:TaxAmount currencyID="TRY">27.85</cbc:TaxAmount>
      <cac:TaxSubtotal>
        <cbc:TaxableAmount currencyID="TRY">278.50</cbc:TaxableAmount>
        <cbc:TaxAmount currencyID="TRY">27.85</cbc:TaxAmount>
        <cac:TaxCategory>
          <cbc:Percent>10</cbc:Percent>
          <cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme>
        </cac:TaxCategory>
      </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:Item><cbc:Name>Basic Lazer Kesim Kadin Hipster Kulot</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="TRY">306.35</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="TRY">278.50</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount currencyID="TRY">306.35</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="TRY">306.35</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)

        canonical = invoice.canonical_invoice
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.line_items[0].description, "Basic Lazer Kesim Kadin Hipster Kulot")
        self.assertEqual(canonical.line_items[0].taxable_amount, "278.50")
        self.assertNotEqual(canonical.line_items[0].description, "KDV")

    def test_xml_customer_title_does_not_use_tax_scheme_name(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>NOISE2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-07</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>SATICI A.S.</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="TCKN">22222222222</cbc:ID></cac:PartyIdentification>
    <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:Person><cbc:FirstName>Ayse</cbc:FirstName><cbc:FamilyName>Yilmaz</cbc:FamilyName></cac:Person>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine><cac:Item><cbc:Name>Bakim hizmeti</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:LegalMonetaryTotal><cbc:PayableAmount>1.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)

        self.assertEqual(invoice.recipient_title, "Ayse Yilmaz")
        self.assertEqual(invoice.recipient_tax_id, "22222222222")
        self.assertEqual(invoice.canonical_invoice.customer_party.title, "Ayse Yilmaz")
        self.assertNotEqual(invoice.recipient_title, "KDV")

    def test_xml_party_details_include_address_and_tax_office(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>ADDR2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-07</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyLegalEntity><cbc:RegistrationName>MEDIKAL TEDARIK A.S.</cbc:RegistrationName></cac:PartyLegalEntity>
    <cac:PartyTaxScheme>
      <cbc:CompanyID>1111111111</cbc:CompanyID>
      <cac:TaxScheme><cbc:Name>KADIKOY</cbc:Name></cac:TaxScheme>
    </cac:PartyTaxScheme>
    <cac:PostalAddress>
      <cbc:StreetName>Bagdat Cad.</cbc:StreetName>
      <cbc:BuildingNumber>10</cbc:BuildingNumber>
      <cbc:CitySubdivisionName>Kadikoy</cbc:CitySubdivisionName>
      <cbc:CityName>Istanbul</cbc:CityName>
    </cac:PostalAddress>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>ALICI LTD</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID>2222222222</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine><cac:Item><cbc:Name>Bakim hizmeti</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:LegalMonetaryTotal><cbc:PayableAmount>1.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)

        supplier = invoice.canonical_invoice.supplier_party
        self.assertEqual(supplier.title, "MEDIKAL TEDARIK A.S.")
        self.assertEqual(supplier.tax_id, "1111111111")
        self.assertEqual(supplier.tax_office, "KADIKOY")
        self.assertIn("Bagdat Cad.", supplier.address)
        self.assertIn("Istanbul", supplier.address)

    def test_xml_invoice_with_visible_cancellation_warning_still_builds_draft(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>IPT2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-07</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cbc:Note>BU FATURA IPTAL EDILMISTIR</cbc:Note>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Tedarikci A.S.</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Isitme Merkezi A</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount>
    <cac:TaxTotal><cbc:TaxAmount currencyID="TRY">20.00</cbc:TaxAmount></cac:TaxTotal>
    <cac:Item><cbc:Name>Bakim hizmeti</cbc:Name></cac:Item>
  </cac:InvoiceLine>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "iptal.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)

        self.assertIn("cancelled_invoice_visible", invoice.risk_flags)

        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="2222222222",
            activity_description="Isitme cihazi satis ve servis merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, intended_direction="purchase")

        self.assertTrue(result.draft_lines)
        self.assertEqual(result.export_status, "review_required")
        self.assertIn("cancelled_invoice_visible", result.review_reason_codes)
        self.assertIn("iptal", result.export_gate_reason.lower())

    def test_ubl_party_resolution_uses_supplier_as_counterparty_for_purchase(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>ALI2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-06</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Supplier From XML</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Client From XML</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Isitme cihazi</cbc:Name></cac:Item></cac:InvoiceLine>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "purchase.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Client From XML",
            tax_id="2222222222",
            activity_description="Odyoloji hizmetleri",
            workplace_addresses=(),
            has_chart_accounts=True,
        )
        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertEqual(result.suggested_counterparty_account, "320.1111111111")
        self.assertEqual(result.counterparty_title, "Supplier From XML")
        self.assertEqual(result.counterparty_identity_key, "purchase|tax:1111111111")

    def test_ubl_party_resolution_uses_customer_as_counterparty_for_sale(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>SAT2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-06</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Client From XML</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Customer From XML</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Isitme cihazi</cbc:Name></cac:Item></cac:InvoiceLine>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sale.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            revenue_account="600.01.001",
            sales_vat_account="391.01.020",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Client From XML",
            tax_id="1111111111",
            activity_description="Odyoloji hizmetleri",
            workplace_addresses=(),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.suggested_counterparty_account, "120.2222222222")
        self.assertEqual(result.counterparty_title, "Customer From XML")
        self.assertEqual(result.counterparty_identity_key, "sales|tax:2222222222")

    def test_ubl_counterparty_matching_uses_person_title_when_tax_scheme_name_is_noise(self) -> None:
        from app.domain.xml_invoices import parse_xml_invoice

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>SAT2026000000002</cbc:ID>
  <cbc:IssueDate>2026-07-07</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
    <cac:PartyName><cbc:Name>Client From XML</cbc:Name></cac:PartyName>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="TCKN">22222222222</cbc:ID></cac:PartyIdentification>
    <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:Person><cbc:FirstName>Ayse</cbc:FirstName><cbc:FamilyName>Yilmaz</cbc:FamilyName></cac:Person>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Bakim hizmeti</cbc:Name></cac:Item></cac:InvoiceLine>
</Invoice>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sale.xml"
            path.write_text(xml, encoding="utf-8")
            invoice = parse_xml_invoice(path)
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            revenue_account="600.01.001",
            sales_vat_account="391.01.020",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Client From XML",
            tax_id="1111111111",
            activity_description="Odyoloji hizmetleri",
            workplace_addresses=(),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.suggested_counterparty_account, "120.22222222222")
        self.assertEqual(result.counterparty_title, "Ayse Yilmaz")
        self.assertEqual(result.counterparty_identity_key, "sales|tax:22222222222")
        self.assertNotEqual(result.counterparty_title, "KDV")

    def test_pdf_invoice_populates_canonical_lines_and_vat_summary_from_deterministic_parser(self) -> None:
        invoice_path = ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "purchases" / "1061386125_AVQ2026000000026.pdf"
        if not invoice_path.exists():
            self.skipTest(f"private pilot invoice sample missing: {invoice_path}")

        invoice = parse_pdf_invoice(invoice_path)

        canonical = invoice.canonical_invoice
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.source, "pdf_text")
        self.assertEqual(canonical.line_items[0].description, "SLIM TAPER")
        self.assertEqual(canonical.line_items[0].vat_rate, "10")
        self.assertEqual(canonical.vat_summary[0].rate, "10")
        self.assertEqual(canonical.validation.status, "valid")

    def test_pdf_canonical_ai_keeps_deterministic_source_line_identity(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import (
            CanonicalExtractionPolicy,
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            with_validation,
        )
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(description="Cihaz", source_position="pdf:text:line:1"),
                    CanonicalInvoiceLine(description="Bakim", source_position="pdf:text:line:2"),
                ),
                totals=CanonicalInvoiceTotals(payable_total="170.00"),
            )
        )

        class Provider:
            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                ids = [item["canonical_line_id"] for item in request.deterministic_payload["line_items"]]
                return {
                    "supplier_party": {},
                    "customer_party": {},
                    "line_items": [
                        {
                            "canonical_line_id": ids[0],
                            "source_position": "ignored",
                            "description": "Cihaz",
                            "taxable_amount": "100.00",
                            "vat_rate": "20",
                            "tax_amount": "20.00",
                            "gross_amount": "120.00",
                        },
                        {
                            "canonical_line_id": ids[1],
                            "source_position": "ignored",
                            "description": "Bakim",
                            "taxable_amount": "50.00",
                            "vat_rate": "0",
                            "tax_amount": "0.00",
                            "gross_amount": "50.00",
                        },
                    ],
                    "vat_summary": [
                        {"rate": "20", "taxable_amount": "100.00", "tax_amount": "20.00"},
                        {"rate": "0", "taxable_amount": "50.00", "tax_amount": "0.00"},
                    ],
                    "totals": {
                        "goods_services_total": "150.00",
                        "vat_total": "20.00",
                        "special_tax_total": "0.00",
                        "tax_inclusive_total": "170.00",
                        "payable_total": "170.00",
                    },
                }

        completed = _maybe_complete_canonical_with_ai(
            provider=Provider(),
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Cihaz ve bakim faturasi",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertTrue(completed.ai_used)
        self.assertEqual(completed.source, "pdf_text")
        self.assertEqual(
            [line.canonical_line_id for line in completed.line_items],
            [line.canonical_line_id for line in deterministic.line_items],
        )
        self.assertEqual(
            [line.source_position for line in completed.line_items],
            [line.source_position for line in deterministic.line_items],
        )

    def test_pdf_canonical_ai_discovers_missing_rows_with_server_generated_identity(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import (
            CanonicalExtractionPolicy,
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            with_validation,
        )
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(
                        description="Cihaz",
                        source_position="pdf:text:line:1",
                        taxable_amount="100.00",
                        vat_rate="20",
                        tax_amount="20.00",
                        gross_amount="120.00",
                    ),
                ),
                totals=CanonicalInvoiceTotals(payable_total="180.00"),
            )
        )

        class Provider:
            seen_mode = ""

            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                self.seen_mode = request.mode
                return {
                    "supplier_party": {"title": "", "tax_id": "", "tax_office": "", "address": "", "evidence": []},
                    "customer_party": {"title": "", "tax_id": "", "tax_office": "", "address": "", "evidence": []},
                    "line_items": [
                        {
                            "canonical_line_id": "provider-line-1",
                            "source_position": "pdf:text:line:1",
                            "external_line_id": "provider-external-1",
                            "description": "Cihaz",
                            "observed_quantity": "1",
                            "observed_unit_code": "ADET",
                            "observed_unit_price": "100.00",
                            "observed_taxable_amount": "100.00",
                            "observed_vat_rate": "20",
                            "observed_tax_amount": "20.00",
                            "observed_gross_amount": "120.00",
                            "evidence": ["pdf:text:line:1"],
                        },
                        {
                            "canonical_line_id": "provider-line-2",
                            "source_position": "pdf:text:line:2",
                            "external_line_id": "provider-external-2",
                            "description": "Bakim",
                            "observed_quantity": "1",
                            "observed_unit_code": "ADET",
                            "observed_unit_price": "50.00",
                            "observed_taxable_amount": "50.00",
                            "observed_vat_rate": "20",
                            "observed_tax_amount": "10.00",
                            "observed_gross_amount": "60.00",
                            "evidence": ["pdf:text:line:2"],
                        },
                    ],
                    "observed_vat_summary": [],
                    "observed_totals": {
                        "observed_goods_services_total": "150.00",
                        "observed_vat_total": "30.00",
                        "observed_special_tax_total": "0.00",
                        "observed_tax_inclusive_total": "180.00",
                        "observed_payable_total": "180.00",
                        "evidence": ["pdf:totals"],
                    },
                    "extraction_notes": [],
                }

        provider = Provider()
        completed = _maybe_complete_canonical_with_ai(
            provider=provider,
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Cihaz 100,00 20,00 120,00\nBakim 50,00 10,00 60,00\nToplam 180,00",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={"payable_total": "180.00"},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertEqual(provider.seen_mode, "discovery")
        self.assertTrue(completed.ai_used)
        self.assertEqual(len(completed.line_items), 2)
        self.assertTrue(all(line.canonical_line_id.startswith("line_") for line in completed.line_items))
        self.assertNotIn("provider-line-1", {line.canonical_line_id for line in completed.line_items})
        self.assertTrue(all(not line.external_line_id for line in completed.line_items))
        self.assertEqual(completed.validation.status, "valid")
        self.assertIn("canonical_ai_discovery_used", completed.extraction_notes)

    def test_pdf_canonical_ai_rejects_discovery_with_duplicate_source_positions(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import CanonicalExtractionPolicy, CanonicalInvoice, CanonicalInvoiceTotals, with_validation
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(source="pdf_text", totals=CanonicalInvoiceTotals(payable_total="120.00"))
        )

        class Provider:
            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                line = {
                    "canonical_line_id": "provider-id",
                    "source_position": "pdf:text:line:1",
                    "external_line_id": "provider-external",
                    "description": "Cihaz",
                    "observed_quantity": "1",
                    "observed_unit_code": "ADET",
                    "observed_unit_price": "50.00",
                    "observed_taxable_amount": "50.00",
                    "observed_vat_rate": "20",
                    "observed_tax_amount": "10.00",
                    "observed_gross_amount": "60.00",
                    "evidence": [],
                }
                return {
                    "supplier_party": {"title": "", "tax_id": "", "tax_office": "", "address": "", "evidence": []},
                    "customer_party": {"title": "", "tax_id": "", "tax_office": "", "address": "", "evidence": []},
                    "line_items": [line, dict(line)],
                    "observed_vat_summary": [],
                    "observed_totals": {
                        "observed_goods_services_total": "100.00",
                        "observed_vat_total": "20.00",
                        "observed_special_tax_total": "0.00",
                        "observed_tax_inclusive_total": "120.00",
                        "observed_payable_total": "120.00",
                        "evidence": [],
                    },
                    "extraction_notes": [],
                }

        completed = _maybe_complete_canonical_with_ai(
            provider=Provider(),
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Iki satir",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={"payable_total": "120.00"},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertFalse(completed.ai_used)
        self.assertEqual(completed.line_items, deterministic.line_items)
        self.assertIn("canonical_ai_discovery_rejected", completed.extraction_notes)

    def test_pdf_canonical_ai_preserves_blank_observation_line_and_rejects_missing_values(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import (
            CanonicalExtractionPolicy,
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            with_validation,
        )
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(description="Cihaz", source_position="pdf:text:line:1"),
                    CanonicalInvoiceLine(description="Bakim", source_position="pdf:text:line:2"),
                ),
                totals=CanonicalInvoiceTotals(payable_total="120.00"),
            )
        )

        class Provider:
            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                ids = [item["canonical_line_id"] for item in request.deterministic_payload["line_items"]]
                return {
                    "supplier_party": {},
                    "customer_party": {},
                    "line_items": [
                        {
                            "canonical_line_id": ids[0],
                            "description": "Cihaz",
                            "taxable_amount": "100.00",
                            "vat_rate": "20",
                            "tax_amount": "20.00",
                            "gross_amount": "120.00",
                        },
                        {
                            "canonical_line_id": ids[1],
                            "description": "",
                            "taxable_amount": "",
                            "vat_rate": "",
                            "tax_amount": "",
                            "gross_amount": "",
                        },
                    ],
                    "vat_summary": [{"rate": "20", "taxable_amount": "100.00", "tax_amount": "20.00"}],
                    "totals": {
                        "goods_services_total": "100.00",
                        "vat_total": "20.00",
                        "special_tax_total": "0.00",
                        "tax_inclusive_total": "120.00",
                        "payable_total": "120.00",
                    },
                }

        completed = _maybe_complete_canonical_with_ai(
            provider=Provider(),
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Cihaz faturasi",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertFalse(completed.ai_used)
        self.assertIn("canonical_ai_rejected", completed.extraction_notes)
        self.assertEqual(len(completed.line_items), 2)
        self.assertIn("line_vat_rate_missing", completed.extraction_notes)
        self.assertNotIn("canonical_line_coverage_invalid", completed.extraction_notes)

    def test_pdf_canonical_ai_reconciles_arithmetic_only_against_document_total(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import (
            CanonicalExtractionPolicy,
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            with_validation,
        )
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(description="Cihaz", source_position="pdf:text:line:1"),
                ),
                totals=CanonicalInvoiceTotals(payable_total="120.00"),
            )
        )

        class Provider:
            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                line_id = request.deterministic_payload["line_items"][0]["canonical_line_id"]
                return {
                    "supplier_party": {},
                    "customer_party": {},
                    "line_items": [
                        {
                            "canonical_line_id": line_id,
                            "description": "Cihaz",
                            "observed_quantity": "1",
                            "observed_unit_code": "ADET",
                            "observed_unit_price": "100.00",
                            "observed_taxable_amount": "100.00",
                            "observed_vat_rate": "20",
                            "observed_tax_amount": "17.00",
                            "observed_gross_amount": "117.00",
                            "evidence": ["pdf:text:line:1"],
                        }
                    ],
                    "observed_vat_summary": [{
                        "observed_rate": "20",
                        "observed_taxable_amount": "100.00",
                        "observed_tax_amount": "17.00",
                        "evidence": ["pdf:vat-summary"],
                    }],
                    "observed_totals": {
                        "observed_goods_services_total": "100.00",
                        "observed_vat_total": "17.00",
                        "observed_special_tax_total": "0.00",
                        "observed_tax_inclusive_total": "117.00",
                        "observed_payable_total": "120.00",
                        "evidence": ["pdf:totals"],
                    },
                    "extraction_notes": [],
                }

        completed = _maybe_complete_canonical_with_ai(
            provider=Provider(),
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Cihaz 100,00 KDV 20 odeme 120,00",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={"payable_total": "120.00"},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertTrue(completed.ai_used)
        self.assertEqual(completed.validation.status, "valid")
        self.assertEqual(completed.line_items[0].tax_amount, "20.00")
        self.assertEqual(completed.line_items[0].gross_amount, "120.00")
        self.assertEqual(completed.totals.vat_total, "20.00")
        self.assertEqual(completed.totals.payable_total, "120.00")
        self.assertIn("canonical_deterministic_arithmetic_applied", completed.extraction_notes)
        self.assertNotIn("canonical_ai_arithmetic_reconciled", completed.extraction_notes)
        self.assertIn("observed_tax_amount_mismatch", completed.extraction_notes)
        self.assertIn("observed_gross_amount_mismatch", completed.extraction_notes)
        self.assertIn("observed_vat_total_mismatch", completed.extraction_notes)
        self.assertIn("observed_vat_summary_mismatch", completed.extraction_notes)

    def test_pdf_canonical_ai_does_not_reconcile_against_a_different_document_total(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import (
            CanonicalExtractionPolicy,
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            with_validation,
        )
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(CanonicalInvoiceLine(description="Cihaz", source_position="pdf:text:line:1"),),
                totals=CanonicalInvoiceTotals(payable_total="125.00"),
            )
        )

        class Provider:
            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                line_id = request.deterministic_payload["line_items"][0]["canonical_line_id"]
                return {
                    "supplier_party": {},
                    "customer_party": {},
                    "line_items": [
                        {
                            "canonical_line_id": line_id,
                            "description": "Cihaz",
                            "taxable_amount": "100.00",
                            "vat_rate": "20",
                            "tax_amount": "20.00",
                            "gross_amount": "120.00",
                        }
                    ],
                    "vat_summary": [{"rate": "20", "taxable_amount": "100.00", "tax_amount": "20.00"}],
                    "totals": {
                        "goods_services_total": "100.00",
                        "vat_total": "20.00",
                        "special_tax_total": "0.00",
                        "tax_inclusive_total": "120.00",
                        "payable_total": "120.00",
                    },
                }

        completed = _maybe_complete_canonical_with_ai(
            provider=Provider(),
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Cihaz 100,00 KDV 20 odeme 125,00",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={"payable_total": "125.00"},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertFalse(completed.ai_used)
        self.assertEqual(completed.totals.payable_total, "125.00")
        self.assertIn("canonical_ai_rejected", completed.extraction_notes)
        self.assertNotIn("canonical_ai_arithmetic_reconciled", completed.extraction_notes)

    def test_pdf_canonical_ai_cannot_overwrite_deterministic_line_money(self) -> None:
        from types import SimpleNamespace

        from app.domain.canonical_invoices import (
            CanonicalExtractionPolicy,
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            with_validation,
        )
        from app.domain.pdf_invoices import _maybe_complete_canonical_with_ai

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(
                        description="Cihaz",
                        source_position="pdf:text:line:1",
                        taxable_amount="100.00",
                        vat_rate="20",
                    ),
                ),
                totals=CanonicalInvoiceTotals(payable_total="120.00"),
            )
        )

        class Provider:
            def extract_invoice_canonical(self, request: object) -> dict[str, object]:
                line_id = request.deterministic_payload["line_items"][0]["canonical_line_id"]
                return {
                    "supplier_party": {"title": "", "tax_id": "", "tax_office": "", "address": "", "evidence": []},
                    "customer_party": {"title": "", "tax_id": "", "tax_office": "", "address": "", "evidence": []},
                    "line_items": [
                        {
                            "canonical_line_id": line_id,
                            "source_position": "",
                            "external_line_id": "",
                            "description": "Cihaz",
                            "observed_quantity": "1",
                            "observed_unit_code": "ADET",
                            "observed_unit_price": "999.00",
                            "observed_taxable_amount": "999.00",
                            "observed_vat_rate": "10",
                            "observed_tax_amount": "99.90",
                            "observed_gross_amount": "1098.90",
                            "evidence": ["pdf:text:line:1"],
                        }
                    ],
                    "observed_vat_summary": [],
                    "observed_totals": {
                        "observed_goods_services_total": "999.00",
                        "observed_vat_total": "99.90",
                        "observed_special_tax_total": "0.00",
                        "observed_tax_inclusive_total": "1098.90",
                        "observed_payable_total": "1098.90",
                        "evidence": ["pdf:totals"],
                    },
                    "extraction_notes": [],
                }

        completed = _maybe_complete_canonical_with_ai(
            provider=Provider(),
            policy=CanonicalExtractionPolicy(enabled=True),
            document_text="Cihaz 100,00 KDV %20 odeme 120,00",
            deterministic=deterministic,
            parsed_identity={},
            parsed_totals={"payable_total": "120.00"},
            line_item_details=(),
            vat_split=SimpleNamespace(status="", lines=()),
            client_identity={},
        )

        self.assertTrue(completed.ai_used)
        self.assertEqual(completed.line_items[0].taxable_amount, "100.00")
        self.assertEqual(completed.line_items[0].vat_rate, "20")
        self.assertEqual(completed.line_items[0].tax_amount, "20.00")
        self.assertEqual(completed.line_items[0].gross_amount, "120.00")
        self.assertIn("observed_payable_total_mismatch", completed.extraction_notes)

    def test_ai_observation_binding_does_not_flag_equivalent_money_format(self) -> None:
        from app.domain.canonical_invoices import CanonicalInvoice, CanonicalInvoiceLine, with_validation
        from app.domain.pdf_invoices import _bind_ai_payload_to_deterministic_lines

        deterministic = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(
                        description="Cihaz",
                        source_position="pdf:text:line:1",
                        taxable_amount="100.00",
                        vat_rate="20",
                    ),
                ),
            )
        )
        line_id = deterministic.line_items[0].canonical_line_id

        bound = _bind_ai_payload_to_deterministic_lines(
            {
                "line_items": [
                    {
                        "canonical_line_id": line_id,
                        "description": "Cihaz",
                        "observed_taxable_amount": "100,00",
                        "observed_vat_rate": "20.00",
                        "evidence": ["pdf:text:line:1"],
                    }
                ],
                "extraction_notes": [],
            },
            deterministic,
        )

        self.assertNotIn("observed_taxable_amount_conflict", bound["extraction_notes"])
        self.assertNotIn("observed_vat_rate_conflict", bound["extraction_notes"])

    def test_private_matching_forwards_canonical_ai_runtime_to_pdf_folder_parser(self) -> None:
        invoice_dir = Path("private-invoices")
        chart_path = Path("chart.xlsx")
        provider = object()
        policy = object()
        profile = ClientProfile(
            client_id="client-1",
            title="Test Client",
            tax_id="1111111111",
            activity_description="Test activity",
            workplace_addresses=("Test address",),
            has_chart_accounts=True,
        )
        expected_run = object()

        with (
            patch("app.domain.matching_simulation.parse_invoice_folder", return_value=[]) as parse_folder,
            patch("app.domain.matching_simulation.simulate_chart_run", return_value=expected_run),
        ):
            runs = simulate_private_matching(
                invoice_dir,
                [chart_path],
                profile,
                canonical_extraction_provider=provider,
                canonical_extraction_policy=policy,
            )

        self.assertEqual(runs, [expected_run])
        parse_folder.assert_called_once_with(
            invoice_dir,
            canonical_extraction_provider=provider,
            canonical_extraction_policy=policy,
            client_identity={
                "title": "Test Client",
                "tax_id": "1111111111",
            },
        )

    def test_private_benchmark_forwards_canonical_ai_runtime(self) -> None:
        from backend.scripts import run_private_pipeline_benchmark as benchmark

        classifier = object()
        canonical_provider = object()
        canonical_policy = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "samples"
            output_root = Path(temp_dir) / "output"
            (output_root / "ai_canary" / "firma-1").mkdir(parents=True)
            firm_dir = root / "firma-1"
            (firm_dir / "invoices").mkdir(parents=True)
            chart_dir = firm_dir / "chart_accounts"
            chart_dir.mkdir(parents=True)
            chart_path = chart_dir / "chart.xlsx"
            chart_path.write_bytes(b"chart")

            with (
                patch.object(benchmark, "simulate_private_matching", return_value=[]) as simulate,
                patch.object(benchmark, "private_benchmark_summary", return_value={"invoice_count": 0}),
                patch.object(benchmark, "write_simulation_csv", return_value=output_root / "matching.csv"),
                patch.object(benchmark, "write_review_ui_json", return_value=output_root / "review.json"),
            ):
                summary = benchmark._run_one(
                    root=root,
                    output_root=output_root,
                    firm_id="firma-1",
                    run_label="ai_canary",
                    classifier=classifier,
                    canonical_extraction_provider=canonical_provider,
                    canonical_extraction_policy=canonical_policy,
                    ai_enabled=True,
                )

        self.assertEqual(summary["status"], "ok")
        simulate.assert_called_once_with(
            firm_dir / "invoices",
            [chart_path],
            benchmark._client_profile("firma-1"),
            product_classifier=classifier,
            canonical_extraction_provider=canonical_provider,
            canonical_extraction_policy=canonical_policy,
        )

    def test_private_benchmark_stage_quality_attributes_semantic_decisions(self) -> None:
        from types import SimpleNamespace
        from backend.scripts import run_private_pipeline_benchmark as benchmark

        initial = {
            "attempt_id": "attempt-1",
            "stage": "initial_account_decision",
            "canonical_line_ids": ["line-1"],
            "validated_response": {"suggested_account_code": "770.01"},
            "validation_errors": [],
            "accepted": False,
        }
        synthesis = {
            "attempt_id": "attempt-2",
            "stage": "research_synthesis",
            "canonical_line_ids": ["line-1"],
            "validated_response": {
                "suggested_account_code": "760.03.012",
                "line_decisions": [{"canonical_line_id": "line-1", "suggested_account_code": "760.03.012"}],
            },
            "validation_errors": [],
            "accepted": True,
        }
        result = SimpleNamespace(
            file_name="private.pdf",
            canonical_line_count=1,
            ai_classification_used=True,
            ai_gate_reason="cold_start_semantic_ai",
            ai_research_requested=True,
            semantic_attempts=(initial, synthesis),
            accepted_semantic_attempt_id="attempt-2",
            selected_expense_account="760.03.012",
            selected_revenue_account="",
            line_decisions=({"canonical_line_id": "line-1", "account_code": "760.03.012"},),
            canonical_validation_status="valid",
            review_reason_codes=(),
            is_balanced=True,
            export_status="export_ready",
        )

        record = benchmark._stage_quality_record(result)

        self.assertEqual(record["canonical_line_count"], 1)
        self.assertTrue(record["semantic_ai_called"])
        self.assertEqual(record["initial_account_code"], "770.01")
        self.assertTrue(record["research_requested"])
        self.assertTrue(record["research_changed_decision"])
        self.assertEqual(record["accepted_account_code"], "760.03.012")
        self.assertFalse(record["deterministic_account_substitution"])
        self.assertEqual(record["semantic_attempt_count"], 2)
        self.assertTrue(record["line_coverage_ok"])
        self.assertTrue(record["vat_reconciled"])
        self.assertTrue(record["balanced"])
        self.assertTrue(record["trace_complete"])

    def test_ubl_invoice_preview_renders_invoice_like_html(self) -> None:
        from app.domain.ubl_invoice_preview import render_ubl_invoice_preview_html

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-06</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Satici Ltd Sti</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
    <cac:PartyTaxScheme>
      <cbc:CompanyID>1111111111</cbc:CompanyID>
      <cac:TaxScheme><cbc:Name>KADIKOY</cbc:Name></cac:TaxScheme>
    </cac:PartyTaxScheme>
    <cac:PostalAddress>
      <cbc:StreetName>Bagdat Cad.</cbc:StreetName>
      <cbc:BuildingNumber>10</cbc:BuildingNumber>
      <cbc:CityName>Istanbul</cbc:CityName>
    </cac:PostalAddress>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Alici Ltd Sti</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">2</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Isitme cihazi bakim seti</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="TRY">50.00</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal><cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="TRY">100.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="TRY">20.00</cbc:TaxAmount>
      <cbc:Percent>20</cbc:Percent>
    </cac:TaxSubtotal></cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:TaxTotal><cac:TaxSubtotal>
    <cbc:TaxableAmount currencyID="TRY">100.00</cbc:TaxableAmount>
    <cbc:TaxAmount currencyID="TRY">20.00</cbc:TaxAmount>
    <cbc:Percent>20</cbc:Percent>
  </cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="TRY">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="TRY">120.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>"""

        html = render_ubl_invoice_preview_html(xml)

        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("ABC2026000000001", html)
        self.assertIn("Satici Ltd Sti", html)
        self.assertIn("Alici Ltd Sti", html)
        self.assertIn("KADIKOY", html)
        self.assertIn("Bagdat Cad.", html)
        self.assertIn("Isitme cihazi bakim seti", html)
        self.assertIn("120.00", html)
        self.assertNotIn("<dd>-</dd>", html)
        self.assertNotIn("<Invoice", html)

    def test_pdf_vat_split_extracts_real_pilot_table_and_summary_evidence(self) -> None:
        cases = [
            (
                ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "purchases" / "6200031354_20D2026000003801.pdf",
                (("1", "795.75", "7.96"), ("20", "116.58", "23.32")),
                "912.33",
                "31.28",
                "943.61",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "purchases" / "1640731289_AAA2026000001303.pdf",
                (("0", "344390.64", "0.00"),),
                "344390.64",
                "0.00",
                "344390.64",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "purchases" / "1640731289_AAA2026000001222.pdf",
                (("20", "94447.80", "18889.56"),),
                "94447.80",
                "18889.56",
                "113337.36",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "purchases" / "1640731289_AAA2026000001172.pdf",
                (("0", "13660.00", "0.00"), ("20", "2500.20", "500.04")),
                "16160.20",
                "500.04",
                "16660.24",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "purchases" / "30007700894_EFR2026000010819.pdf",
                (("20", "248.33", "49.67"),),
                "248.33",
                "49.67",
                "298.00",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "purchases" / "9860008925_YKA2026002672767.pdf",
                (("20", "322.08", "64.42"),),
                "322.08",
                "64.42",
                "386.50",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "sales" / "16973036588_VEÇHİYE YÜRÜKCÜ_AAR2026000000002.pdf",
                (("0", "28000.00", "0.00"),),
                "28000.00",
                "0.00",
                "28000.00",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "purchases" / "1061386125_AVQ2026000000026.pdf",
                (("10", "3090.90", "309.09"),),
                "3090.90",
                "309.09",
                "3399.99",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-2" / "invoices" / "sales" / "46633788588_MELAHAT BİLGİÇ_AAF2026000000004.pdf",
                (("0", "51000.00", "0.00"), ("20", "2500.00", "500.00")),
                "53500.00",
                "500.00",
                "54000.00",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "purchases" / "44513097980_WOO2026000000033.pdf",
                (("0", "105.01", "0.00"), ("10", "146.12", "14.61")),
                "251.13",
                "14.61",
                "265.74",
            ),
            (
                ROOT
                / "private_samples"
                / "real_pilot"
                / "firma-3"
                / "invoices"
                / "sales"
                / "einvoice.1a78033e-af6d-498e-8252-28c5b9132ccb.IF02026000000013.pdf",
                (("20", "15999.90", "3199.98"),),
                "15999.90",
                "3199.98",
                "19199.88",
            ),
        ]
        for path, expected_lines, goods_total, vat_total, payable_total in cases:
            if not path.exists():
                self.skipTest(f"private pilot invoice sample missing: {path}")

            invoice = parse_pdf_invoice(path)

            self.assertEqual(invoice.vat_split_status, "exact", path.name)
            self.assertEqual(
                tuple((line.rate, line.taxable_amount, line.tax_amount) for line in invoice.vat_split_lines),
                expected_lines,
                path.name,
            )
            self.assertEqual(invoice.goods_services_total, goods_total, path.name)
            self.assertEqual(invoice.vat_total, vat_total, path.name)
            self.assertEqual(invoice.payable_total, payable_total, path.name)

    def test_pdf_vat_split_derives_vat_when_invoice_total_has_non_vat_amounts(self) -> None:
        cases = [
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "purchases" / "4810577635_AS02026000752460.pdf",
                (("20", "580.81", "116.16"),),
                "580.81",
                "116.16",
                "700.00",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "purchases" / "7350150917_AFM2026051201795.pdf",
                (("20", "546.40", "109.28"),),
                "546.40",
                "109.28",
                "899.90",
            ),
            (
                ROOT / "private_samples" / "real_pilot" / "firma-1" / "invoices" / "purchases" / "8590380323_GB22026004259480.pdf",
                (("20", "191.30", "38.26"),),
                "191.30",
                "38.26",
                "275.75",
            ),
            (
                Path.home()
                / "Downloads"
                / "einvoice.517717e1-f2c4-44ea-81c3-a1678faa754b.VP12026000173542.pdf",
                (("10", "110.22", "11.02"),),
                "110.22",
                "11.02",
                "121.00",
            ),
        ]
        for path, expected_lines, goods_total, vat_total, payable_total in cases:
            if not path.exists():
                self.skipTest(f"private pilot invoice sample missing: {path}")

            invoice = parse_pdf_invoice(path)

            self.assertEqual(invoice.vat_split_status, "derived", path.name)
            self.assertEqual(
                tuple((line.rate, line.taxable_amount, line.tax_amount) for line in invoice.vat_split_lines),
                expected_lines,
                path.name,
            )
            self.assertEqual(invoice.goods_services_total, goods_total, path.name)
            self.assertEqual(invoice.vat_total, vat_total, path.name)
            self.assertEqual(invoice.payable_total, payable_total, path.name)

    def test_real_pilot_bera_invoice_extracts_issuer_title_for_counterparty_matching(self) -> None:
        invoice_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-2"
            / "invoices"
            / "purchases"
            / "1640731289_AAA2026000001172.pdf"
        )
        chart_path = ROOT / "private_samples" / "real_pilot" / "firma-2" / "chart_accounts" / "orhan hs planı.xlsx"
        if not invoice_path.exists() or not chart_path.exists():
            self.skipTest("private pilot BERA sample missing")

        invoice = parse_pdf_invoice(invoice_path)
        accounts = parse_chart_accounts(chart_path)

        self.assertEqual(invoice.issuer_title, "BERA ODYOLOJİ TİCARET LİMİTED ŞİRKETİ")
        counterparty = match_counterparty(
            accounts,
            tax_ids=(invoice.issuer_tax_id,),
            name_hint=invoice.issuer_title,
            account_prefixes=("320",),
        )
        self.assertEqual(counterparty.account_code, "320.B04")
        self.assertEqual(counterparty.match_reason, "title_token_overlap")

    def test_counterparty_title_overlap_ignores_legal_suffix_only_matches(self) -> None:
        accounts = [
            ChartAccount("320.B04", "320.B04", "BERA ODYOLOJİ SAN TİC LTD ŞTİ", is_detail_account=True),
        ]

        counterparty = match_counterparty(
            accounts,
            name_hint="METRO GROSMARKET BAKIRKÖY ALIŞVERİŞ HİZMETLERİ TİC. LTD. ŞTİ.",
            account_prefixes=("320",),
        )

        self.assertEqual(counterparty.match_reason, "not_found")

    def test_real_pilot_dmarket_invoice_ignores_carrier_tax_id_for_issuer_title(self) -> None:
        invoice_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-1"
            / "invoices"
            / "purchases"
            / "2650179910_HD02026000279063.pdf"
        )
        if not invoice_path.exists():
            self.skipTest("private pilot D-Market sample missing")

        invoice = parse_pdf_invoice(invoice_path)

        self.assertEqual(invoice.issuer_tax_id, "2650179910")
        self.assertEqual(invoice.issuer_title, "D-MARKET ELEKTRONİK HİZMETLER VE TİCARET ANONİM ŞİRKETİ")

    def test_vat_split_review_record_keeps_layout_evidence_for_future_rules(self) -> None:
        exact_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-3"
            / "invoices"
            / "sales"
            / "einvoice.1a78033e-af6d-498e-8252-28c5b9132ccb.IF02026000000013.pdf"
        )
        derived_path = (
            ROOT
            / "private_samples"
            / "real_pilot"
            / "firma-1"
            / "invoices"
            / "purchases"
            / "4810577635_AS02026000752460.pdf"
        )
        if not exact_path.exists() or not derived_path.exists():
            self.skipTest("private pilot invoice sample missing")

        exact_record = build_vat_split_review_record(parse_pdf_invoice(exact_path), document_ref="doc-exact")
        derived_record = build_vat_split_review_record(parse_pdf_invoice(derived_path), document_ref="doc-derived")

        self.assertFalse(exact_record.requires_accountant_review)
        self.assertEqual(exact_record.confidence, "exact_total_validated")
        self.assertEqual(exact_record.similarity_key, "vat_split:exact:20:vat_split_gross_total_validated")
        self.assertEqual(exact_record.lines[0].taxable_amount, "15999.90")
        self.assertTrue(exact_record.learning_candidate)
        self.assertFalse(exact_record.automation_candidate)

        self.assertFalse(derived_record.requires_accountant_review)
        self.assertEqual(derived_record.confidence, "vat_amounts_validated_non_vat_total")
        self.assertEqual(derived_record.review_reason_codes, ("vat_split_non_vat_total",))
        self.assertEqual(derived_record.lines[0].tax_amount, "116.16")
        self.assertEqual(vat_split_review_payload(derived_record)["status"], "derived")

    def test_pdf_invoice_route_returns_notes_tuple_for_journal_candidate(self) -> None:
        route, notes = build_route(
            (),
            {
                "invoice_no": "ABC2026000000001",
                "issue_date": "01.05.2026",
                "payable_total": "1200.00",
            },
        )

        self.assertEqual(route, "journal_candidate")
        self.assertEqual(notes, ())

    def test_invoice_operation_run_splits_journals_and_review_tasks(self) -> None:
        journal_invoice = ParsedInvoice(
            file_name="normal.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
        )
        review_invoice = ParsedInvoice(
            file_name="mixed.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="DEF2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("10", "20"),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
        )

        run = run_invoice_operations([journal_invoice, review_invoice])

        self.assertEqual(len(run.journal_entries), 1)
        self.assertEqual(len(run.review_tasks), 1)
        self.assertTrue(run.journal_entries[0].is_balanced)
        self.assertIsInstance(run.review_tasks[0], ReviewTaskDraft)
        self.assertEqual(vat_rate_decimal(journal_invoice), Decimal("0.20"))

    def test_matching_simulation_creates_review_draft_for_risky_positive_invoice(self) -> None:
        invoice = ParsedInvoice(
            file_name="mixed.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="DEF2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("10", "20"),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
            line_items=("Mixed VAT sale awaiting split",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection, _task3_profile())

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_quality, "gross_balanced_needs_vat_split")
        self.assertTrue(result.is_balanced)
        self.assertEqual(len(result.draft_lines), 3)

    def test_matching_simulation_requires_client_profile_for_export(self) -> None:
        invoice = ParsedInvoice(
            file_name="rexton.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.export_status, "review_required")
        self.assertIn("onboarding_missing_client_profile", result.review_reason_codes)

    def test_sales_invoice_uses_revenue_and_sales_vat_accounts(self) -> None:
        invoice = ParsedInvoice(
            file_name="sales.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SLS2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("SAYIN Musteri A",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            zero_vat_revenue_account="600.00.3065",
            sales_vat_account="391.20",
            customer_account="120.01",
            next_customer_account="120.M03",
            next_supplier_account="320.M03",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.selected_revenue_account, "600.20")
        self.assertEqual(result.selected_sales_vat_account, "391.20")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.selected_purchase_vat_account, "")
        self.assertEqual(result.suggested_counterparty_account, "120.9999999999")
        self.assertEqual(result.counterparty_creation_suggestion["suggested_code"], "120.9999999999")
        account_codes = [line["account_code"] for line in result.draft_lines]
        self.assertEqual(account_codes, ["120.9999999999", "600.20", "391.20"])

    def test_sales_title_match_uses_existing_customer_and_keeps_new_counterparty_suggestion(self) -> None:
        invoice = ParsedInvoice(
            file_name="sales-title-match.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SLS2026000000009",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_title="Isitme Merkezi A",
            issuer_tax_id="1234567890",
            recipient_title="Alici Firma",
            recipient_tax_id="9999999999",
            line_items=("Servis satisi",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        counterparty = CounterpartyMatch(
            account_code="120.A01",
            account_name="Alici Firma",
            confidence=82,
            match_reason="title_similarity",
            requires_review=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, counterparty, processing_mode="controlled_automation")

        self.assertEqual(result.selected_customer_account, "120.A01")
        self.assertEqual(result.suggested_counterparty_account, "120.9999999999")
        self.assertEqual(result.draft_lines[0]["account_code"], "120.A01")
        self.assertIn("counterparty_title_similarity", result.review_reason_codes)
        self.assertEqual(result.counterparty_creation_suggestion["suggested_code"], "120.9999999999")

    def test_zero_vat_sales_uses_3065_revenue_without_vat_line(self) -> None:
        invoice = ParsedInvoice(
            file_name="zero-sales.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="ISTISNA",
            invoice_type="SATIS",
            invoice_no="SLS2026000000002",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("0",),
            goods_services_total="1000.00",
            vat_total="0.00",
            special_tax_total="",
            tax_inclusive_total="1000.00",
            payable_total="1000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("SAYIN Musteri A",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            zero_vat_revenue_account="600.00.3065",
            sales_vat_account="391.20",
            customer_account="120.01",
            next_customer_account="120.M03",
            next_supplier_account="320.M03",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.selected_revenue_account, "600.00.3065")
        self.assertEqual(result.selected_sales_vat_account, "")
        self.assertEqual(len(result.draft_lines), 2)
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["120.9999999999", "600.00.3065"])
        self.assertNotIn("391.20", [line["account_code"] for line in result.draft_lines])

    def test_hearing_device_sales_with_vat_uses_3065_and_requires_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="device-sales-with-vat.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SLS2026000000003",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton isitme cihazi satisi",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            zero_vat_revenue_account="600.00.3065",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.selected_revenue_account, "600.00.3065")
        self.assertEqual(result.selected_sales_vat_account, "")
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["120.9999999999", "600.00.3065"])
        self.assertIn("hearing_device_vat_should_be_zero", result.review_reason_codes)
        self.assertEqual(result.export_status, "review_required")

    def test_purchase_invoice_uses_purchase_accounts_and_skips_revenue_fields(self) -> None:
        invoice = ParsedInvoice(
            file_name="purchase.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="PUR2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("SAYIN Isitme Merkezi A", "Rexton RLi 20"),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="153.01.001",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            zero_vat_revenue_account="600.00.3065",
            sales_vat_account="391.20",
            customer_account="120.01",
            next_customer_account="120.M03",
            next_supplier_account="320.M03",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertEqual(result.selected_purchase_vat_account, "191.20")
        self.assertEqual(result.selected_revenue_account, "")
        self.assertEqual(result.selected_sales_vat_account, "")
        self.assertEqual(result.suggested_counterparty_account, "320.9999999999")
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["153.01.001", "191.20", "320.9999999999"])

    def test_invoice_draft_descriptions_come_from_chart_account_names(self) -> None:
        invoice = ParsedInvoice(
            file_name="chart-name-descriptions.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="PUR2026000000033",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton isitme cihazi",),
        )
        accounts = [
            ChartAccount("153.01.001", "153.01.001", "Rexton stok hesabi", is_detail_account=True),
            ChartAccount("191.01.020", "191.01.020", "Rexton indirilecek KDV 20", is_detail_account=True),
            ChartAccount("320.01.015", "320.01.015", "Rexton Medikal cari", is_detail_account=True, tax_id="9999999999"),
            ChartAccount("120.01.001", "120.01.001", "Alici cari", is_detail_account=True),
            ChartAccount("600.01.020", "600.01.020", "Satislar 20", is_detail_account=True),
            ChartAccount("391.01.020", "391.01.020", "Hesaplanan KDV 20", is_detail_account=True),
            ChartAccount("102.01", "102.01", "Banka", is_detail_account=True),
        ]
        selection = select_accounts("chart.xlsx", accounts)
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        counterparty = CounterpartyMatch(
            account_code="320.01.015",
            account_name="Rexton Medikal cari",
            confidence=100,
            match_reason="tax_id_exact",
            requires_review=False,
        )

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            counterparty,
            classification_override=ProductClassification(
                raw_line="Rexton isitme cihazi",
                category="hearing_aid",
                confidence=95,
                evidence=("test_stock_treatment",),
            ),
            processing_mode="controlled_automation",
        )

        self.assertEqual(
            result.draft_lines,
            (
                {"account_code": "153.01.001", "description": "Rexton stok hesabi", "debit": "1000.00", "credit": "0.00"},
                {"account_code": "191.01.020", "description": "Rexton indirilecek KDV 20", "debit": "200.00", "credit": "0.00", "tax_rate": "20.0000"},
                {"account_code": "320.01.015", "description": "Rexton Medikal cari", "debit": "0.00", "credit": "1200.00"},
            ),
        )

    def test_account_selection_carries_full_chart_account_name_map(self) -> None:
        accounts = [
            ChartAccount("153", "153", "Ticari mallar", is_detail_account=False),
            ChartAccount("153.01.001", "153.01.001", "Ticari mal detay", is_detail_account=True),
            ChartAccount("102.01", "102.01", "Banka hesabi", is_detail_account=True),
            ChartAccount("360.01", "360.01", "Odenecek vergiler", is_detail_account=True),
            ChartAccount("320.01.015", "320.01.015", "Rexton Medikal cari", is_detail_account=True),
        ]

        selection = select_accounts("chart.xlsx", accounts)

        self.assertEqual(selection.account_names["102.01"], "Banka hesabi")
        self.assertEqual(selection.account_names["360.01"], "Odenecek vergiler")
        self.assertEqual(selection.account_names["153"], "Ticari mallar")

    def test_purchase_intake_handles_supplier_perspective_sales_pdf(self) -> None:
        invoice = ParsedInvoice(
            file_name="purchase-tab.pdf",
            provider_hint="Avrupa Yakasi Online",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="AVQ2026000000026",
            ettn="",
            issue_date="13.05.2026",
            tax_ids=("30052309394", "1061386125"),
            vat_rates=("10",),
            goods_services_total="3090.90",
            vat_total="309.09",
            special_tax_total="",
            tax_inclusive_total="3399.99",
            payable_total="3399.99",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("SLIM TAPER",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.001",
            supplier_account="320.A04",
            bank_account="102.01",
            selection_notes=(),
            non_deductible_account="689.01",
            sales_vat_account="391.01.010",
            revenue_account="600.01.010",
            customer_account="120.A01",
            next_supplier_account="320.A06",
            account_candidates={
                "purchase_vat": (
                    {"code": "191.01.001", "name": "KDV 1", "reason": "191 adayi"},
                    {"code": "191.01.010", "name": "Yuzde 10 KDV", "reason": "191 adayi"},
                ),
                "non_deductible": ({"code": "689.01", "name": "K.K.E Giderler", "reason": "KKEG adayi"},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="30052309394",
            tckn="30052309394",
            tax_identifier="30052309394",
            activity_description="TIBBI VE ORTOPEDIK URUNLERIN PERAKENDE TICARETI",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        counterparty = match_counterparty([], name_hint="Avrupa Yakasi Online")
        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            counterparty,
            processing_mode="controlled_automation",
            intended_direction="purchase_invoice",
        )

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertEqual(result.product_category, "personal_clothing")
        self.assertEqual(result.business_relevance_account_treatment, "non_deductible_review")
        self.assertEqual(result.selected_expense_account, "689.01")
        self.assertEqual(result.selected_purchase_vat_account, "")
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["689.01", "320.1061386125"])
        self.assertEqual(result.export_status, "review_required")
        narrative = result.decision_narrative
        self.assertEqual(narrative["invoice_product_line"], "SLIM TAPER")
        self.assertIn("giyim", narrative["fisora_interpretation"].lower())
        self.assertEqual(narrative["account_code"], "689.01")
        self.assertEqual(narrative["account_name"], "K.K.E Giderler")
        self.assertIn("Avrupa Yakasi Online", narrative["counterparty_match"])
        self.assertEqual(narrative["confidence_label"], "Yuksek")
        self.assertIn("faaliyet", narrative["unresolved_info"].lower())
        self.assertEqual(narrative["read_facts"]["Fatura urun satiri"], "SLIM TAPER")
        self.assertEqual(narrative["read_facts"]["Satici unvani"], "Avrupa Yakasi Online")
        self.assertEqual(narrative["read_facts"]["KDV orani"], "%10")
        self.assertEqual(narrative["read_facts"]["Genel toplam"], "3399.99")
        self.assertNotIn("okunamadi", str(narrative).lower())

    def test_account_selection_exposes_semantic_detail_account_candidates(self) -> None:
        selection = select_accounts(
            "chart.xlsx",
            [
                ChartAccount("153", "153", "Ticari mallar", is_detail_account=False),
                ChartAccount("153.01.001", "153.01.001", "Alinan cihazlar", is_detail_account=True),
                ChartAccount("600.00.3065", "600.00.3065", "3065 kapsaminda KDV siz satis", is_detail_account=True),
                ChartAccount("600.20", "600.20", "Yurt ici satislar yuzde 20", is_detail_account=True),
                ChartAccount("191.20", "191.20", "Indirilecek KDV yuzde 20", is_detail_account=True),
                ChartAccount("391.20", "391.20", "Hesaplanan KDV yuzde 20", is_detail_account=True),
                ChartAccount("770.02.001", "770.02.001", "Disaridan alinan fayda hizmet", is_detail_account=True),
                ChartAccount("120.A02", "120.A02", "Alici Ayla", is_detail_account=True),
                ChartAccount("320.R02", "320.R02", "Rexton Medikal", is_detail_account=True),
            ],
        )

        self.assertEqual(selection.stock_account, "153.01.001")
        self.assertEqual(selection.zero_vat_revenue_account, "600.00.3065")
        self.assertEqual(selection.account_candidates["purchase_stock"][0]["code"], "153.01.001")
        self.assertEqual(selection.account_candidates["purchase_stock"][0]["name"], "Alinan cihazlar")
        self.assertIn("153", selection.account_candidates["purchase_stock"][0]["reason"])
        self.assertEqual(selection.account_candidates["sales_revenue"][0]["code"], "600.00.3065")
        self.assertEqual(selection.account_candidates["purchase_expense"][0]["code"], "770.02.001")

    def test_purchase_stock_classification_uses_153_candidate_and_keeps_manual_candidates(self) -> None:
        invoice = ParsedInvoice(
            file_name="stock-purchase.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="STK2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "Alinan cihazlar", "reason": "153 ticari mal adayi"},),
                "purchase_expense": ({"code": "770.02.001", "name": "Disaridan alinan hizmet", "reason": "7xx gider adayi"},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertEqual(result.draft_lines[0]["account_code"], "153.01.001")
        self.assertEqual(result.account_candidates["purchase_stock"][0]["code"], "153.01.001")
        self.assertEqual(result.account_candidates["purchase_expense"][0]["code"], "770.02.001")

    def test_purchase_battery_uses_battery_stock_account(self) -> None:
        invoice = ParsedInvoice(
            file_name="battery-purchase.pdf",
            provider_hint="Pil Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="PIL2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Pil ve kalip montaj kit alisi",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": (
                    {"code": "153.01.001", "name": "Alinan cihazlar", "reason": "153 ticari mal adayi"},
                    {"code": "153.01.002", "name": "Pil ve kalip montaj kit alis", "reason": "153 ticari mal adayi"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.selected_expense_account, "153.01.002")
        self.assertEqual(result.draft_lines[0]["account_code"], "153.01.002")

    def test_purchase_cargo_uses_distribution_cargo_expense_not_stock(self) -> None:
        invoice = ParsedInvoice(
            file_name="cargo-purchase.pdf",
            provider_hint="Kargo Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="KRG2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kargo bedeli",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "Alinan cihazlar", "reason": "153 ticari mal adayi"},),
                "purchase_expense": (
                    {"code": "770.02.001", "name": "Disaridan alinan hizmet", "reason": "7xx gider adayi"},
                    {"code": "760.03.012", "name": "Kargo giderleri", "reason": "7xx gider adayi"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "kargo",
                "confidence": 95,
                "reason": "Canonical satir kargo hizmetini gosteriyor.",
                "evidence": ["ai:canonical_line"],
                "suggested_account_code": "760.03.012",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Gercek hesap plani adaylari icinden kargo gideri secildi.",
                "product_identity": "Kargo hizmeti",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            product_classifier=classifier,
            processing_mode="controlled_automation",
        )

        self.assertEqual(result.business_relevance_account_treatment, "expense")
        self.assertEqual(result.selected_expense_account, "760.03.012")
        self.assertEqual(result.draft_lines[0]["account_code"], "760.03.012")

    def test_purchase_vehicle_rental_uses_vehicle_distribution_subaccount(self) -> None:
        invoice = ParsedInvoice(
            file_name="vehicle-rental.pdf",
            provider_hint="Arac Kiralama",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ARK2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Arac kiralama bedeli",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.008",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "770.02.008", "name": "Isyeri kira giderleri", "reason": "7xx gider adayi"},
                    {"code": "760.03.002", "name": "Arac kiralama gideri", "reason": "7xx gider adayi"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.selected_expense_account, "760.03.002")
        self.assertEqual(result.draft_lines[0]["account_code"], "760.03.002")

    def test_return_invoice_with_accepted_semantic_authority_preserves_reversal_arithmetic(self) -> None:
        invoice = ParsedInvoice(
            file_name="return.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="IADE",
            invoice_type="IADE",
            invoice_no="RET2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_title="Isitme Merkezi A",
            issuer_tax_id="1234567890",
            recipient_title="Alici Firma",
            recipient_tax_id="9999999999",
            is_return_invoice=True,
            line_items=("Iade edilen servis",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.draft_entry_type, "sales_return")
        self.assertEqual(result.total_debit, result.total_credit)
        self.assertTrue(result.draft_lines)
        self.assertEqual(result.selected_revenue_account, "600.20")
        self.assertEqual(result.selected_sales_vat_account, "391.20")
        self.assertEqual(result.ai_resolution_status, "resolved")
        self.assertEqual(result.line_decisions[0]["decision_source"], "accepted_ai")
        self.assertIn("return_invoice_manual_review", result.review_reason_codes)
        self.assertIn("return_invoice_accountant_review", result.review_reason_codes)

    def test_explicit_issuer_recipient_drives_direction_before_tax_id_order(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="supplier-sales.xml",
            provider_hint="Isitme Merkezi A",
            page_count=0,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_title="Tedarikci Firma",
            issuer_tax_id="9999999999",
            recipient_title="Isitme Merkezi A",
            recipient_tax_id="1234567890",
            line_items=("Tedarik hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, intended_direction="purchase")

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertEqual(result.selected_vat_account, "191.20")
        self.assertIn("client_tax_id_matches_recipient", result.direction_evidence)

    def test_safe_direction_conflict_requires_accountant_question(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="wrong-sales-upload.xml",
            provider_hint="Tedarikci Firma",
            page_count=0,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="ABC2026000000002",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_title="Tedarikci Firma",
            issuer_tax_id="9999999999",
            recipient_title="Isitme Merkezi A",
            recipient_tax_id="1234567890",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, intended_direction="sales_invoice")

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertEqual(result.direction_conflict["status"], "needs_review")
        self.assertEqual(result.direction_conflict["intake_direction"], "sales")
        self.assertEqual(result.direction_conflict["detected_direction"], "purchase")
        self.assertIn("Alış yönüne geçirilsin mi?", result.direction_conflict["question_tr"])
        self.assertIn("direction_conflict_review", result.review_reason_codes)
        self.assertEqual(result.export_status, "review_required")

    def test_low_confidence_direction_difference_does_not_open_conflict_question(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="weak-sales-upload.pdf",
            provider_hint="Tedarikci Firma",
            page_count=1,
            text_extractable=True,
            extracted_char_count=900,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="ABC2026000000003",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999",),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, intended_direction="sales_invoice")

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertLess(result.direction_confidence, 80)
        self.assertEqual(result.direction_conflict, {})
        self.assertNotIn("direction_conflict_review", result.review_reason_codes)

    def test_select_accounts_prefers_deep_rate_specific_chart_accounts(self) -> None:
        accounts = [
            ChartAccount("191", "191", "Indirilecek KDV", False),
            ChartAccount("191.01", "191.01", "Indirilecek KDV genel", False),
            ChartAccount("191.01.020", "191.01.020", "Indirilecek KDV yuzde 20", True),
            ChartAccount("391.01.020", "391.01.020", "Hesaplanan KDV %20", True),
            ChartAccount("600.01", "600.01", "Satislar", False),
            ChartAccount("600.01.020", "600.01.020", "Satislar yuzde 20", True),
            ChartAccount("600.00.3065", "600.00.3065", "3065 kapsaminda 0 KDV satislar", True),
            ChartAccount("770.01.001", "770.01.001", "Genel giderler", True),
            ChartAccount("120.A01", "120.A01", "Alici cari", True),
            ChartAccount("320.A01", "320.A01", "Satici cari", True),
            ChartAccount("102.01", "102.01", "Banka", True),
        ]

        selection = select_accounts("chart.xlsx", accounts)

        self.assertEqual(selection.purchase_vat_account, "191.01.020")
        self.assertEqual(selection.sales_vat_account, "391.01.020")
        self.assertEqual(selection.revenue_account, "600.01.020")
        self.assertEqual(selection.zero_vat_revenue_account, "600.00.3065")
        self.assertIn("purchase_vat", selection.account_candidates)
        self.assertEqual(selection.next_customer_account, "120.A02")

    def test_mixed_vat_sales_uses_line_details_and_rate_specific_accounts(self) -> None:
        invoice = ParsedInvoice(
            file_name="mixed-sales.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="MIX2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("10", "20"),
            goods_services_total="1900.00",
            vat_total="300.00",
            special_tax_total="",
            tax_inclusive_total="2200.00",
            payable_total="2200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Pil satisi", "Cihaz satisi"),
            line_item_details=(
                InvoiceLine(raw_text="Pil satisi 1100,00", description="Pil satisi", amount_hint="1100,00"),
                InvoiceLine(raw_text="Cihaz satisi 1200,00", description="Cihaz satisi", amount_hint="1200,00"),
            ),
            issuer_title="Isitme Merkezi A",
            issuer_tax_id="1234567890",
            recipient_title="Alici Firma",
            recipient_tax_id="9999999999",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
            account_candidates={
                "sales_revenue": (
                    {"code": "600.10", "name": "Satislar %10", "reason": ""},
                    {"code": "600.20", "name": "Satislar %20", "reason": ""},
                ),
                "sales_vat": (
                    {"code": "391.10", "name": "Hesaplanan KDV %10", "reason": ""},
                    {"code": "391.20", "name": "Hesaplanan KDV %20", "reason": ""},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_entry_type, "mixed_vat_sales")
        self.assertEqual(result.total_debit, result.total_credit)
        self.assertEqual(result.draft_lines[1]["account_code"], "600.10")
        self.assertEqual(result.draft_lines[2]["account_code"], "600.20")
        self.assertEqual(result.draft_lines[3]["account_code"], "391.10")
        self.assertEqual(result.draft_lines[4]["account_code"], "391.20")
        self.assertNotIn("mixed_vat_accountant_review", result.review_reason_codes)

    def test_exact_vat_split_sales_uses_rate_summary_when_line_amounts_missing(self) -> None:
        invoice = ParsedInvoice(
            file_name="ranamed-mixed-sales.pdf",
            provider_hint="Tel: e-Posta: ranamedmedikal@gmail.com",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="EARSIVFATURA",
            invoice_type="SATIS",
            invoice_no="RNH2026000000003",
            ettn="",
            issue_date="15.05.2026",
            tax_ids=("7342497874", "46141426750"),
            vat_rates=("10", "20"),
            goods_services_total="23257.58",
            vat_total="3742.42",
            special_tax_total="",
            tax_inclusive_total="27000.00",
            payable_total="27000.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("22507 REM PRIMUS", "22509 HI-PRO 2 PROGRAMLAMA CIHAZI", "22510 NOAHLINK WIRELESS"),
            line_item_details=(
                InvoiceLine(raw_text="22507 REM PRIMUS", description="22507 REM PRIMUS", vat_rate="10", tax_amount="909,09"),
                InvoiceLine(raw_text="22509 HI-PRO 2 PROGRAMLAMA CIHAZI", description="22509 HI-PRO 2 PROGRAMLAMA CIHAZI", vat_rate="20", tax_amount="1.583,33"),
                InvoiceLine(raw_text="22510 NOAHLINK WIRELESS", description="22510 NOAHLINK WIRELESS", vat_rate="20", tax_amount="1.250,00"),
            ),
            issuer_title="RANAMED MEDIKAL",
            issuer_tax_id="7342497874",
            recipient_title="Semra Goktas",
            recipient_tax_id="46141426750",
            vat_split_status="exact",
            vat_split_lines=(
                VatSplitLine(rate="10", taxable_amount="9090.91", tax_amount="909.09", source="pdf_summary_table", evidence=("expected_tax:909.09",)),
                VatSplitLine(rate="20", taxable_amount="14166.67", tax_amount="2833.33", source="pdf_summary_table", evidence=("expected_tax:2833.33",)),
            ),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.01.020",
            sales_vat_account="391.01.020",
            customer_account="120.01.S01",
            account_candidates={
                "sales_revenue": (
                    {"code": "600.01.010", "name": "Yuzde 10 Satislar", "reason": ""},
                    {"code": "600.01.020", "name": "Yuzde 20 Satislar", "reason": ""},
                ),
                "sales_vat": (
                    {"code": "391.01.010", "name": "Yuzde 10 Hesaplanan KDV", "reason": ""},
                    {"code": "391.01.020", "name": "Yuzde 20 Hesaplanan KDV", "reason": ""},
                ),
            },
        )
        profile = ClientProfile(
            client_id="ranamed",
            title="RANAMED MEDIKAL",
            tax_id="7342497874",
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.draft_entry_type, "mixed_vat_sales")
        self.assertEqual(result.draft_quality, "line_decision_grouped_draft")
        self.assertEqual(result.selected_customer_account, "120.46141426750")
        self.assertEqual(result.suggested_counterparty_account, "120.46141426750")
        self.assertEqual(
            result.draft_lines,
            (
                {"account_code": "120.46141426750", "description": "", "debit": "27000.00", "credit": "0.00"},
                {"account_code": "600.01.010", "description": "Yuzde 10 Satislar", "debit": "0.00", "credit": "9090.91"},
                {"account_code": "600.01.020", "description": "Yuzde 20 Satislar", "debit": "0.00", "credit": "14166.67"},
                {"account_code": "391.01.010", "description": "Yuzde 10 Hesaplanan KDV", "debit": "0.00", "credit": "909.09", "tax_rate": "10.0000"},
                {"account_code": "391.01.020", "description": "Yuzde 20 Hesaplanan KDV", "debit": "0.00", "credit": "2833.33", "tax_rate": "20.0000"},
            ),
        )
        self.assertIn("counterparty_missing", result.review_reason_codes)
        self.assertNotIn("mixed_vat_manual_review", result.review_reason_codes)
        self.assertIn("KDV oranlari", result.accountant_explanation_tr)

    def test_solved_mixed_vat_purchase_can_be_export_ready(self) -> None:
        invoice = ParsedInvoice(
            file_name="mixed-purchase.pdf",
            provider_hint="Tedarikci A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="MP2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("10", "20"),
            goods_services_total="2000.00",
            vat_total="300.00",
            special_tax_total="",
            tax_inclusive_total="2300.00",
            payable_total="2300.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kargo hizmeti", "Kargo hizmeti"),
            line_item_details=(
                InvoiceLine(raw_text="Kargo hizmeti 1100,00", description="Kargo hizmeti", amount_hint="1100,00"),
                InvoiceLine(raw_text="Kargo hizmeti 1200,00", description="Kargo hizmeti", amount_hint="1200,00"),
            ),
            issuer_title="Tedarikci A",
            issuer_tax_id="9999999999",
            recipient_title="Isitme Merkezi A",
            recipient_tax_id="1234567890",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
            account_candidates={
                "purchase_stock": (
                    {"code": "153.01", "name": "Ticari mal stogu", "reason": ""},
                ),
                "purchase_vat": (
                    {"code": "191.10", "name": "Indirilecek KDV %10", "reason": ""},
                    {"code": "191.20", "name": "Indirilecek KDV %20", "reason": ""},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve servis",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        counterparty = CounterpartyMatch(
            account_code="320.01",
            account_name="Tedarikci A",
            confidence=95,
            match_reason="tax_id",
            requires_review=False,
        )
        invoice = replace(invoice, canonical_invoice=_mechanical_canonical_invoice(invoice))
        provider = FakeProductProvider(
            {
                "category": "medikal_sarf",
                "confidence": 92,
                "reason": "Canonical satirlar satilacak medikal sarf alimidir.",
                "evidence": ["ai:canonical_lines"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Gercek hesap plani adaylari icinden stok hesabi secildi.",
                "product_identity": "Medikal sarf",
                "needs_research": False,
                "research_query": "",
                "line_decisions": [
                    {
                        "canonical_line_id": line.canonical_line_id,
                        "category": "medikal_sarf",
                        "confidence": 92,
                        "product_identity": "Medikal sarf",
                        "suggested_account_code": "153.01",
                        "reason": "Canonical line stock authority.",
                        "evidence": ["ai:canonical_line"],
                        "needs_research": False,
                        "research_query": "",
                        "risk_flags": [],
                    }
                    for line in invoice.canonical_invoice.line_items
                ],
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            counterparty,
            product_classifier=classifier,
            classification_override=ProductClassification(
                raw_line="Sarf malzeme",
                category="medikal_sarf",
                confidence=90,
                evidence=("test_stock_treatment",),
            ),
        )

        self.assertEqual(result.draft_entry_type, "mixed_vat_purchase")
        self.assertTrue(result.is_balanced)
        self.assertEqual(result.export_status, "export_ready")
        self.assertNotIn("mixed_vat_manual_review", result.review_reason_codes)

    def test_exact_vat_split_purchase_uses_rate_summary_when_line_amounts_missing(self) -> None:
        invoice = ParsedInvoice(
            file_name="mixed-purchase-summary.pdf",
            provider_hint="Tedarikci A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="MP2026000000002",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("10", "20"),
            goods_services_total="23257.58",
            vat_total="3742.42",
            special_tax_total="",
            tax_inclusive_total="27000.00",
            payable_total="27000.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Sarf malzeme", "Sarf malzeme"),
            line_item_details=(
                InvoiceLine(raw_text="Sarf malzeme", description="Sarf malzeme", vat_rate="10", tax_amount="909.09"),
                InvoiceLine(raw_text="Sarf malzeme", description="Sarf malzeme", vat_rate="20", tax_amount="2833.33"),
            ),
            issuer_title="Tedarikci A",
            issuer_tax_id="9999999999",
            recipient_title="Isitme Merkezi A",
            recipient_tax_id="1234567890",
            vat_split_status="exact",
            vat_split_lines=(
                VatSplitLine(rate="10", taxable_amount="9090.91", tax_amount="909.09", source="pdf_summary_table", evidence=("expected_tax:909.09",)),
                VatSplitLine(rate="20", taxable_amount="14166.67", tax_amount="2833.33", source="pdf_summary_table", evidence=("expected_tax:2833.33",)),
            ),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            stock_account="153.01.001",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "Ticari mallar", "reason": "153 stok adayi"},),
                "purchase_vat": (
                    {"code": "191.01.010", "name": "Indirilecek KDV %10", "reason": ""},
                    {"code": "191.01.020", "name": "Indirilecek KDV %20", "reason": ""},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve servis",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        counterparty = CounterpartyMatch(
            account_code="320.01",
            account_name="Tedarikci A",
            confidence=95,
            match_reason="tax_id_exact",
            requires_review=False,
        )

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            counterparty,
            classification_override=ProductClassification(
                raw_line="Sarf malzeme",
                category="medikal_sarf",
                confidence=90,
                evidence=("test_stock_treatment",),
            ),
        )

        self.assertEqual(result.draft_entry_type, "mixed_vat_purchase")
        self.assertEqual(result.draft_quality, "mixed_vat_purchase_ready")
        self.assertEqual(
            result.draft_lines,
            (
                {"account_code": "153.01.001", "description": "Ticari mallar", "debit": "23257.58", "credit": "0.00"},
                {"account_code": "191.01.010", "description": "Indirilecek KDV %10", "debit": "909.09", "credit": "0.00", "tax_rate": "10.0000"},
                {"account_code": "191.01.020", "description": "Indirilecek KDV %20", "debit": "2833.33", "credit": "0.00", "tax_rate": "20.0000"},
                {"account_code": "320.01", "description": "Tedarikci A", "debit": "0.00", "credit": "27000.00"},
            ),
        )
        self.assertNotIn("mixed_vat_manual_review", result.review_reason_codes)

    def test_multiline_mixed_vat_purchase_groups_lines_by_rate_and_keeps_stock_account(self) -> None:
        line_details = tuple(
            InvoiceLine(
                raw_text=f"TAMEK kalemi {index + 1}",
                description=f"TAMEK kalemi {index + 1}",
                vat_rate="1" if index < 10 else "10",
                taxable_amount="100.00",
                tax_amount="1.00" if index < 10 else "10.00",
            )
            for index in range(20)
        )
        invoice = ParsedInvoice(
            file_name="tamek-multiline.pdf",
            provider_hint="TAMEK",
            page_count=1,
            text_extractable=True,
            extracted_char_count=2400,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="TMK2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("1", "10"),
            goods_services_total="2000.00",
            vat_total="110.00",
            special_tax_total="",
            tax_inclusive_total="2110.00",
            payable_total="2110.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=tuple(line.description for line in line_details),
            line_item_details=line_details,
            issuer_title="TAMEK",
            issuer_tax_id="9999999999",
            recipient_title="Market A",
            recipient_tax_id="1234567890",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.011",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "Ticari mallar", "reason": "153 stok adayi"},),
                "purchase_expense": ({"code": "770.02.011", "name": "Isyeri Guvenligi Giderleri", "reason": "7xx gider adayi"},),
                "purchase_vat": (
                    {"code": "191.01.001", "name": "Indirilecek KDV %1", "reason": ""},
                    {"code": "191.01.010", "name": "Indirilecek KDV %10", "reason": ""},
                    {"code": "191.01.020", "name": "Indirilecek KDV %20", "reason": ""},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-market",
            title="Market A",
            tax_id="1234567890",
            activity_description="Market ve gida perakende satisi",
            nace_code="471101",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        counterparty = CounterpartyMatch(
            account_code="320.01",
            account_name="TAMEK",
            confidence=95,
            match_reason="tax_id",
            requires_review=False,
        )
        invoice = replace(invoice, canonical_invoice=_mechanical_canonical_invoice(invoice))
        provider = FakeProductProvider(
            {
                "category": "gida_alimi",
                "confidence": 92,
                "reason": "TAMEK gida kalemleri markette yeniden satis icin ticari maldir.",
                "evidence": ["tamek", "market", "gida"],
                "suggested_account_code": "153.01.001",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Gida perakende faaliyetinde stok/ticari mal hesabi uygundur.",
                "product_identity": "TAMEK gida urunleri",
                "needs_research": False,
                "research_query": "",
                "line_decisions": [
                    {
                        "canonical_line_id": line.canonical_line_id,
                        "category": "gida_alimi",
                        "confidence": 92,
                        "product_identity": "TAMEK gida urunu",
                        "suggested_account_code": "153.01.001",
                        "reason": "Canonical line stock authority.",
                        "evidence": ["ai:canonical_line"],
                        "needs_research": False,
                        "research_query": "",
                        "risk_flags": [],
                    }
                    for line in invoice.canonical_invoice.line_items
                ],
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))

        result = simulate_mechanical_invoice(invoice, selection, profile, counterparty, product_classifier=classifier)

        account_codes = [line["account_code"] for line in result.draft_lines]
        self.assertEqual(result.draft_entry_type, "mixed_vat_purchase")
        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertTrue(result.ai_classification_used)
        self.assertIn("153.01.001", account_codes)
        self.assertIn("191.01.001", account_codes)
        self.assertIn("191.01.010", account_codes)
        self.assertNotIn("770.02.011", account_codes)
        self.assertTrue(result.is_balanced)

    def test_structured_mixed_vat_purchase_with_total_mismatch_keeps_review_draft(self) -> None:
        line_details = (
            InvoiceLine(raw_text="Gida %1", description="Gida %1", vat_rate="1", taxable_amount="100.00", tax_amount="1.00"),
            InvoiceLine(raw_text="Gida %10", description="Gida %10", vat_rate="10", taxable_amount="100.00", tax_amount="10.00"),
        )
        invoice = ParsedInvoice(
            file_name="mismatch-vat.pdf",
            provider_hint="TAMEK",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="MIS2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("1", "10"),
            goods_services_total="999.00",
            vat_total="11.00",
            special_tax_total="",
            tax_inclusive_total="1010.00",
            payable_total="1010.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=tuple(line.description for line in line_details),
            line_item_details=line_details,
            issuer_title="TAMEK",
            issuer_tax_id="9999999999",
            recipient_title="Market A",
            recipient_tax_id="1234567890",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.011",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={"purchase_stock": ({"code": "153.01.001", "name": "Ticari mallar", "reason": ""},)},
        )
        profile = ClientProfile(
            client_id="client-market",
            title="Market A",
            tax_id="1234567890",
            activity_description="Market ve gida perakende satisi",
            nace_code="471101",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.draft_entry_type, "review_purchase")
        self.assertEqual(result.export_status, "review_required")
        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertNotIn("770.02.011", [line["account_code"] for line in result.draft_lines])

    def test_structured_mixed_vat_purchase_with_invalid_rate_stays_in_review(self) -> None:
        line_details = (
            InvoiceLine(raw_text="Gida %5", description="Gida %5", vat_rate="5", taxable_amount="100.00", tax_amount="5.00"),
            InvoiceLine(raw_text="Gida %20", description="Gida %20", vat_rate="20", taxable_amount="100.00", tax_amount="20.00"),
        )
        invoice = ParsedInvoice(
            file_name="invalid-vat.pdf",
            provider_hint="TAMEK",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="INV2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("5", "20"),
            goods_services_total="200.00",
            vat_total="25.00",
            special_tax_total="",
            tax_inclusive_total="225.00",
            payable_total="225.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=tuple(line.description for line in line_details),
            line_item_details=line_details,
            issuer_title="TAMEK",
            issuer_tax_id="9999999999",
            recipient_title="Market A",
            recipient_tax_id="1234567890",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.011",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={"purchase_stock": ({"code": "153.01.001", "name": "Ticari mallar", "reason": ""},)},
        )
        profile = ClientProfile(
            client_id="client-market",
            title="Market A",
            tax_id="1234567890",
            activity_description="Market ve gida perakende satisi",
            nace_code="471101",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.draft_entry_type, "review_purchase")
        self.assertEqual(result.export_status, "review_required")
        self.assertEqual(result.selected_expense_account, "153.01.001")

    def test_mixed_device_and_battery_sales_keeps_device_zero_and_battery_taxable(self) -> None:
        invoice = ParsedInvoice(
            file_name="mixed-device-battery-sales.pdf",
            provider_hint="Isitme Merkezi A",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="MDB2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890", "9999999999"),
            vat_rates=("0", "20"),
            goods_services_total="1100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="1120.00",
            payable_total="1120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton isitme cihazi satisi", "Pil satisi"),
            line_item_details=(
                InvoiceLine(raw_text="Rexton isitme cihazi satisi 1000,00", description="Rexton isitme cihazi satisi", amount_hint="1000,00"),
                InvoiceLine(raw_text="Pil satisi 120,00", description="Pil satisi", amount_hint="120,00"),
            ),
            issuer_title="Isitme Merkezi A",
            issuer_tax_id="1234567890",
            recipient_title="Alici Firma",
            recipient_tax_id="9999999999",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            zero_vat_revenue_account="600.00.3065",
            sales_vat_account="391.20",
            customer_account="120.01",
            account_candidates={
                "sales_revenue": (
                    {"code": "600.00.3065", "name": "3065 kapsaminda KDV siz satis", "reason": ""},
                    {"code": "600.20", "name": "Satislar %20", "reason": ""},
                ),
                "sales_vat": ({"code": "391.20", "name": "Hesaplanan KDV %20", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        account_codes = [line["account_code"] for line in result.draft_lines]
        self.assertEqual(result.draft_entry_type, "mixed_vat_sales")
        self.assertIn("600.00.3065", account_codes)
        self.assertIn("600.20", account_codes)
        self.assertIn("391.20", account_codes)
        self.assertNotIn("hearing_device_vat_should_be_zero", result.review_reason_codes)

    def test_mixed_vat_sales_without_line_details_keeps_sales_review_entry_type(self) -> None:
        invoice = ParsedInvoice(
            file_name="sgk-mixed-sales.pdf",
            provider_hint="SGK",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SGK",
            invoice_no="AAA2026000000007",
            ettn="",
            issue_date="30.05.2026",
            tax_ids=("45661316282", "7750409379"),
            vat_rates=("0", "20"),
            goods_services_total="15261.12",
            vat_total="3744.00",
            special_tax_total="",
            tax_inclusive_total="19005.12",
            payable_total="19005.12",
            risk_flags=("exemption_manual_review", "mixed_vat_manual_review"),
            suggested_route="review_queue",
            parse_notes=(),
            line_items=("ISITME CIHAZI RECETE BEDELI",),
            line_item_details=(),
            issuer_title="Omer Yagci",
            issuer_tax_id="45661316282",
            recipient_title="Sosyal Guvenlik Kurumu",
            recipient_tax_id="7750409379",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Omer Yagci",
            tax_id="45661316282",
            has_chart_accounts=True,
            workplace_addresses=("Istanbul",),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.draft_quality, "gross_balanced_needs_vat_split")
        self.assertEqual(result.draft_entry_type, "review_sales")
        self.assertNotEqual(result.draft_entry_type, "review_purchase")
        self.assertEqual(result.selected_revenue_account, "600.20")
        self.assertEqual(result.selected_customer_account, "120.7750409379")
        self.assertEqual(result.export_status, "review_required")

    def test_payable_total_falls_back_to_single_safe_total_candidate(self) -> None:
        parsed_totals = {
            "goods_services_total": "1000.00",
            "vat_total": "200.00",
            "special_tax_total": "",
            "tax_inclusive_total": "1200.00",
            "payable_total": "",
        }

        resolved_total, notes = resolve_payable_total(parsed_totals)

        self.assertEqual(resolved_total, "1200.00")
        self.assertIn("payable_total_fallback_tax_inclusive_total", notes)

    def test_payable_total_keeps_missing_note_when_totals_conflict(self) -> None:
        parsed_totals = {
            "goods_services_total": "1000.00",
            "vat_total": "180.00",
            "special_tax_total": "",
            "tax_inclusive_total": "1170.00",
            "payable_total": "",
        }

        resolved_total, notes = resolve_payable_total(parsed_totals)

        self.assertEqual(resolved_total, "")
        self.assertEqual(notes, ())

    def test_private_simulation_outputs_direction_and_ai_decision_fields(self) -> None:
        invoice = ParsedInvoice(
            file_name="sales.pdf",
            provider_hint="Client",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SAT2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1111111111", "2222222222"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton cihaz",),
            issuer_title="Client",
            issuer_tax_id="1111111111",
            recipient_title="Buyer",
            recipient_tax_id="2222222222",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(client_id="client-1", title="Client", tax_id="1111111111", has_chart_accounts=True)
        result = simulate_mechanical_invoice(invoice, selection, profile)
        run = SimulatedChartRun(
            chart_file_name="chart.xlsx",
            account_count=1,
            detail_account_count=1,
            customer_candidate_count=1,
            supplier_candidate_count=1,
            has_purchase_vat_191=True,
            has_sales_vat_391=True,
            account_selection=selection,
            invoice_results=(result,),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_simulation_csv([run], Path(temp_dir) / "matching.csv")
            csv_text = csv_path.read_text(encoding="utf-8-sig")
        payload = build_review_ui_payload([run])
        row = payload["invoiceRows"][0]

        self.assertIn("accounting_direction", csv_text.splitlines()[0])
        self.assertIn("draft_entry_type", csv_text.splitlines()[0])
        self.assertEqual(row["accountingDirection"], "sales")
        self.assertEqual(row["directionConfidence"], 95)
        self.assertEqual(row["draftEntryType"], "sales")
        self.assertEqual(row["selectedRevenueAccount"], "600.00.3065")
        self.assertIn("aiProviderStatus", row)

    def test_private_benchmark_summary_counts_pipeline_quality_signals(self) -> None:
        invoice = ParsedInvoice(
            file_name="sales.pdf",
            provider_hint="Client",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SAT2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1111111111", "2222222222"),
            vat_rates=("0", "20"),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=("mixed_vat_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
            line_items=("Cihaz satisi",),
            issuer_title="Client",
            issuer_tax_id="1111111111",
            recipient_title="Buyer",
            recipient_tax_id="2222222222",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.20",
            sales_vat_account="391.20",
            customer_account="120.01",
        )
        profile = ClientProfile(client_id="client-1", title="Client", tax_id="1111111111", has_chart_accounts=True)
        result = simulate_mechanical_invoice(invoice, selection, profile)
        run = SimulatedChartRun(
            chart_file_name="chart.xlsx",
            account_count=1,
            detail_account_count=1,
            customer_candidate_count=1,
            supplier_candidate_count=1,
            has_purchase_vat_191=True,
            has_sales_vat_391=True,
            account_selection=selection,
            invoice_results=(result,),
        )

        run = replace(
            run,
            invoice_results=(
                replace(
                    result,
                    canonical_validation_status="invalid",
                    canonical_extraction_notes=("canonical_ai_error:RuntimeError",),
                ),
            ),
        )
        summary = private_benchmark_summary([run], run_label="baseline", firm_id="firma-1")

        self.assertEqual(summary["firm_id"], "firma-1")
        self.assertEqual(summary["run_label"], "baseline")
        self.assertEqual(summary["invoice_count"], 1)
        self.assertEqual(summary["mixed_vat_review_count"], 1)
        self.assertEqual(summary["sales_direction_purchase_draft_count"], 0)
        self.assertEqual(summary["counterparty_missing_count"], 1)
        self.assertEqual(summary["balanced_count"], 1)
        self.assertEqual(summary["export_ready_count"], 0)
        self.assertEqual(summary["canonical_valid_count"], 0)
        self.assertEqual(summary["canonical_invalid_count"], 1)
        self.assertEqual(summary["canonical_missing_count"], 0)
        self.assertEqual(summary["canonical_ai_used_count"], 0)
        self.assertEqual(summary["canonical_ai_failure_count"], 1)
        self.assertEqual(summary["provider_failure_count"], 1)

    def test_ai_tie_breaker_can_select_stock_account_without_export_ready(self) -> None:
        invoice = ParsedInvoice(
            file_name="unknown-device.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9 receiver unit",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01",
            account_candidates={
                "purchase_stock": ({"code": "153.01", "name": "Cihaz stoku", "reason": ""},),
                "purchase_expense": ({"code": "770.01", "name": "Gider", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider(
                {
                    "category": "isitme_cihazi",
                    "confidence": 86,
                    "reason": "Isitme cihazi stok urunu.",
                    "evidence": ["ai:stock"],
                    "suggested_account_code": "153.01",
                    "suggested_counterparty_code": "320.01",
                    "risk_flags": [],
                    "account_reason": "Stok hesabi onerildi.",
                }
            ),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.product_category, "isitme_cihazi")
        self.assertEqual(result.selected_expense_account, "153.01")
        self.assertEqual(result.draft_lines[0]["account_code"], "153.01")
        self.assertEqual(result.export_status, "review_required")

    def test_simulation_batches_canonical_line_decisions_and_builds_grouped_journal(self) -> None:
        from app.domain.ai_classification import AiClassificationResult
        from app.domain.canonical_invoices import (
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            CanonicalVatSummaryLine,
            with_validation,
        )

        canonical = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(
                        description="ZX cihaz", source_position="pdf:text:line:1",
                        taxable_amount="100.00", vat_rate="20", tax_amount="20.00", gross_amount="120.00",
                    ),
                    CanonicalInvoiceLine(
                        description="Bakim hizmeti", source_position="pdf:text:line:2",
                        taxable_amount="50.00", vat_rate="0", tax_amount="0.00", gross_amount="50.00",
                    ),
                ),
                vat_summary=(
                    CanonicalVatSummaryLine(rate="20", taxable_amount="100.00", tax_amount="20.00"),
                    CanonicalVatSummaryLine(rate="0", taxable_amount="50.00", tax_amount="0.00"),
                ),
                totals=CanonicalInvoiceTotals(
                    goods_services_total="150.00", vat_total="20.00", special_tax_total="0.00",
                    tax_inclusive_total="170.00", payable_total="170.00",
                ),
            )
        )
        invoice = ParsedInvoice(
            file_name="multi-line.pdf", provider_hint="Medikal Tedarik", page_count=1,
            text_extractable=True, extracted_char_count=1200, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="ABC2026000000001", ettn="", issue_date="01.05.2026",
            tax_ids=(), vat_rates=("0", "20"), goods_services_total="150.00", vat_total="20.00",
            special_tax_total="", tax_inclusive_total="170.00", payable_total="170.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("ZX cihaz", "Bakim hizmeti"),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="760.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(), stock_account="153.01",
            account_candidates={
                "purchase_stock": ({"code": "153.01", "name": "Cihaz stogu", "reason": ""},),
                "purchase_expense": ({"code": "760.01", "name": "Bakim gideri", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1", title="Isitme Merkezi", tax_id="1234567890",
            activity_description="Isitme cihazi satis ve servis", workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )

        class BatchAwareClassifier:
            policy = AiClassificationPolicy(enabled=True, static_confidence_threshold=101)

            def __init__(self) -> None:
                self.stages: list[str] = []

            def classify(self, raw_line: str, *, supplier_hint: str = "", context: object = None) -> AiClassificationResult:
                stage = context.candidate_strategy.stage
                self.stages.append(stage)
                line_decisions = ()
                if stage == "line_batch":
                    line_decisions = (
                        {
                            "canonical_line_id": canonical.line_items[0].canonical_line_id,
                            "suggested_account_code": "153.01", "product_identity": "Isitme cihazi",
                            "reason": "Satilacak cihaz stogu.", "needs_research": False, "research_query": "",
                        },
                        {
                            "canonical_line_id": canonical.line_items[1].canonical_line_id,
                            "suggested_account_code": "760.01", "product_identity": "Bakim hizmeti",
                            "reason": "Bakim gideri.", "needs_research": False, "research_query": "",
                        },
                    )
                response = {
                    "suggested_account_code": "153.01",
                    "needs_research": False,
                    "line_decisions": list(line_decisions),
                }
                attempt = serialize_semantic_decision_attempt(
                    attempt_id="batch-aware-attempt",
                    stage="initial_account_decision",
                    canonical_line_ids=(line.canonical_line_id for line in canonical.line_items),
                    prompt_version="test-batch-v1",
                    provider="fake_llm",
                    model="fake-batch-model",
                    candidate_account_codes=context.account_candidates,
                    candidate_counterparty_codes=context.counterparty_candidates,
                    validated_response=response,
                    validation_errors=(),
                    accepted=stage == "line_batch",
                )
                return AiClassificationResult(
                    classification=ProductClassification(
                        raw_line=raw_line, category="isitme_cihazi", confidence=90,
                        evidence=("ai_schema_validated",),
                    ),
                    ai_used=stage == "line_batch", provider="fake_llm", suggested_account_code="153.01",
                    skipped_reason="" if stage == "line_batch" else "ai_provider_error",
                    product_identity="Cihaz ve bakim", line_decisions=line_decisions,
                    semantic_attempts=(attempt,),
                    accepted_semantic_attempt_id="batch-aware-attempt" if stage == "line_batch" else "",
                )

        classifier = BatchAwareClassifier()
        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier)

        self.assertEqual(classifier.stages, ["line_batch"])
        self.assertEqual(
            [decision["account_code"] for decision in result.line_decisions],
            ["153.01", "760.01"],
        )
        self.assertEqual(result.draft_quality, "line_decision_grouped_draft")
        self.assertTrue(result.is_balanced)
        self.assertTrue(result.ai_classification_used)
        self.assertNotIn("line_decision_journal_incomplete", result.review_reason_codes)

    def test_generic_yurtici_line_uses_ai_real_kargo_account(self) -> None:
        invoice = ParsedInvoice(
            file_name="yurtici-generic-line.pdf",
            provider_hint="Yurtiçi Kargo Servisi A.Ş.",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="KRG2026000000099",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Posta Hizmet Geliri",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "760.03.010", "name": "DİĞER ÇEŞİTLİ GİDER", "reason": "7xx gider adayı"},
                    {"code": "760.03.012", "name": "KARGO GİDERLERİ", "reason": "7xx gider adayı"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "kargo",
                "confidence": 90,
                "reason": "Canonical satır posta hizmetini gösteriyor.",
                "evidence": ["ai:canonical_line"],
                "suggested_account_code": "760.03.012",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Aday chart plan içinde kargo giderleri hesabı seçildi.",
                "product_identity": "Kargo hizmeti",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=70),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertFalse(result.learning_rule_applied)
        self.assertTrue(result.ai_classification_used)
        self.assertEqual(provider.requests[0].supplier_hint, "Yurtiçi Kargo Servisi A.Ş.")
        self.assertEqual(result.ai_suggested_account_code, "760.03.012")
        self.assertEqual(result.selected_expense_account, "760.03.012")
        self.assertFalse(result.static_fallback_account)

    def test_invoice_ai_gate_does_not_skip_cold_start_known_category(self) -> None:
        invoice = ParsedInvoice(
            file_name="known-cargo.pdf",
            provider_hint="Kargo Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="KRG2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kargo bedeli",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.02.001",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "770.02.001", "name": "Genel gider", "reason": "7xx gider adayi"},
                    {"code": "760.03.012", "name": "Kargo giderleri", "reason": "7xx gider adayi"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "kargo",
                "confidence": 90,
                "reason": "Canonical kargo satırı doğrulandı.",
                "evidence": ["ai:canonical_line"],
                "suggested_account_code": "760.03.012",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Kargo giderleri aday hesapta mevcut.",
                "product_identity": "Kargo hizmeti",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=70))

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertFalse(result.learning_rule_applied)
        self.assertTrue(result.ai_classification_used)
        self.assertNotEqual(result.ai_gate_reason, "static_confident")
        self.assertEqual(len(provider.requests), 1)

    def test_invoice_ai_gate_static_category_requires_semantic_ai(self) -> None:
        decision = invoice_ai_gate(
            product_category="kargo",
            product_confidence=72,
            business_relation="supporting_expense",
            account_treatment="expense",
            line_hint="Kargo bedeli",
        )

        self.assertTrue(decision.needs_ai)
        self.assertEqual(decision.reason, "cold_start_semantic_authority_required")

    def test_invoice_ai_gate_high_static_confidence_requires_semantic_ai(self) -> None:
        decision = invoice_ai_gate(
            product_category="kargo",
            product_confidence=100,
            business_relation="supporting_expense",
            account_treatment="expense",
            line_hint="Kargo bedeli",
        )

        self.assertTrue(decision.needs_ai)
        self.assertEqual(decision.reason, "cold_start_semantic_authority_required")

    def test_invoice_ai_gate_unconfirmed_pattern_requires_semantic_ai(self) -> None:
        parameters = inspect.signature(invoice_ai_gate).parameters
        self.assertIn("canonical_line_ids", parameters)
        self.assertIn("verified_rule_bindings", parameters)
        if "verified_rule_bindings" not in parameters:
            return

        decision = invoice_ai_gate(
            product_category="kargo",
            product_confidence=100,
            business_relation="supporting_expense",
            account_treatment="expense",
            line_hint="Kargo bedeli",
            canonical_line_ids=("line-1",),
            verified_rule_bindings=(
                {
                    "canonical_line_id": "line-1",
                    "account_code": "760.03.012",
                    "verified": False,
                    "preconditions_match": True,
                },
            ),
        )

        self.assertTrue(decision.needs_ai)
        self.assertEqual(decision.reason, "cold_start_semantic_authority_required")

    def test_verified_line_binding_may_skip_semantic_ai(self) -> None:
        from app.domain.canonical_invoices import (
            CanonicalInvoice,
            CanonicalInvoiceLine,
            CanonicalInvoiceTotals,
            CanonicalVatSummaryLine,
            with_validation,
        )

        canonical = with_validation(
            CanonicalInvoice(
                source="pdf_text",
                line_items=(
                    CanonicalInvoiceLine(
                        description="Kargo bedeli",
                        source_position="pdf:text:line:1",
                        taxable_amount="100.00",
                        vat_rate="20",
                        tax_amount="20.00",
                        gross_amount="120.00",
                    ),
                ),
                vat_summary=(
                    CanonicalVatSummaryLine(rate="20", taxable_amount="100.00", tax_amount="20.00"),
                ),
                totals=CanonicalInvoiceTotals(
                    goods_services_total="100.00",
                    vat_total="20.00",
                    special_tax_total="0.00",
                    tax_inclusive_total="120.00",
                    payable_total="120.00",
                ),
            )
        )
        invoice = ParsedInvoice(
            file_name="verified-rule.pdf",
            provider_hint="Kargo Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="KRG2026000000101",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kargo bedeli",),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "770.01", "name": "Genel gider", "reason": ""},
                    {"code": "760.03.012", "name": "Kargo giderleri", "reason": "", "is_detail_account": True, "is_active": True},
                ),
            },
            account_names={"760.03.012": "Kargo giderleri"},
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider({})
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )
        parameters = inspect.signature(simulate_invoice).parameters
        self.assertIn("verified_rule_bindings", parameters)
        if "verified_rule_bindings" not in parameters:
            return

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            product_classifier=classifier,
            verified_rule_authorities=(
                _task3_verified_authority(
                    canonical.line_items[0].canonical_line_id,
                    "760.03.012",
                    client_id="client-1",
                ),
            ),
        )

        self.assertFalse(result.ai_classification_used)
        self.assertEqual(result.ai_gate_reason, "verified_rule_binding")
        self.assertEqual(provider.requests, [])
        self.assertEqual(result.selected_expense_account, "760.03.012")
        self.assertEqual(result.line_decisions[0]["decision_source"], "verified_rule")
        self.assertEqual(result.draft_lines[0]["account_code"], "760.03.012")

    def test_ai_provider_failure_leaves_no_discretionary_account_substitution(self) -> None:
        class FailingProvider:
            provider_name = "failing_llm"

            def __init__(self) -> None:
                self.requests: list[AiClassificationRequest] = []

            def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
                self.requests.append(request)
                raise RuntimeError("provider unavailable")

        invoice = ParsedInvoice(
            file_name="provider-failure.pdf",
            provider_hint="Kargo Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="KRG2026000000102",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kargo bedeli",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "770.01", "name": "Genel gider", "reason": ""},
                    {"code": "760.03.012", "name": "Kargo giderleri", "reason": ""},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FailingProvider()
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=70),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier)

        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.ai_retry_reason, "ai_provider_error")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.static_fallback_account, "")
        self.assertEqual(result.draft_lines, ())

    def test_verified_binding_rejects_non_semantic_accounts_false_strings_and_incomplete_coverage(self) -> None:
        canonical = _task3_canonical_invoice(
            ("Kargo hizmeti", "100.00", "20", "20.00", "120.00"),
            ("Bakim hizmeti", "50.00", "20", "10.00", "60.00"),
        )
        invoice = ParsedInvoice(
            file_name="binding-negative-cases.xml", provider_hint="Tedarikci", page_count=0,
            text_extractable=True, extracted_char_count=900, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="T3-BIND-1", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("20",),
            goods_services_total="150.00", vat_total="30.00", special_tax_total="",
            tax_inclusive_total="180.00", payable_total="180.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(),
            line_items=("Kargo hizmeti", "Bakim hizmeti"), canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="760.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "760.01", "name": "Kargo gideri", "reason": ""},
                    {"code": "760.02", "name": "Bakim gideri", "reason": ""},
                ),
            },
            account_names={"191.20": "Indirilecek KDV", "600.01": "Yurt ici satislar"},
        )
        line_1, line_2 = (line.canonical_line_id for line in canonical.line_items)
        valid_second = {
            "canonical_line_id": line_2, "account_code": "760.02",
            "verified": True, "preconditions_match": True,
        }
        cases = {
            "purchase_vat_only_in_account_names": (
                {"canonical_line_id": line_1, "account_code": "191.20", "verified": True, "preconditions_match": True},
                valid_second,
            ),
            "sales_code_wrong_direction": (
                {"canonical_line_id": line_1, "account_code": "600.01", "verified": True, "preconditions_match": True},
                valid_second,
            ),
            "verified_string_false": (
                {"canonical_line_id": line_1, "account_code": "760.01", "verified": "false", "preconditions_match": True},
                valid_second,
            ),
            "preconditions_string_false": (
                {"canonical_line_id": line_1, "account_code": "760.01", "verified": True, "preconditions_match": "false"},
                valid_second,
            ),
            "partial": (
                {"canonical_line_id": line_1, "account_code": "760.01", "verified": True, "preconditions_match": True},
            ),
            "duplicate_partial": (
                {"canonical_line_id": line_1, "account_code": "760.01", "verified": True, "preconditions_match": True},
                {"canonical_line_id": line_1, "account_code": "760.02", "verified": True, "preconditions_match": True},
            ),
        }

        for label, bindings in cases.items():
            with self.subTest(label=label):
                result = _simulate_invoice(
                    invoice, selection, _task3_profile(), verified_rule_bindings=bindings,
                )
                self.assertEqual(result.ai_resolution_status, "ai_correction_required")
                self.assertNotEqual(result.ai_gate_reason, "verified_rule_binding")
                self.assertEqual(result.draft_lines, ())

    def test_verified_rule_authority_requires_strict_role_and_explicit_candidate_metadata(self) -> None:
        canonical = _task3_canonical_invoice(("Kargo hizmeti", "100.00", "20", "20.00", "120.00"))
        invoice = ParsedInvoice(
            file_name="strict-verified-authority.xml", provider_hint="Tedarikci", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="T3-STRICT-1", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Kargo hizmeti",),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            account_candidates={"purchase_expense": (
                {"code": "760.01", "name": "Valid detail", "reason": "", "is_detail_account": True, "is_active": True},
                {"code": "760.02", "name": "Missing active", "reason": "", "is_detail_account": True},
                {"code": "760.03", "name": "Inactive", "reason": "", "is_detail_account": True, "is_active": False},
                {"code": "760.04", "name": "Missing detail", "reason": "", "is_active": True},
                {"code": "760.05", "name": "Not detail", "reason": "", "is_detail_account": False, "is_active": True},
            )},
        )
        line_id = canonical.line_items[0].canonical_line_id
        cases = (
            ("garbage_role", "760.01", "garbage", "purchase", "ordinary"),
            ("missing_active", "760.02", "expense", "purchase", "ordinary"),
            ("false_active", "760.03", "expense", "purchase", "ordinary"),
            ("missing_detail", "760.04", "expense", "purchase", "ordinary"),
            ("false_detail", "760.05", "expense", "purchase", "ordinary"),
            ("wrong_direction_role", "760.01", "revenue", "purchase", "ordinary"),
            ("wrong_direction", "760.01", "expense", "sales", "ordinary"),
            ("wrong_mode", "760.01", "expense", "purchase", "return"),
        )

        for label, account_code, semantic_role, direction, invoice_mode in cases:
            with self.subTest(label=label):
                authority = _task3_verified_authority(
                    line_id,
                    account_code,
                    semantic_role=semantic_role,
                    direction=direction,
                    invoice_mode=invoice_mode,
                )
                result = _simulate_invoice(
                    invoice,
                    selection,
                    _task3_profile(),
                    verified_rule_authorities=(authority,),
                )

                self.assertEqual(result.ai_resolution_status, "ai_correction_required")
                self.assertNotEqual(result.ai_gate_reason, "verified_rule_binding")
                self.assertEqual(result.selected_expense_account, "")
                self.assertEqual(result.draft_lines, ())

    def test_verified_rule_authority_requires_independent_chart_semantic_agreement(self) -> None:
        canonical = _task3_canonical_invoice(("Semantic authority line", "100.00", "20", "20.00", "120.00"))
        purchase_invoice = ParsedInvoice(
            file_name="verified-chart-semantics-purchase.xml", provider_hint="Tedarikci", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="T3-SEM-P", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Semantic authority line",),
            canonical_invoice=canonical,
        )
        sales_invoice = replace(
            purchase_invoice,
            file_name="verified-chart-semantics-sales.xml",
            invoice_type="SATIS",
            invoice_no="T3-SEM-S",
            tax_ids=("1234567890", "9999999999"),
            issuer_title="Task 3 Isitme Merkezi",
            issuer_tax_id="1234567890",
            recipient_title="Alici",
            recipient_tax_id="9999999999",
        )
        purchase_selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="760.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(), stock_account="153.01",
            account_candidates={
                "purchase_expense": (
                    {"code": "600.01", "name": "Malicious sales account", "reason": "", "is_detail_account": True, "is_active": True},
                    {"code": "760.01", "name": "Valid expense", "reason": "", "is_detail_account": True, "is_active": True},
                ),
                "purchase_stock": (
                    {"code": "153.01", "name": "Valid stock", "reason": "", "is_detail_account": True, "is_active": True},
                ),
            },
        )
        sales_selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="760.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            revenue_account="600.01", sales_vat_account="391.20", customer_account="120.01",
            account_candidates={"sales_revenue": (
                {"code": "760.01", "name": "Malicious expense account", "reason": "", "is_detail_account": True, "is_active": True},
                {"code": "600.01", "name": "Valid revenue", "reason": "", "is_detail_account": True, "is_active": True},
            )},
        )
        line_id = canonical.line_items[0].canonical_line_id

        malicious_cases = (
            (
                "sales_account_in_purchase_expense",
                purchase_invoice,
                purchase_selection,
                _task3_verified_authority(line_id, "600.01", semantic_role="expense"),
            ),
            (
                "expense_account_in_sales_revenue",
                sales_invoice,
                sales_selection,
                _task3_verified_authority(line_id, "760.01", direction="sales", semantic_role="revenue"),
            ),
        )
        for label, invoice, selection, authority in malicious_cases:
            with self.subTest(label=label):
                result = _simulate_invoice(
                    invoice,
                    selection,
                    _task3_profile(),
                    verified_rule_authorities=(authority,),
                )
                self.assertEqual(result.ai_resolution_status, "ai_correction_required")
                self.assertNotEqual(result.ai_gate_reason, "verified_rule_binding")
                self.assertEqual(result.draft_lines, ())

        valid_cases = (
            (
                "purchase_expense",
                purchase_invoice,
                purchase_selection,
                _task3_verified_authority(line_id, "760.01", semantic_role="expense"),
                "760.01",
            ),
            (
                "purchase_stock",
                purchase_invoice,
                purchase_selection,
                _task3_verified_authority(line_id, "153.01", semantic_role="stock"),
                "153.01",
            ),
            (
                "sales_revenue",
                sales_invoice,
                sales_selection,
                _task3_verified_authority(line_id, "600.01", direction="sales", semantic_role="revenue"),
                "600.01",
            ),
        )
        for label, invoice, selection, authority, expected_code in valid_cases:
            with self.subTest(label=label):
                result = _simulate_invoice(
                    invoice,
                    selection,
                    _task3_profile(),
                    verified_rule_authorities=(authority,),
                )
                self.assertEqual(result.ai_resolution_status, "resolved")
                self.assertEqual(result.ai_gate_reason, "verified_rule_binding")
                self.assertIn(expected_code, {line["account_code"] for line in result.draft_lines})

    def test_orphan_accepted_semantic_attempt_id_cannot_authorize_a_journal(self) -> None:
        class OrphanAcceptedIdClassifier:
            policy = AiClassificationPolicy(enabled=True, static_confidence_threshold=101)

            def classify(self, raw_line: str, *, supplier_hint: str = "", context: AiClassificationContext | None = None) -> AiClassificationResult:
                return AiClassificationResult(
                    classification=ProductClassification(raw_line, "kargo", 95, ("orphan-test",)),
                    ai_used=True,
                    provider="orphan-test",
                    suggested_account_code="760.01",
                    accepted_semantic_attempt_id="missing-attempt-record",
                )

        invoice = ParsedInvoice(
            file_name="orphan-attempt.xml", provider_hint="Kargo", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="T3-ATTEMPT-1", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Kargo hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            account_candidates={"purchase_expense": ({"code": "760.01", "name": "Kargo gideri", "reason": ""},)},
        )

        result = _simulate_invoice(
            invoice,
            selection,
            _task3_profile(),
            product_classifier=OrphanAcceptedIdClassifier(),
        )

        self.assertEqual(result.semantic_attempts, ())
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.draft_lines, ())

    def test_accepted_account_must_match_accepted_attempt_response_and_candidates(self) -> None:
        class MismatchedRecordedClassifier:
            policy = AiClassificationPolicy(enabled=True, static_confidence_threshold=101)

            def classify(self, raw_line: str, *, supplier_hint: str = "", context: AiClassificationContext | None = None) -> AiClassificationResult:
                attempt = {
                    "attempt_id": "attempt-recorded-1", "stage": "initial_account_decision",
                    "canonical_line_ids": [], "prompt_version": "test-v1", "provider": "recorded",
                    "model": "recorded-model", "candidate_account_codes": ["760.02"],
                    "candidate_counterparty_codes": [],
                    "validated_response": {"suggested_account_code": "760.02"},
                    "validation_errors": [], "accepted": True, "superseded_by_attempt_id": "",
                }
                return AiClassificationResult(
                    classification=ProductClassification(raw_line, "kargo", 95, ("recorded",)),
                    ai_used=True, provider="recorded", suggested_account_code="760.01",
                    semantic_attempts=(attempt,), accepted_semantic_attempt_id="attempt-recorded-1",
                )

        invoice = ParsedInvoice(
            file_name="mismatched-attempt.xml", provider_hint="Kargo", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="T3-ATTEMPT-2", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Kargo hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            account_candidates={"purchase_expense": (
                {"code": "760.01", "name": "Kargo 1", "reason": ""},
                {"code": "760.02", "name": "Kargo 2", "reason": ""},
            )},
        )

        result = _simulate_invoice(invoice, selection, _task3_profile(), product_classifier=MismatchedRecordedClassifier())

        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.draft_lines, ())

    def test_post_simulation_learning_cannot_overwrite_accepted_ai_account_or_journal(self) -> None:
        canonical = _task3_canonical_invoice(("Kargo hizmet bedeli", "100.00", "20", "20.00", "120.00"))
        invoice = ParsedInvoice(
            file_name="learning-after-ai.xml", provider_hint="Yurtici Kargo", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="TEMELFATURA",
            invoice_type="ALIS", invoice_no="T3-LEARN-1", ettn="", issue_date="20.07.2026",
            tax_ids=("9860008925", "1234567890"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Kargo hizmet bedeli",),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            account_candidates={"purchase_expense": (
                {"code": "760.01", "name": "Kargo gideri", "reason": ""},
                {"code": "770.05", "name": "Diger gider", "reason": ""},
            )},
        )
        provider = FakeProductProvider({
            "category": "kargo", "confidence": 95, "reason": "Canonical line is cargo.",
            "evidence": ["canonical:kargo"], "suggested_account_code": "760.01",
            "suggested_counterparty_code": "", "risk_flags": [],
            "account_reason": "Accepted chart candidate.", "product_identity": "Kargo hizmeti",
            "needs_research": False, "research_query": "",
        })
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))
        result = _simulate_invoice(invoice, selection, _task3_profile(), product_classifier=classifier)
        base_codes = tuple(line["account_code"] for line in result.draft_lines)
        variants = (
            ("unconfirmed_client_rule", "approve", False),
            ("suggest_for_similar", "suggest_for_similar", False),
            ("automation_candidate", "suggest_for_similar", True),
        )

        for label, action, automation_candidate in variants:
            with self.subTest(label=label):
                rule = rule_from_event_payload({
                    "client_id": "client-task3", "scope": "client_rule", "action": action,
                    "category": "kargo", "corrected_account_code": "770.05",
                    "corrected_counterparty_code": "", "reason": "Prior similar choice.",
                    "normalized_terms": ["kargo", "hizmet", "bedeli"],
                    "automation_candidate": automation_candidate,
                })
                learned = apply_learning_rules(result, (rule,))
                self.assertFalse(learned.learning_rule_applied)
                self.assertEqual(learned.selected_expense_account, "760.01")
                self.assertEqual(tuple(line["account_code"] for line in learned.draft_lines), base_codes)

    def test_verified_binding_account_survives_sales_return_reversal_rules(self) -> None:
        canonical = _task3_canonical_invoice(("Iade edilen servis", "100.00", "20", "20.00", "120.00"))
        invoice = ParsedInvoice(
            file_name="sales-return-authority.xml", provider_hint="Task 3 Isitme Merkezi", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="IADE", invoice_type="IADE",
            invoice_no="T3-RETURN-1", ettn="", issue_date="20.07.2026",
            tax_ids=("1234567890", "9999999999"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Iade edilen servis",),
            canonical_invoice=canonical, issuer_title="Task 3 Isitme Merkezi",
            issuer_tax_id="1234567890", recipient_title="Alici", recipient_tax_id="9999999999",
            is_return_invoice=True,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            revenue_account="600.20", sales_vat_account="391.20", customer_account="120.01",
            account_candidates={"sales_revenue": (
                {"code": "600.20", "name": "Standard sales", "reason": ""},
                {"code": "601.99", "name": "Verified return semantic account", "reason": "", "is_detail_account": True, "is_active": True},
            )},
        )
        binding = (_task3_verified_authority(
            canonical.line_items[0].canonical_line_id,
            "601.99",
            direction="sales",
            invoice_mode="return",
            semantic_role="revenue",
        ),)

        result = _simulate_invoice(invoice, selection, _task3_profile(), verified_rule_authorities=binding)

        self.assertEqual(result.line_decisions[0]["account_code"], "601.99")
        self.assertEqual(result.selected_revenue_account, "601.99")
        self.assertIn("601.99", {line["account_code"] for line in result.draft_lines})
        self.assertIn("return_invoice_manual_review", result.review_reason_codes)

    def test_verified_binding_account_survives_non_deductible_legal_treatment(self) -> None:
        canonical = _task3_canonical_invoice(("SLIM TAPER giyim", "100.00", "20", "20.00", "120.00"))
        invoice = ParsedInvoice(
            file_name="non-deductible-authority.xml", provider_hint="Magaza", page_count=0,
            text_extractable=True, extracted_char_count=700, scenario="TEMELFATURA", invoice_type="ALIS",
            invoice_no="T3-ND-1", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("20",),
            goods_services_total="100.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="120.00", payable_total="120.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("SLIM TAPER giyim",),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            non_deductible_account="689.01",
            account_candidates={"non_deductible": (
                {"code": "689.01", "name": "Default KKEG", "reason": ""},
                {"code": "689.02", "name": "Verified KKEG", "reason": "", "is_detail_account": True, "is_active": True},
            )},
        )
        binding = (_task3_verified_authority(
            canonical.line_items[0].canonical_line_id,
            "689.02",
            semantic_role="non_deductible",
        ),)

        result = _simulate_invoice(invoice, selection, _task3_profile(), verified_rule_authorities=binding)

        self.assertEqual(result.business_relevance_account_treatment, "non_deductible_review")
        self.assertEqual(result.selected_expense_account, "689.02")
        self.assertEqual(result.selected_purchase_vat_account, "")
        self.assertIn("689.02", {line["account_code"] for line in result.draft_lines})

    def test_two_line_verified_sales_bindings_survive_mixed_vat_construction(self) -> None:
        canonical = _task3_canonical_invoice(
            ("Pil satisi", "100.00", "10", "10.00", "110.00"),
            ("Servis satisi", "100.00", "20", "20.00", "120.00"),
        )
        invoice = ParsedInvoice(
            file_name="mixed-sales-binding.xml", provider_hint="Task 3 Isitme Merkezi", page_count=0,
            text_extractable=True, extracted_char_count=900, scenario="TEMELFATURA", invoice_type="SATIS",
            invoice_no="T3-MIX-1", ettn="", issue_date="20.07.2026",
            tax_ids=("1234567890", "9999999999"), vat_rates=("10", "20"),
            goods_services_total="200.00", vat_total="30.00", special_tax_total="",
            tax_inclusive_total="230.00", payable_total="230.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Pil satisi", "Servis satisi"),
            line_item_details=(
                InvoiceLine(raw_text="Pil satisi 110,00", description="Pil satisi", amount_hint="110,00"),
                InvoiceLine(raw_text="Servis satisi 120,00", description="Servis satisi", amount_hint="120,00"),
            ),
            canonical_invoice=canonical, issuer_title="Task 3 Isitme Merkezi", issuer_tax_id="1234567890",
            recipient_title="Alici", recipient_tax_id="9999999999",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="770.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(), revenue_account="600.20",
            sales_vat_account="391.20", customer_account="120.01",
            account_candidates={
                "sales_revenue": (
                    {"code": "601.10", "name": "Verified pil sales", "reason": "", "is_detail_account": True, "is_active": True},
                    {"code": "602.20", "name": "Verified service sales", "reason": "", "is_detail_account": True, "is_active": True},
                    {"code": "600.10", "name": "Static rate 10", "reason": ""},
                    {"code": "600.20", "name": "Static rate 20", "reason": ""},
                ),
                "sales_vat": (
                    {"code": "391.10", "name": "VAT 10", "reason": ""},
                    {"code": "391.20", "name": "VAT 20", "reason": ""},
                ),
            },
        )
        bindings = tuple(
            _task3_verified_authority(
                line.canonical_line_id,
                account_code,
                direction="sales",
                semantic_role="revenue",
                index=index,
            )
            for index, (line, account_code) in enumerate(zip(canonical.line_items, ("601.10", "602.20")), start=1)
        )

        result = _simulate_invoice(invoice, selection, _task3_profile(), verified_rule_authorities=bindings)

        self.assertEqual([item["account_code"] for item in result.line_decisions], ["601.10", "602.20"])
        discretionary_codes = {
            line["account_code"]
            for line in result.draft_lines
            if not line["account_code"].startswith(("120", "391"))
        }
        self.assertEqual(discretionary_codes, {"601.10", "602.20"})
        self.assertEqual(result.draft_entry_type, "mixed_vat_sales")

    def test_incomplete_line_decision_cannot_fall_back_to_valid_top_level_ai_account(self) -> None:
        canonical = _task3_canonical_invoice(
            ("Cihaz", "100.00", "20", "20.00", "120.00"),
            ("Bakim", "50.00", "0", "0.00", "50.00"),
        )
        invoice = ParsedInvoice(
            file_name="incomplete-line-ai.xml", provider_hint="Tedarikci", page_count=0,
            text_extractable=True, extracted_char_count=900, scenario="TEMELFATURA", invoice_type="ALIS",
            invoice_no="T3-LINE-1", ettn="", issue_date="20.07.2026",
            tax_ids=("9999999999", "1234567890"), vat_rates=("0", "20"),
            goods_services_total="150.00", vat_total="20.00", special_tax_total="",
            tax_inclusive_total="170.00", payable_total="170.00", risk_flags=(),
            suggested_route="journal_candidate", parse_notes=(), line_items=("Cihaz", "Bakim"),
            canonical_invoice=canonical,
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx", expense_account="760.01", purchase_vat_account="191.20",
            supplier_account="320.01", bank_account="102.01", selection_notes=(),
            account_candidates={"purchase_expense": (
                {"code": "760.01", "name": "Cihaz gideri", "reason": ""},
                {"code": "760.02", "name": "Bakim gideri", "reason": ""},
            )},
        )
        incomplete_decisions = (
                {
                    "canonical_line_id": canonical.line_items[0].canonical_line_id,
                    "category": "baska_kategori", "confidence": 90, "product_identity": "Cihaz",
                    "suggested_account_code": "760.01", "reason": "Valid first line.", "evidence": [],
                    "needs_research": False, "research_query": "", "risk_flags": [],
                },
                {
                    "canonical_line_id": canonical.line_items[1].canonical_line_id,
                    "category": "baska_kategori", "confidence": 90, "product_identity": "Bakim",
                    "suggested_account_code": "", "reason": "Missing account.", "evidence": [],
                    "needs_research": False, "research_query": "", "risk_flags": [],
                },
        )

        class IncompleteRecordedClassifier:
            policy = AiClassificationPolicy(enabled=True, static_confidence_threshold=101)

            def classify(self, raw_line: str, *, supplier_hint: str = "", context: AiClassificationContext | None = None) -> AiClassificationResult:
                response = {
                    "suggested_account_code": "760.01",
                    "line_decisions": list(incomplete_decisions),
                }
                attempt = {
                    "attempt_id": "attempt-incomplete-lines", "stage": "initial_account_decision",
                    "canonical_line_ids": [line.canonical_line_id for line in canonical.line_items],
                    "prompt_version": "test-v1", "provider": "recorded", "model": "recorded-model",
                    "candidate_account_codes": ["760.01", "760.02"],
                    "candidate_counterparty_codes": [], "validated_response": response,
                    "validation_errors": [], "accepted": True, "superseded_by_attempt_id": "",
                }
                return AiClassificationResult(
                    classification=ProductClassification(raw_line, "baska_kategori", 90, ("canonical:two-lines",)),
                    ai_used=True, provider="recorded", suggested_account_code="760.01",
                    account_reason="Top level is valid.", product_identity="Cihaz ve bakim",
                    semantic_attempts=(attempt,), accepted_semantic_attempt_id="attempt-incomplete-lines",
                    line_decisions=incomplete_decisions,
                )

        classifier = IncompleteRecordedClassifier()

        result = _simulate_invoice(invoice, selection, _task3_profile(), product_classifier=classifier)

        self.assertIn("ai_line_decision_incomplete", result.review_reason_codes)
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.draft_lines, ())

    def test_invoice_ai_gate_calls_ai_for_brand_model_only_line(self) -> None:
        invoice = ParsedInvoice(
            file_name="brand-model.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="BRD2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01",
            account_candidates={"purchase_stock": ({"code": "153.01", "name": "Cihaz stoku", "reason": ""},)},
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 86,
                "reason": "Model isitme cihazi ailesine benziyor.",
                "evidence": ["ai:model_family"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Stok hesabi onerildi.",
                "product_identity": "ZX Sonic Pro 9",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.ai_gate_reason, "unknown_product_category")
        self.assertEqual(result.ai_product_identity, "ZX Sonic Pro 9")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result.selected_expense_account, "153.01")

    def test_ai_first_cold_start_explains_known_hearing_device_sale(self) -> None:
        invoice = ParsedInvoice(
            file_name="helix-sales.pdf",
            provider_hint="Rana Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="HLX2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1111111111", "2222222222"),
            vat_rates=("0",),
            goods_services_total="12000.00",
            vat_total="0.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Helix Force 200 RI isitme cihazi",),
            issuer_title="Rana Medikal",
            issuer_tax_id="1111111111",
            recipient_title="Alici Hasta",
            recipient_tax_id="2222222222",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            zero_vat_revenue_account="600.01.000",
            sales_vat_account="391.20",
            customer_account="120.01",
            next_customer_account="120.A02",
            account_candidates={
                "zero_vat_revenue": ({"code": "600.01.000", "name": "3065 istisnali isitme cihazi satislari", "reason": ""},),
                "customer": ({"code": "120.01", "name": "Alicilar", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Rana Medikal",
            tax_id="1111111111",
            vkn="1111111111",
            activity_description="Medikal ve ortopedik urunlerin perakende satisi",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 92,
                "reason": "Urun isitme cihazidir; NACE 477401 medikal/ortopedik perakende faaliyetiyle guclu iliskili.",
                "evidence": ["ai:product_identity", "ai:nace_477401"],
                "suggested_account_code": "600.01.000",
                "suggested_counterparty_code": "120.01",
                "risk_flags": [],
                "account_reason": "Satis yonunde alici cari 120 borc, 3065 istisnali gelir hesabi alacak.",
                "product_identity": "Helix Force 200 RI isitme cihazi",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.ai_gate_reason, "cold_start_core_accounting_line")
        self.assertEqual(result.ai_product_identity, "Helix Force 200 RI isitme cihazi")
        self.assertEqual(result.product_category, "isitme_cihazi")
        self.assertIn("ai:nace_477401", result.business_relevance_evidence)
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["120.2222222222", "600.01.000"])
        self.assertTrue(all(line["account_code"] != "391.20" for line in result.draft_lines))
        self.assertIn("120 borc", result.ai_account_reason)
        self.assertFalse(result.ai_research_requested)
        self.assertEqual(len(provider.requests), 1)

    def test_ai_response_can_request_research_without_overriding_export(self) -> None:
        invoice = ParsedInvoice(
            file_name="needs-research.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="RSH2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "bilinmeyen",
                "confidence": 45,
                "reason": "Model bilinmiyor, arastirma gerekli.",
                "evidence": ["ai:uncertain"],
                "suggested_account_code": "",
                "suggested_counterparty_code": "",
                "risk_flags": ["accountant_review_required"],
                "account_reason": "",
                "product_identity": "ZX Sonic Pro 9",
                "needs_research": True,
                "research_query": "ZX Sonic Pro 9",
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertTrue(result.ai_research_requested)
        self.assertEqual(result.ai_research_query, "ZX Sonic Pro 9")
        self.assertEqual(result.export_status, "review_required")
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.ai_retry_reason, "research_required")
        self.assertTrue(result.static_fallback_suppressed)
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.draft_lines, ())

    def test_ai_account_candidate_is_not_overridden_by_account_family_guardrail(self) -> None:
        invoice = ParsedInvoice(
            file_name="ai-stock-guard.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="GRD2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01",
            account_candidates={
                "purchase_stock": ({"code": "153.01", "name": "Cihaz stoku", "reason": ""},),
                "purchase_expense": ({"code": "770.01", "name": "Genel gider", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 88,
                "reason": "Stok urunu ama yanlis hesap onerildi.",
                "evidence": ["ai:model_family"],
                "suggested_account_code": "770.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Yanlis gider hesabi onerildi.",
                "product_identity": "ZX Sonic Pro 9",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.ai_suggested_account_code, "770.01")
        self.assertNotIn("ai_account_family_rejected", result.review_reason_codes)
        self.assertEqual(result.selected_expense_account, "770.01")
        self.assertEqual(result.draft_lines[0]["account_code"], "770.01")
        self.assertEqual(result.export_status, "review_required")

    def test_uncertain_purchase_without_ai_provider_suppresses_generic_expense_fallback(self) -> None:
        invoice = ParsedInvoice(
            file_name="unknown-device.pdf",
            provider_hint="Belirsiz Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="UNK2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9 receiver unit",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01",
            account_candidates={
                "purchase_stock": ({"code": "153.01", "name": "Cihaz stoku", "reason": ""},),
                "purchase_expense": ({"code": "770.01", "name": "Genel gider", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        classifier = StaticFirstClassifier(
            provider=None,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertFalse(result.ai_classification_used)
        self.assertEqual(result.ai_classification_skipped_reason, "provider_missing")
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.ai_retry_reason, "provider_missing")
        self.assertEqual(result.static_fallback_account, "")
        self.assertTrue(result.static_fallback_suppressed)
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.draft_lines, ())
        self.assertIn("ai_correction_required", result.review_reason_codes)

    def test_invalid_ai_account_requests_ai_correction_without_static_substitution(self) -> None:
        invoice = ParsedInvoice(
            file_name="invalid-ai-account.pdf",
            provider_hint="Belirsiz Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="BAD2026000000100",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Belirsiz hizmet",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "760.03.010", "name": "DİĞER ÇEŞİTLİ GİDER", "reason": "7xx gider adayı"},
                    {"code": "770.01", "name": "GENEL GİDER", "reason": "7xx gider adayı"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "kargo",
                "confidence": 88,
                "reason": "AI aday dışı bir hesap önerdi.",
                "evidence": ["ai:canonical_line"],
                "suggested_account_code": "760.99.999",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Aday dışı hesap önerisi.",
                "product_identity": "Belirsiz hizmet",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertEqual(getattr(result, "ai_attempted_account_code", ""), "760.99.999")
        self.assertEqual(result.ai_resolution_status, "ai_correction_required")
        self.assertEqual(result.selected_expense_account, "")
        self.assertNotIn(result.selected_expense_account, {"760.03.010", "770.01"})
        self.assertEqual(result.ai_retry_reason, "selected_account_not_in_candidates")

    def test_invalid_ai_account_gets_one_bounded_semantic_correction(self) -> None:
        base = {
            "category": "kargo",
            "confidence": 88,
            "reason": "Kargo hizmeti.",
            "evidence": ["canonical line"],
            "suggested_counterparty_code": "",
            "risk_flags": [],
            "account_reason": "Kargo gideri.",
            "product_identity": "Kargo hizmeti",
            "needs_research": False,
            "research_query": "",
        }
        provider = SequentialFakeProductProvider(
            [
                {**base, "suggested_account_code": "760.99.999"},
                {**base, "suggested_account_code": "760.03.012"},
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )
        canonical = _task3_canonical_invoice(("Kargo hizmeti", "100.00", "20", "20.00", "120.00"))
        context = AiClassificationContext(
            account_candidates=("760.03.012", "770.01"),
            canonical_lines=({"canonical_line_id": canonical.line_items[0].canonical_line_id, "description": "Kargo hizmeti"},),
            candidate_strategy=AiCandidateStrategy(stage="final_account"),
        )

        result = classifier.classify("Kargo hizmeti", context=context)

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.requests[1].context.semantic_stage, "account_correction")
        self.assertEqual(provider.requests[1].context.validation_errors, ("selected_account_not_in_candidates",))
        self.assertEqual(result.suggested_account_code, "760.03.012")
        self.assertEqual([item["stage"] for item in result.semantic_attempts], ["initial_account_decision", "account_correction"])
        self.assertFalse(result.semantic_attempts[0]["accepted"])
        self.assertTrue(result.semantic_attempts[1]["accepted"])
        self.assertEqual(result.accepted_semantic_attempt_id, result.semantic_attempts[1]["attempt_id"])
        from app.domain.matching_simulation import _resolve_accepted_ai_authority

        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.012",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            account_candidates={
                "purchase_expense": (
                    {"code": "760.03.012", "name": "Kargo gideri", "is_detail_account": True, "is_active": True},
                    {"code": "770.01", "name": "Genel gider", "is_detail_account": True, "is_active": True},
                ),
            },
        )
        authority = _resolve_accepted_ai_authority(
            semantic_attempts=result.semantic_attempts,
            accepted_attempt_id=result.accepted_semantic_attempt_id,
            canonical_items=canonical.line_items,
            selection=selection,
            direction="purchase",
        )
        self.assertEqual(
            authority.account_by_line()[canonical.line_items[0].canonical_line_id].account_code,
            "760.03.012",
        )

    def test_ai_provider_call_limit_does_not_starve_later_invoices_in_batch(self) -> None:
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01",
            account_candidates={
                "purchase_stock": ({"code": "153.01", "name": "Cihaz stoku", "reason": ""},),
                "purchase_expense": ({"code": "770.01", "name": "Genel gider", "reason": ""},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 86,
                "reason": "Model isitme cihazi ailesine benziyor.",
                "evidence": ["ai:model_family"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Stok hesabi onerildi.",
                "product_identity": "ZX Sonic Pro 9",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, max_provider_calls=1),
        )
        invoices = [
            ParsedInvoice(
                file_name=f"device-{index}.pdf",
                provider_hint="Medikal Tedarik",
                page_count=1,
                text_extractable=True,
                extracted_char_count=1200,
                scenario="TEMELFATURA",
                invoice_type="ALIS",
                invoice_no=f"BRD202600000010{index}",
                ettn="",
                issue_date="01.05.2026",
                tax_ids=("9999999999", "1234567890"),
                vat_rates=("20",),
                goods_services_total="1000.00",
                vat_total="200.00",
                special_tax_total="",
                tax_inclusive_total="1200.00",
                payable_total="1200.00",
                risk_flags=(),
                suggested_route="journal_candidate",
                parse_notes=(),
                line_items=(f"ZX Sonic Pro 9 receiver unit {index}",),
            )
            for index in range(3)
        ]

        results = [
            simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")
            for invoice in invoices
        ]

        self.assertEqual(len(provider.requests), 3)
        self.assertEqual([result.selected_expense_account for result in results], ["153.01", "153.01", "153.01"])
        self.assertNotIn("provider_call_budget_exhausted", [result.ai_classification_skipped_reason for result in results])

    def test_large_candidate_set_uses_family_stage_then_final_account_stage(self) -> None:
        invoice = ParsedInvoice(
            file_name="bera-device.pdf",
            provider_hint="BERA ODYOLOJI TICARET LIMITED SIRKETI",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="AAA2026000001172",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("1640731289", "1234567890"),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("AU B1-R BN/7613389661644 RECEIVER UNIT",),
            issuer_title="BERA ODYOLOJI TICARET LIMITED SIRKETI",
            issuer_tax_id="1640731289",
            recipient_title="ORHAN ELIBOL",
            recipient_tax_id="1234567890",
        )
        stock_candidates = tuple(
            {"code": f"153.01.{index:03d}", "name": f"Stok hesabi {index}", "reason": "153 stok adayi"}
            for index in range(2, 32)
        )
        expense_candidates = tuple(
            {"code": f"760.03.{index:03d}", "name": f"Gider hesabi {index}", "reason": "760 gider adayi"}
            for index in range(1, 12)
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": (
                    {"code": "153.01.001", "name": "ALINAN CIHAZLAR", "reason": "153 cihaz/stok adayi"},
                    *stock_candidates,
                ),
                "fixed_asset": ({"code": "253.01.001", "name": "TIBBI CIHAZLAR", "reason": "25x demirbas adayi"},),
                "purchase_expense": expense_candidates,
                "purchase_vat": ({"code": "191.01.020", "name": "Indirilecek KDV %20", "reason": ""},),
                "supplier": (
                    {"code": "320.1640731289", "name": "BERA ODYOLOJI", "reason": "VKN bazli yeni satici"},
                    {"code": "320.01", "name": "Genel satici", "reason": "mevcut satici"},
                ),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = SequentialFakeProductProvider(
            [
                {
                    "category": "business_equipment",
                    "confidence": 82,
                    "reason": "Satir cihaz/receiver alimi gibi duruyor; stok ve demirbas aileleri birlikte incelenmeli.",
                    "evidence": ["receiver", "odyoloji"],
                    "selected_account_families": ["153", "25"],
                    "risk_flags": [],
                    "account_reason": "Stage 2 icin stok ve demirbas aileleri acik kalsin.",
                    "product_identity": "Odyoloji receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
                {
                    "category": "business_equipment",
                    "confidence": 88,
                    "reason": "Hesap planindaki ALINAN CIHAZLAR bu kaleme en yakin aday.",
                    "evidence": ["153 cihaz", "320 vkn"],
                    "suggested_account_code": "153.01.001",
                    "suggested_counterparty_code": "320.1640731289",
                    "risk_flags": [],
                    "account_reason": "Cihaz alimi stok/alinan cihazlar hesabina daha yakin.",
                    "product_identity": "Odyoloji receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(
                enabled=True,
                static_confidence_threshold=101,
                max_provider_calls=3,
                single_stage_account_limit=40,
            ),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.requests[0].context.candidate_strategy.stage, "family_select")
        self.assertEqual(provider.requests[1].context.candidate_strategy.stage, "final_account")
        final_payload = provider.requests[1].to_schema_payload()
        self.assertIn("153.01.001", final_payload["account_candidates"])
        self.assertIn("253.01.001", final_payload["account_candidates"])
        self.assertNotIn("760.03.001", final_payload["account_candidates"])
        self.assertIn("320.1640731289", final_payload["counterparty_candidates"])
        self.assertEqual(result.ai_candidate_strategy, "two_stage")
        self.assertEqual(result.ai_selected_account_families, ("153", "25"))
        self.assertEqual(result.ai_suggested_account_code, "153.01.001")
        self.assertEqual(result.ai_suggested_counterparty_code, "320.1640731289")
        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertEqual(result.ai_stage_evidence[0]["ai_stage"], "family_select")
        self.assertEqual(result.ai_stage_evidence[1]["ai_stage"], "final_account")

    def test_family_stage_includes_all_plausible_direction_families_with_examples(self) -> None:
        invoice = ParsedInvoice(
            file_name="unknown-device.pdf",
            provider_hint="Bilinmeyen Cihaz Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000001173",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("MODEL X RECEIVER UNIT",),
        )
        stock_candidates = tuple(
            {"code": f"153.01.{index:03d}", "name": f"Stok hesabi {index}", "reason": "153 stok adayi"}
            for index in range(1, 35)
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": stock_candidates,
                "fixed_asset": ({"code": "255.34", "name": "Telefon demirbas", "reason": "25x demirbas adayi"},),
                "purchase_expense": tuple(
                    {"code": f"760.03.{index:03d}", "name": f"Gider hesabi {index}", "reason": "760 gider adayi"}
                    for index in range(1, 12)
                ),
                "purchase_vat": ({"code": "191.01.020", "name": "Indirilecek KDV %20", "reason": "191 KDV adayi"},),
                "supplier": ({"code": "320.01", "name": "Genel satici", "reason": "mevcut satici"},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = SequentialFakeProductProvider(
            [
                {
                    "category": "business_equipment",
                    "confidence": 82,
                    "reason": "Cihaz, stok ve demirbas aileleri acik kalsin.",
                    "evidence": ["receiver"],
                    "primary_account_families": ["153"],
                    "alternative_account_families": ["25", "760"],
                    "direction_assessment": "purchase",
                    "selected_account_families": ["153", "25", "760"],
                    "risk_flags": [],
                    "account_reason": "Aile acilimi",
                    "product_identity": "Receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
                {
                    "category": "business_equipment",
                    "confidence": 88,
                    "reason": "Stok hesabi en yakin aday.",
                    "evidence": ["153"],
                    "suggested_account_code": "153.01.001",
                    "suggested_counterparty_code": "",
                    "risk_flags": [],
                    "account_reason": "Stok",
                    "product_identity": "Receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, max_provider_calls=3),
        )

        simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        family_payload = provider.requests[0].to_schema_payload()
        family_records = {record["family"]: record for record in family_payload["account_family_candidates"]}
        self.assertIn("153", family_records)
        self.assertIn("25", family_records)
        self.assertIn("760", family_records)
        self.assertIn("191", family_records)
        self.assertEqual(family_records["153"]["direction_role"], "purchase_account")
        self.assertEqual(family_records["191"]["direction_role"], "purchase_vat")
        self.assertGreaterEqual(family_records["153"]["candidate_count"], 34)
        self.assertTrue(family_records["153"]["examples"])

    def test_final_account_stage_uses_all_details_from_selected_families(self) -> None:
        invoice = ParsedInvoice(
            file_name="large-stock-family.pdf",
            provider_hint="Bera Odyoloji",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000001174",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("MODEL X RECEIVER UNIT",),
        )
        stock_candidates = tuple(
            {"code": f"153.01.{index:03d}", "name": f"Stok hesabi {index}", "reason": "153 stok adayi"}
            for index in range(1, 131)
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": stock_candidates,
                "purchase_expense": ({"code": "760.03.010", "name": "Diger gider", "reason": "760 gider adayi"},),
                "supplier": ({"code": "320.01", "name": "Genel satici", "reason": "mevcut satici"},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = SequentialFakeProductProvider(
            [
                {
                    "category": "business_equipment",
                    "confidence": 82,
                    "reason": "153 ailesi acilsin.",
                    "evidence": ["receiver"],
                    "primary_account_families": ["153"],
                    "alternative_account_families": [],
                    "direction_assessment": "purchase",
                    "selected_account_families": ["153"],
                    "risk_flags": [],
                    "account_reason": "153",
                    "product_identity": "Receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
                {
                    "category": "business_equipment",
                    "confidence": 88,
                    "reason": "Son stok detayi en yakin aday.",
                    "evidence": ["153"],
                    "suggested_account_code": "153.01.130",
                    "suggested_counterparty_code": "",
                    "risk_flags": [],
                    "account_reason": "Stok",
                    "product_identity": "Receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, max_provider_calls=3),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        final_payload = provider.requests[1].to_schema_payload()
        self.assertEqual(len(final_payload["account_candidates"]), 130)
        self.assertIn("153.01.130", final_payload["account_candidates"])
        self.assertEqual(result.ai_suggested_account_code, "153.01.130")

    def test_large_counterparty_list_uses_dedicated_all_candidate_stage(self) -> None:
        invoice = ParsedInvoice(
            file_name="large-counterparty-list.pdf",
            provider_hint="BERA ODYOLOJI TICARET LIMITED SIRKETI",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000001175",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("1640731289", "1234567890"),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("MODEL X RECEIVER UNIT",),
            issuer_title="BERA ODYOLOJI TICARET LIMITED SIRKETI",
            issuer_tax_id="1640731289",
            recipient_title="ORHAN ELIBOL",
            recipient_tax_id="1234567890",
        )
        suppliers = tuple(
            {"code": f"320.{index:03d}", "name": f"Satici {index}", "reason": "mevcut satici"}
            for index in range(1, 86)
        ) + ({"code": "320.999", "name": "BERA ODYOLOJI", "reason": "unvan benzerligi"},)
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.001",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "ALINAN CIHAZLAR", "reason": "153 stok adayi"},),
                "supplier": suppliers,
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = SequentialFakeProductProvider(
            [
                {
                    "category": "business_equipment",
                    "confidence": 88,
                    "reason": "Stok hesabi en yakin aday.",
                    "evidence": ["153"],
                    "suggested_account_code": "153.01.001",
                    "suggested_counterparty_code": "",
                    "risk_flags": [],
                    "account_reason": "Stok",
                    "product_identity": "Receiver cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
                {
                    "category": "business_equipment",
                    "confidence": 91,
                    "reason": "Unvan BERA ODYOLOJI carisiyle eslesiyor.",
                    "evidence": ["issuer_title", "320.999"],
                    "suggested_account_code": "",
                    "suggested_counterparty_code": "320.999",
                    "risk_flags": [],
                    "account_reason": "Cari unvan eslesmesi.",
                    "product_identity": "BERA ODYOLOJI",
                    "needs_research": False,
                    "research_query": "",
                },
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, max_provider_calls=3),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.requests[1].context.candidate_strategy.stage, "counterparty_resolve")
        counterparty_payload = provider.requests[1].to_schema_payload()
        self.assertEqual(len(counterparty_payload["counterparty_candidates"]), 87)
        self.assertIn("320.001", counterparty_payload["counterparty_candidates"])
        self.assertIn("320.999", counterparty_payload["counterparty_candidates"])
        self.assertIn("320.1640731289", counterparty_payload["counterparty_candidates"])
        self.assertEqual(result.ai_suggested_counterparty_code, "320.999")
        self.assertEqual(result.ai_stage_evidence[-1]["ai_stage"], "counterparty_resolve")
        self.assertEqual([record["ai_stage"] for record in result.ai_account_stage_evidence], ["final_account"])
        self.assertEqual([record["ai_stage"] for record in result.ai_counterparty_stage_evidence], ["counterparty_resolve"])

    def test_uncertain_direction_keeps_purchase_and_sales_account_candidates_visible(self) -> None:
        invoice = ParsedInvoice(
            file_name="uncertain-direction.pdf",
            provider_hint="BELIRSIZ TEDARIKCI",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="",
            invoice_no="AAA2026000001176",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("BELIRSIZ CIHAZ/HIZMET KALEMI",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.001",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            revenue_account="600.01.020",
            sales_vat_account="391.01.020",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "ALINAN CIHAZLAR", "reason": "153 stok adayi"},),
                "purchase_expense": ({"code": "760.03.010", "name": "GIDER", "reason": "760 gider adayi"},),
                "sales_revenue": ({"code": "600.01.020", "name": "CIHAZ SATISLARI", "reason": "600 satis adayi"},),
                "sales_vat": ({"code": "391.01.020", "name": "HESAPLANAN KDV", "reason": "391 KDV adayi"},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "business_equipment",
                "confidence": 78,
                "reason": "Yon belirsiz oldugu icin satis hesabi secildi.",
                "evidence": ["belirsiz_yon"],
                "suggested_account_code": "600.01.020",
                "suggested_counterparty_code": "",
                "risk_flags": ["direction_uncertain"],
                "account_reason": "Satis ailesi de gorundu.",
                "product_identity": "Belirsiz cihaz hizmeti",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, single_stage_account_limit=40),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        payload = provider.requests[0].to_schema_payload()
        self.assertTrue(payload["direction_uncertainty"])
        self.assertIn("153.01.001", payload["account_candidates"])
        self.assertIn("600.01.020", payload["account_candidates"])
        self.assertTrue(result.direction_uncertainty)
        self.assertEqual(result.ai_suggested_account_code, "600.01.020")

    def test_counterparty_resolution_sends_all_120_candidates_for_sales(self) -> None:
        invoice = ParsedInvoice(
            file_name="large-sales-counterparty-list.pdf",
            provider_hint="ORHAN ELIBOL",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SAT2026000001177",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("1234567890", "5555555555"),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ISITME CIHAZI SATISI",),
            issuer_title="ORHAN ELIBOL",
            issuer_tax_id="1234567890",
            recipient_title="ACME SAGLIK LIMITED SIRKETI",
            recipient_tax_id="5555555555",
        )
        customers = tuple(
            {"code": f"120.{index:03d}", "name": f"Musteri {index}", "reason": "mevcut musteri"}
            for index in range(1, 86)
        ) + ({"code": "120.999", "name": "ACME SAGLIK", "reason": "unvan benzerligi"},)
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.001",
            bank_account="102.01",
            selection_notes=(),
            revenue_account="600.01.020",
            sales_vat_account="391.01.020",
            customer_account="120.001",
            account_candidates={
                "sales_revenue": ({"code": "600.01.020", "name": "CIHAZ SATISLARI", "reason": "600 satis adayi"},),
                "customer": customers,
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = SequentialFakeProductProvider(
            [
                {
                    "category": "business_equipment",
                    "confidence": 88,
                    "reason": "Satis hesabi uygun.",
                    "evidence": ["satis"],
                    "suggested_account_code": "600.01.020",
                    "suggested_counterparty_code": "",
                    "risk_flags": [],
                    "account_reason": "Satis",
                    "product_identity": "Isitme cihazi",
                    "needs_research": False,
                    "research_query": "",
                },
                {
                    "category": "business_equipment",
                    "confidence": 91,
                    "reason": "ACME unvani mevcut 120.999 ile eslesiyor.",
                    "evidence": ["recipient_title"],
                    "suggested_account_code": "",
                    "suggested_counterparty_code": "120.999",
                    "risk_flags": [],
                    "account_reason": "Cari unvan eslesmesi.",
                    "product_identity": "ACME SAGLIK",
                    "needs_research": False,
                    "research_query": "",
                },
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, max_provider_calls=3),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertEqual(provider.requests[1].context.candidate_strategy.stage, "counterparty_resolve")
        counterparty_payload = provider.requests[1].to_schema_payload()
        self.assertEqual(len(counterparty_payload["counterparty_candidates"]), 87)
        self.assertIn("120.001", counterparty_payload["counterparty_candidates"])
        self.assertIn("120.999", counterparty_payload["counterparty_candidates"])
        self.assertIn("120.5555555555", counterparty_payload["counterparty_candidates"])
        self.assertEqual(result.ai_suggested_counterparty_code, "120.999")

    def test_counterparty_resolution_payload_includes_titles_tokens_and_identity_evidence(self) -> None:
        invoice = ParsedInvoice(
            file_name="counterparty-evidence.pdf",
            provider_hint="BERA ODYOLOJI TICARET LIMITED SIRKETI",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000001178",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("1640731289", "1234567890"),
            vat_rates=("20",),
            goods_services_total="2500.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="3000.24",
            payable_total="3000.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("MODEL X RECEIVER UNIT",),
            issuer_title="BERA ODYOLOJI TICARET LIMITED SIRKETI",
            issuer_tax_id="1640731289",
            recipient_title="ORHAN ELIBOL",
            recipient_tax_id="1234567890",
        )
        suppliers = tuple(
            {"code": f"320.{index:03d}", "name": f"Satici {index}", "reason": "mevcut satici"}
            for index in range(1, 82)
        ) + ({"code": "320.999", "name": "BERA ODYOLOJI", "reason": "unvan benzerligi"},)
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.001",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "ALINAN CIHAZLAR", "reason": "153 stok adayi"},),
                "supplier": suppliers,
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="ORHAN ELIBOL",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi satis hizmetleri",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        provider = SequentialFakeProductProvider(
            [
                {
                    "category": "business_equipment",
                    "confidence": 88,
                    "reason": "Stok hesabi uygun.",
                    "evidence": ["receiver"],
                    "suggested_account_code": "153.01.001",
                    "suggested_counterparty_code": "",
                    "risk_flags": [],
                    "account_reason": "Stok",
                    "product_identity": "Receiver",
                    "needs_research": False,
                    "research_query": "",
                },
                {
                    "category": "business_equipment",
                    "confidence": 90,
                    "reason": "Unvan kaniti ile cari eslesti.",
                    "evidence": ["title_overlap"],
                    "suggested_account_code": "",
                    "suggested_counterparty_code": "320.999",
                    "risk_flags": [],
                    "account_reason": "Cari",
                    "product_identity": "BERA ODYOLOJI",
                    "needs_research": False,
                    "research_query": "",
                },
            ]
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101, max_provider_calls=3),
        )

        simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        payload = provider.requests[1].to_schema_payload()
        party = payload["invoice_counterparty"]
        self.assertEqual(party["direction"], "purchase")
        self.assertEqual(party["counterparty_tax_id"], "1640731289")
        self.assertEqual(party["counterparty_title"], "BERA ODYOLOJI TICARET LIMITED SIRKETI")
        self.assertIn("bera", party["normalized_title_tokens"])
        details = {record["code"]: record for record in payload["counterparty_candidate_details"]}
        self.assertEqual(details["320.999"]["name"], "BERA ODYOLOJI")
        self.assertIn("title_token_overlap", details["320.999"]["evidence"])
        self.assertIn("tax_id_suggested_new_account", details["320.1640731289"]["evidence"])

    def test_ai_can_route_business_equipment_to_stock_account_for_review_draft(self) -> None:
        invoice = ParsedInvoice(
            file_name="ai-business-equipment-stock.pdf",
            provider_hint="Bera Odyoloji",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="AAA2026000001172",
            ettn="",
            issue_date="01.06.2026",
            tax_ids=("9999999999", "1234567890"),
            vat_rates=("0", "20"),
            goods_services_total="16160.20",
            vat_total="500.04",
            special_tax_total="",
            tax_inclusive_total="16660.24",
            payable_total="16660.24",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("AU B1-R BN/7613389661644 212547N0M6Y CHARGER RIC P RECEIVER 5.0",),
        )
        selection = AccountSelection(
            chart_file_name="orhan-hesap-plani.xlsx",
            expense_account="760.03.010",
            purchase_vat_account="191.01.020",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            stock_account="153.01.001",
            account_candidates={
                "purchase_stock": ({"code": "153.01.001", "name": "ALINAN CIHAZLAR", "reason": "153 stok adayi"},),
                "purchase_expense": ({"code": "760.03.010", "name": "CESITLI GIDERLER", "reason": "7xx gider adayi"},),
                "purchase_vat": ({"code": "191.01.020", "name": "INDIRILECEK KDV %20", "reason": "191 KDV adayi"},),
            },
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Orhan Elibol",
            tax_id="1234567890",
            activity_description="Odyoloji ve isitme cihazi hizmetleri",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        provider = FakeProductProvider(
            {
                "category": "business_equipment",
                "confidence": 80,
                "reason": "Serial-like codes and odyoloji supplier point to medical equipment.",
                "evidence": ["ai:serial_code", "ai:supplier_odyoloji"],
                "suggested_account_code": "153.01.001",
                "suggested_counterparty_code": "320.01",
                "risk_flags": ["accountant_review_required"],
                "account_reason": "AI mevcut hesap adaylari icinden alinan cihazlar hesabini onerdi.",
                "product_identity": "Bera Odyoloji Lab Equipment",
                "needs_research": False,
                "research_query": "",
            }
        )
        classifier = StaticFirstClassifier(provider=provider, policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101))

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.product_category, "business_equipment")
        self.assertEqual(result.business_relevance_account_treatment, "fixed_asset_review")
        self.assertEqual(result.ai_suggested_account_code, "153.01.001")
        self.assertNotIn("ai_account_family_rejected", result.review_reason_codes)
        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertEqual(result.draft_lines[0]["account_code"], "153.01.001")
        self.assertEqual(result.export_status, "review_required")

    def test_sales_counterparty_match_uses_customer_prefix_not_supplier_prefix(self) -> None:
        canonical = _task3_canonical_invoice(("Cihaz satisi", "1000.00", "20", "200.00", "1200.00"))
        invoice = ParsedInvoice(
            file_name="sales-customer.pdf",
            provider_hint="Client",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SAT2026000000002",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1111111111", "2222222222"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Cihaz satisi",),
            issuer_title="Client",
            issuer_tax_id="1111111111",
            recipient_title="Acme Musteri",
            recipient_tax_id="2222222222",
            canonical_invoice=canonical,
        )
        accounts = [
            ChartAccount("320.01", "320.01", "Acme Musteri", True),
            ChartAccount("120.01", "120.01", "Acme Musteri", True),
            ChartAccount("600.20", "600.20", "Satis", True),
            ChartAccount("391.20", "391.20", "Hesaplanan KDV", True),
        ]
        profile = ClientProfile(client_id="client-1", title="Client", tax_id="1111111111", has_chart_accounts=True)

        with tempfile.TemporaryDirectory() as temp_dir:
            chart_path = Path(temp_dir) / "chart.csv"
            chart_path.write_text(
                "account_code,account_name,is_detail_account\n"
                + "\n".join(f"{account.raw_account_code},{account.account_name},true" for account in accounts),
                encoding="utf-8",
            )
            run = simulate_chart_run(
                chart_path,
                [invoice],
                profile,
                AcceptedSemanticAccountClassifier("600.20"),
            )
        result = run.invoice_results[0]

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.counterparty_match_code, "120.01")
        self.assertEqual(result.selected_customer_account, "120.01")

    def test_new_sales_counterparty_code_uses_customer_tax_identifier(self) -> None:
        invoice = ParsedInvoice(
            file_name="sales-new-customer.pdf",
            provider_hint="Client",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="SATIS",
            invoice_no="SLS2026000000010",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1111111111", "9999999999"),
            vat_rates=("0",),
            goods_services_total="1000.00",
            vat_total="0.00",
            special_tax_total="",
            tax_inclusive_total="1000.00",
            payable_total="1000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_tax_id="1111111111",
            recipient_tax_id="9999999999",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            zero_vat_revenue_account="600.00.3065",
            customer_account="120.01",
            next_customer_account="120.A02",
        )
        profile = ClientProfile(client_id="client-1", title="Client", tax_id="1111111111", has_chart_accounts=True)

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.suggested_counterparty_account, "120.9999999999")
        self.assertEqual(result.counterparty_creation_suggestion["suggested_code"], "120.9999999999")

    def test_new_purchase_counterparty_code_uses_supplier_tax_identifier(self) -> None:
        invoice = ParsedInvoice(
            file_name="purchase-new-supplier.pdf",
            provider_hint="Supplier",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="PUR2026000000010",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("8888888888", "1111111111"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            issuer_tax_id="8888888888",
            recipient_tax_id="1111111111",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
            next_supplier_account="320.A02",
        )
        profile = ClientProfile(client_id="client-1", title="Client", tax_id="1111111111", has_chart_accounts=True)

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.suggested_counterparty_account, "320.8888888888")
        self.assertEqual(result.counterparty_creation_suggestion["suggested_code"], "320.8888888888")

    def test_matching_simulation_marks_incomplete_client_profile_for_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="rexton.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=False,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)

        self.assertEqual(result.export_status, "review_required")
        self.assertIn("onboarding_missing_chart_accounts", result.review_reason_codes)

    def test_matching_simulation_keeps_zero_amount_invoice_in_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="zero.pdf",
            provider_hint="Aposkal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="",
            invoice_type="ISTISNA",
            invoice_no="IST2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("0",),
            goods_services_total="0.00",
            vat_total="0.00",
            special_tax_total="",
            tax_inclusive_total="0.00",
            payable_total="0.00",
            risk_flags=("exemption_manual_review",),
            suggested_route="review_queue",
            parse_notes=(),
            line_items=("Zero amount review item",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection, _task3_profile())

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_quality, "no_positive_amount")
        self.assertEqual(result.draft_lines, ())

    def test_client_onboarding_requires_profile_and_chart_accounts(self) -> None:
        profile = ClientProfile(
            client_id="",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=False,
        )

        check = check_client_onboarding(profile)

        self.assertFalse(check.is_ready)
        self.assertIn("client_id", check.missing_fields)
        self.assertIn("chart_accounts", check.missing_fields)

    def test_brand_model_line_flags_personal_care_for_hearing_center(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Urban Care sac bakim seti", profile)
        status = decide_export_status(is_balanced=True, risk_flags=(), relevance=relevance)

        self.assertEqual(relevance.classification.category, "kisisel_bakim_kozmetik")
        self.assertEqual(relevance.status, "is_alani_disi")
        self.assertEqual(status, "review_required")

    def test_invoice_edge_cases_flags_visible_cancellation_without_return_classification(self) -> None:
        summary = summarize_invoice_edge_cases(
            "fatura.pdf",
            "Fatura No: ABC2026000000001\nBU FATURA IPTAL EDILMISTIR\nGENEL TOPLAM 120,00",
            extracted_char_count=180,
        )

        self.assertIn("cancelled_invoice_visible", summary.risk_flags)
        self.assertNotIn("return_invoice_manual_review", summary.risk_flags)

    def test_brand_model_line_allows_hearing_device_for_hearing_center(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Rexton RLi 20", profile)
        status = decide_export_status(is_balanced=True, risk_flags=(), relevance=relevance)

        self.assertEqual(relevance.classification.category, "isitme_cihazi")
        self.assertEqual(relevance.status, "uygun")
        self.assertEqual(status, "export_ready")

    def test_activity_tag_allows_hearing_device_when_activity_text_is_generic(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Medikal Perakende A",
            tax_id="1234567890",
            activity_description="Belirli bir mala tahsis edilmis magazalarda satis",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Rexton RLi 20", profile)

        self.assertEqual(relevance.status, "uygun")
        self.assertEqual(relevance.relation, "core_business")
        self.assertEqual(relevance.account_treatment, "stock_or_cogs")
        self.assertFalse(relevance.requires_accountant_review)
        self.assertIn("activity_tag:hearing_aid", relevance.evidence)

    def test_food_service_tags_treat_food_inputs_as_core_stock_or_cogs(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Kafe A",
            tax_id="1234567890",
            activity_description="Restoran ve kafe hizmetleri",
            nace_code="561001",
            activity_tags=("food_service",),
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Domates ve gida alimi", profile)

        self.assertEqual(relevance.classification.category, "gida_alimi")
        self.assertEqual(relevance.status, "uygun")
        self.assertEqual(relevance.relation, "core_business")
        self.assertEqual(relevance.account_treatment, "stock_or_cogs")
        self.assertFalse(relevance.requires_accountant_review)

    def test_fixed_asset_candidate_stays_in_review_even_when_activity_is_related(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Yazilim A",
            tax_id="1234567890",
            activity_description="Bilgisayar programlama faaliyetleri",
            nace_code="620101",
            activity_tags=("software_service", "digital_service"),
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        relevance = assess_business_relevance("Macbook Pro laptop bilgisayar", profile)
        status = decide_export_status(is_balanced=True, risk_flags=(), relevance=relevance)

        self.assertEqual(relevance.classification.category, "computer_equipment")
        self.assertEqual(relevance.relation, "adjacent_business")
        self.assertEqual(relevance.account_treatment, "fixed_asset_review")
        self.assertTrue(relevance.requires_accountant_review)
        self.assertEqual(status, "review_required")

    def test_build_activity_profile_creates_controlled_tags_from_nace_and_text(self) -> None:
        profile = build_activity_profile(
            activity_description="Belirli bir mala tahsis edilmis magazalarda isitme cihazlari satisi",
            nace_code="477401",
        )

        self.assertEqual(profile.primary_activity, "hearing_aid_sales_service")
        self.assertEqual(profile.nace_family, "retail_trade")
        self.assertEqual(profile.activity_tags, ("hearing_aid", "medical_retail", "retail_trade"))
        self.assertIn("isitme_cihazi", profile.relevance_hints)
        self.assertGreaterEqual(profile.confidence, 85)
        self.assertFalse(profile.needs_review)

    def test_static_first_classifier_skips_ai_for_high_confidence_static_match(self) -> None:
        provider = FakeProductProvider(
            {"category": "bilinmeyen", "confidence": 40, "reason": "fallback", "evidence": []}
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=70),
        )

        result = classifier.classify("Rexton RLi 20", supplier_hint="Rexton Medikal")

        self.assertFalse(result.ai_used)
        self.assertEqual(result.classification.category, "isitme_cihazi")
        self.assertEqual(result.skipped_reason, "static_high_confidence")
        self.assertEqual(provider.requests, [])

    def test_static_first_classifier_calls_provider_for_unknown_line_with_schema(self) -> None:
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 84,
                "reason": "Model odyoloji cihaz ailesine benziyor.",
                "evidence": ["ai:model_family"],
                "suggested_account_code": "770.01",
                "suggested_counterparty_code": "320.01.015",
                "risk_flags": ["accountant_review_required"],
                "account_reason": "Hesap plani adaylari icinden medikal gider hesabi secildi.",
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, max_input_chars=24),
        )

        result = classifier.classify(
            "ZX Sonic Pro 9 receiver unit",
            supplier_hint="Medikal Tedarik",
            context=AiClassificationContext(
                client_activity="Isitme cihazi satis ve servis",
                account_candidates=("770.01", "760.01"),
                counterparty_candidates=("320.01.015",),
            ),
        )

        self.assertTrue(result.ai_used)
        self.assertEqual(result.provider, "fake_llm")
        self.assertEqual(result.classification.category, "isitme_cihazi")
        self.assertEqual(result.suggested_account_code, "770.01")
        self.assertEqual(result.suggested_counterparty_code, "320.01.015")
        self.assertEqual(result.risk_flags, ("accountant_review_required",))
        self.assertIn("medikal gider", result.account_reason)
        self.assertIn("ai_schema_validated", result.classification.evidence)
        self.assertEqual(provider.requests[0].to_schema_payload()["raw_line"], "ZX Sonic Pro 9 receiver")
        self.assertEqual(provider.requests[0].to_schema_payload()["account_candidates"], ["770.01", "760.01"])

    def test_static_first_classifier_records_ai_trace_payload_response_and_validation(self) -> None:
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 84,
                "reason": "Model odyoloji cihaz ailesine benziyor.",
                "evidence": ["ai:model_family"],
                "suggested_account_code": "770.01",
                "suggested_counterparty_code": "320.01.015",
                "risk_flags": [],
                "account_reason": "Mevcut adaylar icinden cihaz gider hesabi secildi.",
                "product_identity": "ZX Sonic Pro receiver",
                "needs_research": False,
                "research_query": "",
            }
        )
        provider.product_classification_instructions = "AI accounting prompt"
        provider.model = "fake-model"
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, max_input_chars=64),
        )

        result = classifier.classify(
            "ZX Sonic Pro 9 receiver unit",
            supplier_hint="Medikal Tedarik",
            context=AiClassificationContext(
                client_activity="Isitme cihazi satis ve servis",
                account_candidates=("770.01", "760.01"),
                counterparty_candidates=("320.01.015",),
            ),
        )

        self.assertTrue(result.ai_trace)
        trace = result.ai_trace[0]
        self.assertEqual(trace["stage"], "final_account")
        self.assertEqual(trace["provider"], "fake_llm")
        self.assertEqual(trace["model"], "fake-model")
        self.assertEqual(trace["validation_status"], "accepted")
        self.assertEqual(trace["system_prompt"], "AI accounting prompt")
        self.assertEqual(trace["request_payload"]["raw_line"], "ZX Sonic Pro 9 receiver unit")
        self.assertEqual(trace["request_payload"]["account_candidates"], ["770.01", "760.01"])
        self.assertEqual(trace["provider_response"]["suggested_account_code"], "770.01")
        self.assertEqual(trace["accepted_result"]["selected_account_code"], "770.01")
        self.assertEqual(trace["accepted_result"]["selected_counterparty_code"], "320.01.015")
        self.assertNotIn("api_key", trace)
        self.assertNotIn("Authorization", str(trace))

    def test_static_first_classifier_serializes_sanitized_semantic_decision_attempt(self) -> None:
        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 88,
                "reason": "Canonical satir isitme cihazi alimini gosteriyor.",
                "evidence": ["canonical_line:line-1"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01.015",
                "risk_flags": [],
                "account_reason": "Gercek stok hesabi adaylar arasindan secildi.",
                "product_identity": "ZX Sonic Pro 9",
                "needs_research": False,
                "research_query": "",
                "authorization": "Bearer provider-secret",
            }
        )
        provider.model = "fake-model"
        provider.product_classification_prompt_version = "test-semantic-v1"
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = classifier.classify(
            "ZX Sonic Pro 9",
            supplier_hint="Medikal Tedarik",
            context=AiClassificationContext(
                canonical_lines=(
                    {
                        "canonical_line_id": "line-1",
                        "description": "ZX Sonic Pro 9",
                        "taxable_amount": "1000.00",
                        "vat_rate": "20",
                    },
                ),
                account_candidates=("153.01", "770.01"),
                counterparty_candidates=("320.01.015",),
            ),
        )

        self.assertEqual(len(result.semantic_attempts), 1)
        attempt = result.semantic_attempts[0]
        self.assertEqual(
            set(attempt),
            {
                "attempt_id",
                "stage",
                "canonical_line_ids",
                "prompt_version",
                "provider",
                "model",
                "candidate_account_codes",
                "candidate_counterparty_codes",
                "validated_response",
                "validation_errors",
                "accepted",
                "superseded_by_attempt_id",
            },
        )
        self.assertTrue(attempt["attempt_id"])
        self.assertEqual(attempt["stage"], "initial_account_decision")
        self.assertEqual(attempt["canonical_line_ids"], ["line-1"])
        self.assertEqual(attempt["prompt_version"], "test-semantic-v1")
        self.assertEqual(attempt["provider"], "fake_llm")
        self.assertEqual(attempt["model"], "fake-model")
        self.assertEqual(attempt["candidate_account_codes"], ["153.01", "770.01"])
        self.assertEqual(attempt["candidate_counterparty_codes"], ["320.01.015"])
        self.assertEqual(attempt["validated_response"]["suggested_account_code"], "153.01")
        self.assertEqual(attempt["validation_errors"], [])
        self.assertTrue(attempt["accepted"])
        self.assertEqual(result.accepted_semantic_attempt_id, attempt["attempt_id"])
        self.assertNotIn("provider-secret", str(attempt))

    def test_semantic_attempt_sanitizes_secrets_inside_allowed_evidence_fields(self) -> None:
        attempt = serialize_semantic_decision_attempt(
            attempt_id="attempt-safe",
            stage="initial_account_decision",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="fake_llm",
            model="fake-model",
            candidate_account_codes=("153.01",),
            candidate_counterparty_codes=("320.01",),
            validated_response={
                "reason": "Canonical satir isitme cihazidir; Authorization: Bearer secret-token-123",
                "evidence": [
                    "canonical_line:line-1 gercek urun kaniti",
                    "api_key=sk-private-456",
                    {"raw_private_document": "complete-private-evidence"},
                ],
                "line_decisions": [
                    {
                        "canonical_line_id": "line-1",
                        "reason": "Stok hesabi; credential: private-credential-789",
                        "evidence": [
                            "Belge satiri korunmali",
                            "token=private-token-000",
                            {"private_source": "complete-private-line-evidence"},
                        ],
                        "suggested_account_code": "153.01",
                        "raw_private_document": "complete-private-invoice",
                    }
                ],
            },
            validation_errors=(),
            accepted=True,
        )

        serialized = str(attempt)
        self.assertIn("Canonical satir isitme cihazidir", serialized)
        self.assertIn("canonical_line:line-1 gercek urun kaniti", serialized)
        self.assertIn("Belge satiri korunmali", serialized)
        self.assertNotIn("secret-token-123", serialized)
        self.assertNotIn("sk-private-456", serialized)
        self.assertNotIn("private-credential-789", serialized)
        self.assertNotIn("private-token-000", serialized)
        self.assertNotIn("complete-private-invoice", serialized)
        self.assertNotIn("complete-private-evidence", serialized)
        self.assertNotIn("complete-private-line-evidence", serialized)

    def test_semantic_attempt_redacts_json_credentials_and_full_authorization_values(self) -> None:
        attempt = serialize_semantic_decision_attempt(
            attempt_id="attempt-json-credentials",
            stage="initial_account_decision",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="fake_llm",
            model="fake-model",
            candidate_account_codes=("153.01",),
            candidate_counterparty_codes=("320.01",),
            validated_response={
                "reason": (
                    'Canonical satir kaniti; {"password":"hunter2", '
                    '"api_key": "sk-json-private"}; '
                    "Authorization: Basic dXNlcjpwYXNz; hesap adayi 153.01"
                ),
                "evidence": [
                    'Kaynak ozetidir; "token"="quoted-private-token", '
                    "Authorization=Basic YWRtaW46c2VjcmV0; uretici kaynagi dogruladi"
                ],
            },
            validation_errors=(),
            accepted=False,
        )

        serialized = str(attempt)
        self.assertIn("Canonical satir kaniti", serialized)
        self.assertIn("hesap adayi 153.01", serialized)
        self.assertIn("Kaynak ozetidir", serialized)
        self.assertIn("uretici kaynagi dogruladi", serialized)
        self.assertNotIn("hunter2", serialized)
        self.assertNotIn("sk-json-private", serialized)
        self.assertNotIn("quoted-private-token", serialized)
        self.assertNotIn("dXNlcjpwYXNz", serialized)
        self.assertNotIn("YWRtaW46c2VjcmV0", serialized)

    def test_semantic_attempt_redacts_nvidia_api_key_value(self) -> None:
        attempt = serialize_semantic_decision_attempt(
            attempt_id="attempt-nvidia-credential",
            stage="initial_account_decision",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="nvidia",
            model="openai/gpt-oss-120b",
            candidate_account_codes=("153.01",),
            candidate_counterparty_codes=("320.01",),
            validated_response={
                "reason": "Provider note nvapi-private-123456 supports candidate 153.01",
            },
            validation_errors=(),
            accepted=False,
        )

        serialized = str(attempt)
        self.assertIn("supports candidate 153.01", serialized)
        self.assertNotIn("nvapi-private-123456", serialized)

    def test_semantic_attempt_redacts_cloudflare_and_sambanova_key_values(self) -> None:
        attempt = serialize_semantic_decision_attempt(
            attempt_id="attempt-provider-credentials",
            stage="initial_account_decision",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="cloudflare>sambanova",
            model="gpt-oss-120b",
            candidate_account_codes=("153.01",),
            candidate_counterparty_codes=("320.01",),
            validated_response={
                "reason": "Tokens cfai-private-123456 and snapi-private-123456 support candidate 153.01",
            },
            validation_errors=(),
            accepted=False,
        )

        serialized = str(attempt)
        self.assertIn("support candidate 153.01", serialized)
        self.assertNotIn("cfai-private-123456", serialized)
        self.assertNotIn("snapi-private-123456", serialized)

    def test_semantic_attempt_redacts_document_payload_strings_but_keeps_useful_summaries(self) -> None:
        compact_invoice = (
            "<Invoice><cbc:ID>INV-PRIVATE-1</cbc:ID>"
            "<SupplierParty><Name>Private Supplier</Name><TaxID>1111111111</TaxID>"
            "</SupplierParty><InvoiceLine><Item>Private hearing aid</Item>"
            "<Amount>12500.00</Amount></InvoiceLine></Invoice>"
        )
        ocr_document = """--- OCR DOCUMENT START ---
FATURA NO: OCR-PRIVATE-1
SATICI UNVAN: Private Supplier Ltd
SATICI VKN: 1111111111
ALICI UNVAN: Private Customer Ltd
ALICI VKN: 2222222222
KALEM: Private service description
MATRAH: 1000.00
KDV: 200.00
TOPLAM: 1200.00
--- OCR DOCUMENT END ---"""
        attempt = serialize_semantic_decision_attempt(
            attempt_id="attempt-document-payload",
            stage="research_synthesis",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="fake_llm",
            model="fake-model",
            candidate_account_codes=("153.01",),
            candidate_counterparty_codes=("320.01",),
            validated_response={
                "reason": compact_invoice,
                "evidence": [
                    ocr_document,
                    "Canonical line line-1 describes a hearing aid and supports 153.01.",
                    "manufacturer.example source summary: Model X is a hearing aid.",
                ],
                "account_reason": "Real chart candidate 153.01 matches the canonical product line.",
            },
            validation_errors=(),
            accepted=False,
        )

        response = attempt["validated_response"]
        self.assertEqual(response["reason"], "[redacted-document-content]")
        self.assertEqual(response["evidence"][0], "[redacted-document-content]")
        self.assertEqual(
            response["evidence"][1],
            "Canonical line line-1 describes a hearing aid and supports 153.01.",
        )
        self.assertEqual(
            response["evidence"][2],
            "manufacturer.example source summary: Model X is a hearing aid.",
        )
        self.assertEqual(
            response["account_reason"],
            "Real chart candidate 153.01 matches the canonical product line.",
        )
        self.assertNotIn("Private Supplier", str(attempt))
        self.assertNotIn("1111111111", str(attempt))
        self.assertNotIn("OCR-PRIVATE-1", str(attempt))

    def test_semantic_attempt_redacts_high_density_document_fields_without_an_envelope(self) -> None:
        dense_document = """FATURA NO: PRIVATE-2
KALEM: Private line 1
KALEM: Private line 2
KALEM: Private line 3
KALEM: Private line 4
KALEM: Private line 5
KALEM: Private line 6
KDV: 200.00
TOPLAM: 1200.00"""
        attempt = serialize_semantic_decision_attempt(
            attempt_id="attempt-dense-document",
            stage="initial_account_decision",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="fake_llm",
            model="fake-model",
            validated_response={
                "reason": dense_document,
                "account_reason": "Canonical line supports the real chart candidate 153.01.",
            },
            validation_errors=(),
            accepted=False,
        )

        self.assertEqual(
            attempt["validated_response"]["reason"],
            "[redacted-document-content]",
        )
        self.assertEqual(
            attempt["validated_response"]["account_reason"],
            "Canonical line supports the real chart candidate 153.01.",
        )

    def test_semantic_attempt_duplicate_id_is_idempotent_only_for_identical_content(self) -> None:
        original = serialize_semantic_decision_attempt(
            attempt_id="attempt-1",
            stage="initial_account_decision",
            canonical_line_ids=("line-1",),
            prompt_version="semantic-v1",
            provider="fake_llm",
            model="fake-model",
            candidate_account_codes=("153.01",),
            candidate_counterparty_codes=(),
            validated_response={"suggested_account_code": "153.01"},
            validation_errors=(),
            accepted=True,
        )

        self.assertEqual(merge_semantic_attempts((original,), (dict(original),)), [original])
        conflicting = {**original, "model": "different-model"}
        with self.assertRaisesRegex(ValueError, "attempt-1"):
            merge_semantic_attempts((original,), (conflicting,))

    def test_semantic_attempt_history_rejects_invalid_acceptance_and_supersession_graphs(self) -> None:
        def attempt(
            attempt_id: str,
            *,
            accepted: bool,
            superseded_by_attempt_id: str = "",
        ) -> dict[str, object]:
            return serialize_semantic_decision_attempt(
                attempt_id=attempt_id,
                stage="account_correction",
                canonical_line_ids=("line-1",),
                prompt_version="semantic-v1",
                provider="fake_llm",
                model="fake-model",
                candidate_account_codes=("153.01",),
                candidate_counterparty_codes=(),
                validated_response={"suggested_account_code": "153.01"},
                validation_errors=(),
                accepted=accepted,
                superseded_by_attempt_id=superseded_by_attempt_id,
            )

        first = attempt("attempt-1", accepted=True)
        second = attempt("attempt-2", accepted=True)
        with self.assertRaisesRegex(ValueError, "multiple accepted"):
            merge_semantic_attempts((first, second))

        missing_target = attempt("attempt-missing", accepted=False, superseded_by_attempt_id="absent")
        with self.assertRaisesRegex(ValueError, "absent"):
            merge_semantic_attempts((missing_target,))

        cycle_a = attempt("cycle-a", accepted=False, superseded_by_attempt_id="cycle-b")
        cycle_b = attempt("cycle-b", accepted=True, superseded_by_attempt_id="cycle-a")
        with self.assertRaisesRegex(ValueError, "cycle"):
            merge_semantic_attempts((cycle_a, cycle_b))

        valid_first = attempt("valid-1", accepted=True, superseded_by_attempt_id="valid-2")
        valid_second = attempt("valid-2", accepted=True)
        valid = merge_semantic_attempt_result(
            {
                "semantic_attempts": [valid_first, valid_second],
                "accepted_semantic_attempt_id": "valid-2",
            }
        )
        self.assertEqual(valid["accepted_semantic_attempt_id"], "valid-2")

        rejected = attempt("rejected", accepted=False)
        with self.assertRaisesRegex(ValueError, "accepted_semantic_attempt_id"):
            merge_semantic_attempt_result(
                {
                    "semantic_attempts": [rejected],
                    "accepted_semantic_attempt_id": "rejected",
                }
            )

    def test_provider_exception_text_is_not_persisted_in_result_or_ai_trace(self) -> None:
        class SecretRaisingProvider:
            provider_name = "secret_provider"
            model = "secret-model"

            def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
                raise RuntimeError(
                    "Authorization: Bearer fake-provider-credential private-invoice-fragment"
                )

        classifier = StaticFirstClassifier(
            provider=SecretRaisingProvider(),
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = classifier.classify("Belirsiz urun", supplier_hint="Tedarikci")

        persisted = f"{result.provider_reason} {result.ai_trace} {result.semantic_attempts}"
        self.assertIn("provider_error:RuntimeError", persisted)
        self.assertNotIn("fake-provider-credential", persisted)
        self.assertNotIn("private-invoice-fragment", persisted)

    def test_ai_schema_payload_keeps_configured_account_candidate_limit(self) -> None:
        account_codes = tuple(f"770.{index:02d}" for index in range(1, 21))
        request = AiClassificationRequest(
            raw_line="Belirsiz hizmet",
            supplier_hint="Tedarikci",
            allowed_categories=("bilinmeyen",),
            max_input_chars=420,
            context=AiClassificationContext(
                account_candidates=account_codes,
                account_candidate_limit=40,
            ),
        )

        payload = request.to_schema_payload()

        self.assertEqual(payload["account_candidates"], list(account_codes))
        self.assertEqual(payload["output_schema"]["properties"]["suggested_account_code"]["enum"], ["", *account_codes])

    def test_ai_line_batch_schema_constrains_canonical_ids_and_accounts(self) -> None:
        from app.domain.ai_classification import AiCandidateStrategy

        request = AiClassificationRequest(
            raw_line="Cihaz ve bakim satirlari",
            supplier_hint="Medikal Tedarik",
            allowed_categories=("isitme_cihazi", "bakim_hizmeti", "bilinmeyen"),
            max_input_chars=420,
            context=AiClassificationContext(
                account_candidates=("153.01", "760.01"),
                canonical_lines=(
                    {"canonical_line_id": "line-1", "description": "Cihaz"},
                    {"canonical_line_id": "line-2", "description": "Bakim"},
                ),
                candidate_strategy=AiCandidateStrategy(mode="single_stage", stage="line_batch"),
            ),
        )

        payload = request.to_schema_payload()
        line_decisions = payload["output_schema"]["properties"]["line_decisions"]
        decision = line_decisions["items"]["properties"]

        self.assertEqual(payload["candidate_strategy"]["stage"], "line_batch")
        self.assertEqual(line_decisions["minItems"], 2)
        self.assertEqual(line_decisions["maxItems"], 2)
        self.assertEqual(decision["canonical_line_id"]["enum"], ["line-1", "line-2"])
        self.assertEqual(decision["suggested_account_code"]["enum"], ["", "153.01", "760.01"])
        self.assertEqual(line_decisions["items"]["additionalProperties"], False)

    def test_ai_line_batch_output_contains_no_accounting_math_fields(self) -> None:
        from app.domain.ai_classification import AiCandidateStrategy

        payload = AiClassificationRequest(
            raw_line="Cihaz ve bakim",
            supplier_hint="Medikal Tedarik",
            allowed_categories=("isitme_cihazi", "medikal_sarf", "bilinmeyen"),
            max_input_chars=1000,
            context=AiClassificationContext(
                account_candidates=("153.01", "760.01"),
                counterparty_candidates=("320.01",),
                canonical_lines=({"canonical_line_id": "line-1", "description": "Cihaz"},),
                candidate_strategy=AiCandidateStrategy(mode="single_stage", stage="line_batch"),
            ),
        ).to_schema_payload()

        prohibited = {
            "amount", "tax_amount", "gross_amount", "vat_amount", "vat_total",
            "debit", "credit", "balance", "payable_total", "taxable_amount",
        }

        def collect_property_names(schema: object) -> set[str]:
            if not isinstance(schema, dict):
                return set()
            names = set(schema.get("properties", {}))
            for child in schema.get("properties", {}).values():
                names.update(collect_property_names(child))
            if "items" in schema:
                names.update(collect_property_names(schema["items"]))
            return names

        output_names = collect_property_names(payload["output_schema"])
        self.assertTrue(prohibited.isdisjoint(output_names), prohibited & output_names)

    def test_accounting_provider_prompt_requires_complete_line_batch_identity(self) -> None:
        from app.domain.openai_provider import ChatCompletionsAccountingProvider, OpenAiAccountingProvider

        for instructions in (
            OpenAiAccountingProvider.product_classification_instructions,
            ChatCompletionsAccountingProvider.product_classification_instructions,
        ):
            self.assertIn("line_batch", instructions)
            self.assertIn("canonical_line_id", instructions)
            self.assertIn("tam bir kez", instructions)

    def test_static_classifier_accepts_complete_line_batch_in_one_provider_call(self) -> None:
        from app.domain.ai_classification import AiCandidateStrategy

        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 90,
                "reason": "Fatura satirlari ayri ayri degerlendirildi.",
                "evidence": ["line_batch"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Mevcut hesap plani kullanildi.",
                "product_identity": "Cihaz ve bakim",
                "needs_research": False,
                "research_query": "",
                "line_decisions": [
                    {
                        "canonical_line_id": "line-1",
                        "category": "isitme_cihazi",
                        "confidence": 94,
                        "product_identity": "Isitme cihazi",
                        "suggested_account_code": "153.01",
                        "reason": "Satilacak cihaz stogu.",
                        "evidence": ["Cihaz"],
                        "needs_research": False,
                        "research_query": "",
                        "risk_flags": [],
                    },
                    {
                        "canonical_line_id": "line-2",
                        "category": "medikal_sarf",
                        "confidence": 82,
                        "product_identity": "Bakim hizmeti",
                        "suggested_account_code": "760.01",
                        "reason": "Bakim gideri.",
                        "evidence": ["Bakim"],
                        "needs_research": False,
                        "research_query": "",
                        "risk_flags": [],
                    },
                ],
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = classifier.classify(
            "Cihaz ve bakim",
            supplier_hint="Medikal Tedarik",
            context=AiClassificationContext(
                account_candidates=("153.01", "760.01"),
                counterparty_candidates=("320.01",),
                canonical_lines=(
                    {"canonical_line_id": "line-1", "description": "Cihaz"},
                    {"canonical_line_id": "line-2", "description": "Bakim"},
                ),
                candidate_strategy=AiCandidateStrategy(mode="single_stage", stage="line_batch"),
            ),
        )

        self.assertTrue(result.ai_used)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            [decision["canonical_line_id"] for decision in result.line_decisions],
            ["line-1", "line-2"],
        )
        self.assertEqual(
            [decision["suggested_account_code"] for decision in result.line_decisions],
            ["153.01", "760.01"],
        )

    def test_line_batch_with_pending_line_research_is_not_accepted_before_synthesis(self) -> None:
        from app.domain.ai_classification import AiCandidateStrategy

        provider = FakeProductProvider(
            {
                "category": "kisisel_bakim_kozmetik",
                "confidence": 90,
                "reason": "Satirlar birlikte degerlendirildi.",
                "evidence": ["line_batch"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Mevcut hesap plani kullanildi.",
                "product_identity": "Kozmetik urunler",
                "needs_research": False,
                "research_query": "",
                "line_decisions": [
                    {
                        "canonical_line_id": "line-1",
                        "category": "kisisel_bakim_kozmetik",
                        "confidence": 90,
                        "product_identity": "Temizleme jeli",
                        "suggested_account_code": "153.01",
                        "reason": "Kozmetik urun.",
                        "evidence": ["canonical_line"],
                        "needs_research": False,
                        "research_query": "",
                        "risk_flags": [],
                    },
                    {
                        "canonical_line_id": "line-2",
                        "category": "kisisel_bakim_kozmetik",
                        "confidence": 75,
                        "product_identity": "Serum",
                        "suggested_account_code": "153.01",
                        "reason": "Urun kimligi kaynakla dogrulanmali.",
                        "evidence": ["canonical_line"],
                        "needs_research": True,
                        "research_query": "HB5 Suract Serum",
                        "risk_flags": ["research_required"],
                    },
                ],
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=101),
        )

        result = classifier.classify(
            "Temizleme jeli ve serum",
            supplier_hint="Kozmetik Tedarik",
            context=AiClassificationContext(
                account_candidates=("153.01",),
                counterparty_candidates=("320.01",),
                canonical_lines=(
                    {"canonical_line_id": "line-1", "description": "Temizleme jeli"},
                    {"canonical_line_id": "line-2", "description": "HB5 Suract Serum"},
                ),
                candidate_strategy=AiCandidateStrategy(mode="single_stage", stage="line_batch"),
            ),
        )

        self.assertTrue(result.ai_used)
        self.assertEqual(len(result.semantic_attempts), 1)
        self.assertFalse(result.semantic_attempts[0]["accepted"])
        self.assertEqual(result.accepted_semantic_attempt_id, "")

    def test_line_batch_bypasses_single_line_static_shortcut(self) -> None:
        from app.domain.ai_classification import AiCandidateStrategy

        provider = FakeProductProvider(
            {
                "category": "isitme_cihazi",
                "confidence": 94,
                "reason": "Butun canonical satirlar birlikte degerlendirildi.",
                "evidence": ["line_batch"],
                "suggested_account_code": "153.01",
                "suggested_counterparty_code": "320.01",
                "risk_flags": [],
                "account_reason": "Gercek hesap plani adayi secildi.",
                "product_identity": "Isitme cihazlari",
                "needs_research": False,
                "research_query": "",
                "line_decisions": [
                    {
                        "canonical_line_id": "line-1",
                        "category": "isitme_cihazi",
                        "confidence": 94,
                        "product_identity": "Rexton RLi 20",
                        "suggested_account_code": "153.01",
                        "reason": "Satilacak cihaz stogu.",
                        "evidence": ["Rexton RLi 20"],
                        "needs_research": False,
                        "research_query": "",
                        "risk_flags": [],
                    }
                ],
            }
        )
        classifier = StaticFirstClassifier(
            provider=provider,
            policy=AiClassificationPolicy(enabled=True, static_confidence_threshold=70),
        )

        result = classifier.classify(
            "Rexton RLi 20",
            supplier_hint="Rexton Medikal",
            context=AiClassificationContext(
                account_candidates=("153.01",),
                counterparty_candidates=("320.01",),
                canonical_lines=({"canonical_line_id": "line-1", "description": "Rexton RLi 20"},),
                candidate_strategy=AiCandidateStrategy(mode="single_stage", stage="line_batch"),
            ),
        )

        self.assertTrue(result.ai_used)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result.line_decisions[0]["canonical_line_id"], "line-1")

    def test_static_first_classifier_rejects_invalid_provider_schema(self) -> None:
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider({"category": "serbest", "confidence": 110, "reason": ""}),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = classifier.classify("Bilinmeyen marka kalem")

        self.assertTrue(result.ai_used)
        self.assertEqual(result.classification.category, "bilinmeyen")
        self.assertIn("ai_invalid_schema", result.classification.evidence)
        self.assertEqual(result.ai_trace[0]["validation_status"], "invalid_schema")
        self.assertEqual(result.ai_trace[0]["provider_response"]["category"], "serbest")

    def test_static_first_classifier_falls_back_when_provider_raises(self) -> None:
        class RaisingProductProvider:
            provider_name = "raising_llm"

            def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
                raise RuntimeError("provider unavailable")

        classifier = StaticFirstClassifier(
            provider=RaisingProductProvider(),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = classifier.classify("Bilinmeyen marka kalem")

        self.assertFalse(result.ai_used)
        self.assertEqual(result.provider, "raising_llm")
        self.assertEqual(result.skipped_reason, "ai_provider_error")
        self.assertEqual(result.classification.category, "bilinmeyen")
        self.assertIn("ai_provider_error", result.classification.evidence)
        self.assertEqual(result.provider_reason, "provider_error:RuntimeError")
        self.assertEqual(result.ai_trace[0]["validation_status"], "provider_error")
        self.assertEqual(result.ai_trace[0]["error"], "provider_error:RuntimeError")

    def test_openai_accounting_provider_posts_limited_structured_payload(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"category":"isitme_cihazi","confidence":86,'
                                        '"reason":"Kalem isitme cihazi parcasina benziyor.",'
                                        '"evidence":["receiver"],"suggested_account_code":"770.01",'
                                        '"suggested_counterparty_code":"320.01.015",'
                                        '"risk_flags":["accountant_review_required"],'
                                        '"account_reason":"Mevcut hesap adaylari icinden secildi."}'
                                    ),
                                }
                            ]
                        }
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = OpenAiAccountingProvider(api_key="sk-test", model="gpt-5.4-mini", http_client=FakeClient())
        response = provider.classify_product(
            AiClassificationRequest(
                raw_line="ZX Sonic Pro 9 receiver unit",
                supplier_hint="Medikal Tedarik",
                allowed_categories=("isitme_cihazi", "bilinmeyen"),
                max_input_chars=80,
                context=AiClassificationContext(
                    client_activity="Isitme cihazi satis ve servis",
                    account_candidates=("770.01",),
                    counterparty_candidates=("320.01.015",),
                ),
            )
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(request_payload["model"], "gpt-5.4-mini")
        self.assertEqual(request_payload["text"]["format"]["type"], "json_schema")
        user_content = request_payload["input"][1]["content"]
        self.assertIn("ZX Sonic Pro 9 receiver unit", user_content)
        self.assertIn("770.01", user_content)
        self.assertNotIn("raw_pdf", user_content.lower())
        self.assertEqual(response["suggested_account_code"], "770.01")
        self.assertEqual(response["suggested_counterparty_code"], "320.01.015")

    def test_openai_provider_posts_canonical_invoice_extraction_payload(self) -> None:
        from app.domain.canonical_invoices import CanonicalExtractionRequest

        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"supplier_party":{"title":"MEDIKAL TEDARIK","tax_id":"9999999999"},'
                                        '"customer_party":{"title":"ORHAN ELIBOL","tax_id":"1234567890"},'
                                        '"line_items":[{"description":"Isitme cihazi","taxable_amount":"1000.00",'
                                        '"vat_rate":"20","tax_amount":"200.00","gross_amount":"1200.00",'
                                        '"evidence":["pdf line 12"]}],'
                                        '"vat_summary":[{"rate":"20","taxable_amount":"1000.00","tax_amount":"200.00"}],'
                                        '"totals":{"goods_services_total":"1000.00","vat_total":"200.00",'
                                        '"tax_inclusive_total":"1200.00","payable_total":"1200.00"}}'
                                    ),
                                }
                            ]
                        }
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = OpenAiAccountingProvider(api_key="sk-test", model="gpt-5.4-mini", http_client=FakeClient())
        response = provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="SATICI MEDIKAL TEDARIK\nSAYIN ORHAN ELIBOL\n1 Isitme cihazi 1000,00 %20 200,00",
                deterministic_payload={"invoice_no": "AAA2026000000005", "line_count": 0},
                client_identity={"title": "ORHAN ELIBOL", "tax_id": "1234567890"},
                max_input_chars=500,
            )
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(request_payload["text"]["format"]["name"], "fisora_invoice_canonical_extraction")
        user_content = request_payload["input"][1]["content"]
        self.assertIn("SATICI MEDIKAL TEDARIK", user_content)
        self.assertNotIn("output_schema", user_content)
        self.assertNotIn('"instructions"', user_content)
        self.assertIn('"mode": "repair"', user_content)
        system_content = request_payload["input"][0]["content"]
        self.assertIn("Parasal hesaplama yapma", system_content)
        self.assertNotIn("taxable_amount + tax_amount = gross_amount", system_content)
        self.assertNotIn("sum(line_items.taxable_amount)", system_content)
        self.assertIn("canonical_line_id", system_content)
        line_schema = request_payload["text"]["format"]["schema"]["properties"]["line_items"]["items"]
        self.assertIn("observed_tax_amount", line_schema["properties"])
        self.assertNotIn("tax_amount", line_schema["properties"])
        self.assertEqual(response["line_items"][0]["description"], "Isitme cihazi")

    def test_canonical_extraction_schema_is_strict_provider_compatible(self) -> None:
        from app.domain.canonical_invoices import canonical_extraction_output_schema

        def assert_strict_object_schema(schema: dict[str, object]) -> None:
            if schema.get("type") == "object":
                properties = schema.get("properties", {})
                self.assertEqual(schema.get("additionalProperties"), False)
                self.assertEqual(set(schema.get("required", [])), set(properties))
                for child in properties.values():
                    assert_strict_object_schema(child)
            if schema.get("type") == "array":
                assert_strict_object_schema(schema["items"])

        assert_strict_object_schema(canonical_extraction_output_schema())

    def test_canonical_extraction_contract_is_observation_only(self) -> None:
        from app.domain.canonical_invoices import CanonicalExtractionRequest
        from app.domain.openai_provider import OpenAiAccountingProvider

        payload = CanonicalExtractionRequest(
            document_text="Cihaz 100,00 KDV %20",
            deterministic_payload={"line_items": [{"canonical_line_id": "line-1"}]},
            client_identity={},
        ).to_schema_payload()
        instructions = (
            f"{payload['instructions']} "
            f"{OpenAiAccountingProvider.canonical_extraction_instructions}"
        )
        self.assertIn("hesaplama yapma", instructions)
        self.assertIn("belgede acikca yazmiyorsa bos string", instructions)
        self.assertNotIn("taxable_amount + tax_amount", instructions)
        self.assertNotIn("taxable_amount * vat_rate", instructions)
        self.assertNotIn("toplamlarini satir toplamlarina esitle", instructions)

        schema = payload["output_schema"]
        line_properties = schema["properties"]["line_items"]["items"]["properties"]
        self.assertIn("observed_taxable_amount", line_properties)
        self.assertIn("observed_vat_rate", line_properties)
        self.assertIn("observed_tax_amount", line_properties)
        self.assertIn("observed_gross_amount", line_properties)
        self.assertNotIn("taxable_amount", line_properties)
        self.assertNotIn("tax_amount", line_properties)
        self.assertNotIn("gross_amount", line_properties)
        self.assertIn("observed_totals", schema["properties"])
        self.assertNotIn("totals", schema["properties"])

    def test_canonical_extraction_request_constrains_existing_line_id_coverage(self) -> None:
        from app.domain.canonical_invoices import CanonicalExtractionRequest

        payload = CanonicalExtractionRequest(
            document_text="Iki satirli fatura",
            deterministic_payload={
                "line_items": [
                    {"canonical_line_id": "pdf-line-1"},
                    {"canonical_line_id": "pdf-line-2"},
                ]
            },
            client_identity={},
        ).to_schema_payload()

        line_items = payload["output_schema"]["properties"]["line_items"]
        line_id = line_items["items"]["properties"]["canonical_line_id"]
        self.assertEqual(line_items["minItems"], 2)
        self.assertEqual(line_items["maxItems"], 2)
        self.assertEqual(line_id["enum"], ["pdf-line-1", "pdf-line-2"])

    def test_canonical_extraction_request_separates_discovery_from_repair(self) -> None:
        from app.domain.canonical_invoices import CanonicalExtractionRequest

        repair = CanonicalExtractionRequest(
            document_text="Iki satirli fatura",
            deterministic_payload={
                "line_items": [
                    {"canonical_line_id": "pdf-line-1"},
                    {"canonical_line_id": "pdf-line-2"},
                ]
            },
            client_identity={},
            mode="repair",
        ).to_schema_payload()
        discovery = CanonicalExtractionRequest(
            document_text="Parserin satirlari eksik gordugu fatura",
            deterministic_payload={"line_items": [{"canonical_line_id": "partial-line"}]},
            client_identity={},
            mode="discovery",
        ).to_schema_payload()

        repair_lines = repair["output_schema"]["properties"]["line_items"]
        discovery_lines = discovery["output_schema"]["properties"]["line_items"]
        self.assertEqual(repair["mode"], "repair")
        self.assertEqual(repair_lines["minItems"], 2)
        self.assertEqual(repair_lines["maxItems"], 2)
        self.assertEqual(
            repair_lines["items"]["properties"]["canonical_line_id"]["enum"],
            ["pdf-line-1", "pdf-line-2"],
        )
        self.assertEqual(discovery["mode"], "discovery")
        self.assertEqual(discovery_lines["minItems"], 1)
        self.assertNotIn("maxItems", discovery_lines)
        self.assertEqual(
            discovery_lines["items"]["properties"]["canonical_line_id"]["enum"],
            [""],
        )
        self.assertIn("tum fatura satirlarini", discovery["instructions"])
        self.assertIn("canonical_line_id", repair["instructions"])

    def test_openai_provider_posts_review_rule_interpretation_payload(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"status":"ready",'
                                        '"summary_tr":"Bu mükellefte Yurtiçi Kargo faturaları kargo gideri olarak önerilecek.",'
                                        '"trigger_tr":"VKN 9860008925 / Yurtiçi Kargo alış faturası",'
                                        '"action_tr":"Gider hesabı 760.03.010.",'
                                        '"guardrail_tr":"İlk uygulamalarda müşavir kontrolü istenir.",'
                                        '"confidence":90,'
                                        '"reason_codes":["counterparty_tax_id_rule"]}'
                                    ),
                                }
                            ]
                        }
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = OpenAiAccountingProvider(api_key="sk-test", model="gpt-5.4-mini", http_client=FakeClient())
        response = provider.interpret_review_rule(
            {
                "accountant_note": "Bundan sonra bu vergi numarasi ile gelen faturalari kargo gideri olarak isle.",
                "candidate": {"suggested_account_code": "760.03.010"},
                "document": {"counterparty_tax_id": "9860008925", "counterparty_title": "Yurtici Kargo"},
            }
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(request_payload["text"]["format"]["name"], "fisora_review_rule_interpretation")
        user_content = request_payload["input"][1]["content"]
        self.assertIn("accountant_note", user_content)
        self.assertIn("760.03.010", user_content)
        self.assertEqual(response["status"], "ready")
        self.assertIn("Yurtiçi Kargo", response["summary_tr"])

    def test_groq_accounting_provider_posts_openai_compatible_structured_payload(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "output": [
                        {
                            "type": "reasoning",
                            "content": [
                                {
                                    "type": "reasoning_text",
                                    "text": "Internal reasoning text must not be parsed as JSON.",
                                }
                            ],
                        },
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"category":"bilinmeyen","confidence":52,'
                                        '"reason":"Kalem belirsiz, musavir kontrolu gerekli.",'
                                        '"evidence":["belirsiz"],"suggested_account_code":"",'
                                        '"suggested_counterparty_code":"",'
                                        '"risk_flags":["accountant_review_required"],'
                                        '"account_reason":"Hesap adayi yeterli degil."}'
                                    ),
                                }
                            ],
                        },
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = GroqAccountingProvider(api_key="gsk-test", http_client=FakeClient())
        response = provider.classify_product(
            AiClassificationRequest(
                raw_line="Bilinmeyen banka hizmet bedeli",
                supplier_hint="Banka",
                allowed_categories=("genel_gider", "bilinmeyen"),
                max_input_chars=80,
            )
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://api.groq.com/openai/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer gsk-test")
        self.assertEqual(request_payload["model"], "openai/gpt-oss-20b")
        self.assertEqual(request_payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(provider.provider_name, "groq")
        self.assertIn("Bilinmeyen banka hizmet bedeli", request_payload["input"][1]["content"])
        self.assertEqual(response["category"], "bilinmeyen")

    def test_chat_completions_provider_posts_structured_prompt_and_extracts_json(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"category":"genel_gider","confidence":82,'
                                    '"reason":"Banka masrafi genel gider olarak islenebilir.",'
                                    '"evidence":["banka masrafi"],"suggested_account_code":"770.01",'
                                    '"suggested_counterparty_code":"320.B04",'
                                    '"risk_flags":["accountant_review_required"],'
                                    '"account_reason":"Mevcut gider hesabi kullanildi."}'
                                )
                            }
                        }
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                captured["timeout"] = timeout
                return FakeResponse()

        provider = ChatCompletionsAccountingProvider(
            api_key="or-test",
            model="openai/gpt-oss-20b:free",
            chat_completions_url="https://openrouter.ai/api/v1/chat/completions",
            provider_name="openrouter",
            key_name="OPENROUTER_API_KEY",
            extra_headers={"HTTP-Referer": "http://185.184.208.188", "X-Title": "Fisora Operasyon Portal"},
            http_client=FakeClient(),
            max_tokens=512,
        )
        response = provider.classify_product(
            AiClassificationRequest(
                raw_line="Banka pos komisyon bedeli",
                supplier_hint="Banka",
                allowed_categories=("genel_gider", "bilinmeyen"),
                max_input_chars=80,
            )
        )

        request_payload = captured["json"]
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer or-test")
        self.assertEqual(captured["headers"]["HTTP-Referer"], "http://185.184.208.188")
        self.assertEqual(captured["headers"]["X-Title"], "Fisora Operasyon Portal")
        self.assertEqual(request_payload["model"], "openai/gpt-oss-20b:free")
        self.assertFalse(request_payload["stream"])
        self.assertEqual(request_payload.get("max_tokens"), 512)
        self.assertEqual(request_payload["response_format"]["type"], "json_object")
        self.assertIn("Banka pos komisyon bedeli", request_payload["messages"][1]["content"])
        self.assertEqual(response["suggested_account_code"], "770.01")

    def test_chat_completions_provider_posts_canonical_invoice_extraction_payload(self) -> None:
        from app.domain.canonical_invoices import CanonicalExtractionRequest

        captured: dict[str, object] = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"supplier_party":{"title":"MEDIKAL TEDARIK","tax_id":"9999999999"},'
                                    '"customer_party":{"title":"ORHAN ELIBOL","tax_id":"1234567890"},'
                                    '"line_items":[],"vat_summary":[],"totals":{}}'
                                )
                            }
                        }
                    ]
                }

        class FakeClient:
            def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float) -> FakeResponse:
                captured["json"] = json
                return FakeResponse()

        provider = ChatCompletionsAccountingProvider(
            api_key="or-test",
            model="openai/gpt-oss-20b:free",
            chat_completions_url="https://openrouter.ai/api/v1/chat/completions",
            provider_name="openrouter",
            key_name="OPENROUTER_API_KEY",
            http_client=FakeClient(),
        )

        response = provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="SATICI MEDIKAL TEDARIK\nSAYIN ORHAN ELIBOL",
                deterministic_payload={"invoice_no": "AAA2026000000005", "line_count": 0},
                client_identity={"title": "ORHAN ELIBOL", "tax_id": "1234567890"},
                max_input_chars=500,
            )
        )

        request_payload = captured["json"]
        self.assertIn("canonical JSON", request_payload["messages"][0]["content"])
        self.assertIn("fisora_invoice_canonical_extraction", request_payload["messages"][1]["content"])
        self.assertEqual(response["supplier_party"]["tax_id"], "9999999999")

    def test_classification_prompts_are_stage_specific(self) -> None:
        from app.domain.ai_classification import AiCandidateStrategy, AiClassificationContext, AiClassificationRequest
        from app.domain.openai_provider import classification_instructions_for

        def request(stage: str) -> AiClassificationRequest:
            return AiClassificationRequest(
                raw_line="Bakim hizmeti",
                supplier_hint="Tedarikci",
                allowed_categories=("hizmet", "bilinmeyen"),
                max_input_chars=420,
                context=AiClassificationContext(candidate_strategy=AiCandidateStrategy(stage=stage)),
            )

        family = classification_instructions_for(request("family_select"))
        line = classification_instructions_for(request("line_batch"))
        counterparty = classification_instructions_for(request("counterparty_resolve"))

        self.assertIn("hesap aile", family)
        self.assertNotIn("cari aday", family)
        self.assertIn("canonical_line_id", line)
        self.assertIn("gercek hesap", line)
        self.assertIn("VKN/TCKN", counterparty)
        self.assertNotIn("hesap aile", counterparty)

    def test_ai_runtime_reorders_configured_providers_by_task(self) -> None:
        from app.domain.openai_provider import TaskRoutingAccountingProvider
        from app.workflows.document_processing import build_ai_runtime_from_env

        runtime = build_ai_runtime_from_env(
            {
                "FISORA_AI_PROVIDER_CHAIN": "groq,openrouter,cerebras",
                "GROQ_API_KEY": "gsk-test",
                "OPENROUTER_API_KEY": "or-test",
                "CEREBRAS_API_KEY": "csk-test",
            }
        )

        canonical = runtime["canonical_extraction_provider"]
        routed = runtime["product_classifier"].provider
        self.assertEqual(canonical.provider_name, "cerebras>groq>openrouter")
        self.assertIsInstance(routed, TaskRoutingAccountingProvider)
        self.assertEqual(routed.classification_provider.provider_name, "groq>cerebras>openrouter")
        self.assertEqual(routed.counterparty_provider.provider_name, "cerebras>groq>openrouter")

        groq_only = build_ai_runtime_from_env(
            {"FISORA_AI_PROVIDER_CHAIN": "groq", "GROQ_API_KEY": "gsk-test"}
        )
        self.assertEqual(groq_only["canonical_extraction_provider"].provider_name, "groq")
        self.assertEqual(groq_only["product_classifier"].provider.classification_provider.provider_name, "groq")

    def test_task_router_uses_counterparty_chain_only_for_counterparty_stage(self) -> None:
        from types import SimpleNamespace

        from app.domain.openai_provider import TaskRoutingAccountingProvider

        calls: list[str] = []

        class Provider:
            def __init__(self, name: str) -> None:
                self.provider_name = name
                self.model = f"{name}-model"
                self.product_classification_instructions = f"{name}-prompt"

            def classify_product(self, request: object) -> dict[str, object]:
                calls.append(self.provider_name)
                return {"provider": self.provider_name}

        router = TaskRoutingAccountingProvider(
            classification_provider=Provider("classification"),
            counterparty_provider=Provider("counterparty"),
        )
        line_request = SimpleNamespace(context=SimpleNamespace(candidate_strategy=SimpleNamespace(stage="line_batch")))
        counterparty_request = SimpleNamespace(
            context=SimpleNamespace(candidate_strategy=SimpleNamespace(stage="counterparty_resolve"))
        )

        self.assertEqual(router.classify_product(line_request), {"provider": "classification"})
        self.assertEqual(router.classify_product(counterparty_request), {"provider": "counterparty"})
        self.assertEqual(calls, ["classification", "counterparty"])
        self.assertEqual(router.last_provider_name, "counterparty")

    def test_ai_classification_request_includes_controlled_activity_tags(self) -> None:
        request = AiClassificationRequest(
            raw_line="Bilinmeyen medikal sarf",
            supplier_hint="Tedarikci",
            allowed_categories=("medikal_sarf", "bilinmeyen"),
            max_input_chars=120,
            context=AiClassificationContext(
                client_activity="Belirli bir mala tahsis edilmis magazalarda satis",
                activity_tags=("hearing_aid", "medical_retail", "retail_trade"),
            ),
        )

        payload = request.to_schema_payload()

        self.assertEqual(payload["activity_tags"], ["hearing_aid", "medical_retail", "retail_trade"])
        self.assertNotIn("activity_tags", payload["output_schema"]["properties"])
        self.assertNotIn("raw_pdf", str(payload).lower())

    def test_statement_ai_request_schema_disallows_extra_properties_for_groq(self) -> None:
        request = StatementAiSuggestionRequest(
            line_no=1,
            transaction_date="2026-06-08",
            description="Sentetik Tedarikci A odeme",
            amount="500.00",
            direction="out",
            current_transaction_type="unknown",
            current_suggested_account_code="320.01.001",
            current_confidence=35,
            risk_flags=("statement_review_required",),
            review_reason="demo",
            max_input_chars=120,
        )

        schema = request.to_schema_payload()["output_schema"]

        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), set(schema["properties"].keys()))
        self.assertEqual(schema["properties"]["suggested_account_code"]["enum"], ["", "320.01.001"])
        self.assertEqual(schema["properties"]["reason"]["maxLength"], 500)

    def test_statement_ai_suggestions_only_call_provider_for_uncertain_statement_lines(self) -> None:
        provider = FakeStatementSuggestionProvider(
            [
                {
                    "transaction_type": "bank_transfer_out",
                    "suggested_account_code": "320.01.111",
                    "confidence": 74,
                    "reason": "Açıklama tedarikçi ödemesine benziyor.",
                    "evidence": ["odeme", "tedarikci"],
                },
                {
                    "transaction_type": "counterparty_payment",
                    "suggested_account_code": "320.01.222",
                    "confidence": 81,
                    "reason": "Düşük güvenli havale satırı cari ödemeye benziyor.",
                    "evidence": ["havale"],
                },
            ]
        )
        lines = (
            StatementLine(
                line_no=1,
                transaction_date="2026-06-01",
                description="GIB ODEME",
                amount="100.00",
                direction="out",
                suggested_account_code="360",
                transaction_type="tax_payment",
                confidence=86,
                risk_flags=(),
            ),
            StatementLine(
                line_no=2,
                transaction_date="2026-06-02",
                description="BILINMEYEN TEDARIKCI ODEME",
                amount="250.00",
                direction="out",
                transaction_type="unknown",
                confidence=35,
                risk_flags=("statement_review_required", "counterparty_not_found"),
            ),
            StatementLine(
                line_no=3,
                transaction_date="2026-06-03",
                description="GIDEN HAVALE",
                amount="400.00",
                direction="out",
                suggested_account_code="320",
                transaction_type="bank_transfer_out",
                confidence=68,
                risk_flags=("statement_review_required",),
            ),
        )

        batch = suggest_statement_lines(
            lines,
            provider=provider,
            policy=StatementAiSuggestionPolicy(enabled=True, confidence_threshold=70, max_provider_calls=5),
        )

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(batch.ai_used_count, 2)
        self.assertEqual([suggestion.line_no for suggestion in batch.suggestions], [2, 3])
        self.assertEqual(batch.suggestions[0].suggested_account_code, "320.01.111")
        self.assertFalse(batch.suggestions[0].export_allowed)
        self.assertEqual(batch.skipped_count, 1)

    def test_statement_ai_suggestions_fall_back_when_provider_raises(self) -> None:
        class RaisingStatementProvider:
            provider_name = "raising_statement_llm"

            def __init__(self) -> None:
                self.requests: list[object] = []

            def suggest_statement_line(self, request: object) -> dict[str, object]:
                self.requests.append(request)
                raise RuntimeError("statement provider unavailable")

        provider = RaisingStatementProvider()
        line = StatementLine(
            line_no=1,
            transaction_date="2026-06-02",
            description="BILINMEYEN TEDARIKCI ODEME",
            amount="250.00",
            direction="out",
            transaction_type="unknown",
            confidence=35,
            risk_flags=("statement_review_required",),
        )

        batch = suggest_statement_lines(
            (line,),
            provider=provider,
            policy=StatementAiSuggestionPolicy(enabled=True, confidence_threshold=70, max_provider_calls=5),
        )

        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(batch.ai_used_count, 0)
        self.assertEqual(batch.invalid_schema_count, 0)
        self.assertEqual(len(batch.suggestions), 1)
        self.assertEqual(batch.suggestions[0].provider, "raising_statement_llm")
        self.assertEqual(batch.suggestions[0].skipped_reason, "ai_provider_error")
        self.assertIn("ai_provider_error", batch.suggestions[0].risk_flags)
        self.assertFalse(batch.suggestions[0].export_allowed)

    def test_invoice_line_extraction_keeps_brand_model_rows(self) -> None:
        text = """
        Fatura No: ABC2026000000001
        Rexton RLi 20 12.000,00
        Urban Care sac bakim seti 450,00
        Odenecek Tutar 12.450,00
        """

        lines = extract_invoice_lines_from_text(text)

        descriptions = [line.description for line in lines]
        self.assertIn("Rexton RLi 20", descriptions)
        self.assertIn("Urban Care sac bakim seti", descriptions)

    def test_matching_simulation_records_ai_classification_metadata(self) -> None:
        invoice = ParsedInvoice(
            file_name="unknown-device.pdf",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("ZX Sonic Pro 9 receiver unit",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider(
                {
                    "category": "isitme_cihazi",
                    "confidence": 84,
                    "reason": "Model odyoloji cihaz ailesine benziyor.",
                    "evidence": ["ai:model_family"],
                    "suggested_account_code": "770.01",
                    "suggested_counterparty_code": "320.01",
                    "risk_flags": ["accountant_review_required"],
                    "account_reason": "AI mevcut hesap adaylari icinden gider ve cari onerdi.",
                }
            ),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.ai_classification_provider, "fake_llm")
        self.assertEqual(result.product_category, "isitme_cihazi")
        self.assertEqual(result.business_relevance_status, "uygun")
        self.assertEqual(result.ai_suggested_account_code, "770.01")
        self.assertEqual(result.ai_suggested_counterparty_code, "320.01")
        self.assertEqual(result.ai_risk_flags, ("accountant_review_required",))
        self.assertIn("gider ve cari", result.ai_account_reason)
        self.assertEqual(result.export_status, "review_required")

    def test_ai_assisted_draft_mode_keeps_clean_draft_in_review(self) -> None:
        invoice = ParsedInvoice(
            file_name="rexton.pdf",
            provider_hint="Rexton Medikal",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=("1234567890",),
            vat_rates=("20",),
            goods_services_total="10000.00",
            vat_total="2000.00",
            special_tax_total="",
            tax_inclusive_total="12000.00",
            payable_total="12000.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        accounts = [
            ChartAccount("320.01.015", "320.01.015", "Rexton Medikal", is_detail_account=True, tax_id="1234567890"),
        ]
        counterparty = match_counterparty(accounts, tax_ids=invoice.tax_ids, name_hint=invoice.provider_hint)

        assisted = simulate_mechanical_invoice(invoice, selection, profile, counterparty, processing_mode="ai_assisted_draft")
        controlled = simulate_mechanical_invoice(invoice, selection, profile, counterparty, processing_mode="controlled_automation")

        self.assertEqual(assisted.processing_mode, "ai_assisted_draft")
        self.assertEqual(assisted.export_status, "review_required")
        self.assertEqual(assisted.simulated_status, "review_required")
        self.assertIn("ai_assisted_draft_requires_accountant_approval", assisted.review_reason_codes)
        self.assertIn("balanced_entry", assisted.deterministic_checks)
        self.assertIn("mustavir onayi olmadan export kapali", assisted.export_gate_reason)
        self.assertEqual(controlled.export_status, "export_ready")
        self.assertEqual(controlled.simulated_status, "auto_ready")

    def test_ai_assisted_draft_result_exposes_agentic_review_contract(self) -> None:
        invoice = ParsedInvoice(
            file_name="new-supplier.pdf",
            provider_hint="Yeni Tedarikci",
            page_count=1,
            text_extractable=True,
            extracted_char_count=900,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="YEN2026000000001",
            ettn="",
            issue_date="02.05.2026",
            tax_ids=("9999999999",),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Ofis sarf malzemesi",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        profile = ClientProfile(
            client_id="client-1",
            title="Demo Ofis",
            tax_id="1234567890",
            activity_description="Muhasebe ve ofis hizmetleri",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile, counterparty_match=None, processing_mode="ai_assisted_draft")

        self.assertGreater(result.draft_confidence, 0)
        self.assertEqual(result.automation_eligibility, "not_eligible")
        self.assertIn("counterparty_missing", result.review_blockers)
        self.assertIn("mustavir onayi", result.accountant_action_hint.lower())
        self.assertEqual(result.suggested_counterparty_creation["suggested_code"], "320.9999999999")
        self.assertEqual(result.primary_suggestion["direction"], "purchase")
        self.assertEqual(result.primary_suggestion["counterparty_account"], "320.9999999999")
        self.assertEqual(result.primary_suggestion["vat_account"], "191.01")
        self.assertTrue(result.primary_suggestion["draft_lines"])

    def test_counterparty_matching_prefers_tax_id_then_review_for_missing(self) -> None:
        accounts = [
            ChartAccount("320.01", "320.01", "Saticilar", is_detail_account=False),
            ChartAccount("320.01.015", "320.01.015", "Rexton Medikal", is_detail_account=True, tax_id="1234567890"),
        ]

        exact = match_counterparty(accounts, tax_ids=("1234567890",), name_hint="Bilinmeyen")
        missing = match_counterparty(accounts, tax_ids=("9999999999",), name_hint="Baska Firma")

        self.assertEqual(exact.account_code, "320.01.015")
        self.assertEqual(exact.match_reason, "tax_id_exact")
        self.assertFalse(exact.requires_review)
        self.assertEqual(missing.match_reason, "not_found")
        self.assertTrue(missing.requires_review)

    def test_review_decision_creates_learning_event_after_three_consistent_approvals(self) -> None:
        decision = ReviewDecision(
            document_ref="AF-0001",
            action="approve_with_changes",
            reviewer="mustavir",
            corrected_account_code="770.04",
            category="e_fatura_hizmeti",
            apply_to_similar=True,
        )

        event = build_learning_event(decision, prior_consistent_approval_count=2)

        self.assertEqual(event.scope, "client_rule")
        self.assertTrue(event.automation_candidate)

    def test_learning_rule_changes_next_similar_document_suggestion(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="kolaysoft-tekrar.pdf",
            provider_hint="Kolay Soft",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kolay Soft e-fatura hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        decision = ReviewDecision(
            document_ref="kolaysoft-ilk.pdf",
            action="approve_with_changes",
            reviewer="mustavir",
            corrected_account_code="770.05",
            category="e_fatura_hizmeti",
            reason="Bu mukellefte e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
            apply_to_similar=True,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_learning_event(build_learning_event(decision))])

        self.assertEqual(result.selected_expense_account, "770.01")
        self.assertEqual(learned.selected_expense_account, result.selected_expense_account)
        self.assertEqual(learned.draft_lines, result.draft_lines)
        self.assertFalse(learned.learning_rule_applied)
        self.assertEqual(learned.learning_rule_scope, "client_rule")
        self.assertEqual(learned.learning_audit["status"], "evidence_only")

    def test_general_learning_signal_does_not_override_ai_before_threshold(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=("Ataturk Cad. No:1",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="kolaysoft-tekrar.pdf",
            provider_hint="Kolay Soft",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kolay Soft e-fatura hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        decision = ReviewDecision(
            document_ref="kolaysoft-ilk.pdf",
            action="approve_with_changes",
            reviewer="mustavir",
            corrected_account_code="770.05",
            category="e_fatura_hizmeti",
            reason="Bu mukellefte e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
            apply_to_similar=False,
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_learning_event(build_learning_event(decision))])

        self.assertEqual(learned.selected_expense_account, result.selected_expense_account)
        self.assertFalse(learned.learning_rule_applied)

    def test_review_decision_records_accountant_final_decision_and_quality_delta(self) -> None:
        document = {
            "document_ref": "fatura-1",
            "export_status": "review_required",
            "result": {
                "selected_expense_account": "770.01",
                "selected_supplier_account": "320.NEW",
                "counterparty_match_code": "320.NEW",
                "selected_vat_account": "191.01",
                "accounting_direction": "purchase",
                "draft_lines": [
                    {"account_code": "770.01", "description": "Hizmet", "debit": "1000.00", "credit": "0.00"},
                    {"account_code": "191.01", "description": "KDV", "debit": "200.00", "credit": "0.00"},
                    {"account_code": "320.NEW", "description": "Satici", "debit": "0.00", "credit": "1200.00"},
                ],
                "is_balanced": True,
                "export_status": "review_required",
                "ai_quality_scorecard": {
                    "static": {"category": "bilinmeyen", "confidence": 35},
                    "ai": {"category": "e_fatura_hizmeti", "confidence": 72},
                    "final": {
                        "selected_account_code": "770.01",
                        "selected_counterparty_account": "320.NEW",
                        "direction": "purchase",
                    },
                },
            },
        }
        decision = {
            "document_ref": "fatura-1",
            "action": "approve_with_changes",
            "reviewer": "mustavir",
            "corrected_account_code": "153.01",
            "corrected_counterparty_code": "320.01.015",
            "reason": "Bu tedarikciden gelen cihazlar stoktur.",
        }

        updated = apply_review_decision_to_document(
            document,
            decision=decision,
            learning_event={
                "scope": "client_rule",
                "action": "approve_with_changes",
                "reason": "Bu tedarikciden gelen cihazlar stoktur.",
            },
            reviewed_at="2026-07-03T12:00:00Z",
        )
        result = updated["result"]

        self.assertEqual(result["proposal_snapshot"]["selected_account_code"], "770.01")
        self.assertEqual(result["accountant_final_decision"]["selected_account_code"], "153.01")
        self.assertEqual(result["accountant_final_decision"]["selected_counterparty_account"], "320.01.015")
        self.assertEqual(result["quality_delta"]["changed_fields"], ["selected_account_code", "counterparty_account"])
        self.assertEqual(result["quality_delta"]["account_changed_from"], "770.01")
        self.assertEqual(result["quality_delta"]["account_changed_to"], "153.01")
        self.assertTrue(result["quality_delta"]["learning_candidate"])

    def test_learning_event_enriches_accounting_intent_and_rule_prompt_after_three_consistent_decisions(self) -> None:
        base_event = {
            "document_ref": "kolaysoft-uc.pdf",
            "scope": "client_rule",
            "action": "approve_with_changes",
            "category": "e_fatura_hizmeti",
            "corrected_account_code": "770.05",
            "corrected_counterparty_code": "320.01.888",
            "reason": "Bu mukellefte Kolay Soft e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
            "automation_candidate": False,
            "statement_line_no": 0,
        }
        prior_events = [
            {
                **base_event,
                "document_ref": "kolaysoft-bir.pdf",
                "client_id": "client-1",
                "accounting_intent": "e_fatura_yazilim_gideri",
                "corrected_account_code": "770.05",
                "corrected_counterparty_code": "320.01.888",
            },
            {
                **base_event,
                "document_ref": "kolaysoft-iki.pdf",
                "client_id": "client-1",
                "accounting_intent": "e_fatura_yazilim_gideri",
                "corrected_account_code": "770.05",
                "corrected_counterparty_code": "320.01.888",
            },
        ]
        document = {
            "document_ref": "kolaysoft-uc.pdf",
            "result": {
                "invoice_type": "ALIS",
                "provider_hint": "Kolay Soft",
                "product_line_hint": "Kolay Soft e-fatura hizmeti",
                "product_category": "bilinmeyen",
            },
        }

        enriched = enrich_learning_event(
            base_event,
            client_id="client-1",
            decision=base_event,
            document=document,
            prior_learning_events=prior_events,
            policy=LearningPolicy(client_rule_threshold=3, office_client_threshold=3, office_decision_threshold=5),
        )

        self.assertEqual(enriched["accounting_intent"], "e_fatura_yazilim_gideri")
        self.assertEqual(enriched["client_consistent_decision_count"], 3)
        self.assertEqual(enriched["rule_prompt"]["show"], True)
        self.assertEqual(enriched["rule_prompt"]["default_scope"], "client_narrow")
        self.assertIn("kolay", enriched["normalized_terms"])

    def test_learning_event_uses_approved_draft_account_with_nace_vat_signature(self) -> None:
        event = {
            "document_ref": "rexton-onay.xml",
            "scope": "general_candidate",
            "action": "approve",
            "category": "isitme_cihazi",
            "corrected_account_code": "",
            "corrected_counterparty_code": "",
            "reason": "Taslak musavir tarafindan dogru bulundu.",
            "automation_candidate": False,
            "statement_line_no": 0,
        }
        document = {
            "document_ref": "rexton-onay.xml",
            "result": {
                "invoice_type": "ALIS",
                "provider_hint": "Medikal Tedarik",
                "product_line_hint": "Rexton RLi 20 isitme cihazi",
                "product_category": "isitme_cihazi",
                "vat_rates": ["20"],
                "selected_expense_account": "153.01.001",
                "selected_supplier_account": "320.01",
                "accounting_direction": "purchase",
            },
        }

        enriched = enrich_learning_event(
            event,
            client_id="client-1",
            decision=event,
            document=document,
            client_profile={
                "nace_code": "47.74.01",
                "activity_tags": ["hearing_aid", "medical_retail"],
            },
        )

        self.assertEqual(enriched["corrected_account_code"], "153.01.001")
        self.assertEqual(enriched["corrected_counterparty_code"], "320.01")
        self.assertEqual(enriched["nace_code"], "477401")
        self.assertEqual(enriched["vat_rates"], ["20"])
        self.assertEqual(enriched["activity_tags"], ["hearing_aid", "medical_retail"])
        self.assertEqual(
            enriched["posting_signature"],
            "nace:477401|category:isitme_cihazi|vat:20|account:153|counterparty:320",
        )

    def test_direct_rule_request_opens_client_rule_prompt_without_threshold(self) -> None:
        event = {
            "document_ref": "kolaysoft-tek.pdf",
            "scope": "client_rule",
            "action": "suggest_for_similar",
            "category": "e_fatura_hizmeti",
            "corrected_account_code": "770.05",
            "corrected_counterparty_code": "",
            "reason": "KolaySoft e-fatura hizmetini bu mukellefte 770.05 alt hesabina al.",
            "automation_candidate": False,
            "statement_line_no": 0,
        }

        enriched = enrich_learning_event(event, client_id="client-1", decision=event, prior_learning_events=())

        self.assertEqual(enriched["client_consistent_decision_count"], 1)
        self.assertEqual(enriched["rule_prompt"]["show"], True)
        self.assertEqual(enriched["rule_prompt"]["status"], "client_rule_prompt")
        self.assertEqual(enriched["rule_prompt"]["default_scope"], "client_narrow")

    def test_learning_rule_matches_next_invoice_by_intent_and_terms_without_opening_export(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            workplace_addresses=(),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="kolaysoft-tekrar.pdf",
            provider_hint="Kolay Soft",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kolay Soft e-fatura hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        event = {
            "client_id": "client-1",
            "scope": "client_rule",
            "action": "approve_with_changes",
            "category": "baska_kategori",
            "corrected_account_code": "770.05",
            "corrected_counterparty_code": "",
            "reason": "Kolay Soft e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
            "accounting_intent": "e_fatura_yazilim_gideri",
            "normalized_terms": ["kolay", "soft", "e", "fatura", "hizmeti"],
            "automation_candidate": False,
            "rule_prompt": {"show": True, "default_scope": "client_narrow"},
        }

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertEqual(learned.selected_expense_account, result.selected_expense_account)
        self.assertEqual(learned.draft_lines, result.draft_lines)
        self.assertFalse(learned.learning_rule_applied)
        self.assertEqual(learned.export_status, result.export_status)
        self.assertIn("Kolay Soft", learned.learning_rule_reason)

    def test_learning_rule_matches_next_invoice_by_nace_vat_and_account_family(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1234567890",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail"),
            workplace_addresses=(),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="isitme-cihazi-tekrar.xml",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000002",
            ettn="",
            issue_date="02.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Acme receiver unit",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="153.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            stock_account="153.01",
            selection_notes=(),
        )
        event = {
            "client_id": "client-1",
            "scope": "client_rule",
            "action": "approve",
            "category": "baska_kategori",
            "corrected_account_code": "153.01.001",
            "corrected_counterparty_code": "320.01",
            "reason": "Ayni NACE ve yuzde 20 KDV kapsaminda cihaz alimlari stokta izleniyor.",
            "nace_code": "477401",
            "activity_tags": ["hearing_aid"],
            "vat_rates": ["20"],
            "posting_signature": "nace:477401|category:isitme_cihazi|vat:20|account:153|counterparty:320",
            "automation_candidate": False,
            "rule_prompt": {"show": True, "default_scope": "client_narrow"},
        }

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertEqual(result.selected_expense_account, "153.01")
        self.assertEqual(learned.selected_expense_account, result.selected_expense_account)
        self.assertEqual(learned.selected_supplier_account, "320.01")
        self.assertFalse(learned.learning_rule_applied)
        self.assertEqual(learned.draft_lines, result.draft_lines)

    def test_counterparty_scoped_learning_rule_does_not_apply_to_different_supplier(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1111111111",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="baska-tedarikci.xml",
            provider_hint="Baska Tedarikci",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000003",
            ettn="",
            issue_date="03.05.2026",
            tax_ids=("7777777777", "1111111111"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20 isitme cihazi",),
            issuer_title="Baska Tedarikci",
            issuer_tax_id="7777777777",
            recipient_title="Isitme Merkezi A",
            recipient_tax_id="1111111111",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="153.01",
            purchase_vat_account="191.01",
            supplier_account="320.01.020",
            bank_account="102.01",
            stock_account="153.01",
            selection_notes=(),
        )
        event = {
            "client_id": "client-1",
            "scope": "client_rule",
            "action": "suggest_for_similar",
            "category": "isitme_cihazi",
            "corrected_account_code": "153.01.001",
            "corrected_counterparty_code": "320.01.015",
            "reason": "Medikal Tedarik bu mukellefin stok tedarikcisidir.",
            "nace_code": "477401",
            "activity_tags": ["hearing_aid"],
            "vat_rates": ["20"],
            "counterparty_tax_id": "8888888888",
            "counterparty_title": "Medikal Tedarik",
            "counterparty_identity_key": "purchase|tax:8888888888",
            "automation_candidate": True,
        }

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            CounterpartyMatch("320.01.020", "Baska Tedarikci", 98, "tax_id_exact", False),
        )
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertFalse(learned.learning_rule_applied)
        self.assertEqual(learned.selected_expense_account, "153.01")
        self.assertEqual(learned.selected_supplier_account, "320.01.020")
        self.assertEqual(learned.export_status, result.export_status)

    def test_counterparty_scoped_explicit_rule_can_keep_clean_invoice_export_ready(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Isitme Merkezi A",
            tax_id="1111111111",
            activity_description="Isitme cihazi satis ve uygulama merkezi",
            nace_code="477401",
            activity_tags=("hearing_aid", "medical_retail"),
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="medikal-tekrar.xml",
            provider_hint="Medikal Tedarik",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000004",
            ettn="",
            issue_date="04.05.2026",
            tax_ids=("8888888888", "1111111111"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Rexton RLi 20 isitme cihazi",),
            issuer_title="Medikal Tedarik",
            issuer_tax_id="8888888888",
            recipient_title="Isitme Merkezi A",
            recipient_tax_id="1111111111",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="153.01",
            purchase_vat_account="191.01",
            supplier_account="320.01.015",
            bank_account="102.01",
            stock_account="153.01",
            selection_notes=(),
        )
        event = {
            "client_id": "client-1",
            "scope": "client_rule",
            "action": "suggest_for_similar",
            "category": "isitme_cihazi",
            "corrected_account_code": "153.01.001",
            "corrected_counterparty_code": "320.01.015",
            "reason": "Medikal Tedarik bu mukellefin stok tedarikcisidir.",
            "nace_code": "477401",
            "activity_tags": ["hearing_aid"],
            "vat_rates": ["20"],
            "counterparty_tax_id": "8888888888",
            "counterparty_title": "Medikal Tedarik",
            "counterparty_identity_key": "purchase|tax:8888888888",
            "automation_candidate": True,
        }

        result = simulate_mechanical_invoice(
            invoice,
            selection,
            profile,
            CounterpartyMatch("320.01.015", "Medikal Tedarik", 98, "tax_id_exact", False),
        )
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertEqual(result.export_status, "export_ready")
        self.assertEqual(learned.selected_expense_account, result.selected_expense_account)
        self.assertEqual(learned.selected_supplier_account, "320.01.015")
        self.assertEqual(learned.export_status, "export_ready")
        self.assertNotIn("learning_rule_review_required", learned.review_reason_codes)

    def test_accountant_note_creates_global_product_phrase_rule_candidate(self) -> None:
        candidate = build_natural_language_rule_candidate(
            accountant_note="Rexton RLi 20 isitme cihazidir, stok olarak 153.01 alt hesabinda izleyelim.",
            rule_instruction="Benzer Rexton RLi 20 satirlarinda bunu oner.",
            product_line_hint="Rexton RLi 20",
            category="",
            corrected_account_code="153.01",
        )

        self.assertEqual(candidate["scope"], "global_product_phrase")
        self.assertEqual(candidate["match_phrase"], "rexton rli 20")
        self.assertEqual(candidate["product_category"], "isitme_cihazi")
        self.assertEqual(candidate["account_treatment"], "stock_or_cogs")
        self.assertEqual(candidate["suggested_account_code"], "153.01")
        self.assertTrue(candidate["requires_review"])

    def test_office_general_note_creates_semantic_rule_without_account_code(self) -> None:
        candidate = build_natural_language_rule_candidate(
            accountant_note="Ofis geneli bu cariden gelenler dogalgaz gideridir.",
            rule_instruction="Tum mukelleflerde dogalgaz olarak yorumla.",
            product_line_hint="Dogalgaz tuketim bedeli",
            category="",
            corrected_account_code="770.03",
        )

        self.assertEqual(candidate["scope"], "office_semantic")
        self.assertEqual(candidate["semantic_accounting_intent"], "dogalgaz_gideri")
        self.assertEqual(candidate["suggested_account_code"], "")
        self.assertTrue(candidate["requires_review"])

    def test_office_semantic_learning_rule_does_not_copy_account_code_to_other_client(self) -> None:
        profile = ClientProfile(
            client_id="client-2",
            title="Baska Mukellef",
            tax_id="2222222222",
            activity_description="Perakende ticaret",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="dogalgaz-tekrar.pdf",
            provider_hint="IGDAS",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000005",
            ettn="",
            issue_date="05.05.2026",
            tax_ids=("1111111111", "2222222222"),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Dogalgaz tuketim bedeli",),
            issuer_title="IGDAS",
            issuer_tax_id="1111111111",
            recipient_title="Baska Mukellef",
            recipient_tax_id="2222222222",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        event = {
            "client_id": "client-1",
            "scope": "office_policy",
            "action": "suggest_for_similar",
            "category": "dogalgaz_gideri",
            "corrected_account_code": "770.03",
            "corrected_counterparty_code": "",
            "reason": "Ofis geneli dogalgaz gideri olarak yorumlansin.",
            "accounting_intent": "dogalgaz_gideri",
            "accounting_intent_confidence": 88,
            "normalized_terms": ["dogalgaz", "tuketim", "bedeli"],
            "automation_candidate": True,
            "natural_language_rule_candidate": {
                "scope": "office_semantic",
                "match_phrase": "dogalgaz tuketim bedeli",
                "product_category": "dogalgaz_gideri",
                "account_treatment": "expense",
                "semantic_accounting_intent": "dogalgaz_gideri",
                "suggested_account_code": "",
                "requires_review": True,
                "reason": "Ofis geneli anlam bilgisi.",
            },
            "learning_rule_source_summary": "Benzer satirlar dogalgaz gideri olarak isaretlenmis.",
        }

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertTrue(learned.learning_rule_applied)
        self.assertEqual(learned.selected_expense_account, "770.01")
        self.assertEqual(learned.accounting_intent, "dogalgaz_gideri")
        self.assertIn("dogalgaz", learned.learning_rule_source_summary.lower())

    def test_learning_rule_application_adds_debug_audit_payload(self) -> None:
        profile = ClientProfile(
            client_id="client-1",
            title="Pilot Mukellef",
            tax_id="2222222222",
            activity_description="Lojistik hizmetleri",
            workplace_addresses=("Istanbul",),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="kargo-tekrar.pdf",
            provider_hint="Yurtici Kargo",
            page_count=1,
            text_extractable=True,
            extracted_char_count=800,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000006",
            ettn="",
            issue_date="06.05.2026",
            tax_ids=("9860008925", "2222222222"),
            vat_rates=("20",),
            goods_services_total="100.00",
            vat_total="20.00",
            special_tax_total="",
            tax_inclusive_total="120.00",
            payable_total="120.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kargo hizmet bedeli",),
            issuer_title="Yurtici Kargo",
            issuer_tax_id="9860008925",
            recipient_title="Pilot Mukellef",
            recipient_tax_id="2222222222",
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )
        event = {
            "client_id": "client-1",
            "scope": "client_rule",
            "action": "suggest_for_similar",
            "category": "kargo",
            "corrected_account_code": "760.03.010",
            "corrected_counterparty_code": "320.9860008925",
            "reason": "Yurtici Kargo kargo gideri olarak izlenir.",
            "accounting_intent": "kargo_gideri",
            "accounting_intent_confidence": 90,
            "normalized_terms": ["yurtici", "kargo", "hizmet"],
            "counterparty_tax_id": "9860008925",
            "counterparty_title": "Yurtici Kargo",
            "automation_candidate": True,
            "learning_rule_source_summary": "Yurtici Kargo onceki musavir kararindan eslesti.",
        }

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertFalse(learned.learning_rule_applied)
        audit = learned.learning_audit
        self.assertEqual(audit["status"], "evidence_only")
        self.assertEqual(audit["scope"], "client_rule")
        self.assertEqual(audit["suggested_account_code"], "760.03.010")
        self.assertGreaterEqual(audit["match_score"], 60)
        self.assertIn("kargo", audit["matched_terms"])

    def test_accountant_note_creates_client_counterparty_rule_candidate_for_wholesaler(self) -> None:
        candidate = build_natural_language_rule_candidate(
            accountant_note="Bu cari bunun toptancisi, buradan bize kesilen tum faturalar stok alimidir.",
            rule_instruction="Bu tedarikciden gelen faturalari bu mukellefte stok alimi olarak uygula.",
            product_line_hint="Algida gida toptancisi",
            category="gida_alimi",
            corrected_account_code="153.03",
        )

        self.assertEqual(candidate["scope"], "client_counterparty")
        self.assertEqual(candidate["account_treatment"], "stock_or_cogs")
        self.assertEqual(candidate["suggested_account_code"], "153.03")
        self.assertTrue(candidate["requires_review"])

    def test_enriched_natural_language_candidate_uses_selected_account_when_decision_account_is_blank(self) -> None:
        event = {
            "document_ref": "kargo.xml",
            "scope": "general_candidate",
            "action": "approve_with_changes",
            "category": "kargo",
            "corrected_account_code": "",
            "corrected_counterparty_code": "",
            "reason": "Kargo gideri olarak kaydettim.",
            "accountant_note": "Bundan sonra bu vergi numarasi ile gelen faturalari kargo gideri olarak isle.",
            "rule_instruction": "Bundan sonra bu vergi numarasi ile gelen faturalari kargo gideri olarak isle.",
            "automation_candidate": False,
        }
        decision = {
            "document_ref": "kargo.xml",
            "action": "approve_with_changes",
            "reviewer": "mali-musavir",
            "corrected_account_code": "",
            "corrected_counterparty_code": "",
            "category": "kargo",
            "reason": "Kargo gideri olarak kaydettim.",
            "accountant_note": "Bundan sonra bu vergi numarasi ile gelen faturalari kargo gideri olarak isle.",
            "rule_instruction": "Bundan sonra bu vergi numarasi ile gelen faturalari kargo gideri olarak isle.",
        }
        enriched = enrich_learning_event(
            event,
            client_id="client-1",
            decision=decision,
            document={
                "result": {
                    "accounting_direction": "purchase",
                    "selected_expense_account": "760.03.010",
                    "selected_supplier_account": "320.9860008925",
                    "counterparty_tax_id": "9860008925",
                    "counterparty_title": "Yurtici Kargo Servisi A.S.",
                    "product_line_hint": "Posta Hizmet Geliri",
                    "product_category": "kargo",
                }
            },
            prior_learning_events=(),
        )

        candidate = enriched["natural_language_rule_candidate"]
        self.assertEqual(enriched["corrected_account_code"], "760.03.010")
        self.assertEqual(candidate["suggested_account_code"], "760.03.010")
        self.assertEqual(candidate["scope"], "client_counterparty")

    def test_vague_accountant_note_does_not_create_active_learning_rule(self) -> None:
        event = {
            "client_id": "client-1",
            "scope": "client_rule",
            "action": "approve_with_changes",
            "category": "bilinmeyen",
            "corrected_account_code": "770.05",
            "corrected_counterparty_code": "",
            "reason": "bunu boyle yap",
            "accounting_intent": "genel_muhasebe_notu",
            "normalized_terms": ["bunu", "boyle"],
            "automation_candidate": False,
            "natural_language_rule_candidate": {
                "scope": "client_only",
                "match_phrase": "",
                "requires_review": True,
                "reason": "Not kural icin fazla muglak.",
            },
        }
        profile = ClientProfile(
            client_id="client-1",
            title="Demo A",
            tax_id="1234567890",
            activity_description="Genel perakende",
            workplace_addresses=(),
            has_chart_accounts=True,
        )
        invoice = ParsedInvoice(
            file_name="kolaysoft-tekrar.pdf",
            provider_hint="Kolay Soft",
            page_count=1,
            text_extractable=True,
            extracted_char_count=1200,
            scenario="TEMELFATURA",
            invoice_type="ALIS",
            invoice_no="ABC2026000000001",
            ettn="",
            issue_date="01.05.2026",
            tax_ids=(),
            vat_rates=("20",),
            goods_services_total="1000.00",
            vat_total="200.00",
            special_tax_total="1200.00",
            tax_inclusive_total="1200.00",
            payable_total="1200.00",
            risk_flags=(),
            suggested_route="journal_candidate",
            parse_notes=(),
            line_items=("Kolay Soft e-fatura hizmeti",),
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_mechanical_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertFalse(learned.learning_rule_applied)
        self.assertEqual(learned.selected_expense_account, result.selected_expense_account)

    def test_export_package_excludes_risky_or_review_required_entries(self) -> None:
        ready = build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="ready.pdf",
        )
        risky = build_purchase_entry(
            entry_date="2026-05-02",
            total=money("600.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="risky.pdf",
        )

        package = build_export_package(
            [
                ExportCandidate("ready.pdf", "export_ready", ready),
                ExportCandidate("risky.pdf", "review_required", risky, risk_flags=("counterparty_not_found",)),
            ]
        )

        self.assertEqual(len(package.entries), 1)
        self.assertEqual(package.entries[0].description, "Alis faturasi ready.pdf")
        self.assertEqual(package.excluded_document_refs, ("risky.pdf",))
        self.assertEqual(
            package.excluded_documents,
            (
                {
                    "document_ref": "risky.pdf",
                    "export_status": "review_required",
                    "review_blockers": ["counterparty_not_found"],
                },
            ),
        )

    def test_export_adapter_writes_json_manifest_and_rejects_unknown_type(self) -> None:
        entry = build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            document_ref="ready.pdf",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manifest.json"
            adapter = get_export_adapter("json_manifest")

            written = write_export_file(
                adapter=adapter,
                entries=(entry,),
                output_path=output_path,
                client_id="client-1",
            )
            text = written.read_text(encoding="utf-8")

        self.assertTrue(written.name.endswith(".json"))
        self.assertIn('"export_type": "json_manifest"', text)
        self.assertIn('"document_ref": "ready.pdf"', text)
        with self.assertRaises(ValueError):
            get_export_adapter("zirve_verified_format")

    def test_zirve_trial_csv_adapter_writes_field_mapping_candidate(self) -> None:
        entry = build_bank_payment_entry(
            entry_date="2026-05-03",
            amount=money("500.00"),
            bank_account="102.01",
            counterparty_account="360",
            counterparty_tax_id="1111111111",
            document_ref="BNK-0001",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = export_zirve_trial_csv([entry], Path(temp_dir) / "zirve-trial.csv")
            adapter = get_export_adapter("zirve_trial_csv")
            text = output.read_text(encoding="utf-8-sig")

        self.assertEqual(adapter.validation_status, "field_test_pending")
        self.assertFalse(adapter.verified_in_zirve)
        self.assertIn("fis_tarihi;fis_turu;fis_aciklama", text)
        self.assertIn("2026-05-03;BANKA", text)
        self.assertIn("360;Cari odeme;500.00;0.00;BNK-0001;1111111111", text)

    def test_zirve_mapping_csv_adapter_writes_minimum_manual_mapping_fields(self) -> None:
        entry = build_bank_payment_entry(
            entry_date="2026-05-03",
            amount=money("500.00"),
            bank_account="102.01",
            counterparty_account="360",
            counterparty_tax_id="1111111111",
            document_ref="BNK-0001",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = get_export_adapter("zirve_mapping_csv")
            output = write_export_file(
                adapter=adapter,
                entries=(entry,),
                output_path=Path(temp_dir) / "zirve-mapping.csv",
                client_id="client-1",
            )
            raw = output.read_bytes()
            text = output.read_text(encoding="utf-8-sig")

        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(adapter.validation_status, "field_test_pending")
        self.assertFalse(adapter.verified_in_zirve)
        self.assertEqual(text.splitlines()[0], ";".join(ZIRVE_MAPPING_COLUMNS))
        self.assertIn(
            "hesap_kodu;evrak_tarihi;evrak_no;belge_turu;aciklama;borc;alacak;vkn_tckn;odeme_sekli;fis_turu;satir_no;kaynak_belge",
            text,
        )
        self.assertIn("360;2026-05-03;BNK-0001;BANKA;Cari odeme;500.00;0.00;1111111111;;BANKA;1;BNK-0001", text)

    def test_workspace_export_package_includes_only_ready_balanced_entries(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "ready.pdf",
                    "export_status": "export_ready",
                    "result": {
                        "file_name": "ready.pdf",
                        "issue_date": "2026-05-01",
                        "draft_entry_type": "purchase",
                        "review_reason_codes": [],
                        "risk_flags": [],
                        "draft_lines": [
                            {"account_code": "770.01", "description": "Gider", "debit": "100.00", "credit": "0.00"},
                            {"account_code": "320.01", "description": "Satici", "debit": "0.00", "credit": "100.00"},
                        ],
                    },
                },
                {
                    "document_ref": "statement.csv",
                    "export_status": "export_ready",
                    "result": {
                        "export_status": "export_ready",
                        "accountant_export_override": True,
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "GIB ODEME",
                                "statement_line_no": 1,
                                "statement_fingerprint": "statement-ready-1",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                            {
                                "entry_type": "bank_collection",
                                "entry_date": "2026-05-03",
                                "description": "POS BLOKE",
                                "statement_line_no": 2,
                                "statement_fingerprint": "statement-pos-2",
                                "risk_flags": ["pos_policy_review_required"],
                                "lines": [
                                    {"account_code": "102.01", "description": "Banka girisi", "debit": "80.00", "credit": "0.00"},
                                    {"account_code": "108", "description": "pos_blocked", "debit": "0.00", "credit": "80.00"},
                                ],
                            },
                        ]
                    },
                },
            ]
        }

        build = build_workspace_export_package(workspace)

        self.assertEqual(build.candidate_count, 3)
        self.assertEqual(len(build.package.entries), 2)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-2",))
        self.assertEqual(build.package.excluded_documents[0]["review_blockers"], ["pos_policy_review_required"])

    def test_workspace_export_package_blocks_statement_entries_until_accountant_approval(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "export_status": "export_ready",
                    "result": {
                        "export_status": "export_ready",
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "GIB ODEME",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                        ],
                    },
                },
            ]
        }

        build = build_workspace_export_package(workspace)

        self.assertEqual(build.candidate_count, 1)
        self.assertEqual(len(build.package.entries), 0)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-1",))

    def test_workspace_export_package_blocks_duplicate_approved_statement_entry(self) -> None:
        entry_payload = {
            "entry_type": "bank_payment",
            "entry_date": "2026-05-02",
            "description": "GIB ODEME",
            "accountant_review_status": "approved",
            "statement_fingerprint": "2026-05-02|out|50.00|gib-odeme",
            "risk_flags": [],
            "lines": [
                {"account_code": "360", "description": "tax_payment", "debit": "50.00", "credit": "0.00"},
                {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
            ],
        }
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "result": {
                        "statement_entries": [
                            {**entry_payload, "statement_line_no": 1},
                            {**entry_payload, "statement_line_no": 2},
                        ]
                    },
                },
            ]
        }

        candidates = export_candidates_from_workspace(workspace)
        build = build_workspace_export_package(workspace)

        self.assertEqual(candidates[0].export_status, "export_ready")
        self.assertEqual(candidates[1].export_status, "review_required")
        self.assertIn("duplicate_statement_line", candidates[1].risk_flags)
        self.assertEqual(len(build.package.entries), 1)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-2",))

    def test_workspace_export_package_blocks_statement_entry_without_bank_account(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "result": {
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "Eksik banka satiri",
                                "accountant_review_status": "approved",
                                "statement_fingerprint": "2026-05-02|out|50.00|eksik",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "320.01", "description": "Cari", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "320.02", "description": "Cari", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                        ]
                    },
                },
            ]
        }

        candidate = export_candidates_from_workspace(workspace)[0]

        self.assertEqual(candidate.export_status, "review_required")
        self.assertIn("bank_account_missing", candidate.risk_flags)

    def test_workspace_export_package_marks_rejected_statement_entry_as_export_excluded(self) -> None:
        workspace = {
            "documents": [
                {
                    "document_ref": "statement.csv",
                    "result": {
                        "statement_entries": [
                            {
                                "entry_type": "bank_payment",
                                "entry_date": "2026-05-02",
                                "description": "Export disi banka satiri",
                                "accountant_review_status": "rejected",
                                "statement_fingerprint": "2026-05-02|out|50.00|rejected",
                                "risk_flags": [],
                                "lines": [
                                    {"account_code": "320.01", "description": "Cari", "debit": "50.00", "credit": "0.00"},
                                    {"account_code": "102.01", "description": "Banka cikisi", "debit": "0.00", "credit": "50.00"},
                                ],
                            },
                        ]
                    },
                },
            ]
        }

        candidates = export_candidates_from_workspace(workspace)
        build = build_workspace_export_package(workspace)

        self.assertEqual(candidates[0].export_status, "rejected")
        self.assertEqual(len(build.package.entries), 0)
        self.assertEqual(build.package.excluded_document_refs, ("statement.csv#statement-1",))

    def test_ai_batch_benchmark_scores_static_and_replay_provider_results(self) -> None:
        static_summary = run_ai_batch_benchmark(
            (
                AiBenchmarkCase("1", "Rexton RLi 20", "Rexton", "isitme_cihazi"),
                AiBenchmarkCase("2", "Urban Care sac bakim", "", "kisisel_bakim_kozmetik"),
            )
        )
        provider_summary = run_ai_batch_benchmark(
            (AiBenchmarkCase("3", "ZX Sonic Pro 9", "Medikal", "isitme_cihazi"),),
            policy=AiClassificationPolicy(enabled=True),
            provider_name="replay_openai",
            provider_payloads=[
                {
                    "category": "isitme_cihazi",
                    "confidence": 82,
                    "reason": "Model isitme cihazi ailesine benziyor.",
                    "evidence": ["benchmark"],
                }
            ],
        )

        self.assertEqual(static_summary.accuracy_percent, 100)
        self.assertEqual(static_summary.ai_used_count, 0)
        self.assertEqual(provider_summary.provider, "replay_openai")
        self.assertEqual(provider_summary.ai_used_count, 1)
        self.assertEqual(provider_summary.accuracy_percent, 100)

    def test_ai_batch_benchmark_uses_default_demo_cases_when_empty(self) -> None:
        summary = run_ai_batch_benchmark(())

        self.assertGreaterEqual(summary.case_count, 8)
        self.assertEqual(summary.ai_used_count, 0)
        self.assertEqual(summary.accuracy_percent, 100)
        self.assertIn("Urban Care", " ".join(result.raw_line for result in summary.results))


if __name__ == "__main__":
    unittest.main()
