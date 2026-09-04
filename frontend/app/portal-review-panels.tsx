// File: frontend/app/portal-review-panels.tsx
// Summary: Renders document preview, source rows, journal editing, review decisions, and processing-safe approval controls.
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, MutableRefObject } from "react";
import { applyAccountSelectionToLine, classifyDraftAccountCode, filterAccountOptions, resolveAccountSelection } from "./portal-account-combobox";
import { Info, ReasonCard } from "./portal-shared";
import { HtmlDocumentViewer } from "./shared/components/document-viewers/html-document-viewer";
import { PdfDocumentViewer } from "./shared/components/document-viewers/pdf-document-viewer";
import type { ChartAccountOption, CorrectionDraft, DocumentPipelineEvent, DocumentSourceTarget, DraftLine, LocalSession, PilotDocument, PilotStatus, ReviewLearningDecisionOptions, RuleInterpretationView, StatementLineReview } from "./portal-types";
import { backendAuthHeaders, previewReviewRule, resolveApiBaseUrl } from "./upload-api";

const statusLabels: Record<PilotStatus, string> = {
  uploaded: "Yüklendi",
  queued: "Kuyrukta",
  processing: "İşleniyor",
  review_required: "Kontrol gerekli",
  export_ready: "Aktarıma hazır",
  cancel_requested: "İptal talebi",
  cancel_approved: "İptal kabul",
  cancel_rejected: "İptal red",
  export_added: "Çıktı listesinde",
  exported: "Çıktı alındı",
  post_export_correction_requested: "Aktarım sonrası düzeltme",
};

const statementTypeLabels: Record<string, string> = {
  tax_payment: "Vergi ödemesi",
  social_security: "SGK / prim",
  pos_blocked: "POS bloke",
  transfer: "Virman / transfer",
  counterparty_payment: "Cari ödeme",
  unknown: "Belirsiz",
};

function formatStatus(status: PilotStatus) {
  return statusLabels[status] ?? status;
}

function qnbStatusLabel(status?: string) {
  return {
    received: "Alındı / cevap bekleniyor",
    accepted: "Kabul edildi",
    rejected: "Reddedildi",
    cancelled: "İptal edildi",
    unknown: "Durum doğrulanamadı",
  }[String(status || "")] || String(status || "-");
}

function statementDirectionLabel(direction: StatementLineReview["direction"]) {
  if (direction === "in") return "Giriş";
  if (direction === "out") return "Çıkış";
  return "-";
}

function statementStatusLabel(status?: string) {
  if (status === "approved") return "Onaylı";
  if (status === "rejected") return "Reddedildi";
  if (status === "review_required") return "Kontrol";
  return "Bekliyor";
}

function journalDraftLinesForDocument(document: PilotDocument, selectedStatementLineNo: number): DraftLine[] {
  if (document.statementEntries.length) {
    const selectedEntry = document.statementEntries.find((entry) => entry.statement_line_no === selectedStatementLineNo) ?? document.statementEntries[0];
    return selectedEntry.lines;
  }
  return document.draftLines;
}

function resolvePreviewApiBaseUrl() {
  return resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
}

function formatDraftStatus(status: string) {
  const labels: Record<string, string> = {
    draft_ready: "Fiş taslağı hazır",
    manual_draft_completed: "Manuel fiş girildi",
    manual_draft_required: "Manuel fiş gerekli",
    manual_draft_unbalanced: "Fiş dengesi kontrol edilmeli",
    processing: "İşleniyor",
    provider_failed: "AI taslak alınamadı",
    ai_retry_required: "AI yeniden denenecek",
    ai_correction_required: "AI hesap düzeltmesi gerekli",
  };
  return labels[status] ?? (status || "-");
}

