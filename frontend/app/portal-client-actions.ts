import type { Dispatch, SetStateAction } from "react";
import {
  buildClientOnboardingPackagePayload,
  buildNaceResearchRefreshPayload,
  buildTaxCertificateParseStatus,
  createClientOnboardingPackage,
  createPortalInvite,
  deleteClientDocuments,
  parseChartAccountsFromBackend,
  parseTaxCertificateFromBackend,
  reprocessClient,
  resolveApiBaseUrl,
  sessionAuthErrorMessage,
  setPortalPassword as setBackendPortalPassword,
  updateClientPortalAccess,
  uploadChartAccountsToBackend,
  uploadTaxCertificateToBackend,
} from "./upload-api";
import { refreshResearchProfile } from "./workspace-api";
import type { LocalSession, NewClientDraft, PilotClient } from "./portal-types";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export function emptyNewClientDraft(): NewClientDraft {
  return {
    clientId: "",
    title: "",
    taxId: "",
    tckn: "",
    vkn: "",
    identityType: "",
    taxIdentifier: "",
    legalName: "",
    tradeName: "",
    displayTitle: "",
    taxOffice: "",
    activityDescription: "",
    naceCode: "",
    activityTags: [],
    activityProfile: {},
    workplaceAddresses: [],
    chartAccounts: [],
    chartAccountFileName: "",
    portalUserId: "",
    portalDisplayName: "",
  };
}

function profileText(value: unknown): string {
  return String(value || "").trim();
}

function naceResearchStatus(profile: Record<string, unknown>) {
  const title = profileText(profile.activity_title || profile.display_name || profile.nace_code);
  const confidence = Number(profile.research_confidence || profile.confidence || 0);
  const summary = profileText(profile.summary_tr || profile.scope_summary);
  return [
    title ? `NACE araştırması tamamlandı: ${title}` : "NACE araştırması tamamlandı.",
    confidence ? `Güven ${confidence}.` : "",
    summary ? summary : "",
  ].filter(Boolean).join(" ");
}

export async function refreshNewClientNaceResearchAction({
  force = false,
  loginUserId,
  newClientDraft,
  session,
  setNewClientDraft,
  setNewClientNaceResearchPending,
  setNewClientNaceResearchProfile,
  setNewClientNaceResearchStatus,
}: {
  force?: boolean;
  loginUserId: string;
  newClientDraft: NewClientDraft;
  session: LocalSession | null;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientNaceResearchPending: (pending: boolean) => void;
  setNewClientNaceResearchProfile: (profile: Record<string, unknown> | null) => void;
  setNewClientNaceResearchStatus: (status: string) => void;
}) {
  const payload = buildNaceResearchRefreshPayload({
    naceCode: newClientDraft.naceCode,
    activityDescription: newClientDraft.activityDescription,
    force,
  });
  if (!payload) {
    setNewClientNaceResearchStatus("NACE kodu bulunamadı. Kodu veya faaliyeti doldurup araştırmayı onaylayın.");
    return;
  }
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientNaceResearchPending(true);
  setNewClientNaceResearchStatus("NACE araştırması yapılıyor. Bu sırada diğer adımlara devam edebilirsiniz.");
  try {
    const result = await refreshResearchProfile({
      apiBaseUrl,
      userId: actingUserId,
      sessionToken: session?.sessionToken,
      payload,
    });
    const profile = result?.profile && typeof result.profile === "object" ? result.profile as Record<string, unknown> : {};
    const activityTags = Array.isArray(profile.activity_tags)
      ? (profile.activity_tags as unknown[]).map((value) => String(value).trim()).filter(Boolean)
      : [];
    setNewClientNaceResearchProfile(profile);
    setNewClientDraft((current) => ({
      ...current,
      activityTags: activityTags.length ? Array.from(new Set([...current.activityTags, ...activityTags])) : current.activityTags,
      activityProfile: {
        ...current.activityProfile,
        ...(profile.activity_title || profile.display_name ? { display_label: profileText(profile.activity_title || profile.display_name) } : {}),
        ...(profile.confidence || profile.research_confidence ? { confidence: Number(profile.confidence || profile.research_confidence) } : {}),
        nace_research_profile: profile,
      },
    }));
    setNewClientNaceResearchStatus(naceResearchStatus(profile));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setNewClientNaceResearchProfile(null);
    setNewClientNaceResearchStatus(`NACE araştırması tamamlanamadı. Sonra tekrar deneyin. ${message}`);
  } finally {
    setNewClientNaceResearchPending(false);
  }
}

