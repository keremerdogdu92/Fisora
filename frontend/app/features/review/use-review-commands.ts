// File: frontend/app/features/review/use-review-commands.ts
// Summary: Coordinates review persistence, adjacent-document navigation, approval, and revision-safe short-window undo against the existing review APIs.
"use client";

import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  reprocessSelectedDocumentAction,
  requestStatementAiForSelectedDocumentAction,
  saveDecisionAction,
  saveStatementLineDecisionAction,
} from "../../portal-document-actions";
import type { CorrectionDraft, LocalSession, PilotData, PilotDocument, ReviewLearningDecisionOptions } from "../../portal-types";
import { reopenJournal, resolveApiBaseUrl } from "../../upload-api";

type UndoableApproval = {
  clientId: string;
  documentId: string;
  documentRef: string;
  expiresAt: number;
  fileName: string;
  revisionNo: number;
};

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

function normalizedReviewFromPayload(payload: Record<string, unknown> | null) {
  const value = payload?.normalized_review;
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function emptyCorrectionDraft(): CorrectionDraft {
  return {
    accountCode: "",
    applyToSimilar: false,
    readerValidation: "",
    accountingValidation: "",
    counterpartyCode: "",
    manualDraftLines: [],
    reason: "",
    ruleInstruction: "",
  };
}

export function useReviewCommands({
  activeReviewDocuments,
  correctionDraft,
  hasUnsavedReviewChanges,
  localFallbackAllowed,
  loginUserId,
  refreshBackendPilotData,
  selectedDocument,
  selectedStatementLineNo,
  session,
  setData,
  setDecisionStatus,
  setSelectedDocumentId,
  setSelectedStatementLineNo,
  setStatementAiStatus,
}: {
  activeReviewDocuments: PilotDocument[];
  correctionDraft: CorrectionDraft;
  hasUnsavedReviewChanges: boolean;
  localFallbackAllowed: boolean;
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedDocument?: PilotDocument;
  selectedStatementLineNo: number;
  session: LocalSession | null;
  setData: Dispatch<SetStateAction<PilotData>>;
  setDecisionStatus: (status: string) => void;
  setSelectedDocumentId: (documentId: string) => void;
  setSelectedStatementLineNo: (lineNo: number) => void;
  setStatementAiStatus: (status: string) => void;
}) {
  const [undoableApproval, setUndoableApproval] = useState<UndoableApproval | null>(null);
  const [undoAvailable, setUndoAvailable] = useState(false);

  useEffect(() => {
    if (!undoableApproval) {
      setUndoAvailable(false);
      return;
    }
    setUndoAvailable(true);
    const timeoutId = window.setTimeout(() => {
      setUndoAvailable(false);
      setUndoableApproval(null);
    }, Math.max(0, undoableApproval.expiresAt - Date.now()));
    return () => window.clearTimeout(timeoutId);
  }, [undoableApproval]);

  const selectAdjacentReviewDocument = useCallback(
    (direction: 1 | -1 = 1) => {
      if (!activeReviewDocuments.length || !selectedDocument) return;
      const currentIndex = activeReviewDocuments.findIndex((document) => document.id === selectedDocument.id);
      const nextDocument =
        activeReviewDocuments[currentIndex + direction] ??
        activeReviewDocuments[currentIndex - direction] ??
        activeReviewDocuments[0];
      if (nextDocument) setSelectedDocumentId(nextDocument.id);
    },
    [activeReviewDocuments, selectedDocument, setSelectedDocumentId],
  );

  const requestStatementAiForSelectedDocument = useCallback(() => {
    void requestStatementAiForSelectedDocumentAction({
      selectedDocument,
      session,
      setData,
      setStatementAiStatus,
    });
  }, [selectedDocument, session, setData, setStatementAiStatus]);

  const saveStatementLineDecision = useCallback(
    (action: string) => {
      return saveStatementLineDecisionAction({
        action,
        correctionDraft,
        localFallbackAllowed,
        loginUserId,
        refreshBackendPilotData,
        selectedDocument,
        selectedStatementLineNo,
        session,
        setData,
        setDecisionStatus,
      });
    },
    [
      correctionDraft,
      localFallbackAllowed,
      loginUserId,
      refreshBackendPilotData,
      selectedDocument,
      selectedStatementLineNo,
      session,
      setData,
      setDecisionStatus,
    ],
  );

  const persistDecision = useCallback(
    (action: string, options: ReviewLearningDecisionOptions = {}) => {
      return saveDecisionAction({
        action,
        correctionDraft,
        learningOptions: options,
        localFallbackAllowed,
        loginUserId,
        refreshBackendPilotData,
        selectedDocument,
        session,
        setData,
        setDecisionStatus,
      });
    },
    [
      correctionDraft,
      localFallbackAllowed,
      loginUserId,
      refreshBackendPilotData,
      selectedDocument,
      session,
      setData,
      setDecisionStatus,
    ],
  );


  const saveDecision = useCallback(
    async (action: string, options: ReviewLearningDecisionOptions = {}) => {
      return persistDecision(action, options);
    },
    [persistDecision],
  );

  const reprocessSelectedDocument = useCallback(() => {
    return reprocessSelectedDocumentAction({
      loginUserId,
      refreshBackendPilotData,
      selectedDocument,
      session,
      setDecisionStatus,
    });
  }, [
    loginUserId,
    refreshBackendPilotData,
    selectedDocument,
    session,
    setDecisionStatus,
  ]);

  const approveSelectedAndMoveNext = useCallback(async () => {
    if (!selectedDocument) return;
    const approveAction = hasUnsavedReviewChanges ? "approve_with_changes" : "approve";
    const selectedLineIndex = selectedDocument.statementLines.findIndex(
      (line) => line.line_no === selectedStatementLineNo,
    );
    if (selectedDocument.statementLines.length && selectedLineIndex >= 0) {
      await saveStatementLineDecision(approveAction);
      const nextLine = selectedDocument.statementLines[selectedLineIndex + 1];
      if (nextLine) {
        setSelectedStatementLineNo(nextLine.line_no);
        return;
      }
      selectAdjacentReviewDocument(1);
      return;
    }
    const result = await saveDecision(approveAction);
    const normalizedReview = result?.ok ? normalizedReviewFromPayload(result.payload) : null;
    const revisionNo = Number(normalizedReview?.revision_no || 0);
    if (normalizedReview?.approved === true && revisionNo > 0) {
      setUndoableApproval({
        clientId: selectedDocument.clientId,
        documentId: selectedDocument.id,
        documentRef: selectedDocument.id,
        expiresAt: Date.now() + 8000,
        fileName: selectedDocument.fileName,
        revisionNo,
      });
    } else {
      setUndoableApproval(null);
    }
    selectAdjacentReviewDocument(1);
  }, [
    hasUnsavedReviewChanges,
    saveDecision,
    saveStatementLineDecision,
    selectAdjacentReviewDocument,
    selectedDocument,
    selectedStatementLineNo,
    setSelectedStatementLineNo,
  ]);

  const undoLastApproval = useCallback(async () => {
    const approval = undoableApproval;
    if (!approval || Date.now() > approval.expiresAt) return false;
    const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim();
    setDecisionStatus(`${approval.fileName}: son onay geri alınıyor.`);
    try {
      await reopenJournal({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        clientId: approval.clientId,
        documentRef: approval.documentRef,
        expectedRevision: approval.revisionNo,
        reason: "Son onay 8 saniye içinde geri alındı.",
        userId: reviewer,
        sessionToken: session?.sessionToken || "",
      });
      await refreshBackendPilotData();
      setSelectedDocumentId(approval.documentId);
      setDecisionStatus(`${approval.fileName}: onay geri alındı; belge yeniden kontrolde.`);
      setUndoableApproval(null);
      return true;
    } catch (error) {
      setDecisionStatus(error instanceof Error ? error.message : String(error));
      setUndoableApproval(null);
      return false;
    }
  }, [loginUserId, refreshBackendPilotData, session, setDecisionStatus, setSelectedDocumentId, undoableApproval]);

  return {
    approveSelectedAndMoveNext,
    reprocessSelectedDocument,
    requestStatementAiForSelectedDocument,
    saveDecision,
    saveStatementLineDecision,
    selectAdjacentReviewDocument,
    undoAvailable,
    undoLastApproval,
  };
}
