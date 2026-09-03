// File: frontend/app/portal-presentation-chrome.tsx
// Summary: Selects legacy or next-generation portal chrome while keeping the shared portal controller focused on business state and route orchestration.
"use client";

import type { ReactNode } from "react";
import { PortalSidebar, PortalTopbarStatus } from "./shared/components";
import {
  PortalNextSidebar,
  PortalNextTopbar,
  type PortalNextAgentSection,
} from "./portal-next/portal-next-shell";
import type { PortalNotification } from "./portal-notifications";
import type {
  DocumentSegment,
  LocalSession,
  PilotClient,
  PilotMode,
  PortalNavItem,
} from "./portal-types";

export type PortalPresentation = "legacy" | "next";

type WorkspaceSourceState = {
  label: string;
  status: "loading" | "backend" | "empty" | "fallback" | "error";
  detail: string;
};

export function PortalPresentationChrome({
  activeDocumentSegment,
  agentSection,
  children,
  clients,
  collapsed,
  legacySubtitle,
  legacyTitle,
  mobileOpen,
  mode,
  navItems,
  notificationPendingCount,
  notifications,
  onCloseMobile,
  onExit,
  onLegacyNavigate,
  onNextNavigate,
  onReadNotification,
  onSelectClient,
  onSelectPeriod,
  onToggleCollapse,
  onToggleMobile,
  periods,
  presentation,
  selectedClient,
  selectedPeriod,
  showSidebar,
  source,
  session,
}: {
  activeDocumentSegment: DocumentSegment;
  agentSection: PortalNextAgentSection;
  children: ReactNode;
  clients: PilotClient[];
  collapsed: boolean;
  legacySubtitle: string;
  legacyTitle: string;
  mobileOpen: boolean;
  mode: PilotMode;
  navItems: PortalNavItem[];
  notificationPendingCount: number;
  notifications: PortalNotification[];
  onCloseMobile: () => void;
  onExit: () => void;
  onLegacyNavigate: (mode: PilotMode, segment?: DocumentSegment) => void;
  onNextNavigate: (mode: PilotMode, agentSection?: PortalNextAgentSection) => void;
  onReadNotification: (notificationId: string) => Promise<void>;
  onSelectClient: (clientId: string) => void;
  onSelectPeriod: (period: string) => void;
  onToggleCollapse: () => void;
  onToggleMobile: () => void;
  periods: string[];
  presentation: PortalPresentation;
  selectedClient?: PilotClient;
  selectedPeriod: string;
  showSidebar: boolean;
  source: WorkspaceSourceState;
  session: LocalSession | null;
}) {
  const useNext = presentation === "next";
  return (
    <>
      {showSidebar ? (
        useNext ? (
          <PortalNextSidebar
            agentSection={agentSection}
            collapsed={collapsed}
            mobileOpen={mobileOpen}
            mode={mode}
            onCloseMobile={onCloseMobile}
            onExit={onExit}
            onNavigate={onNextNavigate}
            onToggleCollapse={onToggleCollapse}
            session={session}
          />
        ) : (
          <PortalSidebar
            activeDocumentSegment={activeDocumentSegment}
            collapsed={collapsed}
            mobileOpen={mobileOpen}
            mode={mode}
            navItems={navItems}
            onCloseMobile={onCloseMobile}
            onExit={onExit}
            onNavigate={onLegacyNavigate}
            onToggleCollapse={onToggleCollapse}
            session={session}
          />
        )
      ) : null}
      <section className="portal-main-shell">
        {useNext ? (
          <PortalNextTopbar
            agentSection={agentSection}
            clients={clients}
            mode={mode}
            notificationPendingCount={notificationPendingCount}
            onSelectClient={onSelectClient}
            onSelectPeriod={onSelectPeriod}
            onToggleMobile={onToggleMobile}
            periods={periods}
            selectedClient={selectedClient}
            selectedPeriod={selectedPeriod}
          />
        ) : (
          <PortalTopbarStatus
            notificationPendingCount={notificationPendingCount}
            notifications={notifications}
            onReadNotification={onReadNotification}
            onToggleSidebar={onToggleMobile}
            showSidebarToggle={showSidebar}
            source={source}
            subtitle={legacySubtitle}
            title={legacyTitle}
          />
        )}
        {children}
      </section>
    </>
  );
}
