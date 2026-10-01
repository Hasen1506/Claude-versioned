import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { AtpNode, CtpStep, Dataset, DemandRecord, OrderPromise, PromiseResult, ScheduleLine } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, cols, Edits, Empty, Panel, Provenance, Reading, RunButton, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, Term, type Severity, useTooltip,
} from "../components/ui";
import { day, money, pct, plural, qty, unitMoney } from "../lib/format";
import { Loc, Prod, namesOf, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useFreshResult, useStore } from "../state/store";

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
  useFreshResult("promise");
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "promise"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const view = ((route[1] as View) || "orders") as View;
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const commitPromises = async (mode: "entry" | "bop") => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.promiseCommit(ds, mode);
      store.replace(out.dataset, ds);
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
        ship in full on the date asked.{res.kpis.unconfirmed_qty > 0.5 && <> {qty(Math.round(res.kpis.unconfirmed_qty))} units{res.kpis.value_unconfirmed > 0.5 && !res.kpis.unpriced_unconfirmed
          ? <> worth {money(res.kpis.value_unconfirmed, res.currency)}</> : null} can't be confirmed yet.</>}
        {res.kpis.at_risk_orders > 0 && <> {plural(res.kpis.at_risk_orders, "earlier promise")} {res.kpis.at_risk_orders === 1 ? "is" : "are"} now at risk.</>}</> : <>There are no open customer orders.</>)}
      right={<>
      {res && <Provenance kind="solved" at={run.at} stale={stale} />}
      {res?.ok && <Edits><button className="btn" onClick={() => commitPromises("entry")} disabled={busy || stale}
        title={stale ? "Recalculate first" : "Saves every promised date and quantity on the orders in your data, so later checks keep them. Undo reverts it."}>Save these promised dates</button></Edits>}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("promise")} disabled={blocking} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const banners = <>
    {note && <div className="banner info"><Badge sev="ok">Committed</Badge><span>{note}</span><span className="spacer" />
      <a className="btn sm" href={href("data", "confirmations")}>View confirmations</a>
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setNote(null)}>✕</button></div>}
    {err && <div className="banner error"><Badge sev="error">Commit failed</Badge>{err}</div>}
    {done && <div className="banner info" role="status"><Badge sev="ok">Saved</Badge><span>{done}</span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setDone(null)}>✕</button></div>}
  </>;
  if (view === "settings") return body(<><Nav view={view} res={res} /><SettingsView ds={ds} /></>);
  if (view === "simulate") return body(<><Nav view={view} res={res} /><Simulate ds={ds} onDone={setDone} /></>);
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
    {view === "orders" && <Orders res={res} sel={route[2]} ds={ds} onDone={setDone} />}
    {view === "atp" && <Atp res={res} sel={route[2]} />}
    {view === "allocations" && <Allocations res={res} />}
  </>);
}

function Nav({ view, res }: { view: View; res: PromiseResult | null }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("promise", v)} tabs={[
      { id: "orders", label: "Sales orders", count: res?.orders.length },
      { id: "atp", label: "ATP picture", count: res?.nodes.length },
      { id: "simulate", label: "New order" },
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
      <StatTile label="Unconfirmed" value={qty(k.unconfirmed_qty)} sub={k.unpriced_unconfirmed && !k.value_unconfirmed ? "units on backorder (no prices set)"
        : `${money(k.value_unconfirmed, res.currency)} of sales on backorder${k.unpriced_unconfirmed ? `, plus ${plural(k.unpriced_unconfirmed, "order")} without a price` : ""}`} />
      <StatTile label="Beyond RLT" value={qty(k.rlt_lines)} sub="lines confirmed without supply behind them" />
      <StatTile label="Capable-to-promise" value={qty(k.ctp_lines)} sub="lines quoted on new supply" />
      <StatTile label="Alternative location" value={qty(k.alternative_lines)} sub="lines shipped from a second choice" />
    </div>
  );
}

