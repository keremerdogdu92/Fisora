// File: frontend/app/features/export/use-export-commands.ts
// Summary: Coordinates export basket actions and backend package generation for accountant workflows.
"use client";

import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  addSelectedClientToBasketAction,
  markBasketPackagedAction,
  requestCancellationAction,
  resolveCancellationAction,
} from "../../portal-export-actions";
import { createWorkspaceExportPackage, resolveApiBaseUrl, sessionAuthErrorMessage } from "../../upload-api";
import type { ExportMode, LocalSession, PilotClient, PilotData, PilotDocument, ExportBasketItem } from "../../portal-types";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export function useExportCommands({
  cancelReason,
  clientDocuments,
  exportBasket,
  exportMode,
  exportType,
  loginUserId,
  selectedClient,
  selectedPeriod,
  session,
  setCancelReason,
  setClientCancellationDocumentId,
  setData,
  setExportStatus,
  setSelectedDocumentId,
}: {
  cancelReason: string;
  clientDocuments: PilotDocument[];
  exportBasket: ExportBasketItem[];
  exportMode: ExportMode;
  exportType: string;
  loginUserId: string;
  selectedClient?: PilotClient;
  selectedPeriod: string;
  session: LocalSession | null;
  setCancelReason: (value: string) => void;
  setClientCancellationDocumentId: (value: string) => void;
  setData: Dispatch<SetStateAction<PilotData>>;
  setExportStatus: (status: string) => void;
  setSelectedDocumentId: (documentId: string) => void;
}) {
  const requestCancellation = useCallback(
    (document: PilotDocument) => {
      requestCancellationAction({
        cancelReason,
        document,
        selectedClient,
        setCancelReason,
        setClientCancellationDocumentId,
        setData,
        setSelectedDocumentId,
      });
    },
    [
      cancelReason,
      selectedClient,
      setCancelReason,
      setClientCancellationDocumentId,
      setData,
      setSelectedDocumentId,
    ],
  );

  const resolveCancellation = useCallback(
    (requestId: string, status: "approved" | "rejected") => {
      resolveCancellationAction({ requestId, setData, status });
    },
    [setData],
  );

  const addSelectedClientToBasket = useCallback(() => {
    addSelectedClientToBasketAction({
      clientDocuments,
      selectedClient,
      selectedPeriod,
      setData,
      setExportStatus,
    });
  }, [clientDocuments, selectedClient, selectedPeriod, setData, setExportStatus]);

  const markBasketPackaged = useCallback(async (requestedExportType = exportType) => {
    if (!exportBasket.length) {
      setExportStatus("Cikti paketi icin once mukellef ekleyin.");
      return;
    }
    const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
    setExportStatus(`${exportBasket.length} mukellef icin ${requestedExportType} paketi uretiliyor.`);
    try {
      const packages = [];
      for (const item of exportBasket) {
        packages.push(await createWorkspaceExportPackage({
          apiBaseUrl: resolveApiBaseUrl(pageUrl()),
          clientId: item.clientId,
          exportType: requestedExportType,
          userId: actingUserId,
          sessionToken: session?.sessionToken,
        }));
      }
      markBasketPackagedAction({ exportMode, exportType: requestedExportType, setData, setExportStatus });
      const firstPackage = packages[0]?.package || packages[0] || {};
      const download = String(firstPackage.download_url || "");
      setExportStatus(download ? `${packages.length} paket hazir: ${download}` : `${packages.length} ${requestedExportType} paketi hazir.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExportStatus(`Cikti paketi uretilemedi. ${sessionAuthErrorMessage(message) || message}`);
    }
  }, [exportBasket, exportMode, exportType, loginUserId, session, setData, setExportStatus]);

  return {
    addSelectedClientToBasket,
    markBasketPackaged,
    requestCancellation,
    resolveCancellation,
  };
}
