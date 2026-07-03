const REVIEW_STATUSES = new Set(["review_required"]);
const EXPORT_READY_STATUSES = new Set(["export_ready", "export_added"]);
const CANCEL_STATUSES = new Set(["cancel_requested", "post_export_correction_requested"]);
const IN_PROGRESS_STATUSES = new Set(["uploaded", "queued", "processing"]);
const INVOICE_INTAKES = new Set(["sales_invoice", "purchase_invoice"]);
const PROCESSING_DONE_STEPS = new Set(["journal_saved", "processing_completed", "accounting_draft_saved", "draft_ready"]);
const DECISION_DONE_STEPS = new Set(["review_decision", "export_package", "export_ready", "exported"]);
const EXPORT_DONE_STEPS = new Set(["export_package", "exported"]);

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

function dateValue(value) {
  const time = Date.parse(String(value || ""));
  return Number.isFinite(time) ? time : null;
}

function minutesBetween(start, end) {
  const startTime = dateValue(start);
  const endTime = dateValue(end);
  if (startTime === null || endTime === null || endTime < startTime) return null;
  return Math.round((endTime - startTime) / 60000);
}

function eventTime(document, steps) {
  return safeList(document?.pipelineEvents)
    .filter((event) => steps.has(String(event?.step || "")) && event?.createdAt)
    .map((event) => String(event.createdAt))
    .sort()
    .at(-1) || "";
}

function average(values) {
  const usable = safeList(values).filter((value) => Number.isFinite(value));
  if (!usable.length) return null;
  return Math.round(usable.reduce((total, value) => total + value, 0) / usable.length);
}

function durationLabel(minutes) {
  if (!Number.isFinite(minutes)) return "ölçülemiyor";
  if (minutes < 60) return `${minutes} dk`;
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  return remaining ? `${hours} sa ${remaining} dk` : `${hours} sa`;
}

function buildDashboardDurationMetrics({ documents = [] } = {}) {
  const rows = safeList(documents);
  const processingMinutes = rows.map((document) => minutesBetween(document?.uploadedAt, eventTime(document, PROCESSING_DONE_STEPS)));
  const decisionMinutes = rows.map((document) => minutesBetween(document?.uploadedAt, eventTime(document, DECISION_DONE_STEPS)));
  const exportMinutes = rows.map((document) => minutesBetween(document?.uploadedAt, eventTime(document, EXPORT_DONE_STEPS)));
  const averageDocumentMinutes = average(processingMinutes);
  const uploadToDecisionMinutes = average(decisionMinutes);
  const clientAverageCompletionMinutes = average(exportMinutes);

  return {
    averageDocumentMinutes,
    uploadToDecisionMinutes,
    clientAverageCompletionMinutes,
    averageDocumentTimeLabel: durationLabel(averageDocumentMinutes),
    uploadToDecisionTimeLabel: durationLabel(uploadToDecisionMinutes),
    clientAverageCompletionTimeLabel: durationLabel(clientAverageCompletionMinutes),
  };
}

function safeScorecardDelta(document) {
  const scorecard = document?.aiQualityScorecard;
  const delta = scorecard && typeof scorecard === "object" && !Array.isArray(scorecard)
    ? scorecard.quality_delta
    : null;
  return delta && typeof delta === "object" && !Array.isArray(delta) ? delta : {};
}

function unchangedApprovalStats(documents) {
  const scored = safeList(documents).filter((document) => {
    const decision = String(safeScorecardDelta(document).decision || "");
    return decision === "accepted" || decision === "changed";
  });
  const unchanged = scored.filter((document) => String(safeScorecardDelta(document).decision || "") === "accepted").length;
  const rate = scored.length ? Math.round((unchanged / scored.length) * 100) : null;
  return { rate, correctionCount: Math.max(scored.length - unchanged, 0) };
}

function capacityForKind(aiCapacity, kind) {
  const agent = safeList(aiCapacity?.agents).find((row) => String(row?.kind || "") === kind);
  const remaining = agent?.remaining ?? agent?.window?.remaining ?? agent?.daily?.remaining ?? null;
  if (remaining === null || remaining === undefined || remaining === "") return "ölçülemiyor";
  return `${remaining} kaldı`;
}

