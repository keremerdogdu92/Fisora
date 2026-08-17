# Gemini V2 Corpus Hardening Design

Status: Approved

## Goal

Strengthen the native-PDF V2 pipeline from the real 365-PDF corpus findings
without adding invoice-specific patches, parser fallback, UI expansion, or a
new accounting authority. Preserve useful drafts and immutable evidence while
improving correctness, audit lineage, retry recovery, wall-clock latency, and
machine-resource use.

## Approved constraints

- Extraction observes document facts; account selection remains a separate AI
  stage using only active, sent tenant candidates.
- Warnings never erase a useful draft.
- No parser or Textract fallback.
- No automatic account/counterparty creation or export approval.
- Keep the existing document UI contract.
- Keep the accounting decision capacity at one counterparty plus at most eight
  fact decisions per call.
- Tests and live Gemini/corpus runs are prepared for another agent; this
  implementation session does not execute them.
- No commit, push, deploy, production mutation, or paid API call.

## Fact-aware candidate coverage

The 40-account initial pool is allocated from document requirements instead of
being filled by one globally role-ranked list.

The builder first reserves:

1. every exact normalized counterparty tax-ID match;
2. one line account for the active direction;
3. at least one tenant VAT account matching every distinct canonical VAT rate;
4. source-label/kind matches for every non-VAT tax component;
5. one generic candidate for every remaining required role.

The remaining budget is filled by deterministic round-robin across roles, then
by the existing stable ranking. A VAT rate is derived from explicit chart
metadata first and an explicit percentage in the account label second. A code
suffix alone is not authoritative. The AI may still request expansion and may
select any accumulated active sent candidate; no semantic veto is added.

## Named totals and payable authority

Extraction returns every visibly named total as an observed fact:

```text
source_label + amount + source_position + evidence + proposed_role
```

`proposed_role` is an extraction-stage semantic observation such as
`payable_total`, `tax_inclusive_total`, `goods_services_total`, or `other`; it
is not an accounting decision. Existing fixed total fields remain readable for
backward compatibility.

The canonical mapper retains all named totals and resolves the working payable
using evidence in this order:

1. a uniquely evidenced explicit amount-due/payable label;
2. an extraction-proposed payable role whose label is payable-compatible;
3. the legacy observed payable field;
4. a uniquely reconciling named total.

Generic labels such as general total or tax-inclusive total cannot override an
explicit amount-due label. Conflicting equally authoritative payable facts are
preserved with `payable_total_ambiguous`; the best source-backed draft remains
available rather than being deleted.

## Source-backed reconciliation baseline

Mandatory goods/service value is resolved independently from VAT and special
taxes. Evidence priority is:

1. complete canonical line taxable amounts;
2. an explicit goods/services or tax-exclusive named total;
3. complete, non-overlapping VAT taxable bases;
4. visible line amounts whose sum differs from the selected base only by a
   bounded currency-rounding delta.

Visible source lines remain separate facts. A bounded cent difference is
recorded as an explicit allocation adjustment; descriptions or line IDs are
never merged. If no source-backed baseline exists, the closest topology and an
unresolved aggregate base are retained with warnings.

This permits a document such as 703.33 base + 140.67 VAT + 66.00 special tax =
910.00 payable while preserving two visible lines whose printed amounts sum to
703.34 and exposing the one-cent allocation difference.

## Complete component lineage

Successful accounting receipts are accumulated in stable round/chunk order.
Expansion never overwrites an earlier successful receipt reference. The final
proposal links to every successful component receipt from which the merged
proposal history was produced; the last successful receipt remains the direct
provider receipt authority. Failed receipts remain separate failed attempts.

## Compatibility retry parity

The PostgreSQL compatibility claim query accepts:

- `queued`; or
- `retry_wait` with a valid `next_attempt_at <= now()`.

Missing or malformed retry timestamps are not claimed. Claim remains an atomic
`FOR UPDATE SKIP LOCKED` update and mirrors JSON/normalized retry behavior.

## Performance and resource model

### Provider and connection reuse

Build one Gemini V2 runtime per worker process and reuse its thread-safe
`httpx.Client` connection pool across slots and jobs. Do not construct a new
provider for every document. This also gives every slot and chunk one shared
process-local request governor.

### Adaptive queue draining

When a tick processes work, immediately continue draining the queue instead of
sleeping for the full idle interval. When idle, use bounded adaptive backoff to
avoid hot polling while keeping new-document pickup latency low. Retention
cadence remains wall-clock based and is not accelerated by a busy loop.

### Bounded chunk concurrency

Within one accounting round, chunks share an immutable candidate snapshot and
may execute concurrently up to an explicit resource limit. Receipt persistence,
proposal parsing, warning collection, expansion-term merging, and final merge
occur afterward in stable chunk order. Thus scheduling cannot change the
result order or candidate pool.

Concurrency is disabled at `1` by default in the pure pipeline and enabled by
worker configuration. A process-wide Gemini request governor caps request
starts per minute across worker slots and chunk calls. Increasing concurrency
can overlap network wait but cannot exceed the configured provider quota.
429 responses remain retryable evidence, never a silent fallback.

## Non-scope

- Increasing per-call accounting fact capacity.
- Batching multiple documents into one Gemini request.
- Reducing extraction/accounting evidence sent to Gemini.
- Adding timeouts as a performance mechanism.
- Files API caching or cross-document response caching.
- Corpus completion and repeatability execution in this session.

## Acceptance criteria

1. Every canonical VAT rate with a matching active tenant account has a
   matching initial candidate even when many counterparty accounts exist.
2. Explicit amount-due evidence outranks a conflicting general total while all
   named totals remain auditable.
3. A source-backed VAT base can preserve a useful line allocation and exact
   payable reconciliation with an explicit cent adjustment.
4. Final proposal lineage includes every successful accounting receipt.
5. Due compatibility retries are atomically reclaimable; future retries are
   not.
6. Parallel and sequential chunk execution produce the same ordered proposal,
   warnings, candidate expansion, and lineage set.
7. Provider reuse and adaptive draining reduce setup/polling overhead without
   changing accounting output.
8. Resource limits are explicit and bounded; no unbounded thread creation or
   busy polling is introduced.
