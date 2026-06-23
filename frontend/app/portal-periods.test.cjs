const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

test("default upload period uses the last completed month", () => {
  const source = readFileSync(join(__dirname, "portal-periods.ts"), "utf8");
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const documentActions = readFileSync(join(__dirname, "portal-document-actions.ts"), "utf8");

  assert.match(source, /now\.getMonth\(\) - 1/);
  assert.match(source, /padStart\(2, "0"\)/);
  assert.match(portalApp, /setSelectedPeriod\(previousCompletedPeriod\(\)\)/);
  assert.match(documentActions, /TODO: Bulunulan ay yüklemelerini açma\./);
  assert.match(documentActions, /previousCompletedPeriod\(now\)/);
});

test("client portal keeps upload period fixed and list period selectable", () => {
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const clientView = readFileSync(join(__dirname, "portal-client-view.tsx"), "utf8");

  assert.match(portalApp, /clientPeriods/);
  assert.match(portalApp, /uploadPeriod=\{previousCompletedPeriod\(\)\}/);
  assert.doesNotMatch(clientView, /<h2>Mükellef portalı<\/h2>/);
  assert.match(clientView, /Yükleme dönemi/);
  assert.match(clientView, /Belge listesi/);
});
test("client portal renders document list and preview side by side", () => {
  const clientView = readFileSync(join(__dirname, "portal-client-view.tsx"), "utf8");

  assert.match(clientView, /client-document-workspace/);
  assert.match(clientView, /ClientDocumentDetailPanel/);
  assert.doesNotMatch(clientView, /documentTab === "list"/);
  assert.doesNotMatch(clientView, /setDocumentTab\("preview"\)/);
});

test("client portal keeps upload full width above the two-column document workspace", () => {
  const styles = readFileSync(join(__dirname, "styles.css"), "utf8");

  assert.match(styles, /\.client-portal\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\);/);
  assert.match(styles, /\.client-document-workspace\s*\{[\s\S]*?grid-template-columns:\s*minmax\(320px,\s*0\.82fr\)\s+minmax\(420px,\s*1\.18fr\);/);
  assert.match(styles, /\.upload-panel\s*\{[\s\S]*?width:\s*100%;/);
});
