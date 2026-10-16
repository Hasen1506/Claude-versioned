// Enterprise 6.2: stock in the books. Each place's stock valued from the movement journal and the supplier invoices:
// at the standard (planned) price, or at a moving average that receipts and invoices move. The price differences an
// invoice leaves are booked aside where the stock it priced has already gone. Engine: scp/actuals/valuation.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, ValuationRow } from "../api/types";
import { Badge, Edits, Empty, Panel, StatTile } from "../components/ui";
import { day, exactPrice, money, plural, qty } from "../lib/format";
import { useLatest } from "../lib/latest";
import { Msg, useNames } from "../lib/names";
import { store } from "../state/store";

type Control = "standard" | "moving_average";
const CONTROL: Record<Control, string> = { standard: "standard price", moving_average: "moving average" };

export function Books({ ds }: { ds: Dataset }) {
  const nm = useNames();
  const books = useLatest(() => api.valuation(ds), [ds]);
  const [find, setFind] = useState("");
  const [tab, setTab] = useState<"stock" | "differences" | "postings">("stock");
  const v = books.value;
  const cur = ds.settings.currency;
  const control = (ds.execution?.price_control ?? "standard") as Control;
  const setControl = (c: Control) => store.update((d) => { d.execution = { ...(d.execution ?? {}), price_control: c } as Dataset["execution"]; });
  const q = find.trim().toLowerCase();
  const rows = useMemo(() => (v?.rows ?? []).filter((r) => !q || nm.prod(r.product).toLowerCase().includes(q) || nm.loc(r.location).toLowerCase().includes(q)),
    [v, q, nm]);
  if (books.error) return <div className="banner error"><Badge sev="error">Could not value the stock</Badge>{books.error}</div>;
  if (!v) return <p className="faint">Valuing the stock from the journal…</p>;
  const moved = v.rows.filter((r) => r.control === "moving_average" && Math.abs((r.price ?? r.standard) - r.standard) > 0.005);
  return <div className="stack">
    <p className="small" style={{ margin: 0, maxWidth: "75ch" }}>
      The books value each place's stock from its goods movements and the supplier invoices on {day(v.as_of)}. Planning keeps
      valuing stock at the planned unit value (holding cost, lot sizes), whatever the books say.
    </p>
    <div className="grid-auto">
      <StatTile label="Stock in the books" value={money(v.total_value, cur)} sub={plural(v.rows.length, "product at a place", "products at places")} tone="ink" />
      <StatTile label="Price differences" value={money(v.total_differences, cur)} sub="booked aside, not in stock" tone={Math.abs(v.total_differences) > 0.005 ? "hl" : undefined} />
      <StatTile label="Cost of sales" value={money(v.cost_of_sales, cur)} sub="what sold was worth when it left" />
      <StatTile label="Count differences" value={money(v.count_differences, cur)} sub={v.count_differences >= 0 ? "found more than the books" : "found less than the books"} />
    </div>
    <Edits><div className="row wrap small" style={{ gap: 10 }}>
      <label className="row" style={{ gap: 6 }}>Stock is valued at
        <select className="select" aria-label="Price control" value={control} onChange={(e) => setControl(e.target.value as Control)}>
          <option value="standard">the standard (planned) price</option>
          <option value="moving_average">a moving average of what it cost</option>
        </select></label>
      <span className="faint">unless a product says otherwise (Data → Products, “Price control”).</span>
    </div></Edits>
    {v.notes.map((n) => <div key={n} className="banner info"><span>{n}</span></div>)}
    <div className="seg" role="tablist" aria-label="Books">
      {(["stock", "differences", "postings"] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""}
        onClick={() => setTab(t)}>{t === "stock" ? "Stock value" : t === "differences" ? `Price differences (${v.differences.length})` : `Postings (${v.entries.length})`}</button>)}
    </div>
    {tab === "stock" && <Panel flush title="Stock value by product and place" actions={
      <input className="input" style={{ width: 200 }} placeholder="Find a product or place" aria-label="Find" value={find} onChange={(e) => setFind(e.target.value)} />}>
      {moved.length > 0 && <p className="small" style={{ margin: "8px 12px" }}>{plural(moved.length, "product")} at a moving average {moved.length === 1 ? "stands" : "stand"} away from the standard.</p>}
      {rows.length ? <div className="table-wrap"><table className="t" aria-label="Stock value">
        <thead><tr><th>Product</th><th>Place</th><th>Valued at</th><th className="num">Quantity</th><th className="num">Value</th>
          <th className="num">Price now</th><th className="num">Standard</th><th className="num">Moved by</th></tr></thead>
        <tbody>{rows.map((r) => <Row key={`${r.location}|${r.product}`} r={r} cur={cur} />)}</tbody>
      </table></div> : <Empty title="No stock">Nothing is kept anywhere on {day(v.as_of)}.</Empty>}
    </Panel>}
    {tab === "differences" && <Panel flush title="Price differences: cost the stock did not take">
      {v.differences.length ? <div className="table-wrap"><table className="t" aria-label="Price differences">
        <thead><tr><th>Day</th><th>Product</th><th>Place</th><th>From</th><th className="num">Amount</th><th>Why</th></tr></thead>
        <tbody>{v.differences.map((x, i) => <tr key={i}><td>{day(x.date)}</td><td>{nm.prod(x.product)}</td><td>{nm.loc(x.location)}</td>
          <td>{x.reference ?? "—"}</td><td className="num">{money(x.amount, cur)}</td><td className="small"><Msg text={x.why} /></td></tr>)}</tbody>
      </table></div> : <Empty title="No price differences">Every receipt and invoice went into stock at the price the books hold.</Empty>}
    </Panel>}
    {tab === "postings" && <Panel flush title="Postings that changed the stock value, latest first">
      {v.entries.length ? <div className="table-wrap"><table className="t" aria-label="Valuation postings">
        <thead><tr><th>Day</th><th>Product</th><th>Place</th><th>What</th><th className="num">Quantity</th><th className="num">Value</th>
          <th className="num">Price before</th><th className="num">Price after</th></tr></thead>
        <tbody>{v.entries.map((e, i) => <tr key={i}><td>{day(e.date)}</td><td>{nm.prod(e.product)}</td><td>{nm.loc(e.location)}</td>
          <td><Msg text={e.what} />{e.reference ? <span className="faint small"> · {e.reference}</span> : null}</td>
          <td className="num">{e.qty ? qty(e.qty) : "—"}</td><td className="num">{money(e.amount, cur)}</td>
          <td className="num">{e.price_before != null ? exactPrice(e.price_before, cur) : "—"}</td>
          <td className="num">{e.price_after != null ? exactPrice(e.price_after, cur) : "—"}</td></tr>)}</tbody>
      </table></div> : <Empty title="No postings yet">The journal holds no goods movements.</Empty>}
    </Panel>}
  </div>;
}

function Row({ r, cur }: { r: ValuationRow; cur: string }) {
  const nm = useNames();
  const away = r.control === "moving_average" ? (r.price ?? r.standard) - r.standard : 0;
  return <tr><td>{nm.prod(r.product)}</td><td>{nm.loc(r.location)}</td><td>{CONTROL[r.control as Control]}</td>
    <td className="num">{qty(r.qty)}</td><td className="num">{money(r.value, cur)}</td>
    <td className="num">{r.price != null ? exactPrice(r.price, cur) : "—"}</td><td className="num">{exactPrice(r.standard, cur)}</td>
    <td className="num">{Math.abs(away) > 0.005 ? `${away > 0 ? "+" : "−"}${exactPrice(Math.abs(away), cur)}` : "—"}</td></tr>;
}
