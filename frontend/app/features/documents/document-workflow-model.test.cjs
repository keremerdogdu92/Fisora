// File: frontend/app/features/documents/document-workflow-model.test.cjs
// Summary: Verifies document selection, filtering, segmentation, and review cockpit queue behavior without React state.
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  documentMatchesSegment,
  firstInvoiceSelection,
  reviewCockpitQueues,
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

test("invoice page opens the first visible document in the active invoice segment", () => {
  assert.deepEqual(
    firstInvoiceSelection({
      documents: docs,
      reviewFilter: "review_required",
      selectedDocumentSegment: "purchase_invoices",
    }),
    {
      selectedDocumentId: "purchase-1",
      selectedDocumentSegment: "purchase_invoices",
    },
  );
});

test("invoice page initial open can fall back from an empty invoice segment to the other invoice segment", () => {
  assert.deepEqual(
    firstInvoiceSelection({
      documents: docs.filter((document) => document.id !== "purchase-1"),
      reviewFilter: "review_required",
      selectedDocumentSegment: "purchase_invoices",
    }),
    {
      selectedDocumentId: "sale-1",
      selectedDocumentSegment: "sales_invoices",
    },
  );
});

test("review cockpit queues separate one-click, minor-edit, and manual-risk documents", () => {
  const queues = reviewCockpitQueues([
    {
      id: "one-click",
      status: "review_required",
      isBalanced: true,
      reviewReasons: ["ai_assisted_draft_requires_accountant_approval"],
      draftLines: [{ account_code: "770.01" }],
    },
    {
      id: "minor-edit",
      status: "review_required",
      isBalanced: true,
      reviewReasons: ["counterparty_missing"],
      counterpartyCreationSuggestion: { suggested_code: "320.9999999999" },
      draftLines: [{ account_code: "770.01" }],
    },
    {
      id: "manual",
      status: "review_required",
      isBalanced: false,
      reviewReasons: ["mixed_vat_manual_review"],
      draftLines: [],
    },
    {
      id: "ready",
      status: "export_ready",
      isBalanced: true,
      reviewReasons: [],
      draftLines: [{ account_code: "770.01" }],
    },
    {
      id: "no-posting",
      status: "no_posting_required",
      isBalanced: true,
      reviewReasons: [],
      draftLines: [],
    },
  ]);

  assert.deepEqual(queues.oneClickApproval.map((document) => document.id), ["one-click", "ready"]);
  assert.deepEqual(queues.minorEdit.map((document) => document.id), ["minor-edit"]);
  assert.deepEqual(queues.manualRisk.map((document) => document.id), ["manual"]);
});
