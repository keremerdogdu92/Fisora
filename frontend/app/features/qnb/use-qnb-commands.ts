import { useEffect, useState } from "react";

import {
  disableQnbConnection,
  fetchQnbConnectionStatus,
  fetchQnbHealth,
  fetchQnbSyncPolicy,
  resolveApiBaseUrl,
  saveQnbConnectionToBackend,
  saveQnbSyncPolicy,
  syncQnbIncomingInvoices,
} from "../../upload-api";
import type { LocalSession, PilotClient } from "../../portal-types";

function pageUrl() {
  return typeof window === "undefined" ? "" : window.location.href;
}

export function useQnbCommands({
  loginUserId,
  refreshBackendPilotData,
  selectedClient,
  session,
}: {
  loginUserId: string;
  refreshBackendPilotData: () => Promise<unknown>;
  selectedClient: PilotClient | undefined;
  session: LocalSession | null;
}) {
  const [qnbConnection, setQnbConnection] = useState({
    baseUrl: "https://erpefaturatest2.qnbesolutions.com.tr/efatura/ws",
    username: "",
    password: "",
    vkn: "",
  });
  const [qnbStatus, setQnbStatus] = useState({ message: "", maskedUsername: "", status: "", environment: "", lastTestedAt: "", lastError: "" });
  const [qnbSyncStartDate, setQnbSyncStartDate] = useState("");
  const [qnbSyncEndDate, setQnbSyncEndDate] = useState("");
  const [qnbSyncMessage, setQnbSyncMessage] = useState("");
  const [qnbPolicy, setQnbPolicy] = useState({ enabled: false, frequencyMinutes: 60, maxDocumentsPerRun: 100, statusReconciliationEnabled: true, message: "" });
  const [qnbHealth, setQnbHealth] = useState({ safeMessage: "", lastSuccessAt: "", lastAttemptAt: "", nextRunAt: "", cursor: "", listedCount: 0, downloadedCount: 0, duplicateCount: 0, failedCount: 0 });

  useEffect(() => {
    setQnbConnection((current) => ({
      ...current,
      vkn: current.vkn || selectedClient?.vkn || selectedClient?.taxId || "",
    }));
  }, [selectedClient?.clientId, selectedClient?.taxId, selectedClient?.vkn]);

  function updateQnbConnection(field: "baseUrl" | "username" | "password" | "vkn", value: string) {
    setQnbConnection((current) => ({ ...current, [field]: value }));
  }

  async function refreshQnbStatus() {
    if (!selectedClient?.clientId) {
      setQnbStatus({ message: "Önce mükellef seçin.", maskedUsername: "", status: "", environment: "", lastTestedAt: "", lastError: "" });
      return;
    }
    setQnbStatus((current) => ({ ...current, message: "QNB bağlantı durumu okunuyor." }));
    try {
      const request = { apiBaseUrl: resolveApiBaseUrl(pageUrl()), clientId: selectedClient.clientId, userId: loginUserId, sessionToken: session?.sessionToken || "" };
      const [payload, policy, health] = await Promise.all([
        fetchQnbConnectionStatus(request), fetchQnbSyncPolicy(request), fetchQnbHealth(request),
      ]);
      setQnbStatus({
        message: payload?.status === "missing" ? "Bu mükellef için QNB bağlantısı yok." : "QNB bağlantı durumu okundu.",
        maskedUsername: String(payload?.username || ""),
        status: String(payload?.status || ""),
        environment: String(payload?.environment || ""), lastTestedAt: String(payload?.last_tested_at || ""), lastError: String(payload?.last_error || ""),
      });
      setQnbConnection((current) => ({ ...current, password: "" }));
      setQnbPolicy({ enabled: Boolean(policy?.enabled), frequencyMinutes: Number(policy?.frequency_minutes || 60), maxDocumentsPerRun: Number(policy?.max_documents_per_run || 100), statusReconciliationEnabled: Boolean(policy?.status_reconciliation_enabled ?? true), message: "" });
      const latest = health?.latest_run || {};
      setQnbHealth({ safeMessage: String(health?.safe_message || ""), lastSuccessAt: String(health?.policy?.last_success_at || ""), lastAttemptAt: String(health?.policy?.last_attempt_at || ""), nextRunAt: String(health?.policy?.next_run_at || ""), cursor: String(health?.cursor || ""), listedCount: Number(latest?.listed_count || 0), downloadedCount: Number(latest?.downloaded_count || 0), duplicateCount: Number(latest?.skipped_duplicate_count || 0), failedCount: Number(latest?.failed_count || 0) });
    } catch (error) {
      setQnbStatus({
        message: `QNB bağlantı durumu okunamadı. ${error instanceof Error ? error.message : String(error)}`,
        maskedUsername: "",
        status: "error", environment: "", lastTestedAt: "", lastError: "",
      });
    }
  }

  async function disableQnb() {
    if (!selectedClient?.clientId) return;
    try {
      const payload = await disableQnbConnection({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()), clientId: selectedClient.clientId,
        userId: loginUserId, sessionToken: session?.sessionToken || "",
      });
      setQnbStatus({ message: "QNB bağlantısı devre dışı bırakıldı.", maskedUsername: String(payload?.username || ""), status: String(payload?.status || "disabled"), environment: String(payload?.environment || ""), lastTestedAt: String(payload?.last_tested_at || ""), lastError: "" });
      setQnbConnection((current) => ({ ...current, password: "" }));
    } catch (error) {
      setQnbStatus({ message: `QNB bağlantısı kapatılamadı. ${error instanceof Error ? error.message : String(error)}`, maskedUsername: "", status: "error", environment: "", lastTestedAt: "", lastError: "" });
    }
  }

  async function saveQnbConnection() {
    if (!selectedClient?.clientId) {
      setQnbStatus({ message: "Önce mükellef seçin.", maskedUsername: "", status: "", environment: "", lastTestedAt: "", lastError: "" });
      return;
    }
    setQnbStatus((current) => ({ ...current, message: "QNB bağlantısı kaydediliyor." }));
    try {
      const payload = await saveQnbConnectionToBackend({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        clientId: selectedClient.clientId,
        userId: loginUserId,
        sessionToken: session?.sessionToken || "",
        connection: qnbConnection,
      });
      setQnbStatus({
        message: payload?.status === "active" ? "QNB bağlantısı aktif." : `QNB bağlantısı kaydedildi: ${String(payload?.status || "")}`,
        maskedUsername: String(payload?.username || ""),
        status: String(payload?.status || ""),
        environment: String(payload?.environment || ""), lastTestedAt: String(payload?.last_tested_at || ""), lastError: String(payload?.last_error || ""),
      });
      setQnbConnection((current) => ({ ...current, password: "" }));
    } catch (error) {
      setQnbStatus({
        message: `QNB bağlantısı kaydedilemedi. ${error instanceof Error ? error.message : String(error)}`,
        maskedUsername: "",
        status: "error", environment: "", lastTestedAt: "", lastError: "",
      });
    }
  }

  async function syncQnbIncoming() {
    if (!selectedClient?.clientId) {
      setQnbSyncMessage("Önce mükellef seçin.");
      return;
    }
    setQnbSyncMessage("QNB gelen e-Fatura listesi alınıyor.");
    try {
      const payload = await syncQnbIncomingInvoices({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        clientId: selectedClient.clientId,
        userId: loginUserId,
        sessionToken: session?.sessionToken || "",
        startDate: qnbSyncStartDate,
        endDate: qnbSyncEndDate,
      });
      setQnbSyncMessage(
        `${Number(payload?.listed_count || 0)} listelendi, ${Number(payload?.downloaded_count || 0)} indirildi, ${Number(payload?.queued_processing_count || 0)} kuyruğa alındı.`,
      );
      await refreshBackendPilotData();
    } catch (error) {
      setQnbSyncMessage(`QNB sync çalışmadı. ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function saveQnbPolicy() {
    if (!selectedClient?.clientId) return;
    try {
      const payload = await saveQnbSyncPolicy({ apiBaseUrl: resolveApiBaseUrl(pageUrl()), clientId: selectedClient.clientId, userId: loginUserId, sessionToken: session?.sessionToken || "", policy: qnbPolicy });
      setQnbPolicy((current) => ({ ...current, enabled: Boolean(payload?.enabled), message: payload?.enabled ? "Otomatik senkronizasyon aktif." : "Otomatik senkronizasyon kapalı." }));
    } catch (error) {
      setQnbPolicy((current) => ({ ...current, message: `Otomatik senkronizasyon kaydedilemedi. ${error instanceof Error ? error.message : String(error)}` }));
    }
  }

  return {
    qnbConnection,
    qnbStatus,
    qnbHealth,
    qnbPolicy: { ...qnbPolicy, set: (patch: Partial<typeof qnbPolicy>) => setQnbPolicy((current) => ({ ...current, ...patch })), save: saveQnbPolicy },
    qnbSyncWindow: {
      startDate: qnbSyncStartDate,
      endDate: qnbSyncEndDate,
      setStartDate: setQnbSyncStartDate,
      setEndDate: setQnbSyncEndDate,
      message: qnbSyncMessage,
    },
    refreshQnbStatus,
    disableQnb,
    saveQnbConnection,
    syncQnbIncoming,
    updateQnbConnection,
  };
}
