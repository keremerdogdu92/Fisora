from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.workflows.synthetic_pilot import run_synthetic_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sanitized Fisora pilot workflow.")
    parser.add_argument(
        "--store-path",
        default="exports/synthetic_pilot_store.json",
        help="Ignored local JSON store path.",
    )
    args = parser.parse_args()

    summary = run_synthetic_pilot(Path(args.store_path))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

