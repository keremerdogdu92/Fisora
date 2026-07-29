# Normalized 50-Invoice Pilot Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reinitialize Fisero onto normalized PostgreSQL with no old operational or protected pilot data, admit exactly 35 purchase and 15 sales invoices through the ordinary accountant upload path, and complete the rule-first, outage, retention, collaborative-review, rule-management, and strict PDF-boundary behavior needed to process that corpus safely.

**Architecture:** Normalized PostgreSQL becomes the only authoritative accounting write/read path. New behavior is split into focused domain policies, PostgreSQL repositories, orchestration services, thin API routes, and small frontend state/view-model modules; large existing modules remain integration points rather than receiving every new responsibility. Ordinary `TEMIZLE` continues preserving protected assets; the one-time clean start uses a separate fingerprinted maintenance operation that explicitly removes both operational and protected pilot data.

**Tech Stack:** Python 3, FastAPI, PostgreSQL 16, Pydantic, existing worker loop, React/Next.js, TypeScript, CommonJS Node tests, `unittest`, `pypdf`, Docker Compose.

## Global Constraints

- Work on the current repository without reverting unrelated dirty-worktree changes.
- This plan authorizes plan-guided local implementation and verification only.
- Do not stage, commit, push, deploy, run a live destructive reset, or upload the real 50 invoices without the separate approval required for that exact action.
- Backup work is outside this plan. Do not add backup services, readiness gates, environment variables, or documentation.
- After clean start, retained application data may contain only:
  - accountant/admin identities and required authentication credentials;
  - the tenant records required by those identities;
  - clients represented in the selected 50-invoice corpus;
  - those clients' real chart plans and access grants;
  - exactly 50 admitted source invoices, target mix 35 purchase and 15 sales;
  - derived canonical evidence, drafts, revisions, decisions, active rules, audit events, and corpus records produced from those 50 invoices.
- Ordinary `TEMIZLE` must continue preserving protected corpus data and protected rules.
- Full pilot reinitialization must be a distinct operation with preview fingerprint, exact confirmation text, actor, counts, and audit receipt.
- UBL/XML remains the canonical primary source. PDF extraction is used when XML is absent.
- Never infer product/service meaning from supplier name alone.
- Missing canonical invoice lines produce `line-missing` or `insufficient-evidence`; they do not create a generic deterministic account.
- Verified rules may own semantic account choice only when current canonical evidence satisfies every recorded precondition.
- Deterministic code owns identity, direction, totals, VAT, balance, line coverage, account usability, authorization, revision safety, and export safety. It does not invent discretionary semantic/account choices.
- Full verified-rule coverage may skip AI and research and may reach automatic approval/export when every mechanical gate passes.
- Partial verified-rule coverage preserves covered decisions but sends uncovered material decisions to AI.
- Provider outage affects only genuinely AI-dependent work.
- Accountant changes, approvals, and rejections are never silently overwritten.
- Retention uses assigned accounting period, not upload time or processing-completion time.
- For accounting period February:
  - preparation becomes due at the end of April;
  - one grouped warning opens on 1 May;
  - the warning remains pending through May even when read;
  - raw source files delete on 31 May;
  - derived accounting, decision, rule, and audit records remain.
- Retention warnings are grouped by client and accounting period, never per document.
- Multi-line, multi-page, mixed-VAT, electricity, and natural-gas invoices do not imply multiple invoices.
- First-phase multi-invoice handling is a strict identity guard, not automatic page splitting.
- Every new PostgreSQL migration is immutable after release and must pass both fresh-install and existing-schema upgrade proof.
- Keep API responses secret-safe and free of raw provider errors and unrestricted filesystem paths.

---

## Settled Product Decisions

1. Old operational data, old protected corpora, old protected rules, and old pilot files are removed before the new corpus is admitted.
2. Accountant/admin identities remain so the office can sign in and perform onboarding/upload/review.
3. Normalized PostgreSQL is active before the first corpus invoice is uploaded.
4. The 50 invoices enter through `POST /phase0/store/document-upload-multipart`, the same authorization/intake path used by the accountant UI.
5. The corpus is created in `draft`, documents are enrolled immediately after ordinary intake, and freeze occurs only after accountant-approved references exist for exactly 35 purchase and 15 sales invoices.
6. A complete verified active rule bypasses AI and research; it does not merely decorate an AI-created result.
7. A provisional outage result blocks unattended export only when an AI-dependent decision remains uncovered. Authorized accountant approval can resolve the document when hard gates pass.
8. Human edit lease duration is five minutes of real user inactivity.
9. Rules are versioned and may be activated, paused, or archived; they are not hard-deleted through the ordinary UI.
10. Automatic multi-invoice page grouping is deferred. Current scope adds only a high-evidence identity-conflict guard.

---

## Current Implementation Truth

- `PostgresWorkflowStore` defaults `FISORA_ACCOUNTING_STORE_TARGET` to `compatibility`.
- `docker-compose.production.yml` forwards `FISORA_STORE_BACKEND` but not `FISORA_ACCOUNTING_STORE_TARGET`.
- `NormalizedAccountingRepository` already owns canonical source/document/journal/revision persistence and `expected_revision` conflict checks.
- Protected corpus migration `005` and `ProtectedCorpusService` already support 35/15 targets, source hash verification, append-only accountant references, and freeze.
- Ordinary PostgreSQL `reset_test_data` intentionally preserves protected corpus tables and protected source root.
- `VerifiedRuleAuthorityV1` and `_resolve_verified_rule_authority` already validate typed semantic authority.
- Real worker `_serializable_simulation` does not pass `verified_rule_authorities` into `simulate_invoice`; it applies legacy learning events after simulation.
- AI failures can produce `ai_retry_required`, but `process_next_job_once` currently saves the result and marks the job `completed`.
- Normalized journal revision conflicts exist; human edit leases, recoverable working drafts, candidate AI revisions, and comparison UI do not.
- `/portal/ajanlar` is read-only; lifecycle APIs do not exist.
- `parse_pdf_invoice` concatenates page text and assumes one `ParsedInvoice`.
- Current retention calculates `expires_at` from upload time and supports manual delete/extend actions.
- Topbar notifications are hardcoded and do not read durable retention/outage state.

---

## Target Runtime Flow

```text
Accountant multipart upload
  -> immutable source commit and intake identity
  -> assigned accounting period validation
  -> normalized processing job
  -> canonical UBL/PDF extraction
  -> strict PDF identity-boundary guard
  -> active verified-rule query
  -> verified-rule authority compilation per canonical line
  -> AI only for uncovered material decisions
  -> deterministic amount/VAT/balance/account/export gates
  -> current or provisional/candidate journal revision
  -> accountant review with edit lease and recoverable working draft
  -> approved journal and optional versioned rule
  -> protected reference outcome
  -> grouped period retention warning
  -> raw-source deletion at third-period month end
```

---

## Target File/Responsibility Map

### New backend domain modules

- `backend/app/domain/period_retention.py`
  - Parses `YYYY-MM`.
  - Computes preparation/warning/deletion dates.
  - Contains no persistence or filesystem code.
- `backend/app/domain/verified_rule_authority.py`
  - Defines persisted rule snapshot contract.
  - Matches active versioned rules against canonical evidence.
  - Compiles `VerifiedRuleAuthorityV1`.
- `backend/app/domain/ai_outage.py`
  - Defines retry schedule and terminal manual-attention decision.
  - Contains no provider calls or persistence.
- `backend/app/domain/pdf_invoice_boundaries.py`
  - Extracts per-page identity clusters.
  - Returns `single_invoice`, `confirmed_multiple`, or `insufficient_identity`.
  - Never uses line count/page count/VAT count as a multi-invoice trigger.

### New backend persistence modules

- `backend/app/persistence/learning_rule_repository.py`
  - Versioned rule lifecycle and active-rule queries.
- `backend/app/persistence/operational_control_repository.py`
  - Retention batches, outage episodes, edit leases, working drafts, candidate revisions, maintenance leases.
  - Uses tenant/taxpayer scoping on every query.

### New backend services

- `backend/app/services/pilot_reinitialization_service.py`
  - Full clean-start preview, fingerprint validation, database deletion, safe file deletion receipt.
- `backend/app/services/retention_service.py`
  - Idempotent preparation, warning opening, raw deletion, listing, read marking.
- `backend/app/services/learning_rule_service.py`
  - Rule list/detail/activate/pause/archive/new-version operations.
- `backend/app/services/notification_service.py`
  - Merges pending retention batches and open outage incidents into one user-facing contract.
- `backend/app/services/review_collaboration_service.py`
  - Edit lease, working draft, forced takeover, candidate revision comparison.

### New backend routes

- `backend/app/api/phase0_routes_maintenance.py`
- `backend/app/api/phase0_routes_learning_rules.py`
- `backend/app/api/phase0_routes_review_collaboration.py`

### New frontend modules

- `frontend/app/features/notifications/use-notifications.ts`
- `frontend/app/features/agents/use-agent-rule-commands.ts`
- `frontend/app/features/review/use-review-edit-lease.ts`
- `frontend/app/portal-notifications.js`
- `frontend/app/portal-notifications.d.ts`
- `frontend/app/portal-agent-rules.js`
- `frontend/app/portal-agent-rules.d.ts`
- `frontend/app/portal-review-collaboration.js`
- `frontend/app/portal-review-collaboration.d.ts`

### New migrations

- `backend/db/migrations/007_period_retention.sql`
- `backend/db/migrations/008_learning_rule_lifecycle.sql`
- `backend/db/migrations/009_journal_edit_collaboration.sql`
- `backend/db/migrations/010_ai_outage_retry.sql`

### New focused tests

- `backend/tests/test_pilot_reinitialization.py`
- `backend/tests/test_pilot_reinitialization_postgres.py`
- `backend/tests/test_period_retention.py`
- `backend/tests/test_learning_rule_lifecycle.py`
- `backend/tests/test_verified_rule_runtime.py`
- `backend/tests/test_review_collaboration.py`
- `backend/tests/test_ai_outage_workflow.py`
- `backend/tests/test_pdf_invoice_boundaries.py`
- `frontend/app/portal-notifications.test.cjs`
- `frontend/app/portal-agent-rules.test.cjs`
- `frontend/app/portal-review-collaboration.test.cjs`

---

## Dependency Order

```text
Task 1 clean-start boundary and normalized config
  -> Task 2 period-retention schema
  -> Task 3 period-retention runtime
  -> Task 4 notification UI

Task 5 rule lifecycle schema/repository
  -> Task 6 rule-first worker authority
  -> Task 11 AI Agents management UI

Task 7 edit collaboration schema/service
  -> Task 8 AI outage schema/policy
  -> Task 9 AI outage worker behavior
  -> Task 10 collaborative review UI

Task 12 strict PDF identity guard

Tasks 1-12
  -> Task 13 50-invoice controlled admission
  -> Task 14 full proof, canonical docs, and release packet
```

