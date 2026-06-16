export type IntakeCategory = "sales_invoice" | "purchase_invoice" | "bank_statement" | "special_document";

export type DraftLine = {
  account_code: string;
  description: string;
  debit: string;
  credit: string;
};

export type StatementLineReview = {
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

export type StatementEntryReview = {
  statement_line_no: number;
  statement_fingerprint: string;
  source_document_ref: string;
  accountant_review_status?: string;
  risk_flags: string[];
  lines: DraftLine[];
};

export type StatementAiSuggestionView = {
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

export type RulePromptView = {
  show: boolean;
  defaultScope: string;
  message: string;
  clientConsistentDecisionCount: number;
  officeDistinctClientCount: number;
  officeConsistentDecisionCount: number;
};

export type PilotStatus =
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

export type PilotDocument = {
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
  originalDocumentRef: string;
  originalDocumentMimeType: string;
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
  draftStatus: string;
  accountantSummary: string;
  technicalDetails: Record<string, unknown>;
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

export type PilotClient = {
  clientId: string;
  clientName: string;
  taxId: string;
  userLabel: string;
  portalUserId: string;
  onboardingStatus: string;
};

export type CancellationRequest = {
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

export type ExportBasketItem = {
  id: string;
  clientId: string;
  clientName: string;
  documentIds: string[];
  documentCount: number;
  period: string;
  status: "ready" | "packaged";
};

export type PilotData = {
  generatedFrom: string;
  clients: PilotClient[];
  documents: PilotDocument[];
  cancellationRequests: CancellationRequest[];
  exportBasket: ExportBasketItem[];
};

export type PilotReadinessView = {
  status: string;
  statusLabel: string;
  productionLabel: string;
  realDataLabel: string;
  realDataAccessLabel: string;
  realDataBlocking: string[];
  offerLabel: string;
  exportLabel: string;
  zirveLabel: string;
  authLabel: string;
  storeLabel: string;
  aiLabel: string;
  blocking: string[];
  warnings: string[];
};

export type ReviewData = {
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

export type PilotMode = "client" | "accountant" | "documents" | "clients" | "settings" | "exports" | "operations";
export type PortalRouteKey = "home" | "mukellef" | "musavir" | "belgeler" | "mukellefler" | "ayarlar" | "cikti" | "operasyon";
export type DocumentSegment = "invoices" | "bank_statements" | "other_documents";
export type PortalNavItem = { mode: PilotMode; label: string; href: string };
export type ReviewFilter = "all" | "review_required" | "export_ready" | "cancel_requested";
export type ExportMode = "bulk" | "by_client";

export type CorrectionDraft = {
  accountCode: string;
  counterpartyCode: string;
  manualDraftLines: DraftLine[];
  reason: string;
};

export type NewClientDraft = {
  clientId: string;
  title: string;
  taxId: string;
  activityDescription: string;
  naceCode: string;
  activityTags: string[];
  activityProfile: Record<string, unknown>;
  workplaceAddresses: string[];
  chartAccounts: Record<string, unknown>[];
  chartAccountFileName: string;
  portalUserId: string;
  portalDisplayName: string;
};

export type DashboardClientRow = {
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

export type ChartRow = {
  key: string;
  label: string;
  count: number;
};

export type LocalSession = {
  userId: string;
  role: "client_user" | "accountant";
  sessionToken?: string;
  expiresAt?: string;
};
