"""
Aggregate Production Planning / S&OP — multi-period LP (PuLP / CBC)
===================================================================
GAP-0 (IMPROVEMENTS.md): the missing middle tier between the single-period
profit-mix LP and weekly production scheduling.

profitmix.py's decision variable is a single scalar per SKU with NO time index
(`q[k]`), so `demand_mode='seasonal'` cannot actually pre-build — a single-period
LP has no buckets to carry inventory across. This module IS the buckets: the
classic Hax–Meal / Holt–Modigliani–Muth–Simon aggregate planning model.

It aggregates the SKU forecasts into one capacity-equivalent family (weighted by
labor content), then solves the level-vs-chase tradeoff over monthly buckets:

  minimize  Σ_t [ reg·P_t + ot·O_t + hold·I_t + back·B_t
                  + hire·H_t + fire·F_t + wage·W_t ]
  s.t.   inventory balance:  I_t − B_t = (I_{t-1} − B_{t-1}) + P_t + O_t − D_t
         workforce balance:  W_t = W_{t-1} + H_t − F_t
         regular capacity:   P_t ≤ rate · W_t
         overtime capacity:  O_t ≤ ot_frac · rate · W_t
         safety stock:       I_t ≥ ss_t          (optional)
         ending target:      I_T ≥ end_target     (optional)
         workforce bounds, non-negativity.

This is where seasonal build-ahead and level-vs-chase strategy actually live, and
it becomes the coherent quantity source that feeds disaggregation → procurement →
production (GAP-2 wires that loop; this module just produces the plan).

Outputs are LP-grade: per-period plan, cost breakdown, a strategy classification
(level / chase / hybrid) derived from the realized workforce-vs-inventory
variability, shadow prices on the capacity rows (the marginal value of one more
worker-period — the hook GAP-5 uses to justify endogenous capacity), and a
proportional per-SKU disaggregation of the aggregate plan.
"""
import pulp
import time


