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
            (session?.sessionToken
              ? `Oturum aktif${session.expiresAt ? ` / ${formatDateText(session.expiresAt)}` : ""}.`
              : localFallbackAllowed
                ? "Lokal geliştirme için şifresiz ofis oturumu açılabilir."
                : "Kullanıcı şifresiyle giriş zorunlu.")}
        </p>
      </div>
      <div className="session-controls">
        <input aria-label="Kullanıcı" onChange={(event) => setLoginUserId(event.target.value)} value={loginUserId} />
        <input
          aria-label="Şifre"
          onChange={(event) => setLoginPassword(event.target.value)}
          placeholder="Kullanıcı şifresi"
          type="password"
          value={loginPassword}
        />
        <select
          aria-label="Rol"
          disabled={Boolean(lockedRole)}
          onChange={(event) => setLoginRole(event.target.value as "client_user" | "accountant")}
          value={lockedRole ?? loginRole}
        >
          <option value="accountant">Müşavir</option>
          <option value="client_user">Mükellef</option>
        </select>
        <button onClick={onLogin} type="button">Giriş</button>
        <button className="secondary" onClick={onLogout} type="button">Çıkış</button>
      </div>
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
  qnbStatus: {
    message: string;
    maskedUsername: string;
    status: string;
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
      <section className="panel settings-grid">
        <Info label="Veri kaynağı" value={source} />
        <Info label="Oturum" value={session ? `${roleLabels[session.role]} / ${session.userId}` : "Oturum kapalı"} />
        <Info label="Saha kullanımı" value={readinessView.statusLabel} />
        <Info label="Production" value={readinessView.productionLabel} />
        <Info label="Auth" value={readinessView.authLabel} />
        <Info label="Store" value={readinessView.storeLabel} />
        <Info label="AI" value={readinessView.aiLabel} />
        <Info label="Çıktı" value={readinessView.exportLabel} />
        <Info label="Lokal veri" value={localFallbackAllowed ? "Geliştirme ortamı" : "Kapalı"} />
        <Info label="Mükellef" value={String(dashboardMetrics.totalClients)} />
        <Info label="Kontrol bekleyen" value={String(dashboardMetrics.pendingReviewDocuments)} />
      </section>
      {session?.role === "accountant" ? (
        <section className="panel settings-card" aria-label="QNB gelen e-Fatura">
          <div>
            <span>QNB gelen e-Fatura</span>
            <strong>{selectedClient ? selectedClient.clientName : "Mükellef seçilmedi"}</strong>
            <p>{qnbStatus.message || (qnbStatus.status ? `Bağlantı durumu: ${qnbStatus.status}` : "Gelen e-Fatura UBL belgelerini mükellefin belge kuyruğuna alır.")}</p>
          </div>
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
            <Info label="Sync" value={qnbSyncWindow.message || "Henüz çalışmadı"} />
          </div>
        </section>
      ) : null}
      {session?.role === "accountant" ? (
        <section className="panel settings-danger-panel" aria-label="Test verisi temizleme">
          <div>
            <span>Test verisi</span>
            <strong>Mükellefleri ve yüklenen dosyaları temizle</strong>
            <p>{resetStatus || "Müşavir hesabı ve şifresi korunur; mükellefler, dosyalar, işler ve çıktılar silinir."}</p>
          </div>
          <div className="session-controls">
            <input
              aria-label="Temizleme onayı"
              onChange={(event) => setResetConfirmation(event.target.value)}
              placeholder="TEMIZLE"
              value={resetConfirmation}
            />
            <button
              className="danger-action"
              disabled={resetConfirmation.trim() !== "TEMIZLE"}
              onClick={onResetTestData}
              type="button"
            >
              Temizle
            </button>
          </div>
        </section>
      ) : null}
    </section>
  );
}
