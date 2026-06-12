"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import { fallbackReviewData } from "./demo-data";
import {
  INTAKE_TABS,
  buildUploadIntakeMetadata,
  labelForIntakeCategory,
  normalizeIntakeCategory,
} from "./upload-intake";
import {
  ensureUploadWorkspace,
  buildClientOnboardingPackagePayload,
  createClientOnboardingPackage,
  createPortalInvite,
  loginWithPassword,
  parseTaxCertificateFromBackend,
  pickUploadUser,
  requestStatementAiSuggestions,
  resolveApiBaseUrl,
  setPortalPassword as setBackendPortalPassword,
  storeReviewDecision,
  uploadChartAccountsToBackend,
  uploadDocumentToBackend,
  uploadTaxCertificateToBackend,
} from "./upload-api";
import { buildPilotReadinessView, canUseLocalPilotFallback } from "./pilot-readiness";
import { fetchBackendPilotData, fetchBackendReadiness } from "./workspace-api";
import {
  buildClientCancellationViewModel,
  buildPortalDashboard,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
  statusFunnel,
} from "./portal-dashboard";
import {
  normalizeSessionForPortalConfig,
  PORTAL_NAV_ITEMS,
  portalConfigForRouteKey,
} from "./portal-routes";

type IntakeCategory = "sales_invoice" | "purchase_invoice" | "bank_statement" | "special_document";

type DraftLine = {
  account_code: string;
  description: string;
  debit: string;
  credit: string;
};

type StatementLineReview = {
  line_no: number;
  transaction_date: string;
  description: string;
  amount: string;
  direction: "in" | "out" | "";
  balance_after: string;
  counterparty_name: string;
  tax_id: string;
  iban: string;
  suggested_account_code: string;
  transaction_type: string;
  confidence: number;
  risk_flags: string[];
  review_reason: string;
  accountant_review_status?: string;
  counterparty_match_code?: string;
};

type StatementEntryReview = {
  statement_line_no: number;
  statement_fingerprint: string;
  source_document_ref: string;
  accountant_review_status?: string;
  risk_flags: string[];
  lines: DraftLine[];
};

type StatementAiSuggestionView = {
  line_no: number;
  transaction_type: string;
  suggested_account_code: string;
  confidence: number;
  reason: string;
  evidence: string[];
  risk_flags: string[];
  ai_used?: boolean;
  provider?: string;
  skipped_reason?: string;
  export_allowed: boolean;
};

type RulePromptView = {
  show: boolean;
  defaultScope: string;
  message: string;
  clientConsistentDecisionCount: number;
  officeDistinctClientCount: number;
  officeConsistentDecisionCount: number;
};

type PilotStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "review_required"
  | "export_ready"
  | "cancel_requested"
  | "cancel_approved"
  | "cancel_rejected"
  | "export_added"
  | "exported"
  | "post_export_correction_requested";

type PilotDocument = {
  id: string;
  clientId: string;
  clientName: string;
  fileName: string;
  documentType: string;
  intakeCategory: IntakeCategory;
  period: string;
  uploadedAt: string;
  uploadedBy: string;
  status: PilotStatus;
  provider: string;
  issueDate: string;
  amount: string;
  vatRates: string[];
  productLine: string;
  productCategory: string;
  businessRelation: string;
  accountTreatment: string;
  requiresAccountantReview: boolean;
  previewText: string;
  aiReason: string;
  aiProvider: string;
  aiSuggestedAccountCode: string;
  aiSuggestedCounterpartyCode: string;
  aiRiskFlags: string[];
  aiAccountReason: string;
  deterministicSummary: string;
  exportGateReason: string;
  selectedExpenseAccount: string;
  selectedVatAccount: string;
  selectedCounterpartyAccount: string;
  counterpartyConfidence: number;
  reviewReasons: string[];
  riskFlags: string[];
  draftLines: DraftLine[];
  statementLines: StatementLineReview[];
  statementEntries: StatementEntryReview[];
  statementAiSuggestions: StatementAiSuggestionView[];
  statementAiSummary: string;
  accountingIntent: string;
  accountingIntentConfidence: number;
  learningRuleScope: string;
  learningRuleReason: string;
  learningRuleSourceSummary: string;
  rulePrompt: RulePromptView;
};

type PilotClient = {
  clientId: string;
  clientName: string;
  taxId: string;
  userLabel: string;
  portalUserId: string;
  onboardingStatus: string;
};

type CancellationRequest = {
  id: string;
  documentId: string;
  clientId: string;
  fileName: string;
  requestedBy: string;
  requestedAt: string;
  reason: string;
  stage: "pre_export" | "post_export";
  status: "open" | "approved" | "rejected";
};

type ExportBasketItem = {
  id: string;
  clientId: string;
  clientName: string;
  documentIds: string[];
  documentCount: number;
  period: string;
  status: "ready" | "packaged";
};

type PilotData = {
  generatedFrom: string;
  clients: PilotClient[];
  documents: PilotDocument[];
  cancellationRequests: CancellationRequest[];
  exportBasket: ExportBasketItem[];
};

type PilotReadinessView = {
  status: string;
  statusLabel: string;
  productionLabel: string;
  offerLabel: string;
  exportLabel: string;
  zirveLabel: string;
  authLabel: string;
  storeLabel: string;
  aiLabel: string;
  blocking: string[];
  warnings: string[];
};

type ReviewData = {
  generatedFrom?: string;
  clientId?: string;
  clientName?: string;
  uploadQueue?: {
    id?: string;
    fileName?: string;
    kind?: string;
    intakeCategory?: string;
    uploadedBy?: string;
    status?: string;
    uploadedAt?: string;
  }[];
  portalUsers?: {
    userId?: string;
    displayName?: string;
    role?: string;
  }[];
  invoiceRows?: {
    documentRef?: string;
    fileName?: string;
    providerHint?: string;
    invoiceType?: string;
    intakeCategory?: string;
    issueDate?: string;
    payableTotal?: string;
    vatRates?: string[];
    status?: string;
    draftQuality?: string;
    isBalanced?: boolean;
    riskFlags?: string[];
    parseNotes?: string[];
    reviewReasonCodes?: string[];
    productLineHint?: string;
    productCategory?: string;
    productConfidence?: number;
    businessRelevanceReason?: string;
    businessRelevanceRelation?: string;
    businessRelevanceAccountTreatment?: string;
    businessRelevanceRequiresReview?: boolean;
    aiClassificationReason?: string;
    aiClassificationProvider?: string;
    aiClassificationSkippedReason?: string;
    aiSuggestedAccountCode?: string;
    aiSuggestedCounterpartyCode?: string;
    aiRiskFlags?: string[];
    aiAccountReason?: string;
    exportStatus?: string;
    selectedExpenseAccount?: string;
    selectedVatAccount?: string;
    selectedSupplierAccount?: string;
    counterpartyMatchCode?: string;
    counterpartyMatchConfidence?: number;
    processingMode?: string;
    deterministicChecks?: string[];
    exportGateReason?: string;
    draftLines?: DraftLine[];
    statementLines?: unknown[];
    statement_lines?: unknown[];
    statementEntries?: unknown[];
    statement_entries?: unknown[];
    statementAiSuggestions?: unknown[];
    statement_ai_suggestions?: unknown[];
    statementAiSummary?: string;
    statement_ai_summary?: string;
    accountingIntent?: string;
    accounting_intent?: string;
    accountingIntentConfidence?: number;
    accounting_intent_confidence?: number;
    learningRuleScope?: string;
    learning_rule_scope?: string;
    learningRuleReason?: string;
    learning_rule_reason?: string;
    learningRuleSourceSummary?: string;
    learning_rule_source_summary?: string;
    rulePrompt?: unknown;
    rule_prompt?: unknown;
  }[];
};

type PilotMode = "client" | "accountant" | "documents" | "clients" | "settings" | "exports" | "operations";
type PortalRouteKey = "home" | "mukellef" | "musavir" | "belgeler" | "mukellefler" | "ayarlar" | "cikti" | "operasyon";
type DocumentSegment = "invoices" | "bank_statements" | "other_documents";
type PortalNavItem = { mode: PilotMode; label: string; href: string };
type ReviewFilter = "all" | "review_required" | "export_ready" | "cancel_requested";
type ExportMode = "bulk" | "by_client";

type CorrectionDraft = {
  accountCode: string;
  counterpartyCode: string;
  reason: string;
};

type NewClientDraft = {
  clientId: string;
  title: string;
  taxId: string;
  activityDescription: string;
  naceCode: string;
  activityTags: string[];
  activityProfile: Record<string, unknown>;
  workplaceAddresses: string[];
  portalUserId: string;
  portalDisplayName: string;
};

type DashboardClientRow = {
  clientId: string;
  clientName: string;
  taxId: string;
  documentCount: number;
  pendingReviewCount: number;
  exportReadyCount: number;
  inProgressCount: number;
  cancellationCount: number;
  lastUploadedAt: string;
  status: string;
};

type ChartRow = {
  key: string;
  label: string;
  count: number;
};

type LocalSession = {
  userId: string;
  role: "client_user" | "accountant";
  sessionToken?: string;
  expiresAt?: string;
};

const SESSION_STORAGE_KEY = "fisora.privatePilot.session.v1";

const emptyPilotData: PilotData = {
  generatedFrom: "Backend bekleniyor",
  clients: [],
  documents: [],
  cancellationRequests: [],
  exportBasket: [],
};

const statusLabels: Record<PilotStatus, string> = {
  uploaded: "Yüklendi",
  queued: "Kuyrukta",
  processing: "İşleniyor",
  review_required: "Kontrol gerekli",
  export_ready: "Export hazır",
  cancel_requested: "İptal talebi",
  cancel_approved: "İptal kabul",
  cancel_rejected: "İptal red",
  export_added: "Çıktı listesinde",
  exported: "Çıktı alındı",
  post_export_correction_requested: "Export sonrası düzeltme",
};

const documentTypeLabels: Record<string, string> = {
  invoice: "Fatura",
  xml: "E-Fatura XML/PDF",
  bank: "Banka ekstresi",
  bank_statement: "Banka ekstresi",
  pos: "POS ekstresi",
  pos_statement: "POS ekstresi",
  special_document: "Özel belge",
  ALIS: "Alış faturası",
  SATIS: "Satış faturası",
};

const roleLabels: Record<LocalSession["role"], string> = {
  accountant: "Müşavir",
  client_user: "Mükellef",
};

function toIntakeCategory(value: unknown): IntakeCategory {
  return normalizeIntakeCategory(safeText(value)) as IntakeCategory;
}

function inferIntakeCategory(documentType: unknown, invoiceType?: unknown): IntakeCategory {
  const explicitType = safeText(documentType);
  if (explicitType === "bank" || explicitType === "bank_statement" || explicitType === "pos" || explicitType === "pos_statement") {
    return "bank_statement";
  }
  if (explicitType === "special_document") {
    return "special_document";
  }
  const explicitInvoiceType = safeText(invoiceType).toLocaleUpperCase("tr-TR");
  if (explicitInvoiceType === "SATIS") {
    return "sales_invoice";
  }
  return "purchase_invoice";
}

function documentPreviewTitle(document: PilotDocument) {
  if (document.intakeCategory === "bank_statement") return "EKSTRE";
  if (document.intakeCategory === "special_document") return "ÖZEL BELGE";
  return "FATURA";
}

function readStoredSession(): LocalSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LocalSession;
    if (!parsed.userId || !parsed.role) return null;
    return parsed;
  } catch {
    return null;
  }
}

function persistSession(session: LocalSession | null) {
  if (typeof window === "undefined") return;
  if (!session) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

function safeText(value: unknown, fallback = "") {
  return value == null || value === "" ? fallback : String(value);
}

function safeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function safeList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function safeNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeStatementLines(value: unknown): StatementLineReview[] {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const row = safeRecord(item);
    const direction = safeText(row.direction) as "in" | "out" | "";
    return {
      line_no: safeNumber(row.line_no ?? row.lineNo, index + 1),
      transaction_date: safeText(row.transaction_date ?? row.transactionDate),
      description: safeText(row.description),
      amount: safeText(row.amount, "0.00"),
      direction: direction === "in" || direction === "out" ? direction : "",
      balance_after: safeText(row.balance_after ?? row.balanceAfter),
      counterparty_name: safeText(row.counterparty_name ?? row.counterpartyName),
      tax_id: safeText(row.tax_id ?? row.taxId),
      iban: safeText(row.iban),
      suggested_account_code: safeText(row.suggested_account_code ?? row.suggestedAccountCode),
      transaction_type: safeText(row.transaction_type ?? row.transactionType, "unknown"),
      confidence: safeNumber(row.confidence, 0),
      risk_flags: safeList(row.risk_flags ?? row.riskFlags),
      review_reason: safeText(row.review_reason ?? row.reviewReason),
      accountant_review_status: safeText(row.accountant_review_status ?? row.accountantReviewStatus),
      counterparty_match_code: safeText(row.counterparty_match_code ?? row.counterpartyMatchCode),
    };
  });
}

function normalizeStatementEntries(value: unknown): StatementEntryReview[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const row = safeRecord(item);
    return {
      statement_line_no: safeNumber(row.statement_line_no ?? row.statementLineNo),
      statement_fingerprint: safeText(row.statement_fingerprint ?? row.statementFingerprint),
      source_document_ref: safeText(row.source_document_ref ?? row.sourceDocumentRef),
      accountant_review_status: safeText(row.accountant_review_status ?? row.accountantReviewStatus),
      risk_flags: safeList(row.risk_flags ?? row.riskFlags),
      lines: Array.isArray(row.lines) ? (row.lines as DraftLine[]) : [],
    };
  });
}

function normalizeStatementAiSuggestions(value: unknown): StatementAiSuggestionView[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const row = safeRecord(item);
    return {
      line_no: safeNumber(row.line_no ?? row.lineNo),
      transaction_type: safeText(row.transaction_type ?? row.transactionType, "unknown"),
      suggested_account_code: safeText(row.suggested_account_code ?? row.suggestedAccountCode),
      confidence: safeNumber(row.confidence, 0),
      reason: safeText(row.reason),
      evidence: safeList(row.evidence),
      risk_flags: safeList(row.risk_flags ?? row.riskFlags),
      ai_used: Boolean(row.ai_used ?? row.aiUsed),
      provider: safeText(row.provider),
      skipped_reason: safeText(row.skipped_reason ?? row.skippedReason),
      export_allowed: Boolean(row.export_allowed ?? row.exportAllowed),
    };
  });
}

