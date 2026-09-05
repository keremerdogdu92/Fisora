// File: frontend/app/portal-normalization.d.ts
// Summary: Declares normalized portal status, statement, review, and utility helper contracts used by frontend data mappers.
export type StatementLineDirection = "in" | "out" | "";
export type NormalizedPilotStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "review_required"
  | "no_posting_required"
  | "export_ready"
  | "cancel_requested"
  | "cancel_approved"
  | "cancel_rejected"
  | "export_added"
  | "exported"
  | "post_export_correction_requested";

export type NormalizedStatementLine = {
  line_no: number;
  transaction_date: string;
  description: string;
  amount: string;
  direction: StatementLineDirection;
  balance_after: string;
  counterparty_name: string;
  tax_id: string;
  iban: string;
  suggested_account_code: string;
  transaction_type: string;
  confidence: number;
  risk_flags: string[];
  review_reason: string;
  accountant_review_status: string;
  counterparty_match_code: string;
};

export type NormalizedDraftLine = {
  account_code: string;
  description: string;
  debit: string;
  credit: string;
};

export type NormalizedStatementEntry = {
  statement_line_no: number;
  statement_fingerprint: string;
  source_document_ref: string;
  accountant_review_status: string;
  risk_flags: string[];
  lines: NormalizedDraftLine[];
};

export type NormalizedStatementAiSuggestion = {
  line_no: number;
  transaction_type: string;
  suggested_account_code: string;
  confidence: number;
  reason: string;
  evidence: string[];
  risk_flags: string[];
  ai_used: boolean;
  provider: string;
  skipped_reason: string;
  export_allowed: boolean;
};

export type NormalizedRulePrompt = {
  show: boolean;
  defaultScope: string;
  message: string;
  clientConsistentDecisionCount: number;
  officeDistinctClientCount: number;
  officeConsistentDecisionCount: number;
};

export type ReviewReasonGroup = {
  code: string;
  label: string;
  count: number;
};

export function agentSourceLabel(value: string): string;
export function groupedReviewReasons(documents: Array<{ reviewReasons?: string[] }>): ReviewReasonGroup[];
export function normalizeRulePrompt(value: unknown): NormalizedRulePrompt;
export function normalizeStatementAiSuggestions(value: unknown): NormalizedStatementAiSuggestion[];
export function normalizeStatementEntries(value: unknown): NormalizedStatementEntry[];
export function normalizeStatementLines(value: unknown): NormalizedStatementLine[];
export function normalizeStatus(value?: string): NormalizedPilotStatus;
export function parseDateParts(value: string): { year: string; month: string } | null;
export function periodFromDate(value: string, fallback?: string): string;
export function reviewReasonLabel(code: string): string;
export function safeList(value: unknown): string[];
export function safeNumber(value: unknown, fallback?: number): number;
export function safeRecord(value: unknown): Record<string, unknown>;
export function safeText(value: unknown, fallback?: string): string;
