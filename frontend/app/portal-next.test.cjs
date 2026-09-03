// File: frontend/app/portal-next.test.cjs
// Summary: Locks the parallel UI migration boundary so the next-generation route can evolve without replacing the existing portal routes before cutover.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

function source(...parts) {
  return readFileSync(join(__dirname, ...parts), "utf8");
}

test("portal-next opts into the new presentation while legacy portal stays default", () => {
  const nextPage = source("portal-next", "page.tsx");
  const legacyPage = source("portal", "musavir", "page.tsx");
  const portalApp = source("portal-app.tsx");

  assert.match(nextPage, /presentation="next"/);
  assert.match(nextPage, /routeKey="musavir"/);
  assert.doesNotMatch(legacyPage, /presentation="next"/);
  assert.match(portalApp, /presentation = "legacy"/);
});

test("next sidebar uses the approved accountant navigation order", () => {
  const shell = source("portal-next", "portal-next-shell.tsx");
  const sidebar = shell.slice(shell.indexOf("const NEXT_SIDEBAR_ITEMS"), shell.indexOf("];", shell.indexOf("const NEXT_SIDEBAR_ITEMS")) + 2);
  const labels = ["Ana Sayfa", "Çalışma Masası", "Onay & Çıktılar", "Mükellefler", "AI Ajanları", "Öğrenilen Kurallar", "İşlem Durumu", "Ayarlar"];
  let previousIndex = -1;
  for (const label of labels) {
    const nextIndex = sidebar.indexOf(`label: "${label}"`);
    assert.ok(nextIndex > previousIndex, `${label} should keep the approved sidebar order`);
    previousIndex = nextIndex;
  }

  assert.doesNotMatch(sidebar, /MÜŞAVİR İŞLERİ/);
  assert.doesNotMatch(sidebar, /label: "Faturalar"/);
  assert.doesNotMatch(sidebar, /label: "Banka Ekstreleri"/);
  assert.doesNotMatch(sidebar, /label: "Diğer Belgeler"/);
});

test("invoice bank and other document navigation lives inside the next workbench", () => {
  const shell = source("portal-next", "portal-next-shell.tsx");

  assert.match(shell, /PortalNextWorkTypeTabs/);
  assert.match(shell, />Faturalar <span>/);
  assert.match(shell, />Banka <span>/);
  assert.match(shell, />Diğer Belgeler <span>/);
  assert.match(shell, /"bank_statements"/);
  assert.match(shell, /"other_documents"/);
});
test("controlled PDF viewer is enabled only for the next presentation", () => {
  const portalApp = source("portal-app.tsx");
  const workspace = source("portal-workspace-view.tsx");
  const reviewPanels = source("portal-review-panels.tsx");
  const pdfViewer = source("shared", "components", "document-viewers", "pdf-document-viewer.tsx");

  assert.match(portalApp, /controlledPdfPreview=\{isNextPresentation\}/);
  assert.match(workspace, /controlledPdfPreview \? \(/);
  assert.match(workspace, /<DocumentPreview controlledPdfPreview document=/);
  assert.match(reviewPanels, /controlledPdfPreview = false/);
  assert.match(reviewPanels, /pdfPreview \? \(/);
  assert.match(reviewPanels, /original-document-frame/);
  assert.match(pdfViewer, /pdfjs-dist/);
  assert.match(pdfViewer, /ResizeObserver/);
  assert.match(pdfViewer, /Sayfaya sığdır/);
  assert.match(pdfViewer, /Genişliğe sığdır/);
  assert.match(pdfViewer, /pageNumber/);
  assert.match(pdfViewer, /effectiveScale/);
});

test("next workbench prefers the latest invoice-bearing period on initial entry", () => {
  const workspaceModel = source("portal-next", "portal-next-workspace-model.ts");

  assert.match(workspaceModel, /function isInvoice/);
  assert.match(workspaceModel, /const invoicePeriods =/);
  assert.match(workspaceModel, /const defaultPeriod = invoicePeriods\[0\] \|\| availablePeriods\[0\]/);
  assert.match(workspaceModel, /selectedPeriod && availablePeriods\.includes\(selectedPeriod\)/);
});

test("next keyboard controls preserve review guards and desktop-only legend", () => {
  const controls = source("portal-next", "portal-next-workspace-controls.tsx");
  const styles = source("portal-next", "portal-next.css");

  assert.match(controls, /button:not\(:disabled\)/);
  assert.match(controls, /event\.key === "F10"/);
  assert.match(controls, /event\.ctrlKey && event\.key === "Enter"/);
  assert.match(controls, /event\.ctrlKey && event\.key\.toLowerCase\(\) === "z" && undoAvailable/);
  assert.match(styles, /\.portal-next-shortcut-bar/);
  assert.match(styles, /@media \(max-width: 860px\)[\s\S]*?\.portal-next-shortcut-bar[\s\S]*?display: none/);
});
