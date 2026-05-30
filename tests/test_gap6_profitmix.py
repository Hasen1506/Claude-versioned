"""
GAP-6 · Profit mix — cannibalization, fixed-charge line opening, MAPE robustness.

SKUs were independent, line cost was a linear daily rate, and demand was a point
buffer. These pin the cross-elasticity coupling, the binary open decision, and the
robustness band.
"""
from profitmix import solve_profitmix


def _base():
    return {
        'planning_horizon_months': 3, 'demand_mode': 'mts',
        'products': [
            {'name': 'Premium', 'sell_price': 50, 'variable_cost': 10, 'cycle_time': 1.0,
             'history': [100] * 12, 'forecast': [100] * 3, 'mape_pct': 15,
             'parts': [{'name': 'm', 'cost': 5, 'qty_per': 1}]},
            {'name': 'Budget', 'sell_price': 30, 'variable_cost': 8, 'cycle_time': 1.0,
             'history': [100] * 12, 'forecast': [100] * 3, 'mape_pct': 15,
             'parts': [{'name': 'm', 'cost': 4, 'qty_per': 1}]},
        ],
        'constraints': {'shared_capacity': 100000},
    }


def _q(r, name):
    return next(p['quantity'] for p in r['products'] if p['name'] == name)


def test_cannibalization_lowers_substitute_ceiling():
    base = solve_profitmix(_base())
    cann = _base()
    cann['products'][1]['substitutes'] = [{'index': 0, 'rate': 0.8}]   # Premium eats Budget demand
    r = solve_profitmix(cann)
    # Budget's effective ceiling = base_ceiling − 0.8·q_Premium, so it must produce strictly less.
    assert _q(r, 'Budget') < _q(base, 'Budget')
    # binding relationship: q_Budget + 0.8·q_Premium ≈ Budget's own ceiling
    ceil_budget = next(p['demand_ceiling'] for p in r['products'] if p['name'] == 'Budget')
    assert _q(r, 'Budget') + 0.8 * _q(r, 'Premium') <= ceil_budget + 1


def test_no_substitutes_is_unchanged():
    r = solve_profitmix(_base())
    assert r['status'] == 'Optimal'
    assert r['opened_lines'] == []                 # no fixed-charge lines → stays an LP path
    assert r['robustness']['pessimistic_profit'] <= r['robustness']['expected_profit']


def test_fixed_charge_opens_cheap_line_declines_expensive():
    d = _base()
    d['lines'] = [
        {'id': 'L1', 'name': 'Line 1', 'avail_hrs_per_week': 40, 'oee': 1.0, 'fixed_open_cost': 100, 'eligible_skus': [0, 1]},
        {'id': 'L2', 'name': 'Line 2', 'avail_hrs_per_week': 40, 'oee': 1.0, 'fixed_open_cost': 500000, 'eligible_skus': [0, 1]},
    ]
    r = solve_profitmix(d)
    assert r['status'] == 'Optimal'
    opened = [l['line'] for l in r['opened_lines']]
    assert 'Line 1' in opened
    assert 'Line 2' not in opened                  # 500k fixed charge not worth opening
    assert r['fixed_open_cost_total'] == 100


def test_robustness_band_is_ordered():
    r = solve_profitmix(_base())
    rb = r['robustness']
    assert rb['pessimistic_profit'] <= rb['expected_profit'] <= rb['optimistic_profit'] + 1e-6
