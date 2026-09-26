import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { AccuracySeries, ActualsView, Dataset, GoodsMovement, OpenOrderRow, PlannedOrder, RollReport, StockRow } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, RunButton, Term,
} from "../components/ui";
import { day, pct, plural, qty } from "../lib/format";
import { Loc, Prod } from "../lib/names";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "stock" | "orders" | "journal" | "roll" | "accuracy";

// The last roll-forward report, kept across tab switches (the roll itself is an undoable dataset edit).
let lastRoll: RollReport | null = null;

const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

const INFLOW = new Set(["opening", "receipt"]);

function nextMovementId(ds: Dataset): string {
  let n = 0;
  for (const m of ds.movements ?? []) {
    const x = /^GM-(\d+)$/.exec(m.id);
    if (x) n = Math.max(n, Number(x[1]));
  }
  return `GM-${String(n + 1).padStart(5, "0")}`;
}

function post(m: Omit<GoodsMovement, "id">) {
  store.update((d) => {
    d.movements = [...(d.movements ?? []), { ...m, id: nextMovementId(d) } as GoodsMovement];
  });
}

export function Execution({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.actuals);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "actuals"));
  const view = ((route[1] as View) || "stock") as View;
  const start = ds.settings.planning_start;

  const head = (
    <StageHeader title="Actuals" kicker="What actually happened: goods received, used and shipped, stock on hand, and how the forecast compared with real sales."
      how={<>Every goods movement (receipts, issues, deliveries, scrap, counts) is added up into stock; firm orders are received and
        closed as their goods arrive; past forecast is measured against actual sales. Moving the plan to a new start date recomputes
        all of it from the full journal. Planned orders inside the <Term t="Firm zone">firm zone</Term> can be turned into firm orders.</>}
      answer={res && actualsAnswer(res)}
      right={<>
      {res && <Provenance kind="derived" at={run.at} stale={stale} />}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("actuals")} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const nav = <Nav view={view} res={res} ds={ds} />;
  if (view === "journal") return body(<>{nav}<Journal ds={ds} /></>);
  if (view === "roll") return body(<>{nav}<Roll ds={ds} /></>);
  if (run.error) return body(<div className="banner error"><Badge sev="error">Could not read the journal</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="On-hand per node as the sum of goods movements, open and in-transit quantities of every firm order, forecast accuracy and bias per series."
        from="The goods-movement journal, firm receipts with their reservations, open sales orders, the accuracy log."
        feeds="The next planning run: rolled-forward stock, receipts and orders, sales history for the forecast, and the control tower's KPIs." />
      <div style={{ height: 14 }} />
      <Panel><Empty title="Journal not read yet">
        <p>{ds.movements?.length ?? 0} goods movements are posted. Planning starts {day(start)}.</p>
      </Empty></Panel></>);
  }
  return body(<>
    {stale && <StaleMark what="journal view" onRerun={() => store.run("actuals")} busy={run.running} />}
    {nav}
    {view === "stock" && <Stock res={res} ds={ds} />}
    {view === "orders" && <Orders res={res} ds={ds} />}
    {view === "accuracy" && <Accuracy res={res} sel={route[2]} />}
  </>);
}

function Nav({ view, res, ds }: { view: View; res: ActualsView | null; ds: Dataset }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("execution", v)} tabs={[
      { id: "stock", label: "Stock from movements", count: res?.stock.length },
      { id: "orders", label: "Open orders & firming", count: res?.open_orders.length },
      { id: "journal", label: "Movement journal", count: ds.movements?.length ?? 0 },
      { id: "roll", label: "Start a new week" },
      { id: "accuracy", label: "Forecast accuracy", count: res?.accuracy.series.length },
    ]} />
  );
}

// ------------------------------------------------------------------------------------------------
function actualsAnswer(res: ActualsView) {
  const off = res.stock.filter((r) => Math.abs(r.difference) > 1e-6).length;
  const neg = res.stock.filter((r) => r.negative_on).length;
  const acc = res.accuracy && res.accuracy.periods > 0 ? res.accuracy.accuracy : null;
  const books = !res.movements ? "No goods movements are recorded yet."
    : off || neg ? `${plural(res.movements, "goods movement")} recorded up to ${day(res.as_of)}; ${[off && `${plural(off, "place")} ${off === 1 ? "has" : "have"} stock that doesn't match them`, neg && `${plural(neg, "place")} would go negative`].filter(Boolean).join(" and ")}.`
    : `${plural(res.movements, "goods movement")} recorded up to ${day(res.as_of)}, and stock matches them everywhere.`;
  return <>{books}{acc !== null && <> The forecast was {pct(acc, 0)} accurate against real sales.</>}</>;
}

