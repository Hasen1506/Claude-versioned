"""
MF-34 · Failure-mode tests (MF-31 + the guard contract from angle B).

An over-constrained solve must report its real status, not a hardcoded 'Optimal'.
"""
from transport import solve_transport
from profitmix import solve_profitmix


def _transport(supply, demand):
    return solve_transport({
        'shipments': [{'name': 's1', 'weight_kg': 100, 'is_import': True}],
        'params': {},
        'origins': [{'name': 'A', 'supply': supply}],
        'destinations': [{'name': 'B', 'demand': demand}],
        'cost_matrix': [[1.0]],
    })


def test_transport_infeasible_allocation_not_reported_optimal():
    # MF-31 — supply (5) < demand (100): the allocation LP is infeasible. The outer status must
    # degrade to the real status instead of hardcoding 'Optimal'.
    r = _transport(supply=5, demand=100)
    assert r['allocation']['status'] != 'Optimal'
    assert r['status'] != 'Optimal', "MF-31 — outer transport status still hardcoded 'Optimal'"
    assert 'error' in r


def test_transport_feasible_allocation_is_optimal():
    # The other direction — a feasible allocation must still report Optimal cleanly.
    r = _transport(supply=200, demand=100)
    assert r['allocation']['status'] == 'Optimal'
    assert r['status'] == 'Optimal'
    assert r['allocation']['total_cost'] >= 0


def test_profitmix_runs_clean_on_feasible_input():
    # Sanity that the guard path doesn't false-positive on a well-formed problem.
    r = solve_profitmix({
        'planning_horizon_months': 3, 'demand_mode': 'mts',
        'products': [{
            'name': 'Y', 'sell_price': 12.0, 'variable_cost': 1.0,
            'history': [20] * 12, 'forecast': [20] * 3, 'cycle_time': 1.0,
            'shelf_life': 99, 'salvage_rate': 0.8, 'carry_rate': 0.24,
            'init_inventory': 0, 'max_demand': 100, 'mape_pct': 15,
            'parts': [{'name': 'm', 'cost': 2.0, 'qty_per': 1.0}],
        }],
        'constraints': {'shared_capacity': 100000},
    })
    assert r['status'] == 'Optimal'
