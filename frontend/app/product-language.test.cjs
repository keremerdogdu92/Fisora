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
  assert.match(visibleSource, /Müşavir notu/);

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
  assert.match(clientsSource, /Mükellefi yeniden işle/);
});

test("client reprocess copy explains queued background processing", () => {
  const actionsSource = source("portal-client-actions.ts");

  assert.match(actionsSource, /arka planda işlenecek/);
  assert.doesNotMatch(actionsSource, /işlem tamamlandı/);
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
  const reasonDisclosureIndex = reviewSource.indexOf("journal-reason-disclosure");
  const decisionBarIndex = reviewSource.indexOf("journal-decision-bar");
  const primaryApproveIndex = reviewSource.indexOf("journal-primary-approve");
  const correctionPanelIndex = reviewSource.indexOf("journal-correction-panel");
  const scrollAreaIndex = reviewSource.indexOf("journal-scroll-area");
  const journalPanelSource = reviewSource.slice(
    reviewSource.indexOf("export function JournalPanel"),
    reviewSource.indexOf("function JournalReasonDisclosure"),
  );

  assert.match(reviewSource, /safeHeaderValue/);
  assert.doesNotMatch(journalPanelSource, /activeReviewTab|reviewWorkspaceTabs/);
  assert.doesNotMatch(journalPanelSource, /journal-account-summary|<h3>Hesap ve cari<\/h3>/);
  assert.doesNotMatch(journalPanelSource, /correctionAccountLabel|correctionAccountPlaceholder|Yeni gider\/stok hesabı|Yeni gelir hesabı|Yeni cari/);
  assert.notEqual(draftEditorIndex, -1);
  assert.notEqual(scrollAreaIndex, -1);
  assert.notEqual(primaryApproveIndex, -1);
  assert.notEqual(decisionBarIndex, -1);
  assert.notEqual(reasonDisclosureIndex, -1);
  assert.ok(draftEditorIndex < reasonDisclosureIndex, "journal line editor should appear before decision details");
  assert.ok(draftEditorIndex < primaryApproveIndex, "primary approval should follow the journal line editor");
  assert.ok(primaryApproveIndex < correctionPanelIndex, "notes should stay below the primary approval path");
  assert.ok(scrollAreaIndex < decisionBarIndex, "decision actions should sit outside the scrollable journal content");
  assert.doesNotMatch(journalPanelSource, /DocumentPipelineTimeline|AiTracePanel/);
  assert.match(reviewSource, /Müşavir notu/);
  assert.match(reviewSource, /Benzer belge öğrenme talimatı/);
  assert.doesNotMatch(journalPanelSource, /className="accountant-summary"/);
  assert.match(reviewSource, /Yeniden işle/);
  assert.match(stylesSource, /\.journal-scroll-area/);
  assert.match(stylesSource, /\.journal-primary-approve/);
  assert.match(stylesSource, /\.journal-decision-bar/);
  assert.match(stylesSource, /\.journal-status-primary/);
  assert.match(stylesSource, /\.journal-status-metrics/);
  assert.match(stylesSource, /align-items:\s*stretch/);
  assert.match(stylesSource, /aspect-ratio:\s*210 \/ 297/);
  assert.match(stylesSource, /\.journal-reason-disclosure/);
  assert.match(reviewSource, /Bu hesap neden seçildi/);
  assert.match(reviewSource, /Cari nasıl eşleşti/);
  assert.match(reviewSource, /Mükellef faaliyetiyle ilişkisi/);
  assert.match(reviewSource, /Kontrol gerektiren nokta/);
  assert.match(reviewSource, /Fiş durumu/);
  assert.match(reviewSource, /AI muhasebe gerekçesi/);
  assert.match(reviewSource, /Neden böyle önerildi/);
  assert.doesNotMatch(reviewSource, /Research ihtiyacı|AI tekrar durumu|Statik fallback izi|Cari aday izi/);
  assert.doesNotMatch(reviewSource, /Muhasebe fişi çalışma sekmeleri/);
  assert.doesNotMatch(stylesSource, /\.journal-account-summary/);
  assert.doesNotMatch(stylesSource, /\.journal-workspace-tabs/);
  assert.match(stylesSource, /\.journal-ledger/);
});
