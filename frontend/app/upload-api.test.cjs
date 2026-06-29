const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildClientBootstrapPayload,
  buildClientOnboardingPackagePayload,
  buildTaxCertificateParseStatus,
  buildPortalUserBootstrapPayload,
  createClientOnboardingPackage,
  createPortalInvite,
  deleteClientDocuments,
  ensureUploadWorkspace,
  loginWithPassword,
  sessionAuthErrorMessage,
  pickUploadUser,
  parseChartAccountsFromBackend,
  parseTaxCertificateFromBackend,
  requestStatementAiSuggestions,
  reprocessClient,
  reprocessDocument,
  resetTestData,
  resolveApiBaseUrl,
  setPortalPassword,
  storeReviewDecision,
  updateClientPortalAccess,
  uploadChartAccountsToBackend,
  uploadDocumentToBackend,
  uploadDocumentsToBackend,
  uploadTaxCertificateToBackend,
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
      activityTags: ["hearing_aid", "medical_retail", "retail_trade"],
      activityProfile: {
        primary_activity: "hearing_aid_sales_service",
        display_label: "Isitme cihazi satis/servis",
        confidence: 88,
        needs_review: false,
      },
      portalDisplayName: "Yeni İşitme Kullanıcısı",
    }),
    {
      client: {
        client_id: "yeni-isitme-merkezi",
        title: "Yeni İşitme Merkezi",
        tax_id: "1234567890",
        tckn: "",
        vkn: "",
        identity_type: "",
        tax_identifier: "1234567890",
        legal_name: "",
        trade_name: "",
        display_title: "Yeni İşitme Merkezi",
        tax_office: "",
        activity_description: "İşitme cihazı satış ve servis",
        nace_code: "47.74",
        activity_tags: ["hearing_aid", "medical_retail", "retail_trade"],
        activity_profile: {
          primary_activity: "hearing_aid_sales_service",
          display_label: "Isitme cihazi satis/servis",
          confidence: 88,
          needs_review: false,
        },
        workplace_addresses: [],
        has_chart_accounts: false,
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

test("buildClientOnboardingPackagePayload preserves extracted workplace addresses", () => {
  const payload = buildClientOnboardingPackagePayload({
    title: "Yeni Isitme Merkezi",
    workplaceAddresses: ["Meclis Mah. Ataturk Cad. No: 10"],
  });

  assert.deepEqual(payload.client.workplace_addresses, ["Meclis Mah. Ataturk Cad. No: 10"]);
});

test("buildClientOnboardingPackagePayload preserves separated tax identity fields", () => {
  const payload = buildClientOnboardingPackagePayload({
    title: "Omer Yagci",
    taxId: "9270740926",
    tckn: "45661316282",
    vkn: "9270740926",
    identityType: "tckn_vkn",
    taxIdentifier: "9270740926",
    legalName: "Omer Yagci",
    tradeName: "",
    displayTitle: "Omer Yagci",
    taxOffice: "Kucukyali",
  });

  assert.equal(payload.client.tax_id, "9270740926");
  assert.equal(payload.client.tckn, "45661316282");
  assert.equal(payload.client.vkn, "9270740926");
  assert.equal(payload.client.identity_type, "tckn_vkn");
  assert.equal(payload.client.tax_identifier, "9270740926");
  assert.equal(payload.client.legal_name, "Omer Yagci");
  assert.equal(payload.client.trade_name, "");
  assert.equal(payload.client.display_title, "Omer Yagci");
  assert.equal(payload.client.tax_office, "Kucukyali");
});

test("buildTaxCertificateParseStatus warns when TCKN is read but VKN is missing", () => {
  const message = buildTaxCertificateParseStatus({
    filledFields: ["unvan", "TCKN"],
    confidence: 82,
    profileSummary: "",
    tckn: "45661316282",
    vkn: "",
  });

  assert.match(message, /VKN okunamadı/);
  assert.match(message, /kontrol edin/);
});

test("buildClientOnboardingPackagePayload includes parsed chart accounts for final onboarding", () => {
  const payload = buildClientOnboardingPackagePayload({
    title: "Yeni Isitme Merkezi",
    chartAccounts: [
      {
        raw_account_code: "320.01",
        normalized_account_code: "320.01",
        account_name: "Rexton Medikal",
        is_detail_account: true,
      },
    ],
  });

  assert.equal(payload.client.has_chart_accounts, true);
  assert.deepEqual(payload.chart_accounts, [
    {
      raw_account_code: "320.01",
      normalized_account_code: "320.01",
      account_name: "Rexton Medikal",
      is_detail_account: true,
    },
  ]);
});

test("parseChartAccountsFromBackend posts a chart file without requiring an existing client", async () => {
  let request;
  const file = { name: "hesap-plani.csv" };
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ account_count: 1, accounts: [{ normalized_account_code: "320.01" }] }) };
  };

  const result = await parseChartAccountsFromBackend({
    apiBaseUrl: "http://localhost:8000",
    userId: "mali-musavir",
    file,
    fetchImpl,
    FormDataCtor: CapturingFormData,
  });

  assert.deepEqual(result, { account_count: 1, accounts: [{ normalized_account_code: "320.01" }] });
  assert.equal(request.url, "http://localhost:8000/phase0/chart-accounts/parse");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, { "X-Fisora-User-Id": "mali-musavir" });
  assert.deepEqual(
    request.init.body.fields.map(([key, value]) => [key, value && value.name ? value.name : value]),
    [["file", "hesap-plani.csv"]],
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

test("createClientOnboardingPackage keeps the mock user fallback when a session token is present", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ workspace: { client: { client_id: "client-1" } } }) };
  };

  await createClientOnboardingPackage({
    apiBaseUrl: "http://localhost:8000",
    client: { clientId: "client-1", title: "Client One", portalUserId: "client-one-user" },
    sessionToken: "stale-session-token",
    userId: "mali-musavir",
    fetchImpl,
  });

  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "stale-session-token",
    "X-Fisora-User-Id": "mali-musavir",
  });
});

