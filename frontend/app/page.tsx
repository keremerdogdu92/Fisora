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

const statusLabels: Record<string, string> = {
  auto_ready: "Otomatik hazır",
  review_required: "Kontrol gerekli",
};

const draftQualityLabels: Record<string, string> = {
  full_basic_purchase: "Tam temel alış fişi",
  partial_review_required: "Hazır ama kontrol gerekli",
  gross_balanced_needs_vat_split: "Brüt dengeli, KDV ayrımı gerekli",
  no_positive_amount: "Pozitif tutar yok",
};

const relevanceLabels: Record<string, string> = {
  uygun: "Uygun",
  genel_gider: "Genel gider",
  supheli: "Şüpheli",
  is_alani_disi: "İş alanı dışı",
};

const exportStatusLabels: Record<string, string> = {
  export_ready: "Export hazır",
  review_required: "Kontrol gerekli",
  blocked: "Bloklandı",
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

export default function Home() {
  const [data, setData] = useState<ReviewData>(fallbackReviewData as ReviewData);
  const [source, setSource] = useState("demo fallback");
  const [activeChart, setActiveChart] = useState("");
  const [selectedKey, setSelectedKey] = useState("");

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

  const visibleInvoices = useMemo(() => {
    return data.invoiceRows.filter((row) => !activeChart || row.chartFileName === activeChart);
  }, [activeChart, data.invoiceRows]);

  const selectedInvoice = useMemo(() => {
    return visibleInvoices.find((row) => `${row.chartFileName}:${row.fileName}` === selectedKey) ?? visibleInvoices[0];
  }, [selectedKey, visibleInvoices]);
  const exportReadyCount = useMemo(() => {
    return visibleInvoices.filter((row) => row.exportStatus === "export_ready").length;
  }, [visibleInvoices]);
  const reviewQueueCount = useMemo(() => {
    return visibleInvoices.filter((row) => row.exportStatus !== "export_ready").length;
  }, [visibleInvoices]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="label">Fisora MVP Portal</p>
          <h1>Mükellef belge ve fiş review console</h1>
        </div>
        <div className="source">{source}</div>
      </header>

      <section className="portal-strip" aria-label="Mükellef portal özeti">
        <Info label="Mükellef" value="Demo İşitme Merkezi" />
        <Info label="Yetki" value="Müşavir review" />
        <Info label="Review kuyruğu" value={String(reviewQueueCount)} />
        <Info label="Export hazır" value={String(exportReadyCount)} />
      </section>

      <section className="metrics" aria-label="Özet">
        <Metric label="Hesap planı denemesi" value={data.summary.chartRunCount} />
        <Metric label="Fatura koşusu" value={data.summary.invoiceRowCount} />
        <Metric label="Otomatik hazır" value={data.summary.autoReadyCount} tone="good" />
        <Metric label="Kontrol gerekli" value={data.summary.reviewRequiredCount} tone="warn" />
        <Metric label="Taslak eksik" value={data.summary.cannotDraftCount} tone="bad" />
      </section>

      <section className="layout">
        <aside className="sidebar" aria-label="Hesap planları">
          <h2>Hesap Planları</h2>
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
                  {chart.detailAccountCount} detay, {chart.supplierCandidateCount} satıcı
                </span>
              </button>
            ))}
          </div>
          <ChartDetails chart={data.chartRuns.find((chart) => chart.chartFileName === activeChart)} />
        </aside>

        <section className="table-panel" aria-label="Fatura testleri">
          <div className="panel-head">
            <h2>Fatura Parser Testleri</h2>
            <span>{visibleInvoices.length} kayıt</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fatura</th>
                  <th>Sağlayıcı</th>
                  <th>Tutar</th>
                  <th>KDV</th>
                  <th>Durum</th>
                  <th>Uygunluk</th>
                  <th>Export</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {visibleInvoices.map((row) => {
                  const key = `${row.chartFileName}:${row.fileName}`;
                  return (
                    <tr
                      className={selectedInvoice && selectedInvoice.fileName === row.fileName ? "selected" : ""}
                      key={key}
                      onClick={() => setSelectedKey(key)}
                    >
                      <td>{row.fileName}</td>
                      <td>{row.providerHint || "Bilinmiyor"}</td>
                      <td>{row.payableTotal || "-"}</td>
                      <td>{row.vatRates.length ? row.vatRates.join(", ") : "-"}</td>
                      <td>
                        <span className={`status ${row.status}`}>{formatStatus(row.status)}</span>
                      </td>
                      <td>{formatRelevance(row.businessRelevanceStatus)}</td>
                      <td>{formatExportStatus(row.exportStatus)}</td>
                      <td>{row.reviewReasonCodes.length ? row.reviewReasonCodes.join(", ") : "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="detail-panel" aria-label="Fiş taslağı">
          <h2>Fiş Taslağı</h2>
          {selectedInvoice ? (
            <>
              <div className="detail-grid">
                <Info label="Fatura" value={selectedInvoice.fileName} />
                <Info label="Tarih" value={selectedInvoice.issueDate || "-"} />
                <Info label="Tip" value={selectedInvoice.invoiceType || "-"} />
                <Info label="Taslak" value={formatDraftQuality(selectedInvoice.draftQuality)} />
                <Info label="Ürün sinyali" value={selectedInvoice.productLineHint || "-"} />
                <Info
                  label="Kategori"
                  value={`${selectedInvoice.productCategory || "-"} (${selectedInvoice.productConfidence ?? 0})`}
                />
                <Info
                  label="Uygunluk"
                  value={`${formatRelevance(selectedInvoice.businessRelevanceStatus)} (${selectedInvoice.businessRelevanceConfidence ?? 0})`}
                />
                <Info label="Export" value={formatExportStatus(selectedInvoice.exportStatus)} />
                <Info label="Gider hesabı" value={selectedInvoice.selectedExpenseAccount} />
                <Info label="KDV hesabı" value={selectedInvoice.selectedVatAccount} />
                <Info label="Cari hesabı" value={selectedInvoice.selectedSupplierAccount} />
                <Info
                  label="Cari eşleşme"
                  value={`${selectedInvoice.counterpartyMatchCode || "-"} (${selectedInvoice.counterpartyMatchConfidence ?? 0})`}
                />
                <Info label="Denge" value={selectedInvoice.isBalanced ? "Dengeli" : "Eksik"} />
              </div>
              <p className="reason">{selectedInvoice.businessRelevanceReason || "Uygunluk gerekçesi yok."}</p>
              <div className="draft-lines">
                {selectedInvoice.draftLines.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Hesap</th>
                        <th>Açıklama</th>
                        <th>Borç</th>
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
                  <p className="empty">Bu kayıt için pozitif tutarlı fiş taslağı üretilemedi.</p>
                )}
              </div>
            </>
          ) : (
            <p className="empty">Fatura seçimi yok.</p>
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
