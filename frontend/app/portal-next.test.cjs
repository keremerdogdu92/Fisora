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
  const labels = ["Ana Sayfa", "Çalışma Masası", "Onay & Çıktılar", "Mükellefler", "Yeni Yükleme", "AI Ajanları", "Öğrenilen Kurallar", "İşlem Durumu", "Ayarlar"];
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
test("next home mirrors the approved v13 office overview with period-scoped live data", () => {
  const dashboard = source("portal-dashboard-view.tsx");
  const portalApp = source("portal-app.tsx");
  const shell = source("portal-next", "portal-next-shell.tsx");
  const styles = source("portal-next", "portal-next.css");
  const resume = source("portal-dashboard-resume.ts");

  assert.match(dashboard, /portal-next-home-page/);
  assert.match(dashboard, /portal-next-home-metrics/);
  assert.match(dashboard, /portal-next-home-priority-card/);
  assert.match(dashboard, /portal-next-home-resume/);
  assert.match(dashboard, /portal-next-home-clients-card/);
  assert.match(dashboard, /portal-next-home-office-card/);
  assert.match(dashboard, /portal-next-home-activity-card/);
  assert.match(dashboard, /Kontrol gerekli/);
  assert.match(dashboard, /Son aktiviteler/);
  assert.match(dashboard, /nextPresentation/);
  assert.match(dashboard, /accountant-dashboard-page/);

  assert.match(portalApp, /resolvedOfficePeriod/);
  assert.match(portalApp, /officeDocuments/);
  assert.match(portalApp, /writeDashboardResume/);
  assert.match(portalApp, /resumeDashboardWork/);
  assert.match(portalApp, /openDashboardTask/);
  assert.match(shell, /portal-next-office-context/);
  assert.match(shell, /longPeriodLabel\(period\)/);
  assert.match(styles, /\.portal-next-home-grid/);
  assert.match(styles, /\.portal-next-home-metrics/);
  assert.match(resume, /fisora\.accountant\./);
  assert.match(resume, /window\.localStorage/);
});

