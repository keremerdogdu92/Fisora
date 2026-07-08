"use client";

import { useMemo, useState } from "react";
import {
  documentMatchesSegment,
  nextDocumentSelection,
  reviewCockpitQueues,
} from "./features/documents/document-workflow-model";
import { reviewReasonLabel } from "./portal-normalization";
import { AiTracePanel, DocumentPipelineTimeline, DocumentPreview, JournalPanel } from "./portal-review-panels";
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

type WorkQueueFilter = "all" | "oneClickApproval" | "minorEdit" | "manualRisk";

function formatStatus(status: PilotStatus) {
  return statusLabels[status] ?? status;
}

function documentAgentSteps(document?: PilotDocument) {
  if (!document) {
    return [
      { key: "document", name: "Belge ajanı", status: "Belge seçin", detail: "Önizleme ve ayrıştırma bekliyor" },
      { key: "account", name: "Hesap ajanı", status: "Beklemede", detail: "Fiş taslağı yok" },
      { key: "counterparty", name: "Cari ajanı", status: "Beklemede", detail: "Cari eşleşmesi yok" },
      { key: "research", name: "Araştırma ajanı", status: "Gerekmedi", detail: "Araştırma sinyali yok" },
    ];
  }
  const accountValue = document.selectedRevenueAccount || document.selectedExpenseAccount || document.draftLines[0]?.account_code || "";
  const counterpartyValue = document.selectedCustomerAccount || document.selectedCounterpartyAccount || document.suggestedCounterpartyAccount || "";
  return [
    {
      key: "document",
      name: "Belge ajanı",
      status: formatStatus(document.status),
      detail: document.provider || document.originalDocumentMimeType || "Belge okunuyor",
    },
    {
      key: "account",
      name: "Hesap ajanı",
      status: accountValue ? "Fiş taslağı hazır" : "Hesap bekliyor",
      detail: accountValue || document.draftStatus || "Taslak yok",
    },
    {
      key: "counterparty",
      name: "Cari ajanı",
      status: counterpartyValue ? "Cari önerildi" : "Cari bekliyor",
      detail: counterpartyValue || "Eşleşme yok",
    },
    {
      key: "research",
      name: "Araştırma ajanı",
      status: document.aiResearchRequested ? "Araştırma sinyali var" : "Gerekmedi",
      detail: document.aiResearchQuery || "Yalnızca belirsizlikte çalışır",
    },
  ];
}

