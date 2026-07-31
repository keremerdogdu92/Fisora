function safeText(value, fallback = "") {
  return value == null || value === "" ? fallback : String(value);
}

function safeRecord(value) {
  return value && typeof value === "object" ? value : {};
}

function safeList(value) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function agentSourceLabel(value) {
  const normalized = safeText(value).toLocaleLowerCase("tr-TR");
  if (!normalized || normalized === "-") return "Kontrollü öneri";
  if (normalized === "static_rules" || normalized === "deterministic_rules" || normalized === "statement_rule_engine") {
    return "Muhasebe motoru";
  }
  if (normalized === "replay_provider" || normalized.includes("ai") || normalized.includes("groq")) {
    return "AI ajan önerisi";
  }
  return "Muhasebe motoru + AI ajan";
}

const REVIEW_REASON_LABELS = {
  cancelled_invoice_visible: "Bu fatura iptal görünmektedir",
  mixed_vat_manual_review: "KDV ayrımı kontrolü",
  counterparty_title_token_overlap: "Cari eşleşme kontrolü",
  onboarding_missing_activity_or_nace: "Mükellef onboarding eksiği",
  onboarding_missing_workplace_addresses: "İşyeri adresi eksiği",
  export_blocked_until_review: "Müşavir onayı gerekli",
  statement_review_required: "Ekstre satırı kontrolü",
  tax_payment_review: "Vergi ödemesi kontrolü",
  line_decision_journal_incomplete: "Fatura satırı dağılımı kontrol edilmeli",
  insufficient_evidence: "Tutar veya KDV kanıtı tamamlanmalı",
};

function reviewReasonLabel(code) {
  return REVIEW_REASON_LABELS[safeText(code)] || "Ek kontrol gerekli";
}

function groupedReviewReasons(documents) {
  const counts = new Map();
  for (const document of documents || []) {
    for (const code of document.reviewReasons || []) {
      counts.set(code, (counts.get(code) || 0) + 1);
    }
  }
  return Array.from(counts.entries())
    .map(([code, count]) => ({ code, label: reviewReasonLabel(code), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "tr"));
}

function normalizeStatementLines(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const row = safeRecord(item);
    const direction = safeText(row.direction);
    return {
      line_no: safeNumber(row.line_no ?? row.lineNo, index + 1),
      transaction_date: safeText(row.transaction_date ?? row.transactionDate),
      description: safeText(row.description),
      amount: safeText(row.amount, "0.00"),
      direction: direction === "in" || direction === "out" ? direction : "",
      balance_after: safeText(row.balance_after ?? row.balanceAfter),
      counterparty_name: safeText(row.counterparty_name ?? row.counterpartyName),
      tax_id: safeText(row.tax_id ?? row.taxId),
      iban: safeText(row.iban),
      suggested_account_code: safeText(row.suggested_account_code ?? row.suggestedAccountCode),
      transaction_type: safeText(row.transaction_type ?? row.transactionType, "unknown"),
      confidence: safeNumber(row.confidence, 0),
      risk_flags: safeList(row.risk_flags ?? row.riskFlags),
      review_reason: safeText(row.review_reason ?? row.reviewReason),
      accountant_review_status: safeText(row.accountant_review_status ?? row.accountantReviewStatus),
      counterparty_match_code: safeText(row.counterparty_match_code ?? row.counterpartyMatchCode),
    };
  });
}

function normalizeStatementEntries(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const row = safeRecord(item);
    return {
      statement_line_no: safeNumber(row.statement_line_no ?? row.statementLineNo),
      statement_fingerprint: safeText(row.statement_fingerprint ?? row.statementFingerprint),
      source_document_ref: safeText(row.source_document_ref ?? row.sourceDocumentRef),
      accountant_review_status: safeText(row.accountant_review_status ?? row.accountantReviewStatus),
      risk_flags: safeList(row.risk_flags ?? row.riskFlags),
      lines: Array.isArray(row.lines) ? row.lines : [],
    };
  });
}

function normalizeStatementAiSuggestions(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const row = safeRecord(item);
    return {
      line_no: safeNumber(row.line_no ?? row.lineNo),
      transaction_type: safeText(row.transaction_type ?? row.transactionType, "unknown"),
      suggested_account_code: safeText(row.suggested_account_code ?? row.suggestedAccountCode),
      confidence: safeNumber(row.confidence, 0),
      reason: safeText(row.reason),
      evidence: safeList(row.evidence),
      risk_flags: safeList(row.risk_flags ?? row.riskFlags),
      ai_used: Boolean(row.ai_used ?? row.aiUsed),
      provider: safeText(row.provider),
      skipped_reason: safeText(row.skipped_reason ?? row.skippedReason),
      export_allowed: Boolean(row.export_allowed ?? row.exportAllowed),
    };
  });
}

function normalizeRulePrompt(value) {
  const row = safeRecord(value);
  return {
    show: Boolean(row.show),
    defaultScope: safeText(row.defaultScope ?? row.default_scope),
    message: safeText(row.message),
    clientConsistentDecisionCount: safeNumber(row.clientConsistentDecisionCount ?? row.client_consistent_decision_count),
    officeDistinctClientCount: safeNumber(row.officeDistinctClientCount ?? row.office_distinct_client_count),
    officeConsistentDecisionCount: safeNumber(row.officeConsistentDecisionCount ?? row.office_consistent_decision_count),
  };
}

function normalizeStatus(value) {
  if (value === "export_ready" || value === "auto_ready") return "export_ready";
  if (value === "processing") return "processing";
  if (value === "queued" || value === "stored") return "queued";
  if (value === "uploaded") return "uploaded";
  if (value === "cancel_requested") return "cancel_requested";
  if (value === "cancel_approved") return "cancel_approved";
  if (value === "cancel_rejected") return "cancel_rejected";
  if (value === "export_added") return "export_added";
  if (value === "exported") return "exported";
  if (value === "post_export_correction_requested") return "post_export_correction_requested";
  return "review_required";
}

function parseDateParts(value) {
  const dotted = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
  if (dotted) return { year: dotted[3], month: dotted[2].padStart(2, "0") };
  const iso = value.match(/^(\d{4})-(\d{2})/);
  if (iso) return { year: iso[1], month: iso[2] };
  return null;
}

function periodFromDate(value, fallback = "2026-06") {
  const parsed = parseDateParts(value);
  return parsed ? `${parsed.year}-${parsed.month}` : fallback;
}

module.exports = {
  agentSourceLabel,
  groupedReviewReasons,
  normalizeRulePrompt,
  normalizeStatementAiSuggestions,
  normalizeStatementEntries,
  normalizeStatementLines,
  normalizeStatus,
  parseDateParts,
  periodFromDate,
  reviewReasonLabel,
  safeList,
  safeNumber,
  safeRecord,
  safeText,
};
