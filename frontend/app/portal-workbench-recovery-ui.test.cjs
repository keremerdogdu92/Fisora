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
  assert.match(source, /counterpartyResolutionLineIndexes/);
  assert.match(source, /Cari hesap seçilmedi/);
  assert.match(source, /Yeni cari hesap kodu/);
  assert.match(source, /Oluştur ve fişe bağla/);
  assert.match(source, /setCounterpartyTaxId/);
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

test("journal separates final-accountant description from source evidence and keeps account names readable", () => {
  const source = panels();
  const css = nextStyles();
  assert.match(source, /aria-label="Fi\u015f sat\u0131r\u0131 a\u00e7\u0131klamas\u0131"/);
  assert.match(source, /title="Fi\u015f sat\u0131r\u0131 a\u00e7\u0131klamas\u0131"/);
  assert.doesNotMatch(source, /aria-label="Fatura sat\u0131r\u0131 a\u00e7\u0131klamas\u0131"/);
  assert.match(css, /\.portal-next-theme \.journal-account-name \{[^}]*display:\s*-webkit-box;[^}]*-webkit-line-clamp:\s*2;[^}]*white-space:\s*normal;/s);
  assert.doesNotMatch(css, /\.portal-next-theme \.journal-account-name \{[^}]*text-overflow:\s*ellipsis;/s);
});

test("narrow desktop journal moves debit and credit to a second visual tier", () => {
  const source = panels();
  const css = nextStyles();
  assert.match(source, /journal-responsive-amount-label/);
  assert.match(source, /aria-label="Bor/);
  assert.match(source, /aria-label="Alacak"/);
  assert.match(css, /@media \(min-width: 861px\) and \(max-width: 1092px\)/);
  assert.match(css, /journal-ledger tbody tr \{[^}]*display:\s*grid;[^}]*grid-template-columns:/s);
  assert.match(css, /journal-ledger tbody td:nth-child\(2\) \{ grid-column: 2; grid-row: 2; \}/);
  assert.match(css, /journal-ledger tbody td:nth-child\(3\) \{ grid-column: 3; grid-row: 2; \}/);
});
