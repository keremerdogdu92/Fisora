import { useState } from "react";
import {
  applyDocumentRetentionAction,
  previewDocumentRetention,
  resolveApiBaseUrl,
} from "../../upload-api";
import type { LocalSession } from "../../portal-types";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export function useDocumentRetentionCommands({
  defaultUserId,
  loginUserId,
  refreshBackendPilotData,
  session,
}: {
  defaultUserId: string;
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  session: LocalSession | null;
}) {
  const [retentionStatus, setRetentionStatus] = useState("");
  const [retentionDocuments, setRetentionDocuments] = useState<Array<Record<string, unknown>>>([]);

  async function previewRetention() {
    const actingUserId = session?.userId || loginUserId.trim() || defaultUserId;
    setRetentionStatus("Belge saklama onizlemesi hazirlaniyor.");
    try {
      const result = await previewDocumentRetention({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        userId: actingUserId,
        sessionToken: session?.sessionToken,
      });
      const documents = Array.isArray(result.documents) ? result.documents : [];
      setRetentionDocuments(documents);
      setRetentionStatus(`${documents.length} belge icin saklama aksiyonu bekliyor.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRetentionStatus(`Belge saklama onizlemesi alinamadi. ${message}`);
    }
  }

  async function applyRetentionAction(action: "delete" | "extend_90_days") {
    const refs = retentionDocuments
      .map((document) => String(document.document_key || document.document_ref || "").trim())
      .filter(Boolean);
    if (!refs.length) {
      setRetentionStatus("Islem icin once saklama onizlemesi alin.");
      return;
    }
    const actingUserId = session?.userId || loginUserId.trim() || defaultUserId;
    setRetentionStatus(action === "delete" ? `${refs.length} belge siliniyor.` : `${refs.length} belge 90 gun uzatiliyor.`);
    try {
      const result = await applyDocumentRetentionAction({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        documentRefs: refs,
        action,
        deleteFiles: true,
        userId: actingUserId,
        sessionToken: session?.sessionToken,
      });
      const count = action === "delete" ? Number(result.deleted_count || 0) : Number(result.extended_count || 0);
      setRetentionStatus(action === "delete" ? `${count} belge silindi.` : `${count} belge 90 gun uzatildi.`);
      setRetentionDocuments([]);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRetentionStatus(`Belge saklama islemi tamamlanamadi. ${message}`);
    }
  }

  return {
    deleteRetentionDocuments: () => void applyRetentionAction("delete"),
    extendRetentionDocuments: () => void applyRetentionAction("extend_90_days"),
    previewRetention: () => void previewRetention(),
    retentionDocuments,
    retentionStatus,
  };
}
