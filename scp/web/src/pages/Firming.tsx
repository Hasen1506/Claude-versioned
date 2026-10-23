// Firming: the planner turns the plan's orders inside the firm zone into firm purchase, production and transfer orders,
// and sends the purchase orders that need no release. It sits with the supply plan (Enterprise 8.4, N350): firming is
// the planner's job, not the storekeeper's.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, PlannedOrder } from "../api/types";
import { Badge, Edits, Empty, Panel } from "../components/ui";
import { addressList, useServerMail } from "../components/ServerSend";
import { day, plural, qty } from "../lib/format";
import { Loc, namesOf, Prod } from "../lib/names";
import { poDocument, poEmail } from "../lib/podoc";
import { isStale, store, useStore } from "../state/store";

const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** The planned orders that can be firmed now: convertible, starting inside the firm zone, not a customer's own. */
export function firmCandidates(ds: Dataset, orders: PlannedOrder[]): PlannedOrder[] {
  const limit = addDays(ds.settings.planning_start, ds.execution?.firm_zone_days ?? 14);
  return orders.filter((o) => o.start_date < limit && o.convertible
    && !(ds.locations ?? []).some((l) => l.id === o.location && l.type === "customer"));
}

/** Where a planned order comes from, by its source record: the supplier of a purchasing source, the start of a lane. */
function SourceFrom({ ds, id }: { ds: Dataset; id?: string | null }) {
  const from = (ds.purchasing_sources ?? []).find((x) => x.id === id)?.supplier ?? (ds.lanes ?? []).find((x) => x.id === id)?.origin;
  return from ? <Loc id={from} /> : <span className="faint">—</span>;
}

