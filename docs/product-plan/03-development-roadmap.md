# Fisero Development Roadmap

Status: Canonical execution baseline
Version: 1.0
Date: 2026-07-18
Owners: Product owner and Fisero engineering
Inputs: PRD, System Architecture Document and canonical decision register

## 1. Roadmap objective

Move Fisero from a capable disposable-data development system to a persistent
real-invoice pilot without weakening its central promise:

> Prepare the strongest complete, balanced and explainable journal, minimize
> accountant correction, and learn confirmed decisions reliably.

The roadmap is dependency based. A phase is complete only when its evidence and
exit gate pass; implementation volume or checklist percentage is not proof.

## 2. Current baseline

### Available foundations

- Next.js accountant/client portal and FastAPI API.
- PostgreSQL, Redis, worker and Nginx production topology.
- Taxpayer onboarding, tax-certificate and chart import foundations.
- Manual upload and QNB incoming-document foundations.
- Invoice direction, XML/PDF parsing and accounting simulation.
- Mixed VAT, chart/counterparty selection and journal draft generation.
- AI provider chain, research harness and usage visibility.
- Review, learning-rule interpretation and pipeline audit evidence.
- QNB scheduling, deduplication, status and credential-encryption foundations.
- Health/readiness, deploy smoke, backup and retention foundations.

### Material gaps

- `workflow_records` JSONB remains the active broad data owner.
- Normalized journal tables do not own the end-to-end approved result.
- Real line-level accounting coverage needs persistent regression proof.
- Edit lease/revision conflict protection is not fully implemented.
- Protected regression data is not isolated from broad reset.
- Off-host source backup and tested restore are not persistent-pilot ready.
- Provider admission thresholds are not calibrated on the final real corpus.
- Direct Zirve delivery remains intentionally deferred.

## 3. Release definitions

### Development lane

Disposable ordinary trial data is allowed. It may use the compatibility store
while the target vertical slice is built. No operational retention/export
readiness claim is made.

### Persistent-pilot candidate

Normalized PostgreSQL owns new operational accounting data; protected sources,
rules and decisions survive restart/reset; backup/recovery and quality gates
pass.

### Closed persistent pilot

One accountant office uses multiple clients and real purchase/sales invoices
for the invoice-to-approved-journal workflow under monitored support.

### Later integration release

Approved immutable journal revisions are delivered directly to Zirve with
idempotency and reconciliation.

## 4. Phase 0 - Documentation closure

Status: Complete

Deliverables:

- canonical decision register;
- PRD;
- System Architecture Document;
- dependency-based roadmap;
- accountant validation-question register.

Exit evidence:

- product scope, architecture ownership and release gates are explicit;
- unresolved office-practice questions are labelled rather than silently
  guessed;
- further implementation detail does not require another week of general
  product discussion.

## 5. Phase 1 - Normalized invoice-to-journal vertical slice

Priority: Immediate code work
Goal: Make PostgreSQL the authoritative owner for one complete supported
invoice path before widening the migration.

### Work package 1.1 - Schema and migrations

Add or complete:

- immutable source-file records;
- document-to-source relationships;
- canonical document fields and line identity;
- durable processing jobs and attempts;
- journal revisions and line allocation;
- AI/provider attempt records;
- append-oriented workflow/audit events;
- required tenant/client/document foreign keys, unique constraints and indexes.

Do not place core accounting money, account or approval truth solely in JSONB.

### Work package 1.2 - Repository contracts

Create explicit repositories/services for:

- source intake;
- canonical invoice persistence;
- processing claims;
- journal draft/revision;
- review decision;
- learning rule;
- workflow event.

The API may preserve current response shapes while repository ownership changes.

### Work package 1.3 - One end-to-end purchase invoice

For one supported purchase invoice:

1. store source durably;
2. deduplicate;
3. parse canonical header/lines;
4. prepare journal;
5. write journal/lines to normalized tables;
6. edit and approve through review service;
7. export from the authoritative journal;
8. reopen into a new revision;
9. prove the original approved revision remains unchanged.

### Work package 1.4 - Cutover harness

- Add a development-only target-store switch.
- Compare compatibility and normalized projections during automated tests.
- Do not enable a long-running production dual-write mode.
- Import only selected protected regression/rule data at final cutover.

### Exit gate

- No approved result depends solely on `document.result.draft_lines`.
- Transaction rollback cannot leave half a journal or half a review.
- Duplicate upload/retry produces one authoritative document/journal.
- Existing frontend flow works without a major Faturalar-page redesign.
- Backend tests, migration tests, frontend tests/build and `git diff --check`
  pass.

## 6. Phase 2 - Canonical line and accounting-quality closure

Goal: Prove every source line reaches the correct journal treatment.

### Work package 2.1 - Canonical extraction

