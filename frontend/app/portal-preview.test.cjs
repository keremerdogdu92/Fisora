const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

test("document previews do not render mock paper markup when an original document exists", () => {
  const reviewPanels = readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");
  const clientView = readFileSync(join(__dirname, "portal-client-view.tsx"), "utf8");

  assert.doesNotMatch(reviewPanels, /className="paper-document"/);
  assert.doesNotMatch(clientView, /className="client-preview-paper"/);
  assert.match(reviewPanels, /DocumentPipelineTimeline/);
  assert.match(clientView, /DocumentPreview/);
});
