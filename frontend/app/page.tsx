// File: frontend/app/page.tsx
// Summary: Renders the shared Fisora split-screen login gateway with production authentication, password reset, and opt-in persistent sessions.
"use client";

import { useMemo, useState } from "react";
import { canUseLocalPilotFallback } from "./pilot-readiness";
import { LANDING_ROLE_ENTRIES, portalEntryForRole } from "./portal-routes";
import { persistSession } from "./portal-session";
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

const STANDARD_SESSION_TTL_HOURS = 12;
const REMEMBERED_SESSION_TTL_HOURS = 30 * 24;

export default function RoleGatewayLanding() {
  const entries = LANDING_ROLE_ENTRIES as LandingEntry[];
  const [selectedRole, setSelectedRole] = useState<LandingRole>("accountant");
  const [userId, setUserId] = useState(() => portalEntryForRole("accountant").defaultUserId);
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
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
          ttlHours: rememberMe ? REMEMBERED_SESSION_TTL_HOURS : STANDARD_SESSION_TTL_HOURS,
        });

        persistSession({
          userId: backendSession.userId || effectiveUserId,
          role: selectedRole,
          sessionToken: backendSession.sessionToken,
          expiresAt: backendSession.expiresAt,
          storageScope: rememberMe ? "local" : "tab",
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

    persistSession({
      userId: effectiveUserId,
      role: selectedRole,
      storageScope: rememberMe ? "local" : "tab",
    });
    window.location.assign(selectedEntry.href);
  }

  return (
    <main className="landing-shell fisora-gateway fisora-gateway-split">
      <section className="gateway-identity-panel" aria-label="Fisora">
        <a className="landing-brand" href="/">
          <span className="gateway-brand-mark">F</span>
          <span className="gateway-brand-copy">
            <strong>Fisora</strong>
            <small>Mali müşavir çalışma sistemi</small>
          </span>
        </a>

        <div className="role-copy">
          <h1>Akıllı ve öğrenen bir yardımcıyla günlük muhasebe işi daha net.</h1>
          <p>
            Fisora, yapay zeka desteğini kararın yerine geçmek için değil, belge okuma ve
            taslak hazırlama sürecini kolaylaştırmak için kullanır. Sistem, zaman içinde
            öğrenilen örnekleri ve kullanıcı tercihlerini daha iyi anlayarak iş yükünü hafifletir.
          </p>
        </div>

        <div className="gateway-identity-foot">Fisora</div>
      </section>

      <section className="gateway-auth-shell">
        <section className="role-entry-panel" aria-label="Rol seçimi ve giriş">
          <div className="gateway-login-heading">
            <span>Güvenli erişim</span>
            <h2>Fisora&apos;ya giriş yap</h2>
            <p>Çalışma alanınızı seçin ve hesabınızla devam edin.</p>
          </div>

          <div className="role-card-grid" aria-label="Çalışma alanı seçimi">
            {entries.map((entry) => (
              <button
                aria-pressed={selectedRole === entry.role}
                className={selectedRole === entry.role ? "role-card active" : "role-card"}
                key={entry.role}
                onClick={() => selectRole(entry.role)}
                type="button"
              >
                <strong>{entry.label}</strong>
              </button>
            ))}
          </div>

          <div className="landing-login">
            <div className="selected-entry">
              <span>Seçili giriş</span>
              <strong>{selectedEntry.label}</strong>
            </div>

            <label>
              <span>Kullanıcı</span>
              <input
                aria-label="Kullanıcı"
                autoComplete="username"
                onChange={(event) => setUserId(event.target.value)}
                value={userId}
              />
            </label>

            <label>
              <span>Şifre</span>
              <input
                aria-label="Şifre"
                autoComplete="current-password"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Kullanıcı şifresi"
                type="password"
                value={password}
              />
            </label>

            <label className="remember-session">
              <input
                checked={rememberMe}
                onChange={(event) => setRememberMe(event.target.checked)}
                type="checkbox"
              />
              <span>
                <strong>Beni hatırla</strong>
                <small>Bu cihazda 30 gün oturum açık kalsın.</small>
              </span>
            </label>

            <button className="primary" onClick={enterPortal} type="button">
              Çalışma alanına gir
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
              <div className="landing-login reset-login">
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
    </main>
  );
}
