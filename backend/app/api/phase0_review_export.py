from __future__ import annotations

import json
from pathlib import Path
import re

from app.api.phase0_schemas import ExportCandidatePayload, ExportPackagePayload
from app.domain.export_adapters import journal_entry_payload
from app.domain.export_packages import ExportCandidate, build_export_package
from app.domain.journal_entries import JournalEntry, JournalLine, money


def safe_export_file_name(client_id: str, export_type: str, extension: str = ".csv") -> str:
    safe_client = re.sub(r"[^A-Za-z0-9_.-]+", "-", client_id.strip()).strip(".-") or "client"
    safe_type = re.sub(r"[^A-Za-z0-9_.-]+", "-", export_type.strip()).strip(".-") or "export"
    safe_extension = extension if extension.startswith(".") else f".{extension}"
    return f"{safe_client}-{safe_type}{safe_extension}"


def manifest_file_name(output_filename: str) -> str:
    path = Path(output_filename)
    return f"{path.stem}.manifest.json"


def write_export_manifest(
    *,
    client_id: str,
    output_path: Path,
    package_payload: dict[str, object],
) -> dict[str, str]:
    manifest_filename = manifest_file_name(str(package_payload.get("output_filename") or output_path.name))
    manifest_path = output_path.with_name(manifest_filename)
    manifest_payload = {
        "client_id": client_id,
        "export_type": package_payload.get("export_type"),
        "output_filename": package_payload.get("output_filename"),
        "entry_count": package_payload.get("entry_count"),
        "candidate_count": package_payload.get("candidate_count"),
        "excluded_document_refs": package_payload.get("excluded_document_refs"),
        "generated_entries": [
            {
                "entry_type": entry.get("entry_type"),
                "entry_date": entry.get("entry_date"),
                "description": entry.get("description"),
                "line_count": len(entry.get("lines") or []),
            }
            for entry in package_payload.get("entries") or []
            if isinstance(entry, dict)
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest_filename": manifest_filename, "manifest_path": str(manifest_path)}


def workspace_document(workspace: dict[str, object], document_ref: str) -> dict[str, object] | None:
    for document in workspace.get("documents", []) or []:
        if not isinstance(document, dict):
            continue
        if str(document.get("document_ref") or document.get("id") or "") == document_ref:
            return document
    return None


def journal_entry(payload: ExportCandidatePayload) -> JournalEntry:
    return JournalEntry(
        entry_type=payload.entry_type,
        entry_date=payload.entry_date,
        description=payload.description or f"Export candidate {payload.document_ref}",
        lines=tuple(
            JournalLine(
                line.account_code,
                line.description,
                debit=money(line.debit),
                credit=money(line.credit),
                document_ref=line.document_ref or payload.document_ref,
            )
            for line in payload.lines
        ),
        risk_flags=tuple(payload.risk_flags),
    )


def entry_payload(entry: JournalEntry) -> dict[str, object]:
    return journal_entry_payload(entry)


def export_package_payload(payload: ExportPackagePayload) -> dict[str, object]:
    candidates = [
        ExportCandidate(
            candidate.document_ref,
            candidate.export_status,
            journal_entry(candidate),
            risk_flags=tuple(candidate.risk_flags),
        )
        for candidate in payload.candidates
    ]
    package = build_export_package(candidates, export_type=payload.export_type)
    return {
        "export_type": package.export_type,
        "entry_count": len(package.entries),
        "excluded_document_refs": list(package.excluded_document_refs),
        "entries": [entry_payload(entry) for entry in package.entries],
    }
