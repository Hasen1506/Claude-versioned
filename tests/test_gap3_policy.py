"""
GAP-3 · Procurement emits an inventory POLICY, not just a frozen PO schedule.

Pins the textbook relationships ((s,S)/(R,Q) from EOQ + safety stock) and that
procurement now surfaces the policy on its result.
"""
import math
from policy import derive_policies
from procurement import solve_procurement
from conftest import make_product, make_part


def _payload():
    return {
        'products': [{'name': 'Widget', 'demand': [100, 120, 80, 110, 90, 130, 100, 95] * 2,
                      'yield_pct': 1.0,
                      'parts': [{'name': 'Steel', 'cost': 5, 'qty_per': 2, 'lead_time': 2,
                                 'ordering_cost': 75, 'hold_pct': 24, 'lt_cv': 0.1}]}],
        'params': {'periods': 16, 'time_grain': 'weekly', 'service_level': 0.95, 'carry_rate': 0.24},
    }


def test_eoq_matches_closed_form():
    r = derive_policies(_payload())
    steel = next(p for p in r['policies'] if p['part'] == 'Steel')
    D, K, h = steel['annual_demand'], steel['ordering_cost'], steel['annual_holding_per_unit']
    expected_eoq = math.sqrt(2 * D * K / h)
    assert abs(steel['eoq'] - expected_eoq) <= max(1.0, 0.01 * expected_eoq)


def test_order_up_to_is_reorder_plus_eoq():
    steel = derive_policies(_payload())['policies'][0]
    assert abs(steel['order_up_to_S'] - (steel['reorder_point_s'] + steel['eoq'])) < 0.5


def test_reorder_point_covers_lead_time_demand_plus_safety():
    steel = derive_policies(_payload())['policies'][0]
    mu_L = steel['avg_period_demand'] * steel['lead_time_periods']
    assert steel['reorder_point_s'] >= mu_L          # at least mean LT demand
    assert steel['safety_stock'] > 0                  # variability ⇒ positive buffer
    assert abs(steel['reorder_point_s'] - (mu_L + steel['safety_stock'])) < 0.5


def test_higher_service_level_raises_safety_stock():
    lo = derive_policies({**_payload(), 'params': {**_payload()['params'], 'service_level': 0.80}})['policies'][0]
    hi = derive_policies({**_payload(), 'params': {**_payload()['params'], 'service_level': 0.99}})['policies'][0]
    assert hi['safety_stock'] > lo['safety_stock']


def test_lumpy_demand_recommends_continuous_review():
    # A spiky/zero-inflated series (high CV) should be flagged for (s,S) continuous review.
    data = {'products': [{'name': 'Spiky', 'demand': [0, 0, 200, 0, 0, 180, 0, 0] * 2, 'yield_pct': 1.0,
                          'parts': [{'name': 'X', 'cost': 3, 'qty_per': 1, 'lead_time': 1,
                                     'ordering_cost': 50, 'hold_pct': 24}]}],
            'params': {'periods': 16, 'time_grain': 'weekly', 'service_level': 0.95, 'carry_rate': 0.24}}
    p = derive_policies(data)['policies'][0]
    assert p['demand_cv'] > 0.5
    assert 's,S' in p['recommended_policy']


def test_procurement_surfaces_inventory_policies():
    payload = {
        'params': {'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
                   'carry_rate_annual': 0.24, 'time_grain': 'weekly'},
        'products': [make_product(demand=[40] * 8, shelf=99, init_inventory=0, capacity=300,
                                  parts=[make_part(cost=2.0)])],
    }
    r = solve_procurement(payload)
    assert r['status'] == 'Optimal'
    assert isinstance(r['inventory_policies'], list) and len(r['inventory_policies']) >= 1
    pol = r['inventory_policies'][0]
    for key in ('eoq', 'reorder_point_s', 'order_up_to_S', 'rq_order_qty', 'recommended_policy'):
        assert key in pol
