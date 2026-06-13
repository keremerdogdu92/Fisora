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
        <Metric label="Mukellef" value={dashboardMetrics.totalClients} />
        <Metric label="Yukleyen" value={dashboardMetrics.uploadedClients} />
        <Metric label="Yuklemeyen" value={dashboardMetrics.notUploadedClients} />
        <Metric label="Kontrol" value={dashboardMetrics.pendingReviewDocuments} />
        <Metric label="Cikti hazir" value={dashboardMetrics.exportReadyDocuments} />
        <Metric label="Talep" value={dashboardMetrics.openCancellationRequests} />
      </section>
      <section className="dashboard-visual-grid">
        <ChartBars title="Belge turu" rows={intakeDistribution} />
        <ChartBars title="Durum hunisi" rows={funnelRows} />
        <ChartBars title="Yukleme takibi" rows={uploadTrackingRows} />
      </section>
      <section className="panel">
        <div className="section-heading">
          <span>Mukellef takibi</span>
          <strong>Yukleme ve kontrol sirasi</strong>
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
              <em>{row.documentCount} belge / {row.pendingReviewCount} kontrol / {row.exportReadyCount} hazir</em>
            </button>
          ))}
        </div>
      </section>
    </section>
  );
}
