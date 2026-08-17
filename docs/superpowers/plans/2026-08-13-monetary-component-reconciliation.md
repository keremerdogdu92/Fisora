# Monetary Component Reconciliation Implementation Plan

> Execution: `executing-plans`; every behavior task uses RED-GREEN-REFACTOR.

## Goal

Implement the approved source-format-neutral monetary reconciliation layer and
use it to drive V2 accounting-decision relevance and deterministic journal
posting.

Approved design:
`docs/superpowers/specs/2026-08-13-monetary-component-reconciliation-design.md`

## Global constraints

- Preserve all unrelated dirty-worktree changes.
- Keep extraction and account selection separate.
- Do not add parser/Textract fallback or expand the current UI.
- Warnings retain the best available draft.
- Use real domain implementations in tests; fake only paid Gemini HTTP.
- No commit, push, deploy, PR, production mutation, or live paid API call.

## Task 1: Lock the extraction and identity contracts

Files:

- Modify `backend/app/domain/canonical_invoices.py`
- Modify `backend/app/domain/openai_provider.py`
- Modify `backend/tests/test_gemini_invoice_form.py`
- Modify `backend/tests/test_gemini_v2_projection.py`

RED acceptance:

1. Extraction output schema omits all `included_in_*` fields from tax and
   monetary component items.
2. Legacy payloads containing those fields still map successfully.
3. Tax/monetary component IDs remain unchanged when only inclusion hints or
   provider classification change.
4. Prior- and next-period carry components receive signed payable effects and
   remain eligible for a separate account decision.

RED command:

```powershell
python -m unittest backend.tests.test_gemini_invoice_form backend.tests.test_gemini_v2_projection
```

GREEN implementation:

- Remove ambiguous membership properties from the new extraction schema and
  clarify extraction instructions.
- Keep mapper defaults for legacy fields.
- Restrict component identity hashes to observed source fields plus occurrence.
- Normalize carryover kinds/effects without choosing accounts.

## Task 2: Add the pure reconciliation domain

Files:

- Create `backend/app/domain/monetary_reconciliation.py`
- Create `backend/tests/test_monetary_reconciliation_v2.py`

Interface:

```python
def reconcile_monetary_projection(
    projection: Mapping[str, object],
    *,
    max_states: int = 10000,
) -> dict[str, object]:
    ...
```

RED acceptance:

1. The 14.04 + 2.81 + 1.40 + 26.98 + 0.17 - 0.15 example reconciles
   exactly to 45.25.
2. OIV is in `special_tax_total`; radio usage fee is not; both are in payable.
3. An exact subset outranks contradictory legacy inclusion hints.
4. A nonzero residual returns `partial`, keeps the closest selected topology,
   and emits `monetary_reconciliation_residual`.
5. Missing payable returns `not_testable` and still selects known economic
   effects rather than blocking them.
6. Duplicate/represented VAT is never counted twice.

RED command:

```powershell
python -m unittest backend.tests.test_monetary_reconciliation_v2
```

GREEN implementation:

- Parse localized signed money deterministically.
- Build mandatory line/VAT base and optional signed components.
- Use a bounded dynamic-programming subset solver with deterministic
  preference/tie-breaking.
- Enrich each component and emit the reconciliation summary.

## Task 3: Integrate projection, decisions, and journal

Files:

- Modify `backend/app/domain/accounting_projection.py`
- Modify `backend/app/domain/accounting_proposal.py`
- Modify `backend/app/domain/journal_draft_builder.py`
- Modify `backend/app/domain/openai_provider.py`
- Modify `backend/tests/test_gemini_v2_projection.py`
- Modify `backend/tests/test_journal_draft_builder_v2.py`
- Extend `backend/tests/test_monetary_reconciliation_v2.py`

RED acceptance:

1. `build_accounting_projection` emits topology and reconciliation metadata.
2. Only `separate`/unresolved facts consume accounting decision capacity.
3. A known tax effect posts despite unknown legacy subtotal membership.
4. The telecom projection plus real proposal parser and journal builder creates
   visible component lines and a balanced journal at 45.25 payable.
5. A represented/excluded component remains visible as a zero-posting line.

RED command:

```powershell
python -m unittest backend.tests.test_gemini_v2_projection backend.tests.test_journal_draft_builder_v2 backend.tests.test_monetary_reconciliation_v2
```

GREEN implementation:

- Reconcile the assembled projection before returning it.
- Transport only compact posting/reconciliation fields to the second AI.
- Make `posting_requirement` authoritative for decision relevance and journal
  representation.
- Remove the blanket "any unknown inclusion means unknown posting side" gate.

## Task 4: Regression and accounting evidence

Targeted verification:

```powershell
python -m unittest backend.tests.test_gemini_invoice_form backend.tests.test_gemini_v2_projection backend.tests.test_monetary_reconciliation_v2 backend.tests.test_journal_draft_builder_v2 backend.tests.test_accounting_proposal_v2 backend.tests.test_gemini_invoice_pipeline_v2 backend.tests.test_gemini_v2_provider_prompt backend.tests.test_gemini_v2_worker_routing
```

Full stable proof:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

Inspect the telecom acceptance output in the test assertion, not only the test
count: exact reconciliation, 45.25 payable, OIV/radio/carry lines visible, zero
unresolved amount/effect lines, and balanced debit/credit totals.

PostgreSQL live DSN and paid Gemini calls are not required for this local domain
change and must be reported as unverified unless run separately with explicit
scope.
