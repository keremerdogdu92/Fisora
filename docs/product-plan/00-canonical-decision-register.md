# Fisero Canonical Decision Register

Status: Living working document
Last updated: 2026-07-18
Owners: Product owner and Fisero planning process

## Purpose

This file preserves decisions agreed during the canonical product-planning
work. It is the continuity source while the final PRD, system architecture
document, development roadmap, acceptance plan, and release gates are being
prepared.

This is not yet the final PRD or implementation specification. Settled
decisions are marked `Accepted`. Matters that still need discussion are marked
`Open`. When the final planning pack is ready, these decisions must be moved
into the relevant canonical documents without changing their meaning.

## 1. Product objective

Status: Accepted

- Fisero is an AI-first accounting assistant primarily for accountants and
  their office employees.
- The primary product outcome is the most correct, complete, explainable, and
  accountant-useful draft journal entry that can be approved with little or no
  change.
- Review is a safety mechanism, not the product goal.
- Low confidence must not cause the system to abandon the journal entry or
  fall back lazily to a generic account. The system must still prepare its best
  complete draft and explain the uncertainty.
- Zirve integration is a downstream phase. Reliable journal preparation comes
  first. The strategic target is direct data delivery into Zirve, not making the
  accountant operate a recurring Excel/CSV bridge.

## 2. Users and responsibilities

Status: Accepted

- Primary users are the accountant and accountant-office employees.
- In the first pilot, the client user is an authenticated document uploader only.
  The upload surface gives an immediate success/failure receipt but does not
  provide persistent processing-status tracking or an in-product completion
  request workflow.
- The client user does not manage accounting rules, approve accounting
  decisions, or see internal rule/audit history in the pilot releases.
- Client-facing status tracking, structured missing-information requests, and
  creating invoices from the client portal are later-phase possibilities, not
  first-pilot requirements.
- Rule-management authority is permission based, not permanently tied to a
  job title.
- The default rule manager is the accountant/office administrator.
- The office administrator may grant trusted employees the
  `can_manage_accounting_rules` permission.
- Office users with access to a client may read the rule history. Only users
  with rule-management permission may activate, edit, pause, or archive rules.
- Accounting review authority is also permission based. Users with
  `can_review_accounting` may edit, approve, or reject journal drafts for the
  clients they are authorized to access. This permission is independent from
  `can_manage_accounting_rules`; reviewing a draft does not automatically grant
  rule-management authority.

## 3. AI and deterministic engine responsibilities

Status: Accepted

AI responsibilities:

- Understand the invoice product or service.
- Use line evidence, document context, client activity/NACE, counterparty
  identity, prior decisions, learned meaning, and research when needed.
- Select the best real account and counterparty candidate from the relevant
  client context.
- Explain what it understood, why it chose the accounting treatment, and what
  remains uncertain.
- Turn accountant notes and corrections into structured learning candidates.

Deterministic responsibilities:

- Preserve debit/credit balance.
- Enforce exact VAT and hard legal constraints.
- Verify invoice direction and rule preconditions.
- Ensure a selected account exists and is usable in the current client's real
  chart of accounts.
- Guard unattended automation and later export gates.

The deterministic engine must not replace a discretionary accountant decision
with a generic fallback merely because confidence is lower. Its role is to
protect mechanical and hard-rule boundaries.

If a confirmed account binding no longer exists or is unusable, the
deterministic engine stops exact application but does not choose a replacement
account. AI must immediately re-enter for the affected accounting decision,
using the retained semantic meaning, the current full chart of accounts,
client activity, counterparty context, and prior accountant instruction.

## 4. Evidence policy

Status: Accepted

Evidence is considered together, with the following default priority:

1. Canonical invoice line evidence from the selected source (XML when
   available; otherwise PDF/image extraction).
2. Document metadata, direction, VAT, and totals.
3. Client activity/NACE and known business context.
4. Counterparty identity, title, and tax identity.
5. Prior decisions and confirmed learning rules.
6. Controlled external research.
7. AI joint interpretation.

Counterparty identity must not be the first or only product/service evidence.
However, it may be strong supporting evidence when lines are weak or generic,
especially for electricity, natural gas, telecom, cargo, and similar known
providers. The system must use the combined evidence instead of discarding a
high-quality draft merely because one evidence source is weak.

Generic phrases such as `muhtelif urun`, `hizmet bedeli`, or `diger hizmetler`
are evidence-quality signals, not terminal outcomes. They cannot by themselves
trigger `Ek bilgi/belge gerekli`, a generic deterministic account, an empty
journal, or a processing stop. When the document still contains sufficient
party, amount, and tax evidence, Fisero must select the strongest defensible
real account and produce a balanced, populated journal.

For a client with multiple activities or projects, the default assumption is
the activity/project most strongly supported by the invoice, counterparty,
client profile, and history. Fisero prepares the complete journal on that basis
and uses focused review only when the remaining ambiguity is material. A later
accountant correction becomes learning evidence; theoretical alternative use
alone does not create a client-information request.

One valid canonical source is sufficient for normal processing. Fisero does not
download XML and PDF together merely to compare them. For QNB/provider intake,
XML is acquired as the accounting source when available and the ordinary visual
preview is rendered locally from that XML/style evidence; a separate provider
PDF is not fetched. PDF/image extraction is used when canonical XML is not
available or the user chose that source. If a second format independently
arrives later, it may be attached as additional source evidence under the
accepted version/duplicate policy, but Fisero never searches for or downloads a
pair as a routine quality step.

For a text-readable PDF, canonical extraction has two explicit modes. `repair`
may fill only the canonical rows already found by the deterministic parser;
`discovery` may propose missing rows only when deterministic extraction is
missing or arithmetically inconsistent. Fisero assigns canonical line identity
from unique source positions after validation; a provider-supplied line ID is
never authoritative. Amounts, VAT reconciliation and journal balance remain
deterministic responsibilities. Image-only/scanned PDF OCR is a separate
capability and is not implied by text-PDF discovery.

### Compact AI chart and counterparty context

Status: Accepted

- The whole current client chart remains searchable by the accounting AI. A
  retrieval limit or staged prompt size is an operational page size, never a
  correctness boundary that permanently hides a valid account or counterparty.
- Account-selection prompts keep candidate representation compact: the real
  chart code and real chart description are the normal candidate payload.
  Family selection likewise uses the real family code and description. The AI
  may expand into another family or search the whole selectable chart when the
  first candidate page is insufficient.
- Unrelated rules, old invoice narratives, usage counts, and historical
  explanations are not added to the prompt merely because they exist. A narrow
  confirmed rule is used only when its current trigger and scope genuinely
  match. Otherwise the AI receives clean current-document and chart context.
- The confirmed NACE code/title and a short, clearly labelled activity-research
  summary are supplied together when research exists. The NACE value remains
  the verified activity anchor; the research summary explains its practical
  business meaning without sending copied pages or long raw research text.
- Purchase processing gives the Counterparty Agent access to every selectable
  `320` supplier account; sales processing gives it access to every selectable
  `120` customer account. No arbitrary top-N cutoff may permanently exclude a
  legacy counterparty. Large lists may be paged or searched while preserving
  full access.
- Existing chart code and description, invoice title and VKN/TCKN, and any
  reliably available chart VKN/TCKN or IBAN are usable counterparty evidence.
  Cheap exact identity matches and previously confirmed client-specific
  bindings are strong signals, but the pilot does not attempt to replace messy
  legacy master data with a large brittle deterministic title-rule engine.
- When legacy counterparty evidence is ambiguous, AI prepares the best current
  match and focused review. An accountant correction becomes a client-specific
  identity binding so the same party is not repeatedly re-resolved.
- When no suitable supplier account exists, the populated draft carries a new
  counterparty proposal in the form `320.<VKN> - <invoice legal title>`. The
  system does not choose an unrelated existing supplier merely to avoid the new
  counterparty state.

### Canonical line-level accounting identity

Status: Accepted

- Product/service interpretation, research escalation, accounting treatment,
  real chart-account selection, tax treatment, and journal allocation operate
  per canonical invoice line. The first invoice line must never stand in for
  every other line on a multi-line invoice.
- Every canonical line receives an immutable `canonical_line_id` derived from
  the canonical document/version and source-line identity. The record also
  retains the UBL line ID or PDF page/row evidence, original description,
  quantity, amount, VAT behavior, and source position.
- An AI request may batch all invoice lines for efficiency and shared invoice
  context, but its structured response must return exactly one decision for
  each supplied `canonical_line_id`. Results are joined by ID, never merely by
  response order, similar wording, or array position.
- AI cannot rewrite canonical descriptions, amounts, quantities, or VAT values
  while choosing accounting meaning. Missing IDs, duplicate IDs, unknown IDs,
  or incomplete coverage fail response validation and trigger bounded retry;
  they cannot silently create a mixed or shifted journal.
- Research and additional model opinions remain attached to the affected line
  IDs or explicitly grouped equivalent-line IDs. Evidence for one line cannot
  silently change another unrelated line.
- Canonical lines remain individually traceable even when journal presentation
  aggregates compatible results. Aggregation is allowed only when account,
  semantic accounting meaning, direction, and tax treatment match. The journal
  line retains the contributing canonical-line IDs and allocated amounts.
- Line-level account coverage and mapping integrity are first-pilot quality
  gates. A balanced journal is not considered correct when a source line is
  missing, duplicated, shifted to another line, or absorbed into an unrelated
  account.

An exact buyer VKN/TCKN mismatch against the current client creates a narrow
identity warning, not a semantic escape hatch. When the identifier exactly
matches another client the reviewer is authorized to access, the UI proposes
`This invoice appears to belong to X; move it?` and requires confirmation before
moving it. Title similarity or low AI confidence cannot move or block a
document automatically.

## 5. Pilot quality targets

Status: Accepted

- Cold-start unchanged approval rate: at least 70%.
- Minor edit rate: at most 20%. Minor edits are description/note changes that
  do not change the accounting result.
- Serious/manual accounting correction rate: at most 10%.
- Similar cases covered by learned decisions: at least 90% unchanged approval.
- For an explicit, confirmed rule whose preconditions genuinely match, the
  target repeat correction rate is 0%.
- A confirmed rule must not silently fall back when its account is unavailable
  or its context has materially changed. AI re-enters immediately for the
  affected decision, prepares the best alternative draft from the current real
  context, and states why the old binding could not be applied exactly.

## 6. Semantic learning and account binding

Status: Accepted

- Accountants usually teach meaning, such as `kargo gideri`, rather than an
  exact account code.
- When the accountant gives a code, the system stores the code, chart-account
  description, and normalized semantic accounting meaning together.
- Semantic matching must tolerate Turkish characters, case, spelling,
  singular/plural, suffixes, and natural-language variations. It must not
  depend on brittle exact strings.
- Office-wide learning shares accounting meaning, not another client's account
  code.
- Each client resolves the shared meaning against its own real chart of
  accounts.
- A client-specific confirmed meaning-to-account binding may become automatic
  after validation.

Example:

- Office meaning: `Yurtici Kargo -> kargo gideri`.
- Client A binding: `760.03.010 - Kargo Giderleri`.
- Client B may use a different valid code from Client B's own chart.

## 7. Rule scope and rule interpretation form

Status: Accepted

User-facing scopes in the pilot:

- Client specific.
- Accountant-office wide.

A platform/global rule is not activated by a single accountant instruction.
It may become a separately governed Fisero candidate in a future release.

The review surface is a compact expandable rule card, not a large technical
form. Its collapsed state shows:

- Semantic rule summary.
- Scope.
- Current client account binding.
- Validation state.

Expandable rows show:

- Original accountant instruction.
- Rule scope.
- Rule type.
- Trigger/counterparty identity and direction.
- Semantic accounting result.
- Current client's chart-account binding.
- Automation behavior.
- Exceptions/safety details.
- Rule history.

Fields are editable through small, searchable selectors. Account selection
must use the client's real chart of accounts and show code plus description.

## 8. Explicit accountant rule lifecycle

Status: Accepted

1. The accountant writes an explicit instruction or asks to make a rule.
2. AI interprets the instruction and prepares the structured rule card.
3. The accountant reviews/edits the scope, trigger, semantic result, and account
   binding.
4. The rule is saved as `awaiting_first_validation`.
5. The source document used to create the rule is not also counted as its
   validation.
6. The next genuinely similar document is prepared using the rule and shown
   for one validation review.
7. If rule-relevant accounting fields are approved unchanged, the rule becomes
   active.

Rule-relevant changes include account, accounting meaning, counterparty,
direction, scope, and automation behavior. Description or internal-note edits
do not invalidate the rule validation.

If a rule-relevant field is changed, the candidate is revised and returns to
`awaiting_first_validation`.

## 9. Natural learning lifecycle

Status: Accepted

- Ordinary accountant corrections and approvals create learning events but do
  not silently activate permanent rules.
- After the first correction, the signal may improve the next similar draft
  without becoming unattended automation.
- If a second genuinely similar document is prepared consistently and approved
  without a rule-relevant change, the system may ask whether the decision
  should become a rule.
- If the accountant confirms, that independent second document counts as the
  validation; a third document is not required.
- If the second decision conflicts, no broad rule is created. The system looks
  for a meaningful scope difference.
- A rejected rule suggestion is suppressed until genuinely new evidence
  appears.
- Repetition inside one client does not silently create an office-wide rule.
  Office-wide scope requires an explicit office instruction or consistent
  evidence across clients followed by confirmation.

## 10. Rule priority and conflict handling

Status: Accepted

Default priority:

1. Explicit active client-specific accountant rule.
2. Confirmed client-specific semantic-to-account binding.
3. Accountant-office semantic rule.
4. Unconfirmed repeated-decision pattern.
5. New AI decision for the current document.

Equal-priority active rules that disagree must not be resolved silently. The
system still prepares its best draft, shows the conflicting rules, and asks an
authorized user to choose or narrow the rules.

A one-off correction does not silently overwrite an active rule. The active
rule is updated only through an explicit rule update or a separately confirmed
new pattern.

## 11. Rule exceptions and the cargo example

Status: Accepted

- A rare edge case must be detectable without designing the normal workflow
  around it.
- The word `ceza` by itself does not break a cargo rule or cause review.
- Normal transport-related return, redirection, surcharge, delivery, heavy
  cargo, VIP, or similar ancillary fees remain inside the cargo-expense
  semantic unless the accountant's chart policy explicitly separates them.
- A separate treatment is considered only when there is positive evidence of
  a materially different economic event, such as a clearly identified public
  administrative fine/recourse, compensation, or a separate material purchase.
- Strong edge-case evidence may include an official authority, administrative
  fine, recourse/compensation wording, decision/report reference, or prohibited
  shipment context. A single generic word is insufficient.
- When such an edge case occurs, normal lines continue through the active rule.
  Only the affected line receives focused review, with the best alternative
  posting already prepared.
- A single exception does not weaken or delete the main rule. An explicit
  instruction can create a child rule immediately; otherwise a repeated
  consistent exception may be proposed as a child rule.

## 12. Rule versions and states

Status: Accepted

Rule states:

- `awaiting_first_validation`
- `active`
- `paused`
- `superseded`
- `archived`

Rules are not physically deleted. Material changes create a new version and
require validation. Material changes include scope, counterparty/tax identity,
direction, semantic meaning, account binding, and automation behavior.

Display-label, alias, spelling, and internal-note changes do not require a new
validation when they do not change accounting behavior.

If an account disappears or becomes unusable, the semantic meaning remains.
The deterministic layer must not select a nearby, generic, or same-family
replacement. AI re-resolves the semantic meaning against the current full
chart of accounts. The new binding is shown for focused human review; approval
on that real affected document validates the new binding and creates the next
rule version.

## 13. Audit and accountability

Status: Accepted

Human, AI, and system actions are recorded as distinct actors. Important events
include candidate creation, human edits, confirmation, first application,
validation, activation, automatic application, blocking, update, pause,
reactivation, and archive.

Each material event records at least:

- Actor identity and actor type.
- Office/client and authorization context.
- Server timestamp.
- Source document and source instruction.
- Rule ID and rule version.
- Action performed.
- Changed fields with before/after values.
- Human reason/note when supplied.
- Application/validation result.

The user-facing rule card shows a compact, lazy-loaded timeline. Technical
pipeline details remain expandable and do not dominate the accounting UI.

## 14. Audit performance contract

Status: Accepted

- Audit is a thin evidence layer, not the main product workload.
- The hot path writes compact structured business events only.
- Large invoice content, chart plans, prompts, and AI responses are referenced
  rather than duplicated in each event.
- No remote service or new AI request runs merely to write an audit event.
- Non-critical technical enrichment is asynchronous.
- Rule history is not embedded in the main workspace payload. It is fetched
  lazily, 20 events at a time, when the user expands history.
- Business-critical rule events are never sampled. Only technical debug noise
  may be sampled or retained for a shorter period.

Pilot performance targets:

- Interactive audit-write overhead p95: approximately 25 ms or less.
- Total document-processing audit overhead: under 3%.
- First 20 rule-history events p95: under 500 ms.
- Main workspace-summary size must not grow with audit-history volume.
- Performance must be tested with at least 100,000 synthetic audit events.

## 15. AI Agents training and rule-management center

Status: Accepted

- The existing `/portal/ajanlar` page becomes the primary AI training and rule
  management center.
