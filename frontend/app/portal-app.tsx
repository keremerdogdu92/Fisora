// File: frontend/app/portal-app.tsx
// Summary: Composes authenticated portal routes, workspace state, selected-document progress polling, and review commands.
"use client";
import { useEffect, useMemo, useState } from "react";
import { AgentTrainingView } from "./portal-agents-view";
import { AccountantDashboard } from "./portal-dashboard-view";
import { readDashboardOfficePeriod, readDashboardResume, writeDashboardOfficePeriod, writeDashboardResume, type DashboardResumeState } from "./portal-dashboard-resume";
import { ClientPortal } from "./portal-client-view";
import { ClientManagementView } from "./portal-clients-view";
import { DocumentProcessingWorkspace } from "./portal-documents-view";
import { ExportBasketView as ExportBasketRouteView, OperationsView as OperationsRouteView } from "./portal-exports-view";
import { SettingsView } from "./portal-settings-view";
import { PortalNextWorkTypeTabs, type PortalNextAgentSection } from "./portal-next/portal-next-shell";
import { PortalNextAgentsView, PortalNextLearnedRulesView } from "./portal-next/portal-next-agents-view";
import { resolvePortalNextWorkspacePeriod } from "./portal-next/portal-next-workspace-model";
import { PortalPresentationChrome, type PortalPresentation } from "./portal-presentation-chrome";
import { AccountantWorkspace } from "./portal-workspace-view";
import { loginWithPassword, persistSession, resolveApiBaseUrl, usePortalSessionGuard, useTestDataReset } from "./features/session";
import {
  PilotQueryProvider,
  buildPilotReadinessView,
  loadInitialPilotData,
  refreshBackendPilotData as refreshBackendPilotDataAction,
  useAiCapacityQuery,
  usePilotReadinessQuery,
  useProgressiveSelectedDocument,
} from "./features/workspace";
import { useClientManagementCommands } from "./features/clients";
import { useDocumentRetentionCommands } from "./features/operations";
import { useNotifications } from "./features/notifications";
import { useQnbCommands } from "./features/qnb";
import { addLocalUploadsAction, useDocumentWorkflow } from "./features/documents";
import { useExportCommands } from "./features/export";
import { buildPortalDashboardViewModels } from "./portal-dashboard";
import { PORTAL_NAV_ITEMS, portalConfigForRouteKey } from "./portal-routes";
import type {
  CancellationRequest,
  CorrectionDraft,
  DocumentSegment,
  ExportMode,
  IntakeCategory, LocalSession,
  PilotData,
  PilotMode, PilotReadinessView, PortalNavItem,
  PortalRouteKey,
} from "./portal-types";
import { emptyPilotData } from "./portal-data-mappers";
import { scopePilotDataForSession } from "./portal-data-scope";
import { periodLabel } from "./portal-formatters";
import { previousCompletedPeriod } from "./portal-periods";
import { emptyCorrectionDraft, useReviewCommands } from "./features/review";
import { useReviewEditLease } from "./features/review";
type WorkspaceSourceState = { label: string; status: "loading" | "backend" | "empty" | "fallback" | "error"; detail: string };
const SIDEBAR_COLLAPSED_STORAGE_KEY = "fisora.portal.sidebar.collapsed";
export function FisoraPortalApp({ routeKey = "home", presentation = "legacy" }: { routeKey?: PortalRouteKey | string; presentation?: PortalPresentation }) {
  return (
    <PilotQueryProvider>
      <FisoraPortalContent presentation={presentation} routeKey={routeKey} />
    </PilotQueryProvider>
  );
}
function workspaceSourceState(payload: PilotData, nextSource: string): WorkspaceSourceState {
  if (nextSource === "Backend okunamadı") {
    return {
      label: "Backend okunamadı",
      status: "error",
      detail: "Oturum veya sunucu yanıtı gerekli. Lütfen tekrar giriş yapın.",
    };
  }
  if (nextSource === "Yerel çalışma verisi") {
    return {
      label: nextSource,
      status: "fallback",
      detail: "Backend okunamadı; yerel çalışma verisi gösteriliyor.",
    };
  }
  if (!payload.clients.length) {
    return {
      label: nextSource || "Çalışma alanı boş",
      status: "empty",
      detail: "Sunucu yanıt verdi, mükellef bulunamadı.",
    };
  }
  return {
    label: nextSource || "Çalışma alanı",
    status: "backend",
    detail: "Sunucu çalışma alanı kullanılıyor.",
  };
}
function FisoraPortalContent({ routeKey = "home", presentation = "legacy" }: { routeKey?: PortalRouteKey | string; presentation?: PortalPresentation }) {
  const portalConfig = useMemo(() => portalConfigForRouteKey(routeKey), [routeKey]);
  const isNextPresentation = presentation === "next";
  const lockedRole = portalConfig.lockedRole as LocalSession["role"] | undefined;
  const visibleNavItems = (PORTAL_NAV_ITEMS as PortalNavItem[]).filter((item) =>
    portalConfig.visibleModes.includes(item.mode),
  );
  const [data, setData] = useState<PilotData>(emptyPilotData);
  const [source, setSource] = useState<WorkspaceSourceState>({
    label: "Çalışma alanı yükleniyor",
    status: "loading",
    detail: "Sunucu çalışma alanı okunuyor.",
  });
  const [readinessPayload, setReadinessPayload] = useState<Record<string, unknown> | null>(null);
  const [localFallbackAllowed, setLocalFallbackAllowed] = useState(false);
  const [mode, setModeState] = useState<PilotMode>(portalConfig.initialMode as PilotMode);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [officePeriod, setOfficePeriod] = useState("");
  const [dashboardResumeState, setDashboardResumeState] = useState<DashboardResumeState | null>(null);
  const [selectedIntakeCategory, setSelectedIntakeCategory] = useState<IntakeCategory>("purchase_invoice");
  const [clientSearch, setClientSearch] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  useEffect(() => {
    if (!isNextPresentation || typeof window === "undefined") return;
    try {
      setSidebarCollapsed(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true");
    } catch {
      // Local preferences are optional; the portal must remain usable when storage is blocked.
    }
  }, [isNextPresentation]);

  function toggleSidebarCollapsed() {
    setSidebarCollapsed((current) => {
      const next = !current;
      if (isNextPresentation && typeof window !== "undefined") {
        try {
          window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(next));
        } catch {
          // Keep the in-memory toggle working even when local storage is unavailable.
        }
      }
      return next;
    });
  }
  const [nextAgentSection, setNextAgentSection] = useState<PortalNextAgentSection>("agents");
  const { session, sessionHydrated, setSession } = usePortalSessionGuard({ lockedRole, portalConfig, routeKey: String(routeKey), setLocalFallbackAllowed });
  const [loginUserId, setLoginUserId] = useState(portalConfig.defaultUserId);
  const [loginPassword, setLoginPassword] = useState("");
  const [loginRole, setLoginRole] = useState<"client_user" | "accountant">(portalConfig.defaultRole as "client_user" | "accountant");
  const [loginStatus, setLoginStatus] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [clientCancellationDocumentId, setClientCancellationDocumentId] = useState("");
  const [decisionStatus, setDecisionStatus] = useState("");
  const [statementAiStatus, setStatementAiStatus] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [exportMode, setExportMode] = useState<ExportMode>("bulk");
  const [exportType, setExportType] = useState("zirve_mapping_csv");
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>(() => emptyCorrectionDraft());
  const notificationApiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
  const notifications = useNotifications({ apiBaseUrl: notificationApiBaseUrl, session });
  const readinessQuery = usePilotReadinessQuery();
  const aiCapacityQuery = useAiCapacityQuery({ defaultUserId: portalConfig.defaultUserId, session });

  function applyPilotData(payload: PilotData, nextSource: string) {
    const scopedPayload = scopePilotDataForSession(payload, session);
    setData(scopedPayload);
    setSource(workspaceSourceState(scopedPayload, nextSource));
    setSelectedClientId((current) =>
      current && scopedPayload.clients.some((client) => client.clientId === current)
        ? current
        : scopedPayload.clients[0]?.clientId ?? "",
    );
    setSelectedPeriod(previousCompletedPeriod());
  }

  async function refreshBackendPilotData(shouldCancel: () => boolean = () => false) {
    return refreshBackendPilotDataAction({
      applyPilotData,
      defaultUserId: portalConfig.defaultUserId,
      session,
      shouldCancel,
    });
  }

  useEffect(() => {
    if (!sessionHydrated) return;
    let cancelled = false;
    void loadInitialPilotData({
      applyPilotData,
      defaultUserId: portalConfig.defaultUserId,
      explicitAllowLocalFallback: process.env.NEXT_PUBLIC_FISORA_ALLOW_LOCAL_FALLBACK === "true",
      session,
      setLocalFallbackAllowed,
      shouldCancel: () => cancelled,
    });
    return () => {
      cancelled = true;
    };
  }, [routeKey, session?.sessionToken, session?.userId, sessionHydrated]);

  useEffect(() => {
    if (readinessQuery.data) {
      setReadinessPayload(readinessQuery.data);
      return;
    }
    if (readinessQuery.isError) {
      setReadinessPayload(null);
    }
  }, [readinessQuery.data, readinessQuery.isError]);

  const clients = data.clients;
  const officePeriods = useMemo(() => {
    const periods = Array.from(new Set(data.documents.map((document) => document.period).filter(Boolean))).sort().reverse();
    return periods.length ? periods : [previousCompletedPeriod()];
  }, [data.documents]);
  const resolvedOfficePeriod = officePeriod && officePeriods.includes(officePeriod) ? officePeriod : officePeriods[0] || previousCompletedPeriod();
  const selectedClient = clients.find((client) => client.clientId === selectedClientId) ?? clients[0];
  useEffect(() => {
    if (!isNextPresentation || !session?.userId) return;
    const storedOfficePeriod = readDashboardOfficePeriod(session.userId);
    if (storedOfficePeriod) setOfficePeriod(storedOfficePeriod);
    setDashboardResumeState(readDashboardResume(session.userId));
  }, [isNextPresentation, session?.userId]);
  useEffect(() => {
    if (!isNextPresentation || !session?.userId || !resolvedOfficePeriod) return;
    writeDashboardOfficePeriod(session.userId, resolvedOfficePeriod);
  }, [isNextPresentation, resolvedOfficePeriod, session?.userId]);
  const {
    qnbConnection, qnbStatus, qnbHealth,
    qnbPolicy,
    qnbSyncWindow,
    disableQnb,
    refreshQnbStatus,
    saveQnbConnection,
    syncQnbIncoming,
    updateQnbConnection,
  } = useQnbCommands({
    loginUserId,
    refreshBackendPilotData: () => refreshBackendPilotData(),
    selectedClient,
    session,
  });
  const {
    chartUploadStatus, clientDocumentDeleteConfirmed, clientDocumentDeleteStatus, clientReprocessStatus,
    clientPortalOpenStatus,
    createInviteForSelectedClient,
    createNewClient,
    deleteSelectedClientDocuments,
    inviteStatus,
    newClientDraft,
    newClientNaceResearchPending, newClientNaceResearchProfile, newClientNaceResearchStatus,
    newClientStatus,
    newClientTaxCertificateFile,
    newClientTaxCertificateInputKey, newClientTaxCertificateParsePending, newClientTaxCertificateStage,
    parseNewClientChartAccounts,
    openSelectedClientPortal,
    portalPassword,
    portalPasswordStatus,
    portalUserIdDraft, reprocessSelectedClient,
    refreshNewClientNaceResearch,
    selectNewClientTaxCertificate,
    selectedClientDocumentRefs,
    setClientDocumentDeleteConfirmed,
    setNewClientDraft,
    setPortalPasswordDraft,
    setPortalUserIdDraft,
    setSelectedClientDocumentRefs,
    setPasswordForSelectedClient,
    updatePortalAccessForSelectedClient,
    uploadChartAccounts,
  } = useClientManagementCommands({
    loginUserId,
    refreshBackendPilotData: () => refreshBackendPilotData(),
    selectedClient,
    session,
    setSelectedClientId,
  });
  const clientDocuments = useMemo(() => {
    return data.documents.filter((document) => document.clientId === selectedClient?.clientId);
  }, [data.documents, selectedClient?.clientId]);
  const clientPeriods = useMemo(() => {
    return Array.from(new Set([previousCompletedPeriod(), ...clientDocuments.map((document) => document.period).filter(Boolean)])).sort().reverse();
  }, [clientDocuments]);
  const periodDocuments = useMemo(() => {
    return clientDocuments.filter((document) => !selectedPeriod || document.period === selectedPeriod);
  }, [clientDocuments, selectedPeriod]);
  const nextWorkspacePeriod = resolvePortalNextWorkspacePeriod({ documents: clientDocuments, fallbackPeriod: previousCompletedPeriod(), selectedPeriod });
  const workflowClientDocuments = isNextPresentation ? nextWorkspacePeriod.documents : clientDocuments;
  const workflowAllDocuments = isNextPresentation && nextWorkspacePeriod.selectedPeriod ? data.documents.filter((document) => document.period === nextWorkspacePeriod.selectedPeriod) : data.documents;
  const {
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
  } = useDocumentWorkflow({
    allDocuments: workflowAllDocuments,
    clientDocuments: workflowClientDocuments,
    mode, initialReviewFilter: isNextPresentation ? "all" : "review_required", selectionScopeKey: isNextPresentation ? nextWorkspacePeriod.selectedPeriod : "",
    selectedClientId: selectedClient?.clientId,
  });
  useEffect(() => {
    if (!isNextPresentation || mode !== "documents" || !session?.userId || !selectedClient?.clientId || !nextWorkspacePeriod.selectedPeriod) return;
    const nextResume: DashboardResumeState = {
      clientId: selectedClient.clientId,
      period: nextWorkspacePeriod.selectedPeriod,
      segment: selectedDocumentSegment,
      documentId: selectedDocumentId || "",
      updatedAt: new Date().toISOString(),
    };
    writeDashboardResume(session.userId, nextResume);
    setDashboardResumeState(nextResume);
  }, [isNextPresentation, mode, nextWorkspacePeriod.selectedPeriod, selectedClient?.clientId, selectedDocumentId, selectedDocumentSegment, session?.userId]);
  useEffect(() => {
    setCorrectionDraft(emptyCorrectionDraft());
  }, [selectedDocument?.id]);
  const { progressiveActiveReviewDocuments, progressiveClientDocuments, progressiveSelectedDocument } = useProgressiveSelectedDocument({
    activeReviewDocuments, clientDocuments: workflowClientDocuments, defaultUserId: portalConfig.defaultUserId,
    enabled: mode === "documents", refreshBackendPilotData, selectedDocument, session,
  });
  const clientSelectedDocument = periodDocuments.find((document) => document.id === selectedDocumentId);
  const filteredClients = useMemo(() => {
    const query = clientSearch.trim().toLocaleLowerCase("tr-TR");
    if (!query) return clients;
    return clients.filter((client) => `${client.clientName} ${client.clientId} ${client.taxId}`.toLocaleLowerCase("tr-TR").includes(query));
  }, [clientSearch, clients]);
  const openCancellationRequests = data.cancellationRequests.filter((request) => request.status === "open");
  const officeDocuments = useMemo(() => data.documents.filter((document) => !resolvedOfficePeriod || document.period === resolvedOfficePeriod), [data.documents, resolvedOfficePeriod]);
  const officeCancellationRequests = useMemo(() => {
    const officeDocumentIds = new Set(officeDocuments.map((document) => document.id));
    return data.cancellationRequests.filter((request) => officeDocumentIds.has(request.documentId));
  }, [data.cancellationRequests, officeDocuments]);
  const dashboardView = useMemo(() => buildPortalDashboardViewModels({
    data: { clients: data.clients, documents: officeDocuments, cancellationRequests: officeCancellationRequests },
    aiCapacity: aiCapacityQuery.data,
  }), [aiCapacityQuery.data, data.clients, officeCancellationRequests, officeDocuments]);
  const dashboardResume = useMemo(() => {
    if (!dashboardResumeState) return null;
    const resumeClient = data.clients.find((client) => client.clientId === dashboardResumeState.clientId);
    if (!resumeClient) return null;
    const resumeDocuments = data.documents.filter((document) => document.clientId === dashboardResumeState.clientId && document.period === dashboardResumeState.period);
    const completedCount = resumeDocuments.filter((document) => ["export_ready", "export_added", "exported"].includes(document.status)).length;
    return { ...dashboardResumeState, clientName: resumeClient.clientName, completedCount, totalCount: resumeDocuments.length };
  }, [dashboardResumeState, data.clients, data.documents]);
  const readinessView = useMemo(
    () => buildPilotReadinessView(readinessPayload) as PilotReadinessView,
    [readinessPayload],
  );
  const visibleDashboardClientRows = useMemo(() => {
    const visibleIds = new Set(filteredClients.map((client) => client.clientId));
    return dashboardView.dashboardClientRows.filter((row: { clientId: string }) => visibleIds.has(row.clientId));
  }, [dashboardView.dashboardClientRows, filteredClients]);

  function setMode(nextMode: PilotMode) {
    if (portalConfig.visibleModes.includes(nextMode)) setModeState(nextMode);
  }

  function dashboardSegmentForDocument(document: PilotData["documents"][number]): DocumentSegment {
    if (document.intakeCategory === "bank_statement") return "bank_statements";
    if (document.intakeCategory === "special_document") return "other_documents";
    return "invoices";
  }

  function openDashboardDocument(document: PilotData["documents"][number]) {
    setSelectedClientId(document.clientId);
    setSelectedPeriod(document.period);
    setSelectedDocumentSegment(dashboardSegmentForDocument(document));
    setReviewFilter("all");
    setSelectedDocumentId(document.id);
    setMode("documents");
  }

  function openDashboardTask(segment: DocumentSegment) {
    const target = officeDocuments.find((document) => {
      if (document.status !== "review_required") return false;
      if (segment === "bank_statements") return document.intakeCategory === "bank_statement";
      if (segment === "other_documents") return document.intakeCategory === "special_document";
      return document.intakeCategory === "purchase_invoice" || document.intakeCategory === "sales_invoice";
    });
    setSelectedDocumentSegment(segment);
    setReviewFilter("review_required");
    if (target) {
      setSelectedClientId(target.clientId);
      setSelectedPeriod(target.period);
      setSelectedDocumentId(target.id);
    } else {
      setSelectedPeriod(resolvedOfficePeriod);
      setSelectedDocumentId("");
    }
    setMode("documents");
  }

  function openDashboardWorkspace() {
    const target = officeDocuments.find((document) => document.status === "review_required")
      ?? officeDocuments.find((document) => ["uploaded", "queued", "processing"].includes(document.status))
      ?? officeDocuments[0];
    if (target) openDashboardDocument(target);
    else setMode("documents");
  }

  function resumeDashboardWork() {
    if (!dashboardResume) return;
    setSelectedClientId(dashboardResume.clientId);
    setSelectedPeriod(dashboardResume.period);
    setSelectedDocumentSegment(dashboardResume.segment);
    setReviewFilter("all");
    const resumeDocumentExists = data.documents.some((document) => document.id === dashboardResume.documentId);
    setSelectedDocumentId(resumeDocumentExists ? dashboardResume.documentId : "");
    setMode("documents");
  }

  async function login() {
    const userId = loginUserId.trim() || "ofis-user";
    const password = loginPassword.trim();
    const effectiveRole = (lockedRole ?? loginRole) as "client_user" | "accountant";
    if (password) {
      setLoginStatus("Oturum açılıyor.");
      try {
        const backendSession = await loginWithPassword({
          apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
          userId,
          password,
        });
        const nextSession: LocalSession = {
          userId: backendSession.userId || userId,
          role: effectiveRole,
          sessionToken: backendSession.sessionToken,
          expiresAt: backendSession.expiresAt,
        };
        persistSession(nextSession);
        setSession(nextSession);
        setLoginPassword("");
        setLoginStatus(`${nextSession.userId} için oturum açıldı.`);
        setMode(nextSession.role === "client_user" ? "client" : (portalConfig.initialMode as PilotMode));
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setLoginStatus(`Oturum açılamadı. ${message}`);
        return;
      }
    }
    if (!localFallbackAllowed) {
      setLoginStatus("Bu ortamda şifresiz ofis oturumu kapalı. Kullanıcı şifresiyle girin.");
      return;
    }
    const nextSession: LocalSession = { userId, role: effectiveRole };
    persistSession(nextSession);
    setSession(nextSession);
    setLoginStatus(`${nextSession.userId} için lokal ofis oturumu açıldı.`);
    setMode(nextSession.role === "client_user" ? "client" : (portalConfig.initialMode as PilotMode));
  }

  function logout() {
    persistSession(null);
    setSession(null);
    setLoginStatus("Oturum kapatıldı.");
  }

  function exitPortal() {
    logout();
    if (typeof window !== "undefined") window.location.assign("/");
  }
  const addLocalUploads = (files: FileList | null) => {
    void addLocalUploadsAction({
      files,
      localFallbackAllowed,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      selectedClient,
      selectedIntakeCategory,
      session,
      setData,
      setSelectedPeriod,
      setUploadStatus,
    });
  };

  const {
    addSelectedClientToBasket,
    markBasketPackaged,
    requestCancellation,
    resolveCancellation,
  } = useExportCommands({
    cancelReason, clientDocuments, exportBasket: data.exportBasket, exportMode, exportType, loginUserId, selectedClient, selectedPeriod, session,
    setCancelReason,
    setClientCancellationDocumentId,
    setData,
    setExportStatus,
    setSelectedDocumentId,
  });
  const hasUnsavedReviewChanges = useMemo(() => Boolean(correctionDraft.accountCode.trim() || correctionDraft.counterpartyCode.trim() || correctionDraft.reason.trim() || correctionDraft.ruleInstruction.trim() || correctionDraft.applyToSimilar || correctionDraft.manualDraftLines.length), [correctionDraft]);
  useReviewEditLease({ correctionDraft, hasUnsavedReviewChanges, loginUserId, selectedDocument, session, onStatus: (status) => { if (status !== "idle") setDecisionStatus(status); } });
  const { approveSelectedAndMoveNext, reprocessSelectedDocument, requestStatementAiForSelectedDocument,
    saveDecision, saveStatementLineDecision, undoAvailable, undoLastApproval } = useReviewCommands({
    activeReviewDocuments,
    correctionDraft,
    hasUnsavedReviewChanges,
    localFallbackAllowed,
    loginUserId,
    refreshBackendPilotData: () => refreshBackendPilotData(),
    selectedDocument,
    selectedStatementLineNo,
    session,
    setData,
    setDecisionStatus,
    setSelectedDocumentId,
    setSelectedStatementLineNo,
    setStatementAiStatus,
  });
  const testDataReset = useTestDataReset({ loginUserId, refreshBackendPilotData: () => refreshBackendPilotData(), session, setSelectedClientId, setSelectedDocumentId });
  const { deleteRetentionDocuments, extendRetentionDocuments, previewRetention, retentionDocuments, retentionStatus } = useDocumentRetentionCommands({
    defaultUserId: portalConfig.defaultUserId, loginUserId, refreshBackendPilotData: () => refreshBackendPilotData(), session,
  });
  const activeNavItem = (PORTAL_NAV_ITEMS as PortalNavItem[]).find((item) => item.mode === mode);
  const showSidebar = visibleNavItems.length > 1;

  if (!sessionHydrated || (lockedRole && !session)) return <main className="landing-shell"><p className="decision-status">Oturum doğrulanıyor.</p></main>;

  const shellClassName = showSidebar
    ? `private-shell portal-shell${sidebarCollapsed ? " sidebar-collapsed" : ""}${isNextPresentation ? " portal-next-theme" : ""}`
    : `private-shell portal-shell no-sidebar${isNextPresentation ? " portal-next-theme" : ""}`;

  const legacySubtitle = mode === "client" && session?.delegatedBy ? "Müşavir vekaletinde işlem yapılıyor" : "";
  const legacyTitle = mode === "client" ? selectedClient?.clientName || "Mükellef portalı" : mode === "documents" ? "Fatura İşleme" : activeNavItem?.label || "Müşavir çalışma alanı";

  return (
    <main className={shellClassName}>
      <PortalPresentationChrome
        activeDocumentSegment={selectedDocumentSegment} agentSection={nextAgentSection} collapsed={sidebarCollapsed}
        legacySubtitle={legacySubtitle} legacyTitle={legacyTitle} mobileOpen={mobileSidebarOpen} mode={mode} navItems={visibleNavItems}
        clients={clients} notificationPendingCount={notifications.pendingCount} notifications={notifications.notifications}
        onCloseMobile={() => setMobileSidebarOpen(false)} onExit={exitPortal}
        onLegacyNavigate={(nextMode, segment) => { if (segment) setSelectedDocumentSegment(segment); setMode(nextMode); setMobileSidebarOpen(false); }}
        onNextNavigate={(nextMode, agentSection) => { if (agentSection) setNextAgentSection(agentSection); setMode(nextMode); setMobileSidebarOpen(false); }}
        onReadNotification={notifications.markRead} onSelectClient={(clientId) => { setSelectedClientId(clientId); setSelectedPeriod(""); setSelectedDocumentId(""); }} onSelectPeriod={(period) => {
          if (isNextPresentation && mode !== "documents") setOfficePeriod(period);
          else { setSelectedPeriod(period); setSelectedDocumentId(""); }
        }} onToggleCollapse={toggleSidebarCollapsed}
        onToggleMobile={() => setMobileSidebarOpen((current) => !current)} periods={isNextPresentation ? (mode === "documents" ? nextWorkspacePeriod.periods : officePeriods) : clientPeriods} presentation={presentation}
        selectedClient={selectedClient} selectedPeriod={isNextPresentation ? (mode === "documents" ? nextWorkspacePeriod.selectedPeriod : resolvedOfficePeriod) : selectedPeriod} session={session} showSidebar={showSidebar} source={source}
      >
      <div className="portal-route-content">

      {mode === "client" ? (
        <ClientPortal
          cancelReason={cancelReason}
          cancellationDocumentId={clientCancellationDocumentId}
          documents={periodDocuments}
          onCancelReasonChange={setCancelReason}
          onFilesSelected={addLocalUploads}
          onOpenCancellationRequest={(document) => {
            setSelectedDocumentId(document.id);
            setClientCancellationDocumentId(document.id);
          }}
          onRequestCancellation={requestCancellation}
          onSelectDocument={(document) => {
            setSelectedDocumentId(document.id);
            setClientCancellationDocumentId((current) => current === document.id ? current : "");
          }}
          periods={clientPeriods}
          selectedClient={selectedClient}
          selectedDocument={clientSelectedDocument}
          selectedIntakeCategory={selectedIntakeCategory}
          selectedPeriod={selectedPeriod}
          uploadPeriod={previousCompletedPeriod()}
          session={session}
          setSelectedIntakeCategory={(value) => {
            setSelectedIntakeCategory(value);
            setSelectedDocumentId("");
            setClientCancellationDocumentId("");
          }}
          setSelectedPeriod={(value) => {
            setSelectedPeriod(value);
            setSelectedDocumentId("");
            setClientCancellationDocumentId("");
          }}
          uploadStatus={uploadStatus}
        />
      ) : null}
      {mode === "agents" ? (
        isNextPresentation ? (
          nextAgentSection === "agents" ? (
            <PortalNextAgentsView agentSummaries={dashboardView.agentSummaries} documents={officeDocuments} learningInsights={dashboardView.learningInsights} loginUserId={loginUserId} onOpenDocument={openDashboardDocument} session={session} />
          ) : (
            <PortalNextLearnedRulesView loginUserId={loginUserId} session={session} />
          )
        ) : (
          <AgentTrainingView key={String(routeKey)} agentSummaries={dashboardView.agentSummaries} defaultSection={routeKey === "bilgi-havuzu" ? "research" : "learning"} learningInsights={dashboardView.learningInsights} loginUserId={loginUserId} session={session} />
        )
      ) : null}

      {mode === "accountant" ? (
        <AccountantDashboard
          clientRows={isNextPresentation ? dashboardView.dashboardClientRows : visibleDashboardClientRows}
          dashboardMetrics={dashboardView.dashboardMetrics}
          documents={isNextPresentation ? officeDocuments : data.documents}
          isLoading={source.status === "loading"}
          nextPresentation={isNextPresentation}
          officePeriod={resolvedOfficePeriod}
          onClientSelect={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
          onOpenAgents={() => { setNextAgentSection("agents"); setMode("agents"); }}
          onOpenClients={() => setMode("clients")}
          onOpenDocument={openDashboardDocument}
          onOpenTask={openDashboardTask}
          onOpenWorkspace={openDashboardWorkspace}
          onResume={resumeDashboardWork}
          priorityItems={dashboardView.priorityItems}
          resume={dashboardResume}
          selectedClientId={selectedClient?.clientId ?? ""}
        />
      ) : null}

      {mode === "documents" ? (
        <>
        {isNextPresentation ? (
          <PortalNextWorkTypeTabs documents={progressiveClientDocuments} selectedSegment={selectedDocumentSegment}
            onSelect={(segment) => { setSelectedDocumentSegment(segment); setSelectedDocumentId(""); }} />
        ) : null}
        <DocumentProcessingWorkspace
          aiCapacity={aiCapacityQuery.data}
          capacityError={aiCapacityQuery.isError}
          capacityPending={aiCapacityQuery.isPending}
        >
        <AccountantWorkspace
          cancellationRequests={openCancellationRequests.filter((request) => request.clientId === selectedClient?.clientId)} controlledHtmlPreview={isNextPresentation} controlledPdfPreview={isNextPresentation} nextPresentation={isNextPresentation}
          statementAiStatus={statementAiStatus}
          clientSearch={clientSearch}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          correctionDraft={correctionDraft}
          dashboardMetrics={dashboardView.dashboardMetrics}
          decisionStatus={decisionStatus}
          documents={progressiveActiveReviewDocuments}
          allClientDocuments={progressiveClientDocuments}
          hasUnsavedReviewChanges={hasUnsavedReviewChanges}
          newClientDraft={newClientDraft}
          newClientStatus={newClientStatus}
          newClientTaxCertificateFile={newClientTaxCertificateFile}
          newClientTaxCertificateInputKey={newClientTaxCertificateInputKey}
          onAddToBasket={addSelectedClientToBasket}
          onApproveAndNext={approveSelectedAndMoveNext}
          onCreateNewClient={createNewClient}
          onClientSearchChange={setClientSearch}
          onTaxCertificateFileChange={selectNewClientTaxCertificate}
          onToggleSidebar={toggleSidebarCollapsed}
          onUndoLastApproval={undoLastApproval}
          onReprocessDocument={reprocessSelectedDocument}
          onRequestStatementAi={requestStatementAiForSelectedDocument}
          onResolveCancellation={resolveCancellation}
          onSaveDecision={saveDecision}
          onSaveStatementDecision={saveStatementLineDecision}
          reviewFilter={reviewFilter}
          selectedClient={selectedClient}
          selectedDocument={progressiveSelectedDocument}
          selectedDocumentSegment={selectedDocumentSegment}
          selectedStatementLineNo={selectedStatementLineNo}
          session={session} undoAvailable={undoAvailable}
          setCorrectionDraft={setCorrectionDraft}
          setNewClientDraft={setNewClientDraft}
          setReviewFilter={setReviewFilter}
          setSelectedClientId={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
          setSelectedDocumentId={setSelectedDocumentId}
          setSelectedDocumentSegment={setSelectedDocumentSegment}
          setSelectedStatementLineNo={setSelectedStatementLineNo}
        />
        </DocumentProcessingWorkspace>
        </>
      ) : null}

      {mode === "clients" ? (
        <ClientManagementView
          cancellationRequests={openCancellationRequests}
          chartUploadStatus={chartUploadStatus} clientDocumentDeleteConfirmed={clientDocumentDeleteConfirmed} clientDocumentDeleteStatus={clientDocumentDeleteStatus}
          clientPortalOpenStatus={clientPortalOpenStatus}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          clientSearch={clientSearch}
          documents={clientDocuments}
          isLoading={source.status === "loading"}
          inviteStatus={inviteStatus}
          newClientDraft={newClientDraft}
          newClientNaceResearchPending={newClientNaceResearchPending} newClientNaceResearchProfile={newClientNaceResearchProfile} newClientNaceResearchStatus={newClientNaceResearchStatus}
          newClientStatus={newClientStatus}
          newClientTaxCertificateFile={newClientTaxCertificateFile}
          newClientTaxCertificateInputKey={newClientTaxCertificateInputKey} newClientTaxCertificateParsePending={newClientTaxCertificateParsePending} newClientTaxCertificateStage={newClientTaxCertificateStage}
          onChartFileSelected={parseNewClientChartAccounts}
          onExistingChartFileSelected={uploadChartAccounts}
          onClientSearchChange={setClientSearch}
          onCreateInvite={createInviteForSelectedClient}
          onCreateNewClient={createNewClient}
          onDeleteSelectedDocuments={deleteSelectedClientDocuments} onReprocessSelectedClient={reprocessSelectedClient}
          onOpenClientPortal={openSelectedClientPortal}
          onResolveCancellation={resolveCancellation}
          onRefreshNaceResearch={refreshNewClientNaceResearch}
          onSetPassword={setPasswordForSelectedClient}
          onUpdatePortalAccess={updatePortalAccessForSelectedClient}
          onTaxCertificateFileChange={selectNewClientTaxCertificate}
          portalPassword={portalPassword}
          portalPasswordStatus={portalPasswordStatus}
          portalUserIdDraft={portalUserIdDraft}
          selectedClient={selectedClient} clientReprocessStatus={clientReprocessStatus}
          selectedDocumentRefs={selectedClientDocumentRefs}
          setClientDocumentDeleteConfirmed={setClientDocumentDeleteConfirmed}
          setNewClientDraft={setNewClientDraft}
          setPortalPassword={setPortalPasswordDraft}
          setPortalUserIdDraft={setPortalUserIdDraft}
          setSelectedDocumentRefs={setSelectedClientDocumentRefs}
          setSelectedClientId={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
        />
      ) : null}

      {mode === "settings" ? (
        <SettingsView
          dashboardMetrics={dashboardView.dashboardMetrics}
          loginPassword={loginPassword}
          loginRole={loginRole}
          loginStatus={loginStatus}
          loginUserId={loginUserId}
          lockedRole={lockedRole}
          onLogin={login}
          onLogout={logout}
          onQnbConnectionChange={updateQnbConnection} onQnbDisable={disableQnb} onQnbRefreshStatus={refreshQnbStatus} onQnbSaveConnection={saveQnbConnection} onQnbSyncIncoming={syncQnbIncoming}
          localFallbackAllowed={localFallbackAllowed}
          qnbConnection={qnbConnection} qnbStatus={qnbStatus} qnbSyncWindow={qnbSyncWindow} qnbPolicy={qnbPolicy} qnbHealth={qnbHealth}
          readinessView={readinessView}
          selectedClient={selectedClient}
          session={session}
          setLoginPassword={setLoginPassword}
          setLoginRole={setLoginRole}
          setLoginUserId={setLoginUserId}
          source={source.label}
          {...testDataReset}
        />
      ) : null}

      {mode === "exports" ? (
        <ExportBasketRouteView
          documents={data.documents} exportBasket={data.exportBasket} exportMode={exportMode} exportStatus={exportStatus} exportType={exportType}
          nextPresentation={isNextPresentation}
          onMarkPackaged={markBasketPackaged} periodLabel={periodLabel} setExportMode={setExportMode} setExportType={setExportType}
        />
      ) : null}
      {mode === "operations" ? (
        <OperationsRouteView
          aiCapacity={aiCapacityQuery.data} data={data} localFallbackAllowed={localFallbackAllowed}
          onDeleteRetentionDocuments={deleteRetentionDocuments} onExtendRetentionDocuments={extendRetentionDocuments} onPreviewRetention={previewRetention}
          readinessView={readinessView} retentionDocuments={retentionDocuments} retentionStatus={retentionStatus} source={source.label}
        />
      ) : null}
      </div>
      </PortalPresentationChrome>
    </main>
  );
}
export default function Home() {
  return <FisoraPortalApp routeKey="home" />;
}
