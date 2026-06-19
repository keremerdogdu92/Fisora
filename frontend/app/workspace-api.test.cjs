const assert = require("node:assert/strict");
const test = require("node:test");

const {
  backendAuthHeaders,
  fetchAiCapacity,
  fetchResearchBenchmarkRuns,
  fetchResearchProfiles,
  fetchBackendReadiness,
  fetchBackendPilotData,
  normalizeBackendWorkspaces,
  overrideResearchProfile,
  refreshResearchProfile,
  runResearchBenchmark,
} = require("./workspace-api");

const clientRecord = {
  client_id: "client-1",
  profile: {
    client_id: "client-1",
    title: "Canli Pilot A.S.",
    tax_id: "1111111111",
  },
};

const workspaceRecord = {
  client: clientRecord,
  portal_users: [
    {
      user_id: "mukellef-user",
      display_name: "Mukellef Kullanici",
      role: "client_user",
    },
  ],
  uploaded_documents: [
    {
      client_id: "client-1",
      document_ref: "upload-1",
      original_file_name: "alis-faturasi.pdf",
      content_type: "application/pdf",
      document_type: "invoice",
      intake_category: "purchase_invoice",
      period: "2026-05",
      status: "stored",
      uploaded_by: "mukellef-user",
      created_at: "2026-06-07T10:00:00Z",
    },
  ],
  documents: [
    {
      client_id: "client-1",
      document_ref: "processed-1",
      export_status: "export_ready",
      result: {
        file_name: "satis-faturasi.pdf",
        invoice_type: "SATIS",
        issue_date: "2026-06-01",
        payable_total: "120.00",
        vat_rates: ["20"],
        provider_hint: "Pilot Alici",
        product_line_hint: "Cihaz satisi",
        product_category: "Satis",
        business_relevance_relation: "core_business",
        business_relevance_account_treatment: "stock_or_cogs",
        business_relevance_requires_review: false,
        ai_classification_provider: "static_rules",
        ai_classification_reason: "Kalem satis olarak siniflandi.",
        ai_explanation_tr: "AI kararı: statik kurallar belge kalemini satış olarak değerlendirdi.",
        accounting_intent: "e_fatura_yazilim_gideri",
        accounting_intent_confidence: 84,
        learning_rule_scope: "client_rule",
        learning_rule_reason: "Kolay Soft e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
        learning_rule_source_summary: "Bu oneride 3 onceki musavir karari kullanildi.",
        rule_prompt: {
          show: true,
          default_scope: "client_narrow",
          message: "Bu karari 3 kez benzer sekilde verdiniz.",
          client_consistent_decision_count: 3,
          office_distinct_client_count: 1,
          office_consistent_decision_count: 3,
        },
        accounting_direction: "sales",
        selected_expense_account: "",
        selected_vat_account: "391.20",
        selected_supplier_account: "",
        selected_revenue_account: "600.20",
        selected_sales_vat_account: "391.20",
        selected_customer_account: "120.01",
        suggested_counterparty_account: "120.A03",
        counterparty_creation_suggestion: {
          type: "customer",
          base_account: "120",
          suggested_code: "120.A03",
          always_suggest_new: true,
        },
        account_candidates: {
          sales_revenue: [
            { code: "600.20", name: "Yurt ici satislar yuzde 20", reason: "600 satis geliri adayi" },
          ],
          sales_vat: [
            { code: "391.20", name: "Hesaplanan KDV yuzde 20", reason: "391 hesaplanan KDV adayi" },
          ],
          customer: [
            { code: "120.A03", name: "Yeni alici onerisi", reason: "120 alici cari adayi" },
          ],
        },
        counterparty_match_confidence: 92,
        review_reason_codes: [],
        risk_flags: [],
        deterministic_checks: ["balanced_entry"],
        export_gate_reason: "Export hazir.",
        document_validation_status: "expected_document",
        draft_status: "draft_ready",
        accountant_summary: "Fis taslagi hazir. Musavir kontrolunden sonra cikti listesine alinabilir.",
        accountant_explanation_tr: "Satis faturasi olarak yorumlandi; gelir 600.20 ve KDV 391.20 hesaplarina gider.",
        technical_details: {
          parse_notes: [],
          review_reason_codes: [],
        },
        draft_lines: [
          { account_code: "120.01", description: "Alici", debit: "120.00", credit: "0.00" },
          { account_code: "600.01", description: "Satis", debit: "0.00", credit: "100.00" },
          { account_code: "391.01", description: "KDV", debit: "0.00", credit: "20.00" },
        ],
      },
    },
  ],
  document_pipeline_events: [
    {
      client_id: "client-1",
      document_ref: "processed-1",
      step: "uploaded",
      status: "ok",
      message_tr: "Belge yüklendi.",
      debug_code: "uploaded",
      details: { size_bytes: 120 },
      created_at: "2026-06-07T10:00:00Z",
    },
    {
      client_id: "client-1",
      document_ref: "processed-1",
      step: "ai_decision_ready",
      status: "ok",
      message_tr: "AI geldi karar verdi.",
      debug_code: "ai_decision_ready",
      details: { provider: "static_rules" },
      created_at: "2026-06-07T10:01:00Z",
    },
    {
      client_id: "client-1",
      document_ref: "upload-1",
      step: "uploaded",
      status: "ok",
      message_tr: "Belge yüklendi.",
      debug_code: "uploaded",
      details: {},
      created_at: "2026-06-07T10:02:00Z",
    },
  ],
  processing_jobs: [
    {
      document_ref: "upload-1",
      status: "queued",
      document_type: "invoice",
      intake_category: "purchase_invoice",
    },
  ],
  export_packages: [
    {
      id: "package-1",
      package: {
        entry_count: 1,
        output_filename: "client-1-zirve.csv",
        export_type: "zirve_universal_csv",
      },
    },
  ],
};

