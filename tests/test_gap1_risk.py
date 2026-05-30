"""
GAP-1 · Risk becomes coherent + prescriptive.

Move 1 — Monte Carlo simulates the ACTUAL committed plan when supplied, instead of
re-deriving a base-stock target (optimize plan A / report risk of policy B).
Move 2 — Rockafellar–Uryasev CVaR optimization: a robust order-up-to level that
enters the decision, and which procurement consumes as a safety-stock floor.
"""
import numpy as np
from montecarlo import run_montecarlo
from cvar import cvar_newsvendor, cvar_safety_stock
from procurement import solve_procurement
from conftest import make_product, make_part


def _mc_base(plan=None, n=300):
    prod = {'name': 'Y', 'demand': [20] * 8, 'capacity': 40, 'setup_cost': 10,
            'variable_cost': 1, 'sell_price': 12, 'shelf_life': 99, 'yield_pct': 1.0,
            'parts': [{'name': 'm', 'cost': 2, 'qty_per': 1, 'cost_cv': 0.05}],
            'mape_pct': 15, 'init_inventory': 0}
    if plan is not None:
        prod['plan'] = plan
    return run_montecarlo({'params': {'periods': 8, 'periods_per_year': 52,
                                      'service_level': 0.95, 'carry_rate': 0.24,
                                      'corr_demand_cost': 0.0},
                           'products': [prod]}, n_runs=n)


def test_mc_auto_detects_base_stock_when_no_plan():
    r = _mc_base()
    assert r['policy_simulated'] == 'base_stock'


def test_mc_simulates_committed_plan_when_supplied():
    # A fixed schedule is replayed, not re-optimized.
    r = _mc_base(plan=[20] * 8)
    assert r['policy_simulated'] == 'plan'


def test_mc_underbuild_plan_costs_more_and_fills_less():
    # The whole point of move 1 — a committed under-build plan (15 < mean 20) cannot react,
    # so it must show higher cost and a worse fill than the reactive base-stock policy.
    base = _mc_base()
    under = _mc_base(plan=[15] * 8)
    assert under['avg_cost'] > base['avg_cost']
    assert under['avg_fill'] < base['avg_fill']


def test_cvar_order_up_to_monotone_in_beta():
    # More tail-averse (higher β) ⇒ stock at least as much.
    draws = list(np.random.default_rng(1).normal(100, 20, 300))
    q50 = cvar_newsvendor(draws, 1, 20, beta=0.50)['order_up_to']
    q95 = cvar_newsvendor(draws, 1, 20, beta=0.95)['order_up_to']
    assert q95 >= q50 - 1e-6


def test_cvar_higher_shortage_cost_stocks_more():
    draws = list(np.random.default_rng(2).normal(100, 20, 300))
    lo = cvar_newsvendor(draws, holding_cost=1, shortage_cost=5, beta=0.9)['order_up_to']
    hi = cvar_newsvendor(draws, holding_cost=1, shortage_cost=50, beta=0.9)['order_up_to']
    assert hi > lo


def test_cvar_safety_stock_positive_with_variability():
    res = cvar_safety_stock(100, 25, holding_cost=1, shortage_cost=20, beta=0.95)
    assert res['safety_stock'] > 0
    assert res['order_up_to'] > res['mean_demand']


def test_procurement_cvar_source_changes_safety_stock():
    # Procurement consuming the CVaR floor must report ss_source='cvar' and a per-product level.
    payload = {
        'params': {'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
                   'carry_rate_annual': 0.24, 'ss_floor_mode': 'soft',
                   'ss_source': 'cvar', 'cvar_beta': 0.95, 'allow_backorder': True},
        'products': [make_product(demand=[30] * 8, shelf=99, init_inventory=0,
                                  capacity=200, parts=[make_part(cost=2.0)])],
    }
    r = solve_procurement(payload)
    assert r['status'] == 'Optimal'
    assert r['ss_source'] == 'cvar'
    assert r['cvar_beta'] == 0.95
    assert r['cvar_safety_stock_by_product']  # non-empty