---

### Task 1: Add a Separate Full Pilot Reinitialization Boundary and Activate Normalized Configuration

**Files:**
- Create: `backend/app/services/pilot_reinitialization_service.py`
- Create: `backend/app/api/phase0_routes_maintenance.py`
- Create: `backend/tests/test_pilot_reinitialization.py`
- Create: `backend/tests/test_pilot_reinitialization_postgres.py`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/api/phase0_context.py`
- Modify: `backend/app/api/phase0.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/persistence/protected_corpus_repository.py`
- Modify: `docker-compose.production.yml`
- Modify: `deploy/production.env.example`
- Modify: `deploy/scripts/fisora-prod.sh`
- Modify: `backend/tests/test_auth_policy.py`
- Modify: `backend/tests/test_production_restart_policy.py`

**Interfaces:**
- Produces:
  - `PilotReinitializationPreviewPayload`
  - `PilotReinitializationExecutePayload`
  - `PilotReinitializationService.preview()`
  - `PilotReinitializationService.execute(...)`
  - `PostgresWorkflowStore.preview_pilot_reinitialization()`
  - `PostgresWorkflowStore.reinitialize_pilot_data(...)`
- Preserves:
  - tenant;
  - accountant/admin portal users;
  - their auth credentials.
- Deletes:
  - every operational client/document/job/journal/review/export/research/rule record;
  - every protected corpus/item/reference/rule record;
  - ordinary document/export/protected-corpus files.

- [ ] **Step 1: Write failing API contract tests**

  Add exact payload expectations:

  ```python
  preview = client.get(
      "/phase0/store/admin/pilot-reinitialization/preview",
      headers=accountant_headers,
  )
  self.assertEqual(preview.status_code, 200)
  body = preview.json()
  self.assertTrue(body["preview_fingerprint"])
  self.assertIn("operational_document_count", body)
  self.assertIn("protected_corpus_count", body)
  self.assertIn("protected_rule_count", body)
  self.assertIn("preserved_accountant_admin_count", body)

  execute = client.post(
      "/phase0/store/admin/pilot-reinitialization",
      headers=accountant_headers,
      json={
          "confirmation": "YALNIZ_50_FATURA_ILE_BASLAT",
          "preview_fingerprint": body["preview_fingerprint"],
          "delete_files": True,
      },
  )
  self.assertEqual(execute.status_code, 200)
  self.assertEqual(execute.json()["remaining_operational_document_count"], 0)
  self.assertEqual(execute.json()["remaining_protected_corpus_count"], 0)
  ```

  Add failures for:

  ```text
  missing user -> 401
  client_user -> 403
  wrong confirmation -> 400 confirmation_required
  stale fingerprint -> 409 pilot_reinitialization_preview_stale
  compatibility target -> 409 normalized_accounting_required
  overlapping filesystem roots -> 409 unsafe_storage_root_overlap
  ```

- [ ] **Step 2: Run tests and prove the route does not exist**

  Run:

  ```powershell
  python -m unittest backend.tests.test_pilot_reinitialization backend.tests.test_auth_policy
  ```

  Expected: new route/payload assertions fail; existing `TEMIZLE` tests remain green.

- [ ] **Step 3: Add exact Pydantic contracts**

  Add:

  ```python
  class PilotReinitializationExecutePayload(BaseModel):
      confirmation: str
      preview_fingerprint: str = Field(min_length=64, max_length=64)
      delete_files: bool = True
  ```

  Preview is a GET and needs no request body.

- [ ] **Step 4: Implement deterministic preview fingerprint**

  `preview_pilot_reinitialization()` must query tenant-scoped counts and stable IDs. Hash canonical JSON:

  ```python
  fingerprint_payload = {
      "tenant_id": self.tenant_id,
      "operational_ids": sorted(operational_ids),
      "protected_corpus_ids": sorted(protected_corpus_ids),
      "protected_item_ids": sorted(protected_item_ids),
      "protected_rule_ids": sorted(protected_rule_ids),
      "preserved_user_ids": sorted(preserved_user_ids),
  }
  preview_fingerprint = hashlib.sha256(
      json.dumps(
          fingerprint_payload,
          ensure_ascii=True,
          separators=(",", ":"),
          sort_keys=True,
      ).encode("utf-8")
  ).hexdigest()
  ```

  Never return raw IDs, filenames, invoice contents, auth credentials, or filesystem paths in the API preview.

- [ ] **Step 5: Implement database deletion in one PostgreSQL transaction**

  Lock tenant-scoped pilot data before rechecking fingerprint. Delete in FK-safe order. The implementation must explicitly cover normalized and QNB safety tables, protected tables, and compatibility records:

  ```text
  protected_rule_versions
  reference_outcome_versions
  protected_corpus_items
  protected_corpora
  document_safety_holds
  external_status_events
  provider_document_links
  document_identities
  export_batch_items
  export_batches
  review_decisions
  journal_line_allocations
  journal_revision_lines
  journal_revisions
  journal_entry_lines
  journal_entries
  ai_attempts
  processing_attempts
  processing_jobs
  invoice_lines
  document_sources
  source_files
  documents
  counterparties
  learning_rules
  chart_accounts
  chart_account_imports
  portal_user_client_access
  taxpayers
  workflow_events
  workflow_records except preserved portal_user/auth_credential records
  ```

  Keep `tenants` and relational/workflow accountant/admin identities. Remove client-user identities and sessions/tokens.

- [ ] **Step 6: Keep ordinary `TEMIZLE` unchanged**

  Add a regression:

  ```python
  store.reset_test_data(...)
  self.assertEqual(store.get_protected_corpus(corpus_id)["status"], "draft")
  self.assertTrue(protected_source.exists())
  ```

  Full protected deletion must occur only through `reinitialize_pilot_data`.

- [ ] **Step 7: Prevalidate filesystem targets before database mutation**

  Reuse/reset-root safety logic and require three distinct descendants:

  ```python
  ordinary_root = Path(document_storage_path).resolve()
  export_root = Path(export_path).resolve()
  protected_root = Path(protected_storage_path).resolve()
  if len({ordinary_root, export_root, protected_root}) != 3:
      raise PilotReinitializationError("unsafe_storage_root_overlap")
  ```

  Inventory files under these exact roots before the transaction. After database commit, delete only inventoried files. Failed deletions return:

  ```python
  {
      "deleted_file_count": int,
      "file_delete_warning_count": int,
      "file_delete_warning_categories": ["file_missing" | "file_delete_failed"],
  }
  ```

  Do not report a failed file as deleted.

- [ ] **Step 8: Add thin routes and authorization**

  Routes:

  ```text
  GET  /phase0/store/admin/pilot-reinitialization/preview
  POST /phase0/store/admin/pilot-reinitialization
  ```

  Require authenticated `accountant` or `admin`, normalized store target, exact confirmation, and matching preview fingerprint. Record actor, timestamp, pre/post counts, and fingerprint in an operation event.

- [ ] **Step 9: Forward normalized target to every store-using service**

  Add to backend, document worker, and QNB worker:

  ```yaml
  FISORA_ACCOUNTING_STORE_TARGET: ${FISORA_ACCOUNTING_STORE_TARGET:-compatibility}
  ```

  Add to `deploy/production.env.example`:

  ```text
  FISORA_ACCOUNTING_STORE_TARGET=normalized
  ```

  Extend `fisora-prod.sh doctor` output to report only:

  ```text
  FISORA_STORE_BACKEND=postgres
  FISORA_ACCOUNTING_STORE_TARGET=normalized
  ```

  Never print `DATABASE_URL`.

- [ ] **Step 10: Add Compose/config regression tests**

  Assert all three services receive the same target:

  ```python
  self.assertEqual(backend_env["FISORA_ACCOUNTING_STORE_TARGET"], "${FISORA_ACCOUNTING_STORE_TARGET:-compatibility}")
  self.assertEqual(worker_env["FISORA_ACCOUNTING_STORE_TARGET"], "${FISORA_ACCOUNTING_STORE_TARGET:-compatibility}")
  self.assertEqual(qnb_worker_env["FISORA_ACCOUNTING_STORE_TARGET"], "${FISORA_ACCOUNTING_STORE_TARGET:-compatibility}")
  ```

- [ ] **Step 11: Run focused proof**

  ```powershell
  python -m unittest backend.tests.test_pilot_reinitialization backend.tests.test_auth_policy backend.tests.test_production_restart_policy
  ```

  With `FISORA_TEST_POSTGRES_DSN`:

  ```powershell
  python -m unittest backend.tests.test_pilot_reinitialization_postgres
  ```

  Expected: preview fingerprint, stale-preview rejection, normalized-only guard, full deletion, user preservation, file-root safety, and ordinary-reset preservation all pass.

- [ ] **Step 12: Review checkpoint**

  Verify no existing reset route changed semantics. Do not stage or commit.

---

### Task 2: Add Typed Period Retention Schema and Upload Contract

**Files:**
- Create: `backend/db/migrations/007_period_retention.sql`
- Create: `backend/app/domain/period_retention.py`
- Create: `backend/tests/test_period_retention.py`
- Modify: `backend/db/schema.sql`
- Modify: `backend/app/domain/document_uploads.py`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/api/phase0_routes_upload_processing.py`
- Modify: `backend/app/persistence/normalized_accounting_repository.py`
- Modify: `backend/tests/test_document_upload_api.py`
- Modify: `backend/tests/test_db_migrations.py`

**Interfaces:**
- Produces:
  - `AccountingPeriod`
  - `PeriodRetentionSchedule`
  - `parse_accounting_period(value: str) -> date`
  - `period_retention_schedule(period: date) -> PeriodRetentionSchedule`
- Stores:
  - normalized first-day-of-month `accounting_period`;
  - one retention batch per tenant/taxpayer/period;
  - durable read state separate from pending/resolved lifecycle.

- [ ] **Step 1: Write failing pure date tests**

  Add:

  ```python
  schedule = period_retention_schedule(date(2026, 2, 1))
  self.assertEqual(schedule.preparation_on, date(2026, 4, 30))
  self.assertEqual(schedule.warning_on, date(2026, 5, 1))
  self.assertEqual(schedule.delete_on, date(2026, 5, 31))

  self.assertEqual(parse_accounting_period("2026-02"), date(2026, 2, 1))
  with self.assertRaisesRegex(ValueError, "invalid_accounting_period"):
      parse_accounting_period("2026-2")
  ```

  Add leap-year and December rollover:

  ```python
  self.assertEqual(period_retention_schedule(date(2024, 11, 1)).delete_on, date(2025, 2, 28))
  self.assertEqual(period_retention_schedule(date(2024, 12, 1)).delete_on, date(2025, 3, 31))
  ```

- [ ] **Step 2: Run and confirm missing module failure**

  ```powershell
  python -m unittest backend.tests.test_period_retention
  ```

  Expected: import failure for `app.domain.period_retention`.

