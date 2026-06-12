const assert = require("node:assert/strict");
const { test } = require("node:test");

const {
  agentSourceLabel,
  normalizeRulePrompt,
  normalizeStatementAiSuggestions,
  normalizeStatementEntries,
  normalizeStatementLines,
  normalizeStatus,
  periodFromDate,
  safeText,
} = require("./portal-normalization");

test("portal normalization helpers map review records without React state", () => {
  assert.equal(safeText("", "fallback"), "fallback");
  assert.equal(periodFromDate("03.06.2026"), "2026-06");
  assert.equal(normalizeStatus("stored"), "queued");
  assert.equal(agentSourceLabel("groq"), "AI ajan önerisi");

  assert.deepEqual(
    normalizeStatementLines([
      {
        lineNo: 7,
        transactionDate: "2026-06-03",
        description: "GIB ODEME",
        amount: "42.00",
        direction: "out",
        riskFlags: ["statement_review_required"],
        counterpartyMatchCode: "360.01",
      },
    ]),
    [
      {
        line_no: 7,
        transaction_date: "2026-06-03",
        description: "GIB ODEME",
        amount: "42.00",
        direction: "out",
        balance_after: "",
        counterparty_name: "",
        tax_id: "",
        iban: "",
        suggested_account_code: "",
        transaction_type: "unknown",
        confidence: 0,
        risk_flags: ["statement_review_required"],
        review_reason: "",
        accountant_review_status: "",
        counterparty_match_code: "360.01",
      },
    ],
  );
});

test("portal normalization helpers preserve statement entries, AI suggestions, and rule prompts", () => {
  assert.deepEqual(normalizeStatementEntries([{ statementLineNo: 2, lines: [{ account_code: "102" }] }]), [
    {
      statement_line_no: 2,
      statement_fingerprint: "",
      source_document_ref: "",
      accountant_review_status: "",
      risk_flags: [],
      lines: [{ account_code: "102" }],
    },
  ]);

  assert.deepEqual(normalizeStatementAiSuggestions([{ lineNo: 2, aiUsed: true, exportAllowed: false }]), [
    {
      line_no: 2,
      transaction_type: "unknown",
      suggested_account_code: "",
      confidence: 0,
      reason: "",
      evidence: [],
      risk_flags: [],
      ai_used: true,
      provider: "",
      skipped_reason: "",
      export_allowed: false,
    },
  ]);

  assert.deepEqual(normalizeRulePrompt({ show: true, default_scope: "client_rule", office_consistent_decision_count: 4 }), {
    show: true,
    defaultScope: "client_rule",
    message: "",
    clientConsistentDecisionCount: 0,
    officeDistinctClientCount: 0,
    officeConsistentDecisionCount: 4,
  });
});
