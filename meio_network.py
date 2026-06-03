"""
Network MEIO — multi-product risk pooling on shared parts (W8 · Inventory L4)
=============================================================================
meio.py places safety stock optimally WITHIN one FG assembly tree (Graves–Willems
guaranteed service). But TPAC's finished SKUs share raw/component parts: the same
chromoly bar, bearing billet, seal ring and bolt feed several FGs. Solving each FG
tree in isolation buffers that shared part once PER tree — it ignores statistical
risk pooling, the single biggest multi-echelon-network lever (the L4 gap named in
the W2 review, SS-C).

The consolidation / square-root law: if a part's demand comes from N finished SKUs
with per-period component-demand std σ₁…σ_N, then

  • DECENTRALISED (a separate buffer per SKU, or per assembly tree):
        SS_dec = Σ_i  z · σ_i · √τ
  • POOLED (ONE buffer at the shared upstream node serving all N):
        σ_pool = √( Σ_i σ_i²  +  2ρ · Σ_{i<j} σ_i σ_j )
        SS_pool = z · σ_pool · √τ

Because σ_pool ≤ Σ σ_i whenever the SKUs are not perfectly correlated (ρ < 1), a
single pooled buffer holds strictly LESS safety stock for the same service level.
The gap (SS_dec − SS_pool) is the pooling dividend; valued at the part's holding
rate it is the annual saving from centralising that part's buffer.

τ = the part's replenishment (supplier lead) time in the chosen time-unit; σ_i is
the part-level component-demand std from SKU i = (FG demand std) × (qty_per ÷ yield).

This is an exact closed-form result (no MILP needed — it IS the pooling theorem),
packaged as a NEW module so the existing solver logic stays frozen. Pooling is only
RECOMMENDED when the annual dividend clears an optional pooling_fixed_cost (the cost
of running the central buffer), so it stays an honest decision, not a free lunch.
"""
import math
from statistics import NormalDist


def _rho_ij(corr_matrix, rho, i, j):
    """MN-C — pairwise correlation ρ_ij. Use the supplied n×n matrix when present
    (real per-pair demand co-movement: correlated cohorts pool poorly, independent
    ones richly), else fall back to the single scalar ρ for every pair."""
    if corr_matrix:
        try:
            return max(-0.99, min(0.99, float(corr_matrix[i][j])))
        except (IndexError, TypeError, ValueError):
            pass
    return rho


def _part_pool(part, z, rho, default_hold):
    """Pool one shared part across its contributing finished SKUs, and (MN-B) place the
    pooled buffer at the echelon that minimises holding cost — pooling AND placement in
    one model: an upstream (raw) echelon is cheap per unit but must cover the FULL
    supplier lead time (more SS units); a downstream (finished) echelon covers only the
    short final lead time (fewer units) but each unit is dearer. The jointly-optimal
    answer is the min-holding-₹ echelon for the pooled σ."""
    pid = part.get('id') or part.get('name') or '?'
    name = part.get('name', pid)
    unit_cost = max(0.0, float(part.get('unit_cost', part.get('landed_cost', 0)) or 0))
    hold_pct = float(part.get('hold_pct', default_hold) or default_hold)
    tau = max(0.0, float(part.get('lead_time', 0) or 0))          # replenishment time
    sqrt_tau = math.sqrt(tau) if tau > 0 else 0.0
    hold_rate = unit_cost * hold_pct / 100.0                      # ₹ / unit-year
    corr_matrix = part.get('corr_matrix')                         # MN-C — optional n×n

    fgs = part.get('fgs', []) or []
    sigmas = []          # part-level component-demand std contributed by each FG
    mus = []
    contrib = []
    for f in fgs:
        qty = float(f.get('qty_per', 1) or 1)
        yld = float(f.get('yield', f.get('yield_pct', 1)) or 1) or 1.0
        scale = qty / yld if yld else qty
        mu_i = max(0.0, float(f.get('mu', 0) or 0)) * scale
        sd_i = max(0.0, float(f.get('sigma', 0) or 0)) * scale
        sigmas.append(sd_i)
        mus.append(mu_i)
        contrib.append({'fg': f.get('name', '?'), 'qty_per': qty,
                        'mu_part': round(mu_i, 2), 'sigma_part': round(sd_i, 3)})

    n = len(sigmas)
    sum_sigma = sum(sigmas)
    # pooled std with pairwise correlation ρ_ij (MN-C) — scalar ρ when no matrix given.
    var_pool = sum(s * s for s in sigmas)
    for i in range(n):
        for j in range(i + 1, n):
            var_pool += 2.0 * _rho_ij(corr_matrix, rho, i, j) * sigmas[i] * sigmas[j]
    sigma_pool = math.sqrt(max(0.0, var_pool))

    ss_dec = z * sum_sigma * sqrt_tau            # one buffer per SKU/tree, at the part node
    ss_pool = z * sigma_pool * sqrt_tau          # one shared buffer, at the part node

    # MN-B — candidate echelons to PLACE the pooled buffer. Default = the part's own
    # (raw) node, so with no echelons supplied the result is identical to before.
    echelons = part.get('echelons') or [{
        'node': part.get('node', 'raw'), 'lead_time': tau,
        'unit_cost': unit_cost, 'hold_pct': hold_pct}]
    placements = []
    for e in echelons:
        e_tau = max(0.0, float(e.get('lead_time', tau) or 0))
        e_cost = max(0.0, float(e.get('unit_cost', unit_cost) or 0))
        e_hold = float(e.get('hold_pct', hold_pct) or hold_pct)
        e_ss = z * sigma_pool * (math.sqrt(e_tau) if e_tau > 0 else 0.0)
        e_value = e_ss * e_cost
        e_holding = e_value * e_hold / 100.0
        placements.append({'node': e.get('node', '?'), 'lead_time': round(e_tau, 2),
                           'unit_cost': round(e_cost, 2), 'hold_pct': round(e_hold, 2),
                           'ss_units': round(e_ss, 1), 'ss_value': round(e_value, 0),
                           'annual_holding': round(e_holding, 0)})
    best = min(placements, key=lambda p: p['annual_holding']) if placements else None

    # pooled economics at the CHOSEN echelon (falls back to the part-node values).
    ss_pool_units = best['ss_units'] if best else round(ss_pool, 1)
    ss_pool_value = best['ss_value'] if best else round(ss_pool * unit_cost, 0)
    pooled_holding = best['annual_holding'] if best else round(ss_pool * hold_rate, 0)
    # the status-quo decentralised buffers sit at the raw node (separate per tree).
    dec_holding = ss_dec * hold_rate
    units_saved = max(0.0, ss_dec - ss_pool_units)
    annual_dividend = max(0.0, dec_holding - pooled_holding)      # pooling + placement gain
    pool_ratio = (sigma_pool / sum_sigma) if sum_sigma > 0 else 1.0

    return {
        'id': pid, 'name': name,
        'n_skus': n,
        'unit_cost': round(unit_cost, 2),
        'hold_pct': round(hold_pct, 2),
        'lead_time': round(tau, 2),
        'pooled_mu': round(sum(mus), 2),
        'sum_sigma': round(sum_sigma, 3),
        'sigma_pooled': round(sigma_pool, 3),
        'pool_ratio': round(pool_ratio, 4),          # σ_pool / Σσ  (1 = no benefit)
        'pairwise_corr': bool(corr_matrix),          # MN-C — whether a real ρ matrix was used
        'ss_decentralised': round(ss_dec, 1),
        'ss_pooled': round(ss_pool_units, 1),
        'units_saved': round(units_saved, 1),
        'ss_value_decentralised': round(ss_dec * unit_cost, 0),
        'ss_value_pooled': round(ss_pool_value, 0),
        'annual_dividend': round(annual_dividend, 0),
        'placed_at': best['node'] if best else (part.get('node', 'raw')),   # MN-B
        'placements': placements,                                            # MN-B — per-echelon detail
        'contributors': contrib,
    }


