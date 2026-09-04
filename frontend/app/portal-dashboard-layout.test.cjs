const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

function source(name) {
  return readFileSync(join(__dirname, name), "utf8");
}

test("dashboard metrics use semantic Lucide icons through the shared Metric component", () => {
  const dashboard = source("portal-dashboard-view.tsx");
  const shared = source("portal-shared.tsx");

  assert.match(dashboard, /ClipboardCheck/);
  assert.match(dashboard, /FileSearch/);
  assert.match(dashboard, /PackageCheck/);
  assert.match(dashboard, /<Metric icon=\{ClipboardCheck\} label="Kontrol"/);
  assert.match(dashboard, /<Metric icon=\{FileSearch\} label="Sırada"/);
  assert.match(dashboard, /<Metric icon=\{PackageCheck\} label="Hazır"/);
  assert.match(shared, /icon\?: LucideIcon/);
  assert.match(shared, /aria-hidden="true"/);
  assert.match(shared, /className="metric-icon"/);
});

test("sidebar uses semantic icons instead of two-letter navigation badges", () => {
  const shell = source("portal-shell-components.tsx");

  assert.match(shell, /LayoutDashboard/);
  assert.match(shell, /Landmark/);
  assert.match(shell, /Bot/);
  assert.doesNotMatch(shell, /BookOpen/);
  assert.match(shell, /Settings/);
  assert.match(shell, /icon: LayoutDashboard/);
  assert.match(shell, /<Icon aria-hidden="true"/);
  assert.doesNotMatch(shell, /symbol:\s*"CA"/);
  assert.doesNotMatch(shell, /symbol:\s*"MK"/);
  assert.doesNotMatch(shell, /\{item\.symbol\}/);
});

