from __future__ import annotations

from dataclasses import dataclass

from app.domain.chart_accounts import ChartAccount, normalize_iban


@dataclass(frozen=True)
class CounterpartyMatch:
    account_code: str
    account_name: str
    confidence: int
    match_reason: str
    requires_review: bool


def _normalize(value: str) -> str:
    replacements = {
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
    lowered = value.lower()
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    return " ".join(lowered.split())


def _distinctive_tokens(value: str) -> set[str]:
    legal_noise = {
        "a",
        "as",
        "aş",
        "ltd",
        "limited",
        "sti",
        "şti",
        "sirketi",
        "şirketi",
        "tic",
        "ticaret",
        "san",
        "sanayi",
        "ve",
    }
    return {
        token
        for token in _normalize(value).replace(".", " ").split()
        if len(token) >= 4 and token not in legal_noise
    }


def match_counterparty(
    accounts: list[ChartAccount],
    *,
    tax_ids: tuple[str, ...] = (),
    ibans: tuple[str, ...] = (),
    name_hint: str = "",
    account_prefixes: tuple[str, ...] = ("120", "320"),
) -> CounterpartyMatch:
    candidates = [
        account
        for account in accounts
        if account.is_detail_account and account.normalized_account_code.startswith(account_prefixes)
    ]

    iban_set = {normalize_iban(iban) for iban in ibans if normalize_iban(iban)}
    for account in candidates:
        if account.iban and normalize_iban(account.iban) in iban_set:
            return CounterpartyMatch(
                account_code=account.normalized_account_code,
                account_name=account.account_name,
                confidence=97,
                match_reason="iban_exact",
                requires_review=False,
            )

    tax_id_set = {tax_id for tax_id in tax_ids if tax_id}
    for account in candidates:
        if account.tax_id and account.tax_id in tax_id_set:
            return CounterpartyMatch(
                account_code=account.normalized_account_code,
                account_name=account.account_name,
                confidence=98,
                match_reason="tax_id_exact",
                requires_review=False,
            )

    normalized_hint = _normalize(name_hint)
    if normalized_hint:
        for account in candidates:
            normalized_name = _normalize(account.account_name)
            if normalized_hint in normalized_name or normalized_name in normalized_hint:
                return CounterpartyMatch(
                    account_code=account.normalized_account_code,
                    account_name=account.account_name,
                    confidence=82,
                    match_reason="title_similarity",
                    requires_review=True,
                )
            overlap = _distinctive_tokens(normalized_hint) & _distinctive_tokens(normalized_name)
            if len(overlap) >= 2:
                return CounterpartyMatch(
                    account_code=account.normalized_account_code,
                    account_name=account.account_name,
                    confidence=76,
                    match_reason="title_token_overlap",
                    requires_review=True,
                )

    return CounterpartyMatch(
        account_code="",
        account_name="",
        confidence=0,
        match_reason="not_found",
        requires_review=True,
    )
