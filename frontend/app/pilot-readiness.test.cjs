const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildPilotReadinessView,
  canUseLocalPilotFallback,
} = require("./pilot-readiness");

test("canUseLocalPilotFallback only allows localhost unless explicitly enabled", () => {
  assert.equal(canUseLocalPilotFallback({ pageUrl: "http://localhost:3000/portal/musavir" }), true);
  assert.equal(canUseLocalPilotFallback({ pageUrl: "http://127.0.0.1:3000/portal/musavir" }), true);
  assert.equal(canUseLocalPilotFallback({ pageUrl: "http://185.184.208.188/portal/musavir" }), false);
  assert.equal(
    canUseLocalPilotFallback({
      pageUrl: "http://185.184.208.188/portal/musavir",
      explicitAllow: true,
    }),
    true,
  );
});

test("buildPilotReadinessView presents controlled office readiness separately from full production", () => {
  const view = buildPilotReadinessView({
    pilot_sellable: true,
    production_ready: false,
    real_data_pilot: {
      allowed: false,
      status: "blocked",
      blocking: ["session_required_active"],
    },
    pilot_blocking: [],
    warnings: ["zirve_verified_adapter_missing"],
    auth: { auth_mode: "mock_header_required" },
    store_backend: "postgres",
    ai_provider: "groq",
    commercial_readiness: {
      primary_offer: "accountant_reviewed_controlled_export",
      export_positioning: "controlled_csv_and_manifest_candidate",
      zirve_import_claim: "unverified_until_field_test",
    },
  });

  assert.equal(view.status, "pilot_sellable");
  assert.equal(view.statusLabel, "Kontrollü kullanıma hazır");
  assert.equal(view.productionLabel, "Canlı kullanım için kontrol gerekli");
  assert.equal(view.exportLabel, "Kontrollü çıktı paketi");
  assert.equal(view.zirveLabel, "Format doğrulaması gerekli");
  assert.equal(view.realDataLabel, "Gerçek veri için kapalı");
  assert.deepEqual(view.realDataBlocking, ["session_required_active"]);
  assert.deepEqual(view.blocking, []);
  assert.deepEqual(view.warnings, ["zirve_verified_adapter_missing"]);
});

test("buildPilotReadinessView marks restricted live real-data pilot as ready", () => {
  const view = buildPilotReadinessView({
    pilot_sellable: true,
    production_ready: false,
    real_data_pilot: {
      allowed: true,
      status: "ready_for_restricted_live_pilot",
      access_mode: "restricted_network",
      blocking: [],
    },
    pilot_blocking: [],
    warnings: ["zirve_field_test_pending"],
    auth: { auth_mode: "session_required" },
    store_backend: "postgres",
    ai_provider: "groq",
  });

  assert.equal(view.realDataLabel, "Kısıtlı canlı pilot hazır");
  assert.equal(view.realDataAccessLabel, "restricted_network");
  assert.deepEqual(view.realDataBlocking, []);
});

test("buildPilotReadinessView surfaces controlled-use gaps", () => {
  const view = buildPilotReadinessView({
    pilot_sellable: false,
    production_ready: false,
    real_data_pilot: {
      allowed: false,
      blocking: ["pilot_sellable", "postgres_store_active"],
    },
    pilot_blocking: ["auth_requires_user", "postgres_store_active"],
    warnings: ["backup_missing"],
    auth: { auth_mode: "mock_header_optional" },
    store_backend: "json",
    ai_provider: "disabled",
  });

  assert.equal(view.status, "blocked");
  assert.equal(view.statusLabel, "Kurulum kontrolü gerekli");
  assert.equal(view.authLabel, "mock_header_optional");
  assert.equal(view.storeLabel, "json");
  assert.equal(view.realDataLabel, "Gerçek veri için kapalı");
  assert.deepEqual(view.realDataBlocking, ["pilot_sellable", "postgres_store_active"]);
  assert.deepEqual(view.blocking, ["auth_requires_user", "postgres_store_active"]);
  assert.deepEqual(view.warnings, ["backup_missing"]);
});
