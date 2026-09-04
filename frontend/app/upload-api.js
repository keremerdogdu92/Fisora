// File: frontend/app/upload-api.js
// Summary: Provides frontend API transport helpers and honest tax-certificate parse status messaging.
const DEFAULT_BACKEND_PORT = "8000";
const DEFAULT_UPLOAD_USER_ID = "ofis-mukellef-user";

function trimSlashes(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function resolveApiBaseUrl(pageUrl, configuredBaseUrl) {
  const configured = trimSlashes(configuredBaseUrl || process.env.NEXT_PUBLIC_FISORA_API_BASE_URL || "");
  if (configured) return configured;

  try {
    const url = new URL(pageUrl || "http://localhost:3000");
    return `${url.protocol}//${url.hostname}:${DEFAULT_BACKEND_PORT}`;
  } catch {
    return `http://localhost:${DEFAULT_BACKEND_PORT}`;
  }
}

function pickUploadUser({ session, selectedClient, fallbackUserId = DEFAULT_UPLOAD_USER_ID }) {
  if (session?.role === "client_user" && String(session.userId || "").trim()) {
    return String(session.userId).trim();
  }
  return String(selectedClient?.portalUserId || selectedClient?.userId || fallbackUserId).trim() || fallbackUserId;
}

function buildClientBootstrapPayload(client) {
  const clientId = String(client?.clientId || "ofis-calisma-client").trim();
  const clientName = String(client?.clientName || clientId || "Ofis Mükellefi").trim();
  const taxId = String(client?.taxId || "").trim();
  return {
    client_id: clientId,
    title: clientName,
    tax_id: taxId === "pilot-local" || taxId === "ofis-local" ? "" : taxId,
    has_chart_accounts: true,
  };
}

function buildPortalUserBootstrapPayload({ userId, displayName, clientId }) {
  const normalizedUserId = String(userId || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
  const normalizedClientId = String(clientId || "ofis-calisma-client").trim();
  return {
    user_id: normalizedUserId,
    display_name: String(displayName || normalizedUserId).trim() || normalizedUserId,
    role: "client_user",
    allowed_client_ids: [normalizedClientId],
  };
}

function slugifyClientId(value) {
  return String(value || "")
    .trim()
    .toLocaleLowerCase("tr-TR")
    .replace(/ç/g, "c")
    .replace(/ğ/g, "g")
    .replace(/ı/g, "i")
    .replace(/ö/g, "o")
    .replace(/ş/g, "s")
    .replace(/ü/g, "u")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function buildClientOnboardingPackagePayload({
  clientId = "",
  title = "",
  taxId = "",
  tckn = "",
  vkn = "",
  identityType = "",
  taxIdentifier = "",
  legalName = "",
  tradeName = "",
  displayTitle = "",
  taxOffice = "",
  activityDescription = "",
  naceCode = "",
  activityTags,
  activityProfile,
  workplaceAddresses,
  chartAccounts,
  portalUserId = "",
  portalDisplayName = "",
} = {}) {
  const normalizedTitle = String(title || "").trim();
  const normalizedClientId = String(clientId || slugifyClientId(normalizedTitle) || "yeni-mukellef").trim();
  const normalizedPortalUserId = String(portalUserId || "").trim();
  const normalizedChartAccounts = Array.isArray(chartAccounts) ? chartAccounts : [];
  const normalizedTckn = String(tckn || "").trim();
  const normalizedVkn = String(vkn || "").trim();
  const normalizedTaxIdentifier = String(normalizedVkn || normalizedTckn || taxIdentifier || taxId || "").trim();
  return {
    client: {
      client_id: normalizedClientId,
      title: normalizedTitle || normalizedClientId,
      tax_id: normalizedTaxIdentifier,
      tckn: normalizedTckn,
      vkn: normalizedVkn,
      identity_type: String(identityType || (normalizedTckn && normalizedVkn ? "tckn_vkn" : normalizedVkn ? "vkn" : normalizedTckn ? "tckn" : "")).trim(),
      tax_identifier: normalizedTaxIdentifier,
      legal_name: String(legalName || "").trim(),
      trade_name: String(tradeName || "").trim(),
      display_title: String(normalizedTitle || displayTitle || "").trim(),
      tax_office: String(taxOffice || "").trim(),
      activity_description: String(activityDescription || "").trim(),
      nace_code: String(naceCode || "").trim(),
      activity_tags: Array.isArray(activityTags) ? activityTags.map(String).map((value) => value.trim()).filter(Boolean) : [],
      activity_profile: activityProfile && typeof activityProfile === "object" ? activityProfile : {},
      ...(activityProfile?.nace_research_profile && typeof activityProfile.nace_research_profile === "object"
        ? { nace_research_profile: activityProfile.nace_research_profile }
        : {}),
      workplace_addresses: Array.isArray(workplaceAddresses) ? workplaceAddresses.map(String).map((value) => value.trim()).filter(Boolean) : [],
      has_chart_accounts: normalizedChartAccounts.length > 0,
    },
    chart_accounts: normalizedChartAccounts,
    portal_users: normalizedPortalUserId
      ? [{
          user_id: normalizedPortalUserId,
          display_name: String(portalDisplayName || normalizedTitle || normalizedPortalUserId).trim(),
          role: "client_user",
          allowed_client_ids: [normalizedClientId],
        }]
      : [],
  };
}

/**
 * @param {{ filledFields?: string[], confidence?: number, profileSummary?: string, parseStatus?: string, missingCriticalFields?: string[] }} options
 */
function buildTaxCertificateParseStatus({
  filledFields = [],
  confidence = 0,
  profileSummary = "",
  parseStatus = "",
  missingCriticalFields = [],
} = {}) {
  const fields = Array.isArray(filledFields) ? filledFields.filter(Boolean) : [];
  const missing = Array.isArray(missingCriticalFields) ? missingCriticalFields.map((value) => String(value || "").trim()).filter(Boolean) : [];
  if (String(parseStatus || "").trim() === "partial") {
    const labels = { title: "unvan", tax_identifier: "VKN/TCKN", nace_code: "NACE" };
    const missingLabel = missing.map((field) => labels[field] || field).join(", ");
    const readLabel = fields.length ? ` Okunan: ${fields.join(", ")}.` : "";
    const confidenceLabel = confidence ? ` Güven ${confidence}.` : "";
    const missingLabelText = missingLabel ? ` Eksik kritik alan: ${missingLabel}.` : "";
    return `Vergi levhası kısmen okundu.${readLabel}${confidenceLabel}${missingLabelText} Elle tamamlayabilirsiniz.`;
  }
  const base = fields.length
    ? `Vergi levhası okundu: ${fields.join(", ")}${confidence ? ` / güven ${confidence}` : ""}.`
    : "Vergi levhasından alan okunamadı; elle kayıt yapabilirsiniz.";
  return [base, profileSummary].filter(Boolean).join(" ");
}

function buildNaceResearchRefreshPayload({ naceCode = "", activityDescription = "", force = false } = {}) {
  const key = String(naceCode || "").trim();
  if (!key) return null;
  return {
    kind: "nace",
    key,
    activity_context: String(activityDescription || "").trim(),
    force: Boolean(force),
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

function backendAuthHeaders({ sessionToken = "", userId = "", userHeader = "" } = {}) {
  const headers = {};
  const normalizedSessionToken = String(sessionToken || "").trim();
  const normalizedUserId = String(userId || userHeader || "").trim();
  if (normalizedSessionToken) headers["X-Fisora-Session"] = normalizedSessionToken;
  if (normalizedUserId) headers["X-Fisora-User-Id"] = normalizedUserId;
  return headers;
}

function sessionAuthErrorMessage(message) {
  let reason = "";
  try {
    const parsed = JSON.parse(String(message || ""));
    reason = String(parsed?.reason || parsed?.detail?.reason || "");
  } catch {
    const text = String(message || "");
    const match = text.match(/"reason"\s*:\s*"([^"]+)"/);
    reason = match?.[1] || "";
  }
  if (reason === "session_not_found") {
    return "Oturum bulunamadı. Çıkış yapıp şifreyle tekrar giriş yapın.";
  }
  if (reason === "session_expired" || reason === "session_revoked") {
    return "Oturum süresi doldu. Çıkış yapıp şifreyle tekrar giriş yapın.";
  }
  if (reason === "session_required") {
    return "Bu işlem için şifreli oturum gerekli. Şifreyle tekrar giriş yapın.";
  }
  return "";
}

async function postJson({ apiBaseUrl, path, payload, headers = {}, fetchImpl = fetch }) {
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `${path} failed with ${response.status}`));
  }
  return response.json();
}

async function loginWithPassword({
  apiBaseUrl,
  userId,
  password,
  ttlHours = 12,
  fetchImpl = fetch,
}) {
  const payload = await postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/login",
    payload: {
      user_id: String(userId || "").trim(),
      password: String(password || ""),
      ttl_hours: Number(ttlHours || 12),
    },
    fetchImpl,
  });
  return {
    sessionToken: String(payload?.session_token || ""),
    userId: String(payload?.session?.user_id || userId || "").trim(),
    expiresAt: String(payload?.session?.expires_at || ""),
    raw: payload,
  };
}

