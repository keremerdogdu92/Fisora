from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.gemini_credential_slots import normalize_gemini_credential_slot
from app.persistence.postgres_workflow_store import tenant_uuid


CSV_COLUMNS = (
    "document_id",
    "pipeline_version",
    "processed_at",
    "draft_status",
    "account_selection_grade",
    "treatment_grade",
    "amount_balance_grade",
    "canonical_line_grade",
    "accountant_note",
)

_WARNING_METRICS = (
    "nonoperative_treatment_ignored",
    "treatment_clarification_attempted",
    "treatment_clarification_resolved",
    "treatment_clarification_review_required",
    "suggested_account_preserved",
    "true_unresolved_account",
    "semantic_conflict_warnings",
    "decision_integrity_rejections",
)
_REPRESENTATIVE_RECEIPT_KINDS = (
    "success",
    "normalization",
    "resolved_clarification",
    "failed_clarification",
    "suggested_account",
    "true_unresolved",
)


class PilotReportRefused(ValueError):
    """Raised when a result set is outside the approved adaptive-only cohort."""


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, (list, tuple)) else ()


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        values: list[str] = []
        for nested in value.values():
            values.extend(_strings(nested))
        return tuple(values)
    if isinstance(value, (list, tuple, set)):
        values = []
        for nested in value:
            values.extend(_strings(nested))
        return tuple(values)
    return ()


def _artifact_metadata(row: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _as_mapping(_as_mapping(artifact).get("metadata"))
        for artifact in _as_sequence(row.get("artifacts"))
    )


def _observed_experiment_percent(rows: Sequence[Mapping[str, object]]) -> int:
    values: list[int] = []
    for row in rows:
        result = _as_mapping(row.get("result"))
        candidates: list[object] = [result.get("candidate_experiment_percent")]
        for metadata in _artifact_metadata(row):
            candidates.append(metadata.get("candidate_experiment_percent"))
        for value in candidates:
            if value is None or value == "":
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise PilotReportRefused("invalid candidate experiment percent") from exc
            if not 0 <= parsed <= 100:
                raise PilotReportRefused("candidate experiment percent must be between 0 and 100")
            values.append(parsed)
    return max(values, default=0)


def _validate_adaptive_only(
    rows: Sequence[Mapping[str, object]],
    configured_experiment_percent: int | str | None,
) -> None:
    for row in rows:
        result = _as_mapping(row.get("result"))
        modes: list[object] = [result.get("candidate_discovery_mode")]
        modes.extend(metadata.get("candidate_discovery_mode") for metadata in _artifact_metadata(row))
        if any(str(mode or "").strip().lower() == "exhaustive" for mode in modes):
            raise PilotReportRefused("exhaustive candidate assignment is not accountant-pilot eligible")
    configured = configured_experiment_percent
    if configured is None:
        configured = os.environ.get("FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT", "0")
    try:
        configured_value = int(str(configured).strip() or "0")
    except ValueError as exc:
        raise PilotReportRefused("invalid candidate experiment percent") from exc
    if not 0 <= configured_value <= 100:
        raise PilotReportRefused("candidate experiment percent must be between 0 and 100")
    if configured_value != 0:
        raise PilotReportRefused("nonzero candidate experiment percent is not accountant-pilot eligible")
    if _observed_experiment_percent(rows) != 0:
        raise PilotReportRefused("observed nonzero candidate experiment percent is not accountant-pilot eligible")


def _normalized_job_status(value: object) -> str:
    status = str(value or "queued").strip().lower()
    return "completed" if status in {"complete", "completed", "success", "successful"} else status


def _proposal_payload(row: Mapping[str, object]) -> Mapping[str, object]:
    proposals = [
        _as_mapping(value)
        for value in _as_sequence(row.get("artifacts"))
        if str(_as_mapping(value).get("artifact_kind") or "") == "accounting_proposal"
    ]
    if not proposals:
        return {}
    content = proposals[-1].get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            content = {}
    payload = _as_mapping(content)
    nested = payload.get("proposal")
    return _as_mapping(nested) if isinstance(nested, Mapping) else payload


