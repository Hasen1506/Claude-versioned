import { GLOSSARY } from "../lib/glossary";
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

export function StatTile({ label, value, sub, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "hl" | "ink";
}) {
  return (
    <div className={`panel tile ${tone ?? ""}`}>
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

// ---- legacy design language: stage header, section band, trust layer ----------------------------

/** Page header: the page's question in plain words, a one-line answer to "what is this", its actions, and
 *  "How this is calculated" folded away for anyone who wants the method. (`n` was the old stage number.) */
export function StageHeader({ title, kicker, how, right }: { n?: string; title: string; kicker?: ReactNode; how?: ReactNode; right?: ReactNode }) {
  return (
    <header className="stage-head">
      <div className="grow">
        <h1 className="title">{title}</h1>
        {kicker && <div className="kicker">{kicker}</div>}
        {how && <details className="how"><summary>How this is calculated</summary><div>{how}</div></details>}
      </div>
      {right && <div className="row wrap">{right}</div>}
    </header>
  );
}

/** Recalculate one page's result. "Plan everything" in the top bar does every page; this is for one. */
export function RunButton({ running, has, onClick, disabled }: { running: boolean; has: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button className="btn" onClick={onClick} disabled={running || disabled}
      title="Recalculate this page from the current data. Plan everything, top right, recalculates every page.">
      {running ? "Calculating…" : has ? "Recalculate" : "Calculate"}
    </button>
  );
}

/** A term of art with its plain meaning on hover (see lib/glossary). */
export function Term({ t, children }: { t: string; children?: ReactNode }) {
  const def = GLOSSARY[t];
  if (!def) return <>{children ?? t}</>;
  return <abbr className="term" title={def}>{children ?? t}</abbr>;
}

/** Numbered section band inside a page (legacy StageSection). */
export function SectionBand({ step, title, right }: { step?: string | number; title: string; right?: ReactNode }) {
  return (
    <div className="section-band">
      {step !== undefined && <span className="step">{step}</span>}
      <h2 className="title">{title}</h2>
      <span className="rule" />
      {right}
    </div>
  );
}

/** How a number is computed, and what it means for the planner (legacy Reading). */
export function Reading({ formula, soWhat }: { formula?: ReactNode; soWhat?: ReactNode }) {
  return (
    <div className="reading">
      {formula && <div className="f">{formula}</div>}
      {soWhat && <div className="so">{soWhat}</div>}
    </div>
  );
}

const PROV = {
  input: { i: "⌨", label: "Your data", title: "Entered by you or imported" },
  derived: { i: "ƒ", label: "Calculated", title: "Calculated from your data" },
  solved: { i: "⚙", label: "Calculated", title: "Calculated from your data by the planning engine" },
} as const;

/** Where a figure comes from, when, and whether its inputs changed since (legacy Provenance). */
export function Provenance({ kind, at, stale }: { kind: keyof typeof PROV; at?: string | null; stale?: boolean }) {
  const p = PROV[kind];
  return (
    <span className={`prov ${kind} ${stale ? "stale" : ""}`} title={p.title}>
      <span className="i" aria-hidden>{p.i}</span>{p.label}
      {at && <span className="when">{at.slice(0, 5)}</span>}
      {stale && <span style={{ color: "var(--warning-text)" }}>· out of date</span>}
    </span>
  );
}

/** Banner shown on a result whose inputs changed after it was computed (legacy StaleMark). */
export function StaleMark({ what, onRerun, busy }: { what: string; onRerun?: () => void; busy?: boolean }) {
  return (
    <div className="stale-mark" role="status">
      <b>⚠ Out of date</b>
      <span className="spacer">You changed the data after this {what} was calculated, so these numbers may be wrong.</span>
      {onRerun && <button className="btn sm" onClick={onRerun} disabled={busy}>{busy ? "Calculating…" : "Recalculate now"}</button>}
    </div>
  );
}

/** What an engine answers, what it reads, and what it feeds (legacy SolverIO). */
export function SolverIO({ answers, from, feeds }: { answers: ReactNode; from: ReactNode; feeds: ReactNode }) {
  return (
    <div className="solver-io">
      <div><div className="k">WHAT IT TELLS YOU</div><div className="v">{answers}</div></div>
      <div><div className="k">WHAT IT USES</div><div className="v">{from}</div></div>
      <div><div className="k">WHAT USES IT →</div><div className="v feeds">{feeds}</div></div>
    </div>
  );
}

export type Theme = "system" | "mono" | "noir" | "sepia";
const THEME_KEY = "scp.theme";

export function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === "mono" || t === "noir" || t === "sepia") return t;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

export function applyTheme(t: Theme) {
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  try {
    localStorage.setItem(THEME_KEY, t);
  } catch {
    /* storage unavailable */
  }
}

/** MONO / NOIR / SEPIA / system theme switch (legacy themes). */
export function ThemeSwitch() {
  const [t, setT] = useState<Theme>(readTheme);
  const opts: [Theme, string][] = [["system", "Auto"], ["mono", "Mono"], ["noir", "Noir"], ["sepia", "Sepia"]];
  return (
    <div className="seg" role="group" aria-label="Theme">
      {opts.map(([id, label]) => (
        <button key={id} className={t === id ? "on" : ""} aria-pressed={t === id}
          onClick={() => { applyTheme(id); setT(id); }}>{label}</button>
      ))}
    </div>
  );
}
