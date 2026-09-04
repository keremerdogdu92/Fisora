// File: frontend/app/features/clients/use-client-management-commands.ts
// Summary: Owns client-management UI state and delegates onboarding, portal, and document actions.
"use client";

import { useEffect, useState } from "react";
import type { LocalSession, NewClientDraft, PilotClient } from "../../portal-types";
import {
  createInviteForSelectedClientAction,
  createNewClientAction,
  deleteSelectedClientDocumentsAction,
  emptyNewClientDraft,
  parseNewClientChartAccountsAction,
  openSelectedClientPortalAction,
  refreshNewClientNaceResearchAction,
  reprocessSelectedClientAction,
  selectNewClientTaxCertificateAction,
  setPasswordForSelectedClientAction,
  updatePortalAccessForSelectedClientAction,
  uploadChartAccountsAction,
} from "../../portal-client-actions";

export function useClientManagementCommands({
  loginUserId,
  refreshBackendPilotData,
  selectedClient,
  session,
  setSelectedClientId,
}: {
  loginUserId: string;
  refreshBackendPilotData: () => Promise<boolean>;
  selectedClient?: PilotClient;
  session: LocalSession | null;
  setSelectedClientId: (clientId: string) => void;
}) {
  const [newClientDraft, setNewClientDraft] = useState<NewClientDraft>(() => emptyNewClientDraft());
  const [newClientChartAccountsFile, setNewClientChartAccountsFile] = useState<File | null>(null);
  const [newClientTaxCertificateFile, setNewClientTaxCertificateFile] = useState<File | null>(null);
  const [newClientTaxCertificateInputKey, setNewClientTaxCertificateInputKey] = useState(0);
  const [newClientTaxCertificateParsePending, setNewClientTaxCertificateParsePending] = useState(false);
  const [newClientTaxCertificateStage, setNewClientTaxCertificateStage] = useState("");
  const [newClientStatus, setNewClientStatus] = useState("");
  const [newClientNaceResearchPending, setNewClientNaceResearchPending] = useState(false);
  const [newClientNaceResearchProfile, setNewClientNaceResearchProfile] = useState<Record<string, unknown> | null>(null);
  const [newClientNaceResearchStatus, setNewClientNaceResearchStatus] = useState("");
  const [chartUploadStatus, setChartUploadStatus] = useState("");
  const [inviteStatus, setInviteStatus] = useState("");
  const [portalPassword, setPortalPasswordDraft] = useState("");
  const [portalUserIdDraft, setPortalUserIdDraft] = useState("");
  const [portalPasswordStatus, setPortalPasswordStatus] = useState("");
  const [clientDocumentDeleteConfirmed, setClientDocumentDeleteConfirmed] = useState(false);
  const [clientDocumentDeleteStatus, setClientDocumentDeleteStatus] = useState("");
  const [clientPortalOpenStatus, setClientPortalOpenStatus] = useState("");
  const [clientReprocessStatus, setClientReprocessStatus] = useState("");
  const [selectedClientDocumentRefs, setSelectedClientDocumentRefs] = useState<string[]>([]);

  useEffect(() => {
    setPortalUserIdDraft(selectedClient?.portalUserId ?? "");
    setSelectedClientDocumentRefs([]);
    setClientDocumentDeleteConfirmed(false);
    setClientDocumentDeleteStatus("");
    setClientPortalOpenStatus("");
  }, [selectedClient?.clientId, selectedClient?.portalUserId]);

  const createNewClient = () => {
    void createNewClientAction({
      loginUserId,
      newClientChartAccountsFile,
      newClientDraft,
      newClientTaxCertificateFile,
      refreshBackendPilotData,
      session,
      setNewClientDraft,
      setNewClientChartAccountsFile,
      setNewClientNaceResearchProfile,
      setNewClientNaceResearchStatus,
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
      setNewClientNaceResearchProfile,
      setNewClientNaceResearchStatus,
      setNewClientStatus,
      setNewClientTaxCertificateFile,
      setNewClientTaxCertificateParsePending,
      setNewClientTaxCertificateStage,
    });
  };

  const refreshNewClientNaceResearch = () => {
    void refreshNewClientNaceResearchAction({
      force: true,
      loginUserId,
      newClientDraft,
      session,
      setNewClientDraft,
      setNewClientNaceResearchPending,
      setNewClientNaceResearchProfile,
      setNewClientNaceResearchStatus,
    });
  };

  const uploadChartAccounts = (files: FileList | null) => {
    void uploadChartAccountsAction({
      files,
      loginUserId,
      refreshBackendPilotData,
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
      setNewClientChartAccountsFile,
      setNewClientDraft,
      setNewClientStatus,
    });
  };

  const reprocessSelectedClient = () => {
    void reprocessSelectedClientAction({
      loginUserId,
      refreshBackendPilotData,
      selectedClient,
      session,
      setClientReprocessStatus,
    });
  };

  const createInviteForSelectedClient = () => {
    void createInviteForSelectedClientAction({
      loginUserId,
      portalUserIdDraft,
      refreshBackendPilotData,
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

  const updatePortalAccessForSelectedClient = () => {
    void updatePortalAccessForSelectedClientAction({
      loginUserId,
      portalPassword,
      portalUserIdDraft,
      refreshBackendPilotData,
      selectedClient,
      session,
      setPortalPasswordDraft,
      setPortalPasswordStatus,
    });
  };

  const openSelectedClientPortal = () => {
    void openSelectedClientPortalAction({
      loginUserId,
      selectedClient,
      session,
      setClientPortalOpenStatus,
    });
  };

  const deleteSelectedClientDocuments = () => {
    void deleteSelectedClientDocumentsAction({
      deleteConfirmed: clientDocumentDeleteConfirmed,
      loginUserId,
      refreshBackendPilotData,
      selectedClient,
      selectedDocumentRefs: selectedClientDocumentRefs,
      session,
      setClientDocumentDeleteStatus,
      setSelectedDocumentRefs: setSelectedClientDocumentRefs,
    });
  };

  return {
    chartUploadStatus,
    clientDocumentDeleteConfirmed,
    clientDocumentDeleteStatus,
    clientPortalOpenStatus,
    clientReprocessStatus,
    createInviteForSelectedClient,
    createNewClient,
    deleteSelectedClientDocuments,
    inviteStatus,
    newClientDraft,
    newClientNaceResearchPending,
    newClientNaceResearchProfile,
    newClientNaceResearchStatus,
    newClientStatus,
    newClientTaxCertificateFile,
    newClientTaxCertificateInputKey,
    newClientTaxCertificateParsePending,
    newClientTaxCertificateStage,
    parseNewClientChartAccounts,
    openSelectedClientPortal,
    portalPassword,
    portalPasswordStatus,
    portalUserIdDraft,
    refreshNewClientNaceResearch,
    selectNewClientTaxCertificate,
    selectedClientDocumentRefs,
    setClientDocumentDeleteConfirmed,
    setNewClientDraft,
    setPortalPasswordDraft,
    setPortalUserIdDraft,
    setSelectedClientDocumentRefs,
    setPasswordForSelectedClient,
    reprocessSelectedClient,
    updatePortalAccessForSelectedClient,
    uploadChartAccounts,
  };
}
