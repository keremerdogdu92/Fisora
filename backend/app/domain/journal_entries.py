from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


MONEY = Decimal("0.01")


@dataclass(frozen=True)
class JournalLine:
    account_code: str
    description: str
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    counterparty_tax_id: str | None = None
    document_ref: str | None = None


@dataclass(frozen=True)
class JournalEntry:
    entry_type: str
    entry_date: str
    description: str
    lines: tuple[JournalLine, ...]
    risk_flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_debit(self) -> Decimal:
        return sum((line.debit for line in self.lines), Decimal("0.00")).quantize(MONEY)

    @property
    def total_credit(self) -> Decimal:
        return sum((line.credit for line in self.lines), Decimal("0.00")).quantize(MONEY)

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit


def money(value: str | int | float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def split_vat(total: Decimal, vat_rate: Decimal) -> tuple[Decimal, Decimal]:
    divisor = Decimal("1.00") + vat_rate
    net = (total / divisor).quantize(MONEY, rounding=ROUND_HALF_UP)
    vat = (total - net).quantize(MONEY, rounding=ROUND_HALF_UP)
    return net, vat


def build_purchase_entry(
    *,
    entry_date: str,
    total: Decimal,
    vat_rate: Decimal,
    expense_account: str,
    vat_account: str = "191.01",
    supplier_account: str = "320.01.001",
    supplier_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    net, vat = split_vat(total, vat_rate)
    return JournalEntry(
        entry_type="purchase",
        entry_date=entry_date,
        description=f"Alis faturasi {document_ref or ''}".strip(),
        lines=(
            JournalLine(expense_account, "Gider", debit=net, document_ref=document_ref),
            JournalLine(vat_account, "Indirilecek KDV", debit=vat, document_ref=document_ref),
            JournalLine(
                supplier_account,
                "Satici cari",
                credit=total,
                counterparty_tax_id=supplier_tax_id,
                document_ref=document_ref,
            ),
        ),
    )


def build_sales_entry(
    *,
    entry_date: str,
    total: Decimal,
    vat_rate: Decimal,
    revenue_account: str,
    vat_account: str = "391.01",
    customer_account: str = "120.01.001",
    customer_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    net, vat = split_vat(total, vat_rate)
    return JournalEntry(
        entry_type="sales",
        entry_date=entry_date,
        description=f"Satis faturasi {document_ref or ''}".strip(),
        lines=(
            JournalLine(
                customer_account,
                "Alici cari",
                debit=total,
                counterparty_tax_id=customer_tax_id,
                document_ref=document_ref,
            ),
            JournalLine(revenue_account, "Satis geliri", credit=net, document_ref=document_ref),
            JournalLine(vat_account, "Hesaplanan KDV", credit=vat, document_ref=document_ref),
        ),
    )


def build_bank_payment_entry(
    *,
    entry_date: str,
    amount: Decimal,
    bank_account: str,
    counterparty_account: str,
    counterparty_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        entry_type="bank_payment",
        entry_date=entry_date,
        description=f"Banka odemesi {document_ref or ''}".strip(),
        lines=(
            JournalLine(
                counterparty_account,
                "Cari odeme",
                debit=amount,
                counterparty_tax_id=counterparty_tax_id,
                document_ref=document_ref,
            ),
            JournalLine(bank_account, "Banka cikisi", credit=amount, document_ref=document_ref),
        ),
    )


def build_mixed_vat_purchase_entry(
    *,
    entry_date: str,
    items: Iterable[tuple[str, Decimal, Decimal]],
    supplier_account: str = "320.01.001",
    supplier_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    lines: list[JournalLine] = []
    total = Decimal("0.00")
    for expense_account, gross_amount, vat_rate in items:
        net, vat = split_vat(gross_amount, vat_rate)
        total += gross_amount
        lines.append(JournalLine(expense_account, f"Gider KDV {vat_rate:.2%}", debit=net, document_ref=document_ref))
        lines.append(JournalLine("191.01", f"Indirilecek KDV {vat_rate:.2%}", debit=vat, document_ref=document_ref))
    lines.append(
        JournalLine(
            supplier_account,
            "Satici cari",
            credit=total.quantize(MONEY),
            counterparty_tax_id=supplier_tax_id,
            document_ref=document_ref,
        )
    )
    return JournalEntry(
        entry_type="mixed_vat_purchase",
        entry_date=entry_date,
        description=f"Karisik KDV alis faturasi {document_ref or ''}".strip(),
        lines=tuple(lines),
        risk_flags=("mixed_vat_manual_review",),
    )


def build_sample_entries() -> list[JournalEntry]:
    return [
        build_purchase_entry(
            entry_date="2026-05-01",
            total=money("1200.00"),
            vat_rate=Decimal("0.20"),
            expense_account="770.01",
            supplier_tax_id="9999999999",
            document_ref="AF-0001",
        ),
        build_sales_entry(
            entry_date="2026-05-02",
            total=money("2400.00"),
            vat_rate=Decimal("0.20"),
            revenue_account="600.01",
            customer_tax_id="8888888888",
            document_ref="SF-0001",
        ),
        build_bank_payment_entry(
            entry_date="2026-05-03",
            amount=money("500.00"),
            bank_account="102.01",
            counterparty_account="320.01.001",
            counterparty_tax_id="9999999999",
            document_ref="BNK-0001",
        ),
        build_mixed_vat_purchase_entry(
            entry_date="2026-05-04",
            items=(
                ("770.01", money("108.00"), Decimal("0.08")),
                ("770.02", money("120.00"), Decimal("0.20")),
            ),
            supplier_tax_id="7777777777",
            document_ref="KDV-0001",
        ),
    ]

