"""
Multi-period capital plan with endogenous capacity (GAP-5)
==========================================================
capital.py is a single-period 0/1 knapsack on hand-set NPVs at one WACC: no budget
rollover, no investment timing, and capacity options are valued by a guessed cash
flow rather than the throughput they unlock.

This module adds the three moves IMPROVEMENTS.md GAP-5 calls for:

  (a) MULTI-PERIOD timing + budget rollover. Decision invest[i,t] ∈ {0,1} picks not
      just WHICH options but WHEN, within each option's [earliest, latest] window,
      under a per-period budget whose unspent balance rolls forward
      (Σ_{τ≤t} spend ≤ Σ_{τ≤t} budget).

  (b) ENDOGENOUS CAPACITY. A 'capacity' option (a new line / shift) carries
      capacity_hours_per_period and a margin_per_hour; its annual cash flow is
      DERIVED — capacity_hours · margin_per_hour · utilization − opex — so the NPV
      is justified by the throughput it adds, not a hand-set number. margin_per_hour
      defaults to the capacity shadow price handed up from the aggregate/production
      solve (GAP-0), directly coupling capital to the binding bottleneck's value.

  (c) RISK-ADJUSTED NPV. After choosing the plan, a Monte Carlo pass perturbs the
      cash-flow drivers (margin/hour and utilization, ±CV) and recomputes the
      portfolio NPV, returning its distribution and P(NPV < 0) — so the plan is
      stress-tested, not reported as a deterministic point.
"""
import pulp
import time
import math

try:
    from .finance import _calc_irr
except ImportError:
    from finance import _calc_irr


def _annual_cf(opt, shadow_price):
    """Derive an option's recurring annual cash flow.

    Capacity options: capacity_hours · margin_per_hour · utilization − opex, where
    margin_per_hour defaults to the passed capacity shadow price (throughput value).
    Cash-flow options: the hand-set annual_cash_flow (legacy behavior).
    """
    if opt.get('type') == 'capacity':
        hrs = float(opt.get('capacity_hours_per_period', 0) or 0)
        mph = opt.get('margin_per_hour')
        mph = float(mph) if mph not in (None, '') else float(shadow_price or 0)
        util = float(opt.get('utilization', 0.85) or 0)
        opex = float(opt.get('opex_per_period', 0) or 0)
        return hrs * mph * util - opex
    return float(opt.get('annual_cash_flow', 0) or 0)


def _npv_if_invested_at(opt, t0, horizon, wacc, annual_cf):
    """Discounted NPV of investing in `opt` at period t0 over the plan horizon."""
    capex = float(opt.get('capex', 0) or 0)
    life = int(opt.get('useful_life', 10) or 10)
    residual = float(opt.get('residual_value', 0) or 0)
    npv = -capex / (1 + wacc) ** t0
    end = min(t0 + life, horizon)
    for t in range(t0 + 1, end + 1):
        cf = annual_cf
        if t == t0 + life:
            cf += residual
        npv += cf / (1 + wacc) ** t
    return npv


