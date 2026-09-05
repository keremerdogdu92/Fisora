// File: frontend/app/portal-workspace-view.tsx
// Summary: Renders the accountant invoice workbench with reversible queue/focus layouts, document navigation, source focus, and approval gates.
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  documentMatchesSegment,
  nextDocumentSelection,
  reviewCockpitQueues,
} from "./features/documents/document-workflow-model";
import { reviewReasonLabel } from "./portal-normalization";
import { AiTracePanel, DocumentPipelineTimeline, DocumentPreview, JournalPanel } from "./portal-review-panels";
import { PortalNextWorkspaceControls } from "./portal-next/portal-next-workspace-controls";
import type {
  CancellationRequest,
  CorrectionDraft,
  DashboardClientRow,
  DocumentSegment,
  DocumentSourceTarget,
  LocalSession,
  NewClientDraft,
  PilotClient,
  PilotDocument,
  PilotStatus,
  ReviewLearningDecisionOptions,
  ReviewFilter,
} from "./portal-types";
import { labelForIntakeCategory } from "./upload-intake";

const statusLabels: Record<PilotStatus, string> = {
  uploaded: "Yüklendi",
  queued: "Kuyrukta",
  processing: "İşleniyor",
  review_required: "Kontrol gerekli",
  no_posting_required: "Fiş gerekmiyor",
  export_ready: "Aktarıma hazır",
  cancel_requested: "İptal talebi",
  cancel_approved: "İptal kabul",
  cancel_rejected: "İptal red",
  export_added: "Çıktı listesinde",
  exported: "Çıktı alındı",
  post_export_correction_requested: "Aktarım sonrası düzeltme",
};

type WorkQueueFilter = "all" | "oneClickApproval" | "minorEdit" | "manualRisk" | "review";

function formatStatus(status: PilotStatus) {
  return statusLabels[status] ?? status;
}

function processingStageLabel(status?: string) {
  if (status === "processing") return "Çalışıyor";
  if (status === "completed") return "Tamamlandı";
  if (status === "failed") return "Hata";
  return "Bekliyor";
}

function processingStageDetail(status: string | undefined, elapsedMs: number | undefined, fallback: string) {
  if (status === "completed" && elapsedMs) return `${fallback} · ${(elapsedMs / 1000).toFixed(1)} sn`;
  return fallback;
}

function documentProcessingComplete(document?: PilotDocument) {
  if (!document) return false;
  if (["queued", "processing"].includes(document.status) || document.draftStatus === "processing") return false;
  if (document.processingStages) return document.processingStages.final.status === "completed";
  return true;
}

