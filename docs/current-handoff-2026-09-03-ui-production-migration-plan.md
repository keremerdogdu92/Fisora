# Fisora UI Production Migration Plan — 2026-09-03

## Purpose

This document is the implementation handoff for migrating the validated Fisora HTML UI/UX prototype into the real Fisora frontend.

The HTML prototype is a design and interaction source-of-truth, not production code. Production must reuse the existing backend, accounting workflow, review state, approval actions, document storage, and security boundaries.

## Validated prototype direction

The current reference prototype is `fisora-unified-prototype-v13-real-invoice-set.html`.

Key decisions validated in the prototype:

- Fisora keeps the existing dark green sidebar identity.
- Main content uses the cleaner navy / slate / white accounting visual language.
- The product remains information-dense enough for professional accounting work.
- Daily controls stay visible; advanced controls move behind lower-priority disclosures.
- Technical pipeline/provider terminology must not be shown in normal user-facing UI.
- Turkish accounting terminology is expected and should remain explicit.

## Navigation and shell

Target sidebar order:

1. Ana Sayfa
2. Çalışma Masası
3. Onay & Çıktılar
4. Mükellefler
5. AI Ajanları
6. Öğrenilen Kurallar
7. İşlem Durumu
8. Ayarlar

The `MÜŞAVİR İŞLERİ` section label is removed.

`Faturalar`, `Banka`, and `Diğer Belgeler` are not primary sidebar destinations. They belong inside `Çalışma Masası` as work-type tabs.

The signed-in user / role remains at the bottom of the sidebar. The visible role label should use normal product language such as `Müşavir` rather than technical portal terminology.

Desktop sidebar supports expanded and collapsed rail states. Mobile uses the existing drawer pattern.

## Çalışma Masası target

Çalışma Masası always operates on one selected taxpayer and one accounting period.

Primary work tabs:

- Faturalar
- Banka
- Diğer Belgeler

The invoice review surface is the highest-priority migration target.

The production layout should preserve the real existing state/actions while moving toward the v13 composition:

- compact taxpayer / period context
- compact queue filters and document navigation
- real source document on the left
- real journal draft on the right
- clear debit / credit / balanced state
- primary `Onayla ve sonraki` action
- advanced decision, learning, validation, and technical history placed behind secondary disclosures

The bottom full document table and large technical agent-stage cards should not dominate the daily review surface.

## Real document rendering

The HTML prototype used rasterized real PDFs only to validate geometry. Production must not convert the normal document workflow into static PNG previews.

Current production already fetches the original document bytes through the existing document-file endpoint and `DocumentPreview` renders supported documents.

Target reusable boundary:

- `DocumentViewer`
  - `PdfDocumentViewer`
  - `HtmlDocumentViewer`
  - `ImageDocumentViewer`

PDF target behavior:

- render the real PDF with a controllable PDF renderer such as PDF.js
- page-by-page navigation for multi-page documents
- fit page
- fit width
- zoom
- ResizeObserver-based responsive scaling
- preserve room for future source/evidence highlighting

HTML remains sandboxed. Image documents remain normal image previews.

## Existing production component mapping

Current repo structure supports the migration without replacing the accounting engine.

Relevant existing components:

- `frontend/app/portal-shell-components.tsx`
  - current sidebar and topbar
- `frontend/app/portal-workspace-view.tsx`
  - current accountant workbench and document navigation
- `frontend/app/portal-review-panels.tsx`
  - current `DocumentPreview`, `JournalPanel`, real review actions, manual journal editing, validation, learning and approval gates
- `frontend/app/portal-exports-view.tsx`
  - current output / control workflow

Production migration must preserve callbacks and real state such as selected client/document, correction draft, approval, save-decision, reprocess, review status and account validation.

The migration is primarily a UI composition and component-boundary change, not an accounting workflow rewrite.

## Keyboard behavior

Target desktop shortcuts:

- F1 — keyboard shortcuts / help
- F2 — edit journal
- F3 — change taxpayer / period
- F10 — collapse / expand main menu
- Up / Down — previous / next document
- Ctrl + Enter — approve and move to next document
- Ctrl + Z — undo the last approval within 8 seconds
- Esc — close the active modal or edit state

Desktop shows the slim shortcut legend by default and allows it to be hidden. Mobile does not show the shortcut legend.

