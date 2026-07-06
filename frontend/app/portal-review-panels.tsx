"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, MutableRefObject } from "react";
import { applyAccountSelectionToLine, filterAccountOptions, resolveAccountSelection } from "./portal-account-combobox";
import { Info, ReasonCard } from "./portal-shared";
import type { ChartAccountOption, CorrectionDraft, DocumentPipelineEvent, DraftLine, LocalSession, PilotDocument, PilotStatus, StatementLineReview } from "./portal-types";
import { resolveApiBaseUrl } from "./upload-api";

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

function uploadDirectionForDocument(document: PilotDocument) {
  if (document.intakeCategory === "sales_invoice") return "sales";
  if (document.intakeCategory === "purchase_invoice") return "purchase";
  return "";
}

function hasPendingDirectionConflict(document: PilotDocument) {
  return document.directionConflict?.status === "needs_review";
}

function previewAuthHeaders(session: LocalSession | null | undefined, document?: PilotDocument): Record<string, string> {
  if (session?.sessionToken) return { "X-Fisora-Session": session.sessionToken };
  const userId = session?.userId || document?.uploadedBy || "";
  const headerUserId = safeHeaderValue(userId);
  return headerUserId ? { "X-Fisora-User-Id": headerUserId } : {};
}

function safeHeaderValue(value: string) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  return /^[\x00-\xff]*$/.test(trimmed) ? trimmed : encodeURIComponent(trimmed);
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
  return (
    <details className="ai-trace-panel">
      <summary>
        <span>AI karar izi</span>
        <strong>{stages.length ? `${stages.length} AI adımı` : "Kayıt yok"}</strong>
      </summary>
      {stages.length ? (
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
        </div>
      ) : (
        <p className="empty">Bu belge için AI trace kaydı yok.</p>
      )}
    </details>
  );
}

