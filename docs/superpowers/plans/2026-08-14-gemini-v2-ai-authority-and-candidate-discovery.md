# Gemini V2 AI Authority and Candidate Discovery Implementation Plan

Approved design:
`docs/superpowers/specs/2026-08-14-gemini-v2-ai-authority-and-candidate-discovery-design.md`

## Goal and constraints

Implement the approved AI-authority contract, progressive candidate discovery,
partial proposal recovery, treatment decisions, semantic warnings, runtime
hardening, and the next-round 50/50 candidate experiment.

- Preserve immutable provider receipts and canonical facts.
- Preserve the detached dirty V2 worktree and unrelated user changes.
- Do not add parser/Textract fallback, automatic account creation, automatic
  approval, UI expansion, or a global/V1 model-default change.
- Do not commit, push, deploy, mutate production, or run paid Gemini calls.
- Write regression tests with the implementation. The external agent executes
  the real API/corpus test round.

## 2026-08-17 approved AI-result resolution amendment

The following tasks are a narrow amendment to Tasks 1, 2, 3, 5, 6, 8, and 10
below. They govern where the older task text differs. Existing implemented
behavior outside this amendment remains unchanged.

For external verification quota safety, the isolated runner sets a hard budget
of nineteen accounting-provider calls per document, shared across ordinary
candidate rounds, all decision-capacity chunks, and treatment clarifications.
The single extraction call makes the twenty-call scheduling reservation a true
upper bound. Exhaustion must retain completed work and end with the existing
partial/review-required representation; the production default remains
uncapped by this external-test-only setting.

### Amendment Task 1: Normalize non-operative line and VAT treatment per decision

Files:

- `backend/app/domain/accounting_proposal.py`
- `backend/tests/test_accounting_proposal_v2.py`

RED evidence:

- A valid sent line or VAT account selection currently becomes invalid when the
  provider adds a non-empty treatment.

Minimal implementation:

- Accept the valid account selection, normalize its treatment to empty, preserve
  the raw receipt, and add a sanitized decision-level
  `nonoperative_treatment_ignored` issue.
- Keep hard candidate and reference integrity failures unchanged.

### Amendment Task 2: Preserve incomplete tax and monetary selections

Files:

- `backend/app/domain/accounting_proposal.py`
- `backend/tests/test_accounting_proposal_v2.py`

RED evidence:

- A non-zero tax or monetary fact can use a blank treatment and later receive a
  deterministic posting effect, or lose a valid account selection when the
  treatment is malformed.

Minimal implementation:

- Require an operative treatment for non-zero `select_existing` tax and monetary
  decisions.
- Preserve a valid sent candidate separately when only treatment validation
  fails and expose the reference as requiring clarification.
- Never classify that preserved candidate as an unresolved account.

### Amendment Task 3: Add one targeted clarification cycle

Files:

- `backend/app/domain/accounting_proposal.py`
- `backend/app/domain/openai_provider.py`
- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/app/domain/document_ai_artifacts.py`
- `backend/tests/test_gemini_v2_provider_prompt.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`
- `backend/tests/test_document_ai_artifacts.py`

RED evidence:

- The pipeline has no decision-ref-scoped treatment clarification stage and
  cannot preserve a selected account while repairing treatment.

Minimal implementation:

- Build a single-reference clarification request containing canonical evidence,
  the incomplete decision, and accumulated sent candidates.
- Permit a corrected full decision or a request for candidate expansion under
  the existing discovery and request-budget caps.
- Persist clarification receipts and lineage; perform at most one clarification
  cycle for each affected reference.
- Reuse only structurally valid earlier decisions and retain explicit warnings.

### Amendment Task 4: Represent failed clarification as review, not account loss

Files:

- `backend/app/domain/journal_draft_builder.py`
- `backend/app/domain/accounting_quality.py`
- `backend/app/workflows/gemini_invoice_result_adapter.py`
- `backend/tests/test_journal_draft_builder_v2.py`
- `backend/tests/test_accounting_quality_v2.py`
- `backend/tests/test_gemini_invoice_result_adapter_v2.py`

RED evidence:

- Missing treatment can silently fall back to deterministic effect, or its
  account can appear unresolved even though a valid candidate was selected.

Minimal implementation:

- Remove silent tax/monetary effect fallback for a treatment-incomplete AI
  selection.
- Preserve the candidate on a non-posting review line with no debit or credit,
  keep the other draft lines, and emit one `review_required` result.
- Report the decision-level reason without adding a new user-facing status.

### Amendment Task 5: Extend external measurements without provider calls

Files:

- `C:\Users\kerem\Desktop\Fisero_V2_RealCorpus_REAL_Retest_2026-08-14\real_retest_runner.py`
- `C:\Users\kerem\Desktop\Fisero_V2_RealCorpus_REAL_Retest_2026-08-14\EXTERNAL_AGENT_TEST_INSTRUCTIONS.md`

Required measurements:

```text
nonoperative_treatment_ignored
treatment_clarification_attempted
treatment_clarification_resolved
treatment_clarification_review_required
suggested_account_preserved
true_unresolved_account
```

The implementation agent updates local tests and the external-agent commands but
does not run Gemini or the real corpus.

The complete quota-aware handoff prompt is maintained in:

```text
docs/superpowers/plans/2026-08-17-gemini-v2-ai-result-resolution-external-agent-verification.md
```

### Amendment targeted GREEN command

```powershell
python -m unittest backend.tests.test_accounting_proposal_v2 backend.tests.test_gemini_v2_provider_prompt backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_journal_draft_builder_v2 backend.tests.test_accounting_quality_v2 backend.tests.test_gemini_invoice_result_adapter_v2 backend.tests.test_document_ai_artifacts
```

## Task 1: Add decision-level treatments and `no_separate_posting`

Files:

- `backend/app/domain/accounting_proposal.py`
- `backend/app/domain/accounting_quality.py`
- `backend/app/domain/journal_draft_builder.py`
- `backend/app/domain/openai_provider.py`
- `backend/tests/test_accounting_proposal_v2.py`
- `backend/tests/test_accounting_quality_v2.py`
- `backend/tests/test_journal_draft_builder_v2.py`
- `backend/tests/test_gemini_v2_provider_prompt.py`

Interfaces:

- Extend fact `AccountingDecisionV2.action` with `represented`, `excluded`, and
  `no_separate_posting`; retain `select_existing` and `unresolved`.
- Add `selected_treatment: str` to fact decisions; counterparty decisions keep
  an empty treatment.
- Tax treatments are exactly `deductible_tax`, `expense_or_cost`,
  `payable_withholding`, `represented_in_line`, `no_separate_posting`, `other`.
- Monetary treatments are exactly `increase_payable`, `reduce_payable`,
  `represented`, `excluded`, `no_separate_posting`, `other`.
- `select_existing` requires a sent candidate; `represented` and `excluded`
  require empty candidate ID plus representation/exclusion evidence;
  `no_separate_posting` requires an exactly zero canonical posting amount.

RED evidence:

- A zero VAT/tax/monetary fact cannot currently produce a valid
  `no_separate_posting` decision.
- The existing `select_existing` plus empty candidate shape invalidates the
  proposal.

Minimal implementation:

- Generate decision-ref-aware output schemas.
- Validate `no_separate_posting` against an exactly zero canonical posting
  amount.
- Normalize `select_existing` plus empty candidate only for exactly zero facts,
  while retaining the immutable raw receipt.
- Represent the fact once in the draft with zero amount and no account posting.
- Keep non-zero represented/excluded facts distinct from the zero-only action and
  preserve their topology without inventing an account.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_accounting_proposal_v2 backend.tests.test_accounting_quality_v2 backend.tests.test_journal_draft_builder_v2 backend.tests.test_gemini_v2_provider_prompt
```

## Task 2: Parse and merge proposals per decision

Files:

- `backend/app/domain/accounting_proposal.py`
- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/app/domain/document_ai_artifacts.py`
- `backend/tests/test_accounting_proposal_v2.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`
- `backend/tests/test_document_ai_artifacts.py`

Interfaces:

```text
AccountingDecisionValidationIssue
  decision_ref
  code
  message
  round_index
  chunk_index
  receipt_artifact_id