- Stable line IDs for XML and PDF-derived lines.
- Exact source location and original description.
- Header, party, total, currency and tax evidence.
- One selected canonical source without routine XML/PDF pairing.
- Multi-invoice package split and additional-evidence attachment.

### Work package 2.2 - Structured AI coverage

- Send all relevant lines with stable IDs.
- Require one response per ID.
- Reject missing, duplicate and unknown IDs.
- Attach research and model evidence to the affected line/group.
- Aggregate journal presentation only after compatible line decisions.

### Work package 2.3 - Accounting construction

- Purchase and sales direction.
- Single and mixed VAT.
- Real account and counterparty selection.
- Missing `120/320` counterparty proposal.
- Return-invoice draft with available original link.
- Focused special-tax review without abandoning the full draft.

### Exit gate

- Zero missing/duplicated/shifted line in the protected corpus.
- Every supported invoice produces a balanced populated journal.
- All selected accounts exist and are usable in the client's chart.
- Material accounting failures remain review-only and cannot auto-approve.

## 7. Phase 3 - Review, revisions and learning safety

Goal: Make accountant work fast, durable and impossible to overwrite silently.

### Work package 3.1 - Review concurrency

- Five-minute meaningful-activity edit lease.
- Recoverable debounced working save.
- `expected_revision` on every mutation.
- Stale-tab conflict response and reload/compare path.
- Admin forced takeover with reason and audit.

### Work package 3.2 - Journal lifecycle

- Atomic complete-journal approval.
- Export-list rejection without source deletion.
- Human-only missing-information action.
- Reopen undelivered approval into a new revision.
- Preserve delivered-revision distinction for future Zirve.

### Work package 3.3 - Learning rules

- Compact interpreted rule card.
- Client/office scope.
- Semantic meaning plus current chart binding.
- `awaiting_first_validation` and independent validation.
- Active/pause/archive/version history.
- Conflict handling and unavailable-account AI re-entry.
- Protected rules excluded from broad pilot reset.

### Exit gate

- Two-user AFK/stale-tab tests cannot lose newer work.
- Approved revisions are immutable.
- Explicit matching rule reaches 0% repeat correction in its validated corpus.
- Ordinary correction never silently becomes office-wide automation.

## 8. Phase 4 - Onboarding and acquisition readiness

Goal: Ensure every active client supplies enough trusted accounting context and
that intake requires minimal accountant effort.

### Work package 4.1 - Tax-certificate quality loop

- Side-by-side extracted and corrected identity/activity fields.
- Field confidence and provenance.
- Correction telemetry by field/parser/version.
- Regression tests that improve title, VKN/TCKN, tax office and NACE reading.

### Work package 4.2 - NACE and chart readiness

- Verified NACE as the activity anchor.
- Cached/researched short activity meaning.
- Real chart parse and detail-account validation.
- Direction-appropriate account/counterparty search.
- Automatic activation when all hard requirements pass.

### Work package 4.3 - Intake sources

- Manual upload idempotency and duplicate handling.
- QNB synchronization/cursor/status hardening.
- Source adapter boundary for later providers.
- Immediate client upload receipt without first-pilot status-tracking scope.

### Exit gate

- A client cannot activate without verified accounting identity/activity and a
  usable imported chart.
- Activation does not require avoidable repeated accountant or client work.
- QNB restart/timeout does not advance cursor without durable source success.

## 9. Phase 5 - Provider, outage and quality admission

Goal: Admit AI/research capacity by accounting quality, privacy and reliability.

### Work package 5.1 - Permanent corpus

- Protect 50 unique real invoices: target 35 purchase / 15 sales.
- Preserve source, canonical extraction, reference journal and rule/chart
  snapshot.
- Version reference corrections rather than rewriting them.
- Remove protected corpus from broad reset.

### Work package 5.2 - Fair provider benchmark

- Frozen prompt/schema/rule/input per comparison.
- Unchanged/minor/material/unusable accountant labels.
- Per-scope quality, structural validity, latency, availability and cost.
- Privacy and data-use allowlist.
- Hard stop/cost controls for paid trials.

### Work package 5.3 - Outage operation

- `Groq -> Cerebras -> OpenRouter` admitted chain baseline.
- Full-chain bounded attempt.
- Accepted retry schedule.
- Provisional deterministic draft.
- No overwrite after meaningful accountant action.
- Capability-based banner and incident notifications.

### Exit gate

- Provider admission thresholds are calibrated from real evidence.
- Cold-start and learned-case quality targets are met or the failing scope is
  explicitly review-only.
- Fifteen-minute warning, six-hour/50-document critical and one recovery
  incident behavior pass.

## 10. Phase 6 - Persistent-pilot infrastructure gate

Goal: Make retained real work recoverable and operationally supportable.

