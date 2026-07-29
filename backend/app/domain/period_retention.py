from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
import re


AccountingPeriod = date


@dataclass(frozen=True)
class PeriodRetentionSchedule:
    accounting_period: AccountingPeriod
    preparation_on: date
    warning_on: date
    delete_on: date


def add_months(period: date, months: int) -> date:
    if period.day != 1:
        raise ValueError("accounting_period_must_be_month_start")
    month_index = period.year * 12 + period.month - 1 + months
    year, month_index = divmod(month_index, 12)
    return date(year, month_index + 1, 1)


def month_end(period: date) -> date:
    first = add_months(period, 0)
    return date(first.year, first.month, monthrange(first.year, first.month)[1])


def parse_accounting_period(value: str) -> AccountingPeriod:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value.strip()):
        raise ValueError("invalid_accounting_period")
    year, month = (int(part) for part in value.strip().split("-"))
    return date(year, month, 1)


def period_retention_schedule(period: date) -> PeriodRetentionSchedule:
    accounting_period = period if period.day == 1 else parse_accounting_period(period.strftime("%Y-%m"))
    preparation_period = add_months(accounting_period, 2)
    warning_period = add_months(accounting_period, 3)
    return PeriodRetentionSchedule(
        accounting_period=accounting_period,
        preparation_on=month_end(preparation_period),
        warning_on=warning_period,
        delete_on=month_end(warning_period),
    )
