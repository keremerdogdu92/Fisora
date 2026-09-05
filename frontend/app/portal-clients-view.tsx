// File: frontend/app/portal-clients-view.tsx
// Summary: Renders accountant taxpayer management, streamlined client detail, portal access, Gemini onboarding, and cancellation review.
"use client";

import { useEffect, useState } from "react";
import type { CancellationRequest, DashboardClientRow, NewClientDraft, PilotClient, PilotDocument } from "./portal-types";
import { resolveApiBaseUrl } from "./upload-api";

type ClientManagementTab = "new-client" | "client-list" | "requests";

function onboardingAttachmentUrl(clientId: string, ref: string) {
  const pageUrl = typeof window === "undefined" ? "" : window.location.href;
  return `${resolveApiBaseUrl(pageUrl)}/phase0/store/document-file/${encodeURIComponent(clientId)}/${encodeURIComponent(ref)}`;
}

type ClientManagementSurface = "list" | "detail";

function clientStatusTone(status: string) {
  if (status === "Çıktı hazır" || status === "Takipte") return "success";
  if (status === "Kontrol bekliyor" || status === "Talep var") return "attention";
  if (status === "İşleniyor") return "info";
  return "neutral";
}

export function ClientManagementView({
  cancellationRequests,
  chartUploadStatus,
  clientPortalOpenStatus,
  clientReprocessStatus,
  clientDocumentDeleteConfirmed,
  clientDocumentDeleteStatus,
  clientRows,
  clients,
  clientSearch,
  documents,
  isLoading,
  inviteStatus,
  newClientDraft,
  newClientNaceResearchPending,
  newClientNaceResearchProfile,
  newClientNaceResearchStatus,
  newClientStatus,
  newClientTaxCertificateFile,
  newClientTaxCertificateInputKey,
  newClientTaxCertificateParsePending,
  newClientTaxCertificateStage,
  onChartFileSelected,
  onExistingChartFileSelected,
  onClientSearchChange,
  onCreateInvite,
  onCreateNewClient,
  onDeleteSelectedDocuments,
  onOpenClientPortal,
  onReprocessSelectedClient,
  onResolveCancellation,
  onRefreshNaceResearch,
  onSetPassword,
  onUpdatePortalAccess,
  onTaxCertificateFileChange,
  portalPassword,
  portalPasswordStatus,
  portalUserIdDraft,
  selectedClient,
  selectedDocumentRefs,
  setClientDocumentDeleteConfirmed,
  setNewClientDraft,
  setPortalPassword,
  setPortalUserIdDraft,
  setSelectedDocumentRefs,
  setSelectedClientId,
}: {
  cancellationRequests: CancellationRequest[];
  chartUploadStatus: string;
  clientPortalOpenStatus: string;
  clientReprocessStatus: string;
  clientDocumentDeleteConfirmed: boolean;
  clientDocumentDeleteStatus: string;
  clientRows: DashboardClientRow[];
  clients: PilotClient[];
  clientSearch: string;
  documents: PilotDocument[];
  isLoading: boolean;
  inviteStatus: string;
  newClientDraft: NewClientDraft;
  newClientNaceResearchPending: boolean;
  newClientNaceResearchProfile: Record<string, unknown> | null;
  newClientNaceResearchStatus: string;
  newClientStatus: string;
  newClientTaxCertificateFile: File | null;
  newClientTaxCertificateInputKey: number;
  newClientTaxCertificateParsePending: boolean;
  newClientTaxCertificateStage: string;
  onChartFileSelected: (files: FileList | null) => void | Promise<void>;
  onExistingChartFileSelected: (files: FileList | null) => void | Promise<void>;
  onClientSearchChange: (value: string) => void;
  onCreateInvite: () => void | Promise<void>;
  onCreateNewClient: () => void | Promise<void>;
  onDeleteSelectedDocuments: () => void | Promise<void>;
  onOpenClientPortal: () => void | Promise<void>;
  onReprocessSelectedClient: () => void | Promise<void>;
  onResolveCancellation: (requestId: string, status: "approved" | "rejected") => void;
  onRefreshNaceResearch: () => void | Promise<void>;
  onSetPassword: () => void | Promise<void>;
  onUpdatePortalAccess: () => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void | Promise<void>;
  portalPassword: string;
  portalPasswordStatus: string;
  portalUserIdDraft: string;
  selectedClient?: PilotClient;
  selectedDocumentRefs: string[];
  setClientDocumentDeleteConfirmed: (value: boolean) => void;
  setNewClientDraft: (value: NewClientDraft) => void;
  setPortalPassword: (value: string) => void;
  setPortalUserIdDraft: (value: string) => void;
  setSelectedDocumentRefs: (value: string[]) => void;
  setSelectedClientId: (value: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<ClientManagementTab>("client-list");
  const [clientSurface, setClientSurface] = useState<ClientManagementSurface>("list");
  const hasSelectedClient = Boolean(selectedClient);
  const readyClientCount = clientRows.filter((row) => (
    row.documentCount > 0
    && row.pendingReviewCount === 0
    && row.inProgressCount === 0
    && row.cancellationCount === 0
  )).length;
  const setupMissingCount = clientRows.filter((row) => row.documentCount === 0).length;
  const attentionClientCount = clientRows.filter((row) => row.pendingReviewCount > 0 || row.cancellationCount > 0).length;
  const selectedClientRow = selectedClient ? clientRows.find((row) => row.clientId === selectedClient.clientId) : undefined;
  const invoiceCount = documents.filter((document) => document.intakeCategory === "sales_invoice" || document.intakeCategory === "purchase_invoice").length;
  const bankCount = documents.filter((document) => document.intakeCategory === "bank_statement").length;
  const otherCount = documents.filter((document) => document.intakeCategory === "special_document").length;
  const selectedTaxId = selectedClient?.vkn || selectedClient?.tckn || selectedClient?.taxId || "-";
  const onboardingAttachments = selectedClient?.onboardingAttachments ?? [];

  const openClientDetail = (clientId: string) => {
    setSelectedClientId(clientId);
    setSelectedDocumentRefs([]);
    setClientSurface("detail");
  };

  const switchTab = (tab: ClientManagementTab) => {
    setActiveTab(tab);
    if (tab === "client-list") setClientSurface("list");
  };

  return (
    <section className="client-management-page client-management-tabbed">
      <header className="client-v13-page-head">
        <div>
          <h1>Mükellefler</h1>
          <p>Kurulum, dönem ve çalışma durumunu tek yerde yönetin.</p>
        </div>
        <div className={`client-v13-page-actions${activeTab === "client-list" ? " list-view" : ""}`}>
          {activeTab === "client-list" && cancellationRequests.length ? (
            <button className="secondary compact" onClick={() => switchTab("requests")} type="button">
              İptal / düzeltme · <strong>{cancellationRequests.length}</strong>
            </button>
          ) : activeTab !== "client-list" ? (
            <button className="secondary compact" onClick={() => switchTab("client-list")} type="button">← Mükellef listesi</button>
          ) : null}
          {activeTab !== "new-client" ? (
            <button className="primary" onClick={() => switchTab("new-client")} type="button">+ Yeni mükellef</button>
          ) : null}
        </div>
      </header>

      <section className="client-v13-metrics" aria-label="Mükellef özeti">
        <article><span>Toplam</span><strong>{isLoading ? "…" : clientRows.length}</strong></article>
        <article><span>Hazır</span><strong>{isLoading ? "…" : readyClientCount}</strong></article>
        <article><span>Kurulum / yükleme eksik</span><strong>{isLoading ? "…" : setupMissingCount}</strong></article>
        <article className={attentionClientCount ? "attention" : ""}><span>Kontrol gereken</span><strong>{isLoading ? "…" : attentionClientCount}</strong></article>
      </section>

      {activeTab === "new-client" ? (
        <section className="panel client-tab-panel">
          <NewClientStepper
            draft={newClientDraft}
            naceResearchPending={newClientNaceResearchPending}
            naceResearchProfile={newClientNaceResearchProfile}
            naceResearchStatus={newClientNaceResearchStatus}
            onChartFileSelected={onChartFileSelected}
            onCreate={onCreateNewClient}
            onRefreshNaceResearch={onRefreshNaceResearch}
            onTaxCertificateFileChange={onTaxCertificateFileChange}
            portalPassword={portalPassword}
            setDraft={setNewClientDraft}
            setPortalPassword={setPortalPassword}
            status={newClientStatus}
            taxCertificateFile={newClientTaxCertificateFile}
            taxCertificateInputKey={newClientTaxCertificateInputKey}
            taxCertificateParsePending={newClientTaxCertificateParsePending}
            taxCertificateStage={newClientTaxCertificateStage}
          />
        </section>
      ) : null}

      {activeTab === "client-list" && clientSurface === "list" ? (
        <section className="client-v13-list-surface">
          <div className="client-v13-toolbar panel">
            <input
              className="search-input"
              onChange={(event) => onClientSearchChange(event.target.value)}
              placeholder="Mükellef ara"
              value={clientSearch}
            />
          </div>

          <section className="client-v13-table-wrap panel" aria-label="Mükellef listesi">
            {isLoading ? (
              <div className="client-list-state loading" role="status" aria-live="polite">
                <span className="workspace-status-dot" aria-hidden="true" />
                <div>
                  <strong>Mükellefler yükleniyor</strong>
                  <small>Çalışma alanındaki kayıtlar hazırlanıyor.</small>
                </div>
              </div>
            ) : clientRows.length ? (
              <table className="client-v13-table">
                <thead>
                  <tr>
                    <th>Mükellef</th>
                    <th>Belge</th>
                    <th>Bekleyen</th>
                    <th>Hazır</th>
                    <th>Portal</th>
                    <th>Durum</th>
                    <th><span className="sr-only">İşlemler</span></th>
                  </tr>
                </thead>
                <tbody>
                  {clientRows.map((row) => {
                    const client = clients.find((item) => item.clientId === row.clientId);
                    const portalEnabled = Boolean(client?.portalUserId);
                    return (
                      <tr key={row.clientId}>
                        <td data-label="Mükellef">
                          <strong>{row.clientName}</strong>
                          <small>{row.taxId ? `VKN / TCKN ${row.taxId}` : "Vergi kimliği yok"}</small>
                        </td>
                        <td data-label="Belge">{row.documentCount}</td>
                        <td data-label="Bekleyen">
                          {row.pendingReviewCount ? `${row.pendingReviewCount} kontrol` : row.inProgressCount ? `${row.inProgressCount} işlemde` : "—"}
                        </td>
                        <td data-label="Hazır">{row.exportReadyCount}</td>
                        <td data-label="Portal">
                          <span className={`client-state-pill ${portalEnabled ? "success" : "neutral"}`}>{portalEnabled ? "Aktif" : "Yok"}</span>
                        </td>
                        <td data-label="Durum">
                          <span className={`client-state-pill ${clientStatusTone(row.status)}`}>{row.status}</span>
                        </td>
                        <td className="client-v13-row-actions">
                          <button className="secondary compact" onClick={() => openClientDetail(row.clientId)} type="button">Görüntüle</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="client-list-state empty">
                <strong>Henüz mükellef yok</strong>
                <small>İlk kaydı vergi levhası ve hesap planıyla oluşturabilirsiniz.</small>
                <button className="secondary compact" onClick={() => switchTab("new-client")} type="button">
                  Yeni mükellef oluştur
                </button>
              </div>
            )}
          </section>
        </section>
      ) : null}

      {activeTab === "client-list" && clientSurface === "detail" ? (
        <section className="client-v13-detail">
          <button className="secondary compact client-v13-back" onClick={() => setClientSurface("list")} type="button">
            ← Mükellefler
          </button>

          <header className="panel client-v13-detail-hero">
            <div className="client-v13-detail-identity">
              <span>MÜKELLEF</span>
              <h2>{selectedClient?.clientName ?? "Mükellef"}</h2>
              <p>VKN / TCKN {selectedTaxId} · {selectedClient?.onboardingStatus || "Kurulum durumu bekleniyor"}</p>
            </div>
            <div className="client-v13-detail-hero-actions">
              <span className={`client-state-pill ${selectedClient?.portalUserId ? "success" : "neutral"}`}>
                {selectedClient?.portalUserId ? "Portal aktif" : "Portal tanımlı değil"}
              </span>
              {selectedClient?.portalUserId ? (
                <button className="primary" onClick={onOpenClientPortal} type="button">Mükellef portalını aç</button>
              ) : null}
            </div>
          </header>

          <section className="client-v13-metrics detail" aria-label="Mükellef belge özeti">
            <article><span>Faturalar</span><strong>{invoiceCount}</strong><small>{selectedClientRow?.pendingReviewCount ?? 0} kontrol</small></article>
            <article><span>Banka</span><strong>{bankCount}</strong></article>
            <article><span>Diğer belgeler</span><strong>{otherCount}</strong></article>
            <article><span>Çıktıya hazır</span><strong>{selectedClientRow?.exportReadyCount ?? 0}</strong></article>
          </section>

          <section className="client-v13-detail-grid">
            <article className="panel client-v13-detail-card client-v13-profile-card">
              <div className="section-heading">
                <span>Mükellef bilgileri</span>
                <strong>{selectedClient?.legalName || selectedClient?.clientName || "-"}</strong>
              </div>
              <dl className="client-v13-fact-grid">
                <div><dt>Vergi kimliği</dt><dd>{selectedTaxId}</dd></div>
                <div><dt>Vergi dairesi</dt><dd>{selectedClient?.taxOffice || "—"}</dd></div>
                <div><dt>NACE</dt><dd>{selectedClient?.naceCode || "—"}</dd></div>
                <div><dt>Hesap planı</dt><dd>{selectedClient?.chartAccountCount ? `${selectedClient.chartAccountCount} hesap` : "Kontrol edin"}</dd></div>
                <div className="wide"><dt>Faaliyet</dt><dd>{selectedClient?.activityDescription || "—"}</dd></div>
                <div className="wide"><dt>İşyeri adresi</dt><dd>{selectedClient?.workplaceAddresses?.join(" · ") || "—"}</dd></div>
              </dl>
            </article>

            <article className="panel client-v13-detail-card">
              <div className="section-heading">
                <span>Kurulum dosyaları</span>
                <strong>{onboardingAttachments.length ? `${onboardingAttachments.length} dosya` : "Dosya yok"}</strong>
              </div>
              <div className="client-v13-file-list">
                {onboardingAttachments.length ? onboardingAttachments.map((attachment) => (
                  <a href={onboardingAttachmentUrl(selectedClient?.clientId ?? "", attachment.ref)} key={`${attachment.type}-${attachment.ref}`} rel="noreferrer" target="_blank">
                    <span>{attachment.label}</span>
                    <strong>{attachment.fileName}</strong>
                  </a>
                )) : <p className="empty">Vergi levhası veya hesap planı dosyası bulunmuyor.</p>}
              </div>

              <label className="file-drop-control compact-upload client-v13-chart-replace">
                <input
                  accept=".csv,.xlsx,.xlsm"
                  disabled={!hasSelectedClient}
                  onChange={(event) => onExistingChartFileSelected(event.target.files)}
                  type="file"
                />
                <span>Hesap planını güncelle</span>
                <small>CSV / XLSX / XLSM</small>
              </label>
              {chartUploadStatus ? <p className="decision-status">{chartUploadStatus}</p> : null}
            </article>

            <article className="panel client-v13-detail-card client-v13-portal-card">
              <div className="section-heading">
                <span>Portal erişimi</span>
                <strong>{selectedClient?.portalUserId ? "Aktif" : "Tanımlı değil"}</strong>
              </div>
              {selectedClient?.portalUserId ? (
                <>
                  <div className="client-v13-portal-user">
                    <span>Portal kullanıcısı</span>
                    <strong>{selectedClient.portalUserId}</strong>
                  </div>
                  <div className="client-v13-portal-edit">
                    <input aria-label="Mükellef üyelik adı" onChange={(event) => setPortalUserIdDraft(event.target.value)} value={portalUserIdDraft} />
                    <button className="secondary" onClick={onUpdatePortalAccess} type="button">Girişi güncelle</button>
                  </div>
                </>
              ) : (
                <>
                  <p className="client-v13-muted-copy">Bu mükellef için henüz portal kullanıcısı oluşturulmamış.</p>
                  <div className="client-v13-portal-edit">
                    <input aria-label="Mükellef üyelik adı" onChange={(event) => setPortalUserIdDraft(event.target.value)} placeholder="Mükellef e-posta / kullanıcı adı" value={portalUserIdDraft} />
                    <button className="primary" disabled={!portalUserIdDraft.trim()} onClick={onCreateInvite} type="button">Davet oluştur</button>
                  </div>
                </>
              )}

              <small>Mükellef davet bağlantısından kendi şifresini belirler.</small>
              {clientPortalOpenStatus ? <p className="decision-status">{clientPortalOpenStatus}</p> : null}
              {inviteStatus ? <p className="decision-status">{inviteStatus}</p> : null}
              {portalPasswordStatus ? <p className="decision-status">{portalPasswordStatus}</p> : null}
            </article>
          </section>
        </section>
      ) : null}

      {activeTab === "requests" ? (
        <section className="panel client-tab-panel">
          <div className="section-heading">
            <span>İptal / düzeltme talepleri</span>
            <strong>{cancellationRequests.length}</strong>
          </div>
          <div className="request-list">
            {cancellationRequests.length ? cancellationRequests.map((request) => (
              <div className="request-compact" key={request.id}>
                <span>{request.clientId}</span>
                <strong>{request.fileName}</strong>
                <p>{request.reason}</p>
                <small>Karar için Belge işleme ekranında ilgili belgeyi seçin.</small>
              </div>
            )) : <p className="empty">Açık talep yok.</p>}
          </div>
        </section>
      ) : null}
    </section>
  );
}

export function NewClientCard({
  draft,
  onCreate,
  onTaxCertificateFileChange,
  setDraft,
  status,
  taxCertificateFile,
  taxCertificateInputKey,
}: {
  draft: NewClientDraft;
  onCreate: () => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void;
  setDraft: (value: NewClientDraft) => void;
  status: string;
  taxCertificateFile: File | null;
  taxCertificateInputKey: number;
}) {
  return (
    <section className="new-client-card">
      <div>
        <span>Yeni mükellef</span>
        <strong>Hızlı kayıt</strong>
      </div>
      <input
        aria-label="Mükellef adı"
        onChange={(event) => setDraft({ ...draft, title: event.target.value })}
        placeholder="Mükellef adı"
        value={draft.title}
      />
      <input
        aria-label="VKN"
        inputMode="numeric"
        maxLength={10}
        onChange={(event) => setDraft({ ...draft, vkn: event.target.value, taxId: event.target.value || draft.tckn })}
        pattern="[0-9]*"
        placeholder="VKN"
        value={draft.vkn}
      />
      <input
        aria-label="TCKN"
        inputMode="numeric"
        maxLength={11}
        onChange={(event) => setDraft({ ...draft, tckn: event.target.value, taxId: draft.vkn || event.target.value })}
        pattern="[0-9]*"
        placeholder="TCKN"
        value={draft.tckn}
      />
      <input
        aria-label="Faaliyet"
        onChange={(event) => setDraft({ ...draft, activityDescription: event.target.value })}
        placeholder="Faaliyet"
        value={draft.activityDescription}
      />
      <div className="new-client-inline">
        <input
          aria-label="NACE"
          onChange={(event) => setDraft({ ...draft, naceCode: event.target.value })}
          placeholder="NACE"
          value={draft.naceCode}
        />
        <input
          aria-label="Mükellef e-posta / giriş kullanıcı adı"
          onChange={(event) => setDraft({ ...draft, portalUserId: event.target.value })}
          placeholder="Mükellef e-posta / giriş kullanıcı adı"
          value={draft.portalUserId}
        />
      </div>
      {draft.activityTags.length ? (
        <div className="activity-tag-strip" aria-label="Faaliyet etiketleri">
          {draft.activityTags.slice(0, 4).map((tag) => (
            <span key={tag}>{tag.replace(/_/g, " ")}</span>
          ))}
        </div>
      ) : null}
      <label className="tax-certificate-upload">
        <span>Vergi levhası</span>
        <input
          accept=".pdf,.jpg,.jpeg,.png"
          aria-label="Vergi levhası"
          key={taxCertificateInputKey}
          onChange={(event) => onTaxCertificateFileChange(event.target.files?.[0] ?? null)}
          type="file"
        />
        <small>{taxCertificateFile?.name ?? "PDF/JPG/PNG seç"}</small>
      </label>
      <button className="primary full" onClick={onCreate} type="button">Mükellef ekle</button>
      {status ? <p className="decision-status">{status}</p> : null}
    </section>
  );
}

function NewClientStepper({
  draft,
  naceResearchPending,
  naceResearchProfile,
  naceResearchStatus,
  onChartFileSelected,
  onCreate,
  onRefreshNaceResearch,
  onTaxCertificateFileChange,
  portalPassword,
  setDraft,
  setPortalPassword,
  status,
  taxCertificateFile,
  taxCertificateInputKey,
  taxCertificateParsePending,
  taxCertificateStage,
}: {
  draft: NewClientDraft;
  naceResearchPending: boolean;
  naceResearchProfile: Record<string, unknown> | null;
  naceResearchStatus: string;
  onChartFileSelected: (files: FileList | null) => void | Promise<void>;
  onCreate: () => void | Promise<void>;
  onRefreshNaceResearch: () => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void;
  portalPassword: string;
  setDraft: (value: NewClientDraft) => void;
  setPortalPassword: (value: string) => void;
  status: string;
  taxCertificateFile: File | null;
  taxCertificateInputKey: number;
  taxCertificateParsePending: boolean;
  taxCertificateStage: string;
}) {
  const identityReady = Boolean(draft.title.trim() && (draft.vkn.trim() || draft.tckn.trim() || draft.taxId.trim()));
  const activityReady = Boolean(draft.activityDescription.trim() || draft.naceCode.trim() || draft.activityTags.length);
  const addressReady = draft.workplaceAddresses.length > 0;
  const profileReady = identityReady && activityReady && addressReady;
  const taxCertificateReady = Boolean(taxCertificateFile && profileReady && !taxCertificateParsePending);
  const chartReady = draft.chartAccounts.length > 0;
  const canComplete = taxCertificateReady && chartReady;
  const [taxCertificatePreviewUrl, setTaxCertificatePreviewUrl] = useState("");
  const taxCertificateIsImage = Boolean(taxCertificateFile?.type?.startsWith("image/"));
  const [taxCertificateSlow, setTaxCertificateSlow] = useState(false);
  const researchSummary = String(naceResearchProfile?.summary_tr || naceResearchProfile?.scope_summary || "");
  const sourceUrls = Array.isArray(naceResearchProfile?.source_urls) ? naceResearchProfile.source_urls.map(String).filter(Boolean) : [];

  useEffect(() => {
    if (!taxCertificateFile) {
      setTaxCertificatePreviewUrl("");
      return;
    }
    const nextUrl = URL.createObjectURL(taxCertificateFile);
    setTaxCertificatePreviewUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [taxCertificateFile]);

  useEffect(() => {
    if (!taxCertificateParsePending) {
      setTaxCertificateSlow(false);
      return;
    }
    const timer = window.setTimeout(() => setTaxCertificateSlow(true), 15000);
    return () => window.clearTimeout(timer);
  }, [taxCertificateParsePending]);

  return (
    <section className="new-client-card onboarding-stepper">
      <div className="stepper-heading">
        <div>
          <span>Yeni mükellef</span>
          <strong>Mükellef kurulumu</strong>
        </div>
        <small>{canComplete ? "Kontrol tamamlandı · kayda hazır" : "Vergi levhasını kontrol edin ve hesap planını yükleyin"}</small>
      </div>


      <section className="client-onboarding-steps" aria-label="Mükellef onboarding adımları">
        <article className={`client-step tax-certificate-step ${taxCertificateReady ? "onboarding-step done" : "onboarding-step active"}`}>
          <div className="tax-certificate-workspace">
            <div>
              <span>Vergi levhası</span>
              <strong>Vergi levhası bilgileri</strong>
            </div>
            <label className="file-drop-control tax-certificate-drop">
              <span>Vergi levhası</span>
              <input
                accept=".pdf,.jpg,.jpeg,.png"
                aria-label="Vergi levhası"
                key={taxCertificateInputKey}
                onChange={(event) => onTaxCertificateFileChange(event.target.files?.[0] ?? null)}
                type="file"
              />
              <small>{taxCertificateFile?.name ?? "PDF/JPG/PNG seç"}</small>
            </label>
            <div className="tax-certificate-preview" aria-label="Vergi levhası önizleme">
              {taxCertificatePreviewUrl ? (
                taxCertificateIsImage ? (
                  <img alt="Vergi levhası önizleme" src={taxCertificatePreviewUrl} />
                ) : (
                  <object data={taxCertificatePreviewUrl} title="Vergi levhası önizleme" type={taxCertificateFile?.type || "application/pdf"} />
                )
              ) : (
                <p>Vergi levhası yüklendiğinde burada görünecek.</p>
              )}
              {taxCertificateParsePending ? (
                <div className="tax-certificate-progress" role="status" aria-live="polite">
                  <span className="tax-certificate-spinner" aria-hidden="true" />
                  <strong>{taxCertificateStage || "Gemini vergi levhasını analiz ediyor"}</strong>
                  <div className="tax-certificate-progress-bar" aria-hidden="true" />
                  <small>{taxCertificateSlow ? "Gemini belgeyi analiz ediyor; büyük veya taranmış dosyalarda işlem uzayabilir." : "Gemini AI ile alanlar okunuyor"}</small>
                </div>
              ) : taxCertificateStage ? (
                <small className="tax-certificate-stage">{taxCertificateStage}</small>
              ) : null}
            </div>
            <div className="tax-certificate-fields" aria-label="Vergi levhası alanları">
              <input aria-label="Görünen unvan" onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="Görünen unvan" value={draft.title} />
              <input aria-label="Adı soyadı / yasal ad" onChange={(event) => setDraft({ ...draft, legalName: event.target.value })} placeholder="Adı soyadı / yasal ad" value={draft.legalName} />
              <input aria-label="Ticaret ünvanı" onChange={(event) => setDraft({ ...draft, tradeName: event.target.value })} placeholder="Ticaret ünvanı" value={draft.tradeName} />
              <input aria-label="VKN" inputMode="numeric" maxLength={10} onChange={(event) => { const value = event.target.value; setDraft({ ...draft, vkn: value, taxId: value || draft.tckn, taxIdentifier: value || draft.tckn, identityType: value ? "vkn" : draft.tckn ? "tckn" : "" }); }} pattern="[0-9]*" placeholder="VKN" value={draft.vkn} />
              <input aria-label="TCKN" inputMode="numeric" maxLength={11} onChange={(event) => { const value = event.target.value; const identifier = draft.vkn || value; setDraft({ ...draft, tckn: value, taxId: identifier, taxIdentifier: identifier, identityType: draft.vkn ? "vkn" : value ? "tckn" : "" }); }} pattern="[0-9]*" placeholder="TCKN" value={draft.tckn} />
              <input aria-label="Vergi dairesi" onChange={(event) => setDraft({ ...draft, taxOffice: event.target.value })} placeholder="Vergi dairesi" value={draft.taxOffice} />
              <input aria-label="NACE" onChange={(event) => setDraft({ ...draft, naceCode: event.target.value })} placeholder="NACE" value={draft.naceCode} />
              <textarea aria-label="Faaliyet" onChange={(event) => setDraft({ ...draft, activityDescription: event.target.value })} placeholder="Faaliyet" value={draft.activityDescription} />
              <textarea
                aria-label="İşyeri adresleri"
                onChange={(event) => setDraft({ ...draft, workplaceAddresses: event.target.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean) })}
                placeholder="İşyeri adresleri"
                value={draft.workplaceAddresses.join("\n")}
              />
              <input
                aria-label="Faaliyet etiketleri"
                onChange={(event) => setDraft({ ...draft, activityTags: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })}
                placeholder="Faaliyet etiketleri"
                value={draft.activityTags.join(", ")}
              />
            </div>
            <div className="nace-research-panel">
              <div>
                <span>NACE araştırması</span>
                <strong>{naceResearchPending ? "Araştırılıyor" : naceResearchProfile ? "Araştırma sonucu hazır" : "Araştırma bekliyor"}</strong>
              </div>
              {naceResearchPending ? <small>NACE araştırması yapılıyor</small> : null}
              <button disabled={!draft.naceCode.trim() || naceResearchPending} onClick={onRefreshNaceResearch} type="button">
                NACE araştırmasını çalıştır
              </button>
              <p className={naceResearchStatus.includes("tamamlanamadı") ? "decision-status error" : "decision-status"}>
                {naceResearchStatus || "NACE araştırması isteğe bağlıdır; mükellef kaydını engellemez."}
              </p>
              {researchSummary ? <p>{researchSummary}</p> : null}
              {sourceUrls.length ? <small>Kaynak: {sourceUrls.slice(0, 2).join(", ")}</small> : null}
            </div>
          </div>
        </article>

        <article className={`client-step ${chartReady ? "onboarding-step done" : "onboarding-step active"}`}>
        <div>
          <span>Hesap planı</span>
          <strong>{chartReady ? `${draft.chartAccountFileName} yüklendi` : "Hesap planı zorunlu"}</strong>
        </div>
        <label className="file-drop-control">
          <span>CSV/XLSX hesap planı</span>
          <input
            accept=".csv,.xlsx,.xlsm"
            onChange={(event) => onChartFileSelected(event.target.files)}
            type="file"
          />
          <small>{chartReady ? `${draft.chartAccounts.length} hesap okundu` : "Dosyayı şimdi yükleyebilirsiniz; vergi levhası adımından bağımsızdır."}</small>
        </label>
        </article>

        <article className="client-step onboarding-step active">
        <div>
          <span>Portal erişimi</span>
          <strong>İsteğe bağlı</strong>
        </div>
        <input
          aria-label="Portal e-posta veya kullanıcı adı"
          onChange={(event) => setDraft({ ...draft, portalUserId: event.target.value })}
          placeholder="E-posta / kullanıcı adı"
          value={draft.portalUserId}
        />
        <input
          aria-label="Portal görünen ad"
          onChange={(event) => setDraft({ ...draft, portalDisplayName: event.target.value })}
          placeholder="Görünen ad (opsiyonel)"
          value={draft.portalDisplayName}
        />
        <small>Boş bırakabilirsiniz. Portal daveti daha sonra da oluşturulabilir; şifreyi mükellef belirler.</small>
        </article>
      </section>

      <button className="primary full" disabled={!canComplete} onClick={onCreate} type="button">Mükellefi oluştur</button>
      {status ? <p className="decision-status">{status}</p> : null}
    </section>
  );
}
