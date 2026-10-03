// Phase N on the Buying page: supplier invoices checked against the order and the goods received, what is owed to
// whom, returns to suppliers and contracts. Every step is an engine action (/api/purchasing/act).
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, PoAction, PoActionInput, PurchasingView, StockType, SupplierInvoiceView } from "../api/types";
import { Badge, Edits, Empty, Panel, Reading, StatTile } from "../components/ui";
import { day, exactMoney, qty, unitMoney } from "../lib/format";
import { Loc, Msg, Prod, namesOf } from "../lib/names";
import { go, href } from "../lib/router";
import { store } from "../state/store";

type Sev = "error" | "warning" | "info" | "ok";
const INV_SEV: Record<string, Sev> = {
  blocked: "error", released: "info", "to pay": "info", paid: "ok", cancelled: "warning", "credit open": "info", credited: "ok",
};
const RET_SEV: Record<string, Sev> = { "to credit": "warning", credited: "ok", "replacement due": "info", replaced: "ok" };
const CON_SEV: Record<string, Sev> = { active: "ok", "not started": "info", expired: "warning", "used up": "warning" };

/** Run a purchasing step on the company, then list buying and plan again. */
export async function poAct(action: PoAction, po: string, extra: PoActionInput = {}) {
  const before = store.get().dataset!;
  const out = await api.poAction(before, action, po, extra);
  store.replace(out.dataset, before);
  await Promise.all([store.run("purchasing"), store.run("plan")]);
  return out;
}

export function usePoAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: PoAction, po: string, extra: PoActionInput = {}, after?: () => void) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const out = await poAct(action, po, extra);
      setMsg(out.report.message);
      after?.();
      return out;
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
      return null;
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

const round2 = (v: number) => Math.round(v * 100) / 100;

