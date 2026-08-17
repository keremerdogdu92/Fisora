# Gemini Two-Stage V2 Stabilization Implementation Plan

> Execution: `subagent-driven-development`; each implementation task uses
> RED-GREEN-REFACTOR and receives an independent code review before dependent
> work begins.

## Goal

Implement the approved V2 domain core as isolated modules, suspend the current
V1 worker connection, verify a five-document runner, and leave V2 disconnected
from production routing until separate user approval.

Approved design:
`docs/superpowers/specs/2026-08-11-gemini-two-stage-v2-stabilization-design.md`

## Global constraints

- Preserve unrelated dirty-worktree changes.
- No parser or Textract call inside the V2 path.
- No production worker connection, commit, push, deploy, auto-export, or UI
  expansion.
- Warnings retain the best available draft and never short-circuit runnable
  downstream stages.
- `complete` requires fact coverage, tenant integrity, no unresolved accounts,
  and a balanced journal. All other useful drafts are `partial`.
- Use real domain code, temp files, and local repositories in tests. Replace
  only the paid Gemini HTTP boundary. PostgreSQL tests require a real configured
  test DSN; otherwise report explicit skips.

## Dependency and exclusive ownership map

Tasks 1, 2, and 4 may run in parallel. Task 3 starts after Tasks 1 and 2. Task 5
starts after Tasks 1-4. Task 6 starts after Task 5.

| Task | Exclusive implementation ownership |
|---|---|
| 1 | `canonical_invoices.py`, `accounting_projection.py`, V2 projection tests |
| 2 | new candidate/runtime modules, `accounting_candidate_expansion.py`, their tests |
| 3 | new proposal/journal/quality modules and their tests |
| 4 | artifact repository, artifact domain if required, migration/schema, artifact tests |
| 5 | new pipeline/adapter, V2-only Gemini prompt stage, V1 worker disconnection, pipeline tests |
| 6 | V2 runner/report and runner tests |

No two active implementers may edit the same file. Reviewers do not edit files.

## Task 1: Stable accounting fact identities and posting semantics

Files:

- Modify `backend/app/domain/canonical_invoices.py`
- Modify `backend/app/domain/accounting_projection.py`
- Create `backend/tests/test_gemini_v2_projection.py`

Interfaces:

- `CanonicalTaxComponent` gains a stable `component_id`, explicit
  `economic_effect`, and inclusion metadata sufficient to prevent duplicate
  posting.
- `CanonicalMonetaryComponent` gains a stable `component_id`, explicit signed
  effect, and `included_in_line_net`, `included_in_tax_total`, and
  `included_in_payable` states. Unknown inclusion is represented explicitly;
  it is not guessed away.
- `build_accounting_projection(...)` emits stable refs:
  `line:<id>`, `vat:<id>`, `tax:<id>`, and `monetary:<id>`.
- VAT tax components that are the same canonical VAT fact as a VAT summary are
  marked as the same identity, so downstream code can represent them once.

RED acceptance tests:

1. A real canonical fixture with discount/charge data preserves each monetary
   component and its amount in projection.
2. VAT present in both summary and component form resolves to one accounting
   identity.
3. Purchase withholding carries a payable-reducing credit-side effect.
4. Empty/unknown inclusion metadata produces a warning but retains the fact.
5. Stable IDs remain identical across repeated mapping of identical input.

RED command:

```powershell
python -m unittest backend.tests.test_gemini_v2_projection
```

Expected RED: assertions fail because IDs/effect/inclusion fields are absent or
VAT/monetary identity is not representable.

Minimal GREEN:

- Add deterministic identity/effect normalization to the canonical mapper.
- Extend the projection without adding any account candidate or account choice.
- Keep existing canonical and projection consumers backward compatible.

GREEN/regression:

```powershell
python -m unittest backend.tests.test_gemini_v2_projection backend.tests.test_gemini_invoice_form
```

## Task 2: Active tenant candidates, exact tax-ID priority, and dedicated runtime

Files:

- Create `backend/app/domain/accounting_candidate_builder.py`
- Create `backend/app/domain/gemini_pdf_runtime.py`
- Modify `backend/app/domain/accounting_candidate_expansion.py`
- Create `backend/tests/test_accounting_candidate_builder_v2.py`
- Create `backend/tests/test_gemini_pdf_runtime_v2.py`

Interfaces:

```python
build_accounting_candidates(
    workspace: Mapping[str, object],
    projection: Mapping[str, object],
) -> AccountingCandidateCatalog

build_gemini_pdf_runtime_from_env(
    env: Mapping[str, str],
) -> GeminiPdfRuntime
```

`AccountingCandidateCatalog` exposes the initial sent slice, accumulated real
candidates, and expansion search. Candidate records preserve `candidate_id`,
code, name, roles, normalized tax ID, tax office, active state, and origin
round. The expansion session supports full provisional proposals and at most two
extra rounds, including returning to an earlier candidate.

RED acceptance tests:

1. Inactive accounts are absent from initial and expansion results.
2. An exact normalized VKN/TCKN match beyond the ordinary limit appears in the
   initial pool.
3. Expansion search finds candidates by tax ID, role, alias, code, name, and tax
   office.
4. Later rounds preserve all earlier sent candidates.
5. A full provisional proposal survives empty expansion and provider failure.
6. Dedicated Gemini runtime builds from `GEMINI_API_KEY` and Gemini-specific
   configuration even when the general provider chain excludes Gemini.
7. Missing key returns
   `GeminiPdfRuntime(provider=None, available=False, retryable=False,
   unavailable_reason="gemini_api_key_missing")` without reading/logging a
   secret or constructing a legacy provider fallback. Invalid numeric Gemini
   configuration returns the same typed unavailable shape with
   `unavailable_reason="gemini_runtime_config_invalid:<field>"`.

RED commands:

```powershell
python -m unittest backend.tests.test_accounting_candidate_builder_v2
python -m unittest backend.tests.test_gemini_pdf_runtime_v2
```

Expected RED: imports fail for the new modules or behavioral assertions fail
against the existing candidate/runtime coupling.

Minimal GREEN:

- Move V2 candidate construction/search into the new pure domain module.
- Extend the existing bounded session only for generic/full proposal retention;
  do not change V1 orchestration.
- Construct `GeminiAccountingProvider` directly from Gemini-specific settings.
- Return a typed unavailable runtime rather than `None` or a raw configuration
  exception when the dedicated provider cannot be constructed.

GREEN/regression:

```powershell
python -m unittest backend.tests.test_accounting_candidate_builder_v2 backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_accounting_candidate_expansion backend.tests.test_gemini_direct_pdf_provider
```

## Task 3: Full proposal, deterministic journal, and non-blocking quality

Depends on Tasks 1 and 2.

Files:

- Create `backend/app/domain/accounting_proposal.py`
- Create `backend/app/domain/journal_draft_builder.py`
- Create `backend/app/domain/accounting_quality.py`
- Create `backend/tests/test_accounting_proposal_v2.py`
- Create `backend/tests/test_journal_draft_builder_v2.py`
- Create `backend/tests/test_accounting_quality_v2.py`

Interfaces:

```python
parse_accounting_proposal(
    payload: Mapping[str, object],
    *,
    required_decision_refs: Sequence[str],
    sent_candidates: Mapping[str, AccountingCandidate],
) -> AccountingProposalV2

build_journal_draft(
    projection: Mapping[str, object],
    proposal: AccountingProposalV2,
) -> JournalDraftV2

evaluate_accounting_quality(
    projection: Mapping[str, object],
    proposal: AccountingProposalV2,
    draft: JournalDraftV2,
) -> AccountingQualityResult
```

The proposal contains counterparty, line, VAT, non-VAT tax/withholding, and
monetary-component decisions. AI amounts are ignored. Missing selections become
explicit unresolved draft lines carrying their fact ref and amount.

RED acceptance tests:

1. Purchase and sales proposals cover every decision-ref family.
2. Unknown, inactive, tenant-external, and never-sent candidate IDs are rejected
   as integrity errors; any sent active tenant candidate is accepted without a
   semantic relevance veto.
3. `propose_new` is preserved with no counterparty creation side effect.
4. Line, VAT, non-VAT tax, withholding, and monetary facts appear exactly once.
5. VAT duplicated in source representations posts once.
6. Purchase withholding posts credit-side and reduces the counterparty balance.
7. Discount/charge inclusion metadata prevents double posting.
8. Debit/credit totals and balance use Decimal currency precision.
9. Unresolved or unbalanced drafts remain intact and evaluate to `partial` with
   warnings; they cannot evaluate to `complete`.
10. Fully covered balanced drafts evaluate to `complete`.

RED commands:

```powershell
python -m unittest backend.tests.test_accounting_proposal_v2
python -m unittest backend.tests.test_journal_draft_builder_v2
python -m unittest backend.tests.test_accounting_quality_v2
```

