"""
Lot-Sizing Policies — Closed-Form + Heuristic + Evaluator
==========================================================
Each policy turns a demand forecast (list of T periods) + cost params into
an order schedule (list of T order quantities, with holding+ordering cost).

Policies covered:
  - LFL           Lot-For-Lot (no holding, 1 order per demand period)
  - EOQ           Economic Order Qty (Wilson formula, steady demand)
  - FOQ           Fixed Order Qty (user-specified q, reorder when net req)
  - POQ           Periodic Order Qty (order every N periods of demand)
  - MIN_MAX       Reorder point + max stock (continuous review, s,S)
  - EPQ           Economic Production Quantity (finite prod rate)
  - WAGNER_WHITIN Dynamic programming — optimal under deterministic demand
  - SILVER_MEAL   Heuristic: minimize avg cost/period
  - PPB           Part-Period Balancing (holding ≈ ordering)
  - LUC           Least Unit Cost heuristic
  - LTC           Least Total Cost heuristic
  - JIT           Order arrives just in time for consumption (LT-shifted LFL)
  - KANBAN        Fixed-qty pull with kanban count × qty per card

auto_select_policy(demand, params) runs them all, returns the cheapest.
"""
import math


def _simulate(orders, demand, unit_cost, ord_cost, hold_rate_weekly, init_inv=0):
    """Given an order schedule, simulate inventory and compute total cost.
    Returns dict: {total_cost, order_cost, hold_cost, prod_cost, inventory[], shortage[]}
    """
    T = len(demand)
    inv = init_inv
    hold_cost = 0.0
    order_cost = 0.0
    prod_cost = 0.0
    shortage = 0
    inv_series = []
    short_series = []
    for t in range(T):
        if orders[t] > 0:
            order_cost += ord_cost
            prod_cost += orders[t] * unit_cost
        inv += orders[t]
        d = demand[t]
        if inv >= d:
            inv -= d
            short_series.append(0)
        else:
            short_series.append(d - inv)
            shortage += d - inv
            inv = 0
        hold_cost += inv * unit_cost * hold_rate_weekly
        inv_series.append(inv)
    return {
        'total_cost': round(order_cost + hold_cost + prod_cost, 2),
        'order_cost': round(order_cost, 2),
        'hold_cost': round(hold_cost, 2),
        'prod_cost': round(prod_cost, 2),
        'inventory': inv_series,
        'shortage': short_series,
        'total_shortage': shortage,
        'num_orders': sum(1 for q in orders if q > 0),
    }


def lfl(demand, params):
    """Lot-for-Lot: each period orders exactly what it needs. No holding."""
    orders = [max(0, d) for d in demand]
    return orders, 'LFL'


def eoq(demand, params):
    """EOQ: q* = sqrt(2·D·S / (i·c)). Steady-demand assumption."""
    T = len(demand)
    total_d = sum(demand)
    avg_d = total_d / max(T, 1)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    i_annual = params.get('hold_rate_annual', 0.24)
    annual_d = avg_d * 52
    if annual_d <= 0 or c <= 0 or i_annual <= 0:
        return lfl(demand, params)
    q_star = math.sqrt(2 * annual_d * S / (i_annual * c))
    q_star = max(1, round(q_star))
    return _schedule_by_fixed_qty(demand, q_star), f'EOQ (q*={q_star})'


def foq(demand, params):
    """Fixed Order Qty — user supplies q (defaults to EOQ if absent)."""
    q = params.get('foq_qty') or 0
    if q <= 0:
        return eoq(demand, params)
    return _schedule_by_fixed_qty(demand, int(q)), f'FOQ (q={q})'


def _schedule_by_fixed_qty(demand, q):
    """Roll inventory; each time net req > 0, order q (or ceil(req/q)·q)."""
    T = len(demand)
    orders = [0] * T
    inv = 0
    for t in range(T):
        while inv < demand[t]:
            orders[t] += q
            inv += q
        inv -= demand[t]
    return orders


def poq(demand, params):
    """Periodic Order Qty: order every N periods to cover next N periods."""
    T = len(demand)
    # Derive N from EOQ as a starting point (POQ = EOQ / avg demand)
    total_d = sum(demand)
    avg_d = max(total_d / max(T, 1), 0.1)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    i_annual = params.get('hold_rate_annual', 0.24)
    annual_d = avg_d * 52
    if annual_d > 0 and c > 0 and i_annual > 0:
        eoq_q = math.sqrt(2 * annual_d * S / (i_annual * c))
        N = max(1, round(eoq_q / avg_d))
    else:
        N = int(params.get('poq_periods', 2))
    N = min(N, T)
    orders = [0] * T
    t = 0
    while t < T:
        orders[t] = sum(demand[t:t + N])
        t += N
    return orders, f'POQ (every {N} weeks)'


