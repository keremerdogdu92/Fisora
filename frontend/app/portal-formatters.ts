// File: frontend/app/portal-formatters.ts
// Summary: Formats accountant-facing period, status, intake, and review labels for portal views.
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

export function longPeriodLabel(period: string) {
  const [year, month] = period.split("-");
  const yearNumber = Number(year);
  const monthNumber = Number(month);
  if (!Number.isInteger(yearNumber) || !Number.isInteger(monthNumber) || monthNumber < 1 || monthNumber > 12) return periodLabel(period);
  const label = new Intl.DateTimeFormat("tr-TR", { month: "long", year: "numeric" }).format(new Date(yearNumber, monthNumber - 1, 1));
  return label.charAt(0).toLocaleUpperCase("tr-TR") + label.slice(1);
}

type PortalDateParts = {
  year: number;
  month: number;
  day: number;
  hour?: number;
  minute?: number;
};

function validPortalDateParts(parts: PortalDateParts) {
  const probe = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  const validDate = probe.getUTCFullYear() === parts.year
    && probe.getUTCMonth() === parts.month - 1
    && probe.getUTCDate() === parts.day;
  const validTime = (parts.hour === undefined || (parts.hour >= 0 && parts.hour <= 23))
    && (parts.minute === undefined || (parts.minute >= 0 && parts.minute <= 59));
  return validDate && validTime;
}

function knownPortalDateParts(value: string): PortalDateParts | null {
  const isoDate = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoDate) {
    const parts = { year: Number(isoDate[1]), month: Number(isoDate[2]), day: Number(isoDate[3]) };
    return validPortalDateParts(parts) ? parts : null;
  }
  const dayFirst = value.match(/^(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})(?:[ T]+(\d{1,2}):(\d{2})(?::\d{2})?)?$/);
  if (!dayFirst) return null;
  const parts: PortalDateParts = {
    year: Number(dayFirst[3]),
    month: Number(dayFirst[2]),
    day: Number(dayFirst[1]),
    ...(dayFirst[4] === undefined ? {} : { hour: Number(dayFirst[4]), minute: Number(dayFirst[5]) }),
  };
  return validPortalDateParts(parts) ? parts : null;
}

function explicitPortalInstant(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function portalDateLabel(parts: PortalDateParts) {
  return `${String(parts.day).padStart(2, "0")}.${String(parts.month).padStart(2, "0")}.${parts.year}`;
}

function istanbulPortalParts(value: Date, includeTime: boolean) {
  const parts = new Intl.DateTimeFormat("tr-TR", {
    timeZone: "Europe/Istanbul",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).formatToParts(value);
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

export function formatPortalDate(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return "-";
  const known = knownPortalDateParts(normalized);
  if (known) return portalDateLabel(known);
  const instant = explicitPortalInstant(normalized);
  if (!instant) return normalized;
  const parts = istanbulPortalParts(instant, false);
  return `${parts.day}.${parts.month}.${parts.year}`;
}

export function formatPortalDateTime(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return "-";
  const known = knownPortalDateParts(normalized);
  if (known) {
    const date = portalDateLabel(known);
    return known.hour === undefined || known.minute === undefined
      ? date
      : `${date} \u00b7 ${String(known.hour).padStart(2, "0")}:${String(known.minute).padStart(2, "0")}`;
  }
  const instant = explicitPortalInstant(normalized);
  if (!instant) return normalized;
  const parts = istanbulPortalParts(instant, true);
  return `${parts.day}.${parts.month}.${parts.year} \u00b7 ${parts.hour}:${parts.minute}`;
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
  bank_fee: "Banka masrafı",
  eft: "EFT/Havale",
  credit_card: "Kredi/kart",
  loan: "Kredi",
  payroll: "Maaş",
  transfer: "Transfer",
  refund: "İade",
  reversal: "Ters kayıt",
  unknown: "Bilinmeyen",
};

export function statementDirectionLabel(direction: StatementLineReview["direction"]) {
  if (direction === "in") return "Giriş";
  if (direction === "out") return "Çıkış";
  return "-";
}

export function statementReviewStatus(action: string) {
  if (action === "approve" || action === "approve_with_changes" || action === "suggest_for_similar") return "approved";
  if (action === "exclude_export" || action === "exclude_from_export" || action === "out_of_scope") return "rejected";
  return "review_required";
}

export function statementStatusLabel(status?: string) {
  if (status === "approved") return "Onaylı";
  if (status === "rejected") return "Red";
  if (status === "review_required") return "Kontrol";
  return "Bekliyor";
}

export function reviewActionLabel(action: string) {
  if (action === "approve") return "Onaylandı";
  if (action === "approve_with_changes") return "Düzeltilip onaylandı";
  if (action === "suggest_for_similar") return "Kural adayı yapıldı";
  if (action === "exclude_export") return "Hariç tutuldu";
  return "Kontrolde tutuldu";
}
