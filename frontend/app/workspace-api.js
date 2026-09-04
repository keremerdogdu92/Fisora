// File: frontend/app/workspace-api.js
// Summary: Loads and normalizes portal workspace data, including attempt-scoped progressive invoice processing snapshots.
const { normalizeChartAccountOptions } = require("./portal-account-combobox");

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

function normalizeDirectionConflict(value) {
  const source = value && typeof value === "object" ? value : {};
  const status = safeText(source.status);
  if (!status) return {};
  const conflict = {
    status,
    intakeDirection: safeText(source.intake_direction || source.intakeDirection),
    detectedDirection: safeText(source.detected_direction || source.detectedDirection),
    confidence: safeNumber(source.confidence),
    evidence: safeList(source.evidence).map(String),
    questionTr: safeText(source.question_tr || source.questionTr),
  };
  const resolution = safeText(source.resolution);
  const resolvedDirection = safeText(source.resolved_direction || source.resolvedDirection);
  if (resolution) conflict.resolution = resolution;
  if (resolvedDirection) conflict.resolvedDirection = resolvedDirection;
  return conflict;
}

function normalizeRuleInterpretation(value) {
  if (!value || typeof value !== "object") return null;
  const status = safeText(value.status);
  const summaryTr = safeText(value.summary_tr || value.summaryTr);
  const triggerTr = safeText(value.trigger_tr || value.triggerTr);
  const actionTr = safeText(value.action_tr || value.actionTr);
  const guardrailTr = safeText(value.guardrail_tr || value.guardrailTr);
  if (!status && !summaryTr && !triggerTr && !actionTr && !guardrailTr) return null;
  return {
    source: safeText(value.source),
    provider: safeText(value.provider),
    status,
    summaryTr,
    triggerTr,
    actionTr,
    guardrailTr,
    confidence: safeNumber(value.confidence),
    reasonCodes: safeList(value.reason_codes || value.reasonCodes).map(String),
  };
}

function normalizeDecisionNarrative(value) {
  if (!value || typeof value !== "object") return undefined;
  const readFactsSource = value.read_facts || value.readFacts;
  const readFacts = {};
  if (readFactsSource && typeof readFactsSource === "object" && !Array.isArray(readFactsSource)) {
    for (const [key, factValue] of Object.entries(readFactsSource)) {
      if (safeText(factValue)) readFacts[String(key)] = safeText(factValue);
    }
  }
  const narrative = {
    invoiceProductLine: safeText(value.invoice_product_line || value.invoiceProductLine),
    fisoraInterpretation: safeText(value.fisora_interpretation || value.fisoraInterpretation),
    businessRelation: safeText(value.business_relation || value.businessRelation),
    accountCode: safeText(value.account_code || value.accountCode),
    accountName: safeText(value.account_name || value.accountName),
    counterpartyMatch: safeText(value.counterparty_match || value.counterpartyMatch),
    confidenceLabel: safeText(value.confidence_label || value.confidenceLabel),
    unresolvedInfo: safeText(value.unresolved_info || value.unresolvedInfo),
    readFacts,
  };
  return Object.values(narrative).some((item) => (typeof item === "string" ? item : Object.keys(item).length)) ? narrative : undefined;
}

const DEFAULT_BACKEND_TIMEOUT_MS = 20000;
const DEFAULT_WORKSPACE_VIEW = "review";

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
  workspaceView = DEFAULT_WORKSPACE_VIEW,
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
        path: workspacePath(clientIdFromRecord(client), workspaceView),
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

function workspacePath(clientId, view) {
  const encodedClientId = encodeURIComponent(clientId);
  const normalizedView = safeText(view).trim();
  const query = normalizedView ? `?view=${encodeURIComponent(normalizedView)}` : "";
  return `/phase0/store/workspace/${encodedClientId}${query}`;
}

