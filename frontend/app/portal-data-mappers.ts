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
  generatedFrom: "Çalışma alanı yükleniyor",
  clients: [],
  documents: [],
  cancellationRequests: [],
  exportBasket: [],
};

function normalizeReviewData(raw: ReviewData): PilotData {
  const clientId = safeText(raw.clientId, "ofis-calisma-client");
  const clientName = safeText(raw.clientName, "Ofis Mükellefi");
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
      originalDocumentRef: safeText(row.documentRef || row.fileName, safeText(row.fileName, "")),
      originalDocumentMimeType: safeText((row as Record<string, unknown>).contentType, "application/pdf"),
      provider: safeText(row.providerHint, "Tedarikçi bilinmiyor"),
      issueDate: safeText(row.issueDate, "-"),
      amount: safeText(row.payableTotal, "-"),
      vatRates: Array.isArray(row.vatRates) ? row.vatRates.map(String) : [],
      productLine: safeText(row.productLineHint, "-"),
      productCategory: safeText(row.productCategory, "-"),
      businessRelation: safeText(row.businessRelevanceRelation, "-"),
      accountTreatment: safeText(row.businessRelevanceAccountTreatment, "-"),
      requiresAccountantReview: Boolean(row.businessRelevanceRequiresReview),
      previewText: [
        safeText(row.providerHint, "Tedarikçi bilinmiyor"),
        safeText(row.productLineHint, "Belge kalemi okunuyor"),
        safeText(row.payableTotal, "-"),
      ].join(" / "),
      aiReason:
        safeText(row.aiClassificationReason) ||
        safeText(row.businessRelevanceReason) ||
        safeText(row.aiClassificationSkippedReason, "Öneri gerekçesi yok"),
      aiProvider: safeText(row.aiClassificationProvider, "-"),
      aiSuggestedAccountCode: safeText(row.aiSuggestedAccountCode, ""),
      aiSuggestedCounterpartyCode: safeText(row.aiSuggestedCounterpartyCode, ""),
      aiRiskFlags: Array.isArray(row.aiRiskFlags) ? row.aiRiskFlags.map(String) : [],
      aiAccountReason: safeText(row.aiAccountReason, ""),
      deterministicSummary: (row.deterministicChecks ?? []).join(", ") || (row.isBalanced ? "balanced_entry" : "denge kontrolü gerekli"),
      exportGateReason: safeText(row.exportGateReason, status === "export_ready" ? "Çıktı listesine alınabilir." : "Müşavir kontrolü gerekiyor."),
      draftStatus: Array.isArray(row.draftLines) && row.draftLines.length ? "draft_ready" : "manual_draft_required",
      accountantSummary: Array.isArray(row.draftLines) && row.draftLines.length ? "Fiş taslağı hazır." : "Fiş taslağı için manuel kontrol gerekiyor.",
      accountantExplanation: safeText(row.accountantExplanationTr ?? row.accountant_explanation_tr ?? row.aiClassificationReason ?? row.businessRelevanceReason),
      technicalDetails: {},
      pipelineEvents: [],
      accountingDirection: safeText(row.accountingDirection, toIntakeCategory(row.intakeCategory || inferIntakeCategory("invoice", row.invoiceType)) === "sales_invoice" ? "sales" : "purchase"),
      selectedExpenseAccount: safeText(row.selectedExpenseAccount, "-"),
      selectedVatAccount: safeText(row.selectedVatAccount, "-"),
      selectedCounterpartyAccount: safeText(row.selectedSupplierAccount || row.counterpartyMatchCode, "-"),
      selectedRevenueAccount: safeText(row.selectedRevenueAccount, "-"),
      selectedPurchaseVatAccount: safeText(row.selectedPurchaseVatAccount || row.selectedVatAccount, "-"),
      selectedSalesVatAccount: safeText(row.selectedSalesVatAccount || row.selectedVatAccount, "-"),
      selectedCustomerAccount: safeText(row.selectedCustomerAccount, "-"),
      suggestedCounterpartyAccount: safeText(row.suggestedCounterpartyAccount || row.selectedSupplierAccount || row.counterpartyMatchCode, "-"),
      counterpartyCreationSuggestion: row.counterpartyCreationSuggestion ?? {},
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
      originalDocumentRef: safeText(item.id, `${clientId}-upload-${index + 1}`),
      originalDocumentMimeType: "application/pdf",
      provider: "İşleme alınacak belge",
      issueDate: "-",
      amount: "-",
      vatRates: [],
      productLine: "Belge kuyrukta",
      productCategory: "-",
      businessRelation: "-",
      accountTreatment: "-",
      requiresAccountantReview: true,
      previewText: "Belge yüklendi, otomatik kuyruğa alınacak.",
      aiReason: "Henüz yorum yok.",
      aiProvider: "-",
      aiSuggestedAccountCode: "",
      aiSuggestedCounterpartyCode: "",
      aiRiskFlags: [],
      aiAccountReason: "",
      deterministicSummary: "İşleme sonucu hazırlanıyor.",
      exportGateReason: "İşleme tamamlanmadan çıktıya eklenemez.",
      draftStatus: "processing",
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
    generatedFrom: safeText(raw.generatedFrom, "Yerel çalışma verisi"),
    clients: [
      {
        clientId,
        clientName,
        taxId: "ofis-local",
        portalUserId: safeText(clientUser?.userId, "ofis-mukellef-user"),
        userLabel: safeText(clientUser?.displayName, "Mükellef kullanıcısı"),
        onboardingStatus: "Hesap planı ve mükellef kartı çalışma alanında hazır",
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
            requestedBy: safeText(clientUser?.displayName, "Mükellef kullanıcısı"),
            requestedAt: "04.06.2026 10:30",
            reason: "Mükellef belge için iptal veya düzeltme kontrolü istedi.",
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
      generatedFrom: safeText(maybePilot.generatedFrom, "Yerel çalışma verisi"),
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
        accountantExplanation: safeText(document.accountantExplanation, ""),
        accountingDirection: safeText(document.accountingDirection, ""),
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
        pipelineEvents: Array.isArray(document.pipelineEvents) ? document.pipelineEvents : [],
        selectedRevenueAccount: safeText(document.selectedRevenueAccount, "-"),
        selectedPurchaseVatAccount: safeText(document.selectedPurchaseVatAccount, document.selectedVatAccount || "-"),
        selectedSalesVatAccount: safeText(document.selectedSalesVatAccount, document.selectedVatAccount || "-"),
        selectedCustomerAccount: safeText(document.selectedCustomerAccount, "-"),
        suggestedCounterpartyAccount: safeText(document.suggestedCounterpartyAccount, document.selectedCounterpartyAccount || "-"),
        counterpartyCreationSuggestion: document.counterpartyCreationSuggestion ?? {},
        accountCandidates: document.accountCandidates ?? {
          purchaseStock: [],
          purchaseExpense: [],
          purchaseVat: [],
          salesRevenue: [],
          zeroVatRevenue: [],
          salesVat: [],
          customer: [],
          supplier: [],
        },
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