function DocumentAgentStrip({ document }: { document?: PilotDocument }) {
  const agents = documentAgentSteps(document);
  return (
    <section className="document-agent-strip" aria-label="Belge ajan şeridi">
      {agents.map((agent) => (
        <div className="document-agent-card" key={agent.key}>
          <span>{agent.name}</span>
          <strong>{agent.status}</strong>
          <small>{agent.detail}</small>
        </div>
      ))}
    </section>
  );
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
  hasUnsavedReviewChanges,
  newClientDraft,
  newClientStatus,
  newClientTaxCertificateFile,
  newClientTaxCertificateInputKey,
  onAddToBasket,
  onApproveAndNext,
  onClientSearchChange,
  onCreateNewClient,
  onReprocessDocument,
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
  hasUnsavedReviewChanges: boolean;
  newClientDraft: NewClientDraft;
  newClientStatus: string;
  newClientTaxCertificateFile: File | null;
  newClientTaxCertificateInputKey: number;
  onAddToBasket: () => void;
  onApproveAndNext: () => void | Promise<void>;
  onClientSearchChange: (value: string) => void;
  onCreateNewClient: () => void | Promise<void>;
  onReprocessDocument: () => void | Promise<void>;
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
  void reviewFilter;
  void setReviewFilter;
  void setNewClientDraft;

  const [documentQuery, setDocumentQuery] = useState("");
  const [workQueueFilter, setWorkQueueFilter] = useState<WorkQueueFilter>("all");
  const selectedRequest = selectedDocument
    ? cancellationRequests.find((request) => request.documentId === selectedDocument.id)
    : undefined;
  const segmentOptions: { id: DocumentSegment; label: string }[] = [
    { id: "purchase_invoices", label: "Alış" },
    { id: "sales_invoices", label: "Satış" },
  ];
  const filteredSegmentDocuments = useMemo(() => {
    const query = documentQuery.trim().toLocaleLowerCase("tr-TR");
    return documents
      .filter((document) => documentMatchesSegment(document, selectedDocumentSegment))
      .filter((document) => {
        if (!query) return true;
        return `${document.fileName} ${document.provider} ${document.amount} ${formatStatus(document.status)}`.toLocaleLowerCase("tr-TR").includes(query);
      });
  }, [documentQuery, documents, selectedDocumentSegment]);
  const cockpitQueues = useMemo(() => reviewCockpitQueues(filteredSegmentDocuments), [filteredSegmentDocuments]);
  const queueDocuments = useMemo(() => {
    if (workQueueFilter === "oneClickApproval") return cockpitQueues.oneClickApproval;
    if (workQueueFilter === "minorEdit") return cockpitQueues.minorEdit;
    if (workQueueFilter === "manualRisk") return cockpitQueues.manualRisk;
    return filteredSegmentDocuments;
  }, [cockpitQueues, filteredSegmentDocuments, workQueueFilter]);
  const navigationDocuments = queueDocuments;
  const selectedDocumentPosition = selectedDocument
    ? navigationDocuments.findIndex((document) => document.id === selectedDocument.id) + 1
    : 0;
  const safeDocumentPosition = Math.max(selectedDocumentPosition, 1);
  const workQueueOptions: { id: WorkQueueFilter; label: string; count: number }[] = [
    { id: "oneClickApproval", label: "Onaylanabilir", count: cockpitQueues.oneClickApproval.length },
    { id: "minorEdit", label: "Küçük düzeltme", count: cockpitQueues.minorEdit.length },
    { id: "manualRisk", label: "Manuel / riskli", count: cockpitQueues.manualRisk.length },
    { id: "all", label: "Tümü", count: filteredSegmentDocuments.length },
  ];

  function applyWorkQueueFilter(nextFilter: WorkQueueFilter) {
    setWorkQueueFilter(nextFilter);
    const nextDocuments =
      nextFilter === "oneClickApproval" ? cockpitQueues.oneClickApproval
        : nextFilter === "minorEdit" ? cockpitQueues.minorEdit
          : nextFilter === "manualRisk" ? cockpitQueues.manualRisk
            : filteredSegmentDocuments;
    if (nextDocuments.length && !nextDocuments.some((document) => document.id === selectedDocument?.id)) {
      setSelectedDocumentId(nextDocuments[0].id);
    }
  }

  function selectDocument(document: PilotDocument) {
    const nextSelection = nextDocumentSelection(document);
    setSelectedDocumentSegment(nextSelection.selectedDocumentSegment as DocumentSegment);
    setSelectedDocumentId(nextSelection.selectedDocumentId);
  }

  return (
    <section className="accountant-workspace">
      <section className="document-review-toolbar" aria-label="Belge kontrol araçları">
        <div className="document-review-toolbar-fields">
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
          <label className="compact-field">
            <span>Ara</span>
            <input
              className="search-input"
              onChange={(event) => setDocumentQuery(event.target.value)}
              placeholder="Belge adı, tür, tutar..."
              value={documentQuery}
            />
          </label>
        </div>
        <div className="document-review-toolbar-tabs">
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
        </div>
        <div className="review-cockpit-queues" aria-label="İş kuyruğu">
          <span>İş kuyruğu</span>
          {workQueueOptions.map((option) => (
            <button
              className={workQueueFilter === option.id ? "active" : ""}
              key={option.id}
              onClick={() => applyWorkQueueFilter(option.id)}
              type="button"
            >
              <span>{option.label}</span>
              <strong>{option.count}</strong>
            </button>
          ))}
        </div>
      </section>

      <section className="document-agent-row" aria-label="Belge durumu ve gezinme">
        <DocumentAgentStrip document={selectedDocument} />
        <div className="queue-stepper">
          <span>{selectedDocument && selectedDocumentPosition > 0 ? `${safeDocumentPosition} / ${Math.max(navigationDocuments.length, 1)}` : `0 / ${navigationDocuments.length}`}</span>
          <button disabled={!selectedDocument || !navigationDocuments.length} onClick={() => setSelectedDocumentId(navigationDocuments[Math.max(safeDocumentPosition - 2, 0)]?.id ?? selectedDocument?.id ?? "")} type="button">Önceki</button>
          <button disabled={!selectedDocument || !navigationDocuments.length} onClick={() => setSelectedDocumentId(navigationDocuments[safeDocumentPosition]?.id ?? selectedDocument?.id ?? "")} type="button">Sonraki</button>
        </div>
      </section>

      <section className="document-review-main">
        <DocumentPreview document={selectedDocument} session={session} />
        <JournalPanel
          correctionDraft={correctionDraft}
          decisionStatus={decisionStatus}
          document={selectedDocument}
          hasUnsavedReviewChanges={hasUnsavedReviewChanges}
          onApproveAndNext={onApproveAndNext}
          onResetDraft={() => setCorrectionDraft({ accountCode: "", applyToSimilar: false, counterpartyCode: "", manualDraftLines: [], reason: "", ruleInstruction: "" })}
          onReprocessDocument={onReprocessDocument}
          onRequestStatementAi={onRequestStatementAi}
          onSaveDecision={onSaveDecision}
          onSaveStatementDecision={onSaveStatementDecision}
          selectedStatementLineNo={selectedStatementLineNo}
          setCorrectionDraft={setCorrectionDraft}
          setSelectedStatementLineNo={setSelectedStatementLineNo}
          statementAiStatus={statementAiStatus}
        />
      </section>

      <details className="debug-accordion">
        <summary>
          <span>Teknik geçmiş</span>
          <strong>Debug için aç</strong>
        </summary>
        <DocumentPipelineTimeline events={selectedDocument?.pipelineEvents ?? []} />
        <AiTracePanel document={selectedDocument} />
      </details>

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
                <div>
                  <em>{formatStatus(document.status)}</em>
                  {document.reviewReasons.length ? (
                    <div className="review-reason-chips" aria-label="Kontrol gerekçeleri">
                      {document.reviewReasons.slice(0, 3).map((reason) => (
                        <span className={reason === "cancelled_invoice_visible" ? "danger" : undefined} key={reason}>{reviewReasonLabel(reason)}</span>
                      ))}
                      {document.reviewReasons.length > 3 ? <span>+{document.reviewReasons.length - 3}</span> : null}
                    </div>
                  ) : document.status === "review_required" ? (
                    <div className="review-reason-chips" aria-label="Kontrol gerekçeleri">
                      <span>Ek kontrol gerekli</span>
                    </div>
                  ) : null}
                </div>
                <div className="bottom-queue-actions">
                  {isActive ? (
                    document.directionConflict?.status === "needs_review" ? (
                      <button disabled type="button">Önce yönü yanıtla</button>
                    ) : (
                      <button onClick={() => void onApproveAndNext()} type="button">Onayla</button>
                    )
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
