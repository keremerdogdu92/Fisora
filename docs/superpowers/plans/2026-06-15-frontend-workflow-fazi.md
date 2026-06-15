# Frontend Workflow Fazi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the portal frontend strong enough for the real pilot workflow by turning the existing feature folders into real boundaries, moving workspace data flow to TanStack Query, and enforcing the core UX with Playwright.

**Architecture:** Keep `frontend/app/portal-app.tsx` as the route/session/workflow orchestrator, but move data loading, feature actions, derived selectors, and workflow-specific state into `features/*` modules. Preserve existing route URLs, backend HTTP contracts, and the current FastAPI service layer.

**Tech Stack:** Next.js, React 19, TanStack Query, Playwright, Node test runner, existing FastAPI Phase 0 APIs.

---

## Current State

- `frontend/app/portal-app.tsx` is still large and owns most state, derived data, and workflow handlers.
- `frontend/app/features/*` exists, but most files currently re-export older `portal-*` action modules.
- `frontend/app/features/workspace/query-provider.tsx` already adds the first TanStack Query boundary.
- `frontend/package.json` already contains `@tanstack/react-query`, `@playwright/test`, and `test:e2e`.
- `frontend/e2e/real-data-pilot.spec.ts` currently checks readiness and landing role entry, not the full document/review/export workflow.
- Do not revert existing local changes. Work with the current dirty tree.

## Completion Gate