- [ ] **Step 3: Implement pure month arithmetic**

  Add exact data contract:

  ```python
  @dataclass(frozen=True)
  class PeriodRetentionSchedule:
      accounting_period: date
      preparation_on: date
      warning_on: date
      delete_on: date

  def parse_accounting_period(value: str) -> date:
      if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value.strip()):
          raise ValueError("invalid_accounting_period")
      year, month = (int(part) for part in value.split("-"))
      return date(year, month, 1)
  ```

  Use a tested `add_months` and `month_end`; do not approximate months with 30/60/90-day timedeltas.

- [ ] **Step 4: Add migration 007**

  Migration must include:

  ```sql
  alter table documents add column accounting_period date;
  alter table source_files add column accounting_period date;

  alter table documents add constraint ck_documents_accounting_period_month_start
      check (accounting_period is null or accounting_period = date_trunc('month', accounting_period)::date);
  alter table source_files add constraint ck_source_files_accounting_period_month_start
      check (accounting_period is null or accounting_period = date_trunc('month', accounting_period)::date);

  create table retention_batches (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      taxpayer_id uuid not null references taxpayers(id),
      accounting_period date not null,
      preparation_on date not null,
      warning_on date not null,
      delete_on date not null,
      status text not null default 'scheduled'
          check (status in ('scheduled', 'warning_open', 'deleting', 'resolved')),
      opened_at timestamptz,
      read_at timestamptz,
      resolved_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique (tenant_id, taxpayer_id, accounting_period),
      check (accounting_period = date_trunc('month', accounting_period)::date),
      check (preparation_on < warning_on and warning_on <= delete_on)
  );

  create table retention_batch_sources (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      taxpayer_id uuid not null references taxpayers(id),
      retention_batch_id uuid not null references retention_batches(id) on delete cascade,
      source_file_id uuid not null references source_files(id),
      created_at timestamptz not null default now(),
      unique (retention_batch_id, source_file_id)
  );

  create table retention_scheduler_state (
      tenant_id uuid primary key references tenants(id),
      next_run_at timestamptz not null default now(),
      claimed_by text,
      claim_expires_at timestamptz,
      updated_at timestamptz not null default now()
  );

  create index idx_retention_batches_due
      on retention_batches(tenant_id, status, warning_on, delete_on);
  ```

- [ ] **Step 5: Require period for invoice uploads**

  At API/service boundary:

  ```python
  if document_type in {"invoice", "einvoice_xml"}:
      accounting_period = parse_accounting_period(period)
  else:
      accounting_period = parse_accounting_period(period) if period.strip() else None
  ```

  Return HTTP 400:

  ```json
  {"allowed": false, "reason": "invalid_accounting_period", "expected": "YYYY-MM"}
  ```

  Do not infer period from upload date or invoice date.

- [ ] **Step 6: Persist accounting period transactionally**

  Update normalized source/document insert statements so the same parsed period reaches `documents.accounting_period` and `source_files.accounting_period`.

  Preserve API compatibility field:

  ```python
  document_payload["period"] = accounting_period.strftime("%Y-%m")
  ```

- [ ] **Step 7: Add upload regressions**

  Cover:

  ```text
  invoice without period -> 400
  malformed period -> 400
  2026-02 invoice uploaded in May -> stored accounting_period 2026-02-01
  bank statement with empty period -> accepted
  delegated accountant upload -> actor metadata unchanged
  duplicate upload -> period does not create a second authoritative source
  ```

- [ ] **Step 8: Add migration contract tests**

  Assert migration 007 contains both month-start checks, both retention tables, scheduler state, unique tenant/taxpayer/period, and due index.

- [ ] **Step 9: Run focused tests**

  ```powershell
  python -m unittest backend.tests.test_period_retention backend.tests.test_document_upload_api backend.tests.test_db_migrations
  ```

  Expected: all period parsing, API, normalized persistence, and migration assertions pass.

- [ ] **Step 10: Review checkpoint**

  Confirm no code computes a retention deadline from `created_at` for invoices in normalized mode. Do not stage or commit.

---

### Task 3: Implement Idempotent Period Retention Runtime and Raw-Only Deletion

**Files:**
- Create: `backend/app/persistence/operational_control_repository.py`
- Create: `backend/app/services/retention_service.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/api/phase0_context.py`
- Modify: `backend/app/api/phase0_routes_upload_processing.py`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/worker.py`
- Modify: `backend/tests/test_period_retention.py`
- Modify: `backend/tests/test_normalized_invoice_journal_postgres.py`
- Modify: `backend/tests/test_workflow_store.py`

**Interfaces:**
- Produces:
  - `RetentionService.run_due(now: datetime, worker_id: str) -> dict`
  - `RetentionService.list_pending(user_id: str) -> dict`
  - `RetentionService.mark_read(batch_id: str, user_id: str) -> dict`
  - `OperationalControlRepository.claim_retention_tick(...)`
  - `OperationalControlRepository.prepare_retention_batches(...)`
  - `OperationalControlRepository.open_due_retention_warnings(...)`
  - `OperationalControlRepository.claim_due_retention_deletions(...)`
  - `OperationalControlRepository.resolve_retention_batch(...)`

- [ ] **Step 1: Add failing repository/service tests**

  Seed three February source files for one client and assert:

  ```python
  april = service.run_due(now=datetime(2026, 4, 30, 12, tzinfo=UTC), worker_id="w1")
  self.assertEqual(april["prepared_batch_count"], 1)
  self.assertEqual(april["opened_warning_count"], 0)

  may_first = service.run_due(now=datetime(2026, 5, 1, 0, 5, tzinfo=UTC), worker_id="w1")
  self.assertEqual(may_first["opened_warning_count"], 1)
  self.assertEqual(service.list_pending(user_id="accountant")["items"][0]["document_count"], 3)

  service.mark_read(batch_id=batch_id, user_id="accountant")
  self.assertEqual(service.list_pending(user_id="accountant")["items"][0]["status"], "warning_open")
  self.assertTrue(service.list_pending(user_id="accountant")["items"][0]["read_at"])
  ```

  At 31 May:

  ```python
  deleted = service.run_due(now=datetime(2026, 5, 31, 23, 59, tzinfo=UTC), worker_id="w1")
  self.assertEqual(deleted["deleted_source_count"], 3)
  self.assertEqual(deleted["resolved_batch_count"], 1)
  self.assertTrue(approved_journal_still_exists())
  self.assertTrue(review_decision_still_exists())
  self.assertTrue(active_rule_still_exists())
  ```

- [ ] **Step 2: Add concurrency and idempotency failures**

  Run two workers against the same due batch. Assert one claims it and repeated runs produce no second deletion/audit event:

  ```python
  self.assertEqual(sum(item["deleted_source_count"] for item in results), 3)
  self.assertEqual(count_event("raw_sources_deleted_for_period"), 1)
  ```

- [ ] **Step 3: Implement retention scheduler claim**

  Use one tenant-scoped row and `FOR UPDATE SKIP LOCKED`. Claim only when `next_run_at <= now()` or lease expired. Renew:

  ```sql
  update retention_scheduler_state
  set claimed_by = %s,
      claim_expires_at = %s,
      next_run_at = %s,
      updated_at = now()
  where tenant_id = %s;
  ```

  Default next run: one hour. The operation remains date-idempotent, so delayed runs safely catch up.

- [ ] **Step 4: Prepare grouped batches**

  At/after `preparation_on`, insert one batch per tenant/taxpayer/accounting period and map every undeleted source file for that period:

  ```sql
  insert into retention_batches (...)
  values (...)
  on conflict (tenant_id, taxpayer_id, accounting_period) do nothing;
  ```

  A late source upload with the same accounting period must attach to the existing unresolved batch before deletion.

- [ ] **Step 5: Open warnings without resolving on read**

  Opening changes `scheduled -> warning_open`. Reading only sets `read_at`; status stays `warning_open`.

- [ ] **Step 6: Delete raw source bytes, not accounting truth**

  In one database transaction:

  1. lock due batch and mapped sources;
  2. set `source_files.status='deleted'`, `deleted_at=now()`, clear preview availability;
  3. set source-related `documents.storage_status='deleted'`, `deleted_at=now()` without deleting the document row;
  4. append `raw_sources_deleted_for_period` workflow event;
  5. set batch `resolved`.

  After commit, delete only validated mapped file paths. Preserve:

  ```text
  documents row
  canonical invoice fields
  invoice_lines
  journal entries/revisions/lines/allocations
  review decisions
  learning rules
  protected reference outcomes
  workflow/audit events
  ```

- [ ] **Step 7: Deprecate manual extend in normalized mode**

  Existing action endpoint remains backward compatible for compatibility tests, but normalized mode rejects `extend_90_days`:

  ```json
  {"allowed": false, "reason": "period_retention_extension_not_supported"}
  ```

  Manual early raw deletion may remain only if it targets an entire client+period batch and records actor/audit; per-document retention deletion is not exposed in the new UI.

- [ ] **Step 8: Wire worker tick**

  Add:

  ```python
  def run_retention_once() -> dict[str, int]:
      store = build_workflow_store()
      if not getattr(store, "normalized_accounting_enabled", False):
          return {"claimed": 0, "prepared_batch_count": 0, "deleted_source_count": 0}
      return get_retention_service(store).run_due(
          now=datetime.now(UTC),
          worker_id=WORKER_ID,
      )
  ```

  Merge summary without allowing retention failure to stop document processing. Record one operational error event with sanitized category.

- [ ] **Step 9: Update retention API contract**

  Routes:

  ```text
  GET  /phase0/store/document-retention/pending
  POST /phase0/store/document-retention/{batch_id}/read
  POST /phase0/store/document-retention/run
  ```

  Pending response:

  ```json
  {
    "items": [{
      "batch_id": "uuid",
      "client_id": "firma-1",
      "client_name": "Firma",
      "accounting_period": "2026-02",
      "warning_on": "2026-05-01",
      "delete_on": "2026-05-31",
      "document_count": 12,
      "status": "warning_open",
      "read_at": ""
    }]
  }
  ```

- [ ] **Step 10: Run focused proof**

  ```powershell
  python -m unittest backend.tests.test_period_retention backend.tests.test_workflow_store
  ```

  With PostgreSQL:

  ```powershell
  python -m unittest backend.tests.test_normalized_invoice_journal_postgres
  ```

  Expected: date boundary, late upload, grouping, read-vs-pending, idempotency, two-worker claim, raw-only deletion, and retained accounting evidence pass.

- [ ] **Step 11: Review checkpoint**

  Inspect one February fixture before/after 31 May. Confirm source preview fails with a specific raw-deleted state while journal explanation still renders. Do not stage or commit.

---

### Task 4: Replace Hardcoded Notifications With Durable Retention/Outage Notifications

**Files:**
- Create: `backend/app/services/notification_service.py`
- Create: `frontend/app/features/notifications/use-notifications.ts`
- Create: `frontend/app/features/notifications/index.ts`
- Create: `frontend/app/portal-notifications.js`
- Create: `frontend/app/portal-notifications.d.ts`
- Create: `frontend/app/portal-notifications.test.cjs`
- Modify: `backend/app/api/phase0_routes_operations.py`
- Modify: `backend/app/api/phase0_context.py`
- Modify: `frontend/app/portal-shell-components.tsx`
- Modify: `frontend/app/portal-app.tsx`
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/upload-api.js`
- Modify: `frontend/app/styles.css`

