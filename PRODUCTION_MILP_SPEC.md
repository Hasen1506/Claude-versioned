# Production MILP Specification (R15 · Phase 3 · D1)

Verbal model for the three solvers under `/workspaces/Claude-versioned/`.
Owners read this BEFORE editing solver math, BEFORE writing solver tests,
and BEFORE answering "why didn't the LP do X." Each section has the same
shape: objective, decision vars, constraints, key inputs, key outputs, and
an **explicit "does NOT model" list** to set expectations.

---

## 1. profitmix.py — Profit-Maximizer LP

**Type:** `pulp.LpProblem(LpMaximize)`. Pure LP — all decision vars
continuous. Solved by CBC.

### Objective
Maximize total profit minus excess-holding penalty minus labor cost
(mode-dependent) minus fixed cost.

```
max  Σ_k margin_k · q_k
     − Σ_k holding_penalty_k · excess_k
     − Σ_k expiry_cost_k · expired_k                (when shelf < 12 mo)
     − Σ_l Σ_k rate_l · cycle_hrs(k,l) · x[k,l]     (only if labor_cost_mode='hourly')
     − salaried_monthly_cost · horizon_months         (only if labor_cost_mode='salaried_idle')
     − fixed_total                                  (per-SKU fixed daily costs × horizon days)
```

where `margin_k = sell − var_cost − Σ(parts.landed_cost × qty_per) − labor_pu`.
`labor_pu` is zeroed in the margin when mode ≠ `'per_unit'` to avoid
double-charging with the hourly/salaried envelope (R14.1 / D5).

### Decision variables
- `q[k] ≥ 0` — aggregated units produced of SKU k (continuous)
- `x[k, l] ≥ 0` — units of SKU k allocated to line l (only when a line pool
  is supplied; pinned to 0 when SKU k is not eligible on line l)
- `excess[k] ≥ 0` — overproduction beyond `di['absorbable']` (drives holding
  penalty in the objective)

### Constraints
1. **Quantity conservation:** `q[k] = Σ_l x[k, l]` (when line pool present)
2. **Demand ceiling:** `q[k] ≤ min(market_ceiling, user_max)` per SKU.
   The market ceiling depends on the **demand mode**:
   - `mts`: forecast sum (or history × cap factor)
   - `mto`: confirmed MTO order book only (ceiling == floor; no speculation)
   - `ato`: forecast + confirmed orders (hybrid)
   - `seasonal`: forecast with seasonality applied
3. **Demand floor:** `q[k] ≥ max(mto_floor, user_min)` per SKU. MTO mode
   forces `floor == ceiling` (must fulfill).
4. **Excess linearization:** `excess[k] ≥ q[k] − absorbable_k`
5. **Per-line capacity (machine-hours):**
   `Σ_k cycle_hrs(k, l) · x[k, l] ≤ avail_hrs[l] × weeks × OEE[l]`
   `cycle_hrs(k, l)` reads `line.cycle_time_by_sku_min[k] / 60` when present
   (R13.6 wiring), falling back to `cycle_times[k]`.
6. **Org labor-hours cap (R14.1 D5):** when `labor_cost_mode == 'hourly'`
   AND `workforce.hourly_headcount_cap > 0`:
   `Σ_l Σ_k cycle_hrs(k, l) · x[k, l] ≤ headcount_cap × 40 hrs/wk × weeks`
7. **Budget cap (optional):** `Σ_k (var_cost + mat_cost) · q[k] ≤ budget`
8. **Material availability (optional):** per BOM part i,
   `Σ_k parts_qty[k][i] · q[k] ≤ supply[i]`
9. **Warehouse cap (optional):** `Σ_k volume_per_unit[k] · q[k] ≤ wh_max`

### Key inputs (payload)
- `products[]`: sell_price, parts (with landed_cost), forecast, mape_pct,
  mto_orders, demand_ceiling_mode, min_quantity, max_quantity
- `lines[]`: avail_hrs_per_week, oee, cycle_time_by_sku_min, eligible_skus,
  hourly_rate (for D5 cost), workers_per_shift
- `params`: planning_horizon_months, demand_mode, budget, wh_max
- `labor_cost_mode`, `workforce` (R14.1 D5)

