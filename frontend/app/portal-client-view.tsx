"use client";

import { buildClientCancellationViewModel } from "./portal-dashboard";
import { Info, Metric } from "./portal-shared";
import { INTAKE_TABS, buildUploadIntakeMetadata, labelForIntakeCategory } from "./upload-intake";
import type { CancellationRequest, IntakeCategory, PilotClient, PilotDocument, PilotStatus } from "./portal-types";

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

const documentTypeLabels: Record<string, string> = {
  invoice: "Fatura",
  xml: "E-Fatura XML/PDF",
  bank: "Banka ekstresi",
  bank_statement: "Banka ekstresi",
  pos: "POS ekstresi",
  pos_statement: "POS ekstresi",
  special_document: "Özel belge",
  ALIS: "Alış faturası",
  SATIS: "Satış faturası",
};

function documentPreviewTitle(document: PilotDocument) {
  if (document.intakeCategory === "bank_statement") return "EKSTRE";
  if (document.intakeCategory === "special_document") return "ÖZEL BELGE";
  return "FATURA";
}

function periodLabel(period: string) {
  const [year, month] = period.split("-");
  if (!year || !month) return period;
  return `${month}.${year}`;
}

function formatStatus(status: PilotStatus) {
  return statusLabels[status] ?? status;
}

function isInProgress(status: PilotStatus) {
  return status === "uploaded" || status === "queued" || status === "processing";
}

function isCancelStatus(status: PilotStatus) {
  return status === "cancel_requested" || status === "post_export_correction_requested";
}

export function ClientPortal({
  cancelReason,
  cancellationDocumentId,
  documents,
  onCancelReasonChange,
  onFilesSelected,
  onOpenCancellationRequest,
  onRequestCancellation,
  onSelectDocument,
  periods,
  selectedClient,
  selectedDocument,
  selectedIntakeCategory,
  selectedPeriod,
  setSelectedIntakeCategory,
  setSelectedPeriod,
  uploadStatus,
}: {
  cancelReason: string;
  cancellationDocumentId: string;
  documents: PilotDocument[];
  onCancelReasonChange: (value: string) => void;
  onFilesSelected: (files: FileList | null) => void | Promise<void>;
  onOpenCancellationRequest: (document: PilotDocument) => void;
  onRequestCancellation: (document: PilotDocument) => void;
  onSelectDocument: (document: PilotDocument) => void;
  periods: string[];
  selectedClient?: PilotClient;
  selectedDocument?: PilotDocument;
  selectedIntakeCategory: IntakeCategory;
  selectedPeriod: string;
  setSelectedIntakeCategory: (value: IntakeCategory) => void;
  setSelectedPeriod: (value: string) => void;
  uploadStatus: string;
}) {
  const activeDocuments = documents.filter((document) => document.intakeCategory === selectedIntakeCategory);
  const selectedIntake = buildUploadIntakeMetadata(selectedIntakeCategory);
  const uploadedCount = activeDocuments.length;
  const processingCount = activeDocuments.filter((document) => isInProgress(document.status)).length;
  const handledCount = activeDocuments.filter((document) => document.status === "review_required" || document.status === "export_ready" || document.status === "export_added" || document.status === "exported").length;
  const cancelCount = activeDocuments.filter((document) => isCancelStatus(document.status)).length;
  const cancellationView = buildClientCancellationViewModel({
    documents: activeDocuments,
    selectedDocumentId: selectedDocument?.id ?? "",
    requestDocumentId: cancellationDocumentId,
    cancellationReason: cancelReason,
  });
  return (
    <section className="client-portal">
      <div className="panel upload-panel">
        <div className="panel-heading">
          <div>
            <h2>MÃ¼kellef portalÄ±</h2>
            <span>{selectedClient?.clientName ?? "-"}</span>
          </div>
          <select aria-label="Ay seÃ§imi" onChange={(event) => setSelectedPeriod(event.target.value)} value={selectedPeriod}>
            {periods.map((period) => (
              <option key={period} value={period}>{periodLabel(period)}</option>
            ))}
          </select>
        </div>
        <div className="intake-tabs" role="tablist" aria-label="Belge yÃ¼kleme tÃ¼rÃ¼">
          {INTAKE_TABS.map((tab) => {
            const tabId = tab.id as IntakeCategory;
            const tabCount = documents.filter((document) => document.intakeCategory === tabId).length;
            return (
              <button
                aria-selected={selectedIntakeCategory === tabId}
                className={selectedIntakeCategory === tabId ? "intake-tab active" : "intake-tab"}
                key={tab.id}
                onClick={() => setSelectedIntakeCategory(tabId)}
                role="tab"
                type="button"
              >
                <span>{tab.label}</span>
                <strong>{tabCount}</strong>
              </button>
            );
          })}
        </div>
        <div className="summary-grid">
          <Metric label="YÃ¼klenen" value={uploadedCount} />
          <Metric label="Ä°ÅŸlemde" value={processingCount} />
          <Metric label="Ä°ÅŸleme alÄ±ndÄ±" value={handledCount} />
          <Metric label="Ä°ptal talebi" value={cancelCount} />
        </div>
        <label className="upload-dropzone">
          <span>{selectedIntake.label}</span>
          <strong>Dosya seÃ§</strong>
          <small>{selectedIntake.documentType === "special_document" ? "MÃ¼ÅŸavir kontrol kuyruÄŸu" : "Otomatik iÅŸleme kuyruÄŸu"}</small>
          <input
            multiple
            onChange={(event) => {
              void onFilesSelected(event.currentTarget.files);
              event.currentTarget.value = "";
            }}
            type="file"
            accept={selectedIntake.accept}
          />
        </label>
        {uploadStatus ? <p className="decision-status">{uploadStatus}</p> : null}
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Ay bazlÄ± belge listesi</h2>
            <span>{selectedPeriod ? periodLabel(selectedPeriod) : "DÃ¶nem seÃ§ilmedi"}</span>
          </div>
        </div>
        <div className="document-list">
          {activeDocuments.length ? null : <p className="empty">{selectedIntake.label} iÃ§in bu ay yÃ¼klenen belge yok.</p>}
          {activeDocuments.map((document) => (
            <div className={selectedDocument?.id === document.id ? "client-document-row active" : "client-document-row"} key={document.id}>
              <button className="document-row-main" onClick={() => onSelectDocument(document)} type="button">
                <strong>{document.fileName}</strong>
                <span>{labelForIntakeCategory(document.intakeCategory)} / {documentTypeLabels[document.documentType] ?? document.documentType} / {document.uploadedAt}</span>
              </button>
              <span className={`status ${document.status}`}>{formatStatus(document.status)}</span>
              <button onClick={() => onOpenCancellationRequest(document)} type="button">Ä°ptal/DÃ¼zeltme</button>
            </div>
          ))}
        </div>
      </div>

      <ClientDocumentDetailPanel
        cancelReason={cancelReason}
        cancellationView={cancellationView}
        onCancelReasonChange={onCancelReasonChange}
        onOpenCancellationRequest={onOpenCancellationRequest}
        onRequestCancellation={onRequestCancellation}
        selectedDocument={selectedDocument}
      />
    </section>
  );
}

