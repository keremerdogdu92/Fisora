from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata


@dataclass(frozen=True)
class StatementRuleDecision:
    transaction_type: str
    suggested_account_code: str
    confidence: int
    risk_flags: tuple[str, ...]
    review_reason: str


@dataclass(frozen=True)
class StatementRule:
    transaction_type: str
    account_code: str
    confidence: int
    terms_any: tuple[str, ...]
    direction: str = ""
    risk_flags: tuple[str, ...] = ("statement_review_required",)
    review_reason: str = "deterministic_rule_requires_accountant_review"

    def matches(self, *, text: str, direction: str, amount: Decimal | None) -> bool:
        if self.direction and self.direction != direction:
            return False
        return any(term in text for term in self.terms_any)


def _normalize(value: str) -> str:
    replacements = {
        "\u0131": "i",
        "\u0130": "i",
        "\u011f": "g",
        "\u011e": "g",
        "\u00fc": "u",
        "\u00dc": "u",
        "\u015f": "s",
        "\u015e": "s",
        "\u00f6": "o",
        "\u00d6": "o",
        "\u00e7": "c",
        "\u00c7": "c",
    }
    result = value.strip()
    for source, target in replacements.items():
        result = result.replace(source, target)
    result = unicodedata.normalize("NFKD", result)
    result = "".join(character for character in result if not unicodedata.combining(character))
    result = result.lower()
    result = re.sub(r"[^a-z0-9]+", " ", result)
    return re.sub(r"\s+", " ", result).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


RULES: tuple[StatementRule, ...] = (
    StatementRule(
        transaction_type="refund_or_reversal",
        account_code="",
        confidence=64,
        terms_any=("iade", "ters kayit", "iptal", "refund", "chargeback"),
        risk_flags=("statement_review_required", "reversal_review_required"),
        review_reason="refund_or_reversal_requires_manual_direction_check",
    ),
    StatementRule(
        transaction_type="tax_payment",
        account_code="360",
        confidence=86,
        terms_any=("gib", "vergi", "kdv", "muhtasar", "stopaj"),
        direction="out",
        risk_flags=(),
        review_reason="tax_payment_static_rule",
    ),
    StatementRule(
        transaction_type="sgk_payment",
        account_code="361",
        confidence=86,
        terms_any=("sgk", "sosyal guvenlik", "bagkur", "bag kur"),
        direction="out",
        risk_flags=(),
        review_reason="sgk_payment_static_rule",
    ),
    StatementRule(
        transaction_type="pos_blocked",
        account_code="108",
        confidence=78,
        terms_any=("pos bloke", "bloke pos", "pos blokeli"),
        risk_flags=("pos_policy_review_required",),
        review_reason="pos_blocked_policy_requires_review",
    ),
    StatementRule(
        transaction_type="pos_collection",
        account_code="108",
        confidence=72,
        terms_any=("pos", "sanal pos", "kart tahsilat"),
        direction="in",
        risk_flags=("pos_policy_review_required",),
        review_reason="pos_collection_policy_requires_review",
    ),
    StatementRule(
        transaction_type="bank_fee",
        account_code="780",
        confidence=82,
        terms_any=("banka masraf", "masraf", "komisyon", "hesap isletim", "swift ucreti", "eft ucreti", "havale ucreti"),
        direction="out",
    ),
    StatementRule(
        transaction_type="salary_payment",
        account_code="335",
        confidence=82,
        terms_any=("maas", "ucret odeme", "personel odeme", "bordro"),
        direction="out",
    ),
    StatementRule(
        transaction_type="loan_payment",
        account_code="300",
        confidence=80,
        terms_any=("kredi taksit", "kredi odeme", "kredi geri odeme", "kredi tahsilat"),
        direction="out",
    ),
    StatementRule(
        transaction_type="loan_disbursement",
        account_code="300",
        confidence=78,
        terms_any=("kredi kullandirim", "kredi kullanim", "kredi hesaba"),
        direction="in",
    ),
    StatementRule(
        transaction_type="card_payment",
        account_code="309",
        confidence=78,
        terms_any=("kredi karti odeme", "kk odeme", "kart borcu", "business kart"),
        direction="out",
    ),
    StatementRule(
        transaction_type="internal_transfer",
        account_code="102",
        confidence=74,
        terms_any=("virman", "hesaplar arasi", "kendi hesab", "subeler arasi"),
        risk_flags=("statement_review_required", "transfer_review_required"),
        review_reason="internal_transfer_requires_bank_account_pair_check",
    ),
    StatementRule(
        transaction_type="bank_transfer_in",
        account_code="120",
        confidence=68,
        terms_any=("gelen eft", "gelen havale", "eft", "havale", "fast", "tahsilat"),
        direction="in",
    ),
    StatementRule(
        transaction_type="bank_transfer_out",
        account_code="320",
        confidence=68,
        terms_any=("giden eft", "giden havale", "eft", "havale", "fast", "odeme"),
        direction="out",
    ),
)


def classify_statement_transaction(
    *,
    description: str,
    direction: str,
    amount: Decimal | None,
    suggested_account_code: str = "",
) -> StatementRuleDecision:
    text = _normalize(description)
    normalized_direction = _normalize(direction)
    for rule in RULES:
        if rule.matches(text=text, direction=normalized_direction, amount=amount):
            return StatementRuleDecision(
                transaction_type=rule.transaction_type,
                suggested_account_code=suggested_account_code or rule.account_code,
                confidence=rule.confidence,
                risk_flags=rule.risk_flags,
                review_reason=rule.review_reason,
            )
    if suggested_account_code:
        return StatementRuleDecision(
            transaction_type="suggested_by_import",
            suggested_account_code=suggested_account_code,
            confidence=70,
            risk_flags=("statement_review_required",),
            review_reason="imported_account_suggestion_requires_review",
        )
    unknown_flags = ("statement_review_required",)
    if _contains_any(text, ("eft", "havale", "fast", "odeme", "tahsilat")):
        unknown_flags = ("statement_review_required", "counterparty_not_found")
    return StatementRuleDecision(
        transaction_type="unknown",
        suggested_account_code="",
        confidence=35,
        risk_flags=unknown_flags,
        review_reason="no_statement_rule_matched",
    )
