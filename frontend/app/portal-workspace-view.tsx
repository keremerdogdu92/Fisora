"use client";

import { useMemo, useState } from "react";
import { DocumentPipelineTimeline, DocumentPreview, JournalPanel } from "./portal-review-panels";
import type {
  CancellationRequest,
  CorrectionDraft,
  DashboardClientRow,
  DocumentSegment,
  LocalSession,
  NewClientDraft,
  PilotClient,
  PilotDocument,
  PilotStatus,
  ReviewFilter,
} from "./portal-types";
import { labelForIntakeCategory } from "./upload-intake";

const statusLabels: Record<PilotStatus, string> = {
  uploaded: "Yüklendi",
  queued: "Kuyrukta",
  processing: "İşleniyor",
  review_required: "Kontrol gerekli",
  export_ready: "Aktarıma hazır",
  cancel_requested: "İptal talebi",
  cancel_approved: "İptal kabul",
  cancel_rejected: "İptal red",
  export_added: "Çıktı listesinde",
  exported: "Çıktı alındı",
  post_export_correction_requested: "Aktarım sonrası düzeltme",
};

function formatStatus(status: PilotStatus) {
  return statusLabels[status] ?? status;
}

function segmentForDocument(document: PilotDocument): DocumentSegment {
  if (document.intakeCategory === "bank_statement") return "bank_statements";
  if (document.intakeCategory === "special_document") return "other_documents";
  if (document.intakeCategory === "purchase_invoice") return "purchase_invoices";
  return "sales_invoices";
}

function documentMatchesSegment(document: PilotDocument, segment: DocumentSegment) {
  if (segment === "invoices") return document.intakeCategory === "sales_invoice" || document.intakeCategory === "purchase_invoice";
  return segmentForDocument(document) === segment;
}

