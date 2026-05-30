"""
MF-34 · Grain-scaling unit tests (the MF-4 / MF-5 / MF-14 class).

Holding cost and forecast lag offsets must scale with the planning grain, not assume weekly/daily.
"""
import pytest

from montecarlo import run_montecarlo
from conftest import make_product

import forecast


def _avg_cost(periods_per_year):
    # Hold genuine surplus so holding cost is non-trivial and the per-period rate shows.
    data = {
        'params': {'periods': 8, 'periods_per_year': periods_per_year, 'service_level': 0.95,
                   'carry_rate': 0.24, 'corr_demand_cost': 0.0},
        'products': [make_product(demand=[20] * 8, shelf=99, salvage=0.8,
                                  init_inventory=80, capacity=5)],
    }
    return run_montecarlo(data, n_runs=300)['avg_cost']


def test_montecarlo_holding_scales_with_grain():
    # MF-4 — per-period holding = annual / periods_per_year. A coarser grain (fewer periods/yr)
    # charges MORE holding per period, so monthly (12) must cost > weekly (52) for held stock.
    weekly = _avg_cost(52)
    monthly = _avg_cost(12)
    assert monthly > weekly, f"holding not grain-scaled: monthly={monthly} not > weekly={weekly}"


def test_forecast_lag_offsets_are_grain_aware():
    # MF-14 — lag offsets scale with grain (monthly→(1,3,12), weekly→(1,4,season), daily→(1,7,30)).
    assert forecast._lag_offsets('monthly', 12) == (1, 3, 12)
    assert forecast._lag_offsets('weekly', 52) == (1, 4, 52)
    assert forecast._lag_offsets('daily', 7) == (1, 7, 30)


def test_forecast_runs_monthly_without_30_months_history():
    # MF-14 — a monthly series shorter than 30 periods must still forecast (lag-30 would have
    # required 30 months of history under the old daily-centric offsets).
    payload = {
        'products': [{'name': 'Y',
                      'history': [100, 110, 90, 120, 105, 115, 95, 125, 100, 110, 90, 130]}],
        'params': {'periods': 3, 'time_grain': 'monthly', 'season_length': 12},
    }
    r = forecast.run_forecast(payload)
    prods = r.get('products') or []
    assert prods and prods[0].get('leaderboard'), "monthly forecast produced no model results"
    winner = prods[0]['leaderboard'][0]
    assert len(winner['forecast']) == 3
