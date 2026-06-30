"use client";

import { useEffect, useState } from "react";
import type { LocalSession, NewClientDraft, PilotClient } from "../../portal-types";
import {
  createInviteForSelectedClientAction,
  createNewClientAction,
  deleteSelectedClientDocumentsAction,
  emptyNewClientDraft,
  parseNewClientChartAccountsAction,
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
  const [newClientNaceResearchWarningAccepted, setNewClientNaceResearchWarningAccepted] = useState(false);
  const [chartUploadStatus, setChartUploadStatus] = useState("");
  const [inviteStatus, setInviteStatus] = useState("");
  const [portalPassword, setPortalPasswordDraft] = useState("");
  const [portalUserIdDraft, setPortalUserIdDraft] = useState("");
  const [portalPasswordStatus, setPortalPasswordStatus] = useState("");
  const [clientDocumentDeleteConfirmed, setClientDocumentDeleteConfirmed] = useState(false);
  const [clientDocumentDeleteStatus, setClientDocumentDeleteStatus] = useState("");
  const [clientReprocessStatus, setClientReprocessStatus] = useState("");
  const [selectedClientDocumentRefs, setSelectedClientDocumentRefs] = useState<string[]>([]);

  useEffect(() => {
    setPortalUserIdDraft(selectedClient?.portalUserId ?? "");
    setSelectedClientDocumentRefs([]);
    setClientDocumentDeleteConfirmed(false);
    setClientDocumentDeleteStatus("");
  }, [selectedClient?.clientId, selectedClient?.portalUserId]);

  const createNewClient = () => {
    void createNewClientAction({
      loginUserId,
      newClientChartAccountsFile,
      newClientDraft,
      newClientNaceResearchPending,
      newClientNaceResearchProfile,
      newClientNaceResearchWarningAccepted,
      newClientTaxCertificateFile,
      portalPassword,
      refreshBackendPilotData,
      session,
      setNewClientDraft,
      setNewClientChartAccountsFile,
      setNewClientNaceResearchProfile,
      setNewClientNaceResearchStatus,
      setNewClientNaceResearchWarningAccepted,
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
      setNewClientNaceResearchPending,
      setNewClientNaceResearchProfile,
      setNewClientNaceResearchStatus,
      setNewClientStatus,
      setNewClientTaxCertificateFile,
      setNewClientTaxCertificateParsePending,
      setNewClientTaxCertificateStage,
    });
  };

  const refreshNewClientNaceResearch = () => {
    setNewClientNaceResearchWarningAccepted(false);
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
