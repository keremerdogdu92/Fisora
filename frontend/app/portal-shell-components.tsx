import { Info } from "./portal-shared";
import { roleLabels } from "./portal-session";
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
  symbol: string;
}[] = [
  { key: "workspace", label: "Çalışma Alanı", mode: "accountant", fallbackHref: "/portal/musavir", symbol: "CA" },
  { key: "clients", label: "Mükellefler", mode: "clients", fallbackHref: "/portal/mukellefler", symbol: "MK" },
  { key: "documents", label: "Belgeler", mode: "documents", segment: "invoices", fallbackHref: "/portal/belgeler", symbol: "BL" },
  { key: "bank", label: "Banka Ekstreleri", mode: "documents", segment: "bank_statements", fallbackHref: "/portal/belgeler", symbol: "BK" },
  { key: "other", label: "Diğer Belgeler", mode: "documents", segment: "other_documents", fallbackHref: "/portal/belgeler", symbol: "DB" },
  { key: "exports", label: "Çıktı / Kontroller", mode: "exports", fallbackHref: "/portal/cikti", symbol: "CK" },
  { key: "research", label: "Bilgi Havuzu", mode: "research", fallbackHref: "/portal/bilgi-havuzu", symbol: "BH" },
  { key: "operations", label: "Operasyon", mode: "operations", fallbackHref: "/portal/operasyon", symbol: "OP" },
  { key: "settings", label: "Ayarlar", mode: "settings", fallbackHref: "/portal/ayarlar", symbol: "AY" },
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
  mode,
  navItems,
  onExit,
  onNavigate,
  session,
}: {
  activeDocumentSegment: DocumentSegment;
  mode: PilotMode;
  navItems: PortalNavItem[];
  onExit: () => void;
  onNavigate: (mode: PilotMode, segment?: DocumentSegment) => void;
  session: LocalSession | null;
}) {
  const allowedModes = new Set(navItems.map((item) => item.mode));
  return (
    <aside className="portal-sidebar" aria-label="Müşavir menüsü">
      <div className="portal-brand">
        <span className="brand-mark">F</span>
        <div>
          <strong>Fisero</strong>
          <small>Özel Muhasebe Operasyon Portalı</small>
        </div>
      </div>
      <nav className="portal-sidebar-nav" aria-label="Portal ekranları">
        {sidebarItems.filter((item) => allowedModes.has(item.mode)).map((item) => (
          <button
            aria-current={isSidebarItemActive(item, mode, activeDocumentSegment) ? "page" : undefined}
            className={isSidebarItemActive(item, mode, activeDocumentSegment) ? "sidebar-link active" : "sidebar-link"}
            key={item.key}
            onClick={() => onNavigate(item.mode, item.segment)}
            type="button"
          >
            <span className="nav-symbol">{item.symbol}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <span>{session?.userId?.slice(0, 2).toLocaleUpperCase("tr-TR") || "OY"}</span>
          <div>
            <strong>{session?.userId || "Ömer Yağcı"}</strong>
            <small>{session ? roleLabels[session.role] : "Mali Müşavir"}</small>
          </div>
        </div>
        <button className="sidebar-exit" onClick={onExit} type="button">Çıkış</button>
      </div>
    </aside>
  );
}

export function PortalTopbarStatus({
  clientName,
  localFallbackAllowed,
  onExit,
  session,
  source,
  title,
}: {
  clientName?: string;
  localFallbackAllowed: boolean;
  onExit: () => void;
  session: LocalSession | null;
  source: string;
  title: string;
}) {
  return (
    <header className="portal-topbar" aria-label="Portal üst çubuğu">
      <div className="portal-title-block">
        <button className="topbar-menu" type="button" aria-label="Menüyü daralt">☰</button>
        <h1>{title}</h1>
      </div>
      <div className="portal-topbar-actions">
        <button className="topbar-action" type="button">Bildirimler <strong>3</strong></button>
        <button className="topbar-action" type="button">Yardım</button>
        <div className="topbar-user">
          <span>{session ? roleLabels[session.role] : localFallbackAllowed ? "Lokal ofis" : "Oturum kapalı"}</span>
          <strong>{clientName || session?.userId || "Oturum yok"}</strong>
        </div>
        <div className="pilot-source compact">
          <span>Veri kaynağı</span>
          <strong>{source}</strong>
        </div>
        <button className="secondary compact-exit" onClick={onExit} type="button">
          Çıkış
        </button>
      </div>
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
