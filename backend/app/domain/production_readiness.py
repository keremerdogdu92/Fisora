from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from app.domain.auth_policy import auth_status_payload, build_auth_config
from app.domain.export_adapters import SUPPORTED_EXPORT_ADAPTERS
from app.domain.openai_provider import (
    DEFAULT_CEREBRAS_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENROUTER_MODEL,
)
from app.domain.rate_limits import rate_limit_config
from app.domain.storage_adapters import storage_readiness
from app.domain.system_health import backup_health, storage_usage_health


def _env_bool(value: str, *, default: bool = False) -> bool:
    if not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _ai_provider_chain(source: Mapping[str, str]) -> list[str]:
    chain = [
        name.strip().lower()
        for name in source.get("FISORA_AI_PROVIDER_CHAIN", "").split(",")
        if name.strip()
    ]
    provider_name = source.get("FISORA_AI_PROVIDER", "disabled").strip().lower() or "disabled"
    if not chain and provider_name != "disabled":
        chain = [provider_name]
    return chain


def _ai_provider_model(provider_name: str, source: Mapping[str, str]) -> str:
    configured_ai_model = source.get("FISORA_AI_MODEL", "").strip()
    if provider_name == "openai":
        return source.get("FISORA_OPENAI_MODEL", "").strip() or configured_ai_model or DEFAULT_OPENAI_MODEL
    if provider_name == "groq":
        return source.get("FISORA_GROQ_MODEL", "").strip() or configured_ai_model or DEFAULT_GROQ_MODEL
    if provider_name == "openrouter":
        return source.get("FISORA_OPENROUTER_MODEL", "").strip() or DEFAULT_OPENROUTER_MODEL
    if provider_name == "cerebras":
        return source.get("FISORA_CEREBRAS_MODEL", "").strip() or DEFAULT_CEREBRAS_MODEL
    return configured_ai_model


def _ai_provider_key_present(provider_name: str, source: Mapping[str, str]) -> bool:
    key_names = {
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
    }
    key_name = key_names.get(provider_name, "")
    return bool(key_name and source.get(key_name, "").strip())