test("controlled PDF viewer is enabled only for the next presentation", () => {
  const portalApp = source("portal-app.tsx");
  const workspace = source("portal-workspace-view.tsx");
  const reviewPanels = source("portal-review-panels.tsx");
  const pdfViewer = source("shared", "components", "document-viewers", "pdf-document-viewer.tsx");

  assert.match(portalApp, /controlledPdfPreview=\{isNextPresentation\}/);
  assert.match(workspace, /controlledPdfPreview \|\| controlledHtmlPreview/);
  assert.match(workspace, /<DocumentPreview controlledHtmlPreview=\{controlledHtmlPreview\} controlledPdfPreview=\{controlledPdfPreview\}/);
  assert.match(reviewPanels, /controlledPdfPreview = false/);
  assert.match(reviewPanels, /pdfPreview \? \(/);
  assert.match(reviewPanels, /original-document-frame/);
  assert.match(pdfViewer, /pdfjs-dist/);
  assert.match(pdfViewer, /ResizeObserver/);
  assert.match(pdfViewer, /Sığdır/);
  assert.match(pdfViewer, /Genişlik/);
  assert.match(pdfViewer, /%100/);
  assert.match(pdfViewer, /pageNumber/);
  assert.match(pdfViewer, /effectiveScale/);
});

test("HTML viewer remains sandboxed and shares compact fit, width, 100 percent, and bounded zoom controls", () => {
  const htmlViewer = source("shared", "components", "document-viewers", "html-document-viewer.tsx");
  const portalApp = source("portal-app.tsx");
  const workspace = source("portal-workspace-view.tsx");

  assert.match(htmlViewer, /sandbox="allow-same-origin"/);
  assert.match(htmlViewer, /allow-same-origin/);
  assert.doesNotMatch(htmlViewer, /allow-scripts/);
  assert.match(htmlViewer, /ResizeObserver/);
  assert.match(htmlViewer, /MIN_ZOOM = 0\.35/);
  assert.match(htmlViewer, /MAX_ZOOM = 3/);
  assert.match(htmlViewer, /fitMode.*"width"/);
  assert.match(htmlViewer, /Sığdır/);
  assert.match(htmlViewer, /Genişlik/);
  assert.match(htmlViewer, /%100/);
  assert.match(portalApp, /controlledHtmlPreview=\{isNextPresentation\}/);
  assert.match(workspace, /controlledHtmlPreview/);
});

test("next AI Agents separates overview, reading quality, and research while keeping source focus safe", () => {
  const agents = source("portal-next", "portal-next-agents-view.tsx");
  const portalApp = source("portal-app.tsx");
  const reviewPanels = source("portal-review-panels.tsx");

  assert.match(agents, /Genel Bakış/);
  assert.match(agents, /Okuma Kalitesi/);
  assert.match(agents, /Araştırma Kayıtları/);
  assert.match(agents, /Okuma Ajanı/);
  assert.match(agents, /Muhasebe Ajanı/);
  assert.match(agents, /Araştırma Ajanı/);
  assert.match(agents, /sourceTarget=\{sourceTarget\}/);
  assert.match(agents, /Reader/);
  assert.match(agents, /Fisora'da/);
  assert.match(portalApp, /PortalNextAgentsView/);
  assert.match(portalApp, /PortalNextLearnedRulesView/);
  assert.doesNotMatch(portalApp, /HtmlReaderQualityControl documents=/);
  assert.match(reviewPanels, /PdfDocumentViewer/);
});

test("next learned rules only presents confirmed active rules and lifecycle actions", () => {
  const agents = source("portal-next", "portal-next-agents-view.tsx");
  assert.match(agents, /activeRules = rules\.filter/);
  assert.match(agents, /Etkin öğrenme/);
  assert.match(agents, /Tedarikçi/);
  assert.match(agents, /Ürün ailesi/);
  assert.match(agents, /Vergi \/ işlem/);
  assert.match(agents, /changeStatus\(rule, "pause"\)/);
  assert.match(agents, /changeStatus\(rule, "archive"\)/);
  assert.match(agents, /Yeni adaylar önce AI Ajanları altında doğrulama sinyali olarak görünür/);
});
test("next workbench prefers the latest invoice-bearing period on initial entry", () => {
  const workspaceModel = source("portal-next", "portal-next-workspace-model.ts");

  assert.match(workspaceModel, /function isInvoice/);
  assert.match(workspaceModel, /const invoicePeriods =/);
  assert.match(workspaceModel, /const defaultPeriod = invoicePeriods\[0\] \|\| availablePeriods\[0\]/);
  assert.match(workspaceModel, /selectedPeriod && availablePeriods\.includes\(selectedPeriod\)/);
});

test("next outputs preserve the approved v13 target composition while marking future integrations", () => {
  const exportsView = source("portal-exports-view.tsx");
  const portalApp = source("portal-app.tsx");
  const styles = source("portal-next", "portal-next.css");

  assert.match(portalApp, /nextPresentation=\{isNextPresentation\}/);
  assert.match(exportsView, /Onay & Çıktılar/);
  assert.match(exportsView, /Çıktıya hazır/);
  assert.match(exportsView, /Kısa kontrol/);
  assert.match(exportsView, /Blokeli/);
  assert.match(exportsView, /Dönem toplamı/);
  assert.match(exportsView, /Excel çalışma dosyası/);
  assert.match(exportsView, /CSV çıktı paketi/);
  assert.match(exportsView, /Kontrol paketi/);
  assert.match(exportsView, /Zirve’ye otomatik gönder/);
  assert.match(exportsView, /HTML DEMO/);
  assert.match(exportsView, /portal-next-zirve-button/);
  assert.match(styles, /\.portal-next-export-grid/);
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

test("next workbench prioritizes queue, source document, journal, and focus mode", () => {
  const workspace = source("portal-workspace-view.tsx");
  const styles = source("portal-next", "portal-next.css");

  assert.match(workspace, /portal-next-workbench-commandbar/);
  assert.match(workspace, /portal-next-document-queue/);
  assert.match(workspace, /portal-next-workbench-stage/);
  assert.match(workspace, /Kuyruğu gizle/);
  assert.match(workspace, /Belgeyi incele/);
  assert.match(workspace, /fullscreen-action/);
  assert.match(workspace, /Tam ekran/);
  assert.match(workspace, /requestFullscreen/);
  assert.match(workspace, /journalHidden/);
  assert.match(workspace, /mobilePane/);
  assert.match(workspace, /portal-next-focus-document/);
  assert.match(workspace, /Evrak \{selectedDocument/);
  assert.match(styles, /grid-template-columns:\s*210px minmax\(0, 1fr\)/);
  assert.match(styles, /\.portal-next-workbench-stage\.next\.queue-hidden\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(styles, /focus-mode \.portal-next-document-queue\s*\{[\s\S]*?display:\s*grid/);
  assert.match(styles, /focus-mode\.queue-hidden \.portal-next-document-queue\s*\{\s*display:\s*none/);
  assert.match(styles, /\.portal-next-workbench-stage\.next\.focus-mode/);
  assert.match(styles, /focus-mode\.journal-hidden/);
  assert.match(styles, /portal-next-mobile-review-switch/);
});

test("journal source links locate and highlight the matching PDF or sandboxed HTML evidence", () => {
  const workspace = source("portal-workspace-view.tsx");
  const review = source("portal-review-panels.tsx");
  const types = source("portal-types.ts");
  const pdfViewer = source("shared", "components", "document-viewers", "pdf-document-viewer.tsx");
  const htmlViewer = source("shared", "components", "document-viewers", "html-document-viewer.tsx");
  const styles = source("portal-next", "portal-next.css");

  assert.match(types, /DocumentSourceTarget/);
  assert.match(types, /sourceAmount\?: string/);
  assert.match(review, /source-review-chip/);
  assert.match(review, /journal-account-caption/);
  assert.match(review, /chartAccountNameForCode/);
  assert.match(review, /aria-label="Fatura satırı açıklaması"/);
  assert.match(review, /journal-remove-line/);
  assert.match(review, /aria-label="Satırı sil"/);
  assert.match(review, /onFocusSource/);
  assert.match(review, /onHoverSource/);
  assert.match(types, /pinned\?: boolean/);
  assert.match(workspace, /hoverSourceTarget/);
  assert.match(workspace, /pinnedSourceTarget/);
  assert.match(workspace, /150/);
  assert.match(workspace, /setMobilePane\("preview"\)/);
  assert.match(pdfViewer, /getTextContent/);
  assert.match(pdfViewer, /findTokenSequence/);
  assert.match(pdfViewer, /LENS_ZOOM = 2\.2/);
  assert.match(pdfViewer, /TOUCH_HOLD_MS = 420/);
  assert.match(pdfViewer, /pdf-source-highlight/);
  assert.match(pdfViewer, /document-magnifier/);
  assert.match(pdfViewer, /magnifierRequested/);
  assert.match(pdfViewer, /setMagnifierRequested\(mode === "page"\)/);
  assert.match(pdfViewer, /Vurguyu kaldır/);
  assert.match(htmlViewer, /DOMParser/);
  assert.match(htmlViewer, /SOURCE_TARGET_ID/);
  assert.match(htmlViewer, /findTokenSequence/);
  assert.match(htmlViewer, /invoiceLineRows/);
  assert.match(htmlViewer, /#lineTable/);
  assert.match(htmlViewer, /sourceAmount/);
  assert.match(htmlViewer, /measureDocumentLayout/);
  assert.match(htmlViewer, />İçerik</);
  assert.match(htmlViewer, /LENS_ZOOM = 2\.2/);
  assert.match(htmlViewer, /TOUCH_HOLD_MS = 420/);
  assert.match(htmlViewer, /document-magnifier/);
  assert.match(htmlViewer, /magnifierRequested/);
  assert.match(htmlViewer, /setMagnifierRequested\(mode === "page"\)/);
  assert.match(htmlViewer, /Vurguyu kaldır/);
  assert.match(htmlViewer, /viewStateRef/);
  assert.match(htmlViewer, /sandbox="allow-same-origin"/);
  assert.doesNotMatch(htmlViewer, /allow-scripts/);
  assert.match(styles, /document-source-focus-controls/);
  assert.match(styles, /document-magnifier/);
  assert.match(styles, /journal-remove-line/);
  assert.match(styles, /journal-account-caption/);
  assert.match(styles, /account-code-combobox input[\s\S]*?width:\s*11ch/);
  assert.match(styles, /source-pinned-row/);
  assert.match(styles, /journal-source-row/);
});

test("collapsed next sidebar always keeps a visible expand control", () => {
  const shell = source("portal-next", "portal-next-shell.tsx");
  const styles = source("portal-next", "portal-next.css");

  assert.match(shell, /aria-label=\{collapsed \? "Menüyü genişlet" : "Menüyü daralt"\}/);
  assert.match(styles, /\.portal-next-sidebar\.collapsed \.portal-next-collapse\s*\{[\s\S]*?display:\s*inline-grid/);
});

test("shared login gateway uses the portal-next product language", () => {
  const page = source("page.tsx");
  const styles = source("styles.css");

  assert.match(page, /landing-shell fisora-gateway/);
  assert.match(page, /Akıllı ve öğrenen bir yardımcıyla günlük muhasebe işi daha net\./);
  assert.match(page, /Fisora, yapay zeka desteğini kararın yerine geçmek için değil/);
  assert.match(page, /gateway-identity-panel/);
  assert.match(page, /gateway-login-heading/);
  assert.match(page, /Fisora&apos;ya giriş yap/);
  assert.match(page, /Beni hatırla/);
  assert.match(page, /REMEMBERED_SESSION_TTL_HOURS = 30 \* 24/);
  assert.match(page, /ttlHours: rememberMe \? REMEMBERED_SESSION_TTL_HOURS : STANDARD_SESSION_TTL_HOURS/);
  assert.match(page, /storageScope: rememberMe \? "local" : "tab"/);
  assert.match(styles, /\.landing-login \.remember-session/);
  assert.match(styles, /\.fisora-gateway \.role-copy/);
  assert.match(styles, /--gateway-navy:\s*#1d3557/);
  assert.match(styles, /--gateway-ink:\s*#172033/);
});

test("next quick upload keeps invoice staging separate from the accounting workbench", () => {
  const portalApp = source("portal-app.tsx");
  const uploadView = source("portal-next", "portal-next-upload-view.tsx");
  const shell = source("portal-next", "portal-next-shell.tsx");

  assert.match(shell, /label: "Yeni Yükleme", mode: "uploads"/);
  assert.match(portalApp, /mode === "uploads" && isNextPresentation/);
  assert.match(portalApp, /<PortalNextUploadView/);
  assert.match(uploadView, /"purchase_invoice"/);
  assert.match(uploadView, /"sales_invoice"/);
  assert.match(uploadView, /accept="\.pdf,\.html,\.htm,\.xml,\.zip"/);
  assert.match(uploadView, /onUpload\(pendingFiles\)/);
  assert.match(uploadView, /Son yüklemeler/);
});
