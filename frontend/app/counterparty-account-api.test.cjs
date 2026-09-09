// File: frontend/app/counterparty-account-api.test.cjs
// Summary: Verifies the additive counterparty-account API transport contract.
const assert = require("node:assert/strict");
const test = require("node:test");

const { createCounterpartyAccountToBackend } = require("./upload-api.js");

test("createCounterpartyAccountToBackend posts one detail account without replacing the chart", async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ created: true }) };
  };

  const result = await createCounterpartyAccountToBackend({
    apiBaseUrl: "http://localhost:8000",
    clientId: "client-1",
    userId: "mali-musavir",
    sessionToken: "session-1",
    accountCode: "320.1234567890",
    accountName: "Yeni Tedarikci",
    taxId: "1234567890",
    fetchImpl,
  });

  assert.deepEqual(result, { created: true });
  assert.equal(request.url, "http://localhost:8000/phase0/store/counterparty-account");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["X-Fisora-User-Id"], "mali-musavir");
  assert.equal(request.options.headers["X-Fisora-Session"], "session-1");
  assert.deepEqual(JSON.parse(request.options.body), {
    client_id: "client-1",
    account: {
      raw_account_code: "320.1234567890",
      normalized_account_code: "320.1234567890",
      account_name: "Yeni Tedarikci",
      is_detail_account: true,
      tax_id: "1234567890",
      tax_office: null,
      iban: null,
    },
  });
});