### Key outputs
- `total_profit`, `total_cost` (including hourly_lc, salaried_fc)
- `q[k]` per-SKU optimal mix, `line_allocation[i][k]`
- **Shadow prices** (`c.pi`) per constraint → which limits actually bind
- **Reduced costs** (`q.dj`) per excluded SKU → price increase needed to
  enter the mix
- `labor_cost_mode_active`, `hourly_labor_cost`, `salaried_fixed_cost`

### Does NOT model
- **Multi-period scheduling.** profitmix is strategic — one fat planning
  horizon, no t-index. For period-aware production, see production.py.
- **Setup/changeover cost on the mix.** That belongs in production.py once
  the mix is decided.
- **Inventory carrying across periods.** Excess is penalized in one shot,
  not period-by-period.
- **OT scheduling.** The hourly cap binds *regular* hours only. OT lives in
  production.py per-period.
- **Per-stage labor mode.** Cycle time already accounts for stage laborMode
  via the frontend `resolveCycleTime` resolver — solver math is unchanged.
- **Shared work-center pooling.** `shared_stage_ids` is echoed but not yet
  treated as a pooled-capacity constraint. Phase 4 work.

---

## 2. production.py — Production Scheduler MILP

**Type:** `pulp.LpProblem(LpMinimize)`. MILP — integer x, binary y, binary
switch, continuous ot. Solved by CBC with 5% gap tolerance, 60 s time limit.

### Objective
Minimize total cost across the horizon:

```
min  Σ_k setup_cost_k · y[k,l,t]                  (setup once per active assignment)
   + Σ_l co_cost_l · switch[l,t]                  (changeover cost — expected-value)
   + Σ_l ot_per_hr_l · ot[l,t]                    (overtime cost = workers × rate × mult)
   + makespan_weight · completion[k]              (encourage early finish)
   + salaried_monthly_cost · (T / 4.33)           (only if labor_cost_mode='salaried_idle')
```

### Decision variables
- `x[k, l, t]` ∈ ℤ ∩ [0, cap(k,l,t)] — units of product k on line l in period t
- `y[k, l, t]` ∈ {0,1} — whether product k is assigned to line l in period t
- `switch[l, t]` ∈ {0,1} for t ≥ 1 — changeover event detector
- `ot[l, t]` ∈ [0, max_ot_per_period(l)] — overtime hours on line l in period t
- `completion[k]` ∈ ℤ ∩ [0, T] — last period product k is produced

### Constraints
1. **Demand satisfaction:** `Σ_l Σ_t x[k,l,t] · yield_k ≥ required_qty_k`.
   `yield_k` is route-derived (cascaded across ops) when routing exists,
   else `prod.yield_pct`.
2. **Line eligibility:** `x[k,l,t] = 0` when line l is not on product k's
   routing (when routing exists) or when `k ∉ lines[l].products` (fallback).
3. **Linking x ↔ y:** `x[k,l,t] ≤ cap(k,l,t) · y[k,l,t]` AND
   `x[k,l,t] ≥ y[k,l,t]` (forces y=1 whenever any production happens).
4. **Per-line capacity:** `Σ_k x[k,l,t] ≤ total_cap_l + (ot_extra / hrs_per_shift) · ot[l,t]`.
   `total_cap_l = capacity × shifts_per_day`. OT adds up to +50% of base cap.
5. **Shared-line mutex:** for shared lines, `Σ_k y[k,l,t] ≤ 2` (allows two
   for changeover periods).
6. **Changeover detection:** `switch[l,t] ≥ y[k,l,t] − y[k,l,t−1]` for all k.
   Forces switch=1 whenever a new SKU starts on the line.
7. **Completion tracking:** `completion[k] ≥ (t+1) · y[k,l,t]`. Picks the
   last period any production happened.
8. **OT per-line cap:** `ot[l,t] ≤ max_ot_hrs_per_worker_per_week × workers
   × shifts` (built into variable upper bound).
9. **Org labor-hours cap (R14.1 D6):** when `labor_cost_mode == 'hourly'`
   AND `workforce.hourly_headcount_cap > 0`:
   `Σ_l Σ_k cycle_hrs(k,l) · x[k,l,t] ≤ headcount_cap × 40` per period.
