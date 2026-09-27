import { Fragment, useMemo, useState } from "react";
import { api } from "../api/client";
import type { AccuracySeries, ActualsView, Dataset, GoodsMovement, OpenOrderRow, PlannedOrder, PostAction, RollReport, ShortOrder, StockRow } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, Edits, Empty, MoreRows, Panel, Provenance, Reading, ROW_LIMIT, RunButton, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, Term,
} from "../components/ui";
import { day, pct, plural, qty } from "../lib/format";
import { Loc, Msg, namesOf, Prod, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useFreshResult, useStore } from "../state/store";
import {
  daysBetween, hasDetail, LotFields, lotExtra, LotsDetail, NO_LOT, PhysicalInventory, postAct, ShortOrders, StockRules, StockTypeCells, type LotInput,
} from "./ExecutionStock";

type View = "stock" | "count" | "orders" | "journal" | "roll" | "accuracy";

// The last roll-forward report, kept across tab switches (the roll itself is an undoable dataset edit).
let lastRoll: RollReport | null = null;

const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

const INFLOW = new Set(["opening", "receipt"]);

/** Where a planned order comes from, by its source record: the supplier of a purchasing source, the start of a lane. */
function SourceFrom({ ds, id }: { ds: Dataset; id?: string | null }) {
  const from = (ds.purchasing_sources ?? []).find((x) => x.id === id)?.supplier ?? (ds.lanes ?? []).find((x) => x.id === id)?.origin;
  return from ? <Loc id={from} /> : <span className="faint">—</span>;
}

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

/** Post through the engine (ship, receive with parts issued, count), keep the new dataset and re-read the journal. */
async function postActual(ds: Dataset, action: PostAction, extra: Parameters<typeof api.postActual>[2]): Promise<string> {
  return (await postAct(ds, action, extra)).text;
}

/** Book the journal into the starting position again without moving the planning start (a late posting, a count). */
async function rebook(ds: Dataset) {
  const out = await api.roll(ds, ds.settings.planning_start);
  lastRoll = out.report;
  store.replace(out.dataset);
  await store.run("actuals");
}

export function Execution({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.actuals);
  useFreshResult("actuals");
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
      answer={res && actualsAnswer(res, (ds.movements ?? []).reduce((m, x) => (x.date > m ? x.date : m), ""))}
      right={<>
      {res && <Provenance kind="derived" at={run.at} stale={stale} />}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("actuals")} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const nav = <Nav view={view} res={res} ds={ds} />;
  if (view === "journal") return body(<>{nav}<Journal ds={ds} /></>);
  if (view === "count") return body(<>{nav}<Count ds={ds} res={res ?? null} /></>);
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
    {!stale && <UnbookedBanner res={res} ds={ds} />}
    {view === "stock" && <Stock res={res} ds={ds} />}
    {view === "orders" && <Orders res={res} ds={ds} />}
    {view === "accuracy" && <Accuracy res={res} sel={route[2]} />}
  </>);
}

function Nav({ view, res, ds }: { view: View; res: ActualsView | null; ds: Dataset }) {
  return (
    <Tabs<View> value={view} onChange={(v) => go("execution", v)} tabs={[
      { id: "stock", label: "Stock from movements", count: res?.stock.length },
      { id: "count", label: "Count stock" },
      { id: "orders", label: "Open orders & firming", count: res?.open_orders.length },
      { id: "journal", label: "Movement journal", count: ds.movements?.length ?? 0 },
      { id: "roll", label: "Start a new week" },
      { id: "accuracy", label: "Forecast accuracy", count: res?.accuracy.series.length },
    ]} />
  );
}

// ------------------------------------------------------------------------------------------------
/** `last`: the latest movement's date (movements of the week under way run past the plan's start). */
function actualsAnswer(res: ActualsView, last: string) {
  const upTo = day(last > res.as_of ? last : res.as_of);
  const off = res.stock.filter((r) => Math.abs(r.difference) > 1e-6).length;
  const neg = res.stock.filter((r) => r.negative_on).length;
  const acc = res.accuracy && res.accuracy.periods > 0 ? res.accuracy.accuracy : null;
  const books = !res.movements ? "No goods movements are recorded yet."
    : off || neg ? `${plural(res.movements, "goods movement")} recorded up to ${upTo}; ${[off && `${plural(off, "place")} ${off === 1 ? "has" : "have"} stock that doesn't match them`, neg && `${plural(neg, "place")} would go negative`].filter(Boolean).join(" and ")}.`
    : `${plural(res.movements, "goods movement")} recorded up to ${upTo}, and stock matches them everywhere.`;
  return <>{books}{acc !== null && <> The forecast was {pct(acc, 0)} accurate against real sales over {plural(res.accuracy.periods, "week")}.</>}</>;
}

