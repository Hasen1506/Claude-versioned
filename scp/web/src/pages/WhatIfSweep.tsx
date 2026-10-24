// Enterprise plan 5.3: one change swept over several sizes (engine: whatif.sweep_chip), read as cost against service
// for safety stock (against the service expected when demand misses its forecast) or as an exposure for the rest (how
// far it can go before service falls), and the money at risk over time of any what-if.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, SweepPoint, SweepResult, VersionMeta, WhatIfChip, WhatIfResult } from "../api/types";
import { BucketChart } from "../components/charts";
import { Badge, Empty, Panel } from "../components/ui";
import { money, pct } from "../lib/format";
import { href } from "../lib/router";
import { store, useReadOnly } from "../state/store";
import { chipLabel } from "./WhatIf";

type Kind = "safety_days" | "demand" | "lead_time" | "lane_delay" | "machine_down" | "customer_price" | "fx" | "supplier_price";

const KINDS: { id: Kind; label: string; unit: string; values: string }[] = [
  { id: "safety_days", label: "Safety stock in days", unit: "d", values: "0, 2, 5, 10, 20" },
  { id: "demand", label: "Demand change", unit: "%", values: "-20, -10, 10, 20, 40" },
  { id: "lead_time", label: "Supplier lead time change", unit: "d", values: "-7, 7, 14, 21" },
  { id: "lane_delay", label: "Route delay", unit: "d", values: "3, 7, 14" },
  { id: "machine_down", label: "Machine or line down", unit: "d", values: "3, 7, 14" },
  { id: "customer_price", label: "Price change for a customer", unit: "%", values: "-10, -5, 5, 10" },
  { id: "supplier_price", label: "Purchase price change", unit: "%", values: "-10, 5, 10, 20" },
  { id: "fx", label: "Exchange rate move", unit: "%", values: "-10, 5, 10, 20" },
];

/** The chip to sweep (its number is replaced by each value on the server). */
function chipOf(kind: Kind, who: string): WhatIfChip | null {
  switch (kind) {
    case "safety_days": return { kind, days: 0, products: [] };
    case "demand": return { kind, pct: 0, products: [] };
    case "lead_time": return { kind, days: 0, supplier: who || null };
    case "lane_delay": return { kind, days: 0, location: who || null };
    case "machine_down": return who ? { kind, resource: who, days: 1, start: null } : null;
    case "customer_price": return who ? { kind, customer: who, pct: 0 } : null;
    case "fx": return who ? { kind, currency: who, pct: 0 } : null;
    case "supplier_price": return { kind, pct: 0, supplier: who || null, products: [] };
  }
}

export function parseValues(text: string): number[] | null {
  const parts = text.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
  const nums = parts.map(Number);
  return parts.length >= 2 && parts.length <= 8 && nums.every(Number.isFinite) ? nums : null;
}

