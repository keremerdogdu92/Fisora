import { Bot, CircleCheckBig, GraduationCap } from "lucide-react";

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
}: {
  agentSummaries: AgentSummary[];
  learningInsights: AgentLearningInsight[];
}) {
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
    </section>
  );
}
