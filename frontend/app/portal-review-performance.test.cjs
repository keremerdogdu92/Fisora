const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

test("manual journal row identity does not depend on the editable account code", () => {
  const reviewPanels = readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");

  assert.doesNotMatch(
    reviewPanels,
    /<tr key=\{`\$\{line\.account_code\}-\$\{index\}`\}>/,
    "changing the account code must not remount the row while the user is typing",
  );
});

test("unsaved journal corrections reset when the selected document changes", () => {
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const reviewIndex = readFileSync(join(__dirname, "features", "review", "index.ts"), "utf8");

  assert.match(portalApp, /import \{ emptyCorrectionDraft, journalDraftLinesForDocument, useReviewCommands \} from "\.\/features\/review";/);
  assert.match(reviewIndex, /emptyCorrectionDraft/);
  assert.match(
    portalApp,
    /useEffect\(\(\) => \{\s*setCorrectionDraft\(emptyCorrectionDraft\(\)\);\s*\}, \[selectedDocument\?\.id\]\);/,
    "manual journal draft state must be scoped to the active document",
  );
});

test("approve and next sends approve_with_changes only when the current draft is dirty", () => {
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const reviewCommands = readFileSync(join(__dirname, "features", "review", "use-review-commands.ts"), "utf8");

  assert.match(portalApp, /const hasUnsavedReviewChanges = useMemo/);
  assert.match(reviewCommands, /hasUnsavedReviewChanges:\s*boolean/);
  assert.match(reviewCommands, /const approveAction = hasUnsavedReviewChanges \? "approve_with_changes" : "approve";/);
  assert.match(reviewCommands, /saveDecision\(approveAction\)/);
  assert.match(reviewCommands, /saveStatementLineDecision\(approveAction\)/);
});
