const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildClientBootstrapPayload,
  buildClientOnboardingPackagePayload,
  buildPortalUserBootstrapPayload,
  createClientOnboardingPackage,
  createPortalInvite,
  ensureUploadWorkspace,
  loginWithPassword,
  pickUploadUser,
  requestStatementAiSuggestions,
  resolveApiBaseUrl,
  setPortalPassword,
  storeReviewDecision,
  uploadChartAccountsToBackend,
  uploadDocumentToBackend,
} = require("./upload-api.js");

class CapturingFormData {
  constructor() {
    this.fields = [];
  }

  append(name, value) {
    this.fields.push([name, value]);
  }
}

test("resolveApiBaseUrl targets the matching backend host", () => {
  assert.equal(resolveApiBaseUrl("http://localhost:3000"), "http://localhost:8000");
  assert.equal(resolveApiBaseUrl("http://127.0.0.1:3000/client"), "http://127.0.0.1:8000");
  assert.equal(resolveApiBaseUrl("http://192.168.1.101:3000/client"), "http://192.168.1.101:8000");
});

test("resolveApiBaseUrl honors an explicit configured base URL", () => {
  assert.equal(resolveApiBaseUrl("http://192.168.1.101:3000", " http://api.local:9000/ "), "http://api.local:9000");
});

test("pickUploadUser uses the client session or selected client's portal user", () => {
  assert.equal(
    pickUploadUser({
      session: { userId: " mukellef-user ", role: "client_user" },
      selectedClient: { portalUserId: "selected-user" },
    }),
    "mukellef-user",
  );
  assert.equal(
    pickUploadUser({
      session: { userId: "mali-musavir", role: "accountant" },
      selectedClient: { portalUserId: "selected-user" },
    }),
    "selected-user",
  );
});

test("bootstrap payloads keep the selected client and upload user aligned", () => {
  assert.deepEqual(
    buildClientBootstrapPayload({
      clientId: "client-1",
      clientName: "Demo Client",
      taxId: "pilot-local",
    }),
    {
      client_id: "client-1",
      title: "Demo Client",
      tax_id: "",
      has_chart_accounts: true,
    },
  );
  assert.deepEqual(
    buildPortalUserBootstrapPayload({
      userId: "client-user",
      displayName: "Client User",
      clientId: "client-1",
    }),
    {
      user_id: "client-user",
      display_name: "Client User",
      role: "client_user",
      allowed_client_ids: ["client-1"],
    },
  );
});

test("ensureUploadWorkspace upserts client then portal user", async () => {
  const requests = [];
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    return { ok: true, json: async () => ({ ok: true }) };
  };

  await ensureUploadWorkspace({
    apiBaseUrl: "http://localhost:8000",
    client: { clientId: "client-1", clientName: "Demo Client", taxId: "123" },
    userId: "client-user",
    displayName: "Client User",
    fetchImpl,
  });

  assert.equal(requests[0].url, "http://localhost:8000/phase0/store/client");
  assert.equal(requests[1].url, "http://localhost:8000/phase0/store/portal-user");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    client_id: "client-1",
    title: "Demo Client",
    tax_id: "123",
    has_chart_accounts: true,
  });
  assert.deepEqual(JSON.parse(requests[1].init.body), {
    user_id: "client-user",
    display_name: "Client User",
    role: "client_user",
    allowed_client_ids: ["client-1"],
  });
});

test("buildClientOnboardingPackagePayload builds a backend onboarding package", () => {
  assert.deepEqual(
    buildClientOnboardingPackagePayload({
      title: "Yeni İşitme Merkezi",
      taxId: "1234567890",
      activityDescription: "İşitme cihazı satış ve servis",
      naceCode: "47.74",
      portalDisplayName: "Yeni İşitme Kullanıcısı",
    }),
    {
      client: {
        client_id: "yeni-isitme-merkezi",
        title: "Yeni İşitme Merkezi",
        tax_id: "1234567890",
        activity_description: "İşitme cihazı satış ve servis",
        nace_code: "47.74",
        workplace_addresses: [],
        has_chart_accounts: true,
      },
      chart_accounts: [],
      portal_users: [
        {
          user_id: "yeni-isitme-merkezi-user",
          display_name: "Yeni İşitme Kullanıcısı",
          role: "client_user",
          allowed_client_ids: ["yeni-isitme-merkezi"],
        },
      ],
    },
  );
});

