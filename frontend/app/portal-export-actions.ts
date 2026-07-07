import type { Dispatch, SetStateAction } from "react";
import type { CancellationRequest, ExportBasketItem, ExportMode, PilotClient, PilotData, PilotDocument } from "./portal-types";

export function requestCancellationAction({
  cancelReason,
  document,
  selectedClient,
  setCancelReason,
  setClientCancellationDocumentId,
  setData,
  setSelectedDocumentId,
}: {
  cancelReason: string;
  document: PilotDocument;
  selectedClient?: PilotClient;
  setCancelReason: (value: string) => void;
  setClientCancellationDocumentId: (value: string) => void;
  setData: Dispatch<SetStateAction<PilotData>>;
  setSelectedDocumentId: (documentId: string) => void;
}) {
  const request: CancellationRequest = {
    id: `${document.id}-request-${Date.now()}`,
    documentId: document.id,
    clientId: document.clientId,
    fileName: document.fileName,
    requestedBy: selectedClient?.userLabel ?? "Mükellef kullanıcısı",
    requestedAt: new Date().toLocaleString("tr-TR"),
    reason: cancelReason.trim() || "Mükellef iptal veya düzeltme talebi gönderdi.",
    stage: document.status === "exported" || document.status === "export_added" ? "post_export" : "pre_export",
    status: "open",
  };
  setData((current) => ({
    ...current,
    cancellationRequests: [request, ...current.cancellationRequests],
    documents: current.documents.map((item) =>
      item.id === document.id
        ? { ...item, status: request.stage === "post_export" ? "post_export_correction_requested" : "cancel_requested" }
        : item,
    ),
  }));
  setCancelReason("");
  setClientCancellationDocumentId("");
  setSelectedDocumentId(document.id);
}

export function resolveCancellationAction({
  requestId,
  setData,
  status,
}: {
  requestId: string;
  setData: Dispatch<SetStateAction<PilotData>>;
  status: "approved" | "rejected";
}) {
  setData((current) => ({
    ...current,
    cancellationRequests: current.cancellationRequests.map((request) =>
      request.id === requestId ? { ...request, status } : request,
    ),
    documents: current.documents.map((document) => {
      const request = current.cancellationRequests.find((item) => item.id === requestId);
      if (!request || request.documentId !== document.id) return document;
      return { ...document, status: status === "approved" ? "cancel_approved" : "cancel_rejected" };
    }),
  }));
}

export function addSelectedClientToBasketAction({
  clientDocuments,
  selectedClient,
  selectedPeriod,
  setData,
  setExportStatus,
}: {
  clientDocuments: PilotDocument[];
  selectedClient?: PilotClient;
  selectedPeriod: string;
  setData: Dispatch<SetStateAction<PilotData>>;
  setExportStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const readyDocuments = clientDocuments.filter((document) => document.status === "export_ready" || document.status === "export_added");
  if (!readyDocuments.length) {
    setExportStatus("Bu mukellefte ciktiya uygun belge yok.");
    return;
  }
  const item: ExportBasketItem = {
    id: `${selectedClient.clientId}-${Date.now()}`,
    clientId: selectedClient.clientId,
    clientName: selectedClient.clientName,
    documentIds: readyDocuments.map((document) => document.id),
    documentCount: readyDocuments.length,
    period: selectedPeriod || readyDocuments[0].period,
    status: "ready",
  };
  setData((current) => ({
    ...current,
    exportBasket: [item, ...current.exportBasket.filter((basketItem) => basketItem.clientId !== selectedClient.clientId)],
    documents: current.documents.map((document) =>
      item.documentIds.includes(document.id) ? { ...document, status: "export_added" } : document,
    ),
  }));
  setExportStatus(`${selectedClient.clientName} cikti listesine eklendi.`);
}

export function markBasketPackagedAction({
  exportMode,
  exportType = "zirve_mapping_csv",
  setData,
  setExportStatus,
}: {
  exportMode: ExportMode;
  exportType?: string;
  setData: Dispatch<SetStateAction<PilotData>>;
  setExportStatus: (status: string) => void;
}) {
  setData((current) => ({
    ...current,
    exportBasket: current.exportBasket.map((item) => ({ ...item, status: "packaged" })),
    documents: current.documents.map((document) =>
      current.exportBasket.some((item) => item.documentIds.includes(document.id)) ? { ...document, status: "exported" } : document,
    ),
  }));
  setExportStatus(exportMode === "bulk" ? `Secili mukellefler icin ${exportType} paketi hazir.` : `Mukellef bazli ${exportType} paketleri hazir.`);
}
