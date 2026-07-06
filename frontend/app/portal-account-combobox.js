function safeText(value, fallback = "") {
  return value == null || value === "" ? fallback : String(value);
}

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

function normalizeSearchText(value) {
  return safeText(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function normalizeAccountCode(value) {
  return safeText(value).trim().replace(/\s+/g, ".");
}

function normalizeChartAccountOptions(accounts) {
  return safeList(accounts)
    .map((account) => {
      const code = normalizeAccountCode(account?.normalized_account_code || account?.code || account?.raw_account_code);
      const rawCode = safeText(account?.raw_account_code || code).trim();
      const name = safeText(account?.account_name || account?.name);
      if (!code || !name) return null;
      return {
        code,
        name,
        isDetail: Boolean(account?.is_detail_account ?? account?.isDetail),
        taxId: safeText(account?.tax_id || account?.taxId),
        taxOffice: safeText(account?.tax_office || account?.taxOffice),
        iban: safeText(account?.iban),
        searchText: normalizeSearchText(`${code} ${rawCode} ${name}`),
      };
    })
    .filter(Boolean);
}

function filterAccountOptions(options, query, limit = 20) {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) return [];
  const startsWithMatches = [];
  const containsMatches = [];
  for (const option of safeList(options)) {
    const codeText = normalizeSearchText(option?.code);
    const searchText = safeText(option?.searchText) || normalizeSearchText(`${option?.code || ""} ${option?.name || ""}`);
    if (codeText.startsWith(normalizedQuery)) {
      startsWithMatches.push(option);
    } else if (searchText.includes(normalizedQuery)) {
      containsMatches.push(option);
    }
    if (startsWithMatches.length + containsMatches.length >= limit) break;
  }
  return [...startsWithMatches, ...containsMatches].slice(0, limit);
}

function resolveAccountSelection(options, input, activeIndex = 0) {
  const normalizedInput = normalizeSearchText(input);
  if (!normalizedInput) return null;
  const normalizedOptions = safeList(options);
  const exact = normalizedOptions.find((option) => normalizeSearchText(option?.code) === normalizedInput);
  if (exact) return exact;
  const codeMatches = normalizedOptions.filter((option) => normalizeSearchText(option?.code).startsWith(normalizedInput));
  if (codeMatches.length === 1) return codeMatches[0];
  const visible = filterAccountOptions(normalizedOptions, input);
  return visible[Math.max(0, Math.min(activeIndex, visible.length - 1))] || null;
}

function accountNameForCode(options, accountCode) {
  const normalizedCode = normalizeSearchText(accountCode);
  if (!normalizedCode) return "";
  return safeText(safeList(options).find((option) => normalizeSearchText(option?.code) === normalizedCode)?.name);
}

function shouldReplaceDescription(line, options) {
  const description = safeText(line?.description).trim();
  if (!description) return true;
  const previousAccountName = accountNameForCode(options, line?.account_code);
  return Boolean(previousAccountName && normalizeSearchText(previousAccountName) === normalizeSearchText(description));
}

function applyAccountSelectionToLine(line, account, options = []) {
  const description = safeText(line?.description).trim();
  const accountName = safeText(account?.name);
  return {
    account_code: safeText(account?.code),
    description: shouldReplaceDescription(line, options) ? accountName : description,
    debit: safeText(line?.debit, "0.00"),
    credit: safeText(line?.credit, "0.00"),
  };
}

module.exports = {
  applyAccountSelectionToLine,
  filterAccountOptions,
  normalizeChartAccountOptions,
  resolveAccountSelection,
};
