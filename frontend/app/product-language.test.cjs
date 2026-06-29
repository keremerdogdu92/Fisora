const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

function source(name) {
  return readFileSync(join(__dirname, name), "utf8");
}

const visibleCopyFiles = [
  "layout.tsx",
  "page.tsx",
  "portal-app.tsx",
  "portal-client-actions.ts",
  "portal-client-view.tsx",
  "portal-clients-view.tsx",
  "portal-dashboard.js",
  "portal-dashboard-view.tsx",
  "portal-data-mappers.ts",
  "portal-document-actions.ts",
  "portal-documents-view.tsx",
  "portal-formatters.ts",
  "portal-review-actions.ts",
  "portal-review-panels.tsx",
  "portal-settings-view.tsx",
  "portal-shell-components.tsx",
  "portal-session.ts",
  "portal-workspace-actions.ts",
  "portal-workspace-view.tsx",
  "workspace-api.js",
];

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
  assert.match(visibleSource, /Düzeltme notu/);

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

test("document processing shows passive AI agent capacity labels", () => {
  const documentSource = source("portal-documents-view.tsx");
  const queriesSource = source("features/workspace/queries.ts");
  const operationsSource = source("portal-exports-view.tsx");
  const stylesSource = source("styles.css");

  assert.match(documentSource, /AI kapasitesi/);
  assert.match(documentSource, /Belge ajanı/);
  assert.match(documentSource, /Araştırma ajanı/);
  assert.match(documentSource, /yaklaşık/i);
  assert.doesNotMatch(documentSource, /onClick|research\/refresh|yenile/i);
  assert.match(queriesSource, /refetchInterval:\s*5 \* 60 \* 1000/);
  assert.match(queriesSource, /refetchOnWindowFocus:\s*true/);
  assert.match(operationsSource, /Ölçülemiyor/);
  assert.match(stylesSource, /\.document-capacity-strip\s*\{/);
  assert.match(stylesSource, /@media \(max-width: 720px\)/);
});

test("client onboarding labels portal user as the client email login", () => {
  const clientsSource = source("portal-clients-view.tsx");

  assert.match(clientsSource, /Mükellef e-posta \/ giriş kullanıcı adı/);
});

test("portal visible source does not contain mojibake Turkish copy", () => {
  const visibleSource = visibleCopyFiles.map(source).join("\n");

  assert.doesNotMatch(visibleSource, /(?:Ã|Ä|Å|�|ï¿½)/);
  assert.match(visibleSource, /Çalışma alanı boş/);
  assert.match(visibleSource, /Veri kaynağı/);
  assert.match(visibleSource, /Çıkış/);
  assert.match(visibleSource, /Mükellef takibi/);
  assert.match(visibleSource, /Yükleme ve kontrol sırası/);
});

test("document processing workbench keeps the journal review explicit", () => {
  const reviewSource = source("portal-review-panels.tsx");
  const stylesSource = source("styles.css");
  const draftEditorIndex = reviewSource.indexOf("<ManualDraftEditor");
  const decisionChainIndex = reviewSource.indexOf("<DecisionChainPanel");

  assert.match(reviewSource, /safeHeaderValue/);
  assert.match(reviewSource, /reviewWorkspaceTabs/);
  assert.notEqual(draftEditorIndex, -1);
  assert.notEqual(decisionChainIndex, -1);
  assert.ok(draftEditorIndex < decisionChainIndex, "journal line editor should appear before decision chain details");
  assert.match(reviewSource, /Karar ve gerekçe/);
  assert.match(reviewSource, /Düzeltme notu/);
  assert.match(reviewSource, /Kural talimatı/);
  assert.match(stylesSource, /\.decision-chain-panel/);
  assert.match(reviewSource, /Fiş durumu/);
  assert.match(reviewSource, /Muhasebe fişi detayları/);
  assert.match(reviewSource, /AI muhasebe gerekçesi/);
  assert.match(reviewSource, /Düzeltme/);
  assert.match(reviewSource, /Geçmiş/);
  assert.match(reviewSource, /Kararı etkileyen açıklamaları göster/);
  assert.match(stylesSource, /\.journal-workspace-tabs/);
  assert.match(stylesSource, /\.journal-ledger/);
});
