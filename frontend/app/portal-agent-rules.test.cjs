const assert = require("node:assert/strict");
const test = require("node:test");
const { buildAgentRuleViewModel, maskTaxId, ruleStatusBuckets } = require("./portal-agent-rules.js");

test("ruleStatusBuckets preserves lifecycle buckets and ignores unknown status", () => {
  const buckets = ruleStatusBuckets([{ status: "draft" }, { status: "active" }, { status: "archived" }, { status: "deleted" }]);
  assert.equal(buckets.awaiting.length, 1);
  assert.equal(buckets.active.length, 1);
  assert.equal(buckets.archived.length, 1);
  assert.equal(buckets.paused.length, 0);
});

test("rule view masks tax id in general list and exposes lifecycle actions", () => {
  const view = buildAgentRuleViewModel({ status: "active", counterparty_tax_id: "1234567890", version: 2, account_code: "770.03.001" });
  assert.equal(maskTaxId("1234567890"), "12******90");
  assert.equal(view.triggerLabel, "12******90");
  assert.equal(view.bindingLabel, "770.03.001");
  assert.equal(view.canPause, true);
  assert.equal(view.canActivate, false);
  assert.equal(view.canArchive, true);
});

test("rule detail may show authorized tax id", () => {
  const view = buildAgentRuleViewModel({ status: "draft", trigger_tax_id: "1234567890" }, { detail: true });
  assert.equal(view.triggerLabel, "1234567890");
  assert.equal(view.canActivate, true);
  assert.equal(view.canArchive, true);
});