async function fetchDocumentProgress({
  apiBaseUrl,
  clientId,
  documentRef,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
}) {
  return getJson({
    apiBaseUrl,
    path: `/phase0/store/workspace/${encodeURIComponent(clientId)}/documents/${encodeURIComponent(documentRef)}/progress`,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
    timeoutMs,
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
  const portalUser = safeList(workspace?.portal_users).find((user) => user?.role === "client_user") || {};
  const onboarding = clientRecord?.onboarding || {};
  const missingOnboarding = safeList(onboarding?.missing_fields);
  return {
    clientId,
    clientName: safeText(profile.title || clientRecord?.title, clientId || "Mükellef"),
    taxId: safeText(profile.tax_id || profile.tax_identifier || clientRecord?.tax_id),
    tckn: safeText(profile.tckn),
    vkn: safeText(profile.vkn),
    legalName: safeText(profile.legal_name),
    tradeName: safeText(profile.trade_name),
    taxOffice: safeText(profile.tax_office),
    naceCode: safeText(profile.nace_code),
    activityDescription: safeText(profile.activity_description),
    workplaceAddresses: safeList(profile.workplace_addresses).map(String).filter(Boolean),
    chartAccountCount: Number(workspace?.chart_accounts?.account_count || 0),
    userLabel: safeText(portalUser.display_name || portalUser.user_id),
    portalUserId: safeText(portalUser.user_id),
    onboardingStatus: onboarding?.is_ready ? "Kurulum tamam" : missingOnboarding.length ? `${missingOnboarding.length} kurulum eksiği` : "Çalışma alanı",
    onboardingAttachments: normalizeOnboardingAttachments(workspace),
  };
}

function clientIdFromRecord(clientRecord) {
  const profile = clientRecord?.profile || {};
  return safeText(clientRecord?.client_id || profile.client_id || clientRecord?.id).trim();
}

function normalizeOnboardingAttachments(workspace) {
  return safeList(workspace?.onboarding_attachments)
    .map((attachment) => {
      const type = safeText(attachment?.attachment_type, "onboarding_attachment");
      return {
        ref: safeText(attachment?.attachment_ref || attachment?.document_id || attachment?.original_file_name),
        type,
        label: onboardingAttachmentLabel(type),
        fileName: safeText(attachment?.original_file_name || attachment?.stored_file_name, "-"),
        status: safeText(attachment?.storage_status || attachment?.status, "-"),
        createdAt: safeText(attachment?.created_at || attachment?.updated_at),
      };
    })
    .filter((attachment) => attachment.ref);
}

function onboardingAttachmentLabel(type) {
  if (type === "tax_certificate") return "Vergi levhasi";
  if (type === "chart_accounts") return "Hesap plani";
  return "Onboarding dosyasi";
}

function latestProcessingJob(workspace, documentRef) {
  return safeList(workspace?.processing_jobs)
    .filter((job) => safeText(job?.document_ref) === safeText(documentRef))
    .sort((left, right) => safeText(right?.updated_at || right?.created_at).localeCompare(safeText(left?.updated_at || left?.created_at)))[0] || {};
}

function activeProcessingJob(workspace, documentRef) {
  const job = latestProcessingJob(workspace, documentRef);
  const status = safeText(job?.status).toLowerCase();
  return ["queued", "processing", "retry_wait", "failed"].includes(status) ? job : null;
}

function backendDocumentsForWorkspace(workspace, client) {
  const uploads = safeList(workspace?.uploaded_documents);
  const uploadByRef = new Map(uploads.map((document) => [safeText(document?.document_ref), document]));
  const processedRefs = new Set(safeList(workspace?.documents).map((document) => safeText(document?.document_ref)));
  const processed = safeList(workspace?.documents).map((document) => {
    const documentRef = safeText(document?.document_ref || document?.result?.file_name || document?.id);
    const activeJob = activeProcessingJob(workspace, documentRef);
    return activeJob
      ? pendingBackendDocument(uploadByRef.get(documentRef) || { document_ref: documentRef, document_type: document?.document_type }, workspace, client, activeJob)
      : processedBackendDocument(document, workspace, client);
  });
  const pending = uploads
    .filter((document) => !processedRefs.has(safeText(document?.document_ref)))
    .map((document) => pendingBackendDocument(document, workspace, client));
  return [...processed, ...pending];
}

function normalizeSourceReviewRows(value) {
  return safeList(value).map((row) => {
    const amountBasis = safeText(row?.amount_basis || row?.amountBasis, "none");
    const role = safeText(row?.role, "informational");
    return {
      sourcePosition: safeText(row?.source_position || row?.sourcePosition),
      sourceText: safeText(row?.source_text || row?.sourceText),
      description: safeText(row?.description),
      amount: safeText(row?.amount),
      amountLabel: safeText(row?.amount_label || row?.amountLabel),
      amountBasis: ["line_total_ex_tax", "line_total_inc_tax", "ambiguous", "none"].includes(amountBasis) ? amountBasis : "none",
      role: ["posting_candidate", "group_or_subtotal", "informational"].includes(role) ? role : "informational",
    };
  }).filter((row) => row.sourcePosition || row.sourceText || row.description);
}

function normalizeSourceSnapshot(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const sections = safeList(value.sections).map((section) => ({
    kind: safeText(section?.kind),
    title: section?.title == null ? null : safeText(section?.title),
    columns: safeList(section?.columns).map(String),
    rows: safeList(section?.rows).map((row) => safeList(row).map(String)),
    columnCount: safeNumber(section?.columnCount),
    meta: section?.meta && typeof section.meta === "object" ? section.meta : {},
  }));
  if (!sections.length) return undefined;
  return {
    version: safeText(value.version),
    source: {
      file: value?.source?.file == null ? null : safeText(value?.source?.file),
      folder: value?.source?.folder == null ? null : safeText(value?.source?.folder),
      bytes: safeNumber(value?.source?.bytes),
    },
    mode: safeText(value.mode),
    confidence: safeNumber(value.confidence),
    sections,
    warnings: safeList(value.warnings).map(String),
    metrics: {
      sectionCount: safeNumber(value?.metrics?.sectionCount),
      rowCount: safeNumber(value?.metrics?.rowCount),
      columnCount: safeNumber(value?.metrics?.columnCount),
    },
  };
}

function readerSourceReviewRows(reader) {
  return normalizeSourceReviewRows(safeList(reader?.invoice_table_rows).map((row) => ({
    source_position: row?.source_position,
    source_text: row?.source_text,
    description: row?.description,
    amount: row?.ui_amount,
    amount_label: row?.ui_amount_label,
    amount_basis: row?.ui_amount_basis,
    role: row?.ui_role,
  })));
}

function labeledSnapshotValue(lines, labels) {
  const normalizedLabels = labels.map((label) => label.toLocaleUpperCase("tr-TR"));
  const match = safeList(lines).find((item) => {
    const label = safeText(item?.label).toLocaleUpperCase("tr-TR");
    return normalizedLabels.some((candidate) => label.includes(candidate));
  });
  return safeText(match?.value);
}

function processingStagesForJob(job) {
  const snapshot = job?.processing_snapshot && typeof job.processing_snapshot === "object" ? job.processing_snapshot : {};
  const stages = snapshot?.stages && typeof snapshot.stages === "object" ? snapshot.stages : {};
  const jobStatus = safeText(job?.status).toLowerCase();
  const fallbackReaderStatus = jobStatus === "processing" ? "processing" : "pending";
  const stage = (key, fallbackStatus) => ({
    status: safeText(stages?.[key]?.status, fallbackStatus),
    elapsedMs: safeNumber(stages?.[key]?.elapsed_ms),
  });
  return {
    attemptId: safeText(snapshot?.attempt_id),
    attemptCount: safeNumber(snapshot?.attempt_count || job?.attempt_count),
    currentStage: safeText(snapshot?.current_stage, jobStatus === "processing" ? "reader" : jobStatus),
    reader: stage("reader", fallbackReaderStatus),
    planner: stage("planner", "pending"),
    final: stage("final", "pending"),
  };
}

function progressiveFieldsForJob(job) {
  const snapshot = job?.processing_snapshot && typeof job.processing_snapshot === "object" ? job.processing_snapshot : {};
  const reader = snapshot?.reader && typeof snapshot.reader === "object" ? snapshot.reader : {};
  const planner = snapshot?.planner && typeof snapshot.planner === "object" ? snapshot.planner : {};
  const sourceReviewRows = readerSourceReviewRows(reader);
  const sourceSnapshot = normalizeSourceSnapshot(reader?.source_snapshot);
  const isHtmlSource = safeText(reader?.reader_kind) === "html_source_reader";
  const issueDate = labeledSnapshotValue(reader?.document_header, ["FATURA TARİH", "FATURA TARIH", "ISSUE DATE", "TARİH", "TARIH"]);
  const amount = labeledSnapshotValue(reader?.printed_summary_lines, ["ÖDENECEK TOPLAM", "ODENECEK TOPLAM", "ÖDENECEK TUTAR", "ODENECEK TUTAR", "PAYABLE"]);
  const exactCounterpartyCode = safeText(planner?.counterparty_match) === "exact" ? safeText(planner?.counterparty_account_code) : "";
  return {
    status: statusForBackendJob(job?.status),
    provider: isHtmlSource ? "HTML Source Reader" : snapshot?.current_stage ? "AI invoice pipeline" : "Belge yükleme",
    issueDate: issueDate || "-",
    amount: amount || "-",
    sourceReviewRows,
    sourceSnapshot,
    accountingDirection: safeText(planner?.accounting_direction),
    counterpartyTitle: safeText(planner?.counterparty_name),
    counterpartyTaxId: safeText(planner?.counterparty_identifier),
    selectedCounterpartyAccount: exactCounterpartyCode || "-",
    suggestedCounterpartyAccount: exactCounterpartyCode || "-",
    draftStatus: isHtmlSource ? "manual_draft_required" : "processing",
    processingStages: processingStagesForJob(job),
    exportGateReason: isHtmlSource
      ? "HTML kaynak satırları hazır; muhasebe kararı bu geçici denemede otomatik çalıştırılmadı."
      : "Final Accountant tamamlanmadan onay veya çıktı alınamaz.",
    accountantSummary: isHtmlSource
      ? sourceReviewRows.length
        ? "HTML kaynak satırları ve orijinal karşılaştırma hazır; muhasebe kararı bu geçici denemede çalıştırılmadı."
        : "HTML kaynak okuyucu sonucu bekleniyor."
      : sourceReviewRows.length
        ? "Kaynak fatura satırları hazır; muhasebe fişi Final Accountant tarafından hazırlanıyor."
        : "Belge işleniyor; Reader sonucu bekleniyor.",
  };
}

function mergeProcessingJobIntoDocument(document, job) {
  if (!document || !job) return document;
  const fields = progressiveFieldsForJob(job);
  return {
    ...document,
    ...fields,
    accountingDirection: fields.accountingDirection || document.accountingDirection,
    draftLines: [],
    lineDecisions: [],
    reviewReasons: [],
    riskFlags: [],
  };
}

function processedBackendDocument(document, workspace, client) {
  const result = document?.result || {};
  const documentRef = safeText(document?.document_ref || result.file_name || document?.id);
  const uploadedDocument = safeList(workspace?.uploaded_documents).find((item) => safeText(item?.document_ref) === documentRef) || {};
  const originalDocumentRef = safeText(uploadedDocument?.document_ref || documentRef);
  const intakeSource = uploadedDocument?.intake_category || result.intake_category || document?.intake_category || result.invoice_type || document?.document_type;
  const chartAccounts = normalizeChartAccountOptions(safeList(workspace?.chart_accounts?.accounts));
  return {
    id: documentRef,
    clientId: client.clientId,
    clientName: client.clientName,
    fileName: safeText(result.file_name || document?.document_ref, documentRef),
    documentType: safeText(result.invoice_type || document?.document_type, "invoice"),
    intakeCategory: intakeCategoryForBackendDocument(intakeSource),
    period: safeText(uploadedDocument?.period || result.period || document?.period) || periodFromDate(safeText(result.issue_date || document?.created_at || document?.updated_at)),
    uploadedAt: safeText(document?.created_at || document?.updated_at),
    uploadedBy: client.userLabel,
    status: statusForBackendDocument(document?.export_status || result.export_status || result.status),
    originalDocumentRef,
    originalDocumentMimeType: safeText(uploadedDocument?.content_type || result.content_type || mimeTypeForFile(safeText(result.file_name || document?.document_ref))),
    provider: safeText(result.provider_hint, "Çalışma alanı"),
    qnbStatus: safeText(uploadedDocument?.source_qnb_normalized_status),
    qnbStatusCheckedAt: safeText(uploadedDocument?.source_qnb_status_checked_at),
    qnbPulledAt: safeText(uploadedDocument?.source_pulled_at),
    qnbStatusChanged: Boolean(uploadedDocument?.source_qnb_status_changed),
    qnbReviewRequired: Boolean(uploadedDocument?.qnb_review_required),
    qnbStatusDetail: safeText(uploadedDocument?.source_qnb_status_detail),
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
    aiGateReason: safeText(result.ai_gate_reason),
    aiProductIdentity: safeText(result.ai_product_identity),
    aiResearchRequested: Boolean(result.ai_research_requested),
    aiResearchQuery: safeText(result.ai_research_query),
    aiResolutionStatus: safeText(result.ai_resolution_status),
    aiRetryReason: safeText(result.ai_retry_reason),
    aiAttemptedAccountCode: safeText(result.ai_attempted_account_code),
    aiSuggestedAccountCode: safeText(result.ai_suggested_account_code),
    aiSuggestedCounterpartyCode: safeText(result.ai_suggested_counterparty_code || result.counterparty_match_code || result.selected_supplier_account),
    aiRiskFlags: safeList(result.ai_risk_flags).map(String),
    aiAccountReason: safeText(result.ai_account_reason || result.counterparty_match_reason || result.learning_rule_reason),
    clientNaceCode: safeText(result.client_nace_code),
    clientActivityTags: safeList(result.client_activity_tags).map(String),
    counterpartyTaxId: safeText(result.counterparty_tax_id),
    counterpartyTitle: safeText(result.counterparty_title),
    counterpartyIdentityKey: safeText(result.counterparty_identity_key),
    decisionNarrative: normalizeDecisionNarrative(result.decision_narrative || result.decisionNarrative),
    canonicalLineCount: safeNumber(result.canonical_line_count),
    canonicalValidationStatus: safeText(result.canonical_validation_status),
    canonicalValidationReasons: safeList(result.canonical_validation_reasons).map(String),
    canonicalExtractionAiUsed: Boolean(result.canonical_extraction_ai_used),
    deterministicSummary: safeList(result.deterministic_checks).join(", "),
    exportGateReason: safeText(result.export_gate_reason),
    draftStatus: safeText(result.draft_status, safeList(result.draft_lines).length ? "draft_ready" : "manual_draft_required"),
    draftConfidence: safeNumber(result.draft_confidence),
    chartAccounts,
    primarySuggestion: result.primary_suggestion && typeof result.primary_suggestion === "object" ? result.primary_suggestion : {},
    reviewBlockers: safeList(result.review_blockers).map(String),
    automationEligibility: safeText(result.automation_eligibility),
    accountantActionHint: safeText(result.accountant_action_hint),
    accountantSummary: safeText(result.accountant_summary, accountantSummaryForResult(result)),
    accountantExplanation: safeText(result.accountant_explanation_tr || result.ai_explanation_tr || result.accountant_summary),
    aiQualityScorecard: result.ai_quality_scorecard && typeof result.ai_quality_scorecard === "object" ? result.ai_quality_scorecard : {},
    technicalDetails: result.technical_details && typeof result.technical_details === "object" ? result.technical_details : {},
    pipelineEvents: pipelineEventsForDocument(workspace, documentRef, originalDocumentRef),
    accountingDirection: safeText(result.accounting_direction || directionForBackendDocument(intakeSource)),
    directionConflict: normalizeDirectionConflict(result.direction_conflict),
    staticFallbackAccount: safeText(result.static_fallback_account),
    staticFallbackSuppressed: Boolean(result.static_fallback_suppressed),
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
    sourceReviewRows: normalizeSourceReviewRows(result.source_review_rows),
    sourceSnapshot: normalizeSourceSnapshot(result.source_snapshot),
    lineDecisions: safeList(result.line_decisions),
    statementLines: safeList(result.statement_lines),
    statementEntries: safeList(result.statement_entries),
    statementAiSuggestions: safeList(result.statement_ai_suggestions),
    statementAiSummary: statementAiSummaryText(result.statement_ai_summary),
    accountingIntent: safeText(result.accounting_intent),
    accountingIntentConfidence: safeNumber(result.accounting_intent_confidence),
    learningRuleScope: safeText(result.learning_rule_scope),
    learningRuleReason: safeText(result.learning_rule_reason),
    learningRuleSourceSummary: safeText(result.learning_rule_source_summary || result.learning_rule_reason),
    ruleInterpretation: normalizeRuleInterpretation(result.rule_interpretation),
    rulePrompt: normalizeRulePrompt(result.rule_prompt),
  };
}

function pendingBackendDocument(document, workspace, client, processingJob = null) {
  const documentRef = safeText(document?.document_ref || document?.document_id || document?.original_file_name);
  const job = processingJob || latestProcessingJob(workspace, documentRef);
  const documentType = safeText(document?.document_type || job.document_type, "invoice");
  const chartAccounts = normalizeChartAccountOptions(safeList(workspace?.chart_accounts?.accounts));
  const progressive = progressiveFieldsForJob(job);
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
    aiGateReason: "",
    aiProductIdentity: "",
    aiResearchRequested: false,
    aiResearchQuery: "",
    aiResolutionStatus: "",
    aiRetryReason: "",
    aiAttemptedAccountCode: "",
    aiSuggestedAccountCode: "",
    aiSuggestedCounterpartyCode: "",
    aiRiskFlags: [],
    aiAccountReason: "",
    clientNaceCode: "",
    clientActivityTags: [],
    counterpartyTaxId: "",
    counterpartyTitle: "",
    counterpartyIdentityKey: "",
    deterministicSummary: safeText(job.parser_kind, "queued"),
    exportGateReason: "İşleme ve müşavir kontrolü tamamlanmadan çıktıya alınmaz.",
    draftStatus: "processing",
    chartAccounts,
    accountantSummary: "Belge alındı; fiş taslağı işleme kuyruğunda hazırlanacak.",
    accountantExplanation: "Belge henuz muhasebe gerekcesi uretmedi.",
    aiQualityScorecard: {},
    technicalDetails: {},
    pipelineEvents: pipelineEventsForDocument(workspace, documentRef, documentRef),
    accountingDirection: directionForBackendDocument(document?.intake_category || job.intake_category || documentType),
    directionConflict: {},
    staticFallbackAccount: "",
    staticFallbackSuppressed: false,
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
    sourceReviewRows: [],
    statementLines: [],
    statementEntries: [],
    statementAiSuggestions: [],
    statementAiSummary: "",
    accountingIntent: "",
    accountingIntentConfidence: 0,
    learningRuleScope: "",
    learningRuleReason: "",
    learningRuleSourceSummary: "",
    ruleInterpretation: null,
    rulePrompt: normalizeRulePrompt({}),
    ...progressive,
    accountingDirection: progressive.accountingDirection || directionForBackendDocument(document?.intake_category || job.intake_category || documentType),
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
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "text/html";
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
  fetchDocumentProgress,
  mergeProcessingJobIntoDocument,
  normalizeBackendWorkspaces,
  overrideResearchProfile,
  refreshResearchProfile,
  runResearchBenchmark,
  turkishResearchSummary,
};
