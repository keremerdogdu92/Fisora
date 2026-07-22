# Protected Accountant Reference Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a versioned 35-purchase/15-sales accountant-reference corpus, confirmed learning rules, and original UBL bytes across ordinary pilot reset, then prove encrypted off-host backup and isolated restore before real invoices enter Fisero.

**Architecture:** Add a PostgreSQL-owned protected-corpus repository that is available in both compatibility and normalized accounting modes, with JSON-store parity only for local/API contract tests. Copy enrolled source bytes into a separate hash-verified protected root, snapshot canonical/accounting evidence append-only, and make reset preservation explicit and fail-closed. Keep the existing invoice/review UI; first-pilot corpus creation, enrollment, inspection, and freeze use accountant/admin API operations.

**Tech Stack:** Python 3, FastAPI/Pydantic, PostgreSQL 16/psycopg, JSON compatibility store, local filesystem storage adapters, shell/Docker Compose backup jobs, `unittest`, Node test runner, Next.js build.

## Global Constraints

- UBL/XML is the preferred canonical source; PDF evidence cannot invent missing product/service meaning.
- The protected corpus target is exactly 50 unique real sources: 35 purchase and 15 sales.
- A source is unique within a corpus version by tenant plus SHA-256.
- Protected source bytes, canonical evidence, accountant reference versions, and confirmed rule versions are never deleted by ordinary `TEMIZLE` or document retention.
- A reference version is append-only. A later accountant correction creates version N+1 and leaves all earlier versions unchanged.
- Only explicit accountant/admin review can create an authoritative reference or confirmed protected rule.
- Every authoritative reference journal must be balanced, use real usable chart accounts, and cover every canonical line exactly once; export readiness remains an independent gate.
- Rule candidates and learning events may be recorded automatically, but a rule becomes protected/active only through the existing explicit confirmation contract.
- Provider comparison reads frozen source/canonical/chart/rule/reference snapshots and cannot mutate operational drafts or export batches.
- Existing Faturalar/review UI and API consumers remain backward compatible; no new accountant-facing corpus dashboard is part of this slice.
- The protected source root must not be nested under the ordinary document or export roots cleared by reset.
- Tenant authorization is checked on every corpus operation; cross-tenant identifiers return not-found/forbidden without leaking existence.
- Existing unrelated dirty-worktree changes are preserved.
- This plan authorizes a future local implementation and verification only. Commit, push, deploy, production reset, and real-invoice upload each remain behind the Fisero release/destructive-operation boundaries.
- During execution, do not make per-task commits. Record review checkpoints and request the single disclosed commit + push + deploy approval only after the complete local proof set passes.

---

## Target File Structure

- Create `backend/db/migrations/005_protected_accountant_reference_corpus.sql`: durable corpus, item, reference-version, and protected-rule-version schema.
- Create `backend/app/persistence/protected_corpus_repository.py`: PostgreSQL transactions, tenant scoping, append-only versioning, freeze validation, and reset inventory.
- Create `backend/app/services/protected_corpus_service.py`: authorization-independent domain orchestration, source copy/hash verification, reference capture, and safe serialization.
- Create `backend/app/api/phase0_routes_corpus.py`: accountant/admin corpus API.
- Create `backend/tests/test_protected_corpus.py`: JSON/service/API contract tests.
- Create `backend/tests/test_protected_corpus_postgres.py`: DSN-gated real PostgreSQL transaction, uniqueness, reset, and constraint proof.
- Create `deploy/backup/Dockerfile`: backup image with `age`, `tar`, and PostgreSQL client support.
- Create `deploy/backup/verify_restore.py`: application-level restored-corpus verifier.
- Modify `backend/app/persistence/workflow_store.py`: JSON corpus parity and reset preservation.
- Modify `backend/app/persistence/postgres_workflow_store.py`: repository delegation and safe reset transaction.
- Modify `backend/app/api/phase0_context.py`: protected path and corpus service factory.
- Modify `backend/app/api/phase0_schemas.py`: corpus and reset-preview payloads.
- Modify `backend/app/api/phase0.py`: register corpus routes.
- Modify `backend/app/services/review_service.py`: append reference/rule versions after persisted review.
- Modify `backend/app/domain/workspace_review_updates.py`: expose stable proposal/final/quality-delta snapshots without changing accounting decisions.
- Modify `backend/tests/test_auth_policy.py`: route authorization and reset-preview coverage.
- Modify `backend/tests/test_workflow_store.py`: JSON reset behavior.
- Modify `backend/tests/test_normalized_invoice_journal.py`: reference capture from canonical review.
- Modify `backend/tests/test_db_migrations.py`: migration 005 contract.
- Modify `deploy/backup/backup.sh`: package database plus protected bytes, SHA-256 manifest, encryption, and off-host copy.
- Modify `deploy/scripts/fisora-prod.sh`: isolated restore/verify command.
- Modify `docker-compose.production.yml`: protected source volume and custom backup image.
- Modify `deploy/production.env.example`: protected path, off-host target, and age recipient settings.
- Modify `docs/production-ops-runbook.md`: backup, restore, final reset, and real-intake gate.
- Modify `docs/current-handoff.md` only after implementation evidence exists; do not claim the corpus or backup gate complete early.

