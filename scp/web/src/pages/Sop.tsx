import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, SopResult } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, cols, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs,
} from "../components/ui";
import { money, pct, qty } from "../lib/format";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "overview" | "demand" | "capacity" | "prices" | "supply" | "settings";

// A pinned result to compare scenarios against. It lives for the browser session, outside React
// state, so it survives navigating between tabs and pages.
let pinned: { label: string; res: SopResult } | null = null;

export function Sop({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.sop);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "sop"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const view = ((route[1] as View) || "overview") as View;
  const [releasing, setReleasing] = useState(false);
  const [released, setReleased] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const release = async () => {
    setReleasing(true);
    setErr(null);
    try {
      const out = await api.sopRelease(ds);
      store.replace(out.dataset);
      const r = out.release;
      setReleased(`${r.records} constrained demand records for ${r.nodes} demand points replaced ${r.replaced} forecast records ` +
        `(${qty(r.constrained_qty)} of ${qty(r.unconstrained_qty)} units can be supplied).`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setReleasing(false);
    }
  };

  const head = (
    <StageHeader n="05" title="Sales & operations planning" kicker={<>One linear programme over the whole network and horizon:
      what to make, buy and move each {ds.sop?.bucket ?? "month"} within capacity, supplier and lane limits, at least cost or most
      profit. Shadow prices say what each limit is costing you.</>} right={<>
      {res && <Provenance kind="solved" at={run.at} stale={stale} />}
      {res?.ok && <button className="btn" onClick={release} disabled={releasing || stale}
        title={stale ? "Re-solve first: the plan is stale" : "Replace forecast demand with the constrained plan"}>
        {releasing ? "Releasing…" : "Release to MRP"}</button>}
      <button className="btn accent" onClick={() => store.run("sop")} disabled={run.running || blocking}>
        {run.running ? "Solving…" : res ? "Re-solve" : "Solve"}
      </button></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const banners = <>
    {released && (
      <div className="banner info"><Badge sev="ok">Released</Badge><span>{released} The supply plan is now stale; undo reverts the release.</span>
        <span className="spacer" /><a className="btn sm" href={href("plan")}>Open supply plan</a>
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setReleased(null)}>✕</button></div>
    )}
    {err && <div className="banner error"><Badge sev="error">Release failed</Badge>{err}</div>}
  </>;
  if (view === "settings") return body(<><Nav view={view} res={res} /><Levers ds={ds} /></>);
  if (run.error) return body(<div className="banner error"><Badge sev="error">Solve failed</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      {banners}
      <SolverIO answers="The feasible volume plan: what can be sold, where it is made and bought, what it costs, and which limits bind."
        from="Released forecast and orders, stock, receipts, BOMs, routings, resource hours, supplier and lane limits, costs and prices."
        feeds="Constrained demand for MRP (on release), capacity decisions, finance (value of capacity)." />
      <div style={{ height: 14 }} />
      <Panel><Empty title={blocking ? "Fix blocking readiness issues first" : "Not solved yet"}>
        {blocking ? <a className="btn" href={href("readiness")}>Open readiness</a> : <p>Solve to see the constrained plan and its shadow prices.</p>}
      </Empty></Panel></>);
  }
  if (!res.ok || !res.kpis || !res.economics) {
    return body(<div className="banner error"><Badge sev="error">Not solved</Badge>
      {res.issues.some((i) => i.severity === "error") ? <>The dataset has blocking readiness issues. <a href={href("readiness")}>Review them</a>.</>
        : res.notes.join(" ")}</div>);
  }
  return body(<>
    {banners}
    {stale && <StaleMark what="S&OP plan" onRerun={() => store.run("sop")} busy={run.running} />}
    <Nav view={view} res={res} />
    {view === "overview" && <Overview res={res} />}
    {view === "demand" && <DemandView res={res} sel={route[2]} />}
    {view === "capacity" && <CapacityView res={res} sel={route[2]} />}
    {view === "prices" && <PricesView res={res} />}
    {view === "supply" && <SupplyView res={res} />}
  </>);
}

function Nav({ view, res }: { view: View; res: SopResult | null }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("sop", v)} tabs={[
      { id: "overview", label: "Overview" },
      { id: "demand", label: "Demand vs supply", count: res?.demand.length },
      { id: "capacity", label: "Capacity", count: res?.resources.filter((r) => r.finite).length },
      { id: "prices", label: "Shadow prices", count: res?.binding.length },
      { id: "supply", label: "Sourcing", count: res?.flows.filter((f) => f.qty.some((q) => q > 0)).length },
      { id: "settings", label: "Scenario levers" },
    ]} />
  );
}

