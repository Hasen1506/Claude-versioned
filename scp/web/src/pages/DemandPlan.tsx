// The demand plan: exactly the demand the supply plan works to, product by place and week. Type into the grid, upload a
// spreadsheet, or release a forecast into it. A forecast record that covers several weeks (a monthly bucket) is shown
// spread over its days; editing one of its weeks splits it into weekly records first, so nothing is lost.
import { useMemo, useState } from "react";
import type { Dataset, DemandRecord } from "../api/types";
import { ImportPanel } from "../components/Import";
import { Badge, Empty, Panel } from "../components/ui";
import { addDays, day, qty } from "../lib/format";
import { href } from "../lib/router";
import { store } from "../state/store";

const DAY = 86400000;
const toDate = (iso: string) => new Date(iso + "T00:00:00Z").getTime();
const iso = (t: number) => new Date(t).toISOString().slice(0, 10);

/** Monday (or the company's week start) on or before the planning start, then one column per week to the horizon end. */
export function weeks(ds: Dataset): string[] {
  const start = toDate(ds.settings.planning_start);
  const ws = ds.settings.week_start ?? 0;
  const dow = (new Date(start).getUTCDay() + 6) % 7;         // 0 = Monday
  const first = start - (((dow - ws) + 7) % 7) * DAY;
  const end = start + ds.settings.horizon_days * DAY;
  const out: string[] = [];
  for (let t = first; t < end; t += 7 * DAY) out.push(iso(t));
  return out;
}

/** How much of a record falls in [from, to): a spread forecast by the share of its calendar days. */
function share(r: DemandRecord, from: number, to: number): number {
  const a = toDate(r.date);
  const days = r.kind === "forecast" && r.period_days ? r.period_days : 1;
  const b = a + days * DAY;
  const overlap = Math.max(0, Math.min(b, to) - Math.max(a, from));
  return (r.qty * overlap) / (b - a);
}

interface Series { location: string; product: string; fc: number[]; so: number[]; before: number; after: number }

