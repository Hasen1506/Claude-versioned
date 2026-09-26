// Registry of master/transactional data collections: how each is listed, keyed and cross-
// referenced. Adding an object type to the engine means adding one entry here.
import type { Dataset } from "../api/types";

type Obj = Record<string, unknown>;

export type CollectionKey =
  | "locations" | "products" | "location_products" | "resources" | "production_sources"
  | "purchasing_sources" | "lanes" | "calendars" | "changeovers" | "allocations" | "confirmations" | "demand" | "receipts" | "history" | "events" | "npi" | "overrides"
  | "movements" | "closed_orders" | "accuracy" | "rolled_weeks" | "vendors" | "purchase_orders";

export interface Column {
  label: string;
  get: (o: Obj, ds: Dataset) => string | number | null | undefined;
  num?: boolean;
}

export interface CollectionDef {
  key: CollectionKey;
  label: string;
  singular: string;
  defName: string;
  /** readiness-gate object_type */
  issueType: string;
  keyOf: (o: Obj, index: number) => string;
  columns: Column[];
  group: "Network" | "Make & buy" | "Planning data" | "Demand inputs" | "Execution";
  blurb: string;
}

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const lanesModes = (o: Obj) => ((o.modes as Obj[]) ?? []).map((m) => `${m.mode} ${m.transit_days}d`).join(", ");

