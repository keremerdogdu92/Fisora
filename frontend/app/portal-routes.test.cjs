// File: frontend/app/portal-routes.test.cjs
// Summary: Verifies portal routing and client-management source contracts.
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
  const rootPage = require("node:fs").readFileSync(join(__dirname, "page.tsx"), "utf8");

  assert.deepEqual(
    LANDING_ROLE_ENTRIES.map((entry) => ({
      role: entry.role,
      label: entry.label,
      href: entry.href,
      defaultUserId: entry.defaultUserId,
    })),
    [
      { role: "accountant", label: "Müşavir girişi", href: "/portal-next", defaultUserId: "mali-musavir" },
      { role: "client_user", label: "Mükellef girişi", href: "/portal/mukellef", defaultUserId: "mukellef-user" },
    ],
  );
  assert.equal(portalEntryForRole("accountant").href, "/portal-next");
  assert.equal(portalEntryForRole("client_user").href, "/portal/mukellef");
  assert.doesNotMatch(rootPage, /aria-label="Portal girişleri"/);
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
    visibleModes: ["accountant", "agents", "documents", "clients", "uploads", "exports", "operations", "settings"],
  });
});

test("accountant subpaths stay under the accountant link family", () => {
  assert.equal(portalConfigForPath("/portal/ajanlar").initialMode, "agents");
  assert.equal(portalConfigForPath("/portal/belgeler").initialMode, "documents");
  assert.equal(portalConfigForPath("/portal/mukellefler").initialMode, "clients");
  assert.equal(portalConfigForPath("/portal/bilgi-havuzu").initialMode, "agents");
  assert.equal(portalConfigForPath("/portal/ayarlar").initialMode, "settings");
  assert.equal(portalConfigForPath("/portal/cikti").initialMode, "exports");
  assert.equal(portalConfigForPath("/portal/operasyon").initialMode, "operations");
  assert.deepEqual(portalConfigForRouteKey("ajanlar").visibleModes, ["accountant", "agents", "documents", "clients", "uploads", "exports", "operations", "settings"]);
  assert.deepEqual(portalConfigForRouteKey("belgeler").visibleModes, ["accountant", "agents", "documents", "clients", "uploads", "exports", "operations", "settings"]);
  assert.deepEqual(portalConfigForRouteKey("bilgi-havuzu").visibleModes, ["accountant", "agents", "documents", "clients", "uploads", "exports", "operations", "settings"]);
  assert.deepEqual(portalConfigForRouteKey("ayarlar").visibleModes, ["accountant", "agents", "documents", "clients", "uploads", "exports", "operations", "settings"]);
});

test("research knowledge is an AI agents subview, not a sidebar destination", () => {
  const {
    ACCOUNTANT_MODES,
    PORTAL_NAV_ITEMS,
  } = require("./portal-routes");

  assert.equal(ACCOUNTANT_MODES.includes("agents"), true);
  assert.equal(ACCOUNTANT_MODES.includes("research"), false);
  assert.deepEqual(
    PORTAL_NAV_ITEMS.find((item) => item.mode === "agents"),
    { mode: "agents", label: "AI ajanları", href: "/portal/ajanlar" },
  );
  assert.equal(PORTAL_NAV_ITEMS.some((item) => item.mode === "research"), false);
});

test("research view reads legacy labels only from non-authoritative display", () => {
  const researchView = require("node:fs").readFileSync(join(__dirname, "portal-research-view.tsx"), "utf8");

  assert.match(researchView, /non_authoritative_display/);
  assert.doesNotMatch(researchView, /profile\.product_category/);
  assert.doesNotMatch(researchView, /profile\.account_treatment/);
  assert.doesNotMatch(researchView, /selectedProfile\.account_treatment/);
  assert.match(researchView, /profile\.profile_id/);
  assert.match(researchView, /profile_id: selectedProfile\.profile_id/);
  assert.match(researchView, /expected_revision: selectedProfile\.revision/);
  assert.doesNotMatch(researchView, /selectedProfile\?\.key === profile\.key/);
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
  assert.equal(existsSync(join(__dirname, "portal", "ajanlar", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "belgeler", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "mukellefler", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "bilgi-havuzu", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "ayarlar", "page.tsx")), true);
});