export function Firming({ ds }: { ds: Dataset }) {
  const plan = useStore((s) => s.runs.plan);
  const planStale = useStore((s) => isStale(s, "plan"));
  const zone = ds.execution?.firm_zone_days ?? 14;
  const limit = addDays(ds.settings.planning_start, zone);
  const cands = useMemo(() => (plan.data?.ok ? firmCandidates(ds, plan.data.orders) : []), [plan.data, ds]);
  const [pick, setPick] = useState<Set<string> | null>(null);
  // a purchase that an open order would cover if it came sooner is left out until someone decides (Q9)
  const chosen = pick ?? new Set(cands.filter((o) => !o.open_later?.length).map((o) => o.id));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [toSend, setToSend] = useState<string[]>([]);
  const company = useStore((s) => s.company);
  const serverMail = useServerMail() && !!company?.live && company.role !== "viewer";
  const sendThem = async () => {
    setBusy(true);
    setErr(null);
    try {
      let orders = toSend;
      const said: string[] = [];
      if (serverMail && company) {
        // N139: on a server that sends mail, each order goes to its supplier's address first; only those e-mailed are
        // recorded as sent, the rest are named (no address, or the mail server refused) to send from Buying
        const before = store.get().dataset!;
        await store.run("purchasing");
        const views = store.get().runs.purchasing.data?.orders ?? [];
        const mailed: string[] = [], none: string[] = [], failed: string[] = [];
        for (const id of toSend) {
          const po = views.find((v) => v.id === id);
          if (!po || !po.approved) continue;                     // waiting to be released: send_all names it
          const m = poEmail(po, before);
          const to = addressList(m.to);
          if (!to.length) { none.push(id); continue; }
          try {
            const row = await api.sendMail(company.id, { kind: po.kind === "scheduling_agreement" ? "delivery_schedule" : "purchase_order", ref: id, to, cc: [], subject: m.subject, text: m.body, html: poDocument(po, before) });
            if (row.status === "sent") mailed.push(`${id} to ${to.join(", ")}`);
            else failed.push(`${id} (${row.error || "the mail server did not take it"})`);
          } catch (x) {
            failed.push(`${id} (${x instanceof Error ? x.message : String(x)})`);
          }
        }
        if (mailed.length) said.push(`E-mailed ${mailed.join("; ")}.`);
        if (none.length) said.push(`Not e-mailed, no address on the supplier's purchasing data: ${none.join(", ")}; send ${none.length === 1 ? "it" : "them"} from Buying.`);
        if (failed.length) said.push(`Not e-mailed: ${failed.join("; ")}.`);
        const skip = new Set([...none, ...failed.map((f) => f.split(" ")[0])]);
        orders = toSend.filter((id) => !skip.has(id));
      }
      const before = store.get().dataset!;
      let text = "";
      if (orders.length) {
        const out = await api.poAction(before, "send_all", "", { orders });
        store.replace(out.dataset, before);
        text = namesOf(out.dataset).text(out.report.message);
      }
      setToSend([]);
      setMsg([text, ...said].filter(Boolean).join(" "));
      await store.run("purchasing");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const firm = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.firm(ds, [...chosen]);
      store.replace(out.dataset, ds);
      setPick(null);
      const r = out.report;
      const pos = r.purchase_orders ?? [];
      setToSend(pos);
      setMsg(`${plural(r.firmed.length, "planned order")} firmed: ${r.firmed.slice(0, 4).map((f) => `${f.planned_id} → ${f.receipt_id}`).join(", ")}${r.firmed.length > 4 ? "…" : ""}.`
        + (pos.length ? ` Purchases went onto ${plural(pos.length, "purchase order")} (${pos.join(", ")}), grouped per supplier as on Buying${(r.notes ?? []).length ? `: ${(r.notes ?? []).map(namesOf(ds).text).join("; ")}` : ""}.` : "")
        + (Object.keys(r.skipped).length ? ` Not firmed: ${Object.entries(r.skipped).slice(0, 3).map(([k, v]) => `${k} (${v})`).join(", ")}.` : "")
        + " Everything is calculated again around them.");
      // firm orders change what every job reads (N353): the buyer's purchase orders, the stores' receipts, the money
      await store.planAll();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const toggle = (o: PlannedOrder) => {
    const n = new Set(chosen);
    if (n.has(o.id)) n.delete(o.id);
    else n.add(o.id);
    setPick(n);
  };
  return (
    <Panel flush title={`Firm zone: planned orders starting before ${day(limit)} (${zone} days)`} actions={
      plan.data ? <Edits><><button className="btn sm ghost" disabled={busy || planStale || !cands.length} onClick={() => setPick(new Set(chosen.size ? [] : cands.map((o) => o.id)))}>
        {chosen.size ? "Select none" : "Select all"}</button><button className="btn sm accent" disabled={busy || planStale || chosen.size === 0} onClick={firm}
        title={planStale ? "Recalculate the supply plan first" : "Turns these planned orders into firm purchase, production and transfer orders in your data. Undo reverts it."}>
        {busy ? "Saving…" : `Make ${chosen.size} order${chosen.size === 1 ? "" : "s"} firm`}</button></></Edits> : null}>
      {msg && <div className="banner info" role="status" style={{ margin: 12 }}><Badge sev="ok">Firmed</Badge><span>{msg}</span><span className="spacer" />
        {toSend.length > 0 && <Edits><button className="btn sm accent" disabled={busy} onClick={sendThem}
          title={serverMail ? "The server e-mails each one that needs no release to its supplier, the order attached, and records it as sent; the rest wait on Buying"
            : "Records every one of them that needs no release as sent; the rest wait on Buying"}>
          {serverMail ? `E-mail the ${plural(toSend.length, "purchase order")} to the suppliers` : `Send the ${plural(toSend.length, "purchase order")} now`}</button></Edits>}
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
      {err && <div className="banner error" style={{ margin: 12 }}><Badge sev="error">Firming failed</Badge>{err}</div>}
      {!plan.data ? <Empty title="No supply plan yet"><button className="btn" onClick={() => store.run("plan")} disabled={plan.running}>Calculate the supply plan</button></Empty>
        : planStale ? <Empty title="The supply plan is out of date"><button className="btn" onClick={() => store.run("plan")} disabled={plan.running}>{plan.running ? "Calculating…" : "Recalculate the supply plan"}</button></Empty>
        : cands.length === 0 ? <Empty title="Nothing to firm">No convertible planned order starts inside the firm zone.</Empty> : (
          <><p className="small muted" style={{ margin: "10px 12px 0" }}>Planned numbers are temporary: every plan hands them out again.
            A firm order gets its own number and keeps the planned one as “was …”.</p>
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            <table className="t">
              <thead><tr><th style={{ width: 28 }} /><th>Planned order</th><th>Becomes</th><th>Location</th><th>Product</th><th>From</th><th className="num">Qty</th><th>Start</th><th>Due</th></tr></thead>
              <tbody>
                {cands.map((o) => (
                  <tr key={o.id} className="clickable" onClick={() => toggle(o)}>
                    <td><input type="checkbox" checked={chosen.has(o.id)} onChange={() => toggle(o)} onClick={(e) => e.stopPropagation()} aria-label={`Firm ${o.id}`} /></td>
                    <td><b>{o.id}</b></td><td>{o.kind === "make" ? "production order" : o.kind === "buy" ? "purchase order line" : "stock transfer"}
                      {!!o.open_later?.length && <div className="small" style={{ color: "var(--warning-text)" }}>{o.open_later.join(", ")} is already on order but arrives
                        later; expediting it may do instead</div>}</td>
                    <td><Loc id={o.location} /></td><td><Prod id={o.product} /></td><td>{o.kind === "make" ? <span className="faint">made here</span> : o.origin ? <Loc id={o.origin} /> : <SourceFrom ds={ds} id={o.source_id} />}</td><td className="num">{qty(o.qty)}</td>
                    <td>{day(o.start_date)} {o.start_in_past && <Badge sev="warning">late start</Badge>}</td><td>{day(o.due_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div></>
        )}
    </Panel>
  );
}