async function requestPasswordReset({ apiBaseUrl, email, fetchImpl = fetch }) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/password-reset/request",
    payload: { email: String(email || "").trim() },
    fetchImpl,
  });
}

async function confirmPasswordReset({ apiBaseUrl, resetToken, password, fetchImpl = fetch }) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/password-reset/confirm",
    payload: { reset_token: String(resetToken || "").trim(), password: String(password || "") },
    fetchImpl,
  });
}

async function fetchAuthSession({
  apiBaseUrl,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
}) {
  return getJson({
    apiBaseUrl,
    path: "/phase0/store/auth/session",
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function createDelegatedClientSession({
  apiBaseUrl,
  clientId,
  targetUserId = "",
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  ttlHours = 12,
  fetchImpl = fetch,
}) {
  const payload = await postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/delegated-client-session",
    payload: {
      client_id: String(clientId || "").trim(),
      target_user_id: String(targetUserId || "").trim(),
      ttl_hours: Number(ttlHours || 12),
    },
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
  const session = payload?.session || {};
  return {
    sessionToken: String(payload?.session_token || ""),
    userId: String(session?.user_id || targetUserId || "").trim(),
    role: "client_user",
    storageScope: "tab",
    delegatedBy: String(payload?.delegated_by || session?.delegated_by || userId || "").trim(),
    delegatedClientId: String(payload?.delegated_client_id || session?.delegated_client_id || clientId || "").trim(),
    expiresAt: String(session?.expires_at || ""),
    raw: payload,
  };
}

function buildDelegatedClientPortalUrl({ origin = "", session }) {
  const normalizedOrigin = String(origin || "").replace(/\/+$/, "");
  const encodedSession = encodeURIComponent(JSON.stringify(session || {}));
  return `${normalizedOrigin}/portal/mukellef#delegated_session=${encodedSession}`;
}

function parseDelegatedSessionHash(hash = "") {
  const rawHash = String(hash || "").replace(/^#/, "");
  const params = new URLSearchParams(rawHash);
  const encodedSession = params.get("delegated_session");
  if (!encodedSession) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(encodedSession));
    if (!parsed?.sessionToken || !parsed?.userId) return null;
    return {
      sessionToken: String(parsed.sessionToken || ""),
      userId: String(parsed.userId || ""),
      role: "client_user",
      storageScope: "tab",
      delegatedBy: String(parsed.delegatedBy || ""),
      delegatedClientId: String(parsed.delegatedClientId || ""),
      expiresAt: String(parsed.expiresAt || ""),
    };
  } catch {
    return null;
  }
}

async function resetTestData({
  apiBaseUrl,
  confirmation,
  userId,
  sessionToken = "",
  deleteFiles = true,
  fetchImpl = fetch,
}) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/admin/test-reset",
    payload: {
      confirmation: String(confirmation || ""),
      delete_files: Boolean(deleteFiles),
    },
    headers: backendAuthHeaders({ sessionToken, userId: String(userId || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID }),
    fetchImpl,
  });
}

