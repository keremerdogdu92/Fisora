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
import { ModeButton, PortalTopbarStatus, SelectedClientStrip } from "./portal-shell-components";
import { AccountantWorkspace } from "./portal-workspace-view";
import {
  loginWithPassword,
  resolveApiBaseUrl,
} from "./upload-api";
import { buildPilotReadinessView, loadInitialPilotData, refreshBackendPilotData as refreshBackendPilotDataAction } from "./portal-workspace-actions";
import {
  createInviteForSelectedClientAction,
  createNewClientAction,
  emptyNewClientDraft,
  selectNewClientTaxCertificateAction,
  setPasswordForSelectedClientAction,
  uploadChartAccountsAction,
} from "./portal-client-actions";
import {
  addLocalUploadsAction,
  requestStatementAiForSelectedDocumentAction,
  saveDecisionAction,
  saveStatementLineDecisionAction,
} from "./portal-document-actions";
import {
  addSelectedClientToBasketAction,
  markBasketPackagedAction,
  requestCancellationAction,
  resolveCancellationAction,
} from "./portal-export-actions";
import {
  buildClientCancellationViewModel,
  buildPortalDashboard,
  clientDashboardRows,
  clientUploadTracking,
  documentIntakeDistribution,
  documentsForProcessing,
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
  DocumentSegment,
  ExportMode,
  IntakeCategory,
  LocalSession,
  NewClientDraft,
  PilotClient,
  PilotData,
  PilotDocument,
  PilotMode,
  PilotReadinessView,
  PilotStatus,
  PortalNavItem,
  PortalRouteKey,
  ReviewFilter,
} from "./portal-types";
import { emptyPilotData } from "./portal-data-mappers";
import {
  isCancelStatus,
  periodLabel,
} from "./portal-formatters";
import { journalDraftLinesForDocument } from "./portal-review-actions";
import { persistSession, readStoredSession } from "./portal-session";

