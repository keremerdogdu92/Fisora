function safeText(value, fallback = "") {
  return value == null || value === "" ? fallback : String(value);
}

function safeList(value) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function realDataLabel(value) {
  if (value?.allowed) return "Kısıtlı canlı pilot hazır";
  return "Gerçek veri için kapalı";
}

function hostForUrl(pageUrl) {
  try {
    return new URL(pageUrl || "http://localhost").hostname.toLowerCase();
  } catch {
    return "";
  }
}

/**
 * @param {{ pageUrl?: string, explicitAllow?: boolean }} [options]
 */
function canUseLocalPilotFallback({ pageUrl = "", explicitAllow = false } = {}) {
  if (explicitAllow) return true;
  const host = hostForUrl(pageUrl);
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function offerLabel(value) {
  if (value === "accountant_reviewed_controlled_export") return "Müşavir onaylı kontrollü aktarım";
  return safeText(value, "Müşavir onaylı kontrollü aktarım");
}

function exportLabel(value) {
  if (value === "controlled_csv_and_manifest_candidate") return "Kontrollü çıktı paketi";
  return safeText(value, "Kontrollü çıktı paketi");
}

function zirveLabel(value) {
  if (value === "unverified_until_field_test") return "Format doğrulaması gerekli";
  if (value === "verified_in_zirve") return "Format doğrulandı";
  return safeText(value, "Format doğrulaması gerekli");
}

/**
 * @param {Record<string, any> | null | undefined} payload
 */
function buildPilotReadinessView(payload = null) {
  const readiness = payload && typeof payload === "object" ? payload : {};
  const commercial = readiness.commercial_readiness && typeof readiness.commercial_readiness === "object"
    ? readiness.commercial_readiness
    : {};
  const realDataPilot = readiness.real_data_pilot && typeof readiness.real_data_pilot === "object"
    ? readiness.real_data_pilot
    : {};
  const pilotSellable = Boolean(readiness.pilot_sellable);
  const productionReady = Boolean(readiness.production_ready);
  const status = pilotSellable ? "pilot_sellable" : "blocked";

  return {
    status,
    statusLabel: pilotSellable ? "Kontrollü kullanıma hazır" : "Kurulum kontrolü gerekli",
    productionLabel: productionReady ? "Canlı kullanım hazır" : "Canlı kullanım için kontrol gerekli",
    realDataLabel: realDataLabel(realDataPilot),
    realDataAccessLabel: safeText(realDataPilot.access_mode, "-"),
    realDataBlocking: safeList(realDataPilot.blocking),
    offerLabel: offerLabel(commercial.primary_offer),
    exportLabel: exportLabel(commercial.export_positioning),
    zirveLabel: zirveLabel(commercial.zirve_import_claim),
    authLabel: safeText(readiness.auth?.auth_mode, "-"),
    storeLabel: safeText(readiness.store_backend, "-"),
    aiLabel: safeText(readiness.ai_provider, "-"),
    blocking: safeList(readiness.pilot_blocking),
    warnings: safeList(readiness.warnings),
  };
}

module.exports = {
  buildPilotReadinessView,
  canUseLocalPilotFallback,
};
