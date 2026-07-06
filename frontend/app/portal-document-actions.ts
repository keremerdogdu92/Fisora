import type { Dispatch, SetStateAction } from "react";
import { statementStatusLabel, statementReviewStatus, reviewActionLabel } from "./portal-formatters";
import { normalizeRulePrompt, normalizeStatementAiSuggestions, normalizeStatus, safeNumber, safeRecord } from "./portal-normalization";
import { applyStatementLineDecision } from "./portal-review-actions";
import type { CorrectionDraft, IntakeCategory, LocalSession, PilotClient, PilotData, PilotDocument, PilotStatus } from "./portal-types";
import { previousCompletedPeriod } from "./portal-periods";
import { buildUploadIntakeMetadata } from "./upload-intake";
import {
  ensureUploadWorkspace,
  pickUploadUser,
  requestStatementAiSuggestions,
  reprocessDocument,
  resolveApiBaseUrl,
  storeReviewDecision,
  uploadDocumentsToBackend,
} from "./upload-api";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export async function addLocalUploadsAction({
  files,
  localFallbackAllowed,
  refreshBackendPilotData,
  selectedClient,
  selectedIntakeCategory,
  session,
  setData,
  setSelectedPeriod,
  setUploadStatus,
}: {
  files: FileList | null;
  localFallbackAllowed: boolean;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  selectedIntakeCategory: IntakeCategory;
  session: LocalSession | null;
  setData: Dispatch<SetStateAction<PilotData>>;
  setSelectedPeriod: (period: string) => void;
  setUploadStatus: (status: string) => void;
}) {
  const selectedFiles = Array.from(files ?? []);
  if (!selectedFiles.length || !selectedClient) return;
  const now = new Date();
  // TODO: Bulunulan ay yüklemelerini açma.
  const period = previousCompletedPeriod(now);
  const intakeMetadata = buildUploadIntakeMetadata(selectedIntakeCategory);
  const nextDocuments = selectedFiles.map((file, index): PilotDocument => ({
    id: `local-upload-${now.getTime()}-${index}`,
    clientId: selectedClient.clientId,
    clientName: selectedClient.clientName,
    fileName: file.name,
    documentType: intakeMetadata.documentType,
    intakeCategory: intakeMetadata.intakeCategory as IntakeCategory,
    period,
    uploadedAt: now.toLocaleString("tr-TR"),
    uploadedBy: selectedClient.userLabel,
    status: normalizeStatus(intakeMetadata.status),
    originalDocumentRef: `local-upload-${now.getTime()}-${index}`,
    originalDocumentMimeType: file.type || "application/octet-stream",
    provider: intakeMetadata.provider,
    issueDate: "-",
    amount: "-",
    vatRates: [],
    productLine: intakeMetadata.productLine,
    productCategory: intakeMetadata.productCategory,
    businessRelation: "-",
    accountTreatment: "-",
    requiresAccountantReview: true,
    previewText: intakeMetadata.previewText,
    aiReason: intakeMetadata.aiReason,
    aiProvider: "-",
    aiSuggestedAccountCode: "",
    aiSuggestedCounterpartyCode: "",
    aiRiskFlags: [],
    aiAccountReason: "",
    deterministicSummary: intakeMetadata.deterministicSummary,
    exportGateReason: intakeMetadata.exportGateReason,
    draftStatus: "processing",
    chartAccounts: [],
    accountantSummary: "Belge alındı; fiş taslağı işleme kuyruğunda hazırlanacak.",
    accountantExplanation: "Belge henuz muhasebe gerekcesi uretmedi.",
    technicalDetails: {},
    pipelineEvents: [],
    accountingDirection: "",
    selectedExpenseAccount: "-",
    selectedVatAccount: "-",
    selectedCounterpartyAccount: "-",
    selectedRevenueAccount: "-",
    selectedPurchaseVatAccount: "-",
    selectedSalesVatAccount: "-",
    selectedCustomerAccount: "-",
    suggestedCounterpartyAccount: "-",
    counterpartyCreationSuggestion: {},
    accountCandidates: {
      purchaseStock: [],
      purchaseExpense: [],
      purchaseVat: [],
      salesRevenue: [],
      zeroVatRevenue: [],
      salesVat: [],
      customer: [],
      supplier: [],
    },
    counterpartyConfidence: 0,
    reviewReasons: intakeMetadata.intakeCategory === "special_document" ? ["manual_review_required"] : [],
    riskFlags: intakeMetadata.intakeCategory === "special_document" ? ["manual_review_required"] : [],
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
  }));
  if (localFallbackAllowed) {
    setData((current) => ({ ...current, documents: [...nextDocuments, ...current.documents] }));
    setSelectedPeriod(period);
  }
  setUploadStatus(`${selectedFiles.length} belge backend kuyruguna gonderiliyor.`);

  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const uploadUserId = pickUploadUser({ session, selectedClient });
  const uploadDisplayName = session?.delegatedBy || selectedClient.userLabel || uploadUserId;
  try {
    await ensureUploadWorkspace({
      apiBaseUrl,
      client: selectedClient,
      userId: uploadUserId,
      displayName: uploadDisplayName,
      sessionToken: session?.sessionToken,
    });
    const uploadResults = await uploadDocumentsToBackend({
      apiBaseUrl,
      clientId: selectedClient.clientId,
      userId: uploadUserId,
      uploadedBy: uploadDisplayName,
      documentType: intakeMetadata.documentType,
      intakeCategory: intakeMetadata.intakeCategory,
      period,
      sessionToken: session?.sessionToken,
      files: selectedFiles,
    });
    const failedUploads = uploadResults.filter((result) => !result.ok);
    setUploadStatus(
      failedUploads.length
        ? `${uploadResults.length - failedUploads.length}/${selectedFiles.length} belge yuklendi. Basarisiz: ${failedUploads.map((result) => result.fileName).join(", ")}`
        : `${selectedFiles.length} belge backend kuyruguna alindi.`,
    );
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setUploadStatus(
      localFallbackAllowed
        ? `Backend yukleme tamamlanamadi; belge lokal listede tutuldu. ${message}`
        : `Backend yukleme tamamlanamadi; serverda belge kaydedilmedi. ${message}`,
    );
  }
}

