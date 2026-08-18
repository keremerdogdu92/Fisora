# Gemini V2 Multi-Project Runtime and Accountant Pilot Readiness Plan

**Date:** 2026-08-17  
**Status:** Approved-scope implementation plan; not yet executed  
**Execution mode:** `subagent-driven-development` with fresh `gpt-5.6-luna` / `high` agents  
**Target checkout:** `C:\Users\kerem\Documents\Fisero` on `main`

## Goal

Make Gemini V2 the testable accountant-facing pipeline for the already uploaded,
authorized invoice set without re-uploading those invoices. The implementation
must use one to eight independently governed Gemini project keys, remove the
fixed nineteen-accounting-call control entirely, run adaptive candidate
discovery only, delete disposable trial outputs while preserving uploaded input
documents, and prepare a secret-safe accountant pilot report.

This plan prepares code, tests, migrations, reset/requeue tooling, and an
operator handoff. It does not commit, push, deploy, call real Gemini, touch the
real corpus, or mutate production. Release and live execution remain manual
user actions under `AGENTS.md`.

## Approved Decisions

1. `FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS` is removed from active
   code and configuration. There is no replacement fixed per-document call
   ceiling. Existing finite candidate rounds, one targeted clarification, and
   at most one clarification-triggered expansion remain the structural bounds.
2. Gemini credentials belong to separate Google projects. The product runtime
   supports `GEMINI_API_KEY`, then `GEMINI_API_KEY_2` through
   `GEMINI_API_KEY_8`; blank slots are ignored.
3. Each configured project owns its own request governor and cooldown state.
   Calls can execute concurrently across different projects.
4. No hidden same-call retry loop is introduced. One logical provider call
   produces one provider attempt. A `429` marks only the selected slot cooling
   down and preserves the failed receipt; the existing job retry lineage makes
   the next attempt eligible for another slot.
5. Production and accountant-pilot behavior is adaptive only:
   `FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT=0`. Exhaustive discovery code
   may remain dormant for a future external experiment, but this plan does not
   activate or execute it.
6. Uploaded invoice inputs and their source files are preserved. Disposable
   generated outputs are removed, affected document-derived fields are reset,
   and eligible existing invoices are requeued without upload duplication.
7. Provider receipts expose an opaque credential slot such as
   `GEMINI_API_KEY_SLOT_3`; secret values, fingerprints, and authorization
   headers never enter logs, artifacts, reports, or tracked files.

## Non-Scope

- No real Gemini or corpus request.
- No live database cleanup or requeue.
- No production release or environment mutation.
- No exhaustive/adaptive A/B run.
- No deletion of `documents`, `source_files`, `document_sources`, chart plans,
  counterparties, tenant/user/access records, or protected corpus inputs.
- No accounting-policy change beyond the already approved V2 authority and
  result-resolution specifications.

## Agent Execution Contract

The root orchestrator owns integration and final verification. Every
implementation task is dispatched to a fresh subagent with these exact
overrides:

```text
model: gpt-5.6-luna
reasoning_effort: high
fork_turns: "3"
```

Each task runs in this order:

1. Luna implementer reads repository `AGENTS.md`, this complete plan, and only
   the canonical design/plan sections named by the task.
2. Implementer uses `test-driven-development`: add the narrow failing test,
   capture RED, implement the minimum change, capture GREEN, and run the listed
   regression command.
3. Root inspects the diff directly.
4. A different fresh Luna/high reviewer performs read-only requirement and test
   review. The reviewer must not trust the implementer's summary.
5. Defects return to the same implementer, then the fresh reviewer verifies the
   correction.
6. Root advances only after fresh evidence satisfies the task acceptance
   criteria.

Tasks are serialized because runtime, artifact, workflow, and configuration
files overlap transitively. Agents must preserve all unrelated dirty and
untracked content and must not commit, push, deploy, use secrets, make provider
calls, access the private corpus, or mutate production.

At the end of every task, both implementer and reviewer report exactly:

