// File: frontend/app/portal-dashboard-view.tsx
// Summary: Renders the accountant home dashboard, including the v13 office-period overview and the legacy review surface.

import {
  Bot,
  ClipboardCheck,
  FileSearch,
  MessageSquareWarning,
  PackageCheck,
  Upload,
  Users,
  UserX,
} from "lucide-react";
import { Metric } from "./portal-shared";
import { longPeriodLabel } from "./portal-formatters";
import type { DashboardClientRow, DocumentSegment, PilotDocument } from "./portal-types";
import type { DashboardResumeState } from "./portal-dashboard-resume";

type DashboardMetrics = {
  totalClients: number;
  uploadedClients: number;
  notUploadedClients: number;
  pendingReviewDocuments: number;
  exportReadyDocuments: number;
  openCancellationRequests: number;
};

type PriorityWorkItem = {
  id: string;
  kind: string;
  label: string;
  title: string;
  detail: string;
  statusLabel: string;
};

type DashboardResumeView = DashboardResumeState & {
  clientName: string;
  completedCount: number;
  totalCount: number;
};

type ActivityItem = {
  id: string;
  title: string;
  detail: string;
  timestamp: string;
  tone: "ok" | "warn" | "neutral";
};

const REVIEW_STATUS = "review_required";
const IN_PROGRESS_STATUSES = new Set(["uploaded", "queued", "processing"]);
const READY_STATUSES = new Set(["export_ready", "export_added", "exported"]);

function timestampValue(value: string) {
  if (!value) return 0;
  const native = Date.parse(value);
  if (Number.isFinite(native)) return native;
  const match = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (!match) return 0;
  return new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]), Number(match[4] || 0), Number(match[5] || 0)).getTime();
}

function activityTime(value: string) {
  if (!value) return "";
  const localized = value.match(/(?:^|\s)(\d{1,2}:\d{2})(?:$|\s)/)?.[1];
  if (localized) return localized;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("tr-TR", { hour: "2-digit", minute: "2-digit" }).format(parsed);
}

function activityItems(documents: PilotDocument[]): ActivityItem[] {
  return documents
    .map((document) => {
      const event = [...(document.pipelineEvents ?? [])]
        .filter((row) => row.createdAt)
        .sort((a, b) => timestampValue(b.createdAt) - timestampValue(a.createdAt))[0];
      const timestamp = event?.createdAt || document.qnbPulledAt || document.uploadedAt || "";
      if (document.qnbPulledAt) {
        return {
          id: `${document.id}-qnb`,
          title: `QNB · ${document.fileName}`,
          detail: `${document.clientName} için belge çalışma alanına alındı.`,
          timestamp,
          tone: "ok" as const,
        };
      }
      if (document.status === REVIEW_STATUS) {
        return {
          id: `${document.id}-review`,
          title: `${document.fileName} kontrol istedi`,
          detail: document.accountantSummary || event?.messageTr || `${document.clientName} · Müşavir kararı bekliyor.`,
          timestamp,
          tone: "warn" as const,
        };
      }
      if (READY_STATUSES.has(document.status)) {
        return {
          id: `${document.id}-ready`,
          title: `${document.clientName} · ${document.fileName}`,
          detail: event?.messageTr || "Fiş onay / çıktı aşamasına hazır.",
          timestamp,
          tone: "ok" as const,
        };
      }
      return {
        id: `${document.id}-activity`,
        title: `${document.fileName} ${IN_PROGRESS_STATUSES.has(document.status) ? "işleniyor" : "güncellendi"}`,
        detail: event?.messageTr || `${document.clientName} · Arka plan işlemi devam ediyor.`,
        timestamp,
        tone: "neutral" as const,
      };
    })
    .sort((a, b) => timestampValue(b.timestamp) - timestampValue(a.timestamp))
    .slice(0, 3);
}

function clientStatusTone(row: DashboardClientRow) {
  if (row.cancellationCount || row.pendingReviewCount) return "warn";
  if (!row.documentCount) return "warn";
  if (row.inProgressCount) return "neutral";
  return "ok";
}

