import type { IntakeCategory, PilotStatus, StatementLineReview } from "./portal-types";
import { normalizeIntakeCategory } from "./upload-intake";
import { safeText } from "./portal-normalization";

export function toIntakeCategory(value: unknown): IntakeCategory {
  return normalizeIntakeCategory(safeText(value)) as IntakeCategory;
}

export function inferIntakeCategory(documentType: unknown, invoiceType?: unknown): IntakeCategory {
  const explicitType = safeText(documentType);
  if (explicitType === "bank" || explicitType === "bank_statement" || explicitType === "pos" || explicitType === "pos_statement") {
    return "bank_statement";
  }
  if (explicitType === "special_document") {
    return "special_document";
  }
  const explicitInvoiceType = safeText(invoiceType).toLocaleUpperCase("tr-TR");
  if (explicitInvoiceType === "SATIS") {
    return "sales_invoice";
  }
  return "purchase_invoice";
}

export function periodLabel(period: string) {
  const [year, month] = period.split("-");
  if (!year || !month) return period;
  return `${month}.${year}`;
}

export function isInProgress(status: PilotStatus) {
  return status === "uploaded" || status === "queued" || status === "processing";
}

export function isCancelStatus(status: PilotStatus) {
  return status === "cancel_requested" || status === "post_export_correction_requested";
}

export const statementTypeLabels: Record<string, string> = {
  pos_collection: "POS tahsilat",
  pos_blocked: "POS bloke",
  tax: "Vergi",
  sgk: "SGK",
  bank_fee: "Banka masrafÄ±",
  eft: "EFT/Havale",
  credit_card: "Kredi/kart",
  loan: "Kredi",
  payroll: "MaaÅŸ",
  transfer: "Transfer",
  refund: "Ä°ade",
  reversal: "Ters kayÄ±t",
  unknown: "Bilinmeyen",
};

export function statementDirectionLabel(direction: StatementLineReview["direction"]) {
  if (direction === "in") return "GiriÅŸ";
  if (direction === "out") return "Ã‡Ä±kÄ±ÅŸ";
  return "-";
}

export function statementReviewStatus(action: string) {
  if (action === "approve" || action === "approve_with_changes" || action === "suggest_for_similar") return "approved";
  if (action === "exclude_export" || action === "exclude_from_export" || action === "out_of_scope") return "rejected";
  return "review_required";
}

export function statementStatusLabel(status?: string) {
  if (status === "approved") return "OnaylÄ±";
  if (status === "rejected") return "Red";
  if (status === "review_required") return "Kontrol";
  return "Bekliyor";
}

export function reviewActionLabel(action: string) {
  if (action === "approve") return "OnaylandÄ±";
  if (action === "approve_with_changes") return "DÃ¼zeltilip onaylandÄ±";
  if (action === "suggest_for_similar") return "Kural adayÄ± yapÄ±ldÄ±";
  if (action === "exclude_export") return "Ã‡Ä±ktÄ± dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ±";
  return "Kontrolde tutuldu";
}
