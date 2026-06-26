import {
  ClipboardCheck,
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

export function AccountantDashboard({
  clientRows,
  dashboardMetrics,
  documents,
  funnelRows,
  intakeDistribution,
  onClientSelect,
  selectedClientId,
  uploadTrackingRows,
}: {
  clientRows: DashboardClientRow[];
  dashboardMetrics: DashboardMetrics;
  documents: PilotDocument[];
  funnelRows: ChartRow[];
  intakeDistribution: ChartRow[];
  onClientSelect: (clientId: string) => void;
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
          {clientRows.map((row) => (
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
