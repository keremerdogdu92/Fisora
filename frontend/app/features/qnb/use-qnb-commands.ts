import { useEffect, useState } from "react";

import {
  disableQnbConnection,
  fetchQnbConnectionStatus,
  resolveApiBaseUrl,
  saveQnbConnectionToBackend,
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
  const [qnbStatus, setQnbStatus] = useState({ message: "", maskedUsername: "", status: "" });
  const [qnbSyncStartDate, setQnbSyncStartDate] = useState("");
  const [qnbSyncEndDate, setQnbSyncEndDate] = useState("");
  const [qnbSyncMessage, setQnbSyncMessage] = useState("");

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
      setQnbStatus({ message: "Önce mükellef seçin.", maskedUsername: "", status: "" });
      return;
    }
    setQnbStatus((current) => ({ ...current, message: "QNB bağlantı durumu okunuyor." }));
    try {
      const payload = await fetchQnbConnectionStatus({
        apiBaseUrl: resolveApiBaseUrl(pageUrl()),
        clientId: selectedClient.clientId,
        userId: loginUserId,
        sessionToken: session?.sessionToken || "",
      });
      setQnbStatus({
        message: payload?.status === "missing" ? "Bu mükellef için QNB bağlantısı yok." : "QNB bağlantı durumu okundu.",
        maskedUsername: String(payload?.username || ""),
        status: String(payload?.status || ""),
      });
      setQnbConnection((current) => ({ ...current, password: "" }));
    } catch (error) {
      setQnbStatus({
        message: `QNB bağlantı durumu okunamadı. ${error instanceof Error ? error.message : String(error)}`,
        maskedUsername: "",
        status: "error",
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
      setQnbStatus({ message: "QNB bağlantısı devre dışı bırakıldı.", maskedUsername: String(payload?.username || ""), status: String(payload?.status || "disabled") });
      setQnbConnection((current) => ({ ...current, password: "" }));
    } catch (error) {
      setQnbStatus({ message: `QNB bağlantısı kapatılamadı. ${error instanceof Error ? error.message : String(error)}`, maskedUsername: "", status: "error" });
    }
  }

  async function saveQnbConnection() {
    if (!selectedClient?.clientId) {
      setQnbStatus({ message: "Önce mükellef seçin.", maskedUsername: "", status: "" });
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
      });
      setQnbConnection((current) => ({ ...current, password: "" }));
    } catch (error) {
      setQnbStatus({
        message: `QNB bağlantısı kaydedilemedi. ${error instanceof Error ? error.message : String(error)}`,
        maskedUsername: "",
        status: "error",
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

  return {
    qnbConnection,
    qnbStatus,
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