**Interfaces:**
- Produces:
  - `GET /phase0/store/notifications`
  - `POST /phase0/store/notifications/{notification_id}/read`
  - `PortalNotification`
  - `buildNotificationViewModel(raw)`
- Consumes retention batches now; consumes outage episodes after Task 9.

- [ ] **Step 1: Write failing pure frontend tests**

  Assert:

  ```javascript
  const view = buildNotificationViewModel({
    notification_id: "retention:batch-1",
    kind: "retention",
    status: "pending",
    read_at: "2026-05-02T09:00:00Z",
    accounting_period: "2026-02",
    delete_on: "2026-05-31",
    document_count: 12,
  });
  assert.equal(view.badgeLabel, "12 belge");
  assert.equal(view.pending, true);
  assert.equal(view.read, true);
  assert.match(view.title, /Şubat 2026/);
  ```

  Reading must not remove the item:

  ```javascript
  assert.equal(pendingNotificationCount([view]), 1);
  ```

- [ ] **Step 2: Implement backend notification aggregation**

  Contract:

  ```python
  {
      "notification_id": f"retention:{batch_id}",
      "kind": "retention",
      "severity": "warning",
      "status": "pending",
      "title": "Şubat 2026 belgeleri ay sonunda silinecek",
      "message": "12 kaynak belge 31 Mayıs 2026 tarihinde silinecek.",
      "client_id": client_id,
      "accounting_period": "2026-02",
      "document_count": 12,
      "read_at": "",
      "created_at": opened_at,
  }
  ```

  Deduplicate by stable `notification_id`. Do not generate one item per document.

- [ ] **Step 3: Add authorized list/read routes**

  Accountant/admin may see office-scoped notifications; client users see only allowed clients. Read is actor-specific if the current auth model can store per-user read state; if not, store `read_by` append-only metadata instead of globally hiding the notification.

- [ ] **Step 4: Replace hardcoded topbar count**

  Remove `Bildirimler <strong>3</strong>`. Render:

  ```tsx
  <button className="topbar-action" onClick={() => setActivePanel("notifications")} type="button">
    Bildirimler <strong>{pendingCount}</strong>
  </button>
  ```

  The popover lists retention items and later outage incidents. Read items remain visible while `pending`.

- [ ] **Step 5: Add retention actions**

  Each retention item exposes:

  ```text
  Dönemi aç
  Okundu işaretle
  ```

  No `90 gün uzat`, no per-document delete.

- [ ] **Step 6: Run tests and build**

  ```powershell
  node --test frontend/app/portal-notifications.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  ```

  Expected: dynamic count, pending-after-read, grouped copy, and type checks pass.

- [ ] **Step 7: Review checkpoint**

  Verify notification popover remains sparse at 0, 1, and many client-period items. Do not stage or commit.

---

### Task 5: Add Versioned Learning-Rule Lifecycle and Authority Compiler

**Files:**
- Create: `backend/db/migrations/008_learning_rule_lifecycle.sql`
- Create: `backend/app/domain/verified_rule_authority.py`
- Create: `backend/app/persistence/learning_rule_repository.py`
- Create: `backend/app/services/learning_rule_service.py`
- Create: `backend/tests/test_learning_rule_lifecycle.py`
- Modify: `backend/db/schema.sql`
- Modify: `backend/app/domain/invoice_ai_gate.py`
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/persistence/protected_corpus_repository.py`
- Modify: `backend/tests/test_db_migrations.py`
- Modify: `backend/tests/test_phase0_services.py`

**Interfaces:**
- Produces:
  - `VerifiedRuleRecordV1`
  - `compile_verified_rule_authorities(...)`
  - `LearningRuleRepository.create_version(...)`
  - `LearningRuleRepository.list_active(...)`
  - `LearningRuleService.activate/pause/archive/create_version`
- Each persisted rule version has immutable conditions and binding snapshot.

- [ ] **Step 1: Write failing rule lifecycle tests**

  Cover:

  ```python
  created = service.create_version(
      rule_key="client:firma-1:supplier:1234567890:dogalgaz",
      expected_version=0,
      snapshot=fixture,
      actor="accountant",
  )
  self.assertEqual(created["version"], 1)
  self.assertEqual(created["status"], "draft")

  active = service.activate(
      rule_key=created["rule_key"],
      expected_version=1,
      actor="accountant",
  )
  self.assertEqual(active["status"], "active")

  with self.assertRaisesRegex(LearningRuleConflict, "learning_rule_version_conflict"):
      service.pause(rule_key=created["rule_key"], expected_version=0, actor="accountant")
  ```

  Assert archive does not delete old versions.

- [ ] **Step 2: Add authority match tests**

  Full VKN-scoped rule:

  ```python
  authorities = compile_verified_rule_authorities(
      rules=(rule,),
      client_id="firma-1",
      direction="purchase",
      invoice_mode="ordinary",
      counterparty_tax_id="1234567890",
      canonical_lines=(line1, line2),
      account_selection=selection,
  )
  self.assertEqual({item.canonical_line_id for item in authorities}, {line1.id, line2.id})
  self.assertTrue(all(item.account_code == "770.03.001" for item in authorities))
  ```

  Reject:

  ```text
  wrong client
  wrong VKN
  wrong direction
  wrong invoice mode
  inactive/archived rule
  missing confirmation provenance
  inactive/non-detail/missing chart account
  phrase mismatch for phrase-scoped rule
  incomplete canonical lines
  conflicting same-priority rules
  ```

- [ ] **Step 3: Add migration 008**

  Extend `learning_rules`:

  ```sql
  alter table learning_rules add column rule_key text;
  alter table learning_rules add column version integer not null default 1;
  alter table learning_rules add column status text not null default 'draft'
      check (status in ('draft', 'active', 'paused', 'archived'));
  alter table learning_rules add column schema_version text not null default 'v1';
  alter table learning_rules add column scope_snapshot jsonb not null default '{}';
  alter table learning_rules add column rule_snapshot jsonb not null default '{}';
  alter table learning_rules add column activation_event_id uuid;
  alter table learning_rules add column confirmed_by text;
  alter table learning_rules add column confirmed_at timestamptz;
  alter table learning_rules add column supersedes_rule_id uuid references learning_rules(id);

  create unique index uq_learning_rules_key_version
      on learning_rules(tenant_id, rule_key, version)
      where rule_key is not null;
  create index idx_learning_rules_active_scope
      on learning_rules(tenant_id, taxpayer_id, status, scope, rule_key)
      where status = 'active';
  ```

  Existing rows remain non-authoritative until explicitly revalidated; default `draft` prevents accidental activation.

- [ ] **Step 4: Define immutable V1 snapshot**

  Use:

  ```python
  @dataclass(frozen=True)
  class VerifiedRuleRecordV1:
      rule_id: str
      rule_key: str
      version: int
      status: Literal["active"]
      client_id: str
      scope: Literal["client_counterparty", "client_phrase", "office_semantic"]
      direction: Literal["purchase", "sales"]
      invoice_mode: Literal["ordinary", "return"]
      counterparty_tax_id: str
      line_match_mode: Literal["all_lines", "normalized_terms_all"]
      normalized_terms: tuple[str, ...]
      semantic_role: str
      account_code: str
      activation_event_id: str
      source_review_decision_id: str
      confirmed_actor_id: str
  ```

  `office_semantic` may preserve meaning across clients but cannot carry another client's account code. It never produces `VerifiedRuleAuthorityV1` with a client-bound account unless the current client has its own validated binding.

- [ ] **Step 5: Implement strict compiler**

  Compiler must:

  1. filter by active status and current client;
  2. match canonical counterparty VKN when required;
  3. match every rule condition;
  4. verify selected code exists in correct direction/semantic-role candidate family;
  5. verify active detail-account metadata;
  6. emit one authority per matched canonical line;
  7. return conflict metadata instead of choosing between equal-priority rules.

- [ ] **Step 6: Persist rules only from explicit accountant confirmation**

  `ReviewService.store_review_decision` creates a rule version only when:

  ```python
  payload.decision.learning_confirmation == "save_rule"
  and saved_learning_event["source"] == "accountant_confirmed"
  and payload.decision.confirmed_rule_interpretation
  ```

  Store exact source review ID, actor, client/chart binding, direction, invoice mode, matching conditions, and account code. Do not derive an active rule from free text alone.

- [ ] **Step 7: Keep protected reference linkage**

  When the source document is enrolled, append a protected rule snapshot linked to the exact authoritative reference version. Ordinary rule lifecycle and protected history share `rule_key`/version but remain separate storage boundaries.

- [ ] **Step 8: Run focused tests**

  ```powershell
  python -m unittest backend.tests.test_learning_rule_lifecycle backend.tests.test_phase0_services backend.tests.test_db_migrations
  ```

  Expected: lifecycle, version conflicts, strict matching, chart-account validation, confirmation provenance, and protected linkage pass.

- [ ] **Step 9: Review checkpoint**

  Inspect one VKN-wide client rule and one phrase-scoped rule. Confirm neither relies on supplier name inference. Do not stage or commit.

---

### Task 6: Wire Verified Rule Authority Before AI and Preserve Export Semantics

**Files:**
- Create: `backend/tests/test_verified_rule_runtime.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/domain/learning_rules.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/persistence/normalized_accounting_repository.py`
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_normalized_invoice_journal.py`
- Modify: `backend/tests/test_normalized_invoice_journal_postgres.py`

**Interfaces:**
- Consumes `LearningRuleRepository.list_active(...)` and Task 5 compiler.
- Produces rule-first worker behavior with zero provider/research calls for complete coverage.

- [ ] **Step 1: Add end-to-end worker test for zero provider calls**

  Seed:

  - canonical two-line purchase invoice;
  - exact client/counterparty VKN;
  - active VKN-wide verified rule;
  - active detail account in current chart;
  - fake AI and research providers that fail if called.

  Assert:

  ```python
  self.assertEqual(ai_provider.requests, [])
  self.assertEqual(research_provider.requests, [])
  self.assertEqual(result["ai_gate_reason"], "verified_rule_binding")
  self.assertEqual(
      {item["decision_source"] for item in result["line_decisions"]},
      {"verified_rule"},
  )
  self.assertEqual(result["export_status"], "export_ready")
  self.assertEqual(result["automation_label"], "Dogrulanmis kuralla otomatik")
  ```

