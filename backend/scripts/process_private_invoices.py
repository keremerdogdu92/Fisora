from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.pdf_invoices import (  # noqa: E402
    parse_invoice_folder,
    write_invoice_analysis_csv,
    write_invoice_analysis_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process private real invoice PDFs through the phase 0 parser.")
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
    csv_path = write_invoice_analysis_csv(invoices, output_dir / "invoice_analysis.csv")
    json_path = write_invoice_analysis_json(invoices, output_dir / "invoice_analysis.json")

    route_counts = Counter(invoice.suggested_route for invoice in invoices)
    provider_counts = Counter(invoice.provider_hint or "unknown" for invoice in invoices)
    note_counts = Counter(note for invoice in invoices for note in invoice.parse_notes)
    print(f"Processed {len(invoices)} invoices.")
    print(f"Routes: {dict(route_counts)}")
    print(f"Providers: {dict(provider_counts)}")
    print(f"Parse notes: {dict(note_counts)}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