10. **Org OT envelope (R15 D-OT-envelope):** when `workforce.ot_cap_hrs > 0`:
    `Σ_l ot[l,t] ≤ ot_cap_hrs` per period. Stays alongside the per-line cap;
    solver effectively binds on min(org cap, line cap).

### Capacity derivation (key helper `_route_cap`)
Per (product k, line l):
1. If routing exists: bottleneck op on this line, throughput =
   `hrs_per_period · 60 · OEE / cycle_min`, cascaded yield.
2. Else if `line.cycle_time_by_sku_min[k]` exists (R13.6 frontend wiring):
   throughput = `hrs_per_period · 60 · OEE / cycle_min_k`.
3. Else: legacy flat `line.capacity`.

OEE is `lines[l].oee` (resolveLineOEE on the frontend) → `prod.oee` →
0.766 default. Per-stage `laborMode` adjustment is **already baked into
`cycle_time_by_sku_min`** by the frontend — solver does not re-apply.

### Key outputs
- `total_cost`, `status`, `solve_time`
- `gantt[]`: per (product, line, period) qty
- `products[k]`: required, produced, completion_period, utilization
- `lines[l]`: utilization, total_produced, overtime_hours, overtime_cost,
  changeovers, oee echo, shared_stage_ids echo
- `labor_cost_mode_active`, `salaried_fixed_cost`, `org_ot_cap_hrs` (R15)
- **Shadow prices:** not currently extracted from this MILP (CBC only emits
  reliable duals for the LP relaxation). Use profitmix.py for shadow-price
  analysis.

### Does NOT model
- **From-to changeover matrix.** A full from-to changeover MIP would
  explode (n_prod × n_prod × t × l binaries). Current model uses an
  expected-value mean changeover minutes across all defined pairs and a
  single switch binary per (line, period).
- **Material/RM availability.** That's procurement.py's job; production.py
  assumes RM is always available.
- **Demand mode (mts/mto/ato/seasonal).** The required_qty per product is
  taken as a hard floor; demand-ceiling logic lives in profitmix.py.
- **Per-period inventory & expiry.** No carrying cost modeled. If you
  produce 100 and demand is 90, the 10 surplus doesn't cost anything here
  (it does in profitmix.py via `excess[k]`).
- **Joint truck consolidation / multi-SKU shipments.** Bucket-2 scope, not
  here.

---

## 3. procurement.py — Procurement & Production MILP

**Type:** `pulp.LpProblem(LpMinimize)`. MILP — integer p/r, binary y/o.
Solved by CBC with configurable time limit + gap.

### Objective
Minimize total supply chain cost across the horizon:

```
min  setup_cost(k,t) + production_cost(k,t) + FG_holding(k,t) + expiry(k,t)
   + shortage_cost(k,t) + RM_purchase(i,t) + RM_holding(i,t) + RM_ordering(i,t)
   + transport_cost(i,t)                    (R8/R10 — mode-aware via pickTransportMode)
   + lead_time_band_extra(i,t)              (R12 D — small/mid/large step function)
   + working_capital_penalty                (Pillar 10 — when over WC cap)
   + supplier_concentration_penalty         (#7 — over-concentration soft pen)
   + co2_penalty                             (#7 — when > co2_max_per_period)
```

### Decision variables (key)
- `p[k, t]` ∈ ℤ — units of product k produced in period t
- `r[i, t]` ∈ ℤ — units of raw material i ordered in period t
- `y[k, t]` ∈ {0,1} — production binary
- `o[i, t]` ∈ {0,1} — ordering binary
- `a_small/a_mid/a_large[gidx, t]` — band sub-vars when lead_time_band active
- `inv[k, t]`, `rm_inv[i, t]` — inventory positions
- `short[k, t]` — shortage units
- Plus MEIO: per-node inventory positions and in-transit `it[edge, t]`

### Constraints (key, not exhaustive)
1. **Demand satisfaction with shortage:** `inv[k,t] = inv[k,t-1] + p[k,t] − demand[k,t] + short[k,t]`
2. **Capacity:** per-line throughput × hrs_per_period × OEE per period.
   Honors planned maintenance (line-down weeks / hourly downtime).
