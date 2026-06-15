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

test("client onboarding labels portal user as the client email login", () => {
  const clientsSource = source("portal-clients-view.tsx");

  assert.match(clientsSource, /Mükellef e-posta \/ giriş kullanıcı adı/);
});