def min_max(demand, params):
    """(s,S) policy: reorder when inv ≤ s, order up to S.
    s = z·σ·sqrt(LT) + μ·LT; S = s + EOQ."""
    T = len(demand)
    mu = sum(demand) / max(T, 1)
    sigma = (sum((d - mu) ** 2 for d in demand) / max(T, 1)) ** 0.5
    lt = params.get('lead_time', 1)
    z = params.get('z', 1.645)
    s = z * sigma * math.sqrt(max(lt, 1)) + mu * lt
    # S target: s + EOQ lot
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    i_annual = params.get('hold_rate_annual', 0.24)
    eoq_q = math.sqrt(max(2 * mu * 52 * S / max(i_annual * c, 0.01), 1))
    S_target = s + eoq_q
    orders = [0] * T
    # Start with init_inv from params (default 0); first tick will trigger order up to S
    inv = params.get('init_inv', 0)
    for t in range(T):
        if inv <= s:
            q = max(0, round(S_target - inv))
            orders[t] = q
            inv += q
        inv = max(0, inv - demand[t])
    return orders, f'Min-Max (s={round(s,1)}, S={round(S_target,1)})'


def epq(demand, params):
    """Economic Production Quantity — accounts for finite production rate p.
    q* = sqrt(2·D·S / (i·c) · p/(p-d))"""
    T = len(demand)
    avg_d = sum(demand) / max(T, 1)
    p_rate = params.get('prod_rate', avg_d * 3)  # weekly production capacity
    if p_rate <= avg_d:
        return eoq(demand, params)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    i_annual = params.get('hold_rate_annual', 0.24)
    D_ann = avg_d * 52
    if D_ann <= 0 or c <= 0 or i_annual <= 0:
        return lfl(demand, params)
    q_star = math.sqrt(2 * D_ann * S / (i_annual * c) * p_rate / (p_rate - avg_d))
    q_star = max(1, round(q_star))
    return _schedule_by_fixed_qty(demand, q_star), f'EPQ (q*={q_star})'


def wagner_whitin(demand, params):
    """Dynamic programming — OPTIMAL under deterministic demand.
    Builds order schedule covering periods [i..j] via backward recursion.
    F[t] = min cost to plan periods t..T-1. j is the next order period
    after an order at t (so order at t covers demand[t..j-1])."""
    T = len(demand)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    i_w = params.get('hold_rate_weekly', 0.24 / 52)
    h = c * i_w
    INF = float('inf')
    F = [0.0] * (T + 1)          # F[T] = 0 (no cost after horizon)
    next_order = [T] * T
    for t in range(T - 1, -1, -1):
        best = INF
        best_j = t + 1
        # Try ordering at t covering up to period j-1 (j in [t+1..T])
        for j in range(t + 1, T + 1):
            qty = sum(demand[t:j])
            hold = sum(demand[t + k] * h * k for k in range(j - t))
            cost = (S + hold if qty > 0 else 0) + F[j]
            if cost < best:
                best = cost
                best_j = j
        F[t] = best
        next_order[t] = best_j
    # Walk forward
    orders = [0] * T
    t = 0
    while t < T:
        j = next_order[t]
        orders[t] = sum(demand[t:j])
        t = j if j > t else t + 1
    return orders, 'Wagner-Whitin (DP-optimal)'


def silver_meal(demand, params):
    """Heuristic: at each order point, extend coverage while avg cost/period drops."""
    T = len(demand)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    h = c * params.get('hold_rate_weekly', 0.24 / 52)
    orders = [0] * T
    t = 0
    while t < T:
        best_j = t + 1
        best_avg = float('inf')
        qty_so_far = 0
        hold_so_far = 0
        for j in range(t + 1, T + 1):
            k = j - 1 - t
            qty_so_far += demand[j - 1]
            hold_so_far += demand[j - 1] * h * k
            avg = (S + hold_so_far) / (j - t)
            if avg < best_avg:
                best_avg = avg
                best_j = j
            else:
                break  # avg starting to rise → stop
        orders[t] = sum(demand[t:best_j])
        t = best_j
    return orders, 'Silver-Meal'


def ppb(demand, params):
    """Part-Period Balancing: extend coverage until holding ≈ ordering cost."""
    T = len(demand)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    h = c * params.get('hold_rate_weekly', 0.24 / 52)
    epp = S / max(h, 1e-9)  # economic part-periods
    orders = [0] * T
    t = 0
    while t < T:
        cum_pp = 0
        j = t
        while j < T:
            k = j - t
            cum_pp += demand[j] * k
            if cum_pp > epp:
                break
            j += 1
        best_j = max(j, t + 1)
        orders[t] = sum(demand[t:best_j])
        t = best_j
    return orders, 'Part-Period Balancing'


def luc(demand, params):
    """Least Unit Cost: extend coverage while unit cost drops."""
    T = len(demand)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    h = c * params.get('hold_rate_weekly', 0.24 / 52)
    orders = [0] * T
    t = 0
    while t < T:
        best_j = t + 1
        best_unit = float('inf')
        qty_so_far = 0
        hold_so_far = 0
        for j in range(t + 1, T + 1):
            k = j - 1 - t
            qty_so_far += demand[j - 1]
            hold_so_far += demand[j - 1] * h * k
            if qty_so_far == 0:
                continue
            unit = (S + hold_so_far) / qty_so_far
            if unit < best_unit:
                best_unit = unit
                best_j = j
            else:
                break
        orders[t] = sum(demand[t:best_j])
        t = best_j
    return orders, 'Least Unit Cost'