- [ ] **Step 2: Add partial-coverage test**

  Rule covers line 1; AI covers line 2. Assert line 1 remains rule-owned and AI request contains only uncovered canonical line ID:

  ```python
  self.assertEqual(ai_provider.requests[0].canonical_line_ids, (line2.id,))
  self.assertEqual(result["line_decisions"][0]["decision_source"], "verified_rule")
  self.assertEqual(result["line_decisions"][1]["decision_source"], "accepted_ai")
  ```

- [ ] **Step 3: Add conflict and invalid-binding tests**

  Equal-priority conflicting rules must not pick an account:

  ```python
  self.assertIn("verified_rule_conflict", result["review_reason_codes"])
  self.assertNotEqual(result["export_status"], "export_ready")
  ```

  Invalid/inactive chart account must route uncovered decision to AI, not generic fallback.

- [ ] **Step 4: Load rules before simulation**

  Extend `_serializable_simulation`:

  ```python
  def _serializable_simulation(
      invoice: ParsedInvoice,
      workspace: dict[str, Any],
      *,
      verified_rule_authorities: tuple[VerifiedRuleAuthorityV1, ...] = (),
      product_classifier: ProductClassifier | None = None,
      intended_direction: str | None = None,
      classification_override: ProductClassification | None = None,
  ) -> dict[str, Any]:
  ```

  `process_next_job_once` loads active rules, compiles authorities after canonical parsing and account-selection assembly, then passes them into `simulate_invoice`.

- [ ] **Step 5: Stop legacy post-AI rule mutation**

  `apply_learning_rules` may add non-authoritative audit/display context for legacy unconfirmed events. It must not overwrite selected account, draft lines, or export status after `simulate_invoice`.

  Add regression:

  ```python
  self.assertEqual(post_learning.draft_lines, authoritative_result.draft_lines)
  self.assertEqual(post_learning.export_status, authoritative_result.export_status)
  ```

- [ ] **Step 6: Keep export independent from AI usage**

  Export readiness depends on:

  ```text
  complete semantic authority (verified rule or accepted AI)
  canonical line coverage
  current chart-account usability
  direction
  VAT/totals
  balanced journal
  no hard review blocker
  authorized automation policy
  ```

  It must not require `ai_classification_used=True`.

- [ ] **Step 7: Persist authority provenance**

  Each line decision stores:

  ```python
  {
      "decision_source": "verified_rule",
      "authority_source_id": f"{rule_key}:{version}",
      "source_review_decision_id": source_review_decision_id,
      "confirmed_actor_id": confirmed_actor_id,
  }
  ```

  Persist exact applied rule-set digest with the processing attempt.

- [ ] **Step 8: Run focused accounting proof**

  ```powershell
  python -m unittest backend.tests.test_verified_rule_runtime backend.tests.test_phase0_domain backend.tests.test_normalized_invoice_journal
  ```

  With PostgreSQL:

  ```powershell
  python -m unittest backend.tests.test_normalized_invoice_journal_postgres
  ```

  Expected: zero-call, partial coverage, conflict, current-chart validation, rule provenance, balance, revision, and export tests pass.

- [ ] **Step 9: Review checkpoint**

  Inspect canonical source -> rule conditions -> line authorities -> journal allocations -> export gate. Do not stage or commit.

---

### Task 7: Add Human Edit Leases, Working Drafts, and Candidate Revision Schema

**Files:**
- Create: `backend/db/migrations/009_journal_edit_collaboration.sql`
- Create: `backend/app/services/review_collaboration_service.py`
- Create: `backend/tests/test_review_collaboration.py`
- Modify: `backend/db/schema.sql`
- Modify: `backend/app/persistence/operational_control_repository.py`
- Modify: `backend/app/persistence/normalized_accounting_repository.py`
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/tests/test_db_migrations.py`
- Modify: `backend/tests/test_normalized_invoice_journal_postgres.py`

**Interfaces:**
- Produces:
  - `EditLeaseView`
  - `WorkingDraftView`
  - `ReviewCollaborationService.acquire/renew/release/takeover/save_working_draft`
  - candidate journal revision role.

- [ ] **Step 1: Add failing lease tests**

  Assert:

  ```python
  first = service.acquire(
      client_id="firma-1",
      document_ref="doc-1",
      actor="accountant-a",
      expected_revision=1,
      now=at("2026-07-27T10:00:00Z"),
  )
  self.assertEqual(first["status"], "owned")

  second = service.acquire(
      client_id="firma-1",
      document_ref="doc-1",
      actor="accountant-b",
      expected_revision=1,
      now=at("2026-07-27T10:01:00Z"),
  )
  self.assertEqual(second["status"], "blocked")
  self.assertEqual(second["owner_display_name"], "Accountant A")
  ```

  At five minutes inactivity, another actor may acquire. Background heartbeat without recent user activity must not renew.

- [ ] **Step 2: Add working-draft and stale-revision tests**

  ```python
  saved = service.save_working_draft(
      lease_id=first["lease_id"],
      actor="accountant-a",
      expected_revision=1,
      draft_snapshot={"draft_lines": fixture_lines},
  )
  self.assertEqual(saved["base_revision_no"], 1)

  with self.assertRaisesRegex(NormalizedRevisionConflict, "journal_revision_conflict"):
      service.save_working_draft(
          lease_id=first["lease_id"],
          actor="accountant-a",
          expected_revision=0,
          draft_snapshot={"draft_lines": fixture_lines},
      )
  ```

- [ ] **Step 3: Add migration 009**

  ```sql
  create table journal_edit_leases (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      taxpayer_id uuid not null references taxpayers(id),
      document_id uuid not null references documents(id),
      actor_user_key text not null,
      base_revision_no integer not null,
      acquired_at timestamptz not null,
      last_user_activity_at timestamptz not null,
      expires_at timestamptz not null,
      released_at timestamptz,
      takeover_reason text,
      created_at timestamptz not null default now()
  );

  create unique index uq_journal_edit_leases_active_document
      on journal_edit_leases(tenant_id, document_id)
      where released_at is null;

  create table journal_working_drafts (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      taxpayer_id uuid not null references taxpayers(id),
      document_id uuid not null references documents(id),
      edit_lease_id uuid not null references journal_edit_leases(id),
      actor_user_key text not null,
      base_revision_no integer not null,
      draft_snapshot jsonb not null,
      updated_at timestamptz not null default now(),
      unique (tenant_id, document_id, actor_user_key)
  );

  alter table journal_revisions add column revision_role text not null default 'current'
      check (revision_role in ('current', 'candidate'));
  alter table journal_revisions add column candidate_reason text;
  alter table journal_revisions add column candidate_source_attempt_id uuid references processing_attempts(id);
  ```

- [ ] **Step 4: Implement atomic lease acquisition**

  Lock document/current journal row. Expire old lease only when `last_user_activity_at + interval '5 minutes' <= now()`. Do not renew from a heartbeat unless request includes `user_activity_at` newer than stored value and not in the future.

- [ ] **Step 5: Require active lease for human accounting mutations**

  Extend stored review payload later with `edit_lease_id`. Until frontend Task 10 lands, keep backward compatibility for tests through an explicit service flag; normalized production route must require the lease when draft lines or accounting fields changed.

- [ ] **Step 6: Add forced takeover**

  Only accountant/admin; require non-empty reason. Release old lease, create new lease, append audit event:

  ```python
  {
      "event_type": "journal_edit_lease_taken_over",
      "prior_actor": prior_actor,
      "new_actor": actor,
      "reason": reason,
  }
  ```

- [ ] **Step 7: Add candidate revision persistence**

  Extend normalized journal persistence with explicit:

  ```python
  persist_canonical_journal(..., revision_role: Literal["current", "candidate"])
  ```

  Candidate revisions:

  - are append-only;
  - do not advance `documents.current_revision_no`;
  - do not change export status;
  - are never read by export;
  - are visible for comparison.

- [ ] **Step 8: Run focused tests**

  ```powershell
  python -m unittest backend.tests.test_review_collaboration backend.tests.test_db_migrations
  ```

  With PostgreSQL:

  ```powershell
  python -m unittest backend.tests.test_normalized_invoice_journal_postgres
  ```

  Expected: acquire/block/expiry/activity renewal/takeover/working-draft/conflict/candidate-current separation pass.

- [ ] **Step 9: Review checkpoint**

  Verify opening a document creates no lease; first meaningful edit does. Do not stage or commit.

---

### Task 8: Add Durable AI Outage Episodes and Retry Policy

**Files:**
- Create: `backend/db/migrations/010_ai_outage_retry.sql`
- Create: `backend/app/domain/ai_outage.py`
- Create: `backend/tests/test_ai_outage_workflow.py`
- Modify: `backend/db/schema.sql`
- Modify: `backend/app/persistence/operational_control_repository.py`
- Modify: `backend/app/persistence/normalized_accounting_repository.py`
- Modify: `backend/tests/test_db_migrations.py`

**Interfaces:**
- Produces:
  - `AiRetryDecision`
  - `next_ai_retry(...)`
  - outage episode CRUD/claim methods.

- [ ] **Step 1: Add retry-policy tests**

  Exact schedule:

  ```python
  expected = [
      timedelta(minutes=2),
      timedelta(minutes=5),
      timedelta(minutes=10),
      timedelta(minutes=15),
      timedelta(minutes=30),
      timedelta(hours=2),
      timedelta(hours=6),
  ]
  self.assertEqual([next_ai_retry(step=i, opened_at=opened, now=opened).delay for i in range(7)], expected)
  ```

  After the initial 6-hour step, use six-hour cadence until 24 hours, then:

  ```python
  self.assertEqual(decision.status, "manual_attention")
  self.assertIsNone(decision.next_attempt_at)
  ```

  Jitter is deterministic from document ID and bounded so tests remain stable.

- [ ] **Step 2: Add migration 010**

  ```sql
  create table ai_outage_episodes (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      task_kind text not null,
      status text not null
          check (status in ('open', 'recovered')),
      opened_at timestamptz not null,
      last_failure_at timestamptz not null,
      recovered_at timestamptz,
      failed_provider_categories jsonb not null default '[]',
      affected_document_count integer not null default 0,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
  );

  alter table processing_jobs add column next_attempt_at timestamptz;
  alter table processing_jobs add column retry_step integer not null default 0;
  alter table processing_jobs add column outage_episode_id uuid references ai_outage_episodes(id);

  create index idx_processing_jobs_due_retry
      on processing_jobs(tenant_id, status, next_attempt_at)
      where status = 'retry_wait';

  create unique index uq_ai_outage_episode_open_task
      on ai_outage_episodes(tenant_id, task_kind)
      where status = 'open';
  ```

- [ ] **Step 3: Extend job claim**

  Claim condition:

  ```sql
  status = 'queued'
  or (status = 'retry_wait' and next_attempt_at <= now())
  or (status = 'processing' and claim_expires_at < now())
  ```

  Keep `FOR UPDATE SKIP LOCKED`.

- [ ] **Step 4: Implement episode deduplication**

  First all-provider failure opens one task-scoped episode. Further documents join the same open episode and increment affected count transactionally. Do not create one incident per provider or per document.

- [ ] **Step 5: Sanitize provider failure evidence**

  Store:

  ```python
  {
      "provider": provider_name,
      "category": "timeout" | "rate_limited" | "unavailable" | "configuration_error",
      "attempted_at": iso,
  }
  ```

  Do not store raw response bodies, credentials, auth headers, or full exception strings.

- [ ] **Step 6: Run tests**

  ```powershell
  python -m unittest backend.tests.test_ai_outage_workflow backend.tests.test_db_migrations
  ```

  Expected: schedule, 24-hour terminal state, due claim, episode deduplication, and sanitization pass.

- [ ] **Step 7: Review checkpoint**

  Confirm job retry and outage incident are separate concepts: one incident may own many jobs. Do not stage or commit.

---

### Task 9: Implement Rule-Aware AI Outage Worker Behavior and No-Overwrite Recovery

**Files:**
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/services/notification_service.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/worker.py`
- Modify: `backend/tests/test_ai_outage_workflow.py`
- Modify: `backend/tests/test_verified_rule_runtime.py`
- Modify: `backend/tests/test_workflow_store.py`
- Modify: `frontend/app/portal-normalization.js`
- Modify: `frontend/app/portal-normalization.d.ts`
- Modify: `frontend/app/portal-normalization.test.cjs`