export function DocumentPreview({ document, session }: { document?: PilotDocument; session?: LocalSession | null }) {
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

  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>Orijinal belge</h2>
        <p className="empty">Belge seçimi yok.</p>
      </section>
    );
  }
  const pipelineProblem = latestPipelineProblem(document);
  const errorMessage = previewError || pipelineProblem?.messageTr || "Gerçek belge henüz önizlenemiyor.";
  const canFramePreview = isFramePreviewMime(document.originalDocumentMimeType);
  return (
    <section className="review-panel document-panel">
      <div className="panel-heading">
        <div>
          <h2>Orijinal belge</h2>
          <span>{document.fileName}</span>
        </div>
        <span className={`status ${document.status}`}>{formatStatus(document.status)}</span>
      </div>
      <div className="document-preview-layout">
        <div className="document-canvas">
          {previewUrl ? (
            isImageMime(document.originalDocumentMimeType) ? (
              <img alt={`${document.fileName} orijinal belge`} className="original-document-image" src={previewUrl} />
            ) : canFramePreview ? (
              <iframe className="original-document-frame" src={previewUrl} title={`${document.fileName} orijinal belge`} />
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
          <Info label="Orijinal ref" value={document.originalDocumentRef || "-"} />
        </aside>
      </div>
    </section>
  );
}

export function JournalPanel({
  correctionDraft,
  decisionStatus,
  document,
  hasUnsavedReviewChanges,
  onApproveAndNext,
  onResetDraft,
  onReprocessDocument,
  onRequestStatementAi,
  onSaveDecision,
  onSaveStatementDecision,
  selectedStatementLineNo,
  setCorrectionDraft,
  setSelectedStatementLineNo,
  statementAiStatus,
}: {
  correctionDraft: CorrectionDraft;
  decisionStatus: string;
  document?: PilotDocument;
  hasUnsavedReviewChanges: boolean;
  onApproveAndNext: () => void | Promise<void>;
  onResetDraft: () => void;
  onReprocessDocument: () => void | Promise<void>;
  onRequestStatementAi: () => void | Promise<void>;
  onSaveDecision: (action: string) => void | Promise<void>;
  onSaveStatementDecision: (action: string) => void | Promise<void>;
  selectedStatementLineNo: number;
  setCorrectionDraft: (value: CorrectionDraft) => void;
  setSelectedStatementLineNo: (value: number) => void;
  statementAiStatus: string;
}) {
  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>Muhasebe fişi</h2>
        <p className="empty">Belge seçimi yok.</p>
      </section>
    );
  }
  const generatedDraftLines = journalDraftLinesForDocument(document, selectedStatementLineNo);
  const activeDraftLines = correctionDraft.manualDraftLines.length ? correctionDraft.manualDraftLines : generatedDraftLines;
  const totals = draftTotals(activeDraftLines);
  const needsManualDraft = !generatedDraftLines.length || document.draftStatus === "manual_draft_required";
  const isStatement = document.intakeCategory === "bank_statement" || document.statementLines.length > 0;
  const accountingDirection = accountingDirectionForDocument(document);
  const uploadDirection = uploadDirectionForDocument(document);
  const pendingDirectionConflict = hasPendingDirectionConflict(document);
  const directionSummary = [
    `Yükleme: ${directionLabel(uploadDirection)}`,
    `Mükellef açısından: ${directionLabel(accountingDirection)}`,
  ].join(" / ");

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
    if (pendingDirectionConflict) return;
    if (event.key === "F2" || (event.key === "Enter" && event.ctrlKey)) {
      event.preventDefault();
      void onApproveAndNext();
    }
  }

  return (
    <section className={`review-panel journal-panel ${isStatement ? "statement-mode" : ""}`} onKeyDown={handleJournalShortcut}>
      <div className="journal-scroll-area">
        <div className="panel-heading">
          <div>
            <h2>Muhasebe fişi</h2>
            <span>{document.clientName} için belge, fiş ve kontrol kararları</span>
          </div>
        </div>
        <section className={`journal-status-strip ${totals.balanced ? "" : "unbalanced"}`} aria-label="Fiş durumu">
          <div className="journal-status-primary">
            <span>Fiş durumu</span>
            <strong>{formatDraftStatus(document.draftStatus)}</strong>
            <small>{directionSummary}</small>
          </div>
          <div className="journal-status-metrics" aria-label="Fiş toplamları">
            <span><strong>Borç</strong> {totals.debit.toFixed(2)}</span>
            <span><strong>Alacak</strong> {totals.credit.toFixed(2)}</span>
            <span><strong>Denge</strong> {activeDraftLines.length ? (totals.balanced ? "Dengeli" : "Dengesiz") : "Taslak yok"}</span>
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
        <ManualDraftEditor
          activeDraftLines={activeDraftLines}
          chartAccounts={document.chartAccounts}
          generatedDraftLines={generatedDraftLines}
          needsManualDraft={needsManualDraft}
          onAddLine={addManualDraftLine}
          onRemoveLine={removeManualDraftLine}
          onUpdateLine={setManualDraftLine}
        />
        {!pendingDirectionConflict ? (
          <section className="journal-primary-approve" aria-label="Ana fiş kararı">
            <button onClick={onApproveAndNext} type="button">Onayla ve geç</button>
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
        <section className="journal-correction-panel" aria-label="Fiş notu ve öğrenme talimatı">
          <div className="statement-review-heading">
            <div>
              <h3>Düzeltme ve not</h3>
              <span>Hesap ve cari değişikliği fiş satırında yapılır; not karar kaydı, öğrenme talimatı benzer belge önerisi içindir.</span>
            </div>
          </div>
          <div className="correction-form">
            <label className="wide">
              <span>Müşavir notu</span>
              <textarea
                onChange={(event) => setCorrectionDraft({ ...correctionDraft, reason: event.target.value })}
                placeholder="Bu fişte neyi neden değiştirdiniz?"
                rows={3}
                value={correctionDraft.reason}
              />
            </label>
            <label className="wide">
              <span>Benzer belge öğrenme talimatı</span>
              <textarea
                onChange={(event) => setCorrectionDraft({ ...correctionDraft, ruleInstruction: event.target.value })}
                placeholder="Benzer belgelerde nasıl önerilsin? Kural olarak kullan seçilirse aday kural bu metinden oluşur."
                rows={2}
                value={correctionDraft.ruleInstruction}
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
        </section>
        <JournalReasonDisclosure document={document} />
      </div>
      <JournalDecisionBar
        decisionStatus={decisionStatus}
        document={document}
        onReprocessDocument={onReprocessDocument}
        onSaveDecision={onSaveDecision}
        pendingDirectionConflict={pendingDirectionConflict}
      />
    </section>
  );
}

function JournalDecisionBar({
  decisionStatus,
  document,
  onReprocessDocument,
  onSaveDecision,
  pendingDirectionConflict,
}: {
  decisionStatus: string;
  document: PilotDocument;
  onReprocessDocument: () => void | Promise<void>;
  onSaveDecision: (action: string) => void | Promise<void>;
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
          <button onClick={() => onSaveDecision("review_required")} type="button">Kontrol için beklet</button>
          <button onClick={() => onSaveDecision("suggest_for_similar")} type="button">Benzerleri için öneri yap</button>
          <button onClick={onReprocessDocument} type="button">Yeniden işle</button>
          <button onClick={() => onSaveDecision("exclude_export")} type="button">Çıktı listesine ekleme</button>
        </div>
      )}
    </section>
  );
}

