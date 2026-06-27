from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.chart_accounts import (
    extract_counterparty_candidates,
    normalize_account_code,
    parse_chart_accounts,
    validate_vat_accounts,
)
from app.domain.ai_benchmark import AiBenchmarkCase, run_ai_batch_benchmark
from app.domain.ai_classification import AiClassificationContext, AiClassificationPolicy, AiClassificationRequest, StaticFirstClassifier
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
    assess_business_relevance,
    check_client_onboarding,
    decide_export_status,
)
from app.domain.chart_accounts import ChartAccount
from app.domain.counterparty_matching import match_counterparty
from app.domain.export_adapters import get_export_adapter, write_export_file
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.exporters import export_universal_journal_csv, export_zirve_trial_csv
from app.domain.invoice_lines import InvoiceLine, extract_invoice_lines_from_text
from app.domain.invoice_edge_cases import summarize_invoice_edge_cases
from app.domain.invoice_operations import (
    ReviewTaskDraft,
    run_invoice_operations,
    vat_rate_decimal,
)
from app.domain.learning_intelligence import LearningPolicy, enrich_learning_event
from app.domain.learning_rules import apply_learning_rules, rule_from_event_payload, rule_from_learning_event
from app.domain.matching_simulation import AccountSelection, SimulatedChartRun, private_benchmark_summary, simulate_chart_run, simulate_invoice
from app.domain.matching_simulation import build_review_ui_payload, write_simulation_csv
from app.domain.matching_simulation import select_accounts
from app.domain.journal_entries import (
    build_bank_payment_entry,
    build_mixed_vat_purchase_entry,
    build_purchase_entry,
    build_sales_entry,
    money,
)
from app.domain.pdf_invoices import ParsedInvoice, build_route, extract_vat_rates, parse_amount, parse_pdf_invoice, resolve_payable_total
from app.domain.production_readiness import production_readiness_payload
from app.domain.review_learning import ReviewDecision, build_learning_event
from app.domain.statement_ai_suggestions import StatementAiSuggestionPolicy, StatementAiSuggestionRequest, suggest_statement_lines
from app.domain.statement_lines import StatementLine
from app.domain.vat_split_learning import build_vat_split_review_record, vat_split_review_payload
from app.domain.workspace_exports import build_workspace_export_package, export_candidates_from_workspace


