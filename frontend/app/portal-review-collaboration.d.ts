export function reviewStatusLabel(status?: unknown): string;
export function candidateDiff(current?: unknown, candidate?: unknown): unknown[];
export function shouldRenewLease(options?: { visible?: boolean; lastActivityAt?: number; now?: number; intervalMs?: number }): boolean;
