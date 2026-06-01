"use client";

import { useEffect, useMemo, useState } from "react";
import { fallbackReviewData } from "./demo-data";

type DraftLine = {
  account_code: string;
  description: string;
  debit: string;
  credit: string;
};

type InvoiceRow = {
  chartFileName: string;
  fileName: string;
  providerHint: string;
  invoiceType: string;
  issueDate: string;
  payableTotal: string;
  vatRates: string[];
  status: string;
  draftQuality: string;
  isBalanced: boolean;
  riskFlags: string[];
  parseNotes: string[];
  reviewReasonCodes: string[];
  productLineHint: string;
  productCategory: string;
  productConfidence: number;
  businessRelevanceStatus: string;
  businessRelevanceConfidence: number;
  businessRelevanceReason: string;
  businessRelevanceEvidence: string[];
  aiClassificationUsed: boolean;
  aiClassificationProvider: string;
  aiClassificationSkippedReason: string;
  aiClassificationReason: string;
  aiEstimatedInputChars: number;
  exportStatus: string;
  selectedExpenseAccount: string;
  selectedVatAccount: string;
  selectedSupplierAccount: string;
  counterpartyMatchCode: string;
  counterpartyMatchConfidence: number;
  counterpartyMatchReason: string;
  draftLines: DraftLine[];
};

type ChartRun = {
  chartFileName: string;
  accountCount: number;
  detailAccountCount: number;
  customerCandidateCount: number;
  supplierCandidateCount: number;
  hasPurchaseVat191: boolean;
  hasSalesVat391: boolean;
  autoReadyCount: number;
  reviewRequiredCount: number;
  cannotDraftCount: number;
  selectedAccounts: Record<string, unknown>;
};

type ReviewData = {
  generatedFrom: string;
  summary: {
    chartRunCount: number;
    invoiceRowCount: number;
    autoReadyCount: number;
    reviewRequiredCount: number;
    cannotDraftCount: number;
    allDraftsBalanced: boolean;
  };
  chartRuns: ChartRun[];
  invoiceRows: InvoiceRow[];
};

type ViewMode = "all" | "review" | "export";
type DecisionAction = "approve" | "approve_with_changes" | "exclude_export" | "out_of_scope" | "wrong_counterparty";

type LocalDecision = {
  action: DecisionAction;
  label: string;
  learningScope: string;
};

const statusLabels: Record<string, string> = {
  auto_ready: "Otomatik hazir",
  review_required: "Kontrol gerekli",
  cannot_draft: "Taslak yok",
};

const draftQualityLabels: Record<string, string> = {
  full_basic_purchase: "Tam temel alis fisi",
  partial_review_required: "Hazir ama kontrol gerekli",
  gross_balanced_needs_vat_split: "Brut dengeli, KDV ayrimi gerekli",
  no_positive_amount: "Pozitif tutar yok",
};

const relevanceLabels: Record<string, string> = {
  uygun: "Uygun",
  genel_gider: "Genel gider",
  supheli: "Supheli",
  is_alani_disi: "Is alani disi",
};

const exportStatusLabels: Record<string, string> = {
  export_ready: "Export hazir",
  review_required: "Kontrol gerekli",
  blocked: "Bloklandi",
  rejected: "Reddedildi",
};

const viewLabels: Record<ViewMode, string> = {
  all: "Belgeler",
  review: "Review kuyrugu",
  export: "Export hazir",
};

const decisions: Record<DecisionAction, LocalDecision> = {
  approve: {
    action: "approve",
    label: "Onayla",
    learningScope: "Ayni cari ve ayni kategori tekrar ederse guven puani artar.",
  },
  approve_with_changes: {
    action: "approve_with_changes",
    label: "Duzelt ve onayla",
    learningScope: "Duzeltilen hesap/cari mukellef ozel kural adayi olur.",
  },
  exclude_export: {
    action: "exclude_export",
    label: "Export disi birak",
    learningScope: "Benzer risk bayraklari sonraki belgelerde export disi onerilir.",
  },
  out_of_scope: {
    action: "out_of_scope",
    label: "Is alani disi",
    learningScope: "Urun kategorisi bu mukellefte kontrol veya red onerisine tasinir.",
  },
  wrong_counterparty: {
    action: "wrong_counterparty",
    label: "Cari yanlis",
    learningScope: "Cari eslestirme guveni dusurulur ve yeni cari secimi istenir.",
  },
};

