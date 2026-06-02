"""
Multi-echelon safety-stock placement — Graves–Willems guaranteed-service (GAP-MEIO)
===================================================================================
policy.py is single-echelon: it slaps  ss = z·σ_LTD  on every raw material in
isolation. That double-buffers the chain and — worse — prescribes a finished-goods
buffer for expensive / specific items that should be **make-to-order**. Real
multi-echelon inventory optimisation (MEIO) decides *where* in the RM→WIP→FG chain
to hold ONE buffer, not z·σ at every node.

This module implements the classic **Graves–Willems guaranteed-service model (GSM)**
over an assembly tree:

  Each stage j has a deterministic processing time  T_j  and quotes an *outbound
  guaranteed service time*  S_j  to its customer. Its *inbound service time* is the
  worst of its suppliers' outbound times:  SI_j ≥ S_i  ∀ supplier i. The stage must
  cover, with safety stock, only its **net replenishment time**

        τ_j = SI_j + T_j − S_j            (≥ 0, integer)

  Safety stock there is  ss_j = z · σ_j · √τ_j  and costs  h_j · ss_j / yr, where
  h_j is the *cumulative* unit value at that stage (RM < WIP < FG). We minimise total
  safety-stock holding cost over the integer service times S_j, subject to a maximum
  committed service time at the demand (FG) stages.

Two behaviours fall straight out of the optimum and answer the planner's question:
  • τ_j = 0  ⇒ the stage holds NO buffer (pure pass-through). For an FG stage this is
    **make-to-order** — exactly what you want for a high-value part you never stock.
  • The optimiser pushes the buffer **upstream** (to cheap, generic RM/WIP) whenever
    holding finished value is dearer than quoting a longer lead time.

Formulation note — the only non-linearity is √τ_j. Because service times are integer,
τ_j is integer and bounded, so we represent it with a one-hot selector y[j,k] (τ_j=k)
and pre-compute the exact cost coefficient h_j·z·σ_j·√k. The result is an **exact**
MILP (no piecewise approximation), solved with CBC like every other solver here.
"""
import math
from statistics import NormalDist

import pulp


