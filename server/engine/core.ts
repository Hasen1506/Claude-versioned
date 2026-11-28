import crypto from "node:crypto";
import type {
  BucketOut,
  Dataset,
  Issue,
  LevelPreview,
  NetEdge,
  NetLocation,
  NetNode,
  NetOption,
  NetworkView,
  NodeBucket,
  NodePlan,
  Peg,
  PlanException,
  PlanResult,
  PlanTrace,
  PlannedOrder,
  Requirement,
  ResourcePlan,
  SetupItem,
  ValidationResult,
} from "../types.ts";

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  d.setUTCDate(d.getUTCDate() + Math.round(days));
  return d.toISOString().slice(0, 10);
}

export function diffDays(a: string, b: string): number {
  const da = new Date(`${a}T00:00:00Z`).getTime();
  const db = new Date(`${b}T00:00:00Z`).getTime();
  if (Number.isNaN(da) || Number.isNaN(db)) return 0;
  return Math.round((db - da) / 86_400_000);
}

export function buildBuckets(start: string, horizonDays: number, size: "day" | "week" | "month" = "week"): BucketOut[] {
  const step = size === "day" ? 1 : size === "month" ? 30 : 7;
  const count = Math.max(1, Math.ceil(Math.max(1, horizonDays) / step));
  const out: BucketOut[] = [];
  for (let i = 0; i < count; i++) {
    const s = addDays(start, i * step);
    const e = addDays(start, Math.min(horizonDays, (i + 1) * step) - 1);
    const label = size === "day" ? s : size === "month" ? s.slice(0, 7) : `W${i + 1} (${s.slice(5)})`;
    out.push({ index: i, start: s, end: e, label });
  }
  return out;
}

export function bucketIndexFor(date: string, start: string, buckets: BucketOut[]): number {
  const diff = diffDays(start, date);
  if (diff <= 0) return 0;
  for (let i = 0; i < buckets.length; i++) {
    if (date >= buckets[i].start && date <= buckets[i].end) return i;
  }
  return buckets.length - 1;
}

export function carryingRate(ds: Dataset): number {
  return (ds.settings?.wacc ?? 0.12) + (ds.settings?.holding_spread ?? 0.06);
}

export function resourceHoursPerDay(r: NonNullable<Dataset["resources"]>[number]): number {
  return (r.shifts_per_day ?? 1) * (r.hours_per_shift ?? 8) * (r.units ?? 1) * (r.efficiency ?? 1);
}

export function unitValueOf(ds: Dataset, locId: string, prodId: string): { value: number; basis: string } {
  const lp = (ds.location_products ?? []).find((x) => x.location === locId && x.product === prodId);
  if (lp?.unit_cost && lp.unit_cost > 0) return { value: lp.unit_cost, basis: "location_cost" };
  const prod = (ds.products ?? []).find((p) => p.id === prodId);
  const pur = (ds.purchasing_sources ?? []).find((s) => s.product === prodId && (!s.location || s.location === locId));
  if (pur?.price && pur.price > 0) return { value: pur.price, basis: "purchase_price" };
  const ps = (ds.production_sources ?? []).find((s) => s.product === prodId && s.location === locId);
  if (ps) {
    let bomCost = 0;
    const outQty = Math.max(1e-9, ps.output_qty ?? 1);
    for (const line of ps.components ?? []) {
      const compPur = (ds.purchasing_sources ?? []).find((x) => x.product === line.product);
      const compProd = (ds.products ?? []).find((p) => p.id === line.product);
      const compUnit = compPur?.price ?? (compProd?.price ? compProd.price * 0.5 : 10);
      bomCost += (compUnit * (line.qty ?? 1)) / outQty;
    }
    const runCost = (ps.operations ?? []).reduce((sum, r) => sum + ((r.run_hours_per_unit ?? 0) * 500), 0) + (ps.conversion_cost_per_unit ?? 0);
    if (bomCost + runCost > 0) return { value: Math.round((bomCost + runCost) * 100) / 100, basis: "bom_rollup" };
  }
  if (prod?.price && prod.price > 0) return { value: Math.round(prod.price * 0.6 * 100) / 100, basis: "price_margin" };
  return { value: 10, basis: "default" };
}

