from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.business_relevance import ClientProfile  # noqa: E402
from app.domain.matching_simulation import simulate_chart_run  # noqa: E402
from app.domain.xml_invoices import parse_xml_invoice  # noqa: E402
from app.workflows.document_processing import build_ai_runtime_from_env  # noqa: E402


PILOT_CASES = (
    ("easy", "19736107464_DZY2026000000288.xml", "ordinary hearing-device purchase"),
    ("easy", "26170052632_ABP2026000000581.xml", "ordinary hearing-device battery purchase"),
    ("easy", "2120473226_CPE2026000017190.xml", "ordinary merchandise purchase"),
    ("easy", "3250566851_QES2026000042355.xml", "ordinary e-invoice service purchase"),
    ("easy", "9860008925_YKA2026003309353.xml", "ordinary cargo service purchase"),
    ("hard", "4700022607_ES02026001604820.xml", "natural-gas utility with extra components"),
    ("hard", "4810577635_AS02026001010557.xml", "electricity utility with consumption tax"),
    ("hard", "8590491872_A322026000097438.xml", "internet utility with prior-period balance, device/installment and ÖİV"),
    ("hard", "9250353261_N3F2026000841471.xml", "GSM utility with ÖİV and radio usage fee"),
    ("hard", "3210362123_SV02026000010240.xml", "fully discounted zero-payable invoice"),
)


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


def _client_profile(path: Path) -> ClientProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))["profile"]
    return ClientProfile(
        client_id=str(payload["client_id"]),
        title=str(payload["title"]),
        tax_id=str(payload["tax_id"]),
        activity_description=str(payload["activity_description"]),
        workplace_addresses=tuple(str(item) for item in payload["workplace_addresses"]),
        has_chart_accounts=bool(payload["has_chart_accounts"]),
        nace_code=str(payload.get("nace_code") or ""),
    )


def _report(*, chart_path: Path, records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "ubl-utility-pilot-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source_adapter": "ubl_xml",
        "pdf_used": False,
        "tenant_chart_file": chart_path.name,
        "invoice_count": len(records),
        "easy_count": sum(item["difficulty"] == "easy" for item in records),
        "hard_count": sum(item["difficulty"] == "hard" for item in records),
        "canonical_usable_count": sum(
            item["canonical_validation_status"] in {"valid", "partial_valid"} for item in records
        ),
        "balanced_draft_count": sum(bool(item["is_balanced"]) for item in records),
        "export_ready_count": sum(item["export_status"] == "export_ready" for item in records),
        "no_posting_count": sum(item["simulated_status"] == "no_posting" for item in records),
        "review_required_count": sum(item["simulated_status"] == "review_required" for item in records),
        "records": records,
    }