test("parseTaxCertificateFromBackend posts the selected certificate for extraction", async () => {
  let request;
  const file = { name: "vergi-levhasi.pdf" };
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return {
      ok: true,
      json: async () => ({
        title: "IBRAHIM DEGERLI",
        tax_id: "1234567890",
        activity_description: "Isitme cihazi satisi",
        nace_code: "477401",
        workplace_addresses: ["Meclis Mah."],
      }),
    };
  };

  const result = await parseTaxCertificateFromBackend({
    apiBaseUrl: "http://localhost:8000",
    userId: "mali-musavir",
    file,
    fetchImpl,
    FormDataCtor: CapturingFormData,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/tax-certificate/parse");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, { "X-Fisora-User-Id": "mali-musavir" });
  assert.deepEqual(
    request.init.body.fields.map(([key, value]) => [key, value && value.name ? value.name : value]),
    [["file", "vergi-levhasi.pdf"]],
  );
  assert.equal(result.title, "IBRAHIM DEGERLI");
  assert.equal(result.tax_id, "1234567890");
  assert.deepEqual(result.workplace_addresses, ["Meclis Mah."]);
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
    period: "2026-05",
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
      ["period", "2026-05"],
      ["uploaded_by", "Client User"],
      ["uploaded_by_user_id", "client-user"],
      ["retention_policy_days", "90"],
      ["file", "satis.pdf"],
    ],
  );
});

test("uploadTaxCertificateToBackend stores the certificate outside the processing queue", async () => {
  let request;
  const file = { name: "vergi-levhasi.pdf" };
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ attachment_ref: "tax-cert-1" }) };
  };

  const result = await uploadTaxCertificateToBackend({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    uploadedBy: "Mali Musavir",
    file,
    fetchImpl,
    FormDataCtor: CapturingFormData,
  });

  assert.deepEqual(result, { attachment_ref: "tax-cert-1" });
  assert.equal(request.url, "http://localhost:8000/phase0/store/client-onboarding-attachment");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, { "X-Fisora-User-Id": "mali-musavir" });
  assert.deepEqual(
    request.init.body.fields.map(([key, value]) => [key, value && value.name ? value.name : value]),
    [
      ["client_id", "client-1"],
      ["attachment_type", "tax_certificate"],
      ["uploaded_by", "Mali Musavir"],
      ["uploaded_by_user_id", "mali-musavir"],
      ["retention_policy_days", "365"],
      ["file", "vergi-levhasi.pdf"],
    ],
  );
});

