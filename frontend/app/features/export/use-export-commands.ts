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
import { createWorkspaceExportPackage, resolveApiBaseUrl, userSafeErrorMessage } from "../../upload-api";
import type { ExportMode, LocalSession, PilotClient, PilotData, PilotDocument, ExportBasketItem } from "../../portal-types";

const DIRECT_OUTPUT_STATUSES = new Set(["export_ready", "export_added", "exported"]);

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export function useExportCommands({
  cancelReason,
  clientDocuments,
  directApprovedScope,
  documents,
  exportBasket,
  exportMode,
  exportType,
  loginUserId,
  outputPeriod,
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
  directApprovedScope: boolean;
  documents: PilotDocument[];
  exportBasket: ExportBasketItem[];
  exportMode: ExportMode;
  exportType: string;
  loginUserId: string;
  outputPeriod: string;
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
    const directDocuments = directApprovedScope
      ? documents.filter((document) => document.period === outputPeriod && DIRECT_OUTPUT_STATUSES.has(document.status))
      : [];
    const targets = directApprovedScope
      ? Array.from(new Set(directDocuments.map((document) => document.clientId))).map((clientId) => ({ clientId, period: outputPeriod }))
      : exportBasket.map((item) => ({ clientId: item.clientId, period: item.period || selectedPeriod }));
    if (!targets.length) {
      setExportStatus(directApprovedScope ? "Bu dönemde çıktıya uygun onaylı belge yok." : "Çıktı paketi için önce mükellef ekleyin.");
      return;
    }
    const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
    setExportStatus(`${targets.length} mükellef için çıktı paketi hazırlanıyor.`);
    try {
      const packages = [];
      for (const target of targets) {
        packages.push(await createWorkspaceExportPackage({
          apiBaseUrl: resolveApiBaseUrl(pageUrl()), clientId: target.clientId, period: target.period,
          exportType: requestedExportType, userId: actingUserId, sessionToken: session?.sessionToken,
        }));
      }
      if (!directApprovedScope) markBasketPackagedAction({ exportMode, exportType: requestedExportType, setData, setExportStatus });
      const firstPackage = packages[0]?.package || packages[0] || {};
      const download = String(firstPackage.download_url || "");
      setExportStatus(download ? `${packages.length} paket hazır: ${download}` : `${packages.length} çıktı paketi hazır.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExportStatus(userSafeErrorMessage(message, "Çıktı paketi üretilemedi. Tekrar deneyin."));
    }
  }, [directApprovedScope, documents, exportBasket, exportMode, exportType, loginUserId, outputPeriod, selectedPeriod, session, setData, setExportStatus]);

  return {
    addSelectedClientToBasket,
    markBasketPackaged,
    requestCancellation,
    resolveCancellation,
  };
}
