import type { DraftLine, PilotDocument } from "./portal-types";
import { statementReviewStatus, statementStatusLabel } from "./portal-formatters";

export function reviewedStatementRiskFlags(flags: string[], status: string) {
  if (status === "approved") {
    const removable = new Set([
      "ai_invalid_schema",
      "counterparty_match_review_required",
      "counterparty_not_found",
      "learning_rule_review_required",
      "statement_accountant_approval_required",
      "statement_review_required",
    ]);
    return flags.filter((flag) => !removable.has(flag));
  }
  if (status === "rejected") return Array.from(new Set([...flags, "statement_line_rejected"]));
  return Array.from(new Set([...flags, "statement_review_required"]));
}

export function replaceStatementCounterpart(lines: DraftLine[], accountCode: string) {
  if (!accountCode.trim()) return lines;
  let replaced = false;
  return lines.map((line) => {
    if (replaced || line.account_code.startsWith("102")) return line;
    replaced = true;
    return { ...line, account_code: accountCode };
  });
}

export function applyStatementLineDecision(
  document: PilotDocument,
  lineNo: number,
  action: string,
  correctedAccountCode: string,
  correctedCounterpartyCode: string,
  reviewer: string,
  reason: string,
): PilotDocument {
  const reviewStatus = statementReviewStatus(action);
  const newAccount = correctedCounterpartyCode.trim() || correctedAccountCode.trim();
  const reviewedAt = new Date().toLocaleString("tr-TR");
  const statementLines = document.statementLines.map((line) => {
    if (line.line_no !== lineNo) return line;
    return {
      ...line,
      suggested_account_code: newAccount || line.suggested_account_code,
      counterparty_match_code: newAccount || line.counterparty_match_code,
      confidence: newAccount ? 100 : line.confidence,
      accountant_review_status: reviewStatus,
      risk_flags: reviewedStatementRiskFlags(line.risk_flags, reviewStatus),
      review_reason: reason || line.review_reason,
    };
  });
  const statementEntries = document.statementEntries.map((entry) => {
    if (entry.statement_line_no !== lineNo) return entry;
    return {
      ...entry,
      accountant_review_status: reviewStatus,
      risk_flags: reviewedStatementRiskFlags(entry.risk_flags, reviewStatus),
      lines: replaceStatementCounterpart(entry.lines, newAccount),
    };
  });
  const allApproved = statementLines.length > 0 && statementLines.every((line) => line.accountant_review_status === "approved");
  return {
    ...document,
    status: allApproved ? "export_ready" : "review_required",
    exportGateReason: allApproved
      ? "Banka satırları müşavir onayından geçti; çıktı listesine alınabilir."
      : "Banka satırlarında müşavir kontrolü sürüyor.",
    deterministicSummary: `${document.deterministicSummary}${document.deterministicSummary ? ", " : ""}statement_line_reviewed:${lineNo}`,
    statementLines,
    statementEntries,
    statementAiSummary: `${statementStatusLabel(reviewStatus)} / ${reviewer} / ${reviewedAt}`,
  };
}

export function journalDraftLinesForDocument(document: PilotDocument, selectedStatementLineNo: number): DraftLine[] {
  if (document.intakeCategory !== "bank_statement" && document.statementLines.length === 0) return document.draftLines;
  const selectedEntry = document.statementEntries.find((entry) => entry.statement_line_no === selectedStatementLineNo);
  return selectedEntry?.lines ?? [];
}