test("uploadDocumentsToBackend uploads multiple files sequentially with the same intake metadata", async () => {
  const requests = [];
  const files = [{ name: "fatura-1.pdf" }, { name: "fatura-2.pdf" }];
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    return { ok: true, json: async () => ({ document_ref: `doc-${requests.length}` }) };
  };

  const results = await uploadDocumentsToBackend({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "client-user",
    uploadedBy: "Client User",
    documentType: "invoice",
    intakeCategory: "purchase_invoice",
    files,
    fetchImpl,
    FormDataCtor: CapturingFormData,
  });

  assert.deepEqual(results, [
    { fileName: "fatura-1.pdf", ok: true, payload: { document_ref: "doc-1" } },
    { fileName: "fatura-2.pdf", ok: true, payload: { document_ref: "doc-2" } },
  ]);
  assert.deepEqual(
    requests.map((request) => request.init.body.fields.find(([key]) => key === "file")[1].name),
    ["fatura-1.pdf", "fatura-2.pdf"],
  );
  assert.deepEqual(
    requests.map((request) => request.init.body.fields.find(([key]) => key === "intake_category")[1]),
    ["purchase_invoice", "purchase_invoice"],
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

test("sessionAuthErrorMessage translates stale backend sessions into a re-login prompt", () => {
  assert.equal(
    sessionAuthErrorMessage('{"valid":false,"reason":"session_not_found"}'),
    "Oturum bulunamadı. Çıkış yapıp şifreyle tekrar giriş yapın.",
  );
  assert.equal(
    sessionAuthErrorMessage('{"valid":false,"reason":"session_expired"}'),
    "Oturum süresi doldu. Çıkış yapıp şifreyle tekrar giriş yapın.",
  );
  assert.equal(sessionAuthErrorMessage("plain backend error"), "");
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

test("updateClientPortalAccess posts single-login portal changes", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ portal_user: { user_id: "new-user" }, old_user_removed: true }) };
  };

  const result = await updateClientPortalAccess({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    oldUserId: "old-user",
    newUserId: "new-user",
    displayName: "New User",
    password: "YeniSifre123",
    sessionToken: "session-token-1",
    userHeader: "mali-musavir",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/client-portal-access");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    client_id: "client-1",
    old_user_id: "old-user",
    new_user_id: "new-user",
    display_name: "New User",
    password: "YeniSifre123",
  });
  assert.deepEqual(result, { portal_user: { user_id: "new-user" }, old_user_removed: true });
});

test("deleteClientDocuments posts confirmed bulk document deletion", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ deleted_count: 2, deleted_document_refs: ["doc-1", "doc-2"] }) };
  };

  const result = await deleteClientDocuments({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    documentRefs: ["doc-1", "doc-2"],
    deleteFiles: true,
    sessionToken: "session-token-1",
    userHeader: "mali-musavir",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/documents/delete");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    client_id: "client-1",
    document_refs: ["doc-1", "doc-2"],
    confirmed: true,
    delete_files: true,
  });
  assert.deepEqual(result, { deleted_count: 2, deleted_document_refs: ["doc-1", "doc-2"] });
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
    "X-Fisora-User-Id": "mali-musavir",
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
      accountant_note: "",
      rule_instruction: "",
      apply_to_similar: false,
      prior_consistent_approval_count: 0,
      statement_line_no: 3,
    },
  });
  assert.deepEqual(result, { updated_at: "2026-06-06T10:00:00" });
});

