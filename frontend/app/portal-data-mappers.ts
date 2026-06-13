import type {
  CancellationRequest,
  ExportBasketItem,
  PilotClient,
  PilotData,
  PilotDocument,
  ReviewData,
} from "./portal-types";
import { inferIntakeCategory, toIntakeCategory } from "./portal-formatters";
import {
  normalizeRulePrompt,
  normalizeStatementAiSuggestions,
  normalizeStatementEntries,
  normalizeStatementLines,
  normalizeStatus,
  periodFromDate,
  safeNumber,
  safeText,
} from "./portal-normalization";

export const emptyPilotData: PilotData = {
  generatedFrom: "Ã‡alÄ±ÅŸma alanÄ± yÃ¼kleniyor",
  clients: [],
  documents: [],
  cancellationRequests: [],
  exportBasket: [],
};

function normalizeReviewData(raw: ReviewData): PilotData {
  const clientId = safeText(raw.clientId, "ofis-calisma-client");
  const clientName = safeText(raw.clientName, "Ofis MÃ¼kellefi");
  const clientUser = raw.portalUsers?.find((user) => user.role === "client_user") ?? raw.portalUsers?.[0];
  const documentsFromRows = (raw.invoiceRows ?? []).map((row, index): PilotDocument => {
    const fileName = safeText(row.documentRef || row.fileName, `ofis-belge-${index + 1}.pdf`);
    const status = normalizeStatus(row.exportStatus || row.status);
    return {
      id: safeText(row.documentRef || row.fileName, `${clientId}-doc-${index + 1}`),
      clientId,
      clientName,
      fileName,
      documentType: safeText(row.invoiceType, "invoice"),
      intakeCategory: toIntakeCategory(row.intakeCategory || inferIntakeCategory("invoice", row.invoiceType)),
      period: periodFromDate(safeText(row.issueDate), "2026-04"),
      uploadedAt: safeText(row.issueDate, "01.04.2026"),
      uploadedBy: safeText(clientUser?.displayName, clientName),
      status,
      provider: safeText(row.providerHint, "TedarikÃ§i bilinmiyor"),
      issueDate: safeText(row.issueDate, "-"),
      amount: safeText(row.payableTotal, "-"),
      vatRates: Array.isArray(row.vatRates) ? row.vatRates.map(String) : [],
      productLine: safeText(row.productLineHint, "-"),
      productCategory: safeText(row.productCategory, "-"),
      businessRelation: safeText(row.businessRelevanceRelation, "-"),
      accountTreatment: safeText(row.businessRelevanceAccountTreatment, "-"),
      requiresAccountantReview: Boolean(row.businessRelevanceRequiresReview),
      previewText: [
        safeText(row.providerHint, "TedarikÃ§i bilinmiyor"),
        safeText(row.productLineHint, "Belge kalemi okunuyor"),
        safeText(row.payableTotal, "-"),
      ].join(" / "),
      aiReason:
        safeText(row.aiClassificationReason) ||
        safeText(row.businessRelevanceReason) ||
        safeText(row.aiClassificationSkippedReason, "Ã–neri gerekÃ§esi yok"),
      aiProvider: safeText(row.aiClassificationProvider, "-"),
      aiSuggestedAccountCode: safeText(row.aiSuggestedAccountCode, ""),
      aiSuggestedCounterpartyCode: safeText(row.aiSuggestedCounterpartyCode, ""),
      aiRiskFlags: Array.isArray(row.aiRiskFlags) ? row.aiRiskFlags.map(String) : [],
      aiAccountReason: safeText(row.aiAccountReason, ""),
      deterministicSummary: (row.deterministicChecks ?? []).join(", ") || (row.isBalanced ? "balanced_entry" : "denge kontrolÃ¼ gerekli"),
      exportGateReason: safeText(row.exportGateReason, status === "export_ready" ? "Ã‡Ä±ktÄ± listesine alÄ±nabilir." : "MÃ¼ÅŸavir kontrolÃ¼ gerekiyor."),
      selectedExpenseAccount: safeText(row.selectedExpenseAccount, "-"),
      selectedVatAccount: safeText(row.selectedVatAccount, "-"),
      selectedCounterpartyAccount: safeText(row.selectedSupplierAccount || row.counterpartyMatchCode, "-"),
      counterpartyConfidence: Number(row.counterpartyMatchConfidence ?? 0),
      reviewReasons: Array.isArray(row.reviewReasonCodes) ? row.reviewReasonCodes.map(String) : [],
      riskFlags: Array.isArray(row.riskFlags) ? row.riskFlags.map(String) : [],
      draftLines: Array.isArray(row.draftLines) ? row.draftLines : [],
      statementLines: normalizeStatementLines(row.statementLines ?? row.statement_lines),
      statementEntries: normalizeStatementEntries(row.statementEntries ?? row.statement_entries),
      statementAiSuggestions: normalizeStatementAiSuggestions(row.statementAiSuggestions ?? row.statement_ai_suggestions),
      statementAiSummary: safeText(row.statementAiSummary ?? row.statement_ai_summary),
      accountingIntent: safeText(row.accountingIntent ?? row.accounting_intent),
      accountingIntentConfidence: safeNumber(row.accountingIntentConfidence ?? row.accounting_intent_confidence),
      learningRuleScope: safeText(row.learningRuleScope ?? row.learning_rule_scope),
      learningRuleReason: safeText(row.learningRuleReason ?? row.learning_rule_reason),
      learningRuleSourceSummary: safeText(row.learningRuleSourceSummary ?? row.learning_rule_source_summary),
      rulePrompt: normalizeRulePrompt(row.rulePrompt ?? row.rule_prompt),
    };
  });

  const rowFileNames = new Set(documentsFromRows.map((document) => document.fileName));
  const uploadOnlyDocuments = (raw.uploadQueue ?? [])
    .filter((item) => !rowFileNames.has(safeText(item.fileName)))
    .map((item, index): PilotDocument => ({
      id: safeText(item.id, `${clientId}-upload-${index + 1}`),
      clientId,
      clientName,
      fileName: safeText(item.fileName, `yuklenen-belge-${index + 1}`),
      documentType: safeText(item.kind, "invoice"),
      intakeCategory: toIntakeCategory(item.intakeCategory || inferIntakeCategory(item.kind)),
      period: periodFromDate(safeText(item.uploadedAt), "2026-06"),
      uploadedAt: safeText(item.uploadedAt, "-"),
      uploadedBy: safeText(item.uploadedBy, safeText(clientUser?.displayName, clientName)),
      status: normalizeStatus(item.status),
      provider: "Ä°ÅŸleme alÄ±nacak belge",
      issueDate: "-",
      amount: "-",
      vatRates: [],
      productLine: "Belge kuyrukta",
      productCategory: "-",
      businessRelation: "-",
      accountTreatment: "-",
      requiresAccountantReview: true,
      previewText: "Belge yÃ¼klendi, otomatik kuyruÄŸa alÄ±nacak.",
      aiReason: "HenÃ¼z yorum yok.",
      aiProvider: "-",
      aiSuggestedAccountCode: "",
      aiSuggestedCounterpartyCode: "",
      aiRiskFlags: [],
      aiAccountReason: "",
      deterministicSummary: "Ä°ÅŸleme sonucu hazÄ±rlanÄ±yor.",
      exportGateReason: "Ä°ÅŸleme tamamlanmadan Ã§Ä±ktÄ±ya eklenemez.",
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
      accountingIntent: "",
      accountingIntentConfidence: 0,
      learningRuleScope: "",
      learningRuleReason: "",
      learningRuleSourceSummary: "",
      rulePrompt: normalizeRulePrompt({}),
    }));

  const documents = [...documentsFromRows, ...uploadOnlyDocuments];
  return {
    generatedFrom: safeText(raw.generatedFrom, "Yerel Ã§alÄ±ÅŸma verisi"),
    clients: [
      {
        clientId,
        clientName,
        taxId: "ofis-local",
        portalUserId: safeText(clientUser?.userId, "ofis-mukellef-user"),
        userLabel: safeText(clientUser?.displayName, "MÃ¼kellef kullanÄ±cÄ±sÄ±"),
        onboardingStatus: "Hesap planÄ± ve mÃ¼kellef kartÄ± Ã§alÄ±ÅŸma alanÄ±nda hazÄ±r",
      },
    ],
    documents,
    cancellationRequests: documents.length > 1
      ? [
          {
            id: `${documents[1].id}-cancel`,
            documentId: documents[1].id,
            clientId,
            fileName: documents[1].fileName,
            requestedBy: safeText(clientUser?.displayName, "MÃ¼kellef kullanÄ±cÄ±sÄ±"),
            requestedAt: "04.06.2026 10:30",
            reason: "MÃ¼kellef belge iÃ§in iptal veya dÃ¼zeltme kontrolÃ¼ istedi.",
            stage: documents[1].status === "export_ready" ? "post_export" : "pre_export",
            status: "open",
          },
        ]
      : [],
    exportBasket: documents.some((document) => document.status === "export_ready")
      ? [
          {
            id: `${clientId}-basket`,
            clientId,
            clientName,
            documentIds: documents.filter((document) => document.status === "export_ready").map((document) => document.id),
            documentCount: documents.filter((document) => document.status === "export_ready").length,
            period: documents.find((document) => document.status === "export_ready")?.period ?? "2026-06",
            status: "ready",
          },
        ]
      : [],
  };
}

