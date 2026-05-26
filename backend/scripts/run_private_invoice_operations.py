from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.invoice_operations import (  # noqa: E402
    run_invoice_operations,
    write_journal_drafts_csv,
    write_operation_summary_json,
    write_review_tasks_csv,
)
from app.domain.pdf_invoices import parse_invoice_folder  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run private invoice PDFs as an operational phase 0 batch.")
    parser.add_argument("input_dir", help="Folder containing private invoice PDFs.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "private_samples"),
        help="Private output folder ignored by git.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input folder not found: {input_dir}")

    invoices = parse_invoice_folder(input_dir)
    run = run_invoice_operations(invoices)
    journal_path = write_journal_drafts_csv(run.journal_entries, output_dir / "journal_drafts.csv")
    review_path = write_review_tasks_csv(run.review_tasks, output_dir / "review_tasks.csv")
    summary_path = write_operation_summary_json(run, output_dir / "operation_summary.json")

    print(f"Processed {len(invoices)} invoices as an operational batch.")
    print(f"Journal drafts: {len(run.journal_entries)}")
    print(f"Review tasks: {len(run.review_tasks)}")
    print(f"Journal entries balanced: {all(entry.is_balanced for entry in run.journal_entries)}")
    print(f"Journal CSV: {journal_path}")
    print(f"Review CSV: {review_path}")
    print(f"Summary JSON: {summary_path}")


if __name__ == "__main__":
    main()

