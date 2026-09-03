# File: backend/app/persistence/learning_rule_repository.py
# Summary: Persists versioned accountant-confirmed learning rules and enforces a single active version per rule key.
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from app.domain.verified_rule_authority import LearningRuleConflict


ConnectFactory = Callable[[], Any]


class LearningRuleRepository:
    """Versioned learning-rule persistence with an in-memory unit-test lane."""

    def __init__(
        self,
        *,
        connect: ConnectFactory | None = None,
        tenant_id: UUID | str | None = None,
        json_value: Callable[[Any], Any] | None = None,
    ) -> None:
        self._connect = connect
        self.tenant_id = tenant_id
        self._json = json_value or (lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))
        self._rows: dict[str, list[dict[str, Any]]] = {}

    def create_version(
        self,
        *,
        rule_key: str,
        expected_version: int,
        snapshot: Mapping[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        key = str(rule_key or "").strip()
        if not key or not str(actor or "").strip():
            raise ValueError("learning_rule_input_invalid")
        if self._connect is None:
            versions = self._rows.setdefault(key, [])
            current = versions[-1] if versions else None
            current_version = int(current["version"]) if current else 0
            if current_version != int(expected_version):
                raise LearningRuleConflict("learning_rule_version_conflict")
            row = self._new_row(key, current, snapshot, actor)
            versions.append(row)
            return deepcopy(row)

        with self._connect() as conn:
            with conn.cursor() as cursor:
                current = self._current_db_row(cursor, key, lock=True)
                current_version = int(current["version"]) if current else 0
                if current_version != int(expected_version):
                    raise LearningRuleConflict("learning_rule_version_conflict")
                row = self._new_row(key, current, snapshot, actor)
                cursor.execute(
                    """
                    insert into learning_rules (
                        id, tenant_id, taxpayer_id, source_review_decision_id,
                        scope, action, category, corrected_account_code,
                        corrected_counterparty_code, reason, automation_candidate,
                        consistent_approval_count, rule_key, version, status,
                        schema_version, scope_snapshot, rule_snapshot,
                        activation_event_id, confirmed_by, confirmed_at,
                        supersedes_rule_id
                    ) values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._insert_values(row),
                )
        return deepcopy(row)

    def list_active(
        self,
        *,
        client_id: str | None = None,
        rule_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._connect is None:
            rows = [row for values in self._rows.values() for row in values if row["status"] == "active"]
            return [deepcopy(row) for row in rows if self._matches_filter(row, client_id, rule_key)]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, rule_key, version, status, schema_version,
                           scope_snapshot, rule_snapshot, activation_event_id,
                           source_review_decision_id, confirmed_by,
                           supersedes_rule_id
                    from learning_rules
                    where tenant_id = %s and status = 'active'
                      and (%s is null or rule_key = %s)
                    order by rule_key, version
                    """,
                    (self.tenant_id, rule_key, rule_key),
                )
                rows = [self._db_row(row) for row in cursor.fetchall()]
        return [row for row in rows if self._matches_filter(row, client_id, rule_key)]

    def list_versions(self, rule_key: str) -> list[dict[str, Any]]:
        if self._connect is None:
            return deepcopy(self._rows.get(str(rule_key), []))
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, rule_key, version, status, schema_version,
                           scope_snapshot, rule_snapshot, activation_event_id,
                           source_review_decision_id, confirmed_by,
                           supersedes_rule_id
                    from learning_rules
                    where tenant_id = %s and rule_key = %s
                    order by version
                    """,
                    (self.tenant_id, rule_key),
                )
                return [self._db_row(row) for row in cursor.fetchall()]

    def transition(self, *, rule_key: str, expected_version: int, status: str, actor: str) -> dict[str, Any]:
        if status not in {"active", "paused", "archived"} or not str(actor or "").strip():
            raise ValueError("learning_rule_transition_invalid")
        if self._connect is None:
            versions = self._rows.get(str(rule_key), [])
            if not versions or int(versions[-1]["version"]) != int(expected_version):
                raise LearningRuleConflict("learning_rule_version_conflict")
            row = versions[-1]
            if row["status"] == "archived" and status != "archived":
                raise LearningRuleConflict("learning_rule_archived")
            if status == "active":
                for prior in versions[:-1]:
                    if prior["status"] == "active":
                        prior["status"] = "paused"
                        prior["confirmed_by"] = str(actor)
                        prior["updated_at"] = _now()
            row["status"] = status
            row["confirmed_by"] = str(actor)
            row["updated_at"] = _now()
            return deepcopy(row)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                if status == "active":
                    cursor.execute(
                        """
                        update learning_rules
                        set status = 'paused', confirmed_by = %s, updated_at = now()
                        where tenant_id = %s and rule_key = %s and status = 'active' and version <> %s
                        """,
                        (actor, self.tenant_id, rule_key, expected_version),
                    )
                cursor.execute(
                    """
                    update learning_rules
                    set status = %s, confirmed_by = %s, updated_at = now()
                    where tenant_id = %s and rule_key = %s and version = %s
                      and status <> 'archived'
                    returning id, rule_key, version, status, schema_version,
                              scope_snapshot, rule_snapshot, activation_event_id,
                              source_review_decision_id, confirmed_by,
                              supersedes_rule_id
                    """,
                    (status, actor, self.tenant_id, rule_key, expected_version),
                )
                row = cursor.fetchone()
                if row is None:
                    raise LearningRuleConflict("learning_rule_version_conflict")
        return self._db_row(row)

    def _new_row(self, key: str, current: dict[str, Any] | None, snapshot: Mapping[str, Any], actor: str) -> dict[str, Any]:
        copied = deepcopy(dict(snapshot))
        version = int(current["version"]) + 1 if current else 1
        row = {
            **copied,
            "id": str(uuid4()),
            "rule_key": key,
            "version": version,
            "status": "draft",
            "schema_version": "v1",
            "scope_snapshot": deepcopy(copied),
            "rule_snapshot": deepcopy(copied),
            "activation_event_id": str(copied.get("activation_event_id") or ""),
            "source_review_decision_id": str(copied.get("source_review_decision_id") or ""),
            "confirmed_by": str(actor),
            "confirmed_actor_id": str(copied.get("confirmed_actor_id") or actor),
            "confirmed_at": _now(),
            "supersedes_rule_id": current.get("id") if current else None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        row["rule_id"] = row["id"]
        return row

    def _current_db_row(self, cursor: Any, rule_key: str, *, lock: bool) -> dict[str, Any] | None:
        cursor.execute(
            f"""
            select id, rule_key, version, status, schema_version,
                   scope_snapshot, rule_snapshot, activation_event_id,
                   source_review_decision_id, confirmed_by, supersedes_rule_id
            from learning_rules
            where tenant_id = %s and rule_key = %s
            order by version desc limit 1 {'for update' if lock else ''}
            """,
            (self.tenant_id, rule_key),
        )
        row = cursor.fetchone()
        return self._db_row(row) if row else None

    def _insert_values(self, row: Mapping[str, Any]) -> tuple[Any, ...]:
        scope = row.get("scope") or "general_candidate"
        action = row.get("action") or "suggest_for_similar"
        return (
            row["id"], self.tenant_id, None, row.get("source_review_decision_id") or None,
            scope, action, row.get("category") or None, row.get("account_code") or None,
            row.get("corrected_counterparty_code") or None, row.get("reason") or None,
            False, 1, row["rule_key"], row["version"], row["status"], row["schema_version"],
            self._json(row["scope_snapshot"]), self._json(row["rule_snapshot"]),
            row.get("activation_event_id") or None, row.get("confirmed_by"), row.get("confirmed_at"),
            row.get("supersedes_rule_id"),
        )

    @staticmethod
    def _db_row(row: tuple[Any, ...]) -> dict[str, Any]:
        result = {
            "id": str(row[0]), "rule_id": str(row[0]), "rule_key": str(row[1]),
            "version": int(row[2]), "status": str(row[3]), "schema_version": str(row[4]),
            "scope_snapshot": deepcopy(row[5] or {}), "rule_snapshot": deepcopy(row[6] or {}),
            "activation_event_id": str(row[7] or ""), "source_review_decision_id": str(row[8] or ""),
            "confirmed_by": str(row[9] or ""), "supersedes_rule_id": str(row[10]) if row[10] else None,
        }
        result.update(deepcopy(result["rule_snapshot"]))
        return result

    @staticmethod
    def _matches_filter(row: Mapping[str, Any], client_id: str | None, rule_key: str | None) -> bool:
        return (client_id is None or str(row.get("client_id") or "") == client_id) and (
            rule_key is None or str(row.get("rule_key") or "") == rule_key
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