- A separate top-level `Learned Rules` route is not created.
- The daily document-review screen retains the small inline rule card.
- The AI Agents page shows what the agents learned, what needs confirmation,
  active learning, paused/archived rules, rule health, and useful outcome
  metrics.
- Rules remain single canonical records even when they affect multiple agent
  roles. A rule may show tags such as Document Agent, Account Agent, and
  Counterparty Agent without duplicating the rule.
- The page must show genuine learning evidence and saved work, not pretend that
  independently personified agents are being trained.

Recommended page language:

- Navigation: `AI Ajanlari`.
- Page promise: corrections and approvals teach Fisero's accounting agents.
- Action area: `Benden Ogreniyor`.
- Confirmed knowledge area: `Ajanlara Ogrettiklerim`.

## 16. Active-rule AI/research behavior

Status: Accepted

Proposed behavior:

- When a narrow, confirmed rule genuinely matches, the normal document flow
  applies the rule without asking AI/research to decide the same question
  again.
- Mechanical checks still verify identity, direction, account availability,
  balance, and hard legal/VAT constraints.
- If the rule's preconditions no longer hold, the system does not say that the
  accountant's accounting choice was rejected. It says the rule could not be
  applied exactly in the changed context.
- When an account binding is missing, closed, or unusable, AI must immediately
  re-enter for that affected accounting decision. The deterministic engine is
  prohibited from choosing a replacement account or using a generic fallback.
- AI receives the retained semantic intent, current full chart of accounts,
  client activity, counterparty identity, original rule instruction, and the
  affected document evidence, then prepares the best complete draft.
- Office-wide semantic meaning without a client account binding may still need
  AI account resolution against the current client's chart.
- Ambiguous or materially changed cases re-enter AI reasoning. External
  research is used only when the available local evidence remains insufficient.
- The account-binding failure creates one deduplicated attention item per
  client and rule. It appears in the existing Notifications surface and links
  to the affected item in the AI Agents page under `Benden Ogreniyor`.
- Repeated invoices must not create repeated copies of the same unresolved
  notification. The item closes when an authorized user confirms the new
  binding.
- Random asynchronous shadow sampling is not used in the pilot. A confirmed,
  unchanged rule is not re-questioned merely for sampling.
- AI re-evaluation is event triggered. It runs when a rule condition, account
  binding, counterparty identity, document direction/content, or accountant
  decision materially changes.
- In the first pilot, a new AI decision or an unconfirmed learning signal always
  enters `Kontrol bekliyor`; high model confidence alone does not bypass review.
- A verified active rule may bypass the review queue only when every material
  canonical line and discretionary accounting decision is covered, the
  counterparty and direction are resolved, the current chart bindings remain
  usable, tax behavior matches the document, and the complete journal passes
  line-coverage, amount, VAT and debit/credit checks. Partial rule coverage
  keeps the complete journal in review while preserving the already resolved
  lines.
- Rule-based bypass uses the ordinary visible status `Onaylandi` with the
  secondary explanation `Dogrulanmis kuralla otomatik`. It is never recorded as
  a new human click: audit stores the system actor, rule ID/version, automation
  time, and the authorized accountant who originally confirmed the rule.

The accepted pilot contract is no deterministic account fallback, immediate AI
re-entry for the affected decision, deduplicated notification and AI Agents
attention routing, and event-triggered re-evaluation only.

### Generic-line semantic escalation

Status: Accepted

When a product/service line remains genuinely generic after ordinary local
interpretation, the system escalates for decision quality rather than escaping
to a missing-information state:

1. The primary accounting interpretation uses the line, seller/company and
   brand identity, client activity, VAT behavior, historical decisions,
   confirmed semantic rules, and the current full chart of accounts.
2. If the meaning still cannot be resolved and the ambiguity can materially
   change the account, the Research Agent searches minimized public supplier,
   brand, and product/service information under the accepted privacy boundary.
3. If the first research result remains insufficient or conflicts with local
   evidence, the same uncertainty event may obtain up to three independent
   research results and up to three independent accounting-model opinions.
   Escalated calls run in parallel where practical and share normalized cached
   evidence.
4. A final synthesis evaluates evidence quality, client context, and valid chart
   accounts. It does not blindly use provider majority voting.
5. If no external source resolves the phrase, Fisero still writes the strongest
   defensible complete journal and explains that the available description was
   very general. The unresolved detail becomes a focused review reason, not a
   deterministic fallback, empty line, or `Ek bilgi/belge gerekli` status.

The visible product continues to have four logical roles: Document, Account,
Counterparty, and Research Agent. The additional independent calls are bounded
model/provider opinions behind those roles, not six new user-facing agents.
Known confirmed rules and already-strong local evidence bypass this escalation.

## 17. AI outage and provisional deterministic draft

Status: Accepted. New provider admission remains separately governed by
benchmark, privacy, structured-output, and cost-control requirements.

When an accounting decision requires AI but every configured provider is
temporarily unavailable, the system uses a special outage-only behavior:

- AI unavailability does not pause or downgrade a verified active rule whose
  complete current preconditions can be resolved from canonical document data,
  confirmed client/counterparty identity, and the current chart. When every
  material line and discretionary decision is covered and the mechanical gates
  pass, normal rule-based automatic approval continues and is labelled
  `Dogrulanmis kuralla otomatik`.
- The provisional outage path is used only for decisions that genuinely remain
  AI-dependent. Deterministic rule matching applies previously confirmed
  structured meaning; it does not invent a new semantic/accounting decision.
- Partial rule coverage is preserved, but any uncovered material line or
  unresolved counterparty/account decision that requires unavailable AI keeps
  the complete journal in the provisional outage/review path.

- The document is not left empty.
- Existing deterministic logic prepares the best provisional journal draft it
  can, including all fields and lines it can support.
- This exception does not authorize deterministic logic to pretend it made a
  reliable AI/accounting selection. The draft is explicitly stamped as
  `ai_unavailable_provisional` and `deterministic_outage_fallback`.
- In the document-status position that normally says `Fis hazir`, the outage
  draft says exactly `Ajan olmadan hazirlanmis`.
- The document list and review screen also explain:
  `AI ajanina su anda ulasilamiyor. Bu gecici taslak ajan olmadan hazirlandi ve
  otomatik olarak yeniden denenecek.`
- The user-facing explanation states that provider unavailability caused the
  lower-quality draft. Expandable technical details may show provider names,
  failure category, attempt time, and next retry time, but not secrets or raw
  sensitive provider responses.
- The provisional draft is not eligible for unattended automation or export.
  An authorized accountant may still review, edit, approve, or reject it. A
  valid human approval becomes the authoritative resolution and may reopen the
  normal downstream workflow when deterministic hard gates pass.

### Provider order within one attempt

- Try each configured, benchmark-approved provider once in the task-specific
  ordering before declaring the attempt unavailable. Task ordering may only
  reorder providers already admitted by the configured base chain.
- Default semantic ordering is `Groq -> Cerebras -> OpenRouter`; canonical PDF
  extraction and counterparty resolution prefer
  `Cerebras -> Groq -> OpenRouter`. Statement work preserves the configured
  base ordering. Environment overrides may reorder admitted providers per task.
- Gemini is a candidate additional provider, but a free quota alone is not an
  admission criterion. A provider may enter the production chain only with
  valid credentials, cost controls, structured-output compatibility, accepted
  accounting-quality evidence, and approved data-use/retention terms.
- Do not repeatedly call the same failed provider inside one interactive
  request. Provider failover must have bounded timeouts so the document is not
  held indefinitely.

### Ownership and overwrite protection

- Merely opening or viewing the document creates no edit lock and does not
  permanently stop AI retry. The first meaningful accounting edit acquires a
  short, renewable server-side edit lease. The accepted idle timeout is 5
  minutes, renewed only by recent user activity in a visible document tab. A
  tab being left open or running a background heartbeat is not sufficient.
- An AI retry may finish during this short lease, but it must not overwrite the
  draft currently visible to the accountant. The result is saved as a candidate
  revision and surfaced as `AI surumu hazir` when the lease ends or the user
  refreshes.
- Automatic replacement stops authoritatively only when an accounting field is
  actually changed and saved, the document is approved, or the document is
  rejected. In this contract, rejection means removing the document from the
  export list.
- If the accountant opens the document and leaves without saving or deciding,
  the short lease expires and AI retries/replacement continue.
- AI may replace the provisional draft only when the accounting revision is
  unchanged and no authoritative manual decision has occurred.
- If an AI result arrives after manual intervention, it is not applied over the
  user's work. The ignored result and reason are recorded in audit evidence.
- If the document remains untouched, a successful retry creates a new draft
  revision, removes the provisional stamp, and notifies the user that the AI
  draft is ready.

### Human editing, AFK takeover, and revision conflicts

Status: Accepted

- Viewing remains concurrent: multiple authorized office users may open and
  inspect the same document without blocking one another.
- The first meaningful edit acquires the edit lease. While the lease is active,
  other users may view the document but may not edit it through the normal
  flow. The UI identifies the active editor without exposing unnecessary
  personal data.
- Meaningful activity includes accounting-field interaction and document work;
  a hidden/background tab does not renew the lease merely by sending a timer.
  The editor receives an expiry warning at approximately minute 4. After 5
  minutes of inactivity, the lease expires automatically.
- Edits are debounced into a recoverable working revision. A user who takes over
  an expired lease starts from the latest successfully saved working revision,
  with the previous editor and save time visible.
- Every mutation, final save, approval, rejection, or reopen request carries an
  `expected_revision` (or equivalent base-version token). The server performs
  an atomic compare-and-update. A stale lease token or stale revision is
  rejected with a conflict response and can never overwrite a newer revision.
- If the first editor returns after another user has changed or approved the
  draft, the old screen becomes stale/read-only. It explains who changed the
  record and offers to reload the current revision or compare/copy any local
  unsaved input. It does not merge accounting decisions automatically.
- An approved journal cannot be changed from an old browser tab. Further work
  requires an explicit `Reopen for correction` action that creates a new
  version and preserves the approved version and its audit evidence.
- After lease expiry, any user with `can_review_accounting` and client access may
  take over normally. Before expiry, forced takeover is restricted to the
  accountant/office administrator, requires confirmation and a reason, and is
  audited.
- Performance-sensitive presence heartbeats and keystrokes are not appended as
  individual audit records. Audit stores meaningful transitions only: lease
  acquired/expired, forced takeover, authoritative revision saved, approval,
  rejection, conflict, and reopen.
- Current repository truth: worker/scheduler lease behavior exists for QNB
  processing, but this human-review edit-lease plus optimistic-concurrency
  contract is a planned implementation requirement, not a claim that the full
  protection is already implemented.

### Shared review queue and optional assignment

Status: Accepted

- New documents enter a shared office review queue and are not required to be
  assigned to an employee before work can begin.
- Starting an edit makes the user the temporary active editor under the lease
  contract above; it does not create a permanent task assignment.
- Offices that need workload planning may optionally assign a responsible user
  to a document. Small offices may operate entirely without assignments.
- Assignment does not hide the document or remove access from other authorized
  reviewers. The normal AFK takeover and revision-conflict rules continue to
  apply.
- An office administrator may change or clear the responsible user. The audit
  trail records assignment changes, but accounting responsibility is attributed
  to the user who actually edited, approved, rejected, or reopened the revision.
- Automatic round-robin distribution is outside the first pilot. The shared
  queue and optional assignee are the pilot contract.

### Reopening approved and externally delivered journals

Status: Accepted

- An approved journal that has not yet been delivered to an external accounting
  system may be reopened for correction by a user with
  `can_review_accounting`. Reopening requires a reason, preserves the approved
  revision, creates a new working revision, and returns the document to
  `Kontrol bekliyor`.
- A journal already delivered to Zirve or another external system cannot be
  silently reopened through the normal review action. It requires the stronger
  `can_reopen_delivered_accounting` permission, granted by default to the
  accountant/office administrator.
- The delivered revision remains immutable. Reopening creates a correction or
  reversal candidate and, when direct integration exists, enters an explicit
  external-reconciliation flow rather than rewriting history.
- Audit evidence records the actor, reason, prior approved/delivered revision,
  new correction revision, timestamps, and later reconciliation outcome.
- Direct Zirve delivery is not part of the first pilot, but the state and
  revision model must preserve this distinction now so it can be added without
  changing the accounting-history contract later.

### Atomic journal approval for multi-line invoices

Status: Accepted

- Review work may proceed line by line. Edits, issue markers, and recoverable
  working progress are saved so already-correct lines do not need to be reviewed
  repeatedly.
- Authoritative accounting approval applies to the complete journal, not to
  independently approved fragments. A document cannot be partly `Onaylandi`
  while another line remains `Kontrol bekliyor`.
- Final approval validates the journal as one accounting record, including its
  accounts, VAT behavior, debit/credit balance, totals, required counterparties,
  and applicable deterministic hard gates.
- If one line remains unresolved, the entire journal stays `Kontrol bekliyor`,
  or becomes `Ek bilgi/belge gerekli` when resolution genuinely depends on new
  external evidence. The completed work on other lines remains preserved.
- No partial journal is eligible for export or later direct delivery to Zirve.
  External delivery consumes one authoritative approved revision.

### Human-only missing-information action in the pilot

Status: Accepted

- AI, research, extraction, and deterministic components cannot set
  `Ek bilgi/belge gerekli`; only a user with `can_review_accounting` may select
  it after inspecting the document and prepared journal.
- The canonical review surface does not add another permanent top-level button.
  `Onayla ve gec` remains the primary action. `Ek bilgi/belge gerekli`,
  `Kontrol icin beklet`, `Yeniden isle`, and `Cikti listesine ekleme` are grouped
  under one compact `Diger islemler` menu.
- Selecting the state opens a small structured form for the exact missing item
  and note. Pilot reason families are limited to a human-unreadable source,
  genuinely missing essential page/attachment, or transaction information the
  accountant confirms cannot be derived. This action preserves the prepared
  draft and its evidence.
- In the pilot, this is an internal office state. Fisero does not automatically
  contact the client or require the client to upload again. The accountant
  obtains the item through the office's existing method and attaches or records
  it against the existing document.
- A later phase may send the structured request by Fisero-managed email or
  WhatsApp and bind the reply/attachment to the same document. That future
  channel does not expand the pilot scope.

### Accepted retry schedule

- One normal processing attempt tries the configured provider chain.
- If all configured providers fail, retry after approximately 2 minutes.
- The subsequent delays after each failed full-chain attempt are approximately
  5 minutes, 10 minutes, 15 minutes, 30 minutes, 2 hours, and 6 hours. Small
  jitter prevents simultaneous retry spikes without materially changing the
  accountant-facing schedule.
- After reaching the 6-hour cadence, retry no more frequently than every 6 hours
  until the 24-hour manual-attention threshold. Any successful full-chain
  attempt closes the outage episode and cancels later retries.
- Stop automatic replacement immediately after a saved accounting change,
  approval, or export-list rejection. A temporary presence lease only defers
  visible replacement.
- After 24 hours without success, stop frequent automatic retries and mark the
  item `manual_attention_required`. A manual retry and provider-recovery retry
  remain available.

### Notifications and urgency

- Create one deduplicated notification per affected document and outage
  episode, not one notification per provider attempt.
- Initial notification copy stays calm and clear:
  `AI ajanina su anda ulasilamiyor. Gecici taslak ajan olmadan hazirlandi; sistem
  bir sure sonra yeniden deneyecek.`
- While an accounting-agent outage is active, the main page shows a system
  banner: `AI ajanlarina su anda ulasilamiyor. Bazi belgeler ajan olmadan gecici
  olarak hazirlaniyor; sistem yeniden deneyecek.` The banner closes
  automatically after recovery and does not multiply per document.
- Product notifications describe affected agent capabilities, not the number of
  infrastructure providers. The four visible roles are `Belge Ajani`, `Hesap
  Ajani`, `Cari Ajani`, and `Arastirma Ajani`, each with `Calisiyor`, `Sinirli`,
  or `Ulasilamiyor` health.
- If only research infrastructure fails, the product says `Arastirma Ajani
  sinirli`; it does not falsely claim that every agent is unavailable. If the
  shared accounting provider chain fails, the affected document/account/
  counterparty roles are shown together. Provider names remain in expandable
  technical/operations details.
- Normal severity: retry is scheduled and the document is not selected for an
  immediate downstream operation.
- High severity: the document has waited more than 2 hours, is selected for an
  imminent export/work batch, or the same outage affects at least 10 documents.
- Operational critical severity: all providers remain unavailable for at least
  6 hours or the unresolved AI backlog reaches at least 50 documents. This is
  primarily an office administrator/operations alert, not repeated noise for
  every accountant.
- Send deduplicated technical-service incident email to
  `keremerdogdu92@gmail.com`. The pilot may keep this destination hard coded;
  the production design moves it to configuration (for example
  `FISORA_TECH_ALERT_EMAIL`) and may deliver through the planned Brevo
  integration.
- The accepted email escalation timing is incident based:
  - Send an early technical warning after the complete accounting-provider
    chain has remained unavailable for 15 continuous minutes.
  - Send a critical follow-up when the outage reaches 6 hours or the unresolved
    AI backlog reaches 50 documents.
  - Send one recovery message when the provider chain becomes healthy again.
  - Do not send repeated messages for individual documents, providers, or retry
    attempts inside the same incident.
- The technical email is incident based, not document/provider based. It
  includes incident start, affected agent capabilities, provider failure
  categories, affected-document count, oldest waiting item, retry status, and
  an operations link, without invoice contents, credentials, or raw sensitive
  provider responses.
