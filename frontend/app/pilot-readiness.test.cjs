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

test("buildPilotReadinessView presents a closed paid pilot separately from production", () => {
  const view = buildPilotReadinessView({
    pilot_sellable: true,
    production_ready: false,
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
  assert.equal(view.statusLabel, "Kapali pilot satilabilir");
  assert.equal(view.productionLabel, "Production hazir degil");
  assert.equal(view.exportLabel, "Kontrollu CSV + manifest adayi");
  assert.equal(view.zirveLabel, "Zirve import dogrulanmadi");
  assert.deepEqual(view.blocking, []);
  assert.deepEqual(view.warnings, ["zirve_verified_adapter_missing"]);
});

test("buildPilotReadinessView surfaces blocking pilot gaps", () => {
  const view = buildPilotReadinessView({
    pilot_sellable: false,
    production_ready: false,
    pilot_blocking: ["auth_requires_user", "postgres_store_active"],
    warnings: ["backup_missing"],
    auth: { auth_mode: "mock_header_optional" },
    store_backend: "json",
    ai_provider: "disabled",
  });

  assert.equal(view.status, "blocked");
  assert.equal(view.statusLabel, "Pilot satis bloklu");
  assert.equal(view.authLabel, "mock_header_optional");
  assert.equal(view.storeLabel, "json");
  assert.deepEqual(view.blocking, ["auth_requires_user", "postgres_store_active"]);
  assert.deepEqual(view.warnings, ["backup_missing"]);
});
