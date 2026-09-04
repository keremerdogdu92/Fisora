const ACCOUNTANT_MODES = ["accountant", "agents", "documents", "clients", "uploads", "exports", "operations", "settings"];

const LANDING_ROLE_ENTRIES = [
  {
    role: "accountant",
    label: "Müşavir girişi",
    href: "/portal/musavir",
    defaultUserId: "mali-musavir",
    cta: "Çalışma alanına gir",
    description: "Belge kontrolü, müşavir kararları ve çıktı listesi.",
  },
  {
    role: "client_user",
    label: "Mükellef girişi",
    href: "/portal/mukellef",
    defaultUserId: "mukellef-user",
    cta: "Belge yükleme ekranına gir",
    description: "Ay bazlı belge yükleme, önizleme ve talep takibi.",
  },
];

const PORTAL_NAV_ITEMS = [
  { mode: "client", label: "Mükellef portalı", href: "/portal/mukellef" },
  { mode: "accountant", label: "Anasayfa", href: "/portal/musavir" },
  { mode: "agents", label: "AI ajanları", href: "/portal/ajanlar" },
  { mode: "documents", label: "Belge işleme", href: "/portal/belgeler" },
  { mode: "clients", label: "Mükellefler", href: "/portal/mukellefler" },
  { mode: "exports", label: "Çıktı listesi", href: "/portal/cikti" },
  { mode: "settings", label: "Ayarlar", href: "/portal/ayarlar" },
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
  belgeler: {
    routeKey: "belgeler",
    initialMode: "documents",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
  ajanlar: {
    routeKey: "ajanlar",
    initialMode: "agents",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
  mukellefler: {
    routeKey: "mukellefler",
    initialMode: "clients",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
  "bilgi-havuzu": {
    routeKey: "bilgi-havuzu",
    initialMode: "agents",
    defaultUserId: "mali-musavir",
    defaultRole: "accountant",
    lockedRole: "accountant",
    visibleModes: ACCOUNTANT_MODES,
  },
  ayarlar: {
    routeKey: "ayarlar",
    initialMode: "settings",
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

function portalEntryForRole(role) {
  return LANDING_ROLE_ENTRIES.find((entry) => entry.role === role) || LANDING_ROLE_ENTRIES[0];
}

function portalConfigForPath(pathname) {
  const path = String(pathname || "").replace(/\/+$/, "") || "/";
  if (path === "/portal/mukellef") return PORTAL_ROUTE_CONFIGS.mukellef;
  if (path === "/portal/musavir") return PORTAL_ROUTE_CONFIGS.musavir;
  if (path === "/portal/ajanlar") return PORTAL_ROUTE_CONFIGS.ajanlar;
  if (path === "/portal/belgeler") return PORTAL_ROUTE_CONFIGS.belgeler;
  if (path === "/portal/mukellefler") return PORTAL_ROUTE_CONFIGS.mukellefler;
  if (path === "/portal/bilgi-havuzu") return PORTAL_ROUTE_CONFIGS["bilgi-havuzu"];
  if (path === "/portal/ayarlar") return PORTAL_ROUTE_CONFIGS.ayarlar;
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
  LANDING_ROLE_ENTRIES,
  PORTAL_NAV_ITEMS,
  PORTAL_ROUTE_CONFIGS,
  normalizeSessionForPortalConfig,
  portalEntryForRole,
  portalConfigForPath,
  portalConfigForRouteKey,
};