function normalizeRulePrompt(value: unknown): RulePromptView {
  const row = safeRecord(value);
  return {
    show: Boolean(row.show),
    defaultScope: safeText(row.defaultScope ?? row.default_scope),
    message: safeText(row.message),
    clientConsistentDecisionCount: safeNumber(row.clientConsistentDecisionCount ?? row.client_consistent_decision_count),
    officeDistinctClientCount: safeNumber(row.officeDistinctClientCount ?? row.office_distinct_client_count),
    officeConsistentDecisionCount: safeNumber(row.officeConsistentDecisionCount ?? row.office_consistent_decision_count),
  };
}

function normalizeStatus(value?: string): PilotStatus {
  if (value === "export_ready" || value === "auto_ready") return "export_ready";
  if (value === "processing") return "processing";
  if (value === "queued" || value === "stored") return "queued";
  if (value === "uploaded") return "uploaded";
  if (value === "cancel_requested") return "cancel_requested";
  if (value === "cancel_approved") return "cancel_approved";
  if (value === "cancel_rejected") return "cancel_rejected";
  if (value === "export_added") return "export_added";
  if (value === "exported") return "exported";
  if (value === "post_export_correction_requested") return "post_export_correction_requested";
  return "review_required";
}

function parseDateParts(value: string) {
  const dotted = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
  if (dotted) return { year: dotted[3], month: dotted[2].padStart(2, "0") };
  const iso = value.match(/^(\d{4})-(\d{2})/);
  if (iso) return { year: iso[1], month: iso[2] };
  return null;
}

function periodFromDate(value: string, fallback = "2026-06") {
  const parsed = parseDateParts(value);
  return parsed ? `${parsed.year}-${parsed.month}` : fallback;
}

function periodLabel(period: string) {
  const [year, month] = period.split("-");
  if (!year || !month) return period;
  return `${month}.${year}`;
}

function formatDateText(value: string) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("tr-TR");
}

function formatStatus(status: PilotStatus) {
  return statusLabels[status] ?? status;
}

function isInProgress(status: PilotStatus) {
  return status === "uploaded" || status === "queued" || status === "processing";
}

function isCancelStatus(status: PilotStatus) {
  return status === "cancel_requested" || status === "post_export_correction_requested";
}

const statementTypeLabels: Record<string, string> = {
  pos_collection: "POS tahsilat",
  pos_blocked: "POS bloke",
  tax: "Vergi",
  sgk: "SGK",
  bank_fee: "Banka masrafı",
  eft: "EFT/Havale",
  credit_card: "Kredi/kart",
  loan: "Kredi",
  payroll: "Maaş",
  transfer: "Transfer",
  refund: "İade",
  reversal: "Ters kayıt",
  unknown: "Bilinmeyen",
};

function statementDirectionLabel(direction: StatementLineReview["direction"]) {
  if (direction === "in") return "Giriş";
  if (direction === "out") return "Çıkış";
  return "-";
}

function statementReviewStatus(action: string) {
  if (action === "approve" || action === "approve_with_changes" || action === "suggest_for_similar") return "approved";
  if (action === "exclude_export" || action === "exclude_from_export" || action === "out_of_scope") return "rejected";
  return "review_required";
}

function statementStatusLabel(status?: string) {
  if (status === "approved") return "Onaylı";
  if (status === "rejected") return "Red";
  if (status === "review_required") return "Kontrol";
  return "Bekliyor";
}

function reviewActionLabel(action: string) {
  if (action === "approve") return "Onaylandı";
  if (action === "approve_with_changes") return "Düzeltilip onaylandı";
  if (action === "suggest_for_similar") return "Kural adayı yapıldı";
  if (action === "exclude_export") return "Export dışı bırakıldı";
  return "Kontrolde tutuldu";
}

function reviewedStatementRiskFlags(flags: string[], status: string) {
  if (status === "approved") {
    const removable = new Set([
      "ai_invalid_schema",
      "counterparty_match_review_required",
      "counterparty_not_found",
      "learning_rule_review_required",
      "statement_accountant_approval_required",
      "statement_review_required",
    ]);
    return flags.filter((flag) => !removable.has(flag));
  }
  if (status === "rejected") return Array.from(new Set([...flags, "statement_line_rejected"]));
  return Array.from(new Set([...flags, "statement_review_required"]));
}

function replaceStatementCounterpart(lines: DraftLine[], accountCode: string) {
  if (!accountCode.trim()) return lines;
  let replaced = false;
  return lines.map((line) => {
    if (replaced || line.account_code.startsWith("102")) return line;
    replaced = true;
    return { ...line, account_code: accountCode };
  });
}

function applyStatementLineDecision(
  document: PilotDocument,
  lineNo: number,
  action: string,
  correctedAccountCode: string,
  correctedCounterpartyCode: string,
  reviewer: string,
  reason: string,
): PilotDocument {
  const reviewStatus = statementReviewStatus(action);
  const newAccount = correctedCounterpartyCode.trim() || correctedAccountCode.trim();
  const reviewedAt = new Date().toLocaleString("tr-TR");
  const statementLines = document.statementLines.map((line) => {
    if (line.line_no !== lineNo) return line;
    return {
      ...line,
      suggested_account_code: newAccount || line.suggested_account_code,
      counterparty_match_code: newAccount || line.counterparty_match_code,
      confidence: newAccount ? 100 : line.confidence,
      accountant_review_status: reviewStatus,
      risk_flags: reviewedStatementRiskFlags(line.risk_flags, reviewStatus),
      review_reason: reason || line.review_reason,
    };
  });
  const statementEntries = document.statementEntries.map((entry) => {
    if (entry.statement_line_no !== lineNo) return entry;
    return {
      ...entry,
      accountant_review_status: reviewStatus,
      risk_flags: reviewedStatementRiskFlags(entry.risk_flags, reviewStatus),
      lines: replaceStatementCounterpart(entry.lines, newAccount),
    };
  });
  const allApproved = statementLines.length > 0 && statementLines.every((line) => line.accountant_review_status === "approved");
  return {
    ...document,
    status: allApproved ? "export_ready" : "review_required",
    exportGateReason: allApproved
      ? "Banka satırları müşavir onayından geçti; export sepetine alınabilir."
      : "Banka satırlarında müşavir kontrolü sürüyor.",
    deterministicSummary: `${document.deterministicSummary}${document.deterministicSummary ? ", " : ""}statement_line_reviewed:${lineNo}`,
    statementLines,
    statementEntries,
    statementAiSummary: `${statementStatusLabel(reviewStatus)} / ${reviewer} / ${reviewedAt}`,
  };
}

function journalDraftLinesForDocument(document: PilotDocument, selectedStatementLineNo: number): DraftLine[] {
  if (document.intakeCategory !== "bank_statement" && document.statementLines.length === 0) return document.draftLines;
  const selectedEntry = document.statementEntries.find((entry) => entry.statement_line_no === selectedStatementLineNo);
  return selectedEntry?.lines ?? [];
}

function normalizeReviewData(raw: ReviewData): PilotData {
  const clientId = safeText(raw.clientId, "private-pilot-client");
  const clientName = safeText(raw.clientName, "Private Pilot Mükellef");
  const clientUser = raw.portalUsers?.find((user) => user.role === "client_user") ?? raw.portalUsers?.[0];
  const documentsFromRows = (raw.invoiceRows ?? []).map((row, index): PilotDocument => {
    const fileName = safeText(row.documentRef || row.fileName, `pilot-belge-${index + 1}.pdf`);
    const status = normalizeStatus(row.exportStatus || row.status);
    return {
      id: safeText(row.documentRef || row.fileName, `${clientId}-doc-${index + 1}`),
      clientId,
      clientName,
      fileName,
      documentType: safeText(row.invoiceType, "invoice"),
      intakeCategory: toIntakeCategory(row.intakeCategory || inferIntakeCategory("invoice", row.invoiceType)),
      period: periodFromDate(safeText(row.issueDate), "2026-04"),
      uploadedAt: safeText(row.issueDate, "01.04.2026"),
      uploadedBy: safeText(clientUser?.displayName, clientName),
      status,
      provider: safeText(row.providerHint, "Tedarikçi bilinmiyor"),
      issueDate: safeText(row.issueDate, "-"),
      amount: safeText(row.payableTotal, "-"),
      vatRates: Array.isArray(row.vatRates) ? row.vatRates.map(String) : [],
      productLine: safeText(row.productLineHint, "-"),
      productCategory: safeText(row.productCategory, "-"),
      businessRelation: safeText(row.businessRelevanceRelation, "-"),
      accountTreatment: safeText(row.businessRelevanceAccountTreatment, "-"),
      requiresAccountantReview: Boolean(row.businessRelevanceRequiresReview),
      previewText: [
        safeText(row.providerHint, "Tedarikçi bilinmiyor"),
        safeText(row.productLineHint, "Belge kalemi okunuyor"),
        safeText(row.payableTotal, "-"),
      ].join(" / "),
      aiReason:
        safeText(row.aiClassificationReason) ||
        safeText(row.businessRelevanceReason) ||
        safeText(row.aiClassificationSkippedReason, "AI/kural gerekçesi yok"),
      aiProvider: safeText(row.aiClassificationProvider, "-"),
      aiSuggestedAccountCode: safeText(row.aiSuggestedAccountCode, ""),
      aiSuggestedCounterpartyCode: safeText(row.aiSuggestedCounterpartyCode, ""),
      aiRiskFlags: Array.isArray(row.aiRiskFlags) ? row.aiRiskFlags.map(String) : [],
      aiAccountReason: safeText(row.aiAccountReason, ""),
      deterministicSummary: (row.deterministicChecks ?? []).join(", ") || (row.isBalanced ? "balanced_entry" : "denge kontrolü gerekli"),
      exportGateReason: safeText(row.exportGateReason, status === "export_ready" ? "Çıktı listesine alınabilir." : "Müşavir kontrolü gerekiyor."),
      selectedExpenseAccount: safeText(row.selectedExpenseAccount, "-"),
      selectedVatAccount: safeText(row.selectedVatAccount, "-"),
      selectedCounterpartyAccount: safeText(row.selectedSupplierAccount || row.counterpartyMatchCode, "-"),
      counterpartyConfidence: Number(row.counterpartyMatchConfidence ?? 0),
      reviewReasons: Array.isArray(row.reviewReasonCodes) ? row.reviewReasonCodes.map(String) : [],
      riskFlags: Array.isArray(row.riskFlags) ? row.riskFlags.map(String) : [],
      draftLines: Array.isArray(row.draftLines) ? row.draftLines : [],
      statementLines: normalizeStatementLines(row.statementLines ?? row.statement_lines),
      statementEntries: normalizeStatementEntries(row.statementEntries ?? row.statement_entries),
      statementAiSuggestions: normalizeStatementAiSuggestions(row.statementAiSuggestions ?? row.statement_ai_suggestions),
      statementAiSummary: safeText(row.statementAiSummary ?? row.statement_ai_summary),
      accountingIntent: safeText(row.accountingIntent ?? row.accounting_intent),
      accountingIntentConfidence: safeNumber(row.accountingIntentConfidence ?? row.accounting_intent_confidence),
      learningRuleScope: safeText(row.learningRuleScope ?? row.learning_rule_scope),
      learningRuleReason: safeText(row.learningRuleReason ?? row.learning_rule_reason),
      learningRuleSourceSummary: safeText(row.learningRuleSourceSummary ?? row.learning_rule_source_summary),
      rulePrompt: normalizeRulePrompt(row.rulePrompt ?? row.rule_prompt),
    };
  });

  const rowFileNames = new Set(documentsFromRows.map((document) => document.fileName));
  const uploadOnlyDocuments = (raw.uploadQueue ?? [])
    .filter((item) => !rowFileNames.has(safeText(item.fileName)))
    .map((item, index): PilotDocument => ({
      id: safeText(item.id, `${clientId}-upload-${index + 1}`),
      clientId,
      clientName,
      fileName: safeText(item.fileName, `yuklenen-belge-${index + 1}`),
      documentType: safeText(item.kind, "invoice"),
      intakeCategory: toIntakeCategory(item.intakeCategory || inferIntakeCategory(item.kind)),
      period: periodFromDate(safeText(item.uploadedAt), "2026-06"),
      uploadedAt: safeText(item.uploadedAt, "-"),
      uploadedBy: safeText(item.uploadedBy, safeText(clientUser?.displayName, clientName)),
      status: normalizeStatus(item.status),
      provider: "İşleme alınacak belge",
      issueDate: "-",
      amount: "-",
      vatRates: [],
      productLine: "Belge kuyrukta",
      productCategory: "-",
      businessRelation: "-",
      accountTreatment: "-",
      requiresAccountantReview: true,
      previewText: "Belge yüklendi, otomatik kuyruğa alınacak.",
      aiReason: "Henüz yorum yok.",
      aiProvider: "-",
      aiSuggestedAccountCode: "",
      aiSuggestedCounterpartyCode: "",
      aiRiskFlags: [],
      aiAccountReason: "",
      deterministicSummary: "Worker sonucu bekleniyor.",
      exportGateReason: "İşleme tamamlanmadan çıktıya eklenemez.",
      selectedExpenseAccount: "-",
      selectedVatAccount: "-",
      selectedCounterpartyAccount: "-",
      counterpartyConfidence: 0,
      reviewReasons: [],
      riskFlags: [],
      draftLines: [],
      statementLines: [],
      statementEntries: [],
      statementAiSuggestions: [],
      statementAiSummary: "",
      accountingIntent: "",
      accountingIntentConfidence: 0,
      learningRuleScope: "",
      learningRuleReason: "",
      learningRuleSourceSummary: "",
      rulePrompt: normalizeRulePrompt({}),
    }));

  const documents = [...documentsFromRows, ...uploadOnlyDocuments];
  return {
    generatedFrom: safeText(raw.generatedFrom, "Private pilot yerel yedek veri"),
    clients: [
      {
        clientId,
        clientName,
        taxId: "pilot-local",
        portalUserId: safeText(clientUser?.userId, "pilot-mukellef-user"),
        userLabel: safeText(clientUser?.displayName, "Mükellef kullanıcısı"),
        onboardingStatus: "Hesap planı ve mükellef kartı pilot veride hazır",
      },
    ],
    documents,
    cancellationRequests: documents.length > 1
      ? [
          {
            id: `${documents[1].id}-cancel`,
            documentId: documents[1].id,
            clientId,
            fileName: documents[1].fileName,
            requestedBy: safeText(clientUser?.displayName, "Mükellef kullanıcısı"),
            requestedAt: "04.06.2026 10:30",
            reason: "Mükellef belge için iptal veya düzeltme kontrolü istedi.",
            stage: documents[1].status === "export_ready" ? "post_export" : "pre_export",
            status: "open",
          },
        ]
      : [],
    exportBasket: documents.some((document) => document.status === "export_ready")
      ? [
          {
            id: `${clientId}-basket`,
            clientId,
            clientName,
            documentIds: documents.filter((document) => document.status === "export_ready").map((document) => document.id),
            documentCount: documents.filter((document) => document.status === "export_ready").length,
            period: documents.find((document) => document.status === "export_ready")?.period ?? "2026-06",
            status: "ready",
          },
        ]
      : [],
  };
}

