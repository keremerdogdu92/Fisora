# Gemini Direct-PDF Two-Stage V1 Implementation Plan

> **Execution:** Use `subagent-driven-development`; every implementation task is
> RED-GREEN, followed by a separate review before dependent work starts.

**Goal:** Make Gemini native-PDF the primary invoice fact-extraction path, keep
its exact provider receipt re-inspectable, derive an accountant-readable
canonical invoice form and compact accounting projection, then let the
accounting AI select from real tenant candidates with at most two expansion
turns.

**Architecture:** Persist four immutable, linked artifact revisions: provider
receipt, canonical invoice form, accounting input projection, and accounting
proposal. Warnings are evidence, never pipeline control flow: every downstream
stage that can operate on available data continues and the best possible draft
is retained. Existing document-processing UI consumes the improved result; V1
adds no UI surface.

**Tech stack:** Python 3, dataclasses, unittest, PostgreSQL migrations, existing
JSON workflow store and `DocumentStorageAdapter`, Gemini `generateContent` REST.

## Global constraints

- Never log, persist, print, or commit `GEMINI_API_KEY` or authorization headers.
- Native Gemini PDF extraction is the only V1 primary extraction route. Do not
  add Textract/parser/provider fallback.
- Extraction returns document facts only; no account or counterparty choice.
- Candidate validation is tenant-data integrity only, never semantic relevance.
- One initial accounting call plus at most two expansion calls.
- Candidate history accumulates; a later answer may select an earlier candidate.
- `propose_new` remains a proposal and never auto-creates a counterparty in V1.
- A warning cannot stop a usable downstream stage, erase a draft, or replace a
  prior valid revision. Only missing/unparseable prerequisite data can make that
  specific transformation impossible.
- No new frontend panel, tab, card, approval flow, auto-export rule, retention
  policy, commit, push, or deploy.

## Task dependency and ownership map

Tasks 1-3 may run independently with exclusive file ownership. Task 4 starts
after Tasks 1 and 3. Task 5 starts after Tasks 1-4. Task 6 starts after Task 5.

| Task | Exclusive implementation ownership |
|---|---|
| 1 | `canonical_invoices.py`, new `accounting_projection.py`, its new tests |
| 2 | new `accounting_candidate_expansion.py`, its new tests |
| 3 | new artifact domain/repository, schema/migration, its new tests |
| 4 | `openai_provider.py`, direct-PDF provider tests |
| 5 | PDF/workflow/store/service integration files, workflow integration tests |
| 6 | benchmark runner/report contract only; then repository-wide verification |

---

### Task 1: Canonical invoice form and accounting projection

**Files:**
- Modify: `backend/app/domain/canonical_invoices.py`
- Create: `backend/app/domain/accounting_projection.py`
- Create: `backend/tests/test_gemini_invoice_form.py`

**Interfaces:**
- `CanonicalExtractionRequest` continues carrying original PDF bytes outside its
  serializable schema payload.
- Canonical output includes invoice identity/date/type/currency, supplier and
  customer identifiers, every line with explicit net/gross semantics, VAT and
  special-tax components, withholding, allowances/charges, and totals.
- `build_accounting_projection(canonical_revision, warnings)` returns the compact
  second-stage payload and explicit source-field links.

- [ ] RED: add fixture-driven tests proving header/party/line/tax/total coverage,
  source links, and projection losslessness for line count, VKN/TCKN, every tax
  component, and totals.
- [ ] Run `python -m unittest backend.tests.test_gemini_invoice_form` and confirm
  the missing model/projection failures.
- [ ] GREEN: extend the canonical schema and implement the minimal projection
  mapper without account-selection fields.
- [ ] Add a warning case proving warnings are carried alongside facts without
  deleting or emptying projection data.
- [ ] Re-run the targeted module and confirm PASS.

**Acceptance:** Projection is smaller than the canonical provider result yet
retains every accounting-relevant fact and source link; it contains no chart
account or counterparty choice.

---

### Task 2: Bounded, accumulating candidate expansion protocol

**Files:**
- Create: `backend/app/domain/accounting_candidate_expansion.py`
- Create: `backend/tests/test_accounting_candidate_expansion.py`

