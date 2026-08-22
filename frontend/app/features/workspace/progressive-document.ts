// File: frontend/app/features/workspace/progressive-document.ts
// Summary: Keeps selected-document progressive processing isolated from the portal shell and refreshes terminal jobs once.
"use client";

import { useEffect, useMemo, useRef } from "react";
import type { LocalSession, PilotDocument } from "../../portal-types";
import { mergeProcessingJobIntoDocument } from "../../workspace-api";
import { useSelectedDocumentProgressQuery } from "./queries";

type ProgressiveDocumentArgs = {
  activeReviewDocuments: PilotDocument[];
  clientDocuments: PilotDocument[];
  defaultUserId: string;
  enabled: boolean;
  refreshBackendPilotData: () => unknown | Promise<unknown>;
  selectedDocument?: PilotDocument;
  session: LocalSession | null;
};

export function useProgressiveSelectedDocument({
  activeReviewDocuments,
  clientDocuments,
  defaultUserId,
  enabled,
  refreshBackendPilotData,
  selectedDocument,
  session,
}: ProgressiveDocumentArgs) {
  const needsProgress = enabled && Boolean(selectedDocument)
    && ["queued", "processing"].includes(selectedDocument?.status ?? "");
  const progressQuery = useSelectedDocumentProgressQuery({
    clientId: selectedDocument?.clientId ?? "",
    defaultUserId,
    documentRef: selectedDocument?.id ?? "",
    enabled: needsProgress,
    session,
  });
  const progressiveSelectedDocument = useMemo(
    () => selectedDocument && progressQuery.data?.job
      ? mergeProcessingJobIntoDocument(selectedDocument, progressQuery.data.job)
      : selectedDocument,
    [progressQuery.data, selectedDocument],
  );
  const progressiveClientDocuments = useMemo(
    () => progressiveSelectedDocument
      ? clientDocuments.map((document) => document.id === progressiveSelectedDocument.id ? progressiveSelectedDocument : document)
      : clientDocuments,
    [clientDocuments, progressiveSelectedDocument],
  );
  const progressiveActiveReviewDocuments = useMemo(
    () => progressiveSelectedDocument
      ? activeReviewDocuments.map((document) => document.id === progressiveSelectedDocument.id ? progressiveSelectedDocument : document)
      : activeReviewDocuments,
    [activeReviewDocuments, progressiveSelectedDocument],
  );
  const terminalRefreshRef = useRef("");
  useEffect(() => {
    const progress = progressQuery.data;
    if (!progress?.terminal || !progress?.job) return;
    const refreshKey = `${progress.job.id || selectedDocument?.id}:${progress.job.attempt_count || 0}:${progress.job.updated_at || ""}`;
    if (terminalRefreshRef.current === refreshKey) return;
    terminalRefreshRef.current = refreshKey;
    void refreshBackendPilotData();
  }, [progressQuery.data, refreshBackendPilotData, selectedDocument?.id]);

  return {
    progressiveActiveReviewDocuments,
    progressiveClientDocuments,
    progressiveSelectedDocument,
  };
}