---

### Task 1: Lock the SQL and Repository Contracts

**Files:**
- Create: `backend/db/migrations/005_protected_accountant_reference_corpus.sql`
- Create: `backend/app/persistence/protected_corpus_repository.py`
- Create: `backend/tests/test_protected_corpus_postgres.py`
- Modify: `backend/tests/test_db_migrations.py`

**Interfaces:**
- Consumes: `ConnectFactory`, tenant UUIDs, existing `taxpayers`, `documents`, `source_files`, `review_decisions`, and `journal_revisions` identities.
- Produces: `ProtectedCorpusRepository.create_corpus`, `enroll_item`, `get_item`, `item_for_document`, `list_protected_items`, `append_reference`, `append_confirmed_rule`, `preview_reset`, `freeze_corpus`, and `get_corpus`.

- [ ] **Step 1: Add a failing migration-contract test**

  Add to `backend/tests/test_db_migrations.py`:

  ```python
  def test_protected_corpus_migration_is_immutable_and_complete(self) -> None:
      migration = next(
          item
          for item in discover_migrations(ROOT / "backend" / "db" / "migrations")
          if item.version == "005"
      )

      self.assertIn("create table protected_corpora", migration.sql.lower())
      self.assertIn("create table protected_corpus_items", migration.sql.lower())
      self.assertIn("create table reference_outcome_versions", migration.sql.lower())
      self.assertIn("create table protected_rule_versions", migration.sql.lower())
      self.assertIn("unique (corpus_id, source_sha256)", migration.sql.lower())
  ```

- [ ] **Step 2: Run the migration test and verify the intended failure**

  Run:

  ```powershell
  python -m unittest backend.tests.test_db_migrations.DbMigrationTests.test_protected_corpus_migration_is_immutable_and_complete
  ```

  Expected: `ERROR` because migration version `005` does not exist.

- [ ] **Step 3: Add migration 005 with append-only constraints**

  Create the four tables with this minimum contract:

  ```sql
  create table protected_corpora (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      corpus_key text not null,
      version integer not null check (version > 0),
      status text not null check (status in ('draft', 'frozen', 'archived')),
      target_purchase_count integer not null default 35 check (target_purchase_count >= 0),
      target_sales_count integer not null default 15 check (target_sales_count >= 0),
      created_by text not null,
      frozen_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique (tenant_id, corpus_key, version)
  );

  create table protected_corpus_items (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      taxpayer_id uuid not null references taxpayers(id),
      corpus_id uuid not null references protected_corpora(id),
      document_id uuid references documents(id) on delete set null,
      source_file_id uuid references source_files(id) on delete set null,
      source_ref text not null,
      source_sha256 text not null check (length(source_sha256) = 64),
      protected_storage_path text not null,
      direction text not null check (direction in ('purchase', 'sale')),
      status text not null check (status in ('candidate', 'reference_ready')),
      source_snapshot jsonb not null,
      canonical_snapshot jsonb not null default '{}',
      chart_snapshot jsonb not null default '{}',
      current_reference_version integer not null default 0,
      created_by text not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique (corpus_id, source_sha256)
  );

  create table reference_outcome_versions (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      corpus_item_id uuid not null references protected_corpus_items(id),
      version integer not null check (version > 0),
      source_review_decision_id uuid references review_decisions(id) on delete set null,
      source_journal_revision_id uuid references journal_revisions(id) on delete set null,
      quality_label text not null check (quality_label in ('unchanged', 'minor', 'material', 'unusable')),
      proposal_snapshot jsonb not null,
      accountant_final_decision jsonb not null,
      journal_snapshot jsonb not null,
      allocation_snapshot jsonb not null,
      provenance jsonb not null,
      reviewer text not null,
      reason text not null default '',
      is_authoritative boolean not null default true,
      created_at timestamptz not null default now(),
      unique (corpus_item_id, version)
  );

  create table protected_rule_versions (
      id uuid primary key,
      tenant_id uuid not null references tenants(id),
      taxpayer_id uuid references taxpayers(id) on delete set null,
      corpus_item_id uuid not null references protected_corpus_items(id),
      reference_version integer not null,
      rule_key text not null,
      version integer not null check (version > 0),
      status text not null check (status in ('active', 'paused', 'archived', 'detached')),
      scope_snapshot jsonb not null,
      rule_snapshot jsonb not null,
      confirmed_by text not null,
      created_at timestamptz not null default now(),
      unique (tenant_id, rule_key, version)
  );
  ```

  Add tenant/status/item indexes and do not modify migrations `001`-`004`.

