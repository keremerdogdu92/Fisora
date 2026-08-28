# File: backend/app/workflows/html_source_processing.py
# Summary: Converts frozen HTML snapshots into review rows, accounting source packages, and progressive source-stage persistence.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import time
from typing import Any, Mapping

from app.domain.document_source_snapshots import validate_source_snapshot


HTML_SOURCE_PARSER_KIND = "html_source_invoice"
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def html_accounting_enabled(env: Mapping[str, str]) -> bool:
    """Return whether HTML Planner/Final rollout is explicitly enabled."""

    return str(env.get("FISORA_HTML_ACCOUNTING_ENABLED") or "").strip().lower() in _ENABLED_VALUES


def source_review_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section_index, section in enumerate(snapshot.get("sections") or [], start=1):
        if not isinstance(section, dict):
            continue
        kind = str(section.get("kind") or "")
        for row_index, raw_row in enumerate(section.get("rows") or [], start=1):
            cells = [str(cell) for cell in raw_row] if isinstance(raw_row, list) else []
            text = " | ".join(cell for cell in cells if cell.strip())
            if not text:
                continue
            rows.append({
                "source_position": f"{section_index}:{row_index}",
                "source_text": text,
                "description": text,
                "ui_amount": "",
                "ui_amount_label": "",
                "ui_amount_basis": "none",
                "ui_role": "posting_candidate" if kind == "table" else "informational",
            })
    return rows


def build_html_source_result(
    *,
    document: dict[str, Any],
    snapshot: dict[str, Any],
    snapshot_record: dict[str, Any],
) -> dict[str, Any]:
    rows = source_review_rows(snapshot)
    warnings = [str(item) for item in snapshot.get("warnings") or []]
    return {
        "file_name": str(document.get("original_file_name") or ""),
        "invoice_type": "HTML_SOURCE",
        "provider_hint": "HTML Source Reader",
        "product_line_hint": rows[0]["description"] if rows else "",
        "product_category": "HTML source invoice",
        "document_validation_status": "source_snapshot_ready",
        "canonical_line_count": 0,
        "canonical_validation_status": "source_snapshot_only",
        "canonical_validation_reasons": ["semantic_accounting_not_run"],
        "canonical_extraction_ai_used": False,
        "source_review_rows": rows,
        "source_snapshot": snapshot,
        "draft_lines": [],
        "draft_status": "manual_draft_required",
        "export_status": "review_required",
        "business_relevance_requires_review": True,
        "review_reason_codes": ["html_source_accounting_review_required", *warnings],
        "risk_flags": [],
        "automation_eligibility": "manual_review",
        "accountant_summary": "HTML kaynak satırları hazır. Muhasebe kararını müşavir tamamlamalı.",
        "accountant_explanation_tr": "Kaynak yapı deterministik okuyucuyla çıkarıldı; muhasebe semantiği bu aşamada çalıştırılmadı.",
        "export_gate_reason": "HTML source-only trial requires accountant review.",
        "ai_classification_provider": "",
        "ai_classification_reason": "",
        "technical_details": {
            "source_snapshot_id": str(snapshot_record.get("id") or ""),
            "source_snapshot_sha256": str(snapshot_record.get("snapshot_sha256") or ""),
            "snapshot_version": str(snapshot.get("version") or ""),
            "reader_version": "1.0.0",
            "source_mode": str(snapshot.get("mode") or ""),
            "source_confidence": snapshot.get("confidence"),
            "source_metrics": dict(snapshot.get("metrics") or {}),
            "source_warnings": warnings,
        },
    }


def _normalized_label(value: object) -> str:
    text = str(value or "").upper()
    replacements = str.maketrans({ord("\u00c7"): "C", ord("\u011e"): "G", ord("\u0130"): "I", ord("\u00d6"): "O", ord("\u015e"): "S", ord("\u00dc"): "U"})
    return re.sub(r"[^A-Z0-9]+", " ", text.translate(replacements)).strip()