def production_readiness_payload(
    *,
    document_storage_path: Path | str,
    export_path: Path | str,
    backup_path: Path | str,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    source = env if env is not None else os.environ
    supported_ai_providers = {"openai", "groq", "openrouter", "cerebras"}
    ai_provider_chain = _ai_provider_chain(source)
    ai_provider = ">".join(ai_provider_chain) if ai_provider_chain else "disabled"
    ai_models = [_ai_provider_model(provider_name, source) for provider_name in ai_provider_chain]
    ai_model = " > ".join(ai_models) if ai_models else source.get("FISORA_AI_MODEL", "").strip()
    openai_key_present = bool(source.get("OPENAI_API_KEY", "").strip())
    groq_key_present = bool(source.get("GROQ_API_KEY", "").strip())
    openrouter_key_present = bool(source.get("OPENROUTER_API_KEY", "").strip())
    cerebras_key_present = bool(source.get("CEREBRAS_API_KEY", "").strip())
    if not ai_provider_chain:
        ai_provider_configured = True
    else:
        ai_provider_configured = all(
            provider_name in supported_ai_providers
            and _ai_provider_key_present(provider_name, source)
            and _ai_provider_model(provider_name, source)
            for provider_name in ai_provider_chain
        )
    auth = auth_status_payload(build_auth_config(source))
    rate_limit = rate_limit_config(source)
    document_storage = storage_readiness(
        base_dir=document_storage_path,
        backend=source.get("FISORA_DOCUMENT_STORAGE_BACKEND", "local"),
    )
    export_storage = storage_readiness(
        base_dir=export_path,
        backend="local",
    )
    backup = backup_health(backup_path=backup_path)
    storage_usage = storage_usage_health(
        document_path=document_storage_path,
        export_path=export_path,
        backup_path=backup_path,
    )
    store_backend = source.get("FISORA_STORE_BACKEND", "json").strip().lower() or "json"
    database_configured = bool(source.get("DATABASE_URL") or source.get("FISORA_DATABASE_URL"))
    adapters = [
        {
            "export_type": adapter.export_type,
            "display_name": adapter.display_name,
            "verified_in_zirve": adapter.verified_in_zirve,
            "validation_status": adapter.validation_status,
        }
        for adapter in SUPPORTED_EXPORT_ADAPTERS.values()
    ]
    zirve_mapping_adapter_available = "zirve_mapping_csv" in SUPPORTED_EXPORT_ADAPTERS
    zirve_field_test_pending = any(
        adapter.validation_status == "field_test_pending" for adapter in SUPPORTED_EXPORT_ADAPTERS.values()
    )
    session_required_active = auth["auth_mode"] == "session_required"
    session_cookie_secure = source.get("FISORA_SESSION_COOKIE_SECURE", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    real_data_pilot_enabled = _env_bool(source.get("FISORA_REAL_DATA_PILOT_ENABLED", ""), default=False)
    real_data_access_mode = source.get("FISORA_REAL_DATA_ACCESS_MODE", "").strip().lower()
    restricted_live_access = real_data_access_mode in {"tls", "restricted_network", "vpn", "ip_allowlist"}
    checks = {
        "auth_not_anonymous": not bool(auth["allows_anonymous_access"]),
        "document_storage_writable": bool(document_storage["ok"]),
        "export_storage_writable": bool(export_storage["ok"]),
        "postgres_configured": (store_backend != "postgres") or database_configured,
        "ai_provider_configured": ai_provider_configured,
        "zirve_verified_adapter_available": any(adapter.verified_in_zirve for adapter in SUPPORTED_EXPORT_ADAPTERS.values()),
        "zirve_mapping_adapter_available": zirve_mapping_adapter_available,
        "session_required_active": session_required_active,
        "session_cookie_secure": session_cookie_secure,
        "rate_limit_configured": rate_limit.configured,
    }
    blocking = [
        key
        for key, passed in checks.items()
        if not passed
        and key
        not in {
            "zirve_verified_adapter_available",
            "session_required_active",
            "session_cookie_secure",
            "rate_limit_configured",
        }
    ]
    warnings = []
    if not checks["zirve_verified_adapter_available"]:
        warnings.append("zirve_verified_adapter_missing")
    if zirve_field_test_pending:
        warnings.append("zirve_field_test_pending")
    if not session_required_active:
        warnings.append("session_required_missing")
    if not session_cookie_secure:
        warnings.append("session_cookie_secure_missing")
    if not rate_limit.configured:
        warnings.append("rate_limit_missing")
    if not ai_provider_chain:
        warnings.append("ai_provider_disabled")
    for provider_name in ai_provider_chain:
        if provider_name not in supported_ai_providers:
            warnings.append("ai_provider_unsupported")
            continue
        if not _ai_provider_key_present(provider_name, source):
            warnings.append(f"ai_{provider_name}_key_missing")
        if not _ai_provider_model(provider_name, source):
            warnings.append("ai_model_missing")
    if not backup["ok"]:
        warnings.append("backup_missing")
    if storage_usage["disk_warning"]:
        warnings.append("disk_usage_high")
    controlled_export_available = {
        "zirve_universal_csv",
        "zirve_mapping_csv",
        "json_manifest",
    }.issubset(SUPPORTED_EXPORT_ADAPTERS)
    pilot_checks = {
        "auth_requires_user": bool(auth["requires_portal_user"]),
        "auth_not_anonymous": not bool(auth["allows_anonymous_access"]),
        "session_auth_available": True,
        "postgres_store_active": store_backend == "postgres" and database_configured,
        "document_storage_writable": bool(document_storage["ok"]),
        "export_storage_writable": bool(export_storage["ok"]),
        "backup_available": bool(backup["ok"]),
        "ai_provider_configured": ai_provider_configured,
        "controlled_export_available": controlled_export_available,
    }
    pilot_blocking = [key for key, passed in pilot_checks.items() if not passed]
    pilot_sellable = not pilot_blocking
    real_data_pilot_checks = {
        "explicit_real_data_enable": real_data_pilot_enabled,
        "pilot_sellable": pilot_sellable,
        "restricted_live_access": restricted_live_access,
        "session_required_active": session_required_active,
        "session_cookie_secure": session_cookie_secure,
        "rate_limit_configured": rate_limit.configured,
        "postgres_store_active": bool(pilot_checks["postgres_store_active"]),
        "document_storage_writable": bool(document_storage["ok"]),
        "export_storage_writable": bool(export_storage["ok"]),
        "backup_available": bool(backup["ok"]),
        "ai_provider_configured": ai_provider_configured,
        "controlled_export_available": controlled_export_available,
    }
    real_data_pilot_blocking = [key for key, passed in real_data_pilot_checks.items() if not passed]
    real_data_pilot_allowed = not real_data_pilot_blocking
    production_ready = (
        not blocking
        and bool(auth["production_ready"])
        and session_required_active
        and session_cookie_secure
        and rate_limit.configured
        and bool(checks["zirve_verified_adapter_available"])
    )
    commercial_readiness = {
        "status": "pilot_sellable" if pilot_sellable else "blocked",
        "primary_offer": "accountant_reviewed_controlled_export",
        "pilot_sellable": pilot_sellable,
        "production_ready": production_ready,
        "requires_accountant_review": True,
        "export_positioning": "controlled_csv_and_manifest_candidate",
        "zirve_import_claim": "unverified_until_field_test",
    }
    real_data_pilot = {
        "status": "ready_for_restricted_live_pilot" if real_data_pilot_allowed else "blocked",
        "allowed": real_data_pilot_allowed,
        "access_mode": real_data_access_mode or "unset",
        "blocking": real_data_pilot_blocking,
        "checks": real_data_pilot_checks,
    }
    return {
        "ready": not blocking,
        "pilot_sellable": pilot_sellable,
        "production_ready": production_ready,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
        "pilot_checks": pilot_checks,
        "pilot_blocking": pilot_blocking,
        "commercial_readiness": commercial_readiness,
        "real_data_pilot": real_data_pilot,
        "auth": auth,
        "document_storage": document_storage,
        "export_storage": export_storage,
        "backup": backup,
        "storage_usage": storage_usage,
        "store_backend": store_backend,
        "ai_provider": ai_provider,
        "ai_provider_chain": ai_provider_chain,
        "ai_model": ai_model,
        "ai_openai_key_present": openai_key_present,
        "ai_groq_key_present": groq_key_present,
        "ai_openrouter_key_present": openrouter_key_present,
        "ai_cerebras_key_present": cerebras_key_present,
        "rate_limit": {
            "enabled": rate_limit.enabled,
            "window_seconds": rate_limit.window_seconds,
            "ai_max_requests": rate_limit.ai_max_requests,
            "export_max_requests": rate_limit.export_max_requests,
        },
        "export_adapters": adapters,
    }