export function validateDataset(ds: Dataset): ValidationResult {
  const issues: Issue[] = [];
  const locs = ds.locations ?? [];
  const prods = ds.products ?? [];
  const locIds = new Set(locs.map((l) => l.id));
  const prodIds = new Set(prods.map((p) => p.id));

  if (locs.length === 0) {
    issues.push({
      code: "NO_LOCATIONS",
      severity: "error",
      object_type: "location",
      object_id: "",
      message: "Add at least one location (plant, warehouse, store, or customer) before planning.",
      hint: "Open Set up -> Places and add a location.",
      field: "locations",
    });
  }
  if (prods.length === 0) {
    issues.push({
      code: "NO_PRODUCTS",
      severity: "error",
      object_type: "product",
      object_id: "",
      message: "Add at least one product before planning.",
      hint: "Open Set up -> Products and add a product.",
      field: "products",
    });
  }

  for (const d of ds.demand ?? []) {
    if (!locIds.has(d.location)) {
      issues.push({
        code: "UNKNOWN_LOCATION",
        severity: "error",
        object_type: "demand",
        object_id: d.id ?? `${d.location}:${d.product}`,
        message: `Demand references unknown location ${d.location}.`,
        hint: "Choose an existing location or add it under Places.",
        field: "location",
      });
    }
    if (!prodIds.has(d.product)) {
      issues.push({
        code: "UNKNOWN_PRODUCT",
        severity: "error",
        object_type: "demand",
        object_id: d.id ?? `${d.location}:${d.product}`,
        message: `Demand references unknown product ${d.product}.`,
        hint: "Choose an existing product or add it under Products.",
        field: "product",
      });
    }
  }

  for (const l of ds.lanes ?? []) {
    if (!locIds.has(l.origin) || !locIds.has(l.destination)) {
      issues.push({
        code: "UNKNOWN_LOCATION",
        severity: "error",
        object_type: "lane",
        object_id: l.id,
        message: `Lane ${l.id} connects an unknown location.`,
        hint: "Update origin and destination to existing locations.",
        field: "origin",
      });
    }
  }

  const hasDemand = (ds.demand?.length ?? 0) > 0 || (ds.history?.length ?? 0) > 0;
  if (locs.length > 0 && prods.length > 0 && !hasDemand) {
    issues.push({
      code: "NO_DEMAND",
      severity: "warning",
      object_type: "demand",
      object_id: "",
      message: "No demand or sales history has been entered yet.",
      hint: "Enter demand on Demand -> Demand plan or upload sales history.",
      field: "demand",
    });
  }

  const hasSources =
    (ds.production_sources?.length ?? 0) > 0 ||
    (ds.purchasing_sources?.length ?? 0) > 0 ||
    (ds.lanes?.length ?? 0) > 0;

  const setup: SetupItem[] = [
    {
      step: "locations",
      status: locs.length > 0 ? "done" : "todo",
      text: locs.length > 0 ? `${locs.length} locations set up` : "Add your plants, warehouses, suppliers and customers",
      action: { label: "Add places", route: ["setup", "places"] },
    },
    {
      step: "products",
      status: prods.length > 0 ? "done" : "todo",
      text: prods.length > 0 ? `${prods.length} products set up` : "Add your finished products and raw materials",
      action: { label: "Add products", route: ["setup", "products"] },
    },
    {
      step: "sources",
      status: hasSources ? "done" : locs.length > 0 && prods.length > 0 ? "todo" : "info",
      text: hasSources ? "Supply sources configured" : "Say how each product is made, bought or shipped",
      action: { label: "Set up supply", route: ["setup", "supply"] },
    },
    {
      step: "demand",
      status: hasDemand ? "done" : locs.length > 0 && prods.length > 0 ? "todo" : "info",
      text: hasDemand
        ? `${ds.demand?.length ?? 0} demand lines${ds.history?.length ? ` and ${ds.history.length} history rows` : ""}`
        : "Add customer demand or past sales",
      action: { label: "Enter demand", route: ["demand", "plan"] },
    },
  ];

  return {
    issues,
    blocking: issues.some((i) => i.severity === "error"),
    set_aside: [],
    setup,
  };
}

