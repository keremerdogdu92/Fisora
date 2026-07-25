from __future__ import annotations

from copy import copy
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5


ConnectFactory = Callable[[], Any]


class _BorrowedConnectionContext:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def __enter__(self) -> Any:
        return self.connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False


class NormalizedAccountingError(RuntimeError):
    pass


class NormalizedRevisionConflict(NormalizedAccountingError):
    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(f"journal revision conflict: expected {expected}, actual {actual}")
        self.expected = expected
        self.actual = actual


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _uuid_for(namespace: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"fisora:{namespace}:{value}")


def _date_or_none(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _canonical_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("canonical_invoice")
    return payload if isinstance(payload, dict) else {}


def _canonical_lines(result: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = _canonical_payload(result)
    values = canonical.get("line_items")
    return [dict(line) for line in values if isinstance(line, dict)] if isinstance(values, (list, tuple)) else []


def _line_fingerprint(line: dict[str, Any]) -> str:
    material = {
        key: line.get(key)
        for key in (
            "canonical_line_id",
            "source_position",
            "external_line_id",
            "description",
            "quantity",
            "unit_code",
            "unit_price",
            "taxable_amount",
            "vat_rate",
            "tax_amount",
            "gross_amount",
            "evidence",
        )
    }
    return sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _validated_draft_lines(
    values: object,
) -> tuple[list[dict[str, Any]], Decimal, Decimal]:
    if not isinstance(values, (list, tuple)):
        raise NormalizedAccountingError("normalized journal requires populated draft lines")
    lines: list[dict[str, Any]] = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for raw in values:
        if not isinstance(raw, dict):
            continue
        line = dict(raw)
        account_code = str(line.get("account_code") or "").strip()
        debit = _decimal(line.get("debit"))
        credit = _decimal(line.get("credit"))
        if not account_code:
            raise NormalizedAccountingError("normalized journal line requires an account code")
        if debit < 0 or credit < 0 or (debit > 0 and credit > 0) or (debit == 0 and credit == 0):
            raise NormalizedAccountingError("normalized journal line must contain one non-negative side")
        line["account_code"] = account_code
        line["debit"] = f"{debit:.2f}"
        line["credit"] = f"{credit:.2f}"
        lines.append(line)
        total_debit += debit
        total_credit += credit
    if not lines:
        raise NormalizedAccountingError("normalized journal requires populated draft lines")
    total_debit = total_debit.quantize(Decimal("0.01"))
    total_credit = total_credit.quantize(Decimal("0.01"))
    if total_debit != total_credit:
        raise NormalizedAccountingError("normalized journal draft must be balanced")
    return lines, total_debit, total_credit


def _allocation_component(account_code: str) -> str:
    compact = "".join(ch for ch in account_code if ch.isdigit())
    if compact.startswith(("120", "320")):
        return "gross"
    if compact.startswith(("191", "391")):
        return "tax"
    return "net"


def _line_amount(line: dict[str, Any], component: str) -> Decimal:
    net = _decimal(line.get("taxable_amount"))
    tax = _decimal(line.get("tax_amount"))
    if component == "net":
        return net
    if component == "tax":
        return tax
    return _decimal(line.get("gross_amount")) or (net + tax).quantize(Decimal("0.01"))


def _allocation_plan(
    *,
    canonical_lines: list[dict[str, Any]],
    draft_lines: list[dict[str, Any]],
    line_decisions: object,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decisions_by_id = {
        str(item.get("canonical_line_id") or ""): item
        for item in line_decisions
        if isinstance(item, dict) and str(item.get("canonical_line_id") or "")
    } if isinstance(line_decisions, (list, tuple)) else {}
    remaining = {
        line_no: _decimal(line.get("debit")) + _decimal(line.get("credit"))
        for line_no, line in enumerate(draft_lines, start=1)
    }
    plan: list[dict[str, Any]] = []
    missing: list[str] = []
    for component in ("net", "tax", "gross"):
        component_candidates = [
            line_no
            for line_no, line in enumerate(draft_lines, start=1)
            if _allocation_component(str(line.get("account_code") or "")) == component
        ]
        for canonical in canonical_lines:
            canonical_line_id = str(canonical.get("canonical_line_id") or "")
            amount = _line_amount(canonical, component)
            if amount <= 0:
                continue
            preferred_code = str((decisions_by_id.get(canonical_line_id) or {}).get("account_code") or "")
            candidates = list(component_candidates)
            if component == "net":
                candidates = [
                    line_no
                    for line_no in candidates
                    if preferred_code
                    and str(draft_lines[line_no - 1].get("account_code") or "") == preferred_code
                ]
            elif component == "tax":
                canonical_rate = _decimal(canonical.get("vat_rate"))
                candidates = [
                    line_no
                    for line_no in candidates
                    if canonical_rate is not None
                    and draft_lines[line_no - 1].get("tax_rate") not in (None, "")
                    and _decimal(draft_lines[line_no - 1].get("tax_rate")) == canonical_rate
                ]
            ordered = sorted(
                candidates,
                key=lambda line_no: (
                    remaining[line_no] != amount,
                    remaining[line_no] < amount,
                    line_no,
                ),
            )
            outstanding = amount
            for line_no in ordered:
                available = remaining[line_no]
                if available <= 0:
                    continue
                allocated = min(available, outstanding)
                if allocated <= 0:
                    continue
                plan.append(
                    {
                        "journal_line_no": line_no,
                        "canonical_line_id": canonical_line_id,
                        "allocation_kind": component,
                        f"allocated_{component}": allocated,
                        "allocation_method": (
                            "line_decision_account"
                            if component == "net"
                            else "vat_rate_reconciliation"
                            if component == "tax"
                            else "amount_reconciliation"
                        ),
                    }
                )
                remaining[line_no] = (available - allocated).quantize(Decimal("0.01"))
                outstanding = (outstanding - allocated).quantize(Decimal("0.01"))
                if outstanding == 0:
                    break
            if outstanding != 0:
                missing.append(f"{canonical_line_id}:{component}:{outstanding:.2f}")
    unallocated_journal_lines = [
        f"{line_no}:{amount:.2f}"
        for line_no, amount in remaining.items()
        if amount != 0
    ]
    coverage = {
        "status": "valid" if not missing and not unallocated_journal_lines else "invalid",
        "missing_components": missing,
        "unallocated_journal_lines": unallocated_journal_lines,
        "canonical_line_count": len(canonical_lines),
        "allocation_count": len(plan),
    }
    return plan, coverage


def build_line_allocation_plan(
    *,
    canonical_lines: list[dict[str, Any]],
    draft_lines: list[dict[str, Any]],
    line_decisions: object,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shared deterministic coverage proof for normalized and compatibility review snapshots."""
    return _allocation_plan(
        canonical_lines=canonical_lines,
        draft_lines=draft_lines,
        line_decisions=line_decisions,
    )


class NormalizedAccountingRepository:
    """Relational owner for the Phase 1 purchase-invoice vertical slice.

    The existing workspace JSON remains an API compatibility projection. This
    repository owns source identity, canonical facts, journal revisions, review
    decisions and the approved revision consumed by export.
    """

    def __init__(
        self,
        *,
        connect: ConnectFactory,
        tenant_id: UUID,
        json_value: Callable[[Any], Any],
    ) -> None:
        self._connect = connect
        self.tenant_id = tenant_id
        self._json = json_value

    def with_connection(self, connection: Any) -> "NormalizedAccountingRepository":
        bound = copy(self)
        bound._connect = lambda: _BorrowedConnectionContext(connection)
        return bound

    def store_source_document(
        self,
        *,
        client_id: str,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        requested_ref = str(document.get("document_id") or uuid4())
        sha256 = str(document.get("sha256") or f"unhashed:{requested_ref}")
        source_id = _uuid_for("source", f"{self.tenant_id}:{client_id}:{sha256}")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    insert into source_files (
                        id, tenant_id, taxpayer_id, source_ref, original_filename,
                        stored_filename, storage_path, storage_backend, size_bytes,
                        sha256, status, retention_policy_days,
                        download_available_until, expires_at, deleted_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (tenant_id, taxpayer_id, sha256) do update
                    set source_ref = source_files.source_ref
                    returning id, source_ref
                    """,
                    (
                        source_id,
                        self.tenant_id,
                        taxpayer_id,
                        requested_ref,
                        str(document.get("original_file_name") or requested_ref),
                        str(document.get("stored_file_name") or ""),
                        str(document.get("storage_path") or ""),
                        str(document.get("storage_backend") or "local"),
                        int(document.get("size_bytes") or 0),
                        sha256,
                        str(document.get("storage_status") or document.get("status") or "stored"),
                        int(document.get("retention_policy_days") or 90),
                        document.get("download_available_until") or None,
                        document.get("expires_at") or None,
                        document.get("deleted_at") or None,
                    ),
                )
                source_row = cursor.fetchone()
                if not source_row:
                    raise NormalizedAccountingError("source persistence did not return an identity")
                stored_source_id, authoritative_ref = source_row
                document_id = _uuid_for("document", f"{self.tenant_id}:{client_id}:{authoritative_ref}")
                cursor.execute(
                    """
                    insert into documents (
                        id, tenant_id, taxpayer_id, source_ref, source_filename,
                        stored_filename, storage_path, size_bytes, sha256,
                        document_type, status, storage_status,
                        retention_policy_days, download_available_until, expires_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (tenant_id, taxpayer_id, source_ref) where source_ref is not null
                    do update set updated_at = now()
                    returning id
                    """,
                    (
                        document_id,
                        self.tenant_id,
                        taxpayer_id,
                        authoritative_ref,
                        str(document.get("original_file_name") or authoritative_ref),
                        str(document.get("stored_file_name") or ""),
                        str(document.get("storage_path") or ""),
                        int(document.get("size_bytes") or 0),
                        sha256,
                        str(document.get("document_type") or "invoice"),
                        str(document.get("status") or "stored"),
                        str(document.get("storage_status") or "stored"),
                        int(document.get("retention_policy_days") or 90),
                        document.get("download_available_until") or None,
                        document.get("expires_at") or None,
                    ),
                )
                stored_document_row = cursor.fetchone()
                if not stored_document_row:
                    raise NormalizedAccountingError("document persistence did not return an identity")
                stored_document_id = stored_document_row[0]
                cursor.execute(
                    """
                    insert into document_sources (
                        id, tenant_id, taxpayer_id, document_id, source_file_id,
                        relationship_type, is_canonical
                    )
                    values (%s, %s, %s, %s, %s, 'canonical', true)
                    on conflict (document_id, source_file_id) do nothing
                    """,
                    (uuid4(), self.tenant_id, taxpayer_id, stored_document_id, stored_source_id),
                )
                self._append_event(
                    cursor,
                    taxpayer_id=taxpayer_id,
                    document_id=stored_document_id,
                    event_type="source_deduplicated" if str(authoritative_ref) != requested_ref else "source_accepted",
                    status="ok",
                    actor=str(document.get("uploaded_by_user_id") or document.get("uploaded_by") or ""),
                    details={"source_ref": str(authoritative_ref), "sha256": sha256},
                )
        return {
            "document_ref": str(authoritative_ref),
            "normalized_document_id": str(stored_document_id),
            "normalized_source_file_id": str(stored_source_id),
            "deduplicated": str(authoritative_ref) != requested_ref,
            "requested_document_ref": requested_ref,
        }

    def accept_source_document(
        self,
        *,
        client_id: str,
        document: dict[str, Any],
        source_channel: str,
        identities: list[dict[str, str]],
        parser_kind: str,
        intake_category: str,
    ) -> dict[str, Any]:
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        requested_ref = str(document.get("document_id") or uuid4())
        source_sha256 = str(document.get("sha256") or f"unhashed:{requested_ref}")
        source_id = _uuid_for(
            "source",
            f"{self.tenant_id}:{client_id}:{source_sha256}",
        )
        normalized_identities = [
            {
                "kind": str(identity.get("kind") or "").strip().lower(),
                "value": str(identity.get("value") or "").strip(),
            }
            for identity in identities
            if str(identity.get("kind") or "").strip()
            and str(identity.get("value") or "").strip()
        ]
        lock_identity = (
            f"{normalized_identities[0]['kind']}:{normalized_identities[0]['value']}"
            if normalized_identities
            else f"sha256:{source_sha256}"
        )
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{self.tenant_id}:{taxpayer_id}:{lock_identity}",),
                )
                cursor.execute(
                    """
                    insert into source_files (
                        id, tenant_id, taxpayer_id, source_ref, original_filename,
                        stored_filename, storage_path, storage_backend, size_bytes,
                        sha256, status, retention_policy_days,
                        download_available_until, expires_at, deleted_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (tenant_id, taxpayer_id, sha256) do update
                    set source_ref = source_files.source_ref
                    returning id, source_ref
                    """,
                    (
                        source_id,
                        self.tenant_id,
                        taxpayer_id,
                        requested_ref,
                        str(document.get("original_file_name") or requested_ref),
                        str(document.get("stored_file_name") or ""),
                        str(document.get("storage_path") or ""),
                        str(document.get("storage_backend") or "local"),
                        int(document.get("size_bytes") or 0),
                        source_sha256,
                        str(document.get("storage_status") or document.get("status") or "stored"),
                        int(document.get("retention_policy_days") or 90),
                        document.get("download_available_until") or None,
                        document.get("expires_at") or None,
                        document.get("deleted_at") or None,
                    ),
                )
                stored_source_id, authoritative_source_ref = cursor.fetchone()

                document_id = None
                for identity in normalized_identities:
                    cursor.execute(
                        """
                        select document_id
                        from document_identities
                        where tenant_id = %s and taxpayer_id = %s
                          and identity_kind = %s and identity_value = %s
                        """,
                        (
                            self.tenant_id,
                            taxpayer_id,
                            identity["kind"],
                            identity["value"],
                        ),
                    )
                    row = cursor.fetchone()
                    if row and document_id is not None and row[0] != document_id:
                        raise NormalizedAccountingError("document_identity_conflict")
                    if row:
                        document_id = row[0]

                created_document = document_id is None
                if document_id is None:
                    document_id = _uuid_for(
                        "document",
                        f"{self.tenant_id}:{client_id}:{authoritative_source_ref}",
                    )
                    cursor.execute(
                        """
                        insert into documents (
                            id, tenant_id, taxpayer_id, source_ref, source_filename,
                            stored_filename, storage_path, size_bytes, sha256,
                            document_type, status, storage_status,
                            retention_policy_days, download_available_until, expires_at,
                            ettn, invoice_number, invoice_date, supplier_tax_id, gross_total
                        )
                        values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        returning id
                        """,
                        (
                            document_id,
                            self.tenant_id,
                            taxpayer_id,
                            authoritative_source_ref,
                            str(document.get("original_file_name") or authoritative_source_ref),
                            str(document.get("stored_file_name") or ""),
                            str(document.get("storage_path") or ""),
                            int(document.get("size_bytes") or 0),
                            source_sha256,
                            str(document.get("document_type") or "invoice"),
                            str(document.get("status") or "stored"),
                            str(document.get("storage_status") or "stored"),
                            int(document.get("retention_policy_days") or 90),
                            document.get("download_available_until") or None,
                            document.get("expires_at") or None,
                            next(
                                (
                                    identity["value"]
                                    for identity in normalized_identities
                                    if identity["kind"] == "ettn"
                                ),
                                None,
                            ),
                            str(document.get("source_invoice_no") or "") or None,
                            _date_or_none(document.get("source_issue_date")),
                            str(document.get("source_supplier_tax_id") or "") or None,
                            str(document.get("source_payable_total") or "") or None,
                        ),
                    )
                    cursor.fetchone()

                cursor.execute(
                    """
                    select source_ref
                    from documents
                    where id = %s and tenant_id = %s and taxpayer_id = %s
                    """,
                    (document_id, self.tenant_id, taxpayer_id),
                )
                document_ref = str(cursor.fetchone()[0])
                cursor.execute(
                    """
                    insert into document_sources (
                        id, tenant_id, taxpayer_id, document_id, source_file_id,
                        relationship_type, is_canonical
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (document_id, source_file_id) do nothing
                    """,
                    (
                        uuid4(),
                        self.tenant_id,
                        taxpayer_id,
                        document_id,
                        stored_source_id,
                        "canonical" if created_document else "supporting",
                        created_document,
                    ),
                )
                for identity in normalized_identities:
                    cursor.execute(
                        """
                        insert into document_identities (
                            id, tenant_id, taxpayer_id, document_id,
                            identity_kind, identity_value, source_channel,
                            state, committed_at
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, 'committed', now())
                        on conflict (tenant_id, taxpayer_id, identity_kind, identity_value)
                        do update set committed_at = coalesce(
                            document_identities.committed_at, excluded.committed_at
                        )
                        returning document_id
                        """,
                        (
                            uuid4(),
                            self.tenant_id,
                            taxpayer_id,
                            document_id,
                            identity["kind"],
                            identity["value"],
                            source_channel,
                        ),
                    )
                    owner_document_id = cursor.fetchone()[0]
                    if owner_document_id != document_id:
                        raise NormalizedAccountingError("document_identity_conflict")

                external_identity = next(
                    (
                        identity["value"]
                        for identity in normalized_identities
                        if identity["kind"] == "ettn"
                    ),
                    "",
                )
                if source_channel == "qnb_esolutions" and external_identity:
                    cursor.execute(
                        """
                        insert into provider_document_links (
                            id, tenant_id, taxpayer_id, document_id, provider,
                            external_identity, current_status
                        )
                        values (%s, %s, %s, %s, %s, %s, %s)
                        on conflict (tenant_id, taxpayer_id, provider, external_identity)
                        do update set document_id = excluded.document_id, updated_at = now()
                        """,
                        (
                            uuid4(),
                            self.tenant_id,
                            taxpayer_id,
                            document_id,
                            source_channel,
                            external_identity,
                            str(document.get("source_qnb_status") or "unknown"),
                        ),
                    )

                job_id = _uuid_for(
                    "processing-job",
                    f"{self.tenant_id}:{client_id}:{document_ref}",
                )
                cursor.execute(
                    """
                    insert into processing_jobs (
                        id, tenant_id, taxpayer_id, document_id, document_ref,
                        document_type, parser_kind, intake_category, status
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, 'queued')
                    on conflict (tenant_id, taxpayer_id, document_ref)
                    do update set updated_at = processing_jobs.updated_at
                    returning id, status, attempt_count, created_at, updated_at, (xmax = 0)
                    """,
                    (
                        job_id,
                        self.tenant_id,
                        taxpayer_id,
                        document_id,
                        document_ref,
                        str(document.get("document_type") or "invoice"),
                        parser_kind,
                        intake_category,
                    ),
                )
                job_row = cursor.fetchone()
                self._append_event(
                    cursor,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    event_type="source_attached" if not created_document else "source_accepted",
                    status="ok",
                    actor=str(document.get("uploaded_by_user_id") or document.get("uploaded_by") or source_channel),
                    details={
                        "source_ref": str(authoritative_source_ref),
                        "sha256": source_sha256,
                        "source_channel": source_channel,
                    },
                )
        return {
            "document_ref": document_ref,
            "normalized_document_id": str(document_id),
            "normalized_source_file_id": str(stored_source_id),
            "deduplicated": not created_document,
            "requested_document_ref": requested_ref,
            "processing_job_created": bool(job_row[5]),
            "processing_job": {
                "id": str(job_row[0]),
                "client_id": client_id,
                "document_ref": document_ref,
                "document_type": str(document.get("document_type") or "invoice"),
                "parser_kind": parser_kind,
                "intake_category": intake_category,
                "status": str(job_row[1]),
                "attempt_count": int(job_row[2] or 0),
                "created_at": str(job_row[3]),
                "updated_at": str(job_row[4]),
            },
        }

    def create_processing_job(
        self,
        *,
        client_id: str,
        document_ref: str,
        document_type: str,
        parser_kind: str,
        intake_category: str,
        force_requeue: bool = False,
    ) -> dict[str, Any]:
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        job_id = _uuid_for("processing-job", f"{self.tenant_id}:{client_id}:{document_ref}")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                if force_requeue:
                    cursor.execute(
                        """
                        update processing_attempts
                        set status = 'superseded', completed_at = now(),
                            error_message = coalesce(error_message, 'manual requeue superseded this attempt')
                        where processing_job_id = %s and status = 'processing'
                        """,
                        (job_id,),
                    )
                cursor.execute(
                    """
                    insert into processing_jobs (
                        id, tenant_id, taxpayer_id, document_id, document_ref,
                        document_type, parser_kind, intake_category, status
                    )
                    select %s, %s, %s, d.id, %s, %s, %s, %s, 'queued'
                    from documents d
                    where d.tenant_id = %s and d.taxpayer_id = %s and d.source_ref = %s
                    on conflict (tenant_id, taxpayer_id, document_ref)
                    do update set
                        status = case when %s then 'queued' else processing_jobs.status end,
                        error_message = case when %s then null else processing_jobs.error_message end,
                        claimed_by = case when %s then null else processing_jobs.claimed_by end,
                        claim_expires_at = case when %s then null else processing_jobs.claim_expires_at end,
                        current_attempt_id = case when %s then null else processing_jobs.current_attempt_id end,
                        updated_at = case when %s then now() else processing_jobs.updated_at end
                    returning id, status, attempt_count, created_at, updated_at
                    """,
                    (
                        job_id,
                        self.tenant_id,
                        taxpayer_id,
                        document_ref,
                        document_type,
                        parser_kind,
                        intake_category,
                        self.tenant_id,
                        taxpayer_id,
                        document_ref,
                        force_requeue,
                        force_requeue,
                        force_requeue,
                        force_requeue,
                        force_requeue,
                        force_requeue,
                    ),
                )
                row = cursor.fetchone()
        if not row:
            raise NormalizedAccountingError("processing job requires a normalized document")
        return {
            "id": str(row[0]),
            "client_id": client_id,
            "document_ref": document_ref,
            "document_type": document_type,
            "parser_kind": parser_kind,
            "intake_category": intake_category,
            "status": str(row[1]),
            "attempt_count": int(row[2] or 0),
            "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
            "updated_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
        }

    def claim_next_processing_job(self, *, worker_id: str = "document_worker") -> dict[str, Any] | None:
        attempt_id = uuid4()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    with next_job as (
                        select id
                        from processing_jobs
                        where tenant_id = %s
                          and (
                              status = 'queued'
                              or (status = 'processing' and claim_expires_at < now())
                          )
                        order by created_at asc
                        limit 1
                        for update skip locked
                    )
                    update processing_jobs jobs
                    set status = 'processing',
                        attempt_count = jobs.attempt_count + 1,
                        claimed_by = %s,
                        claim_expires_at = now() + interval '15 minutes',
                        updated_at = now()
                    from next_job
                    where jobs.id = next_job.id
                    returning jobs.id, jobs.taxpayer_id, jobs.document_id,
                              jobs.document_ref, jobs.document_type, jobs.parser_kind,
                              jobs.intake_category, jobs.status, jobs.attempt_count,
                              jobs.created_at, jobs.updated_at
                    """,
                    (self.tenant_id, worker_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute(
                    """
                    insert into processing_attempts (
                        id, tenant_id, taxpayer_id, processing_job_id,
                        attempt_no, status, worker_id
                    )
                    values (%s, %s, %s, %s, %s, 'processing', %s)
                    """,
                    (attempt_id, self.tenant_id, row[1], row[0], row[8], worker_id),
                )
                cursor.execute(
                    "update processing_jobs set current_attempt_id = %s where id = %s",
                    (attempt_id, row[0]),
                )
        return {
            "id": str(row[0]),
            "document_ref": str(row[3]),
            "document_type": str(row[4]),
            "parser_kind": str(row[5]),
            "intake_category": str(row[6]),
            "status": str(row[7]),
            "attempt_count": int(row[8]),
            "normalized_attempt_id": str(attempt_id),
            "created_at": row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
            "updated_at": row[10].isoformat() if hasattr(row[10], "isoformat") else str(row[10]),
        }

    def update_processing_job(
        self,
        *,
        job_id: str,
        status: str,
        error_message: str,
        processing_metrics: dict[str, Any] | None,
        attempt_id: str = "",
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    update processing_jobs
                    set status = %s, error_message = %s, claimed_by = null,
                        claim_expires_at = null, updated_at = now()
                    where tenant_id = %s and id = %s
                      and (%s = '' or current_attempt_id = %s::uuid)
                    returning id, document_ref, document_type, parser_kind,
                              intake_category, status, attempt_count, created_at, updated_at
                    """,
                    (
                        status,
                        error_message or None,
                        self.tenant_id,
                        job_id,
                        attempt_id,
                        attempt_id or None,
                    ),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute(
                    """
                    update processing_attempts
                    set status = %s, error_message = %s, metrics = %s, completed_at = now()
                    where processing_job_id = %s
                      and attempt_no = %s
                    """,
                    (
                        status,
                        error_message or None,
                        self._json(processing_metrics or {}),
                        row[0],
                        row[6],
                    ),
                )
        return {
            "id": str(row[0]),
            "document_ref": str(row[1]),
            "document_type": str(row[2]),
            "parser_kind": str(row[3]),
            "intake_category": str(row[4]),
            "status": str(row[5]),
            "attempt_count": int(row[6]),
            "error_message": error_message,
            "processing_metrics": processing_metrics or {},
            "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            "updated_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
        }

    def persist_canonical_journal(
        self,
        *,
        client_id: str,
        document_ref: str,
        result: dict[str, Any],
        attempt_id: str = "",
    ) -> dict[str, Any]:
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        canonical = _canonical_payload(result)
        header = canonical.get("header") if isinstance(canonical.get("header"), dict) else {}
        supplier = canonical.get("supplier_party") if isinstance(canonical.get("supplier_party"), dict) else {}
        customer = canonical.get("customer_party") if isinstance(canonical.get("customer_party"), dict) else {}
        totals = canonical.get("totals") if isinstance(canonical.get("totals"), dict) else {}
        lines = _canonical_lines(result)
        if not canonical or not lines:
            raise NormalizedAccountingError("normalized invoice requires canonical line evidence")
        if any(not str(line.get("canonical_line_id") or "").strip() for line in lines):
            raise NormalizedAccountingError("normalized invoice requires stable canonical line ids")
        if len({str(line.get("canonical_line_id")) for line in lines}) != len(lines):
            raise NormalizedAccountingError("normalized invoice canonical line ids must be unique")
        draft_lines, total_debit, total_credit = _validated_draft_lines(result.get("draft_lines"))
        result["total_debit"] = f"{total_debit:.2f}"
        result["total_credit"] = f"{total_credit:.2f}"
        result["is_balanced"] = True
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, current_journal_entry_id, current_revision_no
                    from documents
                    where tenant_id = %s and taxpayer_id = %s and source_ref = %s
                    for update
                    """,
                    (self.tenant_id, taxpayer_id, document_ref),
                )
                document_row = cursor.fetchone()
                if not document_row:
                    raise NormalizedAccountingError("canonical persistence requires a normalized document")
                document_id, current_journal_id, current_revision_no = document_row
                if attempt_id:
                    cursor.execute(
                        """
                        select current_attempt_id
                        from processing_jobs
                        where tenant_id = %s and taxpayer_id = %s and document_id = %s
                        for update
                        """,
                        (self.tenant_id, taxpayer_id, document_id),
                    )
                    processing_job_row = cursor.fetchone()
                    if (
                        not processing_job_row
                        or str(processing_job_row[0] or "") != attempt_id
                    ):
                        raise NormalizedAccountingError("stale processing attempt cannot persist accounting state")
                cursor.execute(
                    """
                    update documents set
                        invoice_number = %s, ettn = %s, invoice_date = %s,
                        currency = %s, accounting_direction = %s,
                        original_invoice_number = %s, original_invoice_date = %s,
                        supplier_title = %s, supplier_tax_id = %s,
                        customer_title = %s, customer_tax_id = %s,
                        net_total = %s, vat_total = %s, gross_total = %s,
                        status = %s, parse_notes = %s, risk_flags = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        str(header.get("invoice_no") or result.get("invoice_no") or ""),
                        str(header.get("ettn") or result.get("ettn") or ""),
                        _date_or_none(header.get("issue_date") or result.get("issue_date")),
                        str(header.get("currency") or totals.get("currency") or "TRY"),
                        str(result.get("accounting_direction") or "purchase"),
                        str(header.get("original_invoice_no") or ""),
                        _date_or_none(header.get("original_invoice_date")),
                        str(supplier.get("title") or result.get("issuer_title") or ""),
                        str(supplier.get("tax_id") or result.get("issuer_tax_id") or ""),
                        str(customer.get("title") or result.get("recipient_title") or ""),
                        str(customer.get("tax_id") or result.get("recipient_tax_id") or ""),
                        _decimal(totals.get("goods_services_total") or result.get("goods_services_total")),
                        _decimal(totals.get("vat_total") or result.get("vat_total")),
                        _decimal(totals.get("payable_total") or result.get("payable_total")),
                        str(result.get("simulated_status") or "review_required"),
                        self._json(result.get("parse_notes") or []),
                        self._json(result.get("risk_flags") or []),
                        document_id,
                    ),
                )
                canonical_line_ids: list[UUID] = []
                canonical_line_id_map: dict[str, UUID] = {}
                for position, line in enumerate(lines, start=1):
                    canonical_line_id = str(line.get("canonical_line_id") or "").strip()
                    fingerprint = _line_fingerprint(line)
                    cursor.execute(
                        """
                        select id, extraction_version, source_fingerprint, superseded_at
                        from invoice_lines
                        where document_id = %s and canonical_line_id = %s
                        order by extraction_version desc
                        limit 1
                        """,
                        (document_id, canonical_line_id),
                    )
                    previous_line = cursor.fetchone()
                    if (
                        previous_line
                        and previous_line[3] is None
                        and str(previous_line[2] or "") == fingerprint
                    ):
                        line_id = previous_line[0]
                        canonical_line_ids.append(line_id)
                        canonical_line_id_map[canonical_line_id] = line_id
                        continue
                    extraction_version = int(previous_line[1] or 0) + 1 if previous_line else 1
                    if previous_line:
                        cursor.execute(
                            "update invoice_lines set superseded_at = now() where id = %s and superseded_at is null",
                            (previous_line[0],),
                        )
                    line_id = _uuid_for(
                        "invoice-line",
                        f"{document_id}:{canonical_line_id}:{extraction_version}:{fingerprint}",
                    )
                    canonical_line_ids.append(line_id)
                    canonical_line_id_map[canonical_line_id] = line_id
                    cursor.execute(
                        """
                        insert into invoice_lines (
                            id, document_id, tenant_id, taxpayer_id, line_no,
                            canonical_line_id, source_position, raw_text,
                            original_description, quantity, unit_code, unit_price, net_amount,
                            vat_rate, tax_amount, gross_amount, evidence,
                            extraction_version, source_fingerprint
                        )
                        values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            line_id,
                            document_id,
                            self.tenant_id,
                            taxpayer_id,
                            position,
                            canonical_line_id,
                            str(line.get("source_position") or line.get("external_line_id") or ""),
                            str(line.get("description") or ""),
                            str(line.get("description") or ""),
                            _decimal(line.get("quantity")),
                            str(line.get("unit_code") or ""),
                            _decimal(line.get("unit_price")),
                            _decimal(line.get("taxable_amount")),
                            _decimal(line.get("vat_rate")),
                            _decimal(line.get("tax_amount")),
                            _decimal(line.get("gross_amount")),
                            self._json(line.get("evidence") or []),
                            extraction_version,
                            fingerprint,
                        ),
                    )
                if str(result.get("canonical_validation_status") or "") == "valid":
                    cursor.execute(
                        """
                        select id, canonical_line_id
                        from invoice_lines
                        where document_id = %s and superseded_at is null
                        """,
                        (document_id,),
                    )
                    current_canonical_ids = set(canonical_line_id_map)
                    stale_line_ids = [
                        row[0]
                        for row in cursor.fetchall()
                        if str(row[1] or "") not in current_canonical_ids
                    ]
                    for stale_line_id in stale_line_ids:
                        cursor.execute(
                            "update invoice_lines set superseded_at = now() where id = %s",
                            (stale_line_id,),
                        )
                allocation_plan, allocation_coverage = _allocation_plan(
                    canonical_lines=lines,
                    draft_lines=draft_lines,
                    line_decisions=result.get("line_decisions"),
                )
                result["line_allocation_coverage"] = allocation_coverage
                line_decision_coverage = result.get("line_decision_coverage")
                line_decision_valid = (
                    isinstance(line_decision_coverage, dict)
                    and str(line_decision_coverage.get("status") or "") == "valid"
                )
                if allocation_coverage["status"] != "valid" or not line_decision_valid:
                    result["export_status"] = "review_required"
                    result["review_reason_codes"] = list(
                        dict.fromkeys(
                            [
                                *(result.get("review_reason_codes") or []),
                                *(
                                    ["canonical_line_allocation_incomplete"]
                                    if allocation_coverage["status"] != "valid"
                                    else []
                                ),
                                *(["canonical_line_decision_incomplete"] if not line_decision_valid else []),
                            ]
                        )
                    )
                ai_trace = [item for item in result.get("ai_trace") or [] if isinstance(item, dict)]
                if not ai_trace and result.get("ai_classification_provider"):
                    ai_trace = [
                        {
                            "provider": result.get("ai_classification_provider"),
                            "status": "completed",
                            "model": result.get("ai_model") or "",
                        }
                    ]
                cursor.execute(
                    """
                    select current_attempt_id
                    from processing_jobs
                    where tenant_id = %s and taxpayer_id = %s and document_id = %s
                    """,
                    (self.tenant_id, taxpayer_id, document_id),
                )
                processing_job_row = cursor.fetchone()
                processing_attempt_id = processing_job_row[0] if processing_job_row else None
                for attempt in ai_trace:
                    cursor.execute(
                        """
                        insert into ai_attempts (
                            id, tenant_id, taxpayer_id, document_id, processing_attempt_id, provider,
                            model, status, prompt_version, schema_version,
                            usage_metadata, evidence
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            uuid4(),
                            self.tenant_id,
                            taxpayer_id,
                            document_id,
                            processing_attempt_id,
                            str(attempt.get("provider") or attempt.get("agent") or "unknown"),
                            str(attempt.get("model") or ""),
                            str(attempt.get("status") or "completed"),
                            str(attempt.get("prompt_version") or ""),
                            str(attempt.get("schema_version") or ""),
                            self._json(attempt.get("usage") or {}),
                            self._json(attempt),
                        ),
                    )
                journal_id = current_journal_id or _uuid_for("journal", str(document_id))
                cursor.execute(
                    """
                    insert into journal_entries (
                        id, tenant_id, taxpayer_id, document_id, entry_date,
                        entry_type, description, status, total_debit, total_credit,
                        confidence_score, risk_flags, export_status
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, 'working_draft', %s, %s, %s, %s, %s)
                    on conflict (document_id) where document_id is not null
                    do update set
                        entry_date = excluded.entry_date,
                        entry_type = excluded.entry_type,
                        description = excluded.description,
                        status = 'working_draft',
                        total_debit = excluded.total_debit,
                        total_credit = excluded.total_credit,
                        confidence_score = excluded.confidence_score,
                        risk_flags = excluded.risk_flags,
                        export_status = excluded.export_status,
                        updated_at = now()
                    returning id, current_revision_no, approved_revision_no
                    """,
                    (
                        journal_id,
                        self.tenant_id,
                        taxpayer_id,
                        document_id,
                        _date_or_none(result.get("issue_date")) or date.today(),
                        str(result.get("draft_entry_type") or "purchase_invoice"),
                        str(result.get("accountant_summary") or result.get("file_name") or document_ref),
                        total_debit,
                        total_credit,
                        _decimal(result.get("draft_confidence")),
                        self._json(result.get("risk_flags") or []),
                        str(result.get("export_status") or "review_required"),
                    ),
                )
                journal_row = cursor.fetchone()
                if not journal_row:
                    raise NormalizedAccountingError("journal upsert did not return an identity")
                journal_id, journal_current_revision, approved_revision_no = journal_row
                if approved_revision_no is not None:
                    raise NormalizedAccountingError("approved normalized journal cannot be replaced by processing")
                revision_no = int(journal_current_revision or current_revision_no or 0) + 1
                revision_id = uuid4()
                result["normalized_revision"] = revision_no
                result["normalized_revision_status"] = "review_required"
                self._insert_revision(
                    cursor=cursor,
                    revision_id=revision_id,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    journal_id=journal_id,
                    revision_no=revision_no,
                    base_revision_no=int(journal_current_revision or 0) or None,
                    status="review_required",
                    result=result,
                    created_by="document_worker",
                )
                revision_line_ids = self._insert_revision_lines(
                    cursor=cursor,
                    revision_id=revision_id,
                    taxpayer_id=taxpayer_id,
                    draft_lines=draft_lines,
                    canonical_line_ids=canonical_line_ids,
                )
                self._insert_allocations(
                    cursor=cursor,
                    taxpayer_id=taxpayer_id,
                    revision_line_ids=revision_line_ids,
                    canonical_line_id_map=canonical_line_id_map,
                    allocation_plan=allocation_plan,
                    currency=str(header.get("currency") or totals.get("currency") or "TRY"),
                )
                cursor.execute(
                    """
                    update journal_entries
                    set current_revision_no = %s, version = version + 1, updated_at = now()
                    where id = %s
                    """,
                    (revision_no, journal_id),
                )
                cursor.execute(
                    """
                    update documents
                    set current_journal_entry_id = %s, current_revision_no = %s, updated_at = now()
                    where id = %s
                    """,
                    (journal_id, revision_no, document_id),
                )
                self._append_event(
                    cursor,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    event_type="normalized_journal_draft_saved",
                    status="ok",
                    actor="document_worker",
                    details={"revision_no": revision_no, "line_count": len(draft_lines)},
                )
        return {"revision_no": revision_no, "journal_entry_id": str(journal_id)}

    def save_review(
        self,
        *,
        client_id: str,
        document_ref: str,
        decision: dict[str, Any],
        corrected_result: dict[str, Any],
    ) -> dict[str, Any]:
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        expected = int(decision.get("expected_revision") or 0)
        draft_lines, total_debit, total_credit = _validated_draft_lines(corrected_result.get("draft_lines"))
        corrected_result["draft_lines"] = draft_lines
        corrected_result["total_debit"] = f"{total_debit:.2f}"
        corrected_result["total_credit"] = f"{total_credit:.2f}"
        corrected_result["is_balanced"] = True
        with self._connect() as conn:
            with conn.cursor() as cursor:
                document_id, journal_id, current_revision = self._locked_current_journal(
                    cursor, taxpayer_id=taxpayer_id, document_ref=document_ref
                )
                if expected < 1 or expected != current_revision:
                    raise NormalizedRevisionConflict(expected=expected, actual=current_revision)
                cursor.execute("select currency from documents where id = %s", (document_id,))
                document_currency_row = cursor.fetchone()
                document_currency = str(document_currency_row[0] or "TRY").upper() if document_currency_row else "TRY"
                cursor.execute(
                    """
                    select canonical_line_id, id, source_position, original_description,
                           quantity, unit_code, unit_price, net_amount, vat_rate,
                           tax_amount, gross_amount, evidence
                    from invoice_lines
                    where document_id = %s and superseded_at is null
                    order by line_no, extraction_version desc
                    """,
                    (document_id,),
                )
                canonical_rows = cursor.fetchall()
                canonical_lines = [
                    {
                        "canonical_line_id": str(row[0] or ""),
                        "source_position": str(row[2] or ""),
                        "description": str(row[3] or ""),
                        "quantity": row[4],
                        "unit_code": str(row[5] or ""),
                        "unit_price": row[6],
                        "taxable_amount": row[7],
                        "vat_rate": row[8],
                        "tax_amount": row[9],
                        "gross_amount": row[10],
                        "evidence": row[11] or [],
                    }
                    for row in canonical_rows
                ]
                canonical_line_id_map = {
                    str(row[0] or ""): row[1]
                    for row in canonical_rows
                    if str(row[0] or "")
                }
                corrected_account_code = str(decision.get("corrected_account_code") or "").strip()
                existing_decision_accounts = {
                    str(item.get("account_code") or "")
                    for item in corrected_result.get("line_decisions") or []
                    if isinstance(item, dict) and str(item.get("account_code") or "")
                }
                scoped_correction_required = bool(
                    corrected_account_code and len(existing_decision_accounts) > 1
                )
                if (
                    str(decision.get("action") or "") == "approve_with_changes"
                    and corrected_account_code
                    and not scoped_correction_required
                    and isinstance(corrected_result.get("line_decisions"), list)
                ):
                    corrected_result["line_decisions"] = [
                        {
                            **item,
                            "account_code": corrected_account_code,
                            "decision_source": "accountant",
                            "decision_actor": str(decision.get("reviewer") or ""),
                        }
                        if isinstance(item, dict)
                        else item
                        for item in corrected_result["line_decisions"]
                    ]
                if scoped_correction_required:
                    corrected_result["review_reason_codes"] = list(
                        dict.fromkeys(
                            [
                                *(corrected_result.get("review_reason_codes") or []),
                                "canonical_line_correction_scope_required",
                            ]
                        )
                    )
                allocation_plan, allocation_coverage = _allocation_plan(
                    canonical_lines=canonical_lines,
                    draft_lines=draft_lines,
                    line_decisions=corrected_result.get("line_decisions"),
                )
                corrected_result["line_allocation_coverage"] = allocation_coverage
                expected_line_ids = {str(line.get("canonical_line_id") or "") for line in canonical_lines}
                received_line_ids = [
                    str(item.get("canonical_line_id") or "")
                    for item in corrected_result.get("line_decisions") or []
                    if isinstance(item, dict)
                ]
                duplicate_line_ids = {
                    line_id for line_id in received_line_ids if line_id and received_line_ids.count(line_id) > 1
                }
                line_decision_valid = (
                    bool(expected_line_ids)
                    and set(received_line_ids) == expected_line_ids
                    and len(received_line_ids) == len(expected_line_ids)
                    and not duplicate_line_ids
                )
                corrected_result["line_decision_coverage"] = {
                    "status": "valid" if line_decision_valid else "invalid",
                    "expected_ids": sorted(expected_line_ids),
                    "received_ids": received_line_ids,
                    "missing_ids": sorted(expected_line_ids - set(received_line_ids)),
                    "duplicate_ids": sorted(duplicate_line_ids),
                    "unknown_ids": sorted(set(received_line_ids) - expected_line_ids),
                }
                cursor.execute(
                    """
                    select normalized_account_code
                    from chart_accounts
                    where tenant_id = %s and taxpayer_id = %s
                      and is_active = true and is_detail_account = true
                    """,
                    (self.tenant_id, taxpayer_id),
                )
                usable_accounts = {str(row[0] or "") for row in cursor.fetchall()}
                selected_accounts = {str(line.get("account_code") or "") for line in draft_lines}
                unusable_accounts = sorted(selected_accounts - usable_accounts)
                review_reasons = {
                    str(reason)
                    for reason in corrected_result.get("review_reason_codes") or []
                    if str(reason)
                }
                material_reasons = {
                    reason
                    for reason in review_reasons
                    if reason in {
                        "line_items_missing",
                        "canonical_line_id_missing",
                        "canonical_line_id_duplicate",
                        "canonical_source_position_missing",
                        "line_vat_rate_missing",
                        "line_tax_amount_missing",
                        "canonical_line_allocation_incomplete",
                        "canonical_line_correction_scope_required",
                        "direction_conflict_review",
                        "counterparty_missing",
                        "return_invoice_manual_review",
                        "special_tax_review_required",
                        "withholding_manual_review",
                        "hearing_device_vat_should_be_zero",
                        "vat_split_unresolved",
                        "mixed_vat_manual_review",
                    }
                    or any(token in reason for token in ("withholding", "tevkifat", "special_tax", "vat_split_unresolved"))
                }
                canonical_valid = (
                    bool(canonical_lines)
                    and str(corrected_result.get("canonical_validation_status") or "") == "valid"
                )
                requested_approval = str(decision.get("action") or "") in {"approve", "approve_with_changes"}
                approved = (
                    requested_approval
                    and total_debit > 0
                    and canonical_valid
                    and line_decision_valid
                    and allocation_coverage["status"] == "valid"
                    and not unusable_accounts
                    and not material_reasons
                    and document_currency == "TRY"
                )
                corrected_result["account_validation"] = {
                    "status": "valid" if not unusable_accounts else "invalid",
                    "unusable_accounts": unusable_accounts,
                }
                corrected_result["export_status"] = "export_ready" if approved else "review_required"
                if not approved:
                    corrected_result["review_reason_codes"] = list(
                        dict.fromkeys(
                            [
                                *review_reasons,
                                *(["canonical_validation_required"] if not canonical_valid else []),
                                *(
                                    ["canonical_line_allocation_incomplete"]
                                    if allocation_coverage["status"] != "valid"
                                    else []
                                ),
                                *(["canonical_line_decision_incomplete"] if not line_decision_valid else []),
                                *(["chart_account_unusable"] if unusable_accounts else []),
                                *(["foreign_currency_not_supported"] if document_currency != "TRY" else []),
                            ]
                        )
                    )
                export_status = str(corrected_result["export_status"])
                status = "approved" if approved else "review_required"
                revision_no = current_revision + 1
                revision_id = uuid4()
                corrected_result["normalized_revision"] = revision_no
                corrected_result["normalized_revision_status"] = status
                self._insert_revision(
                    cursor=cursor,
                    revision_id=revision_id,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    journal_id=journal_id,
                    revision_no=revision_no,
                    base_revision_no=current_revision,
                    status=status,
                    result=corrected_result,
                    created_by=str(decision.get("reviewer") or ""),
                    approved_by=str(decision.get("reviewer") or "") if approved else "",
                )
                revision_line_ids = self._insert_revision_lines(
                    cursor=cursor,
                    revision_id=revision_id,
                    taxpayer_id=taxpayer_id,
                    draft_lines=draft_lines,
                    canonical_line_ids=list(canonical_line_id_map.values()),
                )
                self._insert_allocations(
                    cursor=cursor,
                    taxpayer_id=taxpayer_id,
                    revision_line_ids=revision_line_ids,
                    canonical_line_id_map=canonical_line_id_map,
                    allocation_plan=allocation_plan,
                    currency=str(corrected_result.get("currency") or "TRY"),
                )
                cursor.execute(
                    """
                    insert into review_decisions (
                        id, tenant_id, taxpayer_id, document_id, journal_entry_id,
                        journal_revision_id, reviewer_user_id, action,
                        corrected_account_code, corrected_counterparty_code,
                        category, reason, apply_to_similar, base_revision_no
                    )
                    values (%s, %s, %s, %s, %s, %s, null, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid4(),
                        self.tenant_id,
                        taxpayer_id,
                        document_id,
                        journal_id,
                        revision_id,
                        str(decision.get("action") or ""),
                        str(decision.get("corrected_account_code") or ""),
                        str(decision.get("corrected_counterparty_code") or ""),
                        str(decision.get("category") or ""),
                        str(decision.get("reason") or ""),
                        bool(decision.get("apply_to_similar")),
                        current_revision,
                    ),
                )
                cursor.execute(
                    """
                    update journal_entries set
                        status = %s, total_debit = %s, total_credit = %s,
                        export_status = %s, current_revision_no = %s,
                        approved_revision_no = case when %s then %s else approved_revision_no end,
                        version = version + 1, updated_at = now()
                    where id = %s
                    """,
                    (
                        status,
                        total_debit,
                        total_credit,
                        export_status,
                        revision_no,
                        approved,
                        revision_no,
                        journal_id,
                    ),
                )
                cursor.execute(
                    "update documents set current_revision_no = %s, status = %s, updated_at = now() where id = %s",
                    (revision_no, status, document_id),
                )
                self._append_event(
                    cursor,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    event_type="journal_approved" if approved else "journal_review_saved",
                    status="ok",
                    actor=str(decision.get("reviewer") or ""),
                    details={"revision_no": revision_no, "base_revision_no": current_revision},
                )
        return {"revision_no": revision_no, "approved": approved, "result": corrected_result}

    def reopen(
        self,
        *,
        client_id: str,
        document_ref: str,
        expected_revision: int,
        reviewer: str,
        reason: str,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise NormalizedAccountingError("reopen reason is required")
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                document_id, journal_id, current_revision = self._locked_current_journal(
                    cursor, taxpayer_id=taxpayer_id, document_ref=document_ref
                )
                if expected_revision != current_revision:
                    raise NormalizedRevisionConflict(expected=expected_revision, actual=current_revision)
                cursor.execute(
                    """
                    select id, result_snapshot
                    from journal_revisions
                    where journal_entry_id = %s and revision_no = %s and status = 'approved'
                    """,
                    (journal_id, current_revision),
                )
                approved_row = cursor.fetchone()
                if not approved_row:
                    raise NormalizedAccountingError("only the current approved revision can be reopened")
                approved_revision_id = approved_row[0]
                snapshot = dict(approved_row[1])
                cursor.execute(
                    """
                    select distinct a.invoice_line_id
                    from journal_revision_lines l
                    join journal_line_allocations a
                      on a.journal_revision_line_id = l.id
                    where l.journal_revision_id = %s
                    order by a.invoice_line_id
                    """,
                    (approved_revision_id,),
                )
                canonical_line_ids = [row[0] for row in cursor.fetchall()]
                snapshot["export_status"] = "review_required"
                snapshot["accountant_export_override"] = False
                revision_no = current_revision + 1
                snapshot["normalized_revision"] = revision_no
                snapshot["normalized_revision_status"] = "working_draft"
                revision_id = uuid4()
                self._insert_revision(
                    cursor=cursor,
                    revision_id=revision_id,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    journal_id=journal_id,
                    revision_no=revision_no,
                    base_revision_no=current_revision,
                    status="working_draft",
                    result=snapshot,
                    created_by=reviewer,
                    reopen_reason=reason,
                )
                revision_line_ids = self._insert_revision_lines(
                    cursor=cursor,
                    revision_id=revision_id,
                    taxpayer_id=taxpayer_id,
                    draft_lines=[dict(line) for line in snapshot.get("draft_lines") or [] if isinstance(line, dict)],
                    canonical_line_ids=canonical_line_ids,
                )
                self._copy_revision_allocations(
                    cursor=cursor,
                    taxpayer_id=taxpayer_id,
                    source_revision_id=approved_revision_id,
                    target_revision_line_ids=revision_line_ids,
                )
                cursor.execute(
                    """
                    update journal_entries
                    set status = 'working_draft', export_status = 'review_required',
                        current_revision_no = %s, version = version + 1, updated_at = now()
                    where id = %s
                    """,
                    (revision_no, journal_id),
                )
                cursor.execute(
                    "update documents set current_revision_no = %s, status = 'working_draft', updated_at = now() where id = %s",
                    (revision_no, document_id),
                )
                self._append_event(
                    cursor,
                    taxpayer_id=taxpayer_id,
                    document_id=document_id,
                    event_type="journal_reopened",
                    status="ok",
                    actor=reviewer,
                    details={"revision_no": revision_no, "approved_revision_no": current_revision, "reason": reason},
                )
        return {"document_ref": document_ref, "revision_no": revision_no, "result": snapshot}

    def project_documents(self, *, client_id: str, approved_only: bool = False) -> list[dict[str, Any]]:
        taxpayer_id = _uuid_for("taxpayer", f"{self.tenant_id}:{client_id}")
        status_sql = "and revisions.status = 'approved'" if approved_only else ""
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    select documents.source_ref, documents.status, revisions.revision_no,
                           revisions.result_snapshot, revisions.status
                    from documents
                    join journal_entries on journal_entries.id = documents.current_journal_entry_id
                    join journal_revisions revisions
                      on revisions.journal_entry_id = journal_entries.id
                     and revisions.revision_no = journal_entries.current_revision_no
                    where documents.tenant_id = %s and documents.taxpayer_id = %s
                      {status_sql}
                    order by documents.created_at asc
                    """,
                    (self.tenant_id, taxpayer_id),
                )
                rows = cursor.fetchall()
        return [
            {
                "document_ref": str(row[0]),
                "status": str(row[1]),
                "export_status": str((row[3] or {}).get("export_status") or "review_required"),
                "normalized_revision": int(row[2]),
                "normalized_revision_status": str(row[4]),
                "result": dict(row[3] or {}),
            }
            for row in rows
        ]

    def _locked_current_journal(
        self,
        cursor: Any,
        *,
        taxpayer_id: UUID,
        document_ref: str,
    ) -> tuple[UUID, UUID, int]:
        cursor.execute(
            """
            select documents.id, journal_entries.id, journal_entries.current_revision_no
            from documents
            join journal_entries on journal_entries.id = documents.current_journal_entry_id
            where documents.tenant_id = %s and documents.taxpayer_id = %s
              and documents.source_ref = %s
            for update of journal_entries
            """,
            (self.tenant_id, taxpayer_id, document_ref),
        )
        row = cursor.fetchone()
        if not row:
            raise NormalizedAccountingError("normalized journal not found")
        return row[0], row[1], int(row[2] or 0)

    def _insert_revision(
        self,
        *,
        cursor: Any,
        revision_id: UUID,
        taxpayer_id: UUID,
        document_id: UUID,
        journal_id: UUID,
        revision_no: int,
        base_revision_no: int | None,
        status: str,
        result: dict[str, Any],
        created_by: str,
        approved_by: str = "",
        reopen_reason: str = "",
    ) -> None:
        cursor.execute(
            """
            insert into journal_revisions (
                id, tenant_id, taxpayer_id, document_id, journal_entry_id,
                revision_no, base_revision_no, status, total_debit, total_credit,
                is_balanced, export_status, result_snapshot, created_by,
                approved_by, approved_at, reopen_reason
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    case when %s <> '' then now() else null end, %s)
            """,
            (
                revision_id,
                self.tenant_id,
                taxpayer_id,
                document_id,
                journal_id,
                revision_no,
                base_revision_no,
                status,
                _decimal(result.get("total_debit")),
                _decimal(result.get("total_credit")),
                bool(result.get("is_balanced")),
                str(result.get("export_status") or "review_required"),
                self._json(result),
                created_by,
                approved_by or None,
                approved_by,
                reopen_reason or None,
            ),
        )

    def _insert_revision_lines(
        self,
        *,
        cursor: Any,
        revision_id: UUID,
        taxpayer_id: UUID,
        draft_lines: list[dict[str, Any]],
        canonical_line_ids: list[UUID],
    ) -> dict[int, UUID]:
        revision_line_ids: dict[int, UUID] = {}
        for line_no, line in enumerate(draft_lines, start=1):
            revision_line_id = uuid4()
            revision_line_ids[line_no] = revision_line_id
            cursor.execute(
                """
                insert into journal_revision_lines (
                    id, tenant_id, taxpayer_id, journal_revision_id,
                    canonical_invoice_line_id, line_no, raw_account_code,
                    description, debit_amount, credit_amount, tax_rate,
                    allocation_metadata
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    revision_line_id,
                    self.tenant_id,
                    taxpayer_id,
                    revision_id,
                    None,
                    line_no,
                    str(line.get("account_code") or ""),
                    str(line.get("description") or ""),
                    _decimal(line.get("debit")),
                    _decimal(line.get("credit")),
                    _decimal(line.get("tax_rate")) if line.get("tax_rate") not in (None, "") else None,
                    self._json(
                        {
                            "allocation_model": "journal_line_allocations",
                            "candidate_canonical_line_ids": [str(value) for value in canonical_line_ids],
                        }
                    ),
                ),
            )
        return revision_line_ids

    def _insert_allocations(
        self,
        *,
        cursor: Any,
        taxpayer_id: UUID,
        revision_line_ids: dict[int, UUID],
        canonical_line_id_map: dict[str, UUID],
        allocation_plan: list[dict[str, Any]],
        currency: str,
    ) -> None:
        for allocation in allocation_plan:
            revision_line_id = revision_line_ids.get(int(allocation["journal_line_no"]))
            invoice_line_id = canonical_line_id_map.get(str(allocation["canonical_line_id"]))
            if revision_line_id is None or invoice_line_id is None:
                continue
            kind = str(allocation["allocation_kind"])
            cursor.execute(
                """
                insert into journal_line_allocations (
                    id, tenant_id, taxpayer_id, journal_revision_line_id,
                    invoice_line_id, allocation_kind, allocated_net,
                    allocated_tax, allocated_gross, currency,
                    allocation_method, evidence
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (journal_revision_line_id, invoice_line_id, allocation_kind)
                do nothing
                """,
                (
                    uuid4(),
                    self.tenant_id,
                    taxpayer_id,
                    revision_line_id,
                    invoice_line_id,
                    kind,
                    _decimal(allocation.get("allocated_net")),
                    _decimal(allocation.get("allocated_tax")),
                    _decimal(allocation.get("allocated_gross")),
                    currency or "TRY",
                    str(allocation.get("allocation_method") or "amount_reconciliation"),
                    self._json(
                        {
                            "canonical_line_id": str(allocation["canonical_line_id"]),
                            "journal_line_no": int(allocation["journal_line_no"]),
                        }
                    ),
                ),
            )

    def _copy_revision_allocations(
        self,
        *,
        cursor: Any,
        taxpayer_id: UUID,
        source_revision_id: UUID,
        target_revision_line_ids: dict[int, UUID],
    ) -> None:
        cursor.execute(
            """
            select l.line_no, a.invoice_line_id, a.allocation_kind,
                   a.allocated_net, a.allocated_tax, a.allocated_gross,
                   a.currency, a.allocation_method, a.evidence
            from journal_revision_lines l
            join journal_line_allocations a
              on a.journal_revision_line_id = l.id
            where l.journal_revision_id = %s
            order by l.line_no, a.allocation_kind, a.invoice_line_id
            """,
            (source_revision_id,),
        )
        for row in cursor.fetchall():
            target_revision_line_id = target_revision_line_ids.get(int(row[0]))
            if target_revision_line_id is None:
                raise NormalizedAccountingError(
                    "reopened journal line does not match approved allocation lineage"
                )
            cursor.execute(
                """
                insert into journal_line_allocations (
                    id, tenant_id, taxpayer_id, journal_revision_line_id,
                    invoice_line_id, allocation_kind, allocated_net,
                    allocated_tax, allocated_gross, currency,
                    allocation_method, evidence
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    self.tenant_id,
                    taxpayer_id,
                    target_revision_line_id,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    "reopen_copy",
                    self._json(
                        {
                            **(dict(row[8]) if isinstance(row[8], dict) else {}),
                            "copied_from_revision_id": str(source_revision_id),
                            "source_allocation_method": str(row[7] or ""),
                        }
                    ),
                ),
            )

    def _append_event(
        self,
        cursor: Any,
        *,
        taxpayer_id: UUID,
        document_id: UUID,
        event_type: str,
        status: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            insert into workflow_events (
                id, tenant_id, taxpayer_id, document_id, event_type,
                status, actor, details
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                self.tenant_id,
                taxpayer_id,
                document_id,
                event_type,
                status,
                actor or None,
                self._json(details),
            ),
        )
