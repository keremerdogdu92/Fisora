// File: frontend/app/portal-workbench-recovery-ui.test.cjs
// Summary: Verifies source contracts for account navigation, counterparty recovery, interaction emphasis, and readable compact journal typography.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const appDir = __dirname;
const panels = () => readFileSync(join(appDir, "portal-review-panels.tsx"), "utf8");
const styles = () => readFileSync(join(appDir, "styles.css"), "utf8");
const nextStyles = () => readFileSync(join(appDir, "portal-next", "portal-next.css"), "utf8");

test("account combobox keeps keyboard and pointer on one active candidate", () => {
  const source = panels();
  assert.match(source, /nextSelectableAccountIndex/);
  assert.match(source, /optionRefs/);
  assert.match(source, /scrollIntoView\(\{\s*block:\s*"nearest"/s);
  assert.match(source, /onMouseEnter=\{\(\) => setActiveIndex\(index\)\}/);
});

test("unresolved counterparty blocks approval and opens an in-workbench recovery drawer", () => {
  const source = panels();
  assert.match(source, /draftAccountResolutionIssues/);
  assert.match(source, /createCounterpartyAccountToBackend/);
  assert.match(source, /counterparty-resolution-drawer/);
  assert.match(source, /Mevcut cariyi seç/);
  assert.match(source, /Yeni cari oluştur/);
  assert.match(source, /onRefreshWorkspace/);
});
test("active candidate and queue hover states are visibly stronger", () => {
  const baseCss = styles();
  const nextCss = nextStyles();
  assert.match(baseCss, /\.account-code-options button\.active,[\s\S]*\.account-code-options button:hover[\s\S]*background:/);
  assert.match(baseCss, /\.account-code-options button\.active,[\s\S]*box-shadow:/);
  assert.match(nextCss, /\.portal-next-queue-list button:hover/);
  assert.match(nextCss, /\.portal-next-queue-list button\.active[^{]*\{[^}]*box-shadow:/s);
  assert.match(nextCss, /\.counterparty-resolution-drawer/);
});

test("journal typography is stronger without abandoning compact rows", () => {
  const css = nextStyles();
  assert.match(css, /\.portal-next-theme \.journal-ledger input \{[^}]*font-size:\s*0\.79rem;[^}]*font-weight:\s*6\d\d;/s);
  assert.match(css, /\.portal-next-theme \.journal-account-name \{[^}]*font-size:\s*0\.78rem;[^}]*font-weight:\s*7\d\d;/s);
  assert.match(css, /\.portal-next-theme \.journal-ledger td:nth-child\(2\) input,[\s\S]*font-variant-numeric:\s*tabular-nums;/);
});