- change made;
- tests written and RED/GREEN evidence;
- external validation command and exit/result;
- remaining risk or `none identified`.

## Task 1: Record the Approved Amendment and Remove the Fixed Call Cap

**Depends on:** none  
**Exclusive ownership:** canonical Gemini V2 docs, pipeline request cap surface,
runtime cap parser, and their direct tests.

### Files

- Modify:
  `docs/superpowers/specs/2026-08-14-gemini-v2-ai-authority-and-candidate-discovery-design.md`
- Modify:
  `docs/superpowers/plans/2026-08-14-gemini-v2-ai-authority-and-candidate-discovery.md`
- Modify:
  `docs/superpowers/plans/2026-08-17-gemini-v2-ai-result-resolution-external-agent-verification.md`
- Modify: `backend/app/domain/gemini_pdf_runtime.py`
- Modify: `backend/app/workflows/gemini_invoice_pipeline.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/tests/test_gemini_pdf_runtime_v2.py`
- Modify: `backend/tests/test_gemini_invoice_pipeline_v2.py`

### Contract

Append a dated amendment to both canonical V2 documents before changing code.
The amendment must say that the former fixed nineteen-call accounting cap and
twenty-call scheduling reservation are superseded. External verification meters
actual calls per project and stops at operator-supplied project budgets; it does
not pretend those budgets are Google quota facts.

Remove all active references to:

```text
FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS
max_accounting_provider_calls_from_env
GeminiInvoicePipelineRequest.max_accounting_provider_calls
```

Do not remove the existing finite candidate-round and targeted-clarification
rules. Their present tests become the proof that eliminating the artificial cap
does not create an unbounded repair loop.

### RED

Add/adjust tests that fail against the current code:

- runtime construction never reads the removed environment key;
- pipeline requests no longer accept `max_accounting_provider_calls`;
- a treatment clarification remains bounded to one corrected-decision attempt
  plus at most one candidate-expansion follow-up;
- independent invalid decision references still do not create repeated repair
  loops.

Run:

```powershell
python -m unittest backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_gemini_invoice_pipeline_v2
```

Expected RED: removed-interface assertions fail while the old parser/request
field exists.

### GREEN and regression

```powershell
python -m unittest backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_v2_worker_routing
rg -n "FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS|max_accounting_provider_calls" backend deploy docker-compose.production.yml
```

Expected: tests pass; `rg` returns no active code/config matches. Historical
documentation may mention the removed control only inside the explicit
superseding amendment/history.

### Acceptance

- No active environment/config/request field represents the number nineteen.
- Clarification/candidate discovery remains structurally finite.
- No valid decisions are discarded because a document-level call cap is gone.

## Task 2: Persist an Opaque Gemini Credential Slot on Every Receipt

**Depends on:** Task 1  
**Exclusive ownership:** provider-attempt envelope, artifact domain/repositories,
migration `012`, and their direct tests.

### Files

- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/domain/document_ai_artifacts.py`
- Modify: `backend/app/workflows/gemini_invoice_pipeline.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/persistence/document_ai_artifact_repository.py`
- Add: `backend/db/migrations/012_gemini_credential_slot.sql`
- Modify: `backend/tests/test_gemini_direct_pdf_provider.py`
- Modify: `backend/tests/test_document_ai_artifacts.py`
- Modify: `backend/tests/test_document_ai_artifacts_postgres.py`
- Modify: `backend/tests/test_db_migrations.py`

### Interfaces

Extend the attempt and artifact contracts with a backward-compatible empty
default:

```python
GeminiAttemptEnvelope.credential_slot: str = ""
ArtifactWrite.credential_slot: str = ""
DocumentAiArtifact.credential_slot: str = ""
```

Migration `012` adds:

```sql
alter table document_ai_artifacts
    add column if not exists credential_slot text not null default '';
