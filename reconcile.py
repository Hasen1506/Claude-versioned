"""
Closed-loop S&OP reconciliation (GAP-2)
=======================================
The pipeline (app.py /api/solve/pipeline) ran strictly forward — profit → disaggregate
→ procure → produce — and production results never revised the mix. Demand also entered
each solver independently, so the four solvers could silently disagree.

This module adds the two moves IMPROVEMENTS.md GAP-2 calls for, with NO new math —
pure orchestration:

  1. ONE demand truth. `consensus_demand` picks a single per-SKU demand vector and
     stamps it onto every solver's payload, so profit-mix, procurement and production
     all plan against the same numbers. Priority: an aggregate (S&OP) plan if supplied
     (GAP-0's output), else the forecast-leaderboard consensus the caller passes, else
     each product's own forecast/demand.

  2. CLOSED LOOP. `run_sop_pipeline` runs the forward chain, then checks whether
     production could actually hit the mix quantity. Where a line is capacity-bound and
     `produced < required`, it feeds the achievable quantity back as a ceiling on the
     mix and re-solves — iterating until the plan is self-consistent (production can make
     what the mix promises) or a max-iteration budget is hit. That feedback is what turns
     a report pipeline into S&OP.
"""
try:
    from .profitmix import solve_profitmix
    from .disaggregate import disaggregate
    from .procurement import solve_procurement
    from .production import solve_production
except ImportError:
    from profitmix import solve_profitmix
    from disaggregate import disaggregate
    from procurement import solve_procurement
    from production import solve_production


def consensus_demand(data):
    """Resolve ONE per-SKU demand vector (the demand truth) and its source label.

    Returns {name: [monthly...]} keyed by product name, plus a 'source' string.
    Priority:
      'aggregate'  — data['aggregate_plan']['sku_plans'][i]['monthly_plan'] (GAP-0)
      'consensus'  — data['consensus_demand'] = {name: [...]} passed by the caller
      'forecast'   — each profit product's own 'forecast' (last resort)
    """
    agg = (data.get('aggregate_plan') or {}).get('sku_plans')
    if agg:
        return {row.get('name', f'P{i}'): list(row.get('monthly_plan', []))
                for i, row in enumerate(agg)}, 'aggregate'
    cons = data.get('consensus_demand')
    if isinstance(cons, dict) and cons:
        return {k: list(v) for k, v in cons.items()}, 'consensus'
    out = {}
    for p in data.get('profit_data', {}).get('products', []):
        out[p.get('name')] = list(p.get('forecast', []) or [])
    return out, 'forecast'


def _stamp_demand(data, demand_by_name):
    """Overwrite every solver payload's demand with the single consensus vector."""
    for p in data.get('profit_data', {}).get('products', []):
        d = demand_by_name.get(p.get('name'))
        if d:
            p['forecast'] = list(d)
            p['max_demand'] = sum(d)
    for p in data.get('procurement_data', {}).get('products', []):
        d = demand_by_name.get(p.get('name'))
        if d:
            p['demand'] = list(d)


def _production_unit_capacity(prod_data):
    """Rough total feasible output (units) across all lines over the horizon — the flat
    capacity×periods basis production.py falls back to without per-SKU cycle times. Used
    only as the feedback signal that sizes the mix ceiling; the production re-solve is the
    real feasibility check."""
    lines = prod_data.get('lines', []) or []
    T = prod_data.get('params', {}).get('periods', 12)
    return sum((l.get('capacity', 50) or 50) for l in lines) * max(T, 1)