- The notification links to the affected document. System-wide outage details
  are also visible in the operations/readiness surface.

## 18. Hermes Agent and expanded provider architecture

Status: Product role accepted - implementation boundary and provider admission
still require architectural validation

### Architectural role

- Hermes Agent is not another inference provider like Groq, Cerebras, Gemini,
  or an OpenRouter-routed model. It is an agent runtime/orchestration layer that
  can use model providers, tools, MCP connections, memory, skills, and separate
  profiles.
- Fisero must not route the synchronous core accounting hot path through Hermes
  in the first integration. Doing so would add latency and another failure,
  memory, and audit boundary around the product's most critical decision path.
- Hermes is accepted as the runtime candidate for a controlled in-product
  `Musavir Yancisi`, not merely a hidden Research/Operations sidecar. The
  companion may investigate genuinely ambiguous documents, complete missing
  context, coordinate bounded research, explain decisions, summarize pending
  work, and guide an office worker through Fisero. It does not replace the four
  visible logical accounting agents or become the canonical accounting engine.
- Final journal-posting choices, KDV and balance rules, client-specific account
  bindings, rule approval, audit history, and export gates remain canonical in
  Fisero.
- Hermes memory and self-created skills must not become a parallel canonical
  accounting-learning store. Fisero's versioned, approved learning rules remain
  the source of truth. Any Hermes skill write affecting accounting behavior
  requires an explicit human approval gate and auditable promotion into Fisero.
- Hermes may read tenant-scoped learning evidence and propose a narrow,
  structured deterministic-rule candidate. The proposal includes semantic
  meaning, scope, match conditions, exclusions, supporting correction/approval
  events, and the account binding where applicable. Hermes cannot activate the
  rule; Fisero validates the structure and the accountant confirms it through
  the normal rule-review form.
- The first release starts with one recognizable office companion and a common
  core personality. As new office users are created, each user receives an
  isolated personal session and preference layer; small personality and
  communication-style differences may develop without fragmenting verified
  office knowledge or changing accounting policy.
- The identity and knowledge model is hybrid:
  - the visible character, core behavior, verified office terminology, approved
    semantic knowledge, and published Fisero usage guidance are shared;
  - personal conversation history, verbosity, frequently used views, working
    preferences, and non-authoritative reminders are isolated per office user;
  - client-specific account bindings, approved rules, journal history, and
    permissions always come from Fisero's tenant-scoped canonical store rather
    than free-form Hermes memory;
  - one user's unapproved interpretation or preference never silently becomes
    office knowledge.
- The companion is contextual rather than being only a separate chat page. A
  small, non-obstructive character may live at the screen edge and open a side
  drawer for conversation. Its calm, working, result-ready, and
  approval-required states may be visible, but it must not interrupt routine
  review work or generate unsolicited animation/noise.
- The default proactive posture is almost silent. Unless an issue is genuinely
  critical, the companion stays still at the edge and joins the work only when
  the user opens it. A critical condition may produce one restrained visual
  pulse or badge, without sound, repeated animation, modal interruption, or
  replacing the canonical Fisero notification/incident surface.
- Non-critical proactive suggestions are an adaptive, tightly rate-limited
  pilot capability. The companion may occasionally test a suggestion in a
  context where the same user previously chose to open a similar suggestion,
  but its optimization objective is useful intervention rather than engagement,
  conversation length, or click volume. The initial default is at most one such
  experimental suggestion per office user per working day; the office or user
  can reduce this to zero. Repeatedly ignored, immediately dismissed, or
  unhelpful suggestions suppress that suggestion/context family instead of
  increasing its intensity. Exact promotion and suppression thresholds are
  calibrated from pilot evidence rather than treated as accounting rules.
- Proactive usefulness is measured with privacy-minimized product events:
  suggestion category and context fingerprint, time shown, whether the
  companion was opened from it, time-to-open, whether a relevant question was
  asked or proposed action was inspected, dismissal/ignore, and whether the
  underlying task was completed. Raw conversation content is not copied into
  analytics merely to measure a click. A click alone is not success, and lack
  of a click is not automatically failure; repeated patterns and task outcome
  determine whether the timing was useful or annoying.
- Passive presence, animation decisions, badges, and proactive-trigger
  eligibility use existing Fisero state/events and do not themselves call a
  model. Opening the drawer allows ordinary AI-backed conversation. Generic
  screen guidance uses maintained product guidance/retrieval first and only
  calls an approved low-cost model when synthesis is useful. Invoice-specific
  explanation may use the appropriate accounting context, but it receives a
  bounded screen/document summary rather than the entire office history.
- Companion consumption is accounted separately from journal-preparation and
  research capacity. The office has a configurable companion budget with
  visible usage and warning thresholds; proactive background model calls are
  forbidden. When the companion budget is exhausted, canonical invoice
  preparation is not sacrificed: static screen guidance remains available and
  the chat clearly reports that new AI conversation capacity is temporarily
  unavailable. Conversation history is summarized and bounded, common screen
  explanations may be safely cached by screen/version, and each user may start
  a fresh context without deleting canonical Fisero knowledge.
- The companion is a Fisero/accounting work assistant, not an unrestricted
  social-chat benefit. Brief greetings, thanks, and light conversational tone
  are allowed, but sustained requests unrelated to Fisero, the user's current
  office work, accounting/tax workflow, supported document research, or product
  help are politely redirected without continuing a long exchange. This scope
  is enforced both in the companion policy and by per-user/session usage limits;
  it is not left only to a prompt that users can easily bypass.
- Work-relevance decisions should be forgiving around ordinary human language:
  a user may explain context, ask a short follow-up, or use humor while solving
  a real task. The system restricts repeated clearly unrelated conversation,
  not personality. A borderline request receives a concise answer only when it
  helps return to the work context; repeated off-topic turns are stopped with a
  clear invitation to continue with the invoice, rule, screen, or office task.
- Companion allowances are hierarchical: a protected office-wide budget, a
  per-user rolling allowance, and a bounded active-conversation allowance.
  Reaching a personal/off-topic limit never consumes reserved journal or
  research capacity. Only an office accountant/administrator with the dedicated
  `can_manage_companion_policy` permission may expand general-conversation
  allowance, choose eligible users, or raise companion budgets. Changes are
  explicit, time-bounded where practical, visible in usage reporting, and
  audited; ordinary office users cannot raise their own allowance.
- The pilot default keeps general conversation low but comfortable: ordinary
  human conversation around a workday is allowed, while sustained unrelated
  chat is progressively redirected and eventually paused. It must not feel
  suffocating, and it must not support unlimited social use. Exact
  token/message ceilings are configuration values calibrated with real usage
  rather than frozen into the product contract. The dashboard reports companion usage by
  work-help versus general-conversation category, without exposing private chat
  content to office-wide analytics. It warns the authorized accountant before
  an expanded allowance can materially affect the office budget.
- Hermes technically supports persistent curated `USER`/agent memory, searchable
  prior sessions, per-profile personality, and independent profile state. Fisero
  uses those capabilities behind its own authenticated user identity and memory
  policy; the companion recognizes a person from the Fisero user/session ID,
  never by guessing identity from writing style, device fingerprints, or
  invoice contents.
- Each user can choose and later change a companion relationship mode without
  changing accounting permissions or office policy:
  - `Sadece Is` keeps the relationship concise and professional;
  - `Dengeli Is Arkadasi` is warm, conversational, and work-centred and is the
    recommended default;
  - `Yanci/Ahbap` permits more personal continuity and informal conversation
    within the user's general-conversation allowance.
  The companion adapts tone and memory depth rather than pretending that three
  unrelated accounting agents exist.
- Personal learning is allowed for compact and genuinely useful preferences
  such as the user's name and office role, preferred explanation length and
  tone, familiar terminology, commonly used views, accessibility/interaction
  preferences, interests voluntarily discussed, and which categories of
  proactive suggestion the user usually opens or ignores. In `Yanci/Ahbap`
  mode, the private companion memory may also retain personal context and the
  user's opinions or comments about people when this provides the continuity
  the user asked for.
- A personal comment about another person is stored, when appropriate, as the
  speaker's subjective recollection or opinion—not as a verified fact about the
  third party. It is visible and reusable only inside that speaker's private
  companion context; it cannot alter what another user's companion believes,
  be surfaced to the person discussed, influence permissions/performance
  analytics, or silently enter shared office knowledge. Particularly sensitive
  personal information is not made durable merely because it appeared once;
  explicit remembrance or confirmation is required where the privacy impact is
  material.
- Personal companion memory and Fisero professional memory are separate stores
  with separate authorization. Personal memory must not contain passwords/API
  keys, raw invoice/document contents, client account bindings, authoritative
  journal decisions, or unapproved accounting rules. Durable accounting
  learning is promoted only through Fisero's structured rule and approval
  workflow; it is never inferred as authoritative merely because it appeared
  in a conversation.
- Personal-memory writes are observable and reversible. The user can see in
  plain language what the companion remembers about them, correct an entry,
  delete an entry, disable new personal learning, or reset their companion
  profile without deleting office or canonical accounting knowledge. A memory
  that changes permissions, office-wide behavior, or accounting treatment
  always requires the existing authorized approval path; Hermes' unrestricted
  default auto-write mode is not used for such records.
- Raw session history and curated personal memory are separate. Fisero may keep
  bounded recent conversation history so the user can continue a work thread,
  but it is not an indefinite employee-surveillance archive. Curated preferences
  can outlive a chat only until the user removes them, the profile is reset, or
  the user's office access ends.
- In the initial private-companion policy, each worker can inspect only their
  own personal memory and conversations. An accountant/office administrator can
  see aggregate usage and policy state but not private content. A future
  `managed office conversation` option may permit authorized office access only
  with a defined business purpose, legal basis, advance in-product disclosure,
  clear scope and retention, access logging, and visible indication to affected
  users. It must not retroactively expose conversations or memories that were
  created under a promise of private access. Legal/security preservation and
  disclosure requests remain a dedicated privacy design and legal review item.
- The pilot may use one pinned Hermes runtime with Fisero-enforced user/tenant
  memory namespaces rather than running a full operating-system process for
  every employee. Native Hermes profiles can support later isolation and
  personality packaging, but a Hermes profile is state separation rather than a
  security sandbox; Fisero authorization remains mandatory at every tool and
  data boundary.
- The companion can explain the currently open Fisero screen: what the page is
  for, what visible fields and statuses mean, why an action is available or
  unavailable, how to complete the current task, and—when a document is
  selected—what Fisero currently understood and which evidence supports it.
  This is a first-class product capability, not a generic chatbot fallback.
- Screen understanding uses a permission-filtered `screen context manifest`
  produced by Fisero as its primary source. The manifest contains the route and
  screen version, visible component/field identifiers and labels, current
  status, enabled actions, selected canonical entity references, focused field,
  validation messages, and links to the matching product guidance. It contains
  only data already visible and authorized for that user. The companion cannot
  inspect hidden form values, browser storage, another tab, another tenant, or
  arbitrary application state.
- A screenshot/vision reading of the visible Fisero surface may be offered only
  as a deliberate user-triggered diagnostic aid when the structured manifest
  cannot explain a visual/layout problem. It is not the default navigation or
  accounting-evidence channel, is cropped to the Fisero surface, follows the
  same provider-data policy, and is not retained as companion memory.
- Context must be refreshed on route, selected entity, revision, permission, or
  material screen-state change. Every answer is bound to that context version;
  if the screen changes while the answer is being prepared, the companion says
  that the context changed instead of presenting stale instructions as current.
- The initial companion is read-mostly, tenant-scoped, permission-aware, and
  evidence-citing. It may expose three bounded workflows first: `Secili faturayi
  acikla`, `Arastir ve kural adayi hazirla`, and `Bugun ne var?`. Any action that
  changes a document, rule, account binding, assignee, or export state is an
  explicit Fisero tool call with a preview and the same confirmation,
  authorization, revision, and audit rules as the ordinary UI. Conversation
  text alone never performs a write.
- Separate Hermes profiles may later isolate personal companions, Research, and
  Operations runtimes. Tenant/client separation, retention, permissions, tool
  authorization, and trace correlation must be proven before production invoice
  data is exposed. Fisero should initially pin an upstream Hermes version and
  integrate through a narrow plugin/MCP/tool gateway; it should not maintain a
  broad fork unless the supported extension surfaces cannot enforce these
  boundaries.

Official research references:

- Hermes overview and runtime capabilities:
  <https://hermes-agent.nousresearch.com/docs/>
- Hermes agent-managed skills and write approval:
  <https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/>
- Independent Hermes profiles:
  <https://hermes-agent.nousresearch.com/docs/user-guide/profiles/>
- KVKK transparency duties for personal-data processing:
  <https://www.kvkk.gov.tr/Icerik/2033/Aydinlatma-Yukumlulugu->
- KVKK employee-account access/monitoring decision example:
  <https://www.kvkk.gov.tr/Icerik/7593/2023-86>

### Provider candidates and free-tier policy

- Provider discovery and invoice-data eligibility are separate. `freellm.net`
  is used only as a discovery catalog; Fisero never sends prompts, invoices, or
  API keys through it. Every candidate is integrated directly and accepted only
  after its official terms, privacy behavior, quota, output contract, and
  accounting benchmark are verified.
- The expanded raw-invoice candidate chain is `Groq -> Cerebras -> Cloudflare
  Workers AI -> SambaNova -> OpenRouter ZDR allowlist`. This is a candidate pool,
  not permission to call every provider for every document. Health-aware
  circuit breakers skip unavailable or exhausted providers and the first valid
  benchmark-approved result wins.
- This candidate membership/order is accepted for benchmarking. Individual
  models and providers enter the active chain only after Section 20 admission.
- Synthetic invoices are not used as the primary product/accounting validation
  set. The pilot benchmark and accountant acceptance work use real invoices from
  the participating accountant's known clients, with appropriate authority and
  provider-data eligibility. A provider that cannot accept that data does not
  count as invoice-pipeline capacity.
- A sanitized development lane may still exist for narrowly bounded auxiliary
  work, but it is not presented to the accountant as proof that Fisero prepares
  real journal drafts correctly.
- Free tiers are benchmark/development capacity, not a production continuity
  SLA. Published model limits change and actual project/organization limits
  must be read from each provider console.
- Gemini is technically easy to integrate through its OpenAI-compatible API and
  supports structured output. Under Google's current terms, Turkey does not
  receive the EEA/Switzerland/UK unpaid-service exception. In unpaid Gemini/API
  usage, Google may use prompts and responses to improve products, human
  reviewers may process them, and Google explicitly says not to submit personal,
  sensitive, or confidential information. Development status, a single
  accountant, temporary storage in Fisero, or later deletion from Fisero does
  not change that provider-side contract.
- Therefore unpaid Gemini may process only synthetic data or a locally sanitized
  accounting projection. Sanitization removes or substitutes names, VKN/TCKN,
  MERSIS/trade-registry values, addresses, phones, emails, IBAN/payment data,
  invoice identifiers/UUIDs, QR/signature payloads, attachments, and any free
  text capable of re-identifying the commercial relationship. Necessary
  accounting structure such as direction, generalized line meaning, tax rate,
  currency, and bucketed amounts may remain only when the combination cannot
  reasonably identify a party or real transaction.
- Because synthetic invoices are excluded from the main validation strategy,
  unpaid Gemini is not part of the accounting-provider benchmark or fallback
  chain. A future optional `line semantics lab` may send only locally approved,
  generic product/service phrases with no identifying or confidential content.
  Its permitted tasks are abbreviation expansion, generic product-versus-service
  classification, line normalization, and candidate public search-term
  generation. It cannot select the final account or claim full-draft quality.
- This optional Gemini line path is deferred. The current code can add another
  OpenAI-compatible accounting provider cheaply, but line-only Gemini needs a
  separate payload contract, local sensitive-data detector, rejection policy,
  result mapping, and evidence/audit path. Groq, Cerebras, Cloudflare, and other
  real-data-eligible providers can perform the same line task with the complete
  accounting context, so the expected incremental value does not currently
  justify that implementation effort.
- An active Cloud Billing project changes Gemini API use to the paid-service
  data contract, under which prompts/responses are not used to improve Google
  products. It can still generate charges; budget alerts are not a guaranteed
  hard spending cap. This option is not treated as zero-budget capacity.
- OpenRouter free models are useful for development and emergency experiments,
  but their published low limits are not suitable as a dependable production
  fallback. Production routing requires an explicit model/provider allowlist
  and Zero Data Retention enforcement.
- Groq and Cerebras remain direct low-latency candidates, subject to the same
  accounting benchmark, schema, privacy, credential, rate-limit, and operations
  gates. Cerebras currently states that service content is not used for model
  training and that inference inputs/outputs are not retained; it is therefore
  a stronger real-data free-tier candidate than unpaid Gemini.
- Cloudflare Workers AI is a strong additional real-data candidate. Its current
  terms state that Customer Content is not used to train models or improve
  Cloudflare/third-party services without explicit consent, and its free plan
  includes 10,000 Neurons per day. Exact document capacity depends heavily on
  the selected model and prompt/output size, so it is measured with Fisero's
  real prompt envelope rather than advertised request counts.
- SambaNova is another direct candidate. Its current free tier publishes 20
  requests/day and 200,000 tokens/day for production-designated models such as
  `gpt-oss-120b`; its terms limit Customer Content processing to providing the
  service or legal requirements. It remains subject to accountant/client notice
  and consent requirements before personal data is processed.
