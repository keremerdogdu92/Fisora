function text(value) {
  return String(value ?? "").trim();
}

function reviewStatusLabel(status) {
  return {
    saved: "Kaydedildi",
    saving: "Kaydediliyor",
    stale: "Baska surum olustu",
    offline: "Baglanti kesildi; yerel degisiklik korunuyor",
  }[text(status)] || "Kaydedilmedi";
}

function candidateDiff(current = {}, candidate = {}) {
  const keys = new Set([
    ...(Array.isArray(current.lines) ? current.lines : []),
    ...(Array.isArray(candidate.lines) ? candidate.lines : []),
  ].map((line) => text(line?.lineKey || line?.canonical_line_id || line?.id)));
  const byKey = (lines) => new Map((Array.isArray(lines) ? lines : []).map((line) => [text(line?.lineKey || line?.canonical_line_id || line?.id), line]));
  const left = byKey(current.lines);
  const right = byKey(candidate.lines);
  return [...keys].filter(Boolean).map((lineKey) => {
    const a = left.get(lineKey) || {};
    const b = right.get(lineKey) || {};
    const result = {
      lineKey,
      currentAccount: text(a.accountCode || a.account_code),
      candidateAccount: text(b.accountCode || b.account_code),
      currentDebit: text(a.debit),
      candidateDebit: text(b.debit),
      currentCredit: text(a.credit),
      candidateCredit: text(b.credit),
    };
    return { ...result, changed: (
      result.currentAccount !== result.candidateAccount ||
      result.currentDebit !== result.candidateDebit ||
      result.currentCredit !== result.candidateCredit
    ) };
  });
}

function shouldRenewLease({ visible = true, lastActivityAt = 0, now = Date.now(), intervalMs = 60000 } = {}) {
  return Boolean(visible && lastActivityAt && now - lastActivityAt >= 0 && now - lastActivityAt <= intervalMs);
}

module.exports = { candidateDiff, reviewStatusLabel, shouldRenewLease };
