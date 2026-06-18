"use client";

import { useEffect, useMemo, useState } from "react";
import { AccountantDashboard } from "./portal-dashboard-view";
import { ClientPortal } from "./portal-client-view";
import { ClientManagementView } from "./portal-clients-view";
import { DocumentProcessingWorkspace } from "./portal-documents-view";
import {
  ExportBasketView as ExportBasketRouteView,
  OperationsView as OperationsRouteView,
} from "./portal-exports-view";
import { SettingsView } from "./portal-settings-view";
import { ModeButton, PortalTopbarStatus, SelectedClientStrip } from "./shared/components";
import { AccountantWorkspace } from "./portal-workspace-view";
import {
  loginWithPassword,
  persistSession,
  readStoredSession,
  resolveApiBaseUrl,
  useTestDataReset,
} from "./features/session";
import {
  PilotQueryProvider,
  buildPilotReadinessView,
  loadInitialPilotData,
  refreshBackendPilotData as refreshBackendPilotDataAction,
  usePilotReadinessQuery,
} from "./features/workspace";
import {
  createInviteForSelectedClientAction,
  createNewClientAction,
  emptyNewClientDraft,
  parseNewClientChartAccountsAction,
  selectNewClientTaxCertificateAction,
  setPasswordForSelectedClientAction,
  uploadChartAccountsAction,
} from "./features/clients";
import {
  addLocalUploadsAction,
  useDocumentWorkflow,
} from "./features/documents";
import { useExportCommands } from "./features/export";
import {
  buildClientCancellationViewModel,
  buildPortalDashboard,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  statusFunnel,
} from "./portal-dashboard";
import {
  normalizeSessionForPortalConfig,
  PORTAL_NAV_ITEMS,
  portalConfigForRouteKey,
} from "./portal-routes";
import type {
  CancellationRequest,
  CorrectionDraft,
  ExportMode,
  IntakeCategory,
  LocalSession,
  NewClientDraft,
  PilotClient,
  PilotData,
  PilotMode,
  PilotReadinessView,
  PilotStatus,
  PortalNavItem,
  PortalRouteKey,
} from "./portal-types";
import { emptyPilotData } from "./portal-data-mappers";
import { periodLabel } from "./portal-formatters";
import { previousCompletedPeriod } from "./portal-periods";
import { journalDraftLinesForDocument, useReviewCommands } from "./features/review";

export function FisoraPortalApp({ routeKey = "home" }: { routeKey?: PortalRouteKey | string }) {
  return (
    <PilotQueryProvider>
      <FisoraPortalContent routeKey={routeKey} />
    </PilotQueryProvider>
  );
}