test("portal implementation is split into route view modules", () => {
  const portalApp = require("node:fs").readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
  const workspaceView = require("node:fs").readFileSync(join(__dirname, "portal-workspace-view.tsx"), "utf8");

  assert.match(portalApp, /portal-dashboard-view/);
  assert.match(portalApp, /portal-agents-view/);
  assert.match(portalApp, /portal-client-view/);
  assert.match(portalApp, /portal-clients-view/);
  assert.match(portalApp, /portal-documents-view/);
  assert.match(portalApp, /portal-exports-view/);
  assert.doesNotMatch(portalApp, /portal-research-view/);
  assert.match(require("node:fs").readFileSync(join(__dirname, "portal-agents-view.tsx"), "utf8"), /portal-research-view/);
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
  assert.equal(existsSync(join(__dirname, "portal-agents-view.tsx")), true);
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

test("workspace marks visible invoice cancellation reasons as danger chips", () => {
  const workspaceView = require("node:fs").readFileSync(join(__dirname, "portal-workspace-view.tsx"), "utf8");
  const styles = require("node:fs").readFileSync(join(__dirname, "styles.css"), "utf8");

  assert.match(workspaceView, /cancelled_invoice_visible/);
  assert.match(workspaceView, /className=\{reason === "cancelled_invoice_visible" \? "danger" : undefined\}/);
  assert.match(styles, /\.review-reason-chips span\.danger/);
});

test("portal shell delegates session and review helpers to feature modules", () => {
  const portalApp = require("node:fs").readFileSync(join(__dirname, "portal-app.tsx"), "utf8");
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
  assert.match(portalApp, /mode === "agents"/);
  assert.match(portalApp, /aiCapacity=\{aiCapacityQuery\.data\}/);
  assert.match(portalApp, /capacityPending=\{aiCapacityQuery\.isPending\}/);
  assert.match(portalApp, /capacityError=\{aiCapacityQuery\.isError\}/);
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

test("client management defaults to the existing-client list and separates loading from empty", () => {
  const clientsView = require("node:fs").readFileSync(join(__dirname, "portal-clients-view.tsx"), "utf8");

  assert.match(clientsView, /type ClientManagementTab = "new-client" \| "client-list" \| "requests"/);
  assert.match(clientsView, /useState<ClientManagementTab>\("client-list"\)/);
  assert.match(clientsView, /isLoading/);
  assert.match(clientsView, /Mükellefler yükleniyor/);
  assert.match(clientsView, /Henüz mükellef yok/);
  assert.match(clientsView, /className="client-v13-list-surface"/);
  assert.match(clientsView, /className="client-v13-table-wrap panel"/);
  assert.match(clientsView, /clientSurface === "detail"/);
  assert.match(clientsView, /switchTab\("new-client"\)/);
  assert.match(clientsView, /switchTab\("requests"\)/);
  assert.doesNotMatch(clientsView, /className="client-management-tabs"/);
  assert.match(clientsView, /Vergi levhası bilgileri/);
  assert.match(clientsView, /className="tax-certificate-preview"/);
  assert.match(clientsView, /NACE araştırmasını onayla/);
});

test("initial workspace loading is not blocked by the separate readiness request", () => {
  const actions = require("node:fs").readFileSync(join(__dirname, "portal-workspace-actions.ts"), "utf8");
  const initialLoader = actions.slice(
    actions.indexOf("export async function loadInitialPilotData"),
    actions.indexOf("export { buildPilotReadinessView"),
  );

  assert.doesNotMatch(initialLoader, /await refreshBackendReadiness/);
  assert.match(initialLoader, /refreshBackendPilotData/);
});

test("export view exposes Zirve mapping adapter for field testing", () => {
  const exportsView = require("node:fs").readFileSync(join(__dirname, "portal-exports-view.tsx"), "utf8");
  const portalApp = require("node:fs").readFileSync(join(__dirname, "portal-app.tsx"), "utf8");

  assert.match(exportsView, /zirve_mapping_csv/);
  assert.match(exportsView, /Zirve mapping CSV/);
  assert.match(exportsView, /setExportType/);
  assert.match(portalApp, /const \[exportType, setExportType\]/);
});

test("client management view separates Gemini tax certificate loading from NACE research", () => {
  const clientsView = require("node:fs").readFileSync(join(__dirname, "portal-clients-view.tsx"), "utf8");
  const clientActions = require("node:fs").readFileSync(join(__dirname, "portal-client-actions.ts"), "utf8");

  assert.match(clientsView, /taxCertificateParsePending/);
  assert.match(clientsView, /tax-certificate-progress/);
  assert.match(clientsView, /Gemini vergi levhasını analiz ediyor/);
  assert.match(clientsView, /Gemini belgeyi analiz ediyor; büyük veya taranmış dosyalarda işlem uzayabilir\./);
  assert.match(clientsView, /NACE araştırması yapılıyor/);
  assert.match(clientActions, /setNewClientTaxCertificateParsePending\(true\)/);
  assert.match(clientActions, /setNewClientTaxCertificateStage\("Gemini vergi levhasını analiz ediyor"\)/);
  assert.match(clientActions, /setNewClientTaxCertificateStage\(parseStatus === "partial" \? "Eksik kritik alanlar var" : "Alanlar dolduruldu"\)/);
  assert.match(clientActions, /missing_critical_fields/);
});

test("journal distinguishes a missing new cari suggestion from an invalid ledger account", () => {
  const reviewPanels = require("node:fs").readFileSync(join(__dirname, "portal-review-panels.tsx"), "utf8");

  assert.match(reviewPanels, /Yeni cari hesabı önerisi/);
  assert.match(reviewPanels, /mevcut cariyi seçin veya müşavir onayıyla yeni cari açın/);
  assert.match(reviewPanels, /className="field-notice"/);
  assert.match(reviewPanels, /className="field-warning"/);
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
  const sessionGuard = require("node:fs").readFileSync(
    join(__dirname, "features", "session", "use-portal-session-guard.ts"),
    "utf8",
  );

  assert.doesNotMatch(portalApp, /useState<LocalSession \| null>\(\(\) =>/);
  assert.match(portalApp, /usePortalSessionGuard/);
  assert.match(sessionGuard, /fetchAuthSession/);
  assert.match(sessionGuard, /window\.location\.replace\("\/"\)/);
  assert.match(sessionGuard, /persistSession\(null\)/);
  assert.match(portalApp, /if \(!sessionHydrated\) return;/);
});