// ---- supplier invoices --------------------------------------------------------------------------------------
export function Invoices({ res, ds, sel, po }: { res: PurchasingView; ds: Dataset; sel?: string; po?: string }) {
  const pay = res.payables!;
  const nm = namesOf(ds);
  const waiting = pay.to_invoice.filter((g) => g.qty > 1e-6);
  const [pick, setPick] = useState<Set<string> | null>(null);
  const chosen = pick ?? new Set(waiting.filter((g) => !po || g.po === po).map((g) => g.order));
  const picked = waiting.filter((g) => chosen.has(g.order));
  const suppliers = new Set(picked.map((g) => g.supplier));
  const [edit, setEdit] = useState<Record<string, { qty: string; price: string }>>({});
  const [ref, setRef] = useState("");
  const [on, setOn] = useState(ds.settings.planning_start);
  const [tax, setTax] = useState("");
  const { busy, run, banners } = usePoAction();
  const line = (o: string) => edit[o] ?? { qty: "", price: "" };
  const net = picked.reduce((a, g) => a + Number(line(g.order).qty || g.qty) * Number(line(g.order).price || g.price || 0), 0);
  const supplier = suppliers.size === 1 ? [...suppliers][0] : null;
  const vendor = (ds.vendors ?? []).find((v) => v.supplier === supplier);
  const rate = vendor?.tax_rate ?? ds.purchasing?.tax_rate ?? 0;
  const toggle = (o: string) => { const n = new Set(chosen); if (n.has(o)) n.delete(o); else n.add(o); setPick(n); };
  const enter = () => run("enter_invoice", "", {
    supplier, date: on, reference: ref, tax: tax === "" ? null : Number(tax),
    lines: picked.map((g) => ({ id: g.order, order: g.order, final: false, qty: Number(line(g.order).qty || g.qty),
      price: line(g.order).price === "" ? null : Number(line(g.order).price) })),
  }, () => { setPick(null); setEdit({}); setRef(""); setTax(""); });
  const cur = pay.invoices.find((i) => i.id === sel);
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="We owe" value={exactMoney(pay.open_value, res.currency)} sub="open invoices less credit memos" tone="hl" />
        <StatTile label="Overdue" value={exactMoney(pay.overdue_value, res.currency)} />
        <StatTile label="Blocked for payment" value={qty(pay.blocked)} sub="price or quantity differs" />
        <StatTile label="Received, not invoiced" value={exactMoney(pay.not_invoiced_value, res.currency)} sub="goods in, no bill yet" />
      </div>
      {banners}
      <Panel flush title="Received, not invoiced yet" actions={waiting.length > 0 && <>
        <label className="row small">Their invoice no. <input className="input" style={{ width: 130 }} value={ref} aria-label="Their invoice number"
          onChange={(e) => setRef(e.target.value)} /></label>
        <label className="row small">Dated <input type="date" className="input" style={{ width: 150 }} value={on} aria-label="Invoice date"
          onChange={(e) => setOn(e.target.value || ds.settings.planning_start)} /></label>
        <label className="row small">Tax <input className="input num" style={{ width: 90 }} type="number" min={0} step="any" aria-label="Tax charged"
          placeholder={String(round2(net * rate))} value={tax} onChange={(e) => setTax(e.target.value)} /></label>
        <Edits><button className="btn accent" disabled={busy || !picked.length || suppliers.size !== 1} onClick={enter}
          title={suppliers.size > 1 ? "One invoice is from one supplier: tick lines of one supplier" : undefined}>
          {busy ? "Checking…" : `Enter the invoice (${exactMoney(round2(net + (tax === "" ? net * rate : Number(tax))), res.currency)})`}</button></Edits>
      </>}>
        {waiting.length === 0 ? <Empty title="Nothing waiting for an invoice">Every goods receipt is invoiced. A supplier's credit memo for goods sent back is entered on Returns.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="t">
              <thead><tr><th aria-label="Invoice" /><th>Order line</th><th>Supplier</th><th>Product</th><th className="num">Received</th>
                <th className="num">Invoiced</th><th className="num">Billed now</th><th className="num">Order price</th><th className="num">Price billed</th><th>Last in</th></tr></thead>
              <tbody>
                {waiting.map((g) => (
                  <tr key={g.order} className={chosen.has(g.order) ? "selected" : ""}>
                    <td><input type="checkbox" checked={chosen.has(g.order)} onChange={() => toggle(g.order)} aria-label={`Invoice ${g.order}`} /></td>
                    <td><b>{g.order}</b>{g.po && <div className="faint small"><a href={href("buying", "orders", g.po)}>{g.po}</a></div>}</td>
                    <td><Loc id={g.supplier} /></td><td><Prod id={g.product} /></td>
                    <td className="num">{qty(g.received)}</td><td className="num">{g.invoiced ? qty(g.invoiced) : ""}</td>
                    <td className="num"><input className="input num" style={{ width: 80 }} type="number" min={0} aria-label={`Billed quantity ${g.order}`}
                      placeholder={String(g.qty)} value={line(g.order).qty} onChange={(e) => setEdit({ ...edit, [g.order]: { ...line(g.order), qty: e.target.value } })} /></td>
                    <td className="num">{g.price != null ? unitMoney(g.price, g.currency) : "—"}</td>
                    <td className="num"><input className="input num" style={{ width: 80 }} type="number" min={0} step="any" aria-label={`Billed price ${g.order}`}
                      placeholder={g.price != null ? String(g.price) : ""} value={line(g.order).price}
                      onChange={(e) => setEdit({ ...edit, [g.order]: { ...line(g.order), price: e.target.value } })} /></td>
                    <td>{g.last_receipt ? day(g.last_receipt) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel flush title="Supplier invoices">
        {pay.invoices.length === 0 ? <Empty title="No supplier invoices yet">Enter one from the goods received above.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <table className="t">
              <thead><tr><th>Invoice</th><th>Supplier</th><th>Their no.</th><th>Dated</th><th>Due</th><th className="num">Total</th>
                <th className="num">Open</th><th>Status</th></tr></thead>
              <tbody>
                {pay.invoices.map((i) => (
                  <tr key={i.id} className={`clickable ${i.id === sel ? "selected" : ""}`} onClick={() => go("buying", "invoices", i.id)}>
                    <td><b>{i.id}</b>{i.kind === "credit_memo" && <div className="faint small">credit memo{i.return_id ? ` for ${i.return_id}` : ""}</div>}</td>
                    <td><Loc id={i.supplier} /></td><td>{i.reference || "—"}</td><td>{day(i.date)}</td>
                    <td>{i.kind === "invoice" ? day(i.due_date) : "—"}{i.days_overdue > 0 && <Badge sev="error">{i.days_overdue} d overdue</Badge>}</td>
                    <td className="num">{exactMoney(i.kind === "credit_memo" ? -i.total : i.total, i.currency)}</td>
                    <td className="num">{i.open > 0.005 ? exactMoney(i.kind === "credit_memo" ? -i.open : i.open, i.currency) : ""}</td>
                    <td><Badge sev={INV_SEV[i.status]}>{i.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {cur && <InvoiceDetail key={cur.id} inv={cur} ds={ds} />}
      <Reading formula={<>Each line is checked when entered: the quantity against what arrived and is not yet invoiced, the price against the order's
        (more than {Math.round((ds.purchasing?.price_tolerance ?? 0.02) * 1000) / 10} % and {exactMoney(ds.purchasing?.amount_tolerance ?? 1, res.currency)} over blocks it).</>}
        soWhat={<>A quantity block lifts by itself once the goods arrive; a price block waits until someone releases the invoice. {nm.loc(supplier ?? "")
          ? `${nm.loc(supplier!)} is paid on ${vendor?.payment_terms ? "its payment terms" : `${vendor?.payment_terms_days ?? 30} days`}.` : ""}</>} />
    </div>
  );
}

function InvoiceDetail({ inv, ds }: { inv: SupplierInvoiceView; ds: Dataset }) {
  const today = ds.settings.planning_start;
  const [on, setOn] = useState(today);
  const inTime = inv.kind === "invoice" && !!inv.discount_date && on <= inv.discount_date && inv.payments.length === 0 && inv.discount > 0;
  const due = round2(inv.open - (inTime ? round2(inv.total * inv.discount) : 0));
  const [amount, setAmount] = useState("");
  const [ref, setRef] = useState("");
  const { busy, run, banners } = usePoAction();
  const blocked = inv.status === "blocked";
  const open = inv.open > 0.005 && inv.status !== "cancelled";
  return (
    <Panel title={<h3>{inv.kind === "credit_memo" ? "Credit memo" : "Invoice"} {inv.id} <span className="muted">from {namesOf(ds).loc(inv.supplier)}</span>{" "}
      <Badge sev={INV_SEV[inv.status]}>{inv.status}</Badge></h3>}
      actions={<Edits>
        {blocked && <button className="btn accent" disabled={busy} onClick={() => run("release_invoice", inv.id, { date: today })}>Release for payment</button>}
        {inv.status !== "cancelled" && inv.payments.length === 0 && <button className="btn ghost" disabled={busy} onClick={() => run("cancel_invoice", inv.id)}>Cancel it</button>}
      </Edits>}>
      <div className="row wrap small muted" style={{ gap: 16, marginBottom: 10 }}>
        {inv.reference && <span>Their no. {inv.reference}</span>}<span>Dated {day(inv.date)}</span>
        {inv.kind === "invoice" && <span>Due {day(inv.due_date)}</span>}
        {inv.discount_date && <span>{Math.round(inv.discount * 1000) / 10} % off if paid by {day(inv.discount_date)}</span>}
        <span>Net {exactMoney(inv.net, inv.currency)} · tax {exactMoney(inv.tax, inv.currency)} · total {exactMoney(inv.total, inv.currency)}</span>
        {inv.released_on && <span>Released {day(inv.released_on)}{inv.released_by ? ` by ${inv.released_by}` : ""}</span>}
      </div>
      {inv.still.length > 0 && <div className="banner warning" style={{ marginBottom: 10 }}><div><b>Blocked for payment:</b>
        {inv.still.map((b) => <div key={b}>• {namesOf(ds).text(b)}</div>)}</div></div>}
      {inv.blocks.length > 0 && !inv.still.length && inv.status !== "cancelled" && <p className="small muted">Blocked when entered ({inv.blocks.map((b) => b.split(": ")[0]).join(", ")}):
        {inv.released_on ? " released." : " the goods have arrived since, so it can be paid."}</p>}
      {banners}
      <div className="table-wrap">
        <table className="t">
          <thead><tr><th>Order line</th><th>Product</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Order price</th>
            <th className="num">Received</th><th className="num">Invoiced</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {inv.lines.map((l) => (
              <tr key={l.order}>
                <td><b>{l.order}</b></td><td><Prod id={l.product} /></td><td className="num">{qty(l.qty)}</td>
                <td className="num">{unitMoney(l.price, inv.currency)}</td>
                <td className="num">{l.order_price != null ? unitMoney(l.order_price, inv.currency) : "—"}
                  {l.order_price != null && l.price > l.order_price + 1e-9 && <Badge sev="warning">+{Math.round((l.price / l.order_price - 1) * 1000) / 10} %</Badge>}</td>
                <td className="num">{qty(l.received)}</td><td className="num">{qty(l.invoiced)}</td>
                <td className="num">{exactMoney(l.amount, inv.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {inv.payments.length > 0 && <p className="small" style={{ marginTop: 8 }}>{inv.payments.map((p, i) => <span key={i}>{i > 0 && "; "}
        {exactMoney(p.amount, inv.currency)} on {day(p.date)}{p.discount ? ` (discount ${exactMoney(p.discount, inv.currency)})` : ""}{p.reference ? `, ${p.reference}` : ""}</span>)}</p>}
      {open && !blocked && <Edits><div className="row wrap" style={{ gap: 10, marginTop: 10 }}>
        <label className="row small">{inv.kind === "credit_memo" ? "Refund received on" : "Paid on"} <input type="date" className="input" value={on} aria-label="Paid on"
          onChange={(e) => setOn(e.target.value || today)} /></label>
        <label className="row small">Amount <input className="input num" style={{ width: 110 }} type="number" min={0} step="any" aria-label="Amount paid"
          placeholder={String(due)} value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <label className="row small">Bank reference <input className="input" style={{ width: 120 }} value={ref} aria-label="Bank reference" onChange={(e) => setRef(e.target.value)} /></label>
        <button className="btn accent" disabled={busy} onClick={() => run("pay_invoice", inv.id, { date: on, amount: amount === "" ? null : Number(amount), reference: ref },
          () => { setAmount(""); setRef(""); })}>{inv.kind === "credit_memo" ? "Refund received" : `Pay ${exactMoney(amount === "" ? due : Number(amount), inv.currency)}`}</button>
        {inTime && <span className="small faint">in time for the cash discount of {exactMoney(round2(inv.total * inv.discount), inv.currency)}</span>}
      </div></Edits>}
    </Panel>
  );
}

// ---- what we owe --------------------------------------------------------------------------------------------
export function Owed({ res, ds }: { res: PurchasingView; ds: Dataset }) {
  const pay = res.payables!;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="We owe" value={exactMoney(pay.open_value, res.currency)} tone="hl" />
        <StatTile label="Overdue" value={exactMoney(pay.overdue_value, res.currency)} />
        <StatTile label="Due within 7 days" value={exactMoney(pay.payables.reduce((a, r) => a + r.due_soon, 0), res.currency)} />
        <StatTile label="Received, not invoiced" value={exactMoney(pay.not_invoiced_value, res.currency)} sub="to accrue at month end" />
      </div>
      <Panel flush title="What we owe each supplier">
        {pay.payables.length === 0 ? <Empty title="Nothing owed">No open supplier invoice and nothing received without one.</Empty> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Supplier</th><th>Terms</th><th className="num">Open</th><th className="num">Overdue</th><th className="num">Due in 7 days</th>
                <th className="num">Blocked</th><th className="num">Received, not invoiced</th><th>Next due</th></tr></thead>
              <tbody>
                {pay.payables.map((r) => (
                  <tr key={r.supplier}>
                    <td><b>{r.name}</b><div className="faint small">{r.supplier}</div></td><td className="small">{r.terms}</td>
                    <td className="num">{exactMoney(r.open, res.currency)}</td>
                    <td className="num">{r.overdue ? <b style={{ color: "var(--error-text)" }}>{exactMoney(r.overdue, res.currency)}</b> : ""}</td>
                    <td className="num">{r.due_soon ? exactMoney(r.due_soon, res.currency) : ""}</td>
                    <td className="num">{r.blocked ? exactMoney(r.blocked, res.currency) : ""}</td>
                    <td className="num">{r.not_invoiced ? exactMoney(r.not_invoiced, res.currency) : ""}</td>
                    <td>{r.next_due ? day(r.next_due) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Reading formula="Open: invoices not yet paid, less credit memos not yet refunded. Received, not invoiced: goods in at the order price with no invoice for them yet."
        soWhat={<>Pay what is due on <a href={href("buying", "invoices")}>Supplier invoices</a>; a supplier's payment terms are on their <a href={href("data", "vendors")}>purchasing data</a>.
          {ds.vendors?.length ? "" : " No supplier has purchasing data yet, so every invoice is due 30 days after its date."}</>} />
    </div>
  );
}

// ---- returns to suppliers -----------------------------------------------------------------------------------
export function Returns({ res, ds }: { res: PurchasingView; ds: Dataset }) {
  const pay = res.payables!;
  const lines = useMemo(() => res.orders.flatMap((p) => p.lines.filter((l) => l.received - 1e-6 > 0)
    .map((l) => ({ ...l, supplier: p.supplier ?? "", po: p.id }))), [res.orders]);
  const [order, setOrder] = useState("");
  const [n, setN] = useState("");
  const [reason, setReason] = useState("");
  const [where, setWhere] = useState<StockType>("blocked");
  const [replace, setReplace] = useState(false);
  const [refs, setRefs] = useState<Record<string, string>>({});
  const { busy, run, banners } = usePoAction();
  const sel = lines.find((l) => l.id === order);
  const send = () => run("return_goods", "", { lines: [{ id: order, qty: Number(n || 0), final: false }], note: reason, stock_type: where, replace,
    date: ds.settings.planning_start }, () => { setN(""); setReason(""); });
  return (
    <div className="stack">
      {banners}
      <Panel title="Send goods back to the supplier" actions={<Edits><button className="btn accent" disabled={busy || !order || !(Number(n) > 0)} onClick={send}>Send them back</button></Edits>}>
        {lines.length === 0 ? <Empty title="Nothing received yet">Goods received on a purchase order can be sent back from here.</Empty> : (
          <div className="row wrap" style={{ gap: 10 }}>
            <label className="row small">Order line <select className="input" aria-label="Order line sent back" value={order} onChange={(e) => setOrder(e.target.value)}>
              <option value="">Choose…</option>
              {lines.map((l) => <option key={l.id} value={l.id}>{l.id} · {namesOf(ds).prod(l.product)} · {qty(l.received)} received</option>)}
            </select></label>
            <label className="row small">Quantity <input className="input num" style={{ width: 90 }} type="number" min={0} aria-label="Quantity sent back" value={n}
              placeholder={sel ? String(sel.received) : ""} onChange={(e) => setN(e.target.value)} /></label>
            <label className="row small">From <select className="input" aria-label="Stock it leaves" value={where} onChange={(e) => setWhere(e.target.value as StockType)}>
              <option value="blocked">blocked stock</option><option value="quality">quality inspection</option><option value="unrestricted">unrestricted stock</option>
            </select></label>
            <label className="row small">Why <input className="input" style={{ width: 180 }} aria-label="Why it goes back" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
            <label className="row small"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> The supplier replaces them</label>
          </div>
        )}
        <p className="small faint" style={{ marginTop: 8 }}>Credited goods reduce the order line and wait for the supplier's credit memo; replaced goods leave the line open for the new ones.</p>
      </Panel>
      <Panel flush title="Returns">
        {pay.returns.length === 0 ? <Empty title="No returns">Nothing has gone back to a supplier.</Empty> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Return</th><th>Supplier</th><th>Order line</th><th>Product</th><th className="num">Qty</th><th>Sent</th><th>Why</th><th>Status</th><th aria-label="Credit memo" /></tr></thead>
              <tbody>
                {pay.returns.map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.id}</b></td><td><Loc id={r.supplier} /></td><td>{r.order}</td><td><Prod id={r.product} /></td>
                    <td className="num">{qty(r.qty)}</td><td>{day(r.date)}</td><td className="small">{r.reason}</td>
                    <td><Badge sev={RET_SEV[r.status]}>{r.status}</Badge>{r.credit_memo && <div className="faint small">{r.credit_memo}</div>}</td>
                    <td>{r.status === "to credit" && <Edits><span className="row" style={{ gap: 6 }}>
                      <input className="input" style={{ width: 110 }} placeholder="Their credit no." aria-label={`Credit memo number for ${r.id}`}
                        value={refs[r.id] ?? ""} onChange={(e) => setRefs({ ...refs, [r.id]: e.target.value })} />
                      <button className="btn sm" disabled={busy} onClick={() => run("enter_invoice", "", { return_id: r.id, reference: refs[r.id] ?? "",
                        date: ds.settings.planning_start })}>Credit memo in</button></span></Edits>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---- contracts ----------------------------------------------------------------------------------------------
export function Contracts({ res }: { res: PurchasingView; ds: Dataset }) {
  const list = res.payables!.contracts;
  return (
    <div className="stack">
      <Panel flush title="Contracts with suppliers" actions={<a className="btn sm" href={href("data", "contracts")}>Add or edit contracts</a>}>
        {list.length === 0 ? <Empty title="No contracts">A contract fixes a supplier's prices for a period; orders made while it is valid take its price.
          <div style={{ marginTop: 8 }}><a className="btn sm accent" href={href("data", "contracts")}>Add a contract</a></div></Empty> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Contract</th><th>Supplier</th><th>Valid</th><th>Product</th><th className="num">Price</th><th className="num">Agreed</th>
                <th className="num">Ordered</th><th className="num">Left</th><th>Status</th></tr></thead>
              <tbody>
                {list.flatMap((k) => k.lines.map((l, i) => (
                  <tr key={`${k.id}/${l.product}`}>
                    {i === 0 && <><td rowSpan={k.lines.length}><b>{k.id}</b>{k.supplier_reference && <div className="faint small">their no. {k.supplier_reference}</div>}
                      {k.attention.map((a) => <div key={a} className="small" style={{ color: "var(--warning-text)" }}>{a}</div>)}</td>
                      <td rowSpan={k.lines.length}><Loc id={k.supplier} />{k.location && <div className="faint small">to <Loc id={k.location} /></div>}</td>
                      <td rowSpan={k.lines.length} className="small">{day(k.valid_from)} – {day(k.valid_to)}</td></>}
                    <td><Prod id={l.product} /></td><td className="num">{unitMoney(l.price, k.currency)}</td>
                    <td className="num">{l.target_qty != null ? qty(l.target_qty) : "—"}</td><td className="num">{qty(l.ordered)}</td>
                    <td className="num">{l.left != null ? qty(l.left) : "—"}</td>
                    {i === 0 && <td rowSpan={k.lines.length}><Badge sev={CON_SEV[k.status]}>{k.status}</Badge>
                      {k.target_value != null && <div className="faint small">{exactMoney(k.ordered_value, k.currency)} of {exactMoney(k.target_value, k.currency)}</div>}</td>}
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Reading formula="Ordered: on purchase order lines that name the contract, open and closed."
        soWhat="A new purchase order for a contract's product takes the contract's price while it is valid, the lowest when several apply, and the line names the contract." />
    </div>
  );
}