def _machine_fact(evidence: Mapping[str, Any], key: str) -> str:
    normalized_key = str(key or "").strip().casefold()
    for item in evidence.get("machine_facts") or []:
        if isinstance(item, Mapping) and str(item.get("key") or "").strip().casefold() == normalized_key:
            return str(item.get("value") or "").strip()
    return ""


def _projected_value(value: object) -> str:
    return re.sub(r"^[\s:;|]+", "", str(value or "")).strip()


def _label_value(evidence: Mapping[str, Any], *needles: str) -> str:
    normalized_needles = tuple(_normalized_label(item) for item in needles)
    for item in evidence.get("label_values") or []:
        if not isinstance(item, Mapping):
            continue
        label = _normalized_label(item.get("label"))
        if any(needle and needle in label for needle in normalized_needles):
            return _projected_value(item.get("value"))
    return ""


_HTML_POSTING_BASIS_LABEL_HINTS = (
    "ODENECEK",
    "PAYABLE",
    "FATURA TOPLAMI",
    "TOPLAM FATURA TUTARI",
    "VERGILER DAHIL TOPLAM",
    "VERGI DAHIL TOPLAM",
    "KDV DAHIL TOPLAM",
    "GENEL TOPLAM",
    "GRAND TOTAL",
    "TAX INCLUSIVE",
)


