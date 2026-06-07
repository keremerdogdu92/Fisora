from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from app.domain.auth_policy import auth_status_payload, build_auth_config
from app.domain.export_adapters import SUPPORTED_EXPORT_ADAPTERS
from app.domain.openai_provider import DEFAULT_GROQ_MODEL, DEFAULT_OPENAI_MODEL
from app.domain.storage_adapters import storage_readiness
from app.domain.system_health import backup_health, storage_usage_health


def production_readiness_payload(
    *,
    document_storage_path: Path | str,
    export_path: Path | str,
    backup_path: Path | str,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    source = env if env is not None else os.environ
    ai_provider = source.get("FISORA_AI_PROVIDER", "disabled").strip().lower() or "disabled"
    configured_ai_model = source.get("FISORA_AI_MODEL", "").strip()
    if ai_provider == "openai":
        ai_model = configured_ai_model or DEFAULT_OPENAI_MODEL
    elif ai_provider == "groq":
        ai_model = configured_ai_model or DEFAULT_GROQ_MODEL
    else:
        ai_model = configured_ai_model
    openai_key_present = bool(source.get("OPENAI_API_KEY", "").strip())
    groq_key_present = bool(source.get("GROQ_API_KEY", "").strip())
    if ai_provider == "disabled":
        ai_provider_configured = True
    elif ai_provider == "openai":
        ai_provider_configured = bool(openai_key_present and ai_model)
    elif ai_provider == "groq":
        ai_provider_configured = bool(groq_key_present and ai_model)
    else:
        ai_provider_configured = False
    auth = auth_status_payload(build_auth_config(source))
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
    adapters = [
        {
            "export_type": adapter.export_type,
            "display_name": adapter.display_name,
            "verified_in_zirve": adapter.verified_in_zirve,
            "validation_status": adapter.validation_status,
        }
        for adapter in SUPPORTED_EXPORT_ADAPTERS.values()
    ]
    checks = {
        "auth_not_anonymous": not bool(auth["allows_anonymous_access"]),
        "document_storage_writable": bool(document_storage["ok"]),
        "export_storage_writable": bool(export_storage["ok"]),
        "postgres_configured": (source.get("FISORA_STORE_BACKEND", "json").lower() != "postgres")
        or bool(source.get("DATABASE_URL") or source.get("FISORA_DATABASE_URL")),
        "ai_provider_configured": ai_provider_configured,
        "zirve_verified_adapter_available": any(adapter.verified_in_zirve for adapter in SUPPORTED_EXPORT_ADAPTERS.values()),
    }
    blocking = [
        key
        for key, passed in checks.items()
        if not passed and key != "zirve_verified_adapter_available"
    ]
    warnings = []
    if not checks["zirve_verified_adapter_available"]:
        warnings.append("zirve_verified_adapter_missing")
    if ai_provider == "disabled":
        warnings.append("ai_provider_disabled")
    elif ai_provider == "openai" and not openai_key_present:
        warnings.append("ai_openai_key_missing")
    elif ai_provider == "groq" and not groq_key_present:
        warnings.append("ai_groq_key_missing")
    elif ai_provider == "openai" and not ai_model:
        warnings.append("ai_model_missing")
    elif ai_provider == "groq" and not ai_model:
        warnings.append("ai_model_missing")
    elif ai_provider not in {"openai", "groq", "disabled"}:
        warnings.append("ai_provider_unsupported")
    if not backup["ok"]:
        warnings.append("backup_missing")
    if storage_usage["disk_warning"]:
        warnings.append("disk_usage_high")
    return {
        "ready": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
        "auth": auth,
        "document_storage": document_storage,
        "export_storage": export_storage,
        "backup": backup,
        "storage_usage": storage_usage,
        "store_backend": source.get("FISORA_STORE_BACKEND", "json"),
        "ai_provider": ai_provider,
        "ai_model": ai_model,
        "ai_openai_key_present": openai_key_present,
        "ai_groq_key_present": groq_key_present,
        "export_adapters": adapters,
    }