async function ensureUploadWorkspace({ apiBaseUrl, client, userId, displayName, sessionToken = "", fetchImpl = fetch }) {
  const clientPayload = buildClientBootstrapPayload(client);
  const headers = sessionToken ? { "X-Fisora-Session": String(sessionToken) } : {};
  await postJson({
    apiBaseUrl,
    path: "/phase0/store/client",
    payload: clientPayload,
    headers,
    fetchImpl,
  });
  await postJson({
    apiBaseUrl,
    path: "/phase0/store/portal-user",
    payload: buildPortalUserBootstrapPayload({
      userId,
      displayName,
      clientId: clientPayload.client_id,
    }),
    headers,
    fetchImpl,
  });
}

async function parseTaxCertificateFromBackend({
  apiBaseUrl,
  userId = "",
  sessionToken = "",
  file,
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const formData = new FormDataCtor();
  formData.append("file", file);
  const headers = sessionToken
    ? { "X-Fisora-Session": String(sessionToken) }
    : userId
      ? { "X-Fisora-User-Id": String(userId) }
      : {};
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/tax-certificate/parse`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `tax certificate parse failed with ${response.status}`));
  }
  return response.json();
}

async function parseChartAccountsFromBackend({
  apiBaseUrl,
  userId = "",
  sessionToken = "",
  file,
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const formData = new FormDataCtor();
  formData.append("file", file);
  const headers = sessionToken
    ? { "X-Fisora-Session": String(sessionToken) }
    : userId
      ? { "X-Fisora-User-Id": String(userId) }
      : {};
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/chart-accounts/parse`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `chart accounts parse failed with ${response.status}`));
  }
  return response.json();
}

