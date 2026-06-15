"use client";

import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  addSelectedClientToBasketAction,
  markBasketPackagedAction,
  requestCancellationAction,
  resolveCancellationAction,
} from "../../portal-export-actions";
import type { ExportMode, PilotClient, PilotData, PilotDocument } from "../../portal-types";

export function useExportCommands({
  cancelReason,
  clientDocuments,
  exportMode,
  selectedClient,
  selectedPeriod,
  setCancelReason,
  setClientCancellationDocumentId,
  setData,
  setExportStatus,
  setSelectedDocumentId,
}: {
  cancelReason: string;
  clientDocuments: PilotDocument[];
  exportMode: ExportMode;
  selectedClient?: PilotClient;
  selectedPeriod: string;
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

  const markBasketPackaged = useCallback(() => {
    markBasketPackagedAction({ exportMode, setData, setExportStatus });
  }, [exportMode, setData, setExportStatus]);

  return {
    addSelectedClientToBasket,
    markBasketPackaged,
    requestCancellation,
    resolveCancellation,
  };
}
