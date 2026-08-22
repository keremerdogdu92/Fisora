// File: frontend/app/workspace-api.test.cjs
// Summary: Tests workspace mapping, selected-document progress polling, stale-result isolation, capacity, and research API helpers.
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  backendAuthHeaders,
  fetchAiCapacity,
  fetchResearchBenchmarkRuns,
  fetchResearchProfiles,
  fetchBackendReadiness,
  fetchBackendPilotData,
  fetchDocumentProgress,
  normalizeBackendWorkspaces,
  overrideResearchProfile,
  refreshResearchProfile,
  runResearchBenchmark,
  turkishResearchSummary,
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
  onboarding_attachments: [
    {
      attachment_ref: "tax-cert-1",
      attachment_type: "tax_certificate",
      original_file_name: "vergi-levhasi.pdf",
      storage_status: "stored",
      created_at: "2026-06-06T09:00:00Z",
    },
    {
      attachment_ref: "chart-1",
      attachment_type: "chart_accounts",
      original_file_name: "hesap-plani.xlsx",
      storage_status: "stored",
      created_at: "2026-06-06T09:30:00Z",
    },
  ],
  chart_accounts: {
    account_count: 3,
    accounts: [
      {
        raw_account_code: "191 01 020",
        normalized_account_code: "191.01.020",
        account_name: "Indirilecek KDV %20",
        is_detail_account: true,
      },
      {
        raw_account_code: "320.B04",
        normalized_account_code: "320.B04",
        account_name: "Rexton Medikal",
        is_detail_account: true,
        tax_id: "1234567890",
      },
      {
        raw_account_code: "770.01",
        normalized_account_code: "770.01",
        account_name: "Genel gider",
        is_detail_account: true,
      },
    ],
  },
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
        ai_gate_reason: "cold_start_core_accounting_line",
        ai_product_identity: "Helix Force 200 RI isitme cihazi",
        ai_research_requested: false,
        ai_research_query: "",
        client_nace_code: "477401",
        client_activity_tags: ["hearing_aid", "medical_retail", "retail_trade"],
        counterparty_tax_id: "2222222222",
        counterparty_title: "Alici Hasta",
        counterparty_identity_key: "2222222222",
        decision_narrative: {
          invoice_product_line: "Cihaz satisi",
          fisora_interpretation: "Isitme cihazi",
          business_relation: "Faaliyetle dogrudan iliskili",
          account_code: "600.20",
          account_name: "Yurt ici satislar yuzde 20",
          counterparty_match: "VKN birebir eslesti / 120.01 / Alici Hasta",
          confidence_label: "Yuksek",
          unresolved_info: "",
          read_facts: {
            "Fatura urun satiri": "Cihaz satisi",
            "Satici unvani": "Pilot Alici",
            "KDV orani": "%20",
            "Genel toplam": "120.00",
            "Tutar kontrolu": "Matrah + KDV toplamla uyumlu",
          },
        },
        ai_explanation_tr: "AI kararı: statik kurallar belge kalemini satış olarak değerlendirdi.",
        accounting_intent: "e_fatura_yazilim_gideri",
        accounting_intent_confidence: 84,
        learning_rule_scope: "client_rule",
        learning_rule_reason: "Kolay Soft e-fatura hizmetleri 770.05 alt hesabinda izleniyor.",
        learning_rule_source_summary: "Bu oneride 3 onceki musavir karari kullanildi.",
        rule_interpretation: {
          source: "ai",
          provider: "openrouter",
          status: "ready",
          summary_tr: "Bu mükellefte Yurtiçi Kargo faturaları kargo gideri olarak önerilecek.",
          trigger_tr: "VKN 9860008925 / Yurtiçi Kargo alış faturası",
          action_tr: "Gider hesabı 760.03.010, cari 320.9860008925.",
          guardrail_tr: "İlk uygulamalarda müşavir kontrolü istenir.",
          confidence: 91,
          reason_codes: ["counterparty_tax_id_rule", "account_rule"],
        },
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
        line_decisions: [
          {
            canonical_line_id: "line-1",
            description: "Isitme cihazi",
            account_code: "600.20",
            decision_source: "ai",
          },
        ],
        deterministic_checks: ["balanced_entry"],
        export_gate_reason: "Export hazir.",
        document_validation_status: "expected_document",
        draft_status: "draft_ready",
        accountant_summary: "Fis taslagi hazir. Musavir kontrolunden sonra cikti listesine alinabilir.",
        accountant_explanation_tr: "Satis faturasi olarak yorumlandi; gelir 600.20 ve KDV 391.20 hesaplarina gider.",
        technical_details: {
          parse_notes: [],
          review_reason_codes: [],
          ai_trace: [
            {
              stage: "final_account",
              provider: "fake_llm",
              validation_status: "accepted",
              request_payload: {
                candidate_strategy: { stage: "final_account" },
              },
              provider_response: {
                suggested_account_code: "600.20",
              },
              accepted_result: {
                selected_account_code: "600.20",
              },
            },
          ],
        },
        ai_quality_scorecard: {
          static: { category: "Satis", confidence: 82 },
          ai: { provider: "static_rules", category: "Satis", confidence: 82 },
          final: {
            selected_account_code: "600.20",
            selected_counterparty_account: "120.01",
            direction: "sales",
          },
          accountant_final_decision: {
            selected_account_code: "600.20",
            selected_counterparty_account: "120.01",
            action: "approve",
          },
          quality_delta: {
            changed_fields: [],
            decision: "accepted",
            learning_candidate: false,
          },
        },
        draft_lines: [
          { account_code: "120.01", description: "Alici", debit: "120.00", credit: "0.00" },
          {
            account_code: "600.01",
            description: "Satis",
            debit: "0.00",
            credit: "100.00",
            vat_group_id: "KDV|S|20|",
            contributing_line_ids: ["line-1"],
            source_line_numbers: [1],
            allocated_amounts: [{ canonical_line_id: "line-1", amount: "100.00" }],
          },
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
    "X-Fisora-User-Id": "mukellef-user",
  });
  assert.deepEqual(backendAuthHeaders({ userId: "mukellef-user" }), {
    "X-Fisora-User-Id": "mukellef-user",
  });
  assert.deepEqual(backendAuthHeaders({}), {});
});