function learningSignalLabel(documents) {
  const rows = safeList(documents);
  const ruleCandidates = rows.filter((document) => document?.rulePrompt?.show || document?.learningRuleSourceSummary).length;
  if (ruleCandidates >= 2) return "Kural adayı oluştu";
  if (ruleCandidates === 1 || rows.some((document) => document?.aiResearchRequested)) return "Öğrenme sinyali kaydedildi";
  return "Sinyal yok";
}

function rulePromptFor(document) {
  const prompt = document?.rulePrompt;
  return prompt && typeof prompt === "object" && !Array.isArray(prompt) ? prompt : {};
}

function learningEvidenceText(document) {
  const prompt = rulePromptFor(document);
  return String(
    prompt.message
    || document?.learningRuleSourceSummary
    || document?.learningRuleReason
    || document?.accountantExplanation
    || "Müşavir kararı eğitim notu olarak saklandı.",
  );
}

function documentLabel(document) {
  return [document?.clientName, document?.fileName].filter(Boolean).join(" / ") || document?.id || "Belge";
}

function pushLearningInsight(insights, document, stageLabel, summary, confidenceLabel) {
  insights.push({
    id: `${stageLabel}-${document?.id || insights.length}`,
    documentLabel: documentLabel(document),
    stageLabel,
    summary,
    confidenceLabel,
  });
}

function buildAgentLearningInsights({ documents = [], limit = 6 } = {}) {
  const rows = safeList(documents).filter((document) => {
    const prompt = rulePromptFor(document);
    return Boolean(
      document?.learningRuleReason
      || document?.learningRuleSourceSummary
      || prompt.show
      || prompt.clientConsistentDecisionCount
      || prompt.officeConsistentDecisionCount
      || prompt.officeDistinctClientCount
    );
  });
  if (!rows.length) return [];
  const insights = [];
  pushLearningInsight(insights, rows[0], "Öğrenme sinyali kaydedildi", learningEvidenceText(rows[0]), "eğitim notu");
  rows.forEach((document) => {
    const prompt = rulePromptFor(document);
    const clientCount = Number(prompt.clientConsistentDecisionCount || 0);
    const officeCount = Number(prompt.officeConsistentDecisionCount || 0);
    const distinctClientCount = Number(prompt.officeDistinctClientCount || 0);
    if (prompt.show || document?.learningRuleSourceSummary) {
      pushLearningInsight(insights, document, "Kural adayı oluştu", learningEvidenceText(document), document?.learningRuleScope || "mükellef kuralı");
    }
    if (clientCount > 0) {
      pushLearningInsight(insights, document, `${Math.min(clientCount, 3)}/3 tutarlı onay`, learningEvidenceText(document), "müşavir onayı bekliyor");
    }
    if (clientCount >= 3 || (distinctClientCount >= 2 && officeCount >= 3)) {
      pushLearningInsight(insights, document, "Kontrollü otomasyon adayı", learningEvidenceText(document), `${Math.max(distinctClientCount, 1)} mükellef / ${Math.max(officeCount, clientCount)} onay`);
    }
  });
  return insights.slice(0, limit);
}

function buildAgentSummaries({ documents = [], aiCapacity = null } = {}) {
  const rows = safeList(documents);
  const stats = unchangedApprovalStats(rows);
  const touchedDocuments = rows.filter((document) => document?.draftLines?.length || document?.pipelineEvents?.length || document?.status).length;
  const accountTouches = rows.filter((document) => document?.selectedExpenseAccount || document?.selectedRevenueAccount || document?.draftLines?.length).length;
  const counterpartyTouches = rows.filter((document) => document?.selectedCounterpartyAccount || document?.selectedCustomerAccount || document?.suggestedCounterpartyAccount).length;
  const researchTouches = rows.filter((document) => document?.aiResearchRequested || document?.aiResearchQuery).length;
  const unchangedApprovalRateLabel = stats.rate === null
    ? "Müşavirce değişmeden onaylandı ölçülemiyor"
    : `Müşavirce değişmeden onaylandı %${stats.rate}`;

  return [
    {
      key: "document",
      name: "Belge ajanı",
      statusLabel: touchedDocuments ? "Çalışıyor" : "Veri bekliyor",
      touchedCount: touchedDocuments,
      capacityLabel: capacityForKind(aiCapacity, "document"),
      unchangedApprovalRateLabel,
      correctionCount: stats.correctionCount,
      learningLabel: learningSignalLabel(rows),
    },
    {
      key: "account",
      name: "Hesap ajanı",
      statusLabel: accountTouches ? "Fiş taslağı üretiyor" : "Veri bekliyor",
      touchedCount: accountTouches,
      capacityLabel: capacityForKind(aiCapacity, "document"),
      unchangedApprovalRateLabel,
      correctionCount: stats.correctionCount,
      learningLabel: learningSignalLabel(rows),
    },
    {
      key: "counterparty",
      name: "Cari ajanı",
      statusLabel: counterpartyTouches ? "Cari eşleştiriyor" : "Veri bekliyor",
      touchedCount: counterpartyTouches,
      capacityLabel: capacityForKind(aiCapacity, "document"),
      unchangedApprovalRateLabel,
      correctionCount: stats.correctionCount,
      learningLabel: learningSignalLabel(rows),
    },
    {
      key: "research",
      name: "Araştırma ajanı",
      statusLabel: researchTouches ? "Gerektiğinde araştırıyor" : "Beklemede",
      touchedCount: researchTouches,
      capacityLabel: capacityForKind(aiCapacity, "research"),
      unchangedApprovalRateLabel,
      correctionCount: stats.correctionCount,
      learningLabel: learningSignalLabel(rows.filter((document) => document?.aiResearchRequested || document?.aiResearchQuery)),
    },
  ];
}

