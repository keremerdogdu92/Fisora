import { groupedReviewReasons } from "./portal-normalization";
import { Info, Metric } from "./portal-shared";
import type { AiCapacityAgentView, AiCapacityView, ExportBasketItem, ExportMode, PilotData, PilotDocument, PilotReadinessView } from "./portal-types";

type RetentionDocumentView = Record<string, unknown>;

export function ExportBasketView({
  documents,
  exportBasket,
  exportMode,
  exportStatus,
  exportType,
  onMarkPackaged,
  periodLabel,
  setExportMode,
  setExportType,
}: {
  documents: PilotDocument[];
  exportBasket: ExportBasketItem[];
  exportMode: ExportMode;
  exportStatus: string;
  exportType: string;
  onMarkPackaged: () => void;
  periodLabel: (period: string) => string;
  setExportMode: (value: ExportMode) => void;
  setExportType: (value: string) => void;
}) {
  const totalDocuments = exportBasket.reduce((sum, item) => sum + item.documentCount, 0);
  const pendingReviewDocuments = documents.filter((document) => document.status === "review_required");
  const reviewReasonGroups = groupedReviewReasons(pendingReviewDocuments);
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
      <div className="inline-actions">
        <button className={exportType === "zirve_mapping_csv" ? "active-action" : ""} onClick={() => setExportType("zirve_mapping_csv")} type="button">Zirve mapping CSV</button>
        <button className={exportType === "zirve_universal_csv" ? "active-action" : ""} onClick={() => setExportType("zirve_universal_csv")} type="button">Universal CSV</button>
        <button className={exportType === "zirve_trial_csv" ? "active-action" : ""} onClick={() => setExportType("zirve_trial_csv")} type="button">Trial CSV</button>
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
        {!exportBasket.length && pendingReviewDocuments.length ? (
          <div className="basket-row blocked-export-row">
            <div>
              <strong>Çıktı hazır değil</strong>
              <span>Önce kontrol bekleyen belgeleri ve onboarding eksiklerini tamamlayın.</span>
              {reviewReasonGroups.length ? (
                <div className="review-breakdown-list">
                  {reviewReasonGroups.slice(0, 4).map((group) => (
                    <span key={group.code}>{group.label}: {group.count}</span>
                  ))}
                </div>
              ) : null}
            </div>
            <span className="status review_required">Kontrol gerekli</span>
          </div>
        ) : null}
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
  onDeleteRetentionDocuments,
  onExtendRetentionDocuments,
  onPreviewRetention,
  readinessView,
  retentionDocuments,
  retentionStatus,
  source,
}: {
  aiCapacity?: AiCapacityView;
  data: PilotData;
  localFallbackAllowed: boolean;
  onDeleteRetentionDocuments: () => void;
  onExtendRetentionDocuments: () => void;
  onPreviewRetention: () => void;
  readinessView: PilotReadinessView;
  retentionDocuments: RetentionDocumentView[];
  retentionStatus: string;
  source: string;
}) {
  const agents = aiCapacity?.agents ?? [];
  const documentQueries = aiCapacity?.totals?.document_queries ?? "Ölçülemiyor";
  const internetResearches = aiCapacity?.totals?.internet_researches ?? "Ölçülemiyor";
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
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Belge saklama</h2>
            <span>90 gun sonunda silme veya 90 gun uzatma karari.</span>
          </div>
          <button className="secondary" onClick={onPreviewRetention} type="button">Onizle</button>
        </div>
        <div className="summary-grid compact">
          <Metric label="Aksiyon bekleyen" value={retentionDocuments.length} />
          <Metric label="Toplam belge" value={data.documents.length} />
        </div>
        <div className="basket-list">
          {retentionDocuments.slice(0, 6).map((document) => {
            const documentKey = String(document.document_key || document.document_ref || "");
            return (
              <div className="basket-row" key={documentKey}>
                <div>
                  <strong>{String(document.original_file_name || documentKey || "Belge")}</strong>
                  <span>{String(document.client_id || "")} / {String(document.expires_at || "")}</span>
                </div>
                <span className={`status ${document.storage_status === "expired" ? "cancel_requested" : "queued"}`}>
                  {String(document.storage_status || "bekliyor")}
                </span>
              </div>
            );
          })}
          {!retentionDocuments.length ? (
            <div className="basket-row">
              <div>
                <strong>Saklama onizlemesi bekleniyor</strong>
                <span>Once sureci gorelim; silme veya uzatma ondan sonra uygulanir.</span>
              </div>
              <span className="status queued">Bekliyor</span>
            </div>
          ) : null}
        </div>
        <div className="inline-actions">
          <button className="secondary" disabled={!retentionDocuments.length} onClick={onExtendRetentionDocuments} type="button">90 gun uzat</button>
          <button className="danger" disabled={!retentionDocuments.length} onClick={onDeleteRetentionDocuments} type="button">Onayla sil</button>
        </div>
        <p className="decision-status">{retentionStatus || "Musteri indirme yetkisi acilmadan, operasyon tarafinda kontrollu saklama karari verilir."}</p>
      </div>
    </section>
  );
}

function agentStatusLabel(status = "") {
  if (status === "ready") return "Hazır";
  if (status === "configured") return "Tanımlı";
  if (status === "disabled") return "Kapalı";
  if (status === "missing_key") return "Eksik";
  if (status === "configuration_error") return "Son kontrolde hata";
  if (status === "last_check_error") return "Kontrol hatası";
  return "Bilinmiyor";
}

function agentStatusClass(status = "") {
  if (status === "ready" || status === "configured") return "export_ready";
  if (status === "disabled" || status === "missing_key") return "review_required";
  if (status === "configuration_error" || status === "last_check_error") return "cancel_requested";
  return "queued";
}

function agentCapacityText(agent: AiCapacityAgentView) {
  const documents = agent.estimates?.document_queries ?? 0;
  const researches = agent.estimates?.internet_researches ?? 0;
  if (agent.kind === "research") {
    if (agent.status === "disabled") return "Araştırma ajanı kapalı.";
    if (agent.status === "missing_key") return "Araştırma bağlantısı eksik.";
    if (agent.status === "configuration_error") return "Araştırma ajanı son kontrolde hata verdi.";
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
