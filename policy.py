"""
Inventory policy derivation — (s,S) and (R,Q) per part (GAP-3)
=============================================================
Procurement returns a fixed-horizon PO schedule. Planners don't run a frozen
26-week plan — they run a reorder POLICY. This module derives, per raw material,
the classic continuous- and periodic-review policies from the cost structure and
lead-time / demand variability (Hadley–Whitin / Silver–Pyke–Peterson):

  EOQ           Q* = √(2·D·K / h)                 (annual D, order cost K, annual holding h)
  safety stock  ss = z · σ_LTD                    (z from the service level)
  reorder point s  = μ_L + ss                     (mean lead-time demand + ss)
  order-up-to   S  = s + Q*                        ⇒ continuous-review (s, S)
  (R, Q)        review every T = Q*/D years, order Q* up from the reorder point.

A recommendation flags continuous-review (s,S) for lumpy / high-variability parts
(where waiting for a review risks a stockout) and periodic-review (R,Q) for steady
movers (where batching review cycles cuts ordering effort). The resulting policy is
what a planner actually executes; the existing rolling-horizon endpoint
(/api/solve/rolling) is the re-planning validator the policy is meant to survive.
"""
import math
from statistics import NormalDist


def _stats(series):
    n = len(series)
    if n == 0:
        return 0.0, 0.0
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    return mean, math.sqrt(var)


def derive_policies(data):
    """Derive per-part (s,S) and (R,Q) policies from a procurement-shaped payload.

    data = {products:[{name, demand:[...], yield_pct, parts:[{name, cost/landed_cost,
            qty_per, lead_time, ordering_cost, hold_pct, lt_cv}]}], params:{...}}
    Returns {'policies': [...per part...], 'service_level', 'z'}.
    """
    products = data.get('products', []) or []
    params = data.get('params', {}) or {}
    time_grain = params.get('time_grain', 'weekly')
    periods_per_year = {'daily': 365, 'weekly': 52, 'monthly': 12}.get(time_grain, 52)
    carry_rate_annual = float(params.get('carry_rate', 0.24) or 0.24)
    service_level = float(params.get('service_level', 0.95) or 0.95)
    z = NormalDist().inv_cdf(max(0.5, min(0.9999, service_level)))

    T = int(params.get('periods', 0) or 0)
    if T <= 0:
        T = max((len(p.get('demand', []) or []) for p in products), default=0)

    # Aggregate per-period demand for each part across all products that consume it.
    parts = {}   # name -> accumulator
    for p in products:
        dem = [float(v) for v in (p.get('demand', []) or [])][:T]
        if not dem:
            continue
        fy = float(p.get('yield_pct', 0.95) or 0.95) or 1.0
        for part in p.get('parts', []) or []:
            nm = part.get('name', 'part')
            qty_per = float(part.get('qty_per', 1.0) or 1.0)
            acc = parts.setdefault(nm, {
                'demand': [0.0] * T,
                'cost': part.get('landed_cost') if part.get('landed_cost') is not None else part.get('cost', 1.0),
                'lead_time': float(part.get('lead_time', 1) or 1),
                'ordering_cost': float(part.get('ordering_cost', 50) or 50),
                'hold_pct': float(part.get('hold_pct', carry_rate_annual * 100) or carry_rate_annual * 100),
                'lt_cv': float(part.get('lt_cv', 0) or 0),
                'moq': float(part.get('moq', 0) or 0),
            })
            for t in range(T):
                acc['demand'][t] += dem[t] * qty_per / max(fy, 1e-6)

    policies = []
    for nm, a in parts.items():
        mu, sigma = _stats(a['demand'])
        L = max(a['lead_time'], 1e-6)
        lt_cv = a['lt_cv']
        # σ over lead time: demand variance over L periods + demand² × lead-time variance.
        sigma_ltd = math.sqrt(L * sigma ** 2 + (mu ** 2) * ((L * lt_cv) ** 2))
        mu_L = mu * L
        ss = z * sigma_ltd

        D_annual = mu * periods_per_year
        unit_cost = max(float(a['cost']), 1e-6)
        K = a['ordering_cost']
        h = unit_cost * (a['hold_pct'] / 100.0)   # annual holding cost per unit
        eoq = math.sqrt(2 * D_annual * K / h) if (D_annual > 0 and h > 0) else 0.0
        eoq = max(eoq, a['moq'])                  # respect MOQ if larger

        reorder_point = mu_L + ss                 # s
        order_up_to = reorder_point + eoq         # S
        review_periods = (eoq / mu) if mu > 1e-6 else 0.0   # T between orders, in periods

        cv = (sigma / mu) if mu > 1e-6 else 0.0
        # Lumpy / high-variability ⇒ continuous review; steady mover ⇒ periodic review.
        recommended = '(s,S) continuous' if cv > 0.5 else '(R,Q) periodic'

        policies.append({
            'part': nm,
            'avg_period_demand': round(mu, 2),
            'demand_std': round(sigma, 2),
            'demand_cv': round(cv, 3),
            'lead_time_periods': round(L, 2),
            'annual_demand': round(D_annual, 1),
            'unit_cost': round(unit_cost, 2),
            'ordering_cost': round(K, 2),
            'annual_holding_per_unit': round(h, 3),
            'eoq': round(eoq, 1),
            'safety_stock': round(ss, 1),
            'reorder_point_s': round(reorder_point, 1),
            'order_up_to_S': round(order_up_to, 1),
            'rq_reorder_point': round(reorder_point, 1),
            'rq_order_qty': round(eoq, 1),
            'review_period_periods': round(review_periods, 2),
            'orders_per_year': round((D_annual / eoq) if eoq > 0 else 0, 1),
            'recommended_policy': recommended,
        })

    policies.sort(key=lambda p: p['annual_demand'] * p['unit_cost'], reverse=True)
    return {
        'policies': policies,
        'service_level': service_level,
        'z': round(z, 3),
        'periods_per_year': periods_per_year,
        'note': 'Validate by rolling-horizon re-solve (/api/solve/rolling): a good policy keeps '
                'nervousness low as the forecast tail is revealed.',
    }
