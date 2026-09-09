// File: frontend/app/portal-account-combobox.js
// Summary: Normalizes chart-account options and resolves safe keyboard/account selections for the workbench.

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
  const familyQuery = /^\d{3}$/.test(normalizedQuery);
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
    if (!familyQuery && startsWithMatches.length + containsMatches.length >= limit) break;
  }
  const matches = [...startsWithMatches, ...containsMatches];
  return familyQuery ? matches : matches.slice(0, limit);
}

function resolveAccountSelection(options, input, activeIndex = 0) {
  const normalizedInput = normalizeSearchText(input);
  if (!normalizedInput) return null;
  const normalizedOptions = safeList(options);
  const selectableOptions = normalizedOptions.filter((option) => Boolean(option?.isDetail));
  const exact = selectableOptions.find((option) => normalizeSearchText(option?.code) === normalizedInput);
  if (exact) return exact;
  const visible = filterAccountOptions(normalizedOptions, input);
  const active = visible[Math.max(0, Math.min(activeIndex, visible.length - 1))] || null;
  if (/^\d{3}$/.test(normalizedInput)) return active?.isDetail ? active : null;
  const codeMatches = selectableOptions.filter((option) => normalizeSearchText(option?.code).startsWith(normalizedInput));
  if (codeMatches.length === 1) return codeMatches[0];
  return active?.isDetail ? active : null;
}

function nextSelectableAccountIndex(options, currentIndex, direction) {
  const normalizedOptions = safeList(options);
  const step = direction < 0 ? -1 : 1;
  let index = Number.isInteger(currentIndex) ? currentIndex + step : step > 0 ? 0 : normalizedOptions.length - 1;
  while (index >= 0 && index < normalizedOptions.length) {
    if (normalizedOptions[index]?.isDetail) return index;
    index += step;
  }
  if (normalizedOptions[currentIndex]?.isDetail) return currentIndex;
  return normalizedOptions.findIndex((option) => Boolean(option?.isDetail));
}

function draftAccountResolutionIssues(lines, options, suggestedNewCounterpartyCodes = []) {
  return safeList(lines).flatMap((line, index) => {
    const accountCode = normalizeDraftAccountCode(line?.account_code);
    if (!accountCode) return [{ kind: "blank", index, accountCode: "" }];
    const classification = classifyDraftAccountCode(options, accountCode, suggestedNewCounterpartyCodes);
    return classification === "valid" ? [] : [{ kind: classification, index, accountCode }];
  });
}

function accountNameForCode(options, accountCode) {
  const normalizedCode = normalizeSearchText(accountCode);
  if (!normalizedCode) return "";
  return safeText(safeList(options).find((option) => normalizeSearchText(option?.code) === normalizedCode)?.name);
}

function normalizeDraftAccountCode(value) {
  return safeText(value)
    .trim()
    .replace(/[\s,-]+/g, ".")
    .replace(/[^0-9A-Za-z.]/g, "")
    .replace(/\.+/g, ".")
    .replace(/^\.+|\.+$/g, "");
}

function classifyDraftAccountCode(options, accountCode, suggestedNewCounterpartyCodes = []) {
  const code = normalizeDraftAccountCode(accountCode);
  if (!code) return "valid";
  const detailAccountExists = safeList(options).some(
    (option) => Boolean(option?.isDetail) && normalizeDraftAccountCode(option?.code) === code,
  );
  if (detailAccountExists) return "valid";
  const suggestedCodes = new Set(safeList(suggestedNewCounterpartyCodes).map(normalizeDraftAccountCode).filter(Boolean));
  if ((code.startsWith("120") || code.startsWith("320")) && suggestedCodes.has(code)) {
    return "new_counterparty";
  }
  return "invalid";
}

function applyAccountSelectionToLine(line, account, options = []) {
  return {
    account_code: safeText(account?.code),
    description: safeText(line?.description),
    debit: safeText(line?.debit, "0.00"),
    credit: safeText(line?.credit, "0.00"),
  };
}

module.exports = {
  applyAccountSelectionToLine,
  classifyDraftAccountCode,
  draftAccountResolutionIssues,
  filterAccountOptions,
  nextSelectableAccountIndex,
  normalizeChartAccountOptions,
  resolveAccountSelection,
};