export const COLLECTIONS: CollectionDef[] = [
  {
    key: "locations", label: "Locations", singular: "location", defName: "Location", issueType: "location",
    group: "Network", keyOf: (o) => s(o.id),
    blurb: "Plants, distribution centres, warehouses, stores, suppliers and customers — the nodes of your network.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Type", get: (o) => s(o.type) }, { label: "Region", get: (o) => s(o.region) },
      { label: "Calendar", get: (o) => s(o.calendar) },
    ],
  },
  {
    key: "lanes", label: "Transport lanes", singular: "lane", defName: "TransportLane", issueType: "lane",
    group: "Network", keyOf: (o) => s(o.id),
    blurb: "How goods move between two locations: modes, transit times, costs and capacities.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "From", get: (o) => s(o.origin) },
      { label: "To", get: (o) => s(o.destination) },
      { label: "Products", get: (o) => ((o.products as string[] | null)?.length ? (o.products as string[]).join(", ") : "all") },
      { label: "Modes", get: (o) => lanesModes(o) },
    ],
  },
  {
    key: "calendars", label: "Calendars", singular: "calendar", defName: "Calendar", issueType: "calendar",
    group: "Network", keyOf: (o) => s(o.id),
    blurb: "Working weekdays and holidays. Production lead times and capacity count working days only.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Workdays", get: (o) => ((o.workdays as number[]) ?? []).map((d) => "MTWTFSS"[d]).join("") },
      { label: "Holidays", get: (o) => ((o.holidays as string[]) ?? []).length, num: true },
    ],
  },
  {
    key: "products", label: "Products", singular: "product", defName: "Product", issueType: "product",
    group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Finished goods, sub-assemblies, raw materials and packaging, with base UoM, weight, volume and shelf life.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Name", get: (o) => s(o.name) },
      { label: "Type", get: (o) => s(o.type) }, { label: "UoM", get: (o) => s(o.base_uom ?? "EA") },
      { label: "kg", get: (o) => o.weight_kg as number, num: true },
    ],
  },
  {
    key: "resources", label: "Resources", singular: "resource", defName: "Resource", issueType: "resource",
    group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Machines, lines, labour pools and tools with shifts, efficiency (OEE) and overtime.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Plant", get: (o) => s(o.location) },
      { label: "Kind", get: (o) => s(o.kind) }, { label: "Units", get: (o) => o.units as number, num: true },
      { label: "h/day", num: true, get: (o) => {
        const u = (o.units as number) ?? 1, sh = (o.shifts_per_day as number) ?? 1, h = (o.hours_per_shift as number) ?? 8,
          e = (o.efficiency as number) ?? 0.85;
        return +(u * sh * h * e).toFixed(1);
      } },
    ],
  },  {
    key: "changeovers", label: "Changeovers", singular: "changeover", defName: "Changeover", issueType: "changeover",
    group: "Make & buy", keyOf: (_o, i) => `#${i}`,
    blurb: "The setup matrix: hours to switch a resource from one setup group to another. Without an entry a switch costs the operation's full setup.",
    columns: [
      { label: "Resource", get: (o) => s(o.resource) || "all" }, { label: "From", get: (o) => s(o.from_group) },
      { label: "To", get: (o) => s(o.to_group) }, { label: "Hours", get: (o) => o.hours as number, num: true },
    ],
  },

  {
    key: "production_sources", label: "Production sources", singular: "production source",
    defName: "ProductionSource", issueType: "production_source", group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "How a product is made at a plant: bill of material (components, scrap) and routing (operations on resources).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Plant", get: (o) => s(o.location) },
      { label: "Output", get: (o) => s(o.product) },
      { label: "Components", get: (o) => ((o.components as Obj[]) ?? []).length, num: true },
      { label: "Operations", get: (o) => ((o.operations as Obj[]) ?? []).length, num: true },
    ],
  },
  {
    key: "purchasing_sources", label: "Purchasing sources", singular: "purchasing source",
    defName: "PurchasingSource", issueType: "purchasing_source", group: "Make & buy", keyOf: (o) => s(o.id),
    blurb: "Who sells you a product: price, currency, duty, MOQ, lead time and capacity.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Supplier", get: (o) => s(o.supplier) },
      { label: "Product", get: (o) => s(o.product) }, { label: "To", get: (o) => s(o.location) },
      { label: "Price", get: (o) => `${o.price} ${s(o.currency) || ""}`.trim() },
      { label: "LT d", get: (o) => o.lead_time_days as number, num: true },
    ],
  },
  {
    key: "vendors", label: "Supplier purchasing data", singular: "supplier record", defName: "Vendor", issueType: "vendor",
    group: "Make & buy", keyOf: (o) => s(o.supplier),
    blurb: "How you buy from each supplier: contact, payment terms, whether they confirm orders, delivery tolerances and a purchasing block. A supplier without a record buys on the defaults.",
    columns: [
      { label: "Supplier", get: (o) => s(o.supplier) }, { label: "Contact", get: (o) => s(o.contact) },
      { label: "Pay days", get: (o) => o.payment_terms_days as number, num: true },
      { label: "Confirms", get: (o) => (o.confirmation_required ? "yes" : "") },
      { label: "Blocked", get: (o) => (o.blocked ? `yes${o.block_reason ? `: ${s(o.block_reason)}` : ""}` : "") },
    ],
  },
  {
    key: "location_products", label: "Planning policies", singular: "planning policy", defName: "LocationProduct",
    issueType: "location_product", group: "Planning data", keyOf: (o) => `${s(o.location)}|${s(o.product)}`,
    blurb: "How each product is planned at each location: strategy, stock, lot sizing, safety stock, fences.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Strategy", get: (o) => s(o.strategy ?? "MTS_CONSUME") },
      { label: "Lot", get: (o) => s((o.lot_sizing as Obj | undefined)?.policy ?? "L4L") },
      { label: "Safety stock", get: (o) => s((o.safety_stock as Obj | undefined)?.method ?? "none") },
      { label: "On hand", get: (o) => (o.on_hand as number) ?? 0, num: true },
    ],
  },
  {
    key: "demand", label: "Demand", singular: "demand record", defName: "DemandRecord", issueType: "demand",
    group: "Planning data", keyOf: (o, i) => s(o.id) || `#${i}`,
    blurb: "Forecasts (optionally spread over a period's working days) and firm sales orders.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Location", get: (o) => s(o.location) },
      { label: "Product", get: (o) => s(o.product) }, { label: "Date", get: (o) => s(o.date) },
      { label: "Kind", get: (o) => s(o.kind ?? "forecast") }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "receipts", label: "Scheduled receipts", singular: "scheduled receipt", defName: "ScheduledReceipt",
    issueType: "receipt", group: "Planning data", keyOf: (o) => s(o.id),
    blurb: "Firm supply already in the pipeline: open POs, released production orders, stock in transit.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Kind", get: (o) => s(o.kind) },
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Due", get: (o) => s(o.due_date) }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "purchase_orders", label: "Purchase orders", singular: "purchase order", defName: "PurchaseOrder",
    issueType: "purchase_order", group: "Execution", keyOf: (o) => s(o.id),
    blurb: "Purchase order headers: supplier, receiving place, order date, approval and when it was sent. The lines are the scheduled receipts that name the order (Buying manages both).",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Supplier", get: (o) => s(o.supplier) },
      { label: "To", get: (o) => s(o.location) }, { label: "Ordered", get: (o) => s(o.order_date) },
      { label: "Sent", get: (o) => s(o.sent_on) }, { label: "Approved", get: (o) => (o.approved === false ? "no" : "yes") },
    ],
  },
  {
    key: "allocations", label: "Allocations", singular: "allocation", defName: "Allocation", issueType: "allocation",
    group: "Planning data", keyOf: (o) => s(o.id),
    blurb: "Product allocation: the most that may be promised to a product (and customers) in a period, whatever the stock.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Customers", get: (o) => ((o.customers as string[]) ?? []).join(", ") || "all" },
      { label: "From", get: (o) => s(o.start) }, { label: "To", get: (o) => s(o.end) },
      { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "confirmations", label: "Confirmations", singular: "confirmation", defName: "Confirmation", issueType: "confirmation",
    group: "Planning data", keyOf: (_o, i) => `#${i}`,
    blurb: "Committed promises (schedule lines) per sales order. Written by Promising → Commit; they claim supply in every later check.",
    columns: [
      { label: "Order", get: (o) => s(o.order) }, { label: "From", get: (o) => s(o.ship_from) },
      { label: "Ships", get: (o) => s(o.ship_date) }, { label: "Delivers", get: (o) => s(o.date) },
      { label: "Method", get: (o) => s(o.method ?? "atp") }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "history", label: "Sales history", singular: "history row", defName: "SalesHistory", issueType: "history",
    group: "Demand inputs", keyOf: (_o, i) => `#${i}`,
    blurb: "What actually sold, per location, product and date (long format). The forecast learns from it; promo rows are cleansed.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Date", get: (o) => s(o.date) }, { label: "Qty", get: (o) => o.qty as number, num: true },
      { label: "Promo", get: (o) => (o.promo ? "yes" : "") },
    ],
  },
  {
    key: "events", label: "Demand events", singular: "event", defName: "DemandEvent", issueType: "event",
    group: "Demand inputs", keyOf: (o) => s(o.id),
    blurb: "Promotions, price changes, launches, competitor moves. Past events are cleansed from history and their lift measured; future ones lift the forecast.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Kind", get: (o) => s(o.kind) },
      { label: "From", get: (o) => s(o.start) }, { label: "To", get: (o) => s(o.end) },
      { label: "Lift", get: (o) => (o.lift === null || o.lift === undefined ? "measured" : `${Math.round((o.lift as number) * 100)}%`) },
    ],
  },
  {
    key: "npi", label: "New products (NPI)", singular: "NPI rule", defName: "NpiRule", issueType: "npi",
    group: "Demand inputs", keyOf: (o) => `${s(o.location)}|${s(o.product)}`,
    blurb: "Forecast a product without history from a like product: scale, launch date, ramp-up and cannibalisation.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Like", get: (o) => s(o.like_product) }, { label: "Scale", get: (o) => `${Math.round(((o.scale as number) ?? 1) * 100)}%` },
      { label: "Launch", get: (o) => s(o.launch_date) },
    ],
  },
  {
    key: "overrides", label: "Consensus overrides", singular: "override", defName: "ForecastOverride", issueType: "override",
    group: "Demand inputs", keyOf: (_o, i) => `#${i}`,
    blurb: "Planner or sales adjustments to one forecast period: a final quantity or a percentage change, with a reason.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Period of", get: (o) => s(o.date) },
      { label: "Change", get: (o) => (o.qty !== null && o.qty !== undefined ? `= ${o.qty}` : `${Math.round(((o.change as number) ?? 0) * 100)}%`) },
      { label: "Reason", get: (o) => s(o.reason) },
    ],
  },
  {
    key: "movements", label: "Goods movements", singular: "goods movement", defName: "GoodsMovement", issueType: "movement",
    group: "Execution", keyOf: (o) => s(o.id),
    blurb: "The stock journal: openings, goods receipts, component issues, sales, transfer issues, scrap and count adjustments. On-hand is the sum of these.",
    columns: [
      { label: "Id", get: (o) => s(o.id) }, { label: "Date", get: (o) => s(o.date) }, { label: "Type", get: (o) => s(o.type) },
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Reference", get: (o) => s(o.reference) }, { label: "Qty", get: (o) => o.qty as number, num: true },
    ],
  },
  {
    key: "closed_orders", label: "Closed orders", singular: "closed order", defName: "ClosedOrder", issueType: "closed_order",
    group: "Execution", keyOf: (o) => `${s(o.kind)}|${s(o.id)}`,
    blurb: "Orders the roll-forward completed, with due and delivery dates: the record OTIF and supplier reliability are measured on.",
    columns: [
      { label: "Kind", get: (o) => s(o.kind) }, { label: "Id", get: (o) => s(o.id) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Due", get: (o) => s(o.due_date) }, { label: "Delivered", get: (o) => s(o.last_delivery) },
      { label: "Ordered", get: (o) => o.ordered_qty as number, num: true }, { label: "Qty", get: (o) => o.delivered_qty as number, num: true },
    ],
  },
  {
    key: "accuracy", label: "Forecast accuracy log", singular: "accuracy record", defName: "AccuracyRecord", issueType: "accuracy",
    group: "Execution", keyOf: (_o, i) => `#${i}`,
    blurb: "Forecast against actual sales per series and elapsed week, logged by every roll-forward.",
    columns: [
      { label: "Location", get: (o) => s(o.location) }, { label: "Product", get: (o) => s(o.product) },
      { label: "Week of", get: (o) => s(o.start) }, { label: "Forecast", get: (o) => o.forecast as number, num: true },
      { label: "Actual", get: (o) => o.actual as number, num: true },
    ],
  },
  {
    key: "rolled_weeks", label: "Rolled weeks", singular: "rolled week", defName: "RolledWeek", issueType: "rolled_week",
    group: "Execution", keyOf: (_o, i) => `#${i}`,
    blurb: "The weeks the roll-forward has closed. Each later roll re-reads their actuals from the journal, so a late posting still counts.",
    columns: [{ label: "From", get: (o) => s(o.start) }, { label: "To (exclusive)", get: (o) => s(o.end) }],
  },
];

