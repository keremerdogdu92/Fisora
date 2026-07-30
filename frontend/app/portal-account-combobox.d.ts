import type { DraftLine } from "./portal-types";

export type ChartAccountOption = {
  code: string;
  name: string;
  isDetail: boolean;
  taxId: string;
  taxOffice: string;
  iban: string;
  searchText: string;
};

export function applyAccountSelectionToLine(line: DraftLine, account: ChartAccountOption, options?: ChartAccountOption[]): DraftLine;
export function classifyDraftAccountCode(
  options: ChartAccountOption[],
  accountCode: string,
  suggestedNewCounterpartyCodes?: string[],
): "valid" | "new_counterparty" | "invalid";
export function filterAccountOptions(options: ChartAccountOption[], query: string, limit?: number): ChartAccountOption[];
export function normalizeChartAccountOptions(accounts: unknown[]): ChartAccountOption[];
export function resolveAccountSelection(options: ChartAccountOption[], input: string, activeIndex?: number): ChartAccountOption | null;
