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
from statistics import NormalDist


def run_montecarlo(data, n_runs=500):
    t0 = time.time()
    products = data.get('products', [])
    params = data.get('params', {})

    T = params.get('periods', 52)
    carry_rate = params.get('carry_rate', 0.24)
    # (MF-4) Per-period holding grain: divide the ANNUAL carry rate by periods_per_year
    # (52 weekly / 12 monthly / 365 daily) instead of a hardcoded /52.
    periods_per_year = params.get('periods_per_year', 52)
    service_level = params.get('service_level', 0.95)
    # (MF-7) Exact inverse-normal z for ANY service level — was a 4-bucket lookup that
    # snapped every off-grid level to z=1.645 (procurement already uses inv_cdf).
    z = NormalDist().inv_cdf(min(max(float(service_level), 0.5), 0.9999))

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

            fg_hold_per = unit_mat_cost * carry_rate / max(periods_per_year, 1)
            short_penalty = sell_price * 1.5

            # (MF-1) Perishability is now REAL, not a `pass`. Inventory is tracked as FIFO/FEFO
            # cohorts [qty, age]; demand consumes oldest stock first; a lot that ages past
            # shelf_life is written off at its sunk make-cost net of salvage recovery:
            #     write-off/unit = (var_cost + material_cost) · (1 − salvage_rate)
            # so a shorter shelf life or a lower salvage value both raise simulated cost — both
            # are genuine levers now (the researcher's shelf-life sweep is no longer fabricated).
            salvage = float(prod.get('salvage_rate', 0.8) or 0.0)
            unit_made_cost = var_cost + unit_mat_cost
            writeoff_per_unit = unit_made_cost * max(0.0, 1.0 - salvage)
            shelf_eff = shelf if (shelf and shelf < T) else None  # None → no expiry within horizon

            # Safety stock
            ss = max(1, round(z * max(np.std(base_demand), 0.1)))

            # Simulation: replenish up to demand + SS, age cohorts, expire past shelf life.
            lots = []  # list of [qty, age_in_periods], oldest first
            init_inv = prod.get('init_inventory', 0)
            if init_inv > 0:
                lots.append([init_inv, 0])
            cost_k = 0
            served_k = 0

            for t in range(T):
                d = demand[t]
                on_hand = sum(l[0] for l in lots)
                # Decide production (target up to demand + SS, net of what's on hand)
                target = d + ss - on_hand
                prod_qty = max(0, min(target, cap))
                good_qty = round(prod_qty * fy)

                # Costs
                if prod_qty > 0:
                    cost_k += setup_cost
                    cost_k += var_cost * prod_qty
                    cost_k += unit_mat_cost * prod_qty

                if good_qty > 0:
                    lots.append([good_qty, 0])

                # Serve demand FEFO (oldest cohort first — uses near-expiry stock before it spoils)
                remaining = d
                for lot in lots:
                    if remaining <= 0:
                        break
                    take = min(lot[0], remaining)
                    lot[0] -= take
                    remaining -= take
                served = d - remaining
                served_k += served
                shortage = remaining

                # Age cohorts; expire anything that has now lived ≥ shelf_eff periods.
                expired_units = 0
                for lot in lots:
                    lot[1] += 1
                if shelf_eff is not None:
                    kept = []
                    for lot in lots:
                        if lot[0] <= 0:
                            continue
                        if lot[1] >= shelf_eff:
                            expired_units += lot[0]
                        else:
                            kept.append(lot)
                    lots = kept
                else:
                    lots = [l for l in lots if l[0] > 0]

                on_hand_end = sum(l[0] for l in lots)
                cost_k += fg_hold_per * on_hand_end
                cost_k += short_penalty * shortage
                cost_k += writeoff_per_unit * expired_units
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
