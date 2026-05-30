"""
Product Mix / Profit Maximizer — TRUE LP (PuLP / CBC)
======================================================
This module is a TRUE Linear Program, NOT a greedy margin-per-hour heuristic.
It builds a `pulp.LpProblem(LpMaximize)` with continuous decision variables
q[k] (units produced per SKU) and per-line allocations x[k, l], real linear
constraints (demand ceiling/floor, shared/per-line capacity, budget, material
availability, warehouse), and emits LP-grade outputs:
  - Shadow prices (constraint duals via c.pi)
  - Reduced costs / range-of-optimality (q.dj)
  - Slack and binding flags
  - Crossover analysis (price increase needed for excluded SKUs to enter the mix)

Demand-aware features layered on top:
1. FORECAST-DERIVED demand ceilings (not arbitrary max_demand)
2. MAPE uncertainty → optimistic/pessimistic scenarios
3. DEMAND MODE: MTS, MTO, ATO, Seasonal
4. HOLDING/EXPIRY COST for overproduction beyond absorbable demand
5. CAPACITY expressed as machine-hours (margin/hr is the real metric)

The key insight: high margin/unit means NOTHING if:
  a) Demand doesn't exist (forecast says market is 800, not 5000)
  b) Capacity throughput is low (3hr/unit eats all machine-hours)
  c) Excess production rots (shelf life = 4 weeks, demand absorbs in 8)
"""
import pulp
import time
import math


