import {
  Activity,
  BookOpen,
  Bot,
  CircleCheckBig,
  FileText,
  Files,
  Landmark,
  LayoutDashboard,
  LogOut,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Info } from "./portal-shared";
import { roleLabels } from "./portal-session";
import type { PortalNotification } from "./portal-notifications";
import type { DocumentSegment, DraftLine, LocalSession, PilotClient, PilotDocument, PilotMode, PilotStatus, PortalNavItem } from "./portal-types";

export function ModeButton({ active, href, label }: { active: boolean; href: string; label: string }) {
  return (
    <a aria-current={active ? "page" : undefined} className={active ? "mode-tab active" : "mode-tab"} href={href}>
      {label}
    </a>
  );
}

const sidebarItems: {
  key: string;
  label: string;
  mode: PilotMode;
  segment?: DocumentSegment;
  fallbackHref: string;
  icon: LucideIcon;
}[] = [
  { key: "workspace", label: "Çalışma Alanı", mode: "accountant", fallbackHref: "/portal/musavir", icon: LayoutDashboard },
  { key: "agents", label: "AI Ajanları", mode: "agents", fallbackHref: "/portal/ajanlar", icon: Bot },
  { key: "clients", label: "Mükellefler", mode: "clients", fallbackHref: "/portal/mukellefler", icon: Users },
  { key: "documents", label: "Faturalar", mode: "documents", segment: "purchase_invoices", fallbackHref: "/portal/belgeler", icon: FileText },
  { key: "bank", label: "Banka Ekstreleri", mode: "documents", segment: "bank_statements", fallbackHref: "/portal/belgeler", icon: Landmark },
  { key: "other", label: "Diğer Belgeler", mode: "documents", segment: "other_documents", fallbackHref: "/portal/belgeler", icon: Files },
  { key: "exports", label: "Çıktı / Kontroller", mode: "exports", fallbackHref: "/portal/cikti", icon: CircleCheckBig },
  { key: "research", label: "Bilgi Havuzu", mode: "research", fallbackHref: "/portal/bilgi-havuzu", icon: BookOpen },
  { key: "operations", label: "Operasyon", mode: "operations", fallbackHref: "/portal/operasyon", icon: Activity },
  { key: "settings", label: "Ayarlar", mode: "settings", fallbackHref: "/portal/ayarlar", icon: Settings },
];

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

function formatMoney(value: number) {
  return `${value.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} TL`;
}

function formatStatus(status?: PilotStatus) {
  return status ? statusLabels[status] ?? status : "-";
}

function isSidebarItemActive(item: (typeof sidebarItems)[number], mode: PilotMode, segment: DocumentSegment) {
  if (item.mode !== mode) return false;
  if (!item.segment) return mode !== "documents";
  if (item.key === "documents") return segment === "sales_invoices" || segment === "purchase_invoices" || segment === "invoices";
  return item.segment === segment;
}