function Stock({ res, ds }: { res: ActualsView; ds: Dataset }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const off = res.stock.filter((r) => Math.abs(r.difference) > 1e-6);
  const neg = res.stock.filter((r) => r.negative_on);
  const sync = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.roll(ds, ds.settings.planning_start);
      lastRoll = out.report;
      store.replace(out.dataset);
      await store.run("actuals");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Movements" value={qty(res.movements)} sub={`${qty(res.stock.reduce((a, r) => a + r.movements, 0))} before ${day(res.as_of)} are in stock`} />
        <StatTile label="Nodes in the journal" value={qty(res.stock.filter((r) => r.movements > 0).length)} sub={`of ${res.stock.length} holding stock`} />
        <StatTile label="Out of sync" value={qty(off.length)} sub="on-hand ≠ Σ movements" tone={off.length ? "hl" : undefined} />
        <StatTile label="Negative stock" value={qty(neg.length)} sub="a receipt missing or late" />
        <StatTile label="Unmatched references" value={qty(res.unmatched.length)} sub="no open or closed order" />
      </div>
      {err && <div className="banner error"><Badge sev="error">Sync failed</Badge>{err}</div>}
      {off.length > 0 && (
        <div className="banner warning"><Badge sev="warning">{off.length} nodes out of sync</Badge>
          <span>On-hand in the planning policies differs from the journal. Syncing adopts the journal without moving the planning start.</span>
          <span className="spacer" /><button className="btn sm" onClick={sync} disabled={busy}>{busy ? "Syncing…" : "Sync stock from journal"}</button></div>
      )}
      <Panel flush title="On-hand reconciliation">
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="t">
            <thead><tr><th>Location</th><th>Product</th><th className="num">Planning on-hand</th><th className="num">Σ movements</th>
              <th className="num">Difference</th><th>In / out</th><th className="num">Movements</th><th>Last</th></tr></thead>
            <tbody>
              {res.stock.map((r) => <StockLine key={`${r.location}|${r.product}`} r={r} />)}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="on-hand(node) = Σ signed movements dated before the planning start: + opening, receipt; − issue, sale, transfer issue, scrap; ± count adjustment."
        soWhat="Stock is never typed in once a node has movements. Post what happened, then roll forward: the plan starts from the physical truth." />
    </div>
  );
}

function StockLine({ r }: { r: StockRow }) {
  const inflow = Object.entries(r.by_type).filter(([t]) => INFLOW.has(t)).reduce((a, [, v]) => a + v, 0) + Math.max(0, r.by_type.adjustment ?? 0);
  const outflow = -Object.entries(r.by_type).filter(([t]) => !INFLOW.has(t) && t !== "adjustment").reduce((a, [, v]) => a + v, 0) + Math.max(0, -(r.by_type.adjustment ?? 0));
  const scale = Math.max(inflow, outflow, 1);
  return (
    <tr>
      <td><Loc id={r.location} /></td><td><Prod id={r.product} /></td><td className="num">{qty(r.master_on_hand)}</td>
      <td className="num">{r.movement_stock === null ? <span className="faint">—</span> : qty(r.movement_stock)}</td>
      <td className="num">{Math.abs(r.difference) > 1e-6 ? <Badge sev="warning">{r.difference > 0 ? "+" : ""}{qty(r.difference)}</Badge> : <span className="faint">0</span>}
        {r.negative_on && <> <Badge sev="error">negative {day(r.negative_on)}</Badge></>}</td>
      <td style={{ minWidth: 140 }} title={Object.entries(r.by_type).map(([t, v]) => `${t}: ${qty(v)}`).join(" · ")}>
        {r.movements > 0 && <div className="flowbar">
          <span style={{ width: `${(inflow / scale) * 100}%`, background: "var(--series-1)" }} />
          <span style={{ width: `${(outflow / scale) * 100}%`, background: "var(--series-2)" }} />
        </div>}
      </td>
      <td className="num">{r.movements || ""}</td><td>{r.last_date ? day(r.last_date) : ""}</td>
    </tr>
  );
}

