"use client";

import { useEffect, useMemo, useState } from "react";
import { documentsForProcessing } from "../../portal-dashboard";
import { isCancelStatus } from "../../portal-formatters";
import type { DocumentSegment, PilotDocument, ReviewFilter } from "../../portal-types";

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
    if (reviewFilter === "all") return clientDocuments;
    if (reviewFilter === "cancel_requested") {
      return clientDocuments.filter((document) => isCancelStatus(document.status));
    }
    return clientDocuments.filter((document) => document.status === reviewFilter);
  }, [clientDocuments, reviewFilter]);

  const visibleProcessingDocuments = useMemo(() => {
    if (reviewFilter === "all") return segmentedClientDocuments;
    if (reviewFilter === "cancel_requested") {
      return segmentedClientDocuments.filter((document) => isCancelStatus(document.status));
    }
    return segmentedClientDocuments.filter((document) => document.status === reviewFilter);
  }, [reviewFilter, segmentedClientDocuments]);

  const activeReviewDocuments = mode === "documents" ? visibleProcessingDocuments : visibleReviewDocuments;
  const selectedDocumentSource = mode === "documents" ? segmentedClientDocuments : activeReviewDocuments;
  const selectedDocument = selectedDocumentSource.find((document) => document.id === selectedDocumentId);
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
