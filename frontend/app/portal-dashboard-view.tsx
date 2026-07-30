import {
  ClipboardCheck,
  FileSearch,
  MessageSquareWarning,
  PackageCheck,
  Upload,
  Users,
  UserX,
} from "lucide-react";
import { Metric } from "./portal-shared";
import type { DashboardClientRow, PilotDocument } from "./portal-types";

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

export function AccountantDashboard({
  clientRows,
  dashboardMetrics,
  documents,
  isLoading,
  onClientSelect,
  onOpenDocument,
  priorityItems,
  selectedClientId,
}: {
  clientRows: DashboardClientRow[];
  dashboardMetrics: DashboardMetrics;
  documents: PilotDocument[];
  isLoading: boolean;
  onClientSelect: (clientId: string) => void;
  onOpenDocument: (document: PilotDocument) => void;
  priorityItems: PriorityWorkItem[];
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
            <div>
              <dt><Users aria-hidden="true" /> Mükellef</dt>
              <dd>{isLoading ? "…" : dashboardMetrics.totalClients}</dd>
            </div>
            <div>
              <dt><Upload aria-hidden="true" /> Yükleyen</dt>
              <dd>{isLoading ? "…" : dashboardMetrics.uploadedClients}</dd>
            </div>
            <div>
              <dt><UserX aria-hidden="true" /> Yüklemeyen</dt>
              <dd>{isLoading ? "…" : dashboardMetrics.notUploadedClients}</dd>
            </div>
            <div>
              <dt><MessageSquareWarning aria-hidden="true" /> Açık talep</dt>
              <dd>{isLoading ? "…" : dashboardMetrics.openCancellationRequests}</dd>
            </div>
          </dl>
        </aside>
      </section>
    </section>
  );
}
