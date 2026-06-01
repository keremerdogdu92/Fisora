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


def build_export_package(candidates: list[ExportCandidate], *, export_type: str = "zirve_universal_csv") -> ExportPackage:
    entries: list[JournalEntry] = []
    excluded: list[str] = []
    for candidate in candidates:
        if candidate.export_status == "export_ready" and not candidate.risk_flags and candidate.journal_entry.is_balanced:
            entries.append(candidate.journal_entry)
        else:
            excluded.append(candidate.document_ref)
    return ExportPackage(
        export_type=export_type,
        entries=tuple(entries),
        excluded_document_refs=tuple(excluded),
    )