// ------------------------------------------------------------------------------------------------
function Overview({ res }: { res: SopResult }) {
  const k = res.kpis!;
  const e = res.economics!;
  const c = res.currency;
  const [, force] = useState(0);
  const base = pinned && pinned.res !== res ? pinned : null;
  const costs: [string, number][] = [
    ["Purchases", e.purchase], ["Production", e.production], ["Transport & handling", e.transport], ["Holding", e.holding],
    ["Overtime", e.overtime], ["Late-delivery penalty", e.backlog_penalty], ["Lost-sale penalty", e.lost_penalty],
    ["Safety-stock shortfall", e.ss_penalty],
  ];
  const max = Math.max(1, ...costs.map(([, v]) => v));
  const labels = res.buckets.map((b) => b.label);
  const T = labels.length;
  const sum = (f: (t: number) => number) => Array.from({ length: T }, (_, t) => f(t));
  const demand = sum((t) => res.demand.reduce((a, d) => a + d.demand[t], 0));
  const sales = sum((t) => res.demand.reduce((a, d) => a + d.sales[t], 0));
  const late = sum((t) => res.demand.reduce((a, d) => a + d.backlog[t], 0));
  const delta = (now: number, was: number | undefined, fmt: (v: number) => string) =>
    was === undefined ? undefined : `${now - was >= 0 ? "+" : "−"}${fmt(Math.abs(now - was))} vs ${base!.label}`;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Demand served" value={pct(k.fill_rate)} sub={delta(k.fill_rate * 100, base ? base.res.kpis!.fill_rate * 100 : undefined, (v) => `${v.toFixed(1)} pts`) ?? `${qty(k.sales)} of ${qty(k.demand)} units`} tone="hl" />
        <StatTile label="On time" value={pct(k.on_time_rate)} sub={`${qty(k.backlog_end)} still open at the end`} />
        <StatTile label={res.mode === "profit" ? "Profit" : "Total cost"} value={money(res.mode === "profit" ? e.profit : e.total_cost, c)}
          sub={delta(res.mode === "profit" ? e.profit : e.total_cost, base ? (res.mode === "profit" ? base.res.economics!.profit : base.res.economics!.total_cost) : undefined, (v) => money(v, c)) ?? `revenue ${money(e.revenue, c)}`} />
        <StatTile label="Peak utilisation" value={pct(k.max_utilization, 0)} sub="of regular hours, busiest resource-bucket" />
        <StatTile label="Binding limits" value={res.binding.length} sub={res.binding[0] ? `top: ${res.binding[0].label}` : "none: the plan is unconstrained"} />
      </div>
      <div className="grid-2">
        <Panel title="Demand and the constrained plan">
          <BucketChart labels={labels} series={[
            { name: "Demand (unconstrained)", color: "var(--series-1)", values: demand, kind: "column" },
            { name: "Delivered (constrained)", color: "var(--series-3)", values: sales, kind: "column" },
            { name: "Open late", color: "var(--series-2)", values: late, kind: "line" },
          ]} />
        </Panel>
        <Panel title={res.mode === "profit" ? "Revenue and cost" : "Cost build-up"}>
          <div className="bar-list">
            {costs.map(([label, v]) => (
              <div key={label} className="bar-row">
                <span className="muted">{label}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></div>
                <span className="num">{money(v, c)}</span>
              </div>
            ))}
          </div>
          <p className="faint small" style={{ marginBottom: 0 }}>Penalties are the model's prices on late, lost and below-safety-stock
            outcomes (Scenario levers); they steer the plan and are not cash.</p>
        </Panel>
      </div>
      <Panel title="Scenario compare" actions={<button className="btn sm" onClick={() => {
        pinned = { label: `${res.mode} plan pinned ${new Date().toLocaleTimeString("en-GB")}`, res };
        force((x) => x + 1);
      }}>Pin this plan as baseline</button>}>
        {!pinned ? <p className="muted small" style={{ margin: 0 }}>Pin this plan, change the scenario levers (mode, demand or capacity
          factor, overtime), re-solve, and the tiles above show the difference.</p>
          : <table className="t"><thead><tr><th>Measure</th><th className="num">{pinned.label}</th><th className="num">This plan</th></tr></thead>
            <tbody>
              <tr><td>Mode</td><td className="num">{pinned.res.mode}</td><td className="num">{res.mode}</td></tr>
              <tr><td>Demand served</td><td className="num">{pct(pinned.res.kpis!.fill_rate)}</td><td className="num">{pct(k.fill_rate)}</td></tr>
              <tr><td>On time</td><td className="num">{pct(pinned.res.kpis!.on_time_rate)}</td><td className="num">{pct(k.on_time_rate)}</td></tr>
              <tr><td>Revenue</td><td className="num">{money(pinned.res.economics!.revenue, c)}</td><td className="num">{money(e.revenue, c)}</td></tr>
              <tr><td>Operating cost (excl. penalties)</td>
                <td className="num">{money(opCost(pinned.res), c)}</td><td className="num">{money(opCost(res), c)}</td></tr>
              <tr><td>Overtime hours</td><td className="num">{qty(otHours(pinned.res))}</td><td className="num">{qty(otHours(res))}</td></tr>
            </tbody></table>}
      </Panel>
      <SectionBand step="ƒ" title="How to read it" />
      <Reading formula="min Σ cost·flow + holding + overtime + penalties  s.t.  stock balance per node and bucket, demand balance (served, late, lost), hours ≤ regular + overtime, supplier / lane / storage / shelf-life limits."
        soWhat={<>A shadow price is the change in the objective from one more unit of a limit, valid within the range shown. Release the plan to make MRP
          plan against what the network can supply; the unconstrained demand stays here for gap analysis.</>} />
      <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>{res.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </div>
  );
}

