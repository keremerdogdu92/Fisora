export type IntakeCategory = "sales_invoice" | "purchase_invoice" | "bank_statement" | "special_document";

export type DraftLine = {
  account_code: string;
  description: string;
  debit: string;
  credit: string;
};

export type ChartAccountOption = {
  code: string;
  name: string;
  isDetail: boolean;
  taxId: string;
  taxOffice: string;
  iban: string;
  searchText: string;
};

export type AccountCandidate = {
  code: string;
  name: string;
  reason: string;
};

export type AccountCandidateGroups = {
  purchaseStock: AccountCandidate[];
  purchaseExpense: AccountCandidate[];
  purchaseVat: AccountCandidate[];
  salesRevenue: AccountCandidate[];
  zeroVatRevenue: AccountCandidate[];
  salesVat: AccountCandidate[];
  customer: AccountCandidate[];
  supplier: AccountCandidate[];
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

export type RuleInterpretationView = {
  source: string;
  provider: string;
  status: string;
  summaryTr: string;
  triggerTr: string;
  actionTr: string;
  guardrailTr: string;
  confidence: number;
  reasonCodes: string[];
};

export type DecisionNarrativeView = {
  invoiceProductLine: string;
  fisoraInterpretation: string;
  businessRelation: string;
  accountCode: string;
  accountName: string;
  counterpartyMatch: string;
  confidenceLabel: string;
  unresolvedInfo: string;
  readFacts: Record<string, string>;
};

export type DocumentPipelineEvent = {
  eventId: string;
  step: string;
  status: string;
  messageTr: string;
  debugCode: string;
  details: Record<string, unknown>;
  createdAt: string;
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
  aiGateReason?: string;
  aiProductIdentity?: string;
  aiResearchRequested?: boolean;
  aiResearchQuery?: string;
  aiResolutionStatus?: string;
  aiRetryReason?: string;
  aiSuggestedAccountCode: string;
  aiSuggestedCounterpartyCode: string;
  aiRiskFlags: string[];
  aiAccountReason: string;
  clientNaceCode?: string;
  clientActivityTags?: string[];
  counterpartyTaxId?: string;
  counterpartyTitle?: string;
  counterpartyIdentityKey?: string;
  decisionNarrative?: DecisionNarrativeView;
  canonicalLineCount?: number;
  canonicalValidationStatus?: string;
  canonicalValidationReasons?: string[];
  canonicalExtractionAiUsed?: boolean;
  deterministicSummary: string;
  exportGateReason: string;
  draftStatus: string;
  draftConfidence?: number;
  primarySuggestion?: Record<string, unknown>;
  reviewBlockers?: string[];
  automationEligibility?: string;
  accountantActionHint?: string;
  accountantSummary: string;
  accountantExplanation?: string;
  aiQualityScorecard?: Record<string, unknown>;
  technicalDetails: Record<string, unknown>;
  pipelineEvents: DocumentPipelineEvent[];
  accountingDirection?: string;
  directionConflict?: DirectionConflict;
  staticFallbackAccount?: string;
  staticFallbackSuppressed?: boolean;
  selectedExpenseAccount: string;
  selectedVatAccount: string;
  selectedCounterpartyAccount: string;
  selectedRevenueAccount?: string;
  selectedPurchaseVatAccount?: string;
  selectedSalesVatAccount?: string;
  selectedCustomerAccount?: string;
  suggestedCounterpartyAccount?: string;
  counterpartyCreationSuggestion?: Record<string, unknown>;
  accountCandidates?: AccountCandidateGroups;
  counterpartyConfidence: number;
  reviewReasons: string[];
  riskFlags: string[];
  chartAccounts: ChartAccountOption[];
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
  ruleInterpretation: RuleInterpretationView | null;
  rulePrompt: RulePromptView;
};

export type PilotClient = {
  clientId: string;
  clientName: string;
  taxId: string;
  tckn?: string;
  vkn?: string;
  userLabel: string;
  portalUserId: string;
  onboardingStatus: string;
  onboardingAttachments?: {
    ref: string;
    type: string;
    label: string;
    fileName: string;
    status: string;
    createdAt: string;
  }[];
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

export type AiCapacityWindow = {
  limit?: number | null;
  remaining?: number | null;
  reset?: string;
};

export type AiCapacityAgentView = {
  kind: "document" | "research" | string;
  slot: string;
  label: string;
  configured: boolean;
  status: string;
  model?: string;
  source?: string;
  last_checked_at?: string;
  daily_requests?: AiCapacityWindow;
  minute_tokens?: AiCapacityWindow;
  estimates?: {
    document_queries?: number | null;
    internet_researches?: number | null;
    confidence?: string;
  };
};

export type DirectionConflict = {
  status: string;
  intakeDirection: string;
  detectedDirection: string;
  confidence: number;
  evidence: string[];
  questionTr: string;
  resolution?: string;
  resolvedDirection?: string;
};

export type AiCapacityEstimateView = {
  estimate_mode?: "conservative" | string;
  confidence?: "live" | "cached" | "partial" | "not_available" | string;
  last_checked_at?: string;
  reserve_percent?: number;
  retry_multiplier?: number;
};

export type AiCapacityView = {
  generated_at?: string;
  status?: string;
  agents?: AiCapacityAgentView[];
  totals?: {
    document_queries?: number | null;
    internet_researches?: number | null;
  };
  estimate?: AiCapacityEstimateView;
};

export type ResearchSourceView = {
  title?: string;
  url?: string;
  source_type?: string;
  accepted?: boolean;
};

export type ResearchProfileView = {
  kind: string;
  key: string;
  summary?: string;
  summary_tr?: string;
  product_category?: string;
  common_product_categories?: string[];
  business_relation?: string;
  account_treatment?: string;
  confidence?: number;
  research_confidence?: number;
  accounting_impact_confidence?: number;
  status?: string;
  updated_at?: string;
  evidence?: ResearchSourceView[];
  sources?: ResearchSourceView[];
  override?: boolean;
};

export type ResearchBenchmarkCaseView = {
  key?: string;
  expected_category?: string;
  actual_category?: string;
  confidence?: number;
  passed?: boolean;
};

export type ResearchBenchmarkRunView = {
  run_id?: string;
  created_at?: string;
  case_count?: number;
  passed_count?: number;
  matched_count?: number;
  accuracy?: number;
  metrics?: {
    brand_accuracy?: number;
    category_accuracy?: number;
    accounting_impact_accuracy?: number;
    review_gate_accuracy?: number;
  };
  cases?: ResearchBenchmarkCaseView[];
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
    canonicalLineCount?: number;
    canonicalValidationStatus?: string;
    canonicalValidationReasons?: string[];
    canonicalExtractionAiUsed?: boolean;
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
    aiGateReason?: string;
    aiProductIdentity?: string;
    aiResearchRequested?: boolean;
    aiResearchQuery?: string;
    aiResolutionStatus?: string;
    aiRetryReason?: string;
    aiSuggestedAccountCode?: string;
    aiSuggestedCounterpartyCode?: string;
    aiRiskFlags?: string[];
    aiAccountReason?: string;
    clientNaceCode?: string;
    clientActivityTags?: string[];
    counterpartyTaxId?: string;
    counterpartyTitle?: string;
    counterpartyIdentityKey?: string;
    exportStatus?: string;
    staticFallbackAccount?: string;
    staticFallbackSuppressed?: boolean;
    selectedExpenseAccount?: string;
    selectedVatAccount?: string;
    selectedSupplierAccount?: string;
    selectedRevenueAccount?: string;
    selectedPurchaseVatAccount?: string;
    selectedSalesVatAccount?: string;
    selectedCustomerAccount?: string;
    suggestedCounterpartyAccount?: string;
    counterpartyCreationSuggestion?: Record<string, unknown>;
    accountingDirection?: string;
    accountantExplanationTr?: string;
    accountant_explanation_tr?: string;
    counterpartyMatchCode?: string;
    counterpartyMatchConfidence?: number;
    processingMode?: string;
    deterministicChecks?: string[];
    exportGateReason?: string;
    draftConfidence?: number;
    draft_confidence?: number;
    primarySuggestion?: Record<string, unknown>;
    primary_suggestion?: Record<string, unknown>;
    reviewBlockers?: string[];
    review_blockers?: string[];
    automationEligibility?: string;
    automation_eligibility?: string;
    accountantActionHint?: string;
    accountant_action_hint?: string;
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
    ruleInterpretation?: RuleInterpretationView | null;
    rule_interpretation?: unknown;
    rulePrompt?: unknown;
    rule_prompt?: unknown;
  }[];
};

export type PilotMode = "client" | "accountant" | "agents" | "documents" | "clients" | "research" | "settings" | "exports" | "operations";
export type PortalRouteKey = "home" | "mukellef" | "musavir" | "ajanlar" | "belgeler" | "mukellefler" | "bilgi-havuzu" | "ayarlar" | "cikti" | "operasyon";
export type DocumentSegment = "sales_invoices" | "purchase_invoices" | "invoices" | "bank_statements" | "other_documents";
export type PortalNavItem = { mode: PilotMode; label: string; href: string };
export type ReviewFilter = "all" | "review_required" | "export_ready" | "cancel_requested";
export type ExportMode = "bulk" | "by_client";

export type CorrectionDraft = {
  accountCode: string;
  applyToSimilar: boolean;
  counterpartyCode: string;
  manualDraftLines: DraftLine[];
  reason: string;
  ruleInstruction: string;
};

export type ReviewLearningDecisionOptions = {
  learningConfirmation?: "none" | "save_rule" | "suggest_similar";
  confirmedRuleInterpretation?: RuleInterpretationView | null;
  suppressRulePromptKey?: string;
};

export type NewClientDraft = {
  clientId: string;
  title: string;
  taxId: string;
  tckn: string;
  vkn: string;
  identityType: string;
  taxIdentifier: string;
  legalName: string;
  tradeName: string;
  displayTitle: string;
  taxOffice: string;
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
  storageScope?: "local" | "tab";
  delegatedBy?: string;
  delegatedClientId?: string;
};