Expected RED: new API imports fail. Tests must not call the legacy
`_build_accounting_proposal_result` implementation.

Minimal GREEN:

- Implement frozen dataclasses/typed parsers for proposal and draft outputs.
- Build amounts only from projection facts.
- Implement a pure quality evaluator that never mutates or suppresses a draft.

GREEN/regression:

```powershell
python -m unittest backend.tests.test_accounting_proposal_v2 backend.tests.test_journal_draft_builder_v2 backend.tests.test_accounting_quality_v2 backend.tests.test_accounting_candidate_expansion
```

## Task 4: Source-hash-safe artifact lineage

Files:

- Modify `backend/app/persistence/document_ai_artifact_repository.py`
- Modify `backend/app/domain/document_ai_artifacts.py` only if its validation
  contract requires a typed change
- Modify `backend/db/migrations/011_gemini_two_stage_artifacts.sql`
- Modify `backend/db/schema.sql`
- Modify `backend/tests/test_document_ai_artifacts.py`
- Modify `backend/tests/test_document_ai_artifacts_postgres.py`

RED acceptance tests:

1. Local repository rejects parent, typed receipt, expansion, and retry links
   whose source SHA-256 differs from the child.
2. PostgreSQL trigger rejects the same invalid links through direct SQL inserts.
3. Same-hash valid lineage still traces receipt to canonical to projection to
   proposal.
4. Failed expansion remains linked to its successful predecessor while the
   proposal authority points to the successful receipt.

RED command:

```powershell
python -m unittest backend.tests.test_document_ai_artifacts backend.tests.test_document_ai_artifacts_postgres
```

Expected RED: local cross-hash links are accepted; live PostgreSQL negative
assertions fail when a DSN is configured.

Minimal GREEN:

- Add source hash to Python scope equality.
- Add equivalent comparisons to the SQL validation trigger.
- Keep migration and `schema.sql` artifact blocks identical.

GREEN/regression:

```powershell
python -m unittest backend.tests.test_document_ai_artifacts backend.tests.test_document_ai_artifacts_postgres backend.tests.test_period_retention
```

Report PostgreSQL skips as residual risk; do not call them database proof.

## Task 5: Isolated V2 pipeline, current UI adapter, and V1 worker suspension

Depends on Tasks 1-4.

Files:

- Create `backend/app/workflows/gemini_invoice_pipeline.py`
- Create `backend/app/workflows/gemini_invoice_result_adapter.py`
- Modify `backend/app/domain/openai_provider.py` only to add the distinct
  `accounting_selection_v2` instruction branch; do not alter the existing V1
  `accounting_selection` branch or transport safety contract
- Modify `backend/app/workflows/document_processing.py` only to disconnect the
  current V1 helper from `process_next_job_once`; retain the standalone V1
  helper for comparison until V2 proof acceptance
- Create `backend/tests/test_gemini_invoice_pipeline_v2.py`
- Create `backend/tests/test_gemini_invoice_result_adapter_v2.py`
- Create `backend/tests/test_gemini_v1_worker_suspension.py`
- Modify `backend/tests/test_gemini_two_stage_workflow.py` only to replace its
  obsolete V1 worker-wiring expectation with the approved standalone-helper
  boundary; retain its standalone V1 regression coverage
- Create `backend/tests/test_gemini_v2_provider_prompt.py`

Interfaces:

```python
run_gemini_invoice_pipeline_v2(
    request: GeminiInvoicePipelineRequest,
    *,
    extraction_provider: GeminiAccountingProvider,
    accounting_provider: GeminiAccountingProvider,
    artifact_repository: DocumentAiArtifactRepository,
) -> GeminiInvoicePipelineResult

to_document_processing_payload(
    result: GeminiInvoicePipelineResult,
) -> dict[str, object]
```

The pipeline persists each attempt, continues after warnings, retains the last
successful provisional proposal after a later failure, and returns `partial` or
`complete`. It never imports/calls legacy PDF parsing or Textract.

`AccountingProposalRequestV2` uses candidate strategy stage
`accounting_selection_v2`. Its Gemini system instruction explicitly requests
counterparty, every canonical line, VAT, non-VAT tax/withholding, and
accounting-relevant monetary-component decisions plus the bounded sufficiency
protocol. The frozen V1 `accounting_selection` instruction remains unchanged.

