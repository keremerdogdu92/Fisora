from __future__ import annotations

import re
import unicodedata
from typing import Any


VAGUE_NOTES = {
    "bunu boyle yap",
    "bu sekilde yap",
    "ayni sekilde yap",
    "bunu uygula",
}


def build_natural_language_rule_candidate(
    *,
    accountant_note: str = "",
    rule_instruction: str = "",
    product_line_hint: str = "",
    category: str = "",
    corrected_account_code: str = "",
) -> dict[str, Any]:
    source_text = " ".join(part for part in (accountant_note, rule_instruction, product_line_hint, category) if str(part).strip())
    normalized = _normalize_text(source_text)
    match_phrase = _match_phrase(product_line_hint, source_text)
    product_category = _product_category(normalized, category)
    semantic_intent = _semantic_accounting_intent(normalized, product_category)
    account_treatment = _account_treatment(normalized, product_category, corrected_account_code)
    vague = _is_vague(normalized, match_phrase, product_category, corrected_account_code)
    counterparty_rule = _is_counterparty_rule(normalized)
    office_semantic = _is_office_semantic_rule(normalized, semantic_intent)
    scope = _scope(vague=vague, match_phrase=match_phrase, counterparty_rule=counterparty_rule, office_semantic=office_semantic)

    return {
        "scope": scope,
        "match_phrase": "" if vague else match_phrase,
        "product_category": "" if vague else product_category or semantic_intent,
        "account_treatment": "" if vague else account_treatment,
        "semantic_accounting_intent": "" if vague else semantic_intent,
        "suggested_account_code": "" if vague or office_semantic else str(corrected_account_code or "").strip(),
        "requires_review": True,
        "reason": "Not kural icin fazla muglak." if vague else _reason(product_category, account_treatment, match_phrase),
    }


def _match_phrase(product_line_hint: str, source_text: str) -> str:
    hint = _normalize_text(product_line_hint)
    if _phrase_is_specific(hint):
        return hint[:120]
    terms = _normalized_terms(source_text, limit=6)
    if len(terms) >= 2:
        return " ".join(terms[:5])[:120]
    return ""


def _phrase_is_specific(value: str) -> bool:
    if not value:
        return False
    terms = value.split()
    return len(terms) >= 2 or any(any(character.isdigit() for character in term) for term in terms)


def _product_category(normalized: str, category: str) -> str:
    existing = _normalize_text(category).replace(" ", "_")
    if existing and existing not in {"bilinmeyen", "not_assessed"}:
        return existing
    if "isitme" in normalized and "cihaz" in normalized:
        return "isitme_cihazi"
    if any(term in normalized.split() for term in ("pil", "battery", "kalip", "kalib")):
        return "isitme_cihazi_pili"
    if "kargo" in normalized or "nakliye" in normalized:
        return "kargo"
    if "dogalgaz" in normalized or "dogal gaz" in normalized or "igdas" in normalized:
        return "dogalgaz_gideri"
    if "kira" in normalized or "kiralama" in normalized:
        return "isyeri_kirasi"
    return ""


def _semantic_accounting_intent(normalized: str, product_category: str) -> str:
    if product_category == "dogalgaz_gideri" or "dogalgaz" in normalized or "dogal gaz" in normalized or "igdas" in normalized:
        return "dogalgaz_gideri"
    if product_category in {"e_fatura_hizmeti"} or "e fatura" in normalized or "efatura" in normalized:
        return "e_fatura_yazilim_gideri"
    if product_category == "kargo" or "kargo" in normalized or "nakliye" in normalized:
        return "kargo_gideri"
    if "internet" in normalized or "ttnet" in normalized or "turknet" in normalized:
        return "internet_gideri"
    if "elektrik" in normalized or "edas" in normalized:
        return "elektrik_gideri"
    return product_category


def _account_treatment(normalized: str, product_category: str, corrected_account_code: str) -> str:
    account_family = str(corrected_account_code or "").strip().split(".")[0]
    if account_family in {"153", "150", "151", "152"}:
        return "stock_or_cogs"
    if account_family in {"740", "750", "760", "770", "780"}:
        return "expense"
    if product_category in {"isitme_cihazi", "isitme_cihazi_pili"} or "stok" in normalized:
        return "stock_or_cogs"
    if product_category in {"kargo", "isyeri_kirasi"}:
        return "expense"
    return ""


def _is_vague(normalized: str, match_phrase: str, product_category: str, corrected_account_code: str) -> bool:
    if normalized in VAGUE_NOTES:
        return True
    meaningful_terms = _normalized_terms(normalized, limit=6)
    if len(meaningful_terms) < 2:
        return True
    if not match_phrase and not product_category and not corrected_account_code:
        return True
    return False


def _is_counterparty_rule(normalized: str) -> bool:
    terms = set(normalized.split())
    return bool(
        {"cari", "firma", "firmanin", "toptanci", "tedarikci", "satici", "vkn"}.intersection(terms)
        or "vergi numarasi" in normalized
        or "vergi numarali" in normalized
        or "bize kesilen" in normalized
        or "gelen fatura" in normalized
        or "bu mukellefte" in normalized
    )


def _is_office_semantic_rule(normalized: str, semantic_intent: str) -> bool:
    if not semantic_intent:
        return False
    return bool(
        "ofis geneli" in normalized
        or "tum mukellef" in normalized
        or "tum firm" in normalized
        or "firma geneli" in normalized
        or "her mukellef" in normalized
    )


def _scope(*, vague: bool, match_phrase: str, counterparty_rule: bool, office_semantic: bool) -> str:
    if vague or not match_phrase:
        return "client_only"
    if office_semantic:
        return "office_semantic"
    if counterparty_rule:
        return "client_counterparty"
    return "global_product_phrase"


def _reason(product_category: str, account_treatment: str, match_phrase: str) -> str:
    pieces = []
    if match_phrase:
        pieces.append(f"Eslesme ifadesi: {match_phrase}.")
    if product_category:
        pieces.append(f"Urun kategorisi: {product_category}.")
    if account_treatment:
        pieces.append(f"Hesap davranisi: {account_treatment}.")
    pieces.append("Dogal dil notundan aday kural olusturuldu; musavir onayi gerekir.")
    return " ".join(pieces)


def _normalize_text(value: str) -> str:
    replacements = {
        "Ä±": "i",
        "Ä°": "i",
        "ÄŸ": "g",
        "Ä": "g",
        "Ã¼": "u",
        "Ãœ": "u",
        "ÅŸ": "s",
        "Å": "s",
        "Ã¶": "o",
        "Ã–": "o",
        "Ã§": "c",
        "Ã‡": "c",
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
    text = str(value or "").strip()
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _normalized_terms(value: str, *, limit: int = 12) -> tuple[str, ...]:
    stop_terms = {"alt", "bu", "bunu", "boyle", "da", "de", "diye", "gibi", "icin", "ile", "ise", "kalem", "sekilde", "ve"}
    terms = []
    for term in _normalize_text(value).split():
        if len(term) < 2 or term in stop_terms:
            continue
        terms.append(term)
    return tuple(dict.fromkeys(terms))[:limit]
