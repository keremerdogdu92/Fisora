"use client";

import { Info } from "./portal-shared";
import type { LocalSession, PilotClient, PilotReadinessView } from "./portal-types";

const roleLabels: Record<LocalSession["role"], string> = {
  accountant: "Müşavir",
  client_user: "Mükellef",
};

function formatDateText(value: string) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("tr-TR");
}

function SessionPanel({
  loginPassword,
  loginRole,
  loginStatus,
  loginUserId,
  lockedRole,
  localFallbackAllowed,
  onLogin,
  onLogout,
  session,
  setLoginPassword,
  setLoginRole,
  setLoginUserId,
}: {
  loginPassword: string;
  loginRole: "client_user" | "accountant";
  loginStatus: string;
  loginUserId: string;
  lockedRole?: "client_user" | "accountant";
  localFallbackAllowed: boolean;
  onLogin: () => void | Promise<void>;
  onLogout: () => void;
  session: LocalSession | null;
  setLoginPassword: (value: string) => void;
  setLoginRole: (value: "client_user" | "accountant") => void;
  setLoginUserId: (value: string) => void;
}) {
  return (
    <section className="session-panel" aria-label="Giriş ve çıkış">
      <div>
        <span>Ofis erişimi</span>
        <strong>{session ? `${session.userId} / ${roleLabels[session.role]}` : "Oturum yok"}</strong>
        <p>
          {loginStatus ||
            (session
              ? session.sessionToken
                ? `Oturum aktif${session.expiresAt ? ` / ${formatDateText(session.expiresAt)}` : ""}.`
                : "Ofis oturumu aktif."
              : localFallbackAllowed
                ? "Şifresiz yerel oturum kullanılabilir."
                : "Kullanıcı şifresiyle giriş zorunlu.")}
        </p>
      </div>
      {session ? (
        <div className="session-controls session-controls-compact">
          <button className="secondary" onClick={onLogout} type="button">Çıkış yap</button>
        </div>
      ) : (
        <div className="session-controls">
          <input aria-label="Kullanıcı" onChange={(event) => setLoginUserId(event.target.value)} value={loginUserId} />
          <input aria-label="Şifre" onChange={(event) => setLoginPassword(event.target.value)} placeholder="Kullanıcı şifresi" type="password" value={loginPassword} />
          <select aria-label="Rol" disabled={Boolean(lockedRole)} onChange={(event) => setLoginRole(event.target.value as "client_user" | "accountant")} value={lockedRole ?? loginRole}>
            <option value="accountant">Müşavir</option><option value="client_user">Mükellef</option>
          </select>
          <button onClick={onLogin} type="button">Giriş</button>
        </div>
      )}
    </section>
  );
}

