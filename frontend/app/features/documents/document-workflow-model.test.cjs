const assert = require("node:assert/strict");
const test = require("node:test");

const {
  documentMatchesSegment,
  nextDocumentSelection,
  reviewFilteredDocuments,
  segmentForDocument,
  selectedDocumentFromState,
} = require("./document-workflow-model");

const docs = [
  { id: "sale-1", fileName: "sale.pdf", intakeCategory: "sales_invoice", status: "review_required" },
  { id: "purchase-1", fileName: "purchase.pdf", intakeCategory: "purchase_invoice", status: "review_required" },
  { id: "ready-1", fileName: "ready.pdf", intakeCategory: "purchase_invoice", status: "export_ready" },
  { id: "bank-1", fileName: "bank.csv", intakeCategory: "bank_statement", status: "review_required" },
];

test("row open selects the document and moves to its segment without losing selection", () => {
  assert.equal(segmentForDocument(docs[1]), "purchase_invoices");
  assert.deepEqual(nextDocumentSelection(docs[1]), {
    selectedDocumentId: "purchase-1",
    selectedDocumentSegment: "purchase_invoices",
  });
  assert.equal(
    selectedDocumentFromState({
      clientDocuments: docs,
      selectedDocumentId: "purchase-1",
      selectedDocumentSegment: "purchase_invoices",
    })?.fileName,
    "purchase.pdf",
  );
});

test("selected document is found from the segment source even when the visible review filter changes", () => {
  const visible = reviewFilteredDocuments({
    documents: docs.filter((document) => documentMatchesSegment(document, "purchase_invoices")),
    reviewFilter: "export_ready",
  });

  assert.deepEqual(visible.map((document) => document.id), ["ready-1"]);
  assert.equal(
    selectedDocumentFromState({
      clientDocuments: docs,
      selectedDocumentId: "purchase-1",
      selectedDocumentSegment: "purchase_invoices",
    })?.id,
    "purchase-1",
  );
});