**Interfaces:**
- Consumes Task 6 rule coverage, Task 7 edit/candidate primitives, Task 8 retry policy.
- Produces real provisional/retry/recovery states and outage notifications.

- [ ] **Step 1: Add failing full-coverage outage test**

  Configure every provider to fail but provide complete verified rule coverage. Assert:

  ```python
  self.assertEqual(result["ai_resolution_status"], "resolved")
  self.assertEqual(result["automation_label"], "Dogrulanmis kuralla otomatik")
  self.assertEqual(job["status"], "completed")
  self.assertEqual(count_open_outage_episodes(), 0)
  ```

- [ ] **Step 2: Add failing uncovered outage test**

  Assert:

  ```python
  self.assertEqual(result["status"], "review_required")
  self.assertEqual(result["outage_state"], "ai_unavailable_provisional")
  self.assertEqual(result["draft_origin"], "deterministic_outage_fallback")
  self.assertEqual(result["status_label"], "Ajan olmadan hazirlanmis")
  self.assertEqual(job["status"], "retry_wait")
  self.assertTrue(job["next_attempt_at"])
  self.assertNotEqual(result["export_status"], "export_ready")
  ```

  If no safe discretionary account exists, keep lines/fields that are mechanically supported but do not invent an account.

- [ ] **Step 3: Branch before marking completed**

  Replace unconditional completion:

  ```python
  if _ai_attention_status(result) == "ai_retry_required":
      retry = outage_service.schedule_retry(...)
      store.update_processing_job(
          job_id=job_id,
          status=retry.status,
          next_attempt_at=retry.next_attempt_at,
          retry_step=retry.retry_step,
          outage_episode_id=retry.outage_episode_id,
          ...
      )
  else:
      store.update_processing_job(job_id=job_id, status="completed", ...)
  ```

- [ ] **Step 4: Preserve partial rule coverage**

  Provisional result keeps verified line decisions. Uncovered lines remain explicit and do not inherit a generic account:

  ```python
  self.assertEqual(result["line_decisions"][0]["decision_source"], "verified_rule")
  self.assertIn("ai_line_decision_incomplete", result["review_reason_codes"])
  ```

- [ ] **Step 5: Protect active human work**

  On successful retry:

  - no active lease and unchanged current revision: append new `current` revision and clear provisional state;
  - active lease: append `candidate` revision with `candidate_reason='ai_retry_during_edit'`;
  - saved human change/approval/rejection since failure: append audit-only candidate or ignored result; never advance current.

- [ ] **Step 6: Allow authorized human resolution**

  An accountant may approve/edit provisional work. If resulting journal has complete semantic authority from human decision and all hard gates pass, approval becomes authoritative and export may open. Mark linked retry job resolved so later AI cannot replace it.

- [ ] **Step 7: Close outage episode only on real recovery**

  A successful admitted-provider call is recovery evidence. Close the episode only when no linked job remains `retry_wait`; emit one recovery notification.

- [ ] **Step 8: Add notification contracts**

  Open episode:

  ```json
  {
    "kind": "ai_outage",
    "severity": "warning",
    "status": "pending",
    "title": "AI ajanlarına ulaşılamıyor",
    "message": "Etkilenen belgeler korunuyor ve otomatik yeniden denenecek."
  }
  ```

  At 15 minutes or 50 affected documents, severity becomes critical. One episode still equals one notification.

- [ ] **Step 9: Normalize frontend status**

  Map exact state to:

  ```text
  Ajan olmadan hazırlanmış
  AI sürümü hazır
  AI tekrar denenecek
  ```

  Do not show provider internals in ordinary document rows.

- [ ] **Step 10: Run focused proof**

  ```powershell
  python -m unittest backend.tests.test_ai_outage_workflow backend.tests.test_verified_rule_runtime backend.tests.test_workflow_store
  node --test frontend/app/portal-normalization.test.cjs frontend/app/portal-notifications.test.cjs
  ```

  Expected: rule continuity, provisional state, real retry, episode deduplication, candidate revision, human no-overwrite, and recovery pass.

- [ ] **Step 11: Review checkpoint**

  Inspect one outage lifecycle from first failure through retry and human/AI resolution. Confirm no false `completed`. Do not stage or commit.

---

### Task 10: Add Collaborative Review API and Frontend Lease/Autosave/Compare Flow

**Files:**
- Create: `backend/app/api/phase0_routes_review_collaboration.py`
- Create: `frontend/app/features/review/use-review-edit-lease.ts`
- Create: `frontend/app/portal-review-collaboration.js`
- Create: `frontend/app/portal-review-collaboration.d.ts`
- Create: `frontend/app/portal-review-collaboration.test.cjs`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/api/phase0_context.py`
- Modify: `backend/app/api/phase0.py`
- Modify: `backend/app/api/phase0_routes_review_export.py`
- Modify: `backend/app/services/review_service.py`
- Modify: `frontend/app/features/review/use-review-commands.ts`
- Modify: `frontend/app/portal-review-actions.ts`
- Modify: `frontend/app/portal-review-panels.tsx`
- Modify: `frontend/app/portal-app.tsx`
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/upload-api.js`
- Modify: `frontend/app/styles.css`
- Modify: `backend/tests/test_review_collaboration.py`

**Interfaces:**
- Routes:
  - `POST /store/journal/edit-lease/acquire`
  - `POST /store/journal/edit-lease/renew`
  - `POST /store/journal/edit-lease/release`
  - `POST /store/journal/edit-lease/takeover`
  - `PUT /store/journal/working-draft`
  - `GET /store/journal/candidates/{client_id}/{document_ref}`
- Stored review now accepts `edit_lease_id`.

- [ ] **Step 1: Add failing authorization/API tests**

  Cover owner, blocked viewer, expired lease, wrong client, wrong actor, stale revision, takeover without reason, and candidate list tenant isolation.

- [ ] **Step 2: Add payloads**

  ```python
  class JournalEditLeaseAcquirePayload(BaseModel):
      client_id: str
      document_ref: str
      expected_revision: int

  class JournalEditLeaseRenewPayload(BaseModel):
      lease_id: str
      user_activity_at: str

  class JournalEditLeaseTakeoverPayload(BaseModel):
      client_id: str
      document_ref: str
      expected_revision: int
      reason: str = Field(min_length=3, max_length=500)

  class JournalWorkingDraftPayload(BaseModel):
      client_id: str
      document_ref: str
      edit_lease_id: str
      expected_revision: int
      draft_lines: list[JournalLinePayload]
      corrected_account_code: str = ""
      corrected_counterparty_code: str = ""
      reason: str = ""
  ```

  Add `edit_lease_id: str = ""` to `ReviewDecisionPayload` for a transition period; normalized mutation rejects empty lease after frontend rollout.

- [ ] **Step 3: Acquire on first meaningful edit**

  `useReviewEditLease` receives `hasUnsavedReviewChanges`. It must not acquire on document open. On `false -> true`, call acquire once.

- [ ] **Step 4: Renew from real activity only**

  Track keyboard/mouse/input activity in visible review tab. Renew at most once per minute while activity occurred in the previous minute and `document.visibilityState === "visible"`. Do not renew from a hidden idle tab.

- [ ] **Step 5: Add debounced recoverable autosave**

  Debounce 750 ms after draft change. Send `expected_revision` and `edit_lease_id`. Surface:

  ```text
  Kaydediliyor
  Kaydedildi
  Başka sürüm oluştu
  Bağlantı kesildi; yerel değişiklik korunuyor
  ```

  Failed autosave keeps local draft and never clears dirty state.

- [ ] **Step 6: Render blocked editor state**

  Other user sees:

  ```text
  Kerem bu fişi düzenliyor.
  Son etkinlik: 2 dakika önce.
  ```

  Inputs and approve/change actions become read-only. Viewing evidence remains available.

- [ ] **Step 7: Add candidate comparison**

  When `AI sürümü hazır`, show current vs candidate line differences using stable keys:

  ```javascript
  {
    lineKey,
    currentAccount,
    candidateAccount,
    currentDebit,
    candidateDebit,
    currentCredit,
    candidateCredit,
    changed
  }
  ```

  Actions:

  ```text
  Mevcut çalışmamı koru
  AI sürümünü yeni çalışma kopyası olarak aç
  ```

  Candidate never replaces current silently.

- [ ] **Step 8: Release lease**

  Release after successful approve/reject, explicit document switch with saved state, or component teardown when safe. Server expiry remains authoritative if release call fails.

- [ ] **Step 9: Run focused tests/build**

  ```powershell
  python -m unittest backend.tests.test_review_collaboration backend.tests.test_phase0_services
  node --test frontend/app/portal-review-collaboration.test.cjs frontend/app/portal-review-performance.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  ```

  Expected: first-edit acquisition, real-activity renewal, blocked viewer, autosave, stale conflict, takeover, candidate comparison, keyboard shortcuts, and build pass.

- [ ] **Step 10: Review checkpoint**

  Manually inspect two-browser-session flow before any live claim. Do not stage or commit.

---

### Task 11: Make AI Agents a Versioned Rule-Management Surface

