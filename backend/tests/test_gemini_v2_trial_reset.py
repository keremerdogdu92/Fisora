from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import NAMESPACE_URL, uuid4, uuid5
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apply_migrations import apply_migrations, discover_migrations
from app.persistence.postgres_workflow_store import PostgresWorkflowStore, tenant_uuid


POSTGRES_DSN = os.environ.get("FISORA_TEST_POSTGRES_DSN", "").strip()


class GeminiTrialResetContractTests(unittest.TestCase):
    def test_reset_contract_exposes_dry_run_summary_and_entrypoint(self) -> None:
        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        summary_type = getattr(module, "GeminiTrialResetSummary", None)
        reset = getattr(module, "reset_gemini_trial_outputs", None)
        self.assertIsNotNone(summary_type)
        self.assertTrue(callable(reset))
        self.assertEqual(
            tuple(summary_type.__dataclass_fields__),
            (
                "tenant_key",
                "eligible_document_count",
                "deleted_counts",
                "reset_document_count",
                "requeued_job_count",
                "artifact_body_delete_count",
                "dry_run",
            ),
        )

    def test_apply_requires_exact_confirmation_before_database_connection(self) -> None:
        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        with self.assertRaisesRegex(Exception, "confirm-tenant-key"):
            module.reset_gemini_trial_outputs(
                dsn="postgresql://not-opened.invalid/test",
                tenant_key="tenant-a",
                artifact_storage_root=Path("."),
                apply=True,
                confirm_tenant_key="tenant-b",
            )

    def test_cli_reports_cleanup_failure_with_nonzero_exit(self) -> None:
        cli = importlib.import_module("reset_gemini_v2_trial_outputs")
        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        summary = module.GeminiTrialResetSummary(
            tenant_key="tenant-a",
            eligible_document_count=1,
            deleted_counts={"artifact_body_cleanup_failures": 1},
            reset_document_count=1,
            requeued_job_count=1,
            artifact_body_delete_count=0,
            dry_run=False,
        )
        output = io.StringIO()
        with patch.object(cli, "reset_gemini_trial_outputs", return_value=summary):
            with redirect_stdout(output):
                exit_code = cli.main(
                    [
                        "--dsn", "unused",
                        "--tenant-key", "tenant-a",
                        "--artifact-storage-root", ".",
                        "--apply",
                        "--confirm-tenant-key", "tenant-a",
                    ]
                )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("artifact_body_cleanup_failures", output.getvalue())


