// Selling (Phase M): from the customer's order to their payment. Orders of several lines priced by the customer's
// prices, scales and discounts; quotations; deliveries picked, packed, shipped and signed for; invoices with payment
// terms and payments; returns and credit notes; and what each customer owes against their credit limit.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, DeliveryView, InvoiceView, OrderView, SalesAction, SalesActionInput, SalesView } from "../api/types";
import {
  Badge, Edits, Empty, Panel, Provenance, RunButton, SolverIO, StageHeader, StaleMark, StatTile, Tabs, Term,
} from "../components/ui";
import { addDays, day, exactMoney, money, pct, plural, qty, unitMoney } from "../lib/format";
import { Loc, Msg, Prod, namesOf, useNames } from "../lib/names";
import { confirmationDocument, customerAddresses, customerEmail, invoiceDocument } from "../lib/sodoc";
import { ServerSend } from "../components/ServerSend";
import { download } from "../lib/tabular";
import { go, href } from "../lib/router";
import { isStale, store, useFreshResult, useReadOnly, useStore } from "../state/store";

type View = "orders" | "new" | "quotes" | "deliver" | "bill" | "returns" | "customers";
type Sev = "error" | "warning" | "info" | "ok";

const ORDER_SEV: Record<string, Sev> = {
  open: "info", "partly delivered": "info", delivered: "ok", invoiced: "ok", cancelled: "warning", "credit block": "error",
};
const DELIVERY_SEV: Record<string, Sev> = { "to pick": "warning", picked: "info", packed: "info", shipped: "ok", delivered: "ok" };
const INVOICE_SEV: Record<string, Sev> = { open: "info", "part paid": "info", paid: "ok", overdue: "error", cancelled: "warning" };
const QUOTE_SEV: Record<string, Sev> = { open: "info", won: "ok", lost: "warning", expired: "warning" };

/** Run an order-to-cash step on the company, then list selling again. */
async function act(action: SalesAction, extra: SalesActionInput = {}) {
  const before = store.get().dataset!;
  const out = await api.salesAct(before, action, extra);
  store.replace(out.dataset, before);
  await store.run("sales");
  return out;
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: SalesAction, extra: SalesActionInput = {}, after?: () => void) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const out = await act(action, extra);
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

export function Selling({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.sales);
  useFreshResult("sales");
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "sales"));
  const view = ((route[1] as View) || "orders") as View;
  const head = (
    <StageHeader title="Selling" kicker="From the customer's order to their payment: orders, quotations, deliveries, invoices and returns."
      how={<>An order has lines, each priced from the customer's price (its quantity scale), else the product's, less the customer's
        discounts, and each promised like any order (see Orders). An order that takes a customer over their <Term t="Credit limit">credit
        limit</Term> is promised but not shipped until someone releases it. Lines due to ship go on deliveries, which are picked, packed,
        shipped (the goods leave stock) and signed for. What was shipped is invoiced with the customer's payment terms and tax; payments
        settle invoices, with the cash discount when paid in time. Returns come back into quality inspection and are paid back with a
        credit note.</>}
      answer={res && sellingAnswer(res)}
      right={<>{res && <Provenance kind="derived" at={run.at} stale={stale} />}
        <RunButton running={run.running} has={!!res} onClick={() => store.run("sales")} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  if (run.error) return body(<div className="banner error"><Badge sev="error">Could not list selling</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="Every order with its lines, what is due to ship, what is waiting for an invoice, unpaid invoices and each customer's credit position."
        from="Sales orders and their lines, customer prices with scales and discounts, customers' payment terms and credit limits, deliveries, invoices, returns and the goods movements."
        feeds="Promising (the lines are customer orders), stock (deliveries and returns post goods movements) and what customers owe." />
      <div style={{ height: 14 }} />
      <Panel><Empty title="Not listed yet"><p>Press Calculate, or Plan everything, to see selling.</p></Empty></Panel>
    </>);
  }
  const t = res;
  return body(<>
    {stale && <StaleMark what="selling view" onRerun={() => store.run("sales")} busy={run.running} />}
    <Tabs<View> value={view} onChange={(v) => go("selling", v)} tabs={[
      { id: "orders", label: "Orders", count: t.orders.filter((o) => !["invoiced", "cancelled"].includes(o.status)).length },
      { id: "new", label: "New order or quotation" },
      { id: "quotes", label: "Quotations", count: t.quotations.filter((q) => q.status === "open").length },
      { id: "deliver", label: "Deliveries", count: t.to_deliver.length + t.deliveries.filter((d) => d.status !== "delivered" && d.status !== "shipped").length },
      { id: "bill", label: "Invoices", count: t.to_bill.length + t.invoices.filter((i) => i.open > 0.005).length },
      { id: "returns", label: "Returns", count: t.returns.filter((r) => r.status !== "credited").length },
      { id: "customers", label: "Customers", count: t.customers.length },
    ]} />
    {view === "orders" && <Orders res={res} ds={ds} sel={route[2]} />}
    {view === "new" && <NewOrder res={res} ds={ds} />}
    {view === "quotes" && <Quotes res={res} />}
    {view === "deliver" && <Deliveries res={res} ds={ds} sel={route[2]} />}
    {view === "bill" && <Invoices res={res} ds={ds} sel={route[2]} />}
    {view === "returns" && <Returns res={res} ds={ds} />}
    {view === "customers" && <Customers res={res} />}
  </>);
}

