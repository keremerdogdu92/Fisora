from __future__ import annotations

from dataclasses import dataclass

from app.domain.journal_entries import JournalEntry


@dataclass(frozen=True)
class ExportCandidate:
    document_ref: str
    export_status: str
    journal_entry: JournalEntry
    risk_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportPackage:
    export_type: str
    entries: tuple[JournalEntry, ...]
    excluded_document_refs: tuple[str, ...]
    excluded_documents: tuple[dict[str, object], ...] = ()


def build_export_package(candidates: list[ExportCandidate], *, export_type: str = "zirve_universal_csv") -> ExportPackage:
    entries: list[JournalEntry] = []
    excluded: list[str] = []
    excluded_documents: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate.export_status == "export_ready" and not candidate.risk_flags and candidate.journal_entry.is_balanced:
            entries.append(candidate.journal_entry)
        else:
            excluded.append(candidate.document_ref)
            blockers = list(candidate.risk_flags)
            if not candidate.journal_entry.is_balanced:
                blockers.append("unbalanced_entry")
            if candidate.export_status != "export_ready" and not blockers:
                blockers.append(candidate.export_status)
            excluded_documents.append(
                {
                    "document_ref": candidate.document_ref,
                    "export_status": candidate.export_status,
                    "review_blockers": list(dict.fromkeys(blockers)),
                }
            )
    return ExportPackage(
        export_type=export_type,
        entries=tuple(entries),
        excluded_document_refs=tuple(excluded),
        excluded_documents=tuple(excluded_documents),
    )
