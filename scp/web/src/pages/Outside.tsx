// Enterprise 7.1: work done by suppliers outside our walls (S/4 guide §16.3 third-party orders, §10.1
// subcontracting). Drop-ship: a sale the supplier ships straight to the customer, billed from their dispatch advice
// and matched against their invoice. Job work: a production order's parts sent to a job worker on a GST delivery
// challan, held there until the processed goods come back, with the one-year limit and the ITC-04 return.
// Engine: scp/dropship, scp/jobwork.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ChallanRow, Dataset, OutsideAction, OutsideActionInput, OutsideView, ThirdPartyRow } from "../api/types";
import { Badge, Edits, Empty, Panel, StageHeader, StatTile, Tabs } from "../components/ui";
import { challanDocument } from "../lib/challandoc";
import { day, exactMoney, money, plural, qty } from "../lib/format";
import { Msg, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { download, toCsv } from "../lib/tabular";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { store, useStore } from "../state/store";

type View = "jobwork" | "dropship" | "itc04";
type Sev = "info" | "warning" | "ok" | "error";

const CHALLAN: Record<string, Sev> = { "at job worker": "info", "due soon": "warning", overdue: "error", closed: "ok", cancelled: "error" };
const ORDER: Record<string, Sev> = {
  "to send": "warning", sent: "info", "partly dispatched": "info", dispatched: "ok", billed: "ok", cancelled: "error",
};

function useOutside(ds: Dataset) {
  const [v, setV] = useState<OutsideView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.outside(ds).then((x) => { if (live) { setV(x); setErr(null); } }, (e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [ds]);
  return { v, err };
}

function useStep() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: OutsideAction, extra: Partial<OutsideActionInput> = {}, after?: () => void) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const before = store.get().dataset!;
      const out = await api.outsideAct(before, action, extra);
      store.replace(out.dataset, before);
      setMsg(out.message);
      after?.();
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };
  const banners = <>
    {msg && <div className="banner info" role="status"><Badge sev="ok">Done</Badge><span><Msg text={msg} /></span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
    {err && <div className="banner error" role="alert"><Badge sev="error">Not done</Badge><span>{err}</span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setErr(null)}>✕</button></div>}
  </>;
  return { busy, run, banners };
}
type Step = ReturnType<typeof useStep>;