test("storeReviewDecision includes manual journal draft lines when provided", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ updated_at: "2026-06-06T10:00:00" }) };
  };

  await storeReviewDecision({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    documentRef: "fatura.pdf",
    action: "approve_with_changes",
    reviewer: "mali-musavir",
    draftLines: [
      { account_code: "770.01", description: "Gider", debit: "100.00", credit: "0.00" },
      { account_code: "320.01.001", description: "Cari", debit: "0.00", credit: "100.00" },
    ],
    fetchImpl,
  });

  assert.deepEqual(JSON.parse(request.init.body).decision.draft_lines, [
    { account_code: "770.01", description: "Gider", debit: "100.00", credit: "0.00" },
    { account_code: "320.01.001", description: "Cari", debit: "0.00", credit: "100.00" },
  ]);
});

test("storeReviewDecision binds draft corrections to accountant note and rule instruction", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ learning_event: { scope: "client_rule" } }) };
  };

  await storeReviewDecision({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    documentRef: "rexton.pdf",
    action: "approve_with_changes",
    reviewer: "mali-musavir",
    correctedAccountCode: "153.01",
    reason: "Fiş satırını stok hesabına aldım.",
    accountantNote: "Rexton RLi 20 işitme cihazıdır; stok olarak izlenmeli.",
    ruleInstruction: "Benzer Rexton RLi 20 satırlarında stok hesabını öner.",
    draftLines: [
      { account_code: "153.01", description: "Cihaz stoku", debit: "100.00", credit: "0.00" },
      { account_code: "320.01", description: "Satıcı", debit: "0.00", credit: "100.00" },
    ],
    fetchImpl,
  });

  const decision = JSON.parse(request.init.body).decision;
  assert.equal(decision.reason, "Fiş satırını stok hesabına aldım.");
  assert.equal(decision.accountant_note, "Rexton RLi 20 işitme cihazıdır; stok olarak izlenmeli.");
  assert.equal(decision.rule_instruction, "Benzer Rexton RLi 20 satırlarında stok hesabını öner.");
  assert.deepEqual(decision.draft_lines.map((line) => line.account_code), ["153.01", "320.01"]);
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

test("reprocessDocument posts an existing document back to the processing queue", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ processing_job: { status: "queued" } }) };
  };

  const result = await reprocessDocument({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    documentRef: "fatura.pdf",
    userId: "mali-musavir",
    sessionToken: "session-token-1",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/document-reprocess");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    client_id: "client-1",
    document_ref: "fatura.pdf",
  });
  assert.deepEqual(result, { processing_job: { status: "queued" } });
});

test("reprocessClient posts selected client for immediate reprocessing", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return { ok: true, json: async () => ({ queued_document_count: 3, processing_summary: { completed_count: 3 } }) };
  };

  const result = await reprocessClient({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    sessionToken: "session-token-1",
    maxJobs: 25,
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/client-reprocess");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    client_id: "client-1",
    max_jobs: 25,
  });
  assert.equal(result.queued_document_count, 3);
});

test("resetTestData posts guarded accountant reset request", async () => {
  let request;
  const fetchImpl = async (url, init) => {
    request = { url, init };
    return {
      ok: true,
      json: async () => ({
        reset: true,
        deleted_client_count: 2,
        preserved_portal_user_count: 1,
      }),
    };
  };

  const result = await resetTestData({
    apiBaseUrl: "http://localhost:8000",
    confirmation: "TEMIZLE",
    userId: "mali-musavir",
    sessionToken: "session-token-1",
    fetchImpl,
  });

  assert.equal(request.url, "http://localhost:8000/phase0/store/admin/test-reset");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(request.init.headers, {
    "Content-Type": "application/json",
    "X-Fisora-Session": "session-token-1",
    "X-Fisora-User-Id": "mali-musavir",
  });
  assert.deepEqual(JSON.parse(request.init.body), {
    confirmation: "TEMIZLE",
    delete_files: true,
  });
  assert.deepEqual(result, {
    reset: true,
    deleted_client_count: 2,
    preserved_portal_user_count: 1,
  });
});
