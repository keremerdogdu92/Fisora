"use client";

import { useState } from "react";
import { confirmPasswordReset, resolveApiBaseUrl } from "../../upload-api";

export default function PasswordResetPage() {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function submitReset() {
    if (password.length < 8) {
      setStatus("Şifre en az 8 karakter olmalı.");
      return;
    }
    if (password !== confirmPassword) {
      setStatus("Şifreler eşleşmiyor.");
      return;
    }
    const resetToken = new URLSearchParams(window.location.search).get("token") || "";
    if (!resetToken) {
      setStatus("Şifre sıfırlama bağlantısı geçersiz.");
      return;
    }
    setBusy(true);
    setStatus("Şifre güncelleniyor.");
    try {
      await confirmPasswordReset({
        apiBaseUrl: resolveApiBaseUrl(window.location.href),
        resetToken,
        password,
      });
      setStatus("Şifreniz güncellendi. Giriş ekranına yönlendiriliyorsunuz.");
      window.setTimeout(() => window.location.assign("/"), 1000);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(`Şifre güncellenemedi. ${message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="landing-shell">
      <header className="landing-header">
        <a className="landing-brand" href="/">
          <span>Fisero</span>
        </a>
      </header>
      <section className="role-gateway">
        <div className="role-copy">
          <span>Hesap güvenliği</span>
          <h1>Yeni şifrenizi belirleyin</h1>
          <p>Bu bağlantı tek kullanımlıktır ve kısa süre sonra geçersiz olur.</p>
        </div>
        <section className="role-entry-panel" aria-label="Şifre sıfırlama">
          <div className="landing-login">
            <label>
              <span>Yeni şifre</span>
              <input
                aria-label="Yeni şifre"
                autoComplete="new-password"
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                value={password}
              />
            </label>
            <label>
              <span>Yeni şifre tekrar</span>
              <input
                aria-label="Yeni şifre tekrar"
                autoComplete="new-password"
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                value={confirmPassword}
              />
            </label>
            <button className="primary" disabled={busy} onClick={submitReset} type="button">
              {busy ? "Güncelleniyor..." : "Şifreyi güncelle"}
            </button>
            <a className="secondary" href="/">
              Giriş ekranına dön
            </a>
            {status ? <p className="decision-status">{status}</p> : null}
          </div>
        </section>
      </section>
    </main>
  );
}
