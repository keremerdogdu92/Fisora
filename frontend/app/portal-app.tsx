"use client";

import { useEffect, useMemo, useState } from "react";
import { fallbackReviewData } from "./demo-data";
import { AccountantDashboard } from "./portal-dashboard-view";
import { ClientPortal } from "./portal-client-view";
import { ClientManagementView } from "./portal-clients-view";
import { DocumentProcessingWorkspace } from "./portal-documents-view";
import {
  ExportBasketView as ExportBasketRouteView,
  OperationsView as OperationsRouteView,
} from "./portal-exports-view";
import { SettingsView } from "./portal-settings-view";
import { Info } from "./portal-shared";
import { AccountantWorkspace } from "./portal-workspace-view";
import {
  INTAKE_TABS,
  buildUploadIntakeMetadata,
} from "./upload-intake";
import {
  ensureUploadWorkspace,
  buildClientOnboardingPackagePayload,
  createClientOnboardingPackage,
  createPortalInvite,
  loginWithPassword,
  parseTaxCertificateFromBackend,
  pickUploadUser,
  requestStatementAiSuggestions,
  resolveApiBaseUrl,
  setPortalPassword as setBackendPortalPassword,
  storeReviewDecision,
  uploadChartAccountsToBackend,
  uploadDocumentToBackend,
  uploadTaxCertificateToBackend,
} from "./upload-api";
import { buildPilotReadinessView, canUseLocalPilotFallback } from "./pilot-readiness";
import { fetchBackendPilotData, fetchBackendReadiness } from "./workspace-api";
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
  ChartRow,
  CorrectionDraft,
  DashboardClientRow,
  DocumentSegment,
  ExportBasketItem,
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
  RulePromptView,
  StatementAiSuggestionView,
  StatementEntryReview,
} from "./portal-types";
import {
  agentSourceLabel,
  normalizeRulePrompt,
  normalizeStatementAiSuggestions,
  normalizeStatus,
  safeNumber,
  safeRecord,
} from "./portal-normalization";
import { emptyPilotData, normalizePilotData } from "./portal-data-mappers";
import {
  isCancelStatus,
  isInProgress,
  periodLabel,
  reviewActionLabel,
  statementDirectionLabel,
  statementReviewStatus,
  statementStatusLabel,
  statementTypeLabels,
} from "./portal-formatters";
import { applyStatementLineDecision, journalDraftLinesForDocument } from "./portal-review-actions";
import { persistSession, readStoredSession, roleLabels } from "./portal-session";

