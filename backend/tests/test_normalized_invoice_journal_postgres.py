from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import os
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from apply_migrations import apply_migrations, discover_migrations
from app.domain.workspace_exports import build_workspace_export_package
from app.persistence.normalized_accounting_repository import (
    NormalizedAccountingError,
)
from app.persistence.postgres_workflow_store import (
    PostgresWorkflowStore,
    ProcessingAttemptConflict,
)
from app.services.retention_service import RetentionService
from datetime import UTC, datetime


POSTGRES_DSN = os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip()


@unittest.skipUnless(
    POSTGRES_DSN,
    "set FISORA_TEST_POSTGRES_DSN to run normalized PostgreSQL integration tests",
)
class NormalizedInvoiceJournalPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_migrations(
            POSTGRES_DSN,
            discover_migrations(BACKEND / "db" / "migrations"),
        )

    def _prepare_draft(self) -> tuple[PostgresWorkflowStore, str, str]:
        suffix = uuid4().hex
        tenant_key = f"normalized-postgres-test-{suffix}"
        client_id = f"client-{suffix}"
        document_ref = f"document-{suffix}"
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=tenant_key,
            accounting_store_target="normalized",
        )
        store.upsert_client(
            client_id=client_id,
            profile={"title": "Alici Ltd", "tax_id": "2222222222"},
            onboarding={},
        )
        store.replace_chart_accounts(
            client_id=client_id,
            accounts=[
                {
                    "code": "770.01",
                    "account_name": "Gider",
                    "is_detail_account": True,
                },
                {
                    "code": "191.01",
                    "account_name": "Indirilecek KDV",
                    "is_detail_account": True,
                },
                {
                    "code": "320.01",
                    "account_name": "Satici",
                    "is_detail_account": True,
                },
            ],
        )
        store.save_uploaded_document(
            client_id=client_id,
            document={
                "document_id": document_ref,
                "original_file_name": "purchase.xml",
                "storage_path": f"/tmp/{document_ref}.xml",
                "document_type": "einvoice_xml",
                "status": "stored",
                "storage_status": "stored",
                "size_bytes": 512,
                "sha256": uuid4().hex,
            },
        )
        canonical_line_id = f"line-{suffix}"
        store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result={
                "file_name": "purchase.xml",
                "accounting_direction": "purchase",
                "issue_date": "2026-07-18",
                "simulated_status": "review_required",
                "export_status": "review_required",
                "draft_entry_type": "purchase_invoice",
                "canonical_validation_status": "valid",
                "line_decision_coverage": {"status": "valid"},
                "line_decisions": [
                    {
                        "canonical_line_id": canonical_line_id,
                        "account_code": "770.01",
                    }
                ],
                "draft_lines": [
                    {
                        "account_code": "770.01",
                        "description": "Gider",
                        "debit": "100.00",
                        "credit": "0.00",
                    },
                    {
                        "account_code": "191.01",
                        "description": "Indirilecek KDV",
                        "debit": "20.00",
                        "credit": "0.00",
                        "tax_rate": "20",
                    },
                    {
                        "account_code": "320.01",
                        "description": "Satici",
                        "debit": "0.00",
                        "credit": "120.00",
                    },
                ],
                "canonical_invoice": {
                    "header": {
                        "invoice_no": f"INV-{suffix}",
                        "issue_date": "2026-07-18",
                        "currency": "TRY",
                    },
                    "supplier_party": {
                        "title": "Satici Ltd",
                        "tax_id": "1111111111",
                    },
                    "customer_party": {
                        "title": "Alici Ltd",
                        "tax_id": "2222222222",
                    },
                    "totals": {
                        "goods_services_total": "100.00",
                        "vat_total": "20.00",
                        "payable_total": "120.00",
                    },
                    "line_items": [
                        {
                            "canonical_line_id": canonical_line_id,
                            "source_position": "xml:InvoiceLine[1]",
                            "description": "Bakim hizmeti",
                            "quantity": "1",
                            "taxable_amount": "100.00",
                            "vat_rate": "20",
                            "tax_amount": "20.00",
                            "gross_amount": "120.00",
                        }
                    ],
                },
            },
        )
        return store, client_id, document_ref

    def test_review_evidence_without_safe_draft_persists_without_creating_journal(self) -> None:
        suffix = uuid4().hex
        client_id = f"client-{suffix}"
        document_ref = f"document-{suffix}"
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"normalized-review-evidence-{suffix}",
            accounting_store_target="normalized",
        )
        store.upsert_client(
            client_id=client_id,
            profile={"title": "Alici Ltd", "tax_id": "2222222222"},
            onboarding={},
        )
        store.save_uploaded_document(
            client_id=client_id,
            document={
                "document_id": document_ref,
                "original_file_name": "incomplete.xml",
                "storage_path": f"/tmp/{document_ref}.xml",
                "document_type": "einvoice_xml",
                "status": "stored",
                "storage_status": "stored",
                "size_bytes": 512,
                "sha256": uuid4().hex,
            },
        )
        canonical_line_id = f"line-{suffix}"

        saved = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result={
                "file_name": "incomplete.xml",
                "accounting_direction": "purchase",
                "issue_date": "2026-07-18",
                "simulated_status": "review_required",
                "export_status": "review_required",
                "draft_quality": "no_positive_amount",
                "canonical_validation_status": "invalid",
                "canonical_validation_reasons": ["line_tax_amount_missing"],
                "line_decision_coverage": {"status": "valid"},
                "line_decisions": [
                    {
                        "canonical_line_id": canonical_line_id,
                        "account_code": "770.01",
                    }
                ],
                "review_reason_codes": ["insufficient_evidence"],
                "draft_lines": [],
                "canonical_invoice": {
                    "header": {
                        "invoice_no": f"INV-{suffix}",
                        "issue_date": "2026-07-18",
                        "currency": "TRY",
                    },
                    "supplier_party": {
                        "title": "Satici Ltd",
                        "tax_id": "1111111111",
                    },
                    "customer_party": {
                        "title": "Alici Ltd",
                        "tax_id": "2222222222",
                    },
                    "totals": {
                        "goods_services_total": "0.00",
                        "vat_total": "0.00",
                        "payable_total": "0.00",
                    },
                    "line_items": [
                        {
                            "canonical_line_id": canonical_line_id,
                            "source_position": "xml:InvoiceLine[1]",
                            "description": "Kaniti eksik hizmet",
                            "quantity": "1",
                            "taxable_amount": "",
                            "vat_rate": "",
                            "tax_amount": "",
                            "gross_amount": "",
                        }
                    ],
                },
            },
        )

        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        (select count(*) from invoice_lines where tenant_id = %s),
                        (select count(*) from journal_entries where tenant_id = %s)
                    """,
                    (store.tenant_id, store.tenant_id),
                )
                canonical_line_count, journal_count = cursor.fetchone()

        self.assertEqual(saved["status"], "review_required")
        self.assertEqual(saved["result"]["normalized_revision"], 0)
        self.assertEqual(saved["result"]["draft_lines"], [])
        self.assertEqual(canonical_line_count, 1)
        self.assertEqual(journal_count, 0)

    def test_reprocessing_approved_journal_preserves_history_and_blocks_export_until_review(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        approved = self._approve(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        self.assertTrue(approved["normalized_review"]["approved"])
        approved_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(approved_document)
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select r.result_snapshot,
                           (select count(*) from ai_attempts where tenant_id = %s)
                    from documents d
                    join journal_entries j on j.id = d.current_journal_entry_id
                    join journal_revisions r
                      on r.journal_entry_id = j.id
                     and r.revision_no = j.approved_revision_no
                    where d.tenant_id = %s and d.source_ref = %s
                    """,
                    (store.tenant_id, store.tenant_id, document_ref),
                )
                approved_snapshot_before, ai_attempt_count_before = cursor.fetchone()
        reprocessed_result = deepcopy(approved_document["result"])
        reprocessed_result.update(
            {
                "simulated_status": "review_required",
                "export_status": "review_required",
                "review_reason_codes": ["line_decision_journal_incomplete"],
                "accountant_summary": "Yeni islem sonucu kontrol edilmeli.",
                "draft_quality": "gross_balanced_needs_vat_split",
                "draft_lines": [
                    {
                        "account_code": "770.01",
                        "description": "KDV dagilimi kontrol edilecek brut tutar",
                        "debit": "180.00",
                        "credit": "0.00",
                    },
                    {
                        "account_code": "320.01",
                        "description": "Satici",
                        "debit": "0.00",
                        "credit": "180.00",
                    },
                ],
                "ai_trace": [
                    {
                        "provider": "reprocess-test-ai",
                        "model": "test-model",
                        "status": "completed",
                    }
                ],
            }
        )
        canonical = reprocessed_result["canonical_invoice"]
        canonical["totals"].update(
            {
                "goods_services_total": "150.00",
                "vat_total": "30.00",
                "payable_total": "180.00",
            }
        )
        canonical["line_items"][0].update(
            {
                "taxable_amount": "150.00",
                "tax_amount": "30.00",
                "gross_amount": "180.00",
            }
        )

        saved = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=reprocessed_result,
        )

        self.assertEqual(self._revision_count(store, document_ref=document_ref), 2)
        self.assertEqual(saved["status"], "review_required")
        self.assertEqual(saved["result"]["normalized_revision"], 2)
        self.assertFalse(saved["result"]["normalized_journal_persisted"])
        self.assertIn(
            "line_decision_journal_incomplete",
            saved["result"]["review_reason_codes"],
        )
        workspace_document = next(
            item
            for item in store.get_workspace(client_id)["documents"]
            if item["document_ref"] == document_ref
        )
        self.assertEqual(workspace_document["status"], "review_required")
        self.assertEqual(
            workspace_document["result"]["accountant_summary"],
            "Yeni islem sonucu kontrol edilmeli.",
        )
        self.assertEqual(
            store.authoritative_export_workspace(client_id)["documents"],
            [],
        )
        self.assertEqual(
            store.reprocess_review_required_document_refs(
                client_id=client_id,
                document_refs=[document_ref],
            ),
            [document_ref],
        )

        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select d.status, d.current_revision_no,
                           j.current_revision_no, j.approved_revision_no,
                           r.status, r.result_snapshot,
                           (select count(*) from invoice_lines
                             where document_id = d.id),
                           (select count(*) from invoice_lines
                             where document_id = d.id and superseded_at is null),
                           (select net_amount from invoice_lines
                             where document_id = d.id and superseded_at is null
                             limit 1),
                           (select count(*) from ai_attempts
                             where tenant_id = d.tenant_id)
                    from documents d
                    join journal_entries j on j.id = d.current_journal_entry_id
                    join journal_revisions r
                      on r.journal_entry_id = j.id
                     and r.revision_no = j.approved_revision_no
                    where d.tenant_id = %s and d.source_ref = %s
                    """,
                    (store.tenant_id, document_ref),
                )
                state = cursor.fetchone()

        self.assertEqual(
            state[:5],
            ("reprocess_review_required", 2, 2, 2, "approved"),
        )
        self.assertEqual(state[5], approved_snapshot_before)
        self.assertEqual(state[6:9], (2, 1, Decimal("150.00")))
        self.assertGreater(state[9], ai_attempt_count_before)

    def test_reprocessing_reopened_journal_creates_a_new_working_revision(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        approved = self._approve(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        self.assertTrue(approved["normalized_review"]["approved"])
        store.reopen_journal(
            client_id=client_id,
            document_ref=document_ref,
            expected_revision=2,
            reviewer="accountant-1",
            reason="Yeniden islenecek.",
        )
        reopened_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(reopened_document)
        result = deepcopy(reopened_document["result"])
        result["accountant_summary"] = "Reopen sonrasi yeni islem."

        saved = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
        )

        self.assertEqual(self._revision_count(store, document_ref=document_ref), 4)
        self.assertEqual(saved["result"]["normalized_revision"], 4)
        self.assertNotEqual(
            saved["result"].get("normalized_journal_persisted"),
            False,
        )
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select d.status, d.current_revision_no,
                           j.current_revision_no, j.approved_revision_no
                    from documents d
                    join journal_entries j on j.id = d.current_journal_entry_id
                    where d.tenant_id = %s and d.source_ref = %s
                    """,
                    (store.tenant_id, document_ref),
                )
                state = cursor.fetchone()
        self.assertEqual(state, ("review_required", 4, 4, 2))

    def test_empty_draft_keeps_specific_ai_reason_without_false_evidence_label(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        result = deepcopy(stored_document["result"])
        result.update(
            {
                "draft_lines": [],
                "review_reason_codes": ["ai_correction_required"],
                "canonical_validation_status": "valid",
                "canonical_validation_reasons": [],
            }
        )

        saved = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
        )

        self.assertIn("ai_correction_required", saved["result"]["review_reason_codes"])
        self.assertNotIn("insufficient_evidence", saved["result"]["review_reason_codes"])

    def test_source_and_document_store_normalized_accounting_period(self) -> None:
        suffix = uuid4().hex
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"period-postgres-test-{suffix}",
            accounting_store_target="normalized",
        )
        client_id = f"client-{suffix}"
        store.upsert_client(
            client_id=client_id,
            profile={"title": "Period Client", "tax_id": "3333333333"},
            onboarding={},
        )
        document = {
            "document_id": f"document-{suffix}",
            "original_file_name": "february.xml",
            "storage_path": f"/tmp/{suffix}.xml",
            "document_type": "einvoice_xml",
            "status": "stored",
            "storage_status": "stored",
            "size_bytes": 12,
            "sha256": f"period-sha-{suffix}",
            "period": "2026-02",
        }

        first = store.save_uploaded_document(client_id=client_id, document=document)
        duplicate = store.save_uploaded_document(client_id=client_id, document=document)

        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select d.accounting_period, s.accounting_period,
                           (select count(*) from documents where tenant_id = %s),
                           (select count(*) from source_files where tenant_id = %s)
                    from documents d
                    join source_files s on s.tenant_id = d.tenant_id
                    where d.tenant_id = %s and d.source_ref = %s
                    """,
                    (store.tenant_id, store.tenant_id, store.tenant_id, first["document_ref"]),
                )
                accounting_period, source_period, document_count, source_count = cursor.fetchone()

        self.assertEqual(accounting_period.isoformat(), "2026-02-01")
        self.assertEqual(source_period.isoformat(), "2026-02-01")
        self.assertEqual(document_count, 1)
        self.assertEqual(source_count, 1)
        self.assertTrue(duplicate["deduplicated"])

    def test_period_retention_groups_reads_deletes_raw_only_and_is_idempotent(self) -> None:
        suffix = uuid4().hex
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"retention-postgres-test-{suffix}",
            accounting_store_target="normalized",
        )
        client_id = f"client-{suffix}"
        store.upsert_client(
            client_id=client_id,
            profile={"title": "Retention Client", "tax_id": "4444444444"},
            onboarding={},
        )
        store.upsert_portal_user(
            user_id="accountant",
            display_name="Accountant",
            role="accountant",
            allowed_client_ids=[client_id],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for index in range(3):
                path = Path(temp_dir) / f"february-{index}.xml"
                path.write_bytes(f"invoice-{index}".encode())
                paths.append(path)
                store.save_uploaded_document(
                    client_id=client_id,
                    document={
                        "document_id": f"document-{suffix}-{index}",
                        "original_file_name": path.name,
                        "storage_path": str(path),
                        "document_type": "einvoice_xml",
                        "status": "stored",
                        "storage_status": "stored",
                        "size_bytes": path.stat().st_size,
                        "sha256": f"retention-{suffix}-{index}",
                        "period": "2026-02",
                    },
                )

            service = RetentionService(store=store, document_storage_path=Path(temp_dir))
            april = service.run_due(
                now=datetime(2026, 4, 30, 12, tzinfo=UTC),
                worker_id="w1",
            )
            self.assertEqual(april["prepared_batch_count"], 1)
            self.assertEqual(april["opened_warning_count"], 0)

            may_first = service.run_due(
                now=datetime(2026, 5, 1, 0, 5, tzinfo=UTC),
                worker_id="w1",
            )
            self.assertEqual(may_first["opened_warning_count"], 1)
            pending = service.list_pending(user_id="accountant")
            self.assertEqual(pending["items"][0]["document_count"], 3)
            batch_id = pending["items"][0]["batch_id"]
            read = service.mark_read(batch_id=batch_id, user_id="accountant")
            self.assertEqual(read["status"], "warning_open")
            self.assertTrue(read["read_at"])

            deleted = service.run_due(
                now=datetime(2026, 5, 31, 23, 59, tzinfo=UTC),
                worker_id="w1",
            )
            self.assertEqual(deleted["deleted_source_count"], 3)
            self.assertEqual(deleted["resolved_batch_count"], 1)
            self.assertTrue(all(not path.exists() for path in paths))

            repeated = service.run_due(
                now=datetime(2026, 5, 31, 23, 59, tzinfo=UTC),
                worker_id="w2",
            )
            self.assertEqual(repeated["deleted_source_count"], 0)
            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select
                            (select count(*) from documents where tenant_id = %s),
                            (select count(*) from workflow_events
                             where tenant_id = %s
                               and event_type = 'raw_sources_deleted_for_period')
                        """,
                        (store.tenant_id, store.tenant_id),
                    )
                    document_count, event_count = cursor.fetchone()
            self.assertEqual(document_count, 3)
            self.assertEqual(event_count, 1)

    @staticmethod
    def _semantic_attempt(attempt_id: str, *, model: str = "fake-model") -> dict[str, object]:
        return {
            "attempt_id": attempt_id,
            "stage": "initial_account_decision",
            "canonical_line_ids": ["line-1"],
            "prompt_version": "semantic-v1",
            "provider": "fake_llm",
            "model": model,
            "candidate_account_codes": ["770.01"],
            "candidate_counterparty_codes": ["320.01"],
            "validated_response": {"suggested_account_code": "770.01"},
            "validation_errors": [],
            "accepted": False,
            "superseded_by_attempt_id": "",
        }

    @staticmethod
    def _revision_count(
        store: PostgresWorkflowStore,
        *,
        document_ref: str,
    ) -> int:
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select count(*)
                    from journal_revisions r
                    join documents d on d.id = r.document_id
                    where d.tenant_id = %s and d.source_ref = %s
                    """,
                    (store.tenant_id, document_ref),
                )
                return int(cursor.fetchone()[0])

    @staticmethod
    def _claim_processing_attempt(
        store: PostgresWorkflowStore,
        *,
        client_id: str,
        document_ref: str,
    ) -> str:
        store.create_processing_job(
            client_id=client_id,
            document_ref=document_ref,
            document_type="einvoice_xml",
            parser_kind="xml_invoice",
            intake_category="purchase_invoice",
            force_requeue=True,
        )
        claim = store.claim_next_processing_job()
        if claim is None:
            raise AssertionError("expected a processing claim")
        return str(claim["normalized_attempt_id"])

    @staticmethod
    def _approve(
        store: PostgresWorkflowStore,
        *,
        client_id: str,
        document_ref: str,
    ) -> dict[str, object]:
        return store.save_review_decision(
            client_id=client_id,
            decision={
                "document_ref": document_ref,
                "action": "approve",
                "reviewer": "accountant-1",
                "reason": "Kontrol edildi.",
                "expected_revision": 1,
            },
            learning_event={
                "document_ref": document_ref,
                "reason": "Kontrol edildi.",
            },
        )

    def test_reopen_preserves_canonical_line_allocations(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        review = self._approve(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        self.assertTrue(review["normalized_review"]["approved"])

        store.reopen_journal(
            client_id=client_id,
            document_ref=document_ref,
            expected_revision=2,
            reviewer="accountant-1",
            reason="Hesap aciklamasi duzeltilecek.",
        )

        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select r.revision_no, r.id, l.line_no, a.invoice_line_id,
                           a.allocation_kind, a.allocated_net, a.allocated_tax,
                           a.allocated_gross, a.currency, a.allocation_method,
                           a.evidence
                    from journal_revisions r
                    join journal_revision_lines l
                      on l.journal_revision_id = r.id
                    join journal_line_allocations a
                      on a.journal_revision_line_id = l.id
                    where r.tenant_id = %s
                      and r.revision_no in (2, 3)
                    order by r.revision_no, l.line_no,
                             a.allocation_kind, a.invoice_line_id
                    """,
                    (store.tenant_id,),
                )
                allocation_rows = cursor.fetchall()

        source_rows = [row for row in allocation_rows if row[0] == 2]
        reopened_rows = [row for row in allocation_rows if row[0] == 3]
        self.assertEqual(len(source_rows), 3)
        self.assertEqual(
            [row[2:9] for row in reopened_rows],
            [row[2:9] for row in source_rows],
        )
        source_revision_id = str(source_rows[0][1])
        for source_row, reopened_row in zip(source_rows, reopened_rows, strict=True):
            self.assertEqual(reopened_row[9], "reopen_copy")
            self.assertEqual(
                reopened_row[10]["copied_from_revision_id"],
                source_revision_id,
            )
            self.assertEqual(
                reopened_row[10]["source_allocation_method"],
                source_row[9],
            )

    def test_projection_failure_rolls_back_normalized_review(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        trigger_name = f"fail_review_projection_{uuid4().hex}"
        function_name = f"{trigger_name}_fn"
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    create function {function_name}() returns trigger
                    language plpgsql
                    as $$
                    begin
                        if new.record_type = 'review_decision' then
                            raise exception 'forced review projection failure';
                        end if;
                        return new;
                    end
                    $$;
                    create trigger {trigger_name}
                    before insert or update on workflow_records
                    for each row execute function {function_name}();
                    """
                )
        try:
            with self.assertRaisesRegex(Exception, "forced review projection failure"):
                self._approve(
                    store,
                    client_id=client_id,
                    document_ref=document_ref,
                )

            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select d.current_revision_no, count(r.id)
                        from documents d
                        join journal_revisions r on r.document_id = d.id
                        where d.tenant_id = %s and d.source_ref = %s
                        group by d.current_revision_no
                        """,
                        (store.tenant_id, document_ref),
                    )
                    current_revision, revision_count = cursor.fetchone()

            self.assertEqual(current_revision, 1)
            self.assertEqual(revision_count, 1)
        finally:
            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"drop trigger if exists {trigger_name} on workflow_records"
                    )
                    cursor.execute(f"drop function if exists {function_name}()")

    def test_processing_attempt_retry_is_idempotent_and_digest_conflict_rolls_back(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        attempt_id = self._claim_processing_attempt(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        result = deepcopy(stored_document["result"])

        first = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
            attempt_id=attempt_id,
        )
        retried = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=result,
            attempt_id=attempt_id,
        )

        self.assertEqual(retried, first)
        self.assertEqual(first["_processing_attempt"]["attempt_id"], attempt_id)
        self.assertEqual(first["_processing_attempt"]["normalized_revision"], 2)
        self.assertEqual(self._revision_count(store, document_ref=document_ref), 2)

        with self.assertRaises(ProcessingAttemptConflict):
            store.save_simulation_result(
                client_id=client_id,
                document_ref=document_ref,
                result={**result, "accountant_summary": "conflicting processing input"},
                attempt_id=attempt_id,
            )

        self.assertEqual(
            store._get_record(client_id, "document", document_ref),
            first,
        )
        self.assertEqual(self._revision_count(store, document_ref=document_ref), 2)

    def test_conflicting_semantic_attempt_id_leaves_postgres_projection_and_revision_unchanged(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        first_input = deepcopy(stored_document["result"])
        first_input["semantic_attempts"] = [self._semantic_attempt("semantic-conflict")]
        first_input["accepted_semantic_attempt_id"] = ""
        first = store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result=first_input,
        )

        conflicting_input = deepcopy(first_input)
        conflicting_input["semantic_attempts"] = [
            self._semantic_attempt("semantic-conflict", model="different-model")
        ]
        with self.assertRaisesRegex(ValueError, "semantic attempt_id conflict"):
            store.save_simulation_result(
                client_id=client_id,
                document_ref=document_ref,
                result=conflicting_input,
            )

        self.assertEqual(store._get_record(client_id, "document", document_ref), first)
        self.assertEqual(self._revision_count(store, document_ref=document_ref), 2)

    def test_concurrent_document_writers_preserve_both_semantic_attempts(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        second_store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=store.tenant_key,
            accounting_store_target="normalized",
        )
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        base_result = deepcopy(stored_document["result"])
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def save(current_store: PostgresWorkflowStore, attempt_id: str) -> None:
            try:
                result = deepcopy(base_result)
                result["semantic_attempts"] = [self._semantic_attempt(attempt_id)]
                result["accepted_semantic_attempt_id"] = ""
                barrier.wait(timeout=5)
                current_store.save_simulation_result(
                    client_id=client_id,
                    document_ref=document_ref,
                    result=result,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first_thread = threading.Thread(target=save, args=(store, "concurrent-first"))
        second_thread = threading.Thread(target=save, args=(second_store, "concurrent-second"))
        first_thread.start()
        second_thread.start()
        first_thread.join(timeout=15)
        second_thread.join(timeout=15)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(errors, [])
        final_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(final_document)
        self.assertEqual(
            {
                item["attempt_id"]
                for item in final_document["result"]["semantic_attempts"]
            },
            {"concurrent-first", "concurrent-second"},
        )
        self.assertEqual(self._revision_count(store, document_ref=document_ref), 3)

    def test_projection_failure_rolls_back_normalized_processing_revision(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        result = dict(stored_document["result"])
        trigger_name = f"fail_document_projection_{uuid4().hex}"
        function_name = f"{trigger_name}_fn"
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    create function {function_name}() returns trigger
                    language plpgsql
                    as $$
                    begin
                        if new.record_type = 'document' then
                            raise exception 'forced document projection failure';
                        end if;
                        return new;
                    end
                    $$;
                    create trigger {trigger_name}
                    before insert or update on workflow_records
                    for each row execute function {function_name}();
                    """
                )
        try:
            with self.assertRaisesRegex(
                Exception,
                "forced document projection failure",
            ):
                store.save_simulation_result(
                    client_id=client_id,
                    document_ref=document_ref,
                    result=result,
                )

            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select d.current_revision_no, count(r.id)
                        from documents d
                        join journal_revisions r on r.document_id = d.id
                        where d.tenant_id = %s and d.source_ref = %s
                        group by d.current_revision_no
                        """,
                        (store.tenant_id, document_ref),
                    )
                    current_revision, revision_count = cursor.fetchone()

            self.assertEqual(current_revision, 1)
            self.assertEqual(revision_count, 1)
        finally:
            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"drop trigger if exists {trigger_name} on workflow_records"
                    )
                    cursor.execute(f"drop function if exists {function_name}()")

    def test_projection_failure_rolls_back_normalized_source_intake(self) -> None:
        suffix = uuid4().hex
        client_id = f"client-{suffix}"
        document_ref = f"document-{suffix}"
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"normalized-upload-test-{suffix}",
            accounting_store_target="normalized",
        )
        store.upsert_client(
            client_id=client_id,
            profile={"title": "Alici Ltd", "tax_id": "2222222222"},
            onboarding={},
        )
        trigger_name = f"fail_upload_projection_{uuid4().hex}"
        function_name = f"{trigger_name}_fn"
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    create function {function_name}() returns trigger
                    language plpgsql
                    as $$
                    begin
                        if new.record_type = 'uploaded_document' then
                            raise exception 'forced upload projection failure';
                        end if;
                        return new;
                    end
                    $$;
                    create trigger {trigger_name}
                    before insert or update on workflow_records
                    for each row execute function {function_name}();
                    """
                )
        try:
            with self.assertRaisesRegex(
                Exception,
                "forced upload projection failure",
            ):
                store.save_uploaded_document(
                    client_id=client_id,
                    document={
                        "document_id": document_ref,
                        "original_file_name": "purchase.xml",
                        "storage_path": f"/tmp/{document_ref}.xml",
                        "document_type": "einvoice_xml",
                        "status": "stored",
                        "storage_status": "stored",
                        "size_bytes": 512,
                        "sha256": uuid4().hex,
                    },
                )

            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select
                            (select count(*) from documents where tenant_id = %s),
                            (select count(*) from source_files where tenant_id = %s)
                        """,
                        (store.tenant_id, store.tenant_id),
                    )
                    document_count, source_count = cursor.fetchone()

            self.assertEqual(document_count, 0)
            self.assertEqual(source_count, 0)
        finally:
            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"drop trigger if exists {trigger_name} on workflow_records"
                    )
                    cursor.execute(f"drop function if exists {function_name}()")

    def test_projection_failure_rolls_back_normalized_reopen(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        review = self._approve(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        self.assertTrue(review["normalized_review"]["approved"])
        trigger_name = f"fail_reopen_projection_{uuid4().hex}"
        function_name = f"{trigger_name}_fn"
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    create function {function_name}() returns trigger
                    language plpgsql
                    as $$
                    begin
                        if new.record_type = 'document' then
                            raise exception 'forced reopen projection failure';
                        end if;
                        return new;
                    end
                    $$;
                    create trigger {trigger_name}
                    before insert or update on workflow_records
                    for each row execute function {function_name}();
                    """
                )
        try:
            with self.assertRaisesRegex(
                Exception,
                "forced reopen projection failure",
            ):
                store.reopen_journal(
                    client_id=client_id,
                    document_ref=document_ref,
                    expected_revision=2,
                    reviewer="accountant-1",
                    reason="Hesap aciklamasi duzeltilecek.",
                )

            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select d.current_revision_no, count(r.id)
                        from documents d
                        join journal_revisions r on r.document_id = d.id
                        where d.tenant_id = %s and d.source_ref = %s
                        group by d.current_revision_no
                        """,
                        (store.tenant_id, document_ref),
                    )
                    current_revision, revision_count = cursor.fetchone()

            self.assertEqual(current_revision, 2)
            self.assertEqual(revision_count, 2)
        finally:
            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"drop trigger if exists {trigger_name} on workflow_records"
                    )
                    cursor.execute(f"drop function if exists {function_name}()")

    def test_same_client_id_remains_isolated_between_tenants(self) -> None:
        suffix = uuid4().hex
        client_id = f"shared-client-{suffix}"
        first = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"tenant-a-{suffix}",
            accounting_store_target="normalized",
        )
        second = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"tenant-b-{suffix}",
            accounting_store_target="normalized",
        )
        for store, title in ((first, "Tenant A"), (second, "Tenant B")):
            store.upsert_client(
                client_id=client_id,
                profile={"title": title, "tax_id": "2222222222"},
                onboarding={},
            )

        with first._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, tenant_id, display_name
                    from taxpayers
                    where tenant_id in (%s, %s)
                    order by display_name
                    """,
                    (first.tenant_id, second.tenant_id),
                )
                rows = cursor.fetchall()

        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][0], rows[1][0])
        self.assertEqual({row[1] for row in rows}, {first.tenant_id, second.tenant_id})
        self.assertEqual({row[2] for row in rows}, {"Tenant A", "Tenant B"})

    def test_reclaimed_job_fences_stale_processing_attempt(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        result = dict(stored_document["result"])
        result["semantic_attempts"] = [self._semantic_attempt("stale-attempt-evidence")]
        result["accepted_semantic_attempt_id"] = ""
        job = store.create_processing_job(
            client_id=client_id,
            document_ref=document_ref,
            document_type="einvoice_xml",
            parser_kind="xml_invoice",
            intake_category="purchase_invoice",
            force_requeue=True,
        )
        first_claim = store.claim_next_processing_job()
        self.assertIsNotNone(first_claim)
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update processing_jobs
                    set claim_expires_at = now() - interval '1 second'
                    where id = %s
                    """,
                    (job["id"],),
                )
        second_claim = store.claim_next_processing_job()
        self.assertIsNotNone(second_claim)
        self.assertNotEqual(
            first_claim["normalized_attempt_id"],
            second_claim["normalized_attempt_id"],
        )

        with self.assertRaisesRegex(
            NormalizedAccountingError,
            "stale processing attempt",
        ):
            store.save_simulation_result(
                client_id=client_id,
                document_ref=document_ref,
                result=result,
                attempt_id=str(first_claim["normalized_attempt_id"]),
            )
        stale_completion = store.update_processing_job(
            job_id=str(job["id"]),
            status="completed",
            error_message="",
            processing_metrics={},
            attempt_id=str(first_claim["normalized_attempt_id"]),
        )

        self.assertIsNone(stale_completion)
        with store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select current_attempt_id, status
                    from processing_jobs
                    where id = %s
                    """,
                    (job["id"],),
                )
                current_attempt_id, status = cursor.fetchone()
                cursor.execute(
                    """
                    select count(*)
                    from journal_revisions r
                    join documents d on d.id = r.document_id
                    where d.tenant_id = %s and d.source_ref = %s
                    """,
                    (store.tenant_id, document_ref),
                )
                revision_count = cursor.fetchone()[0]

        current_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(current_document)
        persisted_attempt_ids = {
            item["attempt_id"]
            for item in current_document["result"].get("semantic_attempts", [])
        }

        self.assertEqual(str(current_attempt_id), second_claim["normalized_attempt_id"])
        self.assertEqual(status, "processing")
        self.assertEqual(revision_count, 1)
        self.assertNotIn("stale-attempt-evidence", persisted_attempt_ids)

    def test_sales_invoice_uses_real_normalized_owner_and_export_projection(self) -> None:
        suffix = uuid4().hex
        client_id = f"sales-client-{suffix}"
        document_ref = f"sales-document-{suffix}"
        canonical_line_id = f"sales-line-{suffix}"
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=f"normalized-sales-test-{suffix}",
            accounting_store_target="normalized",
        )
        store.upsert_client(
            client_id=client_id,
            profile={"title": "Satici Ltd", "tax_id": "2222222222"},
            onboarding={},
        )
        store.replace_chart_accounts(
            client_id=client_id,
            accounts=[
                {
                    "code": "120.01",
                    "account_name": "Alici",
                    "is_detail_account": True,
                },
                {
                    "code": "600.01",
                    "account_name": "Yurtici Satislar",
                    "is_detail_account": True,
                },
                {
                    "code": "391.01",
                    "account_name": "Hesaplanan KDV",
                    "is_detail_account": True,
                },
            ],
        )
        store.save_uploaded_document(
            client_id=client_id,
            document={
                "document_id": document_ref,
                "original_file_name": "sales.xml",
                "storage_path": f"/tmp/{document_ref}.xml",
                "document_type": "einvoice_xml",
                "status": "stored",
                "storage_status": "stored",
                "size_bytes": 512,
                "sha256": uuid4().hex,
            },
        )
        store.save_simulation_result(
            client_id=client_id,
            document_ref=document_ref,
            result={
                "file_name": "sales.xml",
                "accounting_direction": "sales",
                "issue_date": "2026-07-18",
                "simulated_status": "review_required",
                "export_status": "review_required",
                "draft_entry_type": "sales_invoice",
                "canonical_validation_status": "valid",
                "line_decision_coverage": {"status": "valid"},
                "line_decisions": [
                    {
                        "canonical_line_id": canonical_line_id,
                        "account_code": "600.01",
                    }
                ],
                "draft_lines": [
                    {
                        "account_code": "120.01",
                        "description": "Alici",
                        "debit": "120.00",
                        "credit": "0.00",
                    },
                    {
                        "account_code": "600.01",
                        "description": "Yurtici Satislar",
                        "debit": "0.00",
                        "credit": "100.00",
                    },
                    {
                        "account_code": "391.01",
                        "description": "Hesaplanan KDV",
                        "debit": "0.00",
                        "credit": "20.00",
                        "tax_rate": "20",
                    },
                ],
                "canonical_invoice": {
                    "header": {
                        "invoice_no": f"SALE-{suffix}",
                        "issue_date": "2026-07-18",
                        "currency": "TRY",
                    },
                    "supplier_party": {
                        "title": "Satici Ltd",
                        "tax_id": "2222222222",
                    },
                    "customer_party": {
                        "title": "Alici Ltd",
                        "tax_id": "1111111111",
                    },
                    "totals": {
                        "goods_services_total": "100.00",
                        "vat_total": "20.00",
                        "payable_total": "120.00",
                    },
                    "line_items": [
                        {
                            "canonical_line_id": canonical_line_id,
                            "source_position": "xml:InvoiceLine[1]",
                            "description": "Danismanlik",
                            "quantity": "1",
                            "taxable_amount": "100.00",
                            "vat_rate": "20",
                            "tax_amount": "20.00",
                            "gross_amount": "120.00",
                        }
                    ],
                },
            },
        )
        review = self._approve(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        workspace = store.authoritative_export_workspace(client_id)
        export_build = build_workspace_export_package(
            workspace,
            export_type="zirve_universal_csv",
        )

        self.assertTrue(review["normalized_review"]["approved"])
        self.assertEqual(len(workspace["documents"]), 1)
        self.assertEqual(
            workspace["documents"][0]["result"]["accounting_direction"],
            "sales",
        )
        self.assertEqual(export_build.candidate_count, 1)
        self.assertEqual(len(export_build.package.entries), 1)
        self.assertEqual(
            [
                (line.account_code, line.debit, line.credit)
                for line in export_build.package.entries[0].lines
            ],
            [
                ("120.01", Decimal("120.00"), Decimal("0.00")),
                ("600.01", Decimal("0.00"), Decimal("100.00")),
                ("391.01", Decimal("0.00"), Decimal("20.00")),
            ],
        )
        self.assertTrue(export_build.package.entries[0].is_balanced)

    def test_approval_rejects_missing_canonical_line_decision(self) -> None:
        store, client_id, document_ref = self._prepare_draft()
        stored_document = store._get_record(client_id, "document", document_ref)
        self.assertIsNotNone(stored_document)
        stored_document["result"]["line_decisions"] = []
        store._upsert_record(
            client_id,
            "document",
            document_ref,
            stored_document,
        )

        review = self._approve(
            store,
            client_id=client_id,
            document_ref=document_ref,
        )
        corrected_result = review["corrected_document"]["result"]

        self.assertFalse(review["normalized_review"]["approved"])
        self.assertEqual(
            corrected_result["line_decision_coverage"]["status"],
            "invalid",
        )
        self.assertIn(
            "canonical_line_decision_incomplete",
            corrected_result["review_reason_codes"],
        )
        self.assertEqual(corrected_result["export_status"], "review_required")


if __name__ == "__main__":
    unittest.main()
