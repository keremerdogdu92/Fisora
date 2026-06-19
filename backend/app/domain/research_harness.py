from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import asyncio
import json
import re
from typing import Any, Protocol
from urllib.parse import urlparse

from app.domain.brand_research import normalize_brand_name
from app.domain.nace_research import normalize_nace_code


@dataclass(frozen=True)
class ResearchPolicy:
    enabled: bool = False
    confidence_threshold: int = 70
    max_per_document: int = 1
    source_policy: str = "official_or_manufacturer"


@dataclass(frozen=True)
class ResearchQuery:
    kind: str
    key: str
    search_text: str
    supplier_hint: str = ""
    activity_context: str = ""
    source_policy: str = "official_or_manufacturer"


class ResearchProvider(Protocol):
    provider_name: str

    def research(self, query: ResearchQuery) -> dict[str, Any]:
        ...


MARKETPLACE_HOST_PARTS = (
    "amazon.",
    "trendyol.",
    "hepsiburada.",
    "n11.",
    "ciceksepeti.",
    "aliexpress.",
    "etsy.",
)

REJECTED_HOST_PARTS = (
    "blog.",
    "medium.",
    "reddit.",
    "sikayetvar.",
    "eksisozluk.",
)

OFFICIAL_HOST_PARTS = (
    ".gov",
    ".gov.tr",
    "gib.gov.tr",
    "ticaret.gov.tr",
    "ec.europa.eu",
    "eurostat",
)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _future_timestamp(days: int = 365) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat(timespec="seconds")


def sanitize_research_query(
    *,
    kind: str,
    raw_line: str,
    supplier_hint: str = "",
    activity_context: str = "",
) -> ResearchQuery:
    cleaned_line = _sanitize_text(raw_line)
    cleaned_supplier = _sanitize_supplier(supplier_hint)
    key = cleaned_line.split(" ")[0] if cleaned_line else cleaned_supplier.split(" ")[0] if cleaned_supplier else ""
    return ResearchQuery(
        kind=kind,
        key=key,
        search_text=cleaned_line,
        supplier_hint=cleaned_supplier,
        activity_context=_sanitize_text(activity_context),
    )


