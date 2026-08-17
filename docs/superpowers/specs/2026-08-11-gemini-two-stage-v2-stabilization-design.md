# Gemini Two-Stage V2 Stabilization Design

Status: Approved

## Goal

Build the production-capable core of the approved Gemini native-PDF two-stage
flow without extending the current V1 orchestration inside the legacy worker.
V2 reuses the parts already proven in isolation, replaces the accounting and
runtime seams that failed the code audit, and remains disconnected from the
production worker until a controlled five-document proof is accepted.

V2 optimizes for a useful accountant draft. Warnings never erase a usable
draft or stop downstream work that can still run. `complete` is a quality label,
not a pipeline gate; incomplete results remain visible as `partial` drafts.

## Transition decision

- Freeze the current Gemini V1 worker orchestration. Do not add behavior to it.
- Do not delete V1 in the first V2 implementation tranche; keeping it
  disconnected makes comparison and rollback possible.
- Build V2 as small domain modules with explicit typed boundaries.
- Do not connect V2 to `process_next_job_once` or production configuration
  until the controlled proof passes and the user explicitly approves routing.
- After V2 acceptance, remove the superseded V1 orchestration in a separate
  cleanup change.
- Do not add parser, Textract, or another extraction fallback.

## Reused components

V2 may reuse these existing components after their scoped contract tests pass:

- Gemini native-PDF transport and secret-safe attempt envelope.
- Canonical invoice form and source evidence links.
- Compact accounting projection.
- Immutable artifact repository and migration.
- Bounded candidate expansion session with at most two extra calls.
- Existing storage, document lifecycle, and active document-processing UI
  payload.

Reusing a component does not mean reusing the V1 orchestration or accepting its
current integration behavior.

## New module boundaries

### `gemini_invoice_pipeline.py`

Owns only stage orchestration:

```text
PDF -> extraction receipt -> canonical revision -> accounting projection
    -> candidate session -> accounting proposal -> journal draft -> quality
```

It receives providers, repositories, tenant identity, source identity, chart
revision, and source bytes through explicit constructor/function arguments. It
does not read the general AI provider chain and does not call legacy PDF
parsers. Each stage returns a result or warning; warnings do not control whether
later stages with sufficient inputs run.

### `accounting_candidate_builder.py`

Builds the real tenant candidate pool.

- Include only active tenant accounts.
- Preserve code, name, role metadata, tax ID, tax office, and candidate origin.
- Put an exact normalized VKN/TCKN counterparty match in the initial pool even
  when it falls outside ordinary family limits.
- Expansion search indexes code, name, aliases, roles, VKN/TCKN, and tax office.
- Keep every previously sent candidate selectable in later rounds.
- Validate only tenant membership, active state, and whether the candidate was
  sent. Do not add a semantic relevance veto.
- One initial call plus at most two expansion calls.

### `accounting_proposal.py`

Defines the second AI's full decision contract. The AI selects accounts; it
does not calculate invoice amounts.

Every proposal addresses these stable decision references when present:

- `counterparty`
- `line:<canonical_line_id>`
- `vat:<vat_group_id>`
- `tax:<tax_component_id>` for non-VAT tax and withholding components
- `monetary:<monetary_component_id>` for accounting-relevant allowances,
  charges, discounts, rounding, carry-forward, and similar components

Each selection is either a sent active tenant candidate, `unresolved`, or—for
the counterparty only—`propose_new`. A response may include a full provisional
proposal and request more candidates at the same time. If a later call fails,
the last successful provisional proposal remains authoritative.

### `journal_draft_builder.py`

Builds journal lines deterministically from canonical amounts plus the AI's
account selections.

- Never use AI-supplied amounts as accounting truth.
- Preserve every canonical line, VAT group, non-VAT tax component, withholding,
  and accounting-relevant monetary component exactly once.
- Deduplicate VAT represented both in a VAT summary and tax component list by
  canonical identity; never post the same VAT twice.
- Derive debit/credit from invoice direction and the canonical component's
  economic effect. Purchase withholding reduces counterparty payable and is a
  credit-side liability; the sales direction is mirrored according to the
  canonical effect.
- Never double-post a discount or charge already included in a canonical net
  amount. The projection must carry inclusion/effect metadata; uncertain
  inclusion produces a warning and an explicit unresolved draft component.
- Missing account selection creates an unresolved draft line with its amount
  and decision reference intact; it does not delete the draft.
- Produce `total_debit`, `total_credit`, and `is_balanced` from Decimal amounts.

### `accounting_quality.py`

Evaluates output without mutating it.

`complete` requires all of the following:

- every required decision reference is represented;
- every selected existing account is active, belongs to the tenant, and was
  sent to the AI;
- there are no unresolved journal accounts;
- all canonical line, VAT, tax, withholding, and monetary component identities
  are represented exactly once;
- debit equals credit at currency precision;
- counterparty action is either a valid existing selection or a preserved
  `propose_new` suggestion.

Otherwise the result is `partial` with concise warnings and the best available
draft. Quality evaluation never suppresses artifact persistence or draft
creation. Approval and export policy remain outside V2.

## Runtime separation

The dedicated Gemini PDF runtime is configured independently from the general
accounting/provider chain. A valid dedicated Gemini configuration must be able
to construct the V2 extraction provider even when Gemini is absent from the
general `FISORA_AI_PROVIDER_CHAIN`.

Missing V2 dependencies produce an explicit unavailable/retryable result. They
must not route the document into the legacy parser or Textract path.

## Artifact and lineage corrections

All four artifacts remain append-only: provider receipt, canonical form,
accounting projection, and accounting proposal.

Lineage scope equality includes:

- tenant ID;
- taxpayer ID;
- document ID;
- source file ID;
- source file SHA-256.

Both local validation and the PostgreSQL trigger enforce the same rule. A
proposal derived from a successful provisional response links to that
successful receipt; a later failed expansion receipt remains linked as a failed
expansion attempt, not as the proposal's authority.

## Idempotency and retry

Extraction identity includes source ID/hash, provider, resolved model, prompt,
schema, and pipeline version. Accounting identity additionally includes the
canonical revision, tenant chart revision, candidate-builder version, and
client-context revision.

A changed source hash never reuses or links to the old source's artifacts. A
failed retry never overwrites the previous valid canonical form, proposal, or
draft.

## UI contract

V2 adds no UI surface. Its adapter preserves the current active document screen
contract, including `issue_date`, structured `decision_narrative`, selected
account names/codes, new-counterparty suggestion, warnings, and draft lines.
Raw receipts remain backend/debug artifacts.

## Controlled proof and reporting

The first runnable proof uses the existing five-document set and a real tenant
chart. The paid Gemini HTTP boundary may be replaced only in automated tests;
the controlled proof uses the live provider when credentials are explicitly
available.

Per document, report:

- extraction and accounting artifact lineage;
- line, party/VKN, VAT, non-VAT tax, withholding, monetary-component, and total
  identity preservation;
- initial and expansion candidate rounds;
- selected candidate origin round;
- unresolved decisions and warnings;
- debit, credit, and balance;
- latency, tokens, and estimated cost;
- `complete` or `partial` status.

The aggregate cannot be `OK` if any document is `partial`, unbalanced, missing a
required canonical identity, or built without current-run artifacts. A partial
document still retains its useful draft and warning evidence.

## Failure behavior

- Extraction call failure: persist the failed receipt; do not fabricate a
  canonical form. Preserve the previous valid revision when one exists.
- Canonical/projection warning: persist facts and continue with all usable data.
- Accounting call failure after a successful provisional response: persist the
  failed receipt and keep the last successful proposal/draft.
- Empty expansion: add a warning and continue with the accumulated candidate
  pool.
- Expansion limit reached: finalize the best available proposal as complete or
  partial; never mark the document processing itself failed solely for this.
- Quality failure: retain draft and artifacts as `partial`; do not silently
  promote it to `successful/OK`.

## Non-scope

- Production worker routing or feature-flag activation.
- Parser/Textract/provider fallback.
- Auto-approval, auto-export, or legal/export blocking policy.
- New active-screen UI.
- Long-term retention policy.
- Automatic creation of a new counterparty.
- Removal of legacy V1 orchestration before V2 proof acceptance.

## Acceptance criteria

1. Dedicated Gemini runtime is independent of the general provider chain.
2. Inactive accounts cannot enter any candidate round.
3. Exact VKN/TCKN matches are present initially and discoverable in expansion.
4. Full proposals cover counterparty, every line, VAT, non-VAT tax,
   withholding, and accounting-relevant monetary component.
5. Journal construction neither loses nor duplicates a canonical accounting
   fact and correctly represents withholding direction.
6. Every draft reports debit, credit, and balance.
7. Incomplete or unbalanced results remain useful `partial` drafts and cannot
   be reported as complete/OK.
8. Artifact lineage rejects a parent with a different source hash in local and
   PostgreSQL lanes.
9. The runner verifies monetary components and current-run artifact lineage.
10. No V2 code path calls the legacy PDF parser or Textract.
11. No production worker connection, commit, push, or deploy occurs in this
    implementation tranche.
