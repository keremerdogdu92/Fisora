"use client";

import { useEffect, useState } from "react";
import type { CancellationRequest, DashboardClientRow, NewClientDraft, PilotClient, PilotDocument } from "./portal-types";

type ClientManagementTab = "new-client" | "client-list" | "requests";

export function ClientManagementView({
  cancellationRequests,
  chartUploadStatus,
  clientReprocessStatus,
  clientDocumentDeleteConfirmed,
  clientDocumentDeleteStatus,
  clientRows,
  clients,
  clientSearch,
  documents,
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
  clientReprocessStatus: string;
  clientDocumentDeleteConfirmed: boolean;
  clientDocumentDeleteStatus: string;
  clientRows: DashboardClientRow[];
  clients: PilotClient[];
  clientSearch: string;
  documents: PilotDocument[];
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
  const [activeTab, setActiveTab] = useState<ClientManagementTab>("new-client");
  const selectedDocumentRefSet = new Set(selectedDocumentRefs);
  const selectableDocumentRefs = documents.map((document) => document.originalDocumentRef || document.id).filter(Boolean);
  const allDocumentsSelected = Boolean(selectableDocumentRefs.length && selectableDocumentRefs.every((ref) => selectedDocumentRefSet.has(ref)));
  const hasSelectedClient = Boolean(selectedClient);
  const toggleDocument = (documentRef: string, checked: boolean) => {
    if (checked) {
      setSelectedDocumentRefs(Array.from(new Set([...selectedDocumentRefs, documentRef])));
      return;
    }
    setSelectedDocumentRefs(selectedDocumentRefs.filter((ref) => ref !== documentRef));
  };
  const toggleAllDocuments = (checked: boolean) => {
    setSelectedDocumentRefs(checked ? selectableDocumentRefs : []);
  };
  const tabClass = (tab: ClientManagementTab) => activeTab === tab ? "active" : "";

  return (
    <section className="client-management-page client-management-tabbed">
      <div className="client-management-tabs" role="tablist" aria-label="Mükellefler sekmeleri">
        <button aria-selected={activeTab === "new-client"} className={tabClass("new-client")} onClick={() => setActiveTab("new-client")} role="tab" type="button">
          Yeni mükellef
        </button>
        <button aria-selected={activeTab === "client-list"} className={tabClass("client-list")} onClick={() => setActiveTab("client-list")} role="tab" type="button">
          Mükellef listesi
          <strong>{clients.length}</strong>
        </button>
        <button aria-selected={activeTab === "requests"} className={tabClass("requests")} onClick={() => setActiveTab("requests")} role="tab" type="button">
          İptal / düzeltme
          <strong>{cancellationRequests.length}</strong>
        </button>
      </div>

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

      {activeTab === "client-list" ? (
        <section className="client-list-operations-grid">
          <section className="panel">
            <div className="section-heading">
              <span>Mükellef listesi</span>
              <strong>{clients.length}</strong>
            </div>
            <input
              className="search-input"
              onChange={(event) => onClientSearchChange(event.target.value)}
              placeholder="Mükellef ara"
              value={clientSearch}
            />
            <div className="client-list dashboard-client-list">
              {clientRows.map((row) => (
                <button
                  className={selectedClient?.clientId === row.clientId ? "client-row active" : "client-row"}
                  key={row.clientId}
                  onClick={() => setSelectedClientId(row.clientId)}
                  type="button"
                >
                  <strong>{row.clientName}</strong>
                  <span>{row.status}</span>
                  <em>{row.documentCount} belge / {row.cancellationCount} talep</em>
                </button>
              ))}
            </div>
          </section>
          <section className="panel onboarding-panel client-existing-operations">
            <div className="section-heading">
              <span>Mevcut mükellef işlemleri</span>
              <strong>{selectedClient?.clientName ?? "-"}</strong>
            </div>
            <div className="settings-card">
              <span>Hesap planı import</span>
              <strong>{selectedClient?.clientName ?? "-"}</strong>
              <label className="file-drop-control compact-upload">
                <input
                  accept=".csv,.xlsx,.xlsm"
                  disabled={!hasSelectedClient}
                  onChange={(event) => onExistingChartFileSelected(event.target.files)}
                  type="file"
                />
                <span>Dosya seç</span>
                <small>CSV/XLSX hesap planı</small>
              </label>
              {!hasSelectedClient ? <small className="blocked-reason">Önce mükellef seçin.</small> : null}
              {chartUploadStatus ? <p className="decision-status">{chartUploadStatus}</p> : null}
            </div>
            <div className="settings-card">
              <span>Portal erişimi</span>
              <strong>{selectedClient?.portalUserId ?? "-"}</strong>
              <div className="inline-actions">
                <input
                  aria-label="Mükellef üyelik adı"
                  onChange={(event) => setPortalUserIdDraft(event.target.value)}
                  placeholder="Üyelik adı / e-posta"
                  value={portalUserIdDraft}
                />
                <button onClick={onCreateInvite} type="button">Davet tokeni oluştur</button>
                <input
                  aria-label="Portal şifresi"
                  onChange={(event) => setPortalPassword(event.target.value)}
                  placeholder="Geçici şifre"
                  type="password"
                  value={portalPassword}
                />
                <button className="primary" onClick={onSetPassword} type="button">Şifre kur</button>
                <button className="primary" onClick={onUpdatePortalAccess} type="button">Üyelik güncelle</button>
              </div>
              {inviteStatus ? <p className="decision-status">{inviteStatus}</p> : null}
              {portalPasswordStatus ? <p className="decision-status">{portalPasswordStatus}</p> : null}
            </div>
            <div className="settings-card">
              <span>Mükellef belgeleri</span>
              <strong>{selectedClient?.clientName ?? "-"}</strong>
              <label className="bulk-document-check">
                <input
                  checked={allDocumentsSelected}
                  disabled={!selectableDocumentRefs.length}
                  onChange={(event) => toggleAllDocuments(event.target.checked)}
                  type="checkbox"
                />
                Tüm belgeleri seç
              </label>
              <div className="client-document-delete-list">
                {documents.length ? documents.map((document) => {
                  const documentRef = document.originalDocumentRef || document.id;
                  return (
                    <label className="client-document-delete-row" key={document.id}>
                      <input
                        checked={selectedDocumentRefSet.has(documentRef)}
                        onChange={(event) => toggleDocument(documentRef, event.target.checked)}
                        type="checkbox"
                      />
                      <span>{document.fileName}</span>
                      <small>{document.status}</small>
                    </label>
                  );
                }) : <p className="empty">Belge yok.</p>}
              </div>
              <button disabled={!hasSelectedClient} onClick={onReprocessSelectedClient} type="button">
                Mükellefi yeniden işle
              </button>
              {clientReprocessStatus ? <p className="decision-status">{clientReprocessStatus}</p> : null}
              <label className="bulk-document-check danger">
                <input
                  checked={clientDocumentDeleteConfirmed}
                  onChange={(event) => setClientDocumentDeleteConfirmed(event.target.checked)}
                  type="checkbox"
                />
                Seçili belgelerin dosyalarıyla birlikte silineceğini onaylıyorum
              </label>
              <button
                className="danger"
                disabled={!selectedDocumentRefs.length}
                onClick={onDeleteSelectedDocuments}
                type="button"
              >
                Seçili belgeleri sil
              </button>
              {!selectedDocumentRefs.length ? <small className="blocked-reason">Önce silinecek belgeleri seçin.</small> : null}
              {clientDocumentDeleteStatus ? <p className="decision-status">{clientDocumentDeleteStatus}</p> : null}
            </div>
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
  const identityReady = Boolean(draft.title.trim() && (draft.vkn.trim() || draft.tckn.trim() || draft.taxId.trim()) && draft.activityDescription.trim());
  const chartReady = draft.chartAccounts.length > 0;
  const accessReady = Boolean(draft.portalUserId.trim() && portalPassword.trim());
  const canComplete = identityReady && chartReady && accessReady;
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
          <strong>İlerlemeli kayıt</strong>
        </div>
        <small>{canComplete ? "Tamamlanmaya hazır" : "Vergi levhası, hesap planı ve portal erişimi gerekli"}</small>
      </div>

      <div className="onboarding-steps" aria-label="Yeni mükellef adımları">
        <span className={identityReady ? "done" : "active"}>1 Vergi levhası</span>
        <span className={chartReady ? "done" : identityReady ? "active" : ""}>2 Hesap planı</span>
        <span className={accessReady ? "done" : chartReady ? "active" : ""}>3 Portal erişimi</span>
      </div>

      <section className="client-onboarding-steps" aria-label="Mükellef onboarding adımları">
        <article className={`client-step tax-certificate-step ${identityReady ? "onboarding-step done" : "onboarding-step active"}`}>
          <div className="tax-certificate-workspace">
            <div>
              <span>1. Vergi levhası</span>
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
                  <strong>{taxCertificateStage || "OCR/parser çalışıyor"}</strong>
                  <div className="tax-certificate-progress-bar" aria-hidden="true" />
                  <small>{taxCertificateSlow ? "Bu dosya taranmış görünüyor; OCR biraz sürebilir." : "OCR/parser çalışıyor"}</small>
                </div>
              ) : taxCertificateStage ? (
                <small className="tax-certificate-stage">{taxCertificateStage}</small>
              ) : null}
            </div>
            <div className="tax-certificate-fields" aria-label="Vergi levhası alanları">
              <input aria-label="Görünen unvan" onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="Görünen unvan" value={draft.title} />
              <input aria-label="Adı soyadı / yasal ad" onChange={(event) => setDraft({ ...draft, legalName: event.target.value })} placeholder="Adı soyadı / yasal ad" value={draft.legalName} />
              <input aria-label="Ticaret ünvanı" onChange={(event) => setDraft({ ...draft, tradeName: event.target.value })} placeholder="Ticaret ünvanı" value={draft.tradeName} />
              <input aria-label="Vergi kimliği" inputMode="numeric" onChange={(event) => setDraft({ ...draft, taxId: event.target.value })} pattern="[0-9]*" placeholder="Vergi kimliği" value={draft.taxId} />
              <input aria-label="VKN" inputMode="numeric" maxLength={10} onChange={(event) => setDraft({ ...draft, vkn: event.target.value, taxId: event.target.value || draft.tckn })} pattern="[0-9]*" placeholder="VKN" value={draft.vkn} />
              <input aria-label="TCKN" inputMode="numeric" maxLength={11} onChange={(event) => setDraft({ ...draft, tckn: event.target.value, taxId: draft.vkn || event.target.value })} pattern="[0-9]*" placeholder="TCKN" value={draft.tckn} />
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
                NACE araştırmasını onayla
              </button>
              <p className={naceResearchStatus.includes("tamamlanamadı") ? "decision-status error" : "decision-status"}>
                {naceResearchStatus || "NACE kodu OCR ile gelirse otomatik araştırılır; eksikse kodu doldurup onaylayın."}
              </p>
              {researchSummary ? <p>{researchSummary}</p> : null}
              {sourceUrls.length ? <small>Kaynak: {sourceUrls.slice(0, 2).join(", ")}</small> : null}
            </div>
          </div>
        </article>

        <article className={`client-step ${chartReady ? "onboarding-step done" : identityReady ? "onboarding-step active" : "onboarding-step locked"}`}>
        <div>
          <span>2. Hesap planı</span>
          <strong>{chartReady ? `${draft.chartAccountFileName} yüklendi` : "Hesap planı zorunlu"}</strong>
        </div>
        <label className="file-drop-control">
          <span>CSV/XLSX hesap planı</span>
          <input
            accept=".csv,.xlsx,.xlsm"
            disabled={!identityReady}
            onChange={(event) => onChartFileSelected(event.target.files)}
            type="file"
          />
          <small>{chartReady ? `${draft.chartAccounts.length} hesap okundu` : "Hesap planı yüklenmeden devam edilmez"}</small>
        </label>
        {!identityReady ? <small className="blocked-reason">Önce vergi levhası yükleyin.</small> : null}
        </article>

        <article className={`client-step ${accessReady ? "onboarding-step done" : chartReady ? "onboarding-step active" : "onboarding-step locked"}`}>
        <div>
          <span>3. Portal erişimi</span>
          <strong>Mükellef kullanıcı adı ve geçici şifre</strong>
        </div>
        <div className="onboarding-fields">
          <input
            aria-label="Mükellef e-posta / giriş kullanıcı adı"
            disabled={!chartReady}
            onChange={(event) => setDraft({ ...draft, portalUserId: event.target.value })}
            placeholder="E-posta / kullanıcı adı"
            value={draft.portalUserId}
          />
          <input
            aria-label="Geçici şifre"
            disabled={!chartReady}
            onChange={(event) => setPortalPassword(event.target.value)}
            placeholder="Geçici şifre"
            type="password"
            value={portalPassword}
          />
        </div>
        {!chartReady ? <small className="blocked-reason">Önce hesap planı yükleyin.</small> : null}
        </article>
      </section>

      <button className="primary full" disabled={!canComplete} onClick={onCreate} type="button">Mükellefi oluştur</button>
      {status ? <p className="decision-status">{status}</p> : null}
    </section>
  );
}
