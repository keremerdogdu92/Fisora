function trimSlashes(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function safeText(value, fallback = "") {
  return value == null || value === "" ? fallback : String(value);
}

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function turkishResearchSummary(profile) {
  const summaryTr = safeText(profile?.summary_tr ?? profile?.summaryTr);
  if (summaryTr) return summaryTr;
  return "Kaynak özeti Türkçeye çevrilmemiş. Detay panelinde ham kaynak metni incelenebilir.";
}

function normalizeAccountCandidate(candidate) {
  return {
    code: safeText(candidate?.code),
    name: safeText(candidate?.name),
    reason: safeText(candidate?.reason),
  };
}

function normalizeAccountCandidates(value) {
  const source = value && typeof value === "object" ? value : {};
  const list = (key) => safeList(source[key]).map(normalizeAccountCandidate).filter((candidate) => candidate.code);
  return {
    purchaseStock: list("purchase_stock"),
    purchaseExpense: list("purchase_expense"),
    purchaseVat: list("purchase_vat"),
    salesRevenue: list("sales_revenue"),
    zeroVatRevenue: list("zero_vat_revenue"),
    salesVat: list("sales_vat"),
    customer: list("customer"),
    supplier: list("supplier"),
  };
}

const DEFAULT_BACKEND_TIMEOUT_MS = 2500;

function backendAuthHeaders({ sessionToken = "", userId = "" } = {}) {
  const token = safeText(sessionToken).trim();
  const normalizedUserId = safeText(userId).trim();
  return {
    ...(token ? { "X-Fisora-Session": token } : {}),
    ...(normalizedUserId ? { "X-Fisora-User-Id": normalizedUserId } : {}),
  };
}

async function responseErrorMessage(response, fallback) {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string") return payload.detail;
    if (payload?.detail) return JSON.stringify(payload.detail);
    return JSON.stringify(payload);
  } catch {
    return fallback;
  }
}

async function fetchWithTimeout(fetchImpl, url, options, timeoutMs) {
  if (typeof AbortController === "undefined") {
    return fetchImpl(url, options);
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetchImpl(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

async function getJson({ apiBaseUrl, path, headers = {}, fetchImpl = fetch, timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS }) {
  const response = await fetchWithTimeout(fetchImpl, `${trimSlashes(apiBaseUrl)}${path}`, {
    method: "GET",
    headers,
  }, timeoutMs);
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `${path} failed with ${response.status}`));
  }
  return response.json();
}

