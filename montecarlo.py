"""
Monte Carlo Simulation Engine
==============================
Runs N stochastic simulations of the committed plan with randomized:
  - Demand  (per-period draws ~ N(forecast, mape·forecast), truncated ≥ 0)
  - Material cost (per-part draws ~ N(landed_cost, cost_cv·cost), optionally
    bivariate-correlated with the demand shock via corr_demand_cost; Cholesky)

RK-D (lead-time lag — now MODELLED, was previously only documented away): when a
positive production/inbound lead time is supplied (`prod_lead_time`, per-product
or via params), a unit BUILT in period t is not available to serve until period
t + L, where L ~ N(prod_lead_time, prod_lead_time_cv·prod_lead_time) truncated at
0 (a fresh draw per build event). Costs are charged at BUILD time; units whose
draw lands them beyond the horizon are paid for but never serve — so a committed
plan that mis-times a build against a demand shock is penalised exactly as it
would be in execution. This is the depth fix the old "R-3" docstring deferred:
earlier the loop produced and served WITHIN the same period (no lag), and the
docstring merely *explained* that gap instead of closing it. With
prod_lead_time = 0 the legacy same-period behaviour is preserved exactly.
Demand-side / supply-LT-demand risk still also lives in the CVaR layer (cvar.py
over lead-time demand); this adds the *timing* risk to the FG simulation itself.

In 'plan' mode (auto-selected when a committed production schedule is supplied)
the simulator REPLAYS the fixed MILP schedule against the demand draws — it
reports the risk of the plan that will actually execute, not a re-derived
base-stock policy. Falls back to base-stock when no plan is passed.

Returns: cost distribution, VaR95, CVaR95, fill-rate distribution.
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

    # V4-7 — CROSS-SKU demand correlation (systemic-risk tails, 12-steps Step-9).
    # Independent per-SKU draws understate portfolio risk: when a recession (or a
    # festival season) hits, every SKU swings TOGETHER, so the plant's worst weeks
    # are far worse than √N-diversified noise suggests. Opt-in via
    # params.demand_corr_matrix (n×n over the products order — the UI builds it
    # from XYZ co-movement, the same MN-C heuristic the pooling solver uses).
    # Mechanism: pre-draw eps ~ N(0, I_(n×T)) per run and form Z = L·eps where
    # L = chol(R); each SKU's MARGINAL stays exactly N(0,1) (per-SKU stats
    # unchanged) — only the JOINT moves. Absent matrix ⇒ the legacy per-product
    # draw sequence runs untouched (byte-identical to pre-V4-7).
    corr_m = params.get('demand_corr_matrix')
    L_dd, corr_meta = None, {'active': False}
    n_prod_m = len(products)
    if corr_m and n_prod_m > 1:
        R = np.array(corr_m, dtype=float)
        if R.shape == (n_prod_m, n_prod_m):
            R = (R + R.T) / 2.0
            np.fill_diagonal(R, 1.0)
            R = np.clip(R, -0.99, 0.99)
            np.fill_diagonal(R, 1.0)
            clipped = False
            try:
                L_dd = np.linalg.cholesky(R)
            except np.linalg.LinAlgError:
                # heuristic matrices need not be PSD — eigen-clip to the nearest
                # valid correlation matrix instead of crashing the simulation
                w, V = np.linalg.eigh(R)
                R2 = V @ np.diag(np.clip(w, 1e-8, None)) @ V.T
                d = np.sqrt(np.diag(R2))
                R2 = R2 / np.outer(d, d)
                np.fill_diagonal(R2, 1.0)
                L_dd = np.linalg.cholesky(R2 + 1e-10 * np.eye(n_prod_m))
                clipped = True
            off = R[~np.eye(n_prod_m, dtype=bool)]
            corr_meta = {'active': True, 'n_skus': n_prod_m,
                         'mean_offdiag_rho': round(float(np.mean(off)), 3),
                         'max_offdiag_rho': round(float(np.max(off)), 3),
                         'psd_clipped': clipped}

    # GAP-1 (move 1) — simulate the ACTUAL plan, not a re-derived policy.
    # Historically the inner loop recomputed a base-stock target every period
    # (`target = d + ss − on_hand`), so the risk numbers described a base-stock
    # policy the procurement/production MILP never chose — optimize plan A, report
    # the risk of policy B. When the caller passes each product's committed
    # production schedule (`plan` / `production_plan`, per-period units from the
    # MILP), we now FIX production to that schedule so the distribution describes
    # the plan that will actually execute. Auto-detected; falls back to the
    # base-stock heuristic when no plan is supplied (legacy behavior preserved).
    policy = params.get('policy', 'auto')
    any_plan = any((p.get('plan') or p.get('production_plan')) for p in products)
    if policy == 'auto':
        policy = 'plan' if any_plan else 'base_stock'

    rng = np.random.default_rng(42)
    run_costs = []
    run_fills = []

    for run in range(n_runs):
        total_cost = 0
        total_demand = 0
        total_served = 0

        # V4-7 — one correlated demand z-score block per run: Z[k] is SKU k's
        # period series; rows co-move per R. None ⇒ legacy independent draws.
        z_block = (L_dd @ rng.standard_normal((n_prod_m, T))) if L_dd is not None else None

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
            # V4-7 — in cross-SKU mode the demand z comes from the correlated block
            # (marginal still N(0,1)); the demand↔cost coupling below is unchanged.
            eps_d = z_block[k] if z_block is not None else rng.standard_normal(T)
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

            # Safety stock (base-stock policy only)
            ss = max(1, round(z * max(np.std(base_demand), 0.1)))

            # GAP-1 — the committed production schedule for this product, if supplied.
            # In 'plan' mode the simulator REPLAYS this fixed schedule against the
            # stochastic demand draws instead of reacting period-by-period, so a plan
            # that under- or over-builds for a shock is penalized exactly as it would be
            # in execution.
            plan_arr = prod.get('plan') or prod.get('production_plan') or []
            use_plan = (policy == 'plan') and len(plan_arr) > 0

            # RK-D — stochastic production/inbound lead-time lag. A unit BUILT in period
            # t is received at t + L, with L ~ N(lt_mean, lt_cv·lt_mean) truncated at 0
            # (fresh draw per build). Read per-product with a params-level default; with
            # lt_mean = 0 the legacy same-period receipt is preserved exactly.
            lt_mean = max(0.0, float(prod.get('prod_lead_time', params.get('prod_lead_time', 0)) or 0))
            lt_cv = max(0.0, float(prod.get('prod_lead_time_cv', params.get('prod_lead_time_cv', 0.5)) or 0.0))

            # Simulation: replenish up to demand + SS, age cohorts, expire past shelf life.
            lots = []  # list of [qty, age_in_periods], oldest first
            arrivals = {}   # RK-D — in-transit pipeline: period_due → good units scheduled to land
            init_inv = prod.get('init_inventory', 0)
            if init_inv > 0:
                lots.append([init_inv, 0])
            cost_k = 0
            served_k = 0

            for t in range(T):
                d = demand[t]
                on_hand = sum(l[0] for l in lots)
                if use_plan:
                    # Fixed committed schedule — the plan cannot react to the demand draw.
                    prod_qty = max(0, round(plan_arr[t] if t < len(plan_arr) else 0))
                else:
                    # Base-stock policy: replenish up to demand + SS, net of on-hand AND
                    # the in-transit pipeline (RK-D — don't re-order what's already inbound).
                    pipeline = sum(arrivals.values())
                    target = d + ss - on_hand - pipeline
                    prod_qty = max(0, min(target, cap))
                good_qty = round(prod_qty * fy)

                # Costs — charged at BUILD time t (capital is committed when you produce,
                # not when the units land).
                if prod_qty > 0:
                    cost_k += setup_cost
                    cost_k += var_cost * prod_qty
                    cost_k += unit_mat_cost * prod_qty

                # RK-D — schedule the good units to land after the lead-time lag; receive
                # everything due by now. With lt_mean = 0 they land this same period (legacy).
                if good_qty > 0:
                    if lt_mean > 0:
                        draw = rng.normal(lt_mean, lt_cv * lt_mean) if lt_cv > 0 else lt_mean
                        L = max(0, int(round(draw)))
                        due = t + L
                        arrivals[due] = arrivals.get(due, 0) + good_qty
                    else:
                        lots.append([good_qty, 0])
                if arrivals:
                    for due in [k for k in arrivals if k <= t]:
                        lots.append([arrivals.pop(due), 0])

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

    # VIS-9 — service risk is a LEFT tail: the 5th-percentile fill and the mean
    # fill conditional on being in that worst-5% tail (CVaR of fill).
    fill_p5 = float(np.percentile(fills, 5))
    fill_cvar5 = float(np.mean(fills[fills <= fill_p5])) if np.any(fills <= fill_p5) else fill_p5

    return {
        'n_runs': n_runs,
        'policy_simulated': policy,  # GAP-1 — 'plan' = the committed MILP schedule; 'base_stock' = re-derived policy
        'prod_lead_time': params.get('prod_lead_time', 0),   # RK-D — production/inbound lag applied (0 = same-period legacy)
        'prod_lead_time_cv': params.get('prod_lead_time_cv', 0.5),
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
        'fill_p5': round(fill_p5, 1),          # VIS-9 — worst-5% fill threshold (left-tail VaR)
        'fill_cvar5': round(fill_cvar5, 1),    # VIS-9 — mean fill INSIDE that worst-5% tail
        # V4-7 — cross-SKU systemic-demand mode echo (active/mean ρ/PSD repair flag)
        'demand_correlation': corr_meta,
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