export function normalizePilotData(raw: unknown): PilotData {
  const maybePilot = raw as Partial<PilotData>;
  if (Array.isArray(maybePilot.clients) && Array.isArray(maybePilot.documents)) {
    return {
      generatedFrom: safeText(maybePilot.generatedFrom, "Yerel Ã§alÄ±ÅŸma verisi"),
      clients: (maybePilot.clients as PilotClient[]).map((client) => ({
        ...client,
        portalUserId: safeText(
          client.portalUserId || (client as PilotClient & { userId?: string }).userId,
          "ofis-mukellef-user",
        ),
      })),
      documents: (maybePilot.documents as PilotDocument[]).map((document) => ({
        ...document,
        intakeCategory: toIntakeCategory(document.intakeCategory || inferIntakeCategory(document.documentType)),
        status: normalizeStatus(document.status),
        aiProvider: safeText(document.aiProvider, "-"),
        aiSuggestedAccountCode: safeText(document.aiSuggestedAccountCode, ""),
        aiSuggestedCounterpartyCode: safeText(document.aiSuggestedCounterpartyCode, ""),
        aiRiskFlags: Array.isArray(document.aiRiskFlags) ? document.aiRiskFlags : [],
        aiAccountReason: safeText(document.aiAccountReason, ""),
        vatRates: Array.isArray(document.vatRates) ? document.vatRates : [],
        reviewReasons: Array.isArray(document.reviewReasons) ? document.reviewReasons : [],
        riskFlags: Array.isArray(document.riskFlags) ? document.riskFlags : [],
        draftLines: Array.isArray(document.draftLines) ? document.draftLines : [],
        statementLines: normalizeStatementLines(document.statementLines),
        statementEntries: normalizeStatementEntries(document.statementEntries),
        statementAiSuggestions: normalizeStatementAiSuggestions(document.statementAiSuggestions),
        statementAiSummary: safeText(document.statementAiSummary),
        accountingIntent: safeText(document.accountingIntent, ""),
        accountingIntentConfidence: safeNumber(document.accountingIntentConfidence),
        learningRuleScope: safeText(document.learningRuleScope, ""),
        learningRuleReason: safeText(document.learningRuleReason, ""),
        learningRuleSourceSummary: safeText(document.learningRuleSourceSummary, ""),
        rulePrompt: normalizeRulePrompt(document.rulePrompt),
      })),
      cancellationRequests: Array.isArray(maybePilot.cancellationRequests) ? (maybePilot.cancellationRequests as CancellationRequest[]) : [],
      exportBasket: Array.isArray(maybePilot.exportBasket) ? (maybePilot.exportBasket as ExportBasketItem[]) : [],
    };
  }
  return normalizeReviewData(raw as ReviewData);
}