V1 suspension restores `process_next_job_once` to the existing legacy worker
path and removes its automatic call to `run_gemini_two_stage_invoice_workflow`.
This is not a V2 fallback: V2 is not selected by the worker at all in this
tranche. The standalone V1 helper remains available only to its direct tests.

RED acceptance tests:

1. Native PDF produces linked extraction receipt, canonical, projection,
   accounting receipt(s), proposal, draft, and quality status.
2. Canonical/projection warnings do not stop candidate or journal stages.
3. Empty expansion and failed later expansion retain the best proposal/draft.
4. First accounting call failure creates no fabricated successful proposal but
   retains failure receipt and any prior valid snapshot.
5. Result adapter preserves `issue_date`, structured `decision_narrative`,
   account names/codes, new-counterparty suggestion, warnings, draft totals,
   and balance for the current UI mapper.
6. `process_next_job_once` cannot invoke the standalone V1 helper, even when V1
   providers/repository are present.
7. V2 module import graph and an executed probe prove no parser/Textract call.
8. Exact fake-HTTP transport proves the V2-only system instruction and output
   schema include monetary decision refs without changing V1 instructions.

RED commands:

```powershell
python -m unittest backend.tests.test_gemini_invoice_pipeline_v2
python -m unittest backend.tests.test_gemini_invoice_result_adapter_v2
python -m unittest backend.tests.test_gemini_v1_worker_suspension
```

Expected RED: V2 modules are absent and the worker still invokes V1.

Minimal GREEN:

- Orchestrate only the approved typed components.
- Add a thin, deterministic current-UI adapter.
- Remove only the V1 worker invocation/injection seam; do not delete its domain,
  artifacts, tests, or standalone orchestration.

GREEN/regression:

```powershell
python -m unittest backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_invoice_result_adapter_v2 backend.tests.test_gemini_v1_worker_suspension backend.tests.test_gemini_two_stage_workflow backend.tests.test_workflow_store backend.tests.test_ai_outage_workflow
node --test frontend/app/*.test.cjs
```

## Task 6: Controlled V2 runner and final verification

Depends on Task 5.

Files:

- Create `backend/scripts/run_gemini_two_stage_v2.py`
- Create `backend/tests/test_gemini_two_stage_v2_runner.py`

Runner contract:

- Use the real V2 pipeline and real local artifact repository.
- Replace only the paid Gemini HTTP provider in automated tests.
- Require real tenant/taxpayer identity and an active coded tenant chart.
- Use a unique artifact directory for each run.
- Report line, party/VKN, VAT, non-VAT tax, withholding, monetary-component,
  total, lineage, expansion, selection-origin, warning, debit, credit, balance,
  latency, token, cost, and status evidence.
- Aggregate `OK` requires every document to be `complete`, balanced, fully
  covered, and backed by current-run artifacts. `partial` retains its draft but
  cannot count as `OK`.
- Never print API keys or raw private request/response bodies.

RED acceptance tests:

1. Loss or duplication of a monetary component fails fact-integrity reporting.
2. Partial/unbalanced/unresolved document prevents aggregate `OK`.
3. Stale artifact IDs or previous-run receipts prevent aggregate `OK`.
4. Repeated runner execution does not accumulate prior token/artifact counts.
5. Warning continuation is proven only when later artifact/draft stages exist.

RED command:

```powershell
python -m unittest backend.tests.test_gemini_two_stage_v2_runner
```

Expected RED: module import fails.

Minimal GREEN:

- Implement the secret-safe runner and report contract.
- Do not modify or delete the V1 runner.

Targeted GREEN:

```powershell
python -m unittest backend.tests.test_gemini_two_stage_v2_runner backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_direct_pdf_provider
```

## Final verification

After every task has passed independent review and all important findings are
fixed, run fresh evidence:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check -- backend/app/domain backend/app/workflows backend/app/persistence backend/db backend/tests backend/scripts docs/superpowers
```

Then inspect requirement-by-requirement:

- V2 import/call graph contains no parser/Textract path.
- Worker contains no V1 or V2 production invocation.
- Draft fact refs exactly match projection fact refs.
- Balance/status evidence agrees with journal lines.
- Cross-hash lineage is rejected in every available persistence lane.
- Existing UI mapper receives its expected payload types.

If Gemini credentials and the approved five-document inputs/chart are available,
run the controlled V2 proof once. Otherwise report the exact missing
prerequisite and do not claim live proof. Live PostgreSQL proof likewise requires
the configured test DSN.

No task includes commit, push, deploy, production routing, or removal of V1.
