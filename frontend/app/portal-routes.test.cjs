const assert = require("node:assert/strict");
const { existsSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const {
  normalizeSessionForPortalConfig,
  portalConfigForPath,
  portalConfigForRouteKey,
} = require("./portal-routes");

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
    visibleModes: ["accountant", "exports", "operations"],
  });
});

test("accountant subpaths stay under the accountant link family", () => {
  assert.equal(portalConfigForPath("/portal/cikti").initialMode, "exports");
  assert.equal(portalConfigForPath("/portal/operasyon").initialMode, "operations");
  assert.deepEqual(portalConfigForRouteKey("cikti").visibleModes, ["accountant", "exports", "operations"]);
  assert.deepEqual(portalConfigForRouteKey("operasyon").visibleModes, ["accountant", "exports", "operations"]);
});

test("website entry paths have Next app route files", () => {
  assert.equal(existsSync(join(__dirname, "portal", "mukellef", "page.tsx")), true);
  assert.equal(existsSync(join(__dirname, "portal", "musavir", "page.tsx")), true);
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
