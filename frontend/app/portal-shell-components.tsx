import { Info } from "./portal-shared";
import { roleLabels } from "./portal-session";
import type { LocalSession, PilotClient, PilotDocument } from "./portal-types";

export function ModeButton({ active, href, label }: { active: boolean; href: string; label: string }) {
  return (
    <a aria-current={active ? "page" : undefined} className={active ? "mode-tab active" : "mode-tab"} href={href}>
      {label}
    </a>
  );
}

export function PortalTopbarStatus({
  localFallbackAllowed,
  onExit,
  session,
  source,
}: {
  localFallbackAllowed: boolean;
  onExit: () => void;
  session: LocalSession | null;
  source: string;
}) {
  return (
    <div className="portal-statusbar" aria-label="Portal oturum durumu">
      <div className="topbar-user">
        <span>{session ? roleLabels[session.role] : localFallbackAllowed ? "Lokal ofis" : "Oturum kapalı"}</span>
        <strong>{session?.userId || "Oturum yok"}</strong>
      </div>
      <div className="pilot-source compact">
        <span>Veri kaynağı</span>
        <strong>{source}</strong>
      </div>
      <button className="secondary compact-exit" onClick={onExit} type="button">
        Çıkış
      </button>
    </div>
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
