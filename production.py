"""
Production Scheduler MILP
==========================
Given a set of production orders (products × quantities), production lines,
and setup/changeover costs between products:

Minimize: total setup cost + overtime cost + makespan penalty
Subject to: capacity, sequence, changeover time

Outputs: Gantt chart data, sequence per line per period, utilization
"""
import pulp
import time
import math


def solve_production(data):
    t0 = time.time()
    products = data.get('products', [])
    lines = data.get('lines', [])
    params = data.get('params', {})

    T = params.get('periods', 26)
    ot_cost_default = params.get('overtime_cost_per_hr', 50)  # T4-04 — fallback when line lacks workers/rate
    hrs_per_shift = params.get('hours_per_shift', 8)
    makespan_weight = params.get('makespan_weight', 0.1)

    # R14.1 / Phase 3 · D6 — labor cost mode + org workforce envelope.
    #   'per_unit'     (R13.6): no extra cost; per-line OT cost objective unchanged.
    #   'hourly'       : if workforce.hourly_headcount_cap > 0, add a per-period org-wide labor-hours
    #                    cap (cap × 40 hrs/wk regular). OT vars remain capped per-line by the existing
    #                    line.max_ot_hrs_per_worker_per_week × workers × shifts logic.
    #   'salaried_idle': add a flat salaried envelope to the objective
    #                    (salaried_monthly_cost × T_in_months). Constant — affects total cost only.
    # Per-stage laborMode cycle adjustment is NOT done here — it is applied frontend-side in
    # resolveCycleTime so cycle_time_by_sku_min reaches this solver already adjusted.
    labor_cost_mode = data.get('labor_cost_mode', 'per_unit')
    workforce = data.get('workforce', {}) or {}
    wf_salaried_monthly_cost = float(workforce.get('salaried_monthly_cost', 0) or 0)
    wf_hourly_headcount_cap = float(workforce.get('hourly_headcount_cap', 0) or 0)
    # R15 / Phase 3 · D-OT-envelope — org-wide weekly OT cap. Binds Σ_l ot[l,t] per period
    # in addition to the existing per-line max_ot_hrs_per_worker_per_week × workers × shifts cap.
    # Solver effectively takes min(line cap, org cap) without an explicit min — both are enforced.
    wf_ot_cap_hrs = float(workforce.get('ot_cap_hrs', 0) or 0)

    n_prod = len(products)
    n_lines = len(lines) if lines else 1

    if not n_prod:
        return {'error': 'No products'}

    # If no lines defined, create a default shared line
    if not lines:
        lines = [{'id': 'line1', 'name': 'Line 1', 'capacity': 50,
                   'type': 'shared', 'products': list(range(n_prod))}]
        n_lines = 1

    # T4-04 — per-line OT cost helper. OT_cost = workers × hrs × rate × mult.
    # Falls back to params.overtime_cost_per_hr * hrs when the line lacks workers/rate (old payload).
    def line_ot_cost_per_hr(l):
        w = float(l.get('workers_per_shift', 0) or 0)
        rate = float(l.get('hourly_rate', 0) or 0)
        mult = float(l.get('ot_mult', 1.5) or 1.5)
        if w > 0 and rate > 0:
            return w * rate * mult
        return ot_cost_default
    # T4-04 — legal cap on OT hrs/period: maxOtHrsPerWorkerPerWeek × workers × shifts (assumes weekly grain).
    def line_max_ot_per_period(l):
        cap = float(l.get('max_ot_hrs_per_worker_per_week', 12) or 12)
        w = float(l.get('workers_per_shift', 1) or 1)
        sh = float(l.get('shifts_per_day', 1) or 1)
        return cap * w * sh

    prob = pulp.LpProblem("Production_Scheduler", pulp.LpMinimize)

    # Decision variables
    # x[k,l,t] = units of product k on line l in period t
    x = {}
    # y[k,l,t] = binary: product k assigned to line l in period t
    y = {}
    # ot[l,t] = overtime hours on line l in period t
    ot = {}
    # completion[k] = last period product k is produced
    completion = {}

    # Helper — for each (product, line) compute the effective capacity per period.
    # Resolution order (R13 Phase 1b backend wiring · A4/A5):
    #   1. Routing ops on this line (legacy SAP-style routing) — bottleneck wins.
    #   2. line.cycle_time_by_sku_min[k] — frontend-resolved per-(SKU, line) cycle from
    #      override → Σ stage cycleMin → product fallback. Used when no routing.
    #   3. lines[l].capacity — flat units/period cap (legacy fallback).
    # OEE source preference: lines[l].oee (resolveLineOEE on the frontend) → prod.oee → default.
    def _line_oee(l, prod):
        v = lines[l].get('oee')
        if v is not None:
            try:
                vf = float(v)
                if vf > 0:
                    return vf
            except (TypeError, ValueError):
                pass
        return prod.get('oee', 0.85 * 0.92 * 0.98)

    def _cycle_min_by_sku(l, k):
        by_sku = lines[l].get('cycle_time_by_sku_min', {}) or {}
        if not by_sku:
            return None
        v = by_sku.get(k)
        if v is None:
            v = by_sku.get(str(k))
        try:
            vf = float(v)
            return vf if vf > 0 else None
        except (TypeError, ValueError):
            return None

    def _route_cap(k, l):
        """Return (units_per_period, eligible_bool, route_yield)."""
        prod = products[k]
        route = prod.get('routing') or []
        line_id = lines[l].get('id', f'line{l}')
        hrs_per_period = params.get('hrs_per_period', 40)  # weekly hrs available
        line_oee = _line_oee(l, prod)
        if not route:
            # No routing — try frontend-resolved per-(SKU, line) cycle next, else fall back to line capacity.
            ct_min = _cycle_min_by_sku(l, k)
            if ct_min is not None:
                units = (hrs_per_period * 60 * line_oee) / ct_min
                return int(units), True, prod.get('yield_pct', 0.95)
            return lines[l].get('capacity', 50), True, prod.get('yield_pct', 0.95)
        # Ops assigned to this line
        ops_on_line = [op for op in route if op.get('line_id') == line_id or op.get('lineId') == line_id]
        if not ops_on_line:
            # line isn't part of this product's routing → ineligible
            return 0, False, 0
        # Bottleneck op on this line — lowest throughput. OEE comes from the line, not the product,
        # so a stage retrofit on Line 2 doesn't get inherited by Line 1.
        min_per_period = hrs_per_period * 60 * line_oee
        throughputs = []
        y_mult = 1.0
        for op in ops_on_line:
            ct = op.get('cycleTimeMin', op.get('cycle_time_min', 1)) or 1
            par = max(op.get('parallelism', 1), 1)
            throughputs.append(min_per_period / ct * par)
            y_mult *= op.get('yieldPct', op.get('yield_pct', 100)) / 100.0
        return int(min(throughputs)), True, y_mult

    # Planned maintenance — two modes:
    #   weekly: line fully down for weeks [from_week, to_week]
    #   hourly: specific hours on a specific date → capacity reduced pro-rata
    # JSON payload weekly values are 1-indexed (W1..WT) — normalize to 0-indexed t.
    maint_down = set()               # (line, t) fully down
    maint_scale = {}                 # (line, t) -> multiplier in [0, 1]
    hrs_per_period = params.get('hrs_per_period', 40)  # weekly hrs available per line
    horizon_start_ts = params.get('horizon_start_date')  # optional YYYY-MM-DD
    try:
        import datetime as _dt
        start_dt = _dt.date.fromisoformat(horizon_start_ts) if horizon_start_ts else None
    except Exception:
        start_dt = None

    for l in range(n_lines):
        for w in lines[l].get('planned_maintenance', []) or []:
            mode = (w.get('mode') or 'weekly').lower()
            if mode == 'weekly':
                fw = max(int(w.get('from_week', 0)) - 1, 0)
                tw = max(int(w.get('to_week', 0)) - 1, fw)
                for t in range(fw, min(tw + 1, T)):
                    maint_down.add((l, t))
            elif mode == 'hourly':
                # Resolve which period this date falls in; fallback: period 0.
                t_target = 0
                if start_dt and w.get('date'):
                    try:
                        d = _dt.date.fromisoformat(w['date'])
                        t_target = max(0, min((d - start_dt).days // 7, T - 1))
                    except Exception:
                        t_target = 0
                hrs_lost = float(w.get('hours_lost', 0) or 0)
                if hrs_per_period <= 0 or hrs_lost <= 0:
                    continue
                scale = max(0.0, 1.0 - (hrs_lost / hrs_per_period))
                prev = maint_scale.get((l, t_target), 1.0)
                maint_scale[(l, t_target)] = min(prev, scale)
                if scale <= 0.0:
                    maint_down.add((l, t_target))

    for k in range(n_prod):
        completion[k] = pulp.LpVariable(f'comp_{k}', 0, T, cat='Integer')
        for l in range(n_lines):
            for t in range(T):
                cap_route, eligible, _ = _route_cap(k, l)
                cap = cap_route if eligible else 0
                if (l, t) in maint_down:
                    cap = 0  # line fully down — zero capacity
                elif (l, t) in maint_scale:
                    cap = int(cap * maint_scale[(l, t)])  # hourly downtime pro-rata
                x[k, l, t] = pulp.LpVariable(f'x_{k}_{l}_{t}', 0, cap, cat='Integer')
                y[k, l, t] = pulp.LpVariable(f'y_{k}_{l}_{t}', cat='Binary')
            # Changeover: w[k1,k2,l,t] = 1 if switch from k1 to k2 on line l at period t
    # Changeover variables (simplified: count active product switches per line per period)
    switch = {}
    for l in range(n_lines):
        for t in range(1, T):
            switch[l, t] = pulp.LpVariable(f'sw_{l}_{t}', 0, cat='Binary')

    # T4-04 — OT upper bound = legal cap (maxOtHrsPerWorkerPerWeek × workers × shifts), per line per period.
    for l in range(n_lines):
        max_ot = line_max_ot_per_period(lines[l])
        for t in range(T):
            ot[l, t] = pulp.LpVariable(f'ot_{l}_{t}', 0, max_ot)

    # Objective: minimize setup + overtime + makespan
    obj = []
    for k in range(n_prod):
        setup_cost = products[k].get('setup_cost', 50)
        for l in range(n_lines):
            for t in range(T):
                obj.append(setup_cost * y[k, l, t])

    # T4-10 — Changeover cost: per-line scalar fallback; SKU-pair matrix when populated.
    # The MILP variable `switch[l,t]` only counts switches; sku-pair lookup happens via expected-value
    # average over eligible pairs to keep the model linear (a full from-to changeover MIP would explode).
    changeover_cost_default = params.get('changeover_cost', 100)
    for l in range(n_lines):
        line = lines[l]
        co_matrix = line.get('changeover_matrix', {}) or {}
        # Mean changeover minutes across all defined pairs on this line; falls back to scalar.
        co_mins_scalar = float(line.get('changeover_mins', 30) or 30)
        if co_matrix:
            pair_vals = [float(co_matrix[fi][ti]) for fi in co_matrix for ti in co_matrix.get(fi, {})]
            mean_co_min = sum(pair_vals) / max(len(pair_vals), 1) if pair_vals else co_mins_scalar
        else:
            mean_co_min = co_mins_scalar
        # Cost per changeover scales with minutes lost (1 min = 1/60 hr × line OT cost).
        co_cost_line = changeover_cost_default + (mean_co_min / 60.0) * line_ot_cost_per_hr(line)
        for t in range(1, T):
            obj.append(co_cost_line * switch[l, t])

    # T4-04 — OT cost per line: workers × hrs × hourlyRate × otMult.
    for l in range(n_lines):
        ot_per_hr = line_ot_cost_per_hr(lines[l])
        for t in range(T):
            obj.append(ot_per_hr * ot[l, t])

    # Makespan penalty (encourage finishing early)
    for k in range(n_prod):
        obj.append(makespan_weight * completion[k])

    # R14.1 / Phase 3 · D6 — salaried-idle envelope as a flat fixed cost (added regardless of
    # utilization). Periods are weekly; convert to months at 4.33 weeks/month.
    salaried_fixed_cost = 0.0
    if labor_cost_mode == 'salaried_idle':
        salaried_fixed_cost = wf_salaried_monthly_cost * (T / 4.33)
        obj.append(salaried_fixed_cost)

    # PR-A (W3 follow-up) — OPT-IN time-phased MPS. When params.time_phased is set and a
    # product carries demand_by_period[], we add a no-backorder inventory balance per
    # (product, period). That forces cumulative production to COVER cumulative demand by
    # every period (not just the horizon total), so the schedule tracks the demand curve
    # instead of front-loading everything into week 1-2 to minimize makespan; a holding cost
    # on the carried inventory penalizes building early. Default OFF ⇒ model byte-unchanged
    # (the W3-verified total-demand behavior). This is the additive L3 production-truth gain.
    time_phased = bool(params.get('time_phased', False))
    holding_cost_per_unit = float(params.get('holding_cost_per_unit', 0) or 0)
    # PR-4 (W10) — campaign min-run lever. When > 0, a product that is set up on a line
    # in a period must produce at least `campaign_min_run` units (x ≥ min_run·y, replacing
    # the legacy x ≥ y "at least 1"). This forces CAMPAIGNS — long single-SKU runs (AAAA
    # then BBBB) instead of fragmenting a SKU across many small lots — trading more holding
    # for fewer setups/changeovers. Default 0 ⇒ floor = 1 ⇒ model byte-identical to W3.
    campaign_min_run = int(params.get('campaign_min_run', 0) or 0)
    inv = {}
    if time_phased:
        for k in range(n_prod):
            for t in range(T):
                inv[k, t] = pulp.LpVariable(f'inv_{k}_{t}', lowBound=0)
                if holding_cost_per_unit > 0:
                    obj.append(holding_cost_per_unit * inv[k, t])

    prob += pulp.lpSum(obj)

    # Constraints
    for k in range(n_prod):
        req = products[k].get('required_qty', 100)
        fy = products[k].get('yield_pct', 0.95)
        prod_route = products[k].get('routing') or []

        # C1: Total production meets requirement — use routing-derived yield if available
        if prod_route:
            # Cascaded yield across all ops (serial)
            fy_route = 1.0
            for op in prod_route:
                fy_route *= op.get('yieldPct', op.get('yield_pct', 100)) / 100.0
            fy = fy_route if fy_route > 0 else fy
        prob += pulp.lpSum(
            x[k, l, t] for l in range(n_lines) for t in range(T)
        ) * fy >= req, f"Demand_{k}"

        # C2: Can only produce on eligible lines (routing takes precedence; falls back to lines.products)
        for l in range(n_lines):
            cap_route, eligible_route, _ = _route_cap(k, l)
            if prod_route and not eligible_route:
                for t in range(T):
                    prob += x[k, l, t] == 0, f"InelRt_{k}_{l}_{t}"
            else:
                eligible = lines[l].get('products', list(range(n_prod)))
                if k not in eligible and eligible and isinstance(eligible[0], int):
                    for t in range(T):
                        prob += x[k, l, t] == 0, f"Inelig_{k}_{l}_{t}"

        # C3: Linking x and y using routing-derived per-(k,l) capacity
        for l in range(n_lines):
            cap_route, eligible_route, _ = _route_cap(k, l)
            cap = cap_route if eligible_route else lines[l].get('capacity', 50)
            # PR-4 — campaign floor per active run, capped to the route capacity (and ≥1) so
            # the min-run can never exceed what the line can physically make in a period.
            run_floor = max(1, min(campaign_min_run, cap)) if cap > 0 else 1
            for t in range(T):
                prob += x[k, l, t] <= cap * y[k, l, t], f"Link_{k}_{l}_{t}"
                prob += x[k, l, t] >= run_floor * y[k, l, t], f"MinProd_{k}_{l}_{t}"

        # C4: Completion tracking
        for l in range(n_lines):
            for t in range(T):
                prob += completion[k] >= (t + 1) * y[k, l, t], f"Comp_{k}_{l}_{t}"

    # C5: Line capacity per period.
    # (Audit #11) When per-(SKU,line) cycle times are present, bind MACHINE-HOURS:
    #     Σ_k cycle_hrs(k,l)·x[k,l,t] ≤ avail_hrs·OEE + ot[l,t]
    # The old model summed heterogeneous-cycle SKUs by a single flat unit count
    # (capacity×shifts), which is dimensionally invalid for a shared line and contradicted
    # the per-variable route cap on x. The hours basis here matches `_route_cap` exactly
    # (hrs_per_period·60·OEE / cycle_min), so the aggregate and per-product ceilings agree.
    # OT now adds genuine hours instead of a 0.5·cap/hrs_per_shift unit fudge.
    # NOTE: shift count is assumed folded into hrs_per_period (same convention as _route_cap,
    # which does not separately multiply by shifts); the no-cycle-data branch keeps the legacy
    # capacity×shifts unit fallback so older payloads are unchanged.
    for l in range(n_lines):
        cap = lines[l].get('capacity', 50)
        shifts = lines[l].get('shifts_per_day', 1)
        total_cap = cap * shifts
        line_oee = _line_oee(l, products[0]) if n_prod else 1.0
        avail_hrs = hrs_per_period * line_oee
        has_cycle = any(_cycle_min_by_sku(l, k) for k in range(n_prod))
        for t in range(T):
            if has_cycle:
                prob += pulp.lpSum(
                    ((_cycle_min_by_sku(l, k) or 0) / 60.0) * x[k, l, t] for k in range(n_prod)
                ) <= avail_hrs + ot[l, t], f"LineCapHrs_{l}_{t}"
            else:
                # Legacy flat-unit fallback (no cycle data): OT extends in units via shift conversion.
                ot_cap_extra = cap * 0.5  # OT can add 50% more
                prob += pulp.lpSum(
                    x[k, l, t] for k in range(n_prod)
                ) <= total_cap + (ot_cap_extra / max(hrs_per_shift, 1)) * ot[l, t], f"LineCap_{l}_{t}"

    # C6: Shared lines — at most ONE active product per period, with a 2nd allowed ONLY during a
    # genuine changeover period.
    # (MF-12) The old `≤ 2` permitted two products EVERY period, so the "sequential" semantics in
    # the comment were never enforced. Tie the relaxation to the changeover indicator: switch[l,t]=1
    # (which SwDet forces whenever a new product appears) lets the bound rise to 2 for the transition
    # period only; switch carries a changeover cost in the objective, so it won't be set frivolously.
    # switch is defined for t≥1, so t=0 is hard-capped at 1 (no prior product to change over from).
    for l in range(n_lines):
        if lines[l].get('type') == 'shared':
            for t in range(T):
                rhs = 1 + (switch[l, t] if (l, t) in switch else 0)
                prob += pulp.lpSum(
                    y[k, l, t] for k in range(n_prod)
                ) <= rhs, f"Shared_{l}_{t}"

    # C7: Changeover detection
    for l in range(n_lines):
        for t in range(1, T):
            for k in range(n_prod):
                # If product k was NOT on line l at t-1 but IS at t → switch
                prob += switch[l, t] >= y[k, l, t] - y[k, l, t - 1], f"SwDet_{k}_{l}_{t}"

    # R14.1 / Phase 3 · D6 — per-period org-wide labor-hours cap when 'hourly' mode is active and
    # workforce.hourly_headcount_cap > 0. Bounds Σ_l Σ_k cycle_hrs(k,l) × x[k,l,t] for each period t.
    # 40 hrs/wk regular per worker is the assumed baseline; OT vars (capped per-line) ride on top.
    if labor_cost_mode == 'hourly' and wf_hourly_headcount_cap > 0:
        org_reg_hrs_per_period = wf_hourly_headcount_cap * 40.0
        # G-P4 — resolve the per-(SKU,line) cycle from EITHER the line's cycle_time_by_sku_min OR
        # the product routing (the real payload uses routing), so the labor cap actually binds for
        # routed products. Mirrors _route_cap's bottleneck = max op cycle on this line. Used ONLY
        # here (cap>0), so the routing path stays byte-identical when no cap is set.
        def _labor_cycle_min(l, k):
            cm = _cycle_min_by_sku(l, k)
            if cm:
                return cm
            line_id = lines[l].get('id')
            cands = [float(op.get('cycleTimeMin', op.get('cycle_time_min', 0)) or 0)
                     for op in (products[k].get('routing') or []) if op.get('line_id') == line_id]
            cands = [c for c in cands if c > 0]
            return max(cands) if cands else None
        for t in range(T):
            terms = []
            for k in range(n_prod):
                for l in range(n_lines):
                    cm = _labor_cycle_min(l, k)
                    if cm is None or cm <= 0:
                        continue
                    terms.append((cm / 60.0) * x[k, l, t])
            if terms:
                # G-P4 — labor consumed ≤ regular labor budget (headcount × 40 h) PLUS overtime hours.
                # OT relaxes the cap (mirrors the per-line LineCapHrs constraint), so a TIGHT headcount
                # forces OT up to meet the hard demand rather than going straight to infeasible; with OT
                # also capped (wf_ot_cap_hrs / per-line legal cap) it then binds. Default-off (cap=0).
                prob += pulp.lpSum(terms) <= org_reg_hrs_per_period + pulp.lpSum(
                    ot[l, t] for l in range(n_lines)), f"OrgLaborHrs_{t}"

    # R15 / Phase 3 · D-OT-envelope — org-wide weekly OT envelope.
    # Bound: Σ_l ot[l,t] ≤ wf_ot_cap_hrs for every period t. Stays in addition to per-line legal cap.
    if wf_ot_cap_hrs > 0:
        for t in range(T):
            prob += pulp.lpSum(ot[l, t] for l in range(n_lines)) <= wf_ot_cap_hrs, f"OrgOTCap_{t}"

    # PR-A (W3 follow-up) — time-phased inventory balance (no backorder). Yield matches C1's
    # routing-cascaded fy exactly, so the balance and the demand ceiling agree.
    #   inv[k,t] = inv[k,t-1] (or opening_inventory at t=0) + Σ_l x[k,l,t]·fy − demand[k,t]
    #   inv[k,t] ≥ 0 (declared lowBound) ⇒ on-hand never goes negative ⇒ demand met each period.
    if time_phased:
        for k in range(n_prod):
            dbp = products[k].get('demand_by_period') or []
            fy = products[k].get('yield_pct', 0.95)
            prod_route = products[k].get('routing') or []
            if prod_route:
                fy_route = 1.0
                for op in prod_route:
                    fy_route *= op.get('yieldPct', op.get('yield_pct', 100)) / 100.0
                fy = fy_route if fy_route > 0 else fy
            opening = float(products[k].get('opening_inventory', 0) or 0)
            for t in range(T):
                d_t = float(dbp[t]) if t < len(dbp) else 0.0
                prev = inv[k, t - 1] if t > 0 else opening
                prob += inv[k, t] == prev + pulp.lpSum(
                    x[k, l, t] for l in range(n_lines)) * fy - d_t, f"InvBal_{k}_{t}"

    # Solve
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=60, gapRel=0.05)
    status = prob.solve(solver)
    solve_time = time.time() - t0

    if status != pulp.constants.LpStatusOptimal:
        return {'status': pulp.LpStatus[status], 'error': f'Solver: {pulp.LpStatus[status]}',
                'solve_time': round(solve_time, 2)}

    total_cost = pulp.value(prob.objective)

    # Extract Gantt data
    gantt = []
    product_results = []
    for k in range(n_prod):
        prod_total = 0
        prod_periods = []
        for t in range(T):
            for l in range(n_lines):
                qty = int(pulp.value(x[k, l, t]) or 0)
                if qty > 0:
                    gantt.append({
                        'product': products[k].get('name', f'P{k}'),
                        'line': lines[l].get('name', f'L{l}'),
                        'line_idx': l,
                        'period': t,
                        'quantity': qty,
                        'product_idx': k,
                    })
                    prod_total += qty
                    prod_periods.append(t)

        comp = int(pulp.value(completion[k]) or 0)
        product_results.append({
            'name': products[k].get('name', f'P{k}'),
            'required': products[k].get('required_qty', 100),
            'produced': prod_total,
            'completion_period': comp,
            'active_periods': len(prod_periods),
            'utilization': round(len(prod_periods) / max(T, 1) * 100, 1),
        })

    # Line utilization
    line_results = []
    for l in range(n_lines):
        active = sum(1 for t in range(T) if any(
            int(pulp.value(x[k, l, t]) or 0) > 0 for k in range(n_prod)))
        total_produced = sum(
            int(pulp.value(x[k, l, t]) or 0)
            for k in range(n_prod) for t in range(T))
        cap = lines[l].get('capacity', 50)
        ot_hrs = sum(pulp.value(ot[l, t]) or 0 for t in range(T))
        # T4-04 — solver-emitted OT cost breakdown so the capacity-loading panel can show real cash impact.
        ot_per_hr = line_ot_cost_per_hr(lines[l])
        ot_cost_total = round(ot_per_hr * ot_hrs, 2)
        max_ot_period = line_max_ot_per_period(lines[l])
        line_results.append({
            'name': lines[l].get('name', f'L{l}'),
            'active_periods': active,
            'utilization': round(active / max(T, 1) * 100, 1),
            'total_produced': total_produced,
            'overtime_hours': round(ot_hrs, 1),
            'overtime_cost': ot_cost_total,
            'overtime_cost_per_hr': round(ot_per_hr, 2),
            'max_ot_hrs_per_period': round(max_ot_period, 1),
            'workers_per_shift': lines[l].get('workers_per_shift', 0),
            'hourly_rate': lines[l].get('hourly_rate', 0),
            'ot_threshold_pct': lines[l].get('ot_threshold_pct', 80),
            'changeovers': sum(int(pulp.value(switch.get((l, t), 0)) or 0) for t in range(1, T)),
            # R13 Phase 1b — echo the resolved line OEE + pooled work-center membership for UI banners.
            'oee': round(float(lines[l].get('oee') or 0), 4),
            'shared_stage_ids': lines[l].get('shared_stage_ids', []),
        })

    # R15 / Phase 3 · D3 — low-utilization shutdown recommendations.
    # Post-solve heuristic (does NOT change solver math). For each (line, period) with utilization
    # below `shutdown_threshold_pct` (default 25%), compute:
    #   savings  = workers × shifts × hrs_per_period × hourly_rate              (regular-hour wage saved)
    #   rehire   = workers × hourly_rate × rehire_notice_hrs                    (2 weeks @ 40 hrs/wk default)
    #   net_gain = savings − rehire
    # Surface as `{period, line_idx, type:'shutdown', util_pct, savings, rehire_cost, net_gain}`.
    # Only emits when net_gain > 0 (i.e. the line is idle enough that paying the rehire cost still
    # comes out ahead of paying idle wages). UI can render alongside the gantt as "shut Line 2 in W12".
    shutdown_threshold_pct = float(params.get('shutdown_threshold_pct', 25) or 25)
    rehire_notice_hrs = float(params.get('rehire_notice_hrs', 80) or 80)
    shutdown_recommendations = []
    if labor_cost_mode in ('hourly', 'salaried_idle') or rehire_notice_hrs > 0:
        for l in range(n_lines):
            line = lines[l]
            workers = float(line.get('workers_per_shift', 0) or 0)
            shifts = float(line.get('shifts_per_day', 1) or 1)
            rate = float(line.get('hourly_rate', 0) or 0)
            if workers <= 0 or rate <= 0:
                continue
            line_total_cap = float(line.get('capacity', 50) or 50) * shifts
            if line_total_cap <= 0:
                continue
            # (Audit #13) Group CONSECUTIVE sub-threshold periods into one shutdown "run".
            # A shutdown pays the rehire/notice cost ONCE per run, not once per idle period.
            # The old per-period emission charged rehire on every idle week, so summing net_gain
            # across rows overstated the benefit by ~run_length×.
            per_period_savings = workers * shifts * hrs_per_period * rate  # regular wage saved / idle period
            rehire_cost = workers * rate * rehire_notice_hrs               # one-off notice/rehire per run
            runs = []  # list of (start, end_exclusive, avg_util_pct)
            cur_start = None
            util_acc = 0.0
            for t in range(T):
                produced_kt = sum(int(pulp.value(x[k, l, t]) or 0) for k in range(n_prod))
                util_pct = (produced_kt / line_total_cap) * 100 if line_total_cap > 0 else 0
                if util_pct < shutdown_threshold_pct:
                    if cur_start is None:
                        cur_start = t
                        util_acc = 0.0
                    util_acc += util_pct
                elif cur_start is not None:
                    runs.append((cur_start, t, util_acc / max(t - cur_start, 1)))
                    cur_start = None
            if cur_start is not None:
                runs.append((cur_start, T, util_acc / max(T - cur_start, 1)))
            for (start, end, avg_util) in runs:
                n_idle = end - start
                run_savings = per_period_savings * n_idle
                net_gain = run_savings - rehire_cost
                if net_gain > 0:
                    shutdown_recommendations.append({
                        'line_idx': l,
                        'line_name': line.get('name', f'L{l}'),
                        'type': 'shutdown',
                        'from_period': start,
                        'to_period': end - 1,
                        'idle_periods': n_idle,
                        'avg_util_pct': round(avg_util, 1),
                        'savings': round(run_savings, 2),
                        'rehire_cost': round(rehire_cost, 2),
                        'net_gain': round(net_gain, 2),
                    })

    # GAP-8 (move a) — sequence-dependent changeover. Post-solve, for each line compute the
    # cheapest run order over the asymmetric changeover matrix for the SKUs actually scheduled,
    # and report the true cost vs the MILP's averaged approximation. No MILP change.
    sequence_plans = []
    try:
        from .sequencing import optimal_sequence, _matrix_lookup
    except ImportError:
        try:
            from sequencing import optimal_sequence, _matrix_lookup
        except ImportError:
            optimal_sequence = None
    if optimal_sequence is not None:
        for l in range(n_lines):
            co_matrix = lines[l].get('changeover_matrix', {}) or {}
            sched_ks = [k for k in range(n_prod)
                        if any((pulp.value(x[k, l, t]) or 0) > 0 for t in range(T))]
            if len(sched_ks) < 2:
                continue
            names = [products[k].get('name', f'P{k}') for k in sched_ks]
            default_min = float(lines[l].get('changeover_mins', 30) or 30)
            seq = optimal_sequence(names, co_matrix, default_min)
            # averaged approximation for contrast (matches the MILP's mean-matrix basis)
            vals = [_matrix_lookup(co_matrix, a, b) for a in names for b in names if a != b]
            vals = [v for v in vals if v is not None]
            mean_min = (sum(vals) / len(vals)) if vals else default_min
            seq['line'] = lines[l].get('name', f'L{l}')
            seq['averaged_approx_min'] = round(mean_min * (len(names) - 1), 2)
            seq['sequence_saving_min'] = round(seq['averaged_approx_min'] - seq['total_changeover_min'], 2)
            sequence_plans.append(seq)

    # PR-A (W3 follow-up) — emit the solved per-(product, period) ending inventory so the MPS can
    # show on-hand cover tracking the demand curve (only when time_phased was requested).
    projected_inventory = []
    if time_phased and inv:
        for k in range(n_prod):
            projected_inventory.append({
                'name': products[k].get('name', f'P{k}'),
                'product_idx': k,
                'ending_inventory': [round(float(pulp.value(inv[k, t]) or 0), 1) for t in range(T)],
                'demand_by_period': [round(float(d), 1) for d in (products[k].get('demand_by_period') or [])],
            })

    # PR-4 — campaign metrics: a "run" is one (product,line,period) lot. Fewer, larger runs =
    # campaigned; many small runs = fragmented. avg_run_units exposes the setup↔holding trade.
    _total_units = sum(g['quantity'] for g in gantt)
    _n_runs = len(gantt)
    campaign_summary = {
        'min_run': campaign_min_run,
        'runs': _n_runs,
        'avg_run_units': round(_total_units / _n_runs, 1) if _n_runs else 0,
        'total_units': _total_units,
    }

    return {
        'status': 'Optimal',
        'total_cost': round(total_cost, 2),
        'time_phased': time_phased,
        'campaign': campaign_summary,
        'projected_inventory': projected_inventory,
        # GAP-8 — true sequence-dependent changeover run order per line (vs averaged MILP cost).
        'sequence_plans': sequence_plans,
        # R14.1 / Phase 3 · D6 — labor cost transparency.
        'labor_cost_mode_active': labor_cost_mode,
        'salaried_fixed_cost': round(salaried_fixed_cost, 2),
        # R15 / Phase 3 · D-OT-envelope — echo the active org OT cap so the UI can confirm it bound.
        'org_ot_cap_hrs': round(wf_ot_cap_hrs, 2),
        # R15 / Phase 3 · D3 — low-util shutdown candidates (post-solve heuristic).
        'shutdown_recommendations': shutdown_recommendations,
        'shutdown_threshold_pct': round(shutdown_threshold_pct, 1),
        'solve_time': round(solve_time, 2),
        'products': product_results,
        'lines': line_results,
        'gantt': gantt,
        'periods': T,
    }
