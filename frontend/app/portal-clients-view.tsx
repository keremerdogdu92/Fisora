"use client";

import type { CancellationRequest, DashboardClientRow, NewClientDraft, PilotClient } from "./portal-types";

export function ClientManagementView({
  cancellationRequests,
  chartUploadStatus,
  clientRows,
  clients,
  clientSearch,
  inviteStatus,
  newClientDraft,
  newClientStatus,
  newClientTaxCertificateFile,
  newClientTaxCertificateInputKey,
  onChartFileSelected,
  onClientSearchChange,
  onCreateInvite,
  onCreateNewClient,
  onResolveCancellation,
  onSetPassword,
  onTaxCertificateFileChange,
  portalPassword,
  portalPasswordStatus,
  selectedClient,
  setNewClientDraft,
  setPortalPassword,
  setSelectedClientId,
}: {
  cancellationRequests: CancellationRequest[];
  chartUploadStatus: string;
  clientRows: DashboardClientRow[];
  clients: PilotClient[];
  clientSearch: string;
  inviteStatus: string;
  newClientDraft: NewClientDraft;
  newClientStatus: string;
  newClientTaxCertificateFile: File | null;
  newClientTaxCertificateInputKey: number;
  onChartFileSelected: (files: FileList | null) => void | Promise<void>;
  onClientSearchChange: (value: string) => void;
  onCreateInvite: () => void | Promise<void>;
  onCreateNewClient: () => void | Promise<void>;
  onResolveCancellation: (requestId: string, status: "approved" | "rejected") => void;
  onSetPassword: () => void | Promise<void>;
  onTaxCertificateFileChange: (file: File | null) => void | Promise<void>;
  portalPassword: string;
  portalPasswordStatus: string;
  selectedClient?: PilotClient;
  setNewClientDraft: (value: NewClientDraft) => void;
  setPortalPassword: (value: string) => void;
  setSelectedClientId: (value: string) => void;
}) {
  return (
    <section className="client-management-page">
      <section className="panel">
        <div className="section-heading">
          <span>Mukellef listesi</span>
          <strong>{clients.length}</strong>
        </div>
        <input
          className="search-input"
          onChange={(event) => onClientSearchChange(event.target.value)}
          placeholder="Mukellef ara"
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
      <section className="panel onboarding-panel">
        <NewClientCard
          draft={newClientDraft}
          onCreate={onCreateNewClient}
          onTaxCertificateFileChange={onTaxCertificateFileChange}
          setDraft={setNewClientDraft}
          status={newClientStatus}
          taxCertificateFile={newClientTaxCertificateFile}
          taxCertificateInputKey={newClientTaxCertificateInputKey}
        />
        <div className="settings-card">
          <span>Hesap plani import</span>
          <strong>{selectedClient?.clientName ?? "-"}</strong>
          <label className="upload-dropzone compact-upload">
            <input
              accept=".csv,.xlsx,.xlsm"
              onChange={(event) => onChartFileSelected(event.target.files)}
              type="file"
            />
            CSV/XLSX hesap plani sec
          </label>
          {chartUploadStatus ? <p className="decision-status">{chartUploadStatus}</p> : null}
        </div>
        <div className="settings-card">
          <span>Portal erisimi</span>
          <strong>{selectedClient?.portalUserId ?? "-"}</strong>
          <div className="inline-actions">
            <button onClick={onCreateInvite} type="button">Davet tokeni olustur</button>
            <input
              aria-label="Portal sifresi"
              onChange={(event) => setPortalPassword(event.target.value)}
              placeholder="Gecici sifre"
              type="password"
              value={portalPassword}
            />
            <button className="primary" onClick={onSetPassword} type="button">Sifre kur</button>
          </div>
          {inviteStatus ? <p className="decision-status">{inviteStatus}</p> : null}
          {portalPasswordStatus ? <p className="decision-status">{portalPasswordStatus}</p> : null}
        </div>
      </section>
      <section className="panel">
        <div className="section-heading">
          <span>Iptal / duzeltme talepleri</span>
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
          )) : <p className="empty">Acik talep yok.</p>}
        </div>
      </section>
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
        onChange={(event) => setDraft({ ...draft, taxId: event.target.value })}
        pattern="[0-9]*"
        placeholder="VKN"
        value={draft.taxId}
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
