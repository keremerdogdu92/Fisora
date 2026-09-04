// File: frontend/app/page.tsx
// Summary: Renders the shared Fisora role gateway with production authentication and the portal-next visual language.
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
    <main className="landing-shell fisora-gateway">
      <header className="landing-header">
        <a className="landing-brand" href="/">
          <span className="gateway-brand-mark">F</span>
          <span className="gateway-brand-copy">
            <strong>Fisora</strong>
            <small>Mali müşavir çalışma sistemi</small>
          </span>
        </a>
      </header>

      <section className="role-gateway">
        <div className="role-copy">
          <span className="gateway-kicker">Mali müşavir çalışma sistemi</span>
          <h1>Belgelerden fişe, tek çalışma alanında.</h1>
          <p>
            Fisora belgeleri okur, muhasebe fişi taslağını hazırlar ve kontrolü
            müşavirin elinde tutar. Günlük iş, kaynak belge ve fiş aynı akışta ilerler.
          </p>
          <div className="gateway-feature-list" aria-label="Fisora çalışma akışı">
            <div><span>01</span><strong>Belgeyi oku</strong><small>PDF ve HTML kaynaklarını güvenli biçimde işle.</small></div>
            <div><span>02</span><strong>Fişi hazırla</strong><small>Kaynağı gösterilebilen muhasebe taslağı oluştur.</small></div>
            <div><span>03</span><strong>Kontrol et</strong><small>İstisnayı incele, onayla ve çıktıya taşı.</small></div>
          </div>
        </div>

        <section className="role-entry-panel" aria-label="Rol seçimi ve giriş">
          <div className="gateway-login-heading">
            <span>Güvenli erişim</span>
            <h2>Fisora'ya giriş yap</h2>
            <p>Çalışma alanınızı seçin ve hesabınızla devam edin.</p>
          </div>
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
          <strong>Belgeyi al</strong>
        </div>
        <div>
          <span>02</span>
          <strong>Fişi hazırla</strong>
        </div>
        <div>
          <span>03</span>
          <strong>Kontrol et ve aktar</strong>
        </div>
      </section>
    </main>
  );
}