function Stock({ res, ds }: { res: ActualsView; ds: Dataset }) {
  const nm = useNames();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const [only, setOnly] = useState<"" | "held" | "expiring">("");
  const off = res.stock.filter((r) => Math.abs(r.difference) > 1e-6);
  const held = res.stock.filter((r) => r.quality > 1e-6 || r.blocked > 1e-6);
  const expired = res.stock.filter((r) => r.expired > 1e-6);
  const soon = res.stock.filter((r) => r.lots.some((l) => l.expires_on && !l.expired && l.qty > 1e-6 && daysBetween(res.as_of, l.expires_on) <= 7));
  const q = find.trim().toLowerCase();
  const shown = res.stock.filter((r) => (!q || nm.loc(r.location).toLowerCase().includes(q) || nm.prod(r.product).toLowerCase().includes(q)
    || r.lots.some((l) => (l.batch ?? "").toLowerCase().includes(q)) || r.serials.some((s) => s.toLowerCase() === q))
    && (only !== "held" || held.includes(r)) && (only !== "expiring" || expired.includes(r) || soon.includes(r)));
  const neg = res.stock.filter((r) => r.negative_on);
  const setup = res.stock.filter((r) => r.opening_from_setup).length;
  const sync = async () => {
    setBusy(true);
    setErr(null);
    try {
      await rebook(ds);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Movements" value={qty(res.movements)} sub={setup ? `plus ${plural(setup, "opening balance")} from setup` : `${qty(res.stock.reduce((a, r) => a + r.movements, 0))} before ${day(res.as_of)} are in stock`} />
        <StatTile label="Out of sync" value={qty(off.length)} sub="on-hand ≠ Σ movements" tone={off.length ? "hl" : undefined} />
        <StatTile label="Negative stock" value={qty(neg.length)} sub="a receipt missing or late" />
        <StatTile label="Unmatched references" value={qty(res.unmatched.length)} sub="no open or closed order" />
        <StatTile label="In inspection or blocked" value={qty(held.length)} sub="places planning counts less at" />
        <StatTile label="Expired or expiring" value={qty(expired.length + soon.length)} sub={expired.length ? `${plural(expired.length, "place")} past the date` : "within 7 days"}
          tone={expired.length ? "hl" : undefined} />
      </div>
      {done && <div className="banner info"><Badge sev="ok">Posted</Badge><span>{done}</span><span className="spacer" />
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setDone(null)}>✕</button></div>}
      {err && <div className="banner error"><Badge sev="error">Sync failed</Badge>{err}</div>}
      {off.length > 0 && !res.unbooked?.needed && (
        <div className="banner warning"><Badge sev="warning">{off.length} nodes out of sync</Badge>
          <span>On-hand in the planning policies differs from the journal. Syncing adopts the journal without moving the planning start.</span>
          <span className="spacer" /><Edits><button className="btn sm" onClick={sync} disabled={busy}>{busy ? "Syncing…" : "Sync stock from journal"}</button></Edits></div>
      )}
      <Panel flush title="On-hand reconciliation" actions={<div className="row" style={{ gap: 8 }}>
        <input className="input" style={{ width: 220 }} placeholder="Place, product, batch or serial" value={find} onChange={(e) => setFind(e.target.value)} aria-label="Find stock" />
        <select className="input" style={{ width: 190 }} value={only} onChange={(e) => setOnly(e.target.value as typeof only)} aria-label="Show">
          <option value="">Every place</option><option value="held">In inspection or blocked</option><option value="expiring">Expired or expiring</option>
        </select></div>}>
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="t">
            <thead><tr><th style={{ width: 24 }} /><th>Location</th><th>Product</th><th className="num">Planning on-hand</th><th className="num">Σ movements</th>
              <th className="num">Difference</th><th className="num" title="Now, this week's postings included: received, not yet released from quality inspection">Inspection</th>
              <th className="num" title="Now: held back, planning does not count it">Blocked</th><th className="num" title="Now: past its expiry date, planning does not count it">Expired</th>
              <th className="num" title="Shipped to this place and not yet received">In transit</th><th>In / out</th><th className="num">Movements</th><th>Last</th></tr></thead>
            <tbody>
              {shown.slice(0, ROW_LIMIT).map((r) => <StockLine key={`${r.location}|${r.product}`} r={r} ds={ds} asOf={res.as_of} onDone={setDone} />)}
            </tbody>
          </table>
        </div>
        <MoreRows shown={Math.min(shown.length, ROW_LIMIT)} total={shown.length} what="places" how="Find a place, product, batch or serial to narrow the list." />
      </Panel>
      <Reading formula="on-hand(node) = Σ signed movements dated before the planning start: + opening, receipt; − issue, sale, transfer issue, scrap; ± count adjustment. Planning counts the stock that is free to use and not past its expiry date, and stock in quality inspection unless the company says otherwise; blocked stock never."
        soWhat="Once a place has movements, change its stock with a count, not by typing on-hand: post what happened, then start a new week and the plan starts from the physical truth." />
      <StockRules ds={ds} />
    </div>
  );
}

