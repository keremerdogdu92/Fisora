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

function processingSegmentForDocument(document) {
  const intakeCategory = String(document?.intakeCategory || document?.intake_category || "");
  const accountingDirection = String(document?.accountingDirection || document?.accounting_direction || "");
  const directionConflictStatus = String(document?.directionConflict?.status || document?.direction_conflict?.status || "");
  if (directionConflictStatus === "needs_review") {
    if (intakeCategory === "sales_invoice") return "sales_invoices";
    if (intakeCategory === "purchase_invoice") return "purchase_invoices";
  }
  if (accountingDirection === "sales" || intakeCategory === "sales_invoice") return "sales_invoices";
  if (accountingDirection === "purchase" || intakeCategory === "purchase_invoice") return "purchase_invoices";
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
    { key: "other_documents", label: "Diğer belgeler", count: counts.other_documents },
  ];
}

function statusFunnel(documents = []) {
  const rows = safeList(documents);
  return [
    { key: "uploaded", label: "Yüklendi", count: rows.filter((document) => IN_PROGRESS_STATUSES.has(document?.status)).length },
    { key: "review", label: "Kontrol bekliyor", count: rows.filter((document) => REVIEW_STATUSES.has(document?.status)).length },
    { key: "export", label: "Çıktı hazır", count: rows.filter((document) => EXPORT_READY_STATUSES.has(document?.status)).length },
  ];
}

function clientUploadTracking({ clients = [], documents = [] } = {}) {
  const normalizedClients = safeList(clients);
  const uploadedClientIds = new Set(safeList(documents).map((document) => String(document?.clientId || "")).filter(Boolean));
  const uploadedCount = normalizedClients.filter((client) => uploadedClientIds.has(String(client?.clientId || ""))).length;
  return [
    { key: "uploaded", label: "Yükleyen", count: uploadedCount },
    { key: "missing", label: "Yüklemeyen", count: Math.max(normalizedClients.length - uploadedCount, 0) },
  ];
}

function documentsForProcessing({ documents = [], clientId = "", segment = "invoices" } = {}) {
  return safeList(documents).filter((document) => {
    const matchesClient = String(document?.clientId || "") === String(clientId || "");
    if (!matchesClient) return false;
    if (segment === "invoice_review") return intakeSegmentForDocument(document) === "invoice_review";
    const processingSegment = processingSegmentForDocument(document);
    if (segment === "invoices") {
      return processingSegment === "sales_invoices"
        || processingSegment === "purchase_invoices"
        || processingSegment === "invoices";
    }
    return processingSegment === segment;
  });
}

function buildClientCancellationViewModel({
  documents = [],
  selectedDocumentId = "",
  requestDocumentId = "",
  cancellationReason = "",
} = {}) {
  const rows = safeList(documents);
  const selectedDocument = rows.find((document) => String(document?.id || "") === String(selectedDocumentId || "")) || null;
  const requestDocument = rows.find((document) => String(document?.id || "") === String(requestDocumentId || "")) || null;
  const requestReason = String(cancellationReason || "").trim();

  return {
    selectedDocument,
    requestDocument,
    requestReason,
    canSubmitCancellation: Boolean(requestDocument),
    emptyActionText: selectedDocument ? "Talep açmak için belge önizlemesini veya liste aksiyonunu kullanın." : "Önce belge seçin.",
  };
}

module.exports = {
  buildClientCancellationViewModel,
  buildPortalDashboard,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
  statusFunnel,
};
