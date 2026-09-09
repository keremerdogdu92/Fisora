# Fisora Multi-Agent Review Follow-up — 2026-09-09

## Purpose

This document is the current continuation plan for the 2026-09-05/06 multi-agent UX/accountant acceptance review.
It does not replace the preserved source audits. It converts the accepted decisions and the still-open findings into the next implementation sequence.

## Source of truth

Primary register:
- `docs/audits/2026-09-05/multi-agent-review-register-2026-09-06.md`

Independent audit sources:
- ChatGPT accountant acceptance audit
- Codex UX/QA audit
- Antigravity UX/UI audit

Repository state used for this follow-up:
- `main` HEAD before this document: `1c00c14c87f79619de893c649616e25de5d47d67`
- Latest implementation commit: `[deploy] Make review decisions reversible`
- No later implementation commit was present on `main` when this follow-up was created.

## Already implemented from the review plan

### Review actions

- `REV-B01` — transaction-based Ctrl+Z review undo is implemented. It is not time-window based.
- `REV-B02` — `Hariç tut` persists a reversible excluded/rejected state instead of collapsing back to `review_required`.
- `REV-B03` — excluded documents can be returned to control; a dedicated `Hariç tutulanlar` filter is still undecided.
- `REV-B05` — approval/reversible-action feedback is implemented in the existing workbench action area.
- `REV-B06` — `Kontrolde tut` means “process later”; it is not a terminal error state.

### Still requiring live verification

The source register marks the implemented B-section behavior as awaiting production UI verification. The implementation should not be considered fully closed until the real production flow is retested.

## Highest-priority open work from the original register

### P0/P1 — document identity and selection integrity

**Completed 2026-09-09:** `REV-A01`, `REV-A02`, `REV-A03`, `REV-A04` are accepted and implemented. `REV-A05` is rejected.

Canonical invariant:

`activeDocumentId == previewDocumentId == journalDocumentId == mutationTargetDocumentId`

Implementation now reconciles selection against the visible review/queue documents. A filtered-out stale selection moves to the first visible document; zero results clear selection and show a controlled empty state. During the brief internal reconcile state, preview/journal/mutation controls are not rendered. Genuine processing/accounting failures remain visible in the normal recovery queue instead of being treated as integrity faults.

Rejected UX: no persistent `Aktif belge — filtre dışında` pinned-document concept. Queue selection and the open Workbench document move together.

Acceptance evidence: document workflow/context regression tests pass, full frontend suite is `217/217`, and Next production build + TypeScript pass.

### Review-state provenance

**Completed 2026-09-09:** `REV-B04` — reopening an approved document now preserves the approved journal snapshot and its draft provenance. `Kontrole geri al` uses normalized journal reopen; normal `Kontrolde tut` keeps the generic review path.

Acceptance evidence: targeted provenance/reopen tests pass; full frontend suite is `219/219`; Next production build + TypeScript pass.

**Completed 2026-09-09:** `REV-D01` — approved documents no longer remain in the `Onaya hazır` queue; Workbench uses `Onaylandı` as the approved user-facing label and suppresses the stale draft-review label for approved documents.

Acceptance evidence: full frontend suite `220/220`; Next production build + TypeScript pass.

**Retested 2026-09-10:** `REV-D02` and `REV-D03` are not reproducible in the current build. Clean approval and normalized reopen preserve provenance. `REV-D04` remains only a product-model candidate; no extra state architecture is planned without a concrete need.

### Source linking

`REV-F01` was retested on 2026-09-10 and is not reproducible. `REV-F02` through `REV-F05` remain open.

The HTML/PDF source anchor model and workbench provenance interaction remain a separate high-priority reliability track.

## New decisions — 2026-09-09

### NEW-01 — Account-code combobox keyboard and wheel behavior

**Status:** ACCEPTED — implement and regression-test.

Current source already contains `ArrowDown`, `ArrowUp`, `Enter`, and `Tab` handling for the account-code combobox. The remaining work is therefore an interaction/focus/scroll integration fix, not a new autocomplete implementation.

Required behavior:

1. Typing continues to filter chart-of-accounts matches.
2. `ArrowDown` and `ArrowUp` move the active candidate while the combobox is open.
3. The workbench/global queue shortcuts must not steal those arrows while the account input owns keyboard focus.
4. The active candidate must automatically scroll into view when keyboard navigation moves beyond the visible portion of the popup.
5. Mouse-wheel scrolling over the options popup must scroll the options list normally.
6. `Enter` selects the visibly active candidate.
7. Disabled/non-detail accounts must never become a successful posting selection.
8. `Escape` closes the list without mutating the journal line.

Acceptance tests must cover keyboard navigation, focus ownership, popup scrolling, active-option visibility, and Enter selection.

### NEW-02 — Stronger hover, active-candidate, focus, and selected states

**Status:** ACCEPTED — system design rule; implement first on Workbench critical surfaces.

The current visual difference between neutral, hover, keyboard-active, and selected/current states is too subtle.

Required state model:

- `hover`: pointer is over an item; noticeable but temporary.
- `focus`: keyboard focus is on the control/item; clearly visible focus treatment.
- `active candidate`: this is the option that will be selected if Enter is pressed; stronger than hover.
- `selected/current`: this is the currently selected persistent item/document; strongest persistent state.

Initial required surfaces:

- account-code autocomplete options
- invoice/document queue
- other keyboard-driven selectable lists in the Workbench

The solution should use shared visual tokens/utilities instead of one-off colors so the same interaction hierarchy can be strengthened throughout Fisora without visual drift.

### NEW-03 — Approval completeness gate for unresolved accounts and counterparties

