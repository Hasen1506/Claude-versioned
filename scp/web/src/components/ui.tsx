import { useState, type CSSProperties, type ReactNode } from "react";

export type Severity = "error" | "warning" | "info" | "ok";

/** Status never relies on color alone: icon + label, always. */
export function SevIcon({ sev }: { sev: Severity }) {
  const common = { className: "sev-icon", viewBox: "0 0 16 16", "aria-hidden": true } as const;
  if (sev === "error")
    return (
      <svg {...common}><circle cx="8" cy="8" r="7" fill="var(--critical)" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" /></svg>
    );
  if (sev === "warning")
    return (
      <svg {...common}><path d="M8 1.5l7 12.5H1z" fill="var(--warning)" /><path d="M8 6v4" stroke="#000" strokeWidth="1.5" strokeLinecap="round" /><circle cx="8" cy="12" r=".9" fill="#000" /></svg>
    );
  if (sev === "ok")
    return (
      <svg {...common}><circle cx="8" cy="8" r="7" fill="var(--good)" /><path d="M4.8 8.2l2.2 2.2 4.2-4.6" stroke="#fff" strokeWidth="1.6" fill="none" strokeLinecap="round" /></svg>
    );
  return (
    <svg {...common}><circle cx="8" cy="8" r="7" fill="var(--accent)" /><path d="M8 7v4.5" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" /><circle cx="8" cy="4.8" r=".95" fill="#fff" /></svg>
  );
}

const SEV_LABEL: Record<Severity, string> = { error: "Error", warning: "Warning", info: "Info", ok: "OK" };

export function Badge({ sev, children }: { sev?: Severity; children?: ReactNode }) {
  return (
    <span className={`badge ${sev ?? ""}`}>
      {sev && <SevIcon sev={sev} />}
      {children ?? (sev ? SEV_LABEL[sev] : null)}
    </span>
  );
}

export function Panel({ title, actions, children, flush, className }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string;
}) {
  return (
    <section className={`panel ${className ?? ""}`}>
      {(title || actions) && (
        <div className="panel-head">
          {typeof title === "string" ? <h3>{title}</h3> : title}
          <span className="spacer" />
          {actions}
        </div>
      )}
      <div className={`panel-body ${flush ? "flush" : ""}`}>{children}</div>
    </section>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} className={`tab ${t.id === value ? "active" : ""}`}
          onClick={() => onChange(t.id)}>
          {t.label}
          {t.count !== undefined && <span className="count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="panel tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

/** Cursor-following tooltip for SVG marks. Hit targets are the caller's job (bigger than marks). */
export function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null);
  const node = tip ? (
    <div className="tooltip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 330), top: tip.y + 14 }}>
      {tip.content}
    </div>
  ) : null;
  return {
    node,
    show: (e: { clientX: number; clientY: number }, content: ReactNode) => setTip({ x: e.clientX, y: e.clientY, content }),
    hide: () => setTip(null),
  };
}

/** Column template for a `.split` layout; collapses to one column on narrow screens (see styles.css). */
export function cols(template: string, extra?: CSSProperties): CSSProperties {
  return { ["--split-cols" as string]: template, ...extra } as CSSProperties;
}
