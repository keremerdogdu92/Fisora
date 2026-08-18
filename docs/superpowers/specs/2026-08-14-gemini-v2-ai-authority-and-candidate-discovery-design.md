# Gemini V2 AI Authority and Candidate Discovery Design

Status: Approved

This document is an approved addendum to
`docs/superpowers/specs/2026-08-14-gemini-v2-corpus-hardening-design.md`.
Where the two documents differ, this addendum governs AI semantic authority,
candidate expansion, zero-amount decisions, monetary/tax treatment, semantic
warnings, and the next real-corpus experiment. Existing immutable evidence,
tenant integrity, decision-capacity, lineage, and no-fallback constraints remain.

## Goal

Let the accounting AI work with progressively broader access to the tenant's
real chart without allowing deterministic heuristics to silently replace its
semantic choices. Preserve every useful draft, expose disagreements as evidence,
and measure whether exhaustive candidate access improves quality enough to
justify its latency, token, and quota cost.

## Authority boundary

The accounting AI owns:

- real account choice among candidates sent for the decision;
- special-tax accounting treatment;
- monetary-component inclusion and payable effect;
- the final semantic choice when a deterministic expectation disagrees.

The deterministic layer owns:

- immutable canonical identities and observed amounts;
- tenant, taxpayer, active/detail, and sent-candidate integrity;
- arithmetic reconciliation and alternative hypotheses;
- structured conflict evidence and warnings;
- draft totals, balance calculation, lineage, and audit history.

A deterministic semantic expectation never substitutes its preferred account or
treatment for a valid AI choice. A disagreement keeps the AI choice in the draft
and emits a warning. Warnings do not erase or stop the draft.

An accountant's approved decision is final. Historical AI choices, conflicts,
and warnings remain auditable but do not block export after accountant approval.

## Hard integrity boundaries

The final broad candidate round does not relax these constraints:

- no cross-tenant or cross-taxpayer candidate;
- no inactive or non-detail account;
- no candidate that was not sent in that provider call;
- no invented candidate ID or account code;
- no AI mutation of canonical fact IDs, rates, or source amounts;
- no parser, Textract, or silent provider fallback;
- no automatic counterparty creation.

## Zero-amount decisions

Zero-amount VAT, tax, and monetary facts remain visible in the compact projection
and receive an explicit AI decision. Fact decisions add the action:

```text
no_separate_posting
```

The action is accepted only when the canonical posting amount is exactly zero.
For this exact case, the compatibility normalizer also maps the already-observed
provider shape `select_existing` plus an empty `selected_candidate_id` to
`no_separate_posting`. The raw response remains immutable.

The same shape for a non-zero fact is invalid and cannot suppress a real amount.
It produces a decision-level validation issue while other valid decisions remain.

Fact actions have these exact meanings:

```text
select_existing      = a sent real account is selected
represented          = a non-zero fact is represented by another canonical fact
excluded             = a non-zero monetary fact is excluded from the current posting
no_separate_posting  = an exactly zero fact needs no account line
unresolved           = no valid decision is available
```

`represented` and `excluded` are not aliases for the zero-only
`no_separate_posting` action. They require explicit representation or exclusion
evidence in the proposal and remain visible in the draft topology.

## Partial proposal parsing and last-valid preservation

Provider output is parsed per decision reference rather than as one all-or-nothing
proposal.

- Valid decisions are retained even when another decision is malformed.
- Every invalid decision stores a sanitized validation issue linked to the raw
  receipt, round, chunk, and decision reference.
- A later invalid decision does not overwrite an earlier valid AI decision for
  the same reference.
- The merged proposal uses the latest valid decision per reference and emits
  `latest_ai_decision_invalid` and `using_last_valid_ai_decision` when applicable.
- If no valid decision exists for a required reference, only that reference is
  unresolved; successful extraction and other draft lines remain.

## Progressive candidate universe

`real_candidates` is the complete stable set of active, detail, tenant-owned
chart accounts. Sent candidates accumulate by candidate ID; a later round never
removes an earlier candidate.

### Round 0: focused

Use the existing 40-candidate focused slice, improved by exact counterparty,
direction, VAT-rate, tax-label, and role coverage. These are ranking signals,
not permanent semantic vetoes.

### Round 1: broad discovery

Accumulate a stable relevance-ranked slice covering at least half of the real
candidate universe. Include unseen account families, generic accounts, accounts
with incomplete semantic metadata, AI search-term matches, and alternate role
hypotheses. The target is `max(80, ceil(universe_count / 2))`, capped by the
universe and request-size budget.

### Round 2: exhaustive discovery

Accumulate the entire active/detail real candidate universe when it fits the
accounting request budget. No account is hidden because its inferred role, VAT
rate, or tax kind conflicts with a deterministic expectation.

