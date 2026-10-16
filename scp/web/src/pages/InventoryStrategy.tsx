// Strategy advisor (enterprise 4.3, S/4 guide §5.4): how many days customers accept to wait for each product, against
// the time to deliver it from stock, to assemble it from parts in stock and to make it from scratch. The strategy that
// fits, whether today's meets the wait, and one click to plan it so.
import { useEffect, useState } from "react";
import type { Dataset, StrategyAdvice } from "../api/types";
import { api } from "../api/client";
import { Badge, Empty, Panel } from "../components/ui";
import { useLatest } from "../lib/latest";
import { namesOf } from "../lib/names";
import { store, useReadOnly, useStore } from "../state/store";

const PLANNED: Record<string, string> = {
  MTS: "Made to stock", MTS_CONSUME: "Made to stock, orders using up the forecast", MTO: "Made to order",
  ATO: "Parts to the forecast, assembled to order", ASSEMBLY: "Made to stock, its parents using up its forecast",
};
const DO: Record<string, string> = { MTO: "Make to order", ATO: "Assemble to order", MTS_CONSUME: "Make to stock" };
const d = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(v % 1 ? 1 : 0)} d`);

function WaitInput({ row, ro }: { row: StrategyAdvice; ro: boolean }) {
  const saved = row.wait_days === null || row.wait_days === undefined ? "" : String(row.wait_days);
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);
  const commit = () => {
    if (draft === saved) return;
    const v = draft.trim() === "" ? null : Number(draft);
    if (v !== null && (!Number.isFinite(v) || v < 0 || v > 365)) { setDraft(saved); return; }
    store.update((x) => {
      const p = (x.products ?? []).find((q) => q.id === row.product);
      if (p) p.customer_wait_days = v;
    });
  };
  return <input className="input num" type="number" min={0} max={365} step="any" style={{ width: 70 }} disabled={ro}
    aria-label={`Days customers wait for ${row.product}`} placeholder="days" value={draft}
    onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />;
}

/** Plan the product as advised, where the strategy planning its demand is read (the nearest place upstream of the
 * customer with a record of it, else where it is made or bought). */
function planAs(row: StrategyAdvice) {
  const at = row.set_at, s = row.advised;
  if (!at || !s) return;
  store.update((x) => {
    const lps = (x.location_products ??= []);
    const lp = lps.find((l) => l.location === at && l.product === row.product);
    if (lp) lp.strategy = s;
    else lps.push({ location: at, product: row.product, strategy: s } as (typeof lps)[number]);
  });
}

export function StrategyView({ ds }: { ds: Dataset }) {
  const revision = useStore((s) => s.revision);
  const ro = useReadOnly();
  const res = useLatest(() => api.strategyAdvice(ds), [revision]);
  const nm = namesOf(ds);
  const adv = res.value;

  const intro = (
    <Panel title="Planning strategy from lead times">
      <p className="small" style={{ maxWidth: "72ch" }}>
        How long do customers accept to wait for each product? If that is longer than making it from scratch, it can be
        <b> made to order</b>, with no stock and no forecast. If it is only long enough to assemble it, keep its parts to the
        forecast and <b>assemble to order</b>. Shorter than that, keep it <b>in stock</b> to the forecast. The times follow each
        product's usual path: the delivery to the customer, making it at the plant, and buying or making its parts.
      </p>
    </Panel>
  );
  if (res.error) return <div className="stack">{intro}<div className="banner error"><Badge sev="error">Not worked out</Badge>{res.error}</div></div>;
  if (!adv) return <div className="stack">{intro}<div className="banner info" role="status">Working out the lead times…</div></div>;
  if (!adv.rows.length) return <div className="stack">{intro}<Panel><Empty title="Nothing sold yet"><p>{adv.notes[0]}</p></Empty></Panel></div>;

  const judged = adv.rows.filter((r) => r.fits !== null && r.fits !== undefined);
  const late = judged.filter((r) => r.fits === false);
  const other = judged.filter((r) => r.fits && r.advised && r.advised !== r.strategy
    && !(r.advised === "MTS_CONSUME" && ["MTS", "ASSEMBLY"].includes(r.strategy)));
  return <div className="stack">
    {intro}
    <Panel title="Products">
      <p role="status">
        {judged.length === 0 ? "Enter the days customers wait to see which strategy fits."
          : <>{judged.length} of {adv.rows.length} products judged: {late.length ? <b>{late.length} planned in a way that makes orders late</b> : "every one meets the wait"}
            {other.length > 0 && <>; {other.length} could be planned another way</>}.</>}
      </p>
      <div className="table-wrap"><table className="t" aria-label="Strategies">
        <thead><tr><th>Product</th><th>Sold to</th><th className="num">Customers wait</th><th className="num">From stock</th>
          <th className="num">To assemble</th><th className="num">From scratch</th><th>Planned now</th><th>Fits</th><th>Advised</th><th /></tr></thead>
        <tbody>
          {adv.rows.map((r) => <tr key={r.product}>
            <td>{nm.prod(r.product)}{r.kept_at && <div className="faint small">{r.made ? "made" : "bought"} at {nm.loc(r.kept_at)}</div>}</td>
            <td>{nm.loc(r.sold_at)}</td>
            <td className="num"><WaitInput row={r} ro={ro} /></td>
            <td className="num">{d(r.from_stock_days)}</td><td className="num">{d(r.assemble_days)}</td><td className="num">{d(r.scratch_days)}</td>
            <td className="small">{PLANNED[r.strategy] ?? r.strategy}
              {r.set_at && r.set_at !== r.kept_at && <div className="faint">set at {nm.loc(r.set_at)}</div>}</td>
            <td>{r.fits === null || r.fits === undefined ? <span className="faint">—</span>
              : r.fits ? <Badge sev="ok">Meets the wait</Badge> : <Badge sev="error">Orders late</Badge>}</td>
            <td className="small" style={{ minWidth: 220 }}>{r.advised && <b>{DO[r.advised]}. </b>}{r.reason}</td>
            <td>{r.advised && r.advised !== r.strategy && r.set_at && !ro
              && !(r.advised === "MTS_CONSUME" && ["MTS", "ASSEMBLY"].includes(r.strategy))
              && <button className="btn sm" onClick={() => planAs(r)}>{DO[r.advised]}</button>}</td>
          </tr>)}
        </tbody>
      </table></div>
      {adv.notes.map((n) => <p key={n} className="small faint">{n}</p>)}
    </Panel>
  </div>;
}