3. **Holiday exclusion:** periods overlapping with a holiday excluded from
   capacity and shift demand to surrounding periods.
4. **Working capital cap (Pillar 10):** `Σ_k inv[k,t] · per_unit_value_k ≤ working_capital` per period.
5. **Fill-rate (T8-04):** `Σ short[k,t] ≤ (1 − target) · Σ demand[k,t]` (hard)
   or penalty term (soft).
6. **Lead-time band (R12 D):** `a_small + a_mid + a_large = r[gidx,t]` qty
   conservation; `b_small + b_mid + b_large = o[gidx,t]` event conservation;
   plus the step bounds.
7. **MEIO in-transit (R6):** `it[edge, t+lead]` receives `dispatched[edge, t]`.

### Key outputs
- `total_cost`, `total_revenue` (when sell_prices populated)
- Per-(product, period): production, demand, inventory, shortage, revenue
- Per-(material, period): order qty, inventory, holding cost, ordering cost
- Effective horizon vs committed horizon (R9 C1 — buffer trim)
- Transport cost breakdown by mode (R8/R10)

### Does NOT model
- **Production scheduling at the period level beyond binary y[k,t].** A
  per-line, per-period assignment x[k, l, t] would require coupling with
  production.py. Currently `lines[]` is only used to derive maintenance
  scaling.
- **Demand-mode logic (mts/mto/ato).** That's profitmix.py. procurement.py
  takes demand[k,t] as given.
- **Per-stage / per-machine routing.** procurement.py uses line-level
  effective throughput; the stage topology is consumed at the frontend
  level (resolveCycleTime) and pre-baked.
- **Cross-line worker pool / labor-cost mode.** Workforce envelope binds
  in production.py only. procurement.py has no labor cost concept beyond
  per-unit costs flowing through margin.

---

## 4. Common assumptions (all solvers)

- **Time grain.** Defaults to weekly (52 periods/yr, 40 hrs/wk regular).
  Monthly grain uses 22 workdays/month and ≈4.33 wk/mo conversion.
- **Currency.** Single currency per solve — `state.config.currency`. No FX
  conversion inside the solver.
- **Yield & OEE.** Cascaded multiplicatively across stages/ops. Frontend
  `resolveLineOEE` computes Π(stage.oeePct/100) when stage tables are
  populated; falls back to A·P·Q from the line registry; final fallback
  is 0.766.
- **Cycle time precedence.** `line.cycle_time_by_sku_min[k]` (frontend
  resolver, R13.6) → routing op `cycleTimeMin` (procurement/production
  only) → `cycle_times[k]` scalar fallback → `product.cycleTime`.
- **Labor cost mode (R14.1 D5/D6).**
  - `per_unit`: margin charges `product.labor_per_unit` (R13.6 default).
  - `hourly`: margin SKIPS labor; objective adds `Σ rate × cycle_hrs × x`;
    optional org-wide labor-hours cap binds.
  - `salaried_idle`: margin SKIPS labor; flat envelope `salaried_monthly_cost
    × horizon_months` added.
- **Org OT envelope (R15 D-OT-envelope).** Production.py only. Per-line
  OT cap still applies; org cap is an additional ceiling.

---

## 5. What's intentionally outside scope

These are documented gaps so future readers don't write tickets for them:

- **Stochastic / robust optimization.** All inputs are point estimates.
  Sensitivity is done one-param-at-a-time (Tab 4 sensitivity card,
  tornado, Phase 3 D4 CapEx suggester).
- **Multi-stage stochastic programming.** No scenario tree, no chance
  constraints.
- **Reinforcement learning / rolling-horizon online optimization.** This
  is a periodic re-plan model, not a real-time controller.
- **Bullwhip / supply-chain network dynamics.** MEIO inventory positions
  are static per period; no demand amplification simulation.
- **Censored / lost-sales demand estimation.** Tobit-style demand model
  deferred indefinitely (see ROUND7_HANDOFF.md §E2).
- **Per-truck/multi-SKU consolidation.** Bucket-2 deferral (A0.9).

---

*Spec ships with R15 (Phase 3 · D1). Keep this file in sync when D2 / D3 /
D4 lands — update the "Does NOT model" lists when scope changes.*
