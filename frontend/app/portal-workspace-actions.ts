import { fallbackReviewData } from "./demo-data";
import { buildPilotReadinessView, canUseLocalPilotFallback } from "./pilot-readiness";
import { emptyPilotData, normalizePilotData } from "./portal-data-mappers";
import type { LocalSession, PilotData } from "./portal-types";
import { fetchBackendPilotData, fetchBackendReadiness } from "./workspace-api";
import { resolveApiBaseUrl } from "./upload-api";

async function fetchJson(path: string) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} not found`);
  return response.json();
}

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export async function refreshBackendPilotData({
  applyPilotData,
  defaultUserId,
  session,
  shouldCancel = () => false,
}: {
  applyPilotData: (payload: PilotData, source: string) => void;
  defaultUserId: string;
  session: LocalSession | null;
  shouldCancel?: () => boolean;
}) {
  try {
    const backendPayload = await fetchBackendPilotData({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      sessionToken: session?.sessionToken,
      userId: session?.userId || defaultUserId,
    });
    const payload = normalizePilotData(backendPayload as PilotData);
    if (!payload.clients.length) return false;
    if (shouldCancel()) return true;
    applyPilotData(payload, payload.generatedFrom || "Calisma alani");
    return true;
  } catch {
    return false;
  }
}

export async function refreshBackendReadiness({
  setReadinessPayload,
  shouldCancel = () => false,
}: {
  setReadinessPayload: (payload: Record<string, unknown> | null) => void;
  shouldCancel?: () => boolean;
}) {
  try {
    const payload = await fetchBackendReadiness({ apiBaseUrl: resolveApiBaseUrl(pageUrl()) });
    if (shouldCancel()) return true;
    setReadinessPayload(payload as Record<string, unknown>);
    return true;
  } catch {
    if (!shouldCancel()) setReadinessPayload(null);
    return false;
  }
}

export async function loadInitialPilotData({
  applyPilotData,
  defaultUserId,
  explicitAllowLocalFallback,
  session,
  setLocalFallbackAllowed,
  setReadinessPayload,
  shouldCancel,
}: {
  applyPilotData: (payload: PilotData, source: string) => void;
  defaultUserId: string;
  explicitAllowLocalFallback: boolean;
  session: LocalSession | null;
  setLocalFallbackAllowed: (allowed: boolean) => void;
  setReadinessPayload: (payload: Record<string, unknown> | null) => void;
  shouldCancel: () => boolean;
}) {
  const allowLocalFallback = canUseLocalPilotFallback({
    pageUrl: pageUrl(),
    explicitAllow: explicitAllowLocalFallback,
  });
  if (!shouldCancel()) setLocalFallbackAllowed(allowLocalFallback);
  await refreshBackendReadiness({ setReadinessPayload, shouldCancel });
  if (await refreshBackendPilotData({ applyPilotData, defaultUserId, session, shouldCancel })) return;
  if (!allowLocalFallback) {
    if (!shouldCancel()) applyPilotData(emptyPilotData, "Calisma alanina erisilemedi");
    return;
  }
  const paths = ["/local-pilot-data.json", "/local-workspace-data.json", "/local-review-data.json"];
  for (const path of paths) {
    try {
      const payload = normalizePilotData(await fetchJson(path));
      if (shouldCancel()) return;
      applyPilotData(payload, "Yerel calisma verisi");
      return;
    } catch {
      // Try the next private/local source.
    }
  }
  const fallback = normalizePilotData(fallbackReviewData);
  if (!shouldCancel()) applyPilotData(fallback, "Yerel calisma verisi");
}

export { buildPilotReadinessView };