export async function createNewClientAction({
  loginUserId,
  newClientChartAccountsFile,
  newClientDraft,
  newClientNaceResearchPending = false,
  newClientNaceResearchProfile = null,
  newClientNaceResearchWarningAccepted = false,
  newClientTaxCertificateFile,
  portalPassword,
  refreshBackendPilotData,
  session,
  setNewClientDraft,
  setNewClientChartAccountsFile,
  setNewClientNaceResearchProfile = () => undefined,
  setNewClientNaceResearchStatus = () => undefined,
  setNewClientNaceResearchWarningAccepted = () => undefined,
  setNewClientStatus,
  setNewClientTaxCertificateFile,
  setNewClientTaxCertificateInputKey,
  setPortalPasswordDraft,
  setSelectedClientId,
}: {
  loginUserId: string;
  newClientDraft: NewClientDraft;
  newClientNaceResearchPending?: boolean;
  newClientNaceResearchProfile?: Record<string, unknown> | null;
  newClientNaceResearchWarningAccepted?: boolean;
  newClientTaxCertificateFile: File | null;
  newClientChartAccountsFile: File | null;
  portalPassword: string;
  refreshBackendPilotData: () => Promise<boolean>;
  session: LocalSession | null;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientChartAccountsFile: (file: File | null) => void;
  setNewClientNaceResearchProfile?: (profile: Record<string, unknown> | null) => void;
  setNewClientNaceResearchStatus?: (status: string) => void;
  setNewClientNaceResearchWarningAccepted?: (accepted: boolean) => void;
  setNewClientStatus: (status: string) => void;
  setNewClientTaxCertificateFile: (file: File | null) => void;
  setNewClientTaxCertificateInputKey: Dispatch<SetStateAction<number>>;
  setPortalPasswordDraft: (password: string) => void;
  setSelectedClientId: (clientId: string) => void;
}) {
  if (!newClientDraft.title.trim()) {
    setNewClientStatus("Mükellef adı gerekli.");
    return;
  }
  if (!newClientDraft.vkn.trim() && !newClientDraft.tckn.trim() && !newClientDraft.taxId.trim()) {
    setNewClientStatus("VKN veya TCKN gerekli.");
    return;
  }
  if (!newClientDraft.chartAccounts.length) {
    setNewClientStatus("Devam etmek için hesap planı yükleyin.");
    return;
  }
  if (!newClientDraft.portalUserId.trim() || !portalPassword.trim()) {
    setNewClientStatus("Portal kullanıcı adı ve geçici şifre gerekli.");
    return;
  }
  if (newClientDraft.naceCode.trim() && (newClientNaceResearchPending || !newClientNaceResearchProfile) && !newClientNaceResearchWarningAccepted) {
    setNewClientNaceResearchWarningAccepted(true);
    setNewClientStatus("NACE araştırması henüz tamamlanmadı. Kontrol edip devam etmek istiyorsanız Mükellefi oluştur düğmesine tekrar basın.");
    return;
  }
  const payload = buildClientOnboardingPackagePayload(newClientDraft);
  const taxCertificateFile = newClientTaxCertificateFile;
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientStatus(taxCertificateFile ? "Mükellef kaydediliyor, vergi levhası yüklenecek." : "Mükellef kaydediliyor.");
  try {
    await createClientOnboardingPackage({
      apiBaseUrl,
      client: newClientDraft,
      sessionToken: session?.sessionToken,
      userId: actingUserId,
    });
    setSelectedClientId(payload.client.client_id);
    if (newClientChartAccountsFile) {
      setNewClientStatus("Mükellef kaydedildi. Hesap planı ham dosyası saklanıyor.");
      await uploadChartAccountsToBackend({
        apiBaseUrl,
        clientId: payload.client.client_id,
        userId: actingUserId,
        sessionToken: session?.sessionToken,
        file: newClientChartAccountsFile,
      });
    }
    let certificateStatus = "";
    if (taxCertificateFile) {
      setNewClientStatus("Mükellef kaydedildi. Vergi levhası yükleniyor.");
      try {
        await uploadTaxCertificateToBackend({
          apiBaseUrl,
          clientId: payload.client.client_id,
          userId: actingUserId,
          uploadedBy: actingUserId,
          sessionToken: session?.sessionToken,
          file: taxCertificateFile,
        });
        certificateStatus = " Vergi levhası yüklendi.";
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        certificateStatus = ` Vergi levhası yüklenemedi: ${message}`;
      }
    }
    await setBackendPortalPassword({
      apiBaseUrl,
      userId: payload.portal_users[0]?.user_id || newClientDraft.portalUserId,
      password: portalPassword,
      sessionToken: session?.sessionToken,
      userHeader: actingUserId,
    });
    setNewClientDraft(emptyNewClientDraft());
    setNewClientChartAccountsFile(null);
    setNewClientNaceResearchProfile(null);
    setNewClientNaceResearchStatus("");
    setNewClientNaceResearchWarningAccepted(false);
    setPortalPasswordDraft("");
    setNewClientTaxCertificateFile(null);
    setNewClientTaxCertificateInputKey((current) => current + 1);
    setNewClientStatus(`${payload.client.title} eklendi.${certificateStatus}`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setNewClientStatus(`Mükellef kaydedilemedi. ${sessionAuthErrorMessage(message) || message}`);
  }
}

export async function selectNewClientTaxCertificateAction({
  file,
  loginUserId,
  session,
  setNewClientDraft,
  setNewClientNaceResearchPending = () => undefined,
  setNewClientNaceResearchProfile = () => undefined,
  setNewClientNaceResearchStatus = () => undefined,
  setNewClientStatus,
  setNewClientTaxCertificateFile,
  setNewClientTaxCertificateParsePending = () => undefined,
  setNewClientTaxCertificateStage = () => undefined,
}: {
  file: File | null;
  loginUserId: string;
  session: LocalSession | null;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientNaceResearchPending?: (pending: boolean) => void;
  setNewClientNaceResearchProfile?: (profile: Record<string, unknown> | null) => void;
  setNewClientNaceResearchStatus?: (status: string) => void;
  setNewClientStatus: (status: string) => void;
  setNewClientTaxCertificateFile: (file: File | null) => void;
  setNewClientTaxCertificateParsePending?: (pending: boolean) => void;
  setNewClientTaxCertificateStage?: (stage: string) => void;
}) {
  setNewClientTaxCertificateFile(file);
  setNewClientNaceResearchProfile(null);
  setNewClientNaceResearchStatus("");
  setNewClientTaxCertificateStage(file ? "Vergi levhası alındı" : "");
  setNewClientTaxCertificateParsePending(false);
  if (!file) return;
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientStatus(`${file.name} vergi levhası okunuyor.`);
  setNewClientTaxCertificateParsePending(true);
  setNewClientTaxCertificateStage("OCR/parser çalışıyor");
  try {
    const extraction = await parseTaxCertificateFromBackend({
      apiBaseUrl,
      userId: actingUserId,
      sessionToken: session?.sessionToken,
      file,
    });
    const title = String(extraction?.display_title || extraction?.title || "").trim();
    const legalName = String(extraction?.legal_name || "").trim();
    const tradeName = String(extraction?.trade_name || "").trim();
    const tckn = String(extraction?.tckn || "").trim();
    const vkn = String(extraction?.vkn || "").trim();
    const identityType = String(extraction?.identity_type || "").trim();
    const taxIdentifier = String(extraction?.tax_identifier || extraction?.tax_id || vkn || tckn || "").trim();
    const taxId = String(extraction?.tax_id || taxIdentifier).trim();
    const taxOffice = String(extraction?.tax_office || "").trim();
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
      tckn: current.tckn.trim() || tckn,
      vkn: current.vkn.trim() || vkn,
      identityType: current.identityType.trim() || identityType,
      taxIdentifier: current.taxIdentifier.trim() || taxIdentifier,
      legalName: current.legalName.trim() || legalName,
      tradeName: current.tradeName.trim() || tradeName,
      displayTitle: current.displayTitle.trim() || title,
      taxOffice: current.taxOffice.trim() || taxOffice,
      activityDescription: current.activityDescription.trim() || activityDescription,
      naceCode: current.naceCode.trim() || naceCode,
      activityTags: current.activityTags.length ? current.activityTags : activityTags,
      activityProfile: Object.keys(current.activityProfile).length ? current.activityProfile : activityProfile,
      workplaceAddresses: current.workplaceAddresses.length ? current.workplaceAddresses : workplaceAddresses,
    }));
    const filledFields = [
      title ? "unvan" : "",
      tckn ? "TCKN" : "",
      vkn ? "VKN" : "",
      taxOffice ? "vergi dairesi" : "",
      activityDescription || naceCode ? "faaliyet" : "",
      activityTags.length ? "faaliyet tag" : "",
      workplaceAddresses.length ? "adres" : "",
    ].filter(Boolean);
    const confidence = Number(extraction?.confidence || 0);
    const profileLabel = String(activityProfile.display_label || "").trim();
    const profileConfidence = Number(activityProfile.confidence || 0);
    const profileSummary = profileLabel ? `Profil: ${profileLabel}${profileConfidence ? ` ${profileConfidence}` : ""}` : "";
    setNewClientStatus(buildTaxCertificateParseStatus({ filledFields, confidence, profileSummary, tckn, vkn }));
    setNewClientTaxCertificateStage("Alanlar dolduruldu");
    if (naceCode) {
      await refreshNewClientNaceResearchAction({
        loginUserId,
        newClientDraft: {
          ...emptyNewClientDraft(),
          naceCode,
          activityDescription,
        },
        session,
        setNewClientDraft,
        setNewClientNaceResearchPending,
        setNewClientNaceResearchProfile,
        setNewClientNaceResearchStatus,
      });
    } else {
      setNewClientNaceResearchStatus("Vergi levhasından NACE kodu okunamadı. Alanı doldurunca araştırmayı onaylayın.");
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setNewClientStatus(`Vergi levhası okunamadı. Elle devam edebilirsiniz. ${message}`);
    setNewClientTaxCertificateStage("Vergi levhası okunamadı");
  } finally {
    setNewClientTaxCertificateParsePending(false);
  }
}

