from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.chart_accounts import (  # noqa: E402
    extract_counterparty_candidates,
    parse_chart_accounts,
    validate_vat_accounts,
)


def analyze_file(path: Path) -> dict[str, object]:
    accounts = parse_chart_accounts(path)
    counterparties = extract_counterparty_candidates(accounts)
    vat_status = validate_vat_accounts(accounts)
    detail_accounts = [account for account in accounts if account.is_detail_account]
    bank_accounts = [account for account in detail_accounts if account.normalized_account_code.startswith("102")]
    customer_accounts = [account for account in counterparties if account.counterparty_type == "customer"]
    supplier_accounts = [account for account in counterparties if account.counterparty_type == "supplier"]
    return {
        "file_name": path.name,
        "account_count": len(accounts),
        "detail_account_count": len(detail_accounts),
        "bank_detail_count": len(bank_accounts),
        "customer_candidate_count": len(customer_accounts),
        "supplier_candidate_count": len(supplier_accounts),
        "has_purchase_vat_191": vat_status["has_purchase_vat_191"],
        "has_sales_vat_391": vat_status["has_sales_vat_391"],
        "first_customer_accounts": ";".join(
            f"{account.normalized_account_code} {account.account_name}" for account in customer_accounts[:5]
        ),
        "first_supplier_accounts": ";".join(
            f"{account.normalized_account_code} {account.account_name}" for account in supplier_accounts[:5]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze private Zirve chart account files.")
    parser.add_argument("files", nargs="+", help="XLSX/CSV chart account files.")
    parser.add_argument(
        "--output",
        default=str(ROOT / "private_samples" / "chart_account_analysis.csv"),
        help="Private output CSV path ignored by git.",
    )
    args = parser.parse_args()

    rows = [analyze_file(Path(file_path)) for file_path in args.files]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Analyzed {len(rows)} chart account files. Output: {output_path}")
    for row in rows:
        print(
            f"{row['file_name']}: accounts={row['account_count']} detail={row['detail_account_count']} "
            f"customers={row['customer_candidate_count']} suppliers={row['supplier_candidate_count']} "
            f"191={row['has_purchase_vat_191']} 391={row['has_sales_vat_391']}"
        )


if __name__ == "__main__":
    main()

