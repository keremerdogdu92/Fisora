"use client";

import { NewClientCard } from "./portal-clients-view";
import { DocumentPreview, JournalPanel } from "./portal-review-panels";
import { Info, Metric } from "./portal-shared";
import type {
  CancellationRequest,
  CorrectionDraft,
  DashboardClientRow,
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
  selectedStatementLineNo,
  setCorrectionDraft,
  setNewClientDraft,
  setReviewFilter,
  setSelectedClientId,
  setSelectedDocumentId,
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
  selectedStatementLineNo: number;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setNewClientDraft: (value: NewClientDraft) => void;
  setReviewFilter: (value: ReviewFilter) => void;
  setSelectedClientId: (value: string) => void;
  setSelectedDocumentId: (value: string) => void;
  setSelectedStatementLineNo: (value: number) => void;
}) {
  const selectedRequest = selectedDocument
    ? cancellationRequests.find((request) => request.documentId === selectedDocument.id)
    : undefined;
  const navigationDocuments = selectedDocument && !documents.some((document) => document.id === selectedDocument.id)
    ? allClientDocuments
    : documents;
  const selectedDocumentPosition = selectedDocument
    ? navigationDocuments.findIndex((document) => document.id === selectedDocument.id) + 1
    : 0;

  return (
    <section className="accountant-workspace">
      <section className="office-dashboard" aria-label="Ofis durumu">
        <Metric label="Mükellef" value={dashboardMetrics.totalClients} />
        <Metric label="Belge yükleyen" value={dashboardMetrics.uploadedClients} />
        <Metric label="Yüklemeyen" value={dashboardMetrics.notUploadedClients} />
        <Metric label="Kontrol" value={dashboardMetrics.pendingReviewDocuments} />
        <Metric label="Çıktı hazır" value={dashboardMetrics.exportReadyDocuments} />
        <Metric label="Talep" value={dashboardMetrics.openCancellationRequests} />
      </section>
      <aside className="client-context-rail" aria-label="Seçili mükellef">
        <div className="client-emblem">
          <span>Mükellef</span>
          <strong>{selectedClient?.clientName ?? "-"}</strong>
          <small>{selectedClient?.taxId ?? "-"}</small>
        </div>
        <input
          className="search-input"
          onChange={(event) => onClientSearchChange(event.target.value)}
          placeholder="Mükellef ara"
          value={clientSearch}
        />
        <div className="client-list dashboard-client-list">
          {clientRows.map((row) => (
            <button
              className={selectedClient?.clientId === row.clientId ? "client-row active" : "client-row"}
              key={row.clientId}
              onClick={() => {
                setSelectedClientId(row.clientId);
                setSelectedDocumentId("");
              }}
              type="button"
            >
              <strong>{row.clientName}</strong>
              <span>{row.status}</span>
              <em>{row.documentCount} belge / {row.pendingReviewCount} kontrol / {row.exportReadyCount} hazır</em>
            </button>
          ))}
        </div>
        <label className="compact-field">
          <span>Mükellef seç</span>
          <select
            onChange={(event) => setSelectedClientId(event.target.value)}
            value={selectedClient?.clientId ?? ""}
          >
            {clients.map((client) => (
              <option key={client.clientId} value={client.clientId}>
                {client.clientName}
              </option>
            ))}
          </select>
        </label>
        <div className="rail-stats">
          <Info label="Belge" value={String(documents.length)} />
          <Info label="Kontrol" value={String(documents.filter((document) => document.status === "review_required").length)} />
          <Info label="İptal" value={String(cancellationRequests.length)} />
        </div>
        {selectedDocument ? (
          <div className="selected-document-summary">
            <span>Açık belge</span>
            <strong>{selectedDocument.fileName}</strong>
            <small>{labelForIntakeCategory(selectedDocument.intakeCategory)} / {selectedDocument.provider} / {selectedDocument.amount}</small>
            <span className={`status ${selectedDocument.status}`}>{formatStatus(selectedDocument.status)}</span>
          </div>
        ) : null}
        <button className="primary full" onClick={onAddToBasket} type="button">Çıktı listesine ekle</button>
        {selectedRequest ? (
          <div className="request-compact">
            <span>İptal/düzeltme talebi</span>
            <p>{selectedRequest.reason}</p>
            <div className="inline-actions">
              <button onClick={() => onResolveCancellation(selectedRequest.id, "approved")} type="button">Kabul</button>
              <button onClick={() => onResolveCancellation(selectedRequest.id, "rejected")} type="button">Red</button>
            </div>
          </div>
        ) : null}
        <NewClientCard
          draft={newClientDraft}
          onCreate={onCreateNewClient}
          onTaxCertificateFileChange={onTaxCertificateFileChange}
          setDraft={setNewClientDraft}
          status={newClientStatus}
          taxCertificateFile={newClientTaxCertificateFile}
          taxCertificateInputKey={newClientTaxCertificateInputKey}
        />
      </aside>

      <section className="review-focus">
        <div className="workbench-toolbar">
          <div>
            <span>Belge kontrolü</span>
            <strong>{selectedDocument ? `${selectedDocumentPosition}/${navigationDocuments.length} ${selectedDocument.fileName}` : "Önce belge seçin."}</strong>
          </div>
          <div className="toolbar-controls">
            <select onChange={(event) => setReviewFilter(event.target.value as ReviewFilter)} value={reviewFilter}>
              <option value="review_required">Kontrol gerekli</option>
              <option value="export_ready">Aktarıma hazır</option>
              <option value="cancel_requested">İptal talepleri</option>
              <option value="all">Tüm belgeler</option>
            </select>
            <select
              aria-label="Belge seç"
              onChange={(event) => setSelectedDocumentId(event.target.value)}
              value={selectedDocument?.id ?? ""}
            >
              <option value="">{documents.length ? "Belge seçin" : "Belge yok"}</option>
              {documents.map((document) => (
                <option key={document.id} value={document.id}>
                  {document.fileName}
                </option>
              ))}
            </select>
            <button disabled={!selectedDocument} onClick={() => setSelectedDocumentId(navigationDocuments[Math.max(selectedDocumentPosition - 2, 0)]?.id ?? selectedDocument?.id ?? "")} type="button">Önceki</button>
            <button disabled={!selectedDocument} onClick={() => setSelectedDocumentId(navigationDocuments[selectedDocumentPosition]?.id ?? selectedDocument?.id ?? "")} type="button">Sonraki</button>
            <button className="primary" disabled={!selectedDocument} onClick={onApproveAndNext} type="button">Onayla ve geç</button>
          </div>
        </div>

        <div className="document-queue" aria-label="Mükellef evrakları">
          {allClientDocuments.map((document) => (
            <button
              className={selectedDocument?.id === document.id ? "document-row active" : "document-row"}
              key={document.id}
              onClick={() => setSelectedDocumentId(document.id)}
              type="button"
            >
              <strong>{document.fileName}</strong>
              <span>{labelForIntakeCategory(document.intakeCategory)} / {document.amount}</span>
              <em>{formatStatus(document.status)}</em>
            </button>
          ))}
        </div>

        {cancellationRequests.length && !selectedRequest ? (
          <div className="request-strip">
            <span>Açık talepler</span>
            {cancellationRequests.map((request) => (
              <button key={request.id} onClick={() => setSelectedDocumentId(request.documentId)} type="button">
                {request.fileName}
              </button>
            ))}
          </div>
        ) : null}

        <section className="review-split">
          <DocumentPreview document={selectedDocument} />
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
      </section>
    </section>
  );
}