function sellingAnswer(res: SalesView) {
  const open = res.orders.filter((o) => ["open", "partly delivered", "credit block"].includes(o.status));
  const blocked = res.orders.filter((o) => o.status === "credit block").length;
  const bill = res.to_bill.reduce((a, b) => a + (b.value ?? 0), 0);
  const owed = res.invoices.filter((i) => i.kind === "invoice").reduce((a, i) => a + i.open, 0);
  const overdue = res.invoices.filter((i) => i.status === "overdue");
  const parts = [
    open.length ? `${plural(open.length, "order")} open` : "No orders open",
    res.to_deliver.length ? `${plural(res.to_deliver.length, "line")} due to ship` : null,
    res.to_bill.length ? `${money(bill, res.currency)} shipped and not invoiced` : null,
    owed > 0.005 ? `customers owe ${money(owed, res.currency)}` : null,
  ].filter(Boolean);
  const needs = [blocked && `${plural(blocked, "order")} over a credit limit`,
    overdue.length && `${plural(overdue.length, "invoice")} overdue (${money(overdue.reduce((a, i) => a + i.open, 0), res.currency)})`].filter(Boolean);
  return <>{parts.join("; ")}.{needs.length > 0 && <> Needs you: {needs.join(", ")}.</>}</>;
}

// ------------------------------------------------------------------------------------------------ prices
/** The price a line gets, as the engine works it out: the customer's price at its quantity scale, else the product's,
 *  less the customer's price discount and their own discount. */
export function linePrice(ds: Dataset, customer: string, product: string, n: number): { net: number | null; list: number | null; discount: number } {
  const cust = (ds.customers ?? []).find((c) => c.customer === customer);
  const cd = cust?.discount ?? 0;
  const cp = (ds.customer_prices ?? []).find((c) => c.customer === customer && c.product === product);
  if (cp) {
    let base = cp.price;
    for (const sc of [...(cp.scales ?? [])].sort((a, b) => a.from_qty - b.from_qty)) if (n + 1e-9 >= sc.from_qty) base = sc.price;
    const d = 1 - (1 - (cp.discount ?? 0)) * (1 - cd);
    return { net: base * (1 - d), list: base, discount: d };
  }
  const p = (ds.products ?? []).find((x) => x.id === product)?.price ?? null;
  return { net: p == null ? null : p * (1 - cd), list: p, discount: cd };
}

function customersOf(ds: Dataset) {
  return (ds.locations ?? []).filter((l) => l.type === "customer" || ((ds.customer_prices ?? []).some((c) => c.customer === l.id)));
}

// ------------------------------------------------------------------------------------------------ orders
function Orders({ res, ds, sel }: { res: SalesView; ds: Dataset; sel?: string }) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const nm = useNames();
  const rows = res.orders.filter((o) => (all || !["invoiced", "cancelled"].includes(o.status))
    && (!q || `${o.id} ${o.customer} ${nm.loc(o.customer)} ${o.customer_ref}`.toLowerCase().includes(q.toLowerCase())));
  const open = res.orders.find((o) => o.id === sel);
  if (res.orders.length === 0) {
    return <Panel><Empty title="No orders yet">Take one on <a href={href("selling", "new")}>New order or quotation</a>, or check
      availability first on <a href={href("promise", "simulate")}>Orders → New order</a>.</Empty></Panel>;
  }
  return <div className="stack">
    {open && <OrderDetail o={open} ds={ds} res={res} />}
    <Panel flush title="Sales orders" actions={<>
      <input className="search" placeholder="Find an order or customer" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find an order" />
      <label className="row small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Show invoiced and cancelled</label></>}>
      <div className="table-wrap"><table className="t">
        <thead><tr><th>Order</th><th>Customer</th><th>Ordered</th><th>Their number</th><th className="num">Lines</th><th className="num">Value</th><th>Status</th></tr></thead>
        <tbody>{rows.map((o) => (
          <tr key={o.id} className={`clickable ${sel === o.id ? "selected" : ""}`} onClick={() => go("selling", "orders", sel === o.id ? undefined : o.id)}>
            <td><b>{o.id}</b>{o.quotation && <div className="faint small">from {o.quotation}</div>}</td>
            <td><Loc id={o.customer} /></td><td>{day(o.order_date)}</td><td>{o.customer_ref || "—"}</td>
            <td className="num">{o.lines.length}</td><td className="num">{o.value != null ? exactMoney(o.value, res.currency) : "no price"}</td>
            <td><Badge sev={ORDER_SEV[o.status] ?? "info"}>{o.status}</Badge></td>
          </tr>))}
          {rows.length === 0 && <tr><td colSpan={7} className="faint">Nothing matches.</td></tr>}
        </tbody>
      </table></div>
    </Panel>
  </div>;
}

