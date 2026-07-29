"use client";

import { useEffect, useRef, useState } from "react";
import { acquireReviewEditLease, releaseReviewEditLease, renewReviewEditLease, resolveApiBaseUrl, saveReviewWorkingDraft } from "../../upload-api";
import type { CorrectionDraft, LocalSession, PilotDocument } from "../../portal-types";

type LeaseStatus = "idle" | "acquiring" | "saving" | "saved" | "stale" | "offline";

export function useReviewEditLease({
  correctionDraft,
  hasUnsavedReviewChanges,
  loginUserId,
  selectedDocument,
  session,
  onStatus,
}: {
  correctionDraft: CorrectionDraft;
  hasUnsavedReviewChanges: boolean;
  loginUserId: string;
  selectedDocument?: PilotDocument;
  session: LocalSession | null;
  onStatus?: (status: LeaseStatus) => void;
}) {
  const [status, setStatus] = useState<LeaseStatus>("idle");
  const [editLeaseId, setEditLeaseId] = useState("");
  const previousDirty = useRef(false);
  const lastActivity = useRef(0);
  const documentRef = selectedDocument?.originalDocumentRef || selectedDocument?.id || "";
  const expectedRevision = Number(selectedDocument?.normalizedRevision || 0);
  const userId = session?.userId || loginUserId;
  const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);

  function report(next: LeaseStatus) {
    setStatus(next);
    onStatus?.(next);
  }

  useEffect(() => {
    previousDirty.current = false;
    setEditLeaseId("");
    report("idle");
  }, [documentRef]);

  useEffect(() => {
    if (!hasUnsavedReviewChanges || previousDirty.current || !documentRef || expectedRevision <= 0) {
      previousDirty.current = hasUnsavedReviewChanges;
      return;
    }
    previousDirty.current = true;
    lastActivity.current = Date.now();
    let cancelled = false;
    report("acquiring");
    void acquireReviewEditLease({ apiBaseUrl, clientId: selectedDocument?.clientId || "", documentRef, expectedRevision, userId, sessionToken: session?.sessionToken || "" })
      .then((lease) => { if (!cancelled) { setEditLeaseId(String(lease?.lease_id || documentRef)); report("saved"); } })
      .catch((error) => { if (!cancelled) report(String(error).includes("revision") ? "stale" : "offline"); });
    return () => { cancelled = true; };
  }, [apiBaseUrl, documentRef, expectedRevision, hasUnsavedReviewChanges, selectedDocument?.clientId, session?.sessionToken, userId]);

  useEffect(() => {
    if (!hasUnsavedReviewChanges || !editLeaseId || !documentRef || expectedRevision <= 0) return;
    const timer = window.setTimeout(() => {
      report("saving");
      void saveReviewWorkingDraft({
        apiBaseUrl,
        clientId: selectedDocument?.clientId || "",
        documentRef,
        editLeaseId,
        expectedRevision,
        draftLines: correctionDraft.manualDraftLines,
        correctedAccountCode: correctionDraft.accountCode,
        correctedCounterpartyCode: correctionDraft.counterpartyCode,
        reason: correctionDraft.reason || correctionDraft.ruleInstruction,
        userId,
        sessionToken: session?.sessionToken || "",
      }).then(() => report("saved")).catch((error) => report(String(error).includes("revision") ? "stale" : "offline"));
    }, 750);
    return () => window.clearTimeout(timer);
  }, [apiBaseUrl, correctionDraft, documentRef, editLeaseId, expectedRevision, hasUnsavedReviewChanges, selectedDocument?.clientId, session?.sessionToken, userId]);

  useEffect(() => {
    const markActivity = () => { lastActivity.current = Date.now(); };
    window.addEventListener("keydown", markActivity);
    window.addEventListener("pointerdown", markActivity);
    window.addEventListener("input", markActivity);
    const timer = window.setInterval(() => {
      if (!editLeaseId || !documentRef || document.visibilityState !== "visible" || Date.now() - lastActivity.current > 60000) return;
      void renewReviewEditLease({ apiBaseUrl, clientId: selectedDocument?.clientId || "", documentRef, userActivityAt: new Date(lastActivity.current).toISOString(), userId, sessionToken: session?.sessionToken || "" }).catch(() => report("offline"));
    }, 60000);
    return () => {
      window.removeEventListener("keydown", markActivity);
      window.removeEventListener("pointerdown", markActivity);
      window.removeEventListener("input", markActivity);
      window.clearInterval(timer);
    };
  }, [apiBaseUrl, documentRef, editLeaseId, selectedDocument?.clientId, session?.sessionToken, userId]);

  useEffect(() => () => {
    if (editLeaseId && documentRef && selectedDocument?.clientId) {
      void releaseReviewEditLease({ apiBaseUrl, clientId: selectedDocument.clientId, documentRef, userId, sessionToken: session?.sessionToken || "" });
    }
  }, [apiBaseUrl, documentRef, editLeaseId, selectedDocument?.clientId, session?.sessionToken, userId]);

  return { editLeaseId, status };
}
