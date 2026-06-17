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