def html_accounting_eligibility(source_package: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed unless frozen table rows and explicit current-invoice total evidence are present."""

    rows = [item for item in source_package.get("invoice_table_rows") or [] if isinstance(item, Mapping)]
    normalized_labels = [
        _normalized_label(item.get("label"))
        for item in source_package.get("printed_summary_lines") or []
        if isinstance(item, Mapping)
    ]
    matched_basis = next(
        (
            hint
            for hint in _HTML_POSTING_BASIS_LABEL_HINTS
            if any(_normalized_label(hint) in label for label in normalized_labels)
        ),
        "",
    )
    reasons: list[str] = []
    if not rows:
        reasons.append("no_frozen_table_rows")
    if not matched_basis:
        reasons.append("no_explicit_posting_basis")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "accounting_row_count": len(rows),
        "posting_basis_evidence": matched_basis,
    }


def build_html_accounting_source_package(
    snapshot: dict[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Project immutable HTML snapshot data into the existing accounting source package contract."""

    validated = validate_source_snapshot(snapshot)
    invoice_no = _machine_fact(evidence, "no") or _label_value(evidence, "FATURA NO", "INVOICE NO")
    issue_date = _machine_fact(evidence, "tarih") or _label_value(evidence, "FATURA TARIH", "TARIH", "ISSUE DATE")
    ettn = _machine_fact(evidence, "ettn") or _label_value(evidence, "ETTN", "UUID")
    header = []
    for label, value in (("FATURA NO", invoice_no), ("FATURA TARIHI", issue_date), ("ETTN", ettn)):
        if value:
            header.append({"label": label, "value": value})

    rows: list[dict[str, str]] = []
    headers: list[str] = []
    ordinal = 0
    for section_index, section in enumerate(validated.get("sections") or [], start=1):
        kind = str(section.get("kind") or "")
        columns = [str(value) for value in section.get("columns") or [] if str(value).strip()]
        if columns:
            headers.append(f"SECTION {section_index}: " + " | ".join(columns))
        if kind != "table":
            continue
        for row_index, raw_row in enumerate(section.get("rows") or [], start=1):
            cells = [str(cell) for cell in raw_row] if isinstance(raw_row, list) else []
            text = " | ".join(cell for cell in cells if cell.strip())
            if not text:
                continue
            ordinal += 1
            rows.append({
                "source_position": str(ordinal),
                "source_text": f"[SOURCE {section_index}:{row_index}] {text}",
                "description": text,
                "ui_amount": "",
                "ui_amount_label": "",
                "ui_amount_basis": "none",
                "ui_role": "posting_candidate",
            })

    summaries = [
        {"label": str(item.get("label") or ""), "value": _projected_value(item.get("value"))}
        for item in evidence.get("label_values") or []
        if isinstance(item, Mapping) and str(item.get("label") or "").strip() and str(item.get("value") or "").strip()
    ]
    payable = _machine_fact(evidence, "odenecek")
    if payable and not _label_value(evidence, "ODENECEK TOPLAM", "ODENECEK TUTAR", "PAYABLE"):
        summaries.append({"label": "ODENECEK TUTAR", "value": payable})
    tax_inclusive = _machine_fact(evidence, "vergidahil")
    if tax_inclusive and not _label_value(evidence, "VERGILER DAHIL", "TAX INCLUSIVE"):
        summaries.append({"label": "VERGILER DAHIL TOPLAM TUTAR", "value": tax_inclusive})

    return {
        "document_header": header,
        "principal_parties": [],
        "invoice_table_header": "\n".join(headers),
        "invoice_table_rows": rows,
        "printed_summary_lines": summaries,
        "note_lines": [],
    }


def run_html_source_reader(
    *,
    store: Any,
    document: dict[str, Any],
    job: dict[str, Any],
    client_id: str,
    html_source_reader: Any,
) -> tuple[dict[str, Any], int]:
    if html_source_reader is None:
        raise RuntimeError("html_source_reader_unavailable")
    path = Path(str(document.get("storage_path") or ""))
    started = time.perf_counter()
    payload = html_source_reader.read(path)
    snapshot = validate_source_snapshot(payload.get("snapshot"))
    elapsed_ms = max(int((time.perf_counter() - started) * 1000), 0)
    if not hasattr(store, "save_document_source_snapshot"):
        raise RuntimeError("document_source_snapshot_repository_unavailable")
    snapshot_record = store.save_document_source_snapshot(
        client_id=client_id,
        document=document,
        snapshot=snapshot,
        reader_version=str(getattr(html_source_reader, "reader_version", "1.0.0") or "1.0.0"),
        parser_kind=HTML_SOURCE_PARSER_KIND,
    )
    rows = source_review_rows(snapshot)
    processing_snapshot = {
        "pipeline": "html_source_reader",
        "attempt_id": str(job.get("normalized_attempt_id") or ""),
        "attempt_count": int(job.get("attempt_count") or 0),
        "document_ref": str(job.get("document_ref") or ""),
        "current_stage": "source_ready",
        "updated_at": datetime.now(UTC).isoformat(),
        "stages": {
            "reader": {"status": "completed", "elapsed_ms": elapsed_ms},
            "planner": {"status": "skipped", "elapsed_ms": 0},
            "final": {"status": "skipped", "elapsed_ms": 0},
        },
        "reader": {
            "reader_kind": "html_source_reader",
            "snapshot_version": str(snapshot.get("version") or ""),
            "mode": str(snapshot.get("mode") or ""),
            "confidence": snapshot.get("confidence"),
            "warnings": list(snapshot.get("warnings") or []),
            "metrics": dict(snapshot.get("metrics") or {}),
            "source_snapshot": snapshot,
            "invoice_table_rows": rows,
            "document_header": [],
            "printed_summary_lines": [],
        },
        "planner": {"status": "not_run", "reason": "html_source_only_trial"},
        "source_snapshot_id": str(snapshot_record.get("id") or ""),
    }
    if hasattr(store, "update_processing_snapshot"):
        store.update_processing_snapshot(
            job_id=str(job.get("id") or ""),
            processing_snapshot=processing_snapshot,
            attempt_id=str(job.get("normalized_attempt_id") or ""),
            attempt_count=int(job.get("attempt_count") or 0),
        )
    return build_html_source_result(
        document=document,
        snapshot=snapshot,
        snapshot_record=snapshot_record,
    ), elapsed_ms
