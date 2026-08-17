from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.gemini_pdf_runtime import (
    build_gemini_pdf_runtime_from_env,
    candidate_discovery_assignment,
    gemini_pdf_v2_enabled,
    max_accounting_provider_calls_from_env,
)
from app.domain.openai_provider import GeminiAccountingProvider, GeminiRequestGovernor


class _ObservedEnvironment(Mapping[str, str]):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.read_keys: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.read_keys.append(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: str | None = None) -> str | None:
        self.read_keys.append(key)
        return self._values.get(key, default)


class GeminiPdfRuntimeV2Tests(unittest.TestCase):
    def test_accounting_provider_call_budget_is_optional_and_positive(self) -> None:
        self.assertIsNone(max_accounting_provider_calls_from_env({}))
        self.assertEqual(
            max_accounting_provider_calls_from_env(
                {"FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS": "19"}
            ),
            19,
        )
        with self.assertRaises(ValueError):
            max_accounting_provider_calls_from_env(
                {"FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS": "0"}
            )

    def test_candidate_experiment_assignment_is_stable_taxpayer_scoped_and_defaults_control(self) -> None:
        control = candidate_discovery_assignment(
            taxpayer_id="taxpayer-1",
            document_id="document-1",
            experiment_percent=0,
        )
        first = candidate_discovery_assignment(
            taxpayer_id="taxpayer-1",
            document_id="document-1",
            experiment_percent=50,
        )
        retry = candidate_discovery_assignment(
            taxpayer_id="taxpayer-1",
            document_id="document-1",
            experiment_percent=50,
        )
        other_taxpayer = candidate_discovery_assignment(
            taxpayer_id="taxpayer-2",
            document_id="document-1",
            experiment_percent=50,
        )

        self.assertEqual(control.mode, "adaptive")
        self.assertEqual(control.group, "control")
        self.assertEqual(first, retry)
        self.assertIn(first.mode, {"adaptive", "exhaustive"})
        self.assertIn(first.group, {"control", "experiment"})
        self.assertGreaterEqual(first.bucket, 0)
        self.assertLess(first.bucket, 100)
        self.assertNotEqual(first.bucket, other_taxpayer.bucket)

    def test_runtime_defaults_experiment_off_and_parses_candidate_limits(self) -> None:
        default = build_gemini_pdf_runtime_from_env({"GEMINI_API_KEY": "test-key"})
        configured = build_gemini_pdf_runtime_from_env(
            {
                "GEMINI_API_KEY": "test-key",
                "FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT": "50",
                "FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES": "2500000",
            }
        )

        self.assertEqual(default.candidate_experiment_percent, 0)
        self.assertEqual(default.max_accounting_request_bytes, 3_000_000)
        self.assertEqual(configured.candidate_experiment_percent, 50)
        self.assertEqual(configured.max_accounting_request_bytes, 2_500_000)

    def test_request_governor_spaces_starts_without_changing_results(self) -> None:
        state = {"now": 100.0}
        waits: list[float] = []

        def sleep_and_advance(seconds: float) -> None:
            waits.append(seconds)
            state["now"] += seconds

        governor = GeminiRequestGovernor(
            30,
            clock=lambda: state["now"],
            sleeper=sleep_and_advance,
        )

        governor.acquire()
        governor.acquire()
        governor.acquire()

        self.assertEqual(waits, [2.0, 2.0])

    def test_dedicated_runtime_defaults_to_validated_v2_model(self) -> None:
        runtime = build_gemini_pdf_runtime_from_env({"GEMINI_API_KEY": "test-key"})

        self.assertTrue(runtime.available)
        self.assertEqual("gemini-3.5-flash-lite", runtime.provider.model)

    def test_dedicated_runtime_ignores_general_provider_chain(self) -> None:
        env = _ObservedEnvironment(
            {
                "GEMINI_API_KEY": "test-dedicated-key",
                "FISORA_GEMINI_PDF_V2_MODEL": "gemini-v2-test-model",
                "FISORA_GEMINI_MODEL": "legacy-gemini-model",
                "FISORA_GEMINI_GENERATE_CONTENT_URL": "https://gemini.test/generate",
                "FISORA_GEMINI_TIMEOUT_SECONDS": "17.5",
                "FISORA_GEMINI_MAX_OUTPUT_TOKENS": "4096",
                "FISORA_GEMINI_MAX_INLINE_PDF_BYTES": "123456",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE": "90",
                "FISORA_GEMINI_V2_MAX_PARALLEL_CHUNKS": "4",
                "FISORA_AI_PROVIDER_CHAIN": "groq,cloudflare",
            }
        )

        runtime = build_gemini_pdf_runtime_from_env(env)

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertTrue(runtime.available)
        self.assertFalse(runtime.retryable)
        self.assertIsInstance(runtime.provider, GeminiAccountingProvider)
        self.assertEqual(runtime.provider.model, "gemini-v2-test-model")
        self.assertEqual(runtime.provider.generate_content_url, "https://gemini.test/generate")
        self.assertEqual(runtime.provider.timeout_seconds, 17.5)
        self.assertEqual(runtime.provider.max_output_tokens, 4096)
        self.assertEqual(runtime.provider.max_inline_pdf_bytes, 123456)
        self.assertEqual(runtime.max_parallel_accounting_chunks, 4)
        self.assertNotIn("FISORA_AI_PROVIDER_CHAIN", env.read_keys)
        self.assertNotIn("FISORA_GEMINI_MODEL", env.read_keys)

    def test_worker_feature_flag_is_explicit_and_defaults_off(self) -> None:
        self.assertFalse(gemini_pdf_v2_enabled({}))
        self.assertFalse(
            gemini_pdf_v2_enabled({"FISORA_GEMINI_PDF_V2_ENABLED": "false"})
        )
        for value in ("1", "true", "yes", "on", " TRUE "):
            with self.subTest(value=value):
                self.assertTrue(
                    gemini_pdf_v2_enabled(
                        {"FISORA_GEMINI_PDF_V2_ENABLED": value}
                    )
                )

    def test_missing_key_returns_explicit_unavailable_without_legacy_provider_lookup(self) -> None:
        env = _ObservedEnvironment(
            {
                "GEMINI_API_KEY": "   ",
                "OPENAI_API_KEY": "must-not-be-read",
                "GROQ_API_KEY": "must-not-be-read",
                "FISORA_AI_PROVIDER_CHAIN": "openai,groq",
            }
        )

        runtime = build_gemini_pdf_runtime_from_env(env)

        self.assertFalse(runtime.available)
        self.assertFalse(runtime.retryable)
        self.assertEqual(runtime.unavailable_reason, "gemini_api_key_missing")
        self.assertIsNone(runtime.provider)
        self.assertEqual(env.read_keys, ["GEMINI_API_KEY"])
        self.assertNotIn("must-not-be-read", repr(runtime))

    def test_malformed_numeric_config_returns_field_specific_secret_safe_state(self) -> None:
        numeric_fields = (
            "FISORA_GEMINI_TIMEOUT_SECONDS",
            "FISORA_GEMINI_MAX_OUTPUT_TOKENS",
            "FISORA_GEMINI_MAX_INLINE_PDF_BYTES",
            "FISORA_GEMINI_REQUESTS_PER_MINUTE",
            "FISORA_GEMINI_V2_MAX_PARALLEL_CHUNKS",
            "FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT",
            "FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES",
        )
        for field in numeric_fields:
            with self.subTest(field=field):
                raw_value = f"not-a-number-secret-{field}"
                env = {
                    "GEMINI_API_KEY": "test-key-must-not-leak",
                    field: raw_value,
                    "FISORA_AI_PROVIDER_CHAIN": "openai,groq",
                }

                runtime = build_gemini_pdf_runtime_from_env(env)

                self.assertFalse(runtime.available)
                self.assertFalse(runtime.retryable)
                self.assertIsNone(runtime.provider)
                self.assertEqual(
                    runtime.unavailable_reason,
                    f"gemini_runtime_config_invalid:{field}",
                )
                rendered = repr(runtime)
                self.assertNotIn(raw_value, rendered)
                self.assertNotIn("test-key-must-not-leak", rendered)
                self.assertNotIn("invalid literal", rendered)


if __name__ == "__main__":
    unittest.main()
