// File: frontend/app/portal-formatters.test.cjs
// Summary: Verifies shared accountant-facing date and timestamp formatting without changing canonical backend values.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadFormatters() {
  const source = readFileSync(join(__dirname, "portal-formatters.ts"), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} };
  const localRequire = (id) => {
    if (id === "./upload-intake") return { normalizeIntakeCategory: (value) => value };
    if (id === "./portal-normalization") return { safeText: (value) => String(value ?? "").trim() };
    throw new Error(`Unexpected dependency: ${id}`);
  };
  new Function("require", "module", "exports", output)(localRequire, module, module.exports);
  return module.exports;
}

const { formatPortalDate, formatPortalDateTime } = loadFormatters();

test("portal date formatter uses day-first accountant presentation", () => {
  assert.equal(formatPortalDate("2026-09-04"), "04.09.2026");
  assert.equal(formatPortalDate("31/05/2026"), "31.05.2026");
  assert.equal(formatPortalDate("31.02.2026"), "31.02.2026");
});

test("portal timestamp formatter uses Istanbul time and hides seconds", () => {
  assert.equal(formatPortalDateTime("2026-09-04T23:00:03+00:00"), "05.09.2026 · 02:00");
  assert.equal(formatPortalDateTime("06- 05- 2026 11:12:38"), "06.05.2026 · 11:12");
});

test("portal formatters preserve unknown values instead of guessing", () => {
  assert.equal(formatPortalDate("04/05/26"), "04/05/26");
  assert.equal(formatPortalDateTime("2026-09-04T12:00:00"), "2026-09-04T12:00:00");
  assert.equal(formatPortalDateTime(""), "-");
});