from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.persistence.gemini_trial_reset_repository import reset_gemini_trial_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview or reset disposable Gemini V2 outputs for one tenant."
    )
    parser.add_argument("--dsn", default=os.environ.get("FISORA_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--tenant-key", required=True)
    parser.add_argument("--artifact-storage-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="apply the reset; default is dry-run")
    parser.add_argument("--confirm-tenant-key")
    args = parser.parse_args(argv)
    try:
        summary = reset_gemini_trial_outputs(
            dsn=args.dsn,
            tenant_key=args.tenant_key,
            artifact_storage_root=args.artifact_storage_root,
            apply=args.apply,
            confirm_tenant_key=args.confirm_tenant_key,
        )
    except Exception as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if int(summary.deleted_counts.get("artifact_body_cleanup_failures", 0) or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