export function SettingsView({
  dashboardMetrics,
  loginPassword,
  loginRole,
  loginStatus,
  loginUserId,
  lockedRole,
  localFallbackAllowed,
  onLogin,
  onLogout,
  onQnbConnectionChange,
  onQnbDisable,
  onQnbRefreshStatus,
  onQnbSaveConnection,
  onQnbSyncIncoming,
  onResetTestData,
  qnbConnection,
  qnbHealth,
  qnbPolicy,
  qnbStatus,
  qnbSyncWindow,
  selectedClient,
  readinessView,
  resetConfirmation,
  resetStatus,
  session,
  setResetConfirmation,
  setLoginPassword,
  setLoginRole,
  setLoginUserId,
  source,
}: {
  dashboardMetrics: {
    totalClients: number;
    uploadedClients: number;
    notUploadedClients: number;
    pendingReviewDocuments: number;
    exportReadyDocuments: number;
    openCancellationRequests: number;
  };
  loginPassword: string;
  loginRole: "client_user" | "accountant";
  loginStatus: string;
  loginUserId: string;
  lockedRole?: "client_user" | "accountant";
  localFallbackAllowed: boolean;
  onLogin: () => void | Promise<void>;
  onLogout: () => void;
  onQnbConnectionChange: (field: "baseUrl" | "username" | "password" | "vkn", value: string) => void;
  onQnbDisable: () => void | Promise<void>;
  onQnbRefreshStatus: () => void | Promise<void>;
  onQnbSaveConnection: () => void | Promise<void>;
  onQnbSyncIncoming: () => void | Promise<void>;
  onResetTestData: () => void | Promise<void>;
  qnbConnection: {
    baseUrl: string;
    username: string;
    password: string;
    vkn: string;
  };
  qnbHealth: {
    safeMessage: string; lastSuccessAt: string; lastAttemptAt: string; nextRunAt: string; cursor: string;
    listedCount: number; downloadedCount: number; duplicateCount: number; failedCount: number;
  };
  qnbPolicy: {
    enabled: boolean;
    frequencyMinutes: number;
    maxDocumentsPerRun: number;
    statusReconciliationEnabled: boolean;
    message: string;
    set: (patch: Record<string, unknown>) => void;
    save: () => void | Promise<void>;
  };
  qnbStatus: {
    message: string;
    maskedUsername: string;
    status: string;
    environment: string;
    lastTestedAt: string;
    lastError: string;
  };
  qnbSyncWindow: {
    startDate: string;
    endDate: string;
    setStartDate: (value: string) => void;
    setEndDate: (value: string) => void;
    message: string;
  };
  selectedClient: PilotClient | undefined;
  readinessView: PilotReadinessView;
  resetConfirmation: string;
  resetStatus: string;
  session: LocalSession | null;
  setResetConfirmation: (value: string) => void;
  setLoginPassword: (value: string) => void;
  setLoginRole: (value: "client_user" | "accountant") => void;
  setLoginUserId: (value: string) => void;
  source: string;
}) {
  return (
    <section className="settings-page">
      <SessionPanel
        loginPassword={loginPassword}
        loginRole={loginRole}
        loginStatus={loginStatus}
        loginUserId={loginUserId}
        lockedRole={lockedRole}
        localFallbackAllowed={localFallbackAllowed}
        onLogin={onLogin}
        onLogout={onLogout}
        session={session}
        setLoginPassword={setLoginPassword}
        setLoginRole={setLoginRole}
        setLoginUserId={setLoginUserId}
      />
      <section className="panel settings-card settings-overview-card">
        <div className="section-heading">
          <span>Ofis ayarları</span><strong>Genel görünüm</strong>
        </div>
        <div className="settings-grid">
          <Info label="Hesap" value={session ? `${roleLabels[session.role]} / ${session.userId}` : "Oturum kapalı"} />
          <Info label="Mükellef" value={String(dashboardMetrics.totalClients)} />
          <Info label="Kontrol bekleyen" value={String(dashboardMetrics.pendingReviewDocuments)} />
          <Info label="Çıktı" value={readinessView.exportLabel} />
        </div>
      </section>
      {session?.role === "accountant" ? (
        <section className="panel settings-card" aria-label="QNB gelen e-Fatura">
          <div className="section-heading">
            <span>Entegrasyonlar · QNB e-Fatura</span>
            <strong>{selectedClient ? selectedClient.clientName : "Mükellef seçilmedi"}</strong>
          </div>
          <p>{qnbStatus.message || (qnbStatus.status ? `Bağlantı durumu: ${qnbStatus.status}` : "Gelen e-Fatura UBL belgelerini mükellefin belge kuyruğuna alır.")}</p>
          <div className="qnb-settings-form">
            <input
              aria-label="QNB servis adresi"
              onChange={(event) => onQnbConnectionChange("baseUrl", event.target.value)}
              placeholder="QNB servis adresi"
              value={qnbConnection.baseUrl}
            />
            <input
              aria-label="QNB kullanıcı adı"
              onChange={(event) => onQnbConnectionChange("username", event.target.value)}
              placeholder="QNB kullanıcı adı"
              value={qnbConnection.username}
            />
            <input
              aria-label="QNB şifre"
              onChange={(event) => onQnbConnectionChange("password", event.target.value)}
              placeholder="QNB şifre"
              type="password"
              value={qnbConnection.password}
            />
            <input
              aria-label="Mükellef VKN"
              onChange={(event) => onQnbConnectionChange("vkn", event.target.value)}
              placeholder="Mükellef VKN"
              value={qnbConnection.vkn}
            />
          </div>
          <div className="session-controls">
            <button disabled={!selectedClient} onClick={onQnbSaveConnection} type="button">Bağlantıyı kaydet</button>
            <button className="secondary" disabled={!selectedClient} onClick={onQnbRefreshStatus} type="button">Durumu yenile</button>
            <button className="secondary" disabled={!selectedClient || qnbStatus.status === "disabled"} onClick={onQnbDisable} type="button">Bağlantıyı kapat</button>
          </div>
          <div className="qnb-sync-row">
            <input
              aria-label="QNB başlangıç tarihi"
              onChange={(event) => qnbSyncWindow.setStartDate(event.target.value)}
              type="date"
              value={qnbSyncWindow.startDate}
            />
            <input
              aria-label="QNB bitiş tarihi"
              onChange={(event) => qnbSyncWindow.setEndDate(event.target.value)}
              type="date"
              value={qnbSyncWindow.endDate}
            />
            <button disabled={!selectedClient} onClick={onQnbSyncIncoming} type="button">Gelenleri al</button>
          </div>
          <div className="settings-grid">
            <Info label="Kullanıcı" value={qnbStatus.maskedUsername || "-"} />
            <Info label="Ortam" value={qnbStatus.environment === "production" ? "Canlı" : qnbStatus.environment === "test" ? "Test" : "-"} />
            <Info label="Son bağlantı testi" value={qnbStatus.lastTestedAt || "-"} />
            <Info label="Bağlantı sonucu" value={qnbStatus.lastError || (qnbStatus.status === "active" ? "Bağlantı başarılı" : "-")} />
            <Info label="Sync" value={qnbSyncWindow.message || "Henüz çalışmadı"} />
          </div>
          <div className="qnb-sync-row">
            <label><input checked={qnbPolicy.enabled} onChange={(event) => qnbPolicy.set({ enabled: event.target.checked })} type="checkbox" /> Otomatik al</label>
            <select aria-label="QNB senkronizasyon sıklığı" onChange={(event) => qnbPolicy.set({ frequencyMinutes: Number(event.target.value) })} value={qnbPolicy.frequencyMinutes}>
              <option value={15}>15 dakikada</option><option value={30}>30 dakikada</option><option value={60}>Saatte bir</option><option value={240}>4 saatte bir</option>
            </select>
            <button className="secondary" disabled={!selectedClient || qnbStatus.status !== "active"} onClick={qnbPolicy.save} type="button">Otomatik akışı kaydet</button>
          </div>
          {qnbPolicy.message ? <p>{qnbPolicy.message}</p> : null}
          <div className="settings-grid" aria-label="QNB senkronizasyon sağlığı">
            <Info label="Akış" value={qnbHealth.safeMessage || "Henüz otomatik çalışma yok"} />
            <Info label="Son başarılı" value={qnbHealth.lastSuccessAt || "-"} />
            <Info label="Son deneme" value={qnbHealth.lastAttemptAt || "-"} />
            <Info label="Sonraki çalışma" value={qnbHealth.nextRunAt || "-"} />
            <Info label="Son sonuç" value={`${qnbHealth.listedCount} listelendi / ${qnbHealth.downloadedCount} alındı / ${qnbHealth.duplicateCount} tekrar / ${qnbHealth.failedCount} hata`} />
          </div>
        </section>
      ) : null}
    </section>
  );
}