export function buildNetworkView(ds: Dataset): NetworkView {
  const layerMap: Record<string, number> = {
    supplier: 0,
    plant: 1,
    dc: 2,
    warehouse: 2,
    store: 3,
    customer: 4,
  };

  const prodsByLoc = new Map<string, Set<string>>();
  const addLocProd = (loc: string, prod: string) => {
    if (!prodsByLoc.has(loc)) prodsByLoc.set(loc, new Set());
    prodsByLoc.get(loc)!.add(prod);
  };

  for (const lp of ds.location_products ?? []) addLocProd(lp.location, lp.product);
  for (const ps of ds.production_sources ?? []) {
    addLocProd(ps.location, ps.product);
    for (const b of ps.components ?? []) addLocProd(ps.location, b.product);
  }
  for (const pu of ds.purchasing_sources ?? []) {
    addLocProd(pu.location, pu.product);
    addLocProd(pu.supplier, pu.product);
  }
  for (const d of ds.demand ?? []) addLocProd(d.location, d.product);

  const locations: NetLocation[] = (ds.locations ?? []).map((l) => ({
    id: l.id,
    name: l.name || l.id,
    type: l.type,
    region: l.region ?? "",
    lat: l.lat ?? null,
    lon: l.lon ?? null,
    layer: layerMap[l.type] ?? 2,
    products: [...(prodsByLoc.get(l.id) ?? [])].sort(),
    resources: (ds.resources ?? []).filter((r) => r.location === l.id).map((r) => r.id),
    production_sources: (ds.production_sources ?? []).filter((p) => p.location === l.id).map((p) => p.id),
  }));

  const edges: NetEdge[] = [];
  const laneGroups = new Map<string, { origin: string; destination: string; ids: string[]; products: Set<string>; allProducts: boolean; modes: Set<string>; transit: number | null }>();

  for (const ln of ds.lanes ?? []) {
    const k = `${ln.origin}->${ln.destination}`;
    let g = laneGroups.get(k);
    if (!g) {
      g = { origin: ln.origin, destination: ln.destination, ids: [], products: new Set(), allProducts: false, modes: new Set(), transit: null };
      laneGroups.set(k, g);
    }
    g.ids.push(ln.id);
    if (!ln.products || ln.products.length === 0) g.allProducts = true;
    else ln.products.forEach((p) => g!.products.add(p));
    for (const m of ln.modes ?? []) {
      g.modes.add(m.mode);
      if (g.transit === null || m.transit_days < g.transit) g.transit = m.transit_days;
    }
  }

  for (const g of laneGroups.values()) {
    edges.push({
      origin: g.origin,
      destination: g.destination,
      kind: "lane",
      ids: g.ids,
      products: g.allProducts ? null : [...g.products].sort(),
      modes: [...g.modes].sort(),
      transit_days: g.transit,
    });
  }

  const supGroups = new Map<string, { origin: string; destination: string; ids: string[]; products: Set<string>; transit: number | null }>();
  for (const pu of ds.purchasing_sources ?? []) {
    const k = `${pu.supplier}->${pu.location}`;
    let g = supGroups.get(k);
    if (!g) {
      g = { origin: pu.supplier, destination: pu.location, ids: [], products: new Set(), transit: null };
      supGroups.set(k, g);
    }
    g.ids.push(pu.id);
    g.products.add(pu.product);
    if (g.transit === null || pu.lead_time_days < g.transit) g.transit = pu.lead_time_days;
  }
  for (const g of supGroups.values()) {
    edges.push({
      origin: g.origin,
      destination: g.destination,
      kind: "purchase",
      ids: g.ids,
      products: [...g.products].sort(),
      modes: [],
      transit_days: g.transit,
    });
  }

  // Build nodes & supply options
  const nodeKeys = new Set<string>();
  for (const [loc, set] of prodsByLoc) {
    for (const prod of set) nodeKeys.add(`${loc}|${prod}`);
  }

  const nodes: NetNode[] = [];
  for (const nk of [...nodeKeys].sort()) {
    const [loc, prod] = nk.split("|");
    const options: NetOption[] = [];
    for (const ps of (ds.production_sources ?? []).filter((p) => p.location === loc && p.product === prod)) {
      options.push({
        kind: "make",
        source_id: ps.id,
        upstream: (ps.components ?? []).map((b) => [loc, b.product] as [string, string]),
      });
    }
    for (const pu of (ds.purchasing_sources ?? []).filter((p) => p.location === loc && p.product === prod)) {
      options.push({
        kind: "buy",
        source_id: pu.id,
        upstream: [],
      });
    }
    for (const ln of (ds.lanes ?? []).filter((l) => l.destination === loc && (!l.products || l.products.length === 0 || l.products.includes(prod)))) {
      options.push({
        kind: "transfer",
        source_id: ln.id,
        upstream: [[ln.origin, prod]],
      });
    }
    const locObj = (ds.locations ?? []).find((l) => l.id === loc);
    const prodObj = (ds.products ?? []).find((p) => p.id === prod);
    const baseLlc = prodObj?.type === "RM" ? 2 : prodObj?.type === "SFG" ? 1 : 0;
    const locOffset = locObj?.type === "plant" ? 1 : locObj?.type === "dc" || locObj?.type === "warehouse" ? 0 : 0;
    nodes.push({
      location: loc,
      product: prod,
      llc: baseLlc + locOffset,
      options,
    });
  }

  return { locations, edges, nodes, cycles: [] };
}

export interface PlanBundle {
  plan: PlanResult;
  requirements: Requirement[];
  pegs: Peg[];
}