function OrderDetail({ o, ds, res }: { o: OrderView; ds: Dataset; res: SalesView }) {
  const action = useAction();
  const { busy, run, banners } = action;
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const [adding, setAdding] = useState(false);
  const cur = res.currency;
  const openLines = o.lines.filter((l) => !l.closed && l.open > 1e-9);
  return <Panel title={<>Order {o.id} · <Loc id={o.customer} /></>} actions={<>
    <DocButtons kind="confirmation" o={o} ds={ds} action={action} />
    <button className="btn sm ghost" onClick={() => go("selling", "orders")}>Close</button></>}>
    {banners}
    {o.credit_block && <div className="banner error"><Badge sev="error">Credit block</Badge><span>{o.credit_note}. It is promised but cannot ship until released.</span>
      <span className="spacer" /><Edits><button className="btn sm accent" disabled={busy} onClick={() => run("release_credit", { id: o.id })}>Release for delivery</button></Edits></div>}
    {!o.credit_block && o.credit_note && <p className="faint small">{o.credit_note}</p>}
    <div className="grid-auto">
      <StatTile label="Value" value={o.value != null ? exactMoney(o.value, cur) : "—"} sub="before tax" />
      <StatTile label="Payment" value={o.payment_terms.split(", ").pop() ?? o.payment_terms}
        sub={o.payment_terms.includes(", ") ? o.payment_terms.split(", ").slice(0, -1).join(", ") : undefined} />
      <StatTile label="Shipped" value={pct(o.lines.reduce((a, l) => a + l.delivered, 0) / Math.max(1e-9, o.lines.reduce((a, l) => a + l.qty, 0)), 0)}
        sub={`${plural(openLines.length, "line")} still to ship`} />
      <StatTile label="Confirmation" value={o.confirmation_sent_on ? `sent ${day(o.confirmation_sent_on)}` : o.header ? "not sent" : "—"} />
    </div>
    <div className="table-wrap"><table className="t">
      <thead><tr><th>Line</th><th>Product</th><th className="num">Ordered</th><th className="num">Shipped</th><th className="num">Invoiced</th>
        <th className="num">Returned</th><th>Wanted</th><th>Promised</th><th className="num">Price</th><th className="num">Value</th></tr></thead>
      <tbody>{o.lines.map((l) => (
        <tr key={l.id}>
          <td>{l.id}{l.cancelled && <div><Badge sev="warning">cancelled</Badge></div>}{l.closed && !l.cancelled && <div className="faint small">closed</div>}</td>
          <td><Prod id={l.product} /></td><td className="num">{qty(l.qty)}</td><td className="num">{qty(l.delivered)}</td>
          <td className="num">{qty(l.invoiced)}</td><td className="num">{l.returned ? qty(l.returned) : ""}</td>
          <td>{day(l.date)}</td><td>{l.promised ? <span className={l.promised > l.date ? "warn-text" : undefined}>{day(l.promised)}</span> : "—"}</td>
          <td className="num">{l.price != null ? unitMoney(l.price, cur) : "—"}{l.discount > 1e-9 && <div className="faint small">{pct(l.discount, 1)} off {l.list_price != null ? unitMoney(l.list_price, cur) : ""}</div>}</td>
          <td className="num">{l.value != null ? exactMoney(l.value, cur) : "—"}</td>
        </tr>))}
      </tbody>
    </table></div>
    <Edits><div className="row wrap" style={{ marginTop: 10 }}>
      {o.header && openLines.length > 0 && <button className="btn sm" onClick={() => setAdding(!adding)} aria-expanded={adding}>Add a line</button>}
      {o.header && o.lines.some((l) => !l.closed) && (cancelling
        ? <span className="row wrap"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why (optional)" aria-label="Why it is cancelled" />
          <button className="btn sm danger" disabled={busy} onClick={() => run("cancel_order", { id: o.id, reason }, () => setCancelling(false))}>Cancel what is still open</button>
          <button className="btn sm ghost" onClick={() => setCancelling(false)}>Keep it</button></span>
        : <button className="btn sm ghost" onClick={() => setCancelling(true)}>Cancel the order…</button>)}
    </div></Edits>
    {adding && <LinesForm ds={ds} customer={o.customer} busy={busy} submit="Add to the order"
      onSubmit={(lines) => run("add_lines", { id: o.id, lines }, () => setAdding(false))} />}
  </Panel>;
}

/** Print (or save as PDF), download or e-mail the order confirmation or an invoice. */
type Runner = ReturnType<typeof useAction>;
function DocButtons(p: ({ kind: "confirmation"; o: OrderView } | { kind: "invoice"; id: string }) & { ds: Dataset; action?: Runner }) {
  const ds = p.ds;
  const inv = p.kind === "invoice" ? (ds.invoices ?? []).find((i) => i.id === p.id) : undefined;
  if (p.kind === "invoice" && !inv) return null;
  const customer = p.kind === "confirmation" ? p.o.customer : inv!.customer;
  const id = p.kind === "confirmation" ? p.o.id : inv!.id;
  const html = () => (p.kind === "confirmation" ? confirmationDocument(p.o, ds) : invoiceDocument(inv!, ds));
  const nm = namesOf(ds);
  const mail = p.kind === "confirmation"
    ? customerEmail(ds, customer, `Order confirmation ${id}`, `Thank you for your order${p.o.customer_ref ? ` ${p.o.customer_ref}` : ""}. We confirm ${id}:`,
      p.o.lines.filter((l) => !l.cancelled).map((l) => `- ${nm.prod(l.product)}: ${qty(l.qty)}${l.price != null ? ` at ${unitMoney(l.price, ds.settings.currency ?? "INR")}` : ""}, delivery ${day(l.promised ?? l.date)}`),
      [`Payment: ${p.o.payment_terms}.`])
    : customerEmail(ds, customer, `${inv!.kind === "credit_note" ? "Credit note" : "Invoice"} ${id}`,
      `Please find ${inv!.kind === "credit_note" ? "credit note" : "invoice"} ${id} of ${day(inv!.date)}:`,
      inv!.lines.map((l) => `- ${nm.prod(l.product)}: ${qty(l.qty)} at ${unitMoney(l.price, ds.settings.currency ?? "INR")}`),
      inv!.kind === "credit_note" ? [] : [`Due ${day(inv!.due_date)}. Please quote ${id} with your payment.`]);
  const mailto = `mailto:${encodeURIComponent(mail.to)}?subject=${encodeURIComponent(mail.subject)}&body=${encodeURIComponent(mail.body)}`;
  const print = () => {
    const w = window.open("", "_blank");
    if (!w) return download(`${id}.html`, html(), "text/html");
    w.document.write(html());
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 250);
  };
  const missing = customerAddresses(ds, customer);
  return <span className="row wrap" style={{ gap: 6 }}>
    {missing.length > 0 && <span className="faint small">No address yet for {missing.map((m, i) =>
      <span key={m.href}>{i ? " and " : ""}<a href={m.href}>{m.what}</a></span>)}</span>}
    <button className="btn sm ghost" onClick={print} title="Opens the document as a page and the print dialog, where it can be saved as PDF">Print or PDF</button>
    <button className="btn sm ghost" onClick={() => download(`${id}.html`, html(), "text/html")}>Download</button>
    <a className="btn sm ghost" href={mailto}>E-mail</a>
    <ServerSend kind={p.kind === "confirmation" ? "confirmation" : inv!.kind === "credit_note" ? "credit_note" : "invoice"} docRef={id} to={mail.to}
      subject={mail.subject} text={mail.body} html={html}
      onSent={p.kind === "confirmation" && p.o.header && !p.o.confirmation_sent_on && p.action ? () => p.action!.run("send_confirmation", { id }) : undefined} />
    {p.kind === "confirmation" && p.o.header && !p.o.confirmation_sent_on && p.action && <Edits><button className="btn sm" disabled={p.action.busy}
      onClick={() => p.action!.run("send_confirmation", { id })}>Mark as sent</button></Edits>}
  </span>;
}

