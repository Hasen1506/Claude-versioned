// The supply plan's exceptions, grouped into situations a person can act on: what is happening, why, and what
// can be done, in plain words and one date style. The engine's own messages stay available for analysts.
import type { Dataset, PlanException, PlanResult } from "../api/types";
import { dayName, plural, qty } from "./format";
import { href } from "./router";

export interface SituationItem { label: string; detail?: string; to?: string }
export interface Situation {
  code: string;
  severity: "error" | "warning" | "info";
  title: string;
  why: string;
  items: SituationItem[];
  actions: { label: string; to: string }[];
}

const KIND: Record<string, [string, string]> = {
  make: ["production run", "production runs"], buy: ["purchase", "purchases"], transfer: ["shipment", "shipments"],
};
const iso = (m: string, re: RegExp) => m.match(re)?.[1] ?? null;
const n = (v: number | null | undefined) => qty(Math.round(v ?? 0));

/** The earliest date anything started today could reach demand, from the engine's DEMAND_AT_RISK message. */
export const earliestArrival = (e: PlanException) => iso(e.message, /available (\d{4}-\d{2}-\d{2}) at the earliest/);

export function situations(plan: PlanResult, ds: Dataset): Situation[] {
  const year = new Date(ds.settings.planning_start + "T00:00:00").getFullYear();
  const d = (x: string | null | undefined) => dayName(x, year);
  const loc = Object.fromEntries((ds.locations ?? []).map((l) => [l.id, l.name])) as Record<string, string>;
  const prod = Object.fromEntries((ds.products ?? []).map((p) => [p.id, p.name])) as Record<string, string>;
  const where = (e: PlanException) => `${prod[e.product ?? ""] ?? e.product ?? ""} at ${loc[e.location ?? ""] ?? e.location ?? ""}`;
  const node = (e: PlanException) => (e.location && e.product ? href("plan", "node", e.location, e.product) : undefined);
  const orders = new Map(plan.orders.map((o) => [o.id, o]));
  const by = new Map<string, PlanException[]>();
  plan.exceptions.forEach((e) => by.set(e.code, [...(by.get(e.code) ?? []), e]));
  const out: Situation[] = [];
  const sum = (l: PlanException[]) => l.reduce((a, e) => a + (e.qty ?? 0), 0);
  const first = (l: PlanException[]) => l.map((e) => e.date).filter((x): x is string => !!x).sort()[0];

  for (const [code, list] of by) {
    const sev = list.some((e) => e.severity === "error") ? "error" : list.some((e) => e.severity === "warning") ? "warning" : "info";
    const l = [...list].sort((a, b) => (b.qty ?? 0) - (a.qty ?? 0));
    let s: Omit<Situation, "code" | "severity"> | null = null;
    switch (code) {
      case "DEMAND_AT_RISK": {
        const early = l.map(earliestArrival).filter((x): x is string => !!x).sort()[0];
        s = {
          title: `${n(sum(l))} units of demand will arrive late or short, from ${d(first(l))}`,
          why: early
            ? `Nothing started today can reach these customers before ${d(early)}, so demand due earlier needs stock that is already there or on its way.`
            : "Supply can't be planned in time for this demand with the current sources, lead times and capacity.",
          items: l.map((e) => ({ label: `${n(e.qty)} ${where(e)}`, detail: e.date !== first(l) ? `from ${d(e.date)}` : undefined, to: node(e) })),
          actions: [{ label: "See what's promised to customers", to: href("promise") }],
        };
        break;
      }
      case "START_IN_PAST": {
        s = {
          title: `${plural(l.length, "order")} should already have started`,
          why: "Their start date is before today. The plan dates them as if they start today, so each lands late; start them today to lose the least time.",
          items: l.map((e) => {
            const o = e.order_id ? orders.get(e.order_id) : undefined;
            const late = e.message.match(/\((\d+) d after need\)/)?.[1];
            return { label: `${e.order_id}: ${o ? KIND[o.kind]?.[0] ?? o.kind : ""} of ${n(o?.qty ?? e.qty)} ${prod[e.product ?? ""] ?? e.product} to ${loc[e.location ?? ""] ?? e.location}`,
              detail: late ? `${plural(+late, "day")} late` : undefined, to: e.order_id ? href("plan", "orders", e.order_id) : undefined };
          }),
          actions: [{ label: "Show all orders", to: href("plan", "orders") }],
        };
        break;
      }
      case "FENCE_SHIFT":
        s = {
          title: `${plural(l.length, "order")} moved out of the freeze window`,
          why: `Inside the planning time fence the plan doesn't add orders, so the shop floor keeps a stable plan. These were moved to the fence's end${iso(l[0].message, /fence end (\d{4}-\d{2}-\d{2})/) ? `, ${d(iso(l[0].message, /fence end (\d{4}-\d{2}-\d{2})/))}` : ""}.`,
          items: l.map((e) => ({ label: `${e.order_id}: ${n(e.qty)} ${where(e)}`, detail: `needed ${d(e.date)}`, to: e.order_id ? href("plan", "orders", e.order_id) : undefined })),
          actions: [{ label: "Change the time fence (planning policies)", to: href("data", "location_products") }],
        };
        break;
      case "RESCHEDULE_IN":
        s = {
          title: `${plural(l.length, "incoming order")} should arrive sooner`,
          why: "Each is due after the date it's needed, and a new order couldn't arrive any earlier. Ask the supplier or carrier to expedite.",
          items: l.map((e) => ({ label: `${e.order_id}: ${n(e.qty)} ${where(e)}`, detail: `needed ${d(e.date)}`, to: node(e) })),
          actions: [{ label: "See incoming orders", to: href("data", "receipts") }],
        };
        break;
      case "SCHEDULE_LATE":
        s = {
          title: `${plural(l.length, "production order")} the shop floor schedule finishes late`,
          why: "These orders carry the schedule's dates. The schedule already puts them as early as the machines and parts allow, so the plan counts them where they're needed and shows the delay instead of adding another order.",
          items: l.map((e) => ({ label: `${e.order_id}: ${n(e.qty)} ${where(e)}`, detail: `needed ${d(e.date)}${iso(e.message, /for (\d{4}-\d{2}-\d{2})/) ? `, ready ${d(iso(e.message, /for (\d{4}-\d{2}-\d{2})/))}` : ""}`, to: node(e) })),
          actions: [{ label: "Open the shop floor schedule", to: href("schedule", "orders") }],
        };
        break;
      case "CAPACITY_EARLIER":
        s = {
          title: `${plural(l.length, "production run")} start earlier to fit the machines`,
          why: "Planning within capacity found their machines full on the days they'd normally run, so they start earlier and the goods wait in stock.",
          items: l.map((e) => ({ label: `${e.order_id}: ${n(e.qty)} ${where(e)}`, detail: `needed ${d(e.date)}`, to: e.order_id ? href("plan", "orders", e.order_id) : undefined })),
          actions: [{ label: "See the load day by day", to: href("capacity") }],
        };
        break;
      case "CAPACITY_LATE":
        s = {
          title: `${plural(l.length, "production run")} only fit the machines later`,
          why: "Planning within capacity found no room early enough, even starting today, so these finish later than they're needed. Add a shift or overtime, use another machine, or promise the later date.",
          items: l.map((e) => ({ label: `${e.order_id}: ${n(e.qty)} ${where(e)}`, detail: `needed ${d(e.date)}`, to: e.order_id ? href("plan", "orders", e.order_id) : undefined })),
          actions: [{ label: "See the load day by day", to: href("capacity") }],
        };
        break;
      case "ALTERNATIVE_MACHINE":
        s = {
          title: `${plural(l.length, "step")} moved to an alternative machine`,
          why: "Their own machine is full on those days, and the routing allows another one.",
          items: l.map((e) => ({ label: `${e.order_id}: ${where(e)}`, detail: `on ${e.resource}`, to: e.order_id ? href("plan", "orders", e.order_id) : undefined })),
          actions: [{ label: "See the load day by day", to: href("capacity") }],
        };
        break;
      case "NO_VALID_SOURCE":
        s = {
          title: `${plural(l.length, "product and place", "products and places")} can't be supplied at all`,
          why: "No production source, purchasing source or transport lane is valid on the date it's needed. Add one, or extend an existing one's dates.",
          items: l.map((e) => ({ label: `${n(e.qty)} ${where(e)}`, detail: `from ${d(e.date)}`, to: node(e) })),
          actions: [{ label: "Open the data check", to: href("readiness") }],
        };
        break;
      case "STOCKOUT": {
        const parts = l.filter((e) => (ds.products ?? []).find((p) => p.id === e.product)?.type !== "FG");
        s = {
          title: `Stock runs out at ${plural(l.length, "product and place", "products and places")}`,
          why: `More is needed than is on hand or can arrive in time, so projected stock goes below zero.${parts.length
            ? " For a part, production that needs it can't start as planned until it arrives." : ""}`,
          items: l.map((e) => ({ label: where(e), detail: `from ${d(e.date)}, up to ${n(e.qty)} short`, to: node(e) })),
          actions: [],
        };
        break;
      }
      case "BELOW_SAFETY_STOCK":
        s = {
          title: `Stock drops below safety stock at ${plural(l.length, "place")}`,
          why: "Safety stock is the cushion against surprises. The plan couldn't keep it here, usually because supply can't arrive any sooner.",
          items: l.map((e) => ({ label: where(e), detail: `from ${d(e.date)}, up to ${n(e.qty)} short`, to: node(e) })),
          actions: [],
        };
        break;
      case "EXCESS_STOCK":
        s = {
          title: `Stock goes above its maximum at ${plural(l.length, "place")}`,
          why: "Lot sizes or minimum order quantities bring in more than the maximum stock set for these items.",
          items: l.map((e) => ({ label: where(e), detail: `from ${d(e.date)}, up to ${n(e.qty)} over`, to: node(e) })),
          actions: [{ label: "Planning policies", to: href("data", "location_products") }],
        };
        break;
      case "SHELF_LIFE_RISK":
        s = {
          title: `${plural(l.length, "item")} may expire before they're used`,
          why: "At times the stock would last longer than the product's shelf life.",
          items: l.map((e) => ({ label: where(e), detail: e.message.replace(/^Up to /, "up to "), to: node(e) })),
          actions: [],
        };
        break;
      case "CAPACITY_OVERLOAD":
        s = {
          title: `${plural(l.length, "machine or line", "machines or lines")} loaded beyond capacity and overtime`,
          why: sev === "error" ? "These resources can't do the work planned for them." : "Capacity isn't a hard limit here, so the plan goes over it; in practice the work would slip.",
          items: l.map((e) => ({ label: e.resource ?? "", detail: `from ${d(e.date)}, up to ${qty(e.qty)} h over`, to: e.resource ? href("plan", "capacity", e.resource) : undefined })),
          actions: [{ label: "Balance capacity month by month", to: href("sop") }],
        };
        break;
      case "CAPACITY_OVERTIME":
        s = {
          title: `${plural(l.length, "machine or line", "machines or lines")} need overtime`,
          why: "The regular shifts aren't enough, but the overtime allowed covers it.",
          items: l.map((e) => ({ label: e.resource ?? "", detail: `from ${d(e.date)}`, to: e.resource ? href("plan", "capacity", e.resource) : undefined })),
          actions: [],
        };
        break;
      case "SUPPLIER_CAPACITY":
        s = {
          title: `Suppliers asked for more than they can deliver, ${plural(l.length, "time")}`,
          why: "The plan orders more in a week than the supplier's weekly capacity.",
          items: l.map((e) => ({ label: `${where(e)}`, detail: `week of ${d(e.date)}, ${n(e.qty)} over`, to: node(e) })),
          actions: [{ label: "Purchasing sources", to: href("data", "purchasing_sources") }],
        };
        break;
      case "LANE_CAPACITY":
        s = {
          title: `Transport lanes over capacity, ${plural(l.length, "time")}`,
          why: "More is shipped in a week than the lane can carry.",
          items: l.map((e) => ({ label: e.message.split(":")[0], detail: `week of ${d(e.date)}, ${n(e.qty)} over` })),
          actions: [{ label: "Transport lanes", to: href("data", "lanes") }],
        };
        break;
      case "EOQ_FALLBACK":
        s = {
          title: `${plural(l.length, "item")} order exactly what's needed instead of an economic lot`,
          why: "An economic order quantity needs an ordering cost, a unit value and demand; one of them is missing, so the plan orders lot for lot.",
          items: l.map((e) => ({ label: where(e), to: node(e) })),
          actions: [{ label: "Planning policies", to: href("data", "location_products") }],
        };
        break;
      default:
        s = { title: `${codeLabel(code)} (${list.length})`, why: "", items: l.map((e) => ({ label: e.message, to: node(e) })), actions: [] };
    }
    out.push({ code, severity: sev, ...s });
  }
  const rank = { error: 0, warning: 1, info: 2 };
  return out.sort((a, b) => rank[a.severity] - rank[b.severity]);
}

