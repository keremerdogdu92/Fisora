"use client";

import { useMemo, useState } from "react";
import { canUseLocalPilotFallback } from "./pilot-readiness";
import { LANDING_ROLE_ENTRIES, portalEntryForRole } from "./portal-routes";
import { loginWithPassword, requestPasswordReset, resolveApiBaseUrl } from "./upload-api";

type LandingRole = "accountant" | "client_user";

type LandingEntry = {
  role: LandingRole;
  label: string;
  href: string;
  description: string;
  defaultUserId: string;
  cta: string;
};

type LocalSession = {
  userId: string;
  role: LandingRole;
  sessionToken?: string;
  expiresAt?: string;
};

const SESSION_STORAGE_KEY = "fisora.office.session.v1";

function persistSession(session: LocalSession) {
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export default function RoleGatewayLanding() {
  const entries = LANDING_ROLE_ENTRIES as LandingEntry[];
  const [selectedRole, setSelectedRole] = useState<LandingRole>("accountant");
  const [userId, setUserId] = useState(() => portalEntryForRole("accountant").defaultUserId);
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const [resetMode, setResetMode] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const selectedEntry = useMemo(
    () => portalEntryForRole(selectedRole) as LandingEntry,
    [selectedRole],
  );

  function selectRole(role: LandingRole) {
    const entry = portalEntryForRole(role) as LandingEntry;
    setSelectedRole(role);
    setUserId(entry.defaultUserId);
    setPassword("");
    setStatus("");
    setResetMode(false);
    setResetEmail("");
  }

  async function sendResetLink() {
    const email = resetEmail.trim();
    if (!email) {
      setStatus("Şifre sıfırlama bağlantısı için e-posta adresinizi girin.");
      return;
    }
    setResetBusy(true);
    setStatus("Şifre sıfırlama isteği gönderiliyor.");
    try {
      await requestPasswordReset({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        email,
      });
      setStatus("Hesap bulunursa şifre sıfırlama bağlantısı e-posta adresinize gönderildi.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(`Şifre sıfırlama isteği gönderilemedi. ${message}`);
    } finally {
      setResetBusy(false);
    }
  }

  async function enterPortal() {
    const effectiveUserId = userId.trim() || selectedEntry.defaultUserId;
    if (password.trim()) {
      setStatus("Oturum açılıyor.");
      try {
        const backendSession = await loginWithPassword({
          apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
          userId: effectiveUserId,
          password: password.trim(),
        });
        persistSession({
          userId: backendSession.userId || effectiveUserId,
          role: selectedRole,
          sessionToken: backendSession.sessionToken,
          expiresAt: backendSession.expiresAt,
        });
        window.location.assign(selectedEntry.href);
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setStatus(`Oturum açılamadı. ${message}`);
        return;
      }
    }

    const localFallbackAllowed = canUseLocalPilotFallback({
      pageUrl: typeof window === "undefined" ? "" : window.location.href,
      explicitAllow: process.env.NEXT_PUBLIC_FISORA_ALLOW_LOCAL_FALLBACK === "true",
    });
    if (!localFallbackAllowed) {
      setStatus("Bu ortamda şifresiz giriş kapalı. Kullanıcı şifresi ile girin.");
      return;
    }
    persistSession({ userId: effectiveUserId, role: selectedRole });
    window.location.assign(selectedEntry.href);
  }

  return (
    <main className="landing-shell">
      <header className="landing-header">
        <a className="landing-brand" href="/">
          <span>Fisora</span>
        </a>
      </header>

      <section className="role-gateway">
        <div className="role-copy">
          <span>Muhasebe operasyon çalışma alanı</span>
          <h1>AI ajan destekli fiş taslağı ve müşavir kontrolü</h1>
          <p>
            Belge ayrıştırma, muhasebe motoru, AI ajan önerileri ve müşavir
            kararları aynı çalışma alanında ilerler.
          </p>
        </div>

        <section className="role-entry-panel" aria-label="Rol seçimi ve giriş">
          <div className="role-card-grid">
            {entries.map((entry) => (
              <button
                aria-pressed={selectedRole === entry.role}
                className={selectedRole === entry.role ? "role-card active" : "role-card"}
                key={entry.role}
                onClick={() => selectRole(entry.role)}
                type="button"
              >
                <span>{entry.label}</span>
                <strong>{entry.cta}</strong>
                <small>{entry.description}</small>
              </button>
            ))}
          </div>

          <div className="landing-login">
            <div>
              <span>Seçili giriş</span>
              <strong>{selectedEntry.label}</strong>
            </div>
            <label>
              <span>Kullanıcı</span>
              <input
                aria-label="Kullanıcı"
                onChange={(event) => setUserId(event.target.value)}
                value={userId}
              />
            </label>
            <label>
              <span>Şifre</span>
              <input
                aria-label="Şifre"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Kullanıcı şifresi"
                type="password"
                value={password}
              />
            </label>
            <button className="primary" onClick={enterPortal} type="button">
              {selectedEntry.label}
            </button>
            <button
              className="secondary"
              onClick={() => {
                setResetMode((value) => !value);
                setResetEmail((value) => value || (userId.includes("@") ? userId : ""));
                setStatus("");
              }}
              type="button"
            >
              {resetMode ? "Girişe dön" : "Şifremi unuttum"}
            </button>
            {resetMode ? (
              <div className="landing-login">
                <label>
                  <span>E-posta</span>
                  <input
                    aria-label="Şifre sıfırlama e-postası"
                    autoComplete="email"
                    onChange={(event) => setResetEmail(event.target.value)}
                    placeholder="ornek@firma.com"
                    type="email"
                    value={resetEmail}
                  />
                </label>
                <button className="primary" disabled={resetBusy} onClick={sendResetLink} type="button">
                  {resetBusy ? "Gönderiliyor..." : "Sıfırlama bağlantısı gönder"}
                </button>
              </div>
            ) : null}
            {status ? <p className="decision-status">{status}</p> : null}
          </div>
        </section>
      </section>

      <section className="workflow-strip" aria-label="Portal iş akışı">
        <div>
          <span>01</span>
          <strong>Belge yükle</strong>
        </div>
        <div>
          <span>02</span>
          <strong>AI destekli taslak</strong>
        </div>
        <div>
          <span>03</span>
          <strong>Müşavir onayı</strong>
        </div>
      </section>
    </main>
  );
}