def solve_capital_capacity(data):
    t0_clock = time.time()
    options = data.get('investments', data.get('options', [])) or []
    params = data.get('params', {}) or {}
    n = len(options)
    if not n:
        return {'error': 'No investment options provided'}

    horizon = int(params.get('horizon_periods', 5) or 5)         # years in the plan
    wacc = float(params.get('wacc', 0.10) or 0.10)
    rollover = bool(params.get('budget_rollover', True))
    shadow_price = params.get('capacity_shadow_price', 0)        # GAP-0 hook (₹ / hr of capacity)
    # Per-period budget: a list, or a scalar applied each period.
    bud = params.get('budget_per_period', params.get('budget', 1000000))
    if isinstance(bud, (list, tuple)):
        budget_t = [float(bud[t]) if t < len(bud) else 0.0 for t in range(horizon)]
    else:
        budget_t = [float(bud)] * horizon

    # Pre-compute annual cash flow + NPV(i, t0) for every option/timing pair.
    ann_cf = [_annual_cf(opt, shadow_price) for opt in options]
    npv_it = {}
    for i, opt in enumerate(options):
        e = int(opt.get('earliest_period', 0) or 0)
        l = int(opt.get('latest_period', horizon - 1))
        l = min(l, horizon - 1)
        for t in range(max(0, e), max(0, l) + 1):
            npv_it[(i, t)] = _npv_if_invested_at(opt, t, horizon, wacc, ann_cf[i])

    prob = pulp.LpProblem('Capital_Capacity', pulp.LpMaximize)
    invest = {(i, t): pulp.LpVariable(f'inv_{i}_{t}', cat='Binary') for (i, t) in npv_it}

    prob += pulp.lpSum(npv_it[(i, t)] * invest[(i, t)] for (i, t) in invest), 'Total_NPV'

    # Each option invested at most once.
    for i in range(n):
        opts_i = [invest[(i, t)] for t in range(horizon) if (i, t) in invest]
        if opts_i:
            prob += pulp.lpSum(opts_i) <= 1, f'Once_{i}'

    # Budget, with optional rollover (cumulative spend ≤ cumulative budget).
    def capex(i):
        return float(options[i].get('capex', 0) or 0)
    budget_rows = {}
    if rollover:
        for t in range(horizon):
            row = prob.addConstraint(
                pulp.lpSum(capex(i) * invest[(i, s)]
                           for (i, s) in invest if s <= t) <= sum(budget_t[:t + 1]),
                f'CumBudget_{t}')
            budget_rows[t] = f'CumBudget_{t}'
    else:
        for t in range(horizon):
            prob += pulp.lpSum(capex(i) * invest[(i, t)]
                               for (i2, s) in invest if s == t for i in [i2]) <= budget_t[t], f'Budget_{t}'
            budget_rows[t] = f'Budget_{t}'

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=20))
    if status != pulp.constants.LpStatusOptimal:
        return {'status': pulp.LpStatus[status], 'error': f'Solver: {pulp.LpStatus[status]}',
                'solve_time': round(time.time() - t0_clock, 2)}

    total_npv = pulp.value(prob.objective)
    schedule = []
    selected_plan = []   # (i, t0) chosen — used by the MC pass
    total_capex = 0.0
    capacity_added_by_period = [0.0] * horizon
    for (i, t) in invest:
        if (pulp.value(invest[(i, t)]) or 0) > 0.5:
            opt = options[i]
            selected_plan.append((i, t))
            total_capex += capex(i)
            # full cash-flow vector for transparency
            cfs = [0.0] * (horizon + 1)
            cfs[t] -= capex(i)
            life = int(opt.get('useful_life', 10) or 10)
            for y in range(t + 1, min(t + life, horizon) + 1):
                cfs[y] += ann_cf[i] + (float(opt.get('residual_value', 0) or 0) if y == t + life else 0)
            if opt.get('type') == 'capacity':
                hrs = float(opt.get('capacity_hours_per_period', 0) or 0)
                for y in range(t, horizon):
                    capacity_added_by_period[y] += hrs
            schedule.append({
                'name': opt.get('name', f'Option {i+1}'),
                'type': opt.get('type', 'cashflow'),
                'invest_period': t,
                'capex': round(capex(i), 2),
                'annual_cash_flow': round(ann_cf[i], 2),
                'npv': round(npv_it[(i, t)], 2),
                'irr': (round(_calc_irr([c for c in cfs]) * 100, 2)
                        if _calc_irr([c for c in cfs]) else None),
                'capacity_hours_per_period': float(opt.get('capacity_hours_per_period', 0) or 0) if opt.get('type') == 'capacity' else 0,
            })
    schedule.sort(key=lambda s: s['invest_period'])

    # ── (c) Risk-adjusted NPV: perturb the cash-flow drivers of the CHOSEN plan. ──
    risk = _risk_adjust(options, selected_plan, ann_cf, horizon, wacc, shadow_price,
                        n_runs=int(params.get('npv_mc_runs', 400) or 400),
                        driver_cv=float(params.get('driver_cv', 0.20) or 0.20))

    return {
        'status': 'Optimal',
        'total_npv': round(total_npv, 2),
        'total_capex': round(total_capex, 2),
        'horizon_periods': horizon,
        'wacc': wacc,
        'budget_rollover': rollover,
        'capacity_shadow_price': shadow_price,
        'schedule': schedule,
        'capacity_added_by_period': [round(c, 1) for c in capacity_added_by_period],
        'risk_adjusted_npv': risk,
        'solve_time': round(time.time() - t0_clock, 3),
    }


def _risk_adjust(options, plan, ann_cf, horizon, wacc, shadow_price, n_runs, driver_cv):
    """Monte Carlo on the chosen plan: perturb margin/hour & utilization (±CV) and
    recompute portfolio NPV. Returns mean/P10/P90 and P(NPV<0)."""
    if not plan:
        return {'mean': 0, 'p10': 0, 'p90': 0, 'prob_negative': 0, 'n_runs': 0}
    import numpy as np
    rng = np.random.default_rng(42)
    npvs = []
    for _ in range(n_runs):
        total = 0.0
        for (i, t0) in plan:
            opt = options[i]
            if opt.get('type') == 'capacity':
                hrs = float(opt.get('capacity_hours_per_period', 0) or 0)
                mph = opt.get('margin_per_hour')
                mph = float(mph) if mph not in (None, '') else float(shadow_price or 0)
                util = float(opt.get('utilization', 0.85) or 0)
                mph_s = max(0.0, mph * (1 + driver_cv * rng.standard_normal()))
                util_s = min(1.0, max(0.0, util * (1 + driver_cv * rng.standard_normal())))
                opex = float(opt.get('opex_per_period', 0) or 0)
                cf = hrs * mph_s * util_s - opex
            else:
                base = ann_cf[i]
                cf = base * (1 + driver_cv * rng.standard_normal())
            total += _npv_if_invested_at(opt, t0, horizon, wacc, cf)
        npvs.append(total)
    arr = np.array(npvs)
    return {
        'mean': round(float(arr.mean()), 2),
        'p10': round(float(np.percentile(arr, 10)), 2),
        'p90': round(float(np.percentile(arr, 90)), 2),
        'std': round(float(arr.std()), 2),
        'prob_negative': round(float((arr < 0).mean()) * 100, 1),
        'n_runs': n_runs,
    }
