"use client";
import { useEffect, useMemo, useState } from "react";
import { AgentTrainingView } from "./portal-agents-view";
import { AccountantDashboard } from "./portal-dashboard-view";
import { ClientPortal } from "./portal-client-view";
import { ClientManagementView } from "./portal-clients-view";
import { DocumentProcessingWorkspace } from "./portal-documents-view";
import { ExportBasketView as ExportBasketRouteView, OperationsView as OperationsRouteView } from "./portal-exports-view";
import { SettingsView } from "./portal-settings-view";
import { PortalSidebar, PortalTopbarStatus } from "./shared/components";
import { AccountantWorkspace } from "./portal-workspace-view";
import { loginWithPassword, persistSession, resolveApiBaseUrl, usePortalSessionGuard, useTestDataReset } from "./features/session";
import {
  PilotQueryProvider,
  buildPilotReadinessView,
  loadInitialPilotData,
  refreshBackendPilotData as refreshBackendPilotDataAction,
  useAiCapacityQuery,
  usePilotReadinessQuery,
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

export function FisoraPortalApp({ routeKey = "home" }: { routeKey?: PortalRouteKey | string }) {
  return (
    <PilotQueryProvider>
      <FisoraPortalContent routeKey={routeKey} />
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
function FisoraPortalContent({ routeKey = "home" }: { routeKey?: PortalRouteKey | string }) {
  const portalConfig = useMemo(() => portalConfigForRouteKey(routeKey), [routeKey]);
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
  const [selectedIntakeCategory, setSelectedIntakeCategory] = useState<IntakeCategory>("purchase_invoice");
  const [clientSearch, setClientSearch] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
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
  const selectedClient = clients.find((client) => client.clientId === selectedClientId) ?? clients[0];
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
    allDocuments: data.documents,
    clientDocuments,
    mode,
    selectedClientId: selectedClient?.clientId,
  });
  useEffect(() => {
    setCorrectionDraft(emptyCorrectionDraft());
  }, [selectedDocument?.id]);
  const clientSelectedDocument = periodDocuments.find((document) => document.id === selectedDocumentId);
  const filteredClients = useMemo(() => {
    const query = clientSearch.trim().toLocaleLowerCase("tr-TR");
    if (!query) return clients;
    return clients.filter((client) => `${client.clientName} ${client.clientId} ${client.taxId}`.toLocaleLowerCase("tr-TR").includes(query));
  }, [clientSearch, clients]);
  const openCancellationRequests = data.cancellationRequests.filter((request) => request.status === "open");
  const dashboardView = useMemo(() => buildPortalDashboardViewModels({ data, aiCapacity: aiCapacityQuery.data }), [aiCapacityQuery.data, data]);
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
  const {
    approveSelectedAndMoveNext,
    reprocessSelectedDocument,
    requestStatementAiForSelectedDocument,
    saveDecision,
    saveStatementLineDecision,
  } = useReviewCommands({
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

  return (
    <main className={showSidebar ? `private-shell portal-shell${sidebarCollapsed ? " sidebar-collapsed" : ""}` : "private-shell portal-shell no-sidebar"}>
      {showSidebar ? (
        <PortalSidebar
          activeDocumentSegment={selectedDocumentSegment} collapsed={sidebarCollapsed} mobileOpen={mobileSidebarOpen} mode={mode} navItems={visibleNavItems}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onExit={exitPortal}
          onNavigate={(nextMode, segment) => { if (segment) setSelectedDocumentSegment(segment); setMode(nextMode); setMobileSidebarOpen(false); }}
          onToggleCollapse={() => setSidebarCollapsed((current) => !current)}
          session={session}
        />
      ) : null}
      <section className="portal-main-shell">
        <PortalTopbarStatus
          onToggleSidebar={() => setMobileSidebarOpen((current) => !current)}
          showSidebarToggle={showSidebar}
          source={source}
          notifications={notifications.notifications}
          notificationPendingCount={notifications.pendingCount}
          onReadNotification={notifications.markRead}
          subtitle={mode === "client" && session?.delegatedBy ? "Müşavir vekaletinde işlem yapılıyor" : ""}
          title={mode === "client" ? selectedClient?.clientName || "Mükellef portalı" : mode === "documents" ? "Fatura İşleme" : activeNavItem?.label || "Müşavir çalışma alanı"}
        />

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

      {mode === "agents" ? <AgentTrainingView agentSummaries={dashboardView.agentSummaries} defaultSection={routeKey === "bilgi-havuzu" ? "research" : "learning"} learningInsights={dashboardView.learningInsights} loginUserId={loginUserId} session={session} /> : null}

      {mode === "accountant" ? (
        <AccountantDashboard
          clientRows={visibleDashboardClientRows}
          dashboardMetrics={dashboardView.dashboardMetrics}
          documents={data.documents}
          isLoading={source.status === "loading"}
          onClientSelect={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
          onOpenDocument={(document) => {
            setSelectedClientId(document.clientId);
            setSelectedDocumentId(document.id);
            setMode("documents");
          }}
          priorityItems={dashboardView.priorityItems}
          selectedClientId={selectedClient?.clientId ?? ""}
        />
      ) : null}

      {mode === "documents" ? (
        <DocumentProcessingWorkspace
          aiCapacity={aiCapacityQuery.data}
          capacityError={aiCapacityQuery.isError}
          capacityPending={aiCapacityQuery.isPending}
        >
        <AccountantWorkspace
          cancellationRequests={openCancellationRequests.filter((request) => request.clientId === selectedClient?.clientId)}
          statementAiStatus={statementAiStatus}
          clientSearch={clientSearch}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          correctionDraft={correctionDraft}
          dashboardMetrics={dashboardView.dashboardMetrics}
          decisionStatus={decisionStatus}
          documents={activeReviewDocuments}
          allClientDocuments={clientDocuments}
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
          onReprocessDocument={reprocessSelectedDocument}
          onRequestStatementAi={requestStatementAiForSelectedDocument}
          onResolveCancellation={resolveCancellation}
          onSaveDecision={saveDecision}
          onSaveStatementDecision={saveStatementLineDecision}
          reviewFilter={reviewFilter}
          selectedClient={selectedClient}
          selectedDocument={selectedDocument}
          selectedDocumentSegment={selectedDocumentSegment}
          selectedStatementLineNo={selectedStatementLineNo}
          session={session}
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
      </section>
    </main>
  );
}
export default function Home() {
  return <FisoraPortalApp routeKey="home" />;
}
