"use client";

import { labelForIntakeCategory } from "./upload-intake";
import { agentSourceLabel } from "./portal-normalization";
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

export function DocumentPreview({ document }: { document?: PilotDocument }) {
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
  return (
    <section className={`review-panel journal-panel ${document.intakeCategory === "bank_statement" || document.statementLines.length > 0 ? "statement-mode" : ""}`}>
      <div className="panel-heading">
        <div>
          <h2>AI ajan destekli fiş taslağı</h2>
          <span>{document.clientName}</span>
        </div>
      </div>
      <div className="ai-guidance">
        <ReasonCard label="Öneri gerekçesi" value={document.aiReason} />
        <ReasonCard label="Faaliyet ilişkisi" value={document.businessRelation || "-"} />
        <ReasonCard label="Muhasebe işleme" value={document.accountTreatment || "-"} />
        <ReasonCard label="Kullanılan sinyaller" value={document.aiAccountReason || "Hesap planı, faaliyet alanı ve önceki karar sinyali bekleniyor."} />
        <ReasonCard label="Deterministik kontrol" value={document.deterministicSummary} />
        <ReasonCard label="Kontrol gerekçesi" value={document.exportGateReason} />
      </div>
      <div className="journal-meta ai-meta">
        <Info label="Öneri kaynağı" value={agentSourceLabel(document.aiProvider)} />
        <Info label="Önerilen hesap" value={document.aiSuggestedAccountCode || document.selectedExpenseAccount || "-"} />
        <Info label="Önerilen cari" value={document.aiSuggestedCounterpartyCode || document.selectedCounterpartyAccount || "-"} />
        <Info label="Güven düzeyi" value={document.aiRiskFlags.length ? document.aiRiskFlags.join(", ") : "Risk yok"} />
      </div>
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
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Hesap</th>
              <th>Açıklama</th>
              <th>Borç</th>
              <th>Alacak</th>
            </tr>
          </thead>
          <tbody>
            {journalDraftLinesForDocument(document, selectedStatementLineNo).length ? (
              journalDraftLinesForDocument(document, selectedStatementLineNo).map((line, index) => (
                <tr key={`${line.account_code}-${index}`}>
                  <td>{line.account_code}</td>
                  <td>{line.description}</td>
                  <td>{line.debit}</td>
                  <td>{line.credit}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4}>Fiş taslağı henüz yok.</td>
              </tr>
            )}
          </tbody>
        </table>
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