export function Outside({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const view = (route[1] as View) || "jobwork";
  const { v, err } = useOutside(ds);
  const step = useStep();
  const cur = ds.settings.currency;
  const open = v?.job_work.challans.filter((c) => !["closed", "cancelled"].includes(c.status)) ?? [];
  const live = v?.drop_ship.orders.filter((o) => ["to send", "sent", "partly dispatched"].includes(o.status)) ?? [];
  const head = <StageHeader title="Job work & drop-ship" kicker="What suppliers make or ship for us outside our walls."
    how={<>A <b>job-work challan</b> sends a production order's parts to a job worker: they leave the plant as issues to
      the order (so its backflush does not take them again) and are stock at the job worker, at their planned value,
      until the goods come back. What the bill of materials says the goods took is used up there; parts back unused
      are stock here again. Inputs must be back within {ds.job_work?.inputs_days ?? 365} days, capital goods within {ds.job_work?.capital_goods_days ?? 1095}:
      what is not counts as supplied to the job worker on the day it was sent, and tax is due on its value. A
      <b> third-party order</b> is bought from a supplier who ships it straight to the customer: planning never sees
      it; each dispatch they advise is billed to the customer on Selling, and their invoice is matched against what
      they dispatched on Buying.</>}
    answer={v ? <>{open.length ? `${plural(open.length, "challan")} open, ${money(v.job_work.value_out, cur)} at job workers` : "Nothing at job workers"}
      {v.job_work.deemed.length ? `; tax of ${money(v.job_work.deemed_tax, cur)} due on parts past the limit` : ""};
      {" "}{live.length ? `${plural(live.length, "third-party order")} open (${money(v.drop_ship.open_value, cur)} to dispatch)` : "no third-party orders open"}.</> : undefined} />;
  return (
    <div>{head}<div className="content stack">
      <Tabs<View> value={view} onChange={(x) => go("outside", x)} tabs={[
        { id: "jobwork", label: "Job work", count: open.length || undefined },
        { id: "dropship", label: "Drop-ship", count: live.length || undefined },
        { id: "itc04", label: "ITC-04", count: v?.job_work.itc04.length || undefined },
      ]} />
      {err && <div className="banner error" role="alert"><Badge sev="error">Could not read the work outside</Badge>{err}</div>}
      {step.banners}
      {!v && !err && <p className="faint">Reading the challans and orders…</p>}
      {v && view === "jobwork" && <JobWork ds={ds} v={v} step={step} />}
      {v && view === "dropship" && <DropShip ds={ds} v={v} step={step} />}
      {v && view === "itc04" && <Itc04 ds={ds} v={v} />}
    </div></div>
  );
}

// ------------------------------------------------------------------------------------------------ job work
function suppliers(ds: Dataset) {
  return (ds.locations ?? []).filter((l) => l.type === "supplier");
}

function SendParts({ ds, v, step }: { ds: Dataset; v: OutsideView; step: Step }) {
  const nm = useNames();
  const orders = (ds.receipts ?? []).filter((r) => r.kind === "production");
  const suggested = v.job_work.to_send;
  const [order, setOrder] = useState(suggested[0]?.order ?? orders[0]?.id ?? "");
  const hint = suggested.find((x) => x.order === order);
  const [worker, setWorker] = useState(hint?.job_worker ?? "");
  const [charge, setCharge] = useState("");
  const [vehicle, setVehicle] = useState("");
  const [parts, setParts] = useState<{ product: string; qty: number; location: string }[] | null>(null);
  const [partsErr, setPartsErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setParts(null); setPartsErr(null);
    if (!order) return;
    api.outsideParts(ds, order).then((x) => live && setParts(x), (e) => live && setPartsErr(String(e).replace(/^Error:\s*/, "")));
    return () => { live = false; };
  }, [ds, order]);
  useEffect(() => { if (hint?.job_worker) setWorker(hint.job_worker); }, [hint?.job_worker]);
  if (!orders.length) return <Panel title="Send parts to a job worker"><Empty title="No open production orders">
    Parts go out for a production order. Make one firm on the <a href={href("plan")}>supply plan</a>.</Empty></Panel>;
  const rc = orders.find((r) => r.id === order);
  return <Panel title="Send parts to a job worker">
    <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
      <label className="field"><span className="label">Production order</span>
        <select value={order} onChange={(e) => setOrder(e.target.value)} aria-label="Production order">
          {orders.map((r) => <option key={r.id} value={r.id}>{r.id} · {qty(r.qty)} {nm.prod(r.product)}</option>)}</select></label>
      <label className="field"><span className="label">Job worker</span>
        <select value={worker} onChange={(e) => setWorker(e.target.value)} aria-label="Job worker">
          <option value="">{hint?.job_worker ? "The routing's" : "Choose…"}</option>
          {suppliers(ds).map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></label>
      <label className="field"><span className="label">Job charge per unit</span>
        <input className="input num" type="number" min={0} step="any" style={{ width: 110 }} value={charge} placeholder={hint ? String(hint.charge) : "0"}
          onChange={(e) => setCharge(e.target.value)} aria-label="Job charge per unit" /></label>
      <label className="field"><span className="label">Vehicle</span>
        <input className="input" maxLength={40} style={{ width: 130 }} value={vehicle} placeholder="MH12 AB 1234"
          onChange={(e) => setVehicle(e.target.value)} aria-label="Vehicle" /></label>
    </div>
    {partsErr && <div className="banner warning" style={{ marginTop: 10 }}><Badge sev="warning">Nothing to send</Badge>{partsErr}</div>}
    {parts && parts.length > 0 && <div className="table-wrap" style={{ marginTop: 10 }}><table className="t" aria-label="Parts to send">
      <thead><tr><th>Part</th><th>From</th><th className="num">Quantity</th></tr></thead>
      <tbody>{parts.map((p, i) => <tr key={p.product}><td>{nm.prod(p.product)}</td><td>{nm.loc(p.location)}</td>
        <td className="num"><Edits><input className="input num" type="number" min={0} step="any" style={{ width: 110 }} value={p.qty}
          aria-label={`Send ${p.product}`} onChange={(e) => setParts(parts.map((x, j) => j === i ? { ...x, qty: Number(e.target.value) } : x))} /></Edits>
          {" "}{(ds.products ?? []).find((x) => x.id === p.product)?.base_uom ?? ""}</td></tr>)}</tbody>
    </table></div>}
    <p className="faint small">What the bill of materials needs for the {rc ? qty(rc.qty) : ""} still to make, less what is at job workers
      already; parts counted in whole units are rounded up. They leave {rc ? nm.loc(rc.location) : "the plant"} on the challan and stay the order's.</p>
    <Edits><button className="btn accent" disabled={step.busy || !parts?.length || (!worker && !hint?.job_worker)}
      onClick={() => step.run("send_parts", {
        production_order: order, supplier: worker || null, vehicle, charge: charge === "" ? null : Number(charge),
        parts: (parts ?? []).filter((p) => p.qty > 0).map((p) => ({ product: p.product, qty: p.qty, capital_goods: false })),
      }, () => { setVehicle(""); setCharge(""); })}>Send on a challan</button></Edits>
  </Panel>;
}

function printChallan(c: ChallanRow, ds: Dataset) {
  const html = challanDocument(c, ds);
  const w = window.open("", "_blank");
  if (!w) return download(`${c.id}.html`, html, "text/html");
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 250);
}