def _num(v, default=0.0):
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def solve_aggregate(data):
    """Solve the aggregate production plan. See module docstring for the model.

    data = {
      'products': [{'name', 'forecast':[monthly units], 'labor_hours_per_unit'?}],
      'params': {
         'periods'?,                       # default = max forecast length
         'init_inventory'?, 'init_workforce'?,
         'rate_per_worker'?,               # aggregate units per worker per period
         'reg_cost_per_unit'?, 'ot_cost_per_unit'?,
         'holding_cost_per_unit'?,         # per unit per period
         'backorder_cost_per_unit'?, 'allow_backorder'?,
         'hire_cost'?, 'fire_cost'?, 'wage_per_worker'?,
         'max_ot_pct'?,                    # overtime cap as fraction of regular cap (default 0.25)
         'min_workforce'?, 'max_workforce'?,
         'safety_stock'? (scalar or per-period list),
         'ending_inventory_target'?,
         'integer_workforce'?,             # round headcount to integers (MILP); default False
      }
    }
    """
    t0 = time.time()
    products = data.get('products', []) or []
    params = data.get('params', {}) or {}
    if not products:
        return {'error': 'No products'}

    # ── Aggregate the SKU forecasts into one capacity-equivalent family ──
    # Weight each SKU's units by its labor content so the aggregate "unit" is a
    # consistent capacity-equivalent. The rate_per_worker is expressed in these
    # equivalent units. Default weight 1.0 → aggregate unit == physical unit.
    forecasts = []
    weights = []
    for p in products:
        fc = [max(0.0, _num(v)) for v in (p.get('forecast', []) or [])]
        forecasts.append(fc)
        weights.append(max(0.0, _num(p.get('labor_hours_per_unit', 1.0), 1.0)) or 1.0)

    T = int(params.get('periods', 0) or 0)
    if T <= 0:
        T = max((len(fc) for fc in forecasts), default=0)
    if T <= 0:
        return {'error': 'No forecast periods'}

    # Per-period aggregate demand (labor-weighted equivalent units) + each SKU's
    # share of the raw physical demand (for proportional disaggregation later).
    agg_demand = [0.0] * T
    phys_demand = [0.0] * T
    sku_phys = [[0.0] * T for _ in products]
    for k, fc in enumerate(forecasts):
        for t in range(T):
            v = fc[t] if t < len(fc) else (fc[-1] if fc else 0.0)
            sku_phys[k][t] = v
            agg_demand[t] += v * weights[k]
            phys_demand[t] += v

    # ── Cost / capacity parameters ──
    init_inv = _num(params.get('init_inventory', 0))
    init_wf = _num(params.get('init_workforce', 0))
    rate = _num(params.get('rate_per_worker', 0))
    reg_cost = _num(params.get('reg_cost_per_unit', 0))
    ot_cost = _num(params.get('ot_cost_per_unit', reg_cost * 1.5 if reg_cost else 0))
    hold_cost = _num(params.get('holding_cost_per_unit', 0))
    allow_back = bool(params.get('allow_backorder', True))
    back_cost = _num(params.get('backorder_cost_per_unit', 0))
    hire_cost = _num(params.get('hire_cost', 0))
    fire_cost = _num(params.get('fire_cost', 0))
    wage = _num(params.get('wage_per_worker', 0))
    max_ot_pct = _num(params.get('max_ot_pct', 0.25))
    min_wf = _num(params.get('min_workforce', 0))
    max_wf = params.get('max_workforce', None)
    max_wf = _num(max_wf) if max_wf not in (None, '') else None
    end_target = params.get('ending_inventory_target', None)
    end_target = _num(end_target) if end_target not in (None, '') else None
    integer_wf = bool(params.get('integer_workforce', False))

    ss_param = params.get('safety_stock', 0)
    if isinstance(ss_param, (list, tuple)):
        safety = [_num(ss_param[t]) if t < len(ss_param) else 0.0 for t in range(T)]
    else:
        safety = [_num(ss_param)] * T

    # If no production rate is given, derive a feasible one from peak demand and
    # initial workforce so the model isn't trivially infeasible on a sparse payload.
    if rate <= 0:
        peak = max(agg_demand) if agg_demand else 0.0
        rate = (peak / init_wf) if init_wf > 0 else max(peak, 1.0)

    cat = 'Integer' if integer_wf else 'Continuous'
    prob = pulp.LpProblem('Aggregate_Plan', pulp.LpMinimize)

    P = {t: pulp.LpVariable(f'P_{t}', 0) for t in range(T)}          # regular production
    O = {t: pulp.LpVariable(f'O_{t}', 0) for t in range(T)}          # overtime production
    I = {t: pulp.LpVariable(f'I_{t}', 0) for t in range(T)}          # ending inventory
    B = {t: pulp.LpVariable(f'B_{t}', 0) for t in range(T)}          # ending backorder
    W = {t: pulp.LpVariable(f'W_{t}', lowBound=min_wf, upBound=max_wf, cat=cat) for t in range(T)}
    H = {t: pulp.LpVariable(f'H_{t}', 0, cat=cat) for t in range(T)}  # hires
    F = {t: pulp.LpVariable(f'F_{t}', 0, cat=cat) for t in range(T)}  # fires

    if not allow_back:
        for t in range(T):
            B[t].upBound = 0

    # ── Objective ──
    prob += pulp.lpSum(
        reg_cost * P[t] + ot_cost * O[t] + hold_cost * I[t] + back_cost * B[t]
        + hire_cost * H[t] + fire_cost * F[t] + wage * W[t]
        for t in range(T)
    ), 'Total_Cost'

    # ── Constraints ──
    cap_rows = {}   # capacity constraint names (for shadow prices)
    for t in range(T):
        prev_i = init_inv if t == 0 else I[t - 1]
        prev_b = 0 if t == 0 else B[t - 1]
        prev_w = init_wf if t == 0 else W[t - 1]

        # Inventory balance: net stock position carried + made − demanded
        prob += (I[t] - B[t]) == (prev_i - prev_b) + P[t] + O[t] - agg_demand[t], f'InvBal_{t}'
        # Workforce balance
        prob += W[t] == prev_w + H[t] - F[t], f'WfBal_{t}'
        # Regular capacity tied to workforce
        rc = f'RegCap_{t}'
        prob += P[t] <= rate * W[t], rc
        cap_rows[f'Regular capacity P{t+1}'] = rc
        # Overtime capacity
        prob += O[t] <= max_ot_pct * rate * W[t], f'OtCap_{t}'
        # Safety stock floor
        if safety[t] > 0:
            prob += I[t] >= safety[t], f'SafetyStock_{t}'

    if end_target is not None:
        prob += I[T - 1] >= end_target, 'EndingInventory'

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=30)
    status = prob.solve(solver)
    solve_time = time.time() - t0

    if status != pulp.constants.LpStatusOptimal:
        return {'status': pulp.LpStatus[status],
                'error': f'Solver: {pulp.LpStatus[status]}',
                'solve_time': round(solve_time, 2)}

    # ── Extract per-period plan ──
    def v(x):
        return pulp.value(x) or 0.0

    periods = []
    cost_reg = cost_ot = cost_hold = cost_back = cost_hire = cost_fire = cost_wage = 0.0
    for t in range(T):
        p_reg, p_ot = v(P[t]), v(O[t])
        inv, bk = v(I[t]), v(B[t])
        wf, hi, fi = v(W[t]), v(H[t]), v(F[t])
        c_reg = reg_cost * p_reg
        c_ot = ot_cost * p_ot
        c_hold = hold_cost * inv
        c_back = back_cost * bk
        c_hire = hire_cost * hi
        c_fire = fire_cost * fi
        c_wage = wage * wf
        cost_reg += c_reg; cost_ot += c_ot; cost_hold += c_hold; cost_back += c_back
        cost_hire += c_hire; cost_fire += c_fire; cost_wage += c_wage
        periods.append({
            'period': t + 1,
            'demand': round(agg_demand[t], 1),
            'regular_production': round(p_reg, 1),
            'overtime_production': round(p_ot, 1),
            'inventory': round(inv, 1),
            'backorder': round(bk, 1),
            'workforce': round(wf, 2),
            'hires': round(hi, 2),
            'fires': round(fi, 2),
            'period_cost': round(c_reg + c_ot + c_hold + c_back + c_hire + c_fire + c_wage, 2),
        })

    total_cost = pulp.value(prob.objective)

    # ── Strategy classification: level vs chase ──
    # A "level" plan holds workforce ~flat and absorbs demand swings with inventory;
    # a "chase" plan flexes workforce to track demand and carries little inventory.
    # Classify by which lever varies more, relative to its own mean.
    wf_series = [pr['workforce'] for pr in periods]
    inv_series = [pr['inventory'] for pr in periods]
    total_hire_fire = cost_hire + cost_fire

    def _cv(series):
        n = len(series)
        if n == 0:
            return 0.0
        mean = sum(series) / n
        if mean <= 1e-9:
            return 0.0
        var = sum((s - mean) ** 2 for s in series) / n
        return (var ** 0.5) / mean

    wf_cv = _cv(wf_series)
    inv_cv = _cv(inv_series)
    if wf_cv < 0.05 and inv_cv >= 0.05:
        strategy = 'level'
        strategy_note = 'Workforce held ~flat; demand swings absorbed by inventory build-ahead.'
    elif wf_cv >= 0.05 and inv_cv < wf_cv:
        strategy = 'chase'
        strategy_note = 'Workforce flexed to track demand; minimal inventory carried.'
    elif wf_cv < 0.05 and inv_cv < 0.05:
        strategy = 'level'
        strategy_note = 'Stable plan — neither workforce nor inventory varies materially.'
    else:
        strategy = 'hybrid'
        strategy_note = 'Mixed: partial workforce flex plus partial inventory build.'

    # Seasonal build-ahead detector: inventory peaks BEFORE the demand peak.
    peak_demand_t = max(range(T), key=lambda t: agg_demand[t]) if T else 0
    peak_inv_t = max(range(T), key=lambda t: inv_series[t]) if T else 0
    prebuild = bool(T and peak_inv_t < peak_demand_t and inv_series[peak_inv_t] > 1e-6)

    # ── Shadow prices on capacity rows (marginal value of one more worker-period). ──
    # This is the hook GAP-5 uses: a binding regular-capacity dual means added
    # capacity (a new shift / line) would pay back at that rate.
    shadow_prices = []
    for label, cname in cap_rows.items():
        c = prob.constraints.get(cname)
        if c is None:
            continue
        dual = c.pi if getattr(c, 'pi', None) is not None else 0
        slack = c.slack if getattr(c, 'slack', None) is not None else None
        binding = slack is not None and abs(slack) < 0.01
        if abs(dual) < 1e-6 and not binding:
            continue  # only surface meaningful rows
        shadow_prices.append({
            'constraint': label,
            'shadow_price': round(dual, 3),
            'slack': round(slack, 2) if slack is not None else None,
            'binding': binding,
        })

    # ── Proportional per-SKU disaggregation of the aggregate plan ──
    # Split the aggregate net production (reg+ot) back to SKUs by each SKU's share
    # of that period's physical demand. This is the quantity vector GAP-2 forwards.
    sku_plans = []
    for k, p in enumerate(products):
        weekly = []
        for t in range(T):
            agg_made = periods[t]['regular_production'] + periods[t]['overtime_production']
            share = (sku_phys[k][t] / phys_demand[t]) if phys_demand[t] > 1e-9 else (1.0 / len(products))
            # Convert aggregate (labor-weighted) units back to physical SKU units.
            phys_made = (agg_made * share) / max(weights[k], 1e-9)
            weekly.append(round(phys_made, 1))
        sku_plans.append({
            'name': p.get('name', f'P{k}'),
            'monthly_plan': weekly,
            'total_planned': round(sum(weekly), 1),
            'total_demand': round(sum(sku_phys[k]), 1),
        })

    return {
        'status': 'Optimal',
        'periods': periods,
        'total_cost': round(total_cost, 2),
        'cost_breakdown': {
            'regular_production': round(cost_reg, 2),
            'overtime_production': round(cost_ot, 2),
            'holding': round(cost_hold, 2),
            'backorder': round(cost_back, 2),
            'hiring': round(cost_hire, 2),
            'firing': round(cost_fire, 2),
            'wages': round(cost_wage, 2),
            'hire_fire_total': round(total_hire_fire, 2),
        },
        'strategy': strategy,
        'strategy_note': strategy_note,
        'seasonal_prebuild': prebuild,
        'workforce_cv': round(wf_cv, 4),
        'inventory_cv': round(inv_cv, 4),
        'final_workforce': round(wf_series[-1], 2) if wf_series else 0,
        'peak_inventory': round(max(inv_series), 1) if inv_series else 0,
        'total_backorder': round(sum(pr['backorder'] for pr in periods), 1),
        'shadow_prices': shadow_prices,
        'sku_plans': sku_plans,
        'rate_per_worker': round(rate, 3),
        'solve_time': round(solve_time, 3),
    }
