// File: frontend/app/portal-next/portal-next-shell.tsx
// Summary: Provides the isolated next-generation Fisora shell, navigation, topbar, and agent overview while reusing the existing portal controller and business-state boundaries.
"use client";

import {
  Activity,
  Bot,
  CircleCheckBig,
  Home,
  LogOut,
  PanelTop,
  Settings,
  Sparkles,
  Upload,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { DocumentSegment, LocalSession, PilotClient, PilotDocument, PilotMode } from "../portal-types";

export type PortalNextAgentSection = "agents" | "rules";

type SidebarItem = {
  key: string;
  label: string;
  mode: PilotMode;
  icon: LucideIcon;
  agentSection?: PortalNextAgentSection;
};

const NEXT_SIDEBAR_ITEMS: SidebarItem[] = [
  { key: "home", label: "Ana Sayfa", mode: "accountant", icon: Home },
  { key: "workspace", label: "Çalışma Masası", mode: "documents", icon: PanelTop },
  { key: "exports", label: "Onay & Çıktılar", mode: "exports", icon: CircleCheckBig },
  { key: "clients", label: "Mükellefler", mode: "clients", icon: Users },
  { key: "uploads", label: "Yeni Yükleme", mode: "uploads", icon: Upload },
  { key: "agents", label: "AI Ajanları", mode: "agents", icon: Bot, agentSection: "agents" },
  { key: "rules", label: "Öğrenilen Kurallar", mode: "agents", icon: Sparkles, agentSection: "rules" },
  { key: "operations", label: "İşlem Durumu", mode: "operations", icon: Activity },
  { key: "settings", label: "Ayarlar", mode: "settings", icon: Settings },
];

function roleLabel(session: LocalSession | null) {
  if (!session) return "Oturum yok";
  return session.role === "accountant" ? "Müşavir" : "Mükellef";
}

function isItemActive(item: SidebarItem, mode: PilotMode, agentSection: PortalNextAgentSection) {
  if (item.mode !== mode) return false;
  if (item.mode !== "agents") return true;
  return item.agentSection === agentSection;
}

export function PortalNextSidebar({
  agentSection,
  collapsed,
  mobileOpen,
  mode,
  onCloseMobile,
  onExit,
  onNavigate,
  onToggleCollapse,
  session,
}: {
  agentSection: PortalNextAgentSection;
  collapsed: boolean;
  mobileOpen: boolean;
  mode: PilotMode;
  onCloseMobile: () => void;
  onExit: () => void;
  onNavigate: (mode: PilotMode, agentSection?: PortalNextAgentSection) => void;
  onToggleCollapse: () => void;
  session: LocalSession | null;
}) {
  return (
    <aside className={`portal-next-sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " mobile-open" : ""}`} aria-label="Fisora ana menü">
      <div className="portal-next-brand">
        <span className="portal-next-brand-mark">F</span>
        <div className="portal-next-brand-copy">
          <strong>Fisora</strong>
          <small>Mali müşavir çalışma sistemi</small>
        </div>
        <button className="portal-next-collapse" onClick={onToggleCollapse} type="button" aria-label={collapsed ? "Menüyü genişlet" : "Menüyü daralt"}>
          {collapsed ? "›" : "‹"}
        </button>
      </div>

      <nav className="portal-next-nav" aria-label="Fisora ekranları">
        {NEXT_SIDEBAR_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isItemActive(item, mode, agentSection);
          return (
            <button
              aria-current={active ? "page" : undefined}
              className={active ? "portal-next-nav-item active" : "portal-next-nav-item"}
              key={item.key}
              onClick={() => {
                onNavigate(item.mode, item.agentSection);
                onCloseMobile();
              }}
              title={collapsed ? item.label : undefined}
              type="button"
            >
              <Icon aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="portal-next-sidebar-footer">
        <div className="portal-next-user">
          <span>{session?.userId?.slice(0, 2).toLocaleUpperCase("tr-TR") || "--"}</span>
          <div>
            <strong>{session?.userId || "Oturum bilgisi yok"}</strong>
            <small>{roleLabel(session)}</small>
          </div>
        </div>
        <button className="portal-next-exit" onClick={onExit} title="Çıkış" type="button">
          <LogOut aria-hidden="true" />
          <span>Çıkış</span>
        </button>
      </div>
      <button className="portal-next-mobile-close" onClick={onCloseMobile} type="button" aria-label="Menüyü kapat">×</button>
    </aside>
  );
}

function pageTitle(mode: PilotMode, agentSection: PortalNextAgentSection) {
  if (mode === "accountant") return "Ana Sayfa";
  if (mode === "documents") return "Çalışma Masası";
  if (mode === "exports") return "Onay & Çıktılar";
  if (mode === "clients") return "Mükellefler";
  if (mode === "uploads") return "Yeni Yükleme";
  if (mode === "agents") return agentSection === "rules" ? "Öğrenilen Kurallar" : "AI Ajanları";
  if (mode === "operations") return "İşlem Durumu";
  if (mode === "settings") return "Ayarlar";
  return "Fisora";
}

export function PortalNextTopbar({
  agentSection, clients, mode, notificationPendingCount, onSelectClient, onSelectPeriod,
  onToggleMobile, periods, selectedClient, selectedPeriod,
}: {
  agentSection: PortalNextAgentSection;
  clients: PilotClient[];
  mode: PilotMode;
  notificationPendingCount: number;
  onSelectClient: (clientId: string) => void;
  onSelectPeriod: (period: string) => void;
  onToggleMobile: () => void;
  periods: string[];
  selectedClient?: PilotClient;
  selectedPeriod: string;
}) {
  const showContext = mode === "documents";
  return (
    <header className="portal-next-topbar">
      <div className="portal-next-topbar-left">
        <button className="portal-next-mobile-menu" onClick={onToggleMobile} type="button" aria-label="Menüyü aç">☰</button>
        <strong>{pageTitle(mode, agentSection)}</strong>
      </div>
      {showContext ? (
        <div className="portal-next-context" aria-label="Çalışılan mükellef ve dönem">
          <label>
            <span>Çalışılan mükellef</span>
            <select className="portal-next-client-select" onChange={(event) => onSelectClient(event.target.value)} value={selectedClient?.clientId || ""}>
              {clients.map((client) => <option key={client.clientId} value={client.clientId}>{client.clientName}</option>)}
            </select>
          </label>
          <label>
            <span>Dönem</span>
            <select className="portal-next-period-select" onChange={(event) => onSelectPeriod(event.target.value)} value={selectedPeriod}>
              {periods.map((period) => <option key={period} value={period}>{period}</option>)}
            </select>
          </label>
        </div>
      ) : <div />}
      <div className="portal-next-topbar-status"><span>{notificationPendingCount} kontrol</span></div>
    </header>
  );
}
export function PortalNextWorkTypeTabs({
  documents,
  onSelect,
  selectedSegment,
}: {
  documents: PilotDocument[];
  onSelect: (segment: DocumentSegment) => void;
  selectedSegment: DocumentSegment;
}) {
  const invoiceActive = ["purchase_invoices", "sales_invoices", "invoices"].includes(selectedSegment);
  const invoiceCount = documents.filter((document) => document.intakeCategory === "purchase_invoice" || document.intakeCategory === "sales_invoice").length;
  const bankCount = documents.filter((document) => document.intakeCategory === "bank_statement").length;
  const otherCount = documents.filter((document) => document.intakeCategory === "special_document").length;
  return (
    <nav className="portal-next-work-tabs" aria-label="Çalışma Masası belge türleri">
      <button className={invoiceActive ? "active" : ""} onClick={() => onSelect(invoiceActive ? selectedSegment : "purchase_invoices")} type="button">Faturalar <span>{invoiceCount}</span></button>
      <button className={selectedSegment === "bank_statements" ? "active" : ""} onClick={() => onSelect("bank_statements")} type="button">Banka <span>{bankCount}</span></button>
      <button className={selectedSegment === "other_documents" ? "active" : ""} onClick={() => onSelect("other_documents")} type="button">Diğer Belgeler <span>{otherCount}</span></button>
    </nav>
  );
}

type AgentSummary = {
  key: string;
  name: string;
  statusLabel: string;
  touchedCount: number;
  capacityLabel: string;
  unchangedApprovalRateLabel: string;
  correctionCount: number;
  learningLabel: string;
};

export function PortalNextAgentOverview({ agentSummaries }: { agentSummaries: AgentSummary[] }) {
  return (
    <section className="portal-next-agent-overview" aria-label="AI ajanları">
      <div className="portal-next-section-heading">
        <div>
          <span>Fisora ekibi</span>
          <h2>AI Ajanları</h2>
        </div>
        <p>Günlük muhasebe işini öne çıkar; ajan durumu yalnız gerektiğinde görünür.</p>
      </div>
      <div className="portal-next-agent-grid">
        {agentSummaries.map((agent) => (
          <article className="portal-next-agent-card" key={agent.key}>
            <div className="portal-next-agent-card-head">
              <Bot aria-hidden="true" />
              <div><strong>{agent.name}</strong><span>{agent.statusLabel}</span></div>
            </div>
            <dl>
              <div><dt>Bugün</dt><dd>{agent.touchedCount}</dd></div>
              <div><dt>Aynen onay</dt><dd>{agent.unchangedApprovalRateLabel}</dd></div>
              <div><dt>Düzeltme</dt><dd>{agent.correctionCount}</dd></div>
            </dl>
            <small>{agent.learningLabel || agent.capacityLabel}</small>
          </article>
        ))}
        {!agentSummaries.length ? <p className="empty">Ajan özeti henüz oluşmadı.</p> : null}
      </div>
    </section>
  );
}
