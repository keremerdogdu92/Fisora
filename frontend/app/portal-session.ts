import type { LocalSession } from "./portal-types";
import { parseDelegatedSessionHash } from "./upload-api";

const SESSION_STORAGE_KEY = "fisora.office.session.v1";
const TAB_SESSION_STORAGE_KEY = "fisora.office.tabSession.v1";

export const roleLabels: Record<LocalSession["role"], string> = {
  accountant: "Müşavir",
  client_user: "Mükellef",
};

export function readStoredSession(): LocalSession | null {
  if (typeof window === "undefined") return null;
  const delegatedSession = consumeDelegatedSessionFromLocation();
  if (delegatedSession) return delegatedSession;
  const tabSession = readSessionStorage(window.sessionStorage, TAB_SESSION_STORAGE_KEY);
  if (tabSession) return tabSession;
  return readSessionStorage(window.localStorage, SESSION_STORAGE_KEY);
}

function readSessionStorage(storage: Storage, key: string): LocalSession | null {
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LocalSession;
    if (!parsed.userId || !parsed.role) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function persistSession(session: LocalSession | null) {
  if (typeof window === "undefined") return;
  if (!session) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    window.sessionStorage.removeItem(TAB_SESSION_STORAGE_KEY);
    return;
  }
  if (session.storageScope === "tab") {
    window.sessionStorage.setItem(TAB_SESSION_STORAGE_KEY, JSON.stringify(session));
    return;
  }
  window.sessionStorage.removeItem(TAB_SESSION_STORAGE_KEY);
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ ...session, storageScope: "local" }));
}

export function consumeDelegatedSessionFromLocation(): LocalSession | null {
  if (typeof window === "undefined") return null;
  const delegatedSession = parseDelegatedSessionHash(window.location.hash) as LocalSession | null;
  if (!delegatedSession) return null;
  persistSession(delegatedSession);
  if (window.history?.replaceState) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }
  return delegatedSession;
}
