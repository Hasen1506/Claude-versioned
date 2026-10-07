// Roadmap E: what-if side by side (UX audit section 4). Two to four scenarios are planned from the working copy (the
// first is the baseline) and compared in one table: cost, service, inventory, capacity and late units, with each
// scenario's deltas against the baseline, the cost of one point of service, and the levers it pulled. A scenario is
// built from chips, quick changes made in one click.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { WhatIfChip, WhatIfResult, WhatIfScenarioOut } from "../api/types";
import { Badge, Empty, Panel, Reading, StageHeader } from "../components/ui";
import { money, pct, qty } from "../lib/format";
import { href } from "../lib/router";
import { useStore } from "../state/store";

interface Scenario { label: string; chips: WhatIfChip[] }

const MAX = 4;

/** What a chip says on its button and in the table (the engine labels the levers the same way). */
export function chipLabel(c: WhatIfChip): string {
  switch (c.kind) {
    case "demand": return `Demand ${c.pct > 0 ? "+" : ""}${c.pct} %${c.products?.length ? ` (${c.products.join(", ")})` : ""}`;
    case "supplier_out": return `${c.supplier} out`;
    case "lead_time": return `Lead time ${c.days > 0 ? "+" : ""}${c.days} d${c.supplier ? ` at ${c.supplier}` : ""}`;
    case "add_shift": return `Add a shift on ${c.resource}`;
    case "lane_delay": return `Routes ${c.location ? `via ${c.location} ` : ""}+${c.days} d`;
  }
}

