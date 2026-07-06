const assert = require("node:assert/strict");
const test = require("node:test");

const {
  applyAccountSelectionToLine,
  filterAccountOptions,
  normalizeChartAccountOptions,
  resolveAccountSelection,
} = require("./portal-account-combobox");

const accounts = normalizeChartAccountOptions([
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
  assert.deepEqual(accounts[0], {
    code: "191.01.020",
    name: "Indirilecek KDV %20",
    isDetail: true,
    taxId: "",
    taxOffice: "",
    iban: "",
    searchText: "191.01.020 191 01 020 indirilecek kdv %20",
  });
  assert.equal(accounts[1].taxId, "1234567890");
});

test("filterAccountOptions searches account code and account name", () => {
  assert.deepEqual(filterAccountOptions(accounts, "320").map((account) => account.code), ["320.B04"]);
  assert.deepEqual(filterAccountOptions(accounts, "kdv").map((account) => account.code), ["191.01.020"]);
});

test("resolveAccountSelection accepts exact code and unique partial code", () => {
  assert.equal(resolveAccountSelection(accounts, "191.01.020")?.code, "191.01.020");
  assert.equal(resolveAccountSelection(accounts, "191.01")?.code, "191.01.020");
});

test("resolveAccountSelection uses active index when several candidates are visible", () => {
  const visibleAccounts = normalizeChartAccountOptions([
    { normalized_account_code: "320.01", account_name: "Genel satici", is_detail_account: true },
    { normalized_account_code: "320.B04", account_name: "Rexton Medikal", is_detail_account: true },
  ]);

  assert.equal(resolveAccountSelection(visibleAccounts, "320", 1)?.code, "320.B04");
});

test("applyAccountSelectionToLine fills description from chart name unless user wrote it", () => {
  assert.deepEqual(
    applyAccountSelectionToLine({ account_code: "", description: "", debit: "0.00", credit: "0.00" }, accounts[1], accounts),
    { account_code: "320.B04", description: "Rexton Medikal", debit: "0.00", credit: "0.00" },
  );
  assert.deepEqual(
    applyAccountSelectionToLine(
      { account_code: "191.01.020", description: "Indirilecek KDV %20", debit: "0.00", credit: "0.00" },
      accounts[2],
      accounts,
    ),
    { account_code: "770.01", description: "Genel gider", debit: "0.00", credit: "0.00" },
  );
  assert.deepEqual(
    applyAccountSelectionToLine({ account_code: "191.01.020", description: "Elle yazildi", debit: "0.00", credit: "0.00" }, accounts[1], accounts),
    { account_code: "320.B04", description: "Elle yazildi", debit: "0.00", credit: "0.00" },
  );
});
