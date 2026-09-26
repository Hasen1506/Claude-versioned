import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { AtpNode, CtpStep, Dataset, DemandRecord, OrderPromise, PromiseResult, ScheduleLine } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, cols, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, useTooltip, type Severity, RunButton, Term,
} from "../components/ui";
import { day, money, pct, plural, qty } from "../lib/format";
import { Loc, Prod, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "orders" | "atp" | "simulate" | "bop" | "allocations" | "settings";

// The last BOP simulation, kept across tab switches with the dataset revision it was run on.
let bopRun: { rev: number; res: PromiseResult } | null = null;

const STATUS: Record<OrderPromise["status"], [Severity, string]> = {
  on_time: ["ok", "on time"], late: ["warning", "late"], partial: ["warning", "partial"], unconfirmed: ["error", "unconfirmed"],
};
const CHANGE: Record<OrderPromise["change"], Severity | undefined> = {
  new: "info", kept: undefined, gained: "ok", lost: "error", changed: "info", unchanged: undefined,
};

export function Promising({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.promise);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "promise"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const view = ((route[1] as View) || "orders") as View;
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const commitPromises = async (mode: "entry" | "bop") => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.promiseCommit(ds, mode);
      store.replace(out.dataset);
      store.put("promise", out.result, store.get().revision);
      if (mode === "bop") bopRun = null;
      setNote(`${out.dataset.confirmations?.length ?? 0} schedule lines committed for ${out.result.kpis.orders} orders. ` +
        "Later checks treat them as promised supply; undo reverts the commit.");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <StageHeader title="Customer orders" kicker="What you can promise each customer order, how much, from where and when. Check a new order before you accept it."
      how={<>Each order is checked against <Term t="ATP" /> (stock and incoming supply not yet promised), in priority order, with its
        delivery rules, product allocations and alternative shipping locations. What stock can't cover is checked for <Term t="CTP" />:
        could it be moved, made or bought in time? Beyond the <Term t="RLT">replenishment lead time</Term> anything can be promised.
        {" "}<Term t="BOP" /> re-decides who gets scarce stock after a shortage.</>}
      answer={res?.kpis && (res.kpis.orders ? <>{res.kpis.on_time_orders === res.kpis.orders ? "All" : res.kpis.on_time_orders} of {plural(res.kpis.orders, "customer order")} can
        ship in full on the date asked.{res.kpis.unconfirmed_qty > 0.5 && <> {qty(Math.round(res.kpis.unconfirmed_qty))} units worth {money(res.kpis.value_unconfirmed, res.currency)} can't be confirmed yet.</>}
        {res.kpis.at_risk_orders > 0 && <> {plural(res.kpis.at_risk_orders, "earlier promise")} {res.kpis.at_risk_orders === 1 ? "is" : "are"} now at risk.</>}</> : <>There are no open customer orders.</>)}
      right={<>
      {res && <Provenance kind="solved" at={run.at} stale={stale} />}
      {res?.ok && <button className="btn" onClick={() => commitPromises("entry")} disabled={busy || stale}
        title={stale ? "Recalculate first" : "Saves every promised date and quantity on the orders in your data, so later checks keep them. Undo reverts it."}>Save these promised dates</button>}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("promise")} disabled={blocking} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const banners = <>
    {note && <div className="banner info"><Badge sev="ok">Committed</Badge><span>{note}</span><span className="spacer" />
      <a className="btn sm" href={href("data", "confirmations")}>View confirmations</a>
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setNote(null)}>✕</button></div>}
    {err && <div className="banner error"><Badge sev="error">Commit failed</Badge>{err}</div>}
  </>;
  if (view === "settings") return body(<><Nav view={view} res={res} /><SettingsView ds={ds} /></>);
  if (view === "simulate") return body(<><Nav view={view} res={res} /><Simulate ds={ds} /></>);
  if (view === "bop") return body(<>{banners}<Nav view={view} res={res} /><Bop ds={ds} busy={busy} onCommit={() => commitPromises("bop")} /></>);
  if (run.error) return body(<div className="banner error"><Badge sev="error">Check failed</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      {banners}
      <SolverIO answers="For every open sales order: how much can be confirmed on the requested date, the dates of the rest, from which location, and by which method (ATP, beyond RLT, CTP)."
        from="Stock, firm and planned receipts, MRP dependent demand, earlier confirmations, allocations, lanes, routings and free capacity."
        feeds="Confirmed schedule lines (on commit), backorder processing, customer service KPIs." />
      <div style={{ height: 14 }} />
      <Panel><Empty title={blocking ? "Fix blocking readiness issues first" : "Not checked yet"}>
        {blocking ? <a className="btn" href={href("readiness")}>Open readiness</a>
          : <p>Check the {ds.demand?.filter((d) => d.kind === "sales_order").length ?? 0} open sales orders against the supply picture.</p>}
      </Empty></Panel></>);
  }
  if (!res.ok) {
    return body(<div className="banner error"><Badge sev="error">Not checked</Badge>
      The dataset has blocking readiness issues. <a href={href("readiness")}>Review them</a>.</div>);
  }
  return body(<>
    {banners}
    {stale && <StaleMark what="availability check" onRerun={() => store.run("promise")} busy={run.running} />}
    {res.kpis.at_risk_orders > 0 && (
      <div className="banner error"><Badge sev="error">{res.kpis.at_risk_orders} promises at risk</Badge>
        <span>Committed confirmations exceed the current supply. Run backorder processing to decide who keeps what.</span>
        <span className="spacer" /><a className="btn sm" href={href("promise", "bop")}>Open BOP</a></div>
    )}
    <Nav view={view} res={res} />
    {view === "orders" && <Orders res={res} sel={route[2]} />}
    {view === "atp" && <Atp res={res} sel={route[2]} />}
    {view === "allocations" && <Allocations res={res} />}
  </>);
}

