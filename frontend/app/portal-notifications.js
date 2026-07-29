const TURKISH_MONTHS = [
  "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
  "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
];

function text(value) {
  return String(value ?? "").trim();
}

function periodLabel(period) {
  const match = text(period).match(/^(\d{4})-(0[1-9]|1[0-2])$/);
  return match ? `${TURKISH_MONTHS[Number(match[2]) - 1]} ${match[1]}` : text(period) || "Dönem";
}

function buildNotificationViewModel(raw = {}) {
  const status = text(raw.status || "pending") || "pending";
  const readAt = text(raw.read_at || raw.readAt);
  const count = Number(raw.document_count ?? raw.documentCount ?? 0) || 0;
  const period = text(raw.accounting_period || raw.accountingPeriod);
  const deleteOn = text(raw.delete_on || raw.deleteOn);
  return {
    notificationId: text(raw.notification_id || raw.notificationId),
    kind: text(raw.kind) || "retention",
    severity: text(raw.severity) || "warning",
    status,
    title: text(raw.title) || `${periodLabel(period)} belgeleri ay sonunda silinecek`,
    message: text(raw.message) || `${count} kaynak belge ${deleteOn} tarihinde silinecek.`,
    clientId: text(raw.client_id || raw.clientId),
    accountingPeriod: period,
    deleteOn,
    documentCount: count,
    badgeLabel: `${count} belge`,
    readAt,
    read: Boolean(readAt),
    pending: status === "pending" || status === "warning_open" || status === "deleting",
    createdAt: text(raw.created_at || raw.createdAt),
  };
}

function pendingNotificationCount(items = []) {
  return items.filter((item) => item?.pending).length;
}

function backendAuthHeaders({ sessionToken = "", userId = "" } = {}) {
  const headers = {};
  if (text(sessionToken)) headers["X-Fisora-Session"] = text(sessionToken);
  if (text(userId)) headers["X-Fisora-User-Id"] = text(userId);
  return headers;
}

async function responseErrorMessage(response) {
  try {
    const payload = await response.json();
    return typeof payload?.detail === "string" ? payload.detail : JSON.stringify(payload);
  } catch {
    return `notifications request failed with ${response.status}`;
  }
}

async function fetchPortalNotifications({ apiBaseUrl, sessionToken = "", userId = "", fetchImpl = fetch } = {}) {
  const response = await fetchImpl(`${String(apiBaseUrl || "").replace(/\/+$/, "")}/phase0/store/notifications`, {
    headers: backendAuthHeaders({ sessionToken, userId }),
  });
  if (!response.ok) throw new Error(await responseErrorMessage(response));
  const payload = await response.json();
  return (Array.isArray(payload?.items) ? payload.items : []).map(buildNotificationViewModel);
}

async function markPortalNotificationRead({ apiBaseUrl, notificationId, sessionToken = "", userId = "", fetchImpl = fetch } = {}) {
  const response = await fetchImpl(
    `${String(apiBaseUrl || "").replace(/\/+$/, "")}/phase0/store/notifications/${encodeURIComponent(notificationId)}/read`,
    { method: "POST", headers: backendAuthHeaders({ sessionToken, userId }) },
  );
  if (!response.ok) throw new Error(await responseErrorMessage(response));
  return response.json();
}

module.exports = {
  buildNotificationViewModel,
  fetchPortalNotifications,
  markPortalNotificationRead,
  pendingNotificationCount,
};
