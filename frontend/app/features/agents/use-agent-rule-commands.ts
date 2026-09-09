"use client";

import { useCallback, useEffect, useState } from "react";
import { changeLearningRuleLifecycle, fetchLearningRules, resolveApiBaseUrl } from "../../upload-api";
import type { LocalSession } from "../../portal-types";

export type AgentRuleView = Record<string, unknown> & { rule_key?: string; status?: string; version?: number };

const RULE_LOAD_ERROR = "Öğrenilen kurallar şu anda yüklenemedi. Tekrar deneyin.";
const RULE_UPDATE_ERROR = "Kural durumu güncellenemedi. Tekrar deneyin.";

export function useAgentRuleCommands({ loginUserId, session }: { loginUserId: string; session: LocalSession | null }) {
  const [rules, setRules] = useState<AgentRuleView[]>([]);
  const [status, setStatus] = useState("");
  const apiBaseUrl = resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href);
  const userId = session?.userId || loginUserId;

  const refresh = useCallback(async () => {
    try {
      const payload = await fetchLearningRules({ apiBaseUrl, userId, sessionToken: session?.sessionToken || "" });
      setRules(Array.isArray(payload?.items) ? payload.items : Array.isArray(payload) ? payload : []);
    } catch {
      setStatus(RULE_LOAD_ERROR);
    }
  }, [apiBaseUrl, session?.sessionToken, userId]);

  useEffect(() => { if (session?.role === "accountant") void refresh(); }, [refresh, session?.role]);

  const changeStatus = useCallback(async (rule: AgentRuleView, action: "activate" | "pause" | "archive") => {
    try {
      await changeLearningRuleLifecycle({ apiBaseUrl, ruleKey: String(rule.rule_key || ""), action, expectedVersion: Number(rule.version || 0), userId, sessionToken: session?.sessionToken || "" });
      setStatus("Kural durumu güncellendi.");
      await refresh();
    } catch {
      setStatus(RULE_UPDATE_ERROR);
    }
  }, [apiBaseUrl, refresh, session?.sessionToken, userId]);

  return { rules, status, refresh, changeStatus };
}
