# Fisero Product Requirements Document

Status: Canonical planning baseline
Version: 1.0
Date: 2026-07-18
Owners: Product owner and Fisero engineering
Decision source: `00-canonical-decision-register.md`

## 1. Executive summary

Fisero is an AI-first accounting operations product built primarily for
accountants and their office employees. Its first job is not transport into an
external accounting package; it is to turn real purchase and sales invoices
into the most correct, complete, balanced, explainable and accountant-useful
journal draft possible.

The product succeeds when the accountant can approve the prepared journal with
little or no change and when a confirmed correction is reliably reused in the
same real context. Review is a safety gate, not the product goal. Low confidence
does not license an empty journal, a lazy generic account or an unnecessary
client-information request.

The first persistent pilot covers one accounting office, multiple clients,
invoice intake, canonical line extraction, client-specific chart selection,
AI-assisted journal preparation, accountant review, learning and operational
reliability. Direct Zirve delivery, bank/POS automation and broader ERP scope
follow after the invoice-to-journal loop proves its quality.

## 2. Problem and product outcome

### 2.1 Problem

Accountants repeatedly:

- collect invoices from several sources;
- verify identity, direction, totals, VAT and line meaning;
- find the correct supplier/customer and expense/revenue accounts in a
  client-specific and often messy chart of accounts;
- build balanced journals;
- correct the same recurring decisions;
- protect the result from processing, concurrency and integration errors.

Existing automation often stops at extraction, chooses generic accounts, hides
its reasoning or sends uncertain work back to the accountant without preparing
the strongest possible draft.

### 2.2 Required outcome

For every supported invoice Fisero must:

1. preserve the source and identify the real invoice;
2. extract and validate header, parties, direction, totals, taxes and every
   accounting-relevant line;
3. use the client's real chart, counterparty context, NACE/activity, learned
   decisions and controlled research;
4. prepare one complete and balanced journal;
5. show what it understood and why;
6. allow fast, conflict-safe accountant correction and approval;
7. learn only within an accountant-approved scope;
8. retain enough evidence to reproduce and explain the final result.

## 3. Product principles

1. **Accountant first.** Automation removes repeated office work; it does not
   create avoidable tasks for the accountant.
2. **AI first for discretionary meaning.** AI interprets product/service,
   activity relation, account meaning and counterparty intent.
3. **Deterministic protection for hard boundaries.** Exact VAT, debit/credit
   balance, usable-account checks, identity, legal constraints and unattended
   export gates remain deterministic.
4. **Best draft always.** Review-required work remains populated, balanced and
   useful.
5. **Real client context.** Fisero never invents or owns the client's chart of
   accounts. The accountant imports the real plan.
6. **Line-level integrity.** Every canonical invoice line is accounted for by
   identity, not by array position or first-line generalization.
7. **Explainable learning.** The accountant sees what the system understood,
   confirms scope and can inspect rule history.
8. **Sparse daily UX.** Normal review stays fast; detail expands only when
   requested.
9. **No silent overwrite.** AI retry, another user or an old browser tab cannot
   overwrite authoritative accountant work.
10. **Honest boundaries.** Fisero is not the sole legal invoice archive and does
    not claim direct Zirve delivery before it is field proven.

## 4. Users, roles and permissions

### 4.1 Accountant / office administrator

- Creates and activates clients.
- Reviews and approves accounting work.
- Manages permissions and, by default, accounting rules.
- Can reopen undelivered approved work.
- Can authorize tightly scoped support access.
- Sees office operations, provider health and backup/recovery evidence.

### 4.2 Office employee

- Sees only authorized clients.
- May upload, inspect and process documents.
- May edit/review when granted `can_review_accounting`.
- May read rule history for accessible clients.
- May manage rules only when granted `can_manage_accounting_rules`.

### 4.3 Client user

- Receives an invitation and creates a password.
- Uses a simple authenticated upload portal.
- Receives immediate upload success/failure.
- Does not review journals, manage rules or follow persistent processing status
  in the first pilot.

### 4.4 Technical support

- Has no standing access to taxpayer content.
- Uses redacted operational telemetry by default.
- Content access requires bounded, time-limited, audited office approval.
- Break-glass access is reserved for material security, recovery or data-loss
  incidents.

## 5. First-pilot scope

### 5.1 Included

