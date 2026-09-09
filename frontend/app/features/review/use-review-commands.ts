// File: frontend/app/features/review/use-review-commands.ts
// Summary: Coordinates review persistence, adjacent-document navigation, approval, and revision-safe operation-based undo against the existing review APIs.
"use client";

import { useCallback, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  reprocessSelectedDocumentAction,
  requestStatementAiForSelectedDocumentAction,
  saveDecisionAction,
  saveStatementLineDecisionAction,
} from "../../portal-document-actions";
import { reviewActionLabel } from "../../portal-formatters";
import type { CorrectionDraft, LocalSession, PilotData, PilotDocument, PilotStatus, ReviewLearningDecisionOptions } from "../../portal-types";
import { reopenJournal, resolveApiBaseUrl, storeReviewDecision } from "../../upload-api";

type ReviewRestoreAction = "reopen_approval" | "approve" | "review_required" | "exclude_export";

type UndoableReviewAction = {
  amount: string;
  category: string;
  clientId: string;
  documentId: string;
  documentRef: string;
  fileName: string;
  provider: string;
  restoreAction: ReviewRestoreAction;
  revisionNo: number;
  summary: string;
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

function formatReviewAmount(value: string) {
  const parsed = Number(String(value || "").replace(",", "."));
  if (!Number.isFinite(parsed)) return String(value || "").trim();
  return `${new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(parsed)} TL`;
}

function reviewActionSummaryParts(provider: string, fileName: string, amount: string, label: string) {
  const subject = String(provider || fileName || "Belge").trim();
  const formattedAmount = formatReviewAmount(amount);
  return [subject, formattedAmount, label].filter(Boolean).join(" · ");
}

function reviewActionSummary(document: PilotDocument, label: string) {
  return reviewActionSummaryParts(document.provider, document.fileName, document.amount, label);
}

function restoreActionFor(previousStatus: PilotStatus, action: string, normalizedReview: Record<string, unknown> | null): ReviewRestoreAction | null {
  const normalizedStatus = String(normalizedReview?.status || "");
  if ((action === "approve" || action === "approve_with_changes") && normalizedReview?.approved === true) return "reopen_approval";
  if (action === "exclude_export" && normalizedStatus === "rejected") {
    if (previousStatus === "export_ready") return "approve";
    if (previousStatus === "review_required") return "review_required";
  }
  if (action === "review_required" && normalizedStatus === "review_required") {
    if (previousStatus === "export_ready") return "approve";
    if (previousStatus === "excluded") return "exclude_export";
  }
  return null;
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
  setCorrectionDraft,
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
  setCorrectionDraft: Dispatch<SetStateAction<CorrectionDraft>>;
  setSelectedDocumentId: (documentId: string) => void;
  setSelectedStatementLineNo: (lineNo: number) => void;
  setStatementAiStatus: (status: string) => void;
}) {
  const [undoableReviewAction, setUndoableReviewAction] = useState<UndoableReviewAction | null>(null);
  const [lastReviewActionLabel, setLastReviewActionLabel] = useState("");
  const undoAvailable = Boolean(undoableReviewAction);

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
      const document = selectedDocument;
      if (!document) return undefined;
      const previousStatus = document.status;

      if (action === "review_required" && previousStatus === "export_ready") {
        const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim();
        try {
          const payload = await reopenJournal({
            apiBaseUrl: resolveApiBaseUrl(pageUrl()),
            clientId: document.clientId,
            documentRef: document.id,
            expectedRevision: document.normalizedRevision || 0,
            reason: "Müşavir onayı geri alındı; fiş taslağı ve kaynağı korunarak yeniden kontrole açıldı.",
            userId: reviewer,
            sessionToken: session?.sessionToken || "",
          });
          await refreshBackendPilotData();
          setCorrectionDraft(emptyCorrectionDraft());
          const revisionNo = Number((payload as Record<string, unknown>)?.revision_no || 0);
          const summary = reviewActionSummary(document, "Kontrole geri alındı");
          setDecisionStatus(`${document.fileName}: kontrole geri alındı; fiş kaynağı korunuyor.`);
          setLastReviewActionLabel(summary);
          setUndoableReviewAction(revisionNo > 0 ? {
            amount: document.amount,
            category: document.productCategory,
            clientId: document.clientId,
            documentId: document.id,
            documentRef: document.id,
            fileName: document.fileName,
            provider: document.provider,
            restoreAction: "approve",
            revisionNo,
            summary,
          } : null);
          return { ok: true, payload: { normalized_review: { status: "review_required", revision_no: revisionNo } } };
        } catch (error) {
          await refreshBackendPilotData();
          setDecisionStatus(error instanceof Error ? error.message : String(error));
          return { ok: false, payload: null };
        }
      }

      const result = await persistDecision(action, options);
      if (!result?.ok) return result;

      const normalizedReview = normalizedReviewFromPayload(result.payload);
      const revisionNo = Number(normalizedReview?.revision_no || 0);
      const actionLabel = action === "review_required" && (previousStatus === "export_ready" || previousStatus === "excluded")
        ? "Kontrole geri alındı"
        : reviewActionLabel(action);
      const summary = reviewActionSummary(document, actionLabel);
      setLastReviewActionLabel(summary);
      setUndoableReviewAction(null);

      const restoreAction = revisionNo > 0 ? restoreActionFor(previousStatus, action, normalizedReview) : null;
      if (restoreAction) {
        setUndoableReviewAction({
          amount: document.amount,
          category: document.productCategory,
          clientId: document.clientId,
          documentId: document.id,
          documentRef: document.id,
          fileName: document.fileName,
          provider: document.provider,
          restoreAction,
          revisionNo,
          summary,
        });
      }
      return result;
    },
    [loginUserId, persistDecision, refreshBackendPilotData, selectedDocument, session, setCorrectionDraft, setDecisionStatus],
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
    if (!result?.ok) return;
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

  const undoLastReviewAction = useCallback(async () => {
    const reviewAction = undoableReviewAction;
    if (!reviewAction) return false;
    const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim();
    setDecisionStatus(`${reviewAction.fileName}: son işlem geri alınıyor.`);
    try {
      if (reviewAction.restoreAction === "reopen_approval") {
        await reopenJournal({
          apiBaseUrl: resolveApiBaseUrl(pageUrl()),
          clientId: reviewAction.clientId,
          documentRef: reviewAction.documentRef,
          expectedRevision: reviewAction.revisionNo,
          reason: "Son müşavir onayı işlem bazlı geri alındı.",
          userId: reviewer,
          sessionToken: session?.sessionToken || "",
        });
      } else {
        await storeReviewDecision({
          apiBaseUrl: resolveApiBaseUrl(pageUrl()),
          clientId: reviewAction.clientId,
          userId: reviewer,
          documentRef: reviewAction.documentRef,
          action: reviewAction.restoreAction,
          reviewer,
          category: reviewAction.category,
          reason: "Son müşavir işlemi geri alındı.",
          decisionNote: "Son müşavir işlemi geri alındı.",
          expectedRevision: reviewAction.revisionNo,
          sessionToken: session?.sessionToken || "",
        });
      }
      await refreshBackendPilotData();
      setSelectedDocumentId(reviewAction.documentId);
      setDecisionStatus(`${reviewAction.fileName}: son işlem geri alındı; belge yeniden açıldı.`);
      setLastReviewActionLabel(reviewActionSummaryParts(reviewAction.provider, reviewAction.fileName, reviewAction.amount, "Geri alındı"));
      setUndoableReviewAction(null);
      return true;
    } catch (error) {
      await refreshBackendPilotData();
      setDecisionStatus(error instanceof Error ? error.message : String(error));
      setLastReviewActionLabel(`${reviewAction.summary} · Geri alma tamamlanamadı`);
      setUndoableReviewAction(null);
      return false;
    }
  }, [loginUserId, refreshBackendPilotData, session, setDecisionStatus, setSelectedDocumentId, undoableReviewAction]);

  return {
    approveSelectedAndMoveNext,
    reprocessSelectedDocument,
    requestStatementAiForSelectedDocument,
    saveDecision,
    saveStatementLineDecision,
    selectAdjacentReviewDocument,
    lastReviewActionLabel,
    undoAvailable,
    undoLastReviewAction,
  };
}