Global shortcuts must not interfere with typing in inputs, textareas, selects, account comboboxes, or modal forms.

## AI language

Normal user-facing screens use agent/product language such as `Okuma Ajanı` and `Muhasebe Ajanı` where useful.

Do not expose `Reader`, `Planner`, provider names, pipeline stages, model names, or internal debug terminology in the normal work surface.

Technical history remains available only as an advanced/debug disclosure for authorized users.

## Migration phases

### Phase 1 — Shell and design system

- introduce reusable design tokens
- migrate sidebar / topbar visual language
- apply final sidebar order
- remove the `MÜŞAVİR İŞLERİ` heading
- preserve responsive drawer and collapsed desktop rail

### Phase 2 — Çalışma Masası shell

- move invoice / bank / other-document navigation into workbench tabs
- retain selected taxpayer and selected document state
- reduce technical/secondary UI weight
- establish the v13 document + journal composition

### Phase 3 — Real PDF viewer

- replace uncontrolled PDF iframe behavior with a controllable real-PDF viewer
- keep the existing authenticated document endpoint
- test with the real invoice corpus, including dense and multi-page PDFs

### Phase 4 — Journal visual migration

- keep the existing real draft-line and approval behavior
- migrate the visible journal table to the validated accounting-table design
- keep debit / credit totals and balanced state prominent
- move learning, validation and secondary actions behind lower-priority disclosures

### Phase 5 — Keyboard workflow

- implement the approved shortcut set
- add the desktop shortcut legend
- add the 8-second approval undo behavior without weakening backend review integrity

### Phase 6 — Remaining screens

Recommended order after the workbench is stable:

1. Ana Sayfa
2. Onay & Çıktılar
3. Mükellefler
4. Mükellefi Düzenle / Bağlantılar
5. AI Ajanları
6. Öğrenilen Kurallar
7. İşlem Durumu / Ayarlar

## Parallel UI migration and isolation strategy

The migration uses two independent safety layers at the same time.

### Git isolation

Do not implement the UI migration in the dirty canonical `main` worktree.

- Branch: `ui-vnext-20260903`
- Worktree: `C:\Users\kerem\Documents\Fisero-ui-vnext`
- Baseline: `e61a1fb`
- The canonical `C:\Users\kerem\Documents\Fisero` worktree remains available for the current production UI and unrelated work.

The user handles commit, push, merge, and deploy manually. This worktree is only for preparing and verifying the new UI.

### Runtime UI isolation

The existing `/portal/...` UI must remain operational while the new UI is built.

Create the new presentation layer under a parallel route namespace:

- existing UI: `/portal/...`
- new UI: `/portal-next/...`

Both UI generations use the same authenticated backend APIs, document store, accounting results, review state, approval commands, client data, account plans, QNB connections, and rule data. Do not create a second backend or duplicate accounting state.

The new UI may introduce new presentation components, but shared product/business behavior must continue to come from existing feature hooks and API modules wherever practical.

### Cutover sequence

1. Build and test `/portal-next/...` without changing the existing `/portal/...` behavior.
2. Compare old and new UI on the same real clients, documents, journal drafts, and approval actions.
3. Complete the agreed screens and responsive/keyboard regression gates.
4. When accepted, make the new presentation the canonical `/portal/...` route.
5. Keep the old UI temporarily available only if needed for rollback verification.
6. Remove the legacy presentation components only after the new route passes production parity checks.
7. Remove the temporary `Fisero-ui-vnext` worktree after merge and verification; never delete the canonical repository path.

### Required parity gates before legacy removal

- the same selected client / period resolves to the same underlying records
- the same document displays the same original source file
- the same journal draft lines, debit/credit totals, and review blocks are preserved
- approve / hold / exclude / reprocess actions retain existing backend semantics
- account validation and counterparty guards remain unchanged
- PDF, HTML, and image documents remain accessible
- desktop and mobile routes remain usable
- authentication and tenant boundaries remain unchanged

This parallel-UI strategy is preferred over patching the existing presentation in place because it allows direct old/new comparison and a controlled cutover without carrying a half-migrated interface in production.
## Non-goals / hard safety boundary

The UI migration must not silently change accounting semantics, AI/provider routing, document parsing, journal guards, counterparty selection, review state, storage, authentication, or database schema.

Any future need to change those areas requires separate source review and an explicit implementation decision.