- [ ] **Step 4: Add DSN-gated failing repository tests**

  In `backend/tests/test_protected_corpus_postgres.py`, use the existing temporary-schema/DSN pattern from `test_normalized_invoice_journal_postgres.py`. Prove:

  ```python
  def test_append_reference_is_monotonic_and_duplicate_source_is_rejected(self) -> None:
      corpus = self.repository.create_corpus(
          corpus_key="pilot-accountant-reference",
          version=1,
          created_by="mali-musavir",
      )
      item = self.repository.enroll_item(**self.purchase_item_payload())
      first = self.repository.append_reference(**self.reference_payload(item["item_id"]))
      second = self.repository.append_reference(**self.reference_payload(item["item_id"]))

      self.assertEqual(first["version"], 1)
      self.assertEqual(second["version"], 2)
      self.assertEqual(self.repository.get_item(item["item_id"])["current_reference_version"], 2)
      with self.assertRaises(ProtectedCorpusConflict):
          self.repository.enroll_item(**self.purchase_item_payload())
  ```

- [ ] **Step 5: Implement the repository with transaction locks**

  In `protected_corpus_repository.py`, define:

  ```python
  class ProtectedCorpusConflict(RuntimeError):
      pass


  class ProtectedCorpusRepository:
      def __init__(self, *, connect: ConnectFactory, tenant_id: UUID, json_value: Callable[[Any], Any]) -> None:
          self._connect = connect
          self.tenant_id = tenant_id
          self._json = json_value

      def append_reference(self, *, corpus_item_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
          with self._connect() as conn:
              with conn.cursor() as cursor:
                  cursor.execute(
                      "select current_reference_version from protected_corpus_items "
                      "where tenant_id = %s and id = %s for update",
                      (self.tenant_id, corpus_item_id),
                  )
                  row = cursor.fetchone()
                  if row is None:
                      raise ProtectedCorpusConflict("corpus_item_not_found")
                  version = int(row[0]) + 1
                  # Insert the immutable reference row, then update only the item's pointer.
                  # Use parameterized SQL and self._json for every JSONB value.
          return {"corpus_item_id": str(corpus_item_id), "version": version}
  ```

  Implement the remaining declared methods with `tenant_id` in every query and
  `FOR UPDATE` on append/freeze state transitions.

