from __future__ import annotations

import json
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
from app.domain.exporters import export_universal_journal_csv  # noqa: E402
from app.domain.journal_entries import build_sample_entries  # noqa: E402


def main() -> None:
    chart_path = ROOT / "samples" / "chart_accounts" / "chart_accounts_sample_a.csv"
    output_path = ROOT / "exports" / "universal_journal.csv"

    accounts = parse_chart_accounts(chart_path)
    counterparties = extract_counterparty_candidates(accounts)
    vat_status = validate_vat_accounts(accounts)

    entries = build_sample_entries()
    export_universal_journal_csv(entries, output_path)

    summary = {
        "chart_account_file": str(chart_path.relative_to(ROOT)),
        "account_count": len(accounts),
        "detail_account_count": sum(1 for account in accounts if account.is_detail_account),
        "counterparty_candidate_count": len(counterparties),
        "vat_status": vat_status,
        "entry_count": len(entries),
        "entries_balanced": all(entry.is_balanced for entry in entries),
        "export_file": str(output_path.relative_to(ROOT)),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