def _decision_map(proposal: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    values = _as_sequence(proposal.get("decisions"))
    result: dict[str, Mapping[str, object]] = {}
    counterparty = _as_mapping(proposal.get("counterparty"))
    if counterparty:
        result["counterparty"] = counterparty
    for value in values:
        decision = _as_mapping(value)
        ref = str(decision.get("decision_ref") or "").strip()
        if ref:
            result[ref] = decision
    return result


def _draft_map(row: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    result = _as_mapping(row.get("result"))
    return {
        str(_as_mapping(value).get("fact_ref") or "").strip(): _as_mapping(value)
        for value in _as_sequence(result.get("draft_lines"))
        if str(_as_mapping(value).get("fact_ref") or "").strip()
    }


def _issue_values(proposal: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(_as_mapping(value) for value in _as_sequence(proposal.get("validation_issues")))


def _semantic_conflict_refs(proposal: Mapping[str, object]) -> set[str]:
    return {
        str(_as_mapping(value).get("decision_ref") or "").strip()
        for value in _as_sequence(proposal.get("semantic_conflicts"))
        if str(_as_mapping(value).get("decision_ref") or "").strip()
    }


def _clarification_receipts(row: Mapping[str, object]) -> dict[str, list[Mapping[str, object]]]:
    indexed: dict[str, list[tuple[int, int, Mapping[str, object]]]] = {}
    for index, value in enumerate(_as_sequence(row.get("artifacts"))):
        artifact = _as_mapping(value)
        if str(artifact.get("artifact_kind") or "") != "provider_receipt":
            continue
        metadata = _as_mapping(artifact.get("metadata"))
        ref = str(metadata.get("clarification_for_ref") or "").strip()
        if ref and metadata.get("clarification_attempt") is not None:
            try:
                attempt = int(metadata.get("clarification_attempt"))
            except (TypeError, ValueError):
                # Invalid attempts are retained for evidence, but sort after
                # numeric attempts using the stable artifact order.
                attempt = -1
            indexed.setdefault(ref, []).append((attempt, index, artifact))
    return {
        ref: [item[2] for item in sorted(values, key=lambda item: (item[0], item[1]))]
        for ref, values in indexed.items()
    }


def _required_refs(proposal: Mapping[str, object], row: Mapping[str, object]) -> set[str]:
    refs = {
        str(value).strip()
        for value in _as_sequence(proposal.get("required_decision_refs"))
        if str(value).strip()
    }
    refs.update(_decision_map(proposal))
    refs.update(_draft_map(row))
    refs.update(_clarification_receipts(row))
    return refs


def _valid_candidate(decision: Mapping[str, object], sent_ids: set[str]) -> bool:
    selected = str(decision.get("selected_candidate_id") or "").strip()
    candidate = _as_mapping(decision.get("candidate"))
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    return bool(
        str(decision.get("action") or "") == "select_existing"
        and selected
        and selected in sent_ids
        and candidate_id == selected
        and candidate.get("active") is True
    )


def _operative_treatment(value: object) -> bool:
    treatment = str(value or "").strip()
    # A clarification is resolved when the final AI decision carries any
    # valid treatment and no review flag.  represented/excluded are valid
    # non-posting outcomes and must not be mistaken for an unresolved ref.
    return bool(treatment) and treatment != "other"


def _is_zero(value: object) -> bool:
    try:
        from decimal import Decimal

        return Decimal(str(value or "0")) == Decimal("0")
    except Exception:
        return False


def _safe_receipt_id(value: object) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate and re.fullmatch(r"[A-Za-z0-9._:-]+", candidate) else ""


def _set_representative(representative: dict[str, str], kind: str, value: object) -> None:
    safe = _safe_receipt_id(value)
    if safe:
        representative[kind] = safe


def _clarification_attempt_key(artifact: Mapping[str, object]) -> tuple[str, object]:
    metadata = _as_mapping(artifact.get("metadata"))
    raw_attempt = metadata.get("clarification_attempt")
    try:
        return ("numeric", int(raw_attempt))
    except (TypeError, ValueError):
        return ("raw", str(raw_attempt))


def _resolution_evidence(row: Mapping[str, object]) -> dict[str, object]:
    proposal = _proposal_payload(row)
    decisions = _decision_map(proposal)
    drafts = _draft_map(row)
    refs = _required_refs(proposal, row)
    sent_ids = {
        str(value).strip()
        for value in _as_sequence(proposal.get("sent_candidate_ids"))
        if str(value).strip()
    }
    issues = _issue_values(proposal)
    issue_refs = {
        str(issue.get("decision_ref") or "").strip()
        for issue in issues
        if str(issue.get("decision_ref") or "").strip()
    }
    refs.update(
        ref
        for ref in issue_refs
        if ref not in {"candidate_sufficiency", "candidate_sufficiency_invalid"}
    )
    refs.difference_update({"candidate_sufficiency", "candidate_sufficiency_invalid"})
    clarification = _clarification_receipts(row)
    metric_refs: dict[str, set[str]] = {metric: set() for metric in _WARNING_METRICS}
    representative: dict[str, str] = {}
    nonoperative_issue_count = 0
    for issue in issues:
        ref = str(issue.get("decision_ref") or "").strip()
        if issue.get("code") == "nonoperative_treatment_ignored":
            nonoperative_issue_count += 1
            if ref:
                metric_refs["nonoperative_treatment_ignored"].add(ref)
            _set_representative(representative, "normalization", issue.get("receipt_artifact_id"))
        elif issue.get("code") == "zero_fact_normalized_to_no_separate_posting" and ref:
            _set_representative(representative, "normalization", issue.get("receipt_artifact_id"))
    for ref, receipts in clarification.items():
        metric_refs["treatment_clarification_attempted"].add(ref)
    for ref in refs:
        decision = decisions.get(ref, {})
        draft = drafts.get(ref, {})
        selected = str(decision.get("selected_candidate_id") or "").strip()
        valid_candidate = _valid_candidate(decision, sent_ids)
        treatment_review = decision.get("treatment_review_required") is True
        action = str(decision.get("action") or "").strip()
        clarification_resolved = (
            ref in clarification
            and _operative_treatment(decision.get("selected_treatment"))
            and not treatment_review
            and (
                (action == "select_existing" and valid_candidate)
                or action in {"represented", "excluded", "no_separate_posting"}
            )
        )
        if clarification_resolved:
            metric_refs["treatment_clarification_resolved"].add(ref)
            _set_representative(representative, "resolved_clarification", clarification[ref][-1].get("id"))
        if ref in clarification and str(draft.get("resolution") or "") == "review_required":
            metric_refs["treatment_clarification_review_required"].add(ref)
            _set_representative(representative, "failed_clarification", clarification[ref][-1].get("id"))
        if (
            str(draft.get("resolution") or "") == "review_required"
            and selected
            and str(draft.get("selected_candidate_id") or "").strip() == selected
            and valid_candidate
            and str(draft.get("account_code") or "").strip()
            and (
                not str(_as_mapping(decision.get("candidate")).get("code") or "").strip()
                or str(draft.get("account_code") or "").strip()
                == str(_as_mapping(decision.get("candidate")).get("code") or "").strip()
            )
            and _is_zero(draft.get("debit"))
            and _is_zero(draft.get("credit"))
        ):
            metric_refs["suggested_account_preserved"].add(ref)
            _set_representative(representative, "suggested_account", _proposal_receipt_id(row))
        treatment_only = treatment_review or str(draft.get("resolution") or "") == "review_required"
        if (
            str(draft.get("resolution") or "") == "unresolved"
            and not valid_candidate
            and not treatment_only
        ):
            metric_refs["true_unresolved_account"].add(ref)
            _set_representative(representative, "true_unresolved", _proposal_receipt_id(row))
    semantic_refs = _semantic_conflict_refs(proposal)
    metric_refs["semantic_conflict_warnings"].update(semantic_refs)
    non_fatal_issue_codes = {
        "candidate_sufficiency",
        "candidate_sufficiency_invalid",
        "nonoperative_treatment_ignored",
        "treatment_clarification_required",
        "zero_fact_normalized_to_no_separate_posting",
    }
    metric_refs["decision_integrity_rejections"].update(
        str(issue.get("decision_ref") or "").strip()
        for issue in issues
        if str(issue.get("code") or "") not in non_fatal_issue_codes
        and str(issue.get("decision_ref") or "").strip()
    )
    for artifact_value in _as_sequence(row.get("artifacts")):
        artifact = _as_mapping(artifact_value)
        if (
            str(artifact.get("artifact_kind") or "") == "provider_receipt"
            and str(artifact.get("status") or "") == "successful"
            and not _as_mapping(artifact.get("metadata")).get("clarification_for_ref")
        ):
            representative.setdefault("success", _safe_receipt_id(artifact.get("id")))
    treatment_review_refs = {
        ref
        for ref in refs
        if decisions.get(ref, {}).get("treatment_review_required") is True
        or str(drafts.get(ref, {}).get("resolution") or "") == "review_required"
    }
    return {
        "refs": refs,
        "metric_refs": metric_refs,
        "representative": representative,
        "clarification_ref_count": len(clarification),
        # Count bounded attempts by (document, ref, clarification_attempt),
        # not duplicate provider artifacts for the same attempt.
        "clarification_attempt_count": sum(
            len({_clarification_attempt_key(receipt) for receipt in receipts})
            for receipts in clarification.values()
        ),
        "treatment_review_ref_count": len(treatment_review_refs),
        "nonoperative_issue_count": nonoperative_issue_count,
        "nonoperative_affected_refs": set(metric_refs["nonoperative_treatment_ignored"]),
    }


def _proposal_receipt_id(row: Mapping[str, object]) -> str:
    for value in reversed(_as_sequence(row.get("artifacts"))):
        artifact = _as_mapping(value)
        if str(artifact.get("artifact_kind") or "") == "accounting_proposal":
            return str(artifact.get("provider_receipt_artifact_id") or "")
    return ""


def build_pilot_report(
    rows: Sequence[Mapping[str, object]],
    *,
    configured_experiment_percent: int | str | None = None,
) -> dict[str, object]:
    """Build secret-safe machine evidence and blank human scoring rows."""

    _validate_adaptive_only(rows, configured_experiment_percent)
    statuses = Counter(_normalized_job_status(row.get("job_status")) for row in rows)
    slots: Counter[str] = Counter()
    http_statuses: Counter[str] = Counter()
    latency_total_ms = 0
    token_totals: Counter[str] = Counter()
    canonical_available = 0
    reconciliation_exact = 0
    draft_balanced = 0
    decision_complete = 0
    warning_metrics: Counter[str] = Counter()
    resolution_ref_count = 0
    clarification_ref_count = 0
    clarification_attempt_count = 0
    clarification_affected_refs: set[tuple[str, str]] = set()
    treatment_review_ref_count = 0
    nonoperative_issue_count = 0
    nonoperative_affected_refs: set[tuple[str, str]] = set()
    resolution_document_count: Counter[str] = Counter()
    resolution_ref_counts: Counter[str] = Counter()
    representative_receipts: dict[str, str] = {}
    scoring_rows: list[dict[str, str]] = []

    for row in rows:
        result = _as_mapping(row.get("result"))
        artifacts = _as_sequence(row.get("artifacts"))
        resolution = _resolution_evidence(row)
        refs = resolution["refs"]
        metric_refs = resolution["metric_refs"]
        document_id = str(row.get("document_id") or "")
        resolution_ref_count += len(refs)
        clarification_ref_count += int(resolution["clarification_ref_count"])
        clarification_attempt_count += int(resolution["clarification_attempt_count"])
        clarification_affected_refs.update(
            (document_id, ref) for ref in metric_refs["treatment_clarification_attempted"]
        )
        treatment_review_ref_count += int(resolution["treatment_review_ref_count"])
        nonoperative_issue_count += int(resolution["nonoperative_issue_count"])
        nonoperative_affected_refs.update(
            (document_id, ref) for ref in resolution["nonoperative_affected_refs"]
        )
        if resolution["nonoperative_issue_count"]:
            resolution_document_count["nonoperative_treatment_ignored"] += 1
        if resolution["clarification_attempt_count"]:
            resolution_document_count["treatment_clarification_attempted"] += 1
        for metric, values in metric_refs.items():
            if values:
                if metric in {"nonoperative_treatment_ignored", "treatment_clarification_attempted"}:
                    # Their aggregate numerators are issue/attempt counts;
                    # ref-level rates are populated from affected unique refs.
                    continue
                warning_metrics[metric] += len(values)
                resolution_document_count[metric] += 1
                resolution_ref_counts[metric] += len(values)
        for name, receipt_id in resolution["representative"].items():
            if receipt_id:
                representative_receipts.setdefault(name, receipt_id)
        successful_canonical = False
        pipeline_version = str(row.get("pipeline_version") or "")
        for artifact_value in artifacts:
            artifact = _as_mapping(artifact_value)
            if not pipeline_version:
                pipeline_version = str(artifact.get("pipeline_version") or "")
            if str(artifact.get("artifact_kind") or "") == "canonical_invoice_form" and str(artifact.get("status") or "") == "successful":
                successful_canonical = True
            if str(artifact.get("artifact_kind") or "") != "provider_receipt":
                continue
            try:
                slot = normalize_gemini_credential_slot(artifact.get("credential_slot"))
            except ValueError:
                # Legacy or malformed rows are excluded from the distribution;
                # their raw value must never become report output.
                slot = ""
            if slot:
                slots[slot] += 1
            status = artifact.get("http_status")
            if isinstance(status, int) and 100 <= status <= 599:
                http_statuses[str(status)] += 1
            try:
                latency_total_ms += max(int(artifact.get("elapsed_ms") or 0), 0)
            except (TypeError, ValueError):
                pass
            for token_name in ("prompt_tokens", "candidate_tokens", "cached_tokens", "thought_tokens", "total_tokens"):
                try:
                    token_totals[token_name] += max(int(_as_mapping(artifact.get("token_usage")).get(token_name) or 0), 0)
                except (TypeError, ValueError):
                    pass
        if successful_canonical or str(result.get("canonical_validation_status") or "") in {"valid", "complete"}:
            canonical_available += 1
        if str(result.get("reconciliation_status") or "") == "exact":
            reconciliation_exact += 1
        if str(result.get("draft_balance_status") or "") == "balanced" or result.get("is_balanced") is True:
            draft_balanced += 1
        if str(result.get("accounting_decision_status") or "") == "complete":
            decision_complete += 1
        scoring_rows.append(
            {
                "document_id": str(row.get("document_id") or ""),
                "pipeline_version": pipeline_version,
                "processed_at": str(row.get("processed_at") or ""),
                "draft_status": str(result.get("draft_status") or result.get("status") or _normalized_job_status(row.get("job_status"))),
                "account_selection_grade": "",
                "treatment_grade": "",
                "amount_balance_grade": "",
                "canonical_line_grade": "",
                "accountant_note": "",
            }
        )

    warning_metrics["nonoperative_treatment_ignored"] = nonoperative_issue_count
    warning_metrics["treatment_clarification_attempted"] = clarification_attempt_count
    resolution_ref_counts["nonoperative_treatment_ignored"] = len(nonoperative_affected_refs)
    resolution_ref_counts["treatment_clarification_attempted"] = len(clarification_affected_refs)

    def affected_ref_items(values: set[tuple[str, str]]) -> list[dict[str, str]]:
        return [
            {"document_id": document_id, "decision_ref": decision_ref}
            for document_id, decision_ref in sorted(values)
        ]

    def ref_denominator(metric: str) -> tuple[str, int]:
        if metric == "nonoperative_treatment_ignored":
            return "affected_decision_refs", len(nonoperative_affected_refs)
        if metric == "treatment_clarification_attempted":
            return "clarification_affected_refs", len(clarification_affected_refs)
        if metric in {"treatment_clarification_resolved", "treatment_clarification_review_required"}:
            return "clarification_attempted_refs", clarification_ref_count
        if metric == "suggested_account_preserved":
            return "treatment_review_refs", treatment_review_ref_count
        return "decision_refs", resolution_ref_count

    resolution_rates: dict[str, dict[str, object]] = {}
    for metric in _WARNING_METRICS:
        denominator_kind, denominator_value = ref_denominator(metric)
        rate: dict[str, object] = {
            "document": {
                "numerator": resolution_document_count.get(metric, 0),
                "denominator": len(rows),
                "value": resolution_document_count.get(metric, 0) / len(rows) if rows else 0.0,
            },
            "decision_ref": {
                "numerator": resolution_ref_counts.get(metric, 0),
                "denominator": denominator_value,
                "value": resolution_ref_counts.get(metric, 0) / denominator_value if denominator_value else 0.0,
            },
        }
        if metric == "nonoperative_treatment_ignored":
            rate["issue_count"] = {
                "numerator": nonoperative_issue_count,
                "denominator": len(nonoperative_affected_refs),
                "value": nonoperative_issue_count / len(nonoperative_affected_refs)
                if nonoperative_affected_refs else 0.0,
            }
        if metric == "treatment_clarification_attempted":
            rate["attempt_count"] = {
                "numerator": clarification_attempt_count,
                "denominator": len(clarification_affected_refs),
                "value": clarification_attempt_count / len(clarification_affected_refs)
                if clarification_affected_refs else 0.0,
            }
        resolution_rates[metric] = rate

    aggregate: dict[str, object] = {
        "eligible_document_count": len(rows),
        "queued": statuses.get("queued", 0),
        "completed": statuses.get("completed", 0),
        "retry_wait": statuses.get("retry_wait", 0),
        "failed": statuses.get("failed", 0),
        "provider_attempts_by_credential_slot": dict(sorted(slots.items())),
        "http_status_counts": dict(sorted(http_statuses.items())),
        "latency_total_ms": latency_total_ms,
        "prompt_tokens": token_totals.get("prompt_tokens", 0),
        "candidate_tokens": token_totals.get("candidate_tokens", 0),
        "cached_tokens": token_totals.get("cached_tokens", 0),
        "thought_tokens": token_totals.get("thought_tokens", 0),
        "total_tokens": token_totals.get("total_tokens", 0),
        "canonical_extraction_available": canonical_available,
        "reconciliation_exact": reconciliation_exact,
        "draft_balanced": draft_balanced,
        "accounting_decision_complete": decision_complete,
        **{metric: warning_metrics.get(metric, 0) for metric in _WARNING_METRICS},
        "nonoperative_treatment_ignored_affected_ref_count": len(nonoperative_affected_refs),
        "nonoperative_treatment_ignored_affected_refs": affected_ref_items(nonoperative_affected_refs),
        "treatment_clarification_attempted_affected_ref_count": len(clarification_affected_refs),
        "treatment_clarification_attempted_affected_refs": affected_ref_items(clarification_affected_refs),
        "resolution_metric_count_kinds": {
            metric: (
                "validation_issue_count"
                if metric == "nonoperative_treatment_ignored"
                else "provider_attempt_count"
                if metric == "treatment_clarification_attempted"
                else "unique_decision_ref_count"
            )
            for metric in _WARNING_METRICS
        },
        "resolution_denominators": {
            "document_count": len(rows),
            "decision_ref_count": resolution_ref_count,
        },
        "resolution_metric_document_denominators": {
            metric: {"kind": "eligible_documents", "value": len(rows)}
            for metric in _WARNING_METRICS
        },
        "resolution_metric_ref_denominators": {
            metric: {"kind": ref_denominator(metric)[0], "value": ref_denominator(metric)[1]}
            for metric in _WARNING_METRICS
        },
        "resolution_rates": resolution_rates,
        "representative_receipt_ids": {
            kind: representative_receipts.get(kind, "")
            for kind in _REPRESENTATIVE_RECEIPT_KINDS
        },
        "candidate_discovery_mode": "adaptive",
        "candidate_experiment_percent": 0,
    }
    return {
        "report_version": "gemini-v2-accountant-pilot-v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "aggregate": aggregate,
        "documents": scoring_rows,
        "accountant_grades_blank": True,
    }


def _read_artifact_content(path_value: object, artifact_storage_root: Path) -> Mapping[str, object]:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return {}
    root = artifact_storage_root.resolve()
    path = Path(raw_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PilotReportRefused("accounting proposal content path escapes artifact storage root") from exc
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return _as_mapping(payload)


def _rows_from_postgres(
    dsn: str,
    tenant_key: str,
    *,
    artifact_storage_root: Path | None = None,
) -> list[dict[str, object]]:
    if not dsn.strip():
        raise ValueError("PostgreSQL dsn is required")
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError("psycopg is required for the PostgreSQL report") from exc
    tenant_id = str(tenant_uuid(tenant_key))
    storage_root = (
        artifact_storage_root
        or (Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "backend/data/documents")) / ".document-ai-artifacts")
    ).resolve()
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("set transaction read only")
            cursor.execute(
                """
                select id, status, document_type, source_ref
                from documents
                where tenant_id = %s and coalesce(status, '') <> 'deleted'
                  and (document_type ilike '%%invoice%%' or document_type in ('invoice', 'invoice_pdf', 'einvoice_xml'))
                order by created_at, id
                """,
                (tenant_id,),
            )
            documents = {
                str(row[0]): {"status": str(row[1] or ""), "source_ref": str(row[3] or "")}
                for row in cursor.fetchall()
            }
            if not documents:
                return []
            cursor.execute(
                "select document_id, status, updated_at from processing_jobs where tenant_id = %s",
                (tenant_id,),
            )
            jobs = {str(row[0]): {"job_status": row[1], "processed_at": row[2]} for row in cursor.fetchall()}
            cursor.execute(
                "select record_key, payload from workflow_records where tenant_id = %s and record_type = 'processing_job'",
                (tenant_id,),
            )
            for record_key, payload in cursor.fetchall():
                job_payload = payload if isinstance(payload, Mapping) else {}
                document_ref = str(job_payload.get("document_ref") or "")
                document_id = next(
                    (key for key, document in documents.items() if document.get("source_ref") == document_ref),
                    "",
                )
                if document_id:
                    jobs[document_id] = {
                        "job_status": job_payload.get("status", "queued"),
                        "processed_at": job_payload.get("updated_at") or "",
                    }
            cursor.execute(
                """
                select id, document_id, artifact_kind, status, pipeline_version, credential_slot,
                       provider_receipt_artifact_id, content_storage_path,
                       http_status, elapsed_ms, token_usage, metadata
                from document_ai_artifacts
                where tenant_id = %s
                order by created_at, id
                """,
                (tenant_id,),
            )
            artifacts: dict[str, list[dict[str, object]]] = {}
            for row in cursor.fetchall():
                artifact = {
                    "id": row[0],
                    "artifact_kind": row[2],
                    "status": row[3],
                    "pipeline_version": row[4],
                    "credential_slot": row[5],
                    "provider_receipt_artifact_id": row[6],
                    "content_storage_path": row[7],
                    "http_status": row[8],
                    "elapsed_ms": row[9],
                    "token_usage": row[10] if isinstance(row[10], Mapping) else {},
                    "metadata": row[11] if isinstance(row[11], Mapping) else {},
                }
                if str(artifact["artifact_kind"] or "") == "accounting_proposal":
                    artifact["content"] = _read_artifact_content(
                        artifact["content_storage_path"], storage_root
                    )
                artifacts.setdefault(str(row[1]), []).append(
                    artifact
                )
            cursor.execute(
                "select record_key, payload from workflow_records where tenant_id = %s and record_type = 'document'",
                (tenant_id,),
            )
            results = {str(row[0]): row[1] if isinstance(row[1], Mapping) else {} for row in cursor.fetchall()}
    rows: list[dict[str, object]] = []
    for document_id in documents:
        job = jobs.get(document_id, {})
        result_payload = results.get(document_id) or results.get(str(documents[document_id].get("source_ref") or ""), {})
        result = result_payload.get("result") if isinstance(result_payload.get("result"), Mapping) else result_payload
        item_artifacts = artifacts.get(document_id, [])
        rows.append(
            {
                "document_id": document_id,
                "pipeline_version": next((str(item.get("pipeline_version") or "") for item in item_artifacts if item.get("pipeline_version")), ""),
                "processed_at": job.get("processed_at") or "",
                "job_status": job.get("job_status", "queued"),
                "result": result,
                "artifacts": item_artifacts,
            }
        )
    return rows


def write_pilot_report(
    rows: Sequence[Mapping[str, object]],
    *,
    output_dir: Path,
    configured_experiment_percent: int | str | None = None,
) -> dict[str, Path]:
    report = build_pilot_report(rows, configured_experiment_percent=configured_experiment_percent)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "gemini-v2-accountant-pilot.json"
    csv_path = output_dir / "gemini-v2-accountant-scoring.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(report["documents"])
    return {"json": json_path, "csv": csv_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create read-only adaptive Gemini V2 accountant pilot evidence for one tenant.")
    parser.add_argument("--dsn", default=os.environ.get("FISORA_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--tenant-key", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--artifact-storage-root",
        type=Path,
        default=Path(os.environ.get("FISORA_DOCUMENT_STORAGE_PATH", "backend/data/documents"))
        / ".document-ai-artifacts",
    )
    parser.add_argument("--candidate-experiment-percent")
    args = parser.parse_args(argv)
    try:
        rows = _rows_from_postgres(
            args.dsn,
            args.tenant_key,
            artifact_storage_root=args.artifact_storage_root,
        )
        paths = write_pilot_report(
            rows,
            output_dir=args.output_dir,
            configured_experiment_percent=args.candidate_experiment_percent,
        )
    except PilotReportRefused as exc:
        parser.error(str(exc))
        return 2
    except Exception as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps({"json": str(paths["json"]), "csv": str(paths["csv"])}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