@unittest.skipUnless(
    POSTGRES_DSN,
    "set FISORA_TEST_POSTGRES_DSN to run Gemini V2 trial-reset PostgreSQL tests",
)
class GeminiTrialResetPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_migrations(POSTGRES_DSN, discover_migrations(BACKEND / "db" / "migrations"))

    def _seed_document(self, *, tenant_id: str, suffix: str, escape_artifact: bool = False) -> dict[str, str]:
        import psycopg

        client_id = f"client-{suffix}"
        taxpayer_id = str(uuid5(NAMESPACE_URL, f"fisora:taxpayer:{tenant_id}:{client_id}"))
        document_id = str(uuid4())
        source_id = str(uuid4())
        job_id = str(uuid4())
        attempt_id = str(uuid4())
        ai_attempt_id = str(uuid4())
        invoice_line_id = str(uuid4())
        entry_id = str(uuid4())
        revision_id = str(uuid4())
        revision_line_id = str(uuid4())
        allocation_id = str(uuid4())
        export_id = str(uuid4())
        export_item_id = str(uuid4())
        review_id = str(uuid4())
        rule_id = str(uuid4())
        event_id = str(uuid4())
        artifact_id = str(uuid4())
        revision_review_id = str(uuid4())
        revision_rule_id = str(uuid4())
        legacy_entry_line_id = str(uuid4())
        source_ref = f"source-{suffix}"
        source_path = str(Path(self.artifact_root).parent / f"input-{suffix}.pdf")
        source_digest = hashlib.sha256(suffix.encode()).hexdigest()
        Path(source_path).write_bytes(suffix.encode())
        artifact_root = Path(self.artifact_root)
        body_dir = artifact_root / suffix
        body_dir.mkdir(parents=True, exist_ok=True)
        request_path = body_dir / "request.json"
        response_path = body_dir / "response.json"
        request_path.write_text("{}", encoding="utf-8")
        response_path.write_text("{}", encoding="utf-8")
        if escape_artifact:
            request_path_value = str(artifact_root.parent / "escape.json")
            (artifact_root.parent / "escape.json").write_text("escape", encoding="utf-8")
        else:
            request_path_value = str(request_path)
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "insert into taxpayers (id, tenant_id, display_name) values (%s, %s, %s)",
                    (taxpayer_id, tenant_id, f"Taxpayer {suffix}"),
                )
                cursor.execute(
                    """
                    insert into documents
                        (id, tenant_id, taxpayer_id, source_filename, stored_filename,
                         storage_path, source_ref, document_type, status, parse_notes,
                         risk_flags, invoice_number, current_revision_no)
                    values (%s, %s, %s, %s, %s, %s, %s, 'invoice_pdf', 'completed',
                            '["old-note"]', '["old-risk"]', 'OLD-001', 2)
                    """,
                    (document_id, tenant_id, taxpayer_id, f"{suffix}.pdf", f"{suffix}.pdf", source_path, source_ref),
                )
                cursor.execute(
                    """
                    insert into source_files
                        (id, tenant_id, taxpayer_id, source_ref, original_filename,
                         storage_path, sha256)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (source_id, tenant_id, taxpayer_id, source_ref, f"{suffix}.pdf", source_path, source_digest),
                )
                cursor.execute(
                    """
                    insert into document_sources
                        (id, tenant_id, taxpayer_id, document_id, source_file_id,
                         relationship_type, is_canonical)
                    values (%s, %s, %s, %s, %s, 'canonical', true)
                    """,
                    (str(uuid4()), tenant_id, taxpayer_id, document_id, source_id),
                )
                cursor.execute(
                    """
                    insert into processing_jobs
                        (id, tenant_id, taxpayer_id, document_id, document_ref,
                         document_type, parser_kind, intake_category, status)
                    values (%s, %s, %s, %s, %s, 'invoice_pdf', 'pdf', 'purchase_invoice', 'completed')
                    """,
                    (job_id, tenant_id, taxpayer_id, document_id, source_ref),
                )
                cursor.execute(
                    """
                    insert into processing_attempts
                        (id, tenant_id, taxpayer_id, processing_job_id, attempt_no, status)
                    values (%s, %s, %s, %s, 1, 'completed')
                    """,
                    (attempt_id, tenant_id, taxpayer_id, job_id),
                )
                cursor.execute(
                    """
                    insert into ai_attempts
                        (id, tenant_id, taxpayer_id, document_id, processing_attempt_id,
                         provider, status)
                    values (%s, %s, %s, %s, %s, 'gemini', 'successful')
                    """,
                    (ai_attempt_id, tenant_id, taxpayer_id, document_id, attempt_id),
                )
                cursor.execute(
                    """
                    insert into invoice_lines
                        (id, document_id, tenant_id, taxpayer_id, line_no, raw_text)
                    values (%s, %s, %s, %s, 1, 'old generated line')
                    """,
                    (invoice_line_id, document_id, tenant_id, taxpayer_id),
                )
                cursor.execute(
                    """
                    insert into journal_entries
                        (id, tenant_id, taxpayer_id, document_id, entry_date, entry_type,
                         status, total_debit, total_credit)
                    values (%s, %s, %s, %s, '2026-08-01', 'invoice', 'draft', 10, 10)
                    """,
                    (entry_id, tenant_id, taxpayer_id, document_id),
                )
                cursor.execute(
                    """
                    insert into journal_revisions
                        (id, tenant_id, taxpayer_id, document_id, journal_entry_id,
                         revision_no, status, total_debit, total_credit, is_balanced,
                         export_status, result_snapshot)
                    values (%s, %s, %s, %s, %s, 1, 'draft', 10, 10, true,
                            'review_required', '{}')
                    """,
                    (revision_id, tenant_id, taxpayer_id, document_id, entry_id),
                )
                cursor.execute(
                    "update documents set current_journal_entry_id = %s where id = %s",
                    (entry_id, document_id),
                )
                cursor.execute(
                    """
                    insert into journal_entry_lines
                        (id, journal_entry_id, tenant_id, taxpayer_id, line_no,
                         raw_account_code, debit_amount, credit_amount)
                    values (%s, %s, %s, %s, 1, '770', 10, 0)
                    """,
                    (legacy_entry_line_id, entry_id, tenant_id, taxpayer_id),
                )
                cursor.execute(
                    """
                    insert into journal_revision_lines
                        (id, tenant_id, taxpayer_id, journal_revision_id, line_no,
                         raw_account_code, debit_amount, credit_amount)
                    values (%s, %s, %s, %s, 1, '770', 10, 0)
                    """,
                    (revision_line_id, tenant_id, taxpayer_id, revision_id),
                )
                cursor.execute(
                    """
                    insert into journal_line_allocations
                        (id, tenant_id, taxpayer_id, journal_revision_line_id,
                         invoice_line_id, allocation_kind, allocated_net,
                         allocation_method)
                    values (%s, %s, %s, %s, %s, 'net', 10, 'generated')
                    """,
                    (allocation_id, tenant_id, taxpayer_id, revision_line_id, invoice_line_id),
                )
                cursor.execute(
                    """
                    insert into export_batches
                        (id, tenant_id, taxpayer_id, export_type, status)
                    values (%s, %s, %s, 'lu', 'draft')
                    """,
                    (export_id, tenant_id, taxpayer_id),
                )
                cursor.execute(
                    """
                    insert into export_batch_items
                        (id, tenant_id, taxpayer_id, export_batch_id, journal_revision_id)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (export_item_id, tenant_id, taxpayer_id, export_id, revision_id),
                )
                cursor.execute(
                    """
                    insert into review_decisions
                        (id, tenant_id, taxpayer_id, document_id, journal_entry_id,
                         action, reason)
                    values (%s, %s, %s, %s, %s, 'correct', 'old generated review')
                    """,
                    (review_id, tenant_id, taxpayer_id, document_id, entry_id),
                )
                cursor.execute(
                    """
                    insert into review_decisions
                        (id, tenant_id, taxpayer_id, document_id, journal_entry_id,
                         journal_revision_id, action, reason)
                    values (%s, %s, %s, null, null, %s, 'correct', 'revision-linked review')
                    """,
                    (revision_review_id, tenant_id, taxpayer_id, revision_id),
                )
                cursor.execute(
                    """
                    insert into learning_rules
                        (id, tenant_id, taxpayer_id, source_review_decision_id,
                         scope, action)
                    values (%s, %s, %s, %s, 'counterparty', 'select')
                    """,
                    (rule_id, tenant_id, taxpayer_id, review_id),
                )
                cursor.execute(
                    """
                    insert into learning_rules
                        (id, tenant_id, taxpayer_id, source_review_decision_id,
                         scope, action)
                    values (%s, %s, %s, %s, 'line', 'select')
                    """,
                    (revision_rule_id, tenant_id, taxpayer_id, revision_review_id),
                )
                cursor.execute(
                    """
                    insert into workflow_events
                        (id, tenant_id, taxpayer_id, document_id, event_type, status)
                    values (%s, %s, %s, %s, 'accounting_completed', 'ok')
                    """,
                    (event_id, tenant_id, taxpayer_id, document_id),
                )
                cursor.execute(
                    """
                    insert into document_ai_artifacts
                        (id, tenant_id, taxpayer_id, document_id, source_file_id,
                         artifact_kind, revision_no, stage, status, provider,
                         source_file_sha256, request_storage_path, request_sha256,
                         response_storage_path, response_sha256)
                    values (%s, %s, %s, %s, %s, 'provider_receipt', 1,
                            'accounting_selection', 'successful', 'gemini', %s,
                            %s, %s, %s, %s)
                    """,
                    (
                        artifact_id,
                        tenant_id,
                        taxpayer_id,
                        document_id,
                        source_id,
                        source_digest,
                        request_path_value,
                        hashlib.sha256(b"{}").hexdigest(),
                        str(response_path),
                        hashlib.sha256(b"{}").hexdigest(),
                    ),
                )
                workflow_payloads = (
                    (
                        "uploaded_document",
                        source_ref,
                        {
                            "id": source_ref,
                            "document_ref": source_ref,
                            "document_type": "invoice_pdf",
                            "parser_kind": "pdf",
                            "intake_category": "purchase_invoice",
                            "storage_path": source_path,
                            "status": "uploaded",
                        },
                    ),
                    (
                        "document",
                        source_ref,
                        {"id": source_ref, "document_ref": source_ref, "status": "completed", "result": {"stale": True}},
                    ),
                    (
                        "processing_job",
                        job_id,
                        {
                            "id": job_id,
                            "client_id": client_id,
                            "document_ref": source_ref,
                            "document_type": "invoice_pdf",
                            "parser_kind": "pdf",
                            "intake_category": "purchase_invoice",
                            "status": "completed",
                            "attempt_count": 3,
                            "error_message": "old",
                            "claimed_by": "old-worker",
                        },
                    ),
                    (
                        "document_pipeline_event",
                        str(uuid4()),
                        {"document_ref": source_ref, "step": "accounting_completed", "status": "ok"},
                    ),
                )
                for record_type, record_key, payload in workflow_payloads:
                    cursor.execute(
                        """
                        insert into workflow_records
                            (id, tenant_id, client_id, record_type, record_key, payload)
                        values (%s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (str(uuid4()), tenant_id, client_id, record_type, record_key, json.dumps(payload)),
                    )
        return {
            "taxpayer_id": taxpayer_id,
            "document_id": document_id,
            "source_id": source_id,
            "job_id": job_id,
            "source_ref": source_ref,
            "request_path": request_path_value,
            "response_path": str(response_path),
            "source_path": source_path,
            "source_content": suffix,
            "client_id": client_id,
        }

    def setUp(self) -> None:
        self.artifact_tmp = tempfile.TemporaryDirectory()
        self.artifact_root = Path(self.artifact_tmp.name) / "artifacts"
        self.artifact_root.mkdir()
        self.tenant_key = f"reset-{uuid4().hex}"
        self.other_tenant_key = f"other-{uuid4().hex}"
        self.tenant_id = str(tenant_uuid(self.tenant_key))
        self.other_tenant_id = str(tenant_uuid(self.other_tenant_key))
        import psycopg

        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("insert into tenants (id, name) values (%s, %s), (%s, %s)", (self.tenant_id, "Reset tenant", self.other_tenant_id, "Other tenant"))
        self.selected = self._seed_document(tenant_id=self.tenant_id, suffix=uuid4().hex)
        self.other = self._seed_document(tenant_id=self.other_tenant_id, suffix=uuid4().hex)
        self.missing_source = self._seed_missing_source_document()

    def _seed_missing_source_document(self) -> dict[str, str]:
        import psycopg

        suffix = uuid4().hex
        client_id = f"missing-client-{suffix}"
        taxpayer_id = str(uuid5(NAMESPACE_URL, f"fisora:taxpayer:{self.tenant_id}:{client_id}"))
        document_id = str(uuid4())
        source_id = str(uuid4())
        source_ref = f"missing-source-{suffix}"
        missing_path = str(Path(self.artifact_root).parent / f"does-not-exist-{suffix}.pdf")
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("insert into taxpayers (id, tenant_id, display_name) values (%s, %s, %s)", (taxpayer_id, self.tenant_id, f"Missing {suffix}"))
                cursor.execute(
                    """
                    insert into documents
                        (id, tenant_id, taxpayer_id, source_filename, storage_path,
                         source_ref, document_type, status)
                    values (%s, %s, %s, %s, %s, %s, 'invoice_pdf', 'completed')
                    """,
                    (document_id, self.tenant_id, taxpayer_id, f"{suffix}.pdf", missing_path, source_ref),
                )
                cursor.execute(
                    """
                    insert into source_files
                        (id, tenant_id, taxpayer_id, source_ref, original_filename,
                         storage_path, status, sha256)
                    values (%s, %s, %s, %s, %s, %s, 'missing', %s)
                    """,
                    (source_id, self.tenant_id, taxpayer_id, source_ref, f"{suffix}.pdf", "", hashlib.sha256(suffix.encode()).hexdigest()),
                )
                cursor.execute(
                    """
                    insert into document_sources
                        (id, tenant_id, taxpayer_id, document_id, source_file_id,
                         relationship_type, is_canonical)
                    values (%s, %s, %s, %s, %s, 'canonical', true)
                    """,
                    (str(uuid4()), self.tenant_id, taxpayer_id, document_id, source_id),
                )
                cursor.execute(
                    """
                    insert into workflow_records
                        (id, tenant_id, client_id, record_type, record_key, payload)
                    values (%s, %s, %s, 'uploaded_document', %s, %s::jsonb)
                    """,
                    (
                        str(uuid4()),
                        self.tenant_id,
                        client_id,
                        source_ref,
                        json.dumps({"id": source_ref, "document_ref": source_ref, "storage_path": missing_path, "document_type": "invoice_pdf"}),
                    ),
                )
        return {"document_id": document_id, "client_id": client_id, "source_ref": source_ref}

    def tearDown(self) -> None:
        self.artifact_tmp.cleanup()

    def _counts(self, tenant_id: str) -> dict[str, int]:
        import psycopg

        tables = ("documents", "source_files", "document_sources", "document_ai_artifacts", "processing_jobs", "processing_attempts", "ai_attempts", "invoice_lines", "journal_entries", "journal_entry_lines", "journal_revisions", "journal_revision_lines", "journal_line_allocations", "review_decisions", "learning_rules", "workflow_events", "workflow_records")
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                result = {}
                for table in tables:
                    cursor.execute(f"select count(*) from {table} where tenant_id = %s", (tenant_id,))
                    result[table] = int(cursor.fetchone()[0])
                return result

    def test_dry_run_preserves_rows_files_and_reports_counts(self) -> None:
        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        before = self._counts(self.tenant_id)
        summary = module.reset_gemini_trial_outputs(
            dsn=POSTGRES_DSN,
            tenant_key=self.tenant_key,
            artifact_storage_root=self.artifact_root,
            apply=False,
        )
        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.eligible_document_count, 2)
        self.assertEqual(summary.deleted_counts["document_ai_artifacts"], 1)
        self.assertEqual(summary.deleted_counts["journal_entry_lines"], 1)
        self.assertEqual(summary.deleted_counts["review_decisions"], 2)
        self.assertEqual(summary.deleted_counts["learning_rules"], 2)
        self.assertEqual(summary.deleted_counts["workflow_documents"], 1)
        self.assertEqual(summary.deleted_counts["workflow_processing_jobs"], 1)
        self.assertEqual(summary.deleted_counts["workflow_document_pipeline_events"], 1)
        self.assertEqual(summary.requeued_job_count, 1)
        self.assertEqual(before, self._counts(self.tenant_id))
        self.assertTrue(Path(self.selected["request_path"]).exists())

    def test_apply_preserves_inputs_other_tenant_and_requeues_selected(self) -> None:
        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        other_before = self._counts(self.other_tenant_id)
        summary = module.reset_gemini_trial_outputs(
            dsn=POSTGRES_DSN,
            tenant_key=self.tenant_key,
            artifact_storage_root=self.artifact_root,
            apply=True,
            confirm_tenant_key=self.tenant_key,
        )
        self.assertFalse(summary.dry_run)
        self.assertEqual(summary.requeued_job_count, 1)
        self.assertEqual(self._counts(self.other_tenant_id), other_before)
        selected_counts = self._counts(self.tenant_id)
        self.assertEqual(selected_counts["documents"], 2)
        self.assertEqual(selected_counts["source_files"], 2)
        self.assertEqual(selected_counts["document_sources"], 2)
        for table in ("document_ai_artifacts", "processing_attempts", "ai_attempts", "invoice_lines", "journal_revisions", "review_decisions", "learning_rules", "workflow_events"):
            self.assertEqual(selected_counts[table], 0, table)
        self.assertEqual(selected_counts["processing_jobs"], 1)
        self.assertFalse(Path(self.selected["request_path"]).exists())
        self.assertFalse(Path(self.selected["response_path"]).exists())
        self.assertTrue(Path(self.selected["source_path"]).exists())
        self.assertEqual(Path(self.selected["source_path"]).read_bytes(), self.selected["source_content"].encode())
        import psycopg

        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select status, parse_notes, risk_flags, current_revision_no, invoice_number from documents where id = %s", (self.selected["document_id"],))
                self.assertEqual(cursor.fetchone(), ("uploaded", [], [], 0, None))
                cursor.execute("select id::text, status, attempt_count, intake_category from processing_jobs where document_id = %s", (self.selected["document_id"],))
                self.assertEqual(cursor.fetchone(), (self.selected["job_id"], "queued", 0, "purchase_invoice"))
                cursor.execute("select count(*) from processing_jobs where document_id = %s", (self.missing_source["document_id"],))
                self.assertEqual(cursor.fetchone()[0], 0)
        store = PostgresWorkflowStore(
            POSTGRES_DSN,
            tenant_key=self.tenant_key,
            accounting_store_target="normalized",
        )
        workspace = store.get_workspace(self.selected["client_id"])
        self.assertEqual(len(workspace["uploaded_documents"]), 1)
        self.assertEqual(workspace["documents"], [])
        self.assertEqual(workspace["document_pipeline_events"], [])
        self.assertEqual(len(workspace["processing_jobs"]), 1)
        workflow_job = workspace["processing_jobs"][0]
        self.assertEqual(workflow_job["id"], self.selected["job_id"])
        self.assertEqual(workflow_job["status"], "queued")
        self.assertEqual(workflow_job["attempt_count"], 0)
        self.assertEqual(store._client_id_for_taxpayer_job(self.selected["job_id"]), self.selected["client_id"])

    def test_apply_deletes_journal_collaboration_rows_and_clears_conflicting_job_retry_state(self) -> None:
        import psycopg

        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select current_journal_entry_id, taxpayer_id, source_ref from documents where id = %s",
                    (self.selected["document_id"],),
                )
                journal_entry_id, taxpayer_id, document_ref = cursor.fetchone()
                cursor.execute(
                    "select id from processing_jobs where tenant_id = %s and taxpayer_id = %s and document_ref = %s",
                    (self.tenant_id, taxpayer_id, document_ref),
                )
                conflict_job_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    insert into journal_edit_leases
                        (tenant_id, taxpayer_id, journal_entry_id, owner_actor_id,
                         owner_role, acquired_at, last_user_activity_at, expires_at)
                    values (%s, %s, %s, 'actor', 'accountant', now(), now(), now() + interval '5 minutes')
                    """,
                    (self.tenant_id, taxpayer_id, journal_entry_id),
                )
                cursor.execute(
                    """
                    insert into journal_working_drafts
                        (tenant_id, taxpayer_id, journal_entry_id, base_revision_no,
                         candidate_revision_no, current_export_status, draft_snapshot, saved_by)
                    values (%s, %s, %s, 0, 1, 'review_required', '{}'::jsonb, 'actor')
                    """,
                    (self.tenant_id, taxpayer_id, journal_entry_id),
                )
                conflict_document_id = str(uuid4())
                cursor.execute(
                    """
                    insert into documents
                        (id, tenant_id, taxpayer_id, source_filename, stored_filename,
                         storage_path, source_ref, document_type, status)
                    values (%s, %s, %s, 'conflict.pdf', 'conflict.pdf', '', %s, 'statement', 'uploaded')
                    """,
                    (conflict_document_id, self.tenant_id, taxpayer_id, f"{document_ref}-conflict"),
                )
                outage_episode_id = str(uuid4())
                cursor.execute(
                    """
                    insert into ai_outage_episodes
                        (id, tenant_id, task_kind, status, opened_at, last_failure_at)
                    values (%s, %s, 'accounting', 'open', now(), now())
                    """,
                    (outage_episode_id, self.tenant_id),
                )
                cursor.execute(
                    """
                    update processing_jobs
                    set document_id = %s, status = 'retry_wait',
                        next_attempt_at = now() + interval '1 hour',
                        retry_step = 7, outage_episode_id = %s
                    where tenant_id = %s and taxpayer_id = %s and document_ref = %s
                    """,
                    (
                        conflict_document_id,
                        outage_episode_id,
                        self.tenant_id,
                        taxpayer_id,
                        document_ref,
                    ),
                )

        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        summary = module.reset_gemini_trial_outputs(
            dsn=POSTGRES_DSN,
            tenant_key=self.tenant_key,
            artifact_storage_root=self.artifact_root,
            apply=True,
            confirm_tenant_key=self.tenant_key,
        )
        self.assertFalse(summary.dry_run)

        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select count(*) from journal_edit_leases where tenant_id = %s and journal_entry_id = %s",
                    (self.tenant_id, journal_entry_id),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "select count(*) from journal_working_drafts where tenant_id = %s and journal_entry_id = %s",
                    (self.tenant_id, journal_entry_id),
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    """
                    select status, next_attempt_at, retry_step, outage_episode_id
                    from processing_jobs
                    where tenant_id = %s and taxpayer_id = %s and document_ref = %s
                    """,
                    (self.tenant_id, taxpayer_id, document_ref),
                )
                self.assertEqual(cursor.fetchone(), ("queued", None, 0, None))
                cursor.execute(
                    "select count(*) from processing_attempts where tenant_id = %s and processing_job_id = %s",
                    (self.tenant_id, conflict_job_id),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_escape_path_refuses_before_any_relational_mutation(self) -> None:
        import psycopg

        escape = self._seed_document(tenant_id=self.tenant_id, suffix=uuid4().hex, escape_artifact=True)
        before = self._counts(self.tenant_id)
        module = importlib.import_module("app.persistence.gemini_trial_reset_repository")
        with self.assertRaises(Exception) as context:
            module.reset_gemini_trial_outputs(
                dsn=POSTGRES_DSN,
                tenant_key=self.tenant_key,
                artifact_storage_root=self.artifact_root,
                apply=True,
                confirm_tenant_key=self.tenant_key,
            )
        self.assertIn("artifact", str(context.exception).lower())
        self.assertEqual(before, self._counts(self.tenant_id))
        with psycopg.connect(POSTGRES_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select count(*) from documents where id = %s", (escape["document_id"],))
                self.assertEqual(cursor.fetchone()[0], 1)
