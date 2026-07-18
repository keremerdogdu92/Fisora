# Fisero System Architecture Document

Status: Canonical target architecture
Version: 1.0
Date: 2026-07-18
Owners: Fisero engineering
Product contract: `01-product-requirements-document.md`

## 1. Purpose

This document defines:

- the architecture that exists in the repository today;
- the changes required before persistent real-accounting use;
- the boundaries reserved for later scale and direct Zirve delivery.

It does not claim that a target component is implemented merely because a table,
interface or test scaffold exists.

## 2. Architecture principles

1. PostgreSQL owns durable accounting truth.
2. Original source evidence is immutable.
3. Canonical invoice data and accountant-editable journals are separate.
4. AI produces structured proposals; deterministic code owns mechanical gates.
5. Approved journal revisions cannot be overwritten.
6. Every accepted source and job transition is idempotent and recoverable.
7. Tenant/client authorization is applied at every boundary.
8. Variable AI and workflow evidence may use JSONB, but core accounting truth
   remains relational.
9. Operational events are append-oriented; they are not a second writable
   projection of the same journal.
10. The pilot uses a modular monolith plus independent workers. Microservices
    are introduced only when a measured boundary requires them.

## 3. Current repository architecture

### 3.1 Runtime topology

The production compose stack currently contains:

- Nginx reverse proxy;
- Next.js 16 / React 19 frontend;
- FastAPI backend;
- Python document worker;
- PostgreSQL 16;
- Redis 7;
- backup container/job support.

The backend and worker share domain and persistence code. QNB synchronization
and document processing have claim/lease behavior. The worker supports
configurable parallel document slots.

### 3.2 Current persistence truth

`backend/db/schema.sql` contains normalized tables including:

- tenants and taxpayers;
- portal users and client access;
- chart imports and chart accounts;
- documents and invoice lines;
- counterparties;
- journal entries and lines;
- review decisions;
- learning rules;
- export batches.

However, the active PostgreSQL adapter intentionally preserves the older JSON
workspace contract through `workflow_records`. Live uploads, processing jobs,
document results, review decisions, learning events and pipeline evidence are
largely written as typed JSONB records. The normalized accounting tables are
therefore not yet the authoritative end-to-end write path.

Today:

- source bytes are written to document storage;
- upload metadata is stored as `uploaded_document`;
- processing claims a `processing_job`;
- AI/accounting results are stored in a `document.result` JSON object;
- proposed journal lines live in `result.draft_lines`;
- review mutates the stored document result and adds a review record;
- export reconstructs a journal from the current JSON draft.

This is acceptable for disposable development data. It is not the persistent
pilot target.

### 3.3 Current strengths to preserve

- Working invoice parsing and accounting simulation.
- Direction-aware chart/counterparty selection.
- Mixed-VAT and line-level accounting foundations.
- QNB SOAP synchronization, identity/deduplication and scheduling foundations.
- Provider chain, research harness and AI usage visibility.
- Review, learning and audit-event foundations.
- PostgreSQL job claim using `FOR UPDATE SKIP LOCKED`.
- Production compose, health/readiness, smoke and backup foundations.

## 4. Persistent-pilot logical architecture

```text
Client portal / Accountant portal / QNB scheduler
                       |
                    Nginx
                       |
              FastAPI application API
       +---------------+----------------+
       |               |                |
  Intake service   Review service   Operations/Auth
       |               |                |
       +----------- PostgreSQL ----------+
                       |
                 Durable job queue
                       |
              Document worker slots
       +---------------+----------------+
       |               |                |
  Canonical parser  AI accounting   Research adapter
       |               |                |
       +--------- Journal builder -------+
                       |
             Deterministic hard gates
                       |
            Reviewable/approved journal
```

The pilot remains one deployable backend codebase with explicit module
boundaries. The worker is a separate process/container because document
processing is long-running and failure-isolated.

## 5. Target data ownership

### 5.1 Core entities