function ClientDocumentDetailPanel({
  cancelReason,
  cancellationView,
  onCancelReasonChange,
  onOpenCancellationRequest,
  onRequestCancellation,
  selectedDocument,
}: {
  cancelReason: string;
  cancellationView: {
    requestDocument: PilotDocument | null;
    canSubmitCancellation: boolean;
    emptyActionText: string;
  };
  onCancelReasonChange: (value: string) => void;
  onOpenCancellationRequest: (document: PilotDocument) => void;
  onRequestCancellation: (document: PilotDocument) => void;
  selectedDocument?: PilotDocument;
}) {
  if (!selectedDocument) {
    return (
      <section className="panel client-document-detail empty-detail">
        <h2>Belge Ã¶nizleme</h2>
        <p className="empty">{cancellationView.emptyActionText}</p>
        <button disabled type="button">Ä°ptal/DÃ¼zeltme talebi</button>
      </section>
    );
  }

  const requestDocument = cancellationView.requestDocument;
  return (
    <section className="panel client-document-detail">
      <div className="panel-heading">
        <div>
          <h2>Belge Ã¶nizleme</h2>
          <span>{selectedDocument.fileName}</span>
        </div>
        <span className={`status ${selectedDocument.status}`}>{formatStatus(selectedDocument.status)}</span>
      </div>
      <article className="client-preview-paper" aria-label="SeÃ§ili belge Ã¶nizlemesi">
        <span>{documentPreviewTitle(selectedDocument)}</span>
        <strong>{selectedDocument.fileName}</strong>
        <p>{selectedDocument.previewText}</p>
        <div className="preview-meta-grid">
          <Info label="DÃ¶nem" value={periodLabel(selectedDocument.period)} />
          <Info label="Belge tÃ¼rÃ¼" value={labelForIntakeCategory(selectedDocument.intakeCategory)} />
          <Info label="Tutar" value={selectedDocument.amount} />
        </div>
      </article>
      <button className="primary" onClick={() => onOpenCancellationRequest(selectedDocument)} type="button">
        Ä°ptal/DÃ¼zeltme talebi aÃ§
      </button>
      {requestDocument ? (
        <div className="cancellation-request-panel">
          <div>
            <span>Talep aÃ§Ä±lacak belge</span>
            <strong>{requestDocument.fileName}</strong>
            <small>{labelForIntakeCategory(requestDocument.intakeCategory)} / {formatStatus(requestDocument.status)}</small>
          </div>
          <textarea
            className="cancel-reason"
            onChange={(event) => onCancelReasonChange(event.target.value)}
            placeholder="Opsiyonel aÃ§Ä±klama"
            rows={3}
            value={cancelReason}
          />
          <button
            className="primary"
            disabled={!cancellationView.canSubmitCancellation}
            onClick={() => onRequestCancellation(requestDocument)}
            type="button"
          >
            Talep gÃ¶nder
          </button>
        </div>
      ) : (
        <p className="decision-status">{cancellationView.emptyActionText}</p>
      )}
    </section>
  );
}
