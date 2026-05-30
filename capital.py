"""
Capital Budget Optimizer LP
=============================
Given investment options (machines, facilities, vehicles) each with:
  - CAPEX cost
  - Annual cash flows (revenue - OPEX)
  - NPV at company WACC
  - Residual/salvage value

Maximize: total portfolio NPV
Subject to: budget constraint, mutual exclusivity, dependencies

Also handles buy-vs-lease decisions by treating each option as a
separate investment with different cash flow profiles.
"""
import pulp
import time
import math

# (Audit dedup) IRR lives in finance.py — import it rather than maintaining a copy.
try:
    from .finance import _calc_irr
except ImportError:
    from finance import _calc_irr


def solve_capital_budget(data):
    t0 = time.time()
    investments = data.get('investments', [])
    params = data.get('params', {})

    budget = params.get('budget', 1000000)
    wacc = params.get('wacc', 0.10)
    max_investments = params.get('max_investments', len(investments))

    n = len(investments)
    if not n:
        return {'error': 'No investments provided'}

    # Pre-compute NPV for each investment
    for inv in investments:
        cfs = inv.get('cash_flows', [])
        if not cfs:
            capex = inv.get('capex', 0)
            annual_cf = inv.get('annual_cash_flow', 0)
            life = inv.get('useful_life', 10)
            residual = inv.get('residual_value', 0)
            cfs = [-capex] + [annual_cf] * life
            cfs[-1] += residual
            inv['cash_flows'] = cfs

        npv = sum(cf / (1 + wacc) ** t for t, cf in enumerate(cfs))
        inv['_npv'] = npv

        # IRR
        inv['_irr'] = _calc_irr(cfs)

        # Payback
        cum = 0
        inv['_payback'] = None
        for t, cf in enumerate(cfs):
            cum += cf
            if cum >= 0:
                inv['_payback'] = t
                break

    # (Audit #15) Build the model via a factory so we can solve it twice:
    #   - as a 0/1 IP (the actual select/reject decision), and
    #   - as its LP relaxation (continuous x ∈ [0,1]) to read a *valid* budget dual.
    # CBC's `.pi` on the integer program is NOT a valid sensitivity (it reflects the
    # final-node relaxation), so the budget shadow price is taken from the relaxation
    # and labelled as such.
    exclusivity = data.get('exclusivity_groups', [])
    dependencies = data.get('dependencies', [])

    def _build_model(var_cat):
        m = pulp.LpProblem("Capital_Budget", pulp.LpMaximize)
        xv = {i: pulp.LpVariable(f'x_{i}', lowBound=0, upBound=1, cat=var_cat) for i in range(n)}
        m += pulp.lpSum(investments[i]['_npv'] * xv[i] for i in range(n))
        m += pulp.lpSum(
            investments[i].get('capex', abs(investments[i]['cash_flows'][0])) * xv[i]
            for i in range(n)
        ) <= budget, "Budget"
        m += pulp.lpSum(xv[i] for i in range(n)) <= max_investments, "MaxCount"
        for gi, group in enumerate(exclusivity):
            indices = group.get('indices', [])
            m += pulp.lpSum(xv[i] for i in indices if i < n) <= 1, f"Excl_{gi}"
        for di, dep in enumerate(dependencies):
            requires = dep.get('requires', 0)
            dependent = dep.get('dependent', 0)
            if requires < n and dependent < n:
                m += xv[dependent] <= xv[requires], f"Dep_{di}"
        return m, xv

    prob, x = _build_model('Binary')
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=15)
    status = prob.solve(solver)
    solve_time = time.time() - t0

    if status != pulp.constants.LpStatusOptimal:
        return {'status': pulp.LpStatus[status], 'error': f'Solver: {pulp.LpStatus[status]}',
                'solve_time': round(solve_time, 2)}

    total_npv = pulp.value(prob.objective)
    total_capex = 0
    selected = []
    rejected = []

    for i in range(n):
        inv = investments[i]
        sel = int(pulp.value(x[i]) or 0)
        capex = inv.get('capex', abs(inv['cash_flows'][0]))
        entry = {
            'name': inv.get('name', f'Investment {i+1}'),
            'capex': capex,
            'npv': round(inv['_npv'], 2),
            'irr': round(inv['_irr'] * 100, 2) if inv['_irr'] else None,
            'payback': inv['_payback'],
            'profitability_index': round(inv['_npv'] / capex + 1, 3) if capex > 0 else None,
            'selected': bool(sel),
        }
        if sel:
            selected.append(entry)
            total_capex += capex
        else:
            rejected.append(entry)

    # (Audit #15) Budget shadow price from the LP RELAXATION, not the IP.
    # Re-solve with continuous x to obtain a meaningful dual (marginal NPV per extra ₹
    # of budget). Slack is reported from the actual integer solution (the real spend gap).
    budget_constraint_ip = prob.constraints.get("Budget")
    budget_slack = round(budget_constraint_ip.slack, 2) if budget_constraint_ip and hasattr(budget_constraint_ip, 'slack') else None
    budget_shadow = 0
    try:
        prob_lp, _ = _build_model('Continuous')
        prob_lp.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=15))
        bc_lp = prob_lp.constraints.get("Budget")
        if bc_lp is not None and getattr(bc_lp, 'pi', None) is not None:
            budget_shadow = round(bc_lp.pi, 4)
    except Exception:
        budget_shadow = 0

    return {
        'status': 'Optimal',
        'total_npv': round(total_npv, 2),
        'total_capex': round(total_capex, 2),
        'budget': budget,
        'budget_utilization': round(total_capex / max(budget, 1) * 100, 1),
        'budget_shadow_price': budget_shadow,
        'budget_shadow_price_basis': 'lp_relaxation',  # (Audit #15) IP duals are invalid; this is the relaxation dual
        'budget_slack': budget_slack,
        'selected': selected,
        'rejected': rejected,
        'solve_time': round(solve_time, 2),
    }