AccountingProposalParseResult
  counterparty
  valid_decisions
  issues
  sufficiency
```

RED evidence:

- One invalid fact decision currently discards the whole chunk proposal.
- A later invalid round cannot preserve the earlier valid decision explicitly.

Minimal implementation:

- Parse each required reference independently.
- Persist sanitized validation issues without copying secret/provider exception
  data.
- Maintain latest-valid decision state per reference and merge chunks in stable
  chunk order.
- Emit `latest_ai_decision_invalid` and `using_last_valid_ai_decision` when the
  final receipt for a reference is invalid.
- Use unresolved only when no valid decision exists for that reference.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_accounting_proposal_v2 backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_document_ai_artifacts
```

## Task 3: Implement progressive full-universe candidate rounds

Files:

- `backend/app/domain/accounting_candidate_builder.py`
- `backend/app/domain/accounting_candidate_expansion.py`
- `backend/app/domain/accounting_proposal.py`
- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/tests/test_accounting_candidate_builder_v2.py`
- `backend/tests/test_accounting_candidate_expansion.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`

Interfaces:

- Add discovery mode values `adaptive` and `exhaustive`.
- Add stable round builders:
  - round 0: existing focused limit 40;
  - round 1 cumulative target:
    `max(80, ceil(real_candidate_count / 2))`;
  - round 2 cumulative target: the complete real candidate universe.
- Enforce `max_accounting_request_bytes=3_000_000` and return exact universe,
  sent, coverage, and truncation metadata.

RED evidence:

- Current expansions add at most 40 search-term matches and stop when no literal
  match is found.
- Current execution stops after an apparently sufficient early proposal.
- Current round 2 cannot guarantee full active/detail chart coverage.

Minimal implementation:

- Preserve stable relevance and account-code ordering.
- Accumulate only unseen candidates and preserve `origin_round`.
- In exhaustive mode run all three rounds for every active chunk.
- Accept any valid sent AI selection; emit structured semantic conflicts rather
  than filtering the final selection.
- Never silently exceed or truncate the request budget.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_accounting_candidate_builder_v2 backend.tests.test_accounting_candidate_expansion backend.tests.test_gemini_invoice_pipeline_v2
```

## Task 4: Add deterministic 50/50 next-round assignment

Files:

- `backend/app/domain/gemini_pdf_runtime.py`
- `backend/app/workflows/document_processing.py`
- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/app/worker.py`
- `deploy/production.env.example`
- `docker-compose.production.yml`
- `backend/tests/test_gemini_pdf_runtime_v2.py`
- `backend/tests/test_gemini_v2_worker_routing.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`

Configuration:

```text
FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT=0
FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES=3000000
```

The next external run sets the percentage to `50`. Production-like default
remains `0`.

Assignment algorithm:

```text
bucket = sha256("{taxpayer_id}:{document_id}:candidate-discovery-v1") % 100
mode = exhaustive when bucket < experiment_percent else adaptive
```

RED evidence:

- The runtime currently has no per-document discovery assignment or experiment
  metadata.

Minimal implementation:

- Resolve the mode once per document and carry it through every chunk/round.
- Persist mode, group, bucket, round, candidate counts, coverage, and truncation
  in receipt/proposal metadata.
- Ensure retrying the same document receives the same assignment.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_gemini_v2_worker_routing backend.tests.test_gemini_invoice_pipeline_v2
```

## Task 5: Make VAT and tax semantics advisory and auditable

Files:

- `backend/app/domain/accounting_candidate_builder.py`
- `backend/app/domain/accounting_projection.py`
- `backend/app/domain/accounting_proposal.py`
- `backend/app/domain/journal_draft_builder.py`
- `backend/app/domain/accounting_quality.py`
- `backend/tests/test_accounting_candidate_builder_v2.py`
- `backend/tests/test_gemini_v2_projection.py`
- `backend/tests/test_journal_draft_builder_v2.py`
- `backend/tests/test_accounting_quality_v2.py`

RED evidence:

- Account VAT-rate parsing misses names such as `Yuzde 20` and `KDV 20`.
- `%20` facts can silently accept explicit `%18` accounts without conflict
  evidence.