```

`GeminiAccountingProvider.__init__` accepts `credential_slot: str = ""` and
copies it to every successful and failed `GeminiAttemptEnvelope`. Receipt
builders copy that value to `ArtifactWrite`; repository SELECT/INSERT mapping
round-trips it. No key value or key fingerprint is persisted.

### RED

- Successful and failed provider attempts retain the supplied slot.
- Local and PostgreSQL artifact repositories round-trip the slot.
- An old row/default with an empty slot remains readable.
- Serialized receipt text does not contain the fake secret used by the test.

```powershell
python -m unittest backend.tests.test_gemini_direct_pdf_provider backend.tests.test_document_ai_artifacts backend.tests.test_document_ai_artifacts_postgres backend.tests.test_db_migrations
```

Expected RED: `credential_slot` is absent from the current envelopes/artifacts.

### GREEN and regression

```powershell
python -m unittest backend.tests.test_gemini_direct_pdf_provider backend.tests.test_document_ai_artifacts backend.tests.test_document_ai_artifacts_postgres backend.tests.test_db_migrations backend.tests.test_gemini_invoice_pipeline_v2
```

### Acceptance

- Every new Gemini provider receipt identifies its opaque slot.
- Existing artifact rows remain compatible.
- Secret-leak tests cover success, HTTP failure, transport failure, and parse
  failure.

## Task 3: Implement the One-to-Eight Project Pool

**Depends on:** Task 2  
**Exclusive ownership:** new project-pool module, V2 runtime construction, and
pool/runtime tests.

### Files

- Add: `backend/app/domain/gemini_project_pool.py`
- Modify: `backend/app/domain/gemini_pdf_runtime.py`
- Add: `backend/tests/test_gemini_project_pool.py`
- Modify: `backend/tests/test_gemini_pdf_runtime_v2.py`

### Interfaces

Define:

```python
@dataclass(frozen=True)
class GeminiProjectSlotConfig:
    slot_name: str
    api_key: str
    requests_per_minute: int

class GeminiProjectPoolProvider:
    provider_name = "gemini"

    def extract_invoice_canonical(self, request): ...
    def classify_product(self, request): ...
```

Runtime key enumeration is fixed and ordered:

```text
GEMINI_API_KEY             -> GEMINI_API_KEY_SLOT_1
GEMINI_API_KEY_2 .. _8     -> GEMINI_API_KEY_SLOT_2 .. _8
```

Per-slot RPM uses
`FISORA_GEMINI_REQUESTS_PER_MINUTE_<N>` when present, otherwise the shared
`FISORA_GEMINI_REQUESTS_PER_MINUTE`. Slot 1 may use
`FISORA_GEMINI_REQUESTS_PER_MINUTE_1`; absence falls back to the shared value.

Blank keys are ignored. Duplicate key values are detected in memory with a
SHA-256 digest used only for equality; neither key nor digest is emitted. The
first configured slot wins and the duplicate slot is omitted.

Selection is thread-safe and deterministic: among non-cooling slots choose the
lowest in-flight count, then the oldest selection sequence, then slot number.
Each underlying `GeminiAccountingProvider` owns a distinct
`GeminiRequestGovernor`. Calls release their in-flight lease in `finally`.

On `GeminiProviderAttemptError` with HTTP `429`, mark only that slot cooling for
`FISORA_GEMINI_PROJECT_COOLDOWN_SECONDS` (default `60`) and re-raise the same
error/attempt. Do not retry inside the pool. If every slot is cooling, choose
the one whose cooldown expires first so the provider's own request path and the
existing job retry machinery remain authoritative and receipt-bearing.

`GeminiPdfRuntime.provider` becomes the pool provider and adds only
non-sensitive observability:

```python
configured_project_count: int
configured_credential_slots: tuple[str, ...]
```

### RED

- Any nonblank slot works even when primary is blank.
- 1, 3, 7, and 8 configured unique projects produce the expected slot count.
- Blank/duplicate slots are omitted without exposing values or digests.
- Concurrent calls use separate per-project governors and distribute across
  slots.
- A 429 cools only its slot; the following call selects another available slot.
- No pool method performs an internal second provider call after a failure.

```powershell
python -m unittest backend.tests.test_gemini_project_pool backend.tests.test_gemini_pdf_runtime_v2
```

Expected RED: pool module and multi-key runtime do not exist.

### GREEN and regression

```powershell
python -m unittest backend.tests.test_gemini_project_pool backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_gemini_direct_pdf_provider backend.tests.test_gemini_invoice_pipeline_v2
```

### Acceptance

- Adding key slots up to `_8` requires no code change.
- Different projects can process calls concurrently while each obeys its own
  RPM governor.
- One exhausted project does not globally stop other projects.
- One logical provider call still maps to one immutable receipt.

## Task 4: Wire the Pool Through Worker, Readiness, and Tracked Configuration

**Depends on:** Task 3  
**Exclusive ownership:** worker/runtime wiring, readiness payload, Compose/env
contracts, and routing/readiness tests.

### Files

- Modify: `backend/app/worker.py`
- Modify: `backend/app/domain/production_readiness.py`
- Modify: `docker-compose.production.yml`
- Modify: `deploy/production.env.example`
- Modify: `backend/tests/test_gemini_v2_worker_routing.py`
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_gemini_pdf_runtime_v2.py`

