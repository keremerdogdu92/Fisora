# File: backend/app/domain/gemini_project_pool.py
# Summary: Dispatches Gemini calls across bounded project slots with rate-aware failover and cooldown handling.
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from threading import Lock
from time import monotonic
from typing import Any, Callable, Mapping

from app.domain.openai_provider import (
    GeminiAccountingProvider,
    GeminiProviderAttemptError,
)


@dataclass(frozen=True)
class GeminiProjectSlotConfig:
    slot_name: str
    api_key: str = field(repr=False)
    requests_per_minute: int = 0


@dataclass(frozen=True)
class GeminiProjectSlotDiscovery:
    configs: tuple[GeminiProjectSlotConfig, ...]
    invalid_fields: tuple[str, ...] = ()


def gemini_project_slot_discovery_from_env(
    env: Mapping[str, str],
    *,
    default_requests_per_minute: int = 15,
) -> GeminiProjectSlotDiscovery:
    """Read the bounded, secret-bearing project slots without exposing secrets."""

    unique_keys: list[tuple[int, str]] = []
    seen_digests: set[bytes] = set()
    for index in range(1, 9):
        key_name = "GEMINI_API_KEY" if index == 1 else f"GEMINI_API_KEY_{index}"
        api_key = str(env.get(key_name, "") or "").strip()
        if not api_key:
            continue
        digest = hashlib.sha256(api_key.encode("utf-8")).digest()
        if digest in seen_digests:
            continue
        seen_digests.add(digest)
        unique_keys.append((index, api_key))

    if not unique_keys:
        return GeminiProjectSlotDiscovery(())

    shared_raw = env.get(
        "FISORA_GEMINI_REQUESTS_PER_MINUTE", str(default_requests_per_minute)
    ) or str(default_requests_per_minute)
    shared_rpm = _try_positive_int(shared_raw)
    configs: list[GeminiProjectSlotConfig] = []
    invalid_fields: list[str] = []
    for index, api_key in unique_keys:
        override_name = f"FISORA_GEMINI_REQUESTS_PER_MINUTE_{index}"
        override = env.get(override_name)
        if override is not None and str(override).strip():
            requests_per_minute = _try_positive_int(override)
            if requests_per_minute is None:
                invalid_fields.append(override_name)
                continue
        else:
            requests_per_minute = shared_rpm
            if requests_per_minute is None:
                invalid_fields.append("FISORA_GEMINI_REQUESTS_PER_MINUTE")
                continue
        configs.append(
            GeminiProjectSlotConfig(
                slot_name=f"GEMINI_API_KEY_SLOT_{index}",
                api_key=api_key,
                requests_per_minute=requests_per_minute,
            )
        )
    return GeminiProjectSlotDiscovery(tuple(configs), tuple(invalid_fields))


def gemini_project_slot_configs_from_env(
    env: Mapping[str, str],
    *,
    default_requests_per_minute: int = 15,
) -> tuple[GeminiProjectSlotConfig, ...]:
    """Compatibility view of the usable project slots discovered from env."""

    return gemini_project_slot_discovery_from_env(
        env,
        default_requests_per_minute=default_requests_per_minute,
    ).configs


def gemini_project_credential_slots_from_env(
    env: Mapping[str, str],
) -> tuple[str, ...]:
    """Return usable opaque slot names without parsing or exposing secrets."""

    return tuple(
        config.slot_name
        for config in gemini_project_slot_discovery_from_env(env).configs
    )


