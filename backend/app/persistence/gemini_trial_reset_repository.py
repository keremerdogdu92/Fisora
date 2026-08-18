from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5


class GeminiTrialResetError(RuntimeError):
    """Raised when a reset cannot be proven safe before mutation."""


@dataclass(frozen=True)
class GeminiTrialResetSummary:
    tenant_key: str
    eligible_document_count: int
    deleted_counts: dict[str, int]
    reset_document_count: int
    requeued_job_count: int
    artifact_body_delete_count: int
    dry_run: bool


@dataclass(frozen=True)
class _ResetGraph:
    document_ids: tuple[str, ...]
    job_ids: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    ai_attempt_ids: tuple[str, ...]
    invoice_line_ids: tuple[str, ...]
    entry_ids: tuple[str, ...]
    entry_line_ids: tuple[str, ...]
    revision_ids: tuple[str, ...]
    revision_line_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    export_item_ids: tuple[str, ...]
    export_batch_ids: tuple[str, ...]
    intake_categories: tuple[tuple[str, str], ...]
    workflow_targets: tuple[tuple[str, str, str], ...]
    requeue_contexts: tuple[tuple[str, str, str, str], ...]


def _tenant_id(tenant_key: str) -> str:
    value = str(tenant_key or "").strip()
    if not value:
        raise GeminiTrialResetError("tenant_key is required")
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"fisora:tenant:{value}"))


def _placeholders(values: Iterable[object]) -> str:
    return ", ".join("%s" for _ in values)


def _select_ids(cursor: Any, query: str, args: tuple[object, ...]) -> list[str]:
    cursor.execute(query, args)
    return [str(row[0]) for row in cursor.fetchall()]


