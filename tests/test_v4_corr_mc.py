"""
V4-7 — cross-SKU correlated Monte-Carlo (systemic-risk tails).

Contract (montecarlo.run_montecarlo):
  · params.demand_corr_matrix (n×n, products order) switches demand z-scores to
    Z = chol(R)·eps — each SKU's MARGINAL stays N(0,1), only the JOINT moves;
  · absent matrix ⇒ legacy independent draw sequence, byte-identical results;
  · non-PSD heuristic matrices are eigen-clipped to the nearest valid correlation
    matrix (psd_clipped=True), never a crash;
  · result echoes demand_correlation {active, n_skus, mean_offdiag_rho, …}.

Fixture: 4 identical flat-demand SKUs with fat mape — the portfolio's diversification
(or lack of it) is then purely the correlation structure.
"""
import numpy as np
from montecarlo import run_montecarlo


def _payload(n_skus=4, corr=None, periods=13):
    products = [{'name': f'S{i}', 'demand': [100.0] * periods, 'mape_pct': 30,
                 'capacity': 500, 'setup_cost': 0, 'variable_cost': 50,
                 'sell_price': 100, 'shelf_life': periods + 1, 'yield_pct': 1.0,
                 'salvage_rate': 0.8,
                 'parts': [{'name': 'P', 'landed_cost': 10.0, 'cost_cv': 0.05,
                            'qty_per': 1.0}]}
                for i in range(n_skus)]
    params = {'periods': periods, 'periods_per_year': 52, 'carry_rate': 0.24,
              'service_level': 0.95, 'corr_demand_cost': 0.4, 'policy': 'base_stock'}
    if corr is not None:
        params['demand_corr_matrix'] = corr
    return {'products': products, 'params': params}


def _uniform(n, rho):
    return [[1.0 if i == j else rho for j in range(n)] for i in range(n)]


def test_absent_matrix_is_legacy_and_deterministic():
    r1 = run_montecarlo(_payload(), n_runs=300)
    r2 = run_montecarlo(_payload(), n_runs=300)
    assert r1['demand_correlation'] == {'active': False}
    assert r1['avg_cost'] == r2['avg_cost'] and r1['cvar95'] == r2['cvar95']


def test_correlation_widens_the_portfolio_tail():
    # 4 SKUs at ρ=0.9: portfolio demand variance ≈ (1+3ρ)× the independent case —
    # the cost spread must widen materially while the MEAN barely moves (marginals
    # are untouched; only the joint co-movement changes).
    ind = run_montecarlo(_payload(), n_runs=400)
    cor = run_montecarlo(_payload(corr=_uniform(4, 0.9)), n_runs=400)
    assert cor['demand_correlation']['active'] is True
    assert cor['std_cost'] > ind['std_cost'] * 1.25
    assert (cor['cvar95'] - cor['avg_cost']) > (ind['cvar95'] - ind['avg_cost']) * 1.2
    assert abs(cor['avg_cost'] - ind['avg_cost']) < 0.08 * ind['avg_cost']


def test_non_psd_matrix_is_eigen_clipped_not_crashed():
    # chain ρ=0.9 with zero ends is NOT positive semi-definite (eig 1 − 0.9·√2 < 0)
    bad = [[1, .9, 0], [.9, 1, .9], [0, .9, 1]]
    r = run_montecarlo(_payload(n_skus=3, corr=bad), n_runs=200)
    dc = r['demand_correlation']
    assert dc['active'] is True and dc['psd_clipped'] is True
    assert r['avg_cost'] > 0 and r['cvar95'] >= r['var95']


def test_echo_reports_the_supplied_structure():
    r = run_montecarlo(_payload(corr=_uniform(4, 0.6)), n_runs=150)
    dc = r['demand_correlation']
    assert dc['n_skus'] == 4
    assert abs(dc['mean_offdiag_rho'] - 0.6) < 1e-9
    assert dc['psd_clipped'] is False
