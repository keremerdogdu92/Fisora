import type { Dispatch, SetStateAction } from "react";
import {
  buildClientOnboardingPackagePayload,
  createClientOnboardingPackage,
  createPortalInvite,
  parseTaxCertificateFromBackend,
  resolveApiBaseUrl,
  setPortalPassword as setBackendPortalPassword,
  uploadChartAccountsToBackend,
  uploadTaxCertificateToBackend,
} from "./upload-api";
import type { LocalSession, NewClientDraft, PilotClient } from "./portal-types";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export function emptyNewClientDraft(): NewClientDraft {
  return {
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
  };
}

export async function createNewClientAction({
  loginUserId,
  newClientDraft,
  newClientTaxCertificateFile,
  refreshBackendPilotData,
  session,
  setNewClientDraft,
  setNewClientStatus,
  setNewClientTaxCertificateFile,
  setNewClientTaxCertificateInputKey,
  setSelectedClientId,
}: {
  loginUserId: string;
  newClientDraft: NewClientDraft;
  newClientTaxCertificateFile: File | null;
  refreshBackendPilotData: () => Promise<boolean>;
  session: LocalSession | null;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientStatus: (status: string) => void;
  setNewClientTaxCertificateFile: (file: File | null) => void;
  setNewClientTaxCertificateInputKey: Dispatch<SetStateAction<number>>;
  setSelectedClientId: (clientId: string) => void;
}) {
  if (!newClientDraft.title.trim()) {
    setNewClientStatus("Mukellef adi gerekli.");
    return;
  }
  const payload = buildClientOnboardingPackagePayload(newClientDraft);
  const taxCertificateFile = newClientTaxCertificateFile;
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientStatus(taxCertificateFile ? "Mukellef kaydediliyor, vergi levhasi yuklenecek." : "Mukellef kaydediliyor.");
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
      setNewClientStatus("Mukellef kaydedildi. Vergi levhasi yukleniyor.");
      try {
        await uploadTaxCertificateToBackend({
          apiBaseUrl,
          clientId: payload.client.client_id,
          userId: actingUserId,
          uploadedBy: actingUserId,
          sessionToken: session?.sessionToken,
          file: taxCertificateFile,
        });
        certificateStatus = " Vergi levhasi yuklendi.";
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        certificateStatus = ` Vergi levhasi yuklenemedi: ${message}`;
      }
    }
    setNewClientDraft(emptyNewClientDraft());
    setNewClientTaxCertificateFile(null);
    setNewClientTaxCertificateInputKey((current) => current + 1);
    setNewClientStatus(`${payload.client.title} eklendi.${certificateStatus}`);
    await refreshBackendPilotData();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setNewClientStatus(`Mukellef kaydedilemedi. ${message}`);
  }
}

export async function selectNewClientTaxCertificateAction({
  file,
  loginUserId,
  session,
  setNewClientDraft,
  setNewClientStatus,
  setNewClientTaxCertificateFile,
}: {
  file: File | null;
  loginUserId: string;
  session: LocalSession | null;
  setNewClientDraft: Dispatch<SetStateAction<NewClientDraft>>;
  setNewClientStatus: (status: string) => void;
  setNewClientTaxCertificateFile: (file: File | null) => void;
}) {
  setNewClientTaxCertificateFile(file);
  if (!file) return;
  const apiBaseUrl = resolveApiBaseUrl(pageUrl());
  const actingUserId = session?.userId || loginUserId.trim() || "mali-musavir";
  setNewClientStatus(`${file.name} vergi levhasi okunuyor.`);
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
      ? `Vergi levhasi okundu: ${filledFields.join(", ")}${confidence ? ` / guven ${confidence}` : ""}.`
      : "Vergi levhasindan alan okunamadi; elle kayit yapabilirsiniz.";
    setNewClientStatus(profileSummary ? `${note} ${profileSummary}` : note);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setNewClientStatus(`Vergi levhasi okunamadi. Elle devam edebilirsiniz. ${message}`);
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
  setChartUploadStatus(`${file.name} hesap plani import ediliyor...`);
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
    setChartUploadStatus(`Hesap plani importu tamamlanamadi. ${message}`);
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
  setInviteStatus(`${userId} icin davet tokeni hazirlaniyor...`);
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
  setPortalPasswordStatus(`${userId} icin sifre kuruluyor...`);
  try {
    const result = await setBackendPortalPassword({
      apiBaseUrl: resolveApiBaseUrl(pageUrl()),
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
