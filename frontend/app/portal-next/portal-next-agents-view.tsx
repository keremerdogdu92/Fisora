// File: frontend/app/portal-next/portal-next-agents-view.tsx
// Summary: Renders the accountant-facing AI team, HTML reading quality workspace, research records, and confirmed learned rules for portal-next.
"use client";

import { Bot, CircleCheckBig, GraduationCap, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { useAgentRuleCommands, type AgentRuleView } from "../features/agents";
import { useOriginalDocumentPreview } from "../portal-review-panels";
import { ResearchKnowledgeView } from "../portal-research-view";
import { HtmlDocumentViewer } from "../shared/components/document-viewers/html-document-viewer";
import type { DocumentSourceTarget, LocalSession, PilotDocument, SourceReviewRow } from "../portal-types";

type AgentSummary = {
  key: string; name: string; statusLabel: string; touchedCount: number;
  capacityLabel: string; unchangedApprovalRateLabel: string; correctionCount: number; learningLabel: string;
};
type AgentLearningInsight = {
  id: string; documentLabel: string; stageLabel: string; summary: string; confidenceLabel: string;
};
type AgentTab = "overview" | "reader" | "research";
function isHtmlDocument(document: PilotDocument) {
  const mime = String(document.originalDocumentMimeType || "").toLowerCase();
  const fileName = String(document.fileName || "").toLowerCase();
  return mime.includes("html") || fileName.endsWith(".html") || fileName.endsWith(".htm");
}

function normalizeText(value: string) {
  return String(value || "").normalize("NFKC").toLocaleLowerCase("tr-TR")
    .replace(/\u00a0/g, " ").replace(/\s+/g, " ").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function stageBucket(stageLabel: string) {
  if (stageLabel.includes("Kontrollü otomasyon")) return "automation";
  if (stageLabel.includes("Kural adayı")) return "candidate";
  return "note";
}

function readerRowsFor(document?: PilotDocument) {
  return (document?.sourceSnapshot?.sections ?? []).flatMap((section) =>
    section.rows.map((row) => row.filter(Boolean).join(" · ").trim()).filter(Boolean),
  );
}
function comparisonForRow(row: SourceReviewRow, readerRows: string[], index: number) {
  const sourceIndex = Number.parseInt(String(row.sourcePosition || ""), 10);
  const readerText = readerRows[Number.isInteger(sourceIndex) && sourceIndex > 0 ? sourceIndex - 1 : index] || row.sourceText || "";
  const sourceText = row.sourceText || readerText;
  const readerNormalized = normalizeText(readerText);
  const sourceNormalized = normalizeText(sourceText);
  const matched = Boolean(readerNormalized && sourceNormalized && (readerNormalized.includes(sourceNormalized) || sourceNormalized.includes(readerNormalized)));
  return { readerText, matched };
}

function helpAgent(document: PilotDocument) {
  const reasons = `${document.reviewReasons.join(" ")} ${document.aiGateReason || ""}`.toLocaleLowerCase("tr-TR");
  if (document.aiResearchRequested) return "Araştırma";
  if (isHtmlDocument(document) && (document.sourceSnapshot?.warnings.length || /reader|okuma|html|parse|kaynak/.test(reasons))) return "Okuma";
  return "Muhasebe";
}

function assistanceItems(documents: PilotDocument[]) {
  return documents.filter((document) => document.status === "review_required").slice(0, 6).map((document) => ({
    document,
    agent: helpAgent(document),
    title: document.accountantActionHint || document.accountantSummary || document.reviewReasons[0] || "Müşavir kontrolü gerekiyor.",
    detail: `${document.clientName} · ${document.fileName}`,
  }));
}
function mergedAgentCards(agentSummaries: AgentSummary[], helpItems: ReturnType<typeof assistanceItems>) {
  const byKey = new Map(agentSummaries.map((agent) => [agent.key, agent]));
  const document = byKey.get("document");
  const account = byKey.get("account");
  const counterparty = byKey.get("counterparty");
  const research = byKey.get("research");
  const helpCount = (agent: string) => helpItems.filter((item) => item.agent === agent).length;
  return [
    {
      key: "reader", name: "Okuma Ajanı", description: "Kaynak belgeyi okur ve yapılandırır.",
      status: document?.statusLabel || "Veri bekliyor", today: document?.touchedCount ?? 0,
      statLabel: "Yardım", statValue: String(helpCount("Okuma")), foot: document?.learningLabel || "Okuma sinyali yok",
    },
    {
      key: "accounting", name: "Muhasebe Ajanı", description: "Fiş taslağı, hesap ve cari kararını hazırlar.",
      status: account?.statusLabel || counterparty?.statusLabel || "Veri bekliyor",
      today: Math.max(account?.touchedCount ?? 0, counterparty?.touchedCount ?? 0),
      statLabel: "Düzeltme", statValue: String(Math.max(account?.correctionCount ?? 0, counterparty?.correctionCount ?? 0)),
      foot: account?.unchangedApprovalRateLabel || "Onay ölçümü yok",
    },
    {
      key: "research", name: "Araştırma Ajanı", description: "Yalnızca belirsizlik olduğunda devreye girer.",
      status: research?.statusLabel || "Beklemede", today: research?.touchedCount ?? 0,
      statLabel: "Açık konu", statValue: String(helpCount("Araştırma")), foot: research?.learningLabel || "Araştırma sinyali yok",
    },
  ];
}
function ReaderQualityPanel({ documents, session }: { documents: PilotDocument[]; session: LocalSession | null }) {
  const htmlDocuments = useMemo(() => documents.filter(isHtmlDocument), [documents]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [sourceTarget, setSourceTarget] = useState<DocumentSourceTarget | null>(null);
  const selectedDocument = htmlDocuments.find((document) => document.id === selectedDocumentId) ?? htmlDocuments[0];
  const { previewError, previewUrl } = useOriginalDocumentPreview(selectedDocument, session);
  const readerRows = useMemo(() => readerRowsFor(selectedDocument), [selectedDocument]);
  const rows = selectedDocument?.sourceReviewRows ?? [];
  const snapshot = selectedDocument?.sourceSnapshot;

  if (!selectedDocument) {
    return <section className="portal-next-reader-empty">Bu kapsamda karşılaştırılabilir HTML belge yok.</section>;
  }

  function focusRow(row: SourceReviewRow, index: number) {
    const compared = comparisonForRow(row, readerRows, index);
    setSourceTarget({ key: `${selectedDocument.id}:${row.sourcePosition || index}:${Date.now()}`, text: row.sourceText || compared.readerText || row.description, sourcePosition: row.sourcePosition });
  }

  return (
    <section className="portal-next-reader-workspace" aria-label="Okuma Kalitesi">
      <div className="portal-next-reader-head">
        <div><span>Okuma Kalitesi</span><h2>Orijinal belge ile okunan sonucu karşılaştır</h2></div>
        <label><span>HTML belge</span><select value={selectedDocument.id} onChange={(event) => { setSelectedDocumentId(event.target.value); setSourceTarget(null); }}>
          {htmlDocuments.map((document) => <option key={document.id} value={document.id}>{document.fileName}</option>)}
        </select></label>
      </div>
      <div className="portal-next-reader-metrics">
        <div><span>Reader</span><strong>{snapshot?.version || "-"}</strong></div>
        <div><span>Güven</span><strong>{snapshot ? `%${Math.round(snapshot.confidence * 100)}` : "-"}</strong></div>
        <div><span>Kaynak satırı</span><strong>{snapshot?.metrics.rowCount ?? 0}</strong></div>
        <div><span>Fisora satırı</span><strong>{rows.length}</strong></div>
        <div className={snapshot?.warnings.length ? "attention" : "ok"}><span>Uyarı</span><strong>{snapshot?.warnings.length ?? 0}</strong></div>
      </div>
      {snapshot?.warnings.length ? <div className="portal-next-reader-warning">{snapshot.warnings.join(" · ")}</div> : null}
      <div className="portal-next-reader-grid">
        <article className="portal-next-reader-source">
          <header><strong>Orijinal belge</strong><span>Satıra tıklayınca ilgili kaynak işaretlenir.</span></header>
          {previewUrl ? <HtmlDocumentViewer fileName={selectedDocument.fileName} src={previewUrl} sourceTarget={sourceTarget} onClearSourceTarget={() => setSourceTarget(null)} /> : <p className="empty">{previewError || "Orijinal HTML yükleniyor."}</p>}
        </article>
        <article className="portal-next-reader-results">
          <header><strong>Okunan sonuç</strong><span>Reader ve Fisora satırı aynı kartta.</span></header>
          <div className="portal-next-reader-row-list">
            {rows.map((row, index) => {
              const compared = comparisonForRow(row, readerRows, index);
              return <button className={compared.matched ? "portal-next-reader-row matched" : "portal-next-reader-row attention"} key={`${row.sourcePosition}:${index}`} onClick={() => focusRow(row, index)} type="button">
                <div className="portal-next-reader-row-head"><strong>{row.sourcePosition || String(index + 1)} · {row.description || row.sourceText || "Satır"}</strong><span>{compared.matched ? "Eşleşti" : "Kontrol"}</span></div>
                <div><small>Reader</small><p>{compared.readerText || "Kaynak satırı bulunamadı."}</p></div>
                <div><small>Fisora'da</small><p>{row.description || row.sourceText || "-"}{row.amount ? ` · ${row.amount}` : ""}</p></div>
              </button>;
            })}
            {!rows.length ? <p className="empty">Bu belge için Fisora UI satırı oluşmamış.</p> : null}
          </div>
        </article>
      </div>
    </section>
  );
}
export function PortalNextAgentsView({ agentSummaries, documents, learningInsights, loginUserId, onOpenDocument, session }: {
  agentSummaries: AgentSummary[]; documents: PilotDocument[]; learningInsights: AgentLearningInsight[];
  loginUserId: string; onOpenDocument: (document: PilotDocument) => void; session: LocalSession | null;
}) {
  const [activeTab, setActiveTab] = useState<AgentTab>("overview");
  const helpItems = useMemo(() => assistanceItems(documents), [documents]);
  const cards = useMemo(() => mergedAgentCards(agentSummaries, helpItems), [agentSummaries, helpItems]);
  const trainingNotes = learningInsights.filter((item) => stageBucket(item.stageLabel) === "note");
  const ruleCandidates = learningInsights.filter((item) => stageBucket(item.stageLabel) === "candidate");
  const automationCandidates = learningInsights.filter((item) => stageBucket(item.stageLabel) === "automation");
  const learningColumns = [
    { key: "notes", title: "Eğitim notları", items: trainingNotes, icon: GraduationCap },
    { key: "candidates", title: "Kural adayları", items: ruleCandidates, icon: Bot },
    { key: "automation", title: "Kontrollü otomasyon", items: automationCandidates, icon: CircleCheckBig },
  ];

  return (
    <section className="portal-next-ai-page">
      <div className="portal-next-ai-tabs" role="tablist" aria-label="AI Ajanları bölümleri">
        <button className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")} type="button">Genel Bakış</button>
        <button className={activeTab === "reader" ? "active" : ""} onClick={() => setActiveTab("reader")} type="button">Okuma Kalitesi</button>
        <button className={activeTab === "research" ? "active" : ""} onClick={() => setActiveTab("research")} type="button">Araştırma Kayıtları</button>
      </div>
      {activeTab === "reader" ? <ReaderQualityPanel documents={documents} session={session} /> : null}
      {activeTab === "research" ? <ResearchKnowledgeView loginUserId={loginUserId} session={session} /> : null}
      {activeTab === "overview" ? (
        <>
          <section className="portal-next-ai-hero">
            <span>Dijital ekip çalışıyor</span>
            <h2>Ajanlar teknik aşamaları kendi aralarında yürütür; sen muhasebe sonucunu ve gereken yardımı görürsün.</h2>
            <p>Bir ajan zorlandığında hata kodu yerine neye ihtiyaç duyduğunu açıkça söyler.</p>
          </section>
          <section className="portal-next-ai-cards" aria-label="Fisora dijital ekibi">
            {cards.map((agent) => <article key={agent.key}>
              <div className="portal-next-ai-card-head"><span className="portal-next-ai-avatar"><Bot aria-hidden="true" /></span><div><strong>{agent.name}</strong><small>{agent.description}</small></div><em>{agent.status}</em></div>
              <dl><div><dt>Bugün</dt><dd>{agent.today}</dd></div><div><dt>{agent.statLabel}</dt><dd>{agent.statValue}</dd></div></dl>
              <small className="portal-next-ai-card-foot">{agent.foot}</small>
            </article>)}
          </section>
          <section className="portal-next-ai-help-card">
            <header><strong>Bugün senden yardım isteyenler</strong><span>{helpItems.length} açık konu</span></header>
            <div>{helpItems.map((item) => <article key={item.document.id}>
              <span className="portal-next-ai-help-agent">{item.agent.slice(0, 1)}</span>
              <div><strong>{item.title}</strong><small>{item.detail}</small></div>
              <button onClick={() => onOpenDocument(item.document)} type="button">İncele</button>
            </article>)}{!helpItems.length ? <p className="empty">Şu anda ajanların senden beklediği açık konu yok.</p> : null}</div>
          </section>
          <section className="portal-next-ai-learning-grid">
            {learningColumns.map((column) => {
              const Icon = column.icon;
              return <article key={column.key}>
                <header><strong>{column.title}</strong><span>{column.items.length}</span></header>
                <div>{column.items.slice(0, 4).map((item) => <section key={item.id}>
                  <Icon aria-hidden="true" /><div><span>{item.stageLabel}</span><strong>{item.documentLabel}</strong><p>{item.summary}</p><small>{item.confidenceLabel}</small></div>
                </section>)}{!column.items.length ? <p className="empty">Kayıt yok.</p> : null}</div>
              </article>;
            })}
          </section>
        </>
      ) : null}
    </section>
  );
}

function ruleText(rule: AgentRuleView, key: string) {
  return String(rule[key] || "").trim();
}

function ruleCategory(rule: AgentRuleView) {
  const text = `${ruleText(rule, "meaning_label")} ${ruleText(rule, "rule_key")} ${ruleText(rule, "trigger_label")}`.toLocaleLowerCase("tr-TR");
  if (/kdv|vergi|istisna|öiv|tevkifat/.test(text)) return "tax";
  if (/ürün|urun|stok|mal|cihaz|product/.test(text)) return "product";
  return "supplier";
}

function categoryLabel(category: string) {
  if (category === "product") return "Ürün ailesi";
  if (category === "tax") return "Vergi / işlem";
  return "Tedarikçi";
}
function formatRuleDate(value: string) {
  if (!value) return "Henüz yok";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

export function PortalNextLearnedRulesView({ loginUserId, session }: { loginUserId: string; session: LocalSession | null }) {
  const { rules, status, changeStatus } = useAgentRuleCommands({ loginUserId, session });
  const [filter, setFilter] = useState<"all" | "supplier" | "product" | "tax">("all");
  const activeRules = rules.filter((rule) => String(rule.status || "active") === "active");
  const filteredRules = filter === "all" ? activeRules : activeRules.filter((rule) => ruleCategory(rule) === filter);
  const counts = { supplier: 0, product: 0, tax: 0 };
  activeRules.forEach((rule) => { counts[ruleCategory(rule) as keyof typeof counts] += 1; });

  return (
    <section className="portal-next-rules-page">
      <div className="portal-next-rules-intro">
        <div><span>Doğrulanmış iş mantığı</span><h2>Öğrenilen Kurallar</h2><p>Fisora hesap kodunu ezberlemez; muhasebe anlamını, kapsamını ve dayanağını öğrenir.</p></div>
      </div>
      <div className="portal-next-rules-metrics">
        <div><span>Etkin öğrenme</span><strong>{activeRules.length}</strong><small>İş mantığı</small></div>
        <div><span>Tedarikçi</span><strong>{counts.supplier}</strong></div>
        <div><span>Ürün ailesi</span><strong>{counts.product}</strong></div>
        <div><span>Vergi / işlem</span><strong>{counts.tax}</strong></div>
      </div>
      <div className="portal-next-rule-filters" aria-label="Kural türleri">
        {([['all','Tümü'],['supplier','Tedarikçi'],['product','Ürün ailesi'],['tax','Vergi / işlem']] as const).map(([key, label]) =>
          <button className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key)} type="button">{label}</button>)}
      </div>
      {status ? <p className="status-line">{status}</p> : null}
      <div className="portal-next-rule-list">
        {filteredRules.map((rule) => {
          const key = ruleText(rule, "rule_key");
          const trigger = ruleText(rule, "trigger_label") || ruleText(rule, "source_document_label") || "Doğrulanmış muhasebe kuralı";
          const meaning = ruleText(rule, "meaning_label") || "Müşavir tarafından doğrulanmış iş mantığı";
          const binding = ruleText(rule, "binding_label");
          return <article className="portal-next-rule-card" key={`${key}:${String(rule.version || 0)}`}>
            <div className="portal-next-rule-top"><div><span>{categoryLabel(ruleCategory(rule))} kuralı</span><strong>{trigger}</strong></div><em>Etkin</em></div>
            <div className="portal-next-rule-decision"><strong>{meaning}</strong><p>Hesap kodunu evrensel ezber olarak değil, ilgili mükellefin gerçek hesap planı bağlamında uygula.</p></div>
            <div className="portal-next-rule-meta">
              <div><span>Kapsam</span><strong>{ruleText(rule, "scope_label") || "Mükellefe özel"}</strong></div>
              <div><span>Dayanak</span><strong>{ruleText(rule, "source_document_label") || ruleText(rule, "confirmed_by") || "Müşavir onayı"}</strong></div>
              <div><span>Kullanım</span><strong>{Number(rule.match_count || 0)} kez</strong></div>
              <div><span>Son kullanım</span><strong>{formatRuleDate(ruleText(rule, "last_matched_at"))}</strong></div>
            </div>
            <div className="portal-next-rule-actions">
              <details><summary>Kuralı incele</summary><div><span>Doğrulayan</span><strong>{ruleText(rule, "confirmed_by") || "Müşavir"}</strong>{binding ? <><span>Hesap planı bağı</span><strong>{binding}</strong></> : null}</div></details>
              <button onClick={() => changeStatus(rule, "pause")} type="button">Duraklat</button>
              <button className="danger" onClick={() => changeStatus(rule, "archive")} type="button">Arşivle</button>
            </div>
          </article>;
        })}
        {!filteredRules.length ? <section className="portal-next-rules-empty"><ShieldCheck aria-hidden="true" /><strong>Bu kapsamda etkin kural yok.</strong><p>Yeni adaylar önce AI Ajanları altında doğrulama sinyali olarak görünür; müşavir onayından sonra buraya gelir.</p></section> : null}
      </div>
    </section>
  );
}
