const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildPortalDashboard,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
  statusFunnel,
} = require("./portal-dashboard");

const clients = [
  { clientId: "client-1", clientName: "A Isitme", taxId: "111" },
  { clientId: "client-2", clientName: "B Klinik", taxId: "222" },
  { clientId: "client-3", clientName: "C Market", taxId: "333" },
];

const documents = [
  { id: "doc-1", clientId: "client-1", status: "review_required", intakeCategory: "purchase_invoice", uploadedAt: "2026-06-08T10:00:00Z" },
  { id: "doc-2", clientId: "client-1", status: "export_ready", intakeCategory: "sales_invoice", uploadedAt: "2026-06-08T11:00:00Z" },
  { id: "doc-3", clientId: "client-2", status: "queued", intakeCategory: "bank_statement", uploadedAt: "2026-06-07T09:00:00Z" },
  { id: "doc-4", clientId: "client-2", status: "uploaded", intakeCategory: "special_document", uploadedAt: "2026-06-07T12:00:00Z" },
];

const cancellationRequests = [
  { id: "cancel-1", clientId: "client-1", documentId: "doc-1", status: "open" },
  { id: "cancel-2", clientId: "client-2", documentId: "doc-3", status: "approved" },
];

test("buildPortalDashboard derives office-level metrics", () => {
  assert.deepEqual(
    buildPortalDashboard({ clients, documents, cancellationRequests }),
    {
      totalClients: 3,
      uploadedClients: 2,
      notUploadedClients: 1,
      pendingReviewDocuments: 1,
      exportReadyDocuments: 1,
      openCancellationRequests: 1,
    },
  );
});

test("documentIntakeDistribution groups invoices, bank statements, and other documents", () => {
  assert.deepEqual(documentIntakeDistribution(documents), [
    { key: "invoices", label: "Faturalar", count: 2 },
    { key: "bank_statements", label: "Banka ekstreleri", count: 1 },
    { key: "other_documents", label: "Diger belgeler", count: 1 },
  ]);
});

test("statusFunnel derives operation status buckets", () => {
  assert.deepEqual(statusFunnel(documents), [
    { key: "uploaded", label: "Yuklendi", count: 2 },
    { key: "review", label: "Kontrol bekliyor", count: 1 },
    { key: "export", label: "Cikti hazir", count: 1 },
  ]);
});

test("clientUploadTracking separates uploaded and missing clients", () => {
  assert.deepEqual(clientUploadTracking({ clients, documents }), [
    { key: "uploaded", label: "Yukleyen", count: 2 },
    { key: "missing", label: "Yuklemeyen", count: 1 },
  ]);
});

test("documentsForProcessing filters by client and accountant document segment", () => {
  assert.deepEqual(
    documentsForProcessing({ documents, clientId: "client-1", segment: "invoices" }).map((document) => document.id),
    ["doc-1", "doc-2"],
  );
  assert.deepEqual(
    documentsForProcessing({ documents, clientId: "client-2", segment: "bank_statements" }).map((document) => document.id),
    ["doc-3"],
  );
  assert.deepEqual(
    documentsForProcessing({ documents, clientId: "client-2", segment: "other_documents" }).map((document) => document.id),
    ["doc-4"],
  );
});

test("clientDashboardRows derives per-client follow-up status", () => {
  const rows = clientDashboardRows({ clients, documents, cancellationRequests });

  assert.deepEqual(rows[0], {
    clientId: "client-1",
    clientName: "A Isitme",
    taxId: "111",
    documentCount: 2,
    pendingReviewCount: 1,
    exportReadyCount: 1,
    inProgressCount: 0,
    cancellationCount: 1,
    lastUploadedAt: "2026-06-08T11:00:00Z",
    status: "Talep var",
  });
  assert.equal(rows[1].status, "İşleniyor");
  assert.equal(rows[2].status, "Yükleme yok");
});
