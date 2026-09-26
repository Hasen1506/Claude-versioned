import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, DdmrpRow, InventoryResult, NodeInventory, PoolingRow } from "../api/types";
import {
  Badge, Empty, Panel, Provenance, Reading, SolverIO, StageHeader, StaleMark, StatTile, Tabs, RunButton, Term,
} from "../components/ui";
import { money, pct, qty } from "../lib/format";
import { Loc, Prod } from "../lib/names";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "overview" | "placement" | "ddmrp" | "pooling" | "settings";
const key = (n: { location: string; product: string }) => `${n.location}|${n.product}`;
const days = (v: number) => `${v.toFixed(v < 10 && v % 1 ? 1 : 0)} d`;

export function Inventory({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.inventory);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "inventory"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const view = ((route[1] as View) || "overview") as View;

  const head = (
    <StageHeader title="Buffers" kicker="Where to hold safety stock across the network, and how much, for the service you promise customers."
      how={<>The guaranteed-service model (<Term t="MEIO" />) tries every placement of buffers along each product's path and keeps the one
        that is cheapest to hold for the <Term t="Service level">service level</Term> promised to customers. <Term t="DDMRP" /> sizes
        decoupling buffers with red, yellow and green zones. Pooling shows what holding stock in fewer places would save.</>}
      answer={res?.totals && bufferAnswer(res)}
      right={<>
      {res && <Provenance kind="solved" at={run.at} stale={stale} />}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("inventory")} disabled={blocking} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  if (view === "settings") return body(<><Nav view={view} res={res} /><SettingsView ds={ds} /></>);
  if (run.error) return body(<div className="banner error"><Badge sev="error">Optimisation failed</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="Which locations hold safety stock, how much, and what it costs to carry, against the single-echelon baseline."
        from="Demand (released forecast and orders), forecast-error CV, lead times, BOMs and lanes, unit values, service levels."
        feeds="Safety-stock policies used by the supply plan (after your approval), DDMRP buffer positions." />
      <div style={{ height: 14 }} />
      <Panel><Empty title={blocking ? "Fix blocking readiness issues first" : "Not optimised yet"}>
        {blocking ? <a className="btn" href={href("readiness")}>Open readiness</a>
          : <p>Run the optimisation to compare today's safety stock with single-echelon and multi-echelon placement.</p>}
      </Empty></Panel></>);
  }
  if (!res.ok || !res.totals) {
    return body(<div className="banner error"><Badge sev="error">Not optimised</Badge>
      {res.issues.some((i) => i.severity === "error") ? <>The dataset has blocking readiness issues. <a href={href("readiness")}>Review them</a>.</> : res.solver?.message}</div>);
  }
  return body(<>
    {stale && <StaleMark what="optimisation" onRerun={() => store.run("inventory")} busy={run.running} />}
    <Nav view={view} res={res} />
    {view === "overview" && <Overview res={res} />}
    {view === "placement" && <Placement res={res} ds={ds} />}
    {view === "ddmrp" && <Ddmrp res={res} ds={ds} />}
    {view === "pooling" && <Pooling res={res} />}
  </>);
}

function Nav({ view, res }: { view: View; res: InventoryResult | null }) {
  const stocking = res?.nodes.filter((n) => n.role !== "customer").length;
  return (
    <Tabs<View> value={view} onChange={(v) => go("inventory", v)} tabs={[
      { id: "overview", label: "Overview" },
      { id: "placement", label: "Multi-echelon placement", count: stocking },
      { id: "ddmrp", label: "DDMRP buffers", count: res?.totals?.ddmrp_positions },
      { id: "pooling", label: "Pooling", count: res?.pooling.length },
      { id: "settings", label: "Settings" },
    ]} />
  );
}

function bufferAnswer(res: InventoryResult) {
  const t = res.totals!, c = res.currency;
  const where = `${t.buffers_placed} of ${t.stocking_nodes} places`;
  if (t.saving_vs_current > 0.5)
    return <>Safety stock worth {money(t.current_ss_value, c)} today could be {money(t.meio_ss_value, c)} held at {where},
      saving {money(t.saving_vs_current, c)} a year to carry.</>;
  return <>The service you promise needs {money(t.meio_ss_value, c)} of safety stock held at {where},
    {t.saving_vs_current < -0.5 ? <> {money(-t.saving_vs_current, c)} a year more to carry than today's.</> : <> about what you hold today.</>}</>;
}

// ------------------------------------------------------------------------------------------------
function Overview({ res }: { res: InventoryResult }) {
  const t = res.totals!;
  const c = res.currency;
  const bars: [string, number, string][] = [
    ["Configured today", t.current_ss_value, "var(--text-3)"],
    ["Single-echelon", t.single_ss_value, "var(--series-1)"],
    ["Multi-echelon (GSM)", t.meio_ss_value, "var(--series-3)"],
  ];
  const max = Math.max(1, ...bars.map(([, v]) => v));
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Safety stock today" value={money(t.current_ss_value, c)} sub={`${money(t.current_cost, c)} / year to carry`} />
        <StatTile label="Single-echelon" value={money(t.single_ss_value, c)} sub="every stage buffers its own lead time" />
        <StatTile label="Multi-echelon" value={money(t.meio_ss_value, c)} sub={`${t.buffers_placed} of ${t.stocking_nodes} stages hold stock`} />
        <StatTile label="Saving vs single-echelon" value={money(t.saving_vs_single, c)}
          sub={`${pct(t.single_cost ? t.saving_vs_single / t.single_cost : 0)} of carrying cost per year`} />
        <StatTile label="Change vs today" value={money(-t.saving_vs_current, c)} sub="carrying cost per year (negative = saving)" />
      </div>
      <div className="grid-2">
        <Panel title="Safety-stock value by policy">
          <div className="bar-list">
            {bars.map(([label, v, color]) => (
              <div key={label} className="bar-row">
                <span className="muted">{label}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / max) * 100}%`, background: color }} /></div>
                <span className="num">{money(v, c)}</span>
              </div>
            ))}
          </div>
          <p className="faint small" style={{ marginBottom: 0 }}>Holding cost = unit value × carrying rate ({pct(res.carrying_rate)} a year unless a
            location-product overrides it). Service levels come from each policy or the company default.</p>
        </Panel>
        <Panel title="Placement solver">
          <table className="t">
            <tbody>
              <tr><td className="muted">Status</td><td><Badge sev={res.solver?.status === "optimal" ? "ok" : "warning"}>{res.solver?.status}</Badge></td></tr>
              <tr><td className="muted">Model</td><td>Guaranteed service (Graves–Willems), exact MILP over whole days</td></tr>
              <tr><td className="muted">Size</td><td className="num">{res.solver?.variables} variables · {res.solver?.constraints} constraints</td></tr>
              <tr><td className="muted">Solve time</td><td className="num">{(res.solver?.seconds ?? 0).toFixed(2)} s</td></tr>
            </tbody>
          </table>
        </Panel>
      </div>
      <Reading formula={<>SS<sub>j</sub> = z · √(τ<sub>j</sub>·σ<sub>d</sub>² + d̄²·σ<sub>L</sub>²), τ<sub>j</sub> = SI<sub>j</sub> + T<sub>j</sub> − S<sub>j</sub>.
        The solver picks the outbound service times S that minimise Σ h·z·σ·√τ, with demand-facing stages quoting at most the customer service time.</>}
        soWhat={<>Places that need no stock pass their suppliers' lead time straight on; stock sits where it is cheapest to hold.
          Nothing changes in the plan until you approve a recommendation under <a href={href("inventory", "placement")}>Multi-echelon placement</a>.</>} />
      {res.notes.length > 0 && <details className="how"><summary>Assumptions ({res.notes.length})</summary><div>
        <ul style={{ margin: 0, paddingLeft: 18 }}>{res.notes.map((n) => <li key={n}>{n}</li>)}</ul></div></details>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
/** Timeline per stage: order arrives at 0; the stage waits SI for its inputs, takes T to replenish,
 *  and promises S downstream. Stock covers the gap from S to SI + T (τ). */
function PlacementChart({ nodes }: { nodes: NodeInventory[] }) {
  const rows = nodes.slice(0, 60);
  const maxT = Math.max(1, ...rows.map((n) => n.meio_inbound_days + Math.ceil(n.lead_time_days - 1e-9), 1));
  const W = 900, L = 210, R = 16, rh = 22, top = 22;
  const H = top + rows.length * rh + 24;
  const x = (d: number) => L + (d / maxT) * (W - L - R);
  const ticks = Array.from({ length: 6 }, (_, k) => Math.round((maxT * k) / 5));
  return (
    <div>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span><span className="key dash" style={{ background: "var(--text-2)" }} />waiting for inputs (SI)</span>
        <span><span className="key box" style={{ background: "var(--series-1)" }} />own lead time (T)</span>
        <span><span className="key box" style={{ background: "var(--hl)" }} />covered by stock (τ)</span>
        <span>▼ service quoted downstream (S)</span>
      </div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="Service-time placement per stage">
        {ticks.map((t) => (
          <g key={t}>
            <line className="gridline" x1={x(t)} x2={x(t)} y1={top - 6} y2={H - 20} />
            <text x={x(t)} y={H - 6} textAnchor="middle">{t} d</text>
          </g>
        ))}
        {rows.map((n, i) => {
          const y = top + i * rh;
          const T = Math.ceil(n.lead_time_days - 1e-9);
          const si = n.meio_inbound_days, s = n.meio_service_days;
          return (
            <g key={key(n)}>
              <text x={L - 8} y={y + 14} textAnchor="end">{n.location} · {n.product}</text>
              {n.meio_net_days > 0 && <rect x={x(s)} width={Math.max(2, x(si + T) - x(s))} y={y + 2} height={16} fill="var(--hl)" />}
              {si > 0 && <line x1={x(0)} x2={x(si)} y1={y + 10} y2={y + 10} stroke="var(--text-2)" strokeWidth={2} strokeDasharray="4 3" />}
              {T > 0 && <rect x={x(si)} width={Math.max(2, x(si + T) - x(si) - 2)} y={y + 7} height={6} fill="var(--series-1)" />}
              <path d={`M${x(s) - 5},${y} h10 l-5,7 z`} fill="var(--ink)" />
            </g>
          );
        })}
      </svg>
      {nodes.length > rows.length && <p className="faint small">Showing the first {rows.length} of {nodes.length} stages; the table has all of them.</p>}
    </div>
  );
}

function Placement({ res, ds }: { res: InventoryResult; ds: Dataset }) {
  const c = res.currency;
  const stages = useMemo(() => [...res.nodes].filter((n) => n.role !== "customer").reverse(), [res]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [confirm, setConfirm] = useState(false);
  const target = (n: NodeInventory) => (n.role === "stocking" ? Math.ceil(n.meio_ss - 1e-9) : 0);
  const changes = stages.filter((n) => sel.has(key(n)) && n.role === "stocking");
  const delta = changes.reduce((a, n) => a + (target(n) - n.current_ss) * n.unit_value, 0);
  const [applying, setApplying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // the engine writes the policies (POST /api/inventory/apply), so a script applies exactly what this button does
  const apply = async () => {
    setApplying(true);
    setErr(null);
    try {
      const out = await api.applyPlacement(ds, changes.map((n) => `${n.location}|${n.product}`));
      store.replace(out.dataset);
      setSel(new Set());
      setConfirm(false);
    } catch (e) {
      setErr(String(e));
    } finally {
      setApplying(false);
    }
  };
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const differs = stages.filter((n) => n.role === "stocking" && Math.abs(target(n) - n.current_ss) >= 1);
  return (
    <div className="stack">
      <Panel title="Where the network holds stock"><PlacementChart nodes={stages} /></Panel>
      {err && <div className="banner error" role="alert">{err}</div>}
      {confirm && changes.length > 0 && (
        <div className="banner info" role="dialog" aria-label="Approve safety-stock changes">
          <Badge sev="warning">Approval</Badge>
          <span>Set {changes.length} safety-stock polic{changes.length === 1 ? "y" : "ies"} to the multi-echelon recommendation as a fixed quantity
            ({changes.filter((n) => target(n) === 0).length} to none). Safety-stock value changes by <b>{money(delta, c)}</b>. The supply plan becomes stale; undo reverts it.</span>
          <span className="spacer" />
          <button className="btn sm accent" onClick={apply} disabled={applying}>{applying ? "Saving…" : "Use these buffers in the plan"}</button>
          <button className="btn sm ghost" onClick={() => setConfirm(false)}>Cancel</button>
        </div>
      )}
      <Panel flush title="Recommendations" actions={<div className="row">
        <button className="btn sm" onClick={() => setSel(new Set(differs.map(key)))} disabled={!differs.length}>Select all that differ ({differs.length})</button>
        <button className="btn sm primary" disabled={!changes.length} onClick={() => setConfirm(true)}>Review {changes.length || ""} change{changes.length === 1 ? "" : "s"}…</button>
      </div>}>
        <div className="table-wrap" style={{ maxHeight: 520 }}>
          <table className="t nowrap">
            <thead><tr><th aria-label="Select" /><th>Location</th><th>Product</th><th>Decision</th>
              <th className="num">Demand / day</th><th className="num">CV (week)</th><th className="num">Lead time</th>
              <th className="num">SI</th><th className="num">S</th><th className="num">τ</th>
              <th className="num">Today</th><th className="num">Single-echelon</th><th className="num">Multi-echelon</th><th className="num">Value change</th></tr></thead>
            <tbody>
              {stages.map((n) => {
                const k = key(n);
                const lpExists = ds.location_products?.some((x) => x.location === n.location && x.product === n.product);
                return (
                  <tr key={k} className={sel.has(k) ? "selected" : ""}>
                    <td>{n.role === "stocking" && <input type="checkbox" aria-label={`Select ${n.location} ${n.product}`} checked={sel.has(k)} onChange={() => toggle(k)} />}</td>
                    <td>{n.location}{n.demand_facing && <span className="faint small"> · faces demand</span>}</td>
                    <td><b><Prod id={n.product} /></b>{!lpExists && <span className="faint small"> · no policy yet</span>}</td>
                    <td>{n.decision === "buffer" ? <Badge sev="ok">buffer</Badge> : n.decision === "no_stock" ? <Badge>make to order</Badge> : <Badge>pass through</Badge>}</td>
                    <td className="num">{qty(n.mean_daily)}</td>
                    <td className="num" title={`source: ${n.cv_source}`}>{n.cv_weekly.toFixed(2)}<span className="faint small"> {n.cv_source === "policy" ? "measured" : n.cv_source}</span></td>
                    <td className="num">{days(n.lead_time_days)}</td>
                    <td className="num">{n.meio_inbound_days}</td>
                    <td className="num">{n.meio_service_days}{n.max_service_days !== null && <span className="faint small"> ≤{n.max_service_days}</span>}</td>
                    <td className="num"><b>{n.meio_net_days}</b></td>
                    <td className="num">{qty(n.current_ss)}<div className="faint small">{n.current_method}</div></td>
                    <td className="num">{qty(n.single_ss)}</td>
                    <td className="num"><b>{qty(target(n))}</b></td>
                    <td className="num">{money((target(n) - n.current_ss) * n.unit_value, c)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="SI = inbound service time (the longest service quoted by its suppliers); S = outbound service time; τ = SI + T − S days of demand covered from stock."
        soWhat="Applying writes a fixed safety-stock quantity to each approved location-product, so the supply plan holds exactly this stock. Re-optimise after demand or lead times change." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function ZoneBar({ r, scale }: { r: DdmrpRow; scale: number }) {
  const w = (v: number) => `${(v / scale) * 100}%`;
  const marker = Math.min(1, Math.max(0, r.nfp / scale));
  return (
    <div style={{ position: "relative", height: 16, minWidth: 180, background: "var(--surface-2)" }}
      title={`TOR ${qty(r.tor)} · TOY ${qty(r.toy)} · TOG ${qty(r.tog)} · NFP ${qty(r.nfp)}`}>
      <div style={{ display: "flex", height: "100%", gap: 2 }}>
        <div style={{ width: w(r.red), background: "var(--critical)" }} />
        <div style={{ width: w(r.yellow), background: "var(--warning)" }} />
        <div style={{ width: w(r.green), background: "var(--good)" }} />
      </div>
      <div style={{ position: "absolute", top: -3, bottom: -3, left: `calc(${marker * 100}% - 1px)`, width: 3, background: "var(--ink)" }} />
    </div>
  );
}

function Ddmrp({ res, ds }: { res: InventoryResult; ds: Dataset }) {
  const [all, setAll] = useState(false);
  // the checkbox shows the dataset (what you set), the zones show the last run (what was computed)
  const isPos = (r: DdmrpRow) => ds.location_products?.find((x) => x.location === r.location && x.product === r.product)?.ddmrp_buffer ?? false;
  const rows = res.ddmrp.filter((r) => all || r.positioned || isPos(r));
  const scale = Math.max(1, ...rows.map((r) => Math.max(r.tog, r.nfp)));
  const setPos = (r: DdmrpRow, on: boolean) => store.update((d) => {
    d.location_products ??= [];
    let lp = d.location_products.find((x) => x.location === r.location && x.product === r.product);
    if (!lp) {
      lp = { location: r.location, product: r.product } as (typeof d.location_products)[number];
      d.location_products.push(lp);
    }
    lp.ddmrp_buffer = on;
  });
  const c = res.currency;
  return (
    <div className="stack">
      {!res.totals?.ddmrp_positions && !all && (
        <div className="banner info"><Badge>No positions</Badge><span>No location-product is a DDMRP decoupling point yet. Show every stocking
          stage to see the buffer it would need, then position the ones you want.</span></div>
      )}
      <Panel flush title="Buffers and net flow" actions={<label className="row small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show every stocking stage</label>}>
        <div className="legend" style={{ padding: "8px 12px 0" }}>
          <span><span className="key box" style={{ background: "var(--critical)" }} />red (safety)</span>
          <span><span className="key box" style={{ background: "var(--warning)" }} />yellow (demand over DLT)</span>
          <span><span className="key box" style={{ background: "var(--good)" }} />green (order cycle)</span>
          <span><span className="key" style={{ background: "var(--ink)", width: 3 }} />net flow position</span>
        </div>
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="t nowrap">
            <thead><tr><th>Positioned</th><th>Location</th><th>Product</th><th className="num">ADU</th><th className="num">DLT</th>
              <th>LTF · VF</th><th>Buffer</th><th className="num">NFP</th><th>Zone</th><th className="num">Order</th><th className="num">Avg value</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={key(r)}>
                  <td><input type="checkbox" aria-label={`Position buffer at ${r.location} ${r.product}`} checked={isPos(r)} onChange={(e) => setPos(r, e.target.checked)} /></td>
                  <td><Loc id={r.location} /></td><td><b><Prod id={r.product} /></b></td>
                  <td className="num">{qty(r.adu)}</td>
                  <td className="num">{days(r.dlt)}</td>
                  <td className="small">{r.ltf} ({r.lt_band}) · {r.vf} ({r.var_band})</td>
                  <td style={{ width: "30%" }}><ZoneBar r={r} scale={scale} /></td>
                  <td className="num">{qty(r.nfp)}</td>
                  <td><Badge sev={r.zone === "red" ? "error" : r.zone === "yellow" ? "warning" : r.zone === "green" ? "ok" : "info"}>{r.zone}</Badge> <span className="faint small">{pct(r.priority, 0)}</span></td>
                  <td className="num">{r.order_qty > 0 ? <b>{qty(r.order_qty)}</b> : "—"}</td>
                  <td className="num">{money(r.average_value, c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="Yellow = ADU × DLT; red = ADU × DLT × LTF × (1 + VF); green = max(ADU × order cycle, ADU × DLT × LTF, MOQ). NFP = on hand + open supply − qualified demand (orders due today and spikes inside the DLT)."
        soWhat="Positioning a buffer cuts the decoupled lead time of every stage it feeds. Order TOG − NFP whenever NFP falls to the top of yellow or below." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Pooling({ res }: { res: InventoryResult }) {
  const c = res.currency;
  if (!res.pooling.length) return <Panel><Empty title="Nothing to pool">No product is stocked at two or more demand-facing locations.</Empty></Panel>;
  const max = Math.max(1, ...res.pooling.map((p) => p.separate_ss * p.unit_value));
  return (
    <div className="stack">
      <Panel flush title="Separate vs pooled safety stock">
        <table className="t nowrap">
          <thead><tr><th>Product</th><th>Locations</th><th className="num">Lead time</th><th className="num">Separate</th><th className="num">Pooled</th>
            <th>Value</th><th className="num">Saving</th></tr></thead>
          <tbody>
            {res.pooling.map((p: PoolingRow) => (
              <tr key={p.product}>
                <td><b><Prod id={p.product} /></b></td><td className="small">{p.locations.join(", ")}</td>
                <td className="num">{days(p.lead_time_days)}</td>
                <td className="num">{qty(p.separate_ss)}</td><td className="num">{qty(p.pooled_ss)}</td>
                <td style={{ width: "28%" }}>
                  <div className="bar-track" title={`separate ${money(p.separate_ss * p.unit_value, c)}`}><div className="bar-fill" style={{ width: `${(p.separate_ss * p.unit_value / max) * 100}%`, background: "var(--series-1)" }} /></div>
                  <div className="bar-track" style={{ marginTop: 2 }} title={`pooled ${money(p.pooled_ss * p.unit_value, c)}`}><div className="bar-fill" style={{ width: `${(p.pooled_ss * p.unit_value / max) * 100}%`, background: "var(--series-3)" }} /></div>
                </td>
                <td className="num"><b>{money(p.saving_value, c)}</b><div className="faint small">{pct(p.saving_pct, 0)}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="legend" style={{ padding: "8px 12px" }}>
          <span><span className="key box" style={{ background: "var(--series-1)" }} />separate</span>
          <span><span className="key box" style={{ background: "var(--series-3)" }} />pooled</span>
        </div>
      </Panel>
      <Reading formula="Separate = Σ z·σᵢ·√Lᵢ; pooled = z·√(Σσᵢ²)·√L̄ (L̄ demand-weighted). With n equal, independent locations the pooled stock is 1/√n of the separate total."
        soWhat="The saving is an upper bound: consolidating stock lengthens delivery to customers and adds transport. Weigh it against the service time customers accept." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function SettingsView({ ds }: { ds: Dataset }) {
  const schemaErrors = useStore((s) => s.schemaErrors);
  const errors: Record<string, string> = {};
  for (const e of schemaErrors) {
    const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
    if (loc[0] === "inventory") errors[loc.slice(1).join(".")] = e.msg;
  }
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Inventory settings">
        <SchemaForm defName="InventorySettings" value={(ds.inventory ?? {}) as unknown as Obj} errors={errors}
          onChange={(next) => store.update((d) => { d.inventory = next as unknown as Dataset["inventory"]; })} />
      </Panel>
      <div className="stack">
        <Reading formula="Customer service days = 0 means customers are served from stock at the stages that face demand. Raising it lets those stages quote a lead time and moves stock upstream."
          soWhat="Per location-product, 'max service days' caps the service a stage may quote and 'DDMRP buffer' positions a decoupling point. Both are in Master data → Location-products." />
      </div>
    </div>
  );
}
