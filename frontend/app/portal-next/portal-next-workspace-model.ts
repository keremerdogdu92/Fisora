// File: frontend/app/portal-next/portal-next-workspace-model.ts
// Summary: Resolves the effective period and period-scoped document set for the isolated next-generation accountant workbench.

import type { PilotDocument } from "../portal-types";

function isInvoice(document: PilotDocument) {
  return document.intakeCategory === "purchase_invoice" || document.intakeCategory === "sales_invoice";
}

export function resolvePortalNextWorkspacePeriod({ documents, fallbackPeriod, selectedPeriod }: {
  documents: PilotDocument[];
  fallbackPeriod: string;
  selectedPeriod: string;
}) {
  const periods = Array.from(new Set(documents.map((document) => document.period).filter(Boolean))).sort().reverse();
  const availablePeriods = periods.length ? periods : fallbackPeriod ? [fallbackPeriod] : [];
  const invoicePeriods = Array.from(new Set(documents.filter(isInvoice).map((document) => document.period).filter(Boolean))).sort().reverse();
  // The workbench opens on Faturalar, so an invalid initial period should prefer the latest period that actually contains invoices.
  const defaultPeriod = invoicePeriods[0] || availablePeriods[0] || "";
  const effectivePeriod = selectedPeriod && availablePeriods.includes(selectedPeriod) ? selectedPeriod : defaultPeriod;
  const periodDocuments = effectivePeriod ? documents.filter((document) => document.period === effectivePeriod) : documents;

  return { documents: periodDocuments, periods: availablePeriods, selectedPeriod: effectivePeriod };
}
