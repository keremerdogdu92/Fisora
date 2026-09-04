// File: frontend/app/portal-client-actions.ts
// Summary: Handles client onboarding actions and surfaces Gemini-first tax-certificate extraction safely.
import type { Dispatch, SetStateAction } from "react";
import {
  buildDelegatedClientPortalUrl,
  buildClientOnboardingPackagePayload,
  buildNaceResearchRefreshPayload,
  buildTaxCertificateParseStatus,
  createDelegatedClientSession,
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

function reviewedTaxCertificatePayload(draft: NewClientDraft): Record<string, unknown> {
  const taxIdentifier = draft.vkn.trim() || draft.tckn.trim() || draft.taxId.trim();
  const identityType = draft.identityType.trim() || (draft.vkn.trim() ? "vkn" : draft.tckn.trim() ? "tckn" : "");
  return {
    title: draft.title.trim(),
    display_title: draft.title.trim(),
    legal_name: draft.legalName.trim(),
    trade_name: draft.tradeName.trim(),
    tax_id: taxIdentifier,
    tckn: draft.tckn.trim(),
    vkn: draft.vkn.trim(),
    identity_type: identityType,
    tax_identifier: taxIdentifier,
    tax_office: draft.taxOffice.trim(),
    activity_description: draft.activityDescription.trim(),
    nace_code: draft.naceCode.trim(),
    activity_tags: draft.activityTags,
    activity_profile: draft.activityProfile,
    workplace_addresses: draft.workplaceAddresses,
    extraction_notes: ["reviewed_onboarding"],
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
  newClientTaxCertificateFile,
  refreshBackendPilotData,
  session,
  setNewClientDraft,
  setNewClientChartAccountsFile,
  setNewClientNaceResearchProfile = () => undefined,
  setNewClientNaceResearchStatus = () => undefined,
  setNewClientStatus,
  setNewClientTaxCertificateFile,
  setNewClientTaxCertificateInputKey,
  setPortalPasswordDraft,
  setSelectedClientId,
}: {
  loginUserId: string;
  newClientDraft: NewClientDraft;
  newClientTaxCertificateFile: File | null;
  newClientChartAccountsFile: File | null;
  refreshBackendPilotData: () => Promise<boolean>;
  session: LocalSession | null;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientChartAccountsFile: (file: File | null) => void;
  setNewClientNaceResearchProfile?: (profile: Record<string, unknown> | null) => void;
  setNewClientNaceResearchStatus?: (status: string) => void;
  setNewClientStatus: (status: string) => void;
  setNewClientTaxCertificateFile: (file: File | null) => void;
  setNewClientTaxCertificateInputKey: Dispatch<SetStateAction<number>>;
  setPortalPasswordDraft: (password: string) => void;
  setSelectedClientId: (clientId: string) => void;
}) {
  if (!newClientTaxCertificateFile) {
    setNewClientStatus("Önce vergi levhasını yükleyin.");
    return;
  }
  if (!newClientDraft.title.trim()) {
    setNewClientStatus("Vergi levhasındaki unvanı kontrol edin.");
    return;
  }
  if (!newClientDraft.vkn.trim() && !newClientDraft.tckn.trim() && !newClientDraft.taxId.trim()) {
    setNewClientStatus("VKN veya TCKN gerekli.");
    return;
  }
  if (!newClientDraft.activityDescription.trim() && !newClientDraft.naceCode.trim() && !newClientDraft.activityTags.length) {
    setNewClientStatus("Faaliyet, NACE veya faaliyet etiketi bilgilerinden en az biri gerekli.");
    return;
  }
  if (!newClientDraft.workplaceAddresses.length) {
    setNewClientStatus("Vergi levhasındaki işyeri adresini kontrol edin.");
    return;
  }
  if (!newClientDraft.chartAccounts.length) {
    setNewClientStatus("Devam etmek için hesap planı yükleyin.");
    return;
  }
  const payload = buildClientOnboardingPackagePayload(newClientDraft);
  const taxCertificateFile = newClientTaxCertificateFile;
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientStatus("Mükellef kaydediliyor. Kontrol ettiğiniz vergi levhası bilgileri esas alınacak.");
  try {
    await createClientOnboardingPackage({
      apiBaseUrl,
      client: newClientDraft,
      sessionToken: session?.sessionToken,
      userId: actingUserId,
    });
    setSelectedClientId(payload.client.client_id);
    let chartArchiveStatus = "";
    if (newClientChartAccountsFile) {
      setNewClientStatus("Mükellef kaydedildi. Hesap planı ham dosyası saklanıyor.");
      try {
        await uploadChartAccountsToBackend({
          apiBaseUrl,
          clientId: payload.client.client_id,
          userId: actingUserId,
          sessionToken: session?.sessionToken,
          file: newClientChartAccountsFile,
          storeOnly: true,
        });
        chartArchiveStatus = " Hesap planı ham dosyası arşivlendi.";
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        chartArchiveStatus = ` Hesap planı kaydedildi; ham dosya arşivlenemedi: ${message}`;
      }
    }
    let certificateStatus = "";
    if (taxCertificateFile) {
      setNewClientStatus("Mükellef kaydedildi. Vergi levhasının orijinal dosyası arşivleniyor.");
      try {
        await uploadTaxCertificateToBackend({
          apiBaseUrl,
          clientId: payload.client.client_id,
          userId: actingUserId,
          uploadedBy: actingUserId,
          sessionToken: session?.sessionToken,
          file: taxCertificateFile,
          taxCertificate: reviewedTaxCertificatePayload(newClientDraft),
        });
        certificateStatus = " Vergi levhası arşivlendi; ikinci Gemini okuması yapılmadı.";
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        certificateStatus = ` Vergi levhası yüklenemedi: ${message}`;
      }
    }
    setNewClientDraft(emptyNewClientDraft());
    setNewClientChartAccountsFile(null);
    setNewClientNaceResearchProfile(null);
    setNewClientNaceResearchStatus("");
    setPortalPasswordDraft("");
    setNewClientTaxCertificateFile(null);
    setNewClientTaxCertificateInputKey((current) => current + 1);
    setNewClientStatus(`${payload.client.title} eklendi.${chartArchiveStatus}${certificateStatus}`);
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
  setNewClientTaxCertificateStage("Gemini vergi levhasını analiz ediyor");
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
    const parseStatus = String(extraction?.parse_status || "").trim();
    const missingCriticalFields = Array.isArray(extraction?.missing_critical_fields)
      ? (extraction.missing_critical_fields as unknown[]).map((value) => String(value).trim()).filter(Boolean)
      : [];
    const profileLabel = String(activityProfile.display_label || "").trim();
    const profileConfidence = Number(activityProfile.confidence || 0);
    const profileSummary = profileLabel ? `Profil: ${profileLabel}${profileConfidence ? ` ${profileConfidence}` : ""}` : "";
    setNewClientStatus(buildTaxCertificateParseStatus({
      filledFields,
      confidence,
      profileSummary,
      parseStatus,
      missingCriticalFields,
    }));
    setNewClientTaxCertificateStage(parseStatus === "partial" ? "Gemini alanları kısmen doldurdu" : "Gemini alanları doldurdu");
    if (naceCode) {
      setNewClientNaceResearchStatus("NACE kodu okundu. Araştırma isteğe bağlıdır ve mükellef kaydını engellemez.");
    } else {
      setNewClientNaceResearchStatus("NACE kodu okunamadı. Gerekirse alanı elle doldurup araştırmayı çalıştırabilirsiniz.");
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
  portalUserIdDraft = "",
  refreshBackendPilotData,
  selectedClient,
  session,
  setInviteStatus,
}: {
  loginUserId: string;
  portalUserIdDraft?: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setInviteStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const userId = portalUserIdDraft.trim() || selectedClient.portalUserId || `${selectedClient.clientId}-user`;
  const inviteEmail = userId.includes("@") ? userId : "";
  setInviteStatus(`${userId} için davet linki hazırlanıyor...`);
  try {
    const result = await createPortalInvite({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      userId,
      email: inviteEmail,
      displayName: selectedClient.userLabel || selectedClient.clientName,
      clientId: selectedClient.clientId,
      invitedBy: session?.userId || loginUserId.trim() || "mali-musavir",
      sessionToken: session?.sessionToken,
      userHeader: session?.userId || loginUserId.trim(),
    });
    const delivery = result.email_delivery as Record<string, unknown> | undefined;
    const deliveryStatus = String(delivery?.status || "");
    setInviteStatus(
      deliveryStatus === "sent" || deliveryStatus === "dry_run"
        ? "Davet maili hazırlandı."
        : "Davet linki hazır. Mail kapalıysa link elle paylaşılabilir.",
    );
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setInviteStatus(`Davet linki olusturulamadi. ${message}`);
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
    setClientReprocessStatus(`${selectedClient.clientName}: ${queued} belge kuyruğa alındı, arka planda işlenecek.`);
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

export async function openSelectedClientPortalAction({
  loginUserId,
  selectedClient,
  session,
  setClientPortalOpenStatus,
}: {
  loginUserId: string;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setClientPortalOpenStatus: (status: string) => void;
}) {
  if (!selectedClient) return;
  const targetUserId = selectedClient.portalUserId?.trim();
  if (!targetUserId) {
    setClientPortalOpenStatus("Portal kullanıcısı olmayan mükellef için ekran açılamaz.");
    return;
  }
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  const popup = typeof window === "undefined" ? null : window.open("about:blank", "_blank");
  if (popup) {
    try { popup.opener = null; popup.document.title = "Fisora"; } catch { /* cross-window hardening is best-effort */ }
  }
  setClientPortalOpenStatus(`${selectedClient.clientName} mükellef ekranı açılıyor...`);
  try {
    const delegatedSession = await createDelegatedClientSession({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
      clientId: selectedClient.clientId,
      targetUserId,
      userId: actingUserId,
      sessionToken: session?.sessionToken,
    });
    const url = buildDelegatedClientPortalUrl({
      origin: typeof window === "undefined" ? "" : window.location.origin,
      session: delegatedSession,
    });
    if (popup) {
      popup.location.href = url;
      setClientPortalOpenStatus(`${selectedClient.clientName} mükellef ekranı yeni sekmede açıldı.`);
    } else if (typeof window !== "undefined") {
      window.location.assign(url);
    }
  } catch (error) {
    if (popup && !popup.closed) popup.close();
    const message = error instanceof Error ? error.message : String(error);
    setClientPortalOpenStatus(`Mükellef ekranı açılamadı. ${sessionAuthErrorMessage(message) || message}`);
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
