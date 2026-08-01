from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata


DIRECTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "provider_directory.v1.json"


@dataclass(frozen=True)
class ProviderProfileMatch:
    provider_id: str = ""
    service_profile: str = ""
    match_kind: str = ""
    reason_code: str = "unknown_provider"
    directory_version: int = 0


def _normalized_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", "", normalized.upper())


def _directory() -> tuple[int, tuple[dict[str, object], ...]]:
    payload = json.loads(DIRECTORY_PATH.read_text(encoding="utf-8"))
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise ValueError("provider_directory_providers_missing")
    version = int(payload.get("version") or 0)
    seen_tax_ids: set[str] = set()
    records: list[dict[str, object]] = []
    for provider in providers:
        if not isinstance(provider, dict):
            raise ValueError("provider_directory_record_invalid")
        for tax_id in provider.get("tax_ids") or []:
            value = str(tax_id)
            if value in seen_tax_ids:
                raise ValueError(f"provider_directory_duplicate_tax_id:{value}")
            seen_tax_ids.add(value)
        records.append(provider)
    return version, tuple(records)


def resolve_provider_profile(*, supplier_tax_id: str, supplier_title: str, source: str) -> ProviderProfileMatch:
    version, providers = _directory()
    tax_id = re.sub(r"\D", "", supplier_tax_id)
    for provider in providers:
        if tax_id and tax_id in {str(value) for value in provider.get("tax_ids") or []}:
            return ProviderProfileMatch(
                provider_id=str(provider["provider_id"]),
                service_profile=str(provider["service_profile"]),
                match_kind="vkn",
                reason_code="",
                directory_version=version,
            )

    if source == "xml" and not tax_id:
        return ProviderProfileMatch(reason_code="ubl_supplier_vkn_missing", directory_version=version)

    normalized_title = _normalized_title(supplier_title)
    for provider in providers:
        titles = {_normalized_title(str(value)) for value in provider.get("titles") or []}
        if normalized_title and normalized_title in titles:
            return ProviderProfileMatch(
                provider_id=str(provider["provider_id"]),
                service_profile=str(provider["service_profile"]),
                match_kind="title",
                reason_code="",
                directory_version=version,
            )
    return ProviderProfileMatch(directory_version=version)
