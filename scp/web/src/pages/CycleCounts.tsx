// Enterprise 6.2: cycle counting by ABC class. Each place's products are classed by the value they used up (A most),
// each class counted so many times a year; what is due becomes a physical inventory document, counted and posted on
// the sheets below it. Engine: scp/actuals/cycle.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { CyclePlan, Dataset } from "../api/types";
import { Badge, Edits, Panel } from "../components/ui";
import { day, money, pct, plural } from "../lib/format";
import { useLatest } from "../lib/latest";
import { Msg, useNames } from "../lib/names";
import { store } from "../state/store";
import { postAct } from "./ExecutionStock";

type Cls = "A" | "B" | "C";
const STOCKING = new Set(["plant", "dc", "warehouse", "store"]);
const KEY: Record<Cls, "counts_a" | "counts_b" | "counts_c"> = { A: "counts_a", B: "counts_b", C: "counts_c" };

export function CycleCounts({ ds }: { ds: Dataset }) {
  const nm = useNames();
  const [place, setPlace] = useState("");
  const places = useMemo(() => {
    const kept = new Set((ds.location_products ?? []).map((x) => x.location));
    return (ds.locations ?? []).filter((l) => STOCKING.has(l.type) && kept.has(l.id)).map((l) => l.id)
      .sort((a, b) => nm.loc(a).localeCompare(nm.loc(b)));
  }, [ds, nm]);
  const loc = place && places.includes(place) ? place : places[0] ?? "";
  const all = useLatest(loc ? () => api.cycleCounts(ds, loc) : null, [ds, loc]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const cc = ds.execution?.cycle_counting;
  const plan: CyclePlan | null = all.value && all.value.location === loc ? all.value : null;
  const mine = plan?.rows ?? [];
  const due = mine.filter((r) => r.due);
  const perYear = (c: Cls) => cc?.[KEY[c]] ?? { A: 12, B: 4, C: 1 }[c];
  const setPerYear = (c: Cls, n: number) => store.update((d) => {
    const ex = (d.execution ?? {}) as NonNullable<Dataset["execution"]>;
    d.execution = { ...ex, cycle_counting: { ...(ex.cycle_counting ?? {}), [KEY[c]]: n } } as Dataset["execution"];
  });
  const make = async (classes?: Cls[]) => {
    setBusy(true);
    setErr(null);
    try { setMsg((await postAct(ds, "cycle_count", { location: loc, date: plan?.as_of, classes: classes ?? null })).text); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  };
  if (all.error) return <div className="banner error"><Badge sev="error">No cycle count plan</Badge>{all.error}</div>;
  if (!loc) return null;
  if (!plan) return <Panel title="Cycle counts by ABC class"><p className="faint">Classing the products by what they use up…</p></Panel>;
  const byCls = (c: Cls) => due.filter((r) => r.cls === c).length;
  return (
    <Panel title="Cycle counts by ABC class" actions={<span className="faint small">Count often what moves the most value, the rest less</span>}>
      <div className="stack">
        <Edits><div className="row wrap small" style={{ gap: 12 }}>
          <select className="select" aria-label="Place for cycle counts" value={loc} onChange={(e) => setPlace(e.target.value)}>
            {places.map((l) => <option key={l} value={l}>{nm.loc(l)}</option>)}
          </select>
          {(["A", "B", "C"] as Cls[]).map((c) => <label key={c} className="row" style={{ gap: 4 }}>{c} counted
            <input className="input" type="number" min={0} max={366} style={{ width: 60 }} aria-label={`Counts a year, ${c}`} value={perYear(c)}
              onChange={(e) => { const n = Math.round(Number(e.target.value)); if (Number.isFinite(n) && n >= 0 && n <= 366) setPerYear(c, n); }} />
            × a year</label>)}
        </div></Edits>
        {plan.notes.map((n) => <div key={n} className="banner info"><span><Msg text={n} /></span></div>)}
        <div className="table-wrap"><table className="t" aria-label="Cycle count classes">
          <thead><tr><th>Class</th><th className="num">Products</th><th className="num">Counts a year</th><th className="num">Due now</th>
            <th className="num">Counted</th><th className="num">Found as booked</th><th className="num">Differences</th></tr></thead>
          <tbody>{plan.classes.map((c) => {
            return <tr key={c.cls}><td><b>{c.cls === "none" ? "Not cycle counted" : c.cls}</b></td><td className="num">{c.items}</td>
              <td className="num">{c.per_year}</td><td className="num">{c.due}</td><td className="num">{c.counted}</td>
              <td className="num">{c.accuracy != null ? pct(c.accuracy, 0) : "—"}</td>
              <td className="num">{c.counted ? money(c.difference_value, plan.currency) : "—"}</td></tr>;
          })}</tbody>
        </table></div>
        <Edits><div className="row wrap" style={{ gap: 8 }}>
          <button className="btn sm accent" disabled={busy || !due.length} onClick={() => make()}>
            {due.length ? `Count the ${plural(due.length, "product")} due at ${nm.loc(loc)}` : `Nothing due at ${nm.loc(loc)}`}</button>
          {(["A", "B", "C"] as Cls[]).filter((c) => byCls(c) && byCls(c) < due.length).map((c) =>
            <button key={c} className="btn sm" disabled={busy} onClick={() => make([c])}>Only the {byCls(c)} {c}</button>)}
        </div></Edits>
        {msg && <div className="banner info" role="status"><Badge sev="ok">Done</Badge><span>{msg}</span></div>}
        {err && <div className="banner error"><Badge sev="error">Not done</Badge>{err}</div>}
        {mine.length > 0 && <div className="table-wrap"><table className="t" aria-label="Cycle count plan">
          <thead><tr><th>Product</th><th>Class</th><th className="num">Value used up</th><th className="num">Share</th><th>Last counted</th><th>Next due</th></tr></thead>
          <tbody>{mine.map((r) => <tr key={r.product}>
            <td>{nm.prod(r.product)}</td><td>{r.cls === "none" ? "—" : r.cls}{r.by_hand && <span className="faint small"> (set by hand)</span>}</td>
            <td className="num">{money(r.used_value, plan.currency)}</td><td className="num">{pct(r.share, 0)}</td>
            <td>{r.last_counted ? day(r.last_counted) : "never"}</td>
            <td>{r.on_doc ? <Badge sev="info">on {r.on_doc}</Badge> : r.next_due == null ? "never" : r.due ? <Badge sev="warning">{r.overdue_days ? `due ${plural(r.overdue_days, "day")} ago` : "due now"}</Badge> : day(r.next_due)}</td>
          </tr>)}</tbody>
        </table></div>}
      </div>
    </Panel>
  );
}