function normalizePilotData(raw: unknown): PilotData {
  const maybePilot = raw as Partial<PilotData>;
  if (Array.isArray(maybePilot.clients) && Array.isArray(maybePilot.documents)) {
    return {
      generatedFrom: safeText(maybePilot.generatedFrom, "Yerel pilot veri"),
      clients: (maybePilot.clients as PilotClient[]).map((client) => ({
        ...client,
        portalUserId: safeText(
          client.portalUserId || (client as PilotClient & { userId?: string }).userId,
          "pilot-mukellef-user",
        ),
      })),
      documents: (maybePilot.documents as PilotDocument[]).map((document) => ({
        ...document,
        intakeCategory: toIntakeCategory(document.intakeCategory || inferIntakeCategory(document.documentType)),
        status: normalizeStatus(document.status),
        aiProvider: safeText(document.aiProvider, "-"),
        aiSuggestedAccountCode: safeText(document.aiSuggestedAccountCode, ""),
        aiSuggestedCounterpartyCode: safeText(document.aiSuggestedCounterpartyCode, ""),
        aiRiskFlags: Array.isArray(document.aiRiskFlags) ? document.aiRiskFlags : [],
        aiAccountReason: safeText(document.aiAccountReason, ""),
        vatRates: Array.isArray(document.vatRates) ? document.vatRates : [],
        reviewReasons: Array.isArray(document.reviewReasons) ? document.reviewReasons : [],
        riskFlags: Array.isArray(document.riskFlags) ? document.riskFlags : [],
        draftLines: Array.isArray(document.draftLines) ? document.draftLines : [],
        statementLines: normalizeStatementLines(document.statementLines),
        statementEntries: normalizeStatementEntries(document.statementEntries),
        statementAiSuggestions: normalizeStatementAiSuggestions(document.statementAiSuggestions),
        statementAiSummary: safeText(document.statementAiSummary),
        accountingIntent: safeText(document.accountingIntent, ""),
        accountingIntentConfidence: safeNumber(document.accountingIntentConfidence),
        learningRuleScope: safeText(document.learningRuleScope, ""),
        learningRuleReason: safeText(document.learningRuleReason, ""),
        learningRuleSourceSummary: safeText(document.learningRuleSourceSummary, ""),
        rulePrompt: normalizeRulePrompt(document.rulePrompt),
      })),
      cancellationRequests: Array.isArray(maybePilot.cancellationRequests) ? (maybePilot.cancellationRequests as CancellationRequest[]) : [],
      exportBasket: Array.isArray(maybePilot.exportBasket) ? (maybePilot.exportBasket as ExportBasketItem[]) : [],
    };
  }
  return normalizeReviewData(raw as ReviewData);
}