export async function requestStatementAiForSelectedDocumentAction({
  selectedDocument,
  session,
  setData,
  setStatementAiStatus,
}: {
  selectedDocument?: PilotDocument;
  session: LocalSession | null;
  setData: Dispatch<SetStateAction<PilotData>>;
  setStatementAiStatus: (status: string) => void;
}) {
  if (!selectedDocument || !selectedDocument.statementLines.length) {
    setStatementAiStatus("Seçili belgede banka satırı yok.");
    return;
  }
  setStatementAiStatus("AI ajan onerisi isteniyor.");
  try {
    const payload = await requestStatementAiSuggestions({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedDocument.clientId,
      lines: selectedDocument.statementLines,
      aiPolicy: { enabled: true, max_provider_calls: 3 },
      providerName: "openai",
      providerPayloads: [],
      sessionToken: session?.sessionToken,
    });
    const response = safeRecord(payload);
    const suggestions = normalizeStatementAiSuggestions(response.suggestions);
    const aiUsedCount = safeNumber(response.ai_used_count);
    const skippedCount = safeNumber(response.skipped_count);
    setData((current) => ({
      ...current,
      documents: current.documents.map((document) =>
        document.id === selectedDocument.id
          ? {
              ...document,
              statementAiSuggestions: suggestions.length ? suggestions : document.statementAiSuggestions,
              statementAiSummary: `${aiUsedCount} AI ajan onerisi / ${skippedCount} satir atlandi`,
            }
          : document,
      ),
    }));
    setStatementAiStatus(suggestions.length ? `${suggestions.length} AI ajan onerisi alindi.` : "Oneri motoru sonuc dondurmedi; mevcut oneriler korundu.");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatementAiStatus(`AI ajan onerisi alinamadi. ${message}`);
  }
}