- One accountant office and multiple clients.
- Client onboarding from tax certificate and accountant-provided information.
- Client identity/activity verification and NACE enrichment.
- Import and validation of the accountant-owned chart of accounts.
- QNB synchronization where available.
- Manual invoice upload as a supported fallback.
- Purchase and sales invoice processing.
- XML/UBL canonical extraction and PDF/image extraction when XML is absent.
- Single/multiple line and single/mixed VAT invoices.
- Return invoices with focused original-invoice linkage when available.
- Real chart-account and counterparty selection.
- Full balanced journal preparation.
- Review, edit, approval and removal from the export list.
- Explicit and natural learning flows.
- AI/research provider failover and visible outage handling.
- A permanent real-data regression corpus and go/no-go quality evidence.
- Temporary raw-source retention, archive handoff and controlled deletion.

### 5.2 Not a first-pilot gate

- Direct Zirve delivery and reconciliation.
- Recurring Excel/CSV bridge operation.
- Bank and POS statement quality.
- Payroll, declarations, e-Defter and full fixed-asset lifecycle.
- Full accounting/ERP replacement.
- Client-facing processing tracking and automated missing-information messages.
- Multi-office commercial packaging, subscriptions and billing.
- Native mobile applications.
- Exhaustive automation of rare customs, import/export and special-document
  cases.
- A general-purpose chatbot with unrestricted accounting write authority.

## 6. End-to-end product journey

### 6.1 Client creation and activation

1. The accountant starts client creation.
2. Fisero reads the tax certificate and proposes title, VKN/TCKN, tax office,
   NACE and other available identity fields.
3. Automatically read values and accountant corrections are shown together.
4. The verified NACE code is enriched with a short practical activity summary
   from cache or controlled research.
5. The accountant imports the client's real chart of accounts.
6. Fisero parses codes, descriptions, detail accounts, supplier/customer
   candidates and identity evidence without inventing a new chart.
7. Activation readiness checks identity, activity and a usable chart.
8. When all hard requirements pass, the client becomes active automatically.
9. Portal invitation is sent without making monthly client access dependent on
   repeated magic links.

### 6.2 Invoice intake

1. QNB is the preferred automatic source where configured.
2. Manual upload remains available for other providers, historical documents
   and outages.
3. Fisero durably commits the source before returning `Belge alindi`.
4. Hash, ETTN/UUID, invoice identity and source metadata prevent duplicate
   authoritative invoices.
5. One valid canonical source is sufficient. Fisero does not routinely fetch
   both XML and PDF for comparison.
6. A later independently received format may attach as additional evidence.
7. A package containing multiple invoices may produce multiple independently
   processed documents.

### 6.3 Canonicalization and accounting preparation

1. XML/UBL is parsed into canonical parties, header, totals, tax summary and
   lines. PDF/image extraction is used when XML is unavailable.
2. Every line receives a stable canonical identity and source position.
3. Direction and client identity are verified.
4. The accounting engine gathers the client's chart, counterparty candidates,
   activity/NACE, matching rules and relevant prior decisions.
5. AI interprets every line and returns decisions keyed by canonical line ID.
6. Weak or generic descriptions trigger semantic escalation and controlled
   research; they do not trigger an empty or generic fallback.
7. Deterministic checks validate totals, VAT, balance, account existence and
   automation eligibility.
8. Fisero stores the strongest complete journal draft and explanation.

### 6.4 Accountant review

- The review surface prioritizes source preview, journal lines and the reason
  for the proposed accounting treatment.
- Primary action is `Onayla ve gec`.
- `Ek bilgi/belge gerekli`, `Kontrol icin beklet`, `Yeniden isle` and
  `Cikti listesine ekleme` live under one compact `Diger islemler` menu.
- Multiple users may view. The first meaningful edit obtains a five-minute
  activity-sensitive lease.
- Saved mutations carry an expected revision. Stale screens cannot overwrite
  newer or approved work.
- Approval is atomic for the whole journal. Partially approved journals cannot
  be exported.
- Reopening preserves the prior approved revision and requires a reason.

### 6.5 Learning

- An explicit instruction is interpreted into a compact, editable rule card.
- The accountant confirms client or office scope, trigger, semantic meaning and
  current client account binding.
- The rule starts as `awaiting_first_validation`.
- One genuinely similar independent invoice must be approved without a
  rule-relevant correction before activation.
- Ordinary corrections create learning evidence but do not silently activate
  permanent rules.
- Office-wide learning shares semantic meaning; it never copies one client's
  account code into another client.