def solve_meio(data):
    """Place safety stock across an RM→WIP→FG assembly tree (guaranteed-service MEIO).

    data = {
      stages: [{ id, name, kind:'RM'|'WIP'|'FG', lead_time, unit_cost,
                 hold_pct, mu, sigma,                 # demand stats in the τ time-unit
                 max_service (FG only), suppliers:[id,...] }],
      params: { service_level, time_unit }
    }
    `unit_cost` is the *cumulative* value of one unit at that stage; `mu`/`sigma` are the
    per-time-unit demand seen at the stage (already propagated up the BOM by the caller).
    Returns {'stages':[...per node...], 'total_holding_cost', 'service_level', 'z', ...}.
    """
    stages = data.get('stages', []) or []
    params = data.get('params', {}) or {}
    if not stages:
        return {'error': 'no stages supplied', 'stages': []}

    service_level = float(params.get('service_level', 0.95) or 0.95)
    z = NormalDist().inv_cdf(max(0.5, min(0.9999, service_level)))
    time_unit = params.get('time_unit', 'days')

    by_id = {}
    for s in stages:
        sid = s.get('id')
        if sid is None:
            return {'error': 'a stage is missing an id', 'stages': []}
        by_id[sid] = {
            'id': sid,
            'name': s.get('name', sid),
            'kind': (s.get('kind') or 'WIP').upper(),
            'T': max(0, int(round(float(s.get('lead_time', 0) or 0)))),
            'cost': max(0.0, float(s.get('unit_cost', 0) or 0)),
            'hold_pct': float(s.get('hold_pct', 24) or 24),
            'mu': max(0.0, float(s.get('mu', 0) or 0)),
            'sigma': max(0.0, float(s.get('sigma', 0) or 0)),
            'max_service': s.get('max_service'),
            'suppliers': [x for x in (s.get('suppliers') or []) if x in {st.get('id') for st in stages}],
        }

    # Loose upper bound on any service / net-replenishment time: the whole chain's
    # processing time (no node ever needs to cover more than everything upstream).
    horizon = sum(n['T'] for n in by_id.values()) + max(
        [int(n['max_service']) for n in by_id.values() if n.get('max_service') is not None] or [0]
    )
    horizon = max(horizon, 1)

    prob = pulp.LpProblem("MEIO_Guaranteed_Service", pulp.LpMinimize)

    S, SI, tau, Y = {}, {}, {}, {}
    cost_terms = []
    for sid, n in by_id.items():
        S[sid] = pulp.LpVariable(f'S_{sid}', 0, horizon, cat='Integer')   # outbound service
        SI[sid] = pulp.LpVariable(f'SI_{sid}', 0, horizon, cat='Integer')  # inbound service
        tau[sid] = pulp.LpVariable(f'tau_{sid}', 0, horizon, cat='Integer')

        # SI ≥ each supplier's outbound service; SI=0 for externally-sourced (no suppliers).
        if n['suppliers']:
            for sup in n['suppliers']:
                prob += SI[sid] >= S[sup], f'inbound_{sid}_{sup}'
        else:
            prob += SI[sid] == 0, f'external_{sid}'

        # Net replenishment time the buffer must cover.
        prob += tau[sid] == SI[sid] + n['T'] - S[sid], f'netrepl_{sid}'

        # Demand (FG) stages cannot quote longer than their committed customer service.
        if n['max_service'] is not None:
            prob += S[sid] <= int(n['max_service']), f'maxsvc_{sid}'

        # One-hot selector for the integer value of tau, carrying the exact √τ cost.
        h = n['cost'] * (n['hold_pct'] / 100.0)            # annual holding $/unit
        Y[sid] = {}
        for k in range(0, horizon + 1):
            Y[sid][k] = pulp.LpVariable(f'y_{sid}_{k}', cat='Binary')
            ss_k = z * n['sigma'] * math.sqrt(k)           # safety stock if τ=k
            cost_terms.append(h * ss_k * Y[sid][k])
        prob += pulp.lpSum(Y[sid].values()) == 1, f'onehot_{sid}'
        prob += pulp.lpSum(k * Y[sid][k] for k in Y[sid]) == tau[sid], f'taulink_{sid}'

    prob += pulp.lpSum(cost_terms), 'total_safety_stock_holding'

    solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)
    status = pulp.LpStatus[prob.status]
    if status != 'Optimal':
        return {'error': f'solver status: {status}', 'stages': [], 'status': status}

    out_stages = []
    total_cost = 0.0
    total_ss_value = 0.0
    for sid, n in by_id.items():
        s_val = int(round(S[sid].value() or 0))
        si_val = int(round(SI[sid].value() or 0))
        t_val = int(round(tau[sid].value() or 0))
        h = n['cost'] * (n['hold_pct'] / 100.0)
        ss = z * n['sigma'] * math.sqrt(max(t_val, 0))
        hold_cost = h * ss
        ss_value = n['cost'] * ss
        total_cost += hold_cost
        total_ss_value += ss_value

        is_fg = n['kind'] == 'FG'
        if t_val > 0:
            role = 'BUFFER'                         # decoupling point — holds safety stock
            mode = 'make-to-stock' if is_fg else 'stock'
        else:
            role = 'PASS-THROUGH'                   # no buffer here
            mode = 'make-to-order' if is_fg else 'flow'

        out_stages.append({
            'id': sid, 'name': n['name'], 'kind': n['kind'],
            'processing_time': n['T'],
            'inbound_service': si_val,
            'outbound_service': s_val,
            'net_replenishment': t_val,
            'unit_cost': round(n['cost'], 2),
            'demand_mu': round(n['mu'], 3),
            'demand_sigma': round(n['sigma'], 3),
            'safety_stock': round(ss, 1),
            'safety_stock_value': round(ss_value, 0),
            'annual_holding_cost': round(hold_cost, 0),
            'is_decoupling_point': t_val > 0,
            'role': role,
            'mode': mode,
            'suppliers': n['suppliers'],
        })

    # Order the readout the way a planner reads the chain: RM → WIP → FG.
    kind_rank = {'RM': 0, 'WIP': 1, 'FG': 2}
    out_stages.sort(key=lambda s: (kind_rank.get(s['kind'], 1), -s['annual_holding_cost']))

    decoupling = [s['id'] for s in out_stages if s['is_decoupling_point']]
    mto_fg = [s['name'] for s in out_stages if s['kind'] == 'FG' and s['mode'] == 'make-to-order']

    return {
        'stages': out_stages,
        'total_holding_cost': round(total_cost, 0),
        'total_safety_stock_value': round(total_ss_value, 0),
        'decoupling_points': decoupling,
        'make_to_order_fg': mto_fg,
        'service_level': service_level,
        'z': round(z, 3),
        'time_unit': time_unit,
        'status': status,
        'note': 'Buffer sits only at stages with net_replenishment > 0 (decoupling points). '
                'An FG stage with net_replenishment = 0 is make-to-order — no finished buffer; '
                'its committed service time equals the full upstream lead it passes through.',
    }
