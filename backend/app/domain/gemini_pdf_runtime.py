from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Callable, Mapping

from app.domain.openai_provider import GeminiAccountingProvider


DEFAULT_GEMINI_PDF_V2_MODEL = "gemini-3.5-flash-lite"
GEMINI_PDF_V2_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class GeminiPdfRuntime:
    provider: GeminiAccountingProvider | None
    available: bool
    max_parallel_accounting_chunks: int = 1
    candidate_experiment_percent: int = 0
    max_accounting_request_bytes: int = 3_000_000
    retryable: bool = False
    unavailable_reason: str = ""


@dataclass(frozen=True)
class CandidateDiscoveryAssignment:
    mode: str
    group: str
    bucket: int
    experiment_percent: int


def candidate_discovery_assignment(
    *,
    taxpayer_id: str,
    document_id: str,
    experiment_percent: int,
) -> CandidateDiscoveryAssignment:
    percent = _percentage(experiment_percent)
    key = f"{taxpayer_id}:{document_id}:candidate-discovery-v1".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(key).digest(), "big") % 100
    experiment = bucket < percent
    return CandidateDiscoveryAssignment(
        mode="exhaustive" if experiment else "adaptive",
        group="experiment" if experiment else "control",
        bucket=bucket,
        experiment_percent=percent,
    )


def gemini_pdf_v2_enabled(env: Mapping[str, str]) -> bool:
    return (
        str(env.get("FISORA_GEMINI_PDF_V2_ENABLED", "") or "")
        .strip()
        .lower()
        in GEMINI_PDF_V2_ENABLED_VALUES
    )


def candidate_experiment_percent_from_env(env: Mapping[str, str]) -> int:
    return _percentage(
        env.get("FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT", "0") or "0"
    )


def max_accounting_request_bytes_from_env(env: Mapping[str, str]) -> int:
    return _positive_int(
        env.get("FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES", "3000000")
        or "3000000"
    )


def max_accounting_provider_calls_from_env(
    env: Mapping[str, str],
) -> int | None:
    raw = str(
        env.get("FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS", "") or ""
    ).strip()
    return _positive_int(raw) if raw else None


def build_gemini_pdf_runtime_from_env(
    env: Mapping[str, str],
) -> GeminiPdfRuntime:
    """Build the native-PDF provider without consulting the general AI chain."""

    api_key = str(env.get("GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return _unavailable("gemini_api_key_missing")

    numeric_fields: tuple[
        tuple[str, str, Callable[[object], float | int]], ...
    ] = (
        ("FISORA_GEMINI_TIMEOUT_SECONDS", "60", _positive_float),
        ("FISORA_GEMINI_MAX_OUTPUT_TOKENS", "16384", _positive_int),
        ("FISORA_GEMINI_MAX_INLINE_PDF_BYTES", "50000000", _positive_int),
        ("FISORA_GEMINI_REQUESTS_PER_MINUTE", "15", _positive_int),
        ("FISORA_GEMINI_V2_MAX_PARALLEL_CHUNKS", "3", _positive_int),
    )
    parsed: dict[str, float | int] = {}
    for field, default, parser in numeric_fields:
        try:
            parsed[field] = parser(env.get(field, default) or default)
        except (TypeError, ValueError, OverflowError):
            return _unavailable(f"gemini_runtime_config_invalid:{field}")
    try:
        experiment_percent = candidate_experiment_percent_from_env(env)
    except (TypeError, ValueError, OverflowError):
        return _unavailable(
            "gemini_runtime_config_invalid:FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT"
        )
    try:
        max_accounting_request_bytes = max_accounting_request_bytes_from_env(env)
    except (TypeError, ValueError, OverflowError):
        return _unavailable(
            "gemini_runtime_config_invalid:FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES"
        )

    provider = GeminiAccountingProvider(
        api_key=api_key,
        model=str(
            env.get("FISORA_GEMINI_PDF_V2_MODEL", DEFAULT_GEMINI_PDF_V2_MODEL)
            or DEFAULT_GEMINI_PDF_V2_MODEL
        ),
        generate_content_url=str(
            env.get("FISORA_GEMINI_GENERATE_CONTENT_URL", "") or ""
        ),
        timeout_seconds=float(parsed["FISORA_GEMINI_TIMEOUT_SECONDS"]),
        max_output_tokens=int(parsed["FISORA_GEMINI_MAX_OUTPUT_TOKENS"]),
        max_inline_pdf_bytes=int(parsed["FISORA_GEMINI_MAX_INLINE_PDF_BYTES"]),
        requests_per_minute=int(parsed["FISORA_GEMINI_REQUESTS_PER_MINUTE"]),
    )
    return GeminiPdfRuntime(
        provider=provider,
        available=True,
        max_parallel_accounting_chunks=min(
            int(parsed["FISORA_GEMINI_V2_MAX_PARALLEL_CHUNKS"]), 8
        ),
        candidate_experiment_percent=experiment_percent,
        max_accounting_request_bytes=max_accounting_request_bytes,
    )


def _unavailable(reason: str) -> GeminiPdfRuntime:
    return GeminiPdfRuntime(
        provider=None,
        available=False,
        retryable=False,
        unavailable_reason=reason,
    )


def _positive_float(value: object) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("value must be a finite positive number")
    return parsed


def _positive_int(value: object) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("value must be a positive integer")
    return parsed


def _percentage(value: object) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 100:
        raise ValueError("value must be between 0 and 100")
    return parsed
