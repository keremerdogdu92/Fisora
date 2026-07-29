import { Bot, CircleCheckBig, GraduationCap } from "lucide-react";
import { useAgentRuleCommands } from "./features/agents";
import type { LocalSession } from "./portal-types";

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

export function AgentTrainingView({
  agentSummaries,
  learningInsights,
  loginUserId,
  session,
}: {
  agentSummaries: AgentSummary[];
  learningInsights: AgentLearningInsight[];
  loginUserId: string;
  session: LocalSession | null;
}) {
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
  );
}
