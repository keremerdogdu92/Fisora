import type { ReactNode } from "react";
import type { DocumentSegment } from "./portal-types";

export function DocumentProcessingWorkspace({
  children,
  selectedDocumentSegment,
  setSelectedDocumentSegment,
}: {
  children: ReactNode;
  selectedDocumentSegment: DocumentSegment;
  setSelectedDocumentSegment: (segment: DocumentSegment) => void;
}) {
  const tabs: { id: DocumentSegment; label: string }[] = [
    { id: "invoices", label: "Faturalar" },
    { id: "bank_statements", label: "Banka ekstreleri" },
    { id: "other_documents", label: "Diger belgeler" },
  ];
  return (
    <section className="document-processing-page">
      <div className="segment-tabs" role="tablist" aria-label="Belge segmentleri">
        {tabs.map((tab) => (
          <button
            aria-selected={selectedDocumentSegment === tab.id}
            className={selectedDocumentSegment === tab.id ? "active" : ""}
            key={tab.id}
            onClick={() => setSelectedDocumentSegment(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>
      {children}
    </section>
  );
}
