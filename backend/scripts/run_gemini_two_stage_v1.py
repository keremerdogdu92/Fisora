from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.document_ai_artifacts import ArtifactKind  # noqa: E402
from app.domain.openai_provider import DEFAULT_GEMINI_MODEL, GeminiAccountingProvider  # noqa: E402
from app.domain.storage_adapters import LocalDocumentStorage  # noqa: E402
from app.persistence.document_ai_artifact_repository import (  # noqa: E402
    LocalDocumentAiArtifactRepository,
)
from app.workflows.document_processing import run_gemini_two_stage_invoice_workflow  # noqa: E402


DEFAULT_INPUT_PRICE_PER_MILLION = "0.50"
DEFAULT_OUTPUT_PRICE_PER_MILLION = "2.50"
_MODEL_PRICE_PROFILES = {
    "gemini-flash-lite-latest": (
        DEFAULT_INPUT_PRICE_PER_MILLION,
        DEFAULT_OUTPUT_PRICE_PER_MILLION,
    ),
    "gemini-3.5-flash-lite": (
        DEFAULT_INPUT_PRICE_PER_MILLION,
        DEFAULT_OUTPUT_PRICE_PER_MILLION,
    ),
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_DRAFT_STATUSES = {
    "review_required",
    "ready_for_review",
    "partial_review_required",
    "no_posting",
    "unknown",
}
_SAFE_DRAFT_ROLES = {
    "canonical_line",
    "vat_group",
    "special_tax",
    "counterparty",
    "balancing",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def _manifest_documents(payload: Mapping[str, Any], *, manifest_path: Path) -> list[dict[str, str]]:
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raw_documents = payload.get("cases")
    if not isinstance(raw_documents, list):
        raw_documents = payload.get("results")
    if not isinstance(raw_documents, list):
        raise ValueError("manifest must contain documents, cases, or results")
    documents: list[dict[str, str]] = []
    for index, raw in enumerate(raw_documents):
        item = raw if isinstance(raw, Mapping) else {}
        document_id = str(
            item.get("document_id")
            or item.get("invoice_id")
            or item.get("id")
            or f"document-{index + 1}"
        ).strip()
        raw_path = str(item.get("pdf_path") or item.get("source_pdf") or "").strip()
        path = Path(raw_path)
        if raw_path and not path.is_absolute():
            path = manifest_path.parent / path
        documents.append(
            {
                "document_id": document_id,
                "pdf_path": str(path) if raw_path else "",
                "category": str(item.get("category") or item.get("intake_category") or "").strip(),
            }
        )
    return documents


def _workspace_has_chart(payload: Mapping[str, Any]) -> bool:
    chart = payload.get("chart_accounts")
    if not isinstance(chart, Mapping) or not isinstance(chart.get("accounts"), list):
        return False
    return any(
        isinstance(item, Mapping)
        and str(item.get("normalized_account_code") or item.get("raw_account_code") or "").strip()
        and item.get("is_detail_account", True) is not False
        for item in chart["accounts"]
    )


def _scope_identity(
    *,
    manifest: Mapping[str, Any],
    workspace: Mapping[str, Any],
    tenant_id: str = "",
    taxpayer_id: str = "",
) -> tuple[str, str]:
    return (
        str(tenant_id or workspace.get("tenant_id") or manifest.get("tenant_id") or "").strip(),
        str(
            taxpayer_id
            or workspace.get("taxpayer_id")
            or manifest.get("taxpayer_id")
            or ""
        ).strip(),
    )


def _selected_model(*, manifest: Mapping[str, Any], env: Mapping[str, str]) -> str:
    return str(
        env.get("FISORA_GEMINI_MODEL")
        or manifest.get("model_alias")
        or manifest.get("model")
        or DEFAULT_GEMINI_MODEL
    ).strip()


def _price_rates(
    *,
    model_alias: str,
    input_price_per_million: str | None,
    output_price_per_million: str | None,
) -> tuple[str, str] | None:
    if input_price_per_million is not None and output_price_per_million is not None:
        try:
            if Decimal(str(input_price_per_million)) < 0 or Decimal(str(output_price_per_million)) < 0:
                return None
        except InvalidOperation:
            return None
        return str(input_price_per_million), str(output_price_per_million)
    if input_price_per_million is not None or output_price_per_million is not None:
        return None
    normalized = model_alias.strip().lower()
    if normalized in _MODEL_PRICE_PROFILES:
        return _MODEL_PRICE_PROFILES[normalized]
    return next(
        (
            rates
            for model, rates in _MODEL_PRICE_PROFILES.items()
            if normalized.startswith(f"{model}-")
        ),
        None,
    )


def probe_prerequisites(
    *,
    manifest_path: Path,
    workspace_path: Path,
    env: Mapping[str, str],
    tenant_id: str = "",
    taxpayer_id: str = "",
    input_price_per_million: str | None = None,
    output_price_per_million: str | None = None,
) -> dict[str, object]:
    """Return blocker categories and counts without returning paths or env values."""

    missing: list[str] = []
    if not str(env.get("GEMINI_API_KEY") or "").strip():
        missing.append("gemini_api_key")

    documents: list[dict[str, str]] = []
    manifest: dict[str, Any] = {}
    if not manifest_path.exists() or not manifest_path.is_file():
        missing.append("benchmark_manifest")
    else:
        try:
            manifest = _load_json(manifest_path)
            documents = _manifest_documents(manifest, manifest_path=manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            missing.append("valid_benchmark_manifest")

    workspace: dict[str, Any] = {}
    if not workspace_path.exists() or not workspace_path.is_file():
        missing.append("workspace_file")
    else:
        try:
            workspace = _load_json(workspace_path)
            if not _workspace_has_chart(workspace):
                missing.append("tenant_chart_accounts")
        except (OSError, ValueError, json.JSONDecodeError):
            missing.append("valid_workspace_file")

    resolved_tenant_id, resolved_taxpayer_id = _scope_identity(
        manifest=manifest,
        workspace=workspace,
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
    )
    if not resolved_tenant_id:
        missing.append("tenant_identity")
    if not resolved_taxpayer_id:
        missing.append("taxpayer_identity")
    model_alias = _selected_model(manifest=manifest, env=env)
    if _price_rates(
        model_alias=model_alias,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
    ) is None:
        missing.append("model_pricing")

    available = sum(
        1
        for item in documents
        if item["pdf_path"] and Path(item["pdf_path"]).exists() and Path(item["pdf_path"]).is_file()
    )
    missing_documents = len(documents) - available
    if missing_documents:
        missing.append(f"document_files:{missing_documents}")
    if not documents and "benchmark_manifest" not in missing and "valid_benchmark_manifest" not in missing:
        missing.append("document_files:0_available")
    return {
        "status": "BLOCKED" if missing else "READY",
        "missing_prerequisites": missing,
        "document_count": len(documents),
        "available_document_count": available,
    }


def _kind_value(artifact: object) -> str:
    kind = getattr(artifact, "kind", "")
    return str(getattr(kind, "value", kind) or "")


def _safe_identifier(value: object, *, prefix: str) -> str:
    text = str(value or "").strip()
    if _SAFE_IDENTIFIER.fullmatch(text):
        return text
    return f"{prefix}-{sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _document_pseudonym(value: object) -> str:
    return f"document-{sha256(str(value or '').encode('utf-8')).hexdigest()[:16]}"


def _fact_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    supplier = payload.get("supplier_party")
    customer = payload.get("customer_party")
    party_tax_id_count = sum(
        1
        for party in (supplier, customer)
        if isinstance(party, Mapping) and str(party.get("tax_id") or "").strip()
    )
    totals = payload.get("totals")
    total_count = sum(
        1
        for value in (
            (
                totals.get("goods_services_total"),
                totals.get("allowance_total"),
                totals.get("vat_total"),
                totals.get("special_tax_total"),
                totals.get("tax_inclusive_total"),
                totals.get("payable_total"),
            )
            if isinstance(totals, Mapping)
            else ()
        )
        if str(value or "").strip()
    )
    return {
        "line_count": len(payload.get("line_items") or ()),
        "party_tax_id_count": party_tax_id_count,
        "vat_group_count": len(payload.get("vat_summary") or ()),
        "tax_component_count": len(payload.get("tax_components") or ()),
        "total_count": total_count,
    }


def _selected_fields(value: object, fields: Sequence[str]) -> dict[str, object]:
    item = value if isinstance(value, Mapping) else {}
    return {field: item.get(field) for field in fields}


def _fact_value_sets(payload: Mapping[str, Any]) -> dict[str, object]:
    parties = [
        _selected_fields(payload.get(name), ("tax_id", "tax_id_type"))
        for name in ("supplier_party", "customer_party")
    ]
    line_fields = (
        "canonical_line_id",
        "description",
        "quantity",
        "unit_code",
        "unit_price",
        "unit_price_basis",
        "taxable_amount",
        "vat_rate",
        "tax_amount",
        "gross_amount",
        "tax_scheme_code",
        "tax_category_code",
        "exemption_reason_code",
        "vat_group_id",
    )
    vat_fields = (
        "rate",
        "taxable_amount",
        "tax_amount",
        "tax_scheme_code",
        "tax_category_code",
        "exemption_reason_code",
        "vat_group_id",
        "contributing_line_ids",
    )
    tax_fields = (
        "component_type",
        "source_label",
        "source_code",
        "rate",
        "taxable_amount",
        "tax_amount",
        "canonical_tax_kind",
        "accounting_treatment",
    )
    total_fields = (
        "goods_services_total",
        "allowance_total",
        "vat_total",
        "special_tax_total",
        "tax_inclusive_total",
        "payable_total",
    )
    return {
        "party_tax_ids": parties,
        "line_items": [
            _selected_fields(item, line_fields) for item in payload.get("line_items") or ()
        ],
        "vat_summary": [
            _selected_fields(item, vat_fields) for item in payload.get("vat_summary") or ()
        ],
        "tax_components": [
            _selected_fields(item, tax_fields) for item in payload.get("tax_components") or ()
        ],
        "totals": _selected_fields(payload.get("totals"), total_fields),
    }


def _fact_hash(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _token_counts(artifacts: Iterable[object]) -> dict[str, int]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for artifact in artifacts:
        if _kind_value(artifact) != ArtifactKind.PROVIDER_RECEIPT.value:
            continue
        usage = getattr(artifact, "token_usage", {})
        usage = usage if isinstance(usage, Mapping) else {}
        prompt = int(usage.get("prompt_tokens") or usage.get("promptTokenCount") or 0)
        candidate = int(usage.get("candidate_tokens") or usage.get("candidatesTokenCount") or 0)
        input_tokens += prompt
        output_tokens += candidate
        total_tokens += int(usage.get("total_tokens") or usage.get("totalTokenCount") or prompt + candidate)
    return {"input": input_tokens, "output": output_tokens, "total": total_tokens}


def _estimated_cost(
    tokens: Mapping[str, int],
    *,
    input_price_per_million: str,
    output_price_per_million: str,
) -> str:
    try:
        input_rate = Decimal(str(input_price_per_million))
        output_rate = Decimal(str(output_price_per_million))
    except InvalidOperation as exc:
        raise ValueError("price rates must be decimal values") from exc
    cost = (
        Decimal(tokens["input"]) * input_rate
        + Decimal(tokens["output"]) * output_rate
    ) / Decimal("1000000")
    return f"{cost:.6f}"


def _draft_is_balanced(lines: Sequence[object]) -> bool:
    if not lines:
        return False
    try:
        debit = sum(
            (Decimal(str(item.get("debit") or "0")) for item in lines if isinstance(item, Mapping)),
            Decimal("0"),
        )
        credit = sum(
            (Decimal(str(item.get("credit") or "0")) for item in lines if isinstance(item, Mapping)),
            Decimal("0"),
        )
    except InvalidOperation:
        return False
    return debit == credit


def build_safe_document_report(
    *,
    document_id: str,
    source_sha256: str,
    result: Mapping[str, Any],
    artifacts: Sequence[object],
    canonical_payload: Mapping[str, Any],
    projection_payload: Mapping[str, Any],
    canonical_size_bytes: int,
    projection_size_bytes: int,
    input_price_per_million: str = DEFAULT_INPUT_PRICE_PER_MILLION,
    output_price_per_million: str = DEFAULT_OUTPUT_PRICE_PER_MILLION,
) -> dict[str, object]:
    """Build an allow-listed report; never copy raw invoice or provider values."""

    canonical_counts = _fact_counts(canonical_payload)
    projection_counts = _fact_counts(projection_payload)
    canonical_facts = _fact_value_sets(canonical_payload)
    projection_facts = _fact_value_sets(projection_payload)
    retained = {
        key: _fact_hash(projection_facts[key]) == _fact_hash(canonical_facts[key])
        for key in canonical_facts
    }
    retained["all_accounting_facts"] = all(retained.values())
    warnings = result.get("pipeline_warnings")
    warning_count = len(warnings) if isinstance(warnings, (list, tuple)) else 0
    draft_lines = result.get("draft_lines")
    draft_lines = draft_lines if isinstance(draft_lines, list) else []
    role_counts: Counter[str] = Counter()
    for line in draft_lines:
        role = str(line.get("proposal_role") or "") if isinstance(line, Mapping) else ""
        role_counts[role if role in _SAFE_DRAFT_ROLES else "other"] += 1
    proposal = result.get("accounting_proposal")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    artifact_ids = result.get("document_ai_artifacts")
    artifact_ids = artifact_ids if isinstance(artifact_ids, Mapping) else {}
    tokens = _token_counts(artifacts)
    elapsed_ms = sum(
        int(getattr(item, "elapsed_ms", 0) or 0)
        for item in artifacts
        if _kind_value(item) == ArtifactKind.PROVIDER_RECEIPT.value
    )
    status = str(
        result.get("draft_status")
        or result.get("status")
        or result.get("simulated_status")
        or "unknown"
    )
    if status not in _SAFE_DRAFT_STATUSES:
        status = "unknown"
    safe_artifact_ids = {
        key: _safe_identifier(artifact_ids.get(key), prefix="artifact")
        for key in (
            "extraction_receipt_id",
            "canonical_invoice_form_id",
            "accounting_input_projection_id",
            "accounting_proposal_id",
        )
        if artifact_ids.get(key)
    }
    progressed_stages = {
        (str(getattr(item, "stage", "") or ""), _kind_value(item))
        for item in artifacts
        if str(getattr(item, "status", "") or "") in {"successful", "partial"}
    }
    successful_stages = {
        (str(getattr(item, "stage", "") or ""), _kind_value(item))
        for item in artifacts
        if str(getattr(item, "status", "") or "") == "successful"
    }
    required_stage_artifacts = {
        ("document_extraction", ArtifactKind.PROVIDER_RECEIPT.value),
        ("canonical_mapping", ArtifactKind.CANONICAL_INVOICE_FORM.value),
        ("accounting_projection", ArtifactKind.ACCOUNTING_INPUT_PROJECTION.value),
        ("accounting_selection", ArtifactKind.PROVIDER_RECEIPT.value),
        ("accounting_proposal", ArtifactKind.ACCOUNTING_PROPOSAL.value),
    }
    complete = (
        required_stage_artifacts.issubset(successful_stages)
        and status not in {"unknown", "no_posting"}
        and bool(draft_lines)
    )
    observed_stage = "source"
    if ("document_extraction", ArtifactKind.PROVIDER_RECEIPT.value) in progressed_stages:
        observed_stage = "extraction_receipt"
    if ("canonical_mapping", ArtifactKind.CANONICAL_INVOICE_FORM.value) in progressed_stages:
        observed_stage = "canonical"
    if ("accounting_projection", ArtifactKind.ACCOUNTING_INPUT_PROJECTION.value) in progressed_stages:
        observed_stage = "projection"
    if ("accounting_selection", ArtifactKind.PROVIDER_RECEIPT.value) in progressed_stages:
        observed_stage = "accounting_receipt"
    if ("accounting_proposal", ArtifactKind.ACCOUNTING_PROPOSAL.value) in progressed_stages:
        observed_stage = "proposal"
    if observed_stage in {"projection", "accounting_receipt", "proposal"} and draft_lines:
        observed_stage = "draft"
    return {
        "document_id": _document_pseudonym(document_id),
        "source_sha256": source_sha256 if re.fullmatch(r"[a-fA-F0-9]{64}", source_sha256) else "",
        "artifact_ids": safe_artifact_ids,
        "coverage": {
            "canonical": canonical_counts,
            "projection": projection_counts,
            "retained": retained,
        },
        "projection_size_ratio": (
            round(projection_size_bytes / canonical_size_bytes, 6)
            if canonical_size_bytes > 0
            else None
        ),
        "warnings": {
            "count": warning_count,
            "pipeline_continued": warning_count == 0 or observed_stage in {
                "projection",
                "accounting_receipt",
                "proposal",
                "draft",
            },
            "draft_retained": bool(draft_lines),
            "last_observed_stage": observed_stage,
        },
        "accounting": {
            "call_count": int(proposal.get("accounting_call_count") or 0),
            "expansion_count": int(proposal.get("expansion_count") or 0),
            "selection_origin_round": proposal.get("selection_origin_round"),
        },
        "provider": {
            "elapsed_ms": elapsed_ms,
            "tokens": tokens,
            "estimated_cost_usd": _estimated_cost(
                tokens,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            ),
        },
        "draft": {
            "status": status,
            "line_count": len(draft_lines),
            "is_balanced": (
                bool(result.get("is_balanced"))
                if "is_balanced" in result
                else _draft_is_balanced(draft_lines)
            ),
            "role_counts": dict(sorted(role_counts.items())),
        },
        "workflow_status": "complete" if complete else "partial",
    }


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _artifact_payload(
    repository: LocalDocumentAiArtifactRepository,
    *,
    tenant_id: str,
    taxpayer_id: str,
    artifacts: Sequence[object],
    kind: ArtifactKind,
) -> tuple[dict[str, Any], int]:
    artifact = next((item for item in artifacts if getattr(item, "kind", None) is kind), None)
    if artifact is None:
        return {}, 0
    content = repository.read_content(
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        artifact_id=str(getattr(artifact, "artifact_id")),
    )
    payload = json.loads(content.decode("utf-8"))
    return (dict(payload) if isinstance(payload, dict) else {}), len(content)


def run_controlled_proof(
    *,
    manifest_path: Path,
    workspace_path: Path,
    output_dir: Path,
    env: Mapping[str, str],
    tenant_id: str = "",
    taxpayer_id: str = "",
    input_price_per_million: str | None = None,
    output_price_per_million: str | None = None,
    provider: object | None = None,
) -> dict[str, object]:
    prerequisites = probe_prerequisites(
        manifest_path=manifest_path,
        workspace_path=workspace_path,
        env=env,
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
    )
    if prerequisites["status"] != "READY":
        return prerequisites

    manifest = _load_json(manifest_path)
    documents = _manifest_documents(manifest, manifest_path=manifest_path)
    workspace = _load_json(workspace_path)
    tenant_id, taxpayer_id = _scope_identity(
        manifest=manifest,
        workspace=workspace,
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
    )
    model_alias = _selected_model(manifest=manifest, env=env)
    price_rates = _price_rates(
        model_alias=model_alias,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
    )
    if price_rates is None:
        raise RuntimeError("validated model pricing disappeared")
    input_price_per_million, output_price_per_million = price_rates
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    run_dir = output_dir / "runs" / run_id
    repository = LocalDocumentAiArtifactRepository(
        manifest_path=run_dir / "artifact-manifest.json",
        storage=LocalDocumentStorage(run_dir / "artifact-bodies"),
    )
    if provider is None:
        provider = GeminiAccountingProvider(
            api_key=str(env["GEMINI_API_KEY"]),
            model=model_alias,
            generate_content_url=str(env.get("FISORA_GEMINI_GENERATE_CONTENT_URL") or ""),
            timeout_seconds=float(env.get("FISORA_GEMINI_TIMEOUT_SECONDS") or "60"),
            max_output_tokens=int(env.get("FISORA_GEMINI_MAX_OUTPUT_TOKENS") or "16384"),
            max_inline_pdf_bytes=int(env.get("FISORA_GEMINI_MAX_INLINE_PDF_BYTES") or "50000000"),
        )

    reports: list[dict[str, object]] = []
    for item in documents:
        document_id = item["document_id"]
        source_path = Path(item["pdf_path"])
        source_sha = sha256(source_path.read_bytes()).hexdigest()
        document = {
            "document_id": document_id,
            "document_ref": document_id,
            "source_file_id": source_sha,
            "storage_path": str(source_path),
            "document_type": "invoice",
            "intake_category": item["category"],
        }
        try:
            result = run_gemini_two_stage_invoice_workflow(
                document=document,
                job={
                    "document_ref": document_id,
                    "document_type": "invoice",
                    "intake_category": item["category"],
                },
                workspace=workspace,
                tenant_id=tenant_id,
                taxpayer_id=taxpayer_id,
                extraction_provider=provider,
                accounting_provider=provider,
                artifact_repository=repository,
            )
            artifacts = repository.list_for_document(
                tenant_id=tenant_id,
                taxpayer_id=taxpayer_id,
                document_id=document_id,
            )
            canonical, canonical_size = _artifact_payload(
                repository,
                tenant_id=tenant_id,
                taxpayer_id=taxpayer_id,
                artifacts=artifacts,
                kind=ArtifactKind.CANONICAL_INVOICE_FORM,
            )
            projection, projection_size = _artifact_payload(
                repository,
                tenant_id=tenant_id,
                taxpayer_id=taxpayer_id,
                artifacts=artifacts,
                kind=ArtifactKind.ACCOUNTING_INPUT_PROJECTION,
            )
            reports.append(
                build_safe_document_report(
                    document_id=document_id,
                    source_sha256=source_sha,
                    result=result,
                    artifacts=artifacts,
                    canonical_payload=canonical,
                    projection_payload=projection,
                    canonical_size_bytes=canonical_size,
                    projection_size_bytes=projection_size,
                    input_price_per_million=input_price_per_million,
                    output_price_per_million=output_price_per_million,
                )
            )
        except Exception:  # noqa: BLE001 - private failure details are intentionally omitted
            reports.append(
                {
                    "document_id": _document_pseudonym(document_id),
                    "source_sha256": source_sha,
                    "workflow_status": "failed",
                }
            )

    completed = sum(1 for item in reports if item.get("workflow_status") == "complete")
    partial = sum(1 for item in reports if item.get("workflow_status") == "partial")
    report: dict[str, object] = {
        "status": (
            "OK"
            if completed == len(reports)
            else "PARTIAL"
            if completed or partial
            else "FAILED"
        ),
        "run_id": run_id,
        "model_alias": _safe_identifier(model_alias, prefix="model"),
        "document_count": len(reports),
        "completed_document_count": completed,
        "documents": reports,
    }
    (output_dir / "proof-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the secret-safe Gemini two-stage V1 proof.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=BACKEND / "tmp" / "gemini-two-stage-v1-proof")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy" / "production.env")
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--taxpayer-id", default="")
    parser.add_argument("--input-price-per-million")
    parser.add_argument("--output-price-per-million")
    args = parser.parse_args()
    env = {**os.environ, **_load_env_file(args.env_file)}
    report = run_controlled_proof(
        manifest_path=args.manifest,
        workspace_path=args.workspace,
        output_dir=args.output_dir,
        env=env,
        tenant_id=args.tenant_id,
        taxpayer_id=args.taxpayer_id,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "OK" else 2 if report["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
