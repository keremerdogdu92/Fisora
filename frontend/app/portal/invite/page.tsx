"use client";

import { useState } from "react";
import { acceptPortalInvite, resolveApiBaseUrl, userSafeErrorMessage } from "../../upload-api";

export default function InviteAcceptPage() {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function acceptInvite() {
    if (password.length < 8) {
      setStatus("Şifre en az 8 karakter olmalı.");
      return;
    }
    if (password !== confirmPassword) {
      setStatus("Şifreler eşleşmiyor.");
      return;
    }
    const inviteToken = new URLSearchParams(window.location.search).get("token") || "";
    if (!inviteToken) {
      setStatus("Davet bağlantısı geçersiz.");
      return;
    }
    setBusy(true);
    setStatus("Hesap hazırlanıyor...");
    try {
      await acceptPortalInvite({
        apiBaseUrl: resolveApiBaseUrl(window.location.href),
        inviteToken,
        password,
      });
      setStatus("Hesabınız hazır. Giriş ekranına yönlendiriliyorsunuz.");
      window.setTimeout(() => window.location.assign("/"), 1000);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(userSafeErrorMessage(message, "Davet kabul edilemedi. Yeni bir davet isteyin."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="landing-shell">
      <header className="landing-header">
        <a className="landing-brand" href="/"><span>Fisora</span></a>
      </header>
      <section className="role-gateway">
        <div className="role-copy">
          <span>Ofis erişimi</span>
          <h1>Fisora hesabınızı oluşturun</h1>
          <p>Bu davet tek kullanımlıktır ve 48 saat geçerlidir.</p>
        </div>
        <section className="role-entry-panel" aria-label="Davet kabulü">
          <div className="landing-login">
            <label>
              <span>Şifre</span>
              <input aria-label="Şifre" autoComplete="new-password" onChange={(event) => setPassword(event.target.value)} type="password" value={password} />
            </label>
            <label>
              <span>Şifre tekrar</span>
              <input aria-label="Şifre tekrar" autoComplete="new-password" onChange={(event) => setConfirmPassword(event.target.value)} type="password" value={confirmPassword} />
            </label>
            <button className="primary" disabled={busy} onClick={acceptInvite} type="button">
              {busy ? "Hazırlanıyor..." : "Hesabı oluştur"}
            </button>
            <a className="secondary" href="/">Giriş ekranına dön</a>
            {status ? <p className="decision-status">{status}</p> : null}
          </div>
        </section>
      </section>
    </main>
  );
}