| Entity | Authoritative owner | Notes |
| --- | --- | --- |
| Office/tenant | `tenants` | Security and commercial boundary |
| Client/taxpayer | `taxpayers` | Verified identity/activity profile |
| Portal identity/access | `portal_users`, access table | Permission-scoped |
| Chart import | `chart_account_imports` | Immutable import provenance |
| Chart account | `chart_accounts` | Current client-owned usable plan |
| Source file | `source_files` target table | Immutable bytes/hash/storage lifecycle |
| Accounting document | `documents` | Real invoice identity and direction |
| Source relationship | `document_sources` target table | PDF/XML/additional evidence |
| Canonical line | `invoice_lines` | Stable line identity and source position |
| Counterparty binding | `counterparties` | Client-specific identity/account match |
| Processing attempt | `processing_jobs` target table | Claim, retry and metrics |
| AI/provider attempt | `ai_attempts` target table | Provider/model/schema/evidence |
| Journal | `journal_entries` | Current working/approved accounting record |
| Journal line | `journal_entry_lines` | Debit/credit and canonical-line allocation |
| Journal revision | target revision table or revision columns | Immutable approved snapshots |
| Review decision | `review_decisions` | Actor, action, reason and base revision |
| Learning rule | `learning_rules` plus version/history | Scope, trigger, meaning and binding |
| Workflow/audit event | target append-oriented event table | Diagnostics and accountability |
| Export/delivery | export/delivery tables | Later external idempotency/reconciliation |

### 5.2 Relational versus JSONB

Relational columns are mandatory for:

- tenant/client/document relationships;
- tax identity, invoice number/date/direction;
- canonical line identity and monetary values;
- account codes and chart references;
- journal debit/credit lines;
- revision, approval and export eligibility;
- rule identity, scope and lifecycle state.

JSONB is allowed for:

- raw structured AI response retained for a bounded period;
- provider and research evidence;
- parse warnings and risk metadata;
- model/prompt/schema version metadata;
- workflow-event details that do not own current business state.

HTTP APIs continue to send and receive JSON. API serialization is independent
from database ownership.

### 5.3 Source, document and journal separation

- A source file is immutable evidence.
- One source may contain multiple documents.
- One document may reference multiple independently received sources.
- Canonical facts may be corrected without changing source bytes.
- Journal changes never modify invoice evidence.
- Approved journals remain reproducible after raw-source deletion through the
  accepted minimum derived record.

## 6. State and revision model

The UI presents one clear primary status. Internally, independent state fields
prevent unrelated concerns from overwriting each other.

### 6.1 Source lifecycle

`stored -> terminal_decision_clock_started -> archive_available -> deleted`

Storage failure before durable acknowledgement does not produce `Belge alindi`.
Security quarantine and retention actions are operational details, not
accounting decisions.

### 6.2 Processing job lifecycle

`queued -> processing -> completed`

Recoverable failure transitions through `retry_wait` back to `queued`. An
expired worker claim is reclaimable. A terminal technical failure becomes
`failed/manual_attention_required` without deleting valid work.

### 6.3 Journal lifecycle

`working_draft -> review_required -> approved`

Additional paths:

- provisional AI-outage draft remains reviewable;
- export-list rejection records ineligibility without deleting evidence;
- approved work may be reopened into a new working revision;
- a delivered revision remains immutable and later correction uses a new
  correction/reversal flow.

The UI derives the accepted labels `Belge alindi`, `Fis hazirlaniyor`, `Kontrol
bekliyor`, `Onaylandi`, `Ajan olmadan hazirlanmis`, `Ek bilgi/belge gerekli`
and `Islem hatasi`. Users do not manage the internal dimensions directly.

### 6.4 Optimistic concurrency

- Meaningful edit obtains a five-minute activity-sensitive lease.
- Every mutation includes `expected_revision`.
- PostgreSQL atomically updates only the expected current revision.
- Stale clients receive a conflict response and cannot overwrite.
- Approval is a transaction covering the complete journal and hard checks.
- Reopen creates a new revision; it does not mutate an approved revision.

## 7. Intake and canonicalization

### 7.1 Intake contract

The source and intake identity are committed in one durable operation before a
success response. The client supplies or receives an idempotency identity.
Retry after a lost HTTP response returns the same accepted intake.

Duplicate layers:

1. byte hash for exact source repetition;
2. ETTN/UUID/provider identity where present;
3. invoice identity and tax parties for focused suspected-duplicate review.

Exact duplicates do not create a second authoritative accounting document.

### 7.2 Canonical source policy

- Use XML/UBL as canonical accounting source when available.
- Render preview locally from XML/style evidence.
- Do not routinely fetch a provider PDF merely to compare formats.
- Use PDF/image extraction when no canonical XML source exists.
- Attach a later independent source as evidence after identity verification.

### 7.3 Line identity and validation

Each canonical line carries:

- canonical line ID;
- UBL line ID or PDF page/row source;
- original description;
- quantity/unit;
- net amount;
- VAT/tax behavior;
- source position and evidence.