async function postJson({ apiBaseUrl, path, body = {}, headers = {}, fetchImpl = fetch, timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS }) {
  const response = await fetchWithTimeout(fetchImpl, `${trimSlashes(apiBaseUrl)}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  }, timeoutMs);
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `${path} failed with ${response.status}`));
  }
  return response.json();
}

async function fetchBackendPilotData({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  const headers = backendAuthHeaders({ sessionToken, userId });
  const clientsPayload = await getJson({
    apiBaseUrl,
    path: "/phase0/store/clients",
    headers,
    fetchImpl,
    timeoutMs,
  });
  const clients = safeList(clientsPayload?.clients);
  const workspaces = await Promise.all(
    clients.map((client) =>
      getJson({
        apiBaseUrl,
        path: `/phase0/store/workspace/${encodeURIComponent(clientIdFromRecord(client))}`,
        headers,
        fetchImpl,
        timeoutMs,
      }),
    ),
  );
  return normalizeBackendWorkspaces({
    clients,
    workspaces,
    source: "Çalışma alanı",
  });
}

async function fetchBackendReadiness({
  apiBaseUrl,
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return getJson({
    apiBaseUrl,
    path: "/phase0/store/system/readiness",
    headers: {},
    fetchImpl,
    timeoutMs,
  });
}

async function fetchAiCapacity({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return getJson({
    apiBaseUrl,
    path: "/phase0/store/ai-capacity",
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

async function fetchResearchProfiles({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  kind = "",
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return getJson({
    apiBaseUrl,
    path: `/phase0/store/research/profiles${query}`,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

async function fetchResearchProfile({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  kind,
  key,
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return getJson({
    apiBaseUrl,
    path: `/phase0/store/research/profile/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

async function refreshResearchProfile({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  payload = {},
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/research/refresh",
    body: payload,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

async function overrideResearchProfile({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  payload = {},
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/research/override",
    body: payload,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

async function runResearchBenchmark({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/research/benchmark/run",
    body: {},
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

async function fetchResearchBenchmarkRuns({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return getJson({
    apiBaseUrl,
    path: "/phase0/store/research/benchmark/runs",
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
  });
}

function normalizeBackendWorkspaces({ clients = [], workspaces = [], source = "Çalışma alanı" } = {}) {
  const normalizedClients = [];
  const documents = [];
  const exportBasket = [];

  workspaces.forEach((workspace, index) => {
    const clientRecord = workspace?.client || clients[index] || {};
    const client = normalizeBackendClient(clientRecord, workspace);
    normalizedClients.push(client);
    documents.push(...backendDocumentsForWorkspace(workspace, client));
    exportBasket.push(...backendExportBasketForWorkspace(workspace, client));
  });

  if (!normalizedClients.length) {
    clients.forEach((clientRecord) => normalizedClients.push(normalizeBackendClient(clientRecord, {})));
  }

  return {
    generatedFrom: source,
    clients: normalizedClients,
    documents,
    cancellationRequests: [],
    exportBasket,
  };
}

function normalizeBackendClient(clientRecord, workspace) {
  const profile = clientRecord?.profile || {};
  const clientId = clientIdFromRecord(clientRecord);
  const portalUser = safeList(workspace?.portal_users).find((user) => user?.role === "client_user") || safeList(workspace?.portal_users)[0] || {};
  return {
    clientId,
    clientName: safeText(profile.title || clientRecord?.title, clientId || "Mükellef"),
    taxId: safeText(profile.tax_id || clientRecord?.tax_id),
    userLabel: safeText(portalUser.display_name || portalUser.user_id, "Mükellef kullanıcısı"),
    portalUserId: safeText(portalUser.user_id, "mukellef-user"),
    onboardingStatus: "Çalışma alanı",
  };
}

function clientIdFromRecord(clientRecord) {
  const profile = clientRecord?.profile || {};
  return safeText(clientRecord?.client_id || profile.client_id || clientRecord?.id).trim();
}

function backendDocumentsForWorkspace(workspace, client) {
  const processedRefs = new Set(safeList(workspace?.documents).map((document) => safeText(document?.document_ref)));
  const processed = safeList(workspace?.documents).map((document) => processedBackendDocument(document, workspace, client));
  const pending = safeList(workspace?.uploaded_documents)
    .filter((document) => !processedRefs.has(safeText(document?.document_ref)))
    .map((document) => pendingBackendDocument(document, workspace, client));
  return [...processed, ...pending];
}

function processedBackendDocument(document, workspace, client) {
  const result = document?.result || {};
  const documentRef = safeText(document?.document_ref || result.file_name || document?.id);
  const uploadedDocument = safeList(workspace?.uploaded_documents).find((item) => safeText(item?.document_ref) === documentRef) || {};
  const originalDocumentRef = safeText(uploadedDocument?.document_ref || documentRef);
  return {
    id: documentRef,
    clientId: client.clientId,
    clientName: client.clientName,
    fileName: safeText(result.file_name || document?.document_ref, documentRef),
    documentType: safeText(result.invoice_type || document?.document_type, "invoice"),
    intakeCategory: intakeCategoryForBackendDocument(result.invoice_type || document?.document_type || result.intake_category),
    period: safeText(uploadedDocument?.period || result.period || document?.period) || periodFromDate(safeText(result.issue_date || document?.created_at || document?.updated_at)),
    uploadedAt: safeText(document?.created_at || document?.updated_at),
    uploadedBy: client.userLabel,
    status: statusForBackendDocument(document?.export_status || result.export_status || result.status),
    originalDocumentRef,
    originalDocumentMimeType: safeText(uploadedDocument?.content_type || result.content_type || mimeTypeForFile(safeText(result.file_name || document?.document_ref))),
    provider: safeText(result.provider_hint, "Çalışma alanı"),
    issueDate: safeText(result.issue_date, "-"),
    amount: safeText(result.payable_total, "0.00"),
    vatRates: safeList(result.vat_rates).map(String),
    productLine: safeText(result.product_line_hint, "-"),
    productCategory: safeText(result.product_category, "-"),
    businessRelation: safeText(result.business_relevance_relation, "-"),
    accountTreatment: safeText(result.business_relevance_account_treatment, "-"),
    requiresAccountantReview: Boolean(result.business_relevance_requires_review),
    previewText: safeText(result.business_relevance_reason || result.provider_hint, "İşleme sonucu hazır."),
    aiReason: safeText(result.ai_explanation_tr || result.ai_classification_reason || result.business_relevance_reason, "Öneri gerekçesi hazır."),
    aiProvider: safeText(result.ai_classification_provider || result.draft_decision_source, "-"),
    aiSuggestedAccountCode: safeText(result.ai_suggested_account_code || result.selected_expense_account),
    aiSuggestedCounterpartyCode: safeText(result.ai_suggested_counterparty_code || result.counterparty_match_code || result.selected_supplier_account),
    aiRiskFlags: safeList(result.ai_risk_flags).map(String),
    aiAccountReason: safeText(result.counterparty_match_reason || result.learning_rule_reason),
    deterministicSummary: safeList(result.deterministic_checks).join(", "),
    exportGateReason: safeText(result.export_gate_reason),
    draftStatus: safeText(result.draft_status, safeList(result.draft_lines).length ? "draft_ready" : "manual_draft_required"),
    accountantSummary: safeText(result.accountant_summary, accountantSummaryForResult(result)),
    accountantExplanation: safeText(result.accountant_explanation_tr || result.ai_explanation_tr || result.accountant_summary),
    technicalDetails: result.technical_details && typeof result.technical_details === "object" ? result.technical_details : {},
    pipelineEvents: pipelineEventsForDocument(workspace, documentRef, originalDocumentRef),
    accountingDirection: safeText(result.accounting_direction || directionForBackendDocument(result.invoice_type || document?.document_type || result.intake_category)),
    selectedExpenseAccount: safeText(result.selected_expense_account, "-"),
    selectedVatAccount: safeText(result.selected_vat_account, "-"),
    selectedCounterpartyAccount: safeText(result.selected_supplier_account || result.counterparty_match_code, "-"),
    selectedRevenueAccount: safeText(result.selected_revenue_account, "-"),
    selectedPurchaseVatAccount: safeText(result.selected_purchase_vat_account, result.selected_vat_account || "-"),
    selectedSalesVatAccount: safeText(result.selected_sales_vat_account, result.selected_vat_account || "-"),
    selectedCustomerAccount: safeText(result.selected_customer_account, "-"),
    suggestedCounterpartyAccount: safeText(result.suggested_counterparty_account, result.selected_supplier_account || result.counterparty_match_code || "-"),
    counterpartyCreationSuggestion: result.counterparty_creation_suggestion && typeof result.counterparty_creation_suggestion === "object" ? result.counterparty_creation_suggestion : {},
    accountCandidates: normalizeAccountCandidates(result.account_candidates),
    counterpartyConfidence: safeNumber(result.counterparty_match_confidence),
    reviewReasons: safeList(document?.review_reason_codes || result.review_reason_codes).map(String),
    riskFlags: safeList(result.risk_flags).map(String),
    draftLines: safeList(result.draft_lines),
    statementLines: safeList(result.statement_lines),
    statementEntries: safeList(result.statement_entries),
    statementAiSuggestions: safeList(result.statement_ai_suggestions),
    statementAiSummary: statementAiSummaryText(result.statement_ai_summary),
    accountingIntent: safeText(result.accounting_intent),
    accountingIntentConfidence: safeNumber(result.accounting_intent_confidence),
    learningRuleScope: safeText(result.learning_rule_scope),
    learningRuleReason: safeText(result.learning_rule_reason),
    learningRuleSourceSummary: safeText(result.learning_rule_source_summary || result.learning_rule_reason),
    rulePrompt: normalizeRulePrompt(result.rule_prompt),
  };
}

function pendingBackendDocument(document, workspace, client) {
  const documentRef = safeText(document?.document_ref || document?.document_id || document?.original_file_name);
  const job = safeList(workspace?.processing_jobs).find((item) => safeText(item?.document_ref) === documentRef) || {};
  const documentType = safeText(document?.document_type || job.document_type, "invoice");
  return {
    id: documentRef,
    clientId: client.clientId,
    clientName: client.clientName,
    fileName: safeText(document?.original_file_name || document?.stored_file_name, documentRef),
    documentType,
    intakeCategory: intakeCategoryForBackendDocument(document?.intake_category || job.intake_category || documentType),
    period: safeText(document?.period || job.period) || periodFromDate(safeText(document?.created_at || job.created_at || document?.updated_at)),
    uploadedAt: safeText(document?.created_at || document?.updated_at || job.created_at),
    uploadedBy: safeText(document?.uploaded_by, client.userLabel),
    status: statusForBackendJob(job.status || document?.status),
    originalDocumentRef: documentRef,
    originalDocumentMimeType: safeText(document?.content_type || mimeTypeForFile(safeText(document?.original_file_name || document?.stored_file_name))),
    provider: "Belge yükleme",
    issueDate: "-",
    amount: "-",
    vatRates: [],
    productLine: "-",
    productCategory: documentType,
    previewText: "Belge alındı; işleme sonucu hazırlanıyor.",
    aiReason: "İşleme sonucu hazırlanıyor.",
    aiProvider: "-",
    aiSuggestedAccountCode: "",
    aiSuggestedCounterpartyCode: "",
    aiRiskFlags: [],
    aiAccountReason: "",
    deterministicSummary: safeText(job.parser_kind, "queued"),
    exportGateReason: "İşleme ve müşavir kontrolü tamamlanmadan çıktıya alınmaz.",
    draftStatus: "processing",
    accountantSummary: "Belge alındı; fiş taslağı işleme kuyruğunda hazırlanacak.",
    accountantExplanation: "Belge henuz muhasebe gerekcesi uretmedi.",
    technicalDetails: {},
    pipelineEvents: pipelineEventsForDocument(workspace, documentRef, documentRef),
    accountingDirection: directionForBackendDocument(document?.intake_category || job.intake_category || documentType),
    selectedExpenseAccount: "-",
    selectedVatAccount: "-",
    selectedCounterpartyAccount: "-",
    selectedRevenueAccount: "-",
    selectedPurchaseVatAccount: "-",
    selectedSalesVatAccount: "-",
    selectedCustomerAccount: "-",
    suggestedCounterpartyAccount: "-",
    counterpartyCreationSuggestion: {},
    accountCandidates: normalizeAccountCandidates({}),
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
  };
}

function normalizePipelineEvent(event) {
  return {
    eventId: safeText(event?.event_id || event?.eventId),
    step: safeText(event?.step),
    status: safeText(event?.status),
    messageTr: safeText(event?.message_tr || event?.messageTr),
    debugCode: safeText(event?.debug_code || event?.debugCode),
    details: event?.details && typeof event.details === "object" ? event.details : {},
    createdAt: safeText(event?.created_at || event?.createdAt),
  };
}

function pipelineEventsForDocument(workspace, documentRef, originalDocumentRef) {
  const refs = new Set([documentRef, originalDocumentRef].map(safeText).filter(Boolean));
  return safeList(workspace?.document_pipeline_events)
    .filter((event) => refs.has(safeText(event?.document_ref || event?.documentRef)))
    .map(normalizePipelineEvent);
}

function mimeTypeForFile(fileName) {
  const lower = safeText(fileName).toLocaleLowerCase("tr-TR");
  if (lower.endsWith(".pdf")) return "application/pdf";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".xml")) return "application/xml";
  if (lower.endsWith(".csv")) return "text/csv";
  return "";
}

function accountantSummaryForResult(result) {
  if (safeList(result?.draft_lines).length) {
    return "Fiş taslağı hazır. Müşavir kontrolünden sonra çıktı listesine alınabilir.";
  }
  if (safeText(result?.document_validation_status) === "unexpected_document") {
    return "Bu dosya beklenen fatura/ekstre yapısında görünmüyor. Doğru belge yeniden istenmeli.";
  }
  return "Bu belge için otomatik fiş taslağı üretilemedi. Müşavir manuel fiş satırlarını girmeli.";
}

function backendExportBasketForWorkspace(workspace, client) {
  return safeList(workspace?.export_packages).map((record) => {
    const payload = record?.package || {};
    return {
      id: safeText(record?.id || payload.output_filename || `${client.clientId}-export`),
      clientId: client.clientId,
      clientName: client.clientName,
      documentIds: safeList(payload.document_refs).map(String),
      documentCount: safeNumber(payload.entry_count || payload.candidate_count),
      period: periodFromDate(safeText(record?.created_at || payload.created_at)),
      status: payload.downloaded_at || payload.output_filename ? "packaged" : "ready",
    };
  });
}

function intakeCategoryForBackendDocument(value) {
  const normalized = safeText(value).toLocaleLowerCase("tr-TR").replaceAll("ı", "i").replaceAll("ş", "s");
  if (normalized === "sales_invoice" || normalized === "satis" || normalized === "satis_faturasi" || normalized === "satis faturasi") {
    return "sales_invoice";
  }
  if (normalized === "purchase_invoice" || normalized === "alis" || normalized === "alış" || normalized === "alis_faturasi" || normalized === "alis faturasi") {
    return "purchase_invoice";
  }
  if (normalized === "bank_statement" || normalized === "pos_statement" || normalized === "bank" || normalized === "pos") {
    return "bank_statement";
  }
  if (normalized === "special_document") return "special_document";
  return "purchase_invoice";
}

function directionForBackendDocument(value) {
  const category = intakeCategoryForBackendDocument(value);
  if (category === "sales_invoice") return "sales";
  if (category === "purchase_invoice") return "purchase";
  return "";
}

function statusForBackendDocument(value) {
  const normalized = safeText(value).toLocaleLowerCase("tr-TR");
  if (normalized === "export_ready" || normalized === "auto_ready") return "export_ready";
  if (normalized === "rejected") return "review_required";
  if (normalized === "queued") return "queued";
  if (normalized === "processing") return "processing";
  if (normalized === "uploaded" || normalized === "stored") return "queued";
  return "review_required";
}

function statusForBackendJob(value) {
  const normalized = safeText(value).toLocaleLowerCase("tr-TR");
  if (normalized === "processing") return "processing";
  if (normalized === "completed") return "review_required";
  if (normalized === "failed") return "review_required";
  return "queued";
}

function periodFromDate(value, fallback = "2026-06") {
  const text = safeText(value);
  const dotted = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
  if (dotted) return `${dotted[3]}-${dotted[2].padStart(2, "0")}`;
  const iso = text.match(/^(\d{4})-(\d{2})/);
  if (iso) return `${iso[1]}-${iso[2]}`;
  return fallback;
}

function statementAiSummaryText(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}

function normalizeRulePrompt(value) {
  if (!value || typeof value !== "object") {
    return {
      show: false,
      defaultScope: "",
      message: "",
      clientConsistentDecisionCount: 0,
      officeDistinctClientCount: 0,
      officeConsistentDecisionCount: 0,
    };
  }
  return {
    show: Boolean(value.show),
    defaultScope: safeText(value.default_scope || value.defaultScope),
    message: safeText(value.message),
    clientConsistentDecisionCount: safeNumber(value.client_consistent_decision_count || value.clientConsistentDecisionCount),
    officeDistinctClientCount: safeNumber(value.office_distinct_client_count || value.officeDistinctClientCount),
    officeConsistentDecisionCount: safeNumber(value.office_consistent_decision_count || value.officeConsistentDecisionCount),
  };
}

module.exports = {
  backendAuthHeaders,
  fetchAiCapacity,
  fetchResearchBenchmarkRuns,
  fetchResearchProfile,
  fetchResearchProfiles,
  fetchBackendReadiness,
  fetchBackendPilotData,
  normalizeBackendWorkspaces,
  overrideResearchProfile,
  refreshResearchProfile,
  runResearchBenchmark,
  turkishResearchSummary,
};