**Status:** ACCEPTED — this resolves the main product decision in `REV-C01`.

`Onayla ve sonraki` must not succeed while a required journal/posting row is unresolved.

Approval blockers include:

- blank required account code
- account code that does not resolve to a valid selectable/detail account
- unresolved counterparty/current-account requirement
- a proposed new counterparty account that has not actually been created/selected into a valid state
- any other required posting row that is still waiting for chart-of-accounts resolution

Important workflow rule:

- `Onayla ve sonraki` is blocked.
- `Kontrolde tut` remains available because it means “process later”.
- `Hariç tut` remains available because it means “do not account for this document”, not hard delete.

Required recovery UI:

When the unresolved item is a counterparty/current account, the user must be given a direct route to either:

- select an existing counterparty/current account, or
- create a new counterparty/current account and return to the same document.

The user must not be left at a disabled approval button without a clear next action.

`Dengeli` must continue to mean only debit/credit arithmetic balance. A separate incomplete-accounting state must make it clear that a balanced journal is not necessarily ready for approval.

Acceptance tests must prove that approval is rejected for incomplete required rows while hold/exclude remain usable.

### NEW-04 — Denser but more readable accounting typography

**Status:** ACCEPTED — default typography must become more readable without abandoning the compact Workbench strategy.

The current journal/accounting text is too thin and visually small for sustained accountant use.

Required direction:

1. Increase effective readability of journal/account-code/account-name/amount text.
2. Use a stronger default weight than the current thin presentation.
3. Increase size where necessary, but preserve the compact information density and avoid increasing row height more than needed.
4. Keep numeric alignment and account-code scanning fast.
5. Re-evaluate truncation at 1366×768 and at 125% browser zoom together with `REV-K03`, `REV-K04`, and `REV-K05`.
6. Do not solve this by blindly applying bold to every text element; establish a deliberate hierarchy for primary values, secondary explanations, metadata, and controls.

Recommended implementation approach:

- Make the new, more readable typography the default.
- Add a temporary internal/demo comparison toggle only for accountant evaluation if useful; do not make a permanent customer-facing preference unless testing proves it is needed.
- The toggle must not become a substitute for improving the default.

## Updated original-plan mappings

### `REV-C01`

Decision is now resolved: missing required account/counterparty resolution is a hard gate for approval, with a guided recovery path. Hold and exclude remain allowed.

### `REV-G01`, `REV-G02`, `REV-G03`, `REV-R07`

The account autocomplete exists and keyboard handlers exist in source. The next task is to reproduce and fix focus/scroll/active-state behavior, then close the contradictory audit result with regression tests.

### `REV-K03`, `REV-K04`, `REV-K05`, `REV-K06`

Typography/readability work is now explicitly accepted. The compact layout remains a hard product constraint.

### `REV-L`

Add interaction-state clarity as a Workbench micro-UX requirement: hover, active keyboard candidate, focus, and persistent selection must be visibly distinguishable.

## Recommended implementation order

Completed in the 2026-09-09 implementation passes:

1. **Approval safety gate** — `REV-C01` + `NEW-03`.
2. **Account combobox focus/navigation** — `NEW-01` + `REV-G01/G02/G03/R07` core behavior.
3. **Interaction-state visual hierarchy** — `NEW-02` on account options and invoice queue.
4. **Accounting typography/readability** — `NEW-04` default Workbench typography pass.
5. **Canonical active-document integrity** — `REV-A01/A02/A03/A04`; `REV-A05` rejected.
6. **Client period-scope counters** - `REV-E04/E05`; list and detail summaries now share the selected office period.

Completed 2026-09-10: **`REV-I01` + `REV-I02`** - Learned Rules now maps backend/JSON failures to short accountant-safe messages; raw `error.message` is no longer rendered. Acceptance: targeted regression PASS, full frontend 222/222, Next build + TypeScript PASS.

Completed 2026-09-10: **`REV-I03`** - QNB connection, sync, and policy failures now use short accountant-safe messages; raw backend/endpoint `error.message` is not rendered. Acceptance: targeted regression PASS, full frontend 223/223, Next build + TypeScript PASS.

Next audit verification: **`REV-I04`** - QNB production configuration detail leakage. Test first; do not change the settings model until the current visible fields are verified.

## Required acceptance matrix for this pass

### Account combobox

- type account prefix -> filtered results appear
- ArrowDown/ArrowUp -> active candidate visibly changes
- active candidate stays in viewport
- mouse wheel -> options list scrolls
- Enter -> visibly active candidate is selected
- global queue shortcut does not fire while account input owns focus

### Queue/list state visibility

- pointer hover is obvious
- keyboard focus is obvious
- current selected invoice is unambiguous
- keyboard-active candidate and persistent selected/current item are not visually confused

### Approval gate

- blank required account -> approval blocked with actionable reason
- invalid/non-detail account -> approval blocked
- unresolved counterparty -> approval blocked and select/create actions are offered
- resolved rows -> approval becomes available
- `Kontrolde tut` still works with an incomplete journal
- `Hariç tut` still works with an incomplete journal

### Typography

- 100% browser zoom on standard desktop
- 1366×768 laptop viewport
- 125% browser zoom
- compact journal density remains usable
- account code, account name, source description, and amount remain scannable

## Separate three-analysis thread

There was also a separate 2026-09-06 upload-focused three-analysis discussion:

1. Security & Flow
2. Upload UX/UI
3. Automatic Routing / Classification

That work was summarized as an upload-flow hardening/automatic-routing plan. It is a different thread from this tracked ChatGPT + Codex + Antigravity multi-agent UX review register. The present follow-up continues the latter because the new requests are Workbench/accounting-review UX and approval-safety changes.