export function FisoraPortalApp({ routeKey = "home" }: { routeKey?: PortalRouteKey | string }) {
  const portalConfig = portalConfigForRouteKey(routeKey);
  const lockedRole = portalConfig.lockedRole as LocalSession["role"] | undefined;
  const visibleNavItems = (PORTAL_NAV_ITEMS as PortalNavItem[]).filter((item) =>
    portalConfig.visibleModes.includes(item.mode),
  );
  const [data, setData] = useState<PilotData>(emptyPilotData);
  const [source, setSource] = useState("Ã‡alÄ±ÅŸma alanÄ± yÃ¼kleniyor");
  const [readinessPayload, setReadinessPayload] = useState<Record<string, unknown> | null>(null);
  const [localFallbackAllowed, setLocalFallbackAllowed] = useState(false);
  const [mode, setModeState] = useState<PilotMode>(portalConfig.initialMode as PilotMode);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [selectedIntakeCategory, setSelectedIntakeCategory] = useState<IntakeCategory>("purchase_invoice");
  const [selectedDocumentSegment, setSelectedDocumentSegment] = useState<DocumentSegment>("invoices");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("review_required");
  const [clientSearch, setClientSearch] = useState("");
  const [session, setSession] = useState<LocalSession | null>(() =>
    normalizeSessionForPortalConfig(readStoredSession(), portalConfig),
  );
  const [loginUserId, setLoginUserId] = useState(portalConfig.defaultUserId);
  const [loginPassword, setLoginPassword] = useState("");
  const [loginRole, setLoginRole] = useState<"client_user" | "accountant">(portalConfig.defaultRole as "client_user" | "accountant");
  const [loginStatus, setLoginStatus] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [clientCancellationDocumentId, setClientCancellationDocumentId] = useState("");
  const [decisionStatus, setDecisionStatus] = useState("");
  const [statementAiStatus, setStatementAiStatus] = useState("");
  const [selectedStatementLineNo, setSelectedStatementLineNo] = useState(0);
  const [uploadStatus, setUploadStatus] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [exportMode, setExportMode] = useState<ExportMode>("bulk");
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>({
    accountCode: "",
    counterpartyCode: "",
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

  function applyPilotData(payload: PilotData, nextSource: string) {
    setData(payload);
    setSource(nextSource);
    setSelectedClientId((current) =>
      current && payload.clients.some((client) => client.clientId === current)
        ? current
        : payload.clients[0]?.clientId ?? "",
    );
    setSelectedPeriod(Array.from(new Set(payload.documents.map((document) => document.period))).sort().at(-1) ?? "");
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
  }, [routeKey, session?.sessionToken, session?.userId]);

  const clients = data.clients;
  const selectedClient = clients.find((client) => client.clientId === selectedClientId) ?? clients[0];
  const allPeriods = useMemo(() => {
    return Array.from(new Set(data.documents.map((document) => document.period))).sort().reverse();
  }, [data.documents]);
  const clientDocuments = useMemo(() => {
    return data.documents.filter((document) => document.clientId === selectedClient?.clientId);
  }, [data.documents, selectedClient?.clientId]);
  const periodDocuments = useMemo(() => {
    return clientDocuments.filter((document) => !selectedPeriod || document.period === selectedPeriod);
  }, [clientDocuments, selectedPeriod]);
  const visibleReviewDocuments = useMemo(() => {
    if (reviewFilter === "all") return clientDocuments;
    if (reviewFilter === "cancel_requested") return clientDocuments.filter((document) => isCancelStatus(document.status));
    return clientDocuments.filter((document) => document.status === reviewFilter);
  }, [clientDocuments, reviewFilter]);
  const segmentedClientDocuments = useMemo(() => {
    return documentsForProcessing({
      documents: data.documents,
      clientId: selectedClient?.clientId,
      segment: selectedDocumentSegment,
    }) as PilotDocument[];
  }, [data.documents, selectedClient?.clientId, selectedDocumentSegment]);
  const visibleProcessingDocuments = useMemo(() => {
    if (reviewFilter === "all") return segmentedClientDocuments;
    if (reviewFilter === "cancel_requested") return segmentedClientDocuments.filter((document) => isCancelStatus(document.status));
    return segmentedClientDocuments.filter((document) => document.status === reviewFilter);
  }, [reviewFilter, segmentedClientDocuments]);
  const activeReviewDocuments = mode === "documents" ? visibleProcessingDocuments : visibleReviewDocuments;
  const selectedDocumentSource = mode === "documents" ? segmentedClientDocuments : activeReviewDocuments;
  const selectedDocument = selectedDocumentSource.find((document) => document.id === selectedDocumentId);
  const clientSelectedDocument = periodDocuments.find((document) => document.id === selectedDocumentId);
  const selectedStatementLineKey = selectedDocument?.statementLines.map((line) => line.line_no).join("|") ?? "";
  useEffect(() => {
    const firstLineNo = selectedDocument?.statementLines[0]?.line_no ?? 0;
    if (!firstLineNo) {
      setSelectedStatementLineNo(0);
      return;
    }
    const hasSelectedLine = selectedDocument?.statementLines.some((line) => line.line_no === selectedStatementLineNo);
    if (!hasSelectedLine) setSelectedStatementLineNo(firstLineNo);
  }, [selectedDocument?.id, selectedStatementLineKey, selectedStatementLineNo]);
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
      setLoginStatus("Oturum aÃ§Ä±lÄ±yor.");
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
        setLoginStatus(`${nextSession.userId} iÃ§in oturum aÃ§Ä±ldÄ±.`);
        setMode(nextSession.role === "client_user" ? "client" : (portalConfig.initialMode as PilotMode));
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setLoginStatus(`Oturum aÃ§Ä±lamadÄ±. ${message}`);
        return;
      }
    }
    if (!localFallbackAllowed) {
      setLoginStatus("Bu ortamda ÅŸifresiz ofis oturumu kapalÄ±. KullanÄ±cÄ± ÅŸifresiyle girin.");
      return;
    }
    const nextSession: LocalSession = { userId, role: effectiveRole };
    persistSession(nextSession);
    setSession(nextSession);
    setLoginStatus(`${nextSession.userId} iÃ§in lokal ofis oturumu aÃ§Ä±ldÄ±.`);
    setMode(nextSession.role === "client_user" ? "client" : (portalConfig.initialMode as PilotMode));
  }

  function logout() {
    persistSession(null);
    setSession(null);
    setLoginStatus("Oturum kapatÄ±ldÄ±.");
  }

  function exitPortal() {
    logout();
    if (typeof window !== "undefined") window.location.assign("/");
  }

  function selectAdjacentReviewDocument(direction: 1 | -1 = 1) {
    if (!activeReviewDocuments.length || !selectedDocument) return;
    const currentIndex = activeReviewDocuments.findIndex((document) => document.id === selectedDocument.id);
    const nextDocument =
      activeReviewDocuments[currentIndex + direction] ??
      activeReviewDocuments[currentIndex - direction] ??
      activeReviewDocuments[0];
    if (nextDocument) setSelectedDocumentId(nextDocument.id);
  }

  async function approveSelectedAndMoveNext() {
    if (!selectedDocument) return;
    const selectedLineIndex = selectedDocument.statementLines.findIndex((line) => line.line_no === selectedStatementLineNo);
    if (selectedDocument.statementLines.length && selectedLineIndex >= 0) {
      await saveStatementLineDecision("approve");
      const nextLine = selectedDocument.statementLines[selectedLineIndex + 1];
      if (nextLine) {
        setSelectedStatementLineNo(nextLine.line_no);
        return;
      }
      selectAdjacentReviewDocument(1);
      return;
    }
    await saveDecision("approve");
    selectAdjacentReviewDocument(1);
  }

  const createNewClient = () => {
    void createNewClientAction({
      loginUserId,
      newClientDraft,
      newClientTaxCertificateFile,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      session,
      setNewClientDraft,
      setNewClientStatus,
      setNewClientTaxCertificateFile,
      setNewClientTaxCertificateInputKey,
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

  const requestCancellation = (document: PilotDocument) => {
    requestCancellationAction({
      cancelReason,
      document,
      selectedClient,
      setCancelReason,
      setClientCancellationDocumentId,
      setData,
      setSelectedDocumentId,
    });
  };

  const resolveCancellation = (requestId: string, status: "approved" | "rejected") => {
    resolveCancellationAction({ requestId, setData, status });
  };

  const addSelectedClientToBasket = () => {
    addSelectedClientToBasketAction({
      clientDocuments,
      selectedClient,
      selectedPeriod,
      setData,
      setExportStatus,
    });
  };

  const markBasketPackaged = () => {
    markBasketPackagedAction({ exportMode, setData, setExportStatus });
  };

  const requestStatementAiForSelectedDocument = () => {
    void requestStatementAiForSelectedDocumentAction({
      selectedDocument,
      session,
      setData,
      setStatementAiStatus,
    });
  };

  const saveStatementLineDecision = (action: string) => {
    return saveStatementLineDecisionAction({
      action,
      correctionDraft,
      localFallbackAllowed,
      loginUserId,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      selectedDocument,
      selectedStatementLineNo,
      session,
      setData,
      setDecisionStatus,
    });
  };

  const saveDecision = (action: string) => {
    return saveDecisionAction({
      action,
      correctionDraft,
      localFallbackAllowed,
      loginUserId,
      refreshBackendPilotData: () => refreshBackendPilotData(),
      selectedDocument,
      session,
      setData,
      setDecisionStatus,
    });
  };
  const activeNavItem = (PORTAL_NAV_ITEMS as PortalNavItem[]).find((item) => item.mode === mode);

  return (
    <main className="private-shell portal-shell">
      <header className="private-topbar">
        <div>
          <p className="eyebrow">Fisero</p>
          <h1>{mode === "client" ? "MÃ¼kellef portalÄ±" : activeNavItem?.label || "MÃ¼ÅŸavir Ã§alÄ±ÅŸma alanÄ±"}</h1>
        </div>
        <PortalTopbarStatus
          localFallbackAllowed={localFallbackAllowed}
          onExit={exitPortal}
          session={session}
          source={source}
        />
      </header>

      {visibleNavItems.length > 1 ? (
        <nav className="portal-nav" aria-label="Portal ekranlarÄ±">
          {visibleNavItems.map((item: { mode: PilotMode; label: string; href: string }) => (
            <ModeButton active={mode === item.mode} href={item.href} key={item.mode} label={item.label} />
          ))}
        </nav>
      ) : null}

      {mode === "accountant" ? null : (
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
          periods={allPeriods}
          selectedClient={selectedClient}
          selectedDocument={clientSelectedDocument}
          selectedIntakeCategory={selectedIntakeCategory}
          selectedPeriod={selectedPeriod}
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
          onChartFileSelected={uploadChartAccounts}
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