function Nav({ view, res }: { view: View; res: PromiseResult | null }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("promise", v)} tabs={[
      { id: "orders", label: "Sales orders", count: res?.orders.length },
      { id: "atp", label: "ATP picture", count: res?.nodes.length },
      { id: "simulate", label: "Check a new order" },
      { id: "bop", label: "Backorder processing" },
      { id: "allocations", label: "Allocations", count: res?.allocations.length },
      { id: "settings", label: "Rules & segments" },
    ]} />
  );
}

// ------------------------------------------------------------------------------------------------
function LineChip({ l }: { l: ScheduleLine }) {
  const from = useNames().loc(l.ship_from);
  return (
    <span className="chip" title={`ships ${day(l.ship_date)} from ${from} · delivers ${day(l.date)}`}>
      <b>{qty(l.qty)}</b>&nbsp;{day(l.date)}&nbsp;<span className="faint">{from}</span>
      {l.method !== "atp" && <>&nbsp;<Badge sev={l.method === "ctp" ? "info" : "warning"}>{l.method.toUpperCase()}</Badge></>}
      {!l.on_time && <>&nbsp;<span style={{ color: "var(--warning-text)" }}>late</span></>}
    </span>
  );
}

function Kpis({ res }: { res: PromiseResult }) {
  const k = res.kpis;
  return (
    <div className="grid-auto">
      <StatTile label="Orders on time" value={`${k.on_time_orders} / ${k.orders}`} sub={`${pct(k.qty ? k.on_time_qty / k.qty : 1)} of the quantity on the requested date`} tone={k.on_time_orders < k.orders ? "hl" : undefined} />
      <StatTile label="Confirmed" value={pct(k.qty ? k.confirmed_qty / k.qty : 1)} sub={`${qty(k.confirmed_qty)} of ${qty(k.qty)} units`} />
      <StatTile label="Unconfirmed" value={qty(k.unconfirmed_qty)} sub={`${money(k.value_unconfirmed, res.currency)} of sales on backorder`} />
      <StatTile label="Beyond RLT" value={qty(k.rlt_lines)} sub="lines confirmed without supply behind them" />
      <StatTile label="Capable-to-promise" value={qty(k.ctp_lines)} sub="lines quoted on new supply" />
      <StatTile label="Alternative location" value={qty(k.alternative_lines)} sub="lines shipped from a second choice" />
    </div>
  );
}

