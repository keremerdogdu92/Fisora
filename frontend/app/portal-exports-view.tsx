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
          <h2>Ã‡Ä±ktÄ± listesi</h2>
          <span>MÃ¼kellefler tamamlandÄ±kÃ§a buraya eklenir.</span>
        </div>
        <div className="inline-actions">
          <button className={exportMode === "bulk" ? "active-action" : ""} onClick={() => setExportMode("bulk")} type="button">Toplu paket</button>
          <button className={exportMode === "by_client" ? "active-action" : ""} onClick={() => setExportMode("by_client")} type="button">MÃ¼kellef bazlÄ±</button>
        </div>
      </div>
      <div className="summary-grid compact">
        <Metric label="MÃ¼kellef" value={exportBasket.length} />
        <Metric label="Belge/fiÅŸ" value={totalDocuments} />
      </div>
      <div className="basket-list">
        {exportBasket.map((item) => (
          <div className="basket-row" key={item.id}>
            <div>
              <strong>{item.clientName}</strong>
              <span>{periodLabel(item.period)} / {item.documentCount} kayÄ±t</span>
            </div>
            <span className={`status ${item.status === "packaged" ? "exported" : "export_added"}`}>
              {item.status === "packaged" ? "Paketlendi" : "HazÄ±r"}
            </span>
          </div>
        ))}
      </div>
      <button className="primary" onClick={onMarkPackaged} type="button">Ã‡Ä±ktÄ± seÃ§imini hazÄ±rla</button>
      <p className="decision-status">{exportStatus || "Ay kapanÄ±ÅŸÄ± tek tÄ±k hedefi iÃ§in Ã§Ä±ktÄ± sepeti ÅŸimdiden ayrÄ± tutuldu."}</p>
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
        <h2>KapalÄ± kullanÄ±m durumu</h2>
        <Info label="Saha kullanÄ±mÄ±" value={readinessView.statusLabel} />
        <Info label="Production" value={readinessView.productionLabel} />
        <Info label="Teklif" value={readinessView.offerLabel} />
        <Info label="Ã‡Ä±ktÄ±" value={readinessView.exportLabel} />
        <Info label="Zirve" value={readinessView.zirveLabel} />
      </div>
      <div className="panel">
        <h2>Okunan kaynak</h2>
        <Info label="Kaynak" value={source} />
        <Info label="MÃ¼kellef" value={String(data.clients.length)} />
        <Info label="Belge" value={String(data.documents.length)} />
        <Info label="Ä°ptal talebi" value={String(data.cancellationRequests.length)} />
      </div>
      <div className="panel">
        <h2>Operasyon kapilari</h2>
        <Info label="Auth" value={readinessView.authLabel} />
        <Info label="Store" value={readinessView.storeLabel} />
        <Info label="AI" value={readinessView.aiLabel} />
        <Info label="Blokaj" value={readinessView.blocking.length ? readinessView.blocking.join(", ") : "Yok"} />
        <Info label="Uyari" value={readinessView.warnings.length ? readinessView.warnings.join(", ") : "Yok"} />
        {localFallbackAllowed ? (
          <p className="decision-status">Lokal Ã§alÄ±ÅŸma verisi aÃ§Ä±k.</p>
        ) : null}
      </div>
    </section>
  );
}
