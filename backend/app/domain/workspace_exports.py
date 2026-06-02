from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.export_packages import ExportCandidate, ExportPackage, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, money


@dataclass(frozen=True)
class WorkspaceExportBuild:
    package: ExportPackage
    candidate_count: int


def _lines_from_payload(lines: list[dict[str, Any]], *, document_ref: str) -> tuple[JournalLine, ...]:
    return tuple(
        JournalLine(
            account_code=str(line.get("account_code") or ""),
            description=str(line.get("description") or ""),
            debit=money(str(line.get("debit") or "0.00")),
            credit=money(str(line.get("credit") or "0.00")),
            document_ref=str(line.get("document_ref") or document_ref),
        )
        for line in lines
        if str(line.get("account_code") or "").strip()
    )


def _entry_from_payload(payload: dict[str, Any], *, document_ref: str) -> JournalEntry | None:
    lines = _lines_from_payload(list(payload.get("lines") or []), document_ref=document_ref)
    if not lines:
        return None
    return JournalEntry(
        entry_type=str(payload.get("entry_type") or "workspace_entry"),
        entry_date=str(payload.get("entry_date") or "1900-01-01"),
        description=str(payload.get("description") or f"Workspace export {document_ref}"),
        lines=lines,
        risk_flags=tuple(str(flag) for flag in payload.get("risk_flags") or [] if str(flag).strip()),
    )


def _invoice_entry_from_result(result: dict[str, Any], *, document_ref: str) -> JournalEntry | None:
    lines = _lines_from_payload(list(result.get("draft_lines") or []), document_ref=document_ref)
    if not lines:
        return None
    return JournalEntry(
        entry_type=str(result.get("draft_entry_type") or result.get("invoice_type") or "purchase"),
        entry_date=str(result.get("issue_date") or "1900-01-01"),
        description=f"Workspace belge {result.get('file_name') or document_ref}",
        lines=lines,
        risk_flags=tuple(str(flag) for flag in result.get("risk_flags") or [] if str(flag).strip()),
    )


def export_candidates_from_workspace(workspace: dict[str, Any]) -> list[ExportCandidate]:
    candidates: list[ExportCandidate] = []
    for document in workspace.get("documents", []):
        document_ref = str(document.get("document_ref") or document.get("id") or "")
        result = document.get("result") or {}
        if not isinstance(result, dict):
            continue

        statement_entries = list(result.get("statement_entries") or [])
        if statement_entries:
            for index, entry_payload in enumerate(statement_entries, start=1):
                if not isinstance(entry_payload, dict):
                    continue
                entry = _entry_from_payload(entry_payload, document_ref=f"{document_ref}#statement-{index}")
                if entry is None:
                    continue
                candidates.append(
                    ExportCandidate(
                        document_ref=f"{document_ref}#statement-{index}",
                        export_status="export_ready" if entry.is_balanced and not entry.risk_flags else "review_required",
                        journal_entry=entry,
                        risk_flags=entry.risk_flags,
                    )
                )
            continue

        entry = _invoice_entry_from_result(result, document_ref=document_ref)
        if entry is None:
            continue
        candidates.append(
            ExportCandidate(
                document_ref=document_ref,
                export_status=str(document.get("export_status") or result.get("export_status") or "review_required"),
                journal_entry=entry,
                risk_flags=tuple(str(flag) for flag in result.get("review_reason_codes") or [] if str(flag).strip()),
            )
        )
    return candidates


def build_workspace_export_package(
    workspace: dict[str, Any],
    *,
    export_type: str = "zirve_universal_csv",
) -> WorkspaceExportBuild:
    candidates = export_candidates_from_workspace(workspace)
    return WorkspaceExportBuild(
        package=build_export_package(candidates, export_type=export_type),
        candidate_count=len(candidates),
    )
