const REVIEW_STATUSES = new Set(["review_required"]);
const EXPORT_READY_STATUSES = new Set(["export_ready", "export_added"]);
const CANCEL_STATUSES = new Set(["cancel_requested", "post_export_correction_requested"]);
const IN_PROGRESS_STATUSES = new Set(["uploaded", "queued", "processing"]);
const INVOICE_INTAKES = new Set(["sales_invoice", "purchase_invoice"]);

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

function clientDocuments(documents, clientId) {
  return safeList(documents).filter((document) => String(document?.clientId || "") === String(clientId || ""));
}

function openRequests(cancellationRequests) {
  return safeList(cancellationRequests).filter((request) => request?.status === "open");
}

function buildPortalDashboard({ clients = [], documents = [], cancellationRequests = [] } = {}) {
  const normalizedClients = safeList(clients);
  const normalizedDocuments = safeList(documents);
  const openCancellationRequests = openRequests(cancellationRequests);
  const clientsWithUploads = normalizedClients.filter((client) => clientDocuments(normalizedDocuments, client.clientId).length > 0);

  return {
    totalClients: normalizedClients.length,
    uploadedClients: clientsWithUploads.length,
    notUploadedClients: Math.max(normalizedClients.length - clientsWithUploads.length, 0),
    pendingReviewDocuments: normalizedDocuments.filter((document) => REVIEW_STATUSES.has(document?.status)).length,
    exportReadyDocuments: normalizedDocuments.filter((document) => EXPORT_READY_STATUSES.has(document?.status)).length,
    openCancellationRequests: openCancellationRequests.length,
  };
}

function latestUploadedAt(documents) {
  return safeList(documents)
    .map((document) => String(document?.uploadedAt || ""))
    .filter(Boolean)
    .sort()
    .at(-1) || "";
}

function clientDashboardRows({ clients = [], documents = [], cancellationRequests = [] } = {}) {
  const openCancellationRequests = openRequests(cancellationRequests);
  return safeList(clients).map((client) => {
    const rows = clientDocuments(documents, client?.clientId);
    const pendingReviewCount = rows.filter((document) => REVIEW_STATUSES.has(document?.status)).length;
    const exportReadyCount = rows.filter((document) => EXPORT_READY_STATUSES.has(document?.status)).length;
    const inProgressCount = rows.filter((document) => IN_PROGRESS_STATUSES.has(document?.status)).length;
    const cancellationCount = openCancellationRequests.filter((request) => request?.clientId === client?.clientId).length;
    const status = cancellationCount
      ? "Talep var"
      : pendingReviewCount
        ? "Kontrol bekliyor"
        : !rows.length
          ? "Yükleme yok"
          : inProgressCount
            ? "İşleniyor"
            : exportReadyCount
              ? "Çıktı hazır"
              : "Takipte";

    return {
      clientId: client?.clientId || "",
      clientName: client?.clientName || "",
      taxId: client?.taxId || "",
      documentCount: rows.length,
      pendingReviewCount,
      exportReadyCount,
      inProgressCount,
      cancellationCount,
      lastUploadedAt: latestUploadedAt(rows),
      status,
    };
  });
}

function intakeSegmentForDocument(document) {
  const intakeCategory = String(document?.intakeCategory || document?.intake_category || "");
  if (INTAKE_INVOICE_ALIASES.has(intakeCategory) || INVOICE_INTAKES.has(intakeCategory)) return "invoices";
  if (intakeCategory === "bank_statement" || String(document?.documentType || "") === "bank_statement") return "bank_statements";
  return "other_documents";
}

const INTAKE_INVOICE_ALIASES = new Set(["invoice", "einvoice_xml"]);

function countDocumentsBySegment(documents) {
  return safeList(documents).reduce(
    (counts, document) => {
      counts[intakeSegmentForDocument(document)] += 1;
      return counts;
    },
    { invoices: 0, bank_statements: 0, other_documents: 0 },
  );
}

function documentIntakeDistribution(documents = []) {
  const counts = countDocumentsBySegment(documents);
  return [
    { key: "invoices", label: "Faturalar", count: counts.invoices },
    { key: "bank_statements", label: "Banka ekstreleri", count: counts.bank_statements },
    { key: "other_documents", label: "Diger belgeler", count: counts.other_documents },
  ];
}

function statusFunnel(documents = []) {
  const rows = safeList(documents);
  return [
    { key: "uploaded", label: "Yuklendi", count: rows.filter((document) => IN_PROGRESS_STATUSES.has(document?.status)).length },
    { key: "review", label: "Kontrol bekliyor", count: rows.filter((document) => REVIEW_STATUSES.has(document?.status)).length },
    { key: "export", label: "Cikti hazir", count: rows.filter((document) => EXPORT_READY_STATUSES.has(document?.status)).length },
  ];
}

function clientUploadTracking({ clients = [], documents = [] } = {}) {
  const normalizedClients = safeList(clients);
  const uploadedClientIds = new Set(safeList(documents).map((document) => String(document?.clientId || "")).filter(Boolean));
  const uploadedCount = normalizedClients.filter((client) => uploadedClientIds.has(String(client?.clientId || ""))).length;
  return [
    { key: "uploaded", label: "Yukleyen", count: uploadedCount },
    { key: "missing", label: "Yuklemeyen", count: Math.max(normalizedClients.length - uploadedCount, 0) },
  ];
}

function documentsForProcessing({ documents = [], clientId = "", segment = "invoices" } = {}) {
  return safeList(documents).filter((document) => {
    const matchesClient = String(document?.clientId || "") === String(clientId || "");
    return matchesClient && intakeSegmentForDocument(document) === segment;
  });
}

module.exports = {
  buildPortalDashboard,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
  statusFunnel,
};
