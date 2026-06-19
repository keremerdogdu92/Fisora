"use client";

import { useQuery } from "@tanstack/react-query";
import { emptyPilotData, normalizePilotData } from "../../portal-data-mappers";
import type { AiCapacityView, LocalSession, PilotData } from "../../portal-types";
import { fetchAiCapacity, fetchBackendPilotData, fetchBackendReadiness } from "../../workspace-api";
import { resolveApiBaseUrl } from "../../upload-api";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export const workspaceQueryKeys = {
  data: (userId: string, sessionToken?: string) =>
    ["workspace", "data", userId, sessionToken ?? "anonymous"] as const,
  aiCapacity: (userId: string, sessionToken?: string) =>
    ["workspace", "ai-capacity", userId, sessionToken ?? "anonymous"] as const,
  readiness: () => ["workspace", "readiness"] as const,
};

export function useWorkspaceDataQuery({
  defaultUserId,
  session,
}: {
  defaultUserId: string;
  session: LocalSession | null;
}) {
  const userId = session?.userId || defaultUserId;

  return useQuery({
    queryKey: workspaceQueryKeys.data(userId, session?.sessionToken),
    queryFn: async (): Promise<PilotData> => {
      const payload = await fetchBackendPilotData({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        sessionToken: session?.sessionToken,
        userId,
      });
      return normalizePilotData(payload as PilotData);
    },
    initialData: emptyPilotData,
  });
}

export function usePilotReadinessQuery() {
  return useQuery({
    queryKey: workspaceQueryKeys.readiness(),
    queryFn: async () =>
      (await fetchBackendReadiness({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      })) as Record<string, unknown>,
  });
}

export function useAiCapacityQuery({
  defaultUserId,
  session,
}: {
  defaultUserId: string;
  session: LocalSession | null;
}) {
  const userId = session?.userId || defaultUserId;

  return useQuery({
    queryKey: workspaceQueryKeys.aiCapacity(userId, session?.sessionToken),
    queryFn: async (): Promise<AiCapacityView> =>
      (await fetchAiCapacity({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        sessionToken: session?.sessionToken,
        userId,
      })) as AiCapacityView,
  });
}