async function createClientOnboardingPackage({
  apiBaseUrl,
  client,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
}) {
  const headers = backendAuthHeaders({ sessionToken, userId });
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/client-onboarding-package",
    payload: buildClientOnboardingPackagePayload(client),
    headers,
    fetchImpl,
  });
}

async function createPortalInvite({
  apiBaseUrl,
  userId,
  email = "",
  displayName = "",
  clientId,
  invitedBy = "",
  ttlHours = 48,
  sessionToken = "",
  userHeader = "",
  fetchImpl = fetch,
}) {
  const headers = backendAuthHeaders({ sessionToken, userHeader });
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/invite",
    payload: {
      user_id: String(userId || "").trim(),
      display_name: String(displayName || userId || "").trim(),
      role: "client_user",
      allowed_client_ids: [String(clientId || "").trim()].filter(Boolean),
      invited_by: String(invitedBy || "").trim(),
      email: String(email || "").trim(),
      ttl_hours: Number(ttlHours || 48),
    },
    headers,
    fetchImpl,
  });
}

async function setPortalPassword({
  apiBaseUrl,
  userId,
  password,
  sessionToken = "",
  userHeader = "",
  fetchImpl = fetch,
}) {
  const headers = backendAuthHeaders({ sessionToken, userHeader });
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/password",
    payload: {
      user_id: String(userId || "").trim(),
      password: String(password || ""),
    },
    headers,
    fetchImpl,
  });
}

async function updateClientPortalAccess({
  apiBaseUrl,
  clientId,
  oldUserId = "",
  newUserId,
  displayName = "",
  password = "",
  sessionToken = "",
  userHeader = "",
  fetchImpl = fetch,
}) {
  const headers = backendAuthHeaders({ sessionToken, userHeader });
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/client-portal-access",
    payload: {
      client_id: String(clientId || "").trim(),
      old_user_id: String(oldUserId || "").trim(),
      new_user_id: String(newUserId || "").trim(),
      display_name: String(displayName || "").trim(),
      password: String(password || ""),
    },
    headers,
    fetchImpl,
  });
}

async function deleteClientDocuments({
  apiBaseUrl,
  clientId,
  documentRefs,
  deleteFiles = true,
  sessionToken = "",
  userHeader = "",
  fetchImpl = fetch,
}) {
  const headers = backendAuthHeaders({ sessionToken, userHeader });
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/documents/delete",
    payload: {
      client_id: String(clientId || "").trim(),
      document_refs: Array.isArray(documentRefs) ? documentRefs.map((ref) => String(ref || "").trim()).filter(Boolean) : [],
      confirmed: true,
      delete_files: Boolean(deleteFiles),
    },
    headers,
    fetchImpl,
  });
}