const sign = (v: number, f: (x: number) => string) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(Math.abs(v))}`;

export function WhatIf() {
  const ds = useStore((s) => s.dataset)!;
  const cur = ds.settings.currency;
  const suppliers = useMemo(() => [...new Set((ds.purchasing_sources ?? []).map((s) => s.supplier))].sort(), [ds]);
  const resources = useMemo(() => (ds.resources ?? []).map((r) => r.id), [ds]);
  const places = useMemo(() => [...new Set((ds.lanes ?? []).flatMap((l) => [l.origin, l.destination]))].sort(), [ds]);
  const [scen, setScen] = useState<Scenario[]>([{ label: "Baseline", chips: [] }, { label: "Scenario 1", chips: [] }]);
  const [active, setActive] = useState(1);
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // the chip being configured: which supplier / machine / place, how many days
  const [sup, setSup] = useState("");
  const [lt, setLt] = useState("7");
  const [resId, setResId] = useState("");
  const [place, setPlace] = useState("");
  const [delay, setDelay] = useState("7");

  const edit = (i: number, f: (s: Scenario) => Scenario) => { setScen(scen.map((s, j) => (j === i ? f(s) : s))); setRes(null); };
  const addChip = (c: WhatIfChip) => edit(active, (s) => ({ ...s, chips: [...s.chips, c] }));
  const addScenario = () => {
    if (scen.length >= MAX) return;
    const n = scen.length;
    setScen([...scen, { label: `Scenario ${n}`, chips: [] }]);
    setActive(n);
    setRes(null);
  };
  const remove = (i: number) => {
    setScen(scen.filter((_, j) => j !== i));
    setActive(Math.max(1, Math.min(active, scen.length - 2)));
    setRes(null);
  };
  const names = scen.map((s) => s.label.trim());
  const dup = new Set(names).size !== names.length || names.some((n) => !n);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.whatif(ds, scen.map((s) => ({ label: s.label.trim(), chips: s.chips }))));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setRes(null);
    } finally {
      setBusy(false);
    }
  };

  const a = scen[active];
  return (
    <div>
      <StageHeader title="What if… side by side" kicker={<>Try up to three changes against today's plan and see them next to each other:
        what each costs, what it does to service, stock and machines. Nothing here changes your data.</>}
        how={<>Every scenario is the working copy with its chips applied, planned in full (MRP). The first column is the baseline; the
          others show their difference from it, and the cost of one point of service where cost and service move together.
          To compare stored versions instead, use <a href={href("versions")}>Versions</a>.</>} />
      <div className="content">
        <Panel title="Scenarios" actions={scen.length < MAX && <button className="btn sm" onClick={addScenario}>+ Add a scenario</button>}>
          <div className="row" aria-label="Scenarios" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
            {scen.map((s, i) => (
              <div key={i} className={`panel tile ${i === active ? "hl" : ""}`} style={{ minWidth: 220, padding: 10 }}
                role="group" aria-label={`Scenario ${s.label}`} aria-current={i === active ? "true" : undefined} onClick={() => i > 0 && setActive(i)}>
                <div className="row" style={{ gap: 6 }}>
                  <input className="input" value={s.label} aria-label={`Name of scenario ${i + 1}`} style={{ width: 150 }}
                    onChange={(e) => edit(i, (x) => ({ ...x, label: e.target.value }))} />
                  {i === 0 ? <Badge sev="info">baseline</Badge>
                    : scen.length > 2 && <button className="btn sm ghost" aria-label={`Remove ${s.label}`} onClick={(e) => { e.stopPropagation(); remove(i); }}>×</button>}
                </div>
                <div className="row" style={{ gap: 4, flexWrap: "wrap", marginTop: 6 }} aria-label={`Chips of ${s.label}`}>
                  {i === 0 && <span className="faint small">today's data, as it is</span>}
                  {i > 0 && s.chips.length === 0 && <span className="faint small">no change yet: add chips below</span>}
                  {s.chips.map((c, k) => (
                    <span key={k} className="chip on">{chipLabel(c)}
                      <button aria-label={`Remove ${chipLabel(c)} from ${s.label}`}
                        onClick={(e) => { e.stopPropagation(); edit(i, (x) => ({ ...x, chips: x.chips.filter((_, j) => j !== k) })); }}>×</button></span>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {a && active > 0 && <div style={{ marginTop: 12 }}>
            <p className="small muted" style={{ marginTop: 0 }}>Add a change to <b>{a.label || "this scenario"}</b>:</p>
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }} aria-label="Quick changes">
              {[10, 20, -10, -20].map((p) => <button key={p} className="btn sm" onClick={() => addChip({ kind: "demand", pct: p, products: [] })}>
                {chipLabel({ kind: "demand", pct: p, products: [] })}</button>)}
            </div>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              <select className="input" aria-label="Supplier" value={sup} onChange={(e) => setSup(e.target.value)}>
                <option value="">Supplier…</option>{suppliers.map((s) => <option key={s} value={s}>{s}</option>)}</select>
              <button className="btn sm" disabled={!sup} onClick={() => addChip({ kind: "supplier_out", supplier: sup })}>Supplier out</button>
              <input className="input" type="number" aria-label="Lead time change in days" value={lt} style={{ width: 70 }} onChange={(e) => setLt(e.target.value)} />
              <button className="btn sm" disabled={!(Number(lt) !== 0 && Number.isFinite(Number(lt)))}
                onClick={() => addChip({ kind: "lead_time", days: Number(lt), supplier: sup || null })}>{sup ? `Lead time at ${sup}` : "Lead time, every supplier"}</button>
            </div>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              <select className="input" aria-label="Machine or line" value={resId} onChange={(e) => setResId(e.target.value)}>
                <option value="">Machine or line…</option>{resources.map((r) => <option key={r} value={r}>{r}</option>)}</select>
              <button className="btn sm" disabled={!resId} onClick={() => addChip({ kind: "add_shift", resource: resId })}>Add a shift</button>
              <select className="input" aria-label="Place on the routes" value={place} onChange={(e) => setPlace(e.target.value)}>
                <option value="">Every route</option>{places.map((p) => <option key={p} value={p}>Routes via {p}</option>)}</select>
              <input className="input" type="number" min={0} aria-label="Route delay in days" value={delay} style={{ width: 70 }} onChange={(e) => setDelay(e.target.value)} />
              <button className="btn sm" disabled={!(Number(delay) > 0)} onClick={() => addChip({ kind: "lane_delay", days: Number(delay), location: place || null })}>Delay routes</button>
            </div>
          </div>}
          <div className="row" style={{ gap: 10, marginTop: 14 }}>
            <button className="btn accent" disabled={busy || dup} onClick={run}>{busy ? "Planning every scenario…" : "Compare side by side"}</button>
            {dup && <span className="small"><Badge sev="warning">Names</Badge> give every scenario its own name</span>}
          </div>
        </Panel>
        {err && <div className="banner warning" role="alert">{err}</div>}
        {res ? <SideBySide r={res} currency={cur} /> : !err && <Empty title="Nothing compared yet">Pick a change for each scenario, then compare.</Empty>}
        <Reading formula="Cost per service point = (scenario cost − baseline cost) ÷ (scenario on-time fill rate − baseline) × 100, shown only when both move the same way (a trade-off)."
          soWhat="Decide with the price of service in front of you: an extra shift that buys 3 points of service for ₹40,000 a point, against an expedite that buys 1." />
      </div>
    </div>
  );
}

const VERDICT: Record<string, "ok" | "warning" | "info"> = { "better on both": "ok", "worse on both": "warning", "trade-off": "info", "same service": "info" };

function SideBySide({ r, currency }: { r: WhatIfResult; currency: string }) {
  const m = (v: number) => money(v, currency);
  type Row = [string, (s: WhatIfScenarioOut) => number, (v: number) => string, boolean];
  const rows: Row[] = [
    ["Total plan cost", (s) => s.total_cost, m, false],
    ["On-time service", (s) => s.service, (v) => pct(v, 1), true],
    ["Late units", (s) => s.late_units, qty, false],
    ["Sales at risk (late units × price)", (s) => s.late_revenue, m, false],
    ["Average inventory value", (s) => s.inventory_value_avg, m, false],
    ["Busiest machine", (s) => s.capacity_peak, (v) => pct(v, 0), false],
    ["Planned orders", (s) => s.orders, qty, false],
    ["Exceptions (errors)", (s) => s.errors, qty, false],
  ];
  const b = r.scenarios[0];
  return (
    <Panel flush title="Side by side">
      <div className="table-wrap">
        <table className="t" aria-label="What-if comparison">
          <thead><tr><th />{r.scenarios.map((s, i) => <th key={s.label} className="num">{s.label}
            {i === 0 && <div className="faint small">baseline</div>}
            {s.label === r.best_service && <div><Badge sev="ok">best service</Badge></div>}
            {s.label === r.lowest_cost && <div><Badge sev="info">lowest cost</Badge></div>}</th>)}</tr></thead>
          <tbody>
            <tr><td>Changes</td>{r.scenarios.map((s, i) => <td key={s.label} className="num small">
              {i === 0 ? <span className="faint">as today</span> : s.levers.map((l) => l.what).join(" · ") || <span className="faint">none</span>}</td>)}</tr>
            {rows.map(([label, get, fmt, higherBetter]) => (
              <tr key={label}><td>{label}</td>{r.scenarios.map((s, i) => {
                if (!s.ok) return <td key={s.label} className="num faint">—</td>;
                const v = get(s), d = v - get(b);
                const tone = i === 0 || !b.ok || Math.abs(d) < 1e-9 ? undefined : (d > 0) === higherBetter ? "ok" : "warning";
                return <td key={s.label} className="num">{fmt(v)}
                  {tone && <div><Badge sev={tone}>{label === "On-time service" ? `${sign(d * 100, (x) => x.toFixed(1))} pts` : sign(d, fmt)}</Badge></div>}</td>;
              })}</tr>
            ))}
            <tr><td>Cost per point of service</td>{r.scenarios.map((s, i) => <td key={s.label} className="num">
              {i === 0 ? <span className="faint">—</span> : s.cost_per_service_point != null
                ? (s.cost_delta ?? 0) < 0 ? `saves ${m(Math.abs(s.cost_per_service_point))} per point given up` : `${m(s.cost_per_service_point)} per point gained`
                : <span className="faint">{s.ok ? "no trade-off" : "—"}</span>}</td>)}</tr>
            <tr><td>Verdict</td>{r.scenarios.map((s, i) => <td key={s.label} className="num">
              {i === 0 ? <span className="faint">—</span> : s.verdict ? <Badge sev={VERDICT[s.verdict]}>{s.verdict}</Badge> : <Badge sev="error">not planned</Badge>}
              {s.note && <div className="small faint" style={{ whiteSpace: "normal", maxWidth: 260, marginLeft: "auto" }}>{s.note}</div>}</td>)}</tr>
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