- [ ] **Step 6: Run migration and PostgreSQL tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_db_migrations backend.tests.test_protected_corpus_postgres
  ```

  Expected: migration tests pass; PostgreSQL tests pass when a DSN is configured or report the existing explicit DSN skip.

- [ ] **Step 7: Record the review checkpoint**

  Inspect `git diff -- backend/db/migrations/005_protected_accountant_reference_corpus.sql backend/app/persistence/protected_corpus_repository.py backend/tests/test_db_migrations.py backend/tests/test_protected_corpus_postgres.py`. Do not stage or commit.

---

### Task 2: Add Protected Source Enrollment and Store Parity

**Files:**
- Create: `backend/app/services/protected_corpus_service.py`
- Create: `backend/tests/test_protected_corpus.py`
- Modify: `backend/app/persistence/workflow_store.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/api/phase0_context.py`

**Interfaces:**
- Consumes: uploaded document metadata, existing source `storage_path`, stored SHA-256, client ID, direction, corpus ID, and actor ID.
- Produces: `ProtectedCorpusService.create_corpus`, `enroll_document`, `get_corpus`, `freeze_corpus`, `capture_reference_if_enrolled`, and `protect_confirmed_rule_if_present`.

- [ ] **Step 1: Write failing atomic-copy and mismatch tests**

  Add:

  ```python
  def test_enroll_document_copies_bytes_and_verifies_sha256(self) -> None:
      source = self.base / "documents" / "client-1" / "invoice.xml"
      source.parent.mkdir(parents=True)
      source.write_bytes(b"<Invoice>source</Invoice>")
      digest = hashlib.sha256(source.read_bytes()).hexdigest()

      item = self.service.enroll_document(
          corpus_id="corpus-1",
          client_id="client-1",
          document_ref="invoice.xml",
          direction="purchase",
          actor="mali-musavir",
      )

      protected = Path(item["protected_storage_path"])
      self.assertEqual(protected.read_bytes(), source.read_bytes())
      self.assertEqual(hashlib.sha256(protected.read_bytes()).hexdigest(), digest)

  def test_enroll_document_leaves_no_file_or_row_on_hash_mismatch(self) -> None:
      self.store.force_document_sha256("invoice.xml", "0" * 64)
      with self.assertRaisesRegex(ProtectedCorpusError, "source_hash_mismatch"):
          self.service.enroll_document(
              corpus_id="corpus-1",
              client_id="client-1",
              document_ref="invoice.xml",
              direction="purchase",
              actor="mali-musavir",
          )
      self.assertEqual(self.store.list_protected_items("corpus-1"), [])
  ```

- [ ] **Step 2: Extend the JSON empty store without changing existing keys**

  Add these development-parity collections to `empty_store()`:

  ```python
  "protected_corpora": {},
  "protected_corpus_items": {},
  "reference_outcome_versions": {},
  "protected_rule_versions": {},
  ```

  Add tenant-local JSON methods matching the repository method names. These are
  contract-test parity only; PostgreSQL remains the persistent-pilot authority.

- [ ] **Step 3: Bind the PostgreSQL repository in every accounting mode**

  In `PostgresWorkflowStore.__init__`, initialize the repository regardless of
  `FISORA_ACCOUNTING_STORE_TARGET`:

  ```python
  self.protected_corpus_repository = protected_corpus_repository or ProtectedCorpusRepository(
      connect=self._connect,
      tenant_id=self.tenant_id,
      json_value=self._json,
  )
  ```

  Add delegation methods with the same signatures as JSON store methods. Do not
  hide corpus persistence behind `normalized_accounting_enabled`.

- [ ] **Step 4: Implement atomic protected-source copy**

  In `ProtectedCorpusService.enroll_document`:

  ```python
  target = self.protected_root / str(corpus["corpus_id"]) / f"{source_sha256}.xml"
  target.parent.mkdir(parents=True, exist_ok=True)
  temporary = target.with_suffix(target.suffix + ".tmp")
  shutil.copyfile(source_path, temporary)
  copied_sha256 = hashlib.sha256(temporary.read_bytes()).hexdigest()
  if copied_sha256 != source_sha256:
      temporary.unlink(missing_ok=True)
      raise ProtectedCorpusError("source_hash_mismatch")
  temporary.replace(target)
  ```

  Reject a `protected_root` located inside the ordinary document/export roots.
  If database enrollment fails after copying, remove only the newly created
  target; never remove a pre-existing hash-identical protected object.

- [ ] **Step 5: Add the protected root to phase0 context**

  Define:

  ```python
  DEFAULT_PROTECTED_CORPUS_PATH = Path(
      os.environ.get("FISORA_PROTECTED_CORPUS_PATH", "exports/protected-corpus")
  )

  def default_protected_corpus_path() -> Path:
      return _phase0_value("DEFAULT_PROTECTED_CORPUS_PATH", DEFAULT_PROTECTED_CORPUS_PATH)

  def get_protected_corpus_service() -> ProtectedCorpusService:
      return ProtectedCorpusService(
          store=get_workflow_store(),
          protected_root=default_protected_corpus_path(),
          document_root=default_document_storage_path(),
          export_root=default_export_path(),
      )
  ```

- [ ] **Step 6: Run focused store/service tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_protected_corpus backend.tests.test_workflow_store
  ```

  Expected: all tests pass; existing JSON reset expectations remain unchanged until Task 5 updates the protected case.

- [ ] **Step 7: Record the review checkpoint**

  Inspect the task diff and confirm no protected path can resolve under ordinary document/export roots. Do not stage or commit.

---

### Task 3: Expose a Minimal Authorized Corpus API

**Files:**
- Create: `backend/app/api/phase0_routes_corpus.py`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/api/phase0.py`
- Modify: `backend/tests/test_auth_policy.py`
- Modify: `backend/tests/test_protected_corpus.py`

**Interfaces:**
- Consumes: `get_protected_corpus_service`, request user identity, accountant/admin role, client access, corpus/document identifiers.
- Produces: create, enroll, inspect, reset-preview, and freeze endpoints without adding frontend controls.

- [ ] **Step 1: Add failing authorization tests**

  Cover this route contract:

  ```text
  POST /phase0/store/corpora
  POST /phase0/store/corpora/{corpus_id}/items
  GET  /phase0/store/corpora/{corpus_id}
  POST /phase0/store/corpora/{corpus_id}/freeze
  GET  /phase0/store/admin/test-reset/preview
  ```

  Assert client users receive `403`, missing users receive `401`, an accountant
  without client access cannot enroll, and cross-tenant corpus IDs do not leak.

- [ ] **Step 2: Add backward-compatible payloads**

  In `phase0_schemas.py`:

  ```python
  class ProtectedCorpusCreatePayload(BaseModel):
      corpus_key: str = "pilot-accountant-reference"
      version: int = 1
      target_purchase_count: int = 35
      target_sales_count: int = 15


  class ProtectedCorpusEnrollPayload(BaseModel):
      client_id: str
      document_ref: str
      direction: Literal["purchase", "sale"]


  class ProtectedCorpusFreezePayload(BaseModel):
      confirmation: str
  ```

- [ ] **Step 3: Implement routes with existing authorization helpers**

  Each route must resolve the session/header actor, require accountant/admin,
  and use `require_client_access` before enrollment. Freeze requires exact
  confirmation `CORPUSU_DONDUR` and returns `409` with machine-readable missing
  purchase/sale/reference/hash counts when incomplete.

- [ ] **Step 4: Register the router**

  Import `phase0_routes_corpus` in `phase0.py` and add exactly one
  `router.include_router(phase0_routes_corpus.router)`.

- [ ] **Step 5: Run route and authorization tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_protected_corpus backend.tests.test_auth_policy
  ```

  Expected: all corpus API and existing authentication tests pass.