AI receives canonical IDs and must return exactly one structured decision per
supplied ID. The validator rejects missing, duplicate and unknown IDs.

## 8. Accounting decision architecture

### 8.1 Context assembly

Context is assembled per client and direction:

- canonical line and invoice evidence;
- client identity, NACE and short researched activity meaning;
- real chart code/description candidates;
- every selectable direction-appropriate `120` or `320` counterparty;
- matching active rules and confirmed bindings;
- only relevant prior decisions;
- controlled research result when escalation is required.

Paging or retrieval reduces prompt size but cannot permanently hide a valid
account.

### 8.2 AI roles

Visible product capabilities are:

- Belge Ajani;
- Hesap Ajani;
- Cari Ajani;
- Arastirma Ajani.

They may use a shared provider chain internally. Provider count and agent count
are not presented as the same concept.

AI owns:

- product/service and economic meaning;
- activity relevance;
- semantic account-family/real-account intent;
- counterparty intent;
- explanation and rule interpretation.

### 8.3 Deterministic engine

Deterministic code owns:

- direction and exact identity gates;
- exact totals and VAT arithmetic;
- debit/credit balance;
- chart account existence/usability;
- canonical-line coverage;
- hard rule preconditions;
- automation and export eligibility.

It may reject an invalid binding but does not invent a discretionary replacement
account. AI re-enters with current context.

### 8.4 Research

Research is query-minimized and evidence-scoped:

- canonical line meaning is attempted first;
- supplier/title/activity context disambiguates weak lines;
- cache is reused by normalized query and provenance;
- only accepted sources and bounded summaries enter the decision;
- copied pages and unnecessary personal data are not retained long-term.

## 9. Provider and outage architecture

### 9.1 Provider abstraction

Every provider adapter must expose:

- structured-output capability;
- timeout and retry classification;
- provider/model identity;
- token/usage/cost metadata when available;
- data-use/retention admission metadata;
- normalized error categories.

The current minimum attempt order is:

`Groq -> Cerebras -> OpenRouter`

Additional providers, including Gemini paid-tier use, require privacy,
structured-output, accounting-quality and cost-control admission.

### 9.2 Retry and provisional draft

One attempt calls every admitted provider once with bounded timeouts. Full-chain
failure schedules approximately:

`2m -> 5m -> 10m -> 15m -> 30m -> 2h -> 6h`

After six-hour cadence, frequent retries stop at the 24-hour attention
threshold. Jitter prevents retry spikes.

Verified deterministic rule coverage continues. Uncovered AI-dependent work
receives a populated provisional draft and `Ajan olmadan hazirlanmis`. A later
AI result may replace only untouched work. Saved edits, approval and export-list
rejection are authoritative.

## 10. Worker and queue architecture

### 10.1 Initial topology

- One document-worker container.
- Three parallel document slots.
- One separately controlled QNB scheduler lane.
- One low-priority maintenance/retention lane.

This is an initial capacity, not a permanent scaling limit.

### 10.2 Claim contract

- Claim uses PostgreSQL row locking / `SKIP LOCKED` or an equivalent durable
  lease.
- Claim records worker identity, attempt and expiry.
- Completion is idempotent.
- Expired claims are safely reclaimed.
- One source cannot produce two authoritative final journals.
- Queue priority protects ordinary accounting from provider benchmarks and
  maintenance work.

### 10.3 Scaling

Scale document slots and worker replicas only after measuring:

- queue wait;
- CPU/RAM;
- database connections and lock contention;
- provider rate limits;
- AI/research latency;
- journal-quality parity.

Redis may support caching, coordination and rate limiting. PostgreSQL remains
the durable accounting/job truth unless a later queue migration has explicit
delivery and reconciliation semantics.

## 11. Security and tenancy

- Every row carries tenant ownership and, where applicable, taxpayer ownership.
- Service/repository APIs require tenant/client scope rather than trusting
  frontend filtering.
- Passwords are one-way hashed.
- QNB and reusable integration credentials use application encryption with keys
  outside the database and source control.
- Public traffic uses HTTPS.
- PostgreSQL, Redis and source storage remain private.
- Production secrets are process-scoped, masked and rotatable.
- Support access is time-limited, approved, least-scope and audited.
- Break-glass access is named, alerting and reviewed.
- Real invoice content is prohibited in source-control issues and ordinary
  unprotected support channels.

## 12. Storage, retention and backup

### 12.1 Raw sources