function ChallanActions({ c, step }: { c: ChallanRow; step: Step }) {
  const [n, setN] = useState("");
  const [ref, setRef] = useState("");
  const out = c.lines.filter((l) => l.at_job_worker > 1e-6);
  const [part, setPart] = useState(out[0]?.product ?? "");
  const [pq, setPq] = useState("");
  if (["closed", "cancelled"].includes(c.status)) return null;
  const id = c.id;
  return <Edits><div className="stack" style={{ gap: 6 }}>
    {c.order_open && <div className="row wrap" style={{ gap: 4 }}>
      <input className="input num" style={{ width: 80 }} type="number" min={0} step="any" placeholder="qty" aria-label={`Back processed ${id}`}
        value={n} onChange={(e) => setN(e.target.value)} />
      <input className="input" style={{ width: 90 }} placeholder="their no." maxLength={64} aria-label={`Their challan ${id}`}
        value={ref} onChange={(e) => setRef(e.target.value)} />
      <button className="btn sm accent" disabled={step.busy || !(Number(n) > 0)} aria-label={`Goods back ${id}`}
        onClick={() => step.run("back_processed", { id, qty: Number(n), reference: ref }, () => { setN(""); setRef(""); })}>Goods back</button>
    </div>}
    {out.length > 0 && <div className="row wrap" style={{ gap: 4 }}>
      <select value={part} onChange={(e) => setPart(e.target.value)} aria-label={`Part of ${id}`}>
        {out.map((l) => <option key={l.product} value={l.product}>{l.product_name}</option>)}</select>
      <input className="input num" style={{ width: 70 }} type="number" min={0} step="any" placeholder="all" aria-label={`Part quantity ${id}`}
        value={pq} onChange={(e) => setPq(e.target.value)} />
      <button className="btn sm" disabled={step.busy} aria-label={`Back unused ${id}`}
        onClick={() => step.run("back_unused", { id, product: part, qty: pq === "" ? null : Number(pq), reference: ref }, () => setPq(""))}>Back unused</button>
      <button className="btn sm ghost" disabled={step.busy} aria-label={`Write off ${id}`}
        onClick={() => step.run("write_off", { id, product: part, qty: pq === "" ? null : Number(pq) }, () => setPq(""))}>Write off</button>
    </div>}
    {c.returns.length === 0 && <button className="btn sm ghost" disabled={step.busy} aria-label={`Cancel ${id}`}
      onClick={() => step.run("cancel_challan", { id })}>Cancel challan</button>}
  </div></Edits>;
}