test("research profile summaries expose Turkish-safe fallback text", () => {
  assert.equal(
    turkishResearchSummary({ summary_tr: "Türkçe özet hazır.", summary: "English summary." }),
    "Türkçe özet hazır.",
  );
  assert.equal(
    turkishResearchSummary({ summary: "English summary." }),
    "Kaynak özeti Türkçeye çevrilmemiş. Detay panelinde ham kaynak metni incelenebilir.",
  );
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
    onboardingAttachments: [
      {
        ref: "tax-cert-1",
        type: "tax_certificate",
        label: "Vergi levhasi",
        fileName: "vergi-levhasi.pdf",
        status: "stored",
        createdAt: "2026-06-06T09:00:00Z",
      },
      {
        ref: "chart-1",
        type: "chart_accounts",
        label: "Hesap plani",
        fileName: "hesap-plani.xlsx",
        status: "stored",
        createdAt: "2026-06-06T09:30:00Z",
      },
    ],
  });
  assert.equal(data.documents.length, 2);
  assert.equal(data.documents[0].id, "processed-1");
  assert.equal(data.documents[0].status, "export_ready");
  assert.equal(data.documents[0].intakeCategory, "sales_invoice");
  assert.equal(data.documents[0].draftLines.length, 3);
  assert.deepEqual(data.documents[0].draftLines[1].source_line_numbers, [1]);
  assert.equal(data.documents[0].draftLines[1].vat_group_id, "KDV|S|20|");
  assert.equal(data.documents[0].businessRelation, "core_business");
  assert.equal(data.documents[0].accountTreatment, "stock_or_cogs");
  assert.equal(data.documents[0].requiresAccountantReview, false);
  assert.equal(data.documents[0].aiGateReason, "cold_start_core_accounting_line");
  assert.equal(data.documents[0].aiProductIdentity, "Helix Force 200 RI isitme cihazi");
  assert.equal(data.documents[0].aiResearchRequested, false);
  assert.equal(data.documents[0].clientNaceCode, "477401");
  assert.deepEqual(data.documents[0].clientActivityTags, ["hearing_aid", "medical_retail", "retail_trade"]);
  assert.equal(data.documents[0].counterpartyTaxId, "2222222222");
  assert.equal(data.documents[0].counterpartyTitle, "Alici Hasta");
  assert.deepEqual(data.documents[0].decisionNarrative, {
    invoiceProductLine: "Cihaz satisi",
    fisoraInterpretation: "Isitme cihazi",
    businessRelation: "Faaliyetle dogrudan iliskili",
    accountCode: "600.20",
    accountName: "Yurt ici satislar yuzde 20",
    counterpartyMatch: "VKN birebir eslesti / 120.01 / Alici Hasta",
    confidenceLabel: "Yuksek",
    unresolvedInfo: "",
    readFacts: {
      "Fatura urun satiri": "Cihaz satisi",
      "Satici unvani": "Pilot Alici",
      "KDV orani": "%20",
      "Genel toplam": "120.00",
      "Tutar kontrolu": "Matrah + KDV toplamla uyumlu",
    },
  });
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
  assert.deepEqual(data.documents[0].ruleInterpretation, {
    source: "ai",
    provider: "openrouter",
    status: "ready",
    summaryTr: "Bu mükellefte Yurtiçi Kargo faturaları kargo gideri olarak önerilecek.",
    triggerTr: "VKN 9860008925 / Yurtiçi Kargo alış faturası",
    actionTr: "Gider hesabı 760.03.010, cari 320.9860008925.",
    guardrailTr: "İlk uygulamalarda müşavir kontrolü istenir.",
    confidence: 91,
    reasonCodes: ["counterparty_tax_id_rule", "account_rule"],
  });
  assert.equal(data.documents[0].originalDocumentRef, "processed-1");
  assert.equal(data.documents[0].draftStatus, "draft_ready");
  assert.deepEqual(data.documents[0].chartAccounts.map((account) => [account.code, account.name]), [
    ["191.01.020", "Indirilecek KDV %20"],
    ["320.B04", "Rexton Medikal"],
    ["770.01", "Genel gider"],
  ]);
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
    ai_trace: [
      {
        stage: "final_account",
        provider: "fake_llm",
        validation_status: "accepted",
        request_payload: {
          candidate_strategy: { stage: "final_account" },
        },
        provider_response: {
          suggested_account_code: "600.20",
        },
        accepted_result: {
          selected_account_code: "600.20",
        },
      },
    ],
  });
  assert.deepEqual(data.documents[0].lineDecisions, [
    {
      canonical_line_id: "line-1",
      description: "Isitme cihazi",
      account_code: "600.20",
      decision_source: "ai",
    },
  ]);
  assert.deepEqual(data.documents[0].aiQualityScorecard.final, {
    selected_account_code: "600.20",
    selected_counterparty_account: "120.01",
    direction: "sales",
  });
  assert.deepEqual(data.documents[0].aiQualityScorecard.quality_delta, {
    changed_fields: [],
    decision: "accepted",
    learning_candidate: false,
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

test("processed backend documents keep upload stamp and expose direction conflict separately", () => {
  const workspace = {
    client: clientRecord,
    portal_users: workspaceRecord.portal_users,
    uploaded_documents: [
      {
        client_id: "client-1",
        document_ref: "sales-upload-detected-purchase",
        original_file_name: "istisna-sales-upload.pdf",
        content_type: "application/pdf",
        document_type: "invoice",
        intake_category: "sales_invoice",
        period: "2026-05",
        status: "stored",
        uploaded_by: "mukellef-user",
        created_at: "2026-06-07T10:00:00Z",
      },
    ],
    documents: [
      {
        client_id: "client-1",
        document_ref: "sales-upload-detected-purchase",
        export_status: "review_required",
        result: {
          file_name: "istisna-sales-upload.pdf",
          invoice_type: "ISTISNA",
          accounting_direction: "purchase",
          direction_conflict: {
            status: "needs_review",
            intake_direction: "sales",
            detected_direction: "purchase",
            confidence: 95,
            evidence: ["client_tax_id_matches_recipient"],
            question_tr: "Bu belge Satıştan yüklendi; sistem mükellef açısından Alış olarak tespit etti. Alış yönüne geçirilsin mi?",
          },
        },
      },
    ],
  };

  const data = normalizeBackendWorkspaces({
    clients: [clientRecord],
    workspaces: [workspace],
    source: "test",
  });

  assert.equal(data.documents[0].intakeCategory, "sales_invoice");
  assert.equal(data.documents[0].accountingDirection, "purchase");
  assert.deepEqual(data.documents[0].directionConflict, {
    status: "needs_review",
    intakeDirection: "sales",
    detectedDirection: "purchase",
    confidence: 95,
    evidence: ["client_tax_id_matches_recipient"],
    questionTr: "Bu belge Satıştan yüklendi; sistem mükellef açısından Alış olarak tespit etti. Alış yönüne geçirilsin mi?",
  });
});

test("processed backend documents expose AI retry without promoting static fallback as suggestion", () => {
  const workspace = {
    client: clientRecord,
    portal_users: workspaceRecord.portal_users,
    uploaded_documents: [],
    documents: [
      {
        client_id: "client-1",
        document_ref: "ai-retry-doc",
        export_status: "review_required",
        result: {
          file_name: "belirsiz-alis.xml",
          invoice_type: "ALIS",
          accounting_direction: "purchase",
          provider_hint: "Bilinmeyen Tedarik",
          product_line_hint: "ZX Pilot Kalem",
          ai_resolution_status: "ai_retry_required",
          ai_retry_reason: "ai_account_missing",
          ai_suggested_account_code: "",
          selected_expense_account: "",
          static_fallback_account: "770.01",
          static_fallback_suppressed: true,
          accountant_summary: "AI ajani mesgul veya karar tamamlanamadi; belge tekrar denenecek.",
          technical_details: {
            ai_resolution_status: "ai_retry_required",
            static_fallback_account: "770.01",
            static_fallback_suppressed: true,
          },
        },
      },
    ],
    document_pipeline_events: [
      {
        document_ref: "ai-retry-doc",
        step: "ai_retry_required",
        status: "warning",
        message_tr: "AI ajani mesgul veya karar tamamlanamadi; belge tekrar denenecek.",
        debug_code: "ai_retry_required",
      },
    ],
  };

  const data = normalizeBackendWorkspaces({
    clients: [clientRecord],
    workspaces: [workspace],
    source: "test",
  });

  const document = data.documents[0];
  assert.equal(document.aiResolutionStatus, "ai_retry_required");
  assert.equal(document.aiRetryReason, "ai_account_missing");
  assert.equal(document.aiSuggestedAccountCode, "");
  assert.equal(document.selectedExpenseAccount, "-");
  assert.equal(document.staticFallbackAccount, "770.01");
  assert.equal(document.staticFallbackSuppressed, true);
  assert.deepEqual(document.pipelineEvents.map((event) => event.step), ["ai_retry_required"]);
});

test("processed backend documents preserve AI correction draft status and attempted account evidence", () => {
  const workspace = {
    client: clientRecord,
    portal_users: workspaceRecord.portal_users,
    uploaded_documents: [],
    documents: [{
      client_id: "client-1",
      document_ref: "ai-correction-doc",
      export_status: "review_required",
      result: {
        file_name: "duzeltme-gerekli.xml",
        invoice_type: "ALIS",
        accounting_direction: "purchase",
        ai_resolution_status: "ai_correction_required",
        ai_retry_reason: "selected_account_not_in_candidates",
        ai_attempted_account_code: "770.99",
        draft_status: "ai_correction_required",
        draft_lines: [],
        selected_expense_account: "",
        accountant_summary: "AI hesap karari tamamlanamadi; duzeltme gerekli.",
      },
    }],
    document_pipeline_events: [{
      document_ref: "ai-correction-doc",
      step: "ai_correction_required",
      status: "warning",
      message_tr: "AI hesap karari tamamlanamadi; duzeltme gerekli.",
      debug_code: "ai_correction_required",
    }],
  };

  const data = normalizeBackendWorkspaces({
    clients: [clientRecord],
    workspaces: [workspace],
    source: "test",
  });

  const document = data.documents[0];
  assert.equal(document.aiResolutionStatus, "ai_correction_required");
  assert.equal(document.aiAttemptedAccountCode, "770.99");
  assert.equal(document.draftStatus, "ai_correction_required");
  assert.deepEqual(document.pipelineEvents.map((event) => event.step), ["ai_correction_required"]);
});

test("fetchBackendPilotData loads clients then each allowed review workspace with a longer backend timeout", async () => {
  const requests = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    if (url.endsWith("/phase0/store/clients")) {
      return {
        ok: true,
        json: async () => ({ clients: [clientRecord] }),
      };
    }
    if (url.endsWith("/phase0/store/workspace/client-1?view=review")) {
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
      "http://localhost:8000/phase0/store/workspace/client-1?view=review",
    ],
  );
  assert.deepEqual(requests[0].init.headers, { "X-Fisora-User-Id": "mukellef-user" });
  assert.deepEqual(requests[1].init.headers, { "X-Fisora-User-Id": "mukellef-user" });
  assert.equal(requests[0].init.signal.aborted, false);
  assert.equal(requests[1].init.signal.aborted, false);
});

test("normalizeBackendWorkspaces exposes QNB status evidence on a processed document", () => {
  const workspace = structuredClone(workspaceRecord);
  workspace.uploaded_documents.push({
    document_ref: "processed-1",
    content_type: "application/xml",
    source_provider: "qnb_esolutions",
    source_qnb_normalized_status: "rejected",
    source_qnb_status_checked_at: "2026-07-11T12:00:00+00:00",
    source_qnb_status_changed: true,
    source_qnb_status_detail: "Ticari fatura reddedildi",
    qnb_review_required: true,
  });
  const data = normalizeBackendWorkspaces({ clients: [clientRecord], workspaces: [workspace] });
  const document = data.documents.find((item) => item.id === "processed-1");

  assert.equal(document.qnbStatus, "rejected");
  assert.equal(document.qnbStatusCheckedAt, "2026-07-11T12:00:00+00:00");
  assert.equal(document.qnbStatusChanged, true);
  assert.equal(document.qnbReviewRequired, true);
  assert.equal(document.qnbStatusDetail, "Ticari fatura reddedildi");
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
  assert.deepEqual(requests[0].init.headers, {
    "X-Fisora-Session": "session-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
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


test("active processing snapshot replaces a stale final result for the same document", () => {
  const progressiveWorkspace = structuredClone(workspaceRecord);
  progressiveWorkspace.processing_jobs.push({
    id: "job-reprocess-2",
    document_ref: "processed-1",
    status: "processing",
    attempt_count: 2,
    updated_at: "2026-06-08T10:00:00Z",
    processing_snapshot: {
      attempt_id: "attempt-2",
      attempt_count: 2,
      current_stage: "final",
      stages: {
        reader: { status: "completed", elapsed_ms: 5100 },
        planner: { status: "completed", elapsed_ms: 1200 },
        final: { status: "processing", elapsed_ms: 0 },
      },
      reader: {
        document_header: [{ label: "FATURA TARİHİ", value: "2026-06-08" }],
        printed_summary_lines: [{ label: "ÖDENECEK TOPLAM", value: "245,50" }],
        invoice_table_rows: [{
          source_position: "1",
          source_text: "Danışmanlık 245,50",
          description: "Danışmanlık",
          ui_amount: "245,50",
          ui_amount_label: "Tutar",
          ui_amount_basis: "line_total_inc_tax",
          ui_role: "posting_candidate",
        }],
      },
      planner: {
        accounting_direction: "purchase",
        counterparty_name: "Yeni Tedarikçi A.Ş.",
        counterparty_identifier: "9999999999",
        counterparty_match: "none",
        counterparty_account_code: "",
      },
    },
  });

  const data = normalizeBackendWorkspaces({ clients: [clientRecord], workspaces: [progressiveWorkspace] });
  const document = data.documents.find((item) => item.id === "processed-1");
  assert.equal(document.status, "processing");
  assert.equal(document.amount, "245,50");
  assert.equal(document.accountingDirection, "purchase");
  assert.equal(document.counterpartyTitle, "Yeni Tedarikçi A.Ş.");
  assert.equal(document.sourceReviewRows.length, 1);
  assert.equal(document.draftLines.length, 0);
  assert.equal(document.processingStages.attemptId, "attempt-2");
  assert.equal(document.processingStages.final.status, "processing");
});

test("fetchDocumentProgress loads only the selected document job", async () => {
  const requests = [];
  const fetchImpl = async (url, init = {}) => {
    requests.push({ url, init });
    return { ok: true, json: async () => ({ terminal: false, job: { id: "job-1", status: "processing" } }) };
  };

  const payload = await fetchDocumentProgress({
    apiBaseUrl: "http://localhost:8000/",
    clientId: "client-1",
    documentRef: "doc / 1",
    fetchImpl,
    sessionToken: "session-1",
    userId: "mali-musavir",
  });
  assert.equal(payload.job.id, "job-1");
  assert.equal(requests[0].url, "http://localhost:8000/phase0/store/workspace/client-1/documents/doc%20%2F%201/progress");
  assert.deepEqual(requests[0].init.headers, {
    "X-Fisora-Session": "session-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
});

test("failed reprocess keeps the stale final result hidden", () => {
  const failedWorkspace = structuredClone(workspaceRecord);
  failedWorkspace.processing_jobs.push({
    id: "job-failed-2",
    document_ref: "processed-1",
    status: "failed",
    attempt_count: 2,
    updated_at: "2026-06-08T11:00:00Z",
    error_message: "reader_failed",
    processing_snapshot: {
      attempt_id: "attempt-failed-2",
      stages: {
        reader: { status: "failed", elapsed_ms: 2100 },
        planner: { status: "pending", elapsed_ms: 0 },
        final: { status: "pending", elapsed_ms: 0 },
      },
    },
  });
  const data = normalizeBackendWorkspaces({ clients: [clientRecord], workspaces: [failedWorkspace] });
  const document = data.documents.find((item) => item.id === "processed-1");
  assert.equal(document.status, "review_required");
  assert.equal(document.draftStatus, "processing");
  assert.equal(document.draftLines.length, 0);
  assert.equal(document.processingStages.reader.status, "failed");
});