### Contract

Backend and worker service environments explicitly pass
`GEMINI_API_KEY_2` through `_8`, optional per-slot RPM variables `_1` through
`_8`, and `FISORA_GEMINI_PROJECT_COOLDOWN_SECONDS`. Keep key values blank in the
tracked example.

Readiness reports only:

```json
{
  "gemini_project_count": 2,
  "gemini_credential_slots": [
    "GEMINI_API_KEY_SLOT_1",
    "GEMINI_API_KEY_SLOT_2"
  ]
}
```

The array contains all configured opaque names but no value, prefix, suffix,
digest, or project identifier. V2 is unavailable only when all eight slots are
blank/invalid. The worker continues to cache one process-wide runtime; the pool
inside that runtime is reusable and thread-safe.

Tracked configuration keeps
`FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT=0`. Do not add the removed call
cap anywhere.

### RED

- Compose passes slots to both backend and worker.
- Readiness counts slots without secrets.
- Worker builds an available V2 runtime from `_2` when primary is blank.
- Process-wide runtime reuse does not collapse the pool to one provider.
- Environment examples contain adaptive `0` and no fixed call cap.

```powershell
python -m unittest backend.tests.test_gemini_v2_worker_routing backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_phase0_domain
```

### GREEN and regression

```powershell
python -m unittest backend.tests.test_gemini_v2_worker_routing backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_phase0_domain backend.tests.test_workflow_store
rg -n "GEMINI_API_KEY(_[2-8])?|FISORA_GEMINI_REQUESTS_PER_MINUTE_[1-8]|FISORA_GEMINI_PROJECT_COOLDOWN_SECONDS" docker-compose.production.yml deploy/production.env.example
```

### Acceptance

- Backend, worker, readiness, and runtime agree on the same eight-slot contract.
- Adaptive is the only configured accountant-pilot mode.
- No secret content is printed by readiness or tests.

## Task 5: Build a Tenant-Scoped Trial-Output Reset and Requeue Tool

**Depends on:** Task 4  
**Exclusive ownership:** reset repository/service/script and bulk reprocess
force-requeue behavior.

### Files

- Add: `backend/app/persistence/gemini_trial_reset_repository.py`
- Add: `backend/scripts/reset_gemini_v2_trial_outputs.py`
- Modify: `backend/app/services/document_service.py`
- Add: `backend/tests/test_gemini_v2_trial_reset.py`
- Modify: `backend/tests/test_document_upload_api.py`

### Interface

Provide a dry-run-first repository/service contract:

```python
@dataclass(frozen=True)
class GeminiTrialResetSummary:
    tenant_key: str
    eligible_document_count: int
    deleted_counts: dict[str, int]
    reset_document_count: int
    requeued_job_count: int
    artifact_body_delete_count: int
    dry_run: bool

def reset_gemini_trial_outputs(
    *,
    dsn: str,
    tenant_key: str,
    artifact_storage_root: Path,
    apply: bool,
) -> GeminiTrialResetSummary: ...
```

