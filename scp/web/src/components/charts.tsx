// Small SVG charts following the data-viz rules: one y-axis, recessive hairline grid, 2px lines,
// ≤24px columns with a 4px rounded data end, crosshair + tooltip, legend for ≥2 series, and text in
// text tokens (never the series colour). Tables beside every chart carry the exact values.
import { useMemo, useRef, useState, type ReactNode } from "react";
import { qty } from "../lib/format";

export interface Series {
  name: string;
  color: string;                 // CSS var, e.g. "var(--series-1)"
  values: (number | null)[];     // null = no value in that bucket (the line breaks)
  kind?: "line" | "step" | "column" | "dots";
  dash?: boolean;                // dashed line: a forecast / projection rather than an actual
}

export interface Band {
  name: string;
  color: string;
  lower: (number | null)[];
  upper: (number | null)[];
}

export interface Span {
  from: number;                  // bucket index, inclusive
  to: number;                    // bucket index, inclusive
  label: string;
}

export interface Mark {
  i: number;
  v: number;
  label: string;
  shape: "triangle" | "cross";
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

const finite = (v: number | null | undefined): v is number => v !== null && v !== undefined && Number.isFinite(v);

export function BucketChart({ labels, series, height = 240, unit = "", highlight, format = qty, band, divider, dividerLabel,
  spans = [], marks = [] }: {
  labels: string[]; series: Series[]; height?: number; unit?: string;
  highlight?: (i: number) => ReactNode; format?: (v: number) => string;
  band?: Band; divider?: number; dividerLabel?: string; spans?: Span[]; marks?: Mark[];
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const width = 900;
  const pad = { l: 56, r: 16, t: 14, b: 28 };
  const n = labels.length;
  const all = [
    ...series.flatMap((s) => s.values.filter(finite)),
    ...(band ? band.upper.filter(finite) : []),
    ...marks.map((m) => m.v),
  ];
  const lo = Math.min(0, ...all);
  const top = Math.max(0, ...all);
  const hi = top > 0 || lo >= 0 ? niceMax(top) : 0;   // all-negative data tops out at zero
  const loN = lo < 0 ? -niceMax(-lo) : 0;
  const x0 = pad.l;
  const bw = (width - pad.l - pad.r) / Math.max(1, n);
  const y = (v: number) => pad.t + ((hi - v) / (hi - loN || 1)) * (height - pad.t - pad.b);
  const cx = (i: number) => x0 + bw * i + bw / 2;
  const ticks = useMemo(() => {
    const out: number[] = [];
    const step = (hi - loN) / 4;
    for (let k = 0; k <= 4; k++) out.push(loN + step * k);
    return out;
  }, [hi, loN]);
  const cols = series.filter((s) => s.kind === "column");
  const colW = Math.min(24, (bw - 4) / Math.max(1, cols.length));
  // space labels by their width (~6.5 px per mono character) so long date labels never collide
  const maxLen = Math.max(1, ...labels.map((l) => l.length));
  const labelEvery = Math.max(1, Math.ceil((n * (maxLen * 6.5 + 14)) / (width - pad.l - pad.r)));

  const linePath = (vals: (number | null)[], step: boolean) => {
    let d = "";
    let open = false;
    vals.forEach((v, i) => {
      if (!finite(v)) { open = false; return; }
      const py = y(v);
      if (step) {
        const left = x0 + bw * i;
        d += open ? ` V${py} H${left + bw}` : `M${left},${py} H${left + bw}`;
      } else d += `${open ? " L" : "M"}${cx(i)},${py}`;
      open = true;
    });
    return d;
  };
  const bandPath = (b: Band) => {
    // one closed polygon per contiguous run of defined values
    const runs: number[][] = [];
    let cur: number[] = [];
    b.lower.forEach((l, i) => {
      if (finite(l) && finite(b.upper[i])) cur.push(i);
      else if (cur.length) { runs.push(cur); cur = []; }
    });
    if (cur.length) runs.push(cur);
    return runs.map((r) => {
      const top = r.map((i) => `${cx(i)},${y(b.upper[i] as number)}`);
      const bot = [...r].reverse().map((i) => `${cx(i)},${y(b.lower[i] as number)}`);
      return `M${top.join(" L")} L${bot.join(" L")} Z`;
    }).join(" ");
  };

  return (
    <div ref={wrap} style={{ position: "relative" }}>
      {(series.length > 1 || band || spans.length > 0 || marks.length > 0) && (
        <div className="legend" style={{ marginBottom: 6 }}>
          {series.map((s) => (
            <span key={s.name} style={{ color: s.dash ? s.color : undefined }}>
              <span className={`key ${s.kind === "column" ? "box" : ""} ${s.dash ? "dash" : ""}`} style={{ background: s.color }} />
              <span style={{ color: "var(--text-2)" }}>{s.name}</span>
            </span>
          ))}
          {band && <span><span className="key box" style={{ background: band.color, opacity: 0.35 }} />{band.name}</span>}
          {spans.length > 0 && <span><span className="key box" style={{ background: "var(--hl)", opacity: 0.5 }} />Event</span>}
          {marks.some((m) => m.shape === "triangle") && <span>▲ cleansed (event)</span>}
          {marks.some((m) => m.shape === "cross") && <span>✕ cleansed (outlier)</span>}
        </div>
      )}
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={series.map((s) => s.name).join(", ")}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * width;
          const i = Math.floor((px - x0) / bw);
          setHover(i >= 0 && i < n ? i : null);
        }} style={{ width: "100%", height: "auto" }}>
        {spans.map((sp, k) => (
          <rect key={`span-${k}`} className="event-span" x={x0 + bw * sp.from} width={bw * (sp.to - sp.from + 1)}
            y={pad.t} height={height - pad.t - pad.b} />
        ))}
        {ticks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={x0} x2={width - pad.r} y1={y(t)} y2={y(t)} />
            <text x={x0 - 8} y={y(t) + 4} textAnchor="end">{format(t)}</text>
          </g>
        ))}
        {loN < 0 && <line className="axis" x1={x0} x2={width - pad.r} y1={y(0)} y2={y(0)} />}
        {labels.map((l, i) => (i % labelEvery === 0 ? (
          <text key={i} x={cx(i)} y={height - 8} textAnchor="middle">{l}</text>
        ) : null))}
        {hover !== null && <rect x={x0 + bw * hover} y={pad.t} width={bw} height={height - pad.t - pad.b} fill="var(--surface-3)" opacity={0.6} />}
        {band && <path d={bandPath(band)} fill={band.color} className="band" />}
        {divider !== undefined && divider > 0 && divider < n && (
          <g>
            <line className="today" x1={x0 + bw * divider} x2={x0 + bw * divider} y1={pad.t - 4} y2={height - pad.b} />
            {dividerLabel && <text x={x0 + bw * divider + 4} y={pad.t + 6} style={{ fontWeight: 700 }}>{dividerLabel}</text>}
          </g>
        )}
        {cols.map((s, si) => s.values.map((v, i) => {
          if (!finite(v)) return null;
          const x = cx(i) - (colW * cols.length) / 2 + si * colW + 1;
          const top = y(Math.max(v, 0));
          const base = y(0);
          const h = Math.max(0, base - top);
          const r = Math.min(4, h, (colW - 2) / 2);
          return h > 0 ? (
            <path key={`${si}-${i}`} fill={s.color}
              d={`M${x},${base} V${top + r} Q${x},${top} ${x + r},${top} H${x + colW - 2 - r} Q${x + colW - 2},${top} ${x + colW - 2},${top + r} V${base} Z`} />
          ) : null;
        }))}
        {series.filter((s) => s.kind !== "column" && s.kind !== "dots").map((s) => (
          <path key={s.name} d={linePath(s.values, s.kind === "step")} fill="none" stroke={s.color} strokeWidth={2}
            strokeDasharray={s.dash ? "6 4" : undefined} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {series.filter((s) => s.kind === "dots").map((s) => s.values.map((v, i) => finite(v) ? (
          <circle key={`${s.name}-${i}`} cx={cx(i)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
        ) : null))}
        {marks.map((m, k) => m.shape === "triangle" ? (
          <path key={`m-${k}`} d={`M${cx(m.i)},${y(m.v) - 11} l5,8 h-10 z`} fill="var(--ink)" />
        ) : (
          <path key={`m-${k}`} d={`M${cx(m.i) - 4},${y(m.v) - 4} l8,8 M${cx(m.i) + 4},${y(m.v) - 4} l-8,8`} stroke="var(--critical)" strokeWidth={2.5} />
        ))}
        {hover !== null && series.filter((s) => s.kind === "line" || s.kind === undefined).map((s) => (
          finite(s.values[hover]) ? <circle key={s.name} cx={cx(hover)} cy={y(s.values[hover] as number)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} /> : null
        ))}
      </svg>
      {hover !== null && (
        <div className="tooltip" style={{
          position: "absolute", left: `${Math.min(78, (cx(hover) / width) * 100)}%`, top: 24,
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4, fontFamily: "var(--display)" }}>{labels[hover]}</div>
          {series.filter((s) => finite(s.values[hover])).map((s) => (
            <div key={s.name} className="row" style={{ gap: 6 }}>
              <span style={{ display: "inline-block", width: 10, height: s.kind === "column" || s.kind === "dots" ? 10 : 3, background: s.color }} />
              <span className="muted">{s.name}</span><span className="spacer" />
              <b className="num">{format(s.values[hover] as number)}{unit}</b>
            </div>
          ))}
          {band && finite(band.lower[hover]) && (
            <div className="row" style={{ gap: 6 }}>
              <span style={{ display: "inline-block", width: 10, height: 10, background: band.color, opacity: 0.35 }} />
              <span className="muted">{band.name}</span><span className="spacer" />
              <b className="num">{format(band.lower[hover] as number)} – {format(band.upper[hover] as number)}</b>
            </div>
          )}
          {marks.filter((m) => m.i === hover).map((m, k) => <div key={k} className="small muted">{m.label}</div>)}
          {spans.filter((sp) => sp.from <= hover && hover <= sp.to).map((sp, k) => <div key={`s${k}`} className="small muted">Event: {sp.label}</div>)}
          {highlight?.(hover)}
        </div>
      )}
    </div>
  );
}