export function AccountantWorkspace({
  cancellationRequests,
  statementAiStatus,
  clientSearch,
  clientRows,
  clients,
  correctionDraft,
  dashboardMetrics,
  decisionStatus,
  documents,
  allClientDocuments,
  newClientDraft,
  newClientStatus,
  newClientTaxCertificateFile,
  newClientTaxCertificateInputKey,
  onAddToBasket,
  onApproveAndNext,
  onClientSearchChange,
  onCreateNewClient,
  onRequestStatementAi,
  onResolveCancellation,
  onSaveDecision,
  onSaveStatementDecision,
  onTaxCertificateFileChange,
  reviewFilter,
  selectedClient,
  selectedDocument,
  selectedDocumentSegment,
  selectedStatementLineNo,
  session,
  setCorrectionDraft,
  setNewClientDraft,
  setReviewFilter,
  setSelectedClientId,
  setSelectedDocumentId,
  setSelectedDocumentSegment,
  setSelectedStatementLineNo,
}: {
  cancellationRequests: CancellationRequest[];
  statementAiStatus: string;
  clientSearch: string;
  clientRows: DashboardClientRow[];
  clients: PilotClient[];
  correctionDraft: CorrectionDraft;
  dashboardMetrics: {
    totalClients: number;
    uploadedClients: number;
    notUploadedClients: number;
    pendingReviewDocuments: number;
    exportReadyDocuments: number;
    openCancellationRequests: number;
  };
  decisionStatus: string;
  documents: PilotDocument[];
  allClientDocuments: PilotDocument[];
  newClientDraft: NewClientDraft;
  newClientStatus: string;
  newClientTaxCertificateFile: File | null;
  newClientTaxCertificateInputKey: number;
  onAddToBasket: () => void;
  onApproveAndNext: () => void | Promise<void>;
  onClientSearchChange: (value: string) => void;
  onCreateNewClient: () => void | Promise<void>;
  onRequestStatementAi: () => void | Promise<void>;
  onResolveCancellation: (requestId: string, status: "approved" | "rejected") => void;
  onSaveDecision: (action: string) => void | Promise<void>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void | Promise<void>;
  reviewFilter: ReviewFilter;
  selectedClient?: PilotClient;
  selectedDocument?: PilotDocument;
  selectedDocumentSegment: DocumentSegment;
  selectedStatementLineNo: number;
  session: LocalSession | null;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setNewClientDraft: (value: NewClientDraft) => void;
  setReviewFilter: (value: ReviewFilter) => void;
  setSelectedClientId: (value: string) => void;
  setSelectedDocumentId: (value: string) => void;
  setSelectedDocumentSegment: (value: DocumentSegment) => void;
  setSelectedStatementLineNo: (value: number) => void;
}) {
  void clientSearch;
  void clientRows;
  void dashboardMetrics;
  void newClientDraft;
  void newClientStatus;
  void newClientTaxCertificateFile;
  void newClientTaxCertificateInputKey;
  void onAddToBasket;
  void onClientSearchChange;
  void onCreateNewClient;
  void onTaxCertificateFileChange;
  void setNewClientDraft;

  const [documentQuery, setDocumentQuery] = useState("");
  const selectedRequest = selectedDocument
    ? cancellationRequests.find((request) => request.documentId === selectedDocument.id)
    : undefined;
  const segmentOptions: { id: DocumentSegment; label: string }[] = [
    { id: "invoices", label: "Faturalar" },
    { id: "sales_invoices", label: "Satış" },
    { id: "purchase_invoices", label: "Alış" },
    { id: "bank_statements", label: "Ekstreler" },
    { id: "other_documents", label: "Diğer" },
  ];
  const queueDocuments = useMemo(() => {
    const query = documentQuery.trim().toLocaleLowerCase("tr-TR");
    return allClientDocuments
      .filter((document) => documentMatchesSegment(document, selectedDocumentSegment))
      .filter((document) => {
        if (reviewFilter === "all") return true;
        if (reviewFilter === "cancel_requested") return document.status === "cancel_requested" || document.status === "post_export_correction_requested";
        return document.status === reviewFilter;
      })
      .filter((document) => {
        if (!query) return true;
        return `${document.fileName} ${document.provider} ${document.amount} ${formatStatus(document.status)}`.toLocaleLowerCase("tr-TR").includes(query);
      });
  }, [allClientDocuments, documentQuery, reviewFilter, selectedDocumentSegment]);
  const navigationDocuments = selectedDocument && !documents.some((document) => document.id === selectedDocument.id)
    ? queueDocuments
    : documents;
  const selectedDocumentPosition = selectedDocument
    ? navigationDocuments.findIndex((document) => document.id === selectedDocument.id) + 1
    : 0;
  const safeDocumentPosition = Math.max(selectedDocumentPosition, 1);

  function selectDocument(document: PilotDocument) {
    setSelectedDocumentSegment(segmentForDocument(document));
    setSelectedDocumentId(document.id);
  }

  return (
    <section className="accountant-workspace">
      <section className="document-review-toolbar" aria-label="Belge kontrol araçları">
        <label className="compact-field">
          <span>Mükellef</span>
          <select
            onChange={(event) => {
              setSelectedClientId(event.target.value);
              setSelectedDocumentId("");
            }}
            value={selectedClient?.clientId ?? ""}
          >
            {clients.map((client) => (
              <option key={client.clientId} value={client.clientId}>
                {client.clientName}
              </option>
            ))}
          </select>
        </label>
        <div className="queue-segment-tabs" role="tablist" aria-label="Belge türleri">
          {segmentOptions.map((option) => (
            <button
              aria-selected={selectedDocumentSegment === option.id}
              className={selectedDocumentSegment === option.id ? "active" : ""}
              key={option.id}
              onClick={() => {
                setSelectedDocumentSegment(option.id);
                setSelectedDocumentId("");
              }}
              role="tab"
              type="button"
            >
              <span>{option.label}</span>
              <strong>{allClientDocuments.filter((document) => documentMatchesSegment(document, option.id)).length}</strong>
            </button>
          ))}
        </div>
        <label className="compact-field">
          <span>Kontrol filtresi</span>
          <select onChange={(event) => setReviewFilter(event.target.value as ReviewFilter)} value={reviewFilter}>
            <option value="review_required">Kontrol gerekli</option>
            <option value="export_ready">Aktarıma hazır</option>
            <option value="cancel_requested">İptal talepleri</option>
            <option value="all">Tüm belgeler</option>
          </select>
        </label>
        <label className="compact-field">
          <span>Ara</span>
          <input
            className="search-input"
            onChange={(event) => setDocumentQuery(event.target.value)}
            placeholder="Belge adı, tür, tutar..."
            value={documentQuery}
          />
        </label>
        <div className="queue-stepper">
          <span>{selectedDocument ? `${safeDocumentPosition} / ${Math.max(navigationDocuments.length, 1)}` : `0 / ${navigationDocuments.length}`}</span>
          <button disabled={!selectedDocument} onClick={() => setSelectedDocumentId(navigationDocuments[Math.max(safeDocumentPosition - 2, 0)]?.id ?? selectedDocument?.id ?? "")} type="button">Önceki</button>
          <button disabled={!selectedDocument} onClick={() => setSelectedDocumentId(navigationDocuments[safeDocumentPosition]?.id ?? selectedDocument?.id ?? "")} type="button">Sonraki</button>
        </div>
      </section>

      <details className="debug-accordion">
        <summary>
          <span>Teknik açıklama ve pipeline</span>
          <strong>Debug için aç</strong>
        </summary>
        <DocumentPipelineTimeline events={selectedDocument?.pipelineEvents ?? []} />
      </details>

      <section className="document-review-main">
        <DocumentPreview document={selectedDocument} session={session} />
        <JournalPanel
          correctionDraft={correctionDraft}
          decisionStatus={decisionStatus}
          document={selectedDocument}
          onApproveAndNext={onApproveAndNext}
          onRequestStatementAi={onRequestStatementAi}
          onSaveDecision={onSaveDecision}
          onSaveStatementDecision={onSaveStatementDecision}
          selectedStatementLineNo={selectedStatementLineNo}
          setCorrectionDraft={setCorrectionDraft}
          setSelectedStatementLineNo={setSelectedStatementLineNo}
          statementAiStatus={statementAiStatus}
        />
      </section>

      <section className="bottom-document-queue" aria-label="Belge listesi">
        <div className="bottom-queue-heading">
          <div>
            <h2>Belge listesi</h2>
            <span>{queueDocuments.length} belge gösteriliyor. Aktif belge üstte açık kalır.</span>
          </div>
          {selectedRequest ? (
            <div className="request-strip">
              <span>İptal/düzeltme talebi: {selectedRequest.reason}</span>
              <button onClick={() => onResolveCancellation(selectedRequest.id, "approved")} type="button">Kabul</button>
              <button onClick={() => onResolveCancellation(selectedRequest.id, "rejected")} type="button">Red</button>
            </div>
          ) : null}
        </div>
        <div className="bottom-queue-table">
          <div className="bottom-queue-row header">
            <div>Belge</div>
            <div>Tür</div>
            <div>Tutar</div>
            <div>Durum</div>
            <div>Aksiyon</div>
          </div>
          {queueDocuments.map((document) => {
            const isActive = selectedDocument?.id === document.id;
            return (
              <div className={isActive ? "bottom-queue-row active" : "bottom-queue-row"} key={document.id}>
                <button className="bottom-queue-document" onClick={() => selectDocument(document)} type="button">
                  <strong>{document.fileName}</strong>
                  <span>{document.uploadedAt}</span>
                </button>
                <div>{labelForIntakeCategory(document.intakeCategory)}</div>
                <div>{document.amount || "-"}</div>
                <div><em>{formatStatus(document.status)}</em></div>
                <div className="bottom-queue-actions">
                  {isActive ? (
                    <>
                      <button onClick={() => void onApproveAndNext()} type="button">Onayla</button>
                      <button onClick={() => void onSaveDecision("approve_with_changes")} type="button">Düzelt</button>
                    </>
                  ) : (
                    <button onClick={() => selectDocument(document)} type="button">Aç</button>
                  )}
                </div>
              </div>
            );
          })}
          {!queueDocuments.length ? <p className="empty">Bu filtrede belge yok.</p> : null}
        </div>
      </section>
    </section>
  );
}
