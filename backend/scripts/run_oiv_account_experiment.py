from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.chart_accounts import parse_chart_accounts  # noqa: E402
from app.domain.tax_component_accounting import (  # noqa: E402
    build_tax_component_account_experiment_request,
    validate_tax_component_account_experiment_response,
)
from app.domain.xml_invoices import parse_xml_invoice  # noqa: E402
from app.workflows.document_processing import build_ai_runtime_from_env  # noqa: E402


def _load_env_file(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError(f"Environment file encoding is unsupported: {path}")
    env: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def _default_invoice_paths() -> tuple[Path, ...]:
    root = ROOT / "private_samples" / "real_pilot" / "firma-7" / "invoices" / "purchases"
    return (
        root / "8590491872_A322026000097438.xml",
        root / "9250353261_N3F2026000841471.xml",
    )


def run_experiment(*, env_file: Path, chart_path: Path, invoice_paths: tuple[Path, ...], trials: int) -> dict[str, object]:
    env = _load_env_file(env_file)
    runtime = build_ai_runtime_from_env(env)
    classifier = runtime.get("product_classifier")
    provider = getattr(classifier, "provider", None)
    if provider is None:
        raise RuntimeError("Configured AI classification provider is unavailable")
    accounts = parse_chart_accounts(chart_path)
    observations: list[dict[str, object]] = []
    for invoice_path in invoice_paths:
        invoice = parse_xml_invoice(invoice_path)
        component = next(
            item
            for item in invoice.tax_components
            if item.canonical_tax_kind == "special_communication_tax"
        )
        request = build_tax_component_account_experiment_request(
            component=component,
            service_profile=invoice.service_profile,
            supplier_title=invoice.issuer_title,
            accounts=accounts,
            client_activity="İşitme cihazı satış ve uygulama merkezi",
        )
        candidate_names = {
            str(item["code"]): str(item["name"])
            for item in request.context.account_candidate_details
        }
        for trial in range(1, trials + 1):
            try:
                response = provider.classify_product(request)
                validated = validate_tax_component_account_experiment_response(request=request, response=response)
                error = ""
            except Exception as exc:  # provider boundary is reported, never allowed to expose secrets
                validated = {
                    "accepted": False,
                    "category": "",
                    "confidence": -1,
                    "reason": "",
                    "selected_account_code": "",
                    "validation_errors": ("provider_error",),
                }
                error = type(exc).__name__
            selected = str(validated["selected_account_code"])
            observations.append(
                {
                    "invoice_file": invoice_path.name,
                    "invoice_no": invoice.invoice_no,
                    "supplier_title": invoice.issuer_title,
                    "service_profile": invoice.service_profile,
                    "source_tax_code": component.source_code,
                    "source_tax_label": component.source_label,
                    "taxable_amount": component.taxable_amount,
                    "tax_amount": component.tax_amount,
                    "trial": trial,
                    **validated,
                    "selected_account_name": candidate_names.get(selected, ""),
                    "provider": str(getattr(provider, "last_provider_name", "") or getattr(provider, "provider_name", "")),
                    "provider_error_type": error,
                    "candidate_codes": list(request.context.account_candidates),
                }
            )
    accepted_codes = [
        str(item["selected_account_code"])
        for item in observations
        if item["accepted"]
    ]
    consistent = bool(accepted_codes) and len(accepted_codes) == len(observations) and len(set(accepted_codes)) == 1
    return {
        "schema_version": "oiv-account-experiment-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "policy_hint_included": False,
        "trial_count": len(observations),
        "all_responses_accepted": all(bool(item["accepted"]) for item in observations),
        "consistent_selection": consistent,
        "selected_account_code_if_consistent": accepted_codes[0] if consistent else "",
        "observations": observations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the controlled ÖİV tenant-chart account experiment.")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy" / "production.env")
    parser.add_argument(
        "--chart",
        type=Path,
        default=ROOT / "private_samples" / "real_pilot" / "firma-7" / "chart_accounts" / "chart_accounts.xlsx",
    )
    parser.add_argument("--invoice", type=Path, action="append", dest="invoices")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "private_samples" / "real_pilot" / "firma-7" / "analysis" / "oiv_account_experiment.json",
    )
    args = parser.parse_args()
    invoice_paths = tuple(args.invoices) if args.invoices else _default_invoice_paths()
    result = run_experiment(
        env_file=args.env_file,
        chart_path=args.chart,
        invoice_paths=invoice_paths,
        trials=max(1, args.trials),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