- Exact matching tolerates Turkish characters, case, spelling and normal
  language variation.

### 6.6 Output boundary

- `Onaylandi` means the authoritative accounting result exists; it does not
  mean Zirve received it.
- A temporary export package may be generated when useful, but is not the pilot
  product promise.
- Later direct Zirve delivery consumes an approved immutable journal revision
  and must implement idempotency, acknowledgement, reconciliation and
  correction handling.

## 7. Functional requirements

### FR-01 Client onboarding

- Required accounting identity and activity fields must be complete before
  activation.
- Tax-certificate OCR must expose confidence and corrections.
- Corrections must become measurable extraction-improvement evidence.
- NACE enrichment must use the verified code as its anchor.
- Chart import must preserve real codes and descriptions.

### FR-02 Source and duplicate control

- Acknowledged sources must be durable.
- Original files must remain immutable.
- Duplicate retry must resolve to the same intake identity.
- XML/PDF evidence relationships and multi-invoice packages must not create
  duplicate authoritative journals.

### FR-03 Canonical invoice

- Supplier, customer, date, number, currency, totals, tax and line evidence must
  be traceable to the selected source.
- AI may not rewrite canonical descriptions, quantities, amounts or VAT.
- Missing, duplicate or unknown line IDs fail structured-response validation.

### FR-04 Accounting intelligence

- All selectable real chart accounts remain reachable.
- Candidate paging is a performance mechanism, not a correctness boundary.
- Direction-filtered `320` or `120` counterparty candidates remain searchable.
- If no suitable counterparty exists, Fisero proposes
  `<120|320>.<VKN> - <legal title>` rather than selecting an unrelated account.
- If a confirmed account binding becomes unusable, AI re-enters; deterministic
  code does not choose an arbitrary replacement.

### FR-05 Journal and review

- Every supported invoice receives a populated balanced draft.
- Review displays uncertainty without abandoning the accounting decision.
- Journal edits, approvals, rejections and reopen actions are durable and
  attributable.
- Approved revisions cannot be silently mutated.
- Export uses only the authoritative approved journal.

### FR-06 Learning and rules

- Rule scope, meaning, trigger and binding must be understandable before save.
- Only authorized users may activate, edit, pause or archive rules.
- Explicit confirmed rules target 0% repeat correction when preconditions match.
- Conflicting equal-priority rules prepare a draft but require authorized
  resolution.

### FR-07 AI outage

- One attempt tries each admitted provider once in configured order.
- If all fail, Fisero preserves verified rule coverage and prepares the best
  possible provisional draft.
- The visible state is `Ajan olmadan hazirlanmis`.
- Untouched work retries after approximately 2, 5, 10, 15 and 30 minutes, then
  2 and 6 hours, with bounded jitter.
- Saved accountant work is never automatically overwritten.
- Notifications are incident based and deduplicated.

### FR-08 Status semantics

Office users see:

- `Belge alindi`
- `Fis hazirlaniyor`
- `Kontrol bekliyor`
- `Onaylandi`
- `Ajan olmadan hazirlanmis`
- `Ek bilgi/belge gerekli`
- `Islem hatasi`

Internal processing, edit lease and later delivery states may remain separate,
but the ordinary UI presents one clear primary status and only relevant detail.

### FR-09 Retention and deletion

- Raw-source retention begins after an authoritative terminal accounting
  decision.
- Sources remain normally accessible for 60 days.
- The accountant may download a client/period archive and confirm early
  deletion.
- A 30-day grace period follows; day 90 is the ordinary hard deletion bound.
- Approved journals, decision history and active rules are not deleted with raw
  source files.
- Broad test reset must not delete the protected regression corpus or verified
  active rules.

### FR-10 Operations

- Office operations shows queue health, oldest work, provider capability,
  storage, backup and restore evidence.
- Provider outage creates one calm document notification and one system banner.
- A 15-minute full-chain outage sends one early technical warning.
- Six hours or 50 unresolved AI documents creates a critical incident.
- Recovery sends one incident recovery message.

## 8. Quality and success metrics

### 8.1 Accounting quality targets

- Cold-start unchanged approval: at least 70%.
- Minor edit: at most 20%.
- Serious/manual accounting correction: at most 10%.
- Learned similar cases approved unchanged: at least 90%.
- Explicit confirmed rule repeat correction when conditions match: 0%.
- Critical mechanical accounting error in unattended approval: 0.
- Missing, duplicated or shifted canonical line in an accepted journal: 0.

