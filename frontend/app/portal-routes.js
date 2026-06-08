const ACCOUNTANT_MODES = ["accountant", "exports", "operations"];

const PORTAL_NAV_ITEMS = [
  { mode: "client", label: "Mükellef portalı", href: "/portal/mukellef" },
  { mode: "accountant", label: "Müşavir masası", href: "/portal/musavir" },
  { mode: "exports", label: "Çıktı listesi", href: "/portal/cikti" },
  { mode: "operations", label: "Operasyon", href: "/portal/operasyon" },
];

const PORTAL_ROUTE_CONFIGS = {
  home: {
    routeKey: "home",
    initialMode: "accountant",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    visibleModes: ["client", ...ACCOUNTANT_MODES],
  },
  mukellef: {
    routeKey: "mukellef",
    initialMode: "client",
    defaultUserId: "mukellef-user",
    defaultRole: "client_user",
    lockedRole: "client_user",
    visibleModes: ["client"],
  },
  musavir: {
    routeKey: "musavir",
    initialMode: "accountant",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
  cikti: {
    routeKey: "cikti",
    initialMode: "exports",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
  operasyon: {
    routeKey: "operasyon",
    initialMode: "operations",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
};

function portalConfigForRouteKey(routeKey) {
  return PORTAL_ROUTE_CONFIGS[routeKey] || PORTAL_ROUTE_CONFIGS.home;
}

function portalConfigForPath(pathname) {
  const path = String(pathname || "").replace(/\/+$/, "") || "/";
  if (path === "/portal/mukellef") return PORTAL_ROUTE_CONFIGS.mukellef;
  if (path === "/portal/musavir") return PORTAL_ROUTE_CONFIGS.musavir;
  if (path === "/portal/cikti") return PORTAL_ROUTE_CONFIGS.cikti;
  if (path === "/portal/operasyon") return PORTAL_ROUTE_CONFIGS.operasyon;
  return PORTAL_ROUTE_CONFIGS.home;
}

function normalizeSessionForPortalConfig(session, portalConfig) {
  if (!session || !portalConfig?.lockedRole) return session || null;
  return session.role === portalConfig.lockedRole ? session : null;
}

module.exports = {
  ACCOUNTANT_MODES,
  PORTAL_NAV_ITEMS,
  PORTAL_ROUTE_CONFIGS,
  normalizeSessionForPortalConfig,
  portalConfigForPath,
  portalConfigForRouteKey,
};