async function createWorkspaceExportPackage({
  apiBaseUrl,
  clientId,
  exportType = "zirve_mapping_csv",
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/export-package/from-workspace",
    payload: {
      client_id: String(clientId || "").trim(),
      export_type: String(exportType || "zirve_mapping_csv").trim() || "zirve_mapping_csv",
    },
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function saveQnbConnectionToBackend({
  apiBaseUrl,
  clientId,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  connection,
  fetchImpl = fetch,
}) {
  return postJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}`,
    payload: {
      base_url: String(connection?.baseUrl || connection?.base_url || "").trim(),
      username: String(connection?.username || "").trim(),
      password: String(connection?.password || ""),
      vkn: String(connection?.vkn || "").trim(),
      environment: String(connection?.baseUrl || connection?.base_url || "").toLowerCase().includes("test") ? "test" : "production",
    },
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function fetchQnbConnectionStatus({
  apiBaseUrl,
  clientId,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  return getJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}`,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function disableQnbConnection({
  apiBaseUrl,
  clientId,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  return postJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}/disable`,
    payload: {},
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function syncQnbIncomingInvoices({
  apiBaseUrl,
  clientId,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  startDate = "",
  endDate = "",
  fetchImpl = fetch,
}) {
  return postJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}/sync-incoming-invoices`,
    payload: {
      start_date: String(startDate || "").trim(),
      end_date: String(endDate || "").trim(),
    },
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function fetchQnbSyncPolicy({ apiBaseUrl, clientId, userId = DEFAULT_UPLOAD_USER_ID, sessionToken = "", fetchImpl = fetch }) {
  return getJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}/sync-policy`,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function fetchQnbHealth({ apiBaseUrl, clientId, userId = DEFAULT_UPLOAD_USER_ID, sessionToken = "", fetchImpl = fetch }) {
  return getJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}/health`,
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function saveQnbSyncPolicy({ apiBaseUrl, clientId, userId = DEFAULT_UPLOAD_USER_ID, sessionToken = "", policy, fetchImpl = fetch }) {
  return postJson({
    apiBaseUrl,
    path: `/phase0/qnb/connections/${encodeURIComponent(String(clientId || "").trim())}/sync-policy`,
    payload: {
      enabled: Boolean(policy?.enabled),
      start_from_date: String(policy?.startFromDate || ""),
      frequency_minutes: Number(policy?.frequencyMinutes || 60),
      max_documents_per_run: Number(policy?.maxDocumentsPerRun || 100),
      status_reconciliation_enabled: Boolean(policy?.statusReconciliationEnabled),
    },
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}

async function uploadChartAccountsToBackend({
  apiBaseUrl,
  clientId,
  userId = "",
  sessionToken = "",
  file,
  storeOnly = false,
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const formData = new FormDataCtor();
  formData.append("client_id", String(clientId || ""));
  if (storeOnly) formData.append("store_only", "true");
  formData.append("file", file);

  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/chart-accounts/upload`, {
    method: "POST",
    headers: backendAuthHeaders({ sessionToken, userId }),
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `chart account upload failed with ${response.status}`));
  }
  return response.json();
}

async function uploadDocumentToBackend({
  apiBaseUrl,
  clientId,
  userId,
  uploadedBy,
  documentType,
  intakeCategory,
  period = "",
  file,
  retentionPolicyDays = 90,
  sessionToken = "",
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const normalizedUserId = String(userId || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
  const formData = new FormDataCtor();
  formData.append("client_id", String(clientId || ""));
  formData.append("document_type", String(documentType || "invoice"));
  formData.append("intake_category", String(intakeCategory || ""));
  if (period) formData.append("period", String(period));
  formData.append("uploaded_by", String(uploadedBy || normalizedUserId));
  formData.append("uploaded_by_user_id", normalizedUserId);
  formData.append("retention_policy_days", String(retentionPolicyDays));
  formData.append("file", file);

  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/document-upload-multipart`, {
    method: "POST",
    headers: backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `document upload failed with ${response.status}`));
  }
  return response.json();
}

function uploadTaxCertificateToBackend({
  apiBaseUrl,
  clientId,
  userId,
  uploadedBy,
  file,
  retentionPolicyDays = 365,
  sessionToken = "",
  taxCertificate = /** @type {Record<string, unknown> | null} */ (null),
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const normalizedUserId = String(userId || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
  const formData = new FormDataCtor();
  formData.append("client_id", String(clientId || ""));
  formData.append("attachment_type", "tax_certificate");
  formData.append("uploaded_by", String(uploadedBy || normalizedUserId));
  formData.append("uploaded_by_user_id", normalizedUserId);
  formData.append("retention_policy_days", String(retentionPolicyDays));
  if (taxCertificate && typeof taxCertificate === "object") {
    formData.append("tax_certificate_json", JSON.stringify(taxCertificate));
  }
  formData.append("file", file);

  return fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/client-onboarding-attachment`, {
    method: "POST",
    headers: backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    body: formData,
  }).then(async (response) => {
    if (!response.ok) {
      throw new Error(await responseErrorMessage(response, `tax certificate attachment failed with ${response.status}`));
    }
    return response.json();
  });
}

async function uploadDocumentsToBackend({
  apiBaseUrl,
  clientId,
  userId,
  uploadedBy,
  documentType,
  intakeCategory,
  period = "",
  files,
  retentionPolicyDays = 90,
  sessionToken = "",
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const uploads = Array.from(files || []);
  const results = [];
  for (const file of uploads) {
    try {
      const payload = await uploadDocumentToBackend({
        apiBaseUrl,
        clientId,
        userId,
        uploadedBy,
        documentType,
        intakeCategory,
        period,
        file,
        retentionPolicyDays,
        sessionToken,
        fetchImpl,
        FormDataCtor,
      });
      results.push({ fileName: String(file?.name || ""), ok: true, payload });
    } catch (error) {
      results.push({ fileName: String(file?.name || ""), ok: false, error: error instanceof Error ? error.message : String(error) });
    }
  }
  return results;
}

function normalizeStatementLinePayload(line) {
  return {
    line_no: Number(line?.line_no || line?.lineNo || 0),
    transaction_date: String(line?.transaction_date || line?.transactionDate || ""),
    description: String(line?.description || ""),
    amount: String(line?.amount || "0.00"),
    direction: String(line?.direction || ""),
    balance_after: String(line?.balance_after || line?.balanceAfter || ""),
    counterparty_name: String(line?.counterparty_name || line?.counterpartyName || ""),
    tax_id: String(line?.tax_id || line?.taxId || ""),
    iban: String(line?.iban || ""),
    suggested_account_code: String(line?.suggested_account_code || line?.suggestedAccountCode || ""),
    transaction_type: String(line?.transaction_type || line?.transactionType || "unknown"),
    confidence: Number(line?.confidence ?? 35),
    risk_flags: Array.isArray(line?.risk_flags) ? line.risk_flags.map(String) : Array.isArray(line?.riskFlags) ? line.riskFlags.map(String) : [],
    review_reason: String(line?.review_reason || line?.reviewReason || ""),
  };
}

async function requestStatementAiSuggestions({
  apiBaseUrl,
  clientId,
  lines,
  aiPolicy,
  providerName = "replay_provider",
  providerPayloads,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const payload = {
    client_id: String(clientId || ""),
    lines: Array.isArray(lines) ? lines.map(normalizeStatementLinePayload) : [],
    ai_policy: aiPolicy || {},
    provider_name: String(providerName || "replay_provider"),
    provider_payloads: Array.isArray(providerPayloads) ? providerPayloads : [],
  };
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/statement/ai-suggestions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(sessionToken ? { "X-Fisora-Session": String(sessionToken) } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `statement AI suggestions failed with ${response.status}`));
  }
  return response.json();
}

async function storeReviewDecision({
  apiBaseUrl,
  clientId,
  userId,
  documentRef,
  action,
  reviewer,
  correctedAccountCode = "",
  correctedCounterpartyCode = "",
  category = "",
  reason = "",
  decisionNote = "",
  accountantNote = "",
  ruleInstruction = "",
  applyToSimilar = false,
  learningConfirmation = "none",
  confirmedRuleInterpretation = null,
  suppressRulePromptKey = "",
  priorConsistentApprovalCount = 0,
  statementLineNo = 0,
  expectedRevision = 0,
  draftLines = /** @type {Array<Record<string, unknown>> | null} */ (null),
  validation = /** @type {Record<string, unknown> | null} */ (null),
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const normalizedUserId = String(userId || reviewer || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
  const normalizedDraftLines = Array.isArray(draftLines)
    ? draftLines
        .map((line) => ({
          account_code: String(line?.account_code || line?.accountCode || ""),
          description: String(line?.description || ""),
          debit: String(line?.debit || "0.00"),
          credit: String(line?.credit || "0.00"),
          ...(line?.tax_rate || line?.taxRate
            ? { tax_rate: String(line?.tax_rate || line?.taxRate || "") }
            : {}),
        }))
        .filter((line) => line.account_code || line.description || line.debit !== "0.00" || line.credit !== "0.00")
    : [];
  const normalizedDecisionNote = String(decisionNote || "").trim();
  const payload = {
    client_id: String(clientId || ""),
    decision: {
      document_ref: String(documentRef || ""),
      action: String(action || "approve"),
      reviewer: String(reviewer || normalizedUserId),
      corrected_account_code: String(correctedAccountCode || ""),
      corrected_counterparty_code: String(correctedCounterpartyCode || ""),
      category: String(category || ""),
      reason: String(reason || ""),
      accountant_note: normalizedDecisionNote || String(accountantNote || ""),
      rule_instruction: normalizedDecisionNote || String(ruleInstruction || ""),
      apply_to_similar: Boolean(applyToSimilar),
      prior_consistent_approval_count: Number(priorConsistentApprovalCount || 0),
      statement_line_no: Number(statementLineNo || 0),
    },
  };
  if (Number(expectedRevision || 0) > 0) {
    payload.decision.expected_revision = Number(expectedRevision);
  }
  if (normalizedDecisionNote) {
    payload.decision.decision_note = normalizedDecisionNote;
  }
  if (learningConfirmation && learningConfirmation !== "none") {
    payload.decision.learning_confirmation = String(learningConfirmation);
  }
  if (suppressRulePromptKey) {
    payload.decision.suppress_rule_prompt_key = String(suppressRulePromptKey);
  }
  const normalizedInterpretation = normalizeRuleInterpretationPayload(confirmedRuleInterpretation);
  if (normalizedInterpretation) {
    payload.decision.confirmed_rule_interpretation = normalizedInterpretation;
  }
  if (normalizedDraftLines.length) {
    payload.decision.draft_lines = normalizedDraftLines;
  }
  const readerStatus = String(validation?.readerStatus || validation?.reader_status || "");
  const accountingStatus = String(validation?.accountingStatus || validation?.accounting_status || "");
  if (readerStatus || accountingStatus) {
    payload.decision.validation = { reader_status: readerStatus, accounting_status: accountingStatus };
  }
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/review-decision`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `review decision failed with ${response.status}`));
  }
  return response.json();
}

async function reopenJournal({ apiBaseUrl, clientId, documentRef, expectedRevision, reason, userId = "", sessionToken = "", fetchImpl = fetch }) {
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/journal/reopen",
    payload: {
      client_id: String(clientId || "").trim(),
      document_ref: String(documentRef || "").trim(),
      expected_revision: Number(expectedRevision || 0),
      reviewer: String(userId || "").trim(),
      reason: String(reason || "").trim(),
    },
    headers: backendAuthHeaders({ sessionToken, userId }),
    fetchImpl,
  });
}
async function reviewCollaborationRequest({ apiBaseUrl, path, method = "POST", payload, userId = "", sessionToken = "", fetchImpl = fetch }) {
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...backendAuthHeaders({ userId, sessionToken }) },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await responseErrorMessage(response, `${path} failed with ${response.status}`));
  return response.json();
}