test("backendAuthHeaders prefers session tokens and falls back to the mock user header", () => {
  assert.deepEqual(backendAuthHeaders({ sessionToken: "session-1", userId: "mukellef-user" }), {
    "X-Fisora-Session": "session-1",
  });
  assert.deepEqual(backendAuthHeaders({ userId: "mukellef-user" }), {
    "X-Fisora-User-Id": "mukellef-user",
  });
  assert.deepEqual(backendAuthHeaders({}), {});
});

test("normalizeBackendWorkspaces maps backend workspace records into portal data", () => {
  const data = normalizeBackendWorkspaces({
    clients: [clientRecord],
    workspaces: [workspaceRecord],
    source: "Çalışma alanı",
  });

  assert.equal(data.generatedFrom, "Çalışma alanı");
  assert.deepEqual(data.clients[0], {
    clientId: "client-1",
    clientName: "Canli Pilot A.S.",
    taxId: "1111111111",
    userLabel: "Mukellef Kullanici",
    portalUserId: "mukellef-user",
    onboardingStatus: "Çalışma alanı",
  });
  assert.equal(data.documents.length, 2);
  assert.equal(data.documents[0].id, "processed-1");
  assert.equal(data.documents[0].status, "export_ready");
  assert.equal(data.documents[0].intakeCategory, "sales_invoice");
  assert.equal(data.documents[0].draftLines.length, 3);
  assert.equal(data.documents[0].businessRelation, "core_business");
  assert.equal(data.documents[0].accountTreatment, "stock_or_cogs");
  assert.equal(data.documents[0].requiresAccountantReview, false);
  assert.equal(data.documents[0].aiReason, "AI kararı: statik kurallar belge kalemini satış olarak değerlendirdi.");
  assert.deepEqual(
    data.documents[0].pipelineEvents.map((event) => [event.step, event.status, event.messageTr, event.debugCode]),
    [
      ["uploaded", "ok", "Belge yüklendi.", "uploaded"],
      ["ai_decision_ready", "ok", "AI geldi karar verdi.", "ai_decision_ready"],
    ],
  );
  assert.equal(data.documents[0].accountingIntent, "e_fatura_yazilim_gideri");
  assert.equal(data.documents[0].accountingIntentConfidence, 84);
  assert.deepEqual(data.documents[0].rulePrompt, {
    show: true,
    defaultScope: "client_narrow",
    message: "Bu karari 3 kez benzer sekilde verdiniz.",
    clientConsistentDecisionCount: 3,
    officeDistinctClientCount: 1,
    officeConsistentDecisionCount: 3,
  });
  assert.equal(data.documents[0].learningRuleSourceSummary, "Bu oneride 3 onceki musavir karari kullanildi.");
  assert.equal(data.documents[0].originalDocumentRef, "processed-1");
  assert.equal(data.documents[0].draftStatus, "draft_ready");
  assert.equal(data.documents[0].accountantSummary, "Fis taslagi hazir. Musavir kontrolunden sonra cikti listesine alinabilir.");
  assert.equal(data.documents[0].accountantExplanation, "Satis faturasi olarak yorumlandi; gelir 600.20 ve KDV 391.20 hesaplarina gider.");
  assert.equal(data.documents[0].accountingDirection, "sales");
  assert.equal(data.documents[0].selectedExpenseAccount, "-");
  assert.equal(data.documents[0].selectedRevenueAccount, "600.20");
  assert.equal(data.documents[0].selectedSalesVatAccount, "391.20");
  assert.equal(data.documents[0].selectedCustomerAccount, "120.01");
  assert.equal(data.documents[0].suggestedCounterpartyAccount, "120.A03");
  assert.deepEqual(data.documents[0].accountCandidates.salesRevenue, [
    { code: "600.20", name: "Yurt ici satislar yuzde 20", reason: "600 satis geliri adayi" },
  ]);
  assert.deepEqual(data.documents[0].accountCandidates.salesVat, [
    { code: "391.20", name: "Hesaplanan KDV yuzde 20", reason: "391 hesaplanan KDV adayi" },
  ]);
  assert.deepEqual(data.documents[0].technicalDetails, {
    parse_notes: [],
    review_reason_codes: [],
  });
  assert.equal(data.documents[1].id, "upload-1");
  assert.equal(data.documents[1].status, "queued");
  assert.equal(data.documents[1].originalDocumentRef, "upload-1");
  assert.equal(data.documents[1].originalDocumentMimeType, "application/pdf");
  assert.equal(data.documents[1].period, "2026-05");
  assert.equal(data.documents[1].previewText, "Belge alındı; işleme sonucu hazırlanıyor.");
  assert.deepEqual(data.documents[1].pipelineEvents.map((event) => event.step), ["uploaded"]);
  assert.deepEqual(data.exportBasket[0], {
    id: "package-1",
    clientId: "client-1",
    clientName: "Canli Pilot A.S.",
    documentIds: [],
    documentCount: 1,
    period: "2026-06",
    status: "packaged",
  });
});