## Implementation status — 2026-09-03

Phase 1 parallel-UI isolation is implemented in the `ui-vnext-20260903` worktree.

- `/portal-next` opts into the new presentation explicitly.
- Existing `/portal/...` routes continue to use the legacy presentation by default.
- New sidebar order matches the approved information architecture and has no `Müşavir İşleri` heading.
- `Faturalar / Banka / Diğer Belgeler` are represented as Çalışma Masası work-type tabs instead of sidebar destinations.
- New shell styles are scoped under `.portal-next-theme`; legacy route styles are not globally replaced.
- The shared portal controller, authenticated API hooks, review commands, document store access, and accounting state remain shared.
- A regression test locks the parallel-route boundary and approved navigation order.

Phase 2 has started with route-scoped v13-inspired workbench composition:

- the technical agent strip is removed from the next daily review surface
- the original document and journal remain side by side on desktop
- the document information rail is removed from the first viewport in the next presentation
- the real journal ledger is visually promoted above advanced validation/learning controls
- advanced pilot controls remain available lower in the existing journal scroll; their behavior was not deleted
- the existing original-document fetch path and real journal actions are unchanged

Verification at this checkpoint: 182/182 frontend Node tests pass, `next build` passes, and both `/portal-next` and legacy `/portal/*` routes are emitted.
## Implementation progress — controlled PDF viewer

Completed in the isolated `ui-vnext-20260903` worktree:

- `pdfjs-dist` added to the frontend dependency set.
- `/portal-next` enables the controlled PDF viewer; legacy `/portal/...` keeps the existing iframe behavior until cutover.
- authenticated document fetching remains in the existing `DocumentPreview` boundary.
- PDF rendering is isolated in `shared/components/document-viewers/pdf-document-viewer.tsx`.
- controls now support previous/next page, fit page, fit width, zoom out, zoom in, and responsive `ResizeObserver` scaling.
- the PDF.js worker is emitted by the Next/Turbopack build as a static media asset.
- high-DPI canvas rendering preserves the PDF page aspect ratio.
- zoomed canvases scroll safely instead of being clipped by centered flex overflow.

Validation completed:

- frontend source tests: 183/183 passing before final cleanup.
- production Next build passed with both `/portal-next` and all legacy `/portal/*` routes present.
- real PDF.js parse smoke test passed on three Rana corpus invoices, including a two-page invoice.
- browser smoke test passed on a real two-page TurkNet e-Fatura: page navigation `1 / 2 -> 2 / 2`, fit-width and zoom controls worked with no browser console errors.
- canvas pixel/content check and screenshot confirmed that the real invoice, QR code, line table, and totals were rendered rather than a blank/mock page.

No backend endpoint, accounting semantics, authentication rule, database schema, or document storage behavior was changed.

## Implementation progress — usable next workbench

The parallel `/portal-next` workbench is now usable as a complete local UI flow without replacing legacy routes.

- topbar client and period selectors are real controls, not display-only context
- next workbench data is scoped to the selected client and selected period
- initial entry prefers the latest period containing invoices because the default work type is `Faturalar`
- an explicitly selected period is preserved even when it contains only bank or other documents
- invoice queue filters are `Tümü`, `Kontrol`, and `Onaya hazır`
- compact `Evrak X / N` navigation is active and keyboard navigation respects editable-field focus
- desktop shortcut legend supports F1, F2, F3, F10, Arrow Up/Down, Ctrl+Enter, Ctrl+Z, and Esc
- Ctrl+Enter reuses the enabled guarded approval button instead of bypassing journal validation
- Ctrl+Z uses the existing revision-safe `/phase0/store/journal/reopen` endpoint for the supported eight-second invoice approval undo window
- the shortcut legend is hidden completely at the mobile breakpoint

Local browser smoke verification: default fallback opens `2026-04` with `Faturalar 3`, queue counts `Tümü 3 / Kontrol 2 / Onaya hazır 1`, and `Evrak 1 / 3`; ArrowDown advances to `Evrak 2 / 3`. F1 help, Esc close, F3 client focus, and F10 sidebar collapse all work.

Final verification at this checkpoint: 190/190 frontend Node tests pass, TypeScript passes, production `next build` passes, and `git diff --check` passes. The build still emits both `/portal-next` and all legacy `/portal/*` routes.
