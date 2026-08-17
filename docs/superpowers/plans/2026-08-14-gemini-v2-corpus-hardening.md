# Gemini V2 Corpus Hardening Implementation Plan

Approved design:
`docs/superpowers/specs/2026-08-14-gemini-v2-corpus-hardening-design.md`

## Constraints

- Preserve the dirty detached V2 worktree and unrelated changes.
- No fallback, UI expansion, account creation, export authority, commit, push,
  deploy, production mutation, or paid API call.
- Add regression tests, but do not execute tests in this session. Hand exact
  commands to the external test agent.

## Task 1: Fact-aware tenant candidate allocation

Files:

- `backend/app/domain/accounting_candidate_builder.py`
- `backend/app/domain/accounting_proposal.py`
- `backend/tests/test_accounting_candidate_builder_v2.py`

Behavior:

- Add candidate VAT-rate metadata derived from explicit chart metadata or an
  explicit percentage label.
- Reserve candidates for every required VAT rate and non-VAT tax source label.
- Fill remaining capacity by deterministic role round-robin.
- Transport candidate VAT rates to the second AI.

External RED/GREEN command:

```powershell
python -m unittest backend.tests.test_accounting_candidate_builder_v2
```

## Task 2: Named totals and source-backed reconciliation

Files:

- `backend/app/domain/canonical_invoices.py`
- `backend/app/domain/openai_provider.py`
- `backend/app/domain/accounting_projection.py`
- `backend/app/domain/monetary_reconciliation.py`
- `backend/tests/test_gemini_invoice_form.py`
- `backend/tests/test_monetary_reconciliation_v2.py`

Behavior:

- Add backward-compatible observed named-total facts.
- Resolve explicit payable labels ahead of general/tax-inclusive totals.
- Resolve mandatory net baseline from complete lines, explicit totals, or
  complete VAT bases.
- Preserve line facts and expose bounded cent allocation differences.

External RED/GREEN command:

```powershell
python -m unittest backend.tests.test_gemini_invoice_form backend.tests.test_monetary_reconciliation_v2 backend.tests.test_gemini_v2_projection backend.tests.test_journal_draft_builder_v2
```

## Task 3: Complete receipt lineage

Files:

- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`

Behavior:

- Accumulate successful receipts instead of overwriting by chunk.
- Keep latest per-chunk receipt as direct proposal authority while linking all
  successful receipts in stable round/chunk order.

External RED/GREEN command:

```powershell
python -m unittest backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_document_ai_artifacts
```

## Task 4: Compatibility retry recovery

Files:

- `backend/app/persistence/postgres_workflow_store.py`
- `backend/tests/test_workflow_store.py`

Behavior:

- Atomically claim queued or due retry-wait compatibility jobs.
- Reject future, missing, and malformed retry timestamps.

External RED/GREEN commands:

```powershell
python -m unittest backend.tests.test_workflow_store backend.tests.test_ai_outage_workflow backend.tests.test_gemini_v2_worker_routing
```

If a test DSN is available:

```powershell
python -m unittest backend.tests.test_normalized_invoice_journal_postgres
```

## Task 5: Bounded performance improvements

Files:

- `backend/app/domain/gemini_pdf_runtime.py`
- `backend/app/domain/openai_provider.py`
- `backend/app/workflows/gemini_invoice_pipeline.py`
- `backend/app/workflows/document_processing.py`
- `backend/app/worker.py`
- `deploy/production.env.example`
- `docker-compose.production.yml`
- `backend/tests/test_gemini_pdf_runtime_v2.py`
- `backend/tests/test_gemini_invoice_pipeline_v2.py`
- `backend/tests/test_gemini_v2_worker_routing.py`
- `backend/tests/test_workflow_store.py`

Behavior:

- Reuse one runtime/provider connection pool per worker process.
- Immediately continue after productive ticks and use bounded idle backoff.
- Execute same-round chunks with configured bounded concurrency, then process
  results in stable chunk order.
- Enforce a shared per-process request-start governor.

External targeted command:

```powershell
python -m unittest backend.tests.test_gemini_pdf_runtime_v2 backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_v2_worker_routing backend.tests.test_workflow_store
```

## External final verification

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

Then rerun the remaining 225 corpus contexts and the 6 PDF x 3 repeatability
matrix with real Gemini. Compare sequential and parallel modes on the same
selected documents for canonical facts, proposal decisions, lineage IDs,
journal lines, warnings, latency, token use, and 429 count.
