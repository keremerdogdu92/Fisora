# Gemini V2 AI Result Resolution — External Agent Verification

Use this file as the complete prompt for the external verification agent.

## Scope and safety

Work against the existing dirty detached V2 worktree only:

```text
C:\Users\kerem\.codex\worktrees\b2cd\Fisero
```

Read `AGENTS.md` first. Preserve all unrelated and existing dirty changes. Do
not commit, push, deploy, mutate production, print secrets, or rewrite provider
receipts. Local regression commands must complete before any paid/provider or
real-corpus call.

The real-corpus runner remains isolated at:

```text
C:\Users\kerem\Desktop\Fisero_V2_RealCorpus_REAL_Retest_2026-08-14
```

Do not copy its outputs into production storage. Use isolated PostgreSQL and
the already configured project-specific Gemini credentials. Never print API
keys or authorization headers.

## Order of execution

### 1. Local targeted regression

From the V2 worktree run:

```powershell
python -m unittest backend.tests.test_accounting_proposal_v2 backend.tests.test_gemini_v2_provider_prompt backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_journal_draft_builder_v2 backend.tests.test_accounting_quality_v2 backend.tests.test_gemini_invoice_result_adapter_v2 backend.tests.test_document_ai_artifacts
```

Stop before provider/corpus work if this command fails. Report the failing test
and traceback without attempting to repair the dirty worktree.

### 2. Full local proof

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

Record each command, exit code, test count, and duration separately.

### 3. Quota-aware provider preflight

Before the real corpus, inspect the active quota/capacity for every configured
Gemini project without exposing credentials. Do not assume that every project
has unused capacity. In particular, a project already near its RPM, TPM, or RPD
limit is unavailable capacity, not a product-quality failure.

Do not reserve a fixed number of provider calls per document. The former
nineteen-accounting-call control and related twenty-call scheduling reservation
are superseded and must not be enabled in the application or runner request
contract. External verification meters actual provider calls separately for
each configured Gemini project and stops at operator-supplied per-project test
budgets. These budgets are test-run safeguards, not claims about Google quota
facts. The finite candidate rounds, one targeted treatment clarification, and
at most one clarification-triggered candidate expansion remain the structural
bounds on V2 work.

Before the real corpus, preflight every configured project and record its
operator-supplied usable test budget without exposing credentials. If the
combined actual-budget capacity cannot cover the intended run, stop before
provider/corpus calls and report `BLOCKED`, or run only the largest unbiased
deterministic subset explicitly authorized for that run. Never lower a project
budget or represent it as a Google quota fact.

Use a per-project throttle based on the actual active limits. Never drive a
project knowingly beyond its daily limit. If available capacity cannot cover
the whole corpus, run the largest unbiased deterministic subset that fits,
preserve the original document ordering/assignment, and report:

- eligible documents;
- attempted documents;
- completed documents;
- quota-skipped documents;
- retryable provider failures;
- permanent/integrity failures.

Do not report a misleading `100%` corpus completion rate when quotas prevent
full execution. Quota-skipped documents must not enter accounting-quality
denominators.

### 4. Isolated real-corpus A/B run

Use the external runner with:

```text
FISORA_GEMINI_V2_CANDIDATE_EXPERIMENT_PERCENT=50
```

Keep control and experiment denominators separate, including by taxpayer. Keep
every provider attempt with provider, resolved model, timing, HTTP status,
token usage, raw request/response artifact references, retry/expansion lineage,
and terminal outcome. Sanitize secrets only; do not normalize away raw provider
behavior.

The following result-resolution measurements are mandatory:

```text
nonoperative_treatment_ignored
treatment_clarification_attempted
treatment_clarification_resolved
treatment_clarification_review_required
suggested_account_preserved
true_unresolved_account
```

Derive them as follows:

- `nonoperative_treatment_ignored`: decision validation issue count and affected
  line/VAT refs.
- `treatment_clarification_attempted`: provider receipts whose metadata has
  `clarification_for_ref`, grouped by attempt number and ref.
- `treatment_clarification_resolved`: affected refs whose final valid decision
  has an operative treatment and no treatment review flag.
- `treatment_clarification_review_required`: affected refs that remain as draft
  lines with `resolution=review_required` after the bounded cycle.
- `suggested_account_preserved`: review-required refs with a non-empty, sent,
  active selected candidate and zero debit/credit.
- `true_unresolved_account`: unresolved refs with no valid selected candidate;
  do not include treatment-only review refs.

Also retain the already approved candidate, semantic-conflict, validation,
cache/token, latency, cost, balance, residual, and adaptive-vs-exhaustive
measurements. Report counts and rates with explicit denominators; never combine
document-level and decision-ref-level percentages.

## Required conclusion

Return one concise report containing:

1. Local regression/build results.
2. Per-project quota preflight and usable capacity without secrets.
3. Attempted/completed/quota-skipped corpus counts.
4. The six resolution measurements above, with document and ref denominators.
5. Representative immutable receipt IDs for success, normalization, resolved
   clarification, failed clarification, suggested account, and true unresolved
   account.
6. Whether any treatment-only case became `unresolved_accounts` or received an
   automatic financial posting; either occurrence is a regression.
7. Remaining risks and the exact command needed to continue if quota prevented
   completion.

Do not claim production readiness solely from local tests or a quota-limited
sample. Do not change application behavior while performing this verification.
