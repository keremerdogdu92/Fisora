// File: frontend/app/portal-next/portal-next-upload-view.tsx
// Summary: Renders the accountant quick-upload workspace, stages invoice files safely, and delegates persistence to the existing authenticated upload action.
"use client";

import { FileText, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { IntakeCategory, PilotClient, PilotDocument, PilotStatus } from "../portal-types";

const invoiceCategories = new Set<IntakeCategory>(["purchase_invoice", "sales_invoice"]);
const acceptedExtensions = new Set(["pdf", "html", "htm", "xml", "zip"]);

type InvoiceCategory = "purchase_invoice" | "sales_invoice";

type UploadWorkspaceProps = {
  clients: PilotClient[];
  documents: PilotDocument[];
  onClientChange: (clientId: string) => void;
  onIntakeCategoryChange: (category: InvoiceCategory) => void;
  onUpload: (files: File[]) => Promise<boolean>;
  selectedClient?: PilotClient;
  selectedIntakeCategory: IntakeCategory;
  uploadPeriod: string;
  uploadStatus: string;
};
const statusLabels: Record<PilotStatus, string> = {
  uploaded: "Yüklendi",
  queued: "Kuyrukta",
  processing: "İşleniyor",
  review_required: "Kontrol gerekli",
  export_ready: "Hazır",
  cancel_requested: "İptal talebi",
  cancel_approved: "İptal kabul",
  cancel_rejected: "İptal red",
  export_added: "Çıktıda",
  exported: "Çıktı alındı",
  post_export_correction_requested: "Düzeltme",
};

function categoryLabel(category: IntakeCategory) {
  return category === "sales_invoice" ? "Satış" : "Alış";
}

function fileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function isAcceptedFile(file: File) {
  const extension = file.name.split(".").pop()?.toLocaleLowerCase("tr-TR") ?? "";
  return acceptedExtensions.has(extension);
}

function statusTone(status: PilotStatus) {
  if (["uploaded", "queued", "processing"].includes(status)) return "waiting";
  if (["review_required", "cancel_requested", "post_export_correction_requested"].includes(status)) return "review";
  return "ready";
}

function uploadTimestamp(value: string) {
  const direct = Date.parse(value);
  if (Number.isFinite(direct)) return direct;
  const match = value.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[ ,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
  if (!match) return 0;
  return new Date(
    Number(match[3]), Number(match[2]) - 1, Number(match[1]),
    Number(match[4] || 0), Number(match[5] || 0), Number(match[6] || 0),
  ).getTime();
}

function periodLabel(period: string) {
  const [year, month] = period.split("-");
  return year && month ? `${month}.${year}` : period;
}
export function PortalNextUploadView({
  clients, documents, onClientChange, onIntakeCategoryChange, onUpload,
  selectedClient, selectedIntakeCategory, uploadPeriod, uploadStatus,
}: UploadWorkspaceProps) {
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [selectionStatus, setSelectionStatus] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const activeCategory: InvoiceCategory = selectedIntakeCategory === "sales_invoice" ? "sales_invoice" : "purchase_invoice";

  useEffect(() => {
    if (!invoiceCategories.has(selectedIntakeCategory)) onIntakeCategoryChange("purchase_invoice");
  }, [onIntakeCategoryChange, selectedIntakeCategory]);

  const recentDocuments = useMemo(
    () => documents
      .filter((document) => invoiceCategories.has(document.intakeCategory))
      .slice()
      .sort((a, b) => uploadTimestamp(b.uploadedAt) - uploadTimestamp(a.uploadedAt))
      .slice(0, 8),
    [documents],
  );
  function appendFiles(files: File[]) {
    const accepted = files.filter(isAcceptedFile);
    const skippedCount = files.length - accepted.length;
    setPendingFiles((current) => {
      const known = new Set(current.map(fileKey));
      const uniqueFiles = accepted.filter((file) => !known.has(fileKey(file)));
      const duplicateCount = accepted.length - uniqueFiles.length;
      setSelectionStatus([
        skippedCount ? `${skippedCount} desteklenmeyen dosya atlandı.` : "",
        duplicateCount ? `${duplicateCount} tekrar dosya eklenmedi.` : "",
      ].filter(Boolean).join(" "));
      return [...current, ...uniqueFiles];
    });
  }

  async function startUpload() {
    if (!selectedClient || !pendingFiles.length || isUploading) return;
    setIsUploading(true);
    setSelectionStatus("");
    try {
      const completed = await onUpload(pendingFiles);
      if (completed) setPendingFiles([]);
    } finally {
      setIsUploading(false);
    }
  }
  return (
    <section className="portal-next-upload-page">
      <div className="portal-next-upload-heading">
        <div>
          <span>Ofis yüklemeleri</span>
          <h2>Yeni yüklemeler</h2>
          <p>Faturaları mükellef ve yön bilgisiyle doğrudan işleme kuyruğuna alın.</p>
        </div>
        <div className="portal-next-upload-period">
          <span>Yükleme dönemi</span>
          <strong>{periodLabel(uploadPeriod)}</strong><small>Bu ekrandaki faturalar bu döneme kaydedilir.</small>
        </div>
      </div>

      <section className="portal-next-upload-card">
        <div className="portal-next-upload-controls">
          <label>
            <span>Mükellef</span>
            <select
              disabled={!clients.length || isUploading}
              onChange={(event) => onClientChange(event.target.value)}
              value={selectedClient?.clientId ?? ""}
            >
              {clients.map((client) => <option key={client.clientId} value={client.clientId}>{client.clientName}</option>)}
            </select>
          </label>
          <div className="portal-next-upload-type-field">
            <span>Fatura türü</span>
            <div className="portal-next-upload-type-switch" role="tablist" aria-label="Fatura türü">
              <button
                aria-selected={activeCategory === "purchase_invoice"}
                className={activeCategory === "purchase_invoice" ? "active" : ""}
                disabled={isUploading}
                onClick={() => onIntakeCategoryChange("purchase_invoice")}
                role="tab"
                type="button"
              >Alış</button>
              <button
                aria-selected={activeCategory === "sales_invoice"}
                className={activeCategory === "sales_invoice" ? "active" : ""}
                disabled={isUploading}
                onClick={() => onIntakeCategoryChange("sales_invoice")}
                role="tab"
                type="button"
              >Satış</button>
            </div>
          </div>

        </div>
        <label
          className={isDragging ? "portal-next-upload-dropzone dragging" : "portal-next-upload-dropzone"}
          onDragEnter={(event) => { event.preventDefault(); setIsDragging(true); }}
          onDragLeave={(event) => { event.preventDefault(); setIsDragging(false); }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            appendFiles(Array.from(event.dataTransfer.files));
          }}
        >
          <input
            accept=".pdf,.html,.htm,.xml,.zip"
            disabled={!selectedClient || isUploading}
            multiple
            onChange={(event) => {
              appendFiles(Array.from(event.currentTarget.files ?? []));
              event.currentTarget.value = "";
            }}
            type="file"
          />
          <span className="portal-next-upload-drop-icon"><Upload aria-hidden="true" /></span>
          <div>
            <strong>Dosyaları buraya bırakabilirsiniz</strong>
            <span>PDF · HTML · XML · ZIP</span>
            <small>Çoklu seçim desteklenir</small>
          </div>
          <span className="portal-next-upload-browse">Gözat</span>
        </label>
        {pendingFiles.length ? (
          <div className="portal-next-upload-pending" aria-label="Yüklenecek dosyalar">
            {pendingFiles.map((file) => (
              <div className="portal-next-upload-pending-row" key={fileKey(file)}>
                <FileText aria-hidden="true" />
                <div>
                  <strong>{file.name}</strong>
                  <span>{formatBytes(file.size)} · {categoryLabel(activeCategory)}</span>
                </div>
                <button
                  aria-label={`${file.name} dosyasını kaldır`}
                  disabled={isUploading}
                  onClick={() => setPendingFiles((current) => current.filter((item) => fileKey(item) !== fileKey(file)))}
                  type="button"
                >
                  <X aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <div className="portal-next-upload-actions">
          <div>
            {selectionStatus ? <p className="portal-next-upload-selection-status">{selectionStatus}</p> : null}
            {uploadStatus ? <p className="decision-status" role="status">{uploadStatus}</p> : (
              <p>Belgeler seçili mükellefin {categoryLabel(activeCategory).toLocaleLowerCase("tr-TR")} faturası kuyruğuna gider.</p>
            )}
          </div>
          <button className="portal-next-upload-secondary" disabled={!pendingFiles.length || isUploading} onClick={() => { setPendingFiles([]); setSelectionStatus(""); }} type="button">Temizle</button>
          <button className="portal-next-upload-primary" disabled={!selectedClient || !pendingFiles.length || isUploading} onClick={() => void startUpload()} type="button">
            {isUploading ? "Yükleniyor…" : `Yüklemeyi Başlat${pendingFiles.length ? ` (${pendingFiles.length})` : ""}`}
          </button>
        </div>
      </section>

      <section className="portal-next-upload-recent">
        <div className="portal-next-upload-recent-heading">
          <div>
            <h2>Son yüklemeler</h2>
            <span>Ofiste son eklenen faturalar</span>
          </div>
          <strong>{recentDocuments.length} belge</strong>
        </div>
        <div className="portal-next-upload-table-wrap">
          <table className="portal-next-upload-table">
            <thead><tr><th>Mükellef</th><th>Belge</th><th>Tür</th><th>Durum</th><th>Zaman</th></tr></thead>
            <tbody>
              {recentDocuments.map((document) => (
                <tr key={document.id}>
                  <td data-label="Mükellef"><strong>{document.clientName}</strong></td>
                  <td data-label="Belge">{document.fileName}</td>
                  <td data-label="Tür">{categoryLabel(document.intakeCategory)}</td>
                  <td data-label="Durum"><span className={`portal-next-upload-status ${statusTone(document.status)}`}>{statusLabels[document.status]}</span></td>
                  <td data-label="Zaman">{document.uploadedAt || "-"}</td>
                </tr>
              ))}
              {!recentDocuments.length ? (
                <tr><td className="empty" colSpan={5}>Henüz yüklenmiş fatura yok.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
