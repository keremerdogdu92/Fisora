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

  assert.match(dashboard, /Users/);
  assert.match(dashboard, /Upload/);
  assert.match(dashboard, /UserX/);
  assert.match(dashboard, /ClipboardCheck/);
  assert.match(dashboard, /PackageCheck/);
  assert.match(dashboard, /MessageSquareWarning/);
  assert.match(dashboard, /<Metric icon=\{Users\} label="Mükellef"/);
  assert.match(shared, /icon\?: LucideIcon/);
  assert.match(shared, /aria-hidden="true"/);
  assert.match(shared, /className="metric-icon"/);
});

test("sidebar uses semantic icons instead of two-letter navigation badges", () => {
  const shell = source("portal-shell-components.tsx");

  assert.match(shell, /LayoutDashboard/);
  assert.match(shell, /Landmark/);
  assert.match(shell, /BookOpen/);
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
  assert.match(portalApp, /onToggleCollapse=\{\(\) => setSidebarCollapsed\(\(current\) => !current\)\}/);
  assert.match(shell, /aria-label=\{collapsed \? "Menüyü genişlet" : "Menüyü daralt"\}/);
  assert.match(shell, /className=\{collapsed \? "portal-sidebar collapsed" : "portal-sidebar"\}/);
  assert.match(styles, /\.portal-shell\.sidebar-collapsed\s*\{[\s\S]*?grid-template-columns:\s*76px minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.portal-sidebar\.collapsed \.sidebar-link span:not\(\.nav-symbol\)/);
});

test("document processing workspace uses the approved bottom-list review layout", () => {
  const workspace = source("portal-workspace-view.tsx");
  const styles = source("styles.css");

  assert.match(workspace, /className="document-review-toolbar"/);
  assert.match(workspace, /className="document-review-main"/);
  assert.match(workspace, /className="bottom-document-queue"/);
  assert.match(workspace, /Belge listesi/);
  assert.match(workspace, /<DocumentPreview document=\{selectedDocument\} session=\{session\} \/>[\s\S]*<JournalPanel/);
  assert.doesNotMatch(workspace, /<aside className="document-queue-panel"/);
  assert.match(styles, /\.accountant-workspace\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.document-review-main\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1\.05fr\) minmax\(0,\s*0\.95fr\);/);
  assert.match(styles, /\.bottom-document-queue\s*\{/);
});

test("document review toolbar and main workspace can wrap before desktop overflow", () => {
  const styles = source("styles.css");

  assert.match(styles, /\.document-review-toolbar\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.document-review-toolbar\s*\{[\s\S]*?align-items:\s*stretch;/);
  assert.match(styles, /\.document-review-toolbar-fields\s*\{[\s\S]*?display:\s*grid;/);
  assert.match(styles, /\.document-review-main\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1\.05fr\) minmax\(0,\s*0\.95fr\);/);
  assert.match(styles, /@media \(max-width:\s*1320px\)[\s\S]*?\.document-review-main\s*\{[\s\S]*?grid-template-columns:\s*1fr;/);
});

test("dashboard metric grid follows the approved desktop tablet and mobile columns", () => {
  const styles = source("styles.css");

  assert.match(
    styles,
    /\.office-dashboard\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*repeat\(6,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(
    styles,
    /@media \(max-width: 1279px\)[\s\S]*?\.office-dashboard\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(
    styles,
    /@media \(max-width: 759px\)[\s\S]*?\.office-dashboard\s*\{[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);/,
  );
  assert.match(styles, /\.metric\.with-icon/);
  assert.match(styles, /\.nav-symbol svg/);
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
