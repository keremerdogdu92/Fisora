from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.matching_simulation import simulate_private_matching, write_review_ui_json, write_simulation_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate current invoices against current private chart account files.")
    parser.add_argument("--invoice-dir", required=True, help="Folder containing private PDF invoices.")
    parser.add_argument("--chart-file", action="append", required=True, help="Private XLSX/CSV chart account file. Repeatable.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "private_samples"),
        help="Private output folder ignored by git.",
    )
    parser.add_argument(
        "--ui-json",
        default=str(ROOT / "frontend" / "public" / "local-review-data.json"),
        help="Ignored local JSON consumed by the review UI.",
    )
    args = parser.parse_args()

    runs = simulate_private_matching(
        Path(args.invoice_dir),
        [Path(chart_file) for chart_file in args.chart_file],
    )
    output_dir = Path(args.output_dir)
    csv_path = write_simulation_csv(runs, output_dir / "matching_simulation.csv")
    json_path = write_review_ui_json(runs, Path(args.ui_json))

    print(f"Simulated {len(runs)} chart runs.")
    for run in runs:
        print(
            f"{run.chart_file_name}: auto_ready={run.auto_ready_count} "
            f"review_required={run.review_required_count} cannot_draft={run.cannot_draft_count}"
        )
    print(f"CSV: {csv_path}")
    print(f"UI JSON: {json_path}")


if __name__ == "__main__":
    main()