The request-size ceiling is 3,000,000 serialized UTF-8 bytes, configurable by
`FISORA_GEMINI_V2_MAX_ACCOUNTING_REQUEST_BYTES`. If the full request cannot fit,
the stable relevance order is used up to the ceiling and the receipt records
`candidate_universe_truncated`, universe count, sent count, and coverage ratio.
Truncation is never silent.

## Candidate discovery modes

Two modes share the same proposal and integrity contract:

- `adaptive`: preserve the current production-like behavior; expand only when
  the AI requests more candidates.
- `exhaustive`: execute all three rounds for every active accounting chunk even
  when an earlier round reports sufficient candidates.

The next real-corpus test round uses a deterministic 50/50 experiment:

```text
control    = adaptive
experiment = exhaustive
```

Assignment is stable within taxpayer scope:

```text
sha256("{taxpayer_id}:{document_id}:candidate-discovery-v1") % 100 < 50
```

The exhaustive behavior is test-round-only. It does not become the production
default. The result of that round determines whether later tests or production
use adaptive, exhaustive, or another measured policy.

## Semantic conflict evidence

Every valid AI selection is applied to the draft. A deterministic disagreement
adds a structured conflict record with:

```text
decision_ref
conflict_code
deterministic_expectation
ai_selection_or_treatment
ai_reason
candidate_round_index
candidate_id
source_evidence_refs
```

Examples include `vat_rate_semantic_conflict`, `tax_treatment_conflict`, and
`monetary_effect_conflict`. These are review warnings, not draft blockers and
not deterministic account overrides.

## VAT decisions

VAT candidate ranking is progressive:

1. exact normalized rate and document direction;
2. direction-compatible general VAT accounts and accounts whose rate metadata
   is unknown;
3. the full active/detail tenant chart in exhaustive round 2.

If the AI finally chooses an explicitly different VAT rate, the selected account
remains in the draft and `vat_rate_semantic_conflict` records both rates and the
AI reason.

## Special-tax treatment

Canonical tax observations preserve source label, source code, rate, taxable
amount, tax amount, evidence, and normalized kind. The canonical kind does not
silently dictate the journal account.

For every non-VAT tax decision the accounting AI returns `selected_treatment`
from:

```text
deductible_tax
expense_or_cost
payable_withholding
represented_in_line
no_separate_posting
other
```

The blanket inference `360* => special_tax` is removed. Tax kind, direction,
source label, and account role rank early candidates. The AI may choose a
different treatment or account in a broader round; the choice is retained with
`tax_treatment_conflict` when it disagrees with deterministic evidence.

`represented_in_line` uses fact action `represented`. Zero-only
`no_separate_posting` uses the action and treatment of the same name. Treatments
that create a separate posting use `select_existing` and require a sent account.

## Monetary-component treatment

Canonical monetary facts preserve the observed label and amount. Reconciliation
builds source-backed alternative topologies using explicit components,
`allowance_total`, and de-duplicated named totals.

For every accounting-relevant monetary decision the AI returns
`selected_treatment` from:

```text
increase_payable
reduce_payable
represented
excluded
no_separate_posting
other
```

Reconciliation reports which topology best matches observed payable and its
residual, but does not replace the AI treatment. A conflicting treatment remains
in the draft and emits `monetary_effect_conflict` plus the resulting residual or
balance warning. Canonical amounts remain immutable.

Monetary treatment `represented` uses fact action `represented`; treatment
`excluded` uses action `excluded`; zero-only `no_separate_posting` uses the action
of the same name. Treatments that create a separate posting use
`select_existing` and require a sent account.

## Prompt caching readiness

Explicit Gemini cache creation is deferred until the candidate experiment has
measured the repeated context. This phase:

- places stable instructions, projection, and accumulated candidate catalog in
  a stable common prefix;
- places round/chunk-specific decision references and schema variation after the
  shared content where the API contract permits;
- records `cachedContentTokenCount` and any cache diagnostics from usage metadata;
- reports cache-hit tokens, latency, and estimated cost by experiment group.

No result may depend on a cache hit. A cache miss changes only cost and latency.

## Runtime and status hardening

- Transient PostgreSQL operational/connection failures become bounded retryable
  technical failures; integrity and schema failures remain permanent.
- A bounded process-local PostgreSQL connection pool replaces repeated direct
  connections without holding a transaction during Gemini HTTP waits.
- Later attempts link to failed provider receipts through `retry_of_artifact_id`.
- Result reporting separates processing, extraction validation, reconciliation,
  accounting decision, draft balance, review, and export states.
- Derived line-to-VAT linkage is stored outside immutable extraction and reports
  factual contradiction separately from missing or derived evidence.

## Next-round measurements

The external real-corpus runner reports control and experiment separately:

- documents and chunks per group;
- round 0 to round 1 to round 2 selection changes;
- improved, degraded, unchanged, and conflict-producing selections;
- candidate universe count, sent count, coverage, and truncation;
- valid, invalid, normalized, and last-valid-reused decisions;
- balanced drafts, residuals, zero-draft documents, and semantic warnings;
- provider calls, HTTP status, retries, wall time, and per-document latency;
- prompt, output, cached, and total tokens;
- list-price estimate and cache-adjusted estimate;
- quality gain or loss per added call and per added million input tokens.

