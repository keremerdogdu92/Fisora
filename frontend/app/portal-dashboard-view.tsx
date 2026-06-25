import {
  ClipboardCheck,
  MessageSquareWarning,
  PackageCheck,
  Upload,
  Users,
  UserX,
} from "lucide-react";
import { ChartBars, Metric } from "./portal-shared";
import type { ChartRow, DashboardClientRow } from "./portal-types";

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
  funnelRows,
  intakeDistribution,
  onClientSelect,
  selectedClientId,
  uploadTrackingRows,
}: {
  clientRows: DashboardClientRow[];
  dashboardMetrics: DashboardMetrics;
  funnelRows: ChartRow[];
  intakeDistribution: ChartRow[];
  onClientSelect: (clientId: string) => void;
  selectedClientId: string;
  uploadTrackingRows: ChartRow[];
}) {
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
