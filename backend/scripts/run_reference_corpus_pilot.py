from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.domain.tax_certificates import parse_tax_certificate_file  # noqa: E402
from app.persistence.store_factory import build_workflow_store  # noqa: E402
from app.services.protected_corpus_service import (  # noqa: E402
    ProtectedCorpusError,
    ProtectedCorpusService,
)
from app.workflows.document_processing import process_queued_documents  # noqa: E402
from import_private_intake_manifest import import_manifest  # noqa: E402
from prepare_reference_corpus_admission import validate_manifest  # noqa: E402


def _client_profile(source_root: Path, client_id: str) -> dict[str, Any]:
    certificate_dir = source_root / client_id / "tax_certificate"
    fixture = next(iter(sorted(certificate_dir.glob("*.json"))), None)
    if fixture is not None:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        profile = payload.get("profile") if isinstance(payload, dict) else {}
        if isinstance(profile, dict):
            return profile
    certificate = next(iter(sorted(certificate_dir.glob("*.pdf"))), None)
    if certificate is None:
        raise ValueError(f"tax_certificate_missing:{client_id}")
    return asdict(parse_tax_certificate_file(certificate))


def _line_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = result.get("canonical_invoice")
    if not isinstance(canonical, dict):
        return []
    items = canonical.get("line_items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _corpus_id(corpus: dict[str, Any]) -> str:
    corpus_id = str(corpus.get("corpus_id") or "")
    if not corpus_id:
        raise ValueError("protected_corpus_id_missing")
    return corpus_id


def _enroll_completed(
    *,
    service: ProtectedCorpusService,
    corpus_id: str,
    client_id: str,
    document_ref: str,
    expected_direction: str,
) -> str:
    try:
        service.enroll_document(
            corpus_id=corpus_id,
            client_id=client_id,
            document_ref=document_ref,
            direction="sale" if expected_direction == "sales" else "purchase",
            actor="task7-reference-corpus",
        )
    except ProtectedCorpusError as exc:
        error = str(exc)
        return "" if error == "duplicate_corpus_source" else error
    return ""


def _direction_mismatch(record: dict[str, Any]) -> bool:
    return (
        str(record.get("job_status") or "") == "completed"
        and str(record.get("accounting_direction") or "")
        != str(record.get("expected_direction") or "")
    )


def run(
    *,
    manifest_path: Path,
    intake_manifest_dir: Path,
    source_root: Path,
    document_root: Path,
    protected_root: Path,
    export_root: Path,
    output_path: Path,
    postgres_dsn: str,
    resume_corpus_id: str = "",
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validated = validate_manifest(manifest=manifest, source_root=source_root)
    expected_by_hash = {str(item["sha256"]): item for item in validated["items"]}
    clients = sorted({str(item["client_id"]) for item in validated["items"]})
    store = build_workflow_store(
        store_backend="postgres",
        postgres_dsn=postgres_dsn,
    )
    import_summaries: list[dict[str, Any]] = []
    processing_runs: list[dict[str, Any]] = []
    if not resume_corpus_id:
        for client_id in clients:
            profile = _client_profile(source_root, client_id)
            client_manifest = intake_manifest_dir / f"{client_id}.json"
            import_summaries.append(
                import_manifest(
                    manifest_path=client_manifest,
                    source_dir=source_root,
                    document_storage_path=document_root,
                    output_path=output_path.parent / f"import-{client_id}.json",
                    client_id=client_id,
                    client_name=str(
                        profile.get("display_title")
                        or profile.get("title")
                        or profile.get("legal_name")
                        or client_id
                    ),
                    tax_id=str(profile.get("tax_id") or profile.get("tax_identifier") or ""),
                    activity=str(profile.get("activity_description") or ""),
                    uploaded_by="task7-reference-corpus",
                    retention_days=365,
                    run_worker=False,
                    store_backend="postgres",
                    postgres_dsn=postgres_dsn,
                )
            )
        for _ in range(100):
            summary = process_queued_documents(store, max_jobs=10)
            processing_runs.append(summary)
            if int(summary.get("queued_count") or 0) == 0:
                break
        else:
            raise RuntimeError("reference_corpus_worker_did_not_drain")

    service = ProtectedCorpusService(
        store=store,
        protected_root=protected_root,
        document_root=document_root,
        export_root=export_root,
    )
    corpus = (
        service.get_corpus(resume_corpus_id)
        if resume_corpus_id
        else service.create_corpus(
            corpus_key=str(validated["corpus_key"]),
            version=int(validated["version"]),
            target_purchase_count=35,
            target_sales_count=15,
            actor="task7-reference-corpus",
        )
    )
    if (
        str(corpus.get("corpus_key") or "") != str(validated["corpus_key"])
        or int(corpus.get("version") or 0) != int(validated["version"])
    ):
        raise ValueError("resume_corpus_identity_mismatch")
    corpus_id = _corpus_id(corpus)
    records: list[dict[str, Any]] = []
    enrolled_count = 0
    for client_id in clients:
        workspace = store.get_workspace(client_id)
        processed_by_ref = {
            str(item.get("document_ref") or ""): item
            for item in workspace.get("documents") or []
            if isinstance(item, dict)
        }
        jobs_by_ref = {
            str(item.get("document_ref") or ""): item
            for item in workspace.get("processing_jobs") or []
            if isinstance(item, dict)
        }
        for uploaded in workspace.get("uploaded_documents") or []:
            source_hash = str(uploaded.get("sha256") or "")
            expected = expected_by_hash.get(source_hash)
            if expected is None:
                continue
            document_ref = str(uploaded.get("document_ref") or "")
            processed = processed_by_ref.get(document_ref) or {}
            result = processed.get("result") if isinstance(processed, dict) else {}
            result = result if isinstance(result, dict) else {}
            job = jobs_by_ref.get(document_ref) or {}
            canonical_items = _line_items(result)
            direction = str(result.get("accounting_direction") or "")
            expected_direction = str(expected["direction"])
            record = {
                "client_id": client_id,
                "document_ref": document_ref,
                "source_sha256": source_hash,
                "expected_direction": expected_direction,
                "accounting_direction": direction,
                "job_status": str(job.get("status") or ""),
                "draft_line_count": len(result.get("draft_lines") or []),
                "simulated_status": str(result.get("simulated_status") or ""),
                "export_status": str(result.get("export_status") or ""),
                "canonical_line_count": len(canonical_items),
                "missing_vat_group_line_count": sum(
                    1 for item in canonical_items if not str(item.get("vat_group_id") or "")
                ),
                "line_decision_count": len(result.get("line_decisions") or []),
                "allocation_coverage_status": str(
                    (result.get("line_allocation_coverage") or {}).get("status") or ""
                ),
                "review_reason_codes": list(result.get("review_reason_codes") or []),
            }
            records.append(record)
            if str(job.get("status") or "") != "completed" or not result:
                continue
            enrollment_error = _enroll_completed(
                service=service,
                corpus_id=corpus_id,
                client_id=client_id,
                document_ref=document_ref,
                expected_direction=expected_direction,
            )
            record["enrollment_error"] = enrollment_error
            if enrollment_error:
                continue
            enrolled_count += 1

    report = {
        "tenant_key": os.environ.get("FISORA_TENANT_KEY", ""),
        "corpus_id": corpus_id,
        "manifest_counts": {
            key: validated[key]
            for key in (
                "item_count",
                "purchase_count",
                "sales_count",
                "unique_sha256_count",
                "missing_direction_count",
                "duplicate_source_hash_count",
                "xml_party_direction_conflict_count",
            )
        },
        "imported_document_count": sum(
            int(summary.get("imported_document_count") or 0)
            for summary in import_summaries
        ),
        "enrolled_count": enrolled_count,
        "enrollment_error_count": sum(
            1 for record in records if str(record.get("enrollment_error") or "")
        ),
        "completed_job_count": sum(record["job_status"] == "completed" for record in records),
        "failed_job_count": sum(record["job_status"] == "failed" for record in records),
        "populated_editable_draft": sum(record["draft_line_count"] > 0 for record in records),
        "no_posting_suggested": sum(
            record["simulated_status"] == "no_posting_suggested"
            for record in records
        ),
        "direction_mismatch": sum(
            _direction_mismatch(record) for record in records
        ),
        "missing_vat_group_line": sum(
            int(record["missing_vat_group_line_count"])
            for record in records
        ),
        "missing_line_decision": sum(
            record["canonical_line_count"] > record["line_decision_count"]
            for record in records
        ),
        "missing_allocation": sum(
            record["draft_line_count"] > 0
            and record["allocation_coverage_status"] not in {"complete", "valid"}
            for record in records
        ),
        "processing_runs": processing_runs,
        "records": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild and measure an isolated protected 50-invoice pilot corpus.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--intake-manifest-dir", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--document-root", required=True)
    parser.add_argument("--protected-root", required=True)
    parser.add_argument("--export-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--postgres-dsn", default=os.environ.get("FISORA_DATABASE_URL") or "")
    parser.add_argument("--resume-corpus-id", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.postgres_dsn:
        print("FISORA_DATABASE_URL or --postgres-dsn is required", file=sys.stderr)
        return 2
    report = run(
        manifest_path=Path(args.manifest),
        intake_manifest_dir=Path(args.intake_manifest_dir),
        source_root=Path(args.source_root),
        document_root=Path(args.document_root),
        protected_root=Path(args.protected_root),
        export_root=Path(args.export_root),
        output_path=Path(args.output),
        postgres_dsn=str(args.postgres_dsn),
        resume_corpus_id=str(args.resume_corpus_id),
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"records", "processing_runs", "tenant_key", "corpus_id"}
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
