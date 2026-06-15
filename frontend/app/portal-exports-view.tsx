import { Info, Metric } from "./portal-shared";
import type { ExportBasketItem, ExportMode, PilotData, PilotReadinessView } from "./portal-types";

export function ExportBasketView({
  exportBasket,
  exportMode,
  exportStatus,
  onMarkPackaged,
  periodLabel,
  setExportMode,
}: {
  exportBasket: ExportBasketItem[];
  exportMode: ExportMode;
  exportStatus: string;
  onMarkPackaged: () => void;
  periodLabel: (period: string) => string;
  setExportMode: (value: ExportMode) => void;
}) {
  const totalDocuments = exportBasket.reduce((sum, item) => sum + item.documentCount, 0);
  return (
    <section className="panel export-workspace">
      <div className="panel-heading">
        <div>
          <h2>Çıktı listesi</h2>
          <span>Mükellefler tamamlandıkça buraya eklenir.</span>
        </div>
        <div className="inline-actions">
          <button className={exportMode === "bulk" ? "active-action" : ""} onClick={() => setExportMode("bulk")} type="button">Toplu paket</button>
          <button className={exportMode === "by_client" ? "active-action" : ""} onClick={() => setExportMode("by_client")} type="button">Mükellef bazlı</button>
        </div>
      </div>
      <div className="summary-grid compact">
        <Metric label="Mükellef" value={exportBasket.length} />
        <Metric label="Belge/fiş" value={totalDocuments} />
      </div>
      <div className="basket-list">
        {exportBasket.map((item) => (
          <div className="basket-row" key={item.id}>
            <div>
              <strong>{item.clientName}</strong>
              <span>{periodLabel(item.period)} / {item.documentCount} kayıt</span>
            </div>
            <span className={`status ${item.status === "packaged" ? "exported" : "export_added"}`}>
              {item.status === "packaged" ? "Paketlendi" : "Hazır"}
            </span>
          </div>
        ))}
      </div>
      <button className="primary" onClick={onMarkPackaged} type="button">Çıktı seçimini hazırla</button>
      <p className="decision-status">{exportStatus || "Ay kapanışı tek tık hedefi için çıktı sepeti şimdiden ayrı tutuldu."}</p>
    </section>
  );
}

export function OperationsView({
  data,
  localFallbackAllowed,
  readinessView,
  source,
}: {
  data: PilotData;
  localFallbackAllowed: boolean;
  readinessView: PilotReadinessView;
  source: string;
}) {
  return (
    <section className="operations-grid">
      <div className="panel">
        <h2>Kapalı kullanım durumu</h2>
        <Info label="Saha kullanımı" value={readinessView.statusLabel} />
        <Info label="Production" value={readinessView.productionLabel} />
        <Info label="Gerçek veri" value={readinessView.realDataLabel} />
        <Info label="Erişim" value={readinessView.realDataAccessLabel} />
        <Info label="Teklif" value={readinessView.offerLabel} />
        <Info label="Çıktı" value={readinessView.exportLabel} />
        <Info label="Zirve" value={readinessView.zirveLabel} />
      </div>
      <div className="panel">
        <h2>Okunan kaynak</h2>
        <Info label="Kaynak" value={source} />
        <Info label="Mükellef" value={String(data.clients.length)} />
        <Info label="Belge" value={String(data.documents.length)} />
        <Info label="İptal talebi" value={String(data.cancellationRequests.length)} />
      </div>
      <div className="panel">
        <h2>Operasyon kapıları</h2>
        <Info label="Auth" value={readinessView.authLabel} />
        <Info label="Store" value={readinessView.storeLabel} />
        <Info label="AI" value={readinessView.aiLabel} />
        <Info
          label="Gerçek veri blokajı"
          value={readinessView.realDataBlocking.length ? readinessView.realDataBlocking.join(", ") : "Yok"}
        />
        <Info label="Blokaj" value={readinessView.blocking.length ? readinessView.blocking.join(", ") : "Yok"} />
        <Info label="Uyarı" value={readinessView.warnings.length ? readinessView.warnings.join(", ") : "Yok"} />
        {localFallbackAllowed ? (
          <p className="decision-status">Lokal çalışma verisi açık.</p>
        ) : null}
      </div>
    </section>
  );
}