// ------------------------------------------------------------------------------------------------ new order or quotation
interface Line { product: string; qty: number; date: string; price: number | null }

function LinesForm({ ds, customer, busy, submit, onSubmit, second }: {
  ds: Dataset; customer: string; busy: boolean; submit: string; onSubmit: (lines: Line[]) => void;
  second?: { label: string; onClick: (lines: Line[]) => void };
}) {
  const products = useMemo(() => (ds.products ?? []).filter((p) => p.type === "FG" || p.type === "SFG" || p.price != null), [ds]);
  const start = ds.settings.planning_start;
  const blank = (): Line => ({ product: products[0]?.id ?? "", qty: 1, date: addDays(start, 7), price: null });
  const [lines, setLines] = useState<Line[]>([blank()]);
  const cur = ds.settings.currency ?? "INR";
  const set = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const ok = customer && lines.length > 0 && lines.every((l) => l.product && l.qty > 0 && l.date);
  const total = lines.reduce((a, l) => a + l.qty * (l.price ?? linePrice(ds, customer, l.product, l.qty).net ?? 0), 0);
  return <div className="stack">
    <div className="table-wrap"><table className="t">
      <thead><tr><th>Line</th><th>Product</th><th className="num">Quantity</th><th>Wanted on</th><th className="num">Price a unit</th><th className="num">Value</th><th /></tr></thead>
      <tbody>{lines.map((l, i) => {
        const pr = linePrice(ds, customer, l.product, l.qty);
        return <tr key={i}>
          <td>{(i + 1) * 10}</td>
          <td><select value={l.product} onChange={(e) => set(i, { product: e.target.value })} aria-label={`Line ${(i + 1) * 10} product`}>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}</select></td>
          <td className="num"><input type="number" min={0} step="any" value={l.qty} style={{ width: 90 }} onChange={(e) => set(i, { qty: Number(e.target.value) })} aria-label={`Line ${(i + 1) * 10} quantity`} /></td>
          <td><input type="date" value={l.date} onChange={(e) => set(i, { date: e.target.value })} aria-label={`Line ${(i + 1) * 10} wanted on`} /></td>
          <td className="num"><input type="number" min={0} step="any" style={{ width: 110 }} value={l.price ?? ""} aria-label={`Line ${(i + 1) * 10} price`}
            placeholder={pr.net != null ? `${Math.round(pr.net * 100) / 100}` : "no price"} onChange={(e) => set(i, { price: e.target.value === "" ? null : Number(e.target.value) })} />
            {l.price == null && pr.discount > 1e-9 && pr.list != null && <div className="faint small">{unitMoney(pr.list, cur)} less {pct(pr.discount, 1)}</div>}</td>
          <td className="num">{exactMoney(l.qty * (l.price ?? pr.net ?? 0), cur)}</td>
          <td>{lines.length > 1 && <button className="btn sm ghost" aria-label={`Remove line ${(i + 1) * 10}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>✕</button>}</td>
        </tr>;
      })}</tbody>
      <tfoot><tr><td /><td><button className="btn sm ghost" onClick={() => setLines((ls) => [...ls, blank()])}>+ Add a line</button></td><td /><td />
        <td className="num faint">before tax</td><td className="num"><b>{exactMoney(total, cur)}</b></td><td /></tr></tfoot>
    </table></div>
    <Edits><div className="row wrap">
      <button className="btn accent" disabled={busy || !ok} onClick={() => onSubmit(lines)}>{busy ? "Working…" : submit}</button>
      {second && <button className="btn" disabled={busy || !ok} onClick={() => second.onClick(lines)}>{second.label}</button>}
    </div></Edits>
  </div>;
}

function NewOrder({ res, ds }: { res: SalesView; ds: Dataset }) {
  const places = useMemo(() => customersOf(ds), [ds]);
  const [customer, setCustomer] = useState(places[0]?.id ?? "");
  const [ref, setRef] = useState("");
  const [terms, setTerms] = useState("");
  const { busy, run, banners } = useAction();
  const credit = res.customers.find((c) => c.customer === customer);
  const blocked = (ds.customers ?? []).find((c) => c.customer === customer && c.blocked);
  if (places.length === 0) return <Panel><Empty title="No customers">Add a place of type customer in <a href={href("setup")}>Set up</a>.</Empty></Panel>;
  const payload = (lines: Line[]) => ({ customer, customer_ref: ref, payment_terms: terms || null,
    lines: lines.map((l) => ({ product: l.product, qty: l.qty, date: l.date, price: l.price })) });
  return <div className="stack">
    {banners}
    <Panel title="New order or quotation">
      <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
        <label className="field"><span className="label">Customer</span>
          <select value={customer} onChange={(e) => setCustomer(e.target.value)} aria-label="Customer">
            {places.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></label>
        <label className="field"><span className="label">Their order number</span>
          <input value={ref} maxLength={64} onChange={(e) => setRef(e.target.value)} aria-label="Their order number" /></label>
        <label className="field"><span className="label">Payment terms</span>
          <select value={terms} onChange={(e) => setTerms(e.target.value)} aria-label="Payment terms">
            <option value="">The customer's ({credit?.payment_terms ?? "net 30 days"})</option>
            {(ds.payment_terms ?? []).map((t) => <option key={t.id} value={t.id}>{t.name || t.id}</option>)}</select></label>
      </div>
      {blocked && <div className="banner error" style={{ marginTop: 10 }}><Badge sev="error">Blocked for sales</Badge>{blocked.block_reason || "Lift the block on the customer's sales data first."}</div>}
      {credit?.credit_limit != null && <p className="small" role="status">Credit: owes {exactMoney(credit.exposure, res.currency)} of a {exactMoney(credit.credit_limit, res.currency)} limit
        ({exactMoney(credit.headroom ?? 0, res.currency)} left{credit.overdue > 0 ? `, ${exactMoney(credit.overdue, res.currency)} overdue` : ""}). An order beyond it is held until released.</p>}
      <LinesForm key={customer} ds={ds} customer={customer} busy={busy} submit="Take the order"
        onSubmit={(lines) => run("create_order", payload(lines), () => setRef(""))}
        second={{ label: "Make a quotation", onClick: (lines) => run("create_quotation", payload(lines)) }} />
      <p className="faint small">Prices come from the customer's price (and its quantity scale), else the product's, less their discounts; type a price
        to agree another. <b>Take the order</b> promises every line after the orders already promised and makes any new production it needs
        firm. <b>Make a quotation</b> promises nothing; it holds for {ds.sales?.quotation_days ?? 30} days.
        To see first what can be promised for one product, use <a href={href("promise", "simulate")}>Orders → New order</a>.</p>
    </Panel>
  </div>;
}

// ------------------------------------------------------------------------------------------------ quotations
function Quotes({ res }: { res: SalesView }) {
  const { busy, run, banners } = useAction();
  const [losing, setLosing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  if (res.quotations.length === 0) return <Panel><Empty title="No quotations">Make one on <a href={href("selling", "new")}>New order or quotation</a>.</Empty></Panel>;
  return <div className="stack">{banners}
    <Panel flush title="Quotations">
      <div className="table-wrap"><table className="t">
        <thead><tr><th>Quotation</th><th>Customer</th><th>Made</th><th>Valid to</th><th className="num">Lines</th><th className="num">Value</th><th>Status</th><th /></tr></thead>
        <tbody>{res.quotations.map((q) => (
          <tr key={q.id}>
            <td><b>{q.id}</b></td><td><Loc id={q.customer} /></td><td>{day(q.quote_date)}</td><td>{day(q.valid_to)}</td>
            <td className="num">{q.lines}</td><td className="num">{exactMoney(q.value, res.currency)}</td>
            <td><Badge sev={QUOTE_SEV[q.status] ?? "info"}>{q.status}</Badge>{q.order && <> <a href={href("selling", "orders", q.order)}>{q.order}</a></>}</td>
            <td>{q.status === "open" && <Edits><span className="row wrap" style={{ gap: 6 }}>
              <button className="btn sm accent" disabled={busy} onClick={() => run("win_quotation", { id: q.id })}>Won: make the order</button>
              {losing === q.id
                ? <><input value={reason} placeholder="Why (optional)" onChange={(e) => setReason(e.target.value)} aria-label="Why it was lost" />
                  <button className="btn sm" disabled={busy} onClick={() => run("lose_quotation", { id: q.id, reason }, () => setLosing(null))}>Lost</button></>
                : <button className="btn sm ghost" onClick={() => { setLosing(q.id); setReason(""); }}>Lost…</button>}
            </span></Edits>}</td>
          </tr>))}
        </tbody>
      </table></div>
    </Panel>
  </div>;
}

// ------------------------------------------------------------------------------------------------ deliveries
function Deliveries({ res, ds, sel }: { res: SalesView; ds: Dataset; sel?: string }) {
  const { busy, run, banners } = useAction();
  const [pick, setPick] = useState<Set<string> | null>(null);
  const free = res.to_deliver.filter((t) => !t.credit_block);
  const chosen = pick ?? new Set(free.map((t) => t.order));
  const open = res.deliveries.find((d) => d.id === sel);
  const toggle = (id: string) => { const n = new Set(chosen); if (n.has(id)) n.delete(id); else n.add(id); setPick(n); };
  return <div className="stack">
    {banners}
    {open && <DeliveryDetail d={open} ds={ds} />}
    <Panel flush title={`Due to ship in the next ${plural(ds.sales?.delivery_days ?? 3, "day")}`} actions={<Edits>
      <button className="btn sm accent" disabled={busy || chosen.size === 0}
        onClick={() => run("create_deliveries", { lines: [...chosen].map((order) => ({ order })) }, () => setPick(null))}>
        Make deliveries for {plural(chosen.size, "line")}</button></Edits>}>
      {res.to_deliver.length === 0 ? <p className="faint" style={{ padding: "8px 12px" }}>Nothing is due to ship that is not on a delivery already.</p> :
        <div className="table-wrap"><table className="t">
          <thead><tr><th /><th>Order line</th><th>Customer</th><th>Product</th><th className="num">Quantity</th><th>From</th><th>Ships</th></tr></thead>
          <tbody>{res.to_deliver.map((t) => (
            <tr key={t.order}>
              <td>{t.credit_block ? <Badge sev="error">credit block</Badge>
                : <input type="checkbox" checked={chosen.has(t.order)} onChange={() => toggle(t.order)} aria-label={`Deliver ${t.order}`} />}</td>
              <td><a href={href("selling", "orders", t.header)}>{t.order}</a></td><td><Loc id={t.customer} /></td><td><Prod id={t.product} /></td>
              <td className="num">{qty(t.qty)}</td><td>{t.ship_from ? <Loc id={t.ship_from} /> : "—"}</td><td>{day(t.ship_date)}</td>
            </tr>))}
          </tbody>
        </table></div>}
    </Panel>
    <Panel flush title="Deliveries">
      {res.deliveries.length === 0 ? <p className="faint" style={{ padding: "8px 12px" }}>No deliveries yet.</p> :
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Delivery</th><th>Customer</th><th>From</th><th>Planned</th><th className="num">Quantity</th><th>Packed</th><th>Status</th></tr></thead>
          <tbody>{res.deliveries.map((d) => (
            <tr key={d.id} className={`clickable ${sel === d.id ? "selected" : ""}`} onClick={() => go("selling", "deliver", sel === d.id ? undefined : d.id)}>
              <td><b>{d.id}</b></td><td><Loc id={d.customer} /></td><td><Loc id={d.ship_from} /></td><td>{day(d.planned_on)}</td>
              <td className="num">{qty(d.qty)}</td><td>{d.packages ? `${plural(d.packages, "package")}${d.gross_kg ? `, ${qty(d.gross_kg)} kg` : ""}` : "—"}</td>
              <td><Badge sev={DELIVERY_SEV[d.status] ?? "info"}>{d.status}</Badge>{d.short > 1e-9 && <> <Badge sev="warning">{qty(d.short)} short</Badge></>}
                {d.invoiced && <span className="faint small"> invoiced</span>}</td>
            </tr>))}
          </tbody>
        </table></div>}
    </Panel>
  </div>;
}

function DeliveryDetail({ d, ds }: { d: DeliveryView; ds: Dataset }) {
  const rec = (ds.deliveries ?? []).find((x) => x.id === d.id);
  const { busy, run, banners } = useAction();
  const [picked, setPicked] = useState<Record<string, number>>({});
  const [received, setReceived] = useState<Record<string, number>>({});
  const [packages, setPackages] = useState(1);
  const [by, setBy] = useState("");
  const [on, setOn] = useState(ds.settings.planning_start);
  const ro = useReadOnly();
  if (!rec) return null;
  const shipped = !!rec.issued_on;
  return <Panel title={<>Delivery {d.id} · <Loc id={d.customer} /></>} actions={<button className="btn sm ghost" onClick={() => go("selling", "deliver")}>Close</button>}>
    {banners}
    <div className="table-wrap"><table className="t">
      <thead><tr><th>Order line</th><th>Product</th><th className="num">To deliver</th><th className="num">Picked</th>{shipped && <th className="num">Signed for</th>}<th>Batch</th></tr></thead>
      <tbody>{rec.lines.map((l) => (
        <tr key={l.order}>
          <td>{l.order}</td><td><Prod id={l.product} /></td><td className="num">{qty(l.qty)}</td>
          <td className="num">{shipped || ro ? qty(l.picked ?? l.qty)
            : <input type="number" min={0} max={l.qty} step="any" style={{ width: 90 }} value={picked[l.order] ?? l.picked ?? l.qty}
              onChange={(e) => setPicked({ ...picked, [l.order]: Number(e.target.value) })} aria-label={`Picked on ${l.order}`} />}</td>
          {shipped && <td className="num">{rec.pod_on || ro ? qty(l.received ?? l.picked ?? l.qty)
            : <input type="number" min={0} step="any" style={{ width: 90 }} value={received[l.order] ?? l.picked ?? l.qty}
              onChange={(e) => setReceived({ ...received, [l.order]: Number(e.target.value) })} aria-label={`Signed for on ${l.order}`} />}</td>}
          <td>{l.batch ?? (shipped ? "" : "first expiring")}</td>
        </tr>))}
      </tbody>
    </table></div>
    <Edits><div className="row wrap" style={{ marginTop: 10, gap: 8, alignItems: "flex-end" }}>
      {!shipped && <>
        <button className="btn sm" disabled={busy} onClick={() => run("pick", { id: d.id, lines: rec.lines.map((l) => ({ order: l.order, picked: picked[l.order] ?? l.picked ?? l.qty })) })}>
          {rec.lines.some((l) => l.picked != null) ? "Picked again" : "Picked"}</button>
        <label className="field"><span className="label">Packages</span><input type="number" min={1} value={packages} style={{ width: 80 }}
          onChange={(e) => setPackages(Math.max(1, Number(e.target.value)))} aria-label="Packages" /></label>
        <button className="btn sm" disabled={busy} onClick={() => run("pack", { id: d.id, packages })}>Packed</button>
        <label className="field"><span className="label">Ships on</span><input type="date" value={on} onChange={(e) => setOn(e.target.value)} aria-label="Ships on" /></label>
        <button className="btn sm accent" disabled={busy} onClick={() => run("issue", { id: d.id, date: on })}>Ship it</button>
        <button className="btn sm ghost" disabled={busy} onClick={() => run("cancel_delivery", { id: d.id }, () => go("selling", "deliver"))}>Cancel the delivery</button>
      </>}
      {shipped && !rec.pod_on && <>
        <label className="field"><span className="label">Signed by</span><input value={by} onChange={(e) => setBy(e.target.value)} aria-label="Signed by" /></label>
        <label className="field"><span className="label">Received on</span><input type="date" value={on < rec.issued_on! ? rec.issued_on! : on} min={rec.issued_on!}
          onChange={(e) => setOn(e.target.value)} aria-label="Received on" /></label>
        <button className="btn sm accent" disabled={busy} onClick={() => run("proof", { id: d.id, by, date: on < rec.issued_on! ? rec.issued_on! : on,
          lines: rec.lines.filter((l) => received[l.order] != null).map((l) => ({ order: l.order, received: received[l.order] })) })}>Signed for</button>
      </>}
    </div></Edits>
    {shipped && <p className="faint small">Shipped {day(rec.issued_on)}{rec.pod_on ? `, delivered ${day(rec.pod_on)}${rec.pod_by ? ` (signed by ${rec.pod_by})` : ""}` : ""}.
      {" "}<a href={href("selling", "bill")}>Invoice it</a>.</p>}
  </Panel>;
}

// ------------------------------------------------------------------------------------------------ invoices
function Invoices({ res, ds, sel }: { res: SalesView; ds: Dataset; sel?: string }) {
  const { busy, run, banners } = useAction();
  const [on, setOn] = useState(ds.settings.planning_start);
  const [all, setAll] = useState(false);
  const value = res.to_bill.reduce((a, b) => a + (b.value ?? 0), 0);
  const rows = res.invoices.filter((i) => all || i.open > 0.005);
  const open = res.invoices.find((i) => i.id === sel);
  return <div className="stack">
    {banners}
    {open && <InvoiceDetail i={open} ds={ds} res={res} />}
    <Panel flush title="Shipped, not invoiced" actions={<Edits><span className="row" style={{ gap: 6 }}>
      <input type="date" value={on} onChange={(e) => setOn(e.target.value)} aria-label="Invoice date" />
      <button className="btn sm accent" disabled={busy || res.to_bill.length === 0} onClick={() => run("create_invoices", { date: on })}>
        Invoice {exactMoney(value, res.currency)}</button></span></Edits>}>
      {res.to_bill.length === 0 ? <p className="faint" style={{ padding: "8px 12px" }}>Everything shipped has been invoiced.</p> :
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Order line</th><th>Customer</th><th>Product</th><th>Shipped</th><th className="num">Quantity</th><th className="num">Price</th><th className="num">Value</th></tr></thead>
          <tbody>{res.to_bill.map((b) => (
            <tr key={`${b.order}|${b.delivered_on}`}>
              <td>{b.order}</td><td><Loc id={b.customer} /></td><td><Prod id={b.product} /></td><td>{day(b.delivered_on)}</td>
              <td className="num">{qty(b.qty)}</td><td className="num">{b.price != null ? unitMoney(b.price, res.currency) : <Badge sev="error">no price</Badge>}</td>
              <td className="num">{b.value != null ? exactMoney(b.value, res.currency) : "—"}</td>
            </tr>))}
          </tbody>
        </table></div>}
    </Panel>
    <Panel flush title="Invoices and credit notes" actions={<label className="row small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Show settled</label>}>
      {rows.length === 0 ? <p className="faint" style={{ padding: "8px 12px" }}>{res.invoices.length ? "Everything is settled." : "No invoices yet."}</p> :
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Number</th><th>Customer</th><th>Date</th><th>Due</th><th className="num">Total</th><th className="num">Open</th><th>Status</th></tr></thead>
          <tbody>{rows.map((i) => (
            <tr key={i.id} className={`clickable ${sel === i.id ? "selected" : ""}`} onClick={() => go("selling", "bill", sel === i.id ? undefined : i.id)}>
              <td><b>{i.id}</b>{i.kind === "credit_note" && <div className="faint small">credit note</div>}</td><td><Loc id={i.customer} /></td>
              <td>{day(i.date)}</td><td>{day(i.due_date)}{i.discount_until && <div className="faint small">{exactMoney(i.discount_amount, res.currency)} off by {day(i.discount_until)}</div>}</td>
              <td className="num">{exactMoney(i.kind === "credit_note" ? -i.total : i.total, res.currency)}</td>
              <td className="num">{exactMoney(i.kind === "credit_note" ? -i.open : i.open, res.currency)}</td>
              <td><Badge sev={INVOICE_SEV[i.status] ?? "info"}>{i.status}{i.days_overdue ? ` ${i.days_overdue} d` : ""}</Badge></td>
            </tr>))}
          </tbody>
        </table></div>}
    </Panel>
  </div>;
}

function InvoiceDetail({ i, ds, res }: { i: InvoiceView; ds: Dataset; res: SalesView }) {
  const rec = (ds.invoices ?? []).find((x) => x.id === i.id);
  const { busy, run, banners } = useAction();
  const [amount, setAmount] = useState<number | null>(null);
  const [on, setOn] = useState(ds.settings.planning_start);
  const [ref, setRef] = useState("");
  if (!rec) return null;
  const credit = i.kind === "credit_note";
  const suggested = i.discount_until && on <= i.discount_until ? i.total - i.discount_amount : i.open;
  return <Panel title={<>{credit ? "Credit note" : "Invoice"} {i.id} · <Loc id={i.customer} /></>} actions={<>
    <DocButtons kind="invoice" id={i.id} ds={ds} /><button className="btn sm ghost" onClick={() => go("selling", "bill")}>Close</button></>}>
    {banners}
    <div className="grid-auto">
      <StatTile label="Net" value={exactMoney(i.net, res.currency)} sub={`tax ${exactMoney(i.tax, res.currency)}`} />
      <StatTile label="Total" value={exactMoney(i.total, res.currency)} />
      <StatTile label={credit ? "To pay out" : "Open"} value={exactMoney(i.open, res.currency)} sub={i.status} tone={i.status === "overdue" ? "hl" : undefined} />
      <StatTile label="Due" value={day(i.due_date)} sub={i.discount_until ? `${exactMoney(i.discount_amount, res.currency)} off by ${day(i.discount_until)}` : undefined} />
    </div>
    <div className="table-wrap"><table className="t">
      <thead><tr><th>Order line</th><th>Product</th><th className="num">Quantity</th><th className="num">Price</th><th className="num">Amount</th></tr></thead>
      <tbody>{rec.lines.map((l, n) => <tr key={n}><td>{l.order ?? "—"}</td><td><Prod id={l.product} /></td><td className="num">{qty(l.qty)}</td>
        <td className="num">{unitMoney(l.price, res.currency)}</td><td className="num">{exactMoney(l.qty * l.price, res.currency)}</td></tr>)}</tbody>
    </table></div>
    {(rec.payments ?? []).length > 0 && <p className="small">{credit ? "Paid out" : "Payments"}: {(rec.payments ?? []).map((p) =>
      `${exactMoney(p.amount, res.currency)} on ${day(p.date)}${p.discount ? ` (+${exactMoney(p.discount, res.currency)} discount)` : ""}${p.reference ? ` · ${p.reference}` : ""}`).join("; ")}</p>}
    {i.open > 0.005 && !rec.cancelled && <Edits><div className="row wrap" style={{ marginTop: 10, gap: 8, alignItems: "flex-end" }}>
      <label className="field"><span className="label">Amount</span><input type="number" min={0} step="any" style={{ width: 120 }}
        value={amount ?? Math.round(suggested * 100) / 100} onChange={(e) => setAmount(Number(e.target.value))} aria-label="Amount" /></label>
      <label className="field"><span className="label">On</span><input type="date" value={on} onChange={(e) => setOn(e.target.value)} aria-label="Paid on" /></label>
      <label className="field"><span className="label">Bank reference</span><input value={ref} onChange={(e) => setRef(e.target.value)} aria-label="Bank reference" /></label>
      <button className="btn sm accent" disabled={busy} onClick={() => run("pay", { id: i.id, amount: amount ?? Math.round(suggested * 100) / 100, date: on, reference: ref }, () => setAmount(null))}>
        {credit ? "Paid out" : "Payment received"}</button>
      {!(rec.payments ?? []).length && <button className="btn sm ghost" disabled={busy} onClick={() => run("cancel_invoice", { id: i.id })}>Cancel it</button>}
    </div></Edits>}
  </Panel>;
}

// ------------------------------------------------------------------------------------------------ returns
function Returns({ res, ds }: { res: SalesView; ds: Dataset }) {
  const { busy, run, banners } = useAction();
  const shipped = res.orders.flatMap((o) => o.lines.filter((l) => l.delivered - l.returned > 1e-9).map((l) => ({ o, l })));
  const [line, setLine] = useState(shipped[0]?.l.id ?? "");
  const [n, setN] = useState(1);
  const [reason, setReason] = useState("");
  const [stock, setStock] = useState<"quality" | "blocked" | "unrestricted">("quality");
  const pickd = shipped.find((x) => x.l.id === line);
  return <div className="stack">
    {banners}
    <Panel title="A customer sends goods back">
      {shipped.length === 0 ? <p className="faint">Nothing has been shipped on an order yet.</p> :
        <Edits><div className="row wrap" style={{ gap: 10, alignItems: "flex-end" }}>
          <label className="field"><span className="label">Order line</span>
            <select value={line} onChange={(e) => setLine(e.target.value)} aria-label="Order line returned">
              {shipped.map(({ o, l }) => <option key={l.id} value={l.id}>{l.id} · {namesOf(ds).loc(o.customer)} · {namesOf(ds).prod(l.product)} ({qty(l.delivered - l.returned)} shipped)</option>)}</select></label>
          <label className="field"><span className="label">Quantity</span><input type="number" min={0} step="any" value={n} style={{ width: 90 }}
            onChange={(e) => setN(Number(e.target.value))} aria-label="Quantity returned" /></label>
          <label className="field"><span className="label">Why</span><input value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Why it comes back" /></label>
          <label className="field"><span className="label">Into</span><select value={stock} onChange={(e) => setStock(e.target.value as typeof stock)} aria-label="Comes back into">
            <option value="quality">quality inspection</option><option value="blocked">blocked stock</option><option value="unrestricted">stock ready to sell</option></select></label>
          <button className="btn sm accent" disabled={busy || !pickd || n <= 0} onClick={() => pickd && run("create_return", {
            customer: pickd.o.customer, product: pickd.l.product, qty: n, order: pickd.l.id, reason, stock_type: stock })}>Agree the return</button>
        </div></Edits>}
    </Panel>
    <Panel flush title="Returns">
      {res.returns.length === 0 ? <p className="faint" style={{ padding: "8px 12px" }}>No returns.</p> :
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Return</th><th>Customer</th><th>Product</th><th className="num">Quantity</th><th className="num">Value</th><th>Status</th><th /></tr></thead>
          <tbody>{res.returns.map((r) => (
            <tr key={r.id}>
              <td><b>{r.id}</b>{r.order && <div className="faint small">{r.order}</div>}</td><td><Loc id={r.customer} /></td><td><Prod id={r.product} /></td>
              <td className="num">{qty(r.received_qty ?? r.qty)}</td><td className="num">{exactMoney(r.value, res.currency)}</td>
              <td><Badge sev={r.status === "credited" ? "ok" : "info"}>{r.status}</Badge>{r.credit_note && <> <a href={href("selling", "bill", r.credit_note)}>{r.credit_note}</a></>}</td>
              <td><Edits>{r.status === "expected" ? <button className="btn sm" disabled={busy} onClick={() => run("receive_return", { id: r.id })}>Goods are back</button>
                : r.status === "received" ? <button className="btn sm accent" disabled={busy} onClick={() => run("credit_return", { id: r.id })}>Credit it</button> : null}</Edits></td>
            </tr>))}
          </tbody>
        </table></div>}
    </Panel>
  </div>;
}

// ------------------------------------------------------------------------------------------------ customers
function Customers({ res }: { res: SalesView }) {
  if (res.customers.length === 0) return <Panel><Empty title="No customers yet">Customers appear here once they order or have sales data.</Empty></Panel>;
  return <Panel flush title="What customers owe" actions={<>
    <a className="btn sm ghost" href={href("data", "customers")}>Edit customer sales data</a>
    <a className="btn sm ghost" href={href("data", "payment_terms")}>Payment terms</a>
    <a className="btn sm ghost" href={href("data", "customer_prices")}>Prices</a></>}>
    <div className="table-wrap"><table className="t">
      <thead><tr><th>Customer</th><th>Terms</th><th className="num">Open orders</th><th className="num">Shipped, not invoiced</th><th className="num">Unpaid</th>
        <th className="num">Owes in all</th><th className="num">Credit limit</th><th className="num">Left</th><th className="num">Overdue</th></tr></thead>
      <tbody>{res.customers.map((c) => (
        <tr key={c.customer}>
          <td><b><Loc id={c.customer} /></b>{c.blocked && <> <Badge sev="error">blocked</Badge></>}</td><td className="small">{c.payment_terms}</td>
          <td className="num">{exactMoney(c.open_orders, res.currency)}</td><td className="num">{exactMoney(c.to_bill, res.currency)}</td>
          <td className="num">{exactMoney(c.receivable, res.currency)}</td><td className="num"><b>{exactMoney(c.exposure, res.currency)}</b></td>
          <td className="num">{c.credit_limit != null ? exactMoney(c.credit_limit, res.currency) : "no limit"}</td>
          <td className="num">{c.headroom != null ? <span className={c.headroom < 0 ? "warn-text" : undefined}>{exactMoney(c.headroom, res.currency)}</span> : "—"}</td>
          <td className="num">{c.overdue > 0 ? <Badge sev="error">{exactMoney(c.overdue, res.currency)}</Badge> : "—"}</td>
        </tr>))}
      </tbody>
    </table></div>
    <p className="faint small" style={{ padding: "0 12px" }}>Amounts include tax. What a customer owes counts their open order lines, goods shipped and not invoiced,
      and unpaid invoices less credit notes not yet paid out.</p>
  </Panel>;
}
