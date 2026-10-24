// Work waiting, by job (Enterprise 8.4, N352): what each person who opens the app has to do now, from the results
// "Plan everything" already calculated, each item linked to the screen where it is done. Home shows every job; Money
// shows the accountant's.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Dataset } from "../api/types";
import { day, money, plural } from "../lib/format";
import { href } from "../lib/router";
import { firmCandidates } from "../pages/Firming";
import { namesOf } from "../lib/names";
import { useStore } from "../state/store";

export type Job = "planning" | "demand" | "orders" | "production" | "buying" | "stores" | "accounts";
export interface WorkItem { text: string; to: string }
export interface JobWork { job: Job; label: string; items: WorkItem[] }

const LABEL: Record<Job, string> = { planning: "Planning", demand: "Demand", orders: "Order desk", production: "Production",
  buying: "Buying", stores: "Stores", accounts: "Accounts" };

const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** Goods waiting in goods in to be put away, per place with bins (the first few). */
function usePutAway(ds: Dataset): [string, number][] {
  const [n, setN] = useState<[string, number][]>([]);
  useEffect(() => {
    let live = true;
    const places = [...new Set((ds.bins ?? []).map((b) => b.location))].slice(0, 3);
    if (!places.length) { setN([]); return; }
    Promise.all(places.map((p) => api.warehouse(ds, p).then((v) => [p, v.loose.filter((r) => r.to_put_away > 1e-6).length] as [string, number])))
      .then((x) => { if (live) setN(x.filter(([, k]) => k > 0)); }, () => live && setN([]));
    return () => { live = false; };
  }, [ds]);
  return n;
}

/** Series whose forecast keeps missing one way (the tracking signal past its limit, N363). */
function useBiased(ds: Dataset): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    if (!(ds.forecast_snapshots ?? []).length) { setN(0); return; }
    api.valueAdd(ds).then((v) => { if (live) setN(v.biased ?? 0); }, () => live && setN(0));
    return () => { live = false; };
  }, [ds]);
  return n;
}

