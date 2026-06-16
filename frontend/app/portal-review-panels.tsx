"use client";

import { useEffect, useState } from "react";
import { labelForIntakeCategory } from "./upload-intake";
import { Info, ReasonCard } from "./portal-shared";
import type { CorrectionDraft, DraftLine, PilotDocument, PilotStatus, StatementLineReview } from "./portal-types";

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

const documentTypeLabels: Record<string, string> = {
  invoice: "Fatura",
  xml: "E-Fatura XML/PDF",
  bank: "Banka ekstresi",
  bank_statement: "Banka ekstresi",
  pos: "POS ekstresi",
  pos_statement: "POS ekstresi",
  special_document: "Özel belge",
  ALIS: "Alış faturası",
  SATIS: "Satış faturası",
};

const statementTypeLabels: Record<string, string> = {
  tax_payment: "Vergi ödemesi",
  social_security: "SGK / prim",
  pos_blocked: "POS bloke",
  transfer: "Virman / transfer",
  counterparty_payment: "Cari ödeme",
  unknown: "Belirsiz",
};

function documentPreviewTitle(document: PilotDocument) {
  if (document.intakeCategory === "bank_statement") return "EKSTRE";
  if (document.intakeCategory === "special_document") return "ÖZEL BELGE";
  return "FATURA";
}

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
  if (typeof window === "undefined") return "";
  const configured = process.env.NEXT_PUBLIC_FISORA_API_BASE_URL?.trim().replace(/\/+$/, "");
  if (configured) return configured;
  return `${window.location.protocol}//${window.location.hostname}:8000`;
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
  const normalized = String(value || "0").replace(/\./g, "").replace(",", ".");
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

export function DocumentPreview({ document }: { document?: PilotDocument }) {
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (!document?.originalDocumentRef) {
      setPreviewUrl("");
      return;
    }
    let active = true;
    let objectUrl = "";
    const fetchPreview = async () => {
      try {
        const response = await fetch(
          `${resolvePreviewApiBaseUrl()}/phase0/store/document-file/${encodeURIComponent(document.clientId)}/${encodeURIComponent(document.originalDocumentRef)}`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error("preview unavailable");
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (active) setPreviewUrl(objectUrl);
      } catch {
        if (active) setPreviewUrl("");
      }
    };
    void fetchPreview();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document?.clientId, document?.originalDocumentRef]);

  if (!document) {
    return (
      <section className="panel review-panel">
        <h2>Orijinal belge</h2>
        <p className="empty">Belge seçimi yok.</p>
      </section>
    );
  }
  return (
    <section className="review-panel document-panel">
      <div className="panel-heading">
        <div>
          <h2>Orijinal belge</h2>
          <span>{document.fileName}</span>
        </div>
        <span className={`status ${document.status}`}>{formatStatus(document.status)}</span>
      </div>
      <div className="document-canvas">
        {previewUrl ? (
          isImageMime(document.originalDocumentMimeType) ? (
            <img alt={`${document.fileName} orijinal belge`} className="original-document-image" src={previewUrl} />
          ) : (
            <iframe className="original-document-frame" src={previewUrl} title={`${document.fileName} orijinal belge`} />
          )
        ) : (
        <article className="paper-document" aria-label="Belge orijinal görünümü">
          <header className="paper-header">
            <div>
              <span>{labelForIntakeCategory(document.intakeCategory)} / {documentTypeLabels[document.documentType] ?? document.documentType}</span>
              <strong>{document.provider}</strong>
            </div>
            <small>{document.issueDate}</small>
          </header>
          <div className="paper-title">
            <span>{documentPreviewTitle(document)}</span>
            <strong>{document.fileName}</strong>
          </div>
          <div className="paper-row">
            <span>Açıklama</span>
            <strong>{document.previewText}</strong>
          </div>
          <div className="paper-line-item">
            <span>Kalem</span>
            <strong>{document.productLine}</strong>
            <small>{document.productCategory}</small>
          </div>
          <div className="paper-totals">
            <div>
              <span>KDV</span>
              <strong>{document.vatRates.length ? `%${document.vatRates.join(", %")}` : "-"}</strong>
            </div>
            <div>
              <span>Toplam</span>
              <strong>{document.amount}</strong>
            </div>
          </div>
          <footer className="paper-footer">
            <span>Belge referansı</span>
            <strong>{document.id}</strong>
          </footer>
        </article>
        )}
      </div>
    </section>
  );
}

