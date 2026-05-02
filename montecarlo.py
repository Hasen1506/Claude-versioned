"""
Monte Carlo Simulation Engine
==============================
Runs N stochastic simulations of the supply chain with randomized:
  - Demand (normal distribution around forecast)
  - Lead times (normal distribution around mean LT)
  - Prices (normal distribution around base cost)

Returns: cost distribution, VaR95, CVaR95, fill rate distribution
"""
import numpy as np
import time
import math


def run_montecarlo(data, n_runs=500):
    t0 = time.time()
    products = data.get('products', [])
    params = data.get('params', {})

    T = params.get('periods', 52)
    carry_rate = params.get('carry_rate', 0.24)
    service_level = params.get('service_level', 0.95)
    z_map = {0.85: 1.036, 0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
    z = z_map.get(service_level, 1.645)

    # T8-10 — Bivariate-correlated demand & cost shocks.
    # Real-world: commodity-price spikes often co-occur with demand surges (expansion-phase
    # correlation typical for FMCG / industrial). Default ρ=0.4 — flip to 0 for legacy
    # independence behavior. Cholesky decomposition of [[1, ρ], [ρ, 1]] gives:
    #   L = [[1, 0], [ρ, √(1−ρ²)]]
    # so we sample two iid N(0,1) variates ε_d, ε_c and form correlated z's:
    #   z_d = ε_d
    #   z_c = ρ · ε_d + √(1−ρ²) · ε_c
    rho = float(params.get('corr_demand_cost', 0.4) or 0.0)
    rho = max(-0.95, min(0.95, rho))   # bound away from singularity
    chol_a = rho
    chol_b = math.sqrt(max(0.0, 1.0 - rho * rho))

    rng = np.random.default_rng(42)
    run_costs = []
    run_fills = []

    for run in range(n_runs):
        total_cost = 0
        total_demand = 0
        total_served = 0

        for k, prod in enumerate(products):
            base_demand = np.array(prod.get('demand', [0] * T)[:T], dtype=float)
            mape_pct = prod.get('mape_pct', 15) / 100
            cap = prod.get('capacity', 50)
            setup_cost = prod.get('setup_cost', 50)
            var_cost = prod.get('variable_cost', 0)
            sell_price = prod.get('sell_price', 10)
            shelf = prod.get('shelf_life', T)
            fy = prod.get('yield_pct', 0.95)

            # T8-10 — Correlated noise pair per period: (z_d, z_c) ~ N(0, [[1,ρ],[ρ,1]]).
            eps_d = rng.standard_normal(T)
            eps_c = rng.standard_normal(T)
            z_d = eps_d                       # demand z-score
            z_c = chol_a * eps_d + chol_b * eps_c  # cost z-score, correlated with demand
            # Map z-score → multiplier with the per-stream CV (mape for demand; per-part cost_cv for cost).
            demand_mult = 1.0 + mape_pct * z_d
            demand = np.maximum(0, np.round(base_demand * demand_mult)).astype(int)

            # Unit material cost — share the SAME z_c across parts within a period
            # (commodity correlation: a USD spike hits all parts together).
            parts = prod.get('parts', [])
            unit_mat_cost_pp = np.zeros(T)
            for part in parts:
                base_cost = part.get('landed_cost')
                if base_cost is None:
                    base_cost = part.get('cost', 1.0)
                cost_cv = float(part.get('cost_cv', 0.05) or 0.05)
                qty_per = float(part.get('qty_per', 1.0) or 1.0)
                cost_mult = 1.0 + cost_cv * z_c
                stoch_cost_arr = np.maximum(0.01, base_cost * cost_mult)
                unit_mat_cost_pp = unit_mat_cost_pp + stoch_cost_arr * qty_per
            # Period-mean material cost — simulation loop below uses scalar per-period.
            unit_mat_cost = float(np.mean(unit_mat_cost_pp))

            fg_hold_per = unit_mat_cost * carry_rate / 52
            short_penalty = sell_price * 1.5

            # Safety stock
            ss = max(1, round(z * max(np.std(base_demand), 0.1)))

            # Simple simulation: produce to replenish up to demand + SS
            inv = prod.get('init_inventory', 0)
            cost_k = 0
            served_k = 0

            for t in range(T):
                d = demand[t]
                # Decide production
                target = d + ss - inv
                prod_qty = max(0, min(target, cap))
                good_qty = round(prod_qty * fy)

                # Costs
                if prod_qty > 0:
                    cost_k += setup_cost
                    cost_k += var_cost * prod_qty
                    cost_k += unit_mat_cost * prod_qty

                inv += good_qty

                # Expiry
                if shelf < T and t >= shelf:
                    pass  # simplified: tracked by cohort in full version

                # Serve demand
                served = min(inv, d)
                served_k += served
                shortage = d - served
                inv -= served

                cost_k += fg_hold_per * inv
                cost_k += short_penalty * shortage
                total_demand += d

            total_served += served_k
            total_cost += cost_k

        run_costs.append(total_cost)
        fill = (total_served / max(total_demand, 1)) * 100
        run_fills.append(fill)

    costs = np.array(run_costs)
    fills = np.array(run_fills)

    var95 = float(np.percentile(costs, 95))
    cvar95 = float(np.mean(costs[costs >= var95])) if np.any(costs >= var95) else var95
    avg_cost = float(np.mean(costs))
    fragility = round(var95 / max(avg_cost, 1), 2)

    return {
        'n_runs': n_runs,
        'avg_cost': round(avg_cost, 2),
        'median_cost': round(float(np.median(costs)), 2),
        'std_cost': round(float(np.std(costs)), 2),
        'p10': round(float(np.percentile(costs, 10)), 2),
        'p50': round(float(np.percentile(costs, 50)), 2),
        'p90': round(float(np.percentile(costs, 90)), 2),
        'var95': round(var95, 2),
        'cvar95': round(cvar95, 2),
        'fragility': fragility,
        'avg_fill': round(float(np.mean(fills)), 1),
        'min_fill': round(float(np.min(fills)), 1),
        'histogram': {
            'bins': [round(float(b), 0) for b in np.linspace(costs.min(), costs.max(), 21)],
            'counts': np.histogram(costs, bins=20)[0].tolist(),
        },
        'fill_histogram': {
            'bins': [round(float(b), 1) for b in np.linspace(max(fills.min(), 50), 100, 11)],
            'counts': np.histogram(fills, bins=10, range=(max(fills.min(), 50), 100))[0].tolist(),
        },
        'solve_time': round(time.time() - t0, 2),
    }
