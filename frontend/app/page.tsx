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
  documentRef?: string;
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
  accountantDecisionAction?: string;
  accountantDecisionReason?: string;
  accountantReviewedAt?: string;
  accountantReviewedBy?: string;
  accountantExportOverride?: boolean;
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
type UploadStatus =
  | "queued"
  | "processing"
  | "stored"
  | "expiring"
  | "deleted"
  | "upload_failed"
  | "review_required"
  | "export_ready";

type UploadItem = {
  id: string;
  remoteDocumentId?: string;
  processingJobId?: string;
  parserKind?: string;
  processingStatus?: string;
  fileName: string;
  kind: UploadKind;
  uploadedBy: string;
  status: UploadStatus;
  uploadedAt: string;
  downloadAvailableUntil?: string;
  deletedAt?: string;
};

type ExportPackageItem = {
  id: string;
  exportType: string;
  entryCount: number;
  excludedCount: number;
  outputFilename: string;
  downloadUrl: string;
  downloadedAt: string;
  downloadCount: number;
  createdAt: string;
};

type ReviewData = {
  generatedFrom: string;
  clientId?: string;
  clientName?: string;
  uploadQueue?: UploadItem[];
  exportPackages?: ExportPackageItem[];
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

type WorkspaceUploadedDocument = {
  document_id?: string;
  document_ref?: string;
  document_type?: string;
  original_file_name?: string;
  uploaded_by?: string;
  status?: string;
  storage_status?: string;
  download_available_until?: string;
  expires_at?: string;
  deleted_at?: string;
  created_at?: string;
  updated_at?: string;
};

type WorkspaceProcessingJob = {
  id?: string;
  client_id?: string;
  document_ref?: string;
  document_type?: string;
  parser_kind?: string;
  status?: string;
  error_message?: string;
  created_at?: string;
  updated_at?: string;
};

type WorkspaceExportPackage = {
  id?: string;
  client_id?: string;
  package?: {
    export_type?: string;
    entry_count?: number;
    excluded_document_refs?: string[];
    output_filename?: string;
    download_url?: string;
    downloaded_at?: string;
    download_count?: number;
  };
  created_at?: string;
  updated_at?: string;
};

type WorkspaceSnapshot = {
  client?: {
    client_id?: string;
    profile?: {
      client_id?: string;
      title?: string;
    };
  };
  chart_accounts?: {
    account_count?: number;
  };
  uploaded_documents?: WorkspaceUploadedDocument[];
  documents?: WorkspaceDocument[];
  processing_jobs?: WorkspaceProcessingJob[];
  export_packages?: WorkspaceExportPackage[];
};

type PortalMode = "client" | "accountant";
type ViewMode = "all" | "review" | "export";
type DecisionAction = "approve" | "approve_with_changes" | "exclude_export" | "out_of_scope" | "wrong_counterparty";

type LocalDecision = {
  action: DecisionAction;
  label: string;
  learningScope: string;
};

type CorrectionDraft = {
  correctedAccountCode: string;
  correctedCounterpartyCode: string;
  reason: string;
};

const statusLabels: Record<string, string> = {
  auto_ready: "Otomatik hazir",
  export_ready: "Export hazir",
  review_required: "Kontrol gerekli",
  cannot_draft: "Taslak yok",
  processing: "Isleniyor",
  queued: "Kuyrukta",
  stored: "Yuklendi",
  expiring: "Silinmeye yaklasiyor",
  deleted: "Ham belge silindi",
  upload_failed: "Yukleme hatasi",
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

const API_BASE_URL = process.env.NEXT_PUBLIC_FISORA_API_BASE_URL ?? "http://localhost:8000";

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
  return `${row.chartFileName}:${row.documentRef || row.fileName}`;
}

function exportGateReason(row: InvoiceRow) {
  if (row.accountantExportOverride) return "Musavir onayi ile export paketine alinabilir.";
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

function formatDateText(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("tr-TR");
}

function apiDocumentType(kind: UploadKind) {
  if (kind === "xml") return "einvoice_xml";
  if (kind === "bank") return "bank_statement";
  if (kind === "pos") return "pos_statement";
  return "invoice";
}

function uploadKindFromApi(documentType?: string): UploadKind {
  if (documentType === "einvoice_xml") return "xml";
  if (documentType === "bank_statement") return "bank";
  if (documentType === "pos_statement") return "pos";
  return "invoice";
}

function uploadStatusFromApi(status?: string): UploadStatus {
  if (status === "deleted") return "deleted" as UploadStatus;
  if (status === "expiring") return "expiring" as UploadStatus;
  if (status === "stored") return "stored";
  if (status === "processing") return "processing";
  if (status === "export_ready") return "export_ready";
  if (status === "review_required") return "review_required";
  return "queued";
}

function uploadStatusFromJob(documentStatus: string | undefined, job?: WorkspaceProcessingJob): UploadStatus {
  if (documentStatus === "deleted") return "deleted";
  if (documentStatus === "expiring") return "expiring";
  if (job?.status === "queued") return "queued";
  if (job?.status === "processing") return "processing";
  if (job?.status === "failed") return "upload_failed";
  if (job?.status === "completed") return uploadStatusFromApi(documentStatus || "review_required");
  return uploadStatusFromApi(documentStatus);
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

function correctedDraftLines(invoice: InvoiceRow, correction: CorrectionDraft) {
  const accountCode = correction.correctedAccountCode.trim();
  const counterpartyCode = correction.correctedCounterpartyCode.trim();
  if (!accountCode && !counterpartyCode) return invoice.draftLines;
  return invoice.draftLines.map((line) => {
    if (accountCode && line.account_code === invoice.selectedExpenseAccount) {
      return { ...line, account_code: accountCode };
    }
    const supplierTargets = [invoice.selectedSupplierAccount, invoice.counterpartyMatchCode].filter(Boolean);
    if (counterpartyCode && supplierTargets.includes(line.account_code)) {
      return { ...line, account_code: counterpartyCode };
    }
    return line;
  });
}

function blankInvoiceRow(document: WorkspaceDocument): InvoiceRow {
  const result = document.result ?? {};
  return {
    chartFileName: textValue(result, "chartFileName", "chart_file_name", "workspace-store"),
    documentRef: document.document_ref,
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
    accountantDecisionAction: textValue(result, "accountantDecisionAction", "accountant_decision_action"),
    accountantDecisionReason: textValue(result, "accountantDecisionReason", "accountant_decision_reason"),
    accountantReviewedAt: textValue(result, "accountantReviewedAt", "accountant_reviewed_at"),
    accountantReviewedBy: textValue(result, "accountantReviewedBy", "accountant_reviewed_by"),
    accountantExportOverride: boolValue(result, "accountantExportOverride", "accountant_export_override"),
    draftLines: draftLineValue(result),
  };
}

function workspaceToReviewData(snapshot: WorkspaceSnapshot, fallback?: ReviewData): ReviewData {
  const invoiceRows = snapshot.documents?.length ? snapshot.documents.map(blankInvoiceRow) : (fallback?.invoiceRows ?? []);
  const exportReadyCount = invoiceRows.filter((row) => row.exportStatus === "export_ready").length;
  const reviewRequiredCount = invoiceRows.length - exportReadyCount;
  const clientId = snapshot.client?.client_id ?? snapshot.client?.profile?.client_id ?? fallback?.clientId ?? "pilot-mukellef";
  const clientName = snapshot.client?.profile?.title ?? fallback?.clientName ?? "Pilot Mukellef";
  return {
    generatedFrom: "local workspace snapshot",
    clientId,
    clientName,
    uploadQueue: uploadedDocumentsToQueue(snapshot.uploaded_documents ?? [], snapshot.processing_jobs ?? [], clientName),
    exportPackages: exportPackagesFromWorkspace(snapshot.export_packages ?? [], fallback?.exportPackages ?? []),
    summary: {
      chartRunCount: snapshot.chart_accounts ? 1 : (fallback?.summary.chartRunCount ?? 0),
      invoiceRowCount: invoiceRows.length,
      autoReadyCount: exportReadyCount,
      reviewRequiredCount,
      cannotDraftCount: invoiceRows.filter((row) => !row.draftLines.length).length,
      allDraftsBalanced: invoiceRows.every((row) => row.isBalanced || !row.draftLines.length),
    },
    chartRuns: snapshot.chart_accounts
      ? [
          {
            chartFileName: "workspace-store",
            accountCount: snapshot.chart_accounts.account_count ?? 0,
            detailAccountCount: snapshot.chart_accounts.account_count ?? 0,
            customerCandidateCount: 0,
            supplierCandidateCount: 0,
            hasPurchaseVat191: true,
            hasSalesVat391: true,
            autoReadyCount: exportReadyCount,
            reviewRequiredCount,
            cannotDraftCount: invoiceRows.filter((row) => !row.draftLines.length).length,
            selectedAccounts: {},
          },
        ]
      : (fallback?.chartRuns ?? []),
    invoiceRows,
  };
}

function exportPackagesFromWorkspace(
  packages: WorkspaceExportPackage[],
  fallback: ExportPackageItem[],
): ExportPackageItem[] {
  if (!packages.length) return fallback;
  return packages
    .map((record) => {
      const packagePayload = record.package ?? {};
      return {
        id: record.id ?? packagePayload.output_filename ?? record.created_at ?? "export-package",
        exportType: packagePayload.export_type ?? "zirve_universal_csv",
        entryCount: packagePayload.entry_count ?? 0,
        excludedCount: packagePayload.excluded_document_refs?.length ?? 0,
        outputFilename: packagePayload.output_filename ?? "",
        downloadUrl: packagePayload.download_url ?? "",
        downloadedAt: packagePayload.downloaded_at ?? "",
        downloadCount: packagePayload.download_count ?? 0,
        createdAt: record.created_at ?? record.updated_at ?? "",
      };
    })
    .reverse();
}

function uploadedDocumentsToQueue(
  documents: WorkspaceUploadedDocument[],
  jobs: WorkspaceProcessingJob[],
  fallbackUploadedBy: string,
): UploadItem[] {
  const jobsByDocumentRef = new Map(jobs.map((job) => [String(job.document_ref ?? ""), job]));
  return documents.map((document) => ({
    id: document.document_id ?? document.document_ref ?? `${document.original_file_name ?? "document"}-${document.created_at ?? ""}`,
    remoteDocumentId: document.document_id ?? document.document_ref,
    processingJobId: jobsByDocumentRef.get(String(document.document_ref ?? document.document_id ?? ""))?.id,
    parserKind: jobsByDocumentRef.get(String(document.document_ref ?? document.document_id ?? ""))?.parser_kind,
    processingStatus: jobsByDocumentRef.get(String(document.document_ref ?? document.document_id ?? ""))?.status,
    fileName: document.original_file_name ?? document.document_ref ?? "document",
    kind: uploadKindFromApi(document.document_type),
    uploadedBy: document.uploaded_by || fallbackUploadedBy,
    status: uploadStatusFromJob(
      document.storage_status ?? document.status,
      jobsByDocumentRef.get(String(document.document_ref ?? document.document_id ?? "")),
    ),
    uploadedAt: document.created_at ?? document.updated_at ?? "",
    downloadAvailableUntil: document.download_available_until ?? document.expires_at ?? "",
    deletedAt: document.deleted_at ?? "",
  }));
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
  const [decisionStatus, setDecisionStatus] = useState("");
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>({
    correctedAccountCode: "",
    correctedCounterpartyCode: "",
    reason: "",
  });
  const [exportPackageStatus, setExportPackageStatus] = useState("");
  const [exportPackageDownloadUrl, setExportPackageDownloadUrl] = useState("");

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
  const clientId = data.clientId ?? "demo-isitme-merkezi";
  const latestExportPackage = data.exportPackages?.[0];
  const activeExportDownloadUrl =
    exportPackageDownloadUrl || (latestExportPackage?.downloadUrl ? `${API_BASE_URL}${latestExportPackage.downloadUrl}` : "");

  useEffect(() => {
    setCorrectionDraft({ correctedAccountCode: "", correctedCounterpartyCode: "", reason: "" });
    setDecisionStatus("");
  }, [selectedInvoice ? rowKey(selectedInvoice) : ""]);

  async function refreshWorkspaceFromApi(targetClientId = clientId) {
    const response = await fetch(`${API_BASE_URL}/phase0/store/workspace/${encodeURIComponent(targetClientId)}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("workspace refresh failed");
    const snapshot = (await response.json()) as WorkspaceSnapshot;
    const payload = workspaceToReviewData(snapshot, data);
    setData(payload);
    setSource("api workspace");
    setActiveChart(payload.chartRuns[0]?.chartFileName ?? "");
    if (payload.uploadQueue?.length) {
      setUploadItems(payload.uploadQueue);
    }
    return payload;
  }

  async function setDecision(action: DecisionAction) {
    if (!selectedInvoice) return;
    const decision = decisions[action];
    setDecisionLog((current) => ({
      ...current,
      [rowKey(selectedInvoice)]: decision,
    }));
    setDecisionStatus("Karar API'ye yaziliyor...");
    try {
      const response = await fetch(`${API_BASE_URL}/phase0/store/review-decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          decision: {
            document_ref: selectedInvoice.documentRef || selectedInvoice.fileName,
            action,
            reviewer: "mali-musavir",
            corrected_account_code: correctionDraft.correctedAccountCode.trim(),
            corrected_counterparty_code: correctionDraft.correctedCounterpartyCode.trim(),
            category: selectedInvoice.productCategory || "",
            reason: correctionDraft.reason.trim() || exportGateReason(selectedInvoice),
            apply_to_similar: action === "approve" || action === "approve_with_changes",
            prior_consistent_approval_count: action === "approve" ? 2 : 0,
          },
        }),
      });
      if (!response.ok) throw new Error("review decision save failed");
      const saved = (await response.json()) as {
        learning_event?: {
          automation_candidate?: boolean;
        };
      };
      await refreshWorkspaceFromApi(clientId);
      setDecisionStatus(saved.learning_event?.automation_candidate ? "Karar kaydedildi, otomasyon adayi." : "Karar kaydedildi.");
    } catch {
      setDecisionStatus("API yazilamadi; karar bu ekranda lokal tutuldu.");
    }
  }

  async function createExportPackage() {
    setExportPackageStatus("Export paketi olusturuluyor...");
    try {
      const response = await fetch(`${API_BASE_URL}/phase0/store/export-package/from-workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          export_type: "zirve_universal_csv",
        }),
      });
      if (!response.ok) throw new Error("export package failed");
      const saved = (await response.json()) as {
        package?: {
          entry_count?: number;
          excluded_document_refs?: string[];
          download_url?: string;
          output_filename?: string;
        };
      };
      const entryCount = saved.package?.entry_count ?? 0;
      const excludedCount = saved.package?.excluded_document_refs?.length ?? 0;
      setExportPackageStatus(`${entryCount} fis export paketine alindi, ${excludedCount} kayit disarida kaldi.`);
      const downloadUrl = saved.package?.download_url ?? "";
      setExportPackageDownloadUrl(downloadUrl ? `${API_BASE_URL}${downloadUrl}` : "");
      await refreshWorkspaceFromApi(clientId);
    } catch {
      setExportPackageStatus("Export paketi olusturulamadi.");
      setExportPackageDownloadUrl("");
    }
  }

  async function onFilesSelected(files: FileList | null) {
    if (!files?.length) return;
    const nextItems = Array.from(files).map((file, index) => ({
      id: `${Date.now()}-${index}`,
      fileName: file.name,
      kind: uploadKind,
      uploadedBy: clientName,
      status: "processing" as UploadStatus,
      uploadedAt: new Date().toLocaleString("tr-TR"),
    }));
    setUploadItems((current) => [...nextItems, ...current]);
    const uploadResults = await Promise.all(
      nextItems.map(async (item, index) => {
        const file = files[index];
        try {
          const formData = new FormData();
          formData.append("client_id", clientId);
          formData.append("document_type", apiDocumentType(item.kind));
          formData.append("uploaded_by", clientName);
          formData.append("retention_policy_days", "90");
          formData.append("file", file);
          const response = await fetch(`${API_BASE_URL}/phase0/store/document-upload-multipart`, {
            method: "POST",
            body: formData,
          });
          if (!response.ok) throw new Error("upload failed");
          const stored = (await response.json()) as {
            document_id?: string;
            status?: UploadStatus;
            download_available_until?: string;
            processing_job?: {
              id?: string;
              status?: string;
              parser_kind?: string;
            };
          };
          setUploadItems((current) =>
            current.map((currentItem) =>
              currentItem.id === item.id
                ? {
                    ...currentItem,
                    remoteDocumentId: stored.document_id,
                    processingJobId: stored.processing_job?.id,
                    parserKind: stored.processing_job?.parser_kind,
                    processingStatus: stored.processing_job?.status,
                    status: stored.processing_job?.status === "queued" ? "queued" : stored.status === "stored" ? "stored" : "queued",
                    downloadAvailableUntil: stored.download_available_until,
                  }
                : currentItem,
            ),
          );
          return true;
        } catch {
          setUploadItems((current) =>
            current.map((currentItem) =>
              currentItem.id === item.id ? { ...currentItem, status: "upload_failed" } : currentItem,
            ),
          );
          return false;
        }
      }),
    );
    if (uploadResults.some(Boolean)) {
      try {
        await refreshWorkspaceFromApi(clientId);
      } catch {
        setSource("api upload ok, workspace refresh failed");
      }
    }
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
          clientId={clientId}
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
          correctionDraft={correctionDraft}
          createExportPackage={createExportPackage}
          exportPackageDownloadUrl={activeExportDownloadUrl}
          exportPackageStatus={exportPackageStatus}
          exportReadyCount={exportReadyCount}
          latestExportPackage={latestExportPackage}
          reviewQueueCount={reviewQueueCount}
          selectedInvoice={selectedInvoice}
          decisionStatus={decisionStatus}
          setActiveChart={setActiveChart}
          setCorrectionDraft={setCorrectionDraft}
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
  clientId,
  uploadKind,
  uploadItems,
  onFilesSelected,
  setUploadKind,
}: {
  clientName: string;
  clientId: string;
  uploadKind: UploadKind;
  uploadItems: UploadItem[];
  onFilesSelected: (files: FileList | null) => Promise<void>;
  setUploadKind: (kind: UploadKind) => void;
}) {
  return (
    <section className="client-workspace" aria-label="Mukellef yukleme alani">
      <div className="upload-panel">
        <div className="panel-head compact">
          <div>
            <h2>Belge yukleme</h2>
            <span>{clientName} - {clientId}</span>
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
                {item.remoteDocumentId ? <span>Belge ID: {item.remoteDocumentId}</span> : null}
                {item.parserKind ? <span>Parser: {item.parserKind} / {item.processingStatus || "queued"}</span> : null}
                {item.deletedAt ? (
                  <span>Ham belge silindi: {formatDateText(item.deletedAt)}</span>
                ) : item.downloadAvailableUntil ? (
                  <span>Son indirme: {formatDateText(item.downloadAvailableUntil)}</span>
                ) : null}
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
  correctionDraft,
  createExportPackage,
  exportPackageDownloadUrl,
  decisionStatus,
  exportPackageStatus,
  exportReadyCount,
  latestExportPackage,
  reviewQueueCount,
  selectedInvoice,
  setActiveChart,
  setCorrectionDraft,
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
  correctionDraft: CorrectionDraft;
  createExportPackage: () => Promise<void>;
  exportPackageDownloadUrl: string;
  decisionStatus: string;
  exportPackageStatus: string;
  exportReadyCount: number;
  latestExportPackage?: ExportPackageItem;
  reviewQueueCount: number;
  selectedInvoice?: InvoiceRow;
  setActiveChart: (value: string) => void;
  setCorrectionDraft: (value: CorrectionDraft) => void;
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
            <button className="export-button" onClick={createExportPackage} type="button">
              Export paketi olustur
            </button>
            {exportPackageStatus ? <span>{exportPackageStatus}</span> : null}
            {exportPackageDownloadUrl ? (
              <a className="download-link" href={exportPackageDownloadUrl}>
                CSV indir
              </a>
            ) : null}
            {latestExportPackage ? (
              <span>
                Son paket: {latestExportPackage.entryCount} fis, {latestExportPackage.excludedCount} disarida
              </span>
            ) : null}
            {latestExportPackage?.downloadedAt ? (
              <span>
                Indirildi: {formatDateText(latestExportPackage.downloadedAt)}
                {latestExportPackage.downloadCount > 1 ? ` (${latestExportPackage.downloadCount} kez)` : ""}
              </span>
            ) : null}
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
        <JournalReviewPanel
          activeDecision={activeDecision}
          correctionDraft={correctionDraft}
          decisionStatus={decisionStatus}
          invoice={selectedInvoice}
          setCorrectionDraft={setCorrectionDraft}
          setDecision={setDecision}
        />
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
  correctionDraft,
  decisionStatus,
  invoice,
  setCorrectionDraft,
  setDecision,
}: {
  activeDecision?: LocalDecision;
  correctionDraft: CorrectionDraft;
  decisionStatus: string;
  invoice?: InvoiceRow;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setDecision: (action: DecisionAction) => void;
}) {
  const visibleDraftLines = invoice ? correctedDraftLines(invoice, correctionDraft) : [];
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
            <Info
              label="Musavir onayi"
              value={invoice.accountantDecisionAction ? `${invoice.accountantDecisionAction} / ${formatDateText(invoice.accountantReviewedAt)}` : "Yok"}
            />
          </div>

          {invoice.learningRuleReason ? <p className="reason">{invoice.learningRuleReason}</p> : null}
          {invoice.accountantDecisionReason ? <p className="reason">{invoice.accountantDecisionReason}</p> : null}

          <div className="correction-form" aria-label="Duzeltme alanlari">
            <label>
              <span>Gider hesabi</span>
              <input
                onChange={(event) =>
                  setCorrectionDraft({ ...correctionDraft, correctedAccountCode: event.target.value })
                }
                placeholder={invoice.selectedExpenseAccount || "770.01"}
                value={correctionDraft.correctedAccountCode}
              />
            </label>
            <label>
              <span>Cari hesabi</span>
              <input
                onChange={(event) =>
                  setCorrectionDraft({ ...correctionDraft, correctedCounterpartyCode: event.target.value })
                }
                placeholder={invoice.selectedSupplierAccount || invoice.counterpartyMatchCode || "320.01"}
                value={correctionDraft.correctedCounterpartyCode}
              />
            </label>
            <label className="wide">
              <span>Gerekce</span>
              <textarea
                onChange={(event) => setCorrectionDraft({ ...correctionDraft, reason: event.target.value })}
                placeholder="Musteriye ozel hesap/cari duzeltmesi veya kontrol gerekcesi"
                rows={3}
                value={correctionDraft.reason}
              />
            </label>
          </div>

          <div className="draft-lines">
            {visibleDraftLines.length ? (
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
                  {visibleDraftLines.map((line, index) => (
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
                {decisionStatus ? <p>{decisionStatus}</p> : null}
              </>
            ) : (
              <p>{decisionStatus || "Bu belge icin henuz musavir karari verilmedi."}</p>
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