/** A short plain name for an exception code from any page (the code itself stays visible for analysts). */
const CODE_LABEL: Record<string, string> = {
  DEMAND_AT_RISK: "Demand late or short", START_IN_PAST: "Should already have started", FENCE_SHIFT: "Moved out of the freeze window",
  RESCHEDULE_IN: "Incoming order needed sooner", NO_VALID_SOURCE: "No way to supply", BELOW_SAFETY_STOCK: "Below safety stock",
  EXCESS_STOCK: "Above maximum stock", SHELF_LIFE_RISK: "May expire", CAPACITY_OVERLOAD: "Over capacity",
  CAPACITY_OVERTIME: "Overtime needed", SUPPLIER_CAPACITY: "Supplier over capacity", LANE_CAPACITY: "Lane over capacity",
  EOQ_FALLBACK: "No economic lot size", STOCKOUT: "Stock runs out", SCHEDULE_LATE: "Scheduled to finish late",
  CAPACITY_EARLIER: "Started earlier to fit", CAPACITY_LATE: "Only fits later", ALTERNATIVE_MACHINE: "On an alternative machine",
};
export function codeLabel(code: string): string {
  if (CODE_LABEL[code]) return CODE_LABEL[code];
  const w = code.toLowerCase().replace(/_/g, " ");
  return w.charAt(0).toUpperCase() + w.slice(1);
}