export function PortalSidebar({
  activeDocumentSegment,
  collapsed,
  mobileOpen,
  mode,
  navItems,
  onCloseMobile,
  onExit,
  onNavigate,
  onToggleCollapse,
  session,
}: {
  activeDocumentSegment: DocumentSegment;
  collapsed: boolean;
  mobileOpen: boolean;
  mode: PilotMode;
  navItems: PortalNavItem[];
  onCloseMobile: () => void;
  onExit: () => void;
  onNavigate: (mode: PilotMode, segment?: DocumentSegment) => void;
  onToggleCollapse: () => void;
  session: LocalSession | null;
}) {
  const allowedModes = new Set(navItems.map((item) => item.mode));
  useEffect(() => {
    if (!mobileOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseMobile();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen, onCloseMobile]);

  return (
    <aside
      className={collapsed ? "portal-sidebar collapsed" : "portal-sidebar"}
      aria-label="Müşavir menüsü"
      data-mobile-open={mobileOpen ? "true" : "false"}
    >
      <div className="portal-brand">
        <span className="brand-mark">F</span>
        <div>
          <strong>Fisero</strong>
          <small>Özel Muhasebe Operasyon Portalı</small>
        </div>
        <button
          aria-label={collapsed ? "Menüyü genişlet" : "Menüyü daralt"}
          className="sidebar-collapse-button"
          onClick={onToggleCollapse}
          type="button"
        >
          {collapsed ? "›" : "‹"}
        </button>
        <button className="sidebar-mobile-close" onClick={onCloseMobile} type="button" aria-label="Menüyü kapat">
          x
        </button>
      </div>
      <nav className="portal-sidebar-nav" aria-label="Portal ekranları">
        {sidebarItems.filter((item) => allowedModes.has(item.mode)).map((item) => {
          const Icon = item.icon;
          return (
            <button
              aria-current={isSidebarItemActive(item, mode, activeDocumentSegment) ? "page" : undefined}
              className={isSidebarItemActive(item, mode, activeDocumentSegment) ? "sidebar-link active" : "sidebar-link"}
              key={item.key}
              onClick={() => {
                onNavigate(item.mode, item.segment);
                onCloseMobile();
              }}
              type="button"
            >
              <span className="nav-symbol">
                <Icon aria-hidden="true" />
              </span>
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <span>{session?.userId?.slice(0, 2).toLocaleUpperCase("tr-TR") || "OY"}</span>
          <div>
            <strong>{session?.userId || "Ömer Yağcı"}</strong>
            <small>{session ? roleLabels[session.role] : "Mali Müşavir"}</small>
          </div>
        </div>
        <button aria-label="Çıkış yap" className="sidebar-exit" onClick={onExit} title="Çıkış" type="button">
          <LogOut aria-hidden="true" />
          <span>Çıkış</span>
        </button>
      </div>
    </aside>
  );
}

export function PortalTopbarStatus({
  notificationPendingCount,
  notifications,
  onReadNotification,
  onToggleSidebar,
  showSidebarToggle,
  source,
  subtitle = "",
  title,
}: {
  notificationPendingCount: number;
  notifications: PortalNotification[];
  onReadNotification: (notificationId: string) => Promise<void>;
  onToggleSidebar?: () => void;
  showSidebarToggle?: boolean;
  source: { label: string; status: string; detail: string };
  subtitle?: string;
  title: string;
}) {
  const [activePanel, setActivePanel] = useState<"notifications" | "help" | null>(null);

  useEffect(() => {
    if (!activePanel) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setActivePanel(null);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [activePanel]);

  return (
    <header className="portal-topbar" aria-label="Portal üst çubuğu">
      <div className="portal-title-block">
        {showSidebarToggle ? (
          <button className="topbar-menu" onClick={onToggleSidebar} type="button" aria-label="Menüyü aç">☰</button>
        ) : null}
        <div>
          <h1>{title}</h1>
          {subtitle ? <small className="portal-title-subtitle">{subtitle}</small> : null}
        </div>
      </div>
      <div className="portal-topbar-actions">
        <button className="topbar-action" onClick={() => setActivePanel("notifications")} type="button">Bildirimler <strong>{notificationPendingCount}</strong></button>
        <button className="topbar-action" onClick={() => setActivePanel("help")} type="button">Yardım</button>
        <div className={`pilot-source compact ${source.status}`}>
          <span>Veri kaynağı</span>
          <strong>{source.label}</strong>
          <small>{source.detail}</small>
        </div>
      </div>
      {activePanel ? (
        <div className="topbar-popover" role="dialog" aria-label={activePanel === "notifications" ? "Bildirimler" : "Yardım"}>
          <button aria-label="Paneli kapat" onClick={() => setActivePanel(null)} type="button">x</button>
          {activePanel === "notifications" ? (
            <div>
              <strong>Bildirimler</strong>
              <div className="notification-list">
                {notifications.map((notification) => (
                  <article className={notification.read ? "notification-item read" : "notification-item"} key={notification.notificationId}>
                    <strong>{notification.title}</strong>
                    <p>{notification.message}</p>
                    <span className="notification-badge">{notification.badgeLabel}</span>
                    <button
                      className="secondary compact"
                      disabled={notification.read}
                      onClick={() => void onReadNotification(notification.notificationId)}
                      type="button"
                    >
                      {notification.read ? "Okundu" : "Okundu işaretle"}
                    </button>
                  </article>
                ))}
              </div>
              <p>Kontrol bekleyen belgeler ve çıktı blokajları belge listesinde gerekçeleriyle gösterilir.</p>
            </div>
          ) : (
            <div>
              <strong>Yardım</strong>
              <p>Belge listesinde satırı açın, fiş taslağını kontrol edin, sonra onay veya düzeltme kararı verin.</p>
            </div>
          )}
        </div>
      ) : null}
    </header>
  );
}

export function DocumentContextBar({
  client,
  draftLines,
  period,
  selectedDocument,
}: {
  client?: PilotClient;
  draftLines: DraftLine[];
  period: string;
  selectedDocument?: PilotDocument;
}) {
  const totals = draftTotals(draftLines);
  const hasDraft = draftLines.length > 0;
  return (
    <section className="document-context-bar" aria-label="Belge işleme özeti">
      <Info label="Mükellef" value={client?.clientName ?? "-"} />
      <Info label="Dönem" value={period || "-"} />
      <Info label="Belge" value={selectedDocument?.fileName ?? "Belge seçilmedi"} />
      <Info label="Fiş durumu" value={selectedDocument ? formatStatus(selectedDocument.status) : "-"} />
      <Info label="Borç toplamı" value={hasDraft ? formatMoney(totals.debit) : "-"} />
      <Info label="Alacak toplamı" value={hasDraft ? formatMoney(totals.credit) : "-"} />
      <Info label="Denge" value={hasDraft ? (totals.balanced ? "Dengeli" : "Dengesiz") : "-"} />
    </section>
  );
}

export function SelectedClientStrip({
  client,
  documents,
  openCancellationCount,
}: {
  client?: PilotClient;
  documents: PilotDocument[];
  openCancellationCount: number;
}) {
  const readyCount = documents.filter((document) => document.status === "export_ready" || document.status === "export_added").length;
  const reviewCount = documents.filter((document) => document.status === "review_required").length;
  return (
    <section className="selected-client-strip" aria-label="Seçili mükellef">
      <Info label="Seçili mükellef" value={client?.clientName ?? "-"} />
      <Info label="VKN" value={client?.taxId ?? "-"} />
      <Info label="Belge" value={String(documents.length)} />
      <Info label="Kontrol" value={String(reviewCount)} />
      <Info label="Çıktı hazır" value={String(readyCount)} />
      <Info label="İptal talebi" value={String(openCancellationCount)} />
    </section>
  );
}
