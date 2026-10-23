// Enterprise 7.3: several companies in one network (S/4 guide §17.5). A transfer between places of two companies is
// an inter-company order: the one that ships sells to the one that receives at the transfer price, bills it on a GST
// tax invoice from its own series, and each keeps its stock in its own books. The group's books keep the goods at
// what they cost the group; the difference is the profit still in stock between the companies.
// Engine: scp/intercompany, scp/actuals/transfer_price.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Dataset, IcInvoiceRow, IntercompanyAction, IntercompanyActionInput, IntercompanyView } from "../api/types";
import { Badge, Edits, Empty, Panel, StageHeader, StatTile, Tabs } from "../components/ui";
import { day, exactMoney, money, plural, qty } from "../lib/format";
import { icInvoiceDocument } from "../lib/icinvoicedoc";
import { Msg, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { download } from "../lib/tabular";
import { store, useStore } from "../state/store";

type View = "companies" | "billing" | "invoices" | "orders";

function useGroup(ds: Dataset) {
  const [v, setV] = useState<IntercompanyView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.intercompany(ds).then((x) => { if (live) { setV(x); setErr(null); } }, (e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [ds]);
  return { v, err };
}

function useStep() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: IntercompanyAction, extra: Partial<IntercompanyActionInput> = {}) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const before = store.get().dataset!;
      const out = await api.intercompanyAct(before, action, extra);
      store.replace(out.dataset, before);
      setMsg(out.message);
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

export function Group({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const view = (route[1] as View) || "companies";
  const { v, err } = useGroup(ds);
  const step = useStep();
  const cur = ds.settings.currency;
  const n = (ds.entities ?? []).length + 1;
  const head = <StageHeader title="Group companies" kicker="What the group's companies sell each other, and what is still in stock between them."
    how={<>A place belongs to one company of the group (a place without one belongs to {ds.settings.company_name}).
      A stock transfer between two companies is an <b>inter-company order</b>: planning moves the goods as inside one
      company, and the company that ships sells them to the one that receives at the <b>transfer price</b> — a fixed
      price, the cost plus a mark-up, or the selling price less a margin, the most specific of the{" "}
      <a href={href("data", "transfer_prices")}>transfer prices</a> that fits. Each shipment is <b>billed</b> on a GST
      tax invoice from the seller's own series (CGST and SGST in one state, IGST across); a transfer between two GST
      registrations of one company is billed too, at cost. The receiving company's books take the goods at what it
      paid; the group's books keep them at what they cost the group, and the difference is the profit still in stock.
      An invoice is <b>settled</b> when the buyer pays it: each company's <a href={href("accounts")}>accounts</a>
      carry what the others owe it and what it owes them until then.</>}
    answer={v ? <>{plural(n, "company", "companies")}; {v.consolidation.sales ? `${money(v.consolidation.sales, cur)} sold between them, ${money(v.consolidation.margin, cur)} margin, ${money(v.consolidation.unrealised, cur)} of it still in stock` : "nothing shipped between them yet"}
      {v.due ? `; ${plural(v.due, "shipment")} to bill (${money(v.due_value, cur)})` : "; everything shipped is billed"}.</> : undefined} />;
  return (
    <div>{head}<div className="content stack">
      <Tabs<View> value={view} onChange={(x) => go("group", x)} tabs={[
        { id: "companies", label: "Companies", count: n },
        { id: "billing", label: "To bill", count: v?.due || undefined },
        { id: "invoices", label: "Invoices", count: v?.invoices.length || undefined },
        { id: "orders", label: "Inter-company orders", count: v?.orders.length || undefined },
      ]} />
      {err && <div className="banner error" role="alert"><Badge sev="error">Could not read the group</Badge>{err}</div>}
      {step.banners}
      {!v && !err && <p className="faint">Reading both sets of books…</p>}
      {v && v.notes.map((t) => <div key={t} className="banner info" role="note"><Msg text={t} /></div>)}
      {v && view === "companies" && <Companies ds={ds} v={v} />}
      {v && view === "billing" && <Billing ds={ds} v={v} step={step} />}
      {v && view === "invoices" && <Invoices ds={ds} v={v} step={step} />}
      {v && view === "orders" && <Orders ds={ds} v={v} />}
    </div></div>
  );
}

function Companies({ ds, v }: { ds: Dataset; v: IntercompanyView }) {
  const nm = useNames();
  const cur = ds.settings.currency;
  const c = v.consolidation;
  return <>
    <div className="grid-auto">
      <StatTile label="Sold between companies" value={money(c.sales, cur)} sub={`cost ${money(c.cost, cur)}`} />
      <StatTile label="Margin between them" value={money(c.margin, cur)} sub={`${money(c.realised, cur)} sold on to customers`} />
      <StatTile label="Profit still in stock" value={money(c.unrealised, cur)} tone={c.unrealised > 0.005 ? "hl" : undefined}
        sub="taken out in the group's accounts" />
      <StatTile label="Stock, the group's books" value={money(c.stock_group + c.transit_group, cur)}
        sub={`${money(c.stock_entities + c.transit_entities, cur)} in the companies' own`} />
    </div>
    <Panel flush title={`The companies, ${day(v.period_start)} to ${day(v.period_end)}`}
      actions={<a className="btn sm" href={href("data", "entities")}>Companies and their GSTINs</a>}>
      <div className="table-wrap"><table className="t" aria-label="Companies of the group">
        <thead><tr><th>Company</th><th>GSTIN</th><th>Places</th><th className="num">Stock in its books</th><th className="num">Sold to the group</th>
          <th className="num">Cost of it</th><th className="num">Margin</th><th className="num">Bought from the group</th><th className="num">Billed</th>
          <th className="num">Owed to it</th><th className="num">It owes</th></tr></thead>
        <tbody>{v.entities.map((e) => <tr key={e.id || "-"}>
          <td><b>{e.name}</b>{!e.id && <div className="faint">this company</div>}</td><td className="mono">{e.tax_id || "—"}</td>
          <td>{e.places.map((p) => nm.loc(p)).join(", ") || "—"}</td>
          <td className="num">{exactMoney(e.stock, cur)}</td><td className="num">{exactMoney(e.sales, cur)}</td>
          <td className="num">{exactMoney(e.cost, cur)}</td><td className="num">{exactMoney(e.margin, cur)}</td>
          <td className="num">{exactMoney(e.purchases, cur)}</td><td className="num">{exactMoney(e.billed, cur)}</td>
          <td className="num">{exactMoney(e.receivable ?? 0, cur)}</td><td className="num">{exactMoney(e.payable ?? 0, cur)}</td>
        </tr>)}</tbody>
      </table></div>
    </Panel>
    <Panel title="From the companies' books to the group's">
      <div className="table-wrap"><table className="t" aria-label="Elimination">
        <tbody>
          <tr><td>Stock in the companies' own books</td><td className="num">{exactMoney(c.stock_entities, cur)}</td></tr>
          <tr><td>On the way between places, at what it will come in at</td><td className="num">{exactMoney(c.transit_entities, cur)}</td></tr>
          <tr><td>Less the profit still in stock between companies</td><td className="num">−{exactMoney(c.unrealised, cur)}</td></tr>
          <tr><th>Stock in the group's books</th><th className="num">{exactMoney(c.stock_group + c.transit_group, cur)}</th></tr>
          <tr><td>Cost of sales: the companies' / the group's</td><td className="num">{exactMoney(c.cost_of_sales_entities, cur)} / {exactMoney(c.cost_of_sales_group, cur)}</td></tr>
          <tr><td>Margin between them in these books / on goods shipped before go-live</td><td className="num">{exactMoney(c.margin, cur)} / {exactMoney(c.margin_before, cur)}</td></tr>
          <tr><td>Of it, sold on out of the group</td><td className="num">{exactMoney(c.realised, cur)}</td></tr>
          {Math.abs(c.differences_entities - c.differences_group) > 0.005 &&
            <tr><td>Price differences from transfer prices (a standard price where it arrived)</td><td className="num">{exactMoney(c.differences_entities - c.differences_group, cur)}</td></tr>}
        </tbody>
      </table></div>
    </Panel>
  </>;
}

function Billing({ ds, v, step }: { ds: Dataset; v: IntercompanyView; step: Step }) {
  const nm = useNames();
  const cur = ds.settings.currency;
  const [no, setNo] = useState("");
  const due = v.shipments.filter((s) => Math.abs(s.due_qty) > 1e-9);
  const party = (id: string) => v.entities.find((e) => e.id === id)?.name ?? id;
  return <>
    <Panel title="Billing due list" actions={due.length ? <Edits><div className="row">
      <input className="input sm" placeholder="Invoice number (optional)" aria-label="Invoice number" value={no} maxLength={16}
        onChange={(e) => setNo(e.target.value)} />
      <button className="btn sm primary" disabled={step.busy}
        onClick={() => step.run("bill", { id: no.trim() || null, date: v.as_of }).then(() => setNo(""))}>
        Bill {plural(due.length, "shipment")}</button></div></Edits> : undefined}>
      {!due.length ? <Empty title="Nothing to bill">Every shipment between companies or GST registrations is on an invoice.</Empty> :
        <p className="faint">Billing puts the shipments between one pair of places on one invoice dated {day(v.as_of)}; what came back after it was billed goes on a credit note at the price it was billed at.</p>}
    </Panel>
    <Panel flush title="Shipments between companies and registrations, latest first">
      {!v.shipments.length ? <div className="pad"><Empty title="No shipments yet">Ship a transfer to a place of another company on <a href={href("execution")}>Stock &amp; actuals</a>.</Empty></div> :
        <div className="table-wrap"><table className="t" aria-label="Shipments">
          <thead><tr><th>Shipped</th><th>Transfer</th><th>Goods</th><th>From → to</th><th>Seller → buyer</th><th className="num">Qty</th>
            <th className="num">Cost each</th><th className="num">Price each</th><th className="num">Amount</th><th className="num">Margin</th><th>Billed</th></tr></thead>
          <tbody>{v.shipments.map((s) => <tr key={s.movement}>
            <td>{day(s.date)}<div className="faint mono">{s.movement}</div></td><td className="mono">{s.order}</td><td>{s.product_name}</td>
            <td>{nm.loc(s.ship_from)} → {nm.loc(s.ship_to)}</td>
            <td>{s.crossing === "entity" ? `${party(s.seller)} → ${party(s.buyer)}` : <>one company, two GSTINs</>}</td>
            <td className="num">{qty(s.qty)}</td><td className="num">{exactMoney(s.cost, cur)}</td>
            <td className="num">{exactMoney(s.price, cur)}<div className="faint">{s.basis}</div></td>
            <td className="num">{exactMoney(s.amount, cur)}</td><td className="num">{s.crossing === "entity" ? exactMoney(s.margin, cur) : "—"}</td>
            <td>{s.invoices.join(", ") || "—"}{Math.abs(s.due_qty) > 1e-9 && <div><Badge sev="warning">{s.due_qty > 0 ? `${qty(s.due_qty)} to bill` : `${qty(-s.due_qty)} to credit`}</Badge></div>}</td>
          </tr>)}</tbody>
        </table></div>}
    </Panel>
  </>;
}

function printInvoice(inv: IcInvoiceRow, ds: Dataset) {
  const html = icInvoiceDocument(inv, ds);
  const w = window.open("", "_blank");
  if (!w) return download(`${inv.id.replace(/[/\\]/g, "-")}.html`, html, "text/html");
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 250);
}

function Invoices({ ds, v, step }: { ds: Dataset; v: IntercompanyView; step: Step }) {
  const cur = ds.settings.currency;
  if (!v.invoices.length) return <Empty title="No inter-company invoices yet">Bill what has been shipped on the <a href={href("group", "billing")}>To bill</a> tab.</Empty>;
  return <Panel flush title="Inter-company invoices and credit notes, latest first">
    <div className="table-wrap"><table className="t" aria-label="Inter-company invoices">
      <thead><tr><th>Number</th><th>Date</th><th>From</th><th>To</th><th>Place of supply</th><th className="num">Taxable value</th>
        <th className="num">CGST</th><th className="num">SGST</th><th className="num">IGST</th><th className="num">Total</th>
        <th className="num">Open</th><th></th></tr></thead>
      <tbody>{v.invoices.map((i) => <tr key={i.id} className={i.cancelled ? "muted" : undefined}>
        <td className="mono"><b>{i.id}</b>{i.kind === "credit_note" && <div><Badge sev="info">credit note</Badge></div>}
          {i.cancelled && <div><Badge sev="error">cancelled</Badge></div>}</td>
        <td>{day(i.date)}</td><td>{i.seller_name}<div className="faint">{i.ship_from_name}</div></td>
        <td>{i.buyer_name}<div className="faint">{i.ship_to_name}</div></td><td>{i.place_of_supply || "—"}</td>
        <td className="num">{exactMoney(i.net, cur)}</td><td className="num">{i.cgst ? exactMoney(i.cgst, cur) : "—"}</td>
        <td className="num">{i.sgst ? exactMoney(i.sgst, cur) : "—"}</td><td className="num">{i.igst ? exactMoney(i.igst, cur) : "—"}</td>
        <td className="num">{exactMoney(i.total, cur)}</td>
        <td className="num">{i.cancelled || i.seller === i.buyer ? "—" : (i.open ?? 0) > 0.005 ? exactMoney(i.open ?? 0, cur) : <Badge sev="ok">settled</Badge>}</td>
        <td><div className="row">
          <button className="btn sm ghost" aria-label={`Print ${i.id}`} title="Three copies: original, duplicate, triplicate"
            onClick={() => printInvoice(i, ds)}>Print</button>
          {!i.cancelled && i.seller !== i.buyer && (i.open ?? 0) > 0.005 && <Edits><button className="btn sm" disabled={step.busy}
            aria-label={`Settle ${i.id}`} title={i.kind === "credit_note" ? "The seller pays it back" : "The buyer pays what is open"}
            onClick={() => step.run("pay", { id: i.id, date: v.as_of })}>Settle</button></Edits>}
          {!i.cancelled && !(i.paid ?? 0) && <Edits><button className="btn sm ghost" disabled={step.busy} aria-label={`Cancel ${i.id}`}
            onClick={() => step.run("cancel", { id: i.id })}>Cancel</button></Edits>}
        </div></td>
      </tr>)}</tbody>
    </table></div>
  </Panel>;
}

function Orders({ ds, v }: { ds: Dataset; v: IntercompanyView }) {
  const nm = useNames();
  const cur = ds.settings.currency;
  const party = (id: string) => v.entities.find((e) => e.id === id)?.name ?? id;
  if (!v.orders.length) return <Empty title="No open inter-company orders">A stock transfer to a place of another company (or another GST registration) is one: the supply plan proposes them like any transfer.</Empty>;
  return <Panel flush title="Open transfers between companies">
    <div className="table-wrap"><table className="t" aria-label="Inter-company orders">
      <thead><tr><th>Transfer</th><th>Goods</th><th>From → to</th><th>Seller → buyer</th><th>Due</th><th className="num">Ordered</th>
        <th className="num">Shipped</th><th className="num">To ship</th><th className="num">Price each</th><th className="num">Value to ship</th></tr></thead>
      <tbody>{v.orders.map((o) => <tr key={o.order}>
        <td className="mono">{o.order}</td><td>{o.product_name}</td><td>{nm.loc(o.ship_from)} → {nm.loc(o.ship_to)}</td>
        <td>{o.seller === o.buyer ? "one company, two GSTINs" : `${party(o.seller)} → ${party(o.buyer)}`}</td><td>{day(o.due_date)}</td>
        <td className="num">{qty(o.ordered)}</td><td className="num">{qty(o.shipped)}</td><td className="num">{qty(o.to_ship)}</td>
        <td className="num">{exactMoney(o.price, cur)}<div className="faint">{o.basis}</div></td><td className="num">{exactMoney(o.value, cur)}</td>
      </tr>)}</tbody>
    </table></div>
  </Panel>;
}