function Orders({ res, sel }: { res: PromiseResult; sel?: string }) {
  const n = useNames();
  const [filter, setFilter] = useState<"all" | "issues">("all");
  const rows = res.orders.filter((o) => filter === "all" || o.status !== "on_time" || o.at_risk);
  const cur = res.orders.find((o) => o.order === sel);
  return (
    <div className="stack">
      <Kpis res={res} />
      <Panel flush title="Open sales orders in entry sequence" actions={
        <div className="row">
          <button className={`btn sm ${filter === "all" ? "primary" : ""}`} onClick={() => setFilter("all")}>All</button>
          <button className={`btn sm ${filter === "issues" ? "primary" : ""}`} onClick={() => setFilter("issues")}>Not on time</button>
        </div>}>
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="t">
            <thead><tr><th>Order</th><th>Customer</th><th>Product</th><th className="num">Prio</th><th className="num">Qty</th><th>Requested</th>
              <th>Status</th><th>Schedule lines</th></tr></thead>
            <tbody>
              {rows.map((o) => {
                const [sev, label] = STATUS[o.status];
                return (
                  <tr key={o.order} className={`clickable ${o.order === sel ? "selected" : ""}`} onClick={() => go("promise", "orders", o.order === sel ? undefined : o.order)}>
                    <td><b>{o.order}</b>{o.complete_delivery && <div className="faint small">complete delivery</div>}</td>
                    <td title={o.location}>{n.loc(o.location)}</td><td title={o.product}>{n.prod(o.product)}</td><td className="num">{o.priority}</td><td className="num">{qty(o.qty)}</td>
                    <td>{day(o.requested)}</td>
                    <td><Badge sev={sev}>{label}</Badge> {o.at_risk && <Badge sev="error">at risk</Badge>}
                      {CHANGE[o.change] && o.change !== "new" && <> <Badge sev={CHANGE[o.change]}>{o.change}</Badge></>}</td>
                    <td><div className="chips">{o.lines.map((l, i) => <LineChip key={i} l={l} />)}
                      {o.unconfirmed > 1e-6 && <span className="chip" style={{ borderColor: "var(--critical)" }}><b>{qty(o.unconfirmed)}</b>&nbsp;open</span>}</div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      {cur && <OrderCard o={cur} currency={res.currency} />}
      <Reading formula="ATP(d) = min over later days e of [Σ receipts(≤ e) − Σ outflows(≤ e)] — the look-ahead keeps a new promise from taking stock an earlier promise needs later. Beyond the replenishment lead time everything is confirmable."
        soWhat="Commit promises to persist the schedule lines; after that, every check (and MRP's supply changes) is measured against them, and backorder processing decides who gives way in a shortage." />
    </div>
  );
}

function OrderCard({ o, currency }: { o: OrderPromise; currency: string }) {
  return (
    <Panel title={`${o.order}: ${qty(o.qty)} ${o.product} for ${o.location} on ${day(o.requested)}`}
      actions={<button className="btn sm ghost" onClick={() => go("promise", "orders")}>Close</button>}>
      <div className="grid-auto" style={{ marginBottom: 12 }}>
        <StatTile label="On time" value={qty(o.on_time)} sub={pct(o.qty ? o.on_time / o.qty : 0)} />
        <StatTile label="Confirmed" value={qty(o.confirmed)} sub={o.unconfirmed > 1e-6 ? `${qty(o.unconfirmed)} open` : "complete"} />
        <StatTile label="Order value" value={money(o.value, currency)} sub={`priority ${o.priority}`} />
        {o.allocation_capped > 0 && <StatTile label="Held back by allocation" value={qty(o.allocation_capped)} sub="on the requested date" />}
      </div>
      {o.reason && <div className="banner warning"><Badge sev="warning">Why not</Badge>{o.reason}</div>}
      {o.at_risk && <div className="banner error"><Badge sev="error">At risk</Badge>Supply no longer covers this confirmation: run backorder processing to re-promise it.</div>}
      <table className="t nowrap">
        <thead><tr><th>Ships from</th><th>Ship date</th><th>Delivery</th><th className="num">Qty</th><th>Method</th><th>On time</th></tr></thead>
        <tbody>
          {o.lines.map((l, i) => (
            <tr key={i}><td>{l.ship_from}</td><td>{day(l.ship_date)}</td><td>{day(l.date)}</td><td className="num">{qty(l.qty)}</td>
              <td>{l.method === "atp" ? "available-to-promise" : l.method === "rlt" ? <Badge sev="warning">beyond RLT</Badge> : <Badge sev="info">capable-to-promise</Badge>}</td>
              <td>{l.on_time ? <Badge sev="ok">yes</Badge> : <Badge sev="warning">late</Badge>}</td></tr>
          ))}
        </tbody>
      </table>
      {o.previous.length > 0 && <p className="faint small">Committed before: {o.previous.map((l) => `${qty(l.qty)} on ${day(l.date)} from ${l.ship_from}`).join(" · ")}</p>}
      {o.ctp.length > 0 && <><SectionBand step="CTP" title="How the new supply gets there" /><CtpTimeline steps={o.ctp} /></>}
    </Panel>
  );
}

// ------------------------------------------------------------------------------------------------
const STEP_COLOR: Record<CtpStep["kind"], string> = {
  stock: "var(--series-3)", component: "var(--series-5)", buy: "var(--series-2)", capacity: "var(--series-4)",
  make: "var(--series-1)", transfer: "var(--series-7)",
};

/** CTP chain as a small Gantt: each step's window, earliest at the top. */
function CtpTimeline({ steps }: { steps: CtpStep[] }) {
  const tip = useTooltip();
  const t = (d: string) => new Date(d + "T00:00:00").getTime() / 86400_000;
  const starts = steps.map((s) => t(s.start ?? s.end!));
  const ends = steps.map((s) => t(s.end ?? s.start!));
  const lo = Math.min(...starts), hi = Math.max(...ends, lo + 1);
  const W = 900, L = 230, R = 20, RH = 24, TOP = 22;
  const x = (v: number) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const H = TOP + steps.length * RH + 10;
  const ticks = Array.from({ length: Math.min(8, Math.round(hi - lo) + 1) }, (_, k) => lo + ((hi - lo) * k) / Math.max(1, Math.min(7, Math.round(hi - lo))));
  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Capable-to-promise chain">
        {ticks.map((v) => <g key={v}><line x1={x(v)} x2={x(v)} y1={TOP - 4} y2={H} className="gridline" />
          <text x={x(v) + 3} y={TOP - 8}>{new Date(v * 86400_000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</text></g>)}
        {steps.map((s, i) => {
          const y = TOP + i * RH + 4;
          const a = x(starts[i]), b = x(ends[i]);
          return (
            <g key={i} onMouseMove={(e) => tip.show(e, <div><b>{s.kind}</b> · {s.product} at {s.location}<div className="small">{qty(s.qty)} {s.kind === "capacity" ? "h" : "units"} · {s.note}</div>
              <div className="small">{s.start ?? "—"} → {s.end ?? "—"}</div></div>)} onMouseLeave={tip.hide}>
              <text x={8} y={y + 12}>{s.kind} · {s.product}</text>
              {b - a < 3 ? <circle cx={a} cy={y + 8} r={5} fill={STEP_COLOR[s.kind]} stroke="var(--surface)" strokeWidth={2} />
                : <rect x={a} y={y} width={b - a} height={16} rx={2} fill={STEP_COLOR[s.kind]} stroke="var(--surface)" strokeWidth={1} />}
            </g>
          );
        })}
      </svg>
      {tip.node}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
const WINDOWS: [string, number][] = [["4 weeks", 28], ["8 weeks", 56], ["Horizon", 400]];

function Atp({ res, sel }: { res: PromiseResult; sel?: string }) {
  const key = (n: AtpNode) => `${n.location}|${n.product}`;
  const cur = res.nodes.find((n) => key(n) === sel) ?? res.nodes[0];
  const [win, setWin] = useState(56);
  if (!cur) return <Panel><Empty title="No shipping locations">Sales orders need a lane from a stocking location.</Empty></Panel>;
  const n = Math.min(win, cur.dates.length);
  const labels = cur.dates.slice(0, n).map((d) => day(d).slice(0, 6));
  const moves = cur.dates.map((d, i) => ({ d, i })).filter(({ i }) => i < n && (cur.receipts[i] > 1e-6 || cur.other_demand[i] > 1e-6 || cur.promised[i] > 1e-6));
  return (
    <div className="split" style={cols("minmax(220px, 280px) minmax(0, 1fr)")}>
      <Panel flush title="Shipping locations">
        <div className="table-wrap">
          <table className="t">
            <tbody>
              {res.nodes.map((x) => (
                <tr key={key(x)} className={`clickable ${key(x) === key(cur) ? "selected" : ""}`} onClick={() => go("promise", "atp", key(x))}>
                  <td><b><Prod id={x.product} /></b><div className="faint small"><Loc id={x.location} /></div></td>
                  <td className="num">{x.shortage_date ? <Badge sev="error">short</Badge> : <span className="muted">{qty(x.available[0] ?? 0)}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="stack">
        <Panel title={`${cur.product} at ${cur.location}`} actions={<div className="row">
          {WINDOWS.map(([l, w]) => <button key={l} className={`btn sm ${win === w ? "primary" : ""}`} onClick={() => setWin(w)}>{l}</button>)}</div>}>
          <BucketChart labels={labels} height={260} series={[
            { name: "Receipts", color: "var(--series-2)", values: cur.receipts.slice(0, n), kind: "column" },
            { name: "Promised to orders", color: "var(--series-4)", values: cur.promised.slice(0, n), kind: "column" },
            { name: "Cumulative position", color: "var(--series-1)", values: cur.cumulative.slice(0, n), kind: "step" },
            { name: "Available to promise", color: "var(--series-3)", values: cur.available.slice(0, n), kind: "step", dash: true },
          ]} divider={cur.rlt_days !== null && cur.rlt_days < n ? cur.rlt_days : undefined} dividerLabel="RLT → unconditional" />
          <p className="faint small" style={{ marginBottom: 0 }}>On hand {qty(cur.on_hand)} · replenishment lead time {cur.rlt_days === null ? "not used (backorders instead)" : `${cur.rlt_days} days`}
            {cur.shortage_date && <> · <b style={{ color: "var(--critical)" }}>promises exceed supply by {qty(cur.shortage_qty)} from {day(cur.shortage_date)}</b></>}</p>
        </Panel>
        <Panel flush title="Supply and demand elements">
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="t nowrap">
              <thead><tr><th>Date</th><th className="num">Receipts</th><th className="num">MRP demand</th><th className="num">Promised</th>
                <th className="num">Cumulative</th><th className="num">ATP</th></tr></thead>
              <tbody>
                {moves.map(({ d, i }) => (
                  <tr key={d}><td>{day(d)}</td><td className="num">{cur.receipts[i] ? qty(cur.receipts[i]) : ""}</td>
                    <td className="num">{cur.other_demand[i] ? qty(cur.other_demand[i]) : ""}</td><td className="num">{cur.promised[i] ? qty(cur.promised[i]) : ""}</td>
                    <td className="num">{qty(cur.cumulative[i])}</td><td className="num">{cur.available[i] === null ? "∞" : qty(cur.available[i])}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Simulate({ ds }: { ds: Dataset }) {
  const demandLocs = useMemo(() => (ds.locations ?? []).filter((l) => ["customer", "dc", "warehouse", "store", "plant"].includes(l.type)), [ds]);
  const products = useMemo(() => (ds.products ?? []).filter((p) => p.type === "FG" || p.type === "SFG"), [ds]);
  const start = ds.settings.planning_start;
  const plus = (iso: string, n: number) => new Date(new Date(iso + "T00:00:00").getTime() + n * 86400_000).toISOString().slice(0, 10);
  const [order, setOrder] = useState<DemandRecord>({
    location: demandLocs.find((l) => l.type === "customer")?.id ?? demandLocs[0]?.id ?? "", product: products[0]?.id ?? "",
    date: plus(start, 7), qty: 500, kind: "sales_order", priority: 5, complete_delivery: false,
  } as DemandRecord);
  const [out, setOut] = useState<PromiseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (patch: Partial<DemandRecord>) => setOrder((o) => ({ ...o, ...patch }));
  const check = async () => {
    setBusy(true);
    setErr(null);
    try {
      setOut(await api.promiseCheck(ds, order));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const c = out?.checked;
  return (
    <div className="split" style={cols("minmax(260px, 340px) minmax(0, 1fr)")}>
      <Panel title="New order (simulation)">
        <div className="form">
          <label className="field"><span className="label">Customer / location</span>
            <select value={order.location} onChange={(e) => set({ location: e.target.value })}>
              {demandLocs.map((l) => <option key={l.id} value={l.id}>{l.id}{l.name ? ` — ${l.name}` : ""}</option>)}</select></label>
          <label className="field"><span className="label">Product</span>
            <select value={order.product} onChange={(e) => set({ product: e.target.value })}>
              {products.map((p) => <option key={p.id} value={p.id}>{p.id}{p.name ? ` — ${p.name}` : ""}</option>)}</select></label>
          <label className="field"><span className="label">Quantity</span>
            <input type="number" min={0} value={order.qty} onChange={(e) => set({ qty: Number(e.target.value) })} /></label>
          <label className="field"><span className="label">Requested delivery</span>
            <input type="date" value={order.date} onChange={(e) => set({ date: e.target.value })} /></label>
          <label className="field"><span className="label">Priority (1 = highest)</span>
            <input type="number" min={1} max={9} value={order.priority} onChange={(e) => set({ priority: Number(e.target.value) })} /></label>
          <label className="row small"><input type="checkbox" checked={!!order.complete_delivery} onChange={(e) => set({ complete_delivery: e.target.checked })} />Complete delivery only</label>
          <button className="btn accent" onClick={check} disabled={busy || !order.qty}>{busy ? "Checking…" : "Check availability"}</button>
        </div>
        <p className="faint small">Checked after every open order already promised (entry sequence). Nothing is saved.</p>
      </Panel>
      <div className="stack">
        {err && <div className="banner error"><Badge sev="error">Check failed</Badge>{err}</div>}
        {!c ? <Panel><Empty title="Enter an order and check it">The answer shows what can ship on the requested date, when the rest follows, and — when ATP falls short — the
          capable-to-promise chain behind a quoted date.</Empty></Panel> : <>
          <div className="grid-auto">
            <StatTile label="Answer" value={STATUS[c.status][1]} sub={`${qty(c.on_time)} on ${day(c.requested)}`} tone={c.status === "on_time" ? undefined : "hl"} />
            <StatTile label="Confirmed" value={qty(c.confirmed)} sub={c.unconfirmed > 1e-6 ? `${qty(c.unconfirmed)} cannot be promised` : "full quantity"} />
            <StatTile label="Last delivery" value={c.lines.length ? day(c.lines[c.lines.length - 1].date) : "—"} sub={c.lines.length > 1 ? `${c.lines.length} schedule lines` : "one line"} />
            {c.allocation_capped > 0 && <StatTile label="Allocation withheld" value={qty(c.allocation_capped)} sub="on the requested date" />}
          </div>
          <OrderCard o={c} currency={out!.currency} />
        </>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Bop({ ds, busy, onCommit }: { ds: Dataset; busy: boolean; onCommit: () => void }) {
  const rev = useStore((s) => s.revision);
  const [, force] = useState(0);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cur = bopRun && bopRun.rev === rev ? bopRun.res : null;
  const segs = ds.promising?.bop_segments ?? [];
  const simulate = async () => {
    setRunning(true);
    setErr(null);
    try {
      bopRun = { rev, res: await api.bop(ds) };
      force((x) => x + 1);
    } catch (e) {
      setErr(String(e));
    } finally {
      setRunning(false);
    }
  };
  const out: Record<string, Severity | undefined> = { gained: "ok", lost: "error", changed: "info", unchanged: undefined };
  return (
    <div className="stack">
      <SolverIO answers="Who keeps, gains or loses confirmation when supply no longer covers every promise."
        from="Committed confirmations, the current supply picture, and the segment sequence with a strategy each."
        feeds="New confirmations (on commit) and the list of customers to call." />
      <Panel title="Segment cascade — processed top to bottom, earlier segments claim supply first" actions={
        <div className="row"><a className="btn sm ghost" href={href("promise", "settings")}>Edit segments</a>
          <button className="btn sm accent" onClick={simulate} disabled={running}>{running ? "Working…" : "Re-decide who gets scarce stock"}</button></div>}>
        <div className="row wrap">
          <span className="chip">orders no segment selects · keep their confirmations</span>
          {segs.map((s, i) => (
            <span key={i} className="chip"><b>{i + 1}. {s.name}</b>&nbsp;
              <span className="faint">{s.priorities?.length ? `prio ${s.priorities.join(",")}` : "any prio"}{s.customers?.length ? ` · ${s.customers.join(",")}` : ""}</span>
              &nbsp;<Badge sev={s.strategy === "win" || s.strategy === "gain" ? "ok" : s.strategy === "lose" ? "error" : "info"}>{s.strategy}</Badge></span>
          ))}
        </div>
      </Panel>
      {err && <div className="banner error"><Badge sev="error">BOP failed</Badge>{err}</div>}
      {!cur ? <Panel><Empty title="No simulation yet">Simulate to see each order's confirmation before and after, then commit if the result is right.</Empty></Panel> : <>
        <div className="grid-auto">
          <StatTile label="Gained" value={qty(cur.bop.filter((b) => b.outcome === "gained").length)} sub="orders" />
          <StatTile label="Lost" value={qty(cur.bop.filter((b) => b.outcome === "lost").length)} sub="orders to call" />
          <StatTile label="On time after BOP" value={`${cur.kpis.on_time_orders} / ${cur.kpis.orders}`} sub={pct(cur.kpis.qty ? cur.kpis.on_time_qty / cur.kpis.qty : 1)} />
        </div>
        <Panel flush title="Gain / loss log" actions={<button className="btn sm accent" onClick={onCommit} disabled={busy} title="Saves the new promised dates on the orders in your data. Undo reverts it.">Save these new promised dates</button>}>
          <div className="table-wrap" style={{ maxHeight: 520 }}>
            <table className="t nowrap">
              <thead><tr><th>Order</th><th>Customer</th><th>Product</th><th className="num">Prio</th><th>Segment</th><th>Strategy</th>
                <th className="num">On time before → after</th><th className="num">Confirmed before → after</th><th>Outcome</th></tr></thead>
              <tbody>
                {cur.bop.map((b) => (
                  <tr key={b.order} className="clickable" onClick={() => go("promise", "orders", b.order)}>
                    <td><b>{b.order}</b></td><td><Loc id={b.location} /></td><td><Prod id={b.product} /></td><td className="num">{b.priority}</td>
                    <td>{b.segment ?? <span className="faint">—</span>}</td><td>{b.strategy ?? <span className="faint">keep</span>}</td>
                    <td className="num">{qty(b.before_on_time)} → <b>{qty(b.after_on_time)}</b></td>
                    <td className="num">{qty(b.before_confirmed)} → <b>{qty(b.after_confirmed)}</b></td>
                    <td>{out[b.outcome] ? <Badge sev={out[b.outcome]}>{b.outcome}</Badge> : <span className="muted">{b.outcome}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </>}
      <Reading formula="Win and Gain may not lose (a re-check that comes out worse is rolled back to the old lines); Fill keeps its lines and tops up; Redistribute re-plans from scratch; Lose may keep at most what it had."
        soWhat="Design the cascade as commercial policy: who is protected, who is topped up, who is re-planned, who gives supply back. Simulate, read the log, then commit." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Allocations({ res }: { res: PromiseResult }) {
  if (!res.allocations.length) {
    return <Panel><Empty title="No product allocations">Add allocations under <a href={href("data", "allocations")}>Allocations</a> to cap what a product or customer group can be promised per period.</Empty></Panel>;
  }
  return (
    <div className="stack">
      <Panel flush title="Allocation consumption">
        <table className="t nowrap">
          <thead><tr><th>Allocation</th><th>Product</th><th>Customers</th><th>Period</th><th style={{ width: 240 }}>Used</th><th className="num">Left</th><th>When used up</th></tr></thead>
          <tbody>
            {res.allocations.map((a) => (
              <tr key={a.id}>
                <td><b>{a.id}</b></td><td><Prod id={a.product} /></td><td>{a.customers.join(", ") || "all"}</td><td>{day(a.start)} – {day(a.end)}</td>
                <td><div className="row"><div className="bar-track" style={{ flex: 1, minWidth: 90 }}><div className="bar-fill" style={{ width: `${Math.min(100, (a.used / Math.max(a.qty, 1e-9)) * 100)}%`,
                  background: a.used >= a.qty - 1e-6 ? "var(--warning)" : "var(--series-1)" }} /></div><span className="num small">{qty(a.used)} / {qty(a.qty)}</span></div></td>
                <td className="num">{qty(Math.max(0, a.qty - a.used))}</td><td>{a.fallback === "next_period" ? "next period" : "reject the rest"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Reading formula="Confirmable = min(ATP, allocation left in the period of the ship date). Once a product-customer has allocations, a date outside every period has none."
        soWhat="Use allocations for launches and scarce supply to share fairly across channels; the S&OP constrained plan is a natural source for the quantities." />
    </div>
  );
}

function SettingsView({ ds }: { ds: Dataset }) {
  const schemaErrors = useStore((s) => s.schemaErrors);
  const errors: Record<string, string> = {};
  for (const e of schemaErrors) {
    const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
    if (loc[0] === "promising") errors[loc.slice(1).join(".")] = e.msg;
  }
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Checking rules and BOP segments">
        <SchemaForm defName="PromiseSettings" value={(ds.promising ?? {}) as unknown as Obj} errors={errors}
          onChange={(next) => store.update((d) => { d.promising = next as unknown as Dataset["promising"]; })} />
      </Panel>
      <Reading formula="Scope of check: stock + firm receipts (+ MRP planned receipts and their dependent demand). RLT = total replenishment lead time along the primary sources; beyond it confirmation is unconditional unless turned off."
        soWhat="Turn planned receipts off for a strict ‘physical supply only’ promise; turn RLT off to see true backorders instead of paper confirmations." />
    </div>
  );
}
