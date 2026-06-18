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
  const invoiceTabs: { id: DocumentSegment; label: string }[] = [
    { id: "sales_invoices", label: "Satış Faturaları" },
    { id: "purchase_invoices", label: "Alış Faturaları" },
  ];
  const mainTabs: { id: "invoices" | "bank_statements" | "other_documents"; label: string; segment: DocumentSegment }[] = [
    { id: "invoices", label: "Faturalar", segment: "sales_invoices" },
    { id: "bank_statements", label: "Banka ekstreleri", segment: "bank_statements" },
    { id: "other_documents", label: "Diğer belgeler", segment: "other_documents" },
  ];
  const selectedMainTab = selectedDocumentSegment === "bank_statements" || selectedDocumentSegment === "other_documents"
    ? selectedDocumentSegment
    : "invoices";
  const selectedInvoiceSegment = selectedDocumentSegment === "purchase_invoices" ? "purchase_invoices" : "sales_invoices";

  return (
    <section className="document-processing-page">
      <div className="segment-tabs segment-tabs-main" role="tablist" aria-label="Belge segmentleri">
        {mainTabs.map((tab) => (
          <button
            aria-selected={selectedMainTab === tab.id}
            className={selectedMainTab === tab.id ? "active" : ""}
            key={tab.id}
            onClick={() => setSelectedDocumentSegment(tab.segment)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>
      {selectedMainTab === "invoices" ? (
        <div className="segment-tabs segment-tabs-sub" role="tablist" aria-label="Fatura türleri">
          {invoiceTabs.map((tab) => (
            <button
              aria-selected={selectedInvoiceSegment === tab.id}
              className={selectedInvoiceSegment === tab.id ? "active" : ""}
              key={tab.id}
              onClick={() => setSelectedDocumentSegment(tab.id)}
              role="tab"
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </div>
      ) : null}
      {children}
    </section>
  );
}