- Store immutable source and cryptographic hash.
- Start retention clock only after authoritative terminal accounting decision.
- Normal access: 60 days.
- Grace/archive handoff: through day 90.
- Delete ordinary raw sources by day 90.
- Preserve the minimum derived accounting/learning evidence while the client is
  active.

### 12.2 Persistent-pilot protection

Before retaining operational real data:

- encrypted off-host incremental database/source protection at least every 15
  minutes;
- nightly encrypted full database and document backup;
- backup key stored separately;
- isolated restore test;
- backup lifecycle compatible with raw-source deletion.

Objectives:

- ordinary backend/worker recovery within five minutes;
- maximum 15 minutes acknowledged work at risk after activation;
- core service restoration within four hours of detected full-host loss.

## 13. Observability and audit

Record meaningful events, not every heartbeat or keystroke:

- intake accepted/deduplicated;
- parse/AI/research stage completion and failure;
- provider attempt and retry schedule;
- journal revision save;
- edit lease conflict/takeover;
- approval, rejection and reopen;
- rule interpretation, validation and activation;
- export/delivery attempt and acknowledgement;
- support access and destructive retention operations;
- backup and restore proof.

Operational telemetry excludes secrets and invoice content by default.

Key measurements:

- queue depth and oldest wait;
- stage duration;
- provider capability/latency/error category;
- worker slots and expired claims;
- database/storage pressure;
- backup freshness and recoverable point;
- accounting quality and correction rate.

## 14. QNB boundary

QNB is an acquisition source adapter, not the owner of Fisero accounting truth.

Fisero retains:

- QNB connection/sync policy;
- ETTN/UUID, number, tax parties and dates;
- source hash and pulled-at time;
- canonical data;
- QNB cancellation/rejection/status evidence;
- cursor/claim/reconciliation evidence.

The cursor advances only after durable success. Repeated download deduplicates.
QNB unavailability does not disable manual intake or existing review work.

## 15. Zirve boundary

Direct Zirve transport is later architecture. It must:

- consume one immutable approved journal revision;
- use an idempotency key;
- distinguish sent, accepted, rejected and unknown;
- reconcile external identifiers and status;
- preserve payload/acknowledgement evidence;
- create correction/reversal work rather than mutate delivered history.

Temporary CSV/Excel output may reuse the same approved journal but is not the
strategic integration contract.

## 16. Migration from `workflow_records`

The cutover is not a long-running dual-write migration.

1. Add/complete normalized schema, constraints and repositories.
2. Implement transactional normalized writes for new source, document,
   canonical lines, jobs, journals, review and rules.
3. Make audit/workflow events append-oriented.
4. Import only protected regression items, selected benchmark evidence and
   verified active rules.
5. Run parity verification against the compatibility view.
6. Pause persistent writes briefly.
7. Switch reads and writes together.
8. Verify tenant counts, source hashes, canonical coverage, balanced journals,
   revisions, rules and permissions.
9. Disable broad compatibility writes.
10. Retain old disposable trial data only for a bounded rollback/debug window,
    then remove it.

No persistent-pilot readiness claim is allowed while approved journals still
depend solely on `document.result.draft_lines`.

## 17. Verification strategy

Required automated proof:

- backend unit/integration suite;
- frontend contract tests and production build;
- line-ID response validation;
- database migration and constraint tests;
- tenant authorization tests;
- idempotent intake and duplicate tests;
- revision/lease conflict tests;
- provider outage/retry tests;
- QNB cursor/deduplication tests;
- export from authoritative journal tests.

Required deployed proof:

- 50-source burst;
- worker termination/reclaim;
- backend/PostgreSQL/Redis/host restart;
- storage-pressure boundaries;
- provider-chain outage/recovery;
- encrypted isolated restore;
- protected regression quality parity.

## 18. Architecture decisions and deferrals

Accepted now:

- modular monolith and separate worker;
- normalized PostgreSQL accounting ownership;
- immutable source, separate canonical invoice and journal;
- relational core plus bounded JSONB evidence;
- append-oriented workflow/audit events;
- explicit revision/concurrency protection;
- QNB acquisition and later Zirve delivery boundaries.

Deferred without blocking the persistent invoice pilot:

- a distributed microservice split;
- a separate high-scale message broker;
- direct Zirve transport implementation;
- exhaustive customs/import/export workflow;
- full Hermes/Musavir Yancisi deployment isolation and write-tool contract;
- numeric provider admission thresholds until the real benchmark;
- exact capacity scale-out until load evidence exists.