- Mistral Free can be useful in the sanitized benchmark lane. Its Studio Free
  documentation says input/output may be used for training but permits opt-out;
  Labs models can use data regardless of the opt-out. Do not promote it to the
  raw-invoice chain until the organization privacy controls are verified,
  training is disabled, Labs models are excluded, and retention is accepted.
- NVIDIA API Catalog is only for internal testing/evaluation, expressly excludes
  confidential, sensitive, and personal data, and may use content to improve
  NVIDIA products/models. It is sanitized-test-only. GitHub Models is likewise
  positioned by GitHub for learning, experimentation, and proof of concept and
  is not a production failover.
- OVHcloud AI Endpoints and Scaleway Generative APIs are explicitly excluded
  from the candidate pool. Their time-limited allowance and/or payment-method
  exposure do not justify integration and benchmark effort for the zero-budget
  development phase.

Official research references:

- Gemini pricing/data-use distinction:
  <https://ai.google.dev/gemini-api/docs/pricing>
- Gemini OpenAI compatibility and structured output:
  <https://ai.google.dev/gemini-api/docs/openai> and
  <https://ai.google.dev/gemini-api/docs/structured-output>
- Groq rate limits and data controls:
  <https://console.groq.com/docs/rate-limits> and
  <https://console.groq.com/docs/your-data>
- Cerebras free pricing and rate limits:
  <https://inference-docs.cerebras.ai/support/pricing> and
  <https://inference-docs.cerebras.ai/support/rate-limits>
- Cerebras data terms and privacy:
  <https://www.cerebras.ai/terms-of-service> and
  <https://cloud.cerebras.ai/privacy>
- Cloudflare Workers AI data usage and free allocation:
  <https://developers.cloudflare.com/workers-ai/platform/data-usage/> and
  <https://developers.cloudflare.com/workers-ai/platform/pricing/>
- SambaNova free limits and content terms:
  <https://docs.sambanova.ai/docs/en/models/rate-limits> and
  <https://sambanova.ai/hubfs/23945802/PubSec/fast-api-program-tos.pdf>
- Mistral API privacy controls and free-mode purpose:
  <https://docs.mistral.ai/admin/monitor-comply/privacy-data-controls> and
  <https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them>
- NVIDIA API trial terms and GitHub Models responsible use:
  <https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf>
  and
  <https://docs.github.com/en/github-models/responsible-use-of-github-models>
- Free-provider discovery catalog:
  <https://freellm.net/>
- OpenRouter pricing, production guidance, and ZDR:
  <https://openrouter.ai/pricing>, <https://openrouter.ai/docs/faq>, and
  <https://openrouter.ai/docs/guides/features/zdr>

## 19. Internet research provider pool

Status: Accepted architecture - activation still requires benchmark evidence

### Product boundary and query minimization

- Internet research remains uncertainty-triggered. Known rules and confident
  local evidence do not spend research quota.
- Research providers never receive the invoice file, complete XML/PDF, journal
  draft, chart of accounts, client identity, invoice identifiers, amount, tax
  totals, payment data, or unrelated line items.
- A permitted request contains only the minimum public-information question: a
  generic product/service phrase, a public corporate supplier/brand name when
  required, and a non-identifying activity category. A sole-proprietor personal
  name is treated as personal data rather than an ordinary public brand.
- The current repo already removes several VKN/TCKN/ETTN, invoice-number, IBAN-
  shaped, and amount patterns through `sanitize_research_query`, but this is not
  a complete DLP boundary. Before provider chaining, expand it for email, phone,
  address, person-name/sole-proprietor, plate, contract/order/serial numbers,
  QR fragments, and configurable deny patterns. Unsafe queries fail closed and
  remain local/reviewable.
- Search results are evidence, not accounting truth. The existing source policy,
  official/manufacturer preference, research cache, confidence split, and
  accountant override remain provider-independent.

### Candidate order

- Keep Tavily as the proven baseline while alternatives are benchmarked. Its
  current free Researcher plan includes 1,000 API credits per month without a
  credit card.
- First alternative: Linkup. It advertises 4,000 free queries, structured and
  sourced answers, and Zero Data Retention on every plan. This is the strongest
  immediate Tavily failover candidate.
- Second alternative: Exa Search. It currently advertises up to 20,000 free
  requests per month plus search and page-content extraction. Exa announces ZDR
  across search products, while its pricing page also lists ZDR in enterprise
  features; therefore free-account ZDR must be verified in the actual account
  before any non-public query. With Fisero's public-only minimized queries, it
  remains a high-value benchmark candidate.
- Supporting fetch/reader: Jina Reader/Search. New keys receive 10 million free
  tokens; Reader converts selected source URLs to LLM-friendly text and Jina
  states a zero-data-retention API policy. It is valuable after search for
  extracting official pages, not necessarily as the sole ranking provider.
- Additional monthly fallback: Firecrawl Free currently includes 1,000 credits
  per month; search costs two credits for up to ten results and it can fetch
  difficult pages. Free-plan ZDR is not generally available, so only public URLs
  and minimized public queries are permitted.
- Lower-priority capacity: Brave Search offers $5 monthly free credits, equal to
  roughly 1,000 basic searches at current pricing, but requires a card, retains
  query records for up to 90 days, and its standard plan limits result-storage
  rights. It is unsuitable for silently persisting raw search responses into
  Bilgi Havuzu without confirming the selected plan's storage grant.
- Development-only trials: Serper grants 2,500 free queries without a card but
  this is an initial grant rather than proven recurring capacity; SerpAPI offers
  250 searches per month and excludes ZeroTrace from its free plan. Neither is
  a preferred production research provider.

Proposed research pool after benchmark:

`Tavily -> Linkup -> Exa -> Jina/Firecrawl source fetch`

The fallback chain is bounded: one uncertainty event creates one deduplicated
research job, providers with exhausted quota or open circuit are skipped, and
equivalent normalized queries share cached evidence. Normal uncertainty uses
the first adequate result. Only the accepted generic-line escalation may fan
out to at most three independent research results when the first result remains
insufficient or conflicting; providers are never called merely to consume free
quota.

### Current repo impact

- `ResearchProvider` already provides a narrow adapter contract and Tavily has a
  concrete implementation.
- `build_research_runtime_from_env` currently selects a single provider, unlike
  the accounting provider fallback chain. Supporting this proposal requires a
  `FallbackResearchProvider`, provider-specific adapters, bounded timeout/error
  classification, passive quota snapshots, and evidence normalization.
- This is worthwhile implementation work because it preserves the existing
  uncertainty-gated product behavior while materially increasing recurring
  research capacity and eliminating Tavily as a single point of failure.

Official research references:

- Tavily free credits: <https://www.tavily.com/pricing>
- Linkup pricing and all-plan ZDR: <https://www.linkup.so/pricing>
- Exa free allowance and ZDR announcement:
  <https://exa.ai/pricing> and <https://exa.ai/blog/zdr-search-engine>
- Jina API allowance, Reader, and data posture:
  <https://api.jina.ai/docs>, <https://jina.ai/reader/>, and
  <https://jina.ai/news/a-practical-guide-to-deploying-search-foundation-models-in-production/>
- Firecrawl allowance and data controls:
  <https://www.firecrawl.dev/> and
  <https://docs.firecrawl.dev/features/scrape>
- Brave pricing and query retention:
  <https://brave.com/search/api/> and
  <https://api-dashboard.search.brave.com/privacy-policy>
- Serper and SerpAPI trial capacity:
  <https://serper.dev/> and <https://serpapi.com/pricing>

## 20. Real-invoice provider acceptance benchmark

Status: Accepted design - numeric provider admission thresholds remain open until calibration

### Purpose and truth source

- A provider is not admitted because it is free, fast, popular, or technically
  compatible. It must demonstrate that it prepares accountant-useful journal
  drafts from real invoices belonging to clients known by the pilot accountant.
- Synthetic invoices are excluded. The preferred reference is the accountant's
  historical final posting for the same invoice. When no reliable historical
  posting is available, the accountant creates the reference decision during
  review and the reason is recorded.
- Benchmark execution cannot overwrite current drafts or enter an export batch.
  Existing approved rules are preserved rather than erased. The provider
  comparison reads a fixed versioned snapshot of those rules, and benchmark
  outputs cannot modify that snapshot while providers are being compared.
- Learning quality is measured in a separate chronological track. In that track,
  accountant-approved rules persist from one invoice to the next so the product
  can prove that repeated corrections actually fall rather than repeatedly
  testing a blank system.

### Proposed initial corpus

- Start with 50 unique real invoices in total, not 50 invoices per client and not
  250 unique invoices. If five providers prepare every invoice, this creates up
  to 250 candidate journal drafts from the same 50 source invoices, but the
  accountant is not asked to review all 250 drafts separately.
- Weight the corpus toward the harder purchase direction: 35 purchase invoices
  and 15 sales invoices. This is a deliberate benchmark distribution, not a
  claim that the future production mix must be 70/30.
- The accountant supplies an unsorted recent invoice archive or continues the
  normal live workflow; the product inventories and selects the corpus. The
  accountant is not asked to find VAT, return, recurring-supplier, or other
  benchmark categories manually.
- Target at least 5 clients when enough suitable material exists. Coverage
  quotas guide automatic selection; if the raw pool cannot supply a quota, the
  benchmark reports that scope as unproven rather than assigning the accountant
  a document-hunting task.
- Ensure coverage across purchase/sale direction, services/goods, mixed and
  single VAT, common recurring suppliers, first-seen suppliers, multi-line
  documents, discounts/freight, withholding or special tax behavior when
  present, and low-quality/ambiguous line descriptions.
- Track coverage explicitly. A provider can be accepted for a narrower supported
  scope even when the corpus does not yet prove every document family.

### Fair comparison

- Each source invoice has one canonical reference journal entry, not one manual
  review per provider. Prefer a historical finalized Zirve posting. Otherwise,
  the accountant's final posting from the normal Fisora review flow becomes the
  reference.
- Provider drafts are compared automatically with that reference for account
  meaning/code, counterparty, tax treatment, debit/credit, amount, and line
  allocation. The initial benchmark asks the accountant to adjudicate only
  material unresolved disagreements, capped at 10-15 additional cases.
- Every provider receives the same canonical line evidence, direction-filtered
  current chart of accounts, client activity context, permitted counterparty
  context, and deterministic constraints. A provider is not disadvantaged by a
  smaller or stale prompt merely because its adapter is newer.
- Model/provider identity is hidden from the accountant during quality review
  where practical. Display order is randomized to reduce provider-name and
  first-result bias.
- Compare the complete proposed journal draft after deterministic hard checks,
  not attractive prose or the provider's self-reported confidence.
- A provider timeout, invalid schema, missing lines, or unusable response is a
  benchmark failure, not silently excluded from its denominator.

### Review labels and metrics

The benchmark assigns each result one primary label from the canonical-reference
diff. The accountant confirms the label only for unresolved or disputed cases:

- `unchanged_approval`: usable exactly as prepared.
- `minor_correction`: small edit that does not change the accounting treatment.
- `material_correction`: account, tax treatment, direction, counterparty, or
  meaningful line allocation changed.
- `unusable_or_unsafe`: draft would create substantial work or material risk.

Record supporting measures:

- unchanged-approval rate;
- material-correction and unusable rate;
- exact account/account-meaning agreement on clear cases;
- canonical line coverage and allocation completeness;
- deterministic hard-check violations;
- median/p95 latency and timeout/error rate;
- input/output tokens and estimated documents per current free quota;
- repeated systematic error clusters rather than only an average score;
- approximate accountant correction time or number of changed fields.

### Admission and ordering principle

- Technical admission requires stable structured output, complete line handling,
  bounded latency, privacy eligibility, and no unresolved systematic failure.
- Accounting admission requires the provider to be genuinely useful to the
  accountant, not merely better than an empty deterministic fallback.
- The highest-quality accepted provider becomes primary. Lower accepted
  providers are ordered by accounting quality first, then availability, latency,
  and sustainable quota. Free capacity never outranks materially better journal
  quality.
- A provider may be admitted only for a proven scope or model version. A model
  change reopens a smaller regression benchmark before production activation.
- Exact numeric thresholds are approved with the accountant after the first
  calibration set so that `minor_correction` is not manipulated to make a weak
  provider look successful.

### Proposed staged execution

- Stage A is a shared 15-invoice calibration set: 10 purchases and 5 sales. All
  five candidate providers process the same set, producing 75 candidate drafts
  that are automatically checked against the 15 canonical references.
- Providers with privacy, schema, line-completeness, or clearly unacceptable
  accounting failures are eliminated after Stage A with a recorded reason.
- Stage B sends the remaining 35 invoices, 25 purchases and 10 sales, to the
  surviving providers. If three providers survive, the system evaluates 180
  total drafts rather than 250. These are not 180 separate accountant review
  tasks; normal final postings and the limited disagreement queue provide truth.
- A provider eliminated after 15 invoices is not represented as having a
  50-invoice score. Its rejection is reported as an early-gate result.

### Zirve source acquisition research

Status: Direction accepted - real accountant-machine sample and column-level
validation are intentionally deferred until the Zirve data-acquisition phase

- The preferred historical truth source is Zirve's Yevmiye Defteri Excel export.
  Zirve's official General Accounting guidance states that the Yevmiye screen
  can create an Excel file with `Excel'e Aktar`. This is more suitable than a
  printed voucher list because it should preserve final journal-line structure.