function JournalReasonDisclosure({ document }: { document: PilotDocument }) {
  const aiStatus = document.aiResolutionStatus === "ai_retry_required"
    ? "Tekrar denenecek"
    : document.aiProvider && document.aiProvider !== "-" ? document.aiProvider : "Gerekmedi";
  const researchStatus = document.reviewReasons.includes("research_low_confidence")
    || document.reviewReasons.includes("research_source_rejected")
    ? "Kontrol"
    : document.aiResearchRequested
      ? "İstendi"
      : "Gerekmedi";
  const learningStatus = document.rulePrompt.show || document.learningRuleSourceSummary
    ? "Aday var"
    : "Yok";
  const activityContext = [
    document.clientNaceCode,
    ...(document.clientActivityTags ?? []),
  ].filter(Boolean).join(" / ");
  const counterpartyIntent = [
    document.counterpartyTaxId,
    document.counterpartyTitle,
    document.aiSuggestedCounterpartyCode,
    document.suggestedCounterpartyAccount,
  ].filter(Boolean).join(" / ");
  const researchNote = document.aiResearchRequested
    ? (document.aiResearchQuery || "AI ek araştırma istedi.")
    : "Ek araştırma gerekmedi.";
  const accountReason = document.aiAccountReason || document.accountantExplanation || document.aiReason || document.deterministicSummary || "-";
  return (
    <section className="journal-reason-disclosure" aria-label="Karar ve gerekçe">
      <details>
        <summary>
          <span>Neden böyle önerildi?</span>
          <strong>Gerekçe ve AI izi</strong>
        </summary>
        <div className="decision-chain-steps">
          <Info label="Kural" value={document.deterministicSummary || "Statik kontrol"} />
          <Info label="AI" value={aiStatus} />
          <Info label="Araştırma" value={researchStatus} />
          <Info label="Müşavir öğrenmesi" value={learningStatus} />
        </div>
        <div className="ai-guidance compact">
          <ReasonCard label="AI muhasebe gerekçesi" value={document.accountantExplanation || document.aiReason || document.accountantSummary || "-"} />
          <ReasonCard label="Bu hesap neden seçildi?" value={accountReason} />
          <ReasonCard label="Ürün / hizmet yorumu" value={document.aiProductIdentity || document.productLine || "-"} />
          <ReasonCard label="Mükellef faaliyetiyle ilişkisi" value={activityContext || document.businessRelation || "-"} />
          <ReasonCard label="Cari nasıl eşleşti?" value={counterpartyIntent || "-"} />
          <ReasonCard label="Araştırma notu" value={researchNote} />
          <ReasonCard label="Muhasebe davranışı" value={document.accountTreatment || "-"} />
          <ReasonCard label="Kontrol gerektiren nokta" value={document.exportGateReason || document.aiRetryReason || "-"} />
        </div>
        <QualityScorecardPanel document={document} />
        <LearningRuleCard document={document} />
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
      <ReasonCard label="Statik motor" value={`${qualityText(staticDecision, "category")} / %${qualityText(staticDecision, "confidence", "0")}`} />
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
  needsManualDraft,
  onAddLine,
  onRemoveLine,
  onUpdateLine,
}: {
  activeDraftLines: DraftLine[];
  chartAccounts: ChartAccountOption[];
  generatedDraftLines: DraftLine[];
  needsManualDraft: boolean;
  onAddLine: () => void;
  onRemoveLine: (index: number) => void;
  onUpdateLine: (index: number, patch: Partial<DraftLine>) => void;
}) {
  const descriptionRefs = useRef<Array<HTMLInputElement | null>>([]);
  const debitRefs = useRef<Array<HTMLInputElement | null>>([]);
  const creditRefs = useRef<Array<HTMLInputElement | null>>([]);

  if (!needsManualDraft && !activeDraftLines.length) return null;
  const rows = activeDraftLines.length ? activeDraftLines : [blankDraftLine(), blankDraftLine()];

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

  return (
    <section className="manual-draft-panel">
      <div className="statement-review-heading">
        <div>
          <h3>{generatedDraftLines.length ? "Fiş satırları" : "Manuel fiş satırları"}</h3>
          <span>{generatedDraftLines.length ? "Taslağı düzeltip onaylayabilirsiniz." : "Taslak oluşmadı; satırları girerek belgeyi tamamlayın."}</span>
        </div>
        <button onClick={onAddLine} type="button">Satır ekle</button>
      </div>
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
            {rows.map((line, index) => (
              <tr key={index}>
                <td>
                  <AccountCodeCombobox
                    accounts={chartAccounts}
                    onChange={(value) => onUpdateLine(index, { account_code: value })}
                    onSelect={(account) => selectAccount(index, account)}
                    value={line.account_code}
                  />
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
            ))}
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
  const matches = useMemo(() => filterAccountOptions(accounts, value, 20), [accounts, value]);

  function selectActiveAccount() {
    const selected = resolveAccountSelection(accounts, value, activeIndex);
    if (!selected) return false;
    onSelect(selected);
    setOpen(false);
    setActiveIndex(0);
    return true;
  }

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
          setOpen(true);
        }}
        onFocus={() => setOpen(Boolean(value))}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
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
        value={value}
      />
      {open && matches.length ? (
        <div className="account-code-options" role="listbox">
          {matches.map((account, index) => (
            <button
              className={index === activeIndex ? "active" : ""}
              key={account.code}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(account);
                setOpen(false);
              }}
              type="button"
            >
              <span>{account.code}</span>
              <strong>{account.name}</strong>
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
