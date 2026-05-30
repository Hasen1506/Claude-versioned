"""
CVaR optimization — Rockafellar–Uryasev linear formulation (PuLP / CBC)
=======================================================================
GAP-1 move 2 (IMPROVEMENTS.md): the risk model was descriptive (Monte Carlo
reports CVaR but it never enters any optimization). This module makes a decision
robust BY CONSTRUCTION instead of optimize-then-check.

Rockafellar–Uryasev (2000): for loss L(x,ξ) and confidence β,

    CVaR_β(x) = min_α  α + 1/((1−β)·S) · Σ_s [ L(x,ξ_s) − α ]^+

The inner [·]^+ linearizes with z_s ≥ L_s − α, z_s ≥ 0, so minimizing CVaR over the
decision x is a single LP. Here the decision is a single-period order-up-to level Q
for a newsvendor whose per-unit overage (holding) cost is h and underage (shortage)
cost is p:

    L_s(Q) = h·[Q − d_s]^+ + p·[d_s − Q]^+

with the two [·]^+ each linearized by an overage var o_s and underage var u_s. The
result Q* is the CVaR-β-optimal stocking level; (Q* − E[d]) is a CVaR-robust safety
stock that procurement holds as a floor (see procurement.py, ss_source='cvar'),
making the resulting PO plan robust to the β-tail of demand rather than only the mean.
"""
import pulp
import math
from statistics import NormalDist


def cvar_newsvendor(scenarios, holding_cost, shortage_cost, beta=0.95, q_max=None):
    """CVaR-β-optimal order-up-to level over equiprobable demand scenarios.

    scenarios       : list of demand draws (lead-time demand, equiprobable)
    holding_cost    : per-unit cost of a leftover unit (overage)
    shortage_cost   : per-unit cost of an unmet unit (underage)
    beta            : tail confidence (0.95 → average over worst 5% of outcomes)
    Returns: {order_up_to, cvar, var (the optimal α), expected_loss, beta}
    """
    S = len(scenarios)
    if S == 0:
        return {'order_up_to': 0.0, 'cvar': 0.0, 'var': 0.0, 'expected_loss': 0.0, 'beta': beta}
    beta = min(max(float(beta), 0.0), 0.999)
    h = max(float(holding_cost), 0.0)
    p = max(float(shortage_cost), 0.0)
    if q_max is None:
        q_max = max(scenarios) * 2 + 1

    prob = pulp.LpProblem('CVaR_Newsvendor', pulp.LpMinimize)
    Q = pulp.LpVariable('Q', 0, q_max)
    alpha = pulp.LpVariable('alpha')          # VaR level (free)
    o = {s: pulp.LpVariable(f'o_{s}', 0) for s in range(S)}  # overage  [Q − d]^+
    u = {s: pulp.LpVariable(f'u_{s}', 0) for s in range(S)}  # underage [d − Q]^+
    z = {s: pulp.LpVariable(f'z_{s}', 0) for s in range(S)}  # [L_s − α]^+

    coeff = 1.0 / ((1.0 - beta) * S) if beta < 1.0 else 1.0 / S
    prob += alpha + coeff * pulp.lpSum(z[s] for s in range(S)), 'CVaR'

    for s, d in enumerate(scenarios):
        prob += o[s] >= Q - d, f'Over_{s}'
        prob += u[s] >= d - Q, f'Under_{s}'
        prob += z[s] >= (h * o[s] + p * u[s]) - alpha, f'Tail_{s}'

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    q_star = pulp.value(Q) or 0.0
    cvar = pulp.value(prob.objective) or 0.0
    var = pulp.value(alpha) or 0.0
    # Expected loss at Q* (for the risk/return frontier display).
    exp_loss = sum(h * max(q_star - d, 0) + p * max(d - q_star, 0) for d in scenarios) / S
    return {
        'order_up_to': round(q_star, 2),
        'cvar': round(cvar, 2),
        'var': round(var, 2),
        'expected_loss': round(exp_loss, 2),
        'beta': beta,
    }


def cvar_safety_stock(mean_demand, std_demand, holding_cost, shortage_cost,
                      beta=0.95, n_scenarios=200, seed=42):
    """CVaR-robust safety stock from demand statistics.

    Samples n_scenarios lead-time-demand draws ~ N(mean, std) (truncated at 0),
    solves the R–U CVaR newsvendor, and returns the safety stock implied by the
    CVaR-optimal order-up-to level: ss = max(0, Q* − mean_demand).
    """
    import numpy as np
    mean_demand = max(float(mean_demand), 0.0)
    std_demand = max(float(std_demand), 1e-6)
    rng = np.random.default_rng(seed)
    draws = rng.normal(mean_demand, std_demand, n_scenarios)
    draws = [max(0.0, float(x)) for x in draws]
    res = cvar_newsvendor(draws, holding_cost, shortage_cost, beta=beta)
    ss = max(0.0, res['order_up_to'] - mean_demand)
    res['safety_stock'] = round(ss, 2)
    res['mean_demand'] = round(mean_demand, 2)
    return res


def solve_cvar(data):
    """Endpoint wrapper. Two call shapes:
       scenarios:  {scenarios:[...], holding_cost, shortage_cost, beta}
       stats:      {mean, std, holding_cost, shortage_cost, beta, n_scenarios}
    Also returns the expected-cost-minimizing newsvendor quantity for contrast,
    so the UI can show the risk premium CVaR pays over the expected-value plan.
    """
    holding = float(data.get('holding_cost', 1.0) or 1.0)
    shortage = float(data.get('shortage_cost', 5.0) or 5.0)
    beta = float(data.get('beta', 0.95) or 0.95)
    if 'scenarios' in data and data['scenarios']:
        res = cvar_newsvendor(list(data['scenarios']), holding, shortage, beta=beta)
        mean_d = sum(data['scenarios']) / len(data['scenarios'])
        res['safety_stock'] = round(max(0.0, res['order_up_to'] - mean_d), 2)
        res['mean_demand'] = round(mean_d, 2)
    else:
        res = cvar_safety_stock(
            data.get('mean', 0), data.get('std', 1), holding, shortage,
            beta=beta, n_scenarios=int(data.get('n_scenarios', 200)),
        )
    # Expected-value (critical-ratio) newsvendor for contrast: Q_ev = μ + z·σ where
    # the critical ratio is p/(p+h). The gap Q*_CVaR − Q_ev is the robustness premium.
    cr = shortage / max(shortage + holding, 1e-9)
    z_ev = NormalDist().inv_cdf(min(max(cr, 0.001), 0.999))
    mean_d = res.get('mean_demand', 0)
    std_d = float(data.get('std', 0) or 0)
    if not std_d and 'scenarios' in data and data['scenarios']:
        m = mean_d
        std_d = math.sqrt(sum((x - m) ** 2 for x in data['scenarios']) / len(data['scenarios']))
    q_ev = mean_d + z_ev * std_d
    res['critical_ratio'] = round(cr, 4)
    res['expected_value_order_up_to'] = round(q_ev, 2)
    res['robustness_premium_units'] = round(res['order_up_to'] - q_ev, 2)
    return res
