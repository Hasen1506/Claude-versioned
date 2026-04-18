"""
Procurement & Production MILP Solver
=====================================
Minimizes total supply chain cost:
  setup + FG holding + production + expiry + shortage + RM purchase + RM holding + RM ordering

Decision variables:
  p[k,t]  = units of product k produced in period t
  r[i,t]  = units of raw material i ordered in period t
  y[k,t]  = binary: whether product k is produced in period t
  o[i,t]  = binary: whether raw material i is ordered in period t
"""
import pulp
import math
import time
import numpy as np

try:
    from .lot_sizing import run_policy, auto_select_policy
except ImportError:
    from lot_sizing import run_policy, auto_select_policy


def solve_procurement(data):
    """Main entry point. data = dict from API request."""
    t0 = time.time()
    products = data.get('products', [])
    params = data.get('params', {})
    cap_mode = data.get('capacity_mode', 'parallel')  # shared or parallel

    T = params.get('periods', 52)  # weekly periods
    carry_rate = params.get('carry_rate', 0.24)
    wh_max = params.get('wh_max', 5000)
    fixed_daily = params.get('fixed_daily', 0)
    bo_on = params.get('backorder_on', False)
    salvage = params.get('salvage_rate', 0.80)
    service_level = params.get('service_level', 0.95)
    budget = params.get('budget', None)  # optional budget constraint

    n_products = len(products)
    if not n_products:
        return {'error': 'No products provided'}

    z_map = {0.85: 1.036, 0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
    z = z_map.get(service_level, 1.645)

    # ── Build problem ──
    prob = pulp.LpProblem("Procurement_Optimizer", pulp.LpMinimize)

    # ── Decision variables ──
    p = {}   # production
    inv = {}  # FG inventory
    short = {}  # shortages
    y = {}   # production binary
    r = {}   # RM orders
    o = {}   # RM order binary
    rm_inv = {}  # RM inventory

    all_parts = []
    part_map = {}  # (product_idx, part_idx) -> global part index

    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)
        while len(demand) < T:
            demand.append(demand[-1] if demand else 0)
        demand = demand[:T]

        cap = prod.get('capacity', 50)
        setup_cost = prod.get('setup_cost', 50)
        var_cost = prod.get('variable_cost', 0)
        shelf = prod.get('shelf_life', T)
        sell_price = prod.get('sell_price', 10)
        fy = prod.get('yield_pct', 0.95)
        short_penalty = sell_price * 1.5  # lost margin + goodwill

        # Safety stock
        demand_arr = np.array(demand, dtype=float)
        avg_d = max(demand_arr.mean(), 0.1)
        std_d = max(demand_arr.std(), 0.1)
        ss = max(1, round(z * std_d))

        for t in range(T):
            p[k, t] = pulp.LpVariable(f'p_{k}_{t}', 0, cap, cat='Integer')
            inv[k, t] = pulp.LpVariable(f'inv_{k}_{t}', 0)
            short[k, t] = pulp.LpVariable(f'short_{k}_{t}', 0)
            y[k, t] = pulp.LpVariable(f'y_{k}_{t}', cat='Binary')

        # BOM parts
        parts = prod.get('parts', [])
        for i, part in enumerate(parts):
            gidx = len(all_parts)
            part_map[(k, i)] = gidx
            all_parts.append({
                'name': part.get('name', f'Part_{k}_{i}'),
                'cost': part.get('cost', 1.0),
                'qty_per': part.get('qty_per', 1.0),
                'lt': part.get('lead_time', 1),
                'moq': part.get('moq', 1),
                'max_order': part.get('max_order', 9999),
                'hold_pct': part.get('hold_pct', carry_rate * 100),
                'rm_cap': part.get('rm_capacity', 9999),
                'ord_cost': part.get('ordering_cost', 50),
                'rm_shelf': part.get('rm_shelf', T),
                'product_k': k,
                'part_i': i,
                'scrap': part.get('scrap_factor', 0),
                'vol_disc': part.get('vol_disc', []),
                'trans_tiers': part.get('trans_tiers', []),
                'trans_rate': part.get('trans_rate', 0.0),
                'pay_term_days': part.get('pay_term_days', 30),
                'early_pay_disc': part.get('early_pay_disc', 0),
                'proc_policy': (part.get('proc_policy') or 'milp').lower(),
            })

            for t in range(T):
                r[gidx, t] = pulp.LpVariable(f'r_{gidx}_{t}', 0, cat='Integer')
                o[gidx, t] = pulp.LpVariable(f'o_{gidx}_{t}', cat='Binary')
                rm_inv[gidx, t] = pulp.LpVariable(f'rminv_{gidx}_{t}', 0)

    # ── Objective function ──
    obj = []

    # Helper — expand scalar base into period-indexed series, applying cost_events.
    # Cost events are stepwise: from_month m onwards, param switches to new value.
    def _period_series(base, events, param_key, weeks_per_month=4):
        series = [base] * T
        if not events:
            return series
        ev = sorted(
            [e for e in events if e.get('param') == param_key],
            key=lambda e: e.get('from_month', 0),
        )
        for e in ev:
            fm_week = int(e.get('from_month', 0)) * weeks_per_month
            new_val = e.get('value', base)
            for t in range(fm_week, T):
                series[t] = new_val
        return series

    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)[:T]
        setup_base = prod.get('setup_cost', 50)
        vc_base = prod.get('variable_cost', 0)
        sp_base = prod.get('sell_price', 10)
        events = prod.get('cost_events', [])
        setup_series = _period_series(setup_base, events, 'setupCost')
        vc_series = _period_series(vc_base, events, 'variableCost')
        sp_series = _period_series(sp_base, events, 'sellPrice')
        shelf = prod.get('shelf_life', T)
        fy = prod.get('yield_pct', 0.95)
        unit_cost = sum(
            pt.get('cost', 1) * pt.get('qty_per', 1)
            for pt in prod.get('parts', [])
        )
        fg_hold = unit_cost * carry_rate / 52  # weekly holding cost per unit

        for t in range(T):
            # Setup cost (period-varying)
            obj.append(setup_series[t] * y[k, t])
            # Variable production cost (period-varying)
            obj.append(vc_series[t] * p[k, t])
            # FG holding
            obj.append(fg_hold * inv[k, t])
            # Shortage penalty (period-varying via sell_price events)
            obj.append(sp_series[t] * 1.5 * short[k, t])

    # RM costs — with volume discount & transport tier support via effective unit cost.
    # Strategy: for each part compute effective per-unit cost at the MAX applicable tier
    # (assumes solver will tend toward larger batches when discount dominates holding).
    # For piecewise-linear exact MILP discount modelling, we use tier-indicator binaries.
    tier_indicators = {}  # (gidx,t,tier_i) -> binary
    for gidx, part in enumerate(all_parts):
        base_cost = part['cost']
        tiers = sorted(part.get('vol_disc', []) or [], key=lambda x: x.get('minQty', 0))
        trans_tiers = sorted(part.get('trans_tiers', []) or [], key=lambda x: x.get('minQty', 0))
        default_trans = part.get('trans_rate', 0.0) or 0.0
        has_vol = len(tiers) > 1
        has_trans = len(trans_tiers) > 0
        for t in range(T):
            if has_vol or has_trans:
                # Build tier break points combining both discount and transport tiers
                break_qtys = sorted(set(
                    [x.get('minQty', 0) for x in tiers]
                    + [x.get('minQty', 0) for x in trans_tiers]
                    + [0]
                ))
                # Indicator binaries: exactly one active per period
                inds = {}
                seg_costs = []
                for si, q_lo in enumerate(break_qtys):
                    q_hi = break_qtys[si + 1] if si + 1 < len(break_qtys) else None
                    # Effective unit cost at this tier
                    disc_pct = 0
                    for vd in tiers:
                        if vd.get('minQty', 0) <= q_lo:
                            disc_pct = max(disc_pct, vd.get('pct', 0))
                    eff_cost = base_cost * (1 - disc_pct / 100.0)
                    trans_rate_eff = default_trans
                    for tt in trans_tiers:
                        if tt.get('minQty', 0) <= q_lo:
                            trans_rate_eff = tt.get('rate', default_trans)
                    seg_costs.append((q_lo, q_hi, eff_cost + trans_rate_eff))
                    inds[si] = pulp.LpVariable(f'tier_{gidx}_{t}_{si}', cat='Binary')
                tier_indicators[(gidx, t)] = inds
                # Exactly one segment active when ordering; zero if not ordering
                prob += pulp.lpSum(inds[si] for si in inds) == o[gidx, t], \
                    f"TierOne_{gidx}_{t}"
                # Force r within selected segment bounds
                M = part.get('max_order', 9999)
                for si, (q_lo, q_hi, _) in enumerate(seg_costs):
                    prob += r[gidx, t] >= q_lo * inds[si], f"TierLo_{gidx}_{t}_{si}"
                    if q_hi is not None:
                        prob += r[gidx, t] <= q_hi * inds[si] + M * (1 - inds[si]), \
                            f"TierHi_{gidx}_{t}_{si}"
                # Cost contribution: sum of (segment_cost × qty × ind) — linearize via
                # auxiliary: r_seg[si] = r * ind[si]. To keep linear, approximate with
                # segment cost × minQty as baseline plus marginal at that tier rate.
                # Simplification: weight each segment's effective rate by indicator × r cap.
                # Since r is bounded by max_order, we use effective cost of the binding tier:
                # total = sum(seg_cost[si] × inds[si] × r[t]) — nonlinear; use McCormick/big-M
                # Introduce auxiliary r_seg ≥ 0, r_seg ≤ M*ind, r_seg ≤ r, r_seg ≥ r - M*(1-ind)
                for si, (q_lo, q_hi, eff_rate) in enumerate(seg_costs):
                    r_seg = pulp.LpVariable(f'rseg_{gidx}_{t}_{si}', 0, M)
                    prob += r_seg <= M * inds[si], f"RsegUB1_{gidx}_{t}_{si}"
                    prob += r_seg <= r[gidx, t], f"RsegUB2_{gidx}_{t}_{si}"
                    prob += r_seg >= r[gidx, t] - M * (1 - inds[si]), f"RsegLB_{gidx}_{t}_{si}"
                    obj.append(eff_rate * r_seg)
            else:
                # No tiers — base cost + simple per-unit transport
                obj.append((base_cost + default_trans) * r[gidx, t])
            # Ordering admin cost
            obj.append(part['ord_cost'] * o[gidx, t])
            # RM holding (use base cost as proxy for holding valuation)
            rm_hold = base_cost * (part['hold_pct'] / 100) / 52
            obj.append(rm_hold * rm_inv[gidx, t])

    # Fixed overhead
    obj.append(fixed_daily * T)

    prob += pulp.lpSum(obj), "Total_Cost"

    # ── Constraints ──

    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)[:T]
        cap = prod.get('capacity', 50)
        shelf = prod.get('shelf_life', T)
        fy = prod.get('yield_pct', 0.95)
        init_inv = prod.get('init_inventory', 0)

        demand_arr = np.array(demand, dtype=float)
        ss = max(1, round(z * max(demand_arr.std(), 0.1)))

        for t in range(T):
            d = demand[t] if t < len(demand) else demand[-1]

            # C1: Inventory balance
            prev_inv = inv[k, t - 1] if t > 0 else init_inv
            good_prod = p[k, t]  # simplified: yield applied at BOM consumption
            prob += inv[k, t] == prev_inv + good_prod - d + short[k, t], \
                f"InvBal_{k}_{t}"

            # C2: Capacity
            prob += p[k, t] <= cap * y[k, t], f"Cap_{k}_{t}"

            # C3: Min production (if producing, produce at least 1)
            prob += p[k, t] >= y[k, t], f"MinProd_{k}_{t}"

            # C4: Warehouse limit (shared across products)
            # Added below as aggregate

            # C5: No backorder if disabled
            if not bo_on:
                prob += short[k, t] == 0, f"NoBO_{k}_{t}"

    # Aggregate warehouse constraint
    for t in range(T):
        prob += pulp.lpSum(
            inv[k, t] for k in range(n_products)
        ) <= wh_max, f"WH_{t}"

    # Shared capacity constraint
    if cap_mode == 'shared':
        shared_cap = params.get('shared_capacity', 100)
        for t in range(T):
            prob += pulp.lpSum(
                p[k, t] for k in range(n_products)
            ) <= shared_cap, f"SharedCap_{t}"

    # RM constraints
    for gidx, part in enumerate(all_parts):
        k = part['product_k']
        i = part['part_i']
        prod = products[k]
        demand = prod.get('demand', [0] * T)[:T]
        lt = part['lt']
        moq = part['moq']
        max_ord = part['max_order']
        rm_cap = part['rm_cap']
        qty_per = part['qty_per']
        scrap = part['scrap']
        fy = prod.get('yield_pct', 0.95)
        effective_qty = qty_per * (1 + scrap) / max(fy, 0.01)
        # Default init RM: enough for lead_time periods of avg demand
        avg_demand_per_t = sum(demand[:T]) / T if T > 0 else 10
        default_init_rm = max(0, round(avg_demand_per_t * effective_qty * (lt + 1)))
        init_rm = part.get('init_inventory', default_init_rm)

        for t in range(T):
            # RM arrives lt periods after ordering
            arrive_t = t - lt
            arrived = r[gidx, arrive_t] if arrive_t >= 0 else 0

            # RM consumption = production * effective qty per unit
            consumed = p[k, t] * effective_qty

            prev_rm = rm_inv[gidx, t - 1] if t > 0 else init_rm
            prob += rm_inv[gidx, t] == prev_rm + arrived - consumed, \
                f"RMBal_{gidx}_{t}"

            # RM non-negative (redundant with var bounds but explicit)
            prob += rm_inv[gidx, t] >= 0, f"RMNonNeg_{gidx}_{t}"

            # MOQ: if ordering, order at least MOQ
            prob += r[gidx, t] >= moq * o[gidx, t], f"MOQ_{gidx}_{t}"
            prob += r[gidx, t] <= max_ord * o[gidx, t], f"MaxOrd_{gidx}_{t}"

            # RM warehouse capacity
            prob += rm_inv[gidx, t] <= rm_cap, f"RMCap_{gidx}_{t}"

    # Budget constraint (optional)
    if budget and budget > 0:
        prob += pulp.lpSum(
            part['cost'] * r[gidx, t]
            for gidx, part in enumerate(all_parts)
            for t in range(T)
        ) <= budget, "Budget"

    # ── Solve ──
    solver = pulp.PULP_CBC_CMD(
        msg=0,
        timeLimit=90,
        gapRel=0.02
    )
    status = prob.solve(solver)

    solve_time = time.time() - t0

    if status != pulp.constants.LpStatusOptimal:
        return {
            'status': pulp.LpStatus[status],
            'error': f'Solver returned: {pulp.LpStatus[status]}',
            'solve_time': round(solve_time, 2)
        }

    # ── Extract results ──
    total_cost = pulp.value(prob.objective)

    product_results = []
    for k, prod in enumerate(products):
        demand = prod.get('demand', [0] * T)[:T]
        prod_schedule = [int(pulp.value(p[k, t]) or 0) for t in range(T)]
        inv_levels = [round(pulp.value(inv[k, t]) or 0, 1) for t in range(T)]
        shortages = [round(pulp.value(short[k, t]) or 0, 1) for t in range(T)]
        setups = [int(pulp.value(y[k, t]) or 0) for t in range(T)]

        total_prod = sum(prod_schedule)
        total_demand = sum(demand[:T])
        total_short = sum(shortages)
        fill_rate = round((1 - total_short / max(total_demand, 1)) * 100, 1)

        product_results.append({
            'name': prod.get('name', f'Product_{k}'),
            'production': prod_schedule,
            'inventory': inv_levels,
            'shortages': shortages,
            'setups': setups,
            'total_produced': total_prod,
            'total_demand': total_demand,
            'total_shortage': round(total_short),
            'fill_rate': fill_rate,
            'num_batches': sum(setups),
        })

    material_results = []
    for gidx, part in enumerate(all_parts):
        orders = [int(pulp.value(r[gidx, t]) or 0) for t in range(T)]
        rm_levels = [round(pulp.value(rm_inv[gidx, t]) or 0, 1) for t in range(T)]
        order_flags = [int(pulp.value(o[gidx, t]) or 0) for t in range(T)]

        # Build PO list
        po_list = []
        for t in range(T):
            if orders[t] > 0:
                po_list.append({
                    'period': t,
                    'arrive_period': t + part['lt'],
                    'quantity': orders[t],
                    'cost': round(orders[t] * part['cost'], 2),
                })

        # v3.2 — compute MILP's realized per-part cost for comparison
        milp_cost = round(
            sum(orders) * part['cost']
            + sum(order_flags) * part['ord_cost']
            + sum(rm_levels) * part['cost'] * (part['hold_pct'] / 100) / 52,
            2,
        )

        # v3.2 — run alternative closed-form / heuristic policies on the part's
        # derived demand (production × qty_per × effective_qty_mult) for ranking.
        k = part['product_k']
        prod = products[k]
        fy = prod.get('yield_pct', 0.95)
        qty_per = part['qty_per']
        scrap = part['scrap']
        eff_mult = qty_per * (1 + scrap) / max(fy, 0.01)
        prod_schedule = product_results[k]['production']
        part_demand = [int(round(q * eff_mult)) for q in prod_schedule]

        lp_params = {
            'unit_cost': part['cost'],
            'ord_cost': part['ord_cost'],
            'hold_rate_annual': part['hold_pct'] / 100,
            'hold_rate_weekly': (part['hold_pct'] / 100) / 52,
            'lead_time': part['lt'],
            'z': z,
            'init_inv': 0,
            'max_shortage': 0,
        }
        alt = auto_select_policy(part_demand, lp_params)
        leaderboard = alt['leaderboard']
        # Prepend MILP for ranking visibility (flagged separately)
        leaderboard = [{
            'policy': 'milp',
            'label': 'MILP (joint solver)',
            'total_cost': milp_cost,
            'order_cost': round(sum(order_flags) * part['ord_cost'], 2),
            'hold_cost': round(
                sum(rm_levels) * part['cost'] * (part['hold_pct'] / 100) / 52,
                2,
            ),
            'num_orders': sum(order_flags),
            'shortage': 0,
            'feasible': True,
        }] + leaderboard
        leaderboard.sort(key=lambda x: (not x['feasible'], x['total_cost']))
        cheapest_policy = leaderboard[0]['policy'] if leaderboard else 'milp'

        # Honor per-part procPolicy setting
        policy_pref = part.get('proc_policy', 'milp')
        if policy_pref == 'auto':
            chosen = cheapest_policy
        elif policy_pref in ('milp', None, ''):
            chosen = 'milp'
        else:
            chosen = policy_pref

        material_results.append({
            'name': part['name'],
            'product': products[part['product_k']].get('name', ''),
            'orders': orders,
            'inventory': rm_levels,
            'purchase_orders': po_list,
            'total_ordered': sum(orders),
            'total_cost': round(sum(orders) * part['cost'], 2),
            'num_orders': sum(order_flags),
            # v3.2 additions
            'proc_policy_pref': policy_pref,
            'proc_policy_chosen': chosen,
            'cheapest_policy': cheapest_policy,
            'milp_cost': milp_cost,
            'policy_leaderboard': leaderboard,
            'winner_vs_milp_savings': round(
                milp_cost - (leaderboard[0]['total_cost'] if leaderboard else milp_cost),
                2,
            ),
        })

    # Cost breakdown
    cost_breakdown = {
        'total': round(total_cost, 2),
        'material_purchase': round(sum(
            sum(int(pulp.value(r[g, t]) or 0) * all_parts[g]['cost']
                for t in range(T))
            for g in range(len(all_parts))
        ), 2),
        'ordering_admin': round(sum(
            sum(int(pulp.value(o[g, t]) or 0) * all_parts[g]['ord_cost']
                for t in range(T))
            for g in range(len(all_parts))
        ), 2),
        'production_setup': round(sum(
            sum(int(pulp.value(y[k, t]) or 0) * products[k].get('setup_cost', 50)
                for t in range(T))
            for k in range(n_products)
        ), 2),
        'production_variable': round(sum(
            sum(int(pulp.value(p[k, t]) or 0) * products[k].get('variable_cost', 0)
                for t in range(T))
            for k in range(n_products)
        ), 2),
        'fixed_overhead': round(fixed_daily * T, 2),
    }

    return {
        'status': 'Optimal',
        'total_cost': round(total_cost, 2),
        'cost_breakdown': cost_breakdown,
        'products': product_results,
        'materials': material_results,
        'solve_time': round(solve_time, 2),
        'periods': T,
        'solver': 'CBC',
    }
