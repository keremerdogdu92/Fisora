# Protected Accountant Reference Corpus Design

## Status

Accepted for implementation planning on 2026-07-21. This document records the
agreed design only. It does not authorize code changes, production reset,
commit, push, deploy, or real-invoice upload.

## Problem

Fisero needs a durable, versioned set of 50 real invoices (target 35 purchase
and 15 sales) with accountant-approved reference outcomes. The accountant will
review Fisero's draft in the existing review flow, correct it, and make the
final result the authoritative reference. Confirmed corrections may also create
reusable learning rules.

The current tenant-wide `TEMIZLE` action preserves accountant/admin identities
but deletes clients, documents, journals, review decisions, learning records,
and stored document/export files. The current backup job creates a PostgreSQL
dump and a document path/size manifest; the manifest is not a source-file
backup. Real accountant work must not begin while those two gaps remain.

## Decision

Build a dedicated protected corpus boundary backed by PostgreSQL and a separate
protected source-file root. Corpus sources, canonical evidence, reference
outcome versions, and confirmed rule snapshots are reset-exempt. The ordinary
review UI remains the accountant's working surface; corpus administration is an
accountant/admin backend operation for the first pilot.

The final live reset happens only after this protection is deployed and proven
with non-real fixtures. Real UBL files are uploaded only after backup and
restore evidence passes.

## Alternatives Rejected

### Backup before every reset

Rejected as the primary control. A whole-database restore also restores
unwanted trial data and cannot express which accountant decisions are durable.
Backup remains a disaster-recovery layer.

### Separate benchmark tenant or database

Deferred. It gives strong isolation but duplicates tenant setup, account plans,
authorization, and operations before the first 50-invoice corpus needs it.

### Boolean protection flags only on operational rows

Rejected. Reset and retention cascades span sources, documents, canonical
lines, journals, decisions, rules, taxpayers, and filesystem objects. A flag on
one operational row cannot preserve a reproducible reference package safely.

## Protected Data Model

### Corpus

A corpus has a stable key, integer version, target purchase/sales counts, and
`draft`, `frozen`, or `archived` status. A frozen version is immutable.

### Corpus item

Each item is tenant- and taxpayer-scoped and unique by source SHA-256 within a
corpus version. It records direction, source identity, immutable protected
storage locator, source provenance, canonical extraction snapshot, chart-plan
snapshot, and current authoritative reference version.

Enrollment copies the source bytes into a protected storage root using an
atomic write, recalculates SHA-256, and refuses a mismatch. Merely storing a
path or manifest is insufficient.

### Reference outcome version

An accountant's final review creates an append-only reference version. It
stores the proposal snapshot, accountant final decision, quality delta,
balanced journal snapshot, canonical-line allocation snapshot, quality label,
reviewer, reason, and relevant prompt/provider/pipeline versions. A later
correction appends version N+1 and never rewrites version N.

Only an explicit final accountant action may become authoritative. Mechanical
guards still require canonical evidence, balanced debit/credit, real chart
accounts, and complete line allocation. `review_required` is not itself a
successful reference outcome.

### Protected rule version

Ordinary review may create learning evidence or a rule candidate. A protected
rule version is created only after the existing explicit accountant
confirmation path establishes its scope and meaning. It keeps the originating
reference version, taxpayer/counterparty/product scope, account binding,
status, and version history.

Reset does not erase protected rule versions. If their original taxpayer is
later recreated, Fisero must require an explicit reviewed rebind; matching a
VKN must not silently reactivate a detached client-specific rule.

## State Flow

1. Create corpus version in `draft`.
2. Upload a UBL through the existing intake path.
3. Enroll the document into the corpus immediately after selection.
4. Copy and hash-verify the source under protected storage.
5. Process the invoice through the normal canonical and accounting pipeline.
6. Let the accountant approve or correct the draft in the existing review UI.
7. Capture an append-only reference version from the saved final decision.
8. Persist learning evidence; protect a rule only after explicit confirmation.
9. Freeze the corpus only when it contains exactly 35 purchase and 15 sales
   authoritative items, every source is available and hash-valid, and every
   reference meets the accounting evidence contract.

## Reset Contract

The existing route and confirmation text remain backward compatible, but reset
becomes fail-safe:

- preview reports ordinary rows/files to delete and protected rows/files to
  preserve;
- protected corpus tables and protected source root are never touched;
- protected rule versions are never touched;
- ordinary operational projections may be cleared without deleting the
  versioned corpus snapshots;
- any dependency that cannot be safely separated blocks reset before the first
  delete rather than partially clearing the tenant;
- protected-corpus deletion is a separate, explicit, authorized, audited
  operation and is not part of this implementation slice.

The settings UI does not gain new corpus controls in this slice. Its existing
reset action continues to work against the safer backend contract.

## Benchmark Integrity

The same accountant reference is reused across provider comparisons. Provider
runs cannot mutate the source, reference, current operational draft, rules, or
export batches.

Cold-start quality and learning quality remain separate:

- provider quality uses frozen source, canonical, prompt/schema, chart, and rule
  snapshots;
- chronological learning evaluation applies confirmed rules only to later
  eligible invoices;
- a rule learned from an invoice cannot be credited for fixing that same
  invoice.

## Backup and Restore Contract

Before real uploads:

- PostgreSQL and protected source bytes are included in the same timestamped
  backup set;
- the set contains SHA-256 manifests, not only path/size manifests;
- an encrypted copy is written to an off-host target;
- encryption key material remains outside the server backup set;
- an isolated restore reconstructs source bytes, corpus metadata, canonical
  snapshots, reference versions, and protected rules;
- application-level verification recomputes hashes and checks tenant boundaries
  and the authoritative journal/rule links.

## Initial Pilot Operating Sequence

1. Keep received UBL ZIP files outside Fisero and do not upload them yet.
2. Implement and locally verify corpus, reset, and backup/restore protection.
3. Complete the separate release approval transaction.
4. Deploy and prove protection with non-real fixtures.
5. Inventory live records and create a recoverable pre-reset snapshot.
6. Obtain explicit destructive approval and perform one final live reset.
7. Recreate/verify pilot clients and real chart plans.
8. Upload UBL files, enroll selected items, and begin accountant review.
9. Freeze version 1 only after the 35/15 and accounting-quality gates pass.

## Acceptance Criteria

- Protected source bytes survive reset and retain the same SHA-256.
- Protected corpus metadata, reference versions, and confirmed rules survive
  reset while ordinary trial records/files are removed.
- A failed separation check causes zero deletions.
- A later accountant correction creates a new authoritative version without
  changing the prior version.
- An unconfirmed rule candidate never becomes protected or active.
- Every authoritative journal is balanced, uses real usable chart accounts, and
  covers every canonical line exactly once.
- Tenant A cannot read, enroll, freeze, reset, or restore Tenant B's corpus.
- Duplicate source hashes cannot create two corpus items in one corpus version.
- A benchmark run cannot alter operational drafts or create an export batch.
- An isolated encrypted backup restore passes source-hash, journal, rule, and
  tenant-integrity checks.

## Non-Scope

- A new accountant-facing corpus dashboard.
- Automatic selection of the best 35/15 from an unsorted archive.
- Provider admission or production-quality claims before accountant parity.
- Permanent deletion of a protected corpus.
- Direct Zirve delivery.

