const assert = require("node:assert/strict");
const test = require("node:test");
const { candidateDiff, reviewStatusLabel, shouldRenewLease } = require("./portal-review-collaboration.js");

test("candidateDiff compares stable canonical line keys", () => {
  const diff = candidateDiff(
    { lines: [{ lineKey: "line-1", accountCode: "770.01", debit: "10.00", credit: "" }] },
    { lines: [{ lineKey: "line-1", accountCode: "770.02", debit: "10.00", credit: "" }, { lineKey: "line-2", accountCode: "191.01" }] },
  );
  assert.equal(diff.length, 2);
  assert.equal(diff.find((item) => item.lineKey === "line-1").changed, true);
  assert.equal(diff.find((item) => item.lineKey === "line-2").candidateAccount, "191.01");
});

test("review status and lease renewal require visible recent activity", () => {
  assert.equal(reviewStatusLabel("saving"), "Kaydediliyor");
  assert.equal(shouldRenewLease({ visible: true, lastActivityAt: 90, now: 100 }), true);
  assert.equal(shouldRenewLease({ visible: false, lastActivityAt: 90, now: 100 }), false);
  assert.equal(shouldRenewLease({ visible: true, lastActivityAt: 0, now: 100 }), false);
});
