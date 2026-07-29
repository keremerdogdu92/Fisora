from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol
from uuid import UUID

from app.persistence.normalized_accounting_repository import NormalizedRevisionConflict


LEASE_DURATION = timedelta(minutes=5)


class ReviewCollaborationError(Exception):
    pass


class EditLeaseConflict(ReviewCollaborationError):
    pass


class EditLeaseActivityError(ValueError, ReviewCollaborationError):
    pass


class ReviewCollaborationRepository(Protocol):
    def read_lease(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any] | None: ...

    def write_lease(self, tenant_id: str, journal_entry_id: str, lease: dict[str, Any]) -> None: ...

    def delete_lease(self, tenant_id: str, journal_entry_id: str) -> None: ...

    def read_current_journal_state(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any]: ...

    def read_working_draft(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any] | None: ...

    def write_working_draft(
        self,
        tenant_id: str,
        journal_entry_id: str,
        draft: dict[str, Any],
    ) -> None: ...


class InMemoryReviewCollaborationRepository:
    """Deterministic repository used by local workflow tests without a DSN."""

    def __init__(self) -> None:
        self._leases: dict[tuple[str, str], dict[str, Any]] = {}
        self._journal_states: dict[tuple[str, str], dict[str, Any]] = {}
        self._working_drafts: dict[tuple[str, str], dict[str, Any]] = {}

    def set_current_journal_state(
        self,
        *,
        tenant_id: str,
        journal_entry_id: str,
        current_revision: int,
        export_status: str,
    ) -> None:
        self._journal_states[(tenant_id, journal_entry_id)] = {
            "current_revision": current_revision,
            "export_status": export_status,
        }

    def read_lease(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any] | None:
        lease = self._leases.get((tenant_id, journal_entry_id))
        return deepcopy(lease) if lease else None

    def write_lease(self, tenant_id: str, journal_entry_id: str, lease: dict[str, Any]) -> None:
        self._leases[(tenant_id, journal_entry_id)] = deepcopy(lease)

    def delete_lease(self, tenant_id: str, journal_entry_id: str) -> None:
        self._leases.pop((tenant_id, journal_entry_id), None)

    def read_current_journal_state(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any]:
        return deepcopy(
            self._journal_states.get(
                (tenant_id, journal_entry_id),
                {"current_revision": 0, "export_status": "review_required"},
            )
        )

    def read_working_draft(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any] | None:
        draft = self._working_drafts.get((tenant_id, journal_entry_id))
        return deepcopy(draft) if draft else None

    def write_working_draft(self, tenant_id: str, journal_entry_id: str, draft: dict[str, Any]) -> None:
        self._working_drafts[(tenant_id, journal_entry_id)] = deepcopy(draft)

    def list_candidates(self, tenant_id: str) -> list[dict[str, Any]]:
        return [deepcopy(item) for (stored_tenant, _), item in self._working_drafts.items() if stored_tenant == tenant_id]