test("createClientOnboardingPackage posts to the backend package endpoint", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ workspace: { client: { client_id: "client-1" } } }) };
  };

  const result = await createClientOnboardingPackage({
    apiBaseUrl: "http://localhost:8000",
    client: { clientId: "client-1", title: "Client One", portalUserId: "client-one-user" },
    userId: "mali-musavir",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/client-onboarding-package");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.equal(JSON.parse(request.init.body).client.client_id, "client-1");
  assert.deepEqual(result, { workspace: { client: { client_id: "client-1" } } });
});

test("uploadDocumentToBackend posts the selected intake category as multipart data", async () => {
  let request;
  const file = { name: "satis.pdf" };
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ document_ref: "doc-1" }) };
  };

  const result = await uploadDocumentToBackend({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "client-user",
    uploadedBy: "Client User",
    documentType: "invoice",
    intakeCategory: "sales_invoice",
    file,
    fetchImpl,
    FormDataCtor: CapturingFormData,
  });

  assert.deepEqual(result, { document_ref: "doc-1" });
  assert.equal(request.url, "http://localhost:8000/phase0/store/document-upload-multipart");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, { "X-Fisora-User-Id": "client-user" });
  assert.deepEqual(
    request.init.body.fields.map(([key, value]) => [key, value && value.name ? value.name : value]),
    [
      ["client_id", "client-1"],
      ["document_type", "invoice"],
      ["intake_category", "sales_invoice"],
      ["uploaded_by", "Client User"],
      ["uploaded_by_user_id", "client-user"],
      ["retention_policy_days", "90"],
      ["file", "satis.pdf"],
    ],
  );
});

test("uploadChartAccountsToBackend posts chart account files to parser endpoint", async () => {
  let request;
  const file = { name: "hesap-plani.csv" };
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ client_id: "client-1", account_count: 2 }) };
  };

  const result = await uploadChartAccountsToBackend({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    file,
    fetchImpl,
    FormDataCtor: CapturingFormData,
  });

  assert.deepEqual(result, { client_id: "client-1", account_count: 2 });
  assert.equal(request.url, "http://localhost:8000/phase0/store/chart-accounts/upload");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, { "X-Fisora-User-Id": "mali-musavir" });
  assert.deepEqual(
    request.init.body.fields.map(([key, value]) => [key, value && value.name ? value.name : value]),
    [
      ["client_id", "client-1"],
      ["file", "hesap-plani.csv"],
    ],
  );
});

test("loginWithPassword posts credentials and returns a backend session", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return {
      ok: true,
      json: async () => ({
        session_token: "session-token-1",
        session: { user_id: "mali-musavir", expires_at: "2026-06-06T22:00:00+00:00" },
      }),
    };
  };

  const result = await loginWithPassword({
    apiBaseUrl: "http://localhost:8000",
    userId: "mali-musavir",
    password: "GizliSifre123",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/auth/login");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(JSON.parse(request.init.body), {
    user_id: "mali-musavir",
    password: "GizliSifre123",
    ttl_hours: 12,
  });
  assert.equal(result.sessionToken, "session-token-1");
  assert.equal(result.userId, "mali-musavir");
});

test("createPortalInvite posts invite payload without sending email", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ invite_token: "invite-1" }) };
  };

  const result = await createPortalInvite({
    apiBaseUrl: "http://localhost:8000",
    userId: "client-user",
    displayName: "Client User",
    clientId: "client-1",
    invitedBy: "mali-musavir",
    sessionToken: "session-token-1",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/auth/invite");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    user_id: "client-user",
    display_name: "Client User",
    role: "client_user",
    allowed_client_ids: ["client-1"],
    invited_by: "mali-musavir",
    ttl_hours: 48,
  });
  assert.deepEqual(result, { invite_token: "invite-1" });
});

