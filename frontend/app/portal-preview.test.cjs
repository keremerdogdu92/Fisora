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

test("document previews include portal auth headers when fetching original files", () => {
  const reviewPanels = readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");
  const clientView = readFileSync(join(__dirname, "portal-client-view.tsx"), "utf8");

  assert.match(reviewPanels, /previewAuthHeaders/);
  assert.match(reviewPanels, /X-Fisora-Session/);
  assert.match(reviewPanels, /X-Fisora-User-Id/);
  assert.match(clientView, /<DocumentPreview document=\{selectedDocument\} session=\{session\}/);
});

test("document previews use the configured backend api base path", () => {
  const reviewPanels = readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");

  assert.match(reviewPanels, /resolveApiBaseUrl/);
  assert.doesNotMatch(reviewPanels, /window\.location\.hostname\}:8000/);
});

test("journal totals keep dot-decimal amounts as decimals", () => {
  const reviewPanels = readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");

  assert.match(reviewPanels, /decimalSeparator/);
  assert.doesNotMatch(reviewPanels, /replace\(\/\\\\\\.\/g, ""\)/);
});