function formatStatus(status: string) {
  return statusLabels[status] ?? status;
}

function formatDraftQuality(value: string) {
  return draftQualityLabels[value] ?? value;
}

function formatRelevance(value: string) {
  return relevanceLabels[value] ?? (value || "-");
}

function formatExportStatus(value: string) {
  return exportStatusLabels[value] ?? (value || "-");
}

function rowKey(row: InvoiceRow) {
  return `${row.chartFileName}:${row.fileName}`;
}

function exportGateReason(row: InvoiceRow) {
  if (!row.isBalanced) return "Fis dengeli degil.";
  if (!row.counterpartyMatchCode || row.counterpartyMatchReason === "not_found") return "Cari eslesmesi net degil.";
  if (row.reviewReasonCodes.length) return row.reviewReasonCodes.join(", ");
  if (row.businessRelevanceStatus === "is_alani_disi") return "Kalem faaliyet disi riski tasiyor.";
  if (row.businessRelevanceStatus === "supheli") return "Kalem faaliyet profiliyle net eslesmedi.";
  if (row.exportStatus !== "export_ready") return "Musavir politikasi export onayi istiyor.";
  return "Export paketine alinabilir.";
}

function formatAiStatus(row: InvoiceRow) {
  if (row.aiClassificationUsed) return `AI: ${row.aiClassificationProvider || "provider"} kullanildi`;
  return `AI yok: ${row.aiClassificationSkippedReason || "statik akış"}`;
}