- [ ] **Step 6: Record the review checkpoint**

  Confirm API responses contain no raw invoice bytes, secrets, or unrestricted
  filesystem paths. Do not stage or commit.

---

### Task 4: Capture Accountant References and Confirmed Rules Append-Only

**Files:**
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/domain/workspace_review_updates.py`
- Modify: `backend/app/api/phase0_context.py`
- Modify: `backend/tests/test_normalized_invoice_journal.py`
- Modify: `backend/tests/test_phase0_services.py`
- Modify: `backend/tests/test_protected_corpus.py`

**Interfaces:**
- Consumes: persisted review result, `proposal_snapshot`, `accountant_final_decision`, `quality_delta`, canonical validation, draft lines, allocations, reviewer identity, and confirmed rule interpretation.
- Produces: immutable reference version and optional protected rule version linked to that exact reference.

- [ ] **Step 1: Add failing reference-capture tests**

  Add tests proving:

  ```python
  self.assertEqual(first_reference["version"], 1)
  self.assertEqual(first_reference["quality_label"], "material")
  self.assertEqual(first_reference["journal_snapshot"]["total_debit"], "118.00")
  self.assertEqual(first_reference["journal_snapshot"]["total_credit"], "118.00")
  self.assertEqual(second_reference["version"], 2)
  self.assertEqual(reloaded_reference_v1, first_reference)
  ```

  Also assert a non-enrolled document creates no reference and an unconfirmed
  `rule_interpretation` creates no protected rule.

- [ ] **Step 2: Centralize deterministic quality labeling**

  Add a pure helper in `workspace_review_updates.py`:

  ```python
  MATERIAL_REFERENCE_FIELDS = {
      "selected_account_code",
      "counterparty_account",
      "vat_split",
      "draft_lines",
      "canonical_line_allocation",
  }

  def reference_quality_label(*, action: str, quality_delta: dict[str, Any]) -> str:
      if action == "approve" and not quality_delta.get("changed_fields"):
          return "unchanged"
      changed = {str(value) for value in quality_delta.get("changed_fields") or []}
      if action == "approve_with_changes" and changed & MATERIAL_REFERENCE_FIELDS:
          return "material"
      if action == "approve_with_changes":
          return "minor"
      return "unusable"
  ```

  The label describes Fisero's proposal quality; it does not change the final
  accounting result or export gate.

- [ ] **Step 3: Capture only after the review transaction succeeds**

  Add an optional `protected_corpus_service` constructor dependency to
  `ReviewService` so existing unit callers remain compatible, and pass
  `get_protected_corpus_service()` from `phase0_context.get_review_service()`.
  Then, after `save_review_decision` returns, call:

  ```python
  reference = None
  if self.protected_corpus_service is not None:
      reference = self.protected_corpus_service.capture_reference_if_enrolled(
          client_id=payload.client_id,
          document_ref=decision.document_ref,
          decision=decision.model_dump(),
          saved_review=saved,
          reviewer=user_id or decision.reviewer,
      )
  ```

  Do not capture before persistence. If corpus capture fails, record a specific
  `protected_reference_capture_failed` operation event, leave the already saved
  accountant decision/export status unchanged, and never report the corpus item
  as `reference_ready`. Corpus freeze remains blocked until capture succeeds.

- [ ] **Step 4: Enforce the accounting evidence gate**

  `capture_reference_if_enrolled` rejects authoritative completion unless:

  ```python
  valid = (
      bool(canonical_lines)
      and canonical_validation_status == "valid"
      and line_decision_coverage_status == "valid"
      and line_allocation_coverage_status == "valid"
      and Decimal(total_debit) > 0
      and Decimal(total_debit) == Decimal(total_credit)
      and not unusable_accounts
  )
  ```

  Store an `unusable` quality observation when the proposal cannot be used, but
  do not mark the item `reference_ready` until the accountant supplies a valid
  final journal.

- [ ] **Step 5: Protect only explicitly confirmed rules**

  Call `protect_confirmed_rule_if_present` only when the saved learning event
  carries the existing confirmed interpretation/confirmation contract. Persist
  the exact scope snapshot and source reference version. Never infer office-wide
  or client-wide scope from a free-text note alone.

- [ ] **Step 6: Run focused accounting/review tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_protected_corpus backend.tests.test_normalized_invoice_journal backend.tests.test_phase0_services
  ```

  Expected: append-only references, accounting evidence guards, revision
  conflicts, and explicit rule confirmation tests pass.

