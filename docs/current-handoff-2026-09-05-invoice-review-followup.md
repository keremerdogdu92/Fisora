# Fisora Invoice Pipeline / Review Handoff — 2026-09-05

## Purpose
Continue the production invoice-pipeline cleanup after the 50-document APEX UI test. Do not restart the investigation from memory; verify the current repo/worktree first.

## Production baseline
- Repo: `C:\Users\kerem\Documents\Fisero`
- Production repo: `/opt/fisora/app`
- Canonical deploy path: GitHub Actions -> AWS OIDC -> restricted SSM `FisoraProductionDeploy` -> exact SHA.
- Current deployed SHA at handoff start: `7288e91`.
- `FISORA_WORKER_RETENTION_ENABLED=false` must remain false until Kerem explicitly changes it.
- GitHub deploy infrastructure was repaired: root-owned `.git` metadata was normalized safely and the restricted SSM document is version-controlled/self-diagnosing.
- Remember-me feature is already in production; new checked logins use a 30-day persistent session.

## 50-document production test
- 50/50 uploaded strictly through UI: 25 purchase + 25 sales.
- 49 processing jobs completed; 1 failed on duplicate ETTN unique constraint, not AI failure.
- For the 49 persisted results: Source Reader 49/49, Identity Planner 49/49, XKIRO Final Accountant 49/49 successful; no balance self-repair was needed in the original run.
- Approx stage timings: Reader p50 ~6.6s / p95 ~9.7s; Planner p50 ~2.1s / p95 ~4.7s; Final Accountant p50 ~21.8s / p95 ~37.2s; total p50 ~31.3s / p95 ~46.6s.
## Review analysis and user decisions
Three groups were separated:

### A. 25 documents with missing counterparty/account
- 23 sales + 2 purchase.
- Sales generally have the revenue account, but customer current account is intentionally blank when no exact chart match exists.
- 3 customer names exist in the chart under 340 (`Yasemin Demiroğlu -> 340.Y02`, `Veli Polat -> 340.V01`, `Lütfi Gündoğan -> 340.L01`), so accounting policy is needed before using them as 120-style customer current accounts.
- Superonline: supplier current account missing.
- Multinet: supplier current account missing AND model emitted out-of-chart VAT code `191.01.010`; actual chart contains `191.01.10`.
- User agrees missing-current guard is sensible; do not invent current accounts.

### B. 5 zero-value DEMANT purchase invoices
- All are 0.00 debit / 0.00 credit and match current account `320.D02`.
- Existing normalizer interpreted the 0/0 journal line as malformed, producing `normalized_draft_review_required`.
- User decision: these need their own explicit state, conceptually `no_posting_required`, while preserving the document/source rows and creating no journal posting.

### C. 19 normalized-clean documents
- 19/19 have normalized journal/revision records; all balanced.
- 17 have no meaningful accounting warning; 2 contain legitimate discount/printed-total review warnings.
- Root cause for the clean 17 still being review: three-stage compatibility result hard-codes `draft_status/review_status/export_status = review_required`.
- User decision: KEEP this policy. Clean AI drafts should remain `review_required` as **one-click accountant approval**, not auto-export.
## Out-of-chart account audit
A production-wide audit was run over persisted `document` results.
- Persisted `draft_lines` with account codes not present in the client's chart: **0**.
- Persisted `selected_*` account fields outside the chart: **0**.
- Guarded model attempts containing `account_not_in_chart:*`: **1 total**, the Multinet `191.01.010` case.
- Therefore this is not currently systemic in stored results, but the model did rewrite a valid chart code and the membership guard correctly prevented it from being persisted as a valid posting account.
- Current Final Accountant prompt already says to use only exact real chart codes; XKIRO still reformatted `191.01.10` as `191.01.010`.
- Intended fix: on `account_not_in_chart:*`, perform one targeted Final Accountant retry with explicit instruction to copy account-code strings exactly from `chart_accounts`; do NOT silently deterministically convert `010 -> 10`. If retry still emits a non-member code, leave it blocked/review-required.

## In-progress uncommitted implementation
IMPORTANT: the worktree is mixed and currently dirty. Do not reset, discard, or commit everything blindly.
Current HEAD: `7288e91`.
At handoff time `git status --short` showed 12 modified files:
- `backend/app/persistence/normalized_accounting_repository.py`
- `backend/app/workflows/three_stage_accounting_pipeline.py`
- `frontend/app/features/documents/document-workflow-model.js`
- `frontend/app/portal-client-view.tsx`
- `frontend/app/portal-next/portal-next-upload-view.tsx`
- `frontend/app/portal-normalization.d.ts`
- `frontend/app/portal-normalization.js`
- `frontend/app/portal-review-panels.tsx`
- `frontend/app/portal-shell-components.tsx`
- `frontend/app/portal-types.ts`
- `frontend/app/portal-workspace-view.tsx`
- `frontend/app/styles.css`
## What has already been edited in this turn
The current turn began implementing two approved behaviors:
1. `no_posting_required` handling in the three-stage result + normalized persistence path, so zero-value invoices preserve canonical evidence but do not create a journal.
2. targeted Final Accountant retry when `_compose_journal` returns `account_not_in_chart:*`.

Some frontend status support for `no_posting_required` has also been started (`PilotStatus`, normalization/status labels, work-queue exclusion), but there are other unrelated frontend edits already present in the same worktree. Inspect every diff before deciding what belongs to this change.

Do not assume the implementation is complete. It has NOT yet been fully tested, committed, pushed, or deployed.

## Next actions, in order
1. Run `git status`, then inspect the full diffs of the two backend files and every frontend file touched by this task. Separate unrelated pre-existing UI edits from this change; preserve them.
2. Finish/refactor the account-membership retry cleanly in both prepared-source and direct three-stage code paths. Avoid duplicated fragile logic if possible. Ensure telemetry exposes whether account repair was attempted/succeeded/failed.
3. Finish `no_posting_required` persistence semantics. Critical safety rule: if reprocessing a document that already has an existing journal, do NOT silently delete/replace it; hold for review instead.
4. Complete frontend mapping/labels so `no_posting_required` is visibly distinct (e.g. `Fiş gerekmiyor`) and does not appear as an error, review queue item, or export-ready posting.
5. Add/extend backend tests for: zero-value invoice; no journal creation; existing-journal reprocess hold; out-of-chart code -> targeted AI retry -> exact valid chart member; failed retry remains review; normal one-click approval policy unchanged.
6. Add frontend tests for `normalizeStatus('no_posting_required')`, label/rendering, and queue classification.
7. Run targeted tests, full relevant backend suite, frontend node tests/build, and `git diff --check`.
8. Only after review of the mixed worktree: commit the intended files without swallowing unrelated changes, push main, deploy through canonical GitHub/OIDC workflow, verify production smoke/retention=false.
9. Re-run the 5 DEMANT zero-value invoices and Multinet through the UI or an equivalent production reprocess flow, then verify DB/telemetry behavior.

## Non-negotiable behavioral decisions
- Clean balanced AI drafts remain one-click accountant approval; do NOT auto-export them.
- Missing/unmatched current accounts remain blank/review; do NOT invent them.
- Do not add deterministic account-code correction that mutates one unknown chart code into another.
- Retention remains disabled.