- Every `360*` account can be inferred as `special_tax` whenever the document has
  any tax component.

Minimal implementation:

- Normalize structured rates and explicit label forms `%20`, `Yuzde 20`, and
  `KDV 20`.
- Remove blanket `360* => special_tax` inference.
- Rank focused candidates with direction, tax kind, label, and rate signals.
- Add AI `selected_treatment` for non-VAT tax decisions.
- Apply the valid AI choice to the draft and emit structured
  `vat_rate_semantic_conflict` or `tax_treatment_conflict` when expectations
  differ.

Regression fixtures include document IDs:

```text
d782e9d0-1408-5d1a-9fa0-169520ada471
66f04688-4dc1-5b15-a653-857707153932
f59b7669-7e26-5b7c-9672-615816cf1b9a
```

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_accounting_candidate_builder_v2 backend.tests.test_gemini_v2_projection backend.tests.test_journal_draft_builder_v2 backend.tests.test_accounting_quality_v2
```

## Task 6: Build the source-backed monetary ledger and keep AI authority

Files:

- `backend/app/domain/accounting_projection.py`
- `backend/app/domain/monetary_reconciliation.py`
- `backend/app/domain/accounting_proposal.py`
- `backend/app/domain/journal_draft_builder.py`
- `backend/app/domain/accounting_quality.py`
- `backend/tests/test_gemini_v2_projection.py`
- `backend/tests/test_monetary_reconciliation_v2.py`
- `backend/tests/test_journal_draft_builder_v2.py`
- `backend/tests/test_accounting_quality_v2.py`

RED evidence:

- `allowance_total` and unmatched named totals do not participate in payable
  topology.
- Discounts can remain classified as payable increases.
- SGK participation pay can remain outside the component ledger even when it
  exactly explains the payable difference.

Minimal implementation:

- Build candidates from explicit monetary components, `allowance_total`, and
  de-duplicated named totals with source links.
- Produce deterministic alternative effects and exact/best-fit reconciliation
  evidence without selecting the journal treatment.
- Ask AI for `selected_treatment` and use it to build the draft.
- Preserve AI treatment on disagreement and emit `monetary_effect_conflict`,
  residual, and balance warnings.
- Keep line IDs and equal-description lines separate.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_gemini_v2_projection backend.tests.test_monetary_reconciliation_v2 backend.tests.test_journal_draft_builder_v2 backend.tests.test_accounting_quality_v2
```

## Task 7: Add cache-ready prompt structure and complete usage accounting

Files:

- `backend/app/domain/openai_provider.py`
- `backend/app/domain/document_ai_artifacts.py`
- `backend/tests/test_gemini_v2_provider_prompt.py`
- `backend/tests/test_document_ai_artifacts.py`

RED evidence:

- Token usage currently omits `cachedContentTokenCount`.
- Raw test receipts contain no persisted cache-hit metric.
- Chunk-specific variation is not explicitly separated from the stable prompt
  prefix.

Minimal implementation:

- Keep stable instructions, projection, and accumulated candidate catalog in
  deterministic serialization order before chunk-specific content.
- Capture prompt, candidate, cached, thought when present, and total tokens.
- Remove deprecated Gemini 3.5 Flash-Lite sampling parameters `temperature` and
  `topP` from new-model requests.
- Do not create explicit cached-content resources in this task.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_gemini_v2_provider_prompt backend.tests.test_document_ai_artifacts backend.tests.test_gemini_direct_pdf_provider
```

## Task 8: Separate result status axes and derived evidence

Files:

- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/app/workflows/gemini_invoice_result_adapter.py`
- `backend/app/domain/accounting_quality.py`
- `backend/app/domain/canonical_invoices.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`
- `backend/tests/test_gemini_invoice_result_adapter_v2.py`
- `backend/tests/test_gemini_invoice_form.py`

Interfaces:

```text
processing_status
extraction_validation_status
reconciliation_status
accounting_decision_status
draft_balance_status
review_status
export_status
```

RED evidence:

- A document can report `complete` while canonical validation is invalid.
- Missing line VAT metadata and factual contradictions are flattened into the
  same invalid summary.

Minimal implementation:

