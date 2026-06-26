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
  reviewFilteredDocuments,
  segmentForDocument,
  selectedDocumentFromState,
};