async function acquireReviewEditLease(args) {
  return reviewCollaborationRequest({ ...args, path: "/phase0/store/journal/edit-lease/acquire", payload: { client_id: args.clientId, document_ref: args.documentRef, expected_revision: args.expectedRevision } });
}

async function renewReviewEditLease(args) {
  return reviewCollaborationRequest({ ...args, path: "/phase0/store/journal/edit-lease/renew", payload: { client_id: args.clientId, document_ref: args.documentRef, user_activity_at: args.userActivityAt } });
}

async function releaseReviewEditLease(args) {
  return reviewCollaborationRequest({ ...args, path: "/phase0/store/journal/edit-lease/release", payload: { client_id: args.clientId, document_ref: args.documentRef, user_activity_at: new Date().toISOString() } });
}

async function saveReviewWorkingDraft(args) {
  return reviewCollaborationRequest({ ...args, method: "PUT", path: "/phase0/store/journal/working-draft", payload: { client_id: args.clientId, document_ref: args.documentRef, edit_lease_id: args.editLeaseId || args.documentRef, expected_revision: args.expectedRevision, draft_lines: args.draftLines || [], corrected_account_code: args.correctedAccountCode || "", corrected_counterparty_code: args.correctedCounterpartyCode || "", reason: args.reason || "" } });
}

