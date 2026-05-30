"""
GAP-5 · Capital ↔ capacity coupling (multi-period, endogenous capacity, risk-adjusted).

Pins that a capacity option's cash flow is DERIVED from throughput × the capacity
shadow price (not hand-set), that timing/budget-rollover actually bind, and that the
chosen NPV is risk-adjusted.
"""
from capital_capacity import solve_capital_capacity, _annual_cf


def _opts():
    return [
        {'name': 'New Line', 'type': 'capacity', 'capex': 200000, 'capacity_hours_per_period': 2000,
         'utilization': 0.85, 'opex_per_period': 10000, 'useful_life': 5, 'residual_value': 30000,
         'earliest_period': 0, 'latest_period': 3},
        {'name': 'Extra Shift', 'type': 'capacity', 'capex': 50000, 'capacity_hours_per_period': 800,
         'utilization': 0.9, 'opex_per_period': 20000, 'useful_life': 5, 'earliest_period': 1, 'latest_period': 4},
        {'name': 'WMS', 'type': 'cashflow', 'capex': 120000, 'annual_cash_flow': 40000,
         'useful_life': 6, 'earliest_period': 0, 'latest_period': 2},
    ]


def test_capacity_cash_flow_is_throughput_derived():
    # 2000 hrs × 50/hr shadow × 0.85 util − 10000 opex = 75000.
    cf = _annual_cf(_opts()[0], shadow_price=50)
    assert abs(cf - 75000) < 1e-6


def test_margin_per_hour_override_beats_shadow():
    opt = {**_opts()[0], 'margin_per_hour': 100}
    cf = _annual_cf(opt, shadow_price=50)  # should use 100, not 50
    assert abs(cf - (2000 * 100 * 0.85 - 10000)) < 1e-6


def test_plan_selects_positive_npv_capacity():
    r = solve_capital_capacity({'investments': _opts(),
                                'params': {'horizon_periods': 6, 'wacc': 0.10,
                                           'capacity_shadow_price': 50,
                                           'budget_per_period': 150000, 'budget_rollover': True}})
    assert r['status'] == 'Optimal'
    assert r['total_npv'] > 0
    names = [s['name'] for s in r['schedule']]
    assert 'New Line' in names                      # throughput-justified, gets picked
    assert any(s['capacity_hours_per_period'] > 0 for s in r['schedule'])


def test_tight_budget_no_rollover_drops_big_line():
    # 60k/period, no rollover → cannot afford the 200k line in any single period.
    r = solve_capital_capacity({'investments': _opts(),
                                'params': {'horizon_periods': 6, 'wacc': 0.10,
                                           'capacity_shadow_price': 50,
                                           'budget_per_period': 60000, 'budget_rollover': False}})
    assert r['status'] == 'Optimal'
    assert all(s['capex'] <= 60000 for s in r['schedule'])
    assert 'New Line' not in [s['name'] for s in r['schedule']]


def test_rollover_is_a_relaxation():
    # Rollover only ADDS feasible spending patterns (cumulative ≥ per-period budgets), so the
    # optimal NPV under rollover can never be worse than without it.
    p = {'horizon_periods': 6, 'wacc': 0.10, 'capacity_shadow_price': 50, 'budget_per_period': 90000}
    no_roll = solve_capital_capacity({'investments': _opts(), 'params': {**p, 'budget_rollover': False}})
    roll = solve_capital_capacity({'investments': _opts(), 'params': {**p, 'budget_rollover': True}})
    assert roll['total_npv'] >= no_roll['total_npv'] - 1e-6
    # and at 90k rollover the big line becomes fundable by mid-horizon (cum ≥ 200k by Y2)
    assert 'New Line' in [s['name'] for s in roll['schedule']]


def test_risk_adjusted_npv_present_and_bounded():
    r = solve_capital_capacity({'investments': _opts(),
                                'params': {'horizon_periods': 6, 'wacc': 0.10,
                                           'capacity_shadow_price': 50,
                                           'budget_per_period': 150000, 'budget_rollover': True,
                                           'driver_cv': 0.2}})
    risk = r['risk_adjusted_npv']
    assert risk['n_runs'] > 0
    assert risk['p10'] <= risk['mean'] <= risk['p90']
    assert 0 <= risk['prob_negative'] <= 100