### 8.2 Pilot evidence

- Versioned corpus: 50 unique real invoices.
- Target mix: 35 purchase and 15 sales invoices.
- Corpus covers clients, counterparties, multi-line, mixed VAT, weak lines,
  returns and available special-tax examples.
- Every result receives unchanged/minor/material/unusable accountant labels.
- Provider admission uses the same frozen input, rule and prompt versions.
- Performance improvement may not silently reduce accounting quality.

### 8.3 Product-efficiency measures

- Median accountant review time.
- One-click approval rate.
- Average changed journal fields per reviewed invoice.
- Repeated-correction rate by active rule.
- Queue wait and end-to-end completion time.
- AI/research calls and cost per accepted journal.
- Provisional outage draft and recovery counts.

## 9. Non-functional requirements

- Tenant and client authorization applies to every protected read/write.
- Passwords use salted one-way hashing; reusable integration credentials use
  application-level encryption.
- PostgreSQL, Redis and document storage are not publicly exposed.
- Core accounting state uses normalized PostgreSQL tables.
- API JSON and JSONB metadata do not replace relational accounting truth.
- One persistent-pilot worker starts with three document slots; QNB scheduling
  and low-priority maintenance remain separately controlled.
- Legitimate 50/100/250-document intake is durably accepted and queued rather
  than rejected by arbitrary daily quotas.
- Ordinary backend/worker recovery target is five minutes.
- Full host-loss core recovery target is four hours after detection and
  recovery start.
- After persistent-pilot activation, acknowledged work has a 15-minute maximum
  catastrophic-loss objective.
- HTTPS, backup encryption, isolated restore tests, rate limits and redacted
  diagnostics are release requirements.

## 10. First-pilot acceptance scenarios

The pilot cannot be declared ready until it proves:

1. Client activation from verified identity/activity and a usable imported
   chart.
2. QNB and manual intake without duplicate authoritative documents.
3. Canonical extraction and full line-to-journal coverage.
4. Correct purchase/sales direction and mixed-VAT journal construction.
5. Real chart and counterparty selection, including a missing-counterparty
   proposal.
6. Accountant edit, approval, export-list rejection and reopen without stale
   overwrite.
7. Explicit rule creation, independent validation and correct subsequent use.
8. AI-chain outage, provisional draft, accepted retry schedule and overwrite
   protection.
9. Fifty-source burst, worker interruption and safe job reclamation.
10. Encrypted backup restore with source hashes, journals, rules and tenant
    boundaries intact.

## 11. Risks and controls

| Risk | Product control |
| --- | --- |
| Generic or empty low-confidence drafts | Best-complete-draft contract and real chart search |
| AI shifts multi-line decisions | Canonical line IDs and exact response coverage |
| Wrong client/counterparty | Exact identity evidence and confirmed move/binding |
| Learned rule overgeneralizes | Scope confirmation and independent validation |
| AI outage hides quality downgrade | Provisional label, retries and no unattended export |
| Concurrent work is overwritten | Edit lease, expected revision and immutable approval |
| Raw documents become permanent archive | 60-day access, archive handoff, day-90 deletion |
| JSON compatibility store becomes permanent truth | One-way normalized PostgreSQL cutover |
| Provider is cheap but unsafe/weak | Privacy allowlist and real-invoice benchmark admission |
| Rare cases consume the pilot | Main-path release gate and explicit deferral |

## 12. Deferred validations

The following do not block strongest-draft preparation but remain review-only
until the pilot accountant confirms office practice:

- foreign-currency exchange-rate treatment;
- price-, maturity- and exchange-difference accounts;
- foreign supplier/import/customs/imported-service treatment;
- goods/service export and customs completion treatment.

The questions and answer records live in
`90-accountant-validation-questions.md`.

## 13. Release decision

The first persistent pilot is a go only when:

- normalized PostgreSQL accounting ownership is active;
- protected real sources and accountant decisions are backed up off-host;
- the end-to-end acceptance scenarios pass;
- the 50-invoice corpus meets quality thresholds or every failing scope remains
  explicitly review-only;
- no known defect can lose an acknowledged source, cross tenant boundaries,
  duplicate an authoritative journal or silently overwrite approved work.

Anything not required by this gate belongs in the roadmap rather than becoming
another pre-implementation product discussion.