test("portal sidebar can collapse so document review has more workspace width", () => {
  const portalApp = source("portal-app.tsx");
  const shell = source("portal-shell-components.tsx");
  const styles = source("styles.css");

  assert.match(portalApp, /const \[sidebarCollapsed, setSidebarCollapsed\] = useState\(false\);/);
  assert.match(portalApp, /sidebar-collapsed/);
  assert.match(portalApp, /collapsed=\{sidebarCollapsed\}/);
  assert.match(portalApp, /function toggleSidebarCollapsed\(\)/);
  assert.match(portalApp, /fisora\.portal\.sidebar\.collapsed/);
  assert.match(portalApp, /localStorage\.setItem\(SIDEBAR_COLLAPSED_STORAGE_KEY/);
  assert.match(portalApp, /onToggleCollapse=\{toggleSidebarCollapsed\}/);
  assert.match(shell, /aria-label=\{collapsed \? "Menüyü genişlet" : "Menüyü daralt"\}/);
  assert.match(shell, /className=\{collapsed \? "portal-sidebar collapsed" : "portal-sidebar"\}/);
  assert.match(styles, /\.portal-shell\.sidebar-collapsed\s*\{[\s\S]*?grid-template-columns:\s*76px minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.portal-sidebar\.collapsed \.sidebar-link span:not\(\.nav-symbol\)/);
});

test("document processing workspace uses the approved bottom-list review layout", () => {
  const workspace = source("portal-workspace-view.tsx");
  const styles = source("styles.css");

  assert.match(workspace, /className="document-review-toolbar"/);
  assert.match(workspace, /className="document-agent-row"/);
  assert.match(workspace, /className="document-agent-strip"/);
  assert.match(workspace, /className="document-review-main"/);
  assert.match(workspace, /className="bottom-document-queue"/);
  assert.match(workspace, /Belge listesi/);
  assert.match(workspace, /Teknik ge/);
  assert.match(workspace, /<DocumentPreview[\s\S]*sourceTarget=\{sourceTarget\}[\s\S]*<JournalPanel/);
  assert.match(workspace, /onFocusSource=\{focusDocumentSource\}/);
  assert.match(workspace, /<section className="document-review-main">[\s\S]*<\/section>\s*<details className="debug-accordion">/);
  assert.doesNotMatch(workspace, /<aside className="document-queue-panel"/);
  assert.match(styles, /\.accountant-workspace\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.document-agent-row\s*\{/);
  assert.match(styles, /\.document-agent-strip\s*\{/);
  assert.match(styles, /\.document-review-main\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1\.05fr\) minmax\(0,\s*0\.95fr\);/);
  assert.match(styles, /\.bottom-document-queue\s*\{/);
});

test("invoice review first viewport removes duplicate context and keeps invoice navigation compact", () => {
  const portalApp = source("portal-app.tsx");
  const shell = source("portal-shell-components.tsx");
  const workspace = source("portal-workspace-view.tsx");
  const workflow = source("features/documents/use-document-workflow.ts");
  const styles = source("styles.css");

  assert.doesNotMatch(portalApp, /<DocumentContextBar/);
  assert.doesNotMatch(portalApp, /title=\{mode === "client"[\s\S]*?"Belge İşleme"/);
  assert.match(portalApp, /"Fatura İşleme"/);
  assert.match(shell, /label: "Faturalar"/);
  assert.doesNotMatch(shell, /label: "Belgeler"/);
  assert.match(workflow, /useState<DocumentSegment>\("purchase_invoices"\)/);
  assert.match(workspace, /\{ id: "purchase_invoices", label: "Alış" \}/);
  assert.match(workspace, /\{ id: "sales_invoices", label: "Satış" \}/);
  assert.doesNotMatch(workspace, /\{ id: "invoices", label: "Faturalar" \}/);
  assert.doesNotMatch(workspace, /\{ id: "bank_statements", label: "Ekstreler" \}/);
  assert.doesNotMatch(workspace, /\{ id: "other_documents", label: "Diğer" \}/);
  assert.doesNotMatch(workspace, /<span>Kontrol filtresi<\/span>/);
  assert.match(workspace, /İş kuyruğu/);
  assert.match(workspace, /Onaylanabilir/);
  assert.match(styles, /\.document-review-toolbar \.queue-segment-tabs button\s*\{[\s\S]*?min-height:\s*54px;/);
  assert.match(styles, /\.document-review-toolbar \.queue-segment-tabs button\.active\s*\{[\s\S]*?box-shadow:\s*inset 0 -3px 0 var\(--accent\);/);
});

test("document review toolbar and main workspace can wrap before desktop overflow", () => {
  const styles = source("styles.css");

  assert.match(styles, /\.document-review-toolbar\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.document-review-toolbar\s*\{[\s\S]*?align-items:\s*stretch;/);
  assert.match(styles, /\.document-review-toolbar-fields\s*\{[\s\S]*?display:\s*grid;/);
  assert.match(styles, /\.document-review-main\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1\.05fr\) minmax\(0,\s*0\.95fr\);/);
  assert.match(styles, /@media \(max-width:\s*1320px\)[\s\S]*?\.document-review-main\s*\{[\s\S]*?grid-template-columns:\s*1fr;/);
});

test("dashboard review summary keeps three compact counts at every working width", () => {
  const styles = source("styles.css");

  assert.match(
    styles,
    /\.office-dashboard\.dashboard-review-summary\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(styles, /@media \(max-width: 520px\)[\s\S]*?\.office-dashboard\.dashboard-review-summary \.metric\s*\{/);
});

test("tablet dashboard stacks charts before they can overflow the page", () => {
  const styles = source("styles.css");

  assert.match(
    styles,
    /@media \(max-width: 1080px\)[\s\S]*?\.dashboard-visual-grid\s*\{[\s\S]*?grid-template-columns:\s*1fr;/,
  );
});

test("global controls have focus-visible and minimum target contracts", () => {
  const styles = source("styles.css");

  assert.match(styles, /:where\(button,\s*a,\s*input,\s*select,\s*textarea,\s*summary\):focus-visible/);
  assert.match(styles, /min-height:\s*44px/);
  assert.match(styles, /\.topbar-popover/);
});

test("accountant dashboard keeps agents and secondary telemetry off the daily review surface", () => {
  const dashboard = source("portal-dashboard-view.tsx");
  const styles = source("styles.css");

  assert.match(dashboard, /dashboard-review-layout/);
  assert.match(dashboard, /review-work-list/);
  assert.match(dashboard, /office-summary/);
  assert.doesNotMatch(dashboard, /agent-workbench-panel/);
  assert.doesNotMatch(dashboard, /learning-prep-panel/);
  assert.doesNotMatch(dashboard, /ChartBars/);
  assert.match(styles, /\.dashboard-review-layout\s*\{/);
  assert.match(styles, /\.review-work-row\s*\{/);
  assert.match(styles, /\.office-summary\s*\{/);
});

test("document cockpit keeps corrections inline with dirty-state reset and no primary Duzelt action", () => {
  const reviewPanels = source("portal-review-panels.tsx");
  const workspace = source("portal-workspace-view.tsx");

  assert.match(reviewPanels, /Değişiklik var/);
  assert.match(reviewPanels, /İlk taslağa dön/);
  assert.match(reviewPanels, /Benzerleri için öneri olarak kullan/);
  assert.doesNotMatch(reviewPanels, /Düzelt ve onayla/);
  assert.doesNotMatch(workspace, />Düzelt<\/button>/);
});

test("agent training page is read-only and uses learning evidence language", () => {
  const agentsView = source("portal-agents-view.tsx");
  const styles = source("styles.css");

  assert.match(agentsView, /agent-training-page/);
  assert.match(agentsView, /Eğitim notları/);
  assert.match(agentsView, /Kural adayları/);
  assert.match(agentsView, /Kontrollü otomasyon adayları/);
  assert.doesNotMatch(agentsView, /Yeni ajan oluştur/);
  assert.match(styles, /\.agent-training-page\s*\{/);
  assert.match(styles, /\.agent-training-grid\s*\{/);
});

test("dashboard distinguishes workspace loading from a real empty work queue", () => {
  const dashboard = source("portal-dashboard-view.tsx");
  const portalApp = source("portal-app.tsx");

  assert.match(dashboard, /isLoading/);
  assert.match(dashboard, /Çalışma alanı yükleniyor/);
  assert.match(dashboard, /isLoading \? "…" : dashboardMetrics/);
  assert.match(portalApp, /isLoading=\{source\.status === "loading"\}/);
});

test("document cockpit exposes accountant learning preview modal controls", () => {
  const reviewPanels = source("portal-review-panels.tsx");

  assert.match(reviewPanels, /learning-rule-modal/);
  assert.match(reviewPanels, /onPreviewReviewRule/);
  assert.match(reviewPanels, /Kural olarak kaydet/);
  assert.match(reviewPanels, /Benzerlerde oner/);
});

test("accountant dashboard promotes review work and keeps agent metrics off the home surface", () => {
  const dashboard = source("portal-dashboard-view.tsx");
  const styles = source("styles.css");

  assert.match(dashboard, /dashboard-review-summary/);
  assert.match(dashboard, /Bugün bakılacak belgeler/);
  assert.match(dashboard, /onOpenDocument/);
  assert.match(dashboard, />İncele<\/button>/);
  assert.match(dashboard, /office-summary/);
  assert.doesNotMatch(dashboard, /agent-workbench-panel/);
  assert.doesNotMatch(dashboard, /className="duration-metrics"/);
  assert.match(styles, /\.dashboard-review-layout\s*\{/);
  assert.match(styles, /\.review-work-list,/);
  assert.match(styles, /\.office-summary \{/);
});