function Orders({ res, sel, ds, onDone }: { res: PromiseResult; sel?: string; ds: Dataset; onDone: (m: string) => void }) {
  const n = useNames();
  const [filter, setFilter] = useState<"all" | "issues">("all");
  const rows = res.orders.filter((o) => filter === "all" || o.status !== "on_time" || o.at_risk);
  const cur = res.orders.find((o) => o.order === sel);
  return (
    <div className="stack">
      <Kpis res={res} />
      <Panel flush title="Open sales orders in entry sequence" actions={
        <div className="row">
          <a className="btn sm accent" href={href("promise", "simulate")}>New order</a>
          <button className={`btn sm ${filter === "all" ? "primary" : ""}`} onClick={() => setFilter("all")}>All</button>
          <button className={`btn sm ${filter === "issues" ? "primary" : ""}`} onClick={() => setFilter("issues")}>Not on time</button>
        </div>}>
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="t">
            <thead><tr><th>Order</th><th>Customer</th><th>Product</th><th className="num">Prio</th><th className="num">Qty</th><th>Requested</th>
              <th>Status</th><th>Schedule lines</th><th className="num">Value</th></tr></thead>
            <tbody>
              {rows.map((o) => {
                const [sev, label] = STATUS[o.status];
                return (
                  <tr key={o.order} className={`clickable ${o.order === sel ? "selected" : ""}`} onClick={() => go("promise", "orders", o.order === sel ? undefined : o.order)}>
                    <td><b>{o.order}</b>{refOf(ds, o.order) && <div className="faint small">{refOf(ds, o.order)}</div>}
                      {o.complete_delivery && <div className="faint small">complete delivery</div>}</td>
                    <td title={o.location}>{n.loc(o.location)}</td><td title={o.product}>{n.prod(o.product)}</td><td className="num">{o.priority}</td><td className="num">{qty(o.qty)}</td>
                    <td>{day(o.requested)}</td>
                    <td><Badge sev={sev}>{label}</Badge> {o.at_risk && <Badge sev="error">at risk</Badge>}
                      {CHANGE[o.change] && o.change !== "new" && <> <Badge sev={CHANGE[o.change]}>{o.change}</Badge></>}</td>
                    <td><div className="chips">{o.lines.map((l, i) => <LineChip key={i} l={l} />)}
                      {o.unconfirmed > 1e-6 && <span className="chip" style={{ borderColor: "var(--critical)" }}><b>{qty(o.unconfirmed)}</b>&nbsp;open</span>}</div></td>
                    <td className="num">{o.value === null || o.value === undefined ? <span className="faint">no price</span> : money(o.value, res.currency)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      {sel && !cur && <Panel><Empty title={`${sel} is not open`}>It was delivered or cancelled: see <a href={href("execution", "orders")}>Actuals → orders</a>.</Empty></Panel>}
      {cur && <OrderCard o={cur} currency={res.currency} actions={<OrderActions o={cur} ds={ds} currency={res.currency} onDone={onDone} />} />}
      <Reading formula="ATP(d) = min over later days e of [Σ receipts(≤ e) − Σ outflows(≤ e)] — the look-ahead keeps a new promise from taking stock an earlier promise needs later. Beyond the replenishment lead time everything is confirmable."
        soWhat="Commit promises to persist the schedule lines; after that, every check (and MRP's supply changes) is measured against them, and backorder processing decides who gives way in a shortage." />
    </div>
  );
}

function OrderCard({ o, currency, actions }: { o: OrderPromise; currency: string; actions?: React.ReactNode }) {
  const n = useNames();
  return (
    <Panel title={`${o.order}: ${qty(o.qty)} ${n.prod(o.product)} for ${n.loc(o.location)}, asked for ${day(o.requested)}`}
      actions={actions ? <button className="btn sm ghost" onClick={() => go("promise", "orders")}>Close</button> : undefined}>
      {actions}
      <div className="grid-auto" style={{ marginBottom: 12 }}>
        <StatTile label="On time" value={qty(o.on_time)} sub={pct(o.qty ? o.on_time / o.qty : 0)} />
        <StatTile label="Confirmed" value={qty(o.confirmed)} sub={o.unconfirmed > 1e-6 ? `${qty(o.unconfirmed)} open` : "complete"} />
        <StatTile label="Order value" value={o.value === null || o.value === undefined ? "—" : money(o.value, currency)}
          sub={o.price === null || o.price === undefined ? `no selling price · priority ${o.priority}` : `${unitMoney(o.price, currency)} a unit · priority ${o.priority}`} />
        {o.allocation_capped > 0 && <StatTile label="Held back by allocation" value={qty(o.allocation_capped)} sub="on the requested date" />}
      </div>
      {o.reason && <div className="banner warning"><Badge sev="warning">Why not</Badge>{o.reason}</div>}
      {o.at_risk && <div className="banner error"><Badge sev="error">At risk</Badge>Supply no longer covers this confirmation: run backorder processing to re-promise it.</div>}
      <table className="t nowrap">
        <thead><tr><th>Ships from</th><th>Ship date</th><th>Delivery</th><th className="num">Qty</th><th>Method</th><th>On time</th></tr></thead>
        <tbody>
          {o.lines.map((l, i) => (
            <tr key={i}><td><Loc id={l.ship_from} /></td><td>{day(l.ship_date)}</td><td>{day(l.date)}</td><td className="num">{qty(l.qty)}</td>
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
  const nm = useNames();
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
        <Panel title={`${nm.prod(cur.product)} at ${nm.loc(cur.location)}`} actions={<div className="row">
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
/** The customer's own order number on a sales order, if any. */
function refOf(ds: Dataset, id: string): string {
  return ds.demand?.find((d) => d.id === id && d.kind === "sales_order")?.customer_ref ?? "";
}

/** Places an order can come from: customers first, then places that sell directly. */
function orderPlaces(ds: Dataset) {
  const order = ["customer", "store", "dc", "warehouse", "plant"];
  return (ds.locations ?? []).filter((l) => order.includes(l.type)).sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type));
}

const TYPE_WORD: Record<string, string> = { customer: "", store: "store", dc: "distribution centre", warehouse: "warehouse", plant: "plant" };

/** Stocking places a delivery can leave from. */
function shipPlaces(ds: Dataset) {
  return (ds.locations ?? []).filter((l) => ["plant", "dc", "warehouse", "store"].includes(l.type));
}

function listPrice(ds: Dataset, location: string, product: string): number | null {
  const cp = (ds.customer_prices ?? []).find((c) => c.customer === location && c.product === product);
  if (cp) return cp.price;
  return ds.products?.find((p) => p.id === product)?.price ?? null;
}

function OrderActions({ o, ds, currency, onDone }: { o: OrderPromise; ds: Dataset; currency: string; onDone: (m: string) => void }) {
  const rec = ds.demand?.find((d) => d.id === o.order && d.kind === "sales_order");
  const n = useNames();
  const [mode, setMode] = useState<null | "change" | "deliver" | "cancel">(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const done = (ds.movements ?? []).filter((m) => m.type === "sale" && m.reference === o.order).reduce((a, m) => a + m.qty, 0);
  const ordered = rec ? rec.ordered_qty ?? rec.qty : o.qty;
  const open = Math.max(0, ordered - done);
  const list = listPrice(ds, o.location, o.product);
  const [ch, setCh] = useState({ qty: ordered, date: rec?.date ?? o.requested, priority: rec?.priority ?? o.priority,
    price: rec?.price ?? null as number | null, complete_delivery: !!rec?.complete_delivery, customer_ref: rec?.customer_ref ?? "" });
  const [dl, setDl] = useState({ qty: open, date: ds.settings.planning_start, final: false, from: o.lines[0]?.ship_from ?? "" });
  const [reason, setReason] = useState("");
  if (!rec) return null;
  const act = async (f: () => Promise<{ dataset: Dataset; report: { message: string } }>) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await f();
      store.replace(out.dataset, ds);
      onDone(namesOf(out.dataset).text(out.report.message));
      setMode(null);
      void store.run("promise");
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };
  const tab = (m: typeof mode, label: string) => (
    <Edits><button className={`btn sm ${mode === m ? "primary" : ""}`} aria-pressed={mode === m} onClick={() => { setErr(null); setMode(mode === m ? null : m); }}>{label}</button></Edits>);
  return (
    <div className="stack" style={{ marginBottom: 12 }}>
      <div className="row wrap">
        {tab("deliver", "Deliver")}{tab("change", "Change")}{tab("cancel", "Cancel")}
        <span className="faint small">{done > 0 ? `${qty(done)} of ${qty(ordered)} delivered · ` : ""}{rec.customer_ref ? `customer's number ${rec.customer_ref}` : ""}</span>
      </div>
      {mode === "deliver" && <div className="qrow" role="group" aria-label="Deliver">
        <label className="qf"><span className="qf-l">Quantity</span>
          <input className="input num" type="number" min={0} step="any" value={dl.qty} onChange={(e) => setDl({ ...dl, qty: Number(e.target.value) })} aria-label="Quantity to deliver" />
          <span className="qf-h">{qty(open)} still open</span></label>
        <label className="qf"><span className="qf-l">Ships from</span>
          <select className="select" value={dl.from} onChange={(e) => setDl({ ...dl, from: e.target.value })} aria-label="Ships from">
            <option value="">{o.lines[0] ? `Where it was promised (${n.loc(o.lines[0].ship_from)})` : "The customer's first route"}</option>
            {shipPlaces(ds).map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></label>
        <label className="qf"><span className="qf-l">Goods leave on</span>
          <input className="input" type="date" value={dl.date} onChange={(e) => setDl({ ...dl, date: e.target.value })} aria-label="Delivery date" /></label>
        <label className="row small"><input type="checkbox" checked={dl.final} onChange={(e) => setDl({ ...dl, final: e.target.checked })} />Last delivery (close the rest)</label>
        <button className="btn accent" disabled={busy || !(dl.qty > 0)} onClick={() => act(() => api.postActual(ds, "deliver",
          { order: o.order, qty: dl.qty, date: dl.date, final: dl.final, ship_from: dl.from || null }))}>Post the delivery</button>
      </div>}
      {mode === "change" && <div className="qrow" role="group" aria-label="Change the order">
        <label className="qf"><span className="qf-l">Ordered</span>
          <input className="input num" type="number" min={0} step="any" value={ch.qty} onChange={(e) => setCh({ ...ch, qty: Number(e.target.value) })} aria-label="Ordered quantity" />
          {done > 0 && <span className="qf-h">{qty(done)} already delivered</span>}</label>
        <label className="qf"><span className="qf-l">Wanted on</span>
          <input className="input" type="date" value={ch.date} onChange={(e) => setCh({ ...ch, date: e.target.value })} aria-label="Wanted on" /></label>
        <label className="qf"><span className="qf-l">Priority</span>
          <input className="input num" type="number" min={1} max={9} value={ch.priority} style={{ width: 70 }} onChange={(e) => setCh({ ...ch, priority: Number(e.target.value) })} aria-label="Priority" />
          <span className="qf-h">1 = first</span></label>
        <label className="qf"><span className="qf-l">Price a unit</span>
          <input className="input num" type="number" min={0} step="any" value={ch.price ?? ""} placeholder={list !== null ? String(list) : "no price"}
            onChange={(e) => setCh({ ...ch, price: e.target.value === "" ? null : Number(e.target.value) })} aria-label="Price a unit" />
          <span className="qf-h">{list !== null ? `empty = price list, ${unitMoney(list, currency)}` : "no price list for this customer"}</span></label>
        <label className="qf"><span className="qf-l">Customer's number</span>
          <input className="input" value={ch.customer_ref} maxLength={64} onChange={(e) => setCh({ ...ch, customer_ref: e.target.value })} aria-label="Customer's order number" /></label>
        <label className="row small"><input type="checkbox" checked={ch.complete_delivery} onChange={(e) => setCh({ ...ch, complete_delivery: e.target.checked })} />Complete delivery only</label>
        <button className="btn accent" disabled={busy || !(ch.qty > 0)} onClick={() => act(() => api.salesOrder(ds, "change", { id: o.order, changes: ch }))}>Save and promise again</button>
      </div>}
      {mode === "cancel" && <div className="qrow" role="group" aria-label="Cancel the order">
        <label className="qf" style={{ flex: 1 }}><span className="qf-l">Why (optional)</span>
          <input className="input" value={reason} maxLength={120} onChange={(e) => setReason(e.target.value)} placeholder="e.g. customer changed their mind" aria-label="Why" /></label>
        <button className="btn danger" disabled={busy} onClick={() => act(() => api.salesOrder(ds, "cancel", { id: o.order, reason }))}>
          {done > 0 ? `Cancel the ${qty(open)} still open` : "Cancel the order"}</button>
        <span className="faint small">{done > 0 ? "What was delivered stays on the order's record." : "Its promised stock goes back to other orders."} Undo reverses it.</span>
      </div>}
      {err && <div className="banner error"><Badge sev="error">Not saved</Badge>{err}</div>}
    </div>
  );
}

function Simulate({ ds, onDone }: { ds: Dataset; onDone: (m: string) => void }) {
  const places = useMemo(() => orderPlaces(ds), [ds]);
  const products = useMemo(() => (ds.products ?? []).filter((p) => p.type === "FG" || p.type === "SFG"), [ds]);
  const start = ds.settings.planning_start;
  const plus = (iso: string, n: number) => new Date(new Date(iso + "T00:00:00").getTime() + n * 86400_000).toISOString().slice(0, 10);
  const [order, setOrder] = useState<DemandRecord>({
    location: places[0]?.id ?? "", product: products[0]?.id ?? "",
    date: plus(start, 7), qty: 100, kind: "sales_order", priority: 5, complete_delivery: false, price: null, customer_ref: "",
  } as DemandRecord);
  const [out, setOut] = useState<PromiseResult | null>(null);
  const [checked, setChecked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (patch: Partial<DemandRecord>) => setOrder((o) => ({ ...o, ...patch }));
  const key = JSON.stringify(order);
  const list = listPrice(ds, order.location, order.product);
  const nm = useNames();
  const ref = (order.customer_ref ?? "").trim();
  const twin = ref ? ds.demand?.find((d) => d.kind === "sales_order" && d.location === order.location && d.customer_ref === ref) : undefined;
  const check = async () => {
    setBusy(true);
    setErr(null);
    try {
      setOut(await api.promiseCheck(ds, order));
      setChecked(key);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const take = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.salesOrder(ds, "accept", { order });
      store.replace(r.dataset, ds);
      onDone(namesOf(r.dataset).text(r.report.message));
      go("promise", "orders", r.report.order);
      void store.run("promise");
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };
  const c = out?.checked;
  const fresh = !!c && checked === key;
  return (
    <div className="split" style={cols("minmax(260px, 340px) minmax(0, 1fr)")}>
      <Panel title="New order">
        <div className="form">
          <label className="field"><span className="label">Customer</span>
            <select value={order.location} onChange={(e) => set({ location: e.target.value })} aria-label="Customer">
              {places.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}{TYPE_WORD[l.type] ? ` (${TYPE_WORD[l.type]})` : ""}</option>)}</select></label>
          <label className="field"><span className="label">Product</span>
            <select value={order.product} onChange={(e) => set({ product: e.target.value })} aria-label="Product">
              {products.map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}</select></label>
          <label className="field"><span className="label">Quantity</span>
            <input type="number" min={0} value={order.qty} onChange={(e) => set({ qty: Number(e.target.value) })} aria-label="Quantity" /></label>
          <label className="field"><span className="label">Wanted on</span>
            <input type="date" value={order.date} onChange={(e) => set({ date: e.target.value })} aria-label="Wanted on" /></label>
          <label className="field"><span className="label">Price a unit</span>
            <input type="number" min={0} step="any" value={order.price ?? ""} placeholder={list !== null ? `${list} (price list)` : "no price"}
              onChange={(e) => set({ price: e.target.value === "" ? null : Number(e.target.value) })} aria-label="Price a unit" /></label>
          <label className="field"><span className="label">Customer's order number</span>
            <input value={order.customer_ref ?? ""} maxLength={64} onChange={(e) => set({ customer_ref: e.target.value })} aria-label="Customer's order number" /></label>
          {twin && <p className="small" role="status" style={{ color: "var(--warning-text)", margin: 0 }}>Already taken as {twin.id}: {qty(twin.qty)} {nm.prod(twin.product)} for {day(twin.date)}.
            Taking it again makes a second order.</p>}
          <label className="field"><span className="label">Priority (1 = first)</span>
            <input type="number" min={1} max={9} value={order.priority} onChange={(e) => set({ priority: Number(e.target.value) })} aria-label="Priority" /></label>
          <label className="row small"><input type="checkbox" checked={!!order.complete_delivery} onChange={(e) => set({ complete_delivery: e.target.checked })} />Complete delivery only</label>
          <div className="row wrap">
            <button className="btn" onClick={check} disabled={busy || !order.qty || !order.location || !order.product}>{busy && !fresh ? "Checking…" : "Check availability"}</button>
            <Edits><button className="btn accent" onClick={take} disabled={busy || !fresh} title={fresh ? "Save it as a sales order with this promise" : "Check it first"}>Take this order</button></Edits>
          </div>
        </div>
        <p className="faint small">Checking saves nothing: it comes after every order already promised. <b>Take this order</b> saves it as a
          sales order with the promise shown, so later orders can't take its stock.</p>
      </Panel>
      <div className="stack">
        {err && <div className="banner error"><Badge sev="error">Not taken</Badge>{err}</div>}
        {!c ? <Panel><Empty title="Enter an order and check it">The answer shows what can ship on the date asked, when the rest follows, and — when stock falls short — how
          new supply would get there in time.</Empty></Panel> : <>
          {!fresh && <div className="banner warning"><Badge sev="warning">Changed</Badge>The order changed since it was checked: check it again before taking it.</div>}
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
      {!cur ? <Panel><Empty title="Nothing re-decided yet"><i>Re-decide who gets scarce stock</i> shows each order's promise before and after; nothing is saved until you press <i>Save these new promised dates</i>.</Empty></Panel> : <>
        <div className="grid-auto">
          <StatTile label="Gained" value={qty(cur.bop.filter((b) => b.outcome === "gained").length)} sub="orders" />
          <StatTile label="Lost" value={qty(cur.bop.filter((b) => b.outcome === "lost").length)} sub="orders to call" />
          <StatTile label="On time after BOP" value={`${cur.kpis.on_time_orders} / ${cur.kpis.orders}`} sub={pct(cur.kpis.qty ? cur.kpis.on_time_qty / cur.kpis.qty : 1)} />
        </div>
        <Panel flush title="Gain / loss log" actions={<Edits><button className="btn sm accent" onClick={onCommit} disabled={busy} title="Saves the new promised dates on the orders in your data. Undo reverts it.">Save these new promised dates</button></Edits>}>
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
        soWhat="Design the cascade as commercial policy: who is protected, who is topped up, who is re-planned, who gives supply back. Re-decide, read the log, then save the new promised dates." />
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
