import { Info, Metric } from "./portal-shared";
import type { AiCapacityAgentView, AiCapacityView, ExportBasketItem, ExportMode, PilotData, PilotReadinessView } from "./portal-types";

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
  aiCapacity,
  data,
  localFallbackAllowed,
  readinessView,
  source,
}: {
  aiCapacity?: AiCapacityView;
  data: PilotData;
  localFallbackAllowed: boolean;
  readinessView: PilotReadinessView;
  source: string;
}) {
  const agents = aiCapacity?.agents ?? [];
  const documentQueries = aiCapacity?.totals?.document_queries ?? 0;
  const internetResearches = aiCapacity?.totals?.internet_researches ?? 0;
  return (
    <section className="operations-grid">
      <div className="panel">
        <h2>AI ajanı kapasitesi</h2>
        <div className="summary-grid compact">
          <Metric label="Belge taslağı" value={documentQueries} />
          <Metric label="İnternet araştırması" value={internetResearches} />
        </div>
        <div className="basket-list">
          {agents.length ? agents.map((agent) => (
            <div className="basket-row" key={agent.slot || agent.label}>
              <div>
                <strong>{agent.label}</strong>
                <span>{agentCapacityText(agent)}</span>
              </div>
              <span className={`status ${agentStatusClass(agent.status)}`}>{agentStatusLabel(agent.status)}</span>
            </div>
          )) : (
            <div className="basket-row">
              <div>
                <strong>Ajan kapasitesi</strong>
                <span>Sunucu bilgisi bekleniyor.</span>
              </div>
              <span className="status queued">Bekleniyor</span>
            </div>
          )}
        </div>
        <p className="decision-status">
          {aiCapacity?.generated_at ? `Son güncelleme: ${formatCapacityDate(aiCapacity.generated_at)}.` : "Kapasite bilgisi alınamadı."}
        </p>
      </div>
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

function agentStatusLabel(status = "") {
  if (status === "ready") return "Hazır";
  if (status === "configured") return "Tanımlı";
  if (status === "disabled") return "Kapalı";
  if (status === "missing_key") return "Eksik";
  if (status === "last_check_error") return "Kontrol hatası";
  return "Bilinmiyor";
}

function agentStatusClass(status = "") {
  if (status === "ready" || status === "configured") return "export_ready";
  if (status === "disabled" || status === "missing_key") return "review_required";
  if (status === "last_check_error") return "cancel_requested";
  return "queued";
}

function agentCapacityText(agent: AiCapacityAgentView) {
  const documents = agent.estimates?.document_queries ?? 0;
  const researches = agent.estimates?.internet_researches ?? 0;
  if (agent.kind === "research") {
    if (agent.status === "disabled") return "Araştırma ajanı kapalı.";
    if (agent.status === "missing_key") return "Araştırma bağlantısı eksik.";
    return `Yaklaşık ${researches} internet araştırması.`;
  }
  const daily = agent.daily_requests?.remaining;
  if (typeof daily === "number") {
    return `Yaklaşık ${documents} belge taslağı / günlük kalan istek ${daily}.`;
  }
  return documents ? `Yaklaşık ${documents} belge taslağı.` : "Kapasite son gerçek kullanımdan sonra netleşir.";
}

function formatCapacityDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("tr-TR");
}
