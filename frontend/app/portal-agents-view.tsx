// File: frontend/app/portal-agents-view.tsx
// Summary: Renders learned-rule training, research records, and the isolated HTML Reader quality-control surface for accountant workflows.
import { Bot, CircleCheckBig, GraduationCap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useAgentRuleCommands } from "./features/agents";
import { HtmlReaderSnapshot, HtmlSourceComparison, useOriginalDocumentPreview } from "./portal-review-panels";
import { ResearchKnowledgeView } from "./portal-research-view";
import { HtmlDocumentViewer } from "./shared/components/document-viewers/html-document-viewer";
import type { LocalSession, PilotDocument } from "./portal-types";

type AgentSummary = {
  key: string;
  name: string;
  statusLabel: string;
  touchedCount: number;
  capacityLabel: string;
  unchangedApprovalRateLabel: string;
  correctionCount: number;
  learningLabel: string;
};

type AgentLearningInsight = {
  id: string;
  documentLabel: string;
  stageLabel: string;
  summary: string;
  confidenceLabel: string;
};

function stageBucket(stageLabel: string) {
  if (stageLabel.includes("Kontrollü otomasyon")) return "automation";
  if (stageLabel.includes("Kural adayı")) return "candidate";
  return "note";
}

function isHtmlDocument(document: PilotDocument) {
  const mime = String(document.originalDocumentMimeType || "").toLowerCase();
  const fileName = String(document.fileName || "").toLowerCase();
  return mime.includes("html") || fileName.endsWith(".html") || fileName.endsWith(".htm");
}

