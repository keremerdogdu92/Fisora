const assert = require("node:assert/strict");
const { existsSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const {
  LANDING_ROLE_ENTRIES,
  normalizeSessionForPortalConfig,
  portalEntryForRole,
  portalConfigForPath,
  portalConfigForRouteKey,
} = require("./portal-routes");

test("root page is the private pilot role gateway", () => {
  assert.deepEqual(
    LANDING_ROLE_ENTRIES.map((entry) => ({
      role: entry.role,
      label: entry.label,
      href: entry.href,
      defaultUserId: entry.defaultUserId,
    })),
    [
      { role: "accountant", label: "Müşavir girişi", href: "/portal/musavir", defaultUserId: "mali-musavir" },
      { role: "client_user", label: "Mükellef girişi", href: "/portal/mukellef", defaultUserId: "mukellef-user" },
    ],
  );
  assert.equal(portalEntryForRole("accountant").href, "/portal/musavir");
  assert.equal(portalEntryForRole("client_user").href, "/portal/mukellef");
});

test("same-domain portal paths open the correct private pilot screen", () => {
  assert.deepEqual(portalConfigForPath("/portal/mukellef"), {
    routeKey: "mukellef",
    initialMode: "client",
    defaultUserId: "mukellef-user",
    defaultRole: "client_user",
    lockedRole: "client_user",
    visibleModes: ["client"],
  });
  assert.deepEqual(portalConfigForPath("/portal/musavir"), {
    routeKey: "musavir",
    initialMode: "accountant",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ["accountant", "documents", "clients", "research", "exports", "operations", "settings"],
  });
});

test("accountant subpaths stay under the accountant link family", () => {
  assert.equal(portalConfigForPath("/portal/belgeler").initialMode, "documents");
  assert.equal(portalConfigForPath("/portal/mukellefler").initialMode, "clients");
  assert.equal(portalConfigForPath("/portal/bilgi-havuzu").initialMode, "research");
  assert.equal(portalConfigForPath("/portal/ayarlar").initialMode, "settings");
  assert.equal(portalConfigForPath("/portal/cikti").initialMode, "exports");
  assert.equal(portalConfigForPath("/portal/operasyon").initialMode, "operations");
  assert.deepEqual(portalConfigForRouteKey("belgeler").visibleModes, ["accountant", "documents", "clients", "research", "exports", "operations", "settings"]);
  assert.deepEqual(portalConfigForRouteKey("bilgi-havuzu").visibleModes, ["accountant", "documents", "clients", "research", "exports", "operations", "settings"]);
  assert.deepEqual(portalConfigForRouteKey("ayarlar").visibleModes, ["accountant", "documents", "clients", "research", "exports", "operations", "settings"]);
});

test("research knowledge hub is visible to accountant users", () => {
  const {
    ACCOUNTANT_MODES,
    PORTAL_NAV_ITEMS,
  } = require("./portal-routes");

  assert.equal(ACCOUNTANT_MODES.includes("research"), true);
  assert.deepEqual(
    PORTAL_NAV_ITEMS.find((item) => item.mode === "research"),
    { mode: "research", label: "Bilgi havuzu", href: "/portal/bilgi-havuzu" },
  );
});

test("website entry paths have Next app route files", () => {
  const rootPage = require("node:fs").readFileSync(join(__dirname, "page.tsx"), "utf8");
  assert.match(rootPage, /RoleGatewayLanding/);
  assert.doesNotMatch(rootPage, /return <FisoraPortalApp routeKey="home" \/>/);

  const musavirPage = require("node:fs").readFileSync(join(__dirname, "portal", "musavir", "page.tsx"), "utf8");
  assert.match(musavirPage, /portal-app/);
  assert.doesNotMatch(musavirPage, /\.\.\/\.\.\/page/);

  assert.equal(existsSync(join(__dirname, "portal", "mukellef", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "musavir", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "belgeler", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "mukellefler", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "bilgi-havuzu", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "ayarlar", "page.tsx")), true);
});

test("portal implementation is split into route view modules", () => {
  const portalApp = require("node:fs").readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const workspaceView = require("node:fs").readFileSync(join(__dirname, "portal-workspace-view.tsx"), "utf8");

  assert.match(portalApp, /portal-dashboard-view/);
  assert.match(portalApp, /portal-client-view/);
  assert.match(portalApp, /portal-clients-view/);
  assert.match(portalApp, /portal-documents-view/);
  assert.match(portalApp, /portal-exports-view/);
  assert.match(portalApp, /portal-research-view/);
  assert.match(portalApp, /portal-settings-view/);
  assert.match(portalApp, /portal-workspace-view/);
  assert.match(workspaceView, /portal-review-panels/);
  assert.doesNotMatch(portalApp, /function AccountantDashboard/);
  assert.doesNotMatch(portalApp, /function AccountantWorkspace/);
  assert.doesNotMatch(portalApp, /function ClientPortal/);
  assert.doesNotMatch(portalApp, /function ClientManagementView/);
  assert.doesNotMatch(portalApp, /function DocumentProcessingWorkspace/);
  assert.doesNotMatch(portalApp, /function DocumentPreview/);
  assert.doesNotMatch(portalApp, /function JournalPanel/);
  assert.doesNotMatch(portalApp, /function SettingsView/);
  assert.doesNotMatch(portalApp, /function SessionPanel/);
  assert.equal(existsSync(join(__dirname, "portal-types.ts")), true);
  assert.equal(existsSync(join(__dirname, "portal-dashboard-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-client-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-clients-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-documents-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-exports-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-research-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-review-panels.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-settings-view.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-shared.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal-workspace-view.tsx")), true);
});

test("portal shell delegates session and review helpers to feature modules", () => {
  const portalApp = require("node:fs").readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const lineCount = portalApp.split(/\r?\n/).length;

  assert.equal(existsSync(join(__dirname, "features", "session", "index.ts")), true);
  assert.equal(existsSync(join(__dirname, "features", "review", "index.ts")), true);
  assert.equal(existsSync(join(__dirname, "features", "clients", "index.ts")), true);
  assert.equal(existsSync(join(__dirname, "features", "documents", "index.ts")), true);
  assert.equal(existsSync(join(__dirname, "features", "export", "index.ts")), true);
  assert.equal(existsSync(join(__dirname, "features", "workspace", "index.ts")), true);
  assert.equal(existsSync(join(__dirname, "portal-formatters.ts")), true);
  assert.match(portalApp, /features\/session/);
  assert.match(portalApp, /features\/review/);
  assert.match(portalApp, /features\/clients/);
  assert.match(portalApp, /features\/documents/);
  assert.match(portalApp, /features\/export/);
  assert.match(portalApp, /features\/workspace/);
  assert.match(portalApp, /aiCapacity=\{aiCapacityQuery\.data\}/);
  assert.match(portalApp, /capacityPending=\{aiCapacityQuery\.isPending\}/);
  assert.match(portalApp, /capacityError=\{aiCapacityQuery\.isError\}/);
  assert.ok(lineCount <= 620, `portal-app.tsx should stay below 620 lines, found ${lineCount}`);
  assert.doesNotMatch(portalApp, /function readStoredSession/);
  assert.doesNotMatch(portalApp, /function persistSession/);
  assert.doesNotMatch(portalApp, /function applyStatementLineDecision/);
  assert.doesNotMatch(portalApp, /async function createNewClient/);
  assert.doesNotMatch(portalApp, /async function addLocalUploads/);
  assert.doesNotMatch(portalApp, /async function saveStatementLineDecision/);
  assert.doesNotMatch(portalApp, /function requestCancellation/);
  assert.doesNotMatch(portalApp, /function reviewActionLabel/);
  assert.doesNotMatch(portalApp, /const statementTypeLabels/);
});

test("client management view keeps new-client onboarding readable in tabs", () => {
  const clientsView = require("node:fs").readFileSync(join(__dirname, "portal-clients-view.tsx"), "utf8");

  assert.match(clientsView, /type ClientManagementTab = "new-client" \| "client-list" \| "requests"/);
  assert.match(clientsView, /useState<ClientManagementTab>\("new-client"\)/);
  assert.match(clientsView, /className="client-management-tabs"/);
  assert.match(clientsView, /Vergi levhası bilgileri/);
  assert.match(clientsView, /className="tax-certificate-preview"/);
  assert.match(clientsView, /NACE araştırmasını onayla/);
});

test("locked portal links ignore stale sessions from the other role", () => {
  const clientConfig = portalConfigForRouteKey("mukellef");
  const accountantConfig = portalConfigForRouteKey("musavir");
  const homeConfig = portalConfigForRouteKey("home");
  const accountantSession = { userId: "mali-musavir", role: "accountant" };
  const clientSession = { userId: "mukellef-user", role: "client_user" };

  assert.equal(normalizeSessionForPortalConfig(accountantSession, clientConfig), null);
  assert.equal(normalizeSessionForPortalConfig(clientSession, accountantConfig), null);
  assert.deepEqual(normalizeSessionForPortalConfig(accountantSession, accountantConfig), accountantSession);
  assert.deepEqual(normalizeSessionForPortalConfig(clientSession, homeConfig), clientSession);
});

test("portal shell hydrates stored sessions after the first client render", () => {
  const portalApp = require("node:fs").readFileSync(join(__dirname, "portal-app.tsx"), "utf8");

  assert.doesNotMatch(portalApp, /useState<LocalSession \| null>\(\(\) =>/);
  assert.match(portalApp, /const \[session, setSession\] = useState<LocalSession \| null>\(null\);/);
  assert.match(portalApp, /const \[sessionHydrated, setSessionHydrated\] = useState\(false\);/);
  assert.match(portalApp, /useEffect\(\(\) => \{\s*setSession\(normalizeSessionForPortalConfig\(readStoredSession\(\), portalConfig\)\);/);
  assert.match(portalApp, /if \(!sessionHydrated\) return;/);
});
