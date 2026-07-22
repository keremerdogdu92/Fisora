from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import psycopg2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(database_url: str, protected_root: Path) -> dict[str, bool]:
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, tenant_id, status, target_purchase_count, target_sales_count
                from protected_corpora order by id
                """
            )
            corpus_rows = cursor.fetchall()
            cursor.execute(
                """
                select id, tenant_id, corpus_id, protected_storage_path, source_sha256,
                       direction, status, current_reference_version
                from protected_corpus_items order by id
                """
            )
            item_rows = cursor.fetchall()
            corpus_by_id = {str(row[0]): row for row in corpus_rows}
            items_by_corpus: dict[str, list[tuple[Any, ...]]] = {}
            for row in item_rows:
                items_by_corpus.setdefault(str(row[2]), []).append(row)

            frozen_corpora_complete = bool(corpus_rows)
            for corpus_id, _tenant_id, status, target_purchase, target_sales in corpus_rows:
                items = items_by_corpus.get(str(corpus_id), [])
                purchase_count = sum(1 for item in items if str(item[5]) == "purchase")
                sales_count = sum(1 for item in items if str(item[5]) == "sale")
                if (
                    str(status) != "frozen"
                    or purchase_count != int(target_purchase)
                    or sales_count != int(target_sales)
                    or any(str(item[6]) != "reference_ready" for item in items)
                ):
                    frozen_corpora_complete = False

            source_hashes_match = bool(item_rows)
            for _item_id, _tenant_id, corpus_id, stored_path, expected_hash, *_rest in item_rows:
                filename = str(stored_path).replace("\\", "/").rsplit("/", 1)[-1]
                restored_path = protected_root / str(corpus_id) / filename
                if not restored_path.is_file() or _sha256(restored_path) != str(expected_hash):
                    source_hashes_match = False

            cursor.execute(
                """
                select pci.id, pci.current_reference_version,
                       array_agg(rov.version order by rov.version) filter (where rov.id is not null)
                from protected_corpus_items pci
                left join reference_outcome_versions rov on rov.corpus_item_id = pci.id
                group by pci.id, pci.current_reference_version order by pci.id
                """
            )
            reference_rows = cursor.fetchall()
            references_append_only = len(reference_rows) == len(item_rows) and all(
                int(current) > 0 and list(versions or []) == list(range(1, int(current) + 1))
                for _item_id, current, versions in reference_rows
            )

            cursor.execute(
                """
                select pci.id, rov.journal_snapshot, rov.allocation_snapshot
                from protected_corpus_items pci
                left join reference_outcome_versions rov
                  on rov.corpus_item_id = pci.id
                 and rov.version = pci.current_reference_version
                 and rov.is_authoritative = true
                order by pci.id
                """
            )
            authoritative_rows = cursor.fetchall()
            latest_references_authoritative = len(authoritative_rows) == len(item_rows) and all(
                snapshot is not None for _item_id, snapshot, _allocation in authoritative_rows
            )
            journals_balanced = latest_references_authoritative
            canonical_allocations_complete = latest_references_authoritative
            for _item_id, snapshot, allocation in authoritative_rows:
                if snapshot is None:
                    continue
                lines = (snapshot or {}).get("draft_lines") or []
                debit = sum((Decimal(str(line.get("debit") or "0")) for line in lines), Decimal("0"))
                credit = sum((Decimal(str(line.get("credit") or "0")) for line in lines), Decimal("0"))
                if debit <= 0 or debit != credit or not bool((snapshot or {}).get("is_balanced")):
                    journals_balanced = False
                decision_coverage = (allocation or {}).get("line_decision_coverage") or {}
                allocation_coverage = (allocation or {}).get("line_allocation_coverage") or {}
                expected_ids = decision_coverage.get("expected_ids") or []
                received_ids = decision_coverage.get("received_ids") or []
                if (
                    decision_coverage.get("status") != "valid"
                    or allocation_coverage.get("status") != "valid"
                    or not expected_ids
                    or len(expected_ids) != len(set(expected_ids))
                    or set(expected_ids) != set(received_ids)
                    or len(expected_ids) != len(received_ids)
                ):
                    canonical_allocations_complete = False

            cursor.execute(
                """
                select count(*) from protected_rule_versions prv
                left join reference_outcome_versions rov
                  on rov.corpus_item_id = prv.corpus_item_id and rov.version = prv.reference_version
                where rov.id is null
                """
            )
            rules_linked = int(cursor.fetchone()[0]) == 0
            tenant_boundaries_intact = all(
                str(item[1]) == str(corpus_by_id.get(str(item[2]), (None, None))[1])
                for item in item_rows
            )
            cursor.execute(
                """
                select count(*) from reference_outcome_versions rov
                join protected_corpus_items pci on pci.id = rov.corpus_item_id
                where rov.tenant_id <> pci.tenant_id
                """
            )
            tenant_boundaries_intact = tenant_boundaries_intact and int(cursor.fetchone()[0]) == 0
            cursor.execute(
                """
                select count(*) from protected_rule_versions prv
                join protected_corpus_items pci on pci.id = prv.corpus_item_id
                where prv.tenant_id <> pci.tenant_id
                """
            )
            tenant_boundaries_intact = tenant_boundaries_intact and int(cursor.fetchone()[0]) == 0

    return {
        "frozen_corpora_complete": frozen_corpora_complete,
        "source_hashes_match": source_hashes_match,
        "references_append_only": references_append_only,
        "latest_references_authoritative": latest_references_authoritative,
        "journals_balanced": journals_balanced,
        "canonical_allocations_complete": canonical_allocations_complete,
        "rules_linked": rules_linked,
        "tenant_boundaries_intact": tenant_boundaries_intact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an isolated protected-corpus restore.")
    parser.add_argument("protected_root", type=Path)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    checks = verify(args.database_url, args.protected_root.resolve())
    print(json.dumps({"verified": all(checks.values()), "checks": checks}, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
