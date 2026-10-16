// Enterprise 6.1: the warehouse inside a place (S/4 guide §12.2–12.3, a small EWM). Stock by bin, put-away by the
// place's rules, waves of deliveries picked together with one pick list in walk order, and the open warehouse
// tasks. The phone page (Scan.tsx) confirms the same tasks with a scanner. Engine: scp/warehouse.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, PickList, PutawayProposal, WarehouseAction, WarehouseTask, WarehouseView } from "../api/types";
import { Badge, Edits, Empty, Panel, StageHeader, StatTile, Tabs } from "../components/ui";
import { day, pct, plural, qty } from "../lib/format";
import { Loc, Msg, Prod, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { store, useStore } from "../state/store";

type View = "bins" | "putaway" | "picking" | "tasks";

/** Places that have bins, first the one asked for. */
export function binPlaces(ds: Dataset): string[] {
  return [...new Set((ds.bins ?? []).map((b) => b.location))];
}

/** A warehouse step on the company: the changed company is kept, the report's message returned. */
export async function whAct(action: WarehouseAction, extra: Parameters<typeof api.warehouseAct>[2] = {}) {
  const before = store.get().dataset!;
  const out = await api.warehouseAct(before, action, extra);
  store.replace(out.dataset, before);
  return out;
}

/** The place's bins read again whenever the company changes. */
export function useWarehouse(ds: Dataset, loc: string) {
  const [v, setV] = useState<WarehouseView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    if (!loc) return;
    api.warehouse(ds, loc).then((x) => { if (live) { setV(x); setErr(null); } }, (e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [ds, loc]);
  return { v, err };
}

function useStep() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: WarehouseAction, extra: Parameters<typeof api.warehouseAct>[2] = {}) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const out = await whAct(action, extra);
      setMsg(out.report.message);
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

export function Warehouse({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const nm = useNames();
  const places = useMemo(() => binPlaces(ds), [ds]);
  const view = (route[1] as View) || "bins";
  const loc = route[2] && places.includes(route[2]) ? route[2] : places[0] ?? "";
  const { v, err } = useWarehouse(ds, loc);
  const tasks = (ds.warehouse_tasks ?? []).filter((t) => t.location === loc);
  const open = tasks.filter((t) => t.status === "open");
  const loose = v?.loose.filter((r) => r.to_put_away > 1e-6) ?? [];
  const head = <StageHeader title="Warehouse" kicker="Where the stock is inside a place: in which bin, what to put away, what to pick for the deliveries."
    how={<>Stock by bin is read from the goods-movement journal: a movement names the bin its quantity comes from or goes
      to. Put-away follows the place's rules: the storage types named for the product, in order, and in each its
      strategy (fixed bins, a bin already holding the product, or the next empty bin along the walk), within each bin's
      quantity and weight. A wave picks its deliveries' lines from the bins first expiring, then first in, then nearest on
      the walk. A confirmed task posts the move between bins; it never changes the place's stock or the plan.</>}
    answer={v && loc ? <>{plural(new Set(v.bins.filter((b) => b.product).map((b) => b.bin)).size, "bin")} hold stock at {nm.loc(loc)}, {plural(v.bins.filter((b) => !b.product).length, "bin")} empty;
      {loose.length ? ` ${plural(loose.length, "product")} ${loose.length === 1 ? "waits" : "wait"} in goods in to be put away;` : " nothing waits to be put away;"} {plural(open.length, "open task")}.</> : undefined}
    right={loc ? <a className="btn" href={href("scan", loc)}>Scan on a phone</a> : undefined} />;
  if (!places.length) {
    return <div>{head}<div className="content"><Panel><Empty title="No bins yet">
      <p>Give a plant or warehouse its storage types and bins, and the rules that say where goods go:
        <a href={href("data", "storage_types")}> storage types</a>, <a href={href("data", "bins")}>bins</a> and
        <a href={href("data", "putaway_rules")}> put-away rules</a> in master data.</p></Empty></Panel></div></div>;
  }
  return (
    <div>{head}<div className="content stack">
      <div className="row" style={{ gap: 8 }}>
        <label className="faint" htmlFor="wh-place">Place</label>
        <select id="wh-place" className="select" value={loc} onChange={(e) => go("warehouse", view, e.target.value)} aria-label="Warehouse place">
          {places.map((p) => <option key={p} value={p}>{nm.loc(p)}</option>)}
        </select>
      </div>
      <Tabs<View> value={view} onChange={(x) => go("warehouse", x, loc)} tabs={[
        { id: "bins", label: "Stock by bin", count: v?.bins.filter((b) => b.product).length },
        { id: "putaway", label: "Put away", count: loose.length || undefined },
        { id: "picking", label: "Waves & picking", count: (ds.waves ?? []).filter((w) => w.location === loc).length || undefined },
        { id: "tasks", label: "Open tasks", count: open.length },
      ]} />
      {err && <div className="banner error" role="alert"><Badge sev="error">Could not read the bins</Badge>{err}</div>}
      {v && v.notes.map((n) => <div key={n} className="banner warning"><Badge sev="warning">Check</Badge><span><Msg text={n} /></span></div>)}
      {v && view === "bins" && <Bins v={v} />}
      {view === "putaway" && <Putaway ds={ds} loc={loc} v={v} />}
      {view === "picking" && <Picking ds={ds} loc={loc} />}
      {view === "tasks" && <Tasks ds={ds} tasks={open} />}
    </div></div>
  );
}

function Fill({ f }: { f?: number | null }) {
  if (f === null || f === undefined) return <span className="faint">—</span>;
  return <span className="fill" title={`${pct(f, 0)} of the bin's limit`}><span style={{ width: `${Math.min(100, f * 100)}%` }} />{pct(f, 0)}</span>;
}

function Bins({ v }: { v: WarehouseView }) {
  const held = v.bins.filter((b) => b.product);
  const empty = v.bins.filter((b) => !b.product);
  const inNone = v.loose.reduce((a, r) => a + Math.max(0, r.qty), 0);
  return (<>
    <div className="grid-auto">
      <StatTile label="Bins in use" value={qty(new Set(held.map((b) => b.bin)).size)} sub={`of ${qty(new Set(v.bins.map((b) => b.bin)).size)}`} />
      <StatTile label="Empty bins" value={qty(empty.length)} sub={empty.filter((b) => b.blocked).length ? `${empty.filter((b) => b.blocked).length} blocked` : "ready for put-away"} />
      <StatTile label="In no bin" value={qty(inNone)} sub="goods in, or picked and staged to ship" tone={inNone ? "hl" : undefined} />
    </div>
    <Panel flush title={<h3>Bins at <Loc id={v.location} /> on {day(v.on)}</h3>}>
      <div className="table-wrap" style={{ maxHeight: 560 }}>
        <table className="t" aria-label="Stock by bin">
          <thead><tr><th>Bin</th><th>Area</th><th className="num">Walk</th><th>Product</th><th>Batch</th><th>Stock</th>
            <th className="num">Quantity</th><th>In since</th><th>Expires</th><th>Fill</th></tr></thead>
          <tbody>{v.bins.map((b, i) => (
            <tr key={`${b.bin}|${b.product}|${b.batch}|${b.stock_type}|${i}`} className={b.product ? "" : "faint"}>
              <td><code>{b.bin}</code>{b.blocked && <> <Badge sev="warning">blocked</Badge></>}{b.fixed_for && <span className="faint"> fixed: {b.fixed_for}</span>}</td>
              <td>{b.storage_type}</td><td className="num">{b.walk}</td>
              <td>{b.product ? <Prod id={b.product} /> : "empty"}</td><td>{b.batch ?? ""}</td>
              <td>{b.product && b.stock_type !== "unrestricted" ? b.stock_type : ""}</td>
              <td className="num">{b.product ? qty(b.qty) : ""}</td><td>{b.since ? day(b.since) : ""}</td>
              <td>{b.expires_on ? day(b.expires_on) : ""}</td><td><Fill f={b.fill} /></td>
            </tr>))}</tbody>
        </table>
      </div>
    </Panel>
    {v.loose.length > 0 && <Panel flush title="In no bin">
      <table className="t" aria-label="Stock in no bin">
        <thead><tr><th>Product</th><th>Batch</th><th>Stock</th><th className="num">Quantity</th><th className="num">To put away</th></tr></thead>
        <tbody>{v.loose.map((r) => <tr key={`${r.product}|${r.batch}|${r.stock_type}`}>
          <td><Prod id={r.product} /></td><td>{r.batch ?? ""}</td><td>{r.stock_type}</td>
          <td className="num">{qty(r.qty)}</td><td className="num">{qty(r.to_put_away)}</td></tr>)}</tbody>
      </table>
    </Panel>}
  </>);
}

function Putaway({ ds, loc, v }: { ds: Dataset; loc: string; v: WarehouseView | null }) {
  const [p, setP] = useState<PutawayProposal | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const step = useStep();
  useEffect(() => {
    let live = true;
    api.putawayProposal(ds, loc).then((x) => { if (live) { setP(x); setErr(null); } }, (e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [ds, loc]);
  return (<>
    {step.banners}
    {err && <div className="banner error" role="alert"><Badge sev="error">No proposal</Badge>{err}</div>}
    <Panel flush title="Where the stock in no bin goes" actions={<Edits>
      <button className="btn primary" disabled={step.busy || !p?.tasks.length} onClick={() => step.run("putaway", { location: loc })}>
        Make the put-away tasks</button></Edits>}>
      {p && !p.tasks.length ? <Empty title="Nothing to put away">{v?.loose.length ? "What is in no bin has tasks already." : "Every unit at this place is in a bin."}</Empty> : null}
      {p && p.tasks.length > 0 && <table className="t" aria-label="Put-away proposal">
        <thead><tr><th>Product</th><th>Batch</th><th className="num">Quantity</th><th>To bin</th><th>Area</th></tr></thead>
        <tbody>{p.tasks.map((t, i) => <tr key={i}><td><Prod id={t.product} /></td><td>{t.batch ?? ""}</td>
          <td className="num">{qty(t.qty)}</td><td><code>{t.to_bin}</code></td><td>{t.storage_type}</td></tr>)}</tbody>
      </table>}
      {p?.notes.map((n) => <p key={n} className="banner warning"><Msg text={n} /></p>)}
    </Panel>
  </>);
}

function Picking({ ds, loc }: { ds: Dataset; loc: string }) {
  const step = useStep();
  const waves = (ds.waves ?? []).filter((w) => w.location === loc);
  const inWave = new Set((ds.warehouse_tasks ?? []).filter((t) => t.delivery && t.status !== "cancelled").map((t) => t.delivery!));
  const due = (ds.deliveries ?? []).filter((d) => d.ship_from === loc && !d.issued_on && !inWave.has(d.id) && d.lines.every((x) => x.picked == null));
  const [chosen, setChosen] = useState<string[] | null>(null);
  const picked = chosen ?? due.map((d) => d.id);
  const [wave, setWave] = useState<string>(waves[waves.length - 1]?.id ?? "");
  const [pl, setPl] = useState<PickList | null>(null);
  useEffect(() => {
    let live = true;
    if (!wave) { setPl(null); return; }
    api.pickList(ds, wave).then((x) => live && setPl(x), () => live && setPl(null));
    return () => { live = false; };
  }, [ds, wave]);
  const make = async () => {
    const out = await step.run("wave", { location: loc, deliveries: picked });
    if (out?.report.wave) { setWave(out.report.wave); setChosen(null); }
  };
  const confirmRow = async (ids: string[]) => {
    for (const id of ids) {
      if (!(await step.run("confirm", { task: id }))) break;
    }
  };
  return (<>
    {step.banners}
    <Panel flush title="Deliveries to pick" actions={due.length ? <Edits>
      <button className="btn primary" disabled={step.busy || !picked.length} onClick={make}>
        Make a wave of {plural(picked.length, "delivery", "deliveries")}</button></Edits> : undefined}>
      {!due.length ? <Empty title="Nothing to pick">Every open delivery from <Loc id={loc} /> is in a wave or picked. Create deliveries on <a href={href("selling", "deliver")}>Selling</a>.</Empty>
        : <table className="t" aria-label="Deliveries to pick">
          <thead><tr><th /><th>Delivery</th><th>To</th><th>Goods issue</th><th>Lines</th></tr></thead>
          <tbody>{due.map((d) => <tr key={d.id}>
            <td><input type="checkbox" aria-label={`Pick ${d.id}`} checked={picked.includes(d.id)}
              onChange={(e) => setChosen(e.target.checked ? [...picked, d.id] : picked.filter((x) => x !== d.id))} /></td>
            <td>{d.id}</td><td><Loc id={d.customer} /></td><td>{day(d.planned_on)}</td>
            <td>{d.lines.map((x) => <div key={x.order}>{qty(x.qty)} <Prod id={x.product} /> <span className="faint">{x.order}</span></div>)}</td></tr>)}</tbody>
        </table>}
    </Panel>
    {waves.length > 0 && <Panel flush title={<div className="row" style={{ gap: 8 }}><h3 style={{ whiteSpace: "nowrap" }}>Pick list</h3>
      <select className="select" aria-label="Wave" value={wave} onChange={(e) => setWave(e.target.value)}>
        {waves.map((w) => <option key={w.id} value={w.id}>{w.id} · {plural(w.deliveries.length, "delivery", "deliveries")} · {day(w.created_on)}</option>)}
      </select>{pl?.done && <Badge sev="ok">picked</Badge>}</div>}
      actions={wave ? <a className="btn" href={href("scan", loc, wave)}>Pick it on a phone</a> : undefined}>
      {pl && <table className="t" aria-label={`Pick list ${pl.wave}`}>
        <thead><tr><th>Bin</th><th>Product</th><th>Batch</th><th className="num">To pick</th><th className="num">Picked</th><th>For</th><th /></tr></thead>
        <tbody>{pl.rows.map((r) => {
          const openIds = r.deliveries.filter((f) => f.status === "open").map((f) => f.task);
          return <tr key={`${r.bin}|${r.product}|${r.batch}`}>
            <td><code>{r.bin ?? "goods in"}</code></td><td>{r.name}</td><td>{r.batch ?? ""}</td>
            <td className="num">{qty(r.qty)}</td><td className="num">{qty(r.picked)}</td>
            <td>{r.deliveries.map((f) => <div key={f.task}>{qty(f.qty)} for {f.delivery} <span className="faint">{f.order}</span>{f.status !== "open" && <> <Badge sev={f.status === "done" ? "ok" : "warning"}>{f.status}</Badge></>}</div>)}</td>
            <td>{openIds.length > 0 && <Edits><button className="btn sm" disabled={step.busy} onClick={() => confirmRow(openIds)}
              aria-label={`Picked ${r.bin ?? "goods in"} ${r.product} in full`}>Picked in full</button></Edits>}</td>
          </tr>;
        })}</tbody>
      </table>}
    </Panel>}
  </>);
}

function Tasks({ ds, tasks }: { ds: Dataset; tasks: WarehouseTask[] }) {
  const step = useStep();
  const bins = new Map((ds.bins ?? []).map((b) => [`${b.location}|${b.id}`, b.walk ?? 0]));
  const walk = (t: WarehouseTask) => bins.get(`${t.location}|${t.kind === "pick" ? t.from_bin : t.to_bin}`) ?? 1e9;
  const sorted = [...tasks].sort((a, b) => walk(a) - walk(b) || a.id.localeCompare(b.id));
  if (!tasks.length) return <Panel><Empty title="No open tasks">Make put-away tasks or a wave of picks first.</Empty></Panel>;
  return (<>{step.banners}
    <Panel flush title="Open warehouse tasks, in walk order">
      <table className="t" aria-label="Open warehouse tasks">
        <thead><tr><th>Task</th><th>What</th><th>Product</th><th>Batch</th><th className="num">Quantity</th><th>From</th><th>To</th><th>For</th><th /></tr></thead>
        <tbody>{sorted.map((t) => <tr key={t.id}>
          <td>{t.id}</td><td>{t.kind === "putaway" ? "put away" : t.kind}</td><td><Prod id={t.product} /></td><td>{t.batch ?? ""}</td>
          <td className="num">{qty(t.qty)}</td><td><code>{t.from_bin ?? "goods in"}</code></td><td><code>{t.to_bin ?? "to ship"}</code></td>
          <td>{t.delivery ?? ""}</td>
          <td><Edits><div className="row" style={{ gap: 4 }}>
            <button className="btn sm" disabled={step.busy} onClick={() => step.run("confirm", { task: t.id })} aria-label={`Confirm ${t.id}`}>Done</button>
            <button className="btn sm ghost" disabled={step.busy} onClick={() => step.run("cancel", { task: t.id })} aria-label={`Cancel ${t.id}`}>Cancel</button>
          </div></Edits></td></tr>)}</tbody>
      </table>
    </Panel></>);
}