export function JournalPanel({
  correctionDraft,
  decisionStatus,
  document,
  onApproveAndNext,
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
  onApproveAndNext: () => void | Promise<void>;
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

  return (
    <section className={`review-panel journal-panel ${document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "statement-mode" : ""}`}>
      <div className="panel-heading">
        <div>
          <h2>Muhasebe fişi</h2>
          <span>{document.clientName}</span>
        </div>
      </div>
      <div className="draft-summary">
        <Info label="Fiş durumu" value={formatDraftStatus(document.draftStatus)} />
        <Info label="Borç toplamı" value={totals.debit.toFixed(2)} />
        <Info label="Alacak toplamı" value={totals.credit.toFixed(2)} />
        <Info label="Denge" value={activeDraftLines.length ? (totals.balanced ? "Dengeli" : "Dengesiz") : "Taslak yok"} />
      </div>
      <p className="accountant-summary">
        {document.accountantSummary || (needsManualDraft ? "Fiş taslağı çıkarılamadı; manuel satır girerek belgeyi tamamlayın." : "Fiş taslağı kontrol için hazır.")}
      </p>
      <LearningRuleCard document={document} />
      <div className="journal-meta">
        <Info label={document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Banka hesabı" : "Gider hesabı"} value={document.selectedExpenseAccount} />
        <Info label={document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Fiş KDV" : "KDV hesabı"} value={document.selectedVatAccount} />
        <Info label={document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Karşı hesap" : "Cari"} value={`${document.selectedCounterpartyAccount} (${document.counterpartyConfidence})`} />
      </div>
      {document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? (
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
      <ManualDraftEditor
        activeDraftLines={activeDraftLines}
        generatedDraftLines={generatedDraftLines}
        needsManualDraft={needsManualDraft}
        onAddLine={addManualDraftLine}
        onRemoveLine={removeManualDraftLine}
        onUpdateLine={setManualDraftLine}
      />
      <div className="correction-form">
        <label>
          <span>{document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Yeni işlem hesabı" : "Yeni gider hesabı"}</span>
          <input
            onChange={(event) => setCorrectionDraft({ ...correctionDraft, accountCode: event.target.value })}
            placeholder={document.selectedExpenseAccount}
            value={correctionDraft.accountCode}
          />
        </label>
        <label>
          <span>{document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "Yeni karşı hesap" : "Yeni cari"}</span>
          <input
            onChange={(event) => setCorrectionDraft({ ...correctionDraft, counterpartyCode: event.target.value })}
            placeholder={document.selectedCounterpartyAccount}
            value={correctionDraft.counterpartyCode}
          />
        </label>
        <label className="wide">
          <span>Müşavir açıklaması</span>
          <textarea
            onChange={(event) => setCorrectionDraft({ ...correctionDraft, reason: event.target.value })}
            placeholder="Neden değiştirdiniz? Bu açıklama sonraki benzer belgelerde öğrenme sinyali olur."
            rows={3}
            value={correctionDraft.reason}
          />
        </label>
      </div>
      <div className="accountant-guidance">
        <details>
          <summary>Kararı etkileyen açıklamalar</summary>
          <div className="ai-guidance compact">
            <ReasonCard label="Öneri gerekçesi" value={document.aiReason || document.accountantSummary || "-"} />
            <ReasonCard label="Faaliyet ilişkisi" value={document.businessRelation || "-"} />
            <ReasonCard label="Muhasebe işleme" value={document.accountTreatment || "-"} />
            <ReasonCard label="Kontrol gerekçesi" value={document.exportGateReason || "-"} />
          </div>
        </details>
        <details>
          <summary>Teknik detay</summary>
          <pre>{JSON.stringify(document.technicalDetails || {}, null, 2)}</pre>
        </details>
      </div>
      <div className="decision-actions">
        <button onClick={onApproveAndNext} type="button">Onayla ve geç</button>
        <button onClick={() => onSaveDecision("approve_with_changes")} type="button">Düzelt ve onayla</button>
        <button onClick={() => onSaveDecision("suggest_for_similar")} type="button">Kural olarak kullan</button>
        <button onClick={() => onSaveDecision("exclude_export")} type="button">Çıktı listesine ekleme</button>
        <button onClick={() => onSaveDecision("review_required")} type="button">Kontrolde tut</button>
      </div>
      <p className="decision-status">{decisionStatus || "Bu belge için henüz müşavir kararı verilmedi."}</p>
    </section>
  );
}

function ManualDraftEditor({
  activeDraftLines,
  generatedDraftLines,
  needsManualDraft,
  onAddLine,
  onRemoveLine,
  onUpdateLine,
}: {
  activeDraftLines: DraftLine[];
  generatedDraftLines: DraftLine[];
  needsManualDraft: boolean;
  onAddLine: () => void;
  onRemoveLine: (index: number) => void;
  onUpdateLine: (index: number, patch: Partial<DraftLine>) => void;
}) {
  if (!needsManualDraft && !activeDraftLines.length) return null;
  const rows = activeDraftLines.length ? activeDraftLines : [blankDraftLine(), blankDraftLine()];
  return (
    <section className="manual-draft-panel">
      <div className="statement-review-heading">
        <div>
          <h3>{generatedDraftLines.length ? "Fiş satırları" : "Manuel fiş satırları"}</h3>
          <span>{generatedDraftLines.length ? "Taslağı düzeltip onaylayabilirsiniz." : "Taslak oluşmadı; satırları girerek belgeyi tamamlayın."}</span>
        </div>
        <button onClick={onAddLine} type="button">Satır ekle</button>
      </div>
      <div className="table-wrap">
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
              <tr key={`${line.account_code}-${index}`}>
                <td><input onChange={(event) => onUpdateLine(index, { account_code: event.target.value })} value={line.account_code} /></td>
                <td><input onChange={(event) => onUpdateLine(index, { description: event.target.value })} value={line.description} /></td>
                <td><input inputMode="decimal" onChange={(event) => onUpdateLine(index, { debit: event.target.value })} value={line.debit} /></td>
                <td><input inputMode="decimal" onChange={(event) => onUpdateLine(index, { credit: event.target.value })} value={line.credit} /></td>
                <td><button onClick={() => onRemoveLine(index)} type="button">Sil</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
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
            <button onClick={() => onSaveStatementDecision("approve_with_changes")} type="button">Düzelt ve onayla</button>
            <button onClick={() => onSaveStatementDecision("suggest_for_similar")} type="button">Kural olarak kullan</button>
            <button onClick={() => onSaveStatementDecision("exclude_from_export")} type="button">Çıktı listesine ekleme</button>
            <button onClick={() => onSaveStatementDecision("wrong_account")} type="button">Kontrolde tut</button>
          </div>
        </div>
      </div>
    </section>
  );
}