export function useWorkWaiting(ds: Dataset): JobWork[] {
  const runs = useStore((s) => s.runs);
  const outdated = useStore((s) => (s.validation?.issues ?? []).some((i) => i.code === "FORECAST_INPUTS_CHANGED"));
  const putAway = usePutAway(ds);
  const biased = useBiased(ds);
  const start = ds.settings.planning_start;
  const cur = ds.settings.currency;
  const week = addDays(start, 6);
  const out: JobWork[] = [];
  const add = (job: Job, items: (WorkItem | false | null | undefined | 0)[]) => {
    const list = items.filter((x): x is WorkItem => !!x);
    out.push({ job, label: LABEL[job], items: list });
  };

  const plan = runs.plan.data?.ok ? runs.plan.data : null;
  const tower = runs.tower.data?.ok ? runs.tower.data : null;
  const firm = plan ? firmCandidates(ds, plan.orders).length : 0;
  const problems = tower ? tower.worklist.filter((w) => w.status === "open").length : 0;
  add("planning", [
    firm > 0 && { text: `${plural(firm, "planned order")} in the firm zone to make firm`, to: href("plan", "firm") },
    problems > 0 && { text: `${plural(problems, "problem")} on the follow-up list`, to: href("tower", "inbox") },
  ]);

  add("demand", [
    biased > 0 && { text: `${plural(biased, "forecast")} that keep${biased === 1 ? "s" : ""} missing one way`, to: href("demand", "value") },
    outdated && { text: "The forecast changed since the supply plan last used it", to: href("demand", "overview") },
  ]);

  const prom = runs.promise.data?.ok ? runs.promise.data : null;
  const sold = runs.sales.data;
  const blocked = (sold?.orders ?? []).filter((o) => o.credit_block && o.status !== "closed" && o.status !== "cancelled").length;
  const quotes = (sold?.quotations ?? []).filter((q) => q.status === "open" && q.valid_to <= week).length;
  add("orders", [
    prom && prom.kpis.at_risk_orders > 0 && { text: `${plural(prom.kpis.at_risk_orders, "customer order")} at risk of missing the date promised`, to: href("promise", "bop") },
    prom && prom.kpis.orders - prom.kpis.on_time_orders > 0 && { text: `${plural(prom.kpis.orders - prom.kpis.on_time_orders, "customer order")} not confirmed for the date asked`, to: href("promise", "orders") },
    blocked > 0 && { text: `${plural(blocked, "order")} held on a credit block`, to: href("selling", "orders") },
    quotes > 0 && { text: `${plural(quotes, "quotation")} running out by ${day(week)}`, to: href("selling", "quotes") },
  ]);

  const shop = runs.schedule.data?.ok ? runs.schedule.data : null;
  if (shop && shop.kpis.orders > 0) {
    add("production", [
      shop.kpis.late_orders > 0 && { text: `${plural(shop.kpis.late_orders, "order")} the shop floor schedule finishes late`, to: href("schedule", "board") },
    ]);
  }

  const buy = runs.purchasing.data?.ok ? runs.purchasing.data : null;
  if (buy) {
    const t = buy.totals;
    add("buying", [
      t.due_now > 0 && { text: `${plural(t.due_now, "purchase")} to order this week, worth ${money(t.due_now_value, cur)}`, to: href("buying", "order") },
      t.awaiting_approval > 0 && { text: `${plural(t.awaiting_approval, "purchase order")} to release`, to: href("buying", "orders") },
      t.to_send > 0 && { text: `${plural(t.to_send, "purchase order")} to send`, to: href("buying", "orders") },
      t.confirmations_overdue > 0 && { text: `${plural(t.confirmations_overdue, "confirmation")} to chase`, to: href("buying", "orders") },
      t.late_lines > 0 && { text: `${plural(t.late_lines, "order line")} late`, to: href("buying", "orders") },
    ]);
  }

  const act = runs.actuals.data;
  const sales = runs.sales.data;
  if (act) {
    const open = act.open_orders.filter((o) => o.open > 1e-6);
    const inbound = open.filter((o) => o.kind !== "sales" && o.due_date <= week);
    const late = inbound.filter((o) => o.past_due).length;
    const ship = (sales?.to_deliver ?? []).filter((x) => x.ship_date <= week).length;
    const tasks = (ds.warehouse_tasks ?? []).filter((t) => t.status === "open").length;
    add("stores", [
      ...putAway.map(([p, k]) => ({ text: `${plural(k, "product")} in goods in at ${namesOf(ds).loc(p)} to put away`, to: href("warehouse", "putaway", p) })),
      tasks > 0 && { text: `${plural(tasks, "warehouse task")} open`, to: href("warehouse", "tasks") },
      inbound.length > 0 && { text: `${plural(inbound.length, "receipt")} due in by ${day(week)}${late ? `, ${late} of them past due` : ""}`, to: href("execution", "orders") },
      ship > 0 && { text: `${plural(ship, "order line")} to ship by ${day(week)}`, to: href("selling", "deliver") },
    ]);
  }

  if (sales || buy) {
    const bill = (sales?.to_bill ?? []).reduce((a, b) => a + (b.value ?? 0), 0);
    const nbill = sales?.to_bill.length ?? 0;
    const overdue = (sales?.invoices ?? []).filter((i) => i.status === "overdue");
    const remind = (sales?.invoices ?? []).filter((i) => (i.reminder_due ?? 0) > 0).length;
    const pay = buy?.payables;
    const owed = (pay?.payables ?? []).reduce((a, p) => a + p.overdue + p.due_soon, 0);
    const blocked = buy?.totals.blocked_invoices ?? 0;
    add("accounts", [
      nbill > 0 && { text: `${money(bill, cur)} shipped and not invoiced (${plural(nbill, "line")})`, to: href("selling", "bill") },
      overdue.length > 0 && { text: `${plural(overdue.length, "customer invoice")} overdue, ${money(overdue.reduce((a, i) => a + i.open, 0), cur)} to collect`, to: href("selling", "bill") },
      remind > 0 && { text: `${plural(remind, "payment reminder")} to send`, to: href("selling", "bill") },
      owed > 0.005 && { text: `${money(owed, cur)} owed to suppliers, due or overdue within 7 days`, to: href("buying", "owed") },
      blocked > 0 && { text: `${plural(blocked, "supplier invoice")} blocked for a price or quantity difference`, to: href("buying", "invoices") },
    ]);
  }
  return out;
}

/** The jobs as a list: each job's items, or that nothing waits. */
export function WorkList({ ds, only }: { ds: Dataset; only?: Job[] }) {
  const work = useWorkWaiting(ds).filter((w) => !only || only.includes(w.job));
  if (!work.length) return null;
  return (
    <dl className="work">
      {work.map((w) => (
        <div key={w.job} className="work-job" aria-label={`${w.label} work`}>
          <dt>{w.label}</dt>
          <dd>{w.items.length === 0 ? <span className="faint">Nothing waiting</span>
            : <ul className="plain">{w.items.map((i) => <li key={i.text}><a href={i.to}>{i.text}</a></li>)}</ul>}</dd>
        </div>
      ))}
    </dl>
  );
}