def _eligible_documents(cursor: Any, tenant_id: str) -> list[tuple[str, str, str, str]]:
    cursor.execute(
        """
        select d.id::text, d.taxpayer_id::text, coalesce(d.source_ref, d.id::text),
               lower(coalesce(d.document_type, ''))
        from documents d
        where d.tenant_id = %s
          and d.deleted_at is null
          and lower(coalesce(d.document_type, '')) like '%%invoice%%'
        order by d.created_at, d.id
        """,
        (tenant_id,),
    )
    return [(str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in cursor.fetchall()]


def _body_paths(cursor: Any, tenant_id: str, document_ids: list[str]) -> list[str]:
    if not document_ids:
        return []
    placeholders = _placeholders(document_ids)
    cursor.execute(
        f"""
        select content_storage_path, request_storage_path, response_storage_path
        from document_ai_artifacts
        where tenant_id = %s and document_id in ({placeholders})
        """,
        (tenant_id, *document_ids),
    )
    paths: list[str] = []
    for row in cursor.fetchall():
        paths.extend(str(value) for value in row if value)
    return paths


def _validated_paths(paths: Iterable[str], root: Path) -> list[Path]:
    resolved_root = root.expanduser().resolve()
    validated: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        candidate = Path(raw_path)
        resolved = candidate.resolve() if candidate.is_absolute() else (resolved_root / candidate).resolve()
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise GeminiTrialResetError(
                f"artifact body path escapes artifact_storage_root: {raw_path}"
            ) from exc
        if not relative.parts:
            raise GeminiTrialResetError(
                f"artifact body path is the artifact_storage_root itself: {raw_path}"
            )
        if resolved not in seen:
            seen.add(resolved)
            validated.append(resolved)
    return validated


def _count_rows(cursor: Any, table: str, tenant_id: str, document_ids: list[str]) -> int:
    if not document_ids:
        return 0
    placeholders = _placeholders(document_ids)
    cursor.execute(
        f"select count(*) from {table} where tenant_id = %s and document_id in ({placeholders})",
        (tenant_id, *document_ids),
    )
    return int(cursor.fetchone()[0] or 0)


def _count_by_ids(cursor: Any, table: str, id_column: str, tenant_id: str, ids: list[str]) -> int:
    if not ids:
        return 0
    placeholders = _placeholders(ids)
    cursor.execute(
        f"select count(*) from {table} where tenant_id = %s and {id_column} in ({placeholders})",
        (tenant_id, *ids),
    )
    return int(cursor.fetchone()[0] or 0)


def _preview_deleted_counts(cursor: Any, tenant_id: str, graph: _ResetGraph) -> dict[str, int]:
    document_ids = list(graph.document_ids)
    if not document_ids:
        return {}
    counts = {
        "document_ai_artifacts": _count_rows(cursor, "document_ai_artifacts", tenant_id, document_ids),
        "ai_attempts": _count_rows(cursor, "ai_attempts", tenant_id, document_ids),
        "processing_attempts": _count_by_ids(cursor, "processing_attempts", "id", tenant_id, list(graph.attempt_ids)),
        "processing_jobs": _count_rows(cursor, "processing_jobs", tenant_id, document_ids),
        "invoice_lines": _count_rows(cursor, "invoice_lines", tenant_id, document_ids),
        "journal_revisions": _count_rows(cursor, "journal_revisions", tenant_id, document_ids),
        "journal_revision_lines": _count_by_ids(cursor, "journal_revision_lines", "id", tenant_id, list(graph.revision_line_ids)),
        "journal_line_allocations": _count_by_ids(cursor, "journal_line_allocations", "journal_revision_line_id", tenant_id, list(graph.revision_line_ids)),
        "journal_entries": _count_by_ids(cursor, "journal_entries", "id", tenant_id, list(graph.entry_ids)),
        "journal_entry_lines": _count_by_ids(cursor, "journal_entry_lines", "id", tenant_id, list(graph.entry_line_ids)),
        "journal_edit_leases": _count_by_ids(cursor, "journal_edit_leases", "journal_entry_id", tenant_id, list(graph.entry_ids)),
        "journal_working_drafts": _count_by_ids(cursor, "journal_working_drafts", "journal_entry_id", tenant_id, list(graph.entry_ids)),
        "review_decisions": _count_by_ids(cursor, "review_decisions", "id", tenant_id, list(graph.review_ids)),
        "workflow_events": _count_rows(cursor, "workflow_events", tenant_id, document_ids),
        "export_batch_items": _count_by_ids(cursor, "export_batch_items", "id", tenant_id, list(graph.export_item_ids)),
        "learning_rules": _count_by_ids(cursor, "learning_rules", "source_review_decision_id", tenant_id, list(graph.review_ids)),
    }
    if graph.export_item_ids:
        placeholders = _placeholders(graph.export_item_ids)
        if graph.export_batch_ids:
            batch_placeholders = _placeholders(graph.export_batch_ids)
            cursor.execute(
                f"""
                select count(*) from export_batches b
                where b.tenant_id = %s and b.id in ({batch_placeholders})
                  and not exists (
                      select 1 from export_batch_items i where i.export_batch_id = b.id
                        and i.id not in ({placeholders})
                  )
                """,
                (tenant_id, *graph.export_batch_ids, *graph.export_item_ids),
            )
            counts["export_batches"] = int(cursor.fetchone()[0] or 0)
        else:
            counts["export_batches"] = 0
    else:
        counts["export_batches"] = 0
    workflow_counts = {
        "workflow_documents": 0,
        "workflow_processing_jobs": 0,
        "workflow_document_pipeline_events": 0,
    }
    for _document_id, client_id, document_ref in graph.workflow_targets:
        cursor.execute(
            """
            select record_type, count(*)
            from workflow_records
            where tenant_id = %s and client_id = %s
              and record_type in ('document', 'processing_job', 'document_pipeline_event')
              and (record_key = %s or payload->>'document_ref' = %s)
            group by record_type
            """,
            (tenant_id, client_id, document_ref, document_ref),
        )
        for record_type, count in cursor.fetchall():
            workflow_counts[
                {
                    "document": "workflow_documents",
                    "processing_job": "workflow_processing_jobs",
                    "document_pipeline_event": "workflow_document_pipeline_events",
                }[str(record_type)]
            ] += int(count or 0)
    counts.update(workflow_counts)
    return counts


def _ids_for_values(cursor: Any, table: str, column: str, tenant_id: str, values: list[str]) -> list[str]:
    if not values:
        return []
    placeholders = _placeholders(values)
    return _select_ids(
        cursor,
        f"select id::text from {table} where tenant_id = %s and {column} in ({placeholders})",
        (tenant_id, *values),
    )


def _collect_graph(cursor: Any, tenant_id: str, documents: list[tuple[str, str, str, str]]) -> _ResetGraph:
    document_ids = [row[0] for row in documents]
    job_ids: list[str] = []
    if document_ids:
        job_match_clauses = [f"document_id in ({_placeholders(document_ids)})"]
        job_match_args: list[object] = [tenant_id, *document_ids]
        for _document_id, taxpayer_id, document_ref, _document_type in documents:
            job_match_clauses.append("(taxpayer_id = %s and document_ref = %s)")
            job_match_args.extend((taxpayer_id, document_ref))
        job_ids = _select_ids(
            cursor,
            f"select id::text from processing_jobs where tenant_id = %s and ({' or '.join(job_match_clauses)})",
            tuple(job_match_args),
        )
    attempt_ids = _ids_for_values(cursor, "processing_attempts", "processing_job_id", tenant_id, job_ids)
    ai_attempt_ids = _ids_for_values(cursor, "ai_attempts", "document_id", tenant_id, document_ids)
    invoice_line_ids = _ids_for_values(cursor, "invoice_lines", "document_id", tenant_id, document_ids)
    revision_ids = _ids_for_values(cursor, "journal_revisions", "document_id", tenant_id, document_ids)
    entry_ids = _ids_for_values(cursor, "journal_entries", "document_id", tenant_id, document_ids)
    if revision_ids:
        placeholders = _placeholders(revision_ids)
        cursor.execute(
            f"select journal_entry_id::text from journal_revisions where tenant_id = %s and id in ({placeholders})",
            (tenant_id, *revision_ids),
        )
        entry_ids = sorted(set(entry_ids + [str(row[0]) for row in cursor.fetchall() if row[0]]))
    entry_line_ids = _ids_for_values(cursor, "journal_entry_lines", "journal_entry_id", tenant_id, entry_ids)
    revision_line_ids = _ids_for_values(cursor, "journal_revision_lines", "journal_revision_id", tenant_id, revision_ids)
    review_ids: list[str] = []
    if document_ids or revision_ids or entry_ids:
        clauses: list[str] = []
        args: list[object] = [tenant_id]
        if document_ids:
            clauses.append(f"document_id in ({_placeholders(document_ids)})")
            args.extend(document_ids)
        if revision_ids:
            clauses.append(f"journal_revision_id in ({_placeholders(revision_ids)})")
            args.extend(revision_ids)
        if entry_ids:
            clauses.append(f"journal_entry_id in ({_placeholders(entry_ids)})")
            args.extend(entry_ids)
        review_ids = _select_ids(
            cursor,
            f"select id::text from review_decisions where tenant_id = %s and ({' or '.join(clauses)})",
            tuple(args),
        )
    export_item_ids = _ids_for_values(cursor, "export_batch_items", "journal_revision_id", tenant_id, revision_ids)
    export_batch_ids: list[str] = []
    if export_item_ids:
        export_batch_ids = _select_ids(
            cursor,
            f"select export_batch_id::text from export_batch_items where tenant_id = %s and id in ({_placeholders(export_item_ids)})",
            (tenant_id, *export_item_ids),
        )
    intake_categories: dict[str, str] = {}
    jobs_by_document: dict[str, tuple[str, str]] = {}
    if document_ids:
        cursor.execute(
            f"""
            select document_id::text, id::text, coalesce(intake_category, '')
            from processing_jobs
            where tenant_id = %s and document_id in ({_placeholders(document_ids)})
            order by updated_at desc nulls last, created_at desc nulls last
            """,
            (tenant_id, *document_ids),
        )
        for document_id, job_id, intake_category in cursor.fetchall():
            intake_categories.setdefault(str(document_id), str(intake_category or ""))
            jobs_by_document.setdefault(str(document_id), (str(job_id), str(intake_category or "")))
    workflow_targets: list[tuple[str, str, str]] = []
    requeue_contexts: list[tuple[str, str, str, str]] = []
    for document_id, taxpayer_id, document_ref, _document_type in documents:
        cursor.execute(
            """
            select distinct client_id
            from workflow_records
            where tenant_id = %s
              and record_type in ('uploaded_document', 'document', 'processing_job', 'document_pipeline_event')
              and (record_key = %s or payload->>'document_ref' = %s)
            order by client_id
            """,
            (tenant_id, document_ref, document_ref),
        )
        candidates = [str(row[0]) for row in cursor.fetchall()]
        matching_clients = [
            client_id
            for client_id in candidates
            if str(uuid5(NAMESPACE_URL, f"fisora:taxpayer:{tenant_id}:{client_id}")) == taxpayer_id
        ]
        if len(matching_clients) != 1:
            continue
        client_id = matching_clients[0]
        workflow_targets.append((document_id, client_id, document_ref))
        old_job = jobs_by_document.get(document_id)
        fallback_intake = ""
        if old_job is None:
            cursor.execute(
                """
                select coalesce(payload->>'intake_category', '')
                from workflow_records
                where tenant_id = %s and client_id = %s
                  and record_type = 'uploaded_document'
                  and (record_key = %s or payload->>'document_ref' = %s)
                order by updated_at desc
                limit 1
                """,
                (tenant_id, client_id, document_ref, document_ref),
            )
            row = cursor.fetchone()
            fallback_intake = str(row[0] or "") if row else ""
        job_id = (
            old_job[0]
            if old_job is not None
            else str(
                uuid5(
                    NAMESPACE_URL,
                    f"fisora:processing-job:{tenant_id}:{client_id}:{document_ref}",
                )
            )
        )
        requeue_contexts.append(
            (document_id, client_id, job_id, old_job[1] if old_job is not None else fallback_intake)
        )
    return _ResetGraph(
        document_ids=tuple(document_ids),
        job_ids=tuple(job_ids),
        attempt_ids=tuple(attempt_ids),
        ai_attempt_ids=tuple(ai_attempt_ids),
        invoice_line_ids=tuple(invoice_line_ids),
        entry_ids=tuple(entry_ids),
        entry_line_ids=tuple(entry_line_ids),
        revision_ids=tuple(revision_ids),
        revision_line_ids=tuple(revision_line_ids),
        review_ids=tuple(review_ids),
        export_item_ids=tuple(export_item_ids),
        export_batch_ids=tuple(export_batch_ids),
        intake_categories=tuple(sorted(intake_categories.items())),
        workflow_targets=tuple(workflow_targets),
        requeue_contexts=tuple(requeue_contexts),
    )


def _has_canonical_source(cursor: Any, tenant_id: str, document_id: str) -> bool:
    cursor.execute(
        """
        select sf.storage_path
        from document_sources ds
        join source_files sf on sf.id = ds.source_file_id
        where ds.tenant_id = %s and ds.document_id = %s
          and ds.is_canonical = true
          and sf.status = 'stored'
          and nullif(btrim(sf.storage_path), '') is not null
          and sf.deleted_at is null
        limit 1
        """,
        (tenant_id, document_id),
    )
    row = cursor.fetchone()
    return bool(row and Path(str(row[0])).is_file())


def _delete_by_document(cursor: Any, table: str, tenant_id: str, document_ids: list[str]) -> int:
    if not document_ids:
        return 0
    placeholders = _placeholders(document_ids)
    cursor.execute(
        f"delete from {table} where tenant_id = %s and document_id in ({placeholders})",
        (tenant_id, *document_ids),
    )
    return int(cursor.rowcount or 0)


def _delete_by_ids(cursor: Any, table: str, id_column: str, tenant_id: str, ids: list[str]) -> int:
    if not ids:
        return 0
    placeholders = _placeholders(ids)
    cursor.execute(
        f"delete from {table} where tenant_id = %s and {id_column} in ({placeholders})",
        (tenant_id, *ids),
    )
    return int(cursor.rowcount or 0)


def _parser_kind(document_type: str) -> str:
    return "xml" if "xml" in document_type else "pdf"


def _reset_relational_rows(
    cursor: Any,
    *,
    tenant_id: str,
    documents: list[tuple[str, str, str, str]],
) -> tuple[dict[str, int], int, int]:
    document_ids = [row[0] for row in documents]
    deleted: dict[str, int] = {}
    if not document_ids:
        return deleted, 0, 0
    graph = _collect_graph(cursor, tenant_id, documents)
    job_ids = list(graph.job_ids)
    attempt_ids = list(graph.attempt_ids)
    entry_ids = list(graph.entry_ids)
    entry_line_ids = list(graph.entry_line_ids)
    revision_ids = list(graph.revision_ids)
    revision_line_ids = list(graph.revision_line_ids)
    review_ids = list(graph.review_ids)
    export_item_ids = list(graph.export_item_ids)
    intake_categories = dict(graph.intake_categories)
    requeue_contexts = {
        document_id: (client_id, job_id, intake_category)
        for document_id, client_id, job_id, intake_category in graph.requeue_contexts
    }

    # Break the document -> journal entry pointer before deleting the entry
    # graph; the FK intentionally protects entries during normal operation.
    cursor.execute(
        f"update documents set current_journal_entry_id = null where tenant_id = %s and id in ({_placeholders(document_ids)})",
        (tenant_id, *document_ids),
    )

    deleted["workflow_documents"] = 0
    deleted["workflow_processing_jobs"] = 0
    deleted["workflow_document_pipeline_events"] = 0
    workflow_count_keys = {
        "document": "workflow_documents",
        "processing_job": "workflow_processing_jobs",
        "document_pipeline_event": "workflow_document_pipeline_events",
    }
    for _document_id, client_id, document_ref in graph.workflow_targets:
        cursor.execute(
            """
            delete from workflow_records
            where tenant_id = %s and client_id = %s
              and record_type in ('document', 'processing_job', 'document_pipeline_event')
              and (record_key = %s or payload->>'document_ref' = %s)
            returning record_type
            """,
            (tenant_id, client_id, document_ref, document_ref),
        )
        for row in cursor.fetchall():
            key = workflow_count_keys[str(row[0])]
            deleted[key] += 1

    if review_ids:
        placeholders = _placeholders(review_ids)
        cursor.execute(
            f"delete from learning_rules where tenant_id = %s and source_review_decision_id in ({placeholders})",
            (tenant_id, *review_ids),
        )
        deleted["learning_rules"] = int(cursor.rowcount or 0)
    else:
        deleted["learning_rules"] = 0

    if export_item_ids:
        placeholders = _placeholders(export_item_ids)
        cursor.execute(
            f"select export_batch_id::text from export_batch_items where tenant_id = %s and id in ({placeholders})",
            (tenant_id, *export_item_ids),
        )
        export_batch_ids = [str(row[0]) for row in cursor.fetchall()]
        cursor.execute(
            f"delete from export_batch_items where tenant_id = %s and id in ({placeholders})",
            (tenant_id, *export_item_ids),
        )
        deleted["export_batch_items"] = int(cursor.rowcount or 0)
        if export_batch_ids:
            batch_placeholders = _placeholders(export_batch_ids)
            cursor.execute(
                f"""
                delete from export_batches b
                where b.tenant_id = %s and b.id in ({batch_placeholders})
                  and not exists (
                      select 1 from export_batch_items i where i.export_batch_id = b.id
                  )
                """,
                (tenant_id, *export_batch_ids),
            )
            deleted["export_batches"] = int(cursor.rowcount or 0)
    else:
        deleted["export_batch_items"] = 0
        deleted["export_batches"] = 0

    if revision_line_ids:
        deleted["journal_line_allocations"] = _delete_by_ids(
            cursor, "journal_line_allocations", "journal_revision_line_id", tenant_id, revision_line_ids
        )
    else:
        deleted["journal_line_allocations"] = 0
    deleted["journal_revision_lines"] = _delete_by_ids(
        cursor, "journal_revision_lines", "id", tenant_id, revision_line_ids
    )
    deleted["journal_entry_lines"] = _delete_by_ids(
        cursor, "journal_entry_lines", "id", tenant_id, entry_line_ids
    )
    deleted["journal_edit_leases"] = _delete_by_ids(
        cursor, "journal_edit_leases", "journal_entry_id", tenant_id, entry_ids
    )
    deleted["journal_working_drafts"] = _delete_by_ids(
        cursor, "journal_working_drafts", "journal_entry_id", tenant_id, entry_ids
    )
    deleted["review_decisions"] = _delete_by_ids(cursor, "review_decisions", "id", tenant_id, review_ids)
    deleted["journal_revisions"] = _delete_by_document(cursor, "journal_revisions", tenant_id, document_ids)
    deleted["journal_entries"] = _delete_by_ids(cursor, "journal_entries", "id", tenant_id, entry_ids)
    deleted["invoice_lines"] = _delete_by_document(cursor, "invoice_lines", tenant_id, document_ids)
    deleted["ai_attempts"] = _delete_by_document(cursor, "ai_attempts", tenant_id, document_ids)
    if attempt_ids:
        cursor.execute(
            f"update processing_jobs set current_attempt_id = null where tenant_id = %s and id in ({_placeholders(job_ids)})",
            (tenant_id, *job_ids),
        )
        deleted["processing_attempts"] = _delete_by_ids(cursor, "processing_attempts", "id", tenant_id, attempt_ids)
    else:
        deleted["processing_attempts"] = 0
    deleted["processing_jobs"] = _delete_by_document(cursor, "processing_jobs", tenant_id, document_ids)
    deleted["workflow_events"] = _delete_by_document(cursor, "workflow_events", tenant_id, document_ids)

    # Artifact rows are append-only during normal operation. The reset is an
    # explicit operator action and disables only the append-only trigger;
    # lineage/scope triggers remain active throughout the transaction.
    cursor.execute(
        "alter table document_ai_artifacts disable trigger trg_document_ai_artifact_append_only"
    )
    try:
        deleted["document_ai_artifacts"] = _delete_by_document(
            cursor, "document_ai_artifacts", tenant_id, document_ids
        )
    finally:
        cursor.execute(
            "alter table document_ai_artifacts enable trigger trg_document_ai_artifact_append_only"
        )

    placeholders = _placeholders(document_ids)
    cursor.execute(
        f"""
        update documents
        set status = 'uploaded',
            parse_notes = '[]'::jsonb,
            risk_flags = '[]'::jsonb,
            invoice_number = null,
            ettn = null,
            invoice_date = null,
            currency = null,
            accounting_direction = null,
            original_invoice_number = null,
            original_invoice_date = null,
            supplier_title = null,
            supplier_tax_id = null,
            customer_title = null,
            customer_tax_id = null,
            net_total = null,
            vat_total = null,
            gross_total = null,
            current_journal_entry_id = null,
            current_revision_no = 0,
            updated_at = now()
        where tenant_id = %s and id in ({placeholders})
        """,
        (tenant_id, *document_ids),
    )
    reset_count = int(cursor.rowcount or 0)

    requeued = 0
    for document_id, taxpayer_id, document_ref, document_type in documents:
        if not _has_canonical_source(cursor, tenant_id, document_id):
            continue
        requeue_context = requeue_contexts.get(document_id)
        if requeue_context is None:
            continue
        client_id, job_id, intake_category = requeue_context
        cursor.execute(
            """
            insert into processing_jobs
                (id, tenant_id, taxpayer_id, document_id, document_ref,
                 document_type, parser_kind, intake_category, status, attempt_count,
                 claimed_by, claim_expires_at, current_attempt_id,
                 error_message, updated_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', 0,
                    null, null, null, null, now())
            on conflict (tenant_id, taxpayer_id, document_ref)
            do update set
                status = 'queued', attempt_count = 0, claimed_by = null,
                claim_expires_at = null, current_attempt_id = null,
                error_message = null, next_attempt_at = null, retry_step = 0,
                outage_episode_id = null, updated_at = now()
            """,
            (
                job_id,
                tenant_id,
                taxpayer_id,
                document_id,
                document_ref,
                document_type,
                _parser_kind(document_type),
                intake_category or intake_categories.get(document_id, ""),
            ),
        )
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        workflow_job = {
            "id": job_id,
            "client_id": client_id,
            "document_ref": document_ref,
            "document_type": document_type,
            "parser_kind": _parser_kind(document_type),
            "intake_category": intake_category or intake_categories.get(document_id, ""),
            "status": "queued",
            "attempt_count": 0,
            "error_message": "",
            "claimed_by": "",
            "claim_expires_at": "",
            "current_attempt_id": "",
            "next_attempt_at": "",
            "retry_step": 0,
            "outage_episode_id": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        cursor.execute(
            """
            insert into workflow_records
                (id, tenant_id, client_id, record_type, record_key, payload)
            values (%s, %s, %s, 'processing_job', %s, %s::jsonb)
            on conflict (tenant_id, client_id, record_type, record_key)
            do update set payload = excluded.payload, updated_at = now()
            """,
            (str(uuid4()), tenant_id, client_id, job_id, json.dumps(workflow_job)),
        )
        requeued += 1
    return deleted, reset_count, requeued


def reset_gemini_trial_outputs(
    *,
    dsn: str,
    tenant_key: str,
    artifact_storage_root: Path,
    apply: bool,
    confirm_tenant_key: str | None = None,
) -> GeminiTrialResetSummary:
    if not str(dsn or "").strip():
        raise GeminiTrialResetError("dsn is required")
    if apply and confirm_tenant_key != tenant_key:
        raise GeminiTrialResetError("--confirm-tenant-key must exactly match tenant_key")

    import psycopg

    tenant_id = _tenant_id(tenant_key)
    body_delete_paths: list[Path] = []
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            documents = _eligible_documents(cursor, tenant_id)
            raw_paths = _body_paths(cursor, tenant_id, [row[0] for row in documents])
            body_delete_paths = _validated_paths(raw_paths, Path(artifact_storage_root))
            graph = _collect_graph(cursor, tenant_id, documents)
            if not apply:
                deleted_counts = _preview_deleted_counts(cursor, tenant_id, graph)
                deleted_counts["artifact_body_missing"] = sum(not path.exists() for path in body_delete_paths)
                return GeminiTrialResetSummary(
                    tenant_key=tenant_key,
                    eligible_document_count=len(documents),
                    deleted_counts=deleted_counts,
                    reset_document_count=len(documents),
                    requeued_job_count=sum(
                        1
                        for document_id, *_ in documents
                        if document_id in {context[0] for context in graph.requeue_contexts}
                        and _has_canonical_source(cursor, tenant_id, document_id)
                    ),
                    artifact_body_delete_count=sum(path.is_file() for path in body_delete_paths),
                    dry_run=True,
                )
            deleted_counts, reset_count, requeued_count = _reset_relational_rows(
                cursor, tenant_id=tenant_id, documents=documents
            )
    deleted_body_count = 0
    missing_body_count = 0
    body_failure_count = 0
    for path in body_delete_paths:
        try:
            if not path.exists():
                missing_body_count += 1
            elif path.is_file():
                path.unlink()
                deleted_body_count += 1
        except OSError:
            body_failure_count += 1
    deleted_counts["artifact_body_missing"] = missing_body_count
    deleted_counts["artifact_body_cleanup_failures"] = body_failure_count
    return GeminiTrialResetSummary(
        tenant_key=tenant_key,
        eligible_document_count=len(documents),
        deleted_counts=deleted_counts,
        reset_document_count=reset_count,
        requeued_job_count=requeued_count,
        artifact_body_delete_count=deleted_body_count,
        dry_run=False,
    )