export const byKey = Object.fromEntries(COLLECTIONS.map((c) => [c.key, c])) as Record<CollectionKey, CollectionDef>;
export const byIssueType = Object.fromEntries(COLLECTIONS.map((c) => [c.issueType, c])) as Record<string, CollectionDef>;

export function items(ds: Dataset, key: CollectionKey): Obj[] {
  return ((ds as unknown as Record<string, Obj[] | undefined>)[key] ?? []) as Obj[];
}

/** Where an id is referenced — so deleting or renaming never silently breaks the network. */
export function whereUsed(ds: Dataset, kind: "location" | "product" | "resource" | "calendar", id: string): string[] {
  const out: string[] = [];
  const add = (cond: boolean, what: string) => cond && out.push(what);
  if (kind === "location") {
    for (const r of ds.resources ?? []) add(r.location === id, `resource ${r.id}`);
    for (const p of ds.production_sources ?? []) add(p.location === id, `production source ${p.id}`);
    for (const p of ds.purchasing_sources ?? []) add(p.supplier === id || p.location === id, `purchasing source ${p.id}`);
    for (const v of ds.vendors ?? []) add(v.supplier === id, "its supplier purchasing data");
    for (const p of ds.purchase_orders ?? []) add(p.supplier === id || p.location === id, `purchase order ${p.id}`);
    for (const l of ds.lanes ?? []) add(l.origin === id || l.destination === id, `lane ${l.id}`);
    const lp = (ds.location_products ?? []).filter((x) => x.location === id).length;
    add(lp > 0, `${lp} planning polic${lp === 1 ? "y" : "ies"}`);
    const dm = (ds.demand ?? []).filter((x) => x.location === id).length;
    add(dm > 0, `${dm} demand record(s)`);
    const hs = (ds.history ?? []).filter((x) => x.location === id).length;
    add(hs > 0, `${hs} history row(s)`);
    for (const n of ds.npi ?? []) add(n.location === id || n.like_location === id, `NPI rule ${n.location}|${n.product}`);
    for (const e of ds.events ?? []) add(!!e.locations?.includes(id), `event ${e.id}`);
  }
  if (kind === "product") {
    for (const p of ds.production_sources ?? []) {
      add(p.product === id, `output of ${p.id}`);
      add((p.components ?? []).some((c) => c.product === id), `component in ${p.id}`);
    }
    for (const p of ds.purchasing_sources ?? []) add(p.product === id, `purchasing source ${p.id}`);
    for (const l of ds.lanes ?? []) add(!!l.products?.includes(id), `lane ${l.id}`);
    const lp = (ds.location_products ?? []).filter((x) => x.product === id).length;
    add(lp > 0, `${lp} planning polic${lp === 1 ? "y" : "ies"}`);
    const dm = (ds.demand ?? []).filter((x) => x.product === id).length;
    add(dm > 0, `${dm} demand record(s)`);
    const hs = (ds.history ?? []).filter((x) => x.product === id).length;
    add(hs > 0, `${hs} history row(s)`);
    for (const n of ds.npi ?? []) add(n.product === id || n.like_product === id, `NPI rule ${n.location}|${n.product}`);
    for (const e of ds.events ?? []) add(!!e.products?.includes(id), `event ${e.id}`);
  }
  if (kind === "resource") {
    for (const p of ds.production_sources ?? [])
      for (const op of p.operations ?? []) {
        add(op.resource === id, `${p.id} op ${op.seq} (machine)`);
        add(op.labor_resource === id, `${p.id} op ${op.seq} (labour)`);
      }
  }
  if (kind === "calendar") {
    add(ds.settings.default_calendar === id, "settings (default calendar)");
    for (const l of ds.locations ?? []) add(l.calendar === id, `location ${l.id}`);
    for (const r of ds.resources ?? []) add(r.calendar === id, `resource ${r.id}`);
  }
  return out;
}

export function issueRoute(objectType: string, objectId: string): string[] | null {
  if (objectType === "settings") return ["settings"];
  if (objectType === "network") return ["network"];
  const c = byIssueType[objectType];
  if (!c || objectId === "*") return c ? ["data", c.key] : null;
  if (c.key === "overrides") return ["data", c.key];
  const id = c.key === "location_products" || c.key === "npi" ? objectId.replace("/", "|") : objectId;
  return ["data", c.key, id];
}
