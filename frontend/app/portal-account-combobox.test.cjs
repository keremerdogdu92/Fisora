const assert = require("node:assert/strict");
const test = require("node:test");

const {
  applyAccountSelectionToLine,
  classifyDraftAccountCode,
  filterAccountOptions,
  normalizeChartAccountOptions,
  resolveAccountSelection,
} = require("./portal-account-combobox");

const accounts = normalizeChartAccountOptions([
  {
    raw_account_code: "320",
    normalized_account_code: "320",
    account_name: "Saticilar",
    is_detail_account: false,
  },
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
]);

test("normalizeChartAccountOptions maps backend chart rows to keyboard options", () => {
  assert.deepEqual(accounts[1], {
    code: "191.01.020",
    name: "Indirilecek KDV %20",
    isDetail: true,
    taxId: "",
    taxOffice: "",
    iban: "",
    searchText: "191.01.020 191 01 020 indirilecek kdv %20",
  });
  assert.equal(accounts[2].taxId, "1234567890");
});

test("filterAccountOptions searches account code and account name", () => {
  assert.deepEqual(filterAccountOptions(accounts, "320").map((account) => account.code), ["320", "320.B04"]);
  assert.deepEqual(filterAccountOptions(accounts, "kdv").map((account) => account.code), ["191.01.020"]);
});

test("filterAccountOptions shows the whole three digit account family", () => {
  const familyAccounts = normalizeChartAccountOptions([
    { normalized_account_code: "320", account_name: "Saticilar", is_detail_account: false },
    { normalized_account_code: "320.01", account_name: "Yurt ici saticilar", is_detail_account: false },
    { normalized_account_code: "320.01.001", account_name: "Tedarikci A", is_detail_account: true },
    { normalized_account_code: "320.01.002", account_name: "Tedarikci B", is_detail_account: true },
    { normalized_account_code: "320.01.003", account_name: "Tedarikci C", is_detail_account: true },
  ]);

  assert.deepEqual(
    filterAccountOptions(familyAccounts, "320", 2).map((account) => account.code),
    ["320", "320.01", "320.01.001", "320.01.002", "320.01.003"],
  );
});

test("resolveAccountSelection accepts exact code and unique partial code", () => {
  assert.equal(resolveAccountSelection(accounts, "191.01.020")?.code, "191.01.020");
  assert.equal(resolveAccountSelection(accounts, "191.01")?.code, "191.01.020");
});

test("resolveAccountSelection does not select header accounts", () => {
  assert.equal(resolveAccountSelection(accounts, "320"), null);
});

test("resolveAccountSelection uses active index when several candidates are visible", () => {
  const visibleAccounts = normalizeChartAccountOptions([
    { normalized_account_code: "770.01", account_name: "Genel gider", is_detail_account: true },
    { normalized_account_code: "770.02", account_name: "Pazarlama gideri", is_detail_account: true },
  ]);

  assert.equal(resolveAccountSelection(visibleAccounts, "770.", 1)?.code, "770.02");
});

test("applyAccountSelectionToLine preserves the journal description while changing the account", () => {
  assert.deepEqual(
    applyAccountSelectionToLine({ account_code: "", description: "TICKET RESTAURANT YEMEK BEDELI", debit: "0.00", credit: "0.00" }, accounts[2], accounts),
    { account_code: "320.B04", description: "TICKET RESTAURANT YEMEK BEDELI", debit: "0.00", credit: "0.00" },
  );
  assert.deepEqual(
    applyAccountSelectionToLine(
      { account_code: "191.01.020", description: "Fatura satiri", debit: "0.00", credit: "0.00" },
      accounts[3],
      accounts,
    ),
    { account_code: "770.01", description: "Fatura satiri", debit: "0.00", credit: "0.00" },
  );
});

test("classifyDraftAccountCode treats a missing suggested cari as a warning, not an invalid account", () => {
  assert.equal(classifyDraftAccountCode(accounts, "191.01.020", ["320.19736107464"]), "valid");
  assert.equal(classifyDraftAccountCode(accounts, "153.99.999", ["320.19736107464"]), "invalid");
  assert.equal(classifyDraftAccountCode(accounts, "320.19736107464", ["320.19736107464"]), "new_counterparty");
  assert.equal(classifyDraftAccountCode(accounts, "120.9876543210", ["120.9876543210"]), "new_counterparty");
  assert.equal(classifyDraftAccountCode(accounts, "320.B04", ["320.B04"]), "valid");
});