Run these before claiming the phase is complete:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
cd frontend
npm.cmd run build
npm.cmd run test:e2e
```

Expected result:

- Backend tests pass.
- Frontend Node tests pass.
- Next build passes.
- Playwright runs the restricted pilot workflow without mojibake or route failures.

---

### Task 1: Lock The Frontend Boundary With Tests

**Files:**
- Modify: `frontend/app/e2e-gate.test.cjs`
- Modify: `frontend/app/portal-routes.test.cjs`
- Read: `frontend/app/portal-app.tsx`
- Read: `frontend/app/features/*/index.ts`

- [ ] **Step 1: Add structure assertions for real feature ownership**

Add checks to `frontend/app/e2e-gate.test.cjs` that assert these files exist:

```js
[
  "features/workspace/query-provider.tsx",
  "features/workspace/index.ts",
  "features/session/index.ts",
  "features/documents/index.ts",
  "features/review/index.ts",
  "features/export/index.ts",
  "features/clients/index.ts",
  "shared/components/index.ts",
].forEach((path) => {
  assert.equal(existsSync(join(__dirname, path)), true, `${path} should exist`);
});
```

- [ ] **Step 2: Add a guard against growing `portal-app.tsx`**

In the same test file, assert that `portal-app.tsx` stays below a fixed line count after each extraction:

```js
test("portal app remains an orchestrator instead of a feature implementation file", () => {
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  assert.ok(portalApp.split(/\r?\n/).length <= 620, "portal-app.tsx should keep shrinking as feature modules take ownership");
});
```

If the current file is above this limit, set the first limit to the current line count minus the lines removed in the same task. Do not increase the limit later.

- [ ] **Step 3: Run the focused tests**

Run:

```powershell
node --test frontend/app/e2e-gate.test.cjs frontend/app/portal-routes.test.cjs
```

Expected: Fail first if the line-count guard or missing ownership checks are not satisfied, then pass after extraction tasks.

- [ ] **Step 4: Commit**

```powershell
git add -- frontend/app/e2e-gate.test.cjs frontend/app/portal-routes.test.cjs
git commit -m "test: lock frontend workflow boundaries"
```

---

### Task 2: Make Workspace Data Loading A Query Boundary

**Files:**
- Create: `frontend/app/features/workspace/queries.ts`
- Modify: `frontend/app/features/workspace/index.ts`
- Modify: `frontend/app/portal-app.tsx`
- Test: `frontend/app/e2e-gate.test.cjs`

- [ ] **Step 1: Create workspace query keys and hook**

Create `frontend/app/features/workspace/queries.ts`:

```ts
"use client";

import { useQuery } from "@tanstack/react-query";
import { emptyPilotData, normalizePilotData } from "../../portal-data-mappers";
import type { LocalSession, PilotData } from "../../portal-types";
import { fetchBackendPilotData, fetchBackendReadiness } from "../../workspace-api";
import { resolveApiBaseUrl } from "../../upload-api";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export const workspaceQueryKeys = {
  data: (userId: string, sessionToken?: string) => ["workspace", "data", userId, sessionToken ?? "anonymous"] as const,
  readiness: () => ["workspace", "readiness"] as const,
};

export function useWorkspaceDataQuery({
  defaultUserId,
  session,
}: {
  defaultUserId: string;
  session: LocalSession | null;
}) {
  const userId = session?.userId || defaultUserId;
  return useQuery({
    queryKey: workspaceQueryKeys.data(userId, session?.sessionToken),
    queryFn: async (): Promise<PilotData> => {
      const payload = await fetchBackendPilotData({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        sessionToken: session?.sessionToken,
        userId,
      });
      return normalizePilotData(payload as PilotData);
    },
    initialData: emptyPilotData,
  });
}

export function usePilotReadinessQuery() {
  return useQuery({
    queryKey: workspaceQueryKeys.readiness(),
    queryFn: async () =>
      (await fetchBackendReadiness({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      })) as Record<string, unknown>,
  });
}
```

- [ ] **Step 2: Export the query boundary**

Modify `frontend/app/features/workspace/index.ts`:

```ts
export {
  buildPilotReadinessView,
  loadInitialPilotData,
  refreshBackendPilotData,
} from "../../portal-workspace-actions";
export { PilotQueryProvider } from "./query-provider";
export { usePilotReadinessQuery, useWorkspaceDataQuery, workspaceQueryKeys } from "./queries";
```

- [ ] **Step 3: Wire the readiness query without changing UI copy**

In `portal-app.tsx`, import `usePilotReadinessQuery`. Replace direct readiness-only `useEffect` ownership with a query result where possible. Keep `loadInitialPilotData` fallback behavior until Task 3 moves data loading fully.

Important behavior to preserve:

- Local fallback is allowed only when existing `canUseLocalPilotFallback` rules allow it.
- `pilot_sellable` and `production_ready` stay separate in the operations screen.
- No visible route or API path changes.

- [ ] **Step 4: Add test guard for query hook usage**

In `frontend/app/e2e-gate.test.cjs`, assert:

```js
const workspaceQueries = readFileSync(join(__dirname, "features", "workspace", "queries.ts"), "utf8");
assert.match(workspaceQueries, /useQuery/);
assert.match(workspaceQueries, /workspaceQueryKeys/);
```

- [ ] **Step 5: Run tests**

```powershell
node --test frontend/app/e2e-gate.test.cjs frontend/app/pilot-readiness.test.cjs
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/app/features/workspace frontend/app/portal-app.tsx frontend/app/e2e-gate.test.cjs
git commit -m "feat: add workspace query boundary"
```

---

### Task 3: Move Document Workflow State And Mutations

**Files:**
- Create: `frontend/app/features/documents/use-document-workflow.ts`
- Modify: `frontend/app/features/documents/index.ts`
- Modify: `frontend/app/portal-app.tsx`
- Test: `frontend/app/e2e-gate.test.cjs`

- [ ] **Step 1: Extract selected document and statement-line workflow**

Create `use-document-workflow.ts` with the state currently owned by `portal-app.tsx`:

```ts
"use client";

import { useEffect, useMemo, useState } from "react";
import { isCancelStatus } from "../../portal-formatters";
import type { DocumentSegment, PilotDocument, ReviewFilter } from "../../portal-types";
import { documentsForProcessing } from "../../portal-dashboard";

export function useDocumentWorkflow({
  allDocuments,
  clientDocuments,
  mode,
  selectedClientId,
}: {
  allDocuments: PilotDocument[];
  clientDocuments: PilotDocument[];
  mode: string;
  selectedClientId?: string;
}) {
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [selectedDocumentSegment, setSelectedDocumentSegment] = useState<DocumentSegment>("invoices");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("review_required");
  const [selectedStatementLineNo, setSelectedStatementLineNo] = useState(0);

  const segmentedClientDocuments = useMemo(
    () =>
      documentsForProcessing({
        documents: allDocuments,
        clientId: selectedClientId,
        segment: selectedDocumentSegment,
      }) as PilotDocument[],
    [allDocuments, selectedClientId, selectedDocumentSegment],
  );

  const visibleReviewDocuments = useMemo(() => {
    if (reviewFilter === "all") return clientDocuments;
    if (reviewFilter === "cancel_requested") return clientDocuments.filter((document) => isCancelStatus(document.status));
    return clientDocuments.filter((document) => document.status === reviewFilter);
  }, [clientDocuments, reviewFilter]);

  const visibleProcessingDocuments = useMemo(() => {
    if (reviewFilter === "all") return segmentedClientDocuments;
    if (reviewFilter === "cancel_requested") return segmentedClientDocuments.filter((document) => isCancelStatus(document.status));
    return segmentedClientDocuments.filter((document) => document.status === reviewFilter);
  }, [reviewFilter, segmentedClientDocuments]);

  const activeReviewDocuments = mode === "documents" ? visibleProcessingDocuments : visibleReviewDocuments;
  const selectedDocumentSource = mode === "documents" ? segmentedClientDocuments : activeReviewDocuments;
  const selectedDocument = selectedDocumentSource.find((document) => document.id === selectedDocumentId);
  const selectedStatementLineKey = selectedDocument?.statementLines.map((line) => line.line_no).join("|") ?? "";

  useEffect(() => {
    const firstLineNo = selectedDocument?.statementLines[0]?.line_no ?? 0;
    if (!firstLineNo) {
      setSelectedStatementLineNo(0);
      return;
    }
    const hasSelectedLine = selectedDocument?.statementLines.some((line) => line.line_no === selectedStatementLineNo);
    if (!hasSelectedLine) setSelectedStatementLineNo(firstLineNo);
  }, [selectedDocument?.id, selectedStatementLineKey, selectedStatementLineNo]);

  return {
    activeReviewDocuments,
    reviewFilter,
    segmentedClientDocuments,
    selectedDocument,
    selectedDocumentId,
    selectedDocumentSegment,
    selectedStatementLineNo,
    setReviewFilter,
    setSelectedDocumentId,
    setSelectedDocumentSegment,
    setSelectedStatementLineNo,
    visibleProcessingDocuments,
    visibleReviewDocuments,
  };
}
```

- [ ] **Step 2: Export the hook**

Modify `features/documents/index.ts`:

```ts
export {
  addLocalUploadsAction,
  requestStatementAiForSelectedDocumentAction,
  saveDecisionAction,
  saveStatementLineDecisionAction,
} from "../../portal-document-actions";
export { useDocumentWorkflow } from "./use-document-workflow";
```

- [ ] **Step 3: Replace duplicated state in `portal-app.tsx`**

Remove direct `useState` and `useMemo` blocks for:

- `selectedDocumentId`
- `selectedDocumentSegment`
- `reviewFilter`
- `selectedStatementLineNo`
- `segmentedClientDocuments`
- `visibleReviewDocuments`
- `visibleProcessingDocuments`
- `activeReviewDocuments`
- `selectedDocument`

Use the returned values from `useDocumentWorkflow`.

- [ ] **Step 4: Run tests**

```powershell
node --test frontend/app/*.test.cjs
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/app/features/documents frontend/app/portal-app.tsx frontend/app/e2e-gate.test.cjs
git commit -m "refactor: move document workflow state into feature hook"
```

---

### Task 4: Move Review And Export Commands Behind Feature Hooks

**Files:**
- Create: `frontend/app/features/review/use-review-commands.ts`
- Create: `frontend/app/features/export/use-export-commands.ts`
- Modify: `frontend/app/features/review/index.ts`
- Modify: `frontend/app/features/export/index.ts`
- Modify: `frontend/app/portal-app.tsx`

- [ ] **Step 1: Extract review commands**

Create `features/review/use-review-commands.ts` that wraps:

- `approveSelectedAndMoveNext`
- `selectAdjacentReviewDocument`
- `saveDecision`
- `saveStatementLineDecision`
- `requestStatementAiForSelectedDocument`

The hook should accept the current dependencies as arguments instead of importing global state. Keep the existing action functions in `portal-document-actions.ts`.

- [ ] **Step 2: Extract export commands**

Create `features/export/use-export-commands.ts` that wraps:

- `addSelectedClientToBasket`
- `markBasketPackaged`
- `requestCancellation`
- `resolveCancellation`

The hook should accept `setData`, selected client/document values, and status setters. Keep existing action functions in `portal-export-actions.ts`.

- [ ] **Step 3: Keep route components unchanged**

Do not redesign `portal-documents-view.tsx`, `portal-workspace-view.tsx`, or `portal-exports-view.tsx` in this task. Only change where handlers are created.

- [ ] **Step 4: Run tests**

```powershell
node --test frontend/app/*.test.cjs
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/app/features/review frontend/app/features/export frontend/app/portal-app.tsx
git commit -m "refactor: move review and export commands into feature hooks"
```

---

### Task 5: Expand Playwright To The Core Pilot Workflow

**Files:**
- Modify: `frontend/e2e/real-data-pilot.spec.ts`
- Modify: `frontend/playwright.config.ts` if timeout or route handling must be tuned

- [ ] **Step 1: Add deterministic API route fixtures**

In `real-data-pilot.spec.ts`, route these backend calls:

- `**/phase0/store/system/readiness`
- `**/phase0/store/clients`
- `**/phase0/store/workspace*` or the actual workspace data endpoint used by `workspace-api.js`
- `**/phase0/ai/statement-suggestions*` if the current UI triggers it through fetch

Use a fixture containing:

- one accountant session
- one client
- one bank statement document with statement lines
- one invoice document ready for review
- one export-ready document

- [ ] **Step 2: Test login and document selection**

Add a test that enters the accountant portal and verifies:

- route is `/portal/musavir` or `/portal/belgeler`
- document workspace is visible
- the fixture client name is visible
- selecting a document shows its review state

- [ ] **Step 3: Test AI draft and decision flow**

Add a test that:

- opens a bank statement document
- clicks the AI suggestion command
- verifies the AI status text changes
- approves one statement line
- verifies the next line or next document becomes active

- [ ] **Step 4: Test export basket flow**

Add a test that:

- opens `/portal/cikti`
- adds the selected client to the export basket
- marks the package as prepared
- verifies exported/package status text is visible

- [ ] **Step 5: Run Playwright**

```powershell
cd frontend
npm.cmd run test:e2e
```

Expected: Chromium passes without relying on live server data.

- [ ] **Step 6: Commit**

```powershell
git add -- frontend/e2e/real-data-pilot.spec.ts frontend/playwright.config.ts
git commit -m "test: cover core portal workflow with playwright"
```

---

### Task 6: Full Verification And Deploy Readiness Check

**Files:**
- Modify only if failures identify a concrete bug.
- Read: `docs/current-handoff.md`

- [ ] **Step 1: Run backend tests**

```powershell
python -m unittest discover -s backend/tests
```

- [ ] **Step 2: Run frontend Node tests**

```powershell
node --test frontend/app/*.test.cjs
```

- [ ] **Step 3: Run Next build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 4: Run Playwright**

```powershell
cd frontend
npm.cmd run test:e2e
```

- [ ] **Step 5: Review diff**

```powershell
git status --short
git diff --stat
```

Expected:

- `portal-app.tsx` is smaller.
- `features/documents`, `features/review`, `features/export`, and `features/workspace` contain real implementation, not only re-exports.
- `frontend/e2e/real-data-pilot.spec.ts` covers the core pilot workflow.

- [ ] **Step 6: Final commit if needed**

```powershell
git add -- frontend/app frontend/e2e frontend/playwright.config.ts frontend/package.json frontend/package-lock.json
git commit -m "feat: strengthen frontend pilot workflow"
```

---

## Deferred Work

These are intentionally not in this phase:

- React Hook Form + Zod across all forms.
- Full UI redesign.
- Alembic migration rollout.
- Repository-layer replacement work.
- Object storage adapter.
- Audit-log persistence.

Those should become later phases after the frontend workflow gate is stable.

