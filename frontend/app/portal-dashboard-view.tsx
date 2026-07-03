import {
  Bot,
  Clock3,
  ClipboardCheck,
  FileSearch,
  MessageSquareWarning,
  PackageCheck,
  Upload,
  Users,
  UserX,
} from "lucide-react";
import { groupedReviewReasons } from "./portal-normalization";
import { ChartBars, Metric } from "./portal-shared";
import type { ChartRow, DashboardClientRow, PilotDocument } from "./portal-types";

type DashboardMetrics = {
  totalClients: number;
  uploadedClients: number;
  notUploadedClients: number;
  pendingReviewDocuments: number;
  exportReadyDocuments: number;
  openCancellationRequests: number;
};

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

type DurationMetrics = {
  averageDocumentTimeLabel: string;
  uploadToDecisionTimeLabel: string;
  clientAverageCompletionTimeLabel: string;
};

type PriorityWorkItem = {
  id: string;
  kind: string;
  label: string;
  title: string;
  detail: string;
  statusLabel: string;
};

export function AccountantDashboard({
  agentSummaries,
  clientRows,
  dashboardMetrics,
  documents,
  durationMetrics,
  funnelRows,
  intakeDistribution,
  learningInsights,
  onClientSelect,
  priorityItems,
  selectedClientId,
  uploadTrackingRows,
}: {
  agentSummaries: AgentSummary[];
  clientRows: DashboardClientRow[];
  dashboardMetrics: DashboardMetrics;
  documents: PilotDocument[];
  durationMetrics: DurationMetrics;
  funnelRows: ChartRow[];
  intakeDistribution: ChartRow[];
  learningInsights: AgentLearningInsight[];
  onClientSelect: (clientId: string) => void;
  priorityItems: PriorityWorkItem[];
  selectedClientId: string;
  uploadTrackingRows: ChartRow[];
}) {
  const reviewReasonGroups = groupedReviewReasons(
    documents.filter((document) => document.status === "review_required"),
  );

  return (
    <section className="accountant-dashboard-page">
      <section className="office-dashboard" aria-label="Ofis durumu">
        <Metric icon={Users} label="Mükellef" value={dashboardMetrics.totalClients} />
        <Metric icon={Upload} label="Yükleyen" value={dashboardMetrics.uploadedClients} />
        <Metric icon={UserX} label="Yüklemeyen" value={dashboardMetrics.notUploadedClients} />
        <Metric icon={ClipboardCheck} label="Kontrol" value={dashboardMetrics.pendingReviewDocuments} />
        <Metric icon={PackageCheck} label="Çıktı hazır" value={dashboardMetrics.exportReadyDocuments} />
        <Metric icon={MessageSquareWarning} label="Talep" value={dashboardMetrics.openCancellationRequests} />
      </section>
      <section className="dashboard-workbench-grid" aria-label="Müşavir iş masası">
        <section className="panel priority-work-list">
          <div className="section-heading">
            <span>Öncelikli işler</span>
            <strong>{Math.min(priorityItems.length, 8)} iş</strong>
          </div>
          <div className="priority-items">
            {priorityItems.slice(0, 8).map((item) => (
              <button
                className="priority-item"
                key={item.id}
                onClick={() => item.kind === "document" ? onClientSelect(clientRows.find((row) => row.clientName === item.label)?.clientId || selectedClientId) : undefined}
                type="button"
              >
                <FileSearch aria-hidden="true" />
                <span>
                  <strong>{item.label}</strong>
                  <em>{item.title}</em>
                  <small>{item.detail}</small>
                </span>
                <b>{item.statusLabel}</b>
              </button>
            ))}
            {!priorityItems.length ? <p className="empty">Aksiyon bekleyen öncelikli iş yok.</p> : null}
          </div>
        </section>
        <section className="panel agent-workbench-panel">
          <div className="section-heading">
            <span>AI ajanları</span>
            <strong>4 rol</strong>
          </div>
          <div className="agent-summary-list">
            {agentSummaries.map((agent) => (
              <article className="agent-summary-card" key={agent.key}>
                <div>
                  <Bot aria-hidden="true" />
                  <span>
                    <strong>{agent.name}</strong>
                    <em>{agent.statusLabel}</em>
                  </span>
                </div>
                <dl>
                  <div>
                    <dt>Bugün dokundu</dt>
                    <dd>{agent.touchedCount}</dd>
                  </div>
                  <div>
                    <dt>Kapasite</dt>
                    <dd>{agent.capacityLabel}</dd>
                  </div>
                  <div>
                    <dt>Müşavirce değişmeden onaylandı</dt>
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
          </div>
        </section>
      </section>
      <section className="duration-metrics" aria-label="Süre metrikleri">
        <div>
          <Clock3 aria-hidden="true" />
          <span>Ortalama belge süresi</span>
          <strong>{durationMetrics.averageDocumentTimeLabel}</strong>
        </div>
        <div>
          <Clock3 aria-hidden="true" />
          <span>Yüklemeden müşavir kararına</span>
          <strong>{durationMetrics.uploadToDecisionTimeLabel}</strong>
        </div>
        <div>
          <Clock3 aria-hidden="true" />
          <span>Mükellef ortalama tamamlanma</span>
          <strong>{durationMetrics.clientAverageCompletionTimeLabel}</strong>
        </div>
      </section>
      <section className="panel learning-prep-panel" aria-label="Ajan eğitim hazırlığı">
        <div className="section-heading">
          <span>Eğitim hazırlığı</span>
          <strong>{learningInsights.length ? `${learningInsights.length} sinyal` : "Sinyal yok"}</strong>
        </div>
        <div className="learning-prep-list">
          {learningInsights.slice(0, 6).map((item) => (
            <article className="learning-prep-item" key={item.id}>
              <span>{item.stageLabel}</span>
              <strong>{item.documentLabel}</strong>
              <p>{item.summary}</p>
              <small>{item.confidenceLabel}</small>
            </article>
          ))}
          {!learningInsights.length ? <p className="empty">Henüz eğitim notu veya kural adayı yok.</p> : null}
        </div>
      </section>
      <section className="dashboard-visual-grid">
        <ChartBars title="Belge türü" rows={intakeDistribution} />
        <ChartBars title="Durum hunisi" rows={funnelRows} />
        <ChartBars title="Yükleme takibi" rows={uploadTrackingRows} />
      </section>
      {reviewReasonGroups.length ? (
        <section className="panel review-breakdown" aria-label="Kontrol bekleyen belge kırılımı">
          <div className="section-heading">
            <span>Kontrol bekleyenlerin nedeni</span>
            <strong>{dashboardMetrics.pendingReviewDocuments} belge aksiyon bekliyor</strong>
          </div>
          <div className="review-breakdown-list">
            {reviewReasonGroups.slice(0, 4).map((group) => (
              <span key={group.code}>{group.label}: {group.count}</span>
            ))}
          </div>
        </section>
      ) : null}
      <section className="panel">
        <div className="section-heading">
          <span>Mükellef takibi</span>
          <strong>Yükleme ve kontrol sırası</strong>
        </div>
        <div className="client-list dashboard-client-list">
          {clientRows.slice(0, 10).map((row) => (
            <button
              className={selectedClientId === row.clientId ? "client-row active" : "client-row"}
              key={row.clientId}
              onClick={() => onClientSelect(row.clientId)}
              type="button"
            >
              <strong>{row.clientName}</strong>
              <span>{row.status}</span>
              <em>{row.documentCount} belge / {row.pendingReviewCount} kontrol / {row.exportReadyCount} hazır</em>
            </button>
          ))}
        </div>
      </section>
    </section>
  );
}
