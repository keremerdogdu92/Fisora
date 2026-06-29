from __future__ import annotations


def account_family(code: str) -> str:
    return str(code or "").strip().split(".")[0]


def account_allowed_for_treatment(code: str, treatment: str, direction: str) -> bool:
    family = account_family(code)
    if not family:
        return False
    if direction == "sales":
        return family in {"600", "601", "602"}
    if treatment == "stock_or_cogs":
        return family in {"153", "150", "151", "152"}
    if treatment == "expense":
        return family in {"740", "750", "760", "770", "780"}
    if treatment == "non_deductible_review":
        return family == "689"
    if treatment == "fixed_asset_review":
        return family.startswith("25")
    return family in {"153", "740", "750", "760", "770", "780", "689"}
