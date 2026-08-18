from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.gemini_project_pool import (
    GeminiProjectPoolProvider,
    GeminiProjectSlotConfig,
    gemini_project_slot_discovery_from_env,
    gemini_project_slot_configs_from_env,
)
from app.domain.openai_provider import GeminiAttemptEnvelope, GeminiProviderAttemptError


def _attempt(*, http_status: int | None) -> GeminiAttemptEnvelope:
    now = datetime.now(UTC)
    return GeminiAttemptEnvelope(
        request_body=b"{}",
        response_body=b"",
        provider="gemini",
        model_alias="test",
        resolved_model="test",
        http_status=http_status,
        started_at=now,
        finished_at=now,
        elapsed_ms=0,
        token_usage={},
        status="failed",
        error_metadata={},
        credential_slot="GEMINI_API_KEY_SLOT_1",
    )


class _FakeProvider:
    def __init__(self, config: GeminiProjectSlotConfig) -> None:
        self.config = config
        self.provider_name = "gemini"
        self.request_governor = object()
        self.last_capacity_snapshot: dict[str, object] = {
            "slot": config.slot_name,
            "tokens": 0,
        }
        self.last_product_classification_instructions = "instructions"
        self.product_classification_instructions = "product-instructions"
        self.product_classification_prompt_version = "prompt-v1"
        self.calls: list[tuple[str, object]] = []
        self.error_once: GeminiProviderAttemptError | None = None
        self.started: threading.Event | None = None
        self.release: threading.Event | None = None

    def classify_product(self, request: object) -> dict[str, object]:
        self.calls.append(("classify_product", request))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        if self.error_once is not None:
            error, self.error_once = self.error_once, None
            raise error
        return {"slot": self.config.slot_name}

    def extract_invoice_canonical(self, request: object) -> dict[str, object]:
        self.calls.append(("extract_invoice_canonical", request))
        if self.error_once is not None:
            error, self.error_once = self.error_once, None
            raise error
        return {"slot": self.config.slot_name}


