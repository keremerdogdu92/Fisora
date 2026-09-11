// Summary: Protects locale display formatting from mutating editable/canonical accounting amounts.
const test = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { formatReadOnlyAmount } = require("./portal-money-format.js");

test("formatReadOnlyAmount formats canonical decimal strings without numeric reparse", () => {
  assert.equal(formatReadOnlyAmount("12000.50"), "12.000,50");
  assert.equal(formatReadOnlyAmount("1034.33"), "1.034,33");
  assert.equal(formatReadOnlyAmount("238.69"), "238,69");
  assert.equal(formatReadOnlyAmount("245,50"), "245,50");
  assert.equal(formatReadOnlyAmount("12000"), "12.000,00");
  assert.equal(formatReadOnlyAmount("-12000.5"), "-12.000,50");
});

test("formatReadOnlyAmount refuses ambiguous or over-precise display values", () => {
  assert.equal(formatReadOnlyAmount("12.345,67"), "12.345,67");
  assert.equal(formatReadOnlyAmount("123.4567"), "123.4567");
  assert.equal(formatReadOnlyAmount("n/a"), "n/a");
  assert.equal(formatReadOnlyAmount(""), "-");
});

test("read-only amount formatting does not replace editable journal values", () => {
  const review = readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");
  const workspace = readFileSync(join(__dirname, "portal-workspace-view.tsx"), "utf8");
  assert.match(review, /value=\{line\.debit\}/);
  assert.match(review, /value=\{line\.credit\}/);
  assert.match(review, /formatReadOnlyAmount\(document\.amount\)/);
  assert.match(workspace, /formatReadOnlyAmount\(queueDocument\.amount\)/);
  assert.match(workspace, /formatReadOnlyAmount\(document\.amount\)/);
});