def run_sop_pipeline(data, max_iters=3, tol=0.02):
    """Forward chain + capacity feedback loop. Returns the reconciled S&OP plan.

    data carries the same sub-payloads as /api/solve/pipeline (profit_data,
    procurement_data, production_data, calendar) plus optional 'aggregate_plan' /
    'consensus_demand'. The mix is re-solved with a tightened ceiling whenever
    production is capacity-bound below the requested quantity.
    """
    demand_by_name, demand_source = consensus_demand(data)
    _stamp_demand(data, demand_by_name)

    profit_data = data.get('profit_data', {}) or {}
    proc_data = data.get('procurement_data', {}) or {}
    prod_data = data.get('production_data', {}) or {}

    iterations = []
    caps = {}            # name -> ceiling fed back from production
    final = {}
    converged = False

    for it in range(max_iters):
        # Apply any capacity feedback as a hard mix ceiling.
        for p in profit_data.get('products', []):
            nm = p.get('name')
            if nm in caps:
                p['max_quantity'] = caps[nm]

        profit = solve_profitmix(profit_data)
        if profit.get('status') != 'Optimal':
            return {'status': profit.get('status', 'Infeasible'),
                    'error': f"Profit-mix: {profit.get('error', 'failed')}",
                    'stage': 'profit_mix', 'iterations': iterations,
                    'demand_source': demand_source}

        # Map optimal mix quantity onto production required_qty.
        qty_by_name = {pr['name']: pr.get('quantity', 0) for pr in profit.get('products', [])}
        for p in prod_data.get('products', []):
            nm = p.get('name')
            if nm in qty_by_name:
                p['required_qty'] = round(qty_by_name[nm])

        prod = solve_production(prod_data) if prod_data.get('products') else {'status': 'Skipped', 'products': []}

        # ── Capacity feedback ──
        new_caps = {}
        gaps = []
        if prod.get('status') == 'Optimal':
            # Production met the mix (C1 is a hard floor, so Optimal ⇒ required was achievable).
            # Keep a soft check in case a future build relaxes that constraint.
            for pr in prod.get('products', []):
                req, made = pr.get('required', 0), pr.get('produced', 0)
                if req > 0 and made < req * (1 - tol):
                    new_caps[pr['name']] = made
                    gaps.append({'product': pr['name'], 'required': req, 'produced': round(made, 1),
                                 'shortfall': round(req - made, 1)})
        elif prod.get('status') not in ('Skipped', None):
            # Infeasible/sub-optimal ⇒ the requested mix exceeds line capacity. Ration the mix
            # ceiling down to the achievable total (proportional), with a small buffer, and re-solve.
            total_cap = _production_unit_capacity(prod_data)
            total_req = sum(qty_by_name.values())
            if total_req > 0 and total_cap < total_req:
                scale = (total_cap / total_req) * (1 - tol)
                for nm, q in qty_by_name.items():
                    new_caps[nm] = max(0, round(q * scale))
                    gaps.append({'product': nm, 'required': round(q), 'produced': new_caps[nm],
                                 'shortfall': round(q - new_caps[nm], 1), 'capacity_bound': True})

        iterations.append({
            'iter': it + 1,
            'profit': profit.get('total_profit'),
            'mix': {k: round(v) for k, v in qty_by_name.items()},
            'gaps': gaps,
            'production_status': prod.get('status'),
        })
        final = {'profit_mix': profit, 'production': prod}

        if not gaps:
            converged = True
            break
        # Stabilized when no strictly-tighter cap appeared this round.
        if new_caps and all(caps.get(k) is not None and caps.get(k) <= v for k, v in new_caps.items()):
            break
        caps.update(new_caps)

    # Procurement on the reconciled quantities (disaggregate annual mix → periodic demand).
    profit = final.get('profit_mix', {})
    if profit.get('status') == 'Optimal' and proc_data.get('products'):
        calendar = data.get('calendar', {}) or {}
        disagg_input = {'products': [], 'calendar': {
            'work_days_per_week': calendar.get('work_days_per_week', 6),
            'start_month': calendar.get('start_month', 0)}}
        pmix = {pr['name']: pr.get('quantity', 0) for pr in profit.get('products', [])}
        for p in proc_data.get('products', []):
            nm = p.get('name')
            prof = p.get('demand', [])
            disagg_input['products'].append({
                'name': nm, 'annual_qty': round(pmix.get(nm, sum(prof) if prof else 0)),
                'forecast_monthly': prof[:12] if len(prof) >= 12 else prof})
        disagg = disaggregate(disagg_input)
        for k, p in enumerate(proc_data.get('products', [])):
            if k < len(disagg.get('products', [])):
                weekly = disagg['products'][k].get('weekly', [])
                T = proc_data.get('params', {}).get('periods', 26)
                p['demand'] = weekly[:T] if len(weekly) >= T else weekly + [weekly[-1] if weekly else 0] * (T - len(weekly))
        final['disaggregation'] = disagg
        final['procurement'] = solve_procurement(proc_data)

    return {
        'status': 'Optimal' if final.get('profit_mix', {}).get('status') == 'Optimal' else 'Partial',
        'demand_source': demand_source,
        'reconciled': converged,
        'iterations_run': len(iterations),
        'iterations': iterations,
        'final_gaps': iterations[-1]['gaps'] if iterations else [],
        **final,
    }
