import type { LocalSession, PilotData } from "./portal-types";

export function scopePilotDataForSession(payload: PilotData, session: LocalSession | null): PilotData {
  const delegatedClientId = session?.delegatedClientId;
  if (!delegatedClientId) return payload;
  return {
    ...payload,
    clients: payload.clients.filter((client) => client.clientId === delegatedClientId),
    documents: payload.documents.filter((document) => document.clientId === delegatedClientId),
    cancellationRequests: payload.cancellationRequests.filter((request) => request.clientId === delegatedClientId),
    exportBasket: payload.exportBasket.filter((item) => item.clientId === delegatedClientId),
  };
}