The CLI defaults to dry run. Mutating mode requires both `--apply` and
`--confirm-tenant-key <exact same tenant key>`; mismatch refuses before opening
a write transaction. The implementation is tenant-scoped and uses one database
transaction for relational changes.

Preserve exactly:

- `tenants`, `taxpayers`, users/access;
- `documents` rows and uploaded-file identity/storage columns;
- `source_files` and `document_sources`;
- chart imports/accounts, counterparties, and protected corpus inputs.

Delete/reset generated trial output for eligible, non-deleted invoice documents
in the selected tenant:

- `document_ai_artifacts` and their request/response bodies;
- `ai_attempts`, `processing_attempts`, and old `processing_jobs` state;
- `invoice_lines`;
- draft/revision journal allocations, lines, revisions, entries;
- export batch items tied to those revisions, then only export batches left
  empty by that deletion;
- review decisions and learning rules sourced from those trial decisions;
- document-scoped `workflow_events`;
- derived document accounting/extraction fields, parse notes, risk flags,
  current journal pointer/revision, and processing status.

Before deleting artifact rows, collect body paths and prove every resolved path
is beneath `artifact_storage_root`. Refuse the whole apply operation if any path
escapes that root. Missing body files are counted, not treated as permission to
touch another path. After the relational reset, delete only the validated
artifact body files and report any cleanup failure explicitly.

Recreate/force-requeue one processing job for each preserved eligible invoice
with an available canonical source file. Also change
`DocumentService.store_client_reprocess` to pass `force_requeue=True`, matching
the existing single-document reprocess behavior. Do not process jobs inside the
reset command.

### RED

Seed an isolated PostgreSQL database with two tenants, uploaded source files,
old artifacts, drafts, attempts, reviews, and one path-escape artifact. Tests
must initially fail because the reset contract does not exist and bulk
reprocess does not force requeue.

```powershell
python -m unittest backend.tests.test_gemini_v2_trial_reset backend.tests.test_document_upload_api
```

### GREEN and regression

```powershell
python -m unittest backend.tests.test_gemini_v2_trial_reset backend.tests.test_document_upload_api backend.tests.test_workflow_store backend.tests.test_document_ai_artifacts_postgres
```

### Acceptance

- Dry run changes nothing and returns exact counts.
- Apply tests remove only selected-tenant generated outputs.
- Every uploaded invoice/source byte remains present and unchanged.
- Other-tenant rows/files remain unchanged.
- A path outside the artifact root causes refusal before mutation.
- Eligible preserved invoices finish with one clean queued job and require no
  upload.

## Task 6: Produce Adaptive-Only Accountant Pilot Evidence

**Depends on:** Task 5  
**Exclusive ownership:** read-only pilot report, accountant scoring template,
and its tests.

### Files

- Add: `backend/scripts/report_gemini_v2_accountant_pilot.py`
- Add: `backend/tests/test_gemini_v2_accountant_pilot_report.py`
- Modify: `backend/tests/test_gemini_v2_worker_routing.py`
- Modify: `backend/tests/test_document_upload_api.py`

### Contract

The report command is read-only, tenant-scoped, and accepts an explicit output
directory. It refuses to label a run accountant-pilot-ready when observed
artifact metadata contains exhaustive experiment assignments or when configured
experiment percent is nonzero.

Produce aggregate JSON plus a CSV scoring sheet containing opaque document IDs,
not invoice body text or secrets. Required aggregate metrics:

```text
eligible_document_count
queued/completed/retry_wait/failed counts
provider_attempts_by_credential_slot
http_status_counts
latency and token totals
canonical_extraction_available
reconciliation_exact
draft_balanced
accounting_decision_complete
nonoperative_treatment_ignored
treatment_clarification_attempted
treatment_clarification_resolved
treatment_clarification_review_required
suggested_account_preserved
true_unresolved_account
semantic_conflict_warnings
decision_integrity_rejections
```

