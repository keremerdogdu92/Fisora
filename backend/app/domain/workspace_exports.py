from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.export_packages import ExportCandidate, ExportPackage, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, money


@dataclass(frozen=True)
class WorkspaceExportBuild:
    package: ExportPackage
    candidate_count: int


STATEMENT_APPROVAL_GATE_FLAGS = {
    "statement_review_required",
    "statement_accountant_approval_required",
}


def _statement_entry_risk_flags(entry: JournalEntry, *, accountant_approved: bool) -> tuple[str, ...]:
    if not accountant_approved:
        return entry.risk_flags
    return tuple(flag for flag in entry.risk_flags if flag not in STATEMENT_APPROVAL_GATE_FLAGS)


def _statement_export_risk_flags(
    *,
    entry: JournalEntry,
    entry_payload: dict[str, Any],
    accountant_approved: bool,
    seen_fingerprints: set[str],
) -> tuple[str, ...]:
    risks = list(_statement_entry_risk_flags(entry, accountant_approved=accountant_approved))
    if not entry.is_balanced:
        risks.append("unbalanced_statement_entry")
    account_codes = [line.account_code.strip() for line in entry.lines if line.account_code.strip()]
    if not any(account.startswith("102") for account in account_codes):
        risks.append("bank_account_missing")
    if not any(account and not account.startswith("102") for account in account_codes):
        risks.append("counterpart_account_missing")
    fingerprint = str(entry_payload.get("statement_fingerprint") or "").strip()
    if not fingerprint:
        risks.append("statement_fingerprint_missing")
    elif fingerprint in seen_fingerprints:
        risks.append("duplicate_statement_line")
    else:
        seen_fingerprints.add(fingerprint)
    return tuple(dict.fromkeys(risks))


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
    seen_statement_fingerprints: set[str] = set()
    for document in workspace.get("documents", []):
        document_ref = str(document.get("document_ref") or document.get("id") or "")
        result = document.get("result") or {}
        if not isinstance(result, dict):
            continue

        statement_entries = list(result.get("statement_entries") or [])
        if statement_entries:
            statement_export_approved = (
                result.get("accountant_export_override") is True
                and str(document.get("export_status") or result.get("export_status") or "") == "export_ready"
            )
            for index, entry_payload in enumerate(statement_entries, start=1):
                if not isinstance(entry_payload, dict):
                    continue
                entry = _entry_from_payload(entry_payload, document_ref=f"{document_ref}#statement-{index}")
                if entry is None:
                    continue
                entry_approved = statement_export_approved or str(entry_payload.get("accountant_review_status") or "") == "approved"
                entry_rejected = str(entry_payload.get("accountant_review_status") or "") == "rejected"
                risk_flags = _statement_export_risk_flags(
                    entry=entry,
                    entry_payload=entry_payload,
                    accountant_approved=entry_approved,
                    seen_fingerprints=seen_statement_fingerprints,
                )
                candidates.append(
                    ExportCandidate(
                        document_ref=f"{document_ref}#statement-{index}",
                        export_status=(
                            "rejected"
                            if entry_rejected
                            else "export_ready"
                            if entry_approved and entry.is_balanced and not risk_flags
                            else "review_required"
                        ),
                        journal_entry=entry,
                        risk_flags=risk_flags,
                    )
                )
            continue

        entry = _invoice_entry_from_result(result, document_ref=document_ref)
        if entry is None:
            continue
        review_risks = tuple(str(flag) for flag in result.get("review_reason_codes") or [] if str(flag).strip())
        if result.get("accountant_export_override") is True:
            review_risks = ()
        candidates.append(
            ExportCandidate(
                document_ref=document_ref,
                export_status=str(document.get("export_status") or result.get("export_status") or "review_required"),
                journal_entry=entry,
                risk_flags=review_risks,
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