const opCost = (r: SopResult) => {
  const e = r.economics!;
  return e.purchase + e.production + e.transport + e.holding + e.overtime;
};
const otHours = (r: SopResult) => r.resources.reduce((a, x) => a + x.overtime.reduce((b, v) => b + v, 0), 0);

// ------------------------------------------------------------------------------------------------
function DemandView({ res, sel }: { res: SopResult; sel?: string }) {
  const c = res.currency;
  const key = (d: { location: string; product: string }) => `${d.location}|${d.product}`;
  const cur = res.demand.find((d) => key(d) === sel) ?? res.demand[0];
  const labels = res.buckets.map((b) => b.label);
  if (!cur) return <Panel><Empty title="No demand in the horizon" /></Panel>;
  return (
    <div className="split" style={cols("minmax(240px, 320px) minmax(0, 1fr)")}>
      <Panel flush title="Demand points">
        <div className="table-wrap" style={{ maxHeight: "calc(100vh - 260px)" }}>
          <table className="t">
            <thead><tr><th>Point</th><th className="num">Served</th></tr></thead>
            <tbody>
              {res.demand.map((d) => {
                const dem = d.demand.reduce((a, v) => a + v, 0);
                const got = d.sales.reduce((a, v) => a + v, 0);
                return (
                  <tr key={key(d)} className={`clickable ${key(d) === key(cur) ? "selected" : ""}`} onClick={() => go("sop", "demand", key(d))}>
                    <td><b>{d.product}</b><div className="faint small">{d.location}</div></td>
                    <td className="num">{got < dem - 0.5 ? <Badge sev="warning">{pct(got / dem, 0)}</Badge> : pct(dem ? got / dem : 1, 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="stack">
        <Panel title={`${cur.product} at ${cur.location}`}>
          <BucketChart labels={labels} series={[
            { name: "Demand", color: "var(--series-1)", values: cur.demand, kind: "column" },
            { name: "Delivered", color: "var(--series-3)", values: cur.sales, kind: "column" },
            { name: "Open late", color: "var(--series-2)", values: cur.backlog, kind: "line" },
          ]} />
        </Panel>
        <Panel flush title="By bucket">
          <div className="table-wrap">
            <table className="t nowrap">
              <thead><tr><th>Bucket</th><th className="num">Demand</th><th className="num">Delivered</th><th className="num">Open late</th>
                <th className="num">Lost</th><th className="num">Marginal cost</th><th className="num">Price</th></tr></thead>
              <tbody>
                {res.buckets.map((b, t) => (
                  <tr key={b.index}>
                    <td>{b.label}</td><td className="num">{qty(cur.demand[t])}</td><td className="num">{qty(cur.sales[t])}</td>
                    <td className="num">{qty(cur.backlog[t])}</td><td className="num">{qty(cur.lost[t])}</td>
                    <td className="num">{money(cur.marginal_cost[t], c)}</td><td className="num">{money(cur.price, c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Reading formula="Marginal cost = the change in the objective from one more unit of demand in that bucket (the demand-balance dual)."
          soWhat="Where it exceeds the price, serving that extra unit loses money; where the plan leaves demand open, the marginal cost shows how far supply is from economic." />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function CapacityView({ res, sel }: { res: SopResult; sel?: string }) {
  const c = res.currency;
  const finite = res.resources.filter((r) => r.finite);
  const cur = finite.find((r) => r.resource === sel) ?? [...finite].sort((a, b) => Math.max(...b.utilization) - Math.max(...a.utilization))[0];
  const labels = res.buckets.map((b) => b.label);
  if (!cur) return <Panel><Empty title="No finite resources">Mark resources as finite to constrain the plan by their hours.</Empty></Panel>;
  return (
    <div className="stack">
      <div className="row wrap">
        {finite.map((r) => (
          <button key={r.resource} className={`btn sm ${r.resource === cur.resource ? "primary" : ""}`} onClick={() => go("sop", "capacity", r.resource)}>
            {r.resource} · {pct(Math.max(0, ...r.utilization.filter(Number.isFinite)), 0)}
          </button>
        ))}
      </div>
      <Panel title={`${cur.resource} at ${cur.location}: hours`}>
        <BucketChart labels={labels} unit=" h" series={[
          { name: "Load", color: "var(--series-1)", values: cur.load, kind: "column" },
          { name: "Regular capacity", color: "var(--text-2)", values: cur.capacity, kind: "step" },
          { name: "With overtime", color: "var(--series-2)", values: cur.capacity.map((v, t) => v + cur.overtime_limit[t]), kind: "step", dash: true },
        ]} />
      </Panel>
      <Panel flush title="Value of capacity">
        <div className="table-wrap">
          <table className="t nowrap">
            <thead><tr><th>Bucket</th><th className="num">Load</th><th className="num">Capacity</th><th className="num">Overtime used</th>
              <th className="num">Utilisation</th><th className="num">Shadow price / hour</th><th className="num">Valid for capacity</th></tr></thead>
            <tbody>
              {res.buckets.map((b, t) => (
                <tr key={b.index}>
                  <td>{b.label}</td><td className="num">{qty(cur.load[t])}</td><td className="num">{qty(cur.capacity[t])}</td>
                  <td className="num">{qty(cur.overtime[t])}{cur.overtime_limit[t] > 0 && <span className="faint small"> / {qty(cur.overtime_limit[t])}</span>}</td>
                  <td className="num">{Number.isFinite(cur.utilization[t]) ? pct(cur.utilization[t], 0) : "—"}</td>
                  <td className="num">{cur.shadow_price[t] > 0 ? <b>{money(cur.shadow_price[t], c)}</b> : money(0, c)}</td>
                  <td className="num small">{cur.shadow_price[t] > 0 ? `${fmtRange(cur.valid_down[t])} – ${fmtRange(cur.valid_up[t])} h` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="Shadow price = objective change per extra regular hour, holding while capacity stays inside the range shown."
        soWhat="A positive price marks a bottleneck: one more hour is worth that much. Compare it with the cost of a shift, overtime or a new machine (Finance turns it into an NPV)." />
    </div>
  );
}

const fmtRange = (v: number | null | undefined) => (v === null || v === undefined ? "∞" : qty(v));

// ------------------------------------------------------------------------------------------------
function PricesView({ res }: { res: SopResult }) {
  const c = res.currency;
  if (!res.binding.length) {
    return <Panel><Empty title="No binding limits">Nothing in the network constrains this plan: every limit has slack.</Empty></Panel>;
  }
  return (
    <div className="stack">
      <Panel flush title="Limits that bind, most valuable first">
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="t nowrap">
            <thead><tr><th>Kind</th><th>Constraint</th><th className="num">Limit</th><th className="num">Used</th>
              <th className="num">Value of one more</th><th className="num">Valid range</th></tr></thead>
            <tbody>
              {res.binding.map((b, i) => (
                <tr key={i}>
                  <td><Badge>{b.kind.replace("_", " ")}</Badge></td><td>{b.label}</td>
                  <td className="num">{qty(b.limit)} {b.unit}</td><td className="num">{qty(b.used)}</td>
                  <td className="num"><b>{money(b.shadow_price, c)}</b> <span className="faint small">/ {b.unit}</span></td>
                  <td className="num small">{b.valid_down === null && b.valid_up === null ? "—" : `${fmtRange(b.valid_down)} – ${fmtRange(b.valid_up)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="Every limit's dual value from the LP: resource hours, overtime ceilings, supplier and lane capacity, storage and shelf life."
        soWhat="Relax the most valuable limits first. A price only holds inside its range; beyond it another limit takes over." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function SupplyView({ res }: { res: SopResult }) {
  const c = res.currency;
  const flows = useMemo(() => res.flows.filter((f) => f.qty.some((q) => q > 1e-6)), [res]);
  return (
    <Panel flush title="Planned volumes by source (by receipt bucket)">
      <div className="table-wrap" style={{ maxHeight: 600 }}>
        <table className="t nowrap">
          <thead><tr><th>Kind</th><th>Source</th><th>To</th><th>Product</th><th className="num">Lead</th>
            {res.buckets.map((b) => <th key={b.index} className="num">{b.label}</th>)}<th className="num">Unit cost</th></tr></thead>
          <tbody>
            {flows.map((f) => (
              <tr key={`${f.kind}-${f.source_id}-${f.product}`}>
                <td>{f.kind}</td><td>{f.source_id}{f.origin && <div className="faint small">from {f.origin}</div>}</td>
                <td>{f.location}</td><td><b>{f.product}</b></td><td className="num">{f.lead_buckets}</td>
                {f.qty.map((q, t) => <td key={t} className="num">{q > 1e-6 ? qty(q) : <span className="faint">·</span>}</td>)}
                <td className="num">{money(f.unit_cost, c)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// ------------------------------------------------------------------------------------------------
function Levers({ ds }: { ds: Dataset }) {
  const schemaErrors = useStore((s) => s.schemaErrors);
  const errors: Record<string, string> = {};
  for (const e of schemaErrors) {
    const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
    if (loc[0] === "sop") errors[loc.slice(1).join(".")] = e.msg;
  }
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Scenario levers and penalties">
        <SchemaForm defName="SopSettings" value={(ds.sop ?? {}) as unknown as Obj} errors={errors}
          onChange={(next) => store.update((d) => { d.sop = next as unknown as Dataset["sop"]; })} />
      </Panel>
      <Reading formula="Cost mode serves all demand it can at least cost and prices unmet demand with the late and lost penalties. Profit mode maximises revenue − cost and only serves demand that earns more than it costs."
        soWhat="To compare scenarios: solve, pin the plan on the Overview, change a lever here, and solve again. Undo restores the levers." />
    </div>
  );
}