function JobWork({ ds, v, step }: { ds: Dataset; v: OutsideView; step: Step }) {
  const nm = useNames();
  const cur = v.job_work.currency;
  const j = v.job_work;
  const soon = j.challans.filter((c) => c.status === "due soon");
  return <>
    {j.deemed.length > 0 && <div className="banner error" role="alert"><Badge sev="error">Past the GST limit</Badge>
      <span>{j.deemed.map((d) => `${qty(d.qty)} ${d.product_name} on ${d.challan} (sent ${day(d.sent_on)})`).join("; ")}: they count as supplied to
        the job worker on the day they were sent. Tax due {exactMoney(j.deemed_tax, cur)}; get them back or write them off.</span></div>}
    {soon.length > 0 && <div className="banner warning"><Badge sev="warning">Due back soon</Badge>
      <span>{soon.map((c) => `${c.id} by ${day(c.due)} (${c.days_left} days)`).join("; ")}.</span></div>}
    <div className="grid-auto">
      <StatTile label="At job workers" value={money(j.value_out, cur)} sub={plural(j.stock.length, "part")} tone="ink" />
      <StatTile label="Challans open" value={qty(j.challans.filter((c) => !["closed", "cancelled"].includes(c.status)).length)}
        sub={`${plural(j.challans.length, "challan")} in all`} />
      <StatTile label="Tax on overdue parts" value={money(j.deemed_tax, cur)} sub="treated as supplied" tone={j.deemed_tax > 0 ? "hl" : undefined} />
    </div>
    {j.to_send.length > 0 && <Panel flush title="Production orders with work done outside">
      <div className="table-wrap"><table className="t" aria-label="Orders to send">
        <thead><tr><th>Order</th><th>Makes</th><th>Starts</th><th>Job worker</th><th>Parts still to send</th><th>On challans</th></tr></thead>
        <tbody>{j.to_send.map((o) => <tr key={o.order}><td><b>{o.order}</b></td><td>{qty(o.qty)} {o.product_name}</td><td>{day(o.start)}</td>
          <td>{o.job_worker_name || <span className="faint">not in the routing</span>}</td>
          <td className="small">{o.parts.map((p) => `${qty(p.qty as number)} ${nm.prod(String(p.product))}`).join(", ")}</td>
          <td>{o.on_challans.join(", ") || "—"}</td></tr>)}</tbody>
      </table></div></Panel>}
    <SendParts key={v.job_work.as_of} ds={ds} v={v} step={step} />
    <Panel flush title="Challans, latest first">
      {j.challans.length === 0 ? <Empty title="No challans yet">Send a production order's parts to a job worker above.</Empty> :
        <div className="table-wrap"><table className="t" aria-label="Challans">
          <thead><tr><th>Challan</th><th>Job worker</th><th>For</th><th>Parts: sent · used · back · lost · there</th>
            <th className="num">Value there</th><th>Back by</th><th>Status</th><th>Next</th></tr></thead>
          <tbody>{j.challans.map((c) => <tr key={c.id}>
            <td><b>{c.id}</b><div className="faint small">{day(c.sent_on)}{c.vehicle ? ` · ${c.vehicle}` : ""}</div>
              <button className="btn sm ghost" onClick={() => printChallan(c, ds)} aria-label={`Print ${c.id}`}
                title="The challan in three copies: original, duplicate, triplicate">Print challan</button></td>
            <td>{c.job_worker_name}<div className="faint small">{c.job_worker_gstin ? `GSTIN ${c.job_worker_gstin}` : "no GSTIN"}</div></td>
            <td>{c.order}<div className="faint small">{c.order_product_name}{c.processed ? ` · ${qty(c.processed)} back` : ""}</div></td>
            <td className="small">{c.lines.map((l) => <div key={l.product}>{l.product_name}: {qty(l.qty)} · {qty(l.used)} · {qty(l.unused)} · {qty(l.lost)} · <b>{qty(l.at_job_worker)}</b> {l.unit.toLowerCase()}
              {l.capital_goods && <span className="faint"> (capital goods)</span>}</div>)}</td>
            <td className="num">{exactMoney(c.value_out, cur)}</td>
            <td>{c.due ? <>{day(c.due)}<div className="faint small">{c.days_left! >= 0 ? `${c.days_left} days left` : `${-c.days_left!} days over`}</div></> : "—"}</td>
            <td><Badge sev={CHALLAN[c.status]}>{c.status}</Badge></td>
            <td><ChallanActions c={c} step={step} /></td>
          </tr>)}</tbody>
        </table></div>}
    </Panel>
    <Panel flush title="Stock at job workers">
      {j.stock.length === 0 ? <Empty title="Nothing at job workers" /> : <div className="table-wrap"><table className="t" aria-label="Stock at job workers">
        <thead><tr><th>Job worker</th><th>Part</th><th className="num">Quantity</th><th className="num">Value</th><th>Challans</th><th>First due back</th></tr></thead>
        <tbody>{j.stock.map((s) => <tr key={`${s.job_worker}|${s.product}`}><td>{s.job_worker_name}</td><td>{s.product_name}</td>
          <td className="num">{qty(s.qty)} {s.unit.toLowerCase()}</td><td className="num">{exactMoney(s.value, cur)}</td>
          <td>{s.challans.join(", ")}</td><td>{day(s.first_due)}</td></tr>)}</tbody>
      </table></div>}
    </Panel>
    <Panel title="Job-work limits">
      <SchemaForm defName="JobWorkSettings" value={(ds.job_work ?? {}) as unknown as Obj}
        onChange={(next) => store.update((d) => { d.job_work = next as unknown as Dataset["job_work"]; })} />
    </Panel>
  </>;
}

