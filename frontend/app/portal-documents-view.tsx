import type { ReactNode } from "react";
import type { DocumentSegment } from "./portal-types";

export function DocumentProcessingWorkspace({
  children,
}: {
  children: ReactNode;
  selectedDocumentSegment: DocumentSegment;
  setSelectedDocumentSegment: (segment: DocumentSegment) => void;
}) {
  return (
    <section className="document-processing-page">
      {children}
    </section>
  );
}
