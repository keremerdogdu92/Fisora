from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import asyncio
from hashlib import sha256
import json
import re
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import httpx

from app.domain.ai_capacity import looks_like_openai_api_key
from app.domain.brand_research import normalize_brand_name
from app.domain.business_relevance import account_treatment_for_category, build_activity_profile
from app.domain.nace_research import normalize_nace_code
from app.domain.product_research_cache import (
    non_authoritative_research_payload,
    normalize_product_research_key,
    research_cache_provenance,
)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


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
    canonical_line_ids: tuple[str, ...] = ()


class ResearchProvider(Protocol):
    provider_name: str

    def research(self, query: ResearchQuery) -> dict[str, Any]:
        ...


MARKETPLACE_DOMAINS = (
    "amazon.com",
    "amazon.com.tr",
    "trendyol.com",
    "hepsiburada.com",
    "n11.com",
    "ciceksepeti.com",
    "aliexpress.com",
    "etsy.com",
)

REJECTED_DOMAINS = (
    "medium.com",
    "reddit.com",
    "sikayetvar.com",
    "eksisozluk.com",
)

OFFICIAL_DOMAINS = (
    "gov",
    "gov.tr",
    "gib.gov.tr",
    "ticaret.gov.tr",
    "ec.europa.eu",
    "eurostat.ec.europa.eu",
)

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+\s*)?\d{1,3}(?:[\s().-]*\d){7,14}(?!\w)")


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
    canonical_line_ids: tuple[str, ...] | list[str] = (),
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
        canonical_line_ids=tuple(_canonical_line_ids(canonical_line_ids)),
    )


