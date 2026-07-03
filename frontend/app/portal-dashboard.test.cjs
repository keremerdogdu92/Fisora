const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildClientCancellationViewModel,
  buildAgentSummaries,
  buildAgentLearningInsights,
  buildDashboardDurationMetrics,
  buildPortalDashboard,
  buildPortalDashboardViewModels,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
  priorityWorkItems,
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
  { id: "doc-5", clientId: "client-1", status: "review_required", intakeCategory: "sales_invoice", uploadedAt: "2026-06-08T12:00:00Z" },
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
      pendingReviewDocuments: 2,
      exportReadyDocuments: 1,
      openCancellationRequests: 1,
    },
  );
});

test("documentIntakeDistribution groups invoices, bank statements, and other documents", () => {
  assert.deepEqual(documentIntakeDistribution(documents), [
    { key: "invoices", label: "Faturalar", count: 3 },
    { key: "bank_statements", label: "Banka ekstreleri", count: 1 },
    { key: "other_documents", label: "Diğer belgeler", count: 1 },
  ]);
});

test("statusFunnel derives operation status buckets", () => {
  assert.deepEqual(statusFunnel(documents), [
    { key: "uploaded", label: "Yüklendi", count: 2 },
    { key: "review", label: "Kontrol bekliyor", count: 2 },
    { key: "export", label: "Çıktı hazır", count: 1 },
  ]);
});

test("clientUploadTracking separates uploaded and missing clients", () => {
  assert.deepEqual(clientUploadTracking({ clients, documents }), [
    { key: "uploaded", label: "Yükleyen", count: 2 },
    { key: "missing", label: "Yüklemeyen", count: 1 },
  ]);
});

