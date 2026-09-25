// Small SVG charts following the data-viz rules: one y-axis, recessive hairline grid, 2px lines,
// ≤24px columns with a 4px rounded data end, crosshair + tooltip, legend for ≥2 series, and text in
// text tokens (never the series colour). Tables beside every chart carry the exact values.
import { useMemo, useRef, useState, type ReactNode } from "react";
import { qty } from "../lib/format";

export interface Series {
  name: string;
  color: string;          // CSS var, e.g. "var(--series-1)"
  values: number[];
  kind?: "line" | "step" | "column";
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

export function BucketChart({ labels, series, height = 240, unit = "", highlight, format = qty }: {
  labels: string[]; series: Series[]; height?: number; unit?: string;
  highlight?: (i: number) => ReactNode; format?: (v: number) => string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const width = 900;
  const pad = { l: 56, r: 16, t: 12, b: 28 };
  const n = labels.length;
  const all = series.flatMap((s) => s.values.filter((v) => Number.isFinite(v)));
  const lo = Math.min(0, ...all);
  const hi = niceMax(Math.max(0, ...all));
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
  const labelEvery = Math.ceil(n / 12);

  return (
    <div ref={wrap} style={{ position: "relative" }}>
      {series.length > 1 && (
        <div className="legend" style={{ marginBottom: 6 }}>
          {series.map((s) => (
            <span key={s.name}><span className={`key ${s.kind === "column" ? "box" : ""}`} style={{ background: s.color }} />{s.name}</span>
          ))}
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
        {hover !== null && <rect x={x0 + bw * hover} y={pad.t} width={bw} height={height - pad.t - pad.b} fill="var(--surface-2)" />}
        {cols.map((s, si) => s.values.map((v, i) => {
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
        {series.filter((s) => s.kind !== "column").map((s) => {
          const pts = s.values.map((v, i) => [cx(i), y(v)] as const);
          let d = "";
          if (s.kind === "step") {
            pts.forEach(([, py], i) => {
              const left = x0 + bw * i;
              d += i === 0 ? `M${left},${py} H${left + bw}` : ` V${py} H${left + bw}`;
            });
          } else d = pts.map(([px, py], i) => `${i ? "L" : "M"}${px},${py}`).join(" ");
          return <path key={s.name} d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />;
        })}
        {hover !== null && series.filter((s) => s.kind === "line").map((s) => (
          <circle key={s.name} cx={cx(hover)} cy={y(s.values[hover])} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
        ))}
      </svg>
      {hover !== null && (
        <div className="tooltip" style={{
          position: "absolute", left: `${Math.min(80, (cx(hover) / width) * 100)}%`, top: 24,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{labels[hover]}</div>
          {series.map((s) => (
            <div key={s.name} className="row" style={{ gap: 6 }}>
              <span className={`key ${s.kind === "column" ? "box" : ""}`} style={{ display: "inline-block", width: 10, height: s.kind === "column" ? 10 : 3, background: s.color, borderRadius: 2 }} />
              <span className="muted">{s.name}</span><span className="spacer" />
              <b className="num">{format(s.values[hover])}{unit}</b>
            </div>
          ))}
          {highlight?.(hover)}
        </div>
      )}
    </div>
  );
}
