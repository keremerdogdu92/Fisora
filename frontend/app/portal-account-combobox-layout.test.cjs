const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const appDir = __dirname;

test("account combobox popup is positioned outside the ledger table flow", () => {
  const source = readFileSync(join(appDir, "portal-review-panels.tsx"), "utf8");
  const styles = readFileSync(join(appDir, "styles.css"), "utf8");

  assert.match(source, /inputRef\s*=\s*useRef/);
  assert.match(source, /updatePopupPosition/);
  assert.match(source, /--account-options-left/);
  assert.match(source, /--account-options-top/);
  assert.match(styles, /\.account-code-options\s*{[^}]*position:\s*fixed;/s);
  assert.match(styles, /\.account-code-options\s*{[^}]*width:\s*min\(520px,\s*calc\(100vw - 32px\)\);/s);
});
