# Fisora - REV-L04 Workbench queue identity handoff - 2026-09-12

## Repo state
- Repo: `C:\Users\kerem\Documents\Fisero`
- Base HEAD before REV-L04: `b8efb58 fix: reveal active queue item on reopen`
- Branch: `main`.
- REV-L04 status: IMPLEMENTED and committed in the current HEAD as `fix: clarify workbench queue identity`.
- Previous completed commits in this sequence: `90610b9` REV-L02, `b8efb58` REV-L03.
- Push/deploy remains intentionally out of scope.

## REV-L04 goal and product decision
Audit complaint: Workbench queue cards use technical-looking filenames as the dominant identity. The agreed direction is business identity first, without parsing invoice numbers from filenames.

Intended compact queue card hierarchy:
1. Row 1: counterparty title (fallback: meaningful provider; final fallback: original filename).
2. Row 2: real invoice number (fallback: document category) + amount.
3. Row 3: issue date/upload date.
4. Original filename remains available via the card tooltip/title for troubleshooting.

Real `invoice_number` must be projected from backend data (`invoice_number`, `original_invoice_number`, or QNB `source_invoice_no`). Do not derive it from filename patterns.

## UX fit evidence
The Workbench queue itself is fixed at 210 px; active card measured 198 px wide and 72 px high.
Three visual variants were tested in real Chromium:
- A: title + amount / invoice number + full date. Rejected: title had only ~120 px.
- B: title / invoice number + short date + amount. Better, but row 2 remained cramped.
- C: title / invoice number + amount / date. Selected.

Variant C measurements:
- card stays 198 x 72 px (no taller queue cards, no loss of visible queue density)
- title gets ~180 px; long legal names ellipsize but remain recognizable
- invoice number fits fully in the tested BEF example
- amount fits fully
- date fits fully
- validated at 1366x768, 1093x614 (125% equivalent), and 1000x700
Therefore no Workbench column width increase is required and preview/journal space is not reduced.

## Implemented scope
Modified files:
- `frontend/app/portal-types.ts`
- `frontend/app/workspace-api.js`
- `frontend/app/portal-data-mappers.ts`
- `frontend/app/portal-workspace-view.tsx`
- `frontend/app/portal-next/portal-next.css`
- `frontend/app/workspace-api.test.cjs`
- `frontend/e2e/document-inspector.spec.ts`

Implementation:
- `PilotDocument.invoiceNumber?: string`
- backend/workspace projection for `invoice_number`, `original_invoice_number`, and QNB `source_invoice_no`
- queue search includes filename, invoice number, counterparty title, provider, amount, and status
- queue identity fallback is counterparty title -> meaningful provider -> filename
- generic provider placeholders are skipped so they cannot replace a useful filename
- business-identity queue card keeps original filename in the tooltip
- E2E regression keeps the card at 72 px across 1366 / 1093 / 1000 widths
- workspace-api projection regression

Acceptance on the final files:
- targeted workspace-api: 17/17 PASS
- targeted queue identity Playwright: 2/2 PASS
- full frontend Node tests: 235/235 PASS
- full document-inspector Playwright: 12/12 PASS
- `npx tsc --noEmit`: PASS
- Next production build: PASS
- visible-source mojibake guard: PASS
- `git diff --check`: PASS

## Cleanup completed
PowerShell-induced question-mark mojibake in the REV-L04 source and E2E fixture was repaired with Unicode-safe edits. The provider fallback no longer depends on corrupted Turkish literals; generic provider labels are normalized before comparison. `Onaya hazır` and the Turkish E2E business title are valid UTF-8 again. The visible-source mojibake guard and `git diff --check` both pass.

## Closure
REV-L04 is IMPLEMENTED and committed in the current HEAD as `fix: clarify workbench queue identity`. Do not push or deploy this change. REV-L05 date-format consistency is the next separate discussion and was intentionally not included in L04.