async function fetchJson(path: string) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} not found`);
  return response.json();
}

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
  const [newClientDraft, setNewClientDraft] = useState<NewClientDraft>({
    clientId: "",
    title: "",
    taxId: "",
    activityDescription: "",
    naceCode: "",
    activityTags: [],
    activityProfile: {},
    workplaceAddresses: [],
    portalUserId: "",
    portalDisplayName: "",
  });
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
    try {
      const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
      const backendPayload = await fetchBackendPilotData({
        apiBaseUrl,
        sessionToken: session?.sessionToken,
        userId: session?.userId || portalConfig.defaultUserId,
      });
      const payload = normalizePilotData(backendPayload as PilotData);
      if (!payload.clients.length) return false;
      if (shouldCancel()) return true;
      applyPilotData(payload, payload.generatedFrom || "Ã‡alÄ±ÅŸma alanÄ±");
      return true;
    } catch {
      return false;
    }
  }

  async function refreshBackendReadiness(shouldCancel: () => boolean = () => false) {
    try {
      const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
      const payload = await fetchBackendReadiness({ apiBaseUrl });
      if (shouldCancel()) return true;
      setReadinessPayload(payload as Record<string, unknown>);
      return true;
    } catch {
      if (!shouldCancel()) setReadinessPayload(null);
      return false;
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadPilotData() {
      const pageUrl = typeof window === "undefined" ? "" : window.location.href;
      const allowLocalFallback = canUseLocalPilotFallback({
        pageUrl,
        explicitAllow: process.env.NEXT_PUBLIC_FISORA_ALLOW_LOCAL_FALLBACK === "true",
      });
      if (!cancelled) setLocalFallbackAllowed(allowLocalFallback);
      await refreshBackendReadiness(() => cancelled);
      if (await refreshBackendPilotData(() => cancelled)) return;
      if (!allowLocalFallback) {
        if (!cancelled) {
          applyPilotData(emptyPilotData, "Ã‡alÄ±ÅŸma alanÄ±na eriÅŸilemedi");
        }
        return;
      }
      const paths = ["/local-pilot-data.json", "/local-workspace-data.json", "/local-review-data.json"];
      for (const path of paths) {
        try {
          const payload = normalizePilotData(await fetchJson(path));
          if (cancelled) return;
          applyPilotData(payload, "Yerel Ã§alÄ±ÅŸma verisi");
          return;
        } catch {
          // Try the next private/local source.
        }
      }
      const fallback = normalizePilotData(fallbackReviewData);
      if (cancelled) return;
      applyPilotData(fallback, "Yerel Ã§alÄ±ÅŸma verisi");
    }
    void loadPilotData();
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

  async function createNewClient() {
    if (!newClientDraft.title.trim()) {
      setNewClientStatus("MÃ¼kellef adÄ± gerekli.");
      return;
    }
    const payload = buildClientOnboardingPackagePayload(newClientDraft);
    const taxCertificateFile = newClientTaxCertificateFile;
    const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
    const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
    setNewClientStatus(taxCertificateFile ? "MÃ¼kellef kaydediliyor, vergi levhasÄ± yÃ¼klenecek." : "MÃ¼kellef kaydediliyor.");
    try {
      await createClientOnboardingPackage({
        apiBaseUrl,
        client: newClientDraft,
        sessionToken: session?.sessionToken,
        userId: actingUserId,
      });
      setSelectedClientId(payload.client.client_id);
      let certificateStatus = "";
      if (taxCertificateFile) {
        setNewClientStatus("MÃ¼kellef kaydedildi. Vergi levhasÄ± yÃ¼kleniyor.");
        try {
          await uploadTaxCertificateToBackend({
            apiBaseUrl,
            clientId: payload.client.client_id,
            userId: actingUserId,
            uploadedBy: actingUserId,
            sessionToken: session?.sessionToken,
            file: taxCertificateFile,
          });
          certificateStatus = " Vergi levhasÄ± yÃ¼klendi.";
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          certificateStatus = ` Vergi levhasÄ± yÃ¼klenemedi: ${message}`;
        }
      }
      setNewClientDraft({
        clientId: "",
        title: "",
        taxId: "",
        activityDescription: "",
        naceCode: "",
        activityTags: [],
        activityProfile: {},
        workplaceAddresses: [],
        portalUserId: "",
        portalDisplayName: "",
      });
      setNewClientTaxCertificateFile(null);
      setNewClientTaxCertificateInputKey((current) => current + 1);
      setNewClientStatus(`${payload.client.title} eklendi.${certificateStatus}`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNewClientStatus(`MÃ¼kellef kaydedilemedi. ${message}`);
    }
  }

  async function selectNewClientTaxCertificate(file: File | null) {
    setNewClientTaxCertificateFile(file);
    if (!file) return;
    const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
    const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
    setNewClientStatus(`${file.name} vergi levhasÄ± okunuyor.`);
    try {
      const extraction = await parseTaxCertificateFromBackend({
        apiBaseUrl,
        userId: actingUserId,
        sessionToken: session?.sessionToken,
        file,
      });
      const title = String(extraction?.title || "").trim();
      const taxId = String(extraction?.tax_id || "").trim();
      const activityDescription = String(extraction?.activity_description || "").trim();
      const naceCode = String(extraction?.nace_code || "").trim();
      const activityTags = Array.isArray(extraction?.activity_tags)
        ? (extraction.activity_tags as unknown[]).map((value) => String(value).trim()).filter(Boolean)
        : [];
      const activityProfile =
        extraction?.activity_profile && typeof extraction.activity_profile === "object"
          ? (extraction.activity_profile as Record<string, unknown>)
          : {};
      const workplaceAddresses = Array.isArray(extraction?.workplace_addresses)
        ? (extraction.workplace_addresses as unknown[]).map((value) => String(value).trim()).filter(Boolean)
        : [];
      setNewClientDraft((current) => ({
        ...current,
        title: current.title.trim() || title,
        taxId: current.taxId.trim() || taxId,
        activityDescription: current.activityDescription.trim() || activityDescription,
        naceCode: current.naceCode.trim() || naceCode,
        activityTags: current.activityTags.length ? current.activityTags : activityTags,
        activityProfile: Object.keys(current.activityProfile).length ? current.activityProfile : activityProfile,
        workplaceAddresses: current.workplaceAddresses.length ? current.workplaceAddresses : workplaceAddresses,
      }));
      const filledFields = [
        title ? "unvan" : "",
        taxId ? "VKN" : "",
        activityDescription || naceCode ? "faaliyet" : "",
        activityTags.length ? "faaliyet tag" : "",
        workplaceAddresses.length ? "adres" : "",
      ].filter(Boolean);
      const confidence = Number(extraction?.confidence || 0);
      const profileLabel = String(activityProfile.display_label || "").trim();
      const profileConfidence = Number(activityProfile.confidence || 0);
      const profileSummary = profileLabel ? `Profil: ${profileLabel}${profileConfidence ? ` ${profileConfidence}` : ""}` : "";
      const note = filledFields.length
        ? `Vergi levhasÄ± okundu: ${filledFields.join(", ")}${confidence ? ` / gÃ¼ven ${confidence}` : ""}.`
        : "Vergi levhasÄ±ndan alan okunamadÄ±; elle kayÄ±t yapabilirsiniz.";
      setNewClientStatus(profileSummary ? `${note} ${profileSummary}` : note);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setNewClientStatus(`Vergi levhasÄ± okunamadÄ±. Elle devam edebilirsiniz. ${message}`);
    }
  }

  async function uploadChartAccounts(files: FileList | null) {
    const file = files?.[0];
    if (!file || !selectedClient) return;
    setChartUploadStatus(`${file.name} hesap plani import ediliyor...`);
    try {
      const result = await uploadChartAccountsToBackend({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedClient.clientId,
        userId: session?.userId || loginUserId.trim() || "mali-musavir",
        sessionToken: session?.sessionToken,
        file,
      });
      setChartUploadStatus(`${selectedClient.clientName}: ${result.account_count ?? 0} hesap backend store'a yazildi.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setChartUploadStatus(`Hesap plani importu tamamlanamadi. ${message}`);
    }
  }

  async function createInviteForSelectedClient() {
    if (!selectedClient) return;
    const userId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
    setInviteStatus(`${userId} icin davet tokeni hazirlaniyor...`);
    try {
      const result = await createPortalInvite({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        userId,
        displayName: selectedClient.userLabel || selectedClient.clientName,
        clientId: selectedClient.clientId,
        invitedBy: session?.userId || loginUserId.trim() || "mali-musavir",
        sessionToken: session?.sessionToken,
        userHeader: session?.userId || loginUserId.trim(),
      });
      setInviteStatus(`Davet tokeni: ${String(result.invite_token || "")}`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setInviteStatus(`Davet tokeni olusturulamadi. ${message}`);
    }
  }

  async function setPasswordForSelectedClient() {
    if (!selectedClient) return;
    const userId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
    setPortalPasswordStatus(`${userId} icin sifre kuruluyor...`);
    try {
      const result = await setBackendPortalPassword({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        userId,
        password: portalPassword,
        sessionToken: session?.sessionToken,
        userHeader: session?.userId || loginUserId.trim(),
      });
      setPortalPasswordStatus(result.has_password ? `${userId} icin sifre hazir.` : `${userId} icin sifre sonucu alindi.`);
      setPortalPasswordDraft("");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPortalPasswordStatus(`Sifre kurulumu tamamlanamadi. ${message}`);
    }
  }

  async function addLocalUploads(files: FileList | null) {
    const selectedFiles = Array.from(files ?? []);
    if (!selectedFiles.length || !selectedClient) return;
    const now = new Date();
    const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const intakeMetadata = buildUploadIntakeMetadata(selectedIntakeCategory);
    const nextDocuments = selectedFiles.map((file, index): PilotDocument => ({
      id: `local-upload-${now.getTime()}-${index}`,
      clientId: selectedClient.clientId,
      clientName: selectedClient.clientName,
      fileName: file.name,
      documentType: intakeMetadata.documentType,
      intakeCategory: intakeMetadata.intakeCategory as IntakeCategory,
      period,
      uploadedAt: now.toLocaleString("tr-TR"),
      uploadedBy: selectedClient.userLabel,
      status: normalizeStatus(intakeMetadata.status),
      provider: intakeMetadata.provider,
      issueDate: "-",
      amount: "-",
      vatRates: [],
      productLine: intakeMetadata.productLine,
      productCategory: intakeMetadata.productCategory,
      businessRelation: "-",
      accountTreatment: "-",
      requiresAccountantReview: true,
      previewText: intakeMetadata.previewText,
      aiReason: intakeMetadata.aiReason,
      aiProvider: "-",
      aiSuggestedAccountCode: "",
      aiSuggestedCounterpartyCode: "",
      aiRiskFlags: [],
      aiAccountReason: "",
      deterministicSummary: intakeMetadata.deterministicSummary,
      exportGateReason: intakeMetadata.exportGateReason,
      selectedExpenseAccount: "-",
      selectedVatAccount: "-",
      selectedCounterpartyAccount: "-",
      counterpartyConfidence: 0,
      reviewReasons: intakeMetadata.intakeCategory === "special_document" ? ["manual_review_required"] : [],
      riskFlags: intakeMetadata.intakeCategory === "special_document" ? ["manual_review_required"] : [],
      draftLines: [],
      statementLines: [],
      statementEntries: [],
      statementAiSuggestions: [],
      statementAiSummary: "",
      accountingIntent: "",
      accountingIntentConfidence: 0,
      learningRuleScope: "",
      learningRuleReason: "",
      learningRuleSourceSummary: "",
      rulePrompt: normalizeRulePrompt({}),
    }));
    if (localFallbackAllowed) {
      setData((current) => ({ ...current, documents: [...nextDocuments, ...current.documents] }));
      setSelectedPeriod(period);
    }
    setUploadStatus(`${selectedFiles.length} belge backend kuyruÄŸuna gÃ¶nderiliyor.`);

    const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
    const uploadUserId = pickUploadUser({ session, selectedClient });
    const uploadDisplayName = selectedClient.userLabel || uploadUserId;
    try {
      await ensureUploadWorkspace({
        apiBaseUrl,
        client: selectedClient,
        userId: uploadUserId,
        displayName: uploadDisplayName,
        sessionToken: session?.sessionToken,
      });
      await Promise.all(
        selectedFiles.map((file) =>
          uploadDocumentToBackend({
            apiBaseUrl,
            clientId: selectedClient.clientId,
            userId: uploadUserId,
            uploadedBy: uploadDisplayName,
            documentType: intakeMetadata.documentType,
            intakeCategory: intakeMetadata.intakeCategory,
            sessionToken: session?.sessionToken,
            file,
          }),
        ),
      );
      setUploadStatus(`${selectedFiles.length} belge backend kuyruÄŸuna alÄ±ndÄ±.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setUploadStatus(
        localFallbackAllowed
          ? `Backend yÃ¼kleme tamamlanamadÄ±; belge lokal listede tutuldu. ${message}`
          : `Backend yÃ¼kleme tamamlanamadÄ±; serverda belge kaydedilmedi. ${message}`,
      );
    }
  }

  function requestCancellation(document: PilotDocument) {
    const request: CancellationRequest = {
      id: `${document.id}-request-${Date.now()}`,
      documentId: document.id,
      clientId: document.clientId,
      fileName: document.fileName,
      requestedBy: selectedClient?.userLabel ?? "MÃ¼kellef kullanÄ±cÄ±sÄ±",
      requestedAt: new Date().toLocaleString("tr-TR"),
      reason: cancelReason.trim() || "MÃ¼kellef iptal veya dÃ¼zeltme talebi gÃ¶nderdi.",
      stage: document.status === "exported" || document.status === "export_added" ? "post_export" : "pre_export",
      status: "open",
    };
    setData((current) => ({
      ...current,
      cancellationRequests: [request, ...current.cancellationRequests],
      documents: current.documents.map((item) =>
        item.id === document.id
          ? { ...item, status: request.stage === "post_export" ? "post_export_correction_requested" : "cancel_requested" }
          : item,
      ),
    }));
    setCancelReason("");
    setClientCancellationDocumentId("");
    setSelectedDocumentId(document.id);
  }

  function resolveCancellation(requestId: string, status: "approved" | "rejected") {
    setData((current) => ({
      ...current,
      cancellationRequests: current.cancellationRequests.map((request) =>
        request.id === requestId ? { ...request, status } : request,
      ),
      documents: current.documents.map((document) => {
        const request = current.cancellationRequests.find((item) => item.id === requestId);
        if (!request || request.documentId !== document.id) return document;
        return { ...document, status: status === "approved" ? "cancel_approved" : "cancel_rejected" };
      }),
    }));
  }

  function addSelectedClientToBasket() {
    if (!selectedClient) return;
    const readyDocuments = clientDocuments.filter((document) => document.status === "export_ready" || document.status === "export_added");
    if (!readyDocuments.length) {
      setExportStatus("Bu mÃ¼kellefte Ã§Ä±ktÄ±ya uygun belge yok.");
      return;
    }
    const item: ExportBasketItem = {
      id: `${selectedClient.clientId}-${Date.now()}`,
      clientId: selectedClient.clientId,
      clientName: selectedClient.clientName,
      documentIds: readyDocuments.map((document) => document.id),
      documentCount: readyDocuments.length,
      period: selectedPeriod || readyDocuments[0].period,
      status: "ready",
    };
    setData((current) => ({
      ...current,
      exportBasket: [item, ...current.exportBasket.filter((basketItem) => basketItem.clientId !== selectedClient.clientId)],
      documents: current.documents.map((document) =>
        item.documentIds.includes(document.id) ? { ...document, status: "export_added" } : document,
      ),
    }));
    setExportStatus(`${selectedClient.clientName} Ã§Ä±ktÄ± listesine eklendi.`);
  }

  function markBasketPackaged() {
    setData((current) => ({
      ...current,
      exportBasket: current.exportBasket.map((item) => ({ ...item, status: "packaged" })),
      documents: current.documents.map((document) =>
        current.exportBasket.some((item) => item.documentIds.includes(document.id)) ? { ...document, status: "exported" } : document,
      ),
    }));
    setExportStatus(exportMode === "bulk" ? "SeÃ§ili mÃ¼kellefler iÃ§in toplu paket hazÄ±r gÃ¶rÃ¼nÃ¼yor." : "MÃ¼kellef bazlÄ± paketler hazÄ±r gÃ¶rÃ¼nÃ¼yor.");
  }

  async function requestStatementAiForSelectedDocument() {
    if (!selectedDocument || !selectedDocument.statementLines.length) {
      setStatementAiStatus("SeÃ§ili belgede banka satÄ±rÄ± yok.");
      return;
    }
    setStatementAiStatus("AI ajan Ã¶nerisi isteniyor.");
    try {
      const payload = await requestStatementAiSuggestions({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedDocument.clientId,
        lines: selectedDocument.statementLines,
        aiPolicy: { enabled: true, max_provider_calls: 3 },
        providerName: "openai",
        providerPayloads: [],
        sessionToken: session?.sessionToken,
      });
      const response = safeRecord(payload);
      const suggestions = normalizeStatementAiSuggestions(response.suggestions);
      const aiUsedCount = safeNumber(response.ai_used_count);
      const skippedCount = safeNumber(response.skipped_count);
      setData((current) => ({
        ...current,
        documents: current.documents.map((document) =>
          document.id === selectedDocument.id
            ? {
                ...document,
                statementAiSuggestions: suggestions.length ? suggestions : document.statementAiSuggestions,
                statementAiSummary: `${aiUsedCount} AI ajan Ã¶nerisi / ${skippedCount} satÄ±r atlandÄ±`,
              }
            : document,
        ),
      }));
      setStatementAiStatus(suggestions.length ? `${suggestions.length} AI ajan Ã¶nerisi alÄ±ndÄ±.` : "Ã–neri motoru sonuÃ§ dÃ¶ndÃ¼rmedi; mevcut Ã¶neriler korundu.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatementAiStatus(`AI ajan Ã¶nerisi alÄ±namadÄ±. ${message}`);
    }
  }

  async function saveStatementLineDecision(action: string) {
    if (!selectedDocument) return;
    const lineNo = selectedStatementLineNo || selectedDocument.statementLines[0]?.line_no || 0;
    const selectedLine = selectedDocument.statementLines.find((line) => line.line_no === lineNo);
    if (!lineNo || !selectedLine) {
      setDecisionStatus("Banka satÄ±rÄ± seÃ§ili deÄŸil.");
      return;
    }
    const correctedAccountCode = correctionDraft.accountCode.trim();
    const correctedCounterpartyCode = correctionDraft.counterpartyCode.trim();
    const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
    const reason = correctionDraft.reason.trim();
    setData((current) => ({
      ...current,
      documents: current.documents.map((document) =>
        document.id === selectedDocument.id
          ? applyStatementLineDecision(document, lineNo, action, correctedAccountCode, correctedCounterpartyCode, reviewer, reason)
          : document,
      ),
    }));
    const label = statementStatusLabel(statementReviewStatus(action));
    setDecisionStatus(`${selectedDocument.fileName} / ${lineNo}. satÄ±r: ${label} arayÃ¼zde uygulandÄ±.`);
    try {
      await storeReviewDecision({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedDocument.clientId,
        userId: reviewer,
        documentRef: selectedDocument.id,
        action,
        reviewer,
        applyToSimilar: action === "suggest_for_similar",
        statementLineNo: lineNo,
        correctedAccountCode,
        correctedCounterpartyCode,
        category: selectedLine.transaction_type,
        reason,
        sessionToken: session?.sessionToken,
      });
      setDecisionStatus(`${selectedDocument.fileName} / ${lineNo}. satÄ±r: ${label} backend'e kaydedildi.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setDecisionStatus(
        localFallbackAllowed
          ? `${selectedDocument.fileName} / ${lineNo}. satÄ±r lokal uygulandÄ±; backend kaydÄ± tamamlanamadÄ±. ${message}`
          : `${selectedDocument.fileName} / ${lineNo}. satÄ±r backend'e kaydedilemedi; serverda kalÄ±cÄ± karar oluÅŸmadÄ±. ${message}`,
      );
    }
  }

  async function saveDecision(action: string) {
    if (!selectedDocument) return;
    const reviewer = session?.role === "accountant" ? session.userId : loginUserId.trim() || "mali-musavir";
    const correctedAccountCode = correctionDraft.accountCode.trim();
    const correctedCounterpartyCode = correctionDraft.counterpartyCode.trim();
    const reason = correctionDraft.reason.trim();
    const nextStatus: PilotStatus = action === "approve" || action === "approve_with_changes" || action === "suggest_for_similar" ? "export_ready" : "review_required";
    const label = reviewActionLabel(action);
    setData((current) => ({
      ...current,
      documents: current.documents.map((document) =>
        document.id === selectedDocument.id
          ? {
              ...document,
              status: nextStatus,
              selectedExpenseAccount: correctedAccountCode || document.selectedExpenseAccount,
              selectedCounterpartyAccount: correctedCounterpartyCode || document.selectedCounterpartyAccount,
              exportGateReason:
                nextStatus === "export_ready"
                  ? "MÃ¼ÅŸavir onayÄ± verildi; Ã§Ä±ktÄ± listesine alÄ±nabilir."
                  : "MÃ¼ÅŸavir kararÄ± Ã§Ä±ktÄ±ya almadÄ± veya kontrolÃ¼ sÃ¼rdÃ¼rdÃ¼.",
            }
          : document,
      ),
    }));
    setDecisionStatus(`${selectedDocument.fileName}: ${label} arayÃ¼zde uygulandÄ±.`);
    try {
      await storeReviewDecision({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedDocument.clientId,
        userId: reviewer,
        documentRef: selectedDocument.id,
        action,
        reviewer,
        applyToSimilar: action === "suggest_for_similar",
        correctedAccountCode,
        correctedCounterpartyCode,
        category: selectedDocument.productCategory,
        reason,
        sessionToken: session?.sessionToken,
      });
      setDecisionStatus(`${selectedDocument.fileName}: ${label} backend'e kaydedildi.`);
      await refreshBackendPilotData();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setDecisionStatus(
        localFallbackAllowed
          ? `${selectedDocument.fileName}: ${label} lokal uygulandÄ±; backend kaydÄ± tamamlanamadÄ±. ${message}`
          : `${selectedDocument.fileName}: ${label} backend'e kaydedilemedi; serverda kalÄ±cÄ± karar oluÅŸmadÄ±. ${message}`,
      );
    }
  }

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


function ModeButton({ active, href, label }: { active: boolean; href: string; label: string }) {
  return (
    <a aria-current={active ? "page" : undefined} className={active ? "mode-tab active" : "mode-tab"} href={href}>
      {label}
    </a>
  );
}

function PortalTopbarStatus({
  localFallbackAllowed,
  onExit,
  session,
  source,
}: {
  localFallbackAllowed: boolean;
  onExit: () => void;
  session: LocalSession | null;
  source: string;
}) {
  return (
    <div className="portal-statusbar" aria-label="Portal oturum durumu">
      <div className="topbar-user">
        <span>{session ? roleLabels[session.role] : localFallbackAllowed ? "Lokal ofis" : "Oturum kapalÄ±"}</span>
        <strong>{session?.userId || "Oturum yok"}</strong>
      </div>
      <div className="pilot-source compact">
        <span>Veri kaynaÄŸÄ±</span>
        <strong>{source}</strong>
      </div>
      <button className="secondary compact-exit" onClick={onExit} type="button">
        Ã‡Ä±kÄ±ÅŸ
      </button>
    </div>
  );
}

function SelectedClientStrip({
  client,
  documents,
  openCancellationCount,
}: {
  client?: PilotClient;
  documents: PilotDocument[];
  openCancellationCount: number;
}) {
  const readyCount = documents.filter((document) => document.status === "export_ready" || document.status === "export_added").length;
  const reviewCount = documents.filter((document) => document.status === "review_required").length;
  return (
    <section className="selected-client-strip" aria-label="SeÃ§ili mÃ¼kellef">
      <Info label="SeÃ§ili mÃ¼kellef" value={client?.clientName ?? "-"} />
      <Info label="VKN" value={client?.taxId ?? "-"} />
      <Info label="Belge" value={String(documents.length)} />
      <Info label="Kontrol" value={String(reviewCount)} />
      <Info label="Ã‡Ä±ktÄ± hazÄ±r" value={String(readyCount)} />
      <Info label="Ä°ptal talebi" value={String(openCancellationCount)} />
    </section>
  );
}