### Work package 6.1 - Load and failure

- Fifty-source burst through normal intake.
- Three document slots under measured load.
- Worker kill and expired-claim recovery.
- Backend, PostgreSQL, Redis and host restart tests.
- Storage pressure warning/critical/safe-stop thresholds.

### Work package 6.2 - Backup and restore

- Encrypted off-host incremental protection at least every 15 minutes.
- Nightly encrypted full database/source backup.
- Separate key recovery.
- Isolated restore and application-level verification.
- Retention-aware expiry from backup sets.

### Work package 6.3 - Operations and support

- Queue, oldest item, worker, provider and storage health.
- Backup freshness and last restore proof.
- Redacted diagnostics.
- Time-limited support grant and break-glass audit.
- Configurable technical alert mail.

### Exit gate

- No acknowledged source loss in interruption tests.
- No duplicate authoritative journal.
- Five-minute ordinary service recovery target is demonstrated.
- Four-hour host-loss recovery plan and isolated restore proof exist.
- Fifteen-minute maximum acknowledged-work-at-risk objective is active.

## 11. Phase 7 - Closed persistent pilot

Goal: Operate the complete invoice-to-approved-journal loop with one accounting
office and multiple clients.

### Activities

- Start with a controlled client set.
- Monitor quality, review time, repeated corrections and operational load.
- Ask the four accountant validation questions using real examples.
- Promote confirmed treatment into scoped rules and regression cases.
- Fix systematic accounting-quality gaps before expanding document types.
- Produce a temporary output package only if it helps the accountant validate
  final journals.

### Go/no-go

Go:

- core PRD acceptance scenarios pass;
- persistent storage/backup gate passes;
- no critical tenant/source/revision defect remains;
- quality meets thresholds or weak scopes remain explicitly review-only.

No-go:

- acknowledged source can be lost;
- wrong-client chart can create an authoritative journal;
- approved work can be overwritten;
- line coverage can shift silently;
- external output can use a non-authoritative draft.

## 12. Phase 8 - Direct Zirve delivery

Starts only after journal quality is trusted.

Deliverables:

- supported direct transport mechanism;
- credentials and authorization;
- immutable approved-revision payload;
- idempotent send key;
- sent/accepted/rejected/unknown states;
- external identifier and acknowledgement;
- reconciliation dashboard;
- correction/reversal flow;
- field evidence with the pilot accountant.

CSV/Excel remains an optional temporary validation tool, not the final product
workflow.

## 13. Phase 9 - Accounting expansion

Candidate order:

1. Bank and POS statements.
2. Broader QNB/outgoing-document workflows.
3. Import/customs and export evidence automation after accountant validation.
4. Client-facing status and structured information requests.
5. Müşavir Yancısı/Hermes contextual assistant.
6. Multi-office commercial packaging.

Müşavir Yancısı remains read/explain/suggest first. Any accounting mutation uses
the same permission, confirmation, revision and audit contracts as the normal
application.

## 14. Cross-phase quality gates

Every production-bound change runs the relevant portion of:

- `python -m unittest discover -s backend/tests`
- `node --test frontend/app/*.test.cjs`
- `cd frontend && npm.cmd run build`
- `git diff --check`

Changes to model, prompt, canonical extraction, tax engine, chart selection,
counterparty selection or rules also run the protected regression scope.

No phase closes on green tests alone when its exit gate requires live provider,
accountant, load, restore or external-system evidence.

## 15. Deferred decisions and owners

| Item | When resolved | Owner/evidence |
| --- | --- | --- |
| Foreign-currency practical policy | Closed pilot | Pilot accountant + examples |
| Difference-invoice accounts | Closed pilot | Pilot accountant + chart policy |
| Import/customs/imported services | Expansion | Pilot accountant + source evidence |
| Goods/service export treatment | Expansion | Pilot accountant + customs evidence |
| Provider numeric thresholds | Phase 5 | Real 50-invoice benchmark |
| Exact scale-out topology | Phase 6+ | Load and provider evidence |
| Direct Zirve mechanism | Phase 8 | Zirve/accountant field proof |
| Müşavir Yancısı write tools | Phase 9 | Permission and safety design |

These items do not reopen the accepted first-pilot product direction.

## 16. Immediate code-start package

The next implementation task is Phase 1, not another general planning round.

Start with:

1. inspect the existing schema/migrations and define the minimal normalized
   source/document/journal/revision tables;
2. add migrations and repository tests;
3. route one purchase invoice through normalized persistence;
4. make review update the authoritative journal revision;
5. make export read that journal;
6. preserve the current frontend contract;
7. verify the full backend/frontend proof set.

Stop after the first complete vertical slice, review the real diff and measured
behavior, then widen the cutover to sales, mixed VAT, learning and QNB paths.