## Acceptance criteria

1. Zero-amount facts can return `no_separate_posting` without invalidating their
   chunk; non-zero facts cannot use it to suppress an amount.
2. One malformed decision never erases valid decisions, canonical extraction,
   or useful draft lines.
3. A later malformed decision preserves the last valid AI decision with explicit
   warning and receipt lineage.
4. Exhaustive round 2 exposes the full active/detail tenant chart when within the
   request budget and reports exact coverage otherwise.
5. A valid AI choice that conflicts with VAT, tax, or monetary expectations is
   used in the draft and produces structured evidence rather than an override.
6. Accountant approval is final and permits export regardless of historical
   semantic warnings.
7. The next real-corpus run produces a deterministic 50/50 adaptive/exhaustive
   comparison with complete call, token, cache, latency, cost, and quality data.
8. Default production-like behavior remains adaptive; exhaustive does not remain
   enabled automatically after the experiment.

## 2026-08-17 approved AI-result resolution amendment

This amendment governs treatment applicability, targeted clarification, and the
review representation of incomplete AI decisions. It does not weaken immutable
receipts, canonical facts, sent-candidate integrity, per-reference parsing, or
semantic-conflict evidence. Where this amendment differs from earlier treatment
or parsing language in this document, this amendment governs.

### Treatment applicability

- Line and VAT decisions ask the AI only for account selection.
  `selected_treatment` is non-operative for these roles.
- A provider-supplied line or VAT treatment does not discard an otherwise valid
  `select_existing` decision with a sent candidate. The raw response remains
  immutable and the normalized decision stores a decision-level warning.
- Every non-zero non-VAT tax and accounting-relevant monetary fact requires an
  operative `selected_treatment` because it controls posting topology or payable
  effect.
- Exactly zero VAT, tax, and monetary facts use `no_separate_posting` under the
  existing zero-amount integrity rule.
- Deterministic reconciliation may expose alternatives and conflicts but never
  silently supplies a missing tax or monetary treatment.

### Bounded targeted clarification

When a non-zero tax or monetary decision selects a valid sent candidate but its
treatment is missing or invalid, the account selection is preserved and only
that decision reference enters one bounded clarification cycle.

- The clarification asks for a complete corrected decision for that reference.
- The AI may request broader real candidates; any expansion remains subject to
  the existing tenant, taxpayer, active/detail, accumulated-candidate, round,
  request-size, and truncation rules.
- Clarification never becomes an unbounded retry loop.
- A valid clarified decision supersedes the incomplete decision with receipt and
  retry lineage preserved.

If clarification does not produce a complete decision, the valid account remains
visible as an accountant suggestion. The affected fact creates no automatic
financial posting, the other valid decisions remain, and the document has the
single user-facing state `review_required`. This is not an `unresolved_account`:
the account is known, but its posting topology still needs review.

### Integrity and last-valid meaning

Unknown, missing, unsent, inactive, non-detail, cross-tenant, or cross-taxpayer
candidates; unknown decision references; and non-zero `no_separate_posting`
remain hard per-reference integrity failures. Semantic disagreements remain
warnings with the valid AI selection retained.

`last valid` means structurally and integrally valid, not accountant-confirmed
semantic correctness. Reuse always retains the later invalid receipt, explicit
warning, and lineage.

### Additional acceptance criteria

9. A non-operative line or VAT treatment never turns a valid sent account
   selection into an unresolved decision.
10. A non-zero tax or monetary selection without an operative treatment receives
    at most one targeted clarification cycle and never receives a silent
    deterministic treatment fallback.
11. Failed clarification preserves the selected account as a review suggestion,
    creates no automatic posting for that fact, and does not emit
    `unresolved_accounts` solely because treatment is incomplete.
12. Candidate expansion during clarification obeys the existing discovery and
    request-budget boundaries.
13. User-facing status remains `review_required`; decision-level reason and
    receipt lineage stay available for audit and measurement.

### External verification request-call bound

The isolated external runner configures a hard per-document budget of nineteen
accounting-provider calls, shared by ordinary candidate rounds and treatment
clarifications across every decision-capacity chunk. Together with the single
extraction call, this makes the runner's twenty-call scheduling reservation a
real upper bound even when a document contains more than eight facts. Budget
exhaustion preserves completed decisions, stops further provider calls, and
leaves remaining work partial and review-required. The production default does
not enable this external-test-only cap.

## Non-scope

- Enabling explicit Gemini cached-content resources by default.
- Changing the global/V1 model default.
- Increasing the one-counterparty plus eight-fact decision capacity.
- Silent parser/provider fallback.
- Automatic accountant approval, automatic counterparty creation, commit, push,
  deploy, or production mutation.

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