export function HtmlReaderQualityControl({ documents, session }: { documents: PilotDocument[]; session: LocalSession | null }) {
  const htmlDocuments = useMemo(() => documents.filter(isHtmlDocument), [documents]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [activeView, setActiveView] = useState<"original" | "reader" | "comparison">("original");
  const selectedDocument = htmlDocuments.find((document) => document.id === selectedDocumentId) ?? htmlDocuments[0];
  const { previewError, previewUrl } = useOriginalDocumentPreview(selectedDocument, session);

  useEffect(() => {
    if (selectedDocument && selectedDocument.id !== selectedDocumentId) setSelectedDocumentId(selectedDocument.id);
  }, [selectedDocument, selectedDocumentId]);

  if (!htmlDocuments.length) {
    return <section className="panel html-reader-quality-control"><p className="empty">Bu kapsamda HTML belge yok.</p></section>;
  }
  if (!selectedDocument) return null;

  return (
    <section className="panel html-reader-quality-control" aria-label="Okuma Ajanı Kalite Kontrolü">
      <div className="section-heading">
        <div>
          <span>Geçici / pilot kalite yüzeyi</span>
          <h2>Okuma Ajanı Kalite Kontrolü</h2>
        </div>
        <label className="html-reader-document-select">
          <span>HTML belge</span>
          <select onChange={(event) => setSelectedDocumentId(event.target.value)} value={selectedDocument.id}>
            {htmlDocuments.map((document) => <option key={document.id} value={document.id}>{document.fileName}</option>)}
          </select>
        </label>
      </div>
      <div className="mode-tabs html-reader-quality-tabs" role="tablist" aria-label="Okuma ajanı kalite görünümleri">
        <button aria-selected={activeView === "original"} className={activeView === "original" ? "mode-tab active" : "mode-tab"} onClick={() => setActiveView("original")} role="tab" type="button">Orijinal</button>
        <button aria-selected={activeView === "reader"} className={activeView === "reader" ? "mode-tab active" : "mode-tab"} onClick={() => setActiveView("reader")} role="tab" type="button">Reader</button>
        <button aria-selected={activeView === "comparison"} className={activeView === "comparison" ? "mode-tab active" : "mode-tab"} onClick={() => setActiveView("comparison")} role="tab" type="button">Karşılaştır</button>
      </div>
      {activeView === "original" ? (
        previewUrl ? <HtmlDocumentViewer fileName={selectedDocument.fileName} src={previewUrl} /> : <p className="empty">{previewError || "Orijinal HTML yükleniyor."}</p>
      ) : null}
      {activeView === "reader" ? <HtmlReaderSnapshot document={selectedDocument} /> : null}
      {activeView === "comparison" ? (
        previewUrl ? <HtmlSourceComparison document={selectedDocument} previewUrl={previewUrl} /> : <p className="empty">{previewError || "Orijinal HTML yükleniyor."}</p>
      ) : null}
    </section>
  );
}

export function AgentTrainingView({
  agentSummaries,
  defaultSection = "learning",
  learningInsights,
  loginUserId,
  session,
}: {
  agentSummaries: AgentSummary[];
  defaultSection?: "learning" | "research";
  learningInsights: AgentLearningInsight[];
  loginUserId: string;
  session: LocalSession | null;
}) {
  const [activeSection, setActiveSection] = useState<"learning" | "research">(defaultSection);
  const { rules: learningRules, status: ruleStatus, changeStatus: onRuleStatusChange } = useAgentRuleCommands({ loginUserId, session });
  const trainingNotes = learningInsights.filter((item) => stageBucket(item.stageLabel) === "note");
  const ruleCandidates = learningInsights.filter((item) => stageBucket(item.stageLabel) === "candidate");
  const automationCandidates = learningInsights.filter((item) => stageBucket(item.stageLabel) === "automation");
  const columns = [
    { key: "notes", title: "Eğitim notları", items: trainingNotes },
    { key: "candidates", title: "Kural adayları", items: ruleCandidates },
    { key: "automation", title: "Kontrollü otomasyon adayları", items: automationCandidates },
  ];

  return (
    <section className="agent-training-page">
      <div className="mode-tabs" role="tablist" aria-label="AI ajanları bölümleri">
        <button aria-controls="agent-learning-panel" aria-selected={activeSection === "learning"} className={activeSection === "learning" ? "mode-tab active" : "mode-tab"} id="agent-learning-tab" onClick={() => setActiveSection("learning")} role="tab" type="button">
          Öğrenme ve kurallar
        </button>
        <button aria-controls="agent-research-panel" aria-selected={activeSection === "research"} className={activeSection === "research" ? "mode-tab active" : "mode-tab"} id="agent-research-tab" onClick={() => setActiveSection("research")} role="tab" type="button">
          Araştırma kayıtları
        </button>
      </div>

      {activeSection === "research" ? (
        <section aria-labelledby="agent-research-tab" id="agent-research-panel" role="tabpanel">
          <ResearchKnowledgeView loginUserId={loginUserId} session={session} />
        </section>
      ) : (
        <section aria-labelledby="agent-learning-tab" id="agent-learning-panel" role="tabpanel">
      <section className="agent-training-grid" aria-label="AI ajanları">
        {agentSummaries.map((agent) => (
          <article className="agent-training-card" key={agent.key}>
            <div>
              <Bot aria-hidden="true" />
              <span>
                <strong>{agent.name}</strong>
                <em>{agent.statusLabel}</em>
              </span>
            </div>
            <dl>
              <div>
                <dt>Dokunduğu iş</dt>
                <dd>{agent.touchedCount}</dd>
              </div>
              <div>
                <dt>Kapasite</dt>
                <dd>{agent.capacityLabel}</dd>
              </div>
              <div>
                <dt>Onay oranı</dt>
                <dd>{agent.unchangedApprovalRateLabel}</dd>
              </div>
              <div>
                <dt>Düzeltme</dt>
                <dd>{agent.correctionCount}</dd>
              </div>
            </dl>
            <small>{agent.learningLabel}</small>
          </article>
        ))}
      </section>

      <section className="agent-learning-board" aria-label="Ajan eğitim kanıtları">
        {columns.map((column) => (
          <section className="panel agent-learning-column" key={column.key}>
            <div className="section-heading">
              <span>{column.title}</span>
              <strong>{column.items.length}</strong>
            </div>
            <div className="agent-learning-list">
              {column.items.map((item) => (
                <article className="agent-learning-item" key={item.id}>
                  {column.key === "automation" ? <CircleCheckBig aria-hidden="true" /> : <GraduationCap aria-hidden="true" />}
                  <div>
                    <span>{item.stageLabel}</span>
                    <strong>{item.documentLabel}</strong>
                    <p>{item.summary}</p>
                    <small>{item.confidenceLabel}</small>
                  </div>
                </article>
              ))}
              {!column.items.length ? <p className="empty">Kayıt yok.</p> : null}
            </div>
          </section>
        ))}
      </section>

      <section className="panel agent-rule-board" aria-label="Kural yaşam döngüsü">
        <div className="section-heading"><span>Öğrenilmiş kural yönetimi</span><strong>{learningRules.length}</strong></div>
        {ruleStatus ? <p className="status-line">{ruleStatus}</p> : null}
        <div className="agent-learning-list">
          {learningRules.map((rule) => {
            const key = String(rule.rule_key || "");
            const state = String(rule.status || "draft");
            return <article className="agent-learning-item" key={`${key}:${String(rule.version || 0)}`}>
              <Bot aria-hidden="true" />
              <div><span>{state}</span><strong>{String(rule.meaning_label || rule.rule_key || "Kural")}</strong><p>{String(rule.binding_label || rule.source_document_label || "Kaynak kanıtı mevcut")}</p></div>
              <div className="inline-actions">
                {state === "draft" || state === "paused" ? <button type="button" onClick={() => onRuleStatusChange?.(rule, "activate")}>Etkinleştir</button> : null}
                {state === "active" ? <button type="button" onClick={() => onRuleStatusChange?.(rule, "pause")}>Duraklat</button> : null}
                {state !== "archived" ? <button type="button" onClick={() => onRuleStatusChange?.(rule, "archive")}>Arşivle</button> : null}
              </div>
            </article>;
          })}
          {!learningRules.length ? <p className="empty">Henüz yönetilebilir doğrulanmış kural yok.</p> : null}
        </div>
      </section>
        </section>
      )}
    </section>
  );
}
