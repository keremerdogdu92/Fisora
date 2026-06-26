"use client";

import { useEffect, useMemo, useState } from "react";
import { documentsForProcessing } from "../../portal-dashboard";
import type { DocumentSegment, PilotDocument, ReviewFilter } from "../../portal-types";
import {
  reviewFilteredDocuments,
  selectedDocumentFromState,
} from "./document-workflow-model";

export function useDocumentWorkflow({
  allDocuments,
  clientDocuments,
  mode,
  selectedClientId,
}: {
  allDocuments: PilotDocument[];
  clientDocuments: PilotDocument[];
  mode: string;
  selectedClientId?: string;
}) {
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [selectedDocumentSegment, setSelectedDocumentSegment] = useState<DocumentSegment>("invoices");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("review_required");
  const [selectedStatementLineNo, setSelectedStatementLineNo] = useState(0);

  const segmentedClientDocuments = useMemo(() => {
    return documentsForProcessing({
      documents: allDocuments,
      clientId: selectedClientId,
      segment: selectedDocumentSegment,
    }) as PilotDocument[];
  }, [allDocuments, selectedClientId, selectedDocumentSegment]);

  const visibleReviewDocuments = useMemo(() => {
    return reviewFilteredDocuments({ documents: clientDocuments, reviewFilter }) as PilotDocument[];
  }, [clientDocuments, reviewFilter]);

  const visibleProcessingDocuments = useMemo(() => {
    return reviewFilteredDocuments({ documents: segmentedClientDocuments, reviewFilter }) as PilotDocument[];
  }, [reviewFilter, segmentedClientDocuments]);

  const activeReviewDocuments = mode === "documents" ? visibleProcessingDocuments : visibleReviewDocuments;
  const selectedDocument = selectedDocumentFromState({
    clientDocuments,
    selectedDocumentId,
    selectedDocumentSegment,
  }) as PilotDocument | undefined;
  const selectedStatementLineKey = selectedDocument?.statementLines.map((line) => line.line_no).join("|") ?? "";

  useEffect(() => {
    const firstLineNo = selectedDocument?.statementLines[0]?.line_no ?? 0;
    if (!firstLineNo) {
      setSelectedStatementLineNo(0);
      return;
    }
    const hasSelectedLine = selectedDocument?.statementLines.some((line) => line.line_no === selectedStatementLineNo);
    if (!hasSelectedLine) setSelectedStatementLineNo(firstLineNo);
  }, [selectedDocument?.id, selectedStatementLineKey, selectedStatementLineNo]);

  return {
    activeReviewDocuments,
    reviewFilter,
    segmentedClientDocuments,
    selectedDocument,
    selectedDocumentId,
    selectedDocumentSegment,
    selectedStatementLineNo,
    setReviewFilter,
    setSelectedDocumentId,
    setSelectedDocumentSegment,
    setSelectedStatementLineNo,
    visibleProcessingDocuments,
    visibleReviewDocuments,
  };
}
