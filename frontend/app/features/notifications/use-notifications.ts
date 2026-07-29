import { useCallback, useEffect, useState } from "react";
import { fetchPortalNotifications, markPortalNotificationRead } from "../../portal-notifications";
import type { LocalSession } from "../../portal-types";
import type { PortalNotification } from "../../portal-notifications";

export function useNotifications({ apiBaseUrl, session }: { apiBaseUrl: string; session: LocalSession | null }) {
  const [notifications, setNotifications] = useState<PortalNotification[]>([]);

  const refresh = useCallback(async () => {
    if (!session?.userId) {
      setNotifications([]);
      return;
    }
    try {
      const next = await fetchPortalNotifications({
        apiBaseUrl,
        userId: session.userId,
        sessionToken: session.sessionToken,
      });
      setNotifications(next);
    } catch {
      setNotifications([]);
    }
  }, [apiBaseUrl, session?.sessionToken, session?.userId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const markRead = useCallback(async (notificationId: string) => {
    if (!session?.userId) return;
    await markPortalNotificationRead({
      apiBaseUrl,
      notificationId,
      userId: session.userId,
      sessionToken: session.sessionToken,
    });
    setNotifications((current) => current.map((item) =>
      item.notificationId === notificationId ? { ...item, read: true, readAt: new Date().toISOString() } : item,
    ));
  }, [apiBaseUrl, session?.sessionToken, session?.userId]);

  return {
    notifications,
    pendingCount: notifications.filter((item) => item.pending).length,
    refresh,
    markRead,
  };
}