def solve_meio_network(data):
    """Risk-pool shared parts across the finished SKUs that consume them.

    data = {
      parts: [{ id, name, unit_cost|landed_cost, hold_pct, lead_time,
                fgs: [{ name, mu, sigma, qty_per, yield }] }],
      params: { service_level, correlation, pooling_fixed_cost, time_unit }
    }
    Returns per-part pooling economics + the network roll-up and a recommended
    pool list (parts whose annual dividend clears the pooling fixed cost).
    """
    params = data.get('params', {}) or {}
    service_level = float(params.get('service_level', 0.95) or 0.95)
    z = NormalDist().inv_cdf(max(0.5, min(0.9999, service_level)))
    rho = max(-0.99, min(0.99, float(params.get('correlation', 0.0) or 0.0)))
    fixed_cost = max(0.0, float(params.get('pooling_fixed_cost', 0) or 0))
    default_hold = float(params.get('default_hold_pct', 24) or 24)
    time_unit = params.get('time_unit', 'days')

    parts = data.get('parts', []) or []
    if not parts:
        return {'error': 'no shared parts supplied', 'parts': []}

    rows = []
    tot_dec_value = tot_pool_value = tot_dividend = 0.0
    recommended = []
    for p in parts:
        # only parts actually shared by ≥2 SKUs can pool; single-consumer parts are
        # reported honestly with a zero dividend (nothing to pool).
        row = _part_pool(p, z, rho, default_hold)
        row['poolable'] = row['n_skus'] >= 2
        row['recommend_pool'] = bool(row['poolable'] and row['annual_dividend'] > fixed_cost)
        if row['recommend_pool']:
            recommended.append(row['name'])
        tot_dec_value += row['ss_value_decentralised']
        tot_pool_value += row['ss_value_pooled']
        tot_dividend += row['annual_dividend'] if row['recommend_pool'] else 0.0
        rows.append(row)

    rows.sort(key=lambda r: -r['annual_dividend'])

    return {
        'parts': rows,
        'service_level': service_level,
        'z': round(z, 3),
        'correlation': rho,
        'pooling_fixed_cost': round(fixed_cost, 0),
        'time_unit': time_unit,
        'total_ss_value_decentralised': round(tot_dec_value, 0),
        'total_ss_value_pooled': round(tot_pool_value, 0),
        'total_capital_freed': round(tot_dec_value - tot_pool_value, 0),
        'total_annual_dividend': round(tot_dividend, 0),
        'recommended_pool': recommended,
        'note': ('Pooled buffer per shared part uses σ_pool = √(Σσ² + 2ρΣσᵢσⱼ) ≤ Σσ '
                 '(square-root law). Capital freed = SS value held decentralised − pooled, '
                 'at the same service level. Pooling recommended only when the annual holding '
                 'dividend clears the pooling fixed cost.'),
    }