**Interfaces:**
- `AccountingCandidateSession` owns initial candidates, accumulated candidates,
  per-round requests/responses, provisional selection, and a hard expansion
  limit of two.
- AI response is an explicit tagged decision: `select_existing`,
  `request_more_candidates`, or `propose_new`.
- `select_existing` validates only that the selected code belongs to the tenant
  and was present in the accumulated sent pool.

- [ ] RED: test direct first-round selection, one/two expansions, refusal of a
  third expansion, accumulated pool behavior, and returning to a round-one
  candidate after later rounds.
- [ ] RED: test that a provisional first-round candidate survives expansion and
  may become the final answer.
- [ ] RED: test integrity rejection for unknown/unsent codes while allowing any
  sent real candidate without a semantic-relevance gate.
- [ ] RED: test `propose_new` without an existing code and with no creation side
  effect.
- [ ] Run `python -m unittest backend.tests.test_accounting_candidate_expansion`
  and confirm expected failures.
- [ ] GREEN: implement the minimal pure state machine and deterministic round
  transcript.
- [ ] Re-run the targeted module and confirm PASS.

**Acceptance:** Total accounting calls cannot exceed three; all previously sent
candidates remain selectable; no relevance heuristic blocks a real sent tenant
candidate.

---

### Task 3: Immutable linked artifact persistence

**Files:**
- Create: `backend/app/domain/document_ai_artifacts.py`
- Create: `backend/app/persistence/document_ai_artifact_repository.py`
- Create: `backend/db/migrations/011_gemini_two_stage_artifacts.sql`
- Modify: `backend/db/schema.sql`
- Create: `backend/tests/test_document_ai_artifacts.py`
- Create: `backend/tests/test_document_ai_artifacts_postgres.py`

**Interfaces:**
- Artifact kinds are exactly `provider_receipt`, `canonical_invoice_form`,
  `accounting_input_projection`, and `accounting_proposal`.
- Append-only manifest records lineage, stage, source/document/tenant IDs,
  provider/model, elapsed time, token usage, status/error/retry linkage, file
  hash, content hash/storage key, and prompt/schema/pipeline revisions.
- Exact request and response bytes are stored through
  `DocumentStorageAdapter`; credentials and auth headers are never accepted.
- Raw bodies live under the source document storage subtree and are removed with
  source-PDF deletion. Artifact revisions are never overwritten by retries.

- [ ] RED: unit-test exact byte round-trip, hashes, lineage, secret-field
  rejection, retry append behavior, and preservation of the previous valid
  revision.
- [ ] RED: integration-test deletion of PDF plus receipt bodies and real temp
  filesystem behavior.
- [ ] RED: PostgreSQL-test migration constraints, tenant scoping, parent lineage,
  and append-only revisions.
- [ ] Run `python -m unittest backend.tests.test_document_ai_artifacts` and
  confirm missing implementation failures.
- [ ] GREEN: implement the smallest repository and migration satisfying both
  JSON/local-storage and PostgreSQL lanes.
- [ ] Run both targeted modules; when PostgreSQL test prerequisites are absent,
  report the explicit skip rather than claiming database proof.

**Acceptance:** An operator can re-read exact request/response bytes and trace
receipt → canonical → projection → proposal; deleting the source deletes its raw
bodies; API secrets are structurally excluded.

---

### Task 4: Gemini direct-PDF transport with raw receipt capture

**Files:**
- Modify: `backend/app/domain/openai_provider.py`
- Create: `backend/tests/test_gemini_direct_pdf_provider.py`

**Interfaces:**
- Gemini transport returns a typed attempt envelope containing parsed structured
  data plus exact outbound body, exact inbound body, HTTP status, resolved model,
  elapsed time, token usage, and error metadata.
- Canonical extraction posts original `application/pdf` bytes as Gemini native
  PDF input. Accounting calls post only the accounting projection and candidate
  context.
- The transport never includes API keys or headers in the envelope.

- [ ] RED: with a fake HTTP boundary, assert exact request/response byte capture,
  native PDF MIME/base64 payload, model/status/timing/usage, and structured parse.