class GeminiProjectPoolTests(unittest.TestCase):
    def test_enumerates_one_three_seven_and_eight_unique_slots_even_when_primary_blank(self) -> None:
        for count in (1, 3, 7, 8):
            env = {
                "GEMINI_API_KEY": "" if count == 1 else "key-1",
                **{f"GEMINI_API_KEY_{index}": f"key-{index}" for index in range(2, count + 1)},
            }
            if count == 1:
                env["GEMINI_API_KEY_2"] = "key-2"
            configs = gemini_project_slot_configs_from_env(env)
            self.assertEqual(
                len(configs), count,
                msg=f"expected {count} configured slots",
            )
            self.assertEqual(
                tuple(config.slot_name for config in configs),
                tuple(f"GEMINI_API_KEY_SLOT_{index}" for index in range(1, count + 1))
                if count > 1
                else ("GEMINI_API_KEY_SLOT_2",),
            )

    def test_blank_and_duplicate_values_are_omitted_without_exposing_value_or_digest(self) -> None:
        duplicate = "secret-duplicate-value"
        configs = gemini_project_slot_configs_from_env(
            {
                "GEMINI_API_KEY": duplicate,
                "GEMINI_API_KEY_2": "   ",
                "GEMINI_API_KEY_3": duplicate,
                "GEMINI_API_KEY_4": "unique",
            }
        )

        self.assertEqual(
            [config.slot_name for config in configs],
            ["GEMINI_API_KEY_SLOT_1", "GEMINI_API_KEY_SLOT_4"],
        )
        rendered = repr(configs)
        self.assertNotIn(duplicate, rendered)

    def test_slot_rpm_override_falls_back_to_shared_value(self) -> None:
        configs = gemini_project_slot_configs_from_env(
            {
                "GEMINI_API_KEY": "key-1",
                "GEMINI_API_KEY_2": "key-2",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE": "15",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE_1": "30",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE_2": "45",
            }
        )

        self.assertEqual([config.requests_per_minute for config in configs], [30, 45])

    def test_slot_and_shared_rpm_invalid_values_are_excluded_secret_safely(self) -> None:
        invalid_values = ("0", "-1", "not-a-number-secret")
        for field in ("FISORA_GEMINI_REQUESTS_PER_MINUTE", "FISORA_GEMINI_REQUESTS_PER_MINUTE_1"):
            for invalid in invalid_values:
                with self.subTest(field=field, invalid=invalid):
                    env = {"GEMINI_API_KEY": "key-1", field: invalid}
                    discovery = gemini_project_slot_discovery_from_env(env)
                    self.assertEqual(discovery.configs, ())
                    self.assertEqual(discovery.invalid_fields, (field,))
                    self.assertNotIn(invalid, repr(discovery))

    def test_invalid_per_slot_rpm_drops_only_that_unique_project(self) -> None:
        discovery = gemini_project_slot_discovery_from_env(
            {
                "GEMINI_API_KEY": "key-1",
                "GEMINI_API_KEY_2": "key-2",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE": "15",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE_2": "invalid-rpm-secret",
            }
        )

        self.assertEqual(
            tuple(config.slot_name for config in discovery.configs),
            ("GEMINI_API_KEY_SLOT_1",),
        )
        self.assertEqual(
            discovery.invalid_fields,
            ("FISORA_GEMINI_REQUESTS_PER_MINUTE_2",),
        )

    def test_invalid_shared_rpm_does_not_drop_slot_with_valid_override(self) -> None:
        discovery = gemini_project_slot_discovery_from_env(
            {
                "GEMINI_API_KEY": "key-1",
                "GEMINI_API_KEY_2": "key-2",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE": "invalid-shared-secret",
                "FISORA_GEMINI_REQUESTS_PER_MINUTE_2": "30",
            }
        )

        self.assertEqual(
            tuple(config.slot_name for config in discovery.configs),
            ("GEMINI_API_KEY_SLOT_2",),
        )
        self.assertEqual(
            discovery.configs[0].requests_per_minute,
            30,
        )
        self.assertEqual(
            discovery.invalid_fields,
            ("FISORA_GEMINI_REQUESTS_PER_MINUTE",),
        )

    def test_sequential_selection_uses_oldest_selection_then_slot_number(self) -> None:
        providers: list[_FakeProvider] = []

        def factory(config: GeminiProjectSlotConfig) -> _FakeProvider:
            provider = _FakeProvider(config)
            providers.append(provider)
            return provider

        pool = GeminiProjectPoolProvider(
            [
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_1", "key-1", 15),
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_2", "key-2", 15),
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_3", "key-3", 15),
            ],
            provider_factory=factory,
        )

        slots = [pool.classify_product(object())["slot"] for _ in range(4)]

        self.assertEqual(
            slots,
            [
                "GEMINI_API_KEY_SLOT_1",
                "GEMINI_API_KEY_SLOT_2",
                "GEMINI_API_KEY_SLOT_3",
                "GEMINI_API_KEY_SLOT_1",
            ],
        )

    def test_all_cooling_slots_select_earliest_expiry(self) -> None:
        now = {"value": 100.0}
        providers: list[_FakeProvider] = []

        def factory(config: GeminiProjectSlotConfig) -> _FakeProvider:
            provider = _FakeProvider(config)
            providers.append(provider)
            return provider

        pool = GeminiProjectPoolProvider(
            [
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_1", "key-1", 15),
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_2", "key-2", 15),
            ],
            provider_factory=factory,
            cooldown_seconds=60,
            clock=lambda: now["value"],
        )
        first_error = GeminiProviderAttemptError("first", attempt=_attempt(http_status=429))
        providers[0].error_once = first_error
        with self.assertRaises(GeminiProviderAttemptError):
            pool.classify_product(object())

        now["value"] = 110.0
        second_error = GeminiProviderAttemptError("second", attempt=_attempt(http_status=429))
        providers[1].error_once = second_error
        with self.assertRaises(GeminiProviderAttemptError):
            pool.classify_product(object())

        result = pool.classify_product(object())
        self.assertEqual(result["slot"], "GEMINI_API_KEY_SLOT_1")
        self.assertEqual(len(providers[0].calls), 2)
        self.assertEqual(len(providers[1].calls), 1)

    def test_concurrent_calls_use_distinct_slots_and_release_leases(self) -> None:
        providers: list[_FakeProvider] = []

        def factory(config: GeminiProjectSlotConfig) -> _FakeProvider:
            provider = _FakeProvider(config)
            provider.started = threading.Event()
            provider.release = threading.Event()
            providers.append(provider)
            return provider

        pool = GeminiProjectPoolProvider(
            [
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_1", "key-1", 15),
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_2", "key-2", 15),
            ],
            provider_factory=factory,
        )
        results: list[dict[str, object]] = []

        def call() -> None:
            results.append(pool.classify_product(object()))

        first = threading.Thread(target=call)
        second = threading.Thread(target=call)
        first.start()
        self.assertTrue(providers[0].started.wait(timeout=2))
        second.start()
        self.assertTrue(providers[1].started.wait(timeout=2))
        for provider in providers:
            assert provider.release is not None
            provider.release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(
            {result["slot"] for result in results},
            {"GEMINI_API_KEY_SLOT_1", "GEMINI_API_KEY_SLOT_2"},
        )
        self.assertEqual(pool.in_flight_by_slot, {"GEMINI_API_KEY_SLOT_1": 0, "GEMINI_API_KEY_SLOT_2": 0})

    def test_429_cools_only_selected_slot_and_following_call_uses_next_slot(self) -> None:
        clock = {"now": 100.0}
        providers: list[_FakeProvider] = []

        def factory(config: GeminiProjectSlotConfig) -> _FakeProvider:
            provider = _FakeProvider(config)
            providers.append(provider)
            return provider

        pool = GeminiProjectPoolProvider(
            [
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_1", "key-1", 15),
                GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_2", "key-2", 15),
            ],
            provider_factory=factory,
            cooldown_seconds=60,
            clock=lambda: clock["now"],
        )
        first_error = GeminiProviderAttemptError("rate limited", attempt=_attempt(http_status=429))
        providers[0].error_once = first_error

        with self.assertRaises(GeminiProviderAttemptError) as raised:
            pool.classify_product(object())
        self.assertIs(raised.exception, first_error)
        self.assertIs(raised.exception.attempt, first_error.attempt)
        self.assertEqual(len(providers[0].calls), 1)

        result = pool.classify_product(object())
        self.assertEqual(result["slot"], "GEMINI_API_KEY_SLOT_2")
        self.assertEqual(len(providers[0].calls), 1)
        self.assertEqual(len(providers[1].calls), 1)

    def test_selected_provider_metadata_is_propagated_on_success_and_failure(self) -> None:
        provider = _FakeProvider(
            GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_1", "key-1", 15)
        )
        pool = GeminiProjectPoolProvider(
            [provider.config], provider_factory=lambda _config: provider
        )

        provider.last_capacity_snapshot = {"tokens": 42}
        provider.last_product_classification_instructions = "last-success"
        provider.product_classification_instructions = "safe-product"
        provider.product_classification_prompt_version = "prompt-success"
        pool.classify_product(object())

        self.assertEqual(pool.last_capacity_snapshot, {"tokens": 42})
        self.assertEqual(pool.last_product_classification_instructions, "last-success")
        self.assertEqual(pool.product_classification_instructions, "safe-product")
        self.assertEqual(pool.product_classification_prompt_version, "prompt-success")

        provider.last_capacity_snapshot = {"tokens": 43}
        provider.last_product_classification_instructions = "last-failure"
        provider.error_once = GeminiProviderAttemptError(
            "bad request", attempt=_attempt(http_status=400)
        )
        with self.assertRaises(GeminiProviderAttemptError):
            pool.classify_product(object())

        self.assertEqual(pool.last_capacity_snapshot, {"tokens": 43})
        self.assertEqual(pool.last_product_classification_instructions, "last-failure")
        self.assertEqual(pool.product_classification_instructions, "safe-product")
        self.assertEqual(pool.product_classification_prompt_version, "prompt-success")

    def test_failure_is_not_retried_inside_pool(self) -> None:
        provider = _FakeProvider(
            GeminiProjectSlotConfig("GEMINI_API_KEY_SLOT_1", "key-1", 15)
        )
        provider.error_once = GeminiProviderAttemptError(
            "bad request", attempt=_attempt(http_status=400)
        )
        pool = GeminiProjectPoolProvider(
            [provider.config], provider_factory=lambda _config: provider
        )

        with self.assertRaises(GeminiProviderAttemptError):
            pool.extract_invoice_canonical(object())
        self.assertEqual(len(provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
