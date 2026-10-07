import { Fragment, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, PoLineInput, PoView, PurchasingView, Requisition, ShortOrder, VendorRow } from "../api/types";
import {
  Badge, Edits, Empty, Panel, Provenance, Reading, RunButton, SolverIO, StageHeader, StaleMark, StatTile, Tabs, Term,
  MoreRows, ROW_LIMIT,
} from "../components/ui";
import { day, money, pct, plural, qty, unitMoney } from "../lib/format";
import { Loc, Prod, namesOf } from "../lib/names";
import { poAddresses, poDocument, poEmail } from "../lib/podoc";
import { ServerSend } from "../components/ServerSend";
import { download } from "../lib/tabular";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useFreshResult, useStore } from "../state/store";
import { LotFields, lotExtra, NO_LOT, ShortOrders, type LotInput } from "./ExecutionStock";
import { Contracts, Invoices, Owed, Returns, usePoAction } from "./BuyingPay";

type View = "order" | "orders" | "invoices" | "owed" | "returns" | "contracts" | "suppliers";
type Sev = "error" | "warning" | "info" | "ok";

const STATUS_SEV: Record<string, Sev> = {
  "awaiting approval": "warning", "to send": "warning", "awaiting confirmation": "info", sent: "info", confirmed: "ok",
  "partly received": "info", received: "ok", closed: "ok", overdue: "error", "confirmed late": "warning",
  "confirmed short": "warning", open: "info",
};

/** Run an engine write on the dataset, then refresh what it changes. */
async function apply<T extends { dataset: Dataset }>(fn: () => Promise<T>): Promise<T> {
  const before = store.get().dataset!;
  const out = await fn();
  store.replace(out.dataset, before);
  await Promise.all([store.run("purchasing"), store.run("plan")]);
  return out;
}

export function Buying({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.purchasing);
  useFreshResult("purchasing");
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "purchasing"));
  const view = ((route[1] as View) || "order") as View;
  const head = (
    <StageHeader title="Buying" kicker="What to order from which supplier, the purchase orders on their way, and how each supplier delivers."
      how={<>The supply plan's purchases are the <Term t="Purchase requisition">requisitions</Term>. Pick the ones to order and they become
        purchase orders, one per supplier and receiving place, priced from a contract or each supplier's price scales (a product on a
        scheduling agreement gets delivery schedule lines on it instead). An order is released (level by level, by its value), sent,
        confirmed by the supplier (in one delivery or several: the plan expects each) and received. The supplier's invoice is checked
        against the order and the goods received before it is paid; goods can go back to be replaced or credited.</>}
      answer={res && buyingAnswer(res, ds.purchasing?.release_window_days ?? 7)}
      right={<>{res && <Provenance kind="derived" at={run.at} stale={stale} />}
        <RunButton running={run.running} has={!!res} onClick={() => store.run("purchasing")} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  if (run.error) return body(<div className="banner error"><Badge sev="error">Could not list purchasing</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="What to order now and from whom, every purchase order with the state of each line, and each supplier's delivery record."
        from="The supply plan's purchases, the purchasing sources (prices, price scales, lead times, fixed and blocked), supplier purchasing data, purchase orders and goods receipts."
        feeds="The supply plan (orders, confirmed dates and quantities), goods receipts into stock at the next roll-forward, and the supplier reliability KPI." />
      <div style={{ height: 14 }} />
      <Panel><Empty title="Not listed yet"><p>Press Calculate, or Plan everything, to see what to buy.</p></Empty></Panel>
    </>);
  }
  return body(<>
    {stale && <StaleMark what="purchasing view" onRerun={() => store.run("purchasing")} busy={run.running} />}
    <Tabs<View> value={view} onChange={(v) => go("buying", v)} tabs={[
      { id: "order", label: "To order", count: res.totals.requisitions },
      { id: "orders", label: "Purchase orders", count: res.totals.open_orders },
      { id: "invoices", label: "Supplier invoices", count: (res.payables?.invoices.filter((i) => i.open > 0.005 && i.status !== "cancelled").length ?? 0) + res.totals.to_invoice },
      { id: "owed", label: "What we owe", count: res.payables?.payables.length ?? 0 },
      { id: "returns", label: "Returns", count: res.payables?.returns.length ?? 0 },
      { id: "contracts", label: "Contracts", count: res.payables?.contracts.length ?? 0 },
      { id: "suppliers", label: "Suppliers", count: res.vendors.length },
    ]} />
    {view === "order" && <ToOrder res={res} ds={ds} />}
    {view === "orders" && <Orders res={res} ds={ds} sel={route[2]} />}
    {view === "invoices" && res.payables && <Invoices res={res} ds={ds} sel={/^(SI|CM)-/.test(route[2] ?? "") ? route[2] : undefined}
      po={/^(SI|CM)-/.test(route[2] ?? "") ? undefined : route[2]} key={route[2] ?? ""} />}
    {view === "owed" && res.payables && <Owed res={res} ds={ds} />}
    {view === "returns" && res.payables && <Returns res={res} ds={ds} />}
    {view === "contracts" && res.payables && <Contracts res={res} ds={ds} />}
    {view === "suppliers" && <Suppliers res={res} ds={ds} />}
  </>);
}