async function fetchJson(path: string) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} not found`);
  return response.json();
}

export function FisoraPortalApp({ routeKey = "home" }: { routeKey?: PortalRouteKey | string }) {
  const portalConfig = portalConfigForRouteKey(routeKey);
  const lockedRole = portalConfig.lockedRole as LocalSession["role"] | undefined;
  const visibleNavItems = (PORTAL_NAV_ITEMS as PortalNavItem[]).filter((item) =>
    portalConfig.visibleModes.includes(item.mode),
  );
  const [data, setData] = useState<PilotData>(emptyPilotData);
  const [source, setSource] = useState("Backend bekleniyor");
  const [readinessPayload, setReadinessPayload] = useState<Record<string, unknown> | null>(null);
  const [localFallbackAllowed, setLocalFallbackAllowed] = useState(false);
  const [mode, setModeState] = useState<PilotMode>(portalConfig.initialMode as PilotMode);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [selectedIntakeCategory, setSelectedIntakeCategory] = useState<IntakeCategory>("purchase_invoice");
  const [selectedDocumentSegment, setSelectedDocumentSegment] = useState<DocumentSegment>("invoices");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("review_required");
  const [clientSearch, setClientSearch] = useState("");
  const [session, setSession] = useState<LocalSession | null>(() =>
    normalizeSessionForPortalConfig(readStoredSession(), portalConfig),
  );
  const [loginUserId, setLoginUserId] = useState(portalConfig.defaultUserId);
  const [loginPassword, setLoginPassword] = useState("");
  const [loginRole, setLoginRole] = useState<"client_user" | "accountant">(portalConfig.defaultRole as "client_user" | "accountant");
  const [loginStatus, setLoginStatus] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [clientCancellationDocumentId, setClientCancellationDocumentId] = useState("");
  const [decisionStatus, setDecisionStatus] = useState("");
  const [statementAiStatus, setStatementAiStatus] = useState("");
  const [selectedStatementLineNo, setSelectedStatementLineNo] = useState(0);
  const [uploadStatus, setUploadStatus] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [exportMode, setExportMode] = useState<ExportMode>("bulk");
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>({
    accountCode: "",
    counterpartyCode: "",
    reason: "",
  });
  const [newClientDraft, setNewClientDraft] = useState<NewClientDraft>({
    clientId: "",
    title: "",
    taxId: "",
    activityDescription: "",
    naceCode: "",
    activityTags: [],
    activityProfile: {},
    workplaceAddresses: [],
    portalUserId: "",
    portalDisplayName: "",
  });
  const [newClientTaxCertificateFile, setNewClientTaxCertificateFile] = useState<File | null>(null);
  const [newClientTaxCertificateInputKey, setNewClientTaxCertificateInputKey] = useState(0);
  const [newClientStatus, setNewClientStatus] = useState("");
  const [chartUploadStatus, setChartUploadStatus] = useState("");
  const [inviteStatus, setInviteStatus] = useState("");
  const [portalPassword, setPortalPasswordDraft] = useState("");
  const [portalPasswordStatus, setPortalPasswordStatus] = useState("");

  function applyPilotData(payload: PilotData, nextSource: string) {
    setData(payload);
    setSource(nextSource);
    setSelectedClientId((current) =>
      current && payload.clients.some((client) => client.clientId === current)
        ? current
        : payload.clients[0]?.clientId ?? "",
    );
    setSelectedPeriod(Array.from(new Set(payload.documents.map((document) => document.period))).sort().at(-1) ?? "");
  }

  async function refreshBackendPilotData(shouldCancel: () => boolean = () => false) {
    try {
      const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
      const backendPayload = await fetchBackendPilotData({
        apiBaseUrl,
        sessionToken: session?.sessionToken,
        userId: session?.userId || portalConfig.defaultUserId,
      });
      const payload = normalizePilotData(backendPayload as PilotData);
      if (!payload.clients.length) return false;
      if (shouldCancel()) return true;
      applyPilotData(payload, payload.generatedFrom || "Backend workspace");
      return true;
    } catch {
      return false;
    }
  }

  async function refreshBackendReadiness(shouldCancel: () => boolean = () => false) {
    try {
      const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
      const payload = await fetchBackendReadiness({ apiBaseUrl });
      if (shouldCancel()) return true;
      setReadinessPayload(payload as Record<string, unknown>);
      return true;
    } catch {
      if (!shouldCancel()) setReadinessPayload(null);
      return false;
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadPilotData() {
      const pageUrl = typeof window === "undefined" ? "" : window.location.href;
      const allowLocalFallback = canUseLocalPilotFallback({
        pageUrl,
        explicitAllow: process.env.NEXT_PUBLIC_FISORA_ALLOW_LOCAL_FALLBACK === "true",
      });
      if (!cancelled) setLocalFallbackAllowed(allowLocalFallback);
      await refreshBackendReadiness(() => cancelled);
      if (await refreshBackendPilotData(() => cancelled)) return;
      if (!allowLocalFallback) {
        if (!cancelled) {
          applyPilotData(emptyPilotData, "Backend workspace erisilemedi");
        }
        return;
      }
      const paths = ["/local-pilot-data.json", "/local-workspace-data.json", "/local-review-data.json"];
      for (const path of paths) {
        try {
          const payload = normalizePilotData(await fetchJson(path));
          if (cancelled) return;
          applyPilotData(payload, path);
          return;
        } catch {
          // Try the next private/local source.
        }
      }
      const fallback = normalizeReviewData(fallbackReviewData as ReviewData);
      if (cancelled) return;
      applyPilotData(fallback, "Private pilot demo verisi");
    }
    void loadPilotData();
    return () => {
      cancelled = true;
    };
  }, [routeKey, session?.sessionToken, session?.userId]);

  const clients = data.clients;
  const selectedClient = clients.find((client) => client.clientId === selectedClientId) ?? clients[0];
  const allPeriods = useMemo(() => {
    return Array.from(new Set(data.documents.map((document) => document.period))).sort().reverse();
  }, [data.documents]);
  const clientDocuments = useMemo(() => {
    return data.documents.filter((document) => document.clientId === selectedClient?.clientId);
  }, [data.documents, selectedClient?.clientId]);
  const periodDocuments = useMemo(() => {
    return clientDocuments.filter((document) => !selectedPeriod || document.period === selectedPeriod);
  }, [clientDocuments, selectedPeriod]);
  const visibleReviewDocuments = useMemo(() => {
    if (reviewFilter === "all") return clientDocuments;
    if (reviewFilter === "cancel_requested") return clientDocuments.filter((document) => isCancelStatus(document.status));
    return clientDocuments.filter((document) => document.status === reviewFilter);
  }, [clientDocuments, reviewFilter]);
  const segmentedClientDocuments = useMemo(() => {
    return documentsForProcessing({
      documents: data.documents,
      clientId: selectedClient?.clientId,
      segment: selectedDocumentSegment,
    }) as PilotDocument[];
  }, [data.documents, selectedClient?.clientId, selectedDocumentSegment]);
  const visibleProcessingDocuments = useMemo(() => {
    if (reviewFilter === "all") return segmentedClientDocuments;
    if (reviewFilter === "cancel_requested") return segmentedClientDocuments.filter((document) => isCancelStatus(document.status));
    return segmentedClientDocuments.filter((document) => document.status === reviewFilter);
  }, [reviewFilter, segmentedClientDocuments]);
  const activeReviewDocuments = mode === "documents" ? visibleProcessingDocuments : visibleReviewDocuments;
  const selectedDocument = activeReviewDocuments.find((document) => document.id === selectedDocumentId);
  const clientSelectedDocument = periodDocuments.find((document) => document.id === selectedDocumentId);
  const selectedStatementLineKey = selectedDocument?.statementLines.map((line) => line.line_no).join("|") ?? "";
  useEffect(() => {
    const firstLineNo = selectedDocument?.statementLines[0]?.line_no ?? 0;
    if (!firstLineNo) {
      setSelectedStatementLineNo(0);
      return;
    }
    const hasSelectedLine = selectedDocument?.statementLines.some((line) => line.line_no === selectedStatementLineNo);
    if (!hasSelectedLine) setSelectedStatementLineNo(firstLineNo);
  }, [selectedDocument?.id, selectedStatementLineKey, selectedStatementLineNo]);
  const filteredClients = useMemo(() => {
    const query = clientSearch.trim().toLocaleLowerCase("tr-TR");
    if (!query) return clients;
    return clients.filter((client) => `${client.clientName} ${client.clientId} ${client.taxId}`.toLocaleLowerCase("tr-TR").includes(query));
  }, [clientSearch, clients]);
  const openCancellationRequests = data.cancellationRequests.filter((request) => request.status === "open");
  const dashboardMetrics = useMemo(() => buildPortalDashboard(data), [data]);
  const dashboardClientRows = useMemo(() => clientDashboardRows(data), [data]);
  const intakeDistribution = useMemo(() => documentIntakeDistribution(data.documents), [data.documents]);
  const funnelRows = useMemo(() => statusFunnel(data.documents), [data.documents]);
  const uploadTrackingRows = useMemo(() => clientUploadTracking(data), [data]);
  const readinessView = useMemo(
    () => buildPilotReadinessView(readinessPayload) as PilotReadinessView,
    [readinessPayload],
  );
  const visibleDashboardClientRows = useMemo(() => {
    const visibleIds = new Set(filteredClients.map((client) => client.clientId));
    return dashboardClientRows.filter((row: { clientId: string }) => visibleIds.has(row.clientId));
  }, [dashboardClientRows, filteredClients]);

  function setMode(nextMode: PilotMode) {
    if (portalConfig.visibleModes.includes(nextMode)) setModeState(nextMode);
  }

  async function login() {
    const userId = loginUserId.trim() || "pilot-user";
    const password = loginPassword.trim();
    const effectiveRole = (lockedRole ?? loginRole) as "client_user" | "accountant";
    if (password) {
      setLoginStatus("Backend session açılıyor.");
      try {
        const backendSession = await loginWithPassword({
          apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
          userId,
          password,
        });
        const nextSession: LocalSession = {
          userId: backendSession.userId || userId,
          role: effectiveRole,
          sessionToken: backendSession.sessionToken,
          expiresAt: backendSession.expiresAt,
        };
        persistSession(nextSession);
        setSession(nextSession);
        setLoginPassword("");
        setLoginStatus(`${nextSession.userId} için backend session açıldı.`);
        setMode(nextSession.role === "client_user" ? "client" : (portalConfig.initialMode as PilotMode));
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setLoginStatus(`Backend session açılamadı. ${message}`);
        return;
      }
    }
    if (!localFallbackAllowed) {
      setLoginStatus("Bu serverda sifresiz lokal pilot oturumu kapali. Backend sifresi ile girin.");
      return;
    }
    const nextSession: LocalSession = { userId, role: effectiveRole };
    persistSession(nextSession);
    setSession(nextSession);
    setLoginStatus(`${nextSession.userId} için lokal private pilot oturumu açıldı.`);
    setMode(nextSession.role === "client_user" ? "client" : (portalConfig.initialMode as PilotMode));
  }

  function logout() {
    persistSession(null);
    setSession(null);
    setLoginStatus("Oturum kapatıldı.");
  }

  function exitPortal() {
    logout();
    if (typeof window !== "undefined") window.location.assign("/");
  }

  function selectAdjacentReviewDocument(direction: 1 | -1 = 1) {
    if (!activeReviewDocuments.length || !selectedDocument) return;
    const currentIndex = activeReviewDocuments.findIndex((document) => document.id === selectedDocument.id);
    const nextDocument =
      activeReviewDocuments[currentIndex + direction] ??
      activeReviewDocuments[currentIndex - direction] ??
      activeReviewDocuments[0];
    if (nextDocument) setSelectedDocumentId(nextDocument.id);
  }

  async function approveSelectedAndMoveNext() {
    if (!selectedDocument) return;
    const selectedLineIndex = selectedDocument.statementLines.findIndex((line) => line.line_no === selectedStatementLineNo);
    if (selectedDocument.statementLines.length && selectedLineIndex >= 0) {
      await saveStatementLineDecision("approve");
      const nextLine = selectedDocument.statementLines[selectedLineIndex + 1];
      if (nextLine) {
        setSelectedStatementLineNo(nextLine.line_no);
        return;
      }
      selectAdjacentReviewDocument(1);
      return;
    }
    await saveDecision("approve");
    selectAdjacentReviewDocument(1);
  }

  async function createNewClient() {
    if (!newClientDraft.title.trim()) {
      setNewClientStatus("Mükellef adı gerekli.");
      return;
    }
    const payload = buildClientOnboardingPackagePayload(newClientDraft);
    const taxCertificateFile = newClientTaxCertificateFile;
    const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
    const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
    setNewClientStatus(taxCertificateFile ? "Mükellef kaydediliyor, vergi levhası yüklenecek." : "Mükellef kaydediliyor.");
    try {
      await createClientOnboardingPackage({
        apiBaseUrl,
        client: newClientDraft,
        sessionToken: session?.sessionToken,
        userId: actingUserId,
      });
      setSelectedClientId(payload.client.client_id);
      let certificateStatus = "";
      if (taxCertificateFile) {
        setNewClientStatus("Mükellef kaydedildi. Vergi levhası yükleniyor.");
        try {
          await uploadTaxCertificateToBackend({
            apiBaseUrl,
            clientId: payload.client.client_id,
            userId: actingUserId,
            uploadedBy: actingUserId,
            sessionToken: session?.sessionToken,
            file: taxCertificateFile,
          });
          certificateStatus = " Vergi levhası yüklendi.";
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          certificateStatus = ` Vergi levhası yüklenemedi: ${message}`;
        }
      }
      setNewClientDraft({
        clientId: "",
        title: "",
        taxId: "",
        activityDescription: "",
        naceCode: "",
        activityTags: [],
        activityProfile: {},
        workplaceAddresses: [],
        portalUserId: "",
        portalDisplayName: "",
      });
      setNewClientTaxCertificateFile(null);
      setNewClientTaxCertificateInputKey((current) => current + 1);
      setNewClientStatus(`${payload.client.title} eklendi.${certificateStatus}`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNewClientStatus(`Mükellef kaydedilemedi. ${message}`);
    }
  }

  async function selectNewClientTaxCertificate(file: File | null) {
    setNewClientTaxCertificateFile(file);
    if (!file) return;
    const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
    const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
    setNewClientStatus(`${file.name} vergi levhası okunuyor.`);
    try {
      const extraction = await parseTaxCertificateFromBackend({
        apiBaseUrl,
        userId: actingUserId,
        sessionToken: session?.sessionToken,
        file,
      });
      const title = String(extraction?.title || "").trim();
      const taxId = String(extraction?.tax_id || "").trim();
      const activityDescription = String(extraction?.activity_description || "").trim();
      const naceCode = String(extraction?.nace_code || "").trim();
      const activityTags = Array.isArray(extraction?.activity_tags)
        ? (extraction.activity_tags as unknown[]).map((value) => String(value).trim()).filter(Boolean)
        : [];
      const activityProfile =
        extraction?.activity_profile && typeof extraction.activity_profile === "object"
          ? (extraction.activity_profile as Record<string, unknown>)
          : {};
      const workplaceAddresses = Array.isArray(extraction?.workplace_addresses)
        ? (extraction.workplace_addresses as unknown[]).map((value) => String(value).trim()).filter(Boolean)
        : [];
      setNewClientDraft((current) => ({
        ...current,
        title: current.title.trim() || title,
        taxId: current.taxId.trim() || taxId,
        activityDescription: current.activityDescription.trim() || activityDescription,
        naceCode: current.naceCode.trim() || naceCode,
        activityTags: current.activityTags.length ? current.activityTags : activityTags,
        activityProfile: Object.keys(current.activityProfile).length ? current.activityProfile : activityProfile,
        workplaceAddresses: current.workplaceAddresses.length ? current.workplaceAddresses : workplaceAddresses,
      }));
      const filledFields = [
        title ? "unvan" : "",
        taxId ? "VKN" : "",
        activityDescription || naceCode ? "faaliyet" : "",
        activityTags.length ? "faaliyet tag" : "",
        workplaceAddresses.length ? "adres" : "",
      ].filter(Boolean);
      const confidence = Number(extraction?.confidence || 0);
      const profileLabel = String(activityProfile.display_label || "").trim();
      const profileConfidence = Number(activityProfile.confidence || 0);
      const profileSummary = profileLabel ? `Profil: ${profileLabel}${profileConfidence ? ` ${profileConfidence}` : ""}` : "";
      const note = filledFields.length
        ? `Vergi levhası okundu: ${filledFields.join(", ")}${confidence ? ` / güven ${confidence}` : ""}.`
        : "Vergi levhasından alan okunamadı; elle kayıt yapabilirsiniz.";
      setNewClientStatus(profileSummary ? `${note} ${profileSummary}` : note);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNewClientStatus(`Vergi levhası okunamadı. Elle devam edebilirsiniz. ${message}`);
    }
  }

  async function uploadChartAccounts(files: FileList | null) {
    const file = files?.[0];
    if (!file || !selectedClient) return;
    setChartUploadStatus(`${file.name} hesap plani import ediliyor...`);
    try {
      const result = await uploadChartAccountsToBackend({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedClient.clientId,
        userId: session?.userId || loginUserId.trim() || "mali-musavir",
        sessionToken: session?.sessionToken,
        file,
      });
      setChartUploadStatus(`${selectedClient.clientName}: ${result.account_count ?? 0} hesap backend store'a yazildi.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setChartUploadStatus(`Hesap plani importu tamamlanamadi. ${message}`);
    }
  }

  async function createInviteForSelectedClient() {
    if (!selectedClient) return;
    const userId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
    setInviteStatus(`${userId} icin davet tokeni hazirlaniyor...`);
    try {
      const result = await createPortalInvite({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        userId,
        displayName: selectedClient.userLabel || selectedClient.clientName,
        clientId: selectedClient.clientId,
        invitedBy: session?.userId || loginUserId.trim() || "mali-musavir",
        sessionToken: session?.sessionToken,
        userHeader: session?.userId || loginUserId.trim(),
      });
      setInviteStatus(`Davet tokeni: ${String(result.invite_token || "")}`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setInviteStatus(`Davet tokeni olusturulamadi. ${message}`);
    }
  }

  async function setPasswordForSelectedClient() {
    if (!selectedClient) return;
    const userId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
    setPortalPasswordStatus(`${userId} icin sifre kuruluyor...`);
    try {
      const result = await setBackendPortalPassword({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        userId,
        password: portalPassword,
        sessionToken: session?.sessionToken,
        userHeader: session?.userId || loginUserId.trim(),
      });
      setPortalPasswordStatus(result.has_password ? `${userId} icin sifre hazir.` : `${userId} icin sifre sonucu alindi.`);
      setPortalPasswordDraft("");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPortalPasswordStatus(`Sifre kurulumu tamamlanamadi. ${message}`);
    }
  }

  async function addLocalUploads(files: FileList | null) {
    const selectedFiles = Array.from(files ?? []);
    if (!selectedFiles.length || !selectedClient) return;
    const now = new Date();
    const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const intakeMetadata = buildUploadIntakeMetadata(selectedIntakeCategory);
    const nextDocuments = selectedFiles.map((file, index): PilotDocument => ({
      id: `local-upload-${now.getTime()}-${index}`,
      clientId: selectedClient.clientId,
      clientName: selectedClient.clientName,
      fileName: file.name,
      documentType: intakeMetadata.documentType,
      intakeCategory: intakeMetadata.intakeCategory as IntakeCategory,
      period,
      uploadedAt: now.toLocaleString("tr-TR"),
      uploadedBy: selectedClient.userLabel,
      status: normalizeStatus(intakeMetadata.status),
      provider: intakeMetadata.provider,
      issueDate: "-",
      amount: "-",
      vatRates: [],
      productLine: intakeMetadata.productLine,
      productCategory: intakeMetadata.productCategory,
      businessRelation: "-",
      accountTreatment: "-",
      requiresAccountantReview: true,
      previewText: intakeMetadata.previewText,
      aiReason: intakeMetadata.aiReason,
      aiProvider: "-",
      aiSuggestedAccountCode: "",
      aiSuggestedCounterpartyCode: "",
      aiRiskFlags: [],
      aiAccountReason: "",
      deterministicSummary: intakeMetadata.deterministicSummary,
      exportGateReason: intakeMetadata.exportGateReason,
      selectedExpenseAccount: "-",
      selectedVatAccount: "-",
      selectedCounterpartyAccount: "-",
      counterpartyConfidence: 0,
      reviewReasons: intakeMetadata.intakeCategory === "special_document" ? ["manual_review_required"] : [],
      riskFlags: intakeMetadata.intakeCategory === "special_document" ? ["manual_review_required"] : [],
      draftLines: [],
      statementLines: [],
      statementEntries: [],
      statementAiSuggestions: [],
      statementAiSummary: "",
      accountingIntent: "",
      accountingIntentConfidence: 0,
      learningRuleScope: "",
      learningRuleReason: "",
      learningRuleSourceSummary: "",
      rulePrompt: normalizeRulePrompt({}),
    }));
    if (localFallbackAllowed) {
      setData((current) => ({ ...current, documents: [...nextDocuments, ...current.documents] }));
      setSelectedPeriod(period);
    }
    setUploadStatus(`${selectedFiles.length} belge backend kuyruğuna gönderiliyor.`);

    const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
    const uploadUserId = pickUploadUser({ session, selectedClient });
    const uploadDisplayName = selectedClient.userLabel || uploadUserId;
    try {
      await ensureUploadWorkspace({
        apiBaseUrl,
        client: selectedClient,
        userId: uploadUserId,
        displayName: uploadDisplayName,
        sessionToken: session?.sessionToken,
      });
      await Promise.all(
        selectedFiles.map((file) =>
          uploadDocumentToBackend({
            apiBaseUrl,
            clientId: selectedClient.clientId,
            userId: uploadUserId,
            uploadedBy: uploadDisplayName,
            documentType: intakeMetadata.documentType,
            intakeCategory: intakeMetadata.intakeCategory,
            sessionToken: session?.sessionToken,
            file,
          }),
        ),
      );
      setUploadStatus(`${selectedFiles.length} belge backend kuyruğuna alındı.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setUploadStatus(
        localFallbackAllowed
          ? `Backend yükleme tamamlanamadı; belge lokal listede tutuldu. ${message}`
          : `Backend yükleme tamamlanamadı; serverda belge kaydedilmedi. ${message}`,
      );
    }
  }

  function requestCancellation(document: PilotDocument) {
    const request: CancellationRequest = {
      id: `${document.id}-request-${Date.now()}`,
      documentId: document.id,
      clientId: document.clientId,
      fileName: document.fileName,
      requestedBy: selectedClient?.userLabel ?? "Mükellef kullanıcısı",
      requestedAt: new Date().toLocaleString("tr-TR"),
      reason: cancelReason.trim() || "Mükellef iptal veya düzeltme talebi gönderdi.",
      stage: document.status === "exported" || document.status === "export_added" ? "post_export" : "pre_export",
      status: "open",
    };
    setData((current) => ({
      ...current,
      cancellationRequests: [request, ...current.cancellationRequests],
      documents: current.documents.map((item) =>
        item.id === document.id
          ? { ...item, status: request.stage === "post_export" ? "post_export_correction_requested" : "cancel_requested" }
          : item,
      ),
    }));
    setCancelReason("");
    setClientCancellationDocumentId("");
    setSelectedDocumentId(document.id);
  }

  function resolveCancellation(requestId: string, status: "approved" | "rejected") {
    setData((current) => ({
      ...current,
      cancellationRequests: current.cancellationRequests.map((request) =>
        request.id === requestId ? { ...request, status } : request,
      ),
      documents: current.documents.map((document) => {
        const request = current.cancellationRequests.find((item) => item.id === requestId);
        if (!request || request.documentId !== document.id) return document;
        return { ...document, status: status === "approved" ? "cancel_approved" : "cancel_rejected" };
      }),
    }));
  }

  function addSelectedClientToBasket() {
    if (!selectedClient) return;
    const readyDocuments = clientDocuments.filter((document) => document.status === "export_ready" || document.status === "export_added");
    if (!readyDocuments.length) {
      setExportStatus("Bu mükellefte çıktıya uygun belge yok.");
      return;
    }
    const item: ExportBasketItem = {
      id: `${selectedClient.clientId}-${Date.now()}`,
      clientId: selectedClient.clientId,
      clientName: selectedClient.clientName,
      documentIds: readyDocuments.map((document) => document.id),
      documentCount: readyDocuments.length,
      period: selectedPeriod || readyDocuments[0].period,
      status: "ready",
    };
    setData((current) => ({
      ...current,
      exportBasket: [item, ...current.exportBasket.filter((basketItem) => basketItem.clientId !== selectedClient.clientId)],
      documents: current.documents.map((document) =>
        item.documentIds.includes(document.id) ? { ...document, status: "export_added" } : document,
      ),
    }));
    setExportStatus(`${selectedClient.clientName} çıktı listesine eklendi.`);
  }

  function markBasketPackaged() {
    setData((current) => ({
      ...current,
      exportBasket: current.exportBasket.map((item) => ({ ...item, status: "packaged" })),
      documents: current.documents.map((document) =>
        current.exportBasket.some((item) => item.documentIds.includes(document.id)) ? { ...document, status: "exported" } : document,
      ),
    }));
    setExportStatus(exportMode === "bulk" ? "Seçili mükellefler için toplu paket hazır görünüyor." : "Mükellef bazlı paketler hazır görünüyor.");
  }

  async function requestStatementAiForSelectedDocument() {
    if (!selectedDocument || !selectedDocument.statementLines.length) {
      setStatementAiStatus("Seçili belgede banka satırı yok.");
      return;
    }
    setStatementAiStatus("AI önerisi isteniyor.");
    try {
      const payload = await requestStatementAiSuggestions({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedDocument.clientId,
        lines: selectedDocument.statementLines,
        aiPolicy: { enabled: true, max_provider_calls: 3 },
        providerName: "openai",
        providerPayloads: [],
        sessionToken: session?.sessionToken,
      });
      const response = safeRecord(payload);
      const suggestions = normalizeStatementAiSuggestions(response.suggestions);
      const aiUsedCount = safeNumber(response.ai_used_count);
      const skippedCount = safeNumber(response.skipped_count);
      setData((current) => ({
        ...current,
        documents: current.documents.map((document) =>
          document.id === selectedDocument.id
            ? {
                ...document,
                statementAiSuggestions: suggestions.length ? suggestions : document.statementAiSuggestions,
                statementAiSummary: `${aiUsedCount} AI önerisi / ${skippedCount} satır atlandı`,
              }
            : document,
        ),
      }));
      setStatementAiStatus(suggestions.length ? `${suggestions.length} AI önerisi alındı.` : "AI provider öneri döndürmedi; mevcut öneriler korundu.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatementAiStatus(`AI önerisi alınamadı. ${message}`);
    }
  }

  async function saveStatementLineDecision(action: string) {
    if (!selectedDocument) return;
    const lineNo = selectedStatementLineNo || selectedDocument.statementLines[0]?.line_no || 0;
    const selectedLine = selectedDocument.statementLines.find((line) => line.line_no === lineNo);
    if (!lineNo || !selectedLine) {
      setDecisionStatus("Banka satırı seçili değil.");
      return;
    }
    const correctedAccountCode = correctionDraft.accountCode.trim();
    const correctedCounterpartyCode = correctionDraft.counterpartyCode.trim();
    const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
    const reason = correctionDraft.reason.trim();
    setData((current) => ({
      ...current,
      documents: current.documents.map((document) =>
        document.id === selectedDocument.id
          ? applyStatementLineDecision(document, lineNo, action, correctedAccountCode, correctedCounterpartyCode, reviewer, reason)
          : document,
      ),
    }));
    const label = statementStatusLabel(statementReviewStatus(action));
    setDecisionStatus(`${selectedDocument.fileName} / ${lineNo}. satır: ${label} arayüzde uygulandı.`);
    try {
      await storeReviewDecision({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedDocument.clientId,
        userId: reviewer,
        documentRef: selectedDocument.id,
        action,
        reviewer,
        applyToSimilar: action === "suggest_for_similar",
        statementLineNo: lineNo,
        correctedAccountCode,
        correctedCounterpartyCode,
        category: selectedLine.transaction_type,
        reason,
        sessionToken: session?.sessionToken,
      });
      setDecisionStatus(`${selectedDocument.fileName} / ${lineNo}. satır: ${label} backend'e kaydedildi.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setDecisionStatus(
        localFallbackAllowed
          ? `${selectedDocument.fileName} / ${lineNo}. satır lokal uygulandı; backend kaydı tamamlanamadı. ${message}`
          : `${selectedDocument.fileName} / ${lineNo}. satır backend'e kaydedilemedi; serverda kalıcı karar oluşmadı. ${message}`,
      );
    }
  }

  async function saveDecision(action: string) {
    if (!selectedDocument) return;
    const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
    const correctedAccountCode = correctionDraft.accountCode.trim();
    const correctedCounterpartyCode = correctionDraft.counterpartyCode.trim();
    const reason = correctionDraft.reason.trim();
    const nextStatus: PilotStatus = action === "approve" || action === "approve_with_changes" || action === "suggest_for_similar" ? "export_ready" : "review_required";
    const label = reviewActionLabel(action);
    setData((current) => ({
      ...current,
      documents: current.documents.map((document) =>
        document.id === selectedDocument.id
          ? {
              ...document,
              status: nextStatus,
              selectedExpenseAccount: correctedAccountCode || document.selectedExpenseAccount,
              selectedCounterpartyAccount: correctedCounterpartyCode || document.selectedCounterpartyAccount,
              exportGateReason:
                nextStatus === "export_ready"
                  ? "Müşavir onayı verildi; export sepetine alınabilir."
                  : "Müşavir kararı export dışında tuttu veya kontrolü sürdürdü.",
            }
          : document,
      ),
    }));
    setDecisionStatus(`${selectedDocument.fileName}: ${label} arayüzde uygulandı.`);
    try {
      await storeReviewDecision({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedDocument.clientId,
        userId: reviewer,
        documentRef: selectedDocument.id,
        action,
        reviewer,
        applyToSimilar: action === "suggest_for_similar",
        correctedAccountCode,
        correctedCounterpartyCode,
        category: selectedDocument.productCategory,
        reason,
        sessionToken: session?.sessionToken,
      });
      setDecisionStatus(`${selectedDocument.fileName}: ${label} backend'e kaydedildi.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setDecisionStatus(
        localFallbackAllowed
          ? `${selectedDocument.fileName}: ${label} lokal uygulandı; backend kaydı tamamlanamadı. ${message}`
          : `${selectedDocument.fileName}: ${label} backend'e kaydedilemedi; serverda kalıcı karar oluşmadı. ${message}`,
      );
    }
  }

  const activeNavItem = (PORTAL_NAV_ITEMS as PortalNavItem[]).find((item) => item.mode === mode);

  return (
    <main className="private-shell portal-shell">
      <header className="private-topbar">
        <div>
          <p className="eyebrow">Fisero</p>
          <h1>{mode === "client" ? "Mükellef portalı" : activeNavItem?.label || "Müşavir çalışma alanı"}</h1>
        </div>
        <PortalTopbarStatus
          localFallbackAllowed={localFallbackAllowed}
          onExit={exitPortal}
          session={session}
          source={source}
        />
      </header>

      {visibleNavItems.length > 1 ? (
        <nav className="portal-nav" aria-label="Private pilot ekranları">
          {visibleNavItems.map((item: { mode: PilotMode; label: string; href: string }) => (
            <ModeButton active={mode === item.mode} href={item.href} key={item.mode} label={item.label} />
          ))}
        </nav>
      ) : null}

      {mode === "accountant" ? null : (
        <SelectedClientStrip client={selectedClient} documents={clientDocuments} openCancellationCount={openCancellationRequests.length} />
      )}

      {mode === "client" ? (
        <ClientPortal
          cancelReason={cancelReason}
          cancellationDocumentId={clientCancellationDocumentId}
          documents={periodDocuments}
          onCancelReasonChange={setCancelReason}
          onFilesSelected={addLocalUploads}
          onOpenCancellationRequest={(document) => {
            setSelectedDocumentId(document.id);
            setClientCancellationDocumentId(document.id);
          }}
          onRequestCancellation={requestCancellation}
          onSelectDocument={(document) => {
            setSelectedDocumentId(document.id);
            setClientCancellationDocumentId((current) => current === document.id ? current : "");
          }}
          periods={allPeriods}
          selectedClient={selectedClient}
          selectedDocument={clientSelectedDocument}
          selectedIntakeCategory={selectedIntakeCategory}
          selectedPeriod={selectedPeriod}
          setSelectedIntakeCategory={(value) => {
            setSelectedIntakeCategory(value);
            setSelectedDocumentId("");
            setClientCancellationDocumentId("");
          }}
          setSelectedPeriod={(value) => {
            setSelectedPeriod(value);
            setSelectedDocumentId("");
            setClientCancellationDocumentId("");
          }}
          uploadStatus={uploadStatus}
        />
      ) : null}

      {mode === "accountant" ? (
        <AccountantDashboard
          clientRows={visibleDashboardClientRows}
          dashboardMetrics={dashboardMetrics}
          funnelRows={funnelRows}
          intakeDistribution={intakeDistribution}
          onClientSelect={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
          selectedClientId={selectedClient?.clientId ?? ""}
          uploadTrackingRows={uploadTrackingRows}
        />
      ) : null}

      {mode === "documents" ? (
        <DocumentProcessingWorkspace
          selectedDocumentSegment={selectedDocumentSegment}
          setSelectedDocumentSegment={(segment) => {
            setSelectedDocumentSegment(segment);
            setSelectedDocumentId("");
          }}
        >
        <AccountantWorkspace
          cancellationRequests={openCancellationRequests.filter((request) => request.clientId === selectedClient?.clientId)}
          statementAiStatus={statementAiStatus}
          clientSearch={clientSearch}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          correctionDraft={correctionDraft}
          dashboardMetrics={dashboardMetrics}
          decisionStatus={decisionStatus}
          documents={activeReviewDocuments}
          allClientDocuments={segmentedClientDocuments}
          newClientDraft={newClientDraft}
          newClientStatus={newClientStatus}
          newClientTaxCertificateFile={newClientTaxCertificateFile}
          newClientTaxCertificateInputKey={newClientTaxCertificateInputKey}
          onAddToBasket={addSelectedClientToBasket}
          onApproveAndNext={approveSelectedAndMoveNext}
          onCreateNewClient={createNewClient}
          onClientSearchChange={setClientSearch}
          onTaxCertificateFileChange={selectNewClientTaxCertificate}
          onRequestStatementAi={requestStatementAiForSelectedDocument}
          onResolveCancellation={resolveCancellation}
          onSaveDecision={saveDecision}
          onSaveStatementDecision={saveStatementLineDecision}
          reviewFilter={reviewFilter}
          selectedClient={selectedClient}
          selectedDocument={selectedDocument}
          selectedStatementLineNo={selectedStatementLineNo}
          setCorrectionDraft={setCorrectionDraft}
          setNewClientDraft={setNewClientDraft}
          setReviewFilter={setReviewFilter}
          setSelectedClientId={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
          setSelectedDocumentId={setSelectedDocumentId}
          setSelectedStatementLineNo={setSelectedStatementLineNo}
        />
        </DocumentProcessingWorkspace>
      ) : null}

      {mode === "clients" ? (
        <ClientManagementView
          cancellationRequests={openCancellationRequests}
          chartUploadStatus={chartUploadStatus}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          clientSearch={clientSearch}
          inviteStatus={inviteStatus}
          newClientDraft={newClientDraft}
          newClientStatus={newClientStatus}
          newClientTaxCertificateFile={newClientTaxCertificateFile}
          newClientTaxCertificateInputKey={newClientTaxCertificateInputKey}
          onChartFileSelected={uploadChartAccounts}
          onClientSearchChange={setClientSearch}
          onCreateInvite={createInviteForSelectedClient}
          onCreateNewClient={createNewClient}
          onResolveCancellation={resolveCancellation}
          onSetPassword={setPasswordForSelectedClient}
          onTaxCertificateFileChange={selectNewClientTaxCertificate}
          portalPassword={portalPassword}
          portalPasswordStatus={portalPasswordStatus}
          selectedClient={selectedClient}
          setNewClientDraft={setNewClientDraft}
          setPortalPassword={setPortalPasswordDraft}
          setSelectedClientId={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
        />
      ) : null}

      {mode === "settings" ? (
        <SettingsView
          dashboardMetrics={dashboardMetrics}
          loginPassword={loginPassword}
          loginRole={loginRole}
          loginStatus={loginStatus}
          loginUserId={loginUserId}
          lockedRole={lockedRole}
          onLogin={login}
          onLogout={logout}
          localFallbackAllowed={localFallbackAllowed}
          readinessView={readinessView}
          session={session}
          setLoginPassword={setLoginPassword}
          setLoginRole={setLoginRole}
          setLoginUserId={setLoginUserId}
          source={source}
        />
      ) : null}

      {mode === "exports" ? (
        <ExportBasketView
          exportBasket={data.exportBasket}
          exportMode={exportMode}
          exportStatus={exportStatus}
          onMarkPackaged={markBasketPackaged}
          setExportMode={setExportMode}
        />
      ) : null}

      {mode === "operations" ? (
        <OperationsView
          data={data}
          localFallbackAllowed={localFallbackAllowed}
          readinessView={readinessView}
          source={source}
        />
      ) : null}
    </main>
  );
}

export default function Home() {
  return <FisoraPortalApp routeKey="home" />;
}

function SessionPanel({
  loginPassword,
  loginRole,
  loginStatus,
  loginUserId,
  lockedRole,
  localFallbackAllowed,
  onLogin,
  onLogout,
  session,
  setLoginPassword,
  setLoginRole,
  setLoginUserId,
}: {
  loginPassword: string;
  loginRole: "client_user" | "accountant";
  loginStatus: string;
  loginUserId: string;
  lockedRole?: "client_user" | "accountant";
  localFallbackAllowed: boolean;
  onLogin: () => void | Promise<void>;
  onLogout: () => void;
  session: LocalSession | null;
  setLoginPassword: (value: string) => void;
  setLoginRole: (value: "client_user" | "accountant") => void;
  setLoginUserId: (value: string) => void;
}) {
  return (
    <section className="session-panel" aria-label="Giriş ve çıkış">
      <div>
        <span>Private erişim</span>
        <strong>{session ? `${session.userId} / ${roleLabels[session.role]}` : "Oturum yok"}</strong>
        <p>
          {loginStatus ||
            (session?.sessionToken
              ? `Backend session aktif${session.expiresAt ? ` / ${formatDateText(session.expiresAt)}` : ""}.`
              : localFallbackAllowed
                ? "Local gelistirme icin sifresiz pilot oturumu acilabilir."
                : "Backend sifresiyle giris zorunlu.")}
        </p>
      </div>
      <div className="session-controls">
        <input aria-label="Kullanıcı" onChange={(event) => setLoginUserId(event.target.value)} value={loginUserId} />
        <input
          aria-label="Şifre"
          onChange={(event) => setLoginPassword(event.target.value)}
          placeholder="Backend şifresi"
          type="password"
          value={loginPassword}
        />
        <select
          aria-label="Rol"
          disabled={Boolean(lockedRole)}
          onChange={(event) => setLoginRole(event.target.value as "client_user" | "accountant")}
          value={lockedRole ?? loginRole}
        >
          <option value="accountant">Müşavir</option>
          <option value="client_user">Mükellef</option>
        </select>
        <button onClick={onLogin} type="button">Giriş</button>
        <button className="secondary" onClick={onLogout} type="button">Çıkış</button>
      </div>
    </section>
  );
}

function ModeButton({ active, href, label }: { active: boolean; href: string; label: string }) {
  return (
    <a aria-current={active ? "page" : undefined} className={active ? "mode-tab active" : "mode-tab"} href={href}>
      {label}
    </a>
  );
}

function PortalTopbarStatus({
  localFallbackAllowed,
  onExit,
  session,
  source,
}: {
  localFallbackAllowed: boolean;
  onExit: () => void;
  session: LocalSession | null;
  source: string;
}) {
  return (
    <div className="portal-statusbar" aria-label="Portal oturum durumu">
      <div className="topbar-user">
        <span>{session ? roleLabels[session.role] : localFallbackAllowed ? "Local gelistirme" : "Backend oturumu yok"}</span>
        <strong>{session?.userId || "Oturum yok"}</strong>
      </div>
      <div className="pilot-source compact">
        <span>Veri kaynağı</span>
        <strong>{source}</strong>
      </div>
      <button className="secondary compact-exit" onClick={onExit} type="button">
        Çıkış
      </button>
    </div>
  );
}

function SelectedClientStrip({
  client,
  documents,
  openCancellationCount,
}: {
  client?: PilotClient;
  documents: PilotDocument[];
  openCancellationCount: number;
}) {
  const readyCount = documents.filter((document) => document.status === "export_ready" || document.status === "export_added").length;
  const reviewCount = documents.filter((document) => document.status === "review_required").length;
  return (
    <section className="selected-client-strip" aria-label="Seçili mükellef">
      <Info label="Seçili mükellef" value={client?.clientName ?? "-"} />
      <Info label="VKN" value={client?.taxId ?? "-"} />
      <Info label="Belge" value={String(documents.length)} />
      <Info label="Kontrol" value={String(reviewCount)} />
      <Info label="Çıktı hazır" value={String(readyCount)} />
      <Info label="İptal talebi" value={String(openCancellationCount)} />
    </section>
  );
}

function ClientPortal({
  cancelReason,
  cancellationDocumentId,
  documents,
  onCancelReasonChange,
  onFilesSelected,
  onOpenCancellationRequest,
  onRequestCancellation,
  onSelectDocument,
  periods,
  selectedClient,
  selectedDocument,
  selectedIntakeCategory,
  selectedPeriod,
  setSelectedIntakeCategory,
  setSelectedPeriod,
  uploadStatus,
}: {
  cancelReason: string;
  cancellationDocumentId: string;
  documents: PilotDocument[];
  onCancelReasonChange: (value: string) => void;
  onFilesSelected: (files: FileList | null) => void | Promise<void>;
  onOpenCancellationRequest: (document: PilotDocument) => void;
  onRequestCancellation: (document: PilotDocument) => void;
  onSelectDocument: (document: PilotDocument) => void;
  periods: string[];
  selectedClient?: PilotClient;
  selectedDocument?: PilotDocument;
  selectedIntakeCategory: IntakeCategory;
  selectedPeriod: string;
  setSelectedIntakeCategory: (value: IntakeCategory) => void;
  setSelectedPeriod: (value: string) => void;
  uploadStatus: string;
}) {
  const activeDocuments = documents.filter((document) => document.intakeCategory === selectedIntakeCategory);
  const selectedIntake = buildUploadIntakeMetadata(selectedIntakeCategory);
  const uploadedCount = activeDocuments.length;
  const processingCount = activeDocuments.filter((document) => isInProgress(document.status)).length;
  const handledCount = activeDocuments.filter((document) => document.status === "review_required" || document.status === "export_ready" || document.status === "export_added" || document.status === "exported").length;
  const cancelCount = activeDocuments.filter((document) => isCancelStatus(document.status)).length;
  const cancellationView = buildClientCancellationViewModel({
    documents: activeDocuments,
    selectedDocumentId: selectedDocument?.id ?? "",
    requestDocumentId: cancellationDocumentId,
    cancellationReason: cancelReason,
  });
  return (
    <section className="client-portal">
      <div className="panel upload-panel">
        <div className="panel-heading">
          <div>
            <h2>Mükellef portalı</h2>
            <span>{selectedClient?.clientName ?? "-"}</span>
          </div>
          <select aria-label="Ay seçimi" onChange={(event) => setSelectedPeriod(event.target.value)} value={selectedPeriod}>
            {periods.map((period) => (
              <option key={period} value={period}>{periodLabel(period)}</option>
            ))}
          </select>
        </div>
        <div className="intake-tabs" role="tablist" aria-label="Belge yükleme türü">
          {INTAKE_TABS.map((tab) => {
            const tabId = tab.id as IntakeCategory;
            const tabCount = documents.filter((document) => document.intakeCategory === tabId).length;
            return (
              <button
                aria-selected={selectedIntakeCategory === tabId}
                className={selectedIntakeCategory === tabId ? "intake-tab active" : "intake-tab"}
                key={tab.id}
                onClick={() => setSelectedIntakeCategory(tabId)}
                role="tab"
                type="button"
              >
                <span>{tab.label}</span>
                <strong>{tabCount}</strong>
              </button>
            );
          })}
        </div>
        <div className="summary-grid">
          <Metric label="Yüklenen" value={uploadedCount} />
          <Metric label="İşlemde" value={processingCount} />
          <Metric label="İşleme alındı" value={handledCount} />
          <Metric label="İptal talebi" value={cancelCount} />
        </div>
        <label className="upload-dropzone">
          <span>{selectedIntake.label}</span>
          <strong>Dosya seç</strong>
          <small>{selectedIntake.documentType === "special_document" ? "Müşavir kontrol kuyruğu" : "Otomatik işleme kuyruğu"}</small>
          <input
            multiple
            onChange={(event) => {
              void onFilesSelected(event.currentTarget.files);
              event.currentTarget.value = "";
            }}
            type="file"
            accept={selectedIntake.accept}
          />
        </label>
        {uploadStatus ? <p className="decision-status">{uploadStatus}</p> : null}
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Ay bazlı belge listesi</h2>
            <span>{selectedPeriod ? periodLabel(selectedPeriod) : "Dönem seçilmedi"}</span>
          </div>
        </div>
        <div className="document-list">
          {activeDocuments.length ? null : <p className="empty">{selectedIntake.label} için bu ay yüklenen belge yok.</p>}
          {activeDocuments.map((document) => (
            <div className={selectedDocument?.id === document.id ? "client-document-row active" : "client-document-row"} key={document.id}>
              <button className="document-row-main" onClick={() => onSelectDocument(document)} type="button">
                <strong>{document.fileName}</strong>
                <span>{labelForIntakeCategory(document.intakeCategory)} / {documentTypeLabels[document.documentType] ?? document.documentType} / {document.uploadedAt}</span>
              </button>
              <span className={`status ${document.status}`}>{formatStatus(document.status)}</span>
              <button onClick={() => onOpenCancellationRequest(document)} type="button">İptal/Düzeltme</button>
            </div>
          ))}
        </div>
      </div>

      <ClientDocumentDetailPanel
        cancelReason={cancelReason}
        cancellationView={cancellationView}
        onCancelReasonChange={onCancelReasonChange}
        onOpenCancellationRequest={onOpenCancellationRequest}
        onRequestCancellation={onRequestCancellation}
        selectedDocument={selectedDocument}
      />
    </section>
  );
}

function ClientDocumentDetailPanel({
  cancelReason,
  cancellationView,
  onCancelReasonChange,
  onOpenCancellationRequest,
  onRequestCancellation,
  selectedDocument,
}: {
  cancelReason: string;
  cancellationView: {
    requestDocument: PilotDocument | null;
    canSubmitCancellation: boolean;
    emptyActionText: string;
  };
  onCancelReasonChange: (value: string) => void;
  onOpenCancellationRequest: (document: PilotDocument) => void;
  onRequestCancellation: (document: PilotDocument) => void;
  selectedDocument?: PilotDocument;
}) {
  if (!selectedDocument) {
    return (
      <section className="panel client-document-detail empty-detail">
        <h2>Belge önizleme</h2>
        <p className="empty">{cancellationView.emptyActionText}</p>
        <button disabled type="button">İptal/Düzeltme talebi</button>
      </section>
    );
  }

  const requestDocument = cancellationView.requestDocument;
  return (
    <section className="panel client-document-detail">
      <div className="panel-heading">
        <div>
          <h2>Belge önizleme</h2>
          <span>{selectedDocument.fileName}</span>
        </div>
        <span className={`status ${selectedDocument.status}`}>{formatStatus(selectedDocument.status)}</span>
      </div>
      <article className="client-preview-paper" aria-label="Seçili belge önizlemesi">
        <span>{documentPreviewTitle(selectedDocument)}</span>
        <strong>{selectedDocument.fileName}</strong>
        <p>{selectedDocument.previewText}</p>
        <div className="preview-meta-grid">
          <Info label="Dönem" value={periodLabel(selectedDocument.period)} />
          <Info label="Belge türü" value={labelForIntakeCategory(selectedDocument.intakeCategory)} />
          <Info label="Tutar" value={selectedDocument.amount} />
        </div>
      </article>
      <button className="primary" onClick={() => onOpenCancellationRequest(selectedDocument)} type="button">
        İptal/Düzeltme talebi aç
      </button>
      {requestDocument ? (
        <div className="cancellation-request-panel">
          <div>
            <span>Talep açılacak belge</span>
            <strong>{requestDocument.fileName}</strong>
            <small>{labelForIntakeCategory(requestDocument.intakeCategory)} / {formatStatus(requestDocument.status)}</small>
          </div>
          <textarea
            className="cancel-reason"
            onChange={(event) => onCancelReasonChange(event.target.value)}
            placeholder="Opsiyonel açıklama"
            rows={3}
            value={cancelReason}
          />
          <button
            className="primary"
            disabled={!cancellationView.canSubmitCancellation}
            onClick={() => onRequestCancellation(requestDocument)}
            type="button"
          >
            Talep gönder
          </button>
        </div>
      ) : (
        <p className="decision-status">{cancellationView.emptyActionText}</p>
      )}
    </section>
  );
}

function AccountantDashboard({
  clientRows,
  dashboardMetrics,
  funnelRows,
  intakeDistribution,
  onClientSelect,
  selectedClientId,
  uploadTrackingRows,
}: {
  clientRows: DashboardClientRow[];
  dashboardMetrics: {
    totalClients: number;
    uploadedClients: number;
    notUploadedClients: number;
    pendingReviewDocuments: number;
    exportReadyDocuments: number;
    openCancellationRequests: number;
  };
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

function ChartBars({ rows, title }: { rows: ChartRow[]; title: string }) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  return (
    <section className="panel chart-panel">
      <div className="section-heading">
        <span>{title}</span>
        <strong>{rows.reduce((sum, row) => sum + row.count, 0)}</strong>
      </div>
      <div className="bar-list">
        {rows.map((row) => (
          <div className="bar-row" key={row.key}>
            <span>{row.label}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${Math.max((row.count / max) * 100, row.count ? 8 : 0)}%` }} />
            </div>
            <strong>{row.count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function DocumentProcessingWorkspace({
  children,
  selectedDocumentSegment,
  setSelectedDocumentSegment,
}: {
  children: ReactNode;
  selectedDocumentSegment: DocumentSegment;
  setSelectedDocumentSegment: (segment: DocumentSegment) => void;
}) {
  const tabs: { id: DocumentSegment; label: string }[] = [
    { id: "invoices", label: "Faturalar" },
    { id: "bank_statements", label: "Banka ekstreleri" },
    { id: "other_documents", label: "Diger belgeler" },
  ];
  return (
    <section className="document-processing-page">
      <div className="segment-tabs" role="tablist" aria-label="Belge segmentleri">
        {tabs.map((tab) => (
          <button
            aria-selected={selectedDocumentSegment === tab.id}
            className={selectedDocumentSegment === tab.id ? "active" : ""}
            key={tab.id}
            onClick={() => setSelectedDocumentSegment(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>
      {children}
    </section>
  );
}

function ClientManagementView({
  cancellationRequests,
  chartUploadStatus,
  clientRows,
  clients,
  clientSearch,
  inviteStatus,
  newClientDraft,
  newClientStatus,
  newClientTaxCertificateFile,
  newClientTaxCertificateInputKey,
  onChartFileSelected,
  onClientSearchChange,
  onCreateInvite,
  onCreateNewClient,
  onResolveCancellation,
  onSetPassword,
  onTaxCertificateFileChange,
  portalPassword,
  portalPasswordStatus,
  selectedClient,
  setNewClientDraft,
  setPortalPassword,
  setSelectedClientId,
}: {
  cancellationRequests: CancellationRequest[];
  chartUploadStatus: string;
  clientRows: DashboardClientRow[];
  clients: PilotClient[];
  clientSearch: string;
  inviteStatus: string;
  newClientDraft: NewClientDraft;
  newClientStatus: string;
  newClientTaxCertificateFile: File | null;
  newClientTaxCertificateInputKey: number;
  onChartFileSelected: (files: FileList | null) => void | Promise<void>;
  onClientSearchChange: (value: string) => void;
  onCreateInvite: () => void | Promise<void>;
  onCreateNewClient: () => void | Promise<void>;
  onResolveCancellation: (requestId: string, status: "approved" | "rejected") => void;
  onSetPassword: () => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void | Promise<void>;
  portalPassword: string;
  portalPasswordStatus: string;
  selectedClient?: PilotClient;
  setNewClientDraft: (value: NewClientDraft) => void;
  setPortalPassword: (value: string) => void;
  setSelectedClientId: (value: string) => void;
}) {
  return (
    <section className="client-management-page">
      <section className="panel">
        <div className="section-heading">
          <span>Mukellef listesi</span>
          <strong>{clients.length}</strong>
        </div>
        <input
          className="search-input"
          onChange={(event) => onClientSearchChange(event.target.value)}
          placeholder="Mukellef ara"
          value={clientSearch}
        />
        <div className="client-list dashboard-client-list">
          {clientRows.map((row) => (
            <button
              className={selectedClient?.clientId === row.clientId ? "client-row active" : "client-row"}
              key={row.clientId}
              onClick={() => setSelectedClientId(row.clientId)}
              type="button"
            >
              <strong>{row.clientName}</strong>
              <span>{row.status}</span>
              <em>{row.documentCount} belge / {row.cancellationCount} talep</em>
            </button>
          ))}
        </div>
      </section>
      <section className="panel onboarding-panel">
        <NewClientCard
          draft={newClientDraft}
          onCreate={onCreateNewClient}
          onTaxCertificateFileChange={onTaxCertificateFileChange}
          setDraft={setNewClientDraft}
          status={newClientStatus}
          taxCertificateFile={newClientTaxCertificateFile}
          taxCertificateInputKey={newClientTaxCertificateInputKey}
        />
        <div className="settings-card">
          <span>Hesap plani import</span>
          <strong>{selectedClient?.clientName ?? "-"}</strong>
          <label className="upload-dropzone compact-upload">
            <input
              accept=".csv,.xlsx,.xlsm"
              onChange={(event) => onChartFileSelected(event.target.files)}
              type="file"
            />
            CSV/XLSX hesap plani sec
          </label>
          {chartUploadStatus ? <p className="decision-status">{chartUploadStatus}</p> : null}
        </div>
        <div className="settings-card">
          <span>Portal erisimi</span>
          <strong>{selectedClient?.portalUserId ?? "-"}</strong>
          <div className="inline-actions">
            <button onClick={onCreateInvite} type="button">Davet tokeni olustur</button>
            <input
              aria-label="Portal sifresi"
              onChange={(event) => setPortalPassword(event.target.value)}
              placeholder="Gecici sifre"
              type="password"
              value={portalPassword}
            />
            <button className="primary" onClick={onSetPassword} type="button">Sifre kur</button>
          </div>
          {inviteStatus ? <p className="decision-status">{inviteStatus}</p> : null}
          {portalPasswordStatus ? <p className="decision-status">{portalPasswordStatus}</p> : null}
        </div>
      </section>
      <section className="panel">
        <div className="section-heading">
          <span>Iptal / duzeltme talepleri</span>
          <strong>{cancellationRequests.length}</strong>
        </div>
        <div className="request-list">
          {cancellationRequests.length ? cancellationRequests.map((request) => (
            <div className="request-compact" key={request.id}>
              <span>{request.clientId}</span>
              <strong>{request.fileName}</strong>
              <p>{request.reason}</p>
              <small>Karar için Belge işleme ekranında ilgili belgeyi seçin.</small>
            </div>
          )) : <p className="empty">Acik talep yok.</p>}
        </div>
      </section>
    </section>
  );
}

function SettingsView({
  dashboardMetrics,
  loginPassword,
  loginRole,
  loginStatus,
  loginUserId,
  lockedRole,
  localFallbackAllowed,
  onLogin,
  onLogout,
  readinessView,
  session,
  setLoginPassword,
  setLoginRole,
  setLoginUserId,
  source,
}: {
  dashboardMetrics: {
    totalClients: number;
    uploadedClients: number;
    notUploadedClients: number;
    pendingReviewDocuments: number;
    exportReadyDocuments: number;
    openCancellationRequests: number;
  };
  loginPassword: string;
  loginRole: "client_user" | "accountant";
  loginStatus: string;
  loginUserId: string;
  lockedRole?: "client_user" | "accountant";
  localFallbackAllowed: boolean;
  onLogin: () => void | Promise<void>;
  onLogout: () => void;
  readinessView: PilotReadinessView;
  session: LocalSession | null;
  setLoginPassword: (value: string) => void;
  setLoginRole: (value: "client_user" | "accountant") => void;
  setLoginUserId: (value: string) => void;
  source: string;
}) {
  return (
    <section className="settings-page">
      <SessionPanel
        loginPassword={loginPassword}
        loginRole={loginRole}
        loginStatus={loginStatus}
        loginUserId={loginUserId}
        lockedRole={lockedRole}
        localFallbackAllowed={localFallbackAllowed}
        onLogin={onLogin}
        onLogout={onLogout}
        session={session}
        setLoginPassword={setLoginPassword}
        setLoginRole={setLoginRole}
        setLoginUserId={setLoginUserId}
      />
      <section className="panel settings-grid">
        <Info label="Veri kaynagi" value={source} />
        <Info label="Oturum" value={session ? `${roleLabels[session.role]} / ${session.userId}` : "Backend oturumu yok"} />
        <Info label="Pilot satis" value={readinessView.statusLabel} />
        <Info label="Production" value={readinessView.productionLabel} />
        <Info label="Auth" value={readinessView.authLabel} />
        <Info label="Store" value={readinessView.storeLabel} />
        <Info label="AI" value={readinessView.aiLabel} />
        <Info label="Export" value={readinessView.exportLabel} />
        <Info label="Lokal fallback" value={localFallbackAllowed ? "Sadece gelistirme" : "Kapali"} />
        <Info label="Mukellef" value={String(dashboardMetrics.totalClients)} />
        <Info label="Kontrol bekleyen" value={String(dashboardMetrics.pendingReviewDocuments)} />
      </section>
    </section>
  );
}

function AccountantWorkspace({
  cancellationRequests,
  statementAiStatus,
  clientSearch,
  clientRows,
  clients,
  correctionDraft,
  dashboardMetrics,
  decisionStatus,
  documents,
  allClientDocuments,
  newClientDraft,
  newClientStatus,
  newClientTaxCertificateFile,
  newClientTaxCertificateInputKey,
  onAddToBasket,
  onApproveAndNext,
  onClientSearchChange,
  onCreateNewClient,
  onRequestStatementAi,
  onResolveCancellation,
  onSaveDecision,
  onSaveStatementDecision,
  onTaxCertificateFileChange,
  reviewFilter,
  selectedClient,
  selectedDocument,
  selectedStatementLineNo,
  setCorrectionDraft,
  setNewClientDraft,
  setReviewFilter,
  setSelectedClientId,
  setSelectedDocumentId,
  setSelectedStatementLineNo,
}: {
  cancellationRequests: CancellationRequest[];
  statementAiStatus: string;
  clientSearch: string;
  clientRows: DashboardClientRow[];
  clients: PilotClient[];
  correctionDraft: CorrectionDraft;
  dashboardMetrics: {
    totalClients: number;
    uploadedClients: number;
    notUploadedClients: number;
    pendingReviewDocuments: number;
    exportReadyDocuments: number;
    openCancellationRequests: number;
  };
  decisionStatus: string;
  documents: PilotDocument[];
  allClientDocuments: PilotDocument[];
  newClientDraft: NewClientDraft;
  newClientStatus: string;
  newClientTaxCertificateFile: File | null;
  newClientTaxCertificateInputKey: number;
  onAddToBasket: () => void;
  onApproveAndNext: () => void | Promise<void>;
  onClientSearchChange: (value: string) => void;
  onCreateNewClient: () => void | Promise<void>;
  onRequestStatementAi: () => void | Promise<void>;
  onResolveCancellation: (requestId: string, status: "approved" | "rejected") => void;
  onSaveDecision: (action: string) => void | Promise<void>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void | Promise<void>;
  reviewFilter: ReviewFilter;
  selectedClient?: PilotClient;
  selectedDocument?: PilotDocument;
  selectedStatementLineNo: number;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setNewClientDraft: (value: NewClientDraft) => void;
  setReviewFilter: (value: ReviewFilter) => void;
  setSelectedClientId: (value: string) => void;
  setSelectedDocumentId: (value: string) => void;
  setSelectedStatementLineNo: (value: number) => void;
}) {
  const selectedRequest = selectedDocument
    ? cancellationRequests.find((request) => request.documentId === selectedDocument.id)
    : undefined;
  const selectedDocumentPosition = selectedDocument
    ? documents.findIndex((document) => document.id === selectedDocument.id) + 1
    : 0;

  return (
    <section className="accountant-workspace">
      <section className="office-dashboard" aria-label="Ofis durumu">
        <Metric label="Mükellef" value={dashboardMetrics.totalClients} />
        <Metric label="Belge yükleyen" value={dashboardMetrics.uploadedClients} />
        <Metric label="Yüklemeyen" value={dashboardMetrics.notUploadedClients} />
        <Metric label="Kontrol" value={dashboardMetrics.pendingReviewDocuments} />
        <Metric label="Çıktı hazır" value={dashboardMetrics.exportReadyDocuments} />
        <Metric label="Talep" value={dashboardMetrics.openCancellationRequests} />
      </section>
      <aside className="client-context-rail" aria-label="Seçili mükellef">
        <div className="client-emblem">
          <span>Mükellef</span>
          <strong>{selectedClient?.clientName ?? "-"}</strong>
          <small>{selectedClient?.taxId ?? "-"}</small>
        </div>
        <input
          className="search-input"
          onChange={(event) => onClientSearchChange(event.target.value)}
          placeholder="Mükellef ara"
          value={clientSearch}
        />
        <div className="client-list dashboard-client-list">
          {clientRows.map((row) => (
            <button
              className={selectedClient?.clientId === row.clientId ? "client-row active" : "client-row"}
              key={row.clientId}
              onClick={() => {
                setSelectedClientId(row.clientId);
                setSelectedDocumentId("");
              }}
              type="button"
            >
              <strong>{row.clientName}</strong>
              <span>{row.status}</span>
              <em>{row.documentCount} belge / {row.pendingReviewCount} kontrol / {row.exportReadyCount} hazır</em>
            </button>
          ))}
        </div>
        <label className="compact-field">
          <span>Mükellef seç</span>
          <select
            onChange={(event) => setSelectedClientId(event.target.value)}
            value={selectedClient?.clientId ?? ""}
          >
            {clients.map((client) => (
              <option key={client.clientId} value={client.clientId}>
                {client.clientName}
              </option>
            ))}
          </select>
        </label>
        <div className="rail-stats">
          <Info label="Belge" value={String(documents.length)} />
          <Info label="Kontrol" value={String(documents.filter((document) => document.status === "review_required").length)} />
          <Info label="İptal" value={String(cancellationRequests.length)} />
        </div>
        {selectedDocument ? (
          <div className="selected-document-summary">
            <span>Açık belge</span>
            <strong>{selectedDocument.fileName}</strong>
            <small>{labelForIntakeCategory(selectedDocument.intakeCategory)} / {selectedDocument.provider} / {selectedDocument.amount}</small>
            <span className={`status ${selectedDocument.status}`}>{formatStatus(selectedDocument.status)}</span>
          </div>
        ) : null}
        <button className="primary full" onClick={onAddToBasket} type="button">Çıktı listesine ekle</button>
        {selectedRequest ? (
          <div className="request-compact">
            <span>İptal/düzeltme talebi</span>
            <p>{selectedRequest.reason}</p>
            <div className="inline-actions">
              <button onClick={() => onResolveCancellation(selectedRequest.id, "approved")} type="button">Kabul</button>
              <button onClick={() => onResolveCancellation(selectedRequest.id, "rejected")} type="button">Red</button>
            </div>
          </div>
        ) : null}
        <NewClientCard
          draft={newClientDraft}
          onCreate={onCreateNewClient}
          onTaxCertificateFileChange={onTaxCertificateFileChange}
          setDraft={setNewClientDraft}
          status={newClientStatus}
          taxCertificateFile={newClientTaxCertificateFile}
          taxCertificateInputKey={newClientTaxCertificateInputKey}
        />
      </aside>

      <section className="review-focus">
        <div className="workbench-toolbar">
          <div>
            <span>Belge kontrolü</span>
            <strong>{selectedDocument ? `${selectedDocumentPosition}/${documents.length} ${selectedDocument.fileName}` : "Önce belge seçin."}</strong>
          </div>
          <div className="toolbar-controls">
            <select onChange={(event) => setReviewFilter(event.target.value as ReviewFilter)} value={reviewFilter}>
              <option value="review_required">Kontrol gerekli</option>
              <option value="export_ready">Export hazır</option>
              <option value="cancel_requested">İptal talepleri</option>
              <option value="all">Tüm belgeler</option>
            </select>
            <select
              aria-label="Belge seç"
              onChange={(event) => setSelectedDocumentId(event.target.value)}
              value={selectedDocument?.id ?? ""}
            >
              <option value="">{documents.length ? "Belge seçin" : "Belge yok"}</option>
              {documents.map((document) => (
                <option key={document.id} value={document.id}>
                  {document.fileName}
                </option>
              ))}
            </select>
            <button disabled={!selectedDocument} onClick={() => setSelectedDocumentId(documents[Math.max(selectedDocumentPosition - 2, 0)]?.id ?? selectedDocument?.id ?? "")} type="button">Önceki</button>
            <button disabled={!selectedDocument} onClick={() => setSelectedDocumentId(documents[selectedDocumentPosition]?.id ?? selectedDocument?.id ?? "")} type="button">Sonraki</button>
            <button className="primary" disabled={!selectedDocument} onClick={onApproveAndNext} type="button">Onayla ve geç</button>
          </div>
        </div>

        <div className="document-queue" aria-label="Mükellef evrakları">
          {allClientDocuments.map((document) => (
            <button
              className={selectedDocument?.id === document.id ? "document-row active" : "document-row"}
              key={document.id}
              onClick={() => setSelectedDocumentId(document.id)}
              type="button"
            >
              <strong>{document.fileName}</strong>
              <span>{labelForIntakeCategory(document.intakeCategory)} / {document.amount}</span>
              <em>{formatStatus(document.status)}</em>
            </button>
          ))}
        </div>

        {cancellationRequests.length && !selectedRequest ? (
          <div className="request-strip">
            <span>Açık talepler</span>
            {cancellationRequests.map((request) => (
              <button key={request.id} onClick={() => setSelectedDocumentId(request.documentId)} type="button">
                {request.fileName}
              </button>
            ))}
          </div>
        ) : null}

        <section className="review-split">
          <DocumentPreview document={selectedDocument} />
          <JournalPanel
            correctionDraft={correctionDraft}
            decisionStatus={decisionStatus}
            document={selectedDocument}
            onApproveAndNext={onApproveAndNext}
            onRequestStatementAi={onRequestStatementAi}
            onSaveDecision={onSaveDecision}
            onSaveStatementDecision={onSaveStatementDecision}
            selectedStatementLineNo={selectedStatementLineNo}
            setCorrectionDraft={setCorrectionDraft}
            setSelectedStatementLineNo={setSelectedStatementLineNo}
            statementAiStatus={statementAiStatus}
          />
        </section>
      </section>
    </section>
  );
}

function NewClientCard({
  draft,
  onCreate,
  onTaxCertificateFileChange,
  setDraft,
  status,
  taxCertificateFile,
  taxCertificateInputKey,
}: {
  draft: NewClientDraft;
  onCreate: () => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void;
  setDraft: (value: NewClientDraft) => void;
  status: string;
  taxCertificateFile: File | null;
  taxCertificateInputKey: number;
}) {
  return (
    <section className="new-client-card">
      <div>
        <span>Yeni mükellef</span>
        <strong>Hızlı kayıt</strong>
      </div>
      <input
        aria-label="Mükellef adı"
        onChange={(event) => setDraft({ ...draft, title: event.target.value })}
        placeholder="Mükellef adı"
        value={draft.title}
      />
      <input
        aria-label="VKN"
        inputMode="numeric"
        maxLength={10}
        onChange={(event) => setDraft({ ...draft, taxId: event.target.value })}
        pattern="[0-9]*"
        placeholder="VKN"
        value={draft.taxId}
      />
      <input
        aria-label="Faaliyet"
        onChange={(event) => setDraft({ ...draft, activityDescription: event.target.value })}
        placeholder="Faaliyet"
        value={draft.activityDescription}
      />
      <div className="new-client-inline">
        <input
          aria-label="NACE"
          onChange={(event) => setDraft({ ...draft, naceCode: event.target.value })}
          placeholder="NACE"
          value={draft.naceCode}
        />
        <input
          aria-label="Portal kullanıcısı"
          onChange={(event) => setDraft({ ...draft, portalUserId: event.target.value })}
          placeholder="Portal kullanıcı"
          value={draft.portalUserId}
        />
      </div>
      {draft.activityTags.length ? (
        <div className="activity-tag-strip" aria-label="Faaliyet etiketleri">
          {draft.activityTags.slice(0, 4).map((tag) => (
            <span key={tag}>{tag.replace(/_/g, " ")}</span>
          ))}
        </div>
      ) : null}
      <label className="tax-certificate-upload">
        <span>Vergi levhası</span>
        <input
          accept=".pdf,.jpg,.jpeg,.png"
          aria-label="Vergi levhası"
          key={taxCertificateInputKey}
          onChange={(event) => onTaxCertificateFileChange(event.target.files?.[0] ?? null)}
          type="file"
        />
        <small>{taxCertificateFile?.name ?? "PDF/JPG/PNG seç"}</small>
      </label>
      <button className="primary full" onClick={onCreate} type="button">Mükellef ekle</button>
      {status ? <p className="decision-status">{status}</p> : null}
    </section>
  );
}

function DocumentPreview({ document }: { document?: PilotDocument }) {
  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>Orijinal belge</h2>
        <p className="empty">Belge seçimi yok.</p>
      </section>
    );
  }
  return (
    <section className="review-panel document-panel">
      <div className="panel-heading">
        <div>
          <h2>Orijinal belge</h2>
          <span>{document.fileName}</span>
        </div>
        <span className={`status ${document.status}`}>{formatStatus(document.status)}</span>
      </div>
      <div className="document-canvas">
        <article className="paper-document" aria-label="Belge orijinal görünümü">
          <header className="paper-header">
            <div>
              <span>{labelForIntakeCategory(document.intakeCategory)} / {documentTypeLabels[document.documentType] ?? document.documentType}</span>
              <strong>{document.provider}</strong>
            </div>
            <small>{document.issueDate}</small>
          </header>
          <div className="paper-title">
            <span>{documentPreviewTitle(document)}</span>
            <strong>{document.fileName}</strong>
          </div>
          <div className="paper-row">
            <span>Açıklama</span>
            <strong>{document.previewText}</strong>
          </div>
          <div className="paper-line-item">
            <span>Kalem</span>
            <strong>{document.productLine}</strong>
            <small>{document.productCategory}</small>
          </div>
          <div className="paper-totals">
            <div>
              <span>KDV</span>
              <strong>{document.vatRates.length ? `%${document.vatRates.join(", %")}` : "-"}</strong>
            </div>
            <div>
              <span>Toplam</span>
              <strong>{document.amount}</strong>
            </div>
          </div>
          <footer className="paper-footer">
            <span>Belge referansı</span>
            <strong>{document.id}</strong>
          </footer>
        </article>
      </div>
    </section>
  );
}

function JournalPanel({
  correctionDraft,
  decisionStatus,
  document,
  onApproveAndNext,
  onRequestStatementAi,
  onSaveDecision,
  onSaveStatementDecision,
  selectedStatementLineNo,
  setCorrectionDraft,
  setSelectedStatementLineNo,
  statementAiStatus,
}: {
  correctionDraft: CorrectionDraft;
  decisionStatus: string;
  document?: PilotDocument;
  onApproveAndNext: () => void | Promise<void>;
  onRequestStatementAi: () => void | Promise<void>;
  onSaveDecision: (action: string) => void | Promise<void>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  selectedStatementLineNo: number;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setSelectedStatementLineNo: (value: number) => void;
  statementAiStatus: string;
}) {
  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>Muhasebe fişi</h2>
        <p className="empty">Belge seçimi yok.</p>
      </section>
    );
  }
  return (
    <section className={`review-panel journal-panel ${document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "statement-mode" : ""}`}>
      <div className="panel-heading">
        <div>
          <h2>Muhasebe fişi</h2>
          <span>{document.clientName}</span>
        </div>
      </div>
      <div className="ai-guidance">
        <ReasonCard label="AI/kural yorumu" value={document.aiReason} />
        <ReasonCard label="Faaliyet ilişkisi" value={document.businessRelation || "-"} />
        <ReasonCard label="Muhasebe işleme" value={document.accountTreatment || "-"} />
        <ReasonCard label="Neden bu hesap/cari" value={document.aiAccountReason || "AI hesap/cari gerekçesi yok."} />
        <ReasonCard label="Deterministik kontrol" value={document.deterministicSummary} />
        <ReasonCard label="Onaya gitmeme nedeni" value={document.exportGateReason} />
      </div>
      <div className="journal-meta ai-meta">
        <Info label="AI provider" value={document.aiProvider || "-"} />
        <Info label="AI hesap önerisi" value={document.aiSuggestedAccountCode || document.selectedExpenseAccount || "-"} />
        <Info label="AI cari önerisi" value={document.aiSuggestedCounterpartyCode || document.selectedCounterpartyAccount || "-"} />
        <Info label="AI risk" value={document.aiRiskFlags.length ? document.aiRiskFlags.join(", ") : "risk_yok"} />
      </div>
      <LearningRuleCard document={document} />
      <div className="journal-meta">
        <Info label={document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Banka hesabı" : "Gider hesabı"} value={document.selectedExpenseAccount} />
        <Info label={document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Fiş KDV" : "KDV hesabı"} value={document.selectedVatAccount} />
        <Info label={document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Karşı hesap" : "Cari"} value={`${document.selectedCounterpartyAccount} (${document.counterpartyConfidence})`} />
      </div>
      {document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? (
        <StatementReviewPanel
          correctionDraft={correctionDraft}
          document={document}
          onRequestStatementAi={onRequestStatementAi}
          onSaveStatementDecision={onSaveStatementDecision}
          selectedStatementLineNo={selectedStatementLineNo}
          setCorrectionDraft={setCorrectionDraft}
          setSelectedStatementLineNo={setSelectedStatementLineNo}
          statementAiStatus={statementAiStatus}
        />
      ) : null}
      <div className="correction-form">
        <label>
          <span>{document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Yeni işlem hesabı" : "Yeni gider hesabı"}</span>
          <input
            onChange={(event) => setCorrectionDraft({ ...correctionDraft, accountCode: event.target.value })}
            placeholder={document.selectedExpenseAccount}
            value={correctionDraft.accountCode}
          />
        </label>
        <label>
          <span>{document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Yeni karşı hesap" : "Yeni cari"}</span>
          <input
            onChange={(event) => setCorrectionDraft({ ...correctionDraft, counterpartyCode: event.target.value })}
            placeholder={document.selectedCounterpartyAccount}
            value={correctionDraft.counterpartyCode}
          />
        </label>
        <label className="wide">
          <span>Müşavir açıklaması</span>
          <textarea
            onChange={(event) => setCorrectionDraft({ ...correctionDraft, reason: event.target.value })}
            placeholder="Neden değiştirdiniz? Bu açıklama sonraki benzer belgelerde öğrenme sinyali olur."
            rows={3}
            value={correctionDraft.reason}
          />
        </label>
      </div>
      <div className="table-wrap">
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
            {journalDraftLinesForDocument(document, selectedStatementLineNo).length ? (
              journalDraftLinesForDocument(document, selectedStatementLineNo).map((line, index) => (
                <tr key={`${line.account_code}-${index}`}>
                  <td>{line.account_code}</td>
                  <td>{line.description}</td>
                  <td>{line.debit}</td>
                  <td>{line.credit}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4}>Fiş taslağı henüz yok.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="decision-actions">
        <button onClick={onApproveAndNext} type="button">Onayla ve geç</button>
        <button onClick={() => onSaveDecision("approve_with_changes")} type="button">Düzelt ve onayla</button>
        <button onClick={() => onSaveDecision("suggest_for_similar")} type="button">Kural yap</button>
        <button onClick={() => onSaveDecision("exclude_export")} type="button">Export dışı</button>
        <button onClick={() => onSaveDecision("review_required")} type="button">Kontrolde tut</button>
      </div>
      <p className="decision-status">{decisionStatus || "Bu belge için henüz müşavir kararı verilmedi."}</p>
    </section>
  );
}

function LearningRuleCard({ document }: { document: PilotDocument }) {
  const hasLearningSignal = Boolean(
    document.accountingIntent ||
    document.learningRuleReason ||
    document.learningRuleSourceSummary ||
    document.rulePrompt.show,
  );
  if (!hasLearningSignal) return null;
  return (
    <section className="learning-rule-card">
      <div>
        <span>Öğrenme kaynağı</span>
        <strong>{document.rulePrompt.message || document.learningRuleSourceSummary || document.learningRuleReason}</strong>
      </div>
      <div className="learning-rule-meta">
        <Info label="Muhasebe niyeti" value={document.accountingIntent || "-"} />
        <Info label="Güven" value={document.accountingIntentConfidence ? `%${document.accountingIntentConfidence}` : "-"} />
        <Info label="Mükellef kararı" value={String(document.rulePrompt.clientConsistentDecisionCount || 0)} />
        <Info label="Ofis adayi" value={`${document.rulePrompt.officeDistinctClientCount || 0} / ${document.rulePrompt.officeConsistentDecisionCount || 0}`} />
      </div>
    </section>
  );
}

function StatementReviewPanel({
  correctionDraft,
  document,
  onRequestStatementAi,
  onSaveStatementDecision,
  selectedStatementLineNo,
  setCorrectionDraft,
  setSelectedStatementLineNo,
  statementAiStatus,
}: {
  correctionDraft: CorrectionDraft;
  document: PilotDocument;
  onRequestStatementAi: () => void | Promise<void>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  selectedStatementLineNo: number;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setSelectedStatementLineNo: (value: number) => void;
  statementAiStatus: string;
}) {
  if (!document.statementLines.length) return null;
  const selectedLine = document.statementLines.find((line) => line.line_no === selectedStatementLineNo) ?? document.statementLines[0];
  const selectedEntry = document.statementEntries.find((entry) => entry.statement_line_no === selectedLine.line_no);
  const selectedSuggestion = document.statementAiSuggestions.find((suggestion) => suggestion.line_no === selectedLine.line_no);
  const approvedCount = document.statementLines.filter((line) => line.accountant_review_status === "approved").length;
  const riskCount = document.statementLines.filter((line) => line.risk_flags.length > 0 && line.accountant_review_status !== "approved").length;

  function applyAiSuggestion() {
    if (!selectedSuggestion) return;
    setCorrectionDraft({
      ...correctionDraft,
      counterpartyCode: selectedSuggestion.suggested_account_code || correctionDraft.counterpartyCode,
      reason: selectedSuggestion.reason || correctionDraft.reason,
    });
  }

  return (
    <section className="statement-review-panel">
      <div className="statement-review-heading">
        <div>
          <h3>Banka satırları</h3>
          <span>{approvedCount}/{document.statementLines.length} onaylı / {riskCount} riskli</span>
        </div>
        <button onClick={onRequestStatementAi} type="button">AI önerisi al</button>
      </div>

      <div className="statement-grid">
        <div className="statement-lines-list">
          <table>
            <thead>
              <tr>
                <th>No</th>
                <th>Tarih</th>
                <th>Açıklama</th>
                <th>Yön</th>
                <th>Tutar</th>
                <th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {document.statementLines.map((line) => (
                <tr className={line.line_no === selectedLine.line_no ? "selected-row" : ""} key={line.line_no}>
                  <td>
                    <button className="line-select" onClick={() => setSelectedStatementLineNo(line.line_no)} type="button">
                      {line.line_no}
                    </button>
                  </td>
                  <td>{line.transaction_date || "-"}</td>
                  <td>{line.description || "-"}</td>
                  <td>{statementDirectionLabel(line.direction)}</td>
                  <td>{line.amount}</td>
                  <td>{statementStatusLabel(line.accountant_review_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="statement-line-detail">
          <div className="statement-detail-meta">
            <Info label="İşlem tipi" value={statementTypeLabels[selectedLine.transaction_type] ?? selectedLine.transaction_type} />
            <Info label="Karşı hesap" value={selectedLine.suggested_account_code || selectedLine.counterparty_match_code || "-"} />
            <Info label="Güven" value={String(selectedLine.confidence)} />
          </div>
          <div className="statement-risk-tags">
            {selectedLine.risk_flags.length ? selectedLine.risk_flags.map((flag) => <span key={flag}>{flag}</span>) : <span>risk_yok</span>}
          </div>
          <div className="statement-ai-box">
            <div>
              <span>AI önerisi</span>
              <strong>{selectedSuggestion ? `${statementTypeLabels[selectedSuggestion.transaction_type] ?? selectedSuggestion.transaction_type} / ${selectedSuggestion.suggested_account_code || "-"}` : "Yok"}</strong>
              <small>{selectedSuggestion?.reason || document.statementAiSummary || statementAiStatus || "-"}</small>
            </div>
            <button disabled={!selectedSuggestion} onClick={applyAiSuggestion} type="button">Uygula</button>
          </div>
          <div className="statement-entry-ref">
            <Info label="Fiş referansı" value={selectedEntry?.statement_fingerprint || selectedEntry?.source_document_ref || "-"} />
            <Info label="Fiş durumu" value={statementStatusLabel(selectedEntry?.accountant_review_status)} />
          </div>
          <div className="statement-actions">
            <button onClick={() => onSaveStatementDecision("approve")} type="button">Satırı onayla</button>
            <button onClick={() => onSaveStatementDecision("approve_with_changes")} type="button">Düzelt ve onayla</button>
            <button onClick={() => onSaveStatementDecision("suggest_for_similar")} type="button">Kural yap</button>
            <button onClick={() => onSaveStatementDecision("exclude_from_export")} type="button">Export dışı</button>
            <button onClick={() => onSaveStatementDecision("wrong_account")} type="button">Kontrolde tut</button>
          </div>
        </div>
      </div>
    </section>
  );
}

function ExportBasketView({
  exportBasket,
  exportMode,
  exportStatus,
  onMarkPackaged,
  setExportMode,
}: {
  exportBasket: ExportBasketItem[];
  exportMode: ExportMode;
  exportStatus: string;
  onMarkPackaged: () => void;
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

function OperationsView({
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
        <h2>Kapali pilot durumu</h2>
        <Info label="Pilot satis" value={readinessView.statusLabel} />
        <Info label="Production" value={readinessView.productionLabel} />
        <Info label="Teklif" value={readinessView.offerLabel} />
        <Info label="Export" value={readinessView.exportLabel} />
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
        <h2>Operasyon kapilari</h2>
        <Info label="Auth" value={readinessView.authLabel} />
        <Info label="Store" value={readinessView.storeLabel} />
        <Info label="AI" value={readinessView.aiLabel} />
        <Info label="Blokaj" value={readinessView.blocking.length ? readinessView.blocking.join(", ") : "Yok"} />
        <Info label="Uyari" value={readinessView.warnings.length ? readinessView.warnings.join(", ") : "Yok"} />
        {localFallbackAllowed ? (
          <ul className="plain-list">
            <li><code>frontend/public/local-pilot-data.json</code></li>
            <li><code>frontend/public/local-workspace-data.json</code></li>
            <li><code>frontend/public/local-review-data.json</code></li>
          </ul>
        ) : null}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info">
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

function ReasonCard({ label, value }: { label: string; value: string }) {
  const parts = label === "Deterministik kontrol"
    ? value.split(",").map((item) => item.trim()).filter(Boolean)
    : [];
  return (
    <div className="reason-card">
      <span>{label}</span>
      {parts.length > 1 ? (
        <div className="reason-tags">
          {parts.map((part) => (
            <em key={part}>{part}</em>
          ))}
        </div>
      ) : (
        <p>{value || "-"}</p>
      )}
    </div>
  );
}
