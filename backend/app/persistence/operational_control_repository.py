from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.domain.period_retention import period_retention_schedule


ConnectFactory = Callable[[], Any]


class OperationalControlRepository:
    """Durable PostgreSQL control plane for period retention."""

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

    def claim_retention_tick(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int = 300,
        interval_seconds: int = 3600,
    ) -> dict[str, Any] | None:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        next_run_at = now + timedelta(seconds=interval_seconds)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into retention_scheduler_state (tenant_id, next_run_at)
                    values (%s, %s)
                    on conflict (tenant_id) do nothing
                    """,
                    (self.tenant_id, now),
                )
                cursor.execute(
                    """
                    select next_run_at, claimed_by, claim_expires_at
                    from retention_scheduler_state
                    where tenant_id = %s
                    for update skip locked
                    """,
                    (self.tenant_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                next_run, claimed_by, claim_expires = row
                if next_run > now and not (claim_expires and claim_expires <= now):
                    return None
                cursor.execute(
                    """
                    update retention_scheduler_state
                    set claimed_by = %s,
                        claim_expires_at = %s,
                        next_run_at = %s,
                        updated_at = now()
                    where tenant_id = %s
                    """,
                    (worker_id, lease_expires_at, next_run_at, self.tenant_id),
                )
        return {
            "tenant_id": str(self.tenant_id),
            "claimed_by": worker_id,
            "claim_expires_at": lease_expires_at,
            "next_run_at": next_run_at,
            "previous_claimed_by": claimed_by or "",
        }

    def prepare_retention_batches(self, *, now: datetime) -> int:
        prepared = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select distinct taxpayer_id, accounting_period
                    from source_files
                    where tenant_id = %s
                      and accounting_period is not null
                      and deleted_at is null
                    """,
                    (self.tenant_id,),
                )
                periods = cursor.fetchall()
                for taxpayer_id, accounting_period in periods:
                    schedule = period_retention_schedule(accounting_period)
                    if schedule.preparation_on > now.date():
                        continue
                    batch_id = uuid5(
                        NAMESPACE_URL,
                        f"fisora:retention:{self.tenant_id}:{taxpayer_id}:{accounting_period.isoformat()}",
                    )
                    cursor.execute(
                        """
                        insert into retention_batches (
                            id, tenant_id, taxpayer_id, accounting_period,
                            preparation_on, warning_on, delete_on
                        )
                        values (%s, %s, %s, %s, %s, %s, %s)
                        on conflict (tenant_id, taxpayer_id, accounting_period) do nothing
                        """,
                        (
                            batch_id,
                            self.tenant_id,
                            taxpayer_id,
                            schedule.accounting_period,
                            schedule.preparation_on,
                            schedule.warning_on,
                            schedule.delete_on,
                        ),
                    )
                    if cursor.rowcount:
                        prepared += 1
                    cursor.execute(
                        """
                        select id
                        from retention_batches
                        where tenant_id = %s and taxpayer_id = %s and accounting_period = %s
                        """,
                        (self.tenant_id, taxpayer_id, schedule.accounting_period),
                    )
                    row = cursor.fetchone()
                    if not row:
                        continue
                    cursor.execute(
                        """
                        select sf.id
                        from source_files sf
                        where sf.tenant_id = %s
                          and sf.taxpayer_id = %s
                          and sf.accounting_period = %s
                          and sf.deleted_at is null
                        """,
                        (self.tenant_id, taxpayer_id, schedule.accounting_period),
                    )
                    for (source_file_id,) in cursor.fetchall():
                        cursor.execute(
                            """
                            insert into retention_batch_sources (
                                id, tenant_id, taxpayer_id, retention_batch_id, source_file_id
                            )
                            values (%s, %s, %s, %s, %s)
                            on conflict (retention_batch_id, source_file_id) do nothing
                            """,
                            (uuid4(), self.tenant_id, taxpayer_id, row[0], source_file_id),
                        )
        return prepared

    def open_due_retention_warnings(self, *, now: datetime) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update retention_batches
                    set status = 'warning_open', opened_at = coalesce(opened_at, now()), updated_at = now()
                    where tenant_id = %s
                      and status = 'scheduled'
                      and warning_on <= %s
                    """,
                    (self.tenant_id, now.date()),
                )
                return cursor.rowcount

    def claim_due_retention_deletions(
        self,
        *,
        now: datetime,
        worker_id: str,
    ) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, taxpayer_id, accounting_period, delete_on
                    from retention_batches
                    where tenant_id = %s
                      and status in ('warning_open', 'deleting')
                      and delete_on <= %s
                    order by delete_on, accounting_period
                    for update skip locked
                    """,
                    (self.tenant_id, now.date()),
                )
                for batch_id, taxpayer_id, accounting_period, delete_on in cursor.fetchall():
                    cursor.execute(
                        """
                        select distinct rbs.source_file_id, sf.storage_path
                        from retention_batch_sources rbs
                        join source_files sf on sf.id = rbs.source_file_id
                        where rbs.retention_batch_id = %s
                        """,
                        (batch_id,),
                    )
                    sources = [
                        {"source_file_id": str(source_id), "storage_path": str(path or "")}
                        for source_id, path in cursor.fetchall()
                    ]
                    cursor.execute(
                        """
                        update retention_batches
                        set status = 'deleting', updated_at = now()
                        where id = %s and tenant_id = %s
                        """,
                        (batch_id, self.tenant_id),
                    )
                    claimed.append(
                        {
                            "batch_id": str(batch_id),
                            "taxpayer_id": str(taxpayer_id),
                            "accounting_period": accounting_period,
                            "delete_on": delete_on,
                            "worker_id": worker_id,
                            "sources": sources,
                        }
                    )
        return claimed

    def resolve_retention_batch(
        self,
        *,
        batch: dict[str, Any],
        worker_id: str,
        delete_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        batch_id = batch["batch_id"]
        source_ids = [item["source_file_id"] for item in batch.get("sources", [])]
        deleted_at = datetime.now().astimezone()
        warnings = sorted(set(delete_warnings or []))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if source_ids:
                    cursor.execute(
                        """
                        update source_files
                        set status = 'deleted', deleted_at = coalesce(deleted_at, %s),
                            download_available_until = null, expires_at = null
                        where tenant_id = %s and id = any(%s::uuid[])
                        """,
                        (deleted_at, self.tenant_id, source_ids),
                    )
                    cursor.execute(
                        """
                        update documents d
                        set storage_status = 'deleted', deleted_at = coalesce(d.deleted_at, %s),
                            updated_at = now()
                        where d.tenant_id = %s
                          and exists (
                              select 1 from document_sources ds
                              where ds.document_id = d.id
                                and ds.source_file_id = any(%s::uuid[])
                          )
                        """,
                        (deleted_at, self.tenant_id, source_ids),
                    )
                event_id = uuid5(NAMESPACE_URL, f"fisora:raw-sources-deleted:{self.tenant_id}:{batch_id}")
                cursor.execute(
                    """
                    insert into workflow_events (
                        id, tenant_id, taxpayer_id, event_type, status, actor, details
                    )
                    values (%s, %s, %s, 'raw_sources_deleted_for_period', 'ok', %s, %s)
                    on conflict (id) do nothing
                    """,
                    (
                        event_id,
                        self.tenant_id,
                        UUID(str(batch["taxpayer_id"])),
                        worker_id,
                        self._json(
                            {
                                "batch_id": str(batch_id),
                                "accounting_period": batch["accounting_period"].strftime("%Y-%m"),
                                "source_count": len(source_ids),
                                "warnings": warnings,
                            }
                        ),
                    ),
                )
                cursor.execute(
                    """
                    update retention_batches
                    set status = 'resolved', resolved_at = coalesce(resolved_at, now()), updated_at = now()
                    where id = %s and tenant_id = %s
                    """,
                    (batch_id, self.tenant_id),
                )
        return {
            "batch_id": str(batch_id),
            "deleted_source_count": len(source_ids),
            "resolved": True,
            "warnings": warnings,
        }

    def list_pending_retention(self, *, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select rb.id, rb.taxpayer_id, t.display_name, rb.accounting_period,
                           rb.warning_on, rb.delete_on, rb.status, rb.read_at, rb.opened_at,
                           count(distinct rbs.source_file_id)
                    from retention_batches rb
                    join taxpayers t on t.id = rb.taxpayer_id and t.tenant_id = rb.tenant_id
                    left join retention_batch_sources rbs on rbs.retention_batch_id = rb.id
                    where rb.tenant_id = %s
                      and rb.status in ('warning_open', 'deleting')
                    group by rb.id, rb.taxpayer_id, t.display_name, rb.accounting_period,
                             rb.warning_on, rb.delete_on, rb.status, rb.read_at, rb.opened_at
                    order by rb.warning_on, rb.accounting_period
                    """,
                    (self.tenant_id,),
                )
                rows = cursor.fetchall()
        return [
            {
                "batch_id": str(row[0]),
                "taxpayer_id": str(row[1]),
                "client_name": str(row[2] or ""),
                "accounting_period": row[3].strftime("%Y-%m"),
                "warning_on": row[4].isoformat(),
                "delete_on": row[5].isoformat(),
                "status": str(row[6]),
                "read_at": row[7].isoformat() if row[7] else "",
                "created_at": row[8].isoformat() if row[8] else "",
                "document_count": int(row[9]),
            }
            for row in rows
        ]

    def mark_retention_read(self, *, batch_id: str, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update retention_batches rb
                    set read_at = coalesce(rb.read_at, now()), updated_at = now()
                    where rb.id = %s and rb.tenant_id = %s
                      and rb.status in ('warning_open', 'deleting')
                    returning id, status, read_at
                    """,
                    (UUID(str(batch_id)), self.tenant_id),
                )
                row = cursor.fetchone()
        if not row:
            raise ValueError("retention_batch_not_found_or_access_denied")
        return {"batch_id": str(row[0]), "status": str(row[1]), "read_at": row[2].isoformat()}