export function Sweep({ ds }: { ds: Dataset }) {
  const cur = ds.settings.currency;
  const [kind, setKind] = useState<Kind>("safety_days");
  const [who, setWho] = useState("");
  const [text, setText] = useState(KINDS[0].values);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SweepResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const k = KINDS.find((x) => x.id === kind)!;
  const pick = useMemo(() => {
    if (kind === "lead_time" || kind === "supplier_price") return { label: "Supplier (every one if none)", opts: [...new Set((ds.purchasing_sources ?? []).map((s) => s.supplier))].sort(), optional: true };
    if (kind === "lane_delay") return { label: "Place on the routes (every route if none)", opts: [...new Set((ds.lanes ?? []).flatMap((l) => [l.origin, l.destination]))].sort(), optional: true };
    if (kind === "machine_down") return { label: "Machine or line", opts: (ds.resources ?? []).map((r) => r.id), optional: false };
    if (kind === "customer_price") return { label: "Customer", opts: (ds.locations ?? []).filter((l) => l.type === "customer").map((l) => l.id).sort(), optional: false };
    if (kind === "fx") return { label: "Currency", opts: Object.keys(ds.settings.fx_rates ?? {}).sort(), optional: false };
    return null;
  }, [kind, ds]);
  const values = parseValues(text);
  const chip = chipOf(kind, who);
  const run = async () => {
    if (!chip || !values) return;
    setBusy(true); setErr(null);
    try { setRes(await api.sweep(ds, chip, values)); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setRes(null); }
    finally { setBusy(false); }
  };
  return (
    <>
      <Panel title="Sweep one change">
        <p className="small muted" style={{ marginTop: 0 }}>Plan one change at several sizes and read what each size costs
          against the service it gives. Safety stock is read against the service to expect when demand misses its
          forecast; every other change is read as an exposure: how far it can go before service falls.</p>
        <div className="row wrap" style={{ gap: 8, alignItems: "flex-end" }}>
          <label className="stack" style={{ gap: 2 }}><span className="small muted">Change</span>
            <select className="input" aria-label="Change to sweep" value={kind} onChange={(e) => {
              const n = e.target.value as Kind; setKind(n); setWho(""); setText(KINDS.find((x) => x.id === n)!.values); setRes(null);
            }}>{KINDS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></label>
          {pick && <label className="stack" style={{ gap: 2 }}><span className="small muted">{pick.label}</span>
            <select className="input" aria-label={pick.label} value={who} onChange={(e) => { setWho(e.target.value); setRes(null); }}>
              <option value="">{pick.optional ? "Every one" : "Pick one…"}</option>
              {pick.opts.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>}
          <label className="stack" style={{ gap: 2 }}><span className="small muted">Sizes to try ({k.unit}), 2 to 8</span>
            <input className="input" aria-label="Sizes to try" value={text} style={{ width: 200 }} onChange={(e) => { setText(e.target.value); setRes(null); }} /></label>
          <button className="btn accent" disabled={busy || !chip || !values} onClick={run}>
            {busy ? `Planning ${(values?.length ?? 0) + 1} plans…` : "Sweep"}</button>
        </div>
        {!values && <p className="small" role="alert"><Badge sev="warning">Sizes</Badge> give two to eight numbers, separated by commas</p>}
      </Panel>
      {err && <div className="banner warning" role="alert">{err}</div>}
      {res ? <SweepOut r={res} cur={cur} chip={chip} /> : !err && <Empty title="Nothing swept yet">Pick a change and the sizes to try, then sweep.</Empty>}
    </>
  );
}

const svcOf = (r: SweepResult, p: { service: number; expected_service?: number | null }) =>
  r.lever && p.expected_service != null ? p.expected_service : p.service;

function SweepOut({ r, cur, chip }: { r: SweepResult; cur: string; chip: WhatIfChip | null }) {
  const m = (v: number) => money(v, cur);
  const ro = useReadOnly();
  const [sel, setSel] = useState(Math.max(0, r.points.length - 1));
  const [kept, setKept] = useState<Record<number, VersionMeta>>({});
  const [keepErr, setKeepErr] = useState<string | null>(null);
  const keep = async (p: SweepPoint) => {
    if (!chip) return;
    setKeepErr(null);
    const field = r.field as "days" | "pct";
    const c = { ...chip, [field]: chip.kind === "machine_down" ? Math.round(p.value) : p.value } as WhatIfChip;
    try {
      const before = store.captureWorking();
      const out = await api.keepWhatIf(before.dataset, chipLabel(c), [c], before.version?.id ?? null);
      if (out.base) store.saved(out.base, before);
      setKept((x) => ({ ...x, [p.value]: out.version }));
    } catch (e) { setKeepErr(e instanceof Error ? e.message : String(e)); }
  };
  const p = r.points[sel];
  const svcName = r.lever ? "Expected service" : "On-time service";
  return (
    <>
      <Panel title={r.lever ? "Cost against service" : "How far it can go"}>
        <ul className="sweep-read" aria-label="What the sweep says">{r.read.map((x) => <li key={x}>{x}</li>)}</ul>
        <CostService r={r} cur={cur} sel={sel} onPick={setSel} />
      </Panel>
      {keepErr && <div className="banner warning" role="alert">{keepErr}</div>}
      <Panel flush title="Each size">
        <div className="table-wrap">
          <table className="t" aria-label="Sweep">
            <thead><tr><th>Size</th><th className="num">Total plan cost</th><th className="num">{svcName}</th>
              {r.lever && <th className="num">Plan on-time service</th>}
              {r.lever && <th className="num">Cost of a point (from the size before)</th>}
              <th className="num">Sales at risk</th><th className="num">Average stock</th><th />{!ro && <th />}</tr></thead>
            <tbody>
              <tr className="muted"><td>As today</td><td className="num">{m(r.baseline.total_cost)}</td>
                <td className="num">{pct(svcOf(r, r.baseline), 1)}</td>
                {r.lever && <td className="num">{pct(r.baseline.service, 1)}</td>}{r.lever && <td />}
                <td className="num">{m(r.baseline.late_revenue)}</td><td className="num">{m(r.baseline.inventory_value_avg)}</td><td />{!ro && <td />}</tr>
              {r.points.map((x, i) => (
                <tr key={x.value} className={i === sel ? "hl" : undefined} onClick={() => setSel(i)} style={{ cursor: "pointer" }}>
                  <td>{x.label}{x.note && <div className="small faint" style={{ whiteSpace: "normal", maxWidth: 260 }}>{x.note}</div>}</td>
                  <td className="num">{x.ok ? m(x.total_cost) : "—"}{x.cost_delta != null && <div className="small faint">{x.cost_delta >= 0 ? "+" : "−"}{m(Math.abs(x.cost_delta))}</div>}</td>
                  <td className="num">{x.ok ? pct(svcOf(r, x), 1) : "—"}</td>
                  {r.lever && <td className="num">{x.ok ? pct(x.service, 1) : "—"}</td>}
                  {r.lever && <td className="num">{x.step_cost_per_point != null ? (x.step_cost_per_point >= 0 ? m(x.step_cost_per_point) : `saves ${m(-x.step_cost_per_point)}`) : <span className="faint">—</span>}</td>}
                  <td className="num">{x.ok ? m(x.late_revenue) : "—"}</td>
                  <td className="num">{x.ok ? m(x.inventory_value_avg) : "—"}</td>
                  <td>{r.lever && (x.frontier ? <Badge sev="ok">worth it</Badge> : x.ok && <Badge sev="warning">not worth it</Badge>)}
                    {!x.ok && <Badge sev="error">not planned</Badge>}</td>
                  {!ro && <td className="num">{!x.ok ? null : kept[x.value]
                    ? <span className="small">Kept as <b>{kept[x.value].id}</b> · <a href={href("versions")}>Versions</a></span>
                    : <button className="btn sm" aria-label={`Keep ${x.label} as a version`} onClick={(e) => { e.stopPropagation(); keep(x); }}>Keep as a version</button>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {p && <RiskOverTime title={`Money at risk over time: today and ${p.label}`} periods={r.periods} cur={cur}
        rows={[{ label: "As today", at_risk: r.baseline.at_risk ?? [] }, { label: p.label, at_risk: p.at_risk ?? [] }]} />}
    </>
  );
}

/** Cost against service, one dot a size: today as a ring, the sizes worth their money joined in order. */
function CostService({ r, cur, sel, onPick }: { r: SweepResult; cur: string; sel: number; onPick: (i: number) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 900, H = 320, pad = { l: 64, r: 24, t: 34, b: 40 };   // room above the top dots for their labels
  const pts = r.points.filter((p) => p.ok);
  const all = [r.baseline, ...pts];
  const costs = all.map((p) => p.total_cost), svcs = all.map((p) => svcOf(r, p) * 100);
  const cLo = Math.min(...costs), cHi = Math.max(...costs);
  const span = cHi - cLo || Math.max(1, cHi * 0.05);
  const xLo = cLo - span * 0.08, xHi = cHi + span * 0.08;
  const sLo = Math.max(0, Math.floor(Math.min(...svcs) / 5) * 5 - (Math.min(...svcs) % 5 < 1 ? 5 : 0));
  const sHi = Math.min(100, Math.max(sLo + 5, Math.ceil(Math.max(...svcs))));
  const x = (v: number) => pad.l + ((v - xLo) / (xHi - xLo)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + ((sHi - v) / (sHi - sLo)) * (H - pad.t - pad.b);
  const yt = [0, 1, 2, 3, 4].map((k) => sLo + ((sHi - sLo) * k) / 4);
  const xt = [0, 1, 2, 3].map((k) => xLo + ((xHi - xLo) * (k + 0.5)) / 4);
  const front = r.lever ? r.points.map((p, i) => [p, i] as const).filter(([p]) => p.ok && p.frontier) : r.points.map((p, i) => [p, i] as const).filter(([p]) => p.ok);
  const line = front.map(([p], k) => `${k ? "L" : "M"}${x(p.total_cost)},${y(svcOf(r, p) * 100)}`).join(" ");
  const h = hover !== null ? (hover < 0 ? r.baseline : r.points[hover]) : null;
  return (
    <div style={{ position: "relative" }}>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span><span className="key dot" style={{ background: "var(--series-1)" }} /><span style={{ color: "var(--text-2)" }}>{r.lever ? "a size worth its money" : "a size"}</span></span>
        {r.lever && <span><span className="key dot" style={{ background: "var(--text-3)" }} /><span style={{ color: "var(--text-2)" }}>not worth it</span></span>}
        <span><span className="key ring" /><span style={{ color: "var(--text-2)" }}>today</span></span>
      </div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Cost against ${r.lever ? "expected service" : "on-time service"}`}
        style={{ width: "100%", height: "auto" }} onMouseLeave={() => setHover(null)}>
        {yt.map((t) => <g key={t}><line className="gridline" x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} />
          <text x={pad.l - 8} y={y(t) + 4} textAnchor="end">{t.toFixed(t % 1 ? 1 : 0)} %</text></g>)}
        {xt.map((t) => <text key={t} x={x(t)} y={H - 18} textAnchor="middle">{money(t, cur)}</text>)}
        <text x={(pad.l + W - pad.r) / 2} y={H - 3} textAnchor="middle">total plan cost →</text>
        {line && <path d={line} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />}
        <circle cx={x(r.baseline.total_cost)} cy={y(svcOf(r, r.baseline) * 100)} r={6} fill="var(--surface)" stroke="var(--ink)" strokeWidth={2} />
        <circle cx={x(r.baseline.total_cost)} cy={y(svcOf(r, r.baseline) * 100)} r={14} fill="transparent"
          onMouseEnter={() => setHover(-1)} />
        {r.points.map((p, i) => p.ok && (
          <g key={p.value} onMouseEnter={() => setHover(i)} onClick={() => onPick(i)} style={{ cursor: "pointer" }}>
            <circle cx={x(p.total_cost)} cy={y(svcOf(r, p) * 100)} r={i === sel ? 7 : 5}
              fill={!r.lever || p.frontier ? "var(--series-1)" : "var(--text-3)"} stroke="var(--surface)" strokeWidth={2} />
            <circle cx={x(p.total_cost)} cy={y(svcOf(r, p) * 100)} r={14} fill="transparent" />
            <text x={x(p.total_cost)} y={y(svcOf(r, p) * 100) - 12} textAnchor="middle">{`${p.value > 0 && r.field === "pct" ? "+" : ""}${p.value}${r.field === "pct" ? " %" : " d"}`}</text>
          </g>
        ))}
      </svg>
      {h && <div className="tooltip" style={{ position: "absolute", top: 24, left: 72, maxWidth: "60%" }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>{h.label}</div>
        <div className="row" style={{ gap: 6 }}><span className="muted">Total plan cost</span><span className="spacer" /><b className="num">{money(h.total_cost, cur)}</b></div>
        <div className="row" style={{ gap: 6 }}><span className="muted">{r.lever ? "Expected service" : "On-time service"}</span><span className="spacer" /><b className="num">{pct(svcOf(r, h), 1)}</b></div>
        {r.lever && <div className="row" style={{ gap: 6 }}><span className="muted">Plan on-time service</span><span className="spacer" /><b className="num">{pct(h.service, 1)}</b></div>}
        <div className="row" style={{ gap: 6 }}><span className="muted">Sales at risk</span><span className="spacer" /><b className="num">{money(h.late_revenue, cur)}</b></div>
      </div>}
    </div>
  );
}

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/** Money at risk over time: the sales projected late, by the period their demand is due, a line a scenario. */
export function RiskOverTime({ title, periods, rows, cur }: {
  title: string; periods: WhatIfResult["periods"]; rows: { label: string; at_risk?: number[] | null }[]; cur: string;
}) {
  const ps = periods ?? [];
  if (!ps.length) return null;
  const labels = ps.map((p) => p.label);
  const shown = rows.slice(0, SERIES.length);
  const total = (v?: number[] | null) => (v ?? []).reduce((a, b) => a + b, 0);
  return (
    <Panel title={title}>
      {shown.every((r) => total(r.at_risk) === 0)
        ? <p className="small muted" style={{ margin: 0 }}>No sales are projected late in any period.</p>
        // the first (today, or the baseline) dashed and drawn last, so a scenario with the same figures never hides it
        : <BucketChart labels={labels} format={(v) => money(v, cur)}
            series={[...shown.slice(1).map((r, i) => ({ name: r.label, color: SERIES[i + 1], values: r.at_risk ?? [], kind: "line" as const })),
              { name: shown[0].label, color: SERIES[0], values: shown[0].at_risk ?? [], kind: "line" as const, dash: true }]} />}
      <details className="small" style={{ marginTop: 8 }}>
        <summary>The figures by period</summary>
        <div className="table-wrap">
          <table className="t" aria-label="Money at risk by period">
            <thead><tr><th>Period</th>{shown.map((r) => <th key={r.label} className="num">{r.label}</th>)}</tr></thead>
            <tbody>
              {ps.map((p, i) => shown.some((r) => (r.at_risk ?? [])[i]) ? (
                <tr key={p.label}><td>{p.label}</td>{shown.map((r) => <td key={r.label} className="num">{money((r.at_risk ?? [])[i] ?? 0, cur)}</td>)}</tr>
              ) : null)}
              <tr><td><b>All periods</b></td>{shown.map((r) => <td key={r.label} className="num"><b>{money(total(r.at_risk), cur)}</b></td>)}</tr>
            </tbody>
          </table>
        </div>
      </details>
    </Panel>
  );
}