function buyingAnswer(res: PurchasingView, window: number) {
  const t = res.totals;
  if (!res.ok) return <>The supply plan could not run, so there is nothing to order yet: see the Data check.</>;
  const parts: string[] = [];
  if (t.due_now) parts.push(`${plural(t.due_now, "purchase")} worth ${money(t.due_now_value, res.currency)} should be ordered in the next ${plural(window, "day")}${t.late_to_order ? ` (${t.late_to_order} already late)` : ""}`);
  else parts.push(`Nothing needs ordering in the next ${plural(window, "day")}`);
  if (t.open_orders) parts.push(`${plural(t.open_orders, "purchase order")} ${t.open_orders === 1 ? "is" : "are"} open, ${money(t.open_value, res.currency)} still to come`);
  const todo = [t.awaiting_approval && `${t.awaiting_approval} to approve`, t.to_send && `${t.to_send} to send`,
    t.confirmations_overdue && `${t.confirmations_overdue} to chase for a confirmation`, t.late_lines && `${plural(t.late_lines, "line")} late`,
    t.blocked_invoices && `${plural(t.blocked_invoices, "invoice")} blocked for payment`,
    t.payables_overdue && `${money(t.payables_overdue, res.currency)} owed to suppliers overdue`,
    t.to_invoice && `${plural(t.to_invoice, "order line")} received but not invoiced`].filter(Boolean);
  return <>{parts.join("; ")}.{todo.length > 0 && <> Needs you: {todo.join(", ")}.</>}</>;
}