def run_pilot(
    *,
    env_file: Path,
    chart_path: Path,
    invoice_root: Path,
    profile_path: Path,
    cases: tuple[tuple[str, str, str], ...] = PILOT_CASES,
    classification_provider: str = "",
) -> dict[str, object]:
    env = _load_env_file(env_file)
    if classification_provider:
        env["FISORA_AI_PROVIDER_CHAIN"] = classification_provider
        env["FISORA_AI_CLASSIFICATION_PROVIDER_CHAIN"] = classification_provider
        env["FISORA_AI_COUNTERPARTY_PROVIDER_CHAIN"] = classification_provider
        env["FISORA_AI_MAX_PROVIDER_CALLS"] = "2"
        if classification_provider == "nvidia":
            env["FISORA_NVIDIA_TIMEOUT_SECONDS"] = "45"
    runtime = build_ai_runtime_from_env(env)
    classifier = runtime.get("product_classifier")
    if classifier is None:
        raise RuntimeError("Configured AI classification provider is unavailable")
    invoices = [parse_xml_invoice(invoice_root / file_name) for _, file_name, _ in cases]
    run = simulate_chart_run(
        chart_path,
        invoices,
        client_profile=_client_profile(profile_path),
        product_classifier=classifier,
        intended_direction="purchase",
    )
    result_by_file = {result.file_name: result for result in run.invoice_results}
    invoice_by_file = {invoice.file_name: invoice for invoice in invoices}
    records: list[dict[str, object]] = []
    for difficulty, file_name, rationale in cases:
        invoice = invoice_by_file[file_name]
        result = result_by_file[file_name]
        record = {
            "difficulty": difficulty,
            "selection_rationale": rationale,
            "file_name": file_name,
            "invoice_no": invoice.invoice_no,
            "supplier_title": invoice.issuer_title,
            "service_profile": invoice.service_profile,
            "payable_total": invoice.payable_total,
            "canonical_validation_status": invoice.canonical_invoice.validation.status,
            "canonical_validation_reasons": list(invoice.canonical_invoice.validation.reason_codes),
            "canonical_line_count": len(invoice.canonical_invoice.line_items),
            "tax_components": [asdict(component) for component in invoice.tax_components],
            "monetary_components": [asdict(component) for component in invoice.monetary_components],
            "ai_used": result.ai_classification_used,
            "ai_provider": result.ai_classification_provider,
            "ai_resolution_status": result.ai_resolution_status,
            "ai_candidate_strategy": result.ai_candidate_strategy,
            "ai_account_candidate_count": result.ai_account_candidate_count,
            "selected_expense_account": result.selected_expense_account,
            "selected_vat_account": result.selected_vat_account,
            "selected_supplier_account": result.selected_supplier_account,
            "draft_lines": list(result.draft_lines),
            "is_balanced": result.is_balanced,
            "total_debit": result.total_debit,
            "total_credit": result.total_credit,
            "simulated_status": result.simulated_status,
            "draft_quality": result.draft_quality,
            "export_status": result.export_status,
            "review_reason_codes": list(result.review_reason_codes),
            "accountant_action_hint": result.accountant_action_hint,
            "ai_trace": list(result.ai_trace),
        }
        records.append(record)
    return _report(chart_path=chart_path, records=records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a 5-easy/5-hard real UBL accounting pilot.")
    base = ROOT / "private_samples" / "real_pilot" / "firma-7"
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy" / "production.env")
    parser.add_argument("--chart", type=Path, default=base / "chart_accounts" / "chart_accounts.xlsx")
    parser.add_argument("--invoice-root", type=Path, default=base / "invoices" / "purchases")
    parser.add_argument(
        "--profile",
        type=Path,
        default=base / "tax_certificate" / "parsed_tax_certificate_profile.json",
    )
    parser.add_argument("--output", type=Path, default=base / "analysis" / "ubl_utility_pilot.json")
    parser.add_argument("--case-index", type=int, choices=range(1, len(PILOT_CASES) + 1))
    parser.add_argument("--classification-provider", default="")
    parser.add_argument("--merge-dir", type=Path)
    args = parser.parse_args()
    if args.merge_dir:
        records: list[dict[str, object]] = []
        for path in sorted(args.merge_dir.glob("case-*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.extend(payload.get("records") or [])
        expected_files = {item[1] for item in PILOT_CASES}
        observed_files = {str(item.get("file_name") or "") for item in records}
        if expected_files != observed_files:
            missing = sorted(expected_files - observed_files)
            raise RuntimeError(f"Pilot case outputs incomplete: {missing}")
        order = {file_name: index for index, (_, file_name, _) in enumerate(PILOT_CASES)}
        records.sort(key=lambda item: order[str(item["file_name"])])
        report = _report(chart_path=args.chart, records=records)
    else:
        cases = (PILOT_CASES[args.case_index - 1],) if args.case_index else PILOT_CASES
        report = run_pilot(
            env_file=args.env_file,
            chart_path=args.chart,
            invoice_root=args.invoice_root,
            profile_path=args.profile,
            cases=cases,
            classification_provider=args.classification_provider,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "records"}
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
