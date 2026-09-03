// File: frontend/app/e2e-gate.test.cjs
// Summary: Locks production frontend integration boundaries, including authenticated query hydration and real-data browser gate availability.
const assert = require("node:assert/strict");
const { existsSync, readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const FRONTEND_ROOT = join(__dirname, "..");

test("frontend exposes a Playwright real-data pilot gate", () => {
  const packageJson = JSON.parse(readFileSync(join(FRONTEND_ROOT, "package.json"), "utf8"));
  const e2eRunner = readFileSync(join(FRONTEND_ROOT, "scripts", "run-playwright-e2e.cjs"), "utf8");

  assert.equal(typeof packageJson.scripts["test:e2e"], "string");
  assert.match(packageJson.scripts["test:e2e"], /run-playwright-e2e\.cjs/);
  assert.match(e2eRunner, /playwrightCli, "test"/);
  assert.equal(existsSync(join(FRONTEND_ROOT, "playwright.config.ts")), true);
  assert.equal(existsSync(join(FRONTEND_ROOT, "e2e", "real-data-pilot.spec.ts")), true);
});

test("portal shell wires the first TanStack Query provider boundary", () => {
  const packageJson = JSON.parse(readFileSync(join(FRONTEND_ROOT, "package.json"), "utf8"));
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const workspaceQueries = readFileSync(join(__dirname, "features", "workspace", "queries.ts"), "utf8");

  assert.equal(typeof packageJson.dependencies["@tanstack/react-query"], "string");
  assert.equal(existsSync(join(__dirname, "features", "workspace", "query-provider.tsx")), true);
  assert.match(portalApp, /PilotQueryProvider/);
  assert.match(portalApp, /usePilotReadinessQuery/);
  assert.match(workspaceQueries, /useQuery/);
  assert.match(workspaceQueries, /workspaceQueryKeys/);
  assert.match(workspaceQueries, /useAiCapacityQuery[\s\S]*enabled: Boolean\(session\)/);
});

test("portal feature and shared boundaries are explicit", () => {
  [
    "features/workspace/query-provider.tsx",
    "features/workspace/index.ts",
    "features/session/index.ts",
    "features/documents/index.ts",
    "features/review/index.ts",
    "features/export/index.ts",
    "features/clients/index.ts",
    "shared/components/index.ts",
  ].forEach((path) => {
    assert.equal(existsSync(join(__dirname, path)), true, `${path} should exist`);
  });
});

test("portal app remains an orchestrator instead of a feature implementation file", () => {
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");

  assert.ok(
    portalApp.split(/\r?\n/).length <= 620,
    "portal-app.tsx should keep shrinking as feature modules take ownership",
  );
});

test("review and export command handlers live behind feature hooks", () => {
  const portalApp = readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const reviewCommands = readFileSync(join(__dirname, "features", "review", "use-review-commands.ts"), "utf8");
  const exportCommands = readFileSync(join(__dirname, "features", "export", "use-export-commands.ts"), "utf8");

  assert.match(portalApp, /useReviewCommands/);
  assert.match(portalApp, /useExportCommands/);
  assert.match(reviewCommands, /requestStatementAiForSelectedDocumentAction/);
  assert.match(reviewCommands, /saveStatementLineDecisionAction/);
  assert.match(exportCommands, /addSelectedClientToBasketAction/);
  assert.match(exportCommands, /markBasketPackagedAction/);
});