// ------------------------------------------------------------------------------------------------
function ToOrder({ res, ds }: { res: PurchasingView; ds: Dataset }) {
  const [all, setAll] = useState(false);
  const [q, setQ] = useState("");
  const nmq = namesOf(ds);
  const rows = useMemo(() => res.requisitions.filter((r) => (all || r.due_now) && (!q
    || `${r.id} ${r.product} ${nmq.prod(r.product)} ${r.location} ${nmq.loc(r.location)} ${r.supplier} ${nmq.loc(r.supplier)}`.toLowerCase().includes(q.toLowerCase()))),
  [res.requisitions, all, q, nmq]);
  const [pick, setPick] = useState<Set<string> | null>(null);
  const chosen = pick ?? new Set(rows.map((r) => r.id));
  const [source, setSource] = useState<Record<string, string>>({});
  const [orderDate, setOrderDate] = useState(ds.settings.planning_start);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<React.ReactNode>(null);
  const [err, setErr] = useState<string | null>(null);
  const choiceOf = (r: Requisition) => r.choices.find((c) => c.source_id === (source[r.id] ?? r.source_id)) ?? r.choices[0];
  const picked = rows.filter((r) => chosen.has(r.id));
  const value = picked.reduce((a, r) => a + (choiceOf(r)?.value ?? r.value), 0);
  const suppliers = new Set(picked.map((r) => choiceOf(r)?.supplier ?? r.supplier));
  const toggle = (id: string) => {
    const n = new Set(chosen);
    if (n.has(id)) n.delete(id); else n.add(id);
    setPick(n);
  };
  const create = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const lines = picked.map((r) => ({ id: r.id, source_id: source[r.id] ?? null, qty: null }));
      const out = await apply(() => api.createPurchaseOrders(ds, lines, orderDate));
      const rep = out.report;
      setPick(null); setSource({});
      setMsg(<>
        {rep.created.length ? <>{plural(rep.created.length, "purchase order")} created: {rep.created.map((p, i) => (
          <span key={p.id}>{i > 0 && ", "}<a href={href("buying", "orders", p.id)}><b>{p.id}</b></a> to {namesOf(ds).loc(p.supplier)} ({plural(p.lines.length, "line")}, {money(p.value, p.currency)}{!p.approved && ", needs approval"})</span>))}.</> : "No purchase order created."}
        {rep.created.flatMap((p) => p.notes).map((n, i) => <div key={i} className="small">• {namesOf(ds).text(n)}</div>)}
        {Object.entries(rep.skipped).map(([id, why]) => <div key={id} className="small">• {id} not ordered: {namesOf(ds).text(why)}</div>)}
      </>);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };
  if (!res.ok) return <Panel><Empty title="No supply plan">The supply plan could not run; fix the problems in the Data check first.</Empty></Panel>;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Due to order" value={qty(res.totals.due_now)} sub={`within ${ds.purchasing?.release_window_days ?? 7} days`} tone="hl" />
        <StatTile label="Worth" value={money(res.totals.due_now_value, res.currency)} sub="duty included" />
        <StatTile label="Already late" value={qty(res.totals.late_to_order)} sub="order date before today" />
        <StatTile label="All requisitions" value={qty(res.totals.requisitions)} sub="in the plan's horizon" />
      </div>
      {msg && <div className="banner ok" role="status"><div>{msg}</div></div>}
      {err && <div className="banner error" role="alert"><Badge sev="error">Not ordered</Badge>{err}</div>}
      <Panel flush title="Requisitions: the plan's purchases" actions={<>
        <input className="input" placeholder="Product, place, supplier…" value={q} onChange={(e) => { setQ(e.target.value); setPick(null); }}
          style={{ maxWidth: 220 }} aria-label="Find requisitions" />
        <label className="row small"><input type="checkbox" checked={all} onChange={(e) => { setAll(e.target.checked); setPick(null); }} /> Show later ones too</label>
        <label className="row small" htmlFor="po-date">Order date <input id="po-date" type="date" className="input" style={{ width: 150 }} value={orderDate}
          min={ds.settings.planning_start} onChange={(e) => setOrderDate(e.target.value || ds.settings.planning_start)} /></label>
        <Edits><button className="btn accent" disabled={busy || picked.length === 0} onClick={create}>
          {busy ? "Ordering…" : `Create purchase orders (${picked.length})`}</button></Edits>
      </>}>
        {rows.length === 0 ? <Empty title={res.requisitions.length ? "Nothing due this week" : "Nothing to buy"}>
          {res.requisitions.length ? <>The next purchase is due to be ordered on {day(res.requisitions[0].order_date)}. Tick “Show later ones too” to order ahead.</>
            : <>The supply plan buys nothing in its horizon: stock and open orders cover demand.</>}</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 520 }}>
            <table className="t">
              <thead><tr><th aria-label="Order" /><th>Product</th><th>To</th><th className="num">Qty</th><th>Needed</th><th>Order by</th>
                <th>Supplier</th><th className="num">Price</th><th className="num">Value</th><th>Arrives</th></tr></thead>
              <tbody>
                {rows.slice(0, ROW_LIMIT).map((r) => {
                  const c = choiceOf(r);
                  return (
                    <tr key={r.id} className={chosen.has(r.id) ? "selected" : ""}>
                      <td><input type="checkbox" checked={chosen.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Order ${r.id}`} /></td>
                      <td><Prod id={r.product} /><div className="faint small">{r.id}</div>
                        {!!r.open_later?.length && <div className="small" style={{ color: "var(--warning-text)" }}>{r.open_later.join(", ")} is already on order
                          but arrives later: expedite it instead?</div>}</td><td><Loc id={r.location} /></td>
                      <td className="num">{qty(c?.qty ?? r.qty)}</td><td>{day(r.need_date)}</td>
                      <td>{r.late ? <><b>Now</b> <Badge sev="warning">late</Badge><div className="faint small">should have been {day(r.wanted_order_date ?? r.order_date)}</div></> : day(r.order_date)}</td>
                      <td>
                        {r.choices.length > 1 ? (
                          <select className="input" aria-label={`Supplier for ${r.id}`} value={c?.source_id}
                            onChange={(e) => setSource({ ...source, [r.id]: e.target.value })}>
                            {r.choices.map((x) => <option key={x.source_id} value={x.source_id} disabled={!!x.blocked}>
                              {namesOf(ds).loc(x.supplier)}{x.assigned ? " (planned)" : ""}{x.fixed ? " · fixed" : ""}{x.blocked ? " · blocked" : ""}</option>)}
                          </select>
                        ) : <Loc id={r.supplier} />}
                        {c?.blocked && <div className="small">{c.blocked}</div>}
                        {(c?.contract ?? r.contract) && <div className="faint small">contract {c?.contract ?? r.contract}</div>}
                        {r.agreement && (source[r.id] ?? r.source_id) === r.source_id && <div className="faint small">onto scheduling agreement {r.agreement}</div>}
                      </td>
                      <td className="num">{unitMoney(c?.price ?? r.price, c?.currency ?? r.currency)}</td>
                      <td className="num">{money(c?.value ?? r.value, res.currency)}</td>
                      <td>{c ? day(c.arrives) : day(r.due_date)} {c && c.days_late > 0 && <Badge sev="warning">{c.days_late} d late</Badge>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <MoreRows shown={ROW_LIMIT} total={rows.length} what="requisitions"
              how={`${picked.length === rows.length ? "All of them are ticked" : `${picked.length} are ticked`}: find a product, place or supplier to see the rest.`} />
          </div>
        )}
      </Panel>
      {picked.length > 0 && <Reading formula={<>{plural(picked.length, "line")} to {plural(suppliers.size, "supplier")}, {money(value, res.currency)} with duty.
        {(ds.purchasing?.release_levels?.length ?? 0) > 0 ? <> Orders are released by {(ds.purchasing?.release_levels ?? []).slice().sort((a, b) => a.above - b.above)
          .map((l) => `${l.name} above ${money(l.above, res.currency)}`).join(", then ")} before they are sent.</>
          : res.approval_limit != null && <> Orders above {money(res.approval_limit, res.currency)} need approval before they are sent.</>}</>}
        soWhat="Each supplier gets one order per receiving place. Choosing another supplier applies its minimum, pack size and lead time; the line's date moves if it can't deliver in time." />}
      <PurchasingSettings ds={ds} />
    </div>
  );
}

function PurchasingSettings({ ds }: { ds: Dataset }) {
  return (
    <details className="panel" style={{ padding: "10px 14px" }}>
      <summary><b>Purchasing settings</b> <span className="muted small">approval limit or release levels, what counts as due to order, invoice tolerances and tax</span></summary>
      <div style={{ marginTop: 10 }}>
        <SchemaForm defName="PurchasingSettings" value={(ds.purchasing ?? {}) as unknown as Obj}
          onChange={(next) => store.update((d) => { d.purchasing = next as unknown as Dataset["purchasing"]; })} />
      </div>
    </details>
  );
}

// ------------------------------------------------------------------------------------------------
/** A purchase order no requisition asked for: a sample, a spare, a buy ahead of a price rise (UX audit: orders could only
 *  be made from requisitions, so a one-off meant editing master data). */
function OneOffPo({ ds, onClose }: { ds: Dataset; onClose: () => void }) {
  const nm = namesOf(ds);
  const sources = (ds.purchasing_sources ?? []).filter((p) => p.location);
  const [src, setSrc] = useState(sources[0]?.id ?? "");
  const [n, setN] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const q = Number(n.replace(/,/g, ""));
  const create = async () => {
    setBusy(true); setMsg(null);
    try {
      const out = await apply(() => api.oneOffPo(ds, src, q, due || null));
      const po = out.report.created[0];
      setMsg(`${po.id} created${po.approved ? "" : ", needs approval"}.` + po.notes.map((x) => " " + nm.text(x)).join(""));
      setN(""); setDue("");
      go("buying", "orders", po.id);
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <Panel title={<h3>New purchase order</h3>} actions={<button className="btn sm ghost" onClick={onClose}>Close</button>}>
      {sources.length === 0 ? <p className="muted">Say who sells each part first: a product's Buy card in Set up.</p> : <Edits>
        <div className="row wrap">
          <label className="small">What, from whom, to where<br />
            <select className="select" value={src} onChange={(e) => setSrc(e.target.value)} aria-label="What to buy">
              {sources.map((p) => <option key={p.id} value={p.id}>{nm.prod(p.product)} from {nm.loc(p.supplier)} to {nm.loc(p.location ?? "")}</option>)}
            </select></label>
          <label className="small">Quantity<br /><input className="input" inputMode="decimal" style={{ width: 110 }} value={n}
            onChange={(e) => setN(e.target.value)} aria-label="Quantity to buy" /></label>
          <label className="small">Wanted on (blank: as soon as possible)<br /><input className="input" type="date" value={due}
            onChange={(e) => setDue(e.target.value)} aria-label="Wanted on" /></label>
          <button className="btn primary" disabled={busy || !src || !(q > 0)} onClick={create}>Create the purchase order</button>
        </div></Edits>}
      {msg && <p className="small" role="status">{msg}</p>}
    </Panel>
  );
}

function Orders({ res, ds, sel }: { res: PurchasingView; ds: Dataset; sel?: string }) {
  const [showClosed, setShowClosed] = useState(false);
  const [adding, setAdding] = useState(false);
  const list = res.orders.filter((p) => showClosed || !["received", "closed"].includes(p.status));
  const cur = res.orders.find((p) => p.id === sel);
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Open orders" value={qty(res.totals.open_orders)} sub={money(res.totals.open_value, res.currency) + " still to come"} tone="hl" />
        <StatTile label="To approve" value={qty(res.totals.awaiting_approval)} />
        <StatTile label="To send" value={qty(res.totals.to_send)} />
        <StatTile label="Confirmations to chase" value={qty(res.totals.confirmations_overdue)} />
        <StatTile label="Late lines" value={qty(res.totals.late_lines)} sub="confirmed after the date asked, or overdue" />
      </div>
      {adding && <OneOffPo ds={ds} onClose={() => setAdding(false)} />}
      <Panel flush title="Purchase orders" actions={<>
        {!adding && <Edits><button className="btn sm" onClick={() => setAdding(true)}>New purchase order</button></Edits>}
        <label className="row small"><input type="checkbox" checked={showClosed}
        onChange={(e) => setShowClosed(e.target.checked)} /> Show received and closed</label></>}>
        {list.length === 0 ? <Empty title="No open purchase orders">Create them from <a href={href("buying")}>To order</a>, or make a one-off with <b>New purchase order</b>.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 380 }}>
            <table className="t">
              <thead><tr><th>Order</th><th>Supplier</th><th>To</th><th>Status</th><th className="num">Lines</th><th className="num">Value</th>
                <th className="num">Still to come</th><th>Next delivery</th><th>Needs</th></tr></thead>
              <tbody>
                {list.map((p) => {
                  const next = p.lines.filter((x) => !x.closed && x.open > 1e-6).map((x) => x.expected_date).sort()[0];
                  return (
                    <tr key={p.id} className={`clickable ${p.id === sel ? "selected" : ""}`} onClick={() => go("buying", "orders", p.id)}>
                      <td><b>{p.id}</b>{!p.header && <div className="faint small">no order document</div>}
                        {p.kind === "scheduling_agreement" && <div className="faint small">scheduling agreement for <Prod id={p.product ?? ""} /></div>}</td>
                      <td>{p.supplier ? <Loc id={p.supplier} /> : "—"}</td><td><Loc id={p.location} /></td>
                      <td><Badge sev={STATUS_SEV[p.status]}>{p.status}</Badge></td>
                      <td className="num">{p.lines.length}</td><td className="num">{money(p.value, p.currency)}</td>
                      <td className="num">{money(p.open_value, p.currency)}</td><td>{next ? day(next) : "—"}</td>
                      <td className="small">{p.attention.join("; ")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {cur ? <OrderDetail key={cur.id} po={cur} ds={ds} /> : list.length > 0 && <p className="muted small">Pick an order to approve, send, confirm or receive it.</p>}
    </div>
  );
}

type Mode = null | "confirm" | "receive" | "change" | "cancel";

function OrderDetail({ po, ds }: { po: PoView; ds: Dataset }) {
  const [mode, setMode] = useState<Mode>(null);
  const open = po.lines.filter((x) => !x.closed);
  const [edit, setEdit] = useState<Record<string, { qty: string; date: string; price: string; final: boolean; on: boolean;
    parts: { date: string; qty: string }[] | null }>>({});
  const [lots, setLots] = useState<Record<string, LotInput>>({});
  const [on, setOn] = useState(ds.settings.planning_start);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [short, setShort] = useState<ShortOrder[]>([]);
  const start = (m: Mode) => {
    setMode(m); setErr(null); setMsg(null); setText(""); setLots({});
    setEdit(Object.fromEntries(open.map((x) => [x.id, {
      qty: String(m === "receive" ? Math.round(x.open * 1000) / 1000 : m === "confirm" ? x.confirmed_qty ?? x.ordered : x.ordered),
      date: m === "confirm" ? x.confirmed_date ?? x.due_date : x.due_date, price: x.price == null ? "" : String(x.price), final: false,
      on: m !== "receive" || x.open > 1e-6,
      parts: m === "confirm" && (x.confirmations?.length ?? 0) > 1 ? x.confirmations!.map((c) => ({ date: c.date, qty: String(c.qty) })) : null,
    }])));
  };
  const act = async (action: "approve" | "send" | "confirm" | "receive" | "change" | "cancel") => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const lines: PoLineInput[] | undefined = action === "approve" || action === "send" ? undefined : open.filter((x) => edit[x.id]?.on).map((x) => {
        const e = edit[x.id];
        return action === "cancel" ? { id: x.id, qty: null, date: null, price: null, final: false }
          : action === "receive" ? { id: x.id, qty: Number(e.qty), date: null, price: null, final: e.final, ...lotExtra(lots[x.id] ?? NO_LOT) }
          : action === "confirm" ? (e.parts ? { id: x.id, final: false, parts: e.parts.map((p) => ({ date: p.date, qty: Number(p.qty) })) }
            : { id: x.id, qty: Number(e.qty), date: e.date, price: null, final: false })
          : { id: x.id, qty: Number(e.qty), date: e.date, price: e.price === "" ? null : Number(e.price), final: false };
      });
      if (lines && lines.length === 0) throw new Error("Tick at least one line");
      const out = await apply(() => api.poAction(ds, action, po.id, { lines, date: action === "send" || action === "receive" ? on : undefined,
        reference: action === "confirm" ? text : undefined, note: action === "receive" ? text : undefined }));
      setMsg(namesOf(out.dataset).text(out.report.message));
      setShort(out.report.short_orders ?? []);
      setMode(null);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };
  const set = (id: string, patch: Partial<(typeof edit)[string]>) => setEdit({ ...edit, [id]: { ...edit[id], ...patch } });
  const hasOpen = open.some((x) => x.open > 1e-6);
  const agreement = po.kind === "scheduling_agreement";
  const levels = (ds.purchasing?.release_levels?.length ?? 0) > 0;
  const toBill = po.lines.some((x) => x.received - x.invoiced > 1e-6);
  const received = po.lines.some((x) => x.received > 1e-6);
  return (
    <Panel title={<h3>{po.id} <span className="muted">to {po.supplier ? namesOf(ds).loc(po.supplier) : "—"}</span> <Badge sev={STATUS_SEV[po.status]}>{po.status}</Badge></h3>}
      actions={<>
        <Edits>{po.header && !po.approved && <button className="btn accent" disabled={busy} onClick={() => act("approve")}>
          {levels && po.next_level ? `Release: ${po.next_level}` : "Approve"}</button>}
        {po.header && po.approved && !po.sent_on && hasOpen && <button className="btn accent" disabled={busy} onClick={() => act("send")}>
          {agreement ? "Send the delivery schedule" : "Mark as sent"}</button>}
        {hasOpen && <button className="btn" disabled={busy} onClick={() => start("confirm")}>Record confirmation</button>}
        {hasOpen && <button className="btn" disabled={busy} onClick={() => start("receive")}>Receive goods</button>}
        {hasOpen && <button className="btn ghost" disabled={busy} onClick={() => start("change")}>Change</button>}
        {open.some((x) => x.received <= 1e-6) && <button className="btn ghost" disabled={busy} onClick={() => start("cancel")}>Cancel lines</button>}
        {toBill && <button className="btn" disabled={busy} onClick={() => go("buying", "invoices", po.id)}>Enter the invoice</button>}
        {received && <button className="btn ghost" disabled={busy} onClick={() => go("buying", "returns")}>Send goods back</button>}</Edits>
      </>}>
      <div className="row wrap small muted" style={{ gap: 16, marginBottom: 10 }}>
        <span>To <Loc id={po.location} /></span>
        {po.order_date && <span>Ordered {day(po.order_date)}</span>}
        <span>{po.sent_on ? `Sent ${day(po.sent_on)}` : po.header ? "Not sent yet" : "Imported open order"}</span>
        {po.vendor_reference && <span>Supplier ref. {po.vendor_reference}</span>}
        <span>{money(po.value, po.currency)}</span>
        {agreement && <span>Scheduling agreement for <Prod id={po.product ?? ""} />{po.valid_to ? ` until ${day(po.valid_to)}` : ""}
          {po.target_qty != null ? `: ${qty(po.released_qty)} of ${qty(po.target_qty)} scheduled` : ""}</span>}
        {po.approvals.length > 0 && <span>Released {po.approvals.map((a) => `${a.level}${a.by ? ` by ${a.by}` : ""} ${day(a.on)}`).join(", ")}</span>}
        {!po.approved && po.levels_needed.length > 1 && <span>Needs {po.levels_needed.join(", then ")}</span>}
        {po.header && <PoDocButtons po={po} ds={ds} onSent={po.approved && !po.sent_on && hasOpen ? () => act("send") : undefined} />}
      </div>
      {po.attention.length > 0 && <div className="banner warning" style={{ marginBottom: 10 }}><div>{po.attention.map((a) => <div key={a}>• {a}</div>)}</div></div>}
      {msg && <div className="banner ok" role="status" style={{ marginBottom: 10 }}>{msg}</div>}
      <ShortOrders list={short} ds={ds} onDone={setMsg} />
      {err && <div className="banner error" role="alert" style={{ marginBottom: 10 }}><Badge sev="error">Not done</Badge>{err}</div>}
      {mode && (
        <div className="row wrap" style={{ gap: 10, marginBottom: 10 }}>
          {mode === "receive" && <label className="row small">Received on <input type="date" className="input" value={on} onChange={(e) => setOn(e.target.value)} /></label>}
          {(mode === "confirm" || mode === "receive") && <label className="row small">{mode === "confirm" ? "Supplier's confirmation no." : "Delivery note"}
            <input className="input" style={{ width: 160 }} value={text} onChange={(e) => setText(e.target.value)} /></label>}
          <button className="btn accent" disabled={busy} onClick={() => act(mode)}>
            {mode === "confirm" ? "Save confirmation" : mode === "receive" ? "Post goods receipt" : mode === "change" ? "Save changes" : "Cancel the ticked lines"}</button>
          <button className="btn ghost" disabled={busy} onClick={() => setMode(null)}>Back</button>
          <span className="faint small">{MODE_HINT[mode]}</span>
        </div>
      )}
      <div className="table-wrap">
        <table className="t">
          <thead><tr>{mode && <th aria-label="Include" />}<th>Line</th><th>Product</th><th className="num">Ordered</th>
            <th className="num">Received</th><th className="num">Open</th><th className="num">Price</th><th>Asked for</th><th>Confirmed</th><th>Status</th></tr></thead>
          <tbody>
            {po.lines.map((x) => {
              const e = edit[x.id];
              const editing = mode && !x.closed && e;
              const p = (ds.products ?? []).find((y) => y.id === x.product);
              const traced = !!p && ((p.batches ?? !!p.shelf_life_days) || !!p.serial_numbers);
              return (
                <Fragment key={x.id}>
                <tr>
                  {mode && <td>{editing && <input type="checkbox" checked={e.on} onChange={(ev) => set(x.id, { on: ev.target.checked })} aria-label={`Include ${x.id}`}
                    disabled={mode === "cancel" && x.received > 1e-6} />}</td>}
                  <td><b>{x.id}</b></td><td><Prod id={x.product} /></td>
                  <td className="num">{editing && (mode === "change" || mode === "confirm")
                    ? <input className="input num" style={{ width: 90 }} type="number" min={0} aria-label={`${mode === "confirm" ? "Confirmed" : "Ordered"} quantity ${x.id}`} value={e.qty} onChange={(ev) => set(x.id, { qty: ev.target.value })} />
                    : qty(x.ordered)}</td>
                  <td className="num">{editing && mode === "receive"
                    ? <span className="row" style={{ justifyContent: "flex-end" }}>
                        <input className="input num" style={{ width: 90 }} type="number" min={0} aria-label={`Receive quantity ${x.id}`} value={e.qty} onChange={(ev) => set(x.id, { qty: ev.target.value })} />
                        <label className="small row" title="Last delivery: close the line even if short"><input type="checkbox" checked={e.final} onChange={(ev) => set(x.id, { final: ev.target.checked })} />final</label></span>
                    : x.received ? qty(x.received) : ""}</td>
                  <td className="num">{x.closed ? "" : qty(x.open)}</td>
                  <td className="num">{editing && mode === "change"
                    ? <input className="input num" style={{ width: 80 }} type="number" min={0} step="any" aria-label={`Price ${x.id}`} value={e.price} onChange={(ev) => set(x.id, { price: ev.target.value })} />
                    : x.price != null ? unitMoney(x.price, po.currency) : "—"}</td>
                  <td>{editing && mode === "change"
                    ? <input type="date" className="input" aria-label={`Delivery date ${x.id}`} value={e.date} onChange={(ev) => set(x.id, { date: ev.target.value })} />
                    : day(x.due_date)}</td>
                  <td>{editing && mode === "confirm"
                    ? e.parts ? <span className="small">in {e.parts.length} deliveries, below</span>
                      : <span className="row" style={{ gap: 6 }}><input type="date" className="input" aria-label={`Confirmed date ${x.id}`} value={e.date} onChange={(ev) => set(x.id, { date: ev.target.value })} />
                        <button className="btn sm ghost" type="button" onClick={() => set(x.id, { parts: [{ date: e.date, qty: e.qty }, { date: e.date, qty: "0" }] })}>Several deliveries</button></span>
                    : (x.confirmations?.length ?? 0) > 1 ? <span className="small">{x.confirmations!.map((c) => `${qty(c.qty)} on ${day(c.date)}`).join(", ")}</span>
                    : x.confirmed_date ? <>{day(x.confirmed_date)}{x.confirmed_qty != null && x.confirmed_qty < x.ordered - 1e-6 && <span className="small"> · {qty(x.confirmed_qty)}</span>}</>
                    : x.confirmed_qty != null ? qty(x.confirmed_qty) : "—"}
                    {x.contract && <div className="faint small">contract {x.contract}</div>}</td>
                  <td><Badge sev={STATUS_SEV[x.status] ?? "info"}>{x.status}</Badge>{x.days_late > 0 && !x.closed && <span className="small"> {x.days_late} d</span>}
                    {x.last_receipt && <div className="faint small">last in {day(x.last_receipt)}</div>}</td>
                </tr>
                {editing && mode === "confirm" && e.parts && <tr className="sub"><td colSpan={10}>
                  <div className="row wrap" style={{ gap: 8 }}>
                    {e.parts.map((pt, i) => <span key={i} className="row" style={{ gap: 4 }}>
                      <input className="input num" style={{ width: 80 }} type="number" min={0} aria-label={`Delivery ${i + 1} quantity ${x.id}`} value={pt.qty}
                        onChange={(ev) => set(x.id, { parts: e.parts!.map((q, j) => (j === i ? { ...q, qty: ev.target.value } : q)) })} />
                      on <input type="date" className="input" aria-label={`Delivery ${i + 1} date ${x.id}`} value={pt.date}
                        onChange={(ev) => set(x.id, { parts: e.parts!.map((q, j) => (j === i ? { ...q, date: ev.target.value } : q)) })} />
                      {e.parts!.length > 2 && <button className="btn sm ghost" type="button" aria-label={`Remove delivery ${i + 1}`}
                        onClick={() => set(x.id, { parts: e.parts!.filter((_, j) => j !== i) })}>✕</button>}</span>)}
                    <button className="btn sm ghost" type="button" onClick={() => set(x.id, { parts: [...e.parts!, { date: e.parts![e.parts!.length - 1].date, qty: "0" }] })}>+ Another delivery</button>
                    <button className="btn sm ghost" type="button" onClick={() => set(x.id, { parts: null })}>One delivery</button>
                    <span className="small faint">{qty(e.parts.reduce((a, q) => a + Number(q.qty || 0), 0))} of {qty(x.ordered)} confirmed</span>
                  </div></td></tr>}
                {editing && mode === "receive" && traced && e.on && <tr className="sub"><td colSpan={10}>
                  <LotFields ds={ds} product={x.product} value={lots[x.id] ?? NO_LOT} receiving onChange={(v) => setLots({ ...lots, [x.id]: v })} /></td></tr>}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

const MODE_HINT: Record<Exclude<Mode, null>, string> = {
  confirm: "The date and quantity the supplier promised, or several deliveries. The plan expects each then, and counts no more than confirmed.",
  receive: "Posts a goods receipt per line. Stock and the order update when the plan moves past this date (Actuals → Start a new week).",
  change: "A new quantity or date needs a new confirmation from a supplier who confirms; an order that grows above the approval limit needs releasing again.",
  cancel: "Only lines nothing has been received for can be cancelled. The plan buys again what is still needed.",
};

// ------------------------------------------------------------------------------------------------
/** The order as a document: print it (or save it as PDF from the print dialog), download it, or start an e-mail. */
function PoDocButtons({ po, ds, onSent }: { po: PoView; ds: Dataset; onSent?: () => unknown }) {
  const file = `${po.id}.html`;
  const print = () => {
    const html = poDocument(po, ds);
    const w = window.open("", "_blank");
    if (!w) return download(file, html, "text/html");      // pop-ups blocked: the file instead
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 250);
  };
  const mail = poEmail(po, ds);
  const mailto = `mailto:${encodeURIComponent(mail.to)}?subject=${encodeURIComponent(mail.subject)}&body=${encodeURIComponent(mail.body)}`;
  const { missing } = poAddresses(po, ds);
  return <span className="row" style={{ gap: 6 }}>
    {missing.length > 0 && <span className="faint small" title="Printed on the order once filled in">No address yet for {missing.map((m, i) =>
      <span key={m.href}>{i ? (i === missing.length - 1 ? " and " : ", ") : ""}<a href={m.href}>{m.what}</a></span>)}</span>}
    <button className="btn sm ghost" onClick={print} title="Opens the order as a page and the print dialog, where it can be saved as PDF">Print or PDF</button>
    <button className="btn sm ghost" onClick={() => download(file, poDocument(po, ds), "text/html")}>Download</button>
    <a className="btn sm ghost" href={mailto} title={mail.to ? `An e-mail to ${mail.to} with the order in its text` : "An e-mail with the order in its text (no e-mail address on the supplier's purchasing data)"}>E-mail</a>
    <ServerSend kind={po.kind === "scheduling_agreement" ? "delivery_schedule" : "purchase_order"} docRef={po.id} to={mail.to} subject={mail.subject} text={mail.body} html={() => poDocument(po, ds)} onSent={onSent} />
  </span>;
}

function Suppliers({ res, ds }: { res: PurchasingView; ds: Dataset }) {
  const [open, setOpen] = useState<string | null>(null);
  if (res.vendors.length === 0) return <Panel><Empty title="No suppliers">Add a place of type supplier in <a href={href("setup")}>Set up</a>.</Empty></Panel>;
  return (
    <div className="stack">
      <Panel flush title="Suppliers" actions={<>
        <a className="btn sm ghost" href={href("data", "vendors")}>Edit purchasing data</a>
        <a className="btn sm ghost" href={href("data", "purchasing_sources")}>Edit sources and prices</a></>}>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Supplier</th><th>Buying</th><th className="num">Open lines</th><th className="num">Still to come</th><th className="num">Delivered lines</th>
              <th className="num">On time</th><th className="num">In full</th><th className="num">Avg late</th><th>Last delivery</th></tr></thead>
            <tbody>
              {res.vendors.map((v) => (
                <tr key={v.supplier} className={`clickable ${open === v.supplier ? "selected" : ""}`} onClick={() => setOpen(open === v.supplier ? null : v.supplier)}>
                  <td><b>{v.name}</b><div className="faint small">{v.supplier}</div></td>
                  <td>{v.blocked ? <Badge sev="error">blocked</Badge> : <Badge sev="ok">open</Badge>}
                    <span className="small"> {v.confirmation_required ? "confirms orders · " : ""}{v.terms || `${v.payment_terms_days} d terms`} · {v.info_records.length} source{v.info_records.length === 1 ? "" : "s"}</span></td>
                  <td className="num">{v.open_lines || ""}</td><td className="num">{v.open_value ? money(v.open_value, res.currency) : ""}</td>
                  <td className="num">{v.closed_lines || ""}</td>
                  <td className="num">{v.on_time != null ? pct(v.on_time, 0) : "—"}</td><td className="num">{v.in_full != null ? pct(v.in_full, 0) : "—"}</td>
                  <td className="num">{v.avg_days_late != null ? `${v.avg_days_late.toFixed(1)} d` : "—"}</td>
                  <td>{v.last_delivery ? day(v.last_delivery) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {open && <SupplierDetail v={res.vendors.find((x) => x.supplier === open)!} currency={res.currency} ds={ds} />}
      <Reading formula={<>On time: share of delivered lines fully in by their due date. In full: delivered within the tolerance
        ({pct(ds.execution?.delivery_tolerance ?? 0.02, 0)}, or the supplier's own).</>}
        soWhat="The score comes from lines closed by the roll-forward, so it grows as the weeks roll. Blocking a supplier keeps planning and new orders off it; its open orders are still received." />
    </div>
  );
}

function SupplierDetail({ v, currency, ds }: { v: VendorRow; currency: string; ds: Dataset }) {
  const { busy, run, banners } = usePoAction();
  const [until, setUntil] = useState("");
  const [target, setTarget] = useState("");
  const agreements = (ds.purchase_orders ?? []).filter((p) => p.kind === "scheduling_agreement" && p.supplier === v.supplier);
  const recordIndex = (ds.vendors ?? []).findIndex((x) => x.supplier === v.supplier);
  const toggleBlock = () => store.update((d) => {
    const list = [...(d.vendors ?? [])];
    const i = list.findIndex((x) => x.supplier === v.supplier);
    if (i >= 0) list[i] = { ...list[i], blocked: !list[i].blocked };
    else list.push({ supplier: v.supplier, blocked: true } as NonNullable<Dataset["vendors"]>[number]);
    d.vendors = list;
  });
  return (
    <Panel title={<h3>{v.name} {v.blocked && <Badge sev="error">blocked{v.block_reason ? `: ${v.block_reason}` : ""}</Badge>}</h3>}
      actions={<>
        <Edits><button className="btn sm" onClick={toggleBlock}>{v.blocked ? "Lift the purchasing block" : "Block for purchasing"}</button></Edits>
        <a className="btn sm ghost" href={href("data", "vendors", recordIndex >= 0 ? v.supplier : undefined)}>{v.has_record ? "Edit purchasing data" : "Add purchasing data"}</a></>}>
      <div className="row wrap small muted" style={{ gap: 16, marginBottom: 10 }}>
        <span>{v.confirmation_required ? "Confirms every order" : "Does not confirm orders"}</span>
        <span>{(() => { const t = (ds.payment_terms ?? []).find((x) => x.id === (ds.vendors ?? []).find((y) => y.supplier === v.supplier)?.payment_terms);
          return t ? `We pay on ${t.name || t.id}` : `We pay in ${v.payment_terms_days} days`; })()}</span><span>Orders in {v.currency}</span>
        {v.confirmed_late > 0 && <span>{plural(v.confirmed_late, "line")} confirmed later than asked</span>}
      </div>
      {v.info_records.length === 0 ? <Empty title="Sells nothing yet">Add a purchasing source for this supplier.</Empty> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Source</th><th>Product</th><th>To</th><th className="num">Price</th><th>Price scales</th><th className="num">Min</th>
              <th className="num">Lead time</th><th>Valid</th><th>Source list</th><th>Scheduling agreement</th></tr></thead>
            <tbody>
              {v.info_records.map((r) => (
                <tr key={r.source_id}>
                  <td><b>{r.source_id}</b>{r.vendor_material && <div className="faint small">their no. {r.vendor_material}</div>}</td>
                  <td><Prod id={r.product} /></td><td><Loc id={r.location} /></td>
                  <td className="num">{unitMoney(r.price, r.currency)}</td>
                  <td className="small">{r.price_scales.length ? r.price_scales.map((s) => `from ${qty(s.from_qty)}: ${unitMoney(s.price, r.currency)}`).join(" · ") : "—"}</td>
                  <td className="num">{r.moq ? qty(r.moq) : ""}{r.rounding_qty ? <span className="faint small"> ×{qty(r.rounding_qty)}</span> : ""}</td>
                  <td className="num">{qty(r.lead_time_days)} d</td>
                  <td className="small">{r.valid_from || r.valid_to ? `${r.valid_from ? day(r.valid_from) : "…"} – ${r.valid_to ? day(r.valid_to) : "…"}` : "always"}</td>
                  <td>{r.blocked ? <Badge sev="error">blocked</Badge> : r.fixed ? <Badge sev="ok">fixed</Badge> : <span className="small">priority {r.priority}{r.quota != null ? ` · quota ${pct(r.quota, 0)}` : ""}</span>}</td>
                  <td>{(() => {
                    const sa = agreements.find((p) => p.product === r.product && p.location === r.location);
                    return sa ? <a href={href("buying", "orders", sa.id)}>{sa.id}</a> : !r.blocked && !v.blocked && <Edits>
                      <button className="btn sm ghost" disabled={busy} onClick={() => run("create_agreement", "", { supplier: v.supplier, location: r.location,
                        product: r.product, valid_to: until || null, qty: target === "" ? null : Number(target), date: ds.settings.planning_start })}>Make one</button></Edits>;
                  })()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {banners}
      {v.info_records.length > 0 && <Edits><div className="row wrap small" style={{ gap: 10, marginTop: 8 }}>
        <span className="muted">A new scheduling agreement runs</span>
        <label className="row">until <input type="date" className="input" value={until} aria-label="Scheduling agreement until" onChange={(e) => setUntil(e.target.value)} /></label>
        <label className="row">for <input className="input num" style={{ width: 90 }} type="number" min={0} aria-label="Scheduling agreement quantity" value={target}
          placeholder="any" onChange={(e) => setTarget(e.target.value)} /></label>
        <span className="faint">Planning's purchases of that product then become delivery schedule lines on it, sent as one schedule.</span>
      </div></Edits>}
      <p className="faint small" style={{ marginTop: 8 }}>{currency !== v.currency ? `Values in ${currency}; prices in the source's currency.` : ""}</p>
    </Panel>
  );
}
