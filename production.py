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
    ot_cost = params.get('overtime_cost_per_hr', 50)
    hrs_per_shift = params.get('hours_per_shift', 8)
    makespan_weight = params.get('makespan_weight', 0.1)

    n_prod = len(products)
    n_lines = len(lines) if lines else 1

    if not n_prod:
        return {'error': 'No products'}

    # If no lines defined, create a default shared line
    if not lines:
        lines = [{'id': 'line1', 'name': 'Line 1', 'capacity': 50,
                   'type': 'shared', 'products': list(range(n_prod))}]
        n_lines = 1

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

    # Helper — for each (product, line) compute the effective capacity per period
    # based on routing (bottleneck op) when routing is defined, else fall back to line capacity.
    def _route_cap(k, l):
        """Return (units_per_period, eligible_bool, route_yield)."""
        prod = products[k]
        route = prod.get('routing') or []
        line_id = lines[l].get('id', f'line{l}')
        if not route:
            return lines[l].get('capacity', 50), True, prod.get('yield_pct', 0.95)
        # Ops assigned to this line
        ops_on_line = [op for op in route if op.get('line_id') == line_id or op.get('lineId') == line_id]
        if not ops_on_line:
            # line isn't part of this product's routing → ineligible
            return 0, False, 0
        # Bottleneck op on this line — lowest throughput
        hrs_per_period = params.get('hrs_per_period', 40)  # weekly hrs available
        oee = prod.get('oee', 0.85 * 0.92 * 0.98)
        min_per_period = hrs_per_period * 60 * oee
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

    for l in range(n_lines):
        for t in range(T):
            ot[l, t] = pulp.LpVariable(f'ot_{l}_{t}', 0, hrs_per_shift)

    # Objective: minimize setup + overtime + makespan
    obj = []
    for k in range(n_prod):
        setup_cost = products[k].get('setup_cost', 50)
        for l in range(n_lines):
            for t in range(T):
                obj.append(setup_cost * y[k, l, t])

    # Changeover cost
    changeover_cost = params.get('changeover_cost', 100)
    for l in range(n_lines):
        for t in range(1, T):
            obj.append(changeover_cost * switch[l, t])

    # Overtime cost
    for l in range(n_lines):
        for t in range(T):
            obj.append(ot_cost * ot[l, t])

    # Makespan penalty (encourage finishing early)
    for k in range(n_prod):
        obj.append(makespan_weight * completion[k])

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
            for t in range(T):
                prob += x[k, l, t] <= cap * y[k, l, t], f"Link_{k}_{l}_{t}"
                prob += x[k, l, t] >= y[k, l, t], f"MinProd_{k}_{l}_{t}"

        # C4: Completion tracking
        for l in range(n_lines):
            for t in range(T):
                prob += completion[k] >= (t + 1) * y[k, l, t], f"Comp_{k}_{l}_{t}"

    # C5: Line capacity per period (sum across products)
    for l in range(n_lines):
        cap = lines[l].get('capacity', 50)
        shifts = lines[l].get('shifts_per_day', 1)
        total_cap = cap * shifts
        for t in range(T):
            # Regular capacity + overtime extension
            ot_cap_extra = cap * 0.5  # OT can add 50% more
            prob += pulp.lpSum(
                x[k, l, t] for k in range(n_prod)
            ) <= total_cap + (ot_cap_extra / max(hrs_per_shift, 1)) * ot[l, t], f"LineCap_{l}_{t}"

    # C6: Shared lines — max 1 active product per period (optional for sequential mode)
    for l in range(n_lines):
        if lines[l].get('type') == 'shared':
            for t in range(T):
                prob += pulp.lpSum(
                    y[k, l, t] for k in range(n_prod)
                ) <= 2, f"Shared_{l}_{t}"  # allow 2 for changeover periods

    # C7: Changeover detection
    for l in range(n_lines):
        for t in range(1, T):
            for k in range(n_prod):
                # If product k was NOT on line l at t-1 but IS at t → switch
                prob += switch[l, t] >= y[k, l, t] - y[k, l, t - 1], f"SwDet_{k}_{l}_{t}"

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
        line_results.append({
            'name': lines[l].get('name', f'L{l}'),
            'active_periods': active,
            'utilization': round(active / max(T, 1) * 100, 1),
            'total_produced': total_produced,
            'overtime_hours': round(ot_hrs, 1),
            'changeovers': sum(int(pulp.value(switch.get((l, t), 0)) or 0) for t in range(1, T)),
        })

    return {
        'status': 'Optimal',
        'total_cost': round(total_cost, 2),
        'solve_time': round(solve_time, 2),
        'products': product_results,
        'lines': line_results,
        'gantt': gantt,
        'periods': T,
    }