export async function saveStatementLineDecisionAction({
  action,
  correctionDraft,
  localFallbackAllowed,
  loginUserId,
  refreshBackendPilotData,
  selectedDocument,
  selectedStatementLineNo,
  session,
  setData,
  setDecisionStatus,
}: {
  action: string;
  correctionDraft: CorrectionDraft;
  localFallbackAllowed: boolean;
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedDocument?: PilotDocument;
  selectedStatementLineNo: number;
  session: LocalSession | null;
  setData: Dispatch<SetStateAction<PilotData>>;
  setDecisionStatus: (status: string) => void;
}) {
  if (!selectedDocument) return;
  const lineNo = selectedStatementLineNo || selectedDocument.statementLines[0]?.line_no || 0;
  const selectedLine = selectedDocument.statementLines.find((line) => line.line_no === lineNo);
  if (!lineNo || !selectedLine) {
    setDecisionStatus("Banka satırı seçili değil.");
    return;
  }
  const correctedAccountCode = correctionDraft.accountCode.trim();
  const correctedCounterpartyCode = correctionDraft.counterpartyCode.trim();
  const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
  const reason = correctionDraft.reason.trim();
  const ruleInstruction = correctionDraft.ruleInstruction.trim();
  const applyToSimilar = Boolean(correctionDraft.applyToSimilar || action === "suggest_for_similar");
  setData((current) => ({
    ...current,
    documents: current.documents.map((document) =>
        document.id === selectedDocument.id
        ? applyStatementLineDecision(document, lineNo, action, correctedAccountCode, correctedCounterpartyCode, reviewer, reason)
        : document,
    ),
  }));
  const label = statementStatusLabel(statementReviewStatus(action));
  setDecisionStatus(`${selectedDocument.fileName} / ${lineNo}. satir: ${label} arayuzde uygulandi.`);
  try {
    await storeReviewDecision({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedDocument.clientId,
      userId: reviewer,
      documentRef: selectedDocument.id,
      action,
      reviewer,
      applyToSimilar,
      statementLineNo: lineNo,
      correctedAccountCode,
      correctedCounterpartyCode,
      category: selectedLine.transaction_type,
      reason,
      accountantNote: reason,
      ruleInstruction,
      sessionToken: session?.sessionToken,
    });
    setDecisionStatus(`${selectedDocument.fileName} / ${lineNo}. satir: ${label} backend'e kaydedildi.`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setDecisionStatus(
      localFallbackAllowed
        ? `${selectedDocument.fileName} / ${lineNo}. satir lokal uygulandi; backend kaydi tamamlanamadi. ${message}`
        : `${selectedDocument.fileName} / ${lineNo}. satir backend'e kaydedilemedi; serverda kalici karar olusmadi. ${message}`,
    );
  }
}

export async function saveDecisionAction({
  action,
  correctionDraft,
  localFallbackAllowed,
  loginUserId,
  refreshBackendPilotData,
  selectedDocument,
  session,
  setData,
  setDecisionStatus,
}: {
  action: string;
  correctionDraft: CorrectionDraft;
  localFallbackAllowed: boolean;
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedDocument?: PilotDocument;
  session: LocalSession | null;
  setData: Dispatch<SetStateAction<PilotData>>;
  setDecisionStatus: (status: string) => void;
}) {
  if (!selectedDocument) return;
  const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
  const correctedAccountCode = correctionDraft.accountCode.trim();
  const correctedCounterpartyCode = correctionDraft.counterpartyCode.trim();
  const reason = correctionDraft.reason.trim();
  const ruleInstruction = correctionDraft.ruleInstruction.trim();
  const manualDraftLines = correctionDraft.manualDraftLines.filter(
    (line) => line.account_code.trim() || line.description.trim() || line.debit.trim() || line.credit.trim(),
  );
  const applyToSimilar = Boolean(correctionDraft.applyToSimilar || action === "suggest_for_similar");
  const nextStatus: PilotStatus = action === "approve" || action === "approve_with_changes" || action === "suggest_for_similar" ? "export_ready" : "review_required";
  const label = reviewActionLabel(action);
  setData((current) => ({
    ...current,
    documents: current.documents.map((document) =>
      document.id === selectedDocument.id
        ? {
            ...document,
            status: nextStatus,
            selectedExpenseAccount: correctedAccountCode || document.selectedExpenseAccount,
            selectedCounterpartyAccount: correctedCounterpartyCode || document.selectedCounterpartyAccount,
            draftLines: manualDraftLines.length ? manualDraftLines : document.draftLines,
            draftStatus: manualDraftLines.length ? "manual_draft_completed" : document.draftStatus,
            exportGateReason:
              nextStatus === "export_ready"
                ? "Musavir onayi verildi; cikti listesine alinabilir."
                : "Musavir karari ciktiya almadi veya kontrolu surdurdu.",
          }
        : document,
    ),
  }));
  setDecisionStatus(`${selectedDocument.fileName}: ${label} arayuzde uygulandi.`);
  try {
    await storeReviewDecision({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedDocument.clientId,
      userId: reviewer,
      documentRef: selectedDocument.id,
      action,
      reviewer,
      applyToSimilar,
      correctedAccountCode,
      correctedCounterpartyCode,
      category: selectedDocument.productCategory,
      reason,
      accountantNote: reason,
      ruleInstruction,
      draftLines: manualDraftLines,
      sessionToken: session?.sessionToken,
    });
    setDecisionStatus(`${selectedDocument.fileName}: ${label} backend'e kaydedildi.`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setDecisionStatus(
      localFallbackAllowed
        ? `${selectedDocument.fileName}: ${label} lokal uygulandi; backend kaydi tamamlanamadi. ${message}`
        : `${selectedDocument.fileName}: ${label} backend'e kaydedilemedi; serverda kalici karar olusmadi. ${message}`,
    );
  }
}

export async function reprocessSelectedDocumentAction({
  loginUserId,
  refreshBackendPilotData,
  selectedDocument,
  session,
  setDecisionStatus,
}: {
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedDocument?: PilotDocument;
  session: LocalSession | null;
  setDecisionStatus: (status: string) => void;
}) {
  if (!selectedDocument) return;
  const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
  const documentRef = selectedDocument.originalDocumentRef || selectedDocument.id;
  setDecisionStatus(`${selectedDocument.fileName}: yeni motorla yeniden isleme aliniyor.`);
  try {
    await reprocessDocument({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedDocument.clientId,
      documentRef,
      userId: reviewer,
      sessionToken: session?.sessionToken,
    });
    setDecisionStatus(`${selectedDocument.fileName}: yeniden isleme kuyruguna alindi.`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setDecisionStatus(`${selectedDocument.fileName}: yeniden isleme baslatilamadi. ${message}`);
  }
}
