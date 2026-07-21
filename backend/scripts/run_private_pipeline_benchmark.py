from __future__ import annotations

import argparse
from hashlib import sha256
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
    if firm_id not in FIRM_PROFILES:
        raise KeyError(f"verified private benchmark client profile missing: {firm_id}")
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


def _discover_firms(root: Path) -> list[str]:
    return sorted(
        path.name
        for path in root.glob("firma-*")
        if path.is_dir() and (path / "invoices").exists() and _chart_files(path)
    )


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


def _attempt_account_code(attempt: dict[str, object] | None) -> str:
    response = (attempt or {}).get("validated_response")
    if not isinstance(response, dict):
        return ""
    for decision in response.get("line_decisions") or []:
        if isinstance(decision, dict) and str(decision.get("suggested_account_code") or "").strip():
            return str(decision.get("suggested_account_code") or "").strip()
    return str(response.get("suggested_account_code") or response.get("selected_account_code") or "").strip()


def _stage_quality_record(result: object) -> dict[str, object]:
    attempts = [item for item in getattr(result, "semantic_attempts", ()) if isinstance(item, dict)]
    accepted_id = str(getattr(result, "accepted_semantic_attempt_id", "") or "")
    accepted_attempt = next((item for item in attempts if str(item.get("attempt_id") or "") == accepted_id), None)
    initial_attempt = next((item for item in attempts if item.get("stage") == "initial_account_decision"), None)
    initial_code = _attempt_account_code(initial_attempt)
    accepted_code = _attempt_account_code(accepted_attempt)
    selected_code = str(
        getattr(result, "selected_expense_account", "")
        or getattr(result, "selected_revenue_account", "")
        or ""
    )
    canonical_line_count = int(getattr(result, "canonical_line_count", 0) or 0)
    decision_ids = {
        str(item.get("canonical_line_id") or "")
        for item in getattr(result, "line_decisions", ())
        if isinstance(item, dict) and str(item.get("canonical_line_id") or "")
    }
    required_trace_fields = {
        "attempt_id", "stage", "canonical_line_ids", "validated_response", "validation_errors", "accepted"
    }
    trace_complete = bool(attempts) and all(required_trace_fields.issubset(item) for item in attempts)
    if accepted_id:
        trace_complete = trace_complete and accepted_attempt is not None
    reasons = {str(item) for item in getattr(result, "review_reason_codes", ())}
    vat_reconciled = str(getattr(result, "canonical_validation_status", "") or "") == "valid" and not any(
        "vat" in reason and ("mismatch" in reason or "invalid" in reason) for reason in reasons
    )
    source_name = str(getattr(result, "file_name", "") or "")
    return {
        "document_ref": sha256(source_name.encode("utf-8")).hexdigest()[:16],
        "source_type": Path(source_name).suffix.lower().lstrip(".") or "unknown",
        "canonical_line_count": canonical_line_count,
        "semantic_ai_called": bool(getattr(result, "ai_classification_used", False)),
        "verified_rule_applied": str(getattr(result, "ai_gate_reason", "") or "") == "verified_rule_binding",
        "initial_account_code": initial_code,
        "research_requested": bool(getattr(result, "ai_research_requested", False)),
        "research_changed_decision": bool(initial_code and accepted_code and initial_code != accepted_code),
        "accepted_account_code": accepted_code or selected_code,
        "deterministic_account_substitution": bool(accepted_code and selected_code and accepted_code != selected_code),
        "semantic_attempt_count": len(attempts),
        "line_coverage_ok": canonical_line_count > 0 and len(decision_ids) == canonical_line_count,
        "vat_reconciled": vat_reconciled,
        "balanced": bool(getattr(result, "is_balanced", False)),
        "export_status": str(getattr(result, "export_status", "") or ""),
        "trace_complete": trace_complete,
    }


def _quality_gates(records: list[dict[str, object]]) -> dict[str, object]:
    mechanical = [record for record in records if record.get("vat_reconciled")]
    return {
        "line_coverage_failures": sum(1 for record in records if not record.get("line_coverage_ok")),
        "deterministic_account_substitutions": sum(
            1 for record in records if record.get("deterministic_account_substitution")
        ),
        "incomplete_semantic_traces": sum(
            1
            for record in records
            if (record.get("semantic_ai_called") or record.get("research_requested")) and not record.get("trace_complete")
        ),
        "unbalanced_mechanical_invoices": sum(1 for record in mechanical if not record.get("balanced")),
    }


def _run_one(
    *,
    root: Path,
    output_root: Path,
    firm_id: str,
    run_label: str,
    classifier: object | None,
    canonical_extraction_provider: object | None,
    canonical_extraction_policy: object | None,
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
    if firm_id not in FIRM_PROFILES:
        return {
            "firm_id": firm_id,
            "run_label": run_label,
            "status": "blocked",
            "reason": "verified_client_profile_missing",
        }

    runs = simulate_private_matching(
        invoice_dir,
        chart_files,
        _client_profile(firm_id),
        product_classifier=classifier,
        canonical_extraction_provider=canonical_extraction_provider,
        canonical_extraction_policy=canonical_extraction_policy,
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
    stage_quality = [_stage_quality_record(result) for run in runs for result in run.invoice_results]
    summary["stage_quality"] = stage_quality
    summary["quality_gates"] = _quality_gates(stage_quality)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run private real-pilot pipeline benchmark for selected firms.")
    parser.add_argument("--root", default=str(ROOT / "private_samples" / "real_pilot"))
    parser.add_argument("--firm", action="append", default=[])
    parser.add_argument("--output-root", default="")
    parser.add_argument("--include-ai", action="store_true", help="Run AI tie-breaker pass using current process env.")
    args = parser.parse_args()

    root = Path(args.root)
    firms = args.firm or _discover_firms(root)
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
                canonical_extraction_provider=None,
                canonical_extraction_policy=None,
                ai_enabled=False,
            )
        )

    if args.include_ai:
        for firm_id in firms:
            runtime = build_ai_runtime_from_env(os.environ)
            classifier = runtime.get("product_classifier")
            canonical_extraction_provider = runtime.get("canonical_extraction_provider")
            canonical_extraction_policy = runtime.get("canonical_extraction_policy")
            summaries.append(
                _run_one(
                    root=root,
                    output_root=output_root,
                    firm_id=firm_id,
                    run_label="ai_tie_breaker",
                    classifier=classifier,
                    canonical_extraction_provider=canonical_extraction_provider,
                    canonical_extraction_policy=canonical_extraction_policy,
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