async function fetchLearningRules({ apiBaseUrl, userId = "", sessionToken = "", fetchImpl = fetch }) {
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/learning-rules`, { headers: backendAuthHeaders({ userId, sessionToken }) });
  if (!response.ok) throw new Error(await responseErrorMessage(response, `learning rules failed with ${response.status}`));
  return response.json();
}

async function changeLearningRuleLifecycle({ apiBaseUrl, ruleKey, action, expectedVersion, reason = "", userId = "", sessionToken = "", fetchImpl = fetch }) {
  return reviewCollaborationRequest({ apiBaseUrl, path: `/phase0/store/learning-rules/${encodeURIComponent(ruleKey)}/${action}`, payload: { expected_version: Number(expectedVersion || 0), reason }, userId, sessionToken, fetchImpl });
}

async function reprocessDocument({
  apiBaseUrl,
  clientId,
  documentRef,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const normalizedUserId = userId || DEFAULT_UPLOAD_USER_ID;
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/document-reprocess`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    },
    body: JSON.stringify({
      client_id: String(clientId || ""),
      document_ref: String(documentRef || ""),
    }),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `document reprocess failed with ${response.status}`));
  }
  return response.json();
}

async function reprocessClient({
  apiBaseUrl,
  clientId,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  maxJobs = 50,
  fetchImpl = fetch,
}) {
  const normalizedUserId = userId || DEFAULT_UPLOAD_USER_ID;
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/client-reprocess`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    },
    body: JSON.stringify({
      client_id: String(clientId || ""),
      max_jobs: Number(maxJobs || 50),
    }),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `client reprocess failed with ${response.status}`));
  }
  return response.json();
}

async function previewReviewRule({
  apiBaseUrl,
  clientId,
  userId,
  documentRef,
  action,
  reviewer,
  correctedAccountCode = "",
  correctedCounterpartyCode = "",
  category = "",
  reason = "",
  decisionNote = "",
  accountantNote = "",
  ruleInstruction = "",
  applyToSimilar = false,
  statementLineNo = 0,
  draftLines = /** @type {Array<Record<string, unknown>> | null} */ (null),
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const normalizedUserId = String(userId || reviewer || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
  const normalizedDecisionNote = String(decisionNote || "").trim();
  const normalizedDraftLines = Array.isArray(draftLines)
    ? draftLines
        .map((line) => ({
          account_code: String(line?.account_code || line?.accountCode || ""),
          description: String(line?.description || ""),
          debit: String(line?.debit || "0.00"),
          credit: String(line?.credit || "0.00"),
          ...(line?.tax_rate || line?.taxRate
            ? { tax_rate: String(line?.tax_rate || line?.taxRate || "") }
            : {}),
        }))
        .filter((line) => line.account_code || line.description || line.debit !== "0.00" || line.credit !== "0.00")
    : [];
  const payload = {
    client_id: String(clientId || ""),
    decision: {
      document_ref: String(documentRef || ""),
      action: String(action || "suggest_for_similar"),
      reviewer: String(reviewer || normalizedUserId),
      corrected_account_code: String(correctedAccountCode || ""),
      corrected_counterparty_code: String(correctedCounterpartyCode || ""),
      category: String(category || ""),
      reason: String(reason || ""),
      decision_note: normalizedDecisionNote,
      accountant_note: normalizedDecisionNote || String(accountantNote || ""),
      rule_instruction: normalizedDecisionNote || String(ruleInstruction || ""),
      apply_to_similar: Boolean(applyToSimilar),
      statement_line_no: Number(statementLineNo || 0),
    },
  };
  if (normalizedDraftLines.length) {
    payload.decision.draft_lines = normalizedDraftLines;
  }
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/review-rule/preview`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `review rule preview failed with ${response.status}`));
  }
  return response.json();
}

