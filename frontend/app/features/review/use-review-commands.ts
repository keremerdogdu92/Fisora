"use client";

import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  requestStatementAiForSelectedDocumentAction,
  saveDecisionAction,
  saveStatementLineDecisionAction,
} from "../../portal-document-actions";
import type { CorrectionDraft, LocalSession, PilotData, PilotDocument } from "../../portal-types";

export function useReviewCommands({
  activeReviewDocuments,
  correctionDraft,
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

  const saveDecision = useCallback(
    (action: string) => {
      return saveDecisionAction({
        action,
        correctionDraft,
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

  const approveSelectedAndMoveNext = useCallback(async () => {
    if (!selectedDocument) return;
    const selectedLineIndex = selectedDocument.statementLines.findIndex(
      (line) => line.line_no === selectedStatementLineNo,
    );
    if (selectedDocument.statementLines.length && selectedLineIndex >= 0) {
      await saveStatementLineDecision("approve");
      const nextLine = selectedDocument.statementLines[selectedLineIndex + 1];
      if (nextLine) {
        setSelectedStatementLineNo(nextLine.line_no);
        return;
      }
      selectAdjacentReviewDocument(1);
      return;
    }
    await saveDecision("approve");
    selectAdjacentReviewDocument(1);
  }, [
    saveDecision,
    saveStatementLineDecision,
    selectAdjacentReviewDocument,
    selectedDocument,
    selectedStatementLineNo,
    setSelectedStatementLineNo,
  ]);

  return {
    approveSelectedAndMoveNext,
    requestStatementAiForSelectedDocument,
    saveDecision,
    saveStatementLineDecision,
    selectAdjacentReviewDocument,
  };
}
