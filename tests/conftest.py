"""
Shared fixtures for the solver test suite (MF-34).

The solver modules are flat files at the repo root (montecarlo.py, profitmix.py, …).
Put the repo root on sys.path so `import procurement` works regardless of the pytest
invocation directory, and expose small, valid payload builders the tests share.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def make_part(cost=2.0, qty_per=1.0, lead_time=1, moq=1):
    return {
        'name': 'milk', 'cost': cost, 'qty_per': qty_per, 'lead_time': lead_time,
        'lt_cv': 0.0, 'cost_cv': 0.0, 'moq': moq, 'max_order': 5000,
        'hold_pct': 24, 'ordering_cost': 50,
    }


def make_product(name='Yogurt', demand=None, shelf=99, salvage=0.8, **kw):
    """A minimal but complete FMCG product accepted by every solver's payload contract."""
    demand = demand if demand is not None else [20] * 8
    p = {
        'name': name,
        'demand': demand,
        'history': demand,
        'forecast': demand,
        'capacity': 100,
        'setup_cost': 10,
        'variable_cost': 1.0,
        'sell_price': 12.0,
        'yield_pct': 1.0,
        'shelf_life_periods': shelf,
        'shelf_life': shelf,
        'salvage_rate': salvage,
        'init_inventory': 0,
        'demand_mode': 'mts-weekly',
        'carry_rate': 0.24,
        'parts': [make_part()],
    }
    p.update(kw)
    return p


@pytest.fixture
def procurement_payload():
    return {
        'params': {
            'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
            'carry_rate_annual': 0.24, 'salvage_rate': 0.8, 'ss_floor_mode': 'off',
            'allow_backorder': True,
        },
        'products': [make_product()],
    }


@pytest.fixture
def montecarlo_payload():
    return {
        'params': {
            'periods': 8, 'periods_per_year': 52, 'service_level': 0.95,
            'carry_rate': 0.24, 'corr_demand_cost': 0.0,
        },
        'products': [make_product()],
    }


@pytest.fixture
def profitmix_payload():
    return {
        'planning_horizon_months': 3,
        'demand_mode': 'mts',
        'products': [{
            'name': 'Yogurt', 'sell_price': 12.0, 'variable_cost': 1.0,
            'history': [20] * 12, 'forecast': [20] * 3, 'cycle_time': 1.0,
            'shelf_life': 99, 'salvage_rate': 0.8, 'carry_rate': 0.24,
            'init_inventory': 0, 'max_demand': 100, 'mape_pct': 15,
            'parts': [{'name': 'milk', 'cost': 2.0, 'qty_per': 1.0}],
        }],
        'constraints': {'shared_capacity': 100000},
    }