def solve_profitmix(data):
    t0 = time.time()
    products = data.get('products', [])
    constraints = data.get('constraints', {})
    planning_mode = data.get('planning_mode', 'monthly')  # monthly, quarterly, annual
    demand_mode = data.get('demand_mode', 'mts')  # mts, mto, ato, seasonal
    # v3.1.1 Q14 — scope: forecast is already sliced by the caller to planning_horizon_months.
    # If the caller forgot, we fall back to len(forecast) which is self-consistent.
    planning_horizon_months = int(data.get('planning_horizon_months', 0) or 0)

    # R14.1 / Phase 3 · D5 — labor cost mode + org workforce envelope.
    #   'per_unit'      (default, R13.6): margin includes product.labor_per_unit; no labor-hours cap.
    #   'hourly'        : margin SKIPS labor_per_unit (avoids double-charge with the line wage);
    #                     objective adds Σ_l line.hourly_rate × cycle_hrs × x[(k,l)]; if
    #                     workforce.hourly_headcount_cap > 0, bind total labor hours.
    #   'salaried_idle' : margin SKIPS labor_per_unit; subtract a flat fixed cost
    #                     workforce.salaried_monthly_cost × horizon_months from total profit.
    labor_cost_mode = data.get('labor_cost_mode', 'per_unit')
    workforce = data.get('workforce', {}) or {}
    wf_salaried_monthly_cost = float(workforce.get('salaried_monthly_cost', 0) or 0)
    wf_hourly_headcount_cap = float(workforce.get('hourly_headcount_cap', 0) or 0)

    n = len(products)
    if not n:
        return {'error': 'No products'}

    prob = pulp.LpProblem("Profit_Maximizer", pulp.LpMaximize)

    # ── Compute demand ceilings per mode ──
    demand_info = []
    for k in range(n):
        p = products[k]
        forecast = p.get('forecast', [])  # monthly consensus forecast array
        history = p.get('history', [])
        mape = p.get('mape_pct', 15) / 100
        mto_orders = p.get('mto_orders', [])
        shelf_life_weeks = p.get('shelf_life_periods') or p.get('shelf_life', 52)

        # Clip forecast/history to the declared horizon so "sum" means "over the planning scope",
        # not "over whatever array the UI happened to send."
        if planning_horizon_months > 0:
            forecast = forecast[:planning_horizon_months] if forecast else forecast
            history = history[-planning_horizon_months:] if history else history

        if demand_mode == 'mto':
            # ONLY confirmed orders — no speculation
            confirmed = sum(o.get('qty', 0) for o in mto_orders)
            ceiling = confirmed
            floor = confirmed  # MUST fulfill
            source = f"MTO order book: {len(mto_orders)} orders"
        elif demand_mode == 'mts':
            # Forecast-based with MAPE buffer
            if forecast and len(forecast) > 0:
                period_demand = sum(forecast)
            elif history and len(history) > 0:
                period_demand = sum(history)
            else:
                period_demand = p.get('max_demand', 1000)

            # Optimistic ceiling: forecast × (1 + MAPE) — don't produce more than market can absorb
            ceiling = round(period_demand * (1 + mape))
            floor = p.get('min_quantity', 0)
            source = f"Forecast: {period_demand:,} ± {mape*100:.0f}% MAPE → ceiling {ceiling:,}"
        elif demand_mode == 'ato':
            # Components to forecast, final to order
            if mto_orders:
                confirmed = sum(o.get('qty', 0) for o in mto_orders)
                forecast_total = sum(forecast) if forecast else sum(history) if history else 0
                ceiling = max(confirmed, round(forecast_total * (1 + mape)))
                floor = confirmed
                source = f"ATO: orders={confirmed}, forecast buffer={ceiling-confirmed}"
            else:
                period_demand = sum(forecast) if forecast else sum(history) if history else p.get('max_demand', 1000)
                ceiling = round(period_demand * (1 + mape))
                floor = 0
                source = f"ATO (no orders yet): forecast ceiling {ceiling:,}"
        elif demand_mode == 'seasonal':
            # Use full forecast array including seasonal peaks
            if forecast and len(forecast) > 0:
                period_demand = sum(forecast)
                peak_month = max(forecast)
                avg_month = period_demand / len(forecast)
                seasonal_factor = peak_month / avg_month if avg_month > 0 else 1
            else:
                period_demand = sum(history) if history else p.get('max_demand', 1000)
                seasonal_factor = 1.0
            ceiling = round(period_demand * (1 + mape))
            floor = p.get('min_quantity', 0)
            source = f"Seasonal: {period_demand:,}, peak factor={seasonal_factor:.1f}×"
        else:
            # Fallback: use max_demand as before
            ceiling = p.get('max_demand', 99999)
            floor = p.get('min_quantity', 0)
            source = "Static max_demand (no forecast linked)"

        # v3.4 — per-SKU ceiling mode overrides the buffered default
        mode = p.get('demand_ceiling_mode', 'soft')
        if mode == 'strict':
            # Hard cap at the raw forecast/history total — no MAPE upside allowed
            base = sum(forecast) if forecast else (sum(history) if history else ceiling)
            ceiling = int(base) if base else ceiling
            source = f"[STRICT] {source}"
        elif mode == 'off':
            # Solver is free; only max_quantity (if user-set) will constrain from above
            ceiling = 10 ** 9
            source = f"[OFF] {source} (solver unbounded, use maxProd to cap)"
        # soft = leave buffered ceiling as-is

        # v3.4 — replan-from-period: lock actuals[0..replan-1] as committed floor
        replan_from = constraints.get('replan_from_period')
        actuals = p.get('actuals') or []
        if replan_from is not None and 0 < replan_from <= len(actuals):
            committed = sum(a for a in actuals[:replan_from] if a is not None)
            if committed > floor:
                floor = int(committed)
                source += f" | replan anchor: +{committed:,} committed actuals through period {replan_from}"

        # v3.5 — T0 on-hand inventory: already-produced FG reduces the net new-production requirement.
        # Shrink the demand ceiling so the solver doesn't double-plan stock we already have.
        init_inv = int(p.get('init_inventory') or 0)
        if init_inv > 0 and ceiling > 0:
            ceiling = max(0, ceiling - init_inv)
            source += f" | T0 on-hand {init_inv:,} absorbed"

        demand_info.append({
            'ceiling': ceiling,
            'floor': floor,
            'source': source,
            'absorbable': ceiling if mode != 'off' else (sum(forecast) if forecast else sum(history) if history else ceiling),
        })

    # ── Decision variables ──
    # v3.4 — per-line allocation when a shared line pool is supplied at top level.
    # x[k, l] = units of SKU k assigned to line l. q[k] = Σ_l x[k,l].
    # If the line pool is absent, fall back to a single global q[k] (legacy behavior).
    lines_pool = data.get('lines', []) or []
    has_line_pool = bool(lines_pool)
    q = {}  # aggregated production quantity per SKU
    x = {}  # per-line assignment (only populated when has_line_pool)
    excess = {}  # overproduction beyond absorbable demand
    for k in range(n):
        q[k] = pulp.LpVariable(f'q_{k}', 0, cat='Continuous')
        excess[k] = pulp.LpVariable(f'excess_{k}', 0, cat='Continuous')
    if has_line_pool:
        for k in range(n):
            for li, line in enumerate(lines_pool):
                eligible = set(line.get('eligible_skus', list(range(n))))
                if k in eligible:
                    x[(k, li)] = pulp.LpVariable(f'x_{k}_{li}', 0, cat='Continuous')
                else:
                    # Not eligible — pin to 0 via dummy variable (kept for transparency in result inspection).
                    x[(k, li)] = pulp.LpVariable(f'x_{k}_{li}', 0, 0, cat='Continuous')
            # q[k] = Σ_l x[k,l]
            prob += q[k] == pulp.lpSum(x[(k, li)] for li in range(len(lines_pool))), f"QuantitySum_{k}"

    # ── Objective: maximize profit - holding cost on excess ──
    obj = []
    for k in range(n):
        p = products[k]
        sell = p.get('sell_price', 100)
        var_cost = p.get('variable_cost', 0)
        # v3.5 — prefer landed_cost (includes freight/insurance/duty/handling per unit) when the UI provides it.
        # Falls back to base cost so older payloads still work identically.
        mat_cost = sum(
            (part.get('landed_cost') if part.get('landed_cost') is not None else part.get('cost', 0)) * part.get('qty_per', 1)
            for part in p.get('parts', [])
        )
        labor_pu_raw = p.get('labor_per_unit', 0) or 0
        # R14.1 / Phase 3 · D5 — under 'hourly' or 'salaried_idle' modes, the per-unit labor cost
        # is moved out of the margin (charged via line.hourly_rate × hours, or via the salaried
        # envelope). Keeping it in here would double-charge the same labor hour.
        labor_pu = labor_pu_raw if labor_cost_mode == 'per_unit' else 0
        margin = sell - var_cost - mat_cost - labor_pu
        products[k]['_margin'] = margin
        products[k]['_mat_cost'] = mat_cost
        products[k]['_labor_per_unit'] = labor_pu
        products[k]['_labor_per_unit_raw'] = labor_pu_raw

        # Revenue from units actually sold (up to demand ceiling)
        obj.append(margin * q[k])

        # Penalty for overproduction: holding cost over the horizon + expiry write-off.
        # (MF-5) shelf life is stored in WEEKS (default 52); convert to months so it can be
        # compared against the month-based horizon. The old `shelf < 12` compared weeks
        # against months (mixed units) and the holding charge was a single fixed month
        # regardless of planning_horizon_months.
        shelf_weeks = p.get('shelf_life_periods') or p.get('shelf_life', 52)
        shelf_months = shelf_weeks / (52.0 / 12.0)  # ≈ /4.333
        carry_rate = p.get('carry_rate', 0.24)
        unit_cost = var_cost + mat_cost
        # planning_horizon_months (when the UI sends it) is authoritative; planning_mode is only
        # a fallback for legacy payloads that omit it.
        horizon_months = planning_horizon_months if planning_horizon_months > 0 else \
            {'monthly': 1, 'quarterly': 3, 'annual': 12}.get(planning_mode, 1)
        # Holding cost on excess across the WHOLE horizon (annual carry_rate → /12 per month).
        holding_penalty = unit_cost * (carry_rate / 12.0) * horizon_months
        # (MF-2) Expiry write-off — now actually applied. Excess is production beyond absorbable
        # demand, so it can't be sold this horizon; if its shelf life is shorter than the horizon
        # it WILL spoil → charge the sunk make-cost net of salvage recovery, unit_cost·(1−salvage).
        # Higher salvage lowers the penalty (optimizer tolerates more buffer); lower salvage raises it.
        salvage = p.get('salvage_rate', 0.8)
        expiry_penalty = unit_cost * max(0.0, 1.0 - salvage) if shelf_months < horizon_months else 0.0

        obj.append(-(holding_penalty + expiry_penalty) * excess[k])  # penalize overproduction

    # Fixed daily cost per SKU — allocated across the planning horizon.
    # planning_mode 'monthly' ≈ 30 days per period; 'quarterly' ≈ 90; 'annual' ≈ 365.
    horizon_days = {'monthly': 30, 'quarterly': 90, 'annual': 365}.get(planning_mode, 30)
    if planning_horizon_months > 0:
        horizon_days = 30 * planning_horizon_months
    fixed_total = sum((p.get('fixed_daily_cost', 0) or 0) * horizon_days for p in products)

    # R14.1 / Phase 3 · D5 — pulled forward from the constraints section so the labor-cost
    # objective additions below (and the OrgLaborHrsCap constraint later) can reference them.
    # Identical body to the prior in-constraints definition (R13 Phase 1b A4/A5).
    cycle_times = [p.get('cycle_time', 1) for p in products]
    def _cycle_hrs_for_line(k, line):
        by_sku = line.get('cycle_time_by_sku_min', {}) or {}
        if not by_sku:
            return cycle_times[k]
        v = by_sku.get(k)
        if v is None:
            v = by_sku.get(str(k))
        if v is None or float(v) <= 0:
            return cycle_times[k]
        return float(v) / 60.0

    # R14.1 / Phase 3 · D5 — labor cost objective additions.
    #   'hourly' (line pool only): subtract Σ_l line.hourly_rate × Σ_k cycle_hrs × x[(k,l)] from profit.
    #                              Without a line pool, fall back to skipping (no per-line wage to apply).
    #   'salaried_idle': subtract a flat salaried envelope from profit (constant — affects total only).
    hourly_labor_cost_terms = []
    if labor_cost_mode == 'hourly' and has_line_pool:
        for li, line in enumerate(lines_pool):
            rate = float(line.get('hourly_rate', 0) or 0)
            if rate <= 0:
                continue
            for k in range(n):
                if (k, li) in x:
                    ch = _cycle_hrs_for_line(k, line)
                    hourly_labor_cost_terms.append(rate * ch * x[(k, li)])

    salaried_fixed_cost = 0.0
    if labor_cost_mode == 'salaried_idle':
        months = planning_horizon_months if planning_horizon_months > 0 else 1
        salaried_fixed_cost = wf_salaried_monthly_cost * months

    prob += pulp.lpSum(obj) - pulp.lpSum(hourly_labor_cost_terms) - fixed_total - salaried_fixed_cost, "Total_Profit"

    # ── Constraints ──
    constraint_names = {}

    for k in range(n):
        di = demand_info[k]
        user_max = products[k].get('max_quantity', 0) or 0

        # Demand ceiling: can't sell more than market absorbs.
        # If user set maxProd > 0, cap at min(market ceiling, user max).
        effective_ceiling = di['ceiling']
        if user_max > 0:
            effective_ceiling = min(effective_ceiling, user_max)
        prob += q[k] <= effective_ceiling, f"DemandCeiling_{k}"
        if user_max > 0:
            constraint_names[f"Max prod: {products[k].get('name', f'P{k}')}"] = f"DemandCeiling_{k}"

        # Demand floor: minimum commitment (MTO orders, contracts, user-set minProd)
        user_min = products[k].get('min_quantity', 0) or 0
        effective_floor = max(di['floor'], user_min)
        if effective_floor > 0:
            prob += q[k] >= effective_floor, f"DemandFloor_{k}"
            tag = "Min prod" if user_min >= di['floor'] else "Min commit"
            constraint_names[f"{tag}: {products[k].get('name', f'P{k}')}"] = f"DemandFloor_{k}"

        # Excess = max(0, q - absorbable_demand)
        # Linearized: excess >= q - absorbable
        prob += excess[k] >= q[k] - di['absorbable'], f"Excess_{k}"

    # Shared capacity (machine-hours) — `cycle_times` and `_cycle_hrs_for_line` are defined earlier
    # (R14.1 D5 pulled them forward); see comment block above the labor-cost objective additions.
    # R13 Phase 1b backend wiring · A4/A5 — per-(SKU, line) cycle time + per-line OEE.
    # Frontend resolves cycle time using override → Σ stage cycleMin → product fallback, and OEE
    # using stage product or A/P/Q. When `cycle_time_by_sku_min[k]` is present, prefer it (in minutes,
    # converted to hours here). When `oee` is present, derate available hours by it. Both fields are
    # OPTIONAL — payloads from older builds without these fields fall back to the previous behavior.

    if has_line_pool:
        # v3.4 — per-line hours budget. Σ_k cycle[k,l] * x[k,l] ≤ avail_hrs[l] × oee[l]
        for li, line in enumerate(lines_pool):
            avail = line.get('avail_hrs_per_week', line.get('avail_hrs', 0))
            oee = float(line.get('oee') or 1.0)
            # weekly → scale by planning horizon weeks (infer from horizon_days/7)
            weeks = max(1, round((30 * planning_horizon_months / 7) if planning_horizon_months > 0 else 4.33))
            line_cap_hrs = avail * weeks * oee
            c_name = f"LineHrs_{li}"
            prob += pulp.lpSum(
                _cycle_hrs_for_line(k, line) * x[(k, li)] for k in range(n) if (k, li) in x
            ) <= line_cap_hrs, c_name
            constraint_names[f"Line hrs: {line.get('name', f'L{li}')}"] = c_name
    else:
        shared_cap = constraints.get('shared_capacity', 0)
        if shared_cap > 0:
            prob += pulp.lpSum(
                cycle_times[k] * q[k] for k in range(n)
            ) <= shared_cap, "Shared_Capacity"
            constraint_names['Shared Capacity (machine-hrs)'] = "Shared_Capacity"

    # Per-line capacity
    for li, line in enumerate(constraints.get('lines', [])):
        cap = line.get('capacity', 999999)
        line_products = line.get('products', list(range(n)))
        c_name = f"Line_{line.get('name', li)}"
        prob += pulp.lpSum(
            q[k] for k in line_products if k < n
        ) <= cap, c_name
        constraint_names[f"Line: {line.get('name', f'L{li}')}"] = c_name

    # Budget
    budget = constraints.get('budget', 0)
    if budget > 0:
        prob += pulp.lpSum(
            (products[k].get('variable_cost', 0) + products[k].get('_mat_cost', 0)) * q[k]
            for k in range(n)
        ) <= budget, "Budget"
        constraint_names['Budget'] = "Budget"

    # Material availability
    for mat_name, avail in constraints.get('materials', {}).items():
        mat_users = []
        for k in range(n):
            for part in products[k].get('parts', []):
                if part.get('name', '') == mat_name:
                    mat_users.append((k, part.get('qty_per', 1)))
        if mat_users:
            c_name = f"Mat_{mat_name}"
            prob += pulp.lpSum(
                qty_per * q[k] for k, qty_per in mat_users
            ) <= avail, c_name
            constraint_names[f"Material: {mat_name}"] = c_name

    # Warehouse
    wh_max = constraints.get('warehouse', 0)
    if wh_max > 0:
        prob += pulp.lpSum(q[k] for k in range(n)) <= wh_max, "Warehouse"
        constraint_names['Warehouse'] = "Warehouse"

    # R14.1 / Phase 3 · D5 — Org-wide labor-hours cap when 'hourly' mode is active and a cap is set.
    # Total labor hours used = Σ_l Σ_k cycle_hrs(k,l) × x[(k,l)]. Cap = headcount_cap × 40 hrs/wk × weeks.
    # Note: 40 hrs/wk is the assumed regular-hours baseline per worker; OT is a separate per-period
    # ceiling enforced in production.py (this LP is strategic, not period-resolved). Skipped without
    # a line pool (no per-line cycle_hrs data on the aggregate path).
    if labor_cost_mode == 'hourly' and has_line_pool and wf_hourly_headcount_cap > 0:
        weeks = max(1, round((30 * planning_horizon_months / 7) if planning_horizon_months > 0 else 4.33))
        org_labor_hrs_cap = wf_hourly_headcount_cap * 40 * weeks
        prob += pulp.lpSum(
            _cycle_hrs_for_line(k, line) * x[(k, li)]
            for k in range(n) for li, line in enumerate(lines_pool) if (k, li) in x
        ) <= org_labor_hrs_cap, "OrgLaborHrsCap"
        constraint_names['Org Labor Hours Cap (hourly)'] = "OrgLaborHrsCap"

    # ── Solve ──
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=30)
    status = prob.solve(solver)
    solve_time = time.time() - t0

    if status != pulp.constants.LpStatusOptimal:
        return {'status': pulp.LpStatus[status], 'error': f'Solver: {pulp.LpStatus[status]}',
                'solve_time': round(solve_time, 2)}

    total_profit = pulp.value(prob.objective)

    # ── Extract results ──
    product_results = []
    total_revenue = 0
    total_cost = 0
    for k in range(n):
        qty = pulp.value(q[k]) or 0
        exc = pulp.value(excess[k]) or 0
        p = products[k]
        margin = p.get('_margin', 0)
        # (MF-8) Effective cycle hours = realized machine-hours / qty, using the SAME per-line
        # cycle basis the LP optimized on (_cycle_hrs_for_line). The scalar product cycle_time is
        # ignored by the LP whenever a line carries cycle_time_by_sku_min, so the headline
        # margin/hr must not be computed from it. Falls back to the scalar with no line pool.
        if has_line_pool and qty > 0.01:
            realized_hrs = sum(
                (pulp.value(x[(k, li)]) or 0) * _cycle_hrs_for_line(k, lines_pool[li])
                for li in range(len(lines_pool)) if (k, li) in x
            )
            cycle = realized_hrs / qty if qty > 0.01 else cycle_times[k]
        else:
            cycle = cycle_times[k]
        revenue = qty * p.get('sell_price', 0)
        cost = qty * (p.get('variable_cost', 0) + p.get('_mat_cost', 0))
        profit = qty * margin
        total_revenue += revenue
        total_cost += cost

        di = demand_info[k]

        product_results.append({
            'name': p.get('name', f'P{k}'),
            'quantity': round(qty, 1),
            'margin_per_unit': round(margin, 2),
            'margin_per_hour': round(margin / max(cycle, 0.001), 2),
            'cycle_time': cycle,
            'revenue': round(revenue, 2),
            'cost': round(cost, 2),
            'profit': round(profit, 2),
            'pct_of_total': round(profit / max(total_profit, 1) * 100, 1) if total_profit > 0 else 0,
            'demand_ceiling': di['ceiling'],
            'demand_floor': di['floor'],
            'demand_source': di['source'],
            'demand_filled': round(qty / max(di['ceiling'], 1) * 100, 1),
            'excess_inventory': round(exc, 1),
            'capacity_hours_used': round(qty * cycle, 1),
        })

    # Sort by margin/hr for display
    product_results.sort(key=lambda x: x['margin_per_hour'], reverse=True)

    # Shadow prices + LP sensitivity (range of feasibility / allowable RHS change)
    shadow_prices = []
    for display_name, c_name in constraint_names.items():
        c = prob.constraints.get(c_name)
        if c is not None:
            dual = c.pi if hasattr(c, 'pi') and c.pi is not None else 0
            slack = c.slack if hasattr(c, 'slack') else None
            binding = slack is not None and abs(slack) < 0.01
            # For non-binding constraints, allowable decrease = slack (before it becomes binding).
            # For binding constraints, exact range requires sensitivity from CBC; we approximate.
            if not binding and slack is not None:
                allow_dec = round(abs(slack), 2)
                allow_inc = "∞"
            else:
                allow_inc = "see re-solve"  # exact requires basis re-solve; UI can trigger
                allow_dec = "see re-solve"
            shadow_prices.append({
                'constraint': display_name,
                'shadow_price': round(dual, 2),
                'slack': round(slack, 2) if slack is not None else None,
                'binding': binding,
                'allowable_increase': allow_inc,
                'allowable_decrease': allow_dec,
                'interpretation': (
                    f"Binding. Relaxing RHS by 1 improves profit by ${abs(round(dual, 2))}. "
                    f"Tightening by 1 costs ${abs(round(dual, 2))}."
                    if binding and dual != 0
                    else f"Not binding — {round(slack, 1)} units of slack remain. No profit impact until tightened past slack." if slack else "—"
                ),
            })

    # Reduced costs (range of optimality) for decision variables
    reduced_costs = []
    for k in range(n):
        p = products[k]
        dj = q[k].dj if hasattr(q[k], 'dj') and q[k].dj is not None else 0
        qty = pulp.value(q[k]) or 0
        margin = p.get('_margin', 0)
        in_solution = qty > 0.01
        reduced_costs.append({
            'variable': p.get('name', f'P{k}'),
            'quantity': round(qty, 2),
            'margin': round(margin, 2),
            'reduced_cost': round(dj, 2),
            'in_solution': in_solution,
            'interpretation': (
                f"In the optimal mix. Margin must drop by more than ${abs(round(dj, 2))}/u before it exits."
                if in_solution and dj != 0
                else f"Excluded from mix. Margin must rise by ${abs(round(dj, 2))}/u before it enters."
                if not in_solution and dj != 0
                else f"In mix at boundary — margin change has immediate effect."
            ),
        })

    # Compute crossover analysis: at what price does each excluded product enter the mix?
    crossover = []
    shared_cap = constraints.get('shared_capacity', 0)
    if has_line_pool or shared_cap > 0:
        # Find the marginal product (lowest margin/hr that's still produced)
        produced = [pr for pr in product_results if pr['quantity'] > 0]
        if produced:
            min_marginal = min(pr['margin_per_hour'] for pr in produced)
            for pr in product_results:
                if pr['quantity'] == 0 and pr['cycle_time'] > 0:
                    # What price makes margin/hr >= min_marginal?
                    p_data = next(p for p in products if p.get('name') == pr['name'])
                    needed_margin = min_marginal * pr['cycle_time']
                    needed_price = needed_margin + p_data.get('variable_cost', 0) + p_data.get('_mat_cost', 0)
                    current_price = p_data.get('sell_price', 0)
                    crossover.append({
                        'product': pr['name'],
                        'current_price': current_price,
                        'crossover_price': round(needed_price, 2),
                        'price_increase_needed': round(needed_price - current_price, 2),
                        'price_increase_pct': round((needed_price - current_price) / max(current_price, 1) * 100, 1),
                        'explanation': f"At ${needed_price:.0f}+, margin/hr (${needed_margin/pr['cycle_time']:.0f}) exceeds marginal product (${min_marginal:.0f}/hr)",
                    })

    # v3.4 — per-line allocation breakdown (SKU × line grid + line utilization)
    line_allocation = []
    line_utilization = []
    if has_line_pool:
        for li, line in enumerate(lines_pool):
            avail = line.get('avail_hrs_per_week', line.get('avail_hrs', 0))
            oee = float(line.get('oee') or 1.0)
            weeks = max(1, round((30 * planning_horizon_months / 7) if planning_horizon_months > 0 else 4.33))
            # R13 Phase 1b — utilization shown against the OEE-derated capacity actually used in the LP.
            line_cap_hrs = avail * weeks * oee
            line_hrs_used = 0
            per_sku = []
            for k in range(n):
                if (k, li) in x:
                    qty_on_line = pulp.value(x[(k, li)]) or 0
                    if qty_on_line > 0.01:
                        hrs = qty_on_line * _cycle_hrs_for_line(k, line)
                        line_hrs_used += hrs
                        per_sku.append({
                            'sku': products[k].get('name', f'P{k}'),
                            'sku_idx': k,
                            'quantity': round(qty_on_line, 1),
                            'hours': round(hrs, 2),
                            'cycle_hrs_per_unit': round(_cycle_hrs_for_line(k, line), 4),
                        })
            line_allocation.append({
                'line_id': line.get('id', f'L{li}'),
                'line_name': line.get('name', f'Line {li+1}'),
                'skus': per_sku,
                'hours_used': round(line_hrs_used, 2),
                'hours_available': round(line_cap_hrs, 2),
                'oee': round(oee, 4),
                'utilization_pct': round(line_hrs_used / max(line_cap_hrs, 0.01) * 100, 1),
                'dedicated': bool(line.get('dedicated', False)),
                'shared_stage_ids': line.get('shared_stage_ids', []),
            })
            line_utilization.append({
                'line': line.get('name', f'L{li}'),
                'util_pct': round(line_hrs_used / max(line_cap_hrs, 0.01) * 100, 1),
            })

    # R14.1 / Phase 3 · D5 — post-solve extraction of the new labor-cost components so the UI can
    # show how much of total_cost came from hourly wages vs fixed salaried envelope.
    hourly_labor_cost_total = 0.0
    if labor_cost_mode == 'hourly' and has_line_pool:
        for li, line in enumerate(lines_pool):
            rate = float(line.get('hourly_rate', 0) or 0)
            if rate <= 0:
                continue
            for k in range(n):
                if (k, li) in x:
                    ch = _cycle_hrs_for_line(k, line)
                    qty = pulp.value(x[(k, li)]) or 0
                    hourly_labor_cost_total += rate * ch * qty

    return {
        'status': 'Optimal',
        'total_profit': round(total_profit, 2),
        'total_revenue': round(total_revenue, 2),
        'total_cost': round(total_cost + fixed_total + hourly_labor_cost_total + salaried_fixed_cost, 2),
        'fixed_cost': round(fixed_total, 2),
        # R14.1 / Phase 3 · D5 — labor cost transparency.
        'labor_cost_mode_active': labor_cost_mode,
        'hourly_labor_cost': round(hourly_labor_cost_total, 2),
        'salaried_fixed_cost': round(salaried_fixed_cost, 2),
        'horizon_days': horizon_days,
        'contribution_margin': round(total_profit + fixed_total, 2),
        'margin_pct': round(total_profit / max(total_revenue, 1) * 100, 1),
        'demand_mode': demand_mode,
        'products': product_results,
        'shadow_prices': shadow_prices,
        'reduced_costs': reduced_costs,
        'crossover_analysis': crossover,
        'line_allocation': line_allocation,
        'line_utilization': line_utilization,
        'solve_time': round(solve_time, 2),
    }