class GeminiProjectPoolProvider:
    """Thread-safe dispatcher over independently governed Gemini projects."""

    provider_name = "gemini"

    def __init__(
        self,
        slot_configs: tuple[GeminiProjectSlotConfig, ...] | list[GeminiProjectSlotConfig],
        *,
        provider_factory: Callable[[GeminiProjectSlotConfig], Any] | None = None,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not slot_configs:
            raise ValueError("GeminiProjectPoolProvider requires at least one project slot")
        if cooldown_seconds < 0:
            raise ValueError("Gemini project cooldown must not be negative")
        self._configs = tuple(slot_configs)
        self._clock = clock
        self._cooldown_seconds = float(cooldown_seconds)
        factory = provider_factory or self._default_provider_factory
        self._providers = tuple(factory(config) for config in self._configs)
        self._lock = Lock()
        self._in_flight = {config.slot_name: 0 for config in self._configs}
        self._last_selection = {config.slot_name: 0 for config in self._configs}
        self._cooling_until = {config.slot_name: 0.0 for config in self._configs}
        self._selection_sequence = 0
        self.last_provider_name = ""
        self.last_credential_slot = ""
        self.last_attempted_credential_slots: tuple[str, ...] = ()
        self.last_capacity_snapshot: dict[str, object] = {}
        self.last_product_classification_instructions = ""
        self.product_classification_instructions = ""
        self.product_classification_prompt_version = ""
        self._copy_provider_metadata(self._providers[0])

    @staticmethod
    def _default_provider_factory(config: GeminiProjectSlotConfig) -> GeminiAccountingProvider:
        return GeminiAccountingProvider(
            api_key=config.api_key,
            requests_per_minute=config.requests_per_minute,
            credential_slot=config.slot_name,
        )

    @property
    def configured_project_count(self) -> int:
        return len(self._configs)

    @property
    def configured_credential_slots(self) -> tuple[str, ...]:
        return tuple(config.slot_name for config in self._configs)

    @property
    def providers(self) -> tuple[Any, ...]:
        return self._providers

    @property
    def model(self) -> str:
        return str(getattr(self._providers[0], "model", "") or "")

    @property
    def in_flight_by_slot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._in_flight)

    def classify_product(self, request: Any) -> dict[str, Any]:
        return self._call("classify_product", request)

    def extract_invoice_canonical(self, request: Any) -> dict[str, Any]:
        return self._call("extract_invoice_canonical", request)

    def generate_structured_json(self, **kwargs: Any) -> dict[str, Any]:
        return self._call_kwargs("generate_structured_json", kwargs)

    def _call(self, method_name: str, request: Any) -> dict[str, Any]:
        index = self._lease_slot()
        config = self._configs[index]
        provider = self._providers[index]
        try:
            result = getattr(provider, method_name)(request)
            self.last_provider_name = self.provider_name
            return result
        except GeminiProviderAttemptError as error:
            if error.attempt.http_status == 429:
                with self._lock:
                    self._cooling_until[config.slot_name] = (
                        self._clock() + self._cooldown_seconds
                    )
            raise
        finally:
            with self._lock:
                self._copy_provider_metadata(provider)
                self._in_flight[config.slot_name] -= 1

    def _call_kwargs(self, method_name: str, kwargs: Mapping[str, object]) -> dict[str, Any]:
        last_error: GeminiProviderAttemptError | None = None
        attempted_slots: list[str] = []
        for attempt_index in range(len(self._configs)):
            index = self._lease_slot()
            config = self._configs[index]
            provider = self._providers[index]
            attempted_slots.append(config.slot_name)
            try:
                result = getattr(provider, method_name)(**dict(kwargs))
                self.last_provider_name = self.provider_name
                self._record_structured_attempts(attempted_slots, success_slot=config.slot_name)
                return result
            except GeminiProviderAttemptError as error:
                last_error = error
                status = error.attempt.http_status
                phase = str(error.attempt.error_metadata.get("phase") or "").strip().lower()
                failover_statuses = {401, 403, 408, 429, 500, 502, 503, 504}
                failover_phases = {"transport", "response_capture", "response_json", "structured_parse"}
                should_failover = status in failover_statuses or status is None or phase in failover_phases
                if status in failover_statuses:
                    with self._lock:
                        self._cooling_until[config.slot_name] = (
                            float("inf") if status in {401, 403}
                            else self._clock() + self._cooldown_seconds
                        )
                if should_failover and attempt_index + 1 < len(self._configs):
                    continue
                self._record_structured_attempts(attempted_slots)
                raise
            finally:
                with self._lock:
                    self._copy_provider_metadata(provider)
                    self._in_flight[config.slot_name] -= 1
        if last_error is not None:
            self._record_structured_attempts(attempted_slots)
            raise last_error
        self._record_structured_attempts(attempted_slots)
        raise RuntimeError("Gemini project pool has no callable slot")

    def _record_structured_attempts(self, attempted_slots: list[str], *, success_slot: str = "") -> None:
        with self._lock:
            self.last_attempted_credential_slots = tuple(attempted_slots)
            self.last_credential_slot = success_slot

    def _copy_provider_metadata(self, provider: Any) -> None:
        snapshot = getattr(provider, "last_capacity_snapshot", {})
        self.last_capacity_snapshot = dict(snapshot) if isinstance(snapshot, Mapping) else {}
        self.last_product_classification_instructions = str(
            getattr(provider, "last_product_classification_instructions", "") or ""
        )
        self.product_classification_instructions = str(
            getattr(provider, "product_classification_instructions", "") or ""
        )
        self.product_classification_prompt_version = str(
            getattr(provider, "product_classification_prompt_version", "") or ""
        )

    def _lease_slot(self) -> int:
        with self._lock:
            now = self._clock()
            available = [
                index
                for index, config in enumerate(self._configs)
                if self._cooling_until[config.slot_name] <= now
            ]
            if not available:
                earliest = min(
                    self._cooling_until[config.slot_name]
                    for config in self._configs
                )
                available = [
                    index
                    for index, config in enumerate(self._configs)
                    if self._cooling_until[config.slot_name] == earliest
                ]
            index = min(
                available,
                key=lambda candidate: (
                    self._in_flight[self._configs[candidate].slot_name],
                    self._last_selection[self._configs[candidate].slot_name],
                    candidate,
                ),
            )
            config = self._configs[index]
            self._in_flight[config.slot_name] += 1
            self._selection_sequence += 1
            self._last_selection[config.slot_name] = self._selection_sequence
            return index


def _positive_int(value: object, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"invalid Gemini runtime config: {field_name}") from error
    if parsed <= 0:
        raise ValueError(f"invalid Gemini runtime config: {field_name}")
    return parsed


def _try_positive_int(value: object) -> int | None:
    try:
        return _positive_int(value, "rpm")
    except (TypeError, ValueError, OverflowError):
        return None
