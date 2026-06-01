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
  learningRuleApplied: boolean;
  learningRuleScope: string;
  learningRuleReason: string;
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

type UploadKind = "invoice" | "xml" | "bank" | "pos";
type UploadStatus = "queued" | "processing" | "review_required" | "export_ready";

type UploadItem = {
  id: string;
  fileName: string;
  kind: UploadKind;
  uploadedBy: string;
  status: UploadStatus;
  uploadedAt: string;
};

type ReviewData = {
  generatedFrom: string;
  clientName?: string;
  uploadQueue?: UploadItem[];
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

type WorkspaceDocument = {
  document_ref: string;
  status: string;
  export_status: string;
  review_reason_codes?: string[];
  result?: Record<string, unknown>;
};

type WorkspaceSnapshot = {
  client?: {
    profile?: {
      title?: string;
    };
  };
  chart_accounts?: {
    account_count?: number;
  };
  documents?: WorkspaceDocument[];
};

type PortalMode = "client" | "accountant";
type ViewMode = "all" | "review" | "export";
type DecisionAction = "approve" | "approve_with_changes" | "exclude_export" | "out_of_scope" | "wrong_counterparty";

type LocalDecision = {
  action: DecisionAction;
  label: string;
  learningScope: string;
};

const statusLabels: Record<string, string> = {
  auto_ready: "Otomatik hazir",
  export_ready: "Export hazir",
  review_required: "Kontrol gerekli",
  cannot_draft: "Taslak yok",
  processing: "Isleniyor",
  queued: "Kuyrukta",
};

const uploadKindLabels: Record<UploadKind, string> = {
  invoice: "Fatura",
  xml: "E-Fatura XML/PDF",
  bank: "Banka ekstresi",
  pos: "POS ekstresi",
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
  return `AI yok: ${row.aiClassificationSkippedReason || "statik akis"}`;
}

function textValue(source: Record<string, unknown>, camelKey: string, snakeKey: string, fallback = "") {
  const value = source[camelKey] ?? source[snakeKey];
  return value == null ? fallback : String(value);
}

function numberValue(source: Record<string, unknown>, camelKey: string, snakeKey: string) {
  return Number(source[camelKey] ?? source[snakeKey] ?? 0);
}

function boolValue(source: Record<string, unknown>, camelKey: string, snakeKey: string) {
  return Boolean(source[camelKey] ?? source[snakeKey] ?? false);
}

function listValue(source: Record<string, unknown>, camelKey: string, snakeKey: string) {
  const value = source[camelKey] ?? source[snakeKey];
  return Array.isArray(value) ? value.map(String) : [];
}

function draftLineValue(source: Record<string, unknown>) {
  const value = source.draftLines ?? source.draft_lines;
  return Array.isArray(value) ? (value as DraftLine[]) : [];
}

function blankInvoiceRow(document: WorkspaceDocument): InvoiceRow {
  const result = document.result ?? {};
  return {
    chartFileName: textValue(result, "chartFileName", "chart_file_name", "workspace-store"),
    fileName: textValue(result, "fileName", "file_name", document.document_ref),
    providerHint: textValue(result, "providerHint", "provider_hint"),
    invoiceType: textValue(result, "invoiceType", "invoice_type"),
    issueDate: textValue(result, "issueDate", "issue_date"),
    payableTotal: textValue(result, "payableTotal", "payable_total"),
    vatRates: listValue(result, "vatRates", "vat_rates"),
    status: textValue(result, "status", "simulated_status", document.status ?? "review_required"),
    draftQuality: textValue(result, "draftQuality", "draft_quality"),
    isBalanced: boolValue(result, "isBalanced", "is_balanced"),
    riskFlags: listValue(result, "riskFlags", "risk_flags"),
    parseNotes: listValue(result, "parseNotes", "parse_notes"),
    reviewReasonCodes: document.review_reason_codes ?? listValue(result, "reviewReasonCodes", "review_reason_codes"),
    productLineHint: textValue(result, "productLineHint", "product_line_hint"),
    productCategory: textValue(result, "productCategory", "product_category"),
    productConfidence: numberValue(result, "productConfidence", "product_confidence"),
    businessRelevanceStatus: textValue(result, "businessRelevanceStatus", "business_relevance_status"),
    businessRelevanceConfidence: numberValue(result, "businessRelevanceConfidence", "business_relevance_confidence"),
    businessRelevanceReason: textValue(result, "businessRelevanceReason", "business_relevance_reason"),
    businessRelevanceEvidence: listValue(result, "businessRelevanceEvidence", "business_relevance_evidence"),
    aiClassificationUsed: boolValue(result, "aiClassificationUsed", "ai_classification_used"),
    aiClassificationProvider: textValue(result, "aiClassificationProvider", "ai_classification_provider"),
    aiClassificationSkippedReason: textValue(result, "aiClassificationSkippedReason", "ai_classification_skipped_reason"),
    aiClassificationReason: textValue(result, "aiClassificationReason", "ai_classification_reason"),
    aiEstimatedInputChars: numberValue(result, "aiEstimatedInputChars", "ai_estimated_input_chars"),
    learningRuleApplied: boolValue(result, "learningRuleApplied", "learning_rule_applied"),
    learningRuleScope: textValue(result, "learningRuleScope", "learning_rule_scope"),
    learningRuleReason: textValue(result, "learningRuleReason", "learning_rule_reason"),
    exportStatus: textValue(result, "exportStatus", "export_status", document.export_status ?? "review_required"),
    selectedExpenseAccount: textValue(result, "selectedExpenseAccount", "selected_expense_account"),
    selectedVatAccount: textValue(result, "selectedVatAccount", "selected_vat_account"),
    selectedSupplierAccount: textValue(result, "selectedSupplierAccount", "selected_supplier_account"),
    counterpartyMatchCode: textValue(result, "counterpartyMatchCode", "counterparty_match_code"),
    counterpartyMatchConfidence: numberValue(result, "counterpartyMatchConfidence", "counterparty_match_confidence"),
    counterpartyMatchReason: textValue(result, "counterpartyMatchReason", "counterparty_match_reason"),
    draftLines: draftLineValue(result),
  };
}

function workspaceToReviewData(snapshot: WorkspaceSnapshot): ReviewData {
  const invoiceRows = (snapshot.documents ?? []).map(blankInvoiceRow);
  const exportReadyCount = invoiceRows.filter((row) => row.exportStatus === "export_ready").length;
  const reviewRequiredCount = invoiceRows.length - exportReadyCount;
  return {
    generatedFrom: "local workspace snapshot",
    clientName: snapshot.client?.profile?.title ?? "Pilot Mukellef",
    summary: {
      chartRunCount: snapshot.chart_accounts ? 1 : 0,
      invoiceRowCount: invoiceRows.length,
      autoReadyCount: exportReadyCount,
      reviewRequiredCount,
      cannotDraftCount: invoiceRows.filter((row) => !row.draftLines.length).length,
      allDraftsBalanced: invoiceRows.every((row) => row.isBalanced || !row.draftLines.length),
    },
    chartRuns: [
      {
        chartFileName: "workspace-store",
        accountCount: snapshot.chart_accounts?.account_count ?? 0,
        detailAccountCount: snapshot.chart_accounts?.account_count ?? 0,
        customerCandidateCount: 0,
        supplierCandidateCount: 0,
        hasPurchaseVat191: true,
        hasSalesVat391: true,
        autoReadyCount: exportReadyCount,
        reviewRequiredCount,
        cannotDraftCount: invoiceRows.filter((row) => !row.draftLines.length).length,
        selectedAccounts: {},
      },
    ],
    invoiceRows,
  };
}

export default function Home() {
  const [data, setData] = useState<ReviewData>(fallbackReviewData as ReviewData);
  const [source, setSource] = useState("demo fallback");
  const [activeChart, setActiveChart] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("review");
  const [portalMode, setPortalMode] = useState<PortalMode>("accountant");
  const [uploadKind, setUploadKind] = useState<UploadKind>("invoice");
  const [uploadItems, setUploadItems] = useState<UploadItem[]>((fallbackReviewData.uploadQueue ?? []) as UploadItem[]);
  const [decisionLog, setDecisionLog] = useState<Record<string, LocalDecision>>({});

  useEffect(() => {
    let cancelled = false;
    fetch("/local-workspace-data.json", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("No workspace data");
        return response.json() as Promise<WorkspaceSnapshot>;
      })
      .then((snapshot) => {
        if (cancelled) return;
        const payload = workspaceToReviewData(snapshot);
        setData(payload);
        setSource(payload.generatedFrom);
        setActiveChart(payload.chartRuns[0]?.chartFileName ?? "");
      })
      .catch(() => {
        fetch("/local-review-data.json", { cache: "no-store" })
          .then((response) => {
            if (!response.ok) throw new Error("No local review data");
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
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (data.uploadQueue?.length) {
      setUploadItems(data.uploadQueue);
    }
  }, [data.uploadQueue]);

  const clientName = data.clientName ?? "Demo Isitme Merkezi";
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

  function onFilesSelected(files: FileList | null) {
    if (!files?.length) return;
    const nextItems = Array.from(files).map((file, index) => ({
      id: `${Date.now()}-${index}`,
      fileName: file.name,
      kind: uploadKind,
      uploadedBy: clientName,
      status: "queued" as UploadStatus,
      uploadedAt: new Date().toLocaleString("tr-TR"),
    }));
    setUploadItems((current) => [...nextItems, ...current]);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="label">Fisora MVP Portal</p>
          <h1>Mukellef belge ve fis operasyonu</h1>
        </div>
        <div className="top-actions">
          <div className="client-badge">{clientName}</div>
          <div className="source">{source}</div>
        </div>
      </header>

      <section className="modebar" aria-label="Portal modu">
        <button
          aria-pressed={portalMode === "client"}
          className={portalMode === "client" ? "mode-button active" : "mode-button"}
          onClick={() => setPortalMode("client")}
          type="button"
        >
          Mukellef yukleme
        </button>
        <button
          aria-pressed={portalMode === "accountant"}
          className={portalMode === "accountant" ? "mode-button active" : "mode-button"}
          onClick={() => setPortalMode("accountant")}
          type="button"
        >
          Musavir review
        </button>
      </section>

      <section className="portal-strip" aria-label="Mukellef portal ozeti">
        <Info label="Mukellef" value={clientName} />
        <Info label="Yetki" value={portalMode === "client" ? "Mukellef kullanicisi" : "Musavir review"} />
        <Info label="Review kuyrugu" value={String(reviewQueueCount)} />
        <Info label="Export hazir" value={String(exportReadyCount)} />
      </section>

      {portalMode === "client" ? (
        <ClientUploadView
          clientName={clientName}
          uploadKind={uploadKind}
          uploadItems={uploadItems}
          onFilesSelected={onFilesSelected}
          setUploadKind={setUploadKind}
        />
      ) : (
        <AccountantReviewView
          activeChart={activeChart}
          activeDecision={activeDecision}
          chartRuns={data.chartRuns}
          clientName={clientName}
          exportReadyCount={exportReadyCount}
          reviewQueueCount={reviewQueueCount}
          selectedInvoice={selectedInvoice}
          setActiveChart={setActiveChart}
          setDecision={setDecision}
          setSelectedKey={setSelectedKey}
          setViewMode={setViewMode}
          summary={data.summary}
          viewMode={viewMode}
          visibleInvoices={visibleInvoices}
        />
      )}
    </main>
  );
}

function ClientUploadView({
  clientName,
  uploadKind,
  uploadItems,
  onFilesSelected,
  setUploadKind,
}: {
  clientName: string;
  uploadKind: UploadKind;
  uploadItems: UploadItem[];
  onFilesSelected: (files: FileList | null) => void;
  setUploadKind: (kind: UploadKind) => void;
}) {
  return (
    <section className="client-workspace" aria-label="Mukellef yukleme alani">
      <div className="upload-panel">
        <div className="panel-head compact">
          <div>
            <h2>Belge yukleme</h2>
            <span>{clientName}</span>
          </div>
        </div>
        <div className="upload-kind-grid">
          {(Object.keys(uploadKindLabels) as UploadKind[]).map((kind) => (
            <button
              className={uploadKind === kind ? "upload-kind active" : "upload-kind"}
              key={kind}
              onClick={() => setUploadKind(kind)}
              type="button"
            >
              {uploadKindLabels[kind]}
            </button>
          ))}
        </div>
        <label className="upload-dropzone">
          <span>{uploadKindLabels[uploadKind]} sec</span>
          <strong>PDF, XML, CSV veya XLSX</strong>
          <input
            multiple
            onChange={(event) => onFilesSelected(event.target.files)}
            type="file"
            accept=".pdf,.xml,.csv,.xlsx,.xls,.zip"
          />
        </label>
      </div>

      <div className="upload-panel">
        <div className="panel-head compact">
          <div>
            <h2>Yuklenen belgeler</h2>
            <span>{uploadItems.length} kayit</span>
          </div>
        </div>
        <div className="upload-list">
          {uploadItems.map((item) => (
            <div className="upload-row" key={item.id}>
              <div>
                <strong>{item.fileName}</strong>
                <span>{uploadKindLabels[item.kind]} - {item.uploadedAt}</span>
              </div>
              <span className={`status ${item.status}`}>{formatStatus(item.status)}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function AccountantReviewView({
  activeChart,
  activeDecision,
  chartRuns,
  clientName,
  exportReadyCount,
  reviewQueueCount,
  selectedInvoice,
  setActiveChart,
  setDecision,
  setSelectedKey,
  setViewMode,
  summary,
  viewMode,
  visibleInvoices,
}: {
  activeChart: string;
  activeDecision?: LocalDecision;
  chartRuns: ChartRun[];
  clientName: string;
  exportReadyCount: number;
  reviewQueueCount: number;
  selectedInvoice?: InvoiceRow;
  setActiveChart: (value: string) => void;
  setDecision: (action: DecisionAction) => void;
  setSelectedKey: (value: string) => void;
  setViewMode: (value: ViewMode) => void;
  summary: ReviewData["summary"];
  viewMode: ViewMode;
  visibleInvoices: InvoiceRow[];
}) {
  return (
    <>
      <section className="metrics" aria-label="Ozet">
        <Metric label="Hesap plani" value={summary.chartRunCount} />
        <Metric label="Belge sayisi" value={summary.invoiceRowCount} />
        <Metric label="Export hazir" value={exportReadyCount} tone="good" />
        <Metric label="Kontrol gerekli" value={reviewQueueCount} tone="warn" />
        <Metric label="Taslak eksik" value={summary.cannotDraftCount} tone="bad" />
      </section>

      <section className="review-workspace">
        <aside className="document-panel" aria-label="Belge ve hesap plani">
          <div className="client-card">
            <strong>{clientName}</strong>
            <span>VKN/TCKN eslesmis, hesap plani yuklu</span>
          </div>
          <div className="tabbar vertical" role="tablist" aria-label="Belge filtreleri">
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
          <div className="document-list">
            {visibleInvoices.map((row) => {
              const key = rowKey(row);
              const isSelected = selectedInvoice ? rowKey(selectedInvoice) === key : false;
              return (
                <button
                  className={isSelected ? "document-row active" : "document-row"}
                  key={key}
                  onClick={() => setSelectedKey(key)}
                  type="button"
                >
                  <strong>{row.fileName}</strong>
                  <span>{row.providerHint || "Bilinmiyor"} - {row.payableTotal || "-"}</span>
                  <em>{formatExportStatus(row.exportStatus)}</em>
                </button>
              );
            })}
          </div>
          <div className="chart-list compact-list">
            {chartRuns.map((chart) => (
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
                <span>{chart.detailAccountCount} detay, {chart.supplierCandidateCount} satici</span>
              </button>
            ))}
          </div>
        </aside>

        <InvoicePreview clientName={clientName} invoice={selectedInvoice} />
        <JournalReviewPanel activeDecision={activeDecision} invoice={selectedInvoice} setDecision={setDecision} />
      </section>
    </>
  );
}

function InvoicePreview({ clientName, invoice }: { clientName: string; invoice?: InvoiceRow }) {
  if (!invoice) {
    return (
      <section className="invoice-preview">
        <h2>Fatura gorunumu</h2>
        <p className="empty">Belge secimi yok.</p>
      </section>
    );
  }
  return (
    <section className="invoice-preview" aria-label="Fatura gorunumu">
      <div className="panel-head compact">
        <div>
          <h2>Fatura gorunumu</h2>
          <span>{invoice.fileName}</span>
        </div>
        <span className={`status ${invoice.exportStatus}`}>{formatExportStatus(invoice.exportStatus)}</span>
      </div>
      <div className="invoice-paper">
        <div className="invoice-head">
          <strong>{invoice.providerHint || "Tedarikci bilinmiyor"}</strong>
          <span>{invoice.issueDate || "-"}</span>
        </div>
        <Info label="Mukellef" value={clientName} />
        <Info label="Belge tipi" value={invoice.invoiceType || "-"} />
        <Info label="Tutar" value={invoice.payableTotal || "-"} />
        <Info label="KDV" value={invoice.vatRates.length ? invoice.vatRates.join(", ") : "-"} />
        <div className="invoice-line">
          <span>Kalem</span>
          <strong>{invoice.productLineHint || "-"}</strong>
        </div>
        <div className="invoice-line">
          <span>Kategori</span>
          <strong>{invoice.productCategory || "-"} ({invoice.productConfidence || 0})</strong>
        </div>
        <p className="reason">{invoice.businessRelevanceReason || "Uygunluk gerekcesi yok."}</p>
        <p className="gate-reason">{exportGateReason(invoice)}</p>
      </div>
    </section>
  );
}

function JournalReviewPanel({
  activeDecision,
  invoice,
  setDecision,
}: {
  activeDecision?: LocalDecision;
  invoice?: InvoiceRow;
  setDecision: (action: DecisionAction) => void;
}) {
  return (
    <section className="journal-panel" aria-label="Fis taslagi ve karar">
      <div className="panel-head compact">
        <div>
          <h2>Muhasebe fisi</h2>
          <span>{invoice ? formatDraftQuality(invoice.draftQuality) : "-"}</span>
        </div>
      </div>
      {invoice ? (
        <>
          <div className="detail-grid">
            <Info label="Gider hesabi" value={invoice.selectedExpenseAccount || "-"} />
            <Info label="KDV hesabi" value={invoice.selectedVatAccount || "-"} />
            <Info label="Cari hesabi" value={invoice.selectedSupplierAccount || "-"} />
            <Info label="Cari eslesme" value={`${invoice.counterpartyMatchCode || "-"} (${invoice.counterpartyMatchConfidence || 0})`} />
            <Info label="AI sinifi" value={formatAiStatus(invoice)} />
            <Info label="Ogrenme" value={invoice.learningRuleApplied ? invoice.learningRuleScope || "Uygulandi" : "Yok"} />
          </div>

          {invoice.learningRuleReason ? <p className="reason">{invoice.learningRuleReason}</p> : null}

          <div className="draft-lines">
            {invoice.draftLines.length ? (
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
                  {invoice.draftLines.map((line, index) => (
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
        </>
      ) : (
        <p className="empty">Belge secimi yok.</p>
      )}
    </section>
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