function StockLine({ r, ds, asOf, onDone }: { r: StockRow; ds: Dataset; asOf: string; onDone: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const detail = hasDetail(r);
  const inflow = Object.entries(r.by_type).filter(([t]) => INFLOW.has(t)).reduce((a, [, v]) => a + v, 0) + Math.max(0, r.by_type.adjustment ?? 0);
  const outflow = -Object.entries(r.by_type).filter(([t]) => !INFLOW.has(t) && t !== "adjustment").reduce((a, [, v]) => a + v, 0) + Math.max(0, -(r.by_type.adjustment ?? 0));
  const scale = Math.max(inflow, outflow, 1);
  return (<>
    <tr>
      <td>{detail && <button className="btn sm ghost" style={{ padding: "0 6px" }} onClick={() => setOpen(!open)} aria-expanded={open}
        aria-label={`Batches and stock of ${r.product} at ${r.location}`}>{open ? "▾" : "▸"}</button>}</td>
      <td><Loc id={r.location} /></td><td><Prod id={r.product} />{r.counting && <> <Badge sev="info">counting</Badge></>}</td>
      <td className="num">{qty(r.master_on_hand)}{r.opening_from_setup && <> <span title="Stock entered at setup is the opening balance; starting a new week writes it into the journal"><Badge sev="info">opening</Badge></span></>}</td>
      <td className="num">{r.movement_stock === null ? <span className="faint">—</span> : qty(r.movement_stock)}</td>
      <td className="num">{Math.abs(r.difference) > 1e-6 ? <Badge sev="warning">{r.difference > 0 ? "+" : ""}{qty(r.difference)}</Badge> : <span className="faint">0</span>}
        {r.negative_on && <> <Badge sev="error">negative {day(r.negative_on)}</Badge></>}</td>
      <StockTypeCells r={r} />
      <td style={{ minWidth: 140 }} title={Object.entries(r.by_type).map(([t, v]) => `${t}: ${qty(v)}`).join(" · ")}>
        {r.movements > 0 && <div className="flowbar">
          <span style={{ width: `${(inflow / scale) * 100}%`, background: "var(--series-1)" }} />
          <span style={{ width: `${(outflow / scale) * 100}%`, background: "var(--series-2)" }} />
        </div>}
      </td>
      <td className="num">{r.movements || ""}</td><td>{r.last_date ? day(r.last_date) : ""}</td>
    </tr>
    {open && <tr className="sub"><td colSpan={13}><LotsDetail r={r} ds={ds} asOf={asOf} onDone={onDone} /></td></tr>}
  </>);
}

// ------------------------------------------------------------------------------------------------
/** Postings dated before the planning start that the starting position does not reflect yet (Q15). */
function UnbookedBanner({ res, ds }: { res: ActualsView; ds: Dataset }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const u = res.unbooked;
  if (!u?.needed) return null;
  const what = [u.stock && `stock at ${plural(u.stock, "place")}`, u.orders && plural(u.orders, "order"),
    u.accuracy_weeks && `forecast accuracy for ${plural(u.accuracy_weeks, "week")}`,
    !u.accuracy_weeks && u.history_days && `sales history for ${plural(u.history_days, "day")}`,
    u.closed && `deliveries on ${plural(u.closed, "closed order")}`].filter(Boolean).join(", ");
  const book = async () => {
    setBusy(true);
    setErr(null);
    try { await rebook(ds); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="banner warning" role="status" style={{ marginBottom: 12 }}>
      <Badge sev="warning">Not counted yet</Badge>
      <span>Movements dated before {day(ds.settings.planning_start)} were posted after the plan started from them. Counting them
        changes {what}. The planning start stays where it is.</span>
      <span className="spacer" />
      <Edits><button className="btn sm accent" onClick={book} disabled={busy}>{busy ? "Counting…" : "Count them now"}</button></Edits>
      {err && <span className="small" style={{ color: "var(--error-text)" }}>{err}</span>}
    </div>
  );
}

/** Where each product is kept: planning policies, production (and its parts), purchasing, routes that name it, the journal. */
function stockNodes(ds: Dataset): [string, string][] {
  const type = new Map((ds.locations ?? []).map((l) => [l.id, l.type]));
  const phantom = new Set((ds.location_products ?? []).filter((x) => x.phantom).map((x) => `${x.location}|${x.product}`));
  const out = new Map<string, [string, string]>();
  const add = (l?: string | null, p?: string | null) => {
    const t = l ? type.get(l) : undefined;
    if (!l || !p || !t || t === "customer" || t === "supplier" || phantom.has(`${l}|${p}`)) return;
    out.set(`${l}|${p}`, [l, p]);
  };
  for (const x of ds.location_products ?? []) add(x.location, x.product);
  for (const ps of ds.production_sources ?? []) {
    add(ps.location, ps.product);
    for (const c of ps.components ?? []) add(ps.location, c.product);
    for (const c of ps.co_products ?? []) add(ps.location, c.product);
  }
  for (const pu of ds.purchasing_sources ?? []) add(pu.location, pu.product);
  for (const ln of ds.lanes ?? []) for (const p of ln.products ?? []) { add(ln.origin, p); add(ln.destination, p); }
  for (const m of ds.movements ?? []) add(m.location, m.product);
  // A route that names no products carries all of them: its destination holds what its origin has and is sold at
  // or beyond it (not the plant's raw materials, not another channel's goods).
  const demand = new Set((ds.demand ?? []).map((d) => `${d.location}|${d.product}`));
  const sold = (l: string, p: string, seen = new Set<string>()): boolean => {
    if (demand.has(`${l}|${p}`)) return true;
    seen.add(l);
    return (ds.lanes ?? []).some((ln) => ln.origin === l && !seen.has(ln.destination)
      && (!(ln.products ?? []).length || ln.products!.includes(p)) && sold(ln.destination, p, seen));
  };
  const open = (ds.lanes ?? []).filter((ln) => !(ln.products ?? []).length);
  for (let grew = true; grew; ) {
    grew = false;
    for (const ln of open) for (const [l, p] of [...out.values()]) {
      if (l !== ln.origin || out.has(`${ln.destination}|${p}`) || !sold(ln.destination, p)) continue;
      add(ln.destination, p);
      grew ||= out.has(`${ln.destination}|${p}`);
    }
  }
  return [...out.values()];
}

function Count({ ds, res }: { ds: Dataset; res: ActualsView | null }) {
  const nm = useNames();
  const start = ds.settings.planning_start;
  const [on, setOn] = useState(addDays(start, -1));
  const [place, setPlace] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const uom = new Map((ds.products ?? []).map((p) => [p.id, p.base_uom ?? "EA"]));
  const rows = useMemo(() => stockNodes(ds).sort((a, b) => nm.loc(a[0]).localeCompare(nm.loc(b[0])) || nm.prod(a[1]).localeCompare(nm.prod(b[1]))), [ds, nm]);
  const places = [...new Set(rows.map((r) => r[0]))];
  const now = (l: string, p: string) => {
    const r = res?.stock.find((x) => x.location === l && x.product === p);
    if (r) return r.movement_stock ?? r.master_on_hand;
    return (ds.location_products ?? []).find((x) => x.location === l && x.product === p)?.on_hand ?? 0;
  };
  const changed = Object.entries(edits).filter(([, v]) => v.trim() !== "" && Number.isFinite(Number(v)));
  const below = changed.filter(([, v]) => Number(v) < 0);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const counts = changed.map(([k, v]) => { const [location, product] = k.split("|"); return { location, product, qty: Number(v) }; });
      setMsg(await postActual(ds, "count", { counts, date: on }));
      setEdits({});
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  if (!rows.length) {
    return <Panel><Empty title="Nothing is kept anywhere yet">Add places and products first: <a href={href("setup")}>Set up the company</a>.</Empty></Panel>;
  }
  const shown = rows.filter((r) => !place || r[0] === place);
  return (
    <div className="stack">
      <PhysicalInventory ds={ds} nodes={rows} />
      <Panel title="Quick count" actions={
        <Edits><button className="btn sm accent" onClick={save} disabled={busy || !changed.length || below.length > 0}
          title={below.length ? "A count is what is there: 0 or more" : undefined}>{busy ? "Saving…" : changed.length ? `Save ${plural(changed.length, "count")}` : "Save counts"}</button></Edits>}>
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <label className="small muted" htmlFor="count-date">Counted at the end of</label>
          <input id="count-date" type="date" className="input" style={{ width: 170 }} value={on} onChange={(e) => setOn(e.target.value)} />
          <select className="input" style={{ width: 220 }} value={place} onChange={(e) => setPlace(e.target.value)} aria-label="Place">
            <option value="">Every place</option>
            {places.map((l) => <option key={l} value={l}>{nm.loc(l)}</option>)}
          </select>
          <span className="faint small">{on < start
            ? `The plan starts ${day(start)} from these counts. A place with no stock recorded gets them as its opening balance; any other gets the difference as a count adjustment.`
            : `A count after ${day(start)} is posted as a count adjustment and counts when you start a new week past it.`}</span>
        </div>
        {msg && <div className="banner info" style={{ marginTop: 10 }}><Badge sev="ok">Saved</Badge><span>{msg}</span></div>}
        {err && <div className="banner error" style={{ marginTop: 10 }}><Badge sev="error">Not saved</Badge>{err}</div>}
        {below.length > 0 && <div className="banner warning" style={{ marginTop: 10 }} role="status">A count is what is on the shelf: 0 or more.
          Fix {below.map(([k]) => { const [l, p] = k.split("|"); return `${nm.prod(p)} at ${nm.loc(l)}`; }).join(", ")}.</div>}
      </Panel>
      <Panel flush><Edits>
        <div className="table-wrap" style={{ maxHeight: 620 }}>
          <table className="t">
            <thead><tr><th>Place</th><th>Product</th><th className="num">Stock now</th><th className="num">Counted</th><th>Unit</th></tr></thead>
            <tbody>
              {shown.map(([l, p]) => {
                const k = `${l}|${p}`;
                const cur = now(l, p);
                return (
                  <tr key={k}>
                    <td><Loc id={l} /></td><td><Prod id={p} /></td>
                    <td className="num" style={cur < 0 ? { color: "var(--warning-text)" } : undefined}
                      title={cur < 0 ? "Below zero by the journal: more went out than was recorded coming in. Count what is there." : undefined}>{qty(cur)}</td>
                    <td className="num"><input className="input" type="number" min={0} step="any" style={{ width: 110, textAlign: "right" }}
                      value={edits[k] ?? ""} placeholder={qty(Math.max(0, cur))} onChange={(e) => setEdits({ ...edits, [k]: e.target.value })}
                      aria-label={`Counted ${nm.prod(p)} at ${nm.loc(l)}`} /></td>
                    <td className="faint">{uom.get(p)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Edits></Panel>
      <Reading formula="count − stock by the journal on that day = the opening balance (nothing recorded yet) or a count adjustment (±)."
        soWhat="Counting keeps the journal, the stock the plan starts from and the shelf in agreement; typing on-hand in the planning policies does not." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function shipFrom(ds: Dataset, customer: string, order: string): string | null {
  const c = (ds.confirmations ?? []).find((x) => x.order === order);
  if (c) return c.ship_from;
  const lanes = (ds.lanes ?? []).filter((l) => l.destination === customer).sort((a, b) => (a.priority ?? 1) - (b.priority ?? 1));
  if (lanes[0]) return lanes[0].origin;
  const own = (ds.locations ?? []).find((l) => l.id === customer);
  return own && own.type !== "customer" && own.type !== "supplier" ? customer : null;
}

/** The last day an order can leave and still reach the customer on the date asked: the promise's ship date when it
 *  was saved, else the date asked less the route's transit time (in whole days, as arrivals are counted). */
function shipBy(ds: Dataset, customer: string, order: string, due: string): string {
  const c = (ds.confirmations ?? []).filter((x) => x.order === order).map((x) => x.ship_date).sort()[0];
  if (c) return c;
  const from = shipFrom(ds, customer, order);
  const lane = (ds.lanes ?? []).find((l) => l.origin === from && l.destination === customer);
  const t = Math.max(0, Math.ceil((lane?.modes?.[0]?.transit_days ?? 0) - 0.5 - 1e-9));   // up to half a day: same day
  const d = new Date(due + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - t);
  return d.toISOString().slice(0, 10);
}

function Orders({ res, ds }: { res: ActualsView; ds: Dataset }) {
  const [postDate, setPostDate] = useState(ds.settings.planning_start);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [short, setShort] = useState<ShortOrder[]>([]);
  const receipts = res.open_orders.filter((o) => o.kind !== "sales");
  const sales = res.open_orders.filter((o) => o.kind === "sales");
  const closed = [...(ds.closed_orders ?? [])].reverse().slice(0, 30);
  const act = async (id: string, action: PostAction, extra: Parameters<typeof api.postActual>[2] = {}) => {
    setBusy(id);
    setErr(null);
    try {
      const out = await postAct(ds, action, { order: id, date: postDate, ...extra });
      setMsg(out.text);
      setShort(out.report.short_orders ?? []);
      setOpen(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };
  const toShip = (o: OpenOrderRow) => o.ordered - o.delivered - o.in_transit;
  return (
    <div className="stack">
      <div className="row" style={{ gap: 10 }}>
        <label className="small muted" htmlFor="post-date">Posting date</label>
        <input id="post-date" type="date" className="input" style={{ width: 170 }} value={postDate} onChange={(e) => setPostDate(e.target.value)} />
        <span className="faint small">What you post lands in the journal on this date. From {day(ds.settings.planning_start)} on it counts when you
          start a new week; an earlier date is a late posting, counted with one click.</span>
      </div>
      {msg && <div className="banner info"><Badge sev="ok">Posted</Badge><span>{msg}</span><span className="spacer" />
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
      {err && <div className="banner error"><Badge sev="error">Not posted</Badge>{err}</div>}
      <ShortOrders list={short} ds={ds} onDone={setMsg} />
      <Firming ds={ds} />
      <Panel flush title="Firm receipts: purchase, production and transfer orders">
        {receipts.length === 0 ? <Empty title="No firm receipts">Firm planned orders above, or order on Buying.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 520 }}>
            <table className="t">
              <thead><tr><th>Order</th><th>Kind</th><th>Receiving</th><th>Product</th><th>From</th><th className="num">Ordered</th>
                <th className="num">Received</th><th className="num">Open</th><th className="num">In transit</th><th className="num">Parts to issue</th><th>Due</th><th /></tr></thead>
              <tbody>
                {receipts.map((o) => (
                  <Fragment key={o.id}>
                    <tr>
                      <td><b>{o.id}</b>{o.planned_as && <div className="faint small" title="The planned order it was firmed from">was {o.planned_as}</div>}</td><td>{KIND[o.kind] ?? o.kind}</td><td><Loc id={o.location} /></td><td><Prod id={o.product} /></td>
                      <td>{o.kind === "production" ? <span className="faint">made here</span> : o.counterparty ? <Loc id={o.counterparty} /> : ""}</td>
                      <td className="num">{qty(o.ordered)}</td><td className="num">{o.delivered ? qty(o.delivered) : ""}</td><td className="num">{qty(o.open)}</td>
                      <td className="num">{o.in_transit ? qty(o.in_transit) : ""}</td><td className="num">{o.reservations_open ? qty(o.reservations_open) : ""}</td>
                      <td>{day(o.due_date)} {o.past_due && <Badge sev="warning">past due</Badge>}</td>
                      <td className="nowrap">
                        <Edits>{o.kind === "transfer" && <button className="btn sm" onClick={() => act(o.id, "ship")} disabled={!!busy || toShip(o) <= 1e-6}
                          aria-label={`Ship ${o.id}`} title="Goods issue at the sending place: the goods are then in transit">Ship</button>}{" "}
                        <button className="btn sm" onClick={() => act(o.id, "receive")} disabled={!!busy || o.open <= 1e-6} aria-label={`Receive ${o.id}`}
                          title={o.kind === "production" ? "Post what was made and issue its parts" : o.kind === "transfer" ? "Post the arrival (and the dispatch, if it was not posted)" : "Goods receipt of the open quantity"}>
                          {o.kind === "production" ? "Confirm" : "Receive"}</button>{" "}
                        <button className="btn sm ghost" onClick={() => setOpen(open === o.id ? null : o.id)} aria-expanded={open === o.id}
                          aria-label={`Post part of ${o.id}`} title="Part of it, a final delivery, or the parts actually used">…</button></Edits>
                      </td>
                    </tr>
                    {open === o.id && <tr className="sub"><td colSpan={12}><PostForm o={o} ds={ds} busy={busy === o.id}
                      onPost={(extra) => act(o.id, "receive", extra)} onShip={(q, lot) => act(o.id, "ship", { qty: q, ...lotExtra(lot) })} /></td></tr>}
                  </Fragment>
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
                <th className="num">Open</th><th title="The day it must leave to arrive on the date asked">Ship by</th><th>Arrives by</th><th /></tr></thead>
              <tbody>
                {sales.map((o) => {
                  const by = shipBy(ds, o.location, o.id, o.due_date);
                  return (
                  <tr key={o.id}>
                    <td><b>{o.id}</b></td><td><Loc id={o.location} /></td><td><Prod id={o.product} /></td><td className="num">{qty(o.ordered)}</td>
                    <td className="num">{o.delivered ? qty(o.delivered) : ""}</td><td className="num">{qty(o.open)}</td>
                    <td>{day(by)} {o.open > 1e-6 && postDate > by && <Badge sev="warning">late if sent {day(postDate)}</Badge>}</td>
                    <td>{day(o.due_date)} {o.past_due && <Badge sev="warning">past due</Badge>}</td>
                    <td className="nowrap"><Edits><button className="btn sm" onClick={() => act(o.id, "deliver")} disabled={!!busy || o.open <= 1e-6 || !shipFrom(ds, o.location, o.id)}
                      aria-label={`Deliver ${o.id}`} title="Goods issue of the open quantity to the customer, from where it was promised">Deliver</button></Edits>{" "}
                      <a className="btn sm ghost" href={href("promise", "orders", o.id)} aria-label={`Open ${o.id}`} title="Part of it, change or cancel">…</a></td>
                  </tr>
                  );
                })}
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

const KIND: Record<string, string> = { purchase: "purchase", production: "production", transfer: "transfer" };

/** Post part of an order, close it short, or (production) the parts actually used instead of the backflush. */
function PostForm({ o, ds, busy, onPost, onShip }: { o: OpenOrderRow; ds: Dataset; busy: boolean;
  onPost: (extra: Parameters<typeof api.postActual>[2]) => void; onShip: (qty: number, lot: LotInput) => void }) {
  const rc = (ds.receipts ?? []).find((r) => r.id === o.id);
  const [lot, setLot] = useState<LotInput>(NO_LOT);
  const [q, setQ] = useState(String(Math.round(o.open * 1000) / 1000));
  const [final, setFinal] = useState(false);
  const [actual, setActual] = useState(false);
  const parts = (rc?.reservations ?? []).filter((r) => o.kind === "production" || r.location !== o.location);
  const share = o.ordered > 0 ? Math.min(1, (o.delivered + (Number(q) || 0)) / o.ordered) : 1;
  const [usage, setUsage] = useState<Record<string, string>>({});
  const n = Number(q);
  const issued = (prod: string) => (ds.movements ?? []).filter((m) => m.reference === o.id && m.type === "issue" && m.product === prod).reduce((a, m) => a + m.qty, 0);
  const guess = (r: (typeof parts)[number]) => Math.max(0, (r.required_qty ?? r.qty) * share - issued(r.product));
  return (
    <Edits><div className="stack" style={{ gap: 8, padding: "6px 4px" }}>
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <label className="small muted">Quantity <input className="input" type="number" min={0} step="any" value={q} onChange={(e) => setQ(e.target.value)}
          style={{ width: 110 }} aria-label={`Quantity for ${o.id}`} /></label>
        <label className="small"><input type="checkbox" checked={final} onChange={(e) => setFinal(e.target.checked)} /> Last delivery: close the order even if short</label>
        {o.kind === "production" && parts.length > 0 && <label className="small"><input type="checkbox" checked={actual} onChange={(e) => setActual(e.target.checked)} /> Enter the parts actually used</label>}
        <span className="spacer" />
        {o.kind === "transfer" && <button className="btn sm" disabled={busy || !(n > 0)} onClick={() => onShip(n, lot)}>Ship {qty(n || 0)}</button>}
        <button className="btn sm accent" disabled={busy || !(n > 0)}
          onClick={() => onPost({ qty: n, final, ...lotExtra(lot),
            usage: actual ? parts.map((r) => ({ product: r.product, qty: Number(usage[r.product] ?? guess(r).toFixed(3)) || 0 })) : null })}>
          {o.kind === "production" ? "Confirm" : "Receive"} {qty(n || 0)}</button>
      </div>
      <LotFields ds={ds} product={o.product} value={lot} onChange={setLot} receiving={o.kind !== "transfer"} />
      {o.kind === "production" && parts.length > 0 && (
        <div className="small muted">{actual ? "Parts used:" : "Parts issued with it (in proportion to what is made):"}{" "}
          {parts.map((r) => (
            <span key={r.product} style={{ marginRight: 14, whiteSpace: "nowrap" }}><Prod id={r.product} />{" "}
              {actual ? <input className="input" type="number" min={0} step="any" style={{ width: 90 }} value={usage[r.product] ?? guess(r).toFixed(3)}
                onChange={(e) => setUsage({ ...usage, [r.product]: e.target.value })} aria-label={`Used ${namesOf(ds).prod(r.product)}`} />
                : <b>{qty(guess(r))}</b>}</span>
          ))}
        </div>
      )}
      {o.kind === "production" && !parts.length && <div className="small faint">This order has no parts reserved: they are issued from the bill of materials.</div>}
    </div></Edits>
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
  // a purchase that an open order would cover if it came sooner is left out until someone decides (Q9)
  const chosen = pick ?? new Set(cands.filter((o) => !o.open_later?.length).map((o) => o.id));
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
      const r = out.report;
      const pos = r.purchase_orders ?? [];
      setMsg(`${plural(r.firmed.length, "planned order")} firmed: ${r.firmed.slice(0, 4).map((f) => `${f.planned_id} → ${f.receipt_id}`).join(", ")}${r.firmed.length > 4 ? "…" : ""}.`
        + (pos.length ? ` Purchases went onto ${plural(pos.length, "purchase order")} (${pos.join(", ")}), grouped per supplier as on Buying${(r.notes ?? []).length ? `: ${(r.notes ?? []).map(namesOf(ds).text).join("; ")}` : ""}.` : "")
        + (Object.keys(r.skipped).length ? ` Not firmed: ${Object.entries(r.skipped).slice(0, 3).map(([k, v]) => `${k} (${v})`).join(", ")}.` : "")
        + " Re-plan to see the rest move around them.");
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
      plan.data ? <Edits><><button className="btn sm ghost" disabled={busy || planStale || !cands.length} onClick={() => setPick(new Set(chosen.size ? [] : cands.map((o) => o.id)))}>
        {chosen.size ? "Select none" : "Select all"}</button><button className="btn sm accent" disabled={busy || planStale || chosen.size === 0} onClick={firm}
        title={planStale ? "Recalculate the supply plan first" : "Turns these planned orders into firm purchase, production and transfer orders in your data. Undo reverts it."}>
        {busy ? "Saving…" : `Make ${chosen.size} order${chosen.size === 1 ? "" : "s"} firm`}</button></></Edits> : null}>
      {msg && <div className="banner info" style={{ margin: 12 }}><Badge sev="ok">Firmed</Badge><span>{msg}</span><span className="spacer" />
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
      {err && <div className="banner error" style={{ margin: 12 }}><Badge sev="error">Firming failed</Badge>{err}</div>}
      {!plan.data ? <Empty title="No supply plan yet"><button className="btn" onClick={() => store.run("plan")} disabled={plan.running}>Calculate the supply plan</button></Empty>
        : planStale ? <Empty title="The supply plan is out of date"><button className="btn" onClick={() => store.run("plan")} disabled={plan.running}>{plan.running ? "Calculating…" : "Recalculate the supply plan"}</button></Empty>
        : cands.length === 0 ? <Empty title="Nothing to firm">No convertible planned order starts inside the firm zone.</Empty> : (
          <><p className="small muted" style={{ margin: "10px 12px 0" }}>Planned numbers are temporary: every plan hands them out again.
            A firm order gets its own number and keeps the planned one as “was …”.</p>
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            <table className="t">
              <thead><tr><th style={{ width: 28 }} /><th>Planned order</th><th>Becomes</th><th>Location</th><th>Product</th><th>From</th><th className="num">Qty</th><th>Start</th><th>Due</th></tr></thead>
              <tbody>
                {cands.map((o) => (
                  <tr key={o.id} className="clickable" onClick={() => toggle(o)}>
                    <td><input type="checkbox" checked={chosen.has(o.id)} onChange={() => toggle(o)} onClick={(e) => e.stopPropagation()} aria-label={`Firm ${o.id}`} /></td>
                    <td><b>{o.id}</b></td><td>{o.kind === "make" ? "production order" : o.kind === "buy" ? "purchase order line" : "stock transfer"}
                      {!!o.open_later?.length && <div className="small" style={{ color: "var(--warning-text)" }}>{o.open_later.join(", ")} is already on order but arrives
                        later; expediting it may do instead</div>}</td>
                    <td><Loc id={o.location} /></td><td><Prod id={o.product} /></td><td>{o.kind === "make" ? <span className="faint">made here</span> : o.origin ? <Loc id={o.origin} /> : <SourceFrom ds={ds} id={o.source_id} />}</td><td className="num">{qty(o.qty)}</td>
                    <td>{day(o.start_date)} {o.start_in_past && <Badge sev="warning">late start</Badge>}</td><td>{day(o.due_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div></>
        )}
    </Panel>
  );
}

// ------------------------------------------------------------------------------------------------
const TYPES = ["all", "opening", "receipt", "issue", "sale", "transfer_out", "scrap", "adjustment", "status"] as const;
const TYPE_TEXT: Record<string, string> = { transfer_out: "transfer out", adjustment: "count difference", status: "stock change" };
const STOCK_TEXT: Record<string, string> = { quality: "inspection", blocked: "blocked" };

/** The quantity as it counts in stock: + in, − out, count differences and stock changes as signed; a reversal the other way. */
function signedQty(m: GoodsMovement): number {
  const s = m.type === "adjustment" || m.type === "status" ? m.qty : INFLOW.has(m.type) ? m.qty : -m.qty;
  return m.reversal_of ? -s : s;
}

function Journal({ ds }: { ds: Dataset }) {
  const [type, setType] = useState<(typeof TYPES)[number]>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const reversed = useMemo(() => new Set((ds.movements ?? []).map((m) => m.reversal_of).filter(Boolean) as string[]), [ds.movements]);
  const reverse = async (m: GoodsMovement) => {
    setBusy(m.id);
    setErr(null);
    try { setDone(await postActual(ds, "reverse", { movement: m.id })); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };
  const [draft, setDraft] = useState<Obj>(() => ({ date: ds.settings.planning_start, type: "receipt", location: "", product: "", qty: 0, final: false, note: "" }));
  const [err, setErr] = useState<string | null>(null);
  const q = find.trim().toLowerCase();
  const rows = [...(ds.movements ?? [])].filter((m) => (type === "all" || m.type === type)
    && (!q || [m.id, m.doc, m.batch, m.reference, m.product, m.location, ...(m.serials ?? [])].some((x) => (x ?? "").toLowerCase().includes(q))))
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id.localeCompare(a.id)));
  const submit = () => {
    const m = draft as unknown as GoodsMovement;
    if (!m.location || !m.product || !m.qty) { setErr("Location, product and a non-zero quantity are required."); return; }
    if (m.type !== "adjustment" && m.type !== "status" && m.qty < 0) { setErr("Only count differences and stock changes take a negative quantity."); return; }
    setErr(null);
    post({ ...m, reference: m.reference || null, counterparty: m.counterparty || null });
    setDraft({ ...draft, qty: 0, reference: "", note: "" });
  };
  return (
    <div className="grid-2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 1.6fr) minmax(300px, 1fr)" }}>
      <Panel flush title="Goods movements" actions={<div className="row" style={{ gap: 8 }}>
        <input className="input" style={{ width: 200 }} placeholder="Document, batch, order, serial" value={find} onChange={(e) => setFind(e.target.value)} aria-label="Find movements" />
        <select className="input" style={{ width: 150 }} value={type} onChange={(e) => setType(e.target.value as (typeof TYPES)[number])} aria-label="Movement type filter">
          {TYPES.map((t) => <option key={t} value={t}>{t === "all" ? "All types" : TYPE_TEXT[t] ?? t}</option>)}
        </select></div>}>
        {done && <div className="banner info" style={{ margin: 12 }}><Badge sev="ok">Reversed</Badge><span>{done}</span><span className="spacer" />
          <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setDone(null)}>✕</button></div>}
        {rows.length === 0 ? <Empty title="No movements">Post the first one on the right.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 620 }}>
            <table className="t nowrap">
              <thead><tr><th>Id</th><th>Document</th><th>Date</th><th>Type</th><th>Location</th><th>Product</th><th className="num">Qty</th><th>Batch</th>
                <th>Reference</th><th>Counterparty</th><th /></tr></thead>
              <tbody>
                {rows.slice(0, 400).map((m) => {
                  const signed = signedQty(m);
                  const gone = reversed.has(m.id);
                  return (
                    <tr key={m.id} className={m.date >= ds.settings.planning_start ? "" : "dim"}>
                      <td className="faint">{m.id}</td><td className="faint">{m.doc ?? ""}</td><td>{day(m.date)}</td>
                      <td>{TYPE_TEXT[m.type] ?? m.type}{m.final && <> <Badge sev="info">final</Badge></>}
                        {m.reversal_of && <> <Badge sev="info">reverses {m.reversal_of}</Badge></>}{gone && <> <Badge sev="warning">reversed</Badge></>}</td>
                      <td><Loc id={m.location} /></td><td><Prod id={m.product} /></td>
                      <td className="num" style={{ color: signed < 0 ? "var(--warning-text)" : undefined }}
                        title={m.serials?.length ? `Serial numbers: ${m.serials.join(", ")}` : undefined}>{signed > 0 ? "+" : ""}{qty(signed)}</td>
                      <td>{m.batch ?? ""}{m.stock_type && m.stock_type !== "unrestricted" && <span className="faint small"> {STOCK_TEXT[m.stock_type]}</span>}</td>
                      <td>{m.reference ?? ""}</td><td>{m.counterparty ? <Loc id={m.counterparty} /> : ""}</td>
                      <td>{!m.reversal_of && !gone && <Edits><button className="btn sm ghost" disabled={!!busy} onClick={() => reverse(m)}
                        aria-label={`Reverse ${m.id}`} title={m.doc ? `Take back every movement of ${m.doc}` : "Take this movement back"}>Reverse</button></Edits>}</td>
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
          <SchemaForm defName="GoodsMovement" value={draft} onChange={setDraft} hide={["id", "doc", "reversal_of", "serials"]} compact />
          {err && <div className="banner error" style={{ marginTop: 8 }}>{err}</div>}
          <div className="row" style={{ marginTop: 10 }}><Edits><button className="btn accent" onClick={submit}>Post movement</button></Edits></div>
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
          <Edits><button className="btn accent" onClick={roll} disabled={busy || to < start}>{busy ? "Moving…" : "Move the plan to this date"}</button></Edits>
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
      {rep.warnings.map((w, i) => <div key={i} className="banner warning"><Badge sev="warning">Check</Badge><Msg text={w} /></div>)}
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
  const nm = useNames();
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
        <Panel title={`${nm.prod(cur.product)} at ${nm.loc(cur.location)}: forecast against actual`}>
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
