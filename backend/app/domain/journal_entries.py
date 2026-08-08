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
    tax_rate: Decimal | None = None
    counterparty_tax_id: str | None = None
    document_ref: str | None = None
    vat_group_id: str = ""
    contributing_line_ids: tuple[str, ...] = field(default_factory=tuple)
    source_line_numbers: tuple[int, ...] = field(default_factory=tuple)
    allocated_amounts: tuple[tuple[str, str], ...] = field(default_factory=tuple)


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
    supplier_description: str = "Satici cari",
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
            JournalLine(
                vat_account,
                "Indirilecek KDV",
                debit=vat,
                tax_rate=vat_rate * Decimal("100"),
                document_ref=document_ref,
            ),
            JournalLine(
                supplier_account,
                supplier_description,
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
    customer_description: str = "Alici cari",
    customer_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    net, vat = split_vat(total, vat_rate)
    lines = [
            JournalLine(
                customer_account,
                customer_description,
                debit=total,
                counterparty_tax_id=customer_tax_id,
                document_ref=document_ref,
            ),
            JournalLine(revenue_account, "Satis geliri", credit=net, document_ref=document_ref),
    ]
    if vat > Decimal("0.00"):
        lines.append(
            JournalLine(
                vat_account,
                "Hesaplanan KDV",
                credit=vat,
                tax_rate=vat_rate * Decimal("100"),
                document_ref=document_ref,
            )
        )
    return JournalEntry(
        entry_type="sales",
        entry_date=entry_date,
        description=f"Satis faturasi {document_ref or ''}".strip(),
        lines=tuple(lines),
    )


def build_component_purchase_entry(
    *,
    entry_date: str,
    service_expense_account: str,
    service_expense_amount: Decimal,
    vat_account: str,
    vat_amount: Decimal,
    separate_expenses: Iterable[tuple[str, str, Decimal]] = (),
    supplier_account: str,
    supplier_total: Decimal,
    supplier_description: str = "Satici cari",
    supplier_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    lines: list[JournalLine] = []
    if service_expense_amount:
        lines.append(JournalLine(service_expense_account, "Hizmet gideri", debit=money(service_expense_amount), document_ref=document_ref))
    if vat_amount:
        lines.append(JournalLine(vat_account, "Indirilecek KDV", debit=money(vat_amount), document_ref=document_ref))
    for account_code, description, amount in separate_expenses:
        if amount:
            lines.append(JournalLine(account_code, description, debit=money(amount), document_ref=document_ref))
    lines.append(
        JournalLine(
            supplier_account,
            supplier_description,
            credit=money(supplier_total),
            counterparty_tax_id=supplier_tax_id,
            document_ref=document_ref,
        )
    )
    return JournalEntry(
        entry_type="component_purchase",
        entry_date=entry_date,
        description=f"Bilesen bazli alis faturasi {document_ref or ''}".strip(),
        lines=tuple(lines),
    )


def build_purchase_return_entry(
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
        entry_type="purchase_return",
        entry_date=entry_date,
        description=f"Alis iade faturasi {document_ref or ''}".strip(),
        lines=(
            JournalLine(
                supplier_account,
                "Satici cari iade",
                debit=total,
                counterparty_tax_id=supplier_tax_id,
                document_ref=document_ref,
            ),
            JournalLine(expense_account, "Gider iade", credit=net, document_ref=document_ref),
            JournalLine(
                vat_account,
                "Indirilecek KDV iade",
                credit=vat,
                tax_rate=vat_rate * Decimal("100"),
                document_ref=document_ref,
            ),
        ),
        risk_flags=("return_invoice_accountant_review",),
    )


def build_sales_return_entry(
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
    lines = [
        JournalLine(revenue_account, "Satis geliri iade", debit=net, document_ref=document_ref),
    ]
    if vat > Decimal("0.00"):
        lines.append(
            JournalLine(
                vat_account,
                "Hesaplanan KDV iade",
                debit=vat,
                tax_rate=vat_rate * Decimal("100"),
                document_ref=document_ref,
            )
        )
    lines.append(
        JournalLine(
            customer_account,
            "Alici cari iade",
            credit=total,
            counterparty_tax_id=customer_tax_id,
            document_ref=document_ref,
        )
    )
    return JournalEntry(
        entry_type="sales_return",
        entry_date=entry_date,
        description=f"Satis iade faturasi {document_ref or ''}".strip(),
        lines=tuple(lines),
        risk_flags=("return_invoice_accountant_review",),
    )


def build_purchase_return_review_entry(
    *,
    entry_date: str,
    total: Decimal,
    expense_account: str,
    supplier_account: str = "320.01.001",
    supplier_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        entry_type="purchase_return_review",
        entry_date=entry_date,
        description=f"Kontrol gerekli alis iade faturasi {document_ref or ''}".strip(),
        lines=(
            JournalLine(
                supplier_account,
                "Satici cari iade kontrol",
                debit=total,
                counterparty_tax_id=supplier_tax_id,
                document_ref=document_ref,
            ),
            JournalLine(expense_account, "Gider iade kontrol", credit=total, document_ref=document_ref),
        ),
        risk_flags=("return_invoice_accountant_review",),
    )


def build_sales_return_review_entry(
    *,
    entry_date: str,
    total: Decimal,
    revenue_account: str,
    customer_account: str = "120.01.001",
    customer_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        entry_type="sales_return_review",
        entry_date=entry_date,
        description=f"Kontrol gerekli satis iade faturasi {document_ref or ''}".strip(),
        lines=(
            JournalLine(revenue_account, "Satis iade kontrol", debit=total, document_ref=document_ref),
            JournalLine(
                customer_account,
                "Alici cari iade kontrol",
                credit=total,
                counterparty_tax_id=customer_tax_id,
                document_ref=document_ref,
            ),
        ),
        risk_flags=("return_invoice_accountant_review",),
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
    items: Iterable[tuple[str, Decimal, Decimal] | tuple[str, Decimal, Decimal, str]],
    supplier_account: str = "320.01.001",
    supplier_description: str = "Satici cari",
    supplier_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    lines: list[JournalLine] = []
    total = Decimal("0.00")
    for item in items:
        expense_account, gross_amount, vat_rate = item[:3]
        vat_account = item[3] if len(item) > 3 else "191.01"
        net, vat = split_vat(gross_amount, vat_rate)
        total += gross_amount
        lines.append(JournalLine(expense_account, f"Gider KDV {vat_rate:.2%}", debit=net, document_ref=document_ref))
        lines.append(
            JournalLine(
                vat_account,
                f"Indirilecek KDV {vat_rate:.2%}",
                debit=vat,
                tax_rate=vat_rate * Decimal("100"),
                document_ref=document_ref,
            )
        )
    lines.append(
        JournalLine(
            supplier_account,
            supplier_description,
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
        risk_flags=(),
    )


def build_mixed_vat_sales_entry(
    *,
    entry_date: str,
    items: Iterable[tuple[str, Decimal, Decimal] | tuple[str, Decimal, Decimal, str]],
    customer_account: str = "120.01.001",
    customer_description: str = "Alici cari",
    customer_tax_id: str | None = None,
    document_ref: str | None = None,
) -> JournalEntry:
    revenue_and_vat_lines: list[JournalLine] = []
    total = Decimal("0.00")
    for item in items:
        revenue_account, gross_amount, vat_rate = item[:3]
        vat_account = item[3] if len(item) > 3 else "391.01"
        net, vat = split_vat(gross_amount, vat_rate)
        total += gross_amount
        revenue_and_vat_lines.append(JournalLine(revenue_account, f"Satis KDV {vat_rate:.2%}", credit=net, document_ref=document_ref))
        if vat > Decimal("0.00"):
            revenue_and_vat_lines.append(
                JournalLine(
                    vat_account,
                    f"Hesaplanan KDV {vat_rate:.2%}",
                    credit=vat,
                    tax_rate=vat_rate * Decimal("100"),
                    document_ref=document_ref,
                )
            )
    return JournalEntry(
        entry_type="mixed_vat_sales",
        entry_date=entry_date,
        description=f"Karisik KDV satis faturasi {document_ref or ''}".strip(),
        lines=(
            JournalLine(
                customer_account,
                customer_description,
                debit=total.quantize(MONEY),
                counterparty_tax_id=customer_tax_id,
                document_ref=document_ref,
            ),
            *revenue_and_vat_lines,
        ),
        risk_flags=(),
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

