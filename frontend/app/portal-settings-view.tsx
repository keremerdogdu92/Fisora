// File: frontend/app/portal-settings-view.tsx
// Summary: Renders office/session settings and QNB integration controls with shared operational timestamp formatting.
"use client";

import { useState } from "react";
import { formatPortalDateTime } from "./portal-formatters";
import { Info } from "./portal-shared";
import type { LocalSession, PilotClient, PilotReadinessView } from "./portal-types";
import { createPortalInvite, fetchAuditHistory, resolveApiBaseUrl, userSafeErrorMessage } from "./upload-api";

const roleLabels: Record<LocalSession["role"], string> = {
  accountant: "Müşavir",
  client_user: "Mükellef",
};

type AuditHistoryEvent = {
  event_id: string;
  event_type: string;
  actor: string;
  created_at: string;
  document_ref: string;
  file_name: string;
  invoice_number: string;
  details: Record<string, unknown>;
};

function auditStateLabel(value: unknown) {
  const state = String(value || "");
  if (state === "approved") return "Onaylandı";
  if (state === "working_draft") return "Kontrolde";
  if (state === "review_required") return "Kontrol gerekli";
  if (state === "rejected") return "Hariç";
  if (state === "export_ready") return "Çıktıya hazır";
  return state || "-";
}

