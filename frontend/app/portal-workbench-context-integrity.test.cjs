// File: frontend/app/portal-workbench-context-integrity.test.cjs
// Summary: Verifies canonical visible-document reconciliation and safe transient/empty Workbench states.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const appDir = __dirname;
const workflowHook = () => readFileSync(join(appDir, "features", "documents", "use-document-workflow.ts"), "utf8");
const workspace = () => readFileSync(join(appDir, "portal-workspace-view.tsx"), "utf8");

test("document workflow resolves the active document only from the visible review queue", () => {
  const source = workflowHook();
  assert.match(source, /reconcileSelectedDocumentId/);
  assert.match(source, /activeReviewDocuments\.find\(\(document\) => document\.id === selectedDocumentFromSegment\?\.id\)/);
  assert.match(source, /setSelectedDocumentId\(nextSelectedDocumentId\)/);
});

test("workbench query and queue changes reconcile before rendering mutation controls", () => {
  const source = workspace();
  assert.match(source, /reconcileSelectedDocumentId\(queueDocuments, selectedDocument\?\.id \|\| ""\)/);
  assert.match(source, /canonicalDocumentReady/);
  assert.match(source, /contextReconciling/);
  assert.match(source, /Belge görünümü güncelleniyor/);
  assert.match(source, /Bu filtrede belge yok/);
});

test("filtered-out active documents are not pinned as a separate persistent UX concept", () => {
  const source = workspace();
  assert.doesNotMatch(source, /Aktif belge üstte açık kalır/);
  assert.match(source, /Kuyruk ve açık belge birlikte güncellenir/);
  assert.match(source, /canonicalDocumentReady && selectedRequest/);
});

test("transient reconciliation also hides stale status and navigation affordances", () => {
  const source = workspace();
  assert.match(source, /DocumentAgentStrip document=\{canonicalDocumentReady \? selectedDocument : undefined\}/);
  assert.match(source, /disabled=\{!canonicalDocumentReady \|\| !navigationDocuments\.length\}/);
  assert.match(source, /canonicalDocumentReady \? selectedDocument\?\.fileName : queueIsEmpty/);
});
