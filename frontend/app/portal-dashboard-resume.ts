// File: frontend/app/portal-dashboard-resume.ts
// Summary: Persists accountant dashboard office-period and resume context locally without changing backend workflow state.

import type { DocumentSegment } from "./portal-types";

export type DashboardResumeState = {
  clientId: string;
  period: string;
  segment: DocumentSegment;
  documentId: string;
  updatedAt: string;
};

function storageKey(userId: string, suffix: string) {
  return `fisora.accountant.${suffix}.v1:${userId || "anonymous"}`;
}

export function readDashboardResume(userId: string): DashboardResumeState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey(userId, "resume"));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DashboardResumeState;
    if (!parsed.clientId || !parsed.period || !parsed.segment) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeDashboardResume(userId: string, state: DashboardResumeState) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(userId, "resume"), JSON.stringify(state));
}

export function readDashboardOfficePeriod(userId: string) {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(storageKey(userId, "office-period")) || "";
}

export function writeDashboardOfficePeriod(userId: string, period: string) {
  if (typeof window === "undefined" || !period) return;
  window.localStorage.setItem(storageKey(userId, "office-period"), period);
}
