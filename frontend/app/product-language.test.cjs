const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

function source(name) {
  return readFileSync(join(__dirname, name), "utf8");
}

test("portal visible copy presents AI agent automation without internal implementation language", () => {
  const visibleSource = [
    source("layout.tsx"),
    source("page.tsx"),
    source("portal-app.tsx"),
    source("portal-review-panels.tsx"),
    source("pilot-readiness.js"),
    source("demo-data.ts"),
  ].join("\n");

  assert.match(visibleSource, /AI ajan destekli fiş taslağı/);
  assert.match(visibleSource, /Otomasyon adayı/);
  assert.match(visibleSource, /Güven düzeyi/);
  assert.match(visibleSource, /Öneri gerekçesi/);

  assert.doesNotMatch(
    visibleSource,
    /Private Pilot|private pilot|Private pilot demo verisi|Kapali pilot|Kapalı pilot|Pilot satis|Pilot satış|sifresiz pilot|şifresiz pilot|lokal private|Backend session|Backend oturumu yok|Local gelistirme|Lokal fallback|AI provider|AI\/kural yorumu|AI hesap önerisi|AI cari önerisi|AI risk|Export hazır|Export dışı|export kapalı|export'a|Zirve import dogrulanmadi|Zirve import doğrulanmadı|Worker sonucu bekleniyor|Onaya gitmeme nedeni|Codex|Claude|ChatGPT|Prompt verdik|promptla yazılım/i,
  );
});

test("review actions clearly name the export exclusion decision", () => {
  const reviewSource = source("portal-review-panels.tsx");

  assert.match(reviewSource, /Çıktı listesine ekleme/);
});

test("operations page uses AI agent capacity language without plan wording", () => {
  const operationsSource = source("portal-exports-view.tsx");

  assert.match(operationsSource, /AI ajanı kapasitesi/);
  assert.match(operationsSource, /Araştırma ajanı/);
  assert.doesNotMatch(operationsSource, /free tier|free|ücretsiz|API key|secret/i);
});

test("client onboarding labels portal user as the client email login", () => {
  const clientsSource = source("portal-clients-view.tsx");

  assert.match(clientsSource, /Mükellef e-posta \/ giriş kullanıcı adı/);
});

test("portal visible source does not contain mojibake Turkish copy", () => {
  const visibleSource = [
    source("page.tsx"),
    source("portal-app.tsx"),
    source("portal-client-view.tsx"),
    source("portal-clients-view.tsx"),
    source("portal-dashboard.js"),
    source("portal-dashboard-view.tsx"),
    source("portal-data-mappers.ts"),
    source("portal-formatters.ts"),
    source("portal-review-actions.ts"),
    source("portal-settings-view.tsx"),
    source("portal-shell-components.tsx"),
    source("portal-session.ts"),
    source("portal-workspace-actions.ts"),
    source("portal-workspace-view.tsx"),
    source("workspace-api.js"),
  ].join("\n");

  assert.doesNotMatch(visibleSource, /(?:Ã.|Ä.|Å.|�)/);
  assert.match(visibleSource, /Çalışma alanı boş/);
  assert.match(visibleSource, /Veri kaynağı/);
  assert.match(visibleSource, /Çıkış/);
  assert.match(visibleSource, /Mükellef takibi/);
  assert.match(visibleSource, /Yükleme ve kontrol sırası/);
});