class PostgresReviewCollaborationRepository:
    """Tenant-scoped adapter for the normalized collaboration tables."""

    def __init__(self, *, connect: Callable[[], Any], tenant_id: UUID, taxpayer_id: UUID) -> None:
        self._connect = connect
        self._tenant_id = tenant_id
        self._taxpayer_id = taxpayer_id

    def _context(self, cursor: Any, document_ref: str) -> tuple[UUID, UUID, int]:
        cursor.execute(
            """
            select d.id, je.id, je.current_revision_no
            from documents d
            join journal_entries je on je.id = d.current_journal_entry_id
            where d.tenant_id = %s and d.taxpayer_id = %s and d.source_ref = %s
            for update of je
            """,
            (self._tenant_id, self._taxpayer_id, document_ref),
        )
        row = cursor.fetchone()
        if not row:
            raise ReviewCollaborationError("normalized journal not found")
        return row[0], row[1], int(row[2] or 0)

    def read_lease(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                document_id, journal_id, _ = self._context(cursor, journal_entry_id)
                cursor.execute(
                    """
                    select owner_actor_id, owner_role, acquired_at,
                           last_user_activity_at, expires_at, takeover_reason
                    from journal_edit_leases
                    where tenant_id = %s and journal_entry_id = %s
                    """,
                    (self._tenant_id, journal_id),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "journal_entry_id": journal_entry_id, "owner_actor_id": str(row[0]), "owner_role": str(row[1]),
            "acquired_at": row[2], "last_user_activity_at": row[3], "expires_at": row[4],
            "takeover_reason": str(row[5] or ""), "document_id": document_id, "journal_uuid": journal_id,
        }

    def write_lease(self, tenant_id: str, journal_entry_id: str, lease: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                document_id, journal_id, _ = self._context(cursor, journal_entry_id)
                cursor.execute(
                    """
                    insert into journal_edit_leases (
                        tenant_id, taxpayer_id, journal_entry_id, owner_actor_id,
                        owner_role, acquired_at, last_user_activity_at, expires_at, takeover_reason
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (tenant_id, journal_entry_id) do update set
                        owner_actor_id = excluded.owner_actor_id,
                        owner_role = excluded.owner_role,
                        acquired_at = excluded.acquired_at,
                        last_user_activity_at = excluded.last_user_activity_at,
                        expires_at = excluded.expires_at,
                        takeover_reason = excluded.takeover_reason,
                        updated_at = now()
                    """,
                    (self._tenant_id, self._taxpayer_id, journal_id, lease["owner_actor_id"], lease["owner_role"], lease["acquired_at"], lease["last_user_activity_at"], lease["expires_at"], lease.get("takeover_reason") or None),
                )

    def delete_lease(self, tenant_id: str, journal_entry_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                _, journal_id, _ = self._context(cursor, journal_entry_id)
                cursor.execute("delete from journal_edit_leases where tenant_id = %s and journal_entry_id = %s", (self._tenant_id, journal_id))

    def read_current_journal_state(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                _, _, revision = self._context(cursor, journal_entry_id)
                cursor.execute("select export_status from journal_entries where tenant_id = %s and id = (select current_journal_entry_id from documents where tenant_id = %s and taxpayer_id = %s and source_ref = %s)", (self._tenant_id, self._tenant_id, self._taxpayer_id, journal_entry_id))
                row = cursor.fetchone()
        return {"current_revision": revision, "export_status": str(row[0] or "review_required") if row else "review_required"}

    def read_working_draft(self, tenant_id: str, journal_entry_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                _, journal_id, _ = self._context(cursor, journal_entry_id)
                cursor.execute("select base_revision_no, candidate_revision_no, current_export_status, draft_snapshot, saved_by, updated_at from journal_working_drafts where tenant_id = %s and journal_entry_id = %s", (self._tenant_id, journal_id))
                row = cursor.fetchone()
        if not row:
            return None
        return {"journal_entry_id": journal_entry_id, "base_revision_no": int(row[0]), "candidate_revision": int(row[1]), "export_status": str(row[2]), "payload": row[3] or {}, "saved_by": str(row[4]), "saved_at": row[5]}

    def write_working_draft(self, tenant_id: str, journal_entry_id: str, draft: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                _, journal_id, _ = self._context(cursor, journal_entry_id)
                cursor.execute("insert into journal_working_drafts (tenant_id, taxpayer_id, journal_entry_id, base_revision_no, candidate_revision_no, revision_role, current_export_status, draft_snapshot, saved_by) values (%s, %s, %s, %s, %s, 'candidate', %s, %s, %s) on conflict (tenant_id, journal_entry_id) do update set base_revision_no = excluded.base_revision_no, candidate_revision_no = excluded.candidate_revision_no, current_export_status = excluded.current_export_status, draft_snapshot = excluded.draft_snapshot, saved_by = excluded.saved_by, updated_at = now()", (self._tenant_id, self._taxpayer_id, journal_id, draft["current_revision"], draft["candidate_revision"], draft["export_status"], json_value(draft.get("payload") or {}), draft["saved_by"]))

    def list_candidates(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("select d.source_ref, wd.base_revision_no, wd.candidate_revision_no, wd.current_export_status, wd.draft_snapshot, wd.saved_by, wd.updated_at from journal_working_drafts wd join journal_entries je on je.id = wd.journal_entry_id join documents d on d.current_journal_entry_id = je.id where wd.tenant_id = %s and wd.taxpayer_id = %s order by wd.updated_at desc", (self._tenant_id, self._taxpayer_id))
                rows = cursor.fetchall()
        return [{"journal_entry_id": str(row[0]), "expected_revision": int(row[1]), "candidate_revision": int(row[2]), "revision_role": "candidate", "current_revision": int(row[1]), "export_status": str(row[3]), "payload": row[4] or {}, "saved_by": str(row[5]), "saved_at": row[6]} for row in rows]


def json_value(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ReviewCollaborationService:
    """Coordinates editor ownership while keeping drafts outside approved journal state."""

    def __init__(
        self,
        *,
        repository: ReviewCollaborationRepository,
        tenant_id: str,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._now = now

    def acquire(
        self,
        *,
        journal_entry_id: str,
        actor_id: str,
        actor_role: str,
        user_activity_at: datetime,
        expected_revision: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = self._resolve_now(now)
        self._validate_activity(user_activity_at=user_activity_at, now=observed_at)
        if expected_revision is not None:
            current = self._repository.read_current_journal_state(self._tenant_id, journal_entry_id)
            if int(current["current_revision"]) != expected_revision:
                raise NormalizedRevisionConflict(expected=expected_revision, actual=int(current["current_revision"]))
        existing = self._active_lease(journal_entry_id=journal_entry_id, now=observed_at)
        if existing and existing["owner_actor_id"] != actor_id:
            raise EditLeaseConflict("journal edit lease is held by another actor")
        if existing:
            return self._lease_view(existing)

        lease = self._new_lease(
            journal_entry_id=journal_entry_id,
            actor_id=actor_id,
            actor_role=actor_role,
            user_activity_at=user_activity_at,
            acquired_at=observed_at,
        )
        self._repository.write_lease(self._tenant_id, journal_entry_id, lease)
        return self._lease_view(lease)

    def renew(
        self,
        *,
        journal_entry_id: str,
        actor_id: str,
        user_activity_at: datetime,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = self._resolve_now(now)
        self._validate_activity(user_activity_at=user_activity_at, now=observed_at)
        lease = self._active_lease(journal_entry_id=journal_entry_id, now=observed_at)
        if not lease or lease["owner_actor_id"] != actor_id:
            raise EditLeaseConflict("matching active journal edit lease is required")
        if user_activity_at <= lease["last_user_activity_at"]:
            raise EditLeaseActivityError("user_activity_at must be newer than the prior real activity")

        lease["last_user_activity_at"] = user_activity_at
        lease["expires_at"] = user_activity_at + LEASE_DURATION
        self._repository.write_lease(self._tenant_id, journal_entry_id, lease)
        return self._lease_view(lease)

    def release(self, *, journal_entry_id: str, actor_id: str) -> None:
        lease = self._repository.read_lease(self._tenant_id, journal_entry_id)
        if lease and lease["owner_actor_id"] != actor_id:
            raise EditLeaseConflict("only the edit lease owner can release it")
        self._repository.delete_lease(self._tenant_id, journal_entry_id)

    def takeover(
        self,
        *,
        journal_entry_id: str,
        actor_id: str,
        actor_role: str,
        reason: str,
        user_activity_at: datetime,
        expected_revision: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = self._resolve_now(now)
        self._validate_activity(user_activity_at=user_activity_at, now=observed_at)
        if expected_revision is not None:
            current = self._repository.read_current_journal_state(self._tenant_id, journal_entry_id)
            if int(current["current_revision"]) != expected_revision:
                raise NormalizedRevisionConflict(expected=expected_revision, actual=int(current["current_revision"]))
        normalized_role = actor_role.strip().lower()
        if normalized_role not in {"accountant", "admin"}:
            raise EditLeaseConflict("only accountant or admin actors can take over an edit lease")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("takeover reason must be non-empty")

        lease = self._new_lease(
            journal_entry_id=journal_entry_id,
            actor_id=actor_id,
            actor_role=normalized_role,
            user_activity_at=user_activity_at,
            acquired_at=observed_at,
        )
        lease["takeover_reason"] = normalized_reason
        self._repository.write_lease(self._tenant_id, journal_entry_id, lease)
        return self._lease_view(lease)

    def save_working_draft(
        self,
        *,
        journal_entry_id: str,
        actor_id: str,
        expected_revision: int,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = self._resolve_now(now)
        lease = self._active_lease(journal_entry_id=journal_entry_id, now=observed_at)
        if not lease or lease["owner_actor_id"] != actor_id:
            raise EditLeaseConflict("matching active journal edit lease is required")

        current = self._repository.read_current_journal_state(self._tenant_id, journal_entry_id)
        actual_revision = int(current["current_revision"])
        if expected_revision != actual_revision:
            raise NormalizedRevisionConflict(expected=expected_revision, actual=actual_revision)

        draft = {
            "journal_entry_id": journal_entry_id,
            "expected_revision": expected_revision,
            "candidate_revision": actual_revision + 1,
            "revision_role": "candidate",
            "current_revision": actual_revision,
            "export_status": current["export_status"],
            "payload": deepcopy(payload),
            "saved_by": actor_id,
            "saved_at": observed_at,
        }
        self._repository.write_working_draft(self._tenant_id, journal_entry_id, draft)
        return self._working_draft_view(draft)

    def list_candidates(self) -> list[dict[str, Any]]:
        if not hasattr(self._repository, "list_candidates"):
            return []
        candidates = self._repository.list_candidates(self._tenant_id)
        return [self._working_draft_view(candidate) for candidate in candidates]

    def _active_lease(self, *, journal_entry_id: str, now: datetime) -> dict[str, Any] | None:
        lease = self._repository.read_lease(self._tenant_id, journal_entry_id)
        if lease and lease["expires_at"] <= now:
            self._repository.delete_lease(self._tenant_id, journal_entry_id)
            return None
        return lease

    @staticmethod
    def _validate_activity(*, user_activity_at: datetime, now: datetime) -> None:
        if user_activity_at > now:
            raise EditLeaseActivityError("user_activity_at cannot be in the future")

    def _resolve_now(self, now: datetime | None) -> datetime:
        return now if now is not None else self._now()

    @staticmethod
    def _new_lease(
        *,
        journal_entry_id: str,
        actor_id: str,
        actor_role: str,
        user_activity_at: datetime,
        acquired_at: datetime,
    ) -> dict[str, Any]:
        return {
            "journal_entry_id": journal_entry_id,
            "owner_actor_id": actor_id,
            "owner_role": actor_role,
            "acquired_at": acquired_at,
            "last_user_activity_at": user_activity_at,
            "expires_at": user_activity_at + LEASE_DURATION,
            "takeover_reason": "",
        }

    @staticmethod
    def _lease_view(lease: dict[str, Any]) -> dict[str, Any]:
        return {
            "journal_entry_id": lease["journal_entry_id"],
            "owner_actor_id": lease["owner_actor_id"],
            "owner_role": lease["owner_role"],
            "acquired_at": lease["acquired_at"].isoformat(),
            "last_user_activity_at": lease["last_user_activity_at"].isoformat(),
            "expires_at": lease["expires_at"].isoformat(),
            "takeover_reason": lease["takeover_reason"],
        }

    @staticmethod
    def _working_draft_view(draft: dict[str, Any]) -> dict[str, Any]:
        return {
            "journal_entry_id": draft["journal_entry_id"],
            "expected_revision": draft["expected_revision"],
            "candidate_revision": draft["candidate_revision"],
            "revision_role": draft["revision_role"],
            "current_revision": draft["current_revision"],
            "export_status": draft["export_status"],
            "payload": deepcopy(draft["payload"]),
            "saved_by": draft["saved_by"],
            "saved_at": draft["saved_at"].isoformat(),
        }