- Persist independent status axes while keeping the current compatibility status.
- Create derived line-to-VAT linkage outside immutable extraction using source
  evidence, unique groups, and arithmetic.
- Distinguish contradiction, missing evidence, derived/reconciled linkage, and
  informational warnings.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_invoice_result_adapter_v2 backend.tests.test_gemini_invoice_form
```

## Task 9: Harden transient retry, receipt lineage, and DB connections

Files:

- `backend/app/persistence/postgres_workflow_store.py`
- `backend/app/persistence/store_factory.py`
- `backend/app/workflows/document_processing.py`
- `backend/app/worker.py`
- `backend/tests/test_workflow_store.py`
- `backend/tests/test_gemini_v2_worker_routing.py`
- `backend/tests/test_document_ai_artifacts_postgres.py`

RED evidence:

- A transient PostgreSQL `OperationalError` can become a permanent failed job.
- Later successful provider attempts can lack `retry_of_artifact_id`.
- Production store construction opens a new direct connection for each store
  operation.

Minimal implementation:

- Classify psycopg operational/interface and transient transport failures as
  bounded retryable technical errors; keep integrity/schema errors permanent.
- Apply bounded exponential backoff with jitter and retain every failed attempt.
- Link provider retries to the preceding failed receipt.
- Add a bounded process-local connection pool and release connections before
  provider HTTP waits.

Targeted GREEN command:

```powershell
python -m unittest backend.tests.test_workflow_store backend.tests.test_gemini_v2_worker_routing backend.tests.test_document_ai_artifacts_postgres
```

## Task 10: Extend the external real-corpus A/B report

Files:

- `C:\Users\kerem\Desktop\Fisero_V2_RealCorpus_REAL_Retest_2026-08-14\real_retest_runner.py`
- `C:\Users\kerem\Desktop\Fisero_V2_RealCorpus_REAL_Retest_2026-08-14\EXTERNAL_AGENT_TEST_INSTRUCTIONS.md`

Required output additions:

```text
candidate_experiment_assignment.json
candidate_round_transitions.csv
candidate_universe_coverage.json
semantic_conflicts.json
decision_validation_issues.json
cache_and_token_usage.json
adaptive_vs_exhaustive_quality.json
adaptive_vs_exhaustive_cost.json
```

Acceptance evidence:

- Exactly one deterministic group per document and stable assignment on retry.
- Control and experiment denominators shown independently and by taxpayer.
- Selection transitions classify improved, degraded, unchanged, and unresolved.
- Calls, latency, prompt/output/cached/total tokens, list-price estimate, and
  cache-adjusted estimate are reported per group.
- The report does not claim cross-tenant isolation unless the DB contains at
  least two distinct tenant IDs.
- API keys and authorization headers never appear in output.

The external agent first executes local regressions:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

Then it uses isolated PostgreSQL and the four configured project-specific Gemini
keys for the complete 384-document round with:

```text
FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT=50
```

The runner must preflight active project quotas without printing secrets, throttle
per project, continue successful documents after retryable failures, and stop
before a project is knowingly driven past its daily limit.

## Final acceptance

The implementation is ready for the external real-corpus round only when:

1. Every targeted regression command passes.
2. The full backend/frontend/build/diff proof passes.
3. PostgreSQL retry and lineage tests pass against an isolated PostgreSQL 16 DSN.
4. Default experiment percentage is `0` and default discovery mode is adaptive.
5. No paid API call, commit, push, deploy, or production mutation has occurred.

The external A/B result, not implementation completion alone, decides whether
exhaustive discovery, explicit Gemini caching, or another candidate strategy is
adopted afterward.

## 2026-08-18 superseding amendment: external call metering

The former fixed nineteen-accounting-call control and the related twenty-call
scheduling reservation are superseded. They are not part of the active V2
runtime or request contract, and no replacement fixed per-document provider
call ceiling is introduced.

External verification meters actual provider calls separately for each
configured Gemini project and stops only at operator-supplied per-project test
budgets. Those operator budgets are accounting safeguards for a test run; they
are not claims about Google quota facts. The finite candidate rounds, one
targeted treatment clarification, and at most one clarification-triggered
candidate expansion remain the structural bounds on V2 work.