def ltc(demand, params):
    """Least Total Cost: extend coverage while holding < ordering cost."""
    T = len(demand)
    S = params.get('ord_cost', 50)
    c = params.get('unit_cost', 1)
    h = c * params.get('hold_rate_weekly', 0.24 / 52)
    orders = [0] * T
    t = 0
    while t < T:
        cum_hold = 0
        best_j = t + 1
        for j in range(t + 1, T + 1):
            k = j - 1 - t
            cum_hold += demand[j - 1] * h * k
            if cum_hold > S:
                break
            best_j = j
        orders[t] = sum(demand[t:best_j])
        t = max(best_j, t + 1)
    return orders, 'Least Total Cost'


def jit(demand, params):
    """JIT = LFL, offset by lead time (treated same as LFL here since LT is
    handled by procurement solver's arrive_t)."""
    return lfl(demand, params)[0], 'JIT (LFL-shifted)'


def kanban(demand, params):
    """Kanban: fixed qty (kanban_size) per card, triggered when inv ≤ reorder pt."""
    kanban_size = params.get('kanban_size') or 0
    if kanban_size <= 0:
        # Default: container size ≈ avg demand per period
        T = len(demand)
        kanban_size = max(1, round(sum(demand) / max(T, 1)))
    return _schedule_by_fixed_qty(demand, int(kanban_size)), f'Kanban (card={kanban_size})'


POLICIES = {
    'lfl': lfl,
    'eoq': eoq,
    'foq': foq,
    'poq': poq,
    'minmax': min_max,
    'epq': epq,
    'ww': wagner_whitin,
    'silvermeal': silver_meal,
    'ppb': ppb,
    'luc': luc,
    'ltc': ltc,
    'jit': jit,
    'kanban': kanban,
}


def run_policy(policy_key, demand, params):
    """Run one policy and return its simulated cost breakdown."""
    fn = POLICIES.get(policy_key)
    if not fn:
        return {'error': f'Unknown policy: {policy_key}'}
    try:
        orders, label = fn(list(demand), params)
    except Exception as e:
        return {'error': f'{policy_key} failed: {e}'}
    sim = _simulate(
        orders,
        demand,
        unit_cost=params.get('unit_cost', 1),
        ord_cost=params.get('ord_cost', 50),
        hold_rate_weekly=params.get('hold_rate_weekly', 0.24 / 52),
        init_inv=params.get('init_inv', 0),
    )
    return {
        'policy': policy_key,
        'label': label,
        'orders': orders,
        **sim,
    }


def auto_select_policy(demand, params):
    """Run ALL policies, pick cheapest that meets service constraint.
    Returns {winner_key, winner_result, leaderboard[]}.
    """
    results = []
    max_short = int(params.get('max_shortage', 0))
    for key in POLICIES:
        r = run_policy(key, demand, params)
        if r.get('error'):
            continue
        r['feasible'] = r['total_shortage'] <= max_short
        results.append(r)
    # Rank: feasible first, then by total_cost
    results.sort(key=lambda x: (not x['feasible'], x['total_cost']))
    winner = results[0] if results else None
    return {
        'winner_key': winner['policy'] if winner else None,
        'winner_label': winner['label'] if winner else None,
        'winner': winner,
        'leaderboard': [
            {
                'policy': r['policy'],
                'label': r['label'],
                'total_cost': r['total_cost'],
                'order_cost': r['order_cost'],
                'hold_cost': r['hold_cost'],
                'num_orders': r['num_orders'],
                'shortage': r['total_shortage'],
                'feasible': r['feasible'],
            }
            for r in results
        ],
    }


def solve_lot_sizing(data):
    """API entry — runs one policy or auto-select.
    Input: {demand[], policy, unit_cost, ord_cost, hold_rate_annual, lead_time, ...}
    Output: leaderboard (if auto) + best schedule."""
    demand = data.get('demand', [])
    if not demand:
        return {'error': 'No demand provided'}
    policy = (data.get('policy') or 'auto').lower()
    params = {
        'unit_cost': data.get('unit_cost', 1),
        'ord_cost': data.get('ord_cost', 50),
        'hold_rate_annual': data.get('hold_rate_annual', 0.24),
        'hold_rate_weekly': data.get('hold_rate_annual', 0.24) / 52,
        'lead_time': data.get('lead_time', 1),
        'z': data.get('z', 1.645),
        'foq_qty': data.get('foq_qty', 0),
        'poq_periods': data.get('poq_periods', 2),
        'kanban_size': data.get('kanban_size', 0),
        'prod_rate': data.get('prod_rate', 0),
        'init_inv': data.get('init_inv', 0),
        'max_shortage': data.get('max_shortage', 0),
    }
    if policy == 'auto':
        return auto_select_policy(demand, params)
    return run_policy(policy, demand, params)