export async function parseNewClientChartAccountsAction({
  files,
  loginUserId,
  session,
  setNewClientChartAccountsFile,
  setNewClientDraft,
  setNewClientStatus,
}: {
  files: FileList | null;
  loginUserId: string;
  session: LocalSession | null;
  setNewClientChartAccountsFile: (file: File | null) => void;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientStatus: (status: string) => void;
}) {
  const file = files?.[0];
  if (!file) return;
  setNewClientChartAccountsFile(file);
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientStatus(`${file.name} hesap planı okunuyor.`);
  try {
    const result = await parseChartAccountsFromBackend({
      apiBaseUrl,
      userId: actingUserId,
      sessionToken: session?.sessionToken,
      file,
    });
    const accounts = Array.isArray(result?.accounts) ? (result.accounts as Record<string, unknown>[]) : [];
    setNewClientDraft((current) => ({
      ...current,
      chartAccounts: accounts,
      chartAccountFileName: file.name,
    }));
    setNewClientStatus(`${file.name}: ${Number(result?.account_count || accounts.length)} hesap okundu.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setNewClientStatus(`Hesap planı okunamadı. ${message}`);
  }
}

export async function uploadChartAccountsAction({
  files,
  loginUserId,
  refreshBackendPilotData,
  selectedClient,
  session,
  setChartUploadStatus,
}: {
  files: FileList | null;
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setChartUploadStatus: (status: string) => void;
}) {
  const file = files?.[0];
  if (!file || !selectedClient) return;
  setChartUploadStatus(`${file.name} hesap planı import ediliyor...`);
  try {
    const result = await uploadChartAccountsToBackend({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedClient.clientId,
      userId: session?.userId || loginUserId.trim() || "mali-musavir",
      sessionToken: session?.sessionToken,
      file,
    });
    setChartUploadStatus(`${selectedClient.clientName}: ${result.account_count ?? 0} hesap backend store'a yazildi.`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setChartUploadStatus(`Hesap planı importu tamamlanamadı. ${message}`);
  }
}

export async function createInviteForSelectedClientAction({
  loginUserId,
  refreshBackendPilotData,
  selectedClient,
  session,
  setInviteStatus,
}: {
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setInviteStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const userId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
  setInviteStatus(`${userId} için davet tokeni hazırlanıyor...`);
  try {
    const result = await createPortalInvite({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
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

export async function setPasswordForSelectedClientAction({
  loginUserId,
  portalPassword,
  selectedClient,
  session,
  setPortalPasswordDraft,
  setPortalPasswordStatus,
}: {
  loginUserId: string;
  portalPassword: string;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setPortalPasswordDraft: (password: string) => void;
  setPortalPasswordStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const userId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
  setPortalPasswordStatus(`${userId} için şifre kuruluyor...`);
  try {
    const result = await setBackendPortalPassword({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      userId,
      password: portalPassword,
      sessionToken: session?.sessionToken,
      userHeader: session?.userId || loginUserId.trim(),
    });
    setPortalPasswordStatus(result.has_password ? `${userId} için şifre hazır.` : `${userId} için şifre sonucu alındı.`);
    setPortalPasswordDraft("");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setPortalPasswordStatus(`Sifre kurulumu tamamlanamadi. ${message}`);
  }
}

export async function reprocessSelectedClientAction({
  loginUserId,
  refreshBackendPilotData,
  selectedClient,
  session,
  setClientReprocessStatus,
}: {
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setClientReprocessStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setClientReprocessStatus(`${selectedClient.clientName}: vergi levhası, NACE ve belgeler yeniden işleniyor.`);
  try {
    const result = await reprocessClient({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedClient.clientId,
      userId: actingUserId,
      sessionToken: session?.sessionToken,
      maxJobs: 100,
    });
    const queued = Number(result?.queued_document_count || 0);
    const completed = Number(result?.processing_summary?.completed_count || 0);
    setClientReprocessStatus(`${selectedClient.clientName}: ${queued} belge kuyruğa alındı, ${completed} işlem tamamlandı.`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setClientReprocessStatus(`${selectedClient.clientName}: yeniden işleme tamamlanamadı. ${message}`);
  }
}

export async function updatePortalAccessForSelectedClientAction({
  loginUserId,
  portalPassword,
  portalUserIdDraft,
  refreshBackendPilotData,
  selectedClient,
  session,
  setPortalPasswordDraft,
  setPortalPasswordStatus,
}: {
  loginUserId: string;
  portalPassword: string;
  portalUserIdDraft: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setPortalPasswordDraft: (password: string) => void;
  setPortalPasswordStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const oldUserId = selectedClient.portalUserId || `${selectedClient.clientId}-user`;
  const newUserId = portalUserIdDraft.trim();
  if (!newUserId) {
    setPortalPasswordStatus("Yeni üyelik adı gerekli.");
    return;
  }
  setPortalPasswordStatus(`${selectedClient.clientName} üyeliği güncelleniyor...`);
  try {
    const result = await updateClientPortalAccess({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedClient.clientId,
      oldUserId,
      newUserId,
      displayName: selectedClient.userLabel || selectedClient.clientName,
      password: portalPassword,
      sessionToken: session?.sessionToken,
      userHeader: session?.userId || loginUserId.trim(),
    });
    const oldUserMessage = result.old_user_removed ? "Eski giriş kapatıldı." : "Eski giriş bu mükelleften kaldırıldı.";
    setPortalPasswordStatus(`${newUserId} aktif. ${oldUserMessage}`);
    setPortalPasswordDraft("");
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setPortalPasswordStatus(`Üyelik güncellenemedi. ${sessionAuthErrorMessage(message) || message}`);
  }
}

export async function deleteSelectedClientDocumentsAction({
  deleteConfirmed,
  loginUserId,
  refreshBackendPilotData,
  selectedClient,
  selectedDocumentRefs,
  session,
  setClientDocumentDeleteStatus,
  setSelectedDocumentRefs,
}: {
  deleteConfirmed: boolean;
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  selectedDocumentRefs: string[];
  session: LocalSession | null;
  setClientDocumentDeleteStatus: (status: string) => void;
  setSelectedDocumentRefs: (refs: string[]) => void;
}) {
  if (!selectedClient) return;
  const refs = Array.from(new Set(selectedDocumentRefs.map((ref) => ref.trim()).filter(Boolean)));
  if (!refs.length) {
    setClientDocumentDeleteStatus("Silmek için en az bir belge seçin.");
    return;
  }
  if (!deleteConfirmed) {
    setClientDocumentDeleteStatus("Toplu silme için onay kutusunu işaretleyin.");
    return;
  }
  setClientDocumentDeleteStatus(`${refs.length} belge siliniyor...`);
  try {
    const result = await deleteClientDocuments({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedClient.clientId,
      documentRefs: refs,
      deleteFiles: true,
      sessionToken: session?.sessionToken,
      userHeader: session?.userId || loginUserId.trim(),
    });
    setClientDocumentDeleteStatus(`${result.deleted_count ?? refs.length} belge silindi.`);
    setSelectedDocumentRefs([]);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setClientDocumentDeleteStatus(`Belgeler silinemedi. ${sessionAuthErrorMessage(message) || message}`);
  }
}