test("fetchBackendPilotData loads clients then each allowed workspace", async () => {
  const requests = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    if (url.endsWith("/phase0/store/clients")) {
      return {
        ok: true,
        json: async () => ({ clients: [clientRecord] }),
      };
    }
    if (url.endsWith("/phase0/store/workspace/client-1")) {
      return {
        ok: true,
        json: async () => workspaceRecord,
      };
    }
    return { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
  };

  const data = await fetchBackendPilotData({
    apiBaseUrl: "http://localhost:8000",
    userId: "mukellef-user",
    fetchImpl,
  });

  assert.equal(data.clients.length, 1);
  assert.equal(data.documents.length, 2);
  assert.deepEqual(
    requests.map((request) => request.url),
    [
      "http://localhost:8000/phase0/store/clients",
      "http://localhost:8000/phase0/store/workspace/client-1",
    ],
  );
  assert.deepEqual(requests[0].init.headers, { "X-Fisora-User-Id": "mukellef-user" });
  assert.deepEqual(requests[1].init.headers, { "X-Fisora-User-Id": "mukellef-user" });
});

test("fetchBackendReadiness loads the system readiness payload without auth headers", async () => {
  const requests = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    return {
      ok: true,
      json: async () => ({
        pilot_sellable: true,
        production_ready: false,
      }),
    };
  };

  const readiness = await fetchBackendReadiness({
    apiBaseUrl: "http://localhost:8000/",
    fetchImpl,
  });

  assert.deepEqual(readiness, {
    pilot_sellable: true,
    production_ready: false,
  });
  assert.equal(requests[0].url, "http://localhost:8000/phase0/store/system/readiness");
  assert.equal(requests[0].init.method, "GET");
  assert.deepEqual(requests[0].init.headers, {});
  assert.ok(requests[0].init.signal);
});

