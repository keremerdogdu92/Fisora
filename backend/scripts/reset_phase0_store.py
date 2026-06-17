from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.workflow_store import empty_store  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset the local Phase 0 workflow store.")
    parser.add_argument(
        "--confirm-reset-all-clients",
        action="store_true",
        help="Required guard. Deletes all client/workflow records from the target JSON store.",
    )
    parser.add_argument(
        "--store-path",
        default=str(ROOT / "exports" / "phase0_store.json"),
        help="JSON store path to reset. Defaults to exports/phase0_store.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_reset_all_clients:
        print("Refusing reset: pass --confirm-reset-all-clients.", file=sys.stderr)
        return 2
    store_path = Path(args.store_path).resolve()
    workspace_root = ROOT.resolve()
    try:
        store_path.relative_to(workspace_root)
    except ValueError:
        print(f"Refusing reset outside workspace: {store_path}", file=sys.stderr)
        return 3
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(empty_store(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Reset Phase 0 store: {store_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
