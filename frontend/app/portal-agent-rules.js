function text(value) {
  return String(value ?? "").trim();
}

function ruleStatusBuckets(rules = []) {
  const buckets = { awaiting: [], active: [], paused: [], archived: [] };
  for (const rule of Array.isArray(rules) ? rules : []) {
    const status = text(rule?.status);
    const bucket = status === "draft" ? "awaiting" : status;
    if (Object.prototype.hasOwnProperty.call(buckets, bucket)) buckets[bucket].push(rule);
  }
  return buckets;
}

function maskTaxId(value) {
  const digits = text(value).replace(/\D/g, "");
  return digits.length <= 4 ? digits : `${digits.slice(0, 2)}******${digits.slice(-2)}`;
}

function buildAgentRuleViewModel(raw = {}, { detail = false } = {}) {
  const status = text(raw.status) || "draft";
  const taxId = text(raw.trigger_tax_id || raw.counterparty_tax_id || raw.counterpartyTaxId);
  return {
    ruleKey: text(raw.rule_key || raw.ruleKey),
    version: Number(raw.version || 0),
    status,
    scopeLabel: text(raw.scope_label || raw.scopeLabel || raw.client_id || raw.clientId),
    triggerLabel: text(raw.trigger_label || raw.triggerLabel) || (detail ? taxId : maskTaxId(taxId)),
    meaningLabel: text(raw.meaning_label || raw.meaningLabel || raw.category),
    bindingLabel: text(raw.binding_label || raw.bindingLabel || raw.account_code || raw.accountCode),
    sourceDocumentLabel: text(raw.source_document_label || raw.sourceDocumentLabel || raw.document_ref),
    confirmedBy: text(raw.confirmed_by || raw.confirmedBy),
    lastMatchedAt: text(raw.last_matched_at || raw.lastMatchedAt),
    matchCount: Number(raw.match_count || raw.matchCount || 0),
    correctionCount: Number(raw.correction_count || raw.correctionCount || 0),
    canActivate: status === "draft" || status === "paused",
    canPause: status === "active",
    canArchive: status === "draft" || status === "active" || status === "paused",
  };
}

module.exports = { buildAgentRuleViewModel, maskTaxId, ruleStatusBuckets };
