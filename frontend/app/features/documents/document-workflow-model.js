function segmentForDocument(document) {
  if (document.intakeCategory === "bank_statement") return "bank_statements";
  if (document.intakeCategory === "special_document") return "other_documents";
  if (document.intakeCategory === "purchase_invoice") return "purchase_invoices";
  return "sales_invoices";
}

function documentMatchesSegment(document, segment) {
  if (segment === "invoices") {
    return document.intakeCategory === "sales_invoice" || document.intakeCategory === "purchase_invoice";
  }
  return segmentForDocument(document) === segment;
}

function reviewFilteredDocuments({ documents, reviewFilter }) {
  if (reviewFilter === "all") return documents;
  if (reviewFilter === "cancel_requested") {
    return documents.filter((document) =>
      document.status === "cancel_requested" || document.status === "post_export_correction_requested",
    );
  }
  return documents.filter((document) => document.status === reviewFilter);
}

function hasDraftLines(document) {
  return Array.isArray(document.draftLines) && document.draftLines.length > 0;
}

function isBalancedDraft(document) {
  return document.isBalanced === true || document.is_balanced === true;
}

function documentReviewReasons(document) {
  return Array.isArray(document.reviewReasons)
    ? document.reviewReasons
    : Array.isArray(document.review_reason_codes)
      ? document.review_reason_codes
      : [];
}

function hasCounterpartyCreationSuggestion(document) {
  const suggestion = document.counterpartyCreationSuggestion || document.counterparty_creation_suggestion;
  return Boolean(suggestion && typeof suggestion === "object" && Object.keys(suggestion).length > 0);
}

function reviewCockpitQueues(documents) {
  const queues = {
    oneClickApproval: [],
    minorEdit: [],
    manualRisk: [],
  };
  for (const document of documents) {
    const reasons = documentReviewReasons(document);
    const hasOnlyApprovalGate =
      reasons.length === 0 ||
      reasons.every((reason) =>
        reason === "ai_assisted_draft_requires_accountant_approval" ||
        reason === "conservative_mode_requires_review",
      );
    if (document.status === "export_ready" || (hasDraftLines(document) && isBalancedDraft(document) && hasOnlyApprovalGate)) {
      queues.oneClickApproval.push(document);
    } else if (hasDraftLines(document) && isBalancedDraft(document) && (hasCounterpartyCreationSuggestion(document) || reasons.length <= 2)) {
      queues.minorEdit.push(document);
    } else {
      queues.manualRisk.push(document);
    }
  }
  return queues;
}

function selectedDocumentFromState({ clientDocuments, selectedDocumentId, selectedDocumentSegment }) {
  if (!selectedDocumentId) return undefined;
  const segmentDocuments = clientDocuments.filter((document) =>
    documentMatchesSegment(document, selectedDocumentSegment),
  );
  return segmentDocuments.find((document) => document.id === selectedDocumentId);
}

function nextDocumentSelection(document) {
  return {
    selectedDocumentId: document.id,
    selectedDocumentSegment: segmentForDocument(document),
  };
}

module.exports = {
  documentMatchesSegment,
  nextDocumentSelection,
  reviewCockpitQueues,
  reviewFilteredDocuments,
  segmentForDocument,
  selectedDocumentFromState,
};