- [ ] **Step 7: Record the review checkpoint**

  Inspect one fixture's source -> canonical lines -> proposal -> accountant final
  journal -> reference version -> rule snapshot chain. Do not stage or commit.

---

### Task 5: Make Reset Preserve Protected Assets and Fail Closed

**Files:**
- Modify: `backend/app/persistence/workflow_store.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/api/phase0_routes_auth.py`
- Modify: `backend/tests/test_workflow_store.py`
- Modify: `backend/tests/test_auth_policy.py`
- Modify: `backend/tests/test_protected_corpus_postgres.py`

**Interfaces:**
- Consumes: protected reset inventory and existing `TestDataResetPayload`.
- Produces: preview counts, atomic reset, protected preservation counts, and zero-delete failure on unsafe dependency separation.

- [ ] **Step 1: Add failing reset-preservation tests**

  Seed one protected and one ordinary document. Assert:

  ```python
  preview = store.preview_test_data_reset(
      document_storage_path=document_dir,
      export_path=export_dir,
  )
  self.assertEqual(preview["protected_corpus_item_count"], 1)
  self.assertEqual(preview["ordinary_document_count"], 1)

  summary = store.reset_test_data(
      document_storage_path=document_dir,
      export_path=export_dir,
  )
  self.assertTrue(protected_file.exists())
  self.assertFalse(ordinary_file.exists())
  self.assertEqual(store.get_corpus(corpus_id)["items"][0]["current_reference_version"], 1)
  ```

  Add a forced dependency-conflict test and assert the database and filesystem
  remain byte-for-byte unchanged.

- [ ] **Step 2: Add reset preview route behavior**

  `GET /phase0/store/admin/test-reset/preview` returns deletion/preservation
  categories and counts. It does not expose filenames or invoice contents.

- [ ] **Step 3: Change JSON reset to preserve dedicated corpus collections and root**

  Keep `protected_corpora`, `protected_corpus_items`,
  `reference_outcome_versions`, and `protected_rule_versions` out of the reset
  replacement mapping. Clear only
  the ordinary document/export roots; never pass the protected root to
  `_clear_directory_contents`.

- [ ] **Step 4: Change PostgreSQL reset into one database transaction**

  Before deletes, call repository reset inventory validation. Delete ordinary
  operational tables/records as today, but never delete the four protected
  tables. Foreign keys from protected snapshots use `ON DELETE SET NULL`, so
  operational identities may be cleared without losing evidence. If validation
  reports an unsafe dependency, raise `ProtectedResetConflict` before the first
  `DELETE`.

- [ ] **Step 5: Delete ordinary files only after database commit**

  Before the first database delete, build the ordinary-file deletion list from
  non-protected document metadata, resolve every path under the ordinary root,
  reject path traversal, and verify none resolves under the protected root.
  After that preflight succeeds, commit the database transaction and delete the
  validated ordinary paths. Do not recursively clear a root when protected and
  ordinary files could overlap. Return failed file deletions as an operational
  warning and never report them as deleted.

- [ ] **Step 6: Run reset tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_workflow_store backend.tests.test_auth_policy backend.tests.test_protected_corpus_postgres
  ```

  Expected: accountant identity remains; protected corpus/reference/rule/source
  remain; ordinary client/trial state is removed; unsafe separation performs no
  deletion.

- [ ] **Step 7: Record the review checkpoint**

  Compare reset preview counts with reset result counts in both JSON and real
  PostgreSQL tests. Do not stage or commit.

---

### Task 6: Freeze the 35/15 Corpus and Protect Benchmark Integrity

**Files:**
- Modify: `backend/app/persistence/protected_corpus_repository.py`
- Modify: `backend/app/services/protected_corpus_service.py`
- Modify: `backend/app/api/phase0_routes_corpus.py`
- Modify: `backend/tests/test_protected_corpus.py`
- Modify: `backend/tests/test_protected_corpus_postgres.py`
- Modify: `backend/scripts/run_private_pipeline_benchmark.py`

**Interfaces:**
- Consumes: draft corpus with enrolled items and authoritative references.
- Produces: immutable frozen corpus version and read-only benchmark input snapshot.

- [ ] **Step 1: Add failing freeze-gate tests**

  Prove freeze returns structured failures for wrong direction counts, duplicate
  hashes, missing protected bytes, hash mismatch, missing canonical lines,
  incomplete allocations, unbalanced journals, or missing reference versions.

- [ ] **Step 2: Implement freeze under a corpus row lock**

  `freeze_corpus` executes
  `SELECT id, status, target_purchase_count, target_sales_count FROM protected_corpora WHERE tenant_id = %s AND id = %s FOR UPDATE`,
  recomputes all counts and hashes, and then performs only:

  ```sql
  update protected_corpora
  set status = 'frozen', frozen_at = now(), updated_at = now()
  where tenant_id = %s and id = %s and status = 'draft';
  ```

  A frozen corpus rejects enroll, reference append, and rule append. A later
  accountant correction requires a new corpus version rather than mutating the
  frozen version.

- [ ] **Step 3: Make the benchmark accept an explicit frozen corpus ID**

  Add `--corpus-id` to `run_private_pipeline_benchmark.py`. When present, read
  only repository snapshots and refuse a non-frozen corpus. Record corpus ID,
  corpus version, prompt/schema version, provider/model, chart snapshot digest,
  and rule snapshot digest in the output summary.

- [ ] **Step 4: Prohibit benchmark writes**

  Add a regression that hashes/counts operational drafts, rules, export batches,
  and corpus rows before and after a benchmark and asserts they are unchanged.

- [ ] **Step 5: Run freeze and benchmark tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_protected_corpus backend.tests.test_protected_corpus_postgres backend.tests.test_phase0_domain
  ```

  Expected: all freeze gates and read-only benchmark assertions pass.