- [ ] RED: assert malformed JSON and provider error still return a failed raw
  receipt without fabricating canonical data.
- [ ] RED: assert extraction request has no account candidates and accounting
  request has no PDF/base64 or full raw extraction response.
- [ ] Run `python -m unittest backend.tests.test_gemini_direct_pdf_provider` and
  confirm expected failures.
- [ ] GREEN: add the attempt envelope and receipt callback/return path while
  preserving existing non-Gemini provider contracts.
- [ ] Re-run the targeted module and existing provider tests.

**Acceptance:** Paid external HTTP is the only mocked boundary; exact bodies are
available to persistence, and extraction/accounting inputs are strictly
separated.

---

### Task 5: End-to-end worker integration and non-blocking warnings

**Files:**
- Modify: `backend/app/domain/pdf_invoices.py`
- Modify: `backend/app/domain/ai_classification.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/persistence/workflow_store.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/services/document_service.py`
- Create: `backend/tests/test_gemini_two_stage_workflow.py`

**Flow:**
`source PDF → Gemini receipt → canonical form → accounting projection → initial
tenant candidates → optional expansion 1/2 → accounting proposal → existing
draft result payload`

- [ ] RED: integration-test that parser/Textract extraction is not called when
  Gemini direct-PDF runs and all four linked artifacts are persisted.
- [ ] RED: test each stage emitting a warning while later compatible stages still
  run, a best-effort draft is retained, and warnings remain visible in evidence.
- [ ] RED: test that a failed retry appends a failed receipt and does not
  overwrite the previous valid canonical/proposal/draft revision.
- [ ] RED: test first-round selection, special-tax-triggered candidate expansion,
  two-turn cap, and later selection of a first-round candidate.
- [ ] RED: test `select_existing` tenant/sent-candidate integrity and
  `propose_new` draft preservation without counterparty creation.
- [ ] RED: test source deletion removes the PDF and exact raw bodies through the
  existing deletion service.
- [ ] Run `python -m unittest backend.tests.test_gemini_two_stage_workflow` and
  confirm the unintegrated-flow failures.
- [ ] GREEN: wire the approved flow with no extraction fallback and no new UI
  payload surface.
- [ ] Re-run the workflow test plus `test_pdf_invoice_boundaries`,
  `test_workflow_store`, `test_period_retention`, and `test_ai_outage_workflow`.

**Acceptance:** A warning never short-circuits a runnable downstream stage; the
best available draft survives. Only an actually missing prerequisite prevents
that specific transformation, while receipt/retry state remains inspectable.

---

### Task 6: Controlled five-document proof and full verification

**Files:**
- Modify: `backend/scripts/smoke_gemini_native_pdf.py` only if its reusable entry
  point is insufficient.
- Create: `backend/scripts/run_gemini_two_stage_v1.py`
- Create: `backend/tests/test_gemini_two_stage_runner.py`
- No frontend source modifications.

- [ ] RED-GREEN: add a secret-safe runner contract test; output may contain only
  document identifiers/hashes, artifact IDs, coverage metrics, expansion count,
  selection-origin round, warnings, elapsed time, tokens, estimated cost, and
  draft summary—never API keys or full private bodies.
- [ ] Run all backend tests:
  `python -m unittest discover -s backend/tests`
- [ ] Run frontend regressions:
  `node --test frontend/app/*.test.cjs`
- [ ] Run frontend build:
  `Push-Location frontend; npm.cmd run build; Pop-Location`
- [ ] Run `git diff --check` and inspect only scoped changes.
- [ ] If the local secret and five-document benchmark inputs are available, run
  the controlled proof once and report per-document line/VKN/tax/total coverage,
  artifact lineage, warning continuation, expansion use, selection-origin round,
  latency/tokens/cost, and resulting draft. Otherwise report the exact missing
  prerequisite without claiming live proof.
- [ ] Do not commit, push, deploy, enable auto-export, or alter the active UI.

**Final acceptance:** Local tests prove the behavioral contract; controlled real
Gemini evidence demonstrates output quality without claiming production/export
readiness. Every warning observed remains evidence and never causes avoidable
downstream work or a useful draft to be abandoned.
