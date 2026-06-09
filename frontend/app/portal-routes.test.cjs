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
    visibleModes: ["accountant", "documents", "clients", "exports", "settings"],
  });
});

test("accountant subpaths stay under the accountant link family", () => {
  assert.equal(portalConfigForPath("/portal/belgeler").initialMode, "documents");
  assert.equal(portalConfigForPath("/portal/mukellefler").initialMode, "clients");
  assert.equal(portalConfigForPath("/portal/ayarlar").initialMode, "settings");
  assert.equal(portalConfigForPath("/portal/cikti").initialMode, "exports");
  assert.equal(portalConfigForPath("/portal/operasyon").initialMode, "operations");
  assert.deepEqual(portalConfigForRouteKey("belgeler").visibleModes, ["accountant", "documents", "clients", "exports", "settings"]);
  assert.deepEqual(portalConfigForRouteKey("ayarlar").visibleModes, ["accountant", "documents", "clients", "exports", "settings"]);
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
  assert.equal(existsSync(join(__dirname, "portal", "ayarlar", "page.tsx")), true);
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
