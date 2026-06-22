from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.business_relevance import ClientProfile  # noqa: E402
from app.domain.matching_simulation import (  # noqa: E402
    private_benchmark_summary,
    simulate_private_matching,
    write_review_ui_json,
    write_simulation_csv,
)
from app.workflows.document_processing import build_ai_runtime_from_env  # noqa: E402


FIRM_PROFILES = {
    "firma-1": {
        "title": "Omer Yagci",
        "tax_id": "45661316282",
        "activity_description": "Isitme cihazi satis ve servis",
    },
    "firma-2": {
        "title": "Orhan Elibol",
        "tax_id": "30052309394",
        "activity_description": "Isitme cihazi satis ve servis",
    },
}


def _client_profile(firm_id: str) -> ClientProfile:
    profile = FIRM_PROFILES[firm_id]
    return ClientProfile(
        client_id=firm_id,
        title=profile["title"],
        tax_id=profile["tax_id"],
        activity_description=profile["activity_description"],
        workplace_addresses=("Istanbul",),
        has_chart_accounts=True,
    )


def _chart_files(firm_dir: Path) -> list[Path]:
    return sorted(path for path in (firm_dir / "chart_accounts").glob("*") if path.is_file())


def _provider_status(ai_enabled: bool, classifier: object | None) -> dict[str, object]:
    provider = getattr(classifier, "provider", None)
    provider_name = str(getattr(provider, "provider_name", "") or "")
    return {
        "ai_enabled": ai_enabled,
        "ai_provider": provider_name or "disabled",
        "research_enabled": str(os.environ.get("FISORA_RESEARCH_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"},
        "research_provider": str(os.environ.get("FISORA_RESEARCH_PROVIDER", "") or "disabled"),
        "tavily_key_present": bool(str(os.environ.get("TAVILY_API_KEY", "")).strip()),
    }


def _run_one(
    *,
    root: Path,
    output_root: Path,
    firm_id: str,
    run_label: str,
    classifier: object | None,
    ai_enabled: bool,
) -> dict[str, object]:
    firm_dir = root / firm_id
    invoice_dir = firm_dir / "invoices"
    chart_files = _chart_files(firm_dir)
    if not invoice_dir.exists() or not chart_files:
        return {
            "firm_id": firm_id,
            "run_label": run_label,
            "status": "blocked",
            "reason": "private_samples_missing_or_incomplete",
        }

    runs = simulate_private_matching(
        invoice_dir,
        chart_files,
        _client_profile(firm_id),
        product_classifier=classifier,
    )
    run_dir = output_root / run_label / firm_id
    csv_path = write_simulation_csv(runs, run_dir / "matching_simulation.csv")
    ui_path = write_review_ui_json(runs, run_dir / "local-review-data.json")
    summary = {
        **private_benchmark_summary(runs, run_label=run_label, firm_id=firm_id),
        **_provider_status(ai_enabled, classifier),
        "status": "ok",
        "csv_path": str(csv_path),
        "ui_json_path": str(ui_path),
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run private real-pilot pipeline benchmark for selected firms.")
    parser.add_argument("--root", default=str(ROOT / "private_samples" / "real_pilot"))
    parser.add_argument("--firm", action="append", choices=sorted(FIRM_PROFILES), default=[])
    parser.add_argument("--output-root", default="")
    parser.add_argument("--include-ai", action="store_true", help="Run AI tie-breaker pass using current process env.")
    args = parser.parse_args()

    root = Path(args.root)
    firms = args.firm or ["firma-1", "firma-2"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_root) if args.output_root else root / "benchmark_runs" / stamp
    output_root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, object]] = []
    for firm_id in firms:
        summaries.append(
            _run_one(
                root=root,
                output_root=output_root,
                firm_id=firm_id,
                run_label="baseline",
                classifier=None,
                ai_enabled=False,
            )
        )

    if args.include_ai:
        runtime = build_ai_runtime_from_env(os.environ)
        classifier = runtime.get("product_classifier")
        for firm_id in firms:
            summaries.append(
                _run_one(
                    root=root,
                    output_root=output_root,
                    firm_id=firm_id,
                    run_label="ai_tie_breaker",
                    classifier=classifier,
                    ai_enabled=classifier is not None,
                )
            )

    aggregate = {
        "generated_at": stamp,
        "root": str(root),
        "output_root": str(output_root),
        "firms": firms,
        "summaries": summaries,
    }
    aggregate_path = output_root / "benchmark_summary.json"
    aggregate_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
