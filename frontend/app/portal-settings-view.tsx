"use client";

import { Info } from "./portal-shared";
import type { LocalSession, PilotReadinessView } from "./portal-types";

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
    <section className="session-panel" aria-label="GiriÅŸ ve Ã§Ä±kÄ±ÅŸ">
      <div>
        <span>Ofis eriÅŸimi</span>
        <strong>{session ? `${session.userId} / ${roleLabels[session.role]}` : "Oturum yok"}</strong>
        <p>
          {loginStatus ||
            (session?.sessionToken
              ? `Oturum aktif${session.expiresAt ? ` / ${formatDateText(session.expiresAt)}` : ""}.`
              : localFallbackAllowed
                ? "Lokal geliÅŸtirme iÃ§in ÅŸifresiz ofis oturumu aÃ§Ä±labilir."
                : "KullanÄ±cÄ± ÅŸifresiyle giriÅŸ zorunlu.")}
        </p>
      </div>
      <div className="session-controls">
        <input aria-label="KullanÄ±cÄ±" onChange={(event) => setLoginUserId(event.target.value)} value={loginUserId} />
        <input
          aria-label="Åifre"
          onChange={(event) => setLoginPassword(event.target.value)}
          placeholder="KullanÄ±cÄ± ÅŸifresi"
          type="password"
          value={loginPassword}
        />
        <select
          aria-label="Rol"
          disabled={Boolean(lockedRole)}
          onChange={(event) => setLoginRole(event.target.value as "client_user" | "accountant")}
          value={lockedRole ?? loginRole}
        >
          <option value="accountant">MÃ¼ÅŸavir</option>
          <option value="client_user">MÃ¼kellef</option>
        </select>
        <button onClick={onLogin} type="button">GiriÅŸ</button>
        <button className="secondary" onClick={onLogout} type="button">Ã‡Ä±kÄ±ÅŸ</button>
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
  readinessView,
  session,
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
  readinessView: PilotReadinessView;
  session: LocalSession | null;
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
        <Info label="Veri kaynaÄŸÄ±" value={source} />
        <Info label="Oturum" value={session ? `${roleLabels[session.role]} / ${session.userId}` : "Oturum kapalÄ±"} />
        <Info label="Saha kullanÄ±mÄ±" value={readinessView.statusLabel} />
        <Info label="Production" value={readinessView.productionLabel} />
        <Info label="Auth" value={readinessView.authLabel} />
        <Info label="Store" value={readinessView.storeLabel} />
        <Info label="AI" value={readinessView.aiLabel} />
        <Info label="Ã‡Ä±ktÄ±" value={readinessView.exportLabel} />
        <Info label="Lokal veri" value={localFallbackAllowed ? "GeliÅŸtirme ortamÄ±" : "KapalÄ±"} />
        <Info label="Mukellef" value={String(dashboardMetrics.totalClients)} />
        <Info label="Kontrol bekleyen" value={String(dashboardMetrics.pendingReviewDocuments)} />
      </section>
    </section>
  );
}