export default function Home() {
  const [data, setData] = useState<ReviewData>(fallbackReviewData as ReviewData);
  const [source, setSource] = useState("demo fallback");
  const [activeChart, setActiveChart] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("review");
  const [decisionLog, setDecisionLog] = useState<Record<string, LocalDecision>>({});

  useEffect(() => {
    let cancelled = false;
    fetch("/local-review-data.json", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error("No local data");
        }
        return response.json() as Promise<ReviewData>;
      })
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setSource(payload.generatedFrom);
        setActiveChart(payload.chartRuns[0]?.chartFileName ?? "");
      })
      .catch(() => {
        if (cancelled) return;
        setSource("demo fallback");
        setActiveChart(fallbackReviewData.chartRuns[0]?.chartFileName ?? "");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const chartInvoices = useMemo(() => {
    return data.invoiceRows.filter((row) => !activeChart || row.chartFileName === activeChart);
  }, [activeChart, data.invoiceRows]);

  const visibleInvoices = useMemo(() => {
    if (viewMode === "review") return chartInvoices.filter((row) => row.exportStatus !== "export_ready");
    if (viewMode === "export") return chartInvoices.filter((row) => row.exportStatus === "export_ready");
    return chartInvoices;
  }, [chartInvoices, viewMode]);

  const selectedInvoice = useMemo(() => {
    return visibleInvoices.find((row) => rowKey(row) === selectedKey) ?? visibleInvoices[0];
  }, [selectedKey, visibleInvoices]);

  const exportReadyCount = useMemo(() => {
    return chartInvoices.filter((row) => row.exportStatus === "export_ready").length;
  }, [chartInvoices]);

  const reviewQueueCount = useMemo(() => {
    return chartInvoices.filter((row) => row.exportStatus !== "export_ready").length;
  }, [chartInvoices]);

  const activeDecision = selectedInvoice ? decisionLog[rowKey(selectedInvoice)] : undefined;

  function setDecision(action: DecisionAction) {
    if (!selectedInvoice) return;
    setDecisionLog((current) => ({
      ...current,
      [rowKey(selectedInvoice)]: decisions[action],
    }));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="label">Fisora MVP Portal</p>
          <h1>Mukellef belge ve fis review console</h1>
        </div>
        <div className="source">{source}</div>
      </header>

      <section className="portal-strip" aria-label="Mukellef portal ozeti">
        <Info label="Mukellef" value="Demo Isitme Merkezi" />
        <Info label="Yetki" value="Musavir review" />
        <Info label="Review kuyrugu" value={String(reviewQueueCount)} />
        <Info label="Export hazir" value={String(exportReadyCount)} />
      </section>

      <section className="metrics" aria-label="Ozet">
        <Metric label="Hesap plani denemesi" value={data.summary.chartRunCount} />
        <Metric label="Belge sayisi" value={chartInvoices.length} />
        <Metric label="Export hazir" value={exportReadyCount} tone="good" />
        <Metric label="Kontrol gerekli" value={reviewQueueCount} tone="warn" />
        <Metric label="Taslak eksik" value={data.summary.cannotDraftCount} tone="bad" />
      </section>

      <section className="layout">
        <aside className="sidebar" aria-label="Mukellef ve hesap planlari">
          <h2>Mukellef Secimi</h2>
          <div className="client-card">
            <strong>Demo Isitme Merkezi</strong>
            <span>VKN/TCKN eslesmis, hesap plani yuklu</span>
          </div>

          <h2>Hesap Planlari</h2>
          <div className="chart-list">
            {data.chartRuns.map((chart) => (
              <button
                className={chart.chartFileName === activeChart ? "chart-button active" : "chart-button"}
                key={chart.chartFileName}
                onClick={() => {
                  setActiveChart(chart.chartFileName);
                  setSelectedKey("");
                }}
                type="button"
              >
                <strong>{chart.chartFileName}</strong>
                <span>
                  {chart.detailAccountCount} detay, {chart.supplierCandidateCount} satici
                </span>
              </button>
            ))}
          </div>
          <ChartDetails chart={data.chartRuns.find((chart) => chart.chartFileName === activeChart)} />
        </aside>

        <section className="table-panel" aria-label="Belge listesi">
          <div className="panel-head">
            <div>
              <h2>{viewLabels[viewMode]}</h2>
              <span>{visibleInvoices.length} kayit</span>
            </div>
            <div className="tabbar" role="tablist" aria-label="Belge filtreleri">
              {(Object.keys(viewLabels) as ViewMode[]).map((mode) => (
                <button
                  aria-selected={viewMode === mode}
                  className={viewMode === mode ? "tab active" : "tab"}
                  key={mode}
                  onClick={() => {
                    setViewMode(mode);
                    setSelectedKey("");
                  }}
                  role="tab"
                  type="button"
                >
                  {viewLabels[mode]}
                </button>
              ))}
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fatura</th>
                  <th>Saglayici</th>
                  <th>Tutar</th>
                  <th>Uygunluk</th>
                  <th>Cari</th>
                  <th>Export</th>
                  <th>Kontrol nedeni</th>
                </tr>
              </thead>
              <tbody>
                {visibleInvoices.map((row) => {
                  const key = rowKey(row);
                  return (
                    <tr
                      className={selectedInvoice && rowKey(selectedInvoice) === key ? "selected" : ""}
                      key={key}
                      onClick={() => setSelectedKey(key)}
                    >
                      <td>
                        <strong>{row.fileName}</strong>
                        <span className="subtle">{row.issueDate || "-"}</span>
                      </td>
                      <td>{row.providerHint || "Bilinmiyor"}</td>
                      <td>{row.payableTotal || "-"}</td>
                      <td>{formatRelevance(row.businessRelevanceStatus)}</td>
                      <td>
                        {row.counterpartyMatchCode || "-"}
                        <span className="subtle">{row.counterpartyMatchReason}</span>
                      </td>
                      <td>
                        <span className={`status ${row.exportStatus}`}>{formatExportStatus(row.exportStatus)}</span>
                      </td>
                      <td>{exportGateReason(row)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="detail-panel" aria-label="Karar ve fis taslagi">
          <h2>Karar Paneli</h2>
          {selectedInvoice ? (
            <>
              <div className="detail-grid">
                <Info label="Fatura" value={selectedInvoice.fileName} />
                <Info label="Durum" value={formatStatus(selectedInvoice.status)} />
                <Info label="Taslak" value={formatDraftQuality(selectedInvoice.draftQuality)} />
                <Info label="Urun sinyali" value={selectedInvoice.productLineHint || "-"} />
                <Info
                  label="Kategori"
                  value={`${selectedInvoice.productCategory || "-"} (${selectedInvoice.productConfidence ?? 0})`}
                />
                <Info
                  label="Uygunluk"
                  value={`${formatRelevance(selectedInvoice.businessRelevanceStatus)} (${selectedInvoice.businessRelevanceConfidence ?? 0})`}
                />
                <Info label="AI sinifi" value={formatAiStatus(selectedInvoice)} />
                <Info label="AI maliyet sinyali" value={`${selectedInvoice.aiEstimatedInputChars ?? 0} karakter`} />
                <Info label="Export" value={formatExportStatus(selectedInvoice.exportStatus)} />
                <Info
                  label="Cari eslesme"
                  value={`${selectedInvoice.counterpartyMatchCode || "-"} (${selectedInvoice.counterpartyMatchConfidence ?? 0})`}
                />
              </div>

              <p className="reason">{selectedInvoice.businessRelevanceReason || "Uygunluk gerekcesi yok."}</p>
              {selectedInvoice.aiClassificationReason ? (
                <p className="reason">{selectedInvoice.aiClassificationReason}</p>
              ) : null}
              <p className="gate-reason">{exportGateReason(selectedInvoice)}</p>

              <div className="decision-actions" aria-label="Musavir kararlari">
                {(Object.keys(decisions) as DecisionAction[]).map((action) => (
                  <button key={action} onClick={() => setDecision(action)} type="button">
                    {decisions[action].label}
                  </button>
                ))}
              </div>

              <div className="decision-result">
                {activeDecision ? (
                  <>
                    <span>Son karar</span>
                    <strong>{activeDecision.label}</strong>
                    <p>{activeDecision.learningScope}</p>
                  </>
                ) : (
                  <p>Bu belge icin henuz musavir karari verilmedi.</p>
                )}
              </div>

              <h2>Fis Taslagi</h2>
              <div className="draft-lines">
                {selectedInvoice.draftLines.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Hesap</th>
                        <th>Aciklama</th>
                        <th>Borc</th>
                        <th>Alacak</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedInvoice.draftLines.map((line, index) => (
                        <tr key={`${line.account_code}-${index}`}>
                          <td>{line.account_code}</td>
                          <td>{line.description}</td>
                          <td>{line.debit}</td>
                          <td>{line.credit}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="empty">Bu kayit icin pozitif tutarli fis taslagi uretilemedi.</p>
                )}
              </div>
            </>
          ) : (
            <p className="empty">Bu filtrede belge yok.</p>
          )}
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ChartDetails({ chart }: { chart?: ChartRun }) {
  if (!chart) {
    return null;
  }
  return (
    <div className="chart-details">
      <Info label="Toplam hesap" value={String(chart.accountCount)} />
      <Info label="Detay hesap" value={String(chart.detailAccountCount)} />
      <Info label="120 aday" value={String(chart.customerCandidateCount)} />
      <Info label="320 aday" value={String(chart.supplierCandidateCount)} />
      <Info label="191" value={chart.hasPurchaseVat191 ? "Var" : "Yok"} />
      <Info label="391" value={chart.hasSalesVat391 ? "Var" : "Yok"} />
    </div>
  );
}
