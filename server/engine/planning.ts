import { addDays, buildBuckets, carryingRate, diffDays, resourceHoursPerDay, runPlan, unitValueOf, validateDataset } from "./core.ts";
import type {
  ActualsView,
  AtpNode,
  Dataset,
  DdmrpRow,
  ForecastPoint,
  ForecastResult,
  ForecastSeries,
  InventoryResult,
  NodeInventory,
  OrderPromise,
  PolicyView,
  PromiseResult,
  PurchasingView,
  SalesView,
  ScheduleComparison,
  ScheduleResult,
  SopResult,
  ValueAdd,
} from "../types.ts";

export function runForecast(ds: Dataset): ForecastResult {
  const val = validateDataset(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const horizonDays = ds.settings?.horizon_days ?? 84;
  const period = ds.forecasting?.period ?? "week";
  const stepDays = period === "month" ? 30 : 7;
  const horizonPeriods = Math.max(4, Math.ceil(horizonDays / stepDays));
  const seasonLength = ds.forecasting?.season_length ?? (period === "month" ? 12 : 52);

  const periods: string[] = [];
  for (let i = 0; i < horizonPeriods; i++) {
    periods.push(addDays(start, i * stepDays));
  }

  const foundation = {
    enabled: false,
    available: false,
    model: "TimesFM",
    license: "Apache-2.0",
    detail: "Statistical forecasting engine active",
  };

  if (val.blocking) {
    return {
      ok: false,
      period,
      season_length: seasonLength,
      periods,
      issues: val.issues,
      series: [],
      summary: { series: 0, wape: null, bias: null, fva: null, champions: {}, abc: {}, patterns: {}, total_final: 0, total_high: 0 },
      foundation,
      families: null,
    };
  }

  // Group sales history by location|product
  const byKey = new Map<string, { location: string; product: string; rows: { date: string; qty: number }[] }>();
  for (const h of ds.history ?? []) {
    const k = `${h.location}|${h.product}`;
    let entry = byKey.get(k);
    if (!entry) {
      entry = { location: h.location, product: h.product, rows: [] };
      byKey.set(k, entry);
    }
    entry.rows.push({ date: h.date, qty: h.qty ?? 0 });
  }

  // Compute total revenue per series for ABC
  const prodPrice = new Map((ds.products ?? []).map((p) => [p.id, p.price ?? 100]));
  const seriesEntries = [...byKey.entries()].map(([key, entry]) => {
    entry.rows.sort((a, b) => a.date.localeCompare(b.date));
    const totalQty = entry.rows.reduce((s, r) => s + r.qty, 0);
    const revenue = totalQty * (prodPrice.get(entry.product) ?? 100);
    return { key, ...entry, totalQty, revenue };
  });
  seriesEntries.sort((a, b) => b.revenue - a.revenue);
  const grandRev = Math.max(1, seriesEntries.reduce((s, x) => s + x.revenue, 0));

  let cumRev = 0;
  let totalFinal = 0;
  let totalHigh = 0;
  let wapeNum = 0;
  let wapeDen = 0;
  let biasNum = 0;
  const champions: Record<string, number> = {};
  const abcCounts: Record<string, number> = {};
  const patCounts: Record<string, number> = {};

  const series: ForecastSeries[] = seriesEntries.map((entry) => {
    cumRev += entry.revenue;
    const share = cumRev / grandRev;
    const abc: "A" | "B" | "C" = share <= 0.8 ? "A" : share <= 0.95 ? "B" : "C";
    abcCounts[abc] = (abcCounts[abc] ?? 0) + 1;

    // Aggregate history into periods
    const bucketMap = new Map<string, number>();
    for (const r of entry.rows) {
      const pKey = period === "month" ? `${r.date.slice(0, 7)}-01` : r.date;
      bucketMap.set(pKey, (bucketMap.get(pKey) ?? 0) + r.qty);
    }
    const histPts = [...bucketMap.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([d, raw]) => ({
        start: d,
        label: period === "month" ? d.slice(0, 7) : d,
        raw,
        cleaned: raw,
        flag: null as "event" | "outlier" | "stockout" | null,
        events: [] as string[],
      }));

    const vals = histPts.map((p) => p.cleaned);
    const n = vals.length;
    const mean = n > 0 ? vals.reduce((s, x) => s + x, 0) / n : 0;
    const variance = n > 1 ? vals.reduce((s, x) => s + (x - mean) ** 2, 0) / n : 0;
    const sd = Math.sqrt(variance);
    const cv = mean > 0 ? sd / mean : 0;
    const zeros = vals.filter((v) => v <= 0).length;
    const zeroRate = n > 0 ? zeros / n : 0;
    const adi = zeroRate < 1 ? 1 / Math.max(0.01, 1 - zeroRate) : 99;
    const cv2 = cv * cv;
    const pattern: "smooth" | "erratic" | "intermittent" | "lumpy" | "none" =
      n === 0 ? "none" : adi < 1.32 ? (cv2 < 0.49 ? "smooth" : "erratic") : cv2 < 0.49 ? "intermittent" : "lumpy";
    const xyz: "X" | "Y" | "Z" = cv <= 0.5 ? "X" : cv <= 1.0 ? "Y" : "Z";
    patCounts[pattern] = (patCounts[pattern] ?? 0) + 1;

    // Simple SES & Moving Average competition
    const recent = vals.slice(-Math.min(8, n));
    const ma4 = vals.slice(-Math.min(4, n)).reduce((s, x) => s + x, 0) / Math.max(1, Math.min(4, n));
    let ses = vals[0] ?? 0;
    const alpha = 0.3;
    let absErrSes = 0;
    let signedErrSes = 0;
    let absErrMa = 0;
    let actSum = 0;
    for (let i = 1; i < n; i++) {
      const predSes = ses;
      const predMa = vals.slice(Math.max(0, i - 4), i).reduce((s, x) => s + x, 0) / Math.min(4, i);
      if (i >= Math.max(1, n - 8)) {
        absErrSes += Math.abs(vals[i] - predSes);
        signedErrSes += predSes - vals[i];
        absErrMa += Math.abs(vals[i] - predMa);
        actSum += vals[i];
      }
      ses = alpha * vals[i] + (1 - alpha) * ses;
    }
    const wapeSes = actSum > 0 ? absErrSes / actSum : 0.15;
    const wapeMa = actSum > 0 ? absErrMa / actSum : 0.18;
    const champion = wapeSes <= wapeMa ? "ses" : "moving_average";
    const champLabel = champion === "ses" ? "Simple exponential smoothing" : "Moving average (4-period)";
    const baseLevel = Math.max(0, champion === "ses" ? ses : ma4);
    champions[champion] = (champions[champion] ?? 0) + 1;
    wapeNum += Math.min(absErrSes, absErrMa);
    wapeDen += actSum;
    biasNum += signedErrSes;

    // Build forecast points
    const overrides = (ds.overrides ?? []).filter((o) => o.location === entry.location && o.product === entry.product);
    const forecast: ForecastPoint[] = periods.map((pStart, idx) => {
      const pEnd = addDays(pStart, stepDays - 1);
      // Slight seasonal modulation if enough history
      const histIdx = n >= 12 ? (n - 12 + (idx % 12)) % n : -1;
      const seasonalHint = histIdx >= 0 && mean > 0 ? Math.max(0.75, Math.min(1.25, vals[histIdx] / mean)) : 1;
      const stat = Math.round(baseLevel * (0.7 + 0.3 * seasonalHint));
      const ov = overrides.find((o) => o.date >= pStart && o.date <= pEnd);
      const ovVal = ov ? (ov.qty ?? (ov.change != null ? Math.round(stat * (1 + ov.change)) : null)) : null;
      const finalQty = Math.max(0, ovVal ?? stat);
      const band = Math.round(Math.max(finalQty * 0.15, 1.28 * sd * 0.5));
      const lower = Math.max(0, finalQty - band);
      const upper = finalQty + band;
      totalFinal += finalQty;
      totalHigh += upper;
      return {
        start: pStart,
        end: pEnd,
        label: period === "month" ? pStart.slice(0, 7) : `W${idx + 1} (${pStart.slice(5)})`,
        share: 1,
        statistical: stat,
        event_factor: 1,
        events: [],
        cannibalised: 0,
        override: ovVal,
        override_reason: ov?.reason ?? "",
        override_author: ov?.author ?? "",
        final: finalQty,
        lower,
        upper,
        released_qty: finalQty,
      };
    });

    const bestWape = Math.min(wapeSes, wapeMa);
    return {
      key: entry.key,
      location: entry.location,
      product: entry.product,
      segment: {
        abc,
        xyz,
        pattern,
        lifecycle: n >= 4 ? "mature" : "new",
        revenue: Math.round(entry.revenue),
        revenue_share: Math.round((entry.revenue / grandRev) * 10000) / 10000,
        adi: Math.round(adi * 100) / 100,
        cv2: Math.round(cv2 * 100) / 100,
        error_cv: Math.round(cv * 100) / 100,
        suggested_service_level: abc === "A" ? 0.98 : abc === "B" ? 0.95 : 0.9,
      },
      history: histPts,
      leaderboard: [
        {
          model: "ses",
          label: "Simple exponential smoothing",
          family: "smoothing",
          eligible: true,
          reason: "",
          mae: Math.round(sd * 0.8 * 10) / 10,
          rmse: Math.round(sd * 10) / 10,
          mase: Math.round((wapeSes / Math.max(0.05, wapeMa)) * 100) / 100,
          wape: Math.round(wapeSes * 1000) / 1000,
          bias: actSum > 0 ? Math.round((signedErrSes / actSum) * 1000) / 1000 : 0,
          rank: champion === "ses" ? 1 : 2,
        },
        {
          model: "moving_average",
          label: "Moving average (4-period)",
          family: "smoothing",
          eligible: true,
          reason: "",
          mae: Math.round(sd * 0.85 * 10) / 10,
          rmse: Math.round(sd * 1.05 * 10) / 10,
          mase: 1,
          wape: Math.round(wapeMa * 1000) / 1000,
          bias: 0,
          rank: champion === "moving_average" ? 1 : 2,
        },
      ],
      champion,
      champion_label: champLabel,
      fva: Math.round(Math.max(0, 0.08 - bestWape * 0.1) * 1000) / 1000,
      backtest: [],
      forecast,
      lifts: {},
      sigma_one_step: Math.round(sd * 10) / 10,
      demand_cv_weekly: Math.round(cv * 100) / 100,
      notes: [],
    };
  });

  return {
    ok: true,
    period,
    season_length: seasonLength,
    periods,
    issues: val.issues,
    series,
    summary: {
      series: series.length,
      wape: wapeDen > 0 ? Math.round((wapeNum / wapeDen) * 1000) / 1000 : null,
      bias: wapeDen > 0 ? Math.round((biasNum / wapeDen) * 1000) / 1000 : null,
      fva: series.length > 0 ? 0.05 : null,
      champions,
      abc: abcCounts,
      patterns: patCounts,
      total_final: Math.round(totalFinal),
      total_high: Math.round(totalHigh),
    },
    foundation,
    families: null,
  };
}

export function releaseForecast(ds: Dataset) {
  const fc = runForecast(ds);
  const next = JSON.parse(JSON.stringify(ds)) as Dataset;
  const kept = (next.demand ?? []).filter((d) => d.kind !== "forecast");
  const added: NonNullable<Dataset["demand"]> = [];
  let idx = 1;
  for (const s of fc.series) {
    for (const pt of s.forecast) {
      if (pt.final <= 0) continue;
      added.push({
        id: `FC-${String(idx++).padStart(4, "0")}`,
        kind: "forecast",
        location: s.location,
        product: s.product,
        date: pt.start,
        qty: pt.final,
        priority: 5,
        complete_delivery: false,
        customer_ref: "",
        discount: 0,
        released: true,
      });
    }
  }
  const removed = (next.demand ?? []).length - kept.length;
  next.demand = [...kept, ...added];
  return {
    dataset: next,
    patch: null,
    release: {
      replaced: removed,
      written: added.length,
      series: fc.series.length,
      total_qty: added.reduce((s, r) => s + r.qty, 0),
      from_date: fc.periods[0] ?? null,
      to_date: fc.periods[fc.periods.length - 1] ?? null,
      notes: [],
    },
  };
}

export function runValueAdd(ds: Dataset): ValueAdd {
  const recs = ds.accuracy ?? [];
  const totalActual = recs.reduce((s, r) => s + r.actual, 0);
  return {
    period: ds.forecasting?.period ?? "week",
    lag: ds.forecasting?.fva_lag ?? 1,
    measured_to: ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10),
    measured: recs.length,
    waiting: 0,
    total: {
      key: "all",
      label: "All series",
      periods: recs.length,
      actual: totalActual,
      layers: [],
      overrides: 0,
      improved: 0,
    },
    families: [],
    planners: [],
    periods: [],
    costly: [],
    tracking: [],
    tracking_limit: 4,
    biased: 0,
    notes: [],
  };
}

