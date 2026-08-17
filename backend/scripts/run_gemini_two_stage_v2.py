from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable, Mapping, Sequence
from uuid import uuid4


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.accounting_candidate_builder import build_accounting_candidates
from app.domain.document_ai_artifacts import ArtifactKind, DocumentAiArtifact
from app.domain.gemini_pdf_runtime import build_gemini_pdf_runtime_from_env
from app.domain.storage_adapters import LocalDocumentStorage
from app.persistence.document_ai_artifact_repository import (
    LocalDocumentAiArtifactRepository,
)
from app.workflows.gemini_invoice_pipeline import (
    GeminiInvoicePipelineRequest,
    GeminiInvoicePipelineResult,
    run_gemini_invoice_pipeline_v2,
)


_BASE_TOTAL_FIELDS = (
    "goods_services_total",
    "allowance_total",
    "vat_total",
    "tax_inclusive_total",
    "payable_total",
)

_ACCOUNTING_WARNING_CODES = {
    "accounting_expansion_failed",
    "accounting_selection_failed",
    "accounting_proposal_invalid",
    "candidate_expansion_limit_reached",
    "candidate_expansion_returned_no_new_candidates",
}


def probe_prerequisites(
    *,
    manifest_path: Path,
    workspace_path: Path,
    env: Mapping[str, str],
    tenant_id: str = "",
    taxpayer_id: str = "",
    price_profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return a value-free live-run readiness result.

    The report deliberately exposes requirement codes and counts, never paths,
    credentials, tenant identifiers, or document identifiers.
    """

    missing: list[str] = []
    if not str(env.get("GEMINI_API_KEY", "") or "").strip():
        missing.append("gemini_api_key")

    manifest = _read_mapping(manifest_path)
    workspace = _read_mapping(workspace_path)
    resolved_tenant = _first_text(tenant_id, manifest.get("tenant_id"))
    resolved_taxpayer = _first_text(
        taxpayer_id, manifest.get("taxpayer_id")
    )
    if not resolved_tenant:
        missing.append("tenant_identity")
    if not resolved_taxpayer:
        missing.append("taxpayer_identity")
    workspace_tenant = str(workspace.get("tenant_id") or "").strip()
    workspace_taxpayer = str(workspace.get("taxpayer_id") or "").strip()
    if (
        (resolved_tenant and workspace_tenant and resolved_tenant != workspace_tenant)
        or (
            resolved_taxpayer
            and workspace_taxpayer
            and resolved_taxpayer != workspace_taxpayer
        )
    ):
        missing.append("scope_identity_mismatch")

    if _validated_price_profile(price_profile or manifest.get("price_profile")) is None:
        missing.append("model_price_profile")

    revision = _chart_revision(workspace, manifest)
    if not revision:
        missing.append("chart_revision")
    try:
        candidates = build_accounting_candidates(workspace, {})
        has_active_coded_chart = any(
            item.active and str(item.code or "").strip()
            for item in candidates.real_candidates
        )
    except (TypeError, ValueError):
        has_active_coded_chart = False
    if not has_active_coded_chart:
        missing.append("active_coded_tenant_chart")

    raw_documents = _raw_manifest_documents(manifest)
    documents = _manifest_documents(manifest, manifest_path.parent)
    raw_document_count = len(raw_documents) if raw_documents is not None else 0
    expected_count = _positive_manifest_count(manifest.get("expected_document_count"))
    if (
        raw_documents is None
        or len(documents) != raw_document_count
        or (expected_count is not None and expected_count != raw_document_count)
        or len({document_id for document_id, _ in documents}) != len(documents)
    ):
        missing.append("manifest_documents")
    valid_document_count = sum(
        1
        for item in documents
        if _is_native_pdf(item[1])
    )
    if not documents or valid_document_count != raw_document_count:
        missing.append("native_pdf_documents")

    return {
        "status": "BLOCKED" if missing else "READY",
        "missing_prerequisites": tuple(dict.fromkeys(missing)),
        "document_count": raw_document_count,
        "valid_document_count": valid_document_count,
    }


def run_controlled_proof(
    *,
    manifest_path: Path,
    workspace_path: Path,
    output_dir: Path,
    env: Mapping[str, str],
    tenant_id: str = "",
    taxpayer_id: str = "",
    provider: object | None = None,
    price_profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run the isolated V2 pipeline with a fresh local artifact repository."""

    preflight = probe_prerequisites(
        manifest_path=Path(manifest_path),
        workspace_path=Path(workspace_path),
        env=env,
        tenant_id=tenant_id,
        taxpayer_id=taxpayer_id,
        price_profile=price_profile,
    )
    if preflight["status"] != "READY":
        return {
            "status": "BLOCKED",
            "missing_prerequisites": preflight["missing_prerequisites"],
            "document_count": preflight["document_count"],
        }

    selected_provider = provider
    if selected_provider is None:
        runtime = build_gemini_pdf_runtime_from_env(env)
        if not runtime.available or runtime.provider is None:
            return {
                "status": "BLOCKED",
                "missing_prerequisites": (runtime.unavailable_reason or "gemini_runtime",),
                "document_count": preflight["document_count"],
            }
        selected_provider = runtime.provider

    manifest = _read_mapping(Path(manifest_path))
    workspace = _read_mapping(Path(workspace_path))
    resolved_tenant = _first_text(tenant_id, manifest.get("tenant_id"))
    resolved_taxpayer = _first_text(
        taxpayer_id, manifest.get("taxpayer_id")
    )
    normalized_price_profile = _validated_price_profile(
        price_profile or manifest.get("price_profile")
    )
    assert normalized_price_profile is not None
    chart_revision = _chart_revision(workspace, manifest)
    documents = _manifest_documents(manifest, Path(manifest_path).parent)

    run_id = str(uuid4())
    run_dir = Path(output_dir) / f"run-{run_id}"
    repository = LocalDocumentAiArtifactRepository(
        manifest_path=run_dir / "artifacts.json",
        storage=LocalDocumentStorage(run_dir / "artifact-bodies"),
    )
    reports: list[dict[str, object]] = []
    for index, (document_id, pdf_path) in enumerate(documents, start=1):
        before_ids = _repository_document_ids(
            repository, resolved_tenant, resolved_taxpayer, document_id
        )
        source_bytes = pdf_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        result = run_gemini_invoice_pipeline_v2(
            GeminiInvoicePipelineRequest(
                tenant_id=resolved_tenant,
                taxpayer_id=resolved_taxpayer,
                document_id=document_id,
                source_file_id=f"source-{index}-{source_hash[:12]}",
                source_file_sha256=source_hash,
                source_bytes=source_bytes,
                workspace=workspace,
                chart_revision=chart_revision,
            ),
            extraction_provider=selected_provider,
            accounting_provider=selected_provider,
            artifact_repository=repository,
        )
        after_ids = _repository_document_ids(
            repository, resolved_tenant, resolved_taxpayer, document_id
        )
        current_ids = after_ids.difference(before_ids)
        reports.append(
            build_safe_document_report(
                result=result,
                artifact_repository=repository,
                current_run_artifact_ids=current_ids,
                price_profile=normalized_price_profile,
            )
        )

    aggregate = build_aggregate_report(reports)
    report = {
        "status": aggregate["status"],
        "run_id": run_id,
        "document_count": len(reports),
        "artifact_count": aggregate["artifact_count"],
        "provider_totals": aggregate["provider_totals"],
        "documents": reports,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def build_safe_document_report(
    *,
    result: GeminiInvoicePipelineResult,
    artifact_repository: LocalDocumentAiArtifactRepository,
    current_run_artifact_ids: Iterable[str],
    price_profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build an allowlisted report without raw or identifying invoice data."""

    current_ids = frozenset(str(value) for value in current_run_artifact_ids)
    projection = result.projection if isinstance(result.projection, Mapping) else {}
    draft_lines = tuple(result.draft.lines) if result.draft is not None else ()
    actual_refs = Counter(str(line.fact_ref or "").strip() for line in draft_lines)
    fact_groups = _projection_fact_groups(projection)
    integrity: dict[str, object] = {}
    for name, expected_refs in fact_groups.items():
        integrity[name] = _fact_integrity(expected_refs, actual_refs)

    party_values = _party_tax_id_presence(projection)
    party_integrity = integrity["party_vkn"]
    assert isinstance(party_integrity, dict)
    party_integrity["party_count"] = party_values[0]
    party_integrity["vkn_count"] = party_values[1]
    party_integrity["complete"] = bool(
        party_integrity["complete"] and party_values[0] >= 2 and party_values[1] >= 1
    )

    expected_refs = tuple(
        ref for values in fact_groups.values() for ref in values
    )
    unexpected_refs = sum(
        count for ref, count in actual_refs.items() if ref not in expected_refs
    )
    integrity["unexpected_draft_refs"] = {
        "count": unexpected_refs,
        "complete": unexpected_refs == 0,
    }
    amount_parity = bool(
        result.quality is not None
        and result.draft is not None
        and result.quality.draft == result.draft
    )
    integrity["amount_parity"] = {"complete": amount_parity}

    totals = projection.get("totals")
    totals = totals if isinstance(totals, Mapping) else {}
    required_total_fields = _required_total_fields(projection)
    total_present = sum(
        1 for key in required_total_fields if _valid_decimal_text(totals.get(key))
    )
    integrity["totals"] = {
        "expected": len(required_total_fields),
        "present": total_present,
        "missing": len(required_total_fields) - total_present,
        "duplicates": 0,
        "complete": total_present == len(required_total_fields),
    }
    integrity["all_facts_complete"] = all(
        bool(value.get("complete"))
        for key, value in integrity.items()
        if key != "all_facts_complete" and isinstance(value, Mapping)
    )

    artifacts = tuple(result.artifacts)
    lineage = _lineage_report(
        result=result,
        artifacts=artifacts,
        repository=artifact_repository,
        current_ids=current_ids,
    )
    provider_totals = _provider_totals(
        artifacts,
        current_ids,
        price_profile=price_profile,
    )

    unresolved_count = sum(
        1 for line in draft_lines if str(line.resolution or "").strip().lower() == "unresolved"
    )
    if result.proposal is not None:
        unresolved_count += len(result.proposal.unresolved_decision_refs)
    debit = sum((line.debit for line in draft_lines), Decimal("0"))
    credit = sum((line.credit for line in draft_lines), Decimal("0"))
    balanced = bool(
        result.draft is not None
        and result.draft.is_balanced
        and debit == credit
        and debit == result.draft.total_debit
        and credit == result.draft.total_credit
    )

    warning_report = _warning_report(result, artifacts, current_ids)
    warning_continued = bool(warning_report["pipeline_continued"])

    round_origins = _selection_origin_rounds(result)
    complete = bool(
        result.status == "complete"
        and result.draft is not None
        and balanced
        and unresolved_count == 0
        and integrity["all_facts_complete"]
        and lineage["current_run"]
        and warning_continued
        and provider_totals["pricing_valid"]
    )
    return {
        "document_id": _pseudonymous_document_id(result.document_id),
        "workflow_status": "complete" if complete else "partial",
        "integrity": integrity,
        "lineage": lineage,
        "candidate_rounds": {
            "initial_count": len(result.candidate_rounds[0].candidate_ids)
            if result.candidate_rounds
            else 0,
            "expansion_count": max(0, len(result.candidate_rounds) - 1),
            "round_count": len(result.candidate_rounds),
            "selection_origin_rounds": round_origins,
        },
        "warnings": warning_report,
        "draft": {
            "line_count": len(draft_lines),
            "unresolved_count": unresolved_count,
            "debit": _decimal_text(debit),
            "credit": _decimal_text(credit),
            "balanced": balanced,
        },
        "provider": provider_totals,
        "artifact_count": sum(1 for item in artifacts if item.artifact_id in current_ids),
    }


def build_aggregate_report(reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    artifact_count = sum(_safe_int(report.get("artifact_count")) for report in reports)
    elapsed_ms = 0
    prompt_tokens = 0
    candidate_tokens = 0
    total_tokens = 0
    estimated_cost = Decimal("0")
    model_counts: Counter[tuple[str, str]] = Counter()
    for report in reports:
        provider = report.get("provider")
        provider = provider if isinstance(provider, Mapping) else {}
        elapsed_ms += _safe_int(provider.get("elapsed_ms"))
        prompt_tokens += _safe_int(provider.get("prompt_tokens"))
        candidate_tokens += _safe_int(provider.get("candidate_tokens"))
        total_tokens += _safe_int(provider.get("total_tokens"))
        estimated_cost += _decimal(provider.get("estimated_cost"))
        profiles = provider.get("model_profiles")
        if isinstance(profiles, Sequence) and not isinstance(profiles, (str, bytes)):
            for profile in profiles:
                if isinstance(profile, Mapping):
                    model_counts[
                        (
                            str(profile.get("model_alias") or ""),
                            str(profile.get("resolved_model") or ""),
                        )
                    ] += _safe_int(profile.get("call_count"))

    status = "OK" if reports and all(_report_is_complete(item) for item in reports) else "NOT_OK"
    return {
        "status": status,
        "document_count": len(reports),
        "complete_count": sum(1 for item in reports if _report_is_complete(item)),
        "artifact_count": artifact_count,
        "provider_totals": {
            "elapsed_ms": elapsed_ms,
            "prompt_tokens": prompt_tokens,
            "candidate_tokens": candidate_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": _decimal_text(estimated_cost),
            "model_profiles": [
                {
                    "model_alias": alias,
                    "resolved_model": resolved,
                    "call_count": count,
                }
                for (alias, resolved), count in sorted(model_counts.items())
            ],
        },
    }


def _report_is_complete(report: Mapping[str, object]) -> bool:
    integrity = report.get("integrity")
    lineage = report.get("lineage")
    draft = report.get("draft")
    warnings = report.get("warnings")
    return bool(
        report.get("workflow_status") == "complete"
        and isinstance(integrity, Mapping)
        and integrity.get("all_facts_complete") is True
        and isinstance(lineage, Mapping)
        and lineage.get("current_run") is True
        and isinstance(draft, Mapping)
        and draft.get("balanced") is True
        and _safe_int(draft.get("unresolved_count")) == 0
        and isinstance(warnings, Mapping)
        and warnings.get("pipeline_continued") is True
        and isinstance(report.get("provider"), Mapping)
        and report["provider"].get("pricing_valid") is True
    )


def _projection_fact_groups(projection: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    groups: dict[str, list[str]] = {
        "line": [],
        "party_vkn": ["counterparty"],
        "vat": [],
        "non_vat_tax": [],
        "withholding": [],
        "monetary": [],
    }
    for item in _mapping_items(projection.get("line_items")):
        _append_identity(groups["line"], item)
    for item in _mapping_items(projection.get("vat_summary")):
        _append_identity(groups["vat"], item)
    for item in _mapping_items(projection.get("tax_components")):
        identity = _identity(item)
        if not identity:
            continue
        tax_text = " ".join(
            str(item.get(key) or "").strip().lower()
            for key in ("component_type", "canonical_tax_kind", "source_label", "source_code")
        )
        if identity.startswith("vat:") or str(
            item.get("canonical_tax_kind") or ""
        ).strip().lower() in {"vat", "kdv"}:
            continue
        destination = "withholding" if any(
            marker in tax_text for marker in ("withholding", "tevkifat", "stopaj")
        ) else "non_vat_tax"
        if identity not in groups[destination]:
            groups[destination].append(identity)
    for item in _mapping_items(projection.get("monetary_components")):
        _append_identity(groups["monetary"], item)
    return {key: tuple(value) for key, value in groups.items()}


def _fact_integrity(expected_refs: Sequence[str], actual_refs: Counter[str]) -> dict[str, object]:
    expected_counts = Counter(expected_refs)
    projection_duplicates = sum(max(0, count - 1) for count in expected_counts.values())
    missing = sum(
        max(0, expected_count - actual_refs.get(ref, 0))
        for ref, expected_count in expected_counts.items()
    )
    duplicates = sum(
        max(0, actual_refs.get(ref, 0) - expected_count)
        for ref, expected_count in expected_counts.items()
    )
    return {
        "expected": len(expected_refs),
        "observed": sum(actual_refs.get(ref, 0) for ref in expected_counts),
        "missing": missing,
        "duplicates": duplicates,
        "projection_duplicates": projection_duplicates,
        "complete": missing == 0 and duplicates == 0 and projection_duplicates == 0,
    }


def _lineage_report(
    *,
    result: GeminiInvoicePipelineResult,
    artifacts: Sequence[DocumentAiArtifact],
    repository: LocalDocumentAiArtifactRepository,
    current_ids: frozenset[str],
) -> dict[str, object]:
    required = {
        (ArtifactKind.PROVIDER_RECEIPT, "document_extraction"),
        (ArtifactKind.CANONICAL_INVOICE_FORM, "canonical_mapping"),
        (ArtifactKind.ACCOUNTING_INPUT_PROJECTION, "accounting_projection"),
        (ArtifactKind.PROVIDER_RECEIPT, "accounting_selection"),
        (ArtifactKind.ACCOUNTING_PROPOSAL, "accounting_selection"),
    }
    successful = {
        (item.kind, item.stage)
        for item in artifacts
        if item.artifact_id in current_ids and item.status == "successful"
    }
    result_ids = frozenset(item.artifact_id for item in artifacts)
    repository_records = repository.list_for_document(
        tenant_id=result.tenant_id,
        taxpayer_id=result.taxpayer_id,
        document_id=result.document_id,
    )
    repository_by_id = {item.artifact_id: item for item in repository_records}
    repository_membership = current_ids.issubset(repository_by_id)
    records_match = all(repository_by_id.get(item.artifact_id) == item for item in artifacts)
    scope_matches = all(
        item.tenant_id == result.tenant_id
        and item.taxpayer_id == result.taxpayer_id
        and item.document_id == result.document_id
        and item.source_file_sha256 == result.source_file_sha256
        for item in artifacts
    )
    traced_ids: frozenset[str] = frozenset()
    trace_valid = False
    if result.proposal_artifact_id:
        try:
            traced_ids = frozenset(
                item.artifact_id
                for item in repository.trace_lineage(
                    tenant_id=result.tenant_id,
                    taxpayer_id=result.taxpayer_id,
                    artifact_id=result.proposal_artifact_id,
                )
            )
            trace_valid = traced_ids.issubset(current_ids)
        except (KeyError, ValueError):
            trace_valid = False
    proposal_record = repository_by_id.get(result.proposal_artifact_id)
    typed_receipt = (
        repository_by_id.get(proposal_record.provider_receipt_artifact_id or "")
        if proposal_record is not None
        else None
    )
    component_ids = (
        tuple(proposal_record.component_receipt_artifact_ids)
        if proposal_record is not None and proposal_record.component_receipt_artifact_ids
        else ((proposal_record.provider_receipt_artifact_id,) if proposal_record is not None and proposal_record.provider_receipt_artifact_id else ())
    )
    component_receipts = tuple(repository_by_id.get(value) for value in component_ids)
    typed_receipt_valid = bool(
        proposal_record is not None
        and proposal_record.kind is ArtifactKind.ACCOUNTING_PROPOSAL
        and typed_receipt is not None
        and typed_receipt.artifact_id in current_ids
        and typed_receipt.kind is ArtifactKind.PROVIDER_RECEIPT
        and typed_receipt.stage == "accounting_selection"
        and typed_receipt.status == "successful"
        and proposal_record.provider_receipt_artifact_id in component_ids
        and all(
            item is not None
            and item.artifact_id in current_ids
            and item.kind is ArtifactKind.PROVIDER_RECEIPT
            and item.stage == "accounting_selection"
            and item.status == "successful"
            for item in component_receipts
        )
    )
    current_run = bool(
        artifacts
        and result_ids == current_ids
        and required.issubset(successful)
        and scope_matches
        and result.proposal_artifact_id in current_ids
        and trace_valid
        and repository_membership
        and records_match
        and typed_receipt_valid
    )
    return {
        "current_run": current_run,
        "artifact_count": len(current_ids.intersection(result_ids)),
        "required_stage_count": len(required),
        "present_stage_count": len(required.intersection(successful)),
        "trace_depth": len(traced_ids),
        "repository_membership": repository_membership,
        "typed_receipt_edge": typed_receipt_valid,
        "component_receipt_count": len(component_ids),
    }


def _provider_totals(
    artifacts: Sequence[DocumentAiArtifact],
    current_ids: frozenset[str],
    *,
    price_profile: Mapping[str, object] | None,
) -> dict[str, object]:
    receipts = tuple(
        item
        for item in artifacts
        if item.artifact_id in current_ids and item.kind is ArtifactKind.PROVIDER_RECEIPT
    )
    prompt = sum(_token_value(item.token_usage, "prompt_tokens", "input_tokens") for item in receipts)
    candidate = sum(
        _token_value(item.token_usage, "candidate_tokens", "output_tokens") for item in receipts
    )
    total = sum(
        _token_value(item.token_usage, "total_tokens")
        or (
            _token_value(item.token_usage, "prompt_tokens", "input_tokens")
            + _token_value(item.token_usage, "candidate_tokens", "output_tokens")
        )
        for item in receipts
    )
    normalized_profile = _validated_price_profile(price_profile)
    pricing_valid = bool(
        normalized_profile is not None
        and receipts
        and all(
            str(item.model_alias or "") == normalized_profile["model_alias"]
            and str(item.resolved_model or "") == normalized_profile["resolved_model"]
            for item in receipts
        )
    )
    input_price = _decimal(
        normalized_profile["input_price_per_million"] if normalized_profile else 0
    )
    output_price = _decimal(
        normalized_profile["output_price_per_million"] if normalized_profile else 0
    )
    cost = (
        Decimal(prompt) * input_price
        + Decimal(candidate) * output_price
    ) / Decimal("1000000")
    model_counts = Counter(
        (str(item.model_alias or ""), str(item.resolved_model or ""))
        for item in receipts
    )
    return {
        "call_count": len(receipts),
        "elapsed_ms": sum(_safe_int(item.elapsed_ms) for item in receipts),
        "prompt_tokens": prompt,
        "candidate_tokens": candidate,
        "total_tokens": total,
        "estimated_cost": _decimal_text(cost),
        "currency": normalized_profile["currency"] if normalized_profile else "",
        "pricing_valid": pricing_valid,
        "model_profiles": [
            {
                "model_alias": alias,
                "resolved_model": resolved,
                "call_count": count,
            }
            for (alias, resolved), count in sorted(model_counts.items())
        ],
        "status": "successful" if receipts and all(item.status == "successful" for item in receipts) else "partial",
    }


def _selection_origin_rounds(result: GeminiInvoicePipelineResult) -> tuple[int, ...]:
    if result.proposal is None:
        return ()
    selected = set(result.proposal.selected_candidate_ids)
    origins: list[int] = []
    for candidate_id in selected:
        for candidate_round in result.candidate_rounds:
            if candidate_id in candidate_round.candidate_ids:
                origins.append(candidate_round.round_index)
                break
    return tuple(sorted(origins))


def _warning_report(
    result: GeminiInvoicePipelineResult,
    artifacts: Sequence[DocumentAiArtifact],
    current_ids: frozenset[str],
) -> dict[str, object]:
    current = tuple(item for item in artifacts if item.artifact_id in current_ids)
    progression = tuple(sorted(current, key=lambda item: (item.created_at, item.revision_no)))
    canonical_artifact = next(
        (item for item in progression if item.kind is ArtifactKind.CANONICAL_INVOICE_FORM),
        None,
    )
    projection_artifact = next(
        (item for item in progression if item.kind is ArtifactKind.ACCOUNTING_INPUT_PROJECTION),
        None,
    )
    proposal_artifact = next(
        (item for item in progression if item.kind is ArtifactKind.ACCOUNTING_PROPOSAL),
        None,
    )
    accounting_receipts = tuple(
        item
        for item in progression
        if item.kind is ArtifactKind.PROVIDER_RECEIPT
        and item.stage == "accounting_selection"
    )
    proposal_receipt = next(
        (
            item
            for item in accounting_receipts
            if proposal_artifact is not None
            and item.artifact_id == proposal_artifact.provider_receipt_artifact_id
        ),
        None,
    )
    canonical_notes = set(
        str(value)
        for value in getattr(result.canonical_invoice, "extraction_notes", ())
        if str(value)
    )
    validation = getattr(result.canonical_invoice, "validation", None)
    canonical_notes.update(
        str(value) for value in getattr(validation, "reason_codes", ()) if str(value)
    )
    projection_notes = set(
        str(value)
        for value in (
            result.projection.get("projection_warnings", ())
            if isinstance(result.projection, Mapping)
            else ()
        )
        if str(value)
    )
    quality_notes = set(
        str(value)
        for value in getattr(result.quality, "warnings", ())
        if str(value)
    )

    proven = 0
    unproven = 0
    for warning in result.warnings:
        warning_text = str(warning)
        if warning_text in canonical_notes:
            source = canonical_artifact
            later = (projection_artifact, proposal_receipt, proposal_artifact)
        elif warning_text in projection_notes:
            source = projection_artifact
            later = (proposal_receipt, proposal_artifact)
        elif warning_text in _ACCOUNTING_WARNING_CODES:
            source = accounting_receipts[-1] if accounting_receipts else None
            later = (proposal_artifact,)
        elif warning_text in quality_notes:
            source = None
            later = ()
        else:
            source = None
            later = ()
        ordered = bool(
            source is not None
            and later
            and all(
                item is not None
                and item.status == "successful"
                and item.created_at > source.created_at
                for item in later
            )
        )
        if ordered:
            proven += 1
        else:
            unproven += 1

    count = len(tuple(result.warnings))
    later_artifacts_and_draft = bool(
        result.draft is not None and count > 0 and proven == count and unproven == 0
    )
    return {
        "count": count,
        "proven_count": proven,
        "unproven_count": unproven,
        "later_artifacts_and_draft": later_artifacts_and_draft,
        "pipeline_continued": count == 0 or later_artifacts_and_draft,
        "stage_progression": [
            {
                "ordinal": index,
                "stage": item.stage,
                "kind": item.kind.value,
                "status": item.status,
                "revision": item.revision_no,
            }
            for index, item in enumerate(progression, start=1)
        ],
    }


def _required_total_fields(projection: Mapping[str, object]) -> tuple[str, ...]:
    fields = list(_BASE_TOTAL_FIELDS)
    if _mapping_items(projection.get("tax_components")):
        fields.append("special_tax_total")
    return tuple(fields)


def _valid_decimal_text(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return Decimal(text).is_finite()
    except (InvalidOperation, ValueError):
        return False


def _validated_price_profile(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    required_text = ("model_alias", "resolved_model", "currency")
    normalized = {key: str(value.get(key) or "").strip() for key in required_text}
    if any(not normalized[key] for key in required_text):
        return None
    for key in ("input_price_per_million", "output_price_per_million"):
        raw = str(value.get(key) or "").strip()
        try:
            parsed = Decimal(raw)
        except (InvalidOperation, ValueError):
            return None
        if not parsed.is_finite() or parsed < 0:
            return None
        normalized[key] = format(parsed, "f")
    return normalized


def _repository_document_ids(
    repository: LocalDocumentAiArtifactRepository,
    tenant_id: str,
    taxpayer_id: str,
    document_id: str,
) -> frozenset[str]:
    return frozenset(
        item.artifact_id
        for item in repository.list_for_document(
            tenant_id=tenant_id,
            taxpayer_id=taxpayer_id,
            document_id=document_id,
        )
    )


def _raw_manifest_documents(manifest: Mapping[str, object]) -> Sequence[object] | None:
    for key in ("documents", "cases", "results"):
        value = manifest.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return value
    return None


def _positive_manifest_count(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return -1
    return parsed if parsed > 0 else -1


def _is_native_pdf(path: Path) -> bool:
    try:
        if (
            path.suffix.lower() != ".pdf"
            or not path.is_file()
            or path.stat().st_size <= 5
        ):
            return False
        with path.open("rb") as source:
            return source.read(5) == b"%PDF-"
    except OSError:
        return False


def _manifest_documents(
    manifest: Mapping[str, object], base_dir: Path
) -> tuple[tuple[str, Path], ...]:
    values = _raw_manifest_documents(manifest)
    if values is None:
        return ()
    documents: list[tuple[str, Path]] = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        document_id = str(
            item.get("document_id")
            or item.get("invoice_id")
            or item.get("id")
        ).strip()
        raw_path = str(
            item.get("pdf_path") or item.get("source_pdf") or item.get("path") or ""
        ).strip()
        if not document_id or not raw_path:
            continue
        path = Path(raw_path)
        if raw_path and not path.is_absolute():
            path = base_dir / path
        documents.append((document_id, path))
    return tuple(documents)


def _read_mapping(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _chart_revision(workspace: Mapping[str, object], manifest: Mapping[str, object]) -> str:
    chart = workspace.get("chart_accounts")
    chart = chart if isinstance(chart, Mapping) else {}
    return _first_text(
        chart.get("revision"), workspace.get("chart_revision"), manifest.get("chart_revision")
    )


def _party_tax_id_presence(projection: Mapping[str, object]) -> tuple[int, int]:
    parties = tuple(
        value
        for value in (projection.get("supplier_party"), projection.get("customer_party"))
        if isinstance(value, Mapping)
    )
    return len(parties), sum(1 for item in parties if str(item.get("tax_id") or "").strip())


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _append_identity(values: list[str], item: Mapping[str, object]) -> None:
    identity = _identity(item)
    if identity:
        values.append(identity)


def _identity(item: Mapping[str, object]) -> str:
    return str(item.get("identity_ref") or item.get("decision_ref") or "").strip()


def _first_text(*values: object) -> str:
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def _pseudonymous_document_id(document_id: str) -> str:
    digest = hashlib.sha256(str(document_id).encode("utf-8")).hexdigest()[:16]
    return f"document-{digest}"


def _token_value(usage: Mapping[str, object], *keys: str) -> int:
    for key in keys:
        value = _safe_int(usage.get(key))
        if value:
            return value
    return 0


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated Gemini two-stage V2 proof")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--taxpayer-id", default="")
    parser.add_argument("--price-model-alias", default="")
    parser.add_argument("--price-resolved-model", default="")
    parser.add_argument("--input-price-per-million", default="")
    parser.add_argument("--output-price-per-million", default="")
    parser.add_argument("--price-currency", default="")
    args = parser.parse_args(argv)
    cli_price_values = (
        args.price_model_alias,
        args.price_resolved_model,
        args.input_price_per_million,
        args.output_price_per_million,
        args.price_currency,
    )
    price_profile = (
        {
            "model_alias": args.price_model_alias,
            "resolved_model": args.price_resolved_model,
            "input_price_per_million": args.input_price_per_million,
            "output_price_per_million": args.output_price_per_million,
            "currency": args.price_currency,
        }
        if any(cli_price_values)
        else None
    )
    try:
        report = run_controlled_proof(
            manifest_path=args.manifest,
            workspace_path=args.workspace,
            output_dir=args.output_dir,
            env=os.environ,
            tenant_id=args.tenant_id,
            taxpayer_id=args.taxpayer_id,
            price_profile=price_profile,
        )
    except Exception:
        report = {
            "status": "BLOCKED",
            "missing_prerequisites": ("runner_execution_failed",),
            "document_count": 0,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