- [ ] **Step 6: Record the review checkpoint**

  Inspect the frozen payload and verify it contains no raw provider secrets or
  unrelated tenant data. Do not stage or commit.

---

### Task 7: Back Up, Encrypt, Copy Off-Host, and Verify Restore

**Files:**
- Create: `deploy/backup/Dockerfile`
- Create: `deploy/backup/verify_restore.py`
- Modify: `deploy/backup/backup.sh`
- Modify: `deploy/scripts/fisora-prod.sh`
- Modify: `docker-compose.production.yml`
- Modify: `deploy/production.env.example`
- Modify: `docs/production-ops-runbook.md`

**Interfaces:**
- Consumes: PostgreSQL DSN, ordinary document root, protected corpus root, backup root, off-host copy root, and public age recipient.
- Produces: one encrypted timestamped database+source backup set, SHA-256 manifest, off-host copy, isolated restore, and application verifier report.

- [ ] **Step 1: Add shell/static contract checks**

  Extend the existing deployment tests or add a focused unittest that asserts
  compose mounts the protected source root read-only into the backup service and
  `backup.sh` requires `FISORA_BACKUP_AGE_RECIPIENT` and
  `FISORA_BACKUP_COPY_DIR` before reporting a persistent-pilot-ready backup.

- [ ] **Step 2: Build a purpose-specific backup image**

  Create:

  ```dockerfile
  FROM postgres:16-alpine
  RUN apk add --no-cache age tar python3
  COPY deploy/backup/backup.sh /usr/local/bin/fisora-backup.sh
  COPY deploy/backup/verify_restore.py /usr/local/bin/fisora-verify-restore.py
  ```

- [ ] **Step 3: Package actual bytes and hashes**

  Replace the path/size-only protected backup behavior with a staging directory:

  ```sh
  pg_dump "$DATABASE_URL" > "$stage/postgres.sql"
  tar -C "$PROTECTED_CORPUS_DIR" -cf "$stage/protected-corpus.tar" .
  sha256sum "$stage/postgres.sql" "$stage/protected-corpus.tar" > "$stage/SHA256SUMS"
  tar -C "$stage" -czf "$BACKUP_DIR/fisora-$stamp.tar.gz" postgres.sql protected-corpus.tar SHA256SUMS
  age -r "$FISORA_BACKUP_AGE_RECIPIENT" \
      -o "$BACKUP_DIR/fisora-$stamp.tar.gz.age" \
      "$BACKUP_DIR/fisora-$stamp.tar.gz"
  rm -f "$BACKUP_DIR/fisora-$stamp.tar.gz"
  cp "$BACKUP_DIR/fisora-$stamp.tar.gz.age" "$FISORA_BACKUP_COPY_DIR/"
  ```

  Use `mktemp -d`, trap cleanup, restrictive permissions, and never place a
  private age identity in the backup container or backup set.

- [ ] **Step 4: Add isolated restore verification**

  `verify_restore.py` receives a restored DSN and protected root, then checks:

  ```python
  checks = {
      "source_hashes_match": verify_source_hashes(connection, protected_root),
      "references_append_only": verify_reference_versions(connection),
      "journals_balanced": verify_reference_journals(connection),
      "rules_linked": verify_rule_references(connection),
      "tenant_boundaries_intact": verify_tenant_boundaries(connection),
  }
  if not all(checks.values()):
      raise SystemExit(1)
  ```

  Do not log raw invoice contents.

