const DEFAULT_BACKEND_PORT = "8000";
const DEFAULT_UPLOAD_USER_ID = "pilot-mukellef-user";

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
  const clientId = String(client?.clientId || "private-pilot-client").trim();
  const clientName = String(client?.clientName || clientId || "Private Pilot Client").trim();
  const taxId = String(client?.taxId || "").trim();
  return {
    client_id: clientId,
    title: clientName,
    tax_id: taxId === "pilot-local" ? "" : taxId,
    has_chart_accounts: true,
  };
}

function buildPortalUserBootstrapPayload({ userId, displayName, clientId }) {
  const normalizedUserId = String(userId || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
  const normalizedClientId = String(clientId || "private-pilot-client").trim();
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
  activityDescription = "",
  naceCode = "",
  workplaceAddresses,
  portalUserId = "",
  portalDisplayName = "",
} = {}) {
  const normalizedTitle = String(title || "").trim();
  const normalizedClientId = String(clientId || slugifyClientId(normalizedTitle) || "yeni-mukellef").trim();
  const normalizedPortalUserId = String(portalUserId || `${normalizedClientId}-user`).trim();
  return {
    client: {
      client_id: normalizedClientId,
      title: normalizedTitle || normalizedClientId,
      tax_id: String(taxId || "").trim(),
      activity_description: String(activityDescription || "").trim(),
      nace_code: String(naceCode || "").trim(),
      workplace_addresses: Array.isArray(workplaceAddresses) ? workplaceAddresses.map(String).map((value) => value.trim()).filter(Boolean) : [],
      has_chart_accounts: true,
    },
    chart_accounts: [],
    portal_users: [
      {
        user_id: normalizedPortalUserId,
        display_name: String(portalDisplayName || normalizedTitle || normalizedPortalUserId).trim(),
        role: "client_user",
        allowed_client_ids: [normalizedClientId],
      },
    ],
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

async function createClientOnboardingPackage({
  apiBaseUrl,
  client,
  sessionToken = "",
  userId = "",
  fetchImpl = fetch,
}) {
  const headers = sessionToken
    ? { "X-Fisora-Session": String(sessionToken) }
    : userId
      ? { "X-Fisora-User-Id": String(userId) }
      : {};
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
  displayName = "",
  clientId,
  invitedBy = "",
  ttlHours = 48,
  sessionToken = "",
  userHeader = "",
  fetchImpl = fetch,
}) {
  const headers = sessionToken
    ? { "X-Fisora-Session": String(sessionToken) }
    : userHeader
      ? { "X-Fisora-User-Id": String(userHeader) }
      : {};
  return postJson({
    apiBaseUrl,
    path: "/phase0/store/auth/invite",
    payload: {
      user_id: String(userId || "").trim(),
      display_name: String(displayName || userId || "").trim(),
      role: "client_user",
      allowed_client_ids: [String(clientId || "").trim()].filter(Boolean),
      invited_by: String(invitedBy || "").trim(),
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
  const headers = sessionToken
    ? { "X-Fisora-Session": String(sessionToken) }
    : userHeader
      ? { "X-Fisora-User-Id": String(userHeader) }
      : {};
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

async function uploadChartAccountsToBackend({
  apiBaseUrl,
  clientId,
  userId = "",
  sessionToken = "",
  file,
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  const formData = new FormDataCtor();
  formData.append("client_id", String(clientId || ""));
  formData.append("file", file);

  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/chart-accounts/upload`, {
    method: "POST",
    headers: sessionToken ? { "X-Fisora-Session": String(sessionToken) } : userId ? { "X-Fisora-User-Id": String(userId) } : {},
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
  formData.append("uploaded_by", String(uploadedBy || normalizedUserId));
  formData.append("uploaded_by_user_id", normalizedUserId);
  formData.append("retention_policy_days", String(retentionPolicyDays));
  formData.append("file", file);

  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/document-upload-multipart`, {
    method: "POST",
    headers: sessionToken ? { "X-Fisora-Session": String(sessionToken) } : { "X-Fisora-User-Id": normalizedUserId },
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
  fetchImpl = fetch,
  FormDataCtor = FormData,
}) {
  return uploadDocumentToBackend({
    apiBaseUrl,
    clientId,
    userId,
    uploadedBy,
    documentType: "special_document",
    intakeCategory: "special_document",
    file,
    retentionPolicyDays,
    sessionToken,
    fetchImpl,
    FormDataCtor,
  });
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
  applyToSimilar = false,
  priorConsistentApprovalCount = 0,
  statementLineNo = 0,
  sessionToken = "",
  fetchImpl = fetch,
}) {
  const normalizedUserId = String(userId || reviewer || DEFAULT_UPLOAD_USER_ID).trim() || DEFAULT_UPLOAD_USER_ID;
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
      apply_to_similar: Boolean(applyToSimilar),
      prior_consistent_approval_count: Number(priorConsistentApprovalCount || 0),
      statement_line_no: Number(statementLineNo || 0),
    },
  };
  const response = await fetchImpl(`${trimSlashes(apiBaseUrl)}/phase0/store/review-decision`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(sessionToken ? { "X-Fisora-Session": String(sessionToken) } : { "X-Fisora-User-Id": normalizedUserId }),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, `review decision failed with ${response.status}`));
  }
  return response.json();
}

module.exports = {
  DEFAULT_UPLOAD_USER_ID,
  buildClientBootstrapPayload,
  buildClientOnboardingPackagePayload,
  buildPortalUserBootstrapPayload,
  createClientOnboardingPackage,
  createPortalInvite,
  ensureUploadWorkspace,
  loginWithPassword,
  parseTaxCertificateFromBackend,
  pickUploadUser,
  requestStatementAiSuggestions,
  resolveApiBaseUrl,
  setPortalPassword,
  storeReviewDecision,
  uploadChartAccountsToBackend,
  uploadDocumentToBackend,
  uploadTaxCertificateToBackend,
};
