export type PortalNotification = {
  notificationId: string;
  kind: string;
  severity: string;
  status: string;
  title: string;
  message: string;
  clientId: string;
  accountingPeriod: string;
  deleteOn: string;
  documentCount: number;
  badgeLabel: string;
  readAt: string;
  read: boolean;
  pending: boolean;
  createdAt: string;
};

export function buildNotificationViewModel(raw?: Record<string, unknown>): PortalNotification;
export function pendingNotificationCount(items?: PortalNotification[]): number;
export function fetchPortalNotifications(options: Record<string, unknown>): Promise<PortalNotification[]>;
export function markPortalNotificationRead(options: Record<string, unknown>): Promise<Record<string, unknown>>;