- [ ] **Step 5: Add an explicit restore command without the existing five-second implicit overwrite lane**

  Add `restore-protected-check` to `fisora-prod.sh`. It must require an encrypted
  backup path, an age identity path supplied at invocation, and an isolated
  compose project/database target. It must refuse the production project name.

- [ ] **Step 6: Update compose and environment examples**

  Add:

  ```text
  FISORA_PROTECTED_CORPUS_PATH=/opt/fisora/data/protected-corpus
  FISORA_BACKUP_AGE_RECIPIENT=
  FISORA_BACKUP_COPY_DIR=
  ```

  Mount the protected root into backend/worker and read-only into backup. Do not
  commit real recipients, identities, keys, DSNs, or paths containing secrets.

- [ ] **Step 7: Verify scripts and compose locally**

  Run on Windows:

  ```powershell
  docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config --quiet
  ```

  Run shell syntax in the Linux container:

  ```powershell
  docker compose --env-file deploy/production.env.example -f docker-compose.production.yml run --rm --entrypoint sh backup -n /usr/local/bin/fisora-backup.sh
  ```

  Expected: compose and shell syntax checks succeed. Do not claim restore proof
  until the isolated restore command has actually completed.

- [ ] **Step 8: Record the review checkpoint**

  Confirm the generated local test set is encrypted, copied to a distinct
  target, decryptable only with the external identity, and verified after
  isolated restore. Do not stage or commit.

---

### Task 8: Full Local Proof, Documentation, and Release Preflight

**Files:**
- Modify: `docs/current-handoff.md`
- Review: all files changed in Tasks 1-7

**Interfaces:**
- Consumes: completed protected corpus, reset, benchmark, backup, and restore implementation.
- Produces: evidence-backed local completion state and an exact release-approval packet; no release action.

- [ ] **Step 1: Run targeted corpus/reset/accounting tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_db_migrations backend.tests.test_protected_corpus backend.tests.test_protected_corpus_postgres backend.tests.test_normalized_invoice_journal backend.tests.test_workflow_store backend.tests.test_auth_policy backend.tests.test_phase0_services
  ```

  Expected: all configured tests pass; report DSN-gated skips separately.

- [ ] **Step 2: Run a real temporary PostgreSQL proof**

  Apply migrations `001`-`005` to a fresh PostgreSQL 16 database, rerun the
  migration command to obtain `No pending migrations.`, then simulate an
  existing `001`-`004` database upgrading to `005`. Enroll a fixture, append two
  references, run reset, and prove protected hashes/references/rules remain.

- [ ] **Step 3: Run isolated encrypted backup restore proof**

  Create an encrypted backup set from the temporary database and protected
  fixture root, restore to a separate database/root, and run
  `fisora-verify-restore.py`. Expected: every check is `true` and the verifier
  exits `0`.

- [ ] **Step 4: Run the stable full proof set**

  Run:

  ```powershell
  python -m unittest discover -s backend/tests
  node --test frontend/app/*.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  git diff --check
  ```

  Expected: backend and frontend suites pass, Next.js build succeeds, and diff
  check is clean. Restore any generated-only file drift that is unrelated to
  this change.

- [ ] **Step 5: Update continuity from proven behavior only**

  In `docs/current-handoff.md`, record migration 005, protected reset behavior,
  local PostgreSQL/restore evidence, remaining live deployment/reset gate, and
  that no real corpus exists until actual UBLs and accountant references are
  enrolled. Do not call Phase 2/provider/accounting quality complete.

- [ ] **Step 6: Perform plan self-audit**

  Confirm every design acceptance criterion maps to a passing test or explicit
  live gate. Search changed files for placeholder markers, plaintext secrets,
  private document contents, and unrestricted destructive paths.

- [ ] **Step 7: Prepare the single release approval packet**

  Report exact changed files, current branch, remote, production target, local
  test/build/restore results, DSN/provider/accountant gates, dirty-worktree
  boundaries, and material risks. Ask once for the disclosed
  `commit + push + deploy` transaction. Do not stage, commit, push, deploy, reset,
  or upload real invoices before approval.

---

## Post-Deploy Operational Gate (Not Authorized by This Plan)

After the release transaction succeeds:

1. Prove health/readiness and migration `005` on live PostgreSQL.
2. Create a non-real protected fixture, append two reference versions, preview
   reset, run the approved fixture reset, and prove ordinary deletion plus
   protected preservation.
3. Produce an encrypted off-host backup and complete an isolated restore check.
4. Inventory current live tenant/database/filesystem counts and create a
   recoverable pre-reset snapshot.
5. Present the exact deletion/preservation preview and obtain explicit approval
   for the one final live `TEMIZLE` operation.
6. Reset, verify no residue beyond intended identities/protection, recreate or
   verify pilot clients and chart plans, and only then authorize real UBL upload.
7. Enroll selected invoices immediately after upload; do not wait for accountant
   review to protect their source bytes.
