"""
Line-Capacity Shadow-Price LP (PL-A · W4 follow-up)
===================================================
W4's "Line Capacity Pressure" card ranks lines by *utilization vs registry cap* — an
honest pressure signal, but not a ₹ marginal value. This module gives the real one:
the dual price of each line's capacity constraint, i.e. how many ₹ of contribution
margin one extra unit of that line's monthly capacity would unlock.

It is a small, well-posed **continuous LP** (so the duals are valid — unlike a MILP's
`.pi`, which the aggregate/production MILPs cannot give):

  variables  prod[k, l] ≥ 0   units of finished SKU k built on line l (eligible pairs)
             short[k]   ≥ 0   unmet demand of SKU k (lost sales)
  minimize   Σ cost[k, l]·prod[k, l] + Σ lost_margin[k]·short[k]
  s.t.       Σ_l prod[k, l] + short[k] = demand[k]      (meet demand or lose the margin)   → ρ_k
             Σ_k prod[k, l]            ≤ cap[l]         (line capacity, monthly)           → π_l

The capacity dual π_l is the shadow price: if line l is slack, π_l = 0 (its honest value
today, given TPAC volumes); once demand pressures it, π_l rises toward the lost margin of
the cheapest SKU it would otherwise have to short — the exact ₹ that justifies expanding
that line. Capital (W5 F-8) consumes this as `capacity_shadow_price`.

Default eligibility is "each SKU on its assigned line only" (mirrors the production routing
pins); pass `eligible_lines` per SKU to let demand shift across lines.
"""
import pulp
import time


def solve_linecap(data):
    t0 = time.time()
    lines = data.get('lines', []) or []
    skus = data.get('skus', []) or []
    params = data.get('params', {}) or {}
    default_margin = float(params.get('lost_margin_per_unit', 1000) or 1000)

    n_l = len(lines)
    if not n_l or not skus:
        return {'error': 'Provide lines[] and skus[]'}

    line_id = [l.get('id', f'L{i}') for i, l in enumerate(lines)]
    line_name = [l.get('name', line_id[i]) for i, l in enumerate(lines)]
    cap = [max(0.0, float(l.get('cap', 0) or 0)) for l in lines]
    id_to_idx = {line_id[i]: i for i in range(n_l)}

    prob = pulp.LpProblem('LineCapacity', pulp.LpMinimize)

    prod = {}        # (k, l) -> var
    short = {}       # k -> var
    elig = {}        # k -> list of eligible line indices
    cost = {}        # (k, l) -> unit cost
    demand = []
    margin = []
    names = []
    for k, s in enumerate(skus):
        names.append(s.get('name', f'SKU{k}'))
        demand.append(max(0.0, float(s.get('demand', 0) or 0)))
        margin.append(float(s.get('lost_margin_per_unit', default_margin) or default_margin))
        # Eligibility: explicit list, else the assigned line, else all lines.
        el = s.get('eligible_lines')
        if el:
            idxs = [id_to_idx[x] for x in el if x in id_to_idx]
        elif s.get('line') in id_to_idx:
            idxs = [id_to_idx[s['line']]]
        else:
            idxs = list(range(n_l))
        if not idxs:
            idxs = list(range(n_l))
        elig[k] = idxs
        cmap = s.get('cost_per_unit') or {}
        for l in idxs:
            prod[(k, l)] = pulp.LpVariable(f'p_{k}_{l}', lowBound=0)
            cost[(k, l)] = float(cmap.get(line_id[l], cmap.get(str(l), 0)) or 0)
        short[k] = pulp.LpVariable(f's_{k}', lowBound=0)

    prob += (pulp.lpSum(cost[(k, l)] * prod[(k, l)] for (k, l) in prod)
             + pulp.lpSum(margin[k] * short[k] for k in range(len(skus)))), 'Total_Cost'

    # Demand balance (= constraint so short absorbs any unmet units).
    for k in range(len(skus)):
        prob += (pulp.lpSum(prod[(k, l)] for l in elig[k]) + short[k]
                 == demand[k]), f'Demand_{k}'

    # Line capacity — the constraint whose dual we want.
    cap_con = {}
    for l in range(n_l):
        c = prob.addConstraint(
            pulp.lpSum(prod[(k, l)] for k in range(len(skus)) if (k, l) in prod) <= cap[l],
            f'Cap_{l}')
        cap_con[l] = f'Cap_{l}'

    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]

    line_rows = []
    any_binding = False
    for l in range(n_l):
        load = sum(pulp.value(prod[(k, l)]) or 0 for k in range(len(skus)) if (k, l) in prod)
        con = prob.constraints.get(cap_con[l])
        pi = getattr(con, 'pi', None) if con is not None else None
        slack = getattr(con, 'slack', None) if con is not None else None
        # PuLP reports the dual with the sign of a ≤ constraint in a min problem; report
        # the magnitude as a positive ₹/unit "value of one more unit of capacity".
        shadow = round(abs(float(pi)), 2) if pi is not None else 0.0
        binding = cap[l] > 0 and shadow > 1e-6
        any_binding = any_binding or binding
        line_rows.append({
            'line_id': line_id[l],
            'line': line_name[l],
            'cap': round(cap[l], 1),
            'load': round(load, 1),
            'util': round(load / cap[l] * 100, 1) if cap[l] > 0 else 0.0,
            'slack': round(float(slack), 1) if slack is not None else round(cap[l] - load, 1),
            'shadow_price': shadow,
            'binding': binding,
        })

    total_short = sum(pulp.value(short[k]) or 0 for k in range(len(skus)))
    sku_short = [{'name': names[k], 'short': round(float(pulp.value(short[k]) or 0), 1)}
                 for k in range(len(skus)) if (pulp.value(short[k]) or 0) > 1e-6]

    return {
        'status': status,
        'lines': line_rows,
        'any_binding': any_binding,
        'total_demand': round(sum(demand), 1),
        'total_capacity': round(sum(cap), 1),
        'unmet_demand': round(total_short, 1),
        'sku_shortfalls': sku_short,
        'lost_margin_per_unit_default': default_margin,
        'solve_time': round(time.time() - t0, 3),
    }