**Files:**
- Create: `backend/app/api/phase0_routes_learning_rules.py`
- Create: `frontend/app/features/agents/use-agent-rule-commands.ts`
- Create: `frontend/app/features/agents/index.ts`
- Create: `frontend/app/portal-agent-rules.js`
- Create: `frontend/app/portal-agent-rules.d.ts`
- Create: `frontend/app/portal-agent-rules.test.cjs`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/api/phase0_context.py`
- Modify: `backend/app/api/phase0.py`
- Modify: `backend/app/services/learning_rule_service.py`
- Modify: `frontend/app/portal-agents-view.tsx`
- Modify: `frontend/app/portal-app.tsx`
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/upload-api.js`
- Modify: `frontend/app/styles.css`
- Modify: `backend/tests/test_learning_rule_lifecycle.py`

**Interfaces:**
- Routes:
  - `GET /store/learning-rules`
  - `GET /store/learning-rules/{rule_key}`
  - `POST /store/learning-rules/{rule_key}/activate`
  - `POST /store/learning-rules/{rule_key}/pause`
  - `POST /store/learning-rules/{rule_key}/archive`
  - `POST /store/learning-rules/{rule_key}/versions`

- [ ] **Step 1: Add failing API authorization/version tests**

  Assert accountant/admin can manage authorized scope; client user cannot activate/pause/archive; stale `expected_version` returns 409.

- [ ] **Step 2: Add exact payload**

  ```python
  class LearningRuleLifecyclePayload(BaseModel):
      expected_version: int
      reason: str = Field(default="", max_length=500)

  class LearningRuleNewVersionPayload(BaseModel):
      expected_version: int
      rule_snapshot: dict[str, object]
      reason: str = Field(min_length=3, max_length=500)
  ```

- [ ] **Step 3: Return accountant-readable rule view**

  ```json
  {
    "rule_key": "client:firma-1:supplier:1234567890:dogalgaz",
    "version": 2,
    "status": "active",
    "scope_label": "Firma 1",
    "trigger_label": "VKN 1234567890",
    "meaning_label": "Doğal gaz gideri",
    "binding_label": "770.03.001",
    "source_document_label": "ABC2026000000001",
    "confirmed_by": "mali-musavir",
    "last_matched_at": "",
    "match_count": 0,
    "correction_count": 0
  }
  ```

  API may mask VKN in general list while detail remains authorized.

- [ ] **Step 4: Implement state transitions**

  Allowed:

  ```text
  draft -> active
  active -> paused
  paused -> active
  draft|active|paused -> archived
  archived -> new version only
  ```

  Every transition appends audit event. Never mutate an older version's snapshot.

- [ ] **Step 5: Build pure frontend view model**

  Buckets:

  ```javascript
  {
    awaiting: rules.filter(rule => rule.status === "draft"),
    active: rules.filter(rule => rule.status === "active"),
    paused: rules.filter(rule => rule.status === "paused"),
    archived: rules.filter(rule => rule.status === "archived"),
  }
  ```

  Actions depend on status and authorization; no delete action exists.

- [ ] **Step 6: Replace read-only candidate board**

  Preserve agent capacity summary. Replace static learning columns with rule lifecycle tabs/cards. Progressive detail shows source decision, scope, binding, history, and metrics.

- [ ] **Step 7: Handle unavailable chart binding**

  If bound account disappears/inactivates:

  - rule becomes non-applicable;
  - show `Hesap planı bağlantısı geçersiz`;
  - do not silently select another account;
  - offer new version creation after accountant chooses current account.

- [ ] **Step 8: Run tests/build**

  ```powershell
  python -m unittest backend.tests.test_learning_rule_lifecycle backend.tests.test_auth_policy
  node --test frontend/app/portal-agent-rules.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  ```

  Expected: authorization, state transitions, version conflicts, archived history, invalid binding, frontend buckets/actions, and build pass.

- [ ] **Step 9: Review checkpoint**

  Verify an accountant can explain what rule matches, where, why, and which account it owns without reading JSON. Do not stage or commit.

---

### Task 12: Add a Strict High-Evidence Multi-Invoice PDF Identity Guard

**Files:**
- Create: `backend/app/domain/pdf_invoice_boundaries.py`
- Create: `backend/tests/test_pdf_invoice_boundaries.py`
- Modify: `backend/app/domain/pdf_invoices.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_workflow_store.py`

**Interfaces:**
- Produces:
  - `PdfPageText`
  - `PageInvoiceIdentity`
  - `MultiInvoiceBoundaryDecision`
  - `detect_multiple_invoice_identities(pages)`.
- Does not split pages or create child documents.

- [ ] **Step 1: Write negative regressions first**

  Build fixtures:

  ```text
  8-page electricity invoice with repeated headers and consumption rows
  6-page natural-gas invoice with many totals and VAT sections
  4-page mixed-VAT commercial invoice
  3-page invoice with page-level subtotals
  1-page invoice with 100 product rows
  ```

  Assert every fixture:

  ```python
  self.assertEqual(decision.status, "single_invoice")
  self.assertNotIn("multiple_invoice", decision.reason_codes)
  ```

- [ ] **Step 2: Write positive high-evidence test**

  Pages 1-2 contain invoice number A and ETTN A with coherent issuer/buyer/date/total. Pages 3-4 contain invoice number B and ETTN B with a second coherent header/total. Assert:

  ```python
  self.assertEqual(decision.status, "confirmed_multiple")
  self.assertEqual(decision.identity_cluster_count, 2)
  self.assertEqual(decision.reason_codes, ("distinct_invoice_identities",))
  ```

- [ ] **Step 3: Add ambiguous-case test**

  Two different number-like strings without two coherent invoice headers must return:

  ```python
  self.assertEqual(decision.status, "insufficient_identity")
  self.assertNotIn("multiple_invoice", decision.reason_codes)
  ```

  The ordinary parser continues and later canonical/totals validation reports its actual evidence gap.

- [ ] **Step 4: Preserve page text**

  Refactor:

  ```python
  @dataclass(frozen=True)
  class PdfPageText:
      page_no: int
      text: str

  def extract_pdf_pages(path: Path) -> tuple[tuple[PdfPageText, ...], tuple[str, ...]]:
      ...

  def extract_pdf_text(path: Path) -> tuple[int, str, tuple[str, ...]]:
      pages, notes = extract_pdf_pages(path)
      return len(pages), "\n".join(page.text for page in pages), notes
  ```

  Keep existing `extract_pdf_text` callers compatible.

- [ ] **Step 5: Implement strict identity clusters**

  A cluster is authoritative only with:

  ```text
  distinct ETTN/UUID, or distinct invoice number;
  disjoint page range;
  separate coherent header context;
  issuer/buyer evidence;
  issue date;
  independently extractable payable/grand total.
  ```

  Line count, page count, VAT-rate count, repeated supplier VKN, repeated word `fatura`, table headers, and page subtotals are explicitly excluded signals.

- [ ] **Step 6: Stop only confirmed multiple**

  `parse_pdf_invoice` adds:

  ```python
  if boundary.status == "confirmed_multiple":
      return ParsedInvoice(
          ...,
          risk_flags=("multi_invoice_container_confirmed",),
          suggested_route="review_queue",
          parse_notes=("separate_invoice_upload_required",),
      )
  ```

  Worker must not create one combined journal for this exact state.

- [ ] **Step 7: Use focused user copy**

  ```text
  Bir dosyada iki ayrı fatura kimliği bulundu. Faturaları ayrı dosyalar olarak yükleyin.
  ```

  Do not show “Birden fazla fatura olabilir” for weak evidence.

- [ ] **Step 8: Run focused tests**

  ```powershell
  python -m unittest backend.tests.test_pdf_invoice_boundaries backend.tests.test_phase0_domain backend.tests.test_workflow_store
  ```

  Expected: all utility/multi-line negative fixtures pass, confirmed two-identity fixture stops, ambiguous fixture does not use multi-invoice escape.

- [ ] **Step 9: Review checkpoint**

  Confirm no automatic page split, merge, child document, or permanent page-management UI entered scope. Do not stage or commit.

---

### Task 13: Prepare Controlled 50-Invoice Admission and Accountant Reference Workflow

**Files:**
- Create: `backend/scripts/prepare_reference_corpus_admission.py`
- Create: `backend/tests/test_reference_corpus_admission.py`
- Create: `docs/50-invoice-accountant-reference-runbook.md`
- Modify: `backend/app/api/phase0_routes_corpus.py`
- Modify: `backend/app/services/protected_corpus_service.py`
- Modify: `backend/tests/test_protected_corpus.py`
- Modify: `backend/tests/test_protected_corpus_postgres.py`

**Interfaces:**
- Produces:
  - ignored admission manifest under `private_samples`;
  - exact preflight counts/hashes/directions/periods;
  - ordinary upload then immediate corpus enrollment sequence;
  - no direct store bypass.

- [ ] **Step 1: Add manifest validation tests**

  Manifest contract:

  ```json
  {
    "corpus_key": "pilot-accountant-reference",
    "version": 1,
    "items": [{
      "relative_path": "firma-1/fatura.xml",
      "client_id": "firma-1",
      "period": "2026-02",
      "direction": "purchase",
      "sha256": "64-hex",
      "document_type": "einvoice_xml"
    }]
  }
  ```

  Validate:

  ```text
  exactly 50 items
  exactly 35 purchase
  exactly 15 sales
  unique SHA-256
  valid YYYY-MM period
  supported invoice document type
  relative path remains inside supplied source root
  no source bytes or personal data written to repository
  ```