- Request one pilot client and one recent month first. The accountant selects the
  period in Zirve's General Accounting Yevmiye screen and uses `Excel'e Aktar`.
  Fisora inspects the real columns before promising a universal importer.
- The supporting bridge is `Muavin > Fatura Kontrol (F11)`. Zirve documents that
  purchase and sale lists can be exported to Excel there. Zirve also warns that
  tax/identity number and document number must have been entered for this report
  to be prepared correctly. This output can connect invoice number/VKN/amount
  evidence to the final journal entry when the Yevmiye export alone is ambiguous.
- `Fis Islemleri > Fis Listeleri (Alt+S)` is not the primary route because the
  current official guide describes it as a printable date-range list and does
  not confirm a stable detailed Excel export.
- `Fatura Excel` and `Kayit Aktar` are import-into-Zirve features, not evidence
  that finalized Zirve postings can be exported. They remain relevant to the
  later Zirve delivery adapter but are not benchmark truth sources.
- If Yevmiye Excel plus Fatura Kontrol cannot be joined reliably, accept the
  period's e-Defter journal XML as the structured fallback when available. Direct
  Zirve database extraction is not the first choice because it is more invasive,
  version-coupled, and dependent on local database access.
- Minimum automatic match evidence is invoice/document number plus date, VKN or
  TCKN when present, gross/net/tax amounts, journal number, account-code lines,
  debit/credit amounts, and description. Ambiguous matches stay unmatched and
  enter the limited accountant confirmation queue; they are never silently
  treated as historical truth.
- Official research sources checked on 2026-07-13:
  <https://blog.zirveyazilim.net/zirve-programinda-otomatik-donem-sonu-islemleri>,
  <https://blog.zirveyazilim.net/zirve-genel-muhasebe-kullanim-kilavuzu>,
  <https://blog.zirveyazilim.net/zirve-masaustu-fatura-excel-aktarim>, and
  <https://blog.zirveyazilim.net/diger-programlardan-veri-aktarimi>.
- Deferred closure condition: when this phase starts, collect one pilot client
  and one closed month first, inspect the real Yevmiye/Fatura Kontrol columns,
  record match coverage and ambiguity, and only then freeze the importer
  contract. No additional Zirve research or implementation is required in the
  current planning step.

## 21. Benchmark state, source retention, and cleanup lifecycle

Status: Accepted policy - implementation details remain open

### Current repository truth

- The settings action labelled `Test verisi` is a tenant-wide destructive reset,
  not a single-client deletion. It preserves accountant/admin identities and
  credentials, but removes clients, documents, jobs, outputs, research state,
  review/learning records, and files.
- Both current persistence implementations erase learning during this reset:
  the JSON store empties `learning_events`, and the PostgreSQL store deletes the
  relational `learning_rules` table and client-scoped workflow records.
- The client-management screen currently has no permanent `delete client`
  operation. Its danger action deletes only selected documents and their files.
- Selected-document deletion preserves review decisions and learning events. A
  learned behavior therefore survives document cleanup, but its source document
  may no longer be viewable. This is not currently an orphaned-client bug, but it
  is an evidence-lifecycle gap that must be handled explicitly.

### Required separation of destructive operations

1. `Benchmark run outputs clear`: deletes only selected run outputs, temporary
   provider responses, and derived benchmark scores. It preserves clients,
   source invoices, accountant decisions, and every approved rule.
2. `Selected documents clear`: deletes selected source files and rebuildable
   draft/pipeline artifacts. Approved rules remain active. Before the source is
   removed, the rule keeps a minimal immutable evidence snapshot containing the
   decision, normalized conditions, account meaning/code at approval time,
   actor, and timestamps; it must not depend on reopening the deleted invoice.
3. `Permanent client archive/delete`: is a future, separately authorized flow.
   Client-scoped account bindings become inactive and archived rather than
   remaining matchable or being silently hard-deleted. Office-wide semantic
   knowledge may remain because it does not belong only to that client. Audit
   evidence is retained according to the retention policy.

### Temporary raw-source retention and accountant archive handoff

Status: Accepted

- Fisero is not positioned as the accountant's or client's sole legal document
  archive. Raw invoice files are held temporarily to support recent review,
  correction, evidence inspection, and the `this document produced this
  journal` relationship.
- Raw sources are XML, PDF, images, and document attachments. Derived records
  such as canonical identity/fields, approved journal revisions, decision
  history, and minimal learning-rule evidence have a separate lifecycle.
- The raw-source clock begins only after an authoritative terminal accounting
  decision, such as approval or confirmed export-list exclusion. An unresolved
  document is not deleted merely because its upload date is old.
- Raw sources remain normally accessible for 60 days after that decision. A
  reopened journal resets the clock from its new authoritative final decision.
- At the end of normal access, Fisero offers a client/period archive package
  containing original raw files, a document manifest, invoice-to-journal
  mapping summary, approved journal information, and an explicit list of any
  file that could not be packaged.
- The accountant may download the package and confirm `I received the archive;
  delete raw documents`, causing early raw-file deletion with an audit record.
- If the accountant takes no action, a 30-day grace period follows. Batched
  reminders are issued around days 60, 75, 85, and 90; per-document notification
  spam is prohibited.
- Day 90 is the hard upper bound for ordinary raw-source retention. Raw files
  are deleted automatically even without download confirmation, so an ignored
  reminder cannot turn Fisero into permanent raw-document storage.
- Raw deletion removes the ability to reopen the original XML/PDF/image preview.
  It does not silently delete the approved journal, decision history, or an
  approved rule. The exact retained derived fields and their retention period
  are decided separately.

### Derived accounting and learning evidence after raw deletion

Status: Accepted

- While the client remains active, Fisero retains the minimum derived record
  required to reproduce the approved accounting decision and explain learning:
  internal document identity and source hash; ETTN/UUID or invoice number;
  document date and direction; relevant counterparty tax identity; net, VAT,
  and gross summaries; normalized line semantics that affected accounting;
  approved journal lines and revisions; decision actor/time/reason; applied or
  created rule identity; the accountant instruction; the confirmed rule
  interpretation; and a short decision-support evidence summary.
- Raw OCR text, source preview, unnecessary address/phone/email/IBAN fields,
  full model prompts/responses, copied research pages, and temporary provider
  candidates are not part of the long-lived derived record.
- Approved journals, decision history, and client-specific rules remain while
  the client is active; they are not deleted at the raw-source day-90 boundary.
- Permanent client deletion first offers a derived-record export. Client-bound
  journals, tax identities, account bindings, and client-specific rules are
  deleted or irreversibly deactivated after a 30-day deletion window.
- Office-wide semantic knowledge may remain only after removing client,
  invoice, and account-binding identity. A meaning such as `cargo service` may
  survive, but the deleted client's `760.03.010` binding cannot remain active or
  transfer to another client.

### Benchmark rule policy

- The tenant-wide `TEMIZLE` action is not used between benchmark runs.
- Approved learning persists across chronological learning tests. Every result
  records the exact rule-set version, prompt/pipeline version, provider, and
  model so improvement can be attributed and reproduced.
- Side-by-side provider acceptance uses the same frozen rule snapshot for every
  provider. One provider must not receive a rule learned from an earlier result
  while another provider was evaluated before that rule existed.
- Recreating a previously archived client with the same VKN does not silently
  reactivate its old client-specific rules. The accountant is offered an
  explicit reviewed restore/migration decision.
- The existing broad reset should eventually be renamed to
  `Pilot ortamını tamamen sıfırla`, restricted to an explicit developer/admin
  maintenance surface, and accompanied by a preview of record categories that
  will be deleted. Daily benchmark cleanup gets its own scoped action.

## 22. Pilot MVP scope and explicit non-goals

Status: Accepted

### Pilot release gate

The first pilot succeeds by proving the invoice-to-journal-draft product loop:

- one accountant office with authorized accountant and office-worker roles;
- multiple clients, with client users limited to authenticated document upload
  and an immediate upload receipt; persistent status tracking is not required;
- invoice acquisition through QNB synchronization where available and manual
  upload as a supported fallback;
- purchase and sales invoice direction, header and line extraction from the
  selected canonical source, and preservation of source evidence;
- selection from the client's real chart of accounts and counterparty context;
- AI-assisted preparation of the best complete, balanced journal draft even
  when review is required;
- accountant editing, approval, export-list rejection, learning-rule proposal,
  rule confirmation, and reliable reuse on genuinely similar invoices;
- the AI Agents training/rule-management center, bounded audit history,
  provider failover, outage visibility, and operational notifications;
- real-invoice quality benchmarking as a pilot evidence gate.

Pilot planning closes the ordinary high-volume invoice path before expanding
rare nested exceptions. An edge case enters the first-pilot release gate only
when it can realistically corrupt ordinary journals, lose source evidence,
break tenant/accounting identity, or prevent recovery. Other theoretically
possible cases are retained as later-phase notes and must not consume the
decision depth needed for the main accountant workflow.

### Zirve boundary

- A flexible Excel/CSV package may be produced as a temporary bridge only when
  it is useful to the accountant. It is not a core product promise or a pilot
  success requirement because Zirve already allows flexible column mapping and
  the accountant does not want a recurring manual mapping/import workflow.
- The real product objective is direct delivery of approved accounting data into
  Zirve. The supported mechanism, authorization model, idempotency contract,
  reconciliation, and rollback/error behavior will be designed and field-tested
  in a later dedicated integration phase.
- The first pilot does not directly send records into Zirve. It proves that the
  accounting result to be sent is trustworthy before transport automation is
  introduced.

### Deferred from the first pilot gate

- Bank and POS statement accounting is the next accounting expansion after the
  invoice flow is reliable. Existing code and evidence are preserved, but bank/
  POS quality does not block the first pilot release.
- Direct Zirve transmission and automated reconciliation.
- Payroll, declarations, e-Defter production, fixed-asset lifecycle, and a full
  accounting/ERP replacement scope.
- Unattended definitive tax/legal decisions in unsupported or cold-start cases.
- Multi-office commercial packaging, subscriptions, and billing.
- A general-purpose chatbot with unrestricted write authority.
- Native mobile applications and exhaustive automation of every rare document
  or accounting exception.

### First-pilot status semantics

The accountant/office workflow keeps the following visible statuses. Each has a
strict meaning so operational failure, evidence deficiency, and accounting
review are not confused:

- `Belge alindi`: the upload or synchronization record is durably stored,
  identified, deduplicated or marked as a duplicate, and queued. Journal
  preparation has not necessarily started.
- `Fis hazirlaniyor`: canonical parsing, direction detection, context/rule
  retrieval, AI/research work when needed, journal construction, or hard checks
  are actively running or waiting in their bounded processing queue.
- `Kontrol bekliyor`: Fisero has prepared its best available, balanced, populated
  journal draft, but an authorized accountant decision is still required. This
  status never licenses an abandoned or intentionally low-quality draft.
- `Onaylandi`: either an authorized accountant accepted the final journal state,
  with or without saved changes, or the complete journal passed the accepted
  verified-rule automation contract. The visible secondary explanation and
  audit distinguish `Insan tarafindan onaylandi` from `Dogrulanmis kuralla
  otomatik`; automatic approval is never attributed to a human click. This is
  the authoritative accounting result for later learning and future Zirve
  delivery; it does not mean Zirve transmission already occurred.
- `Ajan olmadan hazirlanmis`: the full AI provider chain was unavailable and the
  visible provisional deterministic draft was produced. The draft is clearly
  marked, AI retries continue under the accepted ownership rules, and this is
  not silently represented as a normal AI-prepared result.
- `Ek bilgi/belge gerekli`: only a user with `can_review_accounting` may select
  this state in the pilot, when a named missing or unusable evidence item truly
  prevents a defensible final decision. AI, research, parsers, and deterministic
  checks may propose internal evidence warnings but cannot set this state. A
  corrupt/password-protected file that a human also cannot read, a genuinely
  missing essential page/attachment, or a business fact the accountant confirms
  cannot be derived may qualify. Generic lines, ordinary AI uncertainty, lower
  confidence, account-selection difficulty, or theoretical alternative use do
  not qualify. Any defensible draft content already produced is preserved.
- `Islem hatasi`: a non-accounting technical failure in parsing, worker,
  persistence, or another pipeline component prevents normal completion. The
  failure is safely explained, automatically retried within policy, and exposed
  to operations. Existing valid draft work is preserved. An AI-provider outage
  that produced the provisional draft uses `Ajan olmadan hazirlanmis`, not this
  status.

The ordinary transition path is `Belge alindi -> Fis hazirlaniyor -> Kontrol
bekliyor -> Onaylandi`. Complete verified-rule coverage may transition directly
from preparation to `Onaylandi / Dogrulanmis kuralla otomatik`. A successful AI
retry, new accepted evidence, or an applicable changed context creates a new
preparation/revision transition without overwriting authoritative work.

The visible accounting status is not overloaded with unrelated state. Processing
job state (`queued/processing/failed/completed`), source legal validity,
edit-lease ownership, and export/delivery eligibility remain separate state
dimensions and appear only as relevant badges/details. The review action
`Cikti listesine ekleme` removes the item from the active review/export workflow,
preserves its source and decision history, and shows a `Cikti disi` eligibility
badge; it does not create another primary accounting-processing status.

These statuses belong to the accountant/office workflow in the first pilot. The
client uploader receives only immediate upload success/failure feedback and does
not receive a persistent status-tracking surface yet.

### Automatic intake, duplicate evidence, and reprocessing

Status: Accepted

- Every invoice acquired through QNB or manual upload enters processing
  automatically after durable storage and authorization checks. A separate
  routine `Process` action is not required.
- The same accounting document does not create multiple journal drafts merely
  because it arrived through multiple channels or formats. Matching evidence is
  evaluated using ETTN/UUID first, issuer VKN/TCKN plus invoice number next,
  supporting date/amount identity, and exact file hash/content duplication.
- Exact file duplication and same-document/more-evidence are distinct. An exact
  duplicate is recorded and skipped. A PDF, UBL/XML, or provider copy that
  independently arrives and adds stronger canonical evidence is attached as
  another source version of the same accounting document. This rule never
  authorizes proactive dual-format download.
- Before an accountant decision, stronger new evidence may automatically create
  a new processing/draft version. The previous version and comparison remain in
  history.
- After approval, new evidence never silently overwrites the authoritative
  journal. It creates a visible evidence notice and a new version candidate that
  requires an authorized decision.
- Manual `Reprocess` remains available for bounded failure recovery, corrected
  source evidence, changed chart/context, or an explicitly chosen new rule/model
  evaluation. Reprocessing creates a version; it does not erase the prior draft,
  review, rule evidence, or audit history.
- Version ownership is explicit and separate: immutable raw-source revisions,
  canonical invoice revisions, working/system journal revisions, and immutable
  approved journal revisions are linked but never collapsed into one mutable
  record. The ordinary screen shows the current authoritative revision while
  history retains prior evidence and comparisons.
- A successful AI retry may replace only an untouched provisional current draft
  by creating a new journal revision. A saved human accounting edit, approval,
  or export-list rejection prevents automatic replacement; a later AI result is
  retained only as a non-destructive candidate when useful.
- A chart-plan change first computes the old/new chart diff. Only genuinely
  affected, unapproved journals are automatically reconsidered. Approved
  journals remain immutable, and a closed/missing active-rule binding follows
  the accepted focused AI-rebinding and notification contract.
- A newly active rule may reconsider genuinely matching pending journals, but
  does not rewrite approved history. If a user already has a working revision,
  the rule result becomes a candidate revision instead of overwriting the work.
- Model/provider/prompt changes do not automatically reprocess historical
  documents. Re-evaluation requires a matching operational event, an explicit
  bounded action, or benchmark execution.
- Every processing revision records a reproducibility fingerprint including the
  source/canonical revision, chart version, rule-set version, model/prompt/
  pipeline version, and relevant policy version. Repeating the same effective
  inputs reuses or idempotently returns the existing result rather than creating
  audit/version noise.
- Duplicate/source-version information is a visible badge or evidence detail,
  not a replacement for the primary document-processing status.

### Invoice identity versus unsupported-document classification

Status: Accepted

- Whether a source is an invoice is decided independently from whether its
  product/service lines are easy to understand. Generic, noisy, utility-specific,
  abbreviated, malformed, or semantically unresolved lines can never be used as
  evidence that the source is not an invoice.
- Strong invoice identity locks the source into the invoice pipeline. Examples
  include acquisition as an e-Invoice/e-Archive invoice from QNB, a valid UBL
  `Invoice` root with invoice identifiers, or a PDF/image carrying a coherent
  combination of invoice/e-Archive identity, issuer tax identity, invoice
  number/date, and monetary totals. Once locked, semantic uncertainty cannot
  downgrade the document to `Fatura disi belge`.
- Electricity, natural-gas, water, telecom, and similar utility invoices remain
  invoices even when they contain dense meter, period, consumption, tariff,
  distribution, surcharge, fund, or tax lines. The accounting pipeline uses
  issuer/business context, service period, canonical amounts, prior decisions,
  the client's chart, AI and bounded research to prepare the strongest complete
  balanced journal. Any remaining material uncertainty is a focused review
  reason, not an unsupported-document escape.
- `Fatura disi belge` requires positive evidence for another source type rather
  than absence of semantic understanding. Examples include a UBL
  `DespatchAdvice`, a coherent bank statement/receipt structure, a contract
  structure, or a dispatch note that lacks invoice identity and monetary invoice
  totals. Weak confidence, unreadable line meaning, an unfamiliar issuer, or a
  failed account recommendation are insufficient.
- When source type remains ambiguous, the pilot biases toward continuing the
  invoice pipeline and preparing the best available result. An AI model cannot
  terminate processing merely by asserting `not an invoice`; the decision must
  cite positive structural/source evidence and pass the high-precision document
  classifier contract.
- `Fatura disi belge` is a document classification, not `Islem hatasi` and not
  `Ek bilgi/belge gerekli`. The original source and preview remain available.
  An authorized reviewer can choose `Fatura olarak yeniden isle`, creating a
  new classified/processing version without erasing the original evidence.
- False unsupported classification of a real invoice is a critical pilot
  quality defect with a target of zero in the accepted benchmark set. Every
  override feeds classifier evaluation, but it does not become an office-wide
  accounting rule without the normal approval boundary.

### Multiple invoices inside one uploaded source

Status: Accepted

- One uploaded PDF/image bundle is an immutable source container; it is not
  assumed to equal one accounting document. Page groups are detected using
  invoice number/UUID, issuer and buyer identities, dates, monetary totals,
  explicit page numbering, visual continuity, and canonical XML evidence.
- Each real invoice becomes a separate child accounting document and receives
  its own processing, journal, review, approval, duplicate, and later-delivery
  lifecycle. Monetary values belonging to two distinct invoice identities must
  never be combined into one journal merely because their pages arrived in one
  file.
- High-evidence page boundaries are applied automatically. When a boundary
  remains materially ambiguous after document parsing and bounded AI support,
  Fisero still creates the strongest supported page groups and complete draft
  journals, then adds a focused `Sayfa ayrimi kontrolu` review reason. It does
  not abandon accounting preparation or misuse `Ek bilgi/belge gerekli` as a
  generic escape.
- The ordinary screen is not expanded with permanent page-management buttons.
  An authorized reviewer opens `Diger islemler > Sayfalari duzenle` to move a
  page between child documents, split a group, or merge groups. The UI previews
  affected invoice identities and journals before confirmation.
- Page regrouping creates new document/processing versions and re-runs duplicate
  and journal preparation for affected children. The immutable source upload,
  prior grouping, actor, reason, and prior drafts remain traceable; approved
  journals follow the accepted reopen/version policy rather than being silently
  overwritten.
- A canonical XML or provider copy arriving later is matched to the applicable
  child invoice using the ordinary evidence hierarchy. It strengthens that
  child's source evidence and does not create a duplicate merely because the
  original pages came from a multi-invoice container.

### Return-invoice accounting and original-invoice linkage

Status: Accepted

- A return invoice represents an economic reversal and must not be processed as
  an ordinary sale or purchase merely because of its document direction. An
  outgoing return normally reverses the applicable prior purchase effect; an
  incoming return normally reverses the applicable prior sale effect, subject
  to the document evidence and the client's accounting policy.
- Fisero searches for the original invoice using explicit UBL references first,
  then invoice number/UUID, counterparty identity, dates, line identity,
  quantity, amount, VAT behavior, and prior canonical documents. A match is
  confidence-bearing evidence, not a prerequisite for preparing a journal.
- For a confirmed full return, the approved original journal is the primary
  basis and its applicable economic effect is reversed. The client's chart and
  policy may require dedicated contra accounts such as a sales-return account
  instead of mechanically posting negative values to the original revenue
  account; related inventory/cost reversal is included when supported and in
  scope.
- For a partial return, only the returned lines, quantities, amounts, taxes, and
  supported related accounting effects are reversed. Fisero must not reverse
  the entire original journal merely because the source carries an `IADE` type.
- If the original invoice cannot be found, Fisero still recognizes the return
  direction and prepares the strongest complete balanced return journal from
  the return document, counterparty, line semantics, VAT, client chart, prior
  decisions, approved rules, AI, and bounded research. It does not treat the
  return as a normal sale/purchase, leave the journal empty, or set `Ek
  bilgi/belge gerekli` automatically.
- `Asil fatura bulunamadi` may be a focused review explanation when the missing
  linkage materially weakens account/line certainty. An authorized reviewer may
  link or replace the original invoice from the existing decision surface; the
  affected draft is recalculated as a new version and the confirmed linkage is
  retained as evidence. It does not silently become a broad accounting rule.

### Cancellation, rejection, objection, and post-approval invalidation

Status: Accepted

- Document legal/operational state is separate from accounting workflow state.
  Normalized source states include `valid`, `cancellation_requested`,
  `objection_reported`, `rejected`, `cancelled`, and `replacement_linked`, while
  the journal can independently be preparing, waiting for review, approved, or
  delivered. The UI presents the source state as a prominent badge without
  corrupting the accounting-state machine.
- A cancellation request or reported objection is not treated as confirmed
  invalidation. Fisero continues preparing the best journal, prevents unattended
  automation for the affected document, shows the pending dispute in review,
  and follows the provider/GIB result. It does not erase or exclude a document
  merely because a request was opened.
- Confirmed cancellation/rejection requires verifiable QNB/GIB/provider status
  evidence or an authorized manual decision with source/reason. AI or a parser
  cannot infer a definitive state solely from free text such as `iptal` or
  `itiraz` printed on or near a document. Raw status/evidence and normalized
  interpretation are retained together.
- If confirmed cancellation/rejection arrives before approval, in-flight work
  is stopped safely, existing drafts remain in history, and the document is
  excluded from active review and future export/delivery. It is visibly marked
  cancelled/rejected rather than deleted or labelled as a technical failure.
- If confirmation arrives after Fisero approval but before external delivery,
  the approved revision remains immutable history, receives a
  `belge sonradan iptal/ret edildi` marker, and is removed from the pending
  export/delivery list. Because it has not yet been posted externally, Fisero
  does not manufacture an unnecessary delivered-system reversal; it creates a
  new post-invalidation decision version and prevents the invalidated approval
  from training ordinary accounting behavior.
- If confirmation arrives after delivery/posting, the delivered journal is
  never silently edited or deleted. Fisero creates a linked
  `duzeltme/ters kayit gerekli` case and prepares the strongest reversal or
  correction journal from the delivered version. An authorized accountant must
  review/approve it before external delivery. A locked period, declaration, or
  other downstream impact raises urgency for accountant handling rather than
  being resolved autonomously.
- A replacement invoice is a new canonical document linked with
  `replaces/replaced_by`; it is not discarded as a duplicate even when its
  business content closely resembles the cancelled document. The new invoice
  follows normal processing, and material line/amount/VAT differences can be
  shown to the reviewer.
- Status changes are idempotent, timestamped, source-attributed, auditable, and
  reconciled on later QNB polls. Repeated identical provider messages do not
  create duplicate notifications, correction cases, or reversals.

Official research references:

- GIB e-Archive cancellation/objection notification guide:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-Arsiv_Uygulamalari_Iptal_Ihtar_Itiraz_Bildirim_Kilavuzu_V.1.0.pdf>
- GIB e-Invoice integration/application-response guide:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-FaturaUygulamasiEntegrasyonKilavuzu-v1.9.pdf>

### Monetary-total, tax, and source contradictions

Status: Accepted

- Fisero independently extracts and recomputes line extension totals,
  document-level allowances/charges, tax bases and subtotals, withholding and
  other taxes, tax-exclusive/inclusive totals, rounding, prepayment/settlement
  effects when present, currency, exchange rate, and payable amount. A payable
  amount is not assumed to equal simple line total plus VAT.
- Differences are classified as `normal rounding`, `explained monetary
  adjustment`, or `unresolved material contradiction`. This classification is
  evidence-based and cannot be used as a generic route to a suspense/fallback
  account, `Ek bilgi/belge gerekli`, or `Islem hatasi`.
- A normal rounding difference must be consistent with currency precision,
  line-level calculation, source rounding fields, and document scale. It is
  posted using the client's approved rounding policy/account without creating
  review noise. The numeric tolerance is calibrated and bounded; it can never
  expand enough to hide a material discrepancy.
- A difference explained by explicit discount, charge, withholding, tax,
  tax-inclusive pricing, prepayment/settlement, currency, or other canonical
  source fields is posted according to that economic meaning. The system does
  not create review merely because a naive net-plus-VAT calculation differs
  from payable amount.
- For an unresolved material contradiction, Fisero rechecks every available
  field in the selected canonical source, its locally rendered presentation
  when applicable, and provider/source provenance, then allows bounded AI
  reasoning to identify a missing semantic adjustment. It
  still prepares the strongest complete balanced journal. The AI selects the
  most defensible treatment/account from the client's chart and evidence, while
  the affected candidate line is explicitly marked `Belge toplam farki -
  kontrol` with amount, competing totals, rationale, and source references.
- An unresolved material contradiction forces focused human review and blocks
  unattended rule-based approval for that document. It does not authorize an
  empty journal or a deterministic generic balancing account. The reviewer sees
  the disputed difference rather than being asked to rebuild the whole journal.
- If two source formats independently arrived for the same identity and their
  canonical values materially disagree, the validated structured XML remains
  primary and the accepted source-version/reprocessing workflow exposes the
  conflict. This is an exceptional already-have-both path, not a reason to fetch
  a PDF alongside each XML or to compare a local XML rendering with its own
  source data as if they were independent documents.
- Corrections teach parsing/source-quality evaluation and, when the accountant
  explicitly approves a reusable interpretation, may propose a narrow rule.
  One document's unexplained arithmetic defect never becomes a broad automatic
  accounting rule.

Official research references:

- GIB monetary-total structure example:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-Gider_Pusulasi_Teknik_Kilavuzu_V.1.0.pdf>
- GIB e-Archive tax and withholding structure:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-Arsiv_Teknik_Kilavuzu_V.1.15.pdf>

### Foreign-currency invoice and exchange-rate policy

Status: Provisional default accepted - accountant field validation required

- Fisero retains original currency, original foreign-currency amounts, source
  exchange rate and declared TRY values separately from the TRY amounts posted
  to the journal. Every applied rate records value, rate type, effective date,
  source, retrieval time/version, and the reason that source was selected.
- For an ordinary taxable foreign-currency transaction, the provisional default
  is the TCMB foreign-exchange buying rate applicable when the taxable event
  occurs. Invoice date is used only when it represents that event under the
  applicable scenario. A currency not published by TCMB uses a documented
  current-rate source according to the approved policy.
- A document-declared exchange rate and TRY tax/base/payable amounts are
  extracted rather than overwritten. Fisero compares them with the provisional
  official-rate calculation. An internally coherent and policy-compliant source
  rate can be used; a material unexplained difference does not silently replace
  the configured official-rate policy.
- When source rate and policy rate materially disagree, Fisero still prepares a
  complete balanced journal using the most defensible configured treatment,
  preserves both calculations, and presents the rate/source difference as a
  focused review item. It does not create an arbitrary generic exchange account,
  abandon the journal, or automatically request missing information.
- The invoice's initial recognition, later payment/collection exchange
  difference, and period-end foreign-currency valuation are separate accounting
  events. The first-pilot invoice flow prepares initial recognition only. It
  never invents a later payment rate or embeds an unobserved exchange difference
  into the original invoice journal; settlement and valuation enter their own
  later bank/POS/accounting workflows.
- Before this behavior is admitted to unattended rule execution, the pilot
  accountant must confirm the office's actual treatment for domestic taxable
  invoices, document-declared rates, weekends/holidays, non-TCMB currencies,
  foreign-supplier/import cases, and material rate differences. Until that
  validation is recorded, affected foreign-currency invoices remain eligible
  for best-draft preparation but not unattended automation.

Official research references:

- GIB current KDV General Application Communique, foreign-currency conversion:
  <https://cdn.gib.gov.tr/api/gibportal-file/file/getFile?objectKey=MEVZUAT_TEBLIGLER%2FUNIVERSAL%2F2025%2Fkdv_genteb18092025.pdf>
- GIB e-Archive currency/exchange-rate fields:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-Arsiv_Teknik_Kilavuzu_V.1.18.pdf>

### Price-difference, maturity-difference, and exchange-difference invoices

Status: Product behavior accepted - accountant account-policy validation required

- Price, maturity, and exchange-difference invoices are adjustment documents,
  not ordinary goods/services merely because they use the invoice transport and
  contain a generic line. Fisero detects the adjustment meaning from canonical
  invoice type/notes/references, line semantics, counterparty, dates, currency,
  amounts, and linked accounting history.
- Fisero searches for the original invoice(s), contract/period, or settled
  balance using explicit references first and then counterparty, currency,
  dates, lines, amount relationship, and prior canonical records. Linkage
  improves treatment but is not a prerequisite for producing a journal.
- A price difference adjusts the supported economic meaning of the related
  goods/service, cost, expense, inventory, or revenue rather than being
  classified as an unrelated service. Whether the office uses the original
  account or a dedicated difference account is a validated client/office
  accounting policy.
- An exchange difference does not recalculate and overwrite the original
  invoice at a later rate. It is a separate subsequent economic event with its
  own direction, tax behavior, supporting settlement/reference evidence, and
  configured gain/loss or related-account treatment.
- A maturity difference is not inferred as an ordinary purchased/sold service.
  Its financing/payment-delay meaning, direction, tax behavior, and account
  treatment follow the validated office/client policy and source evidence.
- A single adjustment invoice may refer to multiple originals. Fisero allocates
  by explicit line/reference/period evidence where available, preserves the
  allocation explanation, and never fabricates one original merely to satisfy a
  one-to-one data model.
- If no original can be found, Fisero still prepares the strongest complete
  balanced adjustment journal from the adjustment document, counterparty,
  direction, tax, currency, chart, history, rules, AI and bounded research. It
  may show a focused linkage/account-policy review reason, but it cannot abandon
  the journal or automatically set `Ek bilgi/belge gerekli`.
- Until the pilot accountant confirms actual purchase/sale account treatment,
  these documents are reviewable best drafts and are not admitted to unattended
  automation. Repeated confirmed treatment may become a narrow scoped rule
  through the normal rule-review form.

Official research references:

- GIB KDV law, items included in taxable base:
  <https://www.gib.gov.tr/mevzuat/kanun/436>
- GIB exchange-difference tax treatment example:
  <https://gib.gov.tr/mevzuat/kanun/436/ozelge/25440>

### Special tax semantics, missing codes, and line-level learning

Status: Accepted

- Deterministic validation and semantic tax interpretation have separate jobs.
  The deterministic layer uses a versioned official GIB schema/code catalog and
  arithmetic rules to answer whether a supplied invoice type, tax type,
  exemption/withholding code, required structural combination, base, rate, and
  amount are syntactically known and mathematically coherent. It cannot decide
  from product meaning whether a sale is substantively entitled to an exemption.
- AI/accounting interpretation works at canonical line level. It uses the line
  name/description, unit, tax fields, issuer and client activity, brand/product
  context, prior decisions, approved rules, and bounded current research to
  infer economic/tax meaning. It may explain or propose the most likely missing
  exemption/withholding meaning, but it does not alter the immutable source
  invoice or pretend an absent source code was actually supplied.
- A structurally coherent invoice with supplied special-tax codes is normally
  posted as issued without repeatedly requesting supporting documents or
  second-guessing the product merely because a theoretical exception exists.
  Deterministic checks still protect code/schema/math boundaries; substantive
  doubt arises only from material contrary evidence, not generic suspicion.
- A missing or unknown exemption reason does not stop journal preparation. AI
  produces the strongest line-level treatment and full balanced journal from
  the available tax amounts and semantics. On the first materially new pattern,
  the missing/uncertain legal meaning may be shown as one focused review point;
  it cannot automatically set `Ek bilgi/belge gerekli` or cause every similar
  future invoice to be reviewed.
- Mixed-tax invoices are never assigned one whole-document semantic tax rule.
  For example, a line confirmed as an eligible hearing device may retain the
  invoice's zero/exempt treatment while separately supplied batteries,
  chargers, accessories, consumables, services, or other lines retain their own
  source tax rates and interpretations. A seller-level fact is context, not a
  license to copy one line's treatment to every product that seller invoices.
- When the accountant confirms the first pattern, Fisero proposes a versioned,
  effective-dated tax-interpretation rule containing semantic line class,
  positive match evidence, exclusions/accessory classes, source-tax behavior,
  office/client scope, and the confirmed accounting treatment. One unchanged
  review approval activates the accepted narrow rule. Fuzzy spelling, case, and
  minor wording variation do not break it; materially different products,
  changed tax behavior, expired legal effective date, or conflicting evidence
  re-enter AI/review.
- The learned rule may allow subsequent genuinely matching invoices to bypass
  repeat review even when the issuer routinely omits the same source reason
  code, while preserving that omission as source-quality evidence. It does not
  rewrite the legal invoice, transfer a client-specific account binding to
  another client, or convert the accountant's tax interpretation into an
  unversioned universal law.
- Rules whose correctness depends on legislation carry source/reference,
  effective date, last verification date, and revalidation trigger. A law/code
  catalog change pauses unattended use of affected tax rules and asks for one
  focused revalidation rather than sending all ordinary invoices into permanent
  review.

Official research references:

- GIB e-Archive invoice-type and tax structures:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-Arsiv_Teknik_Kilavuzu_V.1.18.pdf>
- GIB structured exemption-code example:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/Yatirim_Tesvik_Kapsaminda_Yapilan_Teslimlere_Iliskin_Fatura_Teknik_Kilavuzu_V1.1.pdf>

### Foreign-supplier invoices, imports, and imported services

Status: Product behavior accepted - accountant account-policy validation required

- A foreign supplier's commercial invoice and the Turkish customs/tax evidence
  are distinct canonical sources and accounting events. Fisero must not invent
  Turkish input VAT, customs duty, or other import charges from the foreign
  invoice alone, and missing customs evidence must not prevent preparation of
  the underlying goods/service and foreign-payable journal.
- From a foreign goods invoice, Fisero preserves original currency and rate
  provenance, identifies the foreign counterparty, interprets lines into the
  client's inventory/asset/cost/expense accounts, and creates the strongest
  complete balanced foreign-payable journal. No `191` or import-tax amount is
  manufactured without applicable customs/tax evidence.
- A customs declaration, tax payment, broker document, freight/insurance
  evidence, or later import source is processed as linked evidence with its own
  accounting version. Customs duty, additional duties, import VAT, other fiscal
  obligations, freight/insurance, brokerage, and documented deductible versus
  cost/non-deductible components are separated according to evidence and the
  validated client policy.
- Foreign invoices and customs declarations have a many-to-many relationship.
  One declaration may cover multiple invoices and one invoice may be imported
  across multiple declarations/shipments. Fisero allocates using explicit
  references, customs/item lines, values, currency, quantity, dates, and other
  canonical evidence; it never fabricates a one-to-one link to simplify storage.
- When customs evidence has not yet arrived, Fisero may show the secondary fact
  `Gumruk kaydi henuz eslesmedi`, but it does not automatically set `Ek
  bilgi/belge gerekli`, abandon the initial journal, or ask the client to upload
  evidence. A later customs source creates linked additional accounting work
  without silently rewriting an approved/delivered invoice journal.
- Imported services are a separate semantic path from imported goods. AI and
  bounded current research determine service type, place of performance/use,
  client context, potential responsible-party VAT/KDV2, withholding and treaty
  relevance, while deterministic logic verifies configured codes, arithmetic,
  effective dates, and approved rule scope. Not every foreign service is given
  the same tax treatment.
- The first materially new foreign-service pattern produces the strongest full
  journal with a focused tax/account-policy review. Once the accountant confirms
  supplier + service semantic class + client/scope + tax behavior, the normal
  versioned rule flow prevents recurring Google/AWS/advertising/software or
  similar invoices from returning to review without new contrary evidence.
- The first pilot supports best-draft preparation and evidence linkage for these
  sources, but exhaustive customs-declaration automation and landed-cost
  allocation are not pilot go/no-go requirements. Exact accounts, deductible
  import-tax treatment, allocation practice, and foreign-service tax/withholding
  policy require pilot-accountant field validation before unattended automation.

Official research references:

- GIB import VAT treatment example/current amendment:
  <https://www.gib.gov.tr/mevzuat/kanun/436/teblig/11863>
- GIB foreign-service responsible-party VAT example:
  <https://gib.gov.tr/mevzuat/kanun/436/ozelge/28815>
- Ministry of Trade import/customs declaration overview:
  <https://ticaret.gov.tr/gumruk-islemleri/sikca-sorulan-sorular/ticari/ithalat>

### Goods exports, service exports, and customs completion evidence

Status: Product behavior accepted - accountant account-policy validation required

- Goods export and service export are separate semantic/tax paths. A goods
  export uses invoice, foreign-customer, currency, exemption and line evidence
  while customs/GTB/ETGB completion is tracked as linked legal/operational
  evidence. A service export has no goods-customs requirement and instead
  depends on the foreign customer, service meaning and where the service is
  actually used/benefited from.
- An export invoice enters normal best-draft preparation immediately. Fisero
  builds the foreign receivable, export revenue and applicable line/tax journal
  from the selected canonical source and client chart; it does not wait with an
  empty journal merely because customs completion evidence has not yet arrived.
- Pending goods-export completion is represented as the secondary source fact
  `Gumruk cikisi bekleniyor`, not `Ek bilgi/belge gerekli` and not a technical
  failure. It prevents unattended external delivery/automation that depends on
  confirmed export completion, but does not automatically contact the client or
  discard the prepared journal.
- A verifiable GTB/customs acceptance or closure attaches to the same export
  case and satisfies the applicable evidence gate without rebuilding an
  unchanged journal. A rejection follows the accepted cancellation/rejection
  lifecycle. A replacement invoice is separately linked rather than discarded
  as a duplicate.
- Partial acceptance/rejection/return is processed at line, quantity, amount and
  tax-effect level. Fisero preserves the accepted exported portion and prepares
  the strongest correction/replacement treatment for the rejected portion; it
  never invalidates the whole invoice merely because some goods did not exit.
- ETGB/micro-export evidence, carrier information, exit date, currency/amount,
  and later return may be linked to the export case. Exhaustive ETGB/customs
  automation is not a first-pilot go/no-go requirement, but available evidence
  is preserved and used rather than forced into free-text notes.
- For service export, a foreign customer alone is insufficient to establish the
  substantive tax interpretation. AI and bounded current research determine the
  service semantic class, customer/project context and where the benefit/use
  occurs, while deterministic checks enforce configured code/math/effective-date
  boundaries. Fisero still prepares the strongest full journal and uses one
  focused review for a materially new pattern.
- Once the accountant confirms foreign customer + service class + use context +
  tax/account treatment, the normal versioned scoped-rule flow prevents
  genuinely matching recurring service-export invoices from returning to
  review. The rule does not apply when the same foreign customer receives a
  materially different service or the service supports its Turkish activity.
- Later foreign-currency collection may be linked through bank/reconciliation
  evidence. Initial invoice recognition does not wait for collection or invent
  a settlement exchange difference. Any collection condition relevant to a
  later refund/declaration workflow is tracked there rather than corrupting the
  invoice journal state.
- Exact export revenue accounts, customs-completion handling, partial export,
  ETGB practice and service-export interpretation require pilot-accountant field
  validation before unattended automation.

Official research references:

- GIB export e-Invoice customs response guide:
  <https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-Fatura_Uygulamasi_gumruk_islemleri_Kilavuzu.pdf>
- GIB current KDV General Application Communique, service-export conditions:
  <https://cdn.gib.gov.tr/api/gibportal-file/file/getFile?objectKey=MEVZUAT_TEBLIGLER%2FUNIVERSAL%2F2025%2Fkdv_genteb18092025.pdf>
- Ministry of Trade export/customs overview:
  <https://ticaret.gov.tr/gumruk-islemleri/sikca-sorulan-sorular/ticari/ihracat>

### Non-invoice accounting documents outside the first pilot

Status: Accepted scope boundary

- A source that is not an invoice is not necessarily a mistaken or worthless
  upload. Fisero distinguishes `Fatura disi yanlis/ilgisiz dosya` from `Diger
  muhasebe belgesi` and identifies a supported subtype where positive structural
  evidence exists, including e-Serbest Meslek Makbuzu, e-Gider Pusulasi,
  e-Mustahsil Makbuzu, commission/expense documents, and dispatch notes.
- These document types are not forced through the invoice schema or given a
  fabricated invoice journal. Their original source, subtype, identity and
  preview are preserved; classification is not `Islem hatasi` or `Ek
  bilgi/belge gerekli`. An authorized reviewer may reclassify and reprocess a
  source as an invoice when the classifier was wrong.
- Automatic journal preparation for these non-invoice document types is not a
  first-pilot success requirement. The first release must classify/preserve them
  safely without allowing them to dilute invoice-draft quality or provider
  benchmark capacity.
- Each later-supported subtype receives its own canonical fields, tax/withholding
  logic, state machine, accounting policy and acceptance evidence rather than
  inheriting invoice assumptions. Actual office volume and risk determine their
  implementation order.
- Bank/POS remains the principal accounting expansion after reliable invoice
  processing under the accepted roadmap direction. High-volume SMM/gider
  pusulasi or similar subtypes may be developed as a bounded adjacent lane in
  that later phase, but they do not reopen the first-pilot gate.

## 23. Office tenancy and user-access boundary

Status: Accepted

- The accounting office is the tenant and primary operational boundary. It owns
  office memberships, taxpayers, office-level semantic learning, provider
  configuration/budgets and office settings. A taxpayer owns its verified
  profile, imported chart of accounts, counterparties, sources, canonical
  documents, journal versions and taxpayer-specific accounting rules.
- Access scope and action permission are separate decisions. Being able to see
  a taxpayer does not implicitly grant journal approval, rule management,
  user-management, reopening or other privileged actions.
- In the first pilot the accountant/office manager and ordinary office workers
  may access all taxpayers of their office by default. The accountant may
  restrict an individual worker to explicitly selected taxpayers without
  having to assign every taxpayer to every ordinary worker. A taxpayer user is
  limited to its explicitly linked taxpayer workspace and first-pilot upload
  capabilities.
- Background workers and AI/research jobs receive only the immutable tenant,
  taxpayer, source/document and job purpose required for that execution. A
  system job does not acquire office-wide access merely because it runs outside
  an interactive session.
- The server derives tenant, membership and actor identity from a verified
  server-side session. Tenant, role, user or permission claims supplied by a
  request body, URL or client-controlled header are selectors only and never
  authorization proof.
- Authorization is deny-by-default and is checked for every request and every
  affected resource. Tenant-sensitive lookups use the compound boundary
  `tenant_id + taxpayer/client_id + resource_id`; storage paths, cache keys,
  queues, notifications, provider usage, exports and audit evidence preserve
  the same tenant/taxpayer scope.
- Enforcement must exist in the service/data-access path rather than only in
  frontend visibility or route handlers. Database-level tenant isolation may
  be added as defence in depth, but it does not replace application permission
  checks.
- The current repository's tenant tables, `client_id`-scoped records, portal
  access checks and same-client preview authorization are foundations to keep.
  The single configured tenant key, coarse `accountant`/`admin`/`client_user`
  roles, wildcard client access and mock/header compatibility are current-state
  constraints, not the target authorization contract. They must evolve into
  explicit office membership, optional taxpayer restriction and fine-grained
  action permissions.

### Initial invitation and credential lifecycle

Status: Accepted

- When an eligible taxpayer workspace is activated, its portal identity may be
  created automatically in `Davet bekliyor` state. A valid email address causes
  Fisero to send the invitation automatically; the accountant does not create,
  see or communicate a temporary password.
- The initial invitation lets the recipient create the account password once.
  After activation, normal username/email and password login is used; Fisero
  does not require a fresh monthly magic link.
- By deliberate accountant-first product decision, the **initial password-
  creation invitation has no clock-based expiry**. This exception exists
  because many taxpayer users may not inspect the invitation email until the
  office later directs them to it. It applies only while the identity remains
  unactivated and does not apply to password-reset or other sensitive action
  links.
- The non-expiring invitation remains a high-entropy, securely hashed,
  single-use bearer secret. It is invalidated immediately when used, manually
  revoked, replaced/resend, the destination email or user identity changes,
  the taxpayer/user is disabled, or the office removes the portal relationship.
  Only the newest valid invitation may activate the identity.
- A password-reset link is separate, short-lived and single-use. Password and
  material permission changes invalidate or rotate affected existing sessions.
  Emails never contain a password.
- Invitation delivery failure does not block taxpayer activation, invoice
  ingestion or accounting work. It produces a visible portal-access delivery
  problem that the accountant can correct and resend without recreating the
  taxpayer.
- Invitation creation/resend/revocation requires user-management permission,
  is rate-limited and audited, and does not reveal raw tokens in production
  UI/API responses or logs. Password-reset requests return the same public
  response whether or not an account exists.
- Existing repository invite, invite-accept, password-login, password-reset and
  server-session contracts are reused and hardened. The currently exposed raw
  invitation response/manual-link development lane and insufficiently explicit
  invite authorization are implementation constraints, not production policy.

### Trusted-device session policy

Status: Accepted

- A normal login that does not select `Bu cihazda oturumumu acik tut` ends with
  the browser session. Selecting it creates a trusted-device session with a
  rolling 30-day inactivity window.
- Every valid use of that trusted session renews the inactivity deadline. There
  is no separate absolute 30-day re-login deadline for a regularly used office
  or taxpayer device. If the device is not used for 30 days, the user signs in
  again.
- Password change/reset, user disablement, removal from the office/taxpayer,
  manual session revocation and material permission changes revoke or rotate
  affected sessions immediately. The user and authorized office manager can
  inspect and revoke active device sessions.
- Ordinary invoice/review/accounting work does not repeatedly ask for a
  password. High-impact operations such as user/permission management,
  taxpayer deletion, bulk archive download and security-setting changes require
  recent re-authentication even when the trusted session is valid.
- Production sessions use secure server-side session records and protected
  cookies; bearer credentials are not persisted in browser local storage. The
  current header compatibility remains a development/migration concern rather
  than the target browser-authentication contract.

### Staged office second-factor policy

Status: Accepted

- All office-side users require a second login verification factor; taxpayer
  users may enable it voluntarily during the first pilot. The trusted-device
  policy keeps this requirement out of ordinary daily accounting work after a
  device is verified.
- During the closed pilot the office factor is an emailed one-time code. This is
  explicitly a transitional risk-reduction control, not the product's final
  strong-MFA assurance: compromise of the registered mailbox can also weaken
  password recovery and email is not treated as a phishing-resistant channel.
- The email code is cryptographically random, eight digits where the delivery
  UX supports it, securely represented at rest, never logged, single-use and
  valid for at most ten minutes. Verification has a strict attempt limit;
  resend replaces the previous code and account/IP resend and verification are
  rate-limited.
- Existing trusted sessions continue during a temporary mail outage. A new or
  untrusted device cannot complete office login until delivery succeeds or an
  authorized recovery path is used. Office owners receive securely generated,
  single-use recovery codes.
- The second-factor service is method-neutral rather than coupled directly to
  SMTP: challenge creation, attempt/rate limiting, trusted devices, audit,
  recovery and step-up verification remain reusable across `email`, `totp` and
  later `passkey` methods.
- Before broad multi-office release, office accounts move from email codes to
  standards-based TOTP or preferably passkeys. Email then remains for alerts
  and controlled recovery rather than the primary second factor. TOTP is not a
  Google-specific integration; Google Authenticator, Microsoft Authenticator,
  2FAS and compatible applications can use the same standard.
- MFA enrolment/change/reset is a privileged, audited operation. It notifies
  the affected user; an authorized office manager may reset an employee's
  factor but cannot retrieve its secret. Office-owner recovery requires a
  stronger documented recovery path and cannot silently bypass the factor.

### Encryption, secrets and backup protection

Status: Accepted

- User passwords are stored with a suitable one-way, salted and costed password
  hashing scheme; they are never reversibly encrypted, displayed to staff or
  recoverable. Password hashes, action tokens and OTP values never enter logs,
  audit payloads or public diagnostics.
- Credentials that Fisero must use again—such as taxpayer QNB credentials and
  future office-owned integration secrets—are encrypted at application level.
  The existing QNB Fernet-ciphertext boundary is retained and generalized. The
  key-encryption material is not stored in the database, its backups, source
  control, container images or public configuration/readiness output.
- Platform-wide AI, research, mail and infrastructure secrets are injected only
  into the backend/worker processes that need them through protected production
  secret configuration. Development and production secrets are separate;
  secrets are masked, inventory-tracked, revocable and designed for rotation.
  If office-specific provider credentials are introduced later, they use the
  encrypted tenant-owned credential store rather than shared plaintext config.
- Public application traffic uses HTTPS. PostgreSQL, Redis and document storage
  are not exposed directly to the internet. Temporary OCR/processing artifacts
  are access-scoped and removed after their bounded purpose.
- During the pilot, canonical searchable fields such as VKN/TCKN, title, date
  and amount are not individually application-encrypted, and every PDF/XML is
  not wrapped in a separate application encryption layer. Tenant authorization,
  restricted service access and encrypted storage volumes protect these data
  without breaking indexing, preview, OCR and AI processing.
- The document and database volumes on the Radore host must be verified as
  encrypted at rest. An architecture claim or compose label is not live proof.
  If the provider/host cannot establish this protection, an equivalent
  encrypted-volume solution becomes a real-data readiness gate.
- A backup is encrypted before leaving the application host, transferred over
  a protected channel and stored outside the single Radore machine. Its key is
  stored separately and has a protected recovery copy. Restore is periodically
  tested; a backup that cannot be restored is not counted as healthy.
- Backup retention respects the accepted raw-document deletion lifecycle so
  expired source documents do not survive indefinitely in historical backup
  sets. Key version/rotation and old-backup recovery are designed together so a
  routine key change does not silently destroy restore capability.
- Encryption is defence in depth, not a substitute for tenant authorization,
  least-privilege service accounts, secure deletion, monitoring or incident
  response.

### Technical-support and emergency production access

Status: Accepted

- Fisero technical support is not an implicit office member and has no normal
  standing access to taxpayer documents. Routine support uses redacted service,
  queue, worker, provider, disk/backup and error telemetry plus opaque technical
  identifiers; invoice content, titles, chart accounts and journal details are
  excluded by default.
- When real content is genuinely required to diagnose a bounded problem,
  technical support requests access with a reason, office/taxpayer and, where
  possible, exact document scope. An authorized office manager approves it in
  the application. The grant is read-only by default, lasts at most two hours,
  expires automatically and is visibly indicated while active.
- Access is least-scope: a single-document problem does not open the taxpayer or
  office, and a taxpayer-wide pipeline diagnosis does not open another
  taxpayer. Download, mutation, deletion, reprocessing or configuration changes
  require separately appropriate authorization rather than inheriting the
  read grant.
- Every request, approval, denial, start, viewed protected resource, privileged
  action, expiry and revocation records the named technical actor, approving
  office actor, reason/ticket, scope and time without copying protected document
  content into the audit log.
- A separate one-hour `break-glass` path exists only for material data-loss or
  security risk, whole-system unavailability, broken normal authorization or
  critical recovery. It requires a named individual and recorded reason,
  grants only recovery-relevant privilege, immediately alerts the office and
  technical operations, and always produces a post-access incident review.
  It is never an alternative routine remote-support route.
- Pilot reality is stated honestly: a host administrator with sufficient
  operating-system privilege can technically reach application data. Therefore
  individual SSH identities, restricted sudo, no shared daily root account,
  protected operator devices, command/access evidence and a prohibition on
  casual production-data download complement the application grant model.
- Real invoices and credentials are not attached to source-control issues,
  ordinary chat, email or unredacted error reports. The repository's delegated
  client session remains an accountant acting within an authorized taxpayer
  portal; it is not repurposed as a hidden technical-support impersonation
  mechanism.

### Abuse protection without blocking legitimate accounting volume

Status: Accepted

- Fisero does not impose an arbitrary daily invoice-count quota on an authorized
  office. A legitimate 50-, 100- or 250-document intake is accepted durably and
  queued; worker/provider pressure may increase waiting time but cannot reject
  the accounting work, downgrade journal quality or force a weak deterministic
  fallback.
- Limits are feature- and resource-aware rather than one global request count.
  Authentication, invitation/reset mail, OTP, manual AI/research, reprocess,
  export/archive and privileged operations receive stricter identity/IP limits;
  authorized intake uses high-volume-safe streaming and queue backpressure.
- An uploaded source has configurable byte, page, parsed-node and decompressed-
  content limits based on the real pilot corpus. The server validates type and
  signature, streams/counts before full memory allocation and isolates a
  rejected oversized or malformed source as an upload-security error rather
  than an accounting `Islem hatasi` or `Ek bilgi` escape.
- Repeated actions are idempotent. Re-clicking reprocess, export, invite or a
  costly AI action returns/joins the existing compatible work where possible
  instead of multiplying provider calls, drafts, emails or cost.
- Multi-office capacity is fair-share: idle capacity may be borrowed, but one
  office cannot starve another. Canonical invoice/journal work outranks bulk
  backfill, provider benchmark and companion chat; chat/research quotas cannot
  consume the protected accounting lane.
- Edge/network protection and an application limiter use shared state and
  combine tenant, authenticated actor/session, IP and feature scope. The
  repository's current process-local AI/export buckets are a useful pilot
  foundation but reset on restart, do not coordinate replicas and do not yet
  cover the full target surface.

### Worker topology, queue priority and initial throughput targets

Status: Accepted

- The pilot begins with one dedicated document-worker service and three
  concurrent document slots on the existing 4-core/4-GB Radore host. A slot
  owns one document job at a time and immediately claims the next eligible job
  after completion; PostgreSQL atomic claim/lease semantics prevent duplicate
  processing across slots or later replicas.
- Manual upload and QNB acquisition persist the source and enqueue durable work
  before acknowledging receipt. Browser/API requests do not remain open for
  OCR, AI, research or journal completion, and a worker restart does not lose
  accepted work.
- QNB scheduling is separated from document processing so a long invoice queue
  cannot delay due acquisition/status work. Retention/cleanup is a separate
  low-priority scheduled job so document processing cannot indefinitely delay
  cleanup and cleanup cannot block journal production.
- Four product AI agents are logical responsibilities, not four operating-system
  workers. Each document slot invokes only the required accounting/research
  capabilities under provider and stage concurrency limits.
- Queue priority is explicit: verified-rule/cached safe work and relevant
  retries use a fast accounting lane; ordinary new invoices use the normal
  lane; bulk reprocess, provider benchmarks, backfills and companion work use a
  lower lane. Priority cannot erase office fairness or starve normal work.
- Initial measurable targets under healthy dependencies are: upload receipt in
  under two seconds; normal/light-queue start in under 30 seconds with a target
  of a few seconds; first completed journal within two minutes; and a 50-source
  normal batch within 30 minutes. Fifteen minutes for the same batch is the
  optimization target, not an unproven launch claim. Verified-rule invoices
  should use the fast path instead of waiting behind research-heavy cold cases.
- The 50-source/provider-comparison benchmark may create up to 250 candidate
  drafts, but it runs as lower-priority benchmark work and never competes as
  250 ordinary accountant review tasks.
- Concurrency is calibrated with the real 50-invoice set at three, four and six
  slots. Selection uses queue wait, end-to-end latency, peak RAM/CPU, database
  connections, provider 429/timeouts and accounting failure/quality evidence.
  The highest stable setting wins; the system does not raise concurrency merely
  to improve a headline time. Before sustained operation above four slots, an
  8-GB RAM upgrade is preferred when measurements show 4-GB pressure.
- Current repository truth is preserved but not mistaken for the target: the
  production example has one worker with three ThreadPool slots, 30-second
  polling and up to ten jobs per slot/tick, while the same main loop also runs
  QNB scheduling and retention. The target separates those responsibilities,
  claims fairly one job at a time and uses prompt wake-up plus polling as a
  recovery safety net.

### Pilot quality gates and permanent real-data regression corpus

Status: Accepted

- A journal is not marked prepared merely because it balances. Before normal
  completion, every canonical source line is covered exactly once, AI/research
  responses map to known line IDs, debit/credit balances, used account/cari
  choices satisfy the current chart contract, tax/amount allocation is
  mechanically consistent and the journal remains traceable to source evidence.
- A structural failure triggers a focused repair/retry for the affected stage or
  line and reconstruction of the complete journal. This gate cannot become a
  reason to abandon the invoice, emit an empty fallback or lower accounting
  quality. If bounded repair still cannot prove the structure, Fisero preserves
  all defensible work, prepares the strongest full review draft possible and
  exposes the exact unresolved integrity problem.
- The already accepted cold-start quality targets govern the 50-source real
  corpus: at least 70% unchanged approval, at most 20% minor non-accounting
  edits, and at most 10% material/unusable accounting correction. `Unusable` is
  not excluded from the denominator or relabelled as minor to improve a score.
- Aggregate success cannot hide a systematic failure. Results are also grouped
  by purchase/sale, known/new supplier, goods/service, single/mixed VAT,
  single/multi-line, return and any present withholding/exemption or weak-line
  scope. A materially failing scope remains unproven or review-only even when a
  provider's overall percentage passes.
- A material error that escapes an automatic-approval path suspends the narrow
  affected rule/model/scope from unattended use, preserves best-draft review
  operation and opens diagnosis/revalidation. It does not disable unrelated
  rules or push the whole product into a weak fallback. A confirmed rule whose
  real preconditions match retains the accepted 0% repeat-correction target.
- The 50 unique real invoices now become a versioned, durable quality asset as
  the development phase moves from disposable trials toward persistent pilot
  evidence. Synthetic substitutes are not used for accounting/provider
  admission when real evidence is required.
- Each regression item links the protected source, canonical extraction and
  line IDs, accountant/reference final journal, classification label, relevant
  chart/rule snapshot, expected mechanical results and versioned provider/model
  run evidence. The reference is immutable per version; a later accountant
  correction creates a new authoritative version rather than rewriting history.
- The broad tenant `TEMIZLE` action does not delete the protected regression
  corpus, its reference outcomes or approved rules. Corpus removal is a
  separate explicit, authorized and audited destructive operation with clear
  item/count impact. The current repository reset, which broadly erases client
  and learning data while preserving accountant identities, is an
  implementation gap against this target.
- Access is limited to authorized development/quality and accountant roles.
  Regression provider runs still obey the accepted real-data privacy allowlist,
  and raw-source retention/deletion remains visible and revocable. When a raw
  source must be removed, retained structured expected outputs may continue to
  test accounting decisions but are not misrepresented as OCR/source-reading
  coverage.
- Model, prompt/schema, canonical extraction, tax engine, chart/cari selection
  or rule-engine changes run the relevant regression scope before production
  activation. Comparison records unchanged/minor/material/unusable labels,
  structural failures, systematic clusters, latency and correction effort so a
  faster release cannot silently lower journal quality.

### Load, interruption and restore evidence gate

Status: Accepted

- Unit/integration tests and a healthy readiness endpoint are necessary but are
  not sufficient for persistent real-data pilot admission. The deployed stack
  must prove load, interruption, duplicate prevention and isolated restore with
  the protected real 50-source corpus or an explicitly equivalent production-
  shaped run.
- The load run submits the 50 sources in a short window and records durable
  acceptance count, duplicate decisions, first/last completion time, queue
  wait, stage timing, peak CPU/RAM/disk/database connections, provider
  throttling, UI availability and journal-quality parity with serial intake.
  Lower-priority provider comparison may create up to 250 candidates without
  starving ordinary accounting work.
- A document worker is deliberately terminated while jobs are processing.
  Accepted sources remain durable; expired claims are safely reclaimed; no job
  remains indefinitely `processing`; completed stages may be reused where
  provenance permits; and one source cannot produce two authoritative final
  journals.
- Backend, document worker, PostgreSQL, Redis and whole-host restart/failure are
  exercised separately. Fisero cannot acknowledge `Belge alindi` before the
  source and intake identity are durably committed. If commit succeeds but the
  client does not receive the response, idempotent retry resolves to the same
  intake rather than creating another invoice.
- AI/research outage testing proves provider failover, verified-rule continuity,
  protected provisional drafts, accepted retry timing and the rule that an
  accountant-touched or approved journal is not silently overwritten when AI
  returns. Load/outage may extend waiting time but cannot lower the accounting
  standard without a visible provisional state.
- QNB timeout/restart testing proves that cursor/status evidence is not advanced
  without durable success, repeated downloads deduplicate, manual upload and
  document processing remain independent, and recovery continues from the last
  confirmed cursor without accountant reconstruction.
- Storage-pressure tests use controlled thresholds rather than filling the
  production disk. Warning, critical and safe-intake-stop boundaries are
  distinct. At the stop boundary Fisero refuses a new source before claiming it
  was accepted, while preserving access to existing review/approval/export or
  recovery functions where technically safe.
- An encrypted backup is restored into an isolated environment. The proof
  verifies PostgreSQL records, tenant/user relationships, document count and
  hashes, canonical invoices/lines, approved journal revisions, rules and audit
  evidence, then opens selected original previews and journals through the
  application. A backup file or manifest that has not passed this proof is not
  labelled healthy.
- Every scenario must preserve these invariants: no acknowledged source loss;
  no duplicate authoritative journal; no silent approved-revision mutation; no
  cross-tenant mixing; no indefinite ambiguous job; no false completion state;
  no hidden quality downgrade; and one actionable operational alert when human
  intervention is genuinely required.
- The current repository backup service is only a foundation: by default it
  creates a daily PostgreSQL SQL dump and a document hash/path manifest, retains
  local artifacts for 14 days and copies them externally only when an optional
  copy directory is configured. A manifest is not a document backup. Encrypted
  off-host source-file backup/replication and a tested restore are therefore
  real-data readiness gaps, not assumed capabilities.

### Persistent-pilot backup activation and recovery objectives

Status: Accepted

- The current disposable development lane may continue to clear and recreate
  ordinary trial data while Fisero is not yet being used as a persistent
  accounting workspace or output source. The protected real regression corpus
  is the explicit exception and is not erased by the broad test reset.
- The stronger backup contract activates no later than the product transition
  to intentionally retained real documents, persistent accountant decisions or
  accounting output suitable for operational use. That transition cannot be
  declared ready while only same-host daily SQL dumps and document manifests
  exist.
- From activation, encrypted off-host incremental protection covers new/changed
  source files and durable database state at least every 15 minutes, while a
  nightly encrypted full database-and-document backup provides a clean restore
  point. Backup encryption keys remain separate from the backup set.
- The initial catastrophic-loss objective is at most 15 minutes of acknowledged
  work at risk. Ordinary backend/worker failure should recover automatically
  within five minutes. Complete Radore-host loss targets restoration of the
  core service within four hours after the incident is detected and recovery
  begins; this is a staffed pilot objective, not a 24/7 contractual SLA.
- Core restore priority is authentication, tenants/taxpayers, protected sources,
  canonical evidence, approved journals and active rules, followed by new
  intake/processing, QNB automation and secondary reporting/companion features.
- Operations shows the latest incremental protection, full backup, off-host
  copy, recoverable point, items awaiting protection and last successful restore
  exercise. Incremental protection older than 30 minutes creates an operational
  warning; a missed full backup or failed off-host/restore proof creates a
  critical technical alert without per-document alarm noise.

### Persistent-pilot data ownership and PostgreSQL cutover

Status: Accepted

- The current PostgreSQL `workflow_records` compatibility model may remain the
  working store while ordinary development data is disposable. It is not the
  target accounting system of record for the persistent pilot.
- The persistent-pilot cutover uses normalized PostgreSQL tables as the
  authoritative current state. Core taxpayer, source-document, canonical
  invoice/line, chart-account, journal-entry/line, review-decision and
  learning-rule facts are stored in typed relational columns with foreign keys,
  constraints, indexes and transactional writes.
- JSON returned by the HTTP API is only a transport representation. PostgreSQL
  JSONB remains appropriate for variable AI evidence, provider responses,
  research metadata, parse warnings, risk details and workflow-event metadata;
  no JSONB blob is the sole authoritative copy of an approved journal.
- The uploaded PDF, XML, image or package is immutable source evidence.
  Extracted/canonical invoice facts are stored separately from the accountant's
  journal. An extraction correction does not mutate the original source, and a
  journal edit does not rewrite invoice evidence.
- `journal_entries` and `journal_entry_lines` own the current accounting draft
  and approved result. Review decisions identify the actor and change, and
  export reads only the authorized journal state rather than reconstructing the
  authoritative journal from `document.result.draft_lines`.
- `workflow_records` is retained during transition for compatibility and useful
  diagnosis. In the target model its durable successor is an append-oriented
  workflow/audit event stream, not a second writable copy of document or
  accounting state.
- The cutover does not attempt to migrate every disposable trial upload,
  malformed experiment or superseded draft. Only the protected regression
  corpus, explicitly selected benchmark evidence and verified active learning
  rules are imported when they remain valuable.
- Cutover is deliberately one-way: prepare and verify the normalized write
  path, import the selected protected set, stop persistent writes briefly,
  switch authoritative reads and writes together, verify counts/hashes/
  balances/permissions, then retire broad compatibility writes. A long-lived
  dual-write model with two competing truths is prohibited.
- This cutover is a prerequisite for intentionally retaining real operational
  documents, accountant decisions or export-capable accounting output. It is
  not imposed prematurely on the current clear-and-retry development lane.

Official security basis:

- OWASP Authorization Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html>
- OWASP Multi-Tenant Security Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html>
- NIST authenticator requirements:
  <https://pages.nist.gov/800-63-4/sp800-63b/authenticators/>
- OWASP Multifactor Authentication Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html>
- OWASP Secrets Management Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html>
- OWASP Cryptographic Storage Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html>
- OWASP Logging Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html>
- NCSC break-glass authorization guidance:
  <https://www.ncsc.gov.uk/collection/zero-trust/architecture-design-principles/use-policies-to-authorise-requests>
- KVKK data-security obligations:
  <https://www.kvkk.gov.tr/Icerik/2040/Veri-Guvenligine-Iliskin-Yukumlulukler>
- KVKK Personal Data Security Guide:
  <https://www.kvkk.gov.tr/Icerik/4198/Kisisel-Veri-Guvenligi-Rehberi-%28Teknik-ve-Idari-Tedbirler%29>

## 24. Canonical documentation completion map

Status: Accepted working method

### Target document set

The professional planning package will be maintained under `docs/product-plan/`
and will contain:

1. `00-canonical-decision-register.md`: conversation-level decisions, open
   questions, rationale, and deferred field evidence. This remains the decision
   source while the other documents are being written.
2. `01-product-requirements-document.md`: product problem, users, principles,
   pilot scope/non-goals, end-to-end journeys, functional requirements, UX,
   privacy/security requirements, non-functional requirements, quality model,
   acceptance criteria, success metrics, risks, and approval/version history.
3. `02-system-architecture-document.md`: current and target architecture,
   topology, security and tenancy, data model, storage lifecycle, job state
   machine, AI/provider/research architecture, integrations, frontend/backend
   boundaries, observability, testing, deployment, migration, and ADRs.
4. `03-development-roadmap.md`: release definitions, phases, dependencies,
   work packages, deliverables, evidence, exit criteria, go/no-go gates,
   deferred work, and immediate next actions.

### Current completion assessment

- Decision register: the detailed conversation-level rationale and deferred
  evidence remain preserved here.
- PRD: `01-product-requirements-document.md` now defines the canonical product
  scope, journeys, functional/non-functional requirements, quality metrics,
  acceptance scenarios, risks and first-pilot release gate.
- System Architecture Document:
  `02-system-architecture-document.md` now distinguishes the current
  `workflow_records` implementation, the normalized persistent-pilot target and
  later QNB/Zirve/scale boundaries. It records relational ownership, bounded
  JSONB use, internal state/revision defaults, worker/provider architecture,
  security, storage, migration and verification.
- Development Roadmap: `03-development-roadmap.md` now converts the accepted
  plan into dependency-ordered implementation phases, deliverables, evidence,
  exit gates and one immediate code-start package.
- The canonical planning package is sufficiently complete to return to code.
  Remaining office-practice answers, numeric calibration and external-system
  evidence are tracked as phase validations; they are not reasons to continue
  broad pre-implementation product discussion.

### Documentation closure and implementation handoff

1. Do not reopen broad product planning before Phase 1 implementation. Internal
   state fields, repository interfaces and schema details follow the SAD and are
   verified through the first normalized invoice-to-journal vertical slice.
2. Preserve the current Faturalar-page structure during the first persistence
   slice. Any material layout change waits for the accepted computer review;
   API/repository work must not force a redesign.
3. Resolve exact audit/backup-set retention, upload/page/disk thresholds and
   browser/accessibility budgets before the persistent-pilot infrastructure
   gate, using corpus and load evidence rather than another abstract planning
   round.
4. Answer the four office-practice questions during the closed pilot and
   calibrate provider thresholds during the real 50-invoice benchmark.
5. Design direct Zirve transport only after journal quality and persistent
   ownership are proven.
6. Begin implementation with the immediate code-start package in
   `03-development-roadmap.md`.

### Legacy-document precedence and migration

- Until the new package is complete, this decision register overrides older
  product claims when they conflict.
- `docs/current-handoff.md` remains runtime/deployment continuity evidence, not
  the product-definition authority.
- Specialist documents and dated specs remain implementation evidence and may
  be cited by the SAD/roadmap; they are not silently deleted or rewritten.
- `docs/product-decisions.md`, `docs/architecture.md`,
  `docs/implementation-roadmap.md`, `docs/mvp-portal-plan.md`,
  `docs/ai-first-invoice-processing-flow.md`, and
  `docs/rule-engine-and-learning.md` contain useful history but also stale
  assumptions. After their accepted material is migrated, each receives a
  visible `Superseded by docs/product-plan/...` notice rather than remaining an
  ambiguous competing source of truth.
- Known stale examples include three-approval automation as a universal rule,
  AI-only-on-uncertainty wording, first-pilot client status tracking, CSV/Zirve
  export as the primary pilot outcome, old provider candidate lists, and bank/
  POS work as a first-pilot gate.

### Evidence that remains intentionally deferred

- numeric provider admission thresholds until the real calibration run;
- actual Zirve Yevmiye/Fatura Kontrol column validation until the acquisition
  phase;
- direct Zirve transport mechanism and reconciliation until its dedicated
  integration phase;
- live proof for architecture decisions that require accountant data, provider
  credentials, or external systems.

## 25. Deferred validations and implementation refinements

- Exact audit/backup-set retention, provider payload-field matrix, upload/page/
  disk thresholds and browser/accessibility budgets are fixed before the
  persistent-pilot infrastructure gate from measured evidence.
- Major Faturalar-page changes remain paused until computer review; this does
  not block normalized persistence or API implementation.
- Detailed `Musavir Yancisi` screen-context manifest, tool authorization,
  retention, deployment isolation and acceptance tests remain a later roadmap
  phase.
- Numeric provider admission thresholds are calibrated from the 50-invoice
  automatic pool with the accepted 35-purchase/15-sale target and frozen
  comparison method.
- Accountant field confirmation of the provisional foreign-currency invoice
  and exchange-rate policy, tracked in
  `docs/product-plan/90-accountant-validation-questions.md`.
- Accountant field confirmation of price-, maturity-, and exchange-difference
  invoice account policy, tracked in the same validation register.
- Accountant field confirmation of foreign-supplier, import/customs, and
  imported-service accounting/tax policy, tracked in the same register.
- Accountant field confirmation of goods/service export, customs completion,
  partial export, ETGB, and export-account policy, tracked in the same register.
- QNB field reconciliation continues under the accepted acquisition boundary.
  Direct-Zirve transport and reconciliation remain the later dedicated phase.
- PRD acceptance scenarios are the initial canonical set and may gain test-case
  detail during implementation without reopening the product contract.
