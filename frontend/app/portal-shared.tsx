import type { ChartRow } from "./portal-types";

export function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="info">
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

export function ReasonCard({ label, value }: { label: string; value: string }) {
  const parts = label === "Deterministik kontrol"
    ? value.split(",").map((item) => item.trim()).filter(Boolean)
    : [];
  return (
    <div className="reason-card">
      <span>{label}</span>
      {parts.length > 1 ? (
        <div className="reason-tags">
          {parts.map((part) => (
            <em key={part}>{part}</em>
          ))}
        </div>
      ) : (
        <p>{value || "-"}</p>
      )}
    </div>
  );
}

export function ChartBars({ rows, title }: { rows: ChartRow[]; title: string }) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  return (
    <section className="panel chart-panel">
      <div className="section-heading">
        <span>{title}</span>
        <strong>{rows.reduce((sum, row) => sum + row.count, 0)}</strong>
      </div>
      <div className="bar-list">
        {rows.map((row) => (
          <div className="bar-row" key={row.key}>
            <span>{row.label}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${Math.max((row.count / max) * 100, row.count ? 8 : 0)}%` }} />
            </div>
            <strong>{row.count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