export function AccountantDashboard({
  clientRows,
  dashboardMetrics,
  documents,
  isLoading,
  nextPresentation = false,
  officePeriod = "",
  onClientSelect,
  onOpenAgents = () => undefined,
  onOpenClients = () => undefined,
  onOpenDocument,
  onOpenTask = () => undefined,
  onOpenWorkspace = () => undefined,
  onResume = () => undefined,
  priorityItems,
  resume,
  selectedClientId,
}: {
  clientRows: DashboardClientRow[];
  dashboardMetrics: DashboardMetrics;
  documents: PilotDocument[];
  isLoading: boolean;
  nextPresentation?: boolean;
  officePeriod?: string;
  onClientSelect: (clientId: string) => void;
  onOpenAgents?: () => void;
  onOpenClients?: () => void;
  onOpenDocument: (document: PilotDocument) => void;
  onOpenTask?: (segment: DocumentSegment) => void;
  onOpenWorkspace?: () => void;
  onResume?: () => void;
  priorityItems: PriorityWorkItem[];
  resume?: DashboardResumeView | null;
  selectedClientId: string;
}) {
  function openPriorityItem(item: PriorityWorkItem) {
    const documentId = item.id.startsWith("document-") ? item.id.slice("document-".length) : "";
    const matchingDocument = documents.find((document) => document.id === documentId)
      ?? documents.find((document) => document.fileName === item.title && document.clientName === item.label);

    if (matchingDocument) {
      onOpenDocument(matchingDocument);
      return;
    }

    const matchingClient = clientRows.find((row) => row.clientName === item.label);
    onClientSelect(matchingClient?.clientId || selectedClientId);
  }

  if (nextPresentation) {
    const reviewDocuments = documents.filter((document) => document.status === REVIEW_STATUS);
    const invoiceReviewCount = reviewDocuments.filter((document) => ["purchase_invoice", "sales_invoice"].includes(document.intakeCategory)).length;
    const bankReviewCount = reviewDocuments.filter((document) => document.intakeCategory === "bank_statement").length;
    const otherReviewCount = Math.max(0, reviewDocuments.length - invoiceReviewCount - bankReviewCount);
    const inProgressCount = documents.filter((document) => IN_PROGRESS_STATUSES.has(document.status)).length;
    const readyCount = documents.filter((document) => READY_STATUSES.has(document.status)).length;
    const agentHelpCount = reviewDocuments.filter((document) => (
      Boolean(document.aiGateReason)
      || Boolean(document.accountantActionHint)
      || Boolean(document.reviewBlockers?.length)
      || Boolean(document.aiRiskFlags?.length)
    )).length;
    const activities = activityItems(documents);
    const visibleClients = [...clientRows]
      .sort((a, b) => (b.cancellationCount + b.pendingReviewCount + b.inProgressCount) - (a.cancellationCount + a.pendingReviewCount + a.inProgressCount))
      .slice(0, 5);
    const reviewBreakdown = reviewDocuments.length
      ? `${invoiceReviewCount} fatura · ${bankReviewCount} banka · ${otherReviewCount} diğer`
      : "İstisna yok";
    const initials = resume?.clientName
      ? resume.clientName.split(/\s+/).slice(0, 2).map((word) => word.slice(0, 1)).join("").toLocaleUpperCase("tr-TR")
      : "FM";

    return (
      <section className="portal-next-home-page">
        <header className="portal-next-home-head">
          <div>
            <h1>Bugün ilgilenmen gerekenler</h1>
            <p>Tüm ofisin çalışma özeti. Sorunsuz işler arkada ilerler; önce istisnalar.</p>
          </div>
          <button className="primary portal-next-home-workspace-button" onClick={onOpenWorkspace} type="button">Çalışma Masasına Git</button>
        </header>

        <section className="portal-next-home-metrics" aria-label="Ofis dönem özeti">
          <article className={reviewDocuments.length ? "attention" : ""}>
            <span>Kontrol gerekli</span><strong>{isLoading ? "…" : reviewDocuments.length}</strong><small>{reviewBreakdown}</small>
          </article>
          <article><span>İşleniyor</span><strong>{isLoading ? "…" : inProgressCount}</strong><small>Arka planda devam ediyor</small></article>
          <article><span>Hazır</span><strong>{isLoading ? "…" : readyCount}</strong><small>Onay / çıktı aşamasında</small></article>
          <article><span>Bu dönem</span><strong>{isLoading ? "…" : documents.length}</strong><small>Toplam kayıt</small></article>
        </section>

        <div className="portal-next-home-grid">
          <div className="portal-next-home-main-column">
            <article className="portal-next-home-card portal-next-home-priority-card">
              <header><strong>Öncelikli çalışma</strong><span className={reviewDocuments.length ? "portal-next-home-pill warn" : "portal-next-home-pill ok"}>{reviewDocuments.length} kontrol</span></header>
              <div className="portal-next-home-card-body">
                <div className="portal-next-home-resume">
                  <div className="portal-next-home-resume-main">
                    <span>{initials}</span>
                    <div>
                      <strong>Kaldığın yerden devam et</strong>
                      <small>{resume ? `${resume.clientName} · ${longPeriodLabel(resume.period)} · ${resume.completedCount} / ${resume.totalCount} tamamlandı` : "Henüz kayıtlı bir çalışma yok."}</small>
                    </div>
                  </div>
                  <button className="secondary" disabled={!resume} onClick={onResume} type="button">Devam et →</button>
                </div>

                {invoiceReviewCount ? (
                  <div className="portal-next-home-task-row"><span className="portal-next-home-dot danger" /><div><strong>{invoiceReviewCount} fatura muhasebe kararı</strong><small>Hesap / cari seçimi kontrol bekliyor</small></div><button className="secondary compact" onClick={() => onOpenTask("invoices")} type="button">Aç</button></div>
                ) : null}
                {bankReviewCount ? (
                  <div className="portal-next-home-task-row"><span className="portal-next-home-dot danger" /><div><strong>{bankReviewCount} banka hareketi</strong><small>Eşleşme veya sınıflandırma gerekiyor</small></div><button className="secondary compact" onClick={() => onOpenTask("bank_statements")} type="button">Aç</button></div>
                ) : null}
                {otherReviewCount ? (
                  <div className="portal-next-home-task-row"><span className="portal-next-home-dot warn" /><div><strong>{otherReviewCount} diğer belge kontrol bekliyor</strong><small>Belge türüne göre müşavir incelemesi gerekiyor</small></div><button className="secondary compact" onClick={() => onOpenTask("other_documents")} type="button">Aç</button></div>
                ) : null}
                {agentHelpCount ? (
                  <div className="portal-next-home-task-row"><span className="portal-next-home-dot warn" /><div><strong>Muhasebe Ajanı {agentHelpCount} işlem için yardım istiyor</strong><small>Cari, hesap veya risk kontrolü müşavir kararı bekliyor</small></div><button className="secondary compact" onClick={onOpenAgents} type="button"><Bot aria-hidden="true" /> Gör</button></div>
                ) : null}
                {!reviewDocuments.length && !inProgressCount ? <p className="portal-next-home-empty">Bu dönem müşavir aksiyonu bekleyen iş yok.</p> : null}
              </div>
            </article>

            <article className="portal-next-home-card portal-next-home-clients-card">
              <header><strong>Mükellef durumu</strong><button className="ghost compact" onClick={onOpenClients} type="button">Tüm mükellefler</button></header>
              <div className="portal-next-home-client-table-wrap">
                <table>
                  <thead><tr><th>Mükellef</th><th>Belge</th><th>Kontrol</th><th>Hazır</th><th>Durum</th></tr></thead>
                  <tbody>
                    {visibleClients.map((row) => (
                      <tr key={row.clientId}>
                        <td data-label="Mükellef"><button className="portal-next-home-client-link" onClick={() => { onClientSelect(row.clientId); onOpenClients(); }} type="button">{row.clientName}</button></td>
                        <td data-label="Belge">{row.documentCount}</td>
                        <td data-label="Kontrol">{row.pendingReviewCount || "—"}</td>
                        <td data-label="Hazır">{row.exportReadyCount || "—"}</td>
                        <td data-label="Durum"><span className={`portal-next-home-pill ${clientStatusTone(row)}`}>{row.status}</span></td>
                      </tr>
                    ))}
                    {!isLoading && !visibleClients.length ? <tr><td colSpan={5}>Bu dönem için mükellef kaydı yok.</td></tr> : null}
                  </tbody>
                </table>
              </div>
            </article>
          </div>

          <aside className="portal-next-home-side-column">
            <article className="portal-next-home-card portal-next-home-office-card">
              <header><strong>Ofis özeti</strong><span>{officePeriod ? longPeriodLabel(officePeriod) : "Dönem seçilmedi"}</span></header>
              <div className="portal-next-home-office-list">
                <div><span>Toplam mükellef</span><strong>{isLoading ? "…" : dashboardMetrics.totalClients}</strong></div>
                <div><span>Bu ay belge yükleyen</span><strong>{isLoading ? "…" : dashboardMetrics.uploadedClients}</strong></div>
                <div><span>Henüz yüklemeyen</span><strong>{isLoading ? "…" : dashboardMetrics.notUploadedClients}</strong></div>
                <div><span>Tamamlanan kayıt</span><strong>{isLoading ? "…" : `${readyCount} / ${documents.length}`}</strong></div>
              </div>
            </article>

            <article className="portal-next-home-card portal-next-home-activity-card">
              <header><strong>Son aktiviteler</strong></header>
              <div className="portal-next-home-card-body">
                {activities.map((activity) => (
                  <div className="portal-next-home-activity-row" key={activity.id}>
                    <span className={`portal-next-home-dot ${activity.tone}`} />
                    <div><strong>{activity.title}</strong><small>{activityTime(activity.timestamp)}{activityTime(activity.timestamp) ? " · " : ""}{activity.detail}</small></div>
                  </div>
                ))}
                {!activities.length ? <p className="portal-next-home-empty">Bu dönem henüz aktivite oluşmadı.</p> : null}
              </div>
            </article>
          </aside>
        </div>
      </section>
    );
  }

  return (
    <section className="accountant-dashboard-page">
      <section className="office-dashboard dashboard-review-summary" aria-label="Bugünün iş özeti">
        <Metric icon={ClipboardCheck} label="Kontrol" value={isLoading ? "…" : dashboardMetrics.pendingReviewDocuments} />
        <Metric icon={FileSearch} label="Sırada" value={isLoading ? "…" : priorityItems.length} />
        <Metric icon={PackageCheck} label="Hazır" value={isLoading ? "…" : dashboardMetrics.exportReadyDocuments} />
      </section>

      <section className="dashboard-review-layout" aria-label="Müşavir iş masası">
        <section className="panel review-work-list" aria-labelledby="review-work-heading">
          <div className="dashboard-review-heading">
            <div>
              <h2 id="review-work-heading">Bugün bakılacak belgeler</h2>
              <p>Önce bu sırayı tamamlayın; detay ve öğrenme ekranları AI Ajanları altında kalır.</p>
            </div>
            <strong>{isLoading ? "…" : `${Math.min(priorityItems.length, 8)} iş`}</strong>
          </div>

          <div className="review-work-items">
            {priorityItems.slice(0, 8).map((item) => (
              <article className="review-work-row" key={item.id}>
                <FileSearch aria-hidden="true" />
                <div>
                  <strong>{item.title}</strong>
                  <span>{item.label}</span>
                  <p>{item.detail}</p>
                </div>
                <span className="review-status-chip">{item.statusLabel}</span>
                <button onClick={() => openPriorityItem(item)} type="button">İncele</button>
              </article>
            ))}
            {isLoading ? (
              <p className="empty" role="status" aria-live="polite">Çalışma alanı yükleniyor.</p>
            ) : !priorityItems.length ? (
              <p className="empty">Bugün müşavir aksiyonu bekleyen belge yok.</p>
            ) : null}
          </div>
        </section>

        <aside className="panel office-summary" aria-label="Ofis özeti">
          <div className="dashboard-review-heading">
            <div>
              <h2>Ofis özeti</h2>
              <p>İş sırası belge listesinden ilerler.</p>
            </div>
          </div>
          <dl>
            <div><dt><Users aria-hidden="true" /> Mükellef</dt><dd>{isLoading ? "…" : dashboardMetrics.totalClients}</dd></div>
            <div><dt><Upload aria-hidden="true" /> Yükleyen</dt><dd>{isLoading ? "…" : dashboardMetrics.uploadedClients}</dd></div>
            <div><dt><UserX aria-hidden="true" /> Yüklemeyen</dt><dd>{isLoading ? "…" : dashboardMetrics.notUploadedClients}</dd></div>
            <div><dt><MessageSquareWarning aria-hidden="true" /> Açık talep</dt><dd>{isLoading ? "…" : dashboardMetrics.openCancellationRequests}</dd></div>
          </dl>
        </aside>
      </section>
    </section>
  );
}