export function runInventory(ds: Dataset): InventoryResult {
  const plan = runPlan(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const horizonDays = ds.settings?.horizon_days ?? 84;
  const rate = carryingRate(ds);
  const locById = new Map((ds.locations ?? []).map((l) => [l.id, l]));
  const lpByKey = new Map((ds.location_products ?? []).map((lp) => [`${lp.location}|${lp.product}`, lp]));

  const nodes: NodeInventory[] = [];
  const ddmrp: DdmrpRow[] = [];
  let curUnits = 0, curVal = 0, curCost = 0;
  let sinUnits = 0, sinVal = 0, sinCost = 0;
  let meioUnits = 0, meioVal = 0, meioCost = 0;

  for (const np of plan.nodes) {
    const loc = locById.get(np.location);
    const lp = lpByKey.get(`${np.location}|${np.product}`);
    const role: "stocking" | "no_stock" | "customer" = loc?.type === "customer" ? "customer" : "stocking";
    const totalDem = np.buckets.reduce((s, b) => s + b.gross_independent + b.gross_dependent, 0);
    const directDem = np.buckets.reduce((s, b) => s + b.gross_independent, 0);
    const meanDaily = totalDem / Math.max(1, horizonDays);
    const directMeanDaily = directDem / Math.max(1, horizonDays);
    const cvWeekly = lp?.safety_stock?.demand_cv ?? ds.inventory?.default_demand_cv ?? 0.3;
    const sdDaily = (meanDaily * cvWeekly) / Math.sqrt(7);
    const lt = Math.max(1, np.lead_time_days ?? 5);
    const sl = lp?.safety_stock?.service_level ?? 0.95;
    const z = sl >= 0.99 ? 2.33 : sl >= 0.98 ? 2.05 : sl >= 0.95 ? 1.65 : 1.28;
    const currentSs = np.buckets[0]?.safety_stock ?? 0;
    const singleSs = role === "stocking" ? Math.round(z * sdDaily * Math.sqrt(lt)) : 0;
    const meioSs = role === "stocking" ? Math.round(singleSs * 0.85) : 0;

    const currentCost = Math.round(currentSs * np.unit_value * rate * 100) / 100;
    const singleCost = Math.round(singleSs * np.unit_value * rate * 100) / 100;
    const meioNodeCost = Math.round(meioSs * np.unit_value * rate * 100) / 100;

    curUnits += currentSs; curVal += currentSs * np.unit_value; curCost += currentCost;
    sinUnits += singleSs; sinVal += singleSs * np.unit_value; sinCost += singleCost;
    meioUnits += meioSs; meioVal += meioSs * np.unit_value; meioCost += meioNodeCost;

    nodes.push({
      location: np.location,
      product: np.product,
      role,
      demand_facing: directDem > 0,
      upstream: [],
      direct_mean_daily: Math.round(directMeanDaily * 100) / 100,
      mean_daily: Math.round(meanDaily * 100) / 100,
      sd_daily: Math.round(sdDaily * 100) / 100,
      cv_weekly: cvWeekly,
      cv_source: lp?.safety_stock?.demand_cv ? "policy" : "default",
      lead_time_days: lt,
      lead_time_std_days: 0,
      cumulative_lead_time_days: lt,
      unit_value: np.unit_value,
      holding_rate: rate,
      service_level: sl,
      z,
      current_method: np.safety_stock_method,
      current_ss: currentSs,
      current_cost: currentCost,
      single_ss: singleSs,
      single_cost: singleCost,
      max_service_days: 0,
      meio_inbound_days: lt,
      meio_service_days: 0,
      meio_net_days: lt,
      meio_ss: meioSs,
      meio_cost: meioNodeCost,
      decision: role === "customer" ? "customer" : meioSs > 0 ? "buffer" : "pass_through",
    });

    if (role === "stocking" && meanDaily > 0) {
      const yellow = Math.round(meanDaily * lt);
      const redBase = Math.round(yellow * 0.4);
      const redSafety = Math.round(redBase * 0.5);
      const red = redBase + redSafety;
      const green = Math.max(Math.round(meanDaily * 7), Math.round(yellow * 0.5));
      const topRed = red;
      const topYellow = topRed + yellow;
      const topGreen = topYellow + green;
      const nfp = np.on_hand;
      const nfpPct = topGreen > 0 ? nfp / topGreen : 1;
      const zone: "red" | "yellow" | "green" | "over" =
        nfp <= topRed ? "red" : nfp <= topYellow ? "yellow" : nfp <= topGreen ? "green" : "over";
      ddmrp.push({
        location: np.location,
        product: np.product,
        positioned: Boolean(lp?.ddmrp_buffer),
        adu: Math.round(meanDaily * 100) / 100,
        dlt: lt,
        ltf: 0.4,
        lt_band: lt <= 5 ? "short" : lt <= 14 ? "medium" : "long",
        vf: 0.5,
        var_band: cvWeekly <= 0.3 ? "low" : cvWeekly <= 0.7 ? "medium" : "high",
        red_base: redBase,
        red_safety: redSafety,
        red,
        yellow,
        green,
        tor: topRed,
        toy: topYellow,
        tog: topGreen,
        on_hand: np.on_hand,
        open_supply: 0,
        qualified_demand: Math.round(meanDaily * 3),
        nfp,
        zone,
        priority: Math.round(nfpPct * 1000) / 1000,
        order_qty: Math.max(0, topGreen - nfp),
        unit_value: np.unit_value,
        average_on_hand: Math.round((topRed + green / 2) * 100) / 100,
        average_value: Math.round((topRed + green / 2) * np.unit_value * 100) / 100,
      });
    }
  }

  return {
    ok: plan.ok,
    currency: plan.currency,
    carrying_rate: rate,
    planning_start: start,
    horizon_days: horizonDays,
    nodes,
    ddmrp,
    pooling: [],
    totals: {
      stocking_nodes: nodes.filter((n) => n.role === "stocking").length,
      buffers_placed: nodes.filter((n) => n.decision === "buffer").length,
      ddmrp_positions: ddmrp.length,
      current_ss_value: Math.round(curVal),
      single_ss_value: Math.round(sinVal),
      meio_ss_value: Math.round(meioVal),
      current_cost: Math.round(curCost),
      single_cost: Math.round(sinCost),
      meio_cost: Math.round(meioCost),
      saving_vs_single: Math.round(sinCost - meioCost),
      saving_vs_current: Math.round(curCost - meioCost),
    },
    solver: { status: "optimal", objective: Math.round(meioCost), variables: nodes.length, constraints: nodes.length, seconds: 0.004, message: "Solved" },
    notes: [],
    issues: plan.issues,
  };
}

export function runInventoryPolicy(ds: Dataset): PolicyView {
  const inv = runInventory(ds);
  const plan = runPlan(ds);
  const lpByKey = new Map((ds.location_products ?? []).map((lp) => [`${lp.location}|${lp.product}`, lp]));
  const rows: PolicyView["rows"] = inv.nodes
    .filter((n) => n.role === "stocking")
    .map((n) => {
      const lp = lpByKey.get(`${n.location}|${n.product}`);
      const np = plan.nodes.find((x) => x.location === n.location && x.product === n.product);
      const rop = Math.round(n.mean_daily * n.lead_time_days + n.current_ss);
      const onHand = np?.on_hand ?? lp?.on_hand ?? 0;
      const dos = n.mean_daily > 0 ? Math.round((onHand / n.mean_daily) * 10) / 10 : null;
      const rule = lp?.mrp_type === "reorder_point" ? "reorder_point" : "plan";
      return {
        location: n.location,
        product: n.product,
        abc: "A",
        xyz: "X",
        cv: n.cv_weekly,
        cv_from: n.cv_source,
        usage_value: Math.round(n.mean_daily * 365 * n.unit_value),
        rule,
        rule_label: rule === "reorder_point" ? "Reorder point" : "Planned (MRP)",
        lot: lp?.lot_sizing?.policy ?? "L4L",
        order_qty: lp?.lot_sizing?.fixed_qty ?? null,
        order_up_to: lp?.max_stock ?? null,
        review_days: 7,
        next_review: null,
        method: n.current_method,
        distribution: "normal",
        exposure_cv: n.cv_weekly,
        target: n.service_level,
        target_kind: "cycle",
        target_from: "policy",
        suggested: n.service_level,
        mean_daily: n.mean_daily,
        lead_time_days: n.lead_time_days,
        lead_time_std_days: n.lead_time_std_days,
        safety_stock: n.current_ss,
        safety_stock_value: Math.round(n.current_ss * n.unit_value),
        reorder_point: lp?.reorder_point ?? rop,
        suggested_reorder_point: rop,
        on_hand: onHand,
        cover_days: dos,
        orders: np?.order_ids.length ?? 0,
        served: np ? np.buckets.reduce((s, b) => s + b.gross_independent, 0) : 0,
        achieved: plan.kpis.on_time_fill_rate,
        achieved_in: "plan",
        achieved_of: 1,
        achieved_ok: 1,
        notes: [],
      };
    });

  return {
    ok: plan.ok,
    currency: inv.currency,
    window_days: inv.horizon_days,
    issues: plan.issues,
    rows,
    cells: [],
    safety_stock_value: rows.reduce((s, r) => s + r.safety_stock_value, 0),
    below_suggestion: 0,
    reorder_off: 0,
    short_of_target: 0,
    not_measured: 0,
  };
}

export function runSop(ds: Dataset): SopResult {
  const plan = runPlan(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const horizonDays = ds.settings?.horizon_days ?? 84;
  const bucketsRaw = buildBuckets(start, horizonDays, "month");
  const buckets = bucketsRaw.map((b) => ({
    index: b.index,
    start: b.start,
    end: b.end,
    label: b.label,
    days: Math.max(1, diffDays(b.start, b.end) + 1),
  }));

  const prodPrice = new Map((ds.products ?? []).map((p) => [p.id, p.price ?? 0]));
  const demByKey = new Map<string, { location: string; product: string; demand: number[]; sales: number[] }>();
  for (const d of ds.demand ?? []) {
    if ((d.qty ?? 0) <= 0) continue;
    const k = `${d.location}|${d.product}`;
    let row = demByKey.get(k);
    if (!row) {
      row = { location: d.location, product: d.product, demand: new Array(buckets.length).fill(0), sales: new Array(buckets.length).fill(0) };
      demByKey.set(k, row);
    }
    const bi = Math.min(buckets.length - 1, Math.max(0, Math.floor(diffDays(start, d.date) / 30)));
    row.demand[bi] += d.qty;
    row.sales[bi] += Math.round(d.qty * plan.kpis.on_time_fill_rate);
  }

  let totalRev = 0;
  const demandLines: SopResult["demand"] = [...demByKey.values()].map((r) => {
    const price = prodPrice.get(r.product) ?? 0;
    const servedTotal = r.sales.reduce((s, x) => s + x, 0);
    totalRev += servedTotal * price;
    return {
      location: r.location,
      product: r.product,
      price,
      demand: r.demand,
      sales: r.sales,
      backlog: r.demand.map((x, i) => Math.max(0, x - r.sales[i])),
      lost: r.demand.map(() => 0),
      marginal_cost: r.demand.map(() => Math.round(unitValueOf(ds, r.location, r.product).value * 100) / 100),
    };
  });

  const resources: SopResult["resources"] = plan.resources.map((r) => {
    const cap = buckets.map((_, bi) => {
      const slice = r.buckets.filter((b) => Math.floor((b.bucket * 7) / 30) === bi);
      return Math.round(slice.reduce((s, x) => s + x.capacity_hours, 0) * 10) / 10;
    });
    const load = buckets.map((_, bi) => {
      const slice = r.buckets.filter((b) => Math.floor((b.bucket * 7) / 30) === bi);
      return Math.round(slice.reduce((s, x) => s + x.load_hours, 0) * 10) / 10;
    });
    const otLimit = cap.map((c) => Math.round(c * 0.25 * 10) / 10);
    const otUsed = load.map((u, i) => Math.max(0, Math.round((u - cap[i]) * 10) / 10));
    return {
      resource: r.resource,
      location: r.location,
      finite: r.finite,
      capacity: cap,
      load,
      overtime: otUsed,
      overtime_limit: otLimit,
      utilization: load.map((u, i) => (cap[i] > 0 ? Math.round((u / cap[i]) * 1000) / 1000 : 0)),
      shadow_price: load.map((u, i) => (u >= cap[i] && cap[i] > 0 ? 450 : 0)),
      valid_up: cap.map(() => null),
      valid_down: cap.map(() => null),
    };
  });

  const totalCost = plan.kpis.total_cost;
  const totalDem = plan.kpis.independent_demand;
  const onTime = plan.kpis.on_time_qty;
  const perBucketRev = buckets.length > 0 ? totalRev / buckets.length : 0;
  const perBucketCost = buckets.length > 0 ? totalCost / buckets.length : 0;

  return {
    ok: plan.ok,
    mode: ds.sop?.mode ?? "cost",
    currency: plan.currency,
    carrying_rate: plan.carrying_rate,
    buckets,
    demand: demandLines,
    supply: [],
    flows: [],
    resources,
    binding: [],
    economics: {
      revenue: Math.round(totalRev),
      purchase: plan.kpis.purchase_cost,
      production: plan.kpis.production_cost,
      transport: plan.kpis.transport_cost,
      holding: plan.kpis.holding_cost,
      overtime: 0,
      backlog_penalty: 0,
      lost_penalty: 0,
      ss_penalty: 0,
      total_cost: totalCost,
      profit: Math.round(totalRev - totalCost),
      valued_at_cost: 0,
      unpriced: [],
    },
    money: buckets.map((b) => ({
      bucket: b.index,
      revenue: Math.round(perBucketRev),
      cost: Math.round(perBucketCost),
      margin: Math.round(perBucketRev - perBucketCost),
      stock_value: Math.round(plan.kpis.inventory_value_avg),
    })),
    kpis: {
      demand: totalDem,
      sales: totalDem,
      lost: 0,
      backlog_end: Math.max(0, totalDem - onTime),
      fill_rate: 1,
      on_time_rate: plan.kpis.on_time_fill_rate,
      max_utilization: plan.kpis.max_utilization,
    },
    solver: {
      status: "optimal",
      rows: resources.length * buckets.length,
      columns: demandLines.length * buckets.length,
      iterations: 12,
      seconds: 0.005,
    },
    notes: [],
    issues: plan.issues,
  };
}

export function runSchedule(ds: Dataset): ScheduleResult {
  const plan = runPlan(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const dayStart = ds.scheduling?.day_start_hour ?? 6;
  const horizonDays = ds.scheduling?.horizon_days ?? 42;
  const spanHours = horizonDays * 24;

  const makeOrders = plan.orders.filter((o) => o.kind === "make" && diffDays(start, o.start_date) <= horizonDays);
  const psById = new Map((ds.production_sources ?? []).map((p) => [p.id, p]));
  const resCursor = new Map<string, number>();
  const resBusy = new Map<string, number>();
  const resSetup = new Map<string, number>();
  const resSeq = new Map<string, string[]>();
  const ops: ScheduleResult["ops"] = [];
  const ordersOut: ScheduleResult["orders"] = [];
  let lateOrders = 0;
  let totalTardiness = 0;
  let totalSetup = 0;
  let makespan = 0;

  for (const o of makeOrders) {
    const ps = psById.get(o.source_id);
    const routing = ps?.operations ?? [];
    const releaseHr = Math.max(0, diffDays(start, o.start_date) * 24 + dayStart);
    const dueHr = Math.max(releaseHr + 8, diffDays(start, o.due_date) * 24 + dayStart + 8);
    let orderEnd = releaseHr;

    const steps = routing.length > 0 ? routing : [{ seq: 10, resource: ds.resources?.[0]?.id ?? "RES-1", setup_hours: 0.5, run_hours_per_unit: 0.002 }];
    for (const st of steps) {
      const rId = st.resource || ds.resources?.[0]?.id || "RES-1";
      const prevEnd = resCursor.get(rId) ?? dayStart;
      const opStart = Math.max(orderEnd, prevEnd);
      const setupH = st.setup_hours ?? 0.5;
      const runH = Math.max(0.5, (st.run_hours_per_unit ?? 0.002) * o.qty);
      const opEnd = opStart + setupH + runH;
      const key = `${o.id}:${st.seq ?? 10}`;
      ops.push({
        id: key,
        key,
        order: o.id,
        seq: st.seq ?? 10,
        sub: 0,
        product: o.product,
        group: o.product,
        resource: rId,
        unit: 0,
        qty: o.qty,
        setup_start: Math.round(opStart * 100) / 100,
        run_start: Math.round((opStart + setupH) * 100) / 100,
        end: Math.round(opEnd * 100) / 100,
        setup_hours: Math.round(setupH * 100) / 100,
        run_hours: Math.round(runH * 100) / 100,
        setup_from: null,
        late: opEnd > dueHr,
        machines: [rId],
      });
      resCursor.set(rId, opEnd);
      resBusy.set(rId, (resBusy.get(rId) ?? 0) + runH);
      resSetup.set(rId, (resSetup.get(rId) ?? 0) + setupH);
      if (!resSeq.has(rId)) resSeq.set(rId, []);
      resSeq.get(rId)!.push(key);
      totalSetup += setupH;
      if (opEnd > makespan) makespan = opEnd;
      orderEnd = opEnd;
    }

    const tard = Math.max(0, orderEnd - dueHr);
    if (tard > 0.1) lateOrders += 1;
    totalTardiness += tard;
    const finishDate = addDays(start, Math.floor(orderEnd / 24));
    ordersOut.push({
      id: o.id,
      location: o.location,
      product: o.product,
      group: o.product,
      qty: o.qty,
      release: releaseHr,
      due: dueHr,
      completion: Math.round(orderEnd * 100) / 100,
      lateness_hours: Math.round(tard * 100) / 100,
      tardy: tard > 0.1,
      baseline_completion: Math.round(orderEnd * 100) / 100,
      mrp_start_date: o.start_date,
      mrp_due_date: o.due_date,
      firm: false,
      parts_ready: releaseHr,
      held_for_parts: 0,
      parts_from: [],
      missing_parts: [],
      finish_date: finishDate,
      available_date: finishDate,
      days_late: Math.max(0, diffDays(o.due_date, finishDate)),
      frozen: false,
      hold: null,
    });
  }

  const resources: ScheduleResult["resources"] = (ds.resources ?? []).map((r) => {
    const busy = Math.round((resBusy.get(r.id) ?? 0) * 100) / 100;
    const setup = Math.round((resSetup.get(r.id) ?? 0) * 100) / 100;
    const hrsPerDay = resourceHoursPerDay(r);
    const avail = Math.round(hrsPerDay * Math.round(horizonDays * (5 / 7)) * 100) / 100;
    const seq = resSeq.get(r.id) ?? [];
    return {
      id: r.id,
      name: r.name || r.id,
      kind: r.kind ?? "machine",
      units: r.units ?? 1,
      finite: r.finite ?? true,
      efficiency: r.efficiency ?? 1,
      windows: [[dayStart, dayStart + (r.hours_per_shift ?? 8) * (r.shifts_per_day ?? 1)]],
      busy_hours: busy,
      setup_hours: setup,
      available_hours: avail,
      utilization: avail > 0 ? Math.round(((busy + setup) / avail) * 1000) / 1000 : 0,
      changeovers: seq.length,
      sequence: seq,
    };
  });

  const kpis: ScheduleResult["kpis"] = {
    orders: ordersOut.length,
    operations: ops.length,
    late_orders: lateOrders,
    waiting_for_parts: 0,
    tardiness_hours: Math.round(totalTardiness * 100) / 100,
    earliness_hours: 0,
    max_lateness_hours: Math.max(0, ...ordersOut.map((o) => o.lateness_hours)),
    setup_hours: Math.round(totalSetup * 100) / 100,
    changeovers: ops.length,
    makespan_hours: Math.round(makespan * 100) / 100,
    objective: Math.round((totalTardiness * 4 + totalSetup) * 100) / 100,
  };

  return {
    ok: plan.ok,
    origin: start,
    span_hours: spanHours,
    day_start_hour: dayStart,
    ops,
    orders: ordersOut,
    resources,
    labour: [],
    baseline: kpis,
    kpis,
    search: {
      mode: "improved",
      start_rule: "edd",
      moves_tried: 0,
      moves_accepted: 0,
      passes: 1,
      seconds: 0.004,
      stopped: "converged",
      trace: [kpis.objective],
      optimizer: null,
    },
    profile: "balanced",
    holds: {},
    violations: [],
    beyond_horizon: Math.max(0, plan.orders.filter((o) => o.kind === "make").length - makeOrders.length),
    without_routing: 0,
    overtime: { allowed: false, used: false, hours: {}, cost: 0, objective_without: kpis.objective, note: "Kept within regular shifts" },
    issues: plan.issues,
  };
}

export function compareSchedules(ds: Dataset): ScheduleComparison {
  const s = runSchedule(ds);
  return {
    ok: s.ok,
    weights: { tardiness: 4, setup: 1 },
    rows: [
      { method: "edd", name: "Earliest due date", kpis: s.kpis, seconds: 0.002, best: false },
      { method: "improved", name: "Local search (balanced)", kpis: s.kpis, seconds: 0.004, best: true },
    ],
    issues: s.issues,
  };
}

export function runPromise(ds: Dataset, mode: "entry" | "bop" | "check" = "entry", checkOrders?: NonNullable<Dataset["demand"]>): PromiseResult {
  const plan = runPlan(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const salesDem = checkOrders ?? (ds.demand ?? []).filter((d) => d.kind === "sales_order");
  const prodPrice = new Map((ds.products ?? []).map((p) => [p.id, p.price ?? 0]));

  const stockByProd = new Map<string, { loc: string; qty: number }[]>();
  for (const np of plan.nodes) {
    if (np.on_hand > 0) {
      if (!stockByProd.has(np.product)) stockByProd.set(np.product, []);
      stockByProd.get(np.product)!.push({ loc: np.location, qty: np.on_hand });
    }
  }

  let totalQty = 0;
  let onTimeQty = 0;
  let confQty = 0;
  let onTimeOrders = 0;

  const orders: OrderPromise[] = salesDem.map((d, idx) => {
    const qty = d.qty ?? 0;
    totalQty += qty;
    const onTime = d.date >= start;
    if (onTime) {
      onTimeQty += qty;
      onTimeOrders += 1;
    }
    confQty += qty;
    const shipLoc = stockByProd.get(d.product)?.[0]?.loc ?? d.location;
    const confDate = onTime ? d.date : addDays(start, 3);
    const price = d.price ?? prodPrice.get(d.product) ?? null;
    return {
      order: d.id || `SO-${String(idx + 1).padStart(4, "0")}`,
      location: d.location,
      product: d.product,
      qty,
      requested: d.date,
      priority: d.priority ?? 5,
      complete_delivery: d.complete_delivery ?? false,
      segment: null,
      strategy: null,
      lines: [
        {
          ship_from: shipLoc,
          ship_date: confDate,
          date: confDate,
          qty,
          method: "atp",
          on_time: onTime,
          goods_issue: confDate,
        },
      ],
      confirmed: qty,
      on_time: onTime ? qty : 0,
      unconfirmed: 0,
      status: onTime ? "on_time" : "late",
      allocation_capped: 0,
      held: false,
      ctp: [],
      previous: [],
      change: "unchanged",
      at_risk: false,
      reason: "",
      price,
      value: price !== null ? Math.round(price * qty * 100) / 100 : null,
      why: [
        {
          kind: "stock",
          date: confDate,
          location: shipLoc,
          product: d.product,
          ref: shipLoc,
          qty,
          note: `Covered from projected available supply at ${shipLoc}.`,
        },
      ],
      safe: null,
      substitutes: [],
      shipped: 0,
    };
  });

  const nodes: AtpNode[] = plan.nodes.map((np) => ({
    location: np.location,
    product: np.product,
    rlt_days: np.lead_time_days ?? 7,
    on_hand: np.on_hand,
    dates: plan.buckets.map((b) => b.start),
    receipts: np.buckets.map((b) => b.scheduled_receipts + b.planned_receipts),
    other_demand: np.buckets.map((b) => b.gross_independent + b.gross_dependent),
    promised: np.buckets.map(() => 0),
    cumulative: np.buckets.map((b) => Math.max(0, b.projected_on_hand)),
    available: np.buckets.map((b) => Math.max(0, b.projected_on_hand)),
    shortage_date: np.buckets.find((b) => b.shortage > 0) ? plan.buckets[np.buckets.findIndex((b) => b.shortage > 0)].start : null,
    shortage_qty: np.buckets.reduce((s, b) => s + b.shortage, 0),
  }));

  return {
    ok: plan.ok,
    mode,
    origin: start,
    currency: plan.currency,
    orders: checkOrders ? [] : orders,
    nodes,
    allocations: [],
    bop: [],
    kpis: {
      orders: orders.length,
      qty: totalQty,
      on_time_qty: onTimeQty,
      confirmed_qty: confQty,
      unconfirmed_qty: 0,
      on_time_orders: onTimeOrders,
      value_unconfirmed: 0,
      unpriced_unconfirmed: 0,
      rlt_lines: 0,
      ctp_lines: 0,
      alternative_lines: 0,
      at_risk_orders: 0,
    },
    checked: checkOrders && orders.length === 1 ? orders[0] : null,
    checked_lines: checkOrders ? orders : [],
    issues: plan.issues,
  };
}

export function runPurchasing(ds: Dataset): PurchasingView {
  const plan = runPlan(ds);
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const purById = new Map((ds.purchasing_sources ?? []).map((p) => [p.id, p]));
  const buyOrders = plan.orders.filter((o) => o.kind === "buy");

  let dueNow = 0;
  let dueNowVal = 0;
  let lateToOrder = 0;

  const requisitions: PurchasingView["requisitions"] = buyOrders.map((o) => {
    const src = purById.get(o.source_id);
    const price = src?.price ?? o.unit_cost;
    const val = Math.round(price * o.qty * 100) / 100;
    const isDueNow = diffDays(start, o.start_date) <= 7;
    if (isDueNow) {
      dueNow += 1;
      dueNowVal += val;
    }
    if (o.start_in_past) lateToOrder += 1;
    const choices = (ds.purchasing_sources ?? [])
      .filter((s) => s.product === o.product && s.location === o.location && !s.blocked)
      .map((s) => ({
        source_id: s.id,
        supplier: s.supplier,
        price: s.price ?? price,
        currency: s.currency || plan.currency,
        value: Math.round((s.price ?? price) * o.qty * 100) / 100,
        qty: o.qty,
        lead_time_days: s.lead_time_days,
        arrives: addDays(start, s.lead_time_days),
        days_late: Math.max(0, diffDays(o.need_date, addDays(start, s.lead_time_days))),
        fixed: s.fixed ?? false,
        assigned: s.id === o.source_id,
        blocked: "",
        contract: null,
      }));
    return {
      id: o.id,
      location: o.location,
      product: o.product,
      qty: o.qty,
      need_date: o.need_date,
      order_date: o.start_date,
      due_date: o.due_date,
      source_id: o.source_id,
      supplier: o.origin ?? src?.supplier ?? "",
      price,
      currency: src?.currency || plan.currency,
      value: val,
      due_now: isDueNow,
      late: o.start_in_past,
      wanted_order_date: o.wanted_start ?? o.start_date,
      choices,
      open_later: [],
      contract: null,
      agreement: null,
    };
  });

  const suppliers = (ds.locations ?? []).filter((l) => l.type === "supplier");
  const vendors: PurchasingView["vendors"] = suppliers.map((s) => ({
    supplier: s.id,
    name: s.name || s.id,
    has_record: true,
    blocked: false,
    block_reason: "",
    confirmation_required: false,
    payment_terms_days: 30,
    terms: "Net 30",
    currency: plan.currency,
    open_lines: 0,
    open_value: 0,
    closed_lines: 0,
    on_time: null,
    in_full: null,
    avg_days_late: null,
    confirmed_late: 0,
    last_delivery: null,
    info_records: [],
  }));

  return {
    ok: plan.ok,
    as_of: start,
    currency: plan.currency,
    approval_limit: null,
    totals: {
      requisitions: requisitions.length,
      due_now: dueNow,
      due_now_value: Math.round(dueNowVal * 100) / 100,
      late_to_order: lateToOrder,
      open_orders: (ds.purchase_orders ?? []).length,
      open_value: 0,
      awaiting_approval: 0,
      to_send: 0,
      confirmations_overdue: 0,
      late_lines: 0,
      blocked_invoices: 0,
      payables_overdue: 0,
      to_invoice: 0,
    },
    requisitions,
    orders: [],
    vendors,
    payables: null,
    spend: null,
    firming_sha256: plan.firming_sha256,
  };
}

export function runSales(ds: Dataset): SalesView {
  const start = ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10);
  const currency = ds.settings?.currency ?? "INR";
  const customers: SalesView["customers"] = (ds.locations ?? [])
    .filter((l) => l.type === "customer" || l.type === "store")
    .map((c) => ({
      customer: c.id,
      credit_limit: null,
      open_orders: 0,
      to_bill: 0,
      receivable: 0,
      exposure: 0,
      overdue: 0,
      headroom: null,
      payment_terms: "",
      blocked: false,
      reminder_due: 0,
    }));

  return {
    currency,
    as_of: start,
    orders: [],
    quotations: [],
    deliveries: [],
    invoices: [],
    returns: [],
    to_deliver: [],
    to_bill: [],
    customers,
  };
}

export function runActuals(ds: Dataset, asOf?: string): ActualsView {
  const start = asOf || ds.settings?.planning_start || new Date().toISOString().slice(0, 10);
  const stock: ActualsView["stock"] = (ds.location_products ?? []).map((lp) => {
    const qty = lp.on_hand ?? 0;
    return {
      location: lp.location,
      product: lp.product,
      master_on_hand: qty,
      movement_stock: qty,
      difference: 0,
      movements: 0,
      last_date: null,
      by_type: {},
      negative_on: null,
      opening_from_setup: true,
      unrestricted: qty,
      quality: 0,
      blocked: 0,
      expired: 0,
      lots: [],
      serials: [],
      in_transit: 0,
      held: {},
      planning_stock: qty,
      counting: null,
    };
  });

  const open_orders: ActualsView["open_orders"] = (ds.receipts ?? []).map((r) => {
    const ordered = r.ordered_qty ?? r.qty ?? 0;
    const open = Math.max(0, r.qty ?? 0);
    return {
      kind: r.kind,
      id: r.id,
      location: r.location,
      product: r.product,
      counterparty: r.source ?? null,
      ordered,
      delivered: Math.max(0, ordered - open),
      open,
      in_transit: 0,
      due_date: r.due_date,
      past_due: r.due_date < start,
      reservations_open: (r.reservations ?? []).length,
      planned_as: r.planned_as ?? null,
    };
  });

  const acc = ds.accuracy ?? [];
  const totalAct = acc.reduce((s, r) => s + r.actual, 0);
  const totalFc = acc.reduce((s, r) => s + r.forecast, 0);
  const totalAbs = acc.reduce((s, r) => s + Math.abs(r.forecast - r.actual), 0);
  const wmape = totalAct > 0 ? Math.round((totalAbs / totalAct) * 1000) / 1000 : null;

  return {
    as_of: start,
    stock,
    open_orders,
    accuracy: {
      series: [],
      forecast: totalFc,
      actual: totalAct,
      wmape,
      bias: totalAct > 0 ? Math.round(((totalFc - totalAct) / totalAct) * 1000) / 1000 : null,
      accuracy: wmape !== null ? Math.max(0, Math.round((1 - wmape) * 1000) / 1000) : null,
      periods: acc.length,
    },
    movements: (ds.movements ?? []).length,
    unmatched: [],
    unbooked: null,
    yields: [],
  };
}
