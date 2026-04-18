"""
Product Mix / Profit Maximizer LP — Demand-Aware
==================================================
The profit maximizer now accounts for:
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
        shelf_life_weeks = p.get('shelf_life', 52)

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

        demand_info.append({
            'ceiling': ceiling,
            'floor': floor,
            'source': source,
            'absorbable': ceiling,  # market can absorb up to this
        })

    # ── Decision variables ──
    q = {}  # production quantity
    excess = {}  # overproduction beyond absorbable demand
    for k in range(n):
        q[k] = pulp.LpVariable(f'q_{k}', 0, cat='Continuous')
        excess[k] = pulp.LpVariable(f'excess_{k}', 0, cat='Continuous')

    # ── Objective: maximize profit - holding cost on excess ──
    obj = []
    for k in range(n):
        p = products[k]
        sell = p.get('sell_price', 100)
        var_cost = p.get('variable_cost', 0)
        mat_cost = sum(
            part.get('cost', 0) * part.get('qty_per', 1)
            for part in p.get('parts', [])
        )
        margin = sell - var_cost - mat_cost
        products[k]['_margin'] = margin
        products[k]['_mat_cost'] = mat_cost

        # Revenue from units actually sold (up to demand ceiling)
        obj.append(margin * q[k])

        # Penalty for overproduction: holding cost + expiry risk
        shelf = p.get('shelf_life', 52)
        carry_rate = p.get('carry_rate', 0.24)
        unit_cost = var_cost + mat_cost
        # Holding cost on excess inventory (per unit per period)
        holding_penalty = unit_cost * carry_rate / 12  # monthly
        # If short shelf life, excess is even more costly (spoilage)
        if shelf < 12:
            spoilage_factor = 1 + (12 - shelf) / 12  # up to 2× for very short shelf
            holding_penalty *= spoilage_factor
        # Salvage recovery reduces the penalty
        salvage = p.get('salvage_rate', 0.8)
        expiry_penalty = unit_cost * (1 - salvage)

        obj.append(-holding_penalty * excess[k])  # penalize overproduction

    prob += pulp.lpSum(obj), "Total_Profit"

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

    # Shared capacity (machine-hours)
    shared_cap = constraints.get('shared_capacity', 0)
    if shared_cap > 0:
        cycle_times = [p.get('cycle_time', 1) for p in products]
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
        cycle = p.get('cycle_time', 1)
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
    if shared_cap > 0:
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

    return {
        'status': 'Optimal',
        'total_profit': round(total_profit, 2),
        'total_revenue': round(total_revenue, 2),
        'total_cost': round(total_cost, 2),
        'margin_pct': round(total_profit / max(total_revenue, 1) * 100, 1),
        'demand_mode': demand_mode,
        'products': product_results,
        'shadow_prices': shadow_prices,
        'reduced_costs': reduced_costs,
        'crossover_analysis': crossover,
        'solve_time': round(solve_time, 2),
    }