function parseAmount(value: string) {
  const raw = String(value || "0").trim().replace(/\s+/g, "");
  const decimalSeparator = raw.includes(",") ? "," : ".";
  const normalized = decimalSeparator === ","
    ? raw.replace(/\./g, "").replace(",", ".")
    : raw.replace(/\.(?=.*\.)/g, "");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

function draftTotals(lines: DraftLine[]) {
  const debit = lines.reduce((total, line) => total + parseAmount(line.debit), 0);
  const credit = lines.reduce((total, line) => total + parseAmount(line.credit), 0);
  return { debit, credit, balanced: Math.abs(debit - credit) < 0.005 };
}

function blankDraftLine(): DraftLine {
  return { account_code: "", description: "", debit: "0.00", credit: "0.00" };
}

function sourceAmountBasisLabel(value: string) {
  if (value === "line_total_ex_tax") return "vergi hariç satır toplamı";
  if (value === "line_total_inc_tax") return "vergi dahil kaynak tutar";
  if (value === "ambiguous") return "tutar yapısı belirsiz";
  return "kaynak tutar";
}

function sourceReviewDraftLinesForDocument(document: PilotDocument): DraftLine[] {
  return (document.sourceReviewRows ?? [])
    .filter((row) => row.role === "posting_candidate")
    .map((row) => ({
      account_code: "",
      description: String(row.description || row.sourceText || "").replace(/\s+/g, " ").trim(),
      debit: "0.00",
      credit: "0.00",
      source_position: row.sourcePosition,
      source_text: row.sourceText,
      source_amount: row.amount,
      source_amount_label: row.amountLabel,
      source_amount_basis: row.amountBasis,
      source_role: row.role,
      source_line_numbers: /^\d+$/.test(row.sourcePosition.trim()) ? [Number(row.sourcePosition)] : [],
    }));
}

function vatGroupEvidenceText(line: DraftLine) {
  const sourceLineNumbers = Array.isArray(line.source_line_numbers)
    ? line.source_line_numbers.filter((value) => Number.isInteger(value) && value > 0)
    : [];
  if (!line.vat_group_id && !sourceLineNumbers.length) return "";
  const rate = String(line.vat_group_id || "").split("|")[2] || line.tax_rate || "0";
  const sourceText = sourceLineNumbers.length
    ? sourceLineNumbers.join(", ")
    : (line.contributing_line_ids || []).map((_, index) => index + 1).join(", ");
  return `Kaynak: KDV %${rate} · Fatura satırları ${sourceText}`;
}

function normalizeAccountCodeInput(value: string) {
  return String(value || "").trim().replace(/[\s-]+/g, ".").replace(/,+/g, ".").replace(/[^0-9A-Za-z.]/g, "").replace(/\.+/g, ".").replace(/^\.+|\.+$/g, "");
}

function newCounterpartyCodesForDocument(document: PilotDocument) {
  return new Set(
    [
      document.suggestedCounterpartyAccount,
      document.selectedCounterpartyAccount,
      document.selectedCustomerAccount,
    ]
      .map((code) => normalizeAccountCodeInput(code || ""))
      .filter((code) => code.startsWith("120") || code.startsWith("320")),
  );
}

function invalidDraftAccountCodes(lines: DraftLine[], chartAccounts: ChartAccountOption[], document: PilotDocument) {
  const allowedNewCounterparties = [...newCounterpartyCodesForDocument(document)];
  return lines
    .map((line) => normalizeAccountCodeInput(line.account_code))
    .filter(Boolean)
    .filter((code) => classifyDraftAccountCode(chartAccounts, code, allowedNewCounterparties) === "invalid");
}

function newCounterpartyDraftAccountCodes(lines: DraftLine[], chartAccounts: ChartAccountOption[], document: PilotDocument) {
  const allowedNewCounterparties = [...newCounterpartyCodesForDocument(document)];
  return lines
    .map((line) => normalizeAccountCodeInput(line.account_code))
    .filter(Boolean)
    .filter((code) => classifyDraftAccountCode(chartAccounts, code, allowedNewCounterparties) === "new_counterparty");
}

function isImageMime(value: string) {
  return String(value || "").toLowerCase().startsWith("image/");
}

function isFramePreviewMime(value: string) {
  const normalized = String(value || "").toLowerCase();
  return normalized.includes("pdf")
    || normalized.startsWith("text/")
    || normalized.includes("xml")
    || normalized.includes("csv");
}

function isPdfPreview(document: PilotDocument) {
  const mime = String(document.originalDocumentMimeType || "").toLowerCase();
  return mime.includes("pdf") || String(document.fileName || "").toLowerCase().endsWith(".pdf");
}

function isHtmlPreview(document: PilotDocument) {
  const mime = String(document.originalDocumentMimeType || "").toLowerCase();
  const fileName = String(document.fileName || "").toLowerCase();
  return mime.includes("html") || fileName.endsWith(".html") || fileName.endsWith(".htm");
}

function latestPipelineProblem(document: PilotDocument) {
  return [...(document.pipelineEvents ?? [])].reverse().find((event) => event.status === "error" || event.status === "warning");
}

function accountingDirectionForDocument(document: PilotDocument) {
  if (document.accountingDirection) return document.accountingDirection;
  if (document.intakeCategory === "sales_invoice") return "sales";
  if (document.intakeCategory === "purchase_invoice") return "purchase";
  return "";
}

function directionLabel(direction: string) {
  if (direction === "sales") return "Satış";
  if (direction === "purchase") return "Alış";
  return direction || "-";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function qualityText(record: Record<string, unknown>, key: string, fallback = "-") {
  const value = record[key];
  if (Array.isArray(value)) return value.map(String).filter(Boolean).join(", ") || fallback;
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function normalizeRuleInterpretationView(value: unknown): RuleInterpretationView | null {
  const record = asRecord(value);
  const status = qualityText(record, "status", "");
  const summaryTr = qualityText(record, "summary_tr", qualityText(record, "summaryTr", ""));
  const triggerTr = qualityText(record, "trigger_tr", qualityText(record, "triggerTr", ""));
  const actionTr = qualityText(record, "action_tr", qualityText(record, "actionTr", ""));
  const guardrailTr = qualityText(record, "guardrail_tr", qualityText(record, "guardrailTr", ""));
  if (!status && !summaryTr && !triggerTr && !actionTr && !guardrailTr) return null;
  const confidence = Number(record.confidence || 0);
  const reasonCodes = Array.isArray(record.reason_codes)
    ? record.reason_codes
    : Array.isArray(record.reasonCodes)
      ? record.reasonCodes
      : [];
  return {
    source: qualityText(record, "source", ""),
    provider: qualityText(record, "provider", ""),
    status,
    summaryTr,
    triggerTr,
    actionTr,
    guardrailTr,
    confidence: Number.isFinite(confidence) ? confidence : 0,
    reasonCodes: reasonCodes.map(String).filter(Boolean),
  };
}

function uploadDirectionForDocument(document: PilotDocument) {
  if (document.intakeCategory === "sales_invoice") return "sales";
  if (document.intakeCategory === "purchase_invoice") return "purchase";
  return "";
}

function hasPendingDirectionConflict(document: PilotDocument) {
  return document.directionConflict?.status === "needs_review";
}

function previewAuthHeaders(session: LocalSession | null | undefined, document?: PilotDocument): Record<string, string> {
  const userId = session?.userId || document?.uploadedBy || "";
  const headers = backendAuthHeaders({
    sessionToken: session?.sessionToken || "",
    userId: safeHeaderValue(userId),
  });
  return { ...headers };
}

function safeHeaderValue(value: string) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  return /^[\x00-\xff]*$/.test(trimmed) ? trimmed : encodeURIComponent(trimmed);
}

export function useOriginalDocumentPreview(document?: PilotDocument, session?: LocalSession | null) {
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewError, setPreviewError] = useState("");

  useEffect(() => {
    if (!document?.originalDocumentRef) {
      setPreviewUrl("");
      setPreviewError("Gerçek belge referansı yok.");
      return;
    }
    let active = true;
    let objectUrl = "";
    const fetchPreview = async () => {
      try {
        const response = await fetch(
          `${resolvePreviewApiBaseUrl()}/phase0/store/document-file/${encodeURIComponent(document.clientId)}/${encodeURIComponent(document.originalDocumentRef)}`,
          { cache: "no-store", headers: previewAuthHeaders(session, document) },
        );
        if (!response.ok) throw new Error(`Önizleme alınamadı: ${response.status}`);
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (active) {
          setPreviewUrl(objectUrl);
          setPreviewError("");
        }
      } catch (error) {
        if (active) {
          setPreviewUrl("");
          setPreviewError(error instanceof Error ? error.message : "Gerçek belge önizlemesi alınamadı.");
        }
      }
    };
    void fetchPreview();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document?.clientId, document?.originalDocumentRef, session?.sessionToken, session?.userId]);

  return { previewError, previewUrl };
}

export function DocumentPipelineTimeline({ events }: { events: DocumentPipelineEvent[] }) {
  return (
    <section className="pipeline-timeline" aria-label="İşlem geçmişi">
      <div className="pipeline-heading">
        <strong>İşlem geçmişi</strong>
        <span>{events.length ? `${events.length} adım` : "Henüz kayıt yok"}</span>
      </div>
      {events.length ? (
        <ol>
          {events.map((event, index) => (
            <li className={`pipeline-event ${event.status || "ok"}`} key={`${event.step}-${event.createdAt}-${index}`}>
              <div>
                <strong>{event.messageTr || event.step}</strong>
                <span>{event.step} / {event.debugCode || "-"}</span>
              </div>
              {event.details && Object.keys(event.details).length ? (
                <details>
                  <summary>Teknik detay</summary>
                  <pre>{JSON.stringify(event.details, null, 2)}</pre>
                </details>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty">Bu belge için pipeline kaydı yok.</p>
      )}
    </section>
  );
}

function aiTraceStages(document?: PilotDocument) {
  const technicalDetails = asRecord(document?.technicalDetails);
  const trace = technicalDetails.ai_trace;
  return Array.isArray(trace) ? trace.map(asRecord).filter((stage) => Object.keys(stage).length) : [];
}

function traceText(value: unknown, fallback = "-") {
  if (Array.isArray(value)) return value.map(String).filter(Boolean).join(", ") || fallback;
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function traceStageLabel(stage: Record<string, unknown>) {
  const value = traceText(stage.stage);
  const labels: Record<string, string> = {
    family_select: "Aile seçimi",
    final_account: "Hesap seçimi",
    counterparty_resolve: "Cari seçimi",
  };
  return labels[value] ?? value;
}

function JsonTraceBlock({ label, value }: { label: string; value: unknown }) {
  const hasValue = typeof value === "string"
    ? Boolean(value.trim())
    : Boolean(value && (typeof value !== "object" || Object.keys(asRecord(value)).length || Array.isArray(value)));
  if (!hasValue) return null;
  return (
    <details className="json-trace-block">
      <summary>{label}</summary>
      <pre>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function AiTracePanel({ document }: { document?: PilotDocument }) {
  const stages = aiTraceStages(document);
  const lineDecisions = document?.lineDecisions ?? [];
  return (
    <details className="ai-trace-panel">
      <summary>
        <span>AI karar izi</span>
        <strong>{stages.length || lineDecisions.length ? `${stages.length} AI adımı` : "Kayıt yok"}</strong>
      </summary>
      {stages.length || lineDecisions.length ? (
        <div className="ai-trace-stage-list">
          {stages.map((stage, index) => {
            const requestPayload = asRecord(stage.request_payload);
            const providerResponse = asRecord(stage.provider_response);
            const acceptedResult = asRecord(stage.accepted_result);
            return (
              <article className="ai-trace-stage" key={`${traceText(stage.stage)}-${index}`}>
                <div className="ai-trace-stage-header">
                  <div>
                    <strong>{traceStageLabel(stage)}</strong>
                    <span>{traceText(stage.provider)} / {traceText(stage.model, "model yok")}</span>
                  </div>
                  <span className={`ai-trace-status ${traceText(stage.validation_status)}`}>{traceText(stage.validation_status)}</span>
                </div>
                <div className="ai-trace-summary-grid">
                  <Info label="Aday stratejisi" value={traceText(asRecord(stage.candidate_strategy).mode)} />
                  <Info label="Input boyutu" value={traceText(stage.estimated_input_chars)} />
                  <Info label="Seçilen hesap" value={traceText(acceptedResult.selected_account_code)} />
                  <Info label="Seçilen cari" value={traceText(acceptedResult.selected_counterparty_code)} />
                </div>
                <JsonTraceBlock label="Sistem promptu" value={stage.system_prompt} />
                <JsonTraceBlock label="AI'a ne sorduk?" value={requestPayload} />
                <JsonTraceBlock label="AI ne cevap verdi?" value={providerResponse} />
                <JsonTraceBlock label="Biz neyi kabul ettik?" value={acceptedResult} />
                <JsonTraceBlock label="Hata / red gerekçesi" value={stage.error} />
              </article>
            );
          })}
          <JsonTraceBlock label="Kabul edilen satır hesapları" value={lineDecisions} />
        </div>
      ) : (
        <p className="empty">Bu belge için AI trace kaydı yok.</p>
      )}
    </details>
  );
}

export function HtmlReaderSnapshot({ document }: { document: PilotDocument }) {
  const snapshot = document.sourceSnapshot;
  if (!snapshot) return <p className="empty">Frozen Reader snapshot henüz oluşmadı.</p>;

  return (
    <div className="html-source-reader-sections">
      {snapshot.sections.map((section, sectionIndex) => (
        <section className="html-source-reader-section" key={`${section.kind}-${sectionIndex}`}>
          <div className="html-source-reader-section-title">
            <strong>{section.title || `Bölüm ${sectionIndex + 1}`}</strong>
            <span>{section.kind}</span>
          </div>
          {section.columns.length ? <div className="html-source-reader-row header">{section.columns.map((cell, index) => <span key={index}>{cell}</span>)}</div> : null}
          {section.rows.map((row, rowIndex) => (
            <div className="html-source-reader-row" key={rowIndex}>
              {row.map((cell, cellIndex) => <span key={cellIndex}>{cell || "?"}</span>)}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

export function HtmlSourceRows({ document }: { document: PilotDocument }) {
  const rows = document.sourceReviewRows ?? [];
  return (
    <div className="html-source-ui-rows">
      {rows.length ? rows.map((row, index) => (
        <div className="html-source-ui-row" key={`${row.sourcePosition}-${index}`}>
          <span>{row.sourcePosition || String(index + 1)}</span>
          <div>
            <strong>{row.description || row.sourceText || "?"}</strong>
            {row.sourceText && row.sourceText !== row.description ? <small>{row.sourceText}</small> : null}
          </div>
          <span>{row.role}</span>
        </div>
      )) : <p className="empty">UI satırı henüz oluşmadı.</p>}
    </div>
  );
}

export function HtmlSourceComparison({ document, previewUrl }: { document: PilotDocument; previewUrl: string }) {
  const snapshot = document.sourceSnapshot;
  const rows = document.sourceReviewRows ?? [];
  if (!snapshot || !previewUrl) return null;

  return (
    <section className="html-source-comparison" aria-label="HTML kaynak karşılaştırması">
      <div className="html-source-comparison-heading">
        <div>
          <strong>HTML kaynak karşılaştırması</strong>
          <span>Orijinal görünüm / frozen reader / Fisora UI satırları</span>
        </div>
        <span>Reader {snapshot.version} • güven {Math.round(snapshot.confidence * 100)}%</span>
      </div>
      {snapshot.warnings.length ? (
        <div className="html-source-warning">{snapshot.warnings.join(" • ")}</div>
      ) : null}
      <div className="html-source-comparison-grid">
        <article className="html-source-compare-card">
          <header><strong>1. Orijinal HTML</strong><span>Sandboxed görünüm</span></header>
          <HtmlDocumentViewer fileName={document.fileName} src={previewUrl} />
        </article>
        <article className="html-source-compare-card">
          <header><strong>2. Reader snapshot</strong><span>{snapshot.metrics.rowCount} kaynak satırı</span></header>
          <HtmlReaderSnapshot document={document} />
        </article>
        <article className="html-source-compare-card">
          <header><strong>3. Fisora UI satırları</strong><span>{rows.length} satır</span></header>
          <HtmlSourceRows document={document} />
        </article>
      </div>
    </section>
  );
}

export function DocumentPreview({ controlledHtmlPreview = false, controlledPdfPreview = false, document, session, sourceTarget, onClearSourceTarget }: { controlledHtmlPreview?: boolean; controlledPdfPreview?: boolean; document?: PilotDocument; session?: LocalSession | null; sourceTarget?: DocumentSourceTarget | null; onClearSourceTarget?: () => void }) {
  const { previewError, previewUrl } = useOriginalDocumentPreview(document, session);

  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>{controlledPdfPreview || controlledHtmlPreview ? "Kaynak Belge" : "Orijinal belge"}</h2>
        <p className="empty">İşlemek için listeden belge seçin.</p>
      </section>
    );
  }
  const pipelineProblem = latestPipelineProblem(document);
  const errorMessage = previewError || pipelineProblem?.messageTr || "Gerçek belge henüz önizlenemiyor.";
  const canFramePreview = isFramePreviewMime(document.originalDocumentMimeType);
  const pdfPreview = controlledPdfPreview && isPdfPreview(document);
  const htmlPreview = isHtmlPreview(document);
  return (
    <section className="review-panel document-panel">
      <div className="panel-heading">
        <div>
          <h2>{controlledPdfPreview || controlledHtmlPreview ? "Kaynak Belge" : "Orijinal belge"}</h2>
          <span>{document.fileName}</span>
        </div>
        <span className={`status ${document.status}`}>{formatStatus(document.status)}</span>
      </div>
      <div className="document-preview-layout">
        <div className="document-canvas">
          {previewUrl ? (
            isImageMime(document.originalDocumentMimeType) ? (
              <img alt={`${document.fileName} orijinal belge`} className="original-document-image" src={previewUrl} />
            ) : pdfPreview ? (
              <PdfDocumentViewer fileName={document.fileName} onClearSourceTarget={onClearSourceTarget} sourceTarget={sourceTarget} src={previewUrl} />
            ) : htmlPreview && controlledHtmlPreview ? (
              <HtmlDocumentViewer fileName={document.fileName} onClearSourceTarget={onClearSourceTarget} sourceTarget={sourceTarget} src={previewUrl} />
            ) : canFramePreview ? (
              <iframe
                className="original-document-frame"
                sandbox={htmlPreview ? "" : "allow-same-origin"}
                src={previewUrl}
                title={`${document.fileName} orijinal belge`}
              />
            ) : (
              <div className="preview-error-panel">
                <strong>Bu dosya tarayıcı içinde önizlenemiyor.</strong>
                <p>Gerçek belge indirilebilir; mock belge gösterilmedi.</p>
                <a href={previewUrl} download={document.fileName}>Belgeyi indir</a>
              </div>
            )
          ) : (
            <div className="preview-error-panel">
              <strong>{errorMessage}</strong>
              <p>Mock belge çizimi kapalı. Hangi adımda kırıldığını işlem geçmişinden takip edin.</p>
            </div>
          )}
        </div>
        <aside className="document-info-panel" aria-label="Belge bilgileri">
          <Info label="Belge türü" value={document.documentType || document.intakeCategory} />
          <Info label="Tarih" value={document.issueDate || "-"} />
          <Info label="Tutar" value={document.amount || "-"} />
          <Info label="KDV" value={document.vatRates.length ? document.vatRates.join(", ") : "-"} />
          <Info label="Satir" value={typeof document.canonicalLineCount === "number" ? String(document.canonicalLineCount) : "-"} />
          <Info
            label="Okuma"
            value={
              document.canonicalValidationStatus
                ? `${document.canonicalValidationStatus}${document.canonicalValidationReasons?.length ? ` / ${document.canonicalValidationReasons.join(", ")}` : ""}`
                : "-"
            }
          />
          <Info label="AI okuma" value={document.canonicalExtractionAiUsed ? "Kullanildi" : "Yok"} />
          <Info label="Sağlayıcı" value={document.provider || document.aiProvider || "-"} />
          {document.qnbStatus ? <Info label="QNB durumu" value={qnbStatusLabel(document.qnbStatus)} /> : null}
          {document.qnbStatusCheckedAt ? <Info label="QNB kontrol" value={document.qnbStatusCheckedAt} /> : null}
          {document.qnbPulledAt ? <Info label="QNB'den alınma" value={document.qnbPulledAt} /> : null}
          {document.qnbReviewRequired ? (
            <div className="preview-error-panel" role="status">
              <strong>{document.qnbStatus === "unknown" ? "QNB durumu doğrulanamadı" : `QNB belgesi ${qnbStatusLabel(document.qnbStatus).toLocaleLowerCase("tr-TR")}`}</strong>
              <p>{document.qnbStatusDetail || "Muhasebe kaydı otomatik değiştirilmedi. Müşavir kontrolü gerekiyor."}</p>
            </div>
          ) : null}
          {document.canonicalValidationStatus === "insufficient_evidence" ? (
            <div className="decision-warning"><strong>Belge kanıtı yetersiz</strong><p>Satır veya toplam bilgileri güvenle doğrulanamadı. Muhasebe taslağını onaylamadan önce özgün belgeyi kontrol edin.</p></div>
          ) : null}
          <Info label="Orijinal ref" value={document.originalDocumentRef || "-"} />
        </aside>
      </div>
    </section>
  );
}

function ValidationChoice({ label, value, selected, onClick }: { label: string; value: string; selected: string; onClick: (value: string) => void }) {
  return <button className={`validation-choice${selected === value ? " selected" : ""}`} onClick={() => onClick(value)} type="button">{label}</button>;
}

function AccountantValidationPanel({ correctionDraft, setCorrectionDraft }: { correctionDraft: CorrectionDraft; setCorrectionDraft: (value: CorrectionDraft) => void }) {
  return (
    <section className="accountant-validation-panel" aria-label="Pilot kalite doğrulama">
      <div className="statement-review-heading"><div><h3>Pilot kalite doğrulama</h3><span>Okuma ile muhasebe kararını ayrı değerlendiriyoruz.</span></div></div>
      <div className="validation-question"><strong>1. Reader belgeyi doğru okudu mu?</strong><div className="validation-choices">
        <ValidationChoice label="Doğru" value="correct" selected={correctionDraft.readerValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, readerValidation: value as CorrectionDraft["readerValidation"] })} />
        <ValidationChoice label="Hatalı" value="incorrect" selected={correctionDraft.readerValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, readerValidation: value as CorrectionDraft["readerValidation"] })} />
        <ValidationChoice label="Emin değilim" value="unsure" selected={correctionDraft.readerValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, readerValidation: value as CorrectionDraft["readerValidation"] })} />
      </div></div>
      <div className="validation-question"><strong>2. Muhasebe fişi doğru mu?</strong><div className="validation-choices">
        <ValidationChoice label="Doğru" value="correct" selected={correctionDraft.accountingValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, accountingValidation: value as CorrectionDraft["accountingValidation"] })} />
        <ValidationChoice label="Düzelttim" value="corrected" selected={correctionDraft.accountingValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, accountingValidation: value as CorrectionDraft["accountingValidation"] })} />
        <ValidationChoice label="Hatalı" value="incorrect" selected={correctionDraft.accountingValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, accountingValidation: value as CorrectionDraft["accountingValidation"] })} />
        <ValidationChoice label="Emin değilim" value="unsure" selected={correctionDraft.accountingValidation} onClick={(value) => setCorrectionDraft({ ...correctionDraft, accountingValidation: value as CorrectionDraft["accountingValidation"] })} />
      </div></div>
    </section>
  );
}

export function JournalPanel({
  correctionDraft,
  decisionStatus,
  document,
  hasUnsavedReviewChanges,
  nextKeyboardShortcuts = false,
  onApproveAndNext,
  onResetDraft,
  onFocusSource,
  onReprocessDocument,
  onRequestStatementAi,
  onSaveDecision,
  onSaveStatementDecision,
  selectedStatementLineNo,
  session,
  setCorrectionDraft,
  setSelectedStatementLineNo,
  statementAiStatus,
}: {
  correctionDraft: CorrectionDraft;
  decisionStatus: string;
  document?: PilotDocument;
  hasUnsavedReviewChanges: boolean;
  nextKeyboardShortcuts?: boolean;
  onApproveAndNext: () => void | Promise<void>;
  onResetDraft: () => void;
  onFocusSource?: (target: DocumentSourceTarget) => void;
  onReprocessDocument: () => void | Promise<void>;
  onRequestStatementAi: () => void | Promise<void>;
  onSaveDecision: (action: string, options?: ReviewLearningDecisionOptions) => void | Promise<unknown>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  selectedStatementLineNo: number;
  session: LocalSession | null;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setSelectedStatementLineNo: (value: number) => void;
  statementAiStatus: string;
}) {
  const [learningModalOpen, setLearningModalOpen] = useState(false);
  const [rulePreview, setRulePreview] = useState<RuleInterpretationView | null>(null);
  const [rulePreviewStatus, setRulePreviewStatus] = useState("");

  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>Muhasebe fişi</h2>
        <p className="empty">İşlemek için listeden belge seçin.</p>
      </section>
    );
  }
  const activeDocument = document;
  const isStatement = document.intakeCategory === "bank_statement" || document.statementLines.length > 0;
  const sourceReviewMode = !isStatement && Boolean(document.sourceReviewRows?.length);
  const accountingDraftLines = journalDraftLinesForDocument(document, selectedStatementLineNo);
  const sourceReviewDraftLines = sourceReviewDraftLinesForDocument(document);
  const generatedDraftLines = sourceReviewMode ? sourceReviewDraftLines : accountingDraftLines;
  const activeDraftLines = correctionDraft.manualDraftLines.length ? correctionDraft.manualDraftLines : generatedDraftLines;
  const totals = draftTotals(activeDraftLines);
  const needsManualDraft = !sourceReviewMode && (!generatedDraftLines.length || document.draftStatus === "manual_draft_required");
  const invalidAccountCodes = invalidDraftAccountCodes(activeDraftLines, document.chartAccounts, document);
  const newCounterpartyAccountCodes = newCounterpartyDraftAccountCodes(activeDraftLines, document.chartAccounts, document);
  const hasInvalidDraftAccounts = invalidAccountCodes.length > 0;
  const sourceReviewNeedsAccounting = sourceReviewMode && (
    !activeDraftLines.length ||
    activeDraftLines.some((line) => !normalizeAccountCodeInput(line.account_code)) ||
    activeDraftLines.every((line) => parseAmount(line.debit) === 0 && parseAmount(line.credit) === 0) ||
    !totals.balanced
  );
  const htmlSourceReady = isHtmlPreview(document)
    && document.processingStages?.reader.status === "completed"
    && document.processingStages?.currentStage === "source_ready";
  const processingIncomplete = ["queued", "processing"].includes(document.status)
    || document.draftStatus === "processing"
    || Boolean(document.processingStages && !htmlSourceReady && document.processingStages.final.status !== "completed");
  const blocksApproval = processingIncomplete || hasInvalidDraftAccounts || sourceReviewNeedsAccounting;
  const accountingDirection = accountingDirectionForDocument(document);
  const uploadDirection = uploadDirectionForDocument(document);
  const pendingDirectionConflict = hasPendingDirectionConflict(document);
  const directionSummary = [
    `Yükleme: ${directionLabel(uploadDirection)}`,
    `Mükellef açısından: ${directionLabel(accountingDirection)}`,
  ].join(" / ");

  async function onPreviewReviewRule() {
    const decisionNote = correctionDraft.reason.trim() || correctionDraft.ruleInstruction.trim();
    if (!decisionNote) {
      setRulePreviewStatus("Karar notu yazmadan kural yorumu olusturulamaz.");
      return;
    }
    setRulePreviewStatus("Fisora karar notunu yorumluyor...");
    try {
      const payload = await previewReviewRule({
        apiBaseUrl: resolvePreviewApiBaseUrl(),
        clientId: activeDocument.clientId,
        userId: session?.userId || activeDocument.uploadedBy || "mali-musavir",
        documentRef: activeDocument.id,
        action: "suggest_for_similar",
        reviewer: session?.userId || "mali-musavir",
        correctedAccountCode: correctionDraft.accountCode.trim(),
        correctedCounterpartyCode: correctionDraft.counterpartyCode.trim(),
        category: activeDocument.productCategory,
        reason: correctionDraft.reason.trim(),
        decisionNote,
        applyToSimilar: true,
        statementLineNo: selectedStatementLineNo,
        draftLines: activeDraftLines,
        sessionToken: session?.sessionToken || "",
      });
      const interpretation = normalizeRuleInterpretationView(asRecord(payload).rule_interpretation);
      setRulePreview(interpretation);
      setLearningModalOpen(true);
      setRulePreviewStatus(interpretation ? "Yorum hazir." : "Sistem bu nottan net kural olusturamadi.");
    } catch (error) {
      setRulePreviewStatus(error instanceof Error ? error.message : String(error));
    }
  }

  function saveLearningDecision(learningConfirmation: "save_rule" | "suggest_similar") {
    void onSaveDecision("suggest_for_similar", {
      learningConfirmation,
      confirmedRuleInterpretation: rulePreview,
    });
    setLearningModalOpen(false);
  }

  function setManualDraftLine(index: number, patch: Partial<DraftLine>) {
    const lines = correctionDraft.manualDraftLines.length ? correctionDraft.manualDraftLines : (generatedDraftLines.length ? generatedDraftLines : [blankDraftLine(), blankDraftLine()]);
    setCorrectionDraft({
      ...correctionDraft,
      manualDraftLines: lines.map((line, lineIndex) => (lineIndex === index ? { ...line, ...patch } : line)),
    });
  }

  function addManualDraftLine() {
    setCorrectionDraft({
      ...correctionDraft,
      manualDraftLines: [...activeDraftLines, blankDraftLine()],
    });
  }

  function removeManualDraftLine(index: number) {
    setCorrectionDraft({
      ...correctionDraft,
      manualDraftLines: activeDraftLines.filter((_, lineIndex) => lineIndex !== index),
    });
  }

  function handleJournalShortcut(event: KeyboardEvent<HTMLElement>) {
    if (nextKeyboardShortcuts) return;
    if (pendingDirectionConflict) return;
    if (blocksApproval) return;
    if (event.key === "F2" || (event.key === "Enter" && event.ctrlKey)) {
      event.preventDefault();
      void onApproveAndNext();
    }
  }

  return (
    <section className={`review-panel journal-panel ${isStatement ? "statement-mode" : ""}${nextKeyboardShortcuts ? " next-review" : ""}`} onKeyDown={handleJournalShortcut}>
      <div className="journal-scroll-area">
        <div className="panel-heading journal-next-heading">
          <div>
            <h2>{nextKeyboardShortcuts ? "Mahsup Fişi Taslağı" : "Muhasebe fişi"}</h2>
            <span>{nextKeyboardShortcuts ? (document.issueDate || document.period || "") : `${document.clientName} için belge, fiş ve kontrol kararları`}</span>
          </div>
          {nextKeyboardShortcuts ? (
            <span className={`next-balance-pill ${totals.balanced && activeDraftLines.length ? "balanced" : "warning"}`}>
              {activeDraftLines.length ? (totals.balanced ? "✓ Dengeli" : "Denge kontrolü") : "Taslak yok"}
            </span>
          ) : null}
        </div>
        <section className={`journal-status-strip ${totals.balanced ? "" : "unbalanced"}`} aria-label="Fiş durumu">
          <div className="journal-status-primary">
            <span>Fiş durumu</span>
            <strong>{sourceReviewMode ? "Kaynak satırlar hazır" : formatDraftStatus(document.draftStatus)}</strong>
            <small>{directionSummary}</small>
          </div>
          <div className="journal-status-metrics" aria-label="Fiş toplamları">
            <span><strong>Borç</strong> {totals.debit.toFixed(2)}</span>
            <span><strong>Alacak</strong> {totals.credit.toFixed(2)}</span>
            {!nextKeyboardShortcuts ? <span><strong>Denge</strong> {activeDraftLines.length ? (totals.balanced ? "Dengeli" : "Dengesiz") : "Taslak yok"}</span> : null}
          </div>
        </section>
        {hasUnsavedReviewChanges ? (
          <section className="dirty-state-strip" aria-label="Kaydedilmemiş fiş değişikliği">
            <div>
              <strong>Değişiklik var</strong>
              <span>Onayla ve sonraki belgeye geç dediğinizde bu fiş kararın içinde kaydedilir.</span>
            </div>
            <button onClick={onResetDraft} type="button">İlk taslağa dön</button>
          </section>
        ) : null}
        {session?.role === "accountant" ? (
          nextKeyboardShortcuts ? (
            <details className="journal-advanced-details">
              <summary>Pilot kalite doğrulama</summary>
              <AccountantValidationPanel correctionDraft={correctionDraft} setCorrectionDraft={setCorrectionDraft} />
            </details>
          ) : (
            <AccountantValidationPanel correctionDraft={correctionDraft} setCorrectionDraft={setCorrectionDraft} />
          )
        ) : null}
        <ManualDraftEditor
          activeDraftLines={activeDraftLines}
          chartAccounts={document.chartAccounts}
          generatedDraftLines={generatedDraftLines}
          invalidAccountCodes={invalidAccountCodes}
          newCounterpartyAccountCodes={newCounterpartyAccountCodes}
          needsManualDraft={needsManualDraft}
          sourceReviewMode={sourceReviewMode}
          sourceReviewTotalCount={document.sourceReviewRows?.length ?? 0}
          onAddLine={addManualDraftLine}
          onFocusSource={onFocusSource}
          onRemoveLine={removeManualDraftLine}
          onUpdateLine={setManualDraftLine}
        />
        {!nextKeyboardShortcuts && !pendingDirectionConflict ? (
          <section className="journal-primary-approve" aria-label="Ana fiş kararı">
            <button disabled={blocksApproval} onClick={onApproveAndNext} type="button">Onayla ve geç</button>
          </section>
        ) : null}
        {isStatement ? (
          <StatementReviewPanel
            correctionDraft={correctionDraft}
            document={document}
            onRequestStatementAi={onRequestStatementAi}
            onSaveStatementDecision={onSaveStatementDecision}
            selectedStatementLineNo={selectedStatementLineNo}
            setCorrectionDraft={setCorrectionDraft}
            setSelectedStatementLineNo={setSelectedStatementLineNo}
            statementAiStatus={statementAiStatus}
          />
        ) : null}
        <details className={nextKeyboardShortcuts ? "journal-advanced-details journal-learning-details" : "journal-learning-details"} open={!nextKeyboardShortcuts}>
          <summary hidden={!nextKeyboardShortcuts}>Karar notu ve öğrenme</summary>
          <section className="journal-correction-panel" aria-label="Karar notu">
          <div className="statement-review-heading">
            <div>
              <h3>Karar notu</h3>
              <span>Hesap ve cari değişikliği fiş satırında yapılır; bu not karar kaydı ve benzer belge öğrenme adayı için kullanılır.</span>
            </div>
          </div>
          <div className="correction-form">
            <label className="wide">
              <span>Karar notu</span>
              <textarea
                onChange={(event) => setCorrectionDraft({ ...correctionDraft, reason: event.target.value })}
                placeholder="Bu fişte neyi neden değiştirdiniz? Benzer belgelerde nasıl uygulanmalı?"
                rows={3}
                value={correctionDraft.reason}
              />
            </label>
            <label className="checkbox-row wide">
              <input
                checked={correctionDraft.applyToSimilar}
                onChange={(event) => setCorrectionDraft({ ...correctionDraft, applyToSimilar: event.target.checked })}
                type="checkbox"
              />
              <span>Benzerleri için öneri olarak kullan</span>
            </label>
          </div>
          <div className="learning-rule-actions">
            <button onClick={onPreviewReviewRule} type="button">Egitim notunu kaydet</button>
            {rulePreviewStatus ? <span>{rulePreviewStatus}</span> : null}
          </div>
          <RuleInterpretationCard document={document} />
          {learningModalOpen ? (
            <section className="learning-rule-modal" aria-label="Fisora karar notu yorumu">
              <div className="learning-rule-dialog">
                <div className="statement-review-heading">
                  <div>
                    <h3>Fisora bunu boyle anladi</h3>
                    <span>Ilk uygulamalarda musavir kontrolu devam eder.</span>
                  </div>
                  <button onClick={() => setLearningModalOpen(false)} type="button">Kapat</button>
                </div>
                {rulePreview ? (
                  <div className="rule-interpretation-details">
                    <div><span>Ozet</span><strong>{rulePreview.summaryTr || "-"}</strong></div>
                    <div><span>Tetikleyici</span><strong>{rulePreview.triggerTr || "-"}</strong></div>
                    <div><span>Uygulama</span><strong>{rulePreview.actionTr || "-"}</strong></div>
                    <div><span>Guvenlik</span><strong>{rulePreview.guardrailTr || "Ilk uygulamalarda musavir kontrolu istenir."}</strong></div>
                  </div>
                ) : (
                  <p className="empty">Bu nottan net kural olusmadi; karar notunu daha dar yazin.</p>
                )}
                <div className="decision-actions secondary-actions">
                  <button disabled={!rulePreview || rulePreview.status !== "ready"} onClick={() => saveLearningDecision("save_rule")} type="button">Kural olarak kaydet</button>
                  <button disabled={!rulePreview} onClick={() => saveLearningDecision("suggest_similar")} type="button">Benzerlerde oner</button>
                </div>
              </div>
            </section>
          ) : null}
          </section>
        </details>
        <JournalReasonDisclosure document={document} />
      </div>
      {nextKeyboardShortcuts ? (
        <section className="journal-next-actions" aria-label="Belge kararı">
          {pendingDirectionConflict ? (
            <button className="primary" onClick={() => onSaveDecision("accept_detected_direction")} type="button">Yönü çöz</button>
          ) : (
            <>
              <button disabled={hasInvalidDraftAccounts} onClick={() => onSaveDecision("review_required")} type="button">Kontrolde tut</button>
              <button className="danger" onClick={() => onSaveDecision("exclude_export")} type="button">Hariç tut</button>
              <button className="primary" disabled={blocksApproval} onClick={onApproveAndNext} type="button">Onayla ve sonraki →</button>
            </>
          )}
        </section>
      ) : (
        <JournalDecisionBar
          decisionStatus={decisionStatus}
          document={document}
          hasInvalidDraftAccounts={hasInvalidDraftAccounts}
          onReprocessDocument={onReprocessDocument}
          onSaveDecision={onSaveDecision}
          pendingDirectionConflict={pendingDirectionConflict}
        />
      )}
    </section>
  );
}

function JournalDecisionBar({
  decisionStatus,
  document,
  hasInvalidDraftAccounts,
  onReprocessDocument,
  onSaveDecision,
  pendingDirectionConflict,
}: {
  decisionStatus: string;
  document: PilotDocument;
  hasInvalidDraftAccounts: boolean;
  onReprocessDocument: () => void | Promise<void>;
  onSaveDecision: (action: string, options?: ReviewLearningDecisionOptions) => void | Promise<unknown>;
  pendingDirectionConflict: boolean;
}) {
  return (
    <section className="journal-decision-bar" aria-label="Belge değerlendirme">
      <div className="journal-decision-heading">
        <div>
          <h3>Belge değerlendirme</h3>
          <span>{decisionStatus || "Bu belge için henüz müşavir kararı verilmedi."}</span>
        </div>
      </div>
      {pendingDirectionConflict ? (
        <>
          <div className="accountant-guidance">
            <strong>Yön çakışması</strong>
            <p>{document.directionConflict?.questionTr || "Yükleme yönü ile mükellef açısından tespit edilen yön çakışıyor."}</p>
          </div>
          <div className="decision-actions direction-actions">
            <button onClick={() => onSaveDecision("accept_detected_direction")} type="button">Sistemin tespit ettiği yöne geçir</button>
            <button onClick={() => onSaveDecision("keep_upload_direction")} type="button">Yükleme tarafı doğru</button>
          </div>
        </>
      ) : (
        <div className="decision-actions secondary-actions">
          <button disabled={hasInvalidDraftAccounts} onClick={() => onSaveDecision("review_required")} type="button">Kontrol için beklet</button>
          <button disabled={hasInvalidDraftAccounts} onClick={() => onSaveDecision("suggest_for_similar")} type="button">Benzerleri için öneri yap</button>
          <button onClick={onReprocessDocument} type="button">Yeniden işle</button>
          <button onClick={() => onSaveDecision("exclude_export")} type="button">Çıktı listesine ekleme</button>
        </div>
      )}
    </section>
  );
}

function RuleInterpretationCard({ document }: { document: PilotDocument }) {
  const interpretation = document.ruleInterpretation;
  if (!interpretation) return null;
  const needsClarification = interpretation.status === "needs_clarification";
  const title = needsClarification ? "Netleştirme gerekiyor" : "Fisora'nın anladığı";
  const detailRows = [
    ["Tetikleyici", interpretation.triggerTr],
    ["Uygulama", interpretation.actionTr],
    ["Kontrol", interpretation.guardrailTr],
  ].filter(([, value]) => value);
  return (
    <section className={`rule-interpretation-card ${needsClarification ? "needs-clarification" : "ready"}`} aria-label={title}>
      <div>
        <span>{title}</span>
        <strong>{interpretation.summaryTr || "Karar notu kural adayına çevrildi."}</strong>
      </div>
      {detailRows.length ? (
        <div className="rule-interpretation-details">
          {detailRows.map(([label, value]) => (
            <Info key={label} label={label} value={value} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function JournalReasonDisclosure({ document }: { document: PilotDocument }) {
  const narrative = document.decisionNarrative;
  const summaryRows = [
    ["Fatura ürün satırı", narrative?.invoiceProductLine || document.productLine || "-"],
    ["Fisora yorumu", narrative?.fisoraInterpretation || document.aiProductIdentity || document.productCategory || "-"],
    ["Faaliyet ilişkisi", narrative?.businessRelation || document.businessRelation || "-"],
    ["Hesap önerisi", [narrative?.accountCode || document.selectedExpenseAccount || document.selectedRevenueAccount, narrative?.accountName].filter(Boolean).join(" / ") || "-"],
    ["Cari eşleşme", narrative?.counterpartyMatch || document.counterpartyTitle || document.selectedCounterpartyAccount || "-"],
    ["Güven", narrative?.confidenceLabel || (document.draftConfidence ? `%${document.draftConfidence}` : "-")],
  ];
  const readFacts = Object.entries(narrative?.readFacts ?? {});
  const unresolved = narrative?.unresolvedInfo || "";
  return (
    <section className="journal-reason-disclosure" aria-label="Fisora karar özeti">
      <details>
        <summary>
          <span>Fisora Özeti</span>
          <strong>{narrative?.confidenceLabel || formatDraftStatus(document.draftStatus)}</strong>
        </summary>
        <div className="ai-guidance compact fisora-summary-grid">
          {summaryRows.map(([label, value]) => (
            <ReasonCard key={label} label={label} value={value} />
          ))}
        </div>
        {readFacts.length ? (
          <details className="decision-narrative-section">
            <summary>Faturadan Okunan Bilgiler</summary>
            <div className="decision-chain-steps">
              {readFacts.map(([label, value]) => (
                <Info key={label} label={label} value={String(value)} />
              ))}
            </div>
          </details>
        ) : null}
        {unresolved ? (
          <details className="decision-narrative-section">
            <summary>Netleşmeyen Bilgiler</summary>
            <p>{unresolved}</p>
          </details>
        ) : null}
        <LearningRuleCard document={document} />
        <details className="decision-narrative-section technical">
          <summary>Teknik İz</summary>
          <QualityScorecardPanel document={document} />
          <AiTracePanel document={document} />
        </details>
      </details>
    </section>
  );
}

function QualityScorecardPanel({ document }: { document: PilotDocument }) {
  const scorecard = asRecord(document.aiQualityScorecard);
  if (!Object.keys(scorecard).length) return null;
  const staticDecision = asRecord(scorecard.static);
  const aiDecision = asRecord(scorecard.ai);
  const finalDecision = asRecord(scorecard.final);
  const accountantFinal = asRecord(scorecard.accountant_final_decision);
  const delta = asRecord(scorecard.quality_delta);
  const finalValue = [
    qualityText(finalDecision, "direction"),
    qualityText(finalDecision, "selected_account_code"),
    qualityText(finalDecision, "selected_counterparty_account"),
  ].filter((value) => value !== "-").join(" / ") || "-";
  const accountantValue = Object.keys(accountantFinal).length
    ? [
        qualityText(accountantFinal, "action"),
        qualityText(accountantFinal, "selected_account_code"),
        qualityText(accountantFinal, "selected_counterparty_account"),
      ].filter((value) => value !== "-").join(" / ")
    : "Henüz karar yok";
  return (
    <section className="ai-guidance compact" aria-label="Karar kalitesi">
      <ReasonCard label="İlk taslak" value={`${qualityText(staticDecision, "category")} / %${qualityText(staticDecision, "confidence", "0")}`} />
      <ReasonCard label="AI" value={`${qualityText(aiDecision, "provider", "Gerekmedi")} / ${qualityText(aiDecision, "category")} / %${qualityText(aiDecision, "confidence", "0")}`} />
      <ReasonCard label="Sistem final taslağı" value={finalValue} />
      <ReasonCard label="Müşavir finali" value={accountantValue} />
      <ReasonCard label="Fark" value={`${qualityText(delta, "decision", "bekliyor")} / değişen: ${qualityText(delta, "changed_fields", "Yok")}`} />
    </section>
  );
}

function ManualDraftEditor({
  activeDraftLines,
  chartAccounts,
  generatedDraftLines,
  invalidAccountCodes,
  newCounterpartyAccountCodes,
  needsManualDraft,
  sourceReviewMode,
  sourceReviewTotalCount,
  onAddLine,
  onFocusSource,
  onRemoveLine,
  onUpdateLine,
}: {
  activeDraftLines: DraftLine[];
  chartAccounts: ChartAccountOption[];
  generatedDraftLines: DraftLine[];
  invalidAccountCodes: string[];
  newCounterpartyAccountCodes: string[];
  needsManualDraft: boolean;
  sourceReviewMode: boolean;
  sourceReviewTotalCount: number;
  onAddLine: () => void;
  onFocusSource?: (target: DocumentSourceTarget) => void;
  onRemoveLine: (index: number) => void;
  onUpdateLine: (index: number, patch: Partial<DraftLine>) => void;
}) {
  const descriptionRefs = useRef<Array<HTMLInputElement | null>>([]);
  const debitRefs = useRef<Array<HTMLInputElement | null>>([]);
  const creditRefs = useRef<Array<HTMLInputElement | null>>([]);

  if (!sourceReviewMode && !needsManualDraft && !activeDraftLines.length) return null;
  const rows = activeDraftLines.length ? activeDraftLines : sourceReviewMode ? [] : [blankDraftLine(), blankDraftLine()];

  function focusInput(refs: MutableRefObject<Array<HTMLInputElement | null>>, index: number) {
    window.setTimeout(() => refs.current[index]?.focus(), 0);
  }

  function selectAccount(index: number, account: ChartAccountOption) {
    const updated = applyAccountSelectionToLine(rows[index], account, chartAccounts);
    onUpdateLine(index, updated);
    focusInput(descriptionRefs, index);
  }

  function updateDebit(index: number, value: string) {
    onUpdateLine(index, {
      debit: value,
      ...(value.trim() && parseAmount(value) !== 0 ? { credit: "0.00" } : {}),
    });
  }

  function updateCredit(index: number, value: string) {
    onUpdateLine(index, {
      credit: value,
      ...(value.trim() && parseAmount(value) !== 0 ? { debit: "0.00" } : {}),
    });
  }

  function sourceTargetForLine(line: DraftLine, index: number): DocumentSourceTarget | null {
    const text = String(line.source_text || line.description || "").trim();
    const sourceLineNumbers = Array.isArray(line.source_line_numbers) ? line.source_line_numbers : [];
    if (!text && !line.source_position && !sourceLineNumbers.length) return null;
    return {
      key: `${line.source_position || sourceLineNumbers.join("-") || index + 1}`,
      text,
      sourcePosition: line.source_position || "",
      sourceLineNumbers,
    };
  }

  return (
    <section className="manual-draft-panel">
      <div className="statement-review-heading">
        <div>
          <h3>{sourceReviewMode || generatedDraftLines.length ? "Fiş satırları" : "Manuel fiş satırları"}</h3>
          <span>{sourceReviewMode ? `PDF'den ${generatedDraftLines.length}/${sourceReviewTotalCount} çalışma satırı hazır. Hesap ve borç/alacak kararını müşavir tamamlayabilir.` : generatedDraftLines.length ? "Taslağı düzeltip onaylayabilirsiniz." : "Taslak oluşmadı; satırları girerek belgeyi tamamlayın."}</span>
        </div>
        <button onClick={onAddLine} type="button">Satır ekle</button>
      </div>
      {sourceReviewMode && !rows.length ? (
        <p className="empty">PDF satırları okundu; bu belgede fişe doğrudan taşınacak sıfırdan farklı çalışma satırı yok.</p>
      ) : null}
      <div className="table-wrap journal-ledger">
        <table>
          <thead>
            <tr>
              <th>Hesap</th>
              <th>Açıklama</th>
              <th>Borç</th>
              <th>Alacak</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((line, index) => {
              const sourceTarget = sourceTargetForLine(line, index);
              return (
              <tr
                className={sourceTarget ? "journal-source-row" : undefined}
                key={index}
                onClick={(event) => {
                  if (!sourceTarget || !onFocusSource) return;
                  const target = event.target as HTMLElement;
                  if (target.closest("input, button, select, textarea, a")) return;
                  onFocusSource(sourceTarget);
                }}
              >
                <td>
                  <AccountCodeCombobox
                    accounts={chartAccounts}
                    onChange={(value) => onUpdateLine(index, { account_code: value })}
                    onSelect={(account) => selectAccount(index, account)}
                    value={line.account_code}
                  />
                  {invalidAccountCodes.includes(normalizeAccountCodeInput(line.account_code)) ? (
                    <small className="field-warning">Hesap planında olmayan veya seçilemeyen kod.</small>
                  ) : null}
                  {newCounterpartyAccountCodes.includes(normalizeAccountCodeInput(line.account_code)) ? (
                    <small className="field-notice">
                      Yeni cari hesabı önerisi. Hesap planında henüz yok; mevcut cariyi seçin veya müşavir onayıyla yeni cari açın.
                    </small>
                  ) : null}
                </td>
                <td>
                  <input
                    onChange={(event) => onUpdateLine(index, { description: event.target.value })}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        focusInput(debitRefs, index);
                      }
                    }}
                    ref={(element) => { descriptionRefs.current[index] = element; }}
                    value={line.description}
                  />
                  {sourceTarget ? (
                    <button
                      className="field-notice source-review-evidence source-review-link"
                      onClick={() => onFocusSource?.(sourceTarget)}
                      title="Kaynak belgede bu satırı bul"
                      type="button"
                    >
                      ↗ Kaynak satır {line.source_position || line.source_line_numbers?.join(", ") || index + 1}: {line.source_amount || "metni göster"}
                      {line.source_amount_label ? ` · ${line.source_amount_label}` : ""}
                      {line.source_amount_basis ? ` · ${sourceAmountBasisLabel(line.source_amount_basis)}` : ""}
                    </button>
                  ) : null}
                  {vatGroupEvidenceText(line) ? (
                    <small className="field-notice">
                      {vatGroupEvidenceText(line)}
                      <br />
                      Grup hesabı: {line.account_code} · {line.description || "Hesap açıklaması"}
                    </small>
                  ) : null}
                </td>
                <td>
                  <input
                    inputMode="decimal"
                    onChange={(event) => updateDebit(index, event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        focusInput(creditRefs, index);
                      }
                    }}
                    ref={(element) => { debitRefs.current[index] = element; }}
                    value={line.debit}
                  />
                </td>
                <td>
                  <input
                    inputMode="decimal"
                    onChange={(event) => updateCredit(index, event.target.value)}
                    ref={(element) => { creditRefs.current[index] = element; }}
                    value={line.credit}
                  />
                </td>
                <td><button onClick={() => onRemoveLine(index)} type="button">Sil</button></td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AccountCodeCombobox({
  accounts,
  onChange,
  onSelect,
  value,
}: {
  accounts: ChartAccountOption[];
  onChange: (value: string) => void;
  onSelect: (account: ChartAccountOption) => void;
  value: string;
}) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [popupPosition, setPopupPosition] = useState({ left: 16, top: 16 });
  const matches = useMemo(() => filterAccountOptions(accounts, value, 20), [accounts, value]);

  function updatePopupPosition() {
    const input = inputRef.current;
    if (!input) return;
    const rect = input.getBoundingClientRect();
    const viewportWidth = window.innerWidth || 0;
    const popupWidth = Math.min(520, Math.max(0, viewportWidth - 32));
    const left = Math.max(16, Math.min(rect.left, viewportWidth - popupWidth - 16));
    setPopupPosition({
      left,
      top: rect.bottom + 4,
    });
  }

  useEffect(() => {
    if (!open) return undefined;
    updatePopupPosition();
    window.addEventListener("resize", updatePopupPosition);
    window.addEventListener("scroll", updatePopupPosition, true);
    return () => {
      window.removeEventListener("resize", updatePopupPosition);
      window.removeEventListener("scroll", updatePopupPosition, true);
    };
  }, [open, value]);

  function selectActiveAccount() {
    const selected = resolveAccountSelection(accounts, value, activeIndex);
    if (!selected) return false;
    onSelect(selected);
    setOpen(false);
    setActiveIndex(0);
    return true;
  }

  const popupStyle = {
    "--account-options-left": `${popupPosition.left}px`,
    "--account-options-top": `${popupPosition.top}px`,
  } as CSSProperties;

  return (
    <div className="account-code-combobox">
      <input
        aria-label="Hesap kodu"
        aria-expanded={open && matches.length > 0}
        autoComplete="off"
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onChange={(event) => {
          onChange(event.target.value);
          setActiveIndex(0);
          updatePopupPosition();
          setOpen(true);
        }}
        onFocus={() => {
          updatePopupPosition();
          setOpen(Boolean(value));
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            updatePopupPosition();
            setOpen(true);
            setActiveIndex((current) => Math.min(current + 1, Math.max(matches.length - 1, 0)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((current) => Math.max(current - 1, 0));
          } else if (event.key === "Enter" || event.key === "Tab") {
            if (selectActiveAccount()) event.preventDefault();
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
        ref={inputRef}
        value={value}
      />
      {open && matches.length ? (
        <div className="account-code-options" role="listbox" style={popupStyle}>
          {matches.map((account, index) => (
            <button
              aria-disabled={!account.isDetail}
              className={index === activeIndex ? "active" : ""}
              disabled={!account.isDetail}
              key={account.code}
              onMouseDown={(event) => {
                event.preventDefault();
                if (!account.isDetail) return;
                onSelect(account);
                setOpen(false);
              }}
              type="button"
            >
              <span>{account.code}</span>
              <strong>{account.name}</strong>
              {!account.isDetail ? <em>Detay hesap seçin</em> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function LearningRuleCard({ document }: { document: PilotDocument }) {
  const hasLearningSignal = Boolean(
    document.accountingIntent ||
    document.learningRuleReason ||
    document.learningRuleSourceSummary ||
    document.rulePrompt.show,
  );
  if (!hasLearningSignal) return null;
  return (
    <section className="learning-rule-card">
      <div>
        <span>Öğrenme kaynağı</span>
        <strong>{document.rulePrompt.message || document.learningRuleSourceSummary || document.learningRuleReason}</strong>
      </div>
      <div className="learning-rule-meta">
        <Info label="Muhasebe niyeti" value={document.accountingIntent || "-"} />
        <Info label="Güven düzeyi" value={document.accountingIntentConfidence ? `%${document.accountingIntentConfidence}` : "-"} />
        <Info label="Mükellef kararı" value={String(document.rulePrompt.clientConsistentDecisionCount || 0)} />
        <Info label="Otomasyon adayı" value={`${document.rulePrompt.officeDistinctClientCount || 0} / ${document.rulePrompt.officeConsistentDecisionCount || 0}`} />
      </div>
    </section>
  );
}

function StatementReviewPanel({
  correctionDraft,
  document,
  onRequestStatementAi,
  onSaveStatementDecision,
  selectedStatementLineNo,
  setCorrectionDraft,
  setSelectedStatementLineNo,
  statementAiStatus,
}: {
  correctionDraft: CorrectionDraft;
  document: PilotDocument;
  onRequestStatementAi: () => void | Promise<void>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  selectedStatementLineNo: number;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setSelectedStatementLineNo: (value: number) => void;
  statementAiStatus: string;
}) {
  if (!document.statementLines.length) return null;
  const selectedLine = document.statementLines.find((line) => line.line_no === selectedStatementLineNo) ?? document.statementLines[0];
  const selectedEntry = document.statementEntries.find((entry) => entry.statement_line_no === selectedLine.line_no);
  const selectedSuggestion = document.statementAiSuggestions.find((suggestion) => suggestion.line_no === selectedLine.line_no);
  const approvedCount = document.statementLines.filter((line) => line.accountant_review_status === "approved").length;
  const riskCount = document.statementLines.filter((line) => line.risk_flags.length > 0 && line.accountant_review_status !== "approved").length;

  function applyAiSuggestion() {
    if (!selectedSuggestion) return;
    setCorrectionDraft({
      ...correctionDraft,
      counterpartyCode: selectedSuggestion.suggested_account_code || correctionDraft.counterpartyCode,
      reason: selectedSuggestion.reason || correctionDraft.reason,
    });
  }

  return (
    <section className="statement-review-panel">
      <div className="statement-review-heading">
        <div>
          <h3>Banka satırları</h3>
          <span>{approvedCount}/{document.statementLines.length} onaylı / {riskCount} riskli</span>
        </div>
        <button onClick={onRequestStatementAi} type="button">AI önerisi al</button>
      </div>

      <div className="statement-grid">
        <div className="statement-lines-list">
          <table>
            <thead>
              <tr>
                <th>No</th>
                <th>Tarih</th>
                <th>Açıklama</th>
                <th>Yön</th>
                <th>Tutar</th>
                <th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {document.statementLines.map((line) => (
                <tr className={line.line_no === selectedLine.line_no ? "selected-row" : ""} key={line.line_no}>
                  <td>
                    <button className="line-select" onClick={() => setSelectedStatementLineNo(line.line_no)} type="button">
                      {line.line_no}
                    </button>
                  </td>
                  <td>{line.transaction_date || "-"}</td>
                  <td>{line.description || "-"}</td>
                  <td>{statementDirectionLabel(line.direction)}</td>
                  <td>{line.amount}</td>
                  <td>{statementStatusLabel(line.accountant_review_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="statement-line-detail">
          <div className="statement-detail-meta">
            <Info label="İşlem tipi" value={statementTypeLabels[selectedLine.transaction_type] ?? selectedLine.transaction_type} />
            <Info label="Karşı hesap" value={selectedLine.suggested_account_code || selectedLine.counterparty_match_code || "-"} />
            <Info label="Güven" value={String(selectedLine.confidence)} />
          </div>
          <div className="statement-risk-tags">
            {selectedLine.risk_flags.length ? selectedLine.risk_flags.map((flag) => <span key={flag}>{flag}</span>) : <span>risk_yok</span>}
          </div>
          <div className="statement-ai-box">
            <div>
              <span>AI önerisi</span>
              <strong>{selectedSuggestion ? `${statementTypeLabels[selectedSuggestion.transaction_type] ?? selectedSuggestion.transaction_type} / ${selectedSuggestion.suggested_account_code || "-"}` : "Yok"}</strong>
              <small>{selectedSuggestion?.reason || document.statementAiSummary || statementAiStatus || "-"}</small>
            </div>
            <button disabled={!selectedSuggestion} onClick={applyAiSuggestion} type="button">Uygula</button>
          </div>
          <div className="statement-entry-ref">
            <Info label="Fiş referansı" value={selectedEntry?.statement_fingerprint || selectedEntry?.source_document_ref || "-"} />
            <Info label="Fiş durumu" value={statementStatusLabel(selectedEntry?.accountant_review_status)} />
          </div>
          <div className="statement-actions">
            <button onClick={() => onSaveStatementDecision("approve")} type="button">Satırı onayla</button>
            <button onClick={() => onSaveStatementDecision("approve_with_changes")} type="button">Değişiklikle kaydet</button>
            <button onClick={() => onSaveStatementDecision("suggest_for_similar")} type="button">Benzerleri için öneri yap</button>
            <button onClick={() => onSaveStatementDecision("exclude_from_export")} type="button">Çıktı listesine ekleme</button>
            <button onClick={() => onSaveStatementDecision("wrong_account")} type="button">Kontrolde tut</button>
          </div>
        </div>
      </div>
    </section>
  );
}