function normalizeRuleInterpretationPayload(value) {
  if (!value || typeof value !== "object") return null;
  const source = value;
  const status = String(source.status || "").trim();
  const summary = String(source.summary_tr || source.summaryTr || "").trim();
  const trigger = String(source.trigger_tr || source.triggerTr || "").trim();
  const action = String(source.action_tr || source.actionTr || "").trim();
  const guardrail = String(source.guardrail_tr || source.guardrailTr || "").trim();
  if (!status && !summary && !trigger && !action && !guardrail) return null;
  const reasonCodes = Array.isArray(source.reason_codes)
    ? source.reason_codes
    : Array.isArray(source.reasonCodes)
      ? source.reasonCodes
      : [];
  return {
    status,
    summary_tr: summary,
    trigger_tr: trigger,
    action_tr: action,
    guardrail_tr: guardrail,
    confidence: Number(source.confidence || 0),
    reason_codes: reasonCodes.map(String).filter(Boolean),
  };
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

async function previewDocumentRetention({
  apiBaseUrl,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const normalizedUserId = userId || DEFAULT_UPLOAD_USER_ID;
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/document-retention/preview`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    },
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `document retention preview failed with ${response.status}`));
  }
  return response.json();
}

async function applyDocumentRetentionAction({
  apiBaseUrl,
  documentRefs,
  action,
  deleteFiles = true,
  userId = DEFAULT_UPLOAD_USER_ID,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const normalizedUserId = userId || DEFAULT_UPLOAD_USER_ID;
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/document-retention/action`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...backendAuthHeaders({ sessionToken, userId: normalizedUserId }),
    },
    body: JSON.stringify({
      document_refs: Array.from(documentRefs || []).map((ref) => String(ref || "")),
      action: String(action || ""),
      delete_files: Boolean(deleteFiles),
    }),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `document retention action failed with ${response.status}`));
  }
  return response.json();
}

module.exports = {
  DEFAULT_UPLOAD_USER_ID,
  applyDocumentRetentionAction,
  backendAuthHeaders,
  buildClientBootstrapPayload,
  buildClientOnboardingPackagePayload,
  buildDelegatedClientPortalUrl,
  buildNaceResearchRefreshPayload,
  buildTaxCertificateParseStatus,
  buildPortalUserBootstrapPayload,
  createDelegatedClientSession,
  createClientOnboardingPackage,
  createPortalInvite,
  createWorkspaceExportPackage,
  deleteClientDocuments,
  disableQnbConnection,
  ensureUploadWorkspace,
  fetchAuthSession,
  fetchQnbConnectionStatus,
  fetchQnbHealth,
  fetchQnbSyncPolicy,
  loginWithPassword,
  requestPasswordReset,
  confirmPasswordReset,
  parseDelegatedSessionHash,
  parseChartAccountsFromBackend,
  parseTaxCertificateFromBackend,
  previewDocumentRetention,
  previewReviewRule,
  pickUploadUser,
  requestStatementAiSuggestions,
  reopenJournal,
  reprocessClient,
  reprocessDocument,
  resetTestData,
  resolveApiBaseUrl,
  saveQnbConnectionToBackend,
  saveQnbSyncPolicy,
  sessionAuthErrorMessage,
  setPortalPassword,
  storeReviewDecision,
  acquireReviewEditLease,
  renewReviewEditLease,
  releaseReviewEditLease,
  saveReviewWorkingDraft,
  fetchLearningRules,
  changeLearningRuleLifecycle,
  syncQnbIncomingInvoices,
  updateClientPortalAccess,
  uploadChartAccountsToBackend,
  uploadDocumentToBackend,
  uploadDocumentsToBackend,
  uploadTaxCertificateToBackend,
};
