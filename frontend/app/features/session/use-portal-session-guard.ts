"use client";

import { useEffect, useState } from "react";
import { canUseLocalPilotFallback } from "../../pilot-readiness";
import { normalizeSessionForPortalConfig } from "../../portal-routes";
import { persistSession, readStoredSession } from "../../portal-session";
import type { LocalSession } from "../../portal-types";
import { fetchAuthSession, resolveApiBaseUrl } from "../../upload-api";

type PortalConfig = {
  lockedRole?: LocalSession["role"];
};

export function usePortalSessionGuard({
  lockedRole,
  portalConfig,
  routeKey,
  setLocalFallbackAllowed,
}: {
  lockedRole?: LocalSession["role"];
  portalConfig: PortalConfig;
  routeKey: string;
  setLocalFallbackAllowed: (allowed: boolean) => void;
}) {
  const [session, setSession] = useState<LocalSession | null>(null);
  const [sessionHydrated, setSessionHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function hydrateSession() {
      const storedSession = normalizeSessionForPortalConfig(readStoredSession(), portalConfig);
      const pageUrl = typeof window === "undefined" ? "" : window.location.href;
      const tokenlessSessionAllowed = canUseLocalPilotFallback({
        pageUrl,
        explicitAllow: process.env.NEXT_PUBLIC_FISORA_ALLOW_LOCAL_FALLBACK === "true",
      });
      setLocalFallbackAllowed(tokenlessSessionAllowed);
      if (!storedSession) {
        if (lockedRole && typeof window !== "undefined") window.location.replace("/");
        else setSessionHydrated(true);
        return;
      }
      if (!storedSession.sessionToken) {
        if (tokenlessSessionAllowed) {
          setSession(storedSession);
          setSessionHydrated(true);
          return;
        }
        persistSession(null);
        if (lockedRole && typeof window !== "undefined") window.location.replace("/");
        else setSessionHydrated(true);
        return;
      }
      try {
        const verifiedSession = await fetchAuthSession({
          apiBaseUrl: resolveApiBaseUrl(pageUrl),
          sessionToken: storedSession.sessionToken,
          userId: storedSession.userId,
        });
        if (cancelled) return;
        if (!verifiedSession?.valid || verifiedSession.user_id !== storedSession.userId) {
          throw new Error("stored_session_invalid");
        }
        setSession(storedSession);
        setSessionHydrated(true);
      } catch {
        if (cancelled) return;
        persistSession(null);
        setSession(null);
        if (lockedRole && typeof window !== "undefined") window.location.replace("/");
        else setSessionHydrated(true);
      }
    }
    void hydrateSession();
    return () => {
      cancelled = true;
    };
  }, [lockedRole, portalConfig, routeKey, setLocalFallbackAllowed]);

  return { session, sessionHydrated, setSession };
}