function FisoraPortalContent({ routeKey = "home" }: { routeKey?: PortalRouteKey | string }) {
  const portalConfig = portalConfigForRouteKey(routeKey);
  const lockedRole = portalConfig.lockedRole as LocalSession["role"] | undefined;
  const visibleNavItems = (PORTAL_NAV_ITEMS as PortalNavItem[]).filter((item) =>
    portalConfig.visibleModes.includes(item.mode),
  );
  const [data, setData] = useState<PilotData>(emptyPilotData);
  const [source, setSource] = useState("Çalışma alanı yükleniyor");
  const [readinessPayload, setReadinessPayload] = useState<Record<string, unknown> | null>(null);
  const [localFallbackAllowed, setLocalFallbackAllowed] = useState(false);
  const [mode, setModeState] = useState<PilotMode>(portalConfig.initialMode as PilotMode);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [selectedIntakeCategory, setSelectedIntakeCategory] = useState<IntakeCategory>("purchase_invoice");
  const [clientSearch, setClientSearch] = useState("");
  const [session, setSession] = useState<LocalSession | null>(null);
  const [sessionHydrated, setSessionHydrated] = useState(false);
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
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>({
    accountCode: "",
    counterpartyCode: "",
    manualDraftLines: [],
    reason: "",
  });
  const [newClientDraft, setNewClientDraft] = useState<NewClientDraft>(() => emptyNewClientDraft());
  const [newClientTaxCertificateFile, setNewClientTaxCertificateFile] = useState<File | null>(null);
  const [newClientTaxCertificateInputKey, setNewClientTaxCertificateInputKey] = useState(0);
  const [newClientStatus, setNewClientStatus] = useState("");
  const [chartUploadStatus, setChartUploadStatus] = useState("");
  const [inviteStatus, setInviteStatus] = useState("");
  const [portalPassword, setPortalPasswordDraft] = useState("");
  const [portalPasswordStatus, setPortalPasswordStatus] = useState("");
  const readinessQuery = usePilotReadinessQuery();

  function applyPilotData(payload: PilotData, nextSource: string) {
    setData(payload);
    setSource(nextSource);
    setSelectedClientId((current) =>
      current && payload.clients.some((client) => client.clientId === current)
        ? current
        : payload.clients[0]?.clientId ?? "",
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
    setSession(normalizeSessionForPortalConfig(readStoredSession(), portalConfig));
    setSessionHydrated(true);
  }, [routeKey]);

  useEffect(() => {
    if (!sessionHydrated) return;
    let cancelled = false;
    void loadInitialPilotData({
      applyPilotData,
      defaultUserId: portalConfig.defaultUserId,
      explicitAllowLocalFallback: process.env.NEXT_PUBLIC_FISORA_ALLOW_LOCAL_FALLBACK === "true",
      session,
      setLocalFallbackAllowed,
      setReadinessPayload,
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
  const clientSelectedDocument = periodDocuments.find((document) => document.id === selectedDocumentId);
  const filteredClients = useMemo(() => {
    const query = clientSearch.trim().toLocaleLowerCase("tr-TR");
    if (!query) return clients;
    return clients.filter((client) => `${client.clientName} ${client.clientId} ${client.taxId}`.toLocaleLowerCase("tr-TR").includes(query));
  }, [clientSearch, clients]);
  const openCancellationRequests = data.cancellationRequests.filter((request) => request.status === "open");
  const dashboardMetrics = useMemo(() => buildPortalDashboard(data), [data]);
  const dashboardClientRows = useMemo(() => clientDashboardRows(data), [data]);
  const intakeDistribution = useMemo(() => documentIntakeDistribution(data.documents), [data.documents]);
  const funnelRows = useMemo(() => statusFunnel(data.documents), [data.documents]);
  const uploadTrackingRows = useMemo(() => clientUploadTracking(data), [data]);
  const readinessView = useMemo(
    () => buildPilotReadinessView(readinessPayload) as PilotReadinessView,
    [readinessPayload],
  );
  const visibleDashboardClientRows = useMemo(() => {
    const visibleIds = new Set(filteredClients.map((client) => client.clientId));
    return dashboardClientRows.filter((row: { clientId: string }) => visibleIds.has(row.clientId));
  }, [dashboardClientRows, filteredClients]);

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

  const createNewClient = () => {
    void createNewClientAction({
      loginUserId,
      newClientDraft,
      newClientTaxCertificateFile,
      portalPassword,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      session,
      setNewClientDraft,
      setNewClientStatus,
      setNewClientTaxCertificateFile,
      setNewClientTaxCertificateInputKey,
      setPortalPasswordDraft,
      setSelectedClientId,
    });
  };

  const selectNewClientTaxCertificate = (file: File | null) => {
    void selectNewClientTaxCertificateAction({
      file,
      loginUserId,
      session,
      setNewClientDraft,
      setNewClientStatus,
      setNewClientTaxCertificateFile,
    });
  };

  const uploadChartAccounts = (files: FileList | null) => {
    void uploadChartAccountsAction({
      files,
      loginUserId,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      selectedClient,
      session,
      setChartUploadStatus,
    });
  };

  const parseNewClientChartAccounts = (files: FileList | null) => {
    void parseNewClientChartAccountsAction({
      files,
      loginUserId,
      session,
      setNewClientDraft,
      setNewClientStatus,
    });
  };

  const createInviteForSelectedClient = () => {
    void createInviteForSelectedClientAction({
      loginUserId,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      selectedClient,
      session,
      setInviteStatus,
    });
  };

  const setPasswordForSelectedClient = () => {
    void setPasswordForSelectedClientAction({
      loginUserId,
      portalPassword,
      selectedClient,
      session,
      setPortalPasswordDraft,
      setPortalPasswordStatus,
    });
  };

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
    cancelReason,
    clientDocuments,
    exportMode,
    selectedClient,
    selectedPeriod,
    setCancelReason,
    setClientCancellationDocumentId,
    setData,
    setExportStatus,
    setSelectedDocumentId,
  });
  const {
    approveSelectedAndMoveNext,
    requestStatementAiForSelectedDocument,
    saveDecision,
    saveStatementLineDecision,
  } = useReviewCommands({
    activeReviewDocuments,
    correctionDraft,
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
  const activeNavItem = (PORTAL_NAV_ITEMS as PortalNavItem[]).find((item) => item.mode === mode);

  return (
    <main className="private-shell portal-shell">
      <header className="private-topbar">
        <div>
          <p className="eyebrow">Fisero</p>
          <h1>{mode === "client" ? "Mükellef portalı" : activeNavItem?.label || "Müşavir çalışma alanı"}</h1>
        </div>
        <PortalTopbarStatus
          clientName={mode === "client" ? selectedClient?.clientName : undefined}
          localFallbackAllowed={localFallbackAllowed}
          onExit={exitPortal}
          session={session}
          source={source}
        />
      </header>

      {visibleNavItems.length > 1 ? (
        <nav className="portal-nav" aria-label="Portal ekranları">
          {visibleNavItems.map((item: { mode: PilotMode; label: string; href: string }) => (
            <ModeButton active={mode === item.mode} href={item.href} key={item.mode} label={item.label} />
          ))}
        </nav>
      ) : null}

      {mode === "accountant" || mode === "client" ? null : (
        <SelectedClientStrip client={selectedClient} documents={clientDocuments} openCancellationCount={openCancellationRequests.length} />
      )}

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

      {mode === "accountant" ? (
        <AccountantDashboard
          clientRows={visibleDashboardClientRows}
          dashboardMetrics={dashboardMetrics}
          funnelRows={funnelRows}
          intakeDistribution={intakeDistribution}
          onClientSelect={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
          selectedClientId={selectedClient?.clientId ?? ""}
          uploadTrackingRows={uploadTrackingRows}
        />
      ) : null}

      {mode === "documents" ? (
        <DocumentProcessingWorkspace
          selectedDocumentSegment={selectedDocumentSegment}
          setSelectedDocumentSegment={(segment) => {
            setSelectedDocumentSegment(segment);
            setSelectedDocumentId("");
          }}
        >
        <AccountantWorkspace
          cancellationRequests={openCancellationRequests.filter((request) => request.clientId === selectedClient?.clientId)}
          statementAiStatus={statementAiStatus}
          clientSearch={clientSearch}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          correctionDraft={correctionDraft}
          dashboardMetrics={dashboardMetrics}
          decisionStatus={decisionStatus}
          documents={activeReviewDocuments}
          allClientDocuments={segmentedClientDocuments}
          newClientDraft={newClientDraft}
          newClientStatus={newClientStatus}
          newClientTaxCertificateFile={newClientTaxCertificateFile}
          newClientTaxCertificateInputKey={newClientTaxCertificateInputKey}
          onAddToBasket={addSelectedClientToBasket}
          onApproveAndNext={approveSelectedAndMoveNext}
          onCreateNewClient={createNewClient}
          onClientSearchChange={setClientSearch}
          onTaxCertificateFileChange={selectNewClientTaxCertificate}
          onRequestStatementAi={requestStatementAiForSelectedDocument}
          onResolveCancellation={resolveCancellation}
          onSaveDecision={saveDecision}
          onSaveStatementDecision={saveStatementLineDecision}
          reviewFilter={reviewFilter}
          selectedClient={selectedClient}
          selectedDocument={selectedDocument}
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
          setSelectedStatementLineNo={setSelectedStatementLineNo}
        />
        </DocumentProcessingWorkspace>
      ) : null}

      {mode === "clients" ? (
        <ClientManagementView
          cancellationRequests={openCancellationRequests}
          chartUploadStatus={chartUploadStatus}
          clientRows={visibleDashboardClientRows}
          clients={filteredClients}
          clientSearch={clientSearch}
          inviteStatus={inviteStatus}
          newClientDraft={newClientDraft}
          newClientStatus={newClientStatus}
          newClientTaxCertificateFile={newClientTaxCertificateFile}
          newClientTaxCertificateInputKey={newClientTaxCertificateInputKey}
          onChartFileSelected={parseNewClientChartAccounts}
          onClientSearchChange={setClientSearch}
          onCreateInvite={createInviteForSelectedClient}
          onCreateNewClient={createNewClient}
          onResolveCancellation={resolveCancellation}
          onSetPassword={setPasswordForSelectedClient}
          onTaxCertificateFileChange={selectNewClientTaxCertificate}
          portalPassword={portalPassword}
          portalPasswordStatus={portalPasswordStatus}
          selectedClient={selectedClient}
          setNewClientDraft={setNewClientDraft}
          setPortalPassword={setPortalPasswordDraft}
          setSelectedClientId={(clientId) => {
            setSelectedClientId(clientId);
            setSelectedDocumentId("");
          }}
        />
      ) : null}

      {mode === "settings" ? (
        <SettingsView
          dashboardMetrics={dashboardMetrics}
          loginPassword={loginPassword}
          loginRole={loginRole}
          loginStatus={loginStatus}
          loginUserId={loginUserId}
          lockedRole={lockedRole}
          onLogin={login}
          onLogout={logout}
          localFallbackAllowed={localFallbackAllowed}
          readinessView={readinessView}
          session={session}
          setLoginPassword={setLoginPassword}
          setLoginRole={setLoginRole}
          setLoginUserId={setLoginUserId}
          source={source}
          {...testDataReset}
        />
      ) : null}

      {mode === "exports" ? (
        <ExportBasketRouteView
          exportBasket={data.exportBasket}
          exportMode={exportMode}
          exportStatus={exportStatus}
          onMarkPackaged={markBasketPackaged}
          periodLabel={periodLabel}
          setExportMode={setExportMode}
        />
      ) : null}

      {mode === "operations" ? (
        <OperationsRouteView
          data={data}
          localFallbackAllowed={localFallbackAllowed}
          readinessView={readinessView}
          source={source}
        />
      ) : null}
    </main>
  );
}

export default function Home() {
  return <FisoraPortalApp routeKey="home" />;
}