def research_brand_cache_key(query: ResearchQuery, *, cache_scope: str = "") -> str:
    namespace = {
        "kind": "brand",
        "lookup": normalize_product_research_key(query.search_text or query.key),
        "supplier": normalize_product_research_key(query.supplier_hint),
        "activity": normalize_product_research_key(query.activity_context),
        "scope_digest": sha256(str(cache_scope or "").encode("utf-8")).hexdigest(),
    }
    digest = sha256(
        json.dumps(namespace, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ctxv2{digest[:32]}"


def _sanitize_text(value: str) -> str:
    text = str(value or "")
    text = EMAIL_PATTERN.sub(" ", text)
    text = re.sub(r"\b(?:VKN|TCKN|ETTN|Fatura|No)\s*[:#-]?\s*[A-Z0-9]{8,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{10,11}\b", " ", text)
    text = re.sub(r"\b[A-Z]{2,}\d{8,}\b", " ", text)
    text = PHONE_PATTERN.sub(" ", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", " ", text)
    text = re.sub(r"\b\d+[.,]\d{2}\s*(?:TL|TRY)?\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def _safe_research_text(value: object, *, limit: int = 1000) -> str:
    return _sanitize_text(str(value or ""))[:limit]


def _canonical_line_ids(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _sanitize_supplier(value: str) -> str:
    text = _sanitize_text(value)
    text = re.sub(r"\b\w+\s+(?:cad|cadde|sok|sokak|mah|mahalle)\.?.*$", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:no|kat|daire)\s*[:#-]?\s*\d+\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def source_policy_accepts(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = _normalized_hostname(url)
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        return False
    if any(_domain_matches(host, domain) for domain in MARKETPLACE_DOMAINS):
        return False
    if any(_domain_matches(host, domain) for domain in REJECTED_DOMAINS):
        return False
    if "blog" in host.split("."):
        return False
    if any(domain in host and not _domain_matches(host, domain) for domain in OFFICIAL_DOMAINS):
        return False
    return True


RESEARCH_SOURCE_KINDS = frozenset({"official", "manufacturer", "retailer", "other"})


def _source_domain(url: str) -> str:
    return _normalized_hostname(url).removeprefix("www.")


def _normalized_hostname(value: object) -> str:
    try:
        hostname = urlparse(str(value or "").strip()).hostname or ""
        return hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except (UnicodeError, ValueError):
        return ""


def _domain_matches(host: str, domain: str) -> bool:
    normalized_domain = str(domain or "").lower().rstrip(".")
    return host == normalized_domain or host.endswith(f".{normalized_domain}")


def _is_official_domain(host: str) -> bool:
    return any(_domain_matches(host, domain) for domain in OFFICIAL_DOMAINS)


def _safe_source_url(value: object) -> str:
    parsed = urlparse(str(value or "").strip())
    host = _normalized_hostname(value)
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = f"{host}:{port}" if port is not None else host
    decoded_path = unquote(parsed.path or "")
    sensitive_path = (
        EMAIL_PATTERN.search(decoded_path)
        or PHONE_PATTERN.search(decoded_path)
        or re.search(r"(?i)(?:^|/)(?:token|api[-_]?key|secret|password)(?:/|=|$)", decoded_path)
        or re.search(r"(?:^|/)[0-9]{7,}(?:/|$)", decoded_path)
        or re.search(r"(?:^|/)[A-Za-z0-9_-]{24,}(?:/|$)", decoded_path)
    )
    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        path="/" if sensitive_path else parsed.path,
        params="",
        query="",
        fragment="",
    ).geturl()


def _trusted_override(source: dict[str, Any]) -> bool:
    provenance = source.get("override_provenance")
    return bool(
        source.get("override") is True
        and isinstance(provenance, dict)
        and provenance.get("source") == "accountant"
        and str(provenance.get("actor_id") or "").strip()
    )


def research_profile_is_fresh(profile: dict[str, Any]) -> bool:
    expires_at = str(profile.get("expires_at") or "").strip()
    if not expires_at:
        return False
    try:
        parsed = datetime.fromisoformat(expires_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return datetime.now(UTC) < parsed
    except ValueError:
        return False


def _source_kind(item: dict[str, Any], *, url: str) -> str:
    requested = str(item.get("source_kind") or item.get("source_type") or "").strip().lower()
    aliases = {
        "official_or_manufacturer": "manufacturer",
        "brand": "manufacturer",
        "marketplace": "retailer",
        "search_result": "other",
    }
    requested = aliases.get(requested, requested)
    host = _source_domain(url)
    if _is_official_domain(host):
        return "official"
    return requested if requested in RESEARCH_SOURCE_KINDS else "other"


def normalize_research_profile(*, kind: str, key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    source = non_authoritative_research_payload(payload)
    normalized_key = normalize_nace_code(key) if kind == "nace" else normalize_brand_name(key)
    raw_evidence = [item for item in source.get("evidence") or [] if isinstance(item, dict)]
    if not raw_evidence:
        raw_evidence = [
            {"url": str(url), "source_type": "other"}
            for url in source.get("source_urls") or []
            if str(url).strip()
        ]
    evidence = [_normalize_evidence(item) for item in raw_evidence]
    source_urls = [item["url"] for item in evidence if item.get("accepted")]
    fallback_urls = [
        _safe_source_url(item)
        for item in source.get("source_urls") or []
        if _safe_source_url(item)
    ]
    if not source_urls:
        source_urls = [url for url in fallback_urls if source_policy_accepts(url)]
    display_source = (
        dict(source.get("non_authoritative_display") or {})
        if isinstance(source.get("non_authoritative_display"), dict)
        else {}
    )
    categories = source.get("category_tags") or source.get("common_product_categories") or source.get("activity_tags") or []
    summary = _safe_research_text(
        source.get("summary_tr") or source.get("brand_summary") or source.get("scope_summary") or "",
        limit=1000,
    )
    normalized_categories = [str(item).strip() for item in categories if str(item).strip()]
    if not normalized_categories and str(display_source.get("product_category") or "").strip():
        normalized_categories = [str(display_source.get("product_category") or "").strip()]
    research_confidence = _research_confidence(source, summary=summary, categories=normalized_categories, source_urls=source_urls)
    account_treatment = str(display_source.get("account_treatment") or "").strip()
    if not account_treatment and normalized_categories:
        account_treatment = account_treatment_for_category(normalized_categories[0])
    accounting_impact_confidence = _accounting_impact_confidence(
        source,
        research_confidence=research_confidence,
        categories=normalized_categories,
        account_treatment=account_treatment,
    )
    question = _safe_research_text(source.get("question") or source.get("search_text") or key, limit=240)
    canonical_line_ids = _canonical_line_ids(source.get("canonical_line_ids"))
    raw_conflicts = source.get("conflicts") if isinstance(source.get("conflicts"), (list, tuple)) else ()
    conflicts = [
        _safe_research_text(item, limit=500)
        for item in raw_conflicts
        if _safe_research_text(item, limit=500)
    ][:10]
    scoped_evidence = [
        _research_evidence_item(
            item,
            question=question,
            canonical_line_ids=canonical_line_ids,
            conflicts=conflicts,
        )
        for item in evidence
        if item.get("url")
        and item.get("source_domain")
        and (item.get("claim") or item.get("summary_tr"))
    ]
    evidence_gaps: list[str] = []
    if not canonical_line_ids:
        evidence_gaps.append("line-missing")
        research_evidence: list[dict[str, Any]] = []
    else:
        research_evidence = scoped_evidence
        if not research_evidence:
            evidence_gaps.append("insufficient-evidence")
        elif not any(item.get("accepted") for item in research_evidence):
            evidence_gaps.append("source-rejected")
    cache_provenance = (
        dict(source.get("cache_provenance") or {})
        if isinstance(source.get("cache_provenance"), dict)
        else {}
    )
    return {
        "kind": kind,
        "key": normalized_key,
        "normalized_key": normalized_key,
        "profile_id": str(source.get("profile_id") or source.get("cache_key") or normalized_key),
        "display_key": str(source.get("display_key") or normalized_key),
        "tenant_id": str(source.get("tenant_id") or source.get("client_id") or ""),
        "client_id": str(source.get("client_id") or ""),
        "owner_client_id": str(source.get("owner_client_id") or source.get("client_id") or ""),
        "scope_type": str(
            source.get("scope_type")
            or ("client_private" if source.get("client_id") else "office_public" if kind == "nace" else "legacy_unowned")
        ),
        "brand_name": normalized_key if kind == "brand" else "",
        "nace_code": normalized_key if kind == "nace" else "",
        "display_name": str(source.get("display_name") or key or normalized_key).strip(),
        "summary": summary,
        "summary_tr": summary,
        "brand_summary": _safe_research_text(source.get("brand_summary") or source.get("summary_tr") or "", limit=1000),
        "scope_summary": _safe_research_text(source.get("scope_summary") or source.get("summary_tr") or "", limit=1000),
        "common_product_categories": normalized_categories,
        "activity_tags": [str(item).strip() for item in source.get("activity_tags") or [] if str(item).strip()],
        "confidence": research_confidence,
        "research_confidence": research_confidence,
        "accounting_impact_confidence": accounting_impact_confidence,
        "authority": "evidence_only",
        "non_authoritative_display": {
            "product_category": normalized_categories[0] if normalized_categories else "",
            "account_treatment": account_treatment,
        },
        "question": question,
        "canonical_line_ids": canonical_line_ids,
        "research_evidence": research_evidence,
        "evidence_gaps": evidence_gaps,
        "conflicts": conflicts,
        "evidence": evidence,
        "sources": evidence,
        "source_urls": source_urls,
        "source_policy": str(source.get("source_policy") or "official_or_manufacturer"),
        "cache_provenance": cache_provenance,
        "override": _trusted_override(source),
        "override_actor": str(source.get("override_actor") or "") if _trusted_override(source) else "",
        "override_provenance": dict(source.get("override_provenance") or {}) if _trusted_override(source) else {},
        "accountant_override": dict(source.get("accountant_override") or {}) if _trusted_override(source) else {},
        "researched_at": str(source.get("researched_at") or _timestamp()),
        "expires_at": str(source.get("expires_at") or _future_timestamp()),
    }


def _research_confidence(
    source: dict[str, Any],
    *,
    summary: str,
    categories: list[str],
    source_urls: list[str],
) -> int:
    explicit = source.get("research_confidence")
    if explicit is None and source.get("confidence") is not None:
        explicit = source.get("confidence")
    if explicit is not None:
        return _int_between(explicit, 0, 100)
    if source_urls and summary and categories:
        return 85
    if source_urls and summary:
        return 75
    if source_urls:
        return 65
    return 40


def _accounting_impact_confidence(
    source: dict[str, Any],
    *,
    research_confidence: int,
    categories: list[str],
    account_treatment: str,
) -> int:
    explicit = source.get("accounting_impact_confidence")
    if explicit is not None:
        return _int_between(explicit, 0, 100)
    if research_confidence < 70 or not categories:
        return 40
    if account_treatment in {"stock_or_cogs", "expense"}:
        return 90
    if account_treatment in {"fixed_asset_review", "non_deductible_review"}:
        return 80
    return 60


def _normalize_evidence(item: dict[str, Any]) -> dict[str, Any]:
    url = _safe_source_url(item.get("url"))
    accepted = source_policy_accepts(url)
    summary = _safe_research_text(item.get("summary_tr") or item.get("summary"), limit=1000)
    raw_summary = _safe_research_text(item.get("raw_summary") or item.get("summary_tr") or item.get("summary"), limit=1000)
    # A page title identifies a source but does not substantiate a factual claim.
    claim = _safe_research_text(item.get("claim") or summary, limit=500)
    return {
        "url": url,
        "title": _safe_research_text(item.get("title"), limit=300),
        "source_type": _safe_research_text(
            item.get("source_type") or item.get("source_kind") or "other",
            limit=64,
        ),
        "source_kind": _source_kind(item, url=url),
        "source_domain": _source_domain(url),
        "claim": claim,
        "summary_tr": summary,
        "raw_summary": raw_summary,
        "confidence": _int_between(item.get("confidence"), 0, 100) if item.get("confidence") is not None else None,
        "accepted": accepted and bool(claim or summary),
    }


def _research_evidence_item(
    item: dict[str, Any],
    *,
    question: str,
    canonical_line_ids: list[str],
    conflicts: list[str],
) -> dict[str, Any]:
    confidence = item.get("confidence")
    claim = {
        "claim": str(item.get("claim") or item.get("summary_tr") or ""),
        "source_url": str(item.get("url") or ""),
        "source_domain": str(item.get("source_domain") or ""),
        "source_kind": str(item.get("source_kind") or "other"),
        "evidence_summary": str(item.get("summary_tr") or ""),
        "confidence": _int_between(0 if confidence is None else confidence, 0, 100),
    }
    return {
        "question": question,
        "canonical_line_ids": list(canonical_line_ids),
        "claims": [claim],
        "conflicts": list(conflicts),
        "source_url": claim["source_url"],
        "source_domain": claim["source_domain"],
        "source_kind": claim["source_kind"],
        "evidence_summary": claim["evidence_summary"],
        "confidence": claim["confidence"],
        "accepted": bool(item.get("accepted")),
        "quality": "accepted" if item.get("accepted") else "rejected",
        "raw_summary": str(item.get("raw_summary") or item.get("summary_tr") or ""),
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
    updated["research_evidence"] = list(profile.get("research_evidence") or [])
    updated["research_evidence_gaps"] = list(profile.get("evidence_gaps") or [])
    updated["research_quality"] = {
        "research_confidence": int(profile.get("research_confidence") or profile.get("confidence") or 0),
        "accounting_impact_confidence": int(profile.get("accounting_impact_confidence") or 0),
        "confidence_threshold": int(confidence_threshold),
        "accepted_source_count": sum(
            1 for item in profile.get("research_evidence") or [] if isinstance(item, dict) and item.get("accepted")
        ),
        "conflicts": list(profile.get("conflicts") or []),
    }
    return updated


class ResearchHarness:
    def __init__(self, *, store: Any, provider: ResearchProvider | None, policy: ResearchPolicy | None = None) -> None:
        self.store = store
        self.provider = provider
        self.policy = policy or ResearchPolicy()
        self.call_count = 0

    def research_brand(
        self,
        *,
        raw_line: str,
        supplier_hint: str = "",
        activity_context: str = "",
        canonical_line_ids: tuple[str, ...] | list[str] = (),
        cache_scope: str = "",
        cache_key_override: str = "",
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        query = sanitize_research_query(
            kind="brand",
            raw_line=raw_line,
            supplier_hint=supplier_hint,
            activity_context=activity_context,
            canonical_line_ids=canonical_line_ids,
        )
        profile_key = normalize_product_research_key(query.search_text or query.key)
        cache_key = str(cache_key_override or research_brand_cache_key(query, cache_scope=cache_scope))
        trusted_cached: dict[str, Any] | None = None
        if hasattr(self.store, "get_brand_research_profile"):
            cached = self.store.get_brand_research_profile(cache_key)
            if cached and research_profile_is_fresh(cached) and not bypass_cache:
                return normalize_research_profile(
                    kind="brand",
                    key=profile_key,
                    payload={
                        **non_authoritative_research_payload(cached),
                        "question": query.search_text,
                        "canonical_line_ids": list(query.canonical_line_ids),
                        "cache_provenance": research_cache_provenance(
                            hit=True,
                            key=cache_key,
                            kind="brand",
                        ),
                    },
                )
            if cached and _trusted_override(cached):
                trusted_cached = cached
        return self._research_and_store(
            query=query,
            profile_key=profile_key,
            cache_key=cache_key,
            owner_id=str(cache_scope or ""),
            preserved_override=trusted_cached,
        )

    def research_nace(
        self,
        *,
        nace_code: str,
        activity_context: str = "",
        bypass_cache: bool = False,
    ) -> dict[str, Any]:
        key = normalize_nace_code(nace_code)
        if not key:
            return normalize_research_profile(kind="nace", key="", payload={})
        trusted_cached: dict[str, Any] | None = None
        if hasattr(self.store, "get_nace_research_profile"):
            cached = self.store.get_nace_research_profile(key)
            if cached and research_profile_is_fresh(cached) and not bypass_cache:
                return normalize_research_profile(
                    kind="nace",
                    key=key,
                    payload={
                        **non_authoritative_research_payload(cached),
                        "question": f"NACE {key} faaliyet kodu kapsamı",
                        "cache_provenance": research_cache_provenance(hit=True, key=key, kind="nace"),
                    },
                )
            if cached and _trusted_override(cached):
                trusted_cached = cached
        query = ResearchQuery(
            kind="nace",
            key=key,
            search_text=f"NACE {key} faaliyet kodu kapsamı",
            activity_context=_sanitize_text(activity_context),
        )
        return self._research_and_store(
            query=query,
            profile_key=key,
            cache_key=key,
            owner_id="",
            preserved_override=trusted_cached,
        )

    def _research_and_store(
        self,
        *,
        query: ResearchQuery,
        profile_key: str,
        cache_key: str,
        owner_id: str,
        preserved_override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not self.policy.enabled or self.provider is None or self.call_count >= self.policy.max_per_document:
            return normalize_research_profile(kind=query.kind, key=profile_key, payload={})
        self.call_count += 1
        payload = non_authoritative_research_payload(self.provider.research(query))
        for untrusted_key in ("override", "override_actor", "override_provenance"):
            payload.pop(untrusted_key, None)
        ownership = {
            "profile_id": cache_key,
            "display_key": profile_key,
            "tenant_id": "" if query.kind == "nace" else owner_id,
            "client_id": "" if query.kind == "nace" else owner_id,
            "owner_client_id": "" if query.kind == "nace" else owner_id,
            "scope_type": "office_public" if query.kind == "nace" else "client_private",
        }
        profile = normalize_research_profile(
            kind=query.kind,
            key=profile_key,
            payload={
                **payload,
                "question": query.search_text,
                "canonical_line_ids": list(query.canonical_line_ids),
                "cache_provenance": research_cache_provenance(hit=False, key=cache_key, kind=query.kind),
                **ownership,
            },
        )
        if preserved_override and _trusted_override(preserved_override):
            profile.update(
                {
                    "override": True,
                    "override_actor": str(preserved_override.get("override_actor") or ""),
                    "override_provenance": dict(preserved_override.get("override_provenance") or {}),
                    "accountant_override": dict(preserved_override.get("accountant_override") or {}),
                }
            )
        if query.kind == "brand" and hasattr(self.store, "save_brand_research_profile"):
            return self.store.save_brand_research_profile(brand_name=cache_key, profile=profile)
        if query.kind == "nace" and hasattr(self.store, "save_nace_research_profile"):
            return self.store.save_nace_research_profile(nace_code=cache_key, profile=profile)
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
            "Muhasebe kategorisi, hesap turu veya hesap kodu secme. "
            "Yalnizca JSON obje don: display_name, summary_tr, activity_tags, confidence, conflicts, "
            "evidence[{url,title,source_type,claim,summary_tr,confidence}]."
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


class TavilySearchResearchProvider:
    provider_name = "tavily_search"

    def __init__(
        self,
        *,
        api_key: str,
        search_url: str = TAVILY_SEARCH_URL,
        http_client: Any | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TAVILY_API_KEY is required when FISORA_RESEARCH_PROVIDER=tavily")
        self.api_key = api_key.strip()
        self.search_url = search_url
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds

    def research(self, query: ResearchQuery) -> dict[str, Any]:
        response = self.http_client.post(
            self.search_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": _tavily_search_text(query),
                "topic": "general",
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
                "include_raw_content": False,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return _tavily_payload_to_research_profile(query, response.json())


def _tavily_search_text(query: ResearchQuery) -> str:
    if query.kind == "nace":
        return " ".join(
            part
            for part in (
                query.search_text,
                query.activity_context,
                "Turkce anlasilir cevap ver resmi NACE faaliyet kapsami muhasebe giderleri",
            )
            if str(part).strip()
        )
    parts = [
        query.search_text,
        query.supplier_hint,
        query.activity_context,
        "official manufacturer product category",
    ]
    return " ".join(part for part in parts if str(part).strip())


def _looks_like_english_research_text(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    english_tokens = ("retail", "sale", "medical", "orthopaedic", "official", "classification", "business", "expenses", "goods")
    turkish_tokens = ("faaliyet", "ticaret", "perakende", "tibbi", "urun", "kapsam", "gider")
    return sum(1 for token in english_tokens if token in text) >= 2 and not any(token in text for token in turkish_tokens)


def _turkish_nace_summary(query: ResearchQuery, raw_summary: str, activity_profile: object) -> str:
    summary = str(raw_summary or "").strip()
    if summary and not _looks_like_english_research_text(summary):
        return summary
    context = str(query.activity_context or "").strip()
    if context:
        return f"{query.key} NACE kodu, {context} faaliyet kapsami icin degerlendirilir. Kapsam ve gider iliskisi resmi NACE kayitlariyla musavir tarafindan kontrol edilmelidir."
    display_label = str(getattr(activity_profile, "display_label", "") or "").strip()
    if display_label and display_label != "Belirsiz faaliyet":
        return f"{query.key} NACE kodu, {display_label} faaliyeti icin degerlendirilir. Kapsam ve gider iliskisi resmi NACE kayitlariyla kontrol edilmelidir."
    return f"{query.key} NACE kodu icin faaliyet kapsami arastirildi; net kapsam resmi NACE kayitlariyla kontrol edilmelidir."


def _tavily_payload_to_research_profile(query: ResearchQuery, payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") if isinstance(payload, dict) else []
    evidence = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "url": str(item.get("url") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "source_type": "search_result",
                "summary_tr": str(item.get("content") or item.get("raw_content") or "").strip(),
            }
        )
    answer = str(payload.get("answer") or "").strip()
    accepted_evidence = [item for item in evidence if source_policy_accepts(str(item.get("url") or ""))]
    if query.kind == "nace":
        activity_profile = build_activity_profile(
            activity_description=" ".join(part for part in (query.activity_context, answer) if part),
            nace_code=query.key,
        )
        raw_summary = answer or (str(accepted_evidence[0].get("summary_tr") or "") if accepted_evidence else "")
        summary_tr = _turkish_nace_summary(query, raw_summary, activity_profile)
        research_confidence = 85 if answer and accepted_evidence else 75 if accepted_evidence else 40
        return {
            "display_name": query.key,
            "activity_title": query.activity_context or activity_profile.display_label or query.key,
            "scope_summary": summary_tr,
            "summary_tr": summary_tr,
            "included_goods_services": [],
            "likely_business_expenses": [],
            "unlikely_or_personal_items": [],
            "bank_statement_hints": [],
            "activity_tags": list(activity_profile.activity_tags),
            "source_urls": [str(item.get("url") or "") for item in accepted_evidence],
            "confidence": research_confidence,
            "research_confidence": research_confidence,
            "accounting_impact_confidence": 90 if activity_profile.activity_tags else 60,
            "evidence": evidence,
            "source_policy": query.source_policy,
        }
    research_confidence = 85 if answer and accepted_evidence else 65 if accepted_evidence else 40
    return {
        "display_name": query.key or query.search_text,
        "summary_tr": answer or (str(accepted_evidence[0].get("summary_tr") or "") if accepted_evidence else ""),
        "activity_tags": [],
        "confidence": research_confidence,
        "research_confidence": research_confidence,
        "evidence": evidence,
        "source_policy": query.source_policy,
    }


def build_research_runtime_from_env(env: dict[str, str] | Any) -> dict[str, object] | None:
    enabled = str(env.get("FISORA_RESEARCH_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None
    policy = ResearchPolicy(
        enabled=True,
        confidence_threshold=_int_between(env.get("FISORA_RESEARCH_CONFIDENCE_THRESHOLD", 70), 0, 100),
        max_per_document=max(1, _int_between(env.get("FISORA_RESEARCH_MAX_PER_DOCUMENT", 1), 1, 10)),
    )
    provider_name = str(env.get("FISORA_RESEARCH_PROVIDER", "openai")).strip().lower() or "openai"
    if provider_name == "tavily":
        api_key = str(env.get("TAVILY_API_KEY", "")).strip()
        if not api_key:
            return None
        return {"provider": TavilySearchResearchProvider(api_key=api_key), "policy": policy}
    api_key = str(env.get("OPENAI_API_KEY", "")).strip()
    if not looks_like_openai_api_key(api_key):
        return None
    provider = OpenAIAgentsResearchProvider(
        api_key=api_key,
        model=str(env.get("FISORA_RESEARCH_MODEL", "")).strip() or "gpt-5.4-mini",
    )
    return {"provider": provider, "policy": policy}