test("fetchAiCapacity loads the protected AI agent capacity endpoint with accountant auth", async () => {
  const requests = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    return {
      ok: true,
      json: async () => ({
        status: "ok",
        agents: [{ label: "Araştırma ajanı", configured: true }],
        totals: { document_queries: 12, internet_researches: 1 },
      }),
    };
  };

  const capacity = await fetchAiCapacity({
    apiBaseUrl: "http://localhost:8000/",
    fetchImpl,
    sessionToken: "session-1",
    userId: "mali-musavir",
  });

  assert.equal(capacity.agents[0].label, "Araştırma ajanı");
  assert.equal(requests[0].url, "http://localhost:8000/phase0/store/ai-capacity");
  assert.equal(requests[0].init.method, "GET");
  assert.deepEqual(requests[0].init.headers, { "X-Fisora-Session": "session-1" });
});

test("research API helpers use accountant auth and expected endpoints", async () => {
  const requests = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    return {
      ok: true,
      json: async () => ({ ok: true, profiles: [], runs: [], profile: { key: "rexton" } }),
    };
  };

  await fetchResearchProfiles({
    apiBaseUrl: "http://localhost:8000/",
    fetchImpl,
    kind: "brand",
    userId: "mali-musavir",
  });
  await refreshResearchProfile({
    apiBaseUrl: "http://localhost:8000",
    fetchImpl,
    payload: { kind: "brand", key: "rexton", query: "Rexton isitme cihazi" },
    userId: "mali-musavir",
  });
  await overrideResearchProfile({
    apiBaseUrl: "http://localhost:8000",
    fetchImpl,
    payload: { kind: "brand", key: "rexton", category_tags: ["medical_device"], confidence: 95 },
    userId: "mali-musavir",
  });
  await runResearchBenchmark({
    apiBaseUrl: "http://localhost:8000",
    fetchImpl,
    userId: "mali-musavir",
  });
  await fetchResearchBenchmarkRuns({
    apiBaseUrl: "http://localhost:8000",
    fetchImpl,
    userId: "mali-musavir",
  });

  assert.deepEqual(
    requests.map((request) => [request.init.method, request.url]),
    [
      ["GET", "http://localhost:8000/phase0/store/research/profiles?kind=brand"],
      ["POST", "http://localhost:8000/phase0/store/research/refresh"],
      ["POST", "http://localhost:8000/phase0/store/research/override"],
      ["POST", "http://localhost:8000/phase0/store/research/benchmark/run"],
      ["GET", "http://localhost:8000/phase0/store/research/benchmark/runs"],
    ],
  );
  assert.deepEqual(requests[1].init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(requests[2].init.body).category_tags, ["medical_device"]);
});

test("fetchBackendPilotData aborts slow backend requests so local fallback can continue", async () => {
  const fetchImpl = (url, init = {}) =>
    new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new Error(`aborted ${url}`)));
    });

  await assert.rejects(
    () =>
      fetchBackendPilotData({
        apiBaseUrl: "http://localhost:8000",
        fetchImpl,
        timeoutMs: 5,
        userId: "mali-musavir",
      }),
    /aborted http:\/\/localhost:8000\/phase0\/store\/clients/,
  );
});