- [ ] **Step 2: Implement preflight-only script**

  The script reads files, computes hashes, verifies manifest, and prints/writes summary under ignored `private_samples`. It must not write DB, upload, enroll, freeze, or delete.

  CLI:

  ```powershell
  python backend/scripts/prepare_reference_corpus_admission.py `
    --manifest private_samples/reference_corpus_manifest.json `
    --source-root private_samples/real_pilot `
    --output private_samples/reference_corpus_preflight.json
  ```

- [ ] **Step 3: Document ordinary upload sequence**

  For each item:

  1. authenticated accountant selects correct client;
  2. upload uses `POST /phase0/store/document-upload-multipart`;
  3. request includes manifest `period`, `document_type`, and actual file;
  4. response source hash/document ref is compared to manifest;
  5. processed direction is verified from canonical party evidence;
  6. enrollment uses `POST /phase0/store/corpora/{corpus_id}/items`;
  7. only after all sources are enrolled does ordinary processing/review continue.

  Do not use `import_private_intake_manifest.py` because it writes directly to the store and does not prove the accountant API path.

- [ ] **Step 4: Add corpus progress contract**

  Extend safe corpus GET response:

  ```json
  {
    "target_purchase_count": 35,
    "target_sales_count": 15,
    "enrolled_purchase_count": 0,
    "enrolled_sales_count": 0,
    "reference_ready_count": 0,
    "missing_reference_count": 50,
    "status": "draft"
  }
  ```

  No raw source path or bytes.

- [ ] **Step 5: Define accountant review sequence**

  The runbook requires:

  ```text
  inspect canonical source/parties/direction/lines/VAT/totals
  inspect proposed journal and explanation
  approve unchanged or correct then approve
  save rule only when genuinely reusable
  verify reference capture
  move to next document
  ```

  One completed document must produce a reference version even when no correction was needed.

- [ ] **Step 6: Keep freeze gate exact**

  Freeze requires:

  ```text
  35 purchase
  15 sales
  50 unique source hashes
  authoritative reference for every item
  balanced final journal for every item
  complete canonical line and allocation coverage
  current source hash match
  no cross-tenant item
  ```

- [ ] **Step 7: Add admission/freeze tests**

  ```powershell
  python -m unittest backend.tests.test_reference_corpus_admission backend.tests.test_protected_corpus
  ```

  With PostgreSQL:

  ```powershell
  python -m unittest backend.tests.test_protected_corpus_postgres
  ```

  Expected: manifest validation, no-store preflight, safe progress, ordinary intake linkage, reference capture, and freeze gates pass.

- [ ] **Step 8: Review checkpoint**

  Confirm repository contains no real invoice file, VKN list, customer name, manifest, or preflight output. Do not stage or commit.

---

### Task 14: Full Verification, Canonical Documentation Alignment, and Execution Handoff

**Files:**
- Modify: `docs/product-plan/00-canonical-decision-register.md`
- Modify: `docs/product-plan/01-product-requirements-document.md`
- Modify: `docs/product-plan/02-system-architecture-document.md`
- Modify: `docs/product-plan/03-development-roadmap.md`
- Modify: `docs/current-handoff.md`
- Review: all files changed in Tasks 1-13

**Interfaces:**
- Produces an evidence-backed local completion report and exact release/reset/upload approval packets.
- Performs no external release or destructive action.

- [ ] **Step 1: Run migration unit proof**

  ```powershell
  python -m unittest backend.tests.test_db_migrations
  ```

  Expected: migrations `001`-`010` ordered, checksummed, immutable, and contract-complete.

- [ ] **Step 2: Run focused backend proof**

  ```powershell
  python -m unittest `
    backend.tests.test_pilot_reinitialization `
    backend.tests.test_period_retention `
    backend.tests.test_learning_rule_lifecycle `
    backend.tests.test_verified_rule_runtime `
    backend.tests.test_review_collaboration `
    backend.tests.test_ai_outage_workflow `
    backend.tests.test_pdf_invoice_boundaries `
    backend.tests.test_reference_corpus_admission `
    backend.tests.test_protected_corpus `
    backend.tests.test_normalized_invoice_journal `
    backend.tests.test_phase0_services `
    backend.tests.test_auth_policy
  ```

  Expected: all configured tests pass.

- [ ] **Step 3: Run real PostgreSQL 16 proof**

  Set only in the local test shell:

  ```powershell
  $env:FISORA_TEST_POSTGRES_DSN='[REDACTED_TEST_DSN]'
  ```

  Run:

  ```powershell
  python -m unittest `
    backend.tests.test_pilot_reinitialization_postgres `
    backend.tests.test_normalized_invoice_journal_postgres `
    backend.tests.test_protected_corpus_postgres
  ```

  Prove:

  ```text
  fresh 001-010 migration
  existing 001-006 upgrade to 007-010
  migration rerun reports no pending migrations
  normalized source-to-approved-export transaction
  retry claim concurrency
  edit lease concurrency
  retention delete concurrency
  clean-start preview fingerprint and full deletion
  ordinary TEMIZLE still preserves protected assets
  ```

- [ ] **Step 4: Run frontend proof**

  ```powershell
  node --test frontend/app/*.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  ```

  Expected: all Node tests pass and Next.js production build succeeds.

- [ ] **Step 5: Run stable full proof**

  ```powershell
  python -m unittest discover -s backend/tests
  node --test frontend/app/*.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  git diff --check
  ```

  Report exact pass/skip counts. DSN-gated skips are not real PostgreSQL proof.

- [ ] **Step 6: Run explicit architecture invariant audit**

  Confirm:

  ```text
  one normalized accounting authority
  no long-lived compatibility dual write
  no deterministic discretionary fallback
  verified rule loaded before AI
  export independent from AI-used flag
  raw deletion preserves derived truth
  read notification remains pending
  AI retry does not mark false completion
  human work never overwritten
  candidate revision excluded from export
  normal TEMIZLE preserves protected data
  full reinitialization requires separate confirmation/fingerprint
  no weak multi-invoice escape
  no real source/private data in git
  ```

- [ ] **Step 7: Update canonical decisions**

  Update only proven/settled behavior:

  - Retention: replace terminal-decision/upload-day 60+30 language with assigned-period schedule and February/May example.
  - AI outage: explicitly preserve complete verified-rule automation and export eligibility.
  - Human editing: mark implemented pieces only after tests pass.
  - AI Agents: document lifecycle actions/version history.
  - Multi-invoice: defer automatic split; document strict identity guard and excluded weak signals.
  - Persistent-pilot data ownership: record normalized target activation path.
  - Broad reset: retain protected-preservation rule and add distinct full reinitialization exception.
  - 50 corpus: keep exact 35/15 and accountant-reference freeze gate.

- [ ] **Step 8: Update current handoff from evidence**

  Record:

  ```text
  branch and current commit
  local-only implementation state
  migrations 007-010
  exact test/build/PostgreSQL results
  normalized config wiring
  remaining commit/push/deploy approval
  remaining live reinitialization preview/approval
  remaining real 50-invoice upload and accountant review
  ```

  Do not claim the corpus exists or accounting quality is accepted before real admission/review/freeze.

- [ ] **Step 9: Self-review this implementation against the plan**

  Search changed files for:

  ```text
  TODO
  TBD
  placeholder
  extend_90_days
  static_fallback_account
  hardcoded notification count
  raw provider exception output
  private_samples path committed as data
  ```

  Each match must be removed or explicitly justified by a backward-compatibility test.

- [ ] **Step 10: Prepare release approval packet**

  Report:

  ```text
  exact changed files
  branch and remote
  production target
  migration range
  local and real-PostgreSQL proof
  frontend proof
  dirty-worktree boundaries
  material risks
  no live reset/upload performed
  ```

  Ask once for the exact `commit + push + deploy` transaction. Stop if scope/target/risk changes.

- [ ] **Step 11: Prepare separate live reinitialization approval packet**

  After successful release and live read-only preflight, show:

  ```text
  preview fingerprint
  operational counts to delete
  protected counts to delete
  users/credentials to preserve
  resolved storage roots
  normalized target proof
  exact confirmation string
  ```

  Obtain explicit approval before executing the live destructive operation.

- [ ] **Step 12: Prepare separate 50-invoice admission checkpoint**

  After clean-start verification, show:

  ```text
  zero old operational/protected data
  accountant/admin login works
  target normalized
  corpus draft created with 35/15 targets
  local ignored manifest preflight exactly 50/35/15
  clients/chart plans ready
  ```

  Only then upload/enroll the real 50 invoices.

---

## Post-Implementation Live Sequence

This sequence is not authorized merely by approving this plan:

1. Release migrations/code through the approved release transaction.
2. Verify live health, active normalized target, and migrations `001`-`010`.
3. Run read-only full reinitialization preview.
4. Present preview fingerprint and exact deletion/preservation counts.
5. Obtain explicit destructive-action approval.
6. Execute full reinitialization once.
7. Verify only accountant/admin identities and required tenant/auth data remain.
8. Create required clients and import their real chart plans.
9. Create protected corpus version 1 with target 35 purchase / 15 sales.
10. Validate ignored local admission manifest: exactly 50 unique files/hashes.
11. Upload each invoice through the ordinary accountant multipart endpoint.
12. Verify canonical direction and immediately enroll each source.
13. Process drafts through rule-first/AI/outage-safe worker.
14. Have the real accountant approve/correct every document.
15. Capture authoritative reference and optional confirmed rule versions.
16. Freeze only when all 50 accounting-quality gates pass.

---

## Final Acceptance Criteria

### Data and persistence

- Active backend, document worker, and QNB worker use PostgreSQL + normalized accounting target.
- No compatibility store acts as authoritative accounting truth.
- After clean start and corpus admission, exactly 50 source invoices exist.
- No prior operational/protected pilot data or rules remain.
- Required accountant/admin users, selected clients, access grants, and chart plans remain.

### Accounting and rule authority

- Complete verified-rule coverage produces zero AI and zero research calls.
- VKN is authority only through an explicit accountant-confirmed rule condition.
- Every canonical line has exactly one accepted semantic authority and journal allocation.
- Partial rules preserve covered lines and send only uncovered decisions to AI.
- No invalid/uncovered decision receives a generic deterministic account.
- Export uses authoritative approved/current journal state, never candidate revision or processing completion alone.

### AI outage

- All-provider failure creates real `retry_wait`, not false `completed`.
- Retry schedule matches 2m, 5m, 10m, 15m, 30m, 2h, 6h, then bounded six-hour cadence through 24h.
- One outage episode produces one deduplicated notification.
- Full verified-rule documents continue normally during outage.
- Provisional documents are visible, editable, approvable, and protected from unattended export.
- Human edits/approvals/rejections are never overwritten.

### Retention

- Assigned period drives schedule.
- February produces warning on 1 May and raw deletion on 31 May.
- One client+period warning remains pending after read until deletion resolves it.
- No per-document notification spam.
- Raw source deletion preserves canonical, journal, review, rule, and audit records.

### Collaboration

- First meaningful edit acquires five-minute lease.
- Mere viewing creates no lease.
- Hidden/idle tab does not renew.
- Other users see active editor and read-only state.
- Autosave is recoverable and revision-safe.
- AI retry during edit creates candidate revision.
- Candidate comparison is explicit.
- Forced takeover requires reason and audit.

### AI Agents

- Authorized users can activate, pause, archive, and create new versions.
- Old versions remain visible.
- Invalid chart binding disables application without silent account substitution.
- Rule source, scope, trigger, meaning, binding, actor, and history are explainable.

### PDF boundary safety

- Multi-line, multi-page, mixed-VAT, electricity, and natural-gas fixtures never trigger multi-invoice state.
- Only two coherent independent invoice identities trigger the strict guard.
- Weak/ambiguous evidence reports its real canonical/totals issue, not a multi-invoice escape.
- No automatic page splitting exists in this phase.

### Corpus

- Exactly 35 purchase and 15 sales sources.
- Every item entered ordinary accountant upload path.
- Every source hash is unique and protected.
- Every item has canonical lines, balanced final journal, complete allocations, and authoritative accountant reference.
- Freeze is impossible before all 50 gates pass.

---

## Out of Scope

- Backup implementation or readiness.
- Automatic multi-invoice page splitting/merging.
- New document families beyond current UBL/XML and supported PDF intake.
- Automatic rule creation from unconfirmed text.
- Permanent hard-delete button for ordinary rule management.
- Replacing the existing accounting UI with a new workflow.
- Commit, push, deploy, live reset, or real invoice upload without their required approvals.

