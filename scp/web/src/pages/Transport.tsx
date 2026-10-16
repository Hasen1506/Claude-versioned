// Enterprise 6.3: transport (S/4 guide §14, a small TM). What is waiting to be loaded, in vehicles by weight and
// volume with the cheapest carrier; freight orders tendered, accepted or rejected, shipped and settled with the
// carrier's bill shared over what they carried. Engine: scp/transport.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Dataset, FreightRow, LoadGroup, TransportAction, TransportView } from "../api/types";
import { Badge, Edits, Empty, Panel, StageHeader, StatTile, Tabs } from "../components/ui";
import { SchemaForm } from "../schema/SchemaForm";
import { day, exactMoney, money, pct, plural, qty } from "../lib/format";
import { Msg, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { store, useStore } from "../state/store";

type View = "load" | "orders" | "carriers";
type Obj = Record<string, unknown>;

const STATUS: Record<string, "info" | "warning" | "ok" | "error"> = {
  planned: "info", tendered: "warning", accepted: "ok", shipped: "ok", settled: "ok", cancelled: "error",
};

function useTransport(ds: Dataset) {
  const [v, setV] = useState<TransportView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.transport(ds).then((x) => { if (live) { setV(x); setErr(null); } }, (e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [ds]);
  return { v, err };
}

function useStep() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: TransportAction, extra: Parameters<typeof api.transportAct>[2] = {}) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const before = store.get().dataset!;
      const out = await api.transportAct(before, action, extra);
      store.replace(out.dataset, before);
      setMsg(out.report.message);
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

const kg = (v: number) => `${qty(v)} kg`;
const MODE: Record<string, string> = {
  truck_ftl: "full truck", truck_ltl: "part load", reefer: "refrigerated truck", rail: "rail", sea: "sea", air: "air",
  courier: "courier", pipeline: "pipeline",
};

export function Transport({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const view = (route[1] as View) || "load";
  const { v, err } = useTransport(ds);
  const step = useStep();
  const cur = ds.settings.currency;
  const vehicles = v?.groups.flatMap((g) => g.vehicles) ?? [];
  const open = (ds.freight_orders ?? []).filter((f) => ["planned", "tendered", "accepted"].includes(f.status ?? "planned"));
  const head = <StageHeader title="Transport" kicker="Which vehicle carries what, with which carrier, and what it costs."
    how={<>What is waiting to load is every open delivery and every stock transfer with something left to ship, loading
      in the next {ds.transport?.horizon_days ?? 7} days: a delivery on its planned goods issue, a transfer its lane's
      transit time before it is due. On each lane, what loads within the window shares a vehicle. Vehicles are filled
      first fit, heaviest first, up to their kilograms and cubic metres. Every carrier with a rate for the lane is
      costed on its own vehicles (a shipment, a kilogram and a cubic metre, never under its minimum) and the cheapest
      is proposed; where no carrier has a rate, the lane's own cost. A settled bill is shared over what the vehicle
      carried by weight.</>}
    answer={v ? <>{vehicles.length ? `${plural(vehicles.length, "vehicle")} to load for ${money(v.groups.reduce((a, g) => a + g.cost, 0), cur)}; ` : "Nothing waits to be loaded; "}
      {plural(open.length, "freight order")} open{v.billed ? `; ${money(v.billed, cur)} billed, ${v.difference >= 0 ? "+" : "−"}${money(Math.abs(v.difference), cur)} against plan` : ""}.</> : undefined} />;
  if (!(ds.lanes ?? []).length) {
    return <div>{head}<div className="content"><Panel><Empty title="No lanes yet">
      <p>Transport plans the vehicles on the company's <a href={href("data", "lanes")}>lanes</a>: give each route from a
        place to a customer or another place its mode, and the carriers that run it their <a href={href("data", "carriers")}>rates</a>.</p>
    </Empty></Panel></div></div>;
  }
  return (
    <div>{head}<div className="content stack">
      <Tabs<View> value={view} onChange={(x) => go("transport", x)} tabs={[
        { id: "load", label: "To load", count: vehicles.length || undefined },
        { id: "orders", label: "Freight orders", count: (ds.freight_orders ?? []).length || undefined },
        { id: "carriers", label: "Carriers", count: (ds.carriers ?? []).length || undefined },
      ]} />
      {err && <div className="banner error" role="alert"><Badge sev="error">Could not plan the transport</Badge>{err}</div>}
      {step.banners}
      {!v && !err && <p className="faint">Building the loads…</p>}
      {v && view === "load" && <ToLoad v={v} step={step} />}
      {v && view === "orders" && <Orders v={v} step={step} />}
      {v && view === "carriers" && <Carriers ds={ds} v={v} />}
    </div></div>
  );
}

type Step = ReturnType<typeof useStep>;

function ToLoad({ v, step }: { v: TransportView; step: Step }) {
  const nm = useNames();
  const cur = v.currency;
  const vehicles = v.groups.flatMap((g) => g.vehicles);
  const cost = v.groups.reduce((a, g) => a + g.cost, 0);
  return <>
    {v.notes.map((n) => <div key={n} className="banner warning"><Badge sev="warning">Check</Badge><span><Msg text={n} /></span></div>)}
    {v.unplanned.map((u) => <div key={u.id} className="banner warning"><Badge sev="warning">Not planned</Badge>
      <span>{u.id}: {u.why}. Give the route a <a href={href("data", "lanes")}>lane</a>.</span></div>)}
    {vehicles.length === 0 ? <Panel><Empty title="Nothing waits to be loaded">Every open delivery and stock transfer in the
      next days is on a freight order. Deliveries are made on <a href={href("selling", "deliver")}>Selling</a>.</Empty></Panel> : <>
      <div className="grid-auto">
        <StatTile label="Vehicles to load" value={qty(vehicles.length)} sub={plural(v.groups.length, "lane and day", "lanes and days")} tone="ink" />
        <StatTile label="Freight" value={money(cost, cur)} sub="with the cheapest carrier on each" />
        <StatTile label="Weight" value={kg(vehicles.reduce((a, x) => a + x.weight_kg, 0))} sub={`${qty(vehicles.reduce((a, x) => a + x.volume_m3, 0))} m³`} />
      </div>
      <Panel flush title="Vehicles to load" actions={<Edits><button className="btn accent" disabled={step.busy} onClick={() => step.run("plan")}>
        {`Make the ${plural(vehicles.length, "freight order")} (${exactMoney(cost, cur)})`}</button></Edits>}>
        <div className="table-wrap"><table className="t" aria-label="Vehicles to load">
          <thead><tr><th>From</th><th>To</th><th>Loads</th><th>Carrier</th><th>Carries</th><th className="num">Weight</th>
            <th className="num">Volume</th><th>Full</th><th className="num">Cost</th><th>Others would cost</th></tr></thead>
          <tbody>{v.groups.flatMap((g: LoadGroup) => g.vehicles.map((x, i) => (
            <tr key={`${g.lane}|${g.planned_on}|${i}`}>
              <td>{nm.loc(x.ship_from)}</td><td>{nm.loc(x.ship_to)}</td><td>{day(x.planned_on)}</td>
              <td>{x.carrier ? g.choices.find((c) => c.carrier === x.carrier)?.name ?? x.carrier : <span className="faint">no carrier: the lane's cost</span>}
                <div className="faint small">{MODE[x.mode] ?? x.mode}</div></td>
              <td>{[...x.deliveries, ...x.transfers].join(", ")}
                {x.late.length > 0 && <div><Badge sev="warning">late: {x.late.join(", ")}</Badge></div>}
                {x.early.length > 0 && <div className="faint small">sent early to share it: {x.early.join(", ")}</div>}
                {x.over && <div><Badge sev="error">bigger than one vehicle: split it</Badge></div>}</td>
              <td className="num">{kg(x.weight_kg)}</td><td className="num">{qty(x.volume_m3)} m³</td>
              <td>{x.fill != null ? <span className="fill" title="the fuller of weight and volume"><span style={{ width: `${Math.min(100, x.fill * 100)}%` }} /><b>{pct(x.fill, 0)}</b></span> : <span className="faint">—</span>}</td>
              <td className="num">{exactMoney(x.cost, cur)}</td>
              <td className="small">{i === 0 ? g.choices.slice(1).map((c) => `${c.name} ${exactMoney(c.cost, cur)}${c.vehicles > 1 ? ` (${c.vehicles} vehicles)` : ""}${c.too_small ? ", vehicle too small" : ""}`).join("; ") || "—" : ""}</td>
            </tr>)))}</tbody>
        </table></div>
      </Panel>
    </>}
  </>;
}

function Orders({ v, step }: { v: TransportView; step: Step }) {
  const nm = useNames();
  const cur = v.currency;
  const [bill, setBill] = useState<Record<string, { amount: string; ref: string }>>({});
  if (!v.orders.length) return <Panel><Empty title="No freight orders yet">Make them from what is waiting to load.</Empty></Panel>;
  const b = (id: string) => bill[id] ?? { amount: "", ref: "" };
  return <>
    <div className="grid-auto">
      <StatTile label="Open freight" value={money(v.planned_cost, cur)} sub="planned, not settled yet" tone="ink" />
      <StatTile label="Billed" value={money(v.billed, cur)} sub="settled freight orders" />
      <StatTile label="Billed against plan" value={`${v.difference >= 0 ? "+" : "−"}${money(Math.abs(v.difference), cur)}`} tone={Math.abs(v.difference) > 0.005 ? "hl" : undefined} />
    </div>
    <Panel flush title="Freight orders, latest first">
      <div className="table-wrap"><table className="t" aria-label="Freight orders">
        <thead><tr><th>Freight order</th><th>From → to</th><th>Loads</th><th>Carrier</th><th>Carries, cost shared by weight</th>
          <th className="num">Weight</th><th className="num">Planned</th><th className="num">Billed</th><th>Status</th><th>Next</th></tr></thead>
        <tbody>{v.orders.map((r: FreightRow) => {
          const f = r.order;
          const id = f.id;
          const k = f.carrier ? v.carriers.find((c) => c.carrier === f.carrier)?.name ?? f.carrier : null;
          return <tr key={id}>
            <td><b>{id}</b>{f.note && <div className="faint small">{f.note}</div>}</td>
            <td>{nm.loc(f.ship_from)} → {nm.loc(f.ship_to)}</td><td>{day(f.planned_on)}</td>
            <td>{k ?? <span className="faint">the lane's cost</span>}{(f.rejected_by ?? []).length > 0 && <div className="faint small">turned down by {(f.rejected_by ?? []).map((c) => v.carriers.find((x) => x.carrier === c)?.name ?? c).join(", ")}</div>}</td>
            <td className="small">{r.lines.map((ln) => <div key={ln.id}>{ln.id} · {kg(ln.weight_kg)} · {exactMoney(ln.cost, cur)}</div>)}</td>
            <td className="num">{kg(f.weight_kg ?? 0)}</td><td className="num">{exactMoney(f.planned_cost ?? 0, cur)}</td>
            <td className="num">{f.billed != null ? <>{exactMoney(f.billed, cur)}{r.difference ? <div className="small">{r.difference > 0 ? "+" : "−"}{exactMoney(Math.abs(r.difference), cur)}</div> : null}</> : "—"}</td>
            <td><Badge sev={STATUS[f.status ?? "planned"]}>{f.status}</Badge>{r.pay_by && <div className="faint small">pay by {day(r.pay_by)}</div>}</td>
            <td><Edits><div className="row wrap" style={{ gap: 4 }}>
              {f.status === "planned" && f.carrier && <button className="btn sm accent" disabled={step.busy} aria-label={`Tender ${id}`} onClick={() => step.run("tender", { order: id })}>Tender</button>}
              {f.status === "tendered" && <>
                <button className="btn sm accent" disabled={step.busy} aria-label={`Carrier accepted ${id}`} onClick={() => step.run("accept", { order: id })}>Accepted</button>
                <button className="btn sm" disabled={step.busy} aria-label={`Carrier rejected ${id}`} onClick={() => step.run("reject", { order: id })}>Rejected</button></>}
              {(f.status === "accepted" || (f.status === "planned" && !f.carrier)) &&
                <button className="btn sm accent" disabled={step.busy} aria-label={`Ship ${id}`} onClick={() => step.run("ship", { order: id })}>Ship</button>}
              {f.status === "shipped" && <>
                <input className="input num" style={{ width: 100 }} type="number" min={0} step="any" aria-label={`Billed ${id}`} placeholder={String(f.planned_cost)}
                  value={b(id).amount} onChange={(e) => setBill({ ...bill, [id]: { ...b(id), amount: e.target.value } })} />
                <input className="input" style={{ width: 90 }} aria-label={`Bill number ${id}`} placeholder="their no." value={b(id).ref}
                  onChange={(e) => setBill({ ...bill, [id]: { ...b(id), ref: e.target.value } })} />
                <button className="btn sm accent" disabled={step.busy} aria-label={`Settle ${id}`}
                  onClick={() => step.run("settle", { order: id, billed: b(id).amount === "" ? f.planned_cost : Number(b(id).amount), bill: b(id).ref })}>Settle</button></>}
              {["planned", "tendered", "accepted"].includes(f.status ?? "") &&
                <button className="btn sm ghost" disabled={step.busy} aria-label={`Cancel ${id}`} onClick={() => step.run("cancel", { order: id })}>Cancel</button>}
            </div></Edits></td>
          </tr>;
        })}</tbody>
      </table></div>
    </Panel>
  </>;
}

function Carriers({ ds, v }: { ds: Dataset; v: TransportView }) {
  const cur = v.currency;
  return <>
    <Panel flush title="Carriers" actions={<a className="btn sm" href={href("data", "carriers")}>Carriers and their rates</a>}>
      {v.carriers.length ? <div className="table-wrap"><table className="t" aria-label="Carriers">
        <thead><tr><th>Carrier</th><th className="num">Freight orders</th><th className="num">Planned</th><th className="num">Billed</th>
          <th className="num">To pay</th><th className="num">Turned down</th></tr></thead>
        <tbody>{v.carriers.map((c) => <tr key={c.carrier}><td>{c.name}</td><td className="num">{c.orders}</td>
          <td className="num">{exactMoney(c.planned, cur)}</td><td className="num">{exactMoney(c.billed, cur)}</td>
          <td className="num">{exactMoney(c.to_pay, cur)}</td><td className="num">{c.rejected || ""}</td></tr>)}</tbody>
      </table></div> : <Empty title="No freight orders with a carrier yet">{(ds.carriers ?? []).length ? "Tender the freight orders to see what each carries." : "Add the carriers and their rates in master data."}</Empty>}
    </Panel>
    <Panel title="Transport settings">
      <SchemaForm defName="TransportSettings" value={(ds.transport ?? {}) as unknown as Obj}
        onChange={(next) => store.update((d) => { d.transport = next as unknown as Dataset["transport"]; })} />
    </Panel>
  </>;
}
