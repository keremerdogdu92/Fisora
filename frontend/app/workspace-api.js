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

function backendAuthHeaders({ sessionToken = "", userId = "" } = {}) {
  const token = safeText(sessionToken).trim();
  if (token) return { "X-Fisora-Session": token };
  const normalizedUserId = safeText(userId).trim();
  if (normalizedUserId) return { "X-Fisora-User-Id": normalizedUserId };
  return {};
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

async function getJson({ apiBaseUrl, path, headers = {}, fetchImpl = fetch }) {
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}${path}`, {
    method: "GET",
    headers,
  });
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
}) {
  const headers = backendAuthHeaders({ sessionToken, userId });
  const clientsPayload = await getJson({
    apiBaseUrl,
    path: "/phase0/store/clients",
    headers,
    fetchImpl,
  });
  const clients = safeList(clientsPayload?.clients);
  const workspaces = await Promise.all(
    clients.map((client) =>
      getJson({
        apiBaseUrl,
        path: `/phase0/store/workspace/${encodeURIComponent(clientIdFromRecord(client))}`,
        headers,
        fetchImpl,
      }),
    ),
  );
  return normalizeBackendWorkspaces({
    clients,
    workspaces,
    source: "Backend workspace",
  });
}

function normalizeBackendWorkspaces({ clients = [], workspaces = [], source = "Backend workspace" } = {}) {
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
    clientName: safeText(profile.title || clientRecord?.title, clientId || "Backend mukellef"),
    taxId: safeText(profile.tax_id || clientRecord?.tax_id),
    userLabel: safeText(portalUser.display_name || portalUser.user_id, "Mukellef kullanicisi"),
    portalUserId: safeText(portalUser.user_id, "mukellef-user"),
    onboardingStatus: "Backend workspace",
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
  return {
    id: documentRef,
    clientId: client.clientId,
    clientName: client.clientName,
    fileName: safeText(result.file_name || document?.document_ref, documentRef),
    documentType: safeText(result.invoice_type || document?.document_type, "invoice"),
    intakeCategory: intakeCategoryForBackendDocument(result.invoice_type || document?.document_type || result.intake_category),
    period: periodFromDate(safeText(result.issue_date || document?.created_at || document?.updated_at)),
    uploadedAt: safeText(document?.created_at || document?.updated_at),
    uploadedBy: client.userLabel,
    status: statusForBackendDocument(document?.export_status || result.export_status || result.status),
    provider: safeText(result.provider_hint, "Backend workspace"),
    issueDate: safeText(result.issue_date, "-"),
    amount: safeText(result.payable_total, "0.00"),
    vatRates: safeList(result.vat_rates).map(String),
    productLine: safeText(result.product_line_hint, "-"),
    productCategory: safeText(result.product_category, "-"),
    previewText: safeText(result.business_relevance_reason || result.provider_hint, "Backend workspace sonucu."),
    aiReason: safeText(result.ai_classification_reason || result.business_relevance_reason, "Backend workspace sonucu."),
    aiProvider: safeText(result.ai_classification_provider || result.draft_decision_source, "-"),
    aiSuggestedAccountCode: safeText(result.ai_suggested_account_code || result.selected_expense_account),
    aiSuggestedCounterpartyCode: safeText(result.ai_suggested_counterparty_code || result.counterparty_match_code || result.selected_supplier_account),
    aiRiskFlags: safeList(result.ai_risk_flags).map(String),
    aiAccountReason: safeText(result.counterparty_match_reason || result.learning_rule_reason),
    deterministicSummary: safeList(result.deterministic_checks).join(", "),
    exportGateReason: safeText(result.export_gate_reason),
    selectedExpenseAccount: safeText(result.selected_expense_account, "-"),
    selectedVatAccount: safeText(result.selected_vat_account, "-"),
    selectedCounterpartyAccount: safeText(result.selected_supplier_account || result.counterparty_match_code, "-"),
    counterpartyConfidence: safeNumber(result.counterparty_match_confidence),
    reviewReasons: safeList(document?.review_reason_codes || result.review_reason_codes).map(String),
    riskFlags: safeList(result.risk_flags).map(String),
    draftLines: safeList(result.draft_lines),
    statementLines: safeList(result.statement_lines),
    statementEntries: safeList(result.statement_entries),
    statementAiSuggestions: safeList(result.statement_ai_suggestions),
    statementAiSummary: statementAiSummaryText(result.statement_ai_summary),
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
    period: periodFromDate(safeText(document?.created_at || job.created_at || document?.updated_at)),
    uploadedAt: safeText(document?.created_at || document?.updated_at || job.created_at),
    uploadedBy: safeText(document?.uploaded_by, client.userLabel),
    status: statusForBackendJob(job.status || document?.status),
    provider: "Backend upload",
    issueDate: "-",
    amount: "-",
    vatRates: [],
    productLine: "-",
    productCategory: documentType,
    previewText: "Backend'e yuklendi; worker sonucu bekleniyor.",
    aiReason: "Worker sonucu bekleniyor.",
    aiProvider: "-",
    aiSuggestedAccountCode: "",
    aiSuggestedCounterpartyCode: "",
    aiRiskFlags: [],
    aiAccountReason: "",
    deterministicSummary: safeText(job.parser_kind, "queued"),
    exportGateReason: "Worker sonucu ve musavir kontrolu olmadan export kapali.",
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
  };
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

module.exports = {
  backendAuthHeaders,
  fetchBackendPilotData,
  normalizeBackendWorkspaces,
};
