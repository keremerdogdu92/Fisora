from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID, uuid4


ConnectFactory = Callable[[], Any]


class ProtectedCorpusConflict(RuntimeError):
    pass


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="seconds")
    return str(value or "")


class ProtectedCorpusRepository:
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

    @staticmethod
    def _corpus(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "corpus_id": str(row[0]),
            "corpus_key": str(row[1]),
            "version": int(row[2]),
            "status": str(row[3]),
            "target_purchase_count": int(row[4]),
            "target_sales_count": int(row[5]),
            "created_by": str(row[6]),
            "frozen_at": _timestamp(row[7]),
            "created_at": _timestamp(row[8]),
            "updated_at": _timestamp(row[9]),
        }

    @staticmethod
    def _item(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "item_id": str(row[0]),
            "corpus_item_id": str(row[0]),
            "corpus_id": str(row[1]),
            "client_id": str(row[2]),
            "document_ref": str(row[3]),
            "source_ref": str(row[4]),
            "source_sha256": str(row[5]),
            "protected_storage_path": str(row[6]),
            "direction": str(row[7]),
            "status": str(row[8]),
            "source_snapshot": deepcopy(row[9] or {}),
            "canonical_snapshot": deepcopy(row[10] or {}),
            "chart_snapshot": deepcopy(row[11] or {}),
            "current_reference_version": int(row[12]),
            "created_by": str(row[13]),
            "created_at": _timestamp(row[14]),
            "updated_at": _timestamp(row[15]),
        }

    def create_corpus(
        self,
        *,
        corpus_key: str,
        version: int,
        target_purchase_count: int,
        target_sales_count: int,
        created_by: str,
    ) -> dict[str, Any]:
        corpus_id = uuid4()
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into protected_corpora (
                            id, tenant_id, corpus_key, version, status,
                            target_purchase_count, target_sales_count, created_by
                        ) values (%s, %s, %s, %s, 'draft', %s, %s, %s)
                        returning id, corpus_key, version, status,
                                  target_purchase_count, target_sales_count,
                                  created_by, frozen_at, created_at, updated_at
                        """,
                        (
                            corpus_id,
                            self.tenant_id,
                            corpus_key,
                            version,
                            target_purchase_count,
                            target_sales_count,
                            created_by,
                        ),
                    )
                    row = cursor.fetchone()
        except Exception as exc:
            if "protected_corpora_tenant_id_corpus_key_version_key" in str(exc):
                raise ProtectedCorpusConflict("duplicate_corpus_version") from exc
            raise
        if row is None:
            raise ProtectedCorpusConflict("corpus_create_failed")
        return self._corpus(row)

    def get_corpus(self, corpus_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, corpus_key, version, status,
                           target_purchase_count, target_sales_count,
                           created_by, frozen_at, created_at, updated_at
                    from protected_corpora
                    where tenant_id = %s and id = %s
                    """,
                    (self.tenant_id, corpus_id),
                )
                row = cursor.fetchone()
        return self._corpus(row) if row else None

    def enroll_item(self, *, item: dict[str, Any]) -> dict[str, Any]:
        item_id = uuid4()
        taxpayer_id = item["taxpayer_id"]
        corpus_id = item["corpus_id"]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select status from protected_corpora where tenant_id = %s and id = %s for update",
                    (self.tenant_id, corpus_id),
                )
                corpus = cursor.fetchone()
                if corpus is None:
                    raise ProtectedCorpusConflict("corpus_not_found")
                if str(corpus[0]) != "draft":
                    raise ProtectedCorpusConflict("corpus_frozen")
                cursor.execute(
                    """
                    select d.id, sf.id
                    from documents d
                    left join document_sources ds on ds.document_id = d.id and ds.is_canonical = true
                    left join source_files sf on sf.id = ds.source_file_id
                    where d.tenant_id = %s and d.taxpayer_id = %s and d.source_ref = %s
                    """,
                    (self.tenant_id, taxpayer_id, item["document_ref"]),
                )
                identities = cursor.fetchone()
                document_id = identities[0] if identities else None
                source_file_id = identities[1] if identities else None
                try:
                    cursor.execute(
                        """
                        insert into protected_corpus_items (
                            id, tenant_id, taxpayer_id, corpus_id, document_id, source_file_id,
                            client_id, document_ref, source_ref, source_sha256,
                            protected_storage_path, direction, status,
                            source_snapshot, canonical_snapshot, chart_snapshot, created_by
                        ) values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'candidate',
                            %s, %s, %s, %s
                        )
                        returning id, corpus_id, client_id, document_ref, source_ref, source_sha256,
                                  protected_storage_path, direction, status, source_snapshot,
                                  canonical_snapshot, chart_snapshot, current_reference_version,
                                  created_by, created_at, updated_at
                        """,
                        (
                            item_id,
                            self.tenant_id,
                            taxpayer_id,
                            corpus_id,
                            document_id,
                            source_file_id,
                            item["client_id"],
                            item["document_ref"],
                            item["source_ref"],
                            item["source_sha256"],
                            item["protected_storage_path"],
                            item["direction"],
                            self._json(item.get("source_snapshot") or {}),
                            self._json(item.get("canonical_snapshot") or {}),
                            self._json(item.get("chart_snapshot") or {}),
                            item["created_by"],
                        ),
                    )
                except Exception as exc:
                    if "protected_corpus_items_corpus_id_source_sha256_key" in str(exc):
                        raise ProtectedCorpusConflict("duplicate_corpus_source") from exc
                    raise
                row = cursor.fetchone()
        if row is None:
            raise ProtectedCorpusConflict("corpus_item_create_failed")
        return self._item(row)

    def list_items(self, corpus_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select pci.id, pci.corpus_id, pci.client_id, pci.document_ref,
                           pci.source_ref, pci.source_sha256, pci.protected_storage_path,
                           pci.direction, pci.status, pci.source_snapshot,
                           pci.canonical_snapshot, pci.chart_snapshot,
                           pci.current_reference_version, pci.created_by,
                           pci.created_at, pci.updated_at
                    from protected_corpus_items pci
                    where pci.tenant_id = %s and pci.corpus_id = %s
                    order by pci.created_at, pci.id
                    """,
                    (self.tenant_id, corpus_id),
                )
                rows = cursor.fetchall()
        return [self._item(row) for row in rows]

    def item_for_document(self, *, client_id: str, document_ref: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select pci.id, pci.corpus_id, pci.client_id, pci.document_ref,
                           pci.source_ref, pci.source_sha256, pci.protected_storage_path,
                           pci.direction, pci.status, pci.source_snapshot,
                           pci.canonical_snapshot, pci.chart_snapshot,
                           pci.current_reference_version, pci.created_by,
                           pci.created_at, pci.updated_at
                    from protected_corpus_items pci
                    join protected_corpora pc on pc.id = pci.corpus_id
                    where pci.tenant_id = %s and pci.client_id = %s
                      and pci.document_ref = %s and pc.status <> 'archived'
                    order by pc.version desc, pci.created_at desc
                    limit 1
                    """,
                    (self.tenant_id, client_id, document_ref),
                )
                row = cursor.fetchone()
        return self._item(row) if row else None

    def append_reference(self, *, corpus_item_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
        reference_id = uuid4()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select pci.current_reference_version, pc.status
                    from protected_corpus_items pci
                    join protected_corpora pc on pc.id = pci.corpus_id
                    where pci.tenant_id = %s and pci.id = %s
                    for update
                    """,
                    (self.tenant_id, corpus_item_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ProtectedCorpusConflict("corpus_item_not_found")
                if str(row[1]) != "draft":
                    raise ProtectedCorpusConflict("corpus_frozen")
                version = int(row[0] or 0) + 1
                source_review_id = self._existing_uuid(
                    cursor,
                    table="review_decisions",
                    value=outcome.get("source_review_decision_id"),
                )
                source_revision_id = self._existing_uuid(
                    cursor,
                    table="journal_revisions",
                    value=outcome.get("source_journal_revision_id"),
                )
                cursor.execute(
                    """
                    insert into reference_outcome_versions (
                        id, tenant_id, corpus_item_id, version,
                        source_review_decision_id, source_journal_revision_id,
                        quality_label, proposal_snapshot, accountant_final_decision,
                        journal_snapshot, allocation_snapshot, provenance,
                        reviewer, reason, is_authoritative
                    ) values (%s, %s, %s, %s, %s, %s,
                              %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning id, version, quality_label, proposal_snapshot,
                              accountant_final_decision, journal_snapshot,
                              allocation_snapshot, provenance, reviewer, reason,
                              is_authoritative, created_at
                    """,
                    (
                        reference_id, self.tenant_id, corpus_item_id, version,
                        source_review_id,
                        source_revision_id,
                        outcome["quality_label"], self._json(outcome.get("proposal_snapshot") or {}),
                        self._json(outcome.get("accountant_final_decision") or {}),
                        self._json(outcome.get("journal_snapshot") or {}),
                        self._json(outcome.get("allocation_snapshot") or {}),
                        self._json(outcome.get("provenance") or {}), outcome["reviewer"],
                        outcome.get("reason", ""), bool(outcome.get("is_authoritative")),
                    ),
                )
                inserted = cursor.fetchone()
                cursor.execute(
                    """
                    update protected_corpus_items
                    set current_reference_version = %s,
                        status = case when %s then 'reference_ready' else status end,
                        updated_at = now()
                    where tenant_id = %s and id = %s
                    """,
                    (version, bool(outcome.get("is_authoritative")), self.tenant_id, corpus_item_id),
                )
        return {
            "reference_id": str(inserted[0]), "corpus_item_id": corpus_item_id,
            "version": int(inserted[1]), "quality_label": str(inserted[2]),
            "proposal_snapshot": deepcopy(inserted[3] or {}),
            "accountant_final_decision": deepcopy(inserted[4] or {}),
            "journal_snapshot": deepcopy(inserted[5] or {}),
            "allocation_snapshot": deepcopy(inserted[6] or {}),
            "provenance": deepcopy(inserted[7] or {}), "reviewer": str(inserted[8]),
            "reason": str(inserted[9] or ""), "is_authoritative": bool(inserted[10]),
            "created_at": _timestamp(inserted[11]),
        }

    def _existing_uuid(self, cursor: Any, *, table: str, value: Any) -> UUID | None:
        if table not in {"review_decisions", "journal_revisions"}:
            raise ValueError("unsupported protected reference table")
        try:
            candidate = UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None
        cursor.execute(
            f"select id from {table} where tenant_id = %s and id = %s",
            (self.tenant_id, candidate),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def list_references(self, corpus_item_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, version, quality_label, proposal_snapshot,
                           accountant_final_decision, journal_snapshot,
                           allocation_snapshot, provenance, reviewer, reason,
                           is_authoritative, created_at
                    from reference_outcome_versions
                    where tenant_id = %s and corpus_item_id = %s order by version
                    """,
                    (self.tenant_id, corpus_item_id),
                )
                rows = cursor.fetchall()
        return [{
            "reference_id": str(row[0]), "corpus_item_id": corpus_item_id,
            "version": int(row[1]), "quality_label": str(row[2]),
            "proposal_snapshot": deepcopy(row[3] or {}),
            "accountant_final_decision": deepcopy(row[4] or {}),
            "journal_snapshot": deepcopy(row[5] or {}),
            "allocation_snapshot": deepcopy(row[6] or {}),
            "provenance": deepcopy(row[7] or {}), "reviewer": str(row[8]),
            "reason": str(row[9] or ""), "is_authoritative": bool(row[10]),
            "created_at": _timestamp(row[11]),
        } for row in rows]

    def append_rule(self, *, corpus_item_id: str, rule: dict[str, Any]) -> dict[str, Any]:
        rule_id = uuid4()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select pc.status from protected_corpus_items pci
                    join protected_corpora pc on pc.id = pci.corpus_id
                    where pci.tenant_id = %s and pci.id = %s for update
                    """,
                    (self.tenant_id, corpus_item_id),
                )
                corpus = cursor.fetchone()
                if corpus is None:
                    raise ProtectedCorpusConflict("corpus_item_not_found")
                if str(corpus[0]) != "draft":
                    raise ProtectedCorpusConflict("corpus_frozen")
                cursor.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(rule["rule_key"]),))
                cursor.execute(
                    """
                    select coalesce(max(version), 0) + 1
                    from protected_rule_versions
                    where tenant_id = %s and rule_key = %s
                    """,
                    (self.tenant_id, rule["rule_key"]),
                )
                version = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    insert into protected_rule_versions (
                        id, tenant_id, taxpayer_id, corpus_item_id, reference_version,
                        rule_key, version, status, scope_snapshot, rule_snapshot, confirmed_by
                    ) select %s, %s, pci.taxpayer_id, pci.id, %s, %s, %s, %s, %s, %s, %s
                      from protected_corpus_items pci
                     where pci.tenant_id = %s and pci.id = %s
                    returning id, version, created_at
                    """,
                    (rule_id, self.tenant_id, rule["reference_version"], rule["rule_key"],
                     version, rule.get("status", "active"), self._json(rule.get("scope_snapshot") or {}),
                     self._json(rule.get("rule_snapshot") or {}), rule["confirmed_by"],
                     self.tenant_id, corpus_item_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ProtectedCorpusConflict("corpus_item_not_found")
        return {**deepcopy(rule), "protected_rule_id": str(row[0]), "corpus_item_id": corpus_item_id,
                "version": int(row[1]), "created_at": _timestamp(row[2])}

    def list_rules(self, corpus_item_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select id, reference_version, rule_key, version, status,
                           scope_snapshot, rule_snapshot, confirmed_by, created_at
                    from protected_rule_versions
                    where tenant_id = %s and corpus_item_id = %s order by created_at, id
                    """,
                    (self.tenant_id, corpus_item_id),
                )
                rows = cursor.fetchall()
        return [{"protected_rule_id": str(row[0]), "corpus_item_id": corpus_item_id,
                 "reference_version": int(row[1]), "rule_key": str(row[2]), "version": int(row[3]),
                 "status": str(row[4]), "scope_snapshot": deepcopy(row[5] or {}),
                 "rule_snapshot": deepcopy(row[6] or {}), "confirmed_by": str(row[7]),
                 "created_at": _timestamp(row[8])} for row in rows]

    def freeze_corpus(self, corpus_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select status, target_purchase_count, target_sales_count
                    from protected_corpora
                    where tenant_id = %s and id = %s
                    for update
                    """,
                    (self.tenant_id, corpus_id),
                )
                corpus_state = cursor.fetchone()
                if corpus_state is None:
                    raise ProtectedCorpusConflict("corpus_not_found")
                if str(corpus_state[0]) != "draft":
                    raise ProtectedCorpusConflict("corpus_not_draft")
                cursor.execute(
                    """
                    select
                      count(*) filter (where pci.direction = 'purchase'),
                      count(*) filter (where pci.direction = 'sale'),
                      count(*) filter (where pci.status <> 'reference_ready'),
                      count(*) filter (where rov.id is null)
                    from protected_corpus_items pci
                    left join reference_outcome_versions rov
                      on rov.corpus_item_id = pci.id
                     and rov.version = pci.current_reference_version
                     and rov.is_authoritative = true
                    where pci.tenant_id = %s and pci.corpus_id = %s
                    """,
                    (self.tenant_id, corpus_id),
                )
                counts = cursor.fetchone()
                if int(counts[0] or 0) != int(corpus_state[1]) or int(counts[1] or 0) != int(corpus_state[2]):
                    raise ProtectedCorpusConflict("corpus_direction_count_mismatch")
                if int(counts[2] or 0) or int(counts[3] or 0):
                    raise ProtectedCorpusConflict("reference_not_ready")
                cursor.execute(
                    """
                    update protected_corpora
                    set status = 'frozen', frozen_at = now(), updated_at = now()
                    where tenant_id = %s and id = %s and status = 'draft'
                    returning id, corpus_key, version, status,
                              target_purchase_count, target_sales_count,
                              created_by, frozen_at, created_at, updated_at
                    """,
                    (self.tenant_id, corpus_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ProtectedCorpusConflict("corpus_not_draft")
        return self._corpus(row)

    def reset_preservation_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    select
                      (select count(*) from protected_corpora where tenant_id = %s),
                      (select count(*) from protected_corpus_items where tenant_id = %s),
                      (select count(*) from reference_outcome_versions where tenant_id = %s),
                      (select count(*) from protected_rule_versions where tenant_id = %s)
                    """,
                    (self.tenant_id, self.tenant_id, self.tenant_id, self.tenant_id),
                )
                row = cursor.fetchone()
        return {
            "preserved_protected_corpus_count": int(row[0]),
            "preserved_protected_item_count": int(row[1]),
            "preserved_reference_outcome_count": int(row[2]),
            "preserved_protected_rule_count": int(row[3]),
        }