function auditEventLabel(event: AuditHistoryEvent) {
  const action = String(event.details?.action || "");
  if (event.event_type === "journal_undo") return "Geri alındı";
  if (event.event_type === "journal_reopened") return "Kontrole geri alındı";
  if (event.event_type === "journal_approved") return action === "approve_with_changes" ? "Düzeltip onayladı" : "Onayladı";
  if (["exclude_export", "exclude_from_export", "out_of_scope", "business_out_of_scope"].includes(action)) return "Hariç tuttu";
  if (action === "review_required") return "Kontrolde tuttu";
  return "Karar kaydetti";
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
                ? `Oturum aktif${session.expiresAt ? ` / ${formatPortalDateTime(session.expiresAt)}` : ""}.`
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
  const [auditEvents, setAuditEvents] = useState<AuditHistoryEvent[]>([]);
  const [auditLoadedClientId, setAuditLoadedClientId] = useState("");
  const [auditQuery, setAuditQuery] = useState("");
  const [auditActor, setAuditActor] = useState("");
  const [auditAction, setAuditAction] = useState("");
  const [auditStartDate, setAuditStartDate] = useState("");
  const [auditEndDate, setAuditEndDate] = useState("");
  const [auditStatus, setAuditStatus] = useState("");
  const [officeInviteEmail, setOfficeInviteEmail] = useState("");
  const [officeInviteName, setOfficeInviteName] = useState("");
  const [officeInviteStatus, setOfficeInviteStatus] = useState("");
  const [officeInviteBusy, setOfficeInviteBusy] = useState(false);

  async function inviteOfficeUser() {
    const email = officeInviteEmail.trim().toLowerCase();
    if (!email || !email.includes("@")) { setOfficeInviteStatus("Geçerli bir e-posta adresi girin."); return; }
    setOfficeInviteBusy(true);
    setOfficeInviteStatus("Davet hazırlanıyor...");
    try {
      const result = await createPortalInvite({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        userId: email, email, displayName: officeInviteName.trim() || email,
        role: "accountant", clientId: "*", invitedBy: session?.userId || "",
        ttlHours: 48, userHeader: session?.userId || "", sessionToken: session?.sessionToken || "",
      });
      const delivery = String((result as { email_delivery?: { status?: string } })?.email_delivery?.status || "");
      setOfficeInviteStatus(delivery === "sent" ? "Davet e-postası gönderildi. Bağlantı 48 saat geçerli." : "Davet oluşturuldu. E-posta gönderimi yapılandırmasını kontrol edin.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOfficeInviteStatus(userSafeErrorMessage(message, "Ofis kullanıcısı davet edilemedi. Tekrar deneyin."));
    } finally { setOfficeInviteBusy(false); }
  }

  async function loadAuditHistory() {
    if (!selectedClient) {
      setAuditEvents([]);
      setAuditLoadedClientId("");
      setAuditStatus("Önce mükellef seçin.");
      return;
    }
    setAuditStatus("İşlem geçmişi aranıyor...");
    try {
      const payload = await fetchAuditHistory({
        apiBaseUrl: resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
        clientId: selectedClient.clientId,
        query: auditQuery.trim(),
        actor: auditActor.trim(),
        action: auditAction,
        startDate: auditStartDate,
        endDate: auditEndDate,
        userId: session?.userId || "",
        sessionToken: session?.sessionToken || "",
      }) as { events?: AuditHistoryEvent[] };
      const events = Array.isArray(payload?.events) ? payload.events : [];
      setAuditEvents(events);
      setAuditLoadedClientId(selectedClient.clientId);
      setAuditStatus(events.length ? `${events.length} kayıt bulundu.` : "Bu aramada işlem kaydı bulunamadı.");
    } catch {
      setAuditEvents([]);
      setAuditLoadedClientId(selectedClient.clientId);
      setAuditStatus("İşlem geçmişi alınamadı. Tekrar deneyin.");
    }
  }

  const visibleAuditEvents = auditLoadedClientId === selectedClient?.clientId ? auditEvents : [];

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
        <section className="panel settings-card" aria-label="Ofis kullanıcısı daveti">
          <div className="section-heading">
            <span>Ofis erişimi</span><strong>Kullanıcı davet et</strong>
          </div>
          <p>Ofiste birlikte çalışacak kişi ayrı hesabıyla giriş yapar. Bu kullanıcı tüm mükelleflere erişebilir; aynı belgeyi iki kişi aynı anda düzenleyemez.</p>
          <div className="qnb-settings-form">
            <input aria-label="Ofis kullanıcısı adı" onChange={(event) => setOfficeInviteName(event.target.value)} placeholder="Ad soyad" value={officeInviteName} />
            <input aria-label="Ofis kullanıcısı e-posta" onChange={(event) => setOfficeInviteEmail(event.target.value)} placeholder="E-posta" type="email" value={officeInviteEmail} />
          </div>
          <div className="session-controls">
            <button disabled={officeInviteBusy || !officeInviteEmail.trim()} onClick={() => void inviteOfficeUser()} type="button">{officeInviteBusy ? "Gönderiliyor..." : "Davet gönder"}</button>
          </div>
          {officeInviteStatus ? <p className="decision-status" role="status">{officeInviteStatus}</p> : null}
        </section>
      ) : null}
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
            <Info label="Son bağlantı testi" value={formatPortalDateTime(qnbStatus.lastTestedAt)} />
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
            <Info label="Son başarılı" value={formatPortalDateTime(qnbHealth.lastSuccessAt)} />
            <Info label="Son deneme" value={formatPortalDateTime(qnbHealth.lastAttemptAt)} />
            <Info label="Sonraki çalışma" value={formatPortalDateTime(qnbHealth.nextRunAt)} />
            <Info label="Son sonuç" value={`${qnbHealth.listedCount} listelendi / ${qnbHealth.downloadedCount} alındı / ${qnbHealth.duplicateCount} tekrar / ${qnbHealth.failedCount} hata`} />
          </div>
        </section>
      ) : null}
      {session?.role === "accountant" ? (
        <details
          className="panel settings-card settings-audit-card"
          onToggle={(event) => {
            if (event.currentTarget.open && selectedClient && auditLoadedClientId !== selectedClient.clientId) void loadAuditHistory();
          }}
        >
          <summary className="settings-audit-summary">
            <span><small>Gelişmiş</small><strong>İşlem geçmişi</strong></span>
            <em>Yalnız sorun incelemesi için</em>
          </summary>
          <div className="settings-audit-body">
            <p>Günlük çalışma ekranına eklenmez. Seçili mükellefte kim, ne zaman, hangi muhasebe kararını değiştirdi diye aramak için kullanılır.</p>
            <div className="settings-audit-context">
              <strong>{selectedClient?.clientName || "Mükellef seçilmedi"}</strong>
              <span>{selectedClient ? "Sonuçlar yalnız seçili mükellefe aittir." : "Üstten bir mükellef seçin."}</span>
            </div>
            <div className="settings-audit-filters">
              <input aria-label="İşlem geçmişinde belge ara" onChange={(event) => setAuditQuery(event.target.value)} placeholder="Belge no, dosya veya açıklama" value={auditQuery} />
              <input aria-label="İşlem geçmişinde kullanıcı ara" onChange={(event) => setAuditActor(event.target.value)} placeholder="Kullanıcı" value={auditActor} />
              <select aria-label="İşlem türü" onChange={(event) => setAuditAction(event.target.value)} value={auditAction}>
                <option value="">Tüm işlemler</option>
                <option value="approve">Onay</option>
                <option value="approve_with_changes">Düzeltip onay</option>
                <option value="review_required">Kontrolde tut / geri al</option>
                <option value="exclude_export">Hariç tut</option>
              </select>
              <input aria-label="İşlem geçmişi başlangıç tarihi" onChange={(event) => setAuditStartDate(event.target.value)} type="date" value={auditStartDate} />
              <input aria-label="İşlem geçmişi bitiş tarihi" onChange={(event) => setAuditEndDate(event.target.value)} type="date" value={auditEndDate} />
              <button className="secondary" disabled={!selectedClient} onClick={() => void loadAuditHistory()} type="button">Ara</button>
            </div>
            {auditStatus ? <p className="decision-status" role="status">{auditStatus}</p> : null}
            {visibleAuditEvents.length ? (
              <div className="settings-audit-table-wrap">
                <table className="settings-audit-table">
                  <thead><tr><th>Tarih</th><th>Belge</th><th>Kullanıcı</th><th>İşlem</th><th>Değişim</th></tr></thead>
                  <tbody>
                    {visibleAuditEvents.map((event) => {
                      const beforeState = auditStateLabel(event.details?.before_state);
                      const afterState = auditStateLabel(event.details?.after_state);
                      const reason = String(event.details?.reason || "");
                      return (
                        <tr key={event.event_id}>
                          <td>{formatPortalDateTime(event.created_at)}</td>
                          <td><strong>{event.invoice_number || event.file_name || event.document_ref || "-"}</strong>{event.file_name && event.invoice_number ? <small>{event.file_name}</small> : null}</td>
                          <td>{event.actor || "-"}</td>
                          <td>{auditEventLabel(event)}</td>
                          <td><strong>{beforeState !== "-" ? `${beforeState} → ${afterState}` : afterState}</strong>{reason ? <small>{reason}</small> : null}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </section>
  );
}