export function DemandPlan({ ds }: { ds: Dataset }) {
  const cols = useMemo(() => weeks(ds), [ds]);
  const [upload, setUpload] = useState(false);
  const [addLoc, setAddLoc] = useState("");
  const [addProd, setAddProd] = useState("");
  const [extra, setExtra] = useState<string[]>([]);    // series added but still empty
  const names = useMemo(() => ({
    loc: Object.fromEntries((ds.locations ?? []).map((l) => [l.id, l.name || l.id])) as Record<string, string>,
    prod: Object.fromEntries((ds.products ?? []).map((p) => [p.id, p.name || p.id])) as Record<string, string>,
  }), [ds]);

  const series = useMemo(() => {
    const m = new Map<string, Series>();
    const get = (l: string, p: string) => {
      const k = `${l}|${p}`;
      if (!m.has(k)) m.set(k, { location: l, product: p, fc: cols.map(() => 0), so: cols.map(() => 0), before: 0, after: 0 });
      return m.get(k)!;
    };
    const first = toDate(cols[0] ?? ds.settings.planning_start), end = first + cols.length * 7 * DAY;
    for (const r of ds.demand ?? []) {
      const s = get(r.location, r.product);
      cols.forEach((w, i) => {
        const v = share(r, toDate(w), toDate(w) + 7 * DAY);
        if (v) (r.kind === "sales_order" ? s.so : s.fc)[i] += v;
      });
      s.before += share(r, -Infinity, first);
      s.after += share(r, end, Infinity);
    }
    for (const k of extra) { const [l, p] = k.split("|"); get(l, p); }
    return [...m.values()].sort((a, b) => (names.prod[a.product] ?? a.product).localeCompare(names.prod[b.product] ?? b.product)
      || (names.loc[a.location] ?? a.location).localeCompare(names.loc[b.location] ?? b.location));
  }, [ds, cols, extra, names]);

  const total = series.reduce((a, s) => a + s.fc.reduce((x, y) => x + y, 0) + s.so.reduce((x, y) => x + y, 0), 0);
  const orders = series.reduce((a, s) => a + s.so.reduce((x, y) => x + y, 0), 0);
  const places = (ds.locations ?? []).filter((l) => l.type !== "supplier");

  /** Set the forecast of one product at one place in one week. Records spanning other weeks are split into weekly ones. */
  const setWeek = (s: Series, i: number, value: number) => {
    const from = toDate(cols[i]), to = from + 7 * DAY;
    store.update((d) => {
      const list = (d.demand ??= []);
      const mine = (r: DemandRecord) => r.location === s.location && r.product === s.product && r.kind === "forecast";
      const touching = list.filter((r) => mine(r) && share(r, from, to) > 0);
      // split any record that also covers other weeks into its weekly parts
      for (const r of touching) {
        const a = toDate(r.date), b = a + (r.period_days ?? 1) * DAY;
        if (a >= from && b <= to) continue;
        list.splice(list.indexOf(r), 1);
        const W = 7 * DAY;
        for (let t = from + Math.floor((a - from) / W) * W; t < b; t += W) {
          const part = share(r, t, t + W);
          if (part <= 0 || t === from) continue;
          const lo = Math.max(t, a), hi = Math.min(t + W, b);
          list.push({ location: r.location, product: r.product, date: iso(lo), qty: +part.toFixed(6), kind: "forecast",
            period_days: Math.max(1, Math.round((hi - lo) / DAY)) } as DemandRecord);
        }
      }
      // replace this week's forecast with one weekly record
      d.demand = list.filter((r) => !(mine(r) && toDate(r.date) >= from && toDate(r.date) < to));
      // the first week may start before the plan does: its forecast covers only the days from the start
      const at = Math.max(from, toDate(ds.settings.planning_start));
      if (value > 0) d.demand.push({ location: s.location, product: s.product, date: iso(at), qty: value, kind: "forecast",
        period_days: Math.round((to - at) / DAY) } as DemandRecord);
    });
  };

  const addSeries = () => {
    if (!addLoc || !addProd) return;
    setExtra((x) => [...new Set([...x, `${addLoc}|${addProd}`])]);
    setAddLoc(""); setAddProd("");
  };

  return (
    <div className="stack">
      <Panel title={<h3>What the supply plan works to</h3>} actions={<>
        <button className="btn" onClick={() => setUpload(!upload)} aria-expanded={upload}>Upload CSV / Excel</button>
        <a className="btn ghost" href={href("data", "demand")}>Every demand record</a></>}>
        <p className="muted" style={{ marginTop: 0 }}>
          {total > 0 ? <>{qty(Math.round(total))} units over the next {cols.length} weeks, {qty(Math.round(orders))} of them on customer orders.{" "}
            </> : <>No demand yet. </>}
          Type a week's forecast into the grid, upload a spreadsheet, or <a href={href("demand", "overview")}>forecast it from past sales</a> and use that.
          Customer orders show under each row and are changed on the <a href={href("promise")}>Orders</a> page.</p>
      </Panel>
      {upload && <ImportPanel ds={ds} ckey="demand" onClose={() => setUpload(false)} />}
      {series.length === 0 && !upload ? (
        <Panel><Empty title="No demand to plan for yet">
          <p>Say which product is sold where, then enter how many per week. Or upload a file with one row per product, place, date and quantity.</p>
        </Empty></Panel>
      ) : series.length > 0 && (
        <Panel flush>
          <div className="table-wrap dp-wrap">
            <table className="t dp">
              <thead><tr>
                <th className="dp-stub">Product at place</th>
                {series.some((s) => s.before > 0) && <th className="num" title="Due before the plan starts: planned as overdue">Overdue</th>}
                {cols.map((w) => <th key={w} className="num" title={`Week of ${day(w)} to ${day(addDays(w, 6))}`}>{day(w)}</th>)}
                <th className="num">Total</th>
              </tr></thead>
              <tbody>{series.map((s) => {
                const fcT = s.fc.reduce((a, b) => a + b, 0), soT = s.so.reduce((a, b) => a + b, 0);
                return [
                  <tr key={`${s.location}|${s.product}`}>
                    <td className="dp-stub"><b>{names.prod[s.product] ?? s.product}</b> <span className="muted">at {names.loc[s.location] ?? s.location}</span>
                      {(!names.prod[s.product] || !names.loc[s.location]) && <Badge sev="warning">unknown</Badge>}</td>
                    {series.some((x) => x.before > 0) && <td className="num faint">{s.before ? qty(Math.round(s.before)) : ""}</td>}
                    {s.fc.map((v, i) => <td key={i} className="num dp-cell">
                      <input className="dp-in" inputMode="decimal" defaultValue={v ? +v.toFixed(2) : ""} key={`${v}`}
                        aria-label={`Forecast of ${names.prod[s.product] ?? s.product} at ${names.loc[s.location] ?? s.location}, week of ${day(cols[i])}`}
                        onBlur={(e) => {
                          const t = e.target.value.trim(), n = t === "" ? 0 : Number(t.replace(/,/g, ""));
                          if (!(n >= 0)) { e.target.value = v ? String(+v.toFixed(2)) : ""; return; }
                          if (Math.abs(n - v) > 1e-9) setWeek(s, i, n);
                        }}
                        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} /></td>)}
                    <td className="num"><b>{qty(Math.round(fcT + soT))}</b></td>
                  </tr>,
                  soT > 0 && <tr key={`${s.location}|${s.product}|so`} className="dp-so">
                    <td className="dp-stub small muted">customer orders</td>
                    {series.some((x) => x.before > 0) && <td />}
                    {s.so.map((v, i) => <td key={i} className="num small">{v ? qty(Math.round(v)) : ""}</td>)}
                    <td className="num small">{qty(Math.round(soT))}</td>
                  </tr>,
                ];
              })}</tbody>
            </table>
          </div>
          {series.some((s) => s.after > 0) && <p className="faint small" style={{ padding: "0 14px" }}>Demand after the end of the plan is kept but not planned.</p>}
        </Panel>
      )}
      <div className="row wrap">
        <span className="small muted">Add a row:</span>
        <select className="select" style={{ width: "auto" }} value={addProd} onChange={(e) => setAddProd(e.target.value)} aria-label="Product">
          <option value="">product…</option>{(ds.products ?? []).filter((p) => p.type === "FG" || p.type === "SFG").map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}</select>
        <span className="small muted">at</span>
        <select className="select" style={{ width: "auto" }} value={addLoc} onChange={(e) => setAddLoc(e.target.value)} aria-label="Place">
          <option value="">place…</option>{places.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select>
        <button className="btn sm" disabled={!addLoc || !addProd} onClick={addSeries}>Add</button>
      </div>
    </div>
  );
}
