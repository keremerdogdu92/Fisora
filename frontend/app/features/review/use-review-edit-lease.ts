"use client";

import { useEffect, useRef, useState } from "react";
import {
  acquireReviewEditLease,
  releaseReviewEditLease,
  renewReviewEditLease,
  resolveApiBaseUrl,
  saveReviewWorkingDraft,
} from "../../upload-api";
import type { CorrectionDraft, LocalSession, PilotDocument } from "../../portal-types";

type LeaseStatus = "idle" | "acquiring" | "saving" | "saved" | "locked" | "stale" | "offline";
type CollaborationError = Error & { code?: string; ownerActorId?: string };

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
  const [conflictOwner, setConflictOwner] = useState("");
  const [retryNonce, setRetryNonce] = useState(0);
  const lastActivity = useRef(0);
  const documentRef = selectedDocument?.originalDocumentRef || selectedDocument?.id || "";
  const expectedRevision = Number(selectedDocument?.normalizedRevision || 0);
  const userId = session?.userId || loginUserId;
  const clientId = selectedDocument?.clientId || "";
  const sessionToken = session?.sessionToken || "";
  const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);

  function report(next: LeaseStatus) {
    setStatus(next);
    onStatus?.(next);
  }

  useEffect(() => {
    setEditLeaseId("");
    setConflictOwner("");
    report("idle");
  }, [documentRef]);

  useEffect(() => {
    if (!documentRef || !clientId || expectedRevision <= 0 || !userId || session?.role !== "accountant") return;
    let cancelled = false;
    report("acquiring");
    lastActivity.current = Date.now();
    void acquireReviewEditLease({ apiBaseUrl, clientId, documentRef, expectedRevision, userId, sessionToken })
      .then((lease) => {
        if (cancelled) return;
        setEditLeaseId(String(lease?.lease_id || documentRef));
        setConflictOwner("");
        report("saved");
      })
      .catch((error: CollaborationError) => {
        if (cancelled) return;
        if (error?.code === "edit_lease_conflict") {
          setConflictOwner(String(error.ownerActorId || ""));
          report("locked");
          return;
        }
        setConflictOwner("");
        report(String(error?.message || "").includes("revision") ? "stale" : "offline");
      });
    return () => { cancelled = true; };
  }, [apiBaseUrl, clientId, documentRef, expectedRevision, retryNonce, session?.role, sessionToken, userId]);

  useEffect(() => {
    if (!hasUnsavedReviewChanges || !editLeaseId || !documentRef || expectedRevision <= 0) return;
    const timer = window.setTimeout(() => {
      report("saving");
      void saveReviewWorkingDraft({
        apiBaseUrl,
        clientId,
        documentRef,
        editLeaseId,
        expectedRevision,
        draftLines: correctionDraft.manualDraftLines,
        correctedAccountCode: correctionDraft.accountCode,
        correctedCounterpartyCode: correctionDraft.counterpartyCode,
        reason: correctionDraft.reason || correctionDraft.ruleInstruction,
        userId,
        sessionToken,
      }).then(() => report("saved")).catch((error: CollaborationError) => {
        if (error?.code === "edit_lease_conflict") {
          setEditLeaseId("");
          setConflictOwner(String(error.ownerActorId || ""));
          report("locked");
          return;
        }
        report(String(error?.message || "").includes("revision") ? "stale" : "offline");
      });
    }, 750);
    return () => window.clearTimeout(timer);
  }, [apiBaseUrl, clientId, correctionDraft, documentRef, editLeaseId, expectedRevision, hasUnsavedReviewChanges, sessionToken, userId]);

  useEffect(() => {
    const markActivity = () => { lastActivity.current = Date.now(); };
    window.addEventListener("keydown", markActivity);
    window.addEventListener("pointerdown", markActivity);
    window.addEventListener("input", markActivity);
    const timer = window.setInterval(() => {
      if (!editLeaseId || !documentRef || document.visibilityState !== "visible" || Date.now() - lastActivity.current > 60000) return;
      void renewReviewEditLease({
        apiBaseUrl,
        clientId,
        documentRef,
        userActivityAt: new Date(lastActivity.current).toISOString(),
        userId,
        sessionToken,
      }).catch((error: CollaborationError) => {
        if (error?.code === "edit_lease_conflict") {
          setEditLeaseId("");
          setConflictOwner(String(error.ownerActorId || ""));
          report("locked");
          return;
        }
        report("offline");
      });
    }, 60000);
    return () => {
      window.removeEventListener("keydown", markActivity);
      window.removeEventListener("pointerdown", markActivity);
      window.removeEventListener("input", markActivity);
      window.clearInterval(timer);
    };
  }, [apiBaseUrl, clientId, documentRef, editLeaseId, sessionToken, userId]);

  useEffect(() => () => {
    if (editLeaseId && documentRef && clientId) {
      void releaseReviewEditLease({ apiBaseUrl, clientId, documentRef, userId, sessionToken });
    }
  }, [apiBaseUrl, clientId, documentRef, editLeaseId, sessionToken, userId]);

  return {
    conflictOwner,
    editLeaseId,
    retryAcquire: () => setRetryNonce((value) => value + 1),
    status,
  };
}