function priorityWorkItems({ clients = [], documents = [], cancellationRequests = [], limit = 8 } = {}) {
  const clientNames = new Map(safeList(clients).map((client) => [String(client?.clientId || ""), client?.clientName || "Mükellef"]));
  const requestItems = openRequests(cancellationRequests)
    .sort((a, b) => String(b?.requestedAt || "").localeCompare(String(a?.requestedAt || "")))
    .map((request) => ({
      id: `request-${request?.id || request?.documentId}`,
      kind: "request",
      label: clientNames.get(String(request?.clientId || "")) || "Mükellef",
      title: request?.fileName || "İptal/düzeltme talebi",
      detail: request?.reason || "Açık müşavir talebi var",
      statusLabel: "Talep var",
    }));
  const documentItems = safeList(documents)
    .filter((document) => REVIEW_STATUSES.has(document?.status) || IN_PROGRESS_STATUSES.has(document?.status))
    .sort((a, b) => {
      const statusWeight = (document) => REVIEW_STATUSES.has(document?.status) ? 2 : 1;
      const weightDiff = statusWeight(b) - statusWeight(a);
      if (weightDiff) return weightDiff;
      return String(b?.uploadedAt || "").localeCompare(String(a?.uploadedAt || ""));
    })
    .map((document) => ({
      id: `document-${document?.id}`,
      kind: "document",
      label: document?.clientName || clientNames.get(String(document?.clientId || "")) || "Mükellef",
      title: document?.fileName || "Belge",
      detail: `${document?.fileName || "Belge"} - ${
        safeList(document?.reviewReasons).length
          ? safeList(document.reviewReasons).slice(0, 2).join(", ")
          : REVIEW_STATUSES.has(document?.status)
            ? "Müşavir kararı bekliyor"
            : "İşleme kuyruğunda"
      }`,
      statusLabel: REVIEW_STATUSES.has(document?.status) ? "Kontrol" : "İşleniyor",
    }));

  return [...requestItems, ...documentItems].slice(0, limit);
}

function buildPortalDashboardViewModels({ data = {}, aiCapacity = null } = {}) {
  const safeData = {
    clients: safeList(data.clients),
    documents: safeList(data.documents),
    cancellationRequests: safeList(data.cancellationRequests),
  };
  return {
    dashboardMetrics: buildPortalDashboard(safeData),
    dashboardClientRows: clientDashboardRows(safeData),
    intakeDistribution: documentIntakeDistribution(safeData.documents),
    funnelRows: statusFunnel(safeData.documents),
    uploadTrackingRows: clientUploadTracking(safeData),
    agentSummaries: buildAgentSummaries({ documents: safeData.documents, aiCapacity }),
    learningInsights: buildAgentLearningInsights({ documents: safeData.documents }),
    durationMetrics: buildDashboardDurationMetrics({ documents: safeData.documents }),
    priorityItems: priorityWorkItems({ ...safeData, limit: 8 }),
  };
}

module.exports = {
  buildAgentLearningInsights,
  buildAgentSummaries,
  buildClientCancellationViewModel,
  buildDashboardDurationMetrics,
  buildPortalDashboard,
  buildPortalDashboardViewModels,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
  priorityWorkItems,
  statusFunnel,
};