// ------------------------------------------------------------------------------------------------ drop-ship
function NewOrder({ ds, step }: { ds: Dataset; step: Step }) {
  const customers = (ds.locations ?? []).filter((l) => l.type === "customer");
  const sups = suppliers(ds);
  const [customer, setCustomer] = useState(customers[0]?.id ?? "");
  const [product, setProduct] = useState((ds.products ?? []).find((p) => p.type === "FG")?.id ?? ds.products?.[0]?.id ?? "");
  const [supplier, setSupplier] = useState(sups[0]?.id ?? "");
  const [n, setN] = useState("");
  const [wanted, setWanted] = useState(ds.settings.planning_start);
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [ref, setRef] = useState("");
  if (!customers.length || !sups.length) return <Panel title="New third-party order"><Empty title="Customers and suppliers first">
    A third-party order needs a customer and a supplier who ships to them: add them in <a href={href("setup")}>Set up</a>.</Empty></Panel>;
  return <Panel title="New third-party order">
    <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
      <label className="field"><span className="label">Customer</span>
        <select value={customer} onChange={(e) => setCustomer(e.target.value)} aria-label="Customer">
          {customers.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></label>
      <label className="field"><span className="label">Product</span>
        <select value={product} onChange={(e) => setProduct(e.target.value)} aria-label="Product">
          {(ds.products ?? []).map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}</select></label>
      <label className="field"><span className="label">Quantity</span>
        <input className="input num" type="number" min={0} step="any" style={{ width: 90 }} value={n} onChange={(e) => setN(e.target.value)} aria-label="Quantity" /></label>
      <label className="field"><span className="label">Wanted by</span>
        <input className="input" type="date" value={wanted} onChange={(e) => setWanted(e.target.value)} aria-label="Wanted by" /></label>
      <label className="field"><span className="label">Shipped by</span>
        <select value={supplier} onChange={(e) => setSupplier(e.target.value)} aria-label="Shipped by">
          {sups.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></label>
      <label className="field"><span className="label">Sale price</span>
        <input className="input num" type="number" min={0} step="any" style={{ width: 100 }} value={price} placeholder="customer's"
          onChange={(e) => setPrice(e.target.value)} aria-label="Sale price" /></label>
      <label className="field"><span className="label">Purchase price</span>
        <input className="input num" type="number" min={0} step="any" style={{ width: 100 }} value={cost} placeholder="supplier's"
          onChange={(e) => setCost(e.target.value)} aria-label="Purchase price" /></label>
      <label className="field"><span className="label">Their order number</span>
        <input className="input" maxLength={64} style={{ width: 130 }} value={ref} onChange={(e) => setRef(e.target.value)} aria-label="Their order number" /></label>
    </div>
    <p className="faint small">The sale price comes from the customer's price, else the product's; the purchase price from the supplier's
      purchasing source, else type it. Nothing is planned or reserved at our places: the supplier ships it straight to the customer.</p>
    <Edits><button className="btn accent" disabled={step.busy || !(Number(n) > 0) || !wanted}
      onClick={() => step.run("order", { customer, product, supplier, qty: Number(n), wanted, customer_ref: ref,
        price: price === "" ? null : Number(price), cost: cost === "" ? null : Number(cost) }, () => { setN(""); setRef(""); })}>Take the order</button></Edits>
  </Panel>;
}

function DispatchActions({ o, step }: { o: ThirdPartyRow; step: Step }) {
  const [n, setN] = useState("");
  const [ref, setRef] = useState("");
  const [fin, setFin] = useState(false);
  const id = o.id;
  if (o.status === "to send") return <Edits><div className="row wrap" style={{ gap: 4 }}>
    <button className="btn sm accent" disabled={step.busy} aria-label={`Send ${id}`} onClick={() => step.run("send_order", { id })}>Sent to supplier</button>
    <button className="btn sm ghost" disabled={step.busy} aria-label={`Cancel ${id}`} onClick={() => step.run("cancel_order", { id })}>Cancel</button></div></Edits>;
  if (o.status === "sent" || o.status === "partly dispatched") return <Edits><div className="row wrap" style={{ gap: 4 }}>
    <input className="input num" style={{ width: 80 }} type="number" min={0} step="any" placeholder={qty(o.qty - o.shipped)} aria-label={`Dispatched ${id}`}
      value={n} onChange={(e) => setN(e.target.value)} />
    <input className="input" style={{ width: 90 }} placeholder="their LR no." maxLength={64} aria-label={`Dispatch note ${id}`} value={ref} onChange={(e) => setRef(e.target.value)} />
    <label className="row small" style={{ gap: 4 }}><input type="checkbox" checked={fin} onChange={(e) => setFin(e.target.checked)} aria-label={`Last dispatch ${id}`} />last</label>
    <button className="btn sm accent" disabled={step.busy} aria-label={`Dispatch ${id}`}
      onClick={() => step.run("dispatch", { id, qty: n === "" ? null : Number(n), reference: ref, final: fin }, () => { setN(""); setRef(""); setFin(false); })}>Dispatched</button>
    {o.status === "sent" && <button className="btn sm ghost" disabled={step.busy} aria-label={`Cancel ${id}`} onClick={() => step.run("cancel_order", { id })}>Cancel</button>}
  </div></Edits>;
  return null;
}

function DropShip({ ds, v, step }: { ds: Dataset; v: OutsideView; step: Step }) {
  const cur = v.job_work.currency;
  const d = v.drop_ship;
  const toBill = d.orders.filter((o) => o.shipped > o.billed + 1e-6);
  const toMatch = d.orders.filter((o) => o.shipped > o.supplier_invoiced + 1e-6);
  return <>
    <div className="grid-auto">
      <StatTile label="To dispatch" value={money(d.open_value, cur)} sub="at the sale price" tone="ink" />
      <StatTile label="Margin" value={money(d.margin, cur)} sub="on every order not cancelled" />
      <StatTile label="To bill" value={plural(toBill.length, "order")} sub={toBill.length ? "dispatched, not invoiced" : "all billed"} />
    </div>
    {toBill.length > 0 && <div className="banner info"><Badge sev="info">Bill them</Badge>
      <span>{toBill.map((o) => `${o.id}: ${qty(o.shipped - o.billed)} dispatched`).join("; ")}. Invoice them on <a href={href("selling", "bill")}>Selling</a>
        {toMatch.length ? <>; enter the supplier's invoice on <a href={href("buying", "invoices")}>Buying</a></> : ""}.</span></div>}
    <NewOrder ds={ds} step={step} />
    <Panel flush title="Third-party orders, latest first">
      {d.orders.length === 0 ? <Empty title="No third-party orders yet">Take one above.</Empty> :
        <div className="table-wrap"><table className="t" aria-label="Third-party orders">
          <thead><tr><th>Order</th><th>Customer</th><th>Product</th><th>Shipped by</th><th className="num">Quantity</th><th>Wanted</th>
            <th className="num">Sale · purchase</th><th className="num">Margin</th><th className="num">Dispatched · billed · their invoice</th><th>Status</th><th>Next</th></tr></thead>
          <tbody>{d.orders.map((o) => <tr key={o.id}>
            <td><b>{o.id}</b>{o.customer_ref && <div className="faint small">their {o.customer_ref}</div>}</td>
            <td>{o.customer_name}</td><td>{o.product_name}</td><td>{o.supplier_name}</td><td className="num">{qty(o.qty)}</td>
            <td>{day(o.date)}{o.late && <div><Badge sev="warning">late</Badge></div>}</td>
            <td className="num">{exactMoney(o.price, cur)}<div className="faint small">{exactMoney(o.cost, o.currency)}</div></td>
            <td className="num">{o.margin != null ? exactMoney(o.margin, cur) : "—"}</td>
            <td className="num">{qty(o.shipped)} · {qty(o.billed)} · {qty(o.supplier_invoiced)}
              {o.shipments.length > 0 && <div className="faint small">{o.shipments.map((s) => `${day(s.date)} ${qty(s.qty)}${s.reference ? ` (${s.reference})` : ""}`).join(", ")}</div>}</td>
            <td><Badge sev={ORDER[o.status]}>{o.status}</Badge></td>
            <td><DispatchActions o={o} step={step} /></td>
          </tr>)}</tbody>
        </table></div>}
    </Panel>
  </>;
}

// ------------------------------------------------------------------------------------------------ ITC-04
function Itc04({ ds, v }: { ds: Dataset; v: OutsideView }) {
  const cur = v.job_work.currency;
  const j = v.job_work;
  const sent = j.itc04.filter((x) => x.table === "4");
  const back = j.itc04.filter((x) => x.table === "5A");
  const csv = useMemo(() => toCsv([
    ["Table", "Challan", "Date", "Job worker GSTIN", "State", "Job worker's challan", "Description", "HSN", "UQC", "Quantity", "Taxable value", "Type of goods"],
    ...j.itc04.map((x) => [x.table, x.challan, x.date, x.job_worker_gstin, x.job_worker_state, x.their_challan, x.description, x.hsn, x.uqc, x.qty, x.value, x.goods]),
  ]), [j.itc04]);
  const missing = j.itc04.filter((x) => !x.hsn || !x.job_worker_gstin);
  const table = (rows: typeof sent, title: string, label: string, valued: boolean) => <Panel flush title={title}>
    {rows.length === 0 ? <Empty title="Nothing in this period" /> : <div className="table-wrap"><table className="t" aria-label={label}>
      <thead><tr><th>Challan</th><th>Date</th><th>Job worker GSTIN</th><th>State</th>{!valued && <th>Their challan</th>}<th>Goods</th><th>HSN</th>
        <th>UQC</th><th className="num">Quantity</th>{valued && <th className="num">Taxable value</th>}<th>Type</th></tr></thead>
      <tbody>{rows.map((x, i) => <tr key={`${x.challan}|${x.product}|${i}`}><td>{x.challan}</td><td>{day(x.date)}</td><td>{x.job_worker_gstin || "—"}</td>
        <td>{x.job_worker_state || "—"}</td>{!valued && <td>{x.their_challan || "—"}</td>}<td>{x.description}</td><td>{x.hsn || "—"}</td><td>{x.uqc}</td>
        <td className="num">{qty(x.qty)}</td>{valued && <td className="num">{x.value != null ? exactMoney(x.value, cur) : "—"}</td>}<td>{x.goods}</td></tr>)}</tbody>
    </table></div>}
  </Panel>;
  return <>
    <Panel title={`ITC-04 for ${j.period}`} actions={<button className="btn sm" disabled={!j.itc04.length}
      onClick={() => download(`ITC-04 ${j.period}.csv`, csv)}>Download for the return</button>}>
      <p className="small">What went to job workers and what came back from {day(j.period_start)} to {day(j.period_end)}, the half
        year the return is filed for{j.company_gstin ? `, under GSTIN ${j.company_gstin}` : ""}. Parts written off are not returns: they are
        supplies to the job worker.</p>
      {missing.length > 0 && <div className="banner warning"><Badge sev="warning">Fill in</Badge><span>
        {[...new Set(missing.map((x) => !x.hsn ? `the HSN code of ${x.description}` : `the GSTIN of ${(ds.locations ?? []).find((l) => l.id === x.job_worker)?.name ?? x.job_worker}`))].join("; ")}
        {" "}in <a href={href("data")}>master data</a>.</span></div>}
    </Panel>
    {table(sent, "Table 4: sent to job workers", "Sent to job workers", true)}
    {table(back, "Table 5A: back from job workers", "Back from job workers", false)}
  </>;
}