class FakeProductProvider:
    provider_name = "fake_llm"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.requests: list[AiClassificationRequest] = []

    def classify_product(self, request: AiClassificationRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.response


class FakeStatementSuggestionProvider:
    provider_name = "fake_statement_llm"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def suggest_statement_line(self, request: object) -> dict[str, object]:
        self.requests.append(request)
        return self.responses.pop(0)


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

    def test_production_readiness_requires_openai_key_when_openai_enabled(self) -> None:
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
                },
            )

        self.assertTrue(payload["pilot_sellable"])
        self.assertFalse(payload["real_data_pilot"]["allowed"])
        self.assertIn("session_required_active", payload["real_data_pilot"]["blocking"])

    def test_real_data_pilot_allows_restricted_session_backed_live_flow(self) -> None:
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
                    "FISORA_AUTH_MODE": "session_required",
                    "FISORA_SESSION_COOKIE_SECURE": "true",
                    "FISORA_STORE_BACKEND": "postgres",
                    "DATABASE_URL": "postgresql://fisora:test@localhost:5432/fisora",
                    "FISORA_AI_PROVIDER": "groq",
                    "GROQ_API_KEY": "gsk-test",
                    "FISORA_REAL_DATA_PILOT_ENABLED": "true",
                    "FISORA_REAL_DATA_ACCESS_MODE": "restricted_network",
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

    def test_mixed_vat_purchase_entry_is_balanced_and_flagged(self) -> None:
        entry = build_mixed_vat_purchase_entry(
            entry_date="2026-05-04",
            items=(("770.01", money("108.00"), Decimal("0.08")), ("770.02", money("120.00"), Decimal("0.20"))),
        )

        self.assertTrue(entry.is_balanced)
        self.assertIn("mixed_vat_manual_review", entry.risk_flags)

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
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_invoice(invoice, selection)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_quality, "gross_balanced_needs_vat_split")
        self.assertTrue(result.is_balanced)
        self.assertEqual(len(result.draft_lines), 2)

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

        result = simulate_invoice(invoice, selection)

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

        result = simulate_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.selected_revenue_account, "600.20")
        self.assertEqual(result.selected_sales_vat_account, "391.20")
        self.assertEqual(result.selected_expense_account, "")
        self.assertEqual(result.selected_purchase_vat_account, "")
        self.assertEqual(result.suggested_counterparty_account, "120.M03")
        self.assertEqual(result.counterparty_creation_suggestion["suggested_code"], "120.M03")
        account_codes = [line["account_code"] for line in result.draft_lines]
        self.assertEqual(account_codes, ["120.01", "600.20", "391.20"])

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

        result = simulate_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.selected_revenue_account, "600.00.3065")
        self.assertEqual(result.selected_sales_vat_account, "")
        self.assertEqual(len(result.draft_lines), 2)
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["120.01", "600.00.3065"])
        self.assertNotIn("391.20", [line["account_code"] for line in result.draft_lines])

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

        result = simulate_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.accounting_direction, "purchase")
        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertEqual(result.selected_purchase_vat_account, "191.20")
        self.assertEqual(result.selected_revenue_account, "")
        self.assertEqual(result.selected_sales_vat_account, "")
        self.assertEqual(result.suggested_counterparty_account, "320.M03")
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["153.01.001", "191.20", "320.01"])

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
        result = simulate_invoice(
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
        self.assertEqual([line["account_code"] for line in result.draft_lines], ["689.01", "320.A06"])
        self.assertEqual(result.export_status, "review_required")

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

        result = simulate_invoice(invoice, selection, profile, processing_mode="controlled_automation")

        self.assertEqual(result.selected_expense_account, "153.01.001")
        self.assertEqual(result.draft_lines[0]["account_code"], "153.01.001")
        self.assertEqual(result.account_candidates["purchase_stock"][0]["code"], "153.01.001")
        self.assertEqual(result.account_candidates["purchase_expense"][0]["code"], "770.02.001")

    def test_return_invoice_stays_out_of_automatic_journal_draft(self) -> None:
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

        result = simulate_invoice(invoice, selection, profile)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.draft_entry_type, "sales_return")
        self.assertEqual(result.total_debit, result.total_credit)
        self.assertTrue(result.draft_lines)
        self.assertEqual(result.selected_revenue_account, "600.20")
        self.assertEqual(result.selected_sales_vat_account, "391.20")
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
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.20",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_invoice(invoice, selection, profile, intended_direction="purchase")

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

        result = simulate_invoice(invoice, selection, profile, intended_direction="sales_invoice")

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

        result = simulate_invoice(invoice, selection, profile, intended_direction="sales_invoice")

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

        result = simulate_invoice(invoice, selection, profile)

        self.assertEqual(result.simulated_status, "review_required")
        self.assertEqual(result.draft_entry_type, "mixed_vat_sales")
        self.assertEqual(result.total_debit, result.total_credit)
        self.assertEqual(result.draft_lines[1]["account_code"], "600.10")
        self.assertEqual(result.draft_lines[2]["account_code"], "391.10")
        self.assertEqual(result.draft_lines[3]["account_code"], "600.20")
        self.assertEqual(result.draft_lines[4]["account_code"], "391.20")
        self.assertIn("mixed_vat_accountant_review", result.review_reason_codes)

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

        result = simulate_invoice(invoice, selection, profile)

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.draft_quality, "gross_balanced_needs_vat_split")
        self.assertEqual(result.draft_entry_type, "review_sales")
        self.assertNotEqual(result.draft_entry_type, "review_purchase")
        self.assertEqual(result.selected_revenue_account, "600.20")
        self.assertEqual(result.selected_customer_account, "120.01")
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
        result = simulate_invoice(invoice, selection, profile)
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
        self.assertEqual(row["selectedRevenueAccount"], "600.20")
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
        result = simulate_invoice(invoice, selection, profile)
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

        summary = private_benchmark_summary([run], run_label="baseline", firm_id="firma-1")

        self.assertEqual(summary["firm_id"], "firma-1")
        self.assertEqual(summary["run_label"], "baseline")
        self.assertEqual(summary["invoice_count"], 1)
        self.assertEqual(summary["mixed_vat_review_count"], 1)
        self.assertEqual(summary["sales_direction_purchase_draft_count"], 0)
        self.assertEqual(summary["counterparty_missing_count"], 1)
        self.assertIn("provider_failure_count", summary)

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

        result = simulate_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

        self.assertTrue(result.ai_classification_used)
        self.assertEqual(result.product_category, "isitme_cihazi")
        self.assertEqual(result.selected_expense_account, "153.01")
        self.assertEqual(result.draft_lines[0]["account_code"], "153.01")
        self.assertEqual(result.export_status, "review_required")

    def test_sales_counterparty_match_uses_customer_prefix_not_supplier_prefix(self) -> None:
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
            run = simulate_chart_run(chart_path, [invoice], profile)
        result = run.invoice_results[0]

        self.assertEqual(result.accounting_direction, "sales")
        self.assertEqual(result.counterparty_match_code, "120.01")
        self.assertEqual(result.selected_customer_account, "120.01")

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

        result = simulate_invoice(invoice, selection, profile)

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
        )
        selection = AccountSelection(
            chart_file_name="chart.xlsx",
            expense_account="770.01",
            purchase_vat_account="191.01",
            supplier_account="320.01",
            bank_account="102.01",
            selection_notes=(),
        )

        result = simulate_invoice(invoice, selection)

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

    def test_static_first_classifier_rejects_invalid_provider_schema(self) -> None:
        classifier = StaticFirstClassifier(
            provider=FakeProductProvider({"category": "serbest", "confidence": 110, "reason": ""}),
            policy=AiClassificationPolicy(enabled=True),
        )

        result = classifier.classify("Bilinmeyen marka kalem")

        self.assertTrue(result.ai_used)
        self.assertEqual(result.classification.category, "bilinmeyen")
        self.assertIn("ai_invalid_schema", result.classification.evidence)

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
        self.assertIn("provider unavailable", result.provider_reason)

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
        self.assertEqual(request_payload["response_format"]["type"], "json_object")
        self.assertIn("Banka pos komisyon bedeli", request_payload["messages"][1]["content"])
        self.assertEqual(response["suggested_account_code"], "770.01")

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

        result = simulate_invoice(invoice, selection, profile, product_classifier=classifier, processing_mode="ai_assisted_draft")

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

        assisted = simulate_invoice(invoice, selection, profile, counterparty, processing_mode="ai_assisted_draft")
        controlled = simulate_invoice(invoice, selection, profile, counterparty, processing_mode="controlled_automation")

        self.assertEqual(assisted.processing_mode, "ai_assisted_draft")
        self.assertEqual(assisted.export_status, "review_required")
        self.assertEqual(assisted.simulated_status, "review_required")
        self.assertIn("ai_assisted_draft_requires_accountant_approval", assisted.review_reason_codes)
        self.assertIn("balanced_entry", assisted.deterministic_checks)
        self.assertIn("mustavir onayi olmadan export kapali", assisted.export_gate_reason)
        self.assertEqual(controlled.export_status, "export_ready")
        self.assertEqual(controlled.simulated_status, "auto_ready")

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

        result = simulate_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_learning_event(build_learning_event(decision))])

        self.assertEqual(result.selected_expense_account, "770.01")
        self.assertEqual(learned.selected_expense_account, "770.05")
        self.assertEqual(learned.draft_lines[0]["account_code"], "770.05")
        self.assertTrue(learned.learning_rule_applied)
        self.assertEqual(learned.learning_rule_scope, "client_rule")

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

        result = simulate_invoice(invoice, selection, profile)
        learned = apply_learning_rules(result, [rule_from_event_payload(event)])

        self.assertEqual(learned.selected_expense_account, "770.05")
        self.assertIn("learning_rule_review_required", learned.review_reason_codes)
        self.assertEqual(learned.export_status, "review_required")
        self.assertIn("Kolay Soft", learned.learning_rule_reason)

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
