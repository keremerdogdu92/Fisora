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