CSV columns for human scoring:

```text
document_id,pipeline_version,processed_at,draft_status,
account_selection_grade,treatment_grade,amount_balance_grade,
canonical_line_grade,accountant_note
```

Grades are left blank for the accountant. The program must never synthesize
accountant correctness.

Add a local fake-provider/PostgreSQL flow proving:

```text
preserved source -> clean queued job -> Gemini V2 route -> new artifacts ->
new balanced draft -> workspace/API exposes the new result
```

No test performs a network call.

### RED

```powershell
python -m unittest backend.tests.test_gemini_v2_accountant_pilot_report backend.tests.test_gemini_v2_worker_routing backend.tests.test_document_upload_api
```

Expected RED: report and reset-to-current-result integration proof are absent.

### GREEN and regression

```powershell
python -m unittest backend.tests.test_gemini_v2_accountant_pilot_report backend.tests.test_gemini_v2_worker_routing backend.tests.test_document_upload_api backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_journal_draft_builder_v2
```

### Acceptance

- Report contains all required machine metrics and blank human grades.
- Credential distribution is visible without secrets.
- No exhaustive result is mixed into the pilot cohort.
- Existing input files are reused and the API surfaces only the freshly created
  V2 draft after reset/requeue.

## Task 7: Whole-Change Verification and Manual Handoff

**Depends on:** Tasks 1-6  
**Exclusive ownership:** final evidence and `docs/current-handoff.md` status
update only.

### Files

- Modify: `docs/current-handoff.md`
- No other implementation edits unless a failed verification is returned to
  the owning task agent.

### Fresh verification

Run from `C:\Users\kerem\Documents\Fisero`:

```powershell
python -m unittest backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_gemini_project_pool backend.tests.test_gemini_direct_pdf_provider backend.tests.test_document_ai_artifacts backend.tests.test_document_ai_artifacts_postgres backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_v2_worker_routing backend.tests.test_gemini_v2_trial_reset backend.tests.test_gemini_v2_accountant_pilot_report backend.tests.test_document_upload_api backend.tests.test_workflow_store backend.tests.test_db_migrations
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
rg -n "FISORA_GEMINI_V2_MAX_ACCOUNTING_PROVIDER_CALLS|max_accounting_provider_calls" backend deploy docker-compose.production.yml
git status --short
```

Expected evidence:

- all targeted and full backend tests pass;
- all frontend tests pass;
- frontend build exits `0`;
- `git diff --check` exits `0` for plan-owned files;
- removed call-cap search returns no active code/config matches;
- status contains only expected plan changes plus preserved unrelated paths;
- no real provider/corpus/live database action occurred.

### Independent Luna/high review

Dispatch a final fresh `gpt-5.6-luna` / `high` read-only reviewer with
`fork_turns: "3"`. It must inspect the complete diff against every Approved
Decision and run the targeted verification command independently. It reports
actionable findings only; root resolves every material finding before handoff.

### Handoff content

Update `docs/current-handoff.md` with confirmed local state only:

- multi-project slot contract and adaptive-only setting;
- removed call-cap contract;
- reset/requeue tool prepared but not executed live;
- exact fresh verification results;
- migration `012` prepared but not applied live;
- live secrets, release, cleanup, requeue, Gemini calls, corpus processing, and
  accountant scoring remain manual/unperformed.

## Completion Criteria

Implementation is locally complete only when:

1. all seven approved decisions map to passing tests and inspected code;
2. one-to-eight project routing is secret-safe and receipt-visible;
3. no active fixed accounting-provider-call cap remains;
4. trial outputs can be dry-run previewed and reset in an isolated PostgreSQL
   test while preserving invoice inputs;
5. preserved invoices can be force-requeued without upload;
6. adaptive-only fake-provider end-to-end proof produces a fresh visible draft;
7. accountant pilot reporting separates machine integrity from blank human
   correctness grades;
8. full verification and independent Luna/high review pass;
9. no release or production action has been taken by any agent.