export function computePlanBundle(ds: Dataset): PlanBundle {
  const val = validateDataset(ds);
  const currency = ds.settings?.currency ?? "INR";
  const rate = carryingRate(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const horizonDays = ds.settings?.horizon_days ?? 84;
  const bucketSize = ds.settings?.bucket ?? "week";
  const buckets = buildBuckets(start, horizonDays, bucketSize);

  if (val.blocking) {
    return {
      plan: {
        ok: false,
        currency,
        carrying_rate: rate,
        buckets,
        nodes: [],
        orders: [],
        requirements: [],
        receipts: [],
        pegs: [],
        resources: [],
        exceptions: [],
        kpis: {
          purchase_cost: 0,
          production_cost: 0,
          setup_cost: 0,
          ordering_cost: 0,
          transport_cost: 0,
          handling_cost: 0,
          holding_cost: 0,
          total_cost: 0,
          inventory_value_start: 0,
          inventory_value_end: 0,
          inventory_value_avg: 0,
          orders_make: 0,
          orders_buy: 0,
          orders_transfer: 0,
          independent_demand: 0,
          on_time_qty: 0,
          on_time_fill_rate: 1,
          max_utilization: 0,
        },
        issues: val.issues,
        planned_again: null,
        firming_sha256: null,
      },
      requirements: [],
      pegs: [],
    };
  }

  const net = buildNetworkView(ds);
  const locById = new Map((ds.locations ?? []).map((l) => [l.id, l]));
  const lpByKey = new Map((ds.location_products ?? []).map((lp) => [`${lp.location}|${lp.product}`, lp]));
  const prodSourceByKey = new Map<string, NonNullable<Dataset["production_sources"]>[number][]>();
  for (const ps of ds.production_sources ?? []) {
    const k = `${ps.location}|${ps.product}`;
    if (!prodSourceByKey.has(k)) prodSourceByKey.set(k, []);
    prodSourceByKey.get(k)!.push(ps);
  }
  const purSourceByKey = new Map<string, NonNullable<Dataset["purchasing_sources"]>[number][]>();
  for (const pu of ds.purchasing_sources ?? []) {
    const k = `${pu.location}|${pu.product}`;
    if (!purSourceByKey.has(k)) purSourceByKey.set(k, []);
    purSourceByKey.get(k)!.push(pu);
  }
  const lanesByDest = new Map<string, NonNullable<Dataset["lanes"]>[number][]>();
  for (const ln of ds.lanes ?? []) {
    if (!lanesByDest.has(ln.destination)) lanesByDest.set(ln.destination, []);
    lanesByDest.get(ln.destination)!.push(ln);
  }

  // Independent demand by (loc|prod) -> bucket -> qty
  const indDemand = new Map<string, number[]>();
  const depDemand = new Map<string, number[]>();
  const reqs: Requirement[] = [];
  const pegs: Peg[] = [];
  const ensureArr = (m: Map<string, number[]>, k: string) => {
    let arr = m.get(k);
    if (!arr) {
      arr = new Array(buckets.length).fill(0);
      m.set(k, arr);
    }
    return arr;
  };

  let totalIndependent = 0;
  let reqSeq = 1;
  for (const d of ds.demand ?? []) {
    if ((d.qty ?? 0) <= 0) continue;
    const endDate = addDays(start, horizonDays);
    if (d.date < start || d.date > endDate) continue;
    const k = `${d.location}|${d.product}`;
    const bi = bucketIndexFor(d.date, start, buckets);
    ensureArr(indDemand, k)[bi] += d.qty;
    totalIndependent += d.qty;
    reqs.push({
      id: d.id ?? `REQ-${String(reqSeq++).padStart(4, "0")}`,
      kind: d.kind === "sales_order" ? "sales_order" : "forecast",
      location: d.location,
      product: d.product,
      date: d.date,
      qty: d.qty,
      parent_order: null,
      priority: d.priority ?? 100,
      consumed_forecast: 0,
      past_due: d.date < start,
    });
  }

  // Scheduled receipts by (loc|prod) -> bucket -> qty
  const schedRec = new Map<string, number[]>();
  const receiptsOut: PlanResult["receipts"] = [];
  for (const r of ds.receipts ?? []) {
    const qtyRem = Math.max(0, r.qty ?? 0);
    if (qtyRem <= 0) continue;
    const k = `${r.location}|${r.product}`;
    const bi = bucketIndexFor(r.due_date, start, buckets);
    ensureArr(schedRec, k)[bi] += qtyRem;
    receiptsOut.push({
      id: r.id,
      kind: r.kind,
      location: r.location,
      product: r.product,
      qty: qtyRem,
      date: r.due_date,
    });
  }

  // Order nodes top-down: customer -> store -> dc/warehouse -> plant (FG -> SFG -> RM)
  const rankNode = (locId: string, prodId: string): number => {
    const l = locById.get(locId);
    const p = (ds.products ?? []).find((x) => x.id === prodId);
    const locRank = l?.type === "customer" ? 0 : l?.type === "store" ? 1 : l?.type === "dc" || l?.type === "warehouse" ? 2 : l?.type === "plant" ? 3 : 4;
    const prodRank = p?.type === "FG" ? 0 : p?.type === "SFG" ? 1 : 2;
    return prodRank * 10 + locRank;
  };

  const allNodeKeys = new Set<string>([
    ...net.nodes.map((n) => `${n.location}|${n.product}`),
    ...indDemand.keys(),
    ...lpByKey.keys(),
  ]);
  const orderedKeys = [...allNodeKeys]
    .filter((k) => {
      const [locId] = k.split("|");
      return locById.get(locId)?.type !== "supplier";
    })
    .sort((a, b) => {
      const [la, pa] = a.split("|");
      const [lb, pb] = b.split("|");
      return rankNode(la, pa) - rankNode(lb, pb) || a.localeCompare(b);
    });

  const orders: PlannedOrder[] = [];
  const nodePlans: NodePlan[] = [];
  const exceptions: PlanException[] = [];
  const resDailyLoad = new Map<string, Map<string, number>>();
  const resOrders = new Map<string, ResourcePlan["orders"]>();

  let makeSeq = 1;
  let buySeq = 1;
  let trSeq = 1;
  let purchaseCost = 0;
  let productionCost = 0;
  let setupCost = 0;
  let orderingCost = 0;
  let transportCost = 0;
  let handlingCost = 0;
  let holdingCost = 0;
  let invValStart = 0;
  let invValEnd = 0;
  let invValSum = 0;
  let lateDemandQty = 0;

  for (const nk of orderedKeys) {
    const [locId, prodId] = nk.split("|");
    const loc = locById.get(locId);
    const lp = lpByKey.get(nk);
    const ind = indDemand.get(nk) ?? new Array(buckets.length).fill(0);
    const dep = depDemand.get(nk) ?? new Array(buckets.length).fill(0);
    const rec = schedRec.get(nk) ?? new Array(buckets.length).fill(0);

    const totalNodeDemand = ind.reduce((s, x) => s + x, 0) + dep.reduce((s, x) => s + x, 0);
    const avgDaily = totalNodeDemand / Math.max(1, horizonDays);

    // Safety stock
    let ssQty = 0;
    let ssMethod = lp?.safety_stock?.method ?? "none";
    if (lp?.safety_stock?.method === "fixed") ssQty = lp.safety_stock.qty ?? 0;
    else if (lp?.safety_stock?.method === "days_of_supply") ssQty = Math.round(avgDaily * (lp.safety_stock.days ?? 0));
    else if (lp?.safety_stock?.method === "service_level") {
      const sl = lp.safety_stock.service_level ?? 0.95;
      const z = sl >= 0.99 ? 2.33 : sl >= 0.98 ? 2.05 : sl >= 0.95 ? 1.65 : 1.28;
      const cv = lp.safety_stock.demand_cv ?? 0.25;
      ssQty = Math.round(z * cv * avgDaily * Math.sqrt(7));
    }

    const { value: unitVal, basis: valBasis } = unitValueOf(ds, locId, prodId);
    let onHand = lp?.on_hand ?? 0;
    const startOnHand = onHand;
    invValStart += startOnHand * unitVal;

    // Pick primary supply source: make at plant, buy from supplier (product-specific), or internal transfer lane
    const makeSrcs = prodSourceByKey.get(nk) ?? [];
    const buySrcs = (purSourceByKey.get(nk) ?? []).filter((p) => !p.blocked);
    const laneSrcs = (lanesByDest.get(locId) ?? []).filter(
      (l) => locById.get(l.origin)?.type !== "supplier" && (!l.products || l.products.length === 0 || l.products.includes(prodId)),
    );
    const primaryKind: "make" | "buy" | "transfer" | null =
      makeSrcs.length > 0 ? "make" : buySrcs.length > 0 ? "buy" : laneSrcs.length > 0 ? "transfer" : null;

    const leadTimeDays =
      primaryKind === "make"
        ? Math.max(1, makeSrcs[0].fixed_lead_time_workdays ?? 2)
        : primaryKind === "buy"
          ? Math.max(1, buySrcs[0].lead_time_days ?? 7)
          : primaryKind === "transfer"
            ? Math.max(1, laneSrcs[0].modes?.[0]?.transit_days ?? 3)
            : null;

    const lotPolicy = lp?.lot_sizing?.policy ?? ds.settings?.default_lot_policy ?? "L4L";
    const fixedLot = lp?.lot_sizing?.fixed_qty ?? 0;
    const minQty = lp?.lot_sizing?.min_qty ?? 0;

    const nodeBuckets: NodeBucket[] = [];
    const orderIds: string[] = [];

    for (let bi = 0; bi < buckets.length; bi++) {
      const grossInd = ind[bi];
      const grossDep = dep[bi];
      const sched = rec[bi];
      const needBeforeOrder = grossInd + grossDep;
      const projectedBefore = onHand + sched - needBeforeOrder;
      let plannedQty = 0;
      let shortage = 0;
      let atRisk = 0;

      if (projectedBefore < ssQty && (needBeforeOrder > 0 || (loc?.type !== "customer" && ssQty > 0))) {
        const netReq = Math.max(0, ssQty - projectedBefore);
        if (primaryKind && netReq > 0) {
          let qty = netReq;
          if (lotPolicy === "FIXED" && fixedLot > 0) {
            qty = Math.ceil(netReq / fixedLot) * fixedLot;
          } else if (lotPolicy === "MIN_MAX" && lp?.max_stock && lp.max_stock > projectedBefore) {
            qty = Math.max(netReq, lp.max_stock - projectedBefore);
          }
          if (minQty > 0 && qty < minQty) qty = minQty;
          qty = Math.ceil(qty);

          const needDate = buckets[bi].start;
          const lt = leadTimeDays ?? 1;
          const wantedStart = addDays(needDate, -lt);
          const startInPast = wantedStart < start;
          const startDate = startInPast ? start : wantedStart;
          const dueDate = startInPast ? addDays(start, lt) : needDate;
          const delayDays = startInPast ? Math.max(0, diffDays(needDate, dueDate)) : 0;

          let orderId = "";
          let sourceId = "";
          let origin: string | null = null;
          let orderUnitCost = unitVal;
          let orderTotalCost = 0;
          const costs: Record<string, number> = {};

          if (primaryKind === "make") {
            const ps = makeSrcs[0];
            orderId = `MO-${String(makeSeq++).padStart(4, "0")}`;
            sourceId = ps.id;
            const resById = new Map((ds.resources ?? []).map((r) => [r.id, r]));
            let setupC = 0;
            let runHours = 0;
            for (const step of ps.operations ?? []) {
              const resObj = step.resource ? resById.get(step.resource) : undefined;
              const rateHr = resObj?.cost_per_hour ?? 350;
              const sHrs = step.setup_hours ?? 0;
              const rHrs = (step.run_hours_per_unit ?? 0.002) * qty;
              setupC += sHrs * rateHr;
              runHours += sHrs + rHrs;
              if (step.resource) {
                const stepHours = sHrs + rHrs;
                if (!resDailyLoad.has(step.resource)) resDailyLoad.set(step.resource, new Map());
                const dm = resDailyLoad.get(step.resource)!;
                dm.set(startDate, (dm.get(startDate) ?? 0) + stepHours);
                if (!resOrders.has(step.resource)) resOrders.set(step.resource, []);
                resOrders.get(step.resource)!.push({
                  order: orderId,
                  product: prodId,
                  firm: false,
                  hours: { [startDate]: Math.round(stepHours * 100) / 100 },
                });
              }
            }
            const convC = (ps.conversion_cost_per_unit ?? 0) * qty;
            const runC = Math.round((runHours * 350 + convC) * 100) / 100;
            setupC = Math.round(setupC * 100) / 100;
            costs.production = runC;
            costs.setup = setupC;
            orderTotalCost = runC + setupC;
            orderUnitCost = qty > 0 ? orderTotalCost / qty : 0;
            productionCost += runC;
            setupCost += setupC;

            // Explode BOM dependent demand at this plant
            const depBucket = bucketIndexFor(startDate, start, buckets);
            const outQty = Math.max(1e-9, ps.output_qty ?? 1);
            for (const line of ps.components ?? []) {
              const scrap = line.scrap ?? 0;
              const rawNeed = line.fixed_qty ? line.qty : (qty * (line.qty ?? 1)) / outQty;
              const compQty = Math.ceil(rawNeed / Math.max(0.01, 1 - scrap));
              const compKey = `${locId}|${line.product}`;
              ensureArr(depDemand, compKey)[depBucket] += compQty;
              reqs.push({
                id: `REQ-${String(reqSeq++).padStart(4, "0")}`,
                kind: "dependent",
                location: locId,
                product: line.product,
                date: startDate,
                qty: compQty,
                parent_order: orderId,
                priority: 100,
                consumed_forecast: 0,
                past_due: startDate < start,
              });
            }
          } else if (primaryKind === "buy") {
            const pu = buySrcs[0];
            orderId = `PO-P-${String(buySeq++).padStart(4, "0")}`;
            sourceId = pu.id;
            origin = pu.supplier;
            const unitPrice = pu.price ?? unitVal;
            const purC = Math.round(unitPrice * qty * (1 + (pu.duty_rate ?? 0)) * 100) / 100;
            const ordC = pu.ordering_cost ?? 0;
            costs.purchase = purC;
            costs.ordering = ordC;
            orderTotalCost = purC + ordC;
            orderUnitCost = unitPrice;
            purchaseCost += purC;
            orderingCost += ordC;
          } else {
            const ln = laneSrcs[0];
            orderId = `TR-${String(trSeq++).padStart(4, "0")}`;
            sourceId = ln.id;
            origin = ln.origin;
            const mode = ln.modes?.[0];
            const freightPerUnit = mode?.cost_per_unit ?? 1.5;
            const trC = Math.round((freightPerUnit * qty + (mode?.cost_per_shipment ?? 0)) * 100) / 100;
            costs.transport = trC;
            orderTotalCost = trC;
            orderUnitCost = freightPerUnit;
            transportCost += trC;

            // Push dependent demand to origin location
            const depBucket = bucketIndexFor(startDate, start, buckets);
            const origKey = `${ln.origin}|${prodId}`;
            ensureArr(depDemand, origKey)[depBucket] += qty;
            reqs.push({
              id: `REQ-${String(reqSeq++).padStart(4, "0")}`,
              kind: "transfer",
              location: ln.origin,
              product: prodId,
              date: startDate,
              qty,
              parent_order: orderId,
              priority: 100,
              consumed_forecast: 0,
              past_due: startDate < start,
            });
          }

          orders.push({
            id: orderId,
            kind: primaryKind,
            location: locId,
            product: prodId,
            qty,
            source_id: sourceId,
            origin,
            need_date: needDate,
            start_date: startDate,
            due_date: dueDate,
            available_date: dueDate,
            start_in_past: startInPast,
            wanted_start: startInPast ? wantedStart : null,
            fence_shifted: false,
            convertible: true,
            sales_order: null,
            unit_cost: Math.round(orderUnitCost * 100) / 100,
            total_cost: Math.round(orderTotalCost * 100) / 100,
            costs,
            shipments: primaryKind === "transfer" ? 1 : null,
            delay_days: delayDays,
            projected_available_date: delayDays > 0 ? dueDate : null,
            projected_on_time_qty: delayDays > 0 ? 0 : qty,
            limited_by: null,
            limited_at: null,
            limited_until: null,
            lot_excess: Math.max(0, qty - netReq),
            for_buffer: Math.min(qty, Math.max(0, ssQty - Math.max(0, projectedBefore))),
            for_lot_size: Math.max(0, qty - netReq),
            capacity_shift_days: 0,
            step_resources: {},
            overtime_hours: {},
            open_later: [],
          });
          orderIds.push(orderId);
          plannedQty = qty;

          if (startInPast) {
            atRisk = Math.min(grossInd, qty);
            lateDemandQty += atRisk;
            exceptions.push({
              code: "START_IN_PAST",
              severity: "warning",
              location: locId,
              product: prodId,
              resource: null,
              order_id: orderId,
              message: `${orderId} for ${prodId} at ${locId} needs to start on ${wantedStart}, before planning start.`,
              date: needDate,
              qty,
            });
            if (atRisk > 0) {
              exceptions.push({
                code: "DEMAND_AT_RISK",
                severity: "error",
                location: locId,
                product: prodId,
                resource: null,
                order_id: orderId,
                message: `${atRisk} units of ${prodId} at ${locId} due ${needDate} arrive late (${dueDate}).`,
                date: needDate,
                qty: atRisk,
              });
            }
          }
        } else if (projectedBefore < 0) {
          shortage = Math.abs(projectedBefore);
          atRisk = Math.min(grossInd, shortage);
          lateDemandQty += atRisk;
          exceptions.push({
            code: "SHORTAGE",
            severity: "error",
            location: locId,
            product: prodId,
            resource: null,
            order_id: null,
            message: `Shortage of ${Math.round(shortage)} units for ${prodId} at ${locId} in ${buckets[bi].label} (no supply source).`,
            date: buckets[bi].start,
            qty: shortage,
          });
        }
      }

      onHand = Math.max(0, projectedBefore + plannedQty);
      const belowSafety = Math.max(0, ssQty - onHand);
      const bucketDays = Math.max(1, diffDays(buckets[bi].start, buckets[bi].end) + 1);
      const bHold = Math.round(onHand * unitVal * rate * (bucketDays / 365) * 100) / 100;
      holdingCost += bHold;
      invValSum += onHand * unitVal;

      nodeBuckets.push({
        bucket: bi,
        gross_independent: grossInd,
        gross_dependent: grossDep,
        expiring: 0,
        scheduled_receipts: sched,
        planned_receipts: plannedQty,
        projected_on_hand: onHand,
        safety_stock: ssQty,
        target_stock: ssQty,
        below_safety: belowSafety,
        shortage,
        holding_cost: bHold,
        at_risk: atRisk,
      });
    }

    invValEnd += onHand * unitVal;

    nodePlans.push({
      location: locId,
      product: prodId,
      llc: rankNode(locId, prodId),
      strategy: lp?.strategy ?? "MTS",
      mrp_type: lp?.mrp_type ?? "deterministic",
      lot_policy: lotPolicy,
      unit_value: unitVal,
      value_basis: valBasis,
      on_hand: startOnHand,
      safety_stock_method: ssMethod,
      safety_stock_note: "",
      lead_time_days: leadTimeDays,
      sources: [
        ...makeSrcs.map((s) => s.id),
        ...buySrcs.map((s) => s.id),
        ...laneSrcs.map((s) => s.id),
      ],
      buckets: nodeBuckets,
      order_ids: orderIds,
    });
  }

  // Resource capacity plans
  let maxUtil = 0;
  const resources: ResourcePlan[] = (ds.resources ?? []).map((r) => {
    const dailyObj: Record<string, number> = {};
    const dm = resDailyLoad.get(r.id);
    if (dm) {
      for (const [d, h] of dm) dailyObj[d] = Math.round(h * 100) / 100;
    }
    const hrsPerDay = resourceHoursPerDay(r);
    const rBuckets = buckets.map((b) => {
      const days = Math.max(1, Math.round((diffDays(b.start, b.end) + 1) * (5 / 7)));
      const avail = Math.round(hrsPerDay * days * 100) / 100;
      let req = 0;
      for (const [d, h] of Object.entries(dailyObj)) {
        if (d >= b.start && d <= b.end) req += h;
      }
      const util = avail > 0 ? req / avail : 0;
      if (util > maxUtil) maxUtil = util;
      if (util > 1.0) {
        exceptions.push({
          code: "CAPACITY_OVERLOAD",
          severity: "warning",
          location: r.location,
          product: null,
          resource: r.id,
          order_id: null,
          message: `Resource ${r.name || r.id} is at ${Math.round(util * 100)}% load in ${b.label}.`,
          date: b.start,
          qty: Math.round((req - avail) * 10) / 10,
        });
      }
      return {
        bucket: b.index,
        load_hours: Math.round(req * 100) / 100,
        capacity_hours: avail,
        overtime_hours: Math.max(0, Math.round((req - avail) * 100) / 100),
        utilization: Math.round(util * 1000) / 1000,
      };
    });
    return {
      resource: r.id,
      location: r.location,
      kind: r.kind ?? "machine",
      finite: r.finite ?? true,
      buckets: rBuckets,
      daily_load: dailyObj,
      orders: resOrders.get(r.id) ?? [],
    };
  });

  const totalCost = Math.round((purchaseCost + productionCost + setupCost + orderingCost + transportCost + handlingCost + holdingCost) * 100) / 100;
  const invValAvg = buckets.length > 0 ? Math.round((invValSum / buckets.length) * 100) / 100 : invValStart;
  const onTimeQty = Math.max(0, totalIndependent - lateDemandQty);
  const fillRate = totalIndependent > 0 ? onTimeQty / totalIndependent : 1;

  const firmingSha = crypto
    .createHash("sha256")
    .update(JSON.stringify(orders.map((o) => [o.id, o.qty, o.start_date, o.due_date])))
    .digest("hex")
    .slice(0, 16);

  const plan: PlanResult = {
    ok: true,
    currency,
    carrying_rate: rate,
    buckets,
    nodes: nodePlans,
    orders,
    requirements: [],
    receipts: receiptsOut,
    pegs: [],
    resources,
    exceptions,
    kpis: {
      purchase_cost: Math.round(purchaseCost * 100) / 100,
      production_cost: Math.round(productionCost * 100) / 100,
      setup_cost: Math.round(setupCost * 100) / 100,
      ordering_cost: Math.round(orderingCost * 100) / 100,
      transport_cost: Math.round(transportCost * 100) / 100,
      handling_cost: Math.round(handlingCost * 100) / 100,
      holding_cost: Math.round(holdingCost * 100) / 100,
      total_cost: totalCost,
      inventory_value_start: Math.round(invValStart * 100) / 100,
      inventory_value_end: Math.round(invValEnd * 100) / 100,
      inventory_value_avg: invValAvg,
      orders_make: orders.filter((o) => o.kind === "make").length,
      orders_buy: orders.filter((o) => o.kind === "buy").length,
      orders_transfer: orders.filter((o) => o.kind === "transfer").length,
      independent_demand: totalIndependent,
      on_time_qty: onTimeQty,
      on_time_fill_rate: Math.round(fillRate * 10000) / 10000,
      max_utilization: Math.round(maxUtil * 1000) / 1000,
    },
    issues: val.issues,
    planned_again: null,
    firming_sha256: firmingSha,
  };

  return { plan, requirements: reqs, pegs };
}

export function runPlan(ds: Dataset, includePegging = false): PlanResult {
  const b = computePlanBundle(ds);
  if (includePegging) {
    return { ...b.plan, requirements: b.requirements, pegs: b.pegs };
  }
  return b.plan;
}

export function runPlanTrace(ds: Dataset, what: { order?: string; location?: string; product?: string }): PlanTrace {
  const b = computePlanBundle(ds);
  const requirements = b.requirements.filter((r) => {
    if (what.order) return r.parent_order === what.order || r.id === what.order;
    if (what.location && what.product) return r.location === what.location && r.product === what.product;
    return true;
  });
  return { requirements, pegs: b.pegs };
}

export function runLevelPreview(ds: Dataset): LevelPreview {
  const plan = runPlan(ds);
  return {
    ok: plan.ok,
    active: ds.settings?.capacity_constrained ?? false,
    moves: [],
    resources: plan.resources.map((r) => {
      const req = r.buckets.reduce((s, b) => s + b.load_hours, 0);
      const maxU = Math.max(0, ...r.buckets.map((b) => b.utilization));
      const overloadedDays = r.buckets.filter((b) => b.utilization > 1).length;
      return {
        resource: r.resource,
        finite: r.finite,
        peak_before: maxU,
        peak_after: maxU,
        overloaded_days_before: overloadedDays,
        overloaded_days_after: overloadedDays,
        hours: Math.round(req * 100) / 100,
      };
    }),
    late_before: plan.kpis.independent_demand - plan.kpis.on_time_qty,
    late_after: plan.kpis.independent_demand - plan.kpis.on_time_qty,
    fill_before: plan.kpis.on_time_fill_rate,
    fill_after: plan.kpis.on_time_fill_rate,
    issues: plan.issues,
  };
}