function documentAgentSteps(document?: PilotDocument) {
  if (!document) {
    return [
      { key: "reader", name: "Reader", status: "Belge seçin", detail: "PDF kaynak okuması bekliyor" },
      { key: "planner", name: "Planner", status: "Bekliyor", detail: "Yön ve cari bağlamı bekliyor" },
      { key: "final", name: "Final Accountant", status: "Bekliyor", detail: "Muhasebe fişi bekliyor" },
      { key: "research", name: "Research Agent", status: "Gerekmedi", detail: "Yalnızca belirsizlikte çalışır" },
    ];
  }
  const stages = document.processingStages;
  const legacyStatus = documentProcessingComplete(document) ? "completed" : "pending";
  const reader = stages?.reader ?? { status: document.status === "processing" ? "processing" : legacyStatus, elapsedMs: 0 };
  const planner = stages?.planner ?? { status: legacyStatus, elapsedMs: 0 };
  const final = stages?.final ?? { status: legacyStatus, elapsedMs: 0 };
  return [
    { key: "reader", name: "Reader", status: processingStageLabel(reader.status), detail: processingStageDetail(reader.status, reader.elapsedMs, document.sourceReviewRows?.length ? `${document.sourceReviewRows.length} kaynak satır hazır` : "PDF kaynak okuması") },
    { key: "planner", name: "Planner", status: processingStageLabel(planner.status), detail: processingStageDetail(planner.status, planner.elapsedMs, document.counterpartyTitle || document.accountingDirection || "Yön ve cari bağlamı") },
    { key: "final", name: "Final Accountant", status: processingStageLabel(final.status), detail: processingStageDetail(final.status, final.elapsedMs, documentProcessingComplete(document) ? document.draftStatus : "Muhasebe fişi hazırlanıyor") },
    { key: "research", name: "Research Agent", status: document.aiResearchRequested ? "Sinyal var" : "Gerekmedi", detail: document.aiResearchQuery || "İleride gerektiğinde devreye girer" },
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
  controlledHtmlPreview = false,
  controlledPdfPreview = false,
  nextPresentation = false,
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
  onToggleSidebar,
  onUndoLastApproval,
  reviewFilter,
  selectedClient,
  selectedDocument,
  selectedDocumentSegment,
  selectedStatementLineNo,
  session,
  undoAvailable = false,
  setCorrectionDraft,
  setNewClientDraft,
  setReviewFilter,
  setSelectedClientId,
  setSelectedDocumentId,
  setSelectedDocumentSegment,
  setSelectedStatementLineNo,
}: {
  cancellationRequests: CancellationRequest[];
  controlledHtmlPreview?: boolean;
  controlledPdfPreview?: boolean;
  nextPresentation?: boolean;
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
  onSaveDecision: (action: string, options?: ReviewLearningDecisionOptions) => void | Promise<unknown>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void | Promise<void>;
  onToggleSidebar: () => void;
  onUndoLastApproval: () => void | Promise<boolean>;
  reviewFilter: ReviewFilter;
  selectedClient?: PilotClient;
  selectedDocument?: PilotDocument;
  selectedDocumentSegment: DocumentSegment;
  selectedStatementLineNo: number;
  session: LocalSession | null;
  undoAvailable?: boolean;
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
  const [queueHidden, setQueueHidden] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [workspaceFullscreen, setWorkspaceFullscreen] = useState(false);
  const [journalHidden, setJournalHidden] = useState(false);
  const [mobilePane, setMobilePane] = useState<"queue" | "preview" | "journal">("preview");
  const [hoverSourceTarget, setHoverSourceTarget] = useState<DocumentSourceTarget | null>(null);
  const [pinnedSourceTarget, setPinnedSourceTarget] = useState<DocumentSourceTarget | null>(null);
  const hoverSourceTimerRef = useRef<number | null>(null);
  const sourceTarget = hoverSourceTarget ?? pinnedSourceTarget;
  const focusStageRef = useRef<HTMLElement | null>(null);
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
  const reviewQueueDocuments = useMemo<PilotDocument[]>(() => {
    const unique = new Map<string, PilotDocument>();
    const reviewSources: PilotDocument[] = [
      ...(cockpitQueues.minorEdit as PilotDocument[]),
      ...(cockpitQueues.manualRisk as PilotDocument[]),
    ];
    reviewSources.forEach((document) => unique.set(document.id, document));
    return [...unique.values()];
  }, [cockpitQueues]);
  const queueDocuments = useMemo(() => {
    if (workQueueFilter === "oneClickApproval") return cockpitQueues.oneClickApproval;
    if (workQueueFilter === "minorEdit") return cockpitQueues.minorEdit;
    if (workQueueFilter === "manualRisk") return cockpitQueues.manualRisk;
    if (workQueueFilter === "review") return reviewQueueDocuments;
    return filteredSegmentDocuments;
  }, [cockpitQueues, filteredSegmentDocuments, reviewQueueDocuments, workQueueFilter]);
  const navigationDocuments = queueDocuments;
  const selectedDocumentPosition = selectedDocument
    ? navigationDocuments.findIndex((document) => document.id === selectedDocument.id) + 1
    : 0;
  const safeDocumentPosition = Math.max(selectedDocumentPosition, 1);
  const workQueueOptions: { id: WorkQueueFilter; label: string; count: number }[] = nextPresentation
    ? [
        { id: "all", label: "Tümü", count: filteredSegmentDocuments.length },
        { id: "review", label: "Kontrol", count: reviewQueueDocuments.length },
        { id: "oneClickApproval", label: "Onaya hazır", count: cockpitQueues.oneClickApproval.length },
      ]
    : [
        { id: "oneClickApproval", label: "Onaylanabilir", count: cockpitQueues.oneClickApproval.length },
        { id: "minorEdit", label: "Küçük düzeltme", count: cockpitQueues.minorEdit.length },
        { id: "manualRisk", label: "Manuel / riskli", count: cockpitQueues.manualRisk.length },
        { id: "all", label: "Tümü", count: filteredSegmentDocuments.length },
      ];

  function applyWorkQueueFilter(nextFilter: WorkQueueFilter) {
    setWorkQueueFilter(nextFilter);
    const nextDocuments = nextFilter === "oneClickApproval" ? cockpitQueues.oneClickApproval
      : nextFilter === "minorEdit" ? cockpitQueues.minorEdit
        : nextFilter === "manualRisk" ? cockpitQueues.manualRisk
          : nextFilter === "review" ? reviewQueueDocuments
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

  function navigateDocument(direction: 1 | -1) {
    if (!selectedDocument || !navigationDocuments.length) return;
    const currentIndex = navigationDocuments.findIndex((document) => document.id === selectedDocument.id);
    const target = navigationDocuments[currentIndex + direction];
    if (target) setSelectedDocumentId(target.id);
  }

  useEffect(() => {
    if (hoverSourceTimerRef.current !== null) window.clearTimeout(hoverSourceTimerRef.current);
    hoverSourceTimerRef.current = null;
    setHoverSourceTarget(null);
    setPinnedSourceTarget(null);
  }, [selectedDocument?.id]);

  useEffect(() => () => {
    if (hoverSourceTimerRef.current !== null) window.clearTimeout(hoverSourceTimerRef.current);
  }, []);

  useEffect(() => {
    const onFullscreenChange = () => setWorkspaceFullscreen(document.fullscreenElement === focusStageRef.current);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  useEffect(() => {
    if (!focusMode) return undefined;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (document.fullscreenElement) return;
      event.preventDefault();
      setFocusMode(false);
      setJournalHidden(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [focusMode]);

  function clearDocumentSource() {
    if (hoverSourceTimerRef.current !== null) window.clearTimeout(hoverSourceTimerRef.current);
    hoverSourceTimerRef.current = null;
    setHoverSourceTarget(null);
    setPinnedSourceTarget(null);
  }

  function hoverDocumentSource(target: DocumentSourceTarget | null) {
    if (hoverSourceTimerRef.current !== null) window.clearTimeout(hoverSourceTimerRef.current);
    hoverSourceTimerRef.current = null;
    if (!target) {
      setHoverSourceTarget(null);
      return;
    }
    hoverSourceTimerRef.current = window.setTimeout(() => {
      setHoverSourceTarget({ ...target, pinned: false });
      hoverSourceTimerRef.current = null;
    }, 150);
  }

  function focusDocumentSource(target: DocumentSourceTarget) {
    setHoverSourceTarget(null);
    setPinnedSourceTarget({ ...target, pinned: true });
    setMobilePane("preview");
  }

  async function toggleWorkspaceFullscreen(openFocusMode = false) {
    const stage = focusStageRef.current;
    if (!stage) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    if (openFocusMode) {
      setFocusMode(true);
      setJournalHidden(false);
    }
    await stage.requestFullscreen();
  }

  async function closeFocusMode() {
    if (document.fullscreenElement) await document.exitFullscreen();
    setFocusMode(false);
    setJournalHidden(false);
  }
  return (
    <section className="accountant-workspace">
      {nextPresentation ? (
        <section className="portal-next-workbench-commandbar" aria-label="Çalışma kuyruğu ve görünüm araçları">
          <div className="review-cockpit-queues" aria-label="İş kuyruğu">
            {workQueueOptions.map((option) => (
              <button className={workQueueFilter === option.id ? "active" : ""} key={option.id} onClick={() => applyWorkQueueFilter(option.id)} type="button">
                <span>{option.label}</span>
                <strong>{option.count}</strong>
              </button>
            ))}
          </div>
          <div className="portal-next-workbench-actions">
            <button className={`queue-action${queueHidden ? " active" : ""}`} onClick={() => setQueueHidden((current) => !current)} type="button">
              <span aria-hidden="true">☰</span> {queueHidden ? "Kuyruğu göster" : "Kuyruğu gizle"}
            </button>
            <button className="focus-action" onClick={() => { setFocusMode(true); setJournalHidden(false); }} type="button">
              <span aria-hidden="true">▣</span> Belgeyi incele
            </button>
            <button className="fullscreen-action" onClick={() => void toggleWorkspaceFullscreen(true)} title="Çalışma masasını tarayıcı tam ekranında aç" type="button">
              <span aria-hidden="true">⛶</span> Tam ekran
            </button>
            <span>Evrak {selectedDocument && selectedDocumentPosition > 0 ? safeDocumentPosition : 0} / {navigationDocuments.length}</span>
          </div>
        </section>
      ) : (
        <section className="document-review-toolbar" aria-label="Belge kontrol araçları">
          <div className="document-review-toolbar-fields">
            <label className="compact-field">
              <span>Ara</span>
              <input className="search-input" onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Belge adı, tür, tutar..." value={documentQuery} />
            </label>
          </div>
          <div className="document-review-toolbar-tabs">
            <div className="queue-segment-tabs" role="tablist" aria-label="Belge türleri">
              {segmentOptions.map((option) => (
                <button aria-selected={selectedDocumentSegment === option.id} className={selectedDocumentSegment === option.id ? "active" : ""} key={option.id} onClick={() => { setSelectedDocumentSegment(option.id); setSelectedDocumentId(""); }} role="tab" type="button">
                  <span>{option.label}</span>
                  <strong>{allClientDocuments.filter((document) => documentMatchesSegment(document, option.id)).length}</strong>
                </button>
              ))}
            </div>
          </div>
          <div className="review-cockpit-queues" aria-label="İş kuyruğu">
            <span>İş kuyruğu</span>
            {workQueueOptions.map((option) => (
              <button className={workQueueFilter === option.id ? "active" : ""} key={option.id} onClick={() => applyWorkQueueFilter(option.id)} type="button">
                <span>{option.label}</span>
                <strong>{option.count}</strong>
              </button>
            ))}
          </div>
        </section>
      )}

      {!nextPresentation ? (
        <section className="document-agent-row" aria-label="Belge durumu ve gezinme">
          <DocumentAgentStrip document={selectedDocument} />
          <div className="queue-stepper">
            <span>{selectedDocument && selectedDocumentPosition > 0 ? `${safeDocumentPosition} / ${Math.max(navigationDocuments.length, 1)}` : `0 / ${navigationDocuments.length}`}</span>
            <button disabled={!selectedDocument || !navigationDocuments.length} onClick={() => navigateDocument(-1)} type="button">Önceki</button>
            <button disabled={!selectedDocument || !navigationDocuments.length} onClick={() => navigateDocument(1)} type="button">Sonraki</button>
          </div>
        </section>
      ) : null}

      {nextPresentation ? (
        <nav className="portal-next-mobile-review-switch" aria-label="Mobil çalışma görünümü">
          <button className={mobilePane === "queue" ? "active" : ""} onClick={() => setMobilePane("queue")} type="button">Kuyruk</button>
          <button className={mobilePane === "preview" ? "active" : ""} onClick={() => setMobilePane("preview")} type="button">Belge</button>
          <button className={mobilePane === "journal" ? "active" : ""} onClick={() => setMobilePane("journal")} type="button">Fiş</button>
        </nav>
      ) : null}

      <section
        className={`portal-next-workbench-stage${nextPresentation ? " next" : ""}${queueHidden ? " queue-hidden" : ""}${focusMode ? " focus-mode" : ""}${journalHidden ? " journal-hidden" : ""} mobile-pane-${mobilePane}`}
        ref={focusStageRef}
      >
        {nextPresentation ? (
          <header className="portal-next-focus-toolbar">
            <strong>Belge İnceleme</strong>
            <div className="portal-next-focus-document">
              <span>{selectedDocument?.fileName || "Belge seçilmedi"}</span>
              {queueHidden ? (
                <strong>Evrak {selectedDocument && selectedDocumentPosition > 0 ? safeDocumentPosition : 0} / {navigationDocuments.length}</strong>
              ) : null}
            </div>
            <div>
              <button className={`queue-action${queueHidden ? " active" : ""}`} onClick={() => setQueueHidden((current) => !current)} type="button"><span aria-hidden="true">☰</span> {queueHidden ? "Kuyruğu göster" : "Kuyruğu gizle"}</button>
              <button onClick={() => setJournalHidden((current) => !current)} type="button">{journalHidden ? "Fişi göster" : "Fişi gizle"}</button>
              <button className={`fullscreen-action${workspaceFullscreen ? " active" : ""}`} onClick={() => void toggleWorkspaceFullscreen()} title="Tarayıcı tam ekran" type="button"><span aria-hidden="true">⛶</span> {workspaceFullscreen ? "Tam ekrandan çık" : "Tam ekran"}</button>
              <button className="focus-close-action" onClick={() => void closeFocusMode()} type="button">× Kapat</button>
            </div>
          </header>
        ) : null}
        {nextPresentation ? (
          <aside className="portal-next-document-queue" aria-label="İncelenecek faturalar">
            <div className="portal-next-queue-head">
              <strong>İncelenecek Faturalar</strong>
              <span>↑ ↓</span>
            </div>
            <div className="portal-next-queue-tools">
              <input aria-label="Kuyrukta ara" onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Ara..." value={documentQuery} />
              <div className="portal-next-direction-tabs">
                {segmentOptions.map((option) => (
                  <button className={selectedDocumentSegment === option.id ? "active" : ""} key={option.id} onClick={() => { setSelectedDocumentSegment(option.id); setSelectedDocumentId(""); }} type="button">
                    {option.label} <strong>{allClientDocuments.filter((document) => documentMatchesSegment(document, option.id)).length}</strong>
                  </button>
                ))}
              </div>
            </div>
            <ol className="portal-next-queue-list">
              {queueDocuments.map((queueDocument) => {
                const active = selectedDocument?.id === queueDocument.id;
                return (
                  <li key={queueDocument.id}>
                    <button className={active ? "active" : ""} onClick={() => selectDocument(queueDocument)} type="button">
                      <span>
                        <strong>{queueDocument.fileName}</strong>
                        <b>{queueDocument.amount || "-"}</b>
                      </span>
                      <small>{queueDocument.issueDate || queueDocument.uploadedAt || "-"} · {labelForIntakeCategory(queueDocument.intakeCategory)}</small>
                      <em>{queueDocument.status === "export_ready" ? "Onaya hazır" : formatStatus(queueDocument.status)}</em>
                    </button>
                  </li>
                );
              })}
            </ol>
          </aside>
        ) : null}
        <section className="document-review-main">
          {controlledPdfPreview || controlledHtmlPreview ? (
            <DocumentPreview controlledHtmlPreview={controlledHtmlPreview} controlledPdfPreview={controlledPdfPreview} document={selectedDocument} onClearSourceTarget={clearDocumentSource} session={session} sourceTarget={sourceTarget} />
          ) : (
            <DocumentPreview document={selectedDocument} onClearSourceTarget={clearDocumentSource} session={session} sourceTarget={sourceTarget} />
          )}
          <JournalPanel
            correctionDraft={correctionDraft}
            decisionStatus={decisionStatus}
            document={selectedDocument}
            hasUnsavedReviewChanges={hasUnsavedReviewChanges}
            nextKeyboardShortcuts={nextPresentation}
            onApproveAndNext={onApproveAndNext}
            onResetDraft={() => setCorrectionDraft({ accountCode: "", applyToSimilar: false, readerValidation: "", accountingValidation: "", counterpartyCode: "", manualDraftLines: [], reason: "", ruleInstruction: "" })}
            onFocusSource={focusDocumentSource}
            onHoverSource={hoverDocumentSource}
            onReprocessDocument={onReprocessDocument}
            onRequestStatementAi={onRequestStatementAi}
            onSaveDecision={onSaveDecision}
            onSaveStatementDecision={onSaveStatementDecision}
            selectedStatementLineNo={selectedStatementLineNo}
            session={session}
            sourceTarget={sourceTarget}
            setCorrectionDraft={setCorrectionDraft}
            setSelectedStatementLineNo={setSelectedStatementLineNo}
            statementAiStatus={statementAiStatus}
          />
        </section>
      </section>

      <details className="debug-accordion">
        <summary>
          <span>Teknik geçmiş</span>
          <strong>Debug için aç</strong>
        </summary>
        <DocumentPipelineTimeline events={selectedDocument?.pipelineEvents ?? []} />
        <AiTracePanel document={selectedDocument} />
      </details>

      <PortalNextWorkspaceControls
        active={nextPresentation}
        onNavigateDocument={navigateDocument}
        onToggleSidebar={onToggleSidebar}
        onUndoLastApproval={onUndoLastApproval}
        undoAvailable={undoAvailable}
      />


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
                    !documentProcessingComplete(document) ? (
                      <button disabled type="button">Final bekleniyor</button>
                    ) : document.directionConflict?.status === "needs_review" ? (
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
          {!queueDocuments.length ? <p className="empty">Bu filtrede belge yok. Mükellef seçin veya filtreyi değiştirin.</p> : null}
        </div>
      </section>
    </section>
  );
}
