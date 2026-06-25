"use client";

import { useEffect, useState } from "react";
import type { LocalSession, NewClientDraft, PilotClient } from "../../portal-types";
import {
  createInviteForSelectedClientAction,
  createNewClientAction,
  deleteSelectedClientDocumentsAction,
  emptyNewClientDraft,
  parseNewClientChartAccountsAction,
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
  const [newClientTaxCertificateFile, setNewClientTaxCertificateFile] = useState<File | null>(null);
  const [newClientTaxCertificateInputKey, setNewClientTaxCertificateInputKey] = useState(0);
  const [newClientStatus, setNewClientStatus] = useState("");
  const [chartUploadStatus, setChartUploadStatus] = useState("");
  const [inviteStatus, setInviteStatus] = useState("");
  const [portalPassword, setPortalPasswordDraft] = useState("");
  const [portalUserIdDraft, setPortalUserIdDraft] = useState("");
  const [portalPasswordStatus, setPortalPasswordStatus] = useState("");
  const [clientDocumentDeleteConfirmed, setClientDocumentDeleteConfirmed] = useState(false);
  const [clientDocumentDeleteStatus, setClientDocumentDeleteStatus] = useState("");
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
      newClientDraft,
      newClientTaxCertificateFile,
      portalPassword,
      refreshBackendPilotData,
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
      setNewClientDraft,
      setNewClientStatus,
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
    createInviteForSelectedClient,
    createNewClient,
    deleteSelectedClientDocuments,
    inviteStatus,
    newClientDraft,
    newClientStatus,
    newClientTaxCertificateFile,
    newClientTaxCertificateInputKey,
    parseNewClientChartAccounts,
    portalPassword,
    portalPasswordStatus,
    portalUserIdDraft,
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
  };
}