// ------------------------------------------------------------------------------------------------
function shipFrom(ds: Dataset, customer: string, order: string): string | null {
  const c = (ds.confirmations ?? []).find((x) => x.order === order);
  if (c) return c.ship_from;
  const lanes = (ds.lanes ?? []).filter((l) => l.destination === customer).sort((a, b) => (a.priority ?? 1) - (b.priority ?? 1));
  return lanes[0]?.origin ?? null;
}

function Orders({ res, ds }: { res: ActualsView; ds: Dataset }) {
  const [postDate, setPostDate] = useState(addDays(ds.settings.planning_start, -1));
  const receipts = res.open_orders.filter((o) => o.kind !== "sales");
  const sales = res.open_orders.filter((o) => o.kind === "sales");
  const closed = [...(ds.closed_orders ?? [])].reverse().slice(0, 30);
  const receive = (o: OpenOrderRow) => post({ date: postDate, type: "receipt", location: o.location, product: o.product,
    qty: Math.round(o.open * 1000) / 1000, reference: o.id, counterparty: o.kind === "purchase" ? o.counterparty : null, final: false, note: "" });
  const ship = (o: OpenOrderRow) => {
    const from = shipFrom(ds, o.location, o.id);
    if (!from) return;
    post({ date: postDate, type: "sale", location: from, product: o.product, qty: Math.round(o.open * 1000) / 1000, reference: o.id,
      counterparty: o.location, final: false, note: "" });
  };
  return (
    <div className="stack">
      <div className="row" style={{ gap: 10 }}>
        <label className="small muted" htmlFor="post-date">Posting date</label>
        <input id="post-date" type="date" className="input" style={{ width: 170 }} value={postDate} onChange={(e) => setPostDate(e.target.value)} />
        <span className="faint small">Quick posts land in the journal on this date. Movements before the planning start ({day(ds.settings.planning_start)}) count
          at the next sync; later ones at the next roll-forward.</span>
      </div>
      <Firming ds={ds} />
      <Panel flush title="Firm receipts: purchase, production and transfer orders">
        {receipts.length === 0 ? <Empty title="No firm receipts">Firm planned orders above, or add receipts under Planning data.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="t">
              <thead><tr><th>Order</th><th>Kind</th><th>Receiving</th><th>Product</th><th>From</th><th className="num">Ordered</th>
                <th className="num">Received</th><th className="num">Open</th><th className="num">In transit</th><th className="num">To issue</th><th>Due</th><th /></tr></thead>
              <tbody>
                {receipts.map((o) => (
                  <tr key={o.id}>
                    <td><b>{o.id}</b></td><td>{o.kind}</td><td><Loc id={o.location} /></td><td><Prod id={o.product} /></td><td>{o.counterparty ?? ""}</td>
                    <td className="num">{qty(o.ordered)}</td><td className="num">{o.delivered ? qty(o.delivered) : ""}</td><td className="num">{qty(o.open)}</td>
                    <td className="num">{o.in_transit ? qty(o.in_transit) : ""}</td><td className="num">{o.reservations_open ? qty(o.reservations_open) : ""}</td>
                    <td>{day(o.due_date)} {o.past_due && <Badge sev="warning">past due</Badge>}</td>
                    <td><button className="btn sm" onClick={() => receive(o)} disabled={o.open <= 1e-6} aria-label={`Receive ${o.id}`}>Receive</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel flush title="Open sales orders">
        {sales.length === 0 ? <Empty title="No open sales orders" /> : (
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="t">
              <thead><tr><th>Order</th><th>Customer</th><th>Product</th><th className="num">Ordered</th><th className="num">Delivered</th>
                <th className="num">Open</th><th>Requested</th><th /></tr></thead>
              <tbody>
                {sales.map((o) => (
                  <tr key={o.id}>
                    <td><b>{o.id}</b></td><td><Loc id={o.location} /></td><td><Prod id={o.product} /></td><td className="num">{qty(o.ordered)}</td>
                    <td className="num">{o.delivered ? qty(o.delivered) : ""}</td><td className="num">{qty(o.open)}</td>
                    <td>{day(o.due_date)} {o.past_due && <Badge sev="warning">past due</Badge>}</td>
                    <td><button className="btn sm" onClick={() => ship(o)} disabled={o.open <= 1e-6 || !shipFrom(ds, o.location, o.id)} aria-label={`Ship ${o.id}`}>Ship</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {closed.length > 0 && (
        <Panel flush title="Recently closed" actions={<a className="btn sm ghost" href={href("data", "closed_orders")}>All closed orders</a>}>
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            <table className="t">
              <thead><tr><th>Order</th><th>Kind</th><th>Product</th><th className="num">Ordered</th><th className="num">Delivered</th><th>Due</th><th>Last delivery</th><th>OTIF</th></tr></thead>
              <tbody>
                {closed.map((c) => {
                  const onTime = !!c.last_delivery && c.last_delivery <= c.due_date;
                  const inFull = c.delivered_qty >= c.ordered_qty * (1 - (ds.execution?.delivery_tolerance ?? 0.02)) - 1e-6;
                  return (
                    <tr key={`${c.kind}|${c.id}`}><td><b>{c.id}</b></td><td>{c.kind}</td><td><Prod id={c.product} /></td><td className="num">{qty(c.ordered_qty)}</td>
                      <td className="num">{qty(c.delivered_qty)}</td><td>{day(c.due_date)}</td><td>{c.last_delivery ? day(c.last_delivery) : "—"}</td>
                      <td>{onTime && inFull ? <Badge sev="ok">OTIF</Badge> : <Badge sev="warning">{!onTime ? "late" : ""}{!onTime && !inFull ? " · " : ""}{!inFull ? "short" : ""}</Badge>}</td></tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function Firming({ ds }: { ds: Dataset }) {
  const plan = useStore((s) => s.runs.plan);
  const planStale = useStore((s) => isStale(s, "plan"));
  const zone = ds.execution?.firm_zone_days ?? 14;
  const limit = addDays(ds.settings.planning_start, zone);
  const cands = useMemo(() => (plan.data?.ok ? plan.data.orders.filter((o) => o.start_date < limit && o.convertible
    && !(ds.locations ?? []).some((l) => l.id === o.location && l.type === "customer")) : []), [plan.data, limit, ds.locations]);
  const [pick, setPick] = useState<Set<string> | null>(null);
  const chosen = pick ?? new Set(cands.map((o) => o.id));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const firm = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.firm(ds, [...chosen]);
      store.replace(out.dataset);
      setPick(null);
      setMsg(`${out.report.firmed.length} planned orders firmed: ${out.report.firmed.slice(0, 4).map((f) => `${f.planned_id} → ${f.receipt_id}`).join(", ")}${out.report.firmed.length > 4 ? "…" : ""}. Re-plan to see the rest move around them.`);
      await Promise.all([store.run("plan"), store.run("actuals")]);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const toggle = (o: PlannedOrder) => {
    const n = new Set(chosen);
    if (n.has(o.id)) n.delete(o.id);
    else n.add(o.id);
    setPick(n);
  };
  return (
    <Panel flush title={`Firm zone: planned orders starting before ${day(limit)} (${zone} days)`} actions={
      plan.data ? <button className="btn sm accent" disabled={busy || planStale || chosen.size === 0} onClick={firm}
        title={planStale ? "Recalculate the supply plan first" : "Turns these planned orders into firm purchase, production and transfer orders in your data. Undo reverts it."}>
        {busy ? "Saving…" : `Make ${chosen.size} order${chosen.size === 1 ? "" : "s"} firm`}</button> : null}>
      {msg && <div className="banner info" style={{ margin: 12 }}><Badge sev="ok">Firmed</Badge><span>{msg}</span><span className="spacer" />
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
      {err && <div className="banner error" style={{ margin: 12 }}><Badge sev="error">Firming failed</Badge>{err}</div>}
      {!plan.data ? <Empty title="No supply plan yet"><button className="btn" onClick={() => store.run("plan")} disabled={plan.running}>Calculate the supply plan</button></Empty>
        : planStale ? <Empty title="The supply plan is out of date"><button className="btn" onClick={() => store.run("plan")} disabled={plan.running}>{plan.running ? "Calculating…" : "Recalculate the supply plan"}</button></Empty>
        : cands.length === 0 ? <Empty title="Nothing to firm">No convertible planned order starts inside the firm zone.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            <table className="t">
              <thead><tr><th style={{ width: 28 }} /><th>Planned order</th><th>Becomes</th><th>Location</th><th>Product</th><th>From</th><th className="num">Qty</th><th>Start</th><th>Due</th></tr></thead>
              <tbody>
                {cands.map((o) => (
                  <tr key={o.id} className="clickable" onClick={() => toggle(o)}>
                    <td><input type="checkbox" checked={chosen.has(o.id)} onChange={() => toggle(o)} onClick={(e) => e.stopPropagation()} aria-label={`Firm ${o.id}`} /></td>
                    <td><b>{o.id}</b></td><td>{o.kind === "make" ? "production order" : o.kind === "buy" ? "purchase order" : "stock transfer"}</td>
                    <td><Loc id={o.location} /></td><td><Prod id={o.product} /></td><td>{o.origin ?? o.source_id}</td><td className="num">{qty(o.qty)}</td>
                    <td>{day(o.start_date)} {o.start_in_past && <Badge sev="warning">late start</Badge>}</td><td>{day(o.due_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </Panel>
  );
}

// ------------------------------------------------------------------------------------------------
const TYPES = ["all", "opening", "receipt", "issue", "sale", "transfer_out", "scrap", "adjustment"] as const;

function Journal({ ds }: { ds: Dataset }) {
  const [type, setType] = useState<(typeof TYPES)[number]>("all");
  const [draft, setDraft] = useState<Obj>(() => ({ date: ds.settings.planning_start, type: "receipt", location: "", product: "", qty: 0, final: false, note: "" }));
  const [err, setErr] = useState<string | null>(null);
  const rows = [...(ds.movements ?? [])].filter((m) => type === "all" || m.type === type).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id.localeCompare(a.id)));
  const submit = () => {
    const m = draft as unknown as GoodsMovement;
    if (!m.location || !m.product || !m.qty) { setErr("Location, product and a non-zero quantity are required."); return; }
    if (m.type !== "adjustment" && m.qty < 0) { setErr("Only count adjustments take a negative quantity."); return; }
    setErr(null);
    post({ ...m, reference: m.reference || null, counterparty: m.counterparty || null });
    setDraft({ ...draft, qty: 0, reference: "", note: "" });
  };
  return (
    <div className="grid-2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 1.6fr) minmax(300px, 1fr)" }}>
      <Panel flush title="Goods movements" actions={
        <select className="input" style={{ width: 150 }} value={type} onChange={(e) => setType(e.target.value as (typeof TYPES)[number])} aria-label="Movement type filter">
          {TYPES.map((t) => <option key={t} value={t}>{t === "all" ? "All types" : t.replace("_", " ")}</option>)}
        </select>}>
        {rows.length === 0 ? <Empty title="No movements">Post the first one on the right.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 620 }}>
            <table className="t nowrap">
              <thead><tr><th>Id</th><th>Date</th><th>Type</th><th>Location</th><th>Product</th><th className="num">Qty</th><th>Reference</th><th>Counterparty</th></tr></thead>
              <tbody>
                {rows.slice(0, 400).map((m) => {
                  const signed = m.type === "adjustment" ? m.qty : INFLOW.has(m.type) ? m.qty : -m.qty;
                  return (
                    <tr key={m.id} className={m.date >= ds.settings.planning_start ? "" : "dim"}>
                      <td className="faint">{m.id}</td><td>{day(m.date)}</td><td>{m.type.replace("_", " ")}{m.final && <> <Badge sev="info">final</Badge></>}</td>
                      <td><Loc id={m.location} /></td><td><Prod id={m.product} /></td>
                      <td className="num" style={{ color: signed < 0 ? "var(--warning-text)" : undefined }}>{signed > 0 ? "+" : ""}{qty(signed)}</td>
                      <td>{m.reference ?? ""}</td><td>{m.counterparty ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <div className="stack">
        <Panel title="Post a movement">
          <SchemaForm defName="GoodsMovement" value={draft} onChange={setDraft} hide={["id"]} compact />
          {err && <div className="banner error" style={{ marginTop: 8 }}>{err}</div>}
          <div className="row" style={{ marginTop: 10 }}><button className="btn accent" onClick={submit}>Post movement</button></div>
        </Panel>
        <Reading formula="Receipts, issues and transfer issues carry the firm order they belong to as reference; sales carry the sales order and the customer. Mark the last delivery ‘final’ to close an order short."
          soWhat="Movements dated before the planning start are history already counted; later ones take effect when you roll forward past them." />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Roll({ ds }: { ds: Dataset }) {
  const start = ds.settings.planning_start;
  const [to, setTo] = useState(addDays(start, 7));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rep, setRep] = useState<RollReport | null>(lastRoll);
  const pending = (ds.movements ?? []).filter((m) => m.date >= start && m.date < to);
  const roll = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.roll(ds, to);
      lastRoll = out.report;
      setRep(out.report);
      store.replace(out.dataset);
      await store.run("actuals");
      setTo(addDays(to, 7));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <Panel title="Roll the plan forward">
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <span className="muted">From <b>{day(start)}</b> to</span>
          <input type="date" className="input" style={{ width: 170 }} value={to} min={start} onChange={(e) => setTo(e.target.value)} aria-label="Roll forward to" />
          <button className="btn accent" onClick={roll} disabled={busy || to < start}>{busy ? "Moving…" : "Move the plan to this date"}</button>
          <span className="faint small">{pending.length} movement{pending.length === 1 ? "" : "s"} fall in this window. Undo reverts the roll.</span>
        </div>
        {err && <div className="banner error" style={{ marginTop: 10 }}><Badge sev="error">Roll failed</Badge>{err}</div>}
      </Panel>
      {rep && <RollResult rep={rep} />}
      <Reading formula="New start = the roll date. On-hand = Σ movements before it; open qty = ordered − received (or delivered); elapsed forecast dropped, a straddling period keeps its remaining share; each elapsed week logged as forecast vs actual."
        soWhat="Every quantity is recomputed from the original order quantities and the whole journal, so rolling twice, or re-rolling after a late posting, gives the same answer." />
    </div>
  );
}

function RollResult({ rep }: { rep: RollReport }) {
  return (
    <>
      <SectionBand step="✓" title={`Rolled from ${day(rep.from_date)} to ${day(rep.to_date)}`} />
      <div className="grid-auto">
        <StatTile label="Stock changes" value={qty(rep.stock.length)} sub="nodes whose on-hand moved" />
        <StatTile label="Orders closed" value={qty(rep.closed.length)} sub={`${rep.orders.length - rep.closed.length} reduced`} />
        <StatTile label="Forecast consumed" value={qty(rep.forecast_dropped)} sub={`${rep.forecast_prorated} periods pro-rated`} />
        <StatTile label="History added" value={qty(rep.history_added)} sub="sales days, now forecast input" />
        <StatTile label="Accuracy logged" value={qty(rep.accuracy.length)} sub="series-weeks" />
      </div>
      {rep.warnings.map((w, i) => <div key={i} className="banner warning"><Badge sev="warning">Check</Badge>{w}</div>)}
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Panel flush title="Stock">
          {rep.stock.length === 0 ? <Empty title="No stock changes" /> : (
            <div className="table-wrap" style={{ maxHeight: 360 }}>
              <table className="t"><thead><tr><th>Location</th><th>Product</th><th className="num">Before</th><th className="num">After</th><th className="num">Δ</th></tr></thead>
                <tbody>{rep.stock.map((s) => <tr key={`${s.location}|${s.product}`}><td><Loc id={s.location} /></td><td><Prod id={s.product} /></td><td className="num">{qty(s.before)}</td>
                  <td className="num">{qty(s.after)}</td><td className="num">{s.after - s.before > 0 ? "+" : ""}{qty(s.after - s.before)}</td></tr>)}</tbody></table>
            </div>
          )}
        </Panel>
        <Panel flush title="Orders">
          {rep.orders.length === 0 ? <Empty title="No deliveries in the window" /> : (
            <div className="table-wrap" style={{ maxHeight: 360 }}>
              <table className="t"><thead><tr><th>Order</th><th>Kind</th><th>Product</th><th className="num">Open before</th><th className="num">Open after</th><th /></tr></thead>
                <tbody>{rep.orders.map((o) => <tr key={`${o.kind}|${o.id}`}><td><b>{o.id}</b></td><td>{o.kind}</td><td><Prod id={o.product} /></td>
                  <td className="num">{qty(o.open_before)}</td><td className="num">{qty(o.open_after)}</td>
                  <td>{o.closed ? <Badge sev="ok">closed</Badge> : <Badge sev="info">partial</Badge>}</td></tr>)}</tbody></table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

// ------------------------------------------------------------------------------------------------
function Accuracy({ res, sel }: { res: ActualsView; sel?: string }) {
  const a = res.accuracy;
  const key = (s: AccuracySeries) => `${s.location}|${s.product}`;
  const cur = a.series.find((s) => key(s) === sel) ?? a.series[0];
  if (a.series.length === 0) {
    return <Panel><Empty title="No elapsed weeks yet">Move the plan past a week with posted sales; each elapsed week is logged as forecast against actual.
      <div style={{ marginTop: 10 }}><a className="btn" href={href("execution", "roll")}>Start a new week</a></div></Empty></Panel>;
  }
  const sevOf = (acc: number | null) => (acc === null ? undefined : acc >= 0.8 ? "ok" : acc >= 0.6 ? "warning" : "error");
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Forecast accuracy" value={pct(a.accuracy, 0)} sub="1 − WMAPE over every series-week" />
        <StatTile label="WMAPE" value={pct(a.wmape, 1)} sub="Σ|F − A| / ΣA" />
        <StatTile label="Bias" value={a.bias === null ? "—" : `${a.bias > 0 ? "+" : ""}${pct(a.bias, 1)}`} sub={a.bias === null ? "" : a.bias > 0 ? "over-forecast" : "under-forecast"} />
        <StatTile label="Weeks measured" value={qty(a.periods)} sub={`${qty(a.actual)} units sold vs ${qty(a.forecast)} forecast`} />
      </div>
      {cur && (
        <Panel title={`${cur.product} at ${cur.location}: forecast against actual`}>
          <BucketChart labels={cur.weeks.map((w) => day(w.start))} height={220} series={[
            { name: "Actual sales", color: "var(--series-1)", values: cur.weeks.map((w) => w.actual), kind: "column" },
            { name: "Forecast", color: "var(--series-2)", values: cur.weeks.map((w) => w.forecast), kind: cur.weeks.length > 1 ? "line" : "dots", dash: true },
          ]} />
        </Panel>
      )}
      <Panel flush title="By series">
        <div className="table-wrap" style={{ maxHeight: 480 }}>
          <table className="t">
            <thead><tr><th>Location</th><th>Product</th><th className="num">Forecast</th><th className="num">Actual</th><th className="num">|Error|</th>
              <th className="num">WMAPE</th><th className="num">Bias</th><th>Accuracy</th></tr></thead>
            <tbody>
              {a.series.map((s) => (
                <tr key={key(s)} className={`clickable ${cur && key(cur) === key(s) ? "selected" : ""}`} onClick={() => go("execution", "accuracy", key(s))}>
                  <td><Loc id={s.location} /></td><td><Prod id={s.product} /></td><td className="num">{qty(s.forecast)}</td><td className="num">{qty(s.actual)}</td>
                  <td className="num">{qty(s.abs_error)}</td><td className="num">{pct(s.wmape, 1)}</td>
                  <td className="num">{s.bias === null ? "—" : `${s.bias > 0 ? "+" : ""}${pct(s.bias, 1)}`}</td>
                  <td>{s.accuracy === null ? <span className="faint">no sales</span> : <Badge sev={sevOf(s.accuracy)}>{pct(s.accuracy, 0)}</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="WMAPE = Σ|forecast − actual| / Σ actual, per series over the logged weeks; bias = (Σ forecast − Σ actual) / Σ actual; accuracy = max(0, 1 − WMAPE). A sale counts at the customer when demand is planned there, else at the shipping location."
        soWhat="Persistent positive bias inflates stock; negative bias shows up as late orders. The actuals are already appended to sales history, so the next forecast run learns from them." />
    </div>
  );
}