test("documentsForProcessing filters by client and accountant document segment", () => {
  assert.deepEqual(
    documentsForProcessing({ documents, clientId: "client-1", segment: "invoices" }).map((document) => document.id),
    ["doc-1", "doc-2", "doc-5"],
  );
  assert.deepEqual(
    documentsForProcessing({ documents, clientId: "client-1", segment: "sales_invoices" }).map((document) => document.id),
    ["doc-2", "doc-5"],
  );
  assert.deepEqual(
    documentsForProcessing({ documents, clientId: "client-1", segment: "purchase_invoices" }).map((document) => document.id),
    ["doc-1"],
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

test("documentsForProcessing keeps pending direction conflicts in the upload segment", () => {
  const conflictedDocuments = [
    {
      id: "sales-upload-detected-purchase",
      clientId: "client-1",
      status: "review_required",
      intakeCategory: "sales_invoice",
      accountingDirection: "purchase",
      directionConflict: { status: "needs_review" },
      uploadedAt: "2026-06-08T13:00:00Z",
    },
  ];

  assert.deepEqual(
    documentsForProcessing({ documents: conflictedDocuments, clientId: "client-1", segment: "sales_invoices" }).map((document) => document.id),
    ["sales-upload-detected-purchase"],
  );
  assert.deepEqual(
    documentsForProcessing({ documents: conflictedDocuments, clientId: "client-1", segment: "purchase_invoices" }).map((document) => document.id),
    [],
  );
});

test("buildClientCancellationViewModel keeps cancellation actions bound to a selected document", () => {
  assert.equal(typeof buildClientCancellationViewModel, "function");

  const noSelection = buildClientCancellationViewModel({
    documents,
    selectedDocumentId: "",
    requestDocumentId: "",
    cancellationReason: "",
  });
  assert.equal(noSelection.selectedDocument, null);
  assert.equal(noSelection.requestDocument, null);
  assert.equal(noSelection.canSubmitCancellation, false);

  const selected = buildClientCancellationViewModel({
    documents,
    selectedDocumentId: "doc-1",
    requestDocumentId: "doc-1",
    cancellationReason: "Yanlis belge yuklendi",
  });
  assert.equal(selected.selectedDocument.id, "doc-1");
  assert.equal(selected.requestDocument.id, "doc-1");
  assert.equal(selected.canSubmitCancellation, true);
  assert.equal(selected.requestReason, "Yanlis belge yuklendi");
});

test("clientDashboardRows derives per-client follow-up status", () => {
  const rows = clientDashboardRows({ clients, documents, cancellationRequests });

  assert.deepEqual(rows[0], {
    clientId: "client-1",
    clientName: "A Isitme",
    taxId: "111",
    documentCount: 3,
    pendingReviewCount: 2,
    exportReadyCount: 1,
    inProgressCount: 0,
    cancellationCount: 1,
    lastUploadedAt: "2026-06-08T12:00:00Z",
    status: "Talep var",
  });
  assert.equal(rows[1].inProgressCount, 2);
  assert.equal(rows[2].documentCount, 0);
});

test("buildAgentSummaries exposes the four accountant-facing agents with safe metrics", () => {
  const agentDocuments = [
    {
      id: "accepted",
      status: "export_ready",
      draftLines: [{ account_code: "770", description: "Gider", debit: "100", credit: "0" }],
      selectedExpenseAccount: "770",
      selectedCounterpartyAccount: "320.01",
      aiResearchRequested: false,
      aiQualityScorecard: { quality_delta: { decision: "accepted", changed_fields: [] } },
    },
    {
      id: "changed",
      status: "review_required",
      draftLines: [],
      selectedExpenseAccount: "",
      selectedCounterpartyAccount: "",
      aiResearchRequested: true,
      aiQualityScorecard: { quality_delta: { decision: "changed", changed_fields: ["account"] } },
    },
  ];

  const agents = buildAgentSummaries({
    documents: agentDocuments,
    aiCapacity: {
      agents: [
        { kind: "document", label: "Document provider", remaining: 18, configured: true, status: "ready" },
        { kind: "research", label: "Research provider", remaining: null, configured: true, status: "ready" },
      ],
    },
  });

  assert.deepEqual(agents.map((agent) => agent.name), ["Belge ajanı", "Hesap ajanı", "Cari ajanı", "Araştırma ajanı"]);
  assert.equal(agents[0].capacityLabel, "18 kaldı");
  assert.equal(agents[1].unchangedApprovalRateLabel, "Müşavirce değişmeden onaylandı %50");
  assert.equal(agents[1].correctionCount, 1);
  assert.equal(agents[3].capacityLabel, "ölçülemiyor");
  assert.equal(agents[3].learningLabel, "Öğrenme sinyali kaydedildi");
});

test("buildAgentLearningInsights normalizes learning signals for the future training center", () => {
  const insights = buildAgentLearningInsights({
    documents: [
      {
        id: "signal",
        clientName: "A Isitme",
        fileName: "Kolaysoft.pdf",
        learningRuleReason: "Müşavir 770.05 hesabına aldı.",
        learningRuleSourceSummary: "",
        rulePrompt: { show: false },
      },
      {
        id: "candidate",
        clientName: "A Isitme",
        fileName: "Rexton.pdf",
        learningRuleSourceSummary: "Benzer kararlar kural adayına dönüştü.",
        rulePrompt: {
          show: true,
          message: "Rexton işitme cihazı alımlarında stok hesabı öner.",
          clientConsistentDecisionCount: 2,
          officeConsistentDecisionCount: 3,
          officeDistinctClientCount: 2,
        },
      },
    ],
  });

  assert.deepEqual(insights.map((item) => item.stageLabel), [
    "Öğrenme sinyali kaydedildi",
    "Kural adayı oluştu",
    "2/3 tutarlı onay",
    "Kontrollü otomasyon adayı",
  ]);
  assert.equal(insights[0].documentLabel, "A Isitme / Kolaysoft.pdf");
  assert.match(insights[1].summary, /Rexton/);
  assert.equal(insights[3].confidenceLabel, "2 mükellef / 3 onay");
});

test("buildAgentLearningInsights stays neutral without evidence", () => {
  assert.deepEqual(buildAgentLearningInsights({ documents: [{ id: "empty", rulePrompt: { show: false } }] }), []);
});

test("buildDashboardDurationMetrics only derives time from existing timestamps", () => {
  const metrics = buildDashboardDurationMetrics({
    documents: [
      {
        id: "timed-1",
        clientId: "client-1",
        uploadedAt: "2026-06-08T10:00:00Z",
        pipelineEvents: [
          { step: "uploaded", createdAt: "2026-06-08T10:00:00Z" },
          { step: "journal_saved", createdAt: "2026-06-08T10:04:00Z" },
          { step: "review_decision", createdAt: "2026-06-08T10:10:00Z" },
        ],
      },
      {
        id: "timed-2",
        clientId: "client-1",
        uploadedAt: "2026-06-08T11:00:00Z",
        pipelineEvents: [
          { step: "processing_completed", createdAt: "2026-06-08T11:08:00Z" },
          { step: "export_package", createdAt: "2026-06-08T11:20:00Z" },
        ],
      },
      { id: "missing", clientId: "client-2", uploadedAt: "", pipelineEvents: [] },
    ],
  });

  assert.equal(metrics.averageDocumentTimeLabel, "6 dk");
  assert.equal(metrics.uploadToDecisionTimeLabel, "15 dk");
  assert.equal(metrics.clientAverageCompletionTimeLabel, "20 dk");
});

test("buildDashboardDurationMetrics stays neutral when timestamps are missing", () => {
  const metrics = buildDashboardDurationMetrics({ documents: [{ id: "missing", uploadedAt: "", pipelineEvents: [] }] });

  assert.equal(metrics.averageDocumentTimeLabel, "ölçülemiyor");
  assert.equal(metrics.uploadToDecisionTimeLabel, "ölçülemiyor");
  assert.equal(metrics.clientAverageCompletionTimeLabel, "ölçülemiyor");
});

test("priorityWorkItems keeps the accountant workbench short and ordered by action need", () => {
  const manyDocuments = Array.from({ length: 12 }, (_, index) => ({
    id: `doc-${index}`,
    clientId: index % 2 ? "client-1" : "client-2",
    clientName: index % 2 ? "A Isitme" : "B Klinik",
    fileName: `Belge ${index}`,
    status: index < 6 ? "review_required" : "queued",
    reviewReasons: index === 0 ? ["manual_draft_required"] : [],
    uploadedAt: `2026-06-08T10:${String(index).padStart(2, "0")}:00Z`,
  }));

  const items = priorityWorkItems({ clients, documents: manyDocuments, cancellationRequests, limit: 8 });

  assert.equal(items.length, 8);
  assert.equal(items[0].kind, "request");
  assert.equal(items[1].kind, "document");
  assert.equal(items[1].label, "A Isitme");
  assert.match(items[1].detail, /Belge/);
});

test("buildPortalDashboardViewModels includes learning insights without opening a new agent page", () => {
  const view = buildPortalDashboardViewModels({
    data: {
      clients,
      cancellationRequests: [],
      documents: [
        {
          id: "candidate",
          clientId: "client-1",
          clientName: "A Isitme",
          fileName: "Kural.pdf",
          status: "review_required",
          learningRuleSourceSummary: "2/3 tutarlı onay bekleniyor.",
          rulePrompt: { show: true, clientConsistentDecisionCount: 2 },
        },
      ],
    },
  });

  assert.equal(view.learningInsights.length, 3);
  assert.equal(view.learningInsights[0].stageLabel, "Öğrenme sinyali kaydedildi");
});
