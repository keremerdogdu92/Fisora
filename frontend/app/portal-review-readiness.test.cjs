// File: frontend/app/portal-review-readiness.test.cjs
// Summary: Verifies approval account-resolution gates and selectable account keyboard navigation.
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  draftAccountResolutionIssues,
  nextSelectableAccountIndex,
  normalizeChartAccountOptions,
} = require("./portal-account-combobox");

const accounts = normalizeChartAccountOptions([
  { normalized_account_code: "320", account_name: "Saticilar", is_detail_account: false },
  { normalized_account_code: "320.01.001", account_name: "Tedarikci A", is_detail_account: true },
  { normalized_account_code: "770.01.001", account_name: "Genel gider", is_detail_account: true },
]);

test("approval issues include blank, invalid, and uncreated counterparty accounts", () => {
  const lines = [
    { account_code: "", debit: "100.00", credit: "0.00" },
    { account_code: "770.99.999", debit: "0.00", credit: "20.00" },
    { account_code: "320.1234567890", debit: "0.00", credit: "80.00" },
  ];
  assert.deepEqual(
    draftAccountResolutionIssues(lines, accounts, ["320.1234567890"]).map((issue) => issue.kind),
    ["blank", "invalid", "new_counterparty"],
  );
});

test("approval issues are empty when every required row resolves to a detail account", () => {
  const lines = [
    { account_code: "770.01.001", debit: "100.00", credit: "0.00" },
    { account_code: "320.01.001", debit: "0.00", credit: "100.00" },
  ];
  assert.deepEqual(draftAccountResolutionIssues(lines, accounts, []), []);
});

test("keyboard navigation skips non-detail header accounts", () => {
  assert.equal(nextSelectableAccountIndex(accounts, -1, 1), 1);
  assert.equal(nextSelectableAccountIndex(accounts, 1, 1), 2);
  assert.equal(nextSelectableAccountIndex(accounts, 2, -1), 1);
  assert.equal(nextSelectableAccountIndex(accounts, 2, 1), 2);
});