test("setPortalPassword posts password bootstrap payload", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ has_password: true }) };
  };

  const result = await setPortalPassword({
    apiBaseUrl: "http://localhost:8000",
    userId: "client-user",
    password: "GizliSifre123",
    userHeader: "mali-musavir",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/auth/password");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    user_id: "client-user",
    password: "GizliSifre123",
  });
  assert.deepEqual(result, { has_password: true });
});

test("requestStatementAiSuggestions posts structured statement lines", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return {
      ok: true,
      json: async () => ({
        suggestions: [{ line_no: 2, transaction_type: "unknown", export_allowed: false }],
        ai_used_count: 1,
      }),
    };
  };

  const result = await requestStatementAiSuggestions({
    apiBaseUrl: "http://localhost:8000/",
    clientId: "client-1",
    lines: [
      {
        line_no: 2,
        transaction_date: "2026-05-02",
        description: "Bilinmeyen EFT",
        amount: "1250.00",
        direction: "out",
        suggested_account_code: "320.01",
        transaction_type: "unknown",
        confidence: 45,
        risk_flags: ["counterparty_not_found"],
      },
    ],
    aiPolicy: { enabled: true, max_provider_calls: 2 },
    providerName: "openai",
    providerPayloads: [{ transaction_type: "eft", suggested_account_code: "320.01.040" }],
    sessionToken: "session-token-1",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/statement/ai-suggestions");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    client_id: "client-1",
    lines: [
      {
        line_no: 2,
        transaction_date: "2026-05-02",
        description: "Bilinmeyen EFT",
        amount: "1250.00",
        direction: "out",
        balance_after: "",
        counterparty_name: "",
        tax_id: "",
        iban: "",
        suggested_account_code: "320.01",
        transaction_type: "unknown",
        confidence: 45,
        risk_flags: ["counterparty_not_found"],
        review_reason: "",
      },
    ],
    ai_policy: {
      enabled: true,
      max_provider_calls: 2,
    },
    provider_name: "openai",
    provider_payloads: [{ transaction_type: "eft", suggested_account_code: "320.01.040" }],
  });
  assert.deepEqual(result, {
    suggestions: [{ line_no: 2, transaction_type: "unknown", export_allowed: false }],
    ai_used_count: 1,
  });
});

test("storeReviewDecision posts statement line accountant decisions", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ updated_at: "2026-06-06T10:00:00" }) };
  };

  const result = await storeReviewDecision({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    documentRef: "mayis-banka-ekstresi.xlsx",
    action: "approve_with_changes",
    reviewer: "mali-musavir",
    statementLineNo: 3,
    correctedCounterpartyCode: "320.01.040",
    correctedAccountCode: "",
    reason: "Cari müşavir tarafından seçildi.",
    sessionToken: "session-token-1",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/review-decision");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    client_id: "client-1",
    decision: {
      document_ref: "mayis-banka-ekstresi.xlsx",
      action: "approve_with_changes",
      reviewer: "mali-musavir",
      corrected_account_code: "",
      corrected_counterparty_code: "320.01.040",
      category: "",
      reason: "Cari müşavir tarafından seçildi.",
      apply_to_similar: false,
      prior_consistent_approval_count: 0,
      statement_line_no: 3,
    },
  });
  assert.deepEqual(result, { updated_at: "2026-06-06T10:00:00" });
});

test("storeReviewDecision marks one-click rule requests as apply-to-similar", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ learning_event: { scope: "client_rule" } }) };
  };

  await storeReviewDecision({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    documentRef: "kolaysoft.pdf",
    action: "suggest_for_similar",
    reviewer: "mali-musavir",
    correctedAccountCode: "770.05",
    category: "software_service",
    reason: "KolaySoft e-fatura hizmeti bu alt hesaba alinsin.",
    applyToSimilar: true,
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/review-decision");
  assert.equal(JSON.parse(request.init.body).decision.apply_to_similar, true);
  assert.equal(JSON.parse(request.init.body).decision.action, "suggest_for_similar");
});
