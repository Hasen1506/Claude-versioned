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

    prob = pulp.LpProblem("Capital_Budget", pulp.LpMaximize)

    # Binary: select investment or not
    x = {i: pulp.LpVariable(f'x_{i}', cat='Binary') for i in range(n)}

    # Objective: maximize total NPV
    prob += pulp.lpSum(investments[i]['_npv'] * x[i] for i in range(n))

    # Budget constraint
    prob += pulp.lpSum(
        investments[i].get('capex', abs(investments[i]['cash_flows'][0])) * x[i]
        for i in range(n)
    ) <= budget, "Budget"

    # Max number of investments
    prob += pulp.lpSum(x[i] for i in range(n)) <= max_investments, "MaxCount"

    # Mutual exclusivity groups (e.g., buy Machine A OR lease Machine A, not both)
    exclusivity = data.get('exclusivity_groups', [])
    for gi, group in enumerate(exclusivity):
        indices = group.get('indices', [])
        prob += pulp.lpSum(x[i] for i in indices if i < n) <= 1, f"Excl_{gi}"

    # Dependencies (e.g., investment B requires investment A)
    dependencies = data.get('dependencies', [])
    for di, dep in enumerate(dependencies):
        requires = dep.get('requires', 0)
        dependent = dep.get('dependent', 0)
        if requires < n and dependent < n:
            prob += x[dependent] <= x[requires], f"Dep_{di}"

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

    # Budget shadow price
    budget_constraint = prob.constraints.get("Budget")
    budget_shadow = round(budget_constraint.pi, 4) if budget_constraint and hasattr(budget_constraint, 'pi') and budget_constraint.pi else 0
    budget_slack = round(budget_constraint.slack, 2) if budget_constraint and hasattr(budget_constraint, 'slack') else None

    return {
        'status': 'Optimal',
        'total_npv': round(total_npv, 2),
        'total_capex': round(total_capex, 2),
        'budget': budget,
        'budget_utilization': round(total_capex / max(budget, 1) * 100, 1),
        'budget_shadow_price': budget_shadow,
        'budget_slack': budget_slack,
        'selected': selected,
        'rejected': rejected,
        'solve_time': round(solve_time, 2),
    }


def _calc_irr(cash_flows, tol=1e-6, max_iter=200):
    if not cash_flows or len(cash_flows) < 2:
        return None
    r = 0.1
    for _ in range(max_iter):
        npv = sum(cf / (1 + r) ** t for t, cf in enumerate(cash_flows))
        dnpv = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cash_flows))
        if abs(dnpv) < 1e-12:
            break
        r_new = r - npv / dnpv
        if abs(r_new - r) < tol:
            return r_new
        r = r_new
        if abs(r) > 10:
            return None
    return r
