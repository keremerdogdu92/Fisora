"use client";

import { useState } from "react";
import type { LocalSession } from "../../portal-types";
import { resetTestData, resolveApiBaseUrl } from "../../upload-api";

export function useTestDataReset({
  loginUserId,
  refreshBackendPilotData,
  session,
  setSelectedClientId,
  setSelectedDocumentId,
}: {
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  session: LocalSession | null;
  setSelectedClientId: (value: string) => void;
  setSelectedDocumentId: (value: string) => void;
}) {
  const [resetConfirmation, setResetConfirmation] = useState("");
  const [resetStatus, setResetStatus] = useState("");

  async function onResetTestData() {
    if (session?.role !== "accountant") {
      setResetStatus("Bu işlem için müşavir oturumu gerekli.");
      return;
    }
    if (resetConfirmation.trim() !== "TEMIZLE") {
      setResetStatus("Onay alanına TEMIZLE yazın.");
      return;
    }
    setResetStatus("Test verisi temizleniyor.");
    try {
      const result = await resetTestData({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        confirmation: resetConfirmation,
        userId: session.userId || loginUserId,
        sessionToken: session.sessionToken,
      });
      await refreshBackendPilotData();
      setSelectedClientId("");
      setSelectedDocumentId("");
      setResetConfirmation("");
      setResetStatus(
        `Temizlendi: ${Number(result.deleted_client_count || 0)} mükellef, ${Number(result.deleted_file_count || 0)} dosya. Müşavir hesabı korundu.`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setResetStatus(`Temizleme başarısız. ${message}`);
    }
  }

  return {
    onResetTestData,
    resetConfirmation,
    resetStatus,
    setResetConfirmation,
  };
}