def _sanitize_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\b(?:VKN|TCKN|ETTN|Fatura|No)\s*[:#-]?\s*[A-Z0-9]{8,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{10,11}\b", " ", text)
    text = re.sub(r"\b[A-Z]{2,}\d{8,}\b", " ", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", " ", text)
    text = re.sub(r"\b\d+[.,]\d{2}\s*(?:TL|TRY)?\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def _sanitize_supplier(value: str) -> str:
    text = _sanitize_text(value)
    text = re.sub(r"\b\w+\s+(?:cad|cadde|sok|sokak|mah|mahalle)\.?.*$", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:no|kat|daire)\s*[:#-]?\s*\d+\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def source_policy_accepts(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if any(part in host for part in MARKETPLACE_HOST_PARTS):
        return False
    if any(part in host for part in REJECTED_HOST_PARTS):
        return False
    if any(part in host for part in OFFICIAL_HOST_PARTS):
        return True
    return True


def normalize_research_profile(*, kind: str, key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    source = payload or {}
    normalized_key = normalize_nace_code(key) if kind == "nace" else normalize_brand_name(key)
    evidence = [_normalize_evidence(item) for item in source.get("evidence") or [] if isinstance(item, dict)]
    source_urls = [item["url"] for item in evidence if item.get("accepted")]
    fallback_urls = [str(item).strip() for item in source.get("source_urls") or [] if str(item).strip()]
    if not source_urls:
        source_urls = [url for url in fallback_urls if source_policy_accepts(url)]
    categories = source.get("category_tags") or source.get("common_product_categories") or source.get("activity_tags") or []
    summary = str(source.get("summary_tr") or source.get("brand_summary") or source.get("scope_summary") or "").strip()
    normalized_categories = [str(item).strip() for item in categories if str(item).strip()]
    return {
        "kind": kind,
        "key": normalized_key,
        "normalized_key": normalized_key,
        "brand_name": normalized_key if kind == "brand" else "",
        "nace_code": normalized_key if kind == "nace" else "",
        "display_name": str(source.get("display_name") or key or normalized_key).strip(),
        "summary": summary,
        "summary_tr": summary,
        "brand_summary": str(source.get("brand_summary") or source.get("summary_tr") or "").strip(),
        "scope_summary": str(source.get("scope_summary") or source.get("summary_tr") or "").strip(),
        "product_category": normalized_categories[0] if normalized_categories else "",
        "common_product_categories": normalized_categories,
        "activity_tags": [str(item).strip() for item in source.get("activity_tags") or [] if str(item).strip()],
        "confidence": _int_between(source.get("confidence"), 0, 100),
        "evidence": evidence,
        "sources": evidence,
        "source_urls": source_urls,
        "source_policy": str(source.get("source_policy") or "official_or_manufacturer"),
        "override": bool(source.get("override")),
        "researched_at": str(source.get("researched_at") or _timestamp()),
        "expires_at": str(source.get("expires_at") or _future_timestamp()),
    }


def _normalize_evidence(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or "").strip()
    accepted = source_policy_accepts(url)
    return {
        "url": url,
        "title": str(item.get("title") or "").strip(),
        "source_type": str(item.get("source_type") or ("official_or_manufacturer" if accepted else "rejected")).strip(),
        "summary_tr": str(item.get("summary_tr") or item.get("summary") or "").strip(),
        "accepted": accepted,
    }


def _int_between(value: object, floor: int, ceiling: int) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(floor, min(ceiling, parsed))


def apply_research_to_result(
    result: dict[str, Any],
    profile: dict[str, Any],
    *,
    confidence_threshold: int = 70,
) -> dict[str, Any]:
    updated = dict(result)
    updated["research_profile"] = profile
    review_reason_codes = list(updated.get("review_reason_codes") or [])
    risk_flags = list(updated.get("risk_flags") or [])
    accepted_sources = [item for item in profile.get("evidence") or [] if item.get("accepted")] or profile.get("source_urls")
    if int(profile.get("confidence") or 0) < confidence_threshold:
        _append_unique(review_reason_codes, "research_low_confidence")
        _append_unique(risk_flags, "research_low_confidence")
    if not accepted_sources:
        _append_unique(review_reason_codes, "research_source_rejected")
        _append_unique(risk_flags, "research_source_rejected")
    if "research_low_confidence" in review_reason_codes or "research_source_rejected" in review_reason_codes:
        updated["export_status"] = "review_required"
        updated["simulated_status"] = "review_required"
    updated["review_reason_codes"] = review_reason_codes
    updated["risk_flags"] = risk_flags
    return updated


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


class ResearchHarness:
    def __init__(self, *, store: Any, provider: ResearchProvider | None, policy: ResearchPolicy | None = None) -> None:
        self.store = store
        self.provider = provider
        self.policy = policy or ResearchPolicy()
        self.call_count = 0

    def research_brand(self, *, raw_line: str, supplier_hint: str = "", activity_context: str = "") -> dict[str, Any]:
        query = sanitize_research_query(
            kind="brand",
            raw_line=raw_line,
            supplier_hint=supplier_hint,
            activity_context=activity_context,
        )
        key = query.search_text.split(" ")[0] if query.search_text else query.key
        if hasattr(self.store, "get_brand_research_profile"):
            cached = self.store.get_brand_research_profile(key)
            if cached:
                return normalize_research_profile(kind="brand", key=key, payload=cached)
        return self._research_and_store(query=query, key=key)

    def _research_and_store(self, *, query: ResearchQuery, key: str) -> dict[str, Any]:
        if not self.policy.enabled or self.provider is None or self.call_count >= self.policy.max_per_document:
            return normalize_research_profile(kind=query.kind, key=key, payload={})
        self.call_count += 1
        payload = self.provider.research(query)
        profile = normalize_research_profile(kind=query.kind, key=key, payload=payload)
        if query.kind == "brand" and hasattr(self.store, "save_brand_research_profile"):
            return self.store.save_brand_research_profile(brand_name=key, profile=profile)
        if query.kind == "nace" and hasattr(self.store, "save_nace_research_profile"):
            return self.store.save_nace_research_profile(nace_code=key, profile=profile)
        return profile


class OpenAIAgentsResearchProvider:
    provider_name = "openai_agents_research"

    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def research(self, query: ResearchQuery) -> dict[str, Any]:
        try:
            from agents import Agent, Runner, WebSearchTool  # type: ignore
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("openai-agents package is required for research runtime") from exc
        instructions = (
            "Muhasebe otomasyonu icin marka/NACE arastirmasi yap. "
            "Sadece resmi kurum, uretici/marka sitesi, teknik katalog veya guvenilir sektor kaynagi kullan. "
            "Pazaryeri, blog, forum ve SEO icerigini reddet. "
            "Yalnizca JSON obje don: display_name, summary_tr, common_product_categories, activity_tags, "
            "confidence, evidence[{url,title,source_type,summary_tr}]."
        )
        agent = Agent(
            name="Fisora Research Agent",
            instructions=instructions,
            model=self.model,
            tools=[WebSearchTool()],
        )
        prompt = json.dumps(
            {
                "kind": query.kind,
                "search_text": query.search_text,
                "supplier_hint": query.supplier_hint,
                "activity_context": query.activity_context,
                "source_policy": query.source_policy,
            },
            ensure_ascii=False,
        )
        result = asyncio.run(Runner.run(agent, prompt))
        output = getattr(result, "final_output", result)
        return json.loads(str(output)) if isinstance(output, str) else dict(output)


def build_research_runtime_from_env(env: dict[str, str] | Any) -> dict[str, object] | None:
    enabled = str(env.get("FISORA_RESEARCH_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}
    api_key = str(env.get("OPENAI_API_KEY", "")).strip()
    if not enabled or not api_key:
        return None
    policy = ResearchPolicy(
        enabled=True,
        confidence_threshold=_int_between(env.get("FISORA_RESEARCH_CONFIDENCE_THRESHOLD", 70), 0, 100),
        max_per_document=max(1, _int_between(env.get("FISORA_RESEARCH_MAX_PER_DOCUMENT", 1), 1, 10)),
    )
    provider = OpenAIAgentsResearchProvider(
        api_key=api_key,
        model=str(env.get("FISORA_RESEARCH_MODEL", "")).strip() or "gpt-5.4-mini",
    )
    return {"provider": provider, "policy": policy}
